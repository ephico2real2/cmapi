"""#479, review of PR #488 (F01, F02): the expiry keys and an environment whose expiration is turned off.

F01: cmapi.net/expiry and cmapi.net/expires-at are written only through expiresAt, whatever system lists.
F02, the coordinator's ruling: with expiration now off in an environment, an ordinary change keeps a namespace's date
as it is, Make permanent still removes it, and Extend and Set stay refused ("never block a capability; approval rules
gate"). The planner runs on the reference configuration with stand-ins for Git, the cluster and the validator.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.metadata import MetadataKeys
from cmapi.core.pipeline import Pipeline, folder_etag
from cmapi.core.ports import CapacityResult
from cmapi.plugins.expiration.rules import ExpirationRules, ExpiryInfo, utc_today
from cmapi.tools.openapi import load

NS = "abc-payments-dev"
OLA = Identity("user", "ola", "user", "portal", employee_id="1001", roles=frozenset({"cmapi-requester"}))
BODY = {"namespace": NS, "labels": {"cmapi.net/team": "payments"},
        "annotations": {"cmapi.net/team-dl": "payments@ephico2real.com"}}


def planner() -> Pipeline:
    """The pipeline on the reference metadata-keys.yaml, for the dev cluster CRC, with no namespace in Git yet."""
    cfg = load(Path(__file__).resolve().parents[3] / "examples/cluster-configs/policies/metadata-keys.yaml", None)
    registry, git, validator, capacity = Mock(), Mock(), Mock(), Mock()
    registry.writable.return_value.policy.environment = "dev"
    registry.writable.return_value.policy.labels = {}
    registry.cache.return_value.namespace.return_value = None
    git.read_folder.return_value = {}, "base"
    validator.validate.return_value = []
    capacity.check.return_value = CapacityResult("fits", True)
    return Pipeline(cfg, registry, git, validator, capacity, None, [])


def namespace_doc(plan) -> dict:
    return yaml.safe_load(next(t for p, t in plan.files.items() if p.endswith("/namespace.yaml")))


def dated_then_switched_off() -> tuple[Pipeline, str, str]:
    """A namespace created with a date while dev took expiry; then dev's expiration is turned off. (pipe, etag, date)"""
    pipe = planner()
    day = (utc_today() + timedelta(days=7)).isoformat()
    first = pipe.plan_namespace(OLA, "CRC", {**BODY, "expiresAt": day}, action="create")
    stored = {p: t for p, t in first.files.items() if t is not None}
    pipe.git.read_folder.return_value = stored, "base"
    pipe.cfg.expiration.envs["dev"] = replace(pipe.cfg.expiration.envs["dev"], enabled=False)
    return pipe, folder_etag(stored), day


# ---- F01
def test_a_request_cannot_set_the_expiry_keys_when_the_file_leaves_them_out_of_system():
    pipe = planner()
    pipe.cfg.expiration = ExpirationRules({"environments": {"dev": {"enabled": False}}})
    keys = MetadataKeys({"extraLabels": {"allowOther": {"prefixes": ["cmapi.net/"]}},
                         "extraAnnotations": {"allowOther": {"prefixes": ["cmapi.net/"]}}})
    pipe.cfg.metadata = pipe.renderer.keys = keys
    body = {**BODY, "labels": {"cmapi.net/expiry": "managed"}, "annotations": {"cmapi.net/expires-at": "2027-01-23"}}
    with pytest.raises(Problem) as refused:
        pipe.plan_namespace(OLA, "CRC", body, action="create")
    assert refused.value.code == "policy-violation"
    assert sorted((e["key"], e["code"]) for e in refused.value.errors) == [
        ("cmapi.net/expires-at", "reserved_key"), ("cmapi.net/expiry", "reserved_key")]


@pytest.mark.parametrize("stanza,key", [("requiredLabels", "cmapi.net/expiry"),
                                        ("requiredAnnotations", "cmapi.net/expires-at")])
def test_a_file_cannot_declare_an_expiry_key_as_its_own(stanza, key):
    with pytest.raises(ValueError, match="system, operator-only or reserved"):
        MetadataKeys({stanza: {key: {"value": {"from": "namespace"}}}})


# ---- F02
def test_an_ordinary_change_keeps_the_date_where_expiration_is_now_off():
    pipe, etag, day = dated_then_switched_off()
    plan = pipe.plan_namespace(OLA, "CRC", {"namespace": NS, "labels": {"cmapi.net/cost-center": "cc-1234"}},
                               action="update", if_match=etag)
    doc = namespace_doc(plan)
    assert doc["metadata"]["annotations"]["cmapi.net/expires-at"] == day
    assert doc["metadata"]["labels"]["cmapi.net/expiry"] == "managed"
    assert doc["metadata"]["labels"]["cmapi.net/cost-center"] == "cc-1234"
    assert "expirationAction" not in plan.facts


def test_make_permanent_removes_the_date_where_expiration_is_now_off():
    pipe, etag, _ = dated_then_switched_off()
    plan = pipe.plan_namespace(OLA, "CRC", {"namespace": NS, "makePermanent": True}, action="update", if_match=etag,
                               reason="expiration:makePermanent")
    doc = namespace_doc(plan)
    assert "cmapi.net/expiry" not in doc["metadata"]["labels"]
    assert "cmapi.net/expires-at" not in doc["metadata"]["annotations"]
    assert plan.facts["expirationAction"] == "makePermanent" and plan.facts["expirationBeyondLimits"]


@pytest.mark.parametrize("change,reason", [({"extendDays": 5}, "expiration:extend"),
                                           ({"extendUntil": "2099-01-01"}, "expiration:extend"),
                                           ({"expiresAt": "2099-01-01"}, "expiration:set")])
def test_extend_and_set_stay_refused_where_expiration_is_off(change, reason):
    pipe, etag, _ = dated_then_switched_off()
    with pytest.raises(Problem) as refused:
        pipe.plan_namespace(OLA, "CRC", {"namespace": NS, **change}, action="update", if_match=etag, reason=reason)
    assert refused.value.code == "expiration-not-allowed"


def test_make_permanent_of_a_permanent_namespace_where_expiration_is_off_is_still_expiration_not_allowed():
    rules = ExpirationRules({"environments": {"dev": {"enabled": False}}})
    with pytest.raises(Problem) as refused:
        rules.plan_make_permanent(ExpiryInfo(NS, "dev", created=utc_today(), expires_at=None))
    assert refused.value.code == "expiration-not-allowed"
