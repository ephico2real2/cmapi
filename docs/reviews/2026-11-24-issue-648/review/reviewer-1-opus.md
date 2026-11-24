# PR #652 (#648): reviewer 1 (Opus 5.5 at high)

I review this PR in place of Codex, which is at its usage limit. I did not write this change.

- **Export:** `head/` is the PR head and `base/` is main `a2a55f3`.
- **Where the runs happened:** every run used the Mac, against PostgreSQL 16 on `127.0.0.1:55432`, database `cmapi_603`. No cluster was used.
- **How to read the claims:** each claim below says whether it was measured or inferred. Every output file named here is under `review-652/r1-outputs/`.

## Verdict

Every claim in the brief holds:
- The PR keeps every deliberate refusal byte for byte.
- No deliberate client error becomes a 500, as measured.
- Its 500 leaks no text.
- It changes neither #645 nor #647.
- The PR's 7 tests kill all 6 mutants.

The PR's new `requested_qty` misses two kinds of client value:
- **F1, Medium.** A quantity too large for `Decimal` raises `decimal.InvalidOperation`, which is an `ArithmeticError`, not a `ValueError`. It answers 500 internal-error.
- **F2, Low.** A value with more than 28 digits hits Decimal's `%` on the step check. That also answers 500.

Both answered 500 on `a2a55f3` too, so they are not regressions. They are gaps in the PR's own contract: "One that is not a quantity is the caller's to correct: 422".

There are also two smaller issues:
- **F3, Low.** A `ValueError` inside the CSV stream logs `error_type: ExceptionGroup`.
- **F4, Low.** Two of the README's citations are wrong.

`fix.diff` fixes F1 to F4, with tests, and relocates the doc citations that the change moved.

Two more defects are outside this PR, and both answer 500 on base and head alike:
- **O1.** A NUL in a text value of the request.
- **O2.** `:extend` with a day count past what `date` can hold.

Their fixes and tests are in `outside.diff`, or `outside-after-fix.diff` if `fix.diff` is applied first.

## Research: each source fetched 2026-11-24, and each README quote checked

| Source | What it says | README |
|---|---|---|
| RFC 9457 §3.1.4 (rfc-editor.org/rfc/rfc9457.txt, `sources/rfc9457.txt:329-330`) | "The "detail" string, if present, ought to focus on helping the client correct the problem, rather than giving debugging information." | Exact |
| RFC 9457 §5 (`:529-536`) | "Risks include leaking information that can be exploited to compromise the system, access to the system, or the privacy of users of the system." and "Generators providing links to occurrence information are encouraged to avoid making implementation details such as a stack dump available through the HTTP interface, since this can expose sensitive details of the server implementation, its data, and so on." | First sentence exact. The second leaves out its subject, "Generators providing links to occurrence information". F4 corrects it |
| RFC 9110 §15.5.21 (`sources/rfc9110.txt:7826-7830`) | "The 422 (Unprocessable Content) status code indicates that the server understands the content type of the request content ..., and the syntax of the request content is correct, but it was unable to process the contained instructions." | Exact |
| RFC 9110 §15.6.1 (`:7865-7867`) | "The 500 (Internal Server Error) status code indicates that the server encountered an unexpected condition that prevented it from fulfilling the request." | Exact |
| pydantic validators (docs.pydantic.dev/latest/concepts/validators/, which redirects to pydantic.dev/docs/validation/latest/concepts/validators/; `sources/pydantic-validators.html`) | "To raise a validation error, three types of exceptions can be used: ValueError: this is the most common exception raised inside validators." | Exact, and the redirect is as stated |
| FastAPI 0.115.6, installed `fastapi/_compat.py:127-135` | `ModelField.validate` catches `ValidationError` of `validate_python` and returns the errors | Exact |
| `fastapi/routing.py:342-346` | `if errors: validation_error = RequestValidationError(_normalize_errors(errors), body=body); raise validation_error` | Exact |
| `fastapi/routing.py:175-178` | `serialize_response` raises `ResponseValidationError(errors=..., body=response_content)` when the response model refuses | Not in the README; asked for by the brief |
| `fastapi/exceptions.py:149,157,167` | `ValidationException(Exception)`, `RequestValidationError(ValidationException)`, `ResponseValidationError(ValidationException)` | Exact. Measured MRO: `ResponseValidationError -> ValidationException -> Exception`, which is not a ValueError |
| `fastapi/routing.py:267-288` | A body that `json.loads` cannot parse is a `RequestValidationError` (`json_invalid`). Any other exception of the read, `UnicodeDecodeError` among them, becomes `HTTPException(400, "There was an error parsing the body")` | Relevant to #645 |
| Starlette 0.41.3 `_exception_handler.py:16-20` | Looks a handler up along `type(exc).__mro__` | Exact |
| Same file, re-raise | `if handler is None: raise exc` is at **:52-53**. Lines :49-50 are the class lookup | The README says `:49-50`. F4 corrects it |
| pydantic_core 2.50.2 | Measured `ValidationError.__mro__ = (ValidationError, ValueError, Exception, BaseException, object)` | Exact |
| apimachinery master, `pkg/api/resource/suffix.go:194-199` (`sources/suffix.go`) | `parsed, err := strconv.ParseInt(string(suffix[1:]), 10, 64)`. `quantity.go:371-470` takes `1e9999999` on its fast path | New. It is the basis of F1's message: such a value is a quantity, and cmapi cannot hold it |
| psycopg 3.3.8, installed `psycopg/types/string.py:50-52` | `if "\x00" in obj: raise DataError("PostgreSQL text fields cannot contain NUL (0x00) bytes")` | New. It is the basis of O1 |
| Starlette `responses.py:252`, `_utils.py:79-80` | StreamingResponse runs in `anyio.create_task_group()`. Starlette's own `collapse_excgroups` unwraps one-member groups | New. It is the basis of F3 |

