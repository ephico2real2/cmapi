# #663: the image builds fetch their base images first, with retries, and read them from a verified OCI layout

The implementer's record: Opus 5.5 at `high`, 2026-11-24, on `fix/663-base-image-pull-retry` from `0a85b4d`. The reviews go
beside it when they are done.

## What failed

**Measured.** PR #659, run 45492928616, job `images-pr (cmapi, cmapi/Containerfile, cmapi)` (138795724679), 2026-11-24 21:37Z.
BuildKit v0.35.1 on buildx v0.39.0 (`docker-container` driver) resolved
`registry.access.redhat.com/ubi9/python-312-minimal@sha256:b99faa…` and its manifest, and had started the first layer
(3.44 MB of 25.28 MB), when a layer request was sent to registry.redhat.io for an anonymous token:

> failed to copy: httpReadSeeker: failed open: failed to authorize: failed to fetch anonymous token: unexpected status from
> GET request to https://registry.redhat.io/auth/realms/rhcc/protocol/redhat-docker-v2/auth?scope=repository%3Aubi9%2Fpython-312-minimal%3Apull&service=docker-registry: 401 Unauthorized

The second attempt of the same run, on the same commit `1cdaea58`, passed (job 138810952851). The log is in the implementer's
outputs, `failing-job-138795724679.log`.

**Measured, 2026-11-24, from this Mac.** `registry.access.redhat.com/v2/` answers 200 with no challenge, and the two layers of
that manifest answer 302 to `cdn01.quay.io`, with no token. The same token URL answers 401 to an anonymous request. So the
transient part was the registry asking for a token at all; once it asks, the token endpoint refuses. **Inferred**, not
measurable from here: which side of Red Hat's registry sent that challenge.

## Sources

Each read 2026-11-24, at the version CI runs where there is one.

- **docker/build-push-action v7.4.0** (`action.yml` at `c3c9e263`, the pin in `ci.yml`): its inputs are `add-hosts` …
  `github-token`; none retries. `build-contexts`: "List of additional build contexts (e.g., name=path)". The request for a
  retry, docker/build-push-action#719 "Feature Request: Automated Recovery", is open.
- **docker/setup-buildx-action v4.4.1** (`action.yml` at `f87e5991`): no retry input. Its own BuildKit image pull goes through
  `@docker/actions-toolkit` v0.100.0 `Docker.pullWithRetry`: `retries = 5`, `minTimeout: 1000`, `factor: 2`, and only for
  errors that `isPullTransientError` matches: timeouts, resets, EOF, and `500|502|503|504`. A 401 is not one.
- **BuildKit v0.35.1**, `util/resolver/retryhandler/retry.go`, `retryError`: "// Retry on 5xx errors" (`StatusCode >= 500 &&
  StatusCode <= 599`), then `io.EOF`, `io.ErrUnexpectedEOF`, a reset connection, `EPIPE`, `net.ErrClosed` and a temporary
  `net.Error`. Nothing else retries, and `MaxRetryBackoff` is a variable "so that code which embeds BuildKit can override",
  not a buildkitd setting. So BuildKit's own retry exists and cannot cover a 401.
