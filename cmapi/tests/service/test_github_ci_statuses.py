"""#279: the config repository's CI outcome read from commit statuses (instance.yaml git.ciSource statuses).

A fine-grained personal access token cannot call the Checks API (GitHub, "Managing your personal access tokens", the
limitations of fine-grained tokens). On CRC every read of the PR head's check suites answered 403 "Resource not accessible by
personal access token", and the request failed. With ciSource statuses the workflow posts ci/kubeconform and ci/kyverno as
commit statuses with its own GITHUB_TOKEN, and pr_status reads the list of the head's statuses, which names each creator. The
bot's token holds Commit statuses read and write, so a ci/* status counts only when Actions (github-actions[bot]) posted it.
The provider tests run on a MockTransport shaped by GitHub's REST docs; the job tests run the real adapter over the fake host."""
from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
import yaml

from cmapi.core.config import ConfigError, load_instance
from cmapi.core.git import make_provider
from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.github import GitHubProvider
from cmapi.jobs.pr_checks import CONTEXT_CMAPI, CONTEXT_KUBECONFORM, CONTEXT_KYVERNO
from test_flow import NS, OLA, auth
from test_github_check_runs import API, PR, SHA, GitHubOverFake, paged, poll, pr_checks_job, provider
from test_review_d_delivery import run_until, status

ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN = {"message": "Resource not accessible by personal access token",
             "documentation_url": "https://docs.github.com/rest/checks/suites#list-check-suites-for-a-git-reference"}
# The workflow token's login, spelled out so that this file also runs against an adapter without the mode.
CI_STATUS_CREATOR = "github-actions[bot]"
BOT = "ephico2real2"          # the login behind cmapi's own token on CRC: it may post statuses too


def status_of(context, state="success", creator=CI_STATUS_CREATOR):
    return {"context": context, "state": state, "creator": {"login": creator, "type": "Bot" if creator.endswith("[bot]") else "User"}}


def on_statuses_list(items, seen=None):
    """GitHub's list of a commit's statuses: a bare JSON array, newest first, paginated."""
    def handle(request):
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if path == "/repos/o/r/pulls/7":
            return httpx.Response(200, json={"state": "open", "merged": False, "head": {"sha": SHA, "ref": PR.branch}})
        if path == f"/repos/o/r/commits/{SHA}/statuses":
            per_page, page = int(request.url.params.get("per_page", 30)), int(request.url.params.get("page", 1))
            chunk = items[(page - 1) * per_page:page * per_page]
            headers = {"Link": f'<{API}{path}?per_page={per_page}&page={page + 1}>; rel="next"'} if page * per_page < len(items) else {}
            return httpx.Response(200, json=chunk, headers=headers)
        if "check-suites" in path or "check-runs" in path:
            return httpx.Response(403, json=FORBIDDEN)
        if path == f"/repos/o/r/commits/{SHA}/status":
            raise AssertionError("statuses mode reads the list, not the combined status: it names no creator")
        return httpx.Response(404, json={"message": f"not routed: {path}"})
    git = GitHubProvider(API, "o/r", "token", ci_source="statuses")
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(handle))
    return git


def read(items, seen=None):
    return dict(on_statuses_list(items, seen).pr_status(PR).checks)


# ------------------------------------------------------------------ the 403 path, as measured on CRC
def test_with_checks_a_token_that_cannot_call_the_checks_api_fails_the_read():
    """Today's mode, kept for a GitHub App or a classic token: the 403 on the check suites is an error, never 'no checks'."""
    def handle(request):
        path = request.url.path
        if path == "/repos/o/r/pulls/7":
            return httpx.Response(200, json={"state": "open", "merged": False, "head": {"sha": SHA, "ref": PR.branch}})
        if path == f"/repos/o/r/commits/{SHA}/status":
            return paged(request, "statuses", [])
        return httpx.Response(403, json=FORBIDDEN)       # check-suites, as GitHub answered on CRC
    git = GitHubProvider(API, "o/r", "token")
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(handle))
    with pytest.raises(GitUnavailable, match="check-suites.*403.*Resource not accessible by personal access token"):
        git.pr_status(PR)


