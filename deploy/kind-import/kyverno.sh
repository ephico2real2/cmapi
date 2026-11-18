#!/usr/bin/env bash
# deploy/kind-import/kyverno.sh <cmapi-cluster-configs checkout>: Kyverno and cmapi's rnd bundle on the kind cluster cmapi-test, so
# KIND_CMAPI_TEST (environment rnd) runs its bundle (#430; docs/13, "A second cluster: kind"). up.sh runs it after the reader; run it
# alone after a pull request that changes policies/env/rnd merges. In order:
#   1. stop unless the checkout's policies/env/rnd is clean at a commit and holds the three files, and the kubeconfig is kind's
#   2. install or upgrade Kyverno, chart 3.10.0 (v1.20.0, cmapi's CLI pin) with deploy/kyverno/kind-values.yaml, and wait for it
#   3. a server dry run of the three files; only when it passes, the apply, field manager cmapi-policies
#   4. wait until each policy of the files is ready
# The bundle is read from the checkout, not fetched: the operator chooses the commit. The chart is fetched from Kyverno's repository.
# Every call goes to kind; nothing touches CRC. Applies prune nothing (docs/13). Exits non-zero on the first failure.
set -euo pipefail
# shellcheck source=SCRIPTDIR/common.sh
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
{ [ $# = 1 ] && [[ $1 != -* ]]; } || { echo "usage: $0 <cmapi-cluster-configs checkout>" >&2; exit 2; }

check_config
check_bundle "$1"
check_kind_target
say "bundle: policies/env/$ENVIRONMENT of $1 at commit $BUNDLE_COMMIT"

hm upgrade --install kyverno kyverno --repo "$KYVERNO_REPO" --version "$KYVERNO_CHART_VERSION" -n kyverno --create-namespace \
  -f "$KYVERNO_VALUES" --wait --timeout 8m >/dev/null ||
  die "the Kyverno install failed, and no policy was applied. Read: helm status kyverno -n kyverno --kubeconfig $KC"
kc wait --for=condition=Established --timeout=60s crd/validatingpolicies.policies.kyverno.io >/dev/null ||
  die "Kyverno's ValidatingPolicy type is not served on $NAME"
say "Kyverno $KYVERNO_CHART_VERSION is ready on $NAME"

files=(); for f in "${BUNDLE_FILES[@]}"; do files+=(-f "$BUNDLE_DIR/$f"); done
# The dry run goes through Kyverno's own webhook, which fails closed on a policy it refuses: the apply waits on its exit status.
kc apply --server-side --field-manager="$POLICY_FIELD_MANAGER" --dry-run=server "${files[@]}" >/dev/null ||
  die "the server dry run refused the bundle, and nothing was applied"
kc apply --server-side --field-manager="$POLICY_FIELD_MANAGER" "${files[@]}" >/dev/null
kc wait --for=jsonpath='{.status.conditionStatus.ready}'=true --timeout=120s "${files[@]}" >/dev/null ||
  die "a policy of the bundle is not ready: kubectl --kubeconfig=$KC get validatingpolicies.policies.kyverno.io"
say "$(kc get "${files[@]}" -o name | wc -l | tr -d ' ') policies of $ENVIRONMENT applied and ready on $NAME, at commit $BUNDLE_COMMIT"