How a request model's validator behaves:
- **Read in the installed sources.** A `ValueError` raised in a validator of a request model becomes a pydantic `ValidationError`. FastAPI's `validate` then catches it and raises `RequestValidationError`, which is not a ValueError. So the removed handler never saw it.
- **Measured.** A body that breaks `DnsLabel` and a `limit=0` answer 422 `validation-failed` "The request is not valid: ..." on both base and head (`probe/compare.txt`: `namespaces.limit-0`).
- **Measured.** A response model's refusal is a `ResponseValidationError`, and it was already 500.

## Claim 1: the inventory is complete. Confirmed, by measurement and by reading

What I read:
- **The code graph was stale for this.** The tokensave graph of `/Users/olasumbo/gitRepos/cmapi-design` serves `a10cf76`, which is older than `a2a55f3`. So I searched the export directly for `raise ValueError`, `ValueError(`, `except ...ValueError`, `fromisoformat`, `strptime`, `json.loads`, `.decode(`, `b64decode`, `model_validate`, `int(`, `float(`, `Decimal(` and tuple-unpacking `split`.
- **What I covered.** I read every hit outside `tools/`, `jobs/` and migrations. I read each route of the 13 routers, and the pipeline's request path: `requester_for`, `label_value_of`, `quota_for`, `limits_for`, `_merge_limits`, `plan_extend` and `plan_set`, and `ListQuery`, `Lister._open`, `etag._http_date`, `Authenticator.authenticate` and `KeycloakAdminDirectory`.

What I measured:
- **The probe.** `probe/test_r1_probe.py` sent 59 hostile but well-formed inputs, on base and on head. They cover:
  - label keys with two slashes, empty keys and non-ASCII keys, and NUL, non-ASCII and two-`@` values;
  - quotas and limits that are empty, negative, `1e40`, `1e999999999999999999`, a dotted kind, a non-overridable `min`, and storage pvc;
  - a tier that does not exist, `onBehalfOf` from a person, and a username that is not a label value;
  - invalid UTF-8 and invalid JSON bodies;
  - a PATCH of a custom namespace that is not a quantity, has Git's own text, or removes a label;
  - `:extend` days of `1e10` and `999999999` and an `until` of 30 Feb, and `:set` far in the future;
  - NUL in a query or a path, garbage cursors, `limit=0`, a bad `state`, a bad `since` and a bad `groupBy`;
  - four `If-Modified-Since` forms, a non-UTF-8 token header and bad base64.
