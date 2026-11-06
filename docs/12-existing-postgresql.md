# Consuming an existing PostgreSQL server

cmapi's default database is one CloudNativePG `Cluster` (`deploy/manifests/components/database-cnpg/cluster.yaml`,
operator 1.30.1 on CRC). A site with its own PostgreSQL server uses that instead. This guide is the whole procedure;
nothing in the application changes, only what provides Secret `cmapi-db-app`.

Both designs of the deployment (`docs/reviews/2026-11-05-deployment-design.md`, D4) agreed on this list; the numbers
come from the code and from what the kind runs measured.

## 1. What cmapi needs from the server

| Need | Value | Where it comes from |
|---|---|---|
| Version | PostgreSQL 16 or 17 | `cmapi/tests/service` runs on 16; CNPG ships 17 (`ghcr.io/cloudnative-pg/postgresql:17`) |
| Database | `cmapi`, owned by a role `cmapi` that is **not** a superuser | `bootstrap.initdb` in the CNPG `Cluster`; the migrations create every table |
| Connections | each api or worker pod holds a pool of **5 plus 5 overflow**; the migrate initContainer one more while it runs | `core/db/__init__.py` (`pool_size=5, max_overflow=5`) |
| TLS | `sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt` in the URI, against the server's CA in ConfigMap `cmapi-trust` | The URI is the one place: neither container sets `PGSSLROOTCERT`, so a URI without `sslrootcert` fails at the first migration with `root certificate file ... does not exist` (measured) |
| An advisory lock | `pg_advisory_lock(727364)` serialises migrators; `lock_timeout` 30 s (`CMAPI_MIGRATE_LOCK_TIMEOUT`) bounds each DDL wait | `core/db/migrations/env.py` |
| Time to come up | the migrate initContainer waits up to 540 s (`CMAPI_MIGRATE_WAIT_SECONDS`) for a server that is not listening | `core/db/migrate.py` |

## 2. On the server

As a superuser, once:

```sql
CREATE ROLE cmapi LOGIN PASSWORD '<generated, never on a command line>' CONNECTION LIMIT 45;
CREATE DATABASE cmapi OWNER cmapi ENCODING 'UTF8';
REVOKE ALL ON DATABASE cmapi FROM PUBLIC;
```

`CONNECTION LIMIT 45` fits one api and one worker through a rolling update, when the old and the new pod of each hold a
pool at once (4 × 10), plus two migrators and a margin; raise it with the replica count (20 per replica, 10 for the
pod and 10 for its surge). The role owns the database, so the migrations need no further grant: Alembic creates the
`alembic_version` table and every cmapi table under that ownership. Do not grant `SUPERUSER` or `CREATEDB`.

Require TLS from that role in `pg_hba.conf` (`hostssl cmapi cmapi <cluster cidr> scram-sha-256`), and make sure the
server certificate's name is the one the pods will connect to (`verify-full` checks it).

## 3. On the cluster

1. Leave `components/database-cnpg/` out of what you apply: `deploy/render.sh` copies the whole `components/` tree, so
   delete `components/database-cnpg/` from the rendered output before applying it (a later environment switch may make
   this a flag; today it is a `rm -r`).
2. Put the server's CA in `cmapi-trust` (`environments/<env>/*trust*.yaml`), appended to the other certificates the pods
   trust. An invalid bundle crash-loops the api and the worker with `ssl.SSLError: NO_CERTIFICATE_OR_CRL_FOUND`
   (measured on kind): the file must hold at least one well-formed PEM certificate.
