# PR #666 (closes #663): reviewer 1's report

Reviewer 1, adversarial: Fable 5.2, 2026-11-24. I did not write the change (Opus 5.5 did). I worked only in
`review-666/`: `head/` (PR head `4b5fb24`), `base/` (`0a85b4d`), scratch copies of them, and `r1-outputs/`. No image was
built. No git repository, GitHub object or cluster was written to. The one GitHub read was `gh run view 45529793850 --log`.

## What was measured, and where

| What | Where | Result |
|---|---|---|
| `download-retry-test.py` and `ci-guard.py` on `head/` | this Mac, skopeo 1.24.1, Python 3.12.14 | exit 0 and exit 0: 17 downloads, 6 base-image checks, 94 guard checks (`retry-test-head.txt`, `ci-guard-head.txt`) |
| The same two on `base/` (base's own versions) | this Mac | exit 0 and exit 0 |
| Head's two tests on the base tree | this Mac | both exit 1: "ci.yml fetches the base images before it builds an image" FAIL; 8 guard FAILs (`head-tests-on-base-*.txt`). The implementer's "before" column is confirmed |
| CI run 45529793850 | GitHub, skopeo 1.13.3, buildx v0.39.0, BuildKit v0.35.1 | success; `images` skipped (it runs on `main` only). Each of the three bases shows `[context …] OCI load from client` in `front-door` and both `images-pr` jobs; no `[internal] load metadata` line (0 matches) |
| Experiments against the PR's own stub registry | this Mac (1.24.1), and skopeo 1.13.3 in `quay.io/skopeo/stable:v1.13.3` run with podman (pulled, not built) | `experiments-head*.txt` |
| Mutants of `base-images.py` | this Mac | `mutants-head.txt`, `mutants-fix.txt` |
| The fixed tree | this Mac and the 1.13.3 container | below |

Not tested by me: any image build, so BuildKit reading the layout is proved only by the CI run above; the `images` job; the
real registries (the implementer's run against them is not repeated).

## Findings

Seven findings: none High, two Medium, five Low. `r1-outputs/fix.diff` fixes 1 to 6. Finding 7 has its own optional patch.

### 1. Medium: an image whose manifest lists one layer twice is refused

**Where.** `head/deploy/base-images.py:164-168`. The loop goes over `[config, *layers]`, and `put_blob` moves each file out
of the `dir:` directory. skopeo's `dir:` holds one file per digest (containers/image v5.26.2 `directory_transport.go`,
`layerPath`: `filepath.Join(ref.path, digest.Encoded())`). So the second listing of a digest finds no file.

**Measured.** A stub image with one layer listed twice: exit 1, "the blob sha256:… is missing, or its size or SHA-256 does
not match", on 1.24.1 and on 1.13.3 (`experiments-head-dup.txt`, `experiments-head-skopeo-1.13.3.txt`).

**How common.** Read from the registries on 2026-11-24 with `skopeo inspect --raw` (`real-images-duplicate-layers.txt`): of
six public images sampled, three list `sha256:4f4fb700ef54…` more than once in their linux/amd64 manifest
(`tomcat:latest` 3 times, `apache/airflow:latest` twice, `sonarqube:latest` twice). The three bases pinned today list none,
which is why CI passed. A digest bump of a base to such an image would stop every image build until the script is fixed.

**Fix** (in `fetch`):

```python
    filed = set()  # A manifest may list one layer twice; dir: holds it once, and it is checked and filed once.
    for blob in [manifest["config"], *manifest["layers"]]:
        digest = checked_digest(ref, blob["digest"])
        if (digest, blob["size"]) in filed:
            continue
        path = os.path.join(work, digest.split(":", 1)[1])
        if not os.path.isfile(path) or os.path.getsize(path) != blob["size"] or sha256_file(path) != digest:
            raise Refused(f"{ref}: the blob {digest} is missing, or its size or SHA-256 does not match")
        put_blob(layout, digest, path)
        filed.add((digest, blob["size"]))
```

A second listing with another size is not in `filed`, so it still fails as missing.

**Test.** `download-retry-test.py`: "takes an image whose manifest lists one layer twice" (`stub_image(..., times=2)`).
Before: FAIL, exit 1. After: ok, exit 0, "2 layers".

### 2. Medium: a digest mismatch that skopeo reports is retried 5 times, and the test hid it

**Where.** `head/deploy/base-images.py:95`: `retried` catches every `CalledProcessError`. The script's own three checks are
final, but skopeo makes its checks first, inside the retried call: each blob in `copy`
(containers/image v5.26.2 `copy/digesting_reader.go:57`: `"Digest did not match, expected %s, got %s"`), and the manifest
(`internal/image/unparsed.go:66`: `"Manifest does not match provided manifest digest %s"`).
`head/deploy/tests/download-retry-test.py:275,279` run both refusal cases with `--attempts 1`, so they cannot see a retry.

**Measured** with the workflow's own `--attempts 5 --delay 2` (`experiments-head.txt`): a tampered layer was requested 5
times and the script took 30.9 s to exit 1. A tampered manifest on skopeo 1.24.1: 5 requests, 31.0 s. On 1.13.3 the
tampered manifest is final at once, because there `inspect --raw` does not check it and the script's own check does. So on
the runner today it is the layer case that retries.

The integrity claim itself holds: every attempt is checked, so a retry cannot let wrong bytes in. What is wrong is the
retry: the brief's rule, and the record's own sentence "a mismatch there is final", which is true only of the script's
checks. Also measured, and left as it is: a digest the registry does not have (404) is retried 5 times over 31.0 s. The
record states that cost and accepts it.

**Fix** (in `retried`, with the constant beside the others):

```python
# skopeo's own digest checks, as it words them (containers/image copy/digesting_reader.go, internal/image/unparsed.go).
MISMATCH = re.compile(r"Digest did not match|does not match provided manifest digest")
...
            if MISMATCH.search(stderr):
                raise Refused(f"{what}: not tried again: {why}") from e
```

If skopeo changes its wording, the mismatch is retried as it is today and still fails; the test below then fails and
names it.

**Test.** The two cases now run with the workflow's `--attempts`, and a third serves a tampered index. Each asserts the
registry was asked for that path once and that no "trying again" was printed. Before, on 1.24.1: three FAILs, "asked 5".
On 1.13.3 before: the layer case FAILs, the manifest and index cases pass. After: ok on both, "asked 1".

### 3. Low: an unpinned image can reach the build two ways the script does not see

**Where.** `head/deploy/base-images.py:56-58` reads only lines that start with `FROM`.

- `COPY --from=<image>` and `RUN --mount=…,from=<image>`. BuildKit v0.35.1 `frontend/dockerfile/dockerfile2llb/convert.go`
  (lines 973-978): a `--from` that is neither a number nor a stage name becomes `instructions.Stage{BaseName: c.From, …}`,
  an image that BuildKit pulls itself. No retry, no pin check, not in the layout.
- A byte-order mark before the first `FROM`. BuildKit's `parser.go` (line 319): "First line, strip the byte-order-marker if
  present". Python's `\s` does not match U+FEFF, so the script skips that line.

**Measured** (`experiments-head.txt`, pins 8 to 10): each exits 0 and prints a build context, with `ubi:latest` or
`node:latest` unseen. Neither Containerfile in the repository does this today (read: `cmapi/Containerfile`,
`cmapi-portal-ui/Containerfile`; every `--from=` names a stage, and there is no `# syntax=` line).

**Fix** (in `base_images`): `open(containerfile, encoding="utf-8-sig")`, and on every other line that is not a comment:

```python
OTHER_FROM = re.compile(r"(?:--from=|--mount=(?:\S*,)?from=)([^\s,]+)", re.IGNORECASE)
...
                    for other in OTHER_FROM.findall(line):
                        if not other.isdigit() and other.lower() not in stages:
                            raise Refused(f"{containerfile}:{n}: from={other} names an image, not a stage; only a FROM image "
                                          "is fetched and checked here, so make it a FROM stage")
```

**Test.** Three refusal cases (byte-order mark, `COPY --from=` an image, a mount from an image). Before: three FAILs, exit 0.
After: ok. The success case's Containerfile now also has `COPY --from=tools`, `COPY --from=0` and a mount from a stage, so a
false refusal would fail it. The fixed script reads both real Containerfiles to the same three images.

### 4. Low: the script's own three checks have no test that can fail, nor has TLS

**Measured** (`mutants-head.txt`, this Mac). These mutants of head pass both tests:

| Mutant | Result on head |
|---|---|
| the blob check skipped | SURVIVED |
| the copied-manifest check skipped | SURVIVED |
| the pinned-manifest check skipped | SURVIVED on 1.24.1, where skopeo's check comes first |
| all three skipped | SURVIVED |
| the script's own mismatch raised inside the retried call | SURVIVED |
| TLS off inside `skopeo()` (`--tls-verify=false`, `--src-tls-verify=false`) | SURVIVED: the guard reads the two call sites, not line 87, and the stub is plain HTTP either way |
| the platform not read: the index's first image manifest | SURVIVED: amd64 is first in the stub's index |
| the wait does not double | SURVIVED |
| no retry; the script goes on after the last attempt; `--preserve-digests` dropped; TLS off at a call site; an unpinned FROM; another digest in the context | killed |

**Is the script's own manifest check correct?** Yes. skopeo 1.13.3 `cmd/skopeo/inspect.go` writes what `src.GetManifest`
returns, and containers/image v5.26.2 `internal/image/unparsed.go:58` says: "ImageSource.GetManifest does not do digest
verification, but we do". 1.24.1 calls `unparsedInstance.Manifest(ctx)`, which checks. The script hashes the exact bytes
skopeo printed and compares them with the pin, then takes the platform image's digest only from those bytes. On the
runner's log the tampered-manifest case ends in the script's own message. The check is right; it only lacked a test that
could fail on every skopeo.

**Fix** (tests only):

- A `skopeo` put first on `PATH` that runs the real one and then adds one byte: to the output of `inspect`, to
  `manifest.json`, or to a layer file. Three cases, each must end in that check's own message.
- TLS: the same plain-HTTP stub with a `HOME` that has no `registries.conf`. The script must exit 1 with no token request
  and no content request. A script with TLS off is served, because containers/image falls back to HTTP then.
- The stub's index lists arm64 first.
- The success case asserts "trying again in 2 s" and "in 4 s".
- `ci-guard.py` pins the one line that runs a command.

**Test of the tests** (`mutants-fix.txt`): see "Mutants on the fixed tree" below.

### 5. Low: three statements in the record and the docstring are refuted or inexact

- **Refuted: "`skopeo copy … oci:` converts the UBI base's Docker v2s2 manifest and changes its digest"** (record, Sources
  and the options table; docstring lines 23-25). True only without `--preserve-digests`. Source and measurement are in
  finding 7. I retract nothing of my own here; the record's sentence is what the source and the test refute.
- **Inexact: the logs "should show … no `load metadata for registry.access.redhat.com`".** They show
  `#2 [context registry.access.redhat.com/ubi9/python-312-minimal@sha256:b99f…] load metadata for registry.access.redhat.com/…`.
  That line is the layout's: BuildKit v0.35.1 `frontend/dockerui/namedcontext.go:189`, in the `oci-layout` case, sets
  `LogName: fmt.Sprintf("[context %s] load metadata for %s", …)`. The proof is the `[context …]` prefix and line 208's
  `OCI load from client`, both present for all three bases.
- **Inexact: "skopeo checks the manifest against the pinned digest"** (docstring line 14). Not `inspect --raw` on 1.13.3; the
  record's last section already says so.

Every other quote in the record matches its source as fetched on 2026-11-24 (table under "Sources").

**Fix.** The docstring is corrected, and the record gets a section "Reviewer 1's corrections" with the retraction in so
many words, plus three short pointers at the old sentences.

### 6. Low: exit status in the docstring

"Exit 1 on any failure", but a wrong argument exits 2 (`argparse`). The workflow fails either way. The docstring now says so.

### 7. Low, the over-build question: one rejected option was rejected for a reason that does not hold

**The claim.** The record rejects "`skopeo copy … oci:` straight into a layout" because it "converts the UBI base's v2s2
manifest to OCI, so the pinned digest is no longer the one the build uses".

**The source.** containers/image v5.26.2, the runner's (skopeo 1.13.3 `go.mod`), read 2026-11-24:

- `copy/single.go:117`: `if options.PreserveDigests { cannotModifyManifestReason = "Instructed to preserve digests" }`
- `copy/manifest.go:132-142`: `if in.cannotModifyManifestReason != "" { … return manifestConversionPlan{ // Take our chances - FIXME? Or should we fail without trying?  preferredMIMEType: srcType, …` (<https://github.com/containers/image/blob/v5.26.2/copy/manifest.go>)
- `oci/layout/oci_dest.go:242`: `desc.MediaType = manifest.GuessMIMEType(m)`: it files the bytes it is given.

**Measured** on the stub's v2s2 image (`experiments-head.txt`, `experiments-head-skopeo-1.13.3.txt`):

| Command | skopeo 1.24.1 | skopeo 1.13.3 |
|---|---|---|
| `skopeo copy --preserve-digests docker://…@<pin> oci:<dir>` | exit 0; `index.json` names the pin, as `application/vnd.docker.distribution.manifest.v2+json` | the same |
| `skopeo copy docker://…@<pin> oci:<dir>` | exit 0; another digest, as an OCI manifest | the same |

So the script's `dir:` copy, its own filing of each blob, and its hand-written `oci-layout` and `index.json` are not the
only way. skopeo's own manual says of `dir:`: "This is a non-standardized format, primarily useful for debugging or
noninvasive container inspection" (containers/image v5.26.2 `docs/containers-transports.5.md`). Finding 1 lives in exactly
that hand-written part.

**The other six rejections**, each checked:

| Rejected option | The record's reason | Checked |
|---|---|---|
| `docker pull` first | the docker-container driver cannot see the Docker store | Confirmed. Docker docs, `named-contexts.md`: "this driver can't load an image from the Docker store as it's isolated" (<https://docs.docker.com/build/ci/github-actions/named-contexts/>) |
| The tools' own retries | none retries a 401 | Confirmed by source: BuildKit v0.35.1 `retry.go:125` "// Retry on 5xx errors"; containers/common v0.55.4 `pkg/retry/retry.go:80-82` returns false for `ErrorCodeUnauthorized`. Confirmed by test: `skopeo inspect --retry-times 5` and `skopeo copy --retry-times 5` against the stub made 1 token request and exited 1, on both versions |
| Retry the whole build step | retries compile errors, re-pushes, third-party action | Confirmed as far as it can be read: GitHub has no retry key for a step; nick-fields/retry v4.0.0 takes `command`; wretry.action takes `action`. Not tested |
| A local registry | needs `network=host` and a registry image | Confirmed: the same Docker page's example has "network=host driver-opt needed to push to local registry" and `image: registry:3` |
| `driver: docker` | changes how the publisher builds | Not tested. The reasoning is sound: PR builds would no longer take the publisher's path |
| Warming the cache | rests on a 5-minute lease in BuildKit | Not verified by me: I did not read that code |

**Verdict.** Fetching the bases first and handing them to the build by `build-contexts` is needed: nothing simpler keeps
the retry on a 401. Inside the script, 45 lines (237 with `fix.diff`, 192 without them) are there only for the `dir:` path:
`sha256_file`, `put_blob`, the work directory, the blob loop and the layout files. What the direct copy gives up is the script's third check of each blob
(skopeo checks as it copies; BuildKit checks again as it reads: containerd v2.4.2 `core/remotes/handlers.go:184`
`content.Copy(ctx, cw, rc, desc.Size, desc.Digest)` and `plugins/content/local/writer.go:135` "unexpected commit digest").
It keeps the script's check of the pinned manifest, which is the one skopeo 1.13.3 does not make.

**Fix, optional: `r1-outputs/fix-direct-oci.diff`**, applied on top of `fix.diff`. `fetch` becomes:

```python
    retried(f"{ref}: the {platform} image {image}", attempts, delay,
            lambda: skopeo("copy", "--quiet", "--preserve-digests", f"docker://{repo}@{image}", f"oci:{layout}"))
    if image != pinned:  # the index itself, so that the build can be given the pinned digest; its bytes were checked above
        with open(os.path.join(layout, "blobs", "sha256", pinned.split(":", 1)[1]), "wb") as f:
            f.write(raw)
```

The script is 192 lines with it (215 on head, 237 with `fix.diff`). Build contexts are unchanged:
`<FROM ref>=oci-layout://<layout>@<pin>`. BuildKit finds the image by digest and does not read `index.json`
(`source/containerimage/ocilayout.go`, `Resolve`: `store.Info(ctx, dgst)`; buildx `build/opt.go:1107` reads the index only
when the reference has no digest). A layout path with a colon is refused, because "_Path_ terminates at the first `:`
character" (`containers-transports.5.md`).

**Test.** The same suite, less the two cases for checks the script no longer makes: 13 base-image checks pass on 1.24.1 and
on 1.13.3; the guard passes (95). **Not tested: BuildKit reading a layout that skopeo wrote.** Only this PR's CI can show
that, by the same `OCI load from client` lines. That is why it is a separate patch: `fix.diff` alone changes nothing CI has
not already proved about the layout.

My recommendation: apply `fix.diff` now. Apply `fix-direct-oci.diff` in the same PR if its CI run shows the three
`OCI load from client` lines; it removes the code finding 1 was in.

## The five questions

**1. Supply-chain integrity: confirmed, with finding 3 as the gap.**

- Index, manifest, config and each layer are each compared with a SHA-256: the index or pinned manifest by the script
  (`"sha256:" + hashlib.sha256(raw).hexdigest() != pinned`), the platform manifest by the script (`sha256_file(manifest_path)
  != image`) and by skopeo's copy, the config and each layer by size and SHA-256. Every digest read from a manifest must
  match `sha256:[0-9a-f]{64}` before it names a file. BuildKit is given `@<pin>` and checks again on read.
- A tampered layer, manifest and index are each refused, on both skopeo versions (tests, finding 2). A byte added after
  skopeo has finished is refused by the script's own checks (tests, finding 4).
- The platform: the index entry is taken from the verified index by `os`/`architecture`[/`variant`], and none or more than
  one is a refusal. `ci-guard.py` ties `--platform` to the build's `platforms`. The layout holds only that image, so
  BuildKit cannot build another platform's from it. Not tested: BuildKit's own choice, since no build ran here.
- TLS: no flag weakens it. `skopeo()` passes only the two argument lists the guard pins. Measured: the script asks a
  plain-HTTP registry for nothing unless `registries.conf` allows it, on both versions.
- An unpinned `FROM`: refused in seven written forms (`experiments-head.txt`, pins 0 to 6: tag, no tag, `$ARG`, short
  digest, lower case, tabs, `--platform=`); a tag with a digest is taken, by its digest (pin 7). It passed in the three forms of finding 3.
- Credentials: in `images` the base step runs before "Sign in to GHCR", so skopeo has no GHCR credential.

**2. Retry correctness: refuted in part (finding 2).** Waits are `delay * 2 ** (attempt - 1)`: 2, 4, 8, 16 s for 5 attempts,
30 s in all, for the inspect and for the copy separately. When every attempt fails: exit 1, nothing on stdout,
"failed 5 times; the last: …unauthorized" (test, both versions). The step's shell is `bash -e` (the run's log:
`shell: /usr/bin/bash -e {0}`), and `x=$(false)` under `bash -e` exits 1 (run here), so the step stops before it writes
`GITHUB_OUTPUT`. It retried every skopeo failure, a digest mismatch included.

**3. Coverage: confirmed.** Three jobs build an image: `front-door`, `images`, `images-pr` (the last two over `cmapi` and
`cmapi-portal`). Each has the base step before the build and `build-contexts` on it; the guard checks all three and that no
`run` line builds an image. FROM lines: `cmapi/Containerfile` 14 and 59 (the same UBI pin; stage `tools`),
`cmapi-portal-ui/Containerfile` 11 (node, stage `build`) and 21 (nginx-unprivileged). The CI log shows `OCI load from
client` for each. `front-door`: the tag is still `cmapi-portal:ci`, `GIT_COMMIT` is the same value (`github.sha`), the two
test steps are unchanged, and the run shows "exporting to docker image format", "importing to docker" and the browser
checks passing. `build-contexts` is read with `Util.getInputList('build-contexts', {ignoreComma: true})`
(build-push-action `src/context.ts:60` at `c3c9e263`), so one context per line is right. One thing nothing checks: if a later
buildx stopped matching the context name to the `FROM`, BuildKit would pull from the registry again and no test would fail;
only the log line would differ. Both sides are normalised the same way today (buildx v0.39.0 `util/buildflags/context.go`
and BuildKit v0.35.1 `frontend/dockerui/config.go:487`: `strings.TrimSuffix(reference.FamiliarString(named), ":latest")`).
I have no code for that, so it is a note, not a finding.

**4. Over-build: finding 7.**

**5. Tests: findings 2 and 4.** Of the PR's six base-image checks, five were made to fail: the first on the base tree, the
success case by the no-retry mutant, the all-refused and the layer cases by the mutant that goes on after the last
attempt, the unpinned case by its mutant. The tampered-manifest check was failed by no mutant I ran. Eight mutants of the
script survived both tests (finding 4).

## Mutants on the fixed tree

`mutants-fix.txt`, this Mac, skopeo 1.24.1, on head + `fix.diff`: all 17 mutants are killed, 0 survive.

| Mutant | Head | Fixed tree |
|---|---|---|
| no retry: the first failure is final | killed | killed |
| the wait does not double | SURVIVED | killed |
| the script's own mismatch raised inside the retried call | SURVIVED | killed |
| the blob check skipped | SURVIVED | killed |
| the pinned-manifest check skipped | SURVIVED | killed |
| the copied-manifest check skipped | SURVIVED | killed |
| all three skipped | SURVIVED | killed (3 FAIL) |
| TLS off inside `skopeo()` | SURVIVED | killed, by the retry test and by the guard |
| TLS off at the call sites | killed | killed |
| the platform not read | SURVIVED | killed |
| `--preserve-digests` dropped | killed | killed (the guard only) |
| an unpinned FROM passes | killed | killed |
| the context names another digest | killed | killed |
| a digest skopeo found wrong is tried again (finding 2 undone) | | killed (3 FAIL) |
| a layer listed twice is looked for twice (finding 1 undone) | | killed |
| an image named by `--from=` or a mount passes (finding 3 undone) | | killed |
| a byte-order mark hides the first FROM (finding 3 undone) | | killed |

Not run on the fixed tree: the mutant "the script goes on after the last attempt" (killed on head). The run used the test
file before two long lines were wrapped; no assertion changed after it. Mutants were not run on `fix-direct-oci.diff`.

## Sources, each fetched and read on 2026-11-24

| Source | The sentence |
|---|---|
| skopeo v1.13.3 `docs/skopeo-copy.1.md` <https://github.com/containers/skopeo/blob/v1.13.3/docs/skopeo-copy.1.md> | `--preserve-digests`: "Preserve the digests during copying. Fail if the digest cannot be preserved." `--src-tls-verify`: "Require HTTPS and verify certificates when talking to container source registry or daemon. Default to source registry setting." `--retry-times`: "The number of times to retry. Retry wait time will be exponentially increased based on the number of failed attempts." |
| skopeo v1.13.3 `docs/skopeo-inspect.1.md` | `--raw`: "Output raw manifest or config data depending on --config option." `--tls-verify`: "…Default to registry.conf setting." |
| containers/image v5.26.2 `docs/containers-transports.5.md` | `dir:`: "An existing local directory _path_ storing the manifest, layer tarballs and signatures as individual files. This is a non-standardized format, primarily useful for debugging or noninvasive container inspection." `oci:`: "An image in a directory structure compliant with the "Open Container Image Layout Specification" at _path_." |
| containers/common v0.55.4 `pkg/retry/retry.go` | `case errcode.ErrorCodeUnauthorized, errcode.ErrorCodeDenied, errcodev2.ErrorCodeNameUnknown, errcodev2.ErrorCodeManifestUnknown: return false` |
| OCI image-spec v1.1.1 `image-layout.md` <https://github.com/opencontainers/image-spec/blob/v1.1.1/image-layout.md> | "The content of `blobs/<alg>/<encoded>` MUST match the digest `<alg>:<encoded>`"; "The blobs directory MAY be missing referenced blobs, in which case the missing blobs SHOULD be fulfilled by an external blob store."; `index.json` "MUST be an image index JSON object" |
| OCI image-spec v1.1.1 `image-index.md`, `manifest.md` | `mediaType`: "This property SHOULD be used … When used, this field MUST contain the media type `application/vnd.oci.image.index.v1+json`" (and `…manifest.v1+json`); `platform`: "This OPTIONAL property describes the minimum runtime requirements of the image." |
| OCI image-spec v1.1.1 `media-types.md` | `application/vnd.oci.image.index.v1+json`, `application/vnd.oci.image.manifest.v1+json`, `application/vnd.oci.image.config.v1+json`, `application/vnd.oci.image.layer.v1.tar+gzip` |
| distribution `docs/content/spec/manifest-v2-2.md` <https://github.com/distribution/distribution/blob/main/docs/content/spec/manifest-v2-2.md> | "`application/vnd.docker.distribution.manifest.v2+json`: New image manifest format (schemaVersion = 2)"; "`application/vnd.docker.distribution.manifest.list.v2+json`: Manifest list, aka "fat manifest""; `application/vnd.docker.container.image.v1+json`; `application/vnd.docker.image.rootfs.diff.tar.gzip` |
| buildx v0.39.0 `docs/reference/buildx_build.md` <https://github.com/docker/buildx/blob/v0.39.0/docs/reference/buildx_build.md> | "Use the `oci-layout:///` scheme. Source an image from a local OCI layout compliant directory, either by tag, or by digest:", then `$ docker buildx build --build-context foo=oci-layout:///path/to/local/layout@sha256:<digest>`; "The OCI layout directory must be compliant with the OCI layout specification." |
| BuildKit v0.35.1 `frontend/dockerui/namedcontext.go`, `source/containerimage/ocilayout.go`, `util/resolver/retryhandler/retry.go` | quoted in findings 5 and 7 and in question 3 |
| docker/build-push-action `action.yml` at `c3c9e263` | `build-contexts`: "List of additional build contexts (e.g., name=path)"; no input named retry |
| The record's other quotes: setup-buildx-action `action.yml` at `f87e5991` (no retry input), actions-toolkit v0.100.0 `Docker.pullWithRetry` (`retries = 5`, `minTimeout: 1000`, `factor: 2`, `500\|502\|503\|504`), runner image 20261116.376.1 ("Skopeo 1.13.3", "Docker-Buildx 0.39.0"), build-push-action issue 719 (open, "Feature Request: Automated Recovery"), GitHub workflow syntax ("Prevents a job from failing when a step fails."), nick-fields/retry v4.0.0, Wandalen/wretry.action | each matches |

The media types in the script (`INDEX_TYPES`, `MANIFEST_TYPES`) are the four that the two specifications name.

## Results on the fixed tree

| Tree | Test | skopeo 1.24.1, this Mac | skopeo 1.13.3, container |
|---|---|---|---|
| head + `fix.diff` | `download-retry-test.py` | exit 0: 17 downloads, 15 base-image checks | exit 0: 15 base-image checks (that part alone) |
| head + `fix.diff` | `ci-guard.py` | exit 0: 95 checks | not run there (no PyYAML) |
| head, with the fixed tests | the base-image part | exit 1: 7 FAIL, 8 ok (findings 1, 2 and 3) | exit 1: 5 FAIL, 10 ok (the manifest and index cases of finding 2 pass there) |
| + `fix-direct-oci.diff` | `download-retry-test.py` | exit 0: 17 downloads, 13 base-image checks | exit 0: 13 |
| + `fix-direct-oci.diff` | `ci-guard.py` | exit 0: 95 checks | not run there |

`fix.diff` touches `deploy/base-images.py`, `deploy/tests/ci-guard.py`, `deploy/tests/download-retry-test.py` and
`docs/reviews/2026-11-24-issue-663/README.md`. It applies to a fresh copy of `head/` with `patch -p1 -F0`, and the result
equals the tree the tests ran on (`diff -rq` over `.github`, `deploy` and `docs`: no difference). `ci.yml` is not changed.

Left in the record for the coordinator: its tests table still gives the head counts ("6 of 6", "94 checks"). The numbers
above replace them once CI has run on the fixed head.

## Files in `r1-outputs/`

`fix.diff`, `fix-direct-oci.diff`; `experiments.py` and its outputs `experiments-head.txt` (its first entry, the
layer-twice case, hit a file-name clash on this Mac's file system; `experiments-head-dup.txt` is the corrected run),
`experiments-head-skopeo-1.13.3.txt`; `mutants.py`, `mutants-head.txt`, `mutants-fix.txt`; `real-images-duplicate-layers.txt`;
the test outputs named above; `ci-run-45529793850.log`.

Left on this Mac: the podman image `quay.io/skopeo/stable:v1.13.3`, which I pulled to run skopeo 1.13.3. Remove it with
`podman rmi quay.io/skopeo/stable:v1.13.3` when reviewer 2 no longer needs it.