- **The result.** All 59 answers are identical on base and head (`probe/compare.txt`). On base, every `validation-failed` that did not come from FastAPI came from rows 1 and 2 of the README. No other `ValueError` from client input reached the old handler.

Pydantic field validators on request models:
- The request models have no `field_validator` or `model_validator`, only `StringConstraints` (`DnsLabel`, `core/models.py:16`) and types.
- They raise `RequestValidationError` before any handler runs, so they are unaffected.

**Not tested:** NUL or other odd values in a JWT's claims, which the IdP signs. Also any route input I did not think of: the probe is a sample, not a proof.

## Claim 2: the deliberate 422 bodies are byte-for-byte unchanged. Confirmed

Measured, three ways:
- **The PR's test on base.** `test_value_error_648.py` ran on base's source (`test-648-on-base.txt`). The 4 deliberate tests pass with whole-body equality, and the 3 internal tests fail.
- **The probe.** The probe's bodies for `create.username-not-label`, `create.quota-empty`, `create.quota-negative`, `patch.quota-not-quantity`, `patch.limit-not-quantity` and `create.quota-huge-exponent` are equal on base and head (`probe/compare.txt`).
- **The side effects.**
  - `count_refusal` counts `validation-failed` in no metric (`pipeline.py:552-559`; `CMAPI_REFUSALS` does not hold it).
  - `refusals()` records only `RECORDED` codes, and `validation-failed` is not among them.
  - So neither the metrics nor the stored rejections change.

`_kept` preserves behaviour. I read it against `_same` in all four sites. Values reach it as `str` only (`quota_for` applies `str(v)`, and `flatten_limits` applies `str(v)`), so the `(None, None)` case cannot happen. It refuses at the same key and in the same order. Mutant m2c drops `requested_qty` from `_kept`, and the PR's PATCH test kills it.

## Claim 3: the 500. Confirmed, with F3

What I measured:
- **No text in the answer.** The PR's tests assert that the answer holds no exception text, and that the log line `unhandled` holds `error_type`, `route` and the request ID. Mutants m3 (leaks `str(exc)`) and m4 (drops `error_type`) are each killed by the 3 internal tests.
- **The stream, measured with my own test.** A `ValueError` raised after the CSV export started streaming goes like this:
  - the 200 has gone;
  - the stream ends early, with no text of the exception (`test-648-fixed-on-fix.txt`);
  - `UnhandledToProblemMiddleware` logs it and re-raises it (`main.py:112-113`).
  - On base, Starlette's `ExceptionMiddleware` would have raised `RuntimeError("Caught handled exception, but response already started.")` (`_exception_handler.py:55-56`), so head is no worse.
  - **F3:** the logged `error_type` is `ExceptionGroup`, not `ValueError`, because the response's anyio task group wraps the error (`tests/findings-on-head.txt`).

What I read:
- **No background task.** No route uses `BackgroundTasks` (`grep`: no hit outside docs).
- **Exceptions outside the middleware.** An exception raised in a middleware outside `UnhandledToProblemMiddleware`, CORS or metrics, reaches Starlette's `ServerErrorMiddleware`, whose plain 500 holds no exception text. This PR does not change that.

## Claim 4: the interaction with PR #645 (#644, #646). No change. Shown

The code:
- `pr645/pr645-main.diff` holds #645's main.py. Its `framework_refusal` is an `@app.exception_handler(HTTPException)`.
- FastAPI raises `HTTPException(400)` from the failed body read, with the `UnicodeDecodeError` or `RecursionError` as its `__cause__` (`fastapi/routing.py:284-288`).
- Starlette looks up `type(exc).__mro__` of the `HTTPException` (`_exception_handler.py:16-20`), never its cause's, so a `ValueError` handler could not have taken it.

What I measured:
- `git merge-file` of #652's main.py, base `a2a55f3` and #645's main.py merges with 0 conflicts (`pr645/merged-main.py`).
- On a tree with #645's six files and that main.py, three files ran together: `test_framework_problems_646.py` (including `b"\xff"`, `b'{"name": "caf\xe9"}'`, deep nesting and 5000 digits, each to 422 `json_invalid`), `test_router_problems_644.py` and `test_value_error_648.py`. Result: **40 passed** (`pr645/merged-tests.txt`).
- Head alone, with no #645, answers an invalid UTF-8 body with the same 400 "There was an error parsing the body" as base (`probe/compare.txt`, `create.invalid-utf8-body`).

