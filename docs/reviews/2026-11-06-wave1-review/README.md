# Wave 1 (#94) code review, at `fa8c27c`

Reviewer 1: Codex, 174,046 tokens (`reviewer-1-codex.md`). Reviewer 2: a separate Opus 5.5 at `high` (`reviewer-2-opus.md`). `APPLY.md` is reviewer 2's order and commands. Nothing here has run on CRC.

## Decisions

The coordinator accepted all nine patches, applied unchanged, one commit each.

| Patch | Issue | Finding | Found by | Coordinator's check |
|---|---|---|---|---|
| 01 | #99 | CI: BSD-first `stat` | CI | `crc-scripts-test.sh` passes on the Mac; Ubuntu is CI's to show |
| 02 | #100 | The watch can die with no stop file | Codex, amended | Guard test with mutants |
| 03 | #101 | `--issuer` takes any realm | Codex, amended | `mutate-secrets.py`: 32 mutants, 0 wrong |
| 04 | #102 | A broken service reads as blocked | Codex, amended | `crc-scripts-test.sh` |
| 05 | #103 | `gate` passes with a dead watch | Reviewer 2 | Guard test with mutants |
| 06 | #104 | The runbook's stops do not stop | Codex, amended | `doc13-test.py`: 34 mutants, none surviving |
| 07 | #105, #106 | `import-wait` gives up on one read; `HasErrors` kills a running import | Reviewer 2 | Guard test with mutants |
| 08 | #107 | A multi-certificate `caData` is refused | Reviewer 2 | Service suite, and CRC's bundle read |
| 09 | #108 | Unlimited password guesses, no client secret | Reviewer 2 | Service suite; `realm-test.py` was reviewer 2's run, not repeated |

## The coordinator's own run

On a fresh export of `fa8c27c` with the nine patches, none applying with fuzz, on this Mac:

| Suite | Result |
|---|---|
| `crc-guard-test.py`, with mutants | 0 failed, 0 survived, 974 s |
| `crc-scripts-test.sh`, `doc12-test.py`, `render-test.sh`, `ci-guard.py`, `shellcheck` | rc 0 |
| `doc13-test.py` | 0 failed, 0 survived |
| `mutate-secrets.py` | 32 mutants, 0 wrong |
| Service suite on `cmapi-test-pg` | 352 passed, 1 failed: `test_every_shell_script_...` needs a git repository |
| That test's file and the three CRC and registry files, on the branch at `0adc281` | 75 passed |

**A warning during the review.** The harness flagged reviewer 2 as "Security Test Removal". The likely trigger: it switched its own scratch proof script to `--no-mutants`, while a separate full run went on. No patch removes a test: `doc13-test.py`'s mutants went from 14 to 34 and `crc-guard-test.py`'s from 21 to 33, none dropped, and the full run above is the coordinator's.

**#107 on CRC.** `kube-root-ca.crt` in namespace `cmapi` holds 6 certificates (read 2026-11-06). Whether those 6 have the padding that triggers it was not checked. The fix is safe either way.

## Not proven

Docker on the runner and the kind steps are CI's to show. On CRC: OVN-Kubernetes dropping rather than resetting, RHBK matching 26.6.4 on `HasErrors` and the realm's fields, and a real terminal for the runbook.

**Found later, open:** #109, the keychain loop in `docs/13`.
