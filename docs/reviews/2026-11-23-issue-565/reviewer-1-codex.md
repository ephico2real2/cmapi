# PR #576, reviewer 1 (Codex gpt-6.1-sol, high), 2026-11-23

Saved by the coordinator from Codex's returned report. Paths are relative to /Users/olasumbo/gitRepos/workbench/cmapi/review-576/.

Verdict: the header declaration, the merge with `response_model`, the quoting, the TS type (`ETag?: string`), oasdiff (one `response-header-added`) and the citation move hold. There are two description defects.

## Finding 1 (P2): "another value is 412" omits Idempotency-Key replays
- Location: head/cmapi/src/cmapi/core/models.py:394.
- `pipeline.py:215-220` and `:431-435` compare the tag and give 412. But `router.py:321-324` (PATCH) and `:342-345` (DELETE) return a stored answer after only checking that If-Match is present. `router.py:303-308` already documents this.
- Scenario: submit a change and let it merge, then retry with the same body, Idempotency-Key and the original tag. The answer is the stored one, not 412. A weak tag or `*` also skips the comparison on a replay.

## Finding 2 (P2): "changes whenever the namespace's folder in Git changes" is too broad
- Locations: models.py:395 and router.py:207.
- The folder readers select only `.yaml` files: `core/git/github.py:74-77`, `core/git/gitea.py:70-73` and `core/git/workspace.py:299-308`. `pipeline.py:98-100` hashes that mapping.
- Scenario: a README.md added to the folder leaves the tag unchanged.

## Proposed fix
NamespaceView.etag description:
"The namespace's entity tag: the `ETag` header without its quotes. Send it back unchanged, in double quotes, as `If-Match` on a change or a delete. For a new request, a value that does not match is 412 `precondition-failed`; an Idempotency-Key replay requires the header but returns the stored answer without comparing its value again. It tracks the files read from the namespace's folder in Git; changes to other files need not change it. Compare it; never parse it. Null on the list, which reads no Git"

NAMESPACE_ETAG_HEADER description:
"The namespace's entity tag, quoted: the `etag` of the body. Send it unchanged as `If-Match` on a change or a delete. It tracks the files read from the namespace's folder in Git; changes to other files need not change it."

Then regenerate openapi.json and schema.generated.ts.

## Proposed tests (NOT EXECUTED by Codex: no pytest, FastAPI or PostgreSQL in its runtime)
- test_etag_description_explains_stale_idempotency_replays: create, GET, PATCH tier=medium and let it run, check that the tag changed, retry the same PATCH with the old If-Match, and expect the same requestId. Then assert the description contains "For a new request", "Idempotency-Key replay" and "without comparing its value again".
- test_etag_descriptions_allow_changes_to_unread_files: add README.md to the FakeGit main branch folder (`git.branches["main"][...]`, `git._sha("main")`). The GET etag body and header stay unchanged. Then assert that both descriptions contain "changes to other files need not change it".

## Test-quality notes
- The first three tests in test_namespace_etag_doc_565.py match strings. With both descriptions replaced by "If-Match always succeeds, even with a stale value", all three still pass.
- The fourth test is behavioural: create, GET, a stale PATCH 412, a fresh PATCH plan. It uses the doc example as a deliberately stale tag, which fails if the fixture's current tag ever equals the example.
- Codex ran the first three on the exported JSON. On base: fail, fail, pass. On head: pass, pass, pass.

## Confirmed
- The examples have the real form (16 hex).
- The list sets etag None (router.py:131) and reads no Git.
- PlanView.etag equals the If-Match tag on a change (pipeline.py:215, 218, 357; Plan.view :73).
- A create gives "0" for an empty folder.
- Submit plans again with the supplied header (router.py:326).
- No public namespace-tag description still says commit or SHA.
- The docs/14:178 citation moved from router.py:223 to :232.
- No style issue: new lines reach 124-125 characters, against existing maxima of 513 and 218.
