"""A large config: N declared keys of each kind and D email domains. The proposed body's size and the time to build it."""
import json, sys, time
import cmapi.core.metadata as m
from pathlib import Path
for n, d in ((50, 10), (500, 200), (2000, 1000)):
    raw = {"emailDomains": [f"d{i}.example.com" for i in range(d)],
           "requiredLabels": {f"company.net/l{i}": {"pattern": "^[a-z0-9-]{2,40}$", "example": "ab", "description": "x" * 80} for i in range(n)},
           "extraAnnotations": {"keys": {f"company.net/a{i}": {"format": "email-in-domains", "description": "y" * 80} for i in range(n)}}}
    t = time.perf_counter(); keys = m.MetadataKeys(raw); load = time.perf_counter() - t
    t = time.perf_counter()
    body = {"labels": keys.json_schema("label", "create"), "annotations": keys.json_schema("annotation", "create")}
    gen = time.perf_counter() - t
    data = json.dumps(body, separators=(",", ":")).encode()
    Path(__file__).with_name(f"large-{n}-{d}.json").write_bytes(data)
    import gzip
    print(f"keys {n}+{n} domains {d}: load {load*1000:.0f} ms, json_schema {gen*1000:.0f} ms, body {len(data)/1024:.0f} KiB, gzip {len(gzip.compress(data))/1024:.0f} KiB")
