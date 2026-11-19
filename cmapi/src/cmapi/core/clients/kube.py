"""The Kubernetes API client and the watch cache (docs/01, "Reads are live").

KubeClient speaks to one cluster's API over HTTPS with that cluster's imported token, verified in the cluster's trust mode
(core/clients/trust.py, #434).
Every call is counted in cmapi_cluster_api_calls_total. It is used for reads through cmapi-reader
and, by the worker's delivery job only, for server-side apply with the deliverer identity.

WatchCache keeps namespaces, ResourceQuotas and LimitRanges of one cluster current from a
list-then-watch loop per kind, in a daemon thread, with a full relist every 30 minutes and a
reconnect with backoff on any error. A read never calls the cluster; a cluster that cannot be
reached keeps its rows, marked stale with the time of the last good read.
"""
from __future__ import annotations

import json
import ssl
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping

import httpx

from cmapi.core.clients.redact import redact, secret_forms
from cmapi.core.clients.trust import Trust, file_context, trusted_context
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


def list_items(body: Mapping[str, Any], path: str, status: int) -> list[dict[str, Any]]:
    """The items of a list answer, or BadResponse (#421; docs/02 "Client rules": a 200 response without an items field is
    never read as an empty list). Every Kubernetes list type has `items` (API conventions, "Lists and Simple kinds"; the API
    server tests for it in an empty list since kubernetes#126286), so an answer without it is not a list: a Status, or a
    proxy's own JSON. Read as an empty list, it would retire every imported cluster or drop every cached object.

    `items: null` is an empty list: Go writes a nil slice as null, and the API's own guidance is that null and [] mean the
    same in a list field (kubernetes#43422)."""
    if "items" not in body:
        raise BadResponse(path, status, "no items field: not a list")
    items = body["items"]
    if items is None:
        return []
    if not isinstance(items, list):
        raise BadResponse(path, status, f"items is a JSON {_JSON_TYPES.get(type(items), 'object')}, not an array")
    if not all(isinstance(item, dict) for item in items):
        raise BadResponse(path, status, "an item that is not an object")
    return items


