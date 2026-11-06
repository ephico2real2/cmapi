#!/usr/bin/env bash
set -u

TREE=${1:?tree containing deploy/secrets.sh}
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
printf '0\n' > "$T/applies"
cp "$(dirname "$0")/fake-empty-realm-kubectl.sh" "$T/kubectl"
chmod +x "$T/kubectl"

set +e
FAKE_STATE=$T "$TREE/deploy/secrets.sh" --namespace app --realm-namespace realm --kubectl "$T/kubectl" --no-ldap-bind >"$T/out" 2>&1
rc=$?
set -e
applies=$(cat "$T/applies")
if [ "$rc" -ne 1 ] || [ "$applies" -ne 0 ]; then
  echo "FAIL empty realm Secret must stop without writes: rc=$rc applies=$applies"
  exit 1
fi
echo "PASS empty realm Secret stopped: rc=$rc applies=$applies"
