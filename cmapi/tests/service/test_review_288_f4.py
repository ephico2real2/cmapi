"""PR #288 review, F4: every delivery job fences before each external effect (jobs/delivery.py; Fable's design 1.4). merge._reopen
re-creates the request branch (a git push) before its jobs.fence(), so a worker whose lease was claimed still pushes."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from cmapi.core.db.repo import LeaseLost


def test_reopen_fences_before_it_recreates_the_branch(monkeypatch):
    merge_mod = importlib.import_module("cmapi.jobs.merge")
    calls: list[str] = []
    monkeypatch.setattr(merge_mod, "branch_request", lambda ctx, row: "the branch request")

    class Git:
        def branch_head(self, branch):
            return "f" * 40                            # the branch is gone or elsewhere: _reopen re-creates it

        def recreate_branch(self, req, base, expected):
            calls.append("push")
            return expected

        def open_pr(self, *a):
            calls.append("open_pr")

    class StaleJobs:
        def fence(self):
            calls.append("fence")
            raise LeaseLost("job 1: lease generation 1 of w was superseded by 2 (w2)")

    row = SimpleNamespace(request_id="req-1", pr={"branch": "cmapi/CRC/req-1", "base": "b" * 40, "number": 1})
    with pytest.raises(LeaseLost):
        merge_mod._reopen(SimpleNamespace(git=Git()), None, StaleJobs(), row, "a" * 40)
    assert calls == ["fence"], f"a stale worker ran {calls} before its fence refused it"
