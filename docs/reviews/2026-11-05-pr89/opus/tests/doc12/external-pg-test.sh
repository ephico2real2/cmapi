#!/usr/bin/env bash
# docs/12 sections 2 and 3 against a real PostgreSQL 16 with TLS in a throwaway podman container (prefix pr89a-), migrating with
# the real image (localhost/cmapi:dev, built from 1f30ab1; cmapi/src is unchanged in this PR). usage: external-pg-test.sh <certs dir>
set -uo pipefail
C=$1; NET=pr89a-net; PG=pr89a-pg
PW='p@ss%w/rd:#&?x y'    # a throwaway password with every character the URI must encode
cleanup() { podman rm -f $PG pr89a-mig >/dev/null 2>&1; podman network rm $NET >/dev/null 2>&1; }; trap cleanup EXIT
cleanup; podman network create $NET >/dev/null
podman create --name $PG --network $NET --network-alias pr89a-pg --network-alias pr89a-wrongname -e POSTGRES_PASSWORD=superthrowaway --entrypoint sh docker.io/library/postgres:16-alpine \
  -c 'chown -R postgres /certs; chmod 600 /certs/server.key; exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/certs/server.crt -c ssl_key_file=/certs/server.key' >/dev/null
mkdir -p "$C/in"; cp "$C/server.crt" "$C/server.key" "$C/in/"; podman cp "$C/in" $PG:/certs; podman start $PG >/dev/null
for _ in $(seq 1 40); do podman exec $PG pg_isready -U postgres >/dev/null 2>&1 && [ "$(podman exec $PG psql -U postgres -Atc 'select 1' 2>/dev/null)" = 1 ] && break; sleep 1; done
sleep 2
echo "--- section 2, the SQL verbatim, with a password from no command line"
podman exec -i $PG psql -v ON_ERROR_STOP=1 -U postgres <<SQL
CREATE ROLE cmapi LOGIN PASSWORD '$PW' CONNECTION LIMIT 30;
CREATE DATABASE cmapi OWNER cmapi ENCODING 'UTF8';
REVOKE ALL ON DATABASE cmapi FROM PUBLIC;
SQL
echo "rc=$?"
# pg_hba as the guide says, nothing but TLS for that role
podman exec -i $PG sh -c 'cat > "$PGDATA/pg_hba.conf"' <<'HBA'
local all all trust
hostssl cmapi cmapi all scram-sha-256
HBA
podman exec $PG psql -U postgres -c 'select pg_reload_conf()' >/dev/null
printf '%s' "$PW" > "$C/pw.txt"; chmod 600 "$C/pw.txt"
ENC=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(open(sys.argv[1]).read().strip(), safe=""))' "$C/pw.txt")
run_mig() { # label, host, ca file, query, extra env lines
  local label=$1 host=$2 ca=$3 q=$4 extra=${5:-}
  podman rm -f pr89a-mig >/dev/null 2>&1
  { echo "CMAPI_DATABASE_URL=postgresql://cmapi:$ENC@$host:5432/cmapi$q"; echo "CMAPI_MIGRATE_WAIT_SECONDS=4"; printf '%s' "$extra"; } > "$C/env"
  podman create --name pr89a-mig --network $NET --env-file "$C/env" --entrypoint "${CMD[0]}" localhost/cmapi:dev "${CMD[@]:1}" >/dev/null
  mkdir -p "$C/ca"; cp "$ca" "$C/ca/ca-bundle.crt"; podman cp "$C/ca" pr89a-mig:/etc/cmapi/ca
  out=$(podman start -a pr89a-mig 2>&1); rc=$?
  echo "[$label] rc=$rc: $(printf '%s' "$out" | tail -1 | sed "s/$ENC/<pw>/g" | cut -c1-200)"
}
Q='?sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt'
CMD=(cmapi-migrate head)
echo "--- section 3: the guide's URI, the real migrator"
run_mig "right CA, right name" pr89a-pg "$C/ca.crt" "$Q"
podman exec $PG psql -U postgres -d cmapi -Atc "select 'alembic_version='||version_num from alembic_version" -c "select 'owner of change_requests='||tableowner from pg_tables where tablename='change_requests'"
run_mig "twice is a no-op" pr89a-pg "$C/ca.crt" "$Q"
run_mig "wrong CA must fail" pr89a-pg "$C/other.crt" "$Q"
run_mig "wrong name must fail" pr89a-wrongname "$C/ca.crt" "$Q"
CMD=(python3 -c "
import os,psycopg
from cmapi.core.db import sqlalchemy_url, make_engine
e=make_engine(os.environ['CMAPI_DATABASE_URL'])
with e.connect() as c:
    print('engine:',c.exec_driver_sql('select current_user, s.ssl, s.version from pg_stat_ssl s where s.pid=pg_backend_pid()').fetchone())
")
echo "--- the api's engine (make_engine) with the guide's URI"
run_mig "make_engine" pr89a-pg "$C/ca.crt" "$Q"
echo "--- the same engine with no PGSSLROOTCERT in the environment but the URI's sslrootcert: that is what the main containers have"
echo "--- now the default path's shape, a URI with no sslmode (CNPG's), server allowing both TLS and not"
podman exec -i $PG sh -c 'cat > "$PGDATA/pg_hba.conf"' <<'HBA'
local all all trust
host cmapi cmapi all scram-sha-256
HBA
podman exec $PG psql -U postgres -c 'select pg_reload_conf()' >/dev/null
run_mig "no sslmode, no PGSSLROOTCERT (main container)" pr89a-pg "$C/ca.crt" ""
run_mig "no sslmode, PGSSLROOTCERT = bundle without the server's CA (migrate initContainer)" pr89a-pg "$C/other.crt" "" $'PGSSLROOTCERT=/etc/cmapi/ca/ca-bundle.crt\n'
run_mig "no sslmode, PGSSLROOTCERT = bundle with the server's CA" pr89a-pg "$C/ca.crt" "" $'PGSSLROOTCERT=/etc/cmapi/ca/ca-bundle.crt\n'
