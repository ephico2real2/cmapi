"""#483, the contract of a change to an existing namespace's metadata (docs/reviews/2026-11-20-epic-481-metadata-patch/
design.md). The pure parts, with no database and no cluster: the key classes of section 3 (x-cmapi-edit and validate()
on a change), the metadataDiff of section 4.1, the sync state of section 4.2 and the ranked lookup of section 4.4.

The configuration is the design's company.net file, with one more extra key and a suffix-free name. Each test names one
behaviour."""
from __future__ import annotations

import pytest

from cmapi.core.listquery import Lister, ListQuery
from cmapi.core.metadata import DEFAULT_LIVE_ONLY_KEYS, MetadataKeys
from cmapi.plugins.namespaces.state import sync_state, sync_view

RAW = {
    "system": ["cmapi.net/tier", "cmapi.net/managed", "cmapi.net/request-id"],
    "operatorOnly": ["cmapi.net/protected"],
    "reservedPrefixes": ["kubernetes.io/", "openshift.io/", "argocd.argoproj.io/"],
    "requiredLabels": {
        "name": {"value": {"from": "namespace"}},
        "company.net/app-environment": {"value": {"from": "environment"}},
        "company.net/mnemonic": {"pattern": "^[a-z]{3,4}$", "namespacePrefix": True, "example": "abc"},
        "company.net/lob": {"example": "amgsst"},
        "company.net/cl": {"enum": ["0", "1", "2", "3", "4", "5", "6"], "example": "1"},
    },
    "requiredAnnotations": {"cmapi.net/team-dl": {"format": "email-in-domains", "example": "payments-team@company.net"}},
    "extraLabels": {"keys": {"cmapi.net/cost-center": {"pattern": "^cc-[0-9]{4}$", "example": "cc-4410"}},
                    "allowOther": {"prefixes": ["", "*.company.net/"], "max": 50}},
    "extraAnnotations": {"keys": {}, "allowOther": {"prefixes": ["*.company.net/"], "max": 50}},
    "adoptionLabels": {"company.net/provisioner": {"recognise": ["cluster-configs"]}},
    "sensitiveKeys": ["company.net/cl", "cmapi.net/protected"],
    "emailDomains": ["company.net"],
}
KEYS = MetadataKeys(RAW)
GIT = {"name": "abc-payments-dev", "company.net/app-environment": "dev", "company.net/mnemonic": "abc",
       "company.net/lob": "amgsst", "company.net/cl": "1", "cmapi.net/cost-center": "cc-4410"}
CHANGE = dict(operator=False, existing=True, current_labels=GIT,
              current_annotations={"cmapi.net/team-dl": "payments-team@company.net"},
              sources={"namespace": "abc-payments-dev", "environment": "dev"})


def edit(kind: str, key: str, keys: MetadataKeys = KEYS) -> tuple[str, str | None, bool]:
    rule = keys.edit_rule(kind, key)
    return rule["mode"], rule["reason"], rule["sensitive"]


def errors(found: list[dict]) -> list[tuple[str, str]]:
    return [(e["code"], e["key"]) for e in found]


# ---------------------------------------------------------------- section 3: each class from the configuration

def test_a_system_key_is_fixed_and_managed_by_cmapi():
    assert edit("label", "cmapi.net/tier") == ("fixed", "Managed by cmapi.", False)


def test_the_expiry_keys_are_fixed_and_point_to_the_expiry_calls():
    assert edit("annotation", "cmapi.net/expires-at") == \
        ("fixed", "Change it with Extend, Set expiry or Make permanent.", False)


def test_a_reserved_an_adoption_and_a_not_allowed_key_are_fixed_each_with_its_reason():
    assert edit("label", "kubernetes.io/metadata.name") == ("fixed", "Reserved for the platform.", False)
    assert edit("label", "company.net/provisioner") == ("fixed", "Marks how the namespace was first made.", False)
    assert edit("annotation", "other.org/x") == ("fixed", "Not allowed by this instance's rules.", False)


def test_metadata_keys_operator_only_rule_is_optional_and_generic_without_a_cluster():
    assert edit("label", "cmapi.net/protected") == \
        ("optional", "Needs namespaces:protect in the namespace's environment. Changing this key needs one more approval.",
         True)


