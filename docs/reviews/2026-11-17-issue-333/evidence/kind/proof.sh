#!/bin/bash
# The kind proof of #333 and #345: Kyverno v1.20.0 on the cmapi-test cluster, the dev bundle in audit.
#   proof.sh install | before | after | outside | show <ns>
# Every kubectl call names the kubeconfig of this cluster; nothing else is touched.
set -uo pipefail
D=/Users/olasumbo/gitRepos/workbench/cmapi/ob-333/kind
K="kubectl --kubeconfig $D/kubeconfig --context kind-cmapi-test"

# The results of the cluster's report for one namespace: policy, result, message, process, timestamp.
show() {
  $K get clusterpolicyreports.wgpolicyk8s.io -o json 2>/dev/null | python3 -c '
import json, sys
ns = sys.argv[1]
for r in json.load(sys.stdin)["items"]:
    if (r.get("scope") or {}).get("name") != ns:
        continue
    for x in sorted(r.get("results", []), key=lambda x: x["policy"]):
        if "metadata" in x["policy"]:
            print(x["policy"], x["result"], x["timestamp"]["seconds"], str(x.get("properties", {}).get("process")).replace(" ", "_"), "|", x.get("message", ""))
' "$1"
}

# Wait until the namespace's report holds a result of the policy that was written after the given time (UNIX seconds).
wait_for() {   # ns policy since timeout
  for _ in $(seq 1 "$4"); do
    if show "$1" | awk -v p="$2" -v t="$3" '$1 == p && $3 >= t {f=1} END {exit !f}'; then return 0; fi
    sleep 5
  done
  echo "no result of $2 for $1 after $3 within $(( $4 * 5 ))s"; return 1
}

case "$1" in
  install)
    $K create -f "$D/install.yaml" >/dev/null 2>"$D/install.err"; tail -3 "$D/install.err"
    $K -n kyverno rollout status deploy --timeout=300s
    $K -n kyverno get deploy -o custom-columns=NAME:.metadata.name,IMAGE:.spec.template.spec.containers[0].image
    ;;
  before|after)
    side=$1; ns=$([ "$side" = before ] && echo payments-dev || echo orders-dev)
    echo "== $side: $([ "$side" = before ] && echo "the branch's bundle without #345's evaluation.background setting (with #333 and #356)" || echo "the branch's bundle")"
    # In place: the after bundle upgrades the before bundle as a re-render reaches a cluster (same names).
    $K apply -f "$D/$side/bundle-original" >/dev/null && $K get validatingpolicies.policies.kyverno.io --no-headers | wc -l | xargs echo "policies:"
    sleep 15   # the admission webhook's policy cache
    if [ "$side" = after ]; then echo "-- payments-dev (from before) once the fixed bundle is applied:"; show payments-dev; fi
    t0=$(date +%s)
    $K apply -f "$D/$side/ns-$ns.yaml" 2>&1
    wait_for "$ns" cmapi-metadata-dev-label-cmapi-net-cost-center-pattern "$t0" 60
    echo "-- $ns created under the original rule (^cc-[0-9]{4}\$), its report:"; show "$ns"
    t1=$(date +%s)
    echo "-- cost-center tightened to ^cc-[0-9]{5}\$: cc-4410 is a value that cmapi keeps"
    # Applied in place, as a re-rendered bundle reaches a cluster: the same policy names, a new rule.
    $K apply -f "$D/$side/bundle-tightened" >/dev/null && echo "tightened bundle applied in place"
    if [ "$side" = before ]; then
      wait_for "$ns" cmapi-metadata-dev-label-cmapi-net-cost-center-pattern "$t1" 120
    else
      # The pattern policy is not scanned: wait for a policy that is (the background scan ran), then read.
      wait_for "$ns" cmapi-metadata-dev-label-other-keys-prefix "$t1" 120
    fi
    echo "-- after the background scan, its report:"; show "$ns"
    ;;
  outside)
    ns=orders-dev
    t2=$(date +%s)
    echo "== a change outside cmapi: kubectl label namespace $ns other.example/x=1 cmapi.net/team=orders"
    $K label namespace "$ns" other.example/x=1 cmapi.net/team=orders --overwrite 2>&1
    wait_for "$ns" cmapi-metadata-dev-label-other-keys-prefix "$t2" 60
    sleep 20
    echo "-- its report:"; show "$ns"
    ;;
  show) show "$2" ;;
esac
