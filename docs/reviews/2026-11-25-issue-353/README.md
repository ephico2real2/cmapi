# #353: a string of a request body that holds a surrogate code point is refused at the edge

The implementer's record: Opus 5.5 at `high`, 2026-11-25, on `fix/353-lone-surrogate` from `c2b89f5`. The reviews go beside
it when they are done. This fix is at the parser edge, so it gets two reviewers.

## What is wrong

A JSON string may carry a surrogate code point (U+D800 to U+DFFF) that is not half of a pair: `"\ud800"`, a reversed pair
`"\ude00\ud83d"`, or the bytes ED A0 80. None of these is a Unicode character. FastAPI 0.162.2 reads a body with Starlette's
`Request.json()`, which is `json.loads`, and `json.loads` keeps such a code point in the Python string. pydantic's
`model_validate` on that object accepts it.

**Measured, 2026-11-25, service suite on this Mac (PostgreSQL 16, `cmapi_impl_353`), on main `c2b89f5`**
(`outputs/before.txt`):

| Request | Answer on main |
|---|---|
| Create, team annotation `note: "a\ud800"` (submit, dry run, and the bytes ED A0 80) | 500 internal-error, UnicodeEncodeError at `core/metadata.py:1279` (`len(v.encode())`) |
| PATCH, team annotation `note: "a\ud800"` | 500 internal-error, the same line |
| Create, `justification: "why\ud800"` | 500 internal-error, UnicodeEncodeError at `core/db/repo.py:171` (the insert) |
| Create, annotation key `"no\ud800te"` | 500 internal-error, UnicodeEncodeError in `main.py:249` `problem_response`: the policy-violation names the key, and the UTF-8 answer cannot carry it |
| Approve, `comment: "c\ud800"` | 500 internal-error, UnicodeEncodeError at `core/db/repo.py:246` |
| Create, label value `team2: "a\ud800"` | 422 policy-violation `invalid_value` (the label value's pattern) |
| Create, unknown member `"x\ud800": 1` | 422 validation-failed `string_unicode`, field `body` |
| Create, limit `cpu: "1\udfff"` | 422 with no `errors` member (the quantity's rule) |

**Retracted.** The issue says the team-annotation create "answers 202 on main". The measurement refutes that on `c2b89f5`: it
answers 500. At #351's head the UnicodeEncodeError (a ValueError) reached the ValueError handler and became a 422; #648 removed
that handler, so it is now internal-error. The issue's first comment says the same line raises; it is now a 500, not a 422.

**Retracted in part.** The issue infers "drift": Kubernetes would hold U+FFFD where Git holds the surrogate. Measured with Go
1.27.4 (`probes/k8s_decoders.go`, `outputs/k8s-decoders.txt`):

```
encoding/json: "a�"
sigs.k8s.io/json: "a�"
sigs.k8s.io/yaml: "" err=error converting YAML to JSON: yaml: found invalid Unicode character escape code
```

So it depends on the path. cmapi's apply mode reads the Git file with PyYAML and sends JSON (`core/clients/kube.py:278`,
`json.dumps` escapes it as `\ud800`), and the API server's decoder, sigs.k8s.io/json, stores U+FFFD: drift, as inferred. A
GitOps tool that reads the file with sigs.k8s.io/yaml, as kubectl and Argo CD do, cannot read the file at all, so the folder
does not sync. With the shipped `metadata-keys.yaml` no surrogate reached Git on `c2b89f5`: every case above failed before the
write. A declared governed key with no pattern, format or enum would have let it through (the issue's first comment); none
ships.

## Sources

Each fetched 2026-11-25.

- **RFC 8259, section 8.2** (<https://www.rfc-editor.org/rfc/rfc8259.txt>): "the ABNF in this specification allows member
  names and string values to contain bit sequences that cannot encode Unicode characters; for example, "\uDEAD" (a single
  unpaired UTF-16 surrogate)." "The behavior of software that receives JSON texts containing such values is unpredictable".
  Section 8.1: "JSON text exchanged between systems that are not part of a closed ecosystem MUST be encoded using UTF-8".
- **RFC 7493 (I-JSON), section 2.1** (<https://www.rfc-editor.org/rfc/rfc7493.html>): "Object member names, and string values
  in arrays and object members, MUST NOT include code points that identify Surrogates or Noncharacters as defined by
  [UNICODE]. This applies both to characters encoded directly in UTF-8 and to those which are escaped; thus, "\uDEAD" is
  invalid because it is an unpaired surrogate, while "\uD800\uDEAD" would be legal." Section 3: this "allows receivers to
  reject or otherwise disregard messages that do not conform".
- **Go `encoding/json`** (<https://raw.githubusercontent.com/golang/go/master/src/encoding/json/decode.go>), the doc of
  `Unmarshal`: "When unmarshaling quoted strings, invalid UTF-8 or invalid UTF-16 surrogate pairs are not treated as an error.
  Instead, they are replaced by the Unicode replacement character U+FFFD." **sigs.k8s.io/json**, the fork the API server
  decodes with (`internal/golang/encoding/json/decode.go` at `11ed52e`, lines 92-95, and `unquoteBytes` lines 1391-1400:
  "Invalid surrogate; fall back to replacement rune"); `k8s.io/apimachinery` `pkg/runtime/serializer/json/json.go` line 273
  calls `kjson.UnmarshalCaseSensitivePreserveInts`.
- **FastAPI 0.162.2** (installed, `fastapi/routing.py:458-475`): a body whose content type is JSON is `await request.json()`;
  **Starlette 1.10.0** `requests.py:264-268`: `self._json = json.loads(body)`; **CPython 3.12.14** `json/__init__.py:341`:
  bytes are decoded with `s.decode(detect_encoding(s), 'surrogatepass')`, so the bytes ED A0 80 become U+D800 too.
- **pydantic 2.14.2 / pydantic-core 2.50.2** (measured): `M.model_validate(json.loads('{"annotations": {"a": "x\\ud800"}}'))`
  succeeds; `M.model_validate_json(...)` answers `json_invalid` "unexpected end of hex escape". FastAPI calls the first.
  pydantic's validators page (<https://pydantic.dev/docs/validation/latest/concepts/validators/>): "To raise a validation
  error, three types of exceptions can be used": ValueError, AssertionError and PydanticCustomError, "a bit more verbose, but
  provides extra flexibility". A model validator in `before` mode receives "the raw input".
- **Unicode Corrigendum #9** (<https://www.unicode.org/versions/corrigendum9.html>): noncharacters "are not illegal in
  interchange nor do they cause ill-formed Unicode text".
- **uvicorn 0.32.1** (installed): `h11_impl.py:198` `path = unquote(raw_path.decode("ascii"))`, `httptools_impl.py:257`
  `urllib.parse.unquote(path)`; Starlette `datastructures.py:156` `parse_qsl`. Both use `errors="replace"`: measured,
  `unquote('%ED%A0%80')` is `'���'`.

## The choice

`core/models.py` `RequestBody`, the base of every request body, already refuses U+0000 in a before-mode model validator
(#653), and `test_every_request_body_is_a_request_body` keeps every body model a RequestBody. The same validator now walks the
parsed body and refuses any string or key that holds a code point from U+D800 to U+DFFF. `json.loads` joins an escaped pair
into one character, so any such code point left is not a character, and a valid pair (`\ud83d\ude00`, U+1F600) is taken.
The walk is a loop over a stack, not recursion: `json.loads` parses a body nested about 10000 deep (CPython's C recursion
limit), and a recursive walk raised RecursionError, which answered 500, from about depth 600.

The answer is 422 validation-failed, the problem every refusal of a body is, with one error for each place, the first 20
(`MAX_PLACES`) in document order, so that the answer stays small whatever the body holds:
`{"field": "body.annotations.note", "message": "holds U+D800, a surrogate code point, which is not a Unicode character",
"code": "string_surrogate"}`. A key's place ends in `[key]`, as pydantic names a key's error, and the key is shown with the
surrogate escaped (`body.annotations.no\ud800te.[key]`), since the UTF-8 answer cannot carry it. The validator raises one
PydanticCustomError whose context holds the places; `main.py` `request_validation_handler` names each place below the body.

A path or a query cannot carry one: the server decodes both with U+FFFD for bytes that are not UTF-8 (sources above), and the
last test of `test_lone_surrogate_353.py` proves the query and the path. A header is Latin-1. So the edge is the body.

Not refused: noncharacters (U+FFFE, U+FDD0 and the like). I-JSON refuses them, but cmapi does not declare I-JSON, they are
well-formed Unicode (Corrigendum #9), UTF-8 and PostgreSQL carry them, and Go decodes them unchanged. Refusing them would change
behaviour beyond this defect.

Rejected:

- **A check in `MetadataKeys._syntax` for each key and value**, the issue's second option, or `invalid_value` for metadata as the
  issue's first comment proposed. It covers labels and annotations only; the justification and a decision's comment reached
  PostgreSQL and answered 500. A surrogate is not a metadata rule but text that is not text, so it belongs where the body is read.
- **A custom JSON decoder** (a `Request.json` on `pydantic_core.from_json` through a custom APIRoute). It refuses at the parse,
  but FastAPI turns that error into its 400 "There was an error parsing the body" (`routing.py:495-499`), which names no field,
  and the decoder differs from `json.loads` in other ways (large integers, NaN, duplicate members): a behaviour change beyond
  this defect.
- **An ASGI middleware that scans the raw bytes.** It must parse JSON to tell `\\ud800` from `\ud800` and a pair from a lone
  half, a second parser in front of the first, and it buffers each body.
- **A constrained `str` type on each field.** pydantic would name the field itself, but every field of every model, the
  `Any` ones included, must use it, and a key at the top of the body (an unknown member) is never a field. The walk is complete
  by construction.
- **Raising pydantic's ValidationError with a location for each place inside the validator.** It works today, but it is not
  one of the three exceptions pydantic documents for a validator.

## Proof

`cmapi/tests/service/test_lone_surrogate_353.py`, 19 tests, each body sent as raw JSON bytes: a create (submit and dry run) and a
PATCH with the team annotation `note: "a\ud800"`, the same value as the bytes ED A0 80, a label value, the justification, an
annotation key, an unknown member, a nested limit, two places named in order, a decision's comment, a valid pair still taken,
and the query and the path (a guard, which passes before the fix too). The review added six: keys at depth, a pair sent as
CESU-8 bytes (both pass before the review's fix too), a body nested 600, 5000 and 8000 deep (plain, NUL and surrogate leaves),
and a refusal of 1,000 places that names the first 20.

- The review's fixes (reviewer 1 and reviewer 2, `fix.diff` of the review): with the 19 tests on the PR's code, 4 failed (the
  three depths answered 500, and the 1,000 places were all named) and 15 passed; on the fixed code, the new file,
  `test_client_input_653.py`, `test_framework_problems_646.py`, `test_value_error_648.py` and `test_api_docs.py` passed 103 of
  103. The fixed walk equals the PR's walk on 60,000 random bodies (the first 20 places, and every place with the cap lifted).

- Before, `cmapi/src` stashed (`outputs/before.txt`): 11 failed, 2 passed (the valid pair and the query-and-path guard).
- After (`outputs/after.txt`): 13 passed.
- The related suites, 21 files (the #653, #646 and #648 problem suites, the contract, standard and samples suites, the
  metadata API suites, the namespace create and PATCH suites, `test_flow.py`): 470 passed (`outputs/related-suites.txt`).
  Two edits that change no behaviour came after that run (the pattern as a raw string, and a walrus in the walker); on the
  final code the new file passed 13 of 13 (`outputs/after.txt`), and `test_client_input_653.py`, `test_framework_problems_646.py`,
  `test_value_error_648.py` and `test_api_docs.py` passed 84 of 84.
- The contract: `contract/openapi.json` is unchanged (`test_the_committed_contract_is_the_document_this_code_serves` passed),
  so the oasdiff gate, the changelog check and the examples-doc check have nothing to compare.

Not tested: a CRC or kind run, and the Go decoders reading a manifest that cmapi wrote (the probe reads the bytes PyYAML wrote).

Filed: #679 (Low, Backlog), a surrogate escape in a value Git already holds, read by PyYAML, would make a PATCH of that
namespace answer 500 at the same `metadata.py:1279` (inferred, not reproduced).

## Review and the coordinator's run (2026-11-25)

- **Reviewers.** Two reviewers, because the fix sits at the parser edge. Reviewer 1 and reviewer 2 are both Opus 5.5 high, standing in for Codex, which is at its limit. Their reports are in `review/`.
- **Reviewer 1:**
  - **H1 (High):** the walk was O(size × depth), and the answer had no limit on errors. A 1 MB body got a 93 MB answer after 15 s. Fixed: one loop over a stack, and the first 20 places.
  - **M1 (Medium, older than this PR):** a body nested about 600 deep gave 500 through RecursionError. Fixed by the same loop.
  - **L1:** the RFC 7493 quote is fixed.
  - **L2** (no limit on body size) is #683, security, fixed next.
  - **L3** goes to #684 (Backlog).
- **Reviewer 2** accepted H1, M1 and L1, with amendments:
  - a test at depth 8000 and a NUL leaf;
  - corrected docstrings, from CPython 3.12.14's recursion limits;
  - a second misquoted character in the README;
  - the test count;
  - tests for a raw CESU-8 pair and for surrogate keys at depth.

  Its Backlog items R2-B1 to R2-B3 go to #684.
- **The coordinator** applied reviewer 2's final patch with `patch -p1 -F0`, and relocated 4 docs/14 citations, reading each one. Full service suite in database `cmapi_coord_681`, 16:22:51Z to 17:04:24Z: **2956 passed**, none failed (`coord-suite.txt`).
