#!/usr/bin/env bash
# Renew CRC's import using the reader ServiceAccount and the CA for the in-cluster API.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
cluster_id=${1:-CRC}
namespace=${2:-cmapi-imports}
OC=${CMAPI_OC:-oc}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }

# shellcheck source=SCRIPTDIR/kind-import/write-import.sh
source "$HERE/kind-import/write-import.sh"
duration=$(python3 "$HERE/kind-import/import-secret.py" --request-duration)
ca=$(mktemp)
trap 'rm -f "$ca"' EXIT
oc_ get configmap kube-root-ca.crt -n cmapi-system -o 'jsonpath={.data.ca\.crt}' >"$ca"
grep -q 'BEGIN CERTIFICATE' "$ca" || { echo "ERROR: no CA in cmapi-system/kube-root-ca.crt" >&2; exit 1; }

# Finish and check both producers before allowing the API write. Keep the
# rendered Secret in shell memory, including under bash -x or set -a.
set +ax
unset import_document
request_token() {
  oc_ create token cmapi-reader -n cmapi-system --duration="$duration" 2>/dev/null || {
    echo "ERROR: reader TokenRequest failed" >&2
    return 1
  }
}
name=$(printf 'cmapi-cluster-%s' "$cluster_id" | tr 'A-Z_' 'a-z-')
version=$(import_version "$name" "$namespace")
import_document=$(request_token | python3 "$HERE/kind-import/import-secret.py" "$cluster_id" https://kubernetes.default.svc "$ca" --namespace "$namespace" --resource-version "$version")

# Take ownership of the import fields previously applied by cmapi-wave1.
if ! builtin printf '%s\n' "$import_document" |
  write_import crc-reader-import.sh "$version" >/dev/null 2>&1; then
  echo "ERROR: CRC import apply failed" >&2
  exit 1
fi
echo "import Secret for $cluster_id in $namespace is current"
