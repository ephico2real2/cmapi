#!/usr/bin/env bash
# deploy/tests/external-db-test.sh <kubeconfig>: docs/12's route on a kind cluster (only), run on the cluster deploy/kind-test.sh leaves
# with KIND_TEST_KEEP=true. It removes the CNPG Cluster, which takes Secrets cmapi-db-app and cmapi-db-ca with it, starts a PostgreSQL
# with TLS under its own CA in namespace cmapi-external-db, adds that CA to cmapi-trust, writes cmapi-db-app as docs/12 step 3 does, and
# starts the api and the worker from the same Deployments. They must come up on verify-full against the bundle, with the CNPG CA absent,
# and a URI that names no sslmode or the wrong host must refuse. Destroys the database: throwaway clusters only. Exit 1 on any failure.
set -uo pipefail
KC=${1:?kubeconfig of the kind cluster deploy/kind-test.sh left}
IMG=postgres:16-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab
NS=cmapi-external-db
HOST=external-pg.$NS.svc
k() { kubectl --kubeconfig="$KC" "$@"; }
case "$(k config current-context)" in kind-*) ;; *) echo "ERROR: $KC does not point at a kind cluster; this test removes a database" >&2; exit 2;; esac
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }; ok() { echo "  ok   $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

k -n cmapi scale deploy cmapi-api cmapi-worker --replicas=0 >/dev/null
k -n cmapi wait --for=delete pod -l 'app.kubernetes.io/component in (api,worker)' --timeout=120s >/dev/null || die "the old pods did not go"
k -n cmapi delete cluster cmapi-db >/dev/null || die "could not delete the Cluster"
k -n cmapi wait --for=delete secret/cmapi-db-app secret/cmapi-db-ca --timeout=120s >/dev/null || die "CNPG's Secrets did not go with the Cluster"

openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=external-db-test CA" -keyout "$T/ca.key" -out "$T/ca.crt" 2>/dev/null || die "openssl: CA"
openssl req -newkey rsa:2048 -nodes -subj "/CN=$HOST" -keyout "$T/server.key" -out "$T/server.csr" 2>/dev/null || die "openssl: request"
printf 'subjectAltName=DNS:%s\n' "$HOST" >"$T/san"
openssl x509 -req -in "$T/server.csr" -CA "$T/ca.crt" -CAkey "$T/ca.key" -CAcreateserial -days 2 -extfile "$T/san" -out "$T/server.crt" 2>/dev/null || die "openssl: certificate"
openssl rand -hex 24 >"$T/pw"; chmod 600 "$T/pw"

k create ns "$NS" --dry-run=client -o yaml | k apply -f - >/dev/null
k -n "$NS" create secret generic external-pg --from-file=server.crt="$T/server.crt" --from-file=server.key="$T/server.key" --from-file=password="$T/pw" >/dev/null || die "the server's Secret"
k apply -f - >/dev/null <<YAML || die "the server's Pod"
apiVersion: v1
kind: Service
metadata: {name: external-pg, namespace: $NS}
spec:
  selector: {app: external-pg}
  ports: [{port: 5432}]
---
apiVersion: v1
kind: Pod
metadata: {name: external-pg, namespace: $NS, labels: {app: external-pg}}
spec:
  containers:
    - name: postgres
      image: $IMG
      command: [sh, -c]
      args:
        - >-
          install -o postgres -m 0600 /certs/server.key /tmp/server.key && install -o postgres -m 0644 /certs/server.crt /tmp/server.crt &&
          exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/server.crt -c ssl_key_file=/tmp/server.key
      env:
        - {name: POSTGRES_USER, value: cmapi}
        - {name: POSTGRES_DB, value: cmapi}
        - {name: POSTGRES_PASSWORD_FILE, value: /certs/password}
      readinessProbe:
        exec: {command: [pg_isready, -h, 127.0.0.1, -U, cmapi, -d, cmapi]}
      volumeMounts: [{name: certs, mountPath: /certs, readOnly: true}]
  volumes: [{name: certs, secret: {secretName: external-pg}}]
YAML
k -n "$NS" wait pod/external-pg --for=condition=Ready --timeout=180s >/dev/null || die "the server did not come up"

# docs/12 step 2: the server's CA appended to cmapi-trust. Step 3: the Secret, the password never on an argument list.
k -n cmapi get configmap cmapi-trust -o 'jsonpath={.data.ca-bundle\.crt}' >"$T/bundle" || die "reading cmapi-trust"
cat "$T/ca.crt" >>"$T/bundle"
k -n cmapi create configmap cmapi-trust --from-file=ca-bundle.crt="$T/bundle" --dry-run=client -o yaml | k apply -f - >/dev/null || die "writing cmapi-trust"
{ printf 'apiVersion: v1\nkind: Secret\ntype: Opaque\nmetadata: {name: cmapi-db-app, namespace: cmapi}\nstringData:\n'
  printf '  uri: postgresql://cmapi:%s@%s:5432/cmapi?sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt\n' "$(cat "$T/pw")"  "$HOST"
} | k apply --server-side -f - >/dev/null || die "writing cmapi-db-app"

k -n cmapi scale deploy cmapi-api cmapi-worker --replicas=1 >/dev/null
for c in api worker; do
  if k -n cmapi rollout status "deploy/cmapi-$c" --timeout=300s >/dev/null; then ok "the $c came up, its migrate container through to head"; else bad "the $c did not come up"; fi
done

# What each running container gets from what docs/12 gives it, and what a URI short of it gets. Nothing printed holds the password.
CHECK='import os, sys
import psycopg
uri = os.environ["CMAPI_DATABASE_URL"]
base = uri.split("?")[0]
def attempt(label, url):
    try:
        with psycopg.connect(url, connect_timeout=10) as c:
            print(label, "connected", *c.execute("select ssl from pg_stat_ssl where pid = pg_backend_pid()").fetchone(),
                  *[o.val.decode() for key in (b"sslmode", b"sslrootcert") for o in c.pgconn.info if o.keyword == key])
    except psycopg.OperationalError as exc:
        print(label, "refused", " ".join(str(exc).split()))
print("ca-file", os.path.exists("/etc/cmapi/ca/database-ca.crt"))
attempt("docs12", uri)
attempt("no-sslmode", base)
attempt("wrong-name", base.replace(".svc:", ":") + "?sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt")'
for c in api worker; do
  pod=$(k -n cmapi get pod -l "app.kubernetes.io/component=$c" -o jsonpath='{.items[0].metadata.name}')
  out=$(k -n cmapi exec "$pod" -c "$c" -- python3 -c "$CHECK" 2>&1); printf '%s\n' "$out"
  case "$out" in *"ca-file False"*) ok "$c: no CNPG CA in the pod, and it started" ;; *) bad "$c: the CNPG CA file should be absent";; esac
  case "$out" in *"docs12 connected True verify-full /etc/cmapi/ca/ca-bundle.crt"*) ok "$c: docs/12's URI is verify-full against the bundle";; *) bad "$c: docs/12's URI";; esac
  case "$out" in *"no-sslmode refused"*"root certificate file"*) ok "$c: a URI with no sslmode refuses: no CA, no fallback";; *) bad "$c: a URI with no sslmode did not refuse";; esac
  case "$out" in *"wrong-name refused"*"does not match host name"*) ok "$c: a name the certificate does not cover refuses";; *) bad "$c: a wrong name did not refuse";; esac
done

row=$(k -n "$NS" exec external-pg -- psql -U cmapi -d cmapi -Atc "select count(*) filter (where s.ssl), count(*) filter (where not s.ssl) from pg_stat_ssl s join pg_stat_activity a using (pid) where a.usename='cmapi' and a.client_addr is not null")
echo "  the server's pg_stat_ssl for its clients, on TLS|not: $row"
case "$row" in "0|0"|"") bad "no client connection to read: $row";; *"|0") ok "every client connection is on TLS";; *) bad "a plaintext connection: $row";; esac
rev=$(k -n "$NS" exec external-pg -- psql -U cmapi -d cmapi -Atc "select version_num from alembic_version")
if [ -n "$rev" ]; then ok "the migrations ran on this server: revision $rev"; else bad "no alembic_version on this server"; fi
ready=$(k -n cmapi exec deploy/cmapi-api -c api -- python3 -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/readyz", timeout=5).status)' 2>&1)
if [ "$ready" = 200 ]; then ok "/readyz is 200"; else bad "/readyz: $ready"; fi
echo "external database cases failed: $fails"; [ "$fails" = 0 ]
