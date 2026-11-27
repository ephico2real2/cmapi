"""#751: delivery.mode gitops. Whatever applies Git main applies the folder, and cmapi confirms by a read of the full
approved plan. The test plays the outside deliverer: it applies main's folder to the fake cluster, as Argo CD, Flux or a
pipeline would. Design and sources: docs/reviews/2026-11-27-issue-751/README.md.

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_gitops_delivery_751.py -q -W ignore
"""
from __future__ import annotations

import pytest
import yaml
from sqlalchemy import text

from cmapi.core.clients.kube import KubeError
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs
from test_review_d_delivery import run_until, status

PATH = "clusters/CRC/namespaces/payments-dev/"
LEGACY = {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "legacy-bot", "namespace": "payments-dev"}}


def gitops(ctx, timeout=1800, signal="none"):
    ctx.delivery = type(ctx.delivery)(**{**ctx.delivery.__dict__, "mode": "gitops", "poll_seconds": 0,
                                         "sync_timeout_seconds": timeout, "signal": signal})


def deliver(git, kube):
    """The outside deliverer: every object of main's folder, applied as written."""
    for path, body in sorted(git.branches["main"].items()):
        if path.startswith(PATH) and path.endswith(".yaml"):
            for doc in yaml.safe_load_all(body):
                if doc:
                    kube.apply(doc)


def merged(client, ctx, keys, **gitops_kw) -> str:
    """A create of payments-dev, auto-approved, merged in gitops mode, with watch_sync next and nothing applied yet."""
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    gitops(ctx, **gitops_kw)
    assert run_until(ctx, "watch_sync") == "watch_sync"
    assert status(client, keys, rid)["status"] == "merged"
    return rid


def notes(view, event=None):
    return [e["note"] for e in view["events"] if event is None or e["event"] == event]


def detail(ctx, rid, event):
    """The detail of the request's last event of that name: stored with the event (docs/16), not in the request's view."""
    with ctx.db.session() as s:
        return s.execute(text("select detail from request_events where request_id = :r and event = :e order by id desc limit 1"),
                         {"r": rid, "e": event}).scalar()


def ns_labels(kube):
    return kube.objects[("Namespace", "", "payments-dev")]["metadata"]["labels"]


# --------------------------------------------------------------------------- an outside deliverer, and what it leaves out

def test_gitops_an_outside_deliverer_applies_the_folder_and_cmapi_confirms_synced(world):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys)
    deliver(git, kube)
    kube.get = lambda path, params=None: pytest.fail(f"gitops read an Argo CD object with no signal set: {path}")
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "synced", notes(v)[-2:]
    synced = next(e for e in v["events"] if e["event"] == "synced")
    assert synced["by"] == "gitops" and "1 Namespace, 1 ResourceQuota and 2 LimitRanges match the plan" in synced["note"], synced


def test_gitops_nothing_applied_waits_then_fails_naming_the_namespace(world):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys)
    run_jobs(ctx, limit=3)
    v = status(client, keys, rid)
    assert v["status"] == "merged" and "Namespace/payments-dev: plan 'present', live absent" in notes(v, "sync_wait")[-1]
    gitops(ctx, timeout=0)
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed", notes(v)[-2:]
    assert "Namespace/payments-dev: plan 'present', live absent" in notes(v, "sync_timeout")[-1]
    found = detail(ctx, rid, "sync_differences")
    assert {d["object"] for d in found["differences"]} == {
        "Namespace/payments-dev", "ResourceQuota/payments-dev-quota", "LimitRange/payments-dev-limits-cpu",
        "LimitRange/payments-dev-limits-memory", "RoleBinding/cmapi-token-issuer"}, found


def test_gitops_a_missing_label_stays_unconfirmed_then_fails_naming_it(world):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys)
    deliver(git, kube)
    del ns_labels(kube)["cmapi.net/team"]                 # the deliverer's apply did not take it, or someone removed it
    run_jobs(ctx, limit=3)
    v = status(client, keys, rid)
    want = "Namespace/payments-dev label cmapi.net/team: plan 'payments', live absent"
    assert v["status"] == "merged" and want in notes(v, "sync_wait")[-1], notes(v)[-1]
    gitops(ctx, timeout=0)
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed" and want in notes(v, "sync_timeout")[-1], notes(v)[-2:]