def test_with_statuses_the_checks_api_is_never_called_and_green_actions_read_as_green():
    seen = []
    got = read([status_of(CONTEXT_KYVERNO), status_of(CONTEXT_KUBECONFORM), status_of(CONTEXT_CMAPI, creator=BOT)], seen)
    assert got == {CONTEXT_KYVERNO: "success", CONTEXT_KUBECONFORM: "success", CONTEXT_CMAPI: "success"}
    assert not [r for r in seen if "check-" in r.url.path], [r.url.path for r in seen]


# ------------------------------------------------------------------ the creator pin
@pytest.mark.parametrize("creator", [BOT, "someone-with-write", "github-actions", "dependabot[bot]"])
def test_a_ci_status_another_creator_posted_does_not_count(creator):
    """cmapi's own token may post statuses: a ci/* success from it, or from anyone but Actions, must not pass the PR."""
    assert read([status_of(CONTEXT_KUBECONFORM, creator=creator), status_of(CONTEXT_KYVERNO, creator=creator)]) == {}


def test_a_forged_success_newer_than_an_actions_failure_does_not_hide_it():
    assert read([status_of(CONTEXT_KYVERNO, "success", creator=BOT), status_of(CONTEXT_KYVERNO, "failure")]) == {
        CONTEXT_KYVERNO: "failure"}


def test_a_status_with_no_creator_does_not_count():
    assert read([{"context": CONTEXT_KYVERNO, "state": "success", "creator": None}]) == {}


def test_cmapis_own_context_is_read_whoever_posted_it():
    assert read([status_of(CONTEXT_CMAPI, "failure", creator=BOT)]) == {CONTEXT_CMAPI: "failure"}


# ------------------------------------------------------------------ the latest status of a context decides
def test_the_latest_actions_status_of_a_context_wins():
    """The list is newest first: a re-run's success replaces the failure before it, as GitHub's combined status does."""
    assert read([status_of(CONTEXT_KYVERNO, "success"), status_of(CONTEXT_KYVERNO, "failure")]) == {CONTEXT_KYVERNO: "success"}
    assert read([status_of(CONTEXT_KYVERNO, "failure"), status_of(CONTEXT_KYVERNO, "success")]) == {CONTEXT_KYVERNO: "failure"}


@pytest.mark.parametrize("state,expected", [("success", "success"), ("pending", "pending"), ("failure", "failure"),
                                            ("error", "failure"), ("a-state-github-adds-later", "failure")])
def test_each_state_reads_as_before(state, expected):
    assert read([status_of(CONTEXT_KUBECONFORM, state)]) == {CONTEXT_KUBECONFORM: expected}


def test_a_failure_on_a_later_page_counts():
    items = [status_of(f"ci/other-{i}") for i in range(150)] + [status_of(CONTEXT_KYVERNO, "failure")]
    assert read(items)[CONTEXT_KYVERNO] == "failure"


def test_a_refused_read_of_the_statuses_raises():
    git = GitHubProvider(API, "o/r", "token", ci_source="statuses")
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"state": "open", "merged": False, "head": {"sha": SHA, "ref": PR.branch}})
        if r.url.path.endswith("/pulls/7") else httpx.Response(403, json={"message": "Resource not accessible by personal access token"})))
    with pytest.raises(GitUnavailable, match="403"):
        git.pr_status(PR)


# ------------------------------------------------------------------ the switch
def test_the_creator_the_adapter_pins_is_the_workflow_tokens():
    from cmapi.core.ports import CI_STATUS_CREATOR as pinned
    assert pinned == CI_STATUS_CREATOR


def test_the_mode_is_checked_where_it_is_built():
    with pytest.raises(ValueError, match="ciSource"):
        GitHubProvider(API, "o/r", "token", ci_source="status")
    assert make_provider("github", API, "o/r", "t", ci_source="statuses").ci_source == "statuses"
    assert make_provider("github", API, "o/r", "t").ci_source == "checks"
    with pytest.raises(ValueError, match="ciSource"):
        make_provider("gitea", API, "o/r", "t", ci_source="statuses")


def crc_config(tmp_path, **git):
    data = next(yaml.safe_load_all((ROOT / "deploy/manifests/environments/crc/20-config.yaml").read_text()))["data"]
    for name, text in data.items():
        (tmp_path / name).write_text(text)
    if git:
        inst = yaml.safe_load(data["instance.yaml"])
        inst["instance"]["git"].update(git)
        (tmp_path / "instance.yaml").write_text(yaml.safe_dump(inst))
    return tmp_path


