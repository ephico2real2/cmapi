# PR #598, reviewer 2 (Opus 5.5 high): rulings on reviewer 1 and the database runs

Head 169d107 (`review-598/head/`). Fixed copy: `review-598/r2/`. Scratch: `review-598/r2-work/`. Outputs: `review-598/r2-outputs/`.
Patch: `review-598/r2-outputs/fix.diff`, 244 lines, against head. It applies with `patch -p1` from the repo root: I applied
it to a fresh copy of `head/`, and all 6 files came out byte-identical to `r2/`. All results are from the local
PostgreSQL 16.15 on 127.0.0.1:55432, in my own databases `r2_598_head` and `r2_598_fix`. Nothing ran on kind or CRC.

## Rulings

### 1. P1, #596 incomplete: **accepted**, with Codex's fix and a stronger test

The premise is verified against the installed Starlette 0.41.3 (`ob1-run/venv/.../starlette`):

- `middleware/cors.py`. `simple_response` wraps the `send` it is given in `functools.partial(self.send, send=send, ...)`.
  For an allowed origin, `self.send` calls `self.allow_explicit_origin(headers, origin)`, which runs
  `headers.add_vary_header("Origin")`. Only after that does it call cmapi's `vary_send`. So Starlette rewrites Vary
  before cmapi sees it.
- `datastructures.py:647-651`. `add_vary_header` reads `existing = self.get("vary")`, the first line only. Then
  `self["vary"] = ...`. The `__setitem__` at 568-588 deletes every later line with the same key.
- Preflight never reaches `allow_explicit_origin`. `preflight_response` builds its own headers with `Vary: Origin`.
- Starlette master, fetched 2026-11-23 from
  <https://raw.githubusercontent.com/encode/starlette/master/starlette/middleware/cors.py>, now writes
  `headers["Vary"] = ", ".join([*headers.getlist("Vary"), "Origin"])` in `allow_explicit_origin`. That confirms the
  cmapi comment "as Starlette's main branch does".

Measured with a raw-ASGI probe (`r2-work/corsprobe.py`, outputs `r2-work/corsprobe-{head,r2}.txt`). The probe used the
real METHODS, REQUEST_HEADERS, EXPOSED_HEADERS and MAX_AGE, with the listed origin `https://portal.example`:

| Upstream Vary lines | head, listed origin | fix, listed origin (the same for no Origin and for a denied one) |
|---|---|---|
| `Accept` / `Cookie` | `Accept, Origin` (Cookie lost) | `Accept, Cookie, Origin` |
| `oRiGiN` / `Cookie` | `oRiGiN, Origin` | `oRiGiN` / `Cookie` |
| `Accept` / `OrIgIn` | `Accept, Origin` | `Accept` / `OrIgIn` |
| `Accept` / `*` | `Accept, Origin` (`*` lost) | `Accept` / `*` |
| `*` | `*, Origin` | `*` |
| `Origin` | **`Origin, Origin`** (a duplicate, which Codex did not list) | `Origin` |
| ` \toRiGiN\t ` | ` \toRiGiN\t , Origin` | ` \toRiGiN\t ` |
| `<A0>Origin<A0>` | `<A0>Origin<A0>, Origin` | `<A0>Origin<A0>, Origin` |
| none | `Origin` | `Origin` |

Origin appears exactly once wherever it is needed, and a `*` Vary is kept. The preflight lines are byte-identical
between head and the fix. An allowed origin gets 200, `Vary: Origin` and the allow headers. A denied origin gets 400
and `Vary: Origin`. Without an Origin header, and for a denied origin, the output was already right on head and is
unchanged.

**The fix** (`cmapi/src/cmapi/core/cors.py`, appended to `OriginVaryCORSMiddleware`, with the class docstring and the
`vary_send` comment updated to say so):

```python
    @staticmethod
    def allow_explicit_origin(headers: MutableHeaders, origin: str) -> None:
        """Only the allowed origin. Starlette 0.41.3 also calls add_vary_header("Origin") here, which keeps the first Vary
        line and drops the others, before vary_send sees them (#596); vary_send adds Origin to every answer instead."""
        headers["Access-Control-Allow-Origin"] = origin
```

