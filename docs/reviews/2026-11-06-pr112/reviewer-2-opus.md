# Reviewer 2 on #110 and #109, code at be66382: STOPPED, not finished

The owner asked this run to stop, to resume later. All background work is stopped, and the containers this run labelled are removed. `cmapi-test-pg` was not touched. **The patch set is not proven yet, so do not apply it as ready.** "What remains" lists the proofs that did not finish.

Patches: `output/final/NN-*.patch`, order in `output/final/APPLY.md`. Logs: `output/logs/`. To regenerate the patches: `work/build.py`.

## Verdicts

| # | Item | Verdict | Evidence |
|---|---|---|---|
| R1-1 | Measurements can disappear or hash nothing | **AMEND** (patch 03) | Reproduced: `job3-exp1b-before.txt`, H, H1, H1b and H1c all rc 0 with 13 users written; H printed "digest  before and after" with no digest |
| R1-2 | A failed hash read counts as zero hashes | **ACCEPT the fix, replace the test** (patch 04) | Reproduced: exp1b, case I, rc 0, "sees no password hash: 0" |
| J2 | CI `reference-code` failure | Test moved to `tests/service` (patch 01) | Before 1 failed, 136 passed. After: `proof-examples.txt` |
| M1 | A holder whose DN is not ASCII is invisible to the guards | **New, confirmed** (05) | exp1 C3: rc 0 with `uidNumber` 10105 on two entries. C2: 13 users written before a later check noticed |
| M2 | Bind user's read of `ou=Groups` is only measured after the write | **New, confirmed** (06) | exp1 D: 13 users, 10 groups and the Secret written, then FAIL |
| M3 | `--remove-old-groups` proceeds on an unproven new set | **New, confirmed** (07) | exp1 E2: rc 0, ten old groups deleted, with a real person in a new group and a test user missing. One new group simply absent was already refused (E) |
| M4 | `--remove-test-identities` deletes what it did not write | **New, confirmed: the worst one** (08) | exp1 F: deleted an entry at `cn=cmapi.admin` holding another `sn`, and a group holding a real person; the run failed only after the deletes |
| M5 | A failed openssl leaves a Secret of empty passwords | **New, confirmed** (09) | exp1 G: 13 keys, 0 bytes, no LDAP write. Every later run then stops until the Secret is deleted |
| M6 | `--mac-ca` regression with `--extra-ca` | **New, confirmed** (10) | `patch10-crc-scripts-before.txt`: 3 failures before |
| M7 | `apply-bind-user.sh` has reviewer 1's defect twice, on lines 114 and 115 | **New, pre-existing on main** (11) | `ldap-failures-reviewer1-patches-only.txt`: both fail with reviewer 1's patches on |
| M8 | A row with no `groupPath` reads under the new default | **New, fails closed** (02) | `job3-groupPath-before.txt`: old row gives `/cmapi/app-cmapi-rbac-platform-leads`, a group nobody holds |

## Job 1

Reviewer 1's `tests/*.sh` look for strings in the script, confirmed by reading them. They run none of its logic, and an equivalent fix written differently would fail them. Replaced by `the_failures` in `deploy/tests/ldap-identities-test.sh`, which breaks the real tool inside the real OpenLDAP container (moved aside, or a shim that fails matching calls) and runs the real script.

- **Why finding 1 is amended:** with reviewer 1's patch on, a `sort` that fails on what the digest covers still passes and writes everything (`ldap-failures-reviewer1-patches-only.txt`), because `sort | sha256sum` hashes nothing and this shell has no pipefail. Patch 03 goes through files, one step a line, under `set -e`. Reviewer 1's host-side check and gate check are kept.
- **Its other cases hold with its patch:** sha256sum gone, an empty digest, the gate's grep failing, and a gate with no member attribute are all refused.
- **Delivery:** reviewer 1's measurements patch **does not apply at `--fuzz=0`** on be66382, measured. It applies at the default fuzz.
- **Questions in the brief:**
  - `grep -c` under `set -u`: no problem. It prints 0 and `|| true` handles the status.
  - `|| true` on the gate's grep hides nothing, since the `-s` check catches the empty file (the grep-failure case proves it).
  - `|| true` on the hash count: a grep that fails prints nothing, and "" is not 0, so it fails. This comes from reading the code; no case runs it.
  - An empty gate group is refused. A `groupOfNames` cannot be empty by schema, so this only stops a gate of another shape. That includes a rollback, where a gate with no member attribute passed before.

