# PR #599 · reviewer 2 (Opus 5.5 high) · head 3f4843b (head2)

I copied head2 to `/Users/olasumbo/gitRepos/workbench/cmapi/review-599/r2/`, applied my fix there, and used `/Users/olasumbo/gitRepos/workbench/cmapi/review-599/r2-work/` for scratch work. I touched no git repository,
pushed nothing, and wrote nothing to CRC, LDAP or Keycloak.

## Rulings at a glance

| # | Finding (reviewer 1) | Ruling | Action |
|---|---|---|---|
| 1 | caData: a non-ASCII line inside a sibling `X509 CERTIFICATE` block is dropped, so a corrupted certificate loads and the cluster reports `connected` | **Confirmed on head2.** Fix before merging | Fixed in `fix.diff`. Codex's diagnosis is accepted; its patch is restructured (see 1.3) |
| 2 | Stand-in create key omits cluster and defaults; policy runs before replay | Real difference, but outside what the portal sends | No change, no issue (see 2) |
| 3 | Stand-in PATCH replay needs the current row; quota PATCH hashes top-level nulls | Same | No change, no issue |
| 4 | Stand-in extend fingerprints `until` alongside `days` | Same: the portal's extend body is `{days}` only | No change, no issue |
| 5 | Stand-in tag grammar and problem details | **Out of date on head2 for NBSP: retracted by measurement.** The tag-list and missing-quote differences remain, but the portal never sends them | No change. Codex's precondition regex would now be **wrong** and must not be applied |
| 6 | Key length, 24 h lifetime, `dryRun` parsing, conflict `title` | Outside what the portal sends or reads | No change, no issue |
| 7 | Stand-in has no DELETE replay (predates the PR) | The portal never calls DELETE | No change, no issue. A related **API** defect was found and is issue A below |
| 8 | Docs text | Confirmed, with the four corrections from the brief | Final text in `r2-outputs/LIVE-DOC-EDITS.md`, plus a docs/02:775 edit that reviewer 1 missed |
| 9 | Surviving mutants | Confirmed: 2 CA mutants and 2 Node mutants survived | Tests added. All 8 CA mutants and 6 Node mutants are now killed |

## 1. #591: production finding

### 1.1 Reproduction on head2

Script: `/Users/olasumbo/gitRepos/workbench/cmapi/review-599/r2-work/repro1.py`. It uses two distinct synthetic CAs, with the line `Issuer: Zürich` inserted into the second
CA's body. Command: `python -I repro1.py ../head2`. OpenSSL 3.6.4.

```
[X509 CERTIFICATE] registry: ('connected', [], 2) | direct ca_data_context: ('ok', 2) | OpenSSL cafile of UTF-8: ('SSLError', '[X509] PEM lib (_ssl.c:4106)')
[CERTIFICATE]      registry: ('invalid-secret', ['invalid caData'], None) | direct ca_data_context: ('ok', 2) | OpenSSL cafile of UTF-8: ('SSLError', ...)
```

The import reports `connected` with 2 anchors, while OpenSSL refuses the same bytes as a file. The direct loader repairs
both labels. Same script on the fix (`../r2`):

```
[X509 CERTIFICATE] registry: ('invalid-secret', ['invalid caData'], None) | direct ca_data_context: ('ok', 1) | OpenSSL cafile: SSLError
[CERTIFICATE]      registry: ('invalid-secret', ['invalid caData'], None) | direct ca_data_context: ('ok', 1) | OpenSSL cafile: SSLError
[comment-before] ('connected', [], 1)   [two distinct] ('connected', [], 2)   [x509 sibling] ('connected', [], 2)
```

The direct loader now holds only the intact first CA. The corrupted second CA is never an anchor.

### 1.2 The rule, and the sources behind it

OpenSSL 3.6 sources, fetched 2026-11-23:
- `crypto/evp/encode.c`, `conv_ascii2bin`: `if (a & 0x80) return B64_ERROR;`. In `data_ascii2bin`, index 0x3F (`?`) is `0xFF`
  (B64_ERROR) and 0x2D (`-`) is `0xF2` (B64_EOF). `EVP_DecodeUpdate` returns -1 on B64_ERROR.
- `crypto/pem/pem_lib.c`, `check_pem`: `if (strcmp(nm, PEM_STRING_X509_OLD) == 0 && strcmp(name, PEM_STRING_X509) == 0) return 1;`.
  So `PEM_read_bio_X509`, CPython's cadata loader, takes `CERTIFICATE` and `X509 CERTIFICATE`. It skips `TRUSTED CERTIFICATE`
  (measured: corpus case 9 loads only the X509 block via cadata, while the file loader loads both). `get_header_and_data` ends a
  block at the END line of its own name, or fails with `PEM_R_BAD_END_LINE`.
- `PEM_read_bio` passes `PEM_FLAG_EAY_COMPATIBLE`, whose `sanitize_line` "Strip[s] trailing whitespace" with
  `linebuf[len] <= ' '` on a `char`. On a signed-char build such as x86-64, trailing high bytes are stripped too, so OpenSSL's
  file reading of a trailing NBSP depends on the platform. Our rule is stricter than either build, which is the safe direction.

**The rule implemented:**
- **Loader** (`trust.py:95-108`): each character that is not ASCII becomes `?`. `?` is never a boundary, never base64 and never
  whitespace. Outside a block, OpenSSL skips it as explanatory text. Inside any block, decoding fails. So the loader can never
  repair a certificate by leaving a line out, and it keeps every physical line, including a lone CR. An ASCII value is
  unchanged, and the spy test still passes.
- **Validator** (`registry.py:61-64, 295-331`): one parser, now for both labels, through `PEM_BLOCKS`. A BEGIN of either label
  needs the END of the same label. Every body is checked with the existing `decodes`, which already refuses non-ASCII. A
  non-ASCII line inside a block of either label is `invalid caData` before any client is made. Non-ASCII text outside the
  blocks is ignored, as before.

The validator also needs both labels for another reason, measured in `/Users/olasumbo/gitRepos/workbench/cmapi/review-599/r2-work/probe2.py`. CPython's cadata loader **silently
stops** at a corrupted later block when the corruption contains a `:` (it looks like a PEM header). For example,
`'Issuer: Z?rich'` inside the second block, with the good block first, gives `('ok', 1)`, not SSLError. The same happens with
pure ASCII (`'Issuer: Zurich'`). So without validating X509 bodies, the registry would report `connected` with an anchor
silently missing. Fewer anchors is the safe direction, but the import would still report `connected`.

