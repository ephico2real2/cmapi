"""#402, the job side: watch_sync reads the cluster's client once in argocd mode.

`watch_sync` checked `st.client is None` and then passed a second read of `st.client` to `ArgoCdSignal`. The registry sets
`client` to None from its own thread (`_set`, the relist) when a cluster leaves `connected`; landing between the two reads,
the job built `ArgoCdSignal(None, ...)` and died on `None.get` with an AttributeError: a failed attempt of five, where the
module's rule is that a cluster that is not connected is something to wait for (`_reader_cache`, `ClusterUnreachable`).

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_watch_sync_client_once_402.py -q -W ignore
"""
from __future__ import annotations

from cmapi.core.clients.kube import KubeError
from cmapi.core.db.repo import JobRepo
from cmapi.jobs import HANDLERS
from test_cache_read_once_402 import cleared
from test_flow import NS, OLA, auth
from test_review_d_delivery import run_until_merged


class ArgoNotYet:
    """A reader whose Argo CD Application is not there yet: the KubeError that watch_sync waits on."""

    cluster_id = "CRC"

    def get(self, path, params=None):
        raise KubeError(404, path, "application not found")


def test_watch_sync_reads_the_client_it_checked(world):
    client, ctx, git, kube, validator, keys = world
    assert client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).status_code == 202
    assert run_until_merged(ctx) == "watch_sync"
    ctx.delivery = type(ctx.delivery)(**{**ctx.delivery.__dict__, "mode": "argocd"})
    ctx.registry.clusters["CRC"].client = ArgoNotYet()
    reads = cleared(ctx, "client")                  # the check reads the client; the clear lands before the next read
    with ctx.db.session() as s:
        job = JobRepo(s).claim("t")
        assert job.kind == "watch_sync"
        jid = job.job_id
    with ctx.db.session() as s:
        job = s.get(type(job), jid)
        HANDLERS["watch_sync"](ctx, s, job)         # a wait, never an AttributeError on None
        assert job.done_at is None and "application not found" in (job.last_error or ""), job.last_error
    assert len(reads) == 1, f"st.client read {len(reads)} times"
