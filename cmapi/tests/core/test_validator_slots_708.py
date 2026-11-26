"""#708: the validator's slots bound how many plans run the Kyverno CLI at once in one process.

On CRC twelve concurrent create dry runs started twelve `kyverno apply` processes in the API's memory cgroup, and the
kubelet killed the container at its 512 MiB limit (exit 137). The stub `kyverno` here is a Python script that counts, under
an exclusive file lock, how many copies of itself are running, keeps the highest count, and sleeps while it holds its place:
so each test reads the real peak of child processes, not a count kept by the code under test.

    cd cmapi && PYTHONPATH=src python -m pytest tests/core/test_validator_slots_708.py -q
"""
from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import cmapi.core.validate as V
from cmapi.core.policy import PolicySettings
from cmapi.core.validate import CliValidator, ValidatorUnavailable

NAME = "abc-dev"
FILES = {f"clusters/C/namespaces/{NAME}/namespace.yaml": f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {NAME}\n"}
POLICY = ("apiVersion: policies.kyverno.io/v1\nkind: ValidatingPolicy\nmetadata:\n  name: p\nspec:\n  matchConstraints:\n"
          "    resourceRules:\n    - apiGroups: ['']\n      apiVersions: [v1]\n      operations: [CREATE, UPDATE]\n"
          "      resources: [namespaces]\n")
REPORT = {"summary": {"fail": 1}, "results": [{"policy": "p", "result": "fail", "message": "refused", "rule": "r",
                                               "resources": [{"kind": "Namespace", "name": NAME}]}]}
# The stub kyverno. {state} is a folder of this test alone: "now" is the number of copies running, "peak" the highest.
KYVERNO = """#!{python}
import fcntl, sys, time
from pathlib import Path
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
print({report!r})
sys.exit(1)
"""


def stub_kyverno(tmp_path: Path, seconds: float) -> tuple[str, Path]:
    state = tmp_path / "state"
    state.mkdir()
    path = tmp_path / "kyverno"
    path.write_text(KYVERNO.format(python=sys.executable, state=str(state), seconds=seconds, report=json.dumps(REPORT)))
    path.chmod(0o755)
    return str(path), state


def stub_kubeconform(tmp_path: Path, out: dict) -> str:
    path = tmp_path / "kubeconform"
    path.write_text(f"#!/bin/sh\necho '{json.dumps(out)}'\n")
    path.chmod(0o755)
    return str(path)


def validator(tmp_path: Path, seconds: float = 0.5, slots: V.ValidatorSlots | None = None,
              kubeconform: dict | None = None) -> tuple[CliValidator, Path]:
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies" / "p.yaml").write_text(POLICY)
    kyverno, state = stub_kyverno(tmp_path, seconds)
    kc = stub_kubeconform(tmp_path, kubeconform or {"resources": [], "summary": {"valid": 1}})
    return CliValidator(tmp_path / "policies", kyverno=kyverno, kubeconform=kc, policy=PolicySettings(),
                        **({"slots": slots} if slots is not None else {})), state


def at_once(v: CliValidator, n: int) -> list[object]:
    """n plans' validate() at the same moment; each gives its findings or the exception it raised."""
    start = threading.Barrier(n, timeout=30)

    def one(_: int) -> object:
        start.wait()
        try:
            return v.validate(FILES, "C", "dev")
        except ValidatorUnavailable as exc:
            return exc

    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(one, range(n)))


def peak(state: Path) -> int:
    return int((state / "peak").read_text())


def test_twelve_plans_at_once_run_one_kyverno_at_a_time_by_default(tmp_path):
    """The CRC case: twelve plans at once. Without the slots all twelve kyverno processes ran together."""
    v, state = validator(tmp_path)
    results = at_once(v, 12)
    assert peak(state) == 1, f"{peak(state)} kyverno processes ran at once"
    done = [r for r in results if isinstance(r, list)]
    busy = [r for r in results if isinstance(r, V.ValidatorBusy)]
    assert len(done) + len(busy) == 12, results
    # One runs and four wait (the defaults); the queue is full for the others, which are refused at once.
    assert len(done) >= 5 and busy, results
    assert {(b.reason, b.retry_after) for b in busy} == {("queue-full", 15)}
    assert all(r == done[0] for r in done) and [(f.source, f.rule) for f in done[0]] == [("kyverno", "p")]


@pytest.mark.parametrize("concurrency", [2, 3])
def test_the_configured_concurrency_is_the_peak(tmp_path, concurrency):
    """With room for every plan in the queue, all twelve pass, and never more than `concurrency` run at once. That the peak
    reaches it shows the stub sees concurrent runs, so the default's peak of 1 above is a bound and not a blind count."""
    v, state = validator(tmp_path, seconds=0.3, slots=V.ValidatorSlots(concurrency, queue=12, wait_seconds=30))
    results = at_once(v, 12)
    assert all(isinstance(r, list) for r in results), results
    assert peak(state) == concurrency


