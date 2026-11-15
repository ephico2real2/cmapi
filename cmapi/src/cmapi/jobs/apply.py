"""apply: delivery.mode apply, a create or a change whose PR passed its checks (#286; the Atlantis model, Fable's design 1.3).
Apply the PR head's folder, confirm it by a read, and move to applied; the merge job merges after that, so main records only
what succeeded.

    1. The branch is still at the pinned head, its folder is the plan's files, and the merge check passes. Before any apply a
       failure here ends the PR: failed, or superseded for a merge check. Nothing was applied.
    2. apply_started, in its own transaction under the row lock (jobs/delivery.py): from here the cluster may be ahead of main,
       so this request can only reach applied or sync_failed, never failed or superseded, and :cancel is refused.
    3. Server-side apply with the deliverer identity, and the removal of the objects the plan drops; a namespace that exists and
       is not cmapi-managed is refused before the first write.
    4. confirmed_by_read. Not yet: wait at pollInterval, up to syncTimeout from apply_started. Past it: sync_failed, PR and
       branch kept, the lock held; :retry runs this job again.
    5. applied, row.pr.applied_head, and the merge job.

Also from sync_failed with no merge sha (a :retry of an apply that had not finished). Deletes merge first (the arbitration,
row 4) and never come here.
"""
from __future__ import annotations


import yaml
from sqlalchemy.orm import Session

from cmapi.core.clients.kube import ClusterUnreachable, KubeError
from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo, utcnow
from cmapi.core.errors import Problem
from cmapi.core.git.oplog import Op
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.observability import MERGE_CONFLICTS
from cmapi.core.render.manifests import folder
from cmapi.core.sync import ApplyDelivery, confirmed_by_read
from cmapi.jobs.delivery import APPLY_STARTED, apply_started, end_pr, mark_apply_started, mode_of, planned, request_context


