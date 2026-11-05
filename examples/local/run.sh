#!/usr/bin/env bash
# The cmapi local stack: Keycloak, a local Git repository, a Kubernetes cluster and the cmapi API.
# See INSTALL.md for the full guide. Linux or macOS.
#
#   ./run.sh                start everything, run the unit tests and the end-to-end demo
#   ./run.sh up             start everything, no demo
#   ./run.sh demo           run demo.py against a running stack (writes transcript.txt)
#   ./run.sh test           run the unit tests
#   ./run.sh status         what is running, and where
#   ./run.sh stop           stop the API, Keycloak and k3s (a kind cluster keeps running)
#   ./run.sh down           stop, delete the kind cluster and the local Git repositories
#
# Choices (environment variables):
#   CLUSTER=k3s|kind|existing   k3s: Linux, root, no registry needed (the default when root on Linux)
#                               kind: Docker or Podman, Linux or macOS (the default otherwise)
#                               existing: the cluster KUBECONFIG / CMAPI_KUBE_CONTEXT point at
#   KEYCLOAK=tarball|docker     tarball: Java 21 (the default when java is on PATH); docker: the
#                               quay.io/keycloak/keycloak image
#   CMAPI_STACK=<dir>           downloads, logs, Git repositories (/opt/stack as root, else ~/.cmapi-local)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
KC_VER=26.0.7 K3S_VER=v1.31.4+k3s1 KUBE_VER=v1.31.4 KIND_VER=v0.26.0 KYVERNO_VER=v1.16.2 KUBECONFORM_VER=v0.6.7
GH=https://github.com

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$(uname -m)" in x86_64|amd64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) echo "unsupported CPU $(uname -m)"; exit 1 ;; esac
ROOT=$([[ $(id -u) == 0 ]] && echo yes || echo no)

export CMAPI_STACK=${CMAPI_STACK:-$([[ $ROOT == yes ]] && echo /opt/stack || echo "$HOME/.cmapi-local")}
STACK=$CMAPI_STACK BIN=$CMAPI_STACK/bin LOGS=$CMAPI_STACK/logs RUN=$CMAPI_STACK/run
mkdir -p "$BIN" "$LOGS" "$RUN"
export PATH="$BIN:$PATH"

if [[ -z "${CLUSTER:-}" ]]; then CLUSTER=$([[ $OS == linux && $ROOT == yes ]] && echo k3s || echo kind); fi
if [[ -z "${KEYCLOAK:-}" ]]; then KEYCLOAK=$(command -v java >/dev/null && echo tarball || echo docker); fi
export CMAPI_CLUSTER=$CLUSTER

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
fetch() { curl -sSfL --retry 3 "$@"; }

# ---------------------------------------------------------------- cluster wiring
case $CLUSTER in
  k3s)
    [[ $OS == linux ]] || die "k3s runs on Linux only; use CLUSTER=kind on macOS"
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml CMAPI_KUBECTL="$BIN/kubectl" ;;
  kind)
    export KUBECONFIG=$STACK/kind.kubeconfig CMAPI_KUBECTL=kubectl ;;
  existing)
    export CMAPI_KUBECTL=kubectl ;;
  *) die "CLUSTER must be k3s, kind or existing" ;;
esac

# ---------------------------------------------------------------- commands
stop() {
  for svc in cmapi keycloak k3s; do
    [[ -f $RUN/$svc.pid ]] && kill "$(cat "$RUN/$svc.pid")" 2>/dev/null || true
    rm -f "$RUN/$svc.pid"
  done
  pkill -f "uvicorn app:app" 2>/dev/null || true
  [[ $KEYCLOAK == docker ]] && docker rm -f cmapi-keycloak >/dev/null 2>&1 || true
  [[ $CLUSTER == k3s ]] && { pkill -f "k3s server" 2>/dev/null || true; }
  say "stopped"
}

status() {
  echo "stack     $STACK"
  echo "cluster   $CLUSTER  (KUBECONFIG=${KUBECONFIG:-default}${CMAPI_KUBE_CONTEXT:+, context $CMAPI_KUBE_CONTEXT})"
  echo "keycloak  $KEYCLOAK  $(curl -s -o /dev/null -w '%{http_code}' localhost:8080/realms/ephico2real 2>/dev/null || echo down)"
  echo "cmapi     $(curl -s localhost:8000/healthz 2>/dev/null || echo down)"
}

