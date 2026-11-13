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
    # With CNPG's URI and a bundle without its CA, sslmode=prefer falls back to plaintext (measured), so this never names the bundle.
    assert e["PGSSLROOTCERT"]["value"] != TRUST and e["PGSSLMODE"]["value"] == "verify-full"
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


def test_crc_realm_takes_a_password_through_no_client_and_limits_guesses():
    """No client takes the resource owner password grant (RFC 9700, section 2.4: "MUST NOT be used"; #181). Each client says so itself, because
    Keycloak's default for a client that does not say is on. Keycloak gives every realm a public admin-cli unless the import names it. The
    automation client signs in by its service account. Measured in deploy/tests/realm-test.py."""
    realm = crc("KeycloakRealmImport", "cmapi")["spec"]["realm"]
    assert [c["clientId"] for c in realm["clients"] if c.get("directAccessGrantsEnabled") is not False] == []
    auto = next(c for c in realm["clients"] if c["clientId"] == "cmapi-automation")
    assert auto["serviceAccountsEnabled"] is True and auto["publicClient"] is False and auto["standardFlowEnabled"] is False
    account = next(u for u in realm["users"] if u.get("serviceAccountClientId") == "cmapi-automation")
    assert account["clientRoles"] == {"cmapi-nonprod": ["cmapi-onboarding"]}
    assert [u["username"] for u in realm["users"] if "serviceAccountClientId" not in u] == [], "a local account in the import"
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
    assert ldap["requireSync"] is True and ldap["groupsFilter"] == "(cn=app-cmapi-rbac-*)" and ldap["connectionUrl"].startswith("ldaps://")
    # This realm reads the test users of the shared directory and nobody else, and the Job fails unless it read exactly them. Measured in deploy/tests/realm-test.py.
    assert ldap["usersFilter"] == "(uid=cmapi.*)" and ldap["expectUsers"] == len(IDENTITIES)


# ---- the groups: the one table the owner decided, and everything that has to agree with it (#110)
IDENTITIES = [line.rstrip("\n").split("\t") for line in (ROOT / "examples/cmapi-sso/ldap/test-identities.tsv").read_text().splitlines()
              if line and not line.startswith("#")]
OWNERS_TABLE = {"app-cmapi-rbac-viewer": ["cmapi-viewer"], "app-cmapi-rbac-onboarding": ["cmapi-onboarding"], "app-cmapi-rbac-requester": ["cmapi-requester"],
                "app-cmapi-rbac-approver-prod": ["cmapi-approver"], "app-cmapi-rbac-approver-qa": ["cmapi-approver"], "app-cmapi-rbac-approver-uat": ["cmapi-approver"],
                "app-cmapi-rbac-approver-platform": ["cmapi-approver"], "app-cmapi-rbac-operator": ["cmapi-operator", "cmapi-approver"],
                "app-cmapi-rbac-admin": ["cmapi-admin"], "app-cmapi-rbac-auditor": ["cmapi-auditor"]}
OLD_GROUPS = ("cmapi-viewers", "cmapi-requesters", "cmapi-prod-approvers", "cmapi-qa-leads", "cmapi-uat-leads", "cmapi-platform-leads", "cmapi-platform-operators", "cmapi-platform-admins", "cmapi-auditors")


def realm_groups():
    realm = crc("KeycloakRealmImport", "cmapi")["spec"]["realm"]
    top = next(g for g in realm["groups"] if g["path"] == "/cmapi")
    return top["subGroups"]


def test_the_realm_import_holds_the_owners_table():
    got = {g["name"]: g["clientRoles"]["cmapi-nonprod"] for g in realm_groups()}
    assert got == OWNERS_TABLE
    assert all(g["path"] == f"/cmapi/{g['name']}" for g in realm_groups())


