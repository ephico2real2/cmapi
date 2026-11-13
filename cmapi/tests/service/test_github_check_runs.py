"""#87: on GitHub, ci/kubeconform and ci/kyverno are check runs from the config repository's Actions. pr_status reads them next
to the commit statuses, and pr_checks waits for them instead of posting them. The provider tests run on a MockTransport shaped by
GitHub's REST docs (2026-11); the job tests run the real adapter over the same fake host as the rest of this suite. No test here
reaches GitHub: "a PR whose ci/* come from Actions merges" is the Wave 3 proof on the real repository."""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import unquote

import httpx
import pytest
from sqlalchemy import text

from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.github import GitHubProvider
from cmapi.core.ports import PrRef
from cmapi.jobs.pr_checks import CONTEXT_CMAPI, CONTEXT_KUBECONFORM, CONTEXT_KYVERNO
from cmapi.worker import MAX_ATTEMPTS, Worker
from test_flow import NS, OLA, auth
from test_review_d_delivery import run_until, status
from test_review_e_recovery import lease_expired

SHA = "c" * 40
API = "https://github.test"
PR = PrRef(7, "https://github.test/o/r/pull/7", "cmapi/CRC/x/r1", SHA)


def run(name, *, status="completed", conclusion="success", id=1, app=15368, suite=100):
    return {"id": id, "name": name, "status": status, "conclusion": conclusion, "app": {"id": app} if app else None,
            "check_suite": {"id": suite}}


def st(context, state="success"):
    return {"context": context, "state": state}


def paged(request, key, items):
    """One page of a GitHub list, as the REST docs give it: per_page (default 30, max 100), page, and a Link header naming the next."""
    per_page, page = min(int(request.url.params.get("per_page", 30)), 100), int(request.url.params.get("page", 1))
    chunk = items[(page - 1) * per_page:page * per_page]
    headers = {}
    if page * per_page < len(items):
        headers["Link"] = f'<{API}{request.url.path}?per_page={per_page}&page={page + 1}>; rel="next"'
    return httpx.Response(200, json={"total_count": len(items), key: chunk}, headers=headers)


def provider(statuses=(), runs=(), *, seen=None, pr=None, on_runs=None, on_statuses=None):
    def handle(request):
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if path == "/repos/o/r/pulls/7":
            return httpx.Response(200, json=pr or {"state": "open", "merged": False, "head": {"sha": SHA, "ref": PR.branch}})
        if path == f"/repos/o/r/commits/{SHA}/status":
            return on_statuses(request) if on_statuses else paged(request, "statuses", list(statuses))
        if path == f"/repos/o/r/commits/{SHA}/check-suites":
            suites = sorted({r["check_suite"]["id"] for r in runs})
            return paged(request, "check_suites", [{"id": i} for i in suites])
        if path == f"/repos/o/r/commits/{SHA}/check-runs":
            return on_runs(request) if on_runs else paged(request, "check_runs", list(runs))
        return httpx.Response(404, json={"message": f"not routed: {path}"})
    git = GitHubProvider(API, "o/r", "token")
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(handle))
    return git


def checks(**kw):
    return dict(provider(**kw).pr_status(PR).checks)


# ------------------------------------------------------------------ the issue's test
def test_no_statuses_and_two_successful_check_runs_read_as_green():
    assert checks(runs=[run(CONTEXT_KUBECONFORM, id=1), run(CONTEXT_KYVERNO, id=2)]) == {
        CONTEXT_KUBECONFORM: "success", CONTEXT_KYVERNO: "success"}


# ------------------------------------------------------------------ every conclusion and status, decided
@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required", "stale", "startup_failure",
                                        "neutral", "skipped", None, "a-conclusion-github-adds-later"])
def test_a_completed_run_that_is_not_success_is_not_green(conclusion):
    """GitHub treats neutral and skipped as passing for a required check. cmapi does not: ci/* is the evidence that the validation
    ran and passed, and a run that was skipped validated nothing. A value GitHub adds later fails closed too."""
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}


@pytest.mark.parametrize("state", ["queued", "in_progress", "waiting", "requested", "pending", "a-status-github-adds-later"])
@pytest.mark.parametrize("conclusion", [None, "success", "failure"])
def test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says(state, conclusion):
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}


@pytest.mark.parametrize("state,expected", [("success", "success"), ("pending", "pending"), ("failure", "failure"), ("error", "failure")])
def test_commit_statuses_still_read_as_before(state, expected):
    assert checks(statuses=[st(CONTEXT_CMAPI, state)]) == {CONTEXT_CMAPI: expected}


