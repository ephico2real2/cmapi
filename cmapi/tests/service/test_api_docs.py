"""The API documentation that docs/01 specifies ("API documentation: Swagger UI and ReDoc"), on the running app.

One section per defect: #127 (no CDN), #128 BUG-01 (tags and groups), #129 BUG-02 (curl samples), #130 BUG-03 (changelog),
#132 BUG-05 (ETag), #133 BUG-06 (parameters), #134 BUG-07 (docs.public). #131 BUG-04 is the CI job `api-contract`; its
part here is that the committed contract is the one the code serves.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shlex
import tarfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, Query

import cmapi.main as main_mod
from cmapi import __version__
from cmapi.core.changelog import changelog_html, load_changelog
from cmapi.core.docs import TAG_GROUPS, DocumentedRouter, build_openapi, check_documented, plugin_routers
from cmapi.core.models import Health
from cmapi.tools.docs_assets import BUNDLES, main as docs_assets_main, pinned
from conftest import build_world

CMAPI = Path(__file__).resolve().parents[2]
CONTRACT = CMAPI / "contract" / "openapi.json"
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json", "/openapi.yaml", "/docs/changelog")


@pytest.fixture
def bundles(tmp_path, monkeypatch) -> Path:
    """A static directory with the files the image holds, so /docs and /redoc have something to serve."""
    for name in ("swagger-ui/swagger-ui-bundle.js", "swagger-ui/swagger-ui.css", "swagger-ui/favicon-32x32.png",
                 "redoc/redoc.standalone.js"):
        f = tmp_path / "static" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("/* test bundle */")
    monkeypatch.setattr(main_mod, "STATIC", tmp_path / "static")
    return tmp_path / "static"


def operations(spec: dict):
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            yield method, path, op


# ---------------------------------------------------------------- #127: the bundles of the image, never a CDN

def test_the_pages_load_only_from_this_server(bundles, test_config, fresh_db, keys, monkeypatch):
    with build_world(test_config, keys, monkeypatch) as (client, *_):
        for page in ("/docs", "/redoc"):
            r = client.get(page)
            assert r.status_code == 200, page
            outside = re.findall(r"""(?:src|href)=["'](https?://[^"']+)""", r.text)
            assert outside == [], f"{page} loads from outside this server: {outside}"
        assert client.get("/static/swagger/swagger-ui-bundle.js").status_code == 200
        assert client.get("/static/redoc/redoc.standalone.js").status_code == 200


def test_without_the_bundles_the_pages_say_so_and_name_the_command(tmp_path, test_config, fresh_db, keys, monkeypatch):
    monkeypatch.setattr(main_mod, "STATIC", tmp_path / "absent")
    with build_world(test_config, keys, monkeypatch) as (client, *_):
        for page in ("/docs", "/redoc"):
            r = client.get(page)
            assert r.status_code == 503 and r.headers["content-type"] == "application/problem+json", page
            assert r.json()["code"] == "docs-assets-missing" and "cmapi-tools docs-assets" in r.json()["detail"]
        assert client.get("/openapi.json").status_code == 200       # the document needs no bundle


def _npm_tarball(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def registry():
    """A stand-in npm registry on 127.0.0.1 that serves the tarballs given to it."""
    files: dict[str, bytes] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = files.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", files
    server.shutdown()


def test_docs_assets_fetches_what_the_containerfile_pins_and_refuses_another_hash(tmp_path, registry):
    url, files = registry
    swagger = _npm_tarball({"package/swagger-ui-bundle.js": b"S", "package/swagger-ui.css": b"C", "package/favicon-32x32.png": b"F"})
    redoc = _npm_tarball({"package/bundles/redoc.standalone.js": b"R"})
    files["/swagger-ui-dist/-/swagger-ui-dist-9.9.9.tgz"] = swagger
    files["/redoc/-/redoc-8.8.8.tgz"] = redoc
    cf = tmp_path / "Containerfile"

    def write(redoc_sha: str) -> None:
        cf.write_text(f"ARG SWAGGER_UI_VERSION=9.9.9\nARG SWAGGER_UI_SHA256={hashlib.sha256(swagger).hexdigest()}\n"
                      f"ARG REDOC_VERSION=8.8.8\nARG REDOC_SHA256={redoc_sha}\n")

    write("0" * 64)
    with pytest.raises(SystemExit, match="Nothing was written"):
        docs_assets_main(["--static-dir", str(tmp_path / "s"), "--containerfile", str(cf), "--registry", url])
    assert not (tmp_path / "s").exists(), "a file was written although one hash did not match"
    write(hashlib.sha256(redoc).hexdigest())
    docs_assets_main(["--static-dir", str(tmp_path / "s"), "--containerfile", str(cf), "--registry", url])
    assert (tmp_path / "s/swagger-ui/swagger-ui-bundle.js").read_bytes() == b"S"
    assert (tmp_path / "s/redoc/redoc.standalone.js").read_bytes() == b"R"


def test_docs_assets_reads_the_real_containerfile_and_unpacks_what_it_unpacks():
    text = (CMAPI / "Containerfile").read_text()
    pins = pinned(CMAPI / "Containerfile")
    assert re.fullmatch(r"\d+\.\d+\.\d+", pins["SWAGGER_UI"][0]) and re.fullmatch(r"[0-9a-f]{64}", pins["SWAGGER_UI"][1])
    assert re.fullmatch(r"\d+\.\d+\.\d+", pins["REDOC"][0]) and re.fullmatch(r"[0-9a-f]{64}", pins["REDOC"][1])
    for _, _, _, members in BUNDLES:
        for member in members:
            assert member in text, f"the Containerfile does not unpack {member}"


# ---------------------------------------------------------------- #128 BUG-01: tags, groups, plugin versions

def test_each_tag_has_a_description_and_is_in_exactly_one_of_the_six_groups(world):
    client, *_ = world
    spec = client.get("/openapi.json").json()
    groups = spec["x-tagGroups"]
    assert [g["name"] for g in groups] == list(TAG_GROUPS) and len(TAG_GROUPS) == 6
    used = {t for _, _, op in operations(spec) for t in op["tags"]}
    described = {t["name"]: t for t in spec["tags"]}
    assert used == set(described), "a tag has operations and no description, or a description and no operation"
    for name, tag in described.items():
        assert len(tag["description"]) > 20 and tag["x-plugin-version"], name
        assert sum(name in g["tags"] for g in groups) == 1, f"{name} is not in exactly one group"
    for method, path, op in operations(spec):
        assert op.get("x-plugin-version") == described[op["x-cmapi-plugin"]]["x-plugin-version"], f"{method} {path}"


def test_a_plugin_that_is_not_included_is_not_in_the_spec():
    def router(plugin: str, group: str) -> DocumentedRouter:
        r = DocumentedRouter(plugin, prefix="/api/v1", version="1.2.3", description=f"What the {plugin} plugin does.", group=group)

        @r.read(f"/{plugin}", summary=f"Read {plugin}", permission=None, response_model=Health)
        def read():
            """Reads it."""

        return r

    kept, left_out = router("alpha", "Access"), router("beta", "Admin")
    app = FastAPI(title="t", version="0")
    app.include_router(kept)
    spec = build_openapi(app, plugin_routers([kept]), "https://cmapi.test")
    assert [t["name"] for t in spec["tags"]] == ["alpha"] and spec["x-tagGroups"] == [{"name": "Access", "tags": ["alpha"]}]
    assert "/api/v1/beta" not in spec["paths"] and left_out.plugin not in json.dumps(spec)


def test_a_router_must_name_a_known_group_and_say_what_it_does():
    with pytest.raises(RuntimeError, match="group"):
        DocumentedRouter("x", version="1", description="Something that it does.", group="Miscellaneous")
    with pytest.raises(RuntimeError, match="no description"):
        DocumentedRouter("x", version="1", description=" ", group="Admin")


# ---------------------------------------------------------------- #129 BUG-02: one curl sample per operation

def _curl(source: str) -> tuple[str, str, dict[str, str], str | None]:
    """The method, URL, headers and body of a sample, read as a shell would read it ($TOKEN left as it is)."""
    words = shlex.split(source)
    assert words[0] == "curl" and words[1] == "-X", source
    method, url, headers, body, i = words[2], words[3], {}, None, 4
    while i < len(words):
        if words[i] == "-H":
            name, _, value = words[i + 1].partition(": ")
            headers[name] = value
        elif words[i] == "-d":
            body = words[i + 1]
        else:
            raise AssertionError(f"unexpected {words[i]} in {source}")
        i += 2
    return method, url, headers, body


def test_each_operation_has_one_curl_sample_that_the_app_accepts(world):
    client, ctx, _, _, _, keys = world
    spec = client.get("/openapi.json").json()
    server = spec["servers"][0]["url"]
    token = keys.token("ada", roles=["cmapi-admin"], groups=["/cmapi/app-cmapi-rbac-platform"])
    count = 0
    for method, path, op in operations(spec):
        samples = op.get("x-codeSamples")
        assert samples and len(samples) == 1 and samples[0]["lang"] == "Shell" and samples[0]["label"] == "curl", f"{method} {path}"
        m, url, headers, body = _curl(samples[0]["source"])
        assert m == method.upper() and url.startswith(server + "/api/v1/") and "{" not in url, samples[0]["source"]
        assert ("Authorization" in headers) == bool(op.get("security")), f"{method} {path}"
        names = {p["name"] for p in op.get("parameters", [])}
        for header in ("Idempotency-Key", "If-Match"):
            assert (header in headers) == (header in names), f"{method} {path}: {header}"
        if "Authorization" in headers:
            assert headers["Authorization"] == "Bearer $TOKEN"
            headers["Authorization"] = f"Bearer {token}"
        if "Idempotency-Key" in headers:
            headers["Idempotency-Key"] = str(uuid.uuid4())       # the sample's key is an example; a second run needs its own
        r = client.request(m, url[len(server):], headers=headers, content=body)
        code = r.json().get("code") if r.headers.get("content-type", "").startswith("application/problem+json") else None
        # The sample names objects that this empty world does not hold, so 404, 409 and 412 are what a real call would get.
        # What it must never get is a refusal for something the sample left out or wrote wrongly.
        assert r.status_code not in (400, 401, 405, 428) and code not in ("validation-failed", "idempotency-key-required",
                                                                         "precondition-required", "unauthenticated"), \
            f"{samples[0]['source']} -> {r.status_code} {r.text[:300]}"
        count += 1
    assert count == len(list(operations(spec))) and count >= 31


# ---------------------------------------------------------------- #130 BUG-03: /docs/changelog

def test_the_changelog_page_is_served_and_says_what_is_released(world):
    client, *_ = world
    r = client.get("/docs/changelog")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert __version__ in r.text
    data = load_changelog()
    if not data["releases"]:
        assert 'id="no-release"' in r.text
    for rel in data["releases"]:
        assert f'id="v{rel["version"]}"' in r.text
    assert re.findall(r"""(?:src|href)=["'](https?://[^"']+)""", r.text) == []


def test_the_changelog_page_lists_each_change_of_each_release_and_escapes_it():
    page = changelog_html("cmapi (t)", "1.1.0", {"releases": [
        {"version": "1.0.0", "previous": None, "changes": []},
        {"version": "1.1.0", "previous": "1.0.0", "changes": [
            {"level": 3, "operation": "GET", "path": "/api/v1/requests", "text": "removed the required property 'items' <b>"},
            {"level": 1, "operation": "POST", "path": "/api/v1/x", "text": "endpoint added"}]}]})
    assert 'id="v1.0.0"' in page and "The first released contract." in page
    assert '<span class="breaking">breaking</span> <code>GET /api/v1/requests</code>' in page
    assert "&lt;b&gt;" in page and "<b>" not in page
    assert "endpoint added" in page


# ---------------------------------------------------------------- #132 BUG-05: the ETag of the documents

def test_each_document_has_a_strong_etag_and_answers_304_to_the_same_one(world):
    client, *_ = world
    tags = {}
    for path in ("/openapi.json", "/openapi.yaml"):
        r = client.get(path)
        etag = r.headers.get("etag")
        assert r.status_code == 200 and etag and re.fullmatch(r'"[0-9a-f]{32}"', etag), f"{path}: {etag}"
        assert etag == '"' + hashlib.sha256(r.content).hexdigest()[:32] + '"', "the tag is not a hash of the bytes served"
        same = client.get(path, headers={"If-None-Match": etag})
        assert same.status_code == 304 and same.content == b"" and same.headers["etag"] == etag
        assert client.get(path, headers={"If-None-Match": f'"other", W/{etag}'}).status_code == 304
        assert client.get(path, headers={"If-None-Match": "*"}).status_code == 304
        assert client.get(path, headers={"If-None-Match": '"other"'}).status_code == 200
        tags[path] = etag
    assert tags["/openapi.json"] != tags["/openapi.yaml"]
    assert yaml.safe_load(client.get("/openapi.yaml").text) == client.get("/openapi.json").json()


# ---------------------------------------------------------------- #133 BUG-06: parameters

def test_each_parameter_in_the_spec_has_a_description_and_an_example(world):
    client, *_ = world
    spec = client.get("/openapi.json").json()
    bad = [f"{method} {path}: {p['in']} {p['name']}" for method, path, op in operations(spec) for p in op.get("parameters", [])
           if not p.get("description") or not (p.get("schema", {}).get("examples") or p.get("examples") or "example" in p)]
    assert bad == []


def test_a_parameter_without_a_description_or_an_example_stops_startup():
    def app_with(**query) -> FastAPI:
        r = DocumentedRouter("x", prefix="/api/v1", version="1", description="What the x plugin does.", group="Admin")

        @r.read("/x/{thing}", summary="Read x", permission=None, response_model=Health)
        def read(thing: str, limit: int = Query(default=5, **query)):
            """Reads it."""

        app = FastAPI()
        app.include_router(r)
        return app

    with pytest.raises(RuntimeError) as exc:
        check_documented(app_with(description="How many"))
    text = str(exc.value)
    assert "path parameter thing: no description" in text and "path parameter thing: no example" in text
    assert "query parameter limit: no example" in text and "query parameter limit: no description" not in text
    with pytest.raises(RuntimeError, match="query parameter limit: no description"):
        check_documented(app_with(examples=[5]))


# ---------------------------------------------------------------- #134 BUG-07: docs.public

def _config(test_config: Path, tmp_path: Path, docs: dict) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    for f in test_config.iterdir():
        (d / f.name).write_text(f.read_text())
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    inst["instance"]["docs"] = docs
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    return d


def test_docs_public_false_puts_the_five_paths_behind_a_token(bundles, test_config, tmp_path, fresh_db, keys, monkeypatch):
    with build_world(_config(test_config, tmp_path, {"public": False}), keys, monkeypatch) as (client, *_):
        token = {"Authorization": f"Bearer {keys.token('ada', roles=['cmapi-viewer'])}"}
        for path in DOCS_PATHS:
            r = client.get(path)
            assert r.status_code == 401 and r.headers.get("www-authenticate", "").startswith("Bearer"), f"{path}: {r.status_code}"
            assert r.json()["code"] == "unauthenticated"
            assert client.get(path, headers={"Authorization": "Bearer not-a-token"}).status_code == 401, path
            assert client.get(path, headers=token).status_code == 200, path
        assert client.get("/api/v1/version").status_code == 200       # the API's own public route stays public


def test_docs_are_public_by_default_and_when_public_is_true(bundles, test_config, tmp_path, fresh_db, keys, monkeypatch):
    with build_world(test_config, keys, monkeypatch) as (client, *_):
        assert [client.get(p).status_code for p in DOCS_PATHS] == [200] * 5
    with build_world(_config(test_config, tmp_path, {"public": True}), keys, monkeypatch) as (client, *_):
        assert [client.get(p).status_code for p in DOCS_PATHS] == [200] * 5


def test_docs_enabled_false_serves_none_of_them(bundles, test_config, tmp_path, fresh_db, keys, monkeypatch):
    with build_world(_config(test_config, tmp_path, {"enabled": False}), keys, monkeypatch) as (client, *_):
        assert [client.get(p).status_code for p in DOCS_PATHS] == [404] * 5
        assert client.get("/api/v1/version").status_code == 200


# ---------------------------------------------------------------- #131 BUG-04: the committed contract is the served one

def test_the_committed_contract_is_the_document_this_code_serves(world):
    """cmapi/contract/openapi.json is what the CI job `api-contract` compares with the base branch, so it must be current.
    To write it again after a change to the API: CMAPI_WRITE_CONTRACT=1 with this test."""
    client, *_ = world
    served = json.dumps(client.get("/openapi.json").json(), indent=2, sort_keys=True) + "\n"
    if os.environ.get("CMAPI_WRITE_CONTRACT") == "1":
        CONTRACT.write_text(served)
    assert CONTRACT.exists(), "cmapi/contract/openapi.json is missing: run this test with CMAPI_WRITE_CONTRACT=1"
    assert CONTRACT.read_text() == served, "the API changed: run this test with CMAPI_WRITE_CONTRACT=1 and commit the file"
