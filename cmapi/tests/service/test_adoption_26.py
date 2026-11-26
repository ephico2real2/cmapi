"""Story #26, criterion 1: an unmanaged namespace is never silently taken over, and its adoption is reviewed through GitOps.

The adoption design is docs/reviews/2026-11-14-issue-26-adoption/README.md. These tests drive the API, the pipeline and the
worker jobs with the fakes of conftest.py, on the owner's sample namespace (the design's section 5): its company labels kept
as they are, a deliberate `name` mismatch, two empty contact labels, a ResourceQuota with a scope and a value beyond the
custom bounds, and one LimitRange for CPU and another for memory.
"""
from __future__ import annotations

import copy

import pytest
import yaml
from sqlalchemy import text

from cmapi.core.ports import Finding
from test_flow import AMY, OLA, OPAL, auth, run_jobs

NS = "abc-rnd"
BASE = f"clusters/CRC/namespaces/{NS}/"
ANN = dict(roles=["cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-platform"])

# Who wrote each label, as metadata.managedFields records it: `oc label` for the opt-in label, kubectl's client-side apply
# for the rest, and OpenShift's controller for the pod-security label (the design's D3a).
LABELS = {"name": "aao-rnd", "company.net/app-environment": "rnd", "company.net/mnemonic": "abc", "company.net/lob": "amgsst",
          "company.net/cl": "1", "company.net/provisioner": "cluster-configs", "company.net/mnemonic-group-contact": "",
          "company.net/mnemonic-confluence": "", "cmapi.net/adopt": "true", "kubernetes.io/metadata.name": NS,
          "pod-security.kubernetes.io/audit": "restricted"}


def _fields(keys):
    return {"f:metadata": {"f:labels": {f"f:{k}": {} for k in keys}}}


def owner_sample(kube, *, labels=None, quota_hard=None):
    """The owner's sample, made "the old way": what the API server returns for it, server fields and all."""
    labels = dict(LABELS if labels is None else labels)
    kube.objects[("Namespace", "", NS)] = {
        "apiVersion": "v1", "kind": "Namespace",
        "metadata": {"name": NS, "uid": "uid-ns-1", "resourceVersion": "100", "creationTimestamp": "2026-01-02T03:04:05Z",
                     "labels": labels, "annotations": {"company.net/app-environment": "rnd"},
                     "managedFields": [
                         {"manager": "kubectl-client-side-apply", "operation": "Update",
                          "fieldsV1": _fields([k for k in labels if k not in ("cmapi.net/adopt", "kubernetes.io/metadata.name",
                                                                                 "pod-security.kubernetes.io/audit")])},
                         {"manager": "kubectl-label", "operation": "Update", "fieldsV1": _fields(["cmapi.net/adopt"])},
                         {"manager": "kube-apiserver", "operation": "Update", "fieldsV1": _fields(["kubernetes.io/metadata.name"])},
                         {"manager": "pod-security-admission-label-synchronization-controller", "operation": "Update",
                          "fieldsV1": _fields(["pod-security.kubernetes.io/audit"])}]},
        "spec": {"finalizers": ["kubernetes"]}, "status": {"phase": "Active"}}
    kube.objects[("ResourceQuota", NS, "abc-rnd-quota")] = {
        "metadata": {"name": "abc-rnd-quota", "namespace": NS, "uid": "uid-rq-1", "resourceVersion": "101"},
        "spec": {"hard": quota_hard or {"requests.cpu": "40", "requests.memory": "64Gi", "pods": "100"},
                 "scopes": ["NotTerminating"]},
        "status": {"hard": {"requests.cpu": "40"}, "used": {"requests.cpu": "3"}}}
    for res, (lo, hi) in {"cpu": ("100m", "2"), "memory": ("128Mi", "4Gi")}.items():
        kube.objects[("LimitRange", NS, f"abc-rnd-limits-{res}")] = {
            "metadata": {"name": f"abc-rnd-limits-{res}", "namespace": NS, "uid": f"uid-lr-{res}", "resourceVersion": "102"},
            "spec": {"limits": [{"type": "Container", "defaultRequest": {res: lo}, "max": {res: hi}}]}}


