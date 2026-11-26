"""#710: a namespace rendered from an older tier catalog (tier-outdated), changed later. Its quota is sized from Git.

docs/02, "Changing a tier": a change of tiers.yaml "changes no namespace by itself"; the request that re-renders an outdated
namespace is "an ordinary update request: the plan diff shows old and new values, increases go through the capacity check
and reserve the delta, [...] and the approval rules apply as for any quota change". The old values are the ones Git holds
and the cluster enforces, so the capacity delta, quotaIncreasePct and the network exposure are taken from Git, never from
the catalog.

Before the fix the plan took the old quota of a named tier from the catalog: with Git holding requests.cpu 1 and the
catalog 8, a label change wrote 8 with a capacity delta of 0, quotaIncreasePct 0 and no approval (reviewer 2 of #707).
"""
from __future__ import annotations

import shutil

import pytest
import yaml

from cmapi.core.db.models import ChangeRequestRow
from conftest import build_world
from test_flow import NS, OLA, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces"
NAME = NS["namespace"]
ONE = f"{URL}/{NAME}"
BASE = f"clusters/CRC/namespaces/{NAME}/"
OWN = f"{NAME}-quota"
QUOTA_FILE = BASE + f"resourcequota-{OWN}.yaml"
LABEL = {"labels": {"cmapi.net/cost-center": "cc-9000"}}
# The nonprod catalog's tier small (examples/instances/nonprod/tiers.yaml), the tier NS is created on.
SMALL = {"requests.cpu": "8", "requests.memory": "16Gi", "pods": "50"}


def created(world) -> None:
    """payments-dev on tier small, created, merged and synced: auto-approved in dev."""
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    assert client.get(f"/api/v1/requests/{r.json()['requestId']}", headers=auth(keys, "ola", **OLA)).json()["status"] == "synced"


def rendered_by_an_older_catalog(world, hard: dict[str, str]) -> dict:
    """Git and the cluster hold <ns>-quota as an older catalog rendered it: these sizable values and another tier hash."""
    client, ctx, git, kube, validator, keys = world
    main = git.branches["main"]
    rq = yaml.safe_load(main[QUOTA_FILE])
    assert rq["spec"]["hard"]["requests.cpu"] == SMALL["requests.cpu"], "the test starts from the current catalog"
    rq["spec"]["hard"].update(hard)
    rq["metadata"]["annotations"]["cmapi.net/tier-hash"] = "0123456789ab"
    main[QUOTA_FILE] = yaml.safe_dump(rq, sort_keys=False)
    git._sha("main")
    kube.apply(rq)
    return rq


def without_tier_label(world) -> None:
    """Git's Namespace names no tier, as a folder written by hand does: a change renders it on tier small."""
    client, ctx, git, kube, validator, keys = world
    main = git.branches["main"]
    namespace = yaml.safe_load(main[BASE + "namespace.yaml"])
    assert namespace["metadata"]["labels"].pop("cmapi.net/tier") == "small"
    main[BASE + "namespace.yaml"] = yaml.safe_dump(namespace, sort_keys=False)
    git._sha("main")


def patch(world, body: dict, *, dry_run: bool):
    client, ctx, git, kube, validator, keys = world
    tag = client.get(ONE, headers=auth(keys, "ola", **OLA))
    assert tag.status_code == 200, tag.text
    return client.patch(ONE + ("?dryRun=true" if dry_run else ""), json=body,
                        headers={**auth(keys, "ola", **OLA), "If-Match": tag.json()["etag"]})


def stored_facts(world, request_id: str) -> dict:
    client, ctx, git, kube, validator, keys = world
    with ctx.db.session() as s:
        return dict(s.get(ChangeRequestRow, request_id).plan["facts"])


