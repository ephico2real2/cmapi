# #648: a ValueError that escapes a route is internal-error, not the caller's validation-failed

Part of #481. Implementer: Opus 5.5 at high, from `main` `a2a55f3`. Every file of this change is the implementer's.

## What was wrong

`cmapi/src/cmapi/main.py` had a handler for every `ValueError`, `value_error_handler` (l.227-229 at `a2a55f3`). It answered
`422 validation-failed` with `str(exc)[:300]` as the detail. `UnicodeDecodeError`, `json.JSONDecodeError` and pydantic's
`ValidationError` are ValueErrors, so a fault of the service blamed the caller and sent it an implementation message.

## Research (each source read on 2026-11-24)

- **RFC 9457, section 3.1.4** (<https://www.rfc-editor.org/rfc/rfc9457.txt>): "The "detail" string, if present, ought to
  focus on helping the client correct the problem, rather than giving debugging information."
- **RFC 9457, section 5**: "Risks include leaking information that can be exploited to compromise the system, access to the
  system, or the privacy of users of the system." It adds that generators "are encouraged to avoid making implementation
  details such as a stack dump available through the HTTP interface, since this can expose sensitive details of the server
  implementation, its data, and so on."
- **RFC 9110, section 15.5.21** (<https://www.rfc-editor.org/rfc/rfc9110.txt>): "The 422 (Unprocessable Content) status
  code indicates that the server understands the content type of the request content ..., and the syntax of the request
  content is correct, but it was unable to process the contained instructions."
- **RFC 9110, section 15.6.1**: "The 500 (Internal Server Error) status code indicates that the server encountered an
  unexpected condition that prevented it from fulfilling the request."
- **pydantic v2, "Validators", section "Raising validation errors"**
  (<https://pydantic.dev/docs/validation/latest/concepts/validators/>, to which docs.pydantic.dev/latest/concepts/validators/
  redirects with a 301): "To raise a validation error, three types of exceptions can be used: ValueError : this is the most
  common exception raised inside validators." In the installed pydantic_core 2.50.2,
  `ValidationError.__mro__` is `(ValidationError, ValueError, Exception, BaseException, object)`.
- **FastAPI 0.115.6** (installed sources): `fastapi/_compat.py:127-135`, `ModelField.validate`, catches the
  `ValidationError` of `validate_python` and returns its errors. `fastapi/routing.py:342-346` raises
  `RequestValidationError(_normalize_errors(errors), body=body)` from them. `fastapi/exceptions.py:149,157` defines
  `ValidationException(Exception)` and `RequestValidationError(ValidationException)`, which is not a ValueError. So a request
  model's validator never reached `value_error_handler`. Only a ValueError raised in a route, a dependency or the code they
  call did.
- **Starlette 0.41.3** (installed): `starlette/_exception_handler.py:16-20` looks the handler up along `type(exc).__mro__`,
  and `:49-50` re-raises when none matches. Without a ValueError handler, a ValueError reaches cmapi's
  `UnhandledToProblemMiddleware`, which logs `unhandled` and answers 500 `internal-error` with no text of the exception
  (#216). `TierError(ValueError)` keeps its own handler, which comes first in its MRO.

## Inventory: each ValueError that could escape a route at `a2a55f3`

**How the inventory was made.** The implementer ran a literal search for `raise ValueError`, `ValueError(` and
`except ValueError`, and read each raise site and its callers. A static read can miss a path, so it then measured as well.
A probe in `value_error_handler` logged every ValueError that reached it while the 45 service modules that mention 422 ran:
1151 passed (`probe-run.txt`). Exactly two distinct ValueErrors reached it (`probe-valueerrors.jsonl`): rows 1 and 2.

| # | Raise site (`a2a55f3`) | Route and caller | Meaning | Answered before | Now | Evidence |
|---|---|---|---|---|---|---|
| 1 | `core/identity/claims.py:21` `label_value_of` | POST namespaces, `core/pipeline.py:259` (create only) | The request: the requester's username, or onBehalfOf's, cannot be the label `cmapi.net/requested-by-user` | 422 validation-failed, "username 'John Doe@corp' cannot be a label value" | The same, byte for byte: an explicit `Problem` at the call | Measured (probe; `test_review_d_delivery.py`) |
| 2 | `core/tiers.py:56` `qty`, on a value that the body sends: `_out_of_bounds` (l.500, 502), `quota_for` (l.524), `limits_for` (l.557, 564) | POST and PATCH namespaces with tier custom, `core/pipeline.py:336-337` | The request: a quota or limit value is not a Kubernetes quantity | 422 validation-failed, "not a Kubernetes quantity: 'lots'" | The same, byte for byte: `tiers.requested_qty` raises the `Problem` | Measured (probe; `test_custom_tier_change.py`) |
| 3 | `.decode()` of a name or a manifest: `core/git/workspace.py:301, 318, 332`; `core/git/github.py:100`; `core/git/gitea.py:79` | Every namespace write and the single read, through `core/pipeline.py:205` (`_read_folder`) and `:214` (`removable_folder`) | The service: Git holds bytes that it cannot read | 422 validation-failed, "'utf-8' codec can't decode byte 0xe9 ..." | 500 internal-error; PR #647 makes a folder with such a name 409 folder-not-utf8 | Measured (#626's test-before; the new test) |
| 4 | pydantic `ValidationError` of a response model: `plugins/namespaces/router.py:278, 332, 361, 384` (`PlanView.model_validate`); `plugins/capacity/router.py:219` (`CapacityPage.model_validate`) | Each dry run of a namespace write; GET capacity | The service: its own answer breaks its model | 422 validation-failed, "6 validation errors for PlanView ..." | 500 internal-error | Measured (the new test injects it) |
| 5 | `date.fromisoformat` of `cmapi.net/expires-at` from Git, `core/pipeline.py:299, 311` | PATCH and the three expiry writes | The service: a hand-edited annotation in Git | 422 validation-failed, "Invalid isoformat string: ..." | 500 internal-error | Inferred from the code |
| 6 | `date.fromisoformat` of the cluster's `creationTimestamp`, `core/pipeline.py:492` | DELETE namespace (`plan_delete`) | The service: the API server's data | 422 validation-failed | 500 internal-error | Inferred |
| 7 | `qty` on a value of Git, the cluster or the catalog: `core/pipeline.py:377-378, 393, 397` (the old quota in Git); `core/tiers.py` `_same` when the text is Git's own; `plugins/quotas/__init__.py:65` (a quota's `status`); `plugins/capacity/router.py:91` (capacity.yaml) | Namespace writes; GET quotas; GET capacity | The service: data it holds or reads | 422 validation-failed, "not a Kubernetes quantity: ..." | 500 internal-error | Inferred |
| 8 | Any other ValueError of a route or a dependency | Any | The service: a bug | 422 validation-failed with its text | 500 internal-error | Measured (the new test injects one from a dependency) |

**Caught before a route sees them**, so not in the table:
- `core/listquery.py:111` becomes 400 invalid-cursor.
- `core/auth.py:65` is caught in `Jwks._refresh`.
- `plugins/namespaces/router.py:403` becomes a validation-failed Problem.
- `plugins/expiration/router.py:72, 81`, `core/etag.py:134` and `core/pipeline.py:579` (`created_day`).
- `BadResponse` at `core/pipeline.py:231`, `core/registry.py:504-525`, `core/clients/nodes.py:157` and `core/clients/policyreports.py:213`.

**Raised only at start-up, in a job or in a tool, never in a route:**
- The configuration loaders: `approvals.py:110`, `authz.py:59-138`, `capacity.py:74`, `metadata.py:590-665`, `plugins.py:51, 92`, `registry.py:219`, `errors.py:23`, `cors.py`, `giturl.py`, `config.py` and `plugins/expiration/rules.py:82-100`.
- `git/__init__.py:43`, `db/__init__.py:135, 140` and `policygen.py`.
- The jobs: `cluster_tokens.py:69-94` (token_renew), and `git/workspace.py:391, 400` and `git/transport.py:108` (the branch writes).
- `policybundle.py:66`.
- `metadata.py:1424` (`json_schema`, which builds the document).

## Options and choice

| Option | For | Against |
|---|---|---|
| A. Keep a ValueError handler, but answer 500 | One line | Rows 1 and 2, the deliberate refusals, would become 500 |
| B. Keep the 422 handler, and catch each internal ValueError at its source | No change for the deliberate rows | Rows 3 to 8 are open-ended. Each new bug would blame the caller until someone found it |
| C. Move the request-model checks into pydantic (a quantity pattern on `quota` and `limitRange`) | The contract documents the rule | Changes the body of row 2 (RequestValidationError's detail and `errors[]`) and the contract. Row 1 depends on the token, not the body |
| **D (chosen)**. Make each deliberate refusal an explicit `Problem` where it is decided, and remove the ValueError handler | A refusal is a decision made in one place, and anything else is a fault. This follows RFC 9457 §3.1.4 and §5 and RFC 9110 §15.6.1. Rows 1 and 2 keep their bytes | `qty` serves request values and stored values alike, so the conversion has to be at the request-value call sites |

**What the change does:**
- **`core/tiers.py`.** `requested_qty` raises `Problem.unprocessable("validation-failed", str(exc)[:300])`, the old handler's
  exact body.
- **`_kept`.** `_kept(value, approved)` replaces the four comparisons of a request value with Git's (`_same`). It parses the
  request's value with `requested_qty` when its text differs from Git's, so a bad value is refused at the same key and in
  the same order as before.
- **`core/pipeline.py:259`.** Wraps `label_value_of` in the same Problem.
- **`main.py`.** Removes `value_error_handler`. The `unhandled` log line also gets `error_type`, the exception's class.

**Behaviour that changes, and why.**
- Rows 3 to 8 now answer 500 internal-error with no exception text. Their text and traceback go to the log line `unhandled`.
- A quota value in Git that is not a quantity used to answer 422 "not a Kubernetes quantity: <Git's value>". That blamed the
  caller for Git's data, and it still does if the caller resends Git's text. It now answers 500 internal-error.
- No deliberate 422 changes.
- `validation-failed` is not in `CMAPI_REFUSALS` or in `rejections.RECORDED`, so no metric and no stored rejection changes.

## Tests

`cmapi/tests/service/test_value_error_648.py`, run from `cmapi/` with
`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_603 PYTHONPATH=src:tests/service`:

- **`test-before.txt`**, with the fix stashed: 3 failed and 4 passed.
  - The 3 failures are the internal cases. Each answered 422 with the exception text: the codec error, the dependency's
    message, and pydantic's "6 validation errors for PlanView".
  - The 4 passes pin today's deliberate 422 bodies, whole.
- **`test-after.txt`**, with the fix: 7 passed.
- **`test-mutant-no-explicit-refusals.txt`**: the handler is removed but the two explicit refusals are not added. The 4
  deliberate tests fail with 500, so they guard the explicit Problems.
- **`suites-after.txt`**:
  - Every service module that asserts `validation-failed`, plus `test_cors.py` and `test_head_605.py` (the `unhandled` log
    line), `test_review_d_delivery.py` and `test_api_samples.py`: 519 passed.
  - `tests/core/test_tiers.py`, `test_limitrange_split.py` and `test_metadata_pattern_subset_332.py`: 168 passed and 2
    skipped.
- **`contract-checks.txt`**:
  - `openapi.json`, `samples.json`, `docs/04` and the portal types are unchanged.
  - `contract/gate.sh` reports "No changes detected".
  - `changelog.py --check` and `scripts/api-examples-doc.py --check` exit 0.
- **`scripts/doc-citations.py`.** `--check` found 12 citations in docs/14 and docs/15 that only moved, and `--relocate` moved
  them. After that it reports 0 problems.
- **`doc-suites-after.txt`**: the suites that read docs/02, docs/14 or docs/15, `test_doc_citations.py` among them: 161
  passed, and `tests/core/test_review_255.py` 7 passed.

All runs are on the Mac, against PostgreSQL 16 on `127.0.0.1:55432`. No cluster was used.

## Not tested

- Rows 5, 6 and 7 are inferred from the code. No test injects a bad date or a bad quantity into Git or the cluster: the
  dependency-raised and Git-raised cases prove the path.
- The whole service suite was not run, by the brief.
- Nothing ran on kind or CRC.
