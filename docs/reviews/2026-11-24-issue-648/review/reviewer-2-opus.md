# PR #652 (#648) and #653: reviewer 2 (Opus 5.5 at high)

I did not write the change or reviewer 1's review. I checked reviewer 1's report (`r1-opus-report.md`) and both of its
patches against the code, the primary sources and tests. I return one patch, `r2-outputs/fix.diff`, against `head/`.

- **Where the runs happened:** on the Mac only, against PostgreSQL 16 on `127.0.0.1:55432`, database `cmapi_603`. No
  cluster was used. The whole service suite was not run.
- **The trees:**
  - `r2/` is the final tree: head with `fix.diff` applied.
  - `r2-outputs/work/head` is head.
  - `work/r1` is head with reviewer 1's `fix.diff` and `outside-after-fix.diff` applied.
  - `work/base` is main `a2a55f3`.
- **How to read the claims:** each one says whether it was measured, read or inferred. Every path below is under
  `review-652/r2-outputs/` unless the text says otherwise.
- **Load on the machine:** the load average was 734 during my runs. Another session's targeted run was taking 1484 % CPU:
  pid 6957, started by `wt-651-outputs/run-targeted.sh`. It is not mine, and I did not touch it. Each of my pytest runs first
  waited in the background until no whole-suite run was going.

## Rulings

| # | Reviewer 1 | Ruling | The test that decides |
|---|---|---|---|
| F1 | `qty` wraps its arithmetic and turns `ArithmeticError` and `ValueError` into "quantity '…' is out of range" | **Shape accepted, fix replaced.** A ValueError, so `requested_qty` answers 422, is right. Two cases still fail, both measured on `work/r1`. `"1e9000000000000000"` raises `MemoryError`, which is not caught, and **still answers 500**. `"1e2147483647"` reaches **906 MB of tracemalloc's peak** before decimal refuses it. Now an explicit bound runs before quantize, and only `DecimalException` is caught | core `test_tiers.py::test_a_quantity_too_large_to_hold_is_refused_before_it_takes_memory`: fails on head and r1 (`assert 906205380 < 50000000`), passes on r2. Service `test_value_error_648.py::…too_large_to_hold…[quota-memory-error]`: 500 on r1, 422 on r2 |
| F2 | `_off_step`: the precision is the value's digits plus one | **Accepted unchanged.** The bound holds: both values are whole nano-units from `qty`, so the integer quotient is at most the value's coefficient. Cost, measured: 0.02 ms at 1e20, 2 ms at 1e100000, and 861 ms at 1e999999 (a stepped key with no max). That is bounded by F1's limit | `…more_digits_than_decimal_keeps…`: fails on head, passes on r1 and r2 |
| F3 | Unwrap one-member ExceptionGroups for `error_type` | **Accepted unchanged.** The loop is Starlette's `collapse_excgroups` (`starlette/_utils.py:79-80`), and the task group is at `responses.py:252`. I read both in the installed 0.41.3 | `…csv_stream…`: fails on head, passes on r1 and r2 |
| F4 | README: the re-raise is at `:52-53`, and the §5 quote gets its subject | **Accepted.** The installed `_exception_handler.py` has `if handler is None:` and `raise exc` at 52-53, and the lookup at 49-50. The RFC text is quoted below | `doc-citations.py --check`: 0 problems |
| O1 | A `DataError` handler that matches psycopg's text "cannot contain NUL (0x00)" | **Rejected; the NUL is refused at input instead.** Measured on `work/r1`: 4 entry points still answer 500. They are an annotation value at create, an annotation in a PATCH, a rejection's comment and the pause reason. All four are jsonb, where the **server** refuses `\u0000` with `UntranslatableCharacter: unsupported Unicode escape sequence`, so the text never matches. A dry run answered 200 for a body that its submit then refused. A static path never reaches the database (N1) | `test_client_input_653.py`: 29 cases, all pass on r2 (see "Before and after") |
| O2 | `:extend` checks the step before it moves the date | **Accepted, and completed.** Behaviour preservation, measured: 43,272 inputs that worked on head give the identical answer on r1, with 0 differences. Of the 9,552 inputs that overflowed on head, **4,527 still raise OverflowError on r1**: a date already near 9999-12-31, or a large `maxExtensionDays`. I added a last-date guard | `…extend_past_the_last_date…`: 500 on r1, 422 on r2 |

