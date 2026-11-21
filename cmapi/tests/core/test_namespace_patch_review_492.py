"""The review of #492 (#483, the change of an existing namespace's metadata): the guarantees that its fixes add, on
MetadataKeys and the renderer alone (design docs/reviews/2026-11-20-epic-481-metadata-patch/design.md, section 3).
The rest, which needs the pipeline and the routes, is in tests/service/test_namespace_patch_review_492.py."""
from __future__ import annotations

import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.core.render.manifests import ManifestRenderer
from test_policygen import catalog, kyverno  # noqa: F401  (fixtures)
from test_render_listquery_config import FOLDER, renderer, spec  # noqa: F401  (renderer is a fixture)

AUTOMATIC = MetadataKeys({"requiredLabels": {"app-env": {"value": {"from": "environment"}},
                                             "name": {"value": {"from": "namespace"}}},
                          "requiredAnnotations": {"app-env": {"value": {"from": "environment"}}}})


# ---------------------------------------------------------------- F01: an automatic key is fixed on a change (row 5)

def test_a_change_keeps_each_automatic_key_as_git_holds_it_and_a_create_fills_it(renderer):
    render = ManifestRenderer(renderer.catalog, AUTOMATIC)
    path = FOLDER + "namespace.yaml"
    files = render.render(spec())                                     # a create: filled in from the target
    created = yaml.safe_load(files[path])["metadata"]
    assert created["labels"]["app-env"] == created["annotations"]["app-env"] == "dev"
    assert created["labels"]["name"] == "payments-dev"
    for field in ("labels", "annotations"):                           # Git from before the cluster moved to dev
        created[field]["app-env"] = "rnd"
    del created["labels"]["name"]                                     # and from before the key was configured
    files[path] = yaml.safe_dump({"apiVersion": "v1", "kind": "Namespace", "metadata": created})
    for sent in ({}, {"app-env": "rnd"}):                             # left out, or sent back as Git holds it
        changed = render.render(spec(tier="large", labels={**spec().labels, **sent},
                                     annotations={**spec().annotations, **sent}), previous=files)
        meta = yaml.safe_load(changed[path])["metadata"]
        assert meta["labels"]["app-env"] == meta["annotations"]["app-env"] == "rnd", sent
        assert "name" not in meta["labels"], sent


def test_a_change_accepts_only_gits_value_of_an_automatic_key():
    git = {"app-env": "rnd"}
    target = {"environment": "dev", "namespace": "payments-dev"}

    def codes(labels, current):
        return [(e["code"], e["key"]) for e in AUTOMATIC.validate(labels, {}, operator=False, current_labels=current,
                                                                   sources=target, existing=True)]

    assert codes({"app-env": "rnd"}, git) == []                       # the echo of Git
    assert codes({"app-env": "dev"}, git) == [("derived_key", "app-env")]   # today's target is not Git's value
    assert codes({"name": "payments-dev"}, git) == [("derived_key", "name")]   # Git lacks it: adoption adds it
    assert codes({"app-env": None}, git) == [("derived_key", "app-env")]
    create = AUTOMATIC.validate({"app-env": "dev"}, {}, operator=False, sources=target, create=True)
    assert create == []                                               # a create still takes the target's value


def test_a_mnemonic_sent_back_is_accepted_even_when_todays_rule_refuses_it():
    keys = MetadataKeys({"requiredLabels": {"code": {"namespacePrefix": True, "pattern": "^[a-z]{3}$", "example": "abc"}}})
    git = {"code": "ab"}                                              # named before the rule had three letters
    assert keys.validate({"code": "ab"}, {}, operator=False, existing=True, current_labels=git) == []
    refused = keys.validate({"code": "abc"}, {}, operator=False, existing=True, current_labels=git)
    assert [(e["code"], e["key"], e["detail"]) for e in refused] == [
        ("invalid_value", "code", "part of the namespace's fixed name: a change keeps 'ab'")]
    removed = keys.validate({"code": None}, {}, operator=False, existing=True, current_labels=git)
    assert [(e["code"], e["key"]) for e in removed] == [("missing_required_key", "code")]   # once, as before (D5)


# ---------------------------------------------------------------- F04: a sensitive key added to an existing namespace

