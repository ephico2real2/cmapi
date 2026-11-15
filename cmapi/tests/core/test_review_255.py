"""Regressions from the Codex review of PR #255 (F1, F2, F3, F5). F4 is in tests/service/test_review_255_apply.py,
because it needs core/sync.py (structlog), which the reference-code job does not install (#261)."""
"""Offline adversarial regressions for export abb18cd; no service fixtures or database."""
import copy
import hashlib
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cmapi.core.render.manifests import object_file, objects_of, plan_hash, diff_files
from cmapi.core.tiers import BEYOND_TIER, TierCatalog, TierError, flatten_limits
from cmapi.core.validate import _previous_objects, _previous_version, _held
from conftest import ALL_ENVS, EX
from test_limitrange_split import raw, KW, SIZES, renderer, spec, old_layout
from test_policygen import kyverno, validator, owners_sample, BASE, LR_CPU


def test_f1_quota_approval_is_not_a_limitrange_approval():
    hard = {**SIZES, "requests.storage": "300Gi"}
    rq, lrs = TierCatalog(raw(), ALL_ENVS).render(**KW, tier="custom", hard=hard)
    assert rq["metadata"]["annotations"][BEYOND_TIER] == "requests.storage"
    assert all(BEYOND_TIER not in lr["metadata"]["annotations"] for lr in lrs)


@pytest.mark.parametrize("resource", [
    "example.com/gpu..unit", "example.com/gpu.-unit",
    ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61]) + "/gpu",
])
def test_f2_loader_accepted_resources_render_dns_subdomain_names(resource):
    r = raw()
    key = f"limitRange.container.max.{resource}"
    r["overridable"].append(key)
    r["custom"]["max"][key] = "4"
    cat = TierCatalog(r, ALL_ENVS)
    for namespace in ("abc-rnd", "a" * 63):
        _, lrs = cat.render(**{**KW, "namespace": namespace}, tier="custom", hard=SIZES,
                            limits={"container": {"max": {resource: "1"}}})
        for lr in lrs:
            name = lr["metadata"]["name"]
            assert len(name) <= 253, (len(name), name)
            assert re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*", name), name
        assert len({lr["metadata"]["name"] for lr in lrs}) == len(lrs)


@pytest.mark.parametrize("kind", ["LimitRange", "ResourceQuota"])
def test_f3_long_file_fallback_cannot_alias_an_ordinary_name(kind):
    long_name = "a" * 253
    # This short name is a legal Kubernetes object name, not a hash collision.
    short_name = hashlib.sha256(long_name.encode()).hexdigest()[:32]
    assert object_file(kind, long_name) != object_file(kind, short_name)
    assert len(object_file(kind, long_name).encode()) <= 255


def test_f5_docs_reference_the_current_own_namespace_files():
    doc = (EX.parent / "docs/02-technical-design-v2.md").read_text()
    block = doc.split("**Reference implementation.**", 1)[1].split("\n", 1)[0]
    assert "resourcequota.yaml" not in block and "limitrange.yaml" not in block
    assert "limitrange-payments-dev-limits-cpu.yaml" in block
    assert "limitrange-payments-dev-limits-memory.yaml" in block
