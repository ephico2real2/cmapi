#!/usr/bin/env bash
# deploy/kind-test.sh [<cmapi image>]: the functional test of the plain manifests on a kind cluster named cmapi-test.
# Creates the cluster (KIND_EXPERIMENTAL_PROVIDER=podman, kind v0.33.0, node image v1.35.8 by digest), installs the
# CloudNativePG operator 1.30.1, loads the image (default localhost/cmapi:dev, built from this tree), applies
# environments/kind, writes the Secrets, renders components with the image and applies them, then checks: api and worker
# Ready, the migrate container's environment reaching the database over TLS, /readyz 200, /api/v1/version naming the built
# commit, no restart after the rollout, a changed cmapi-env restarting the api and the worker, and the secrets cases. Every
# kubectl call carries an explicit --kubeconfig (KIND_TEST_KUBECONFIG, default ./.cmapi-test.kubeconfig, git-ignored). KIND_TEST_KEEP=true keeps
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
# Only a cluster this run created: "kind create" fails when the name is taken, and that cluster is somebody else's.
created=false
# A port-forward left behind holds its port and would answer a later run's curl from this run's cluster.
PF=
finish() { rc=$?; [ -z "$PF" ] || kill "$PF" 2>/dev/null || true; [ -z "${T:-}" ] || rm -rf "$T"; if [ "$created" = true ] && [ "${KIND_TEST_KEEP:-false}" != true ]; then say "deleting kind cluster cmapi-test"; kind delete cluster --name cmapi-test --kubeconfig "$KC" >/dev/null 2>&1 || true; rm -f "$KC"; fi; exit $rc; }
trap finish EXIT

say "kind create cluster cmapi-test ($NODE_IMAGE)"
kind create cluster --name cmapi-test --image "$NODE_IMAGE" --kubeconfig "$KC" --wait 120s >/dev/null
created=true
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

say "waiting for api and worker (60 s, then a DNS probe from the migrate container)"
dns_fail=false
if ! k -n cmapi rollout status deploy/cmapi-api --timeout=60s >/dev/null 2>&1; then
  pod=$(k -n cmapi get pod -l app.kubernetes.io/component=api -o jsonpath='{.items[0].metadata.name}')
  # The migrate container runs while it waits for the database, so it can be asked whether it resolves the Service at
  # all; after the wait it crash-loops and its previous log says the same (psycopg: "failed to resolve host").
  # A probe that ran and resolved settles it, whatever an older log says; the log counts only when the probe could not run.
  dns_evidence=false
  if probe=$(k -n cmapi exec "$pod" -c migrate -- python3 -c "import socket; socket.getaddrinfo('cmapi-db-rw.cmapi.svc', 5432)" 2>&1); then
    :
  elif echo "$probe" | grep -q "Name or service not known"; then
    dns_evidence=true
  elif k -n cmapi logs "$pod" -c migrate --previous 2>/dev/null | grep -q "failed to resolve host"; then
    dns_evidence=true
  fi
  if [ "$dns_evidence" = true ]; then
    mock=$(k -n cmapi get pod -l app.kubernetes.io/component=mockup -o jsonpath='{.items[0].metadata.name}')
    if k -n cmapi exec "$mock" -- getent hosts cmapi-db-rw.cmapi.svc >/dev/null 2>&1; then
      dns_fail=true
      say "MEASURED: the migrate container (selected by the ingress-only NetworkPolicy cmapi-metrics) cannot resolve cmapi-db-rw while the mockup pod (not selected) can: the podman-kind DNS failure under a NetworkPolicy. Deleting the policy for this test only; it ships, and the hosted runner and CRC decide"
      k -n cmapi delete networkpolicy cmapi-metrics >/dev/null
      k -n cmapi delete pod -l app.kubernetes.io/component=api >/dev/null; k -n cmapi delete pod -l app.kubernetes.io/component=worker >/dev/null
    fi
  fi
