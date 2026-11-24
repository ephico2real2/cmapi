# PR #637, reviewer 2 (Opus 5.5, high)

The PR closes #633, #634 and #635. This review checks reviewer 1's findings (Codex gpt-6.2-astra xhigh, `codex-result.txt`,
lines 80 to 296) against the design and the code, and runs them on PostgreSQL 16 (`127.0.0.1:55432/cmapi_wt616`).
It works on the export only: `head/` is c18dd5f, and `r2/` is a copy of it with the fixes. No git repository, GitHub or
cluster was touched.

**Patch:** `r2-outputs/fix.diff`, against c18dd5f. It applies with `patch -p1 -F0` from the repository root. I applied it to
a fresh copy of head (exit 0, no fuzz, no `.rej`), and each of the seven files then matched `r2/` byte for byte.

**Ruling in one line:** reviewer 1's findings 1, 2 and 3 are confirmed. Finding 2's fix is taken with a stronger test, and
finding 3's test is rewritten to read the real log. Reviewer 1 missed finding 4: the export now answers 400 `invalid-sort`, but
its API document does not list a 400. The patch fixes all four.

## Sources

Fetched 2026-11-24:

- **RFC 9110, section 9.3.2** (<https://www.rfc-editor.org/rfc/rfc9110.txt>, saved as `r2-outputs/sources/rfc9110.txt`, lines
  3984 to 4003):
  - "HEAD is used to obtain metadata about the selected representation without transferring its representation data".
  - "These minor inconsistencies are considered preferable to generating and discarding the content for a HEAD request,
    since HEAD is usually requested for the sake of efficiency."
- **RFC 9110, section 15.5.6** (line 7601): "The origin server MUST generate an Allow header field in a 405 response
  containing a list of the target resource's currently supported methods."
- **Google AIP-136** (<https://google.aip.dev/136>): "The HTTP URI must use a `:` character followed by the custom verb", and
  "POST must be used if the method has side effects or mutates resources or data."
- **The design, `docs/01-design-and-architecture.md:178`:** "sort is name (default), used (highest percentage of quota
  first) or severity."
- **The repository's own rule, `cmapi/tests/service/test_api_samples.py:452-457`:** "A refusal that a client meets must be
  one that the operation's documentation names."

## Runs

These are all on the real database. Each run waited for `r2-outputs/gate.sh`: no other `pytest … tests/service` or
`npm test` running, and a 1-minute load under 16. Other reviewers' suites (review-630 and review-631) held the database
for about 70 minutes in total, and the runs waited for them.

| Run | Tree | Result | Evidence |
|---|---|---|---|
| The 31 DB tests reviewer 1 could not run (`test_head_605.py`, `test_review_c_authz.py`), plus 1 non-DB | head c18dd5f | **32 passed** | `r2-outputs/head-31.txt` |
| My changed `test_head_605.py` on head's code (before) | head src + new tests | **2 failed**, 18 passed: the finding 1 and finding 2 tests | `r2-outputs/before-new-tests.txt` |
| The same two files on the fix (after) | r2 | **33 passed** | `r2-outputs/after-two-files.txt` |
| 7 mutants of the fix | r2-outputs/mut | **7 of 7 killed** | `r2-outputs/mutant-*.txt` |
| Samples re-recorded; only the new entry was merged in | r2 | 1 entry added, `operationProblems.quotas_export:invalid-sort`; check run 3 passed | `r2-outputs/summary-regen.txt`, `regen-*.txt` |
| Contract written again (`CMAPI_WRITE_CONTRACT=1`) | r2 | 1 passed; the diff adds only the 400 of `GET /api/v1/quotas:export` | `regen-3-write-contract.txt` |
| `contract/gate.sh` (oasdiff), head contract against r2 contract | r2 | exit 0: "1 changes: 0 error, 0 warning, 1 info … `response-non-success-status-added`" | `r2-outputs/contract-gate.txt` |
| `contract/lint.sh` (Spectral, pinned) | r2 | exit 0, "No results with a severity of 'warn' or higher" | `r2-outputs/spectral-lint.txt` |
| `scripts/api-examples-doc.py --check`, `contract/changelog.py --check` | r2 | both exit 0 | (console) |
| Portal types (`npm run api:types` equivalent, then `--check`) | r2 | "ok - the API types match"; `schema.generated.ts` gains the 400 only; `permissions.generated.ts` is unchanged | `r2-outputs/portal-types-write.txt` |
| `scripts/doc-citations.py --check`, with a `git ls-files` shim that lists files with `find` | r2 | exit 0, "doc-citations: 0 problems" | `r2-outputs/doc-citations-r2.txt` |
| **The whole service suite, once** | r2 | **2584 passed, 2 failed**, 2094.79 s. The 2 failures are `git ls-files` in an export with no `.git` (see below) | `r2-outputs/full-suite-r2.txt` |
| Both files of those 2 tests again, with the git shim on PATH (`r2-outputs/shim/git`: passes through to `/usr/bin/git`; emulates only `ls-files` outside a repository) | r2 | **30 passed** | `r2-outputs/full-suite-git-rerun.txt` |