def test_a_filled_in_key_is_automatic_with_its_source():
    assert edit("label", "name") == ("automatic", "Copied from the namespace name.", False)
    assert edit("label", "company.net/app-environment") == ("automatic", "Copied from the cluster's environment.", False)


def test_the_key_that_starts_the_name_is_fixed():
    assert edit("label", "company.net/mnemonic") == ("fixed", "Part of the namespace's fixed name.", False)


def test_a_required_key_is_required_and_a_sensitive_one_says_it_adds_an_approval():
    assert edit("label", "company.net/lob") == ("required", "Required on every namespace.", False)
    assert edit("label", "company.net/cl") == \
        ("required", "Required on every namespace. Changing this key needs one more approval.", True)


def test_an_extra_key_and_a_key_that_allow_other_admits_are_optional():
    assert edit("label", "cmapi.net/cost-center") == ("optional", None, False)
    assert edit("label", "team.company.net/squad") == ("optional", None, False)


def test_each_property_of_both_schemas_carries_its_x_cmapi_edit():
    for op in ("create", "patch"):
        props = KEYS.json_schema("label", op)["properties"]
        assert props["company.net/mnemonic"]["x-cmapi-edit"] == KEYS.edit_rule("label", "company.net/mnemonic"), op
        assert props["cmapi.net/protected"]["x-cmapi-edit"]["sensitive"] is True, op
        assert all("x-cmapi-edit" in p for p in props.values()), op
    assert KEYS.keys_view()["labels"]["properties"]["name"]["x-cmapi-edit"]["mode"] == "automatic"


# ---------------------------------------------------------------- section 3 on a change: validate()

def test_a_change_that_sends_back_each_fixed_and_automatic_key_is_accepted():
    echo = {k: GIT[k] for k in ("name", "company.net/app-environment", "company.net/mnemonic")}
    assert KEYS.validate(echo, {}, **CHANGE) == []


def test_a_change_of_the_mnemonic_is_refused_even_when_the_name_starts_with_the_new_value():
    keys = MetadataKeys({**RAW, "requiredLabels": {**RAW["requiredLabels"], "company.net/mnemonic": {
        "pattern": "^[a-z-]{3,12}$", "namespacePrefix": True, "example": "abc"}}})
    found = keys.validate({"company.net/mnemonic": "abc-payments"}, {}, **CHANGE)
    assert errors(found) == [("invalid_value", "company.net/mnemonic")]
    assert "a change keeps 'abc'" in found[0]["detail"]


def test_a_change_that_removes_the_mnemonic_is_refused_once_as_a_missing_required_key():
    found = KEYS.validate({"company.net/mnemonic": None}, {}, **CHANGE)
    assert errors(found) == [("missing_required_key", "company.net/mnemonic")]


def test_a_change_that_removes_an_optional_key_that_starts_the_name_is_refused_as_part_of_the_name():
    raw = {**RAW, "requiredLabels": {k: v for k, v in RAW["requiredLabels"].items() if k != "company.net/mnemonic"}}
    raw["extraLabels"] = {**RAW["extraLabels"], "keys": {**RAW["extraLabels"]["keys"],
                                                         "company.net/unit": {"pattern": "^[a-z]{3}$", "namespacePrefix": True}}}
    current = {**CHANGE, "current_labels": {**GIT, "company.net/unit": "abc"}}
    found = MetadataKeys(raw).validate({"company.net/unit": None}, {}, **current)
    assert errors(found) == [("invalid_value", "company.net/unit")]


def test_a_change_cannot_add_a_mnemonic_that_the_namespace_lacks():
    lacking = {**CHANGE, "current_labels": {k: v for k, v in GIT.items() if k != "company.net/mnemonic"}}
    found = KEYS.validate({"company.net/mnemonic": "abc"}, {}, **lacking)
    assert errors(found) == [("invalid_value", "company.net/mnemonic")]
    assert "adoption does" in found[0]["detail"]


