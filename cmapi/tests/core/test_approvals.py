import pytest

from cmapi.core.approvals import ApprovalLedger, ApprovalRules
from cmapi.core.errors import Problem
from cmapi.core.expression import Expression, ExpressionError
from conftest import ALL_ENVS, EX, INSTANCES, person


@pytest.fixture(scope="module")
def rules():
    return ApprovalRules.load(EX / "config/approval-rules.yaml", ALL_ENVS)


def facts(**kw):
    base = {"plugin": "namespaces", "action": "create", "environment": "prod", "namespace": "payments-prod",
            "tier": "medium", "capacity": "fits", "capacityFresh": True, "quotaIncreasePct": 0,
            "clusterLabels": {"region": "us-central"}}
    return {**base, **kw}


# ---- expressions
def test_expression_whitelist():
    assert Expression('action == "delete" and (pods > 20 or pvcs > 10)')({"action": "delete", "pods": 30})
    assert not Expression("quotaIncreasePct > 100")({})                  # missing number: false
    assert Expression('reason != "expired"')({})                         # missing reason is not "expired"
    for bad in ["__import__('os')", "pods.real", "pods + 1 > 2", "unknownFact > 1", "pods[0] > 1"]:
        with pytest.raises(ExpressionError):
            Expression(bad)


@pytest.mark.parametrize("instance,envs", INSTANCES.items())
def test_instance_files_load(instance, envs):
    ApprovalRules.load(EX / f"instances/{instance}/approval-rules.yaml", envs)


# ---- decide
def test_prod_create_needs_one_prod_approver(rules):
    r = rules.decide(facts())
    assert [(s.group, s.count) for s in r.slots] == [("prod-approvers", 1)]
    assert r.timeout_hours == 48 and not r.self_approval and r.auto is None


def test_prod_delete_of_old_namespace_adds_platform_leads(rules):
    r = rules.decide(facts(action="delete", namespaceAgeDays=200, pods=3, pvcs=0))
    assert {(s.group, s.count) for s in r.slots} == {("prod-approvers", 2), ("platform-leads", 1)}
    assert r.total == 3


def test_quota_increase_and_capacity_warn_add_up(rules):
    r = rules.decide(facts(action="update", quotaIncreasePct=300, capacity="warn"))
    assert {(s.group, s.count) for s in r.slots} == {("prod-approvers", 1), ("platform-leads", 2)}


def test_patterns_raise_and_waive(rules):
    r = rules.decide(facts(namespace="critical-ledger"))
    assert [(s.group, s.count) for s in r.slots] == [("platform-leads", 2)]
    r = rules.decide(facts(environment="qa", action="update", namespace="temp-load"))
    assert r.slots == () and r.auto == "none-required"


def test_rnd_small_create_is_auto_approved(rules):
    r = rules.decide(facts(environment="rnd", namespace="payments-rnd", tier="small"))
    assert r.auto == "auto:baseline-rnd-namespace" and r.slots == ()


@pytest.mark.parametrize("override,guard", [
    ({"tier": "large"}, None),                                 # policy does not match: humans, no fallback
    ({"capacity": "warn"}, "rules-added-approvers"),            # the threshold added an approver first
    ({"capacityFresh": False}, "capacity"),
    ({"warnings": ["near quota"]}, "warnings"),
])
def test_auto_approval_guards(rules, override, guard):
    r = rules.decide(facts(**{"environment": "dev", "namespace": "payments-dev", "tier": "small", **override}))
    assert r.auto is None and r.auto_fallback == guard


def test_team_allowance_and_kill_switch(rules):
    f = facts(environment="rnd", namespace="payments-rnd", tier="small")
    assert rules.decide(f, team_auto_today=20).auto_fallback == "team-allowance"
    r = rules.decide(f, paused=True)
    assert r.auto is None and r.slots[0].group == "platform-leads" and r.auto_fallback == "paused"


def test_expired_namespace_delete(rules):
    f = facts(environment="qa", action="delete", reason="expired", namespace="critical-old",
              namespaceAgeDays=400, pods=50, noticesSent=3)
    r = rules.decide(f)                                         # pattern and delete threshold do not apply
    assert r.auto == "auto:expired-namespace"
    r = rules.decide({**f, "noticesSent": 1})
    assert r.auto is None and r.auto_fallback == "noticesSentAtLeast2"
    assert [(s.group, s.count) for s in r.slots] == [("qa-leads", 1)]


def test_protected_delete_refused(rules):
    with pytest.raises(Problem) as e:
        rules.decide(facts(action="delete", protected=True))
    assert e.value.code == "namespace-protected"


def test_team_metadata_policy_only_for_team_keys(rules):
    f = facts(plugin="metadata", action="patch", keyClasses=["team"])
    assert rules.decide(f).auto == "auto:team-metadata"
    assert rules.decide({**f, "keyClasses": ["team", "governed"]}).auto is None


# ---- ledger
APPROVER = dict(roles={"cmapi-approver"})


