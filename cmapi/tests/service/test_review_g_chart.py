"""C7, C6, C8, C10: the chart as rendered, the entry points, and what the docs name."""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import tomllib
import importlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
CHART, CRC = ROOT / "deploy/helm/cmapi", ROOT / "deploy/environments/crc.yaml"
PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm")


def render(tmp_path):
    (tmp_path / "ca.crt").write_text(PEM)
    r = subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", "-f", str(CRC), "--set", "cmapi.digest=sha256:" + "a" * 64,
                        "--set-file", f"trustedCA.certificates={tmp_path / 'ca.crt'}"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [d for d in yaml.safe_load_all(r.stdout) if d]


@pytest.fixture
def docs(tmp_path):
    return render(tmp_path)


@pytest.fixture
def deviation(tmp_path):
    """The apply deviation, which CRC's values no longer select: the write identity and its containment policy."""
    (tmp_path / "ca.crt").write_text(PEM)
    r = subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", "-f", str(CRC), "--set", "cmapi.digest=sha256:" + "a" * 64,
                        "--set-file", f"trustedCA.certificates={tmp_path / 'ca.crt'}", "--set", "delivery.mode=apply",
                        "--set", "delivery.hubDeliverer.enabled=true", "--set", "delivery.hubDeliverer.acknowledgeDirectWrites=true"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def find(docs, kind, name=None):
    return [d for d in docs if d["kind"] == kind and (name is None or d["metadata"]["name"] == name)]


def test_only_declared_objects_leave_namespace_cmapi(docs):
    outside = sorted((d["kind"], d["metadata"].get("namespace", "<cluster>"), d["metadata"]["name"]) for d in docs if d["metadata"].get("namespace") != "cmapi")
    print(outside)
    allowed_kc = {("KeycloakRealmImport", "keycloak", "cmapi"), ("Secret", "keycloak", "cmapi-realm-secrets")}
    assert not [o for o in outside if o[1] in ("keycloak", "ldap-testing") and o not in allowed_kc]
    assert not [o for o in outside if o[1] not in ("keycloak", "cmapi-imports", "<cluster>")]


def test_deliverer_cannot_bind_admin_edit_or_view_anywhere(deviation):
    cr = find(deviation, "ClusterRole", "cmapi-deliverer")[0]
    bind = [r for r in cr["rules"] if "bind" in r["verbs"]][0]
    assert set(bind["resourceNames"]) == {"cmapi-token-issuer"}, f"bind on {bind['resourceNames']}: a rolebinding to admin in any namespace, namespace keycloak included"


def test_deliverer_is_contained_by_an_admission_policy(deviation):
    vap = find(deviation, "ValidatingAdmissionPolicy", "cmapi-deliverer-managed-only")
    assert vap, "RBAC alone: create, patch and delete on rolebindings and namespaces in every namespace on a shared cluster"
    assert "system:serviceaccount:cmapi:cmapi-worker" in vap[0]["spec"]["matchConditions"][0]["expression"]
    assert find(deviation, "ValidatingAdmissionPolicyBinding", "cmapi-deliverer-managed-only")[0]["spec"]["validationActions"] == ["Deny"]


def test_api_port_is_not_open_to_every_namespace(docs):
    rules = find(docs, "NetworkPolicy", "cmapi-metrics")[0]["spec"]["ingress"]
    api = [r for r in rules if any(p["port"] == 8080 for p in r["ports"])][0]
    assert api.get("from"), "a rule with no from: any pod on the shared cluster reaches 8080"


def test_every_container_has_requests_and_limits(docs):
    missing = []
    for d in docs:
        if d["kind"] in ("Deployment", "Job"):
            for c in d["spec"]["template"]["spec"]["containers"]:
                res = c.get("resources") or {}
                for side in ("requests", "limits"):
                    for k in ("cpu", "memory"):
                        if k not in (res.get(side) or {}):
                            missing.append((d["kind"], d["metadata"]["name"], side, k))
    db = find(docs, "Cluster", "cmapi-db")[0]["spec"]["resources"]
    if "cpu" not in db.get("limits", {}):
        missing.append(("Cluster", "cmapi-db", "limits", "cpu"))
    assert not missing, missing


def test_restricted_scc_shape(docs):
    for d in docs:
        if d["kind"] in ("Deployment", "Job"):
            pod = d["spec"]["template"]["spec"]
            assert pod["securityContext"]["runAsNonRoot"] is True and "runAsUser" not in pod["securityContext"] and "fsGroup" not in pod["securityContext"]
            assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
            for c in pod["containers"]:
                sc = c["securityContext"]
                assert sc["allowPrivilegeEscalation"] is False and sc["capabilities"]["drop"] == ["ALL"] and "runAsUser" not in sc


def test_no_secret_value_in_values_files():
    bad = []
    for f in [CRC, CHART / "values.yaml"]:
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"(?i)(password|secret|token)\s*:\s*\S+", line) and "Secret" not in line and "#" not in line.split(":")[0]:
                if not re.search(r"directorySecret|credentialSecret|bindSecret|existingSecret|CMAPI_", line):
                    bad.append((f.name, i, line.strip()))
    assert not bad, bad


def test_placeholder_trust_bundle_does_not_render():
    r = subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", "-f", str(CRC), "--set", "cmapi.digest=sha256:" + "a" * 64],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "placeholder" in r.stderr, "the rendered ca-bundle.crt holds the placeholder text; httpx.Client(verify=that) raises SSLError at startup"