# ------------------------------------------------------------------ merged by context name: the worst of what is reported
@pytest.mark.parametrize("from_status,from_run,expected", [
    ("success", dict(conclusion="success"), "success"),
    ("success", dict(conclusion="failure"), "failure"),
    ("failure", dict(conclusion="success"), "failure"),
    ("error", dict(conclusion="success"), "failure"),
    ("pending", dict(conclusion="success"), "pending"),
    ("success", dict(status="in_progress", conclusion=None), "pending"),
    ("failure", dict(status="in_progress", conclusion=None), "failure"),
    ("pending", dict(conclusion="failure"), "failure"),
])
def test_a_status_and_a_run_of_one_name_merge_to_the_worst(from_status, from_run, expected):
    assert checks(statuses=[st(CONTEXT_KYVERNO, from_status)], runs=[run(CONTEXT_KYVERNO, **from_run)]) == {CONTEXT_KYVERNO: expected}


def test_other_names_stay_apart_and_a_context_nobody_reported_is_not_invented():
    got = checks(statuses=[st(CONTEXT_CMAPI)], runs=[run(CONTEXT_KUBECONFORM)])
    assert got == {CONTEXT_CMAPI: "success", CONTEXT_KUBECONFORM: "success"}


# ------------------------------------------------------------------ re-runs
def test_it_asks_for_the_latest_runs_of_the_pr_head():
    seen: list[httpx.Request] = []
    provider(runs=[run(CONTEXT_KUBECONFORM)], seen=seen).pr_status(PR)
    asked = next(r for r in seen if r.url.path.endswith("/check-runs"))
    assert asked.url.params["filter"] == "latest"


@pytest.mark.parametrize("older,newer,expected", [
    (dict(id=1, conclusion="failure"), dict(id=2, conclusion="success"), "success"),
    (dict(id=2, conclusion="success"), dict(id=1, conclusion="failure"), "success"),
    (dict(id=1, conclusion="success"), dict(id=2, status="in_progress", conclusion=None), "pending"),
    (dict(id=1, conclusion="success"), dict(id=2, conclusion="failure"), "failure"),
])
def test_a_rerun_in_one_suite_replaces_the_attempt_before_it(older, newer, expected):
    """filter=latest is what asks for this; the id holds it if a page still carries both attempts."""
    assert checks(runs=[run(CONTEXT_KUBECONFORM, **older), run(CONTEXT_KUBECONFORM, **newer)]) == {CONTEXT_KUBECONFORM: expected}


@pytest.mark.parametrize("other", [dict(suite=200), dict(app=999), dict(app=None)])
def test_one_name_from_another_suite_or_app_does_not_hide_a_failure(other):
    """Two workflows, or another App, reporting one name are two checks, whichever came last."""
    runs = [run(CONTEXT_KUBECONFORM, id=1, conclusion="failure"), run(CONTEXT_KUBECONFORM, id=2, **other)]
    assert checks(runs=runs) == {CONTEXT_KUBECONFORM: "failure"}


# ------------------------------------------------------------------ pagination: an unread page must not read as green
def test_a_failure_on_a_later_page_of_check_runs_counts():
    runs = [run(f"other-{i}", id=i) for i in range(150)] + [run(CONTEXT_KYVERNO, id=999, conclusion="failure")]
    got = checks(runs=runs)
    assert len(got) == 151 and got[CONTEXT_KYVERNO] == "failure"


def test_a_failure_on_a_later_page_of_statuses_counts():
    statuses = [st(f"other-{i}") for i in range(150)] + [st(CONTEXT_KYVERNO, "failure")]
    got = checks(statuses=statuses)
    assert len(got) == 151 and got[CONTEXT_KYVERNO] == "failure"


def test_it_asks_for_full_pages_and_stops_when_the_link_header_has_no_next():
    seen: list[httpx.Request] = []
    provider(runs=[run(f"r{i}", id=i) for i in range(101)], seen=seen).pr_status(PR)
    asked = [r for r in seen if r.url.path.endswith("/check-runs")]
    assert [(r.url.params["per_page"], r.url.params["page"]) for r in asked] == [("100", "1"), ("100", "2")]


def test_the_next_link_is_a_signal_and_is_never_followed_to_another_host():
    """The Authorization header goes with every request on this client, so a URL from a response body or header is not called."""
    seen: list[httpx.Request] = []

    def evil(request):
        if request.url.params.get("page", "1") == "1":
            return httpx.Response(200, json={"check_runs": [run(CONTEXT_KUBECONFORM)]}, headers={"Link": '<https://evil.test/steal?page=2>; rel="next"'})
        return httpx.Response(200, json={"check_runs": []})
    provider(on_runs=evil, seen=seen).pr_status(PR)
    assert {r.url.host for r in seen} == {"github.test"}


