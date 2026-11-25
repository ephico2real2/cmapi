"""#683: the time and size of a 422 for a body of 60,000 unknown members (769 KB, under the 1 MiB limit), 7 runs each after
a warm-up request, on the code under test. Copied into tests/service to run; never committed."""
from __future__ import annotations

import json
import statistics
import time

from test_custom_tier_change import URL
from test_flow import NS, OLA, auth


def test_measure_422(world):
    client, ctx, git, kube, validator, keys = world
    content = json.dumps({**NS, **{f"x{i}": 0 for i in range(60_000)}}).encode()
    h = {**auth(keys, "ola", **OLA), "Content-Type": "application/json"}
    client.post(URL + "?dryRun=true", content=json.dumps(NS).encode(), headers=h)    # warm-up
    times, sizes = [], set()
    for _ in range(7):
        t0 = time.perf_counter()
        r = client.post(URL + "?dryRun=true", content=content, headers=h)
        times.append(time.perf_counter() - t0)
        sizes.add((r.status_code, len(r.content), len(r.json().get("errors") or [])))
    print(f"\nMEASURE422 request {len(content):,} bytes -> {sorted(sizes)}; median {statistics.median(times):.3f} s, "
          f"min {min(times):.3f} s, max {max(times):.3f} s")
