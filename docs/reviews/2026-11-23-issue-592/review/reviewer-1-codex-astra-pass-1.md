# PR #601 adversarial review — reviewer 1

**Request changes before deployment.** The 0008 application implements the owner’s decision correctly for requests written and read by 0008. The release procedure, however, allows a 0007 API pod to serve traffic after the migration commits. That pod can return a request belonging to another caller, and its writes can bypass the new uniqueness guarantee. This can happen on an ordinary forward rollout as well as on rollback.

I reviewed the exported base `8a5b41c` and head `628a6c5`. The GitHub issue command could not connect, so I used the owner’s decision recorded in `head/docs/reviews/2026-11-23-issue-592/README.md:15–19`. PostgreSQL denied the connection from this sandbox. The database behavior below is **inferred from the source and PostgreSQL 16 documentation**. The test results at the end are **measured**.

The sandbox permits writes to the `cmapi-design` workspace and temporary directories. The requested `workbench/cmapi/review-601/codex-report.md` is outside those roots, and permission escalation is disabled. I did not write a substitute file or modify a repository. The full report follows.

Paths below are relative to `head/` unless prefixed with `base/`. `0008` refers to `cmapi/src/cmapi/core/db/migrations/versions/0008_idempotency_key_of_the_caller.py`.

## 1. High — the normal rollout and image rollback can violate caller isolation

**Evidence.** `deploy/helm/cmapi/templates/api.yaml:13–15` specifies `maxUnavailable: 0, maxSurge: 1`. The new pod runs the migration in its init container at lines 26–35. The worker can also initiate it in `deploy/helm/cmapi/templates/worker.yaml:26–33`. The old API can therefore be serving when either migrator commits. `base/cmapi/src/cmapi/core/db/repo.py:128–133` clears and selects by `(requester_sub, key)` and returns `.first()` without an ordering. `0008:70–77` removes uniqueness on that pair. `docs/12-existing-postgresql.md:76–83` mentions keys becoming invisible after an image rollback but misses both the forward-rollout window and the old reader’s behavior.

**Failure scenarios.**

