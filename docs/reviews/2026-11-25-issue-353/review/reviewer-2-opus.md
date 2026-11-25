# PR #681 (closes #353): reviewer 2 (Opus 5.5 high)

I reviewed reviewer 1's report (`r1-opus-report.md`) and its `r1-outputs/fix.diff` against `head/` at `c0cf45f`. I did not write
the PR or reviewer 1's fix. My copy is `r2-work/` (head plus reviewer 1's `fix.diff`, applied with `patch -p1 -F0`, then my
changes). Every result below comes from the venv `wt-655-outputs/venv-merged`: CPython 3.12.14, pydantic 2.14.2,
pydantic-core 2.50.2, FastAPI 0.162.2, Starlette 1.10.0 and structlog 26.1.0. The service tests ran on PostgreSQL 16, database
`cmapi_r2_681`, on this Mac. No cluster was used.

The final patch is `r2-outputs/fix.diff`, 263 lines, a complete patch against `head/`. Applied to a fresh copy of `head/` with
`patch -p1 -F0`, it gives a tree byte-identical to `r2-work/`.

## Verdicts on reviewer 1's points

| # | R1 severity | Verdict | Why (measured) |
|---|---|---|---|
| H1 | High | **Accept** | Speed claims hold on my copy (below). The capped walk matches head's walk on 60,000 random bodies. |
| M1 | Medium | **Accept, amended** | Head answers 500 at every depth from 600 to 9900, for every kind of field. The fix answers 422 at all of them. I added depth 8000 and a NUL leaf to the test, and corrected the docstring: the limit is CPython's C recursion counter, not "the C stack". |
| L1 | Low | **Accept, extended** | The fetched RFC 7493 text (rfc-editor.org, 2026-11-25) reads `while "𐊭" would be legal`. The same mangling also hit README line 85 (R2-1 below). |
| L2 | Low, Backlog | Accept | — |
| L3 | Low, Backlog | Accept | — |

## Check 1: does the walk match the old one?

**Differential test.** `r2-outputs/diff_walk.py` loads head's `models.py` and the fixed `models.py` side by side and runs
60,000 random bodies (3 seeds × 20,000; `diff_walk.txt`). The bodies mix nested dicts and lists, surrogate keys, NUL, reversed
pairs, valid pairs, CESU-like halves, the 6 ASCII characters `\ud800`, U+FFFD, and bodies that are not objects. For each body:

- `holds_nul` gives the same answer on both.
- The fixed `surrogate_places` equals head's first 20 places.
- With `MAX_PLACES` lifted, the fixed walk equals head's **in full**: the same places, in the same order.

| Seed | Bodies | Places | Bodies with more than 20 places | Equal with the cap lifted |
|---|---|---|---|---|
| 1 | 20,000 | 663,506 | 9,148 | 20,000 |
| 2 | 20,000 | 660,380 | 9,049 | 20,000 |
| 3 | 20,000 | 661,003 | 9,115 | 20,000 |

**Edge cases, run by hand:** `"\ud800"`, `["\ud800"]`, `{"\ud800":"\ud800"}`, `[]`, `{}`, `[[],[[]],"\ud800"]`, and a key at
depth. All are identical. One case differs: a dict with an `int` key (`{1: "x"}`) raises `AttributeError` in head (`_shown(key)`
runs for every key), and the fix handles it. JSON cannot produce such a key, so this is a note, not a finding.

**`place_of` through the app.** The surrogate keys at depth in `{"x":{"a":[{"\udfff":{"b\ud800":"\udc00"}}]}}` give three
fields, the same on head and on the fix: `body.x.a.0.\udfff.[key]`, then `body.x.a.0.\udfff.b\ud800.[key]`, then
`body.x.a.0.\udfff.b\ud800`. They are now the test case `keys-at-depth`.

## Check 2: is the depth fix complete? (decides M1)

**Primary sources** (CPython 3.12.14; the headers installed with the interpreter, and `Modules/_json.c` fetched at tag
`v3.12.14`, saved in `r2-outputs/src/_json-v3.12.14.c`):

- `Include/cpython/pystate.h` lines 251-273, the non-debug build that is not WASI, s390x, Windows or ASan:
  `#    define C_RECURSION_LIMIT 10000`.
- `Include/internal/pycore_ceval.h:16`: `#  define Py_DEFAULT_RECURSION_LIMIT 1000`. This is `sys.getrecursionlimit()`, which
  returned 1000 when measured.
