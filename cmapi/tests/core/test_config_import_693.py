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


# cmapi.core.validate (#708): tests/core imports it in that job, so its slots report their wait through a callback, not a metric.
# The usage reader, the verdicts and the list severity are tested here (test_usage_verdicts_310.py, usage_fake.py, #310); the
# Thanos client, the sweep and the plan are the service's and are tested in tests/service (test_usage_review_707.py).
@pytest.mark.parametrize("module", ["cmapi.core.config", "cmapi.core.http_settings", "cmapi.core.ratelimit", "cmapi.core.docs",
                                    "cmapi.core.validate", "cmapi.capacity.usage", "cmapi.capacity.verdicts",
                                    "cmapi.core.listquery"])
def test_imports_without_service_packages(module: str) -> None:
    r = subprocess.run([sys.executable, "-c", CHILD, str(SRC), module], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


# An import at call time escapes the test above: PR #707's usage reader imported its deadlines from thanos.py inside
# PromUsage.namespace and .cluster, so it imported cleanly and then failed on its first read (#310).
READER = CHILD + """from datetime import datetime, timezone
usage = sys.modules["cmapi.capacity.usage"]


class Empty:
    def query(self, cluster_id, promql, at=None):
        return []


reader = usage.PromUsage(Empty())
assert reader.namespace("c", "ns").state == "insufficient-data"
assert reader.cluster("c", idle_days=14, ceiling=0.85, at=datetime.now(timezone.utc)) == {}
"""


def test_the_usage_reader_reads_without_service_packages() -> None:
    r = subprocess.run([sys.executable, "-c", READER, str(SRC), "cmapi.capacity.usage"], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