## Claim 5: the interaction with PR #647 (#626). No reliance. Shown

The code:
- #647's `NotUtf8` is an `Exception`, not a `ValueError` (`wt-626` HEAD `190e406`, `core/git/base.py:65`).
- It is caught as 409 `folder-not-utf8` at `pipeline.py:208, 219` and at `jobs/push_branch.py:39`.
- Its remaining decodes use `errors="backslashreplace"` or are git's ASCII.
- Its tests assert no 422 for a codec path.

What I measured: on a three-way merge of #647's 12 files (from merge base `ff5e992`) onto #652's head, with 0 conflicts, `test_non_utf8_names_626.py` and `test_value_error_648.py` ran together. Result: **24 passed** (`pr647/merged-tests.txt`).

## Claim 6: the tests and the mutants. Confirmed

All runs are from `cmapi/`, with the brief's command.

| Run | Result | File |
|---|---|---|
| PR test on head | 7 passed | `head-new-test.txt` |
| PR test on base source | 3 failed (codec, dependency, PlanView), 4 passed | `test-648-on-base.txt` |
| m1: keeps the old handler | 3 failed (the internal cases) | `mutants/m1-keep-old-handler.txt` |
| m2a: drops the username refusal | 1 failed | `mutants/m2a-no-label-refusal.txt` |
| m2b: `requested_qty` raises the bare ValueError | 3 failed | `mutants/m2b-requested-qty-raises-valueerror.txt` |
| m2c: `_kept` without `requested_qty` | 1 failed (the PATCH test) | `mutants/m2c-kept-without-requested-qty.txt` |
| m3: leaks `str(exc)` into the 500's detail | 3 failed | `mutants/m3-leak-str-exc.txt` |
| m4: drops `error_type` | 3 failed | `mutants/m4-no-error-type.txt` |

## Findings

### F1, Medium: a quantity too large for Decimal answers 500, or 422 with decimal's own text

- **Where:** `core/tiers.py:49-69` (`qty`) and `:133-140` (`requested_qty`), on head.
- **What happens:**
  - `qty("1e9999999")` raises `decimal.InvalidOperation`. Its MRO is `InvalidOperation -> DecimalException -> ArithmeticError`, measured. `requested_qty` catches only `ValueError`, so the caller's own value answers **500 internal-error**. Measured on head: `custom(quota={"requests.cpu": "1e9999999"})`, and the same for `limitRange.container.max.cpu` (`tests/findings-on-head.txt`).
  - `qty("1e999999999999999999")` raises `ValueError("valid range for prec is [1, MAX_PREC]")` from `localcontext`. `requested_qty` sends that text as the 422's `detail`. That is debugging information, which RFC 9457 §3.1.4 asks a detail not to give.
- **Why this is the client's value:** apimachinery parses the exponent as an int64 (`suffix.go:195`) and takes `1e9999999`. So it is the caller's value, and the right answer is 422 with a text that says what to correct.
- **Not a regression:** the same inputs answered 500, and 422 "valid range for prec", on `a2a55f3`.
- **The cost of a large value, measured:** `qty("1e999999")` takes 0.021 s and holds 1,000,009 digits. `1e1000000` is the first exponent past `Emax`.
- **Fix:** `fix.diff`, `core/tiers.py`. `qty` wraps its arithmetic and raises `ValueError(f"quantity {value!r} is out of range") from None`. Its other callers that catch `ValueError` (the catalog load at `tiers.py:371/396/407`, `validate._same_amount`, `capacity_ledger`) now also take this case, where before an `InvalidOperation` would have escaped them.
- **Test:** `test_a_requested_quantity_too_large_to_hold_is_validation_failed`, with 3 parameters, in `test_value_error_648.py`. It fails on head: 500, 422 with the prec text, and 500. It passes with the fix (`test-648-extended-on-head.txt`, `test-648-fixed-on-fix.txt`).

### F2, Low: the step check runs in 28 digits

