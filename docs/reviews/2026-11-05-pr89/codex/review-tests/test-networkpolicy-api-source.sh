#!/usr/bin/env bash
set -euo pipefail
f=${1:?tree}/deploy/manifests/components/cmapi/40-networkpolicy.yaml
grep -q 'network.openshift.io/policy-group: ingress' "$f" || { echo 'FAIL API ingress is not restricted to the OpenShift router'; exit 1; }
grep -q 'podSelector: {}' "$f" || { echo 'FAIL API ingress does not retain same-namespace access'; exit 1; }
echo 'PASS API ingress has the chart router/source guard'