3. Create the Secret the manifests read, in namespace `cmapi`, **before** the components, with the password read from a
   file so that it never reaches an argument list or a shell history:

   ```bash
   # pw.txt holds the password only, mode 0600; it is deleted only once the Secret is written
   ( set -o pipefail
     enc=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(open(sys.argv[1]).read().strip(), safe=""))' pw.txt) &&
     printf 'uri postgresql://cmapi:%s@db.example.internal:5432/cmapi?sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt\n' "$enc" \
     | { printf 'apiVersion: v1\nkind: Secret\ntype: Opaque\nmetadata: {name: cmapi-db-app, namespace: cmapi}\nstringData:\n'; while read -r k v; do printf '  %s: %s\n' "$k" "$v"; done; } \
     | oc apply --server-side -f - ) && rm -f pw.txt
   ```

   The key is `uri` and nothing else; CNPG writes the same key, so the Deployments do not know which provided it.
4. Check connectivity and the certificate name from inside the cluster, read-only, before the first migration:

   ```bash
   # --overrides replaces the whole containers list, so the digest is repeated there and nothing else may rely on --image or --env.
   # The URI's password goes to psql decoded, in PGPASSWORD, and the rest of the URI as its argument: an argument list is readable.
   oc run -n cmapi pg-check --rm -it --restart=Never --image=ghcr.io/cloudnative-pg/postgresql:17@sha256:70664ebcfa1100361b5bdc28bbf06fdbe08db2dc4ad7bd14de33c5e05fe8ea8e \
     --overrides='{"spec":{"containers":[{"name":"pg-check","image":"ghcr.io/cloudnative-pg/postgresql:17@sha256:70664ebcfa1100361b5bdc28bbf06fdbe08db2dc4ad7bd14de33c5e05fe8ea8e","command":["bash","-c","uri=$(cat /run/db/uri); pw=${uri#*://*:}; pw=${pw%%@*}; export PGPASSWORD=$(printf %b \"${pw//%/\\\\x}\"); exec psql \"${uri/\":$pw@\"/@}\" -c \"select version(), current_user, ssl.ssl from pg_stat_ssl ssl where pid = pg_backend_pid()\""],"volumeMounts":[{"name":"db","mountPath":"/run/db"},{"name":"ca","mountPath":"/etc/cmapi/ca"}]}],"volumes":[{"name":"db","secret":{"secretName":"cmapi-db-app"}},{"name":"ca","configMap":{"name":"cmapi-trust"}}]}}'
   ```

   It must print the version, `cmapi` and `ssl = t`. A wrong CA or name fails here with the same message the
   initContainer would print 540 s later.
5. Apply the components. The migrate initContainer runs `cmapi-migrate head` against the server, serialised by the
   advisory lock; `/readyz` answers 200 when the schema is at or past the code's revision.

## 4. Running it

- **Migrations** are expand-only. A rollback of the image keeps running on a later schema (the old migrator exits 0 on
  a later four-digit revision, and `/readyz` counts it as ready); a divergent or unknown revision is refused by both.
  Nothing rolls a data migration back; none exists yet.
- **A changed password.** The pods read `cmapi-db-app` at start. A pod started from a Secret the server no longer
  accepts waits on the stale password until the 540 s wait runs out and then crash-loops (measured on kind with a CNPG
  cluster recreated under running pods): after a rotation, update the Secret and restart the api and the worker.
- **Backups, HA, upgrades and credential rotation** belong to the server's operator, not to cmapi. cmapi holds no
  backup of its own data; the schema is reproducible from the migrations, the data is not.
- **Limits to watch.** `max_connections` on the server against the pods' pools (10 each), and the `lock_timeout`: a
  migration queued behind a long transaction gives up after 30 s and the pod restarts, which is the right behaviour.

## 5. Moving from CloudNativePG to an existing server

`cmapi-db-app` cannot be replaced while the `Cluster` exists. CNPG owns it: its type is `kubernetes.io/basic-auth`, so
applying section 3's Opaque Secret over it fails (`type: field is immutable`), and if it is deleted the operator writes it
back at once; deleting the `Cluster` garbage-collects it, and removes the PVC too (measured, CNPG 1.30.1 on kind). So prove
the copy first, with the workloads at 0, and only then delete the `Cluster` and create the Secret.