## What reviewer 1 missed

1. **N1, a regression of #652 itself: a NUL in a static path.**
   - **The cause.** `GET /static/swagger/swagger-ui.css%00` makes `os.stat` raise `ValueError("embedded null byte")`
     (`starlette/staticfiles.py:164`, Starlette 0.41.3).
   - **Measured** (`probe/static-base.txt`, `probe/static-head.txt`). On base it answered 422 with lstat's text: "lstat:
     embedded null character in path". On head, with the ValueError handler gone, it answers **500**.
   - **Upstream.** Starlette fixed it after 0.41.3: commit 51057d574, "Handle null bytes in `StaticFiles` path (#3139)",
     2026-02-14, which answers 404. `sources/starlette-staticfiles-master.py:132-134` reads: `except ValueError: # Null
     bytes or other invalid characters in the path. raise HTTPException(status_code=404)`.
   - **Why reviewer 1 missed it.** Its inventory covered cmapi's code. This raise is in a mounted Starlette app.
2. **N2: F1's MemoryError and memory amplification.** See F1.
   - **Measured.** On head, `"1e2147483647"` took 935 MB of RSS (`/usr/bin/time -l`) and 2.4 s. On r1 it took 933 MB.
   - **Inferred.** The API container's limit is `memory: 512Mi` (`deploy/manifests/components/cmapi/20-api.yaml:151`), so one
     such request from any requester would OOM-kill the pod. I did not test this on a cluster.
