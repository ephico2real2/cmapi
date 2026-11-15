#!/usr/bin/env bash
# shellcheck disable=SC2015,SC2016  # ok and bad never fail, and the single-quoted scripts run in the container
# deploy/tests/crc-backup-test.sh [<deploy dir>]: deploy/crc-backup.sh on a real PostgreSQL of the image family postgres-0 runs, with oc exec standing on the container runtime's exec.
# The image's own variables, its own rules, a full dump, the proof of the file, a restore of it into an empty database. Its stops on a real server: the rules tightened, a wrong
# password, the variables missing, a stream cut short. Test values only. CI uses quay.io/sclorg/postgresql-16-c9s, the public build of the same image scripts; set PG_IMAGE to
# registry.redhat.io/rhel9/postgresql-16@sha256:... where a login exists. One container, cmapi-w1-backup, labelled, no published port, removed at the end. Never touches a cluster.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); SRC=$(cd "${1:-$HERE/..}" && pwd); W=$(mktemp -d)
C=${CONTAINER:-docker}   # CONTAINER=podman on a Mac
PG_IMAGE=${PG_IMAGE:-quay.io/sclorg/postgresql-16-c9s@sha256:29e66548679f0d14b63e2a210dfcc783c376330366bd24b97f2968e7c3bff0f7}
N=cmapi-w1-backup; LABEL=cmapi.test=crc-backup-test; PW=test-only-backup-password
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }; ok() { echo "  ok   $*"; }
# Only what this test labelled: a container of that name without the label is somebody else's, and the run stops at its own docker run.
cleanup() { $C ps -a -q --filter "label=$LABEL" | while read -r id; do $C rm -f "$id" >/dev/null; done; rm -rf "$W"; }
trap cleanup EXIT
mkdir "$W/bin"; export ARGV_LOG=$W/argv.log N C
cat >"$W/bin/oc" <<'OC'
#!/usr/bin/env bash
printf 'oc %s\n' "$*" >>"$ARGV_LOG"
case "$*" in
  "get pod postgres-0 -n keycloak -o json") printf '{"spec":{"containers":[{"name":"postgres","image":"rhel9/postgresql-16","resources":{"limits":{"memory":"512Mi"}},"env":[{"name":"POSTGRESQL_USER","valueFrom":{"secretKeyRef":{"name":"keycloak-db","key":"user"}}}]}]}}\n'; exit 0;;
  "get pod postgres-0 -n keycloak -o jsonpath"*) printf 512Mi; exit 0;;
  "adm top pod postgres-0"*) echo "postgres-0 5m 52Mi"; exit 0;;
esac
[ "$1" = exec ] || { echo "shim: unhandled $*" >&2; exit 3; }
shift; i=; if [ "$1" = -i ]; then i=-i; shift; fi
while [ "$1" != -- ]; do shift; done; shift
[ "$1 $2" = "sh -c" ] || { echo "shim: not sh -c" >&2; exit 3; }
envs=(); for e in ${SHIM_ENV:-}; do envs+=(-e "$e"); done
if [ -n "${SHIM_CUT:-}" ] && [[ "$3" == *pg_dump* ]]; then
  # The stream ends early with a clean status: what --list passes and only a full read catches. SHIM_CUT is a byte count, or half.
  t=$(mktemp); $C exec "${envs[@]}" "$N" sh -c "$3" >"$t"; rc=$?
  python3 -c 'import sys; d=open(sys.argv[1],"rb").read(); n=len(d)//2 if sys.argv[2]=="half" else int(sys.argv[2]); sys.stdout.buffer.write(d[:-n])' "$t" "$SHIM_CUT"; rm -f "$t"; exit "$rc"
fi
# With stdin, as CRI-O's exec does: a command that ends with stdin unread fails the exec ("write |1: broken pipe", measured on CRC, #268). CRI-O fails
# only past the pipe buffer; this fails on any unread byte, and the dump below is larger than the buffer, so both would fail.
if [ -n "$i" ]; then
  exec $C exec -i "${envs[@]}" "$N" sh -c 'sh -c "$1"; rc=$?; left=$(wc -c | tr -d " "); [ "$left" = 0 ] || { echo "error executing command in container: write |1: broken pipe ($left bytes of stdin unread)" >&2; exit 1; }; exit $rc' sh "$3"
