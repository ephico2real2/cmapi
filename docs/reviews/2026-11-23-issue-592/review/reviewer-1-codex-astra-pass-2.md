[codex] Starting Codex task thread.
[codex] Thread ready (01a209b9-bebd-7282-81b0-e9e0143a8024).
[codex] Turn started (01a209b9-c119-7c61-b211-93348c71dcca).
[codex] Assistant message captured: I’ll review the exported snapshots and decision record, trace the mixed-version paths against...
[codex] Running command: /bin/zsh -lc "cd /Users/olasumbo/gitRepos/workbench/cmapi/review-601b && ls -la && cat first-...
[codex] Command completed: /bin/zsh -lc "cd /Users/olasumbo/gitRepos/workbench/cmapi/review-601b && ls -la && cat first-... (exit 0)
[codex] Running command: /bin/zsh -lc 'nl -ba head/cmapi/tests/service/test_idempotency_caller_592.py'
[codex] Command completed: /bin/zsh -lc 'nl -ba head/cmapi/tests/service/test_idempotency_caller_592.py' (exit 0)
[codex] Running command: /bin/zsh -lc 'nl -ba LIVE-DOC-EDITS.md; nl -ba head/docs/reviews/2026-11-23-issue-592/README....
[codex] Command completed: /bin/zsh -lc 'nl -ba LIVE-DOC-EDITS.md; nl -ba head/docs/reviews/2026-11-23-issue-592/README.... (exit 0)
[codex] Running command: /bin/zsh -lc "nl -ba head/cmapi/src/cmapi/core/db/migrations/versions/0008*.py; nl -ba head/c...
[codex] Command completed: /bin/zsh -lc "nl -ba head/cmapi/src/cmapi/core/db/migrations/versions/0008*.py; nl -ba head/c... (exit 0)
[codex] Running command: /bin/zsh -lc 'nl -ba head/cmapi/src/cmapi/core/db/migrations/versions/0008*.py; nl -ba LIVE-D...
[codex] Command completed: /bin/zsh -lc 'nl -ba head/cmapi/src/cmapi/core/db/migrations/versions/0008*.py; nl -ba LIVE-D... (exit 0)
[codex] Running command: /bin/zsh -lc "nl -ba head/cmapi/tests/service/test_idempotency_caller_592.py | sed -n '300,41...
[codex] Command completed: /bin/zsh -lc "nl -ba head/cmapi/tests/service/test_idempotency_caller_592.py | sed -n '300,41... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'def test_|WAIT' head/cmapi/tests/service/{test_data_model_doc.py,test_if...
[codex] Command completed: /bin/zsh -lc "rg -n 'def test_|WAIT' head/cmapi/tests/service/{test_data_model_doc.py,test_if... (exit 0)
[codex] Running command: /bin/zsh -lc 'cd head/cmapi && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../../../ob1-run/venv...
[codex] Running command: /bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=head/cmapi/src ../ob1-run/venv/bin/python ...
[codex] Running command: /bin/zsh -lc "nl -ba head/cmapi/src/cmapi/core/db/migrations/env.py | tail -30; tail -19 head...
[codex] Command completed: /bin/zsh -lc "nl -ba head/cmapi/src/cmapi/core/db/migrations/env.py | tail -30; tail -19 head... (exit 0)
[codex] Command completed: /bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=head/cmapi/src ../ob1-run/venv/bin/python ... (exit 0)
[codex] Command completed: /bin/zsh -lc 'cd head/cmapi && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../../../ob1-run/venv... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'ck_cr_requester_kind|requester_kind|submittedBySub|request_id:|idempoten...
[codex] Command failed: /bin/zsh -lc "rg -n 'ck_cr_requester_kind|requester_kind|submittedBySub|request_id:|idempoten... (exit 1)
[codex] Assistant message captured: The export’s mixed-version probe confirms that a 0007 reader can still return a service’s req...
[codex] Running command: /bin/zsh -lc "nl -ba head/cmapi/src/cmapi/core/db/models.py | sed -n '24,63p;196,206p'; rg -n...
[codex] Command completed: /bin/zsh -lc "nl -ba head/cmapi/src/cmapi/core/db/models.py | sed -n '24,63p;196,206p'; rg -n... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'actor_sub|who.sub|VARCHAR\\(100\\)|\"sub\".*100|oidc.*sub' head/cmapi/sr...
[codex] Command completed: /bin/zsh -lc "rg -n 'actor_sub|who.sub|VARCHAR\\(100\\)|\"sub\".*100|oidc.*sub' head/cmapi/sr... (exit 0)
[codex] Searching:
[codex] Running command: /bin/zsh -lc 'cd head/cmapi && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../../../ob1-run/venv...
[codex] Command completed: /bin/zsh -lc 'cd head/cmapi && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../../../ob1-run/venv... (exit 0)
[codex] Assistant message captured: **Request changes on `030c656`.** The rework fixes the migration, downgrade, and loss of the ...
[codex] Turn completed.
**Request changes on `030c656`.** The rework fixes the migration, downgrade, and loss of the old index’s guarantees. It also fixes ordinary delegated replay on a new pod. Two release-1 correctness problems remain:

