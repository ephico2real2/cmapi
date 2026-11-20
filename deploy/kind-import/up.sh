#!/usr/bin/env bash
# deploy/kind-import/up.sh <cmapi-cluster-configs checkout>: the kind cluster cmapi-test, imported into cmapi on CRC as KIND_CMAPI_TEST
# (docs/13, "A second cluster: kind"). The baseline's work by hand (docs/02, "Cluster connections and auto-import"), in order:
#   1. stop unless kind-cmapi-test.yaml, the pf anchor and this Mac's LAN address agree, oc is CRC's, and the checkout holds a
#      clean policies/env/rnd
#   2. create cmapi-test from kind-cmapi-test.yaml, or reuse it when it is there
#   3. stop unless its served certificate names the address and host.crc.testing, and kind's CA verifies it
#   4. apply the reader (reader.yaml) on kind
#   5. Kyverno and the rnd bundle from the checkout on kind (kyverno.sh, #430)
#   6. pipe a bounded TokenRequest token into Secret cmapi-imports/cmapi-cluster-kind-cmapi-test on CRC
# Run it again to rotate: each run writes a new token. The token goes from kubectl to oc through pipes alone: never an argument, a
# file or a line of output. The import is read only until clusters.yaml has the KIND_CMAPI_TEST entry. Exits non-zero on the first failure.
set -euo pipefail
# shellcheck source=SCRIPTDIR/common.sh
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
{ [ $# = 1 ] && [[ $1 != -* ]]; } || { echo "usage: $0 <cmapi-cluster-configs checkout>" >&2; exit 2; }

# shellcheck source=SCRIPTDIR/write-import.sh
source "$HERE/write-import.sh"
duration=$(python3 "$HERE/import-secret.py" --request-duration)
check_config
address_held || moved
check_hub
check_bundle "$1"
if cluster_exists; then
  say "kind cluster $NAME exists: reused, and its token rewritten"
  kind export kubeconfig --name "$NAME" --kubeconfig "$KC" >/dev/null 2>&1 || die "kind export kubeconfig --name $NAME failed"
else
  say "creating kind cluster $NAME from $CONFIG"
  kind create cluster --config "$CONFIG" --kubeconfig "$KC" --wait 180s
fi
check_kind_target
check_served

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
kc config view --raw --minify -o 'jsonpath={.clusters[0].cluster.certificate-authority-data}' |
  python3 -c 'import base64,sys; sys.stdout.write(base64.b64decode(sys.stdin.read()).decode())' >"$T/ca.pem"
grep -q 'BEGIN CERTIFICATE' "$T/ca.pem" || die "no CA in $KC"
curl -fsS -m 10 --cacert "$T/ca.pem" "https://$ADDRESS:$PORT/version" >/dev/null || die "kind's CA does not verify https://$ADDRESS:$PORT"
say "https://$ADDRESS:$PORT verifies against kind's CA"

kc apply --server-side --field-manager="$FIELD_MANAGER" -f "$HERE/reader.yaml" >/dev/null
say "reader applied on $NAME: cmapi-system/cmapi-reader and ClusterRole cmapi-reader"
"$HERE/kyverno.sh" "$1"

# Finish the issuer and renderer before apply. Keep credentials out of xtrace, argv and exported variables.
set +ax
unset import_document
version=$(import_version "$SECRET" "$HUB_NS")
import_document=$(kc create token cmapi-reader -n cmapi-system --duration="$duration" 2>/dev/null |
  python3 "$HERE/import-secret.py" "$CLUSTER_ID" "https://$ADDRESS:$PORT" "$T/ca.pem" host.crc.testing --resource-version "$version") ||
  die "reader TokenRequest or import validation failed"
builtin printf '%s\n' "$import_document" |
  write_import "$FIELD_MANAGER" "$version" >/dev/null 2>&1 ||
  die "kind import apply failed"
say "Secret $HUB_NS/$SECRET is current on CRC; cmapi picks it up at its next relist (up to 5 min)"
