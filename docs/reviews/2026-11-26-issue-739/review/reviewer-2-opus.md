# Reviewer 2 (Opus 5.5, high): PR #742, self-service adoption (closes #739, part of #26)

**Verdict: request changes. All three of reviewer 1's findings are confirmed. My narrowed patch fixes them.**
- The patch is [`r2-outputs/final.diff`](r2-outputs/final.diff). It applies to a fresh copy of `head/` with `patch -p1 -F0`, and the result is identical to the tested tree.
- Every run below used **PostgreSQL 16 on `127.0.0.1:55432`**, database `cmapi_r2_742`. No SQLite was used.
- No repository, GitHub or cluster was changed. I only read issue #736.

## Each finding

### F1, Medium: the adoption lists are unscoped on an imported cluster with no environment. **Confirmed.**

**The code.**
- `RoleGrant.covers(None)` returns `True` (`core/authz.py:75`).
- On head, `_standings` passes `None` when the cluster has no `clusters.yaml` entry. The registry keeps such a cluster as connected and read-only (`core/registry.py`, module docstring: "A connected cluster with no clusters.yaml entry is read-only").

**Measured on head, PostgreSQL** (`ctx.registry.get("CRC").policy = None`):
- `cmapi-bot-rnd` (a requester limited to rnd), `cmapi-requester` and `cmapi-operator` all got 200 on `candidates` and `skipped`. The answer included `abc-rnd` with its `missingKeys`.
- `:adopt` on the same cluster answered 422 `cluster-not-writable`.
- docs/14:180 scopes all three routes to "The cluster's environment".

**Why it belongs to this PR.** Before #739 only `adoption:write` holders (operators) reached these lists. #739 opens them to every holder of `namespaces:write`, including env-limited ones.

**The fix.** `_standings` refuses with 403 `environment-forbidden` when the cluster has no environment.
- It is three lines, through `ClusterState.environment`.
- `environment-forbidden` is already in `LIST_PROBLEMS`, so the contract does not change.

**Behaviour change, stated.** An operator now also gets 403 on such a cluster, where head gave 200. Nothing can be adopted there, because the plan is 422, so the list had no use.

**Test.** `test_an_imported_cluster_with_no_environment_lists_no_candidates` (HTTP, PostgreSQL).
- It replaces reviewer 1's Mock-based test.
- It **fails on head**: 200 with items, for `cmapi-bot-rnd`. It passes with the fix.

**Cut from reviewer 1's patch: the replay grant check in `adopt()` and its test.** This is #736 B-2, "the idempotency replay is answered before the environment grant on every write route. Check the grant first, on all routes together. Predates #733". I verified it is already filed on GitHub. Fixing one route of the set would split that fix.

### F2, Medium: the Adopt form forces every derived or prefix value into the request. **Confirmed.**

**The code.** On head, `addedOf` used `f.fixed ?? typed`, so every read-only value was sent. The only control was a read-only `TextInput`, so it could not be left out.

**Measured on head.** The patched `739-D` direct test was run against head's source (`logs/direct-head-with-r2-tests.log`). An untouched form sent `labels: {name: "abc-legacy-dev", "company.net/mnemonic": "abc"}`.

**Why it contradicts the design:**
- Decision 7 (§1): "A required key missing at adoption is never forced, only reported."
- #732, decision 2: "it stays a finding until someone chooses to add it."
- D20: "Leaving both out is the adoption before #739: the same files, findings and approval."
- An untouched portal adoption on head wrote extra labels and dropped findings. With fewer findings, the approval count can also fall (D10: "one more when the plan has findings").

**The fix, which is reviewer 1's, kept.** Each read-only value gets an "Add <title>" PatternFly `Checkbox`, unselected in the Adopt form.

**The owner's points, checked:**
- *Optional:* an untouched form sends nothing, which is the adoption before #739.
- *No added steps:* the plain adoption is still Justification, Check, Submit. Adding a fixed key takes one click. On head it took zero clicks only because the key was forced.
- "Add missing metadata" still pre-selects its values when opened, because the person asked to add them. Head offered no way to leave one out there. The checkbox now does.
- The typed fields are unchanged.

**Tests.**
- `739-D` (direct test) fails on head and passes with the fix.
- I added a browser step to `739-N`: clearing "Add Mnemonic" drops it from the next PATCH dry run. It passes in Playwright.
- `739-L` axe scans of the add-missing screen, which now has checkboxes, pass at 390 and 1440 px in both themes.

