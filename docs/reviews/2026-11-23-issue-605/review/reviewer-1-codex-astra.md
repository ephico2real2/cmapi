**Reviewer 1 verdict — request changes.** On `7f0da62` against `447234e`, the four conditional reads now answer HEAD correctly. I found no HEAD-only route around authentication or permission checks. The main merge concern is the quota export audit trail. An authenticated HEAD creates the same `quotas.export` event as a GET and runs the CSV generator, although the caller receives no CSV. The new tests also miss a permission regression that I reproduced with a mutant.

Two routing issues affect the broader 405 claim. Starlette reports incomplete `Allow` headers on shared paths, and five documented POST actions also match the generic request-detail GET route. Both routing behaviors have roots in the base branch. Neither permits HEAD to execute a write action.

I used the supplied Python and both exported trees. Changes proposed below were exercised in memory. I made no repository edits or pushes. File references are relative to `head/` unless marked otherwise.

## Findings and fixes

### 1. A HEAD probe is recorded as a quota export

`cmapi/src/cmapi/plugins/quotas/__init__.py:137–147` loads the rows, records `quotas.export`, and returns a `StreamingResponse`. `core/db/repo.py:341–343` adds the audit row, and `core/db/__init__.py:44–50` commits the session. `core/listquery.py:177–190` generates the header and filters, sorts, and serializes the rows.

**Measured:** With the real endpoint, real authentication, an empty row source, and spies on the audit call and CSV filtering, GET returned 114 CSV bytes and HEAD returned zero. After GET followed by HEAD, both spies had been called twice. On the base branch, HEAD returned 405 and neither count advanced. PostgreSQL persistence is inferred from the repository and transaction code.

**Failure scenario:** A portal checks the export link with HEAD, then downloads it with GET. An audit consumer counting `quotas.export` sees two indistinguishable events. I retract any interpretation that HTTP safety itself prohibits an audit write. RFC 9110 explicitly allows incidental effects of safe methods. The defect is the meaning of this application audit event. [RFC 9110 §9.2.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.1)

**Fix:** Keep an audit record of the access and distinguish the metadata probe. This preserves GET’s existing audit action, filtering, validation, and stream behavior. The following is the complete production change.

```diff
-from fastapi import Depends, Query
+from fastapi import Depends, Query, Request
@@
-def export(q: Text = "", env: Env = None, cluster_id: ClusterFilter = None, team: Team = None, tier: Tier = None,
+def export(request: Request, q: Text = "", env: Env = None, cluster_id: ClusterFilter = None, team: Team = None, tier: Tier = None,
@@
-    with c.db.session() as s:
-        AuditRepo(s).record(who, "quotas.export", "csv", {"rows": len(rows), "q": q, "env": env, "clusterId": cluster_id})
+    action = "quotas.export.head" if request.method == "HEAD" else "quotas.export"
+    with c.db.session() as s:
+        AuditRepo(s).record(who, action, "csv", {"rows": len(rows), "q": q, "env": env, "clusterId": cluster_id})
```

**Regression test:** Failed on head and passed with the change in the in-memory service harness. The choice to preserve the access audit is deliberate. This fix does not save the cost of generating the stream.

```python
def test_export_audit_distinguishes_metadata(world, monkeypatch):
    from cmapi.plugins import quotas

    client, *_, keys = world
    events = []
    monkeypatch.setattr(
        quotas.AuditRepo, "record",
        lambda self, who, action, target, detail: events.append(action),
    )
    path = "/api/v1/quotas:export"
    headers = auth(keys, "ola", **OLA)

    assert client.head(path, headers=headers).status_code == 200
    assert client.get(path, headers=headers).status_code == 200
    assert events == ["quotas.export.head", "quotas.export"]
```

### 2. The authorization sweep misses a signed-in caller losing a permission check

`cmapi/tests/service/test_head_605.py:55–62` tests a caller without the required permission on two paths. Lines 65–74 visit all GET routes anonymously. An anonymous request stops at sign-in before it reaches most permission checks.

**Failure scenario, measured:** I changed only the tier route’s permission dependency in the test app so that HEAD accepted a signed-in caller without `objects:read`. All nine existing test bodies passed. With the same signed token, `GET /api/v1/tiers` returned 403 and HEAD returned 200. The unmodified branch returned 403 for both methods.

**Fix and regression test:** Add this test to `test_head_605.py`, which already imports `re`, `APIRoute`, and `auth`. It covers the 23 GET routes declaring a permission in the tested configuration. The expected result is an explicit 403, so two equally incorrect answers cannot pass. The tier assertion fails on the mutant and passes on head.

