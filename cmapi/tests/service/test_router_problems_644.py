"""#644: the 404 and 405 that no route makes are RFC 9457 problems, like every other refusal of cmapi.

Starlette 0.41.3's router raises HTTPException(404) when no route matches the path (starlette/routing.py:651) and
HTTPException(405) when a route matches it with another method (:283); StaticFiles raises its own under /static
(starlette/staticfiles.py:114, :123, :149). FastAPI 0.115.6's default handler answered those with {"detail": ...} as
application/json (fastapi/exception_handlers.py:11-17). RFC 9457 (https://www.rfc-editor.org/rfc/rfc9457.txt, read
2026-11-24), section 3: "When serialized in a JSON document, that format is identified with the "application/problem+json"
media type." docs/02, "Problem type URIs": the type of a problem is the base and its code, and /problems/{code} documents it.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from cmapi.core.docs import PROBLEMS
from cmapi.core.errors import BASE
from conftest import build_world
from test_api_docs import bundles  # noqa: F401  (the fixture: Swagger UI's and ReDoc's files, so /static is mounted)
from test_flow import OLA, auth

FIELDS = {"type", "title", "status", "detail", "code"}

# (method, path, status, code, Allow as a set or None). The first four are the issue's measured cases on CRC.
ROUTER_CASES = [
    ("PUT", "/api/v1/clusters/CRC/namespaces", 405, "method-not-allowed", {"GET", "HEAD", "POST"}),
    ("GET", "/api/v1/requests/req-20261121-0005:approve", 405, "method-not-allowed", {"POST"}),
    ("DELETE", "/api/v1/version", 405, "method-not-allowed", {"GET", "HEAD"}),
    ("GET", "/api/v1/no-such-path", 404, "not-found", None),
    ("PUT", "/api/v1/clusters/CRC/namespaces/demo", 405, "method-not-allowed", {"GET", "HEAD", "PATCH", "DELETE"}),
    ("GET", "/no-such-path", 404, "not-found", None),
    ("GET", "/problems/a/b", 404, "not-found", None),
    ("POST", "/problems", 405, "method-not-allowed", {"GET", "HEAD"}),
    ("DELETE", "/openapi.json", 405, "method-not-allowed", {"GET", "HEAD"}),
    ("PUT", "/docs/changelog", 405, "method-not-allowed", {"GET", "HEAD"}),
    ("GET", "/docs/no-such-page", 404, "not-found", None),
]
# Under /static: StaticFiles answers a file it does not have and a method it does not take; a mount that does not exist is
# the router's 404.
STATIC_CASES = [
    ("GET", "/static/swagger/no-such-file.js", 404, "not-found", None),
    ("GET", "/static/redoc/" + "x" * 300, 404, "not-found", None),          # ENAMETOOLONG: staticfiles.py:123
    ("POST", "/static/swagger/swagger-ui-bundle.js", 405, "method-not-allowed", {"GET", "HEAD"}),
    ("DELETE", "/static/redoc/redoc.standalone.js", 405, "method-not-allowed", {"GET", "HEAD"}),
    ("GET", "/static/no-such-mount/x.js", 404, "not-found", None),
]


def _assert_problem(client, method: str, path: str, status: int, code: str, allow: set[str] | None) -> None:
    r = client.request(method, path)
    where = (method, path, r.status_code, r.headers.get("content-type"), r.text[:200])
    assert r.status_code == status, where
    assert r.headers["content-type"] == "application/problem+json", where
    body = r.json()
    assert set(body) == FIELDS, where
    assert (body["status"], body["code"], body["type"], body["title"]) == (status, code, BASE + code, code.replace("-", " ")), where
    assert PROBLEMS[code][0] == status and body["detail"] == PROBLEMS[code][1], where
    if allow is None:
        assert "allow" not in r.headers, where
    else:
        assert set(r.headers["allow"].split(", ")) == allow and len(r.headers.get_list("allow")) == 1, where
    page = client.get(urlsplit(body["type"]).path)          # the type resolves on the instance, with no token
    assert page.status_code == 200 and f'<h1 id="code">{code}</h1>' in page.text, (code, page.status_code)


def _assert_head_answers_as_get(client, path: str) -> None:
    """RFC 9110, section 9.3.2: HEAD is GET without content, with GET's status and header fields. The content is uvicorn's
    to drop (main.py, _serve_head_with_get), and TestClient drops it too before a test sees it (starlette/testclient.py:362),
    so this checks the status and the header fields."""
    get, head = client.get(path), client.head(path)
    assert head.status_code == get.status_code, (path, get.status_code, head.status_code)
    for field in ("content-type", "content-length", "allow"):
        assert head.headers.get(field) == get.headers.get(field), (path, field)


@pytest.mark.parametrize("method, path, status, code, allow", ROUTER_CASES)
def test_a_refusal_of_the_router_is_a_problem(world, method, path, status, code, allow):
    client, *_ = world
    _assert_problem(client, method, path, status, code, allow)


@pytest.mark.parametrize("method, path, status, code, allow", STATIC_CASES)
def test_a_refusal_under_static_is_a_problem(bundles, test_config, fresh_db, keys, monkeypatch,  # noqa: F811
                                             method, path, status, code, allow):
    with build_world(test_config, keys, monkeypatch) as (client, *_):
        _assert_problem(client, method, path, status, code, allow)


def test_head_of_each_case_has_the_status_and_header_fields_of_get(bundles, test_config, fresh_db, keys, monkeypatch):  # noqa: F811
    """HEAD of each path: a 404 or a 405 keeps its status, its problem media type and its Allow. The paths
    with a GET route answer HEAD as that GET does (#605): the namespace list needs a token (401), the version is public."""
    with build_world(test_config, keys, monkeypatch) as (client, *_):
        paths = sorted({path for _, path, *_ in ROUTER_CASES + STATIC_CASES})
        for path in paths:
            _assert_head_answers_as_get(client, path)
        assert client.head("/api/v1/requests/req-20261121-0005:approve").headers["allow"] == "POST"
        assert client.head("/api/v1/no-such-path").headers["content-type"] == "application/problem+json"
        assert client.head("/static/swagger/no-such-file.js").status_code == 404
        assert client.head("/api/v1/clusters/CRC/namespaces").status_code == 401
        assert client.head("/api/v1/version").status_code == 200


def test_a_route_keeps_its_own_problem(world):
    """A Problem that a route raises is not an HTTPException, so the router's handlers leave it as it was: the code that
    names what is missing, and its own detail."""
    client, *_, keys = world
    page = client.get("/problems/no-such-type")
    assert page.status_code == 404 and page.json()["code"] == "object-not-found"
    cluster = client.get("/api/v1/capacity?clusterId=OCP_NOPE", headers=auth(keys, "ola", **OLA))
    assert cluster.status_code == 404 and cluster.headers["content-type"] == "application/problem+json", cluster.text
    assert cluster.json()["code"] == "cluster-not-found" and "OCP_NOPE" in cluster.json()["detail"], cluster.text