case "${1:-all}" in
  stop) stop; exit 0 ;;
  down)
    stop
    [[ $CLUSTER == kind ]] && command -v kind >/dev/null && kind delete cluster --name cmapi-local --kubeconfig "$KUBECONFIG" || true
    rm -rf "$STACK/git"; say "down"; exit 0 ;;
  status) status; exit 0 ;;
  all|up|demo|test) ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac
CMD=${1:-all}

# ---------------------------------------------------------------- downloads (once)
install_tools() {
  say "tools in $BIN"
  local ky_arch=$([[ $ARCH == amd64 ]] && echo x86_64 || echo arm64)
  [[ -x $BIN/kyverno ]] || fetch "$GH/kyverno/kyverno/releases/download/$KYVERNO_VER/kyverno-cli_${KYVERNO_VER}_${OS}_${ky_arch}.tar.gz" | tar xz -C "$BIN" kyverno
  [[ -x $BIN/kubeconform ]] || fetch "$GH/yannh/kubeconform/releases/download/$KUBECONFORM_VER/kubeconform-$OS-$ARCH.tar.gz" | tar xz -C "$BIN" kubeconform
  if [[ $CLUSTER == k3s ]]; then
    local k3s_bin=$([[ $ARCH == amd64 ]] && echo k3s || echo k3s-arm64)
    [[ -x $BIN/k3s ]] || { fetch -o "$BIN/k3s" "$GH/k3s-io/k3s/releases/download/${K3S_VER/+/%2B}/$k3s_bin"; chmod +x "$BIN/k3s"; }
    ln -sf "$BIN/k3s" "$BIN/kubectl"            # k3s is multi-call: invoked as kubectl it is kubectl
    mkdir -p /var/lib/rancher/k3s/agent/images
    local img=/var/lib/rancher/k3s/agent/images/k3s-airgap-images-$ARCH.tar.zst
    [[ -f $img ]] || [[ -f /var/lib/rancher/k3s/agent/images/k3s-airgap.tar.zst ]] || \
      fetch -o "$img" "$GH/k3s-io/k3s/releases/download/${K3S_VER/+/%2B}/k3s-airgap-images-$ARCH.tar.zst"
  else
    command -v kubectl >/dev/null || { fetch -o "$BIN/kubectl" "https://dl.k8s.io/release/$KUBE_VER/bin/$OS/$ARCH/kubectl"; chmod +x "$BIN/kubectl"; }
  fi
  if [[ $CLUSTER == kind ]]; then
    command -v kind >/dev/null || { fetch -o "$BIN/kind" "$GH/kubernetes-sigs/kind/releases/download/$KIND_VER/kind-$OS-$ARCH"; chmod +x "$BIN/kind"; }
  fi
  if [[ $KEYCLOAK == tarball && ! -d $STACK/keycloak ]]; then
    fetch "$GH/keycloak/keycloak/releases/download/$KC_VER/keycloak-$KC_VER.tar.gz" | tar xz -C "$STACK"
    mv "$STACK/keycloak-$KC_VER" "$STACK/keycloak"
  fi
  if [[ ! -x $STACK/venv/bin/python ]]; then python3 -m venv "$STACK/venv"; fi
  "$STACK/venv/bin/pip" install -q -r "$HERE/requirements.txt"
}

start_keycloak() {
  if curl -sf -o /dev/null localhost:8080/realms/master; then say "Keycloak already up on :8080"; return; fi
  say "Keycloak $KC_VER ($KEYCLOAK) on :8080"
  if [[ $KEYCLOAK == tarball ]]; then
    KC_BOOTSTRAP_ADMIN_USERNAME=admin KC_BOOTSTRAP_ADMIN_PASSWORD=admin JAVA_OPTS_APPEND=-Xmx768m \
      nohup "$STACK/keycloak/bin/kc.sh" start-dev --http-port 8080 --hostname http://localhost:8080 \
      > "$LOGS/keycloak.log" 2>&1 & echo $! > "$RUN/keycloak.pid"
  else
    docker rm -f cmapi-keycloak >/dev/null 2>&1 || true
    docker run -d --name cmapi-keycloak -p 8080:8080 \
      -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
      "quay.io/keycloak/keycloak:$KC_VER" start-dev --hostname http://localhost:8080 >/dev/null
  fi
}

