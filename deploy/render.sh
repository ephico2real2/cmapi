#!/usr/bin/env bash
# deploy/render.sh <environment> <cmapi image> [<out dir>]
# Plain YAML in, plain YAML out: copies deploy/manifests/components/ and deploy/manifests/environments/<environment>/ into
# <out dir> (default deploy/rendered/<environment>) with the one placeholder, ghcr.io/ephico2real2/cmapi@sha256:DIGEST,
# replaced by <cmapi image>. The image must be by digest (ghcr.io/ephico2real2/cmapi@sha256:<64 hex>); a tag is accepted
# only with --allow-tag, for a locally built image on a kind cluster. The last step fails if any placeholder is left.
set -euo pipefail
ALLOW_TAG=false
for a in "$@"; do [ "$a" = --allow-tag ] && ALLOW_TAG=true; done
set -- "${@/--allow-tag/}"
ENV_NAME=${1:?environment (a folder under deploy/manifests/environments)}
IMAGE=${2:?cmapi image, ghcr.io/ephico2real2/cmapi@sha256:<digest>}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${3:-$HERE/rendered/$ENV_NAME}
PLACEHOLDER='ghcr.io/ephico2real2/cmapi@sha256:DIGEST'
if ! [[ "$IMAGE" =~ ^ghcr\.io/ephico2real2/cmapi@sha256:[0-9a-f]{64}$ ]]; then
  if [ "$ALLOW_TAG" = true ]; then
    echo "note    : ${IMAGE} is not a GHCR digest; accepted because of --allow-tag (a kind test, never a deployment)"
  else
    echo "ERROR: ${IMAGE} is not ghcr.io/ephico2real2/cmapi@sha256:<64 hex>; a deployment is by digest only (--allow-tag for a kind test)" >&2; exit 1
  fi
fi
[ -d "$HERE/manifests/environments/$ENV_NAME" ] || { echo "ERROR: no environment $ENV_NAME under deploy/manifests/environments" >&2; exit 1; }
rm -rf "$OUT"; mkdir -p "$OUT"
cp -R "$HERE/manifests/components" "$OUT/components"
cp -R "$HERE/manifests/environments/$ENV_NAME" "$OUT/environment"
# sed on YAML, on purpose: no templating language in the path. The placeholder is a whole image reference.
find "$OUT" -name '*.yaml' -print0 | while IFS= read -r -d '' f; do
  sed -i.bak "s|${PLACEHOLDER}|${IMAGE}|g" "$f" && rm -f "$f.bak"
done
if grep -rn 'sha256:DIGEST' "$OUT" >/dev/null; then
  echo "ERROR: an image placeholder was not filled:" >&2; grep -rn 'sha256:DIGEST' "$OUT" >&2; exit 1
fi
printf '%s\n' "$IMAGE" > "$OUT/IMAGE"
echo "rendered: ${OUT} for ${ENV_NAME} with ${IMAGE}"