def apply(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    serves = row.status == S.PR_OPEN.value or (row.status == S.SYNC_FAILED.value and not row.merge_sha)
    if not serves or not row.pr or row.action == "delete" or mode_of(ctx, row.cluster_id) != "apply":
        jobs.done(job)
        return
    with request_context(ctx, row, job):
        _apply(ctx, repo, jobs, row, job)


def _stop(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, why: str, started: bool,
          event: E = E.PR_FAILED) -> None:
    """Before an apply started: the PR ends (failed, or superseded). After: sync_failed, the PR and the branch kept (F1)."""
    if started:
        if row.status == S.PR_OPEN.value:
            repo.move(row, E.SYNC_TIMEOUT, "cmapi-deliverer", f"{why}; the cluster may hold part of {row.pr['head'][:8]}"[:240])
        else:
            repo.event(row, "refused", "cmapi-deliverer", why[:300])
    else:
        repo.move(row, event, "cmapi-deliverer", why[:240])
        end_pr(ctx, repo, jobs, row, why)
    jobs.done(job)


def _apply(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow) -> None:
    from cmapi.jobs.watch_sync import _deliverer, _direct, _managed, _NotYet, _reader_cache

    head = (job.payload or {}).get("head") or row.pr.get("applied_head") or row.pr["head"]
    started = apply_started(repo, row) == head
    where = folder(row.cluster_id, row.namespace)
    files = planned(row)
    removed = {p: row.plan["prev"][p] for p, t in row.plan["files"].items() if t is None and p in (row.plan.get("prev") or {})}
    current = ctx.git.branch_head(row.pr["branch"])
    if current != head:
        return _stop(ctx, repo, jobs, row, job, f"the PR head moved from {head[:8]} to {(current or 'nothing')[:8]}", started)
    if ctx.git.tree_files(head, where) != files:
        return _stop(ctx, repo, jobs, row, job, f"the branch's folder at {head[:8]} is not the approved plan", started)
    check = ctx.git.merge_check(head, where, row.plan.get("prev") or {}, row.plan["files"])
    if not check.ok:
        MERGE_CONFLICTS.labels("apply").inc()
        why = check.reason(ctx.git.default_branch)
        repo.event(row, "merge_check", "worker", why[:300], {"caller": "apply", "main": check.main_sha, "head": head,
                                                             "conflict_paths": list(check.conflicts)})
        return _stop(ctx, repo, jobs, row, job, why, started, E.BASE_CHANGED)
    try:
        client = _deliverer(ctx, row.cluster_id)
        d = ApplyDelivery(client)
        live = d.client.get_object("Namespace", None, row.namespace)
        if live is not None and not _managed(live):
            return _stop(ctx, repo, jobs, row, job, f"{row.namespace} exists on the cluster and cmapi does not manage it; nothing applied",
                         started)
        if not started:
            if not mark_apply_started(ctx, row.request_id, head):
                jobs.done(job)                   # a :cancel won the row first: nothing applied
                return
            started = True
        jobs.fence()
        with Op("apply", head_sha=head) as op:
            n = d.apply_folder(files)
            pruned = 0
            if removed:
                # A file rename removes a path, not the Kubernetes objects retained in another file.
                def identity(doc):
                    meta = doc["metadata"]
                    return doc["kind"], meta.get("namespace", row.namespace), meta["name"]

                retained = {identity(doc) for text in files.values() for doc in yaml.safe_load_all(text) if doc}
                obsolete = {}
                for path, text in removed.items():
                    docs = [doc for doc in yaml.safe_load_all(text) if doc and identity(doc) not in retained]
                    if docs:
                        obsolete[path] = yaml.safe_dump_all(docs, sort_keys=False)
                pruned = d.prune_objects(row.namespace, obsolete)
            cache = _reader_cache(ctx, row.cluster_id)
            ok, why = confirmed_by_read(lambda k, ns, nm: cache.get(k, ns, nm) or _direct(cache, k, ns, nm), row.namespace, files)
            op.set(objects=n, pruned=pruned, confirmed=ok, reason=why)
        if not ok:
            raise _NotYet(why)
    except KubeError as exc:
        if exc.status in (400, 403, 409, 422):           # the cluster refused the objects: waiting cannot fix it
            return _stop(ctx, repo, jobs, row, job, f"the cluster refused the apply: {str(exc)[:160]}", started)
        return _wait(ctx, repo, jobs, row, job, f"{type(exc).__name__}: {exc}", started)
    except (_NotYet, ClusterUnreachable, Problem) as exc:
        return _wait(ctx, repo, jobs, row, job, str(getattr(exc, "detail", None) or exc), started)
    repo.move(row, E.APPLIED, "cmapi-deliverer", f"{n} objects from {row.pr['branch']} at {head[:8]}, before the merge, "
                                                  f"confirmed by a read: {why}"[:300])
    row.pr = {**row.pr, "applied_head": head}
    jobs.done(job)
    jobs.enqueue("merge", request_id=row.request_id, cluster_id=row.cluster_id, payload={"head": head})


def _wait(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, why: str, started: bool) -> None:
    """Not confirmed yet, or the cluster cannot be read: wait at pollInterval, with the reason on the request once. The clock
    starts at apply_started (or the job, before it); past syncTimeout the request is sync_failed, never failed."""
    marks = [e.at for e in repo.events(row.request_id) if e.event == APPLY_STARTED]
    since = marks[-1] if marks and started else job.created_at
    waited = (utcnow() - since).total_seconds()
    if waited > ctx.delivery.sync_timeout_seconds:
        return _stop(ctx, repo, jobs, row, job, f"not confirmed after {int(waited)} s: {why[:160]}", started)
    if job.last_error != why[:2000]:
        repo.event(row, "sync_wait", "worker", why[:200])
    jobs.retry(job, why, ctx.delivery.poll_seconds)
    job.attempts = 0                                     # waiting is not a failure