class KubeClient:
    def __init__(self, cluster_id: str, api_url: str, token: str, trust: Trust | str | None = None, *,
                 insecure: bool = False, timeout: float = 10.0):
        """`trust` is the cluster's mode from its import Secret (core/clients/trust.py), the path of a PEM file that alone is
        trusted (a ServiceAccount's ca.crt), or None: the trusted mode, the system store and CMAPI_TRUSTED_CA_FILE. Never httpx's
        `verify=True`, which is certifi or whatever SSL_CERT_FILE names (#434). The context is built here, so a caData that is no
        certificate raises ssl.SSLError from the constructor (#419)."""
        self.cluster_id, self.api_url = cluster_id, api_url.rstrip("/")
        self._forms = secret_forms(token)            # what `redact` removes from every error this client builds (#420)
        server_name = trust.server_name if isinstance(trust, Trust) else None
        verify: ssl.SSLContext | bool
        if insecure or (isinstance(trust, Trust) and trust.source == "insecure"):
            verify = False
        elif isinstance(trust, Trust):
            verify = trust.verify()
        elif trust:
            verify = file_context(trust)
        else:
            verify = trusted_context()
        hooks = {"request": [self._name_server(server_name)]} if server_name else {}
        self._client = httpx.Client(base_url=self.api_url, verify=verify, timeout=timeout, event_hooks=hooks,
                                    headers={"Authorization": f"Bearer {token}"})

    @staticmethod
    def _name_server(name: str) -> Callable[[httpx.Request], None]:
        """kubeconfig's tls-server-name: the name sent in SNI and checked against the certificate, for a cluster reached by an
        address its certificate does not name. It is RFC 9525's reference identity, from the import and never from the server;
        httpcore takes the request extension `sni_hostname` as the TLS server_hostname, on every request and stream of a direct
        connection. Its HTTP-proxy tunnel ignores the extension, so a verifying mode also carries the name in its SSLContext
        (trust._NamedContext); the hook remains for the insecure mode's SNI."""
        def hook(request: httpx.Request) -> None:
            request.extensions["sni_hostname"] = name
        return hook

    def close(self) -> None:
        self._client.close()

    def redact(self, text: str) -> str:
        """`text` without this client's token in any form; the whole text, before anything cuts it (#420)."""
        return redact(text, self._forms)

    def _error(self, status: int, path: str, body: str) -> KubeError:
        return KubeError(status, path, self.redact(body))

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            r = self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            CLUSTER_CALLS.labels(self.cluster_id, "error").inc()
            raise ClusterUnreachable(self.redact(f"{self.cluster_id}: {type(exc).__name__}: {exc}")) from exc
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
            raise self._error(r.status_code, path, r.text)
        return self._object(r, path)

    def version(self) -> str:
        r = self._request("GET", "/version")
        if r.status_code >= 400:
            raise self._error(r.status_code, "/version", r.text)
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
        raise self._error(r.status_code, "whoami", r.text)

    def served(self, group_version: str) -> bool:
        """Whether the API server serves a group version, from discovery (GET /apis/<group>/<version>).

        Discovery is open to every authenticated identity (system:discovery), so it tells "not installed" (404) from "not
        granted": a list of a kind that the API server does not serve answers 403 to an identity without the grant, because
        authorization runs before the 404 (measured on CRC, #302 design A)."""
        r = self._request("GET", f"/apis/{group_version}")
        if r.status_code == 404:
            return False
        if r.status_code >= 400:
            raise self._error(r.status_code, f"/apis/{group_version}", r.text)
        return True

    def list(self, kind: str, namespace: str | None = None, label_selector: str | None = None,
             resource_version: str | None = None, *, limit: int | None = None, continue_: str | None = None) -> dict[str, Any]:
        """One list call. `limit` and `continue_` page a large collection (API concepts, "Retrieving large results sets in
        chunks"); without them the API server answers in one response. The answer always has `items`, a list of objects:
        anything else is BadResponse (`list_items`, #421)."""
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
        r = self._request("GET", path, params=params)
        if r.status_code == 404:
            raise KubeError(404, path, "list not found")
        if r.status_code >= 400:
            raise self._error(r.status_code, path, r.text)
        out = self._object(r, path)
        out["items"] = list_items(out, path, r.status_code)
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
            raise ClusterUnreachable(self.redact(f"{self.cluster_id}: watch {kind}: {exc}")) from exc

    # ---- the one write path, used only by the delivery job with the deliverer identity
    def apply(self, doc: Mapping[str, Any], field_manager: str = APPLY_FIELD_MANAGER) -> dict[str, Any]:
        kind, meta = doc["kind"], doc["metadata"]
        path = resource_path(kind, meta.get("namespace"))
        r = self._request("PATCH", f"{path}/{meta['name']}", params={"fieldManager": field_manager, "force": "true"},
                          content=json.dumps(doc), headers={"Content-Type": "application/apply-patch+yaml"})
        if r.status_code >= 400:
            raise self._error(r.status_code, path, r.text)
        return self._object(r, path)

    def delete(self, kind: str, namespace: str | None, name: str) -> None:
        path = resource_path(kind, namespace)
        r = self._request("DELETE", f"{path}/{name}")
        if r.status_code not in (200, 202, 404):
            raise self._error(r.status_code, path, r.text)