**The test.** Codex's test covered the listed origin only. Mine is a 7 × 3 parametrization: each upstream case is sent
with no Origin, with a denied origin and with the listed one. Each must give the same Vary lines, and only the listed
origin may get `Access-Control-Allow-Origin`. `_vary_after_cors` is split into `_cors_answer` and `_vary_after_cors`,
so the existing tests are unchanged.

```python
@pytest.mark.parametrize("origin", [None, "https://other.example", ALLOWED])
@pytest.mark.parametrize("upstream, expected", [
    (["Accept", "Cookie"], [b"Accept, Cookie, Origin"]),
    (["oRiGiN", "Cookie"], [b"oRiGiN", b"Cookie"]),
    (["Accept", "OrIgIn"], [b"Accept", b"OrIgIn"]),
    (["Origin"], [b"Origin"]),
    (["Accept", "*"], [b"Accept", b"*"]),
    (["*"], [b"*"]),
    ([], [b"Origin"]),
])
def test_each_origin_gets_every_vary_line_and_one_origin(upstream, expected, origin):
    r = _cors_answer(upstream, origin)
    assert [v for k, v in r.headers.raw if k.lower() == b"vary"] == expected
    assert r.headers.get("access-control-allow-origin") == (ALLOWED if origin == ALLOWED else None)
```

- On head code: 6 failures, all `[...-https://portal.example]`, for upstream0 to upstream5. Examples are
  `[b'Accept, Origin'] == [b'Accept, Cookie, Origin']`, `[b'Origin, Origin'] == [b'Origin']` and
  `[b'*, Origin'] == [b'*']`. Output: `r2-outputs/before-new-tests-on-head-code.txt`.
- With the fix: all 21 pass.
- Mutant m6 puts `add_vary_header("Origin")` back into the override. The same 6 fail
  (`r2-outputs/mutant-m6_starlette_vary_back.txt`).
- `test_cors.py`, whose tests need the database, passes after the fix: it is inside the 463 below.

### 2. The test gaps: **accepted**, with each mutant shown killed

These changes are in `cmapi/tests/service/test_read_preconditions_590_593.py`:

- **Codex's 7 CASES rows, plus 2 rows from ruling 4.** They are appended after the original 10 rows, so the 47 node IDs
  keep running the same cases. The row `(["{etag}", STALE], [], 200)` is Codex's row with a comment.
- **The 304 Cache-Control assertion:**
  `assert (r.content, r.headers["etag"], r.headers["cache-control"]) == (b"", etag, first.headers["cache-control"])`.
- **Exactly these two reads document If-Match.** This is added to `test_the_two_reads_document_if_match_and_its_412`:

```python
    reads = {path for path, methods in spec["paths"].items()
             if any(p["in"] == "header" and p["name"].lower() == "if-match"
                    for p in methods.get("get", {}).get("parameters", []))}
    assert reads == {"/api/v1/metadata-keys", "/api/v1/capacity"}
```

Each mutant is a full copy of `cmapi/`, `examples/` and `docs/`, made from the fixed tree by `r2-work/mkmut.py`. Each one
ran only the test file above. The mutant source edits are exact strings in `mkmut.py`.

| Mutant | Failed / 108 | Killed by |
|---|---:|---|
| m1: only the last If-Match line (`value = if_match[-1]`) | 4 | case 10, `["{etag}", STALE]`, on 4 paths |
| m2: only the first If-None-Match line (`headers.get("if-none-match")`) | 4 | case 12, `["*"]` + `['"old"', "W/{etag}"]` |
| m3: a weak If-None-Match is rejected | 8 | cases 12 and 13 |
| m4: no Cache-Control on 304 (in all 3 handlers) | 20 | every 304 case: 3, 4, 12, 13, 18 |
| m5: `/api/v1/me` documents If-Match (`**CONDITIONAL_READ`) | 1 | `test_the_two_reads_document_if_match_and_its_412` |
| m6: `add_vary_header` back in `allow_explicit_origin` | 6 | `test_each_origin_..._one_origin[*-portal.example]` |
| m7: the `precondition-failed` action is write-only again | 1 | `test_the_precondition_failed_page_says_what_a_read_and_a_change_do` |

