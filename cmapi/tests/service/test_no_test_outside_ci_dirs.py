"""CI runs `cmapi/tests/service` (the service job) and `cmapi/tests/core` (the reference-code job, through the
`examples/tests` link). A test module anywhere else under `cmapi/tests` is collected by no job, so it can never fail.
Two review tests landed at the root of `cmapi/tests` this way (#457, #458); this keeps it from happening again."""
from __future__ import annotations

from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]


def test_every_test_module_is_in_a_folder_that_ci_runs():
    stray = sorted(str(p.relative_to(TESTS)) for p in TESTS.rglob("test_*.py")
                   if p.relative_to(TESTS).parts[0] not in ("service", "core"))
    assert not stray, f"test modules that no CI job collects: {stray}"
