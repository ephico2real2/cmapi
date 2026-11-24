# Reviewer 2 (Opus 5.5, high) on PR #630, `08ef716`, closes #603

I did not write this code. I checked each finding of reviewer 1 (Codex gpt-6.2-astra xhigh, `codex-result.txt`)
against the design record, the code and PostgreSQL 16.15 on `127.0.0.1:55432` (database `cmapi_603`, the probe in a
scratch schema of `cmapi_wt616`). The owner's expand-then-contract decision is not reopened.

- **The patch:** `r2-outputs/fix.diff` against `08ef716`. It applies with `patch -p1 -F0` from the repository root
  (`r2-outputs/patch-apply.txt`). Applied to a fresh copy of `head/`, it reproduces my working copy `r2/` byte for byte.
- **It changes:**
  - one model (`ck_cr_requester_kind` added, a comment corrected);
  - three test modules;
  - the 0009 docstring;
  - `docs/12`, `docs/16` and the decision record.
- **It does not change:** any migration statement, query or answer of the API.
- **Not changed:** `docs/01` and `docs/02`, so there is no `LIVE-DOC-EDITS.md`.

## Sources, fetched 2026-11-23/24

- **PostgreSQL 16, ALTER TABLE**, <https://www.postgresql.org/docs/16/sql-altertable.html>:
  - "Normally, this form will cause a scan of the table to verify that all existing rows in the table satisfy the new
    constraint."
  - "Although most forms of ADD table_constraint require an ACCESS EXCLUSIVE lock, ADD FOREIGN KEY requires only a
    SHARE ROW EXCLUSIVE lock."
  - "Adding a CHECK or NOT NULL constraint requires scanning the table to verify that existing rows meet the constraint,
    but does not require a table rewrite."
  - So 0009's `create_check_constraint` validates under the ACCESS EXCLUSIVE lock it already holds.
- **PostgreSQL 16, Explicit Locking**, <https://www.postgresql.org/docs/16/explicit-locking.html>:
  - ACCESS EXCLUSIVE "Conflicts with locks of all modes ... This mode guarantees that the holder is the only transaction
    accessing the table in any way".
  - "Only an ACCESS EXCLUSIVE lock blocks a SELECT (without FOR UPDATE/SHARE) statement."
  - "Once acquired, a lock is normally held until the end of the transaction."
  - "One should also ensure that the first lock acquired on an object in a transaction is the most restrictive mode that
    will be needed for that object."
- **PostgreSQL 16, LOCK**, <https://www.postgresql.org/docs/16/sql-lock.html>:
  - "LOCK TABLE is useless outside a transaction block".
  - "if multiple lock modes are involved for a single object, then transactions should always acquire the most
    restrictive mode first."
  - "LOCK TABLE obtains a table-level lock, waiting if necessary for any conflicting locks to be released."
- **PostgreSQL 16, lock_timeout**, <https://www.postgresql.org/docs/16/runtime-config-client.html>: "Abort any statement
  that waits longer than the specified amount of time while attempting to acquire a lock ... The time limit applies
  separately to each lock acquisition attempt." So the 30 s of `migrations/env.py` limits each wait, not the migration.
- **Transactional DDL.** The CREATE INDEX and DROP INDEX pages (quoted in the decision record) say the regular forms "can
  be performed within a transaction block" and the CONCURRENTLY forms cannot. That is what makes every refusal a full
  rollback. I measured it again: every refusal test compares every row, index, constraint and the revision before and
  after, and they pass.
- **Alembic 1.20.1, autogenerate**, <https://alembic.sqlalchemy.org/en/latest/autogenerate.html>: under "Autogenerate can
  optionally detect": "Named CHECK constraint additions and removals. This is off by default and must be enabled
  explicitly; the detection is name-based only and has significant limitations." This is why the parity test of the
  models missed finding 3; see the fix.

## The findings of reviewer 1

### 1. A round trip through 0007 can lose a caller-only row: narrowed. Documented and pinned by a test; no guard

**Reviewer 1 is right about the mechanism.**
- `0008.downgrade()` drops `idempotency_sub`, and `0008.upgrade()` rebuilds the caller from `requester`.
- A live delegated row whose caller is in `idempotency_sub` alone (the `g` shape that 0009 accepts) makes the upgrade
  refuse.

**The premise checked: no writer makes that shape.**
- `Pipeline.submit` sets `idempotency_sub=who.sub` (`core/pipeline.py:524-528`).
- `Requester.record()` writes `submittedBySub = caller.sub` whenever the person is not the caller
  (`core/identity/checks.py:59-65`). Otherwise `requester_sub = caller.sub`.