```python
def test_head_enforces_each_documented_read_permission(world):
    client, *_, keys = world
    headers = auth(keys, "nobody", roles=[], groups=[])
    routes = [
        route for route in client.app.routes
        if isinstance(route, APIRoute)
        and "GET" in route.methods
        and (route.openapi_extra or {}).get("x-cmapi-permission")
    ]
    assert routes
    for route in routes:
        path = re.sub(r"\{[^}]+\}", "x", route.path)
        for method in ("GET", "HEAD"):
            response = client.request(method, path, headers=headers)
            assert response.status_code == 403, (method, path, response.status_code)
```

### 3. A 405 can omit supported methods from `Allow`

`cmapi/src/cmapi/main.py:245–247` adds HEAD to the correct GET route. Starlette 0.41.3 retains the first partial path match at `starlette/routing.py:737` and builds `Allow` from that one route at line 281. cmapi registers separate GET and POST routes for the namespace collection, and separate GET, PATCH, and DELETE routes for a namespace at `plugins/namespaces/router.py:177,211,256,282,336`.

| Request measured on head | Status | Actual `Allow` as a set | Supported methods |
|---|---:|---|---|
| `PUT /api/v1/version` | 405 | GET, HEAD | GET, HEAD |
| `HEAD /api/v1/clusters/CRC:probe` | 405 | POST | POST |
| `PUT /api/v1/clusters/CRC/namespaces` | 405 | GET, HEAD | GET, HEAD, POST |
| `PUT /api/v1/clusters/CRC/namespaces/demo` | 405 | GET, HEAD | GET, HEAD, PATCH, DELETE |
| `PUT` on a mounted static asset | 405 | header absent | GET, HEAD |

**Failure scenario:** A client using the namespace collection’s 405 response for method discovery concludes that creation is unsupported. This is an inherited limitation. The PR correctly adds HEAD to the first route’s set, but the resulting header still fails to describe the resource. RFC 9110 requires the 405 response to list the target resource’s currently supported methods. [RFC 9110 §15.5.6](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.6)

**Fix:** Add these imports and helper to `main.py`, then call `_install_allow_handler(app)` in `create_app` before `_serve_head_with_get(app)`. The default FastAPI exception handler still constructs the response.

```python
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException
from starlette.routing import Match


def _install_allow_handler(app: FastAPI) -> None:
    @app.exception_handler(405)
    async def method_not_allowed(request: Request, exc: HTTPException) -> Response:
        response = await http_exception_handler(request, exc)
        scope = request.scope
        if isinstance(scope.get("endpoint"), ConditionalStaticFiles):
            response.headers["Allow"] = "GET, HEAD"
        elif isinstance(scope.get("route"), APIRoute):
            methods: set[str] = set()
            for route in app.routes:
                if isinstance(route, APIRoute) and route.matches(scope)[0] == Match.PARTIAL:
                    methods.update(route.methods)
            if methods:
                response.headers["Allow"] = ", ".join(sorted(methods))
        return response
```

**Regression test:** The shared-path assertion failed before this fix and passed after it. I also measured the mounted asset changing from an absent header to `GET, HEAD`.

```python
def test_405_lists_the_methods_of_the_resource(world):
    client, *_ = world
    cases = [
        ("PUT", "/api/v1/version", {"GET", "HEAD"}),
        ("HEAD", "/api/v1/clusters/CRC:probe", {"POST"}),
        ("PUT", "/api/v1/clusters/CRC/namespaces", {"GET", "HEAD", "POST"}),
        ("PUT", "/api/v1/clusters/CRC/namespaces/demo",
         {"GET", "HEAD", "PATCH", "DELETE"}),
    ]
    for method, path, allowed in cases:
        response = client.request(method, path)
        assert response.status_code == 405
        assert set(response.headers["allow"].split(", ")) == allowed
```

### 4. Five documented POST action URLs also match a GET resource

`cmapi/src/cmapi/routers/requests.py:82` registers `/requests/{request_id}`. The parameter consumes an entire path segment, including a colon and action suffix. The POST routes are registered at lines 124, 157, 177, 199, and 232.

**Failure scenario, measured:** Anonymous HEAD on `/api/v1/requests/demo:approve` returned 401 from request-detail access, while HEAD on the genuine POST-only cluster probe returned 405 with `Allow: POST`. I measured the same overlap for `:reject`, `:cancel`, `:retry`, and `:revert`. GET selected the same detail route. An authorized detail read looks up the suffixed ID and ordinarily returns 404 for a missing row at `core/db/repo.py:76–79`. No POST action runs. The GET ambiguity predates this branch; #605 makes it visible through HEAD as well.