## Finding 1: `sort=newest` is accepted and audited on the quota export. CONFIRMED

**Evidence.**

- The shared Lister has the extra sort `newest`, `r.get("_created", 0.0)` (`core/context.py:160-161`). It exists for the
  request list, which hard-codes it (`routers/requests.py:70-71`).
- `_query` in the quotas plugin passed any sort through to it.
- On head, my test's first failure was `AssertionError: ('GET', 'sort=newest', 400, 200)` (`before-new-tests.txt`).
- The portal offers only `name`, `used` and `severity` (`cmapi-portal-ui/src/portal/QuotasTab.tsx:22`), so the refusal
  breaks no client.

**Reviewer 1's code is taken as written.** I named the tuple after the design sentence so that it has one home:

```python
# docs/01, Lists: "sort is name (default), used (highest percentage of quota first) or severity". The shared Lister also
# knows `newest`, the request list's order (core/context.py), which a quota row has no time for.
SORTS = ("name", "used", "severity")


def _query(q: str, env: str | None, cluster_id: str | None, team: str | None, tier: str | None, sort: str, limit: int,
           cursor: str | None, starts_with: str | None, state: str | None = None) -> ListQuery:
    if sort not in SORTS:
        raise Problem.bad_request("invalid-sort", f"Unknown sort {sort}")
    return ListQuery(...)
```

**Narrowing, recorded for the coordinator.**

1. `_query` also serves `GET /api/v1/quotas`. So the list now refuses `sort=newest` with 400 too, which the design requires.
2. A request with both a bad limit and a bad sort (`?limit=7&sort=bogus`) now gets `invalid-sort` where it got
   `invalid-limit`. `Lister.page` checks the limit first (`listquery.py:142`). Both answers are 400.
3. **This check is load-bearing for HEAD once finding 2 is fixed.** Mutant m1 removes it: GET still answers 400, because
   `export_csv` sorts eagerly, but HEAD answers `('HEAD', 'sort=bogus', 400, 200)`.

**Test.** It is in `test_a_refused_export_is_refused_before_its_audit_and_its_200`, shown in full under finding 2. It has the
cases `("sort=newest", ola, 400)` for GET and HEAD, and `GET /api/v1/quotas?sort=newest` gives 400.

## Finding 2: HEAD sorts the whole matching set, then drops it. CONFIRMED (introduced by this PR)

**Evidence.**

- On head, `export_csv` returns `_csv_lines(self.filtered(rows, query)[:EXPORT_CAP], columns)` (`listquery.py:196`).
  `filtered` sorts every match when it is called.
- `export` called it for both methods and only then replaced `lines` with `iter(())` for HEAD.
- The PR's own test hid this. It patched `export_csv` with a generator function, so the real `export_csv` ran only when
  iterated, and HEAD never iterates.
- My test spies on `Lister.filtered` at the call instead. On head it failed with
  `At index 3 diff: [([], ListQuery(... sort='severity' ...))] != []`, which is one sort for a HEAD (`before-new-tests.txt`).
- This breaks the quoted RFC 9110 section 9.3.2 "preferable" sentence, and the module's own comment at
  `quotas/__init__.py:141-143` ("no CSV made to be dropped").

**Is HEAD still refused exactly as GET?** Yes, checked on the database for GET and HEAD alike:

| Request | Both methods |
|---|---|
| Bad state | 422 |
| Bad sort | 400 |
| `newest` | 400 |
| No token (with a bad sort) | 401 |
| Signed in with no role (with a bad sort) | 403 |

