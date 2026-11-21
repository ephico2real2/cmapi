"""#528: the namespace read says how each key that Git holds and metadata-keys.yaml does not declare may change, so the
Namespaces tab (#484) can tell cmapi's own keys from a team's and offer design section 3, row 3's removal (#492 M2).
On the #479 design's company.net file (test_namespace_contract_479.DESIGN) and the service suite's world with PostgreSQL."""
from __future__ import annotations

from test_namespace_contract_479 import design_config, design_world  # noqa: F401  (fixtures)
from test_namespace_patch_contract_483 import create, errors_of, patch, planned_namespace, read
from test_namespace_patch_review_492 import edit_git

FIXED_SYSTEM = {"mode": "fixed", "reason": "Managed by cmapi.", "sensitive": False, "removable": False}


def test_the_read_gives_the_edit_rule_of_each_undeclared_key_that_git_holds(design_world):
    create(design_world)
    edit_git(design_world, lambda meta: meta["labels"].update({"team.company.net/squad": "checkout", "old.invalid/key": "legacy",
                                                                "company.net/provisioner": "cluster-configs"}))
    edits = read(design_world)["git"]["edits"]
    assert edits["labels"]["cmapi.net/managed"] == FIXED_SYSTEM
    assert edits["labels"]["team.company.net/squad"] == {"mode": "optional", "reason": None, "sensitive": False, "removable": False}
    assert edits["labels"]["old.invalid/key"] == {"mode": "fixed", "reason": "Not allowed by this instance's rules.", "sensitive": False,
                                                  "removable": True}
    assert edits["labels"]["company.net/provisioner"] == {"mode": "fixed", "reason": "Marks how the namespace was first made.",
                                                          "sensitive": False, "removable": False}
    assert edits["annotations"]["argocd.argoproj.io/sync-options"] == {"mode": "fixed", "reason": "Reserved for the platform.",
                                                                       "sensitive": False, "removable": False}
    # Governed keys stay in GET /api/v1/metadata-keys; held operator-only keys also have contextual reasons here (#532).
    assert "company.net/cl" not in edits["labels"] and "cmapi.net/team-dl" not in edits["annotations"]


def test_a_removable_key_is_one_that_the_api_lets_a_change_remove_and_never_set(design_world):
    create(design_world)
    edit_git(design_world, lambda meta: meta["labels"].update({"old.invalid/key": "legacy"}))
    assert read(design_world)["git"]["edits"]["labels"]["old.invalid/key"]["removable"] is True
    assert "old.invalid/key" not in planned_namespace(patch(design_world, {"labels": {"old.invalid/key": None}}))["labels"]
    assert errors_of(patch(design_world, {"labels": {"old.invalid/key": "again"}})) == [("invalid_key", "old.invalid/key")]
    assert errors_of(patch(design_world, {"labels": {"cmapi.net/managed": None}})) != [], "a system key is not removable"


def test_detail_and_declared_edit_rules_against_real_patch(design_world):
    from test_flow import OPAL
    from test_namespace_patch_contract_483 import headers

    create(design_world, labels={"cmapi.net/cost-center": "cc-4410", "team.company.net/squad": "checkout"})
    edit_git(design_world, lambda m: m["labels"].update({"old.invalid/key": "old", "company.net/provisioner": "legacy"}))
    edit_git(design_world, lambda m: m["annotations"].update({"name": "legacy", "do-not-delete": "old"}))
    view = read(design_world)
    schema = design_world[0].get("/api/v1/metadata-keys", headers=headers(design_world[-1])).json()
    cases = [
        ("labels", "cmapi.net/managed", "false", "fixed"),
        ("annotations", "argocd.argoproj.io/sync-options", "other", "fixed"),
        ("labels", "company.net/provisioner", "other", "fixed"),
        ("labels", "old.invalid/key", "other", "remove"),
        ("annotations", "name", "other", "remove"),
        ("annotations", "do-not-delete", "new", "operator"),
        ("labels", "name", "other", "automatic"),
        ("labels", "company.net/app-environment", "qa", "automatic"),
        ("labels", "company.net/mnemonic", "xyz", "prefix"),
        ("labels", "company.net/cl", "2", "required"),
        ("labels", "cmapi.net/cost-center", "cc-5555", "optional"),
        ("labels", "team.company.net/squad", "new", "optional"),
    ]
    for kind, key, value, expected in cases:
        prop = schema[kind]["properties"].get(key)
        edit = prop["x-cmapi-edit"] if prop else view["git"]["edits"][kind][key]
        mode = edit["mode"]
        assert mode == {"remove": "fixed", "operator": "optional", "prefix": "fixed"}.get(expected, expected)
        assert bool(edit.get("removable")) == (expected == "remove")
        for new in (value, None, view["git"][kind][key]):
            # An independent effective edit makes an accepted echo distinguishable from a no-change 422.
            body = {"labels": {"company.net/lob": "retail"}}
            body.setdefault(kind, {})[key] = new
            allowed = mode == "optional" or (mode == "required" and new is not None)
            if expected in ("prefix", "automatic"):
                allowed = new == view["git"][kind][key]
            if expected == "remove":
                allowed = new is None
            if prop and prop.get("x-cmapi-operator-only"):
                assert patch(design_world, body).status_code == 403
                response = patch(design_world, body, user="opal", who=OPAL)
            else:
                response = patch(design_world, body)
            assert response.status_code == (200 if allowed else 422), (key, new, response.text)
            if not allowed:
                assert (response.json()["code"] == "policy-violation"
                        and any(e.get("key") == key for e in response.json()["errors"]))
            if key == "company.net/cl" and allowed:
                slots = response.json()["approval"]["slots"]
                assert sum(s["reason"] == "Sensitive key changed" for s in slots) == int(
                    edit["sensitive"] and new != view["git"][kind][key])
