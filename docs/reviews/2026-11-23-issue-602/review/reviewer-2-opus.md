# PR #607, reviewer 2 (Opus 5.5 at high)

Head f6206e9, from the export in `review-607/head/`. I did not write this PR. I worked in `review-607/r2/`, a copy of
`head/`, and kept scratch in `review-607/r2-work/`. I did not touch a git repository, push anything, or write to CRC.

All database runs used PostgreSQL 16 on `127.0.0.1:55432`, in databases of my own (`cmapi_r2_607_head`, `_fix` and
`_mut`). I created them and dropped them at the end. The runs used the service suite's fakes for Git and Kubernetes, so
no cluster was involved.

**Outputs:**

- the patch, `r2-outputs/fix.diff`: 15 files, 887 lines, against f6206e9;
- the final live-doc edits, `r2-outputs/LIVE-DOC-EDITS.md`;
- every run log, in `r2-outputs/runs/`.

**Patch proof.** `patch -p1` of `fix.diff` onto a fresh copy of `head/` gives a tree identical to `r2/`, by `diff -rq`.

## Rulings

| # | Reviewer 1's finding | Ruling | Test that decides |
|---|---|---|---|
| 1 | High: a repeated `dryRun` can submit | **Confirmed on all six writes. Codex's fix accepted, with a tighter error body: 422 `validation-failed`.** | `test_dry_run_once_607.py` (new) |
| 2 | Medium: a delete preview of a held namespace is 200, and the delete is 409 | **Behavior confirmed. Codex's delete-only holder check is rejected.** All six previews skip the lock, as docs/01 decides. The parity *claim* is wrong and is narrowed instead. | `test_a_delete_dry_run_skips_the_lock_as_every_dry_run_does` (new) |
| 3 | Docs and claims | **All four claims confirmed by measurement.** The wording is fixed in the route descriptions, `DRY_RUN_RETURNS`, `DryRun`, GLOSSARY, the decision record and LIVE-DOC-EDITS. | `test_sign_in_comes_first_then_the_guard_then_the_permission`, `test_the_document_says_dry_run_is_sent_once` (new) |
| 4 | Three surviving mutants | **All three confirmed to survive the PR's tests, and killed by new assertions.** M2 is equivalent on today's code; see below. | the mutant table below |

### 1. A repeated `dryRun` (High): confirmed and fixed

**Measured on f6206e9** with the real database and a counting wrapper around `_submit` (`runs/probe-head.txt`). The
last value wins, because Starlette's `QueryParams` gives the last value of a scalar:

| Write | `dryRun=true&dryRun=false` | `dryRun=false&dryRun=true` | `dryRun=` | `dryRun=1` | `dryRun=0` | `dryRun=maybe` |
|---|---|---|---|---|---|---|
| create | **202, submit called 1 time** | 200 plan | 422 | 200 plan | 202 | 422 |
| change | **202, 1 submit** | 200 | 422 | 200 | 202 | 422 |
| delete | **202, 1 submit** | 200 | 422 | 200 | 202 | 422 |
| extend | **202, 1 submit** | 200 | 422 | 200 | 202 | 422 |
| set (on a permanent namespace) | **202, 1 submit** | 200 | 422 | 200 | – | – |
| makePermanent | **202, 1 submit** | 200 | 422 | 200 | 202 | 422 |

Codex measured only the reverse order, where the preview client loses: `dryRun=true&dryRun=false` writes. That is the
dangerous order, because it is what an HTTP layer produces when it appends a default `dryRun=false` to a preview.

The empty value and `dryRun=1` were asked about:

- **Empty (`dryRun=`):** 422 `validation-failed` on all six. FastAPI's Boolean parse refuses it, and nothing is submitted.
- **`dryRun=1`:** a preview on all six. `dryRun=0` is a real write. This is FastAPI's documented Boolean reading. It is
  safe, and the fix leaves it unchanged.

**422 or 400.** I rule for 422 `validation-failed`:

- A repeated `dryRun` is a value of a *supported* Boolean that is not one Boolean. That is the same class as `dryRun=maybe`
  and `dryRun=`, which cmapi already answers with 422 `validation-failed` (FastAPI's binding, `main.py:194-202`).
- cmapi's 400s split the other way. `invalid-cursor`, `invalid-sort` and `invalid-limit` (`core/docs.py:75-79`) are cmapi's
  own semantic checks of a parsed value, and `dry-run-not-supported` refuses a parameter that the route does not have.
  `limit=abc` is 422 and `limit=30` is 400 `invalid-limit`.
- Kubernetes answers an unaccepted dryRun value on a call that supports dry run with 422. In
  `staging/src/k8s.io/apiserver/pkg/endpoints/handlers/create.go` (master, fetched 2026-11-23):
  `if errs := validation.ValidateCreateOptions(options); len(errs) > 0 { err := errors.NewInvalid(...)`.
  `NewInvalid` sets `Code: http.StatusUnprocessableEntity` (`apimachinery/pkg/api/errors/errors.go`). `ValidateDryRun`
  appends `field.NotSupported` unless `allowedDryRunValues.HasAll(dryRun...)`.

The error body takes the same form as FastAPI's own 422: one `errors` entry with `field: "query.dryRun"`,
`message: "send it at most once"` and `code: "too_many_values"`.

**Fix (`core/docs.py`).** A new `refuse_repeated_dry_run`. `DocumentedRouter._register` adds it to every write that has
a `dry_run_model`, so a future plugin's write gets it too. It also adds `validation-failed` to the route's codes when
the route lacks it; all six have it today, so the document does not change structurally. The nine-route presence guard is
unchanged. Codex's `elif` was right; I took its structure, with the error body above.

**Tests.**

| Test | Before (f6206e9) | After |
|---|---|---|
| `test_dry_run_once_607.py::test_a_repeated_dry_run_is_refused_on_each_write_and_submits_nothing` | **fails**: "POST /api/v1/clusters/CRC/namespaces?dryRun=true&dryRun=false reached _submit: the last dryRun decided, and it wrote" | passes: three orders × six writes, 422 with the `errors` entry, no submit, no `change_requests` row |
| `test_one_dry_run_is_read_as_fastapi_reads_a_boolean` | passes | passes. It pins `true` and `1` as a preview and empty as 422 on all six, with only the two setup requests created |
| `test_the_document_says_dry_run_is_sent_once` | **fails**: the `dryRun` description has no "at most once" | passes |
| `test_dry_run_refused_606.py::test_every_write_without_a_dry_run_refuses_one`, which now also asserts `refuse_repeated_dry_run` on the six | **fails**: `'refuse_repeated_dry_run' in {'caller', 'ctx', 'dep', 'idempotency_key'}` | passes |

### 2. A held namespace (Medium): behavior confirmed, delete-only check rejected, claim narrowed

**Measured on f6206e9** (`runs/probe-head.txt`). Delete request `req-20261123-0002` held payments-dev in
`pending_approval`. The previews and the same writes with a fresh key gave:

| Write | Preview | Same write, fresh key |
|---|---|---|
| change | 200 | 409 `change-pending` `req-20261123-0002` |
| delete | 200 | 409 `change-pending` `req-20261123-0002` |
| extend | 200 | 409 `change-pending` `req-20261123-0002` |
| makePermanent | 200 | 409 `change-pending` `req-20261123-0002` |
| create of a name held by a pending create | 200 | 409 `change-pending` `req-20261123-0001` |

**Today all six previews skip the lock.** That is the decided design. docs/01, line 262, says: "A dry run (?dryRun=true)
returns 200 with the plan ...; it skips the idempotency and lock steps, reserves nothing". Step 4 of that pipeline is
"**Lock.** At most one open request per namespace" (docs/01, line 237).

The portal is built on it. The stand-in API returns the dry run before its `openRequest` check
(`cmapi-portal-ui/tests/api/standin.mjs:1204-1212, 1275-1278, 1338-1344`). The portal test 484-T8 says "the dry run does not
check it, the submit does (repo.py)" (`portal.test.mjs:4774`).

**Why I reject Codex's fix.** It adds a holder check to the delete only. That would make the delete the one preview of six
that answers 409. It would contradict docs/01:262 and reopen a decided design.

AIP-163 (<https://google.aip.dev/163>, fetched 2026-11-23) says "a request using validate_only must fail if it determines
that the actual request would fail". That supports a holder check, but on **all six**, with the portal stand-in and docs/01
changed together. That is a design change, so it is the owner's call and not part of this PR. My recommendation is to keep
docs/01 as it is: the lock is checked at submit, and the portal already shows the holder before a Check. One question for
the owner, if wanted: "Should every dry run answer 409 `change-pending` while another request holds the namespace
(AIP-163), changing docs/01:262 and the portal stand-in?" I recommend no.

**What is fixed is the claim.** The PR's route description and its LIVE-DOC-EDITS said "it is refused where the delete
would be". The new text:

- the delete description says the preview "makes the delete's planning checks" and "like every dry run it skips the
  Idempotency-Key and the namespace's lock: while another request holds the namespace the plan is still 200, and the delete
  is 409 `change-pending`";
- the docs/02 "Dry run" row and GLOSSARY carry the same rule;
- a new test, `test_a_delete_dry_run_skips_the_lock_as_every_dry_run_does`, pins the documented behavior (the preview is
  200, the delete is 409 naming the holder, no rows change). It passes before and after, as a test of documented existing
  behavior should.

### 3. Docs and claims: each measured

| Claim | Measured on f6206e9 (`runs/probe-head.txt`) | Ruling |
|---|---|---|
| "400 before 401" (decision record, and the comment in `docs.py`) | Without a token, `:approve` and `auto-approval:pause` answered **401** `unauthenticated`, with `WWW-Authenticate`, for no `dryRun`, `?dryRun=true` and a repeated `dryRun`. A signed-in requester got **400** with `dryRun` and **403** without it. Malformed JSON without a token got **422**. | **Refuted.** The order is 422 (an undecodable body), then 401 sign-in, then the guard, then the permission. `get_request_handler` in FastAPI 0.115.6 decodes JSON before `solve_dependencies`, and `include_router(dependencies=[authed])` puts sign-in first. |
| "Writes nothing" | With the production `DbKeyStore` and a cold key cache, a delete preview answered 200, wrote **1 row to `jwks_keys`**, and changed `change_requests` by 0. | **Too strong.** The text now says what a preview does not create: no change request, lock, reservation, job or pull request. |
| "Every file of the folder" | With a `README.md` and `extra/sub.yaml` in the folder, `changes` listed only the five direct `.yaml` files. The code agrees: `github.py:69-77` and `gitea.py` `read_folder` keep `.yaml` files at the top of the folder. | **Refuted.** The text now says "each `.yaml` file directly in the namespace's folder". |
| The refusal counter | A protected delete preview answered 422 `namespace-protected`, and `cmapi_plan_refusals_total` changed by **0**. `RECORDED` is `policy-violation` plus `CMAPI_REFUSALS` (`rejections.py:38`). | **Refuted** as written. The decision record now names `RECORDED`. |

**Wording applied, tightened from Codex's:**

- `DRY_RUN_RETURNS`: "Dry run (`?dryRun=true`): the plan. The call opens no change request, takes no lock or reservation,
  queues no job and opens no pull request."
- `DryRun`: "With `true`, the call returns the plan with status 200 and needs no Idempotency-Key. It opens no change
  request, takes no lock or reservation and opens no pull request. Send it at most once: a repeated `dryRun` is 422
  `validation-failed`."
- The delete description: as quoted in section 2.
- The create and PATCH descriptions: the earlier "writes nothing" and "nothing is written" were also refuted by the JWKS
  measurement. They now read "opens no request" and "no request is opened". These two changes predate the PR.
- `dry-run-not-supported`: the example detail "This call has no dry run: send it without dryRun" is now "This call has no
  dry run, and nothing was done". The old text advised running the action. The problem action in `problem_docs.py` now
  reads: "Nothing was done: this call has no dry run. A preview stops here. Send the call without `dryRun` only to do the
  action."
- GLOSSARY, `?dryRun=true` row: the skip of key and lock, the 422 on a repeated value, and "after sign-in and before its
  permission check".
- The decision record (`docs/reviews/2026-11-23-issue-602/README.md`):
  - the paragraph on 400 before 401 is replaced with the measured order;
  - the refusal-counter claim names `RECORDED`;
  - the file claim is now the direct `.yaml` files;
  - the lock skip and the JWKS write are added;
  - the client migration note from Codex is added;
  - a section "#607 review: one `dryRun` at most" is added, with the Kubernetes sources.
- `docs/14-authorization.md` and `docs/citations.lock.json`: three citations relocated by `doc-citations.py --relocate`.
  The texts are unchanged; the lines moved.

**LIVE-DOC-EDITS**, final, in `r2-outputs/LIVE-DOC-EDITS.md` (reproduced in full below). Each "Old" text was matched
exactly against the export at docs/02:128, docs/02:129, docs/01:262 and docs/01:730. The patch does not edit
docs/01 or docs/02.

### 4. The mutants: each survives the PR's tests and is killed by a new assertion

Each mutant ran in a full tree copy of its own (`r2-work/m1a`, `m1b`, `m2`, `m3`), because `pyproject.toml` sets
`pythonpath`. The PR's test files went in as `test_head_*.py`, beside the new ones (`runs/mut-*.txt`).

| Mutant | PR's tests (f6206e9) | New assertion | Result |
|---|---|---|---|
| M1a: `require_if_match(etag, "delete")` moved to the first line of the delete route | 5 passed (**survives**) | `test_a_delete_dry_run_fails_where_the_delete_would` now also sends an unknown namespace without If-Match and expects 404 | **killed**: `(428, 'precondition-required') == (404, 'object-not-found')` |
| M1b: `require_if_match` moved before the namespace lookup in `plan_delete` | 5 passed (**survives**) | the same assertion | **killed**: the same |
| M2: `refusals(..., dry_run=False)` forced in the delete | 5 passed (**survives**) | new `test_a_delete_dry_run_counts_a_recorded_refusal_and_stores_none`: inject a `policy-violation` from `plan_delete`; the preview gives `cmapi_plan_refusals_total{dry_run="true"}` +1 and the stored `policy_rejections.count` +0; the delete gives `dry_run="false"` +1 and stored +1 | **killed**: `(0.0, 1.0, 1) == (1.0, 0.0, 0)` |
| M3: the guard refuses only when exactly one `dryRun` is present | 4 passed (**survives**) | `test_an_approve_or_a_cancel...` now also sends `dryRun=true&dryRun=false` and the reverse order to `:approve` | **killed**: **200**, and the request was approved |

M2 is an **equivalent mutant on today's code**. `plan_delete` raises no code in `RECORDED`: its 422s are
`cluster-not-writable`, `environment-not-served`, `plugin-disabled` and `namespace-protected`. So no real delete stores a
refusal in either mode. The new test therefore injects the refusal. It guards the route's wiring for a future delete rule.
I used the real counter and the real table rather than mocking `_store_refusal`. Codex's point that counting rows misses an
`ON CONFLICT` update is met by summing `count`.

## What reviewer 1 missed

1. **The dangerous order of finding 1.** Codex measured `false&true` as a preview and called the reverse order a submit.
   That is correct, but its regression test only checked that the sentinel was not reached. Measured on all six writes,
   `dryRun=true&dryRun=false` is a real 202 write: the order a preview client produces when its HTTP layer appends a
   default `false`. The new test sends both orders and a duplicate `true`, on all six writes.
2. **Finding 2's fix contradicts a decided design.** docs/01:262 decides that a dry run skips the lock. The other five
   previews and the portal's stand-in and test 484-T8 rely on it. Codex did not check docs/01 or the other previews.
   Measured: all six previews skip the lock today.
3. **The create and PATCH descriptions also said "writes nothing".** These predate the PR and are fixed here.
4. **`docs/01:262` "writes no row"** falls to the same JWKS measurement. It is in LIVE-DOC-EDITS.
5. **The `dry-run-not-supported` example detail** ("send it without dryRun") is the same unsafe advice that Codex found
   in `problem_docs.py`, but it is also the problem's recorded detail in `samples.json`, openapi and docs/04. Both are
   fixed.
6. **M2 is equivalent today.** This is stated above, so that the test is not read as proof of a live path.

Two items do not belong in this PR. The coordinator may file them:

- **(possible defect, low)** "the folder leaves Git after approval" (the delete description, which predates the PR). The
  delete removes only the direct `.yaml` files, because `renderer.delete` maps only the files the provider listed. A
  non-YAML file or a subfolder in a namespace's folder stays in Git after a delete. I did not measure this end to end
  through a merged delete; the reading is from `render/manifests.py:226-229` and the providers' `read_folder`.
- **(observation)** The busy check in the brief, `pgrep -f "[p]ytest tests/service"`, does not match
  `python -m pytest -W ignore ... tests/service/...`, so it misses runs that pass flags first. Another agent's
  `test_migrate_log_614.py` runs were invisible to it. `pgrep -f "[p]ytest.*tests/service"` catches them. My script
  waited on that pattern.

## Before and after

| Run | Before: f6206e9 | After: r2, the patched tree |
|---|---|---|
| The 9 node IDs Codex listed (`test_delete_dry_run_602.py`, `test_dry_run_refused_606.py`) | **9 passed** (`runs/before-tests.txt`) | 9 passed, plus 5 new and strengthened (`runs/after-tests.txt`, `runs/final-after.txt`) |
| New and strengthened tests on f6206e9 (`runs/newtests-on-head.txt`, `runs/newtests-607-on-head.txt`) | 3 fail as intended: `test_every_write_without_a_dry_run_refuses_one`, `test_a_repeated_dry_run_is_refused...`, `test_the_document_says_dry_run_is_sent_once`. The rest pass: they pin existing behavior, and M1 to M3 are killed by mutation, not by head. | all pass |
| `test_api_standard.py`, `test_api_docs.py`, `test_api_samples.py` | all passed | all passed. 241 tests in the full after run. The final run of the five files, after the last edit: **218 passed** |
| `test_doc_citations.py` in the export | 1 failed: `git ls-files` exit 128, because the export is not a git repository | the same environment failure |
| `test_doc_citations.py` and `scripts/doc-citations.py --check`, in scratch copies made with `git init` and `git add -A` (`r2-work/cite-head`, `cite-fix`) | 12 passed; 0 problems | 12 passed; 0 problems, after `--relocate` of three docs/14 citations |
| `contract/gate.sh` (oasdiff 1.37.0) | – | base→r2: no breaking change, exit 0. head→r2: no breaking change, exit 0. `changelog` base→r2: 11 info, 0 warning, 0 error, the same as the PR. head→r2: no changes, because only descriptions and examples changed |
| `contract/lint.sh` (Spectral, linked read-only from `wt-602`) | – | "No results with a severity of 'warn' or higher" |
| `scripts/api-examples-doc.py --check` | – | exit 0 |
| Portal types `scripts/api-types.mjs --check` (generator linked read-only from `wt-602`) | – | stale after the description change; regenerated; then "ok". `schema.generated.ts` changed; `permissions.generated.ts` did not |

**Regeneration was surgical.** Re-recording `samples.json` rewrites every timestamp (I tried it, then reverted). Instead,
`samples.json` is head's file with its one changed `detail` string. `openapi.json` was then written with
`CMAPI_WRITE_CONTRACT=1`, and docs/04 with `api-examples-doc.py --write`. The result is 3 + 26 + 1 changed lines.

## What I ran and did not run

**Ran:**

- the probes (`runs/test_probe_r2_607.py`, which is not in the patch) on head and on the fix;
- the files and checks in the table above;
- the four mutants;
- oasdiff, Spectral and the portal types check;
- source fetches:
  - Kubernetes `create.go`, `validation.go` and `errors.go` (master);
  - AIP-163.

**Not run:**

- the full service suite;
- the portal suites (`npm test`): the patch changes only comment text in `schema.generated.ts` and one sample `detail`
  that the stand-in may serve;
- `lint-test.py` and `gate-test.sh`;
- anything on CRC or kind;
- the `examples/local/app.py` gap (#613, out of scope).

Two of my scratch copies were made with `git init`: `r2-work/cite-head` and `r2-work/cite-fix`. They are new throwaway
repositories, used only so that `doc-citations.py` could list files. No existing repository was touched.

## The patch

`r2-outputs/fix.diff`, applicable with `patch -p1` from the repository root at f6206e9. It touches 15 files:

- `cmapi/src/cmapi/core/docs.py`, `core/problem_docs.py`, `plugins/namespaces/router.py` and `routers/__init__.py`;
- the tests `test_delete_dry_run_602.py`, `test_dry_run_refused_606.py`, and the new `test_dry_run_once_607.py`;
- `contract/openapi.json` and `src/cmapi/contract/samples.json`;
- `cmapi-portal-ui/src/api/schema.generated.ts`;
- `docs/04-api-examples.md`, `docs/14-authorization.md`, `docs/GLOSSARY.md`, `docs/citations.lock.json`, and
  `docs/reviews/2026-11-23-issue-602/README.md`.

Authorship for the PR record: reviewer 2 (Opus 5.5 at high) wrote every line of `fix.diff`. It adapts Codex's
`require_single_dry_run` structure and its three mutant assertions.
