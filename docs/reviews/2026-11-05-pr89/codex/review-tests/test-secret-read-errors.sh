#!/usr/bin/env bash
set -u
TREE=${1:?tree}
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
printf '0\n' > "$T/applies"
printf '%s\n' dummy > "$T/key.pem"
chmod 600 "$T/key.pem"
cp "$(dirname "$0")/fake-secret-read-error-kubectl.sh" "$T/kubectl"
chmod +x "$T/kubectl"
set +e
FAKE_STATE=$T "$TREE/deploy/secrets.sh" --namespace app --realm-namespace realm --kubectl "$T/kubectl" --no-ldap-bind --github-app-key "$T/key.pem" --github-app-id 1 --github-installation-id 2 >"$T/out" 2>&1
rc=$?
set -e
applies=$(cat "$T/applies")
if [ "$rc" -eq 0 ] || [ "$applies" -ne 0 ]; then
  echo "FAIL a failed Secret read was treated as absence: rc=$rc applies=$applies"
  exit 1
fi
echo "PASS Secret read error stopped without writes: rc=$rc applies=$applies"
