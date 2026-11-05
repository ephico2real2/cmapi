#!/usr/bin/env bash
# Build, push and deploy cmapi to CRC's built-in registry (docs/10, Portability: images are built
# outside the cluster, pushed under an immutable sha-<commit> tag and deployed by digest from
# deploy/images.lock.yaml; the running pod serves the commit at /api/v1/version).
#
#   deploy/release-crc.sh                build both images, push, write the lock file, deploy
#   deploy/release-crc.sh --build-only   build and verify the stamps, push nothing
#   deploy/release-crc.sh --deploy-only  helm upgrade from the lock file, build nothing
#   deploy/release-crc.sh --allow-dirty  tag a dirty tree as sha-<commit>-dirty (never pushed under a clean tag)
#   deploy/release-crc.sh --no-portal    the cmapi image only, for values with portal.enabled: false
#
# Portable nowhere else: the external script for a real registry is the same flow with REGISTRY set.
# A sha-<commit> tag is immutable: pushing a different image under an existing tag is refused.
set -euo pipefail
cd "$(dirname "$0")/.."

REGISTRY="${REGISTRY:-default-route-openshift-image-registry.apps-crc.testing}"
INTERNAL_REGISTRY="${INTERNAL_REGISTRY:-image-registry.openshift-image-registry.svc:5000}"
NAMESPACE="${NAMESPACE:-cmapi}"
RELEASE="${RELEASE:-cmapi}"
RELEASE_VALUES="${RELEASE_VALUES:-deploy/environments/crc.yaml}"
LOCK="deploy/images.lock.yaml"
BUILD_ONLY=false; DEPLOY_ONLY=false; ALLOW_DIRTY=false; BUILD_PORTAL=true
for arg in "$@"; do
  case "$arg" in
    --build-only) BUILD_ONLY=true ;;
    --deploy-only) DEPLOY_ONLY=true ;;
    --allow-dirty) ALLOW_DIRTY=true ;;
    --no-portal) BUILD_PORTAL=false ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

VERSION=$(python3 -c "import re,pathlib;print(re.search(r'^version = \"(.+?)\"',pathlib.Path('cmapi/pyproject.toml').read_text(),re.M).group(1))")
COMMIT=$(git rev-parse --short=10 HEAD)
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  if [ "$ALLOW_DIRTY" != true ]; then
    echo "ERROR: the working tree has uncommitted changes; commit them or pass --allow-dirty" >&2
    git status --short --untracked-files=no >&2
    exit 1
  fi
  COMMIT="${COMMIT}-dirty"
fi
TAG="sha-${COMMIT}"
echo "version : ${VERSION}"
echo "commit  : ${COMMIT}"
echo "tag     : ${TAG}"

stamp_check() {        # image, variable, expected
  local got
  got=$(podman run --rm --entrypoint sh "$1" -c "echo \"\$$2\"" | tr -d '\r\n')
  if [ "$got" != "$3" ]; then echo "ERROR: $1 reports $2='$got', expected '$3'" >&2; exit 1; fi
}

