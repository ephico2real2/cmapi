"""FastAPI and Starlette at versions that no published advisory affects (#651), and what the upgrade changes for cmapi.

cmapi pinned fastapi==0.115.6, which installed Starlette 0.41.3, and the image installs from pyproject.toml with no lock
file (Containerfile, `pip install .`), so Starlette is pinned on its own. The GitHub advisories for Starlette, read with
`gh api /advisories -X GET -f ecosystem=pip -f affects=starlette` on 2026-11-24 (docs/reviews/2026-11-24-issue-651), and the
first version that each one names as patched, are ADVISORIES. GHSA-jp82-jpqv-5vv3 names the package "Starlette" and is
missing from the answer for `affects=starlette@0.41.3`; it is listed under `affects=starlette`.

GHSA-7f5h-v6xp-fcq8 (CVE-2025-62727, CVSS 7.5) reaches cmapi without a token through /static (#649): "An unauthenticated
attacker can send a crafted HTTP Range header that triggers quadratic-time processing in Starlette's `FileResponse` Range
parsing/merging logic" (https://github.com/advisories/GHSA-7f5h-v6xp-fcq8). Starlette 1.0.0's release notes also list three
Range fixes that #649 found (https://starlette.dev/release-notes/, 1.0.0, read 2026-11-24): "Include `bytes` unit in
`Content-Range` header on 416 responses", "Set `Content-Type` instead of `Content-Range` on multi-range responses" and
"Use CRLF line endings in multipart byterange boundaries".
"""
from __future__ import annotations

import json
import time
import tomllib
from importlib import metadata
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from packaging.requirements import Requirement
from packaging.version import Version
from starlette.applications import Starlette
from starlette.responses import FileResponse, MalformedRangeHeader
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from conftest import build_world
from test_api_docs import bundles  # noqa: F401  (the fixture: the files the image holds)
from test_flow import NS, OLA, auth

# (advisory, CVE, package, first patched version), from GitHub's advisory database, 2026-11-24.
ADVISORIES = [
    ("GHSA-7f5h-v6xp-fcq8", "CVE-2025-62727", "starlette", "0.49.1"),   # high: O(n^2) Range parse in FileResponse
    ("GHSA-82w8-qh3p-5jfq", "CVE-2026-54283", "starlette", "1.3.1"),    # high: urlencoded form limits ignored
    ("GHSA-wqp7-x3pw-xc5r", "CVE-2026-48818", "starlette", "1.1.0"),    # high: UNC paths in StaticFiles, Windows only
    ("GHSA-86qp-5c8j-p5mr", "CVE-2026-48710", "starlette", "1.0.1"),    # medium: Host header poisons request.url.path
    ("GHSA-x746-7m8f-x49c", "CVE-2026-48817", "starlette", "1.1.0"),    # medium: any method dispatched to HTTPEndpoint
    ("GHSA-2c2j-9gv5-cj73", "CVE-2025-54121", "starlette", "0.47.2"),   # medium: multipart rollover blocks the loop
    ("GHSA-jp82-jpqv-5vv3", "CVE-2026-54282", "starlette", "1.3.0"),    # low: a path without "/" poisons request.url
]
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
STATIC_FILE = "/static/swagger/swagger-ui-bundle.js"
WRITE = "/api/v1/clusters/CRC/namespaces"
# The CVE's proof of concept ("0" * n + "a-") at the size of header line that the front door accepts:
# large_client_header_buffers 4 16k (cmapi-portal-ui/nginx/templates/cmapi.conf.template).
CVE_RANGE = "bytes=" + "0" * 16_000 + "a-"
# Starlette 0.41.3 parsed CVE_RANGE in 3.57 s, and 1.10.0 in 0.00013 s (best of three, measured on the development Mac,
# docs/reviews/2026-11-24-issue-651/outputs/range-probe-before-after.txt). The bound sits far from both.
PARSE_BOUND_S = 0.25


@pytest.mark.parametrize("advisory, cve, package, patched", ADVISORIES, ids=[a[0] for a in ADVISORIES])
def test_the_installed_package_is_patched(advisory, cve, package, patched):
    installed = Version(metadata.version(package))
    assert installed >= Version(patched), f"{package} {installed} is in {advisory} ({cve}), patched in {patched}"


def test_pyproject_pins_a_patched_starlette():
    """The image resolves the dependencies of pyproject.toml when it is built, so FastAPI's own `starlette>=...` could
    pick any version; the pin decides it."""
    dependencies = [Requirement(d) for d in tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]]
    pins = {r.name: r for r in dependencies}
    assert "starlette" in pins, "pyproject.toml does not pin starlette"
    (spec,) = pins["starlette"].specifier
    assert spec.operator == "==", spec
    assert all(Version(spec.version) >= Version(patched) for *_, package, patched in ADVISORIES if package == "starlette")
    assert Version(spec.version) == Version(metadata.version("starlette")), "the tests do not run the pinned version"


def test_the_range_parse_of_the_cve_is_not_quadratic():
    elapsed = []
    for _ in range(3):
        start = time.perf_counter()
        with pytest.raises(MalformedRangeHeader):
            FileResponse._parse_range_header(CVE_RANGE, 1_000_000)
        elapsed.append(time.perf_counter() - start)
    assert min(elapsed) < PARSE_BOUND_S, f"{min(elapsed):.3f} s to parse a 16 kB Range header"


