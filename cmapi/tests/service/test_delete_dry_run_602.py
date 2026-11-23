"""#602: `DELETE .../namespaces/{ns}?dryRun=true` is a dry run, as on every other write.

Before the fix the route declared no `dryRun`, FastAPI ignored the parameter, and the call opened a real delete request
(202, a row). Now it answers 200 with the delete's plan and opens no request: no row, no audit, no Git. It runs the real
delete's planning checks, so it fails where they would (Kubernetes' dry run on DELETE; Google AIP-163). Like every dry run it
skips the Idempotency-Key and the namespace's lock (docs/01, "skips the idempotency and lock steps").
"""
from __future__ import annotations

import copy

from sqlalchemy import text

from test_flow import NS, OLA, OPAL, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces"
ONE = f"{URL}/payments-dev"
FILES = {f"clusters/CRC/namespaces/payments-dev/{f}" for f in
         ("namespace.yaml", "resourcequota-payments-dev-quota.yaml", "limitrange-payments-dev-limits-cpu.yaml",
          "limitrange-payments-dev-limits-memory.yaml", "token-issuer-rolebinding.yaml")}


def bearer(keys, user="ola", who=OLA) -> dict[str, str]:
    """A token and no Idempotency-Key: a dry run needs none."""
    return {"Authorization": f"Bearer {keys.token(user, **who)}"}


def created(world, labels=None) -> str:
    """payments-dev, created (approved at once by baseline-rnd-namespace) and synced; its etag."""
    client, ctx, *_, keys = world
    by = ("opal", OPAL) if labels else ("ola", OLA)
    r = client.post(URL, json={**NS, "labels": {**NS["labels"], **(labels or {})}}, headers=auth(keys, by[0], **by[1]))
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)
    return client.get(ONE, headers=bearer(keys)).json()["etag"]


def git_state(git) -> tuple:
    return copy.deepcopy((git.branches, git.heads, git.prs, git.commits, git.pushes, git.statuses))


def rows(ctx) -> dict[str, int]:
    with ctx.db.session() as s:
        return {t: s.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
                for t in ("change_requests", "request_events", "approvals", "audit_events", "jobs", "policy_rejections")}


def test_a_delete_dry_run_answers_the_plan_and_writes_nothing(world):
    client, ctx, git, kube, validator, keys = world
    etag = created(world)
    before_git, before_rows = git_state(git), rows(ctx)
    # With an Idempotency-Key, as reviewer 2's probe sent it on #599: before the fix this was 202 and a delete row.
    headers = {**auth(keys, "ola", **OLA), "If-Match": f'"{etag}"'}

    r = client.delete(f"{ONE}?dryRun=true", headers=headers)

    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["changes"] == {p: "removed" for p in FILES}
    assert plan["files"] == {} and plan["etag"] == etag
    assert plan["approval"]["auto"] is None and plan["approval"]["slots"], plan["approval"]        # dev: a delete needs an approver
    assert plan["metadata"] is None and plan["metadataDiff"] is None
    assert "requestId" not in plan
    assert rows(ctx) == before_rows, "a dry run opened a request, an event, an audit row or a job"
    assert git_state(git) == before_git, "a dry run wrote to Git"
    assert client.get(ONE, headers=bearer(keys)).json()["openRequest"] is None

    # The namespace is still free and the key was not taken: the same call without dryRun opens the one request.
    real = client.delete(ONE, headers=headers)
    assert real.status_code == 202 and real.json()["action"] == "delete", real.text
    assert rows(ctx)["change_requests"] == before_rows["change_requests"] + 1


def test_a_delete_dry_run_fails_where_the_delete_would(world):
    """AIP-163: "a request using validate_only must fail if it determines that the actual request would fail"."""
    client, ctx, git, kube, validator, keys = world
    etag = created(world)
    before = rows(ctx)
    cases = [({}, 428, "precondition-required"),
             ({"If-Match": "*"}, 428, "precondition-required"),
             ({"If-Match": '"0000000000000000"'}, 412, "precondition-failed")]
    for extra, status, code in cases:
        r = client.delete(f"{ONE}?dryRun=true", headers={**bearer(keys), **extra})
        assert (r.status_code, r.json()["code"]) == (status, code), (extra, r.text)
    missing = client.delete(f"{URL}/not-there-dev?dryRun=true", headers={**bearer(keys), "If-Match": f'"{etag}"'})
    assert (missing.status_code, missing.json()["code"]) == (404, "object-not-found"), missing.text
    # The namespace is looked up before If-Match is read, as on the delete: an unknown one is 404, not 428 (GLOSSARY, 428).
    missing = client.delete(f"{URL}/not-there-dev?dryRun=true", headers=bearer(keys))
    assert (missing.status_code, missing.json()["code"]) == (404, "object-not-found"), missing.text
    approver = client.delete(f"{ONE}?dryRun=true", headers={**bearer(keys, "amy", {"roles": ["cmapi-approver"]}),
                                                             "If-Match": f'"{etag}"'})
    assert approver.status_code == 403, approver.text          # the same permission as the delete: namespaces:write
    assert rows(ctx) == before


