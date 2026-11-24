#!/usr/bin/env bash
# The #640 proof on a disposable Keycloak 26.6.4 in podman (never the shared one on CRC).
# Usage: proof.sh LABEL=SRC [LABEL=SRC ...]   each SRC is a cmapi src directory to drive (before and after the fix).
# Every credential is generated here, lives only in this shell's environment, and is removed from all printed text.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python3}                     # a Python with cmapi's requirements (httpx among them)
IMG=quay.io/keycloak/keycloak@sha256:0aae0de7fca85525f727d3354df17896092de8bb26ae4c12d89c77e5df8cbce4
NAME=kc640-$(openssl rand -hex 4)
REALMS='["cmapi", "cmapi 640", "pct%41é"]'

KC_BOOTSTRAP_ADMIN_PASSWORD=$(openssl rand -hex 24); CMAPI_DIR_SECRET=$(openssl rand -hex 24); CMAPI_RA_SECRET=$(openssl rand -hex 24)
export KC_BOOTSTRAP_ADMIN_PASSWORD CMAPI_DIR_SECRET CMAPI_RA_SECRET
redact() { sed -e "s/$KC_BOOTSTRAP_ADMIN_PASSWORD/[redacted]/g" -e "s/$CMAPI_DIR_SECRET/[redacted]/g" -e "s/$CMAPI_RA_SECRET/[redacted]/g"; }
cleanup() { podman rm -f -v "$NAME" >/dev/null 2>&1 || true; echo "== container $NAME removed, with its volumes"; }
trap cleanup EXIT

echo "== $(date -u +%FT%TZ) image $IMG"
podman run -d --name "$NAME" -p 127.0.0.1::8080 -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD \
  "$IMG" start-dev --http-access-log-enabled=true >/dev/null
PORT=$(podman port "$NAME" 8080 | head -1 | sed 's/.*://')
KC=http://127.0.0.1:$PORT
echo "== container $NAME on $KC"
for _ in $(seq 1 90); do
  [[ $(curl -s -o /dev/null -w '%{http_code}' "$KC/realms/master" || true) == 200 ]] && break
  sleep 2
done
podman exec "$NAME" /opt/keycloak/bin/kc.sh --version 2>/dev/null | grep -i '^keycloak' || true

echo "== realms, and the issuer each one's .well-known/openid-configuration serves"
MARK=$(date -u +%s)
ISSUERS=$("$PY" "$HERE/setup_kc.py" "$KC" "$REALMS")
echo "$ISSUERS"

for pair in "$@"; do
  label=${pair%%=*}; src=${pair#*=}
  echo; echo "######## $label: $src"
  echo "-- core/context.py, the realm from the issuer:"; grep -n 'realms/\|split_issuer(issuer)' "$src/cmapi/core/context.py" | sed 's/^/   /'
  while IFS= read -r line; do
    issuer=$("$PY" -c 'import json,sys; print(json.loads(sys.argv[1])["issuer"])' "$line")
    echo "== $label  KeycloakAdminDirectory  issuer $issuer"
    PYTHONPATH="$src" "$PY" "$HERE/drive_directory.py" "$issuer" 2>&1 | redact
    echo "== $label  realm_sync.main  issuer $issuer"
    PYTHONPATH="$src" CMAPI_REALM_ISSUER="$issuer" CMAPI_REALM_ADMIN_CLIENT_SECRET="$CMAPI_RA_SECRET" \
      CMAPI_REALM_AUDIENCE=cmapi-nonprod CMAPI_REALM_GROUPS='{}' CMAPI_REALM_LDAP='{}' \
      "$PY" -c 'import sys; from cmapi.tools.realm_sync import main; main(sys.argv)' 2>&1 | redact | sed 's/^/  /' || echo "  realm_sync exited non-zero: $?"
  done <<<"$ISSUERS"
done

echo; echo "== Keycloak's access log: the request lines it received for the test realms (not master)"
podman logs --since "$MARK" "$NAME" 2>&1 | grep -E '"(GET|POST|PUT|DELETE) /(admin/)?realms/' | grep -v '/realms/master' \
  | sed -E 's/.*"((GET|POST|PUT|DELETE) [^"]*)" ([0-9]{3}).*/\3 \1/' | redact
