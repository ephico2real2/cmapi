# PR #112 (#110, #109): review

The first pass stopped when the owner cleared the session on 2026-11-06. A new session arbitrated it the same night, per `.claude/skills/fix-defect/SKILL.md`, step 4, until the owner stopped all work to resume later.

- `reviewer-1-codex.md`: Codex at `be66382`, 109,091 tokens. Two findings: #115, #116.
- `reviewer-2-opus.md`: reviewer 2's answer. Finding 1 amended, finding 2's fix accepted with a real test, and new defects #119, #120, #121, #122, #123, #124, #125, #126.
- `reviewer-2-proposed/`: its eleven patches against `be66382`, with `APPLY.md`.
- `reviewer-2-tools/`: its proof runner and patch builder, with paths from the old scratchpad.

## The coordinator's rulings

All eleven patches: **accepted**, and applied unchanged, one commit each. Each applied with `patch -p1 --fuzz=0` on `eabe1a7`, where nothing but documents had changed since `be66382`. After the last commit the tree was identical to the one tested below, by `diff -r`.

| Patch | Issue | Commit | Reason |
|---|---|---|---|
| 01 | #117 | `47ddb4f` | The test only moves, because `cmapi.core.db` needs sqlalchemy. `reference-code` passes in a Python 3.12 venv with only its own requirements. Removed lines read: `test_every_requirement_carries_the_group_path` stays in `tests/core` for `decide()` |
| 02 | #126 | `836c761` | `LEGACY_GROUP_PATH` equals `main`'s `GROUP_PATH`, read from `origin/main`. Without the code, `test_a_stored_requirement_keeps_its_group_path` fails. `test_an_open_request_keeps_the_path_it_was_decided_under` passes either way: it holds docs/11's claim, which already worked, and is kept for that |
| 03 | #115 | `797188a` | Fails before, passes after. It replaces reviewer 1's patch, where a failing `sort` still passed: reviewer 2's measurement, not rerun here |
| 04 | #116 | `7001161` | Reviewer 1's script change, with a test that breaks the real tool |
| 05 | #121 | `5fe1d55` | Fails before, passes after |
| 06 | #122 | `ef6b990` | Fails before, passes after |
| 07 | #120 | `5623dca` | Moves code that the mutants edit: the full run still killed all 11 |
| 08 | #119 | `00f6b72` | The worst of them: on `be66382` the removal asked for 23 deletes with someone else's entry at a test user's name |
| 09 | #123 | `3e66245` | `die` in a piped `while` stops the script under `set -e`, measured on `/bin/dash` and `/bin/bash` |
| 10 | #124 | `e28ce14` | Its test holds the fingerprint of `keycloak-ca.pem` and the 3 certificates in the bundle |
| 11 | #125 | `0bde88c` | Fails closed. See "Inferred" for the 32 |

## What ran

On an Intel Mac, 2026-11-06, Python 3.12, Podman, `KUBECONFIG` an empty file. No cluster.

| Proof | Result |
|---|---|
| `reference-code` (`examples`) | 136 passed |
| Service suite | 371 passed |
| Patch 02's 2 tests | Without its code 1 failed, 1 passed. With it 2 passed |
| `shellcheck`, `ci-guard`, `doc12`, `kind-test-stubbed`, `crc-scripts`, `crc-backup`, `mockup-configmap --check`, `render-test` | rc 0 |
| `mutate-secrets` | 32 mutants, 0 wrong |
| `doc13` | 5 runs, each 0 failed and 0 survived |
| `ldap-identities-test.sh failures` on `be66382`'s two scripts | 31 failed |
| The same on the patched scripts | 0 failed |
| The same with both scripts' shebangs set to `/bin/dash` | 0 failed |
| `ldap-identities-test.sh` in full | 136 cases passed, 0 failed, 11 mutants killed, 0 survived, 454 s |
| `realm-test.py` on real Keycloak 26.6.4 | 0 failed |

