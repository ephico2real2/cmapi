"""Render a fixed corpus with the checked-out cmapi source: the policy bundle of each example instance (both
metadata-keys files) and namespace folders whose team labels and annotations carry ordinary and YAML 1.1 values.
Usage: PYTHONPATH=<repo>/cmapi/src python corpus.py <repo> <out-dir>"""
import sys
from datetime import date
from pathlib import Path

from cmapi.core.config import load_instance
from cmapi.core.metadata import MetadataKeys
from cmapi.core.policygen import render_bundle
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec
from cmapi.core.tiers import TierCatalog

repo, out = Path(sys.argv[1]), Path(sys.argv[2])
EX = repo / "examples"
ENVS = {"rnd", "dev", "qa", "uat", "prod"}
VALUES = ["abc", "amgsst", "1", "true", "yes", "no", "on", "off", "null", "~", "", "2026-11-17", "1:20", "0x1F", "017",
          ".inf", "<<", "=", "y", "Y", "n", "N", "0o17", "1e3", "089", "0X1F", "0B1", "1_000", "+.5", ".5", "1.5",
          "team-a", "a.b_c", "https://wiki.company.net/abc", "abc-team@company.net", "v1.2.3", "10Gi", "500m",
          "2026-1-2", "x", "z", "t", "f"]

for meta_file in ("metadata-keys.yaml", "metadata-keys.company.yaml"):
    for inst in ("nonprod", "staging", "prod"):
        cfg = load_instance(str(EX / "instances" / inst), str(EX / "cluster-configs/policies" / meta_file))
        for rel, text in render_bundle(cfg.tiers, cfg.metadata, cfg.policy, cfg.allowed_environments, cfg.name).items():
            f = out / "bundle" / meta_file / inst / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)

catalog = TierCatalog.load(EX / "config/tiers.yaml", ENVS)
keys = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.company.yaml")
r = ManifestRenderer(catalog, keys)
base = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}
specs = {"owner-small": dict(tier="small"), "owner-medium-sa": dict(tier="medium", service_accounts=["build", "y"],
                                                                     grants=[("build", "edit")]),
         "expiring": dict(tier="small", expires_at=date(2026, 11, 17)),
         "values": dict(tier="small", labels={**base, **{f"x.ephico2real.com/v{i:02d}": v for i, v in enumerate(VALUES)}},
                        annotations={f"team.ephico2real.com/a{i:02d}": v for i, v in enumerate(VALUES)})}
for name, over in specs.items():
    spec = dict(namespace="abc-rnd", cluster_id="OCP_GF15", instance="nonprod", env="rnd", request_id="req-1",
                requested_by_user="ola", requested_by_email="ola@company.net", labels=base,
                annotations={"company.net/mnemonic-confluence": "https://wiki.company.net/abc"})
    spec.update(over)
    for path, text in r.render(NamespaceSpec(**spec)).items():
        f = out / "ns" / name / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text or "")
print("rendered", sum(1 for p in out.rglob("*") if p.is_file()), "files")
