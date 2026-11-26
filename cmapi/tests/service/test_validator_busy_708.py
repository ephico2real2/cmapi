"""#708 through the API: concurrent dry runs run at most the validator's slots of Kyverno at once, and the others answer 503
validator-busy with Retry-After, never a crash.

On CRC (2026-11-26) twelve concurrent create dry runs started twelve `kyverno apply` processes in the API's memory cgroup,
and the kubelet killed the container at its 512 MiB limit: all twelve answered 502 from the front door. Here cmapi's real
validator runs a stub `kyverno` that counts, under an exclusive file lock, how many copies of itself run at once, and keeps
the highest count, so the test reads the peak of real child processes.
"""
from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from prometheus_client import REGISTRY

import cmapi.core.context as context_mod
import cmapi.core.validate as V
from cmapi.core.validate import CliValidator
from conftest import build_world
from test_flow import NS, OLA, auth

URL = "/api/v1/clusters/CRC/namespaces"
POLICY = ("apiVersion: policies.kyverno.io/v1\nkind: ValidatingPolicy\nmetadata:\n  name: p\nspec:\n  matchConstraints:\n"
          "    resourceRules:\n    - apiGroups: ['']\n      apiVersions: [v1]\n      operations: [CREATE, UPDATE]\n"
          "      resources: [namespaces]\n")
# The stub passes each Namespace that --resource names, as `kyverno apply -p --output-format json` reports it (#212).
KYVERNO = """#!{python}
import fcntl, json, sys, time
from pathlib import Path
import yaml
state = Path({state!r})
def count(delta):
    with open(state / "lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = (int((state / "now").read_text()) if (state / "now").exists() else 0) + delta
        (state / "now").write_text(str(now))
        peak = int((state / "peak").read_text()) if (state / "peak").exists() else 0
        (state / "peak").write_text(str(max(peak, now)))
if sys.argv[1:2] == ["version"]:
    print("Version: v1.20.0")
    sys.exit(0)
count(1)
try:
    time.sleep({seconds})
finally:
    count(-1)
files = sys.argv[sys.argv.index("--resource") + 1].split(",")
docs = [yaml.safe_load(open(f)) for f in files]
print(json.dumps({{"results": [{{"policy": "p", "result": "pass", "resources": [{{"kind": "Namespace", "name": d["metadata"]["name"]}}]}}
                               for d in docs if d.get("kind") == "Namespace"]}}))
"""


@pytest.fixture
def real_validator(world, tmp_path):
    """build(slots=None, seconds): cmapi's real validator in the world's pipeline, on stub binaries; returns its state folder,
    where `peak` is the most stub kyverno processes that ran at once."""
    client, ctx, *_ = world

    def build(slots=None, seconds=0.5):
        (tmp_path / "policies").mkdir()
        (tmp_path / "policies" / "p.yaml").write_text(POLICY)
        state = tmp_path / "state"
        state.mkdir()
        kyverno = tmp_path / "kyverno"
        kyverno.write_text(KYVERNO.format(python=sys.executable, state=str(state), seconds=seconds))
        kyverno.chmod(0o755)
        kubeconform = tmp_path / "kubeconform"
        kubeconform.write_text("#!/bin/sh\necho '{\"resources\": [], \"summary\": {\"valid\": 1}}'\n")
        kubeconform.chmod(0o755)
        ctx.pipeline.validator = CliValidator(tmp_path / "policies", kyverno=str(kyverno), kubeconform=str(kubeconform),
                                              policy=ctx.cfg.policy, environments=ctx.cfg.allowed_environments,
                                              **({"slots": slots} if slots is not None else {}))
        return state

    return build