## Job 2

- **Cause:** `cmapi.core.db` imports sqlalchemy, `examples/tests` is a symlink to `cmapi/tests/core`, and that job installs only `examples/local/requirements.txt`. Reproduced in a fresh Python 3.12 venv with those requirements only.
- **Decision:** the test is misplaced and the import is correct, since moving JSON code out of `repo.py` is scope nobody asked for. It is the only core test importing the db package (grep).
- **Look-ahead for `manifests`, Docker versus Podman.** **No Docker daemon runs on this Mac, so nothing ran on Docker.** What I could check:
  - The image's `startup.sh:578` writes `0.0.0.0 <hostname>` to `/etc/hosts`, so `ldap://localhost` should work on Docker as well (read, not run).
  - `LDAP_NOFILE: 1024` is the image default and `process.sh` applies it, so Docker's nofile limit does not reach slapd.
  - The script is `#!/bin/sh`, which is dash on Ubuntu. At be66382 it passed apply, rerun and both removals under `/bin/dash` here (exp1b, K). **The patched script has not been run under dash.**
  - `awk` on the runner may be mawk or gawk (unknown). The container's awk is mawk, and the programs sent to the pod ran on it.
  - File modes are 100755 at be66382. `ci.yml` has no `timeout-minutes`, so the job's length is not a limit.
- **Duration:** on Podman, a `start` took 107 s, a first run 11 s, a rerun 5 s, so the time goes to container starts and the mutants. Reference: `the_failures` alone took 2m47 including one start, under Podman. Its cases share `the_stops`' container in the full run, so they add no start. The patched suite's total time was not measured, because it was stopped.

## Job 3

1. **`apply-test-identities.sh` on a real OpenLDAP with exhaustive rules** (`job3-exp1-before.txt`, `job3-exp1b-before.txt`):
   - The 5th `ldapadd` failing, then a rerun: rc 53 with 4 users and the Secret, then the rerun completes with 13 and 10. Holds.
   - A partial delete, then a rerun: holds.
   - An ASCII-named uid holder: refused, holds. Non-ASCII: M1.
   - Old-group removal: M3. Writes before preconditions: M2 and M5.
2. **Changes beyond the brief:**
   - `--mac-ca` on the saved real certificates: the bundle is **byte-identical** to be66382's after patch 10, `openssl verify` passes on the saved real Keycloak and edge leaves, and the fingerprints match docs/13. So `$CMAPI_CRC_CA` still verifies both. Not tried over TLS against the Routes (no cluster). The regression is only with `--extra-ca` (M6).
   - `apply-bind-user.sh`'s edit: weaker than the "exactly ten" it replaces, and needed for the order of the steps. The new script checks the groups as this user.
   - `expectUsers`: holds. Keycloak answered 13 added on the first sync and 13 updated after it.
   - The table as the source of expected tokens: `realm-test.py` rc 0 on the patched tree.
3. **`identity.groupPath`:**
   - Sixteen malformed values were all refused, including `{name!r}`, `{{name}}`, a lone `{`, None and a missing `/`.
   - An old row: M8.
   - A config change under an open request: patch 02 adds a test through the routes, **not run yet**.
   - `channels.py:62`'s `cmapi-approver-platform@ephico2real.com` is **not a real list name anywhere**: grep finds no such list, no `groupMail` in any config, and the chart cannot pass `groupMail`. `cmapi-platform-leads@` was not one either. SMTP is `{}` on CRC and kind, so it is unreachable as shipped. No patch: what to send to is the owner's decision.
   - Left as is: `PortalChannel` uses the current path rather than the stored one. It only affects the recorded `recipients`, and only across a config change.
