"""#434: the chart and the plain manifests give the api and the worker the trust of a cluster with no caData, and instance.yaml its
clusterTLS. `helm template` against CRC's values; no cluster. trustedCA.injected is an empty ConfigMap that OpenShift fills, and
trustedCA.existingConfigMap one that an operator makes, never templated from values (docs/18, "Cluster trust")."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART, CRC = ROOT / "deploy/helm/cmapi", ROOT / "deploy/environments/crc.yaml"
MANIFESTS = ROOT / "deploy/manifests"
INJECTED = "/etc/cmapi/trusted-ca/injected/ca-bundle.crt"
CA = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def helm(tmp_path: Path, *sets: str, certificates: bool = True) -> subprocess.CompletedProcess:
    (tmp_path / "ca.crt").write_text(CA)
    args = ["helm", "template", "cmapi", str(CHART), "-n", "cmapi", "-f", str(CRC), "--set", "cmapi.digest=sha256:" + "a" * 64,
            "--set", "cmapi_portal.digest=sha256:" + "b" * 64]
    args += ["--set-file", f"trustedCA.certificates={tmp_path / 'ca.crt'}"] if certificates else ["--set", "trustedCA.certificates="]
    for s in sets:
        args += ["--set-json" if s.startswith("json:") else "--set", s.removeprefix("json:")]
    return subprocess.run(args, capture_output=True, text=True)


def objects(tmp_path: Path, *sets: str, certificates: bool = True) -> list[dict]:
    r = helm(tmp_path, *sets, certificates=certificates)
    assert r.returncode == 0, r.stderr
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def obj(docs: list[dict], kind: str, name: str) -> dict | None:
    return next((d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name), None)


def container(deployment: dict, name: str) -> dict:
    return next(c for c in deployment["spec"]["template"]["spec"]["containers"] if c["name"] == name)


def env(c: dict) -> dict[str, str]:
    return {e["name"]: e.get("value") for e in c.get("env", [])}


def volume(deployment: dict, name: str) -> dict | None:
    return next((v for v in deployment["spec"]["template"]["spec"]["volumes"] if v["name"] == name), None)


WORKLOADS = [("cmapi-api", "api"), ("cmapi-worker", "worker")]


def test_by_default_nothing_changes_but_an_empty_cluster_tls(tmp_path):
    docs = objects(tmp_path)
    assert obj(docs, "ConfigMap", "cmapi-trusted-ca") is None
    for name, c in WORKLOADS:
        d = obj(docs, "Deployment", name)
        assert "CMAPI_TRUSTED_CA_FILE" not in env(container(d, c))
        assert volume(d, "trusted-ca-injected") is None and volume(d, "trusted-ca-operator") is None
    instance = yaml.safe_load(obj(docs, "ConfigMap", "cmapi-config")["data"]["instance.yaml"])["instance"]
    assert instance["clusterTLS"] == {}


def test_the_injected_bundle_is_an_empty_labelled_configmap_mounted_optional(tmp_path):
    docs = objects(tmp_path, "trustedCA.injected.enabled=true")
    cm = obj(docs, "ConfigMap", "cmapi-trusted-ca")
    assert "data" not in cm, "OpenShift writes the data; a chart that ships any is overwritten, or overwrites it"
    assert cm["metadata"]["labels"]["config.openshift.io/inject-trusted-cabundle"] == "true"
    assert cm["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == "ServerSideApply=true"
    for name, c in WORKLOADS:
        d = obj(docs, "Deployment", name)
        assert env(container(d, c))["CMAPI_TRUSTED_CA_FILE"] == INJECTED
        assert volume(d, "trusted-ca-injected")["configMap"] == {"name": "cmapi-trusted-ca", "optional": True}
        assert {"name": "trusted-ca-injected", "mountPath": "/etc/cmapi/trusted-ca/injected", "readOnly": True} in container(d, c)["volumeMounts"]
        # Keycloak keeps its own bundle (D4): the certificates of values, not the injected one.
        assert env(container(d, c))["CMAPI_CA_BUNDLE"] == "/etc/cmapi/ca/ca-bundle.crt"
        assert volume(d, "trust")["projected"]["sources"][0]["configMap"]["name"] == "cmapi-trust"


def test_an_operator_configmap_is_mounted_by_name_and_joined_after_the_injected_one(tmp_path):
    docs = objects(tmp_path, "trustedCA.injected.enabled=true", "trustedCA.existingConfigMap.enabled=true",
                   "trustedCA.existingConfigMap.name=corp-ca", "trustedCA.existingConfigMap.key=root.pem")
    assert obj(docs, "ConfigMap", "corp-ca") is None, "never templated: the operator makes it"
    for name, c in WORKLOADS:
        d = obj(docs, "Deployment", name)
        assert env(container(d, c))["CMAPI_TRUSTED_CA_FILE"] == f"{INJECTED}:/etc/cmapi/trusted-ca/operator/root.pem"
        assert volume(d, "trusted-ca-operator")["configMap"] == {"name": "corp-ca", "items": [{"key": "root.pem", "path": "root.pem"}]}


def test_an_operator_configmap_needs_its_name(tmp_path):
    r = helm(tmp_path, "trustedCA.existingConfigMap.enabled=true")
    assert r.returncode != 0
    assert "trustedCA.existingConfigMap.enabled needs trustedCA.existingConfigMap.name" in r.stderr


def test_injected_alone_is_still_keycloaks_trust_as_before(tmp_path):
    """Before #434, injected.enabled labelled cmapi-trust itself, so Keycloak, Git and the database trusted the cluster bundle.
    With no certificates that stays so, from the new ConfigMap."""
    docs = objects(tmp_path, "trustedCA.injected.enabled=true", certificates=False)
    assert obj(docs, "ConfigMap", "cmapi-trust") is None
    for name, c in WORKLOADS:
        d = obj(docs, "Deployment", name)
        assert env(container(d, c))["CMAPI_CA_BUNDLE"] == "/etc/cmapi/ca/ca-bundle.crt"
        assert volume(d, "trust")["projected"]["sources"][0]["configMap"]["name"] == "cmapi-trusted-ca"


def test_cluster_tls_reaches_instance_yaml(tmp_path):
    docs = objects(tmp_path, 'json:instance.clusterTLS={"environments":{"rnd":{"insecureSkipTLSVerify":true}}}')
    instance = yaml.safe_load(obj(docs, "ConfigMap", "cmapi-config")["data"]["instance.yaml"])["instance"]
    assert instance["clusterTLS"] == {"environments": {"rnd": {"insecureSkipTLSVerify": True}}}


# --------------------------------------------------------------------------- plain manifests


def manifest(path: str) -> dict:
    return yaml.safe_load((MANIFESTS / path).read_text())


@pytest.mark.parametrize("path, c", [("components/cmapi/20-api.yaml", "api"), ("components/cmapi/30-worker.yaml", "worker")])
def test_the_plain_workloads_read_both_bundles_optional(path, c):
    d = next(x for x in yaml.safe_load_all((MANIFESTS / path).read_text()) if x and x["kind"] == "Deployment")
    assert env(container(d, c))["CMAPI_TRUSTED_CA_FILE"] == f"{INJECTED}:/etc/cmapi/trusted-ca/operator/ca-bundle.crt"
    assert volume(d, "trusted-ca-injected")["configMap"] == {"name": "cmapi-trusted-ca", "optional": True}
    assert volume(d, "trusted-ca-operator")["configMap"]["optional"] is True
    mounts = {m["name"]: m for m in container(d, c)["volumeMounts"]}
    assert mounts["trusted-ca-injected"]["readOnly"] and mounts["trusted-ca-operator"]["readOnly"]


def test_crc_ships_the_injected_configmap_empty():
    cm = manifest("environments/crc/35-trusted-ca.yaml")
    assert (cm["kind"], cm["metadata"]["name"], cm["metadata"]["namespace"]) == ("ConfigMap", "cmapi-trusted-ca", "cmapi")
    assert "data" not in cm
    assert cm["metadata"]["labels"]["config.openshift.io/inject-trusted-cabundle"] == "true"
