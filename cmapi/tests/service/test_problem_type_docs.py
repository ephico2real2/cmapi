"""#182 (BUG-49): the `type` of a problem resolves to the documentation of that problem type.

RFC 9457, section 3.1.1: the type URI is "the problem type's primary identifier". Section 4: it "SHOULD resolve to HTML
[HTML5] documentation that explains how to resolve the problem". The base is instance.yaml `problems.typeBase`. Each instance
serves /problems/<code>, so the type resolves when the base is on a host that points at an instance.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

from cmapi.core.docs import PROBLEMS
from cmapi.core.errors import BASE, Problem, type_base
from cmapi.core.problem_docs import ACTIONS
from conftest import build_world

OWN = "http://testserver/problems/"       # the address of the instance under test: starlette's TestClient


def _config(test_config: Path, tmp_path: Path, instance: dict) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    for f in test_config.iterdir():
        (d / f.name).write_text(f.read_text())
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    inst["instance"].update(instance)
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    return d


def test_the_type_of_a_real_problem_resolves_on_the_instance_that_gave_it(test_config, tmp_path, fresh_db, keys, monkeypatch):
    with build_world(_config(test_config, tmp_path, {"problems": {"typeBase": OWN}}), keys, monkeypatch) as (client, *_):
        token = {"Authorization": f"Bearer {keys.token('ada', roles=['cmapi-viewer'])}"}
        problems = [client.get("/api/v1/requests"),                                             # 401, with no token
                    client.get("/api/v1/requests/req-00000000-0000", headers=token),            # 404
                    client.get("/api/v1/requests", params={"limit": "x"}, headers=token)]       # 422, FastAPI's own refusal
        assert [r.status_code for r in problems] == [401, 404, 422]
        for r in problems:
            body = r.json()
            assert r.headers["content-type"] == "application/problem+json"
            assert body["type"] == OWN + body["code"]
            page = client.get(urlsplit(body["type"]).path)          # no token: the page is public
            assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
            assert f'<h1 id="code">{body["code"]}</h1>' in page.text
            assert f'<td id="status">{body["status"]}</td>' in page.text
            assert f'<code id="type">{html.escape(body["type"])}</code>' in page.text
            assert f'<td id="title">{html.escape(body["title"])}</td>' in page.text


def test_each_problem_type_has_a_page_that_says_what_to_do(world):
    client, *_ = world
    assert set(ACTIONS) == set(PROBLEMS), "each code of the registry has one action, and no action is for an unknown code"
    index = client.get("/problems")
    assert index.status_code == 200
    assert sorted(re.findall(r'href="/problems/([a-z0-9-]+)"', index.text)) == sorted(PROBLEMS)
    for code, (status, example) in PROBLEMS.items():
        page = client.get(f"/problems/{code}")
        assert page.status_code == 200, code
        assert f'<td id="status">{status}</td>' in page.text and html.escape(example) in page.text, code
        action = re.search(r'<td id="action">(.*?)</td>', page.text, re.S)[1]
        assert len(re.sub(r"<[^>]+>", "", action)) > 20, f"{code}: no action"
        assert Problem(status, code, example).body()["type"] in html.unescape(page.text), code


def test_an_unknown_code_is_a_404_problem_and_nothing_of_the_path_is_in_a_page(world):
    client, *_ = world
    r = client.get("/problems/<script>alert(1)</script>")
    assert r.status_code == 404
    r = client.get("/problems/no-such-type")
    assert r.status_code == 404 and r.headers["content-type"] == "application/problem+json"
    assert r.json()["code"] == "object-not-found" and "no-such-type" not in r.text


def test_the_default_base_does_not_change(world):
    """The type is the identifier that a client compares, so the default stays what it was before the setting."""
    client, *_ = world
    assert client.get("/api/v1/requests").json()["type"] == "https://cmapi.ephico2real.com/problems/unauthenticated"
    assert BASE == "https://cmapi.ephico2real.com/problems/"


def test_the_contract_of_an_instance_shows_its_own_base(test_config, tmp_path, fresh_db, keys, monkeypatch):
    with build_world(_config(test_config, tmp_path, {"problems": {"typeBase": OWN}}), keys, monkeypatch) as (client, *_):
        text = client.get("/openapi.json").text
        assert BASE not in text and text.count(OWN) > 100


def test_the_pages_are_public_when_the_api_documentation_is_not(test_config, tmp_path, fresh_db, keys, monkeypatch):
    """A caller with no token gets `unauthenticated`, and that type must resolve for the same caller."""
    for docs in ({"public": False}, {"enabled": False}):
        cfg = tmp_path / str(sorted(docs)[0])
        cfg.mkdir()
        with build_world(_config(test_config, cfg, {"docs": docs}), keys, monkeypatch) as (client, *_):
            assert client.get("/problems/unauthenticated").status_code == 200, docs
            assert client.get("/problems").status_code == 200, docs


@pytest.mark.parametrize("value, want", [
    (None, BASE),
    ("https://errors.example.org/cmapi/problems", "https://errors.example.org/cmapi/problems/"),
    ("https://errors.example.org/cmapi/problems/", "https://errors.example.org/cmapi/problems/"),
])
def test_type_base_reads_the_setting(value, want):
    assert type_base({"problems": {"typeBase": value}} if value else {}) == want


@pytest.mark.parametrize("value", ["/problems/", "problems", "tag:example.org,2026:problems/", "https://x.example/p/?a=1",
                                   "https://x.example/p/#f", "https:///p/", 7])
def test_type_base_refuses_a_value_that_is_not_an_absolute_http_uri(value):
    with pytest.raises(ValueError, match="problems.typeBase"):
        type_base({"problems": {"typeBase": value}})
