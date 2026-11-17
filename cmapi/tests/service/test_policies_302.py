"""#302, the Policies part of portal slice 4: GET /api/v1/policies/results and /policies/rejections.

The fake cluster serves Kyverno's API groups only when a test says so (`served_groups`): by default it is CRC as measured,
with no Kyverno. Reports are written in the shape of Kyverno v1.20.0's (a ClusterPolicyReport per Namespace, results with
policy, rule, result, message, properties.process and a {seconds} timestamp: docs/reviews/2026-11-17-issue-333/evidence/
kind/outside.log), and the cache is synced in the test's thread (`ReportCache.sync`), since the fake does not stream a watch.

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_policies_302.py -q -W ignore
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone

import pytest
import yaml
from prometheus_client import REGISTRY
from sqlalchemy import select, text

from cmapi.core.db.models import PolicyRejectionRow
from cmapi.core.policygen import ACTIONS
from cmapi.core.ports import Finding
from conftest import build_world
from test_flow import NS, OLA, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces"
RESULTS = "/api/v1/policies/results"
REJECTIONS = "/api/v1/policies/rejections"
KYVERNO = {"wgpolicyk8s.io/v1alpha2", "policies.kyverno.io/v1"}
BOT_RND = dict(roles=["cmapi-bot-rnd"], groups=[])           # objects:read and requests:read in rnd only, not CRC's dev
VIEWER = dict(roles=["cmapi-viewer"], groups=["/cmapi/app-cmapi-rbac-viewer"])
TS = 1794922870                                                 # the background scan of outside.log


def get(client, keys, path, who=OLA, user="ola"):
    r = client.get(path, headers=auth(keys, user, **who))
    assert r.status_code == 200, r.text
    return r.json()


def put_ns(kube, name, managed=True):
    labels = {"cmapi.net/env": "dev", **({"cmapi.net/managed": "true"} if managed else {})}
    kube.objects[("Namespace", "", name)] = {"kind": "Namespace", "metadata": {"name": name, "labels": labels}}


def result(policy, verdict, message="success", rule="validation", process="background scan"):
    return {"policy": policy, "rule": rule, "result": verdict, "message": message, "scored": True,
            "source": "KyvernoValidatingPolicy", "timestamp": {"seconds": TS, "nanos": 0}, "properties": {"process": process}}


def ns_report(kube, ns, results, uid=None):
    """The ClusterPolicyReport of a Namespace, as Kyverno v1.20.0 writes it: named by the resource's UID, scoped to it."""
    name = uid or f"uid-{ns}"
    kube.objects[("ClusterPolicyReport", "", name)] = {
        "apiVersion": "wgpolicyk8s.io/v1alpha2", "kind": "ClusterPolicyReport", "metadata": {"name": name},
        "scope": {"apiVersion": "v1", "kind": "Namespace", "name": ns}, "results": results}


def pod_report(kube, ns, pod, results):
    kube.objects[("PolicyReport", ns, f"uid-{pod}")] = {
        "apiVersion": "wgpolicyk8s.io/v1alpha2", "kind": "PolicyReport", "metadata": {"name": f"uid-{pod}", "namespace": ns},
        "scope": {"apiVersion": "v1", "kind": "Pod", "name": pod, "namespace": ns}, "results": results}


def live_bundle(kube, ctx, env="dev", actions=None, skip=(), digest_of=None):
    """The bundle of the environment on the cluster, as cmapi rendered it: each ValidatingPolicy with its digest and actions."""
    for name, p in ctx.bundle.for_environment(env).items():
        if name in skip:
            continue
        digest = (digest_of or {}).get(name, p.digest)
        kube.objects[("ValidatingPolicy", "", name)] = {
            "apiVersion": "policies.kyverno.io/v1", "kind": "ValidatingPolicy",
            "metadata": {"name": name, "annotations": {"cmapi.net/generated": "true", "cmapi.net/policy-digest": digest}},
            "spec": {"validationActions": list(actions or ACTIONS["audit"])},
            "status": {"conditionStatus": {"ready": True}}}


def sync(ctx):
    st = ctx.registry.clusters["CRC"]
    st.cache._list("Namespace")
    st.reports.sync()


def pick(ctx, rule, kind="label", env="dev"):
    """A rendered policy of the dev bundle by what it checks, from index.json: never a name written here."""
    return next(n for n, p in sorted(ctx.bundle.for_environment(env).items()) if p.check and p.check["rule"] == rule
                and p.check["kind"] == kind)


