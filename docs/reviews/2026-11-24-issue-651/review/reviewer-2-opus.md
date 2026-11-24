# PR #654 (#651): reviewer 2, Opus 5.5 at `high`

Reviewed on 2026-11-24 from the export `review-654/`. I did not write the change or reviewer 1's review.

- **Runs.** Every pytest run used the new-pins venv (`wt-651-outputs/venv`: fastapi 0.162.2, starlette 1.10.0) unless a row
  says `venv-old`. All used PostgreSQL 16 on `127.0.0.1:55432`, database `cmapi_wt605` only, behind the gate
  `until ! pgrep -f "[p]ytest tests/service -q"`. Logs are `r2-outputs/runs/NN-*.txt`; trees and mutants are under
  `r2-outputs/work/`; scripts are under `r2-outputs/probes/`.
- **Nothing outside the export was changed.** No cluster, no GitHub write, and no change to any existing git repository.
  The merge was simulated in throwaway repositories under `r2-outputs/merge/`, built from read-only `git archive` exports of
  `a2a55f3`, `11fd69c` (the PR head), `0bba9ea` and `b97ebb5`.

## Summary

| # | Item | Ruling | Decided by |
|---|---|---|---|
| 1 | Reviewer 1's M1 (the authz table test is vacuous) | **Accepted as written.** It is not brittle, and it catches a partial miss as well as an empty table | runs 10, 19, 20 |
| 2 | Lows L1, L2, L3 | **The text fixes are kept and both new tests are dropped**, because they kill no code mutant (owner's rule). L1/L2 wording corrected: RFC 9110 §9.3.7 makes OPTIONS answers not cacheable | source reading |
| 3 | Strict Content-Type | **Agree: keep FastAPI's default.** Every client re-checked; no test sends JSON without a Content-Type. Added a test that pins the ruling (kills mutant MCT) and a docs/04 rule row | runs 13, 18, 28, 35 |
| 4 | Merge with today's main | Today's `origin/main` is **`b97ebb5` (#652 merged)**. Steps: `git merge -X ours origin/main`, then `patch -p1 -F0 < merge-main.diff`. Found on main: **8 docs/14 citations of `main.py` point at the wrong code since #652's merge commit `359778c`** | runs 37, 38; `doc-citations --check` |
| 5 | HEAD on the shared route objects | **A defect of the tests, not of production.** With any app built first, mutant M4 passes the whole of `test_head_605.py`, and `test_api_standard.py` fails on the PR head in CI's file order. **Fixed** by declaring HEAD where each GET is made | runs 01-03, 12, 14-17, 21-23 |
| 6 | Missed by reviewer 1 | **F0 (High): the upgrade leaks a PostgreSQL pool per app in the test process.** Peak 99 connections against 15 on the old pins, then "sorry, too many clients already" and 500s. Fixed in `AppContext.shutdown`. Also F1-F5 below | runs 31-38 |

## 1. Research: each quote checked against its fetched source

I fetched each source myself on 2026-11-24 into `r2-outputs/research/` and compared it with reviewer 1's copies.

| Source | Fetched | What it says (verbatim) | Reviewer 1 |
|---|---|---|---|
| FastAPI "Strict Content-Type Checking", `docs/en/docs/advanced/strict-content-type.md` at tag 0.162.2 | `strict-content-type-0.162.2.md`, **byte-identical** to R1's copy | "JSON requests **must** include a valid `Content-Type` header (e.g. `application/json`) in order for the body to be parsed as JSON"; "If you need to support clients that don't send a `Content-Type` header, you can disable strict checking by setting `strict_content_type=False`"; "This risk and attack is mainly relevant when the app runs on the **local network** and that is the **only assumed protection**." | Verified |
| FastAPI release notes at tag 0.162.2 | `fastapi-release-notes-0.162.2.md` | line 854, 0.137.0: "Now `router.routes` is no longer a plain list of `APIRoute` objects, it can contain these intermediate objects that can contain additional routers, forming a tree." Line 1235, 0.132.0: "Now FastAPI checks, by default, that JSON requests have a `Content-Type` header with a valid JSON value, like `application/json`, and rejects requests that don't." Line 628, 0.140.0: "Reduce memory usage in dependencies. PR #16049". Line 622, 0.140.1: "Update the lru_cache limit for dependencies to account for large apps. PR #16062" | 0.137.0 and 0.132.0 verified; **0.140.0 not in R1's table** (F0) |
| FastAPI PRs #16049 and #16062 (`api.github.com`, read-only) | `fastapi-pr-16049.json`, `fastapi-pr-16062.json` | #16049, merged 2026-07-24: "So I moved it out of the class and into helper functions." #16062, merged 2026-07-27: "Some users reported a number of dependencies larger than 1024". The installed 0.162.2 has `@lru_cache(maxsize=_CALLABLE_CLASSIFICATION_CACHE_SIZE)` (4096) on `_CallIdentity(call)`, which holds `call` strongly (`fastapi/dependencies/models.py:55-68, 137, 167, 197`) | New |
| Starlette release notes at tag 1.10.0 | `starlette-release-notes-1.10.0.md` | line 98, 1.7.0: "Include `Vary: Origin` on all normal CORS responses and vary preflight responses by all request headers that affect them". Line 175, 1.3.0: "Avoid collapsing exception groups raised from user code [#2830]" | Verified |
| Starlette PR #2830 | `starlette-pr-2830.json` | merged 2026-06-10: "If user code is raising ExceptionGroups eg from TaskGroups or otherwise, they should get ExceptionGroups raised." Installed 1.10.0: `create_collapsing_task_group` is `_utils.py:101-112`, used at `responses.py:278`. uvicorn 0.32.1 sends `spec_version` "2.3" (`h11_impl.py:203`), so production takes that task-group path | **Corrected**: R1 wrote `_utils.py:101-111`; the re-raise is at :112 |
| SQLAlchemy 2.0, "Engine Disposal" | `sqlalchemy-connections.html` | "It's generally not a good idea to rely on Python garbage collection for this to occur for these cases; instead, the Engine can be explicitly disposed using the Engine.dispose() method." | New |
| RFC 9110 (`r1-outputs/research/rfc9110.txt`) | read | §14.2: "An origin server MUST ignore a Range header field that contains a range unit it does not understand." §15.5.21: "(hence a 415 (Unsupported Media Type) status code is inappropriate)". §9.3.7: "Responses to the OPTIONS method are not cacheable." §8.3: "If a Content-Type header field is not present, the recipient MAY either assume a media type of "application/octet-stream" ... or examine the data to determine its type." | §14.2 and §15.5.21 verified |
| openapi-fetch 0.17.0 `dist/index.mjs` (unpkg) | **byte-identical** to R1's copy | `serializedBody === void 0 \|\| serializedBody instanceof FormData ? {} : { "Content-Type": "application/json" }` | Verified |

**Retracted or corrected, in so many words:**
- **R1's L1 test rationale is refuted.** Its docstring and its docs/15 "Why" say that a shared cache must not give "one
  preflight's answer to another". RFC 9110 §9.3.7 says: "Responses to the OPTIONS method are not cacheable."
- **R1's note on 415 is half right.** 415 is the precise status for `text/plain`. For a body with **no** Content-Type,
  §8.3 lets the recipient "examine the data to determine its type", which is what FastAPI 0.115.6 did, so 415 is not
  mandated there. The ruling to keep 422 stands.
- **R1's "an observation, not a finding" (HEAD on the shared routes) is refuted.** R1 said a fix would bring "no measured
  gain"; item 5 measures the gain.
- **The implementer's attribution of "too many clients" is refuted for my runs.** The README attributes the 6 failures of
  "this branch, new pins" to "other agents' suites". In my runs the test process itself held 99 of the server's 100
  connections, while the only other database in use, `cmapi_r1_659`, held 1 to 3 (run 31). This is F0.
- **R1's citation `fastapi/routing.py:494-499`.** The `except Exception as e:` block is `:495-499`; line 494 is the `raise`
  of the HTTPException branch. Minor.
- **R1's merge note for #652's test** dropped the blank line between the third-party and the first-party imports. My
  version keeps the grouping, as `test_head_605.py` in this PR does.

## 2. The rulings

### Item 1: the authz table test (R1's M1): accepted

Reviewer 1's fix compares the table with every operation of the served document:
`assert len(documented) > 30 and documented <= set(answers), sorted(documented - set(answers))`.

| Run | Tree | Result |
|---|---|---|
| 10 | fix | passes |
| 19 | mutant M1: `api_routes` returns `app.routes` only | **fails**: 40 documented operations missing |
| 20 | mutant M1b: `api_routes` drops the `/api/v1/admin` routes | the fixed test **fails** and lists the 8 admin operations; the PR head's unfixed test **passes** |

- **M1b decides that the fix is not only a non-empty check.** A walk that misses one router is caught.
- **It is not brittle.**
  - The document's path items hold only method keys: `delete`, `get`, `patch` and `post` (37 paths and 40 operations,
    measured on `r1-outputs/head-new-openapi.json`).
  - Each path is the route's `path_format`, the same key the table uses.
  - The document comes from `build_openapi`, which walks `iter_route_contexts` itself and not `api_routes`, so it is an
    independent oracle.
  - The floor `> 30` matches the one in `test_head_605.py`.

### Item 2: the three Lows

**L1, the README row for Starlette 1.7.0.**
- **Text: kept, reworded.** The preflight Vary is "Kept, with no test of its own: an answer to OPTIONS is not cacheable
  (RFC 9110, section 9.3.7), so this Vary changes no cache".
- **Test: `test_a_preflight_varies_on_each_request_header_that_decides_it` is dropped.**
  - The preflight's Vary is Starlette's constant `preflight_headers["Vary"]` (`starlette/middleware/cors.py:47-48`).
    No line of cmapi writes it, so the test kills no cmapi mutant.
  - Only a Starlette pin below 1.7.0 would change that Vary, and the change is no defect (§9.3.7).
  - Not run on 1.6.0, which is not installed.

**L2, docs/15.** No test.
- **Kept:** the row now says that a preflight's answer also varies on the three request headers, and its "Why" says that
  OPTIONS answers are not cacheable.
- **Sources** adds Starlette 1.10.0 and RFC 9110 §9.3.7.
- **"Measured" stays at 55 tests.** R1's 57 counted the test dropped under L1.

**L3, `examples/local/INSTALL.md`.**
- **Text: kept.** The guide names no version and says that `requirements.txt` pins each package.
- **Test: `cmapi/tests/core/test_local_pins_doc_651.py` is dropped.** The only mutant it kills is a version written back
  into the prose. The fix removes that cause, because the page names no version, so the test is over-build under the
  owner's rule.

### Item 3: strict Content-Type: agree, keep the default

**Every sender, re-checked:**

| Sender | Sends a body to cmapi? | Content-Type | Evidence |
|---|---|---|---|
| Portal | yes, 9 `api.POST/PATCH/DELETE` calls in `cmapi-portal-ui/src` | `application/json` whenever there is a body | openapi-fetch 0.17.0 (above); `package.json:23` pins 0.17.0 |
| The Git bot | **no**: it calls GitHub and Gitea | n/a; its own calls use httpx `json=` (`core/git/github.py:205,257,266,282,288`, `core/git/gitea.py:133,151,181`) | FastAPI's check applies only to cmapi's own server |
| The worker (`worker.py`, `jobs/*`) | **no** | n/a | It calls Kubernetes, the Git host and Keycloak. `jobs/pr_checks.py:103` only builds a link to `/api/v1/requests/{id}` |
| `deploy/crc-proof.sh:238` | yes (dry-run create) | `header = "Content-Type: application/json"` | read |
| `deploy/kind-test.sh`, `release-crc.sh`, `tests/kind-test-stubbed.sh`, `tests/crc-scripts-test.sh`, `tests/front-door-test.py`, `cmapi/contract/gate-test.sh` | no body to cmapi | n/a | grep for `-X POST/PATCH`, `-d`, `--data`, `json=`, `content=`: their only POSTs go to Keycloak's token endpoint (a form) |
| `examples/local/demo.py` | yes | httpx `json=` | `demo.py:31` |
| `INSTALL.md`, the docs/04 samples | yes | `content-type: application/json` on each | `test_api_docs.py::test_each_operation_has_one_curl_sample_that_the_app_accepts` runs every sample and passes on the new pins |

**The tests.** No test sends JSON with no Content-Type (grep over `cmapi/tests` on head and on main).
- Every raw `content=` request to the API carries a JSON Content-Type: `test_crc_environment.py:96,150`,
  `test_api_docs.py:227` (the sample's own headers), and `test_framework_problems_646.py` on main (`headers=JSON` on each).
- `test_delivery_states_db_review.py:22` and `test_token_renew_398.py:528` send to fakes, not to cmapi.

**Added**, because a decided default that nothing pins can be undone silently:
- **A test**, `test_framework_upgrade_651.py::test_a_body_is_read_as_json_only_with_a_json_content_type`. A signed-in
  dry-run create with the same bytes is 200 with `application/json`, and 422 `validation-failed` with no Content-Type and
  with `text/plain`.

  | Run | Tree | Result |
  |---|---|---|
  | 13 | base, `venv-old` | fails: the body with no Content-Type is answered 200 |
  | 18 | mutant **MCT**, `FastAPI(strict_content_type=False, ...)` in `api_app` | fails; it is the only failure among the 45 tests of `test_framework_upgrade_651`, `test_api_docs` and `test_dry_run_refused_606` |
  | 28 | MCT, after the assertion was made to show the status | fails with `200 != 422` |
  | 35 | fix | passes |

- **A docs/04 rule row** under "Rules for each call": `Content-Type`.
- **docs/02, for the coordinator.** docs/02 has no Content-Type statement either. It is the export of a live Claude Doc,
  so I did not edit the export. Add the same sentence to the live doc's `validation-failed` row, then export.

### Item 5: HEAD on the shared route objects: a defect of the tests, fixed

**Production is not affected.**
- `main.run` starts `uvicorn.run("cmapi.main:create_app", factory=True, ...)` (`main.py:483`): one app per process, and
  every app runs `_serve_head_with_get`.
- The worker builds no app.
- `cmapi-tools openapi render` builds `api_app` without serving it, and `_WithoutHead` filters the document.

**The tests are affected.**
- Since FastAPI 0.137.0 every app in a process shares an included router's route objects.
- FastAPI builds each app's context from the shared route at first use: `_EffectiveRouteContext.from_api_route`,
  `methods=route.methods` (`fastapi/routing.py:1497`).
- So once one app added HEAD to a shared route, every later app's context had HEAD before `_serve_head_with_get` ran.
- The suite therefore tests the first app's case, which is production's, only for the first app that it builds.

| Run | Tree | Order | Result |
|---|---|---|---|
| 01 | M4: the PR head without `route.methods.add("HEAD")` on the context | `test_every_get_route_answers_head_as_its_get` alone | fails (R1's M4 run gives the same) |
| 02 | M4 | after `test_head_is_not_an_operation_of_the_document` | that first test fails; **`test_every_get...` passes** |
| 03 | M4 | `test_head_605.py`, the whole file | **20 passed**: the mutant survives the whole HEAD file |
| 21 | PR head | `test_api_standard::test_the_document_keeps_what_each_route_declares` alone | 3 passed |
| 22 | PR head | after one `world` test of `test_api_docs.py` | **3 failed, `KeyError: 'head'`** (F1) |

CI runs `python -m pytest tests/service -q` in one process (`.github/workflows/ci.yml:104`) in file order, so
`test_api_docs.py` builds apps before `test_api_standard.py` runs. **The PR head is therefore expected to fail CI on F1.**
I did not read the PR's CI result.

**The fix (in `fix.diff`): HEAD is declared where each GET is made, and nothing changes a shared route per app.**
- `core/docs.py`, `DocumentedRouter._register`: `methods=[method, "HEAD"] if method == "GET" else [method]`.
- `routers/health.py`: `/healthz` and `/readyz` become `api_route(..., methods=["GET", "HEAD"])`. They are the only routes
  registered outside `_register` (grep for `@...router.get/api_route/add_api_route`).
- `main.py`, `_serve_head_with_get`: back to base's loop over `app.routes` with `isinstance(route, APIRoute)`, so it
  touches only the app's own routes. The `original_route` line is gone.
- `test_framework_upgrade_651.py`: `test_head_stays_on_a_route_when_its_router_changes` is replaced by
  `test_an_app_changes_no_route_of_a_router_that_it_includes`. The old test covered a rebuild that cmapi never does: no
  router gains a route after import.
- `test_api_standard.py`: the declared document now has the HEAD that the routes declare, so the comparison skips it, as
  `_without_head` does.

| Run | Tree | Result |
|---|---|---|
| 12 | the PR head's code with the new test | **fails**: `assert {'GET', 'HEAD'} == {'GET'}` |
| 10 | fix, the 13-file targeted set, before F1's skip was added | 530 passed and 3 failed, the 3 being F1's test (run 23 has the skip) |
| 23 | fix, `test_api_standard.py` after a `world` test | 178 passed |
| 14 | BM1: `_register` without HEAD | 16 failed, with another app built first |
| 15 | BM2: the health routes without HEAD | 2 failed (`test_every_get...`, `test_head_is_not_an_operation...`), with another app built first |
| 16 | BM3: `_serve_head_with_get` a no-op | 5 failed, the new test among them |
| 17 | BM4: HEAD on the shared `original_route` again (the PR head's function) | 1 failed: the new test only |

Every mutant of this fix is killed in an order with another app built first, so a kill no longer depends on test order.

### Item 6, F0 (High): one open connection pool per app, kept for the life of the test process

**What happens.**
- Since FastAPI 0.140.0 (PR #16049; 4096 entries since 0.140.1, PR #16062), three process-wide `lru_cache`s keep each
  dependency's callable through `_CallIdentity(call)`.
- Through those callables an app's `AppContext`, and with it the SQLAlchemy pool of that context's `Database`, stay alive
  after the lifespan ends.
- `AppContext.shutdown` stopped the registry and the Git layer, but never the pool.
- Production builds one app per process, so it is unaffected. The service suite builds an app per test in one process.

| Run | Tree | Result |
|---|---|---|
| 32 | the merged tree, new pins: the probe builds 5 worlds | connections after each world `[2, 3, 4, 5, 6, 7]`; contexts alive after `gc.collect()`: **5 of 5**; FastAPI's caches hold 140, 102 and 140 entries; after `cache_clear()`, **0 alive** and 3 connections |
| 33 | main `b97ebb5`, `venv-old`: the same probe | `[2, 3, 3, 3, 3, 3]`, **0 of 5 alive** |
| 31 new | the 16-file set on the merged tree, new pins, sampling `pg_stat_activity` every 3 s | **peak 99** connections on `cmapi_wt605`; 10 failed: 500s from `psycopg.OperationalError: ... FATAL: sorry, too many clients already` (in the log's `unhandled` lines), and `/readyz` `degraded` |
| 31 old | the same set on main `b97ebb5`, `venv-old` | **peak 15**; 1 failed, `test_doc_citations`, because the export is not a git repository |
| 25, 30 | the 17-file merged set, before the fix | 10 and 9 failed, the same 500s |

`/Users/olasumbo/gitRepos/workbench/cmapi/review-654/r2-outputs/probes/leak/test_r2_probe_leak.py` is the probe. It is not
part of the patch.

**Fix.** `core/context.py`, `AppContext.shutdown`: after the registry and the Git layer, `self.db.engine.dispose()`. The
comment cites FastAPI's cache and SQLAlchemy's "Engine Disposal". `test_git_layer.py` calls `shutdown` twice, and
`dispose()` can run twice: the engine opens a new pool if it is used again.

**Test.** `test_framework_upgrade_651.py::test_an_app_that_ends_closes_its_database_connections`: inside a world,
`/readyz` leaves at least one connection in the pool; after the world ends, `ctx.db.engine.pool.checkedin() == 0`.

| Run | Tree | Result |
|---|---|---|
| 34 | the PR head's code with the new test | **fails**: `assert 1 == 0` |
| 36 | mutant MDISP, the fix without `dispose()` | **fails** the same way |
| 35 | fix | `test_framework_upgrade_651.py`: 15 passed |
| 37 | the final merge, 18 files with `test_git_layer`, with the sampler | **581 passed**, peak **6** connections, no "too many clients" |

### Item 4: the PR on today's main

`origin/main` moved during the review to **`b97ebb5`, "Merge pull request #652"**. Its tree equals `359778c`
(`git diff --stat` is empty).

**Conflicts.** A plain `git merge` in a throwaway repo, of the PR head plus `fix.diff` against `b97ebb5`, gives:
- `cmapi/src/cmapi/main.py`: one hunk, in `method_not_allowed`: #654's docstring against #645's first body lines.
- `docs/14-authorization.md`: 2 hunks.
- `docs/citations.lock.json`: 3 hunks.

Every docs hunk differs only in digits (checked by a script that compares the two sides with the digits masked).

**How to apply.**
1. On the PR branch, with `fix.diff` committed, run `git merge -X ours origin/main`. `-X ours` keeps #654's side of each
   conflicting hunk.
2. Run `patch -p1 -F0 < review-654/r2-outputs/merge-main.diff`.

**What the patch does:**
1. **`method_not_allowed`** keeps #654's docstring and gets #645's body back (`headers = dict(exc.headers or {})`,
   `allow = None`). The body already calls `api_routes(app)`, because the merge takes #654's line.
2. **#645's comments in `main.py`** cited Starlette 0.41.3 and FastAPI 0.115.6 lines without naming the version. They now
   cite the installed lines, each read:
   - Starlette 1.10.0: `routing.py:639` and `:284`; `staticfiles.py:120, :125, :129, :134, :158`;
     `requests.py:297, :311`.
   - FastAPI 0.162.2: `routing.py:1316-1321` (a route of an included router) and `:495-499` (the body's 400).
   - `_exception_handler.py:46-50`, the same lines in both versions.
   - `test_framework_problems_646.py:106` now cites `requests.py:297`.
3. **#652:**
   - `test_client_input_653.py::test_every_request_body_is_a_request_body` walks `api_routes(client.app)`. On the new pins
     it found no route (R1's run 12: `assert 0 >= 10`).
   - `UnhandledToProblemMiddleware`'s comment says that 1.10.0 raises a stream's failure itself (`responses.py:278`,
     `create_collapsing_task_group`, `_utils.py:101-112`). The loop stays for groups that the application raises
     (Starlette 1.3.0, #2830).
   - `RefuseNulMiddleware`'s docstring says that a NUL in a static path was 500 on 0.41.3 and is 404 on 1.10.0
     (`staticfiles.py:132-134`). The middleware answers 422 first in both cases.
4. **docs/14, docs/15 and the lock are rebuilt from main before #652 (`0bba9ea`), then relocated** (F2).
   - `0bba9ea`'s cited texts are each identical to `a2a55f3`'s (checked).
   - #652 changed nothing in docs/14 but citation digits (3 lines, checked).
   - After the patch, `scripts/doc-citations.py --check` reports **0 problems**.
   - Every `main.py` citation of docs/14 now holds the code its sentence names: `include_router(health.router)`, the
     `authed_routers` line, `if docs_enabled:`, `_add_problem_pages`, the `guard = ...` line of `docs.public`, and
     `/docs/oauth2-redirect`.
5. **docs/15's "Response headers a page can read" row gains `Allow`** (F3).

| Run | Tree | Result |
|---|---|---|
| 37 | the final merge with `b97ebb5` plus `merge-main.diff`, 18 files: #645's `test_router_problems_644` and `test_framework_problems_646`; #647's `test_non_utf8_names_626` and `test_non_utf8_review_647`; #652's `test_client_input_653` and `test_value_error_648`; then `test_framework_upgrade_651`, `test_head_605`, `test_cors`, `test_review_c_authz`, `test_api_standard`, `test_api_docs`, `test_dry_run_refused_606`, `test_plugins_switch`, `test_doc_citations`, `test_api_contract`, `test_if_match_surface_581` and `test_git_layer` | **581 passed** in 13 min, peak 6 connections |
| 38 | the final merge, `tests/core` | **750 passed, 113 skipped** |

## 3. Findings that reviewer 1 missed

**F0 (High): one open connection pool per app in the test process.**
- **What:** see item 6. Up to 99 of PostgreSQL's 100 connections are held, then the 500s follow.
- **Fix:** `AppContext.shutdown` disposes the engine.
- **Test:** runs 32-36 and 37.

**F1 (Medium): `test_api_standard` fails on the PR head in CI's file order.**
- **What:** `test_api_standard::test_the_document_keeps_what_each_route_declares` fails on the PR head whenever an app was
  built earlier in the process (`KeyError: 'head'`).
- **Fix:** item 5's fix, plus a skip of `head` in the test, as `_without_head` does.
- **Test:** runs 21 and 22 (before), 23 (after).

**F1b (Medium): the suite does not test the first app's case, which is production's.**
- **What:** mutant M4 passes the whole of `test_head_605.py` once any app has been built.
- **Fix:** item 5's fix.
- **Test:** runs 03, 12 and 14-17.

**F2 (Medium, on main from #652, not from #654): 8 docs/14 citations of `main.py` hold the wrong code.**
- **What:** commit `359778c`, "Merge origin/main (#647) into #648 #653: citations relocated", rewrote the lock text of 8
  docs/14 citations with the code that then sat at their stale line numbers:
  - `docs.public`'s guard became a line of `_serve_head_with_get`'s docstring (`main.py:343`);
  - `/problems` (`318-332`) became `framework_refusal`'s body;
  - the health routers (`141-142`) became `RefuseNulMiddleware`'s `await self.app(...)`.
- **Why `--check` misses it:** the lock now holds that wrong text, so the check passes. Every other lock entry's text equals
  `0bba9ea`'s.
- **Fix:** `merge-main.diff` restores the 8 citations and relocates them.
- **Test:** `doc-citations --check` reports 0 problems afterwards, and the citations read right.
- **File an issue** with fix-defect, parent #648.

**F3 (Low, on main from #645): docs/15 does not list `Allow`.**
- **What:** docs/15's "Response headers a page can read" row omits `Allow`, which `core/cors.py` `EXPOSED_HEADERS` lists
  since #645.
- **Fix:** `merge-main.diff`.
- **Test:** none for the doc; `test_cors.py` on main already pins `EXPOSED_HEADERS`.

**F4 (Low): the strict Content-Type ruling had no test and no rule in the docs.**
- **Fix:** item 3.
- **Test:** runs 13, 18, 28 and 35.

**F5 (Low): stale framework line citations after the upgrade.**
- **What:** #645's and #652's framework line citations in `main.py` give 0.41.3 and 0.115.6 lines without the version.
- **Fix:** `merge-main.diff`.
- **Test:** each line was read against the installed 1.10.0 and 0.162.2 sources.

## 4. Mutants of the final fix

| Mutant | Change | Killed by | Run |
|---|---|---|---|
| M1 | `api_routes` returns `app.routes` only | the fixed authz test (and 20 other tests, R1's run 04) | 19 |
| M1b | `api_routes` drops `/api/v1/admin` | the fixed authz test; the PR head's version of it survives | 20 |
| M4-head | on the PR head, no HEAD on the context | **survives** the whole of `test_head_605.py` once an app has been built (the defect) | 03 |
| BM1 | `_register` without HEAD | 16 tests of `test_head_605.py` | 14 |
| BM2 | the health routes without HEAD | `test_every_get_route_answers_head_as_its_get`, `test_head_is_not_an_operation_of_the_document` | 15 |
| BM3 | `_serve_head_with_get` a no-op | 5 tests, the new one among them | 16 |
| BM4 | HEAD on the shared `original_route` again | `test_an_app_changes_no_route_of_a_router_that_it_includes` | 17 |
| MCT | `strict_content_type=False` | `test_a_body_is_read_as_json_only_with_a_json_content_type` | 18, 28 |
| MDISP | `AppContext.shutdown` without `dispose()` | `test_an_app_that_ends_closes_its_database_connections` | 36 |

## 5. The patches

**`r2-outputs/fix.diff`**, against `head/`: 14 files under `cmapi/`, `docs/` and `examples/local`. It holds no bytecode,
and `examples/src` is left out because it is a symlink.
- **Code:**
  - F0: `core/context.py`.
  - Item 5: `core/docs.py`, `routers/health.py` and `main.py`.
- **Tests:**
  - `test_framework_upgrade_651.py`: the three new tests, and the test they replace.
  - F1's skip: `test_api_standard.py`.
  - R1's M1: `test_review_c_authz.py`.
- **Docs:**
  - the L1, L2 and L3 text: the README, docs/15 and INSTALL.md;
  - the docs/04 row;
  - the HEAD row of `docs/GLOSSARY.md`, which now names `DocumentedRouter._register`;
  - the README's new 0.140.0 row, and its corrected "too many clients" attribution;
  - docs/14, docs/15 and the lock, relocated with `doc-citations --relocate`; `--check` then reports 0 problems, run in a
    throwaway git copy.
- **Applies:** with `patch -p1 -F0` to a fresh copy of `head/`, cleanly, and it reproduces `work/fix`.

**`r2-outputs/merge-main.diff`**, to apply after `git merge -X ours origin/main` (`b97ebb5`): 6 files. It applies with
`patch -p1 -F0` to a fresh checkout of the merge commit, cleanly. `doc-citations --check` then reports 0 problems.
The merged tree that runs 37 and 38 tested differs from the final one only in the review README's two rows (F0's
record), and `merge-main.diff` is byte-identical for both. `origin/main` was still `b97ebb5` at the end of the review.

## 6. Not done

- Not run: the whole service suite (the brief), CI, kind, CRC and the image build.
- Starlette 1.6.0 was not installed, so L1's test was not run against it. The ruling rests on `cors.py:47-48` and RFC 9110
  §9.3.7.
- The live Claude Doc behind `docs/02` was not edited. That is the coordinator's step (item 3).
- GitHub: the PR's CI result for F0 and F1 was not read.
- FastAPI's cache keeps each app's other objects in memory, up to 4096 callables, after the pool is closed. This is not
  measured beyond the 5-world probe. It is bounded, and it is not a connection.

## 7. Who wrote what

- **Reviewer 1** (Opus 5.5, standing in for Codex) wrote these parts of `fix.diff`:
  - the M1 assertion;
  - the L1 README row, reworded here;
  - the L2 docs/15 row, with its "Why" reworded here;
  - the L3 INSTALL.md text.
- **Reviewer 2** (Opus 5.5, high) wrote every other line of `fix.diff`, all of `merge-main.diff`, and
  `probes/resolve.py`, which produces `merge-main.diff`.
