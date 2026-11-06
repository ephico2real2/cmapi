#!/usr/bin/env bash
# deploy/render.sh <environment> <cmapi image> [<out dir>]
# Plain YAML in, plain YAML out: copies deploy/manifests/components/ and deploy/manifests/environments/<environment>/ into
# <out dir> (default deploy/rendered/<environment>) with two placeholders filled: ghcr.io/ephico2real2/cmapi@sha256:DIGEST by
# <cmapi image>, and CMAPI_CONFIG_CHECKSUM by the checksum of the environment's cmapi-env, cmapi-config and cmapi-trust. The
# process reads its configuration once, at start, so that checksum in the api's and the worker's pod templates is what makes
# a changed ConfigMap restart them. The image must be by digest, from GHCR or CRC's internal registry (Wave 1); anything else
# is accepted only with --allow-tag, for a locally built image, on environment kind only. The out dir is replaced whole, and
# only when it is empty or an earlier render (the marker .cmapi-render). It is built beside the out dir and renamed into place
# only once every check has passed, so a failed render leaves the last good one untouched.
set -euo pipefail
ALLOW_TAG=false; ARGS=()
for a in "$@"; do if [ "$a" = --allow-tag ]; then ALLOW_TAG=true; else ARGS+=("$a"); fi; done
set -- ${ARGS[@]+"${ARGS[@]}"}
ENV_NAME=${1:?environment (a folder under deploy/manifests/environments)}
IMAGE=${2:?cmapi image, ghcr.io/ephico2real2/cmapi@sha256:<digest>}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${3:-$HERE/rendered/$ENV_NAME}
PLACEHOLDER='ghcr.io/ephico2real2/cmapi@sha256:DIGEST'
CHECKSUM_PLACEHOLDER=CMAPI_CONFIG_CHECKSUM
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi | cut -d' ' -f1; }
# config_checksum DIR: SHA-256 over one "name sha256" line per ConfigMap, in this fixed order, so that it depends on the three
# files' bytes alone: not on their paths or the locale, and no bytes can move between two files unseen. A comment counts: a
# restart too many is cheap, a stale process is not. The file that declares each is found by its name, so an environment may
# lay them out as it likes; the Deployments cannot start without any of the three, so a missing one stops the render here.
config_checksum() {
  local name files
  for name in cmapi-env cmapi-config cmapi-trust; do
    files=$(grep -lE "^  name: ${name}\$" "$1"/*.yaml 2>/dev/null || true)
    case "$files" in
      "") echo "ERROR: no file in $1 declares ConfigMap $name" >&2; exit 1;;
      *$'\n'*) echo "ERROR: more than one file in $1 declares ConfigMap $name: $(echo "$files" | tr '\n' ' ')" >&2; exit 1;;
    esac
    printf '%s %s\n' "$name" "$(sha256 <"$files")"
  done | sha256
}
if ! [[ "$IMAGE" =~ ^(ghcr\.io/ephico2real2/cmapi|image-registry\.openshift-image-registry\.svc:5000/cmapi/cmapi)@sha256:[0-9a-f]{64}$ ]]; then
  if [ "$ALLOW_TAG" = true ] && [ "$ENV_NAME" = kind ]; then
    echo "note    : ${IMAGE} is not a GHCR digest; accepted because of --allow-tag (a kind test, never a deployment)"
  else
    echo "ERROR: ${IMAGE} is not ghcr.io/ephico2real2/cmapi@sha256:<64 hex> or the internal registry's; a deployment is by digest only (--allow-tag for a kind test, on environment kind)" >&2; exit 1
  fi
fi
[ -d "$HERE/manifests/environments/$ENV_NAME" ] || { echo "ERROR: no environment $ENV_NAME under deploy/manifests/environments" >&2; exit 1; }
CHECKSUM=$(config_checksum "$HERE/manifests/environments/$ENV_NAME")
# It deletes what it replaces, so only what it wrote: a mistyped out dir must not take a directory with it. A dangling symlink
# is refused too: it is not an empty place to write, and the rename below could not replace it.
if { [ -e "$OUT" ] || [ -L "$OUT" ]; } && { [ ! -d "$OUT" ] || { [ -n "$(ls -A "$OUT")" ] && [ ! -e "$OUT/.cmapi-render" ]; }; }; then
  echo "ERROR: $OUT exists and is not an earlier render (no .cmapi-render); not replacing it" >&2; exit 1
fi
OUT=${OUT%/}   # mv on "link/" moves what the link points at, not the link
OUT_PARENT=$(dirname "$OUT"); mkdir -p "$OUT_PARENT"
# Beside the out dir: a rename is only a rename on one file system. mktemp's directory is 0700, so the tree is a mkdir inside it
# and the out dir keeps the umask's mode.
WORK=$(mktemp -d "$OUT_PARENT/.$(basename "$OUT").render.XXXXXX")
# On every way out: the last good render back in place if the swap stopped half way, and the working directory gone.
cleanup() {
  rc=$?
  if [ -e "$WORK/old" ] && [ ! -e "$OUT" ]; then
    mv "$WORK/old" "$OUT" || { echo "ERROR: could not put the last render back; it is in $WORK/old" >&2; exit 1; }
  fi
  rm -rf "$WORK"; exit "$rc"
}
trap cleanup EXIT
NEW=$WORK/new; mkdir "$NEW"; : >"$NEW/.cmapi-render"
cp -R "$HERE/manifests/components" "$NEW/components"
cp -R "$HERE/manifests/environments/$ENV_NAME" "$NEW/environment"
# sed on YAML, on purpose: no templating language in the path. Each placeholder is a whole value.
find "$NEW" -name '*.yaml' -print0 | while IFS= read -r -d '' f; do
  sed -i.bak -e "s|${PLACEHOLDER}|${IMAGE}|g" -e "s|${CHECKSUM_PLACEHOLDER}|${CHECKSUM}|g" "$f" && rm -f "$f.bak"
done
if grep -rnE "sha256:DIGEST|${CHECKSUM_PLACEHOLDER}" "$NEW" >/dev/null; then
  echo "ERROR: a placeholder was not filled:" >&2; grep -rnE "sha256:DIGEST|${CHECKSUM_PLACEHOLDER}" "$NEW" >&2; exit 1
fi
printf '%s\n' "$IMAGE" > "$NEW/IMAGE"
if [ -e "$OUT" ]; then mv "$OUT" "$WORK/old"; fi
mv "$NEW" "$OUT"
echo "rendered: ${OUT} for ${ENV_NAME} with ${IMAGE}"