if [ "$DEPLOY_ONLY" != true ]; then
  podman build --build-arg "GIT_COMMIT=${COMMIT}" --build-arg "BUILD_VERSION=${VERSION}" \
    -t "cmapi:${TAG}" -f cmapi/Containerfile cmapi >/dev/null
  stamp_check "cmapi:${TAG}" CMAPI_GIT_COMMIT "${COMMIT}"
  echo "built   : cmapi:${TAG} (stamp verified)"
  IMAGES=(cmapi)
  if [ "$BUILD_PORTAL" = true ]; then
    podman build --build-arg "GIT_COMMIT=${COMMIT}" --build-arg "BUILD_VERSION=${VERSION}" \
      -t "cmapi-portal:${TAG}" -f cmapi-portal-ui/Containerfile . >/dev/null
    stamp_check "cmapi-portal:${TAG}" CMAPI_GIT_COMMIT "${COMMIT}"
    echo "built   : cmapi-portal:${TAG} (stamp verified)"
    IMAGES+=(cmapi-portal)
  fi
  if [ "$BUILD_ONLY" = true ]; then exit 0; fi

  # CRC's registry route is signed by the cluster's ingress CA: trust it, never skip verification.
  CA_DIR=$(mktemp -d)
  oc get cm default-ingress-cert -n openshift-config-managed -o jsonpath='{.data.ca-bundle\.crt}' > "$CA_DIR/ca.crt"
  podman login --cert-dir "$CA_DIR" -u "$(oc whoami)" -p "$(oc whoami -t)" "${REGISTRY}" >/dev/null
  oc get ns "${NAMESPACE}" >/dev/null 2>&1 || oc create ns "${NAMESPACE}" >/dev/null
  : > "$LOCK.tmp"
  echo "# Written by deploy/release-crc.sh: the images the chart deploys, by digest. Commit ${COMMIT}." >> "$LOCK.tmp"
  for img in "${IMAGES[@]}"; do
    if oc get istag "${img}:${TAG}" -n "${NAMESPACE}" >/dev/null 2>&1 && [[ "$TAG" != *-dirty ]]; then
      echo "ERROR: ${img}:${TAG} already exists in the registry; tags are immutable, commit to advance it" >&2; exit 1
    fi
    podman tag "${img}:${TAG}" "${REGISTRY}/${NAMESPACE}/${img}:${TAG}"
    podman push --cert-dir "$CA_DIR" "${REGISTRY}/${NAMESPACE}/${img}:${TAG}" >/dev/null
    DIGEST=$(oc get istag "${img}:${TAG}" -n "${NAMESPACE}" -o jsonpath='{.image.metadata.name}')
    echo "pushed  : ${REGISTRY}/${NAMESPACE}/${img}:${TAG} ${DIGEST}"
    printf '%s:\n  repository: %s/%s/%s\n  tag: %s\n  digest: %s\n' "${img//-/_}" "${INTERNAL_REGISTRY}" "${NAMESPACE}" "${img}" "${TAG}" "${DIGEST}" >> "$LOCK.tmp"
  done
  mv "$LOCK.tmp" "$LOCK"
  rm -rf "$CA_DIR"
fi

if [ ! -f "$RELEASE_VALUES" ]; then
  echo "ERROR: no release values at ${RELEASE_VALUES}; an upgrade without it resets the release to chart defaults" >&2; exit 1
fi
# Public certificates only: the Keycloak CA and the ingress CA, read from the cluster at each release.
TRUST=$(mktemp)
trap 'rm -f "$TRUST"' EXIT
{ oc get secret keycloak-tls -n keycloak -o jsonpath='{.data.ca\.crt}' | base64 -d; echo
  oc get cm default-ingress-cert -n openshift-config-managed -o jsonpath='{.data.ca-bundle\.crt}'; } > "$TRUST"
grep -q 'BEGIN CERTIFICATE' "$TRUST" || { echo "ERROR: no CA certificate read from the cluster" >&2; exit 1; }
# -f every time: helm upgrade starts from chart defaults and applies only what this call passes.
helm upgrade --install "${RELEASE}" deploy/helm/cmapi --namespace "${NAMESPACE}" \
  -f "$RELEASE_VALUES" -f "$LOCK" --set-file "trustedCA.certificates=$TRUST" --wait --timeout 10m
oc rollout status "deploy/${RELEASE}-api" -n "${NAMESPACE}" --timeout=300s
oc rollout status "deploy/${RELEASE}-worker" -n "${NAMESPACE}" --timeout=300s

# The running pod is the build just made, not a cached older one.
RUNNING=$(oc exec -n "${NAMESPACE}" "deploy/${RELEASE}-api" -- sh -c 'echo "$CMAPI_GIT_COMMIT"' | tr -d '\r\n')
LOCKED=$(python3 -c "import yaml;print(yaml.safe_load(open('$LOCK'))['cmapi']['tag'])" | sed 's/^sha-//')
if [ "$RUNNING" != "$LOCKED" ]; then echo "ERROR: the api pod runs commit '${RUNNING}', the lock file says '${LOCKED}'" >&2; exit 1; fi
echo "running : ${RUNNING}, verified in-pod"
