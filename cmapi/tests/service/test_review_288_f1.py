"""PR #288 review, F1: a closed PR after the apply re-creates the request branch, and must never overwrite a head that is not
cmapi's for this request (the arbitration of #286, row 3: "A head with no cmapi trailers is a person's work: refuse, log and
alert. Never overwrite it"). On b660758 GitWorkspace.recreate pushes over any head with a lease on the sha it saw."""
from __future__ import annotations

import importlib

from gitserver import git, person_commit
from test_git_layer import drive, layer  # noqa: F401  (the fixture)


def test_a_closed_pr_whose_branch_a_person_rewrote_is_merge_failed_and_the_persons_head_is_kept(layer, monkeypatch):
    w = layer
    rid = w.create()
    merge_mod = importlib.import_module("cmapi.jobs.merge")
    real = merge_mod._merge
    seen = {}

    def closed_and_rewritten(ctx, repo, jobs, row, job):
        if w.host.prs[1]["state"] == "open":
            w.host.prs[1]["state"] = "closed"
            # A person's commit with no cmapi trailers on the request branch: made on main, moved to the branch, main put back.
            main = w.host.head("main")
            foreign = person_commit(w.bare, {"README.md": "a person's work\n"}, "a person's own work", w.tmp)
            git("--git-dir", str(w.bare), "update-ref", f"refs/heads/{row.pr['branch']}", foreign, cwd=w.bare, home=w.tmp)
            git("--git-dir", str(w.bare), "update-ref", "refs/heads/main", main, cwd=w.bare, home=w.tmp)
            seen.update(branch=row.pr["branch"], foreign=foreign)
        return real(ctx, repo, jobs, row, job)

    monkeypatch.setattr(merge_mod, "_merge", closed_and_rewritten)
    drive(w.ctx)
    v = w.view(rid)
    assert w.host.head(seen["branch"]) == seen["foreign"], "a person's head on the request branch was overwritten"
    assert v["status"] == "merge_failed", [(e["event"], e["note"]) for e in v["events"]]
    assert 2 not in w.host.prs, "no PR opens on a branch that is not cmapi's"