4. **`realm_sync.py`'s empty-list PUT holds, measured on real Keycloak 26.6.4** (`job3-realm-put-probe.txt`):
   - No `usersFilter` removes that key and no other.
   - A hand-set key survives a rerun, and mapper ids and configs are unchanged.
   - Every key tried was honoured by a PUT.
   - A person imported while unfiltered is gone once the filter is back, and gets 400.
5. **Old names:**
   - No CODEOWNERS file exists in the export, only a comment in `tiers.yaml`.
   - What remains in non-test code is `examples/local` (keeps its names through the setting), `logic.generated.js` and the mockup ConfigMap (mockup data), and the script's own removal list.
   - The rename pairs in the approval rules checked one to one, and none is swapped.
6. **Scope:** beyond #110's text and #109: `identity.groupPath` with a new stored JSON key, and `expectUsers`; `crc-rollback.sh` now writes to LDAP, and docs say so. Removals in the test files looked like renames and renumbering from a scan, not a line-by-line read.

## Retracted

- I retract "`rules.py`'s hard-coded `approver-platform` gives an expiry slot nobody holds on `examples/local`". `extra_approvals` is only read for truthiness (`expirationBeyondLimits`), and the group comes from the rules' thresholds. No patch.
- exp1 cases H, H2 and I are invalid. My harness left a broken `openssl` on `PATH`. They were rerun in exp1b, and only those results are cited.
- My first shim glob for `ou=TrustedApplications` held a space, a syntax error in a `case`, so that case passed for the wrong reason. Fixed. The log `ldap-failures-before-all-patches.txt` predates the fix, so it shows that case as ok; with the fix it fails on unpatched `apply-bind-user.sh` (reviewer-1-only log).
- My first reviewer-1 run was invalid because its patch had been rejected. It was rerun with the patch applied at default fuzz.

## Measured, inferred, not tested

**Measured, on the patch set** (the first eight on `work/verify`, whose only difference from the final set is two lines of the test file):

| Check | Result |
|---|---|
| `examples` | rc 0 |
| shellcheck | rc 0 |
| ci-guard | rc 0 |
| doc12 | rc 0 |
| doc13 | rc 0 |
| render-test | rc 0 |
| crc-scripts-test | rc 0 |
| crc-guard `--no-mutants` | rc 0 |
| `realm-test.py` (final tree) | rc 0, 0 cases failed |
| `ldap-identities-test.sh failures`, all patches | 0 failed, before the glob fix |
| The same, on be66382's scripts | 30 failed, before the glob fix |
| Patches apply with `patch -p1 --fuzz=0`, in order, on the export | yes |

**Inferred:** behaviour on Docker and on a hosted runner; that the real server answers 32 for `ou=TrustedApplications`, from the script's own comment and docs/11 (patch 11 now requires it); how many real names are non-ASCII, which I did not check, so M1's likelihood is unmeasured.

**Not tested:** any real cluster, `oc`, CRC, Docker, or the real directory.

## What remains, in this order

Containers are removed and the patches are built. `work/final` is a fresh copy with the final patches applied; `cmapi-r2-pg` must be started again on 127.0.0.1:55492.

1. **Service suite: never run on this set.** Patches 01 and 02's tests in `test_flow.py`, including `test_an_open_request_keeps_the_path_it_was_decided_under`, have not run. Any of them may fail.
2. **Patch 02 before and after:** its test against patch 01's `authz.py` and `repo.py`.
3. **`ldap-identities-test.sh` in full with mutants on the final tree:** stopped after the first mutant (killed) with no failure until then. Patch 07 moves code the mutants' edits target, so it must finish. Time it.
4. **`mutate-secrets.py`:** stopped before it reported. It was running on `work/verify`.
5. `failures` on the final tree (after the glob fix), then with the two scripts' shebangs set to `/bin/dash`, and once more on be66382's scripts to replace the "before" log.
6. Rerun shellcheck on the final tree, since the test file changed after that run.

Run the rest with `work/run-proof.sh work/final service mutsec ldap shellcheck`.