def test_a_host_that_never_stops_paging_is_an_error_not_a_partial_read():
    calls = []

    def endless(request):
        calls.append(request)
        return httpx.Response(200, json={"check_runs": [run(CONTEXT_KUBECONFORM)]}, headers={"Link": f'<{API}/x?page=9>; rel="next"'})
    with pytest.raises(GitUnavailable, match="pages"):
        provider(on_runs=endless).pr_status(PR)
    assert len(calls) == GitHubProvider.MAX_PAGES


# ------------------------------------------------------------------ a refused read is not "no checks"
@pytest.mark.parametrize("code", [403, 404, 422, 429])
@pytest.mark.parametrize("which", ["on_runs", "on_statuses"])
def test_a_refused_read_raises_instead_of_reading_as_no_checks(code, which):
    """The App without Checks: read answers 403 here, and {} would read the same as a commit CI has not reached yet."""
    with pytest.raises(GitUnavailable, match=str(code)):
        provider(**{which: lambda r: httpx.Response(code, json={"message": "Resource not accessible by integration"})}).pr_status(PR)


def test_a_refused_later_page_raises_too():
    def second_page_refused(request):
        if request.url.params.get("page") == "1":
            return httpx.Response(200, json={"check_runs": [run(CONTEXT_KUBECONFORM)]}, headers={"Link": f'<{API}/x?page=2>; rel="next"'})
        return httpx.Response(403, json={"message": "rate limited"})
    with pytest.raises(GitUnavailable):
        provider(on_runs=second_page_refused).pr_status(PR)


def test_a_5xx_is_retryable():
    with pytest.raises(GitUnavailable):
        provider(on_runs=lambda r: httpx.Response(502, text="bad gateway")).pr_status(PR)


def test_a_refused_read_of_the_pr_itself_raises():
    git = GitHubProvider(API, "o/r", "token")
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(lambda r: httpx.Response(404, json={"message": "Not Found"})))
    with pytest.raises(GitUnavailable, match="404"):
        git.pr_status(PR)


@pytest.mark.parametrize("pr,state,merge_sha", [
    ({"state": "closed", "merged": True, "merge_commit_sha": "d" * 40, "head": {"sha": SHA}}, "merged", "d" * 40),
    ({"state": "closed", "merged": False, "merge_commit_sha": "e" * 40, "head": {"sha": SHA}}, "closed", None),
])
def test_a_finished_pr_needs_no_read_of_its_checks(pr, state, merge_sha):
    """Nothing reads them, and a refusal on the head of a finished PR must not hold the request back from recording the merge."""
    git = provider(pr=pr, on_runs=lambda r: httpx.Response(403, json={"message": "no"}), on_statuses=lambda r: httpx.Response(403, json={"message": "no"}))
    got = git.pr_status(PR)
    assert (got.state, got.merge_sha, dict(got.checks)) == (state, merge_sha, {})


