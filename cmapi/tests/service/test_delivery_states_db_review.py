"""#448, #449, #451 (Codex's F5, F6, F8 of the Git delivery review, as OB3 corrected them): a hand merge between the checks and
the apply is adopted; the folder at a merge is a gate on every path that records one; a comment whose answer was lost is not
posted twice. These against PostgreSQL, real Git and the GitHub stub (test_git_layer's world); the doubles are in
tests/test_delivery_states_review.py."""
from __future__ import annotations

import json

import httpx
import pytest

from gitserver import git
from test_flow import AMY, OLA, auth
from test_git_layer import API, drive, layer  # noqa: F401  (the fixture)

REPO = "/repos/cmapi/cluster-configs-test"


def person_merges(w, branch: str, head: str) -> None:
    """A person merges PR #n on the host, pinned to head, as GitHub's merge button does."""
    n = next(n for n, p in w.host.prs.items() if p["ref"] == branch and p["state"] == "open")
    answer = w.host(httpx.Request("PUT", f"{API}{REPO}/pulls/{n}/merge", content=json.dumps({"sha": head}).encode()))
    assert answer.status_code == 200, answer.text


# ---------------------------------------------------------------- #448: a hand merge between pr_checks and apply

@pytest.mark.parametrize("deletes_branch", [True, False])
def test_a_hand_merge_after_the_checks_is_adopted_by_the_apply_job(layer, deletes_branch):
    w = layer
    rid = w.create()
    assert drive(w.ctx, limit=3) == ["push_branch", "open_pr", "pr_checks"]          # apply is next
    branch = f"cmapi/CRC/{rid}"
    person_merges(w, branch, w.host.head(branch))
    if deletes_branch:
        git("--git-dir", str(w.bare), "update-ref", "-d", f"refs/heads/{branch}", cwd=w.bare, home=w.tmp)
    drive(w.ctx)
    v = w.view(rid)
    events = w.events(rid)
    assert v["status"] == "synced", [(e["event"], e["note"]) for e in v["events"]]
    assert "merge_verified" in events and events.index("merged") < events.index("applied"), "watch_sync applied from main"
    assert len(w.host.merges) == 1, "cmapi merged nothing itself"


# ---------------------------------------------------------------- #449: the folder at the merge, on the hand-merge path of a delete

def test_a_hand_merged_delete_whose_merge_keeps_the_folder_is_sync_failed_not_awaiting_prune(layer):
    w = layer
    h = auth(w.keys, "ola", **OLA)
    w.create()
    drive(w.ctx)
    etag = w.client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    delete = w.client.delete("/api/v1/clusters/CRC/namespaces/payments-dev",
                             headers={**h, "If-Match": etag}).json()["requestId"]
    w.client.post(f"/api/v1/requests/{delete}:approve", json={}, headers=auth(w.keys, "amy", **AMY))
    for _ in range(10):                          # the approval's notification first, then push_branch and open_pr
        if w.view(delete)["status"] == "pr_open":
            break
        drive(w.ctx, limit=1)
    assert w.view(delete)["status"] == "pr_open"
    branch = f"cmapi/CRC/{delete}"
    # A person pushes a commit that puts the folder back on the branch, and merges it: main keeps the namespace.
    tree = git("--git-dir", str(w.bare), "rev-parse", "main^{tree}", cwd=w.bare, home=w.tmp)
    restored = git("--git-dir", str(w.bare), "commit-tree", tree, "-p", w.host.head(branch), "-m", "keep it",
                   cwd=w.bare, home=w.tmp)
    git("--git-dir", str(w.bare), "update-ref", f"refs/heads/{branch}", restored, cwd=w.bare, home=w.tmp)
    person_merges(w, branch, restored)
    drive(w.ctx)
    v = w.view(delete)
    assert v["status"] == "sync_failed", [(e["event"], e["note"]) for e in v["events"]]
    assert "awaiting_prune" not in [e["event"] for e in v["events"]] and "prune_pending" not in w.events(delete)
