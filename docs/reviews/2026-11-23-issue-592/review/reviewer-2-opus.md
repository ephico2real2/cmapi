# PR #601 (#592, release 1): reviewer 2's report on head 2c663b8

Reviewer 2 is Opus 5.5 at `high`, and it did not write this step. It checked Codex gpt-6.2-astra's second-pass findings
(`codex-result.txt`, sections A to G) against the code and ran every case on PostgreSQL 16.15 at `127.0.0.1:55432`. The
old pod in each case is 0007's own code, from `git archive 8a5b41c`. Every result below comes from a run in this session,
and the files are in `r2-outputs/`. I did not reopen the owner's decisions on #592 ("expand, then contract" and "refuse,
never drop").

- **Patch:** `r2-outputs/fix.diff`, against head2 2c663b8. Seven files. It applies with `patch -p1` to a clean copy of
  `head2/`, and the result matches `r2/` byte for byte (checked with `cmp`).
- **Optional patch:** `r2-outputs/alt-minimal-trigger.diff`, against `r2/`. This is the trigger option for finding 1.
  I do not recommend it. It is tested, so the owner can choose it.
- **Live-doc edits:** `r2-outputs/LIVE-DOC-EDITS.md`.

## Rulings

| # | Codex's finding | Ruling | Changed in fix.diff |
|---|---|---|---|
| 1 | High: mixed writers can acknowledge two requests under one caller key | **Reproduced. I recommend accepting the risk for release 1, with no trigger.** docs/12 now states the exact risk, and #603 must refuse such pairs | docs/12, docs/16, a test that records the behaviour |
| 2 | High: the requester index holds an expired key forever | **Reproduced, and it regressed from 0007. Fixed with one predicate.** The brief's narrower example fix is not enough (mutant M6) | `by_idempotency` and 2 tests |
| 3 | Medium: the 409 branch is chosen by substring | **Reproduced. Fixed with `diag.constraint_name`**, without Codex's redundant SQLSTATE check | `insert` and 1 test |
| 4 | `key_owner()` cost, and the simplified `by_idempotency` | **Measured. No change in release 1.** The simplification needs the trigger, so it is not adopted | Decision-record wording only |
| 5 | Section F: tests that pass with their defect present | **Two tests strengthened and two added.** Each one fails on its mutant | Tests |
| 6 | Documentation | **Updated** to fit the fixes | docs/12, docs/16, the record, LIVE-DOC-EDITS |

### 1. Mixed writers: two 202s under one caller key (High). I recommend accepting the risk

**Reproduced with the real 0007 code** on the 0008 schema (`r2-outputs/mixed-probe-before.txt`; the database is
`cmapi_r2_mixed`):

```text
0007 pod: S writes key f1a for ola (f1a-ola-dev): 202 requestId=req-20261123-0001
0007 pod: S writes key f1a for amy (f1a-amy-dev): 202 requestId=req-20261123-0002
  row ('req-20261123-0001', 'f1a-ola-dev', 'sub-ola', None, 'f1a', 0)
  row ('req-20261123-0002', 'f1a-amy-dev', 'sub-amy', None, 'f1a', 0)
new pod: S retries amy's body, key f1a: 409 idempotency-replay requestId=req-20261123-0001 'Idempotency-Key was used for a different request'
new pod: S retries ola's body, key f1a: 202 requestId=req-20261123-0001
new pod: S writes key f1b for ola: 202 req-20261123-0003     (idempotency_sub = the service)
0007 pod: S writes key f1b for amy: 202 req-20261123-0004    (idempotency_sub NULL)
new pod: S retries amy's body, key f1b: 409 naming req-20261123-0003
```

This is Codex's case exactly, in both writer orders, and it needs no race.

**What the evidence says about the size of the risk:**

- **It needs a client that reuses one key for a different request.** The two bodies name different persons (different
  `onBehalfOf`). A retry of the same body names the same requester, so the retained requester index
  `(requester_sub, key)` catches it whichever pod version wrote the first row. The race in that case resolves to a replay
  through `_submit`'s second lookup. That second point I inferred from the code (`router.py:111-116`, the index in
  `models.py:201`); I did not race it. Draft-09, section 2.4, makes reusing a key for another payload a client error.
