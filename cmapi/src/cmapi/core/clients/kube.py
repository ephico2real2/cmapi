"""The Kubernetes API client and the watch cache (docs/01, "Reads are live").

KubeClient speaks to one cluster's API over HTTPS with that cluster's imported token and CA.
Every call is counted in cmapi_cluster_api_calls_total. It is used for reads through cmapi-reader
and, by the worker's delivery job only, for server-side apply with the deliverer identity.

WatchCache keeps namespaces, ResourceQuotas and LimitRanges of one cluster current from a
list-then-watch loop per kind, in a daemon thread, with a full relist every 30 minutes and a
reconnect with backoff on any error. A read never calls the cluster; a cluster that cannot be
reached keeps its rows, marked stale with the time of the last good read.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping

import httpx

from cmapi.core.errors import Problem
from cmapi.core.observability import CLUSTER_CALLS, log

APPLY_FIELD_MANAGER = "cmapi-deliverer"

# kind -> (api path for cluster-scoped list, namespaced?)
RESOURCES = {
    "Namespace": ("/api/v1/namespaces", False),
    "ResourceQuota": ("/api/v1/resourcequotas", True),
    "LimitRange": ("/api/v1/limitranges", True),
    "ServiceAccount": ("/api/v1/serviceaccounts", True),
    "RoleBinding": ("/apis/rbac.authorization.k8s.io/v1/rolebindings", True),
    "Node": ("/api/v1/nodes", False),
    "Pod": ("/api/v1/pods", True),
    "PersistentVolumeClaim": ("/api/v1/persistentvolumeclaims", True),
}


class ClusterUnreachable(RuntimeError):
    pass


class KubeClient:
    def __init__(self, cluster_id: str, api_url: str, token: str, ca_file: str | None = None, *,
                 insecure: bool = False, timeout: float = 10.0):
        self.cluster_id, self.api_url = cluster_id, api_url.rstrip("/")
        verify: bool | str = False if insecure else (ca_file or True)
        self._client = httpx.Client(base_url=self.api_url, verify=verify, timeout=timeout,
                                    headers={"Authorization": f"Bearer {token}"})

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            r = self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            CLUSTER_CALLS.labels(self.cluster_id, "error").inc()
            raise ClusterUnreachable(f"{self.cluster_id}: {type(exc).__name__}: {exc}") from exc
        CLUSTER_CALLS.labels(self.cluster_id, "ok" if r.status_code < 400 else str(r.status_code)).inc()
        return r

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        r = self._request("GET", path, params=params)
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise KubeError(r.status_code, path, r.text)
        return r.json()

    def version(self) -> str:
        r = self._request("GET", "/version")
        if r.status_code >= 400:
            raise KubeError(r.status_code, "/version", r.text)
        return r.json().get("gitVersion", "?")

    def whoami(self) -> str:
        """OpenShift's users/~ names the identity; on plain Kubernetes a SelfSubjectReview does."""
        r = self._request("GET", "/apis/user.openshift.io/v1/users/~")
        if r.status_code == 200:
            return r.json()["metadata"]["name"]
        r = self._request("POST", "/apis/authentication.k8s.io/v1/selfsubjectreviews",
                          json={"apiVersion": "authentication.k8s.io/v1", "kind": "SelfSubjectReview"})
        if r.status_code in (200, 201):
            return r.json()["status"]["userInfo"]["username"]
        raise KubeError(r.status_code, "whoami", r.text)

    def list(self, kind: str, namespace: str | None = None, label_selector: str | None = None,
             resource_version: str | None = None) -> dict[str, Any]:
        path, namespaced = RESOURCES[kind]
        if namespaced and namespace:
            path = path.replace("/v1/", f"/v1/namespaces/{namespace}/", 1)
        params: dict[str, Any] = {}
        if label_selector:
            params["labelSelector"] = label_selector
        if resource_version is not None:
            params["resourceVersion"] = resource_version
        out = self.get(path, params)
        if out is None:
            raise KubeError(404, path, "list not found")
        return out

    def get_object(self, kind: str, namespace: str | None, name: str) -> dict[str, Any] | None:
        path, namespaced = RESOURCES[kind]
        if namespaced:
            path = path.replace("/v1/", f"/v1/namespaces/{namespace}/", 1)
        return self.get(f"{path}/{name}")

    def watch(self, kind: str, resource_version: str, timeout_seconds: int = 300) -> Iterator[dict[str, Any]]:
        path, _ = RESOURCES[kind]
        params = {"watch": "1", "resourceVersion": resource_version, "timeoutSeconds": timeout_seconds,
                  "allowWatchBookmarks": "true"}
        try:
            with self._client.stream("GET", path, params=params, timeout=timeout_seconds + 10) as r:
                if r.status_code >= 400:
                    raise KubeError(r.status_code, path, "watch refused")
                for line in r.iter_lines():
                    if line:
                        yield json.loads(line)
        except httpx.HTTPError as exc:
            raise ClusterUnreachable(f"{self.cluster_id}: watch {kind}: {exc}") from exc

    # ---- the one write path, used only by the delivery job with the deliverer identity
    def apply(self, doc: Mapping[str, Any], field_manager: str = APPLY_FIELD_MANAGER) -> dict[str, Any]:
        kind, meta = doc["kind"], doc["metadata"]
        path, namespaced = RESOURCES[kind]
        if namespaced:
            path = path.replace("/v1/", f"/v1/namespaces/{meta['namespace']}/", 1)
        r = self._request("PATCH", f"{path}/{meta['name']}", params={"fieldManager": field_manager, "force": "true"},
                          content=json.dumps(doc), headers={"Content-Type": "application/apply-patch+yaml"})
        if r.status_code >= 400:
            raise KubeError(r.status_code, path, r.text)
        return r.json()

    def delete(self, kind: str, namespace: str | None, name: str) -> None:
        path, namespaced = RESOURCES[kind]
        if namespaced:
            path = path.replace("/v1/", f"/v1/namespaces/{namespace}/", 1)
        r = self._request("DELETE", f"{path}/{name}")
        if r.status_code not in (200, 202, 404):
            raise KubeError(r.status_code, path, r.text)