`crc-guard-test.py` did not finish here: the owner stopped it at 622 s, with 94 cases passed, 0 failed and 24 mutants killed, none surviving. No patch touches `crc-guard.py` or its test. CI's run on the head is the proof for it.

**Inferred:** behaviour on Docker and on a hosted runner, until CI's run on the head; that the real server answers 32 for `ou=TrustedApplications`, from `docs/11`, "a user they do not name gets No such object (32)". `apply-bind-user.sh` is not part of `docs/13`'s run, so a wrong inference fails only a manual rerun, and it fails closed.

**Not tested:** Docker on this Mac, a real cluster, the real directory.

**Owner's decision, when it matters:** where channel mail goes; `cmapi-approver-platform@...` is not a real list, and SMTP is off on CRC and kind.

CI, run 42333085083 at `0bde88c`, finished: `reference-code`, `service`, `portal-mockup`, `portal-ui` and `manifests` all success, the last on Docker and Ubuntu, and including the full `crc-guard`.

## #118: proved, not yet applied

`night/118/118.patch`, against `0bde88c` with `patch -p1 --fuzz=0` (dry run measured). Written by Opus 5.5 at `high`, stopped by the owner, and handed to Codex `gpt-6.1-sol`, which left the fix unchanged. Reports: `night/118/`.

Cause: `doc13-test.py` logged each stub call to one file, so a backgrounded `crc-guard.py watch` logging late read as "the step after 12 ran". Delaying only the stub's `watch`, with the document unchanged, reproduced CI's exact message in 3 of 8 runs at 0.25 and 0.3 s. One file per case was not enough: at 0.02 s it still failed 7 of 8, since a case's own `watch` logged after its mark. That CI's one failure was this race is inferred: `manifests` passed on the next three heads with nothing under `deploy/` changed, and CI was not rerun at that commit.

The fix waits for everything a step left in the background, through an inherited pipe, with no sleep. The next step logs to its own file. A new check says "step 12 began the watch all the same", so a failed `snapshot` starting the watch stays caught.

| Proof, final code | Result | By |
|---|---|---|
| The whole test, 3 parallel runs | 3 of 3: 0 failed, 0 survived, at about 270 s under load | Coordinator |
| Mutants of the fix: no wait, no "began the watch" check, no separate next-step log | 3 of 3 made the test fail | Coordinator |
| Step 12 at 7 delays from 0.02 to 1.0 s, 8 runs each | 56 of 56 with no false failure | Codex |
| The 3 late mutants at 0.02, 0.1 and 0.3 s, 8 runs each | 72 of 72 caught | Codex |
| The new test on the logic before the fix | Fails, and names the race | Codex |

**Not finished:** H5, the added runtime: stopped by the owner, with one valid pair at 129.3 s and 138.5 s on a loaded machine. **Not tested:** Linux, until CI runs it. Codex's sandbox reached no container runtime.

## The second pass: not run

The owner stopped it before it began. The brief is `second-pass-brief.md`, with `@@HEAD@@`, `@@COMMITS@@` and `@@GRAPH_ROOT@@` to fill. So after the first pass, no reviewer has looked at these patches together on the fixed head: the coordinator's proofs and CI have. Patches 03 and 04 were derived from reviewer 1's, and reviewer 1 has not seen reviewer 2's others.

## Also stopped that night, in `night/`

`87/` and `91/`: reports, briefs and patches for those issues, each stopped midway by the owner. Nothing in them is validated by the coordinator. The verdicts are in each `verdicts.md`. `proof-summary.txt` and `proofs.sh` are the proofs above, with this night's scratchpad paths. Long logs were not kept. The tests' `logs/` links in those reports therefore lead nowhere, and only the commands can reproduce them.

**Who wrote what.** Eleven patches: reviewer 2, Opus 5.5 at `high`. #118: Opus 5.5 at `high`, proved by Codex `gpt-6.1-sol`. #87's findings and #91's continuation: Codex `gpt-6.1-sol`. The record and the rulings: the coordinator, Opus 5.5.
