# cmapi PR #700 review

**PostgreSQL was unreachable from the sandbox.** Both PR tests stopped in fixture setup on base `c5f705b` and head `0ec93a9`. psycopg reported “Operation not permitted” connecting to `127.0.0.1:55432`. The pool and isolation conclusions below come from source inspection. The reported three HTTP 500s, their latency, and the claimed base/head results remain unverified.

**Request changes.** Head removes the second checkout under the HTTP submit's daily lock. The revert worker still opens a second session for the same switch. The supplied patch fixes the missed caller and includes its regression test.

## Primary sources

- PostgreSQL 16 says a plain SELECT “sees only data committed before the query began” and “does see the effects of previous updates executed within its own transaction”. The relevant instant is the start of the switch query. Read 2026-11-25. [PostgreSQL 16 §13.2.1, Read Committed](https://www.postgresql.org/docs/16/transaction-iso.html#XACT-READ-COMMITTED)
- SQLAlchemy documents the QueuePool constructor default as `timeout: float = 30.0`. cmapi's `core/db/__init__.py:27–29` sets five persistent and five overflow connections and inherits that checkout timeout. It applies when a caller waits for the pool, independently of the advisory-lock wait inside PostgreSQL. Read 2026-11-25. [SQLAlchemy 2.1, QueuePool](https://docs.sqlalchemy.org/en/21/core/pooling.html#sqlalchemy.pool.QueuePool.__init__)
- SQLAlchemy says that for an unexpired object already present in the Session identity map, “the object is returned directly from this collection and no SQL is emitted”. That matters because `SwitchRepo.get` uses `Session.get`. Read 2026-11-25. [SQLAlchemy 2.1, Session.get](https://docs.sqlalchemy.org/en/21/orm/session_api.html#sqlalchemy.orm.Session.get)

## Findings

**Medium — Revert reads the switch on another connection while holding the original request's row lock.** At `jobs/open_pr.py:100`, both a restoring update and a reverting delete call `_decide(facts)`. The handler has already fetched the request and run `repo.move`, which refreshes it `FOR UPDATE` and flushes the transition. The omitted session makes `AppContext.auto_paused(None)` check out another connection. If that checkout stalls, the worker retains the row lock, and a timeout rolls back the revert and enters worker failure handling. The later call to `submit` comes too late to fix this read. This path predates #700. Each production worker builds its own pool and runs one handler at a time, so twelve HTTP creates in an API pod do not exhaust a worker pod's pool. The defect is the unnecessary dependency on a spare connection during recovery.

The patch passes `session=s` at the initial decision. Its focused test runs the real revert handler with a session double and checks the decision received that exact session. On unmodified head it failed with the session argument missing. With the one-line fix it passed. This test establishes the call contract only. [Fix and regression test](r1-outputs/fix.diff)

**Low — The concurrent test can pass without reaching pool capacity.** At `tests/service/test_pool_starvation_695.py:40–44`, twelve executor tasks can arrive at the lock in smaller groups. Base can finish a submit using a spare connection and pass. The 25-second cutoff also includes JWT creation, HTTP dispatch, planning and scheduling, so exceeding it does not identify a checkout timeout. The patch gates the first ten submissions immediately before the real lock SQL, after checkout. It requires all ten to reach the gate and all twelve requests to return 202. Later submissions bypass the opened gate. The barrier timeout diagnoses failure to assemble the first wave. The patched database test still needs a PostgreSQL run.

## Session audit

I searched the exported `head/cmapi/src` with recursive grep for switch references, decision calls, session factories, direct connections and `team_request`, then traced the enclosing callers. The export has no initialized TokenSave graph. Paths below are relative to `head/cmapi/src/cmapi/`.

| Path | What owns the connection |
|---|---|
| Switch wiring and planning | `core/context.py:180` injects the bound method. Its only invocation is `Pipeline._decide` at `core/pipeline.py:503`. The four decision sites are namespace planning (435), delete planning (542), submit (556), and the revert handler (100). HTTP planning, including dry runs and expiry writes, follows the closed replay lookup and precedes the submit session. Its stand-alone switch session closes on return. |
| HTTP submit | `RequestRepo.next_id` issues `pg_advisory_xact_lock` (`core/db/repo.py:153–160`). A waiting submit already owns a connection. On base the lock holder needed a second one for the switch. On head a non-delete with a team counts the day's auto-approvals and reads the switch on `repo.s`. Insertion, queueing, warning recording, audit and response assembly also use that session. Deletes and teamless plans retain their planning decision on both revisions. |
| Approval, rejection and timeout | `routers/requests.py:146–168` locks the row, reconstructs the stored ledger, records the decision and enqueues jobs on one session. The ledger applies rules in memory. The reject, cancel, retry and revert endpoints also pass their session to repositories. The revert endpoint only queues the job. `jobs/approval_timeout.py:16` uses the supplied worker session. |
| Team rate limiting, replay and refusal recording | `routers/__init__.py:96–113` takes or refunds an in-memory token. The limiter releases its mutex before the database work. The submit session exits before a refund or a 409/429 replay lookup (`plugins/namespaces/router.py:101–119`). A planning refusal writes separately before submit. Warning and CI recording use a savepoint on the supplied session. Production JWKS persistence runs during authentication before the route transaction. |
| Expiration | `plugins/expiration/rules.py:214` computes notices and delete candidates in memory. No `expire_check` handler appears in `jobs/__init__.py`. The expiry list closes its open-request session before querying notices. The three expiry writes use ordinary namespace planning and submit. |
| Apply worker — intentional second checkout | `jobs/apply.py:98` calls `jobs/delivery.py:114–124` with a handler transaction open. The marker transaction locks the request and commits `apply_started` **before** the first cluster write. Cancellation checks the same lock and marker. Moving the write into the handler transaction would hide the marker until after the external effect and could lose it on rollback. |
| Worker heartbeat — intentional concurrent checkout | `worker.py:88–100,104–145` renews the lease in a separate thread and transaction while a handler can hold a connection. A lease extension must become visible during the job. The claim commits before the handler starts, and failure recording starts after the handler session exits. |

The base checkout cycle can stall other routes that need the exhausted API pool, including readiness. “Every route waited” is broader than the evidence. For example, the async version endpoint returns build metadata without querying PostgreSQL (`routers/health.py:48–53`). Neither PR test sends an unrelated request during the burst.

## Kill-switch visibility and other behavior

At PostgreSQL's default READ COMMITTED, a pause committed while submit waits for the daily lock is visible when submit subsequently queries the switch. Another transaction's uncommitted pause is invisible. A transaction can read its own uncommitted writes, but the submit path never writes the switch. Its HTTP planning read used a different session, and the submit session has not previously loaded the switch row, so the identity map cannot supply an older copy on this path. The admin pause and resume transactions commit before returning their switch view (`routers/admin.py:148–165`).

This preserves the kill switch for decisions made after a pause commits. A pause committing **after** the decision query can overlap an already-decided request that commits later. Neither revision serializes admin changes with the final request commit. Deletes and teamless requests already used their earlier planning decision. The design's “Immediate, no PR” holds for subsequent switch reads. A requirement to stop every in-flight approval at admin commit would require coordination on both write paths. Under REPEATABLE READ a reused transaction could miss a later commit even before the switch query. The export configures no isolation override, and the live database setting could not be inspected.

The patch adds a two-session PostgreSQL test. The reader starts its transaction with `next_id()`, the admin flushes a pause, the reader checks while the pause is uncommitted, then checks again after admin commit. The expected answers are false and true. The existing `test_flow.py::test_auto_approval_kill_switch` covers a completed admin pause followed by a new create.

The callback signature did change. Direct `ctx.auto_paused()` still works, but `Pipeline._decide` now passes a positional argument even for planning. A custom injected zero-argument callback would raise `TypeError`. Both the default and the only injected callback in the export accept it. The policy rules, fallback counters, pause gauge, daily lock, pool size and HTTP contracts retain their existing behavior. The documentation changes update source citations.

## Test evidence

I ran the supplied pytest module with the specified interpreter, database and import path, sequentially in copies under `r1-work/`. Base received only head's new test file. I set `CMAPI_MIGRATE_WAIT_SECONDS=0` after the sandbox denied TCP, to skip the migration retry delay. No SQLite substitute was used.

| Run | Observed result |
|---|---|
| Base plus the PR tests | 2 setup errors at PostgreSQL migration. Neither test body ran. |
| Unmodified head with the PR tests | 2 setup errors at the same connection attempt. Neither test body ran. |
| Head plus the revert wiring test, before the fix | 1 assertion failure. The real handler called the decision without its worker session. |
| Patched head, full revised module | 1 passed (revert wiring), 3 database setup errors (single create, saturated pool, pause visibility). |
| Patch verification | Both hunks' target files passed a dry-run application against the head export. |

The PR uses a real PostgreSQL engine, pool and transaction-scoped advisory lock. The `limited` fixture uses fake Git, Kubernetes, validation, identity-key fetching and a rate-limit clock (`tests/service/test_rate_limits_689.py:50` and `conftest.py:450–501`). The isolated single-create test samples the real pool's `checkedout()` on each checkout. Source inspection predicts a peak of two on base and one on head. This is the stronger of the two original regressions because it detects overlap without requiring a particular thread schedule.

## Five-line summary

- Head removes the nested switch checkout from HTTP submit under the daily advisory lock.
- The revert worker misses the same session reuse. Its regression test failed before the fix and passed afterward.
- Apply-marker durability and lease renewal account for the intentional overlapping worker transactions.
- READ COMMITTED makes a pause visible to a subsequent switch query, including after a wait for the lock.
- PostgreSQL setup was blocked on both revisions. The patch includes tests for saturation and pause visibility.
