"""Kyverno's policy reports of one cluster, watched and kept small (#302; docs/02, "core/clients/policyreports.py").

Kyverno v1.20 writes one report per resource in `wgpolicyk8s.io/v1alpha2`: a ClusterPolicyReport for a Namespace and other
cluster-scoped objects, a PolicyReport in the namespace of a namespaced one (pkg/utils/report/new.go). Each result names a
policy, a rule, a verdict (pass, fail, warn, error, skip) and a message. The reports are read through the cluster's
cmapi-reader, by a list-then-watch beside the WatchCache of the cluster (docs/01, "Reads are live"): a request to the API
never calls a cluster.

What is kept. A report is reduced as it arrives (`reduce`): its namespace and resource, a counter for each (policy, verdict),
and a row for each fail, warn and error of a policy of the bundle of the cluster's environment, its message cut to 300
characters. Pass and skip are counters only. Past `max_rows` rows for the cluster, further rows are counted, not kept:
the counts stay exact, and the cluster's state says `capped` with the number of rows dropped.

The ValidatingPolicy objects of the cluster are watched too, kept as their name, digest, validationActions and readiness,
so the tab can tell the bundle that runs on the cluster from the one that cmapi renders (`cmapi.net/policy-digest`), and the
configured mode from the live actions.

Whether Kyverno is there at all comes from API discovery (`GET /apis/wgpolicyk8s.io/v1alpha2`), probed every PROBE_SECONDS:
discovery is open to every identity, while a list of a kind that is not served answers 403 to an identity without the
grant (measured on CRC, design A of #302). So 404 is `not-installed`, and a 403 on a list is `forbidden`.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from cmapi.core.clients.kube import ClusterUnreachable, KubeClient, KubeError, WatchCache
from cmapi.core.observability import log
from cmapi.core.policybundle import BundlePolicy
from cmapi.core.policygen import DIGEST

REPORTS_GROUP = "wgpolicyk8s.io/v1alpha2"
POLICIES_GROUP = "policies.kyverno.io/v1"
REPORT_KINDS = ("PolicyReport", "ClusterPolicyReport")
POLICY_KINDS = ("ValidatingPolicy",)
VERDICTS = ("pass", "fail", "warn", "error", "skip")
LISTED = ("fail", "warn", "error")
MESSAGE_MAX = 300
MAX_ROWS = 20_000            # 20,000 kept rows took 9.4 MiB in CPython (design B, M17)
CHUNK = 500


@dataclass(frozen=True, slots=True)
class Row:
    """One fail, warn or error of a policy of the bundle, on one resource."""
    policy: str
    rule: str | None
    result: str
    message: str
    at: str | None                    # the result's timestamp, ISO 8601 in UTC
    process: str | None               # `admission review` or `background scan` (properties.process)
    source: str | None


@dataclass(slots=True)
class Reduced:
    """What is kept of one report."""
    namespace: str | None             # the namespace the resource is in, or the Namespace itself; None for another cluster-scoped kind
    resource: tuple[str, str, str]    # (apiVersion, kind, name)
    counts: dict[tuple[str, str], int] = field(default_factory=dict)    # (policy, verdict) -> results
    rows: list[Row] = field(default_factory=list)
    dropped: int = 0                  # rows past the cluster's cap, counted and not kept


@dataclass(frozen=True, slots=True)
class LivePolicy:
    name: str
    digest: str | None
    generated: bool
    actions: tuple[str, ...]
    ready: bool | None


def _iso(ts: Any) -> str | None:
    """A result's timestamp ({seconds, nanos} in wgpolicyk8s.io/v1alpha2) as ISO 8601 in UTC."""
    if isinstance(ts, Mapping) and isinstance(ts.get("seconds"), (int, float)):
        return datetime.fromtimestamp(ts["seconds"], tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return None


def _scope(kind: str, report: Mapping[str, Any]) -> tuple[str | None, tuple[str, str, str]]:
    meta = report.get("metadata") or {}
    scope = report.get("scope") or {}
    resource = (str(scope.get("apiVersion") or ""), str(scope.get("kind") or ""), str(scope.get("name") or ""))
    if kind == "PolicyReport":
        return meta.get("namespace") or scope.get("namespace"), resource
    return (resource[2] or None) if resource[1] == "Namespace" else None, resource


def reduce(kind: str, report: Mapping[str, Any], bundle: Mapping[str, BundlePolicy]) -> Reduced:
    """A report reduced to its counters and the rows of the bundle's policies, before any cap."""
    namespace, resource = _scope(kind, report)
    out = Reduced(namespace, resource)
    for res in report.get("results") or []:
        if not isinstance(res, Mapping):
            continue
        policy, verdict = res.get("policy"), res.get("result")
        if not isinstance(policy, str) or verdict not in VERDICTS:
            continue
        out.counts[(policy, verdict)] = out.counts.get((policy, verdict), 0) + 1
        if verdict in LISTED and policy in bundle:
            props = res.get("properties") or {}
            rule = res.get("rule")
            out.rows.append(Row(policy, rule if isinstance(rule, str) and rule else None, verdict,
                                str(res.get("message") or "")[:MESSAGE_MAX], _iso(res.get("timestamp")),
                                props.get("process") if isinstance(props, Mapping) else None,
                                res.get("source") if isinstance(res.get("source"), str) else None))
    return out


def reduce_policy(obj: Mapping[str, Any]) -> LivePolicy:
    meta = obj.get("metadata") or {}
    ann = meta.get("annotations") or {}
    actions = (obj.get("spec") or {}).get("validationActions") or []
    ready = ((obj.get("status") or {}).get("conditionStatus") or {}).get("ready")
    return LivePolicy(str(meta.get("name") or ""), ann.get(DIGEST), ann.get("cmapi.net/generated") == "true",
                      tuple(str(a) for a in actions), ready if isinstance(ready, bool) else None)


@dataclass(frozen=True)
class Snapshot:
    """What one read of the cache sees, under its lock."""
    installed: bool | None                         # None: discovery has not answered yet
    probe_error: str | None
    listed: bool                                   # every report kind has been listed once
    forbidden: list[str]                           # the kinds whose last list answered 403
    stale: bool
    as_of: float | None
    reports: list[Reduced]
    policies: dict[str, LivePolicy] | None         # None: the policy kind is not served or not listed yet
    dropped: int


class ReportCache:
    """The reports and the ValidatingPolicies of one cluster, for the bundle of its environment."""

    PROBE_SECONDS = 300

    def __init__(self, client: KubeClient, bundle: Mapping[str, BundlePolicy], *, max_rows: int = MAX_ROWS,
                 clock: Callable[[], float] = time.time, chunk: int | None = CHUNK):
        self.client, self.bundle, self.max_rows, self.clock, self.chunk = client, dict(bundle), max_rows, clock, chunk
        self.installed: bool | None = None
        self.policies_served: bool | None = None
        self.probe_error: str | None = None
        self.watch: WatchCache | None = None
        self._lock = threading.RLock()
        self._held: dict[tuple[str, str], int] = {}       # (kind, key) -> rows kept for that report
        self._total = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- the cap, applied as each report arrives
    def _project(self, kind: str, obj: dict[str, Any]) -> Any:
        if kind in POLICY_KINDS:
            return reduce_policy(obj)
        out = reduce(kind, obj, self.bundle)
        key = (kind, WatchCache._key(obj))
        with self._lock:
            held = self._held.get(key, 0)
            room = max(0, self.max_rows - (self._total - held))
            if len(out.rows) > room:
                out.dropped, out.rows = len(out.rows) - room, out.rows[:room]
            self._total += len(out.rows) - held
            self._held[key] = len(out.rows)
        return out

    def _dropped(self, kind: str, key: str) -> None:
        with self._lock:
            self._total -= self._held.pop((kind, key), 0)

    # ---- discovery, then the watch
    def probe(self) -> None:
        """One discovery pass. Starts nothing: `sync` and `start` act on its answer."""
        try:
            installed = self.client.served(REPORTS_GROUP)
            policies = self.client.served(POLICIES_GROUP) if installed else False
            error = None
        except (ClusterUnreachable, KubeError) as exc:
            installed, policies, error = self.installed, self.policies_served, str(exc)[:200]
            log.warning("policy_reports_probe", cluster_id=self.client.cluster_id, error=error)
        with self._lock:
            self.installed, self.policies_served, self.probe_error = installed, policies, error

    def _kinds(self) -> tuple[str, ...]:
        return REPORT_KINDS + (POLICY_KINDS if self.policies_served else ())

    def _ensure_watch(self) -> WatchCache:
        kinds = self._kinds()
        if self.watch is None or self.watch.kinds != kinds:
            if self.watch is not None:
                self.watch.stop()
            with self._lock:
                self._held, self._total = {}, 0
            self.watch = WatchCache(self.client, kinds, self.clock, project=self._project, dropped=self._dropped,
                                    chunk=self.chunk)
        return self.watch

    def sync(self) -> None:
        """Discovery and one list of each kind, in the caller's thread: what the tests and the first read use."""
        self.probe()
        if not self.installed:
            self._drop_watch()
            return
        watch = self._ensure_watch()
        for kind in watch.kinds:
            try:
                watch._list(kind)
            except (ClusterUnreachable, KubeError, ValueError) as exc:
                with watch._lock:
                    watch.state[kind].error = str(exc)[:200]
                    watch.state[kind].error_status = exc.status if isinstance(exc, KubeError) else None

    def _drop_watch(self) -> None:
        if self.watch is not None:
            self.watch.stop()
            self.watch = None
        with self._lock:
            self._held, self._total = {}, 0

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.probe()
            if self.installed:
                if self.watch is None or self.watch.kinds != self._kinds():
                    self._ensure_watch().start()
            elif self.installed is False:
                self._drop_watch()
            self._stop.wait(self.PROBE_SECONDS)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name=f"reports-{self.client.cluster_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.watch is not None:
            self.watch.stop()

    # ---- reads
    def snapshot(self) -> Snapshot:
        with self._lock:
            installed, probe_error, watch = self.installed, self.probe_error, self.watch
        if not installed or watch is None:
            return Snapshot(installed, probe_error, False, [], False, None, [], None, 0)
        with watch._lock:
            states = {k: watch.state[k] for k in watch.kinds}
            forbidden = [k for k, st in states.items() if st.error_status == 403]
            listed = all(states[k].last_good is not None for k in REPORT_KINDS)
            reports = [v for k in REPORT_KINDS for v in states[k].items.values()]
            policies = None
            if "ValidatingPolicy" in states and states["ValidatingPolicy"].last_good is not None:
                policies = {p.name: p for p in states["ValidatingPolicy"].items.values()}
        stale, as_of = watch.stale()
        return Snapshot(installed, probe_error, listed, forbidden, stale and listed, as_of, reports, policies,
                        sum(r.dropped for r in reports))