**Fix if the five documented actions are to be POST-only:** Reserve precisely their suffixes on the detail route. This intentionally also corrects GET method discovery on those five URLs. The OpenAPI document still compared equal to the committed contract with this change.

```diff
+from starlette.convertors import StringConvertor, register_url_convertor
+
+
+class RequestDetailConvertor(StringConvertor):
+    regex = r"(?![^/]*:(?:approve|reject|cancel|retry|revert)(?:/|$))[^/]+"
+
+
+register_url_convertor("request_detail", RequestDetailConvertor())
@@
-@router.read("/requests/{request_id}", summary="Get a request",
+@router.read("/requests/{request_id:request_detail}", summary="Get a request",
```

**Regression test:** All five GET/HEAD pairs changed from `401/401` to `405/405` in the routing probe. The ordinary detail URL continued to require sign-in.

```python
@pytest.mark.parametrize("action", ["approve", "reject", "cancel", "retry", "revert"])
def test_request_action_is_post_only(world, action):
    client, *_ = world
    path = f"/api/v1/requests/demo:{action}"
    for method in ("GET", "HEAD"):
        response = client.request(method, path)
        assert response.status_code == 405
        assert response.headers["allow"] == "POST"
    assert client.head("/api/v1/requests/demo").status_code == 401
```

### 5. A failed parity assertion prints the bearer token

`cmapi/tests/service/test_head_605.py:34` includes the entire request-header dictionary in the assertion message. A status regression on an authenticated conditional read therefore prints the signed fixture token in test output. The token is synthetic, but it is unnecessary for diagnosing the failure.

**Fix:**

```diff
-    assert head.status_code == get.status_code, (path, headers, get.status_code, head.status_code)
+    assert head.status_code == get.status_code, (path, get.status_code, head.status_code)
```

**Regression test:** Failed before and passed after the change using a harmless marker.

```python
def test_status_mismatch_keeps_authorization_out_of_failure():
    from types import SimpleNamespace

    client = SimpleNamespace(
        get=lambda *a, **kw: SimpleNamespace(status_code=401),
        head=lambda *a, **kw: SimpleNamespace(status_code=405),
    )
    with pytest.raises(AssertionError) as error:
        _same_answer(client, "/api/v1/tiers", {"Authorization": "Bearer test-marker"})
    assert "test-marker" not in str(error.value)
```

## Claims checked

**(a) Authorization and middleware — confirmed for the serving app.** `cmapi/src/cmapi/main.py:138–144` includes the core and enabled plugin routers with their sign-in dependency. Lines 228–232 add problem pages and optional docs, apply the HEAD helper, and immediately return the app. Lines 245–247 modify only `route.methods`. FastAPI has already built the dependency graph and request handler at `fastapi/routing.py:554,569`. `x-cmapi-permission` is documentation metadata at `core/docs.py:306`; runtime enforcement comes from `routers/__init__.py:46–56` and endpoint-specific checks such as `plugins/capacity/router.py:195–203`. Measured on head: 37 GET `APIRoute`s; all 23 permission-bearing reads returned `403/403` for GET/HEAD with a valid grantless token. `/me` separately requires an authenticated caller despite its null permission metadata at `routers/me.py:22–25`.

**Mounts and private docs — confirmed.** With private docs configured, anonymous GET/HEAD returned `401/401` on `/docs` and `/openapi.json`. The OAuth callback and problem pages returned `200/200`. The only mounts were `/static/swagger` and `/static/redoc`. Using existing export files as test assets, both mounts gave `200/200`, matching-tag `304/304`, and stale-tag `412/412`. Static assets and the callback are public for both methods. Evidence is `main.py:43–54,250–260,275–280,298–341` and `starlette/staticfiles.py:109–127`. I found no later route registration or mounted protected sub-app that HEAD reaches through a different check.

**Preconditions and observability — confirmed.** The four target reads passed the original test bodies’ 200, 304, and 412 cases, including stale `If-Match` alongside matching `If-None-Match`. The evaluation order is at `core/etag.py:153–169`; the call sites are `main.py:291–296`, `routers/me.py:78–84`, and `plugins/capacity/router.py:219–225`. On `/api/v1/version`, the middleware’s log calls recorded `GET` and `HEAD`, and their respective metric counters each advanced once. `core/observability.py:82,148,169–175` keeps HEAD as a distinct label. I retract the stronger claim that GET and HEAD both enforce a general read rate limit: `core/ratelimit.py:44–63` defines the limiter, but the source search found no production caller of `RateLimiter`. I verified common dispatch, not an enforced 429 policy.