- **Docker docs, "Named contexts with GitHub Actions"** (<https://docs.docker.com/build/ci/github-actions/named-contexts/>):
  the docker-container driver "can't load an image from the Docker store as it's isolated". So a `docker pull` before the
  build is never seen by this builder.
- **Docker docs, `docker buildx build`, `--build-context`** (<https://docs.docker.com/reference/cli/docker/buildx/build/>):
  "Source an image from a local OCI layout compliant directory, either by tag, or by digest:
  `--build-context foo=oci-layout:///path/to/local/layout@sha256:<digest>`", and "the context can be accessed when `FROM name`
  ... is used".
- **buildx v0.39.0** `util/buildflags/context.go` and **BuildKit v0.35.1** `frontend/dockerui/config.go` (`NamedContext`):
  both turn the context's name and the `FROM` reference into `reference.FamiliarString` before they compare, so the full
  `FROM` reference, digest included, names the context.
- **skopeo 1.13.3**, the runner's (`actions/runner-images`, Ubuntu 24.04 image 20261116.376.1: "Skopeo 1.13.3",
  "Docker-Buildx 0.39.0"). Its `copy` manual: `--preserve-digests` "Preserve the digests during copying. Fail if the digest
  cannot be preserved"; `--retry-times` "The number of times to retry". Its retry uses **containers/common v0.55.4**
  `pkg/retry` `IsErrorRetryable`, which returns false for `errcode.ErrorCodeUnauthorized` and `ErrorCodeDenied`.
- **containers/image v5.26.2** `oci/layout/oci_dest.go`: an OCI layout destination takes only
  `MediaTypeImageManifest` and `MediaTypeImageIndex`, so `skopeo copy … oci:` converts the UBI base's Docker v2s2 manifest
  and changes its digest. **Retracted for a copy with `--preserve-digests`: see "Reviewer 1's corrections".** The `dir:`
  transport keeps the manifest as fetched (`directory_transport.go`: `manifest.json`, and each blob under its encoded digest).
- **OCI image-spec v1.1.1**, `image-layout.md`: "The content of `blobs/<alg>/<encoded>` MUST match the digest", and "The
  blobs directory MAY be missing referenced blobs". So a layout may hold an index with only one platform's image.
- **GitHub Actions workflow syntax** (`github/docs`, `workflow-syntax.md`): there is no retry key for a step;
  `continue-on-error` "Prevents a job from failing when a step fails." **nick-fields/retry v4.0.0** `action.yml`: `command`,
  "The command to run"; it wraps a shell command, not a `uses:` action. **Wandalen/wretry.action** (`action.yml`, default
  branch): `action`, "Github action name", with `with` and `attempt_limit`; it can wrap one.

## The options

| Option | Why not, or why |
|---|---|
| **Fetch the FROM images first, with retries, into an OCI layout; build from it** | Chosen. `deploy/base-images.py` runs skopeo with a doubling wait (5 attempts, 2 s first: 30 s of waits at most, close to the 31 s of #609's `curl --retry 5`), retrying any failure, a 401 included, but not a digest that skopeo found wrong (reviews 1 and 2). The script checks the pinned manifest or index against the pin itself; `skopeo copy --preserve-digests --remove-signatures … oci:<layout>` then copies the image straight into the layout and checks the platform's manifest, the config and each layer against their digests as it copies (review 2's ruling). The build gets `<FROM ref>=oci-layout://…@<pinned digest>` through `build-contexts`, so BuildKit reads the base from the layout and sends no request for it to any registry |
| A `docker pull` with retries before the build | The docker-container driver cannot see the Docker store (Docker docs above). It would retry, and the build would pull again, unretried |
| `driver: docker` with a `docker pull` | Changes how the publisher builds and pushes (`push-by-digest` from the Docker engine), and PR builds would no longer test the publisher's path |
| Warm the builder with a throwaway build of each `FROM`, retried | Leaves the guarantee to BuildKit's cache internals (`imageutil.Config` skips the registry only while the manifest is still in the content store, held by a 5-minute lease); when it is gone, the build pulls again, silently and unretried |
| Retry the whole build step (a second `build-push-action` step on failure, or a wrapper such as Wandalen/wretry.action) | Retries every failure, a compile error or a failing `pip check` too, repeats every network step of the build, re-pushes in `images`, and needs a third-party action. nick-fields/retry wraps only shell commands |
| BuildKit's or skopeo's own retry | Neither retries a 401 (sources above), and BuildKit's is not configurable |
| A local registry service holding the bases (Docker's documented workaround) | Needs `network=host` on the builder, a registry image pulled from Docker Hub, and `--all` copies of the multi-platform bases to keep their digests; the layout does the same with neither |
| `skopeo copy … oci:` straight into a layout | Converts the UBI base's v2s2 manifest to OCI, so the pinned digest is no longer the one the build uses. **Retracted: true only without `--preserve-digests`; see "Reviewer 1's corrections". Taken in review 2, with `--remove-signatures`; see "Reviewer 2's ruling"** |
| Re-running the job by hand | The symptom; the next refused token fails another PR |

**Retrying a 401.** #609 kept curl to its transient codes and rejected `--retry-all-errors` because it would retry a 404. Here
all three tools already refuse to retry a 401, and the failure measured was exactly a 401 that passed on the next attempt. The
script therefore retries any skopeo failure. The cost of a lasting error, a wrong digest or a missing image, is 30 s before the
same failure. (Since review 1 a wrong digest is final on its first attempt; a missing image still costs the 30 s.) The script's own checks (a pinned manifest or index that is not its digest, a `FROM` not pinned by digest, a `FROM` set
by an `ARG`, an image named by `--from=`, a syntax directive, an index with no single image for the platform) are final and
not retried.

## Where

- `deploy/base-images.py`: new.
- `.github/workflows/ci.yml`: a step `base` before the build in `images` (anchored) and `images-pr` (aliased), and in
  `front-door`, whose `docker build` (the Docker engine pulling node and nginx from docker.io, unretried, the same defect)
  becomes `docker/build-push-action` on the docker-container builder with `load: true` and the same tag, `cmapi-portal:ci`.
  Each build gets `build-contexts: ${{ steps.base.outputs.contexts }}`.
- `deploy/tests/download-retry-test.py` and `deploy/tests/ci-guard.py`: extended (below).
- `docs/10-architecture-review.md`, section 8.

Not changed: the Containerfiles (their `FROM` lines and digests stay; a local `podman build` still pulls as before), and
`deploy/release-crc.sh`.

## Tests

| Test | Before (`0a85b4d`, the new tests on the old tree) | After |
|---|---|---|
| `download-retry-test.py`, the base images: each `base-images.py` command of `ci.yml`, with its own `--platform`, `--attempts`, `--delay`, against a stub registry whose token endpoint answers 401 to the first two requests and whose UBI image has a lookaside signature; then all attempts refused; a layer, a config, a manifest, an index and an index's platform manifest that are not their digest, each refused in one attempt; a byte added after skopeo; plain HTTP; a layer listed twice; a layout path with a colon; and six ways an image would reach BuildKit unpinned | FAIL: "ci.yml fetches the base images before it builds an image" | 19 of 19 pass, with skopeo 1.24.1 (this Mac) and with skopeo 1.13.3 (the runner's version, in `quay.io/skopeo/stable:v1.13.3`); the layout holds, for each build context, the blob, the platform's manifest, its config and every layer, each under its SHA-256, and the arm64 image of the index was never requested |
| `download-retry-test.py`, the 17 curl downloads (#609) | unchanged | 17 of 17 pass |
| `ci-guard.py` | FAIL: no base step in the three jobs, `front-door` builds with `docker build` | 98 checks pass |
| Mutant `--attempts 1` in `ci.yml` | | the retry test fails (exit 1 after one refused token) and the guard fails 3 checks |
| Mutant: the script's first failure is final | | the retry test fails; the guard passes (it reads the workflow, not the loop) |
| Mutant: `images` and `images-pr` without `build-contexts` | | the guard fails 2 checks |
| Mutant: `docker build` back in `front-door` | | the guard fails "no job builds an image outside docker/build-push-action" |
| Mutant: `--src-tls-verify=false` on the inspect | | the guard fails on the skopeo commands; the retry test fails too (skopeo has no such flag on `inspect`) |
| `actionlint` 1.7.12 (with shellcheck on the `run` blocks) | exit 0 | exit 0 |
| `base-images.py` against the real registries (this Mac, skopeo 1.24.1) | | exit 0: the UBI manifest kept as Docker v2s2 under `sha256:b99faa…` (4 blobs, 64 MB); node and nginx-unprivileged as their indexes plus the linux/amd64 image (19 blobs, 84 MB); every blob's SHA-256 matches its name |
| The same, review 2's direct copy against the implementer's `dir:` copy (this Mac, skopeo 1.24.1; and skopeo 1.13.3 in its container) | | the same blobs, byte for byte, in each layout of both Containerfiles; only `index.json` differs, which BuildKit does not read for a context named by digest. Without `--remove-signatures`, 1.13.3 in that container failed all 5 attempts on the UBI base: "Can not copy signatures to oci:…: Pushing signatures for OCI images is not supported" |
| Mutants of the final `base-images.py`, `ci.yml` and the tests (`review-666/r2-outputs/mutants.py`) | | 25 of 25 killed with skopeo 1.24.1, each by the retry test, the guard or both: the retry, the doubling wait, each digest check and its finality, TLS, `--preserve-digests`, `--remove-signatures`, the platform, the index in the layout, the context's digest, each way an unpinned image reaches BuildKit, the colon, and two `ci.yml` mutants. Review 2's four script fixes are killed with skopeo 1.13.3 as well |

**On the runner (PR #666, run 45527698703).** `images-pr` for both images and `front-door` passed on the first push. The
`manifests` job failed in this test: skopeo 1.13.3 (containers/image v5.26.2) reads no `CONTAINERS_REGISTRIES_CONF`
(`pkg/sysregistriesv2`, `newConfigWrapperWithHomeDir`: the per-user `$HOME/.config/containers/registries.conf`, or the system
file), so the stub's `insecure = true` was never applied and every call stopped at `tls: first record does not look like a
TLS handshake`. Three refusal cases still passed, because they checked only the exit code. Fixed in the test: the stub's
`registries.conf` is now the per-user file under a `HOME` of its own, which both versions read; the success case asserts
the token endpoint was asked more than twice; and each refusal must name its reason (`unauthorized`, or `did not match` /
`does not match`). Found on the way: skopeo 1.13.3's `inspect --raw` does not check the manifest against the pinned digest
(1.24.1 does: "Manifest does not match provided manifest digest"), so on the runner it is `base-images.py`'s own check that
refuses a wrong manifest.

**Not tested here.** No image was built on this Mac (the owner's rule). That BuildKit v0.35.1 reads each base from the
layout, the v2s2 manifest included, is proved by this PR's CI: `images-pr` for both images and `front-door`, whose logs should
show `[context …] OCI load from client` and no `load metadata for registry.access.redhat.com`. The `images` job runs only on
`main`, after the merge. (Corrected below: the logs do show a `load metadata for` line, and it is the layout's.)

## Reviewer 1's corrections

Fable 5.2, 2026-11-24, on head `4b5fb24`. Each source was fetched and read on that day; each result names where it ran.

**Retracted: "`skopeo copy … oci:` converts the UBI base's v2s2 manifest and changes its digest."** That is so only without
`--preserve-digests`. With it, containers/image v5.26.2 `copy/single.go` sets `cannotModifyManifestReason = "Instructed to
preserve digests"`, and `copy/manifest.go` `determineManifestConversion` then returns the source type: "Take our chances -
FIXME? Or should we fail without trying?"; `oci/layout/oci_dest.go` `PutManifest` files the bytes it is given and sets
`desc.MediaType = manifest.GuessMIMEType(m)`
(<https://github.com/containers/image/blob/v5.26.2/copy/manifest.go>). **Measured** on a stub registry serving a Docker v2s2
manifest, with skopeo 1.24.1 on this Mac and with skopeo 1.13.3 in `quay.io/skopeo/stable:v1.13.3`:
`skopeo copy --preserve-digests docker://…@<pinned> oci:<dir>` exits 0 and `index.json` names the pinned digest as
`application/vnd.docker.distribution.manifest.v2+json`; without the flag it names another digest, as an OCI manifest. So a
direct copy into the layout was open to this change, and the script now makes it: `skopeo copy --preserve-digests …
oci:<layout>`, then the index's own bytes for an index. It no longer files each blob or checks it a third time (skopeo
checks each as it copies, BuildKit as it reads). Not tested on this Mac: BuildKit reading a layout that skopeo wrote. This
pull request's CI run on that commit is the proof, by the same two log lines as below. (Review 2 adds `--remove-signatures`:
see "Reviewer 2's ruling".)

**Corrected: what the build's log shows.** BuildKit v0.35.1 `frontend/dockerui/namedcontext.go` names the layout's metadata
step `[context %s] load metadata for %s` (line 189, the `oci-layout` case) and its load `[context …] OCI load from client`
(line 208). Run 45529793850 shows both for each of the three bases, and no `[internal] load metadata for` line for one. So
the proof is the `[context …]` prefix and the `OCI load from client` line, not the absence of `load metadata for`.

**Changed by review 1** (`deploy/base-images.py`, with a case each in `download-retry-test.py`):

- A manifest that lists one layer twice was refused as "the blob … is missing": the first listing moved the file out of the
  `dir:` directory. skopeo files each digest once now.
- A digest that skopeo finds wrong ("Digest did not match", "does not match provided manifest digest") was tried again, 5
  times over 30 s, and the test hid it with `--attempts 1`. It is final on the first attempt now, and the test runs with the
  workflow's own `--attempts` and counts the requests.
- An image named by `COPY --from=` or `RUN --mount=…,from=`, or a `FROM` behind a byte-order mark (BuildKit's
  `parser.go` drops it: "First line, strip the byte-order-marker if present"), passed unpinned and would have been pulled
  by BuildKit, unretried. Both are refused.
- The script's own check of the pinned manifest had no test that could fail with skopeo 1.24.1, whose check comes first.
  It now runs against a skopeo that adds one byte after the real one. TLS has a behaviour test: the plain-HTTP stub with no setting that allows
  it must be asked for nothing. `ci-guard.py` also pins the one line that runs skopeo.

## Reviewer 2's ruling

Opus 5.5 at `high`, 2026-11-24, on head `4b5fb24` with review 1's two patches. Each source was fetched and read on that day;
each result names where it ran. No image was built.

**Taken: the direct copy into the layout, with `--remove-signatures`.** The script keeps its own check of the pinned manifest
or index, and skopeo checks the rest as it copies: the platform's manifest (containers/image v5.26.2
`internal/image/unparsed.go`: "ImageSource.GetManifest does not do digest verification, but we do"), the config
(`internal/image/docker_schema2.go` and `oci.go`: "Download config.json digest %s does not match expected %s") and each
layer (`copy/digesting_reader.go`: "Digest did not match, expected %s, got %s"); the OCI destination renames a blob into
`blobs/sha256/` only after the whole stream was read without error (`oci/layout/oci_dest.go`, `PutBlobWithOptions`). A test
serves each of the five with one byte changed, on both skopeo versions, and each is refused in one attempt. What the
implementer's `dir:` path added, a third hash of each blob already checked by skopeo, catches nothing those checks miss; and
BuildKit checks each again as it reads (containerd v2.4.2 `core/remotes/handlers.go`: `content.Copy(ctx, cw, rc, desc.Size,
desc.Digest)`; `plugins/content/local/writer.go`: "unexpected commit digest"). BuildKit reads a context named by digest from
the layout's blobs, not from its `index.json` (buildx v0.39.0 `build/opt.go`: `resolveDigest` only when `ref.Digest == ""`;
BuildKit v0.35.1 `source/containerimage/ocilayout.go`, `Resolve`: `store.Info(ctx, dgst)` and the media type from the
blob's bytes), and the two layouts hold the same blobs, byte for byte (table above).

**Found by review 2: an OCI layout cannot hold a signature.** containers/image v5.26.2 `oci/layout/oci_dest.go`:
`stubs.NoSignatures("Pushing signatures for OCI images is not supported")`. Where registries.d names a lookaside for a
registry, skopeo fetches its signatures and the copy fails, every attempt. Fedora's containers-common names one for
registry.access.redhat.com (`/etc/containers/registries.d/registry.access.redhat.com.yaml`, `sigstore:
https://access.redhat.com/webassets/docker/content/sigstore`), so review 1's patch failed on the real UBI base in
`quay.io/skopeo/stable:v1.13.3`. Ubuntu 24.04's packages ship no registries.d file (packages.ubuntu.com, the file lists of
`golang-github-containers-common` and `golang-github-containers-image`), so the runner would likely not have met it; a
Fedora or RHEL runner would. skopeo-copy(1): `--remove-signatures`, "Do not copy signatures, if any, from _source-image_.
Necessary when copying a signed image to a destination which does not support signatures." The script checks no signature
and the `dir:` copy discarded them with its work directory, so nothing is lost. The stub now has a lookaside signature.

