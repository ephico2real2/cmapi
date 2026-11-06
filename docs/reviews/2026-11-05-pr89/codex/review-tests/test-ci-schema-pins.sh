#!/usr/bin/env bash
set -euo pipefail
f=${1:?tree}/.github/workflows/ci.yml
job=$(sed -n '/^  manifests:/,/^  [a-z].*:/p' "$f")
printf '%s' "$job" | grep -q 'runs-on: ubuntu-24.04' || { echo 'FAIL manifests runner floats on ubuntu-latest'; exit 1; }
if grep -Eq 'kubernetes-json-schema/master|CRDs-catalog/main' "$f"; then
  echo 'FAIL kubeconform schema URLs float on a branch'
  exit 1
fi
grep -q 'kubernetes-json-schema/102361970337d65537d40141dc29b991b8e95786/' "$f"
grep -q 'CRDs-catalog/c86448cbf1a840ca62d119259864863897c8748a/' "$f"
echo 'PASS the manifests runner and kubeconform schema URLs are pinned'
