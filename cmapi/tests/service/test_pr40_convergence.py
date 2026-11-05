"""What the convergence of the two PR #40 reviews decided, each decision with the test that fails before it
(docs/reviews/2026-11-05-pr40.md): the prune read outage (Codex X5), the lease fencing token (Codex X2),
the schema-aware readiness with migrations as initContainers, the confidential automation client (Opus Y5),
the private submitter identifier, and the removed cmapi-capacity entry point."""
from __future__ import annotations

import re

import pytest
from sqlalchemy import func, select, text

from cmapi.core.clients.kube import ClusterUnreachable
from cmapi.core.db import Database, REQUIRED_REVISION, older_than_required
from cmapi.core.db.models import JobRow, RequestEventRow
from cmapi.core.db.repo import JobRepo, LeaseLost, RequestRepo
from cmapi.core.identity.claims import Person
from cmapi.core.identity.directory import CachedDirectory, InMemoryDirectory
from cmapi.jobs import HANDLERS
from cmapi.worker import Worker
from test_flow import NS, OLA, auth, run_jobs
from test_review_d_delivery import status
from test_review_e_recovery import lease_expired
from test_review_i_crosscheck import ROOT, rendered


def test_prune_read_outage_does_not_exhaust_the_only_job(world):
    """Codex X5: six failed reads in a row leave the request awaiting_prune with its job still pending."""
    client, ctx, _git, kube, _validator, keys = world
    ctx.delivery = type(ctx.delivery)(mode="argocd")
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    kube.apply({"kind": "Namespace", "metadata": {"name": "payments-dev", "labels": {"cmapi.net/managed": "true"}}})
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='awaiting_prune', action='delete'"))
        rid = s.execute(text("select request_id from change_requests")).scalar()
        JobRepo(s).enqueue("prune", request_id=rid, cluster_id="CRC")
        s.execute(text("delete from jobs where kind='open_pr'"))
    real = kube.get_object
    kube.get_object = lambda *_a, **_k: (_ for _ in ()).throw(ClusterUnreachable("the API server is down"))
    try:
        worker = Worker(ctx, "w")
        for _ in range(6):
            lease_expired(ctx)
            worker.run_one()
        with ctx.db.session() as s:
            pending = s.scalar(select(func.count()).select_from(JobRow).where(JobRow.kind == "prune", JobRow.done_at.is_(None)))
            attempts = s.scalar(select(JobRow.attempts).where(JobRow.kind == "prune"))
        assert status(client, keys, rid)["status"] == "awaiting_prune"
        assert pending == 1 and attempts == 0, (pending, attempts)
    finally:
        kube.get_object = real
    # the cluster is back: the same job confirms the prune once the namespace is gone
    kube.delete("Namespace", None, "payments-dev")
    lease_expired(ctx)
    worker.run_one()
    assert status(client, keys, rid)["status"] == "synced"


def test_a_stale_worker_cannot_commit_after_its_lease_was_claimed_again(world):
    """Codex X2: the lease has a fencing token. A worker paused past its lease comes back to find the job claimed
    by another; its whole transaction, request events included, rolls back instead of landing on top."""
    client, ctx, _git, _kube, _validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    events: list[str] = []

    def slow_handler(c, s, job):
        RequestRepo(s).event(RequestRepo(s).get(rid), "stale_write", "worker-a", "written by the paused worker")
        lease_expired(ctx)                                  # the pause: worker A's lease ran out...
        with ctx.db.session() as other:                     # ...and worker B claimed the job meanwhile
            claimed = JobRepo(other).claim("worker-b")
            events.append(f"b-claimed:{claimed.job_id if claimed else None}")
        JobRepo(s).done(job)

    HANDLERS["fence_probe"] = slow_handler
    try:
        with ctx.db.session() as s:
            s.execute(text("delete from jobs"))
            job = JobRepo(s).enqueue("fence_probe", request_id=rid, cluster_id="CRC")
            job_id = job.job_id
        assert Worker(ctx, "worker-a").run_one() is True
        assert events and events[0] == f"b-claimed:{job_id}"
        with ctx.db.session() as s:
            row = s.get(JobRow, job_id)
            assert row.done_at is None and row.locked_by == "worker-b" and row.lease_generation == 2, \
                (row.done_at, row.locked_by, row.lease_generation)
            assert s.scalar(select(func.count()).select_from(RequestEventRow)
                            .where(RequestEventRow.request_id == rid, RequestEventRow.event == "stale_write")) == 0
    finally:
        HANDLERS.pop("fence_probe", None)


