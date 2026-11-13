## C3 — P2: pagination cannot recover suites excluded by GitHub

MEASURED — The baseline reports success for ci/kyverno when suite 1 failed and suites 2–1001 passed. All ten pages returned by the commit endpoint were read. The regression fails on the baseline (exit 1) and passes with the isolated patch (exit 0, 1 passed). Logs: logs/C3-before.log and logs/C3-after-provider.log.

READ FROM CODE — Root cause: `_check_runs` only calls the commit endpoint. [GitHub REST documentation](https://docs.github.com/en/rest/checks/runs?apiVersion=2022-11-28#list-check-runs-for-a-git-reference) limits it to the newest 1,000 suites; HTTP pagination cannot recover older suites. The test models this documented response, without calling GitHub. Empty suites consume this limit as well.

PROPOSAL NOT OPERATED — The production remedy is to enumerate suites first; beyond the endpoint window, read each suite separately, keeping existing app/suite/name rerun semantics. Existing MAX_PAGES bounds still raise instead of returning partial success. This adds a suite-list read and potentially many per-suite reads, using the same Checks: read permission. No deployment or real GitHub verification occurred. The proposal was operated only on a local review copy.

MEASURED — Complete patch: patches/C3.patch, rooted at exported `head`, zero-fuzz dry-run exit 0. It includes production code, the complete regression, and mock routes for the newly used documented endpoint. Full replacement code follows.

READ FROM CODE — Path: cmapi/src/cmapi/core/git/github.py; complete replacement method:

```python
    def _check_runs(self, head: str) -> list[Mapping[str, Any]]:
        """The check runs of a commit, one per check. filter=latest asks for the latest attempts; within one check suite of one App
        a later id replaces an earlier one of the same name, in case a re-run's attempts still come back together. Two suites or two
        Apps reporting one name are two checks, and both count."""
        # The commit check-runs endpoint only covers the 1,000 newest suites.
        # Count every suite first: empty suites also consume that window.
        suites = self._pages("pr_check_suites", f"{self._repo()}/commits/{head}/check-suites", "check_suites")
        if len(suites) > 1000:
            runs = []
            for suite in suites:
                runs.extend(self._pages("pr_check_runs", f"{self._repo()}/check-suites/{suite['id']}/check-runs",
                                        "check_runs", filter="latest"))
        else:
            runs = self._pages("pr_check_runs", f"{self._repo()}/commits/{head}/check-runs", "check_runs", filter="latest")
        latest: dict[tuple[Any, Any, Any], Mapping[str, Any]] = {}
        for run in runs:
            key = (run["name"], (run.get("app") or {}).get("id"), (run.get("check_suite") or {}).get("id"))
            if key not in latest or run["id"] > latest[key]["id"]:
                latest[key] = run
        return list(latest.values())
```

READ FROM CODE — Path: cmapi/tests/service/test_github_check_runs.py; complete replacement helper (`provider`):

```python
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
```

READ FROM CODE — Same path; complete replacement method (`GitHubOverFake.__call__`):

```python
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
```

READ FROM CODE — Path: cmapi/tests/service/test_review_r87_c3.py; complete regression file:

```python
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
```
