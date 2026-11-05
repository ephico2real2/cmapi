import pytest

from cmapi.core.authz import Binding, allowed, teams_for
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
                              "azp": "cmapi-portal", "groups": ["/cmapi/cmapi-payments-requesters"],
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
                              (person("svc-ci", kind="service", client="svc-ci"), None, "on-behalf-of-required"),
                              (person("svc-ci", kind="service", client="svc-ci"), "gone", "unknown-user"),
                              (person("svc-ci", kind="service", client="svc-ci"), "nobody", "unknown-user")]:
        with pytest.raises(Problem) as e:
            resolve_requester(caller, obo, directory)
        assert e.value.code == code
    svc = person("svc-ci", kind="service", client="svc-ci")
    r = resolve_requester(svc, "123", directory)                   # by employee ID
    assert r.username == "ola" and r.record()["submittedByClient"] == "svc-ci"


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
    assert keys.validate(labels, ann, operator=False, teams={"payments"}, require_governed=True) == []


def test_refusals(keys):
    errs = keys.validate({"cmapi.net/team": "ledger", "cmapi.net/tier": "large", "Bad Key": "x",
                          "cmapi.net/cost-center": "4410"},
                         {"cmapi.net/team-dl": "dl@other.com", "kubernetes.io/x": "y"},
                         operator=False, teams={"payments"}, require_governed=True)
    assert codes(errs) == sorted(["team_not_bound", "reserved_key", "invalid_key", "invalid_value",
                                  "invalid-team-dl", "reserved_key"])
    missing = keys.validate({}, {}, operator=False, teams=set(), require_governed=True)
    assert codes(missing) == ["missing_required_key", "missing_required_key"]
    with pytest.raises(Problem) as e:
        keys.check({"cmapi.net/protected": "true"}, {}, operator=False, teams=set(), require_governed=False)
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


# ---- scope bindings
def test_bindings_and_teams(ex):
    import yaml
    bs = [Binding.from_dict(b) for b in yaml.safe_load((ex / "config/authz-scopes.yaml").read_text())["bindings"]]
    ola = person("ola", roles={"cmapi-requester"}, groups={"/cmapi/cmapi-payments-requesters"})
    assert allowed(ola, "namespaces:write", bs, "OCP_GF1", "prod", "payments-prod")
    assert not allowed(ola, "namespaces:write", bs, "OCP_GF1", "prod", "ledger-prod")
    assert not allowed(ola, "requests:approve", bs, "OCP_GF1", "prod", "payments-prod")
    assert teams_for(ola, bs) == {"payments"}


# ---- regressions from the code review
def test_trailing_newlines_refused(keys):
    errs = keys.validate({"cmapi.net/cost-center": "cc-4410\n", "foo\n": "x"},
                         {"cmapi.net/team-dl": "team\n@ephico2real.com"},
                         operator=False, teams={"payments"}, require_governed=False)
    assert codes(errs) == ["invalid-team-dl", "invalid_key", "invalid_value"]


def test_patch_cannot_remove_a_required_key(keys):
    current_l = {"cmapi.net/team": "payments"}
    current_a = {"cmapi.net/team-dl": "payments-team@ephico2real.com"}
    errs = keys.validate({"cmapi.net/team": None}, {}, operator=False, teams={"payments"},
                         current_labels=current_l, current_annotations=current_a)
    assert codes(errs) == ["missing_required_key"]
    assert keys.validate({"app.ephico2real.com/x": "1"}, {}, operator=False, teams={"payments"},
                         current_labels=current_l, current_annotations=current_a) == []


def test_first_set_of_a_sensitive_key_is_not_a_change(keys):
    # found by the local end-to-end run: every create set cmapi.net/team and needed platform-leads
    assert keys.change_facts({}, {"cmapi.net/team": "payments"})["sensitiveKeyChanged"] is False
    assert keys.change_facts({"network.ephico2real.com/zone": "a"}, {})["sensitiveKeyChanged"] is True
