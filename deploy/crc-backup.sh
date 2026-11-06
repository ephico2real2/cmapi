#!/usr/bin/env bash
# shellcheck disable=SC2016  # the single-quoted scripts run in the pod, on the pod's environment, which is the point
# deploy/crc-backup.sh: the owner-approved, read-only backup of the shared Keycloak database, taken as the step immediately before the realm import.
#   --inspect   what the backup would use, from the pod spec: container, image, env NAMES with where each comes from, the memory limit. Never a value.
#   (no flag)   dumps, proves the file usable, and stops the run on any failure.
#   --delete    removes the backup once the run is verified.
# The dump holds every realm's secrets and users. It is never written inside the pod (stdout, over oc exec), never leaves ~/.cmapi-keycloak-backup (0700, file 0600),
# and nothing here prints its path beyond that directory or any of its content: only byte and row counts. Credentials stay in the pod's own environment,
# expanded by the pod's shell: nothing reaches this Mac's argument list or a log. Restoring is the owner's decision, never automatic (docs/13, "Restoring").
set -euo pipefail
OC=${CMAPI_OC:-oc}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
DIR=${CMAPI_BACKUP_DIR:-$HOME/.cmapi-keycloak-backup}
POD=postgres-0; NS=keycloak
MIN_ROOM_MI=${CMAPI_BACKUP_MIN_ROOM_MI:-128}
# Runs inside postgres-0, on the variables of Red Hat's postgresql-16 image, the image it runs. Anything else stops here: exit 64, no guess at another image's names.
# TCP to the pod's own loopback, not the socket: measured on that image (registry.redhat.io/rhel9/postgresql-16, PostgreSQL 16.15), the image's rules trust both, and if a socket
# rule were peer this user could not use it, while the password below still works on 127.0.0.1 (deploy/tests/crc-backup-test.sh). -w: fail, never prompt.
DBENV='U=${POSTGRESQL_USER:-}; D=${POSTGRESQL_DATABASE:-}; P=${POSTGRESQL_PASSWORD:-}; [ -n "$U" ] && [ -n "$D" ] && [ -n "$P" ] || { echo "POSTGRESQL_USER, POSTGRESQL_DATABASE or POSTGRESQL_PASSWORD is not set in this pod" >&2; exit 64; }; export PGPASSWORD="$P"; export PGHOST=127.0.0.1;'
in_pod() { oc_ exec "$POD" -n "$NS" -c "$CONTAINER" -- sh -c "$DBENV $1"; }
in_pod_stdin() { oc_ exec -i "$POD" -n "$NS" -c "$CONTAINER" -- sh -c "$1"; }
container() { oc_ get pod "$POD" -n "$NS" -o json | python3 -c 'import json,sys
c=json.load(sys.stdin)["spec"]["containers"]
if len(c)!=1: sys.exit("postgres-0 has %d containers; say which by hand" % len(c))
print(c[0]["name"])'; }
inspect() {
  oc_ get pod "$POD" -n "$NS" -o json | python3 -c 'import json,sys
for c in json.load(sys.stdin)["spec"]["containers"]:
    print("container",c["name"],"image",c.get("image"))
    print("memory",c.get("resources",{}))
    for e in c.get("env",[]):
        src=e.get("valueFrom")
        print("env",e["name"],"from "+json.dumps({k:{x:v for x,v in s.items() if x in("name","key")} for k,s in src.items()}) if src else "(literal; value not shown)")
    for e in c.get("envFrom",[]):
        print("envFrom",json.dumps(e))'
}
room_mi() { # limit minus usage, from the metrics API. No limit is plenty; no reading is a stop, not a guess.
  local limit used
  limit=$(oc_ get pod "$POD" -n "$NS" -o 'jsonpath={.spec.containers[0].resources.limits.memory}')
  used=$(oc_ adm top pod "$POD" -n "$NS" --no-headers | awk '{print $3}')
  python3 -c 'import re,sys
def mi(q):
    m=re.fullmatch(r"(\d+)(Ki|Mi|Gi)?",q)
    if not m: sys.exit("cannot read the quantity "+repr(q))
    return int(m[1])*{"Ki":1/1024,"Mi":1,"Gi":1024,None:1/1048576}[m[2]]
print(int(mi(sys.argv[1])-mi(sys.argv[2])) if sys.argv[1] else 999999)' "$limit" "$used"
}
backup() {
  [ ! -L "$DIR" ] || { echo "ERROR: the backup directory is a symbolic link; refusing it" >&2; exit 1; }
  ( umask 077; mkdir -p "$DIR" ); chmod 700 "$DIR"
  # Time Machine must not copy every realm's secrets somewhere the delete cannot reach.
  if command -v tmutil >/dev/null 2>&1; then tmutil addexclusion "$DIR" >/dev/null 2>&1 || echo "note    : could not exclude the backup directory from Time Machine" >&2; fi
  CONTAINER=$(container)
  room=$(room_mi); [ "$room" -ge "$MIN_ROOM_MI" ] || { echo "ERROR: postgres-0 has $room Mi of room under its limit; pg_dump runs in that container's cgroup, and it must not push the shared database towards an OOM kill" >&2; exit 1; }
  slots=$(in_pod 'psql -w -U "$U" -d "$D" -Atc "select current_setting('"'"'max_connections'"'"')::int - count(*) from pg_stat_activity"')
  [ "$slots" -ge 5 ] || { echo "ERROR: only $slots free connections on the shared database" >&2; exit 1; }
  F=$DIR/keycloak-$(date -u +%Y%m%dT%H%M%SZ).dump
  trap 'rm -f "$F" "$F.err"; echo "the partial backup is removed" >&2; exit 1' ERR INT TERM HUP
  ( umask 077; : >"$F"; : >"$F.err" ); chmod 600 "$F" "$F.err"
  t0=$(date +%s)
  # Custom format, one connection, a snapshot, no lock any writer waits on. --lock-wait-timeout: fail rather than queue behind DDL, because a queued lock would hold others up.
  in_pod 'exec pg_dump -w -Fc --lock-wait-timeout=30s -U "$U" "$D"' >"$F" 2>"$F.err" || { echo "ERROR: the dump failed: $(tail -1 "$F.err" | cut -c1-200)" >&2; false; }
  bytes=$(wc -c <"$F" | tr -d ' ')
  [ "$bytes" -gt 0 ] || { echo "ERROR: the dump is empty" >&2; false; }
  [ "$(head -c 5 "$F")" = PGDMP ] || { echo "ERROR: the dump does not start as a custom-format archive" >&2; false; }
  # Proven on the pod's own pg_restore: the same major version, nothing new holds the content, nothing is written there. --list alone misses a lost tail (measured:
  # a file 100 bytes short lists with rc 0), so the whole archive is read too, to /dev/null.
  entries=$(in_pod_stdin 'pg_restore --list | grep -c "TABLE DATA"' <"$F") || { echo "ERROR: pg_restore --list refused the archive" >&2; false; }
  [ "$entries" -gt 0 ] || { echo "ERROR: no table data in the archive" >&2; false; }
  in_pod_stdin 'pg_restore -f /dev/null' <"$F" 2>>"$F.err" || { echo "ERROR: the archive does not read to its end: $(tail -1 "$F.err" | cut -c1-200)" >&2; false; }
  live=$(in_pod 'psql -w -U "$U" -d "$D" -Atc "select count(*) from realm"')
  dumped=$(in_pod_stdin 'pg_restore -a -t realm -f - | awk "/^COPY /{c=1;next} /^\\\\\\./{c=0} c{n++} END{print n+0}"' <"$F") || dumped=0
  [ "$live" = "$dumped" ] || { echo "ERROR: $live realms in the database, $dumped in the dump" >&2; false; }
  rm -f "$F.err"
  trap - ERR INT TERM HUP
  echo "backup in $(basename "$DIR"): $bytes bytes in $(( $(date +%s) - t0 )) s, $entries tables with data, $dumped realms, read to its end"
}
case "${1:-}" in
  --inspect) inspect ;;
  --delete) [ ! -L "$DIR" ] || { echo "ERROR: the backup directory is a symbolic link" >&2; exit 1; }
            n=$(find "$DIR" -type f -name 'keycloak-*' 2>/dev/null | wc -l | tr -d ' ')
            find "$DIR" -type f -name 'keycloak-*' -delete 2>/dev/null || true; rmdir "$DIR" 2>/dev/null || true; echo "deleted $n file(s) from $(basename "$DIR")" ;;
  "") backup ;;
  *) sed -n '3,6p' "$0" >&2; exit 2 ;;
esac