# ------------------------------------------------------------------ the job, on the real adapter: what GitHub would see
class GitHubOverFake:
    """Serves FakeGit's state over the REST paths github.py calls, and keeps branch protection's rule: a merge needs ci/* as
    successful check runs and cmapi/check as a commit status. Records what was posted."""

    def __init__(self, fake):
        self.fake, self.runs, self.posted, self.merge_refused = fake, {}, [], 0
        self.repo = f"/repos/{fake.repository}"
        self.refuse_check_runs = None

    def report(self, context, **kw):
        kw.setdefault("id", len(self.runs) + 1)
        self.runs[context] = run(context, **kw)

    def __call__(self, request):
        path, fake = unquote(request.url.path), self.fake
        assert path.startswith(self.repo), path
        path = path[len(self.repo):]
        m = re.fullmatch(r"/pulls/(\d+)", path)
        if m and request.method == "GET":
            p = fake.prs[int(m[1])]
            return httpx.Response(200, json={"state": "closed" if p["state"] != "open" else "open", "merged": p["state"] == "merged",
                                             "merge_commit_sha": p["merge_sha"], "head": {"sha": fake.heads[p["branch"]], "ref": p["branch"]}})
        if m and request.method == "PATCH":
            fake.prs[int(m[1])]["state"] = "closed"
            return httpx.Response(200, json={})
        if re.fullmatch(r"/commits/\w+/status", path):
            sha = path.split("/")[2]
            return paged(request, "statuses", [st(c, s) for c, s in fake.statuses.get(sha, {}).items()])
        if re.fullmatch(r"/commits/\w+/check-suites", path):
            return paged(request, "check_suites", [{"id": i} for i in sorted({r["check_suite"]["id"] for r in self.runs.values()})])
        if re.fullmatch(r"/commits/\w+/check-runs", path):
            if self.refuse_check_runs:
                return httpx.Response(self.refuse_check_runs, json={"message": "Resource not accessible by integration"})
            return paged(request, "check_runs", list(self.runs.values()))
        if path.startswith("/branches/"):
            head = fake.branch_head(path[len("/branches/"):])
            return httpx.Response(200, json={"commit": {"sha": head}}) if head else httpx.Response(404, json={})
        if path.startswith("/contents/"):
            folder = path[len("/contents/"):]
            files, _ = fake.read_folder(folder, request.url.params["ref"])
            if folder in files:
                return httpx.Response(200, json={"content": base64.b64encode(files[folder].encode()).decode()})
            return httpx.Response(200, json=[{"type": "file", "name": f.rsplit("/", 1)[1], "path": f} for f in files])
        if path.startswith("/compare/"):
            return httpx.Response(200, json={"files": [{"filename": f} for f in fake.changed_paths(path.rsplit("...", 1)[1])]})
        if path.startswith("/statuses/") and request.method == "POST":
            body = json.loads(request.content)
            self.posted.append(body["context"])
            fake.set_check(path.split("/")[2], body["context"], body["state"], body["description"])
            return httpx.Response(201, json={})
        m = re.fullmatch(r"/pulls/(\d+)/merge", path)
        if m:
            number, head = int(m[1]), json.loads(request.content)["sha"]
            green = all(self.runs.get(c, {}).get("conclusion") == "success" for c in (CONTEXT_KUBECONFORM, CONTEXT_KYVERNO))
            if not green or fake.statuses.get(head, {}).get(CONTEXT_CMAPI) != "success":
                self.merge_refused += 1
                return httpx.Response(405, json={"message": "Required status check is expected"})
            fake.statuses[head].update({CONTEXT_KUBECONFORM: "success", CONTEXT_KYVERNO: "success"})
            branch = fake.prs[number]["branch"]
            return httpx.Response(200, json={"sha": fake.merge(PrRef(number, "", branch, head), head)})
        if path.startswith("/git/refs/heads/") and request.method == "DELETE":
            return httpx.Response(204)
        if path.startswith("/issues/"):
            return httpx.Response(201, json={})
        raise AssertionError(f"{request.method} {path} is not on the path pr_checks should take")


@pytest.fixture
def on_github(world):
    """A request with its PR open on the fake host, and ctx.git swapped for the real adapter over it."""
    client, ctx, fake, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "pr_checks") == "pr_checks"
    host = GitHubOverFake(fake)
    git = GitHubProvider(API, fake.repository, "token")
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(host))
    ctx.git = git
    return client, ctx, fake, host, validator, keys, rid


def poll(ctx, n=1):
    worker = Worker(ctx, "w")
    for _ in range(n):
        lease_expired(ctx)
        assert worker.run_one()


def pr_checks_job(ctx):
    with ctx.db.session() as s:
        return s.execute(text("select done_at is null, attempts, last_error from jobs where kind='pr_checks'")).one()


def test_green_from_actions_merges_and_the_worker_posts_only_the_cmapi_check(on_github):
    client, ctx, fake, host, validator, keys, rid = on_github
    host.report(CONTEXT_KUBECONFORM)
    host.report(CONTEXT_KYVERNO)
    poll(ctx)
    assert status(client, keys, rid)["status"] == "merged"
    assert host.posted == [CONTEXT_CMAPI], "the worker posted a context Actions owns"
    assert host.merge_refused == 0


@pytest.mark.parametrize("reported", [dict(), dict(kyverno=dict(status="in_progress", conclusion=None))], ids=["nothing yet", "one still running"])
def test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged(on_github, reported):
    client, ctx, fake, host, validator, keys, rid = on_github
    if reported:
        host.report(CONTEXT_KUBECONFORM)
        host.report(CONTEXT_KYVERNO, **reported["kyverno"])
    poll(ctx, 3)
    view = status(client, keys, rid)
    assert view["status"] == "pr_open"
    assert host.posted == [] and host.merge_refused == 0
    still, attempts, why = pr_checks_job(ctx)
    assert still and attempts == 0, "waiting must not spend the attempts a Git outage gets"
    assert CONTEXT_KYVERNO in why
    assert sum(e["event"] == "ci_wait" for e in view["events"]) == 1, "one event for one reason, not one per poll"
    # And then it finishes.
    host.report(CONTEXT_KUBECONFORM, id=11)
    host.report(CONTEXT_KYVERNO, id=12)
    poll(ctx)
    assert status(client, keys, rid)["status"] == "merged"
    assert host.posted == [CONTEXT_CMAPI]