def test_a_plan_that_waits_longer_than_the_wait_is_refused_busy(tmp_path):
    slots = V.ValidatorSlots(1, queue=1, wait_seconds=0.2)
    v, state = validator(tmp_path, slots=slots)
    with slots.hold():
        with pytest.raises(V.ValidatorBusy, match=r"came free in 0\.2 s; try again in 1 s") as exc:
            v.validate(FILES, "C", "dev")
    assert (exc.value.reason, exc.value.retry_after) == ("wait-timeout", 1)
    assert not (state / "peak").exists(), "kyverno ran without a slot"
    assert [f.rule for f in v.validate(FILES, "C", "dev")] == ["p"], "the slot was not given back"


def test_a_plan_with_a_full_queue_is_refused_at_once_and_holds_no_slot(tmp_path):
    slots = V.ValidatorSlots(1, queue=0, wait_seconds=60)
    v, _ = validator(tmp_path, slots=slots)
    with slots.hold():
        with pytest.raises(V.ValidatorBusy, match=r"busy: 1 running and 0 waiting in this pod; try again in 60 s") as exc:
            v.validate(FILES, "C", "dev")
    assert exc.value.reason == "queue-full"
    v.validate(FILES, "C", "dev")


def test_a_check_that_fails_gives_its_slot_back(tmp_path):
    """kubeconform's schema download fails (ValidatorUnavailable) while the plan holds the slot: the next plan gets it."""
    out = {"resources": [{"filename": "x", "status": "statusError", "msg": "failed downloading schema at https://x"}]}
    v, _ = validator(tmp_path, slots=V.ValidatorSlots(1, queue=0, wait_seconds=0), kubeconform=out)
    for _ in range(3):
        with pytest.raises(ValidatorUnavailable) as exc:
            v.validate(FILES, "C", "dev")
        assert not isinstance(exc.value, V.ValidatorBusy)


def test_a_plan_with_no_files_takes_no_slot(tmp_path):
    slots = V.ValidatorSlots(1, queue=0, wait_seconds=0)
    v, _ = validator(tmp_path, slots=slots)
    with slots.hold():
        assert v.validate({"clusters/C/namespaces/abc-dev/namespace.yaml": None}, "C", "dev") == []


def test_each_holder_reports_its_wait(tmp_path):
    waits: list[float] = []
    v, _ = validator(tmp_path, seconds=0.2, slots=V.ValidatorSlots(1, queue=4, wait_seconds=30, on_wait=waits.append))
    at_once(v, 3)
    assert len(waits) == 3 and max(waits) >= 0.2, waits


@pytest.mark.parametrize("concurrency, queue, wait", [(0, 4, 15), (1, -1, 15), (1, 4, -1), (1, 4, float("inf")),
                                                      (1, 4, float("nan")), (1.5, 0, 0), (1, 0.5, 0), (True, 0, 0)])
def test_slots_refuse_a_bound_that_is_not_one(concurrency, queue, wait):
    with pytest.raises(ValueError, match="validator slots need"):
        V.ValidatorSlots(concurrency, queue, wait)


@pytest.mark.parametrize("wait, retry_after", [(0, 1), (0.2, 1), (15, 15), (14.5, 15)])
def test_retry_after_is_the_wait_in_whole_seconds_at_least_one(wait, retry_after):
    assert V.ValidatorSlots(1, 0, wait).retry_after == retry_after


def test_timeout_restores_the_entire_queue():
    # A queue of one must admit another waiter after *every* timeout, even while
    # the original holder is still running. A leaked admission becomes queue-full.
    slots = V.ValidatorSlots(1, queue=1, wait_seconds=0)
    for _ in range(2):
        with slots.hold():
            for _ in range(3):
                with pytest.raises(V.ValidatorBusy) as exc, slots.hold():
                    pytest.fail("two holders occupied one slot")
                assert exc.value.reason == "wait-timeout"


def test_failed_observer_restores_both_permits():
    def broken(_):
        raise RuntimeError("observation failed")

    slots = V.ValidatorSlots(1, queue=0, wait_seconds=0, on_wait=broken)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="observation failed"), slots.hold():
            pytest.fail("observer failed before the block")


def test_one_admission_covers_both_commands(tmp_path, monkeypatch):
    waits = []
    slots = V.ValidatorSlots(1, queue=0, wait_seconds=0, on_wait=waits.append)
    v, _ = validator(tmp_path, seconds=0, slots=slots)
    run = v._run
    commands = []

    def while_holding(cmd):
        with pytest.raises(V.ValidatorBusy), slots.hold():
            pytest.fail("CLI invoked outside admission")
        commands.append(Path(cmd[0]).name)
        return run(cmd)

    monkeypatch.setattr(v, "_run", while_holding)
    v.validate(FILES, "C", "dev")
    assert commands == ["kubeconform", "kyverno"]
    assert len(waits) == 1
