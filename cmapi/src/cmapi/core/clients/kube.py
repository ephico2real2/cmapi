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
    # Kyverno's reports and the policy kind that cmapi renders (#302), read by the reader's own rule for them.
    "PolicyReport": ("/apis/wgpolicyk8s.io/v1alpha2/policyreports", True),
    "ClusterPolicyReport": ("/apis/wgpolicyk8s.io/v1alpha2/clusterpolicyreports", False),
    "ValidatingPolicy": ("/apis/policies.kyverno.io/v1/validatingpolicies", False),
}


def resource_path(kind: str, namespace: str | None = None) -> str:
    """The collection path of a kind, in one namespace when the kind is namespaced and a namespace is given:
    /api/v1/namespaces/<ns>/pods, /apis/<group>/<version>/namespaces/<ns>/<plural>."""
    path, namespaced = RESOURCES[kind]
    if namespaced and namespace:
        base, plural = path.rsplit("/", 1)
        return f"{base}/namespaces/{namespace}/{plural}"
    return path


_JSON_TYPES = {list: "array", str: "string", int: "number", float: "number", bool: "boolean", type(None): "null"}


class ClusterUnreachable(RuntimeError):
    pass


class BadResponse(ValueError):
    """An answer of the cluster that the client cannot read: a body that is not JSON, JSON that is not an object, or an
    object without a field the call needs. docs/02 "Client rules" names the outcome bad-response (#419).

    A ValueError, as json's own decode error is, so every loop that already retries on a ValueError (`WatchCache._loop`,
    `NodeCache`) keeps doing so. The message never holds the body: it names the path, the status and what was wrong."""

    def __init__(self, path: str, status: int, why: str):
        super().__init__(f"bad response on {path} ({status}): {why}")
        self.path, self.status = path, status


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

    @staticmethod
    def _object(r: httpx.Response, path: str) -> dict[str, Any]:
        """The JSON object of a successful answer, or BadResponse: a proxy's login page, a truncated body or a JSON list
        is the cluster's answer, never a crash of the caller (#419)."""
        try:
            body = r.json()
        except (ValueError, RecursionError) as exc:     # JSONDecodeError, UnicodeDecodeError; a body nested past the limit
            raise BadResponse(path, r.status_code, f"not JSON ({r.headers.get('content-type', 'no content type')[:60]})") from exc
        if not isinstance(body, dict):
            raise BadResponse(path, r.status_code, f"a JSON {_JSON_TYPES.get(type(body), 'value')}, not an object")
        return body

    @staticmethod
    def _text(body: Mapping[str, Any], r: httpx.Response, path: str, *keys: str) -> str:
        """The non-empty string at body[keys[0]][keys[1]]..., or BadResponse naming the field."""
        value: Any = body
        for k in keys:
            value = value.get(k) if isinstance(value, Mapping) else None
        if not isinstance(value, str) or not value:
            raise BadResponse(path, r.status_code, f"no {'.'.join(keys)}")
        return value

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        r = self._request("GET", path, params=params)
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise KubeError(r.status_code, path, r.text)
        return self._object(r, path)

    def version(self) -> str:
        r = self._request("GET", "/version")
        if r.status_code >= 400:
            raise KubeError(r.status_code, "/version", r.text)
        version = self._object(r, "/version").get("gitVersion")
        return version if isinstance(version, str) and version else "?"

    def whoami(self) -> str:
        """OpenShift's users/~ names the identity; on plain Kubernetes a SelfSubjectReview does."""
        path = "/apis/user.openshift.io/v1/users/~"
        r = self._request("GET", path)
        if r.status_code == 200:
            return self._text(self._object(r, path), r, path, "metadata", "name")
        path = "/apis/authentication.k8s.io/v1/selfsubjectreviews"
        r = self._request("POST", path, json={"apiVersion": "authentication.k8s.io/v1", "kind": "SelfSubjectReview"})
        if r.status_code in (200, 201):
            return self._text(self._object(r, path), r, path, "status", "userInfo", "username")
        raise KubeError(r.status_code, "whoami", r.text)

    def served(self, group_version: str) -> bool:
        """Whether the API server serves a group version, from discovery (GET /apis/<group>/<version>).

        Discovery is open to every authenticated identity (system:discovery), so it tells "not installed" (404) from "not
        granted": a list of a kind that the API server does not serve answers 403 to an identity without the grant, because
        authorization runs before the 404 (measured on CRC, #302 design A)."""
        r = self._request("GET", f"/apis/{group_version}")
        if r.status_code == 404:
            return False
        if r.status_code >= 400:
            raise KubeError(r.status_code, f"/apis/{group_version}", r.text)
        return True

    def list(self, kind: str, namespace: str | None = None, label_selector: str | None = None,
             resource_version: str | None = None, *, limit: int | None = None, continue_: str | None = None) -> dict[str, Any]:
        """One list call. `limit` and `continue_` page a large collection (API concepts, "Retrieving large results sets in
        chunks"); without them the API server answers in one response."""
        path = resource_path(kind, namespace)
        params: dict[str, Any] = {}
        if label_selector:
            params["labelSelector"] = label_selector
        if resource_version is not None:
            params["resourceVersion"] = resource_version
        if limit is not None:
            params["limit"] = limit
        if continue_:
            params["continue"] = continue_
        out = self.get(path, params)
        if out is None:
            raise KubeError(404, path, "list not found")
        return out

    def get_object(self, kind: str, namespace: str | None, name: str) -> dict[str, Any] | None:
        return self.get(f"{resource_path(kind, namespace)}/{name}")

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
        path = resource_path(kind, meta.get("namespace"))
        r = self._request("PATCH", f"{path}/{meta['name']}", params={"fieldManager": field_manager, "force": "true"},
                          content=json.dumps(doc), headers={"Content-Type": "application/apply-patch+yaml"})
        if r.status_code >= 400:
            raise KubeError(r.status_code, path, r.text)
        return self._object(r, path)

    def delete(self, kind: str, namespace: str | None, name: str) -> None:
        path = resource_path(kind, namespace)
        r = self._request("DELETE", f"{path}/{name}")
        if r.status_code not in (200, 202, 404):
            raise KubeError(r.status_code, path, r.text)


