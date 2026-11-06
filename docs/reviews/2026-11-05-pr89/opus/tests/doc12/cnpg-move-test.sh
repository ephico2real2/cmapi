#!/usr/bin/env bash
# docs/12 section 5 on the real CNPG 1.30.1 Cluster from components/database-cnpg/cluster.yaml, on kind cluster cmapi-pr89-a.
# Prints hosts and metadata only, never a password. usage: cnpg-move-test.sh <kubeconfig> <out dir>
set -uo pipefail
KC=$1; OUT=$2
k() { kubectl --kubeconfig="$KC" "$@"; }
[ "$(k config current-context)" = kind-cmapi-pr89-a ] || { echo "wrong context"; exit 9; }
host_of() { k -n cmapi get secret cmapi-db-app -o json | python3 -c 'import base64,json,sys,urllib.parse as u; d=json.load(sys.stdin); x=u.urlsplit(base64.b64decode(d["data"]["uri"]).decode()); print(x.hostname, x.port, x.path, x.query or "<no query>")'; }
k -n cmapi wait cluster/cmapi-db --for=jsonpath='{.status.phase}'='Cluster in healthy state' --timeout=280s
echo "--- what CNPG wrote"
k -n cmapi get secret cmapi-db-app -o json | python3 -c 'import json,sys; d=json.load(sys.stdin); print("keys",sorted(d["data"])); print("ownerReferences",[(o["kind"],o["name"],o.get("controller")) for o in d["metadata"].get("ownerReferences",[])]); print("labels",{k:v for k,v in d["metadata"].get("labels",{}).items() if "cnpg" in k})'
echo "uri -> $(host_of)"
echo "--- section 5, line 90 verbatim (oc -> kubectl)"
k -n cmapi exec cmapi-db-1 -c postgres -- pg_dump -Fc -U cmapi cmapi > "$OUT/cmapi.dump"; echo "rc=$? bytes=$(wc -c <"$OUT/cmapi.dump" | tr -d ' ')"
echo "--- the same, as the superuser the local socket maps to"
k -n cmapi exec cmapi-db-1 -c postgres -- pg_dump -Fc -U postgres cmapi > "$OUT/cmapi2.dump"; echo "rc=$? bytes=$(wc -c <"$OUT/cmapi2.dump" | tr -d ' ')"
echo "--- the same over TCP with the Secret's own URI, read inside the pod's shell from a file-less env"
echo "--- section 3's Secret applied over CNPG's, as section 5 says ('Then replace cmapi-db-app (section 3)')"
PW='throwaway-not-a-real-password'
printf 'uri postgresql://cmapi:%s@db.example.internal:5432/cmapi?sslmode=verify-full&sslrootcert=/etc/cmapi/ca/ca-bundle.crt\n' "$PW" \
  | { printf 'apiVersion: v1\nkind: Secret\ntype: Opaque\nmetadata: {name: cmapi-db-app, namespace: cmapi}\nstringData:\n'; while read -r a b; do printf '  %s: %s\n' "$a" "$b"; done; } \
  | k apply --server-side -f - ; echo "apply rc=$?"
echo "immediately: uri -> $(host_of)"
echo "--- force a reconcile, as any later Cluster change or operator restart does"
k -n cmapi annotate cluster cmapi-db pr89a/touch="$(date +%s)" --overwrite >/dev/null
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do s=$(host_of); echo "t=$((i*10))s uri -> $s"; case "$s" in cmapi-db-rw*) break;; esac; perl -e 'select(undef,undef,undef,10)'; done
echo "--- if it was not reverted, or re-applied now: delete the Cluster 'by hand when the move is proven'"
printf 'uri postgresql://cmapi:%s@db.example.internal:5432/cmapi?sslmode=verify-full\n' "$PW" \
  | { printf 'apiVersion: v1\nkind: Secret\ntype: Opaque\nmetadata: {name: cmapi-db-app, namespace: cmapi}\nstringData:\n'; while read -r a b; do printf '  %s: %s\n' "$a" "$b"; done; } \
  | k apply --server-side --force-conflicts -f - >/dev/null; echo "re-applied, uri -> $(host_of)"
k -n cmapi delete cluster cmapi-db --wait=true --timeout=120s
perl -e 'select(undef,undef,undef,15)'
k -n cmapi get secret cmapi-db-app -o name 2>&1
echo "pvcs: $(k -n cmapi get pvc --no-headers 2>/dev/null | wc -l | tr -d ' ')"
