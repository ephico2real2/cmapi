#!/usr/bin/env bash
# deploy/kind-test.sh [<cmapi image>]: the functional test of the plain manifests on a kind cluster named cmapi-test.
# Creates the cluster (KIND_EXPERIMENTAL_PROVIDER=podman, kind v0.33.0, node image v1.35.8 by digest), installs the
# CloudNativePG operator 1.30.1, loads the image (default localhost/cmapi:dev, built from this tree), applies
# environments/kind, writes the Secrets, renders components with the image and applies them, then checks: api and worker
# Ready, every database connection (api, worker, both migrate containers) on verify-full TLS and refusing a CA that does not
# cover the server, /readyz 200, /api/v1/version naming the built commit, no restart after the rollout, a changed cmapi-env restarting the api and the worker, and the secrets cases. Every
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
# Only a cluster this run created, and only a kubeconfig it created: KIND_TEST_KUBECONFIG may name a file with other clusters in it.
created=false
kc_existed=false; [ ! -e "$KC" ] || kc_existed=true
# A port-forward left behind holds its port and would answer a later run's curl from this run's cluster.
PF=
finish() { rc=$?; [ -z "$PF" ] || kill "$PF" 2>/dev/null || true; [ -z "${T:-}" ] || rm -rf "$T"; if [ "$created" = true ] && [ "${KIND_TEST_KEEP:-false}" != true ]; then say "deleting kind cluster cmapi-test"; kind delete cluster --name cmapi-test --kubeconfig "$KC" >/dev/null 2>&1 || true; [ "$kc_existed" = true ] || rm -f "$KC"; fi; exit $rc; }
trap finish EXIT

T=$(mktemp -d)
# A name already taken is somebody else's cluster. Not "| grep -q" in an if: under pipefail an early match can read as none.
clusters=$(kind get clusters)
case $'\n'"$clusters"$'\n' in *$'\n'cmapi-test$'\n'*) echo "ERROR: kind cluster cmapi-test already exists; this run neither uses nor deletes a cluster it did not create" >&2; exit 1;; esac
say "kind create cluster cmapi-test ($NODE_IMAGE)"
# kind removes what it made when a step fails, but not when it is interrupted or when its last step, the kubeconfig export,
# fails (pkg/cluster/internal/create/create.go, v0.33.0), so this run owns the name from here. The exception is another run
# taking the name after the check above: kind then stops before creating anything, and that cluster is the other run's.
created=true
if ! { kind create cluster --name cmapi-test --image "$NODE_IMAGE" --kubeconfig "$KC" --wait 120s >/dev/null; } 2>&1 | tee "$T/kind-create.err" >&2; then
  case "$(cat "$T/kind-create.err")" in *"node(s) already exist for a cluster"*) created=false;; esac
  echo "ERROR: kind create cluster failed" >&2; exit 1
fi
[ "$(k config current-context)" = kind-cmapi-test ] || { echo "ERROR: the kubeconfig's context is not kind-cmapi-test" >&2; exit 1; }
say "node: $(k get nodes -o jsonpath='{.items[0].metadata.name} {.items[0].status.nodeInfo.kubeletVersion}')"

say "CloudNativePG operator 1.30.1"
curl -fsSL "$CNPG_URL" -o "$T/cnpg.yaml"
echo "$CNPG_SHA  $T/cnpg.yaml" | shasum -a 256 -c - >/dev/null || { echo "ERROR: cnpg-1.30.1.yaml checksum mismatch" >&2; exit 1; }
k apply --server-side -f "$T/cnpg.yaml" >/dev/null
k -n cnpg-system rollout status deploy/cnpg-controller-manager --timeout=180s >/dev/null; say "cnpg operator ready"

say "load image $IMAGE (podman save, then kind load image-archive: the podman provider's reliable path)"
podman save -o "$T/image.tar" "$IMAGE"
kind load image-archive "$T/image.tar" --name cmapi-test
rm -f "$T/image.tar"
k apply -f "$HERE/manifests/environments/kind/00-namespaces.yaml" >/dev/null
k apply -f "$HERE/manifests/environments/kind/" >/dev/null; say "environments/kind applied"
"$HERE/secrets.sh" --namespace cmapi --realm-namespace cmapi-imports --kubectl "kubectl --kubeconfig=$KC" --no-ldap-bind --no-issuer-check
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
  else
    # Not "| grep -q": under pipefail kubectl's SIGPIPE from an early match would read as no match.
    previous=$(k -n cmapi logs "$pod" -c migrate --previous 2>/dev/null || true)
    case "$previous" in *"failed to resolve host"*) dns_evidence=true;; esac
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

