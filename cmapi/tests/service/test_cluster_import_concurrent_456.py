"""Deterministic overlapping refresh schedules for #456; every worker is joined."""
import threading

import httpx
from structlog.testing import capture_logs

from cmapi.core.registry import NO_IMPORT_SECRET
from test_cluster_import_log_456 import import_events, refusing
from test_registry_survives_419 import good, registry, secret


class ObservedRefreshLock:
    """Expose a contender's attempt without requiring it to acquire the lock.

    On the old implementation this lock is unused; the second refresh itself
    releases the paused first refresh. On the fix, its lock attempt releases it.
    Thus both schedules finish without sleeps or a timeout deciding the result.
    """
    def __init__(self, progress):
        self.lock = threading.Lock()
        self.progress = progress

    def __enter__(self):
        if threading.current_thread().name == "second-refresh":
            self.progress.set()
        self.lock.acquire()

    def __exit__(self, *args):
        self.lock.release()


def run_overlap(reg, ready, progress):
    reg._refresh_lock = ObservedRefreshLock(progress)
    errors = []

    def refresh():
        try:
            reg.refresh()
        except BaseException as exc:
            errors.append(exc)
        finally:
            if threading.current_thread().name == "second-refresh":
                progress.set()

    first = threading.Thread(target=refresh, name="first-refresh")
    second = threading.Thread(target=refresh, name="second-refresh")
    try:
        with capture_logs() as events:
            first.start()
            assert ready.wait(5), "first refresh never reached the pause"
            second.start()
            second.join(5)
            first.join(5)
        assert not first.is_alive() and not second.is_alive(), "refresh deadlocked"
        assert errors == []
        return import_events(events)
    finally:
        progress.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
        reg.stop()


def test_overlapping_first_checks_log_one_problem_for_unconfigured_cluster():
    ready, progress = threading.Event(), threading.Event()

    def bad_response(request):
        if threading.current_thread().name == "first-refresh":
            ready.set()
            assert progress.wait(5)
        else:
            progress.set()
        return httpx.Response(200, text="not JSON")

    reg = registry({"TEST": bad_response}, [secret("TEST")])
    reg.clusters.clear()
    reg.policies.clear()
    events = run_overlap(reg, ready, progress)
    assert len(events) == 1, events
    assert events[0]["status"] == "bad-response"
    assert reg.clusters["TEST"].status == "bad-response"


def test_overlapping_refresh_events_follow_state_transition_order():
    ready, progress = threading.Event(), threading.Event()

    def handler(request):
        return refusing(request) if threading.current_thread().name == "first-refresh" else good(request)

    reg = registry({"TEST": handler}, [secret("TEST")])
    log_mode = reg._log_mode

    def paused_mode(*args):
        if threading.current_thread().name == "first-refresh":
            ready.set()
            assert progress.wait(5)
        log_mode(*args)

    reg._log_mode = paused_mode
    events = run_overlap(reg, ready, progress)
    assert [e["status"] for e in events] == ["unreachable", "connected"], events
    assert [e["previous"] for e in events] == ["not-imported", "unreachable"]
    assert reg.clusters["TEST"].status == "connected"


def test_overlapping_removal_does_not_resurrect_a_retired_cluster():
    ready, progress = threading.Event(), threading.Event()

    def paused_failure(request):
        ready.set()
        assert progress.wait(5)
        return refusing(request)

    handlers = {"TEST": good}
    reg = registry(handlers, [secret("TEST")])
    reg.refresh()
    handlers["TEST"] = paused_failure
    list_secrets = reg.source.list
    reg.source.list = lambda: [] if threading.current_thread().name == "second-refresh" else list_secrets()
    run_overlap(reg, ready, progress)
    assert reg.clusters["TEST"].status == "not-imported"
    assert reg.clusters["TEST"].findings == [NO_IMPORT_SECRET]
    assert reg.clusters["TEST"].cache is None
    assert reg.clusters["TEST"].trust is None
