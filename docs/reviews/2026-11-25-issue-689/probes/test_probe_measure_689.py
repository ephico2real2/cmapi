"""Probe (#689, not committed): the time of a 429 and of a 422 for #683's 769 KB body of 60,000 unknown members, 7 runs each,
and the JSON decode of that body alone. Copy into cmapi/tests/service/ to run."""
import json
import statistics
import time

import pytest

from test_rate_limits_689 import NS, REQUESTER, URL, auth, limited  # noqa: F401


@pytest.mark.parametrize("limited", [{"write": {"perMinute": 60, "burst": 1}}], indirect=True)
def test_measure(limited, capsys):
    world, clock = limited
    client, *_, keys = world
    body = {**NS, **{f"x{i}": 1 for i in range(60_000)}}
    raw = json.dumps(body).encode()
    decode = []
    for _ in range(7):
        t0 = time.perf_counter(); json.loads(raw); decode.append(time.perf_counter() - t0)
    v422, v429 = [], []
    for _ in range(7):
        clock.now += 10
        h = {**auth(keys, "ola", **REQUESTER), "Content-Type": "application/json"}
        t0 = time.perf_counter(); r = client.post(URL + "?dryRun=true", content=raw, headers=h); v422.append(time.perf_counter() - t0)
        assert r.status_code == 422
        t0 = time.perf_counter(); r = client.post(URL + "?dryRun=true", content=raw, headers=h); v429.append(time.perf_counter() - t0)
        assert r.status_code == 429
    with capsys.disabled():
        print(f"\nbody {len(raw)} bytes; json.loads median {statistics.median(decode):.4f} s; "
              f"422 median {statistics.median(v422):.3f} s {sorted(round(x,3) for x in v422)}; "
              f"429 median {statistics.median(v429):.3f} s {sorted(round(x,3) for x in v429)}")
