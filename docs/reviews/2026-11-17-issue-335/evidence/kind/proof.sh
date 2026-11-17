#!/bin/bash
# #335 on the cmapi-test kind cluster: the chart installed with a custom required label set through the value metadata,
# Kyverno off (instance.policy.engine none); a create without the label must get 422 validation-failed.
# Every kubectl and helm call carries the explicit kubeconfig of this cluster. Prints what it measured.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
WT=/Users/olasumbo/gitRepos/workbench/cmapi/wt-helm-335-metadata-values
KC=/Users/olasumbo/gitRepos/workbench/cmapi/ob-335/kind.kubeconfig
PY=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python
IMAGE=localhost/cmapi:sha-9ba33b2064          # main 9ba33b2: #335 changes the chart only, not the image
ISS=https://issuer.cmapi-test.invalid/realms/cmapi
k() { kubectl --kubeconfig="$KC" "$@"; }
say() { echo "[$(date -u +%H:%M:%SZ)] $*"; }
export KIND_EXPERIMENTAL_PROVIDER=podman
[ "$(k config current-context)" = kind-cmapi-test ] || { echo "not the cmapi-test context" >&2; exit 1; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

for img in "$IMAGE" docker.io/library/postgres:16-alpine; do
  if podman exec cmapi-test-control-plane crictl inspecti "$img" >/dev/null 2>&1; then say "$img already in the node"; continue; fi
  say "load $img"; podman save -o "$T/i.tar" "$img" >/dev/null; kind load image-archive "$T/i.tar" --name cmapi-test >/dev/null; rm -f "$T/i.tar"
done
# The chart deploys by digest. kind load imports the archive under its tag only, so a digest reference finds nothing
# (measured: ErrImageNeverPull for the repoDigest crictl shows). Name the imported manifest by its own digest.
DIGEST=$(podman exec cmapi-test-control-plane ctr -n k8s.io images ls | awk -v ref="$IMAGE" '$1==ref {print $3}')
podman exec cmapi-test-control-plane ctr -n k8s.io images tag --force "$IMAGE" "localhost/cmapi@$DIGEST" >/dev/null
say "image $IMAGE in the node as localhost/cmapi@$DIGEST"

k create namespace cmapi --dry-run=client -o yaml | k apply -f - >/dev/null
# Throwaway credentials, made here and never printed: a file each, read by kubectl, removed by the trap.
# Made once: PostgreSQL takes its password when it first initialises, so a rerun keeps the Secret it has.
if ! k -n cmapi get secret pg-password >/dev/null 2>&1; then
  "$PY" -c 'import secrets; print(secrets.token_urlsafe(24), end="")' > "$T/pw"
  printf 'postgresql://cmapi:%s@pg.cmapi.svc.cluster.local:5432/cmapi?sslmode=disable' "$(cat "$T/pw")" > "$T/uri"
  k -n cmapi create secret generic pg-password --from-file=password="$T/pw" >/dev/null
  k -n cmapi create secret generic cmapi-db --from-file=uri="$T/uri" >/dev/null
fi
# One throwaway signing key for the life of this cluster (outside any repository, mode 600): the API caches the JWKS
# it read first, so a new key under the same kid would be refused as an invalid token (measured, run 4).
KEYS=$HERE/keys; [ -f "$KEYS/key.pem" ] || "$PY" "$HERE/mint.py" keys "$KEYS"
jwks_change=$(k -n cmapi create configmap jwks --from-file=certs="$KEYS/certs" --dry-run=client -o yaml | k apply -f -)
sed "s|image: IMAGE|image: $IMAGE|" "$HERE/support.yaml" | k apply -f - >/dev/null
k -n cmapi rollout status deploy/pg --timeout=180s >/dev/null && k -n cmapi rollout status deploy/jwks --timeout=180s >/dev/null
case $jwks_change in *configured*) k -n cmapi rollout restart deploy/jwks >/dev/null; k -n cmapi rollout status deploy/jwks --timeout=180s >/dev/null
  k -n cmapi get deploy/cmapi-api >/dev/null 2>&1 && k -n cmapi rollout restart deploy/cmapi-api >/dev/null;; esac
say "stand-ins ready: PostgreSQL 16, JWKS"

# The Git host: the repository's own Gitea stand-in chart (deploy/helm/cmapi-git), pulled by its pinned digest, and the
# bot. The planner reads the branch head before it validates, so without a Git host a create stops at
# 502 git-unavailable (measured, run 6). The cmapi chart's git-bootstrap Job makes the bot, the org and the repository.
helm --kubeconfig "$KC" upgrade --install cmapi-git "$WT/deploy/helm/cmapi-git" -n cmapi --set exposure=none \
  --set securityContext.runAsUser=1000 --set securityContext.fsGroup=1000 --wait --timeout 15m >/dev/null