def capacity_deltas(world, monkeypatch) -> list[tuple[float, float]]:
    """The (cpu, memory) deltas that each plan hands the capacity check, in cores and bytes. Submit checks the plan's hold again
    under the cluster's lock (`reserve_check`, #62): that check is not a plan's, so it is not recorded."""
    client, ctx, git, kube, validator, keys = world
    capacity = ctx.pipeline.capacity
    asked, check, recheck, in_submit = [], capacity.check, capacity.reserve_check, []

    def recording(cluster_id, environment, cpu_delta, memory_delta, **kw):
        if not in_submit:
            asked.append((cpu_delta, memory_delta))
        return check(cluster_id, environment, cpu_delta, memory_delta, **kw)

    def rechecking(*args, **kw):
        in_submit.append(True)
        try:
            return recheck(*args, **kw)
        finally:
            in_submit.pop()
    monkeypatch.setattr(capacity, "check", recording)
    monkeypatch.setattr(capacity, "reserve_check", rechecking)
    return asked


def planned_hard(body: dict) -> dict[str, str]:
    return yaml.safe_load(body["files"][QUOTA_FILE])["spec"]["hard"]


def test_a_label_change_that_rerenders_a_raise_is_sized_and_approved_as_a_raise(world, monkeypatch):
    """Reviewer 2's probe of #707: Git holds requests.cpu 1, the catalog 8. The label change re-renders the tier, so the plan
    raises the quota by 7 CPUs: the capacity check counts them, and quotaIncreasePct (700) adds approver-platform."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    rendered_by_an_older_catalog(world, {"requests.cpu": "1"})
    asked = capacity_deltas(world, monkeypatch)
    plan = patch(world, LABEL, dry_run=True)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert planned_hard(body)["requests.cpu"] == "8"
    assert asked == [(7.0, 0.0)], "the raise from Git's 1 CPU to 8 is checked against the cluster"
    assert [(s["group"], s["count"]) for s in body["approval"]["slots"]] == [("approver-platform", 1)], body["approval"]
    assert any("quotaIncreasePct > 100" in reason for reason in body["approval"]["reasons"]), body["approval"]
    assert body["approval"]["auto"] is None

    r = patch(world, LABEL, dry_run=False)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending_approval", r.json()
    facts = stored_facts(world, r.json()["requestId"])
    assert facts["quotaIncreasePct"] == 700.0 and facts["tierChange"] == "same", facts


def test_a_tier_move_from_an_outdated_quota_is_sized_from_git(world, monkeypatch):
    """A move small -> medium (16 CPUs) of a namespace whose Git quota is 1 CPU: the raise is 15 CPUs (1500%), not the
    catalog's 8 to 16 (100%, under the threshold of approval-rules.yaml)."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    rendered_by_an_older_catalog(world, {"requests.cpu": "1"})
    asked = capacity_deltas(world, monkeypatch)
    r = patch(world, {"tier": "medium"}, dry_run=False)
    assert r.status_code == 202, r.text
    assert asked[-1] == (15.0, float(16 * 2**30)), asked
    assert r.json()["status"] == "pending_approval", r.json()
    facts = stored_facts(world, r.json()["requestId"])
    assert facts["quotaIncreasePct"] == 1500.0 and facts["tierChange"] == "up", facts


def test_a_label_change_that_rerenders_a_decrease_is_sized_as_a_decrease(world, monkeypatch):
    """Git holds twice the catalog on every sizable key. The label change lowers them to the tier: nothing is reserved, no
    raise approval is added, and quotaIncreasePct says -50, where the catalog said 0."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    rendered_by_an_older_catalog(world, {"requests.cpu": "16", "requests.memory": "32Gi", "pods": "100"})
    asked = capacity_deltas(world, monkeypatch)
    plan = patch(world, LABEL, dry_run=True)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert {k: planned_hard(body)[k] for k in SMALL} == SMALL
    assert asked == [(0.0, 0.0)], "a decrease reserves nothing"
    assert body["approval"]["slots"] == [] and body["approval"]["auto"] == "none-required", body["approval"]

    r = patch(world, LABEL, dry_run=False)
    assert r.status_code == 202, r.text
    facts = stored_facts(world, r.json()["requestId"])
    assert facts["quotaIncreasePct"] == -50.0 and facts["tierChange"] == "same", facts
    run_jobs(ctx)
    assert kube.objects[("ResourceQuota", NAME, OWN)]["spec"]["hard"]["requests.cpu"] == "8"


def test_a_label_change_with_no_drift_is_unchanged(world, monkeypatch):
    """A guard, which passes before and after: Git holds what the catalog renders, so the label change writes namespace.yaml
    alone, reserves nothing and is auto-approved as before."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    asked = capacity_deltas(world, monkeypatch)
    plan = patch(world, LABEL, dry_run=True)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["changes"] == {BASE + "namespace.yaml": "changed"}, body["changes"]
    assert asked == [(0.0, 0.0)]
    assert body["approval"]["slots"] == [] and body["approval"]["auto"] == "none-required", body["approval"]
    r = patch(world, LABEL, dry_run=False)
    assert r.status_code == 202, r.text
    facts = stored_facts(world, r.json()["requestId"])
    assert facts["quotaIncreasePct"] == 0.0 and facts["tierChange"] == "same" and not facts["networkExposure"], facts


