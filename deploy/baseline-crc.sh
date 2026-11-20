#!/usr/bin/env bash
# The baseline CRC needs before a request can be delivered: the reader and the token issuer, then the import Secret that
# gives cmapi a bounded reader token.
#
#   deploy/baseline-crc.sh [cluster id, default CRC] [imports namespace, default cmapi-imports]
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER_ID="${1:-CRC}"
IMPORTS="${2:-cmapi-imports}"
oc apply --server-side -f examples/baseline/cmapi-reader-rbac.yaml
CMAPI_OC=oc deploy/crc-reader-import.sh "$CLUSTER_ID" "$IMPORTS"
echo "baseline done: reader, token issuer, import Secret for ${CLUSTER_ID} in ${IMPORTS}"
