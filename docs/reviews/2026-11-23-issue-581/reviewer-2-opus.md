# Reviewer 2 (Opus 5.5, high) on PR #589, head 0ce8151

Scope: reviewer 1's (Codex gpt-6.2-astra) findings checked against `head2/` (0ce8151, main with #588 merged), the tests
Codex could not run actually run, and the gaps Codex left. All work is in the export: the fixed copy is `review-589/r2/`,
the outputs are in `review-589/r2-outputs/`, and the mutants are in `review-589/r2-mut/`. No git repository was touched,
nothing was pushed, and nothing was written to CRC, LDAP or Keycloak. The service tests ran on my own database,
`cmapi_r2_589` on `127.0.0.1:55432`, one session at a time. Every result below comes from that local PostgreSQL 16 and
the export. None comes from a cluster.

**Deliverables**

- `r2-outputs/fix.diff` is the full patch against 0ce8151, 12 files. `patch -p1` from the repo root applies it cleanly.
  I checked by applying it to a fresh copy of `head2/` and comparing every file with `r2/` byte for byte.
- `r2-outputs/LIVE-DOC-EDITS.md` is the updated live-doc text for docs/01 and docs/02, with its proposed test.

## Rulings

### 1. #586: the helper is too broad. Accepted. Codex's fix narrowed, and the test now reads the route's own declaration.

**What the code did.** `core/docs.py:820-837` at 0ce8151 had two defects:

- It set `required` on every `If-Match` header of every operation.
- It popped the whole `anyOf`, which threw away the string branch's rules.

**What the tests showed.**

| Mutant | What it changes | Result |
|---|---|---|
| m0 | 0ce8151 with `max_length=128` on the real `Header` (`routers/__init__.py:80`) | The old exception (`test_api_standard.py:392-397`) passed all 3 configurations, and the five-writes test passed too. The document had lost `maxLength`. |
| m1 | My tests, the same maxLength, and 0ce8151's helper | 4 failed: `test_the_document_keeps_what_each_route_declares` in all 3 configurations, with "PATCH …: If-Match is not the route's string, required in the document only: {'type': 'string'}", and the new helper test |
| m2 | My tests, the same maxLength, and the fixed helper | 5 passed. The constraint is published. |
| m9 | The fixed helper with PATCH dropped from the operation list | `test_the_document_marks_if_match_required_on_the_five_writes` failed |

So a helper that misses an operation is caught. My test file hardcodes the five paths. It does not import the constant.

**Changes to Codex's `schema_fix.txt`.**

- **Select by `operationId`, not by path.** `core/docs.py` already does this: `PATCH_OPERATION =
  "namespaces_update_namespace"` at `:744`. The five ids come from the committed contract.
- **Drop the `allOf` branch.** Codex added it for a key conflict between the string branch and the outer schema. The
  outer schema holds only `title`, `description` and `examples`, so that conflict cannot happen, and the branch adds
  complexity no test can reach.
- **Fail fast.** A declaration that is not `str | None` now raises `RuntimeError` naming the operation. That matches
  `check_documented` ("Refuse to start").
- **Match the name exactly** (`If-Match`). That is how FastAPI publishes the alias.

The output is byte-identical to 0ce8151's document apart from description text. I diffed the regenerated
`openapi.json`, and oasdiff gives the same ten diagnostics.

`r2/cmapi/src/cmapi/core/docs.py`, replacing `:820-837`:

```python
# The five writes whose route requires If-Match (plugins/namespaces/router.py): the change, the delete and the three
# expiry writes. A create takes none.
IF_MATCH_OPERATIONS = frozenset({"namespaces_update_namespace", "namespaces_delete_namespace", "namespaces_extend",
                                 "namespaces_set_expiry", "namespaces_make_permanent"})


def _document_if_match_required(spec: dict[str, Any]) -> None:
    """If-Match is required on the five writes of IF_MATCH_OPERATIONS (#586). The runtime parameter keeps
    `Header(default=None)` (routers/__init__.py, if_match), so that a namespace missing from Git answers 404 before 428, as
    RFC 9110 section 13.2.1 orders a precondition after the resource; FastAPI's own check of a required header would answer
    422 before the route runs. So only the document says what the route enforces, and a generated client cannot leave it
    out. Another operation's If-Match keeps what its route declares.

    OpenAPI 3.1.0, Parameter Object: `required` "Determines whether this parameter is mandatory" (default false). A
    header that is sent has a string value, never null, so the schema drops the null of `str | None` and keeps the string
    with each of its rules (a maxLength or a pattern, when the route declares one)."""
    for ops in spec["paths"].values():
        for op in ops.values():
            if not isinstance(op, dict) or op.get("operationId") not in IF_MATCH_OPERATIONS:
                continue
            for param in op.get("parameters") or ():
                if param.get("in") != "header" or param.get("name") != "If-Match":
                    continue
                schema = param["schema"]
                variants = schema.pop("anyOf", None)
                if variants is not None:
                    strings = [v for v in variants if v != {"type": "null"}]
                    if len(variants) != 2 or len(strings) != 1:
                        raise RuntimeError(f"{op['operationId']}: If-Match is not declared as `str | None`: {variants}")
                    schema.update(strings[0])
                if schema.get("type") != "string":
                    raise RuntimeError(f"{op['operationId']}: If-Match is not a string: {schema}")
                param["required"] = True
```

`r2/cmapi/tests/service/test_api_standard.py:392-400`. Codex's `standard_fix.txt`, made smaller. The import gains
`IF_MATCH_OPERATIONS`. The exception covers only the five operations. It requires the route to stay optional, and it
compares the whole published schema, words aside, with the route's string branch, so no rule can be lost or added:

```python
            rules = {k: v for k, v in p["schema"].items() if k not in ("examples", "description", "title")}
            if (p["name"], p["in"]) == ("If-Match", "header") and op.get("operationId") in IF_MATCH_OPERATIONS:
                # The one parameter that the document tightens (#586): the route keeps it optional so that 404 comes before
                # 428, and the document marks it required and drops only the null of `str | None`. Every rule of the string
                # stays, and nothing is added (_document_if_match_required).
                string = next(v for v in rules.pop("anyOf") if v != {"type": "null"})
                shown = {k: v for k, v in (mine.get("schema") or {}).items() if k not in ("examples", "description", "title")}
                if p.get("required") or mine.get("required") is not True or shown != {**rules, **string}:
                    out.append(f"{label}: If-Match is not the route's string, required in the document only: {shown}")
                continue
```

The scope test, Codex's `verify_schema.py` as a pytest, is `test_the_document_tightens_only_the_five_writes_and_keeps_the_string_rules`.
Its full code is in the diff and in the test section below. It needs no database. It fails with 0ce8151's helper (m1)
and passes with the fix.

### 2. #581: the premise test cannot tell the two transports apart. Accepted, with Codex's `test_bytes.py`.

**Before.** `test_if_match_surface_581.py:63-69` passed in m4, where `_raw_patch` sends through `TestClient`. That is the
defect: the test cannot see the UTF-8 re-encoding.

**After.** The replacement echoes the octets the app received. It needs no `world`.

- With TestClient (m3) it fails: `assert b'\xc2\xa0*\xc2\xa0' == b'\xa0*\xa0'`.
- With the PR's `ASGITransport` it passes.

I also checked the comment's uvicorn claim on the installed h11 and httptools (uvicorn 0.32.1, Starlette 0.41.3, httpx
0.28.1, FastAPI 0.115.6):

| Input | h11 | httptools |
|---|---|---|
| `\xa0*\xa0` | unchanged | unchanged |
| `\x85*\x85` | unchanged | unchanged |
| `" \t*\t "` | `*` | `*\t ` |

So "as uvicorn passes the octets it read" was too broad. The comment at `:49-55` now says what was measured. Code, in
`r2/cmapi/tests/service/test_if_match_surface_581.py`:

```python
def test_the_raw_transport_delivers_the_octets_unchanged():
    """The premise of the HTTP tests below: _raw_patch hands the app the octets it was given, not the UTF-8 form that
    TestClient would send (0xC2 0xA0 for 0xA0). An app that echoes the If-Match octets it received tells the two apart,
    where a status cannot: the value names no tag either way, so both forms answer the same 412."""
    from starlette.responses import Response
    from starlette.testclient import TestClient

    async def echo(scope, receive, send):
        await Response(dict(scope["headers"])[b"if-match"])(scope, receive, send)

    for value in OBS_TEXT_STAR:
        assert _raw_patch(TestClient(echo), "/", {"If-Match": value}, {}).content == value
```

### 3. #587 wording. Accepted. All three overpromises measured, and the text corrected everywhere this PR touched it.

**Measured on 0ce8151** with a throwaway probe (`h2run/cmapi/tests/service/test_r2_probe_589.py`, not for commit;
output in `r2-outputs/probe-head2.txt`).

- **Delegated retry (#592).** Service `sub-bot`, `onBehalfOf: jane`, the same key and the same body sent twice.
  - The first answer was 202 `req-20261123-0001`, with requester `sub-jane`.
  - The retry was **409 `idempotency-replay`, "Idempotency-Key is in use for another request"**.
  - The same retry without `onBehalfOf` was 202 with the same `requestId`.

  The code agrees: `_replay` looks the key up under `who.sub` (`router.py:91`), and `submit` stores
  `plan.requester.sub` (`pipeline.py:508`).
- **Justification.** An `:extend` retry that changed only `justification` was 202 with the same `requestId`, and it kept
  the first justification ("One sprint").
- **Create replay.** It returns at `router.py:271-274` with no If-Match dependency.

**What the standard says.** draft-ietf-httpapi-idempotency-key-header-09, section 2.4
(<https://www.ietf.org/archive/id/draft-ietf-httpapi-idempotency-key-header-09.txt>, fetched 2026-11-23) says:

> "If the fingerprint covers only part of the payload, requests that differ only outside that part are treated as the
> same request."

> "A resource that does so SHOULD document it."

So leaving `justification` out is allowed, and documenting it is what the draft asks for. It is not a defect.

**Text changed. Each sentence is short and true, and none promises what #592 shows to be false.**

| Where | Change |
|---|---|
| `routers/__init__.py`, `idempotency_key` (create, PATCH, the expiry writes) | Adds: "For now a retry sent with `onBehalfOf` gets 409 `idempotency-replay` instead (#592). The same key with another request is 409 `idempotency-replay`. The expiry writes do not compare `justification`: a retry that changes only it gets the original request." Adds a docstring with the reason and the quote from the draft. |
| `delete_idempotency_key` | Not changed: a delete takes no `onBehalfOf` and no body, so its sentence is true |
| The `if_match` description | Not changed: it appears only on the five writes, so "An Idempotency-Key replay returns …" is scoped |
| `plugins/namespaces/router.py`, the PATCH docstring | "a retry with its original ETag returns the original request" became "it returns the original request in its current state", plus "The Idempotency-Key parameter says when a retry is a replay". I rewrapped it so that "original request in its current state" stays on one line: a wrap there broke `test_the_document_describes_a_replay…` on my first run. |
| `core/pipeline.py`, the `require_if_match` docstring | "a retry carrying its first ETag still gets" became "a replay carrying its first ETag still returns" |
| docs/04, the `Idempotency-Key` row | Adds the `onBehalfOf` sentence (with why: looked up under the caller, stored under the person) and the `justification` sentence |
| docs/04, the `If-Match` row | Now "An Idempotency-Key replay still needs If-Match and refuses `*`, and returns …" |
| docs/16, the `idempotency_key` row | "a hash of the body" became "a hash of the inputs that the route chooses (`fingerprint`, `repo.py`; the expiry routes leave out `justification`)", with the `requester_sub`/`_replay` mismatch (#592) |
| The glossary's `Idempotency-Key` row | The same two qualifications |
| LIVE-DOC-EDITS, docs/02:131 | The replay sentence is scoped to "one of these five writes". It adds "For a new plan, a namespace missing from Git is 404 first" and "A namespace create takes no If-Match". |
| LIVE-DOC-EDITS, docs/02:130 | A new edit. The old file said this row "already matches `_replay`"; #592 refutes that. |
| LIVE-DOC-EDITS, docs/01:236 | Adds the `onBehalfOf` sentence |
| LIVE-DOC-EDITS, "Not changed" | docs/02:128 is no longer defended as "the general API rule". It now says #594 shows the row is false and owns it. |

**The hash sentence, with #588 in.** `folder_etag` is now `core/pipeline.py:100-113`:

- It hashes `plan_hash`, in which an empty file is written as `<deleted>`.
- A folder where a file holds exactly `<deleted>` or a NUL is hashed from `"folder-v2:" + JSON` instead.

So "It changes when the folder changes" is now true of the `.yaml` files directly in the folder. Codex's replacement
("An empty file contributes `<deleted>`") would have been true of `plan_hash`, but it no longer describes the tag alone.

The glossary and the docs/02 proposal now say:

> 16 hex characters of a SHA-256 over the `.yaml` files directly in the namespace's folder in Git, or `0` when the
> folder has no such file. It hashes their `plan_hash` (each path and its content, an empty file written as
> `<deleted>`). A folder where a file holds exactly `<deleted>` or a NUL is hashed from its files as JSON instead, so an
> empty file and that file give different tags (#584). It changes when one of those files changes.

**Line cites in LIVE-DOC-EDITS** were updated for #588: `folder_etag` 100-113, `check_if_match` 136-146, and
`if_match_tags` 61-72.

**The proposed LIVE-DOC test** now asserts `"PATCH" in row and "DELETE" in row`. It also covers the v2 hash, 404-first,
the create and the scoped replay sentences, and the Idempotency row. It uses the new `_row` helper.

| Mutant | What it is | Result |
|---|---|---|
| m10 | The proposal applied to the docs/02 export | passed |
| m11 | The same, with "PATCH and DELETE" removed from the row | failed |

**New tests.**

- `test_the_expiry_writes_do_not_compare_the_justification_and_a_change_does` pins the behaviour the new descriptions
  state: an expiry retry with a new justification is 202, the same request, and keeps the first justification; a PATCH
  retry with a new justification is 409.
- `test_the_api_docs_describe_the_replay_and_the_one_field` now also requires `onBehalfOf`/#592 and the `justification`
  sentence in each `Idempotency-Key` row.

### 4. The two loose tests. Accepted.

**`:210-218` searched whole files.**

| Mutant | What it is | Result |
|---|---|---|
| m6 | 0ce8151: the one-field sentence removed from docs/04's If-Match row, its keywords put in an HTML comment | the old test passed, both files |
| m5 | The same mutation, against the new test | failed on docs/04 |

The new test selects each row with `_row(path, term)` (exactly one row whose first cell is the term) and asserts each
promise in its own row.

**`:200-206` counted events.**

| Mutant | What it is | Result |
|---|---|---|
| m8 | 0ce8151: `request_view` renames the cancel event | the count check passed |
| m7 | The same mutation, against the new assertions | failed |

The new assertions require `replay.events == cancelled.events`, no `cancel` in the first answer, and `cancel` in the
replay.

### 5. #595 overlap: the stand-in comments. Accepted. Comments only; the behaviour is #595's fix.

The PR's two comments claimed "the original request again", but the stand-in returns the stored first object. They now
say what the stand-in does, and point to #595:

- `standin.mjs:857`: "the request that the key opened, as first answered … Unlike the API, a replay is not refreshed to
  the request's current state (#595)".
- `standin.mjs:1161`: "The replay, before the If-Match check: … get the request as first answered. The API returns it in
  its current state and still requires If-Match without `*`; this stand-in does neither yet (#595)."

`node --check` passes, and `npm test` passed.

### Codex's other findings, re-checked on 0ce8151

- **`etag.py:32`, the If-None-Match strip.** #588 fixed it. `etag_matches("\xa0*\xa0", '"abc"')` is now `False`,
  `" *\t"` is `True`, and `W/"abc"` is `True`. Nothing to do here.
- **`cors.py:102`.** This is #593, out of scope.
- **The contract gate.** Confirmed again on the fixed copy (see Tests).

## Tests: what I ran

The before run is `head2` as copied to `h2run/`. The after run is `r2/`.

**Service tests.** The nine files from the brief:

| Run | Result | Output |
|---|---|---|
| **Before** (0ce8151) | 1 failed, 359 passed | `r2-outputs/before-head2-pytest.txt` |
| **After** (fixed copy) | 1 failed, 361 passed (2 new tests) | `r2-outputs/after-r2-pytest.txt`; after the last docstring edit I reran the #581 file: 16 passed |

The one failure on both sides is `test_doc_citations.py`. The export has no `.git`, so `git ls-files` exits 128. That is
the environment, not the code. In its place I ran `scripts/doc-citations.py`'s `check()` with the export's file list
standing in for `git ls-files` (`r2-outputs/citations_check.py`): "no problems" on head2 and on r2.

**Mutants.** Twelve full tree copies in `r2-mut/`, built by `r2-outputs/make_mutants.py` and run by
`r2-outputs/run_mutants.sh`. Every one gave its expected result. The output is in `r2-outputs/mutants.txt`.

| Mutant | Result |
|---|---|
| m0 | 4 passed |
| m1 | 4 failed |
| m2 | 5 passed |
| m3 | failed |
| m4 | passed |
| m5 | docs/04 failed |
| m6 | 2 passed |
| m7 | failed |
| m8 | passed |
| m9 | failed |
| m10 | passed |
| m11 | failed |

**The contract.**

- I rewrote it (`CMAPI_WRITE_CONTRACT=1 … -k committed_contract`). Only descriptions changed: the 10 `Idempotency-Key`
  occurrences and the PATCH description. The `If-Match` schemas are identical to 0ce8151.
- `schema.generated.ts`: I regenerated it with `scripts/api-types.mjs`, with node_modules symlinked from `wt-581`. Only
  comments changed, and `permissions.generated.ts` is unchanged.
- **oasdiff 1.37.0.**
  - base 9876fee → r2: `gate.sh` exit 0, 10 errors.
  - Each normalised line equals the 10 lines of `accepted-breaking.txt`: True (`r2-outputs/oasdiff-after.txt`).
  - head2 → r2: no breaking change.
- **Spectral.** `contract/lint.sh` exit 0, with spectral node_modules symlinked from `wt-581`.
- `scripts/api-examples-doc.py --check` exit 0.

**Portal.** `npm test` in `r2/cmapi-portal-ui`: exit 0 (`r2-outputs/portal-npm-test.txt`).

## Tests: what I did not run

- **The #582 front-door case** (`deploy/tests/front-door-test.py`): there is no nginx on this machine.
- **The delegated retry as a committed test.** #592 owns that test, so the measurement above was a throwaway probe.
- **Nothing on CRC or kind.**

## For the coordinator to file

None of these is in this PR's scope, and none blocks it.

1. **#592: add the measurement.** The delegated retry is **409 `idempotency-replay`, "Idempotency-Key is in use for
   another request"**. That is a wrong problem for a correct retry, not only a missed replay.
2. **New, or add to #595: the stand-in's expiry fingerprint includes `justification`.** `standin.mjs:1164`,
   `fingerprint({ ...body, route, clusterId, namespace: ns })`. The API leaves it out, so for a retry that changes only
   the justification the stand-in answers 409 where the API replays.
3. **New, trivial: a stale migration comment.** `cmapi/src/cmapi/core/db/migrations/versions/0001_cmapi_schema.py:59`
   still says "returns the first response". It is a migration file, so I left it for a deliberate edit.

## Who wrote what

Reviewer 2 (Opus 5.5, high) wrote:

- every change in `r2-outputs/fix.diff`;
- `r2-outputs/LIVE-DOC-EDITS.md`;
- the mutant scripts.

The design of the #586 helper and the transport test started from reviewer 1's (Codex) snippets and was narrowed as
described above.
