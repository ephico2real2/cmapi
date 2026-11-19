"""An HTTP read overlapping a refresh must return a status and time from the same check."""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from cmapi.core import registry
from conftest import build_world
from test_not_imported_404 import get
from test_status_since_403 import RELIST, START, clock


@pytest.mark.parametrize("path,rows,state,since", [
    ("/api/v1/clusters", "items", "status", "statusSince"),
    ("/api/v1/capacity", "clusters", "state", "asOf"),
    ("/api/v1/policies/results", "clusters", "state", "asOf"),
])
def test_read_during_first_failure(test_config, keys, monkeypatch, clock, path, rows, state, since):
    with build_world(test_config, keys, monkeypatch) as (client, ctx, _, kube, *_):
        [before] = get(client, keys, path)[rows]
        reg = ctx.registry
        lock = reg._lock
        dating, resume = threading.Event(), threading.Event()

        class PausedClock:
            @staticmethod
            def now(tz):
                dating.set()
                assert resume.wait(5), "reader never reached the registry"
                return START + RELIST

        class ObservedLock:
            def __enter__(self):
                if dating.is_set():
                    resume.set()  # The reader reached the lock. Let the writer finish.
                lock.acquire()

            def __exit__(self, *args):
                lock.release()

        monkeypatch.setattr(registry, "datetime", PausedClock)
        monkeypatch.setattr(reg, "_lock", ObservedLock())
        kube.unreachable = True
        with ThreadPoolExecutor(max_workers=1) as pool:
            writer = pool.submit(reg.refresh)
            try:
                assert dating.wait(5)
                [item] = get(client, keys, path)[rows]
            finally:
                resume.set()  # Also release the writer if the reader did not acquire the lock.
            writer.result(timeout=5)

        if item[state] == "unreachable":
            assert datetime.fromisoformat(item[since]) == START + RELIST
        else:
            assert (item[state], item[since]) == (before[state], before[since])
        assert reg.get("CRC").status_since == START + RELIST
