"""The review of #492 (#483, the change of an existing namespace's metadata), through the API on the service suite's world
with PostgreSQL, and the Helm chart. The configuration is the #479 design's company.net file, as in
test_namespace_patch_contract_483: name and both app-environment keys are filled in, the mnemonic starts the name, and
company.net/cl is sensitive. Each test names the guarantee that one review fix adds; the MetadataKeys-only ones are in
tests/core/test_namespace_patch_review_492.py."""
from __future__ import annotations

from datetime import date, timedelta

import yaml

from cmapi.core.metadata import DEFAULT_LIVE_ONLY_KEYS, MetadataKeys
from cmapi.plugins.expiration.rules import utc_today
from test_flow import OPAL
from test_helm_metadata_values import _chart_keys, _helm, _rendered_keys
from test_namespace_contract_479 import URL, design_config, design_world  # noqa: F401  (fixtures)
from test_namespace_patch_contract_483 import (NS, NS_FILE, create, errors_of, headers, lookup, names, patch,
                                               planned_namespace, put_live, read, relist)

APP_ENV = "company.net/app-environment"


def edit_git(world, change) -> None:
    """Change namespace.yaml on Git's main, as a hand edit or another tool would."""
    git = world[2]
    doc = yaml.safe_load(git.branches["main"][NS_FILE])
    change(doc["metadata"])
    git.branches["main"][NS_FILE] = yaml.safe_dump(doc, sort_keys=False)


def set_expiry_dry_run(world):
    """The expiry call :set as a dry run, with the etag of the current read."""
    client, ctx, git, kube, validator, keys = world
    until = (utc_today() + timedelta(days=20)).isoformat()
    return client.post(f"{URL}/{NS}/expiration:set?dryRun=true", json={"until": until},
                       headers=headers(keys, etag=read(world)["etag"]))


def missing_key_messages(r) -> list[str]:
    assert r.status_code == 200, r.text
    return [f["message"] for f in r.json()["findings"] if f["rule"] == "missing_required_key"]


# --------------------------------------------------------------------------- F01: automatic keys are fixed on a change

def test_a_change_keeps_the_automatic_keys_that_git_holds_and_accepts_only_their_echo(design_world):
    create(design_world)

    def moved(meta):                                  # Git written before the cluster's environment became dev
        meta["labels"][APP_ENV] = meta["annotations"][APP_ENV] = "rnd"
    edit_git(design_world, moved)
    r = patch(design_world, {"labels": {"company.net/cl": "0"}})
    meta = planned_namespace(r)
    assert meta["labels"][APP_ENV] == meta["annotations"][APP_ENV] == "rnd"
    assert r.json()["metadataDiff"] == {"labels": {"company.net/cl": {"before": "1", "after": "0", "source": "request"}},
                                        "annotations": {}}
    echo = patch(design_world, {"labels": {APP_ENV: "rnd", "company.net/cl": "0"}, "annotations": {APP_ENV: "rnd"}})
    assert list(echo.json()["metadataDiff"]["labels"]) == ["company.net/cl"] and echo.json()["metadataDiff"]["annotations"] == {}
    assert errors_of(patch(design_world, {"labels": {APP_ENV: "dev"}})) == [("derived_key", APP_ENV)]
    expiry = yaml.safe_load(set_expiry_dry_run(design_world).json()["files"][NS_FILE])["metadata"]
    assert expiry["labels"][APP_ENV] == "rnd"         # the expiry calls render through the same path


def test_a_create_still_fills_in_the_automatic_keys_from_its_target(design_world):
    view = create(design_world)
    assert view["git"]["labels"]["name"] == NS
    assert view["git"]["labels"][APP_ENV] == view["git"]["annotations"][APP_ENV] == "dev"


# --------------------------------------------------------------------------- F02: the namespace is namespace.yaml itself

def test_a_change_and_a_delete_read_namespace_yaml_not_a_file_whose_name_ends_with_it(design_world):
    client, ctx, git, kube, validator, keys = design_world
    create(design_world)
    edit_git(design_world, lambda meta: meta["labels"].update({"cmapi.net/protected": "true"}))
    lookalike = NS_FILE.replace("namespace.yaml", "allow-same-namespace.yaml")      # a hand-added NetworkPolicy
    policy = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
              "metadata": {"name": "allow-same-namespace", "namespace": NS, "labels": {"cmapi.net/managed": "true"}},
              "spec": {"podSelector": {}}}
    git.branches["main"] = {lookalike: yaml.safe_dump(policy), **git.branches["main"]}       # read first
    meta = planned_namespace(patch(design_world, {"labels": {"company.net/cl": "0"}}))
    assert meta["labels"]["company.net/lob"] == "amgsst" and meta["labels"]["company.net/mnemonic"] == "abc"
    assert meta["labels"]["cmapi.net/protected"] == "true"
    d = client.delete(f"{URL}/{NS}", headers=headers(keys, etag=read(design_world)["etag"]))
    assert d.status_code == 422 and d.json()["code"] == "namespace-protected", d.text


# --------------------------------------------------------------------------- F04: a sensitive key added on a change

def test_adding_a_sensitive_key_to_an_existing_namespace_adds_one_approval_and_a_first_protection_none(design_world):
    create(design_world)
    edit_git(design_world, lambda meta: meta["labels"].pop("company.net/cl"))      # adopted without a critical level

    def sensitive_slots(body) -> list[tuple[str, int]]:
        r = patch(design_world, {"labels": body}, user="opal", who=OPAL)
        assert r.status_code == 200, r.text
        return [(s["group"], s["count"]) for s in r.json()["approval"]["slots"] if s["reason"] == "Sensitive key changed"]

    assert sensitive_slots({"company.net/cl": "2"}) == [("approver-platform", 1)]
    assert sensitive_slots({"cmapi.net/protected": "true"}) == []