start_cluster() {
  case $CLUSTER in
    k3s)
      if ! pgrep -f "k3s server" >/dev/null; then
        say "k3s $K3S_VER (air-gapped)"
        nohup "$BIN/k3s" server --disable traefik --disable metrics-server --disable servicelb \
          --write-kubeconfig-mode 644 --node-name cmapi-local > "$LOGS/k3s.log" 2>&1 & echo $! > "$RUN/k3s.pid"
      fi ;;
    kind)
      if ! kind get clusters 2>/dev/null | grep -qx cmapi-local; then
        say "kind cluster cmapi-local ($KUBE_VER)"
        kind create cluster --config "$HERE/kind/kind-config.yaml" --kubeconfig "$KUBECONFIG" --wait 180s
      else
        kind get kubeconfig --name cmapi-local > "$KUBECONFIG"
      fi ;;
    existing)
      say "existing cluster: $(kubectl ${CMAPI_KUBE_CONTEXT:+--context $CMAPI_KUBE_CONTEXT} config current-context 2>/dev/null || echo '?')" ;;
  esac
}

wait_ready() {
  say "waiting for Keycloak and the cluster"
  for _ in $(seq 120); do curl -sf -o /dev/null localhost:8080/realms/master && break; sleep 2; done
  curl -sf -o /dev/null localhost:8080/realms/master || die "Keycloak did not start; see $LOGS/keycloak.log"
  for _ in $(seq 90); do
    $CMAPI_KUBECTL ${CMAPI_KUBE_CONTEXT:+--context $CMAPI_KUBE_CONTEXT} get nodes 2>/dev/null | grep -q " Ready" && return
    sleep 2
  done
  die "the cluster has no Ready node; see $LOGS/k3s.log or 'kubectl get nodes'"
}

reset_data() {
  # A fresh Git repository each run, and no cmapi-managed namespaces left from the last one. The API
  # keeps its requests in memory, so it restarts too.
  [[ -f $RUN/cmapi.pid ]] && kill "$(cat "$RUN/cmapi.pid")" 2>/dev/null || true
  pkill -f "uvicorn app:app" 2>/dev/null || true; sleep 1
  rm -rf "$STACK/git"
  if [[ $CLUSTER == existing && "${CMAPI_RESET:-no}" != yes ]]; then
    say "existing cluster: leaving cmapi.net/managed=true namespaces alone (CMAPI_RESET=yes to delete them)"
  else
    $CMAPI_KUBECTL ${CMAPI_KUBE_CONTEXT:+--context $CMAPI_KUBE_CONTEXT} delete ns -l cmapi.net/managed=true --wait=true >/dev/null 2>&1 || true
  fi
}

start_cmapi() {
  if curl -sf -o /dev/null localhost:8000/healthz; then say "cmapi already up on :8000"; return; fi
  say "cmapi API on :8000"
  (cd "$HERE" && PYTHONPATH=../src:. nohup "$STACK/venv/bin/python" -m uvicorn app:app --port 8000 \
    > "$LOGS/cmapi.log" 2>&1 & echo $! > "$RUN/cmapi.pid")
  for _ in $(seq 60); do curl -sf -o /dev/null localhost:8000/healthz && return; sleep 1; done
  die "cmapi did not start; see $LOGS/cmapi.log"
}

run_tests() { say "unit tests"; (cd "$HERE/.." && PYTHONPATH=src:tests "$STACK/venv/bin/python" -m pytest -q -p no:cacheprovider tests | tail -1); }
run_demo()  { say "end-to-end demo"; (cd "$HERE" && "$STACK/venv/bin/python" demo.py | tee transcript.txt); }

case $CMD in
  test) [[ -x $STACK/venv/bin/python ]] || install_tools; run_tests; exit 0 ;;
  demo) run_demo; exit 0 ;;
esac

install_tools
start_keycloak
start_cluster
wait_ready
say "realm ephico2real"; (cd "$HERE" && "$STACK/venv/bin/python" keycloak_setup.py)
[[ $CMD == all ]] && reset_data
start_cmapi
status
[[ $CMD == all ]] && { run_tests; run_demo; }
say "done. Keycloak admin: http://localhost:8080/admin (admin/admin). API docs: http://localhost:8000/docs"