def test_a_suffix_key_that_cmapi_does_not_fill_in_is_fixed_on_a_change():
    keys = MetadataKeys({**RAW, "requiredLabels": {**RAW["requiredLabels"], "company.net/lob": {
        "pattern": "^[a-z]{2,8}$", "namespaceSuffix": True, "example": "dev"}}})
    current = {**CHANGE, "current_labels": {**GIT, "company.net/lob": "dev"}}
    assert keys.validate({"company.net/lob": "dev"}, {}, **current) == []
    assert errors(keys.validate({"company.net/lob": "qa"}, {}, **current)) == [("invalid_value", "company.net/lob")]


def test_a_filled_in_key_sent_back_as_git_holds_it_is_accepted_after_its_source_moved():
    moved = {**CHANGE, "current_labels": {**GIT, "company.net/app-environment": "rnd"}}
    assert KEYS.validate({"company.net/app-environment": "rnd"}, {}, **moved) == []
    assert errors(KEYS.validate({"company.net/app-environment": "qa"}, {}, **moved)) == \
        [("derived_key", "company.net/app-environment")]


def test_a_required_key_changes_to_a_valid_value_and_is_never_removed():
    assert KEYS.validate({"company.net/cl": "2"}, {}, **CHANGE) == []
    assert errors(KEYS.validate({"company.net/cl": "9"}, {}, **CHANGE)) == [("invalid_value", "company.net/cl")]
    assert errors(KEYS.validate({"company.net/lob": None}, {}, **CHANGE)) == [("missing_required_key", "company.net/lob")]


def test_an_extra_key_and_an_allow_other_key_are_added_changed_and_removed():
    patch = {"cmapi.net/cost-center": None, "team.company.net/squad": "checkout", "squad": "a"}
    assert KEYS.validate(patch, {"runbook.company.net/url": "https://wiki.company.net/abc"}, **CHANGE) == []


# ---------------------------------------------------------------- section 4.1: metadataDiff

def test_the_metadata_diff_lists_each_effective_change_with_before_after_and_source():
    before = {"label": {**GIT, "cmapi.net/tier": "small"}, "annotation": {}}
    after = {"label": {**GIT, "company.net/cl": "2", "cmapi.net/tier": "large", "cmapi.net/cost-center": None},
             "annotation": {"runbook.company.net/url": "https://wiki.company.net/abc"}}
    after["label"] = {k: v for k, v in after["label"].items() if v is not None}
    sent = {"label": {"company.net/cl": "2", "company.net/lob": "amgsst", "cmapi.net/cost-center": None},
            "annotation": {"runbook.company.net/url": "https://wiki.company.net/abc"}}
    assert KEYS.metadata_diff(before, after, sent) == {
        "labels": {"cmapi.net/cost-center": {"before": "cc-4410", "after": None, "source": "request"},
                   "company.net/cl": {"before": "1", "after": "2", "source": "request"}},
        "annotations": {"runbook.company.net/url": {"before": None, "after": "https://wiki.company.net/abc",
                                                    "source": "request"}}}


def test_the_metadata_diff_names_a_filled_in_key_that_cmapi_moved_by_its_source():
    before = {"label": {**GIT, "company.net/app-environment": "rnd"}, "annotation": {}}
    diff = KEYS.metadata_diff(before, {"label": GIT, "annotation": {}}, {"label": {}, "annotation": {}})
    assert diff["labels"] == {"company.net/app-environment": {"before": "rnd", "after": "dev", "source": "environment"}}


def test_the_held_keys_are_the_required_keys_that_the_namespace_lacks():
    lacking = {k: v for k, v in GIT.items() if k not in ("company.net/lob", "name")}
    assert KEYS.missing_required(lacking, {}) == [("label", "name"), ("label", "company.net/lob"), ("annotation", "cmapi.net/team-dl")]


# ---------------------------------------------------------------- section 4.2: the sync state

LIVE = {"label": dict(GIT), "annotation": {}}
HOLDER = {"requestId": "req-20261120-0001", "status": "merged"}


def test_the_sync_state_is_decided_in_the_designs_order():
    drift = [{"kind": "label", "key": "company.net/lob", "git": "amgsst", "live": "x"}]
    assert sync_state(HOLDER, True, drift) == "pending"
    assert sync_state(None, True, drift) == "drift"
    assert sync_state(None, True, []) == "in-sync"
    assert sync_state(None, False, []) == "unknown"
    assert sync_state(HOLDER, False, []) == "pending"


