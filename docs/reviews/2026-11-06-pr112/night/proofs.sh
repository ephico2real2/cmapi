#!/usr/bin/env bash
# PR #112's proofs, fix-defect step 4, one at a time. A failure does not stop the next. No cluster: KUBECONFIG is an empty file.
X=$(cd "$(dirname "$0")" && pwd); F=$X/final; L=$X/logs; V=$X/venv; R=$X/venv-ref
mkdir -p "$L" "$X/tmp"; : > "$X/empty.kubeconfig"; : > "$L/SUMMARY.txt"
export TMPDIR=$X/tmp KUBECONFIG=$X/empty.kubeconfig PYTHONDONTWRITEBYTECODE=1 CONTAINER=podman
DB=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi

one() { # one <name> <dir> <cmd...>
  local name=$1 dir=$2 t0=$SECONDS rc; shift 2
  ( cd "$dir" && "$@" ) >"$L/$name.txt" 2>&1; rc=$?
  echo "$name rc=$rc $((SECONDS-t0))s" | tee -a "$L/SUMMARY.txt"
}

{ /usr/local/bin/python3.12 -m venv "$V" && "$V/bin/pip" -q install -e "$F/cmapi[test]" pyyaml==6.0.2 httpx==0.28.1 \
  && /usr/local/bin/python3.12 -m venv "$R" && "$R/bin/pip" -q install -r "$F/examples/local/requirements.txt"; } >"$L/venvs.txt" 2>&1
echo "venvs rc=$?" | tee -a "$L/SUMMARY.txt"
export PATH=$V/bin:$PATH

# The patch 02 "before": the final test file on the code without patch 02.
cp -R "$F" "$X/before02"; for f in cmapi/src/cmapi/core/authz.py cmapi/src/cmapi/core/db/repo.py; do git -C "$F" show "HEAD:$f" > "$X/before02/$f"; done
# The LDAP "before": the final test file on be66382's two scripts. The "dash" tree: the final scripts under /bin/dash, as on Ubuntu.
cp -R "$F" "$X/beforeldap"; for f in apply-test-identities.sh apply-bind-user.sh; do git -C "$F" show "HEAD:examples/cmapi-sso/ldap/$f" > "$X/beforeldap/examples/cmapi-sso/ldap/$f"; done
cp -R "$F" "$X/dash"; for f in apply-test-identities.sh apply-bind-user.sh; do sed -i '' '1s|.*|#!/bin/dash|' "$X/dash/examples/cmapi-sso/ldap/$f"; done

one examples "$F/examples" env PYTHONPATH=src "$R/bin/python" -m pytest tests -q -p no:cacheprovider
one service "$F/cmapi" env PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=$DB python -m pytest tests/service -q -W ignore -p no:cacheprovider
one patch02-before "$X/before02/cmapi" env PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=$DB python -m pytest tests/service/test_flow.py -q -W ignore -p no:cacheprovider -k "stored_requirement or open_request_keeps"
one patch02-after "$F/cmapi" env PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=$DB python -m pytest tests/service/test_flow.py -q -W ignore -p no:cacheprovider -k "stored_requirement or open_request_keeps"

SC=$(python -c 'import yaml; print(next(s["run"] for s in yaml.safe_load(open(".github/workflows/ci.yml"))["jobs"]["manifests"]["steps"] if s.get("name")=="Shellcheck"))' 2>/dev/null) || SC=
( cd "$F" && SC=$(python -c 'import yaml; print(next(s["run"] for s in yaml.safe_load(open(".github/workflows/ci.yml"))["jobs"]["manifests"]["steps"] if s.get("name")=="Shellcheck"))'); echo "$SC" > "$X/shellcheck-cmd.txt" )
one shellcheck "$F" bash "$X/shellcheck-cmd.txt"
one ci-guard "$F" python deploy/tests/ci-guard.py .github/workflows/ci.yml
one doc12 "$F" python deploy/tests/doc12-test.py docs/12-existing-postgresql.md
one kind-stubbed "$F" deploy/tests/kind-test-stubbed.sh
one mutate-secrets "$F" python deploy/tests/mutate-secrets.py
one crc-guard "$F" python deploy/tests/crc-guard-test.py
one crc-scripts "$F" deploy/tests/crc-scripts-test.sh
for n in 1 2 3 4 5; do one "doc13-$n" "$F" python deploy/tests/doc13-test.py docs/13-crc-deployment.md; done
one crc-backup "$F" deploy/tests/crc-backup-test.sh
one mockup-cm "$F" deploy/mockup-configmap.sh --check
one render "$F" deploy/render-test.sh

one ldap-failures-before "$X/beforeldap" deploy/tests/ldap-identities-test.sh failures
one ldap-failures-final "$F" deploy/tests/ldap-identities-test.sh failures
one ldap-failures-dash "$X/dash" deploy/tests/ldap-identities-test.sh failures
one ldap-full "$F" deploy/tests/ldap-identities-test.sh
one realm "$F" python deploy/tests/realm-test.py deploy/manifests/environments/crc/realm/10-realm-import.yaml
echo DONE | tee -a "$L/SUMMARY.txt"
