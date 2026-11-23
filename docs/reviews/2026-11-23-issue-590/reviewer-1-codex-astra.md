[codex] Starting Codex task thread.
[codex] Thread ready (01a20953-3dff-7353-bf39-d027de7fd049).
[codex] Turn started (01a20953-4017-73f2-8a95-51c1011a6bff).
[codex] Assistant message captured: I’ll review the two exports read-only, check the RFC and pinned Starlette source, and run the...
[codex] Running command: /bin/zsh -lc 'pwd; ls -la; ls head; ls head/cmapi'
[codex] Command completed: /bin/zsh -lc 'pwd; ls -la; ls head; ls head/cmapi' (exit 0)
[codex] Calling tokensave/tokensave_context.
[codex] Calling tokensave/tokensave_status.
[codex] Tool tokensave/tokensave_context failed.
[codex] Tool tokensave/tokensave_status failed.
[codex] Searching:
[codex] Running command: /bin/zsh -lc "rg '"'^diff --git'"' pr598.diff for f in head/cmapi/src/cmapi/core/{etag,cors}....
[codex] Command completed: /bin/zsh -lc "rg '"'^diff --git'"' pr598.diff for f in head/cmapi/src/cmapi/core/{etag,cors}.... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'DATABASE|55432|def world|POSTGRES' head/cmapi/tests/{conftest.py,service...
[codex] Command completed: /bin/zsh -lc "rg -n 'DATABASE|55432|def world|POSTGRES' head/cmapi/tests/{conftest.py,service... (exit 0)
[codex] Running command: /bin/zsh -lc "sed -n '45,145p;400,530p' head/cmapi/tests/service/conftest.py rg -n '"'^def te...
[codex] Command completed: /bin/zsh -lc "sed -n '45,145p;400,530p' head/cmapi/tests/service/conftest.py rg -n '"'^def te... (exit 0)
[codex] Running command: /bin/zsh -lc "nl -ba head/cmapi/src/cmapi/main.py | sed -n '140,244p' nl -ba head/cmapi/src/c...
[codex] Command failed: /bin/zsh -lc "nl -ba head/cmapi/src/cmapi/main.py | sed -n '140,244p' nl -ba head/cmapi/src/c... (exit 2)
[codex] Running command: /bin/zsh -lc "sed -n '/diff --git a\\/cmapi\\/tests\\/service\\/test_api_docs/,/diff --git a\...
[codex] Command completed: /bin/zsh -lc "sed -n '/diff --git a\\/cmapi\\/tests\\/service\\/test_api_docs/,/diff --git a\... (exit 0)
[codex] Running command: /bin/zsh -lc "mkdir -p .review1/tmp cat > .review1/env <<'EOF' export REVIEW_ROOT=\""'$PWD" e...
[codex] Running command: /bin/zsh -lc 'source .review1/env "$P" head/scripts/api-examples-doc.py --check rg -n '"'prec...
[codex] Command completed: /bin/zsh -lc 'source .review1/env "$P" head/scripts/api-examples-doc.py --check rg -n '"'prec... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'DB|db\\.|Database|store\\.|audit\\.' head/cmapi/src/cmapi/{core/context,...
[codex] Command completed: /bin/zsh -lc "rg -n 'DB|db\\.|Database|store\\.|audit\\.' head/cmapi/src/cmapi/{core/context,... (exit 0)
[codex] Running command: /bin/zsh -lc "source .review1/env nl -ba head/cmapi/src/cmapi/core/context.py | sed -n '50,16...
[codex] Command completed: /bin/zsh -lc "source .review1/env nl -ba head/cmapi/src/cmapi/core/context.py | sed -n '50,16... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'def main|--config-dir|--metadata-keys|openapi render' head/cmapi/src |rg...
[codex] Command completed: /bin/zsh -lc "rg -n 'def main|--config-dir|--metadata-keys|openapi render' head/cmapi/src |rg... (exit 0)
[codex] Running command: /bin/zsh -lc "cat > .review1/probe.py <<'PY' import sys, pathlib, tempfile, contextlib, pytes...
[codex] Searching:
[codex] Command completed: /bin/zsh -lc "cat > .review1/probe.py <<'PY' import sys, pathlib, tempfile, contextlib, pytes... (exit 0)
[codex] Running command: /bin/zsh -lc "ls -lh .review1; tail -10 .review1/head.log | cut -c1-250; tail -10 .review1/te...
[codex] Command completed: /bin/zsh -lc "ls -lh .review1; tail -10 .review1/head.log | cut -c1-250; tail -10 .review1/te... (exit 0)
[codex] Running command: /bin/zsh -lc "rg '"'^RESULT'"' .review1/{head,base}.log rg -n 'precondition-failed|def proble...
[codex] Command completed: /bin/zsh -lc "rg '"'^RESULT'"' .review1/{head,base}.log rg -n 'precondition-failed|def proble... (exit 0)
[codex] Running command: /bin/zsh -lc "head -45 head/cmapi/tests/service/conftest.py; head -40 head/cmapi/tests/servic...
[codex] Command completed: /bin/zsh -lc "head -45 head/cmapi/tests/service/conftest.py; head -40 head/cmapi/tests/servic... (exit 0)
[codex] Running command: /bin/zsh -lc "cat head/cmapi/src/cmapi/core/db/migrate.py; rg -n 'starlette' head/cmapi/pypro...
[codex] Command completed: /bin/zsh -lc "cat head/cmapi/src/cmapi/core/db/migrate.py; rg -n 'starlette' head/cmapi/pypro... (exit 0)
[codex] Assistant message captured: All four named GETs returned 412 for stale If-Match plus matching If-None-Match. Base returne...
[codex] Running command: /bin/zsh -lc 'source .review1/env export CMAPI_MIGRATE_WAIT_SECONDS=0 cd head/cmapi t=tests/s...
[codex] Running command: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' import json,pathlib,runpy from cmapi.tools....
[codex] Command failed: /bin/zsh -lc 'source .review1/env export CMAPI_MIGRATE_WAIT_SECONDS=0 cd head/cmapi t=tests/s... (exit 1)
[codex] Command completed: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' import json,pathlib,runpy from cmapi.tools.... (exit 0)
[codex] Running command: /bin/zsh -lc "cat > .review1/corscheck.py <<'PY' import asyncio,httpx from cmapi.core.cors im...
[codex] Command completed: /bin/zsh -lc "cat > .review1/corscheck.py <<'PY' import asyncio,httpx from cmapi.core.cors im... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'metadata_keys_document\\(' head rg -n 'cmapi-problems|precondition-faile...
[codex] Command completed: /bin/zsh -lc "rg -n 'metadata_keys_document\\(' head rg -n 'cmapi-problems|precondition-faile... (exit 0)
[codex] Running command: /bin/zsh -lc "cat > .review1/mutations.py <<'PY' import inspect,sys,tempfile,pathlib,pytest,i...
[codex] Running command: /bin/zsh -lc "sed -n '337,369p' head/cmapi/src/cmapi/core/docs.py sed -n '121,141p' head/cmap...
[codex] Command completed: /bin/zsh -lc "sed -n '337,369p' head/cmapi/src/cmapi/core/docs.py sed -n '121,141p' head/cmap... (exit 0)
[codex] Command completed: /bin/zsh -lc "cat > .review1/mutations.py <<'PY' import inspect,sys,tempfile,pathlib,pytest,i... (exit 0)
[codex] Searching:
[codex] Running command: /bin/zsh -lc "rg '"'^RESULT'"' .review1/mutlog; tail -6 .review1/mutlog|cut -c1-300 rg -n 'cm...
[codex] Command completed: /bin/zsh -lc "rg '"'^RESULT'"' .review1/mutlog; tail -6 .review1/mutlog|cut -c1-300 rg -n 'cm... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'schema.generated.ts|--check' head/cmapi-portal-ui --glob '"'!*.generated...
[codex] Command completed: /bin/zsh -lc "rg -n 'schema.generated.ts|--check' head/cmapi-portal-ui --glob '"'!*.generated... (exit 0)
[codex] Running command: /bin/zsh -lc "cat head/cmapi-portal-ui/scripts/api-types.mjs |head -70; rg -n 'date|current|g...
[codex] Command completed: /bin/zsh -lc "cat head/cmapi-portal-ui/scripts/api-types.mjs |head -70; rg -n 'date|current|g... (exit 0)
[codex] Running command: /bin/zsh -lc "source .review1/env node head/cmapi-portal-ui/scripts/api-types.mjs --check rg ...
[codex] Command completed: /bin/zsh -lc "source .review1/env node head/cmapi-portal-ui/scripts/api-types.mjs --check rg ... (exit 0)
[codex] Running command: /bin/zsh -lc 'source .review1/env mkdir -p .review1/fixed cp -R head/cmapi/src/cmapi .review1...
[codex] Command completed: /bin/zsh -lc 'source .review1/env mkdir -p .review1/fixed cp -R head/cmapi/src/cmapi .review1... (exit 0)
[codex] Running command: /bin/zsh -lc "rg '"'^RESULT|Traceback|Error:'"' .review1/fixedlog | cut -c1-300 source .revie...
[codex] Command completed: /bin/zsh -lc "rg '"'^RESULT|Traceback|Error:'"' .review1/fixedlog | cut -c1-300 source .revie... (exit 0)
[codex] Running command: /bin/zsh -lc "source .review1/env ls -l /usr/local/bin/npm head -33 head/cmapi-portal-ui/tool...
[codex] Command completed: /bin/zsh -lc "source .review1/env ls -l /usr/local/bin/npm head -33 head/cmapi-portal-ui/tool... (exit 0)
[codex] Running command: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' import json,shutil,base64 from pathlib impo...
[codex] Command completed: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' import json,shutil,base64 from pathlib impo... (exit 0)
[codex] Running command: /bin/zsh -lc "rg '"'^RESULT'"' .review1/mutlog; nl -ba head/cmapi/src/cmapi/core/pipeline.py ...
[codex] Command completed: /bin/zsh -lc "rg '"'^RESULT'"' .review1/mutlog; nl -ba head/cmapi/src/cmapi/core/pipeline.py ... (exit 0)
[codex] Running command: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' from pathlib import Path p=Path(\".review1/...
[codex] Running command: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' import os,signal,pathlib p=pathlib.Path('.r...
[codex] Command completed: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' import os,signal,pathlib p=pathlib.Path('.r... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'FileResponse|StaticFiles|status_code\\s*=\\s*304|HTTP_304|is_not_modifie...
[codex] Command completed: /bin/zsh -lc "rg -n 'FileResponse|StaticFiles|status_code\\s*=\\s*304|HTTP_304|is_not_modifie... (exit 0)
[codex] Command completed: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' from pathlib import Path p=Path(\".review1/... (exit 0)
[codex] Running command: /bin/zsh -lc "source .review1/env rg '"'^RESULT'"' .review1/stronglog rg -n 'add_vary_header|...
[codex] Command completed: /bin/zsh -lc "source .review1/env rg '"'^RESULT'"' .review1/stronglog rg -n 'add_vary_header|... (exit 0)
[codex] Running command: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' import pathlib s=pathlib.Path('.review1/str...
[codex] Running command: /bin/zsh -lc "source .review1/env sed 's/\\[\"Accept\",\"Cookie\"\\],/[\"Accept\",\"*\"],[\"A...
[codex] Command completed: /bin/zsh -lc "source .review1/env sed 's/\\[\"Accept\",\"Cookie\"\\],/[\"Accept\",\"*\"],[\"A... (exit 0)
[codex] Command completed: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' import pathlib s=pathlib.Path('.review1/str... (exit 0)
[codex] Running command: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' from cmapi.core.pipeline import check_if_ma...
[codex] Command completed: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' from cmapi.core.pipeline import check_if_ma... (exit 0)
[codex] Running command: /bin/zsh -lc 'source .review1/env PYTHONPATH="$PYTHONPATH:$PWD/head/cmapi/tests/service" "$P"...
[codex] Command completed: /bin/zsh -lc 'source .review1/env PYTHONPATH="$PYTHONPATH:$PWD/head/cmapi/tests/service" "$P"... (exit 0)
[codex] Assistant message captured: The new 40-case GET matrix catches removal of If-Match, but it still passes when only the las...
[codex] Running command: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' from pathlib import Path from shutil import...
[codex] Command completed: /bin/zsh -lc 'source .review1/env "$P" - <<'"'PY' from pathlib import Path from shutil import... (exit 0)
[codex] Assistant message captured: **Reviewer 1 verdict for `169d107`: request changes on #596.** The four named GETs implement ...
[codex] Turn completed.
**Reviewer 1 verdict for `169d107`: request changes on #596.** The four named GETs implement #590 correctly, and the whitespace change implements #593. With an **allowed** origin, #596 still loses cache-selection information. I reproduced a response with `Vary: Accept` and `Vary: Cookie` leaving cmapi as `Vary: Accept, Origin`. A second-line `Vary: *` was lost the same way. The fix works on Starlette 0.41.3.

