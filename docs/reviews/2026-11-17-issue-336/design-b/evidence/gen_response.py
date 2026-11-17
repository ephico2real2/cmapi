"""The proposed GET /api/v1/metadata-keys body for each config, from main's MetadataKeys.json_schema (the #328 generator).
Run: PYTHONPATH=<export>/cmapi/src python gen_response.py <export>"""
import json, sys
from pathlib import Path
import cmapi.core.metadata as m

root = Path(sys.argv[1])
out = Path(__file__).parent
print("imported", m.__file__)
for name, rel in (("reference", "examples/cluster-configs/policies/metadata-keys.yaml"),
                  ("company", "examples/cluster-configs/policies/metadata-keys.company.yaml")):
    keys = m.MetadataKeys.load(root / rel)
    body = {"labels": keys.json_schema("label", "create"), "annotations": keys.json_schema("annotation", "create")}
    text = json.dumps(body, indent=2, ensure_ascii=False)
    (out / f"response-{name}.json").write_text(text + "\n")
    compact = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    print(name, "bytes(pretty)", len(text.encode()), "bytes(compact)", len(compact))
