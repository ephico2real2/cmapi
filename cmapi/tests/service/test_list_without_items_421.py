"""#421: a 200 list answer without `items` is never read as an empty list (docs/02 "Client rules").

Read as empty, such an answer (a Status object, a proxy's own JSON) retired every imported cluster through the hub's list of
import Secrets, emptied a watch cache (and with it the CapacityLedger its ResourceQuotas feed), passed the capability check,
and counted no workloads before a delete. Now it is `BadResponse` (#419's class): the import keeps the previous set of clusters
(docs/02 "Discovery"), the watch keeps its last good list and records the error without a new good read, the capability check
is `bad-response` with a finding, and the workload count is a 503. A list whose `items` is [] or null is still an empty list.

The clients are the real KubeClient and HubImportSource over an httpx MockTransport. No database:

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_list_without_items_421.py -q -W ignore
"""
from __future__ import annotations

import base64
import itertools
from types import SimpleNamespace
from typing import Any, Callable

import httpx
import pytest

from cmapi.core.capacity_ledger import CapacityLedger
from cmapi.core.clients.kube import BadResponse, KubeClient, WatchCache
from cmapi.core.errors import Problem
from cmapi.core.pipeline import Pipeline
from cmapi.core.registry import READER_IDENTITY, ClusterPolicy, ClusterRegistry, HubImportSource
from test_capacity_ledger_302 import ledger_of, quota

TOKEN = "eyJhbGciOiJSUzI1NiJ9.reader-token-421"
HUB = "https://hub.example:6443"
STATUS = {"kind": "Status", "apiVersion": "v1", "metadata": {}, "status": "Success"}
# 200 answers that are no list. A Status (what an aggregated API or a proxy can answer), a list kind with no items (the
# kubernetes#124568 bug), and items of the wrong type.
NOT_A_LIST: dict[str, tuple[Any, str]] = {
    "status-object": (STATUS, "no items field: not a list"),
    "list-without-items": ({"kind": "SecretList", "apiVersion": "v1", "metadata": {"resourceVersion": "7"}},
                           "no items field: not a list"),
    "items-object": ({"items": {"name": "x"}, "metadata": {"resourceVersion": "7"}}, "items is a JSON object, not an array"),
    "items-string": ({"items": "none", "metadata": {"resourceVersion": "7"}}, "items is a JSON string, not an array"),
    "item-not-object": ({"items": ["cmapi-cluster-c"], "metadata": {"resourceVersion": "7"}}, "an item that is not an object"),
}


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


IMPORT_SECRET = {"metadata": {"name": "cmapi-cluster-c", "namespace": "cmapi-imports",
                              "labels": {"cmapi.net/secret-type": "cluster", "cmapi.net/cluster-id": "C"}},
                 "data": {"apiUrl": b64("https://c.example:6443"), "token": b64(TOKEN)}}


def cluster(request: httpx.Request) -> httpx.Response:
    """A cluster that passes the checks."""
    p = request.url.path
    if p == "/version":
        return httpx.Response(200, json={"gitVersion": "v1.35.6"})
    if p.endswith("/users/~"):
        return httpx.Response(200, json={"metadata": {"name": READER_IDENTITY}})
    if p == "/api/v1/namespaces":
        return httpx.Response(200, json={"items": [], "metadata": {"resourceVersion": "1"}})
    return httpx.Response(404)


def kube(handler: Callable[[httpx.Request], httpx.Response], cluster_id: str = "C") -> KubeClient:
    c = KubeClient(cluster_id, "https://c.example:6443", TOKEN)
    c._client = httpx.Client(base_url=c.api_url, headers=c._client.headers, transport=httpx.MockTransport(handler))
    return c


