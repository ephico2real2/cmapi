# PR #674 (closes #671): reviewer 1 report

Reviewer: Opus 5.5 at `high`, a separate agent that did not write the change. It stands in for Codex, which is at its usage
limit, under the owner's rule of 2026-11-25 (reviewer 1 only).

Export: `review-674/head` (the PR head) and `review-674/base` (main `7eb4b62`). Every test ran from the export against
`cmapi_r1_674` on `127.0.0.1:55432`. No cluster was used. Outputs are in `review-674/r1-outputs/`.

## Verdict

The change does what #671 asks. All four raise sites use the helper, every mutant is killed, and no client reads the old
`null`. I found one Medium defect, which the PR introduces: two read routes and `_decide` now read an `instance.directory`
that the start never checks, so a bad entry turns their 422 into a 500. I also found one Low defect in the changed lines,
the RFC citation. Full fixes for both are in `r1-outputs/fix.diff`, which applies with `patch -p1 -F0`. Two more Low
findings are adjacent, so they go to Backlog.

## Research: RFC 9457 and docs/02

- **RFC 9457** was fetched from https://www.rfc-editor.org/rfc/rfc9457.txt on 2026-11-25 (`r1-outputs/rfc9457.txt`).
  - The quoted sentence is in **section 3.1**, "Members of a Problem Details Object", lines 240-245: "If a member's value
    type does not match the specified type, the member MUST be ignored -- i.e., processing will continue as if the member
    had not been present."
  - That sentence governs "the following members", which are the standard ones (`type`, `status`, `title`, `detail`,
    `instance`).
  - Extension members are covered by **section 3.2**, lines 365-379. It says only that "Problem type definitions MAY extend
    the problem details object with additional members" and that clients "MUST ignore any such extensions that they don't
    recognize". It says nothing about null or a type mismatch.
  - So the implementer's quote is accurate, but the citation is not:
    - the helper's docstring cites "section 3";
    - the new test's docstring cites "section 3.2", which does not contain the sentence;
    - and the sentence is applied to extension members by analogy, without saying so.
  - The decision to leave a member out still stands on 3.2: the problem type defines its own extensions, and this one
    defines each as a URL string. This is finding R1-2.
- **docs/02**, `head/docs/02-technical-design-v2.md:161`, reads: "environment-not-served | 422 | The environment is not
  in this instance's allowedEnvironments; the body carries instanceUrl and portalUrl of the instance that serves it".

## The five points

### 1. Every raise site uses the helper: confirmed

- I searched with `grep -rn "environment-not-served\|environment_not_served"` in `head/`, plus `not served`, `TierError`,
  `_need_env` and `.decide(`.
  - The helper is used at four sites:
    - `pipeline.py:187` (`check_env_served`);
    - `pipeline.py:470` (`_decide`);
    - `plugins/capacity/router.py:197`;
    - `plugins/tiers/__init__.py:31`.
  - Two other sites still raise the code, and neither can reach a caller in a configuration that loaded:
    - **`approvals.py:164`** (`ApprovalRules.decide`). `load_instance` refuses an approval-rules file whose environments
      differ from `allowedEnvironments` in either direction (`config.py:129-131` for missing ones, `approvals.py:96-99` for
      extra ones), so `_decide`'s new check is the same test and runs first. `Pipeline._decide` is the only caller of
      `ApprovalRules.decide` (grep `decide(`).
    - **`tiers.py:537`** (`TierCatalog._need_env`). The catalog's environments equal `allowedEnvironments`, because
      `tiers.py:352-357` refuses both extra and missing ones at the start. GET /tiers and the pipeline both refuse first.
- `tokensave_search` (`literal: true`) answers from the served project's index, which is the local main checkout. With
  `graph_root` set to that project, the tool refused: "graph_root selects the same project already served". Without it, it
  returned 22 hits at older line numbers (`pipeline.py:143`), so the index predates this PR (`stale_files: 30`). The grep
  over `head/` is the authoritative result. The tokensave hits confirm only that main had the same set of raise sites, with
  `check_env_served` and the capacity route inline.
