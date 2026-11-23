# PR #588 · reviewer 2 (Opus 5.5 high)

Head 995a890, base 9876fee. I worked in `review-588/r2/`, a copy of `head/`. No git repository was touched and nothing was
pushed. Nothing was written to CRC, LDAP or Keycloak. The service tests ran against my own database `cmapi_r2_588` on the
local PostgreSQL 16 at 127.0.0.1:55432. They ran only after the other agent's full suite (wt-581) had exited.

**Recommendation.** Apply `r2-outputs/fix.diff` (4 files) to #588 and merge once CI is green. The PR keeps
`Closes #583`, `Closes #584` and `Closes #585`. **#590 is not fixed here.** It goes in a follow-up pull request, started
at once. The reasons are in section 2. Do not add `Closes #590` to #588.

Every number below comes from a command whose output is saved in `review-588/r2-outputs/`. The probe scripts are in
`r2-outputs/scripts/`.

## 1. #585, the CA scan: Codex's finding is confirmed. Fixed, with a line-aware scan

**Confirmed on head, with Python's real loader.** I used `load_verify_locations(cadata=...)` on Python 3.12.14 with
OpenSSL 3.6.4, and the real CA from `test_crc_reader_import_398.py:17-28` (`r2-outputs/ca-probe.txt`):

| caData | base | head | r2 | certificates the TLS loader loads |
|---|---|---|---|---|
| CA, then `Example: -----BEGIN CERTIFICATE-----` | True | **False** | True | 1 |
| The same quote before the CA | False | False | True | 1 |
| CA, then `-----BEGIN CERTIFICATE----- is how a block starts` | True | **False** | True | 1 |
| CA, then `Note:<FF>-----BEGIN CERTIFICATE-----` | True | **False** | True | 1 |
| A stray END line before, after or between complete blocks | True | **True** | False | 1 |
| CA, then an unclosed BEGIN | True | False | False | 0 |
| CA, CRLF line ends, or SP/HTAB after a boundary | True | True | True | 1 |
| Leading SP before the boundaries | True | True | False | 0 |
| A BEGIN inside an open block | False | False | False | 1 |
| Bare `YQ==` | True | True | True | 0 |

Through the service, head turns the first rows into `invalid-secret ["invalid caData"]`. My new test
`test_a_certificate_with_text_that_quotes_a_boundary_connects` shows it (section 6).

**Ruling on the stray END: refuse it, as Codex and the brief say.** The evidence is that a stray END is what a lost BEGIN
line leaves, and OpenSSL then drops that certificate without saying so (`r2-outputs/lost-begin-probe.txt`). I used a second
throwaway CA, generated in the scratchpad; only its public certificate was kept.

```
CA + CA2                             base True  head True  r2 True   ssl_loaded=2
CA + CA2 that lost its BEGIN line    base True  head True  r2 False  ssl_loaded=1
```

So refusing the stray END prevents a cluster that trusts one CA fewer than the operator gave it.

**Two rows change behaviour on purpose.**

- **Stray END.** Above.
- **Leading space before a boundary.** OpenSSL does not read such a line as a boundary, and it loads 0 certificates. Base
  and head gave `invalid caData: <the TLS error>`. r2 gives `invalid caData` from the precheck. The status is
  `invalid-secret` either way; only the finding's text changes.

**The BEGIN-inside-a-block row is unchanged.** OpenSSL loads 1, and base, head and r2 all refuse it.

**Codex's replacement, checked against RFC 7468 §2-3.** I fetched https://www.rfc-editor.org/rfc/rfc7468.txt on
2026-11-23.

- §2: "Textual encoding begins with a line comprising "-----BEGIN ", a label, and "-----", and ends with a line
  comprising "-----END "…". So a boundary is a line.
- §2: "Data before the encapsulation boundaries are permitted, and parsers MUST NOT malfunction when processing such
  data."
- §2: "lines are divided with CRLF, CR, or LF".
- §3 ABNF: `textualmsg = preeb *WSP eol …`. So only WSP (SP or HTAB) may follow a boundary.

Codex's logic is right, and I kept it. I changed one thing: line splitting. Codex used `str.splitlines()`, which also
splits on VT, FF, FS, GS, RS, NEL, U+2028 and U+2029. That is not RFC 7468's line division, and it is not OpenSSL's. I
measured Codex's snippet verbatim: with `CA + "Note:<sep>-----BEGIN CERTIFICATE-----\n"`, where sep is `\x0c`, `\x0b` or
`\x1c`, it returned **False**, and the loader loaded 1. r2 splits with `re.split(r"\r\n|\r|\n", ...)`, exactly the RFC's
CRLF, CR or LF. The rest of the function:

- Trailing SP/HTAB on a boundary line is stripped.
- A BEGIN inside an open block, an END with no open block, a body that is not base64, and an unclosed last BEGIN are each
  False.
- A value with no boundary line keeps the earlier bare-base64 fallback.

**Linear time** (`r2-outputs/timing.txt`, CPU ms, r2):

| Input | Sizes | CPU ms |
|---|---|---|
| Unclosed BEGINs | 46.5 / 93 / 186 kB | 0.76 / 1.27 / 2.49 |
| Valid CA ×100 / ×1000 / ×3000 | 60 kB / 0.6 MB / 1.8 MB | 1.38 / 13.98 / 41.84 |
| Prose quoting BEGIN | 10k / 100k / 300k lines | 0.64 / 5.95 / 18.91 |

Time grows linearly with the input. It is about 2× head's constant factor, from the one `re.split`. The PR's timing test
passes on r2: it is in the 52 that passed. I updated its docstring from the measurement: "about 3 ms" and "a margin of over
80 times". The old "about 1 ms" and "over 100 times" no longer hold (2.49 ms measured, so 0.25 s / 2.49 ms ≈ 100×; I wrote
80 to leave room).

**Tests (better than Codex's two).** In `test_validators_583_584_585.py`:

- 8 new rows in `test_ca_data_needs_complete_blocks`:
  - a quote after a block;
  - a quote before a block;
  - an END quoted in a sentence;
  - SP/HTAB after the boundaries;
  - a stray END before a block, and after one;
  - a lost BEGIN;
  - a BEGIN inside an open block.
- `test_a_certificate_with_text_that_quotes_a_boundary_connects`, 4 cases. It goes through `ClusterRegistry._check`, with
  a client factory that calls `Trust.verify()`, the real `ca_data_context` loader. It asserts `("connected", [])`.
- `test_a_certificate_that_lost_its_begin_line_is_refused`. It asserts `("invalid-secret", ["invalid caData"])`.

These tests go through the service path, as `_check_import` does. Codex's two tests used `ssl` and `_valid_ca_data`
directly. On head's source, 9 of these fail; the other 4 rows pass, because they check compatibility. All pass on r2
(section 6).

## 2. #590, If-Match precedence: confirmed. Ruling: a follow-up PR, started at once, not #588

**Confirmed** (`r2-outputs/if-match-590-probe.txt`, the real `_add_docs` routes, no database):

| Request to /openapi.json | base | head |
|---|---|---|
| Stale If-Match, If-None-Match `*` | 304 | 304 |
| Stale If-Match, If-None-Match `"older"` then the current tag | 200 | 304 |
| Current If-Match and current If-None-Match | 304 | 304 |

RFC 9110 §13.2.2 (fetched 2026-11-23): "When recipient is the origin server and If-Match is present, evaluate the If-Match
precondition: … if false, respond 412". §13.1.1: an origin server "MUST evaluate the If-Match condition per Section 13.2
prior to performing the method".

**Why it is not in #588.**

1. **#588 does not create the non-compliance.** Base already answers 304 where 412 is required (row 1). The newly reachable
   row 2 changes one wrong answer (200) into another (304). That 304's claim is true: the If-None-Match tag is current.
2. **The correct fix is a change of the public API contract.** Codex's snippet is not.
   - `/metadata-keys` and `/capacity` document their conditional behaviour through `CONDITIONAL_READ`
     (`core/docs.py:111-123`), which declares only If-None-Match, 200 and 304.
   - A 412 there needs a documented If-Match parameter. Once that parameter is declared,
     `test_each_operation_has_one_curl_sample_that_the_app_accepts` (`test_api_docs.py:218-220`) requires each curl sample
     to carry If-Match.
   - The committed `contract/openapi.json` must then be rewritten (`test_api_docs.py:378-387`).
   - Every other 412 in cmapi is the problem+json `precondition-failed` with the current `etag`
     (`pipeline.py:139-142`). Its documented detail (`docs.py:50`, "The namespace changed in Git since you read it") is
     namespace-specific.
   - Codex's handlers return a 412 with no body and no documentation. Shipped as is, that is an undocumented,
     non-problem error on two documented operations.

   That is a design step of its own under the delivery loop (two designs, contract, samples), not a surgical
   addition to a parser fix.

**For the follow-up's brief.** I prototyped this in the scratchpad; it is not in fix.diff. It tightens Codex's
`read_precondition`:

- It reuses `if_match_tags`, so cmapi has one reading of If-Match, weak tags excluded.
- `*` holds.
- It takes the Headers, so that an empty `If-Match:` is evaluated (and false) rather than treated as absent.

```python
def read_precondition(headers: Headers, etag: str) -> int | None:
    """What a conditional read answers instead of 200, in RFC 9110 section 13.2.2's order: 412 when If-Match is present
    and false, by the strong comparison (13.1.1; `*` holds, as the representation exists), then 304 when If-None-Match
    matches (13.1.2), else None. Each field's lines are joined with ", " (section 5.3)."""
    if_match = headers.getlist("if-match")
    if if_match:
        value = ", ".join(if_match)
        if value.strip(" \t") != "*" and etag[1:-1] not in if_match_tags(value):
            return 412
    return 304 if etag_matches(", ".join(headers.getlist("if-none-match")), etag) else None
```

Measured on `/openapi.json` with it:

| Request | Answer |
|---|---|
| Stale If-Match, If-None-Match `*` | 412 |
| Stale If-Match, two If-None-Match lines | 412 |
| Current If-Match and current If-None-Match | 304 |
| If-Match `*` and current If-None-Match | 304 |
| If-Match `W/<current>` | 412 |
| If-Match on two lines, current second | 200 |
| Current If-Match alone | 200 |
| Empty If-Match | 412 |
| No conditions | 200 |

The follow-up must also:

- return a `Problem(412, "precondition-failed", …, extra={"etag": etag})` with a read-side detail;
- add If-Match and 412 to `CONDITIONAL_READ`;
- exclude If-Match in `takes_validated_input` as If-None-Match is;
- regenerate the contract and the samples;
- test `/metadata-keys` and `/capacity` through `world`.

None of that was run.

## 3. #584

**The `pipeline.py` docstring is reworded, in the same 4 lines (103-106).** Codex's correction is applied: ordinary folders
keep their tags, and an old tag of an exceptional folder still matches the folder it was confused with. The line count is
unchanged, so no citation in docs/14 moves. `doc-citations` reports 0 problems on head and on r2
(`r2-outputs/doc-citations.txt`). I ran it with `tracked()` listing the export's files, because the export has no git.

**The test of two exceptional folders is added and kills the constant-v2 mutant.** The mutant replaces line 110 of r2 with
`return "deadbeefdeadbeef"`. `test_two_exceptional_folders_differ_by_content_and_not_by_order` checks a change of content,
a change of path, and that reversed insertion order gives the same tag.

| Tests | Result on the mutant |
|---|---|
| Head's own file | 36 passed (the mutant survives) |
| r2's file | 1 failed, `test_two_exceptional_folders_differ_by_content_and_not_by_order`; 51 passed |

**The surrogate-pair note: a docstring line is enough.**

- All three Git readers decode strictly: `core/git/workspace.py:317` with `.decode()`, and `github.py:77` and `gitea.py:76`
  with `base64.b64decode(...).decode()`.
- I measured that strict UTF-8 refuses surrogate bytes: `b'\xed\xa0\xbd…'.decode()` raises `UnicodeDecodeError`.
- So a lone surrogate never reaches `json.dumps`. `json.dumps('😀') == json.dumps('😀')` is True, and that is
  the only way the collision arises.
- The docstring now says "unambiguous for Git's strict UTF-8 (no lone surrogate)".
- Changing production tags, or using `ensure_ascii=False`, would gain nothing. Worse, a lone surrogate would then raise on
  `.encode()`.

## 4. The If-None-Match test gap: closed

`test_an_authenticated_read_joins_the_if_none_match_lines[/api/v1/metadata-keys | /api/v1/capacity]` runs through `world`
as `ola`. It sends `"older"` on the first If-None-Match line and the current tag on the second, and asserts
`(304, b"", etag)`. I reverted each handler's join to `.get("if-none-match")`:

| Mutant | Result |
|---|---|
| `routers/me.py:81` | 1 failed (`[/api/v1/metadata-keys]`); 60 passed, `test_metadata_keys_336_api.py` included |
| `plugins/capacity/router.py:223` | 1 failed (`[/api/v1/capacity]`); 80 passed, `test_capacity_302.py` included |

This confirms Codex: the existing endpoint tests miss both reverts, and the new test catches each one.

## 5. docs/02, line 775: the live-doc edit, first

Apply this to the live Claude Doc first, then to the export. The export change is in fix.diff.

**Old text:**

> a caData with a `BEGIN CERTIFICATE` line that no `END CERTIFICATE` line follows, with an `END` line and no `BEGIN` line, or whose certificate blocks are not valid base64 (finding `invalid caData`; `_valid_ca_data` reads the value once, in linear time, decodes each block and does not parse the certificate, #585)

**New text:**

> a caData with an unmatched `BEGIN CERTIFICATE` or `END CERTIFICATE` boundary line, or whose certificate blocks are not valid base64 (finding `invalid caData`; `_valid_ca_data` reads the boundaries as whole lines, as RFC 7468 and OpenSSL do, so text outside the blocks that quotes one is ignored; it runs in linear time, decodes each block and does not parse the certificate, #585)

## 6. Test outputs

Commands, from each tree's `cmapi/`, are in `scripts/run-r2.sh` and `scripts/run-r2b.sh`:

```sh
CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r2_588 \
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python \
  -m pytest <files> -q -W ignore -p no:cacheprovider -rf --tb=line
```

The 15 files:

- `test_validators_583_584_585.py`, `test_if_match_forms_571.py`, `test_api_docs.py`, `test_capacity_302.py`,
  `test_metadata_keys_336_api.py` and `test_crc_reader_import_398.py`;
- every file that touches `caData`, `_valid_ca_data` or `_check_import`: `test_registry_ca_bundle.py`,
  `test_registry_survives_419.py`, `test_cluster_trust_434.py`, `test_cluster_trust_review_435.py`,
  `test_cluster_trust_chart_434.py`, `test_cluster_diagnostics_396.py`, `test_cluster_probe_397.py`,
  `test_second_pass.py` and `test_token_renew_398.py`.

| Run | Result | File |
|---|---|---|
| Before: head's tree, all 15 files | **395 passed** in 202.87 s | `head-own-tests.txt` |
| r2's test file on head's source | **9 failed, 43 passed**: the 5 new #585 rows, 3 connect cases and the lost-BEGIN test | `r2-tests-on-head-src.txt` |
| After: r2, all 15 files (run 1) | 410 passed, 1 failed | `r2-all-files-run1.txt` |
| After: r2, `test_validators_583_584_585.py` (run 2) | **52 passed** | `r2-validators.txt` |
| Mutant: me.py join reverted | 1 failed, 60 passed | `mutant-me.txt` |
| Mutant: capacity join reverted | 1 failed, 80 passed | `mutant-capacity.txt` |
| Mutant: constant v2, head's tests | 36 passed | `mutant-v2const-head-tests.txt` |
| Mutant: constant v2, r2's tests | 1 failed, 51 passed | `mutant-v2const-r2-tests.txt` |
| `doc-citations --check`, head and r2 | 0 problems each | `doc-citations.txt` |

In run 1, the one failure was my own wrong table row: `BEGIN + "YQ==\n" + "Example: " + BEGIN` had no END line. I
corrected it to `BEGIN + "YQ==\n" + END + "Example: " + BEGIN` and reran the file. **After, in total: 411 passed, 0
failed.** That is 359 in the other 14 files on r2 in run 1, plus 52 in the test file in run 2. The other 14 files did not
change between the runs.

**Retracted.** My first runs of the mutants and of "r2's tests on head" were invalid, and I discarded them.
`cmapi/pyproject.toml:44` sets `pythonpath = ["src", "tests/core"]`, so pytest put the tree's own `src` before my
`PYTHONPATH`, and those runs actually tested r2's source. The second runs use one full tree per variant. Coordinator: the
same trap applies to any mutant run that swaps only `PYTHONPATH`.

## 7. A new defect outside this PR, for the coordinator to file

**caData with any non-ASCII character is `unreachable` with "the check failed: TypeError", instead of being loaded or
refused as `invalid-secret`.** Measured on base and on r2 alike, so it predates #588, through `_check_import` with
`Trust.verify()`:

```
'# Issuer: CN=Zürich Root CA\n' + CA  -> unreachable ['the check failed: TypeError: cadata should be an ASCII string or a bytes-like object']
'# Issuer: CN=Zurich Root CA\n' + CA  -> connected []
```

Python's documentation (https://docs.python.org/3.12/library/ssl.html, fetched 2026-11-23) says: "The cadata object, if
present, is either an ASCII string of one or more PEM-encoded certificates or a bytes-like object of DER-encoded
certificates."

- **Where.** `core/clients/trust.py:95-99`, `ca_data_context`, passes the str as it is. `registry.py` `_check` catches
  only `OSError` around the client factory, so the `TypeError` falls to `_check_failed`.
- **Why it matters.** RFC 7468 §2 permits text before the boundaries, and an issuer name in such a comment can be UTF-8.
- **Fix direction, to be researched.** Refuse non-ASCII text inside a block. Pass the loader only the ASCII blocks, or
  refuse a non-ASCII caData as `invalid caData` with a clear finding. Never encode the value to bytes: bytes are read as
  DER.
- **Proof.** A `_check_import` test with a UTF-8 comment and the real CA.

## 8. What I ran and did not run

**Ran:**

- the probes above, on base, head and r2, with Python's own TLS loader;
- the 15 service test files on head and on r2;
- the three mutants;
- `doc-citations --check`, with `tracked()` replaced by the export's file list, because the export has no git;
- `patch -p1` of `fix.diff` onto a fresh copy of head. The result is byte-identical to r2 for all 4 files.

**Not run:**

- the full service suite (the brief allows only targeted files);
- CI, the API contract gate and the portal tests;
- the #590 prototype through `world` or for `/metadata-keys` and `/capacity` (it is not part of this fix);
- `openssl` CLI cross-checks, beyond generating the throwaway CA2;
- the live Claude Doc edit itself, which is left to the coordinator.

## 9. The patch: `r2-outputs/fix.diff`

It is against head 995a890, applied with `patch -p1` from the repo root. Its files are `cmapi/src/cmapi/core/registry.py`
(`_valid_ca_data`, lines 294-325), `cmapi/src/cmapi/core/pipeline.py` (lines 103-106),
`cmapi/tests/service/test_validators_583_584_585.py` and `docs/02-technical-design-v2.md` (line 775).
`examples/src/cmapi` is a symlink to `cmapi/src/cmapi`, so it is left out of the diff on purpose.

The full text of `r2-outputs/fix.diff`:

```diff
--- a/cmapi/src/cmapi/core/registry.py
+++ b/cmapi/src/cmapi/core/registry.py
@@ -293,26 +293,37 @@
 
 def _valid_ca_data(ca_data: str) -> bool:
     """Each PEM block by itself: a service account's ca.crt is usually a bundle, and base64 padding may end any block, so
-    the blocks joined are not base64 even when each one is. Every BEGIN line needs an END line after it (#585): OpenSSL
-    refuses a block that is not closed. Text before, between and after the blocks is ignored, as RFC 7468 section 2 and
-    OpenSSL allow. A value with no BEGIN line is read as bare base64, as before, unless it has an END line, which only a
-    broken block leaves; the client finds no certificate in bare base64 and says so (#419). split and partition read the
-    value once, in linear time: the regex this replaces rescanned the rest of the value from every BEGIN line."""
-    preamble, *blocks = ca_data.split(PEM_BEGIN)
-    if blocks:
-        parts = [block.partition(PEM_END) for block in blocks]
-        if not all(end for _, end, _ in parts):
+    the blocks joined are not base64 even when each one is. A boundary is a whole line: PEM_BEGIN or PEM_END, then only SP
+    or HTAB (RFC 7468 sections 2 and 3, whose lines end in CRLF, CR or LF). Each BEGIN line needs an END line before the
+    next BEGIN, and each END line an open BEGIN (#585): OpenSSL refuses a block that is not closed. Other text before,
+    between and after the blocks is ignored, as RFC 7468 and OpenSSL allow, even a sentence that quotes a boundary. A value
+    with no boundary line is read as bare base64, as before; the client finds no certificate in it and says so (#419).
+    One pass over the lines, in linear time: the regex this replaces rescanned the rest of the value from every BEGIN."""
+    def decodes(lines: list[str]) -> bool:
+        try:
+            return bool(base64.b64decode("".join("".join(lines).split()), validate=True))
+        except (binascii.Error, ValueError):
             return False
-        bodies = [body for body, _, _ in parts]
-    elif PEM_END in preamble:
-        return False
-    else:
-        bodies = ["".join(l for l in ca_data.splitlines() if not l.startswith("-----"))]
-    try:
-        return all(base64.b64decode("".join(b.split()), validate=True) for b in bodies)
-    except (binascii.Error, ValueError):
-        return False
 
+    lines = re.split(r"\r\n|\r|\n", ca_data)
+    body: list[str] | None = None          # the lines of the open block; None outside a block
+    blocks = 0
+    for line in lines:
+        boundary = line.rstrip(" \t")
+        if boundary == PEM_BEGIN:
+            if body is not None:
+                return False               # a BEGIN inside an open block
+            body = []
+        elif boundary == PEM_END:
+            if body is None or not decodes(body):
+                return False               # an END with no open BEGIN, or a body that is not base64
+            body, blocks = None, blocks + 1
+        elif body is not None:
+            body.append(line)
+    if body is not None:
+        return False                       # the last BEGIN is never closed
+    return blocks > 0 or decodes([line for line in lines if not line.startswith("-----")])
+
 
 def _secret(doc: Mapping[str, Any]) -> dict[str, Any]:
     """A Secret as the checks read it. A value that is not base64 of UTF-8 text (a binary file put in a Secret) is named in
--- a/cmapi/src/cmapi/core/pipeline.py
+++ b/cmapi/src/cmapi/core/pipeline.py
@@ -100,10 +100,10 @@
 def folder_etag(files: Mapping[str, str]) -> str:
     """The ETag of a namespace: a hash of its folder's content, stable until the folder changes, and "0" for no files.
 
-    A strong validator changes with every change of the content (RFC 9110 section 8.8.1), so two different folders must not
-    give one hash input. plan_hash writes an empty file as DELETED and ends each path and content with NUL, so a file that
-    holds DELETED, or a NUL, could read as another folder (#584). Only such folders are hashed from an unambiguous JSON
-    encoding; every other folder keeps the tag it always had, so no tag a client holds goes stale. A Git path has no NUL."""
+    A strong validator changes with every change of the content (RFC 9110 section 8.8.1). plan_hash writes an empty file
+    as DELETED and ends each path and content with NUL, so a file holding DELETED or a NUL read as another folder (#584);
+    a Git path has no NUL. Only such a folder is hashed from JSON, unambiguous for Git's strict UTF-8 (no lone surrogate).
+    Every other folder keeps its tag; a tag given for such a folder before #584 still matches the folder it read as."""
     if not files:
         return "0"
     if any(text == DELETED or "\0" in text for text in files.values()):
--- a/cmapi/tests/service/test_validators_583_584_585.py
+++ b/cmapi/tests/service/test_validators_583_584_585.py
@@ -14,7 +14,9 @@
 #585, caData (core/registry.py, _valid_ca_data). RFC 7468 section 2 (https://www.rfc-editor.org/rfc/rfc7468.txt, read
 2026-11-23): textual encoding "begins with a line comprising \"-----BEGIN \", a label, and \"-----\", and ends with a line
 comprising \"-----END \", a label, and \"-----\"", and "Data before the encapsulation boundaries are permitted". A block with
-no END line was read as bare base64, and the regex rescanned the rest of the value from every BEGIN line.
+no END line was read as bare base64, and the regex rescanned the rest of the value from every BEGIN line. A boundary is a
+line, so a sentence that quotes one is text outside the blocks, as OpenSSL reads it; an END line with no open BEGIN is
+refused, because OpenSSL skips the body above it and drops that certificate without a word.
 
 The functions are imported inside each test, so that this file also runs on main and shows each failure there.
 """
@@ -24,6 +26,8 @@
 
 import pytest
 
+from test_crc_reader_import_398 import CA            # a real certificate, of a synthetic CA
+
 # ---------------------------------------------------------------- #583 If-None-Match
 
 
@@ -74,6 +78,20 @@
     assert starred.status_code == 200 and starred.headers["etag"] == etag
 
 
+@pytest.mark.parametrize("path", ["/api/v1/metadata-keys", "/api/v1/capacity"])
+def test_an_authenticated_read_joins_the_if_none_match_lines(world, path):
+    """The two other callers (routers/me.py, plugins/capacity/router.py): the stale tag on the first line must not hide
+    the current one on the second (section 5.3). Reading only the first line answers 200 here."""
+    from test_flow import OLA, auth
+    client, *_, keys = world
+    credentials = auth(keys, "ola", **OLA)
+    first = client.get(path, headers=credentials)
+    assert first.status_code == 200, first.text
+    etag = first.headers["etag"]
+    two_lines = client.get(path, headers=[*credentials.items(), ("If-None-Match", '"older"'), ("If-None-Match", etag)])
+    assert (two_lines.status_code, two_lines.content, two_lines.headers["etag"]) == (304, b"", etag)
+
+
 # ---------------------------------------------------------------- #584 the namespace ETag
 
 NS = {"namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: payments-dev\n"}
@@ -92,6 +110,15 @@
     assert folder_etag({"a.yaml": "x\0b.yaml\0y"}) != folder_etag({"a.yaml": "x", "b.yaml": "y"})
 
 
+def test_two_exceptional_folders_differ_by_content_and_not_by_order():
+    """Both folders take the JSON encoding: its tag still follows each path and content, and not the order of the files."""
+    from cmapi.core.pipeline import folder_etag
+    folder = {"a.yaml": "x\0", "b.yaml": "<deleted>"}
+    assert folder_etag(folder) != folder_etag({**folder, "a.yaml": "y\0"})
+    assert folder_etag(folder) != folder_etag({"a.yaml": "x\0", "c.yaml": "<deleted>"})
+    assert folder_etag(folder) == folder_etag(dict(reversed(folder.items())))
+
+
 @pytest.mark.parametrize("files, tag", [
     (NS, "809899d2a47c256a"),
     ({**NS, "extra.yaml": ""}, "593d77cc82483bd9"),
@@ -120,6 +147,14 @@
     (BEGIN + "Y Q = =\n" + END, True),                             # whitespace inside the body is ignored, as before
     (BEGIN + "YQ=\n" + END, False),                                # not base64
     (BEGIN + END, False),                                          # an empty block
+    (BEGIN + "YQ==\n" + END + "Example: " + BEGIN, True),          # a sentence that quotes a boundary is text
+    ("Example: " + BEGIN + BEGIN + "YQ==\n" + END, True),
+    (BEGIN + "YQ==\n" + END + "A block ends with " + END, True),
+    (BEGIN.replace("\n", " \t\n") + "YQ==\n" + END.replace("\n", "\t \n"), True),  # SP and HTAB after a boundary
+    (END + BEGIN + "YQ==\n" + END, False),                         # an END line with no open BEGIN, before a block
+    (BEGIN + "YQ==\n" + END + END, False),                         # after a block
+    (BEGIN + "YQ==\n" + END + "YWI=\n" + END, False),             # a block whose BEGIN line was lost
+    (BEGIN + "YQ==\n" + BEGIN + "YWI=\n" + END, False),           # a BEGIN inside an open block
 ])
 def test_ca_data_needs_complete_blocks(ca_data, valid):
     from cmapi.core.registry import _valid_ca_data
@@ -129,8 +164,8 @@
 def test_a_large_malformed_bundle_is_read_in_linear_time():
     """#585: 2,000 BEGIN lines and no END line, 186 kB, inside a Secret's 1 MiB (https://kubernetes.io/docs/concepts/
     configuration/secret/, "Individual Secrets are limited to 1MiB in size", read 2026-11-23). The regex took 4.4 s of CPU
-    on main, under the registry's refresh lock; the boundary scan takes about 1 ms. CPU time of this process, not wall time,
-    so a busy runner does not inflate it; the bound leaves the linear scan a margin of over 100 times and is under a tenth
+    on main, under the registry's refresh lock; the line scan takes about 3 ms. CPU time of this process, not wall time,
+    so a busy runner does not inflate it; the bound leaves the linear scan a margin of over 80 times and is under a tenth
     of the quadratic one."""
     from cmapi.core.registry import _valid_ca_data
     ca_data = (BEGIN + "QUFB" * 16 + "\n") * 2000
@@ -138,3 +173,36 @@
     valid = _valid_ca_data(ca_data)
     assert time.process_time() - start < 0.25, "the caData check is no longer linear in the length of the value"
     assert not valid, "no block is closed"
+
+
+def _registry_check(ca_data):
+    """The registry's check of an import Secret, with a client that builds its SSL context as the real one does
+    (Trust.verify, core/clients/trust.py): what OpenSSL loads is what counts, not the encoding alone."""
+    from cmapi.core.registry import ClusterPolicy, ClusterRegistry
+    from test_registry_ca_bundle import Reader
+
+    def client(cluster_id, api_url, token, trust, insecure=False):
+        trust.verify()                       # ssl.SSLError when no certificate loads
+        return Reader()
+
+    policy = ClusterPolicy(cluster_id="CRC", environment="dev", gitops_path="clusters/CRC", writes=False)
+    registry = ClusterRegistry({"CRC": policy}, None, client_factory=client, start_caches=False)
+    secret = {"data": {"apiUrl": "https://kubernetes.default.svc", "token": "t", "caData": ca_data}, "annotations": {}}
+    st = registry._check(registry.get("CRC"), secret)
+    return st.status, st.findings
+
+
+@pytest.mark.parametrize("ca_data", [
+    CA,
+    CA + "Example: " + BEGIN,
+    "Example: " + BEGIN + CA,
+    CA + BEGIN.strip() + " opens a block\n",
+], ids=["certificate", "a-quote-after", "a-quote-before", "a-boundary-in-a-sentence"])
+def test_a_certificate_with_text_that_quotes_a_boundary_connects(ca_data):
+    """OpenSSL loads the certificate and skips the text: so must the check, or a valid import turns invalid-secret."""
+    assert _registry_check(ca_data) == ("connected", [])
+
+
+def test_a_certificate_that_lost_its_begin_line_is_refused():
+    """OpenSSL would load the first certificate and skip the second's body without a word: its END line has no BEGIN."""
+    assert _registry_check(CA + CA.replace(BEGIN, "")) == ("invalid-secret", ["invalid caData"])
--- a/docs/02-technical-design-v2.md
+++ b/docs/02-technical-design-v2.md
@@ -772,7 +772,7 @@
 
 `tlsServerName`, in any mode, is the name sent in SNI and checked against the certificate instead of the host of `apiUrl` (RFC 9525: the reference identity comes from the client's configuration, never from the server). It never changes what is trusted. It is set on each request (httpcore's `sni_hostname`) and, in a mode that verifies, in the SSL context itself, so it also holds through an HTTP proxy (`HTTPS_PROXY`), whose tunnel ignores the request's name. One root dot (`api.example.com.`) is dropped before use. `CMAPI_CA_BUNDLE` is Keycloak's trust and is not a cluster's (the owner's decision D4, #434). The flag that trusts a cluster's certificate is `insecure`, skip verification, as in Kubernetes (D1): pinning on first contact and an operator-given root fingerprint were weighed and not chosen (analysis section 3). Any environment may allow it, prod included, by configuration; none does by default (D2).
 
-Refused, as `invalid-secret` before any client is built, so the token is never sent: caData together with insecure: "true" (finding `insecure with caData`; client-go refuses the same); `insecure` in an environment whose setting does not allow it (finding `insecure is not allowed for environment <env>: instance.clusterTLS.environments.<env>.insecureSkipTLSVerify is false`); an `insecure` other than `"true"` or `"false"` (finding `insecure is "true" or "false"`); a `tlsServerName` that is not a DNS name or an IP address (finding `tlsServerName is not a DNS name or an IP address`); a caData with a `BEGIN CERTIFICATE` line that no `END CERTIFICATE` line follows, with an `END` line and no `BEGIN` line, or whose certificate blocks are not valid base64 (finding `invalid caData`; `_valid_ca_data` reads the value once, in linear time, decodes each block and does not parse the certificate, #585) or whose blocks are valid base64 and no certificate (finding `invalid caData: <the TLS error>`, when the client loads it, #419); an apiUrl that is not https; and a Secret with no apiUrl or no token (finding `missing field <name>`). The finding is a sentence, not a code. A certificate failure has the status `cert-verify-failed`, and the finding names the trust store: `; trust store: caData` or `; trust store: trusted (the system store and CMAPI_TRUSTED_CA_FILE)`. A bundle of `CMAPI_TRUSTED_CA_FILE` that is there and does not load is the same status, with a finding that names the file. One that is not there is skipped and read again at the next check, because OpenShift fills the injected ConfigMap after the pods start. caData is loaded in memory, never written to a file. Each change of a cluster's mode logs `cluster_tls_mode` once (a warning when insecure takes effect, and once when it is cleared), and `cmapi_cluster_tls_insecure{cluster_id}` is 1 while a cluster is read insecure. **Not built (#396):** the expiry of the server's certificate and of caData (the owner's decision D6), and the fix for each mode in the message.
+Refused, as `invalid-secret` before any client is built, so the token is never sent: caData together with insecure: "true" (finding `insecure with caData`; client-go refuses the same); `insecure` in an environment whose setting does not allow it (finding `insecure is not allowed for environment <env>: instance.clusterTLS.environments.<env>.insecureSkipTLSVerify is false`); an `insecure` other than `"true"` or `"false"` (finding `insecure is "true" or "false"`); a `tlsServerName` that is not a DNS name or an IP address (finding `tlsServerName is not a DNS name or an IP address`); a caData with an unmatched `BEGIN CERTIFICATE` or `END CERTIFICATE` boundary line, or whose certificate blocks are not valid base64 (finding `invalid caData`; `_valid_ca_data` reads the boundaries as whole lines, as RFC 7468 and OpenSSL do, so text outside the blocks that quotes one is ignored; it runs in linear time, decodes each block and does not parse the certificate, #585) or whose blocks are valid base64 and no certificate (finding `invalid caData: <the TLS error>`, when the client loads it, #419); an apiUrl that is not https; and a Secret with no apiUrl or no token (finding `missing field <name>`). The finding is a sentence, not a code. A certificate failure has the status `cert-verify-failed`, and the finding names the trust store: `; trust store: caData` or `; trust store: trusted (the system store and CMAPI_TRUSTED_CA_FILE)`. A bundle of `CMAPI_TRUSTED_CA_FILE` that is there and does not load is the same status, with a finding that names the file. One that is not there is skipped and read again at the next check, because OpenShift fills the injected ConfigMap after the pods start. caData is loaded in memory, never written to a file. Each change of a cluster's mode logs `cluster_tls_mode` once (a warning when insecure takes effect, and once when it is cleared), and `cmapi_cluster_tls_insecure{cluster_id}` is 1 while a cluster is read insecure. **Not built (#396):** the expiry of the server's certificate and of caData (the owner's decision D6), and the fix for each mode in the message.
 
 **Client rules.** Every per-cluster call follows these:
 
```