1. **A service can receive two successful request IDs for one live key.** Two sequential writes through 0007 are sufficient. A race between pod versions is a second way to get there. Ordering the lookup makes the answer deterministic but cannot restore the replay promise for the second successful write.
2. **An expired service key can block the person indefinitely, including on an entirely new fleet.** Expiry searches by caller, while the retained index also excludes by requester. The person cannot clear the expired row that prevents their insert.

There is also a reproducible error-classification defect. An opaque key containing `uq_cr_open_namespace` can turn an idempotency violation into a namespace conflict.

I reviewed only the export. I used no Git commands and made no repository changes. Three local checks passed. PostgreSQL refused the connection, so I distinguish the implementer’s measured results from my source-derived scenarios below. Paths are relative to `head/` unless marked `base/`. `0008` means `cmapi/src/cmapi/core/db/migrations/versions/0008_idempotency_key_of_the_caller.py`, `repo.py` means `cmapi/src/cmapi/core/db/repo.py`, `router.py` means `cmapi/src/cmapi/plugins/namespaces/router.py`, and `T` means `cmapi/tests/service/test_idempotency_caller_592.py`.

## A. Disposition of first-review findings 1–6

| First finding | Second-pass disposition |
|---|---|
| **1. Rollout and rollback can violate caller isolation** | **Partly resolved.** Preserving 0007’s requester uniqueness is **confirmed** at `0008:90–100`. New readers recovering the caller of an ordinary 0007 insert is **confirmed** at `repo.py:55–60,142–148` and in `outputs/mixed-version-probe.txt:17–25`. Isolation on an unmodified 0007 reader is **still open and explicitly documented**. The probe actually returns the new pod’s service request to the named person at line 11. Caller uniqueness across mixed writers is also still open, including without concurrency. |
| **2. Migration releases a live key early** | **Resolved — confirmed.** `0008:60–85,90–95` refuses live collisions before either update. There is no winner selection or live-key deletion. `T:274–300` compares pre/post state after refusal, expires one member of each group, and checks both surviving fingerprints. Downgrade performs no data update at `0008:98–100`. The runtime expiry issue below is a separate defect in the opposite direction. |
| **3. Lock and 30-second wording** | **Resolved — confirmed.** `0008:34–39`, `docs/12-existing-postgresql.md:95–101`, and `cmapi/src/cmapi/core/db/migrations/env.py:28–38` agree. Reads and writes can wait through commit. The timeout applies per lock acquisition, and the session advisory lock precedes it. The supplied `outputs/lock-probe.txt:1–9` records `55P03` for both a SELECT and an UPDATE and shows `AccessExclusiveLock` in each direction. |
| **4. Ambiguous delegated legacy row attributed to the person** | **Resolved for the identified legacy shape — confirmed.** `0008:69–77` checks either delegation marker and rejects a missing, JSON-null, non-string, or empty `submittedBySub` on a live keyed row. `T:303–321` exercises missing and JSON-null values and expiry. If every trace of delegation has been removed, the remaining data cannot establish who submitted it. |
| **5. Namespace uniqueness can make the key-race test pass** | **Resolved for that false positive — confirmed.** `T:95–103` closes the winner and verifies its ID, cancelled state, and both lookup subjects. `T:106–117` separately makes only caller uniqueness decisive. `outputs/mutants-unique-indexes.txt:2–15` shows the closed-winner test failing with both indexes nonunique and the second-person test failing with just the caller index nonunique. Neither test runs simultaneous database sessions. |
| **6. Proposed live-doc DDL reads like an unsafe upgrade recipe** | **Resolved in the proposed text — confirmed.** `LIVE-DOC-EDITS.md:63–71` replaces DDL with a catalog read, identifies the two indexes, points to `cmapi-migrate`, and corrects the subject types. `cmapi/src/cmapi/core/db/models.py:44–53,80` and `0008:90–95` support it. The old text at `LIVE-DOC-EDITS.md:48–61` is explicitly the text being replaced. The live edits are still proposals. |

## B. Mixed-version behavior

The following assumes a valid request, an available namespace unless stated otherwise, and initially one live row for the key. “Old” means the actual 0007 binary on the 0008 schema. The fallback runs after a submit-time 409 and does a fresh lookup under the same token subject as the initial lookup. It does not switch to the winner’s writer version. See `router.py:86–116,268–279` and `base/cmapi/src/cmapi/core/db/repo.py:124–133`.