- The metric `cmapi_environment_not_served_total` stays in `check_env_served` only. That is correct and should not move
  into the helper. On the write path the label is a cluster's configured environment, which is bounded. On GET /capacity
  and GET /tiers it would be the caller's query string, which would give unbounded label values.

### 2. GET /tiers moves from `policy-violation` to `environment-not-served`: right by docs/02, and not breaking for any client in the repository

- **docs/02:161** names `environment-not-served` for any environment outside `allowedEnvironments`. The old answer was a
  `policy-violation`, which `main.py:279-281` built from a `TierError`. It contradicted that row.
- **oasdiff v1.37.0** (the CI pin), run base against head:
  - `oasdiff breaking`: "No breaking changes to report, but the specs are different." (`r1-outputs/oasdiff-breaking.txt`);
  - `oasdiff changelog`: "No changes to report" (`r1-outputs/oasdiff-changelog.txt`).
  - Only examples and descriptions changed. `ProblemDetail` has `additionalProperties: true` and does not declare
    `instanceUrl` or `portalUrl`.
- **The portal**:
  - `useTiers` (`hooks.ts:151-163`) and `useCatalog` (`hooks.ts:508-519`) pass any error through `problemOf`
    (`problem.ts:61-63`), which copies `code`, `detail` and `errors`.
  - No portal code branches on `policy-violation` or on the tiers refusal. The only `code ===` checks are `invalid-cursor`
    and `change-pending`.
  - `useTiers` asks for the environment of one of this instance's own clusters, so it cannot meet this refusal in normal
    use.
- **A change on the wire.** The old body carried `errors: [{code: "environment-not-served", environment, served}]`, and the
  new body has no `errors`. A third-party client that keyed on `code == "policy-violation"` for /tiers, or that read
  `errors[0].served`, would see a different answer.
  - No such client exists in the repository.
  - docs/02 never documented the old shape.
  - The PR states the change, and the contract example and description are updated.
  - This is a correction to the documented contract, not a regression.
- **Tests on the regenerated portal types.** `cmapi-portal-ui/src/api/schema.generated.ts` changes in two comment lines
  only (12331, 12563), as `diff base head` shows. `pr.diff` leaves the portal and `examples/` out. `examples/src/cmapi` is a
  symlink to `cmapi/src/cmapi`, so those files are identical.

### 3. Leaving a URL out instead of sending null: no client or test reads null. Confirmed

- I searched `instanceUrl` and `portalUrl` across `base/` and `head/`: `*.py`, `*.ts`, `*.tsx`, `*.js`, `*.md`, `*.sh`,
  `*.yaml` and `*.json`, without node_modules or docs/reviews.
  - No test asserts `None` or `null` for either member.
  - `test_environment_not_served_417.py:103` asserts both members present, and it passes on head (11 passed, together with
    the 671 file).
  - The portal reads neither member. `problemOf` ignores both.
  - The mockup (`mockups/portal/Main.dc.html:1612`) shows both as strings.

### 4. `_decide` refusing before the approval rules: it blocks nothing new, and refusing is right

- **Nothing new is blocked.**
  - On base, `ApprovalRules.decide` already raised 422 `environment-not-served` ("No approval rules for uat") for any
    environment outside the rules, and the rules equal the served set (point 1).
  - Proof: on base, the new test `test_the_approval_decision_names_the_instance_that_serves_the_environment` fails only on
    the body, `assert {} == {'instanceUrl…'}`, with code and status already `environment-not-served` and 422
    (`r1-outputs/base-671.txt`).
  - Only the body changes: the detail text and the URLs.
- **Every caller of `_decide`:**
  - `pipeline.py:404` and `:510`, the write plans. `check_env_served` already refused at `:249` and `:481`.
  - `pipeline.py:522`, the submit.
  - `jobs/open_pr.py:100`, the revert job.
  - Approval of a request already in flight (`:approve`) does not call `_decide`; grep `decide(` finds no other caller. So
    an approval in flight is unaffected.
