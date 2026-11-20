import json
import re
from pathlib import Path
from unittest.mock import Mock

from cmapi.core.approvals import Requirement
from cmapi.core.pipeline import Plan
from cmapi.core.ports import CapacityResult


def test_the_designs_dry_run_example_matches_the_public_field_paths():
    root = Path(__file__).resolve().parents[3]
    text = (root / "docs/reviews/2026-11-20-issue-479/namespace_metadata.md").read_text()
    section = text.split("### 6.2", 1)[1].split("### 6.3", 1)[0]
    example = json.loads(re.search(r"```json\n(.*?)\n```", section, re.S)[1])
    path = "clusters/CRC/namespaces/abc-payments-dev/namespace.yaml"
    namespace = "abc-payments-dev"
    requester = Mock()
    requester.record.return_value = {}
    plan = Plan("CRC", namespace, "dev", "create", "namespaces", None, {path: "manifest"}, {},
                {path: "added"}, Requirement("dev", (), False, 24, ()), CapacityResult("fits", True),
                {}, requester, [], "base", metadata={"namespace": namespace, "labels": {}, "annotations": {}})
    assert example["changes"][path] == plan.view()["changes"][path] == "added"
    assert set(example["metadata"]) == set(plan.view()["metadata"])