def test_a_delete_dry_run_of_a_protected_namespace_is_refused(world):
    client, ctx, git, kube, validator, keys = world
    etag = created(world, {"cmapi.net/protected": "true"})
    before = rows(ctx)
    r = client.delete(f"{ONE}?dryRun=true", headers={**bearer(keys), "If-Match": f'"{etag}"'})
    assert (r.status_code, r.json()["code"]) == (422, "namespace-protected"), r.text
    assert rows(ctx) == before


def test_a_delete_dry_run_needs_no_idempotency_key_and_the_delete_still_does(world):
    client, ctx, git, kube, validator, keys = world
    etag = created(world)
    assert client.delete(f"{ONE}?dryRun=true", headers={**bearer(keys), "If-Match": f'"{etag}"'}).status_code == 200
    r = client.delete(ONE, headers={**bearer(keys), "If-Match": f'"{etag}"'})
    assert (r.status_code, r.json()["code"]) == (400, "idempotency-key-required"), r.text
    r = client.delete(f"{ONE}?dryRun=false", headers={**bearer(keys), "If-Match": f'"{etag}"'})
    assert (r.status_code, r.json()["code"]) == (400, "idempotency-key-required"), r.text


def test_the_document_declares_the_delete_dry_run(world):
    client, *_ = world
    op = client.get("/openapi.json").json()["paths"]["/api/v1/clusters/{cluster_id}/namespaces/{ns}"]["delete"]
    dry = next(p for p in op["parameters"] if p["name"] == "dryRun")
    assert dry["in"] == "query" and dry.get("required") is not True and dry["schema"]["type"] == "boolean"
    assert op["responses"]["200"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/PlanView"}
    assert "202" in op["responses"]
    key = next(p for p in op["parameters"] if p["name"] == "Idempotency-Key")["description"]
    assert "except with `dryRun=true`" in key, key


def test_a_delete_dry_run_skips_the_lock_as_every_dry_run_does(world):
    """docs/01: a dry run "skips the idempotency and lock steps". While a request holds the namespace, the preview still
    answers the plan, and the delete itself is 409 `change-pending`, naming the holder (#607 review)."""
    client, ctx, git, kube, validator, keys = world
    etag = created(world)
    opened = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": f'"{etag}"'})
    assert opened.status_code == 202 and opened.json()["status"] == "pending_approval", opened.text
    before = rows(ctx)

    preview = client.delete(f"{ONE}?dryRun=true", headers={**bearer(keys), "If-Match": f'"{etag}"'})
    assert preview.status_code == 200 and preview.json()["changes"] == {p: "removed" for p in FILES}, preview.text
    real = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": f'"{etag}"'})
    assert (real.status_code, real.json()["code"], real.json()["requestId"]) == \
        (409, "change-pending", opened.json()["requestId"]), real.text
    assert rows(ctx) == before


def test_a_delete_dry_run_counts_a_recorded_refusal_and_stores_none(world, monkeypatch):
    """`refusals(..., dry_run=dry_run)`: a refusal of RECORDED in a dry run is counted with dry_run="true" and not stored in
    policy_rejections; the same refusal on the delete is stored. plan_delete raises none of RECORDED today, so one is injected:
    the test holds the route's wiring, which a future delete rule would rely on (#607 review)."""
    from prometheus_client import REGISTRY

    from cmapi.core.errors import Problem

    client, ctx, git, kube, validator, keys = world
    etag = created(world)

    def refused(*args, **kwargs):
        raise Problem.policy_violation("Injected planning refusal", [{"code": "injected", "detail": "a test refusal"}])

    monkeypatch.setattr(ctx.pipeline, "plan_delete", refused)

    def counted(dry: str) -> float:
        return REGISTRY.get_sample_value("cmapi_plan_refusals_total", {"code": "policy-violation", "dry_run": dry}) or 0.0

    def stored() -> int:
        with ctx.db.session() as s:
            return s.execute(text("SELECT coalesce(sum(count), 0) FROM policy_rejections")).scalar_one()

    before = (counted("true"), counted("false"), stored())
    r = client.delete(f"{ONE}?dryRun=true", headers={**bearer(keys), "If-Match": f'"{etag}"'})
    assert (r.status_code, r.json()["code"]) == (422, "policy-violation"), r.text
    assert (counted("true"), counted("false"), stored()) == (before[0] + 1, before[1], before[2])

    r = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": f'"{etag}"'})
    assert (r.status_code, r.json()["code"]) == (422, "policy-violation"), r.text
    assert (counted("true"), counted("false"), stored()) == (before[0] + 1, before[1] + 1, before[2] + 1)
