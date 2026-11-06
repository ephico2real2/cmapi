"""The guards the chart's reviews earned, on the plain manifests (deploy/manifests): the chart tests read helm's output, so
nothing reads these files until the charts are removed. Ruling 3 of the deployment design: reviewed guards do not leave with
the charts. Static: no cluster, no database."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPONENTS = ROOT / "deploy/manifests/components"
PLACEHOLDER = "ghcr.io/ephico2real2/cmapi@sha256:DIGEST"
TRUST = "/etc/cmapi/ca/ca-bundle.crt"
CHECKSUM_PLACEHOLDER = "CMAPI_CONFIG_CHECKSUM"
# The only images here that are not cmapi's, by repository. A digest bump changes nothing; a new repository is a decision.
OTHER_IMAGES = {"docker.io/nginxinc/nginx-unprivileged", "ghcr.io/cloudnative-pg/postgresql:17"}


def docs():
    # .yml too: kubectl apply -R and Argo CD take it, and render.sh only refuses one that holds a placeholder.
    for f in sorted([*COMPONENTS.rglob("*.yaml"), *COMPONENTS.rglob("*.yml")]):
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


def test_the_readme_says_the_configuration_goes_first():
    """The checksum makes a restart, it does not order one: pods restarted before the ConfigMap changes keep the old values."""
    text = " ".join((ROOT / "deploy/manifests/README.md").read_text().split())
    assert "apply the environment, then the components, in that order" in text


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


def images(node):
    """Every image and imageName under an object, whatever its kind: a Job or a sidecar runs an image as well."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("image", "imageName") and isinstance(value, str):
                yield value
            else:
                yield from images(value)
    elif isinstance(node, list):
        for value in node:
            yield from images(value)


def image_problems(objects):
    """The api and the worker run the placeholder and nothing else, so render.sh decides what they run. Anything else is the
    placeholder or a known repository pinned by a whole digest. Against a mistake (a digest pinned while debugging, a forgotten
    tag), not an attacker: whoever can edit the manifests in a pull request can edit this too, and review is what stops them."""
    problems = []
    for d in objects:
        name = d["metadata"]["name"]
        for image in images(d):
            repository, _, digest = image.partition("@sha256:")
            pinned = repository in OTHER_IMAGES and re.fullmatch(r"[0-9a-f]{64}", digest)
            ours = d["kind"] == "Deployment" and name in ("cmapi-api", "cmapi-worker")
            if image != PLACEHOLDER and (ours or not pinned):
                problems.append(f"{d['kind']}/{name}: {image}")
    return problems


def test_every_image_is_the_placeholder_or_a_known_digest():
    objects = list(docs())
    assert image_problems(objects) == []
    assert sum(1 for d in objects for image in images(d) if image == PLACEHOLDER) == 4, "two Deployments, each a migrate and a main container"


EVIL = "ghcr.io/evil/cmapi@sha256:" + "e" * 64


def _containers(objects, name):
    pod = next(d for d in objects if d["kind"] == "Deployment" and d["metadata"]["name"] == name)["spec"]["template"]["spec"]
    return pod.get("initContainers", []) + pod["containers"]


@pytest.mark.parametrize("change", [
    pytest.param(lambda o: _containers(o, "cmapi-api")[0].update(image=EVIL), id="the api's migrate container"),
    pytest.param(lambda o: _containers(o, "cmapi-worker")[1].update(image=EVIL), id="the worker's main container"),
    pytest.param(lambda o: _containers(o, "cmapi-mockup")[0].update(image=EVIL), id="the mockup, another repository"),
    pytest.param(lambda o: _containers(o, "cmapi-mockup")[0].update(image="docker.io/nginxinc/nginx-unprivileged:latest"), id="the mockup, a tag"),
    pytest.param(lambda o: _containers(o, "cmapi-mockup")[0].update(image="docker.io/nginxinc/nginx-unprivileged@sha256:abc"), id="the mockup, a short digest"),
    pytest.param(lambda o: next(d for d in o if d["kind"] == "Cluster")["spec"].update(imageName="ghcr.io/cloudnative-pg/postgresql:17"), id="the database, a tag"),
    pytest.param(lambda o: o.append({"kind": "Job", "metadata": {"name": "x"}, "spec": {"template": {"spec": {"containers": [{"name": "x", "image": EVIL}]}}}}), id="a Job"),
])
def test_the_image_guard_can_fail(change):
    objects = list(docs())
    assert image_problems(objects) == []
    change(objects)
    assert image_problems(objects), "the guard let this through"


