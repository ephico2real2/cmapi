#!/usr/bin/env bash
# Who reaches port 8080 of a pod the policy selects: another namespace's pod, this namespace's pod, kubectl port-forward. On
# kind cluster cmapi-pr89-a. usage: np-reach-test.sh <kubeconfig> <policy file>
set -uo pipefail
KC=$1; POLICY=$2; IMG=docker.io/nginxinc/nginx-unprivileged@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6
k() { kubectl --kubeconfig="$KC" "$@"; }
[ "$(k config current-context)" = kind-cmapi-pr89-a ] || { echo "wrong context"; exit 9; }
k create ns np-other >/dev/null 2>&1 || true
k delete networkpolicy cmapi-metrics -n cmapi --ignore-not-found >/dev/null
for spec in "cmapi np-api api" "cmapi np-same mockup" "np-other np-out mockup"; do set -- $spec
  k -n "$1" get pod "$2" >/dev/null 2>&1 || k -n "$1" run "$2" --image="$IMG" --image-pull-policy=IfNotPresent --labels="app.kubernetes.io/component=$3" >/dev/null
done
k -n cmapi wait pod/np-api pod/np-same --for=condition=Ready --timeout=120s >/dev/null; k -n np-other wait pod/np-out --for=condition=Ready --timeout=120s >/dev/null
IP=$(k -n cmapi get pod np-api -o jsonpath='{.status.podIP}')
reach() { if k -n "$1" exec "$2" -- wget -q -O /dev/null --timeout=4 "http://$IP:8080/" 2>/dev/null; then echo reached; else echo blocked; fi; }
pf() { k -n cmapi port-forward pod/np-api 18099:8080 >/dev/null 2>&1 & local p=$!; perl -e 'select(undef,undef,undef,2)'; curl -s -o /dev/null -m 4 -w '%{http_code}' http://127.0.0.1:18099/; pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; }
echo "no policy        : other ns $(reach np-other np-out); same ns $(reach cmapi np-same); port-forward $(pf)"
k apply -f "$POLICY" >/dev/null; perl -e 'select(undef,undef,undef,5)'
echo "$(basename "$(dirname "$POLICY")")/$(basename "$POLICY"): other ns $(reach np-other np-out); same ns $(reach cmapi np-same); port-forward $(pf)"
k delete networkpolicy cmapi-metrics -n cmapi --ignore-not-found >/dev/null
