"""The guards the chart's reviews earned, on the plain manifests (deploy/manifests): the chart tests read helm's output, so
nothing reads these files until the charts are removed. Ruling 3 of the deployment design: reviewed guards do not leave with
the charts. Static: no cluster, no database."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPONENTS = ROOT / "deploy/manifests/components"
PLACEHOLDER = "ghcr.io/ephico2real2/cmapi@sha256:DIGEST"
TRUST = "/etc/cmapi/ca/ca-bundle.crt"
CHECKSUM_PLACEHOLDER = "CMAPI_CONFIG_CHECKSUM"


def docs():
    for f in sorted(COMPONENTS.rglob("*.yaml")):
        for d in yaml.safe_load_all(f.read_text()):
            if d:
                yield d


def workload(name):
    return next(d for d in docs() if d["kind"] == "Deployment" and d["metadata"]["name"] == name)["spec"]["template"]["spec"]


def deployments():
    return [d for d in docs() if d["kind"] == "Deployment"]


def env(container):
    return {e["name"]: e for e in container.get("env", [])}


def pod_annotations(name):
    d = next(d for d in deployments() if d["metadata"]["name"] == name)
    return d["spec"]["template"]["metadata"].get("annotations") or {}


@pytest.mark.parametrize("name", ["cmapi-api", "cmapi-worker"])
def test_a_changed_configuration_changes_the_pod_template(name):
    """The process reads its configuration once, at start, and the ConfigMaps are mutable, so without this a changed one leaves
    the running pods on the old values. deploy/render-test.sh proves the fill; this proves the two Deployments ask for it."""
    assert pod_annotations(name)["checksum/config"] == CHECKSUM_PLACEHOLDER


def test_the_mockup_reads_none_of_that_configuration():
    assert "checksum/config" not in pod_annotations("cmapi-mockup")


def test_api_port_is_not_open_to_every_namespace():
    policy = next(d for d in docs() if d["kind"] == "NetworkPolicy" and d["metadata"]["name"] == "cmapi-metrics")
    api = next(r for r in policy["spec"]["ingress"] if any(p["port"] == 8080 for p in r["ports"]))
    assert api.get("from"), "a rule with no from: any pod on the shared cluster reaches 8080"
    # Whole, not "the router's label is among them": an added peer with an empty namespaceSelector would match every namespace
    # and still hold that label's peer.
    assert api["from"] == [
        {"namespaceSelector": {"matchLabels": {"policy-group.network.openshift.io/ingress": ""}}},
        {"podSelector": {}},
    ]


@pytest.mark.parametrize("name", ["cmapi-api", "cmapi-worker"])
def test_both_workloads_migrate_first_trusting_what_the_main_container_trusts(name):
    spec = workload(name)
    init = spec["initContainers"][0]
    assert init["command"] == ["cmapi-migrate", "head"]
    e = env(init)
    assert e["SSL_CERT_FILE"]["value"] == TRUST
    assert "PGSSLROOTCERT" not in e, "with CNPG's URI and a bundle without its CA, libpq falls back to plaintext (measured)"
    assert {"name": "trust", "mountPath": "/etc/cmapi/ca", "readOnly": True} in init["volumeMounts"]
    main = spec["containers"][0]
    assert {"name": "trust", "mountPath": "/etc/cmapi/ca", "readOnly": True} in main["volumeMounts"]
    assert env(main)["CMAPI_CA_BUNDLE"]["value"] == TRUST


@pytest.mark.parametrize("name", ["cmapi-api", "cmapi-worker"])
def test_the_database_url_comes_from_the_one_secret_key(name):
    spec = workload(name)
    for c in spec["initContainers"] + spec["containers"]:
        assert env(c)["CMAPI_DATABASE_URL"]["valueFrom"]["secretKeyRef"] == {"name": "cmapi-db-app", "key": "uri"}, c["name"]


def test_readiness_is_the_schema_and_liveness_does_no_io():
    api = workload("cmapi-api")["containers"][0]
    assert api["readinessProbe"]["httpGet"]["path"] == "/readyz" and api["startupProbe"]["httpGet"]["path"] == "/readyz"
    assert api["livenessProbe"]["httpGet"]["path"] == "/api/v1/version"


def test_every_container_has_requests_limits_and_the_restricted_shape():
    for d in deployments():
        pod = d["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsNonRoot"] is True and pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        assert "runAsUser" not in pod["securityContext"] and "fsGroup" not in pod["securityContext"]
        for c in pod.get("initContainers", []) + pod["containers"]:
            for side in ("requests", "limits"):
                assert {"cpu", "memory"} <= set(c["resources"][side]), (d["metadata"]["name"], c["name"], side)
            sc = c["securityContext"]
            assert sc["allowPrivilegeEscalation"] is False and sc["capabilities"]["drop"] == ["ALL"] and "runAsUser" not in sc


def test_every_image_is_the_placeholder_or_a_digest():
    for d in deployments():
        pod = d["spec"]["template"]["spec"]
        for c in pod.get("initContainers", []) + pod["containers"]:
            assert c["image"] == PLACEHOLDER or "@sha256:" in c["image"], c["image"]


def test_the_database_keeps_itself_and_names_no_storage_class():
    cluster = next(d for d in docs() if d["kind"] == "Cluster")
    assert set(cluster["metadata"]["annotations"]["argocd.argoproj.io/sync-options"].split(",")) >= {"Prune=false", "Delete=false"}
    assert "@sha256:" in cluster["spec"]["imageName"] and "storageClass" not in cluster["spec"]["storage"]


def test_nothing_here_is_kind_only_or_a_secret():
    assert not [d["metadata"]["name"] for d in docs() if d["kind"] in ("Secret", "Namespace")]
