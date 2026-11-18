"""#395: the start check of the pinned Kyverno CLI compares the whole version, not a prefix of it.

`CliValidator` refused another CLI than CMAPI_KYVERNO_VERSION with `f"Version: {pinned}" not in out`, so any version that
starts with the pin passed. Each case runs a stub `kyverno` that prints what Kyverno v1.20.0's `version` command prints
(cmd/cli/kubectl-kyverno/commands/version/command.go at the tag v1.20.0: `Version: %s`, `Time: %s`, `Git commit ID: %s`), with
the version given, so the check runs with no real binary.

    cd cmapi && PYTHONPATH=src python -m pytest tests/core/test_kyverno_pin_395.py -q
"""
from __future__ import annotations

import re
import shlex

import pytest

from cmapi.core.policy import PolicySettings
from cmapi.core.validate import CliValidator, PolicyEngineMissing

PIN = "v1.20.0"


def printed(version: str) -> str:
    return f"Version: {version}\nTime: 2026-10-01T10:00:00Z\nGit commit ID: 0123456789abcdef\n"


def stub(tmp_path, out: str) -> str:
    path = tmp_path / "kyverno"
    path.write_text(f"#!/bin/sh\nprintf %s {shlex.quote(out)}\n")
    path.chmod(0o755)
    return str(path)


def start(tmp_path, out: str, monkeypatch) -> CliValidator:
    monkeypatch.setenv("CMAPI_KYVERNO_VERSION", PIN)
    return CliValidator(tmp_path, kyverno=stub(tmp_path, out), policy=PolicySettings(), environments={"rnd"})


@pytest.mark.parametrize("version", ["v1.20.0-rc1", "v1.20.01", "v1.20.0.1", "v1.20.0+dirty", "v1.20"])
def test_a_version_that_only_starts_or_ends_like_the_pin_stops_the_start(tmp_path, monkeypatch, version):
    with pytest.raises(PolicyEngineMissing, match=rf"is not the pinned {re.escape(PIN)} \(Version: {re.escape(version)}\)"):
        start(tmp_path, printed(version), monkeypatch)


@pytest.mark.parametrize("out", ["", "Client Version: v1.20.0\n", "Time: 2026-10-01T10:00:00Z\n"])
def test_an_answer_with_no_version_line_stops_the_start(tmp_path, monkeypatch, out):
    with pytest.raises(PolicyEngineMissing, match=r"\(no version\)"):
        start(tmp_path, out, monkeypatch)


def test_the_pinned_version_starts(tmp_path, monkeypatch):
    start(tmp_path, printed(PIN), monkeypatch)
    start(tmp_path, printed(PIN).replace("\n", "\r\n"), monkeypatch)


@pytest.mark.parametrize("out, version", [
    (printed("v1.20.0"), "v1.20.0"),
    (printed("v1.20.0-rc1"), "v1.20.0-rc1"),
    ("Client Version: v1.20.0\n", None),
    ("", None),
])
def test_the_version_is_the_whole_value_of_the_version_line(out, version):
    from cmapi.core.validate import kyverno_version     # here, so that the cases above run against a build without it

    assert kyverno_version(out) == version