def test_the_database_keeps_itself_and_names_no_storage_class():
    cluster = next(d for d in docs() if d["kind"] == "Cluster")
    assert set(cluster["metadata"]["annotations"]["argocd.argoproj.io/sync-options"].split(",")) >= {"Prune=false", "Delete=false"}
    assert "@sha256:" in cluster["spec"]["imageName"] and "storageClass" not in cluster["spec"]["storage"]


def test_nothing_here_is_kind_only_or_a_secret():
    assert not [d["metadata"]["name"] for d in docs() if d["kind"] in ("Secret", "Namespace")]


# ---------------------------------------------------------------- environments/crc (Wave 1)
CRC = ROOT / "deploy/manifests/environments/crc"


def crc_docs(pattern="**/*.yaml"):
    for f in sorted(CRC.glob(pattern)):
        for d in yaml.safe_load_all(f.read_text()):
            if d:
                yield d


def crc(kind, name):
    return next(d for d in crc_docs() if d["kind"] == kind and d["metadata"]["name"] == name)


def config_file(env, name):
    root = ROOT / "deploy/manifests/environments" / env / "20-config.yaml"
    return next(yaml.safe_load_all(root.read_text()))["data"][name]


def test_crc_has_exactly_one_more_image_placeholder_and_it_is_the_realm_sync():
    """Ruling: a Job on this image is a decision. components stays at four (test_every_image_is_the_placeholder_or_a_known_digest); CRC adds the realm sync, nothing else."""
    found = [(d["kind"], d["metadata"]["name"]) for d in crc_docs() for image in images(d) if image == PLACEHOLDER]
    assert found == [("Job", "cmapi-realm-sync")]
    assert [i for d in crc_docs() for i in images(d) if i != PLACEHOLDER] == []


@pytest.mark.parametrize("name", ["approval-rules.yaml", "authz-roles.yaml", "tiers.yaml", "expiration.yaml", "metadata-keys.yaml", "capacity.yaml"])
def test_crc_policy_files_are_the_kind_files(name):
    assert config_file("crc", name) == config_file("kind", name)


def test_crc_nothing_can_write_or_reach_a_git_host_in_wave_1():
    """No GitHub until Wave 3 and no Argo CD until Wave 5: delivery stays argocd, so the worker never writes to a cluster, the one cluster refuses writes, and the Git URL cannot resolve."""
    integrations = yaml.safe_load(config_file("crc", "integrations.yaml"))
    clusters = yaml.safe_load(config_file("crc", "clusters.yaml"))["clusters"]
    assert integrations["delivery"]["mode"] == "argocd"
    assert list(clusters) == ["CRC"] and clusters["CRC"]["writes"] is False and "delivery" not in clusters["CRC"]
    env = crc("ConfigMap", "cmapi-env")["data"]
    assert env["CMAPI_GIT_PROVIDER"] == "github", "settings.py's default is the provider that is leaving"
    assert env["CMAPI_GIT_URL"].endswith(".invalid"), "RFC 6761: it can never resolve"
    text = "\n".join(p.read_text() for p in CRC.rglob("*.yaml")).lower()
    assert "gitea" not in text and "cmapi-git" not in text


def test_crc_pods_reach_keycloak_by_its_service_and_tokens_carry_the_route():
    env = crc("ConfigMap", "cmapi-env")["data"]
    assert env["CMAPI_OIDC_JWKS_URL"] == "https://keycloak-service.keycloak.svc:8443/realms/cmapi/protocol/openid-connect/certs"
    assert env["CMAPI_KEYCLOAK_ADMIN_URL"] == "https://keycloak-service.keycloak.svc:8443"
    assert yaml.safe_load(config_file("crc", "instance.yaml"))["instance"]["auth"]["issuer"] == "https://keycloak.apps-crc.testing/realms/cmapi"


