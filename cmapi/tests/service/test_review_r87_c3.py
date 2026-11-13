import httpx
from cmapi.core.git.github import GitHubProvider
from test_github_check_runs import API, PR, SHA, run, paged, CONTEXT_KYVERNO


def test_failure_outside_the_commit_endpoints_1000_suite_window():
    """The documented cap is on suites, independent of HTTP pagination."""
    suites = [{"id": i} for i in range(1, 1002)]
    runs = [run(CONTEXT_KYVERNO, id=i, suite=i, conclusion="failure" if i == 1 else "success") for i in range(1, 1002)]
    seen = []

    def host(request):
        seen.append(request)
        path = request.url.path
        if path == "/repos/o/r/pulls/7":
            return httpx.Response(200, json={"state": "open", "head": {"sha": SHA}})
        if path == f"/repos/o/r/commits/{SHA}/status":
            return paged(request, "statuses", [])
        if path == f"/repos/o/r/commits/{SHA}/check-runs":
            # All pages, correctly linked, but GitHub has already discarded suite 1.
            return paged(request, "check_runs", runs[1:])
        if path == f"/repos/o/r/commits/{SHA}/check-suites":
            return paged(request, "check_suites", suites)
        if path.startswith("/repos/o/r/check-suites/") and path.endswith("/check-runs"):
            suite_id = int(path.split("/")[-2])
            return paged(request, "check_runs", [runs[suite_id - 1]])
        raise AssertionError(f"unexpected request: {request.method} {path}")

    git = GitHubProvider(API, "o/r", "local-placeholder")
    git._client.close()
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(host))
    assert git.pr_status(PR).checks[CONTEXT_KYVERNO] == "failure"
    assert any(r.url.path == "/repos/o/r/check-suites/1/check-runs" for r in seen)
