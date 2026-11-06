import pytest

from cmapi.core.authz import RolePolicy
from cmapi.core.errors import Problem
from cmapi.core.identity.checks import check_team_dl, email_in_domains, resolve_requester
from cmapi.core.identity.claims import Identity, Person
from cmapi.core.identity.directory import CachedDirectory, DirectoryProvider, DirectoryUnavailable, InMemoryDirectory
from cmapi.core.identity.keycloak_admin import KeycloakAdminDirectory
from cmapi.core.metadata import MetadataKeys
from conftest import EX, person

DOMAINS = ["ephico2real.com"]


# ---- claims
def test_identity_from_claims():
    i = Identity.from_claims({"sub": "u1", "preferred_username": "Ola", "email": "ola@ephico2real.com",
                              "given_name": "Ola", "middle_name": "A", "family_name": "B", "employee_id": "123",
                              "azp": "cmapi-portal", "groups": ["/cmapi/app-cmapi-rbac-requester"],
                              "resource_access": {"cmapi-nonprod": {"roles": ["cmapi-requester"]}}}, "cmapi-nonprod")
    assert i.kind == "user" and i.label_value == "ola" and i.employee_id == "123"
    assert i.roles == {"cmapi-requester"} and i.record()["middleName"] == "A"
    s = Identity.from_claims({"sub": "s1", "preferred_username": "service-account-svc-payments-ci",
                              "azp": "svc-payments-ci"}, "cmapi-nonprod")
    assert s.kind == "service" and s.username == "svc-payments-ci"


# ---- directory and requester
@pytest.fixture
def directory():
    return InMemoryDirectory([Person("ola", "ola@ephico2real.com", employee_id="123", given_name="Ola"),
                              Person("gone", "gone@ephico2real.com", enabled=False)])


def test_requester_rules(directory):
    ola = person("ola")
    assert resolve_requester(ola, None, directory).username == "ola"
    for caller, obo, code in [(ola, "x", "on-behalf-of-not-allowed"),
                              (person("ola", employee_id=None), None, "identity-incomplete"),
                              (person("svc-ci", kind="service", client="svc-ci"), "gone", "unknown-user"),
                              (person("svc-ci", kind="service", client="svc-ci"), "nobody", "unknown-user")]:
        with pytest.raises(Problem) as e:
            resolve_requester(caller, obo, directory)
        assert e.value.code == code
    svc = person("svc-ci", kind="service", client="svc-ci")
    r = resolve_requester(svc, "123", directory)                   # by employee ID
    assert r.username == "ola" and r.record()["submittedByClient"] == "svc-ci"


def test_a_bot_requests_in_its_own_name(directory):
    svc = person("svc-ci", kind="service", client="svc-ci")
    r = resolve_requester(svc, None, directory)                    # identity.requireOnBehalfOf: false
    assert r.username == "svc-ci" and "submittedByClient" not in r.record()
    with pytest.raises(Problem) as e:
        resolve_requester(svc, None, directory, require_on_behalf_of=True)
    assert e.value.code == "on-behalf-of-required"


def test_cache_serves_stale_when_directory_is_down(directory):
    t = [0.0]
    c = CachedDirectory(directory, ttl_seconds=900, clock=lambda: t[0])
    assert c.get_user("ola").employee_id == "123"
    t[0] = 1000
    directory.down = True
    assert c.get_user("ola").employee_id == "123"                  # stale-on-error
    with pytest.raises(DirectoryUnavailable):
        c.get_user("never-seen")


def test_keycloak_admin_adapter():
    calls = []

    def http(method, url, headers, form):
        calls.append((method, url))
        if url.endswith("/token"):
            return 200, {"access_token": "t", "expires_in": 300}
        if "q=employeeId%3A123" in url:
            return 200, [{"username": "ola", "email": "ola@ephico2real.com", "enabled": True,
                          "attributes": {"employeeId": ["123"], "middleName": ["A"]}}]
        if "username=ola" in url:
            return 200, [{"username": "ola", "firstName": "Ola", "lastName": "B", "enabled": True,
                          "attributes": {"employeeId": ["123"]}}]
        return 503, None
    k = KeycloakAdminDirectory("https://sso.ephico2real.com", "ephico2real", "cmapi-directory", "s", http)
    assert isinstance(k, DirectoryProvider)
    assert k.get_user("ola").employee_id == "123"
    assert k.find_by_employee_id("123").middle_name == "A"
    assert sum(1 for c in calls if c[1].endswith("/token")) == 1       # token reused
    with pytest.raises(DirectoryUnavailable):
        k.search("x")


# ---- email domains and team DL
def test_email_domains():
    assert email_in_domains("payments-team@ephico2real.com", DOMAINS)
    assert email_in_domains("Payments-Team@EPHICO2REAL.com", DOMAINS)
    for bad in ["payments-team@other.com", "no-at-sign", "a@b@ephico2real.com", "@ephico2real.com"]:
        assert not email_in_domains(bad, DOMAINS)
    with pytest.raises(Problem) as e:
        check_team_dl("dl@other.com", DOMAINS)
    assert e.value.code == "invalid-team-dl"


