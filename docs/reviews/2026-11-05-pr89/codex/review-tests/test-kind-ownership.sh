#!/usr/bin/env bash
set -euo pipefail
TREE=${1:?tree}
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
cp "$(dirname "$0")/fake-kind-existing.sh" "$T/kind"
chmod +x "$T/kind"
set +e
FAKE_KIND_STATE=$T PATH="$T:$PATH" "$TREE/deploy/kind-test.sh" >"$T/out" 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo 'FAIL test unexpectedly accepted an existing cluster'; exit 1; }
[ ! -e "$T/deleted" ] || { echo 'FAIL EXIT trap deleted a cluster this run did not create'; exit 1; }
echo 'PASS existing cluster was refused and not deleted'
