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
    # A declared key, an operator-only one included, is described by GET /api/v1/metadata-keys, not here.
    assert "company.net/cl" not in edits["labels"] and "cmapi.net/team-dl" not in edits["annotations"]


def test_a_removable_key_is_one_that_the_api_lets_a_change_remove_and_never_set(design_world):
    create(design_world)
    edit_git(design_world, lambda meta: meta["labels"].update({"old.invalid/key": "legacy"}))
    assert read(design_world)["git"]["edits"]["labels"]["old.invalid/key"]["removable"] is True
    assert "old.invalid/key" not in planned_namespace(patch(design_world, {"labels": {"old.invalid/key": None}}))["labels"]
    assert errors_of(patch(design_world, {"labels": {"old.invalid/key": "again"}})) == [("invalid_key", "old.invalid/key")]
    assert errors_of(patch(design_world, {"labels": {"cmapi.net/managed": None}})) != [], "a system key is not removable"