def test_ledger_fills_slots_by_group(rules):
    req = rules.decide(facts(action="delete", namespaceAgeDays=200))
    led = ApprovalLedger(req, requester_sub="sub-ola")
    a = person("amy", groups={"/cmapi/cmapi-prod-approvers"}, **APPROVER)
    b = person("bob", groups={"/cmapi/cmapi-prod-approvers"}, **APPROVER)
    c = person("cat", groups={"/cmapi/cmapi-platform-leads"}, **APPROVER)
    assert not led.approve(a)
    with pytest.raises(Problem) as e:
        led.approve(a)
    assert e.value.code == "already-approved"
    assert not led.approve(b)
    assert led.remaining() == [{"group": "platform-leads", "needed": 1}]
    assert led.approve(c)


def test_ledger_eligibility(rules):
    req = rules.decide(facts())
    led = ApprovalLedger(req, requester_sub="sub-ola", client_owner_subs=frozenset({"sub-own"}))
    for who, code in [(person("ola", groups={"/cmapi/cmapi-prod-approvers"}, **APPROVER), "self-approval"),
                      (person("own", groups={"/cmapi/cmapi-prod-approvers"}, **APPROVER), "self-approval"),
                      (person("dan", groups={"/cmapi/cmapi-qa-leads"}, **APPROVER), "not-eligible"),
                      (person("eve", groups={"/cmapi/cmapi-prod-approvers"}, roles={"cmapi-viewer"}), "forbidden")]:
        with pytest.raises(Problem) as e:
            led.approve(who)
        assert e.value.code == code
    with pytest.raises(Problem) as e:
        led.approve(person("fay", groups={"/cmapi/cmapi-prod-approvers"}, **APPROVER), permitted=False)
    assert e.value.code == "forbidden"            # the instance's roles do not grant approve in this environment


def test_self_approval_where_the_environment_allows_it(rules):
    req = rules.decide(facts(environment="rnd", namespace="payments-rnd", tier="large"))
    led = ApprovalLedger(req, requester_sub="sub-ola")
    assert led.approve(person("ola", groups={"/cmapi/cmapi-platform-leads"}, **APPROVER))


def test_relay_names_an_eligible_person(rules):
    req = rules.decide(facts())
    led = ApprovalLedger(req, requester_sub="sub-ola")
    relay = person("svc-servicenow", kind="service", client="svc-servicenow", roles={"cmapi-approval-relay"})
    amy = person("amy", groups={"/cmapi/cmapi-prod-approvers"}, **APPROVER)
    assert led.approve(amy, relay=relay)
    assert led.entries[0]["relayedBy"] == "svc-servicenow"


# ---- regressions from the code review
def test_sensitive_key_adds_platform_leads_and_blocks_auto(rules):
    f = facts(plugin="metadata", action="patch", keyClasses=["team"], sensitiveKeyChanged=True)
    r = rules.decide(f)
    assert r.auto is None and ("platform-leads", 1) in {(s.group, s.count) for s in r.slots}


def test_expiry_beyond_limits_adds_platform_leads(rules):
    r = rules.decide(facts(environment="rnd", namespace="ledger-rnd", action="update", plugin="expiration",
                           expirationBeyondLimits=True))
    assert [(s.group, s.count) for s in r.slots] == [("platform-leads", 1)]


def test_pattern_group_replaces_environment_group(rules):
    r = rules.decide(facts(action="delete", namespace="critical-pay"))
    assert [(s.group, s.count) for s in r.slots] == [("platform-leads", 2)]


def test_missing_capacity_facts_do_not_auto_approve(rules):
    f = {k: v for k, v in facts(environment="rnd", namespace="payments-rnd", tier="small").items()
         if k not in ("capacity", "capacityFresh")}
    r = rules.decide(f)
    assert r.auto is None and r.auto_fallback == "capacity"


def test_multi_group_approver_counts_where_needed(rules):
    req = rules.decide(facts(action="update", quotaIncreasePct=150))      # 1 prod-approvers + 1 platform-leads
    led = ApprovalLedger(req, requester_sub="sub-ola")
    both = person("amy", groups={"/cmapi/cmapi-prod-approvers", "/cmapi/cmapi-platform-leads"}, **APPROVER)
    prod_only = person("bob", groups={"/cmapi/cmapi-prod-approvers"}, **APPROVER)
    assert not led.approve(both)
    assert led.approve(prod_only)                          # amy moves to platform-leads


def test_on_behalf_of_person_cannot_self_approve(rules):
    from cmapi.core.identity.checks import resolve_requester
    from cmapi.core.identity.claims import Person
    from cmapi.core.identity.directory import InMemoryDirectory
    d = InMemoryDirectory([Person("ola", "ola@ephico2real.com", sub="sub-ola")])
    who = resolve_requester(person("svc-ci", kind="service", client="svc-ci"), "ola", d)
    led = ApprovalLedger(rules.decide(facts()), requester_sub=who.sub)
    with pytest.raises(Problem) as e:
        led.approve(person("ola", groups={"/cmapi/cmapi-prod-approvers"}, **APPROVER))
    assert e.value.code == "self-approval"


def test_not_with_a_missing_fact_stays_false():
    assert not Expression("not quotaIncreasePct > 100")({})
    assert Expression("not quotaIncreasePct > 100")({"quotaIncreasePct": 5})
