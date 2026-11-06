# Applying reviewer 2's set to `fa8c27c`

From the repository's root, in this order, each with `patch -p1 < <file>`. Every patch was produced against `fa8c27c` plus the ones before it, and the set applied clean to a fresh copy (`logs/final-apply.txt`). No patch changes a file mode, and no new script needs one: the only new file is a Python test run by pytest.

`S` below is this review's output directory. A "before" means the new test against the old code, which is how each was proven. The logs named hold the runs.

| # | Patch | What it does | Fails before, passes after | Log |
|---|---|---|---|---|
| 01 | `01-gnu-stat-first.patch` | Job 2. `stat -c` first in three places, and a rule in `ci-guard.py` | In Ubuntu 24.04: `deploy/tests/crc-scripts-test.sh`, case `modes`. On a Mac: `python3 deploy/tests/ci-guard.py .github/workflows/ci.yml` with the new `ci-guard.py` over the old tests | `job2-*.txt`, `01-*.txt` |
| 02 | `02-watch-never-dies-silently.patch` | F1. `http_get`'s handler, every exception in the watch's loop, and a watch that ends writes the stop file | `python3 deploy/tests/crc-guard-test.py <old crc-guard.py> --no-mutants`: 5 cases FAIL, then 0 | `02-*.txt` |
| 03 | `03-secrets-issuer-names-cmapi.patch` | F2. `--issuer` must be `https://<host>/realms/cmapi`, whole | `secrets-test.sh` on its stub, new test over old `secrets.sh`: every `11j` FAILs, then 0 | `03-*.txt` |
| 04 | `04-proof-blocked-is-not-broken.patch` | F3. Blocked means wget's own timeout, and the api answers the router straight after | `deploy/tests/crc-scripts-test.sh`, new test over old `crc-proof.sh`: 6 `proof did not fail`, then 0 | `04-*.txt`, `f3-*.txt` |
| 05 | `05-gate-sees-a-dead-watch.patch` | New N1. `gate` refuses a watch that began and is gone or hung; `watching` proves it began | `crc-guard-test.py <04's guard> --no-mutants`: 7 FAIL, then 0 | `05-*.txt` |
| 06 | `06-runbook-stops-hold.patch` | F4. Every step a subshell, every failure written to `$STOP`; `doc13-test.py` now runs the blocks | `python3 deploy/tests/doc13-test.py <old docs/13>`: rc 1, also with reviewer 1's patch applied; then rc 0, no mutant surviving | `06-*.txt` |
| 07 | `07-import-wait-follows-through.patch` | New N2 and N3. A failed read does not end the follow; `HasErrors` alone does not interrupt a running import | `crc-guard-test.py <06's guard> --no-mutants`: 3 FAIL, then 0 | `07-*.txt` |
| 08 | `08-reader-ca-bundle.patch` | New N4. The six checks read a CA bundle, block by block. **Application code**, in `cmapi/src` | In `cmapi/`: `PYTHONPATH=src python -m pytest tests/service/test_registry_ca_bundle.py --noconftest`: 2 failed, then 9 passed | `08-*.txt` |
| 09 | `09-realm-one-password-client.patch` | New N5. Guesses limited, `admin-cli` off. **Changes the realm import, so it must go in before the first import** | `pytest tests/service/test_plain_manifests.py --noconftest -k guesses`: failed, then passed. On real Keycloak: `deploy/tests/realm-test.py` | `09-*.txt` |

The numbering is a dependency order. 06 needs 05's `watching`, 07 builds on 05's `why_stopped` and on the runbook's table in 06. Each of 02, 03, 04, 08 and 09 stands alone if the coordinator declines another, apart from context lines in `crc-guard-test.py`, `crc-scripts-test.sh` and `docs/13`. 05 and 06 go together: 06's `doc13-test.py` requires `$G watching`.

## After applying

```bash
python3 deploy/tests/crc-guard-test.py                    # with mutants
deploy/tests/crc-scripts-test.sh
python3 deploy/tests/doc13-test.py docs/13-crc-deployment.md
deploy/render-test.sh
python3 deploy/tests/mutate-secrets.py
python3 deploy/tests/ci-guard.py .github/workflows/ci.yml
shellcheck deploy/crc-*.sh deploy/secrets.sh deploy/secrets-test.sh deploy/tests/*.sh deploy/tests/secrets-stub/stub.sh
cd cmapi && PYTHONPATH=src:tests/service python3 -m pytest tests/service/test_plain_manifests.py tests/service/test_crc_environment.py tests/service/test_registry_ca_bundle.py --noconftest -q
```

Those need PyYAML and httpx, and the last also needs the service's dependencies. With `--noconftest`, four cases of `test_crc_environment.py` error on a missing `fresh_db` fixture, since they need a database. Run with `conftest.py` on a throwaway PostgreSQL 16 they pass, and the whole service suite gave 352 passed and 1 failed, the one that needs a git repository (`logs/final-pytest-*.txt`).

## Only CI can prove

- **Docker on the runner.** This Mac's Docker daemon is not running. `crc-backup-test.sh` and `realm-test.py` ran here on Podman, under renamed containers. They use only `run`, `exec`, `port`, `ps`, `rm` and `inspect`, whose output they read in forms I read for Docker but did not run.
- **`deploy/tests/realm-test.py`'s `osixia/openldap` under Docker's file limit.** Inferred only: that image is known for trouble when `nofile` is very high. If the LDAP seed case fails on the runner, try `--ulimit nofile=1024:1024` on that one `docker run` first. No change is made for this.
- **The kind steps** (`secrets-test.sh` on real kubectl, `np-reach-test.sh`). Not run: no kind cluster in this review. `secrets-test.sh` ran on its stub.

## Only CRC can prove

Read-only, for the coordinator, before step 21 is reached:

```bash
oc get cm kube-root-ca.crt -n cmapi -o 'jsonpath={.data.ca\.crt}' | grep -c 'BEGIN CERTIFICATE'
```

Above 1 means N4 applies as written. With a bundle, the old check fails if any certificate but the last has base64 padding, which depends on each certificate's length.

- That OVN-Kubernetes drops and does not reset, and so gives `download timed out` (04). A reset stops step 21 with wget's message, for a person to read.
- That RHBK's `HasErrors` matches the 26.6.4 source (07), and that RHBK's import honours an `admin-cli` entry and these brute-force fields as community 26.6.4 did (09).