### 1.3 Review of `reviewer1/591.patch`

Kept: refusing both labels, keeping every line through ASCII replacement, the two-distinct-CA test, and the bare-base64 NBSP test.

Changed:
1. **Its two parsers can drift.** `ascii_certificate_bodies` (`_LINE`, `.rstrip("\r\n").rstrip(" \t")`) would sit beside the
   validator's own `re.split` parser. I extended the one existing parser instead.
2. **Its in-loader check and hand-built `ssl.SSLError("non-ASCII certificate body")` are redundant.** After the `?`
   replacement, the loader cannot repair anything. `ca_data_context` has one production caller, `Trust.verify`, and the only
   caData `Trust` is built in `registry.import_trust` after `_valid_ca_data` (`registry.py:433`).
3. **It checks X509 bodies for non-ASCII only**, so ASCII corruption in an X509 block still reaches the silent-stop path above.
4. **Its test `test_internal_comment_refused` asserts `ca_data_context` raises SSLError.** That holds only because of item 2. My
   test asserts what is true with or without it: the corrupted CA is never among `get_ca_certs()`.

### 1.4 Tests (all in `cmapi/tests/service/test_ca_data_non_ascii_591.py`)

- `test_two_distinct_certificates_beside_such_text_are_both_anchors` (line 93) kills **drop-second-standard**.
- `test_bare_base64_with_a_no_break_space_is_invalid_ca_data` (line 140) kills **bare-unchecked**.
- `test_text_that_is_not_ascii_inside_either_label_is_never_repaired`, 2 labels × {own-line, mixed-line, end-of-line} (line 112).
- `test_a_block_closed_by_the_other_label_is_invalid_ca_data`, both ways (line 134).

New tests on head2's code (`r2-work/before-newtests`), **5 fail**:
```
FAILED tests/service/test_ca_data_non_ascii_591.py::test_text_that_is_not_ascii_inside_either_label_is_never_repaired[CERTIFICATE-own-line]
FAILED tests/service/test_ca_data_non_ascii_591.py::test_text_that_is_not_ascii_inside_either_label_is_never_repaired[CERTIFICATE-mixed-line]
FAILED tests/service/test_ca_data_non_ascii_591.py::test_text_that_is_not_ascii_inside_either_label_is_never_repaired[X509 CERTIFICATE-own-line]
FAILED tests/service/test_ca_data_non_ascii_591.py::test_text_that_is_not_ascii_inside_either_label_is_never_repaired[X509 CERTIFICATE-mixed-line]
FAILED tests/service/test_ca_data_non_ascii_591.py::test_text_that_is_not_ascii_inside_either_label_is_never_repaired[X509 CERTIFICATE-end-of-line]
5 failed, 15 passed in 0.45s
```

The mutants (`r2-work/mutate.py`) each run in a full copy of `r2/cmapi`, because `pyproject.toml` sets `pythonpath`:
```
drop-second-standard: KILLED -- 1 failed, 19 passed in 0.35s
bare-unchecked: KILLED -- 1 failed, 19 passed in 0.37s
head2-line-dropping-loader: KILLED -- 4 failed, 16 passed in 0.39s
validator-certificate-label-only: KILLED -- 3 failed, 17 passed in 0.39s
replace-with-space: KILLED -- 2 failed, 18 passed in 0.34s
replace-with-nothing: KILLED -- 2 failed, 18 passed in 0.34s
no-conversion: KILLED -- 13 failed, 7 passed in 0.52s
end-label-not-matched: KILLED -- 2 failed, 18 passed in 0.37s
```

### 1.5 Measured compatibility: corpus of 4000 inputs (`r2-work/corpus.py`, `compare2.py`, `compare3.py`)

The corpus covers CA, second CA, X509 label, TRUSTED label, bare and empty values. It inserts non-ASCII, `\v`, boundary,
`?`, `TQ==` and `Issuer:` pieces, with LF, CRLF and CR line ends. A *repair* is an anchor that OpenSSL does not load from the
UTF-8 file and whose base64 body is not intact in the input.
```
{
 "inputs": 4000,
 "head2: connects": 1881,
 "head2: connects with a repaired anchor": 11,
 "fix: connects": 1736,
 "fix: connects with a repaired anchor": 0,
 "validation lost": 357,
 "validation gained": 109
}
head2 connected with intact anchors, fix does not: {'X509 block with CR-only line ends': 53, 'END line with no open BEGIN of its label': 144, 'other': 64}
{
 "head2: OpenSSL's file load succeeds, the import does not connect": 505,
 "head2:   ...of which the value is ASCII": 143,
 "head2:   ...of which a stray END X509 CERTIFICATE line": 228,
 "fix: OpenSSL's file load succeeds, the import does not connect": 558,
 "fix:   ...of which the value is ASCII": 116,
 "fix:   ...of which a stray END X509 CERTIFICATE line": 219
}
```

- **Repairs: head2 11, fix 0.**
- **Validation lost: 357.** Each lost case falls in one of these groups:
  - a stray `-----END X509 CERTIFICATE-----` with no open block. #585 already refuses that for `CERTIFICATE`.
  - an X509 block with lone-CR line ends. RFC 7468 counts CR as a line end; OpenSSL reads only LF, so to OpenSSL it is one line of
    text.
  - non-ASCII inside a `TRUSTED CERTIFICATE` block, which head2's line dropping repaired and `?` now refuses.
  - head2 un-gluing a `text\r-----BEGIN` line that OpenSSL never reads as a boundary.
