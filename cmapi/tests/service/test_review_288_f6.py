"""PR #288 review, F6: git_reconcile takes everything after cmapi/<cluster>/ as the request ID, while its docstring and Fable's
design 5.3 say "the request ID is the last path segment". A PR opened before #286, on cmapi/<cluster>/<namespace>/<requestId>,
then finds no row and is closed as an orphan while its request is still pr_open (an upgrade with a request in flight)."""
from __future__ import annotations

from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.jobs.git_reconcile import git_reconcile
from test_flow import NS, OLA, auth
from test_review_d_delivery import run_until, status


def test_an_open_pr_of_the_branch_layout_before_286_is_not_closed_as_an_orphan(world):
    client, ctx, fake, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "pr_checks") == "pr_checks"
    new, legacy = fake.prs[1]["branch"], f"cmapi/CRC/payments-dev/{rid}"
    for table in (fake.branches, fake.heads, fake.owners, fake.based_on, fake.based_on_sha):
        if new in table:
            table[legacy] = table.pop(new)
    fake.prs[1]["branch"] = legacy
    with ctx.db.session() as s:
        row = RequestRepo(s).get(rid)
        row.pr = {**row.pr, "branch": legacy}
    with ctx.db.session() as s:
        git_reconcile(ctx, s, JobRepo(s).enqueue("git_reconcile"))
    assert fake.prs[1]["state"] == "open", "the in-flight PR of a pr_open request was closed as an orphan"
    assert legacy in fake.branches and status(client, keys, rid)["status"] == "pr_open"