- **Where:** `core/tiers.py:527` on head.
- **What happens:** `v % st` uses Decimal's default context, so a quotient of more than 28 digits raises `DivisionImpossible`, which is an `InvalidOperation`.
- **When it is reached:** only when the key has a step and no max. That is allowed for sizable keys: the catalog demands a max only for overridable ones (`tiers.py:419-421`).
- **Measured:** pods with no max and a step of 10, value `1` followed by 39 zeros and `1` (41 digits). Head answers **500**.
- **Fix:** a helper, `_off_step(value, step)`, that sets the precision to the value's digit count plus one. Both values are whole nano-units from `qty`, so the quotient has at most as many digits as `value`. The helper is used in `_out_of_bounds` and in the catalog's step check at load.
- **Test:** `test_a_requested_value_of_more_digits_than_decimal_keeps_is_checked_against_the_step`. It expects 422 `custom-out-of-bounds` with the item, and 200 for a whole number of steps. It fails on head with 500 and passes with the fix.

### F3, Low: `error_type` names the ExceptionGroup of a stream failure

- **Where:** `main.py:109-111` on head, the line this PR added.
- **What happens:** measured, `error_type: "ExceptionGroup"` for a `ValueError` inside `quotas:export`.
- **Fix:** unwrap one-member groups, as Starlette's `collapse_excgroups` does.
- **Test:** `test_a_value_error_after_the_csv_stream_started_is_logged_by_its_class_and_leaks_nothing`. It fails on head and passes with the fix.

### F4, Low (documentation): two README citations

- The Starlette re-raise is at `:52-53`, not `:49-50`.
- The RFC 9457 §5 quote leaves out its subject, "Generators providing links to occurrence information".

`fix.diff` corrects both, and adds F1, F2 and F3 to "What the change does".

### Doc citations

`fix.diff`'s main.py hunk moves nine cited lines of `docs/14` and `docs/15`. I ran `scripts/doc-citations.py --relocate`, then `--check`: **0 problems** (`doc-citations-after-fix.txt`). The tool needs `git ls-files`, and the export has no repository, so I gave it a stand-in, `r1-outputs/shim/git`, which lists the files with `find`. Before the change, `--check` also reported 0 on the head copy.

### O1, Low, outside the PR: a NUL in a request's text answers 500

- **What happens:** psycopg refuses a NUL in a text parameter before it sends the query (`psycopg/types/string.py:50-52`, raising `sqlalchemy.exc.DataError`), and that error is no `ValueError`.
- **Measured, 500 on base and head:**
  - `GET /api/v1/requests?status=%00`, `?clusterId=a%00`, `/requests/req%00x` and `/requests/req%00x/events`;
  - a create whose `justification` holds `\u0000`.
- **Fix:** `outside.diff`, `main.py`. An exception handler for `DataError` that answers 422 `validation-failed` when `exc.orig` is psycopg's NUL error, and re-raises any other `DataError`, which then becomes a 500.
- **Its risk:** the handler matches psycopg's message text. The test pins that text, so a psycopg upgrade that changes it fails CI rather than silently returning 500.
- **Test:** `test_outside_652.py`, 5 cases. They fail on head and pass with the fix (`tests/outside-on-head.txt`, `tests/outside-on-outside.txt`).

### O2, Low, outside the PR: `:extend` with too many days answers 500

- **Where:** `plugins/expiration/rules.py:155-157`.
- **What happens:** the code computes `base + timedelta(days=days)` before it checks `step > max_extension_days`. Days of `10**10`, `999999999` or `3000000` raise `OverflowError`.
- **Measured:** 500, on an expiring custom namespace.
- **Fix:** compute `step` from `days`, or from `until - base`, and check it first. Then move the date by `step`. This is the same result for every value that did not overflow before: when `days` is given, `(new - base).days == days`.
- **Test:** `test_extend_by_more_days_than_a_date_can_hold_is_expiration_limit`, 3 parameters. Each fails with 500 on head and passes with 422 `expiration-limit` with the fix.

## Observations, not findings

