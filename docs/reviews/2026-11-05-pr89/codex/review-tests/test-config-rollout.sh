#!/usr/bin/env bash
set -euo pipefail
TREE=${1:?tree}
for f in "$TREE"/deploy/manifests/environments/kind/{10-env,20-config,30-trust}.yaml; do
  grep -Eq '^  name: .+-v[0-9]+$' "$f" || { echo "FAIL unversioned ConfigMap: $f"; exit 1; }
  grep -qx 'immutable: true' "$f" || { echo "FAIL mutable ConfigMap: $f"; exit 1; }
done
for f in "$TREE"/deploy/manifests/components/cmapi/{20-api,30-worker}.yaml; do
  grep -q 'name: cmapi-env-v1' "$f" || { echo "FAIL workload does not version cmapi-env: $f"; exit 1; }
  grep -q 'configMap: {name: cmapi-config-v1}' "$f" || { echo "FAIL workload does not version cmapi-config: $f"; exit 1; }
  grep -q 'name: cmapi-trust-v1' "$f" || { echo "FAIL workload does not version cmapi-trust: $f"; exit 1; }
done
echo 'PASS ConfigMaps are immutable and versioned in both workloads'
