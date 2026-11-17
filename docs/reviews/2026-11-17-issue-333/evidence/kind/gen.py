"""Render the kind proof's inputs with one cmapi source tree (PYTHONPATH picks main's or the branch's).

    gen.py OUT_DIR WORKTREE

OUT_DIR/bundle-original/   the dev bundle of the reference metadata-keys.yaml (instance nonprod, default mode: audit)
OUT_DIR/bundle-tightened/  the same with cmapi.net/cost-center tightened from ^cc-[0-9]{4}$ to ^cc-[0-9]{5}$
OUT_DIR/ns-<name>.yaml     the Namespace that cmapi renders for team payments and cost-center cc-4410
"""
import copy
import sys
from pathlib import Path

import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import render_bundle
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec
from cmapi.core.tiers import TierCatalog

out, wt = Path(sys.argv[1]), Path(sys.argv[2])
envs = {"rnd", "dev", "qa", "uat", "prod"}
catalog = TierCatalog.load(wt / "examples/config/tiers.yaml", envs)
raw = yaml.safe_load((wt / "examples/cluster-configs/policies/metadata-keys.yaml").read_text())
tight = copy.deepcopy(raw)
tight["extraLabels"]["keys"]["cmapi.net/cost-center"] = {"pattern": "^cc-[0-9]{5}$", "example": "cc-44100"}
for name, data in (("original", raw), ("tightened", tight)):
    keys = MetadataKeys(data)
    for rel, text in render_bundle(catalog, keys, PolicySettings(), {"dev"}, "nonprod").items():
        if rel.endswith(".yaml"):
            f = out / f"bundle-{name}" / Path(rel).name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
keys = MetadataKeys(raw)
for ns in ("payments-dev", "orders-dev"):
    spec = NamespaceSpec(namespace=ns, cluster_id="KIND", instance="nonprod", env="dev", tier="small", request_id="req-1",
                         requested_by_user="ola", requested_by_email="ola@ephico2real.com",
                         labels={"cmapi.net/team": "payments", "cmapi.net/cost-center": "cc-4410"},
                         annotations={"cmapi.net/team-dl": "payments-team@ephico2real.com"})
    files = ManifestRenderer(catalog, keys).render(spec)
    (out / f"ns-{ns}.yaml").write_text(next(t for p, t in files.items() if p.endswith("/namespace.yaml")))
