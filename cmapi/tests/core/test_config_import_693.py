"""The config and the API document load without the service's own packages (#693).

The tools and the reference code (CI job reference-code) install examples/local/requirements.txt, which has no structlog
and no prometheus_client. PR #691 made core/config.py and core/docs.py import core/bodylimit.py, the middleware, which
imports core/observability.py and so structlog: 18 test files of that job failed to collect. Each module is imported in a
fresh interpreter where those packages cannot be imported, whether or not this environment has them.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import cmapi

SRC = Path(cmapi.__file__).resolve().parent.parent
# The Python Language Reference, 5.3.1 "The module cache" (https://docs.python.org/3/reference/import.html): the key "can
# also be assigned to None, forcing the next import of the module to result in a ModuleNotFoundError".
CHILD = """import sys
sys.path.insert(0, sys.argv[1])
for name in ("structlog", "prometheus_client"):
    sys.modules[name] = None
import importlib
importlib.import_module(sys.argv[2])
"""


@pytest.mark.parametrize("module", ["cmapi.core.config", "cmapi.core.http_settings", "cmapi.core.docs"])
def test_imports_without_service_packages(module: str) -> None:
    r = subprocess.run([sys.executable, "-c", CHILD, str(SRC), module], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
