#!/usr/bin/env bash
# deploy/tests/kind-test-stubbed.sh [<deploy dir>]: deploy/kind-test.sh with kind, kubectl, podman, curl and sleep stubbed, on each
# thing the script claims it can fail on. No cluster; downloads the CNPG manifest once, because the script checks its SHA-256
# (KT_CNPG names a copy instead). Each line: the verdict, then what the script did. Exit 0 only when every case is as it must be.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); SRC=$(cd "${1:-$HERE/..}" && pwd); fails=0
# Odd on purpose: pgrep and pkill below match this and nothing else on the machine.
KT_PF_SLEEP=25.4242; KT_REAL_SLEEP=$(command -v sleep); export KT_PF_SLEEP KT_REAL_SLEEP
W=$(mktemp -d); trap 'pkill -f "sleep $KT_PF_SLEEP" 2>/dev/null; rm -rf "$W"' EXIT
mkdir -p "$W/repo/deploy"; cp "$SRC/kind-test.sh" "$SRC/render.sh" "$W/repo/deploy/"; cp -R "$SRC/manifests" "$W/repo/deploy/"
cat >"$W/repo/deploy/secrets.sh" <<'STUB'
#!/bin/sh
echo "secrets.sh $*"
STUB
cat >"$W/repo/deploy/secrets-test.sh" <<'STUB'
#!/bin/sh
exit "${KT_SECRETS_RC:-0}"
STUB
chmod +x "$W/repo/deploy/"*.sh
if [ -z "${KT_CNPG:-}" ]; then
  KT_CNPG=$W/cnpg-1.30.1.yaml
  curl -fsSL "$(sed -n 's/^CNPG_URL=//p' "$SRC/kind-test.sh")" -o "$KT_CNPG" || { echo "ERROR: could not download the CNPG manifest" >&2; exit 1; }
fi
export KT_CNPG
one() { # label, must-exit (0|nonzero), then VAR=VALUE...
  local label=$1 want=$2; shift 2; local log="$W/log.$RANDOM"; : >"$log"
  env PATH="$HERE/kind-test-stubs:$PATH" KT_LOG="$log" KIND_TEST_KUBECONFIG="$W/kc" "$@" "$W/repo/deploy/kind-test.sh" localhost/cmapi:dev >"$W/out" 2>&1; local rc=$?
  local deleted=no; grep -q POLICY-DELETED "$log" && deleted=yes
  local reapplied=no; grep -q POLICY-REAPPLIED "$log" && reapplied=yes
  local killed=no; grep -q 'kind delete cluster' "$log" && killed=yes
  case "$want:$rc" in 0:0|nonzero:[1-9]*) v=ok;; *) v=WRONG; fails=$((fails+1));; esac
  printf '%-5s rc=%-3s policy-deleted=%-3s cluster-deleted=%-3s %s\n' "$v" "$rc" "$deleted" "$killed" "$label"
  LAST_DELETED=$deleted; LAST_REAPPLIED=$reapplied; LAST_KILLED=$killed; LAST_OUT=$(cat "$W/out")
}
want_field() { [ "$2" = "$3" ] || { echo "WRONG $1: expected $2, got $3"; fails=$((fails+1)); }; }
one "all good"                                         0
want_field "a cluster this run created is deleted" yes "$LAST_KILLED"; want_field "the changed render applies the policy" yes "$LAST_REAPPLIED"
one "/readyz is 503"                                   nonzero KT_READY=503
one "/readyz refuses the connection"                   nonzero KT_READY_RC=7
one "the port-forward died"                            nonzero KT_PF_DIE=true
one "the mockup is 404"                                nonzero KT_MOCK=404
one "the secrets cases fail"                           nonzero KT_SECRETS_RC=1
one "api never rolls out"                              nonzero KT_API_NEVER=true
one "DNS proven: migrate cannot resolve, mockup can"   0       KT_API_SLOW=true 'KT_PROBE=socket.gaierror: [Errno -2] Name or service not known'
want_field "the policy goes on the proven pair" yes "$LAST_DELETED"; case "$LAST_OUT" in *"NetworkPolicy deleted for DNS: true"*) ;; *) echo "WRONG: the deletion is not reported"; fails=$((fails+1));; esac
want_field "the changed render does not bring the deleted policy back" no "$LAST_REAPPLIED"
one "DNS not proven: the mockup cannot resolve either" nonzero KT_API_SLOW=true KT_API_NEVER=true 'KT_PROBE=Name or service not known' KT_MOCK_RC=2
want_field "the policy stays" no "$LAST_DELETED"
one "slow, no DNS failure"                             0       KT_API_SLOW=true
want_field "the policy stays" no "$LAST_DELETED"
one "/api/v1/version answers an error, not the commit" nonzero 'KT_VERSION={"detail":"boom"}'
one "/api/v1/version is empty"                         nonzero KT_VERSION=
one "/api/v1/version names another commit than built"  nonzero 'KT_VERSION={"commit":"0000000000"}'
one "the image's revision label is unknown"            nonzero KT_LABEL=unknown
one "the image has no revision label"                  nonzero KT_LABEL=
one "the worker has crash-looped since its rollout"    nonzero KT_WORKER_RESTARTS=4
one "a cluster named cmapi-test already exists"        nonzero KT_CLUSTER_EXISTS=true
want_field "somebody else's cluster is not deleted" no "$LAST_KILLED"
one "probe resolves now, old previous log says failed" 0       KT_API_SLOW=true 'KT_PREVIOUS=failed to resolve host cmapi-db-rw.wrong'
want_field "the policy stays: the container resolves the Service now" no "$LAST_DELETED"
one "the migrate env reaches the database in plaintext" nonzero 'KT_SSL=pg_stat_ssl False None'
one "the pg_stat_ssl check never finishes"             nonzero KT_SSL_WAIT_RC=1
one "a changed cmapi-env leaves the old pods"          nonzero KT_NOT_REPLACED_RC=1
one "the new pods still read the old value"            nonzero KT_LEVEL=INFO
"$KT_REAL_SLEEP" 0.5
pf_left=$(pgrep -f "sleep $KT_PF_SLEEP" | wc -l | tr -d ' ')
echo "port-forward processes left behind by the runs above: $pf_left"; [ "$pf_left" = 0 ] || { echo "WRONG: the kill misses the port-forward"; fails=$((fails+1)); }
echo "wrong: $fails"; [ "$fails" = 0 ]