say "what each database connection gets: the api, the worker and both migrate containers"
# Measured, not assumed: libpq's sslmode=prefer connects to anything and falls back to plaintext without a word. A pod made from each
# container of the two Deployments, its environment and mounts untouched, connects as that process connects and says what it got: ssl,
# the TLS version, and the sslmode libpq used, from PQconninfo. A second one reads, as the CNPG CA, the kind bundle's stand-in CA, which
# signed nothing: it must refuse, and not fall back. Each pod's labels put it under the same NetworkPolicy and in no Service. Every
# measurement is printed before a failure stops the run, so a run on manifests without the fix shows the whole of what they do.
DB_CHECK='import os
from sqlalchemy import create_engine, pool
from sqlalchemy.exc import OperationalError
from cmapi.core.db import sqlalchemy_url
try:
    with create_engine(sqlalchemy_url(os.environ["CMAPI_DATABASE_URL"]), poolclass=pool.NullPool).connect() as c:
        mode = next(o.val.decode() for o in c.connection.dbapi_connection.pgconn.info if o.keyword == b"sslmode")
        print("connected", *c.exec_driver_sql("select ssl, version from pg_stat_ssl where pid = pg_backend_pid()").one(), mode)
except OperationalError as exc:
    print("refused", " ".join(str(exc.orig).split()))'
db_pod() { # <pod> <deployment> <initContainers|containers> <replace the CNPG CA: true|false>
  k -n cmapi get deploy "$2" -o json | python3 -c 'import json,sys
pod,deployment,where,wrong_ca,check=sys.argv[1:]
spec=json.load(sys.stdin)["spec"]["template"]["spec"]
c=spec[where][0]
for key in ("readinessProbe","livenessProbe","startupProbe","ports"): c.pop(key,None)
c.update(name="check",command=["python3","-c",check])
if wrong_ca=="true":
    for v in spec["volumes"]:
        for s in v.get("projected",{}).get("sources",[]):
            if s.get("secret",{}).get("name")=="cmapi-db-ca":
                s["configMap"]={"name":"cmapi-trust","items":[{"key":"ca-bundle.crt","path":s.pop("secret")["items"][0]["path"]}]}
print(json.dumps({"apiVersion":"v1","kind":"Pod","metadata":{"name":pod,"namespace":"cmapi","labels":{"app.kubernetes.io/component":deployment.removeprefix("cmapi-"),"cmapi.net/kind-test":"db-check"}},
  "spec":{"restartPolicy":"Never","serviceAccountName":spec["serviceAccountName"],"securityContext":spec["securityContext"],"volumes":spec["volumes"],"containers":[c]}}))' "$1" "$2" "$3" "$4" "$DB_CHECK" | k apply -f - >/dev/null
}
db_read() { # <pod>: its one line, once it has finished. A check that cannot run proves nothing either way, so it stops the run here.
  k -n cmapi wait "pod/$1" --for=jsonpath='{.status.phase}'=Succeeded --timeout=180s >/dev/null || { k -n cmapi logs "$1" --tail=3 >&2 || true; echo "ERROR: the database check $1 did not finish" >&2; exit 1; }
  k -n cmapi logs "$1"
}
DB_CONTAINERS="api-migrate:cmapi-api:initContainers api:cmapi-api:containers worker-migrate:cmapi-worker:initContainers worker:cmapi-worker:containers"
for e in $DB_CONTAINERS; do
  IFS=: read -r name deployment where <<<"$e"
  db_pod "pg-ssl-$name" "$deployment" "$where" false
  db_pod "pg-ca-$name" "$deployment" "$where" true
done
db_bad=0
for e in $DB_CONTAINERS; do
  name=${e%%:*}
  line=$(db_read "pg-ssl-$name"); say "$name, as deployed: $line"
  case "$line" in "connected True "*" verify-full") ;; *) echo "ERROR: $name does not reach the database over verified TLS: $line" >&2; db_bad=1;; esac
  line=$(db_read "pg-ca-$name"); say "$name, with a CA that does not cover the server: $line"
  case "$line" in "refused "*"certificate verify failed"*) ;; *) echo "ERROR: $name did not refuse a CA that does not cover the server: $line" >&2; db_bad=1;; esac
done
k -n cmapi delete pod -l cmapi.net/kind-test=db-check >/dev/null
# And from the server's side, the processes themselves: what the running api and worker hold, by pod address.
for c in api worker; do
  ip=$(k -n cmapi get pod -l "app.kubernetes.io/component=$c" -o jsonpath='{.items[0].status.podIP}')
  row=$(k -n cmapi exec cmapi-db-1 -c postgres -- psql -d cmapi -Atc "select count(*) filter (where s.ssl), count(*) filter (where not s.ssl) from pg_stat_ssl s join pg_stat_activity a using (pid) where a.usename='cmapi' and a.client_addr='$ip'")
  say "pg_stat_ssl for the $c pod's connections, on TLS|not: $row"
  case "$row" in *"|0") [ "${row%%|*}" -gt 0 ] || { echo "ERROR: the $c pod holds no connection to read: $row" >&2; db_bad=1; };; *) echo "ERROR: the $c pod holds a plaintext connection: $row" >&2; db_bad=1;; esac
done
[ "$db_bad" = 0 ] || exit 1

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