def test_crc_routes():
    """kubeconform skips Route: the pinned CRDs catalog has no schema for it (404, measured). So its shape is held here."""
    routes = {d["metadata"]["name"]: d["spec"] for d in crc_docs() if d["kind"] == "Route"}
    assert set(routes) == {"cmapi-api", "cmapi-mockup"}, "no portal Route: the portal does not run on the API yet"
    for name, spec in routes.items():
        assert set(spec) == {"host", "to", "port", "tls"}
        assert spec["host"] == f"{name}.apps-crc.testing"
        assert spec["to"] == {"kind": "Service", "name": name}
        assert spec["port"] == {"targetPort": "http"}, "never the metrics port"
        assert spec["tls"] == {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"}


def test_crc_redirect_uri_is_the_docs_route():
    realm = crc("KeycloakRealmImport", "cmapi")["spec"]["realm"]
    docs_client = next(c for c in realm["clients"] if c["clientId"] == "cmapi-docs")
    host = crc("Route", "cmapi-api")["spec"]["host"]
    assert docs_client["redirectUris"] == [f"https://{host}/docs/oauth2-redirect"]
    assert yaml.safe_load(config_file("crc", "instance.yaml"))["instance"]["publicUrl"] == f"https://{host}"


def test_crc_realm_import_names_cmapi_and_holds_no_secret():
    kri = crc("KeycloakRealmImport", "cmapi")
    assert (kri["metadata"]["name"], kri["metadata"]["namespace"]) == ("cmapi", "keycloak")
    spec = kri["spec"]
    assert spec["keycloakCRName"] == "keycloak" and spec["realm"]["realm"] == "cmapi" and "id" not in spec["realm"]
    # Without this the operator asks for 1700Mi (Utils.addResources), which with cmapi's 576 Mi is under the stop line.
    assert spec["resources"] == {"requests": {"cpu": "100m", "memory": "768Mi"}, "limits": {"cpu": "1", "memory": "1Gi"}}
    assert {p["secret"]["name"] for p in spec["placeholders"].values()} == {"cmapi-realm-secrets"}
    confidential = [c for c in spec["realm"]["clients"] if "secret" in c]
    assert confidential and all(c["secret"] == "${%s}" % next(k for k in spec["placeholders"] if k in c["secret"]) for c in confidential)
    assert len(list(yaml.safe_load_all((CRC / "realm/10-realm-import.yaml").read_text()))) == 1


def test_crc_realm_takes_a_password_only_through_the_automation_client_and_limits_guesses():
    """A public client with direct grants takes a person's password with no secret. Keycloak gives every realm one, admin-cli, unless the import names it. Measured in deploy/tests/realm-test.py."""
    realm = crc("KeycloakRealmImport", "cmapi")["spec"]["realm"]
    direct = [c["clientId"] for c in realm["clients"] if c.get("directAccessGrantsEnabled") and c.get("enabled")]
    assert direct == ["cmapi-automation"]
    admin_cli = next(c for c in realm["clients"] if c["clientId"] == "admin-cli")
    assert admin_cli["enabled"] is False and admin_cli["directAccessGrantsEnabled"] is False
    assert realm["bruteForceProtected"] is True and realm["permanentLockout"] is False


def test_crc_realm_sync_is_one_try_and_requires_the_federation():
    job = crc("Job", "cmapi-realm-sync")["spec"]
    assert job["backoffLimit"] == 0 and job["template"]["spec"]["restartPolicy"] == "Never", "no retries against a Keycloak that is down"
    assert job["activeDeadlineSeconds"] <= 600
    container = job["template"]["spec"]["containers"][0]
    e = env(container)
    assert e["CMAPI_REALM_ADMIN_URL"]["value"].startswith("https://keycloak-service.keycloak.svc")
    ldap = __import__("json").loads(e["CMAPI_REALM_LDAP"]["value"])
    assert ldap["requireSync"] is True and ldap["groupsFilter"] == "(cn=cmapi-*)" and ldap["connectionUrl"].startswith("ldaps://")


def test_crc_reader_reads_only_what_the_code_reads():
    from_code = {"namespaces", "resourcequotas", "limitranges", "pods", "persistentvolumeclaims"}
    rules = crc("ClusterRole", "cmapi-reader")["rules"]
    assert {r for rule in rules for r in rule["resources"]} == from_code
    assert all(set(rule["verbs"]) <= {"get", "list", "watch"} for rule in rules) and all(rule["apiGroups"] == [""] for rule in rules)
    token = crc("Secret", "cmapi-reader-token")
    assert "data" not in token and "stringData" not in token, "the controller fills it; no value in Git"
    assert token["type"] == "kubernetes.io/service-account-token"


def test_crc_trust_holds_certificates_only():
    data = crc("ConfigMap", "cmapi-trust")["data"]["ca-bundle.crt"]
    assert "PRIVATE KEY" not in data and data.count("BEGIN CERTIFICATE") >= 1
    assert "kind stand-in" not in (CRC / "30-trust.yaml").read_text()


def test_crc_monitoring_selects_the_services_and_the_policy_lets_it_in():
    services = {d["metadata"]["name"]: d for d in docs() if d["kind"] == "Service"}
    for c in ("api", "worker"):
        sm = crc("ServiceMonitor", f"cmapi-{c}")["spec"]
        svc = services[f"cmapi-{c}"]
        assert sm["selector"]["matchLabels"].items() <= svc["metadata"]["labels"].items()
        assert sm["endpoints"][0]["port"] in {p["name"] for p in svc["spec"]["ports"]}
        assert "bearerTokenSecret" not in sm["endpoints"][0] and "authorization" not in sm["endpoints"][0]
    policy = next(d for d in docs() if d["kind"] == "NetworkPolicy")
    metrics = next(r for r in policy["spec"]["ingress"] if any(p["port"] == 9090 for p in r["ports"]))
    assert metrics["from"] == [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "openshift-user-workload-monitoring"}}}]


