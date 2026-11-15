"""PR #288 review, F2: git_reconcile deletes the request branch of a final-state request at any head. push_branch refused that
branch because its head is not cmapi's ("leaves the branch alone", jobs/push_branch.py), and git_cleanup keeps such a head
(jobs/git_cleanup.py:37-45); the reconciler must keep it too (the arbitration of #286, row 3)."""
from __future__ import annotations

import importlib

from gitserver import git, person_commit
from test_git_layer import drive, layer  # noqa: F401  (the fixture)
from cmapi.core.db.repo import JobRepo


def test_the_reconciler_keeps_a_foreign_head_that_push_branch_refused(layer, monkeypatch):
    w = layer
    rid = w.create()
    branch = f"cmapi/CRC/{rid}"
    main = w.host.head("main")
    foreign = person_commit(w.bare, {"README.md": "a person's work\n"}, "a person's own work", w.tmp)
    git("--git-dir", str(w.bare), "update-ref", f"refs/heads/{branch}", foreign, cwd=w.bare, home=w.tmp)
    git("--git-dir", str(w.bare), "update-ref", "refs/heads/main", main, cwd=w.bare, home=w.tmp)
    drive(w.ctx)
    assert w.view(rid)["status"] == "failed" and "branch_refused" in w.events(rid)
    assert w.host.head(branch) == foreign, "push_branch leaves a foreign branch alone"
    rec = importlib.import_module("cmapi.jobs.git_reconcile")
    monkeypatch.setattr(rec, "GRACE_SECONDS", -1)
    with w.ctx.db.session() as s:
        rec.git_reconcile(w.ctx, s, JobRepo(s).enqueue("git_reconcile"))
    assert w.host.head(branch) == foreign, "git_reconcile deleted a head that is not cmapi's for the request"