I also found two pre-existing limits relevant to the review. HEAD returns 405 on all four named routes, and the mounted Swagger and ReDoc assets are conditional GETs that still evaluate the two ETag fields incorrectly.

I ran against the supplied exports with the supplied Python. Paths below refer to `head/` unless marked `base/`. I made no Git calls, pushed nothing, and left both source trees unchanged.

## (a) Conditional GET order and comparison

**Confirmed on all four routes.** I sent requests through the application to `/openapi.json`, `/openapi.yaml`, `/api/v1/metadata-keys`, and `/api/v1/capacity`, using credentials for the latter two. `T` below means the current **quoted** ETag of each individual response.

| Request fields | Head | Base |
|---|---:|---:|
| Neither field | 200 | 200 |
| `If-Match: "stale"` | 412 | 200 |
| `If-Match: "stale"` and `If-None-Match: T` | **412** | **304** |
| `If-Match: T` and `If-None-Match: T` | 304 | 304 |
| `If-Match: *` alone / with `If-None-Match: T` | 200 / 304 | 200 / 304 |
| `If-Match: W/T` | 412 | 200 |
| Present, empty `If-Match` | 412 | 200 |
| `If-Match: T, junk` or `If-Match: *, T` | 412 | 200 |
| Two `If-Match` lines, stale then current / both stale | 200 / 412 | 200 / 200 |
| `If-None-Match: W/T` or `If-None-Match: *` | 304 | 304 |
| `If-None-Match: T, *` | 200 | 200 |
| Two `If-None-Match` lines, stale then current | 304 | 304 |