Where Argo CD syncs cmapi, turn its automated sync off first and put it back at the end: the Deployments say `replicas: 1`,
and self-heal undoes a hand edit (measured at 40 s on an image, the deployment design, D3), so the workloads would come back
during the dump. The block below stops if they did.

```bash
( set -euo pipefail   # a subshell: set -e in a terminal's own shell would close it on the first failure
  oc -n cmapi scale deploy cmapi-api cmapi-worker --replicas=0
  # scale returns at once, and a worker finishes the job in hand for up to 60 s: what it writes after the dump's snapshot is lost.
  oc -n cmapi wait --for=delete pod -l 'app.kubernetes.io/component in (api,worker)' --timeout=120s
  # On the pod's socket only the database user postgres may connect (peer, CNPG's ident map); -U cmapi is refused there.
  oc -n cmapi exec cmapi-db-1 -c postgres -- pg_dump -Fc -U postgres cmapi > cmapi.dump
  test -s cmapi.dump
  # ca-bundle.crt is the server's CA on this machine: verify-full with no root certificate is an error. pg_restore and psql must
  # be 17 or later (CNPG's pg_dump is 17; a 16 client refuses the archive: "unsupported version (1.16) in file header").
  export PGSSLROOTCERT=$PWD/ca-bundle.crt
  TARGET="postgresql://cmapi@db.example.internal:5432/cmapi?sslmode=verify-full"
  # All or nothing, on 16 and 17, through psql and not pg_restore -d. pg_restore 17 always opens with SET transaction_timeout,
  # which PostgreSQL 16 does not have (measured): plain pg_restore -d restores everything and then exits 1, which stops this
  # block, and pg_restore --single-transaction fails on it before the first object. The awk removes that one line, the first
  # match only, so table data cannot be touched. A failed restore leaves the target as it was, so it can simply be run again.
  pg_restore -f - --no-owner --role=cmapi cmapi.dump \
    | LC_ALL=C awk '!done && $0 == "SET transaction_timeout = 0;" { done = 1; next } { print }' \
    | psql -X -q -v ON_ERROR_STOP=1 --single-transaction -d "$TARGET" -f - >/dev/null
  # These two counts must match. Keep cmapi.dump: the next step destroys the source.
  source_rows=$(oc -n cmapi exec cmapi-db-1 -c postgres -- psql -U postgres -d cmapi -Atc 'select count(*) from change_requests')
  target_rows=$(psql "$TARGET" -Atc 'select count(*) from change_requests')
  echo "change_requests: source $source_rows, target $target_rows"
  [ "$source_rows" = "$target_rows" ]
  # And nothing came back while it ran, or the dump is not the last word.
  [ -z "$(oc -n cmapi get pod -l 'app.kubernetes.io/component in (api,worker)' -o name)" ]
)
```

Then, in this order: take `components/database-cnpg/` out of what is applied (the `Cluster` carries
`Prune=false,Delete=false`, so removing its file from Git does not delete it, and leaving the file in would recreate it);
`oc -n cmapi delete cluster cmapi-db`; create the Secret (section 3, step 3); scale back up, or turn Argo CD's automated sync
back on; confirm `/readyz` is 200.

## 6. Not measured

Run against a PostgreSQL 16 with TLS in a container (sections 2 and 3: the real migrator, `verify-full`, a wrong CA and a
wrong name refused, `pg_stat_ssl` true) and against CNPG 1.30.1 on kind (section 5's dump and the Secret's ownership).
Section 5's restore ran from the CNPG image's pg_restore and psql 17.11, without TLS, on the real migrations' schema and on
PostgreSQL 16.15 and 17.11 targets: a complete copy, and a failure on the last table leaving the target as it was. Not run:
that restore of a dump from a real CNPG cluster, or Argo CD's automated sync being turned off around it. No
run against a real external server on a cluster exists yet: the first site that does one records `pg_stat_ssl`, the
migration time and the connection count here.
