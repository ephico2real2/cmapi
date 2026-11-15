"""The merge of a request's PR, after a check (#286, "Before every merge").

1. Fetch main and run git merge-tree --write-tree on main and the PR head: a conflict lists its paths.
2. The request's folder on main must still be the plan's base: the one-open-request-per-namespace lock (core/db/repo.py)
   means no other request changed it, so a difference is a hand edit or a fault, never a race to resolve.

A refused merge logs the paths and the shas (core/git/oplog.py), puts the same reason on the request's timeline, comments on the
PR and closes it, and fails the request. main is untouched.
"""
from __future__ import annotations

from typing import Any

from cmapi.core.context import AppContext
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.lifecycle import Event as E
from cmapi.core.ports import PrRef
from cmapi.core.render.manifests import folder


def delivery_mode(ctx: AppContext, cluster_id: str) -> str:
    st = ctx.registry.get(cluster_id)
    return st.policy.delivery if st.policy and st.policy.delivery else ctx.delivery.mode


def refused(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row: Any, pr: PrRef, head: str, applied: bool = False) -> bool:
    """The merge check. True when it refused: the request is then failed, the PR commented on and closed, and main untouched.
    applied says that the cluster already holds the change (apply before merge), which the reason then says too."""
    check = ctx.git.merge_check(head, folder(row.cluster_id, row.namespace), row.plan.get("prev") or {})
    if check.ok:
        return False
    why = (f"conflicts with {ctx.git.default_branch} at {check.main_sha[:8]} in {', '.join(check.conflicts)}" if check.conflicts
           else f"the folder on {ctx.git.default_branch} at {check.main_sha[:8]} is no longer the plan's base")
    if applied:
        why += "; the cluster holds the applied change, and main does not"
    repo.event(row, "merge_refused", "worker", why[:300],
               {"conflicts": list(check.conflicts), "folderMoved": check.folder_moved, "main": check.main_sha, "head": head})
    repo.move(row, E.PR_FAILED, "worker", f"merge refused: {why}"[:240])
    jobs.fence()
    ctx.git.close(pr, f"cmapi: the merge of {row.request_id} was refused: {why}. The request is failed and may be retried.")
    ctx.git.cleanup(row.cluster_id, row.request_id)
    return True


def merge_after_check(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row: Any, pr: PrRef, head: str,
                      applied: bool = False) -> str | None:
    """The merge sha, or None when the check refused the merge and the request is failed."""
    if refused(ctx, repo, jobs, row, pr, head, applied):
        return None
    jobs.fence()
    sha = ctx.git.merge(pr, head)
    row.merge_sha = sha
    ctx.git.cleanup(row.cluster_id, row.request_id)
    return sha
