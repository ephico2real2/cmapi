#!/usr/bin/env bash
# deploy/kind-test.sh with kind, kubectl, podman and curl stubbed, on each thing the script claims it can fail on.
# usage: run.sh <deploy dir>. Each line: expected verdict vs what the script did. Exit 0 only when every case is as it must be.
set -uo pipefail
SRC=$(cd "$1" && pwd); HERE=$(cd "$(dirname "$0")" && pwd); fails=0
W=$(mktemp -d); trap 'pkill -f "sleep 25" 2>/dev/null; rm -rf "$W"' EXIT
mkdir -p "$W/repo/deploy"; cp "$SRC/kind-test.sh" "$W/repo/deploy/"; cp "$HERE/../../head/deploy/render.sh" "$W/repo/deploy/"; cp -R "$HERE/../../head/deploy/manifests" "$W/repo/deploy/"
printf '#!/bin/sh\necho "secrets.sh $*"\n' >"$W/repo/deploy/secrets.sh"; printf '#!/bin/sh\nexit ${KT_SECRETS_RC:-0}\n' >"$W/repo/deploy/secrets-test.sh"; chmod +x "$W/repo/deploy/"*.sh
export KT_CNPG="$HERE/../../work/dl/cnpg-1.30.1.yaml"
one() { # label, must-exit (0|nonzero), then VAR=VALUE...
  local label=$1 want=$2; shift 2; local log="$W/log.$RANDOM"; : >"$log"
  env PATH="$HERE/bin:$PATH" KT_LOG="$log" KIND_TEST_KUBECONFIG="$W/kc" "$@" "$W/repo/deploy/kind-test.sh" localhost/cmapi:dev >"$W/out" 2>&1; local rc=$?
  local deleted=no; grep -q POLICY-DELETED "$log" && deleted=yes
  local killed=no; grep -q 'kind delete cluster' "$log" && killed=yes
  case "$want:$rc" in 0:0|nonzero:[1-9]*) v=ok;; *) v=WRONG; fails=$((fails+1));; esac
  printf '%-5s rc=%-3s policy-deleted=%-3s cluster-deleted=%-3s %s\n' "$v" "$rc" "$deleted" "$killed" "$label"
  LAST_DELETED=$deleted; LAST_KILLED=$killed; LAST_OUT=$(cat "$W/out")
}
want_field() { [ "$2" = "$3" ] || { echo "WRONG $1: expected $2, got $3"; fails=$((fails+1)); }; }
one "all good"                                         0
one "/readyz is 503"                                   nonzero KT_READY=503
one "the mockup is 404"                                nonzero KT_MOCK=404
one "the secrets cases fail"                           nonzero KT_SECRETS_RC=1
one "api never rolls out"                              nonzero KT_API_NEVER=true
one "DNS proven: migrate cannot resolve, mockup can"   0       KT_API_SLOW=true 'KT_PROBE=socket.gaierror: [Errno -2] Name or service not known'
want_field "the policy goes on the proven pair" yes "$LAST_DELETED"; case "$LAST_OUT" in *"NetworkPolicy deleted for DNS: true"*) ;; *) echo "WRONG: the deletion is not reported"; fails=$((fails+1));; esac
one "DNS not proven: the mockup cannot resolve either" nonzero KT_API_SLOW=true KT_API_NEVER=true 'KT_PROBE=Name or service not known' KT_MOCK_RC=2
want_field "the policy stays" no "$LAST_DELETED"
one "slow, no DNS failure"                             0       KT_API_SLOW=true
want_field "the policy stays" no "$LAST_DELETED"
one "/api/v1/version answers an error, not the commit" nonzero 'KT_VERSION={"detail":"boom"}'
one "/api/v1/version is empty"                         nonzero KT_VERSION=
one "/api/v1/version names another commit than built"  nonzero 'KT_VERSION={"commit":"0000000000"}'
one "the worker has crash-looped since its rollout"    nonzero KT_WORKER_RESTARTS=4
one "a cluster named cmapi-test already exists"        nonzero KT_CLUSTER_EXISTS=true
want_field "somebody else's cluster is not deleted" no "$LAST_KILLED"
one "probe resolves now, old previous log says failed" 0       KT_API_SLOW=true 'KT_PREVIOUS=failed to resolve host cmapi-db-rw.wrong'
want_field "the policy stays: the container resolves the Service now" no "$LAST_DELETED"
pf_left=$(pgrep -f "sleep 25" | wc -l | tr -d ' ')
echo "port-forward processes left behind by the runs above: $pf_left"; [ "$pf_left" = 0 ] || { echo "WRONG: the kill misses the port-forward"; fails=$((fails+1)); }
echo "wrong: $fails"; [ "$fails" = 0 ]
