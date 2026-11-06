#!/usr/bin/env bash
# docs/12 section 3 step 4's SQL, section 5's restore, and a URI without sslrootcert in a main container's environment, on a
# throwaway PostgreSQL 16 with TLS. usage: restore-test.sh <certs dir> <dump from CNPG 17>
set -uo pipefail
C=$1; DUMP=$2; NET=pr89a-net; PG=pr89a-pg; PW=throwawaypw
cleanup() { podman rm -f $PG pr89a-mig >/dev/null 2>&1; podman network rm $NET >/dev/null 2>&1; }; trap cleanup EXIT
cleanup; podman network create $NET >/dev/null
podman create --name $PG --network $NET --network-alias pr89a-pg -e POSTGRES_PASSWORD=superthrowaway --entrypoint sh docker.io/library/postgres:16-alpine \
  -c 'chown -R postgres /certs; chmod 600 /certs/server.key; exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/certs/server.crt -c ssl_key_file=/certs/server.key' >/dev/null
mkdir -p "$C/in"; cp "$C/server.crt" "$C/server.key" "$C/ca.crt" "$C/in/"; podman cp "$C/in" $PG:/certs; podman start $PG >/dev/null
for _ in $(seq 1 40); do [ "$(podman exec $PG psql -U postgres -Atc 'select 1' 2>/dev/null)" = 1 ] && break; perl -e 'select(undef,undef,undef,1)'; done; perl -e 'select(undef,undef,undef,2)'
podman exec -i $PG psql -q -v ON_ERROR_STOP=1 -U postgres <<SQL
CREATE ROLE cmapi LOGIN PASSWORD '$PW' CONNECTION LIMIT 30;
CREATE DATABASE cmapi OWNER cmapi ENCODING 'UTF8';
REVOKE ALL ON DATABASE cmapi FROM PUBLIC;
CREATE ROLE cmapi2 LOGIN PASSWORD '$PW';
CREATE DATABASE cmapi2 OWNER cmapi2 ENCODING 'UTF8';
SQL
URI_V="postgresql://cmapi:$PW@pr89a-pg:5432/cmapi?sslmode=verify-full&sslrootcert=/certs/ca.crt"
echo "--- step 4's SQL"
podman exec -e PGPASSWORD= $PG psql "$URI_V" -c "select version(), current_user, ssl.ssl from pg_stat_ssl ssl where pid = pg_backend_pid()" | sed -n 3p | cut -c1-20,100-
echo "--- section 5, line 91's shape: verify-full, no sslrootcert, no root.crt on the machine"
podman exec $PG psql "postgresql://cmapi:$PW@pr89a-pg:5432/cmapi?sslmode=verify-full" -Atc 'select 1' 2>&1 | tail -1 | cut -c1-160
echo "--- a URI with verify-full and no sslrootcert, as the migrate container sees it (PGSSLROOTCERT set) and as the main container sees it (not set)"
Q='?sslmode=verify-full'
CMDA=(python3 -c "
import os
from cmapi.core.db import make_engine
print(make_engine(os.environ['CMAPI_DATABASE_URL']).connect().exec_driver_sql('select 1').scalar())")
for extra in $'PGSSLROOTCERT=/etc/cmapi/ca/ca-bundle.crt\n' ""; do
  podman rm -f pr89a-mig >/dev/null 2>&1; { echo "CMAPI_DATABASE_URL=postgresql://cmapi:$PW@pr89a-pg:5432/cmapi$Q"; printf '%s' "$extra"; } >"$C/env"
  podman create --name pr89a-mig --network $NET --env-file "$C/env" --entrypoint python3 localhost/cmapi:dev "${CMDA[@]:1}" >/dev/null
  mkdir -p "$C/ca"; cp "$C/ca.crt" "$C/ca/ca-bundle.crt"; podman cp "$C/ca" pr89a-mig:/etc/cmapi/ca
  out=$(podman start -a pr89a-mig 2>&1); echo "[PGSSLROOTCERT ${extra:+set}${extra:-not set}] rc=$? $(printf '%s' "$out" | grep -E '^[0-9]+$|root certificate|sslmode' | head -1 | cut -c1-170)"
done
echo "--- migrate db cmapi, dump as postgres, restore with section 5's flags into another owner's database"
podman rm -f pr89a-mig >/dev/null 2>&1; echo "CMAPI_DATABASE_URL=postgresql://cmapi:$PW@pr89a-pg:5432/cmapi?sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt" >"$C/env"
podman create --name pr89a-mig --network $NET --env-file "$C/env" --entrypoint cmapi-migrate localhost/cmapi:dev head >/dev/null; podman cp "$C/ca" pr89a-mig:/etc/cmapi/ca; podman start -a pr89a-mig 2>&1 | tail -1
podman exec $PG sh -c 'pg_dump -Fc -U postgres cmapi > /tmp/m.dump; pg_restore -d "postgresql://cmapi2:'"$PW"'@pr89a-pg:5432/cmapi2?sslmode=verify-full&sslrootcert=/certs/ca.crt" --no-owner --role=cmapi2 /tmp/m.dump; echo restore rc=$?'
podman exec $PG psql -U postgres -d cmapi2 -Atc "select count(*)||' tables, owner '||min(tableowner) from pg_tables where schemaname='public'" -c "select 'revision '||version_num from alembic_version"
echo "--- a dump really taken from CNPG's PostgreSQL 17, with a 16 client"
podman cp "$DUMP" $PG:/tmp/c17.dump; podman exec $PG sh -c 'pg_restore --version; pg_restore -l /tmp/c17.dump >/dev/null; echo "pg_restore -l rc=$?"'