As Codex said, all the new CASES rows already pass on head code: only the 8 tests named in ruling 1 and ruling 3
failed there.

### 3. Docs: **accepted, reworded**. Codex's `problem_docs.py` snippet is **rejected** as written

- **docs/18:503.** I verified this against `routers/me.py:45-55`. `metadata_keys_document` is
  `functools.lru_cache(maxsize=4)` and builds the answer on the first request. `maxExtensionDays` is not in the body.
  The doc now says three things. The ETag changes "when a rule in the answer does", naming `maxExtensionDays` as the
  exception. "The first request builds the answer and caches it for the loaded files". And "`If-Match: *` passes, and
  any other value must list the `ETag`, by the strong comparison, or the answer is `412`. Then a matching
  `If-None-Match` answers `304`."
- **docs/08:89.** The contract has **40** operations: 25 GET, 13 POST, 1 PATCH, 1 DELETE, counted from
  `cmapi/contract/openapi.json`. All 40 have `x-codeSamples`. A script also confirmed two facts. No GET sample sends
  If-Match or If-None-Match. Every non-GET sample sends `Idempotency-Key` and `If-Match` exactly when the operation
  declares them. The row now says that.
- **`core/problem_docs.py` `precondition-failed`.** The new action text covers a read and a change:
  "For a read, send it again without `If-Match`. For a change, read the object again, and send the change with the new
  `ETag` in `If-Match`."
  - **Codex missed this.** His snippet replaced the entry with 5 lines and pushed lines 53 and 54 down by 4. Those lines
    are cited by `docs/14-authorization.md:312` and `:314`, and the citation lock holds their text. Applied to a copy of
    head, `scripts/doc-citations.py --check` reported "`problem_docs.py:54` moved to line 58" and "`:53` moved to line
    57", 2 problems. My entry stays on one line, at 167 characters, the file's existing maximum. The check then reports
    0 problems.
  - Nothing generated is fed from `ACTIONS`. The `/problems` pages are rendered per request. A grep found the old
    sentence only in a comment in `cmapi-portal-ui/tests/api/portal.test.mjs:2581`, which I updated so that it quotes
    the new text.
- **The tests**, both new and both run without the database:
  - `test_the_docs_say_what_a_conditional_read_answers` reads docs/18, docs/08 and the contract. The number in docs/08
    is computed from `openapi.json`, so a new operation fails it, not just a wording change.
  - `test_the_precondition_failed_page_says_what_a_read_and_a_change_do` renders the page with `problem_html`.
  - Both fail on head: ``'`If-Match: *` passes' in ...`` and `'For a read, ...' in 'Read the object again, ...'`.
    Both pass with the fix.

### 4. Codex's retraction ("an unquoted current hash returns 200"): **keep it. It is consistent with writes and deliberate**

- RFC 9110 §2.4, fetched 2026-11-23 from <https://www.rfc-editor.org/rfc/rfc9110.txt>: "Unless noted otherwise, a
  recipient MAY attempt to recover a usable protocol element from an invalid construct."
- #571 kept the same recovery for writes, in `test_if_match_forms_571.py:39`: `("{tag}", 200, None, None)`, "without its
  quotes, as cmapi always took it". `docs/GLOSSARY.md:55` says "One tag sent without its quotes is still read as that
  tag."
- Reads and writes share one parser, `if_match_tags` (`core/etag.py:66-80`). Its docstring already names both callers.
  Making reads strict would need a second parser, or a flag, for no gain in safety. Recovering the current tag can only
  give the answer that a correctly quoted tag gives, so it cannot hide a lost update on a read.
- The ruling is pinned by two new CASES rows: `(["{tag}"], [], 200)` and `(["{tag}"], ["{etag}"], 304)`. Both pass on
  head and on the fix. The second also proves that the read goes on to If-None-Match after a recovered If-Match.

### 5. The node IDs and files, before and after

