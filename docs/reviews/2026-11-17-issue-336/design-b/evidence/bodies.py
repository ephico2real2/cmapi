"""The validator on the bodies the proposed form sends, and on the mistakes it must not make (company config)."""
import sys
from pathlib import Path
import cmapi.core.metadata as m
co = m.MetadataKeys.load(Path(sys.argv[1]) / "examples/cluster-configs/policies/metadata-keys.company.yaml")
ref = m.MetadataKeys.load(Path(sys.argv[1]) / "examples/cluster-configs/policies/metadata-keys.yaml")
src = {"namespace": "abc-rnd", "environment": "rnd", "cluster": "CRC", "instance": "nonprod"}
L = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}
cases = [
    ("company: the form's body", co, L, {}, src),
    ("company: + derived name, same value", co, {**L, "name": "abc-rnd"}, {}, src),
    ("company: + derived name, another value", co, {**L, "name": "abc"}, {}, src),
    ("company: name not starting with the mnemonic", co, L, {}, {**src, "namespace": "xyz-rnd"}),
    ("company: an empty optional annotation sent", co, L, {"company.net/mnemonic-confluence": ""}, src),
    ("company: the reference body (today's hard-coded keys)", co, {"cmapi.net/team": "payments"}, {"cmapi.net/team-dl": "payments-team@ephico2real.com"}, src),
    ("company: operator-only key by a requester", co, {**L, "cmapi.net/protected": "true"}, {}, src),
    ("reference: today's body", ref, {"cmapi.net/team": "payments"}, {"cmapi.net/team-dl": "payments-team@ephico2real.com"}, {**src, "namespace": "payments-dev"}),
]
for name, keys, labels, anns, sources in cases:
    print(f"{name}: {keys.validate(labels, anns, operator=False, sources=sources)}")
