#!/usr/bin/env bash
# deploy/kind-import/down.sh [--stale]: removes what up.sh made, each by name: Secret cmapi-imports/cmapi-cluster-kind-cmapi-test on CRC
# first, so cmapi retires KIND_CMAPI_TEST (docs/02, "Discovery") instead of reading it as unreachable, then the kind cluster cmapi-test.
# Run before every CRC deploy: crc-guard.py preflight stops on any kind cluster (#157). Nothing else is deleted: no other cluster,
# no label selector, no --all. It stops when the Mac no longer holds the address of kind-cmapi-test.yaml; --stale deletes both anyway,
# which is the first step of moving to a new address. Exits non-zero on the first failure.
set -euo pipefail
# shellcheck source=SCRIPTDIR/common.sh
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
stale=false
case "${1:-}" in --stale) stale=true;; "") ;; *) echo "usage: $0 [--stale]" >&2; exit 2;; esac

check_config
check_hub
exists=false; cluster_exists && exists=true
if [ "$stale" = false ]; then
  address_held || moved
  [ "$exists" = false ] || check_served
fi

if [ -n "$(oc_ get secret "$SECRET" -n "$HUB_NS" --ignore-not-found -o name)" ]; then
  id=$(oc_ get secret "$SECRET" -n "$HUB_NS" -o 'jsonpath={.metadata.labels.cmapi\.net/cluster-id}')
  [ "$id" = "$CLUSTER_ID" ] || die "Secret $HUB_NS/$SECRET is labelled cluster-id '$id', not $CLUSTER_ID: not up.sh's, left as it is"
  oc_ delete secret "$SECRET" -n "$HUB_NS"
else
  say "no Secret $HUB_NS/$SECRET"
fi
if [ "$exists" = true ]; then
  kind delete cluster --name "$NAME" --kubeconfig "$KC"
else
  say "no kind cluster $NAME"
fi
say "done: $NAME and its import are gone"
