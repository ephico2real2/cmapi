#!/usr/bin/env bash
# The baseline CRC needs before a request can be delivered: the reader and the token issuer, then the import Secret that
# gives cmapi the reader's token. Idempotent. The token goes from one Secret to the other through a file, never an argument.
#
#   deploy/baseline-crc.sh [cluster id, default CRC] [imports namespace, default cmapi-imports]
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER_ID="${1:-CRC}"
IMPORTS="${2:-cmapi-imports}"
oc apply --server-side -f examples/baseline/cmapi-reader-rbac.yaml
for _ in $(seq 1 30); do
  TOKEN_B64=$(oc get secret cmapi-reader-token -n cmapi-system -o jsonpath='{.data.token}')
  [ -n "$TOKEN_B64" ] && break
  sleep 1
done
[ -n "$TOKEN_B64" ] || { echo "ERROR: Secret cmapi-reader-token has no token after 30 s" >&2; exit 1; }
CA_B64=$(oc get secret cmapi-reader-token -n cmapi-system -o jsonpath='{.data.ca\.crt}')
FILE=$(mktemp); trap 'rm -f "$FILE"' EXIT; chmod 600 "$FILE"
cat > "$FILE" <<YAML
apiVersion: v1
kind: Secret
metadata:
  name: cmapi-cluster-$(echo "$CLUSTER_ID" | tr '[:upper:]_' '[:lower:]-')
  namespace: ${IMPORTS}
  labels: {cmapi.net/secret-type: cluster, cmapi.net/cluster-id: ${CLUSTER_ID}}
type: Opaque
data:
  apiUrl: $(printf 'https://kubernetes.default.svc' | base64 | tr -d '\n')
  token: ${TOKEN_B64}
  caData: ${CA_B64}
YAML
oc apply --server-side -f "$FILE"
echo "baseline done: reader, token issuer, import Secret for ${CLUSTER_ID} in ${IMPORTS}"