fi
k -n cmapi rollout status deploy/cmapi-api --timeout=600s
k -n cmapi rollout status deploy/cmapi-worker --timeout=300s
k -n cmapi rollout status deploy/cmapi-mockup --timeout=180s
say "ready: $(k -n cmapi get pods -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount --no-headers | tr '\n' ';')"

say "what the migrate container's environment gets from the database"
# libpq falls back to plaintext without a word when PGSSLROOTCERT names a bundle that does not cover the server, so this is
# measured, not assumed: a pod made from the api Deployment's own migrate initContainer, its environment and mounts untouched,
# connecting as cmapi-migrate connects. Its labels put it under the same NetworkPolicy and in no Service.
SSL_CHECK='import os
from sqlalchemy import create_engine, pool
from cmapi.core.db import sqlalchemy_url
with create_engine(sqlalchemy_url(os.environ["CMAPI_DATABASE_URL"]), poolclass=pool.NullPool).connect() as c:
    print("pg_stat_ssl", *c.exec_driver_sql("select ssl, version from pg_stat_ssl where pid = pg_backend_pid()").one())'
k -n cmapi get deploy cmapi-api -o json | python3 -c 'import json,sys
spec=json.load(sys.stdin)["spec"]["template"]["spec"]
c=spec["initContainers"][0]; c.update(name="pg-ssl-check", command=["python3","-c",sys.argv[1]])
print(json.dumps({"apiVersion":"v1","kind":"Pod","metadata":{"name":"pg-ssl-check","namespace":"cmapi","labels":{"app.kubernetes.io/component":"api"}},
  "spec":{"restartPolicy":"Never","serviceAccountName":spec["serviceAccountName"],"securityContext":spec["securityContext"],"volumes":spec["volumes"],"containers":[c]}}))' "$SSL_CHECK" | k apply -f - >/dev/null
k -n cmapi wait pod/pg-ssl-check --for=jsonpath='{.status.phase}'=Succeeded --timeout=180s >/dev/null || { k -n cmapi logs pg-ssl-check --tail=3 >&2 || true; echo "ERROR: the pg_stat_ssl check did not finish" >&2; exit 1; }
ssl_line=$(k -n cmapi logs pg-ssl-check); say "measured, with the migrate container's env: $ssl_line"
k -n cmapi delete pod pg-ssl-check >/dev/null
case "$ssl_line" in "pg_stat_ssl True "*) ;; *) echo "ERROR: the migrate container's environment does not reach the database over TLS: $ssl_line" >&2; exit 1;; esac