@pytest.fixture
def kyverno(world):
    """CRC with Kyverno v1.20 in audit: the dev bundle live and current, two managed namespaces and one that is not."""
    client, ctx, git, kube, validator, keys = world
    kube.served_groups = set(KYVERNO)
    live_bundle(kube, ctx)
    put_ns(kube, "orders-dev")
    put_ns(kube, "payments-dev")
    put_ns(kube, "team-sandbox", managed=False)
    prefix = pick(ctx, "prefix")
    ns_report(kube, "orders-dev", [result(prefix, "fail", "the label keys other.example/x are not declared in metadata-keys.yaml"),
                                   result(pick(ctx, "max"), "pass")])
    ns_report(kube, "payments-dev", [result(prefix, "pass"), result(pick(ctx, "pattern"), "warn", "unscored: pattern")])
    ns_report(kube, "team-sandbox", [result(prefix, "fail", "not managed")])
    ns_report(kube, "orders-dev-extra", [result("require-labels", "fail", "a ClusterPolicy of someone else")], uid="other")
    pod_report(kube, "orders-dev", "web-0", [result("require-labels", "fail", "another policy"),
                                             result(prefix, "error", "could not evaluate")])
    sync(ctx)
    return world


# ---------------------------------------------------------------- the states, never a zero

def test_kyverno_not_installed_is_a_state_from_discovery_with_null_counts(world):
    """CRC as measured: discovery answers 404 for wgpolicyk8s.io, so the tab says not installed, and no list is made."""
    client, ctx, git, kube, validator, keys = world
    kube.calls.clear()
    ctx.registry.clusters["CRC"].reports.sync()
    body = get(client, keys, RESULTS)
    [cl] = body["clusters"]
    assert (cl["clusterId"], cl["env"], cl["mode"], cl["state"]) == ("CRC", "dev", "audit", "not-installed")
    assert cl["counts"] is None and cl["hidden"] is None and cl["dropped"] is None and cl["bundle"] is None
    assert body["items"] == [] and body["page"]["total"] == 0
    assert [c for c in kube.calls if not c.startswith("discovery")] == [], "a list of a kind that discovery does not serve"


def test_a_403_on_the_list_is_forbidden_not_not_installed(world):
    """Discovery serves the group, the reader lacks the grant: the state names the grant (design A, D2)."""
    client, ctx, git, kube, validator, keys = world
    kube.served_groups = set(KYVERNO)
    kube.forbidden_kinds = {"ClusterPolicyReport"}
    sync(ctx)
    [cl] = get(client, keys, RESULTS)["clusters"]
    assert cl["state"] == "forbidden" and "clusterpolicyreports" in cl["stateDetail"] and cl["counts"] is None


def test_an_unreachable_cluster_keeps_its_state_and_the_time_of_its_check(world):
    client, ctx, git, kube, validator, keys = world
    kube.unreachable = True
    ctx.registry.refresh()
    [cl] = get(client, keys, RESULTS)["clusters"]
    assert cl["state"] == "unreachable" and cl["counts"] is None and cl["asOf"] is not None
    assert cl["stateDetail"].startswith("the cluster is unreachable")


def test_a_cluster_not_listed_yet_is_loading(world):
    client, ctx, git, kube, validator, keys = world
    kube.served_groups = set(KYVERNO)
    ctx.registry.clusters["CRC"].reports.probe()
    [cl] = get(client, keys, RESULTS)["clusters"]
    assert cl["state"] == "loading" and cl["counts"] is None


def test_reports_before_the_namespaces_are_listed_are_loading(kyverno):
    """Which namespaces cmapi manages comes from the watch cache: before its first list, no result is counted as unmanaged."""
    client, ctx, git, kube, validator, keys = kyverno
    ctx.registry.clusters["CRC"].cache.state["Namespace"].last_good = None
    [cl] = get(client, keys, RESULTS)["clusters"]
    assert (cl["state"], cl["stateDetail"], cl["counts"]) == ("loading", "the namespaces are being listed", None)


