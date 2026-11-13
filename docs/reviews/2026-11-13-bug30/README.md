# #141 (BUG-30): the second reader

The fix of #141 changes an authorization answer, so it has a second reader. Codex `gpt-6.1-sol` reviewed commit `99c4a42` on an export, on 2026-11-13, with five claims. The brief as sent is `brief.md`, and Codex's verdicts and tests are `verdicts.md` and `tests.md`. Fable 5.2 (OB1) wrote the fix and this record.

| Claim | Codex | Ruling |
|---|---|---|
| C1. A caller of another environment gets 403 `environment-forbidden`, and nothing is written | CONFIRMED, measured | Stands |
| C2. Nobody can approve who could not approve before | CONFIRMED | Stands |
| C3. Nobody is refused who could approve before | CONFIRMED, measured for a scoped role, a self-approving requester and a service client | Stands |
| C4. "The order of answers changed in one way only" | REFUTED | The claim was wrong, not the code. Two answers changed, and both are the intended fix: on a pending request the code goes from `forbidden` to `environment-forbidden`, and on a request that is no longer pending the caller of another environment gets 403 and not 409 `not-pending`. `already-approved`, `self-approval` and `not-eligible` did not change (measured) |
| C5. The check runs inside the transaction that holds the row lock, and a 403 leaves no lock and no write | CONFIRMED, measured with a second database connection | Stands |

Codex found no defect and gave no patch. It ran 44 tests: the 13 of the supplied file and 31 of its own. Its own test file is not in the repository: the supplied test `test_an_approval_in_another_environment_says_so_like_a_rejection` holds the changed behaviour, and the unchanged answers have their tests in `test_review_c_authz.py` and `test_flow.py`.

Measured on macOS, Python 3.12, PostgreSQL 16 on `127.0.0.1:55432`. No cluster.
