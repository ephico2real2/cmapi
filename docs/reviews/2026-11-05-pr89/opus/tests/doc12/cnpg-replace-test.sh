#!/usr/bin/env bash
# The procedure the fix to docs/12 section 5 proposes: delete CNPG's Secret, create ours, and see whether the operator leaves it
# alone across a reconcile and an operator restart, and whether it survives the Cluster's deletion. Prints hosts only.
set -uo pipefail
KC=$1; HEAD=$2
k() { kubectl --kubeconfig="$KC" "$@"; }
[ "$(k config current-context)" = kind-cmapi-pr89-a ] || { echo "wrong context"; exit 9; }
host_of() { k -n cmapi get secret cmapi-db-app -o json | python3 -c 'import base64,json,sys,urllib.parse as u; d=json.load(sys.stdin); x=u.urlsplit(base64.b64decode(d["data"]["uri"]).decode()); print(x.hostname, "type="+d["type"], "owners="+str(len(d["metadata"].get("ownerReferences",[]))))'; }
k apply --server-side -f "$HEAD/deploy/manifests/components/database-cnpg/cluster.yaml" >/dev/null
k -n cmapi wait cluster/cmapi-db --for=jsonpath='{.status.phase}'='Cluster in healthy state' --timeout=280s
echo "CNPG's: $(host_of)"
PW='throwaway-not-a-real-password'
k -n cmapi delete secret cmapi-db-app
printf 'uri postgresql://cmapi:%s@db.example.internal:5432/cmapi?sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt\n' "$PW" \
  | { printf 'apiVersion: v1\nkind: Secret\ntype: Opaque\nmetadata: {name: cmapi-db-app, namespace: cmapi}\nstringData:\n'; while read -r a b; do printf '  %s: %s\n' "$a" "$b"; done; } \
  | k apply --server-side -f - ; echo "apply rc=$?"
echo "immediately: $(host_of)"
k -n cmapi annotate cluster cmapi-db pr89a/touch="$(date +%s)" --overwrite >/dev/null
perl -e 'select(undef,undef,undef,30)'; echo "30 s after a touch: $(host_of)"
k -n cnpg-system rollout restart deploy/cnpg-controller-manager >/dev/null; k -n cnpg-system rollout status deploy/cnpg-controller-manager --timeout=120s >/dev/null
perl -e 'select(undef,undef,undef,45)'; echo "45 s after an operator restart: $(host_of)"
k -n cmapi delete cluster cmapi-db --wait=true --timeout=120s
perl -e 'select(undef,undef,undef,15)'; echo "after the Cluster is deleted: $(host_of 2>&1)"
