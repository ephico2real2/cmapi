# PR #666 (closes #663): reviewer 2's report

Reviewer 2: Opus 5.5 at `high`, 2026-11-24. I did not write the change or reviewer 1's review. I worked only in
`review-666/`: copies of `head/` (`r2/` is the final tree; `r2-direct/` is head with both of reviewer 1's patches; the other scratch copies
are removed), and `r2-outputs/`. No image was built. No git repository, GitHub object or cluster was touched. Network
use: reads of public sources (raw.githubusercontent.com, packages.ubuntu.com) and pulls of the three pinned bases and of
`tomcat:latest`'s manifest from their registries.

**Verdict.** Take reviewer 1's findings 1 to 6 and the optional direct OCI copy (finding 7), **with four corrections of mine**.
The decisive one: `fix-direct-oci.diff` as written **fails on the real UBI base** with the runner's skopeo version, 1.13.3,
when it runs in Fedora's `quay.io/skopeo/stable:v1.13.3`: "Can not copy signatures to oci:…: Pushing signatures for OCI
images is not supported", on all 5 attempts. `--remove-signatures` fixes it. With that flag, the direct copy keeps every
integrity guarantee and writes the same blobs, byte for byte, as the implementer's `dir:` path. My patch is
`r2-outputs/fix.diff`: one patch against `head/` with everything in it.

## What was run, and where

| What | Where | Result |
|---|---|---|
| Both tests on `head/` | this Mac, skopeo 1.24.1, Python 3.12.14 | retry test exit 0 (17 downloads, 6 base-image checks), guard exit 0 (94) (`head-retry.txt`, `head-guard.txt`) |
| Both tests on head + `fix.diff` | this Mac | exit 0 (17 downloads, 15 base checks), guard exit 0 (95) (`fix1-*.txt`); reviewer 1's numbers confirmed |
| `head`'s script and the direct-copy script against the real registries, both Containerfiles | this Mac (1.24.1) and the 1.13.3 container | `real/summary.txt`, below |
| My tests on reviewer 1's final tree (head + both patches) | 1.24.1 and 1.13.3 | exit 1 on both: 5 FAIL each (`r2tests-on-r1final-*.txt`) |
| The final tree (`r2/`), both tests | 1.24.1: retry test 17 downloads + 19 base checks, exit 0; guard 98, exit 0. 1.13.3 (base part): 19 of 19, exit 0 | `final-retry.txt`, `final-guard.txt`, `final-base-1.13.3.txt` |
| Mutants of the final tree | 1.24.1: all; 1.13.3: the four of my own fixes | `mutants-final-1.24.1.txt`, `mutants-final-index-1.24.1.txt`, `mutant-113-*.txt` |

Not tested: BuildKit reading a layout that skopeo wrote (no image built here; CI proves it, see "What CI must show").

## Sources verified (each fetched and read on 2026-11-24)