def test_stale_reports_keep_their_counts_and_say_so(kyverno, monkeypatch):
    client, ctx, git, kube, validator, keys = kyverno
    watch = ctx.registry.clusters["CRC"].reports.watch
    later = watch.clock() + watch.RELIST_SECONDS + 1
    monkeypatch.setattr(watch, "clock", lambda: later)
    [cl] = get(client, keys, RESULTS)["clusters"]
    assert cl["state"] == "stale" and cl["counts"]["fail"] == 1 and cl["asOf"] is not None


def test_ok_counts_the_managed_namespaces_and_hides_the_rest_by_count(kyverno):
    client, ctx, git, kube, validator, keys = kyverno
    body = get(client, keys, RESULTS)
    [cl] = body["clusters"]
    assert cl["state"] == "ok" and cl["stateDetail"] is None and cl["mode"] == "audit"
    assert cl["counts"] == {"pass": 2, "fail": 1, "warn": 1, "error": 1, "skip": 0}
    # team-sandbox is not managed (1), orders-dev-extra is not a namespace the cache knows (1); require-labels is not ours (1)
    assert cl["hidden"] == {"unmanaged": 2, "otherPolicies": 1, "stale": 0}
    expected = len(ctx.bundle.for_environment("dev"))
    assert cl["bundle"] == {"expected": expected, "live": expected, "current": expected, "ready": expected, "missing": [],
                            "differing": [], "actionsDiffer": []}
    assert cl["liveActions"] == ["Audit", "Warn"] and cl["dropped"] == 0
    assert body["policy"]["engine"] == "kyverno" and body["policy"]["environments"] == {"dev": "audit", "rnd": "audit"}


