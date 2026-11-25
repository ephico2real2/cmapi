# PR #665 (#649): reviewer 2's report

Reviewer 2: Opus 5.5 at `high`. I did not write the change or reviewer 1's review. Run on 2026-11-25 (UTC) on the
development Mac. I used the export only, PostgreSQL 16 on `127.0.0.1:55432`, database `cmapi_r2_665`, and the new-pins
venv (FastAPI 0.162.2, Starlette 1.10.0, uvicorn 0.32.1). No cluster, no GitHub, no repository.

The outputs are in `r2-outputs/`. The sources I fetched (2026-11-25 01:52Z to 01:56Z) are in `r2-outputs/sources/`.

## Rulings

| # | Reviewer 1 | Ruling | Test that decides it | Before | After |
|---|---|---|---|---|---|
| F1 | 304 has no `Accept-Ranges: none` | **Accepted**, code as reviewer 1 wrote it; test docstring reworded | `test_a_304_says_accept_ranges_none` | head code: 2 failed (`run-pre.txt`) | 2 passed (`run-final.txt`) |
| F2 | No test guards the scope copy | **Accepted, test rewritten**: 12 lines in place of 25, through `TestClient` instead of a hand-built scope | `test_the_request_keeps_its_range_header` | M4: fails (`run-m4-in-place.txt`); head: passes | passes |
| F3 | No Range row in docs/04, docs/08 | **Accepted, both rows corrected**: docs/08 said "every answer" says `none`, which a 412 or a 404 does not | none possible (prose); `doc-citations.py --check` and `api-examples-doc.py --check` pass | — | rows added |

## F1: should a 304 carry `Accept-Ranges` at all?