- `Modules/_json.c:1043` and `:1051`: `_Py_EnterRecursiveCall(" while decoding a JSON object "` and
  `" while decoding a JSON array "`.
- `pycore_ceval.h:117-122`: that call decrements `tstate->c_recursion_remaining`, the C counter.

So the decoder goes about 10,000 deep, while a Python recursive walk stops near 1,000 frames. Reviewer 1's "its limit is the C
stack" is imprecise: the limit is the C recursion counter. I fixed the docstrings in `models.py` and in the test.

**Measured through the app** (`r2-outputs/probe-head.txt` and `probe-fix.txt`; probe `r2-outputs/probes/test_r2_probe_681.py`;
TestClient, `POST /namespaces?dryRun=true`, bodies built as bytes). There were 11 body shapes at depths 600, 5000, 8000, 9900,
10100 and 20000:

| Body shape | Head, depth 600 to 9900 | Fix, depth 600 to 9900 | Both, depth 10100 and 20000 |
|---|---|---|---|
| Unknown member `x`: plain, surrogate or NUL leaf, or dicts with a surrogate key | **500** internal-error | 422: `extra_forbidden`, `string_surrogate` at the full place, or the NUL `value_error` | 422 `json_invalid` (the decoder's RecursionError, #646) |
| Deep value at `labels`, `justification`, `annotations.note` or `limitRange.container.max.cpu` | **500** | 422 `dict_type` or `string_type` at that field | 422 `json_invalid` |
| The body itself a deep list: plain, or with a surrogate | **500** | 422 `model_attributes_type`, or `string_surrogate` at `body.0.0…` | 422 `json_invalid` |

- **Head:** 44 of the 44 cases at depths 600 to 9900 gave 500.
- **Fix:** 0 of the 66 cases gave 500.

**Other recursion on a request body:**

- **Pydantic.** No body field is `Any`, recursive or unbounded. The 8 RequestBody classes use `str`, `int`, `date`,
  `dict[str, str]`, `dict[str, str | None]` and `LimitRangeValues = dict[str, dict[str, dict[str, str]]]`, and every class has
  `extra="forbid"`. Pydantic therefore stops at the first wrong type, or at `extra_forbidden`, and never descends. The rows
  above measure this at every typed field. This rests on cmapi's field types and on these measurements; I did not quote
  pydantic-core's source.
- **After validation.** The deepest body that passes validation is 4 levels (`limitRange.container.max.cpu`), so no route,
  audit or storage step ever sees a deep body.
- **The structlog renderer and `jsonable_encoder`.** The 422 path renders only `{field, message, code}` strings. Answers up to
  399,154 B rendered with no error. A deep 422 never reaches the 500 log path now.
- **FastAPI telemetry.** `fastapi/telemetry/_api.py:151-174` stores `exc.body` only when request telemetry is set up, and cmapi
  does not set it up.

**Bounded remainder (measured; not a finding).** The answer still grows with depth: each named field is about twice the depth
long. Twenty places at the bottom of a 9900-deep body gave 399,154 B in 0.169 s, from a body of about 20 KB. One place at that
depth gave 20,512 B. This is about 20 times the body, and it cannot grow further, because the decoder refuses depth 10,100 or
more. Before the fix, the same kind of body gave 93 MB in 15 s. Pydantic's own errors already reach 10 MB (L2), so no further
cap is warranted. L2's edge limit covers it.

## Check 3: does the 20-place cap hide anything a client needs? Does docs/02 match the code?

- docs/02 line 150 (reviewer 1's text) says "one error … for each place, the first 20 in document order … at any depth that the
  decoder reads". All three hold:
  - the first 20: `test_a_refusal_names_the_first_twenty_places_only`;
  - document order: the differential test;
  - any depth the decoder reads: 9900 gives 422 with the place, and 10100 gives `json_invalid`.
- The client still gets the first 20 places in order. After fixing them and sending again, it gets the next ones, so nothing is
  lost. What the answer does not say is whether more than 20 exist (Backlog R2-B2).

## Check 4: the speed claims on my copy

I ran reviewer 1's `walk_fix_verify.py` against my copy (`r2-outputs/walk_speed_r1script_on_r2copy.txt`). It found the same
answers on 30,000 random bodies.

| Input | Head | Fix |
|---|---|---|
| Flat, 300k strings | 0.196 s | 0.327 s |
| 300k strings, 400 deep | 1.120 s | 0.288 s |
| 300k strings, 900 deep | RecursionError | 0.266 s |
| 100k surrogates, 400 deep | 3.380 s, 100,000 places | 0.044 s, 20 places |
| One surrogate, 8000 deep | RecursionError | 0.061 s |

- **Holds:** the fix makes the cost linear at any depth and bounds the answer.
- **Cost on flat bodies:** they are now 1.2 to 1.7 times slower. Reviewer 1 measured 0.180 s against 0.218 s; I measured
  0.196 s against 0.327 s. The validator walks the body twice, once for NUL and once for surrogates, and the generator costs
  more for each string (Backlog R2-B3).

## What reviewer 1 missed

| # | Severity | Finding | Status |
|---|---|---|---|
| R2-1 | Low, in the changed lines | README line 85 has `` (`😀`, U+1F600) `` (the bytes F0 9F 98 80) where the sentence means the escaped pair. This is the same mangling as L1; head's README has 2 such characters. | Fixed: `` (`😀`, U+1F600) `` |
| R2-2 | Low, in the changed lines | The README's proof says "13 tests". With the review's tests there are 19, and the README does not say that the walk is now a loop with a cap. | Fixed (below) |
| R2-3 | Test gap | No test covered a raw CESU-8 pair, or surrogate keys below the top. | Tests added |
| R2-4 | Test gap in M1's test | It covered depths 600 and 5000 only, and no NUL leaf at depth. `holds_nul` must *find* the NUL at depth, not only not crash. | Depth 8000 and a NUL leaf added |
| R2-B1 | Low, Backlog | A body with both a NUL and a surrogate gets only the NUL error at `body`, in either order (`probe-fix.txt`, `nul+surrogate` and `surrogate+nul`; head is the same). The client needs two round trips. Naming both would change #653's answer, which is outside #353. | No fix |
| R2-B2 | Low, Backlog | The cap is silent: an answer with 20 errors does not say whether more places exist. Precedent: OPA Gatekeeper caps audit violations at 20 by default (`--constraint-violations-limit`, "defaults to `20`"), and its status still reports `totalViolations`, where "the excess violations will not be reported" but are "still included" (<https://open-policy-agent.github.io/gatekeeper/website/docs/audit/>, fetched 2026-11-25). A count of all places would cost only the linear walk. | No fix |
| R2-B3 | Low, Backlog | Two walks for each body (`holds_nul`, then `surrogate_places`), so flat bodies are 1.2 to 1.7 times slower than head (Check 4). One pass could check both. | No fix |

**Proof for R2-1 and L1:**
- Byte count on `docs/reviews/2026-11-25-issue-353/README.md`. Head has 2 bytes `F0`, 0 copies of `😀` and 0 of
  `𐊭`. The fix has 0 bytes `F0`, 1 copy of each.
- `curl https://www.rfc-editor.org/rfc/rfc7493.txt | grep DEAD` gives line 133: `unpaired surrogate, while "𐊭" would
  be legal.`

### Full code of my changes beyond reviewer 1's

**`cmapi/src/cmapi/core/models.py`, the `strings_of` docstring** (code unchanged):

```python
    A loop over a stack of the containers it is in, not recursion: json.loads parses a body nested far deeper than Python's
    recursion limit of 1000, since its decoder counts depth against CPython's C recursion limit instead (10000 here; CPython
    3.12.14 Include/cpython/pystate.h C_RECURSION_LIMIT, Modules/_json.c; measured, depth 9900 parses). A recursive walk
    raised RecursionError from about depth 600, which answered 500. No place is copied on the way down, so the walk is
    linear in the size of the body at any depth."""
```

**`cmapi/tests/service/test_lone_surrogate_353.py`.** First the import:

```python
from test_client_input_653 import NUL_REFUSED
```

The new test after the ED A0 80 test:

```python
def test_a_pair_sent_as_cesu_8_bytes_is_two_lone_surrogates_and_is_refused(world):
    """U+1F600 as CESU-8, each half of its UTF-16 pair as three bytes (ED A0 BD, ED B8 80): not UTF-8 (RFC 3629, section 3,
    "The definition of UTF-8 prohibits encoding character numbers between U+D800 and U+DFFF"). json.loads decodes the bytes
    with "surrogatepass" and does not join the two halves, as it joins a `\\ud83d\\ude00` escape: the place is named once,
    with the first."""
    client, ctx, git, kube, validator, keys = world
    content = raw({**NS, "justification": "a"}).replace(b'"justification": "a"', b'"justification": "a\xed\xa0\xbd\xed\xb8\x80"')
    assert json.loads(content)["justification"] == "a😀"
    r = send(world, "POST", URL, content)
    assert_refused(r, "body.justification", message="holds U+D83D, a surrogate code point, which is not a Unicode character")
    assert recorded(world) == 0 and git.prs == {}
```

The new case of `test_a_surrogate_anywhere_in_a_create_is_refused_with_its_field`:

```python
    ({**NS, "x": {"a": [{"\udfff": {"b\ud800": "\udc00"}}]}},
     [("body.x.a.0.\\udfff.[key]", "U+DFFF"), ("body.x.a.0.\\udfff.b\\ud800.[key]", "U+D800"),
      ("body.x.a.0.\\udfff.b\\ud800", "U+DC00")]),
], ids=["label-value", "justification", "annotation-key", "unknown-member", "nested-limit", "each-place-named",
        "keys-at-depth"])
```

Reviewer 1's depth test, amended:

```python
@pytest.mark.parametrize("depth", [600, 5000, 8000])
def test_a_body_nested_deeper_than_python_recurses_is_refused_with_422_not_500(world, depth):
    """json.loads parses it: its decoder counts its depth against CPython's C recursion limit, 10000 on this platform
    (CPython 3.12.14 Include/cpython/pystate.h C_RECURSION_LIMIT; Modules/_json.c _Py_EnterRecursiveCall), not against
    sys.getrecursionlimit(), 1000 (measured: depth 9900 parses, 10100 is json_invalid). The recursive walks of RequestBody
    raised RecursionError from about depth 600 here, which answered 500 internal-error; the walk is a loop now. A NUL leaf
    is found at any depth too."""
    plain = send(world, "POST", URL + "?dryRun=true", nested(depth, b'"a"'))
    assert plain.status_code == 422, plain.text
    assert plain.json()["errors"] == [{"field": "body.x", "message": "Extra inputs are not permitted", "code": "extra_forbidden"}]
    nul = send(world, "POST", URL + "?dryRun=true", nested(depth, b'"a\\u0000"'))
    assert nul.status_code == 422, nul.text
    assert nul.json()["errors"] == [{"field": "body", "message": "Value error, " + NUL_REFUSED, "code": "value_error"}]
    r = send(world, "POST", URL + "?dryRun=true", nested(depth, b'"a\\ud800"'))
    assert r.status_code == 422, r.text
    assert r.json()["errors"] == [{"field": "body.x" + ".0" * depth, "message": MESSAGE, "code": "string_surrogate"}]
```

**`docs/reviews/2026-11-25-issue-353/README.md`:**
- Line 85: `` (`😀`, U+1F600) ``, plus two sentences on the loop and its reason.
- The answer: "one error for each place, the first 20 (`MAX_PLACES`) in document order".
- The proof: "19 tests", with a sentence naming the six the review added, and a bullet with the review's numbers (4 failed and 15
  passed on head; 103 of 103 on the fix; 60,000 random bodies equal).

docs/02 is reviewer 1's text, unchanged by me.

## Test results (`r2-outputs/fix-tests.txt`, `mutants.txt`)

| Run | Result |
|---|---|
| Head with the final `test_lone_surrogate_353.py` | **4 failed**, 15 passed: depths 600, 5000 and 8000 gave 500, and the cap test named 1,000 places |
| Fix: `test_lone_surrogate_353.py`, `test_client_input_653.py`, `test_framework_problems_646.py`, `test_value_error_648.py`, `test_api_docs.py` | **103 passed** in 130.03 s |
| Mutant: dict keys not walked (the key `yield` of `strings_of` removed) | 3 failed (`annotation-key`, `unknown-member`, `keys-at-depth`), 16 passed |

- The CESU-8 and keys-at-depth tests pass on head too. They cover behaviour the PR already had, which the brief asked for; they
  are not fail-before tests. The keys mutant shows `keys-at-depth` can fail.
- Not run: the full suite, kind or CRC.

## Files

- `r2-outputs/fix.diff`: the final patch against `head/`.
- `r2-outputs/diff_walk.py` and `diff_walk.txt`: the differential test.
- `r2-outputs/probes/test_r2_probe_681.py`, `probe-head.txt` and `probe-fix.txt`: the probes.
- `r2-outputs/walk_speed_r1script_on_r2copy.txt`: the speed check.
- `r2-outputs/fix-tests.txt` and `mutants.txt`: the test runs.
- `r2-outputs/src/_json-v3.12.14.c`: the fetched CPython source.
- `r2-outputs/run-*.sh`: the scripts that ran them.