- A service has submitted for a person. During the rollout, replaying through a new API uses the service’s subject. An old API still reads the same row under the person’s subject. The security fix therefore depends on which replica handles the request. Where two 0008 callers legitimately have the same key for that person, the old lookup can pick either row.
- An old pod commits a keyed request after 0008 has committed. Its insert omits `idempotency_sub`. PostgreSQL permits multiple `(NULL, key)` entries in this index. A new pod cannot find that row by the caller’s subject. A retry can create another request once the namespace is free. The old pod has also lost the database constraint that enforced its own requester-based uniqueness.
- Starting 0008 again against a database already marked 0008 does not rerun its backfill. An image-only rollback followed by a roll-forward leaves those rows invisible. An explicit schema downgrade and re-upgrade is a different operation.
- `deploy/release-crc.sh:113–136` defaults to Helm atomic rollback. A failure **after** the migration commits can bring back the old API automatically. The Alembic transaction cannot undo that later deployment failure. [PostgreSQL 16 unique indexes](https://www.postgresql.org/docs/16/indexes-unique.html)

**Fix.** An insert trigger alone cannot repair the old SELECT. For this PR, the smallest release fix is an explicit maintenance cutover in both directions. That requires an owner-approved exception to docs/12’s image-only rollback promise. If the promise must be retained, this PR needs a compatibility release before 0008. Making the column nullable does not deliver that compatibility.

Here is the complete cutover wrapper I propose for the maintenance option. It is for the default CRC release and namespace. It must be the entry point for this transition, including rollback. It assumes the operator has configured the **0008** `cmapi-migrate` executable and its database environment for a downgrade, has the target chart and image lock selected for the final deploy, and has suspended other reconcilers that could restart these deployments. It leaves traffic stopped on a migration failure.

```bash
#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  upgrade|downgrade) direction=$1 ;;
  *) echo "usage: cutover-0008 upgrade|downgrade" >&2; exit 2 ;;
esac

namespace=cmapi
deployments=(cmapi-api cmapi-worker)
selectors=()

for deployment in "${deployments[@]}"; do
  selector=$(kubectl -n "$namespace" get deployment "$deployment" \
    -o go-template='{{range $key,$value := .spec.selector.matchLabels}}{{$key}}={{$value}},{{end}}')
  selector=${selector%,}
  test -n "$selector"
  selectors+=("$selector")
done

kubectl -n "$namespace" scale deployment "${deployments[@]}" --replicas=0

for selector in "${selectors[@]}"; do
  deadline=$((SECONDS + 300))
  while :; do
    pods=$(kubectl -n "$namespace" get pods -l "$selector" -o name)
    [[ -z "$pods" ]] && break
    if (( SECONDS >= deadline )); then
      echo "pods still present for $selector" >&2
      exit 1
    fi
    sleep 2
  done
done

if [[ "$direction" == downgrade ]]; then
  cmapi-migrate 0007 --downgrade
else
  cmapi-migrate 0008
fi

RELEASE_ATOMIC=false deploy/release-crc.sh --deploy-only
```

Replace the compatibility claim in `docs/12-existing-postgresql.md:80–83` with:

> For the 0007/0008 transition, drain the API and worker before migrating. Start only the image matching the target revision. To return to 0007, drain 0008, run `cmapi-migrate 0007 --downgrade` with the 0008 migrator, then start 0007. An image-only rollback restores the old requester-based reader on a schema that permits multiple rows for that lookup. Returning to 0007 also restores its delegated-replay limitation.

**Regression test.** In the deployment integration test, hold the replacement API before readiness and let the worker initiate migration. At the first observation of revision 0008, assert zero 0007 API **and** worker pods, including terminating pods. Repeat with the target API deliberately failing readiness after migration. Assert no 0007 endpoint returns to service while the database remains on 0008. On the downgrade path, assert revision 0007 before the first 0007 endpoint becomes ready. The current rolling strategy violates the first assertion by design. The cutover wrapper makes it a prerequisite to migration.

## 2. High — deduplication can release a still-live key early

**Evidence.** `0008:48–52` clears expired rows first. `0008:59–66,74` then clears the key, fingerprint, and owner on every losing **unexpired** row. It retains the caller’s own row first, then the newest `created_at`, then descending `request_id` for a deterministic tie. `cmapi/tests/service/test_idempotency_caller_592.py:180–198` explicitly expects an older own row to beat a newer delegated row.

**Failure scenario.** A service’s delegated request is two hours old. Its own request with the same key is 23 hours old. These can coexist under 0007, for example when the delegated request was submitted first. The upgrade correctly keeps the one the service could already replay, but the delegated request loses 22 hours of key protection. A retry of the losing body initially conflicts with the winner’s fingerprint. Just over an hour later, `cmapi/src/cmapi/core/db/repo.py:130–136` clears the winner too. At that point an ordinary retry can create another request if the namespace is free, while the losing request is still well inside its original 24 hours. Downgrade has the analogous loss for collisions under `(requester_sub, key)`.

**Judgment.** The ranking correctly implements the stated winner policy. It does not implement the unconditional promise at `0008:17–19` that a stored key stays valid for the rest of its 24 hours. No ranking can make one `(subject, key)` return two distinct original requests. I would distinguish approval of option A from acceptance of silently discarding a live retry claim.

**Fix.** My recommendation is to refuse a transition with live collisions, keep the source revision intact, and retry after expiry. This changes the proposed collision policy and needs the owner’s decision. It preserves the one-transaction design and avoids inventing a new replay protocol. Replace `_keep_one_key_per` and both calls with the following. The only owner arguments are the two constants shown.

```python
def _require_unique_live_keys(owner: str) -> None:
    if owner not in {"idempotency_sub", "requester_sub"}:
        raise ValueError("invalid idempotency owner column")

    collisions = op.get_bind().execute(sa.text(f"""
        SELECT count(*)
        FROM (
            SELECT 1
            FROM change_requests
            WHERE idempotency_key IS NOT NULL
            GROUP BY {owner}, idempotency_key
            HAVING count(*) > 1
        ) AS conflicting_keys
    """)).scalar_one()

    if collisions:
        raise RuntimeError(
            f"{collisions} live idempotency key group(s) conflict under "
            f"{owner}; retry after expiry"
        )


# In upgrade(), after backfill and before replacing the index:
# _require_unique_live_keys("idempotency_sub")

# In downgrade(), after clearing expired keys and before recreating the index:
# _require_unique_live_keys("requester_sub")
```

If the owner explicitly accepts lossy deduplication, retain the SQL, document the early-reuse example in docs/12, and report the affected count before deploy. A successful downgrade restores the old schema and a usable old index. It cannot reconstruct keys or fingerprints the upgrade already discarded.

**Regression test.** This test uses the PR’s existing `empty_schema`, `_run`, `_insert`, `_state`, and `migrate` helpers. Add its mirror for downgrade using two 0008 callers and one requester.

```python
def test_upgrade_preserves_live_collisions_until_expiry(empty_schema):
    _run(empty_schema, "0007")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "delegated", requester_sub="person", submitted_by="svc",
                key="k", hours_ago=2)
        _insert(c, "own", requester_sub="svc", key="k", hours_ago=23)
        before = _state(c)

        p = migrate(empty_schema, "head")
        output = p.communicate()[0]
        assert p.returncode != 0 and "conflict" in output
        assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0007",)
        assert _state(c) == before

        c.execute("""
            UPDATE change_requests
            SET created_at = now() - interval '25 hours'
            WHERE request_id = 'own'
        """)
        _run(empty_schema, "head")
        rows, _ = _state(c)
        assert rows["delegated"] == ("k", "fp-delegated", "svc")
        assert rows["own"] == (None, None, None)
```

## 3. Medium — the migration understates read downtime and the meaning of 30 seconds

**Evidence.** `0008:25–27` and the decision record at `docs/reviews/2026-11-23-issue-592/README.md:53` say the index build blocks only writes. The migration first executes `ALTER TABLE ... ADD COLUMN` at `0008:70`. That acquires `ACCESS EXCLUSIVE` and retains it through transaction end, including expiry updates, backfill, window ranking, index replacement, and the revision update. An ordinary SELECT conflicts. Downgrade starts with plain `DROP INDEX` at `0008:81`, which also acquires `ACCESS EXCLUSIVE` on the table. Adding a nullable column without a default avoids a table rewrite, but does not shorten the transaction to that one statement. [PostgreSQL 16 ALTER TABLE](https://www.postgresql.org/docs/16/sql-altertable.html) · [table lock modes and duration](https://www.postgresql.org/docs/16/explicit-locking.html) · [DROP INDEX](https://www.postgresql.org/docs/16/sql-dropindex.html)

**Failure scenario.** A dashboard reading request history and workers updating request state can both wait behind the migration. On a large table, expiry and backfill write row versions, the ranking may sort, and the new index must be built. Once the lock is acquired, running those operations for more than 30 seconds does not trigger `lock_timeout`. A waiting exclusive lock can also queue later traffic before the migration acquires it. No production row count, execution plan, or outage duration was measured here.

**Fix.** Use this complete replacement paragraph in the migration docstring, decision record, and docs/12 operating guidance:

> Upgrade acquires ACCESS EXCLUSIVE on `change_requests` when it adds the column. Downgrade acquires it when it drops the index. Reads and writes to this table can wait through the data updates and index build until commit. The default 30-second `lock_timeout` limits each attempt to acquire a lock. It does not limit work after acquisition or the total migration time. The migrator obtains its session advisory lock before setting this timeout. Measure the transaction on a production-sized copy when scheduling the cutover.

**Regression test.** For the documentation defect, assert the migration explanation and operating guide both contain `ACCESS EXCLUSIVE` and `Reads and writes`, and remove the writes-only claim. For independent database verification, have connection A begin a transaction at 0007 and execute the migration’s `ADD COLUMN`. On B, set `lock_timeout = '100ms'` and issue `SELECT request_id FROM change_requests LIMIT 1`. Expect SQLSTATE `55P03`. Roll A back and verify B can read again in a fresh transaction. Repeat from 0008 with the downgrade’s first `DROP INDEX`. This tests the combined transaction’s lock, which measuring `CREATE INDEX` alone would miss. [PostgreSQL 16 lock timeout](https://www.postgresql.org/docs/16/runtime-config-client.html)

**Confirmed — no insert can slip between upgrade deduplication and index creation.** A writer holding a conflicting table lock first must finish before the ALTER proceeds. Under PostgreSQL’s default Read Committed isolation its committed row is visible to the subsequent updates. A writer queued behind the migration proceeds only after transaction end. The latter can create the null-owner problem in finding 1, but cannot make the in-progress index build fail by inserting between the statements. [PostgreSQL 16 transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html)

**Confirmed — a migration lock timeout rolls back the revision’s work.** `cmapi/src/cmapi/core/db/migrations/env.py:29–38` commits the session setup, then runs Alembic inside `context.begin_transaction()`. `0008:69–87` has no intermediate commit or concurrent index build. A failure before commit rolls back the revision’s DDL, DML, and Alembic version change together. The session advisory lock is obtained **before** `SET lock_timeout`; a second migrator’s wait for that advisory lock is outside the configured 30-second limit. [PostgreSQL 16 CREATE INDEX](https://www.postgresql.org/docs/16/sql-createindex.html)

## 4. Medium, conditional — a delegated legacy record missing its submitter subject is assigned to the person

**Evidence.** `cmapi/src/cmapi/core/identity/checks.py:59–65,73–95` and `cmapi/src/cmapi/core/pipeline.py:504–512` establish the valid 0007 shapes:

| Recorded request | Caller evidence | Backfill result |
|---|---|---|
| Person acting for self | Same object for `person` and `caller` | **confirmed**, `requester_sub` is the caller |
| Service or automation account acting for self | Same object, `automated=True` | **confirmed**, `requester_sub` is the caller |
| Service or automation account acting for a person | Distinct person object, top-level `submittedBySub=caller.sub` | **confirmed**, `submittedBySub` is the caller |

Absence of `submittedBySub` alone is normal. However, `0008:72–73` also falls back when the JSON still has `submittedBy` or `submittedByClient` but its `submittedBySub` is absent or JSON null. The schema at `cmapi/src/cmapi/core/db/migrations/versions/0001_cmapi_schema.py:39–45` does not constrain those JSON fields.

**Failure scenario.** If an imported, repaired, or older record has evidence of delegation but no submitter subject, 0008 attributes its live key to the beneficiary. The new reader then faithfully enforces the wrong owner. **I found no evidence the supplied 0007 application produces that shape or that CRC contains such a row.** If all delegation evidence is missing, those fields alone cannot establish historical ownership.

**Fix.** Fail the upgrade on an identifiable ambiguous live row rather than guessing its owner. Insert this immediately after `_clear_expired_keys()` and before backfill:

```python
ambiguous = op.get_bind().execute(sa.text("""
    SELECT count(*)
    FROM change_requests
    WHERE idempotency_key IS NOT NULL
      AND (requester ? 'submittedBy' OR requester ? 'submittedByClient')
      AND (
          jsonb_typeof(requester->'submittedBySub') IS DISTINCT FROM 'string'
          OR nullif(requester->>'submittedBySub', '') IS NULL
      )
""")).scalar_one()

if ambiguous:
    raise RuntimeError(
        f"{ambiguous} live delegated request(s) lack a caller subject; "
        "verify ownership or retry after expiry"
    )
```

**Regression test.**

```python
def test_upgrade_refuses_ambiguous_delegation(empty_schema):
    _run(empty_schema, "0007")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "delegated", requester_sub="person", key="k",
                submitted_by="svc")
        c.execute("""
            UPDATE change_requests
            SET requester = (requester - 'submittedBySub')
                          || '{"submittedBy":"svc"}'::jsonb
            WHERE request_id = 'delegated'
        """)
        before = _state(c)
        p = migrate(empty_schema, "head")
        output = p.communicate()[0]
        assert p.returncode != 0 and "lack a caller subject" in output
        assert _state(c) == before
```

There is a related ranking detail if the proposed lossy downgrade is retained. `0008:83–84` treats **every** old-image null-owner row as the requester’s own, including a delegated row with a perfectly good `submittedBySub`. If it is newer than the person’s actual own row, it can win. The existing fixture at `test_idempotency_caller_592.py:210` supplies no delegation marker. The full replacement ranking call for that policy is:

```python
_keep_one_key_per(
    "requester_sub",
    "COALESCE(idempotency_sub, requester->>'submittedBySub', requester_sub)"
    " = requester_sub",
)
```

Test with an older 0008 person-owned row and a newer null-owner 0007 row for the same person and key, with `submitted_by="svc"` on the latter. On downgrade assert the actual person-owned row retains its key. The current code picks the newer delegated row. Finding 2’s collision-refusal fix also resolves this case.

## 5. Medium — the race test can pass with idempotency uniqueness broken

**Evidence.** `cmapi/tests/service/test_idempotency_caller_592.py:73–89` leaves the winner **open** and retries the same namespace. Two independent unique indexes can reject the second insert. `cmapi/src/cmapi/core/db/repo.py:166–178` maps the namespace violation to `change-pending` and the key violation to `idempotency-replay`. `cmapi/src/cmapi/plugins/namespaces/router.py:111–116` retries the lookup on **any** 409. Thus the test can return the expected winner and observe both expected lookups even if `uq_cr_idempotency` has lost uniqueness. The index text checks at test lines 190 and 216 match the columns and predicate without asserting `UNIQUE`. The separate model-versus-migration suite does check complete index definitions at `cmapi/tests/service/test_models_match_migrations.py:86–99`.

**Fix and regression test.** Close the winner before forcing the miss. Insert the following after the first POST at test line 79, retaining the existing forced miss and assertions:

```python
    cancel = client.post(
        f"/api/v1/requests/{rid}:cancel",
        json={},
        headers=auth(keys, "ola", sub="sub-ola", **OLA),
    )
    assert cancel.status_code == 200, cancel.text
```

Add this final assertion:

```python
    assert retry.json()["status"] == "cancelled"
```

Also add this assertion immediately after each of the two post-migration `_state(c)` calls that checks a restored or replaced index:

```python
    assert index.startswith("CREATE UNIQUE INDEX "), index
```

**Before/after discriminator.** Run the race test against a deliberately nonunique `uq_cr_idempotency` in the isolated test schema. The original test can pass through the open-namespace constraint. With the change, a duplicate insert is possible and the returned ID or status assertion fails. Restore the unique index and the corrected test requires replay of the closed winner. This is a controlled missed-lookup test; it does not measure concurrent connections.

The HTTP migration test at `test_idempotency_caller_592.py:226–252` also warrants precise labeling. It writes with **head**, downgrades the schema, upgrades it, then reads with **head**. It exercises a useful data round trip. It does not execute the 0007 binary against 0008 and cannot validate docs/12’s mixed-version promise.

## 6. Low — the proposed live design SQL is unsafe to read as a migration recipe

**Evidence.** `LIVE-DOC-EDITS.md:52–58` adds a nullable column, drops the old index, and creates the new one. On populated data, every existing owner remains null. The index can build successfully while enforcing caller uniqueness for **none** of those existing keys. The surrounding SQL at `docs/02-technical-design-v2.md:489–497` also describes `requester_sub` and `approver_sub` as UUIDs. The actual model uses `String(100)` at `cmapi/src/cmapi/core/db/models.py:43,79`. The UUID discrepancy predates this PR.

**Fix.** Replace the proposed executable “What gets recorded” SQL block with this complete read-only schema example, and point operators at the actual migration:

> The request and approval subjects are stored as `varchar(100)`. Migration 0008 migrates existing key ownership before replacing `uq_cr_idempotency`. Use `cmapi-migrate` for the transition. Inspect the installed index with:

```sql
SELECT pg_get_indexdef('uq_cr_idempotency'::regclass);
```

**Regression test.** After live-doc export, extract the “What gets recorded” section of docs/02 and assert that it names `cmapi-migrate` and contains the inspection query. Reject `DROP INDEX uq_cr_idempotency` in that section. The proposed text fails this test. The replacement directs readers to the migration that actually handles existing data.

## Remaining requested checks

- **Confirmed — expiry clock and boundary.** `0008:48` and `cmapi/src/cmapi/core/db/repo.py:49,130–134` both use strict `< now() - interval '24 hours'`. A row exactly on the boundary remains held for that transaction. `0001_cmapi_schema.py:49` and `core/db/models.py:55` use a timezone-aware column with a database `now()` default. `core/pipeline.py:504–512` leaves creation time to the database. `core/db/__init__.py:30–33` sets app sessions to UTC. PostgreSQL `now()` is transaction-start time, and 24 hours is an elapsed-hours interval across DST. Pod clock skew does not change this decision. A long transaction can evaluate an earlier cutoff than a later transaction; neither path promises 24 hours from HTTP response or commit. [PostgreSQL 16 date/time functions](https://www.postgresql.org/docs/16/functions-datetime.html)
- **Confirmed — normal 0008 writer, reader, and race fallback agree.** `core/pipeline.py:508–512` keeps requester and key owner separately. `core/db/repo.py:130–136` clears owner, key, and fingerprint together and preserves `updated_at`. `plugins/namespaces/router.py:86–97,100–116` uses `who.sub` for both lookups and compares the fingerprint before returning the current request view. `core/db/models.py:199–200` matches the migration’s index columns, uniqueness, and predicate. The constraint name still matches `core/db/repo.py:177`.
- **Confirmed — steady-state caller isolation for correctly attributed rows.** `core/auth.py:165–166` verifies the token for the configured issuer and audience. `core/identity/claims.py:52–60` takes the subject from those claims. Guessing an opaque key does not select a different subject’s cache entry. The unit of isolation is the token subject; two OAuth clients presenting the same subject share that namespace by the owner’s option A. Section 5 of the draft recommends binding the key to client-specific attributes to address cache data leaks. A `change-pending` response can independently name the namespace’s open holder at `core/db/repo.py:168–176`; it does not depend on guessing the holder’s key. Findings 1 and 4 identify the exceptions to the deployment-wide security claim. [Idempotency-Key draft 09, §5](https://www.ietf.org/archive/id/draft-ietf-httpapi-idempotency-key-header-09.html#section-5)
- **Confirmed — remaining production paths.** I found no head runtime query that looks up an idempotency key by `requester_sub`. The approval ledger still needs that subject and the recorded submitter at `core/db/repo.py:223–225`. Revert constructs its requester and explicitly submits with `idempotency_key=None` at `jobs/open_pr.py:94–101`. Its internal fingerprint does not put it into the partial key index. Admin reporting and KPI aggregation at `routers/admin.py:229` and `core/kpi.py:188–234` do not resolve keys. The schema generator reads catalog index definitions at `scripts/db-schema-doc.py:25,35`; it does not implement a separate ownership lookup.
- **Confirmed — downgrade schema compatibility, with data-loss qualifications.** `0008:81–87` reconstructs the partial unique index on `(requester_sub, idempotency_key)` and drops `idempotency_sub`. Those are the columns and predicate expected by 0007. A completed downgrade restores 0007’s schema contract and its original delegated-replay defect. It does not reverse the earlier data cleanup.
- **Confirmed — steady-state documentation.** `docs/04-api-examples.md:18`, `docs/GLOSSARY.md:58`, `docs/16-data-model.md:53,106,242,367,375`, and the OpenAPI header source at `cmapi/src/cmapi/routers/__init__.py:60–75` agree on caller ownership where applicable. The delete-specific description at lines 80–86 promises same-caller replay and has no dry-run exception. Expiry routes omit justification from the fingerprint at `plugins/namespaces/router.py:387–399,411–413,424–426`. The proposed lifecycle and idempotency-row wording in `LIVE-DOC-EDITS.md` agrees for a fully upgraded service. The actual exported docs/01 and docs/02 still contain the old caveat pending the live edits. The handwritten docs/16 index matches the migration on inspection; its catalog-generated section was not verified against a running server here.

## Test execution and coordinator handoff

**Measured: 3 passed, 9 setup errors.** I used the supplied Python, `PYTHONPATH=head/cmapi/src`, disabled bytecode and pytest’s cache, and set the migration connection wait to zero. Both a direct psycopg probe and pytest reported `Operation not permitted` connecting to `127.0.0.1:55432`. No migration SQL or database-dependent test body executed. The implementer’s PostgreSQL 16.15 results at `docs/reviews/2026-11-23-issue-592/README.md:80–90` are separate evidence.

The passing checks were both parameterizations of `test_if_match_surface_581.py::test_the_api_docs_describe_the_replay_and_the_one_field` and `test_second_pass_converged.py::test_revision_validation_by_the_history_and_the_convention`.

The following exact tests require the coordinator’s PostgreSQL run. The first eight are in `head/cmapi/tests/service/test_idempotency_caller_592.py`:

```text
test_a_service_retry_on_behalf_of_a_person_replays_its_request
test_a_service_retry_that_loses_the_race_gets_the_winner
test_the_person_cannot_replay_the_service_request_with_its_key
test_a_person_own_retry_still_replays
test_a_service_key_is_free_again_after_24_hours
test_the_upgrade_keys_each_stored_key_on_its_caller
test_the_downgrade_keys_each_stored_key_on_its_requester_again
test_a_key_stored_before_the_upgrade_replays_after_it
```

The ninth is `head/cmapi/tests/service/test_data_model_doc.py::test_the_data_model_document_is_the_schema_of_the_migrations`. The proposed regression tests, mixed-image deployment checks, lock observations, and production-sized timing are unmeasured.

Codex session ID: 01a20936-0381-7aa3-8ab2-b3648237cef2
Resume in Codex: codex resume 01a20936-0381-7aa3-8ab2-b3648237cef2