No refusal writes an audit event. That is the refusal test, which passes on r2. Authentication and permission run as
route dependencies before the body, so the order is the sign-in, then the permission, then the sort.

**Final code.** This is reviewer 1's shape, kept narrow: one variable and no re-indented audit call.

```python
    head = request.method == "HEAD"
    rows = [{**r, "cpuUsed": r["cpu"][0], "cpuHard": r["cpu"][1], "memoryUsed": r["memory"][0], "memoryHard": r["memory"][1],
             "podsUsed": r["pods"][0], "podsHard": r["pods"][1]} for r in quota_rows(c, who)]
    # The refusals first, for both methods (a sort, 400; a state, 422): a refused export is no export, so it writes no audit
    # event, and the refusal is sent before a stream's 200.
    query = _query(q, env, cluster_id, team, tier, sort, 50, None, None, state)
    selected = _in_state(rows, state)
    lines: Iterator[str] = iter(())
    if not head:
        lines = c.lister.export_csv(selected, query, COLUMNS)
        with c.db.session() as s:
            AuditRepo(s).record(who, "quotas.export", "csv", {"rows": len(rows), "q": q, "env": env, "clusterId": cluster_id})
    return StreamingResponse(lines, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="quotas.csv"'})
```

`export_csv` stays eager (the PR's change). With the check in `_query` its `keyfn` can no longer raise here, but it keeps any
future caller's unknown sort a 400 before a 200.

**Tests: reviewer 1's separate test, folded in.** I folded reviewer 1's `test_head_validates_without_sorting_the_export`
into the existing HEAD test, for two reasons:

- The existing test is the one that claims "no CSV made to be dropped", and its generator wrapper was the hiding place.
- The same spy then proves it is live, with exactly one call on the GET. A "not called" assertion alone could pass vacuously.

```python
def test_a_head_of_the_export_exports_nothing(world, monkeypatch):
    """docs/01, "Audit": ... (docstring unchanged)"""
    import cmapi.plugins.quotas as quotas
    from cmapi.core.db.repo import AuditRepo

    client, ctx, *_, keys = world
    sorts, filtered = [], ctx.lister.filtered

    def counted(*args):
        sorts.append(args)      # at the call: the export filters and sorts every matching row there, before its 200
        return filtered(*args)

    monkeypatch.setattr(ctx.lister, "filtered", counted)
    monkeypatch.setattr(quotas, "quota_rows", lambda c, who: [])

    def exports() -> int:
        with ctx.db.session() as s:
            return sum(1 for e in AuditRepo(s).recent() if e.action == "quotas.export")

    path, headers = "/api/v1/quotas:export?sort=severity", auth(keys, "ola", **OLA)
    head = client.head(path, headers=headers)
    assert (head.status_code, head.content, exports(), sorts) == (200, b"", 0, [])
    get = client.get(path, headers=headers)
    assert get.status_code == 200 and get.text.startswith("name,") and exports() == 1 and len(sorts) == 1
    seen = ("content-type", "content-disposition", "content-length", "etag", "cache-control")
    assert {h: head.headers.get(h) for h in seen} == {h: get.headers.get(h) for h in seen}
    assert head.headers.get("content-length") is None


def test_a_refused_export_is_refused_before_its_audit_and_its_200(world, monkeypatch):
    """An unknown state (422) or sort (400) is refused before the export is audited, and the sort before the stream's 200:
    it was read only while the CSV was written, after the status had gone. `newest` is the request list's order, not one of
    the quota list's (docs/01, Lists). HEAD refuses what GET refuses, the sign-in and the permission first."""
    import cmapi.plugins.quotas as quotas
    from cmapi.core.db.repo import AuditRepo
    from fastapi.testclient import TestClient

    client, ctx, *_, keys = world
    monkeypatch.setattr(quotas, "quota_rows", lambda c, who: [])
    c = TestClient(client.app, raise_server_exceptions=False)
    ola, nobody = auth(keys, "ola", **OLA), auth(keys, "nobody", roles=[], groups=[])
    cases = [("state=bogus", ola, 422), ("sort=bogus", ola, 400), ("sort=newest", ola, 400),
             ("sort=bogus", {}, 401), ("sort=bogus", nobody, 403)]
    for query, headers, status in cases:
        for method in ("GET", "HEAD"):
            response = c.request(method, f"/api/v1/quotas:export?{query}", headers=headers)
            assert response.status_code == status, (method, query, status, response.status_code)
    assert client.get("/api/v1/quotas?sort=newest", headers=ola).status_code == 400
    responses = client.get("/openapi.json").json()["paths"]["/api/v1/quotas:export"]["get"]["responses"]
    documented = {s: sorted(responses[s]["content"]["application/problem+json"]["examples"]) for s in ("400", "422")}
    assert documented == {"400": ["invalid-sort"], "422": ["validation-failed"]}, documented     # each refusal, documented
    with ctx.db.session() as s:
        assert not [e for e in AuditRepo(s).recent() if e.action == "quotas.export"]
```

## Finding 3: the `unhandled` log mutant survives. CONFIRMED (a test gap; the production code is right)

**Evidence.** Mutant m6 reverts only `main.py:109` to `path`, and it logged
`"route": "/api/v1/requests/{request_id:request_id}"` (`mutant-m6-log-route-path.txt`). Before the new test, no test asserted
the route of that log.

**Narrowed test.** Reviewer 1's test patched `cmapi.main.log` and asserted the exact keyword arguments. I kept its trigger,
the `ctx` dependency override, which runs after the sign-in and permission and inside the route. The assertion changes to
read the real JSON log line through `capsys`, as the neighbouring `test_cors.py:201-213` does, so the real logger is not
replaced. It passes on head and on r2, and it kills m6.

```python
def test_an_unhandled_failure_of_the_request_read_logs_the_documented_route(world, capsys):
    """The `unhandled` log names the route as the document and the metrics do (`{request_id}`), not with its convertor."""
    from cmapi.routers import ctx as context

    client, *_, keys = world

    def fail():
        raise RuntimeError("the request read failed")

    client.app.dependency_overrides[context] = fail
    try:
        response = client.get("/api/v1/requests/req-20261124-0001", headers=auth(keys, "ola", **OLA))
    finally:
        del client.app.dependency_overrides[context]
    assert response.status_code == 500
    logged = [line for line in capsys.readouterr().out.splitlines() if '"event": "unhandled"' in line]
    assert len(logged) == 1 and '"route": "/api/v1/requests/{request_id}"' in logged[0], logged
```

## Finding 4 (missed by reviewer 1): the export answers 400 `invalid-sort`, but its document lists no 400

**What is wrong, and where.**

- This PR turns a bad sort on `GET /api/v1/quotas:export` into a 400 `invalid-sort` problem (on base, a 200 and then a
  broken stream). The fix for finding 1 adds `newest` to it.
- The route declared no problems: `router.read("/quotas:export", ..., permission="objects:read", media_type="text/csv")`.
  So `cmapi/contract/openapi.json` lists 200, 401, 403, 422 and 503 for the export, and no 400. I measured this on head's
  committed contract.
- The repository's own rule says a refusal that a client meets must be named by the operation's documentation
  (`test_api_samples.py:452-457`).
- Reviewer 1 reported the byte-identical document as a positive. That identity is this gap.

**Fix.** The route declares the problems that `GET /quotas` already declares and that the export can answer. A recorded sample
makes the samples test enforce the rule for it.

```python
@router.read("/quotas:export", summary="Export the quota list as CSV",
             returns="Every row of the quota list with the same filters, in the same order, as CSV: at most 10,000 "
                     "rows.",
             permission="objects:read", media_type="text/csv", problems=["invalid-sort", "validation-failed"])
```

```python
    rec.call("quotas_quotas", "GET", "/api/v1/quotas?sort=nope", ola)                                         # 400 invalid-sort
    rec.call("quotas_export", "GET", "/api/v1/quotas:export?sort=nope", ola)                                  # 400 invalid-sort
```

**The generated files, rebuilt by the README steps in `cmapi/contract/README.md`, "Change the API".** All four are in the
patch.

| File | Change |
|---|---|
| `cmapi/src/cmapi/contract/samples.json` | One entry added, `operationProblems["quotas_export:invalid-sort"]`. I re-recorded and then merged only the new key into the committed file, so the other samples keep their values (`r2-outputs/merge_samples.py`). |
| `cmapi/contract/openapi.json` | 21 lines added: the 400 with its `invalid-sort` example |
| `docs/04-api-examples.md` | The section "400 `invalid-sort` (Export the quota list as CSV)" |
| `cmapi-portal-ui/src/api/schema.generated.ts` | The 400 response type |

The oasdiff gate says the change is not breaking (INFO `response-non-success-status-added`). Spectral, the examples-doc check
and the changelog check pass.

**Test.** It is in the refusal test above: the `documented == {"400": ["invalid-sort"], "422": ["validation-failed"]}`
assertion. Mutant m7 removes the declaration and fails with `KeyError: '400'`. `test_each_operation_has_a_sample_from_a_run`
also fails without the declaration, because of the new sample.

## Mutants of the fix

All seven are killed (`r2-outputs/mutate.py`, logs in `r2-outputs/mutant-*.txt`):

| Mutant | Killed by |
|---|---|
| m1: no sort check in `_query` | refusal test: `('HEAD', 'sort=bogus', 400, 200)` |
| m2: `newest` added to `SORTS` | refusal test: `('GET', 'sort=newest', 400, 200)` |
| m3: HEAD calls `export_csv` again | HEAD test: one `filtered` call |
| m4: the audit before validation | refusal and HEAD tests: two audit events |
| m5: HEAD skips the state check | refusal test: `('HEAD', 'state=bogus', 422, 200)` |
| m6: the `unhandled` log uses `path` | the log test |
| m7: the export declares no problems | refusal test: `KeyError: '400'` |

## Spot checks of reviewer 1's #634 and #635 claims

These were run on the database with the real app (`r2-outputs/spot-head.txt`, `spot-base.txt`).

- **#635, byte identity: confirmed.** The served `/openapi.json` is 428,374 bytes, SHA-256
  `065d775733609040d74ef53fff9892f099f0b5a332e2bea6562f72c1480850b1`, on both base and head. `/openapi.yaml` is 603,739 bytes,
  `733bf7c2…fe133`, on both. Both are exactly reviewer 1's numbers. The committed contracts of base and head are identical
  (`cmp`). Finding 4's fix changes the document on purpose: it adds the 400.
- **#635, action routes: confirmed.**
  - `GET /api/v1/requests/req-x:approve` answers 405 `Allow: POST` on head, and 401 on base.
  - An unknown colon suffix answers 404 with a token on both.
  - `test_a_request_action_is_post_only` passes for all five actions on the database.
- **#634, Allow: confirmed.**
  - A `ConditionalStaticFiles` mount answers `PUT` and `OPTIONS` with 405 `Allow: GET, HEAD` on head, and with no `Allow` on
    base. GET and HEAD of a file answer 200.
  - `DELETE /api/v1/requests/req-x` answers `Allow: GET, HEAD`, and `PUT /api/v1/quotas` answers `GET, HEAD`.
  - `test_405_lists_the_methods_of_the_resource` passes on the database, including the namespace item
    `DELETE, GET, HEAD, PATCH`.

## The two git failures of the full suite

Two tests call `git ls-files` directly, and the export has no `.git`. Both fail with exit status 128, "not a git repository":

- `test_doc_citations.py::test_each_citation_of_the_documents_is_the_text_that_was_recorded_for_it`
- `test_third_pass_converged.py::test_every_shell_script_under_examples_and_deploy_is_executable`

**Cause: the export.** The patch touches no cited line (`doc-citations.py --check` with the shim: 0 problems) and no shell
script. Both files, run again with the shim on PATH, pass: **30 passed** (`r2-outputs/full-suite-git-rerun.txt`).

**So the full suite on r2 is green:** 2584 passed in the full run, plus these 2 passed in the shim re-run, and nothing else
failed. On a git checkout, CI runs them unchanged.

**A shim caution, measured.** My first shim replaced git entirely. It broke the other tests of `test_doc_citations.py`,
which run `git init` in temporary folders (11 errors). The final shim passes everything except `ls-files` outside a
repository through to the real git.

## Defects outside this PR

None found.

## What was not tested

- The portal UI suite (`npm test`) was not run. The patch changes only a generated type file, and the generator's `--check`
  passes.
- CRC and kind were not touched.

## Scratch left in `r2-outputs/`

`before/`, `basecopy/` and `mut/` are full copies, 108 MB each, kept so that the mutants and the before-run can be repeated
(`python r2-outputs/mutate.py <name>`, then `drive.sh focused`). `r2/` has `node_modules` in
`cmapi-portal-ui/tools/openapi-types` and `cmapi/contract/spectral`, from `npm ci`. None of it is in the patch, and all of it can
be deleted.