- So for every row cmapi writes, `idempotency_sub == COALESCE(requester->>'submittedBySub', requester_sub)`. That is
  exactly 0008's `_CALLER`, and the round trip rebuilds the same caller.
- 0007 pods also write `submittedBySub` (0008's `_CALLER` comment).
- 0008 and 0009 both refuse a live delegated row without it.
- So the shape arises only by hand-written SQL.
- The existing `test_keys_written_by_this_code_replay_after_a_schema_round_trip` proves the HTTP-written case. The "wrong
  caller" variant (a different populated `submittedBySub`) also needs hand-written SQL.

**What the failure looks like.** It is not silent. On the way up, 0008 refuses with the request ID, changes nothing, and
succeeds once the row is over 24 hours old. My test `test_a_round_trip_through_0007_takes_the_caller_from_requester`
measures exactly that.

**Ruling: a doc limit, not a guard.**
- The owner's rule is "over-build only if it is the only solution". A guard on `0008.downgrade()` protects only rows no
  writer makes.
- The worst case is a loud, self-clearing 24-hour refusal of the re-upgrade.
- What an operator rolling back to 0007 needs is a 0007 schema that 0007 code runs on, and a re-upgrade that never
  invents a caller. Both hold.
- A guard would also edit a shipped migration's downgrade for that reason only.

**Final code (in `fix.diff`):**
- `docs/12`, "Back to 0007", appended: "On the way up again, `0008` takes each live key's caller from `requester`, as it
  did the first time. For every row that cmapi writes, that is the caller that `idempotency_sub` held. A live delegated
  row whose caller was in `idempotency_sub` alone, with no `requester.submittedBySub`, makes `0008` refuse, changing
  nothing, until it is more than 24 hours old."
- A test in `test_idempotency_release2_603.py`:

```python
def test_a_round_trip_through_0007_takes_the_caller_from_requester(empty_schema):
    _run(empty_schema, "head")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "g-caller-only", requester_sub="sub-amy", key="k5", sub="sub-svc2", with_sub=True,
                requester={"requester": {"sub": "sub-amy"}, "automated": True, "submittedBy": "svc2"})
        _run(empty_schema, "0007", "--downgrade")
        before = _state(c)
        assert before[0] == {"g-caller-only": ("k5", "fp-g-caller-only", None)} and before[2] == "0007", before
        out = _refused(empty_schema, "head")
        assert "0008 refused, nothing changed: the live delegated requests g-caller-only hold an Idempotency-Key" in out, \
            out[-800:]
        assert _state(c) == before
        c.execute("UPDATE change_requests SET created_at = now() - interval '25 hours'")
        _run(empty_schema, "head")
        assert _state(c)[0] == {"g-caller-only": (None, None, None)}
```

This test characterizes behaviour; it is not a regression test. It passes before and after, because it pins the
documented limit and no code changes.
- **Evidence:** `r2-outputs/run-before.txt` (passes on head's code) and `r2-outputs/after-targeted-1.txt`.

### 2. The #612 opaque-key test passes with the substring defect restored: confirmed

**Measured.** I restored the substring classification in `RequestRepo.insert`:

```python
constraint = next((n for n in ("uq_cr_open_namespace", IDEMPOTENCY_INDEX) if n in str(exc.orig)), None)
```

- With head's tests, all 46 tests of the three modules pass (`r2-outputs/run-m5-old-test.txt`). The mutant survives.
- The router's retry after any 409 (`plugins/namespaces/router.py:111-116`) produces the asserted answer on its own.

**Final code:** reviewer 1's test, adopted with a docstring that says why the HTTP answer alone cannot tell. In
`test_idempotency_caller_592.py`:

```python
    real_insert, refused = RequestRepo.insert, []

    def record_refusal(self, *args, **kwargs):
        try:
            return real_insert(self, *args, **kwargs)
        except Problem as exc:
            refused.append((exc.status, exc.code, exc.detail))
            raise

    monkeypatch.setattr(RequestRepo, "insert", record_refusal)
    _first_lookup_misses(monkeypatch)
    other = client.post(URL, json={**OTHER, "onBehalfOf": "amy"}, headers=_service(keys, key))
    assert refused == [(409, "idempotency-replay", IN_USE)], refused
```

**Before and after:**
- With the mutant it fails, as reviewer 1 predicted (`r2-outputs/run-m5-substring-409.txt`):

  ```
  [(409, 'change-pending', 'the request that held ledger-dev has just finished; read the namespace again and resend the change')]
  ```

- It passes on the correct code (`after-targeted-1.txt`).

### 3. The model lacks `ck_cr_requester_kind`, and its comment overstates the CHECK: confirmed, and widened

**Confirmed.**
- `0001_cmapi_schema.py:54` creates `ck_cr_requester_kind`, which `models.py` did not declare.
- The comment said `idempotency_sub` is null "exactly when" there is no key. It is wrong for a row where a 0007 pod's
  expiry cleared the key and left the subject (`docs/16`, line 106, says so).

**Widened: the parity test was blind to every CHECK constraint, not only this one.**
- Alembic compares CHECKs only when enabled, and then by name (the source above). So `test_models_match_migrations.py`
  could not catch the missing CHECK. It also could not catch removing `ck_cr_idempotency_caller` from the model (the
  "removing only the model declaration" mutant that reviewer 1 named).
- Measured: with that model line deleted, head's tests pass (`r2-outputs/run-m1b-old-test.txt`, 42 passed).
- Reviewer 1's hard-coded test catches these two names only. I replaced it with a structural comparison:
  - every constraint of every table, via `pg_get_constraintdef`;
  - between the migrated schema and a schema made from the models alone;
  - by the same mechanism the file already uses for index predicates.
- It catches a missing CHECK and a changed CHECK expression.
- Enabling Alembic's optional CHECK plugin would touch `migrations/env.py` at runtime and still compare by name only.

**Final code:**
- `models.py`:

```python
    __table_args__ = (
        CheckConstraint("requester_kind IN ('user', 'service')", name="ck_cr_requester_kind"),
        CheckConstraint("idempotency_key IS NULL OR idempotency_sub IS NOT NULL", name="ck_cr_idempotency_caller"),
    )
    ...
    # migration 0008). Never null on a row that holds a key (ck_cr_idempotency_caller, 0009). A row with no key may keep
    # one: a 0007 pod's expiry cleared the key and left it (docs/16).
```

- `test_models_match_migrations.py` (abridged; the full text is in `fix.diff`):

```python
def constraint_definitions(connection, schema: str) -> dict[str, str]:
    rows = connection.execute(text("""
        select c.relname || '.' || k.conname, pg_get_constraintdef(k.oid) from pg_constraint k
          join pg_class c on c.oid = k.conrelid join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = :s"""), {"s": schema})
    return {name: definition.replace(f"{schema}.", "") for name, definition in rows}

def test_each_constraint_of_the_models_is_the_constraint_of_the_migrations_checks_included(database):
    migrated, modelled = models_schema(database, Base.metadata, constraint_definitions)
    migrated.pop("alembic_version.alembic_version_pkc", None)
    assert modelled == migrated

@pytest.mark.parametrize("table, name", [("change_requests", "ck_cr_requester_kind"),
                                         ("change_requests", "ck_cr_idempotency_caller"),
                                         ("policy_rejections", "ck_rej_request")])
def test_a_check_of_the_migrations_that_the_models_do_not_declare_is_found(database, table, name):
    ...  # removes it from a copy of the models; alembic check sees nothing, the comparison does
```

- `docs/16`, "The models and the migrations agree", gains one row with the Alembic quote.

**Before and after:**
- Before, on head's model, two tests fail (`r2-outputs/run-before.txt`):
  - `test_each_constraint_...`, with a diff showing `change_requests.ck_cr_requester_kind` missing from the models;
  - `[change_requests-ck_cr_requester_kind]`.
- After, they pass (`after-targeted-1.txt`).
- The model mutant (m1b) now fails two tests (`run-m1b-no-model-check.txt`).
- The comparison of primary keys, foreign keys and unique constraints also passed, so their names agree too.

### 4. The rollout summary contradicts the boundary: confirmed

**Confirmed.**
- `docs/12`, lines 76-79, said 0009 ships once no pod "of the release before it" runs. That release is 0008, whose pods
  may keep running.
- It also said that any rolled-back image keeps running on a later schema. A 0007 image does not on 0009: every keyed
  write breaks the CHECK.

**Final code (`docs/12`):**

> **Migrations** are expand-only, except the contract step of a change made in two releases, such as `0009` below. A
> contract step ships only once no pod older than its expand step runs: for `0009`, no 0007 pod, while release 1
> (`0008`) pods keep serving beside it. An image rolled back to a release that has the expand step keeps running on a
> later schema (the old migrator exits 0 on a later four-digit revision, and `/readyz` counts it as ready). An image
> older than the expand step passes the same two checks but does not work, as "After `0009`" below says. A divergent or
> unknown revision is refused by both. Nothing rolls a data migration back by itself.

There is no automated test for the prose: `deploy/tests/doc12-test.py` does not read this section.

**The two smaller wording corrections, both confirmed and applied:**
- **Lock order.** The decision record said "taking it first adds no blocking". That is not so. The SELECT and UPDATE of
  the checks and the fill would otherwise take only ACCESS SHARE and ROW EXCLUSIVE. With the lock first, readers queue
  from the first statement. That follows from "Only an ACCESS EXCLUSIVE lock blocks a SELECT".
  - The lock order is still right, for the race and by the LOCK page's "most restrictive mode first".
  - Corrected in the 0009 docstring step 1 and the decision record row.
- **"202" overstated.** The other caller's new request goes through the usual checks. A held namespace is still 409
  `change-pending`: `test_the_person_cannot_replay_the_service_request_with_its_key` asserts it.
  - Also, "no caller could learn of another's request from the 409" understated the old 409. It disclosed that the key
    was held, though not by which request.
  - Corrected in the 0009 docstring, `docs/12` and the decision record.

### Reviewer 1's other points

- **The two residual coverage gaps: confirmed with mutants, and closed.**
  - **0009's own `_LIVE` changed from `>=` to `>` (m6).** It survives head's tests (`run-m6-old-test.txt`, 27 passed).
    - Fix: the 24-hour edge test now reads the constants of both 0008 and 0009 through `_migration(name)`, which replaces
      `_migration_0008()`.
    - The mutant now fails (`run-m6-live-gt.txt`).
  - **0009's `_DELEGATED_WITHOUT_CALLER` reduced to `NOT requester ? 'submittedBySub'` (m7).** It survives head's tests
    (`run-m7-old-test.txt`, 27 passed).
    - Fix: `test_the_upgrade_refuses_each_shape_of_an_unknown_caller_and_changes_nothing`, run on 0009 with a JSON null,
      a number and an empty string.
    - The mutant now fails all three (`run-m7-ambiguity-no-type.txt`).
- **The provenance sentence of `docs/16`, line 256: confirmed.** It now names 0008 (#592) and 0009 (#603).
- **(f) Release 1's SQL on 0009 was not measured: now measured** (`r2-outputs/release1-sql-on-0009.txt`). This is my
  derivative of head's `size_probe.py`, on the same 200,000 rows.
  - On 0009, release 1's expiry UPDATE and its `key_owner` SELECT use an index scan of `uq_cr_idempotency_caller` on its
    trailing column:
    - 1,096 buffers each;
    - 26.3 ms and 13.7 ms.
  - On 0008 they took 771 buffers each, 22.0 ms and 33.2 ms.
  - Neither falls back to a sequential scan. The mixed-version window costs about the same per lookup as release 1
    already did.
  - In this run, 0009 took `transaction_seconds` 7.96 and its downgrade 3.30.
  - Measured on a laptop with another agent's suite running (load about 8 to 10).
- **(c) Physical retention is unbounded: confirmed, and not a defect of this PR.** It was lazy in release 1 and on 0007
  too. Nothing reads a stale key, since every lookup clears the caller's own expired row first. No issue proposed.
- **The refusal diagnostics: confirmed.** The `migrate_failed` event carries `RuntimeError` and `sqlstate=null`, and
  the traceback names the rows. #617's restriction on the event's fields is kept.

## The requested mutants, run on PostgreSQL 16.15 against my patched tests

Each tree is `r2/cmapi` with one change, plus a link to `head/examples`. Each ran the three modules `603`, `592` and
`models_match` (46 tests); the old-test trees use head's versions of the modules they swap.

| Mutant | Killed by | Evidence |
|---|---|---|
| m1: drop the CHECK from 0009 (and its downgrade drop) | `test_the_upgrade_fills_..._keeps_only_the_caller_index`, `test_a_0007_insert_in_the_window_no_longer_escapes_the_caller_index` | `run-m1-no-check.txt` |
| m1b: drop the CHECK from the model only | the two new constraint tests (head's tests: survives, `run-m1b-old-test.txt`) | `run-m1b-no-model-check.txt` |
| m2: remove upgrade refusal (b) | `test_the_upgrade_refuses_a_live_collision_under_the_caller_...`, `test_a_0007_insert_in_the_window_...` | `run-m2-no-collision-refusal.txt` |
| m3: expiry without the sub filter | `test_the_lookup_and_its_expiry_..._caller_index`, `test_the_person_can_use_a_key_that_a_service_held_...`, `test_a_service_can_use_a_key_that_the_person_held_...` | `run-m3-expiry-all-callers.txt` |
| m4: downgrade without its refusal | `test_the_downgrade_refuses_a_live_pair_of_one_requester_...` | `run-m4-downgrade-no-refusal.txt` |
| m5: substring 409 (#612) | the rewritten `test_a_key_named_after_an_index_is_an_opaque_key` (head's test: survives, `run-m5-old-test.txt`) | `run-m5-substring-409.txt` |
| m6: 0009 `_LIVE` with `>` | the 24-hour edge test (head's tests: survive, `run-m6-old-test.txt`) | `run-m6-live-gt.txt` |
| m7: 0009 ambiguity without the type and empty checks | the new parametrized test, 3 of 3 (head's tests: survive, `run-m7-old-test.txt`) | `run-m7-ambiguity-no-type.txt` |

`r2-outputs/first-attempt-no-examples/` holds a first pass that I ran without `examples/` linked. Its 14 `world` tests
errored in every tree; I disregarded it.

## What reviewer 1 missed

1. **Alembic's parity check is blind to every CHECK, not only to `ck_cr_requester_kind`.**
   - Reviewer 1's test hard-codes two names.
   - The structural constraint comparison above covers every table and constraint kind, and catches changed expressions.
   - Full code: finding 3.
2. **Reviewer 1 did not measure that its two residual gaps survive.** It predicted them. m6 and m7 survive head's tests
   (27 passed each); both are now killed. Full code: "Reviewer 1's other points".
3. **The "0007 round trip" premise.** Reviewer 1 offered a guard or a doc. It did not establish that no writer can produce
   the shape, or that the failure is a loud refusal rather than a silent loss. Both are now established and tested
   (finding 1).
4. **Release 1's SQL on 0009 is now measured** (f), rather than left as a qualification.

There are no defects outside this PR to file.

## Runs on my patched copy (`r2/`)

All runs used PostgreSQL 16.15 at `127.0.0.1:55432`, behind the gate (`r2-outputs/gate.sh`, run by `r2-outputs/run.sh`).

| Run | Result | Evidence |
|---|---|---|
| #603, #592 (with #611 and #612), the migration modules (`test_migrate_log_614.py`, `test_review_h_tools_migrate.py`), `test_models_match_migrations.py`, `test_data_model_doc.py` | 80 passed | `after-targeted-1.txt` |
| `test_api_standard.py`, `test_api_docs.py`, `test_api_samples.py` | 206 passed | `after-api-standard.txt` |
| The whole service suite, once, at the end (2026-11-24T08:11:54Z to 08:47:11Z) | 2580 passed, 2 failed (both from the export having no `.git`; see below) | `full-suite.txt` |
| The failed citation test again, with `git ls-files` shimmed by `find` | 1 passed | `doc-citations-test-with-shim.txt` |
| `deploy/tests/doc12-test.py` | 0 failed, rc 0 | `doc12-test.txt` |
| `scripts/doc-citations.py --check`, with `git ls-files` shimmed by `find` (`r2-outputs/shim/git`) | 0 problems | `doc-citations.txt` |
| `patch -p1 -F0 < r2-outputs/fix.diff` on a fresh copy of head | applies; the result equals `r2/` | `patch-apply.txt` |

**The two failures of the full suite.** Both call `git` in an export that has no `.git`, which exits 128:
- **`test_doc_citations.py::test_each_citation_of_the_documents_is_the_text_that_was_recorded_for_it`.** It runs
  `git -C <root> ls-files`. With the `find` shim on PATH it passes (`doc-citations-test-with-shim.txt`), as does
  `scripts/doc-citations.py --check`. The other 11 tests of that module use their own `git init` and passed in the full
  suite.
- **`test_third_pass_converged.py::test_every_shell_script_under_examples_and_deploy_is_executable`.** It needs
  `git ls-files -s` (file modes), which a shim cannot honestly give. The patch adds no file and changes no file mode, so
  it cannot affect this test. The coordinator's run in the worktree is its proof.

**Not tested:**
- CRC;
- a real rolling update;
- 0007's own code on 0009 (as in the implementer's record).
