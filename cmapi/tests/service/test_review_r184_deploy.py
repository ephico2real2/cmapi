"""#184 (SEC-07), Codex's review, C4, C7 and E2: the realm files, the chart and the order of the CRC run. Render and read only: no cluster."""
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
RFC9068_HEADER = "access.token.header.type.rfc9068"
needs_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm")


def helm_template(*sets):
    args = ["helm", "template", "cmapi", str(ROOT / "deploy/helm/cmapi"), "-f", str(ROOT / "deploy/environments/crc.yaml"),
            "--set", "cmapi.digest=sha256:" + "a" * 64, "--set", "trustedCA.certificates=x"]
    for s in sets:
        args += ["--set", s]
    return [d for d in yaml.safe_load_all(subprocess.run(args, check=True, capture_output=True, text=True).stdout) if d]


@pytest.mark.parametrize("deployment", ["crc", pytest.param("helm", marks=needs_helm)])
def test_c4_the_api_client_of_the_realm_has_the_rfc9068_header_type(deployment):
    """Keycloak's V1 token exchange encodes the token in the context of the target client (V1TokenExchangeProvider.setClientToContext,
    26.6.4), so the audience client decides the header there. The realm files turn no exchange on: this keeps the import equal to
    what the sync writes."""
    if deployment == "crc":
        docs = [d for d in yaml.safe_load_all((ROOT / "deploy/manifests/environments/crc/realm/10-realm-import.yaml").read_text()) if d]
    else:
        docs = helm_template("keycloak.realmImport.enabled=true")
    realm = next(d["spec"]["realm"] for d in docs if d.get("kind") == "KeycloakRealmImport")
    target = next(c for c in realm["clients"] if c.get("bearerOnly"))
    assert "cmapi-audience" in target["defaultClientScopes"]
    assert (target.get("attributes") or {}).get(RFC9068_HEADER) == "true", (
        f"V1 exchange uses target client {target['clientId']}, whose header defaults to JWT")


@needs_helm
@pytest.mark.parametrize("enabled", [False, True])
def test_e2_the_chart_renders_the_legacy_token_setting(enabled):
    """docs/15 names auth.acceptLegacyTokenType, and core/context.py reads it from instance.yaml, so the chart must write it there."""
    config = next(d for d in helm_template(f"auth.acceptLegacyTokenType={str(enabled).lower()}")
                  if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "cmapi-config")
    auth = yaml.safe_load(config["data"]["instance.yaml"])["instance"]["auth"]
    assert auth.get("acceptLegacyTokenType", False) is enabled


def test_c7_the_realm_sync_completes_before_the_workloads_roll_out():
    """The API refuses a token that the realm does not type yet, and a token has no employee_id before the sync. So the run
    finishes the sync, and stops on its failure, before it applies the API."""
    doc = (ROOT / "docs/13-crc-deployment.md").read_text()
    apply_api = doc.index('oc apply --server-side --field-manager=cmapi-wave1 -R -f "$R/components/cmapi"')
    apply_sync = doc.index('oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/realm/20-realm-sync.yaml"')
    wait_sync = doc.index("oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete")
    assert apply_sync < wait_sync < apply_api, "the API starts before the realm sync is complete"
    assert '[ "$rc" = 0 ]' in doc[wait_sync:apply_api], "a failed sync must stop the rollout"
