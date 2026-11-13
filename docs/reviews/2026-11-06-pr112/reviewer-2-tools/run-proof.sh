#!/usr/bin/env bash
# The proofs named in the brief, on $1, a fresh copy with the patches applied. Each result in output/logs/proof-<name>.txt; a failure does not stop the next.
R=/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/aa3f1eb5-68be-4391-a918-9de29dd6cd7d/scratchpad/rbac-review-opus
T=$1; shift; OUT=$R/output/logs; export TMPDIR=$R/work/tmp KUBECONFIG=$R/work/empty.kubeconfig PYTHONDONTWRITEBYTECODE=1; : > "$KUBECONFIG"
export PATH=$R/../w1venv/bin:$PATH
cd "$T" || exit 1
one() { local name=$1; shift; local t0=$SECONDS rc; { echo "\$ $*"; "$@"; rc=$?; echo "rc=$rc"; } >"$OUT/proof-$name.txt" 2>&1; rc=$(sed -n 's/^rc=//p' "$OUT/proof-$name.txt" | tail -1); echo "$name rc=$rc $((SECONDS-t0)) s" | tee -a "$OUT/proof-SUMMARY.txt"; }
for what in "$@"; do case "$what" in
  shellcheck) SC=$(python -c 'import yaml; print(next(s["run"] for s in yaml.safe_load(open(".github/workflows/ci.yml"))["jobs"]["manifests"]["steps"] if s.get("name")=="Shellcheck"))'); one shellcheck bash -c "$SC";;
  ci-guard) one ci-guard python deploy/tests/ci-guard.py .github/workflows/ci.yml;;
  doc12) one doc12-test python deploy/tests/doc12-test.py docs/12-existing-postgresql.md;;
  doc13) one doc13-test python deploy/tests/doc13-test.py docs/13-crc-deployment.md;;
  render) one render-test deploy/render-test.sh;;
  mutsec) one mutate-secrets python deploy/tests/mutate-secrets.py;;
  guard) one crc-guard-test-no-mutants python deploy/tests/crc-guard-test.py --no-mutants;;
  scripts) one crc-scripts-test deploy/tests/crc-scripts-test.sh;;
  examples) ( cd examples; PYTHONPATH=src one examples "$R/work/venv-ref/bin/python" -m pytest tests -q -p no:cacheprovider );;
  service) ( cd cmapi; PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55492/cmapi one service python -m pytest tests/service -q -W ignore -p no:cacheprovider );;
  realm) CONTAINER=podman one realm-test python deploy/tests/realm-test.py deploy/manifests/environments/crc/realm/10-realm-import.yaml;;
  ldap) CONTAINER=podman one ldap-identities-test deploy/tests/ldap-identities-test.sh;;
esac; done