- **The revert job.** On base and on head it raises, the worker's session rolls back the `E.REVERT` move
  (`worker.py:117-131`), and the job retries up to `MAX_ATTEMPTS` before an `error` event. That is unchanged by this PR.
- **Why refusing is right.**
  - This instance cannot write to that environment: a `clusters.yaml` entry for an environment that is not served stops
    the start (`registry.py:202-203`, docs/02:701).
  - The new body now names where to go.
  - Refusing before `auto_paused()` also saves a database session on a refusal.

### 5. The tests can fail: confirmed

All logs are in `r1-outputs/`.

**The new test file on base and head:**

| Run | Result |
|---|---|
| `test_environment_not_served_671.py` on head, with `_417` | 11 passed |
| Same new file on base (`base-671.txt`) | 5 failed, 1 passed. The pass is `capacity_leaves_both_out…`, which base satisfies trivially because the capacity route sent no URLs; M5 below shows that test kills a null |

**Mutants of head** (`mutants/run_mutants.sh`, one full copy of the repository for each mutant):

| Mutant | Result | Killed by |
|---|---|---|
| M0, the control with no change (671 file + api_standard tiers test) | 9 passed | n/a |
| M1, the tiers route without its pre-check (falls back to TierError) | 1 failed | `test_tiers_names…` |
| M2, the capacity route inline, without URLs (base's line) | 2 failed | `test_capacity_names…`, `…carries_the_portal_url…` |
| M3, `_decide` without the pre-check | 1 failed | `test_the_approval_decision…` |
| M4, `check_env_served` with the old inline code, which sends nulls | 1 failed | `test_the_request_path_leaves_out…` |
| M5, the helper sends null (`if serving.get(key)` removed) | 3 failed | capacity ×2 and request path |
| M5b, the helper sends null through `serving.get(key)` | 3 failed | same |
| M6, the tiers route declares `problems=["policy-violation"]` | 3 failed | the api_standard tiers test, all 3 parameters |

## Findings

### R1-1, Medium: a directory entry the start does not check turns the 422 of GET /capacity, GET /tiers and `_decide` into a 500

**What is wrong.** `environment_not_served` (`config.py:72-74`) reads `instance.directory` as a mapping of mappings, each
with an `environments` list. Nothing checks that shape: `load_instance` never looks at `directory`, and `grep -rn
directory src/cmapi/core/config.py` finds only the helper. Each of these shapes starts, and then raises in the helper:

- `environments: null` gives `TypeError: argument of type 'NoneType' is not iterable`;
- an entry that is a string gives `AttributeError`;
- `directory` as a list gives `AttributeError` on `.values()`.

A string `environments: "qa, uat"` does worse: it raises nothing and matches by substring, so `"a" in "qa, uat"` is true.

**Why this PR.** Before it, only `check_env_served` (the write path) read `directory`.

- GET /capacity answered 422 without reading it.
- GET /tiers answered 422 through TierError.
- `_decide` answered 422 from `ApprovalRules`.

The PR sends all three through the helper. A configuration that starts now answers 500 `internal-error` on reads that
answered 422 on base.

**Proof** (`r1-outputs/demo_500_on_head_test.py`, run on both trees). The test sets the staging entry's `environments` to
`None` and calls GET `/api/v1/capacity?env=prod`:

- head: `assert 500 == 422`, with body `{"code":"internal-error",...}` (`demo-500-head.txt`);
- base: 1 passed (`demo-500-base.txt`).

**Fix** (in `fix.diff`). `_directory_problems(directory)` in `core/config.py`, called from `load_instance`, as
`_git_problems` is. It follows the module's rule that a configuration problem stops the start, and on reload it keeps the
running configuration (`config.py:17-18`). It checks four things:

- `directory` is absent or a mapping;
- each entry is a mapping;
- `environments` is a list of non-empty strings;
- `url` is an absolute http(s) URL, and `portalUrl` is absent, `""`, or an absolute http(s) URL.

The URL test is the one `errors.py:20-23` already uses for `problems.typeBase`. The fix also updates the module's
docstring list and docs/18's `instance.directory` row.

**Test.** The new file is `cmapi/tests/service/test_directory_shape_674.py`, and its source is in `fix.diff`.

- Seven wrong shapes must raise `ConfigError`. Five documented shapes must start:
  - no directory;
  - an empty directory;
  - the reference shape;
  - `portalUrl: ""`;
  - a full `portalUrl`.
- Before the fix, on head: 7 failed, 5 passed (`fix-test-on-head.txt`). The 7 failures are "DID NOT RAISE".
- After the fix, in `r1-outputs/fixtree`: the new file plus `_671`, `_417`, `test_cluster_trust_434`,
  `test_plugins_switch`, `test_plain_manifests` (which loads the CRC and kind ConfigMaps), `test_review_g_chart` and
  `test_api_standard` gave **390 passed**. `tests/core` `test_config_repo_ci`, `test_approvals` and `test_tiers` gave
  **106 passed, 18 skipped** (`fix-tree-tests.txt`).
- Every reference `instance.yaml`, the helm default and the CRC and kind ConfigMaps keep the documented shape. Those load
  tests pass on the fix tree.

### R1-2, Low, in the changed lines: the RFC 9457 citation is wrong

**What is wrong.**

- `config.py:68-70` cites "RFC 9457, section 3" for the sentence "as if the member had not been present".
- `test_environment_not_served_671.py:5` cites "section 3.2".

The sentence is in section 3.1 and governs the standard members, while section 3.2 governs extension members (see
Research). The conclusion is unchanged; only the grounding is fixed.

**Fix** (in `fix.diff`). The docstring now says that section 3.2 leaves an extension's type to its problem type, which
makes each member a URL string, and that section 3.1's rule for the standard members holds here by analogy. The test's
docstring now cites sections 3.1 and 3.2 through the helper.

**Test.** None: this changes only comments.

### R1-3, Low, Backlog: the reference configurations never produce `portalUrl`

No `directory` entry in the shipped files has `portalUrl`:

- `examples/instances/{nonprod,staging,prod}/instance.yaml:32-34`;
- `examples/config`;
- `examples/local`;
- `tools/reference_instance`;
- the helm `values.yaml:31-33`;
- `deploy/manifests/environments/crc/20-config.yaml:35`.

So a shipped instance never sends the `portalUrl` that docs/02:161 says the body carries. The contract example shows one
(`docs.py:178`), which is accurate for a directory that gives it. The fix belongs in configuration files outside this PR's
lines: add `portalUrl` to each entry from the target instance's own `portalUrl` (for example
`examples/instances/staging/instance.yaml:10`).