def test_the_realm_sync_chart_and_ldif_hold_the_same_groups():
    e = env(crc("Job", "cmapi-realm-sync")["spec"]["template"]["spec"]["containers"][0])
    assert __import__("json").loads(e["CMAPI_REALM_GROUPS"]["value"]) == OWNERS_TABLE
    values = yaml.safe_load((ROOT / "deploy/helm/cmapi/values.yaml").read_text())
    assert values["keycloak"]["realm"]["groups"] == OWNERS_TABLE
    assert values["keycloak"]["sync"]["ldap"]["groupsFilter"] == "(cn=app-cmapi-rbac-*)"
    ldif = (ROOT / "examples/cmapi-sso/ldap/cmapi-groups.ldif").read_text()
    assert set(re.findall(r"^cn: (.+)$", ldif, re.M)) == set(OWNERS_TABLE)


def test_every_table_row_holds_exactly_the_roles_of_its_groups():
    """The table's roles are what a token must hold, so they are not read from the realm: this is where a realm that grants the wrong role is caught."""
    assert len(IDENTITIES) == 13 and [i[0] for i in IDENTITIES if i[2] == "-"] == ["cmapi.noaccess"]
    numbers = [int(i[1]) for i in IDENTITIES]
    assert numbers == list(range(10100, 10113)), "unique, and above the 10007 measured in use"
    for uid, _, groups, roles in IDENTITIES:
        wanted = set() if groups == "-" else {r for g in groups.split(",") for r in OWNERS_TABLE[g]}
        assert (set() if roles == "-" else set(roles.split(","))) == wanted, uid


def test_a_group_every_approval_rule_names_is_in_the_realm():
    """A rule whose group has no realm group can never be approved. Through the instance's own setting, for each environment's real file, so a setting and a rule that disagree fail."""
    paths = {g["path"] for g in realm_groups()}
    for name in ("crc", "kind"):
        identity = yaml.safe_load(config_file(name, "instance.yaml"))["instance"]["identity"]
        assert identity["groupPath"] == "/cmapi/app-cmapi-rbac-{name}"
        rules = yaml.safe_load(config_file(name, "approval-rules.yaml"))
        named = {rules["defaults"]["group"]} | {t["group"] for t in rules["thresholds"] if "group" in t} | {p["group"] for p in rules["namespacePatterns"] if "group" in p} \
            | {e["group"] for e in rules["environments"].values() if "group" in e}
        assert named == {"approver-platform"}, name
        assert {identity["groupPath"].format(name=g) for g in named} <= paths
    # Every instance's rules, with the code's default for the expiration plugin: approver-prod, -qa, -uat and -platform all exist.
    for instance in ("nonprod", "staging", "prod"):
        rules = yaml.safe_load((ROOT / f"examples/instances/{instance}/approval-rules.yaml").read_text())
        for e in rules["environments"].values():
            assert "group" not in e or f"/cmapi/app-cmapi-rbac-{e['group']}" in paths, (instance, e)


def test_the_local_realm_users_are_in_groups_the_realm_has():
    """test_users() skips a group it does not know, silently, so a missed rename would leave ola with no roles and no error."""
    from cmapi.tools.realm_sync import TEST_USERS
    assert {g for *_, memberships in TEST_USERS for g in memberships} <= set(OWNERS_TABLE)


def test_none_of_the_old_names_is_in_what_ships():
    """The mockup's sample data waits for Wave 6 and the local demo keeps its names through identity.groupPath: docs/11 says so. The script that removes the old groups has to name them."""
    trees = ["cmapi/src", "deploy/manifests/environments", "deploy/helm", "deploy/environments", "deploy/crc-proof.sh", "examples/config", "examples/instances", "examples/cmapi-sso/realm", "examples/cmapi-sso/ldap/cmapi-groups.ldif", "examples/cmapi-sso/ldap/apply-groups.sh", "examples/cmapi-sso/ldap/apply-bind-user.sh", "examples/cmapi-sso/ldap/test-identities.tsv"]
    shorts = ("platform-leads", "qa-leads", "uat-leads", "prod-approvers")
    found = []
    for tree in trees:
        root = ROOT / tree
        for f in ([root] if root.is_file() else root.rglob("*")):
            if f.is_file() and f.suffix != ".pyc":
                text = f.read_text(errors="replace")
                found += [f"{f.relative_to(ROOT)}: {n}" for n in OLD_GROUPS + shorts + ("cn=cmapi-*",) if n in text]
    assert not found


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