**RFC 9110 §15.4.5** (https://www.rfc-editor.org/rfc/rfc9110.txt, fetched 2026-11-25 01:52Z). The text says:

> The server generating a 304 response MUST generate any of the following header fields that would have been sent in a
> 200 (OK) response to the same request: Content-Location, Date, ETag, and Vary; Cache-Control and Expires

> Since the goal of a 304 response is to minimize information transfer when the recipient already has one or more cached
> representations, a sender SHOULD NOT generate representation metadata other than the above listed fields unless said
> metadata exists for the purpose of guiding cache updates (e.g., Last-Modified might be useful if the response does not
> have an ETag field).

The SHOULD NOT covers only *representation metadata*. RFC 9110 does not list `Accept-Ranges` among the representation
fields:
- §8.2: "Representation header fields provide metadata about the representation."
- §3.4 names the separate kinds: a response "might also contain header fields for server information, resource metadata,
  and representation metadata".
- §14.3: "The "Accept-Ranges" field in a response indicates whether an upstream server supports range requests for the
  target resource". That is a statement about the server and the resource, not about how to read the content.

So §15.4.5 neither requires nor forbids `Accept-Ranges` on a 304. Two more points support sending it here:
- Even if it were representation metadata, the exception "unless said metadata exists for the purpose of guiding cache
  updates" applies, and updating stored entries is the whole purpose here.
- §14.3: the field "is particularly useful for restarting large information transfers that have failed in mid-content".
  That is the cache-resume case.

**RFC 9111 §3.2** (https://www.rfc-editor.org/rfc/rfc9111.txt, fetched 2026-11-25 01:52Z): "When doing so, the cache MUST
add each header field in the provided response to the stored response, replacing field values that are already present".
It has four exceptions, and none of them is Accept-Ranges:
- fields excepted from storage;
- fields that the stored response depends on;
- fields that the recipient processes and removes;
- Content-Length.

§4.3.4: "the cache MUST update its header fields with the header fields provided in the 304 (Not Modified) response, as
per Section 3.2."

**Starlette 1.10.0**, `staticfiles.py:23-37`:
- `NotModifiedResponse.NOT_MODIFIED_HEADERS = ("cache-control", "content-location", "date", "etag", "expires", "vary")`.
  This is exactly §15.4.5's MUST list.
- `file_response` (`:181-193`) builds the `FileResponse` first. Its `__init__` already sets `accept-ranges: bytes`
  (`responses.py:324`, `setdefault`). It then returns `NotModifiedResponse(response.headers)`, which filters that field
  out.

**What a real cache does with it** (primary source code, fetched 2026-11-25):
- Chromium `net/http/http_response_headers.cc`, `kNonUpdatedHeaders` (lines 92-112): the fields a 304 may *not* update
  are connection, proxy-connection, keep-alive, www-authenticate, proxy-authenticate, proxy-authorization, te, trailer,
  transfer-encoding, upgrade, content-location, content-md5, etag, content-encoding, content-range, content-type,
  content-length, x-frame-options and x-xss-protection. `accept-ranges` is not in the list, so a 304's Accept-Ranges
  replaces the stored one.
- Chromium `net/http/http_cache_transaction.cc:4061-4082`, `CanResume`: it returns false when
  `response_.headers->HasHeaderValue("Accept-Ranges", "none")`. A stored entry with `bytes`, or with no field, stays
  resumable by a range request. One with `none` does not.

So the stored value has a measurable consumer. On head, a pre-#649 entry keeps `bytes` through every 304. After the fix it
becomes `none`. This is still Low: §14.3 says a client "MAY generate range requests regardless", and cmapi answers 200,
which Chromium handles.

**Counter-practice, for the record.** nginx's own 304 removes the field
(`ngx_http_not_modified_filter_module.c:94-98`: `ngx_http_clear_accept_ranges(r);`). That is nginx saving bytes on a field
whose value never changes for it. It is not a spec rule, and it does not apply to cmapi: cmapi's value changed in #649.
Proxied 304s pass through nginx's filter untouched (the filter acts on a 200 only).

**Ruling.** The 304 may carry `Accept-Ranges: none`, so reviewer 1's code fix is right, and I take it unchanged. I
checked reviewer 1's F1 premises against the sources above and retract nothing. The `stat_result`/mtime premise (the npm
tarball mtime of 1985-10-26 keeps the ETag stable across images) is reviewer 1's measurement. I did not repeat it.

Code (`cmapi/src/cmapi/main.py`, the import of `FileResponse` removed; `main.py` stays at 597 lines, so no citation
moves):

```python
    def file_response(self, full_path: PathLike, stat_result: os.stat_result, scope: Scope,
                      status_code: int = 200) -> Response:
        """FileResponse says `Accept-Ranges: bytes`. Section 14.3: "A server that does not support any kind of range request
        for the target resource MAY send Accept-Ranges: none to advise the client not to attempt a range request". The 304
        says it too: a cache updates a stored 200 with each field of the 304 (RFC 9111, section 3.2), and a bundle keeps its
        ETag from image to image (the npm tarball fixes its mtime), so a 200 stored before #649 said `bytes`."""
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["accept-ranges"] = "none"
        return response
```

The guard can go because `super().file_response` returns only a `FileResponse` or a `NotModifiedResponse`
(`staticfiles.py:190-193`). Otherwise `is_not_modified` raises the 412 `Problem`, which never reaches this line.

Test: I kept reviewer 1's body. I rewrote the docstring, which read "Accept-Ranges is no representation metadata", to say
what the RFC sections say:

```python
@pytest.mark.parametrize("path", PATHS)
def test_a_304_says_accept_ranges_none(bundles, world, path):
    """RFC 9111 (https://www.rfc-editor.org/rfc/rfc9111.txt, read 2026-11-25), section 3.2: a cache that freshens a stored
    response with a 304 "MUST add each header field in the provided response to the stored response, replacing field values
    that are already present". A field that the 304 leaves out keeps its stored value, so a 200 stored before #649, with
    `Accept-Ranges: bytes`, would keep it: Starlette's ETag is the md5 of the mtime and the size, and the npm tarballs fix
    each file's mtime, so a bundle has one ETag in every image of its version. RFC 9110, section 15.4.5, says a 304 "SHOULD
    NOT generate representation metadata" beyond its list; Accept-Ranges is not representation metadata (section 8.2) but
    a range field of section 14.3, so the 304 may send it."""
    client, *_ = world
    whole = client.get(path)
    for method in ("GET", "HEAD"):
        for validator in ({"If-None-Match": whole.headers["etag"]}, {"If-Modified-Since": whole.headers["last-modified"]}):
            r = client.request(method, path, headers=validator)
            assert (r.status_code, r.headers.get("accept-ranges")) == (304, "none"), (method, validator, r.headers)
```

## F2: keep the scope test?

The ASGI spec (https://raw.githubusercontent.com/django/asgiref/main/specs/asgi.rst, fetched 2026-11-25 01:55Z, line
264): "When middleware is modifying the ``scope``, it should make a copy of the ``scope`` object before mutating it and
passing it to the inner application, as changes may leak upstream otherwise."

The facts:
- Today nothing in cmapi reads `range` after `/static` returns. `MetricsAndRequestIdMiddleware` reads only
  `x-request-id`, before the call (`core/observability.py:144`). CORS writes only response headers.
- So M4 (in place) is a latent spec breach with no visible effect. The PR's 18 tests let it pass (reviewer 1 measured
  this). In my run, the final suite fails M4 by this test alone: 1 failed, 20 passed. The assertion was
  `(200, [None]) == (200, [b'bytes=1-2'])`.
