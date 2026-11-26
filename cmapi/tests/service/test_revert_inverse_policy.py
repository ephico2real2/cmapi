"""A revert is judged as the request it is (separate issue, found reviewing PR #718): the revert of a delete writes the
namespace back, a create; the revert of a create deletes it, judged as any delete; and the rules read its target's team, tier
and cluster labels.

docs/01, the state reverted: "the revert is a new request through the same approval rules". Before the fix the revert of a
delete was a change (dev change: 0, plus a sensitive-key approval for the first cmapi.net/team of the folder); the revert of a
create was a delete of a namespace never protected and 0 days old; and the facts held the original request's team, no tier
and no cluster labels.
"""
from __future__ import annotations

import yaml
from sqlalchemy import text

from cmapi.core.db.models import ChangeRequestRow
from cmapi.worker import Worker
from test_catalog_drift_710 import BASE, ONE, created, patch
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