say "/readyz and /api/v1/version through a port-forward"
# kubectl itself, not k: a function in the background is a subshell, so kill $! would leave kubectl holding the port, and
# a later run's curl would read that old cluster. A port-forward that died (port taken) is a failure, not a read of whatever listens.
kubectl --kubeconfig="$KC" -n cmapi port-forward svc/cmapi-api 18080:8080 >/dev/null 2>&1 & PF=$!; sleep 3
kill -0 "$PF" 2>/dev/null || { echo "ERROR: the port-forward to cmapi-api died (port 18080 taken?)" >&2; exit 1; }
READY=$(curl -s -m 10 -o "$T/readyz" -w '%{http_code}' http://127.0.0.1:18080/readyz); echo "readyz: $READY $(cat "$T/readyz")"
VERSION=$(curl -s -m 10 http://127.0.0.1:18080/api/v1/version); echo "version: $VERSION"
kill "$PF" 2>/dev/null || true
kubectl --kubeconfig="$KC" -n cmapi port-forward svc/cmapi-mockup 18081:8080 >/dev/null 2>&1 & PF=$!; sleep 2
kill -0 "$PF" 2>/dev/null || { echo "ERROR: the port-forward to cmapi-mockup died (port 18081 taken?)" >&2; exit 1; }
MOCK=$(curl -s -m 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/portal.html); echo "mockup: $MOCK"; kill "$PF" 2>/dev/null || true; PF=
[ "$READY" = 200 ] || { echo "ERROR: /readyz is $READY" >&2; exit 1; }
# The running process must name the commit the image says it was built from; that it differs from the tree's HEAD is only a note.
BUILT=$(podman image inspect "$IMAGE" --format '{{index .Labels "org.opencontainers.image.revision"}}')
case "$BUILT" in ""|unknown|"<no value>") echo "ERROR: $IMAGE has no revision label ($BUILT); build it with --build-arg GIT_COMMIT=" >&2; exit 1;; esac
echo "$VERSION" | grep -q "\"commit\":\"$BUILT\"" || { echo "ERROR: /api/v1/version does not name the built commit $BUILT: $VERSION" >&2; exit 1; }
EXPECT=$(git -C "$HERE/.." rev-parse --short=10 HEAD 2>/dev/null || echo unknown)
[ "$BUILT" = "$EXPECT" ] || echo "note    : the image was built from $BUILT; the tree's HEAD is $EXPECT"
[ "$MOCK" = 200 ] || { echo "ERROR: the mockup is $MOCK" >&2; exit 1; }
# rollout status passes at the first start, and the worker has no readiness probe: a process that dies after that shows only here.
sleep 15
restarts=$(k -n cmapi get pods -o jsonpath='{range .items[*]}{.metadata.name}={.status.containerStatuses[0].restartCount} {end}')
case " $restarts" in *=[1-9]*) echo "ERROR: a container restarted after its rollout: $restarts" >&2; exit 1;; esac

say "a changed cmapi-env restarts the api and the worker: render again, apply both"
before=$(k -n cmapi get pods -l 'app.kubernetes.io/component in (api,worker)' -o name | tr '\n' ' ')
[ -n "$before" ] || { echo "ERROR: no api or worker pod to replace" >&2; exit 1; }
C=$T/changed; mkdir -p "$C"; cp "$HERE/render.sh" "$C/"; cp -R "$HERE/manifests" "$C/"
sed -i.bak 's/^  CMAPI_LOG_LEVEL: INFO$/  CMAPI_LOG_LEVEL: DEBUG/' "$C/manifests/environments/kind/10-env.yaml"; rm -f "$C/manifests/environments/kind/10-env.yaml.bak"
"$C/render.sh" kind "$IMAGE" "$C/out" --allow-tag >/dev/null
# Applied with everything else, the policy this run deleted would bring the same DNS failure back to the new pods.
[ "$dns_fail" != true ] || rm -f "$C/out/components/cmapi/40-networkpolicy.yaml"
k apply -f "$C/out/environment/" >/dev/null
k apply --server-side -R -f "$C/out/components" >/dev/null
k -n cmapi rollout status deploy/cmapi-api --timeout=300s >/dev/null
k -n cmapi rollout status deploy/cmapi-worker --timeout=300s >/dev/null
# shellcheck disable=SC2086  # one argument per pod
k -n cmapi wait --for=delete $before --timeout=180s >/dev/null || { echo "ERROR: the pods from before the change are still there: $before" >&2; exit 1; }
for c in api worker; do
  pod=$(k -n cmapi get pod -l "app.kubernetes.io/component=$c" -o jsonpath='{.items[0].metadata.name}')
  level=$(k -n cmapi exec "$pod" -c "$c" -- printenv CMAPI_LOG_LEVEL)
  [ "$level" = DEBUG ] || { echo "ERROR: $pod reads CMAPI_LOG_LEVEL=$level after the change" >&2; exit 1; }
done
say "replaced: $before; the new pods read CMAPI_LOG_LEVEL=DEBUG"

say "secrets cases"
"$HERE/secrets-test.sh" "kubectl --kubeconfig=$KC"
say "done; NetworkPolicy deleted for DNS: $dns_fail"