**Found by review 2: a config that is not its digest was tried 5 times.** Review 1's `MISMATCH` named the layer's and the
manifest's wording, not the config's: "Download config.json digest … does not match expected …" (v5.26.2) and "config
validation failed: blob digest … does not match expected …" (v5.41.2, skopeo 1.24.1). `MISMATCH` now has `does not match
expected`.

**Found by review 2: a `# syntax=` parser directive.** BuildKit v0.35.1 `frontend/dockerfile/builder/build.go` sends the
build to that frontend image (`parser.DetectSyntax`, then `forwardGateway(ctx, c, ref, cmdline)`), which BuildKit pulls
itself, unretried; so does a `BUILDKIT_SYNTAX` build argument. The script refuses the directive, read as BuildKit reads it
(`parser/directives.go`: after a byte-order mark and a `#!` line, the leading `# key=value` lines), and `ci-guard.py`
refuses the build argument. Neither Containerfile has either today.

**Found by review 2, in the test: the layout was not checked whole.** With the direct copy the script writes the index's
bytes itself; a script that left them out passed review 1's success case, and the build would have failed only in CI. The
success case now walks each build context through the layout as BuildKit will: the blob, an index's platform manifest, the
config and every layer.

**Duplicate layers are valid.** Neither OCI image-spec v1.1.1 `manifest.md` nor the Docker v2s2 specification
(distribution, `manifest-v2-2.md`) asks the layers to be distinct, and `docker.io/library/tomcat:latest`'s linux/amd64
manifest lists `sha256:4f4fb700ef54…` 3 times in 10 layers (measured 2026-11-24). Review 1's finding 1 stands; skopeo's
`oci:` destination files the blob once (`TryReusingBlobWithOptions`).