class KubeError(RuntimeError):
    def __init__(self, status: int, path: str, body: str):
        super().__init__(f"{status} on {path}: {body[:300]}")
        self.status, self.path = status, path


@dataclass
class CacheState:
    items: dict[str, Any] = field(default_factory=dict)                  # key -> object, or its projection
    resource_version: str | None = None
    last_good: float | None = None                                       # time.time() of the last list or event
    error: str | None = None
    error_status: int | None = None                                      # the HTTP status of the last error, when it had one


class WatchCache:
    """List-then-watch of the kinds cmapi reads, for one cluster.

    `project(kind, obj)` keeps what a reader needs instead of the object (#302: a PolicyReport is reduced to its non-pass
    results and counters). It must be pure: a chunked list projects each page as it arrives, so the raw objects of one page
    at most are held, never the whole collection. `admit(kind, key, value)` sees each projected value as it enters the
    cache (a committed list or an event) and returns what is stored, after `dropped(kind, key)` was told of each key that
    left: by a DELETED event, or by a relist that no longer holds it. `chunk` lists in pages of that size (`limit` and
    `continue`): a 410 on a continue token restarts the list after the backoff, like any other failed list."""

    KINDS = ("Namespace", "ResourceQuota", "LimitRange")
    RELIST_SECONDS = 1800

    def __init__(self, client: KubeClient, kinds: tuple[str, ...] = KINDS, clock: Callable[[], float] = time.time, *,
                 project: Callable[[str, dict[str, Any]], Any] | None = None,
                 admit: Callable[[str, str, Any], Any] | None = None,
                 dropped: Callable[[str, str], None] | None = None, chunk: int | None = None):
        self.client, self.kinds, self.clock = client, kinds, clock
        self.project, self.admit, self.dropped, self.chunk = project, admit, dropped, chunk
        self.state: dict[str, CacheState] = {k: CacheState() for k in kinds}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @staticmethod
    def _key(obj: Mapping[str, Any]) -> str:
        m = obj["metadata"]
        return f"{m.get('namespace', '')}/{m['name']}"

    def _value(self, kind: str, obj: dict[str, Any]) -> Any:
        return self.project(kind, obj) if self.project else obj

    def _admitted(self, kind: str, key: str, value: Any) -> Any:
        return self.admit(kind, key, value) if self.admit else value

    def _fetch(self, kind: str) -> tuple[list[tuple[str, Any]], str]:
        """(key, projected value) of every object of the kind, and the list's resourceVersion, in one call or in chunks.
        Each page is projected before the next is asked for, so its raw objects are released page by page."""
        if not self.chunk:
            out = self.client.list(kind)
            return [(self._key(o), self._value(kind, o)) for o in out.get("items", [])], out["metadata"]["resourceVersion"]
        values: list[tuple[str, Any]] = []
        token: str | None = None
        while True:
            out = self.client.list(kind, limit=self.chunk, continue_=token)
            values.extend((self._key(o), self._value(kind, o)) for o in out.get("items", []))
            token = (out.get("metadata") or {}).get("continue") or None
            if token is None:
                return values, out["metadata"]["resourceVersion"]
            del out                         # the page's raw objects go before the next page arrives

    def _list(self, kind: str) -> None:
        values, rv = self._fetch(kind)
        with self._lock:
            st = self.state[kind]
            fresh = {key for key, _ in values}
            if self.dropped:
                for key in set(st.items) - fresh:
                    self.dropped(kind, key)
            st.items = {key: self._admitted(kind, key, value) for key, value in values}
            st.resource_version = rv
            st.last_good, st.error, st.error_status = self.clock(), None, None

    def _event(self, kind: str, ev: Mapping[str, Any]) -> None:
        """One watch event into the cache: ADDED and MODIFIED through `project` and `admit`, DELETED through `dropped`; a
        BOOKMARK only moves the resourceVersion and the last good read. ERROR raises, so the loop lists again."""
        t, obj = ev.get("type"), ev.get("object", {})
        if t == "ERROR":
            raise KubeError(410, kind, json.dumps(obj)[:200])
        with self._lock:
            st = self.state[kind]
            st.resource_version = obj.get("metadata", {}).get("resourceVersion", st.resource_version)
            st.last_good = self.clock()
            if t in ("ADDED", "MODIFIED"):
                key = self._key(obj)
                st.items[key] = self._admitted(kind, key, self._value(kind, obj))
            elif t == "DELETED":
                if st.items.pop(self._key(obj), None) is not None and self.dropped:
                    self.dropped(kind, self._key(obj))

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
                        self._event(kind, ev)
                        if self._stop.is_set():
                            break
            except (ClusterUnreachable, KubeError, ValueError) as exc:
                with self._lock:
                    self.state[kind].error = str(exc)[:200]
                    self.state[kind].error_status = exc.status if isinstance(exc, KubeError) else None
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
        """(no good read in the last relist window, time of the last good read), over the kinds that have listed: a kind
        that never listed does not count, so a caller that needs one kind uses `kind_stale` (#393)."""
        with self._lock:
            goods = [st.last_good for st in self.state.values()]
        last = min((g for g in goods if g is not None), default=None)
        return (last is None or self.clock() - last > self.RELIST_SECONDS, last)

    def kind_stale(self, kind: str) -> tuple[bool, float | None]:
        """(the kind has not listed, or had no good read in the last relist window; the time of its last good read).
        A list, a watch event or a bookmark is a good read."""
        with self._lock:
            last = self.state[kind].last_good
        return (last is None or self.clock() - last > self.RELIST_SECONDS, last)

    def kind_error(self, kind: str) -> tuple[int | None, str | None]:
        """(HTTP status, message) of the kind's last failed list or watch, or (None, None). A successful list clears it,
        so a status here means the kind has not listed since it failed: the cached items are what it held before."""
        with self._lock:
            st = self.state[kind]
            return st.error_status, st.error

    def namespace(self, name: str) -> dict[str, Any] | None:
        """A namespace by name, falling back to a direct read when the cache has not listed yet."""
        if self.state["Namespace"].last_good is None:
            try:
                return self.client.get_object("Namespace", None, name)
            except ClusterUnreachable as exc:
                raise Problem(503, "cluster-unreachable", str(exc), extra={"retryAfter": 30}) from exc
        return self.get("Namespace", None, name)
