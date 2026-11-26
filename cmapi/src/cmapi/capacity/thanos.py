"""The MetricsSource of each cluster's Thanos Querier (core/ports.py; docs/02, "Capacity plugin", #310).

    "cmapi-capacity reaches each cluster's Thanos Querier at the thanos-querier Route in openshift-monitoring, or at the
    optional thanosUrl override in clusters.yaml, with the cmapi-reader token bound to cluster-monitoring-view."

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
from typing import Any

from cmapi.capacity.usage import MetricsUnavailable
from cmapi.core.clients.kube import BadResponse, ClusterUnreachable, KubeError
from cmapi.core.errors import Problem
from cmapi.core.registry import ClusterRegistry

ROUTE_PATH = "/apis/route.openshift.io/v1/namespaces/openshift-monitoring/routes/thanos-querier"
LIVE_TIMEOUT_SECONDS = 10.0          # docs/02: "A quota change on an existing namespace makes one live query, with a 10-second timeout"
SWEEP_TIMEOUT_SECONDS = 120.0        # docs/03, "Running the sweep": "a 120-second timeout per query"


class ThanosQuerier:
    def __init__(self, registry: ClusterRegistry, timeout: float = LIVE_TIMEOUT_SECONDS):
        self.registry, self.timeout = registry, timeout
        self._routes: dict[str, str] = {}

    def _base_url(self, cluster_id: str, policy_url: str | None, client: Any) -> str:
        if policy_url:
            return policy_url.rstrip("/")
        if cluster_id in self._routes:
            return self._routes[cluster_id]
        try:
            route = client.get(ROUTE_PATH)
        except (ClusterUnreachable, KubeError, BadResponse) as exc:
            raise MetricsUnavailable(f"{cluster_id}: the thanos-querier Route could not be read: {str(exc)[:200]}") from exc
        host = ((route or {}).get("spec") or {}).get("host")
        if not isinstance(host, str) or not host:
            raise MetricsUnavailable(f"{cluster_id}: openshift-monitoring has no thanos-querier Route with a host")
        self._routes[cluster_id] = f"https://{host}"
        return self._routes[cluster_id]

    def query(self, cluster_id: str, promql: str, at: datetime | None = None) -> list[dict[str, Any]]:
        """The `result` of an instant vector query. MetricsUnavailable on anything that is not a clean answer."""
        try:
            st = self.registry.get(cluster_id)
        except Problem as exc:
            raise MetricsUnavailable(f"{cluster_id}: {exc.detail}") from exc
        client = st.client                  # once: the registry clears it when the cluster drops (#402)
        if client is None:
            raise MetricsUnavailable(f"{cluster_id} is {st.status}: no client for its Thanos Querier")
        base = self._base_url(cluster_id, st.policy.thanos_url if st.policy else None, client)
        params: dict[str, Any] = {"query": promql, "partial_response": "false", "dedup": "true"}
        if at is not None:
            params["time"] = f"{at.timestamp():.3f}"
        try:
            r = client.monitoring_get(f"{base}/api/v1/query", params, self.timeout)
        except ClusterUnreachable as exc:
            raise MetricsUnavailable(str(exc)[:300]) from exc
        try:
            body = r.json()
        except ValueError as exc:
            raise MetricsUnavailable(f"{cluster_id}: the Thanos Querier answered {r.status_code} with no JSON") from exc
        return parse_answer(cluster_id, r.status_code, body)


def parse_answer(cluster_id: str, status: int, body: Any) -> list[dict[str, Any]]:
    """The vector of a Prometheus HTTP API answer, or MetricsUnavailable: an error, a warning, or a body of another shape."""
    if not isinstance(body, dict):
        raise MetricsUnavailable(f"{cluster_id}: the Thanos Querier answered {status} with no JSON object")
    if body.get("status") != "success":
        raise MetricsUnavailable(f"{cluster_id}: the Thanos Querier answered {status}: {body.get('errorType')}: "
                                 f"{str(body.get('error'))[:200]}")
    if body.get("warnings"):
        raise MetricsUnavailable(f"{cluster_id}: the Thanos Querier warned: {str(body['warnings'])[:200]}")
    data = body.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector" or not isinstance(data.get("result"), list):
        raise MetricsUnavailable(f"{cluster_id}: the Thanos Querier answered no instant vector")
    return data["result"]
