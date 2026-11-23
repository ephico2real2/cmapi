[codex] Starting Codex task thread.
[codex] Thread ready (01a20898-4c66-7671-9c7c-f63c50f5aae3).
[codex] Turn started (01a20898-4e8f-7361-88f5-06be7d78cdde).
[codex] Assistant message captured: I’ll trace the diff through the runtime, generated contract, portal callers, and docs, then r...
[codex] Running command: /bin/zsh -lc 'pwd; ls -la; ls head; ls head/cmapi; wc -l pr589.diff LIVE-DOC-EDITS.md; which ...
[codex] Command completed: /bin/zsh -lc 'pwd; ls -la; ls head; ls head/cmapi; wc -l pr589.diff LIVE-DOC-EDITS.md; which ... (exit 0)
[codex] Calling tokensave/tokensave_context.
[codex] Calling tokensave/tokensave_status.
[codex] Tool tokensave/tokensave_context failed.
[codex] Tool tokensave/tokensave_status failed.
[codex] Running command: /bin/zsh -lc "rg '"'^diff|''^@@'"' pr589.diff; cat -n LIVE-DOC-EDITS.md; cat head/cmapi/contr...
[codex] Command completed: /bin/zsh -lc "rg '"'^diff|''^@@'"' pr589.diff; cat -n LIVE-DOC-EDITS.md; cat head/cmapi/contr... (exit 0)
[codex] Running command: /bin/zsh -lc "sed -n '1,470p' pr589.diff"
[codex] Command completed: /bin/zsh -lc "sed -n '1,470p' pr589.diff" (exit 0)
[codex] Running command: /bin/zsh -lc "sed -n '470,686p' pr589.diff; cat -n head/cmapi/tests/service/conftest.py; head...
[codex] Command completed: /bin/zsh -lc "sed -n '470,686p' pr589.diff; cat -n head/cmapi/tests/service/conftest.py; head... (exit 0)
[codex] Running command: /bin/zsh -lc "mkdir -p review1/tmp; cp -R head review1/tree cat >review1/env <<'EOF' export P...
[codex] Command completed: /bin/zsh -lc "mkdir -p review1/tmp; cp -R head review1/tree cat >review1/env <<'EOF' export P... (exit 0)
[codex] Running command: /bin/zsh -lc "cat -n head/cmapi/src/cmapi/core/etag.py; cat -n head/cmapi/src/cmapi/core/view...
[codex] Command completed: /bin/zsh -lc "cat -n head/cmapi/src/cmapi/core/etag.py; cat -n head/cmapi/src/cmapi/core/view... (exit 0)
[codex] Running command: /bin/zsh -lc "sed -n '40,90p' head/cmapi/tests/service/conftest.py; sed -n '40,95p;380,424p' ...
[codex] Command completed: /bin/zsh -lc "sed -n '40,90p' head/cmapi/tests/service/conftest.py; sed -n '40,95p;380,424p' ... (exit 0)
[codex] Running command: /bin/zsh -lc 'source review1/env "$PY" -m pytest -p no:cacheprovider -q --tb=line head/cmapi/...
[codex] Running command: /bin/zsh -lc "rg -n 'check|git' head/scripts/doc-citations.py; rg -n '(def |headers|do_PATCH)...
[codex] Command completed: /bin/zsh -lc "rg -n 'check|git' head/scripts/doc-citations.py; rg -n '(def |headers|do_PATCH)... (exit 0)
[codex] Running command: /bin/zsh -lc "cat review1/baseline.txt | tail -45; cat -n head/cmapi/src/cmapi/core/identity/...
[codex] Command completed: /bin/zsh -lc "cat review1/baseline.txt | tail -45; cat -n head/cmapi/src/cmapi/core/identity/... (exit 0)
[codex] Running command: /bin/zsh -lc "ps -Ao pid,command | rg 'pytest|doc-citations' | cut -c1-180; tail -5 review1/b...
[codex] Command completed: /bin/zsh -lc "ps -Ao pid,command | rg 'pytest|doc-citations' | cut -c1-180; tail -5 review1/b... (exit 0)
[codex] Running command: /bin/zsh -lc 'for f in review1/tmp/pytest-of-olasumbo/pytest-*/.lock(N); do cat "$f"; kill -T...
[codex] Command completed: /bin/zsh -lc 'for f in review1/tmp/pytest-of-olasumbo/pytest-*/.lock(N); do cat "$f"; kill -T... (exit 0)
[codex] Running command: /bin/zsh -lc 'source review1/env "$PY" -m pytest -o addopts= -p no:cacheprovider -q --tb=line...
[codex] Assistant message captured: The contract gate passes, and the unfiltered oasdiff run reports ten errors. The PostgreSQL c...
[codex] Running command: /bin/zsh -lc "source review1/env cat >review1/probes.py <<'PY' import asyncio, json, re, insp...
[codex] Command completed: /bin/zsh -lc "source review1/env cat >review1/probes.py <<'PY' import asyncio, json, re, insp... (exit 0)
[codex] Searching:
[codex] Calling codex_apps/github.fetch_file.
[codex] Calling codex_apps/github.fetch_file.
[codex] Tool codex_apps/github.fetch_file completed.
[codex] Tool codex_apps/github.fetch_file completed.
[codex] Running command: /bin/zsh -lc "ls -l review1/*txt; tail -36 review1/results.txt; cat head/cmapi/src/cmapi/core...
[codex] Command completed: /bin/zsh -lc "ls -l review1/*txt; tail -36 review1/results.txt; cat head/cmapi/src/cmapi/core... (exit 0)
[codex] Calling codex_apps/github.fetch_file.
[codex] Tool codex_apps/github.fetch_file completed.
[codex] Running command: /bin/zsh -lc "nl -ba head/cmapi/tests/service/test_pr40_convergence.py | sed -n '142,172p'; h...
[codex] Command completed: /bin/zsh -lc "nl -ba head/cmapi/tests/service/test_pr40_convergence.py | sed -n '142,172p'; h... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'def test_the_committed_contract|"'^class (ExtendBody|PermanentBody|SetBo...
[codex] Command completed: /bin/zsh -lc "rg -n 'def test_the_committed_contract|"'^class (ExtendBody|PermanentBody|SetBo... (exit 0)
[codex] Calling codex_apps/github.fetch_file.
[codex] Tool codex_apps/github.fetch_file completed.
[codex] Running command: /bin/zsh -lc "rg -n 'wait_seconds|WAIT|timeout|seconds' head/cmapi/src/cmapi/core/db/migrate....
[codex] Command completed: /bin/zsh -lc "rg -n 'wait_seconds|WAIT|timeout|seconds' head/cmapi/src/cmapi/core/db/migrate.... (exit 0)
[codex] Running command: /bin/zsh -lc 'source review1/env f=review1/tmp/pytest-of-olasumbo/pytest-current/.lock [[ -f ...
[codex] Command completed: /bin/zsh -lc 'source review1/env f=review1/tmp/pytest-of-olasumbo/pytest-current/.lock [[ -f ... (exit 0)
[codex] Command failed: /bin/zsh -lc 'source review1/env "$PY" -m pytest -p no:cacheprovider -q --tb=line head/cmapi/... (exit 130)
[codex] Running command: /bin/zsh -lc "ls -la review1/tmp/pytest-of-olasumbo; ls -la review1/tmp/pytest-of-olasumbo/py...
[codex] Command completed: /bin/zsh -lc "ls -la review1/tmp/pytest-of-olasumbo; ls -la review1/tmp/pytest-of-olasumbo/py... (exit 0)
[codex] Command failed: /bin/zsh -lc 'source review1/env "$PY" -m pytest -o addopts= -p no:cacheprovider -q --tb=line... (exit 130)
[codex] Running command: /bin/zsh -lc "cat >review1/mutate.py <<'PY' from pathlib import Path import subprocess,os,sys...
[codex] Running command: /bin/zsh -lc "nl -ba head/cmapi/src/cmapi/core/docs.py | sed -n '820,843p'; rg -n 'cmapi-tool...
[codex] Command completed: /bin/zsh -lc "nl -ba head/cmapi/src/cmapi/core/docs.py | sed -n '820,843p'; rg -n 'cmapi-tool... (exit 0)
[codex] Command completed: /bin/zsh -lc "cat >review1/mutate.py <<'PY' from pathlib import Path import subprocess,os,sys... (exit 0)
[codex] Running command: /bin/zsh -lc 'source review1/env "$PY" head/deploy/tests/front-door-test.py --nginx nginx "$P...
[codex] Command completed: /bin/zsh -lc 'source review1/env "$PY" head/deploy/tests/front-door-test.py --nginx nginx "$P... (exit 0)
[codex] Running command: /bin/zsh -lc "cat >review1/offline.py <<'PY' from pathlib import Path import sys,json from ty...
[codex] Command completed: /bin/zsh -lc "cat >review1/offline.py <<'PY' from pathlib import Path import sys,json from ty... (exit 0)
[codex] Running command: /bin/zsh -lc "cat >review1/check_raw.py <<'PY' from pathlib import Path import sys from starl...
[codex] Command completed: /bin/zsh -lc "cat >review1/check_raw.py <<'PY' from pathlib import Path import sys from starl... (exit 0)
[codex] Running command: /bin/zsh -lc "sed -n '1,49p;824,953p;1140,1209p' head/cmapi-portal-ui/tests/api/standin.mjs; ...
[codex] Command completed: /bin/zsh -lc "sed -n '1,49p;824,953p;1140,1209p' head/cmapi-portal-ui/tests/api/standin.mjs; ... (exit 0)
[codex] Running command: /bin/zsh -lc "sed -n '1334,1348p;1004,1023p' head/cmapi-portal-ui/tests/api/standin.mjs; rg -...
[codex] Command completed: /bin/zsh -lc "sed -n '1334,1348p;1004,1023p' head/cmapi-portal-ui/tests/api/standin.mjs; rg -... (exit 0)
[codex] Running command: /bin/zsh -lc "cat >review1/standin.mjs <<'JS' import { Readable } from 'node:stream' import a...
[codex] Command completed: /bin/zsh -lc "cat >review1/standin.mjs <<'JS' import { Readable } from 'node:stream' import a... (exit 0)
[codex] Running command: /bin/zsh -lc "sed -n '196,215p' head/cmapi/src/cmapi/plugins/namespaces/router.py; rg -n 'res...
[codex] Command completed: /bin/zsh -lc "sed -n '196,215p' head/cmapi/src/cmapi/plugins/namespaces/router.py; rg -n 'res... (exit 0)
[codex] Running command: /bin/zsh -lc "cat >review1/verify_schema.py <<'PY' from copy import deepcopy from cmapi.core....
[codex] Command failed: /bin/zsh -lc "cat >review1/verify_schema.py <<'PY' from copy import deepcopy from cmapi.core.... (exit 1)
[codex] Running command: /bin/zsh -lc "cat >review1/live_check.py <<'PY' from pathlib import Path from types import Si...
[codex] Command completed: /bin/zsh -lc "cat >review1/live_check.py <<'PY' from pathlib import Path from types import Si... (exit 0)
[codex] Running command: /bin/zsh -lc "source review1/env sed -i '' 's/)),),))/)),))/' review1/live_check.py \""'$PY" ...
[codex] Command completed: /bin/zsh -lc "source review1/env sed -i '' 's/)),),))/)),))/' review1/live_check.py \""'$PY" ... (exit 0)
[codex] Assistant message captured: The scratch mutations exposed two gaps. The byte-transport test still passed after TestClient...
[codex] Running command: /bin/zsh -lc "source review1/env ls head/cmapi/tests | head -25 rg -l 'etag_matches|if_match_...
[codex] Command completed: /bin/zsh -lc "source review1/env ls head/cmapi/tests | head -25 rg -l 'etag_matches|if_match_... (exit 0)
[codex] Running command: /bin/zsh -lc 'source review1/env "$PY" -m pytest -p no:cacheprovider -q --tb=short head/cmapi...
[codex] Command completed: /bin/zsh -lc 'source review1/env "$PY" -m pytest -p no:cacheprovider -q --tb=short head/cmapi... (exit 0)
[codex] Running command: /bin/zsh -lc "cat >review1/standard_fix.txt <<'PY' namespace = \"/api/v1/clusters/{cluster_id...
[codex] Command completed: /bin/zsh -lc "cat >review1/standard_fix.txt <<'PY' namespace = \"/api/v1/clusters/{cluster_id... (exit 0)
[codex] Running command: /bin/zsh -lc "source review1/env rg -n 'def test_|test_.*world' head/cmapi/tests/service/test...
[codex] Command completed: /bin/zsh -lc "source review1/env rg -n 'def test_|test_.*world' head/cmapi/tests/service/test... (exit 0)
[codex] Running command: /bin/zsh -lc 'source review1/env "$PY" -m pytest -p no:cacheprovider -q head/cmapi/tests/serv...
[codex] Command failed: /bin/zsh -lc 'source review1/env "$PY" -m pytest -p no:cacheprovider -q head/cmapi/tests/serv... (exit 1)
[codex] Running command: /bin/zsh -lc 'source review1/env export PYTHONPATH="$PWD/review1/tree/cmapi/src" cp base/cmap...
[codex] Command completed: /bin/zsh -lc 'source review1/env export PYTHONPATH="$PWD/review1/tree/cmapi/src" cp base/cmap... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n '\\.(?:strip|split)\\(' head/cmapi/src/cmapi/{core,routers} -g '*.py' | r...
[codex] Command completed: /bin/zsh -lc "rg -n '\\.(?:strip|split)\\(' head/cmapi/src/cmapi/{core,routers} -g '*.py' | r... (exit 0)
[codex] Running command: /bin/zsh -lc "cat >review1/doc_fixes.py <<'PY' from pathlib import Path root=Path(\"review1/t...
[codex] Command completed: /bin/zsh -lc "cat >review1/doc_fixes.py <<'PY' from pathlib import Path root=Path(\"review1/t... (exit 0)
[codex] Running command: /bin/zsh -lc 'source review1/env "$PY" - <<'"'PY' import uvicorn,h11 print(uvicorn.__version_...
[codex] Command completed: /bin/zsh -lc 'source review1/env "$PY" - <<'"'PY' import uvicorn,h11 print(uvicorn.__version_... (exit 0)
[codex] Running command: /bin/zsh -lc 'source review1/env "$PY" - <<'"'PY' import httptools class R: def on_header(sel...
[codex] Command completed: /bin/zsh -lc 'source review1/env "$PY" - <<'"'PY' import httptools class R: def on_header(sel... (exit 0)
[codex] Running command: /bin/zsh -lc "cat >review1/test_ows_other.py <<'PY' import asyncio import httpx from cmapi.co...
[codex] Command completed: /bin/zsh -lc "cat >review1/test_ows_other.py <<'PY' import asyncio import httpx from cmapi.co... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'Location|status_code=200|WRITE_ACCEPTED' head/cmapi/src/cmapi/{core/docs...
[codex] Command completed: /bin/zsh -lc "rg -n 'Location|status_code=200|WRITE_ACCEPTED' head/cmapi/src/cmapi/{core/docs... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -in 'location' head/cmapi/src/cmapi --glob '*.py' | rg -i 'header|response' ...
[codex] Command completed: /bin/zsh -lc "rg -in 'location' head/cmapi/src/cmapi --glob '*.py' | rg -i 'header|response' ... (exit 0)
[codex] Running command: /bin/zsh -lc "source review1/env cat >review1/audit_files.py <<'PY' from pathlib import Path ...
[codex] Command completed: /bin/zsh -lc "source review1/env cat >review1/audit_files.py <<'PY' from pathlib import Path ... (exit 0)
[codex] Running command: /bin/zsh -lc 'source review1/env "$PY" - <<'"'PY' from pathlib import Path import json h=json...
[codex] Command completed: /bin/zsh -lc 'source review1/env "$PY" - <<'"'PY' from pathlib import Path import json h=json... (exit 0)
[codex] Assistant message captured: **Reviewer 1 verdict: request changes.** The #581 runtime fix works. The generated contract c...
[codex] Turn completed.
**Reviewer 1 verdict: request changes.** The #581 runtime fix works. The generated contract changes exactly five headers, the ten oasdiff exceptions match, and I found no portal call site broken by the new type. The changes I would require before merging are the #586 declaration check, the transport test that claims to verify raw bytes, and the #587 replay documentation and stand-in. I reproduced defects in all three areas.

All paths below are relative to `head/` unless prefixed with `base/`, `review1/`, or `LIVE-DOC-EDITS.md`. I made changes only under `review1/`, including mutations to a copy of `head/`. I used the supplied Python. TokenSave reported that the export had no index, so I inspected the exported files directly.

## 1. #586 — the published result is correct, but the transformation and its test are too broad

**Confirmed for this PR.** Applying `_document_if_match_required` to the base document and ignoring description text produced a document structurally equal to head. The only affected parameters are `If-Match` on namespace PATCH, DELETE, and the three expiry POSTs. The head reference configuration also rendered offline to JSON equal to the committed contract. All **177** tests in `test_api_standard.py` passed. See `cmapi/src/cmapi/core/docs.py:499`, `:828–837`, and `cmapi/contract/openapi.json:10493`, `:11323`, `:12026`, `:12656`, `:13291`.

**Refuted as a guarantee about the implementation.** The helper walks every operation. I supplied an unrelated GET with an optional `If-Match` header and it became required. A plain string schema retains its top-level constraints, and the current unconstrained `anyOf[string,null]` works. A constrained string inside `anyOf` loses its constraints. The helper deletes the entire union before setting `type`. See `cmapi/src/cmapi/core/docs.py:828–837`.

**Refuted that the test exception hides no other regression.** In the scratch copy I added `max_length=128` to the real `Header` at `cmapi/src/cmapi/routers/__init__.py:80`. FastAPI declared the constraint, the helper erased it, and **all three** configurations of `test_the_document_keeps_what_each_route_declares` still passed. The new five-operation document test also passed against an offline render of that mutant. Its assertions check the string type and absence of `anyOf`. The general test skips the rest of the parameter comparison at `cmapi/tests/service/test_api_standard.py:392–397`.

**Failure scenario.** A generated client can send a header that satisfies the published schema and exceeds the route's declared maximum. A future plugin with a legitimately optional `If-Match` would also publish it as mandatory.

**Fix and regression test.** Restrict the helper to the five path/method pairs, preserve the non-null string branch and its constraints, and compare the published schema to the route declaration with only nullability removed. Check the runtime parameter is still optional. The complete replacement helper, test exception, and independent scope test are linked below. With the strengthened test the `max_length` mutant failed in **all three** configurations before the helper fix and passed in all three after it. The independent test failed on head and passed with the fix. [Full helper](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/schema_fix.txt) · [Full replacement test block](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/standard_fix.txt) · [Scope and constraint regression test](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/verify_schema.py)

**Confirmed by source inspection for runtime ordering.** `Header(default=None)` remains at `cmapi/src/cmapi/routers/__init__.py:79–80`. For a new plan, the namespace lookup precedes `check_if_match` at `core/pipeline.py:234–242` and `:449–455`. The two database-independent DELETE cases at `test_if_match_before_replay_495.py:86–93` passed. The end-to-end PATCH 404/428 test was blocked by PostgreSQL. This ordering assumes the request got past earlier checks, including the idempotency-key check for a submission at `plugins/namespaces/router.py:76–83`.

## 2. #581 — TestClient really changes the bytes, but the new premise test cannot detect it

**Confirmed experimentally.** I captured the ASGI header bytes and ran the real `if_match` dependency and `check_if_match` against them. The versions were Starlette **0.41.3**, httpx **0.28.1**, and FastAPI **0.115.6**. The table gives the observed status with the base guard and with the head guard. See `cmapi/tests/service/test_if_match_surface_581.py:49–60`, `cmapi/src/cmapi/routers/__init__.py:97–98`, and `core/pipeline.py:117–134`.

| Input hex | TestClient delivered | ASGITransport delivered | Base status, TestClient / ASGI | Head status, TestClient / ASGI |
|---|---|---|---|---|
| `a0 2a a0` | `c2 a0 2a c2 a0` | `a0 2a a0` | 412 / **428** | 412 / **412** |
| `85 2a 85` | `c2 85 2a c2 85` | `85 2a 85` | 412 / **428** | 412 / **412** |
| `20 09 2a 09 20` | unchanged | unchanged | 428 / 428 | 428 / 428 |

The runtime change at `core/pipeline.py:119` is correct. Reverting it to `.strip()` in the scratch copy made `test_the_if_match_dependency_reads_the_octets_as_starlette_decodes_them` fail. Restoring it made the test pass. The existing parser tests at `cmapi/tests/service/test_if_match_forms_571.py:132–154` also passed, **22 cases**.

**Refuted for the transport premise test.** `test_if_match_surface_581.py:63–69` sends `a0 78 a0` and checks for 412 with detail starting “The namespace changed”. Both `a0 78 a0` and the corrupted `c2 a0 78 c2 a0` produce that exact result. I replaced `_raw_patch` in the scratch copy with `client.patch(...)`. The original assertion still passed against an in-process app using the real dependency and guard. The capture showed the wrong bytes.

**Fix and test.** Replace that test with the following. It exercises the same `_raw_patch` helper as the service tests and needs no database. It failed with the TestClient mutant and passed with the PR transport. [Full executable test](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/test_bytes.py)

```python
def test_the_raw_transport_delivers_the_octets_unchanged():
    from starlette.responses import Response
    from starlette.testclient import TestClient

    async def echo(scope, receive, send):
        value = dict(scope["headers"])[b"if-match"]
        await Response(value)(scope, receive, send)

    client = TestClient(echo)
    for value in OBS_TEXT_STAR:
        result = _raw_patch(client, "/", {"If-Match": value}, {})
        assert result.content == value
```

One wording correction at `test_if_match_surface_581.py:49–51`: say **“ASGITransport preserves the supplied obs-text octets.”** I also fed these requests to the installed h11 and httptools HTTP/1 parsers. Both preserved the two obs-text examples. For the SP/HTAB example, h11 delivered `2a` and httptools delivered `2a 09 20`. The broader statement about passing wire octets unchanged does not hold for surrounding HTTP whitespace.

## 3. #587 — a successful replay returns current state; the descriptions overpromise when replay happens

**Confirmed.** `_replay` looks up a row, checks its fingerprint, and returns `request_view(repo, row)` at `cmapi/src/cmapi/plugins/namespaces/router.py:86–97`. The view reads the row's current status and PR, and queries its events, at `core/views.py:12–34` and `core/db/repo.py:78–80`. PATCH, DELETE, and expiry replay paths require the header and refuse the wildcard without comparing the ETag again at `plugins/namespaces/router.py:324–330`, `:345–352`, and `:366–373`. The 24-hour lookup uses the database clock and the row's creation time at `core/db/repo.py:49`, `:124–133`. “A successful replay returns the original request in its current state” is accurate.

Three qualifications matter to clients:

| Status | Published claim and failure scenario | Evidence |
|---|---|---|
| **Refuted** | The same caller retrying the same request is guaranteed a replay. A service submitting `onBehalfOf` a different person writes the **person's** subject to `requester_sub`. Its retry looks up the **service's** subject and misses the original row. The unique index is also on the person's subject and key. The changed public wording makes an existing implementation limitation part of the promised contract. | `cmapi/src/cmapi/routers/__init__.py:60–65`; `plugins/namespaces/router.py:91`; `core/identity/checks.py:49–53`, `:89–95`; `core/pipeline.py:492–498`; `core/db/models.py:196–197`; `docs/04-api-examples.md:18`; `docs/GLOSSARY.md:58`. Confirmed from the lookup and insert code. End-to-end delegated retry **not tested**. |
| **Refuted** | Every different body produces `409 idempotency-replay`. Changing only `justification` on an expiry request leaves its fingerprint input unchanged. I invoked all three real route functions twice and captured their input to `_expiry_write`. Each pair was identical. The justification is passed separately to submission. | `docs/16-data-model.md:105`; `docs/04-api-examples.md:18`; `plugins/namespaces/router.py:60–73`, `:366–376`, `:387–399`, `:411–413`, `:424–426`; `core/db/repo.py:56–57`. [Executable route probe](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/offline.py:22) |
| **Refuted** | “An Idempotency-Key replay requires If-Match” in the proposed concurrency row. A **create replay** returns at `plugins/namespaces/router.py:271–274` without an If-Match dependency or guard. The preceding statement that create takes no If-Match is correct. | `LIVE-DOC-EDITS.md:30`; `cmapi/src/cmapi/plugins/namespaces/router.py:256–274`. |

**Fix for this documentation PR.** Use the following replacement statements where the respective claims appear in the shared header description, docs/01, docs/02, docs/04, docs/16, and the glossary. This describes existing behavior without changing the idempotency keyspace or the meaning of keys already stored.

> A successful replay returns the original request in its current state. For 24 hours from creation, cmapi looks up the key using the caller's subject. The row stores the requester's subject, so a service retry on behalf of a different person misses that row.
>
> A held key with a different fingerprint is 409 `idempotency-replay`. The fingerprint includes the target and the inputs selected by the route. The expiry routes exclude `justification`.
>
> A replay of one of these five writes requires If-Match and refuses `*`. It returns the original request in its current state without comparing the tag again.

The wording checks failed before those edits and passed after them in scratch. The separate route probe establishes the expiry behavior independently of the wording check. [Complete text replacements](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/doc_fixes.py) · [Regression tests](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/test_wording.py)

## 4. #587 — the portal stand-in replays stale state and accepts a missing or wildcard header

**Confirmed by running the actual JavaScript handler.** I submitted `expiration:makePermanent`, rejected the pending request through the stand-in's rejection endpoint, then repeated the submission. The rejection returned `rejected`. Replay returned **202 `pending_approval`**. Replaying without If-Match or with `*` also returned **202**. The real expiry route has a replay guard at `cmapi/src/cmapi/plugins/namespaces/router.py:368–371`.

The changed comment at `cmapi-portal-ui/tests/api/standin.mjs:1161` sits above a return of `held.request`. The stand-in puts that object into its key map at `:1203`. A decision replaces the object in `state.items` at `:955–960`, `:1013–1020`. The map still points to the first object. This can give a portal test the opposite result from the API precisely when retrying after a lost answer or a later decision.

**Fix.** In the expiry handler, put the namespace-row lookup after replay handling so a held request can still be replayed after the namespace moves. Replace the `if (held)` return with this block. Use `find(held.request.requestId)` for the other successful cached returns at `standin.mjs:1089`, `:1229`, and `:1318` as well.

```javascript
if (held) {
  if (held.fingerprint !== print) {
    return problem(res, refuse(409, "idempotency-replay",
      "Idempotency-Key was used for a different request"), cors);
  }
  if (call.ifMatch == null || /^[ \t]*\*[ \t]*$/.test(call.ifMatch)) {
    return problem(res, SAMPLES.problems["precondition-required"].response.body, cors);
  }
  return ok(find(held.request.requestId), 202);
}
```

**Test.** `node review1/standin.mjs` drives submission, rejection, replay, missing header, and wildcard through `apiHandler` without a network listener. Before the fix it observed `pending_approval / 202 / 202`. After replacing the cached return and adding the guard it observed **`rejected / 428 / 428`**, including the updated events. The namespace-removal ordering is supported by source inspection and was not part of that run. [Full regression test](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/standin.mjs) · [Before-fix output](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/standin-before.txt)

## 5. Contract gate, portal calls, and nginx

| Claim | Verdict and evidence |
|---|---|
| **(b) Exactly ten accepted lines in the right format** | **Confirmed.** oasdiff **1.37.0** reported five `request-parameter-became-required` errors and five `request-parameter-list-of-types-narrowed` errors. I compared each normalized `METHOD path message` string, in order, with `cmapi/contract/accepted-breaking.txt:225–234`. All ten matched exactly. The gate at `cmapi/contract/gate.sh:10` exited **0**. [Raw oasdiff output](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/oas.txt) |
| **(b) Future breaks on these operations** | **Confirmed for distinct diagnostics.** I restricted the very same PATCH `If-Match` parameter to a one-value enum. The gate exited **1** with two enum diagnostics. The ignores do have a lifetime caveat: I made a synthetic baseline where PATCH `If-Match` was optional again, then compared it to head. The gate exited **0**. An identical future optional-to-required change on that same operation is already accepted. These entries do not waive the whole operation. See `accepted-breaking.txt:227–228` and [mutation code](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/probes.py:45). |
| **(c) Portal callers** | **Confirmed by source inspection.** Namespace and quota PATCH plans and submissions send `ifMatchOf(etag)` at `cmapi-portal-ui/src/api/hooks.ts:450`, `:466–467`, `:491–492`. Their UI callers are `NamespacesTab.tsx:191–192` and `QuotasTab.tsx:516–517`, `:659–660`. All three expiry POSTs share the header created at `hooks.ts:620–626`, for both the plan at `:640` and submit at `:660`, used by `ExpirationTab.tsx:340–341`. I found **no namespace DELETE caller** in `cmapi-portal-ui/src`. The five generated fields are required strings at `src/api/schema.generated.ts:6537`, `:6781`, `:7114`, `:7423`, `:7755`. **Not compiler-tested**: the export has no `tsc` or installed generator. `node head/cmapi-portal-ui/scripts/api-types.mjs --check` reported the missing generator at `scripts/api-types.mjs:18–20`. |
| **#582 nginx behavior** | **Confirmed from the exact release source.** Lines 93–95 register `If-Match` with the unique-header handler. Lines 1835–1856 accept the first line and finalize a duplicate as `NGX_HTTP_BAD_REQUEST`. Both cited ranges are accurate. The image identifies its pinned nginx version at `cmapi-portal-ui/Containerfile:19–21`. [nginx registration](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/ngx_http_request.c#L93-L95) · [nginx duplicate handling](https://github.com/nginx/nginx/blob/release-1.30.6/src/http/ngx_http_request.c#L1835-L1856) |
| **#582 front-door test** | **Confirmed by inspection; live case not tested.** `deploy/tests/front-door-test.py:695–708` emits separate `putheader` calls. Lines `723–730` require both a 400 and zero upstream requests, then send the joined field and require one successful upstream request carrying its value. `main` invokes the case at `:768`. `--nginx nginx` reported no binary, and a loopback bind raised `Operation not permitted`. Direct application callers still get comma joining through `cmapi/src/cmapi/routers/__init__.py:97–98`. |

## 6. Other header whitespace in `core/` and `routers/`

**Refuted that #581 removes the last argumentless strip on header values.** I found two more. Both predate this PR. I found no argumentless `.split()` on an HTTP header value in the requested directories.

| File | Observed failure | Full replacement line |
|---|---|---|
| `cmapi/src/cmapi/core/etag.py:32` | `etag_matches("\xa0*\xa0", '"abc"')` returns `True`. An If-None-Match read can consequently return 304. Call sites include `cmapi/main.py:262`, `routers/me.py:81`, and `plugins/capacity/router.py:223`. | `candidates = [c.strip(" \t") for c in if_none_match.split(",")]` |
| `cmapi/src/cmapi/core/cors.py:102` | On a response with `Vary: <NBSP>Origin<NBSP>`, the middleware treats the malformed value as the `Origin` token and omits the valid `Origin` it intended to add at `:103–104`. | `varied = {v.strip(" \t").lower() for v in headers.get("vary", "").split(",")}` |

Both regression tests failed on the copied head and passed after those one-line fixes. The first fix addresses the whitespace question only. `core/registry.py:264` strips a token **file** while constructing an outgoing header. [Full tests for both cases](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/test_ows_other.py)

## 7. Live-doc audit and remaining test gaps

| `LIVE-DOC-EDITS.md` | Verdict against the code |
|---|---|
| **Lines 10–13, 30 — hash and files** | **Confirmed with one correction.** `core/pipeline.py:99–101` returns `"0"` for an empty mapping, otherwise the first 16 hex characters of SHA-256 over the encoded **hex digest** returned by `plan_hash`. `core/render/manifests.py:92–97` sorts paths and uses NUL delimiters. The direct `.yaml` selection is supported by `core/git/workspace.py:299–308`, `github.py:66–78`, and `gitea.py:68–76`. The inner hash substitutes `"<deleted>"` for empty content. I obtained the identical tag `83d5f5923e8c0887` for `{"x.yaml": ""}` and `{"x.yaml": "<deleted>"}`. In `docs/GLOSSARY.md:53`, replace “It changes when the folder changes” with “An empty file contributes the string `<deleted>` to the inner hash.” Non-YAML and nested changes are also outside its inputs. [Hash probe](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/probes.py:43) |
| **Lines 14–16, 30 — verbs, header and body** | **Confirmed.** The namespace resource has PATCH and DELETE and no PUT. The three expiry routes are POSTs at `plugins/namespaces/router.py:379`, `:402`, `:416`, through the default method at `core/docs.py:278–279`. Namespace GET puts the unquoted value in the body and the quoted value in the header at `plugins/namespaces/router.py:248–252`. Create declares no If-Match at `:256–264`. |
| **Lines 17–22, 30 — conditions and citations** | **Confirmed with the replay qualification in finding 3.** The cited `_replay:86–97`, `request_view:12–34`, `check_if_match:124–134`, and `if_match_tags:36–56` ranges identify the stated code. Bare strong tags, weak tags, and lists are handled at `core/etag.py:44–56`; both 412 paths carry the current tag at `core/pipeline.py:129–134`. Scope “else 428” to a request that reaches the precondition check. A fresh write to a namespace missing from Git gets 404 first. A replay of create needs no tag. |
| **Lines 24–30, 34–40 — old text and export state** | **Confirmed.** Both old-text strings equal their respective base lines exactly. Head still contains the old rows at `docs/02-technical-design-v2.md:131` and `docs/01-design-and-architecture.md:236`. The replacements are proposals. The proposed docs/01 sentence also needs the delegated-caller qualification. [Exact comparison](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/offline.py:26) |
| **Lines 44–47 — reasons for leaving other rows alone** | **Mixed.** Line 44 overlooks the caller/requester and fingerprint qualifications. Lines 45–47 correctly locate designed quota and limit-range PUTs at `docs/02:185–186` and metadata PATCH/PUT at `:1168–1169`; `docs/04-api-examples.md:37–41` lists those unbuilt paths. **Refuted as a universal runtime rule:** `docs/02:128` says POST/PUT/PATCH/DELETE return 202 and a `Location` header. Cancel, for example, declares 200 at `routers/requests.py:178–182`. The namespace submit returns `request_view` at `plugins/namespaces/router.py:104–110`, with `links.self` at `core/views.py:17–18`, `:34`. The only `Location` header reference I found in service Python was the CORS exposure list at `core/cors.py:31`. An accurate replacement for that design-table row is “Namespace submissions return 202 with a ChangeRequest. Its `links.self` names the request. Supported dry runs return 200 with a plan.” |
| **Lines 51–73 — proposed proof** | **Refuted that it proves all five verbs are documented.** I ran its exact test body on the old row, the proposed row, and the proposed row with **both PATCH and DELETE removed**. Results were **fail / pass / pass**. Lines 63–64 check those methods only in the schema; line 70 checks only POST and absence of PUT in the prose. Add `assert "PATCH" in row and "DELETE" in row`. [Mutation driver](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/live_check.py) · [Corrected test](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/test_doc_rows.py:17) |

**Two more test-quality findings.**

- `cmapi/tests/service/test_if_match_surface_581.py:210–218` searches whole Markdown files. I removed the one-field instruction from the actual docs/04 `If-Match` row and put its keywords in an HTML comment. Both original parametrizations passed. The fix is to select the `If-Match` and `Idempotency-Key` rows by their first cell and assert each promise in its own row. The replacement failed on the mutant and passed when I restored the text. [Full replacement test](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/test_doc_rows.py:6)
- `cmapi/tests/service/test_if_match_surface_581.py:200–206` checks that the replay has *more* events, while its docstring promises the cancel event. A duplicated unrelated event satisfies the count. Replace line 206 with `assert replay.json()["events"] == cancelled.json()["events"]` and `assert any(e["event"] == "cancel" for e in replay.json()["events"])`. The event name and insertion are supported by `core/lifecycle.py:39`, `routers/requests.py:192–196`, and `core/db/repo.py:211`. This particular mutation was **not run end to end** because it needs PostgreSQL.

**Other diff checks.** The relocated citations in `docs/14-authorization.md:66`, `:177`, `:209`, `:308`, and `:316` resolve. All **130** locked ranges match their source text. I also ran the citation check with the export's file listing substituted for `git ls-files`; it returned no problems. [Read-only citation check](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/citations.py)

## Commands and test limits

These are the principal commands I ran from the export. `review1/env` selects the supplied interpreter, sets `PYTHONPATH=head/cmapi/src`, disables bytecode writes, and keeps temporary files inside the export. Mutant runs used `review1/tree/cmapi/src`.

```sh
source review1/env
diff -qr base head
"$PY" review1/audit_files.py
"$PY" review1/probes.py
"$PY" review1/offline.py head
"$PY" review1/citations.py

oasdiff --version
oasdiff breaking base/cmapi/contract/openapi.json head/cmapi/contract/openapi.json
head/cmapi/contract/gate.sh base/cmapi/contract/openapi.json head/cmapi/contract/openapi.json
head/cmapi/contract/gate.sh base/cmapi/contract/openapi.json review1/narrow.json
head/cmapi/contract/gate.sh review1/optional-again.json head/cmapi/contract/openapi.json

rg -n '\.(strip|split)\(\)' head/cmapi/src/cmapi/{core,routers} --glob '*.py'
rg -n 'ifMatchOf|If-Match|expiration:(extend|set|makePermanent)|\.PATCH\(|\.DELETE\(' \
  head/cmapi-portal-ui/src -g '!schema.generated.ts'
node head/cmapi-portal-ui/scripts/api-types.mjs --check
"$PY" head/deploy/tests/front-door-test.py --nginx nginx

"$PY" -m pytest -p no:cacheprovider -q head/cmapi/tests/service/test_api_standard.py
"$PY" -m pytest -p no:cacheprovider -q \
  head/cmapi/tests/service/test_if_match_forms_571.py -k test_the_parser
CMAPI_MIGRATE_WAIT_SECONDS=0 "$PY" -m pytest -o addopts= -p no:cacheprovider -q --tb=line \
  head/cmapi/tests/service/{test_if_match_surface_581.py,test_api_standard.py::test_the_document_keeps_what_each_route_declares,test_if_match_before_replay_495.py,test_flow.py::test_an_idempotency_key_is_free_again_after_24_hours}

"$PY" review1/mutate.py
"$PY" review1/check_raw.py
"$PY" review1/live_check.py
node review1/standin.mjs
```

**PostgreSQL limit.** Connecting to `127.0.0.1:55432` returned `Operation not permitted`. The focused head run had **8 passed and 17 fixture errors**. These are the cases whose service assertions did not run:

- `test_if_match_surface_581.py` — raw transport (`:63`), fresh obs-text `[nbsp, nel]` (`:73`), SP/HTAB wildcard (`:83`), obs-text replay `[nbsp, nel]` (`:92`), five required headers (`:136`), 404 before 428 (`:155`), one-field documentation (`:166`), replay documentation (`:174`), and replay after cancellation (`:190`).
- `test_if_match_before_replay_495.py` — missing header on PATCH replay (`:35`), retry after Git moved (`:46`), missing header on DELETE replay (`:59`), missing header on expiry replay (`:70`), and unknown namespace before 428 (`:80`).
- `test_flow.py:377` — key reuse after 24 hours.

I ran the three new **document-only** assertion bodies separately against the real offline render, and all passed. The ASGI byte capture, lower-level runtime guard, and stand-in results above were also executed independently of PostgreSQL. [Full focused pytest output](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/results_fast.txt) · [API-standard results](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/standard.txt) · [Mutation results](/Users/olasumbo/gitRepos/workbench/cmapi/review-589/review1/mutants.txt)

[exited with code 0]
