"""Review of #455 (#421): a watch cache's kind thread survives every malformed answer, and keeps its last good list.
Codex's F4 (a page's metadata of another JSON type) as OB3 corrected it, and what Codex missed: an object without
metadata.name, a watch event that is not an object, a projection that fails on a malformed object, and the thread itself.
Offline: real KubeClient over httpx.MockTransport. Each test fails on #455's head (7785e68) and passes with fixes-455.patch."""
from __future__ import annotations

import time

import httpx
import pytest

from cmapi.core.clients.kube import KubeClient, WatchCache
from cmapi.core.clients.nodes import NodeCache

GOOD = {"items": [{"metadata": {"name": "a"}}], "metadata": {"resourceVersion": "1"}}


def cache_over(answers, *, chunk=None, make=None):
    """A WatchCache (or what `make(client)` returns) whose list calls get `answers` in order and whose watch gets the next
    answer as its lines; serving the last answer sets the stop event, so `_loop` returns after it."""
    client = KubeClient("C", "https://kube.test", "reader-token-0123456789", insecure=True)
    queue = list(answers)
    made = make(client) if make else None
    cache = made.watch if made else WatchCache(client, ("Namespace",), chunk=chunk)

    def handle(request):
        body = queue.pop(0)
        if not queue:
            cache._stop.set()
        if request.url.params.get("watch"):
            return httpx.Response(200, content=body)
        return httpx.Response(200, json=body)
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handle), base_url="https://kube.test")
    return cache


def kept_last_good(cache, kind="Namespace"):
    before = cache.state[kind].last_good
    cache._loop(kind)                       # on the head, the exception leaves _loop: the kind's thread would end here
    st = cache.state[kind]
    return st, before


# ---------------------------------------------------------------- Codex's F4, corrected: the page's metadata and token

@pytest.mark.parametrize("metadata", ["broken", ["broken"], 42])
def test_a_page_whose_metadata_is_not_an_object_keeps_the_watch(metadata):
    cache = cache_over([GOOD, {"items": [], "metadata": metadata}], chunk=1)
    cache._list("Namespace")
    st, before = kept_last_good(cache)
    assert list(st.items) == ["/a"] and st.last_good == before and st.resource_version == "1"
    assert "bad response" in st.error and "metadata" in st.error


@pytest.mark.parametrize("token", [7, ["x"], {"x": 1}, True])
def test_a_continue_token_that_is_not_a_string_keeps_the_watch(token):
    """Codex's fix reads `continue or None`: false, 0 and [] end the list as if it were complete."""
    cache = cache_over([GOOD, {"items": [], "metadata": {"resourceVersion": "2", "continue": token}}], chunk=1)
    cache._list("Namespace")
    st, before = kept_last_good(cache)
    assert list(st.items) == ["/a"] and st.last_good == before and "metadata.continue" in st.error


@pytest.mark.parametrize("token", [False, 0, []])
def test_a_falsy_continue_of_another_type_is_refused_not_read_as_the_last_page(token):
    cache = cache_over([GOOD, {"items": [{"metadata": {"name": "b"}}], "metadata": {"resourceVersion": "2", "continue": token}}],
                       chunk=1)
    cache._list("Namespace")
    st, before = kept_last_good(cache)
    assert list(st.items) == ["/a"] and st.resource_version == "1" and "metadata.continue" in st.error


# ---------------------------------------------------------------- missed: an object without metadata.name

@pytest.mark.parametrize("chunk", [None, 1])
@pytest.mark.parametrize("item", [{}, {"metadata": "x"}, {"metadata": {"namespace": "n"}}, {"metadata": {"name": 5}}])
def test_a_listed_object_without_a_name_keeps_the_watch(item, chunk):
    cache = cache_over([GOOD, {"items": [item], "metadata": {"resourceVersion": "2"}}], chunk=chunk)
    cache._list("Namespace")
    st, before = kept_last_good(cache)
    assert list(st.items) == ["/a"] and st.last_good == before and "an object without metadata.name" in st.error


# ---------------------------------------------------------------- missed: a watch event that is not an object

@pytest.mark.parametrize("line", [b"[]\n", b'"x"\n', b'{"type": "ADDED", "object": "x"}\n',
                                  b'{"type": "ADDED", "object": {"spec": {}}}\n',
                                  b'{"type": "MODIFIED", "object": {"metadata": "x"}}\n'])
def test_a_malformed_watch_event_keeps_the_watch(line):
    cache = cache_over([GOOD, line, GOOD])       # list, watch (the bad event), and the relist the loop then makes
    cache.RELIST_SECONDS = 3600
    cache._loop("Namespace")
    st = cache.state["Namespace"]
    assert list(st.items) == ["/a"]
    assert st.error is None or "bad response" in st.error


# ---------------------------------------------------------------- missed: the projection, and the thread itself

def node(name, status):
    return {"metadata": {"name": name}, "status": status}


def test_a_node_the_projection_cannot_read_keeps_the_node_watch():
    """reduce_node calls status.get: a Node whose status is a string raised AttributeError, outside _loop's filter."""
    good = {"items": [node("n1", {"allocatable": {"cpu": "4", "memory": "8Gi"},
                                  "conditions": [{"type": "Ready", "status": "True"}]})], "metadata": {"resourceVersion": "1"}}
    cache = cache_over([good, {"items": [node("n2", "broken")], "metadata": {"resourceVersion": "2"}}],
                       make=lambda client: NodeCache(client, chunk=1))
    cache._list("Node")
    st, before = kept_last_good(cache, "Node")
    assert list(st.items) == ["/n1"] and st.last_good == before and "AttributeError" in st.error


def test_the_kind_thread_survives_a_malformed_relist_and_recovers():
    """The thread itself: a good list, a page that killed the thread on the head, then a good list with a new object."""
    recovered = {"items": [{"metadata": {"name": "a"}}, {"metadata": {"name": "b"}}], "metadata": {"resourceVersion": "3"}}
    cache = cache_over([GOOD, {"items": [], "metadata": "broken"}, recovered], chunk=1)
    cache.RELIST_SECONDS = 0                    # relist at once: no watch between the lists
    cache.start()
    thread = cache._threads[0]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and cache.state["Namespace"].resource_version != "3" and thread.is_alive():
        time.sleep(0.05)
    thread.join(5)
    st = cache.state["Namespace"]
    assert st.resource_version == "3" and sorted(st.items) == ["/a", "/b"] and st.error is None
