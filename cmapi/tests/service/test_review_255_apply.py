"""F4 of the Codex review of PR #255: in delivery mode apply, a folder that moves from the old layout
(resourcequota.yaml, limitrange.yaml) to one file for each object must not lose its ResourceQuota. watch_sync
applied the new resourcequota-<name>.yaml, then pruned the removed resourcequota.yaml by identity, which deleted the
quota it had just applied. It lives here, not in tests/core, because core/sync.py needs structlog (#261)."""
from __future__ import annotations

import copy
import textwrap
from pathlib import Path
from types import SimpleNamespace

import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec, objects_of
from cmapi.core.sync import ApplyDelivery, confirmed_by_read
from cmapi.core.tiers import TierCatalog

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"
WATCH_SYNC = ROOT / "cmapi/src/cmapi/jobs/watch_sync.py"
BASE = "clusters/OCP_GF15/namespaces/abc-rnd/"
ENVS = {"rnd", "dev", "qa", "uat", "prod"}


def renderer() -> ManifestRenderer:
    return ManifestRenderer(TierCatalog.load(EXAMPLES / "config/tiers.yaml", ENVS),
                            MetadataKeys.load(EXAMPLES / "cluster-configs/policies/metadata-keys.yaml"))


def spec(**kw) -> NamespaceSpec:
    base = dict(namespace="abc-rnd", cluster_id="OCP_GF15", instance="nonprod", env="rnd", request_id="req-1",
                tier="small", requested_by_user="ola", requested_by_email="ola@company.net", labels={}, annotations={})
    return NamespaceSpec(**{**base, **kw})


def old_layout(files: dict[str, str | None]) -> dict[str, str]:
    """The folder as cmapi wrote it before #253: resourcequota.yaml, and one <ns>-limits with every container item."""
    out = {p: t for p, t in files.items() if t and "/resourcequota-" not in p and "/limitrange-" not in p}
    rq = objects_of(files, "ResourceQuota")[0]
    lrs = objects_of(files, "LimitRange")
    one = copy.deepcopy(lrs[0])
    one["metadata"]["name"] = "abc-rnd-limits"
    one["metadata"]["annotations"].pop("cmapi.net/beyond-tier", None)
    container: dict = {"type": "Container"}
    for lr in lrs:
        for item in lr["spec"]["limits"]:
            if item["type"] == "Container":
                for part, vals in item.items():
                    if part != "type":
                        container.setdefault(part, {}).update(vals)
    one["spec"]["limits"] = [container]
    out[BASE + "resourcequota.yaml"] = yaml.safe_dump(rq, sort_keys=False)
    out[BASE + "limitrange.yaml"] = yaml.safe_dump(one, sort_keys=False)
    return out


class MemoryClient:
    def __init__(self):
        self.objects: dict = {}
        self.deleted: list = []

    def apply(self, doc):
        meta = doc["metadata"]
        self.objects[(doc["kind"], meta.get("namespace"), meta["name"])] = copy.deepcopy(doc)

    def delete(self, kind, namespace, name):
        self.deleted.append((kind, namespace, name))
        self.objects.pop((kind, namespace, name), None)


def test_a_file_rename_does_not_prune_the_reapplied_quota():
    r = renderer()
    previous = old_layout(r.render(spec()))
    assert BASE + "resourcequota.yaml" in previous
    after = r.render(spec(request_id="req-2"), previous=previous)
    files = {p: t for p, t in after.items() if t is not None}
    removed = {p: previous[p] for p, t in after.items() if t is None and p in previous}
    assert BASE + "resourcequota.yaml" in removed
    client = MemoryClient()
    d = ApplyDelivery(client)
    d.apply_folder(previous)
    # Run watch_sync's own apply-and-prune block, with the real renderer and ApplyDelivery; no job, session or database.
    source = WATCH_SYNC.read_text()
    start = source.index("            n = d.apply_folder(files)")
    end = source.index('            repo.event(row, "applied"', start)
    exec(textwrap.dedent(source[start:end]), {"d": d, "files": files, "removed": removed,
                                             "row": SimpleNamespace(namespace="abc-rnd")})
    assert ("ResourceQuota", "abc-rnd", "abc-rnd-quota") in client.objects
    assert ("LimitRange", "abc-rnd", "abc-rnd-limits") in client.deleted
    assert confirmed_by_read(lambda k, ns, n: client.objects.get((k, ns, n)), "abc-rnd", files)[0]
