"""A revert is judged as the request it is (separate issue, found reviewing PR #718): the revert of a delete writes the
namespace back, a create; the revert of a create deletes it, judged as any delete; and the rules read its target's team, tier
and cluster labels.

docs/01, the state reverted: "the revert is a new request through the same approval rules". Before the fix the revert of a
delete was a change (dev change: 0, plus a sensitive-key approval for the first cmapi.net/team of the folder); the revert of a
create was a delete of a namespace never protected and 0 days old; and the facts held the original request's team, no tier
and no cluster labels.
"""
from __future__ import annotations

from datetime import timedelta

import yaml
from sqlalchemy import text

from cmapi.core.db.models import ChangeRequestRow
from cmapi.core.pipeline import utc_today
from cmapi.core.ports import Finding
from cmapi.worker import Worker
from test_catalog_drift_710 import BASE, LABEL, ONE, URL, created, patch
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs


def view(world, rid):
    client, ctx, git, kube, validator, keys = world
    return client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "opal", **OPAL)).json()


def facts_of(world, rid) -> dict:
    client, ctx, git, kube, validator, keys = world
    with ctx.db.session() as s:
        return dict(s.get(ChangeRequestRow, rid).plan["facts"])


def revert_once(world, rid) -> str | None:
    client, ctx, git, kube, validator, keys = world
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed' where request_id=:r"), {"r": rid})
    assert client.post(f"/api/v1/requests/{rid}:revert", headers=auth(keys, "opal", **OPAL)).status_code == 200
    assert Worker(ctx, "w").run_one()
    opened = [e["note"] for e in view(world, rid)["events"] if e["event"] == "revert_opened"]
    return opened[0] if opened else None


def test_the_revert_of_a_delete_is_judged_as_a_create(world):
    """payments-dev on tier small in dev: a create there is auto-approved by baseline-rnd-namespace (approval-rules.yaml)."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    tag = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]
    gone = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": tag}).json()["requestId"]
    assert client.post(f"/api/v1/requests/{gone}:approve", json={}, headers=auth(keys, "amy", **AMY)).status_code == 200
    run_jobs(ctx)
    child = revert_once(world, gone)
    v, facts = view(world, child), facts_of(world, child)
    assert v["action"] == "create" and v["approval"]["rule"] == "dev-create", v["approval"]
    assert facts["sensitiveKeyChanged"] is False and facts["networkExposure"] is False, facts
    assert (facts["tier"], facts["clusterLabels"]) == ("small", {"region": "us-central"}), facts
    assert v["approval"]["auto"] == "auto:baseline-rnd-namespace", v["approval"]


def test_the_revert_of_a_create_of_a_protected_namespace_is_refused(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    run_jobs(ctx)
    main = git.branches["main"]
    ns = yaml.safe_load(main[BASE + "namespace.yaml"])
    ns["metadata"]["labels"]["cmapi.net/protected"] = "true"
    main[BASE + "namespace.yaml"] = yaml.safe_dump(ns, sort_keys=False)
    git._sha("main")
    assert revert_once(world, rid) is None
    after = view(world, rid)
    assert after["status"] == "sync_failed"
    assert any(e["event"] == "error" and "Protected namespaces cannot be deleted" in e["note"] for e in after["events"])


def test_the_revert_of_a_create_counts_the_namespace_age(world):
    """The namespace was on the cluster before the create's folder (an old namespace): a delete of one over 90 days old adds
    an approval (approval-rules.yaml), 1 for dev's delete and 1 more."""
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    run_jobs(ctx)
    kube.objects[("Namespace", "", NS["namespace"])]["metadata"]["creationTimestamp"] = "2020-01-01T00:00:00Z"
    ctx.registry.cache("CRC")._list("Namespace")
    child = revert_once(world, rid)
    assert facts_of(world, child)["namespaceAgeDays"] > 90
    assert sum(s["count"] for s in view(world, child)["approval"]["slots"]) == 2, view(world, child)["approval"]


def test_the_rules_read_the_restored_tier_and_the_cluster_labels(world):
    client, ctx, git, kube, validator, keys = world
    created(world)
    up = patch(world, {"tier": "large"}, dry_run=False).json()["requestId"]
    assert client.post(f"/api/v1/requests/{up}:approve", json={}, headers=auth(keys, "amy", **AMY)).status_code == 200
    run_jobs(ctx)
    low = patch(world, {"tier": "small"}, dry_run=False).json()["requestId"]
    run_jobs(ctx)
    facts = facts_of(world, revert_once(world, low))
    assert (facts["tier"], facts["team"], facts["clusterLabels"]) == ("large", "payments", {"region": "us-central"}), facts