def test_release_script_fills_the_trust_bundle_as_crc_yaml_says():
    assert "trustedCA.certificates" in (ROOT / "deploy/release-crc.sh").read_text()


def test_realm_import_grants_the_sync_clients_their_roles(docs):
    realm = find(docs, "KeycloakRealmImport", "cmapi")[0]["spec"]["realm"]
    users = {u["username"]: u for u in realm.get("users", [])}
    assert users.get("service-account-cmapi-realm-admin", {}).get("clientRoles") == {"realm-management": ["realm-admin"]}, \
        "realm_sync signs in as cmapi-realm-admin; nothing grants it realm-admin before its first call"
    assert users["service-account-cmapi-directory"]["clientRoles"] == {"realm-management": ["view-users", "query-users"]}


def test_every_scope_a_client_names_is_defined_in_the_import(docs):
    realm = find(docs, "KeycloakRealmImport", "cmapi")[0]["spec"]["realm"]
    defined = {s["name"] for s in realm["clientScopes"]}
    named = {x for c in realm["clients"] for x in c.get("defaultClientScopes", []) + c.get("optionalClientScopes", [])}
    assert named <= defined, f"named but not defined: {sorted(named - defined)}"


def test_every_console_script_resolves():
    scripts = tomllib.loads((ROOT / "cmapi/pyproject.toml").read_text())["project"]["scripts"]
    bad = []
    for name, target in scripts.items():
        mod = target.split(":")[0]
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            bad.append((name, str(exc)))
    assert not bad, bad


@pytest.mark.parametrize("path,text", [
    ("docs/10-architecture-review.md", "`tests/core/test_auth.py`"),
    ("docs/10-architecture-review.md", "cmapi/tests/core/test_api_contract.py"),
    ("docs/10-architecture-review.md", "proven on kind"),
    ("docs/10-architecture-review.md", "`autoscaling.keda.enabled`"),
    ("docs/10-architecture-review.md", "part of `deploy/check.sh`"),
    ("cmapi/src/cmapi/core/git/github.py", "Proven against a fake transport in the unit tests"),
    ("CRC-BUILD-STATUS.md", "`deploy/release-crc.sh --no-portal` (flag still to add), `helm install cmapi-git`"),
])
def test_docs_do_not_claim_what_is_not_there(path, text):
    assert text not in (ROOT / path).read_text()


def test_image_bakes_the_kubeconform_schemas_by_checksum():
    c = (ROOT / "cmapi/Containerfile").read_text()
    assert "CMAPI_KUBECONFORM_SCHEMAS" in c and "SCHEMAS_COMMIT=" in c and c.count("-v1:") >= 4, \
        "CliValidator then fetches raw.githubusercontent.com/.../master at every plan; CRC-BUILD-STATUS says that is unverified from a pod"


# ---- #205: exact redirect URIs for the public clients

def test_the_chart_gives_the_portal_client_exact_redirect_uris(docs):
    realm = find(docs, "KeycloakRealmImport", "cmapi")[0]["spec"]["realm"]
    portal = next(c for c in realm["clients"] if c["clientId"] == "cmapi-portal")
    assert portal["redirectUris"] == ["https://cmapi-portal.apps-crc.testing/", "https://cmapi-portal.apps-crc.testing/index.html"]
    assert [u for c in realm["clients"] for u in (c.get("redirectUris") or []) if "*" in u] == []


@pytest.mark.parametrize("key,uri,message", [
    ("portalRedirects", "https://cmapi-portal.apps-crc.testing/*", "has a wildcard"),
    ("portalRedirects", "*", "has a wildcard"),
    ("docsRedirects", "https://cmapi-api.apps-crc.testing/docs/*", "has a wildcard"),
    ("portalRedirects", "http://cmapi-portal.apps-crc.testing/", "must be an https URI"),
    ("portalRedirects", "http://localhost.evil.example/", "must be an https URI"),
    ("portalRedirects", "cmapi-portal://callback", "must be an https URI"),
    ("portalRedirects", "https://cmapi-portal.apps-crc.testing/#x", "has a fragment"),
])
def test_the_chart_refuses_a_redirect_uri_that_is_not_exact(tmp_path, key, uri, message):
    (tmp_path / "ca.crt").write_text(PEM)
    r = subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", "-f", str(CRC), "--set", "cmapi.digest=sha256:" + "a" * 64,
                        "--set-file", f"trustedCA.certificates={tmp_path / 'ca.crt'}", "--set-json",
                        f"keycloak.realm.{key}={__import__('json').dumps([uri])}"], capture_output=True, text=True)
    assert r.returncode != 0 and message in r.stderr and f"keycloak.realm.{key}" in r.stderr, r.stderr[-400:]


def test_the_chart_takes_a_localhost_redirect_for_a_local_realm(tmp_path):
    (tmp_path / "ca.crt").write_text(PEM)
    r = subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", "-f", str(CRC), "--set", "cmapi.digest=sha256:" + "a" * 64,
                        "--set-file", f"trustedCA.certificates={tmp_path / 'ca.crt'}", "--set-json",
                        'keycloak.realm.portalRedirects=["http://localhost:5173/","http://127.0.0.1:5173/index.html"]'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
