"""pr_checks: the PR is open. Run kubeconform and the Kyverno bundle on the PR head and the cmapi check
(the request is approved and the head holds exactly the approved plan), post the cmapi check as a commit
status, and merge with the expected head when all are green. A closed PR, a failed check, or a head that
moved is failed; a Git host outage, or a validator that could not run, is retried.

On a host whose own CI reports ci/* (git.external_ci: GitHub, from the config repository's Actions) the
worker reads those two contexts and never posts them. A context not reported yet is a wait, polled at
delivery.pollInterval, spending no attempts and bounded by delivery.syncTimeout from when the job was
queued; past that the request is failed. A failed one ends the wait at once. The local validators still
run once CI has finished: CI's green does not excuse what they refuse. On the Gitea stand-in, which has no
runner, the worker posts ci/* from those validators, as it always has (#60). GitHub's host CI is off by default since #286:
the worker then posts ci/* the same way, and never reads the Checks API.

Since #286 the checks are one job and the merge another (Fable's design, 2). When every check passes, the merge check runs
(git merge-tree and the plan's base; a refusal before any apply is superseded), then: with delivery.mode apply a create or a
change goes to the apply job, which applies the branch, confirms it, and only then lets merge run, so main records only what
succeeded. A delete, and delivery.mode argocd, go to merge at once (the arbitration, row 4). The worker posts its checks as
commit statuses only when the provider asks for them (post_statuses: the Gitea stand-in, or GitHub with host CI or postStatus)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo, utcnow
from cmapi.core.git.base import IncompleteList
from cmapi.core.observability import MERGE_CONFLICTS
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.ports import PrRef
from cmapi.core.rejections import record_ci
from cmapi.core.render.manifests import folder, plan_hash
from cmapi.jobs.delivery import end_pr, mode_of, request_context

CONTEXT_KUBECONFORM = "ci/kubeconform"
CONTEXT_KYVERNO = "ci/kyverno"
CONTEXT_CMAPI = "cmapi/check"
CI_CONTEXTS = [CONTEXT_KUBECONFORM, CONTEXT_KYVERNO]
REQUIRED_CONTEXTS = [*CI_CONTEXTS, CONTEXT_CMAPI]


def pr_checks(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status != S.PR_OPEN.value or not row.pr:
        jobs.done(job)
        return
    with request_context(ctx, row, job):
        _pr_checks(ctx, repo, jobs, row, job)


def _pr_checks(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow) -> None:
    pr = PrRef(number=row.pr["number"], url=row.pr["url"], branch=row.pr["branch"], head_sha=row.pr["head"])
    status = ctx.git.pr_status(pr)
    if status.state == "closed":
        repo.move(row, E.PR_FAILED, "worker", "the PR was closed")
        jobs.done(job)
        jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
        return
    if status.state == "merged":
        # A person merged it before any apply: adopted through the merge job's post-merge check (#449). In apply mode
        # watch_sync then applies from main (Fable 1.1).
        from cmapi.jobs.merge import _merged

        _merged(ctx, repo, jobs, row, job, status.merge_sha or "", adopted=True)
        return
    # A context nobody has reported yet is pending: the workflow may not have started.
    ci = {c: status.checks.get(c, "pending") for c in CI_CONTEXTS} if ctx.git.external_ci else {}
    ci_failed = [c for c, state in ci.items() if state == "failure"]
    ci_waiting = [c for c, state in ci.items() if state == "pending"]
    if ci_waiting and not ci_failed:
        _wait_for_ci(ctx, repo, jobs, row, job, pr, ci_waiting)
        return
    head = ctx.git.branch_head(pr.branch) or pr.head_sha
    tree =ctx.git.tree_files(head, folder(row.cluster_id, row.namespace))
    expected = {p: t for p, t in row.plan["files"].items() if t is not None}
    # The cmapi check: approved request, PR head == approved plan hash (a push after approval fails it).
    actual: dict[str, str | None] = dict(tree)
    for p, t in row.plan["files"].items():
        if t is None and p not in tree:
            actual[p] = None
    # The folder comparison sees only the folder. The bot alone writes this branch, so any other head means
    # someone pushed, possibly outside the folder (another namespace's folder, CI files): the merge would carry it.
    try:
        outside = sorted(ctx.git.changed_paths(head) - set(row.plan["files"]))
    except IncompleteList as exc:      # a list that the host cut cannot show that nothing is outside the plan: the check fails
        outside = [f"a list that is not complete: {exc}"]
    cmapi_ok = not outside and head == pr.head_sha and tree == expected and plan_hash(actual) == row.plan_hash
    # The default branch's folder is what this merge changes: a value that it already holds is not refused (#212).
    base, _ = ctx.git.read_folder(folder(row.cluster_id, row.namespace))
    findings = ctx.pipeline.validator.validate(tree, row.cluster_id, row.env, previous=base)
    # Only an error fails a check. In audit a Kyverno finding is a warning (core/validate, #213): the plan showed it and the
    # approvers accepted it, so the PR check reports it and does not fail, as the cluster's Audit action does.
    errors = [f for f in findings if f.severity == "error"]
    audited = [f for f in findings if f.severity != "error"]
    kc = [f for f in errors if f.source in ("kubeconform", "cmapi")]
    ky = [f for f in errors if f.source == "kyverno"]
    ky_text = "; ".join(f"{f.rule}: {f.message}" for f in ky) or \
        ("audit, not refused: " + "; ".join(f"{f.rule}: {f.message}" for f in audited) if audited else "policies ok")
    link = f"{ctx.cfg.raw_instance['instance'].get('publicUrl', '')}/api/v1/requests/{row.request_id}"
    if ctx.git.post_statuses:
        jobs.fence()                   # the statuses are external writes: a worker whose lease was claimed posts none
        if not ctx.git.external_ci:
            ctx.git.set_check(head, CONTEXT_KUBECONFORM, "failure" if kc else "success",
                              "; ".join(f.message for f in kc)[:200] or "schema ok", link)
            ctx.git.set_check(head, CONTEXT_KYVERNO, "failure" if ky else "success",
                              ky_text[:200], link)
        ctx.git.set_check(head, CONTEXT_CMAPI, "success" if cmapi_ok else "failure",
                          f"request {row.request_id} approved, head == plan {row.plan_hash[:12]}" if cmapi_ok
                          else f"head differs from the approved plan {row.plan_hash[:12]}, moved after it was opened, or touches {outside[:3]}", link)
    host_ci = "".join(f"; {c}: {state}" for c, state in ci.items())
    repo.event(row, "ci", "ci", f"kubeconform: {'pass' if not kc else 'fail'}; kyverno: {'fail' if ky else 'audit' if audited else 'pass'}; "
                                f"cmapi check: {'pass' if cmapi_ok else 'fail'}{host_ci}",
               {"findings": [f.message for f in findings], "head": head})
    if errors or not cmapi_ok or ci_failed:
        # The Policies tab lists a CI refusal beside the plan-time ones (#302), with the request it failed.
        why = (f"the pull request touches paths outside the plan: {', '.join(outside[:3])}" if outside else
               f"the head moved from {pr.head_sha[:8]} to {head[:8]} after the pull request was opened" if head != pr.head_sha else
               f"the head differs from the approved plan {row.plan_hash[:12]}")
        extra = [{"source": "cmapi", "policy": "cmapi-check", "rule": None, "kyvernoRule": None, "path": None,
                  "severity": "error", "message": why[:300]}] if not cmapi_ok else []
        extra += [{"source": "ci", "policy": context, "rule": None, "kyvernoRule": None, "path": None, "severity": "error",
                   "message": f"{context} failed on the Git host"} for context in ci_failed]
        record_ci(repo.s, ctx, row, errors, extra)
        if head != pr.head_sha:
            repo.event(row, "head_moved", "ci", f"PR head moved from {pr.head_sha[:8]} to {head[:8]} after approval")
        repo.move(row, E.PR_FAILED, "ci", "checks failed")
        end_pr(ctx, repo, jobs, row, "its checks failed; the request is failed and may be retried")
        jobs.done(job)
        return
    check = ctx.git.merge_check(head, folder(row.cluster_id, row.namespace), row.plan.get("prev") or {}, row.plan["files"])
    if not check.ok:
        MERGE_CONFLICTS.labels("pr_checks").inc()
        why = check.reason(ctx.git.default_branch)
        repo.event(row, "merge_check", "worker", why[:300], {"caller": "pr_checks", "main": check.main_sha, "head": head,
                                                             "conflict_paths": list(check.conflicts)})
        repo.move(row, E.BASE_CHANGED, "worker", why[:240])
        end_pr(ctx, repo, jobs, row, why)
        jobs.done(job)
        return
    jobs.done(job)
    nxt = "apply" if mode_of(ctx, row.cluster_id) == "apply" and row.action != "delete" else "merge"
    jobs.enqueue(nxt, request_id=row.request_id, cluster_id=row.cluster_id, payload={"head": head})


def _wait_for_ci(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, pr: PrRef, waiting: list[str]) -> None:
    """Waiting is not a failure, so the attempts reset and a Git outage keeps its own five. It is not silent either: one event per
    reason, and past the bound the PR closes and the request fails, because a workflow that never starts would otherwise hold the
    request's lock for ever."""
    why = f"waiting for {', '.join(waiting)} from the Git host's CI"
    waited = int((utcnow() - job.created_at).total_seconds())
    if waited >= ctx.delivery.sync_timeout_seconds:
        repo.move(row, E.PR_FAILED, "ci", f"{why}: not reported after {waited} s")
        end_pr(ctx, repo, jobs, row, f"{', '.join(waiting)} not reported after {waited} s; the request may be retried")
        jobs.done(job)
        return
    if job.last_error != why:
        repo.event(row, "ci_wait", "worker", why)
    jobs.retry(job, why, ctx.delivery.poll_seconds)
    job.attempts = 0
