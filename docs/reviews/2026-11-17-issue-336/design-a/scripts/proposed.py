"""Design 336-A measurement: the proposed GET /api/v1/metadata-keys body for the reference (CRC) and the company config,
built only from origin/main's MetadataKeys.json_schema and docs.py helpers. Also proves that factoring the per-field
dict out of docs._document_metadata leaves /openapi.json unchanged, and dumps the create corpus of tests/core with
validate()'s verdict for the Node leg (client validator)."""
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path[:0] = [str(SRC / "cmapi" / "src"), str(SRC / "cmapi" / "tests" / "core")]

import yaml
from cmapi.core.metadata import MetadataKeys
from cmapi.core import docs
from metadata_corpus import cases, verdict, good

OUT = ROOT / "evidence"
FILES = {"reference": SRC / "examples/cluster-configs/policies/metadata-keys.yaml",
         "company": SRC / "examples/cluster-configs/policies/metadata-keys.company.yaml"}
SOURCES = {"reference": {"namespace": "payments-dev", "environment": "dev", "cluster": "CRC", "instance": "nonprod"},
           "company": {"namespace": "abc-rnd", "environment": "rnd", "cluster": "CRC", "instance": "nonprod"}}
FIELDS = (("labels", "label"), ("annotations", "annotation"))


def field_schema(keys, kind, op, title):
    """The proposed shared function: exactly what _document_metadata puts at NamespaceCreate.properties.<field>."""
    schema = keys.json_schema(kind, op)
    words = {"title": title, "description": ("" if op == "create" else "Merge patch; null removes a key. ")
             + docs.metadata_description(keys, kind)}
    return {**schema, **words, "examples": [docs.metadata_example(keys, kind)]}


def route_body(keys, text):
    return {
        "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
        "configHash": hashlib.sha256(text.encode()).hexdigest()[:16],
        "labels": field_schema(keys, "label", "create", "Labels"),
        "annotations": field_schema(keys, "annotation", "create", "Annotations"),
    }


def openapi_like(keys):
    """Run origin/main's _document_metadata on a minimal NamespaceCreate component, as build_openapi does."""
    spec = {"components": {"schemas": {
        "NamespaceCreate": {"properties": {"labels": {"title": "Labels"}, "annotations": {"title": "Annotations"},
                                           "namespace": {"examples": ["payments-dev"]}}, "required": ["namespace"]},
        "NamespacePatch": {"properties": {"labels": {"title": "Labels"}, "annotations": {"title": "Annotations"}}}}}}
    docs._document_metadata(spec, keys)
    return spec["components"]["schemas"]["NamespaceCreate"]["properties"]


report = []
for name, path in FILES.items():
    text = path.read_text()
    keys = MetadataKeys(yaml.safe_load(text))
    body = route_body(keys, text)
    raw = json.dumps(body, indent=2, ensure_ascii=False)
    (OUT / f"response-{name}.json").write_text(raw + "\n")
    compact = json.dumps(body, separators=(",", ":")).encode()
    props = openapi_like(keys)
    equal = all(body[f] == props[f] for f, _ in FIELDS)
    report.append(f"{name}: route labels/annotations == _document_metadata output on origin/main: {equal}; "
                  f"compact body {len(compact)} bytes; strong ETag would be \"{hashlib.sha256(compact).hexdigest()[:32]}\"")
    for f, kind in FIELDS:
        s = body[f]
        report.append(f"  {f}: properties={list(s['properties'])} required={s.get('required', [])} "
                      f"x-cmapi-other-keys={s['x-cmapi-other-keys']}")
    # The create corpus with validate()'s verdict (the server's authority) for the Node leg.
    rows = []
    for c in cases(keys):
        if c.op != "create":
            continue
        errs = verdict(keys, c, SOURCES[name])
        rows.append({"kind": c.kind, "body": c.body, "operator": c.operator, "accepted": not errs,
                     "codes": sorted({e["code"] + ("/prefix" if "does not start with" in e.get("detail", "") else "") for e in errs})})
    (OUT / f"corpus-{name}.json").write_text(json.dumps({"schema": {f: body[f] for f, _ in FIELDS},
                                                          "good": {k: good(keys, k) for _, k in FIELDS},
                                                          "rows": rows}, ensure_ascii=False))
    report.append(f"  create corpus: {len(rows)} maps, {sum(r['accepted'] for r in rows)} accepted by validate()")
print("\n".join(report))