# With git.bootstrap.enabled the cmapi chart writes the bot's Secret, cmapi-git-bot, itself (templates/secrets.yaml).
say "Gitea ready: $(k -n cmapi get deploy cmapi-git-gitea -o jsonpath='{.status.readyReplicas}') replica, image $(k -n cmapi get deploy cmapi-git-gitea -o jsonpath='{.spec.template.spec.containers[0].image}')"

say "helm lint and helm upgrade --install with the metadata value"
helm lint "$WT/deploy/helm/cmapi" -f "$HERE/values-kind-335.yaml" --set cmapi.repository=localhost/cmapi --set cmapi.digest="$DIGEST" --set cmapi_portal.digest="$DIGEST"
helm --kubeconfig "$KC" upgrade --install cmapi "$WT/deploy/helm/cmapi" -n cmapi -f "$HERE/values-kind-335.yaml" \
  --set cmapi.repository=localhost/cmapi --set cmapi.digest="$DIGEST" --set cmapi_portal.digest="$DIGEST" \
  --set git.bootstrap.enabled=true --wait --wait-for-jobs --timeout 10m
# The cluster CRC of the chart's clusters.yaml, imported as this kind cluster itself: the reader baseline of the plain
# manifests and the import Secret that deploy/crc-reader-import.sh writes (the token passes through a pipe). Without it
# a create stops earlier, at 503 cluster-unreachable (measured, run 5).
k apply -f "$WT/deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml" >/dev/null
if ! k -n cmapi-imports get secret cmapi-cluster-crc >/dev/null 2>&1; then
  CMAPI_OC="kubectl --kubeconfig=$KC" "$WT/deploy/crc-reader-import.sh"
fi
# The pods read the bot's Secret and the import Secret at start; both may be newer than the pods.
k -n cmapi rollout restart deploy/cmapi-api deploy/cmapi-worker >/dev/null
k -n cmapi rollout status deploy/cmapi-api --timeout=300s >/dev/null
k -n cmapi get deploy,pods -o wide
say "the rendered file in the ConfigMap: required labels"
k -n cmapi get configmap cmapi-config -o jsonpath='{.data.metadata-keys\.yaml}' | "$PY" -c 'import sys,yaml; d=yaml.safe_load(sys.stdin); print(sorted(d["requiredLabels"]))'
say "instance.yaml policy: $(k -n cmapi get configmap cmapi-config -o jsonpath='{.data.instance\.yaml}' | grep 'policy:')"

k -n cmapi port-forward deploy/cmapi-api 18335:8080 >"$T/pf.log" 2>&1 & PF=$!
trap 'kill $PF 2>/dev/null || true; rm -rf "$T"' EXIT
for i in $(seq 1 30); do curl -fsS -o /dev/null http://127.0.0.1:18335/api/v1/version && break; sleep 1; done
say "GET /api/v1/version: $(curl -sS http://127.0.0.1:18335/api/v1/version)"
for i in $(seq 1 60); do curl -fsS http://127.0.0.1:18335/readyz >/dev/null 2>&1 && break; sleep 2; done
say "GET /readyz: $(curl -sS http://127.0.0.1:18335/readyz)"
# The token goes to curl in a header file, not on its command line.
printf 'Authorization: Bearer %s\n' "$("$PY" "$HERE/mint.py" token "$KEYS" "$ISS" cmapi-nonprod ola)" > "$T/auth"
body() { printf '{"namespace": "%s", "tier": "small", "labels": %s, "annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"}, "justification": "#335 kind proof"}' "$1" "$2"; }
post() {
  curl -sS -o "$T/out.json" -w '%{http_code}' -X POST "http://127.0.0.1:18335/api/v1/clusters/CRC/namespaces$2" \
    -H @"$T/auth" -H "Idempotency-Key: $("$PY" -c 'import uuid; print(uuid.uuid4())')" \
    -H 'Content-Type: application/json' -d "$1"
}
say "POST /api/v1/clusters/CRC/namespaces without acme.example/owner"
code=$(post "$(body payments-dev '{"cmapi.net/team": "payments"}')" ""); echo "HTTP $code"; "$PY" -m json.tool "$T/out.json"
say "POST /api/v1/clusters/CRC/namespaces?dryRun=true with acme.example/owner (the control: the same body passes validation; a dry run writes nothing)"
code2=$(post "$(body payments-dev '{"cmapi.net/team": "payments", "acme.example/owner": "payments"}')" "?dryRun=true"); echo "HTTP $code2"; "$PY" -m json.tool "$T/out.json" | head -40