**(b) Side effects — confirmed for audit, caches, metrics, and stream work.** In addition to finding 1, a cold authenticated HEAD on `/tiers` fetched JWKS once and called the key store’s `save` once. An immediate GET reused the keys; the counts remained `1/1`. Production wires in `DbKeyStore` at `core/context.py:87`, refreshes at `core/auth.py:60–75,100–112`, and writes keys or their fetched timestamp at `core/db/repo.py:376–383`. Directory reads can warm a person cache or obtain a Keycloak service credential at `core/identity/directory.py:63–80` and `core/identity/keycloak_admin.py:32–43`. These are source-level conclusions for the directory adapter.

I found no GET dispatch to the cluster token-renew job or caller last-seen update. The worker schedules renewal at `jobs/__init__.py:27,39` and re-enqueues it at `jobs/token_renew.py:97–104`. Policy-rejection recording updates `last_at` at `core/rejections.py:97`; the GET uses the read query at `core/rejections.py:100–105` via `plugins/policies/router.py:303–305`. I did not measure a production database or identity provider.

**(c) Document and contract — confirmed.** `core/docs.py:543–546` shallow-copies each GET/HEAD route and assigns a newly allocated method set. For all 37 GET routes, I checked that the document copy and its method set were distinct objects, the copy held `{GET}`, and the served route held `{GET, HEAD}`. **The route copy is transient.** `main.py:151–155` caches the generated schema; lines 281–289 separately cache serialized bytes and ETag by format. `check_documented` ran successfully. Registration occurs before HEAD augmentation at `main.py:144,231`.

| Comparison | Measured result |
|---|---|
| Served `/openapi.json`, base versus head, same configuration | Both 427,840 bytes, SHA-256 `917e48f3bad5467d0b3f883c206eb8d9ab7656c71fd3d55451e8adf951a888b8` |
| Committed `cmapi/contract/openapi.json`, base versus head | Both SHA-256 `f9b61dc6bd22ad2f609183c4d18c6f5bcea6237b5ba9af03bb6861d7e271c501` |
| Parsed served JSON versus parsed committed JSON | Equal on each branch |
| `bash head/cmapi/contract/gate.sh base/cmapi/contract/openapi.json head/cmapi/contract/openapi.json` | oasdiff 1.37.0, `No changes detected` |

The served compact encoding and committed pretty encoding account for the two different hashes. The existing contract test canonicalizes the response at `cmapi/tests/service/test_api_docs.py:379–386`.

**(d) Method refusal — confirmed for an unambiguous POST-only path.** `HEAD /api/v1/clusters/CRC:probe` returned 405, `Allow: POST`, and zero body bytes. `PUT /api/v1/version` advertised GET and HEAD. Findings 3 and 4 give the limits of generalizing either observation.