fi
exec $C exec "${envs[@]}" "$N" sh -c "$3"
OC
printf '#!/bin/sh\nexit 0\n' >"$W/bin/tmutil"; chmod +x "$W/bin/"*
export PATH="$W/bin:$PATH" CMAPI_BACKUP_DIR=$W/backup
B() { : >"$ARGV_LOG"; "$SRC/crc-backup.sh" "$@" >"$W/out" 2>&1; echo $?; }
in_c() { $C exec "$N" sh -c "$1"; }

$C run -d --name "$N" --label "$LABEL" --memory=512m -e POSTGRESQL_USER=kctest -e "POSTGRESQL_PASSWORD=$PW" -e POSTGRESQL_DATABASE=kcdb "$PG_IMAGE" >/dev/null || { echo "ERROR: could not start $PG_IMAGE" >&2; exit 1; }
[ -z "$($C port "$N")" ] && ok "no port published" || bad "a port is published: $($C port "$N")"
for _ in $(seq 1 60); do in_c 'pg_isready -q -h 127.0.0.1 -d postgres' 2>/dev/null && in_c 'psql -w -U "$POSTGRESQL_USER" -d "$POSTGRESQL_DATABASE" -Atc "select 1"' >/dev/null 2>&1 && break; sleep 2; done
sleep 3
echo "image: $PG_IMAGE: $(in_c 'pg_dump --version')"
# As a Keycloak database holds them: odd ids, a multi-line value, and a second table.
$C exec -i "$N" sh -c 'psql -q -w -U "$POSTGRESQL_USER" -d "$POSTGRESQL_DATABASE" -v ON_ERROR_STOP=1' <<'SQL' >/dev/null || bad "could not seed the database"
create table realm(id text primary key, name text); insert into realm select 'id-'||g, E'name\nwith a newline '||g from generate_series(1,6) g;
insert into realm values (E'tab\there', 'x');
create table client(id serial primary key, secret text); insert into client(secret) select md5(g::text) from generate_series(1,2000) g;
-- Random hex, which compresses to about half: a dump well past a 64 KiB pipe buffer, as the shared Keycloak's 14 MB database gives (#268). Named as Keycloak's
-- own table, which sorts after realm: pg_dump writes table data in name order, so realm's data is not the archive's last and -t realm stops short of the end,
-- as on Keycloak's database (realm_attribute ... user_entity ... follow it), and a cut tail is caught only by the full read, not by the realm count.
create table user_entity(x text); insert into user_entity select md5(random()::text)||md5(random()::text)||md5(random()::text)||md5(random()::text) from generate_series(1,8000) g;
SQL

# 1. The image as it ships.
HBA=/var/lib/pgsql/data/userdata/pg_hba.conf
echo "the image's rules: $(in_c "grep -E '^(local|host) +all' $HBA | tr -s ' ' | tr '\n' ';'")"
rc=$(B); [ "$rc" = 0 ] && ok "a backup on the image as it ships" || bad "a backup on the image as it ships: rc $rc: $(tail -2 "$W/out")"
tail -1 "$W/out" | grep -q '7 realms, read to its end' && ok "it counted the seven realm rows: $(tail -1 "$W/out" | sed 's/^backup in [^:]*: //')" || bad "its last line: $(tail -1 "$W/out")"
f=$(find "$W/backup" -type f -name 'keycloak-*.dump'); [ -n "$f" ] && ok "one dump in the directory" || bad "no dump"
size=$(wc -c <"$f" | tr -d " "); [ "${size:-0}" -gt 65536 ] && ok "the dump is larger than a pipe buffer: $size bytes" || bad "the dump is $size bytes, not past a 64 KiB pipe buffer: the stdin case proves nothing"
# Each partial reader must leave more than a pipe buffer unread on this dump, or the stand-in's stdin rule proves nothing for that check.
for r in 'pg_restore --list' 'pg_restore -a -t realm -f -'; do
  left=$($C exec -i "$N" sh -c "$r >/dev/null; wc -c" <"$f" 2>/dev/null | tr -d ' ')
  [ "${left:-0}" -gt 65536 ] && ok "$r leaves $left bytes of the dump unread" || bad "$r leaves ${left:-no} bytes unread, not past a 64 KiB pipe buffer: its drain is not tested"
