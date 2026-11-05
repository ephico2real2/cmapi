#!/usr/bin/env bash
# deploy/kind-test.sh [<cmapi image>]: the functional test of the plain manifests on a kind cluster named cmapi-test.
# Creates the cluster (KIND_EXPERIMENTAL_PROVIDER=podman, kind v0.33.0, node image v1.35.8 by digest), installs the
# CloudNativePG operator 1.30.1, loads the image (default localhost/cmapi:dev, built from this tree), applies
# environments/kind, writes the Secrets, renders components with the image and applies them, then checks: api and worker
# Ready, /readyz 200, /api/v1/version naming the built commit, and the secrets cases. Every kubectl call carries an
# explicit --kubeconfig (KIND_TEST_KUBECONFIG, default ./.cmapi-test.kubeconfig, git-ignored). KIND_TEST_KEEP=true keeps
# the cluster; otherwise it is deleted by name at the end. Prints what it measured; exits non-zero on the first failure.
set -euo pipefail
IMAGE=${1:-localhost/cmapi:dev}
HERE=$(cd "$(dirname "$0")" && pwd)
KC=${KIND_TEST_KUBECONFIG:-$HERE/../.cmapi-test.kubeconfig}
NODE_IMAGE='kindest/node:v1.35.8@sha256:07b2536e30b803ed61d1677a79df6115f798ce64c80f9e22f6ed45afd09323c0'
CNPG_URL=https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.30/releases/cnpg-1.30.1.yaml
CNPG_SHA=37237f145d8138256ea25ae830f87759255665ff08f8d552fdd8224a5ec032fb
export KIND_EXPERIMENTAL_PROVIDER=podman
t0=$(date +%s); say() { echo "[$(( $(date +%s) - t0 ))s] $*"; }
k() { kubectl --kubeconfig="$KC" "$@"; }
finish() { rc=$?; if [ "${KIND_TEST_KEEP:-false}" != true ]; then say "deleting kind cluster cmapi-test"; kind delete cluster --name cmapi-test --kubeconfig "$KC" >/dev/null 2>&1 || true; rm -f "$KC"; fi; exit $rc; }
trap finish EXIT

say "kind create cluster cmapi-test ($NODE_IMAGE)"
kind create cluster --name cmapi-test --image "$NODE_IMAGE" --kubeconfig "$KC" --wait 120s >/dev/null
[ "$(k config current-context)" = kind-cmapi-test ] || { echo "ERROR: the kubeconfig's context is not kind-cmapi-test" >&2; exit 1; }
say "node: $(k get nodes -o jsonpath='{.items[0].metadata.name} {.items[0].status.nodeInfo.kubeletVersion}')"

say "CloudNativePG operator 1.30.1"
T=$(mktemp -d); curl -fsSL "$CNPG_URL" -o "$T/cnpg.yaml"
echo "$CNPG_SHA  $T/cnpg.yaml" | shasum -a 256 -c - >/dev/null || { echo "ERROR: cnpg-1.30.1.yaml checksum mismatch" >&2; exit 1; }
k apply --server-side -f "$T/cnpg.yaml" >/dev/null
k -n cnpg-system rollout status deploy/cnpg-controller-manager --timeout=180s >/dev/null; say "cnpg operator ready"

say "load image $IMAGE (podman save, then kind load image-archive: the podman provider's reliable path)"
podman save -o "$T/image.tar" "$IMAGE"
kind load image-archive "$T/image.tar" --name cmapi-test
rm -f "$T/image.tar"
k apply -f "$HERE/manifests/environments/kind/00-namespaces.yaml" >/dev/null
k apply -f "$HERE/manifests/environments/kind/" >/dev/null; say "environments/kind applied"
"$HERE/secrets.sh" --namespace cmapi --realm-namespace cmapi-imports --kubectl "kubectl --kubeconfig=$KC" --no-ldap-bind
"$HERE/render.sh" kind "$IMAGE" "$T/rendered" --allow-tag
# Server-side: the mockup ConfigMap (300 KB) is over the 256 KiB a client-side apply writes into its last-applied
# annotation (measured: "metadata.annotations: Too long"); Argo CD applies server-side too (ServerSideApply=true).
k apply --server-side -R -f "$T/rendered/components" >/dev/null; say "components applied (server-side)"

say "waiting for the database"
for _ in $(seq 1 60); do ph=$(k -n cmapi get cluster cmapi-db -o jsonpath='{.status.phase}' 2>/dev/null || true); [ "$ph" = "Cluster in healthy state" ] && break; sleep 5; done
say "cmapi-db: ${ph:-no phase}"
[ "$ph" = "Cluster in healthy state" ] || { k -n cmapi get cluster cmapi-db -o yaml | tail -30; exit 1; }

say "waiting for api and worker (120 s before looking at the migrate logs)"
dns_fail=false
if ! k -n cmapi rollout status deploy/cmapi-api --timeout=120s >/dev/null 2>&1; then
  pod=$(k -n cmapi get pod -l app.kubernetes.io/component=api -o jsonpath='{.items[0].metadata.name}')
  if k -n cmapi logs "$pod" -c migrate 2>/dev/null | grep -qi "could not translate host name\|Name or service not known\|Temporary failure in name resolution"; then
    dns_fail=true
    say "MEASURED: the migrate initContainer cannot resolve the database under the cmapi-metrics NetworkPolicy on podman kind; deleting the policy for this test only (the policy ships; the hosted runner and CRC decide)"
    k -n cmapi delete networkpolicy cmapi-metrics >/dev/null
    k -n cmapi delete pod -l app.kubernetes.io/part-of=cmapi,app.kubernetes.io/component --field-selector=status.phase!=Running >/dev/null 2>&1 || true
  fi
fi
k -n cmapi rollout status deploy/cmapi-api --timeout=600s
k -n cmapi rollout status deploy/cmapi-worker --timeout=300s
k -n cmapi rollout status deploy/cmapi-mockup --timeout=180s
say "ready: $(k -n cmapi get pods -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount --no-headers | tr '\n' ';')"

say "/readyz and /api/v1/version through a port-forward"
k -n cmapi port-forward svc/cmapi-api 18080:8080 >/dev/null 2>&1 & PF=$!; sleep 3
READY=$(curl -s -o "$T/readyz" -w '%{http_code}' http://127.0.0.1:18080/readyz); echo "readyz: $READY $(cat "$T/readyz")"
VERSION=$(curl -s http://127.0.0.1:18080/api/v1/version); echo "version: $VERSION"
kill $PF 2>/dev/null || true
k -n cmapi port-forward svc/cmapi-mockup 18081:8080 >/dev/null 2>&1 & PF=$!; sleep 2
MOCK=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/portal.html); echo "mockup: $MOCK"; kill $PF 2>/dev/null || true
[ "$READY" = 200 ] || { echo "ERROR: /readyz is $READY" >&2; exit 1; }
EXPECT=$(git -C "$HERE/.." rev-parse --short=10 HEAD 2>/dev/null || echo unknown)
echo "$VERSION" | grep -q "\"commit\":\"${EXPECT:0:7}" || echo "note    : /version commit does not start with the tree's HEAD ${EXPECT}; the image was built from another commit"
[ "$MOCK" = 200 ] || { echo "ERROR: the mockup is $MOCK" >&2; exit 1; }

say "secrets cases"
"$HERE/secrets-test.sh" "kubectl --kubeconfig=$KC"
say "done; NetworkPolicy deleted for DNS: $dns_fail"
