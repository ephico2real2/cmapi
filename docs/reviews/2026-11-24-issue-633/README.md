# #633, #634 and #635: the follow-ups of #605's review

PR #637. The PR body has the three defects, their fixes and the coordinator's first suite on `c18dd5f`, which passed
2585 tests.

## Review

- **Reviewer 1:** Codex `gpt-6.2-astra` at xhigh, on head `c18dd5f` (`review/reviewer-1-codex-astra.md`). It found three
  defects.
- **Reviewer 2:** a separate Opus 5.5 agent at high (`review/reviewer-2-opus.md`). It confirmed all three and found a
  fourth.

| # | Finding | Ruling (coordinator, Opus 5.5) |
|---|---|---|
| 1 | `GET /api/v1/quotas:export?sort=newest` answered 200. The shared `Lister` knows `newest`, which is the request list's order, and a quota row has no time to sort by | Accepted. `_query` refuses a sort outside `SORTS = ("name", "used", "severity")` with 400 `invalid-sort`, as docs/01, Lists, says. `GET /api/v1/quotas?sort=newest` becomes 400 too. The portal offers only those three sorts (`QuotasTab.tsx:22`), so no client breaks |
| 2 | HEAD filtered and sorted the whole matching set, then dropped it. This PR introduced the defect | Accepted. HEAD validates as GET does and does not call `export_csv`. RFC 9110 §9.3.2: "These minor inconsistencies are considered preferable to generating and discarding the content for a HEAD request". The HEAD test now spies on `Lister.filtered`: 0 calls on HEAD and 1 on GET |
| 3 | A mutant that logs the template `{request_id:request_id}` in `unhandled` survived | Accepted. The test reads the real JSON log line through `capsys`, and the mutant now fails it |
| 4 (reviewer 2) | The export answered 400 `invalid-sort`, but its API document listed no 400. `test_api_samples.py` requires each refusal a client meets to be documented | Accepted. The route declares `problems=["invalid-sort", "validation-failed"]`, and one recorded sample of the 400 was added. `contract/openapi.json`, `docs/04` and `schema.generated.ts` were regenerated. The oasdiff gate reports this as not breaking: one new 400 response, info level |

HEAD and GET refuse the same requests with the same status, measured on the database for both methods:

| Request | Status |
|---|---|
| A bad state | 422 |
| A bad sort | 400 |
| `newest` | 400 |
| No token | 401 |
| No permission | 403 |

None of these refused requests writes an audit event.

Reviewer 2 ran 7 mutants, and all 7 were killed. The output of each is in `workbench/cmapi/review-637/r2-outputs/mutant-m*.txt`.

Reviewer 2 also spot-checked two of reviewer 1's claims:
- #634: the served `/openapi.json` is byte-identical on base and head, 428,374 bytes.
- #635: `GET /api/v1/requests/req-x:approve` answers 405 with `Allow: POST`.

## Coordinator's run

Reviewer 2's patch was applied with `patch -p1 -F0`, and `main` was merged in, including #630.

- **The full service suite** in database `cmapi_wt616`, from 2026-11-24T10:41:02Z to 11:16:33Z. It ran after the gate
  (no other suite, 1-minute load 8.70): **2602 passed in 2122.65 s**.
- `api-examples-doc.py --check` and `changelog.py --check` exit 0, and `doc-citations.py --check` finds 0 problems.

## Not tested

- CRC. It comes with deploy run 38.
- The portal's own `npm test`. The only portal change is the generated type file, and its generator check passes.