### R1-4, Low, Backlog: the mockup's body has more members than the code sends

`mockups/portal/Main.dc.html:1612` shows these members:

- `environment`;
- `instance`;
- `servedBy`;
- `instanceUrl`, as the API base plus `/api/v1`;
- `portalUrl`.

The code sends only `instanceUrl` (the base URL, without `/api/v1`) and `portalUrl`. That gap predates this PR on the write
path.

GET /tiers also stops sending `environment` and the `served` list, which the old `TierError` body carried in `errors`.
docs/02 mandates only the two URLs, so this is not a defect of #674. Whether the API should also carry `environment` and
`servedBy` is a design question for the coordinator. Per "Don't reopen a decided design", I only record it.

## Files

| File | What it is |
|---|---|
| `r1-outputs/fix.diff` | R1-1 and R1-2, from `cmapi/` and `docs/`; `patch -p1 -F0` applies it cleanly to `head/` |
| `r1-outputs/test_directory_shape_674.py` | R1-1's test, also inside `fix.diff` |
| `r1-outputs/demo_500_on_head_test.py`, `demo-500-{head,base}.txt` | R1-1 evidence |
| `r1-outputs/mutants/` | `run_mutants.sh`, `summary.txt`, one log per mutant |
| `r1-outputs/base-671.txt`, `head-671-417.txt` | Point 5 |
| `r1-outputs/oasdiff-{breaking,changelog}.txt` | Point 2 |
| `r1-outputs/rfc9457.txt` | The fetched RFC |
| `r1-outputs/fixtree/` | `head/` with the fix applied, where the post-fix tests ran |