class KubeError(RuntimeError):
    def __init__(self, status: int, path: str, body: str):
        super().__init__(f"{status} on {path}: {body[:300]}")
        self.status, self.path = status, path


@dataclass
class CacheState:
    items: dict[str, dict[str, Any]] = field(default_factory=dict)      # key -> object
    resource_version: str | None = None
    last_good: float | None = None                                       # time.time() of the last list or event
    error: str | None = None


class WatchCache:
    """List-then-watch of the kinds cmapi reads, for one cluster."""

    KINDS = ("Namespace", "ResourceQuota", "LimitRange")
    RELIST_SECONDS = 1800

    def __init__(self, client: KubeClient, kinds: tuple[str, ...] = KINDS, clock: Callable[[], float] = time.time):
        self.client, self.kinds, self.clock = client, kinds, clock
        self.state: dict[str, CacheState] = {k: CacheState() for k in kinds}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @staticmethod
    def _key(obj: Mapping[str, Any]) -> str:
        m = obj["metadata"]
        return f"{m.get('namespace', '')}/{m['name']}"

    def _list(self, kind: str) -> None:
        out = self.client.list(kind)
        with self._lock:
            st = self.state[kind]
            st.items = {self._key(o): o for o in out.get("items", [])}
            st.resource_version = out["metadata"]["resourceVersion"]
            st.last_good, st.error = self.clock(), None

    def _loop(self, kind: str) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._list(kind)
                backoff = 1.0
                listed_at = self.clock()
                while not self._stop.is_set() and self.clock() - listed_at < self.RELIST_SECONDS:
                    rv = self.state[kind].resource_version or "0"
                    for ev in self.client.watch(kind, rv, timeout_seconds=60):
                        t, obj = ev.get("type"), ev.get("object", {})
                        if t == "ERROR":
                            raise KubeError(410, kind, json.dumps(obj)[:200])
                        with self._lock:
                            st = self.state[kind]
                            st.resource_version = obj.get("metadata", {}).get("resourceVersion", st.resource_version)
                            st.last_good = self.clock()
                            if t in ("ADDED", "MODIFIED"):
                                st.items[self._key(obj)] = obj
                            elif t == "DELETED":
                                st.items.pop(self._key(obj), None)
                        if self._stop.is_set():
                            break
            except (ClusterUnreachable, KubeError, ValueError) as exc:
                with self._lock:
                    self.state[kind].error = str(exc)[:200]
                log.warning("watch_cache", cluster_id=self.client.cluster_id, kind=kind, error=str(exc)[:200],
                            retry_in=backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60.0)

    def start(self) -> None:
        for kind in self.kinds:
            t = threading.Thread(target=self._loop, args=(kind,), name=f"watch-{self.client.cluster_id}-{kind}",
                                 daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    def wait_ready(self, timeout: float = 15.0) -> bool:
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            if all(self.state[k].last_good is not None for k in self.kinds):
                return True
            time.sleep(0.1)
        return False

    # ---- reads
    def all(self, kind: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.state[kind].items.values())

    def get(self, kind: str, namespace: str | None, name: str) -> dict[str, Any] | None:
        with self._lock:
            return self.state[kind].items.get(f"{namespace or ''}/{name}")

    def stale(self) -> tuple[bool, float | None]:
        """(no good read in the last relist window, time of the last good read)."""
        with self._lock:
            goods = [st.last_good for st in self.state.values()]
        last = min((g for g in goods if g is not None), default=None)
        return (last is None or self.clock() - last > self.RELIST_SECONDS, last)

    def namespace(self, name: str) -> dict[str, Any] | None:
        """A namespace by name, falling back to a direct read when the cache has not listed yet."""
        if self.state["Namespace"].last_good is None:
            try:
                return self.client.get_object("Namespace", None, name)
            except ClusterUnreachable as exc:
                raise Problem(503, "cluster-unreachable", str(exc), extra={"retryAfter": 30}) from exc
        return self.get("Namespace", None, name)