def dry_run(client, keys):
    return client.post(f"{URL}?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))


def planned(r) -> bool:
    """A dry run's 200: the plan of the create, with the namespace's own file added."""
    return r.status_code == 200 and r.json()["changes"].get(f"clusters/CRC/namespaces/{NS['namespace']}/namespace.yaml") == "added"


def sample(name: str, **labels: str) -> float:
    """A metric's value now; 0 before its first sample."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


def busy_count(reason: str) -> float:
    return sample("cmapi_validator_busy_total", reason=reason)


def test_twelve_dry_runs_at_once_run_one_kyverno_at_a_time_and_the_rest_answer_503(world, real_validator):
    """The CRC case, with the default slots (one runs, four wait 15 s at most). Each answer is the plan or validator-busy."""
    client, ctx, git, kube, validator, keys = world
    state = real_validator()
    start = threading.Barrier(12, timeout=30)

    def one(_: int):
        start.wait()
        return dry_run(client, keys)

    with ThreadPoolExecutor(12) as pool:
        answers = list(pool.map(one, range(12)))
    assert int((state / "peak").read_text()) == 1, f"{(state / 'peak').read_text()} kyverno processes ran at once"
    statuses = sorted(r.status_code for r in answers)
    assert set(statuses) <= {200, 503} and statuses.count(200) >= 5 and 503 in statuses, statuses
    for r in answers:
        if r.status_code == 503:
            body = r.json()
            assert r.headers["content-type"] == "application/problem+json", r.headers
            assert body["code"] == "validator-busy" and body["retryAfter"] == 15, body
            assert r.headers["Retry-After"] == "15"
            assert body["detail"] == "The policy check is busy: 1 running and 4 waiting in this pod; try again in 15 s"
        else:
            assert planned(r), r.text


def test_a_dry_run_that_waits_longer_than_the_wait_answers_503_with_retry_after(world, real_validator):
    client, ctx, git, kube, validator, keys = world
    slots = V.ValidatorSlots(1, queue=1, wait_seconds=0.3)
    real_validator(slots=slots)
    before = busy_count("wait-timeout")
    with slots.hold():
        r = dry_run(client, keys)
    assert r.status_code == 503, r.text
    assert r.json()["code"] == "validator-busy" and r.json()["retryAfter"] == 1 and r.headers["Retry-After"] == "1", r.text
    assert "came free in 0.3 s" in r.json()["detail"]
    assert busy_count("wait-timeout") - before == 1
    # The slot is free again: the same dry run is the plan, as it was before #708.
    r = dry_run(client, keys)
    assert planned(r), r.text


def test_a_create_with_a_free_slot_is_unchanged(world, real_validator):
    """The normal path: a create plans, runs Kyverno once and opens its request (202)."""
    client, ctx, git, kube, validator, keys = world
    state = real_validator(seconds=0.1)
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    assert int((state / "peak").read_text()) == 1


def test_the_settings_size_the_slots_of_the_process(test_config, fresh_db, keys, monkeypatch):
    """CMAPI_VALIDATOR_CONCURRENCY, _QUEUE and _WAIT_SECONDS reach the one validator that build_context makes, and each
    slot's wait is observed in cmapi_validator_wait_seconds."""
    made = []

    class Recording(V.ValidatorSlots):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)

    monkeypatch.setattr(context_mod, "ValidatorSlots", Recording)
    monkeypatch.setenv("CMAPI_VALIDATOR_CONCURRENCY", "2")
    monkeypatch.setenv("CMAPI_VALIDATOR_QUEUE", "6")
    monkeypatch.setenv("CMAPI_VALIDATOR_WAIT_SECONDS", "7.5")
    with build_world(test_config, keys, monkeypatch):
        pass
    assert [(s.concurrency, s.queue, s.wait_seconds, s.retry_after) for s in made] == [(2, 6, 7.5, 8)]
    waits = sample("cmapi_validator_wait_seconds_count")
    with made[0].hold():
        pass
    assert sample("cmapi_validator_wait_seconds_count") == waits + 1


@pytest.mark.parametrize("name, value", [("CMAPI_VALIDATOR_CONCURRENCY", "0"), ("CMAPI_VALIDATOR_CONCURRENCY", "41"),
                                         ("CMAPI_VALIDATOR_QUEUE", "-1"), ("CMAPI_VALIDATOR_WAIT_SECONDS", "61"),
                                         ("CMAPI_VALIDATOR_WAIT_SECONDS", "inf"), ("CMAPI_VALIDATOR_WAIT_SECONDS", "nan")])
def test_a_slot_setting_out_of_range_stops_the_start(monkeypatch, name, value):
    from pydantic import ValidationError

    from cmapi.settings import Settings

    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_the_defaults_are_one_slot_four_waiting_and_fifteen_seconds(monkeypatch):
    from cmapi.settings import Settings

    for name in ("CMAPI_VALIDATOR_CONCURRENCY", "CMAPI_VALIDATOR_QUEUE", "CMAPI_VALIDATOR_WAIT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    s = Settings()
    assert (s.validator_concurrency, s.validator_queue, s.validator_wait_seconds) == (1, 4, 15.0)
    slots = V.ValidatorSlots()
    assert (slots.concurrency, slots.queue, slots.wait_seconds, slots.retry_after) == (1, 4, 15.0, 15)