def test_crc_memory_requests_are_the_planned_576_mi():
    """docs/13's arithmetic: the stop line is 2 GiB of request headroom. A request raised here must change the plan with it."""
    def mi(q):
        return int(q[:-2]) * (1024 if q.endswith("Gi") else 1)
    total = 0
    for d in docs():
        if d["kind"] == "Deployment":
            spec = d["spec"]["template"]["spec"]
            main = sum(mi(c["resources"]["requests"]["memory"]) for c in spec["containers"])
            init = max([mi(c["resources"]["requests"]["memory"]) for c in spec.get("initContainers", [])] or [0])
            total += max(main, init)                       # Kubernetes' effective request for a pod
        if d["kind"] == "Cluster":
            total += mi(d["spec"]["resources"]["requests"]["memory"])
    assert total == 576


def test_crc_routes_name_a_port_their_service_has():
    """kubeconform skips Route, and a Route whose targetPort the Service does not name answers 503 with every pod healthy."""
    services = {d["metadata"]["name"]: d for d in docs() if d["kind"] == "Service"}
    for d in crc_docs():
        if d["kind"] == "Route":
            assert d["spec"]["port"]["targetPort"] in {p["name"] for p in services[d["spec"]["to"]["name"]]["spec"]["ports"]}


def test_crc_realm_sync_runs_on_an_account_and_secrets_that_exist():
    """A Job with a name that resolves to nothing would sit Pending, and only on CRC."""
    spec = crc("Job", "cmapi-realm-sync")["spec"]["template"]["spec"]
    accounts = {d["metadata"]["name"] for d in docs() if d["kind"] == "ServiceAccount"}
    assert spec["serviceAccountName"] in accounts
    container = spec["containers"][0]
    secrets = {s["secretRef"]["name"] for s in container["envFrom"]} | {e["valueFrom"]["secretKeyRef"]["name"] for e in container["env"] if "valueFrom" in e}
    assert secrets == {"cmapi-test-users", "cmapi-ldap-bind", "cmapi-keycloak"}
    written = (ROOT / "deploy/secrets.sh").read_text()
    assert all(name in written for name in secrets)
    assert container["command"] == ["cmapi-tools", "realm-sync"]
    assert 'cmapi-tools = "cmapi.tools:run"' in (ROOT / "cmapi/pyproject.toml").read_text()


def test_crc_rollback_names_every_object_the_run_creates():
    """deploy/crc-rollback.sh deletes by name from a fixed list, so an object added to the manifests and not to the list would stay behind on a shared cluster, with nothing to say so.
    Objects in cmapi-imports and cmapi-system go with their namespace; namespace cmapi was there before this wave."""
    text = (ROOT / "deploy/crc-rollback.sh").read_text()
    missing = []
    for d in [*docs(), *crc_docs()]:
        kind, name, ns = d["kind"], d["metadata"]["name"], d["metadata"].get("namespace")
        if ns in ("cmapi-imports", "cmapi-system") or (kind == "Namespace" and name == "cmapi"):
            continue
        if not re.search(rf"\b{kind.lower()}(\.[a-z.]+)? {re.escape(name)}\b", text):
            missing.append(f"{kind}/{name}")
    assert missing == []
