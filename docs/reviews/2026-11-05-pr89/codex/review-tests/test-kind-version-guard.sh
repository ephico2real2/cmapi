#!/usr/bin/env bash
set -euo pipefail
f=${1:?tree}/deploy/kind-test.sh
grep -q 'org.opencontainers.image.revision' "$f" || { echo 'FAIL expected commit is not read from the tested image'; exit 1; }
if grep -q '/version commit does not start.*|| echo "note' "$f"; then
  echo 'FAIL a /version mismatch is only a note'
  exit 1
fi
grep -q 'VERSION_COMMIT.*EXPECTED_COMMIT' "$f" || { echo 'FAIL no fatal exact comparison of version and image stamp'; exit 1; }
echo 'PASS /version is compared fatally with the tested image stamp'