def test_a_namespace_that_names_no_tier_is_sized_from_git_too(world, monkeypatch):
    """Git's Namespace has no cmapi.net/tier and its quota holds 1 CPU. A label change renders tier small: the raise of 7 CPUs
    is quotaIncreasePct 700, where before the plan had no quotaIncreasePct at all and the change was auto-approved."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    rendered_by_an_older_catalog(world, {"requests.cpu": "1"})
    without_tier_label(world)
    asked = capacity_deltas(world, monkeypatch)
    r = patch(world, LABEL, dry_run=False)
    assert r.status_code == 202, r.text
    assert asked == [(7.0, 0.0)], asked
    assert r.json()["status"] == "pending_approval", r.json()
    facts = stored_facts(world, r.json()["requestId"])
    assert facts["quotaIncreasePct"] == 700.0 and facts["tierChange"] == "same", facts


def test_a_quota_that_git_does_not_hold_is_written_from_nothing(world, monkeypatch):
    """Decision 3. Git's Namespace names tier small, and neither its folder nor the cluster holds <ns>-quota. The label change
    renders the tier's quota: the capacity check counts all of it, and quotaIncreasePct is 100, as compare gives a key with
    no old value. Before the fix the check counted nothing (the catalog was the baseline), and the fallback `old_hard or
    hard` made the percentage 0."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    del git.branches["main"][QUOTA_FILE]
    git._sha("main")
    kube.delete("ResourceQuota", NAME, OWN)
    asked = capacity_deltas(world, monkeypatch)
    r = patch(world, LABEL, dry_run=False)
    assert r.status_code == 202, r.text
    assert asked == [(8.0, float(16 * 2**30))], asked
    facts = stored_facts(world, r.json()["requestId"])
    assert facts["quotaIncreasePct"] == 100.0 and facts["tierChange"] == "same", facts


@pytest.mark.parametrize("names_tier", [True, False])
def test_network_exposure_is_counted_from_what_git_holds(test_config, tmp_path, fresh_db, keys, monkeypatch, names_tier):
    """The catalog now gives tier small one load balancer; Git holds 0, from the older catalog. A label change renders the
    one load balancer, which opens network exposure (approval-rules.yaml, networkExposure). With a tier label the plan
    already compared with Git; without one it compared with the catalog and saw no raise."""
    config = tmp_path / "config"
    shutil.copytree(test_config, config)
    tiers = yaml.safe_load((config / "tiers.yaml").read_text())
    tiers["tiers"]["small"]["quota"]["services.loadbalancers"] = "1"
    (config / "tiers.yaml").write_text(yaml.safe_dump(tiers, sort_keys=False))
    with build_world(config, keys, monkeypatch) as world:
        created(world)
        rendered_by_an_older_catalog(world, {"services.loadbalancers": "0"})
        if not names_tier:
            without_tier_label(world)
        plan = patch(world, LABEL, dry_run=True)
        assert plan.status_code == 200, plan.text
        body = plan.json()
        assert planned_hard(body)["services.loadbalancers"] == "1"
        assert any("networkExposure" in reason for reason in body["approval"]["reasons"]), body["approval"]
        assert body["approval"]["auto"] is None