def test_assert_lease_refuses_a_superseded_generation(world):
    client, ctx, *_rest, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    with ctx.db.session() as s:
        s.execute(text("delete from jobs"))
        JobRepo(s).enqueue("open_pr", request_id=rid, cluster_id="CRC")
    with ctx.db.session() as s:
        a = JobRepo(s).claim("a")
        assert a.lease_generation == 1
        JobRepo(s).assert_lease(a.job_id, "a", 1)               # still mine
    lease_expired(ctx)
    with ctx.db.session() as s:
        b = JobRepo(s).claim("b")
        assert b.lease_generation == 2
    with ctx.db.session() as s:
        with pytest.raises(LeaseLost):
            JobRepo(s).assert_lease(b.job_id, "a", 1)


def test_readiness_waits_for_the_schema_and_tolerates_a_newer_one(world, monkeypatch):
    client, ctx, *_ = world
    assert client.get("/readyz").json() == {"status": "ok", "database": "ok", "schema": "ok"}
    monkeypatch.setattr(ctx.db, "schema_version", lambda: None)
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json()["schema"] == "not-migrated"
    monkeypatch.setattr(ctx.db, "schema_version", lambda: "0001")
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json()["schema"].startswith("behind: at 0001")
    monkeypatch.setattr(ctx.db, "schema_version", lambda: "9999_from_a_later_release")   # ahead: expand-only, so ready
    assert client.get("/readyz").status_code == 200
    monkeypatch.setattr(ctx.db, "schema_version", lambda: REQUIRED_REVISION)
    assert client.get("/readyz").status_code == 200


def test_required_revision_is_the_newest_migration():
    versions = sorted(p.name[:4] for p in (ROOT / "cmapi/src/cmapi/core/db/migrations/versions").glob("*.py"))
    assert versions[-1] == REQUIRED_REVISION
    assert older_than_required("0001") and older_than_required("0002") and not older_than_required(REQUIRED_REVISION)


def test_migrations_run_as_init_containers_and_no_hook_job():
    docs = rendered()
    assert not [d for d in docs if d["kind"] == "Job" and d["metadata"]["name"].endswith("-migrate")]
    for name in ("cmapi-api", "cmapi-worker"):
        dep = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == name)
        init = dep["spec"]["template"]["spec"]["initContainers"]
        assert [c["name"] for c in init] == ["migrate"] and init[0]["command"] == ["cmapi-migrate", "head"]
        assert init[0]["resources"]["limits"] and "@sha256:" in init[0]["image"]


def test_automation_client_is_confidential_and_the_cli_is_not_a_password_client():
    realm = next(d for d in rendered() if d["kind"] == "KeycloakRealmImport")["spec"]
    clients = {c["clientId"]: c for c in realm["realm"]["clients"]}
    assert clients["cmapi-automation"]["publicClient"] is False
    assert clients["cmapi-automation"]["secret"] == "${CMAPI_AUTOMATION_SECRET}"
    assert "CMAPI_AUTOMATION_SECRET" in realm["placeholders"]
    assert clients["cmapi-cli"]["directAccessGrantsEnabled"] is False
    secrets = {d["metadata"]["name"]: d for d in rendered() if d["kind"] == "Secret"}
    assert "CMAPI_AUTOMATION_SECRET" in secrets["cmapi-realm-secrets"]["data"]
    assert "automationClientSecret" in secrets["cmapi-keycloak"]["data"]


def test_the_submitter_sub_is_stored_but_never_served(world):
    """The ledger needs a stable identifier of whoever filed a request for someone else (self-approval through
    onBehalfOf); the public contract carries the username only."""
    client, ctx, *_rest, keys = world
    ctx.pipeline.directory = CachedDirectory(InMemoryDirectory([Person(username="ola", email="ola@ephico2real.com", sub="sub-ola")]))
    svc = dict(roles=["cmapi-requester"], client="svc-payments-ci", employee_id=None)
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "onBehalfOf": "ola"},
                    headers=auth(keys, "service-account-svc-payments-ci", **svc))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["requester"]["submittedByClient"] == "svc-payments-ci" and "submittedBySub" not in body["requester"]
    with ctx.db.session() as s:
        row = RequestRepo(s).get(body["requestId"])
        assert row.requester["submittedBySub"] == "sub-service-account-svc-payments-ci"
    spec = client.get("/openapi.json").json()
    assert "submittedBySub" not in str(spec["components"]["schemas"]["RequesterView"])


def test_no_console_script_points_at_code_that_does_not_exist():
    text_ = (ROOT / "cmapi/pyproject.toml").read_text()
    for name, target in re.findall(r'^(cmapi-[a-z-]+) = "([\w.]+):run"$', text_, re.M):
        module = target.replace(".", "/")
        base = ROOT / "cmapi/src" / module
        assert base.with_suffix(".py").exists() or (base / "__init__.py").exists(), f"{name} -> {target}"
    assert "cmapi-capacity" not in text_
