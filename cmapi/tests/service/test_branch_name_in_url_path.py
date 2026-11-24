"""A branch name, a revision or a file path is data in a URL path (#638). Git accepts "#" and "%" in a branch name
(git check-ref-format --branch 'release#2'), and RFC 3986, section 3.3: "The path is terminated by the first question mark
("?") or number sign ("#") character"; section 2.4: a data "%" "must be percent-encoded as "%25"". Unquoted, the branch
release#2 read the head of release, and rel%41 the head of relA (measured on Gitea 1.25.5, the review record of #639).

Each test asserts request.url.raw_path, the bytes httpx puts on the request line, not the decoded request.url.path: "rel%"
and "rel%25" decode to the same path, and "team/main" and "team%2Fmain" too.

The slash differs by route. GitHub: "any slashes in the parameter value must be replaced with %2F" (REST troubleshooting).
Gitea 1.25.5 routes /branches/*, /compare/* and /contents/* with a wildcard, so a "/" stays a "/", and /branch_protections/{name}
with one segment, so a "/" there is %2F (routers/api/v1/api.go)."""
from __future__ import annotations

from typing import Callable

import httpx
import pytest

from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.settings import settings
from cmapi.tools import git_bootstrap

API = "https://host.test"
ROOT = b"/repos/o/r/"
SHA = "a" * 40


@pytest.fixture
def host(monkeypatch):
    """Every httpx.Client made during the test answers from `reply`; `seen` holds (method, raw path and query) of each request."""
    seen: list[tuple[str, bytes]] = []
    state: dict[str, Callable[[httpx.Request], tuple[int, object]]] = {
        "reply": lambda req: (200, {"commit": {"sha": SHA, "id": SHA}, "commits": [], "sha": SHA})}
    real = httpx.Client

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.raw_path))
        status, body = state["reply"](req)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(httpx, "Client", lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handle)}))
    return seen, state


@pytest.mark.parametrize("provider", [GitHubProvider, GiteaProvider])
@pytest.mark.parametrize(("name", "tail"), [
    ("main", b"main"),                      # an ordinary name: the same bytes as before #638
    ("release#2", b"release%232"),
    ("release?2", b"release%3F2"),
    ("rel%41", b"rel%2541"),
    ("rel%", b"rel%25"),
    ("team/main", None),                    # by route: below
])
def test_a_branch_name_stays_one_name_in_the_path(host, provider, name, tail):
    seen, _ = host
    if tail is None:
        tail = b"team%2Fmain" if provider is GitHubProvider else b"team/main"
    assert provider(API, "o/r", "").branch_head(name) == SHA
    assert seen == [("GET", ROOT + b"branches/" + tail)]


def test_gitea_delete_and_compare_keep_the_name_whole(host):
    seen, state = host
    replies = iter([(200, {"commit": {"id": SHA}}), (204, None), (200, {"commits": []})])
    state["reply"] = lambda req: next(replies)
    git = GiteaProvider(API, "o/r", "", default_branch="team/main#2")
    assert git.delete_branch(git.default_branch, SHA)
    assert git.changed_paths(SHA) == set()
    branch = ROOT + b"branches/team/main%232"
    assert seen == [("GET", branch), ("DELETE", branch), ("GET", ROOT + b"compare/team/main%232..." + SHA.encode())]


def test_gitea_compare_escapes_an_observed_revision(host):
    """contains takes the revision Argo CD reports (core/sync.py), not a name cmapi made."""
    seen, state = host
    state["reply"] = lambda req: (404, {})
    assert GiteaProvider(API, "o/r", "").contains("v1+build%41", SHA) is False
    assert seen == [("GET", ROOT + b"compare/v1%2Bbuild%2541..." + SHA.encode())]


def test_gitea_blob_read_escapes_the_file_name_and_the_ref(host):
    seen, _ = host
    assert GiteaProvider(API, "o/r", "")._blob_sha("dir/a#b?c%41.yaml", "team/r#1") == SHA
    assert seen == [("GET", ROOT + b"contents/dir/a%23b%3Fc%2541.yaml?ref=team%2Fr%231")]


@pytest.mark.parametrize("exists", [False, True], ids=["first-run", "re-run"])
def test_git_bootstrap_names_the_default_branch_and_its_rule_whole(host, monkeypatch, tmp_path, exists):
    """The chart runs git-bootstrap on every install and upgrade. Its re-run must find the rule it made: on Gitea 1.25.5 a
    second create answers 403 "Branch protection already exist", which failed the hook (measured, the review record of #639)."""
    seen, state = host

    def gitea(req: httpx.Request) -> tuple[int, object]:
        named = b"/branches/" in req.url.raw_path or b"/branch_protections/" in req.url.raw_path
        if req.method == "GET" and named and not exists:
            return 404, {}
        return (201 if req.method == "POST" else 200), {}

    state["reply"] = gitea
    for key, value in {"CMAPI_GIT_URL": API, "CMAPI_GIT_DEFAULT_BRANCH": "team/r#2", "CMAPI_GIT_REPOSITORY": "o/r",
                       "CMAPI_GIT_ADMIN_USER": "admin", "CMAPI_GIT_ADMIN_PASSWORD": "placeholder", "CMAPI_GIT_PASSWORD": "placeholder",
                       "CMAPI_POLICIES_DIR": str(tmp_path), "CMAPI_METADATA_KEYS": str(tmp_path / "none")}.items():
        monkeypatch.setenv(key, value)
    settings.cache_clear()
    try:
        git_bootstrap.main([])
    finally:
        settings.cache_clear()
    rule = ROOT + b"branch_protections/team%2Fr%232"
    then = ("PATCH", rule) if exists else ("POST", ROOT + b"branch_protections")
    assert [s for s in seen if b"/branch" in s[1]] == [("GET", ROOT + b"branches/team/r%232"), ("GET", rule), then]