| Claim | Source and sentence | Ruling |
|---|---|---|
| `--preserve-digests` keeps a v2s2 manifest in an `oci:` copy | skopeo v1.13.3 `docs/skopeo-copy.1.md`: "Preserve the digests during copying. Fail if the digest cannot be preserved." containers/image v5.26.2 (skopeo 1.13.3's `go.mod`: `github.com/containers/image/v5 v5.26.2`) `copy/single.go:117-118`: `if options.PreserveDigests { cannotModifyManifestReason = "Instructed to preserve digests" }`; `copy/manifest.go:132-140`: `if in.cannotModifyManifestReason != "" { … return manifestConversionPlan{ // Take our chances - FIXME? Or should we fail without trying? preferredMIMEType: srcType,`; `oci/layout/oci_dest.go` `PutManifest`: `os.WriteFile(blobPath, m, 0644)`, `desc.MediaType = manifest.GuessMIMEType(m)` | Confirmed. The implementer's sentence stays retracted. Measured on the real UBI base: the layout holds the v2s2 manifest under `sha256:b99faa…` (`real/rs113-cmapi.index.json`) |
| An `oci:` layout path ends at the first colon | v5.26.2 `docs/containers-transports.5.md`: "_Path_ terminates at the first `:` character; any further `:` characters are not separators, but a part of _reference_." | Confirmed |
| OCI image layout | image-spec v1.1.1 `image-layout.md`: "The content of `blobs/<alg>/<encoded>` MUST match the digest `<alg>:<encoded>`"; "The blobs directory MAY contain blobs which are not referenced by any of the refs"; "The blobs directory MAY be missing referenced blobs"; "Implementations should not error when encountering unknown files." | Confirmed. So the index's blob outside `index.json`, and a stray `oci-put-blob*` temp file after a killed attempt, are both within the spec |
| BuildKit resolves an `oci-layout://…@digest` context without `index.json` | buildx v0.39.0 `build/opt.go:1100-1124`: `if ref.Digest == "" { dig, err := resolveDigest(localPath, ref.Tag)` … `store, err := local.NewStore(localPath)`. BuildKit v0.35.1 `source/containerimage/ocilayout.go` `Resolve`: `info, err := r.info(ctx, ref)` → `store.Info(ctx, dgst)`, then `imageutil.DetectManifestBlobMediaType(b)` from the blob's bytes | Confirmed |
| The log lines | BuildKit v0.35.1 `frontend/dockerui/namedcontext.go:189`: `LogName: fmt.Sprintf("[context %s] load metadata for %s", …)`; `:208`: `llb.WithCustomName("[context " + nc.nameWithPlatform + "] OCI load from client")`. Run 45529793850's log (reviewer 1's copy): lines 8211/8222 (UBI), 5051-5073 and 9742-9765 (node, nginx-unprivileged) | Confirmed: reviewer 1's correction of the record stands |
| BuildKit checks each blob as it reads it | containerd v2.4.2 (BuildKit v0.35.1's `go.mod`) `core/remotes/handlers.go:184`: `return content.Copy(ctx, cw, rc, desc.Size, desc.Digest)`; `plugins/content/local/writer.go:135`: `"unexpected commit digest %s, expected %s: %w"` | Confirmed for content fetched through that handler. I did not trace every BuildKit path for lazily read layers; the claim does not carry the decision, see below |
| Duplicate layers are valid | image-spec v1.1.1 `manifest.md` (`layers`: "Each item in the array MUST be a descriptor", base layer at index 0, then stack order) and distribution `manifest-v2-2.md` (`layers`: "The layer list is ordered starting from the base image") set no uniqueness rule; "unique" and "duplicate" appear in neither about layers | Confirmed valid. Re-measured: `docker.io/library/tomcat:latest`, linux/amd64 `sha256:7e5e49b1…`: 10 layers, `sha256:4f4fb700ef54` listed 3 times (`real-tomcat-duplicate-layers.txt`) |
| skopeo checks what the direct copy relies on | v5.26.2 `internal/image/unparsed.go:58-66`: "ImageSource.GetManifest does not do digest verification, but we do" … "Manifest does not match provided manifest digest %s"; `copy/digesting_reader.go:57`: "Digest did not match, expected %s, got %s"; `internal/image/docker_schema2.go:115` and `oci.go:77`: "Download config.json digest %s does not match expected %s"; `oci_dest.go` `PutBlobWithOptions`: `io.Copy` then `os.Rename` only on success, the temporary file removed otherwise | Confirmed by source, and by test on both versions (below) |
| An OCI layout refuses signatures | v5.26.2 `oci/layout/oci_dest.go:71`: `stubs.NoSignatures("Pushing signatures for OCI images is not supported")`; skopeo v1.13.3 `skopeo-copy.1.md`: `--remove-signatures` "Do not copy signatures, if any, from _source-image_. Necessary when copying a signed image to a destination which does not support signatures."; `containers-registries.d.5.md`: "the registries configuration directory is `$HOME/.config/containers/registries.d` if it exists, otherwise `/etc/containers/registries.d`" | New (finding R2-1) |
| `# syntax=` pulls a frontend image | BuildKit v0.35.1 `frontend/dockerfile/builder/build.go:55-63`: `if cmdline, ok := opts[keySyntaxArg]` (`build-arg:BUILDKIT_SYNTAX`) … `} else if ref, cmdline, loc, ok := parser.DetectSyntax(src.Data); ok { res, err := forwardGateway(ctx, c, ref, cmdline)`; `parser/directives.go`: `discardBOM`, `discardShebang`, then `# key=value` lines until the first other line; "c-style directives '// syntax = ...'" | New (finding R2-3) |

**Retracted, in so many words.** I retract nothing of my own. One statement of reviewer 1 is **refuted for the real UBI
base**: finding 7's table says `skopeo copy --preserve-digests docker://…@<pin> oci:<dir>` on 1.13.3 gives "the same" as on
1.24.1. That was measured on the stub, which has no signatures. On `registry.access.redhat.com/ubi9/python-312-minimal@sha256:b99faa…`
in `quay.io/skopeo/stable:v1.13.3`, the copy fails (finding R2-1).

## Rulings on reviewer 1's findings

| # | Finding | Ruling | The test that decides it |
|---|---|---|---|
| 1 | A manifest that lists one layer twice is refused (Medium) | **Accepted.** Valid per both specifications; real images do it. With the direct copy, skopeo's `TryReusingBlobWithOptions` files the blob once | "takes an image whose manifest lists one layer twice": fails on head, passes on the final tree (both versions), with the layout checked whole |
| 2 | A digest mismatch skopeo reports is retried (Medium) | **Accepted, and incomplete** (R2-2): the config's wording was missing | "refuses a config that is not its digest": on reviewer 1's tree, `asked 10` and 5 attempts (1.24.1); final tree: one attempt, both versions. Mutant "MISMATCH without the config's wording" (= reviewer 1's regex) is killed on 1.24.1 and 1.13.3 |
| 3 | `COPY --from=` an image, a mount from an image, a BOM before FROM (Low) | **Accepted.** I checked the regex against `--mount=type=bind,from=build,target=/m` (stage, passes), `COPY --from=0` (passes) and an image (refused). A heredoc line containing `--from=` would be refused; that fails closed and neither Containerfile has one | Its three cases; mutants "an image named by --from= or a mount passes" and "a byte-order mark hides the first FROM" killed |
| 4 | The script's own checks had no test that could fail; TLS (Low) | **Accepted.** With the direct copy only the pinned-manifest check is the script's; its lying-skopeo case stays. TLS case kept | Mutants "the pinned-manifest check skipped", "TLS off, in the helper", "TLS off, at the call sites" killed |
| 5 | Record and docstring statements (Low) | **Accepted.** I checked each quoted source myself (table above) | n/a (documentation) |
| 6 | Exit status 2 on a wrong argument (Low) | **Accepted** | n/a |
| 7 | The direct `oci:` copy was rejected for a reason that does not hold | **Accepted, with `--remove-signatures` (R2-1).** Decision below | Real-registry comparison and the signature case |

## Reviewer 2's findings

### R2-1. Medium: the direct copy fails where registries.d names a signature lookaside

**Where.** `r1-outputs/fix-direct-oci.diff`, `fetch`: `skopeo("copy", "--quiet", "--preserve-digests", …, f"oci:{layout}")`.

**Measured** (`real/direct113-cmapi.stderr`, `real/summary.txt`): reviewer 1's final script, in `quay.io/skopeo/stable:v1.13.3`,
on `cmapi/Containerfile`: exit 1 after 5 attempts, each "Can not copy signatures to oci:/s/direct113-cmapi:: Pushing
signatures for OCI images is not supported". That image's `/etc/containers/registries.d/registry.access.redhat.com.yaml`
(Fedora 39 `containers-common-1-95.fc39`) has `sigstore: https://access.redhat.com/webassets/docker/content/sigstore`. The
same script on 1.24.1 here (no registries.d) and head's `dir:` script (the `dir:` transport stores signatures) passed.

**Does it hit the runner?** Probably not today. Ubuntu 24.04's `golang-github-containers-common` ships
`/etc/containers/policy.json` and `/etc/containers/registries.conf.d/shortnames.conf`, and `golang-github-containers-image`
ships `/etc/containers/registries.conf`; neither has a `registries.d` file (packages.ubuntu.com file lists, noble). Inferred,
not measured: I cannot list the runner's `/etc/containers/registries.d`. A Fedora or RHEL runner, or a later runner image
that adds the file, would fail every image build.

**Fix.** `--remove-signatures` on the copy. The script verifies no signature, and head's `dir:` copy threw them away with its
work directory, so nothing is lost; the copy also stops fetching signatures, one network dependency fewer. `ci-guard.py`
pins the flag.

**Test.** The stub's UBI image has a lookaside signature (`/sigstore/ubi@sha256=<hex>/signature-1`, first byte `0xA3` so
skopeo parses it as a simple signing signature), named by a `registries.d` file under the test's `HOME`. A first check proves
the lookaside is live: a plain `skopeo copy … oci:` fails with "Pushing signatures for OCI images is not supported", on both
versions. Mutant "--remove-signatures dropped": killed on 1.24.1 (3 FAIL, and the guard) and 1.13.3 (3 FAIL). After
`--remove-signatures`, the same real UBI copy in the 1.13.3 container: exit 0, and the same 4 blobs as head's layout
(`real/rs113-cmapi.blobs`).

### R2-2. Medium: a config that is not its digest was still tried 5 times

**Where.** `fix.diff`'s `MISMATCH = re.compile(r"Digest did not match|does not match provided manifest digest")`.

**Measured.** skopeo reads the config whole before the copy pipeline and words its own check: "Download config.json digest
%s does not match expected %s" (v5.26.2) and, on 1.24.1, "config validation failed: blob digest sha256:ff3e… does not match
expected sha256:d825…" (`final-base-1.24.1.txt`, first run). Reviewer 1's tree: 5 attempts, 30 s of waits.

**Fix.** `MISMATCH = re.compile(r"Digest did not match|does not match provided manifest digest|does not match expected")`.

**Test.** "refuses a config that is not its digest, in one attempt of 5". The check is "no `trying again`" and the path
asked at least once: skopeo reads a config twice in one attempt (`asked 2` per attempt measured on 1.24.1), so reviewer 1's
`asked == 1` cannot be the rule for it. I also added "the platform's manifest of an index, not the digest the index names",
the one artifact no case covered; it was already refused in one attempt on both versions.

### R2-3. Low: a `# syntax=` directive, or `BUILDKIT_SYNTAX`, makes BuildKit pull an image itself

Same class as finding 3: the frontend image is pulled by BuildKit, unretried and unchecked, and `# syntax=docker/dockerfile:1`
is a common first line. Neither Containerfile has one today (read: `cmapi/Containerfile` lines 1-16 are comments with no
`=` directive; `cmapi-portal-ui/Containerfile` starts with `# cmapi-portal: …`).

**Fix.** `base_images` reads the parser directives as BuildKit does (after a BOM and a `#!` line, the leading `#` or `//`
`syntax|escape|check = value` lines, to the first other line) and refuses `syntax`. `ci-guard.py`: "the build names no
frontend image to pull" for each of the three builds.

**Test.** Two cases (a plain `# syntax=`; a BOM, a `#!` line, `# check=…` and `#SYNTAX = …`). The success case starts with
`# escape=\` and has `# syntax=a-comment-here` after a `FROM`, which BuildKit treats as a comment, so a false refusal fails
it. Mutants "a syntax directive passes", "directives read past the first line that is not one", "the #! line is not
skipped" and the `ci.yml` mutant "a BUILDKIT_SYNTAX build-arg in images-pr" are all killed.

### R2-4. Low, the test: the layout was not checked whole, nor a colon in the layout path

With the direct copy the script writes the index's bytes itself. On reviewer 1's tree, with reviewer 1's tests
(`mutants-r1tree-r1tests-1.24.1.txt`): "the index is not put in the layout" SURVIVED, and "a layout path with a colon passes"
SURVIVED. The build would have failed only in CI.

**Fix (tests only).** `layout_holds` walks each build context through the layout as BuildKit will: the blob, an index's
platform manifest, the config and every layer. A case gives `--layout` a colon. The stub's index is indented, so a script
that re-serialized it would file other bytes under the pin; before that, the mutant "the index is put in the layout
re-serialized" survived, because the stub's index was already in `json.dumps`'s form.

## The key decision: `fix-direct-oci.diff`

**Taken, with `--remove-signatures`.** The owner's rule is "over-build only if it is the only solution". The direct copy is
simpler: no `dir:` work directory, no `sha256_file`, no `put_blob`, no blob loop, no hand-written `oci-layout` or
`index.json`. The script is 210 lines, against 215 on head and 237 with `fix.diff` alone; the 18 lines over reviewer 1's
192 are my R2-1 to R2-3 checks and their comments. It keeps every guarantee:

| What goes in the layout | Checked by | Shown by |
|---|---|---|
| The index, or the pinned manifest | The script: `sha256(raw) == pinned`, on every skopeo version (1.13.3's `inspect --raw` does not check it); the index's bytes are written as fetched | "refuses a manifest / an index that is not the pinned digest"; the lying-skopeo case; mutant "the pinned-manifest check skipped" |
| An index's platform manifest | skopeo `copy` (`UnparsedImage.Manifest`), against the digest the verified index names; only a `sha256:` + 64 hex digest is used | New case "the platform's manifest of an index…", both versions |
| The config | skopeo (`ConfigBlob`: "does not match expected") | New case "a config that is not its digest", both versions |
| Each layer | skopeo (`digestingReader`); the blob is renamed into place only after a clean read | "a layer that is not its digest", both versions; `layout_ok` hashes every file in `blobs/sha256` |
| All of them, again | BuildKit, as it ingests them (containerd `content.Copy` with the expected digest) | Source only |

**Does losing the third blob check weaken anything real?** No. It re-hashed, a moment later, bytes that skopeo had hashed as
it wrote them, and that skopeo renames into `blobs/sha256/<digest>` only after that hash passed. It would catch only a
skopeo that wrote unverified bytes under a digest name; BuildKit would still refuse those at the build, so the build fails
closed either way. What does change: such a failure would show in the build step, not the base step. A retry would not have
helped it.

**The layout BuildKit reads is the one CI already proved, blob for blob** (`real/summary.txt`): for both Containerfiles, the
direct copy (1.24.1, and 1.13.3 with `--remove-signatures` for UBI) and head's `dir:` copy hold the same files in
`blobs/sha256`, with the same SHA-256 and size. Only `index.json` differs, and BuildKit does not read it for a context named
by digest (buildx `build/opt.go`, BuildKit `ocilayout.go`, above).

**What CI must show on the commit with this patch** (the proof that is not possible here): in the logs of `front-door`,
`images-pr (cmapi, cmapi/Containerfile, cmapi)` and `images-pr (cmapi-portal, cmapi-portal-ui/Containerfile, .)`:

1. `[context registry.access.redhat.com/ubi9/python-312-minimal@sha256:b99faaadaf10de740d60c713a047088df2f46ebdd766e9c6a0957896f44d0ea1] OCI load from client` (in `images-pr (cmapi, …)`);
2. `[context node@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53] OCI load from client`;
3. `[context nginxinc/nginx-unprivileged@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03] OCI load from client` (2 and 3 in `front-door` and `images-pr (cmapi-portal, …)`);
4. and no `[internal] load metadata for` line naming any of the three. Each base's `load metadata for` line must carry the
   `[context …]` prefix, and its `resolve <registry ref>@sha256:… done` line must sit under the step number of its `OCI load
   from client` line. That `resolve` line is the layout's, named after the `FROM` reference: run 45529793850 shows
   `#5 [context node@sha256:06d7…] OCI load from client`, then `#5 resolve docker.io/library/node@sha256:06d7… done`
   (log lines 5061-5062), so the bare presence of `resolve docker.io/…` is not a registry pull.

Run 45529793850 showed exactly these for the `dir:` layout. If any is missing, drop the direct copy: reviewer 1's `fix.diff`
with my R2-2 and R2-3 changes is the fallback.

## Mutants of the final fix (`r2-outputs/mutants.py`)

25 of 25 killed. On 1.24.1, each run is the base-image part of `download-retry-test.py` plus `ci-guard.py`; the file is restored after each. The full set ran before the stub's index was indented; the two index mutants and the final tests ran again after it.

| Mutant | Result |
|---|---|
| none (the tree as it is) | baseline ok |
| no retry: the first failure is final | killed (1 FAIL) |
| the wait does not double | killed (1) |
| every attempt failed, and the script goes on | killed (2) |
| a digest skopeo found wrong is tried again (finding 2 undone) | killed (5) |
| MISMATCH without the manifest's wording | killed (3) |
| MISMATCH without the config's wording (review 1's regex, R2-2) | killed (1); also on 1.13.3 (1) |
| the pinned-manifest check skipped | killed (1) |
| the script's own mismatch raised inside the retried call | killed (1) |
| TLS off, in the helper | killed (1, and the guard) |
| TLS off, at the call sites | killed (1, and the guard) |
| `--preserve-digests` dropped | killed (1, and the guard) |
| `--remove-signatures` dropped (R2-1) | killed (3, and the guard); also on 1.13.3 (3) |
| the platform is not read: the index's first image manifest | killed (2) |
| the index is not put in the layout (R2-4) | killed (1); also on 1.13.3 (1) |
| the index is put in the layout re-serialized (R2-4) | SURVIVED in the full run; killed (1) after the stub's index was indented (`mutants-final-index-1.24.1.txt`) |
| the build context names no digest | killed (1) |
| an unpinned FROM passes | killed (2) |
| an image named by `--from=` or a mount passes | killed (2) |
| a byte-order mark hides the first FROM | killed (2) |
| a syntax directive passes (R2-3) | killed (2); also on 1.13.3 (2) |
| directives read past the first line that is not one (R2-3) | killed (2) |
| the `#!` line is not skipped (R2-3) | killed (1) |
| a layout path with a colon passes (R2-4) | killed (1) |
| `ci.yml`: `--attempts 1` in `front-door` | killed (1, and the guard) |
| `ci.yml`: a `BUILDKIT_SYNTAX` build-arg in `images-pr` (R2-3) | killed (the guard) |

## The patch

`r2-outputs/fix.diff`, against `head/`, built with `diff -ruN` over `.github`, `deploy` and `docs` (`.github` is unchanged).
It touches `deploy/base-images.py`, `deploy/tests/download-retry-test.py`, `deploy/tests/ci-guard.py` and
`docs/reviews/2026-11-24-issue-663/README.md`. It holds reviewer 1's `fix.diff`, `fix-direct-oci.diff`, and R2-1 to R2-4.
The record's test table has the final numbers and a section "Reviewer 2's ruling". It applies to a fresh copy of `head/` with `patch -p1 -F0` (exit 0, no `.orig` or `.rej`), and the result equals `r2/` (`diff -rq` over `.github`, `deploy` and `docs`: no difference). 744 lines.

## Left for the coordinator

- The CI gate above, on the commit that carries this patch.
- `docs/10-architecture-review.md` section 8 says "each blob checked by digest": still true (skopeo checks each), unchanged.
- Reviewer 1's section of the record keeps its own wording, with one sentence pointed at my ruling.
- The podman image `quay.io/skopeo/stable:v1.13.3` is removed (`podman rmi`).

## Files in `review-666/r2-outputs/`

`fix.diff`; `mutants.py`, `mutants-final-1.24.1.txt`, `mutants-final-index-1.24.1.txt`, `mutants-r1tree-r1tests-1.24.1.txt`,
`mutant-113-*.txt`; `run-tests.sh`, `base-only.sh`, `in-113.sh`, `mut113.sh`, `real-compare.sh`; `head-*.txt`, `fix1-*.txt`,
`final-*.txt`, `r2tests-on-r1final-*.txt`; `real/` (contexts, stderr, blob lists, `index.json` and `ls` of each layout, and
`summary.txt`); `real-tomcat-duplicate-layers.txt`.