class KubeError(RuntimeError):
    """An HTTP error answer. `body` is cut to 300 characters here, so a KubeClient redacts it first (`_error`, #420)."""

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
    def _key(obj: Mapping[str, Any], kind: str = "object") -> str:
        """`<namespace>/<name>` of a listed or watched object, or BadResponse: an object without metadata.name is no object
        of the kind, and its KeyError or TypeError would end the kind's thread (#421)."""
        m = obj.get("metadata")
        if not isinstance(m, Mapping) or not isinstance(m.get("name"), str):
            raise BadResponse(kind, 200, "an object without metadata.name")
        return f"{m.get('namespace', '')}/{m['name']}"

    def _value(self, kind: str, obj: dict[str, Any]) -> Any:
        return self.project(kind, obj) if self.project else obj

    def _admitted(self, kind: str, key: str, value: Any) -> Any:
        return self.admit(kind, key, value) if self.admit else value

    def _fetch(self, kind: str) -> tuple[list[tuple[str, Any]], str]:
        """(key, projected value) of every object of the kind, and the list's resourceVersion, in one call or in chunks.
        Each page is projected before the next is asked for, so its raw objects are released page by page.

        `items` is read without a default: the client's list call has refused an answer without it (#421), and one read
        here as empty would drop every cached object. A list without a resourceVersion to watch from is BadResponse, a
        ValueError that `_loop` retries, never a KeyError that would end the kind's thread."""
        if not self.chunk:
            out = self.client.list(kind)
            return [(self._key(o, kind), self._value(kind, o)) for o in out["items"]], self._resource_version(kind, out)
        values: list[tuple[str, Any]] = []
        token: str | None = None
        while True:
            out = self.client.list(kind, limit=self.chunk, continue_=token)
            values.extend((self._key(o, kind), self._value(kind, o)) for o in out["items"])
            token = self._continue(kind, out)
            if token is None:
                return values, self._resource_version(kind, out)
            del out                         # the page's raw objects go before the next page arrives

    @staticmethod
    def _continue(kind: str, out: Mapping[str, Any]) -> str | None:
        """The page's continue token, None on the last page, or BadResponse: a metadata or a token of another JSON type is
        no list page, and reading it raised AttributeError, which ended the kind's thread (#421)."""
        meta = out.get("metadata")
        if meta is None:
            return None                     # the last page; `_resource_version` then refuses it for want of one
        if not isinstance(meta, Mapping):
            raise BadResponse(kind, 200, f"metadata is a JSON {_JSON_TYPES.get(type(meta), 'value')}, not an object")
        token = meta.get("continue")
        if token is None or token == "":
            return None
        if not isinstance(token, str):
            raise BadResponse(kind, 200, f"metadata.continue is a JSON {_JSON_TYPES.get(type(token), 'value')}, not a string")
        return token

    @staticmethod
    def _resource_version(kind: str, out: Mapping[str, Any]) -> str:
        meta = out.get("metadata")
        rv = meta.get("resourceVersion") if isinstance(meta, Mapping) else None
        if not isinstance(rv, str) or not rv:
            raise BadResponse(kind, 200, "no metadata.resourceVersion")
        return rv

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
        if not isinstance(ev, Mapping) or not isinstance(ev.get("object", {}), Mapping):
            raise BadResponse(kind, 200, "a watch event that is not an object with an object")
        t, obj = ev.get("type"), ev.get("object", {})
        if t == "ERROR":
            # The client redacts before the cut (#420); a test's fake client, which holds no token, has no `redact`.
            text = json.dumps(obj)
            raise KubeError(410, kind, (getattr(self.client, "redact", None) or str)(text)[:200])
        with self._lock:
            st = self.state[kind]
            meta = obj.get("metadata", {})
            if not isinstance(meta, Mapping):
                raise BadResponse(kind, 200, "a watch event's object without metadata")
            st.resource_version = meta.get("resourceVersion", st.resource_version)
            st.last_good = self.clock()
            if t in ("ADDED", "MODIFIED"):
                key = self._key(obj, kind)
                st.items[key] = self._admitted(kind, key, self._value(kind, obj))
            elif t == "DELETED":
                key = self._key(obj, kind)
                if st.items.pop(key, None) is not None and self.dropped:
                    self.dropped(kind, key)

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
            except Exception as exc:                    # noqa: BLE001 - the kind's thread never ends (#421)
                if isinstance(exc, (ClusterUnreachable, KubeError, ValueError)):
                    text = str(exc)[:200]
                    log.warning("watch_cache", cluster_id=self.client.cluster_id, kind=kind, error=text, retry_in=backoff)
                else:
                    # The last net, as ClusterRegistry.refresh has one (#419): what the checks did not foresee, such as a
                    # projection of a malformed object. The cache keeps its last good list and goes stale as after any
                    # failed list; the log has the trace. The client redacts before the cut (#420).
                    text = (getattr(self.client, "redact", None) or str)(f"{type(exc).__name__}: {exc}")[:200]
                    log.exception("watch_cache_failed", cluster_id=self.client.cluster_id, kind=kind, error=text,
                                  retry_in=backoff)
                with self._lock:
                    self.state[kind].error = text
                    self.state[kind].error_status = exc.status if isinstance(exc, KubeError) else None
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