- **A bad value in Git blocks the namespace with a 500.** Say a hand-edited quota in Git is not a quantity, and the caller sends a valid new value for that key. The answer is now 500, because `_same` parses Git's text; before, it was a 422 that named Git's value. This follows the README's stated intent. Note that the old quota is parsed again at `pipeline.py:381-382`, at `compare` and at `beyond`, so letting `_kept` pass such a value would not unblock the namespace. Repairing it needs an edit to Git.
- **The README's inventory of `ValueError`s matches my reading.** It just could not see the `ArithmeticError` path, which was never a `ValueError`.

## Regression runs (measured)

All runs are on the Mac, against `cmapi_603`, under `r1-outputs/`.

| Tree | Suites | Result | File |
|---|---|---|---|
| `work/fix` (head + F1-F3) | `test_custom_tier_change`, `test_storage_limits_switch`, `test_review_255_apply`, `test_cors`, `test_head_605`, `test_value_error_648` (12 tests), `test_review_d_delivery` | 156 passed | `regress-fix.txt` |
| `work/full` (head + `fix.diff`, with docs) | core: `test_tiers`, `test_limitrange_split`, `test_metadata_pattern_subset_332`, `test_fable_review_245`, `test_policygen`, `test_render_listquery_config`, `test_review_255`, `test_lifecycle_expiration` | 239 passed, 32 skipped | `regress-full-core.txt` |
| `work/outside` (head + O1, O2) | core: `test_lifecycle_expiration`, `test_local_dry_run_613` | 40 passed | `regress-outside-core.txt` |
| `work/outside` | `test_review_479_expiry`, `test_dry_run_once_607`, `test_protected_366`, `test_api_samples`, `test_cors`, `test_head_605`, `test_outside_652`, `test_value_error_648`, `test_review_c_authz`, `test_plugins_switch` | 180 passed | `regress-outside.txt` |
| `work/full-both` (head + `fix.diff` + `outside-after-fix.diff`) | `test_second_pass` | 29 passed | `regress-second-pass-full-both.txt` |

Two runs failed in a way that does not touch the change.

**First:** `work/fix` core runs gave 1 failure.
- **The failing test:** `test_review_255.py::test_f5`, which reads `docs/02`.
- **Why:** the `work/fix` tree has no `docs/02`.
- **Re-run:** on `work/full`, it passes.

**Second:** a combined run on `work/full-both` gave 13 failed and 4 errors (`regress-docs-full-both.txt`).
- **The direct cause, measured:**
  - 16 errors are `FATAL: sorry, too many clients already`.
  - At that time, another session's whole `tests/service` suite was running (pid 42122), and so was a #647 review suite (pid 92048).
- **Re-run:** `test_second_pass` alone passed, 29 of 29.
- **What remains:** `test_doc_citations.py::test_each_citation_of_the_documents_is_the_text_that_was_recorded_for_it` fails on the **unmodified head copy** too (`regress-docs-full-control.txt`).
  - Why: it needs `git ls-files`, and the export is no repository.
  - Measured instead: `scripts/doc-citations.py --check` run through `shim/git` reports 0 problems on `work/full` (`doc-citations-after-fix.txt`).
  - The 10 tool tests of `test_doc_citations.py` are not run here: they need a real `git init`, which the shim does not provide.

## Files in `r1-outputs/`

- **Patches:**
  - `fix.diff`: F1 to F4 and the citation relocation. It applies to `head/` with `patch -p1 -F0`; checked on a fresh copy (`applycheck/`), and the result is identical to `work/full/`.
  - `outside.diff`: O1 and O2, against `head/`.
  - `outside-after-fix.diff`: the same, for a tree with `fix.diff` applied. Checked with `-F0 --dry-run`.
- **Tests:**
  - `tests/test_r1_findings_652.py`: the measurement tests run on head.
  - `tests/test_outside_652.py`.
  - The F tests are inside `fix.diff`.
- **Evidence:**
  - `probe/`: the probe, its base and head results, and `compare.txt`.
  - `mutants/`: one tree and one run log per mutant.
  - `pr645/` and `pr647/`: the merge and test evidence.
  - `sources/`: the RFCs, the pydantic page and apimachinery's `quantity.go` and `suffix.go`, as fetched.
  - `work/`: the scratch trees. `run.sh` is the test command, and `regress.sh` the regression runs.
