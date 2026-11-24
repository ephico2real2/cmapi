[codex] Starting Codex task thread.
[codex] Thread ready (01a20bfd-fa79-7ab3-904e-d9b3663c17b9).
[codex] Turn started (01a20bfd-fe18-7903-bfd1-e8ae3ac40ca2).
[codex] Assistant message captured: I’ll compare the exported revisions, trace the migration and write paths, and run the availab...
[codex] Searching:
[codex] Running command: /bin/zsh -lc "cd /Users/olasumbo/gitRepos/workbench/cmapi/review-630 && ls -a && lsd='' && rg...
[codex] Command completed: /bin/zsh -lc "cd /Users/olasumbo/gitRepos/workbench/cmapi/review-630 && ls -a && lsd='' && rg... (exit 0)
[codex] Running command: /bin/zsh -lc 'cd head && nl -ba cmapi/tests/service/test_idempotency_release2_603.py'
[codex] Command completed: /bin/zsh -lc 'cd head && nl -ba cmapi/tests/service/test_idempotency_release2_603.py' (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && rg -n '0009|idempotency_sub|uq_cr_idempotency|expired|30 s' docs/{04...
[codex] Command completed: /bin/zsh -lc "cd head && rg -n '0009|idempotency_sub|uq_cr_idempotency|expired|30 s' docs/{04... (exit 0)
[codex] Running command: /bin/zsh -lc 'cd head/cmapi/src/cmapi/core/db && for f in migrations/versions/*.py; do echo "...
[codex] Command completed: /bin/zsh -lc 'cd head/cmapi/src/cmapi/core/db && for f in migrations/versions/*.py; do echo "... (exit 0)
[codex] Running command: /bin/zsh -lc 'cd head && nl -ba cmapi/src/cmapi/core/db/migrate.py && nl -ba cmapi/src/cmapi/...
[codex] Command completed: /bin/zsh -lc 'cd head && nl -ba cmapi/src/cmapi/core/db/migrate.py && nl -ba cmapi/src/cmapi/... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && nl -ba cmapi/src/cmapi/core/db/models.py | head -110 && nl -ba cmapi...
[codex] Command completed: /bin/zsh -lc "cd head && nl -ba cmapi/src/cmapi/core/db/models.py | head -110 && nl -ba cmapi... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && rg -n 'key|dry_run|requester|\\.submit\\(' cmapi/src/cmapi/{core/pip...
[codex] Command completed: /bin/zsh -lc "cd head && rg -n 'key|dry_run|requester|\\.submit\\(' cmapi/src/cmapi/{core/pip... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && rg -n 'idempotency_key|idempotency-key|Idempotency-Key' cmapi/src | ...
[codex] Command completed: /bin/zsh -lc "cd head && rg -n 'idempotency_key|idempotency-key|Idempotency-Key' cmapi/src | ... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && rg -n 'pytest|tmp_path|DB_URL|autouse' cmapi/tests/service/{conftest...
[codex] Command completed: /bin/zsh -lc "cd head && rg -n 'pytest|tmp_path|DB_URL|autouse' cmapi/tests/service/{conftest... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && nl -ba docs/12-existing-postgresql.md | sed -n '99,172p' && nl -ba c...
[codex] Command completed: /bin/zsh -lc "cd head && nl -ba docs/12-existing-postgresql.md | sed -n '99,172p' && nl -ba c... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head/cmapi && nl -ba src/cmapi/plugins/namespaces/router.py | sed -n '70,126...
[codex] Command completed: /bin/zsh -lc "cd head/cmapi && nl -ba src/cmapi/plugins/namespaces/router.py | sed -n '70,126... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head/cmapi && sed -n '51,99p' tests/service/conftest.py && cat tests/service...
[codex] Command completed: /bin/zsh -lc "cd head/cmapi && sed -n '51,99p' tests/service/conftest.py && cat tests/service... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && rg -n 'CheckConstraint|uq_cr_idempotency' cmapi/src/cmapi/core/db/mo...
[codex] Command completed: /bin/zsh -lc "cd head && rg -n 'CheckConstraint|uq_cr_idempotency' cmapi/src/cmapi/core/db/mo... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head/cmapi && nl -ba src/cmapi/plugins/namespaces/router.py | sed -n '73,127...
[codex] Command completed: /bin/zsh -lc "cd head/cmapi && nl -ba src/cmapi/plugins/namespaces/router.py | sed -n '73,127... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && nl -ba cmapi/src/cmapi/core/db/migrations/versions/0009* | sed -n '6...
[codex] Command completed: /bin/zsh -lc "cd head && nl -ba cmapi/src/cmapi/core/db/migrations/versions/0009* | sed -n '6... (exit 0)
[codex] Running command: /bin/zsh -lc 'cd head/cmapi && PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYT...
[codex] Command completed: /bin/zsh -lc 'cd head/cmapi && PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYT... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && nl -ba cmapi/tests/service/test_idempotency_caller_592.py | sed -n '...
[codex] Command completed: /bin/zsh -lc "cd head && nl -ba cmapi/tests/service/test_idempotency_caller_592.py | sed -n '... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && nl -ba cmapi/src/cmapi/core/identity/checks.py | head -190 && nl -ba...
[codex] Command completed: /bin/zsh -lc "cd head && nl -ba cmapi/src/cmapi/core/identity/checks.py | head -190 && nl -ba... (exit 0)
[codex] Running command: /bin/zsh -lc 'cd head/cmapi && PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYT...
[codex] Command failed: /bin/zsh -lc 'cd head/cmapi && PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYT... (exit 1)
[codex] Running command: /bin/zsh -lc "cd head && nl -ba cmapi/tests/service/test_idempotency_caller_592.py | sed -n '...
[codex] Command completed: /bin/zsh -lc "cd head && nl -ba cmapi/tests/service/test_idempotency_caller_592.py | sed -n '... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && nl -ba cmapi/src/cmapi/routers/__init__.py | sed -n '58,93p' && nl -...
[codex] Command completed: /bin/zsh -lc "cd head && nl -ba cmapi/src/cmapi/routers/__init__.py | sed -n '58,93p' && nl -... (exit 0)
[codex] Assistant message captured: The exported code confirms the requester index covered every keyed row through 0008. I also f...
[codex] Running command: /bin/zsh -lc "cd head && rg --files | rg 'test_api_(standard|docs|samples)|doc12-test' && sed...
[codex] Command completed: /bin/zsh -lc "cd head && rg --files | rg 'test_api_(standard|docs|samples)|doc12-test' && sed... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && rg -n 'class Problem|def conflict' cmapi/src/cmapi/core/errors.py &&...
[codex] Command completed: /bin/zsh -lc "cd head && rg -n 'class Problem|def conflict' cmapi/src/cmapi/core/errors.py &&... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && nl -ba cmapi/src/cmapi/core/db/migrations/versions/0009* | head -51 ...
[codex] Command completed: /bin/zsh -lc "cd head && nl -ba cmapi/src/cmapi/core/db/migrations/versions/0009* | head -51 ... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && rg -n '"'^[''^#]*(CheckConstraint|Index'"\\()' cmapi/src/cmapi/core/...
[codex] Command completed: /bin/zsh -lc "cd head && rg -n '"'^[''^#]*(CheckConstraint|Index'"\\()' cmapi/src/cmapi/core/... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && rg -n 'Data model|idempotency|0009' cmapi/tests/service/test_data_mo...
[codex] Command failed: /bin/zsh -lc "cd head && rg -n 'Data model|idempotency|0009' cmapi/tests/service/test_data_mo... (exit 1)
[codex] Running command: /bin/zsh -lc "cd head/cmapi && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/olasumbo/gitRe...
[codex] Command completed: /bin/zsh -lc "cd head/cmapi && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/olasumbo/gitRe... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && cat cmapi/tests/service/test_data_model_doc.py | head -90 && rg -n '...
[codex] Command completed: /bin/zsh -lc "cd head && cat cmapi/tests/service/test_data_model_doc.py | head -90 && rg -n '... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && rg -in 'purge|prun|retention|indefinit' docs/16-data-model.md | head...
[codex] Command completed: /bin/zsh -lc "cd head && rg -in 'purge|prun|retention|indefinit' docs/16-data-model.md | head... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && cat docs/reviews/2026-11-23-issue-603/outputs/targeted-after-{1,2}.t...
[codex] Command completed: /bin/zsh -lc "cd head && cat docs/reviews/2026-11-23-issue-603/outputs/targeted-after-{1,2}.t... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && nl -ba docs/reviews/2026-11-23-issue-603/outputs/release-1-code-on-0...
[codex] Command completed: /bin/zsh -lc "cd head && nl -ba docs/reviews/2026-11-23-issue-603/outputs/release-1-code-on-0... (exit 0)
[codex] Running command: /bin/zsh -lc "cd head && rg -n 'def ready|schema_status' cmapi/src/cmapi | head -12 && rg -n ...
[codex] Command failed: /bin/zsh -lc "cd head && rg -n 'def ready|schema_status' cmapi/src/cmapi | head -12 && rg -n ... (exit 1)
[codex] Assistant message captured: # Reviewer 1 — cmapi PR #630, `08ef716` **Verdict:** The 0008 → 0009 contract step is correct...
[codex] Turn completed.
# Reviewer 1 — cmapi PR #630, `08ef716`

**Verdict:** The 0008 → 0009 contract step is correct under the owner’s deployment precondition. I would keep both upgrade refusals, the caller CHECK, the caller-scoped expiry, and the removal of the requester index. **No third refusal is warranted.**

I found one data-preservation exception in the *further* downgrade through 0007, a regression test that can pass with the #612 defect restored, and a pre-existing model/schema mismatch. The operator documentation also overstates the rollout restriction in one place. None requires changing the 0009 uniqueness decision.

I reviewed the export read-only. I used the supplied Python, collected 47 tests across the four changed service-test modules, and ran the two that do not require a working PostgreSQL server. Both passed. One database test reached fixture setup and received `Operation not permitted` connecting to `127.0.0.1:55432`. The exact outstanding IDs are below. Reported PostgreSQL measurements from the PR are identified separately from my runs.

Paths below are relative to `head/` unless prefixed `base/`. `0008` and `0009` refer to their files in `cmapi/src/cmapi/core/db/migrations/versions/`.

## Findings and fixes

### 1. The 0007 round trip can discard the only surviving copy of a live caller

**Evidence:** `cmapi/tests/service/test_idempotency_release2_603.py:58–59,74` explicitly treats `g-release-1-caller-only` as valid. It has `idempotency_sub='sub-svc2'`, requester `sub-amy`, a delegation marker, and no `requester.submittedBySub`. `0009:116–126` correctly preserves this row on downgrade to 0008. `0008:98–100` then drops the caller column. Going up again, `0008:69–77` refuses the row because the service subject is gone. A row with a *different*, populated JSON subject can instead be reconstructed under the wrong caller at `0008:93`.

**Failure scenario:** Downgrade a database containing the PR’s `g` fixture from 0009 to 0007. The command succeeds. Immediately migrate back to head. The previously usable service key now blocks the upgrade. The existing round-trip test passes because both of its rows came from `Requester.record()`, which writes the delegated subject into JSON (`core/identity/checks.py:59–65`, `test_idempotency_caller_592.py:477–505`). I found no current application writer that creates the `g` shape. The distinction matters because the PR explicitly accepts that stored shape.

**Fix:** Keep the 0009 → 0008 downgrade as written. If the round-trip guarantee extends to the accepted caller-only rows, guard the step that destroys the information. This is a complete replacement for `0008.downgrade()` in the migrator distributed with this release. An already-shipped 0008 binary would, of course, still have its original downgrade.

```python
def downgrade() -> None:
    op.execute("LOCK TABLE change_requests IN ACCESS EXCLUSIVE MODE")
    blocked = op.get_bind().execute(sa.text(f"""
        SELECT request_id
          FROM change_requests
         WHERE {_LIVE}
           AND idempotency_sub IS NOT NULL
           AND (
               idempotency_sub IS DISTINCT FROM {_CALLER}
               OR (
                   (requester ? 'submittedBy' OR requester ? 'submittedByClient')
                   AND (
                       jsonb_typeof(requester->'submittedBySub')
                           IS DISTINCT FROM 'string'
                       OR requester->>'submittedBySub' = ''
                   )
               )
           )
         ORDER BY request_id
    """)).scalars().all()
    if blocked:
        raise RuntimeError(
            "0008 downgrade refused, nothing changed: 0007 cannot preserve "
            "the live caller of requests " + ", ".join(blocked)
            + ". Retry after those keys expire."
        )
    op.drop_index("uq_cr_idempotency_caller", table_name="change_requests")
    op.drop_column("change_requests", "idempotency_sub")
```

**Regression test** for `test_idempotency_release2_603.py`. On the submitted code `_refused` fails because the destructive downgrade succeeds. With the guard the entire multi-revision command rolls back, including the 0009 downgrade.

```python
def test_down_to_0007_preserves_a_live_caller_only_row(empty_schema):
    _run(empty_schema, "head")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(
            c, "caller-only", requester_sub="sub-amy", key="k",
            sub="sub-svc2", with_sub=True,
            requester={"requester": {"sub": "sub-amy"}, "submittedBy": "svc2"},
        )
        before = _everything(c)
        out = _refused(empty_schema, "0007", "--downgrade")
        assert "0007 cannot preserve the live caller of requests caller-only" in out
        assert _everything(c) == before

        c.execute("UPDATE change_requests SET created_at = now() - interval '25 hours'")
        _run(empty_schema, "0007", "--downgrade")
        _run(empty_schema, "head")
        assert _state(c)[0]["caller-only"] == (None, None, None)
```

If only application-generated rows are within the 0007 rollback guarantee, the narrower fix is to document that limit at `docs/12-existing-postgresql.md:123–124`: “0008 drops `idempotency_sub` on downgrade to 0007. A later upgrade can reconstruct a live caller only from the requester fields retained at 0007. A live row whose caller exists only in `idempotency_sub` must age out before this downgrade.” **The 0009 → 0008 guarantee needs no such qualification.**

### 2. The rewritten opaque-key test can pass with the wrong 409 branch

**Evidence:** `cmapi/tests/service/test_idempotency_caller_592.py:239–253` makes only the first lookup miss. `cmapi/src/cmapi/plugins/namespaces/router.py:111–116` retries the lookup after **any** 409. On that second lookup the fingerprint differs, so `router.py:94–96` produces the asserted `idempotency-replay` and winner ID itself.

**Failure scenario:** Restore substring matching in `core/db/repo.py:176–187`. PostgreSQL’s DETAIL contains the user’s key `uq_cr_open_namespace`. `insert` incorrectly reports `change-pending`. The router catches it, performs the second lookup, and produces exactly the response the test expects. The current production classification is correct. The test does not establish that fact.

**Full test fix:** Observe the exception at the repository boundary and keep the HTTP assertion for the retry. This replaces the existing test and uses its existing helpers.

```python
def test_a_key_named_after_an_index_is_an_opaque_key(world, monkeypatch):
    from cmapi.core.errors import Problem

    client, ctx, *_rest, keys = world
    _directory(ctx)
    key = "uq_cr_open_namespace"
    first = client.post(
        URL, json={**NS, "onBehalfOf": "ola"}, headers=_service(keys, key)
    )
    assert first.status_code == 202, first.text

    real_insert = RequestRepo.insert
    refused = []

    def record_refusal(self, *args, **kwargs):
        try:
            return real_insert(self, *args, **kwargs)
        except Problem as exc:
            refused.append((exc.status, exc.code, exc.detail))
            raise

    monkeypatch.setattr(RequestRepo, "insert", record_refusal)
    _first_lookup_misses(monkeypatch)
    other = client.post(
        URL, json={**OTHER, "onBehalfOf": "amy"}, headers=_service(keys, key)
    )
    assert refused == [(409, "idempotency-replay", IN_USE)]
    assert other.status_code == 409 and other.json()["code"] == "idempotency-replay"
    assert other.json()["requestId"] == first.json()["requestId"]
```

The new repository assertion fails with the substring mutant and passes with `diag.constraint_name`. This is distinct from the four migration/expiry mutants requested below.

### 3. `ChangeRequestRow` omits a real CHECK and its caller comment claims a stronger invariant than the database enforces

**Evidence:** `0001_cmapi_schema.py:54` installs `ck_cr_requester_kind`. `docs/16-data-model.md:371–372` shows both checks on the migrated table. `cmapi/src/cmapi/core/db/models.py:29–31` declares only the caller check. I imported the exported metadata and found exactly that one `ChangeRequestRow` CHECK. `models.py:55` also says the caller is null “exactly when” there is no key. `0009:111–112` enforces only one implication. `docs/16-data-model.md:106` correctly describes a historical exception.

**Failure scenario:** A schema created by `Base.metadata.create_all()` accepts `requester_kind='other'`, which the migrated schema rejects. The parity tests at `test_models_match_migrations.py:48–54,86–108` can remain green: the explicit PostgreSQL definition comparison covers indexes. Separately, a historical row with a cleared key and a retained subject remains legal after 0009. A maintainer following the model comment could incorrectly tighten the CHECK and reject such rows.

**Fix:** Yes, declare `ck_cr_requester_kind` in the model. No database migration is needed. Replace `__table_args__` and the comment above `idempotency_sub` with:

```python
    __table_args__ = (
        CheckConstraint(
            "requester_kind IN ('user', 'service')",
            name="ck_cr_requester_kind",
        ),
        CheckConstraint(
            "idempotency_key IS NULL OR idempotency_sub IS NOT NULL",
            name="ck_cr_idempotency_caller",
        ),
    )
```

```python
    # A keyed row names the token subject that sent it. A keyless historical
    # row may retain its subject after a 0007 pod cleared its key.
    idempotency_sub: Mapped[str | None] = mapped_column(String(100))
```

**Regression test:** This runs without PostgreSQL and fails on the exported metadata.

```python
def test_change_request_models_declare_both_migrated_checks():
    from sqlalchemy import CheckConstraint
    from cmapi.core.db.models import ChangeRequestRow

    actual = {
        c.name: str(c.sqltext)
        for c in ChangeRequestRow.__table__.constraints
        if isinstance(c, CheckConstraint)
    }
    assert actual == {
        "ck_cr_requester_kind": "requester_kind IN ('user', 'service')",
        "ck_cr_idempotency_caller":
            "idempotency_key IS NULL OR idempotency_sub IS NOT NULL",
    }
```

### 4. The rollout summary contradicts the actual compatibility boundary

**Evidence:** `docs/12-existing-postgresql.md:76–79` says 0009 ships only once no pod “of the release before it” runs. The release immediately before 0009 is 0008. Lines 100 and 115–118 correctly allow 0008 pods and exclude 0007. The generic image-rollback assurance at line 77 also reads more broadly than the specific warning at line 117.

**Failure scenario:** An operator reading the opening rule could stop healthy 0008 replicas before migrating, or take the general rollback assurance to cover a 0007 image on 0009.

**Full replacement for lines 76–79:**

> Migrations normally expand the schema. Migration 0009 contracts it after release 1 has reached every replica and all 0007 pods have stopped. During the 0009 rollout, 0008 and 0009 pods can serve against the migrated schema. An image-only rollback to 0008 is supported. Returning to 0007 requires a compatible schema downgrade. A later four-digit revision can pass the old image’s readiness check even when its writer is incompatible.

**Acceptance test:** Read the opening rule against the two mixed-version cases. With a running 0008 replica and zero 0007 replicas, it must permit migration to 0009. With a running 0007 replica, it must require waiting. The existing first sentence fails the first case. The database-side evidence for the distinction is `test_idempotency_release2_603.py:264–280` and the base writer at `core/pipeline.py:524–528`.

Two smaller wording corrections belong with this edit:

- `0009:13–15` and the decision record at `docs/reviews/2026-11-23-issue-603/README.md:52` imply taking the strong lock first adds no blocking. Replace that claim with “Taking the final lock mode first closes the race before the refusal scans and avoids a lock upgrade. Readers and writers can queue from this first statement until the transaction ends.” A reader arriving during the refusal scan distinguishes the two lock timings. The shipped lock order is correct.
- `0009:24–27`, the decision record at line 55, and `docs/12-existing-postgresql.md:110–114` should describe a *permitted insert*, not an unconditional 202 or absence of any disclosure. Use “Another caller can submit the same key for the same requester, subject to the normal request checks and namespace lock. The old idempotency 409 omitted the request ID but indicated the key was occupied.” The existing regression at `test_idempotency_caller_592.py:151–169` supplies both cases: the occupied namespace gives `change-pending` and a different available namespace gives 202.

## Contract checks

**(a) Requester uniqueness — confirmed.** `0001_cmapi_schema.py:39–45,60–61` makes `requester_sub` `NOT NULL` and creates a unique `(requester_sub, idempotency_key)` index predicated solely on `idempotency_key IS NOT NULL`. The predicate includes expired keys that still occupy a row. Revisions 0002:17–18, 0003:19–20, 0004:21–22, 0005:24–35, 0006:24–54 and 0007:18–19 touch approvals, jobs, the namespace index, policy rejections or request-event time. None relaxes requester nullability or drops this index. `0008:88–95` adds the caller column/index and retains the requester index.

`models.py:48` agrees. The production constructor sets `requester_sub=plan.requester.sub` at `core/pipeline.py:520–531`. `core/identity/checks.py:49–53` rejects a missing person subject, including a directory entry lacking one. A raw INSERT, COPY or UPDATE against this schema is subject to the same database constraint. I found no application bypass. Thus two stored **keyed** rows cannot share the requester/key pair before 0009. Dropping the index itself changes no row. The migration’s preceding clear and fill deliberately do change rows. A new request by another caller is the case the drop admits, including two different services writing for the same person. A stored live retry retains its owner or the upgrade refuses. **The decision to proceed with live delegated keys is confirmed.**

**(b) CHECK and writers — confirmed.** `0009:109–113` fills the missing subjects, installs `key IS NULL OR sub IS NOT NULL`, then drops the old index. Both operands are `IS NULL` tests with Boolean results. A keyed/null-caller row cannot escape via SQL’s unknown truth value. The allowed keyless/non-null-caller case is intentional.

The following write paths are shared by the base and head exports:

| Path | Evidence |
|---|---|
| Create, update, delete | `plugins/namespaces/router.py:76–83,271–279,324–333,353–362` rejects an absent or empty real-write key and exits before submit on dry run. |
| `:extend`, `:set`, `:makePermanent` | `router.py:369–385,407,421–422,434` routes all three through `_expiry_write`, with the same key validation and dry-run exit. |
| Self and delegated submission | `core/identity/checks.py:59–65,82–95` records the person and the submitting identity. `core/pipeline.py:524–528` takes `idempotency_sub` from `who.sub` even when the requester is someone else. Authentication requires the `sub` claim at `core/auth.py:166`. |
| Internal revert | `jobs/open_pr.py:107` passes `idempotency_key=None`. This row satisfies the CHECK. |
| Expiry UPDATE | `base/.../core/db/repo.py:148–152` and `head/.../core/db/repo.py:137–141` clear key, fingerprint and subject in the same UPDATE. |

Every current production keyed insert I found reaches that constructor. A dry run with an Idempotency-Key still creates no change request. The 0007-shaped direct insert in `test_idempotency_release2_603.py:269–280` demonstrates why the database guard matters.

PostgreSQL 16 says adding the constraint “will cause a scan of the table” and that “most forms of `ADD table_constraint` require an `ACCESS EXCLUSIVE` lock”. This CHECK is added validated, so the scan runs inside the already-held lock. [PostgreSQL 16, ALTER TABLE, ADD table_constraint](https://www.postgresql.org/docs/16/sql-altertable.html)

**(c) Caller-scoped expiry — confirmed for correctness. Physical retention is unbounded.** `core/db/repo.py:137–142` uses the same caller/key predicates for the UPDATE and SELECT. The caller index is unique and partial on a non-null key (`0008:94–95`, `models.py:204–205`). An expired row belonging to caller A cannot cause an idempotency collision for caller B. If A reuses the key, A clears the expired tuple before lookup. The namespace lock is independent: a request can still hold its namespace because of its status, regardless of its key’s age.

There is no 24-hour physical deletion guarantee. One caller sending fresh keys indefinitely can leave one stale index entry per retained request. With many callers, even one shared key string can leave many stale entries. The bound is one entry per stored `(caller, key)` and at most one per request row, with no time-based bound on the total. Release 1 also retained one-off keys nobody reused. No job or foreign key depends on these stale key values. Request events, approvals, jobs and notifications reference `request_id` (`0001:68,81,95,140`), and the recurring jobs are listed at `docs/16-data-model.md:170–171`. The cost is storage and index maintenance. The current lazy-clear policy is correctly described for release 2 at `docs/16-data-model.md:242`. During the mixed window, a release-1 lookup can still clear another caller’s expired tuple.

**(d) Lock and failure handling — confirmed, with two distinct diagnostics.** `0009:76–77,105–113,116–126` takes `ACCESS EXCLUSIVE` as the first operation of each revision function. I also ran both functions against a recording Alembic operation object: the first call in each was the literal `LOCK TABLE`, before even `get_bind()` for the checks. The overall migrator does other work first, including reading the revision. The refusal queries cannot execute before this table lock returns.

`migrations/env.py:35–41,54–61` takes the session advisory lock, sets the default 30-second `lock_timeout`, then runs the migrations in one transaction. An open reader or writer can hold up 0009. Later queries can queue behind the waiting exclusive request. If that lock attempt times out, PostgreSQL raises `55P03`, the transaction rolls back, the process exits nonzero and the init container retries. Sustained contention can cause repeated failures. Once acquired, the lock covers the checks, updates, CHECK validation and index DDL through commit. Thirty seconds limits each lock-acquisition wait. It provides no total runtime limit, and the initial advisory lock is acquired before this setting. The implementer’s `outputs/lock-probe.txt:1–10` records both SELECT and UPDATE timing out while each direction held the lock.

**Refuted for the JSON event alone; confirmed for the complete log.** All three intentional refusals raise Python `RuntimeError` (`0009:94–102,120–122`). `core/db/migrate.py:87–92` emits `error="RuntimeError"` and `sqlstate=null`, then re-raises. From that event alone the operator cannot distinguish ambiguity, caller collision or downgrade collision, or identify a row. The following traceback contains the direction, reason, sorted request IDs and retry condition. IDs in each collision group are assembled at `0009:80–85`. An operator with the full migrate-container log can identify the blockers for the reported refusal. If ambiguity is present, that refusal fires before the collision query, so it does not inventory every independent reason at once. `docs/12-existing-postgresql.md:137–149` describes the two log surfaces correctly. I would preserve #617’s event-field restriction.

**(e) Downgrade — confirmed for 0009 → 0008.** Under the lock, `_shared("requester_sub")` groups precisely the two columns of the index to be recreated (`0009:80–85,116–125`). `created_at` is non-null (`0001:49`). The live and expired inequalities at `0009:66–67` partition every keyed row using the same transaction’s `now()`. A row exactly 24 hours old is live. Two or more live rows in one group refuse before changes. Every expired holder is then cleared, so no live/expired or expired/expired pair can break the index build. Null keys are outside the partial index. The caller index remains, all live caller values survive, and the CHECK is dropped last. The refusal is complete for conflicts the recreated index could encounter after cleanup. **The further round trip through 0007 is confirmed for normal writer-generated rows; finding 1 refutes it for all supported stored shapes.**

**(f) Release-1 pods on the new schema — confirmed for insert and replay semantics.** `base/.../core/db/repo.py:50–60,148–155,185–201` shows the old code checks membership in a tuple containing **both** index names. It does not query the dropped index by name. A same-caller race still produces `uq_cr_idempotency_caller`. A different caller using the same requester/key no longer produces a requester-index violation, as intended. Release 1’s `COALESCE` reads the populated caller first on every keyed row after 0009. Its broad UPDATE touches expired rows only and still satisfies the CHECK.

The performance qualification is real. The remaining index has columns `(idempotency_sub, idempotency_key)`. The old SELECT expresses the subject through `COALESCE`, and the old UPDATE supplies only the trailing key column. Neither gets the new code’s direct two-column lookup. PostgreSQL may scan a larger portion of an index or the table. The exported size probe compares **old SQL on 0008** with **new SQL on 0009** (`outputs/size_probe.py:56–76`); it does not measure the old SQL’s cost on 0009. The separate compatibility run recorded **27 passed, 3 failed, 9 deselected**. The three failures are old expectations for the removed requester collision or an attempted keyed/null-caller fixture (`outputs/release-1-code-on-0009.txt:289–293`). That is evidence for behavioral compatibility, not a measured mixed-version latency bound or a cluster rollout.

**(g) Docs and model — confirmed for the caller contract, with the findings above.** `docs/04-api-examples.md:18` and `docs/GLOSSARY.md:59,196` give the correct ownership, retry scope and revision history. `docs/16-data-model.md:53,105–106,242,371–376` correctly describes the partial index, CHECK, lookup and legacy keyless subject. Its generated block says head `0009` at line 259. The provenance sentence at line 256 still names `0008`; replace “written again on 2026-11-23 for migration `0008`, #592” with “the migration head of this snapshot is shown below” to avoid duplicating the generated revision. `test_data_model_doc.py:13–22` checks the generated block, so it can pass with stale prose outside the markers.

`core/db/models.py:29–30,48,52–56,204–205` matches the **0009 idempotency change**. Full `change_requests` CHECK parity is refuted by finding 3. `core/db/__init__.py:71–87` sets `REQUIRED_REVISION="0009"` and reports 0008 behind. `routers/health.py:33–37` consumes schema status. The revision-status test passed locally.

**(h) Requested mutants.** These are predictions from tracing the assertions. I could not execute the PostgreSQL mutants here.

| Mutation | Would the submitted tests detect it? |
|---|---|
| Remove the migration’s `create_check_constraint` | **Yes.** `test_idempotency_release2_603.py:66` checks the database definition. Lines 273–280 also require an actual `CheckViolation` naming `ck_cr_idempotency_caller` and verify which row survived. Removing only the *model* declaration is a different mutant that those assertions miss. |
| Remove upgrade refusal (b) | **Yes.** The fill would eventually hit the existing caller unique index and roll back, so an unchanged-state assertion alone would pass. Lines 108–118 also require the intentional refusal and the IDs of **both** collision groups, which the generic unique violation cannot supply. |
| Remove the subject from the expiry UPDATE | **Yes.** Both HTTP responses could still be correct. `test_idempotency_caller_592.py:208–216,230–236` inspects the *other caller’s stored row* before that caller reuses the key. The broader UPDATE fails that assertion. The plan check at `test_idempotency_release2_603.py:244–248` independently requires both indexed columns. |
| Remove the downgrade refusal | **Yes.** `CREATE UNIQUE INDEX` would fail and roll back. `test_idempotency_release2_603.py:167–175` requires the explicit downgrade diagnostic with both IDs as well as unchanged state and a successful retry after expiry. |

Two residual coverage limits are worth recording. The exact-24-hours test imports **0008** at `test_idempotency_caller_592.py:256–275`; it does not exercise the independent 0009 constants. Changing only `0009._LIVE` from `>=` to `>` can survive the supplied 23/25-hour examples. Likewise the 0009 ambiguity test uses a missing subject at `test_idempotency_release2_603.py:82–93`; the parameterized numeric and empty-string cases at `test_idempotency_caller_592.py:412–422` run against **0008**. The submitted predicates at `0009:66–71` are correct. The direct tests should apply those same inputs to 0009 to protect them.

## Test handoff

**Passed locally**

```text
tests/service/test_idempotency_release2_603.py::test_a_database_at_release_1_is_behind_this_code
tests/service/test_migrate_log_614.py::test_the_failure_event_never_carries_the_url_or_its_password
```

**Outstanding PostgreSQL tests:** Each heading is the module under `cmapi/tests/service/`. Append `::` and the listed name to form its pytest node ID. The first test below failed at fixture setup before entering its body. The remaining database-dependent cases were collected and left for the coordinator/reviewer 2.

`test_idempotency_release2_603.py` — 8

```text
test_the_upgrade_fills_each_keyed_row_with_its_caller_and_keeps_only_the_caller_index
test_the_upgrade_refuses_a_live_delegated_row_without_its_caller_and_changes_nothing
test_the_upgrade_refuses_a_live_collision_under_the_caller_and_changes_nothing
test_the_downgrade_restores_release_1_and_keeps_every_live_key
test_the_downgrade_refuses_a_live_pair_of_one_requester_and_changes_nothing
test_rows_that_a_0007_pod_wrote_replay_for_their_caller_after_0009
test_the_lookup_and_its_expiry_find_the_key_by_its_caller_through_the_caller_index
test_the_database_refuses_a_keyed_row_with_no_caller
```

`test_idempotency_caller_592.py` — 18

```text
test_a_service_retry_on_behalf_of_a_person_replays_its_request
test_a_service_retry_that_loses_the_race_gets_the_closed_winner
test_one_service_key_for_a_second_person_is_refused_by_the_caller_index
test_the_person_cannot_replay_the_service_request_with_its_key
test_a_person_own_retry_still_replays
test_a_service_key_is_free_again_after_24_hours
test_the_person_can_use_a_key_that_a_service_held_for_them_once_it_expires
test_a_service_can_use_a_key_that_the_person_held_once_it_expires
test_a_key_named_after_an_index_is_an_opaque_key
test_a_key_exactly_24_hours_old_is_still_held_by_the_lookup_and_the_migration
test_the_upgrade_keys_each_stored_key_on_its_caller_and_keeps_the_old_index
test_the_upgrade_refuses_a_live_collision_and_succeeds_once_it_expires
test_the_upgrade_refuses_a_live_delegated_row_without_its_caller
test_the_upgrade_refuses_a_live_delegated_row_whose_caller_is_not_a_subject[a-number]
test_the_upgrade_refuses_a_live_delegated_row_whose_caller_is_not_a_subject[empty]
test_a_0007_insert_in_the_window_no_longer_escapes_the_caller_index
test_the_downgrade_keeps_every_key_and_the_old_index
test_keys_written_by_this_code_replay_after_a_schema_round_trip
```

`test_migrate_log_614.py` — 8

```text
test_a_run_that_applies_two_revisions_names_them_in_order_with_their_times
test_a_run_at_head_says_it_applied_nothing
test_a_run_from_an_empty_database_starts_from_none
test_a_downgrade_names_the_revisions_it_undid
test_the_lock_wait_is_the_time_spent_behind_the_other_migrator
test_each_time_holds_its_own_work_and_the_transaction_ends_after_its_commit
test_the_result_is_written_whatever_the_log_level
test_a_failed_run_says_so_in_one_event_and_still_exits_with_its_diagnostic
```

`test_models_match_migrations.py` — 11

```text
test_alembic_check_finds_no_difference_between_the_models_and_the_migrations
test_a_column_that_only_the_models_have_is_found
test_an_index_that_only_the_models_have_is_found
test_an_index_of_the_migrations_that_the_models_do_not_declare_is_found[uq_cr_open_namespace]
test_an_index_of_the_migrations_that_the_models_do_not_declare_is_found[uq_cr_idempotency_caller]
test_an_index_of_the_migrations_that_the_models_do_not_declare_is_found[uq_approvals_person]
test_an_index_of_the_migrations_that_the_models_do_not_declare_is_found[uq_jobs_pending]
test_an_index_of_the_migrations_that_the_models_do_not_declare_is_found[idx_jobs_due]
test_an_index_that_is_unique_only_in_the_database_is_found
test_each_index_of_the_models_is_the_index_of_the_migrations_predicate_included
test_a_changed_predicate_of_a_partial_index_is_found_where_alembic_check_is_blind
```

[exited with code 0]