### F3, Medium: a derived namespace suffix is offered. **Confirmed, with a worse effect than reported.**

**The code.** `exact_value` returns the derived value before any suffix check. CRC's `company.net/app-environment` is `value.from: environment` and `namespaceSuffix: true` (`deploy/manifests/environments/crc/20-config.yaml`).

**Measured on head, PostgreSQL.** I used the company keys with CRC's suffix rule, on the dev cluster.
- The candidate `abc-rnd` was offered `company.net/app-environment: dev`, a value its name does not end with.
- Supplying it through `:adopt` returned 200. The `missing-required-key` finding went away, and **no finding said that `abc-rnd` does not end with `-dev`**.
- Combined with F2, head's portal would write that label on every such adoption, untouched.
- D20 says: "A key that the name ends with is never offered."

**Narrowed.**
- I moved the exclusion from `exact_value` into `missing_keys`, which is what D20 and its docstring describe ("nor one that ends the name").
- `exact_value`'s docstring says "None when no request can add it". Reviewer 1's placement made that false, because the #732 validator does still accept a derived suffix key (see Backlog B-A).
- I **cut** reviewer 1's two portal guards: `canFill` in `namespaceChange.ts` and the suffix skip in `missingFields`. The #739 record says "The server computes it, so the portal never guesses". After the server fix no response carries a suffix value, so the guards protected nothing.
- I kept the stand-in change, because it mirrors the server.

