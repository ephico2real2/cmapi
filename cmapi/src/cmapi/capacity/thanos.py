"""The MetricsSource of each cluster's Thanos Querier (core/ports.py; docs/02, "Capacity plugin", #310).

    "cmapi-capacity reaches each cluster's Thanos Querier at the thanos-querier Route in openshift-monitoring, or at the
    optional thanosUrl override in clusters.yaml, with the cmapi-reader token and the reader's own grants in
    openshift-monitoring from the cluster baseline (the platform's Role cluster-monitoring-metrics-api and get on the Route,
    #724)."

A cluster whose import check found the reader without those grants (core/registry.py, `usage_findings`) is not queried.

One instant query per call, GET /api/v1/query of the Prometheus HTTP API (https://prometheus.io/docs/prometheus/latest/
querying/api/, read 2026-11-25: "GET /api/v1/query", `query`, `time` "Evaluation timestamp"), with Thanos's
`partial_response=false` and `dedup=true` (https://thanos.io/tip/components/query.md/, read 2026-11-25: partial response
"If true, then all storeAPIs that will be unavailable ... will not cause query to fail"; dedup "controls if query results
should be deduplicated using the replica labels"). docs/03, "Accuracy rules": "Missing is not zero. Queries use
partial_response=false with deduplication on. A failed or warned query gives ... insufficient-data ... never a zero." So an
answer with `warnings` is a failure here, like an error.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from weakref import WeakKeyDictionary

from cmapi.capacity.usage import LIVE_TIMEOUT_SECONDS, MetricsUnavailable
from cmapi.core.clients.kube import BadResponse, ClusterUnreachable, KubeError
from cmapi.core.errors import Problem
from cmapi.core.registry import ClusterRegistry

ROUTE_PATH = "/apis/route.openshift.io/v1/namespaces/openshift-monitoring/routes/thanos-querier"


class ThanosQuerier:
    def __init__(self, registry: ClusterRegistry, timeout: float = LIVE_TIMEOUT_SECONDS):
        self.registry, self.timeout = registry, timeout
        # By client, not by cluster ID: a replaced import (a new client) reads the Route again, and a dropped one is forgotten.
        self._routes: WeakKeyDictionary[Any, str] = WeakKeyDictionary()

    def _base_url(self, cluster_id: str, policy_url: str | None, client: Any) -> str:
        if policy_url:
            return policy_url.rstrip("/")
        cached = self._routes.get(client)
        if cached:
            return cached
        try:
            route = client.get(ROUTE_PATH)
        except (ClusterUnreachable, KubeError, BadResponse) as exc:
            # KubeClient redacts its token from each of these before it is raised (#420).
            raise MetricsUnavailable(f"{cluster_id}: the thanos-querier Route could not be read: {str(exc)[:200]}") from exc
        spec = (route or {}).get("spec")
        host = spec.get("host") if isinstance(spec, dict) else None
        if not isinstance(host, str) or not host:
            raise MetricsUnavailable(f"{cluster_id}: openshift-monitoring has no thanos-querier Route with a host")
        self._routes[client] = f"https://{host}"
        return self._routes[client]

    def query(self, cluster_id: str, promql: str, at: datetime | None = None) -> list[dict[str, Any]]:
        """The `result` of an instant vector query. MetricsUnavailable on anything that is not a clean answer."""
        try:
            st = self.registry.get(cluster_id)
        except Problem as exc:
            raise MetricsUnavailable(f"{cluster_id}: {exc.detail}") from exc
        client = st.client                  # once: the registry clears it when the cluster drops (#402)
        if client is None:
            raise MetricsUnavailable(f"{cluster_id} is {st.status}: no client for its Thanos Querier")
        if missing := st.usage_findings:
            # The import check found the reader without its own grants (#724): an answer allowed only by another grant, such
            # as one to every user, is not used.
            raise MetricsUnavailable(f"{cluster_id}: {'; '.join(missing)}"[:300])
        base = self._base_url(cluster_id, st.policy.thanos_url if st.policy else None, client)
        # `timeout`: the Querier stops evaluating when the caller has stopped waiting (Prometheus HTTP API, "Evaluation timeout").
        params: dict[str, Any] = {"query": promql, "partial_response": "false", "dedup": "true",
                                  "timeout": f"{self.timeout:g}s"}
        if at is not None:
            params["time"] = f"{at.timestamp():.3f}"
        try:
            r = client.monitoring_get(f"{base}/api/v1/query", params, self.timeout)
        except ClusterUnreachable as exc:
            raise MetricsUnavailable(str(exc)[:300]) from exc
        try:
            body = r.json()
        except (ValueError, RecursionError) as exc:     # JSONDecodeError, UnicodeDecodeError; a body nested past the limit
            raise MetricsUnavailable(f"{cluster_id}: the Thanos Querier answered {r.status_code} with no JSON") from exc
        return parse_answer(cluster_id, r.status_code, body, client.redact)


def parse_answer(cluster_id: str, status: int, body: Any, redact: Callable[[str], str] = lambda text: text) -> list[dict[str, Any]]:
    """The vector of a Prometheus HTTP API answer, or MetricsUnavailable: an error, a warning, or a body of another shape.

    The Querier's own error and warnings are kept, because they say why (a query timeout, a store that did not answer). They
    are text the server returns, so `redact` (the client's, #420) takes the token out of the whole text before it is cut: it
    reaches the plan, analysis_sweeps.detail and the worker's log. The Prometheus HTTP API (read 2026-11-25): "Every successful
    API request returns a 2xx status code", and `warnings` is a key of the envelope."""
    def said(text: str) -> str:
        return redact(f"{cluster_id}: the Thanos Querier {text}")[:300]

    if not isinstance(body, dict):
        raise MetricsUnavailable(f"{cluster_id}: the Thanos Querier answered {status} with no JSON object")
    if not 200 <= status < 300 or body.get("status") != "success":
        raise MetricsUnavailable(said(f"answered {status}: {body.get('errorType')}: {body.get('error')}"))
    if body.get("warnings"):
        raise MetricsUnavailable(said(f"warned: {body['warnings']}"))
    data = body.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector" or not isinstance(data.get("result"), list):
        raise MetricsUnavailable(f"{cluster_id}: the Thanos Querier answered no instant vector")
    for series in data["result"]:
        # A member of another shape is a broken answer, never a missing sample: it fails the read, as an error does.
        value = series.get("value") if isinstance(series, dict) else None
        if (not isinstance(value, list) or len(value) != 2 or not isinstance(value[1], str)
                or not isinstance(series.get("metric"), dict)):
            raise MetricsUnavailable(f"{cluster_id}: the Thanos Querier answered a vector member of another shape")
    return data["result"]
