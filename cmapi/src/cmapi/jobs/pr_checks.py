"""pr_checks: the PR is open. Run the checks CI would run on the PR head (kubeconform, the Kyverno
bundle) and the cmapi check (the request is approved and the head holds exactly the approved
plan), post each as a commit status, and merge with the expected head when all are green. A
closed PR, a failed check, or a head that moved is failed; a Git host outage is retried."""
from __future__ import annotations

from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.ports import PrRef
from cmapi.core.render.manifests import folder, plan_hash

CONTEXT_KUBECONFORM = "ci/kubeconform"
CONTEXT_KYVERNO = "ci/kyverno"
CONTEXT_CMAPI = "cmapi/check"
REQUIRED_CONTEXTS = [CONTEXT_KUBECONFORM, CONTEXT_KYVERNO, CONTEXT_CMAPI]


def pr_checks(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status != S.PR_OPEN.value or not row.pr:
        jobs.done(job)
        return
    pr = PrRef(number=row.pr["number"], url=row.pr["url"], branch=row.pr["branch"], head_sha=row.pr["head"])
    status = ctx.git.pr_status(pr)
    if status.state == "closed":
        repo.move(row, E.PR_FAILED, "worker", "the PR was closed")
        jobs.done(job)
        return
    if status.state == "merged":
        row.merge_sha = status.merge_sha
        repo.move(row, E.MERGED, "cmapi-bot", f"merged {(status.merge_sha or '')[:8]}")
        jobs.done(job)
        jobs.enqueue("watch_sync", request_id=row.request_id, cluster_id=row.cluster_id)
        return
    head = ctx.git.branch_head(pr.branch) or pr.head_sha
    tree = ctx.git.tree_files(head, folder(row.cluster_id, row.namespace))
    expected = {p: t for p, t in row.plan["files"].items() if t is not None}
    # The cmapi check: approved request, PR head == approved plan hash (a push after approval fails it).
    actual: dict[str, str | None] = dict(tree)
    for p, t in row.plan["files"].items():
        if t is None and p not in tree:
            actual[p] = None
    cmapi_ok = tree == expected and plan_hash(actual) == row.plan_hash
    findings = ctx.pipeline.validator.validate(tree, row.cluster_id, row.env)
    kc = [f for f in findings if f.source in ("kubeconform", "cmapi")]
    ky = [f for f in findings if f.source == "kyverno"]
    link = f"{ctx.cfg.raw_instance['instance'].get('publicUrl', '')}/api/v1/requests/{row.request_id}"
    ctx.git.set_check(head, CONTEXT_KUBECONFORM, "failure" if kc else "success",
                      "; ".join(f.message for f in kc)[:200] or "schema ok", link)
    ctx.git.set_check(head, CONTEXT_KYVERNO, "failure" if ky else "success",
                      "; ".join(f"{f.rule}: {f.message}" for f in ky)[:200] or "policies ok", link)
    ctx.git.set_check(head, CONTEXT_CMAPI, "success" if cmapi_ok else "failure",
                      f"request {row.request_id} approved, head == plan {row.plan_hash[:12]}" if cmapi_ok
                      else f"head differs from the approved plan {row.plan_hash[:12]}", link)
    repo.event(row, "ci", "ci", f"kubeconform: {'pass' if not kc else 'fail'}; kyverno: {'pass' if not ky else 'fail'}; "
                                f"cmapi check: {'pass' if cmapi_ok else 'fail'}",
               {"findings": [f.message for f in findings], "head": head})
    if findings or not cmapi_ok:
        if head != pr.head_sha:
            repo.event(row, "head_moved", "ci", f"PR head moved from {pr.head_sha[:8]} to {head[:8]} after approval")
        repo.move(row, E.PR_FAILED, "ci", "checks failed")
        ctx.git.close(pr, f"cmapi: checks failed for {row.request_id}; the request is failed and may be retried.")
        jobs.done(job)
        return
    merge_sha = ctx.git.merge(pr, head)
    row.merge_sha = merge_sha
    repo.move(row, E.MERGED, "cmapi-bot", f"merged {merge_sha[:8]}")
    jobs.done(job)
    jobs.enqueue("watch_sync", request_id=row.request_id, cluster_id=row.cluster_id)