def test_gitops_a_differing_limitrange_stays_unconfirmed_then_fails_naming_it(world):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys)
    deliver(git, kube)
    lr = kube.objects[("LimitRange", "payments-dev", "payments-dev-limits-cpu")]
    planned = lr["spec"]["limits"][0]["max"]["cpu"]
    lr["spec"]["limits"][0]["max"]["cpu"] = "64"
    run_jobs(ctx, limit=3)
    v = status(client, keys, rid)
    want = f"LimitRange/payments-dev-limits-cpu spec.limits[0].max.cpu: plan {planned!r}, live '64'"
    assert v["status"] == "merged" and want in notes(v, "sync_wait")[-1], notes(v)[-1]
    gitops(ctx, timeout=0)
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed" and want in notes(v, "sync_timeout")[-1], notes(v)[-2:]


def test_gitops_server_added_keys_and_defaults_still_confirm(world):
    """What the API server and OpenShift add after any apply is never a difference: the namespace's metadata.name label, the
    SCC annotations, a deliverer's tracking id, a canonical quantity and a LimitRange item's defaults."""
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys)
    deliver(git, kube)
    ns = kube.objects[("Namespace", "", "payments-dev")]["metadata"]
    ns["labels"]["kubernetes.io/metadata.name"] = "payments-dev"
    ns["labels"]["pod-security.kubernetes.io/audit"] = "restricted"
    ns["annotations"]["openshift.io/sa.scc.uid-range"] = "1000660000/10000"
    ns["annotations"]["argocd.argoproj.io/tracking-id"] = "cluster-configs-crc:/Namespace:/payments-dev"
    from cmapi.core.plan_read import defaulted_limit
    for name in ("payments-dev-limits-cpu", "payments-dev-limits-memory"):
        lr = kube.objects[("LimitRange", "payments-dev", name)]
        lr["spec"]["limits"] = [defaulted_limit(i) for i in lr["spec"]["limits"]]
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "synced", notes(v)[-2:]


# --------------------------------------------------------------------------- case 3: a deliverer that does not prune

def _with_a_removed_object(ctx, kube, rid):
    """The plan removes a ServiceAccount that the previous folder held and the cluster still has. The plan's previous folder
    is set directly: the namespaces plugin renders no ServiceAccount file by itself."""
    with ctx.db.session() as s:
        s.execute(text("update change_requests set plan = jsonb_set(plan, '{prev}', cast(:prev as jsonb)) where request_id = :r"),
                  {"prev": __import__("json").dumps({PATH + "serviceaccount-legacy-bot.yaml": yaml.safe_dump(LEGACY)}), "r": rid})
    kube.apply(dict(LEGACY))


def test_gitops_a_leftover_removed_object_waits_in_awaiting_prune_then_synced_when_gone(world):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys)
    _with_a_removed_object(ctx, kube, rid)
    deliver(git, kube)
    run_jobs(ctx, limit=3)
    v = status(client, keys, rid)
    want = "ServiceAccount/legacy-bot: plan absent, live 'present'"
    assert v["status"] == "merged" and want in notes(v, "sync_wait")[-1], notes(v)[-1]
    gitops(ctx, timeout=0)
    run_jobs(ctx, limit=4)
    v = status(client, keys, rid)
    assert v["status"] == "awaiting_prune", notes(v)[-2:]
    notice = notes(v, "prune_pending")[-1]
    assert "has not removed 1 object(s) this plan removes: ServiceAccount/legacy-bot" in notice, notice
    assert not [e for e in v["events"] if e["event"] in ("sync_timeout", "sync_differences")], "a prune wait is no failure"
    assert want in notes(v, "prune_waiting")[-1]
    kube.delete("ServiceAccount", "payments-dev", "legacy-bot")      # an operator pruned it in the deliverer
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "synced", notes(v)[-2:]
    assert next(e for e in v["events"] if e["event"] == "prune_confirmed")["by"] == "gitops"


