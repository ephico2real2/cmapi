"""The YAML readers of Kubernetes tooling, for tests (#355).

yamlread/main.go reads a document with sigs.k8s.io/yaml (go-yaml v2, YAML 1.1: kubectl, Argo CD, the Kyverno CLI) and
with go-yaml v3 (YAML 1.2), and prints each result as JSON, with every value or key that is not a string spelled
"<type value>". It is built once per run with the Go toolchain. A test that needs it is skipped when no `go` is on PATH,
and fails instead under CMAPI_REQUIRE_GO=1, as CI sets it, so CI never passes by skipping.
"""
from __future__ import annotations

import atexit
import functools
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parent / "yamlread"
READERS = ("yaml11", "yaml12")


@functools.cache
def binary() -> str:
    go = shutil.which("go")
    if not go:
        if os.environ.get("CMAPI_REQUIRE_GO") == "1":
            pytest.fail("CMAPI_REQUIRE_GO=1 and no go on PATH")
        pytest.skip("no go on PATH")
    out = Path(tempfile.mkdtemp(prefix="cmapi-yamlread-"))
    atexit.register(shutil.rmtree, out, ignore_errors=True)
    r = subprocess.run([go, "build", "-o", str(out / "yamlread"), "."], cwd=SOURCE, capture_output=True, text=True,
                       timeout=600)
    assert r.returncode == 0, r.stderr
    return str(out / "yamlread")


def read(text: str) -> dict[str, Any]:
    """{reader: the document as that reader reads it} for yaml11 and yaml12; a reader's error fails the test."""
    r = subprocess.run([binary()], input=text, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    for reader in READERS:
        assert not got.get(f"{reader}_error"), (reader, got[f"{reader}_error"])
    return {reader: got[reader] for reader in READERS}
