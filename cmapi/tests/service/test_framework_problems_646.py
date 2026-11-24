"""#646: an HTTPException that FastAPI or Starlette raises is an RFC 9457 problem of the registry (main.py, framework_refusal).

FastAPI 0.115.6 answers a body that it cannot read with HTTPException(400, "There was an error parsing the body")
(fastapi/routing.py:283-287), before any dependency, so without a token too. StaticFiles answers a file that the process
cannot stat with HTTPException(401) (starlette/staticfiles.py:117-119). FastAPI's default handler sent both as
{"detail": ...} in application/json. RFC 9457 (https://www.rfc-editor.org/rfc/rfc9457.txt, read 2026-11-24), section 3.1.2:
"Generators MUST use the same status code in the actual HTTP response".
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from starlette.exceptions import HTTPException

from cmapi.core.docs import PROBLEMS
from conftest import build_world
from test_api_docs import bundles  # noqa: F401  (the fixture: Swagger UI's and ReDoc's files, so /static is mounted)
from test_flow import OLA, auth

WRITE = "/api/v1/clusters/CRC/namespaces"
JSON = {"Content-Type": "application/json"}


def _problem(r, status: int, code: str) -> dict:
    where = (r.status_code, r.headers.get("content-type"), r.text[:300])
    assert r.status_code == status and r.headers["content-type"] == "application/problem+json", where
    body = r.json()
    assert (body["status"], body["code"]) == (status, code) and PROBLEMS[code][0] == status, where
    assert body["type"].endswith(f"/problems/{code}") and body["title"] and body["detail"], where
    return body


def _events(text: str, event: str) -> list[dict]:
    return [line for line in (json.loads(s) for s in text.splitlines() if s.startswith("{")) if line.get("event") == event]


@pytest.mark.parametrize("body", [b"\xff", b'{"name": "caf\xe9"}', b"[" * 100_000],
                         ids=["not-utf-8", "latin-1", "nested-too-deep"])
def test_a_body_that_cannot_be_read_is_validation_failed(world, body):
    """RFC 8259, section 8.1: "JSON text exchanged between systems that are not part of a closed ecosystem MUST be encoded
    using UTF-8". A body that is not UTF-8, or deeper than the decoder goes, is not JSON that cmapi reads: the same
    validation-failed and json_invalid as a body that JSON cannot parse, with or without a token."""
    client, *_, keys = world
    for headers in ({**JSON}, {**JSON, **auth(keys, "ola", **OLA)}):
        problem = _problem(client.post(WRITE, content=body, headers=headers), 422, "validation-failed")
        assert problem["errors"] == [{"field": "body", "message": "the body cannot be read as JSON", "code": "json_invalid"}]
        assert problem["detail"] == "The request is not valid: body: the body cannot be read as JSON"


def test_a_body_that_json_cannot_parse_has_the_same_code(world):
    """The answer that cmapi already gave a body JSON cannot parse (#164): the one a body that cannot be read now matches."""
    client, *_ = world
    problem = _problem(client.post(WRITE, content=b"{", headers=JSON), 422, "validation-failed")
    assert [(e["field"].split(".")[0], e["code"]) for e in problem["errors"]] == [("body", "json_invalid")]


def test_a_static_file_the_process_cannot_read_is_internal_error(bundles, test_config, fresh_db, keys, monkeypatch, capfd):  # noqa: F811
    """StaticFiles' 401 for a PermissionError is no refusal of the caller: RFC 9110, section 15.5.2, a 401 "MUST send a
    WWW-Authenticate header field ... containing at least one challenge applicable to the target resource", and no
    credential opens a file that the image's permissions close. It is internal-error, and the log line names the cause."""
    locked = Path(bundles) / "swagger-ui" / "locked"
    locked.mkdir()
    (locked / "x.js").write_text("/* x */")
    locked.chmod(0)
    try:
        try:
            os.stat(locked / "x.js")
        except PermissionError:
            pass
        else:
            pytest.skip("the premise does not hold: this user stats a file in a directory of mode 000 (root?)")
        with build_world(test_config, keys, monkeypatch) as (client, *_):
            capfd.readouterr()
            for method in ("GET", "HEAD"):
                r = client.request(method, "/static/swagger/locked/x.js")
                assert (r.status_code, r.headers["content-type"]) == (500, "application/problem+json"), r.text
                assert "www-authenticate" not in r.headers
            assert _problem(client.get("/static/swagger/locked/x.js"), 500, "internal-error")["detail"] == PROBLEMS["internal-error"][1]
            logged = _events(capfd.readouterr().out, "framework_refusal")
            assert [(e["status"], e["method"], e["level"]) for e in logged] == [(401, "GET", "error"), (401, "HEAD", "error"),
                                                                                 (401, "GET", "error")], logged
    finally:
        locked.chmod(0o755)


def test_another_framework_status_is_internal_error_and_below_400_is_unchanged(world, capfd):
    """No other site of FastAPI or Starlette that cmapi reaches raises another status. One that appears (a new version, a
    security class with auto_error) is the service's fault: internal-error and a log line, never FastAPI's {"detail"}.
    An HTTPException below 400 is not a refusal and keeps FastAPI's answer."""
    client, *_ = world

    def raises(status: int):
        def endpoint():
            raise HTTPException(status_code=status)
        return endpoint

    client.app.add_api_route("/test-646/403", raises(403))
    client.app.add_api_route("/test-646/304", raises(304))
    capfd.readouterr()
    _problem(client.get("/test-646/403"), 500, "internal-error")
    assert [(e["status"], e["route"]) for e in _events(capfd.readouterr().out, "framework_refusal")] == [(403, "/test-646/403")]
    unchanged = client.get("/test-646/304")
    assert (unchanged.status_code, unchanged.content) == (304, b"")


def test_cmapi_raises_no_http_exception():
    """The premise of framework_refusal: an HTTPException comes from FastAPI or Starlette only, because cmapi refuses with a
    Problem. So a 400 is a body that could not be read, and another status is not a refusal that cmapi chose."""
    src = Path(__file__).resolve().parents[2] / "src" / "cmapi"
    raising = {f.name for f in src.rglob("*.py") if re.search(r"\braise\s+(?:\w+\.)*HTTPException\(", f.read_text())}
    assert raising == set(), raising