**Tests.**
- Core: `test_derived_environment_suffix_is_not_offered` (reviewer 1's) fails on head.
- Service, new: `test_a_key_that_ends_the_name_is_never_offered`. It covers the candidates and the plan's `adoption.missingKeys`, and checks that the key stays a finding. It fails on head and passes with the fix.

### Kept from reviewer 1 beyond the findings

`ADOPT_PERMISSION` now lives in `core/adoption.py` and is used by both the router and `Pipeline.plan_adoption`. The PR changed `plan_adoption`'s literal from `"adoption:write"` to a second literal `"namespaces:write"`. With the shared constant, the environment check and the declared permission can no longer drift apart, which is the PR's claim 1. It costs three lines.

## What reviewer 1 missed

**M1: its patch breaks the docs/14 citation lock, and the tool's own suggestion would point the citation at the wrong check.**
- Reviewer 1 changed `pipeline.py:675` to `ADOPT_PERMISSION`. `scripts/doc-citations.py --check` on reviewer 1's applied copy then reports "`pipeline.py:675` moved to line 558: run --relocate" (`logs/r1-citations.log`).
- Line 558 is **`plan_delete`'s** `namespaces:write` check. `--relocate` would silently point docs/14's adoption row at the delete route.
- `test_doc_citations.py` (service suite, CI) fails on it.
- **Fix (in final.diff):** the lock entry for `pipeline.py|675-675` takes the new text, `self.cfg.roles.require(who, ADOPT_PERMISSION, env)`, which I read against the docs/14 row. `--relocate` is used only for `metadata.py:1404→1405`, the same `namespaces:protect` line moved down by one.
- **Test:** `test_doc_citations.py` passes on the fresh copy with final.diff.

**M2: its patch left the design and the record saying fixed values are always sent.**
- D20's portal bullet and the #739 record's "Read-only fields" row described the forced behaviour.
- Both now name the Add box and when it starts selected. These are one-line edits in final.diff.

**M3: the pipeline import line went to 140 characters.** I wrapped it. This is cosmetic.

## Read and verified, no finding

These are the PostgreSQL walk, `r2-outputs/walk/test_r2_walk_742.py`. It passes on head and on the patched tree (`walk/walk-fixed.log`).

**The walk.**
- `ola` (`cmapi-requester`) adopts with `cmapi.net/team` and `cmapi.net/team-dl`.
- The request gets three approvals, no auto-approval. Then the branch is pushed, the PR opened, CI run, apply started, applied, merge verified, merged, **synced**.
- Every apply-mode write carries the plan's uid and resourceVersion: Namespace `uid-ns-1/100`, the ResourceQuota `uid-rq-1/101`, each LimitRange `.../102`.
- The supplied keys are on the live Namespace and in `main`.

**Drift.** `metadata.drifted_keys` between `main` and the live object returns `[]`.
- The namespace read itself showed `drift` in this harness, for a **plain** adoption too: `name` "live: None".
- The cause is the test world's watch cache, which returns `None` for this namespace. It is not a defect.

**D16.** A resourceVersion change after the plan fails the request with `adoption-plan-stale`. Nothing is applied and no PR is opened.

**Plan hash.** I changed a supplied value in the stored `plan.files` after approval. Delivery refuses it with `plan hash mismatch: stored 0a959adb782a, rendered e8c87e89c6ce`. Nothing is applied and nothing is pushed.

**Approval with a supplied team.** `facts.team` makes `submit` decide again. No auto-approval policy names the plugin `adoption`, so the approval stays manual: three approvals in the walk, as without keys.

## Backlog (each predates this PR)

**B-A, Low: a derived suffix key is accepted with its value even when the name does not end with it.** This is the #732 rule, `MetadataKeys._addition`.
- It is reachable by PATCH and, from this PR, by `:adopt`.
- Measured: `abc-rnd` plus `company.net/app-environment: dev` gives 200 and no finding.
- A create would refuse that name (#479). The #732 ruling covers "exactly the derived value", so this extends the design and needs a ruling.
- Proposed fix: [`r2-outputs/backlog-derived-suffix.diff`](r2-outputs/backlog-derived-suffix.diff). In `_addition`, a derived suffix key is refused when the name does not end with `-<value>`. `remedy()` needs the same condition, so a finding never offers a refused repair (#732's F3).
- Test: [`r2-outputs/backlog-test_derived_suffix_addition.py`](r2-outputs/backlog-test_derived_suffix_addition.py). It has 3 cases: 2 fail before the fix and all 3 pass after.

**B-B, Low: `RoleGrant.covers(None)` admits every grant.** So `GET /clusters/{id}/namespaces` and `GET .../namespaces/{ns}` (`objects:read`) skip the environment limit on an imported cluster that has no `clusters.yaml` entry.
- Measured: `cmapi-bot-rnd` gets 200 on `list_namespaces` for such a cluster.
- docs/14:179 says "The cluster's environment".
- Fix all callers together by refusing `env is None` for env-limited grants, with a test per route.

**#736 B-2** (replay before the grant) is already filed. I did not re-report it.

**Reviewer 1's two Low items** (the summary focus id with the `nsm-` prefix, and the API text that names the prefix value as the only accepted one) stand as Backlog.

## Runs

The two head trees (`r2-work/headrun`, `r2-work/fixed`) are copies of `head/`; `fixed` carries final.diff. All service runs are on PostgreSQL.

| Run | Head | Patched |
|---|---|---|
| `test_self_service_adoption_739.py` with the new tests | 14 passed, **2 failed** (F1, F3) | 16 passed |
| `tests/core/test_missing_keys_739.py` | 19 passed, **1 failed** (F3) | 20 passed |
| Portal direct tests with the patched tests | 45 of 46: **739-D fails** (F2) | 46 of 46 |
| Full `tests/core` (venv-ref) | not run | **948 passed, 115 skipped** |
| Service: 739, 26, 733, 732, samples, api_docs, api_standard, portal_map, 606, review_c_authz, problem_type_docs, namespace_change_doc_rules | not run | **296 passed** |
| `test_doc_citations.py` (needs git; run in a fresh copy with git) | reviewer 1's copy: 2 problems | passes |
| Portal `npm test` (contract and model checks, tsc, both builds, direct, stand-in, bundle, Playwright portal, behaviour, parity) | not run | **exit 0, 213 ok, 0 FAIL**, including 739-A, B, H, N (extended), F and L, with axe |
| PostgreSQL walk (3 tests) | 3 passed | 3 passed |
| Fresh `head/` copy plus `final.diff`: 739 core, 739 service, doc_citations, review_c_authz, direct | not applicable | 20 passed; 41 passed; 46 of 46 |

**Contract:** unchanged. No docstring, model or problem list changed, so nothing needed regenerating. The portal's `api-types --check` and `contract.test.mjs` pass inside `npm test`.

**Logs:** [`r2-outputs/logs/`](r2-outputs/logs/) and [`r2-outputs/walk/`](r2-outputs/walk/). The work trees are in `r2-work/`.

## Who wrote what

- **Reviewer 1 (Codex gpt-6.2-astra xhigh):** the original fixes for F1 to F3, the Checkbox UI, the stand-in mirror, `739-D` and the core suffix test.
- **Reviewer 2 (Opus 5.5 high):**
  - moved the suffix exclusion into `missing_keys`;
  - cut the replay check and the portal suffix guards;
  - wrote the two PostgreSQL HTTP tests that replace the Mock test, and the `739-N` browser step;
  - fixed the citation lock and the design and record lines;
  - ran the walk, the portal suite and the Backlog fix.