done
# The GNU form first: GNU's -f writes the file system's details on stdout before it fails, while BSD's stat refuses -c with nothing on stdout (#90).
m() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }; [ "$(m "$W/backup")" = 700 ] && [ "$(m "$f")" = 600 ] && ok "directory 0700, file 0600" || bad "modes $(m "$W/backup") $(m "$f")"
if grep -qF -e "$PW" -e "$f" "$W/out"; then bad "the password or the path reached the output"; else ok "no password and no path in the output"; fi
if grep -qF "$PW" "$ARGV_LOG"; then bad "the password reached an argument"; else ok "no password on any argument"; fi
# The file restores: into an empty database, the steps docs/13 gives the owner.
in_c 'psql -q -w -U postgres -d postgres -c "create database restored owner kctest"' || bad "could not create the database to restore into"
$C exec -i "$N" sh -c 'PGPASSWORD="$POSTGRESQL_PASSWORD" pg_restore -w -h 127.0.0.1 --single-transaction -U "$POSTGRESQL_USER" -d restored' <"$f" || bad "the dump did not restore"
got=$(in_c 'psql -w -U postgres -d restored -Atc "select (select count(*) from realm)||chr(124)||(select count(*) from client)||chr(124)||(select md5(string_agg(secret, chr(44) order by id)) from client)"')
want=$(in_c 'psql -w -U postgres -d kcdb -Atc "select (select count(*) from realm)||chr(124)||(select count(*) from client)||chr(124)||(select md5(string_agg(secret, chr(44) order by id)) from client)"')
[ -n "$got" ] && [ "$got" = "$want" ] && ok "restored into an empty database, the rows are the same: $got" || bad "restored: $got, not $want"
rc=$(B --delete); [ ! -e "$W/backup" ] && ok "--delete removes it" || bad "--delete left it: rc $rc"

stops() { # stops <label> [--why <text>] [VAR=VALUE...]: the backup must fail, say why (with --why, that check and no other), and leave no file.
  local label=$1 why='' rc; shift; if [ "${1:-}" = --why ]; then why=$2; shift 2; fi
  rc=$(env "$@" "$SRC/crc-backup.sh" >"$W/out" 2>&1; echo $?)
  if [ "$rc" = 0 ]; then bad "did not stop: $label"
  elif [ -n "$why" ] && ! grep -qF "$why" "$W/out"; then bad "$label: stopped, but not with \"$why\": $(grep -m1 ERROR "$W/out" | cut -c1-110)"
  else ok "stops: $label: $({ grep -m1 ERROR "$W/out" || tail -1 "$W/out"; } | cut -c1-110)"; fi
  if find "$W/backup" -type f 2>/dev/null | grep -q .; then bad "$label: left a file"; fi
  if grep -qF "$PW" "$W/out"; then bad "$label: the password in the output"; fi
  rm -rf "$W/backup"
}
# 2. Stops on the image as it ships.
stops "POSTGRESQL_USER empty" SHIM_ENV=POSTGRESQL_USER=
stops "POSTGRESQL_DATABASE empty" SHIM_ENV=POSTGRESQL_DATABASE=
stops "POSTGRESQL_PASSWORD empty" SHIM_ENV=POSTGRESQL_PASSWORD=
stops "a database that does not exist" SHIM_ENV=POSTGRESQL_DATABASE=nothere
stops "a stream 100 bytes short with a clean status" --why "the archive does not read to its end" SHIM_CUT=100
stops "a stream half gone with a clean status" --why "the archive does not read to its end" SHIM_CUT=half

# 3. The rules tightened: peer on the socket, password on the loopback. A socket-only backup could not sign in here; this one still can, and a wrong password stops it.
in_c "sed -i -E 's/^local +all +all +trust/local all all peer/; s#^host +all +all +127.0.0.1/32 +trust#host all all 127.0.0.1/32 md5#; s#^host +all +all +::1/128 +trust#host all all ::1/128 md5#' $HBA && pg_ctl reload -D /var/lib/pgsql/data/userdata >/dev/null" || bad "could not tighten the rules"
sleep 2
echo "the tightened rules: $(in_c "grep -E '^(local|host) +all' $HBA | tr -s ' ' | tr '\n' ';'")"
in_c 'psql -w -U "$POSTGRESQL_USER" -d "$POSTGRESQL_DATABASE" -Atc "select 1"' >/dev/null 2>&1 && bad "the socket still accepts this user, so this case proves nothing" || ok "the socket now refuses this user"
rc=$(B); [ "$rc" = 0 ] && ok "a backup under the tightened rules, by the password on the loopback" || bad "a backup under the tightened rules: rc $rc: $(tail -1 "$W/out" | cut -c1-140)"
rm -rf "$W/backup"
stops "a wrong password" SHIM_ENV=POSTGRESQL_PASSWORD=wrong-password

echo "crc backup cases failed: $fails"; [ "$fails" = 0 ]
