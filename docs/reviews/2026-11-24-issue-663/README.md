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
  and changes its digest. The `dir:` transport keeps the manifest as fetched (`directory_transport.go`: `manifest.json`,
  and each blob under its encoded digest).
- **OCI image-spec v1.1.1**, `image-layout.md`: "The content of `blobs/<alg>/<encoded>` MUST match the digest", and "The
  blobs directory MAY be missing referenced blobs". So a layout may hold an index with only one platform's image.
- **GitHub Actions workflow syntax** (`github/docs`, `workflow-syntax.md`): there is no retry key for a step;
  `continue-on-error` "Prevents a job from failing when a step fails." **nick-fields/retry v4.0.0** `action.yml`: `command`,
  "The command to run"; it wraps a shell command, not a `uses:` action. **Wandalen/wretry.action** (`action.yml`, default
  branch): `action`, "Github action name", with `with` and `attempt_limit`; it can wrap one.

## The options

| Option | Why not, or why |
|---|---|
| **Fetch the FROM images first, with retries, into an OCI layout; build from it** | Chosen. `deploy/base-images.py` runs skopeo with a doubling wait (5 attempts, 2 s first: 30 s of waits at most, close to the 31 s of #609's `curl --retry 5`), retrying any failure, a 401 included. skopeo checks the manifest against the pinned digest and each blob against its own; the script checks each again before it files it. The build gets `<FROM ref>=oci-layout://…@<pinned digest>` through `build-contexts`, so BuildKit reads the base from the layout and sends no request for it to any registry |
| A `docker pull` with retries before the build | The docker-container driver cannot see the Docker store (Docker docs above). It would retry, and the build would pull again, unretried |
| `driver: docker` with a `docker pull` | Changes how the publisher builds and pushes (`push-by-digest` from the Docker engine), and PR builds would no longer test the publisher's path |
| Warm the builder with a throwaway build of each `FROM`, retried | Leaves the guarantee to BuildKit's cache internals (`imageutil.Config` skips the registry only while the manifest is still in the content store, held by a 5-minute lease); when it is gone, the build pulls again, silently and unretried |
| Retry the whole build step (a second `build-push-action` step on failure, or a wrapper such as Wandalen/wretry.action) | Retries every failure, a compile error or a failing `pip check` too, repeats every network step of the build, re-pushes in `images`, and needs a third-party action. nick-fields/retry wraps only shell commands |
| BuildKit's or skopeo's own retry | Neither retries a 401 (sources above), and BuildKit's is not configurable |
| A local registry service holding the bases (Docker's documented workaround) | Needs `network=host` on the builder, a registry image pulled from Docker Hub, and `--all` copies of the multi-platform bases to keep their digests; the layout does the same with neither |
| `skopeo copy … oci:` straight into a layout | Converts the UBI base's v2s2 manifest to OCI, so the pinned digest is no longer the one the build uses |
| Re-running the job by hand | The symptom; the next refused token fails another PR |

**Retrying a 401.** #609 kept curl to its transient codes and rejected `--retry-all-errors` because it would retry a 404. Here
all three tools already refuse to retry a 401, and the failure measured was exactly a 401 that passed on the next attempt. The
script therefore retries any skopeo failure. The cost of a lasting error, a wrong digest or a missing image, is 30 s before the
same failure. The script's own checks (a manifest or blob that is not its digest, a `FROM` not pinned by digest, a `FROM` set
by an `ARG`, an index with no single image for the platform) are final and not retried.

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
| `download-retry-test.py`, the base images: each `base-images.py` command of `ci.yml`, with its own `--platform`, `--attempts`, `--delay`, against a stub registry whose token endpoint answers 401 to the first two requests; then all attempts refused, a layer and a manifest that are not their digest, and a `FROM` not pinned | FAIL: "ci.yml fetches the base images before it builds an image" | 6 of 6 pass; the layout holds both stub images, every blob under its SHA-256, and the arm64 image of the index was never requested |
| `download-retry-test.py`, the 17 curl downloads (#609) | unchanged | 17 of 17 pass |
| `ci-guard.py` | FAIL: no base step in the three jobs, `front-door` builds with `docker build` | 94 checks pass |
| Mutant `--attempts 1` in `ci.yml` | | the retry test fails (exit 1 after one refused token) and the guard fails 3 checks |
| Mutant: the script's first failure is final | | the retry test fails; the guard passes (it reads the workflow, not the loop) |
| Mutant: `images` and `images-pr` without `build-contexts` | | the guard fails 2 checks |
| Mutant: `docker build` back in `front-door` | | the guard fails "no job builds an image outside docker/build-push-action" |
| Mutant: `--src-tls-verify=false` on the inspect | | the guard fails on the skopeo commands; the retry test fails too (skopeo has no such flag on `inspect`) |
| `actionlint` 1.7.12 (with shellcheck on the `run` blocks) | exit 0 | exit 0 |
| `base-images.py` against the real registries (this Mac, skopeo 1.24.1) | | exit 0: the UBI manifest kept as Docker v2s2 under `sha256:b99faa…` (4 blobs, 64 MB); node and nginx-unprivileged as their indexes plus the linux/amd64 image (19 blobs, 84 MB); every blob's SHA-256 matches its name |

**Not tested here.** No image was built on this Mac (the owner's rule). That BuildKit v0.35.1 reads each base from the
layout, the v2s2 manifest included, and builds the same image, is proved only by this PR's CI: `images-pr` for both images
and `front-door`, whose logs should show `[context …] OCI load from client` and no `load metadata for
registry.access.redhat.com`. The `images` job runs only on `main`, after the merge.
