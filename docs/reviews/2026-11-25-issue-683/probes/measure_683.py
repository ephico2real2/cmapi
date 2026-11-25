"""#683 measurements, run as a pytest file copied into tests/service (never committed). Prints one line per case.

1. The issue's case: a body of about 1.7 MB that FastAPI's model refuses with one error per item, on the code under test.
2. The largest real create body at the reference maximums (metadata-keys.yaml allowOther, the custom tier), encoded the
   way json.dumps does by default (ensure_ascii), with annotation values that expand most under that encoding.
"""
from __future__ import annotations

import json
import time

from test_custom_tier_change import URL
from test_flow import OLA, auth


def send(world, content: bytes, url: str = URL + "?dryRun=true"):
    client, ctx, git, kube, validator, keys = world
    t0 = time.perf_counter()
    r = client.post(url, content=content, headers={**auth(keys, "ola", **OLA), "Content-Type": "application/json"})
    return r, time.perf_counter() - t0


def report(name: str, content: bytes, r, seconds: float) -> None:
    body = r.content
    errors = len(r.json().get("errors") or []) if r.headers.get("content-type", "").endswith("json") else None
    print(f"\nMEASURE {name}: request {len(content):,} bytes -> {r.status_code} {r.headers.get('content-type')}, "
          f"answer {len(body):,} bytes, errors {errors}, {seconds:.3f} s")


def label_key(i: int) -> str:
    """A key of allowOther at its longest: a DNS subdomain of ephico2real.com of 253 characters, '/', a name of 63."""
    tail = f".k{i:03d}.ephico2real.com"
    head = "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "."
    prefix = (head + "d" * 253)[: 253 - len(tail)] + tail
    assert len(prefix) == 253, len(prefix)
    return prefix + "/" + "n" * 60 + f"{i:03d}"


def largest_create(value_char: str) -> dict:
    """50 team labels and 50 team annotations at the longest key, labels at 63 characters, annotation values at
    maxValueBytes 4096 each until maxBytesTotal 65536 (16 values of 4096), the governed keys at their longest."""
    per = 4096 // len(value_char.encode())
    values = [value_char * per] * 16 + [""] * 34
    labels = {"cmapi.net/team": "t" * 40, "cmapi.net/cost-center": "cc-4410", "cmapi.net/app": "a" * 40,
              "cmapi.net/rightsizing": "manual"}
    labels |= {label_key(i): "v" * 63 for i in range(50)}
    annotations = {"cmapi.net/team-dl": "payments-team@ephico2real.com"}
    annotations |= {label_key(100 + i): values[i] for i in range(50)}
    return {"namespace": "p" * 63, "tier": "small", "labels": labels, "annotations": annotations,
            "justification": "j" * 1000}


def test_measure_issue_case(world):
    # One unknown member per item: pydantic's extra_forbidden, one error each.
    members = {f"x{i}": 0 for i in range(170_000)}
    content = json.dumps({"namespace": "payments-dev", **members}).encode()
    r, s = send(world, content)
    report("unknown-members ~1.7MB", content, r, s)
    # One label of the wrong type per item: string_type, one error each, below body.labels.
    content = json.dumps({"namespace": "payments-dev", "labels": {f"k{i}": i for i in range(130_000)}}).encode()
    r, s = send(world, content)
    report("non-string labels ~1.7MB", content, r, s)
    for n in (60_000, 90_000):
        content = json.dumps({"namespace": "payments-dev", **{f"x{i}": 0 for i in range(n)}}).encode()
        r, s = send(world, content)
        report(f"unknown-members {n}", content, r, s)


def test_measure_largest_real_create(world):
    # ASCII values; then 2-byte (U+00E9), 3-byte (U+4E2D) and control characters (U+0001), which ensure_ascii writes as
    # a six-byte escape each; then the same pretty-printed with indent=2, as a person's file might be.
    for name, ch in (("ascii", "v"), ("U+00E9", "é"), ("U+4E2D", "中"), ("U+0001", "\u0001")):
        body = largest_create(ch)
        for indent in (None, 2):
            content = json.dumps(body, indent=indent).encode()
            r, s = send(world, content)
            report(f"largest create values {name} indent {indent}", content, r, s)
            assert r.status_code == 200, r.text[:2000]