def test_a_static_file_answers_the_cve_range_at_once(bundles, world):
    """Through the app, with no token: the request that the advisory describes."""
    client, *_ = world
    elapsed = []
    for _ in range(3):
        start = time.perf_counter()
        response = client.get(STATIC_FILE, headers={"Range": CVE_RANGE})
        elapsed.append(time.perf_counter() - start)
        assert response.status_code != 500, response.text
    assert min(elapsed) < PARSE_BOUND_S, f"{min(elapsed):.3f} s for GET {STATIC_FILE} with a 16 kB Range header"


def test_the_range_answers_that_starlette_1_fixed(bundles):
    """RFC 9110 (https://www.rfc-editor.org/rfc/rfc9110.txt): a 416 sends `Content-Range: bytes */<length>` (section 14.4,
    `unsatisfied-range = "*/" complete-length` after `range-unit SP`); a multipart 206 sends Content-Type
    multipart/byteranges and "MUST NOT generate a Content-Range header field in the HTTP header section of a multiple part
    response" (section 15.3.7.2); its parts are framed with CRLF (section 15.3.7.2, RFC 2046 section 5.1.1).

    Starlette's own StaticFiles, over the same bundle: cmapi's /static ignores Range (#649, test_static_range_649.py)."""
    client = TestClient(Starlette(routes=[Mount("/static/swagger", StaticFiles(directory=bundles / "swagger-ui"))]))
    length = len(client.get(STATIC_FILE).content)
    unsatisfiable = client.get(STATIC_FILE, headers={"Range": f"bytes={length + 10}-"})
    assert (unsatisfiable.status_code, unsatisfiable.headers.get("content-range")) == (416, f"bytes */{length}")
    parts = client.get(STATIC_FILE, headers={"Range": "bytes=0-1,4-5"})
    assert parts.status_code == 206
    assert parts.headers["content-type"].startswith("multipart/byteranges; boundary=")
    assert "content-range" not in parts.headers
    boundary = parts.headers["content-type"].split("boundary=", 1)[1]
    assert parts.content.startswith(f"--{boundary}\r\n".encode()), parts.content[:80]


def test_a_route_of_an_included_router_is_one_of_api_routes():
    """FastAPI 0.137.0: an included router is one entry of app.routes, no longer its copied routes (release notes,
    "Specific Breaking Changes"). api_routes lists each route as it is served, with the including router's prefix."""
    from cmapi.core.docs import api_routes

    inner = APIRouter(prefix="/inner")

    @inner.get("/thing")
    def thing() -> dict[str, str]:
        return {}

    app = FastAPI()
    app.include_router(inner, prefix="/outer")
    served = {(r.path, frozenset(r.methods)) for r in api_routes(app)}
    assert ("/outer/inner/thing", frozenset({"GET"})) in served, served


def test_an_app_changes_no_route_of_a_router_that_it_includes():
    """FastAPI 0.137.0 keeps an included router's routes as they are, so each app of the process that includes a router
    serves that router's route objects. Production builds one app per process (main.py, run), and the service suite builds
    many: when _serve_head_with_get added HEAD to an included route, each app after the first had it already, and a mutant
    that left HEAD off the served route passed the whole of test_head_605.py (#654 review). An included router's GET
    declares HEAD where it is made (core/docs.py, DocumentedRouter._register), and _serve_head_with_get adds it to the
    app's own routes only."""
    from cmapi.main import _serve_head_with_get

    shared = APIRouter()

    @shared.get("/thing")
    def thing() -> dict[str, str]:
        return {}

    app = FastAPI()
    app.include_router(shared)

    @app.get("/own")
    def own() -> dict[str, str]:
        return {}

    _serve_head_with_get(app)
    assert shared.routes[0].methods == {"GET"}
    assert TestClient(app).head("/own").status_code == 200


def test_a_body_is_read_as_json_only_with_a_json_content_type(world):
    """FastAPI 0.132.0: "Now FastAPI checks, by default, that JSON requests have a `Content-Type` header with a valid JSON
    value, like `application/json`, and rejects requests that don't" (https://fastapi.tiangolo.com/release-notes/, read
    2026-11-24). cmapi keeps that default (#654 review): the document declares application/json for each body, and every
    client in the repository sends it. A body with no Content-Type was read as JSON on FastAPI 0.115.6 (200); it is now
    422 validation-failed, as a text/plain one already was."""
    client, *_, keys = world
    url, body, signed_in = f"{WRITE}?dryRun=true", json.dumps(NS).encode(), auth(keys, "ola", **OLA)
    assert client.post(url, content=body, headers={**signed_in, "Content-Type": "application/json"}).status_code == 200
    for sent in ({}, {"Content-Type": "text/plain"}):
        r = client.post(url, content=body, headers={**signed_in, **sent})
        assert (r.status_code, r.json().get("code")) == (422, "validation-failed"), (sent, r.text[:300])


def test_an_app_that_ends_closes_its_database_connections(test_config, fresh_db, keys, monkeypatch):
    """FastAPI 0.140.0 keeps each dependency's callable in a process-wide lru_cache ("Reduce memory usage in
    dependencies", PR #16049; 4096 entries since 0.140.1, PR #16062), and through them an app's AppContext stays alive
    after its lifespan ends. The service suite builds an app per test in one process, so each app kept its pool open: 99
    connections at the peak and "sorry, too many clients already", where FastAPI 0.115.6 peaked at 15 (#654 review).
    ctx.shutdown, which the lifespan runs, closes them."""
    with build_world(test_config, keys, monkeypatch) as (client, ctx, *_):
        assert client.get("/readyz").status_code == 200
        assert ctx.db.engine.pool.checkedin() >= 1
    assert ctx.db.engine.pool.checkedin() == 0