| Writer → reader | Person’s own request, or service acting for itself | Service S writes for person P |
|---|---|---|
| **Old → old** | **Confirmed.** An uncontested insert succeeds. Same subject/body replays, including on the second lookup after a lost insert race. | **Confirmed wrong legacy answer.** S ordinarily misses its own row and gets a conflict. P supplying the original body can receive the service request before delegation validation. A different fingerprint can disclose its ID in a 409. |
| **New → old** | **Confirmed.** The new writer still stores the requester and the old index still protects it. | **Confirmed wrong legacy answer.** The populated caller column has no effect on the old reader. The probe measured P receiving the service’s request and S getting 409 at `outputs/mixed-version-probe.txt:7–12`. The same lookup defect applies on fallback. |
| **Old → new** | **Confirmed** for a single matching row. The fallback owner is the requester. | **Confirmed** for a single matching row. S replays via `submittedBySub`, including on a second lookup if a constraint stopped the insert. P cannot replay through the new lookup. The actual-binary probe measured both successful replays at `outputs/mixed-version-probe.txt:17–25`. A conflicting insert for a *different* beneficiary need not encounter any constraint, as detailed below. |
| **New → new** | **Confirmed.** Initial lookup and fallback both use the caller. A changed fingerprint names the caller’s own request. | **Confirmed** for ordinary inputs. S replays the current request. P repeating the delegated create body gets 422 during planning. P submitting a valid own request in a free namespace gets a generic 409 with no `requestId` while the requester pair is held. `T:65–86,120–141` distinguishes these cases. |

The **generic 409 without a request ID is an acceptable and documented release-1 consequence of the owner’s decision** when only the retained requester index conflicts with a live row. `docs/04-api-examples.md:18` gives the detail, and the mixed probe measured it. It is **not** a general guarantee for every use of that key. The namespace may independently be held, in which case `repo.py:180–188` can name its holder. `T:132–136` expressly permits that result. A 0007 reader can also disclose the service’s ID via the fingerprint path. Those are different response paths with different disclosure properties.

### High — mixed writers can acknowledge two requests under one caller key

