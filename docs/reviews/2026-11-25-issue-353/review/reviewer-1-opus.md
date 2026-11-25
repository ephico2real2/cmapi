# PR #681 (closes #353): reviewer 1 (Opus 5.5 high, standing in for Codex)

Reviewed `head/` at `c0cf45f` against `base/` at `c2b89f5`, 2026-11-25. I did not write the change. All measurements come from
the venv `wt-655-outputs/venv-merged` (FastAPI 0.162.2, Starlette 1.10.0, pydantic 2.14.2, pydantic-core 2.50.2, uvicorn 0.32.1,
CPython 3.12.14) and the service suite on PostgreSQL 16 `cmapi_r1_681`, on this Mac. No cluster was used. Outputs are in
`r1-outputs/`, and the fix is `r1-outputs/fix.diff`.

## Findings

| # | Severity | Finding | Fix |
|---|---|---|---|
| H1 | High | The new walk has no bound on cost or on the size of the answer. A 1 MB body got a 93 MB answer in 15 s on the event loop. A deep body with no surrogate costs O(size × depth). | In `fix.diff` |
| M1 | Medium | A body nested about 600 or more deep answers 500 internal-error (RecursionError), on base and on head. `holds_nul` (#653) recurses, and so does the new `surrogate_places`. | In `fix.diff` |
| L1 | Low, in the changed lines | The README misquotes RFC 7493 §2.1: it writes `"𐊭"` (U+102AD) where the RFC writes `"𐊭"` | In `fix.diff` |
| L2 | Low, Backlog | cmapi has no limit on body size. Pydantic's own errors already amplify a body: 1.68 MB in gives 10 MB out in 1.2 s, measured on base. | None (Backlog) |
| L3 | Low, Backlog | `_shown` is ambiguous. A key holding U+D800 and a key holding the 6 ASCII characters `\ud800` are both named `\ud800`. | None (Backlog) |

### H1: the walk and the answer are unbounded (High)

**Where:** `cmapi/src/cmapi/core/models.py`, `surrogate_places` (new in this PR), and `main.py` `request_validation_handler` (one
error for each place).

**Measured through the app** (`r1-outputs/probe-head.txt` and `probe-base.txt`, TestClient, `POST .../namespaces?dryRun=true`):

| Body (an unknown member `x`) | Base: answer, time | Head: answer, time |
|---|---|---|
| 1.00 MB: 100,000 `"\ud800"` nested 400 lists deep | 422, 309 B, 0.044 s | 422 with 100,000 errors, **93,389,474 B, 15.374 s** |
| 1.00 MB: 100,000 `"\ud800"`, flat | 422, 309 B, 0.039 s | 422, 13,389,474 B, 0.939 s |
| 1.20 MB: 300,000 `""` nested 400 deep (no surrogate) | 422, 309 B, 0.074 s | 422, 309 B, **0.965 s** |
| 1.68 MB: 100,000 integer annotation values (pydantic's own errors, for comparison) | 422, 9,989,474 B, 1.226 s | the same |

**Measured on the walk alone** (`r1-outputs/probe_walk.txt`). With 300,000 empty strings below depth d, `surrogate_places` takes
0.785 s at d=300, 1.020 s at d=440 and 1.849 s at d=900. `holds_nul` takes 0.04 s on the same input. The cost is O(size × depth)
because each level builds `(*place, index)` for every child, and `found +=` copies the results up through each level.

FastAPI validates the body on the event loop. So any authenticated requester stalls every request while this runs, and the
answer is about 93 times the size of the body. cmapi has no body-size limit (L2).

**Fix (`fix.diff`):**
- One walk, `strings_of`, is a loop over a stack of iterators, not recursion.
- A place is a linked list `(parent, step)`. It is built into a tuple only for a place that is named (`place_of`).
- `surrogate_places` stops at `MAX_PLACES = 20`, in document order.
- `holds_nul` uses the same walk.
- docs/02 says "the first 20 in document order".

Measured after the fix (`r1-outputs/walk_fix_verify.txt`):

| Input | Head | Fix |
|---|---|---|
| Flat, 300,000 strings | 0.180 s | 0.218 s |
| 300,000 strings, 400 deep | 1.048 s | 0.216 s |
| 300,000 strings, 900 deep | RecursionError | 0.221 s |
| 100,000 surrogates, 400 deep | 2.969 s, 100,000 places | 0.034 s, 20 places |

On 30,000 random bodies, the fixed walk and head's walk agree. The bodies had nested dicts and lists, surrogate keys, NUL,
reversed pairs and valid pairs. `holds_nul` gave the same answer, and the fixed `surrogate_places` equals head's first 20 places,
in the same order.

**Test (fails on head, passes on fix):** `test_a_refusal_names_the_first_twenty_places_only`. A body of 1,000 lone surrogates must
name `body.x.0` to `body.x.19`. Head names 1,000.

I did not write a timing test: it would be flaky with CRC sharing the machine. The linear cost is shown by the measurements above,
not by a test.

### M1: a deep body answers 500 (Medium; it predates the PR, and the PR's new walk has the same defect)

`json.loads` parses a body nested 8,000 deep. Its limit is the C stack: depth 20,000 raises RecursionError
(`probe_primitives.txt`). `holds_nul` uses 2 Python frames for each level, so inside the app it raises RecursionError from about
depth 600.

| Body | Base | Head |
|---|---|---|
| Depth 450 | 422 | 422 |
| Depth 600, 1000 or 5000 (plain or surrogate leaf) | **500 internal-error** | **500 internal-error** |

`r1-outputs/head-deep-600.log` shows `"error_type": "RecursionError"`, 479 frames of `holds_nul` (models.py:45), reached from
`refuse_what_is_not_text`. `framework_refusal` handles a RecursionError from the decoder, not from the validator, so this one
reaches `UnhandledToProblemMiddleware`.

If `holds_nul` alone were fixed, the PR's recursive `surrogate_places` would overflow next, at about depth 900. So the fix
belongs in this PR, and H1's iterative walk fixes both.

**Test:** `test_a_body_nested_deeper_than_python_recurses_is_refused_with_422_not_500[600|5000]`. The body is built as bytes,
because `json.dumps` itself recurses.
- A plain leaf must give 422 `extra_forbidden` at `body.x`.
- A `\ud800` leaf must give 422 `string_surrogate` at `body.x.0.0…`.
- Head gives 500 for both depths.

### L1: README misquote (Low, in the changed lines)

The fetched RFC 7493 §2.1 (`r1-outputs/rfc7493.txt`, fetched 2026-11-25 15:57Z) reads:

> thus, "\uDEAD" is invalid because it is an unpaired surrogate, while "𐊭" would be legal.

README line 58 has the bytes `F0 90 8A AD` (the character U+102AD) in place of the escape. The point of the sentence is that an
*escaped* pair is legal. `fix.diff` restores the RFC's text.

### Backlog (Low, no fix)

- **L2.** cmapi has no limit on request-body size. Neither cmapi nor uvicorn sets one: a grep for a body limit in `src/` found
  none. Pydantic already answers 100,000 wrong annotation values with 100,000 errors: 1.68 MB in, 10 MB out, 1.2 s, the same on
  base. Recommendation: a body limit at the edge, a middleware that answers 413, and a cap on errors for each answer. This needs
  a design decision on the size. It predates #353, and H1's fix removes this PR's part of it.
- **L3.** `_shown` writes a surrogate as `\udXXX`. A key that holds those ASCII characters is named the same way, for example
  `body.annotations.no\ud800te.[key]`. This is cosmetic: `message` says "holds U+D800" only for a real surrogate.

## The seven points, confirmed or refuted

1. **Every body is a RequestBody. Confirmed.**
   - grep of `head/cmapi/src` for `request.json`, `request.body`, `await request.`, `.stream()`, `Form(`, `UploadFile` and
     `Body(`: none in a route.
   - `tokensave_search` (literal) for `request.json(` and `await request.body(`: count 0. That graph is the main checkout, not
     the export.
   - The 8 body classes all inherit RequestBody: SwitchBody, DecisionBody, NamespaceCreate, NamespacePatch, PruneConfirm,
     ExtendBody, SetBody and PermanentBody.
   - `test_every_request_body_is_a_request_body` passed on head. It walks `route.body_field` of every APIRoute, unions included.
   - There is no other before-validator or field validator in `src/` that could run first and echo the value. A grep for
     `model_validator` and `field_validator` finds only this one.
   - Other `json.loads` calls: the list cursor is HMAC-checked before it is parsed (`listquery.py:105-112`); the reader token
     comes from the Kubernetes API; the rest read config, contract or subprocess output.
2. **Keys, nesting and size. Coverage confirmed; the bound is refuted (H1, M1).** Keys, nested lists and dicts, a top-level
   unknown member and a body that is not an object are all reached. Not an object, on head: `"\ud800"` gives `body`, and
   `["\ud800"]` gives `body.0`. `{"\ud800":"\ud800"}` gives `body.\ud800.[key]` and then `body.\ud800`. `null` and `1` keep
   `model_attributes_type`.
3. **The answer and the log. Confirmed.**
   - Every 422 in the probes parsed as JSON. Starlette's `JSONResponse` encodes with `ensure_ascii=False` and then UTF-8, so a raw
     surrogate would raise there; none does, because keys go through `_shown` and the messages are fixed text.
   - The 422 path logs only the `http` line, which carries the route template, not the path or the field
     (`observability.py:175`).
   - structlog's `JSONRenderer` escapes non-ASCII.
   - I did not capture a 422's log line. The claim rests on reading the code.
4. **Path and query, on the wire. Confirmed.** A real uvicorn served the app, over both h11 and httptools, with a raw socket
   (`probe-head.txt`, `wire[...]`):
   - Query `%ED%A0%80`: 200, empty list. Path: 404 `'a���b'`, which is U+FFFD.
   - `%5Cud800` arrives as the 6 ASCII characters `\ud800`: query 200, path 404.
   - The unencoded bytes ED A0 80 in the target: uvicorn answers 400 "Invalid HTTP request received" before the app.
   - Over the wire, a body holding `"\ud800"` or the raw bytes ED A0 80 gets 422 `body.justification`.
5. **Other entry points. Confirmed.**
   - On base, `application/merge-patch+json` and `application/json; charset=utf-8` were 200 (dry-run create) and 500 (PATCH).
     On head they are 422 `string_surrogate`: FastAPI parses `+json` (`routing.py:470`).
   - No content type, `text/plain` and `multipart/form-data` give the body as bytes, so 422 `model_attributes_type`. Bytes cannot
     hold a surrogate, and python-multipart is not installed.
   - Starlette decodes headers as Latin-1. `Headers` gives `0xed 0xa0 0x80` for those bytes, and a POST with
     `Idempotency-Key: k<ED A0 80>` answered 200 over h11 and httptools.
   - I did not run `If-Match` with raw bytes against a PATCH. It is inferred safe from the same Latin-1 decoding.
   - No webhook route exists. `ports.py` names Argo CD Notifications as an option, with no route.
6. **The tests can fail. Confirmed.** All on `test_lone_surrogate_353.py` (`r1-outputs/suites2.txt`):

   | Run | Result |
   |---|---|
   | head, with `test_client_input_653.py` | 42 passed |
   | base | 11 failed, 2 passed (the valid pair and the query/path guard), as the implementer reports |
   | Mutant: check removed | 11 failed |
   | Mutant: key check removed | 2 failed (annotation-key, unknown-member) |
   | Mutant: a valid pair refused (`[\ud800-\udfff\U00010000-\U0010ffff]`) | 1 failed (`test_a_surrogate_pair_is_one_character_and_is_taken`) |

   The query/path test is a guard that passes on base too, as its docstring says.
7. **Behaviour outside #353. Two changes, otherwise none found.**
   - The deep-body 500 and the amplification above.
   - The validator is renamed from `refuse_nul`; nothing references the old name.
   - For any other error, the handler's output is unchanged: `place=()`, so the field is the join of `loc`.
   - Noncharacters are still taken, as the README chose.
   - A raw CESU-8 pair (ED A0 BD ED B8 80) decodes to two lone surrogates and is refused, which RFC 3629 supports. No test covers
     it; this is a note, not a finding.

## Research, verified

- **RFC 8259 §8.2 and §8.1:** fetched (`r1-outputs/rfc8259.txt`). The implementer's quotes match word for word.
- **RFC 7493 §2.1 and §3:** fetched. The quotes match, except L1.
- **Framework citations**, read in the venv:
  - FastAPI `routing.py:458-475` (JSON when the subtype is `json` or ends in `+json`) and `:495-499` (the 400).
  - Starlette `requests.py:266` `json.loads(body)`.
  - CPython `json/__init__.py:341` `surrogatepass`.
  - uvicorn `h11_impl.py:198` and `httptools_impl.py:257` `unquote`.
- **Primitives** (`probe_primitives.txt`):

  | Input | json.loads gives | pydantic | `.encode("utf-8")` |
  |---|---|---|---|
  | `\ud800` | U+D800 | `model_validate` accepts | UnicodeEncodeError |
  | Bytes ED A0 80 | U+D800 | accepts | UnicodeEncodeError |
  | `😀` | U+1F600 | accepts | works |
  | Bytes F0 9F 98 80 | U+1F600 | accepts | works |
  | `\ude00\ud83d` | stays as two lone surrogates | accepts | UnicodeEncodeError |

## The fix

- **File:** `r1-outputs/fix.diff`, 179 lines, built from the repository root. It changes `cmapi/src/cmapi/core/models.py`,
  `cmapi/tests/service/test_lone_surrogate_353.py`, `docs/02-technical-design-v2.md` and the issue's README.
- **Applies:** `patch -p1 -F0` applied cleanly to a copy of `head/`, and the result is byte-identical to the tested copy.
- **Before:** on head with only the new tests, 3 failed and 13 passed. The two depth cases gave 500, and the cap case named 1,000
  places.
- **After:** `test_lone_surrogate_353.py`, `test_client_input_653.py`, `test_framework_problems_646.py`, `test_value_error_648.py`
  and `test_api_docs.py`, 100 passed in 125.76 s (`r1-outputs/fix-tests.txt`).
- **Not run:** the full suite, kind or CRC. The README's record ("13 tests") would need its count updated by the coordinator.

**Correction:** my probe `test_deep[15000]` failed with RecursionError inside my own probe's `json.dumps`, not in cmapi. It is no
finding.