- **Validation gained: 109**, mostly X509 blocks now validated as blocks rather than through the bare-base64 fallback.
- **Values OpenSSL's file load accepts but the import refuses: head2 505, fix 558.** For ASCII values only, 143 before and
  116 after. The validator was already stricter than OpenSSL (#585). The 53 added refusals are the malformed groups above.

Not handled, and the same before and after: a UTF-8 BOM before the first BEGIN. OpenSSL strips it on the first line; the
validator refuses it. Base raised TypeError on it.

## 2. Stand-in parity (findings 2-7)

The stand-in's header says each stand-in "keeps the rules of the real service that the portal must follow"
(`standin.mjs:2`). What the portal sends, measured from `cmapi-portal-ui/src`:
- **A new `crypto.randomUUID()` key whenever the request or change changes**: `NewNamespaceTab.tsx:204`, `NamespacesTab.tsx:197`,
  `ExpirationTab.tsx:337`, `QuotasTab.tsx:513, 673`. So a key is never reused with another body or cluster (findings 2, 3 and 4),
  and keys are 36 characters (finding 6).
- **If-Match is always the GET's etag in quotes** (`ifMatchOf`, `hooks.ts:450`), never `*`, empty, a list or a broken quote
  (finding 5).
- **The dry run is `query: { dryRun: true }`** (`hooks.ts:227, 467, 621`), never `1` or `yes` (finding 6).
- **No DELETE call anywhere in `src/`** (finding 7).
- **`problemOf` reads `code` and `detail`, not `title`** (`problem.ts:61-63`; finding 6).
- The portal's own tests rely on these paths: `direct.test.mjs:782-802` (409, 412 and replay with `justification: null` on the
  metadata path, which head2 already filters) and `portal.test.mjs:782-808` (R1: a changed form gets a new key).

**Ruling.** Changing the stand-in for inputs no client sends would be over-building, so findings 2, 3, 4, 6 and 7 get no change
and no issue. A two-line comment at `standin.mjs:963-964` records this scope where the next reviewer will read it.

**Finding 5, re-measured on head2.** `require_if_match` now uses `.strip(" \t")` (`pipeline.py:131`). On the API's real
functions:
- `"\xa0*\xa0"` gives 412 on a first write and passes on a replay.
- `'"abc'` gives 412.
- `'W/"a,b", "abc"'` passes.

The head2 stand-in (`r2-work/nbsp.mjs`):
```
first write " * " 412
first write "\"db692281b93eda30" 202
first write "W/\"a,b\", \"db692281b93eda30\"" 412
submit 202 replay with NBSP star 202
```

- **NBSP-star now matches the API (412, then 202).** I retract that part of finding 5: head2 refutes it.
- Codex's patch regex `[\x09-\x0d\x1c-\x20\x85\xa0]` would now give **428** for NBSP-star, which is **wrong** on head2.
- The missing-quote difference (stand-in 202, API 412) and the tag-list difference (stand-in 412, API 202) remain, for inputs
  the portal never sends.

**What I kept from `standin.patch`:** only the test strengthening (finding 9). Its handler rewrite, DELETE route, key-age,
dryRun parser, title and CORS changes are not taken.

## 3. Finding 8: docs (final text in `r2-outputs/LIVE-DOC-EDITS.md`, given in full below)

- The citation is `views.py:17-18`.
- The claim is that successful writes omit `Location`, not "no Location anywhere". Measured in-process: a trailing-slash POST
  gets `307 http://testserver/api/v1/clusters/CRC/namespaces`.
- DELETE has no dry run. The contract's DELETE parameters are `cluster_id, ns, Idempotency-Key, If-Match`.
- The probe returns diagnostics and changes nothing (`me.py:91-97`).
- RFC 9110 §15.3.3 and §10.2.2 are quoted from the RFC text, fetched 2026-11-23.

`r2-work/docs_check.py` checks the text against head2's contract, source and in-process app. The proposal fails it (assertion
on `views.py:15-16`). The final text passes:
```
POST /api/v1/admin/auto-approval:pause [('200', 'SwitchView')] False
POST /api/v1/admin/auto-approval:resume [('200', 'SwitchView')] False
POST /api/v1/admin/prune:confirm [('200', 'ChangeRequest')] False
POST /api/v1/clusters/{cluster_id}/namespaces [('200', 'PlanView'), ('202', 'ChangeRequest')] True
DELETE /api/v1/clusters/{cluster_id}/namespaces/{ns} [('202', 'ChangeRequest')] False
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} [('200', 'PlanView'), ('202', 'ChangeRequest')] True
POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:extend [('200', 'PlanView'), ('202', 'ChangeRequest')] True
POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:makePermanent [('200', 'PlanView'), ('202', 'ChangeRequest')] True
POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:set [('200', 'PlanView'), ('202', 'ChangeRequest')] True
POST /api/v1/clusters/{id}:probe [('200', 'ClusterView')] False
POST /api/v1/requests/{request_id}:approve [('200', 'ChangeRequest')] False
POST /api/v1/requests/{request_id}:cancel [('200', 'ChangeRequest')] False
POST /api/v1/requests/{request_id}:reject [('200', 'ChangeRequest')] False
POST /api/v1/requests/{request_id}:retry [('200', 'ChangeRequest')] False
POST /api/v1/requests/{request_id}:revert [('200', 'ChangeRequest')] False
write operations: 15
'Location' in service source at: ['cmapi/src/cmapi/core/cors.py:31']
trailing-slash POST: 307 http://testserver/api/v1/clusters/CRC/namespaces
02-technical-design-v2.md 128 old matches the export; new row checked
01-design-and-architecture.md 730 old matches the export; new row checked
ALL CHECKS PASSED
```

**Reviewer 1 missed:** docs/02:775 describes `_valid_ca_data` as checking only `BEGIN/END CERTIFICATE`, and no doc mentions
#591 at all. Section 3 of the final file gives the exact old and new substring; it occurs once in the file.

## 4. Finding 9: test quality

`standin.test.mjs`:
- `replays()` now compares the whole body.
- The create test uses the API's `PrView` object (`models.py:140-144`) instead of `pr: 42`, and compares the whole body.
- A new test checks that a first write with `*` or `" \t*\t "` gets 428, and empty gets 412, on the quota, metadata and expiry
  paths, with no key held.

The Node mutants (`r2-work/nodemut.py`). The first-write mutant is now anchored to 6-space lines only: Codex's string replace
also matched the 8-space replay lines, so it mutated the replays too.
```
PR tests (head2):
old-view KILLED ['ℹ pass 1', 'ℹ fail 4']
wrong-links SURVIVED ['ℹ pass 5', 'ℹ fail 0']
old-first-match SURVIVED ['ℹ pass 5', 'ℹ fail 0']
old-print KILLED ['ℹ pass 4', 'ℹ fail 1']
old-409 KILLED ['ℹ pass 4', 'ℹ fail 1']
old-wildcard KILLED ['ℹ pass 2', 'ℹ fail 3']
With the r2 tests:
old-view KILLED ['ℹ pass 2', 'ℹ fail 4']
wrong-links KILLED ['ℹ pass 2', 'ℹ fail 4']
old-first-match KILLED ['ℹ pass 5', 'ℹ fail 1']
old-print KILLED ['ℹ pass 5', 'ℹ fail 1']
old-409 KILLED ['ℹ pass 5', 'ℹ fail 1']
old-wildcard KILLED ['ℹ pass 2', 'ℹ fail 4']
```

