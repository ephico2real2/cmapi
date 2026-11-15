"""deliver_pr: delivery.mode apply, a create or a change whose PR passed its checks (#286, the Atlantis model). Apply the
request branch's folder, confirm it by a read, and only then merge the PR, so main records only what succeeded.

    1. The PR head is the head the checks passed on, its folder is the approved plan, and the merge check passes (so nothing
       is applied that could not merge). Anything else fails the request.
    2. Server-side apply of that folder with the deliverer identity, once (job.payload["applied"]), and the removal of the
       objects the plan drops. A namespace that exists and is not cmapi-managed is refused, nothing applied.
    3. confirmed_by_read. Not yet: wait at delivery.pollInterval, bounded by delivery.syncTimeout from the job's start.
    4. The merge check and the merge (jobs/merging.py). Then merged, and synced: the read already confirmed it.

A failure at 1 to 3 comments on the PR and closes it, leaves main untouched, and fails the request with the reason. A failure
after the apply says that the cluster holds the change and main does not. A cluster that cannot be reached is a wait, as in
watch_sync. Deletes are not here: they merge first and wait for an operator's prune confirmation (watch_sync, prune).
"""
from __future__ import annotations

from datetime import datetime, timezone

import yaml
from sqlalchemy.orm import Session

from cmapi.core.clients.kube import ClusterUnreachable, KubeError
from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo, utcnow
from cmapi.core.errors import Problem
from cmapi.core.git.oplog import git_context
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.observability import LEAD_TIME
from cmapi.core.ports import PrRef
from cmapi.core.render.manifests import folder
from cmapi.core.sync import ApplyDelivery, confirmed_by_read
from cmapi.jobs.merging import merge_after_check, refused


def deliver_pr(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status != S.PR_OPEN.value or not row.pr:
        jobs.done(job)
        return
    with git_context(request_id=row.request_id, cluster=row.cluster_id, namespace=row.namespace, branch=row.pr["branch"],
                     attempt=job.attempts):
        _deliver(ctx, repo, jobs, row, job)


def _fail(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, pr: PrRef, why: str, applied: bool) -> None:
    if applied:
        why += "; the cluster holds what was applied, and main does not"
    repo.move(row, E.PR_FAILED, "cmapi-deliverer", why[:240])
    jobs.fence()
    ctx.git.close(pr, f"cmapi: {row.request_id} was not delivered: {why}. The PR is not merged; the request is failed and may be retried.")
    ctx.git.cleanup(row.cluster_id, row.request_id)
    jobs.done(job)


def _deliver(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow) -> None:
    from cmapi.jobs.watch_sync import _deliverer, _direct, _managed, _NotYet, _reader_cache

    pr = PrRef(number=row.pr["number"], url=row.pr["url"], branch=row.pr["branch"], head_sha=row.pr["head"])
    payload = dict(job.payload or {})
    applied = bool(payload.get("applied"))
    checked = payload.get("head") or pr.head_sha
    files = {p: t for p, t in row.plan["files"].items() if t is not None}
    removed = {p: row.plan["prev"][p] for p, t in row.plan["files"].items() if t is None and p in (row.plan.get("prev") or {})}
    head = ctx.git.branch_head(pr.branch)
    if head != checked:
        return _fail(ctx, repo, jobs, row, job, pr, f"the PR head moved from {checked[:8]} to {(head or 'nothing')[:8]} after its checks",
                     applied)
    on_branch = ctx.git.tree_files(head, folder(row.cluster_id, row.namespace))
    if on_branch != files:
        return _fail(ctx, repo, jobs, row, job, pr, f"the branch's folder at {head[:8]} differs from the approved plan", applied)
    if not applied and refused(ctx, repo, jobs, row, pr, head):
        jobs.done(job)                                    # checked before the apply too: nothing is applied that cannot merge
        return
    try:
        if not applied:
            d = ApplyDelivery(_deliverer(ctx, row.cluster_id))
            live = d.client.get_object("Namespace", None, row.namespace)
            if live is not None and not _managed(live):
                return _fail(ctx, repo, jobs, row, job, pr,
                             f"{row.namespace} exists on the cluster and cmapi does not manage it; nothing applied", False)
            jobs.fence()
            n = d.apply_folder(files)
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
                d.prune_objects(row.namespace, obsolete)
            applied = True
            job.payload = {**payload, "applied": True, "applied_at": utcnow().isoformat()}
            repo.event(row, "applied", "cmapi-deliverer", f"server-side applied {n} objects from {pr.branch} at {head[:8]}, before the merge")
        cache = _reader_cache(ctx, row.cluster_id)
        ok, why = confirmed_by_read(lambda k, ns, n: cache.get(k, ns, n) or _direct(cache, k, ns, n), row.namespace, files)
        if not ok:
            raise _NotYet(why)
    except KubeError as exc:
        if exc.status in (400, 403, 409, 422):           # the cluster refused the objects: waiting cannot fix it
            return _fail(ctx, repo, jobs, row, job, pr, f"the cluster refused the apply: {str(exc)[:160]}", applied)
        return _wait(ctx, repo, jobs, row, job, pr, f"{type(exc).__name__}: {exc}", applied)
    except (_NotYet, ClusterUnreachable, Problem) as exc:
        return _wait(ctx, repo, jobs, row, job, pr, str(getattr(exc, "detail", None) or exc), applied)
    merge_sha = merge_after_check(ctx, repo, jobs, row, pr, head, applied=True)
    if merge_sha is None:
        jobs.done(job)
        return
    repo.move(row, E.MERGED, "cmapi-bot", f"merged {merge_sha[:8]} after the apply was confirmed")
    repo.move(row, E.SYNCED, "cmapi-deliverer", f"confirmed by a read before the merge: {why}")
    approval = "auto" if (row.requirement or {}).get("auto") else "human"
    LEAD_TIME.labels(row.plugin, row.action, approval).observe((datetime.now(timezone.utc) - row.created_at).total_seconds())
    jobs.done(job)


def _wait(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, pr: PrRef, why: str, applied: bool) -> None:
    """Not confirmed yet, or the cluster cannot be read: wait, with the reason on the request once, up to syncTimeout."""
    waited = (utcnow() - job.created_at).total_seconds()
    if waited > ctx.delivery.sync_timeout_seconds:
        return _fail(ctx, repo, jobs, row, job, pr, f"not confirmed after {int(waited)} s: {why[:160]}", applied)
    if job.last_error != why[:2000]:
        repo.event(row, "sync_wait", "worker", why[:200])
    jobs.retry(job, why, ctx.delivery.poll_seconds)
    job.attempts = 0                                     # waiting is not a failure