def deleted(world, before=None) -> str:
    """payments-dev created, then deleted and synced; `before` edits Git first, as the folder the delete removes."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    if before:
        before(world)
    tag = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]
    gone = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": tag}).json()["requestId"]
    assert client.post(f"/api/v1/requests/{gone}:approve", json={}, headers=auth(keys, "amy", **AMY)).status_code == 200
    run_jobs(ctx)
    return gone


def dated(expires_at: str):
    """Git's Namespace carries this expiry, as an approved create with expiresAt writes it."""
    def edit(world):
        client, ctx, git, kube, validator, keys = world
        main = git.branches["main"]
        ns = yaml.safe_load(main[BASE + "namespace.yaml"])
        ns["metadata"]["annotations"]["cmapi.net/expires-at"] = expires_at
        ns["metadata"]["labels"]["cmapi.net/expiry"] = "managed"
        main[BASE + "namespace.yaml"] = yaml.safe_dump(ns, sort_keys=False)
        git._sha("main")
    return edit


def test_a_restored_create_carries_no_quota_change(world):
    """A planned create has no tierChange or quotaIncreasePct (Pipeline._plan_namespace); the restore judged as one neither."""
    gone = deleted(world)
    facts = facts_of(world, revert_once(world, gone))
    assert "tierChange" not in facts and "quotaIncreasePct" not in facts, facts


def test_a_restored_create_with_a_warning_goes_to_the_approvers(world):
    """docs/01, auto-approval: a matching request still goes to humans "when the plan has warnings". The planned create of the
    same folder gets 1 approver-platform and no auto-approval; so does its restore, and the finding is on the request."""
    client, ctx, git, kube, validator, keys = world
    gone = deleted(world)
    validator.findings = [Finding("kyverno", "audit-rule", BASE + "namespace.yaml", "audit finding", "warning")]
    forward = client.post(URL + "?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA)).json()["approval"]
    assert forward["auto"] is None and [s["count"] for s in forward["slots"]] == [1], forward
    child = revert_once(world, gone)
    v = view(world, child)
    assert v["action"] == "create" and v["approval"]["auto"] is None, v["approval"]
    assert [(s["group"], s["count"]) for s in v["approval"]["slots"]] == [("approver-platform", 1)], v["approval"]
    assert facts_of(world, child)["warnings"] == ["audit finding"]
    with ctx.db.session() as s:
        assert [f["message"] for f in s.get(ChangeRequestRow, child).plan["findings"]] == ["audit finding"]


def test_a_restored_create_past_the_lifetime_adds_approver_platform(world):
    """docs/01, Namespace expiration: going past the limits adds approver-platform. The planned create with a date 200 days out
    gets 2 (dev create 1, expirationBeyondLimits 1); the restore of the same Namespace gets them too, not an auto-approval."""
    client, ctx, git, kube, validator, keys = world
    expires = (utc_today() + timedelta(days=200)).isoformat()
    gone = deleted(world, dated(expires))
    forward = client.post(URL + "?dryRun=true", json={**NS, "expiresAt": expires}, headers=auth(keys, "ola", **OLA)).json()
    child = revert_once(world, gone)
    v = view(world, child)
    assert v["approval"]["auto"] is None and v["approval"]["slots"] == forward["approval"]["slots"], v["approval"]
    assert sum(s["count"] for s in v["approval"]["slots"]) == 2
    facts = facts_of(world, child)
    assert (facts["expirationAction"], facts["expirationBeyondLimits"]) == ("create", True), facts


def test_the_revert_of_the_delete_of_an_expired_namespace_still_opens(world):
    """A date in the past is refused at create (expiration-in-past), never at a restore: the date is the one Git held."""
    gone = deleted(world, dated((utc_today() - timedelta(days=10)).isoformat()))
    child = revert_once(world, gone)
    assert child is not None
    facts = facts_of(world, child)
    assert (facts["expirationAction"], facts["expirationBeyondLimits"]) == ("create", False), facts


def test_a_restored_lifetime_counts_from_the_namespace_on_the_cluster(world):
    """docs/01, Namespace expiration: "180 days from creation". The delete did not sync, so the namespace is still on the
    cluster, created in 2020: a date 30 days out is past its lifetime, as a change of that namespace counts it."""
    client, ctx, git, kube, validator, keys = world
    gone = deleted(world, dated((utc_today() + timedelta(days=30)).isoformat()))
    kube.objects[("Namespace", "", NS["namespace"])] = {
        "apiVersion": "v1", "kind": "Namespace",
        "metadata": {"name": NS["namespace"], "creationTimestamp": "2020-01-01T00:00:00Z"}}
    ctx.registry.cache("CRC")._list("Namespace")
    facts = facts_of(world, revert_once(world, gone))
    assert facts["expirationBeyondLimits"] is True, facts


def test_the_revert_of_a_change_reads_the_restored_team_and_no_delete_facts(world):
    """The team is the restored Namespace's, not the reverted request's; a change carries no delete facts (protected, age)."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    low = patch(world, LABEL, dry_run=False).json()["requestId"]
    run_jobs(ctx)
    with ctx.db.session() as s:
        s.execute(text("update change_requests set team='former-owner' where request_id=:r"), {"r": low})
    facts = facts_of(world, revert_once(world, low))
    assert (facts["action"], facts["team"]) == ("update", "payments"), facts
    assert not {"protected", "namespaceAgeDays", "pods", "pvcs"} & facts.keys(), facts