3. **N3, outside the PR: an expiry within the last grace period of `date`.**
   - **How it is reached.** A namespace can be created to expire on 9999-12-31. It takes approver-platform's approvals
     ("Expiry beyond limits").
   - **Measured on r1** (`probe/far-expiry-r1.txt`). `GET /api/v1/expirations` then answers **500 to every caller**:
     `graceEnds = expires + timedelta(days=grace)` overflows (`plugins/expiration/router.py:140`). `:extend` with
     `days: 1` answers **500**.
   - **The fix.** A new date at create, `:set` and `:extend` must be on or before `date.max - graceDays`, which is 9999-12-24
     with 7 days. A later one is 422 validation-failed.
   - **The coordinator should file it** as its own issue (Part of #481), or fold it into #653. It is the same class: a
     client's value reaches a 500.
4. **O1's jsonb paths.** See O1.
5. **A correction to reviewer 1's research.** Reviewer 1 says "apimachinery parses the exponent as an int64". That is only
   half of it.
   - In every release branch, release-1.33 to release-1.37, `suffix.go` parses with `strconv.ParseInt(..., 10, 64)`, then
     **narrows it to int32**: `return 10, int32(parsed), DecimalExponent, true` (`sources/suffix-release-1.37.go`). An
     exponent past int32 wraps around.
   - Only master saturates it: `exponent := min(max(parsedExponent, math.MinInt32), 2*math.MaxInt32)`
     (`sources/quantity.go:394`).
   - So Kubernetes takes exponents in the int32 range. `1e9999999` is among them, so F1's premise stands.
   - Master also now keeps 29 significant digits (`maxSignificantDigits = 29`, `quantity.go:590`). No release has it:
     release-1.38 does not exist yet (404). This is an observation for `qty`'s "as the API server reads it" once 1.38 ships,
     not a defect today.

## Primary sources, each fetched 2026-11-24 (in `sources/`)

- **Python `decimal`** (docs.python.org/3/library/decimal.html, `sources/py-decimal.html`):
  - "Unlike other operations, if the length of the coefficient after the quantize operation would be greater than
    precision, then an InvalidOperation is signaled", and "An error is returned whenever the resulting exponent is greater
    than Emax or less than Etiny()".
  - The default context is `prec=28 … Emin=-999999, Emax=999999 … traps=[Overflow, DivisionByZero, InvalidOperation]`.
  - "class decimal.DecimalException: Base class for other signals and a subclass of ArithmeticError."
  - `prec` is "An integer in the range [1, MAX_PREC]", and `MAX_PREC` is 999999999999999999 on 64-bit.
  - These are the bases for catching `DecimalException`, not `ArithmeticError`, and for a bound one past Emax.
- **apimachinery `resource`**, master and release-1.33 to 1.37 (`sources/quantity*.go`, `sources/suffix*.go`): as in
  "What reviewer 1 missed", item 5.
- **psycopg 3.3.8**, installed `psycopg/types/string.py:51-52`, the same on master: `if "\x00" in obj: raise
  DataError("PostgreSQL text fields cannot contain NUL (0x00) bytes")`.
- **PostgreSQL 16, section 8.3** (`sources/pg-datatype-character.html`): "Regardless of the specific character set, the
  character with code zero (sometimes called NUL) cannot be stored."
  - **I retract the brief's wording.** "The character with the code zero cannot be stored" is not the text. The text is as
    quoted above.
- **PostgreSQL 16, section 8.14** (`sources/pg-datatype-json.html`): "The jsonb type also rejects \u0000 (because that
  cannot be represented in PostgreSQL's text type)". This is the basis for O1's jsonb paths.
- **RFC 9457 §3.1.4** (`sources/rfc9457.txt:329-330`): "The "detail" string, if present, ought to focus on helping the
  client correct the problem, rather than giving debugging information." So F1's text names the limit,
  "cmapi takes one below 1e1000000".
- **RFC 9457 §5** (`:533-536`): "Generators providing links to occurrence information are encouraged to avoid making
  implementation details such as a stack dump available through the HTTP interface …". This confirms F4.
- **RFC 8259 §7** (`sources/rfc8259.txt:429-431`): the control characters "(U+0000 through U+001F)" MUST be escaped inside
  JSON strings. So a NUL reaches a body only as `\u0000`, and only a parsed value can be checked reliably. That is why the
  check is in the body's model, not on the raw bytes.
- **uvicorn 0.32.1 with h11 0.16.0 and httptools 0.9.0**, measured (`probe/server/result.txt`): a NUL in a header and a raw
  NUL in the request target are each refused with `HTTP/1.1 400 Bad Request` by both parsers. h11's `field_vchar` is
  `[^\x00\s]` (`h11/_abnf.py:55-56`). So headers need no check of their own. In TestClient, which bypasses the parser, the
  Idempotency-Key header did reach the database.

## The final fix (`fix.diff`, against `head/`)

### F1: `core/tiers.py`

- **The bound.** `_TOO_LARGE = Decimal("1e1000000")`.
- **Where it is checked.** `qty` checks `amount >= _TOO_LARGE` **before** `quantize`, which writes one digit for each
  power of ten.
- **What it catches.** It catches `DecimalException` only: an exponent that Decimal cannot hold, or a product or a rounding
  past Emax. That covers the rounding carry `"9"*1000000 + ".9999999991"`.
- **The answer.** "quantity out of range (cmapi takes one below 1e1000000): '1e9999999'". The limit comes first, so
  `requested_qty`'s `[:300]` keeps it.
- **Should cmapi bound quantities the way Kubernetes does?** No:
  - Kubernetes' range is an int32 exponent. Under qty's nano-unit form, that is up to 2.1 billion digits.
  - The bound is one past Decimal's default Emax, exactly the set of values that head's `qty` could already hold.
  - Measured in `f1/qty_equivalence.txt`: 66 of 66 values that head parsed or refused as "not a Kubernetes quantity" give
    the identical result, and 0 changed. The other 12 failed on head with InvalidOperation, Overflow, MemoryError or the
    prec ValueError, and now give the out-of-range ValueError. Each took at most 0.8 MB, except the 1 MB Ei literal, whose
    multiplication was already on head.
- **Is it a client 422?** Yes. `requested_qty` makes it a 422 validation-failed. RFC 9110 §15.5.21: the "syntax of the
  request content is correct, but it was unable to process the contained instructions".

### F2, F3 and F4

Reviewer 1's code is unchanged. The README is updated for F1's new text.

### #653 O1: the NUL

- **Where it is refused.** At input, as 422 validation-failed, with the same text everywhere: "A value of the request
  holds the character NUL (U+0000), which cmapi does not take".
- **The path and the query: `main.py` `RefuseNulMiddleware`.** A pure ASGI middleware, about 10 lines.
  - It checks `scope["path"]`, which the server has already percent-decoded, and `unquote_to_bytes(query_string)`, before
    routing.
  - So it also covers the static mounts (N1), which app dependencies do not reach.
  - It sits inside `instrument` and CORS, so the answer carries X-Request-Id and the CORS headers.
- **The body: `core/models.py` `RequestBody(Api)`.**
  - A `model_validator(mode="before")` walks the parsed JSON, strings and keys alike, at any depth, through `holds_nul`.
  - All 8 request bodies now inherit it: `DecisionBody`, `NamespaceCreate`, `NamespacePatch`, `PruneConfirm`, `SwitchBody`,
    `ExtendBody`, `SetBody` and `PermanentBody`.
  - The refusal comes through FastAPI's `RequestValidationError`, the same shape as every other body refusal: "The request
    is not valid: body: Value error, …".
  - Response models are left alone, so data read from a cluster is never refused.
- **The guard test.** `test_every_request_body_is_a_request_body` walks the app's routes: 10 or more with a body, and each
  must be a `RequestBody`. A new body cannot skip the check.
- **Reviewer 1's `DataError` handler and its `psycopg` and `sqlalchemy` imports are removed.**

### #653 O2 and N3: `plugins/expiration/rules.py`

- **O2.** Reviewer 1's step-first rewrite is kept.
- **`_last_date(r)`** is `date.max - timedelta(days=r.grace_days)`. Each of `plan_create`, `plan_set` and `plan_extend`
  refuses a later date with 422 validation-failed, "The expiry must be on or before 9999-12-24" or "The new date must be on
  or before …".
- **`plan_extend` compares by days**, `step > (last - base).days`, so it never builds the date that would overflow.
- **Measured in `o2/equivalence-final.txt`:**
  - 43,146 inputs give the same answer as on head.
  - All 9,552 inputs that overflowed on head now give a 422, and 0 still overflow.
  - The only 126 differences are extensions to 9999-12-25 to 9999-12-31, the grace window, which are now refused on
    purpose.

### The docs

- **`docs/02`.** The validation-failed row names the three new refusals. That doc is an export of a live Claude Doc, so the
  coordinator must mirror the row there.
- **The PR's README** records F1's new form and a #653 section.
- **The doc citations.** `scripts/doc-citations.py --relocate` moved 9 citations of `main.py` in `docs/14` and `docs/15`,
  then `--check` gave 0 problems (`doc-citations-check.txt`). Like reviewer 1, I ran it through `shim/git`, because the
  export is no repository.

### The patch

- It is built from `cmapi/` and `docs/` only: 15 files, 836 lines.
- `patch -p1 -F0` applied it cleanly to a fresh copy of `head/`, and the result is identical to `r2/` (`applycheck.txt`).

## Before and after (measured, `runs/`)

| Tree | Core: the 2 new tests | Service: `test_client_input_653.py` and `test_value_error_648.py` (43) |
|---|---|---|
| head | 2 failed (`core2-head.txt`) | 36 failed, 7 passed (`svc2-head.txt`): the 7 are #648's own tests |
| head + reviewer 1 | 2 failed. The memory assertion fails with `906205380 < 50000000`, and the last-date guard is missing (`core2-r1.txt`) | 31 failed, 12 passed (`svc2-r1.txt`). See the note below |
| r2, final | 90 passed, the whole of both files (`core-r2.txt`) | **43 passed** (`svc-r2.txt`) |

A note on the 31 failures on r1: some are only the wording of reviewer 1's NUL text. The failures that decide on behaviour,
by status, are:
- a 500 for `quota-memory-error`, the static path (N1), a PATCH annotation, and `:extend` past the last date;
- a 200 for `?a%00=1`, a NUL in a query key, which reviewer 1's handler never sees, because nothing stores the key;
- a 404 for `/namespaces/a%00b`;
- a 200 for the dry runs.

Its decisions are also in the probe that records each entry point (`probe/r1.json` against `probe/head.json`). On r1:
- **Still 500:** an annotation value at create, a PATCH annotation, a rejection's comment and the pause reason.
- **Now 422:** the query, the path, a justification, an approve comment, `:extend`'s justification and the header.

## Regression runs on `r2/` (measured)

| Suites | Result | File |
|---|---|---|
| core: `test_tiers`, `test_lifecycle_expiration`, `test_limitrange_split`, `test_review_255` (it reads docs/02), `test_metadata_pattern_subset_332`, `test_render_listquery_config`, `test_policygen` | **240 passed, 28 skipped** | `runs/regress-core.txt` |
| service: `test_flow`, `test_custom_tier_change`, `test_api_docs`, `test_api_contract`, `test_api_samples`, `test_api_standard`, `test_problem_type_docs`, `test_review_c_authz`, `test_cors`, `test_head_605`, `test_review_479_expiry`, `test_expirations`, `test_expiry_review_322`, `test_dry_run_once_607`, `test_dry_run_refused_606`, `test_protected_366`, `test_plugins_switch`, `test_namespace_contract_479`, `test_storage_limits_switch`, `test_review_d_delivery`, `test_review_255_apply`, `test_value_error_648` and `test_client_input_653` | **596 passed** | `runs/regress-service.txt` |

What this shows:
- **The contract is unchanged.** `test_api_contract` passed, so `RequestBody` leaves the OpenAPI document as it was.
- **What was not run.** `test_doc_citations.py` needs `git ls-files` and does not run on the export, as reviewer 1 found;
  `doc-citations.py --check` through the shim stands in for it. The whole service suite was not run.

## Mutants of the final fix (`mutants/`)

Each mutant is a fresh copy of `r2/` with one change, made by `mutants/mutate.py` and run by `mutants/run-mutants.sh`.
Each log is `mutants/<id>.txt`.

| Mutant | What it breaks | Result |
|---|---|---|
| m01 | `qty` without the bound | killed: core memory test, 1 failed |
| m02 | `qty` catches no `DecimalException` | **Survived the service F1 test** (5 passed): every service value reaches the bound first. **Killed by the core test**, 1 failed, with `decimal.Overflow` on the `"9"*999982 + "Ei"` value (`m02-no-decimal-catch-core.txt`) |
| m03 | `_off_step` at 28 digits | killed, 1 failed |
| m04 | No unwrap of the ExceptionGroup | killed, 1 failed |
| m05 | No `RefuseNulMiddleware` | killed, 7 failed: the query, the path and the static file |
| m06 | The middleware checks the path only | killed, 3 failed: the 3 query cases |
| m07 | `holds_nul` skips dict keys | killed, 4 failed: annotation-key and limit-key, submit and dry run |
| m08 | Top-level strings only | killed, 10 failed |
| m09 | `SwitchBody` is not a `RequestBody` | killed, 2 failed: the guard test and the pause reason |
| m10 | No last-date guard in `plan_extend` | killed, 2 failed |
| m11 | No guard in `plan_create` | killed, 1 failed |
| m12 | No guard in `plan_set` | killed, 1 failed (core) |
| m13 | `_last_date` without the grace period | killed, 1 failed |
| m14 | The date is moved before the checks (head's order) | killed, 3 failed |

All 14 are killed. m02 is killed only by the core test, so CI must run `tests/core` too.

## Observations, not fixed here

- **The expiration config is not validated.** `expiration.yaml`'s `maxExtensionDays` and `graceDays` are not checked at
  load (`rules.py:84-93`). A negative `graceDays` would make `_last_date` overflow. This is an operator's value, not a
  client's.
- **JWT claims are not covered.** A NUL in a JWT claim, which the IdP signs, still reaches the database where a requester
  record is written. This was not tested, and it is outside the client-input boundary.
- **`"9"*999982 + "Ei"`**, a 1 MB body, costs 1.3 s in head's multiplication before it is refused. That cost is
  pre-existing and bounded by the body size. cmapi has no body-size limit of its own (inferred from reading; not measured).
