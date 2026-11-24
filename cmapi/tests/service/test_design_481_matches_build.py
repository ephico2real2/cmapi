"""The design of epic #481 matches the build (#628).

design.md and second-pass.md are the reference of stories #483 to #485. This test holds them to the code, so a later
ruling cannot leave them saying what the build replaced. It needs no database and no cluster.

Rows 4 and 8 of #628 (the `unknown` row of the sync table, and the list's `sync`) wait for the ruling of #627, so they are
not checked here.
"""
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from cmapi.core.metadata import DEFAULT_LIVE_ONLY_KEYS, MetadataKeys
from cmapi.core.models import KeyEdit, NamespacePatch, NamespaceView

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs" / "reviews" / "2026-11-20-epic-481-metadata-patch"
# The design's examples use the owner's sample keys (company.net/*, mnemonic abc), which this file configures.
COMPANY_KEYS = ROOT / "examples" / "cluster-configs" / "policies" / "metadata-keys.company.yaml"


@pytest.fixture(scope="module")
def design() -> str:
    return (DOCS / "design.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def second_pass() -> str:
    return (DOCS / "second-pass.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = re.search(r"^### ", text[start + len(heading):], re.M)
    return text[start:start + len(heading) + nxt.start()] if nxt else text[start:]


def _row(text: str, first_cell: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(f"| {first_cell} |"))


def test_row1_picture_has_no_permission_filter(design):
    assert "only clusters where you hold namespaces:write" not in design
    assert "every cluster cmapi manages" in design


def test_row2_no_invented_rename_reason(design):
    assert "A namespace cannot be renamed." not in design
    row = _row(design, "1")
    assert "tab has no row for it" in row
    assert "422 `validation-failed`" in row
    # The 422 holds because the PATCH body has no name field and refuses a field it does not know.
    with pytest.raises(ValidationError):
        NamespacePatch.model_validate({"namespace": "abc-payments-dev"})


def test_row3_drift_names_operator_only_keys_and_a_missing_namespace(design):
    drift = _row(design, "`drift`")
    assert "No request is open" in drift
    assert "operator-only" in drift
    assert "does not have the namespace" in drift


def test_in_sync_is_the_drift_row_turned_around(design):
    # plugins/namespaces/state.py: in-sync needs the namespace on the cluster, and drifted_keys compares operator-only keys.
    in_sync = _row(design, "`in-sync`")
    assert "No request is open" in in_sync
    assert "operator-only" in in_sync
    assert "The cluster has the namespace" in in_sync


def test_row5_read_example_validates_against_namespace_view(design):
    block = re.search(r"```json\n(.*?)```", _section(design, "### 4.2 The read"), re.S).group(1)
    example = json.loads(block)
    assert set(example["git"]) == {"labels", "annotations", "edits"}
    # The example shows the fields that the read adds; the other fields of the view take their usual values.
    padded = {"clusterId": "CRC", "env": "dev", "team": "payments", "tier": "small", "managed": True,
              "expiresAt": None, "openRequest": None, "mnemonic": "abc", **example}
    assert NamespaceView.model_validate(padded).git is not None
    # Each edit shown is the one the read builds for that key of Git (plugins/namespaces/router.py, undeclared_edits),
    # in the example's environment, dev.
    git = example["git"]
    built = MetadataKeys.load(COMPANY_KEYS).undeclared_edits(
        {"label": git["labels"], "annotation": git["annotations"]}, "dev")
    for kind in ("labels", "annotations"):
        for key, edit in git["edits"][kind].items():
            assert key in built[kind], f"the read gives no edit for {kind} {key}"
            assert KeyEdit.model_validate(edit) == KeyEdit.model_validate(built[kind][key]), key


def test_removable_says_remove_and_never_set(design):
    paragraph = next(p for p in design.split("\n\n") if p.startswith("`git.edits` gives"))
    assert "may remove that key" in paragraph
    assert "cannot set it" in paragraph


def test_row6_names_the_liveonlykeys_stanza_and_its_default(design):
    assert "a small, configurable ignore list" not in design
    assert "liveOnlyKeys" in design
    for key in DEFAULT_LIVE_ONLY_KEYS:
        assert key in design


def test_row7_if_match_names_the_list_and_star(design):
    headers = next(line for line in design.splitlines() if line.startswith("- **Headers.**"))
    following = design[design.index(headers):design.index("- **Permission.**")]
    assert "passes when one strong tag is the current etag" in following
    assert "`*` is 428" in following


def test_row9_second_pass_says_row3_was_replaced(second_pass):
    assert "Row 3 was replaced the same day" in second_pass
    assert "`git: {labels, annotations}`" in second_pass


def test_row10_second_pass_names_unknown(second_pass):
    assert "in-sync|pending|drift|unknown" in second_pass
    assert "in-sync|pending|drift," not in second_pass
