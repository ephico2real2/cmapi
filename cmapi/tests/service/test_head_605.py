"""HEAD on every GET route (#605): main.py, _head_for_each_get; core/docs.py, build_openapi; core/cors.py, METHODS.

RFC 9110 (https://www.rfc-editor.org/rfc/rfc9110.txt, read 2026-11-23), section 9.1: "All general-purpose servers MUST
support the methods GET and HEAD." Section 9.3.2: "The HEAD method is identical to GET except that the server MUST NOT send
content in the response", and "The server SHOULD send the same header fields in response to a HEAD request as it would
have sent if the request method had been GET." Section 13.2.1: conditional request header fields are "usable with the
HEAD method (to keep HEAD's semantics consistent with those of GET)". FastAPI 0.115.6's APIRoute takes only the methods
it is given (fastapi/routing.py:494), where Starlette's Route adds HEAD to a GET (starlette/routing.py:244-246), so every
GET of cmapi answered HEAD with 405.
"""
from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute

from conftest import build_world
from test_cors import PORTAL, preflight, with_instance
from test_flow import OLA, auth

CONDITIONAL = ["/openapi.json", "/openapi.yaml", "/api/v1/metadata-keys", "/api/v1/capacity"]
# What HEAD must repeat of GET: the status and these headers (section 9.3.2), with no content.
SAME = ("etag", "cache-control", "content-length", "content-type", "www-authenticate")


def _credentials(path: str, keys) -> dict[str, str]:
    return auth(keys, "ola", **OLA) if path.startswith("/api/") else {}


def _same_answer(client, path: str, headers) -> tuple[int, dict[str, str | None]]:
    """GET and HEAD of `path` with the same request headers: HEAD has GET's status and SAME headers, and no content."""
    get, head = client.get(path, headers=headers), client.head(path, headers=headers)
    assert head.status_code == get.status_code, (path, headers, get.status_code, head.status_code)
    assert head.content == b"", (path, head.content[:200])
    seen = {h: get.headers.get(h) for h in SAME}
    assert {h: head.headers.get(h) for h in SAME} == seen, (path, get.status_code)
    return get.status_code, seen


@pytest.mark.parametrize("path", CONDITIONAL)
def test_head_on_a_conditional_read_is_its_get_without_content(world, path):
    client, *_, keys = world
    credentials = _credentials(path, keys)
    status, headers = _same_answer(client, path, credentials)
    etag = headers["etag"]
    assert status == 200 and etag and headers["cache-control"] and int(headers["content-length"]) > 0
    assert _same_answer(client, path, {**credentials, "If-None-Match": etag})[0] == 304
    assert _same_answer(client, path, {**credentials, "If-None-Match": "*"})[0] == 304
    assert _same_answer(client, path, {**credentials, "If-Match": '"stale"'})[0] == 412      # a problem, on HEAD too
    assert _same_answer(client, path, {**credentials, "If-Match": '"stale"', "If-None-Match": etag})[0] == 412
    assert _same_answer(client, path, {**credentials, "If-Match": etag, "If-None-Match": etag})[0] == 304


@pytest.mark.parametrize("path", ["/api/v1/metadata-keys", "/api/v1/capacity"])
def test_head_is_authorized_exactly_as_get(world, path):
    """The same route answers both methods, so HEAD has GET's sign-in and permission: 401 with WWW-Authenticate without a
    token, 403 for a caller without the permission."""
    client, *_, keys = world
    assert _same_answer(client, path, {})[0] == 401
    assert _same_answer(client, path, {"Authorization": "Bearer not-a-token"})[0] == 401
    assert _same_answer(client, path, auth(keys, "nobody", roles=[], groups=[]))[0] == 403


def test_every_get_route_answers_head_as_its_get(world):
    """Every GET route of the app, with no token, a placeholder for each path parameter: HEAD has GET's status and headers.
    A route that HEAD answers with 405 fails here, whoever added it."""
    client, *_ = world
    paths = sorted({r.path for r in client.app.routes if isinstance(r, APIRoute) and "GET" in r.methods})
    assert len(paths) > 30, paths
    for path in paths:
        url = re.sub(r"\{[^}]+\}", "x", path)
        status, _ = _same_answer(client, url, {})
        assert status != 405, url


def test_head_is_not_an_operation_of_the_document(world):
    """HEAD is GET without content, not an operation of its own: the document lists the GETs only, and the committed
    contract is unchanged (test_api_docs.py holds the served document equal to cmapi/contract/openapi.json)."""
    client, *_ = world
    spec = client.get("/openapi.json").json()
    assert not [path for path, methods in spec["paths"].items() if "head" in methods]
    assert all("HEAD" in r.methods for r in client.app.routes if isinstance(r, APIRoute) and "GET" in r.methods)


def test_a_head_from_the_listed_portal_passes_its_preflight(test_config, tmp_path, fresh_db, keys, monkeypatch):
    """A HEAD with Authorization from another origin is preflighted (Fetch: Authorization is not a CORS-safelisted request
    header). Starlette's CORSMiddleware refuses a preflight whose method is not in allow_methods with 400."""
    d = with_instance(test_config, tmp_path, lambda i: i.update({"cors": {"allowedOrigins": [PORTAL]}}))
    with build_world(d, keys, monkeypatch) as (client, *_):
        r = preflight(client, PORTAL, method="HEAD", headers="authorization,if-none-match", path="/api/v1/capacity")
        assert r.status_code == 200, r.text
        assert "HEAD" in r.headers["access-control-allow-methods"].split(", ")
        h = client.head("/api/v1/capacity", headers={"Origin": PORTAL, **auth(keys, "ola", **OLA)})
        assert h.status_code == 200 and h.headers["access-control-allow-origin"] == PORTAL