RFC 9110 §13.2.2 puts If-Match at step 1, with the instruction “if false, respond 412 (Precondition Failed)”; If-None-Match is step 3. The exception for an already-successful state change does not apply to these GETs. Section 13.1.1 specifies strong comparison and allows a standalone wildcard for an existing representation. Section 13.1.2 specifies weak comparison. A wildcard mixed with tags is invalid in either field. [Evaluation order](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.2.2) · [If-Match](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1) · [If-None-Match](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.2)

The decisive code is `cmapi/src/cmapi/core/etag.py:94–99`. An absent field yields `[]` and a present empty field yields `[""]`. `getlist` and the join retain line order. The parser at lines 24 and 36–49 consumes complete list elements, including quoted commas. Lines 77–80 discard weak tags for If-Match; lines 60–65 compare the opaque value regardless of weakness for If-None-Match. Base read only If-None-Match at `base/cmapi/src/cmapi/main.py:262`, `routers/me.py:81`, and `plugins/capacity/router.py:223`. [Combining field lines](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.3) · [Entity-tag comparisons](https://www.rfc-editor.org/rfc/rfc9110.html#section-8.8.3.2)

**One qualification on malformed values.** I retract the blanket hypothesis that every malformed If-Match produces 412. Sending the current hash alone, without quotes, returned **200** on all four head routes. `core/etag.py:73–79` deliberately recovers that single bare tag. It is cmapi compatibility behavior permitted by the RFC’s error-recovery rule, outside the entity-tag grammar. The two-line results above are direct-to-app results. The deployment test separately expects nginx to reject a repeated If-Match line at `deploy/tests/front-door-test.py:712–724`. [RFC 9110 §2.4](https://www.rfc-editor.org/rfc/rfc9110.html#section-2.4)

## (b) 412 bodies, HEAD, and 304 headers

**412 body confirmed.** All four GETs returned `application/problem+json`, `code: "precondition-failed"`, numeric `status: 412`, and a body `etag` equal to the current response ETag with its surrounding quotes removed. I also invoked the namespace comparison. It produced the same problem fields with its own shorter, unquoted tag. The read and namespace details appropriately differ. See `core/etag.py:97–98`, `core/pipeline.py:140–146`, `core/errors.py:38–43`, and `main.py:176–177,190–192`.

**304 headers confirmed.** Every observed 304 had an empty body and the same quoted ETag and Cache-Control as its 200. The documents returned `no-cache`; metadata-keys and capacity returned `private, no-cache`. Each handler constructs one header dictionary for both responses at `main.py:259–264`, `routers/me.py:78–84`, and `plugins/capacity/router.py:219–225`. This satisfies §15.4.5 for the two headers in question. [RFC 9110 §15.4.5](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.4.5)

**HEAD support refuted; pre-existing.** On all four paths, unconditional HEAD, HEAD with stale If-Match, and HEAD with current If-None-Match returned **405, `Allow: GET`, zero client-visible bytes** on both base and head. The document decorators register GET at `main.py:266,270`. The API decorators at `routers/me.py:58` and `plugins/capacity/router.py:177` use the GET default at `core/docs.py:289–295`. Given that routing rejects the method, skipping preconditions is correct under §13.2.1. Clients cannot currently use these paths for conditional HEAD. [When to evaluate](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.2.1) · [HEAD semantics](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.3.2)

If HEAD is part of the intended surface, these are the complete additions to the existing handlers, plus the CORS method-list replacement. Each decorator goes above its corresponding existing GET decorator. I tested these in a scratch copy. The three HEAD requests then returned **200, 412, 304** respectively on every path, each with an empty client-visible body.

```python
# main.py, above the two document GET decorators respectively
@app.head("/openapi.json", include_in_schema=False, dependencies=guard)
@app.head("/openapi.yaml", include_in_schema=False, dependencies=guard)
```

```python
# routers/me.py, above @router.read("/metadata-keys", ...)
@router.head("/metadata-keys", summary="Read metadata-keys headers",
             response_model=MetadataKeysView, include_in_schema=False)

# plugins/capacity/router.py, above @router.read("/capacity", ...)
@router.head("/capacity", summary="Read capacity headers",
             response_model=CapacityPage, include_in_schema=False)

# core/cors.py
METHODS = ["GET", "HEAD", "POST", "PATCH", "DELETE"]
```

Regression test for `test_read_preconditions_590_593.py`:

```python
@pytest.mark.parametrize("path", PATHS)
def test_conditional_head(world, path):
    client, *_, keys = world
    auth = _credentials(path, keys)
    first = client.get(path, headers=auth)
    tag = first.headers["etag"]
    for fields, status in [
        ({}, 200),
        ({"If-Match": '"stale"', "If-None-Match": tag}, 412),
        ({"If-None-Match": tag}, 304),
    ]:
        r = client.head(path, headers={**auth, **fields})
        assert (r.status_code, r.content) == (status, b"")
        if status in (200, 304):
            assert r.headers["etag"] == tag
            assert r.headers["cache-control"] == first.headers["cache-control"]
```

## (c) Curl samples and generators

**Confirmed for the code change.** I ran base and head `sample_request` on identical inputs for all 15 non-GET operations in the head contract. All 15 outputs were equal. The old predicate is at `base/cmapi/src/cmapi/core/docs.py:422`; the new predicate is at `head/cmapi/src/cmapi/core/docs.py:442–444`. Required headers are still included. The GET exception affects the automatic inclusion of the two **optional** headers.

**One committed non-GET curl command did change.** I retract the broader hypothesis that all committed curl strings are identical. Comparing `x-codeSamples` by path and method gave 25/25 equal GETs and 14/15 equal non-GETs. The sole difference was the `expiration:set` POST body’s `until`, from `2026-12-12` to `2026-12-14`. Its headers were identical. The recorder computes today plus 21 days at `cmapi/tests/service/test_api_samples.py:350`, and `core/docs.py:454–455` uses the recorded body. The changed commands can be compared directly at `base/docs/04-api-examples.md:1252` and `head/docs/04-api-examples.md:1252`.

**Generator checks confirmed.**

- `scripts/api-examples-doc.py --check` and `cmapi/contract/changelog.py --check` both exited 0.
- Rendering the reference OpenAPI document using `cmapi.tools.openapi.render` produced byte-for-byte equality with `cmapi/contract/openapi.json`.
- `node cmapi-portal-ui/scripts/api-types.mjs --check` passed in an export-local copy using the lockfile and offline npm cache.
- The citation checker returned zero discrepancies when given the export’s file inventory. Its native CLI limitation is listed at the end.

## (d) CORS

**P1 — allowed origins still lose Vary fields.** `cmapi/src/cmapi/core/cors.py:99–112` wraps the outgoing send. For an allowed origin, the superclass mutates the response **before** that wrapper sees it. Starlette 0.41.3 calls `headers.add_vary_header("Origin")`; the helper starts with `existing = self.get("vary")`. Lookup selects the first line, and assignment deletes the remaining lines. See the installed `starlette/middleware/cors.py:142–172` and `starlette/datastructures.py:534–539,568–584,647–651`. [Pinned CORS source](https://github.com/encode/starlette/blob/0.41.3/starlette/middleware/cors.py#L142-L172) · [Pinned header implementation](https://github.com/encode/starlette/blob/0.41.3/starlette/datastructures.py#L647-L651)

Raw ASGI runs gave these results. A slash between values denotes separate field lines.

| Upstream Vary | No origin or denied origin | Allowed origin |
|---|---|---|
| `Accept` / `Cookie` | `Accept, Cookie, Origin` | **`Accept, Origin`** |
| `oRiGiN` / `Cookie` | `oRiGiN` / `Cookie` | **`oRiGiN, Origin`** |
| `Accept` / `OrIgIn` | `Accept` / `OrIgIn` | `Accept, Origin` |
| `Accept` / `*` | `Accept` / `*` | **`Accept, Origin`** |
| `*` | `*` | `*, Origin` |

The lost `Cookie` selector can cause a shared cache to treat two variants as equivalent. Losing a second-line `*` also removes the upstream indication that matching the listed request fields is insufficient. Duplication is real when Origin is already on the **first** line. When it is on the second line, Starlette can erase and recreate it, so counting Origin tokens alone misses the defect. [RFC 9110 §12.5.5](https://www.rfc-editor.org/rfc/rfc9110.html#section-12.5.5)

**#593 confirmed.** `core/cors.py:106–109` examines every line it receives, strips only SP and HTAB, and compares field names case-insensitively. A0- and 85-wrapped `Origin` each stayed byte-for-byte intact and acquired a separate genuine Origin token. SP/HTAB-wrapped mixed-case Origin was recognized. Base used unrestricted `strip()` and first-line lookup at `base/cmapi/src/cmapi/core/cors.py:102–104`. [HTTP whitespace](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.3) · [Field-name case](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.1)

**Preflight confirmed.** OPTIONS requesting GET with `if-match,if-none-match` returned 200, the allowed origin, both permitted header names, and one `Vary: Origin`. A denied origin returned 400, no allow-origin header, and one `Vary: Origin`. Starlette handles preflight before `simple_response`. [Pinned preflight dispatch](https://github.com/encode/starlette/blob/0.41.3/starlette/middleware/cors.py#L75-L95)

**Fix.** I retract the claim that this has to wait for a Starlette upgrade. Add this complete override to `OriginVaryCORSMiddleware`. The existing outer wrapper then owns Vary for all paths, while Starlette still decides which origin may be reflected. I reran the raw header and preflight probes with this override. All selectors were retained, Origin appeared once where needed, and wildcard responses were preserved.

```python
@staticmethod
def allow_explicit_origin(headers: MutableHeaders, origin: str) -> None:
    headers["Access-Control-Allow-Origin"] = origin
```

**Regression test.** In `test_read_preconditions_590_593.py:93`, add `origin: str | None = None` to `_vary_after_cors` and replace its line 107 with:

```python
return await client.get("/", headers={"Origin": origin} if origin else {})
```

Then add:

```python
@pytest.mark.parametrize(("upstream", "expected"), [
    (["Accept", "Cookie"], [b"Accept, Cookie, Origin"]),
    (["oRiGiN", "Cookie"], [b"oRiGiN", b"Cookie"]),
    (["Accept", "OrIgIn"], [b"Accept", b"OrIgIn"]),
    (["Accept", "*"], [b"Accept", b"*"]),
    (["*"], [b"*"]),
])
def test_allowed_origin_preserves_upstream_vary(upstream, expected):
    assert _vary_after_cors(upstream, origin="https://portal.example") == expected
```

## (e) Other conditional routes

**Confirmed for application-defined 304 handlers.** A source search for ETag production, conditional-field consumption, `FileResponse`, `StaticFiles`, and 304 emission found the four named GETs at `main.py:259–272`, `routers/me.py:78–84`, and `plugins/capacity/router.py:219–225`. The single-namespace GET also emits an ETag, but its handler never evaluates a read precondition. It returns a live view, hashes the **Git folder**, and supplies that tag for subsequent writes at `plugins/namespaces/router.py:219–229,233–253`. Reusing the folder tag to return 304 for the entire live view would be incorrect when cluster state changes alone.

**P2 — the two static mounts are conditional, too.** `main.py:245–248` mounts Starlette `StaticFiles` when the bundles exist. With the suite’s bundle fixture, I fetched both `/static/swagger/swagger-ui-bundle.js` and `/static/redoc/redoc.standalone.js`. Each returned 200 with an ETag. Each then returned **304** for stale If-Match plus matching If-None-Match, **200** for stale If-Match alone, and **200** for `If-None-Match: *`. These results were identical on base and head. The upstream decision is `if self.is_not_modified(response.headers, request_headers):`; its implementation reads If-None-Match and If-Modified-Since, with no If-Match step. Installed `starlette/staticfiles.py:176–181,199–220`. [Pinned StaticFiles source](https://github.com/encode/starlette/blob/0.41.3/starlette/staticfiles.py#L169-L220)

**Fix for the ETag cases under review.** Use this subclass in `main.py`. It retains the existing date check when If-None-Match is absent. I verified in a scratch copy that both mounts then returned 412 for the conflicting request, 304 for `If-None-Match: *`, and 200 for an ordinary GET.

```python
from starlette.datastructures import Headers

class ConditionalStaticFiles(StaticFiles):
    def is_not_modified(self, response_headers: Headers, request_headers: Headers) -> bool:
        if not_modified(request_headers, response_headers["etag"]):
            return True
        return (
            "if-none-match" not in request_headers
            and super().is_not_modified(response_headers, request_headers)
        )
```

```python
if swagger_dir.exists():
    app.mount("/static/swagger", ConditionalStaticFiles(directory=str(swagger_dir)), name="swagger")
if redoc_dir.exists():
    app.mount("/static/redoc", ConditionalStaticFiles(directory=str(redoc_dir)), name="redoc")
```

Regression test for `test_api_docs.py`, where `bundles` is defined:

```python
@pytest.mark.parametrize("path", [
    "/static/swagger/swagger-ui-bundle.js",
    "/static/redoc/redoc.standalone.js",
])
def test_static_asset_evaluates_if_match_first(bundles, world, path):
    client, *_ = world
    tag = client.get(path).headers["etag"]
    r = client.get(path, headers={"If-Match": '"stale"', "If-None-Match": tag})
    assert r.status_code == 412
    assert r.json()["etag"] == tag[1:-1]
    assert client.get(path, headers={"If-None-Match": "*"}).status_code == 304
```

## (f) Test quality and mutants

I ran the new GET test bodies through the real app with its normal fake Git, Kubernetes, and authentication components, bypassing only the unused database setup. These are observed mutation results for the **40 new GET cases**, distinct from claims about the entire suite.

| Mutation | New GET cases that failed |
|---|---:|
| Ignore If-Match entirely | 20/40 |
| Read only the **last** If-Match line | **0/40** |
| Read only the **first** If-None-Match line | **0/40** |
| Reject weak If-None-Match matches | **0/40** |
| Remove Cache-Control from every 304 | **0/40** |

**Finding — the two-line and 304 assertions have blind spots.** At `test_read_preconditions_590_593.py:33`, stale If-Match ends evaluation before either If-None-Match line matters. At line 38 the matching If-Match is last, so reading only the last line passes. Line 69 checks body and ETag but omits Cache-Control. Earlier tests independently cover some of this: `test_validators_583_584_585.py:68–94` exercises repeated If-None-Match, `test_api_docs.py:298–302` checks weak matching, and `test_metadata_keys_336_api.py:110–114` checks Cache-Control on metadata’s 304. The capacity test checks Cache-Control on its **200** at `test_capacity_302.py:343–346`.

**Fix and regression tests.** Add these rows to `CASES` and the assertion to the existing 304 branch:

```python
    (["{etag}", STALE], [], 200),
    (["*"], ['"old"', "W/{etag}"], 304),
    (["*"], ["W/{etag}"], 304),
    (["{etag}, junk"], [], 412),
    (["*, {etag}"], [], 412),
    ([], ["*, {etag}"], 200),
    (["*"], [], 200),
```

```python
assert r.headers["cache-control"] == first.headers["cache-control"]
```

All 28 added route/case combinations passed on head. The stronger probes detected each of the four surviving mutations. For CORS, reverting to `strip()` failed both octet tests, and reverting to `add_vary_header` failed the two-line preservation test. The existing CORS helper deliberately sends **no Origin** at `test_read_preconditions_590_593.py:93–107`, which explains why the actual allowed-origin defect survived. The regression in (d) covers it.

**Finding — an unintended GET can advertise If-Match.** `test_if_match_surface_581.py:159` now counts only writes. The new read test at `test_read_preconditions_590_593.py:79–87` checks two expected paths individually. I added the optional If-Match parameter to `/api/v1/me` in a copy of the generated spec. The five-write test, the forms-documentation test, and the new two-read test **all passed**. That route does not consume the header (`routers/me.py:22–32`).

Add this assertion to the existing read-documentation test. It passes on head and fails on that mutated spec. The separate write assertions should stay.

```python
actual = {
    path for path, methods in spec["paths"].items()
    if any(
        p["in"] == "header" and p["name"].lower() == "if-match"
        for p in methods.get("get", {}).get("parameters", [])
    )
}
assert actual == {"/api/v1/metadata-keys", "/api/v1/capacity"}
```

**Confirmed for the namespace example-format change.** `test_namespace_etag_doc_565.py:78–85` still applies the namespace format to the other operations and requires 32 lowercase hex characters for the read tags it finds. The separate per-path assertion at `test_read_preconditions_590_593.py:84–85` requires a nonempty 412 example tag on each read. Both test bodies passed against the served document.

## (g) Documentation

- **`docs/08-code-status.md:90` — confirmed.** The changed ETag row identifies the four GETs, the strong hash of served bytes, the ordering, the 412, and the wildcard exception. See `core/etag.py:31–33,94–99` and the runs in (a).
- **`docs/GLOSSARY.md:57` — confirmed.** The changed 412 entry expressly excludes standalone `*` for the reads and gives If-Match precedence. The write-specific 428 is implemented at `core/pipeline.py:129–133`.
- **`docs/04-api-examples.md:3850–3878` — confirmed as recorded examples.** The two GET problem bodies agree with their records at `cmapi/src/cmapi/contract/samples.json:3–50`. Both recorded requests sent `If-Match: "stale"` at `cmapi/tests/service/test_api_samples.py:401–403`. The examples generator’s check passed.
- **`docs/14-authorization.md:84` — confirmed.** The relocated citation points to the permission text and operation metadata at `core/docs.py:268–273`. The export-based citation check found no drift.

**Documentation finding — `docs/18-configuration.md:503` omits the wildcard exception.** A reader following “412 on an `If-Match` that does not list the `ETag`” would predict 412 for `If-Match: *`; the observed result was 200. The same sentence says the answer is built at start and implies that any edit to either file changes the tag. `routers/me.py:45–55,78` builds it on first use, caches it, and hashes the serialized view. That view specifically omits `maxExtensionDays` at line 52.

Replace “so the `ETag` changes when either file does” with “so the `ETag` changes when the serialized metadata or expiration rules in this answer change.” Replace the final sentence with:

> The first request builds and caches the answer for the loaded configuration. It has a strong `ETag` over its bytes and `Cache-Control: private, no-cache`. `If-Match: *` passes. Any other present If-Match must match the current tag by strong comparison or the answer is 412. A subsequent matching If-None-Match returns 304.

**Documentation finding — `docs/08-code-status.md:89` describes the old curl policy.** The adjacent row says the samples send If-Match wherever an operation takes it. The two GETs now take it and omit it from curl. The row also says 32 operations; the checked reference contract has 40. Replace its first two sentences with:

> Each documented operation has one `x-codeSamples` entry. It uses the instance’s `publicUrl`, the documented parameter examples, and `Authorization: Bearer $TOKEN` for secured operations. Write samples include their declared `Idempotency-Key` and `If-Match` headers. The conditional GET samples omit optional preconditions.

A small documentation regression test covering both corrections, alongside the runtime tests in (a) and (c):

```python
def test_conditional_read_guidance_matches_the_sample_policy():
    from pathlib import Path

    docs = Path(__file__).resolve().parents[3] / "docs"
    config = (docs / "18-configuration.md").read_text()
    status = (docs / "08-code-status.md").read_text()
    assert "`If-Match: *` passes" in config
    assert "first request builds and caches" in config
    assert "conditional GET samples omit optional preconditions" in status
```

**Documentation finding — the problem type page tells a GET caller to send a change.** `core/problem_docs.py:31,89–98` renders write-only recovery instructions for the same `type` URI now returned to GET callers. A caller following the link from a capacity 412 has no change to send. Replace the action entry with:

```python
"precondition-failed": (
    "For a conditional read, fetch the current representation without `If-Match`. "
    "For a change, read the object again, review its current state, and send the "
    "change with its new `ETag` in `If-Match`."
),
```

Regression test:

```python
def test_precondition_failed_page_covers_reads_and_changes():
    from cmapi.core.problem_docs import problem_html

    page = problem_html("precondition-failed", "https://example.test/problems/", "test")
    assert "For a conditional read" in page
    assert "For a change" in page
```

## Tests and commands I could not run to completion

**Unmodified pytest run: 222 passed, 47 fixture setup errors.** PostgreSQL connection to `127.0.0.1:55432` failed with `Operation not permitted`. The common fixture migrates the database before constructing `world` at `cmapi/tests/service/conftest.py:425–429,470–472`. I separately ran **45 of those 47 test bodies** through `build_world` without the database fixture: all 40 new GET cases, the new document test, and the four changed write/namespace documentation tests passed. The all-operation curl execution and sample-recording bodies still need PostgreSQL.

The [exact 47 pytest node IDs, one per line](/Users/olasumbo/gitRepos/workbench/cmapi/review-598/.review1/postgres-nodeids.txt) are ready for the coordinator. The following also reconstructs the complete list from `head/cmapi` without a wildcard test selection:

```bash
s=tests/service
r="$s/test_read_preconditions_590_593.py"
status=(412 412 412 304 304 412 412 200 200 200)
ids=()
for i in "${!status[@]}"; do
  for path in /openapi.json /openapi.yaml /api/v1/metadata-keys /api/v1/capacity; do
    ids+=("$r::test_a_conditional_read_evaluates_if_match_first[if_match$i-if_none_match$i-${status[$i]}-$path]")
  done
done
ids+=(
  "$r::test_the_two_reads_document_if_match_and_its_412"
  "$s/test_if_match_forms_571.py::test_the_document_says_how_each_form_is_read"
  "$s/test_namespace_etag_doc_565.py::test_each_recorded_etag_in_the_document_has_the_documented_form"
  "$s/test_if_match_surface_581.py::test_the_document_marks_if_match_required_on_the_five_writes"
  "$s/test_if_match_surface_581.py::test_the_document_describes_a_replay_as_the_original_request_in_its_current_state"
  "$s/test_api_docs.py::test_each_operation_has_one_curl_sample_that_the_app_accepts"
  "$s/test_api_samples.py::test_each_operation_has_a_sample_from_a_run"
)
python -m pytest -q "${ids[@]}"
```

I did not run native `scripts/doc-citations.py --check`: line 63 calls `git ls-files`, and the review was restricted to the export. I ran its actual `check()` function with export file enumeration substituted for that one Git call; it returned `[]`. I did not run the deployed nginx front-door test. The repeated-field HTTP runs reported above were against the ASGI application.

[exited with code 0]
