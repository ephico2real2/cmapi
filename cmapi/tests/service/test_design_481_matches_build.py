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

from cmapi.core.metadata import DEFAULT_LIVE_ONLY_KEYS
from cmapi.core.models import NamespaceView

DOCS = Path(__file__).resolve().parents[3] / "docs" / "reviews" / "2026-11-20-epic-481-metadata-patch"


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


def test_row1_picture_has_no_permission_filter(design):
    assert "only clusters where you hold namespaces:write" not in design
    assert "every cluster cmapi manages" in design


def test_row2_no_invented_rename_reason(design):
    assert "A namespace cannot be renamed." not in design
    assert "the tab has no row for it" in design


def test_row3_drift_names_operator_only_keys_and_a_missing_namespace(design):
    drift = next(line for line in design.splitlines() if line.startswith("| `drift` |"))
    assert "operator-only" in drift
    assert "does not have the namespace" in drift


def test_row5_read_example_validates_against_namespace_view(design):
    block = re.search(r"```json\n(.*?)```", _section(design, "### 4.2 The read"), re.S).group(1)
    example = json.loads(block)
    assert set(example["git"]) == {"labels", "annotations", "edits"}
    # The example shows the fields that the read adds; the other fields of the view take their usual values.
    example = {"clusterId": "CRC", "env": "dev", "team": "payments", "tier": "small", "managed": True,
               "expiresAt": None, "openRequest": None, "mnemonic": "abc", **example}
    view = NamespaceView.model_validate(example)
    assert view.git is not None
    edit = view.git.edits.labels["cmapi.net/managed"]
    assert (edit.mode, edit.removable) == ("fixed", False)
    assert "git.edits" in design and "removable" in design


def test_row6_names_the_liveonlykeys_stanza_and_its_default(design):
    assert "a small, configurable ignore list" not in design
    assert "liveOnlyKeys" in design
    for key in DEFAULT_LIVE_ONLY_KEYS:
        assert key in design


def test_row7_if_match_names_the_list_and_star(design):
    headers = next(line for line in design.splitlines() if line.startswith("- **Headers.**"))
    following = design[design.index(headers):design.index("- **Permission.**")]
    assert "A list of tags" in following
    assert "`*` is 428" in following


def test_row9_second_pass_says_row3_was_replaced(second_pass):
    assert "Row 3 was replaced the same day" in second_pass
    assert "`git: {labels, annotations}`" in second_pass


def test_row10_second_pass_names_unknown(second_pass):
    assert "in-sync|pending|drift|unknown" in second_pass
    assert "in-sync|pending|drift," not in second_pass
