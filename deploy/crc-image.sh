#!/usr/bin/env bash
# deploy/crc-image.sh [cmapi|cmapi-portal]: puts CI's image of this commit, cmapi (the default) or the front door's cmapi-portal (#226), in its
# image stream in namespace cmapi, and prints as its last line the reference render.sh takes:
# image-registry.openshift-image-registry.svc:5000/cmapi/<name>@sha256:<digest>.
#
# It builds nothing (#545): a build on this Mac starved the shared CRC VM and restarted 58 containers in run 32. GitHub Actions builds both images
# on each push to main and pushes them to ghcr.io/ephico2real2/<name>:sha-<commit> (.github/workflows/ci.yml, job images), labelled with the
# commit. CRC reads GHCR with the owner's read-only pull secret cmapi-ghcr-pull in namespace cmapi (docs/13, owner step 4), and only CRC does:
# the Mac holds no GHCR credential. The tag is first resolved to its digest without importing anything (an ImageStreamImport with
# import: false, which reads the namespace's pull secrets as an import does). Then that digest, never the tag, is imported with
# referencePolicy Local, so the pods pull through the integrated registry with the namespace's secret. The image stream must then hold GHCR's
# digest, labelled with this commit. An existing sha-<commit> tag is reused only when it already holds GHCR's digest, and refused otherwise.
set -euo pipefail
cd "$(dirname "$0")/.."
OC=${CMAPI_OC:-oc}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
NAME=${1:-cmapi}
case "$NAME" in
  cmapi|cmapi-portal) ;;
  *) echo "ERROR: unknown image $NAME: cmapi or cmapi-portal" >&2; exit 2;;
esac
SOURCE=ghcr.io/ephico2real2/$NAME
INTERNAL=image-registry.openshift-image-registry.svc:5000/cmapi/$NAME
PULL_SECRET=cmapi-ghcr-pull
changes=$(git status --porcelain --untracked-files=no)
[ -z "$changes" ] || { echo "ERROR: the working tree has uncommitted changes; the image must name one commit" >&2; exit 1; }
COMMIT=$(git rev-parse --short=10 HEAD); TAG=sha-$COMMIT

# Compare inside the template so registry label bytes never become shell fields or diagnostics.
label_matches="{{with .dockerImageMetadata.Config.Labels}}{{eq (index . \"org.opencontainers.image.revision\") \"$COMMIT\"}}{{end}}"

# Print only the Secret type from the oc client.
type=$(oc_ get secret "$PULL_SECRET" -n cmapi --ignore-not-found -o 'jsonpath={.type}')
[ -n "$type" ] || { echo "ERROR: Secret $PULL_SECRET is not in namespace cmapi, so CRC cannot read GHCR. The owner creates it: docs/13, \"Steps only the owner can take\", step 4" >&2; exit 1; }
[ "$type" = kubernetes.io/dockerconfigjson ] || { echo "ERROR: Secret $PULL_SECRET is of type $type, not kubernetes.io/dockerconfigjson, so an import does not use it" >&2; exit 1; }

# GHCR's digest of the tag, through the cluster's importer; import: false changes nothing (openshift-apiserver, imagestreamimport/rest.go),
# and a tag GHCR does not have comes back as reason NotFound (importer.go maps the registry's MANIFEST_UNKNOWN to it).
# The registry's free text is in .status.images[].status.message, which the template leaves out; oc's own stderr (a lapsed login, RBAC) stays.
lookup=$(printf '{"apiVersion":"image.openshift.io/v1","kind":"ImageStreamImport","metadata":{"name":"%s","namespace":"cmapi"},"spec":{"import":false,"images":[{"from":{"kind":"DockerImage","name":"%s:%s"}}]}}' "$NAME" "$SOURCE" "$TAG" |
  oc_ create -f - -o "go-template={{range .status.images}}{{.status.status}}|{{with .image}}{{.metadata.name}}|${label_matches}{{else}}|{{end}}|{{with .status.reason}}{{.}}{{end}}{{end}}") || {
  rc=$?; echo "ERROR: CRC could not look up $SOURCE:$TAG (oc exit $rc)" >&2; exit "$rc"
}
IFS='|' read -r status digest matches reason <<<"$lookup"
if [ "$status" != Success ] || [ -z "$digest" ]; then
  case "$reason" in
    NotFound) echo "ERROR: GHCR has no $SOURCE:$TAG. CI pushes it on the push to main of $COMMIT: gh run list --commit $(git rev-parse HEAD) shows that run" >&2;;
    # A package not pushed yet need not answer "not found": GHCR refused a token for one that does not exist (HTTP 403, anonymous, measured 2026-11-21).
    *) echo "ERROR: CRC could not read $SOURCE:$TAG from GHCR. Either CI has not pushed $NAME yet (gh run list --commit $(git rev-parse HEAD)), or Secret $PULL_SECRET cannot read the package: a classic token with read:packages, of an account that can read it" >&2;;
  esac
  exit 1
fi
[[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "ERROR: GHCR returned an invalid SHA-256 digest for $TAG" >&2; exit 1; }
[ "$matches" = true ] || { echo "ERROR: GHCR's $SOURCE:$TAG ($digest) has the wrong revision for $COMMIT" >&2; exit 1; }
echo "GHCR: $SOURCE:$TAG is $digest, labelled $COMMIT" >&2

# A tag pushed before #545 may have no spec tag or reference policy.
read_istag() { oc_ get istag "$NAME:$TAG" -n cmapi "$@" -o "go-template={{.image.metadata.name}}|{{with .tag}}{{.referencePolicy.type}}{{end}}|{{with .image}}${label_matches}{{end}}"; }
existing=$(read_istag --ignore-not-found)
if [ -z "$existing" ]; then
  oc_ import-image "$NAME:$TAG" --from="$SOURCE@$digest" --confirm --reference-policy=local -n cmapi >/dev/null 2>&1 || {
    rc=$?; echo "ERROR: CRC could not import $SOURCE@$digest into $NAME:$TAG (oc exit $rc)" >&2; exit "$rc"
  }
  existing=$(read_istag)
fi
IFS='|' read -r held policy matches <<<"$existing"
[ "$held" = "$digest" ] || { echo "ERROR: image stream tag $NAME:$TAG holds ${held:-nothing}, GHCR's is $digest: not CI's image. Delete the tag (oc delete istag $NAME:$TAG -n cmapi) and run again" >&2; exit 1; }
[ "$policy" = Local ] || { echo "ERROR: image stream tag $NAME:$TAG has referencePolicy '$policy', not Local, so the pods would not pull through the integrated registry. Delete the tag (oc delete istag $NAME:$TAG -n cmapi) and run again" >&2; exit 1; }
[ "$matches" = true ] || { echo "ERROR: image stream tag $NAME:$TAG has the wrong revision for $COMMIT" >&2; exit 1; }
echo "image stream tag $NAME:$TAG holds $digest, labelled $COMMIT" >&2
echo "$INTERNAL@$digest"
