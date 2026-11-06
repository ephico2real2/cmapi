#!/usr/bin/env bash
# deploy/tests/np-reach-test.sh <kubeconfig>: who reaches port 8080 of a pod that deploy/manifests/components/cmapi/40-networkpolicy.yaml
# selects, measured on a kind cluster (only): a pod in another namespace, a pod in the same namespace, and kubectl port-forward.
# With no policy all three must reach it, or "blocked" below proves nothing. With the policy another namespace is blocked, which
# is what the chart's guard earned (H1 of the review of PR #89), and the other two still reach it. Leaves the policy as it found it.
set -uo pipefail
KC=${1:?kubeconfig of a kind cluster}
HERE=$(cd "$(dirname "$0")" && pwd); POLICY=$HERE/../manifests/components/cmapi/40-networkpolicy.yaml
IMG=docker.io/nginxinc/nginx-unprivileged@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6
PORT=18099
k() { kubectl --kubeconfig="$KC" "$@"; }
case "$(k config current-context)" in kind-*) ;; *) echo "ERROR: $KC does not point at a kind cluster; this test only runs on a throwaway one" >&2; exit 2;; esac
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }
had_policy=$(k -n cmapi get networkpolicy cmapi-metrics --ignore-not-found -o name 2>/dev/null)
had_ns=$(k get ns cmapi --ignore-not-found -o name)
cleanup() {
  k -n cmapi delete pod np-api np-same --ignore-not-found --wait=false >/dev/null 2>&1
  k delete ns np-other --ignore-not-found --wait=false >/dev/null 2>&1
  if [ -n "$had_ns" ]; then
    k -n cmapi delete networkpolicy cmapi-metrics --ignore-not-found >/dev/null 2>&1
    [ -z "$had_policy" ] || k apply -f "$POLICY" >/dev/null 2>&1
  else
    k delete ns cmapi --ignore-not-found --wait=false >/dev/null 2>&1
  fi
}
trap cleanup EXIT
[ -n "$had_ns" ] || k create ns cmapi >/dev/null; k create ns np-other >/dev/null 2>&1
k -n cmapi delete networkpolicy cmapi-metrics --ignore-not-found >/dev/null
k -n cmapi run np-api --image="$IMG" --image-pull-policy=IfNotPresent --labels=app.kubernetes.io/component=api >/dev/null
k -n cmapi run np-same --image="$IMG" --image-pull-policy=IfNotPresent --labels=app.kubernetes.io/component=mockup >/dev/null
k -n np-other run np-out --image="$IMG" --image-pull-policy=IfNotPresent >/dev/null
k -n cmapi wait pod/np-api pod/np-same --for=condition=Ready --timeout=180s >/dev/null || { echo "ERROR: the pods did not start" >&2; exit 1; }
k -n np-other wait pod/np-out --for=condition=Ready --timeout=180s >/dev/null || { echo "ERROR: the other namespace's pod did not start" >&2; exit 1; }
IP=$(k -n cmapi get pod np-api -o jsonpath='{.status.podIP}')
reach() { if k -n "$1" exec "$2" -- wget -q -O /dev/null --timeout=4 "http://$IP:8080/" 2>/dev/null; then echo reached; else echo blocked; fi; }
# settle <want> <ns> <pod>: a policy takes a moment to take effect, so the wanted answer has up to 30 s to appear.
settle() { local got i; for i in 1 2 3 4 5 6; do got=$(reach "$2" "$3"); [ "$got" = "$1" ] && break; [ "$i" = 6 ] || sleep 5; done; echo "$got"; }
pf() { # kubectl itself, not k: a function in the background is a subshell, so kill $! would leave kubectl holding the port.
  kubectl --kubeconfig="$KC" -n cmapi port-forward pod/np-api "$PORT:8080" >/dev/null 2>&1 & local p=$!
  sleep 2; curl -s -o /dev/null -m 4 -w '%{http_code}' "http://127.0.0.1:$PORT/"; kill "$p" 2>/dev/null; wait "$p" 2>/dev/null; }
measure() { # label, then what each must be
  local a b c; a=$(settle "$2" np-other np-out); b=$(settle "$3" cmapi np-same); c=$(pf)
  echo "$1: other namespace $a; same namespace $b; port-forward $c"
  [ "$a" = "$2" ] || bad "$1: another namespace is $a, must be $2"
  [ "$b" = "$3" ] || bad "$1: the same namespace is $b, must be $3"
  [ "$c" = 200 ] || bad "$1: port-forward answered $c, must be 200"
}
measure "no policy " reached reached
k apply -f "$POLICY" >/dev/null || { echo "ERROR: the policy did not apply" >&2; exit 1; }
measure "the policy" blocked reached
echo "np cases failed: $fails"; [ "$fails" = 0 ]
