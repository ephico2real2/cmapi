#!/usr/bin/env bash
# deploy/tests/np-reach-test.sh <kubeconfig>: who reaches port 8080 of the pods that deploy/manifests/components/cmapi/40-networkpolicy.yaml
# selects, measured on a kind cluster (only). Two targets: an API pod (cmapi-metrics) and a front door pod (cmapi-front-door, #226). For each,
# three sources: a pod in another namespace, a plain pod in the same namespace, and the other target's pod; and kubectl port-forward. With
# no policy every source must reach every target, or "blocked" below proves nothing. With the policies only the front door reaches the API,
# no pod reaches the front door (on kind no namespace carries the router's label), and port-forward reaches both. Leaves the policies as it
# found them.
set -uo pipefail
KC=${1:?kubeconfig of a kind cluster}
HERE=$(cd "$(dirname "$0")" && pwd); POLICY=$HERE/../manifests/components/cmapi/40-networkpolicy.yaml
IMG=docker.io/nginxinc/nginx-unprivileged@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6
PORT=18099
k() { kubectl --kubeconfig="$KC" "$@"; }
case "$(k config current-context)" in kind-*) ;; *) echo "ERROR: $KC does not point at a kind cluster; this test only runs on a throwaway one" >&2; exit 2;; esac
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }
had_policy=$(k -n cmapi get networkpolicy cmapi-metrics cmapi-front-door --ignore-not-found -o name 2>/dev/null)
had_ns=$(k get ns cmapi --ignore-not-found -o name)
cleanup() {
  k -n cmapi delete pod np-api np-front np-same --ignore-not-found --wait=false >/dev/null 2>&1
  k delete ns np-other --ignore-not-found --wait=false >/dev/null 2>&1
  if [ -n "$had_ns" ]; then
    k -n cmapi delete networkpolicy cmapi-metrics cmapi-front-door --ignore-not-found >/dev/null 2>&1
    [ -z "$had_policy" ] || k apply -f "$POLICY" >/dev/null 2>&1
  else
    k delete ns cmapi --ignore-not-found --wait=false >/dev/null 2>&1
  fi
}
trap cleanup EXIT
[ -n "$had_ns" ] || k create ns cmapi >/dev/null; k create ns np-other >/dev/null 2>&1
k -n cmapi delete networkpolicy cmapi-metrics cmapi-front-door --ignore-not-found >/dev/null
# The labels the policies select: the API's component, and the front door's name and component (components/portal/10-front-door.yaml).
k -n cmapi run np-api --image="$IMG" --image-pull-policy=IfNotPresent --labels=app.kubernetes.io/component=api >/dev/null
k -n cmapi run np-front --image="$IMG" --image-pull-policy=IfNotPresent --labels=app.kubernetes.io/name=cmapi-portal,app.kubernetes.io/component=portal >/dev/null
k -n cmapi run np-same --image="$IMG" --image-pull-policy=IfNotPresent --labels=app.kubernetes.io/component=probe >/dev/null
k -n np-other run np-out --image="$IMG" --image-pull-policy=IfNotPresent >/dev/null
k -n cmapi wait pod/np-api pod/np-front pod/np-same --for=condition=Ready --timeout=180s >/dev/null || { echo "ERROR: the pods did not start" >&2; exit 1; }
k -n np-other wait pod/np-out --for=condition=Ready --timeout=180s >/dev/null || { echo "ERROR: the other namespace's pod did not start" >&2; exit 1; }
API_IP=$(k -n cmapi get pod np-api -o jsonpath='{.status.podIP}'); FRONT_IP=$(k -n cmapi get pod np-front -o jsonpath='{.status.podIP}')
{ [ -n "$API_IP" ] && [ -n "$FRONT_IP" ]; } || { echo "ERROR: a target pod has no address" >&2; exit 1; }
# reach <ns> <pod> <ip>: whether that pod reaches port 8080 of that address.
reach() { if k -n "$1" exec "$2" -- wget -q -O /dev/null --timeout=4 "http://$3:8080/" 2>/dev/null; then echo reached; else echo blocked; fi; }
# settle <want> <ns> <pod> <ip>: a policy takes a moment to take effect, so the wanted answer has up to 30 s to appear.
settle() { local got i; for i in 1 2 3 4 5 6; do got=$(reach "$2" "$3" "$4"); [ "$got" = "$1" ] && break; [ "$i" = 6 ] || sleep 5; done; echo "$got"; }
pf() { # <pod>. kubectl itself, not k: a function in the background is a subshell, so kill $! would leave kubectl holding the port.
  kubectl --kubeconfig="$KC" -n cmapi port-forward "pod/$1" "$PORT:8080" >/dev/null 2>&1 & local p=$!
  sleep 2; curl -s -o /dev/null -m 4 -w '%{http_code}' "http://127.0.0.1:$PORT/"; kill "$p" 2>/dev/null; wait "$p" 2>/dev/null; }
# measure <label> <target pod> <target ip> <the other target's pod>, then what the other namespace, the same namespace and that pod must get.
measure() {
  local a b c d; a=$(settle "$5" np-other np-out "$3"); b=$(settle "$6" cmapi np-same "$3"); c=$(settle "$7" cmapi "$4" "$3"); d=$(pf "$2")
  echo "$1: other namespace $a; same namespace $b; $4 $c; port-forward $d"
  [ "$a" = "$5" ] || bad "$1: another namespace is $a, must be $5"
  [ "$b" = "$6" ] || bad "$1: the same namespace is $b, must be $6"
  [ "$c" = "$7" ] || bad "$1: $4 is $c, must be $7"
  [ "$d" = 200 ] || bad "$1: port-forward answered $d, must be 200"
}
measure "the API,        no policy  " np-api "$API_IP" np-front reached reached reached
measure "the front door, no policy  " np-front "$FRONT_IP" np-api reached reached reached
k apply -f "$POLICY" >/dev/null || { echo "ERROR: the policies did not apply" >&2; exit 1; }
measure "the API,        the policies" np-api "$API_IP" np-front blocked blocked reached
measure "the front door, the policies" np-front "$FRONT_IP" np-api blocked blocked blocked
echo "np cases failed: $fails"; [ "$fails" = 0 ]