def test_a_sensitive_key_added_to_an_existing_namespace_counts_and_a_first_protection_does_not():
    keys = MetadataKeys({"operatorOnly": ["shield"], "sensitiveKeys": ["owner", "zone.example.org/net", "shield"],
                         "extraLabels": {"keys": {"owner": {}}, "allowOther": {"prefixes": ["*.example.org/"], "max": 5}},
                         "extraAnnotations": {"allowOther": {"prefixes": ["*.example.org/"], "max": 5}}})

    def counts(before, after, before_ann=None, after_ann=None, *, existing=True):
        return keys.change_facts(before, after, before_ann or {}, after_ann or {}, existing=existing)["sensitiveKeyChanged"]

    assert counts({}, {"owner": "abc"}) is True                       # an extra key added (row 8)
    assert counts({}, {}, {}, {"zone.example.org/net": "south"}) is True     # an allowOther annotation added (row 9)
    assert counts({"owner": "abc"}, {"owner": "xyz"}) is True         # changed, as before
    assert counts({"owner": "abc"}, {}) is True                       # removed, as before
    assert counts({}, {"shield": "true"}) is False                    # an operator protects: no approval (#366)
    assert counts({"shield": "true"}, {}) is True                     # removing the protection: one approval (#366)
    assert counts({}, {"owner": "abc"}, existing=False) is False      # a create's first value is not a change


# ---------------------------------------------------------------- F05: a reserved prefix comes before operatorOnly

def test_a_reserved_prefix_wins_over_operator_only_in_the_check_and_the_schema():
    key = "ops.example.org/owner"
    keys = MetadataKeys({"reservedPrefixes": ["*.example.org/"], "operatorOnly": [key]})
    for kind in ("label", "annotation"):
        assert keys.classify(key, kind) == "reserved"
        assert keys.edit_rule(kind, key)["mode"] == "fixed"
        assert key not in keys.json_schema(kind, "patch")["properties"]
        labels, annotations = ({key: "new"}, {}) if kind == "label" else ({}, {key: "new"})
        errors = keys.validate(labels, annotations, operator=True, existing=True)
        assert [(e["code"], e["key"]) for e in errors] == [("reserved_key", key)]


# ---------------------------------------------------------------- F12: the adoption finding of a fixed key

def test_the_required_keys_that_a_namespace_lacks_include_the_automatic_ones():
    assert AUTOMATIC.missing_required({}, {}) == [("label", "app-env"), ("label", "name"), ("annotation", "app-env")]
    assert AUTOMATIC.missing_required({"app-env": "rnd", "name": "x"}, {"app-env": "rnd"}) == []


# ---------------------------------------------------------------- M2: a disallowed key that Git holds can be removed

def test_a_disallowed_key_that_git_holds_can_be_removed_but_never_set():
    keys = MetadataKeys({"extraLabels": {"allowOther": {"prefixes": ["*.example.org/"], "max": 5}}})
    git = {"old.invalid/key": "legacy"}                               # allowed by an older allowOther, or a hand edit
    assert keys.validate({"old.invalid/key": None}, {}, operator=False, existing=True, current_labels=git) == []
    for sent, current in (({"old.invalid/key": "other"}, git), ({"new.invalid/key": "x"}, {}), ({"new.invalid/key": None}, {})):
        errors = keys.validate(sent, {}, operator=False, existing=True, current_labels=current)
        assert [(e["code"], e["key"]) for e in errors] == [("invalid_key", next(iter(sent)))], sent
    diff = keys.metadata_diff({"label": git, "annotation": {}}, {"label": {}, "annotation": {}},
                              {"label": {"old.invalid/key": None}, "annotation": {}})
    assert diff["labels"] == {"old.invalid/key": {"before": "legacy", "after": None, "source": "request"}}


def test_the_plan_time_policy_keeps_a_disallowed_key_that_git_holds(kyverno, catalog, tmp_path):
    """Before #497 the other-keys policy had no ratchet, so a kept key was a warning in audit (which stopped auto-approval)
    and a refusal in enforce, on every change of the namespace. Now an unchanged held key gives no finding in either."""
    from cmapi.core.policy import PolicySettings
    from test_policygen import validator
    from test_review_479_suffix_policy import rendered, suffix_keys

    keys = suffix_keys()
    path = "clusters/OCP_GF15/namespaces/abc-legacy-rnd/namespace.yaml"
    now = rendered(catalog, keys, "abc-legacy-rnd")
    doc = yaml.safe_load(now[path])
    doc["metadata"]["labels"]["old.invalid/key"] = "legacy"
    now[path] = yaml.safe_dump(doc)
    for mode, severity in (("audit", "warning"), ("enforce", "error")):
        found = validator(catalog, keys, tmp_path / mode, policy=PolicySettings(default_mode=mode)).validate(
            now, "OCP_GF15", "rnd", previous=dict(now))                # unchanged from Git
        assert [(f.rule, f.severity) for f in found if f.source == "kyverno"] == [], (mode, severity)
