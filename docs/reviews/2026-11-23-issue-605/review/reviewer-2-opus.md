# Reviewer 2 report for #605 (`fix/605-head`, 7f0da62)

Reviewer 2 is Opus 5.5 at `high`, and did not write this step. Reviewer 1 was Codex gpt-6.2-astra xhigh (`codex-result.txt`).
Everything below was measured on the export in `review-605/`, on PostgreSQL 16 at `127.0.0.1:55432`, database `cmapi_r2_605`,
with FastAPI 0.115.6, Starlette 0.41.3 and uvicorn 0.32.1. Those are the installed versions, and they match the pins in
`cmapi/pyproject.toml`. No cluster was used. Every pytest run waited for `r2-outputs/gate.sh` first (no `[p]ytest.*tests/service`
or `[n]pm test` process, and a 1-minute load under 16). Each output file records its load.

## Verdict

**Accept, with the patch `r2-outputs/fix.diff`.** It applies to 7f0da62 with `patch -p1 -F0`. I checked this on a fresh copy of
`head/`, and the patched copy is byte-identical to `r2/`. The patch makes these changes:

- The authz test treats HEAD as public wherever GET is public, and every caller must get the same answer from HEAD as from GET.
  This fixes the coordinator's failing test.
- A HEAD of `quotas:export` writes no audit event and makes no CSV.
- Two of reviewer 1's tests are added, and its test-hygiene fix is applied.
- The docs are corrected.

Findings 3 and 4, and two export defects that reviewer 1 missed, all predate this branch. Their fixes and tests are in
`r2-outputs/followups.diff`, which applies on top of `fix.diff`. The coordinator files them.

## Sources, fetched 2026-11-24

- RFC 9110: https://www.rfc-editor.org/rfc/rfc9110.txt, saved as `r2-outputs/rfc9110.txt`, fetched 02:38Z.
  - §9.1, line 3794: "All general-purpose servers MUST support the methods GET and HEAD." The same section also says: "each
    resource determines for itself whether those semantics are implemented or allowed."
  - §9.3.2: "The HEAD method is identical to GET except that the server MUST NOT send content in the response. HEAD is used to
    obtain metadata about the selected representation without transferring its representation data". It also says: "These
    minor inconsistencies are considered preferable to generating and discarding the content for a HEAD request, since HEAD is
    usually requested for the sake of efficiency."
  - §8.6: "a server MUST NOT send Content-Length in such a response unless its field value equals the decimal number of octets
    that would have been sent in the content of a response if the same request had used the GET method."
  - §15.5.6: "The origin server MUST generate an Allow header field in a 405 response containing a list of the target
    resource's currently supported methods."
  - §10.2.1: "An origin server MUST generate an Allow header field in a 405 (Method Not Allowed) response".
  - §9.2.1: "the client did not request that additional behavior and cannot be held accountable for it". Read with §9.3.2,
    this means an audit write on a HEAD is permitted, not forbidden. Finding 1 is therefore decided by cmapi's own design, below.
- Starlette 0.41.3, from the installed source:
  - `routing.py:244-246`: `Route` adds HEAD to a GET.
  - `routing.py:737`: the router keeps only the first `Match.PARTIAL`.
  - `routing.py:281`: the `Allow` header is built from that one route.
  - `staticfiles.py:113-114`: `raise HTTPException(status_code=405)` with no headers.
  - `responses.py:236-249`: `StreamingResponse` iterates its body for a HEAD too.
  - `docs/routing.md` at tag 0.41.3: "Incoming paths are matched against each `Route` in order", and `register_url_convertor`
    for custom convertors.
- FastAPI 0.115.6, from the installed source:
  - `routing.py:494`: `self.methods = {method.upper() for method in methods}`, so no HEAD is added.
  - `routing.py:588-592`: `APIRoute.matches` puts the route in the scope.
  - `exception_handlers.py:11-17`: `http_exception_handler` keeps `exc.headers`.