- **A 0007 pod does the same today.** On main, `by_idempotency` looks up by requester, so S's second write (requester amy)
  misses S's first row (requester ola), and the requester index sees two different pairs. I measured the two 202s with
  0007's code on the 0008 schema. The 0007 schema has only the requester index of the two, so I infer the same two 202s
  there; I did not run it. Release 1 adds no new acknowledgement. It only keeps 0007's behaviour while 0007 pods serve.
- **No caller sees another caller's data.** The new reader's wrong answer names the older request of the same service. The
  cross-caller exposure on an old reader (the person replays the service's request) is a separate, already documented
  0007 behaviour (docs/12, probe step 2).
- **How long the window lasts.** On CRC it is the rollout (1 replica, `maxSurge: 1`, `maxUnavailable: 0`, per #592), plus
  any image-only rollback. I did not measure the rollout's duration. The rollback window lasts as long as the operator
  keeps 0007 running.
- **What it leaves for #603.** Rows with a NULL `idempotency_sub` for which `key_owner` gives the same caller and key.
  `0009`'s backfill would break the caller index on them. So, by the owner's rule, `0009` must run 0008's collision check
  over `COALESCE(idempotency_sub, requester->>'submittedBySub', requester_sub)` and refuse until all but one row of each
  pair are over 24 hours old. **The coordinator should add that to #603's acceptance criteria.**

**Codex's trigger, evaluated:**

- **Correctness:** it is right for both versions, but it does three jobs:
  - It fills `idempotency_sub`.
  - It raises 23514 on an ambiguous delegated insert. This branch is dead for application writers: `Requester.record`
    (`core/identity/checks.py:59-66`) always writes `submittedBySub` together with `submittedBy`.
  - It clears expired blockers with an UPDATE of the same table, inside a BEFORE INSERT trigger. That UPDATE fires the
    same trigger again (`UPDATE OF idempotency_key`, so TG_OP is UPDATE and it does not recurse).
- **Locks:** the inner UPDATE takes row locks on expired rows while the inserter holds the day's advisory lock
  (`repo.py` `next_id`). A worker holding such a row (`move()` `FOR UPDATE`) would then stall every submit of that day.
  The inner UPDATE also repeats `by_idempotency`'s expiry in a second language, which makes the trigger harder to debug.
- **0009:** it must drop the trigger and the function as well as the index.
- **Tests:** Codex's old-column-list test is good. `test_a_row_that_a_0007_pod_wrote_after_0008_belongs_to_its_caller`
  makes its NULL with an UPDATE, so it would need rewriting.
- **Finding 2 no longer needs the trigger.** Fix 2 below solves it in the application, in one predicate.

**A minimal trigger also works** (fill only; 10 lines of PL/pgSQL). I measured it with the 0007 code
(`r2-outputs/mixed-probe-minimal-trigger.txt`): the 0007 pod's second write becomes `409 idempotency-replay` "in use for
another request", because the old substring matcher also matches `uq_cr_idempotency_caller`. As an Alembic migration with
its downgrade, with the test inverted, it is `r2-outputs/alt-minimal-trigger.diff`; its test run is in
`r2-outputs/alt-trigger-tests.txt`. It would let #603 skip the backfill and look up by `(idempotency_sub, key)`.

**Options I rejected:**

- **A column `DEFAULT`** cannot read other columns.
- **A generated column** (`GENERATED ALWAYS AS (CASE WHEN idempotency_key IS NOT NULL THEN COALESCE(requester->>'submittedBySub', requester_sub) END) STORED`)
  would derive the caller from `requester`, and the new code could no longer write `who.sub`. That changes the decided
  design ("the new code writes it", #592), and adding a stored generated column rewrites the table.

**Why I recommend accepting the risk.** The owner's rule is to over-build only if it is the only solution. Here the
trigger is not the only solution. The risk reaches only clients that misuse a key, it matches 0007's behaviour today, no
caller sees another caller's data, and `0009` closes it under the owner's own refusal rule. If the owner wants the caller
index enforced during the window and rollback too, apply `alt-minimal-trigger.diff`, replace the docs/12 risk paragraph,
and make #603 drop the trigger.

The fix.diff records the accepted behaviour:

- `docs/12-existing-postgresql.md` gets a new bullet, "The risk accepted in release 1", and the `0009` bullet now says it
  refuses such pairs.
- `docs/16-data-model.md` line 53 qualifies the invariant.
- The `by_idempotency` docstring no longer claims that duplicates need a race.
- `test_a_0007_insert_in_the_window_escapes_the_caller_index` pins the behaviour with 0007's column list, so #603 can
  invert it.

### 2. An expired key stays reserved forever by the requester index (High). Fixed

**Reproduced with HTTP on a new pod alone**, no old pod involved (`mixed-probe-before.txt`):

```text
new pod: S writes key f2a for ola: 202 req-20261123-0005, then aged 25 h
new pod: 25 h later ola uses key f2a, own body: 409 'Idempotency-Key is in use for another request'
new pod: ola tries again: 409 (the same)
new pod: ola writes key f2b, own: 202, aged 25 h; then S uses f2b for ola: 409 (a second caller, the other direction)
0007 pod: 25 h after the new pod's service write, ola uses key f2c: 202   <- 0007 expires by requester, so this regressed
```

**Fix** (`repo.py` `by_idempotency`): the expiry UPDATE clears every expired row that holds this key, and the SELECT
still filters by `key_owner`:

```python
        self.s.execute(update(ChangeRequestRow)
                       .where(ChangeRequestRow.idempotency_key == key,
                              ChangeRequestRow.created_at < func.now() - text(f"interval '{IDEMPOTENCY_HOURS} hours'"))
                       .values(idempotency_key=None, idempotency_fingerprint=None, idempotency_sub=None,
                               updated_at=ChangeRequestRow.updated_at))
        return self.s.scalars(select(ChangeRequestRow).where(ChangeRequestRow.idempotency_key == key,
                                                            key_owner() == caller_sub)
                              .order_by(ChangeRequestRow.created_at, ChangeRequestRow.request_id)).first()
```

**Why this is the right layer.** A new row is blocked by rows with the same key and either the same requester or the same
caller. The lookup does not know the new row's requester: the person is resolved only at planning. Clearing every expired
row for the key covers both pairs.

**The brief's example fix is not enough.** I measured it as mutant M6: clear the caller's rows plus the rows whose
requester is the caller. It fixes the person case and still fails the second-caller case
(`test_a_service_can_use_a_key_that_the_person_held_once_it_expires`).

**Security angle:**

- The UPDATE returns nothing to the caller and changes only the three idempotency columns of rows that are already
  expired. The request, its history and its `updated_at` are kept.
- An expired key never replays on any pod version: each version's lookup clears expired rows before its SELECT, and the
  rows that SELECT can match are a subset of the rows the UPDATE matched. So clearing another caller's expired row changes
  nothing that any caller can observe.
- No live key is touched, which keeps "refuse, never drop".

**Costs:**

- Two lookups that use the same key at once may wait on each other's row lock. Keys are random UUIDs, so this is
  negligible.
- The plan is the same index scan as before, measured: 23 ms against 34 ms for 2c663b8's predicate on 200,000 rows
  (`plan-probe.txt`).

**After the fix** (`mixed-probe-after.txt`; the database is `cmapi_r2_mixed_after`):

- f2a: 202 `req-20261123-0006`, and the retry replays it.
- f2b: 202.
- The expired rows keep their requests, with the key and the caller cleared.

### 3. The 409 branch is chosen by substring (Medium). Fixed

**Reproduced:** `test_a_key_named_after_an_index_is_an_opaque_key` fails on 2c663b8 with `change-pending`, "the request
that held ledger-dev has just finished", where `idempotency-replay` is expected (`before-new-tests.txt`).

**Verified in the venv** (`psycopg-diag.txt`), with psycopg 3.3.8 and SQLAlchemy 2.1.8:

- `exc.orig` is `psycopg.errors.UniqueViolation`.
- `exc.orig.sqlstate` and `exc.orig.diag.sqlstate` are both `23505`.
- `exc.orig.diag.constraint_name` is the index name.
- `str(exc.orig)` carries `DETAIL:  Key (a, k)=(p, uq_cr_open_namespace) already exists.`, so the substring test is true.

**Fix:**

```python
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_cr_open_namespace":
                ...
            if constraint in IDEMPOTENCY_INDEXES:
                raise Problem.conflict("idempotency-replay", "Idempotency-Key is in use for another request") from exc
            raise
```

I dropped Codex's `sqlstate != "23505"` guard. An exact constraint-name match can only come from a unique violation of
that index, and any other error still reaches the final `raise`. The 0007 pod keeps the same substring bug, and it can
only be fixed by retiring 0007. It is not worth a separate issue.

### 4. `key_owner()` cost, and Codex's simplified `by_idempotency`. No change in release 1

Measured on 200,000 synthetic rows at 0008 (`plan-probe.txt`, `EXPLAIN (ANALYZE, BUFFERS)`, rolled back):

| Statement | Plan | Buffers | Time |
|---|---|---|---|
| UPDATE, 2c663b8, by key and `key_owner` | Index Scan on `uq_cr_idempotency`, key as the trailing column, then a filter | 1,960 | 34 ms |
| UPDATE, r2, by key | The same | 1,960 | 23 ms |
| SELECT by `key_owner` | Parallel Seq Scan | 6,504 | 57 ms |

**Ruling:**

- Codex was right that the decision record's "one scan per keyed write" was not a measured claim. Each lookup runs both
  statements, and a 409 fallback runs them twice.
- The cost grows with the table. CRC has 19 rows, and #603 removes `key_owner`, so I changed nothing in release 1. The
  record now gives the measured figures.
- Codex's simplified `by_idempotency` (`idempotency_sub == caller`, `.one_or_none()`) is correct only with the trigger. On
  the PR's migration it would hide 0007-written rows, and `test_a_row_that_a_0007_pod_wrote_after_0008_belongs_to_its_caller`
  would fail. Not adopted.
- `.first()` adds no SQL `LIMIT`. At most two rows match a key and an owner, so this is not worth changing.

### 5. Section F: tests that pass with their defect present

Each strengthened test fails on a mutant that the old tests let through (`r2-outputs/mutants-r2.txt`, one tree copy, each
mutant applied and restored):

| Mutant | Caught by | Result |
|---|---|---|
| M1: the lookup's `<` becomes `<=` | new `test_a_key_exactly_24_hours_old_is_still_held_by_the_lookup_and_the_migration` (one transaction, so `now()` stays fixed; it checks 0008's `_LIVE` and `_EXPIRED` and the repository lookup) | FAILED |
| M2: 0008's `_EXPIRED` `<` becomes `<=` | the same | FAILED |
| M3: the downgrade empties the column instead of dropping it | `test_the_downgrade_keeps_every_key_and_the_old_index`, plus `assert not _has_caller_column(c)` | FAILED |
| M4: the refusal checks only a missing or JSON-null `submittedBySub` | new `test_the_upgrade_refuses_a_live_delegated_row_whose_caller_is_not_a_subject[a-number]` and `[empty]` (the existing test PASSED on the mutant) | FAILED ×2 |
| M5: create skips its first lookup, and only `_submit`'s fallback replays | `test_a_service_retry_on_behalf_of_a_person_replays_its_request`, which now spies: one `by_idempotency` call and no `insert` | FAILED |
| M6: the narrower expiry for finding 2 | `test_a_service_can_use_a_key_that_the_person_held_once_it_expires` | FAILED (the person-direction test PASSED on it) |
| M7: substring classification | `test_a_key_named_after_an_index_is_an_opaque_key` | FAILED |

**The other rows of Codex's section F, ruled with no change:**

- `:89` closed winner: already measured against the index mutants.
- `:106` second person: the gap it leaves is the risk accepted in finding 1, now pinned by
  `test_a_0007_insert_in_the_window_escapes_the_caller_index`.
- `:168` the old-pod row: its UPDATE to NULL leaves the same row state as a 0007 insert, which matters only with a
  trigger. The alt diff's test uses 0007's column list.
- `:248`, `:274`, `:347`: correct as labelled.

My first spy for M5 counted only lookups. It passed on M5, because a fallback-only replay also makes one lookup. I
retracted it and replaced it with the insert spy above, which caught M5.

### 6. Documentation

- **docs/12:**
  - "while it is held", and expired keys are freed from every row.
  - A new bullet, "The risk accepted in release 1", with its measured basis.
  - The `0009` bullet now says it refuses live pairs.
- **docs/16:**
  - Line 53: the invariant is qualified for 0007 inserts in the window.
  - Line 106: `idempotency_sub` can remain on a row whose key a 0007 pod's expiry cleared. Codex G was right; the f2c
    probe row shows it.
- **Citations:** 16 citations into `repo.py` in docs/14 and docs/16 moved, because `repo.py` grew 10 lines. I fixed them
  with the repository's own `scripts/doc-citations.py --relocate` in a scratch copy, then ran `--check`: 0 problems.
- **Decision record** (`docs/reviews/2026-11-23-issue-592/README.md`), Codex G's three claims corrected:
  - `change-pending` names the namespace holder.
  - The cost figures are now the measured ones.
  - The `.first()` ordering cannot undo two accepted writes.
  - A new section, "The second review", gives the rulings.
- **Left alone:** docs/04, the glossary and the OpenAPI header text. They already say "while it is held", which is true
  after fix 2. They describe the API that a pod of this version serves; the rollout behaviour is operational and belongs
  to docs/12. I did not adopt Codex's public-doc qualifications for that reason.
- **LIVE-DOC-EDITS** (`r2-outputs/LIVE-DOC-EDITS.md`): edits 1 and 2 stay true ("while it is held"). Edit 2 now says that
  a 0007 pod in the window leaves `idempotency_sub` empty. The header records the review. Edit 3 is unchanged.

## Test runs

Before means head2's code (`r2-work/before`, a copy of `head2/`). After means `r2/`. My own databases:

- `cmapi_r2_before`, `cmapi_r2_after`: the test runs.
- `cmapi_r2_mixed`, `cmapi_r2_mixed_after`: the mixed-version probes.
- `cmapi_r2_trigger`: the minimal-trigger probe.
- `cmapi_r2_plan`: the query plans.

I read none of the implementer's databases and changed none of them.

| Run | Before (2c663b8) | After (r2) | Output |
|---|---|---|---|
| The original 12-test file | 12 passed | (part of the next row) | `before-12-tests.txt` |
| The 592 file with reviewer 2's tests (19 test cases) | 3 failed (findings 2a, 2b and 3), 16 passed | 19 passed | `before-new-tests.txt`, `after-new-tests.txt` |
| `test_flow.py`, `test_review_a_concurrency.py`, `-k "idempotency or same_key"` | 5 passed | 5 passed | `before-flow-concurrency.txt`, `after-flow-concurrency.txt` |
| `test_data_model_doc.py`, `test_models_match_migrations.py`, `test_doc_citations.py`, `test_second_pass_converged.py` | 41 passed | 41 passed | `before-doc-schema-tests.txt`, `after-doc-schema-tests.txt` |
| Mutants M1 to M7 | | each caught | `mutants-r2.txt` |
| Mixed probe with 0007's code | f1a and f1b two 202s; f2a and f2b 409 forever; f2c 202 on 0007 | f1 unchanged (accepted); f2a and f2b 202 | `mixed-probe-before.txt`, `mixed-probe-after.txt` |
| Alt trigger: the 592 file, `test_models_match_migrations.py`, `test_data_model_doc.py`, `test_review_h_tools_migrate.py` | | 55 passed | `alt-trigger-tests.txt` |
| Minimal trigger, SQL by hand, with 0007's code | | the second 0007 write is 409 | `mixed-probe-minimal-trigger.txt` |
| Query plans, 200,000 rows | | see finding 4 | `plan-probe.txt` |

## What I ran and what I did not

**Ran:** everything in the table above, the mixed-version probe with 0007's code (before, after, and with the minimal
trigger), the seven mutants, the query plans, the psycopg diagnostics check, the citation check and relocate, and the
patch application check.

**Not run:**

- The full service suite.
- A concurrent race between pod versions (all probe steps are sequential).
- A rolling update on a cluster, or the rollout's duration on CRC.
- Anything on CRC, LDAP or Keycloak.
- The alt trigger with the mixed HTTP probe through Alembic (its SQL was probed by hand, and its migration through the
  test file).

**Tooling note:** `test_doc_citations.py` needs `git ls-files`, and the export is not a repository. I ran it in scratch
copies (`r2-work/cite-before`, `r2-work/cite-after`) where I ran `git init` and `git add`, with no commits. No existing
repository was touched.

## For the coordinator to file

1. **The expired key reserved forever (finding 2):** a defect in this PR, fixed by fix.diff. File it under fix-defect, as
   the mandate asks, and close it from #601.
2. **The 409 chosen by substring (finding 3):** a defect in this PR, fixed by fix.diff. File and close it the same way.
3. **#603 acceptance criterion:** `0009` must refuse while two rows that 0007 pods wrote in the window share a
   `key_owner` and a live key, and succeed once all but one of each pair are over 24 hours old. It then inverts
   `test_a_0007_insert_in_the_window_escapes_the_caller_index`. With the alt trigger, `0009` drops
   `cmapi_idempotency_caller` instead.
4. **For the owner, only if wanted:** accept the window risk (recommended), or apply `alt-minimal-trigger.diff`.
