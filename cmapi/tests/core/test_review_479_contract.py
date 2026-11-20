"""#479, review of PR #488 (F19): each accepted breaking change is listed once, under the issue that accepted it."""
from __future__ import annotations

from pathlib import Path

ACCEPTED = Path(__file__).resolve().parents[2] / "contract/accepted-breaking.txt"


def test_each_accepted_breaking_change_is_listed_once():
    lines = [ln for ln in ACCEPTED.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    assert sorted({ln for ln in lines if lines.count(ln) > 1}) == []