def _in_awaiting_prune(client, ctx, git, kube, keys, removed=(LEGACY,)) -> str:
    """A delivered create whose plan removes objects that the deliverer left: awaiting_prune, the clock set back long."""
    rid = merged(client, ctx, keys)
    with ctx.db.session() as s:
        prev = {PATH + f"serviceaccount-{d['metadata']['name']}.yaml": yaml.safe_dump(d) for d in removed}
        s.execute(text("update change_requests set plan = jsonb_set(plan, '{prev}', cast(:prev as jsonb)) where request_id = :r"),
                  {"prev": __import__("json").dumps(prev), "r": rid})
    for d in removed:
        kube.apply(dict(d))
    deliver(git, kube)
    gitops(ctx, timeout=0)
    run_jobs(ctx, limit=2)
    assert status(client, keys, rid)["status"] == "awaiting_prune", notes(status(client, keys, rid))[-2:]
    gitops(ctx, timeout=1800)
    return rid


def test_gitops_a_missing_rolebinding_is_not_synced(world):
    """PR #752 review: the renderer writes the token issuer's RoleBinding on every create. A deliverer that applied the rest
    and not the binding (a deliverer without `bind` on the ClusterRole, say) has not delivered the plan."""
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys)
    deliver(git, kube)
    del kube.objects[("RoleBinding", "payments-dev", "cmapi-token-issuer")]
    run_jobs(ctx, limit=3)
    v = status(client, keys, rid)
    want = "RoleBinding/cmapi-token-issuer: plan 'present', live absent"
    assert v["status"] == "merged" and want in notes(v, "sync_wait")[-1], notes(v)[-2:]
    deliver(git, kube)
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "synced" and "as do 1 RoleBinding" in notes(v, "synced")[-1], notes(v)[-2:]


def test_gitops_a_change_waiting_for_a_prune_still_holds_the_namespace(world):
    """Case 2 (D7) on PostgreSQL: awaiting_prune holds the lock as merged and sync_failed do."""
    client, ctx, git, kube, validator, keys = world
    rid = _in_awaiting_prune(client, ctx, git, kube, keys)
    h = auth(keys, "ola", **OLA)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    r = client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"tier": "medium"}, headers={**h, "If-Match": etag})
    assert r.status_code == 409 and r.json()["code"] == "change-pending" and r.json()["requestId"] == rid, r.text
    with ctx.db.session() as s:
        index = s.execute(text("select indexdef from pg_indexes where indexname = 'uq_cr_open_namespace'")).scalar()
    assert all(f"'{state}'" in index for state in ("merged", "awaiting_prune", "sync_failed")), index


def test_gitops_main_changed_while_waiting_for_a_prune_is_never_synced(world):
    """D3 step 1 holds in awaiting_prune too: the deliverer applies main, so a later change of the folder ends the wait."""
    client, ctx, git, kube, validator, keys = world
    rid = _in_awaiting_prune(client, ctx, git, kube, keys)
    git.tamper("main", PATH + "resourcequota-payments-dev-quota.yaml", "kind: ResourceQuota\nedited: true\n")
    kube.delete("ServiceAccount", "payments-dev", "legacy-bot")
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed" and "Git main's folder differs from the approved plan" in notes(v, "sync_timeout")[-1], \
        notes(v)[-2:]


def test_gitops_a_difference_other_than_a_removal_ends_a_prune_wait_at_sync_timeout(world):
    """awaiting_prune has no :retry or :revert of its own: drift that appears while it waits is bounded by syncTimeout, then
    sync_failed, which offers both. Within the bound it waits, so a passing error does not fail the request."""
    client, ctx, git, kube, validator, keys = world
    rid = _in_awaiting_prune(client, ctx, git, kube, keys)
    del ns_labels(kube)["cmapi.net/team"]
    run_jobs(ctx, limit=2)
    v = status(client, keys, rid)
    assert v["status"] == "awaiting_prune" and "label cmapi.net/team" in notes(v, "prune_waiting")[-1], notes(v)[-2:]
    gitops(ctx, timeout=0)
    run_jobs(ctx)
    v = status(client, keys, rid)
    note = notes(v, "sync_timeout")[-1]
    assert v["status"] == "sync_failed" and "the plan did not match in more than removals" in note, notes(v)[-2:]


