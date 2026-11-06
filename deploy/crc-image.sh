#!/usr/bin/env bash
# deploy/crc-image.sh: builds the cmapi image from this commit outside the cluster and pushes it to CRC's internal registry, printing as its last
# line the reference render.sh takes: image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:<digest>. skopeo pushes, because it runs on
# this Mac: podman here is a remote client, so its --cert-dir is not honoured on push and the machine's VM does not trust the route's CA (measured).
# The credential is the current oc session's token, written once to a 0600 file in a 0700 directory removed at exit, passed by path; never an argument,
# and no gh token or GHCR credential is involved. TLS verification stays on, against the ingress CA. An existing sha-<commit> tag is immutable:
# it is reused when its label names this commit, and refused otherwise.
set -euo pipefail
cd "$(dirname "$0")/.."
OC=${CMAPI_OC:-oc}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
INTERNAL=image-registry.openshift-image-registry.svc:5000/cmapi/cmapi
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "ERROR: the working tree has uncommitted changes; the image must name one commit" >&2; exit 1; }
COMMIT=$(git rev-parse --short=10 HEAD); TAG=sha-$COMMIT
VERSION=$(sed -n 's/^version = "\(.*\)"$/\1/p' cmapi/pyproject.toml | head -1)
existing=$(oc_ get istag "cmapi:$TAG" -n cmapi --ignore-not-found -o 'jsonpath={.image.metadata.name} {.image.dockerImageMetadata.Config.Labels.org\.opencontainers\.image\.revision}')
if [ -n "$existing" ]; then
  [ "${existing#* }" = "$COMMIT" ] || { echo "ERROR: cmapi:$TAG in the registry is labelled ${existing#* }, not $COMMIT" >&2; exit 1; }
  echo "$TAG is already in the registry, labelled $COMMIT" >&2
  echo "$INTERNAL@${existing%% *}"; exit 0
fi
W=$(mktemp -d); chmod 700 "$W"; trap 'rm -rf "$W"' EXIT
HOST=$(oc_ get route default-route -n openshift-image-registry -o 'jsonpath={.spec.host}')
mkdir "$W/certs"
oc_ get cm default-ingress-cert -n openshift-config-managed -o 'jsonpath={.data.ca-bundle\.crt}' >"$W/certs/ca.crt"
grep -q 'BEGIN CERTIFICATE' "$W/certs/ca.crt" || { echo "ERROR: no ingress CA read from the cluster" >&2; exit 1; }
# Token on stdin, file created 0600 before a byte is written.
oc_ whoami -t | python3 -c 'import base64,json,os,sys
fd=os.open(sys.argv[2],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
os.write(fd,json.dumps({"auths":{sys.argv[1]:{"auth":base64.b64encode(("unused:"+sys.stdin.read().strip()).encode()).decode()}}}).encode())' "$HOST" "$W/auth.json"
podman build --platform linux/amd64 --build-arg "GIT_COMMIT=$COMMIT" --build-arg "BUILD_VERSION=$VERSION" -t "localhost/cmapi:$TAG" -f cmapi/Containerfile cmapi >&2
built=$(podman image inspect "localhost/cmapi:$TAG" --format '{{index .Labels "org.opencontainers.image.revision"}}')
[ "$built" = "$COMMIT" ] || { echo "ERROR: the image is labelled $built, not $COMMIT" >&2; exit 1; }
podman save --format oci-archive -o "$W/image.tar" "localhost/cmapi:$TAG" >/dev/null
skopeo copy -q --dest-cert-dir "$W/certs" --dest-authfile "$W/auth.json" --digestfile "$W/digest" "oci-archive:$W/image.tar" "docker://$HOST/cmapi/cmapi:$TAG" >&2
digest=$(cat "$W/digest")
registry=$(oc_ get istag "cmapi:$TAG" -n cmapi -o 'jsonpath={.image.metadata.name}')
[ "$digest" = "$registry" ] || { echo "ERROR: pushed $digest, the image stream says $registry" >&2; exit 1; }
echo "$INTERNAL@$digest"