# --------------------------------------------------------------------------- F06: liveOnlyKeys may be left out in Helm

def test_a_helm_metadata_block_written_before_live_only_keys_still_lints_renders_and_loads(tmp_path):
    block = _chart_keys()
    del block["liveOnlyKeys"]
    lint = _helm("lint", tmp_path, {"metadata": block})
    assert lint.returncode == 0, lint.stdout + lint.stderr
    assert MetadataKeys(_rendered_keys(tmp_path, {"metadata": block})).live_only == list(DEFAULT_LIVE_ONLY_KEYS)
    block["liveOnlyKeys"] = []                        # an explicit empty list still compares every key
    assert MetadataKeys(_rendered_keys(tmp_path, {"metadata": block})).live_only == []


# --------------------------------------------------------------------------- F10: no Git, nothing to compare

def test_a_live_namespace_that_git_does_not_hold_has_an_unknown_sync(design_world):
    client, ctx, git, kube, validator, keys = design_world
    put_live(kube, "abc-bare-dev", {})
    put_live(kube, "abc-team-dev", {"company.net/lob": "amgsst"})
    relist(ctx)
    for name in ("abc-bare-dev", "abc-team-dev"):
        view = read(design_world, name)
        assert view["git"] is None
        assert view["sync"] == {"state": "unknown", "openRequest": None, "driftedKeys": []}, name


# --------------------------------------------------------------------------- F11: the lookup's exact mnemonic and limit

def test_the_mnemonic_filter_compares_values_and_an_empty_q_is_capped(design_world):
    client, ctx, git, kube, validator, keys = design_world
    put_live(kube, "aaa-one-dev", {})                                   # no mnemonic
    put_live(kube, "bbb-two-dev", {"company.net/mnemonic": "None"})     # the text None
    relist(ctx)
    r = lookup(design_world, "mnemonic=None")
    assert names(r) == ["bbb-two-dev"] and r.json()["total"] == 1
    for i in range(10):
        put_live(kube, f"abc-app{i:02d}-dev", {"company.net/mnemonic": "abc"})
    relist(ctx)
    assert len(names(lookup(design_world))) == 12                       # no parameter: every namespace, as before
    assert len(names(lookup(design_world, "q="))) == 10                 # q sent, even empty: the default limit


# --------------------------------------------------------------------------- F12: the adoption finding of a fixed key

def test_a_missing_key_says_how_a_request_adds_it_with_the_derived_value_the_name_start_or_any_valid_value(design_world):
    create(design_world)

    def adopted(meta):                                # made by another tool: no name, mnemonic or line of business
        for key in ("name", "company.net/mnemonic", "company.net/lob"):
            meta["labels"].pop(key)
    edit_git(design_world, adopted)
    assert missing_key_messages(patch(design_world, {"labels": {"company.net/cl": "0"}})) == [
        "the label name is required and the namespace lacks it: a request can add it with the value cmapi derives from the "
        "namespace (abc-payments-dev)",
        "the label company.net/mnemonic is required and the namespace lacks it: a request can add it with the start of the "
        "namespace name",
        "the label company.net/lob is required and the namespace lacks it: a request can add it"]


# --------------------------------------------------------------------------- M1: no adoption finding on an expiry call

def test_an_expiry_call_reports_no_adoption_finding_since_its_body_cannot_add_a_key(design_world):
    create(design_world)
    edit_git(design_world, lambda meta: meta["labels"].pop("company.net/lob"))
    assert missing_key_messages(set_expiry_dry_run(design_world)) == []
    assert missing_key_messages(patch(design_world, {"labels": {"company.net/cl": "0"}})) == [
        "the label company.net/lob is required and the namespace lacks it: a request can add it"]


# --------------------------------------------------------------------------- M2: removing a disallowed key that Git holds

def test_a_change_can_remove_a_disallowed_key_that_git_holds_and_the_diff_shows_it(design_world):
    create(design_world)
    edit_git(design_world, lambda meta: meta["labels"].update({"old.invalid/key": "legacy"}))
    kept = patch(design_world, {"labels": {"company.net/cl": "0"}})
    assert planned_namespace(kept)["labels"]["old.invalid/key"] == "legacy"           # D6: kept when not named
    r = patch(design_world, {"labels": {"old.invalid/key": None}})
    assert "old.invalid/key" not in planned_namespace(r)["labels"]
    assert r.json()["metadataDiff"]["labels"] == {"old.invalid/key": {"before": "legacy", "after": None, "source": "request"}}
    assert errors_of(patch(design_world, {"labels": {"old.invalid/key": "again"}})) == [("invalid_key", "old.invalid/key")]


def test_a_fixed_key_that_git_holds_empty_is_reported_as_kept_since_a_change_cannot_replace_it(design_world):
    """#732 (R1 F3): Git's value of a fixed or automatic key stays (#481), an empty one too, so its finding does not offer
    the addition that a change of a missing key gets: the change that the finding would advertise is refused."""
    create(design_world)
    edit_git(design_world, lambda meta: meta["labels"].update({"name": "", "company.net/mnemonic": ""}))
    assert missing_key_messages(patch(design_world, {"labels": {"company.net/cl": "0"}})) == [
        "the required label name is empty in Git: a change keeps that value",
        "the required label company.net/mnemonic is empty in Git: a change keeps that value"]
    assert errors_of(patch(design_world, {"labels": {"name": NS}})) == [("derived_key", "name")]
    assert errors_of(patch(design_world, {"labels": {"company.net/mnemonic": "abc"}})) == [
        ("invalid_value", "company.net/mnemonic")]
