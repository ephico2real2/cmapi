"""git_reconcile: every GIT_RECONCILE_EVERY seconds, one pending at a time. The PRs and branches that a crashed worker left
(#286; Fable's design 5.3). For each cluster of this instance it lists the open PRs and the branches under cmapi/<cluster>/,
reads the request ID from the last segment, and compares with the request's row. A branch younger than the grace period, by
its head's commit time, is left alone: a job may be writing it.

    PR or branch, no row, or a final state     close the PR, delete the branch with a lease    orphan
                                               when its head is cmapi's for the request;
                                               any other head is kept and counted               foreign_branch
    an open PR that is not row.pr.number       close it, keep the row's                         duplicate
    a branch, no PR, approved, no job pending  queue open_pr (it adopts, replaces or refuses)   stalled
    applied, merge_failed, sync_failed,        nothing, ever: the merge job reopens a closed PR
    awaiting_prune
    pr_open, no PR and no job, past syncTimeout  counted in cmapi_requests_stalled for the alert

Every action is fenced, logged as a cleanup event with its reason, and counted in cmapi_git_orphans_total{kind,action}."""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import ChangeRequestRow, JobRow
from cmapi.core.db.repo import JobRepo
from cmapi.core.git.oplog import Op
from cmapi.core.git.workspace import BRANCH_PREFIX
from cmapi.core.lifecycle import TERMINAL, State as S
from cmapi.core.observability import GIT_ORPHANS, REQUESTS_STALLED

GIT_RECONCILE_EVERY = 900
GRACE_SECONDS = 900
FINAL = {s.value for s in TERMINAL} | {S.FAILED.value}
HANDS_OFF = (S.APPLIED.value, S.MERGE_FAILED.value, S.SYNC_FAILED.value, S.AWAITING_PRUNE.value)


def git_reconcile(ctx: AppContext, s: Session, job: JobRow) -> None:
    jobs = JobRepo(s)
    stalled = 0
    now = time.time()
    for cluster_id in sorted(ctx.registry.clusters):
        prefix = f"{BRANCH_PREFIX}{cluster_id}/"
        with Op("cleanup", scope="reconcile", cluster=cluster_id) as op:
            prs = ctx.git.list_open(prefix)
            branches = ctx.git.list_branches(prefix)
            names = {p.branch[len(prefix):] for p in prs} | {b[len(prefix):] for b in branches}
            # The request ID is the branch's last segment (Fable 5.3), so a branch of the layout before #286,
            # cmapi/<cluster>/<namespace>/<requestId>, still finds its request.
            rid_of = {name: name.rsplit("/", 1)[-1] for name in names}
            rows = {r.request_id: r for r in s.scalars(select(ChangeRequestRow).where(ChangeRequestRow.request_id.in_(set(rid_of.values()))))}
            actions = []
            for name in sorted(names):
                rid, branch = rid_of[name], prefix + name
                head = branches.get(branch)
                young = head is not None and now - ctx.git.branch_time(head) < GRACE_SECONDS
                if young:
                    continue
                row = rows.get(rid)
                open_prs = [p for p in prs if p.branch == branch]
                if row is None or row.status in FINAL:
                    kind = "orphan"
                    for p in open_prs:
                        jobs.fence()
                        ctx.git.close(p, f"cmapi: {rid} is {'unknown' if row is None else row.status}; this PR will not merge.")
                        GIT_ORPHANS.labels(kind, "closed").inc()
                        actions.append(f"closed #{p.number}")
                    if head is not None:
                        # As git_cleanup: only a head that is cmapi's for this request. Anyone else's is left alone (the
                        # arbitration, row 3), such as the head push_branch refused.
                        ours = {(row.pr or {}).get("head"), (row.pr or {}).get("applied_head")} - {None} if row is not None else set()
                        if head in ours or ctx.git.request_of(head) == rid:
                            jobs.fence()
                            if ctx.git.delete_branch(branch, head):
                                GIT_ORPHANS.labels(kind, "deleted").inc()
                                actions.append(f"deleted {branch}")
                        else:
                            GIT_ORPHANS.labels("foreign_branch", "kept").inc()
                            actions.append(f"kept {branch}: its head {head[:8]} is not cmapi's for {rid}")
                    continue
                if row.status in HANDS_OFF:
                    continue
                number = (row.pr or {}).get("number")
                for p in open_prs:
                    if number is not None and p.number != number:
                        jobs.fence()
                        ctx.git.close(p, f"cmapi: {rid} has PR #{number}; this one is a duplicate.")
                        GIT_ORPHANS.labels("duplicate", "closed").inc()
                        actions.append(f"closed duplicate #{p.number}")
                if row.status == S.APPROVED.value and head is not None and not open_prs \
                        and jobs.pending("push_branch", rid) is None and jobs.pending("open_pr", rid) is None:
                    jobs.enqueue("open_pr", request_id=rid, cluster_id=cluster_id)
                    GIT_ORPHANS.labels("stalled", "requeued").inc()
                    actions.append(f"queued open_pr for {rid}")
                if row.status == S.PR_OPEN.value and not open_prs and not any(jobs.pending(k, rid) for k in ("pr_checks", "apply", "merge")) \
                        and (now - row.updated_at.timestamp()) > ctx.delivery.sync_timeout_seconds:
                    stalled += 1
            op.set(reason="reconcile", removed=actions)
    REQUESTS_STALLED.set(stalled)
    jobs.done(job)
    jobs.enqueue("git_reconcile", delay=GIT_RECONCILE_EVERY, payload={"every": GIT_RECONCILE_EVERY})
