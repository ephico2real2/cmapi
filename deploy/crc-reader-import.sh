#!/usr/bin/env bash
# deploy/crc-reader-import.sh: the part of the reader baseline that cannot be plain YAML, the import Secret holding the reader's token. The token goes from one
# Secret to the other through a pipe: no file, no argument. Idempotent. A token Secret the controller has not filled stops it after 30 s.
set -euo pipefail
OC=${CMAPI_OC:-oc}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
for _ in $(seq 1 30); do
  json=$(oc_ get secret cmapi-reader-token -n cmapi-system -o json)
  ready=$(printf '%s' "$json" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("data") or {}; print("yes" if d.get("token") and d.get("ca.crt") else "no")')
  [ "$ready" = yes ] && break
  sleep "${CMAPI_READER_POLL:-1}"
done
[ "$ready" = yes ] || { echo "ERROR: Secret cmapi-reader-token has no token after 30 tries" >&2; exit 1; }
printf '%s' "$json" | python3 -c 'import base64,json,sys
d=json.load(sys.stdin)["data"]
print(json.dumps({"apiVersion":"v1","kind":"Secret","type":"Opaque",
  "metadata":{"name":"cmapi-cluster-crc","namespace":"cmapi-imports","labels":{"cmapi.net/secret-type":"cluster","cmapi.net/cluster-id":"CRC","app.kubernetes.io/part-of":"cmapi"}},
  "data":{"apiUrl":base64.b64encode(b"https://kubernetes.default.svc").decode(),"token":d["token"],"caData":d["ca.crt"]}}))' | oc_ apply --server-side --field-manager=cmapi-wave1 -f - >/dev/null
echo "import Secret cmapi-imports/cmapi-cluster-crc is current"