The new tests pass on head2's stand-in (6/6), as expected: they catch regressions and do not reproduce a defect.

## 5. Issue text for the coordinator to file

**Issue A: `DELETE /clusters/{id}/namespaces/{ns}?dryRun=true` opens a real delete request**
(found by reviewer 2 on #599; parent #594)

- **What is wrong.** The DELETE route declares no `dryRun` parameter (`plugins/namespaces/router.py:336-351`; the contract lists
  `cluster_id, ns, Idempotency-Key, If-Match`), and FastAPI ignores undeclared query parameters. A client that sends
  `?dryRun=true` expecting a preview, as docs/02:129 ("Dry run | ?dryRun=true returns 200 with the Plan") suggests for writes,
  gets a real delete request. Where a policy auto-approves deletes, that request goes ahead.
- **Proof, measured on head2.** Scratch test `r2-work/before-newtests/cmapi/tests/service/test_r2_probe_delete_dryrun.py`:
  ```
DELETE ?dryRun=true -> 202 {'requestId': 'req-20261123-0002', 'action': 'delete', 'status': 'pending_approval'}
requests now: [('delete', 'pending_approval'), ('create', 'synced')]
1 passed in 3.57s
  ```
- **Research mandate.** Fetch and quote how others treat dry run on DELETE: Kubernetes API conventions (`dryRun=All` is
  supported on DELETE), Google AIP-163 (`validate_only`), and RFC 9110 on unknown query parameters. Then choose one:
  - refuse `dryRun` on DELETE with 422 `validation-failed`, smallest and safe;
  - or implement a delete plan with `dry_run_model=PlanView`.
  Update docs/02:129 in the same pull request.
- **Test.** DELETE with `?dryRun=true` either returns 200 PlanView and opens no row, or returns 422 and opens no row. It fails on
  head2 (202, `req-…`, `pending_approval`).

No other issues: findings 2-7 are ruled out of scope above.

## 6. Test outputs

Command shape: `cd <tree>/cmapi && CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/<db> PYTHONPATH=src:tests/service
<venv>/python -m pytest <files> -q -W ignore -p no:cacheprovider`. Runner: `/Users/olasumbo/gitRepos/workbench/cmapi/review-599/r2-work/run-db.sh`. The databases are my own:
`cmapi_r2_599_before` and `cmapi_r2_599`.

The 32 database-backed cases Codex could not run are the 26 setup errors in group 1, the 1 in group 2 and the 5 in group 3.
All pass, before and after.

**Before (head2, pristine copy `r2-work/base-head2`):**
```
== before: tree /Users/olasumbo/gitRepos/workbench/cmapi/review-599/r2-work/base-head2, db cmapi_r2_599_before, 2026-11-23T16:19:52Z
== 1. if-match forms 571 + before replay 495
..................................................                       [100%]
50 passed in 52.78s
== 2. expirations one key
.                                                                        [100%]
1 passed in 3.48s
== 3. flow + review_a_concurrency -k 'idempotency_key_is or same_key'
tests/service/test_flow.py::test_an_idempotency_key_is_free_again_after_24_hours PASSED [ 20%]
tests/service/test_review_a_concurrency.py::test_same_key_same_body_in_parallel_returns_the_first_response PASSED [ 40%]
tests/service/test_review_a_concurrency.py::test_same_key_different_bodies_in_parallel_one_wins PASSED [ 60%]
tests/service/test_review_a_concurrency.py::test_idempotency_key_is_bound_to_the_cluster PASSED [ 80%]
tests/service/test_review_a_concurrency.py::test_long_idempotency_key_is_a_4xx_not_a_500 PASSED [100%]
======================= 5 passed, 28 deselected in 7.87s =======================
== 4. CA and validator files
........................................................................ [ 60%]
................................................                         [100%]
120 passed in 31.52s
== 5. node stand-in
✔ an expiry replay after a rejection answers the rejected request, and needs If-Match (20.410866ms)
✔ a namespace change replayed after a rejection answers the rejected request, and needs If-Match (7.791995ms)
✔ a quota change replayed after a rejection answers the rejected request, and needs If-Match (3.393548ms)
✔ a create replay answers the request as it is now; a create takes no If-Match (3.857088ms)
✔ an expiry replay with another justification is the same request, as the API's fingerprint leaves it out (1.573252ms)
ℹ tests 5
ℹ pass 5
ℹ fail 0
```

**After (r2 = head2 + fix.diff):**
```
== after: tree /Users/olasumbo/gitRepos/workbench/cmapi/review-599/r2, db cmapi_r2_599, 2026-11-23T16:21:45Z
== 1. if-match forms 571 + before replay 495
..................................................                       [100%]
50 passed in 46.72s
== 2. expirations one key
.                                                                        [100%]
1 passed in 2.76s
== 3. flow + review_a_concurrency -k 'idempotency_key_is or same_key'
tests/service/test_flow.py::test_an_idempotency_key_is_free_again_after_24_hours PASSED [ 20%]
tests/service/test_review_a_concurrency.py::test_same_key_same_body_in_parallel_returns_the_first_response PASSED [ 40%]
tests/service/test_review_a_concurrency.py::test_same_key_different_bodies_in_parallel_one_wins PASSED [ 60%]
tests/service/test_review_a_concurrency.py::test_idempotency_key_is_bound_to_the_cluster PASSED [ 80%]
tests/service/test_review_a_concurrency.py::test_long_idempotency_key_is_a_4xx_not_a_500 PASSED [100%]
======================= 5 passed, 28 deselected in 7.00s =======================
== 4. CA and validator files
........................................................................ [ 55%]
..........................................................               [100%]
130 passed in 29.93s
== 5. node stand-in
✔ an expiry replay after a rejection answers the rejected request, and needs If-Match (26.08406ms)
✔ a namespace change replayed after a rejection answers the rejected request, and needs If-Match (9.044942ms)
✔ a quota change replayed after a rejection answers the rejected request, and needs If-Match (5.262222ms)
✔ a create replay answers the request as it is now; a create takes no If-Match (5.282108ms)
✔ an expiry replay with another justification is the same request, as the API's fingerprint leaves it out (2.529623ms)
✔ a first write takes `*` as 428 and an empty If-Match as 412, on each write that needs one (8.528533ms)
ℹ tests 6
ℹ pass 6
ℹ fail 0
```

Also after: `test_registry_survives_419.py` and `test_cluster_trust_review_435.py`: 48 passed in 6.21s.
The CA group goes from 120 to 130 tests: the 10 new cases.

## 7. What I ran and did not run

**Ran:**
- the reproduction;
- the 4000-input corpus, on both trees;
- 8 CA mutants and 6 Node mutants;
- the doc check, including the in-process 307;
- the stand-in NBSP measurement;
- the targeted service files before and after, including all 32 database-backed cases;
- `node scripts/check-discipline.mjs` and `node ../scripts/build-portal.mjs --check`, both ok;
- `patch -p1` of `fix.diff` onto a fresh head2 copy, which leaves it identical to r2;
- the DELETE dryRun probe.

**Did not run:**
- the full service suite;
- the full `npm test`: there is no `node_modules` in the export, so `tsc`, the vite builds, `direct.test.mjs`, `portal.test.mjs`
  and the browser suites were not run. My only stand-in source change is a comment;
- ruff or mypy: neither is installed in the venv;
- anything on kind or CRC;
- an aarch64 (unsigned-char) OpenSSL.

**Disclosures:**
- While I worked, the full service suites of wt-592 (pid 90517) and then wt-590 (pid 8591) were running. I waited for the first to
  finish. I ran my targeted set during the second, on my own databases, because each run is under 2 minutes.
- My early CA-only runs used the default database URL (`/cmapi`). They took the session advisory lock for under a second and
  truncated nothing, because the CA tests use no `fresh_db`. After that I used my own databases.
- One stray scratch copy went to `/tmp/x`, and I deleted it at once.

## 8. Full patch: `r2-outputs/fix.diff` (against head2 3f4843b, `patch -p1` from the repo root)

```diff
--- a/cmapi/src/cmapi/core/clients/trust.py
+++ b/cmapi/src/cmapi/core/clients/trust.py
@@ -28,8 +28,6 @@
 TRUSTED_CA_ENV = "CMAPI_TRUSTED_CA_FILE"
 # RFC 1123 host names: labels of letters, digits and hyphens, neither first nor last a hyphen; at most 253 characters.
 _LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")
-# A line with its end, CRLF, CR or LF (RFC 7468 section 3), as the registry's caData check splits it; the last may have none.
-_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
 
 
 class TrustBundleError(OSError):
@@ -94,20 +92,20 @@
     return ctx
 
 
-def _ascii_lines(ca_data: str) -> str:
-    """caData as Python's loader takes it: "an ASCII string of one or more PEM-encoded certificates" (the ssl docs), since a
-    bytes value is read as DER. A line that is not ASCII, such as an issuer's name above a certificate (RFC 7468 section 5.2's
-    explanatory text), raised TypeError (#591); OpenSSL and client-go skip such text, so that line is left out. The registry
-    has refused a value with one inside a CERTIFICATE block, so no certificate line is lost. An ASCII value is unchanged."""
-    if ca_data.isascii():
-        return ca_data
-    return "".join(line for line in _LINE.findall(ca_data) if line.isascii())
+def _ascii(ca_data: str) -> str:
+    """caData as Python's loader takes it: "an ASCII string of one or more PEM-encoded certificates" (the ssl docs); a str that
+    is not ASCII raised TypeError (#591). Each character that is not ASCII becomes "?", so OpenSSL reads the value as it reads
+    the same file, line for line: "?" is no boundary, and EVP_DecodeUpdate refuses it as it refuses a byte with the high bit set
+    (OpenSSL 3.6 crypto/evp/encode.c, conv_ascii2bin and data_ascii2bin). Outside a block it is skipped, as explanatory text is
+    (RFC 7468 section 5.2); inside a block of any label, CERTIFICATE and X509 CERTIFICATE among them, the load fails, so no
+    certificate is repaired by leaving a line out. An ASCII value is unchanged."""
+    return ca_data.encode("ascii", "replace").decode("ascii")
 
 
 def ca_data_context(ca_data: str, server_name: str | None = None) -> ssl.SSLContext:
     """The caData of an import Secret as the only anchors, in memory. ssl.SSLError when it holds no certificate."""
     ctx = _client_context(server_name)
-    ctx.load_verify_locations(cadata=_ascii_lines(ca_data))
+    ctx.load_verify_locations(cadata=_ascii(ca_data))
     return ctx
 
 
--- a/cmapi/src/cmapi/core/registry.py
+++ b/cmapi/src/cmapi/core/registry.py
@@ -58,9 +58,10 @@
 # Kubernetes date-time annotations carry a full timestamp with an explicit offset.
 TOKEN_EXPIRY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?"
                           r"(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")
-# RFC 7468 section 2: a certificate's encapsulation boundaries; the base64 between them is the block's body.
-PEM_BEGIN = "-----BEGIN CERTIFICATE-----"
-PEM_END = "-----END CERTIFICATE-----"
+# RFC 7468 section 2: a certificate's encapsulation boundaries, each BEGIN line with its END; the base64 between them is the
+# block's body. The caData loader, OpenSSL's PEM_read_bio_X509, also takes the older label X509 CERTIFICATE (pem_lib.c,
+# check_pem: PEM_STRING_X509_OLD), so its body is checked too (#591).
+PEM_BLOCKS = {f"-----BEGIN {label}-----": f"-----END {label}-----" for label in ("CERTIFICATE", "X509 CERTIFICATE")}
 
 
 @dataclass
@@ -293,12 +294,12 @@
 
 def _valid_ca_data(ca_data: str) -> bool:
     """Each PEM block by itself: a service account's ca.crt is usually a bundle, and base64 padding may end any block, so
-    the blocks joined are not base64 even when each one is. A boundary is a whole line: PEM_BEGIN or PEM_END, then only SP
-    or HTAB (RFC 7468 sections 2 and 3, whose lines end in CRLF, CR or LF). Each BEGIN line needs an END line before the
-    next BEGIN, and each END line an open BEGIN (#585): OpenSSL refuses a block that is not closed. Other text before,
-    between and after the blocks is ignored, as RFC 7468 and OpenSSL allow, even a sentence that quotes a boundary, and text
-    that is not ASCII, which the client leaves out of the loader (#591). A value with no boundary line is read as bare base64,
-    as before; the client finds no certificate in it and says so (#419).
+    the blocks joined are not base64 even when each one is. A boundary is a whole line: a BEGIN or END line of PEM_BLOCKS,
+    then only SP or HTAB (RFC 7468 sections 2 and 3, whose lines end in CRLF, CR or LF). Each BEGIN line needs the END line
+    of its label before the next BEGIN, and each END line an open BEGIN of its label (#585): OpenSSL refuses a block that is
+    not closed. Other text before, between and after the blocks is ignored, as RFC 7468 and OpenSSL allow, even a sentence
+    that quotes a boundary, and text that is not ASCII, which the client hands the loader as "?" (#591). A value with no
+    boundary line is read as bare base64, as before; the client finds no certificate in it and says so (#419).
     One pass over the lines, in linear time: the regex this replaces rescanned the rest of the value from every BEGIN."""
     def decodes(lines: list[str]) -> bool:
         text = "".join(lines)
@@ -311,17 +312,18 @@
 
     lines = re.split(r"\r\n|\r|\n", ca_data)
     body: list[str] | None = None          # the lines of the open block; None outside a block
+    end: str | None = None                 # the END line the open block needs
     blocks = 0
     for line in lines:
         boundary = line.rstrip(" \t")
-        if boundary == PEM_BEGIN:
+        if boundary in PEM_BLOCKS:
             if body is not None:
                 return False               # a BEGIN inside an open block
-            body = []
-        elif boundary == PEM_END:
-            if body is None or not decodes(body):
-                return False               # an END with no open BEGIN, or a body that is not base64
-            body, blocks = None, blocks + 1
+            body, end = [], PEM_BLOCKS[boundary]
+        elif boundary in PEM_BLOCKS.values():
+            if body is None or boundary != end or not decodes(body):
+                return False               # an END with no open BEGIN of its label, or a body that is not base64
+            body, end, blocks = None, None, blocks + 1
         elif body is not None:
             body.append(line)
     if body is not None:
--- a/cmapi/tests/service/test_ca_data_non_ascii_591.py
+++ b/cmapi/tests/service/test_ca_data_non_ascii_591.py
@@ -8,7 +8,7 @@
 boundaries are permitted, and parsers MUST NOT malfunction when processing such data"; section 5.2: "Many tools are known to
 emit explanatory text before the BEGIN and after the END lines". OpenSSL and Go's x509.CertPool (client-go's) load such a
 value, and curl's Mozilla bundle has a title in UTF-8 (measured, recorded on the pull request). So the check loads it; a
-character that is not ASCII inside a CERTIFICATE block is still refused as `invalid caData`.
+character that is not ASCII inside a block, CERTIFICATE or X509 CERTIFICATE, is still refused as `invalid caData`.
 
 Each case goes through `ClusterRegistry._check_import` with a client factory that calls `Trust.verify()`, the real loader.
 """
@@ -74,8 +74,8 @@
 
 
 def test_an_x509_certificate_block_beside_such_text_still_loads():
-    """OpenSSL's PEM_read_bio_X509 also reads the older label `X509 CERTIFICATE`, and loads it today beside a CERTIFICATE
-    block. The loader keeps it: only the lines that are not ASCII are left out, never a block, so both CAs are anchors."""
+    """OpenSSL's PEM_read_bio_X509 also reads the older label `X509 CERTIFICATE` (check_pem, PEM_STRING_X509_OLD), and loads
+    it today beside a CERTIFICATE block. Text that is not ASCII outside both blocks is skipped, so both CAs are anchors."""
     old_label = _second_ca().replace("BEGIN CERTIFICATE", "BEGIN X509 CERTIFICATE").replace("END CERTIFICATE",
                                                                                               "END X509 CERTIFICATE")
     assert _check_import(CA + "# Issuer: CN=Zürich Root CA\n" + old_label) == ("connected", [], 2)
@@ -90,6 +90,58 @@
     assert _check_import("\n".join(lines)) == ("invalid-secret", ["invalid caData"], None)
 
 
+def test_two_distinct_certificates_beside_such_text_are_both_anchors():
+    """Two different CAs, so a loader that kept one block of two would count one."""
+    assert _check_import(CA + "# Zürich\n" + _second_ca()) == ("connected", [], 2)
+
+
+def _inside(cert: str, where: str) -> str:
+    """`cert` with text that is not ASCII in its body: a line of it, a mixed line, or the end of a base64 line."""
+    lines = cert.split("\n")
+    if where == "own-line":
+        lines.insert(2, "\u00a0")
+    elif where == "mixed-line":
+        lines.insert(2, "Issuer: Zürich")
+    else:
+        lines[2] += "\u00a0"
+    return "\n".join(lines)
+
+
+@pytest.mark.parametrize("where", ["own-line", "mixed-line", "end-of-line"])
+@pytest.mark.parametrize("label", ["CERTIFICATE", "X509 CERTIFICATE"])
+def test_text_that_is_not_ascii_inside_either_label_is_never_repaired(label, where):
+    """Beside one good CERTIFICATE block, a second CA, under either label the loader takes, with text that is not ASCII in its
+    body. Leaving that line out loaded a certificate that OpenSSL refuses from the same file, and the import said connected
+    (#599, reviewer 1). The import is now invalid caData, and the loader by itself never makes the second CA an anchor."""
+    import ssl
+
+    from cryptography import x509
+    from cryptography.hazmat.primitives.serialization import Encoding
+
+    from cmapi.core.clients.trust import ca_data_context
+
+    second = _second_ca()
+    bundle = CA + _inside(second.replace(" CERTIFICATE-----", f" {label}-----"), where)
+    assert _check_import(bundle) == ("invalid-secret", ["invalid caData"], None)
+    try:
+        anchors = ca_data_context(bundle).get_ca_certs(binary_form=True)
+    except ssl.SSLError:
+        anchors = []
+    assert x509.load_pem_x509_certificate(second.encode()).public_bytes(Encoding.DER) not in anchors
+
+
+@pytest.mark.parametrize("begin, end", [("CERTIFICATE", "X509 CERTIFICATE"), ("X509 CERTIFICATE", "CERTIFICATE")])
+def test_a_block_closed_by_the_other_label_is_invalid_ca_data(begin, end):
+    """OpenSSL needs the END line of the block's own label (pem_lib.c, get_header_and_data: PEM_R_BAD_END_LINE)."""
+    second = _second_ca().replace("BEGIN CERTIFICATE", f"BEGIN {begin}").replace("END CERTIFICATE", f"END {end}")
+    assert _check_import(CA + second) == ("invalid-secret", ["invalid caData"], None)
+
+
+def test_bare_base64_with_a_no_break_space_is_invalid_ca_data():
+    """A value with no boundary is read as bare base64: a no-break space in it is no base64, though str.split() drops it."""
+    assert _check_import("TQ\u00a0==") == ("invalid-secret", ["invalid caData"], None)
+
+
 def test_an_ascii_value_reaches_the_loader_unchanged(monkeypatch):
     """The fix leaves every ASCII caData exactly as it was: the same string reaches load_verify_locations."""
     import ssl
--- a/cmapi-portal-ui/tests/api/standin.mjs
+++ b/cmapi-portal-ui/tests/api/standin.mjs
@@ -960,6 +960,8 @@
       state.items = state.items.map((x) => (x === r ? next : x));
       return next;
     };
+    // The replays keep the API's rules for what the portal sends, as the header says: a new crypto.randomUUID key for each
+    // request or change (src/portal/*Tab.tsx), its etag in quotes as If-Match, dryRun=true, and no DELETE.
     // plugins/namespaces/router.py _replay: a replay answers request_view of the stored row, the request as it is now. The key
     // map holds the first object, and a decision replaces it in state.items, so the replay looks it up there (#595).
     const replayed = (held) => ok(find(held.request.requestId), 202);
--- a/cmapi-portal-ui/tests/api/standin.test.mjs
+++ b/cmapi-portal-ui/tests/api/standin.test.mjs
@@ -33,8 +33,7 @@
 async function replays(send, decided, tag) {
   const again = await send(tag);
   assert.equal(again.status, 202);
-  assert.equal(again.body.status, decided.status, "the request in its current state, not the first answer");
-  assert.deepEqual(again.body.events, decided.events);
+  assert.deepEqual(again.body, decided, "the whole request in its current state, not the first answer");
   for (const value of [undefined, "*", " \t*\t "]) {
     const answer = await send(value);
     assert.equal(answer.status, 428, `If-Match ${JSON.stringify(value)} on a replay`);
@@ -92,11 +91,13 @@
   const first = await send();
   assert.equal(first.status, 202, JSON.stringify(first.body));
   // The API moves an approved request on (the bot opens its pull request); the stand-in has no bot, so the test moves it.
-  const moved = { ...first.body, status: "pr_open", pr: 42 };
+  // ChangeRequest.pr is a PrView (cmapi/src/cmapi/core/models.py), not a number.
+  const moved = { ...first.body, status: "pr_open",
+    pr: { number: 42, url: "https://git.test/pulls/42", branch: "cmapi/CRC/orders-dev", head: "abcdef12" } };
   api.state.items = api.state.items.map((r) => (r.requestId === moved.requestId ? moved : r));
   const again = await send();
   assert.equal(again.status, 202);
-  assert.deepEqual([again.body.status, again.body.pr], ["pr_open", 42]);
+  assert.deepEqual(again.body, moved);
 });
 
 test("an expiry replay with another justification is the same request, as the API's fingerprint leaves it out", async () => {
@@ -116,3 +117,28 @@
   assert.equal(other.body.code, "idempotency-replay");
   assert.equal(other.body.requestId, first.body.requestId, "the 409 names the request that holds the key, as _replay's does");
 });
+
+test("a first write takes `*` as 428 and an empty If-Match as 412, on each write that needs one", async () => {
+  // check_if_match (core/pipeline.py): require_if_match refuses `*` first; an empty value then lists no strong tag, so 412.
+  const writes = {
+    quota: async () => ["PATCH", "/api/v1/clusters/CRC/namespaces/payments-dev", "requester", { tier: "large" }],
+    metadata: async (api) => {
+      api.state.namespaces = [namespaceRecord({ name: "abc-ledger-dev", prefix: "abc", team: "ledger", extraLabels: { "cmapi.net/protected": "true" } })];
+      return ["PATCH", "/api/v1/clusters/CRC/namespaces/abc-ledger-dev", "operator", { labels: { "cmapi.net/protected": null } }];
+    },
+    expiry: async (api) => {
+      api.state.expirations = [{ clusterId: "CRC", name: "notes-dev", env: "dev", expiresAt: "2027-01-01", openRequest: null }];
+      api.state.etags.set("CRC/notes-dev", "abc");
+      return ["POST", "/api/v1/clusters/CRC/namespaces/notes-dev/expiration:extend", "requester", { days: 7 }];
+    }
+  };
+  for (const [name, setUp] of Object.entries(writes)) {
+    for (const [ifMatch, status, code] of [["*", 428, "precondition-required"], [" \t*\t ", 428, "precondition-required"], ["", 412, "precondition-failed"]]) {
+      const api = standIn();
+      const [method, path, user, body] = await setUp(api);
+      const answer = await api.call(method, path, user, { body, key: `fresh-${name}`, ifMatch });
+      assert.deepEqual([answer.status, answer.body.code], [status, code], `${name}, If-Match ${JSON.stringify(ifMatch)}`);
+      assert.equal(api.state.keys.size, 0, "a refused first write holds no key");
+    }
+  }
+});
```

## 9. Final `r2-outputs/LIVE-DOC-EDITS.md`

````markdown
# Live-doc edits for #594 (not committed)

The coordinator applies these to the live Claude Docs first, then to the exports. Each "old" string is the export's line
exactly, as it stands on the PR head 3f4843b (unchanged from origin/main 61273d6).

## Why

The code, measured from the committed contract (`cmapi/contract/openapi.json` at 3f4843b, every POST, PUT, PATCH and DELETE
with its 2xx responses), on 2026-11-23:

| Write | 2xx |
| --- | --- |
| `POST /clusters/{cluster_id}/namespaces`, `PATCH /clusters/{cluster_id}/namespaces/{ns}` and the three `POST .../expiration:extend`, `:set`, `:makePermanent` | 202 ChangeRequest; with `dryRun=true`, 200 PlanView |
| `DELETE /clusters/{cluster_id}/namespaces/{ns}` | 202 ChangeRequest. No dry run: the route declares no `dryRun` parameter (its parameters are `cluster_id`, `ns`, `Idempotency-Key`, `If-Match`) |
| `POST /requests/{request_id}:approve`, `:reject`, `:cancel`, `:retry`, `:revert` | 200 ChangeRequest |
| `POST /admin/prune:confirm` | 200 ChangeRequest |
| `POST /admin/auto-approval:pause`, `:resume` | 200 SwitchView |
| `POST /clusters/{id}:probe` | 200 ClusterView: the cluster's current diagnostics; no Secret or cluster resource is changed (`cmapi/src/cmapi/routers/me.py:91-97`) |

No route is a PUT. No successful write response declares a header, and the write handlers set no `Location`: the only
`Location` in the service source is the CORS exposure list, `cmapi/src/cmapi/core/cors.py:31`. A `Location` can still come
from routing: a POST to `/api/v1/clusters/CRC/namespaces/` (a trailing slash) is answered 307 with
`Location: .../api/v1/clusters/CRC/namespaces` (Starlette's slash redirect, measured in-process). So the doc says that the
successful writes omit `Location`, not that cmapi never sends one. The ChangeRequest names itself: `request_view` sets
`base = f"/api/v1/requests/{row.request_id}"` and `links = {"self": base, "events": f"{base}/events"}`
(`cmapi/src/cmapi/core/views.py:17-18`).

RFC 9110 (https://www.rfc-editor.org/rfc/rfc9110.html#section-15.3.3, read 2026-11-23), section 15.3.3: "The representation
sent with this response ought to describe the request's current status and point to (or embed) a status monitor that can
provide the user with an estimate of when the request will be fulfilled." The body does both, so the doc is corrected to the
code; no `Location` header is added. Section 10.2.2 describes what `Location` means for 201 and for the 3xx redirects; it
does not ask for it on a 202.

## 1. docs/02-technical-design-v2.md, line 128 (Write semantics, the Async row)

Old:

```
| Async | POST, PUT, PATCH and DELETE return 202 with a ChangeRequest and a Location header for GET /requests/{requestId} |
```

New:

```
| Async | A write that opens a change request returns 202 with the ChangeRequest: the namespace create, change (PATCH) and delete, and the three expiry writes (`expiration:extend`, `:set`, `:makePermanent`). Its `status` and its `links.self`, `/api/v1/requests/{requestId}`, are the request to follow (`request_view`, `cmapi/src/cmapi/core/views.py:17-18`), as RFC 9110, section 15.3.3 asks of a 202, so these successful writes send no `Location` header. With `?dryRun=true` the create, the change and the expiry writes return 200 with the PlanView instead; the delete has no dry run. The other writes return 200: the request actions (`:approve`, `:reject`, `:cancel`, `:retry`, `:revert`) and `admin/prune:confirm` with the ChangeRequest, `admin/auto-approval:pause` and `:resume` with the switch, and `clusters/{id}:probe` with the cluster's current diagnostics, changing no Secret or cluster resource |
```

## 2. docs/01-design-and-architecture.md, line 730 (what the OpenAPI document fills in), the same claim

Old:

```
| 202 + ChangeRequest + Location for writes; 200 Plan for dry runs | The pipeline, for every write route |
```

New:

```
| 202 + ChangeRequest, whose `links.self` names the request, for a write that opens one, with no `Location` header; 200 PlanView for its dry run where the route has one (the delete has none); 200 for the other writes | The documented router, `cmapi/src/cmapi/core/docs.py`: each route's status (202 unless the route sets another), its response model, and its `dry_run_model` as the 200 |
```

## 3. docs/02-technical-design-v2.md, line 775 (the import refusals), for #591 (added by reviewer 2)

The PR changes what `_valid_ca_data` refuses and what the loader is handed, and no doc says so. Replace this part of line
775 (it occurs once in the line and once in the file):

Old:

```
a caData with an unmatched `BEGIN CERTIFICATE` or `END CERTIFICATE` boundary line, or whose certificate blocks are not valid base64 (finding `invalid caData`; `_valid_ca_data` reads the boundaries as whole lines, as RFC 7468 and OpenSSL do, so text outside the blocks that quotes one is ignored; it runs in linear time, decodes each block and does not parse the certificate, #585)
```

New:

```
a caData with an unmatched boundary line of `CERTIFICATE` or of `X509 CERTIFICATE`, the older label that OpenSSL's loader also reads (#591), or whose certificate blocks are not valid base64, a character that is not ASCII in one included (finding `invalid caData`; `_valid_ca_data` reads the boundaries as whole lines, as RFC 7468 and OpenSSL do, so text outside the blocks that quotes one is ignored, and so is explanatory text that is not ASCII, such as an issuer's name above a block, which the client hands OpenSSL as `?`, #591; it runs in linear time, decodes each block and does not parse the certificate, #585)
```

## Left as it is

- `docs/15-keycloak-integration.md:212` lists `Location` among the response headers a page can read. That is what
  `core/cors.py:31` exposes, so the row is true of the code: the exposure list says which headers a page may read when a
  response has them, and the 307 above has one.
- The designed quota and limit-range PUTs (`docs/02:185-186`) and metadata PATCH/PUT (`docs/02:1168-1169`) are not built.
  Their response codes are documented when they are.

## Proof after the edit

`scripts/doc-citations.py` holds docs/14, 15 and 16 only (its `DOCS`), so it does not check these two rows. Check the new
citation by hand: `sed -n 17,18p cmapi/src/cmapi/core/views.py` shows the `base` and `links` lines quoted above, and
`sed -n 91,97p cmapi/src/cmapi/routers/me.py` the probe. Then
`grep -n "Location header" docs/01-design-and-architecture.md docs/02-technical-design-v2.md` finds only the two new rows'
"no `Location` header", and `grep -n "a Location header for GET" docs/02-technical-design-v2.md` finds nothing. For
section 3, `grep -c "X509 CERTIFICATE" docs/02-technical-design-v2.md` is 1.
````