def test_gitops_the_prune_notice_keeps_every_name_and_the_operators_action(world):
    client, ctx, git, kube, validator, keys = world
    bots = [{**LEGACY, "metadata": {**LEGACY["metadata"], "name": f"legacy-bot-with-a-long-name-{i:02d}"}} for i in range(30)]
    rid = _in_awaiting_prune(client, ctx, git, kube, keys, removed=bots)
    notice = notes(status(client, keys, rid), "prune_pending")[-1]
    assert "Remove them, or prune in the deliverer" in notice, notice
    assert all(f"ServiceAccount/{b['metadata']['name']}" in notice for b in bots), notice


def test_an_unfillable_deliverer_name_template_stops_the_start():
    """It would raise in the middle of a sync poll, past every handler there (PR #752 review)."""
    from cmapi.core.sync import DeliveryConfig
    for block in ({"flux": {"kustomization": "{cluster}"}}, {"argocd": {"rootApplication": "apps-{0}"}}):
        with pytest.raises(ValueError, match="takes only {clusterId} and {namespace}"):
            DeliveryConfig.from_integrations({"delivery": {"mode": "gitops", "signal": "flux", **block}})


def test_gitops_a_leftover_beside_another_difference_is_sync_failed(world):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys, timeout=0)
    _with_a_removed_object(ctx, kube, rid)
    deliver(git, kube)
    del ns_labels(kube)["cmapi.net/team"]
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed", notes(v)[-2:]
    note = notes(v, "sync_timeout")[-1]
    assert "label cmapi.net/team" in note and "ServiceAccount/legacy-bot" in note, note


def test_gitops_a_retried_change_with_only_removals_left_waits_in_awaiting_prune(world):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys, timeout=0)
    _with_a_removed_object(ctx, kube, rid)
    run_jobs(ctx)                                          # nothing applied: sync_failed
    assert status(client, keys, rid)["status"] == "sync_failed"
    deliver(git, kube)
    r = client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 200, r.text
    run_jobs(ctx, limit=2)
    v = status(client, keys, rid)
    assert v["status"] == "awaiting_prune", notes(v)[-2:]


# --------------------------------------------------------------------------- deletes

def test_gitops_a_delete_is_confirmed_by_absence(world):
    client, ctx, git, kube, validator, keys = world
    merged(client, ctx, keys)
    deliver(git, kube)
    run_jobs(ctx)
    h = auth(keys, "ola", **OLA)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    rid = client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**h, "If-Match": etag}).json()["requestId"]
    assert client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY)).status_code == 200
    run_jobs(ctx, limit=8)
    v = status(client, keys, rid)
    assert v["status"] == "awaiting_prune", notes(v)[-2:]
    assert "waiting for the deliverer to remove the namespace" in notes(v, "prune_pending")[-1]
    assert kube.get_object("Namespace", None, "payments-dev") is not None
    kube.delete("Namespace", None, "payments-dev")      # the deliverer pruned it: no prune:confirm, no Argo CD
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "synced", notes(v)[-2:]
    assert next(e for e in v["events"] if e["event"] == "prune_confirmed")["by"] == "gitops"


# --------------------------------------------------------------------------- case 1: the deliverer's status as signal

def argo_app(phase="Failed", message="admission webhook \"validate.kyverno.svc\" denied the request"):
    return {"status": {"sync": {"status": "OutOfSync", "revision": "x"}, "health": {"status": "Missing"},
                       "operationState": {"phase": phase, "message": message}}}


def flux_kustomization():
    return {"status": {"conditions": [{"type": "Ready", "status": "False", "reason": "ReconciliationFailed",
                                       "message": "Namespace/payments-dev dry-run failed: admission webhook denied"}],
                       "lastAppliedRevision": "main@sha1:aaaa", "lastAttemptedRevision": "main@sha1:bbbb"}}


