"""The kind proof of #302: the service's real KubeClient, registry, ReportCache and router, against the cmapi-test kind
cluster through the cmapi-reader of deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml, with Kyverno v1.20.0
in audit and the dev bundle that cmapi renders (examples/cluster-configs/policies/env/dev).

Only the Git host and the validator are the suite's fakes (no cluster write goes through cmapi here). The API is called
through FastAPI's TestClient, signed with the suite's test keys. Each phase prints its JSON to the log.

    PHASE=all PYTHONPATH=<wt>/cmapi/src:<wt>/cmapi/tests/service python -m pytest -s -q test_kind_proof_302.py
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from pathlib import Path

import yaml

from cmapi.core.clients.kube import KubeClient
from cmapi.core.registry import ImportSource
from conftest import build_world, database, fresh_db, keys, test_config  # noqa: F401  (pytest fixtures)
from test_flow import OLA, auth

HERE = Path(__file__).parent
WT = Path("/Users/olasumbo/gitRepos/workbench/cmapi/wt-302p")
KYVERNO_INSTALL = Path("/Users/olasumbo/gitRepos/workbench/cmapi/ob-333/kind/install.yaml")
K = ["kubectl", "--kubeconfig", str(HERE / "kubeconfig")]


def kubectl(*args: str, check: bool = True, stdin: str | None = None) -> str:
    r = subprocess.run([*K, *args], capture_output=True, text=True, input=stdin)
    if check and r.returncode != 0:
        raise AssertionError(f"kubectl {' '.join(args)}: {r.stderr[-400:]}")
    return r.stdout


def say(title: str, value) -> None:
    print(f"\n== {title}\n{value if isinstance(value, str) else json.dumps(value, indent=1, default=str)}", flush=True)


class KindSecret(ImportSource):
    """The import Secret of the reader, as deploy/crc-reader-import.sh writes it: the API URL, the token and the CA."""

    def __init__(self, api_url: str, token: str, ca: str):
        self.data = {"apiUrl": api_url, "token": token, "caData": ca}

    def list(self):
        return [{"name": "cmapi-cluster-kind", "labels": {"cmapi.net/secret-type": "cluster", "cmapi.net/cluster-id": "CRC"},
                 "annotations": {}, "data": self.data}]


def wait_for(what: str, test, timeout: float = 300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = test()
        if got:
            return got
        time.sleep(3)
    raise AssertionError(f"{what}: not within {timeout} s")


def test_kind_proof(test_config, fresh_db, keys, monkeypatch):  # noqa: F811
    kubectl("apply", "--server-side", "-f", str(WT / "deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml"))
    token = wait_for("the reader's token", lambda: json.loads(kubectl("get", "secret", "cmapi-reader-token", "-n", "cmapi-system",
                                                                          "-o", "json")).get("data", {}).get("token"))
    cfg = yaml.safe_load(Path(HERE / "kubeconfig").read_text())
    cluster = cfg["clusters"][0]["cluster"]
    api_url, ca = cluster["server"], base64.b64decode(cluster["certificate-authority-data"]).decode()
    with build_world(test_config, keys, monkeypatch) as (client, ctx, git, kube, validator, keys):
        ctx.registry.source = KindSecret(api_url, base64.b64decode(token).decode(), ca)
        ctx.registry.client_factory = KubeClient
        ctx.registry._fingerprints.clear()
        ctx.registry.clusters["CRC"].client = None
        ctx.registry.refresh()
        st = ctx.registry.clusters["CRC"]
        say("the six checks against kind, as cmapi-reader", {"status": st.status, "findings": st.findings, "version": st.server_version})
        assert st.status == "connected", st.findings
        reports = st.reports
        reports.PROBE_SECONDS = 5

        def results(q: str = ""):
            r = client.get(f"/api/v1/policies/results{q}", headers=auth(keys, "ola", **OLA))
            assert r.status_code == 200, r.text
            return r.json()

        phase = os.environ.get("PHASE", "all")
        if phase in ("all", "before"):
            body = wait_for("a first discovery", lambda: (lambda b: b if b["clusters"][0]["state"] != "loading" else None)(results()), 60)
            say("1. no Kyverno on the cluster: GET /api/v1/policies/results", body["clusters"])
            assert body["clusters"][0]["state"] == "not-installed" and body["clusters"][0]["counts"] is None

        say("install Kyverno v1.20.0 (install.yaml of #333, sha256 in docs/reviews/2026-11-17-issue-333/evidence/kind)",
            kubectl("create", "-f", str(KYVERNO_INSTALL), check=False)[-300:])
        kubectl("-n", "kyverno", "rollout", "status", "deploy", "--timeout=300s")
        say("Kyverno's images", kubectl("-n", "kyverno", "get", "deploy", "-o", "custom-columns=NAME:.metadata.name,IMAGE:.spec.template.spec.containers[0].image"))
        bundle = WT / "examples/cluster-configs/policies/env/dev"
        for f in sorted(bundle.glob("*.yaml")):
            kubectl("apply", "-f", str(f))
        say("the dev bundle, rendered by cmapi with cmapi.net/policy-digest", kubectl("get", "validatingpolicies.policies.kyverno.io", "--no-headers").count("\n"))
        time.sleep(15)     # the admission webhook's policy cache (#333's proof)
        ns = yaml.safe_load((HERE.parent.parent / "ob-333/kind/after/ns-orders-dev.yaml").read_text())
        kubectl("apply", "-f", "-", stdin=yaml.safe_dump(ns))
        say("a change outside cmapi: kubectl label namespace orders-dev other.example/x=1",
            subprocess.run([*K, "label", "namespace", "orders-dev", "other.example/x=1", "--overwrite"], capture_output=True, text=True).stderr
            + kubectl("get", "ns", "orders-dev", "-o", "jsonpath={.metadata.labels}"))
        ctx.registry.cache("CRC")._list("Namespace")      # the fake world's core watch is replaced; the report watch is live

        def failing():
            ctx.registry.cache("CRC")._list("Namespace")
            b = results()
            c = b["clusters"][0]
            return b if c["state"] in ("ok", "drift") and any(i["namespace"] == "orders-dev" for i in b["items"]) else None
        body = wait_for("the background scan's fail in the API", failing, 420)
        say("2. Kyverno in audit: the cluster", body["clusters"])
        say("2. the row of orders-dev", [i for i in body["items"] if i["namespace"] == "orders-dev"])
        row = next(i for i in body["items"] if i["namespace"] == "orders-dev" and i["policy"].endswith("label-other-keys-prefix"))
        assert row["rule"] == "prefix" and row["result"] == "fail" and "other.example/x" in row["message"], row
        cl = body["clusters"][0]
        assert cl["state"] == "ok" and cl["bundle"]["current"] == cl["bundle"]["expected"] and cl["liveActions"] == ["Audit", "Warn"], cl
        say("the cluster's own report, for comparison", kubectl("get", "clusterpolicyreports.wgpolicyk8s.io", "-o",
                                                               "jsonpath={range .items[?(@.scope.name==\"orders-dev\")].results[?(@.result==\"fail\")]}{.policy} {.rule} {.result} {.message}{\"\\n\"}{end}"))

        # 3. Drift: one policy edited on the cluster, outside the render.
        name = row["policy"]
        kubectl("annotate", "validatingpolicies.policies.kyverno.io", name, "cmapi.net/policy-digest=edited-by-hand", "--overwrite")
        body = wait_for("the drift", lambda: (lambda b: b if b["clusters"][0]["state"] == "drift" else None)(results()), 120)
        say("3. a policy edited on the cluster: drift", body["clusters"][0])
        assert body["clusters"][0]["bundle"]["differing"] == [name]

        # 4. The reader without its report rule: forbidden, never "not installed" and never zero.
        role = kubectl("get", "clusterrole", "cmapi-reader", "-o", "json")
        cut = json.loads(role)
        cut["rules"] = [r for r in cut["rules"] if "wgpolicyk8s.io" not in r["apiGroups"]]
        for k in ("resourceVersion", "uid", "creationTimestamp", "managedFields"):
            cut["metadata"].pop(k, None)
        kubectl("replace", "-f", "-", stdin=json.dumps(cut))
        reports.sync()
        body = results()
        say("4. the reader's report rule removed", body["clusters"][0])
        assert body["clusters"][0]["state"] == "forbidden" and body["clusters"][0]["counts"] is None
        kubectl("apply", "--server-side", "--force-conflicts", "-f", str(WT / "deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml"))
        ctx.registry.stop()
