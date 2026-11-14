"""#226 and #206: the chart's front door. One host for the instance on nginx (cmapi-portal), the API behind it.

What nginx does with these values is measured by deploy/tests/front-door-test.py and the browser check
cmapi-portal-ui/tests/front-door.test.mjs. This file holds the chart to the values that those tests assume.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
CHART, CRC = ROOT / "deploy/helm/cmapi", ROOT / "deploy/environments/crc.yaml"
PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
DIGESTS = ["--set", "cmapi.digest=sha256:" + "a" * 64, "--set", "cmapi_portal.digest=sha256:" + "b" * 64,
           "--set", "argocd.controllerServiceAccount=system:serviceaccount:cmapi-argocd:argocd-application-controller"]
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm")


def helm(tmp_path, *args: str) -> subprocess.CompletedProcess:
    (tmp_path / "ca.crt").write_text(PEM)
    return subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", *DIGESTS,
                           "--set-file", f"trustedCA.certificates={tmp_path / 'ca.crt'}", *args],
                          capture_output=True, text=True, timeout=120)


def render(tmp_path, *args: str) -> list[dict]:
    r = helm(tmp_path, *args)
    assert r.returncode == 0, r.stderr
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def find(docs: list[dict], kind: str, name: str | None = None) -> list[dict]:
    return [d for d in docs if d["kind"] == kind and (name is None or d["metadata"]["name"] == name)]


def env_of(docs: list[dict]) -> dict[str, str]:
    container = find(docs, "Deployment", "cmapi-portal")[0]["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e["value"] for e in container["env"]}


@pytest.fixture
def crc(tmp_path) -> list[dict]:
    return render(tmp_path, "-f", str(CRC))


def test_crc_has_one_host_for_the_instance_and_one_for_the_mockup(crc):
    routes = {r["metadata"]["name"]: r["spec"] for r in find(crc, "Route")}
    assert set(routes) == {"cmapi", "cmapi-mockup"}
    assert routes["cmapi"]["host"] == "cmapi.apps-crc.testing" and routes["cmapi-mockup"]["host"] == "cmapi-mockup.apps-crc.testing"
    for spec in routes.values():
        assert spec["to"] == {"kind": "Service", "name": "cmapi-portal"}, "every host goes to the front door"
        assert spec["tls"] == {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"}


def test_no_route_or_ingress_reaches_the_api_around_the_front_door(tmp_path):
    for args in (["-f", str(CRC)], ["--set", "instance.publicUrl=https://cmapi.example", "--set", "exposure=Ingress",
                                    "--set", "ingress.host=cmapi.example", "--set", "ingress.mockup.host=mockup.example"]):
        docs = render(tmp_path, *args)
        backends = [r["spec"]["to"]["name"] for r in find(docs, "Route")]
        backends += [p["backend"]["service"]["name"] for i in find(docs, "Ingress") for rule in i["spec"]["rules"] for p in rule["http"]["paths"]]
        assert backends and set(backends) == {"cmapi-portal"}, backends


def test_the_front_door_gets_the_api_pods_the_hosts_and_the_issuer_origin(crc):
    assert env_of(crc) == {
        "CMAPI_API_UPSTREAM": "cmapi-api-pods.cmapi.svc.cluster.local:8080",
        "CMAPI_PORTAL_HOST": "cmapi.apps-crc.testing",
        "CMAPI_MOCKUP_HOST": "cmapi-mockup.apps-crc.testing",
        "CMAPI_OIDC_ORIGIN": "https://keycloak.apps-crc.testing",
    }


def test_a_route_with_no_host_gives_nginx_a_wildcard_server_name(tmp_path):
    docs = render(tmp_path, "--set", "instance.publicUrl=https://cmapi.apps.example", "--set", "clusterDomain=cluster.example")
    routes = {r["metadata"]["name"]: r["spec"] for r in find(docs, "Route")}
    assert routes["cmapi"].get("subdomain") == "cmapi" and "host" not in routes["cmapi"]
    env = env_of(docs)
    assert env["CMAPI_PORTAL_HOST"] == "cmapi.*" and env["CMAPI_MOCKUP_HOST"] == "cmapi-mockup.*"
    assert env["CMAPI_API_UPSTREAM"] == "cmapi-api-pods.cmapi.svc.cluster.example:8080"


def test_the_headless_service_selects_the_api_pods(crc):
    svc = find(crc, "Service", "cmapi-api-pods")[0]["spec"]
    api = find(crc, "Deployment", "cmapi-api")[0]["spec"]["template"]["metadata"]["labels"]
    assert svc["clusterIP"] == "None"
    assert svc["selector"].items() <= api.items() and svc["selector"]["app.kubernetes.io/component"] == "api"
    assert svc["ports"] == [{"name": "http", "port": 8080, "targetPort": "http"}]


def test_the_portal_calls_the_api_on_its_own_origin(crc):
    config = json.loads(find(crc, "ConfigMap", "cmapi-portal-config")[0]["data"]["config.json"])
    assert config["apiUrl"] == "https://cmapi.apps-crc.testing"
    assert config["issuer"] == "https://keycloak.apps-crc.testing/realms/cmapi"


def test_the_instance_url_is_the_front_door_for_the_realm_and_the_api(crc):
    realm = find(crc, "KeycloakRealmImport", "cmapi")[0]["spec"]["realm"]
    clients = {c["clientId"]: c for c in realm["clients"]}
    assert clients["cmapi-portal"]["redirectUris"] == ["https://cmapi.apps-crc.testing/", "https://cmapi.apps-crc.testing/index.html"]
    assert clients["cmapi-docs"]["redirectUris"] == ["https://cmapi.apps-crc.testing/docs/oauth2-redirect"]
    instance = yaml.safe_load(find(crc, "ConfigMap", "cmapi-config")[0]["data"]["instance.yaml"])["instance"]
    assert instance["publicUrl"] == instance["portalUrl"] == "https://cmapi.apps-crc.testing"


def test_only_the_front_door_reaches_the_api_port(crc):
    rules = find(crc, "NetworkPolicy", "cmapi-metrics")[0]["spec"]["ingress"]
    api_port = [r for r in rules if r["ports"] == [{"port": 8080, "protocol": "TCP"}]]
    assert len(api_port) == 1
    assert api_port[0]["from"] == [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "cmapi-portal", "app.kubernetes.io/component": "portal"}}}]
    door = find(crc, "NetworkPolicy", "cmapi-front-door")[0]["spec"]
    assert door["podSelector"]["matchLabels"]["app.kubernetes.io/component"] == "portal"
    assert door["ingress"] == [{"from": [{"namespaceSelector": {"matchLabels": {"policy-group.network.openshift.io/ingress": ""}}}],
                                "ports": [{"port": 8080, "protocol": "TCP"}]}]


def test_the_front_door_stops_gracefully_within_the_grace_period(crc):
    pod = find(crc, "Deployment", "cmapi-portal")[0]["spec"]["template"]["spec"]
    c = pod["containers"][0]
    assert c["lifecycle"]["preStop"]["exec"]["command"][-1].startswith("sleep 5; nginx -s quit;")
    # 5 s of preStop and nginx's worker_shutdown_timeout of 20 s (cmapi-portal-ui/nginx/nginx.conf) fit in the grace period.
    assert "worker_shutdown_timeout 20s;" in (ROOT / "cmapi-portal-ui/nginx/nginx.conf").read_text()
    assert pod["terminationGracePeriodSeconds"] >= 5 + 20
    assert c["readinessProbe"]["httpGet"] == {"path": "/healthz", "port": "http"}


def test_the_front_door_needs_the_instance_url_and_ingress_needs_a_host(tmp_path):
    r = helm(tmp_path)
    assert r.returncode != 0 and "instance.publicUrl is required" in r.stderr
    r = helm(tmp_path, "--set", "instance.publicUrl=https://cmapi.example", "--set", "exposure=Ingress")
    assert r.returncode != 0 and "ingress.host is required" in r.stderr


def test_with_the_front_door_off_nothing_is_exposed(tmp_path):
    docs = render(tmp_path, "-f", str(CRC), "--set", "portal.enabled=false")
    assert find(docs, "Route") == [] and find(docs, "Ingress") == [] and find(docs, "Deployment", "cmapi-portal") == []