| Run | Tree | Result | File |
|---|---|---|---|
| The 47 node IDs | head | **47 passed** | `r2-outputs/before-47-nodeids.txt` |
| The 47 node IDs | fix | **47 passed** | `r2-outputs/after-47-nodeids.txt` |
| 8 named files + `test_cors.py` + `test_problem_type_docs.py` | head | **404 passed** | `r2-outputs/before-named-files.txt` |
| The same 10 files | fix | **463 passed**: +36 CASES, +21 CORS and +2 doc tests | `r2-outputs/after-named-files.txt` |
| The new test file on head code | head + new tests | **8 failed, 100 passed**: as expected | `r2-outputs/before-new-tests-on-head-code.txt` |
| 7 mutants, the test file only | fix + mutant | each killed (table in ruling 2) | `r2-outputs/mutant-*.txt` |
| `scripts/doc-citations.py --check` | head / fix | 0 problems / 0 problems | `before-doc-citations.txt`, `after-generator-checks.txt` |

The 8 named files are `test_api_docs`, `test_api_samples`, `test_api_standard`, `test_read_preconditions_590_593`,
`test_if_match_surface_581`, `test_if_match_forms_571`, `test_namespace_etag_doc_565` and `test_doc_citations`. For
`doc-citations`, I ran `git init` and `git add -A` in my two copies only, so that `git ls-files` works. Nothing was
committed or pushed.

### 6. The contract: nothing to regenerate

No description of the API changed. `cmapi/contract/openapi.json` and `cmapi/src/cmapi/contract/samples.json` are
byte-identical to head (`cmp`). The checks, all on the fix (`r2-outputs/after-generator-checks.txt`,
`after-contract-gate.txt`):

- `scripts/api-examples-doc.py --check`: exit 0.
- `contract/changelog.py --check`: exit 0.
- `node cmapi-portal-ui/scripts/api-types.mjs --check`: "ok - the API types match". Its node_modules were symlinked
  from wt-590, whose lockfile is identical.
- `contract/lint.sh`: "No results with a severity of 'warn' or higher".
- `contract/lint-test.py`: 37 cases, 0 failed.
- `contract/gate.sh base head`: "No breaking changes", exit 0.

The symlinks were removed afterwards.

## Files and lines in the fixed copy

- `cmapi/src/cmapi/core/cors.py`
  - 88-93: the class docstring.
  - 103-107: the `vary_send` comment, reflowed.
  - 116-120: the new `allow_explicit_origin`.
- `cmapi/src/cmapi/core/problem_docs.py:31`: one line. Lines 53 and 54, which docs/14 cites, do not move.
- `cmapi/tests/service/test_read_preconditions_590_593.py`
  - The module docstring, the imports and `ROOT`.
  - CASES rows 10-18.
  - The `{tag}` format in the request lines.
  - The 304 assertion.
  - The reads-documented assertion.
  - The two doc tests.
  - The `_cors_answer` split, `ALLOWED`, and the 21-case CORS test.
- `cmapi-portal-ui/tests/api/portal.test.mjs:2581`: the comment only.
- `docs/08-code-status.md:89` and `docs/18-configuration.md:503`.

The full patch is `r2-outputs/fix.diff` (unified, `a/` and `b/` prefixes).

## What I did not run

- The full service suite. The brief said to run targeted files only, and another session's full suite was running
  twice during this review.
- Anything on kind or CRC. The front-door nginx test (`deploy/tests/front-door-test.py`) was not run.
- The portal Playwright suite. Only a comment changed there.

The other session ran its full suite twice during this review. My jobs refused to start while it ran: each checks with
`pgrep -f "[p]ytest tests/service"` from a script file. In batch 1, the later jobs refused on that check. I then stopped
the idle batch 2 to apply two line-length fixes, and batch 3 ran everything after. The after results above are from batch 3, on the final files. No two service sessions overlapped.

## New defects for the coordinator to file

- None in the code beyond the out-of-scope #604 and #605.
- One process finding, already fixed in the patch: reviewer 1's `precondition-failed` snippet would have failed
  `doc-citations --check`, because it moved lines that docs/14 cites.
- One observation, not filed: Starlette 0.41.3 sends `Access-Control-Expose-Headers` to a denied origin too, because
  `simple_headers` is applied before the origin check. A browser ignores it without `Access-Control-Allow-Origin`. It is
  upstream, harmless and unchanged here.

I left the two databases `r2_598_head` and `r2_598_fix` on 55432 so that the runs can be repeated. Drop them when done.