- A test is the only thing that keeps the copy. The comment on the line does not.

So the test meets the rule and stays.

Reviewer 1's version hand-built a 12-key ASGI scope and ran `receive`, `send` and `asyncio.run` itself, in 25 lines. Mine
does the same through `TestClient` and a 4-line ASGI caller, in 12 lines. It kills the same mutant (M4), and also M1 and
M8. It moves `ConditionalStaticFiles` and `TestClient` to the module imports.

```python
from starlette.testclient import TestClient

from cmapi.main import ConditionalStaticFiles
...

def test_the_request_keeps_its_range_header(bundles):
    """ConditionalStaticFiles drops Range from a copy of the scope. The ASGI spec, "Middleware": "When middleware is modifying
    the scope, it should make a copy of the scope object before mutating it and passing it to the inner application, as
    changes may leak upstream otherwise" (https://github.com/django/asgiref/blob/main/specs/asgi.rst, read 2026-11-25)."""
    static = ConditionalStaticFiles(directory=str(bundles / "swagger-ui"))
    after: list[bytes | None] = []

    async def caller(scope, receive, send):
        await static(scope, receive, send)
        after.append(dict(scope["headers"]).get(b"range"))

    r = TestClient(caller).get("/swagger-ui-bundle.js", headers={"Range": "bytes=1-2"})
    assert (r.status_code, after) == (200, [b"bytes=1-2"])
```

## F3: the doc rows, checked against the code

docs/04 and docs/08 are repository docs, not live Claude Docs exports, so they change here.

| Claim in reviewer 1's rows | Code | Verdict |
|---|---|---|
| `/static/swagger` and `/static/redoc` ignore Range and If-Range | `main.py:66-69`; test `..._sent_whole_whatever_its_range`, with If-Range | holds |
| 200 or 304 with `Accept-Ranges: none` | after F1, `main.py:78`; tests pass | holds |
| "No other route reads `Range`" | `grep -rn -i "FileResponse\|StaticFiles\|range" cmapi/src`: only `ConditionalStaticFiles` and the 405 handler's `isinstance(..., StaticFiles)` (`main.py:310`) | holds |
| docs/04: "answer the whole file, 200 or 304" | a 304 has no body | **imprecise**; reworded |
| docs/08: "every answer, the 304 too, says `Accept-Ranges: none`" | a 412 (raised from `is_not_modified`), a 404 and a 405 never pass `file_response`'s return, so they have no Accept-Ranges | **wrong**; reworded |

Final rows:

```markdown
| `Range` | Not supported. The files under `/static/swagger` and `/static/redoc` ignore `Range` and `If-Range`: they answer 200 with the whole file, or 304, and both say `Accept-Ranges: none`. The preconditions above are unchanged (RFC 9110, sections 14.2 and 14.3; `main.py`, `ConditionalStaticFiles`; #649). No other route reads `Range` |
```

```markdown
| `Range` on `/static` | Each file under `/static/swagger` and `/static/redoc` answers 200 with the whole file, or 304, whatever `Range` and `If-Range` say, and both say `Accept-Ranges: none` (RFC 9110, sections 14.2 and 14.3; #649). Starlette's range code is never reached from `/static` | `test_static_range_649.py` |
```

The docs/04 row is in the hand-written table above `<!-- examples:begin -->`, and `scripts/api-examples-doc.py --check`
exits 0 on the patched tree.

## What reviewer 1 missed: mutants of the final fix

Each mutant is a whole copy of the final tree, with `test_static_range_649.py` (21 tests). The diffs are in
`r2-outputs/m*.diff`, built by `r2-outputs/make-trees.py` and run by `r2-outputs/run-all.sh`.

| Mutant | Change | Result | Killed by |
|---|---|---|---|
| pre (head's code) | `isinstance(response, FileResponse)` guard | 2 failed | the F1 test |
| M1 no copy | Range left in the scope | 17 failed | the 16 whole-file tests, and the F2 test |
| M2 no accept | the `accept-ranges` line deleted | 18 failed | the 16 whole-file tests, and the F1 test |
| M3 GET only | the copy only for GET | 16 failed | the whole-file tests (HEAD) |
| M4 in place | `scope["headers"] = ...` | 1 failed | the F2 test only |
| M5 no `.lower()` | `k != b"range"` | **survives** (21 passed) | equivalent: see below |
| M6 FileResponse only | the head guard restored | 2 failed | the F1 test |
| M7 setdefault | `headers.setdefault("accept-ranges", "none")` | 16 failed | the whole-file tests (`FileResponse.__init__` already set `bytes`) |
| M8 drops If-Range | filters `if-range`, not `range` | 17 failed | the whole-file tests, and the F2 test |

**M5 is equivalent under cmapi's server.** Both uvicorn 0.32.1 parsers lowercase header names before the scope is built:
- `h11_impl.py:196`: `self.headers = [(key.lower(), value) for key, value in event.headers]`;
- `httptools_impl.py:240`: `name = name.lower()`.

`TestClient` does too (`testclient.py:253`). ASGI says "Header names should be lowercased, but it is not required", so
the `.lower()` is correct defence. A test for it would need a hand-made scope that no server of cmapi sends. By the
owner's rule (over-build only when it is the only solution), I add none.

Final tree, with `test_static_range_649.py`, reviewer 1's `test_r1_665.py` (13 tests, evidence only, not in the patch),
`test_static_preconditions_604.py`, `test_head_605.py` and `test_framework_upgrade_651.py`: **116 passed**
(`run-final.txt`).

## Deliverable

`r2-outputs/fix.diff`: 93 lines against `head/`, from `cmapi/` and `docs/` only. It touches:
- `cmapi/src/cmapi/main.py` (reviewer 1's change, unchanged);
- `cmapi/tests/service/test_static_range_649.py`;
- `docs/04-api-examples.md`;
- `docs/08-code-status.md`.

On a fresh copy of head:
- `patch -p1 -F0` applies cleanly, and each file is then byte-identical to `r2/`.
- `scripts/doc-citations.py --check` gives "0 problems". No citation moved, since `main.py` stays at 597 lines, so no
  `--write` was needed.
- `scripts/api-examples-doc.py --check` exits 0.

## What I did not test

- The front door. I read its config: `proxy.conf` has no `proxy_cache` and no `proxy_force_ranges`, and does not hide
  Accept-Ranges. I did not run it.
- A real browser's cache update.
- The npm-tarball mtime (reviewer 1's measurement).
- The whole service suite.
- kind or CRC.