**(e) Response content and length — confirmed at the cmapi protocol boundary.** RFC 9110 §9.3.2 says, “The HEAD method is identical to GET except that the server MUST NOT send content in the response.” Section 8.6 permits `Content-Length` on HEAD only when it equals the corresponding GET’s size, expressed as the “decimal number of octets”. Omitting it is valid. Section 9.3.2 also allows omission of fields determined only during content generation. I retract the wording in `docs/02-technical-design-v2.md:123` that §9.1 itself requires every GET *route* to support HEAD. That section places the requirement on the general-purpose server. Applying it to every cmapi GET route is the project’s implementation choice. [RFC 9110 §9.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.1) · [§9.3.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.3.2) · [§8.6](https://www.rfc-editor.org/rfc/rfc9110.html#section-8.6)

I fed HTTP/1.1 requests with `Accept-Encoding: gzip` through both installed Uvicorn 0.32.1 protocol implementations against `create_app` and captured their serialized transport writes. This exercises the server’s actual body suppression independently of TestClient, which discards HEAD bytes itself at `starlette/testclient.py:362`. The transport was in memory because the sandbox denied binding a listener.

| Endpoint | GET | HEAD |
|---|---|---|
| `/openapi.json`, h11 and httptools | 427,840 content bytes, `Content-Length: 427840` | Zero bytes, `Content-Length: 427840` |
| `/api/v1/quotas:export`, h11 and httptools, empty row source | 114 CSV content bytes, 125 bytes with chunk framing, no `Content-Length` | Zero bytes, no `Content-Length` |

For streamed HEAD, h11 emitted `Transfer-Encoding: chunked`; httptools omitted it. Both sent zero bytes after the header terminator. This refutes literal all-header equality while satisfying the measured content requirement. The server paths are `uvicorn/protocols/http/h11_impl.py:495–507` and `httptools_impl.py:519–532`.

I found no gzip middleware in the cmapi app. The front door is a separate boundary: `cmapi-portal-ui/nginx/templates/cmapi.conf.template:103–106,115–127` enables gzip at server level, disables it for `/api/`, and lets `/openapi.json` inherit it. `deploy/tests/front-door-test.py:660–667` explicitly expects a sufficiently large JSON document to be compressed. **The deployed gzip GET/HEAD length and validator pairing remains unverified.** The origin’s 427,840-byte measurement does not establish the compressed representation’s length.

**(f) CORS — confirmed.** Fetch says, “A CORS-safelisted method is a method that is `GET`, `HEAD`, or `POST`.” HEAD alone does not require preflight. `Authorization` and `If-None-Match` make this request preflightable. `core/cors.py:28–30` allows HEAD and both headers, and `main.py:200–203` installs those lists. Starlette checks the requested method at `starlette/middleware/cors.py:120`. The listed origin received 200, its exact `Access-Control-Allow-Origin`, and `GET, HEAD, POST, PATCH, DELETE` in `Access-Control-Allow-Methods`. The unlisted origin received 400 with no allow-origin header. The authorized actual HEAD passed the original CORS test body. [Fetch Standard, methods](https://fetch.spec.whatwg.org/#methods) · [CORS-safelisted request headers](https://fetch.spec.whatwg.org/#cors-safelisted-request-header)

## Mutation results and coordinator reruns

**(g) Mutation evidence — confirmed with substitute fixtures.** I replayed the five changes from `wt-605-outputs/mutants.sh` in memory against the nine original test bodies. Each case built a fresh application with real routes, roles, token verification, and response handling. I substituted configuration and backing-service fixtures because the export was read-only in this sandbox and PostgreSQL loopback access returned `EPERM`. These numbers are independent assertion replays, not PostgreSQL-backed pytest passes.

| Variant | Failed out of 9 | Observation |
|---|---:|---|
| Unmodified head | 0 | Control |
| M1 omit `_serve_head_with_get` call | 9 | Killed |
| M2 retain HEAD in document | 1 | Document test |
| M3 remove HEAD from CORS | 1 | Portal preflight |
| M4 add HEAD only on four conditional reads | 2 | Route sweep and document/route invariant |
| M5 strip HEAD from live route while documenting | 4 | JSON, YAML, route sweep, document invariant |
| M6 skip tier permission for signed-in HEAD | **0** | Survived; finding 2’s grantless probe caught `403/200` |
| M7 add HEAD to the POST-only cluster probe | 1 | Document test; direct HEAD also changed from 405 to 401 |

The ordinary pytest invocation reported **nine setup errors**. Creation of the requested export-local pytest temporary directory was denied, and a separate connection probe to the test PostgreSQL port also returned `Operation not permitted`. The coordinator should run all nine original node IDs with their normal fixtures. Each line below is relative to `head/`.

```text
cmapi/tests/service/test_head_605.py::test_head_on_a_conditional_read_is_its_get_without_content[/openapi.json]
cmapi/tests/service/test_head_605.py::test_head_on_a_conditional_read_is_its_get_without_content[/openapi.yaml]
cmapi/tests/service/test_head_605.py::test_head_on_a_conditional_read_is_its_get_without_content[/api/v1/metadata-keys]
cmapi/tests/service/test_head_605.py::test_head_on_a_conditional_read_is_its_get_without_content[/api/v1/capacity]
cmapi/tests/service/test_head_605.py::test_head_is_authorized_exactly_as_get[/api/v1/metadata-keys]
cmapi/tests/service/test_head_605.py::test_head_is_authorized_exactly_as_get[/api/v1/capacity]
cmapi/tests/service/test_head_605.py::test_every_get_route_answers_head_as_its_get
cmapi/tests/service/test_head_605.py::test_head_is_not_an_operation_of_the_document
cmapi/tests/service/test_head_605.py::test_a_head_from_the_listed_portal_passes_its_preflight
```

Codex session ID: 01a20b04-d2f4-70b2-808f-110dc21281db
Resume in Codex: codex resume 01a20b04-d2f4-70b2-808f-110dc21281db