@pytest.mark.parametrize("signal,answer,said", [
    ("argocd", argo_app(), "last operation Failed: admission webhook"),
    ("flux", flux_kustomization(), "Ready False (ReconciliationFailed): Namespace/payments-dev dry-run failed"),
])
def test_gitops_signal_shows_the_deliverers_error_and_never_gates(world, signal, answer, said):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys, signal=signal)
    paths = []
    kube.get = lambda path, params=None: paths.append(path) or answer
    run_jobs(ctx, limit=3)
    v = status(client, keys, rid)
    assert v["status"] == "merged" and said in notes(v, "sync_wait")[-1], notes(v)[-1]
    want = ("/apis/argoproj.io/v1alpha1/namespaces/openshift-gitops/applications/cluster-configs-crc" if signal == "argocd"
            else "/apis/kustomize.toolkit.fluxcd.io/v1/namespaces/flux-system/kustomizations/cluster-configs-crc")
    assert paths[-1] == want
    gitops(ctx, timeout=0, signal=signal)
    run_jobs(ctx)
    v = status(client, keys, rid)
    note = notes(v, "sync_timeout")[-1]
    assert v["status"] == "sync_failed" and "Namespace/payments-dev: plan 'present'" in note and said in note, note
    assert detail(ctx, rid, "sync_differences")["signal"].startswith("Argo CD" if signal == "argocd" else "Flux")


def test_gitops_a_deliverer_reporting_failure_does_not_stop_a_cluster_that_matches(world):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys, signal="argocd")
    kube.get = lambda path, params=None: argo_app()
    deliver(git, kube)
    run_jobs(ctx)
    assert status(client, keys, rid)["status"] == "synced"


def test_gitops_an_unreadable_signal_is_said_and_changes_nothing(world):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys, signal="flux")

    def forbidden(path, params=None):
        raise KubeError(403, path, "forbidden")
    kube.get = forbidden
    run_jobs(ctx, limit=3)
    v = status(client, keys, rid)
    assert "Flux cluster-configs-crc: forbidden to the reader" in notes(v, "sync_wait")[-1], notes(v)[-1]
    deliver(git, kube)
    run_jobs(ctx)
    assert status(client, keys, rid)["status"] == "synced"


# --------------------------------------------------------------------------- case 2 (D7): checked, and refused at the door

def test_gitops_a_second_request_waits_for_the_first_to_be_confirmed(world):
    """The older request holds the namespace's lock while merged and while sync_failed, so no newer request for it can be
    planned, merged and applied over it: the case of a newer request superseding an unconfirmed one cannot arise."""
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys, timeout=0)

    def change():
        h = auth(keys, "ola", **OLA)
        etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
        return client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"tier": "medium"},
                            headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    second = change()
    assert second.status_code == 409 and second.json()["code"] == "change-pending" and second.json()["requestId"] == rid
    run_jobs(ctx)
    assert status(client, keys, rid)["status"] == "sync_failed"
    again = change()
    assert again.status_code == 409 and again.json()["code"] == "change-pending", again.text


def test_gitops_main_changed_after_the_merge_is_refused_with_the_reason(world):
    client, ctx, git, kube, validator, keys = world
    rid = merged(client, ctx, keys)
    git.tamper("main", PATH + "resourcequota-payments-dev-quota.yaml", "kind: ResourceQuota\nedited: true\n")
    deliver_before = list(kube.applied)
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed" and "Git main's folder differs from the approved plan" in notes(v, "sync_timeout")[-1]
    assert kube.applied == deliver_before, "cmapi never applies in gitops mode"


# --------------------------------------------------------------------------- every mode reads the full plan; configuration

def test_apply_mode_now_reads_the_full_plan(world):
    """Before #751 the read checked the namespace and its quota only: a namespace that lost a label confirmed."""
    client, ctx, git, kube, validator, keys = world
    real = kube.apply

    def drops_the_team_label(doc, field_manager="cmapi-deliverer"):
        obj = real(doc, field_manager)
        if doc["kind"] == "Namespace":
            obj["metadata"]["labels"] = {k: v for k, v in obj["metadata"]["labels"].items() if k != "cmapi.net/team"}
        return obj
    kube.apply = drops_the_team_label
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    run_jobs(ctx, limit=6)
    v = status(client, keys, rid)
    assert v["status"] == "pr_open", notes(v)[-2:]
    assert "label cmapi.net/team: plan 'payments', live absent" in notes(v, "sync_wait")[-1]