def hub_registry(tmp_path, answers: list[Any]) -> tuple[ClusterRegistry, list[Any]]:
    """A registry over the real HubImportSource, whose hub gives `answers` in turn, one per list."""
    (tmp_path / "token").write_text("hub-token-0123456789")
    source = HubImportSource(HUB, tmp_path / "token", tmp_path / "no-ca.crt", "cmapi-imports")
    queue = list(answers)

    def hub(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/namespaces/cmapi-imports/secrets"
        return httpx.Response(200, json=queue.pop(0))
    source.client = httpx.Client(base_url=HUB, transport=httpx.MockTransport(hub))
    reg = ClusterRegistry({"C": ClusterPolicy("C", "rnd", "clusters/C")}, source, start_caches=False,
                          client_factory=lambda cid, api_url, token, trust, *, insecure=False: kube(cluster, cid))
    return reg, queue


@pytest.mark.parametrize("shape", list(NOT_A_LIST))
def test_a_hub_list_without_items_keeps_every_cluster(tmp_path, capsys, shape):
    """The issue's measurement: pass 1 connected, pass 2 a 200 Status, and on main the cluster was `not-imported`."""
    body, why = NOT_A_LIST[shape]
    reg, queue = hub_registry(tmp_path, [{"items": [IMPORT_SECRET], "metadata": {"resourceVersion": "1"}}, body])
    reg.refresh()
    first = reg.clusters["C"]
    assert (first.status, first.findings) == ("connected", []), first.findings
    cache = first.cache
    capsys.readouterr()
    reg.refresh()
    assert not queue
    st = reg.clusters["C"]
    assert (st.status, st.findings) == ("connected", []), st.findings
    assert st.cache is cache and st.client is cache.client                  # its watch cache and client were not stopped
    logged = capsys.readouterr().out
    assert "imports_list_failed" in logged and f"bad response on /api/v1/namespaces/cmapi-imports/secrets (200): {why}" in logged


@pytest.mark.parametrize("empty", [{"items": [], "metadata": {"resourceVersion": "2"}}, {"items": None, "metadata": {}}],
                         ids=["items-empty", "items-null"])
def test_a_hub_list_that_is_empty_still_retires_the_cluster(tmp_path, empty):
    """Behaviour kept: a list that says it is empty ([] or null, the same to Go) means the import Secret is gone."""
    reg, _ = hub_registry(tmp_path, [{"items": [IMPORT_SECRET], "metadata": {"resourceVersion": "1"}}, empty])
    reg.refresh()
    assert reg.clusters["C"].status == "connected"
    reg.refresh()
    assert (reg.clusters["C"].status, reg.clusters["C"].findings, reg.clusters["C"].cache) == ("not-imported", ["no import Secret"], None)


@pytest.mark.parametrize("shape", list(NOT_A_LIST))
def test_a_namespace_list_without_items_fails_the_capability_check(shape):
    """Check 6 lists namespaces: an answer that is no list is `bad-response` with its finding, not `connected`."""
    body, why = NOT_A_LIST[shape]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body) if request.url.path == "/api/v1/namespaces" else cluster(request)
    secret = {"name": "cmapi-cluster-c", "labels": {"cmapi.net/cluster-id": "C"}, "annotations": {},
              "data": {"apiUrl": "https://c.example:6443", "token": TOKEN}}
    reg = ClusterRegistry({"C": ClusterPolicy("C", "rnd", "clusters/C")}, SimpleNamespace(list=lambda: [secret]),
                          start_caches=False, client_factory=lambda cid, api_url, token, trust, *, insecure=False: kube(handler))
    reg.refresh()
    st = reg.clusters["C"]
    assert (st.status, st.findings, st.cache) == ("bad-response", [f"bad response on /api/v1/namespaces (200): {why}"], None)


def namespace(name: str) -> dict:
    return {"kind": "Namespace", "metadata": {"name": name, "resourceVersion": "5"}}


class Cluster:
    """Lists in turn: the first answer is good, the next is `relist`. Watches end at once, empty."""

    def __init__(self, kind_path: str, first: list[dict], relist: Any, *, on_relist: Callable[[], None] = lambda: None,
                 chunk: int | None = None):
        self.kind_path, self.first, self.relist, self.on_relist, self.chunk = kind_path, first, relist, on_relist, chunk
        self.lists = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == self.kind_path, request.url
        if request.url.params.get("watch"):
            return httpx.Response(200, text="")
        cont = request.url.params.get("continue")
        if cont is None:
            self.lists += 1
        if self.lists == 1:
            if self.chunk is None:
                return httpx.Response(200, json={"items": self.first, "metadata": {"resourceVersion": "10"}})
            start = int(cont or 0)
            more = start + self.chunk < len(self.first)
            meta = {"resourceVersion": "10", **({"continue": str(start + self.chunk)} if more else {})}
            return httpx.Response(200, json={"items": self.first[start:start + self.chunk], "metadata": meta})
        self.on_relist()
        if self.chunk is not None and cont is None:          # the relist's first page is good; its second is not a list
            return httpx.Response(200, json={"items": self.first[:1], "metadata": {"resourceVersion": "11", "continue": "1"}})
        return httpx.Response(200, json=self.relist)


def run_list_then_relist(cache: WatchCache, kind: str) -> None:
    """One pass of the cache's own loop: list, one empty watch, the relist (the clock runs past RELIST_SECONDS at once), then
    the relist's failure is recorded and the loop ends, because the cluster stopped the cache as it answered the relist."""
    cache._loop(kind)


