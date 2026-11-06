#!/usr/bin/env bash
set -euo pipefail
f=${1:?tree}/docs/12-existing-postgresql.md
if grep -q 'PGSSLROOTCERT=/tmp/ca.crt' "$f"; then
  echo 'FAIL PGSSLROOTCERT names an unmounted file'
  exit 1
fi
if grep -q '"image":"ghcr.io/cloudnative-pg/postgresql:17"' "$f"; then
  echo 'FAIL --overrides replaces the pinned image with a floating tag'
  exit 1
fi
grep -q 'PGSSLROOTCERT=/etc/cmapi/ca/ca-bundle.crt' "$f"
echo 'PASS the connectivity probe uses the mounted CA and only the pinned image'