# ---- metadata keys
@pytest.fixture(scope="module")
def keys():
    return MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.yaml")


def codes(errs):
    return sorted(e["code"] for e in errs)


def test_classes(keys):
    assert keys.classify("cmapi.net/tier") == "system"
    assert keys.classify("cmapi.net/protected") == "operatorOnly"
    assert keys.classify("cmapi.net/team-dl") == "governed"
    assert keys.classify("app.kubernetes.io/name") == "reserved"
    assert keys.classify("app.ephico2real.com/component") == "team"
    assert keys.classify("owner") == "team"
    assert keys.classify("example.org/x") == "disallowed"


def test_valid_create(keys):
    labels = {"cmapi.net/team": "payments", "cmapi.net/cost-center": "cc-4410", "app.ephico2real.com/component": "api"}
    ann = {"cmapi.net/team-dl": "payments-team@ephico2real.com"}
    assert keys.validate(labels, ann, operator=False, require_governed=True) == []
    # any team value is accepted: cmapi.net/team is ownership metadata, not checked against the caller
    assert keys.validate({**labels, "cmapi.net/team": "ledger"}, ann, operator=False, require_governed=True) == []


def test_refusals(keys):
    errs = keys.validate({"cmapi.net/team": "ledger", "cmapi.net/tier": "large", "Bad Key": "x",
                          "cmapi.net/cost-center": "4410"},
                         {"cmapi.net/team-dl": "dl@other.com", "kubernetes.io/x": "y"},
                         operator=False, require_governed=True)
    assert codes(errs) == sorted(["reserved_key", "invalid_key", "invalid_value", "invalid-team-dl", "reserved_key"])
    missing = keys.validate({}, {}, operator=False, require_governed=True)
    assert codes(missing) == ["missing_required_key", "missing_required_key"]
    with pytest.raises(Problem) as e:
        keys.check({"cmapi.net/protected": "true"}, {}, operator=False, require_governed=False)
    assert e.value.status == 403


def test_merge_patch_and_facts(keys):
    before = {"cmapi.net/team": "payments", "app.ephico2real.com/a": "1"}
    after = MetadataKeys.merge_patch(before, {"app.ephico2real.com/a": None, "app.ephico2real.com/b": "2"})
    assert after == {"cmapi.net/team": "payments", "app.ephico2real.com/b": "2"}
    assert keys.change_facts(before, after) == {"keyClasses": ["team"], "sensitiveKeyChanged": False}
    assert keys.change_facts(before, {**before, "cmapi.net/team": "ledger"})["sensitiveKeyChanged"]


def test_render_order(keys):
    ordered = keys.ordered({"app.ephico2real.com/c": "x", "cmapi.net/team": "p", "cmapi.net/tier": "m",
                            "cmapi.net/cluster-id": "OCP_GF1"})
    assert list(ordered) == ["cmapi.net/cluster-id", "cmapi.net/tier", "cmapi.net/team", "app.ephico2real.com/c"]


# ---- roles (authz-roles.yaml): no team or namespace-name scoping
def test_roles_gate_by_permission_not_by_namespace(ex):
    import yaml
    pol = RolePolicy(yaml.safe_load((ex / "instances/nonprod/authz-roles.yaml").read_text()), {"rnd", "dev"})
    ola = person("ola", roles={"cmapi-requester"})
    assert pol.allowed(ola, "namespaces:write", "dev") and pol.allowed(ola, "namespaces:write", "rnd")
    assert not pol.allowed(ola, "requests:approve", "dev")
    viewer = person("vic", roles={"cmapi-viewer"})
    with pytest.raises(Problem) as e:
        pol.require(viewer, "namespaces:write", "dev")
    assert e.value.status == 403 and e.value.code == "forbidden"
    nobody = person("x", roles=set())
    assert pol.permissions(nobody) == frozenset()


def test_a_role_limited_to_some_environments(ex):
    import yaml
    pol = RolePolicy(yaml.safe_load((ex / "instances/nonprod/authz-roles.yaml").read_text()), {"rnd", "dev"})
    bot = person("svc-bot", kind="service", client="svc-bot", roles={"cmapi-bot-rnd"})
    assert pol.allowed(bot, "namespaces:write", "rnd")
    with pytest.raises(Problem) as e:
        pol.require(bot, "namespaces:write", "dev")
    assert e.value.code == "environment-forbidden"
    assert pol.environments(bot, "namespaces:write") == {"rnd"}
    both = person("svc-bot", kind="service", client="svc-bot", roles={"cmapi-bot-rnd", "cmapi-requester"})
    assert pol.allowed(both, "namespaces:write", "dev")             # roles add up


