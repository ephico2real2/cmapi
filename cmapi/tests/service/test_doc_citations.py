"""The `file:line` citations of docs/14, docs/15 and docs/16 point at the code that they name (#178, BUG-47).

scripts/doc-citations.py holds each citation to the text in docs/citations.lock.json. The first test is the check on this
tree. The others run the script on a small copy, to show that the check can fail and that --relocate repairs a move.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "doc-citations.py"
CODE = "def one():\n    return 1\n\n\ndef two():\n    value = 2\n    return value\n"
DOC = "# Authorization\n\nOne is the first (`pkg/code.py:1-2`). Two holds a value (`code.py:6`), and returns it (`:7`).\n"


def run(root: Path, mode: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), mode, "--root", str(root)], capture_output=True, text=True)


def test_each_citation_of_the_documents_is_the_text_that_was_recorded_for_it():
    r = run(ROOT, "--check")
    assert r.returncode == 0, ("a cited file changed. Run `python scripts/doc-citations.py --relocate`; for what it cannot move, read the code, "
                               "correct the citation and run --write.\n" + r.stderr)
    assert len(json.loads((ROOT / "docs/citations.lock.json").read_text())) >= 80


@pytest.fixture
def copy(tmp_path) -> Path:
    """A repository with the three documents, one of them with three citations, and their lock."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/code.py").write_text(CODE)
    (tmp_path / "docs/14-authorization.md").write_text(DOC)
    for name in ("15-keycloak-integration.md", "16-data-model.md"):
        (tmp_path / "docs" / name).write_text("No citation here. The database is on `127.0.0.1:55432`.\n")
    for cmd in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(tmp_path), *cmd], check=True, capture_output=True)
    assert run(tmp_path, "--write").returncode == 0
    assert run(tmp_path, "--check").returncode == 0
    return tmp_path


def test_a_citation_resolves_a_short_name_and_a_line_alone(copy):
    listed = run(copy, "--list").stdout.splitlines()
    assert [line.split("\t")[1] for line in listed] == ["pkg/code.py:1-2", "pkg/code.py:6-6", "pkg/code.py:7-7"]
    assert set(json.loads((copy / "docs/citations.lock.json").read_text())) == {
        "docs/14-authorization.md|pkg/code.py|1-2", "docs/14-authorization.md|pkg/code.py|6-6", "docs/14-authorization.md|pkg/code.py|7-7"}


def test_lines_added_above_a_cited_range_fail_the_check_and_relocate_repairs_the_citation(copy):
    (copy / "pkg/code.py").write_text('"""A module."""\nimport os\n\n' + CODE)
    r = run(copy, "--check")
    assert r.returncode == 1 and r.stderr.count("run --relocate") == 3, r.stderr
    assert "`pkg/code.py:6` moved to line 9" in r.stderr
    r = run(copy, "--relocate")
    assert r.returncode == 0 and "3 citations moved" in r.stdout, r.stdout + r.stderr
    assert (copy / "docs/14-authorization.md").read_text() == DOC.replace("code.py:1-2", "code.py:4-5").replace("code.py:6", "code.py:9").replace("`:7`", "`:10`")
    assert run(copy, "--check").returncode == 0


def test_a_changed_cited_line_needs_a_person_and_relocate_does_not_hide_it(copy):
    (copy / "pkg/code.py").write_text(CODE.replace("value = 2", "value = 3"))
    r = run(copy, "--check")
    assert r.returncode == 1 and "`pkg/code.py:6` changed: the cited code is not in the file any more" in r.stderr
    r = run(copy, "--relocate")
    assert r.returncode == 1 and "0 citations moved" in r.stdout and "a person must read" in r.stderr
    assert (copy / "docs/14-authorization.md").read_text() == DOC
    assert run(copy, "--check").returncode == 1


def test_text_that_is_now_at_two_places_is_not_moved_by_a_guess(copy):
    (copy / "pkg/code.py").write_text("    return value\n" + CODE)
    r = run(copy, "--check")
    assert r.returncode == 1 and "its text is now at lines [1, 8]" in r.stderr
    assert run(copy, "--relocate").returncode == 1


def test_a_new_citation_must_be_recorded(copy):
    doc = copy / "docs/14-authorization.md"
    doc.write_text(doc.read_text() + "\nThree is new (`pkg/code.py:5`).\n")
    r = run(copy, "--check")
    assert r.returncode == 1 and "is not in docs/citations.lock.json" in r.stderr
    assert run(copy, "--write").returncode == 0 and run(copy, "--check").returncode == 0


def test_a_removed_citation_leaves_no_entry_in_the_lock(copy):
    doc = copy / "docs/14-authorization.md"
    doc.write_text(doc.read_text().replace(", and returns it (`:7`)", ""))
    r = run(copy, "--check")
    assert r.returncode == 1 and "which no document cites" in r.stderr


def test_a_name_that_fits_two_files_or_none_is_an_error(copy):
    (copy / "other").mkdir()
    (copy / "other/code.py").write_text(CODE)
    subprocess.run(["git", "-C", str(copy), "add", "-A"], check=True)
    doc = copy / "docs/16-data-model.md"
    doc.write_text("Two is here (`code.py:5`).\n")
    r = run(copy, "--check")
    assert r.returncode == 2 and "code.py fits 2 files" in r.stderr and "write more of the path" in r.stderr
    doc.write_text("Gone (`missing.py:5`).\n")
    r = run(copy, "--check")
    assert r.returncode == 2 and "no tracked file is or ends with missing.py" in r.stderr


def test_a_range_past_the_end_of_the_file_fails(copy):
    (copy / "pkg/code.py").write_text("def one():\n    return 1\n")
    r = run(copy, "--check")
    assert r.returncode == 1 and r.stderr.count("changed") == 2
