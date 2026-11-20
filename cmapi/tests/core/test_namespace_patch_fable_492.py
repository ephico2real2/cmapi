"""The third review of #492 (#483, the change of an existing namespace's metadata), on MetadataKeys and the sync state
alone: a key that Git holds under the wrong kind can be removed (the M2 ruling, design section 3, row 3), and a namespace
that the cluster does not have is never in-sync (design section 4.2). The routes' side is in
tests/service/test_namespace_patch_fable_492.py."""
from __future__ import annotations

import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.plugins.namespaces.state import sync_view
from test_namespace_patch_483 import CHANGE, GIT, HOLDER, KEYS, RAW, errors
from test_policygen import catalog, kyverno  # noqa: F401  (fixtures)

WRONG_KIND = "cmapi.net/team-dl"                      # RAW declares it for annotations only
ANNOTATIONS = {WRONG_KIND: "payments-team@company.net"}


def keys_with_label_prefixes(prefixes: list[str]) -> MetadataKeys:
    return MetadataKeys({**RAW, "extraLabels": {**RAW["extraLabels"], "allowOther": {"prefixes": prefixes, "max": 50}}})


# ------------------------------------------- F-1: a key that Git holds under the wrong kind can be removed, never set

def test_a_label_that_git_holds_under_an_annotations_key_can_be_removed_but_never_set():
    held = {**GIT, WRONG_KIND: "payments-team"}       # a hand edit, or a namespace from before the key was an annotation
    for prefixes, cls in ((["", "*.company.net/"], "disallowed"), (["", "*.company.net/", "cmapi.net/"], "team")):
        keys = keys_with_label_prefixes(prefixes)
        assert keys.classify(WRONG_KIND, "label") == cls

        def check(sent: dict, current: dict) -> list[tuple[str, str]]:
            return errors(keys.validate(sent, {}, operator=False, existing=True, current_labels=current,
                                        current_annotations=ANNOTATIONS,
                                        sources={"namespace": "abc-payments-dev", "environment": "dev"}))

        assert check({WRONG_KIND: None}, held) == [], cls                                # removed: within the rules again
        assert check({WRONG_KIND: "other"}, held) == [("invalid_key", WRONG_KIND)], cls  # never changed
        assert check({WRONG_KIND: "payments-team"}, GIT) == [("invalid_key", WRONG_KIND)], cls   # never set
        assert check({WRONG_KIND: None}, GIT) == [("invalid_key", WRONG_KIND)], cls      # Git lacks it: nothing to remove
        after = {k: v for k, v in held.items() if k != WRONG_KIND}
        diff = keys.metadata_diff({"label": held, "annotation": ANNOTATIONS}, {"label": after, "annotation": ANNOTATIONS},
                                  {"label": {WRONG_KIND: None}, "annotation": {}})
        assert diff == {"labels": {WRONG_KIND: {"before": "payments-team", "after": None, "source": "request"}},
                        "annotations": {}}, cls                                          # the annotation stays


def test_the_plan_time_policy_reports_a_label_under_an_annotations_key_on_every_change(kyverno, catalog, tmp_path):
    """Why the removal must be possible, as for M2: the other-keys policy has no ratchet, so in enforce every change of a
    namespace that holds such a label is refused, and before this fix no request could remove it."""
    from cmapi.core.policy import PolicySettings
    from test_policygen import validator
    from test_review_479_suffix_policy import rendered, suffix_keys

    keys = suffix_keys()
    key = next(k for k in keys.rules["annotation"]
               if k not in keys.rules["label"] and keys.classify(k, "label") == "disallowed")
    path = "clusters/OCP_GF15/namespaces/abc-legacy-rnd/namespace.yaml"
    now = rendered(catalog, keys, "abc-legacy-rnd")
    doc = yaml.safe_load(now[path])
    doc["metadata"]["labels"][key] = "legacy"
    now[path] = yaml.safe_dump(doc)
    found = validator(catalog, keys, tmp_path / "enforce", policy=PolicySettings(default_mode="enforce")).validate(
        now, "OCP_GF15", "rnd", previous=dict(now))                    # unchanged from Git
    assert [(f.rule, f.severity) for f in found if f.source == "kyverno"] == [
        ("cmapi-metadata-rnd-label-other-keys-prefix", "error")]
    held = {k: v for k, v in doc["metadata"]["labels"].items() if keys.classify(k, "label") != "system"}
    assert keys.validate({key: None}, {}, operator=False, existing=True, current_labels=held,
                         current_annotations=doc["metadata"]["annotations"]) == []


def test_the_removal_of_a_key_that_git_holds_never_reaches_a_reserved_an_adoption_or_a_system_key():
    """Claim 3 of the review: null removes a key that no stanza allows, and only that. A key of a reserved prefix, an
    adoption label and a system key are refused whatever Git holds."""
    labels = {**GIT, "kubernetes.io/role": "infra", "company.net/provisioner": "cluster-configs", "cmapi.net/tier": "small",
              "old.invalid/key": "legacy"}
    annotations = {**CHANGE["current_annotations"], "openshift.io/node-selector": "zone=a"}
    change = {**CHANGE, "current_labels": labels, "current_annotations": annotations}
    for key in ("kubernetes.io/role", "company.net/provisioner", "cmapi.net/tier"):
        assert errors(KEYS.validate({key: None}, {}, **change)) == [("reserved_key", key)]
    assert errors(KEYS.validate({}, {"openshift.io/node-selector": None}, **change)) == \
        [("reserved_key", "openshift.io/node-selector")]
    assert KEYS.validate({"old.invalid/key": None}, {}, **change) == []                 # the one class that null removes


# --------------------------------------------------- F-2: a namespace that the cluster does not have is never in-sync

def test_a_namespace_that_the_cluster_does_not_have_is_drift_never_in_sync():
    bare = {"label": {"cmapi.net/tier": "small"}, "annotation": {}}    # Git holds no key that a request may name
    absent = {"label": {}, "annotation": {}}                           # what the read compares when the cluster lacks it
    assert sync_view(KEYS, bare, absent, None, True, on_cluster=False) == \
        {"state": "drift", "openRequest": None, "driftedKeys": []}
    assert sync_view(KEYS, bare, absent, HOLDER, True, on_cluster=False)["state"] == "pending"   # a create not synced yet
    assert sync_view(KEYS, bare, absent, None, False, on_cluster=False)["state"] == "unknown"    # the watch is not fresh
    assert sync_view(KEYS, bare, absent, None, True)["state"] == "in-sync"                       # on the cluster, the same
    named = sync_view(KEYS, {"label": GIT, "annotation": {}}, absent, None, True, on_cluster=False)
    assert named["state"] == "drift" and len(named["driftedKeys"]) == len(GIT)                   # as before the fix