def test_role_policy_config_errors():
    for raw, msg in [({"roles": {"x": {"permissions": ["namespaces:write", "teleport"]}}}, "unknown permissions"),
                     ({"roles": {"x": {"inherits": ["y"]}, "y": {"inherits": ["x"]}}}, "inherits itself"),
                     ({"roles": {"x": {"inherits": ["cmapi-nope"]}}}, "unknown role"),
                     ({"roles": {"x": {"inherits": ["cmapi-requester"], "environments": ["prod"]}}}, "not served")]:
        with pytest.raises(ValueError, match=msg):
            RolePolicy(raw, {"rnd", "dev"})
    quota = RolePolicy({"roles": {"cmapi-quota-editor": {"permissions": ["objects:read", "quotas:write"]}}})
    assert quota.permissions(person("q", roles={"cmapi-quota-editor"})) == {"objects:read", "quotas:write"}


def test_every_instance_config_loads():
    from cmapi.core.config import load_instance
    for name in ["nonprod", "staging", "prod"]:
        cfg = load_instance(EX / "instances" / name, EX / "cluster-configs/policies/metadata-keys.yaml")
        assert cfg.roles.allowed(person("ola", roles={"cmapi-requester"}), "namespaces:write")


# ---- regressions from the code review
def test_trailing_newlines_refused(keys):
    errs = keys.validate({"cmapi.net/cost-center": "cc-4410\n", "foo\n": "x"},
                         {"cmapi.net/team-dl": "team\n@ephico2real.com"},
                         operator=False, require_governed=False)
    assert codes(errs) == ["invalid-team-dl", "invalid_key", "invalid_value"]


def test_patch_cannot_remove_a_required_key(keys):
    current_l = {"cmapi.net/team": "payments"}
    current_a = {"cmapi.net/team-dl": "payments-team@ephico2real.com"}
    errs = keys.validate({"cmapi.net/team": None}, {}, operator=False,
                         current_labels=current_l, current_annotations=current_a)
    assert codes(errs) == ["missing_required_key"]
    assert keys.validate({"app.ephico2real.com/x": "1"}, {}, operator=False,
                         current_labels=current_l, current_annotations=current_a) == []


def test_first_set_of_a_sensitive_key_is_not_a_change(keys):
    # found by the local end-to-end run: every create set cmapi.net/team and needed approver-platform
    assert keys.change_facts({}, {"cmapi.net/team": "payments"})["sensitiveKeyChanged"] is False
    assert keys.change_facts({"network.ephico2real.com/zone": "a"}, {})["sensitiveKeyChanged"] is True


# ---- onboarding role, automation accounts, namespace names
def test_onboarding_role_creates_and_nothing_else():
    pol = RolePolicy()
    bot = person("bot-user", roles={"cmapi-onboarding"}, employee_id=None)
    assert pol.allowed(bot, "namespaces:create", "dev")
    for perm in ["namespaces:write", "quotas:write", "requests:approve", "operations:run"]:
        assert not pol.allowed(bot, perm, "dev"), perm
    ola = person("ola", roles={"cmapi-requester"})
    assert pol.allowed(ola, "namespaces:create") and pol.allowed(ola, "namespaces:write")


def test_automation_account_needs_no_employee_id(directory):
    bot = person("bot-user", roles={"cmapi-onboarding"}, employee_id=None)
    r = resolve_requester(bot, None, directory)
    assert r.username == "bot-user" and r.automated and r.record()["automated"] is True
    r2 = resolve_requester(bot, "ola", directory)                   # an agent acting for a person
    assert r2.username == "ola" and r2.record()["submittedBy"] == "bot-user"
    human = person("ann", roles={"cmapi-requester"}, employee_id=None)
    with pytest.raises(Problem) as e:
        resolve_requester(human, None, directory)
    assert e.value.code == "identity-incomplete"
    assert resolve_requester(person("ola"), None, directory).automated is False


def test_namespace_names():
    from cmapi.core.naming import check_name, check_not_unmanaged, reserved
    check_name("ledger-dev")
    check_name("agent-sandbox", ["ocp-*"])
    for bad, code in [("Payments", "invalid-namespace-name"), ("a", "invalid-namespace-name"),
                      ("-x", "invalid-namespace-name"), ("x" * 64, "invalid-namespace-name"),
                      ("ok\n", "invalid-namespace-name"), ("default", "reserved-namespace"),
                      ("kube-tools", "reserved-namespace"), ("openshift-x", "reserved-namespace"),
                      ("ocp-tools", "reserved-namespace")]:
        with pytest.raises(Problem) as e:
            check_name(bad, ["ocp-*"])
        assert e.value.code == code, bad
    assert reserved("cmapi-system") == "cmapi-system" and reserved("payments") is None
    check_not_unmanaged("x", None)
    check_not_unmanaged("x", {"metadata": {"labels": {"cmapi.net/managed": "true"}}})
    with pytest.raises(Problem) as e:
        check_not_unmanaged("legacy-app", {"metadata": {"labels": {}}})
    assert e.value.status == 409 and e.value.code == "namespace-exists-unmanaged"