def test_crc_reads_ci_from_statuses(tmp_path):
    """CRC's bot token is a fine-grained personal access token, which cannot call the Checks API."""
    cfg = load_instance(crc_config(tmp_path), tmp_path / "metadata-keys.yaml")
    assert cfg.raw_instance["instance"]["git"]["ciSource"] == "statuses"


def test_an_unknown_ci_source_stops_the_configuration(tmp_path):
    d = crc_config(tmp_path, ciSource="combined")
    with pytest.raises(ConfigError, match="git.ciSource must be one of"):
        load_instance(d, d / "metadata-keys.yaml")


def test_the_context_builds_the_adapter_with_the_instances_mode():
    src = (ROOT / "cmapi/src/cmapi/core/context.py").read_text()
    assert re.search(r'ci_source=inst\["git"\]\.get\("ciSource", "checks"\)', src)


# ------------------------------------------------------------------ the job, both modes, on the real adapter over the fake host
class StatusesOverFake(GitHubOverFake):
    """GitHub with the workflow posting ci/* as statuses: the list endpoint names each creator, the Checks API answers 403 to this
    token, and branch protection is absent (#227), so a merge is not refused here: cmapi's own check is what must hold."""

    def __init__(self, fake):
        super().__init__(fake)
        self.listed: list[dict] = []          # newest first

    def post(self, context, state="success", creator=CI_STATUS_CREATOR):
        self.listed.insert(0, status_of(context, state, creator))

    def __call__(self, request):
        path = request.url.path[len(self.repo):]
        if re.fullmatch(r"/commits/\w+/statuses", path):
            sha = path.split("/")[2]
            own = [status_of(c, s, BOT) for c, s in self.fake.statuses.get(sha, {}).items() if c == CONTEXT_CMAPI]
            items = own + self.listed
            per_page, page = int(request.url.params.get("per_page", 30)), int(request.url.params.get("page", 1))
            return httpx.Response(200, json=items[(page - 1) * per_page:page * per_page])
        if "check-suites" in path or "check-runs" in path:
            return httpx.Response(403, json=FORBIDDEN)
        m = re.fullmatch(r"/pulls/(\d+)/merge", path)
        if m:
            for c in (CONTEXT_KUBECONFORM, CONTEXT_KYVERNO):
                self.report(c)                # so the parent's merge rule, written for check runs, holds
        return super().__call__(request)


@pytest.fixture
def statuses_github(world):
    client, ctx, fake, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "pr_checks") == "pr_checks"
    host = StatusesOverFake(fake)
    git = GitHubProvider(API, fake.repository, "token", ci_source="statuses")
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(host))
    ctx.git = git
    return client, ctx, fake, host, keys, rid


def test_statuses_from_actions_merge_and_the_worker_posts_only_the_cmapi_check(statuses_github):
    client, ctx, fake, host, keys, rid = statuses_github
    host.post(CONTEXT_KUBECONFORM)
    host.post(CONTEXT_KYVERNO)
    poll(ctx)
    assert status(client, keys, rid)["status"] == "merged"
    assert host.posted == [CONTEXT_CMAPI]


def test_forged_ci_statuses_leave_the_request_waiting_and_nothing_merges(statuses_github):
    client, ctx, fake, host, keys, rid = statuses_github
    host.post(CONTEXT_KUBECONFORM, creator=BOT)
    host.post(CONTEXT_KYVERNO, creator=BOT)
    poll(ctx)
    assert status(client, keys, rid)["status"] == "pr_open"
    pending, attempts, last_error = pr_checks_job(ctx)
    assert pending and attempts == 0 and "waiting for ci/kubeconform, ci/kyverno" in last_error
    assert host.posted == [], "nothing is posted while CI has not reported"


def test_an_actions_failure_fails_the_request(statuses_github):
    client, ctx, fake, host, keys, rid = statuses_github
    host.post(CONTEXT_KUBECONFORM)
    host.post(CONTEXT_KYVERNO, "failure")
    poll(ctx)
    assert status(client, keys, rid)["status"] == "failed"
