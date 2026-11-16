# Issue #271: one service-test session per database

**The defect.** In #269's full service run, `test_fable_review_240.py::test_audit_an_approved_request_with_a_kyverno_warning_merges` created `req-20261115-0001` (202 at 2026-11-15T01:41:10.864Z). Its `:approve` 89 ms later answered 404 `No request req-20261115-0001`. The test passed alone. During exactly that window (01:41:00Z to 01:41:13Z), a second session ran the new tests on the base commit against the same database. Every test's `fresh_db` truncates the request tables, so the second session deleted the first one's row.

**Measured.**

| Run on one database, the base commit's conftest | Result |
|---|---|
| `test_fable_review_240.py` alone, 3 runs on the base commit | 4 passed each time (re-measured by the coordinator: `ob1-run8/logs/271-alone-{1,2,3}.log`) |
| The same, 12 runs, while a second session loops `test_flow.py` | 12 of 12 runs failed. Two (`271-repro-5`, `271-repro-9`) failed with the same `404 No request req-...`; the others with the other session's rows or their absence: `KeyError: 'events'`, `409 change-pending` on a request the other session created, a `NoneType` request, a deadlock on `change_requests` |
| With this change, `test_flow.py` running and `test_fable_review_240.py` started 3 s later | The second session exits at once with code 75 and the refusal; the first: 20 passed (re-measured by the coordinator after the review fixes: `ob1-run8/logs/272-concurrent-first.log`, `272-concurrent-second.log`) |

The cause is the shared database, not the code under test.

**Options.**
1. A session-wide PostgreSQL advisory lock, `pg_try_advisory_lock`, held on its own connection from `pytest_sessionstart` (or `pytest_collection_finish`, when pytest loads this conftest only while collecting, as `pytest tests` from `cmapi/` does) until the session ends. **Chosen.** It turns a silent cross-run deletion into an immediate refusal that names the database and the way out (`CMAPI_TEST_DATABASE_URL`). It changes nothing for one session or for CI. A session-level advisory lock is held until it is released or the session ends ([PostgreSQL 16, Advisory Locks](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS); [the lock functions](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS)), so a killed session cannot leave it behind: measured, a session killed with SIGKILL released it at once and the next session ran. The refusal exits 75 (`EX_TEMPFAIL`), not one of pytest's own codes 0 to 5.
2. A database per session, created and dropped by the fixtures, as pytest-postgresql does. **Rejected for now.** Several tests read the module's `DB_URL` at import time (`test_data_model_doc.py`, `test_review_h_tools_migrate.py`, `test_crc_environment.py`), and the role needs CREATEDB. It would allow parallel runs, which nothing needs yet. It remains the next step if it ever is.
3. A schema per session through `search_path`. **Rejected.** The migration tests already use their own schemas through `search_path`, and the two would interfere.

**The test.** `tests/service/test_one_session_per_database.py` starts a second session while this one holds the database. It requires exit 75 and the message, that no test of the second session runs, and that no credential is printed. On the base conftest, the second session ran its test and exited 0, so the test failed (`ob1-run8/logs/271-before.log`). After this change it passes (`271-after.log`).