@pytest.mark.parametrize("chunk", [None, 1], ids=["one-call", "in-chunks"])
@pytest.mark.parametrize("shape", list(NOT_A_LIST))
def test_a_relist_without_items_keeps_the_cached_objects_and_records_the_error(capsys, shape, chunk):
    body, why = NOT_A_LIST[shape]
    clock = itertools.count(1000.0, 1000.0).__next__                   # each reading 1000 s on: the relist comes at once
    holder: dict[str, WatchCache] = {}
    server = Cluster("/api/v1/namespaces", [namespace("a"), namespace("b")], body, chunk=chunk,
                     on_relist=lambda: holder["cache"]._stop.set())
    dropped: list[str] = []
    cache = WatchCache(kube(server), ("Namespace",), clock, dropped=lambda kind, key: dropped.append(key), chunk=chunk)
    holder["cache"] = cache
    run_list_then_relist(cache, "Namespace")
    st = cache.state["Namespace"]
    assert server.lists == 2
    assert sorted(st.items) == ["/a", "/b"] and dropped == []                     # the last good list, every object kept
    assert st.last_good == 1000.0 and st.resource_version == "10"               # no good read since: the relist did not count
    assert (st.error_status, st.error) == (None, f"bad response on /api/v1/namespaces (200): {why}")
    assert cache.kind_error("Namespace") == (None, st.error)
    assert "watch_cache" in capsys.readouterr().out


def test_the_capacity_ledger_keeps_its_quotas_when_a_relist_has_no_items():
    """The issue's consequence: the CapacityLedger forgot every quota, so the committed total read 0 on a fresh cache."""
    quotas = [quota("a", {"requests.cpu": "4", "requests.memory": "8Gi"}), quota("b", {"requests.cpu": "2", "requests.memory": "4Gi"})]
    clock = itertools.count(1000.0, 1000.0).__next__
    holder: dict[str, WatchCache] = {}
    server = Cluster("/api/v1/resourcequotas", quotas, STATUS, on_relist=lambda: holder["cache"]._stop.set())
    ledger = CapacityLedger()
    cache = WatchCache(kube(server), ("ResourceQuota",), clock, admit=ledger.admit, dropped=ledger.dropped)
    holder["cache"] = cache
    run_list_then_relist(cache, "ResourceQuota")
    assert server.lists == 2 and cache.state["ResourceQuota"].error is not None
    assert ledger.totals() == ledger_of(*quotas).totals() and ledger.totals().namespaces == 2, ledger.totals()


def test_a_list_whose_items_is_null_is_an_empty_list():
    """Go writes a nil slice as null; the API's guidance is that null and [] mean the same in a list field (kubernetes#43422)."""
    out = kube(lambda r: httpx.Response(200, json={"items": None, "metadata": {"resourceVersion": "3"}})).list("Namespace")
    assert out["items"] == [] and out["metadata"] == {"resourceVersion": "3"}


def test_a_list_without_a_resource_version_is_bad_response_not_the_end_of_the_watch_thread():
    """`_fetch` read metadata.resourceVersion with [] [], so its KeyError, which `_loop` does not catch, ended the kind's
    thread for good. It is BadResponse now, a ValueError the loop retries."""
    cache = WatchCache(kube(lambda r: httpx.Response(200, json={"items": [namespace("a")], "metadata": {}})), ("Namespace",))
    with pytest.raises(BadResponse, match="no metadata.resourceVersion") as caught:
        cache._list("Namespace")
    assert isinstance(caught.value, ValueError) and cache.state["Namespace"].items == {}


@pytest.mark.parametrize("shape", list(NOT_A_LIST))
def test_a_workload_count_without_items_is_unknown_not_zero(shape):
    """The delete thresholds count Pods and PVCs live: an answer that is no list is 503, never 0 workloads."""
    body, why = NOT_A_LIST[shape]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/namespaces/payments-dev/pods":
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={"items": [{"metadata": {"name": "pvc"}}], "metadata": {"resourceVersion": "1"}})
    registry = SimpleNamespace(cache=lambda cluster_id: SimpleNamespace(client=kube(handler)))
    with pytest.raises(Problem) as caught:
        Pipeline.workload_counts(SimpleNamespace(registry=registry), "C", "payments-dev")
    assert caught.value.status == 503 and caught.value.code == "cluster-unreachable"
    assert why in caught.value.detail, caught.value.detail