def test_a_hand_label_on_the_cluster_is_drift_with_both_values():
    live = {"label": {**GIT, "company.net/lob": "amgsst-old", "team.company.net/squad": "x"}, "annotation": {}}
    view = sync_view(KEYS, {"label": GIT, "annotation": {}}, live, None, True)
    assert view == {"state": "drift", "openRequest": None, "driftedKeys": [
        {"kind": "label", "key": "company.net/lob", "git": "amgsst", "live": "amgsst-old"},
        {"kind": "label", "key": "team.company.net/squad", "git": None, "live": "x"}]}


def test_an_unsynced_merge_is_pending_with_the_keys_the_cluster_lacks():
    git = {"label": {**GIT, "company.net/cl": "2"}, "annotation": {}}
    view = sync_view(KEYS, git, LIVE, HOLDER, True)
    assert view["state"] == "pending" and view["openRequest"] == HOLDER
    assert view["driftedKeys"] == [{"kind": "label", "key": "company.net/cl", "git": "2", "live": "1"}]


def test_system_reserved_and_live_only_keys_are_not_drift():
    live = {"label": {**GIT, "cmapi.net/tier": "large", "kubernetes.io/metadata.name": "abc-payments-dev"},
            "annotation": {"openshift.io/sa.scc.uid-range": "1000/1000", "argocd.argoproj.io/tracking-id": "x"}}
    assert sync_view(KEYS, {"label": GIT, "annotation": {}}, live, None, True)["state"] == "in-sync"


def test_a_live_only_key_that_allow_other_admits_is_not_drift_once_listed():
    keys = MetadataKeys({**RAW, "liveOnlyKeys": ["*.company.net/controller-*"]})
    live = {"label": {**GIT, "ops.company.net/controller-seen": "yes"}, "annotation": {}}
    assert sync_view(KEYS, {"label": GIT, "annotation": {}}, live, None, True)["state"] == "drift"
    assert sync_view(keys, {"label": GIT, "annotation": {}}, live, None, True)["state"] == "in-sync"


def test_a_stale_watch_or_no_git_is_unknown_and_compares_nothing():
    live = {"label": {**GIT, "company.net/lob": "x"}, "annotation": {}}
    assert sync_view(KEYS, {"label": GIT, "annotation": {}}, live, None, False) == \
        {"state": "unknown", "openRequest": None, "driftedKeys": []}
    assert sync_view(KEYS, None, live, None, True)["state"] == "unknown"


def test_live_only_keys_default_to_the_designs_list_and_the_loader_refuses_a_text():
    assert KEYS.live_only == list(DEFAULT_LIVE_ONLY_KEYS)
    assert MetadataKeys({**RAW, "liveOnlyKeys": None}).live_only == []
    with pytest.raises(ValueError, match="liveOnlyKeys must be a list of text"):
        MetadataKeys({**RAW, "liveOnlyKeys": "openshift.io/*"})


# ---------------------------------------------------------------- section 4.4: the lookup

def test_the_mnemonic_is_the_value_of_the_namespace_prefix_key_whatever_its_name():
    assert KEYS.mnemonic(GIT, {}) == "abc"
    keys = MetadataKeys({"requiredAnnotations": {"acme.io/code": {"pattern": "^[a-z]{2}$", "namespacePrefix": True,
                                                                  "example": "pa"}}})
    assert keys.mnemonic({}, {"acme.io/code": "pa"}) == "pa"
    assert MetadataKeys({}).mnemonic(GIT, {}) is None


def test_ranked_puts_names_that_start_with_q_first_then_names_that_contain_it_then_team_matches():
    rows = [{"name": n, "clusterId": "CRC", "team": t, "app": None}
            for n, t in (("xyz-pay-dev", None), ("abc-orders-dev", "payroll"), ("pay-dev", None), ("abc-pay-dev", None))]
    ranked = Lister(b"k").ranked(rows, ListQuery(q="pay"))
    assert [r["name"] for r in ranked] == ["pay-dev", "abc-pay-dev", "xyz-pay-dev", "abc-orders-dev"]