- Google AIP-136 (https://google.aip.dev/136, fetched 2026-11-24): "The HTTP URI must use a `:` character followed by the custom
  verb". This is used for follow-up C only.

## Rulings on reviewer 1's findings

### Finding 1: an authenticated HEAD on the quota export writes a `quotas.export` audit row. Confirmed. The fix is narrowed.

**What the design says.**
- docs/01, "Audit" (line 780): "An audit\_events table records approvals and rejections, exports, reads that span many
  namespaces, ServiceAccount token issuance ... and admin switches."
- docs/01, line 180: an export "streams every row ... written to the audit log".
- docs/02, line 2221: `core/audit.py` holds "reads of many, exports, approvals, token issuance".
- docs/14 lists `audit:export` with "Routes today 0".

**Why a HEAD writes no row.** The audit records an export, which is data leaving the service. A HEAD transfers no representation
(§9.3.2), so it is not an export, and recording `quotas.export` for it is a false record. The design's other trigger, "reads that
span many namespaces", is not built for any route. `GET /api/v1/quotas` returns the same rows and writes no event. Auditing a HEAD
that returns nothing would therefore be stricter than the list read that returns the data.

**Why not reviewer 1's `quotas.export.head`.** It invents an audit action that the design does not name. A HEAD still leaves an
access trace: the `http` log line carries the method `HEAD`, the route and `caller_sub` (`core/observability.py:174`).

**The CSV.** §9.3.2 prefers not generating content for a HEAD, so the HEAD no longer runs the CSV generator. The headers stay the
GET's, and `Content-Length` stays absent: the GET streams, so its length is not known before the content (§8.6). Validation
(`_in_state`, 422) and the GET's order of evaluation are unchanged.

**Evidence.**
- Before: `before-targeted.txt`, on 7f0da62 with the new tests, gave `assert (200, b'', 1, ...'utdated\r\n']) == (200, b'', 0, [])`.
  The HEAD wrote one export event and made the CSV.
- After: `after-targeted.txt`.
- Mutants: R1, which audits the HEAD, and R2, which makes the CSV for a HEAD, are both killed (`mutants.txt`).

Final code, from `fix.diff`, in `cmapi/src/cmapi/plugins/quotas/__init__.py`. The docstring is unchanged because it is the API
document's text (`core/docs.py:298`), so the contract does not change.

```python
from fastapi import Depends, Query, Request
...
def export(request: Request, q: Text = "", env: Env = None, cluster_id: ClusterFilter = None, team: Team = None,
           tier: Tier = None, state: State = None, sort: Sort = "name",
           who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)):
    """Every row matching the same filters in the same order, capped at 10,000 rows, written to the audit log."""
    # A HEAD (main.py, _serve_head_with_get, #605) sends no rows, so it exports nothing: no audit event, and no CSV made to be
    # dropped. RFC 9110, section 9.3.2: HEAD gets the metadata "without transferring its representation data", and skipping
    # "generating and discarding the content for a HEAD request" is "preferable". The docstring is the API document's text.
    head = request.method == "HEAD"
    rows = [...unchanged...]
    if not head:
        with c.db.session() as s:
            AuditRepo(s).record(who, "quotas.export", "csv", {"rows": len(rows), "q": q, "env": env, "clusterId": cluster_id})
    query = _query(q, env, cluster_id, team, tier, sort, 50, None, None, state)
    lines = c.lister.export_csv(_in_state(rows, state), query, COLUMNS)
    return StreamingResponse(iter(()) if head else lines, media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="quotas.csv"'})
```

The test is `test_a_head_of_the_export_exports_nothing` in `test_head_605.py`; the full text is in `fix.diff`. It uses a real
PostgreSQL audit table, not a spy on `record`. It checks that the HEAD returns 200 with no content, writes 0 events and yields 0
CSV lines, and that the GET then writes 1 event. The HEAD has the same `Content-Type`, `Content-Disposition`, `ETag` and
`Cache-Control` as the GET, and no `Content-Length`.

### Finding 2: the permission sweep runs anonymously only. Confirmed.

Reviewer 1's test is accepted almost unchanged. `assert routes` becomes `assert len(routes) > 20, ...`, so an empty or shrunken
sweep fails.
- Before: the test passes on 7f0da62, as it should for a guard.
- Mutant R3 (`routers/__init__.py`, `require`: `if request.method == "HEAD": return who`) is killed by this test and three others
  (`mutants.txt`).

I did not repeat reviewer 1's tier-only mutant M6. R3 is the same mutation applied to every route.

```python
def test_head_enforces_each_documented_read_permission(world):
    client, *_, keys = world
    headers = auth(keys, "nobody", roles=[], groups=[])
    routes = [r for r in client.app.routes if isinstance(r, APIRoute) and "GET" in r.methods
              and (r.openapi_extra or {}).get("x-cmapi-permission")]
    assert len(routes) > 20, [r.path for r in routes]
    for route in routes:
        path = re.sub(r"\{[^}]+\}", "x", route.path)
        for method in ("GET", "HEAD"):
            response = client.request(method, path, headers=headers)
            assert response.status_code == 403, (method, path, response.status_code)
```

### Finding 3: a 405 can leave supported methods out of `Allow`. Confirmed. It predates this branch, so it is a follow-up.

`probe-before.txt`, measured on 7f0da62:

| Request | Status | `Allow` |
|---|---|---|
| `PUT /api/v1/clusters/CRC/namespaces` | 405 | `HEAD, GET` (POST is missing) |
| `PUT .../namespaces/demo` | 405 | `HEAD, GET` (PATCH and DELETE are missing) |
| `DELETE /api/v1/requests/demo` | 405 | `HEAD, GET` |

It predates the branch: Starlette's first-partial rule (`routing.py:737`, `:281`) is independent of #605. Before #605 the same
requests would say `GET` alone; this is inferred from the code, since the PR only adds HEAD to the set.

Reviewer 1's handler is accepted with one narrowing: it checks `StaticFiles`, the base class, rather than
`ConditionalStaticFiles`. Both give the same answer for the two mounts.

- After: `followup-after.txt`, 314 passed. The probe there shows `PUT .../namespaces` 405 `GET, HEAD, POST` and
  `PUT .../namespaces/demo` 405 `DELETE, GET, HEAD, PATCH`.
- Before: `followup-before.txt` fails on `('PUT', '/api/v1/clusters/CRC/namespaces', 'HEAD, GET')`.

The full code and test are in `followups.diff`: `main.py`, `method_not_allowed`, and `test_405_lists_the_methods_of_the_resource`.

### Finding 4: GET and HEAD on the five POST actions are answered by the request read. Confirmed. It predates this branch, so it is a follow-up. Narrowed.

**What #605 changed.** On 7f0da62, HEAD and GET on `/api/v1/requests/demo:approve` answer 401 anonymously and 404 with a token
(`probe-before.txt`). The answer to HEAD equals the answer to GET, which is what §9.3.2 asks. Before #605, a HEAD there got 405
with `Allow: GET`, which was wrong too. #605 does not regress this, and nothing runs an action.

**Shadowing across the whole app.** The probe of every non-GET route against every GET regex found exactly these five
`SHADOW ... <- GET /api/v1/requests/{request_id}` pairs. The other three hits are shared paths, which finding 3 covers.

**Two changes to reviewer 1's fix.**
- **The convertor excludes every colon** (`[^/:]+`), not just the five verbs. Request IDs are `req-YYYYMMDD-NNNN`
  (`RequestRepo.next_id`), and per AIP-136 a colon starts a custom verb. A sixth action is therefore covered without editing a
  regex.
- **Labels and tests keep the plain path template.** Reviewer 1 missed this side effect: any `{x:conv}` path changes
  `APIRoute.path` to `/api/v1/requests/{request_id:request_id}`. Three things read it:
  - the metric label `cmapi_http_requests_total{route=...}` (`observability.py:170`);
  - the `unhandled` log route (`main.py:109`);
  - the path substitution in `test_review_c_authz.py`.

  The follow-up therefore reads `path_format` in all three. The mutant that restores `path` in `observability.py` is killed:
  `followup-mutant-label.txt` shows 5 failed with `assert 0.0 == (0.0 + 1)`.

**Evidence.**
- Before: `followup-before.txt`, 5 failures `(401, None) == (405, 'POST')`.
- After: `followup-after.txt`. The OpenAPI document is unchanged: `test_api_contract.py` and `test_api_docs.py` pass, and the
  test asserts that `/api/v1/requests/{request_id}` is still in the paths.

### Finding 5: a failed comparison prints the bearer token. Confirmed. Applied.

- Before: `t5-before.txt` (head's helper) fails: `assert 'test-marker' not in "('/api/v1/t....status_code"`.
- After: it passes in `after-targeted.txt`.

```python
    assert head.status_code == get.status_code, (path, get.status_code, head.status_code)    # never the token
```

## The coordinator's failing test (`test_review_c_authz.py::test_declared_permission_is_the_enforced_one_and_every_route_answers`)

**Ruling: the test is wrong, and the code is right.** HEAD is served by the GET's own route, with the same dependencies
(`main.py`, `_serve_head_with_get`). §9.3.2 says HEAD "is identical to GET except" for the content, so a HEAD is public exactly
where its GET is.

The fix exempts `HEAD` where `("GET", path)` is in `PUBLIC`, and it also adds a check. The exemption must not open a gap, so
every route's HEAD must give each of the three callers (no token, viewer, onboarding) the same status as its GET. Public routes
are included in that check.

**Evidence.**
- Before: the coordinator's `wt-605-outputs/full-suite.txt` on 7f0da62, with `('no token', 'HEAD', '/api/v1/version', 200)` and
  others.
- After: `after-targeted.txt` and `full-suite-after.txt`. The printed table in `followup-after.txt` shows every HEAD row equal to
  its GET row, for example `/docs` 503/503/503 and `/api/v1/admin/kpi` 401/403/403.
- Mutant R3 is killed by it.

```python
    rows, bad, answers = [], [], {}
    ...
        answers[(m, path)] = (no, vi, ob)
        # A HEAD is answered by its GET's route (main.py, _serve_head_with_get, #605): RFC 9110, section 9.3.2, "identical to
        # GET except that the server MUST NOT send content", so it is public where the GET is.
        if (m, path) in PUBLIC or (m == "HEAD" and ("GET", path) in PUBLIC):
            continue
    ...
    # And each caller gets from HEAD what it gets from GET, on the public routes too.
    bad += [("head is not its get", path, answers[("GET", path)], got) for (m, path), got in answers.items()
            if m == "HEAD" and got != answers[("GET", path)]]
```

This moves the citations in docs/14 by 6 lines. `doc-citations.py --relocate` moved two: `test_review_c_authz.py:120-183` and
`:198-208`, with `docs/citations.lock.json` updated.

## What reviewer 1 missed

1. **The failing authz test.** Reviewer 1 did not run the suite, and its claim (a) "found no HEAD-only route around
   authentication" did not catch the existing test that HEAD breaks. The fix is above.
2. **A refused export is still audited, and an unknown sort fails after the 200.** Both predate this branch and are filed as
   follow-up A. `probe-before.txt`, on 7f0da62:
   - `GET ?state=bogus` returns 422 and writes an export event (`exports=1`). The audit runs before `_in_state` validates.
   - `GET ?sort=bogus` returns `200 text/csv` and writes an event. The sort is validated inside the CSV generator, so the 400
     comes after the 200 has been sent, and the client gets a 200 with a cut stream.

   The fix:
   - `Lister.export_csv` filters and sorts eagerly and formats lazily (`_csv_lines`).
   - The endpoint builds the lines before the audit.

   After the fix, both methods answer 422 and 400, and no event is written (`followup-after.txt` probe: `exports=0` throughout).
   Before: `followup-before.txt` fails with `('GET', 'sort=bogus') assert 200 == 400`.
3. **The convertor side effect in reviewer 1's finding-4 fix:** `route.path` changes, which renames a metric series. See
   finding 4.
4. **Doc accuracy.**
   - docs/02 and docs/04 said every GET answers HEAD "as RFC 9110, section 9.1 requires". §9.1 places the MUST on the server,
     and leaves each resource to decide. Reviewer 1 noted this under claim (e), but proposed no text. Both now cite 9.1 and 9.3.2
     accurately, and both state the audit rule.
   - docs/14's public-route sentence now says "with the `HEAD` of each".
   - The docstring of `test_head_605.py` named a function that does not exist (`_head_for_each_get`); it is now
     `_serve_head_with_get`.
   - docs/02 is a live doc: the exact passage is in `r2-outputs/LIVE-DOC-EDITS.md`. docs/01 is unchanged.

## Mutants on reviewer 2's fix (`mutants.txt`, each on a fresh copy of the patched tree)

| Mutant | Result |
|---|---|
| R0, the control | 13 passed |
| R1, the HEAD of the export is audited | killed by `test_a_head_of_the_export_exports_nothing` |
| R2, the HEAD of the export makes the CSV | killed by the same test |
| R3, a HEAD skips the permission | killed by 4 tests, including the authz test and the grantless sweep |
| R4, no HEAD on `/healthz`, `/readyz` and `/api/v1/version` | killed by 2 tests in `test_head_605.py` |

The authz test does not catch R4, because a route without HEAD has no HEAD row in its table. `test_every_get_route_answers_head_as_its_get` covers that case.

## Runs on the patched copy (`r2/`)

- **Targeted** (`after-targeted.txt`): `test_head_605.py`, `test_review_c_authz.py`, the API standard, docs, samples and contract
  tests, `test_doc_citations.py`, `test_list_filters.py`, `test_plugins_switch.py` and `test_cors.py`. Result: 349 passed,
  1 failed.
- **Full service suite, once** (`full-suite-after.txt`): **2532 passed, 2 failed in 32:52**, at load 8.4 to 9.0.
  - Both failures are `fatal: not a git repository`. `test_doc_citations.py` and
    `test_third_pass_converged.py::test_every_shell_script_under_examples_and_deploy_is_executable` call `git ls-files`, and the
    export has no `.git`.
  - The same checks without git:
    - `doc-citations.py --check`, run through `r2-outputs/citations-check.py` with a file-system listing in place of
      `ls-files`, gives `doc-citations: 0 problems`, rc 0 (`doc-citations-check.txt`).
    - Executable bits: 0 `.sh` files under `examples/` or `deploy/` lack the user execute bit.
  - Neither failure involves code this patch touches.
  - **The coordinator should run these two tests in the worktree after applying the patch.**
- **The follow-up tree** (`fix.diff` and then `followups.diff`), in `followup-after.txt`: 314 passed. It ran `test_head_605.py`,
  `test_review_c_authz.py`, the API docs, contract, samples and standard tests, `test_list_filters.py`, `test_review_f_obs.py`
  and `test_cors.py`.

## Not tested, and housekeeping

- Nothing was run on kind or CRC. The HEAD body on the wire was not re-measured: reviewer 1 measured it on both uvicorn
  implementations.
- In `head/`, my first run of the citation wrapper created `head/scripts/__pycache__`. I deleted it, and `head/` holds no other
  new file. The `head/scripts` directory's mtime changed as a result.
- No git repository was touched, and nothing was pushed.

## Files

- `r2-report.md`: this report.
- `r2-outputs/fix.diff`: the patch for this branch.
- `r2-outputs/followups.diff`: follow-ups A, B and C, which apply after `fix.diff`.
- `r2-outputs/LIVE-DOC-EDITS.md`: the docs/02 passage.
- Test outputs: `before-targeted.txt`, `after-targeted.txt`, `full-suite-after.txt`, `t5-before.txt`, `probe-before.txt`,
  `followup-before.txt`, `followup-after.txt`, `followup-mutant-label.txt` and `mutants.txt`.
- Scripts: `gate.sh`, `run.sh`, `mutants.sh`, `chain*.sh`, `citations-check.py` and `probes/test_probe_r2.py`.