@pytest.mark.parametrize("conclusion", ["failure", "timed_out", "cancelled", "skipped", "neutral"])
def test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr(on_github, conclusion):
    client, ctx, fake, host, validator, keys, rid = on_github
    host.report(CONTEXT_KUBECONFORM)
    host.report(CONTEXT_KYVERNO, conclusion=conclusion)
    poll(ctx)
    view = status(client, keys, rid)
    assert view["status"] == "failed"
    assert fake.prs[1]["state"] == "closed" and host.merge_refused == 0
    assert host.posted == [CONTEXT_CMAPI]
    assert any(CONTEXT_KYVERNO in (e["note"] or "") and "failure" in (e["note"] or "") for e in view["events"]), view["events"]


def test_a_failure_does_not_wait_for_the_other_check_to_finish(on_github):
    client, ctx, fake, host, validator, keys, rid = on_github
    host.report(CONTEXT_KUBECONFORM, conclusion="failure")
    poll(ctx)
    assert status(client, keys, rid)["status"] == "failed"


def test_ci_that_never_reports_fails_the_request_when_the_clock_runs_out(on_github):
    """Not "waits for ever": a config repository whose workflow never starts ends in failed, by the same bound as a sync."""
    client, ctx, fake, host, validator, keys, rid = on_github
    ctx.delivery = type(ctx.delivery)(mode=ctx.delivery.mode, poll_seconds=0, sync_timeout_seconds=0)
    poll(ctx)
    view = status(client, keys, rid)
    assert view["status"] == "failed" and fake.prs[1]["state"] == "closed"
    assert CONTEXT_KUBECONFORM in view["events"][-1]["note"], view["events"][-1]
    assert host.posted == [] and host.merge_refused == 0
    assert pr_checks_job(ctx)[0] is False


def test_green_ci_does_not_excuse_a_head_that_moved(on_github):
    """The cmapi check still decides: Actions passing on a pushed commit is not an approval of it."""
    client, ctx, fake, host, validator, keys, rid = on_github
    branch = fake.prs[1]["branch"]
    fake.tamper(branch, "clusters/CRC/namespaces/payments-dev/extra.yaml", "kind: ConfigMap\n")
    host.report(CONTEXT_KUBECONFORM)
    host.report(CONTEXT_KYVERNO)
    poll(ctx)
    assert status(client, keys, rid)["status"] == "failed" and host.merge_refused == 0
    assert host.posted == [CONTEXT_CMAPI]
    assert fake.statuses[fake.heads[branch]][CONTEXT_CMAPI] == "failure"


def test_the_workers_own_validator_can_still_stop_a_merge_when_ci_is_green(on_github):
    from cmapi.core.ports import Finding
    client, ctx, fake, host, validator, keys, rid = on_github
    validator.findings = [Finding(source="kyverno", rule="r", path="p", message="refused")]
    host.report(CONTEXT_KUBECONFORM)
    host.report(CONTEXT_KYVERNO)
    poll(ctx)
    assert status(client, keys, rid)["status"] == "failed" and host.posted == [CONTEXT_CMAPI]


def test_an_app_without_checks_read_is_a_visible_failure_not_a_silent_wait(on_github):
    """The 403 is retried as a Git failure, says what it is, and ends the request after the attempts; it never reads as pending."""
    client, ctx, fake, host, validator, keys, rid = on_github
    host.refuse_check_runs = 403
    poll(ctx)
    still, attempts, why = pr_checks_job(ctx)
    assert still and attempts == 1 and "403" in why and "check-runs" in why, why
    assert status(client, keys, rid)["status"] == "pr_open"
    poll(ctx, MAX_ATTEMPTS - 1)
    assert status(client, keys, rid)["status"] == "failed"
    assert host.posted == [] and host.merge_refused == 0


def test_the_stand_in_without_a_ci_runner_still_posts_all_three(world):
    """Until Wave 3 removes it: a Gitea stand-in has no Actions, so nobody else would post ci/* and every request would time out."""
    client, ctx, fake, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "pr_checks") == "pr_checks"
    assert fake.external_ci is False and GitHubProvider.external_ci is True
    poll(ctx)
    assert status(client, keys, rid)["status"] == "merged"
    head = next(iter(fake.statuses))
    assert set(fake.statuses[head]) == {CONTEXT_KUBECONFORM, CONTEXT_KYVERNO, CONTEXT_CMAPI}
