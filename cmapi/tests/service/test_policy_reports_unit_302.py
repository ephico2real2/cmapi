"""#302 without a cluster or a database: what the report cache keeps of a report, the digest on each rendered policy, and
Kyverno's own rule kept in a finding of the validator.

The report below has the shape that Kyverno v1.20.0 wrote on kind for #333 (docs/reviews/2026-11-17-issue-333/evidence/kind/
outside.log): a ClusterPolicyReport scoped to the Namespace, results with a {seconds} timestamp and properties.process.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
import yaml

from cmapi.core.clients.policyreports import MESSAGE_MAX, reduce, reduce_policy
from cmapi.core.config import load_instance
from cmapi.core.policy import PolicySettings
from cmapi.core.policybundle import PolicyBundle
from cmapi.core.policygen import DIGEST, policy_digest, render_bundle
from cmapi.core.validate import CliValidator

EX = Path(__file__).resolve().parents[3] / "examples"


@pytest.fixture(scope="module")
def bundle() -> PolicyBundle:
    cfg = load_instance(EX / "instances" / "nonprod", EX / "cluster-configs" / "policies" / "metadata-keys.yaml")
    return PolicyBundle(render_bundle(cfg.tiers, cfg.metadata, cfg.policy, cfg.allowed_environments, cfg.name))


def test_a_report_keeps_counters_and_the_rows_of_the_bundle_only(bundle):
    dev = bundle.for_environment("dev")
    prefix = next(n for n, p in dev.items() if p.check and p.check["rule"] == "prefix" and p.check["kind"] == "label")
    report = {"kind": "ClusterPolicyReport", "metadata": {"name": "0f3c"},
              "scope": {"apiVersion": "v1", "kind": "Namespace", "name": "orders-dev"},
              "results": [
                  {"policy": prefix, "rule": "validation", "result": "fail", "message": "x" * 1000,
                   "timestamp": {"seconds": 1794922870}, "properties": {"process": "background scan"}},
                  {"policy": prefix, "rule": "validation", "result": "pass", "message": "success"},
                  {"policy": "require-labels", "rule": "check", "result": "fail", "message": "a ClusterPolicy"},
                  {"policy": prefix, "result": "unknown"}, "not a result"]}
    out = reduce("ClusterPolicyReport", report, dev)
    assert out.namespace == "orders-dev" and out.resource == ("v1", "Namespace", "orders-dev")
    assert out.counts == {(prefix, "fail"): 1, (prefix, "pass"): 1, ("require-labels", "fail"): 1}
    [row] = out.rows
    assert (row.policy, row.rule, row.result, row.process, row.at) == (prefix, "validation", "fail", "background scan",
                                                                       "2026-11-17T13:41:10Z")
    assert len(row.message) == MESSAGE_MAX


def test_a_namespaced_report_is_of_its_namespace_and_another_cluster_scoped_one_of_none():
    pod = {"metadata": {"name": "a", "namespace": "orders-dev"}, "scope": {"apiVersion": "v1", "kind": "Pod", "name": "web-0"}}
    assert reduce("PolicyReport", pod, {}).namespace == "orders-dev"
    role = {"metadata": {"name": "b"}, "scope": {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole", "name": "x"}}
    assert reduce("ClusterPolicyReport", role, {}).namespace is None


def test_a_live_policy_keeps_its_digest_actions_and_readiness():
    p = reduce_policy({"metadata": {"name": "n", "annotations": {DIGEST: "abc", "cmapi.net/generated": "true"}},
                       "spec": {"validationActions": ["Audit", "Warn"], "validations": [{"expression": "true"}]},
                       "status": {"conditionStatus": {"ready": True}}})
    assert (p.name, p.digest, p.generated, p.actions, p.ready) == ("n", "abc", True, ("Audit", "Warn"), True)


def test_each_rendered_policy_carries_a_digest_of_itself_without_the_digest(bundle):
    docs = [d for path, text in bundle.files.items() if path.endswith(".yaml") for d in yaml.safe_load_all(text) if d]
    assert docs and all(d["metadata"]["annotations"][DIGEST] == policy_digest(d) for d in docs)
    doc = docs[0]
    assert policy_digest(doc) == policy_digest({**doc, "metadata": {**doc["metadata"], "annotations": {
        **doc["metadata"]["annotations"], DIGEST: "anything"}}}), "the digest excludes its own annotation"
    changed = json.loads(json.dumps(doc))
    changed["spec"]["validations"][0]["expression"] += " && true"
    assert policy_digest(changed) != policy_digest(doc), "a changed CEL expression changes the digest"
    again = render_bundle(*_render_args())
    assert {p: t for p, t in again.items()} == {p: t for p, t in bundle.files.items()}, "the render is stable"


def _render_args():
    cfg = load_instance(EX / "instances" / "nonprod", EX / "cluster-configs" / "policies" / "metadata-keys.yaml")
    return cfg.tiers, cfg.metadata, cfg.policy, cfg.allowed_environments, cfg.name


def test_the_validator_keeps_kyvernos_rule(tmp_path, monkeypatch):
    """Before #302, core/validate dropped the `rule` of each result of `kyverno apply -p --output-format json`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("kubeconform", "echo '{\"resources\": []}'\n"),
                       ("kyverno", "echo '" + json.dumps({"results": [{"policy": "p", "rule": "check-team", "result": "fail",
                                                                       "message": "team missing", "resources": [
                                                                           {"kind": "Namespace", "name": "abc-dev"}]}]})
                        + "'\nexit 1\n")):
        f = bin_dir / name
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.delenv("CMAPI_KYVERNO_VERSION", raising=False)
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies" / "p.yaml").write_text("apiVersion: kyverno.io/v1\nkind: ClusterPolicy\nmetadata: {name: p}\n")
    v = CliValidator(tmp_path / "policies", policy=PolicySettings(), environments={"dev"})
    [f] = [f for f in v.validate({"clusters/C/namespaces/abc-dev/namespace.yaml":
                                  "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: abc-dev\n"}, "C", "dev")
           if f.source == "kyverno"]
    assert (f.rule, f.kyverno_rule, f.severity) == ("p", "check-team", "warning")
    assert f.view()["kyvernoRule"] == "check-team"


def test_the_readers_role_grants_each_kind_that_the_report_cache_lists_and_watches():
    """CRC's reader had no rule for the reports (design B, M9): the cache's kinds are each granted get, list and watch."""
    from cmapi.core.clients.kube import RESOURCES
    from cmapi.core.clients.policyreports import POLICY_KINDS, REPORT_KINDS

    role_file = Path(__file__).resolve().parents[3] / "deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml"
    role = next(d for d in yaml.safe_load_all(role_file.read_text()) if d and d["kind"] == "ClusterRole")
    granted = {(g, r, v) for rule in role["rules"] for g in rule["apiGroups"] for r in rule["resources"] for v in rule["verbs"]}
    for kind in REPORT_KINDS + POLICY_KINDS:
        path = RESOURCES[kind][0]                       # /apis/<group>/<version>/<plural>
        group, plural = path.split("/")[2], path.rsplit("/", 1)[1]
        assert {(group, plural, v) for v in ("get", "list", "watch")} <= granted, kind