**What CI must show on this commit.** In each of `front-door`, `images-pr (cmapi, …)` and `images-pr (cmapi-portal, …)`, a
`[context <FROM ref>] OCI load from client` line for each base: `registry.access.redhat.com/ubi9/python-312-minimal@sha256:b99faa…`,
`node@sha256:06d7ad…` and `nginxinc/nginx-unprivileged@sha256:f5116e…`, as run 45529793850 showed for the `dir:` layout; and
no `[internal] load metadata for` line for any of the three. If either is missing, the direct copy is not taken: the
`dir:` path of review 1's `fix.diff` is the fallback.

## The coordinator's rulings and the CI gate

- **Rulings (Opus 5.5).** All of reviewer 1's findings (Fable 5.2, a second model family) are accepted as reviewer 2 (Opus 5.5 high) ruled them.
  - Reviewer 1's simpler design is taken: copy straight into the OCI layout with `--preserve-digests --remove-signatures`.
  - Reviewer 2's three additions are taken:
    - R2-2: a wrong config is final on the first attempt.
    - R2-3: a `syntax` frontend is refused.
    - R2-4: the layout is checked as a whole.
  - Reviewer 2's patch was applied with `patch -p1 -F0`.
- **Local proof (skopeo 1.24.1).** `deploy/tests/ci-guard.py` reports 0 failed cases. `deploy/tests/download-retry-test.py` reports 0 failed for the base images.
- **CI gate (run 45543496938, head `7fcca6e`).** The gate is reviewer 2's: each base loads from its layout, and no base is pulled from a registry. Every job passed.
  - **`images-pr (cmapi)`:** `[context registry.access.redhat.com/ubi9/python-312-minimal@sha256:b99faa…] OCI load from client`.
  - **`images-pr (cmapi-portal)` and `front-door`:** `[context node@sha256:06d7ad…] OCI load from client` and `[context nginxinc/nginx-unprivileged@sha256:f5116e…] OCI load from client`.
  - **All three jobs:** 0 `[internal] load metadata for` lines for any base image.
