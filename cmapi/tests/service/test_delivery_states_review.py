"""#448, #449, #451 (Codex's F5, F6, F8 of the Git delivery review, as OB3 corrected them), with doubles: the states reached
directly, no database. The same cases against PostgreSQL, real Git and the GitHub stub are in
tests/service/test_delivery_states_db_review.py."""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace as NS

import httpx
import pytest

from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.github import GitHubProvider
from cmapi.core.lifecycle import State as S, transition
from cmapi.core.ports import PrRef, PrStatus


# ---------------------------------------------------------------- doubles: the same gates, reached directly

class Repo:
    def __init__(self, events=()):
        self.seen, self._events = [], list(events)

    def events(self, request_id):
        return self._events

    def event(self, row, event, by, note="", detail=None):
        self.seen.append(event)

    def move(self, row, event, by, note=""):
        row.status = transition(S(row.status), event).after.value
        self.seen.append(event.value)


class Jobs:
    def __init__(self):
        self.queued, self.finished = [], False

    def fence(self):
        pass

    def done(self, job):
        self.finished = True

    def enqueue(self, kind, **kw):
        self.queued.append(kind)


FOLDER = "clusters/CRC/namespaces/demo/"
REL = FOLDER + "namespace.yaml"
HEAD, MERGE = "a" * 40, "b" * 40


def row(status="pr_open"):
    return NS(status=status, cluster_id="CRC", namespace="demo", request_id="req-1", action="create",
              plan={"files": {REL: "approved"}, "prev": {}}, merge_sha=None,
              pr={"number": 1, "url": "", "branch": "cmapi/CRC/req-1", "head": HEAD})


@pytest.mark.parametrize("status", ["pr_open", "sync_failed"])
def test_apply_adopts_a_hand_merge_whose_branch_is_gone(status):
    apply_mod = importlib.import_module("cmapi.jobs.apply")
    r = row(status)
    repo = Repo([NS(event="apply_started", detail={"head": HEAD})] if status == "sync_failed" else [])
    jobs = Jobs()
    ctx = NS(git=NS(pr_status=lambda pr: PrStatus("merged", {}, MERGE, HEAD), branch_head=lambda b: None,
                    tree_files=lambda sha, f: {REL: "approved"}, cleanup=lambda *a: None))
    apply_mod._apply(ctx, repo, jobs, r, NS(payload={"head": HEAD}))
    assert (r.status, r.merge_sha, jobs.queued) == ("merged", MERGE, ["watch_sync", "git_cleanup"])


def test_an_apply_that_waits_on_the_cluster_reads_no_pr():
    """Control for the shape of the #448 fix: the PR is read only when a check refuses. An apply that waits at pollInterval
    (here: the cluster cannot be reached) makes no extra host call per poll. Passes on main; Codex's upfront read makes one."""
    from datetime import datetime, timezone

    from cmapi.core.clients.kube import ClusterUnreachable
    from cmapi.core.git.base import MergeCheck

    apply_mod = importlib.import_module("cmapi.jobs.apply")
    reads, retried = [], []

    def unreachable(cid):
        raise ClusterUnreachable("CRC is down")
    ctx = NS(git=NS(pr_status=lambda pr: reads.append(pr) or PrStatus("open", {}, None, HEAD), branch_head=lambda b: HEAD,
                    tree_files=lambda sha, f: {REL: "approved"}, default_branch="main",
                    merge_check=lambda *a: MergeCheck("m" * 40, HEAD)),
             deliverer_factory=unreachable, delivery=NS(sync_timeout_seconds=600, poll_seconds=5))
    jobs = Jobs()
    jobs.retry = lambda job, why, delay: retried.append(why)
    job = NS(payload={"head": HEAD}, created_at=datetime.now(timezone.utc), last_error=None, attempts=1)
    apply_mod._apply(ctx, Repo(), jobs, row(), job)
    assert retried and reads == []


@pytest.mark.parametrize("status", ["pr_open", "applied"])
def test_a_merge_whose_folder_is_not_the_plan_never_queues_delivery(status):
    merge_mod = importlib.import_module("cmapi.jobs.merge")
    r, repo, jobs = row(status), Repo(), Jobs()
    ctx = NS(git=NS(tree_files=lambda sha, f: {REL: "unapproved"}, cleanup=lambda *a: None))
    merge_mod._merged(ctx, repo, jobs, r, NS(), MERGE, adopted=True)
    assert r.status == "sync_failed" and "watch_sync" not in jobs.queued


def test_a_merge_with_no_sha_to_read_is_sync_failed():
    merge_mod = importlib.import_module("cmapi.jobs.merge")
    r, repo, jobs = row(), Repo(), Jobs()
    ctx = NS(git=NS(tree_files=lambda sha, f: pytest.fail("nothing to read"), cleanup=lambda *a: None))
    merge_mod._merged(ctx, repo, jobs, r, NS(), "", adopted=True)
    assert r.status == "sync_failed" and "watch_sync" not in jobs.queued


def test_pr_checks_sends_a_hand_merge_through_the_post_merge_check():
    checks = importlib.import_module("cmapi.jobs.pr_checks")
    r, repo, jobs = row(), Repo(), Jobs()
    ctx = NS(git=NS(pr_status=lambda pr: PrStatus("merged", {}, MERGE, HEAD), tree_files=lambda sha, f: {REL: "unapproved"},
                    cleanup=lambda *a: None))
    checks._pr_checks(ctx, repo, jobs, r, NS())
    assert r.status == "sync_failed" and "merge_verified" in repo.seen and "watch_sync" not in jobs.queued


# ---------------------------------------------------------------- #451: a comment whose answer was lost

def test_a_comment_whose_answer_was_lost_is_not_posted_again():
    kept = []

    def host(request):
        if request.method == "GET":
            return httpx.Response(200, json=[{"body": body} for body in kept])
        kept.append(json.loads(request.content)["body"])
        return httpx.Response(502 if len(kept) == 1 else 201)       # the host kept the first, and its answer was lost
    provider = GitHubProvider("https://offline.invalid", "o/r", "test-token-0123456789")
    provider._client.close()
    provider._client = httpx.Client(base_url="https://offline.invalid", transport=httpx.MockTransport(host))
    pr = PrRef(1, "", "cmapi/CRC/req-1", HEAD)
    with pytest.raises(GitUnavailable):
        provider.comment(pr, "cmapi: merge failed; :retry merges it")
    provider.comment(pr, "cmapi: merge failed; :retry merges it")
    assert kept == ["cmapi: merge failed; :retry merges it"]