def adopt(client, keys, *, dry_run=False, who="opal", role=OPAL):
    return client.post(f"/api/v1/clusters/CRC/namespaces/{NS}:adopt" + ("?dryRun=true" if dry_run else ""),
                       json={"justification": "Bring abc-rnd under cmapi"}, headers=auth(keys, who, **role))


def request(client, keys, rid):
    return client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "opal", **OPAL)).json()


def approve_both(client, keys, rid):
    for user, role in (("amy", AMY), ("ann", ANN)):
        r = client.post(f"/api/v1/requests/{rid}:approve", json={"comment": "ok"}, headers=auth(keys, user, **role))
        assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- the plan


def test_the_dry_run_plans_the_owner_sample_as_it_is_and_writes_nothing(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    before = copy.deepcopy(kube.objects)
    r = adopt(client, keys, dry_run=True)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert set(plan["files"]) == {BASE + f for f in ("namespace.yaml", "resourcequota-abc-rnd-quota.yaml",
                                                     "limitrange-abc-rnd-limits-cpu.yaml", "limitrange-abc-rnd-limits-memory.yaml")}
    text_ns = plan["files"][BASE + "namespace.yaml"]
    ns = yaml.safe_load(text_ns)
    labels, annotations = ns["metadata"]["labels"], ns["metadata"]["annotations"]
    # Every key as it is, strings kept strings (D8, Fable's A9); cmapi.net/adopt stays (the owner's decision 6)
    for key in ("name", "company.net/app-environment", "company.net/mnemonic", "company.net/lob", "company.net/cl",
                "company.net/provisioner", "company.net/mnemonic-group-contact", "company.net/mnemonic-confluence",
                "cmapi.net/adopt"):
        assert labels[key] == LABELS[key], key
    assert "company.net/cl: '1'" in text_ns and "company.net/mnemonic-group-contact: ''" in text_ns
    assert "cmapi.net/adopt: 'true'" in text_ns
    # D4: cmapi's system keys, tier custom
    assert labels["cmapi.net/managed"] == "true" and labels["cmapi.net/tier"] == "custom" and labels["cmapi.net/env"] == "dev"
    assert labels["cmapi.net/cluster-id"] == "CRC" and labels["cmapi.net/requested-by-user"] == "opal"
    assert annotations["argocd.argoproj.io/sync-options"] == "Prune=confirm,ServerSideApply=true"
    assert annotations["company.net/app-environment"] == "rnd"
    # D3: no server field; D3a: a key that only the API server or a controller owns is left out, one kubectl wrote stays
    assert set(ns["metadata"]) == {"name", "labels", "annotations"} and "spec" not in ns and "status" not in ns
    assert "kubernetes.io/metadata.name" not in labels and "pod-security.kubernetes.io/audit" not in labels
    rq = yaml.safe_load(plan["files"][BASE + "resourcequota-abc-rnd-quota.yaml"])
    assert rq["spec"] == {"hard": {"requests.cpu": "40", "requests.memory": "64Gi", "pods": "100"}, "scopes": ["NotTerminating"]}
    assert rq["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == "Prune=confirm"
    assert "cmapi.net/tier-hash" not in rq["metadata"]["annotations"] and "status" not in rq
    for res in ("cpu", "memory"):
        lr = yaml.safe_load(plan["files"][BASE + f"limitrange-abc-rnd-limits-{res}.yaml"])
        assert lr["spec"] == kube.objects[("LimitRange", NS, f"abc-rnd-limits-{res}")]["spec"]
    codes = {f["rule"] for f in plan["findings"]}
    # The reference metadata-keys.yaml of the test instance: cmapi.net/team and team-dl are required, company.net/* undeclared
    assert {"missing-required-key", "unknown-key", "skipped-key", "scoped-only"} <= codes, codes
    assert {o["kind"] for o in plan["adoption"]["objects"]} == {"Namespace", "ResourceQuota", "LimitRange"}
    assert {(k["key"], k["kept"]) for k in plan["adoption"]["keys"]} == {
        ("kubernetes.io/metadata.name", False), ("pod-security.kubernetes.io/audit", False)}
    # D10: never automatic, one approver of approver-platform and one more for the findings
    assert plan["approval"]["auto"] is None
    assert plan["approval"]["slots"] == [{"group": "approver-platform", "count": 2, "reason": plan["approval"]["slots"][0]["reason"]}]
    # Nothing written: no request, no PR, the cluster unchanged
    assert client.get("/api/v1/requests", headers=auth(keys, "opal", **OPAL)).json()["page"]["total"] == 0
    assert git.prs == {} and kube.objects == before and kube.applied == []


def test_a_key_that_client_side_apply_wrote_under_a_skip_prefix_stays_in_git(world):
    """D3a: Argo CD's client-side apply migration would remove it from the cluster on the first sync if Git left it out."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    meta = kube.objects[("Namespace", "", NS)]["metadata"]
    meta["managedFields"][0]["fieldsV1"]["f:metadata"]["f:labels"]["f:pod-security.kubernetes.io/audit"] = {}
    plan = adopt(client, keys, dry_run=True).json()
    labels = yaml.safe_load(plan["files"][BASE + "namespace.yaml"])["metadata"]["labels"]
    assert labels["pod-security.kubernetes.io/audit"] == "restricted"
    kept = [f for f in plan["findings"] if f["rule"] == "skipped-key-kept"]
    assert kept and "kubectl-client-side-apply" in kept[0]["message"]


@pytest.mark.parametrize("change, rule", [
    (lambda kube: kube.objects[("Namespace", "", NS)]["metadata"]["labels"].pop("cmapi.net/adopt"), "not-labelled"),
    (lambda kube: kube.objects[("Namespace", "", NS)]["metadata"]["labels"].update({"cmapi.net/managed": "true"}), "managed"),
    (lambda kube: kube.objects[("Namespace", "", NS)]["metadata"]["annotations"].update(
        {"argocd.argoproj.io/tracking-id": "team-apps:/Namespace:/abc-rnd"}), "tracked-elsewhere"),
])
def test_a_namespace_that_is_not_a_candidate_is_never_taken(world, change, rule):
    """D1: opt-in, not managed, not tracked by another Argo CD Application. Refused, and nothing is recorded."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    change(kube)
    for dry in (True, False):
        r = adopt(client, keys, dry_run=dry)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "namespace-not-adoptable" and r.json()["rule"] == rule
    assert client.get("/api/v1/requests", headers=auth(keys, "opal", **OPAL)).json()["page"]["total"] == 0


def test_a_namespace_with_a_folder_in_git_is_managed_and_not_adopted(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    git.branches["main"][BASE + "namespace.yaml"] = "apiVersion: v1\nkind: Namespace\nmetadata: {name: abc-rnd}\n"
    r = adopt(client, keys, dry_run=True)
    assert r.status_code == 409 and r.json()["rule"] == "managed"


def test_only_adoption_write_may_adopt(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    r = adopt(client, keys, who="ola", role=OLA)
    assert r.status_code == 403, r.text


def test_candidates_and_skipped_list_each_namespace_with_its_rule(world):
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    kube.objects[("Namespace", "", "plain")] = {"metadata": {"name": "plain", "uid": "u2", "labels": {}}}
    kube.objects[("Namespace", "", "kube-x")] = {"metadata": {"name": "kube-x", "uid": "u3", "labels": {"cmapi.net/adopt": "true"}}}
    kube.objects[("Namespace", "", "theirs")] = {"metadata": {
        "name": "theirs", "uid": "u4", "labels": {"cmapi.net/adopt": "true"},
        "annotations": {"argocd.argoproj.io/tracking-id": "team-apps:/Namespace:/theirs"}}}
    h = auth(keys, "opal", **OPAL)
    got = client.get("/api/v1/clusters/CRC/adoption/candidates", headers=h)
    assert got.status_code == 200, got.text
    assert [(i["name"], i["state"]) for i in got.json()["items"]] == [(NS, "candidate")]
    skipped = {i["name"]: i for i in client.get("/api/v1/clusters/CRC/adoption/skipped", headers=h).json()["items"]}
    assert skipped["kube-x"]["rule"] == "excluded" and skipped["theirs"]["rule"] == "tracked-elsewhere"
    assert skipped["theirs"]["application"] == "team-apps" and "plain" not in skipped
    assert client.get("/api/v1/clusters/CRC/adoption/candidates", headers=auth(keys, "ola", **OLA)).status_code == 403


# --------------------------------------------------------------------------- the request, through GitOps


def test_an_adoption_waits_for_people_then_takes_over_only_through_its_pull_request(world):
    """Criterion 1: never automatic, approved by approver-platform, delivered by the bot's PR and its checks. The live objects
    keep every value; only cmapi's keys are added."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    r = adopt(client, keys)
    assert r.status_code == 202, r.text
    req = r.json()
    rid = req["requestId"]
    assert req["status"] == "pending_approval" and req["plugin"] == "adoption" and req["action"] == "adopt"
    assert run_jobs(ctx) == ["channel_notify"] and git.prs == {}          # nothing moves before the approvals
    assert kube.objects[("Namespace", "", NS)]["metadata"]["labels"].get("cmapi.net/managed") is None
    # the files of the request carry its own ID
    row_files = _stored(ctx, rid)["files"]
    assert f"cmapi.net/request-id: {rid}" in row_files[BASE + "namespace.yaml"]
    approve_both(client, keys, rid)
    run_jobs(ctx, limit=40)
    done = request(client, keys, rid)
    assert done["status"] == "synced", done["events"][-4:]
    assert done["pr"] and git.prs[done["pr"]["number"]]["state"] == "merged"
    assert git.branches["main"][BASE + "namespace.yaml"] == row_files[BASE + "namespace.yaml"]
    live = kube.objects[("Namespace", "", NS)]["metadata"]["labels"]
    assert live["cmapi.net/managed"] == "true" and live["company.net/provisioner"] == "cluster-configs"
    assert live["name"] == "aao-rnd" and live["cmapi.net/adopt"] == "true"
    assert kube.objects[("ResourceQuota", NS, "abc-rnd-quota")]["spec"]["scopes"] == ["NotTerminating"]


def test_a_change_after_the_plan_fails_the_request_and_writes_nothing(world):
    """D16: cmapi reads again after the approval; a changed object fails the request, never written over."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    rid = adopt(client, keys).json()["requestId"]
    kube.objects[("ResourceQuota", NS, "abc-rnd-quota")]["metadata"]["resourceVersion"] = "999"
    kube.objects[("ResourceQuota", NS, "abc-rnd-quota")]["spec"]["hard"]["requests.cpu"] = "48"
    approve_both(client, keys, rid)
    run_jobs(ctx, limit=40)
    done = request(client, keys, rid)
    assert done["status"] == "failed"
    assert any(e["event"] == "adoption-plan-stale" for e in done["events"]), done["events"]
    assert kube.applied == [] and git.prs == {}
    assert kube.objects[("ResourceQuota", NS, "abc-rnd-quota")]["spec"]["hard"]["requests.cpu"] == "48"


def test_the_opt_in_label_removed_before_the_merge_cancels_the_request(world):
    """D16: the label is the consent. Removed while the PR is open, the request is cancelled and the PR closed."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    rid = adopt(client, keys).json()["requestId"]
    approve_both(client, keys, rid)
    for _ in range(10):                                    # up to the open PR, its checks not run yet
        ran = run_jobs(ctx, limit=1)
        if ran == ["open_pr"]:
            break
    kube.objects[("Namespace", "", NS)]["metadata"]["labels"].pop("cmapi.net/adopt")
    kube.objects[("Namespace", "", NS)]["metadata"]["resourceVersion"] = "101"
    run_jobs(ctx, limit=40)
    done = request(client, keys, rid)
    assert done["status"] == "cancelled", done["events"][-3:]
    assert any(e["event"] == "adoption-label-removed" for e in done["events"])
    assert all(p["state"] == "closed" for p in git.prs.values()) and kube.applied == []


def test_the_policy_base_is_the_approved_snapshot_at_plan_time_and_in_the_pr_check(world):
    """#248, D6a: a value that the namespace already holds is reported as policy-ratcheted, not refused, at plan time and in
    the PR check, and the PR check takes its base from the stored plan, never from Git or the PR."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    validator.held = [Finding("kyverno", "cmapi-metadata-dev-label-name-derived", BASE + "namespace.yaml",
                              "the label name must be abc-rnd", "warning", kyverno_rule="validation")]
    plan = adopt(client, keys, dry_run=True).json()
    ratcheted = [f for f in plan["findings"] if f["rule"] == "policy-ratcheted"]
    assert ratcheted and "cmapi-metadata-dev-label-name-derived" in ratcheted[0]["message"]
    snapshot = validator.previous[-1]
    assert snapshot and "name: aao-rnd" in snapshot[BASE + "namespace.yaml"]
    assert "cmapi.net/managed" not in snapshot[BASE + "namespace.yaml"]          # the live object, not the adopted file
    rid = adopt(client, keys).json()["requestId"]
    approve_both(client, keys, rid)
    run_jobs(ctx, limit=40)
    assert request(client, keys, rid)["status"] == "synced"
    pr_check_base = validator.previous[-1]
    assert pr_check_base == _stored(ctx, rid)["adoption"]["snapshot"]


def test_a_tampered_snapshot_is_not_believed_by_the_pr_check(world):
    """D6a, step 2: the PR check checks the stored snapshot against the plan's digest."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    rid = adopt(client, keys).json()["requestId"]
    with ctx.db.session() as s:
        s.execute(text("update change_requests set plan = jsonb_set(plan, '{adoption,snapshot}', "
                       "(plan->'adoption'->'snapshot') || jsonb_build_object(CAST(:k AS text), 'x: 1'::text)) where request_id = :r"),
                  {"k": BASE + "extra.yaml", "r": rid})
    approve_both(client, keys, rid)
    run_jobs(ctx, limit=40)
    done = request(client, keys, rid)
    assert done["status"] == "failed" and kube.applied == []
    assert any("snapshot" in (e["note"] or "") for e in done["events"]), done["events"][-3:]


def test_a_failed_adoption_is_never_reverted(world):
    """D11 step 4 (Fable's A2): a revert would let Argo CD prune objects that existed before cmapi."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    rid = adopt(client, keys).json()["requestId"]
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status = 'sync_failed', merge_sha = 'abc123' where request_id = :r"),
                  {"r": rid})
    r = client.post(f"/api/v1/requests/{rid}:revert", headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 409 and r.json()["code"] == "invalid-transition", r.text
    assert run_jobs(ctx) in ([], ["channel_notify"]) and kube.applied == []


def test_an_update_after_the_adoption_keeps_what_cmapi_does_not_own_and_holds_a_missing_key(world):
    """B2 and B9 through the API: after the adoption, a change keeps company.net/provisioner and the wrong `name` as they are,
    lists the missing required key as a finding, and is not refused for it."""
    client, ctx, git, kube, validator, keys = world
    owner_sample(kube)
    rid = adopt(client, keys).json()["requestId"]
    approve_both(client, keys, rid)
    run_jobs(ctx, limit=40)
    assert request(client, keys, rid)["status"] == "synced"
    h = auth(keys, "opal", **OPAL)
    etag = client.get(f"/api/v1/clusters/CRC/namespaces/{NS}", headers=h).json()["etag"]
    r = client.patch(f"/api/v1/clusters/CRC/namespaces/{NS}?dryRun=true", headers={**h, "If-Match": f'"{etag}"'},
                     json={"annotations": {"cmapi.net/team-dl": "abc-team@ephico2real.com"}})
    assert r.status_code == 200, r.text
    plan = r.json()
    ns = yaml.safe_load(plan["files"][BASE + "namespace.yaml"])
    assert ns["metadata"]["labels"]["company.net/provisioner"] == "cluster-configs"
    assert ns["metadata"]["labels"]["name"] == "aao-rnd" and ns["metadata"]["labels"]["cmapi.net/adopt"] == "true"
    assert any(f["rule"] == "missing_required_key" for f in plan["findings"]), plan["findings"]
    # the adopted quota keeps its scope and values: a change of a label leaves every object unchanged (D9)
    assert not any(p.endswith(".yaml") and "resourcequota" in p for p in plan["changes"]), plan["changes"]


def _stored(ctx, rid):
    with ctx.db.session() as s:
        return s.execute(text("select plan from change_requests where request_id = :r"), {"r": rid}).scalar()