def test_rows_carry_the_policy_the_rule_and_the_message(kyverno):
    client, ctx, git, kube, validator, keys = kyverno
    body = get(client, keys, RESULTS)
    rows = {(i["namespace"], i["resource"]["kind"], i["result"]): i for i in body["items"]}
    assert set(rows) == {("orders-dev", "Namespace", "fail"), ("payments-dev", "Namespace", "warn"), ("orders-dev", "Pod", "error")}
    fail = rows[("orders-dev", "Namespace", "fail")]
    assert fail["policy"] == pick(ctx, "prefix") and fail["rule"] == "prefix" and fail["kyvernoRule"] == "validation"
    assert fail["message"].startswith("the label keys other.example/x") and fail["process"] == "background scan"
    assert fail["resource"] == {"apiVersion": "v1", "kind": "Namespace", "name": "orders-dev"} and fail["mode"] == "audit"
    assert fail["observedAt"].startswith(datetime.fromtimestamp(TS, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
    assert "team-sandbox" not in {i["namespace"] for i in body["items"]}, "an unmanaged namespace is a count, never a row"


def test_the_policies_come_from_the_bundle_with_their_counts(kyverno):
    """No list in the code: each policy of the dev bundle, from the render, with what it checks and its counts."""
    client, ctx, git, kube, validator, keys = kyverno
    body = get(client, keys, RESULTS)
    names = [p["name"] for p in body["policies"]]
    assert names == sorted(ctx.bundle.for_environment("dev")) and "require-labels" not in names
    p = next(p for p in body["policies"] if p["name"] == pick(ctx, "prefix"))
    assert p["kind"] == "ValidatingPolicy" and p["generated"] and p["environments"] == ["dev"] and p["check"]["rule"] == "prefix"
    assert p["counts"] == {"pass": 1, "fail": 1, "warn": 0, "error": 1, "skip": 0} and p["description"]
    one = get(client, keys, f"{RESULTS}?namespace=payments-dev")
    assert next(x for x in one["policies"] if x["name"] == p["name"])["counts"]["fail"] == 0, "the counts follow the namespace"


def test_drift_by_digest_by_absence_and_by_the_actions_of_the_mode(kyverno):
    client, ctx, git, kube, validator, keys = kyverno
    changed, gone = pick(ctx, "pattern"), pick(ctx, "max")
    kube.objects.pop(("ValidatingPolicy", "", gone))
    kube.objects[("ValidatingPolicy", "", changed)]["metadata"]["annotations"]["cmapi.net/policy-digest"] = "0" * 64
    sync(ctx)
    [cl] = get(client, keys, RESULTS)["clusters"]
    assert cl["state"] == "drift" and cl["bundle"]["missing"] == [gone] and cl["bundle"]["differing"] == [changed]
    assert cl["hidden"]["stale"] == 1, "the result of a policy that left the cluster is stale, not counted"
    # The configured mode is audit; the cluster's copies deny: the live actions say so, never a guess from fail or warn.
    live_bundle(kube, ctx, actions=ACTIONS["enforce"])
    sync(ctx)
    [cl] = get(client, keys, RESULTS)["clusters"]
    assert cl["state"] == "drift" and cl["mode"] == "audit" and cl["liveActions"] == ["Deny"]
    assert len(cl["bundle"]["actionsDiffer"]) == min(20, cl["bundle"]["expected"]) and "without the actions Audit, Warn of mode audit" in cl["stateDetail"]


def test_an_unscored_warn_stays_warn_in_audit(kyverno):
    """Kyverno turns the fail of an unscored policy into warn (pkg/utils/report/results.go): the row says warn, the mode audit."""
    client, ctx, git, kube, validator, keys = kyverno
    rows = get(client, keys, f"{RESULTS}?result=warn")["items"]
    assert [(r["namespace"], r["result"], r["mode"]) for r in rows] == [("payments-dev", "warn", "audit")]


def test_past_the_cap_rows_are_counted_not_listed(world):
    client, ctx, git, kube, validator, keys = world
    kube.served_groups = set(KYVERNO)
    live_bundle(kube, ctx)
    ctx.registry.clusters["CRC"].reports.max_rows = 2
    put_ns(kube, "team-sandbox", managed=False)
    ns_report(kube, "team-sandbox", [result(pick(ctx, "prefix"), "fail", "not managed")])
    for i in range(4):
        put_ns(kube, f"bulk{i}-dev")
        ns_report(kube, f"bulk{i}-dev", [result(pick(ctx, "prefix"), "fail", f"bulk {i}")])
    sync(ctx)
    body = get(client, keys, RESULTS)
    [cl] = body["clusters"]
    # 5 rows of the bundle's policies, team-sandbox's among them: managed-ness is applied at read, since a namespace can
    # become managed later, so every row counts against the cap. The first two listed are kept, 3 are dropped; the counts
    # stay exact.
    assert cl["state"] == "capped" and cl["dropped"] == 3 and cl["counts"]["fail"] == 4 and cl["hidden"]["unmanaged"] == 1
    assert [i["namespace"] for i in body["items"]] == ["bulk0-dev", "bulk1-dev"] and "maxResultsPerCluster" in cl["stateDetail"]


def test_the_mode_off_reads_nothing(test_config, fresh_db, keys, monkeypatch, tmp_path):
    d = _config(test_config, tmp_path, {"environments": {"dev": {"mode": "off"}}})
    with build_world(d, keys, monkeypatch) as (client, ctx, git, kube, validator, keys):
        kube.served_groups = set(KYVERNO)
        assert ctx.registry.clusters["CRC"].reports is None
        [cl] = get(client, keys, RESULTS)["clusters"]
        assert (cl["state"], cl["mode"], cl["counts"]) == ("mode-off", "off", None)
        assert [c for c in kube.calls if "Report" in c or "discovery" in c or "Policy" in c] == []


def _config(test_config, tmp_path, policy):
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    inst["instance"]["policy"] = policy
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    return d


def test_engine_none_reads_no_report_and_still_lists_cmapis_refusals(test_config, fresh_db, keys, monkeypatch, tmp_path):
    d = _config(test_config, tmp_path, {"engine": "none"})
    with build_world(d, keys, monkeypatch) as (client, ctx, git, kube, validator, keys):
        kube.served_groups = set(KYVERNO)
        body = get(client, keys, RESULTS)
        [cl] = body["clusters"]
        assert body["policy"]["engine"] == "none" and cl["state"] == "engine-off" and cl["counts"] is None
        assert body["policies"] == [] and body["items"] == []
        assert [c for c in kube.calls if "Report" in c or "discovery" in c or "Policy" in c] == [], "engine none calls no report"
        r = client.post(URL, json={**NS, "namespace": "kube-tools"}, headers=auth(keys, "ola", **OLA))
        assert r.status_code == 422 and r.json()["code"] == "reserved-namespace"
        [row] = get(client, keys, REJECTIONS)["items"]
        assert (row["problem"], row["namespace"], row["outcome"]) == ("reserved-namespace", "kube-tools", "refused")


# ---------------------------------------------------------------- what a caller sees

def test_a_caller_sees_only_the_environments_of_its_roles(kyverno):
    client, ctx, git, kube, validator, keys = kyverno
    body = get(client, keys, RESULTS, BOT_RND, "bot")
    assert body["clusters"] == [] and body["items"] == [] and body["policies"] == []
    assert get(client, keys, f"{RESULTS}?namespace=orders-dev", BOT_RND, "bot")["items"] == []
    assert len(get(client, keys, RESULTS, VIEWER, "vic")["items"]) == 3
    r = client.get(RESULTS, headers=auth(keys, "relay", roles=["cmapi-approval-relay"], groups=[]))
    assert r.status_code == 403, "no objects:read anywhere"


def test_filters_and_paging_are_stable_while_verdicts_change(kyverno):
    """Keyset on the result's identity, never on its verdict: a row that turns from fail to warn keeps its place, a new row
    may appear on a later page, and none repeats (design B)."""
    client, ctx, git, kube, validator, keys = kyverno
    prefix = pick(ctx, "prefix")
    for i in range(6):
        put_ns(kube, f"p{i}-dev")
        ns_report(kube, f"p{i}-dev", [result(prefix, "fail", f"row {i}")])
    sync(ctx)
    first = get(client, keys, f"{RESULTS}?limit=4&policy={prefix}")
    seen = [i["namespace"] for i in first["items"]]
    assert first["page"]["total"] == 8 and len(seen) == 4
    # Between the pages: an earlier namespace flips fail to warn, and a new row arrives before the cursor.
    ns_report(kube, seen[1], [result(prefix, "warn", "now unscored")])
    put_ns(kube, "a-early-dev")
    ns_report(kube, "a-early-dev", [result(prefix, "fail", "new")])
    sync(ctx)
    second = get(client, keys, f"{RESULTS}?limit=4&policy={prefix}&cursor={first['page']['nextCursor']}")
    later = [i["namespace"] for i in second["items"]]
    assert not set(seen) & set(later), "a row repeated"
    assert "a-early-dev" not in later and len(later) == 4
    r = client.get(f"{RESULTS}?limit=4&cursor={first['page']['nextCursor']}", headers=auth(keys, "ola", **OLA))
    assert r.status_code == 400 and r.json()["code"] == "invalid-cursor", "a cursor of another filter"
    r = client.get(f"{RESULTS}?result=pass", headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "validation-failed"


def test_reports_are_listed_in_chunks_and_kept_small(kyverno):
    client, ctx, git, kube, validator, keys = kyverno
    reports = ctx.registry.clusters["CRC"].reports
    reports.watch.chunk = 2
    kube.calls.clear()
    sync(ctx)
    assert kube.calls.count("ClusterPolicyReport") == 2, "4 reports in pages of 2"
    snap = reports.snapshot()
    kept = [r for r in snap.reports if r.namespace == "orders-dev" and r.resource[1] == "Namespace"][0]
    assert [row.result for row in kept.rows] == ["fail"], "pass is a counter, not a row"
    assert kept.counts[(pick(ctx, "max"), "pass")] == 1


# ---------------------------------------------------------------- the rejections

def rejection_rows(database):
    with database.session() as s:
        return list(s.scalars(select(PolicyRejectionRow).order_by(PolicyRejectionRow.id)))


def test_a_refusal_is_stored_with_the_username_only(world, fresh_db):
    client, ctx, git, kube, validator, keys = world
    body = {**NS, "namespace": "checkout-dev", "labels": {"cmapi.net/team": "Pay_Ments", "cmapi.net/cost-center": "cc-4410"},
            "justification": "a secret reason 4711"}
    validator.findings = [Finding("kyverno", pick(ctx, "pattern"), "clusters/CRC/namespaces/checkout-dev/namespace.yaml",
                                  "the label cmapi.net/team is not a match", "warning", kyverno_rule="validation")]
    r = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    [row] = rejection_rows(fresh_db)
    assert (row.stage, row.outcome, row.problem, row.request_id, row.username, row.automated) == \
        ("plan", "refused", "policy-violation", None, "ola", False)
    stored = str({c.name: getattr(row, c.name) for c in PolicyRejectionRow.__table__.columns})
    for secret in ("a secret reason 4711", "ola@ephico2real.com", "1001", "sub-ola"):
        assert secret not in stored, f"{secret} is in the stored row"
    item = get(client, keys, REJECTIONS)["items"][0]
    assert item["id"].startswith("rej-") and item["username"] == "ola" and item["requestId"] is None and item["count"] == 1
    assert "justification" not in str(item) and "ola@" not in str(item) and "employee" not in str(item).lower()
    cmapi, kyverno_finding = item["findings"][0], item["findings"][-1]
    assert (cmapi["source"], cmapi["policy"], cmapi["rule"], cmapi["path"], cmapi["severity"]) == \
        ("cmapi", "metadata-keys", "invalid_value", "labels/cmapi.net/team", "error")
    assert (kyverno_finding["source"], kyverno_finding["rule"], kyverno_finding["kyvernoRule"], kyverno_finding["severity"]) == \
        ("kyverno", "pattern", "validation", "warning"), "Kyverno's rule is kept beside index.json's"
    # The same refusal again: one row, count 2, the same id and place.
    again = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    assert again.status_code == 422
    items = get(client, keys, REJECTIONS)["items"]
    assert [(i["id"], i["count"]) for i in items] == [(item["id"], 2)]


def test_a_dry_run_is_counted_not_stored(world, fresh_db):
    client, ctx, git, kube, validator, keys = world
    before = REGISTRY.get_sample_value("cmapi_plan_refusals_total", {"code": "reserved-namespace", "dry_run": "true"}) or 0
    r = client.post(f"{URL}?dryRun=true", json={**NS, "namespace": "kube-tools"}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422
    assert rejection_rows(fresh_db) == []
    assert REGISTRY.get_sample_value("cmapi_plan_refusals_total", {"code": "reserved-namespace", "dry_run": "true"}) == before + 1


def test_cmapis_own_refusals_are_counted_as_validation_failures(world):
    """Before #302, cmapi's own refusals were raised before the only increment of cmapi_validation_failures_total."""
    client, ctx, git, kube, validator, keys = world
    before = REGISTRY.get_sample_value("cmapi_validation_failures_total", {"source": "cmapi"}) or 0
    r = client.post(f"{URL}?dryRun=true", json={**NS, "labels": {"cmapi.net/team": "Pay_Ments"}}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and len(r.json()["errors"]) == 1
    r = client.post(f"{URL}?dryRun=true", json={**NS, "namespace": "kube-tools"}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422
    assert REGISTRY.get_sample_value("cmapi_validation_failures_total", {"source": "cmapi"}) == before + 2


def test_a_failed_write_leaves_the_422_unchanged(world, fresh_db, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    body = {**NS, "namespace": "kube-tools"}
    want = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    import cmapi.core.rejections as rejections

    def broken(self, **kw):
        raise RuntimeError("database down")
    monkeypatch.setattr(rejections.RejectionRepo, "record", broken)
    before = REGISTRY.get_sample_value("cmapi_policy_rejections_unrecorded_total", {"stage": "plan"}) or 0
    got = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    assert (got.status_code, got.json()) == (want.status_code, want.json())
    assert REGISTRY.get_sample_value("cmapi_policy_rejections_unrecorded_total", {"stage": "plan"}) == before + 1


def test_kyvernos_warnings_on_an_accepted_plan_are_stored_with_the_request(world, fresh_db):
    client, ctx, git, kube, validator, keys = world
    validator.findings = [Finding("kyverno", pick(ctx, "prefix"), "clusters/CRC/namespaces/payments-dev/namespace.yaml",
                                  "outside the prefixes", "warning", kyverno_rule="validation")]
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    [row] = rejection_rows(fresh_db)
    assert (row.stage, row.outcome, row.problem, row.request_id) == ("plan", "warned", None, r.json()["requestId"])
    item = get(client, keys, f"{REJECTIONS}?outcome=warned")["items"][0]
    assert item["requestId"] == r.json()["requestId"] and item["findings"][0]["rule"] == "prefix"


def test_a_ci_refusal_is_stored_with_its_request(world, fresh_db):
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    rid = r.json()["requestId"]
    for _ in range(6):
        ran = run_jobs(ctx, limit=1)
        if ran == ["open_pr"] or not ran:
            break
    pr = get(client, keys, f"/api/v1/requests/{rid}")["pr"]
    path = "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml"
    git.tamper(pr["branch"], path, git.branches[pr["branch"]][path] + "# a hand edit\n")
    run_jobs(ctx)
    [row] = [x for x in rejection_rows(fresh_db) if x.stage == "ci"]
    assert (row.outcome, row.request_id, row.problem, row.findings[0]["policy"]) == ("refused", rid, None, "cmapi-check")


def test_rejections_scope_window_and_retention(world, fresh_db):
    client, ctx, git, kube, validator, keys = world
    client.post(URL, json={**NS, "namespace": "kube-tools"}, headers=auth(keys, "ola", **OLA))
    assert get(client, keys, REJECTIONS, BOT_RND, "bot")["items"] == [], "dev's refusal is not for an rnd caller"
    for bad in ("0d", "91d", "8h", "x"):
        r = client.get(f"{REJECTIONS}?since={bad}", headers=auth(keys, "ola", **OLA))
        assert r.status_code == 422 and r.json()["code"] == "validation-failed", bad
    assert get(client, keys, f"{REJECTIONS}?since=90d")["since"] == "90d"
    with fresh_db.engine.begin() as c:
        c.execute(text("UPDATE policy_rejections SET first_at = now() - interval '10 days', last_at = now() - interval '10 days'"))
    assert get(client, keys, REJECTIONS)["items"] == [] and len(get(client, keys, f"{REJECTIONS}?since=30d")["items"]) == 1
    with fresh_db.engine.begin() as c:
        c.execute(text("UPDATE policy_rejections SET last_at = now() - interval '91 days'"))
    from cmapi.core.db.repo import JobRepo
    with fresh_db.session() as s:
        JobRepo(s).enqueue("rejections_prune")
    assert run_jobs(ctx, limit=1) == ["rejections_prune"]
    assert rejection_rows(fresh_db) == [], "past the retention of 90 days"


def test_the_retention_is_a_key_of_the_instance(test_config, tmp_path):
    from cmapi.core.config import ConfigError, load_instance
    d = _config(test_config, tmp_path, {"rejections": {"retentionDays": 30}, "reports": {"maxResultsPerCluster": 500}})
    cfg = load_instance(d, d / "metadata-keys.yaml")
    assert (cfg.policy.rejection_retention_days, cfg.policy.max_results_per_cluster) == (30, 500)
    bad = tmp_path / "bad"
    shutil.copytree(d, bad)
    inst = yaml.safe_load((bad / "instance.yaml").read_text())
    inst["instance"]["policy"] = {"rejections": {"retentionDays": 0}}
    (bad / "instance.yaml").write_text(yaml.safe_dump(inst))
    with pytest.raises(ConfigError, match="retentionDays is a whole number"):
        load_instance(bad, bad / "metadata-keys.yaml")


def test_the_check_constraints_refuse_a_refused_plan_with_a_request(fresh_db):
    with pytest.raises(Exception, match="ck_rej_request"):
        with fresh_db.engine.begin() as c:
            c.execute(text("INSERT INTO change_requests (request_id, instance, cluster_id, namespace, env, plugin, action, status, "
                           "plan, plan_hash, requester, requester_sub, requester_kind, requester_client, requester_username) "
                           "VALUES ('req-1', 'nonprod', 'CRC', 'a', 'dev', 'namespaces', 'create', 'synced', '{}', 'h', '{}', "
                           "'s', 'user', 'c', 'u')"))
            c.execute(text("INSERT INTO policy_rejections (day, stage, outcome, problem, cluster_id, env, namespace, plugin, "
                           "action, request_id, username, automated, findings, fingerprint) VALUES (current_date, 'plan', "
                           "'refused', 'policy-violation', 'CRC', 'dev', 'a', 'namespaces', 'create', 'req-1', 'u', false, "
                           "'[]', 'f')"))


def test_the_integrations_policy_is_the_named_schema(world):
    client, ctx, git, kube, validator, keys = world
    spec = client.get("/openapi.json").json()
    ref = spec["components"]["schemas"]["Integrations"]["properties"]["policy"]
    assert ref.get("$ref") == "#/components/schemas/Policy", ref
    assert set(spec["components"]["schemas"]["Policy"]["properties"]) == {"engine", "kyvernoVersion", "environments"}


def test_kyvernos_rule_is_kept_in_a_finding():
    """Before #302 core/validate dropped the `rule` of Kyverno's report."""
    f = Finding("kyverno", "p", "f.yaml", "m", "warning", kyverno_rule="validation")
    assert f.view() == {"source": "kyverno", "rule": "p", "path": "f.yaml", "message": "m", "severity": "warning",
                        "kyvernoRule": "validation"}
