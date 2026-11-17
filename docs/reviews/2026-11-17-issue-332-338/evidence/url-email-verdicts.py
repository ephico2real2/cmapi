"""The validator's verdict on each value of the three-engine corpus, for the URL key and the email key of the company
file. usage: python url-email-verdicts.py <cmapi src> <repo root> > verdicts.json"""
import json, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from cmapi.core.metadata import MetadataKeys
root = Path(sys.argv[2])
corpus = json.loads((root / "docs/reviews/2026-11-17-issue-332-338/evidence/corpus.json").read_text())["corpus"]
corpus += ["http://[1.2.3.4]/", "http://[v1.x]/", "http://[:::::]/", "a@Kompany.net"]
keys = MetadataKeys.load(root / "examples/cluster-configs/policies/metadata-keys.company.yaml")
sent = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}
sources = {"namespace": "abc-rnd", "environment": "rnd", "cluster": "OCP_GF15", "instance": "nonprod"}
out = {}
for key in ("company.net/mnemonic-confluence", "company.net/mnemonic-group-contact"):
    for s in corpus:
        try:
            out[f"{key} {s!r}"] = "refused" if keys.validate(sent, {key: s}, operator=False, sources=sources) else "accepted"
        except ValueError as e:
            out[f"{key} {s!r}"] = f"ValueError: {e}"
print(json.dumps(out))
