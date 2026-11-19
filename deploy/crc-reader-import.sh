#!/usr/bin/env bash
# Renew CRC's import using the reader ServiceAccount and the CA for the in-cluster API.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OC=${CMAPI_OC:-oc}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }

ca=$(mktemp)
trap 'rm -f "$ca"' EXIT
oc_ get configmap kube-root-ca.crt -n cmapi-system -o 'jsonpath={.data.ca\.crt}' >"$ca"
grep -q 'BEGIN CERTIFICATE' "$ca" || { echo "ERROR: no CA in cmapi-system/kube-root-ca.crt" >&2; exit 1; }

# Take ownership of the import fields previously applied by cmapi-wave1.
{ oc_ create token cmapi-reader -n cmapi-system --duration=168h 2>/dev/null || { echo "ERROR: reader TokenRequest failed" >&2; exit 1; }; } |
  python3 "$HERE/kind-import/import-secret.py" CRC https://kubernetes.default.svc "$ca" |
  { oc_ apply --server-side --field-manager=crc-reader-import.sh --force-conflicts -f - >/dev/null 2>&1 || { echo "ERROR: CRC import apply failed" >&2; exit 1; }; }
echo "import Secret cmapi-imports/cmapi-cluster-crc is current"
