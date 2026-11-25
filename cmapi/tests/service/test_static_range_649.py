"""Each file under /static is sent whole, with 200, whatever the Range header says (#649; main.py, ConditionalStaticFiles).

RFC 9110 (https://www.rfc-editor.org/rfc/rfc9110.txt, read 2026-11-25), section 14.2: "A server MAY ignore the Range header
field", and "An origin server MUST ignore a Range header field that contains a range unit it does not understand". Starlette
1.10.0 answers such a unit with a plain-text 400 "Only support bytes range" (responses.py, FileResponse._parse_range_header),
a malformed Range with a plain-text 400 and an unsatisfiable one with an empty 416, none of them an RFC 9457 problem. The
browser fetches the Swagger UI and ReDoc bundles whole, so /static supports no range: ConditionalStaticFiles drops Range
before Starlette reads it, and says so with `Accept-Ranges: none` (section 14.3: a server "that does not support any kind of
range request for the target resource MAY send Accept-Ranges: none to advise the client not to attempt a range request").
"""
from __future__ import annotations

import pytest
from starlette.responses import FileResponse
from starlette.testclient import TestClient

from cmapi.main import ConditionalStaticFiles
from test_api_docs import bundles  # noqa: F401  (the fixture: the files the image holds)
from test_framework_upgrade_651 import CVE_RANGE

PATHS = ["/static/swagger/swagger-ui-bundle.js", "/static/redoc/redoc.standalone.js"]
# The bundles of the fixture hold "/* test bundle */", 17 bytes, so "bytes=99-" starts past the end.
RANGES = {
    "one-range": "bytes=1-2",
    "suffix-range": "bytes=-5",
    "unsatisfiable": "bytes=99-",
    "malformed": "oops",
    "reversed": "bytes=5-1",
    "other-unit": "widgets=1-2",
    "two-ranges": "bytes=0-0,5-6",
    "long-header": CVE_RANGE,   # the CVE-2025-62727 payload at the 16 kB that the front door accepts
}


@pytest.fixture
def no_range_parse(monkeypatch):
    """Starlette's range code is never reached from /static: the parse of CVE-2025-62727 included."""
    def never(*args, **kwargs):
        raise AssertionError("the Range header reached FileResponse._parse_range_header")

    monkeypatch.setattr(FileResponse, "_parse_range_header", staticmethod(never))


def _is_whole(r, whole, method: str) -> None:
    assert (r.status_code, r.headers.get("content-range")) == (200, None), (method, r.status_code, r.text[:300])
    assert r.headers["accept-ranges"] == "none", r.headers
    for field in ("content-length", "content-type", "etag", "last-modified"):
        assert r.headers[field] == whole.headers[field], (method, field)
    assert r.content == (whole.content if method == "GET" else b"")


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("value", RANGES.values(), ids=RANGES.keys())
def test_a_static_file_is_sent_whole_whatever_its_range(bundles, world, no_range_parse, path, value):
    client, *_ = world
    whole = client.get(path)
    assert whole.status_code == 200 and whole.content == b"/* test bundle */"
    assert whole.headers["accept-ranges"] == "none", "a file that is always sent whole must not advertise byte ranges"
    for method in ("GET", "HEAD"):
        _is_whole(client.request(method, path, headers={"Range": value}), whole, method)
        # If-Range is a precondition of Range only (section 13.1.5), so it changes nothing either.
        _is_whole(client.request(method, path, headers={"Range": value, "If-Range": whole.headers["etag"]}), whole, method)


@pytest.mark.parametrize("path", PATHS)
def test_a_range_does_not_stop_a_revalidation(bundles, world, no_range_parse, path):
    """Section 14.2: "Range is ignored when a conditional GET would result in a 304 (Not Modified) response"."""
    client, *_ = world
    etag = client.get(path).headers["etag"]
    for method in ("GET", "HEAD"):
        for value in RANGES.values():
            r = client.request(method, path, headers={"Range": value, "If-None-Match": etag})
            assert (r.status_code, r.content) == (304, b""), (method, value[:40], r.status_code)
            assert r.headers["etag"] == etag and "content-range" not in r.headers


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