**Evidence.** `0008:90–95` creates a nullable caller column without a default. `base/cmapi/src/cmapi/core/pipeline.py:504–511` omits it. `repo.py:140–148` claims duplicates require a race and selects the oldest. The old SELECT uses `requester_sub`, and neither unique index excludes `(S, K)` when the old insert stores `(NULL, K)` for a different requester. PostgreSQL treats nulls as distinct in this index. [PostgreSQL 16 unique indexes](https://www.postgresql.org/docs/16/indexes-unique.html)

**Failure without a race.** S submits K for P through an old pod, then submits K for Q through the same old pod. Use different free namespaces. Both old lookups search for requester S, both miss, the requester pairs differ, and both caller columns are null. Both writes can return 202. A new reader retrying Q’s successful request now finds P’s older row, compares the wrong fingerprint, and returns 409 naming P’s request. These are two requests of S, so this particular wrong answer is a same-caller mix-up. The **cross-caller** disclosure is the separate old-reader behavior measured in the probe.

The same problem occurs if a new pod commits S-for-P **first** and an old pod subsequently accepts S-for-Q. In the reverse direction a new reader normally sees an already-committed old row, but an initial lookup that misses before the old commit permits the new insert for Q. The daily advisory lock orders the two inserts. It does not repeat the earlier lookup or create the missing index conflict. `cmapi/src/cmapi/core/pipeline.py:492–495,508–515`.

**Fix.** Keep both indexes as decided, and populate the caller in the database for inserts from either binary. The complete migration addition below also fixes the stale requester reservation described next. Install it at the end of `upgrade()`, in the existing transaction. The permitted application writers emit the JSON shapes at `cmapi/src/cmapi/core/identity/checks.py:59–66,73–95`. The explicit guard preserves the refusal rule for a newly inserted identifiable ambiguous row.

```python
def _install_key_trigger() -> None:
    op.execute("""
        CREATE FUNCTION cmapi_set_key_owner() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.idempotency_key IS NULL THEN
                NEW.idempotency_sub := NULL;
                RETURN NEW;
            END IF;

            IF NEW.idempotency_sub IS NULL THEN
                IF (NEW.requester ? 'submittedBy'
                    OR NEW.requester ? 'submittedByClient')
                   AND (jsonb_typeof(NEW.requester->'submittedBySub')
                            IS DISTINCT FROM 'string'
                        OR NEW.requester->>'submittedBySub' = '') THEN
                    RAISE EXCEPTION 'delegated keyed request lacks caller subject'
                        USING ERRCODE = '23514';
                END IF;

                NEW.idempotency_sub := COALESCE(
                    NEW.requester->>'submittedBySub', NEW.requester_sub
                );
            END IF;

            IF TG_OP = 'INSERT' THEN
                UPDATE change_requests
                   SET idempotency_key = NULL,
                       idempotency_fingerprint = NULL,
                       idempotency_sub = NULL
                 WHERE idempotency_key = NEW.idempotency_key
                   AND (requester_sub = NEW.requester_sub
                        OR idempotency_sub = NEW.idempotency_sub)
                   AND created_at < now() - interval '24 hours';
            END IF;

            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER cmapi_key_owner
        BEFORE INSERT OR UPDATE OF idempotency_key ON change_requests
        FOR EACH ROW EXECUTE FUNCTION cmapi_set_key_owner()
    """)


def upgrade() -> None:
    op.add_column("change_requests", sa.Column("idempotency_sub", sa.String(100), nullable=True))
    _refuse_live_keys_without_one_owner()
    op.execute(f"UPDATE change_requests SET idempotency_key = NULL, "
               f"idempotency_fingerprint = NULL WHERE {_EXPIRED}")
    op.execute(f"UPDATE change_requests SET idempotency_sub = {_CALLER} "
               "WHERE idempotency_key IS NOT NULL")
    op.create_index(
        "uq_cr_idempotency_caller", "change_requests",
        ["idempotency_sub", "idempotency_key"], unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    _install_key_trigger()


def downgrade() -> None:
    op.execute("DROP TRIGGER cmapi_key_owner ON change_requests")
    op.execute("DROP FUNCTION cmapi_set_key_owner()")
    op.drop_index("uq_cr_idempotency_caller", table_name="change_requests")
    op.drop_column("change_requests", "idempotency_sub")
```

This changes one observable old-writer behavior intentionally. An old pod can still insert and its requester uniqueness remains intact, but it can no longer acknowledge a second write forbidden by caller uniqueness. The old exception matcher at `base/cmapi/src/cmapi/core/db/repo.py:174–175` also matches the new index name by prefix. A trigger cannot change whom that binary’s SELECT considers the caller.

**Before/after regression**, using the existing migration fixtures. The current head admits the second insert. The fix rejects it specifically at the caller index. This test exercises the actual old *column list*, which assigning NULL after a head insert does not.

```python
import pytest


def test_old_inserts_cannot_claim_one_caller_key_twice(empty_schema):
    _run(empty_schema, "head")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "first", requester_sub="P", submitted_by="S", key="K")
        with pytest.raises(psycopg.errors.UniqueViolation) as caught:
            _insert(c, "second", requester_sub="Q", submitted_by="S", key="K")
        assert caught.value.diag.constraint_name == "uq_cr_idempotency_caller"
        rows, _, _ = _state(c)
        assert rows == {"first": ("K", "fp-first", "S")}
```

Run the same test with the first insert passing `sub="S", with_sub=True`, then with that pair of arguments on the second insert only. Those variants isolate both writer orders without timing dependencies. For the two-process test, hold the losing new request after its first lookup, commit the old winner, then release the new insert. Require one committed request and a 409 naming that caller’s winner for a different body.

**Old-reader disclosure.** If unchanged 0007 must remain routable, the owner is accepting its measured disclosure for that interval and for the whole duration of an image-only rollback. Keeping the old index does resolve the earlier *additional* risk of two requester matches on that reader. It cannot make its single match caller-safe. If caller isolation is required throughout, the minimal application fix is a schema-0007-compatible reader deployed to all serving and rollback images before promising isolation. Its complete lookup needs no 0008 column:

```python
def by_idempotency(self, caller_sub: str, key: str) -> ChangeRequestRow | None:
    owner = func.coalesce(
        ChangeRequestRow.requester["submittedBySub"].astext,
        ChangeRequestRow.requester_sub,
    )
    held = (ChangeRequestRow.idempotency_key == key, owner == caller_sub)
    self.s.execute(
        update(ChangeRequestRow)
        .where(*held, ChangeRequestRow.created_at
               < func.now() - text("interval '24 hours'"))
        .values(idempotency_key=None, idempotency_fingerprint=None,
                updated_at=ChangeRequestRow.updated_at)
    )
    return self.s.scalars(
        select(ChangeRequestRow).where(*held)
        .order_by(ChangeRequestRow.created_at, ChangeRequestRow.request_id)
        .limit(1)
    ).first()
```

The before/after test is the real mixed probe at `outputs/mixed-version-probe.txt:10–12`: run those two HTTP calls against the compatibility image. Require P’s delegated body to get 422 without the service’s ID, and S’s same-body retry to get 202 with its original ID. The unchanged 0007 binary gives the opposite result on both assertions. The migration’s preflight still matters for historical ambiguous or duplicate records.

### High — the requester index can reserve an expired key indefinitely

**Evidence.** `repo.py:142–148` clears only rows whose **effective caller** matches the retry. The requester index at `cmapi/src/cmapi/core/db/models.py:201–204` contains every non-null key regardless of its age. `T:154–165,188–194` ages a delegated row but always lets the **service** perform the reuse.

**Failure.** S writes K for P. After 25 hours, P submits K for a free namespace through a new pod. The expiry UPDATE for P skips S’s row. The SELECT for P misses. The requester index rejects `(P,K)`, and the fallback for P repeats the same miss. Neither retry nor elapsed time releases the key. The same issue affects a second service submitting for P. This requires neither an old pod nor a race.

**Fix.** The insert-time UPDATE in `_install_key_trigger()` above clears expired blockers for **both** unique pairs after the actual caller and beneficiary are known. It preserves live blockers. It also clears `idempotency_sub` when an old application clears the key, which 0007’s own UPDATE otherwise omits.

**Before/after regression.** Current head returns 409 on the last POST. With the fix it returns 202, and the expired row keeps its request history.

```python
def test_person_can_use_an_expired_service_key(world):
    client, ctx, *_rest, keys = world
    _directory(ctx)
    first = client.post(URL, json={**NS, "onBehalfOf": "ola"},
                        headers=_service(keys, "expired"))
    assert first.status_code == 202, first.text
    rid = first.json()["requestId"]
    with ctx.db.session() as s:
        s.execute(text("""
            UPDATE change_requests
               SET created_at = now() - interval '25 hours'
             WHERE request_id = :rid
        """), {"rid": rid})

    own = client.post(URL, json=OTHER, headers=_ola(keys, "expired"))
    assert own.status_code == 202, own.text
    assert own.json()["requestId"] != rid
    assert _keys_of(ctx.db, rid) == ("sub-ola", None, None)
```

### Medium — a key value can select the wrong 409 branch

**Evidence.** `repo.py:178–191` searches `str(exc.orig)` for the namespace index name **before** checking the idempotency indexes. A PostgreSQL unique-violation diagnostic can include the conflicting key value in `DETAIL`. `router.py:76–83` permits an arbitrary nonempty header up to 100 characters.

**Failure.** A service holds the literal key `uq_cr_open_namespace` for P. P submits that key in a different, free namespace. PostgreSQL reports the **requester key index** and includes the key in its detail. The first substring check can match the detail, `open_for` finds no holder, and the client gets `change-pending` saying a holder just finished. There was no such holder. `T:138–140` covers this path only with an ordinary key.

**Fix.** Replace the exception handler in `RequestRepo.insert` with the following. Both index names then map by their actual diagnostic identity, independently of data values and message formatting.

```python
        except IntegrityError as exc:
            self.s.rollback()
            diag = getattr(exc.orig, "diag", None)
            constraint = getattr(diag, "constraint_name", None)
            if getattr(exc.orig, "sqlstate", None) != "23505":
                raise
            if constraint in IDEMPOTENCY_INDEXES:
                raise Problem.conflict(
                    "idempotency-replay",
                    "Idempotency-Key is in use for another request",
                ) from exc
            if constraint == "uq_cr_open_namespace":
                holder = self.open_for(row.cluster_id, row.namespace)
                if holder is None:
                    raise Problem.conflict(
                        "change-pending",
                        f"the request that held {row.namespace} has just finished; "
                        "read the namespace again and resend the change",
                    ) from exc
                raise Problem.conflict(
                    "change-pending", f"{holder.request_id} holds {row.namespace}",
                    requestId=holder.request_id,
                ) from exc
            raise
```

**Before/after regression.**

```python
def test_index_name_is_a_valid_opaque_key(world):
    client, ctx, *_rest, keys = world
    _directory(ctx)
    key = "uq_cr_open_namespace"
    first = client.post(URL, json={**NS, "onBehalfOf": "ola"},
                        headers=_service(keys, key))
    assert first.status_code == 202, first.text

    other = client.post(URL, json=OTHER, headers=_ola(keys, key))
    assert other.status_code == 409, other.text
    assert other.json()["code"] == "idempotency-replay"
    assert other.json()["detail"] == IN_USE
    assert "requestId" not in other.json()
```

**Deadlock and unmapped errors.** For normal application inserts, I found **no new two-index deadlock mechanism** in the examined path. Each submit inserts one request, and both versions acquire the day’s transaction advisory lock before inserting (`repo.py:159–167`, `cmapi/src/cmapi/core/pipeline.py:492–495,515`, and the corresponding base code). Two exclusions on one attempted insert do not themselves form a wait cycle. Either reported key index normally maps to 409. The concrete exception above is **misclassification**, not an unmapped uniqueness error. This is a source conclusion about the application path, not a proof covering arbitrary multi-row SQL, different advisory-lock days, or every transaction in the system. A genuine PostgreSQL deadlock is a different SQLSTATE and is not handled as an idempotent replay here. The supplied probe runs serial steps, not a deadlock stress test. [PostgreSQL 16 locking and deadlocks](https://www.postgresql.org/docs/16/explicit-locking.html)

## C. Refusal checks, timing, and disclosure

- **Confirmed — same cutoff.** `0008:58–63` uses `>= now() - interval '24 hours'` for live and `<` for expired. `repo.py:49,142–146` uses the same strict expiry predicate. Exactly 24 hours is still held in that transaction. `cmapi/src/cmapi/core/db/models.py:57` uses a timezone-aware creation time with a database default. These are database transaction times. Separate transactions can have different cutoffs. The stale-reservation finding concerns *which rows* the UPDATE can reach, not a different clock.
- **Confirmed — no check/build gap.** `0008:89–95` takes the table lock by adding the column first, runs both checks, clears and backfills, then builds the index. `migrations/env.py:35–38` encloses the revision in a transaction. A writer ahead of the ALTER must finish before it obtains the lock. A writer behind it cannot interleave between preflight and index build. The null-owner hole starts **after commit**. [PostgreSQL 16 table locks](https://www.postgresql.org/docs/16/explicit-locking.html)
- **Confirmed — refusal rolls back the revision.** No intermediate commit appears in `0008:88–95`. The tests compare keys, fingerprints, indexes and revision after refusal at `T:284–300,312–321`. The successful retry after sufficient expiry is supported by both tests.
- **Confirmed with a disclosure qualification.** The explicit exceptions at `0008:69–85` print request IDs and, for collisions, reveal which IDs share a caller/key. They do not interpolate the key, token subject, fingerprint, username, body, or client credentials. Normal application IDs are date/sequence identifiers (`repo.py:159–167`). This is operator-visible correlation metadata, and the strings are unbounded in the number of conflicting requests. I found no HTTP path returning the migration message to an API caller. I would not describe the message as revealing *nothing*.

## D. `key_owner()` correctness and cost

**Confirmed for valid application row shapes.** A new keyed row uses `who.sub` at `cmapi/src/cmapi/core/pipeline.py:508–512`. A 0007 delegated write records the submitting subject in the top-level JSON at `cmapi/src/cmapi/core/identity/checks.py:59–66,89–95`. A person, service, or automation account acting for itself uses the requester subject at lines 73–88. `repo.py:55–60` selects the right value for each of those. Keyless rows cannot match `idempotency_key == key`.

**Refuted as an unconditional lookup guarantee.** Correctly identifying the owner of *each row* does not make the result unique across rows. `ORDER BY created_at, request_id` deterministically hides one of two successful requests. Additionally, a malformed delegated row inserted outside the normal writers after preflight can still fall through to the beneficiary if both caller fields are null. The migration checks historical data once. The proposed trigger prevents that identifiable malformed insert as well.

**Refuted — “one sequential scan on every keyed write.”** `repo.py:142–148` executes an UPDATE **and** a SELECT per lookup. A submit-time 409 can run both again at `router.py:111–116`. Neither index at `models.py:201–204` has the `COALESCE` expression as its leading key. PostgreSQL 16 can choose a sequential scan or scan a partial index using the trailing key, depending on statistics and selectivity. The SQL shape establishes the absence of a direct composite-owner seek. It does not establish an exact plan, number of heap scans, or latency. `.first()` on this SQLAlchemy result also does not add a SQL `LIMIT` to the statement. [PostgreSQL 16 multicolumn indexes](https://www.postgresql.org/docs/16/indexes-multicolumn.html)

**Operational judgment.** The record reports 19 CRC rows at `docs/reviews/2026-11-23-issue-592/README.md:28–29`. I would not block that deployment on an unmeasured performance estimate alone. The cost can matter on a larger installation or a long rollback before #603. With the proposed trigger and backfill, the complete new-reader simplification is:

```python
def by_idempotency(self, caller_sub: str, key: str) -> ChangeRequestRow | None:
    held = (
        ChangeRequestRow.idempotency_sub == caller_sub,
        ChangeRequestRow.idempotency_key == key,
    )
    self.s.execute(
        update(ChangeRequestRow)
        .where(*held, ChangeRequestRow.created_at
               < func.now() - text(f"interval '{IDEMPOTENCY_HOURS} hours'"))
        .values(idempotency_key=None, idempotency_fingerprint=None,
                idempotency_sub=None, updated_at=ChangeRequestRow.updated_at)
    )
    return self.s.scalars(select(ChangeRequestRow).where(*held)).one_or_none()
```

This uses the retained caller index directly and makes duplicates an invariant violation. Deploying just this reader against the PR’s current migration **would reintroduce old-row invisibility**. The old-column-list regression above is the required discriminator. For cost verification, run `ANALYZE` on a production-sized copy and compare `EXPLAIN (ANALYZE, BUFFERS)` for **both** the expiry UPDATE and SELECT with present and absent keys, rolling back the measurement transaction. I obtained no execution plan locally.

## E. Downgrade and image rollback

**Confirmed.** `0008:98–100` drops only `uq_cr_idempotency_caller` and `idempotency_sub`. `0001_cmapi_schema.py:60–61` created the old partial unique index, and 0008 never removes or rebuilds it. Thus 0007 still has at most one row per non-null `(requester_sub, idempotency_key)` during a rollout, after an image-only rollback, and after a schema downgrade. `T:324–344` checks that even an expired but uncleared key and its fingerprint survive downgrade. The probe at `outputs/mixed-version-probe.txt:4–5,10–20` also records the actual old migrator accepting the later revision and the actual old writer working on it.

Two qualifications matter. Downgrade preserves the keys existing **at downgrade time**. It cannot restore expired keys previously cleared by upgrade or runtime. And image rollback restores the old reader’s **requester-based** behavior immediately, including its delegated replay defect. It does not restore caller isolation.

## F. What the 12 tests establish

**Confirmed — the exported main run reports all 12 failing**, at `outputs/rework-tests-before-8a5b41c.txt:22–34`. The decision record reports all 12 passing on the reworked head at `README.md:95–113`. Some main failures are missing-column or missing-revision failures. They do not independently show a broken HTTP response.

| Test in `T` | What can still pass with a defect present |
|---|---|
| `:65` service replay | Checks ID, current state, owner, and changed body. A broken initial lookup can sometimes be rescued by insert conflict and fallback, so HTTP success alone cannot prove the fast path worked. |
| `:89` closed race winner | Either unique index can stop this particular insert. **Measured** to pass with the caller index nonunique. Its intended namespace false positive is fixed. |
| `:106` second person | Specifically detects loss of caller uniqueness for **new writers**. An old insert with a null owner bypasses its setup. |
| `:120` person cannot replay | Good distinction between delegated-body rejection, namespace conflict, and free-namespace key conflict. The namespace branch expressly allows a holder ID. An index-name-shaped key is untested. |
| `:144` own retry | The old HTTP behavior already worked. Main fails on the new storage assertion. This test checks preservation plus representation. |
| `:154` expiry | Passes while the named person remains blocked forever. Only the original service performs the reuse. |
| `:168` old-pod row | Uses a head insert followed by `UPDATE ... SET idempotency_sub = NULL`. Useful fallback test, but it cannot detect what an old INSERT bypasses or what an insert trigger would do. |
| `:248` upgrade | Strong schema and data assertions, including exact `CREATE UNIQUE INDEX` definitions. It exercises the migration snapshot, not later old writes. |
| `:274` collision refusal | Strong check of both collision groups, revision, and surviving keys. Tests ages on either side, not the exact 24-hour instant. |
| `:303` ambiguous refusal | Checks both marker names and missing/JSON-null values. It can pass if the non-string or empty-string branch is broken. Add rows with `submittedBySub=42` and `submittedBySub=""` and require both IDs in the refusal. |
| `:324` downgrade | `T:229–239` normalizes a missing column to SQL `NULL`. A mutant that clears all owner values but forgets to drop the column can pass this test. Also, equivalent index definitions cannot by themselves prove the old index was never rebuilt. Source inspection confirms the actual implementation. |
| `:347` schema round trip | Correctly labeled. Head writes and reads at both ends. The downgrade/re-upgrade and replay assertions do not execute a 0007 binary. |

For the downgrade false positive, add this complete assertion immediately after `_run(empty_schema, "0007", "--downgrade")` inside the existing connection block. It fails on the clear-but-keep-column mutant and passes with `0008:100`.

```python
        assert c.execute("""
            SELECT count(*) FROM information_schema.columns
             WHERE table_schema = 'mig' AND table_name = 'change_requests'
               AND column_name = 'idempotency_sub'
        """).fetchone() == (0,)
```

For the refusal false positive, this independent regression checks both missing test cases without depending on the ordering of other IDs:

```python
@pytest.mark.parametrize("subject", [42, ""])
def test_invalid_delegated_subject_is_refused(empty_schema, subject):
    _run(empty_schema, "0007")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "invalid", requester_sub="P", key="K",
                requester={"submittedBy": "svc", "submittedBySub": subject})
        before = _state(c)
        out = _refused(empty_schema, "head")
        assert "live delegated requests invalid" in out
        assert _state(c) == before
```

For the exact cutoff, use one database transaction for setup and evaluation so the boundary does not move between statements. Set `created_at = now() - interval '24 hours'` and assert that the migration’s `_LIVE` predicate matches, `_EXPIRED` does not, and a same-transaction repository lookup retains the key. A separate process starting a migration after fixture commit is unsuitable for that equality test.

## G. Documentation

| Surface | Verdict against the exported code |
|---|---|
| `docs/12-existing-postgresql.md:79–101` | **Confirmed** for both index definitions, old-reader exposure, refusal, rollback, downgrade, and locking. Lines 89–91 overstate replay of all old-written requests when effective-owner duplicates exist. “Under 24 hours” at line 83 omits equality. |
| `docs/16-data-model.md:53,105–106,242,367,375–376` | **Confirmed** for column type, physical indexes, fallback order and database clock. The “one request for each … caller” invariant is false for null-owner old inserts. “Null when the row holds no key” also has an exception: an old reader expiring a **new-written** row clears key and fingerprint but leaves `idempotency_sub` populated (`base/.../repo.py:128–131`). That residue cannot replay because the key is null. |
| `docs/04-api-examples.md:18` | **Confirmed** for ordinary new-reader replay, maximum key length, and the generic free-namespace 409. The unconditional isolation statement is false on old readers. The 409 code and absence of ID need the qualification that only the key conflicts. “While it is held” understates the stale requester-index problem. |
| `docs/GLOSSARY.md:58,195` | **Confirmed** for the intended caller and two-stage schema. The user-facing guarantees need the same version and competing-namespace qualifications as docs/04. |
| OpenAPI, `cmapi/src/cmapi/routers/__init__.py:60–80,84–90` | **Confirmed** for ordinary new-handler replay, create/change dry-run wording, and delete requiring a key. The general header promises `idempotency-replay` too broadly when the namespace also conflicts. The text served by a new pod can describe a deployment whose next request reaches an old pod. |
| `LIVE-DOC-EDITS.md:23,37,63–71` | **Confirmed** for the inspection SQL, types, two physical indexes, and intended ownership. The proposed lifecycle/design wording needs the serving-version qualification. The new docs/02 row also says the key is stored under the caller, although a real old insert in the current PR leaves that column null. |
| Decision record `README.md:62,117–123` | Line 62 says the test requires neither 409 to name the service request. `T:135–136` permits `change-pending` to name it. Line 118 states a scan count without a plan. Line 123 says ordering “covers” races; ordering cannot undo two accepted writes. |

**Replacement wording for the affected public descriptions**, preserving the existing endpoint-specific rules for key length, dry runs and fingerprint fields:

> A new API pod looks up an Idempotency-Key under the token subject. For a live key with one matching request, retrying the same input returns that request in its current state. A service submitting `onBehalfOf` owns the key. During rollout or image rollback, a 0007 API pod still looks up the requester and can return the service’s request to the person it names. Release 1 also reserves the requester/key pair. On a new pod, if only that reservation conflicts, an otherwise valid write gets 409 `idempotency-replay` without a `requestId`. A namespace conflict can instead return 409 `change-pending` and identify the namespace holder.

For documentation shipped **with the current code**, add this operational sentence to docs/12 and the data-model invariant:

> A keyed insert from 0007 leaves `idempotency_sub` null. One caller can therefore acquire multiple live rows for different requesters. The new lookup selects the oldest. An expired delegated row can continue to exclude another caller using the same requester/key pair until the row is cleared.

With the proposed trigger and direct lookup, replace that last paragraph with:

> Migration 0008 backfills existing live keys and fills the caller on inserts from either application version. Before inserting, it releases expired rows that would block either unique pair. A row exactly 24 hours old is still held by that transaction.

For the decision record, replace the three inaccurate claims with:

> A namespace conflict can name its holder. A requester-index-only conflict on a new pod returns no request ID. The current effective-owner lookup executes an UPDATE and a SELECT per attempt, with the execution plans dependent on table statistics. The mixed-version probe ran sequential requests. It did not establish concurrent caller uniqueness.

A documentation regression should require the 0007-reader qualification and the `change-pending` exception beside the release-1 guarantee. The existing checks at `cmapi/tests/service/test_if_match_surface_581.py:251–264` pass on the overbroad text because they look for `onBehalfOf`, `#592`, and removal of one obsolete phrase.

## Execution and coordinator handoff

**Locally measured:** both parameterizations of `test_the_api_docs_describe_the_replay_and_the_one_field` passed, and `test_the_document_tightens_only_the_five_writes_and_keeps_the_string_rules` passed. A direct probe with the supplied Python returned `Operation not permitted` connecting to `127.0.0.1:55432`. No PostgreSQL-dependent body, migration, query plan, or proposed fix was independently executed here.

**Exact database-dependent node IDs for the coordinator**, relative to `head/cmapi/`. The last two check the catalog-generated documentation and the changed readiness floor in addition to the 12 focal tests.

```text
tests/service/test_idempotency_caller_592.py::test_a_service_retry_on_behalf_of_a_person_replays_its_request
tests/service/test_idempotency_caller_592.py::test_a_service_retry_that_loses_the_race_gets_the_closed_winner
tests/service/test_idempotency_caller_592.py::test_one_service_key_for_a_second_person_is_refused_by_the_caller_index
tests/service/test_idempotency_caller_592.py::test_the_person_cannot_replay_the_service_request_with_its_key
tests/service/test_idempotency_caller_592.py::test_a_person_own_retry_still_replays
tests/service/test_idempotency_caller_592.py::test_a_service_key_is_free_again_after_24_hours
tests/service/test_idempotency_caller_592.py::test_a_row_that_a_0007_pod_wrote_after_0008_belongs_to_its_caller
tests/service/test_idempotency_caller_592.py::test_the_upgrade_keys_each_stored_key_on_its_caller_and_keeps_the_old_index
tests/service/test_idempotency_caller_592.py::test_the_upgrade_refuses_a_live_collision_and_succeeds_once_it_expires
tests/service/test_idempotency_caller_592.py::test_the_upgrade_refuses_a_live_delegated_row_without_its_caller
tests/service/test_idempotency_caller_592.py::test_the_downgrade_keeps_every_key_and_the_old_index
tests/service/test_idempotency_caller_592.py::test_keys_written_by_this_code_replay_after_a_schema_round_trip
tests/service/test_data_model_doc.py::test_the_data_model_document_is_the_schema_of_the_migrations
tests/service/test_second_pass_converged.py::test_readiness_refuses_garbage_and_a_divergent_revision
```

The three most informative additional coordinator runs are the **sequential old-column-list duplicate**, **person reuse after service-key expiry**, and **index-name-shaped opaque key** regressions above. All three exercise states outside the 12 reported passing tests.

[exited with code 0]
