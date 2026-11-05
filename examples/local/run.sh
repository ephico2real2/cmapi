#!/usr/bin/env bash
# Stand up the local stack and run the end-to-end demo. Linux, root, Java 21, Python 3.11+, git,
# and outbound access to GitHub and PyPI. No container registry is needed: k3s runs air-gapped.
#
#   ./run.sh            # download (once), start Keycloak, k3s and cmapi, then python demo.py
#   ./run.sh stop       # stop all three
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
STACK=${STACK:-/opt/stack}
KC_VER=26.0.7 K3S_VER=v1.31.4+k3s1 KYVERNO_VER=v1.16.2 KUBECONFORM_VER=v0.6.7
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

if [[ "${1:-}" == stop ]]; then
  pkill -f "uvicorn app:app" || true; pkill -f "kc.sh|quarkus" || true; pkill -f "k3s server" || true; exit 0
fi

mkdir -p "$STACK" && cd "$STACK"
pip install -q --break-system-packages fastapi==0.115.6 uvicorn==0.32.1 "pyjwt[crypto]==2.10.1" httpx==0.28.1 pyyaml pytest
gh=https://github.com
[[ -d keycloak ]] || { curl -sSfL "$gh/keycloak/keycloak/releases/download/$KC_VER/keycloak-$KC_VER.tar.gz" | tar xz && mv "keycloak-$KC_VER" keycloak; }
[[ -x /usr/local/bin/k3s ]] || { curl -sSfL -o /usr/local/bin/k3s "$gh/k3s-io/k3s/releases/download/${K3S_VER/+/%2B}/k3s"; chmod +x /usr/local/bin/k3s; }
mkdir -p /var/lib/rancher/k3s/agent/images
[[ -f /var/lib/rancher/k3s/agent/images/k3s-airgap.tar.zst ]] || curl -sSfL -o /var/lib/rancher/k3s/agent/images/k3s-airgap.tar.zst \
  "$gh/k3s-io/k3s/releases/download/${K3S_VER/+/%2B}/k3s-airgap-images-amd64.tar.zst"
command -v kyverno >/dev/null || curl -sSfL "$gh/kyverno/kyverno/releases/download/$KYVERNO_VER/kyverno-cli_${KYVERNO_VER}_linux_x86_64.tar.gz" | tar xz -C /usr/local/bin kyverno
command -v kubeconform >/dev/null || curl -sSfL "$gh/yannh/kubeconform/releases/download/$KUBECONFORM_VER/kubeconform-linux-amd64.tar.gz" | tar xz -C /usr/local/bin kubeconform

pgrep -f quarkus >/dev/null || (KC_BOOTSTRAP_ADMIN_USERNAME=admin KC_BOOTSTRAP_ADMIN_PASSWORD=admin JAVA_OPTS_APPEND=-Xmx768m \
  nohup keycloak/bin/kc.sh start-dev --http-port 8080 --hostname http://localhost:8080 > keycloak.log 2>&1 &)
pgrep -f "k3s server" >/dev/null || (nohup k3s server --disable traefik --disable metrics-server --disable servicelb \
  --write-kubeconfig-mode 644 --node-name cmapi-local > k3s.log 2>&1 &)
until grep -q "Listening on" keycloak.log 2>/dev/null; do sleep 2; done
until k3s kubectl get nodes 2>/dev/null | grep -q " Ready"; do sleep 2; done

cd "$HERE"
python3 keycloak_setup.py
rm -rf "$STACK/git"; k3s kubectl delete ns -l cmapi.net/managed=true --wait=true >/dev/null 2>&1 || true
pgrep -f "uvicorn app:app" >/dev/null || (PYTHONPATH=../src:. nohup python3 -m uvicorn app:app --port 8000 > "$STACK/cmapi.log" 2>&1 &)
until curl -sf localhost:8000/openapi.json >/dev/null; do sleep 1; done
(cd .. && PYTHONPATH=src:tests python3 -m pytest -q -p no:cacheprovider tests | tail -1)
python3 demo.py | tee transcript.txt