def test_an_unknown_delivery_mode_or_signal_stops_the_start(tmp_path):
    from cmapi.core.registry import load_policies
    from cmapi.core.sync import DeliveryConfig
    with pytest.raises(ValueError, match="delivery.mode must be one of argocd, gitops, apply, not 'gitop'"):
        DeliveryConfig.from_integrations({"delivery": {"mode": "gitop"}})
    with pytest.raises(ValueError, match="delivery.signal must be one of none, argocd, flux, not 'tekton'"):
        DeliveryConfig.from_integrations({"delivery": {"mode": "gitops", "signal": "tekton"}})
    assert DeliveryConfig.from_integrations({"delivery": {"mode": "gitops", "signal": "flux",
                                                          "flux": {"namespace": "flux", "kustomization": "k-{clusterId}"}}}) \
        == DeliveryConfig(mode="gitops", signal="flux", flux_namespace="flux", flux_kustomization="k-{clusterId}")
    f = tmp_path / "clusters.yaml"
    f.write_text("clusters:\n  CRC: {environment: dev, delivery: gitop}\n")
    with pytest.raises(ValueError, match="cluster CRC: delivery must be one of argocd, gitops, apply, not 'gitop'"):
        load_policies(f, {"dev"})
    f.write_text("clusters:\n  CRC: {environment: dev, delivery: gitops}\n")
    assert load_policies(f, {"dev"})["CRC"].delivery == "gitops"


# --------------------------------------------------------------------------- the chart (D8)

def _chart(tmp_path, *sets):
    import pathlib
    import shutil
    import subprocess
    if shutil.which("helm") is None:
        pytest.skip("helm")
    root = pathlib.Path(__file__).resolve().parents[3]
    (tmp_path / "ca.crt").write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    args = ["helm", "template", "cmapi", str(root / "deploy/helm/cmapi"), "-n", "cmapi", "-f", str(root / "deploy/environments/crc.yaml"),
            "--set", "cmapi.digest=sha256:" + "a" * 64, "--set", "cmapi_portal.digest=sha256:" + "b" * 64,
            "--set-file", f"trustedCA.certificates={tmp_path / 'ca.crt'}", "--set", "delivery.mode=gitops"]
    for s in sets:
        args += ["--set", s]
    return subprocess.run(args, capture_output=True, text=True)


def test_the_chart_contains_the_gitops_deliverer_and_writes_its_signal(tmp_path):
    r = _chart(tmp_path)
    assert r.returncode != 0 and "delivery.gitops.delivererServiceAccount is empty" in r.stderr, r.stderr[-300:]
    assert "must read system:serviceaccount" in _chart(tmp_path, "delivery.gitops.delivererServiceAccount=flux").stderr
    who = "system:serviceaccount:flux-system:kustomize-controller"
    r = _chart(tmp_path, f"delivery.gitops.delivererServiceAccount={who}", "delivery.signal=flux")
    assert r.returncode == 0, r.stderr[-300:]
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    policy = next(d for d in docs if d["kind"] == "ValidatingAdmissionPolicy" and d["metadata"]["name"] == "cmapi-deliverer-managed-only")
    assert policy["spec"]["matchConditions"][0]["expression"] == f'request.userInfo.username == "{who}"'
    integrations = yaml.safe_load(next(d for d in docs if d["kind"] == "ConfigMap" and "integrations.yaml" in d.get("data", {}))
                                  ["data"]["integrations.yaml"])
    from cmapi.core.sync import DeliveryConfig
    got = DeliveryConfig.from_integrations(integrations)
    assert (got.mode, got.signal, got.flux_namespace, got.flux_kustomization) == ("gitops", "flux", "flux-system",
                                                                                 "cluster-configs-{clusterId}")
    r = _chart(tmp_path, "delivery.gitops.acknowledgeUncontainedDeliverer=true")
    assert r.returncode == 0 and "cmapi-deliverer-managed-only" not in r.stdout
    assert "delivery.gitops.delivererServiceAccount is empty (acknowledged)" in r.stdout or "NOTES" not in r.stdout
