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
| TLS | `sslmode=verify-full` against the server's CA, which the pods read from `/etc/cmapi/ca/ca-bundle.crt` (ConfigMap `cmapi-trust`) | `PGSSLROOTCERT` and `SSL_CERT_FILE` on the initContainer and the main containers |
| An advisory lock | `pg_advisory_lock(727364)` serialises migrators; `lock_timeout` 30 s (`CMAPI_MIGRATE_LOCK_TIMEOUT`) bounds each DDL wait | `core/db/migrations/env.py` |
| Time to come up | the migrate initContainer waits up to 540 s (`CMAPI_MIGRATE_WAIT_SECONDS`) for a server that is not listening | `core/db/migrate.py` |

## 2. On the server

As a superuser, once:

```sql
CREATE ROLE cmapi LOGIN PASSWORD '<generated, never on a command line>' CONNECTION LIMIT 30;
CREATE DATABASE cmapi OWNER cmapi ENCODING 'UTF8';
REVOKE ALL ON DATABASE cmapi FROM PUBLIC;
```

`CONNECTION LIMIT 30` fits one api and one worker (2 × 10) plus two migrators and a margin; raise it with the replica
count (10 per replica). The role owns the database, so the migrations need no further grant: Alembic creates the
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
   # pw.txt holds the password only, mode 0600; it is deleted afterwards
   printf 'uri postgresql://cmapi:%s@db.example.internal:5432/cmapi?sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt\n' \
     "$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(open(sys.argv[1]).read().strip(), safe=""))' pw.txt)" \
   | { printf 'apiVersion: v1\nkind: Secret\ntype: Opaque\nmetadata: {name: cmapi-db-app, namespace: cmapi}\nstringData:\n'; while read -r k v; do printf '  %s: %s\n' "$k" "$v"; done; } \
   | oc apply --server-side -f -
   rm -f pw.txt
   ```

   The key is `uri` and nothing else; CNPG writes the same key, so the Deployments do not know which provided it.
4. Check connectivity and the certificate name from inside the cluster, read-only, before the first migration:

   ```bash
   oc run -n cmapi pg-check --rm -it --restart=Never --image=ghcr.io/cloudnative-pg/postgresql:17@sha256:70664ebcfa1100361b5bdc28bbf06fdbe08db2dc4ad7bd14de33c5e05fe8ea8e \
     --env="PGSSLROOTCERT=/tmp/ca.crt" --overrides='{"spec":{"containers":[{"name":"pg-check","image":"ghcr.io/cloudnative-pg/postgresql:17","command":["sh","-c","psql \"$(cat /run/db/uri)\" -c \"select version(), current_user, ssl.ssl from pg_stat_ssl ssl where pid = pg_backend_pid()\""],"volumeMounts":[{"name":"db","mountPath":"/run/db"},{"name":"ca","mountPath":"/etc/cmapi/ca"}]}],"volumes":[{"name":"db","secret":{"secretName":"cmapi-db-app"}},{"name":"ca","configMap":{"name":"cmapi-trust"}}]}}'
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

With the api and the worker scaled to 0 (nothing writes):

```bash
oc -n cmapi scale deploy cmapi-api cmapi-worker --replicas=0
oc -n cmapi exec cmapi-db-1 -c postgres -- pg_dump -Fc -U cmapi cmapi > cmapi.dump
pg_restore -d "postgresql://cmapi@db.example.internal:5432/cmapi?sslmode=verify-full" --no-owner --role=cmapi cmapi.dump
```

Then replace `cmapi-db-app` (section 3), scale back up, and confirm `/readyz` is 200 and `select count(*) from
change_requests` matches. The CNPG `Cluster` carries `Prune=false,Delete=false`, so removing its file from Git does not
delete it: delete it by hand when the move is proven.

## 6. Not measured

This guide was written from the code and from CNPG runs on kind. No run against an external server exists yet: the
first site that does one records `pg_stat_ssl`, the migration time and the connection count here.
