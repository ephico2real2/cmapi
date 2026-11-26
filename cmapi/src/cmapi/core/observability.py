"""Metrics and logs for every component (docs/01, Observability).

- structlog JSON to stdout with request_id, caller, cluster_id and plugin; never a token.
- Prometheus metrics with the cmapi_ prefix and low-cardinality labels, served on a separate
  metrics port by prometheus_client's own HTTP server, so the Route never exposes them.
"""
from __future__ import annotations

import logging
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Iterator

import structlog
from fastapi import FastAPI, Request
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cmapi import __version__

BUILD_INFO = Gauge("cmapi_build_info", "Which instance and release a series came from", ["instance", "version", "component"])
HTTP_REQUESTS = Counter("cmapi_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_DURATION = Histogram("cmapi_http_request_duration_seconds", "HTTP request duration", ["method", "route"],
                          buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
CHANGE_REQUESTS = Counter("cmapi_change_requests_total", "Change requests by outcome", ["plugin", "action", "environment", "status"])
VALIDATION_FAILURES = Counter("cmapi_validation_failures_total", "Plans refused by validation", ["source"])
# #302: each refusal of cmapi's that the Policies tab lists, by problem code, and whether it was a dry run (a dry run is
# counted here only: the portal's forms dry-run as a person types, so storing them would store drafts).
PLAN_REFUSALS = Counter("cmapi_plan_refusals_total", "Plans that cmapi refused before Git", ["code", "dry_run"])
REJECTIONS_UNRECORDED = Counter("cmapi_policy_rejections_unrecorded_total",
                                "Refusals that could not be stored in policy_rejections; the refusal itself was answered", ["stage"])
AUTHZ_DENIED = Counter("cmapi_authz_denied_total", "Permission refusals", ["permission"])
# #689: each 429 rate-limited, by the bucket class that refused it (read, write, place, suggest, export or team); never the caller.
RATE_LIMITED = Counter("cmapi_rate_limited_total", "Calls refused 429 by a rate limit", ["limit"])
ENV_NOT_SERVED = Counter("cmapi_environment_not_served_total", "Requests for another instance's environment", ["environment"])
PLUGIN_DISABLED = Counter("cmapi_plugin_disabled_total", "Writes refused because plugins.yaml disables the plugin in the environment",
                          ["plugin", "environment"])
# The Git layer and the platform adapters (#286; the fields and metrics of Fable's design, 6.2). One count per operation
# (core/git/oplog.py): op is clone, fetch, ls_remote, worktree, commit, push, merge_check, branch_delete, cleanup, and the host
# calls pr_open, pr_find, pr_state, pr_list, merge, pr_comment, pr_close, status_read, status_write; result is ok, retry,
# refused, skipped or error. No metric carries a request ID.
GIT_OPS = Counter("cmapi_git_operations_total", "Git and Git host operations", ["op", "result"])
GIT_DURATION = Histogram("cmapi_git_operation_seconds", "Git and Git host operation duration", ["op"])
PLATFORM_REQUESTS = Counter("cmapi_git_platform_requests_total", "Git host API calls", ["platform", "op", "code"])
MERGE_CONFLICTS = Counter("cmapi_git_merge_conflicts_total", "Merge checks that refused: a conflict or a folder that moved", ["caller"])
REQUESTS_IN_STATE = Gauge("cmapi_requests_in_state", "Requests in a state the alerts watch", ["state"])
GIT_WORKDIR_BYTES = Gauge("cmapi_git_workdir_bytes", "Size of this pod's Git workdir")
GIT_WORKTREES = Gauge("cmapi_git_worktrees", "Request worktrees in this pod's Git workdir")
SWEEPER_RUNS = Counter("cmapi_git_sweeper_runs_total", "Passes of the Git workdir sweeper", ["result"])
GIT_ORPHANS = Counter("cmapi_git_orphans_total", "Branches and PRs that git_reconcile or a job found and acted on", ["kind", "action"])
REQUESTS_STALLED = Gauge("cmapi_requests_stalled", "pr_open requests with no PR and no job, older than syncTimeout")
JOBS_PENDING = Gauge("cmapi_jobs_pending", "Jobs waiting to run", ["kind"])
JOB_FAILURES = Counter("cmapi_job_failures_total", "Jobs that raised", ["kind"])
LEAD_TIME = Histogram("cmapi_change_lead_time_seconds", "Submit to synced", ["plugin", "action", "approval"],
                      buckets=(30, 60, 120, 300, 600, 1800, 3600, 14400, 86400))
APPROVAL_WAIT = Histogram("cmapi_approval_wait_seconds", "pending_approval to approved", ["rule"],
                          buckets=(60, 300, 900, 3600, 14400, 28800, 86400, 172800))
AUTO_APPROVALS = Counter("cmapi_auto_approvals_total", "Auto-approved requests", ["policy", "environment"])
AUTO_FALLBACKS = Counter("cmapi_auto_approval_fallbacks_total", "Matching policies stopped by a guard", ["guard"])
AUTO_PAUSED = Gauge("cmapi_auto_approval_paused", "1 when the kill switch is on")
POLICY_MODE = Gauge("cmapi_policy_mode", "1 for the policy mode of each served environment (instance.yaml policy, #213)",
                    ["environment", "mode"])
CLUSTER_STATUS = Gauge("cmapi_cluster_status", "1 for the cluster's current import status", ["cluster_id", "status"])
CLUSTER_TOKEN_EXPIRY = Gauge("cmapi_cluster_token_expiry_seconds", "Seconds remaining until the annotated import token expiry",
                             ["cluster_id"])
CLUSTER_TOKEN_RENEWALS = Counter("cmapi_cluster_token_renewals_total", "Import token renewal attempts", ["cluster_id", "outcome"])
CLUSTER_TOKEN_LIFETIME = Gauge("cmapi_cluster_token_lifetime_seconds", "Issued reader token lifetime", ["cluster_id"])
CLUSTER_TLS_INSECURE = Gauge("cmapi_cluster_tls_insecure", "1 while the cluster is read with TLS verification off: its import "
                             "Secret says insecure and instance.clusterTLS allows its environment (#434)", ["cluster_id"])
CLUSTER_CALLS = Counter("cmapi_cluster_api_calls_total", "Cluster API calls", ["cluster_id", "result"])
OPEN_REQUEST_AGE = Gauge("cmapi_open_change_requests_oldest_age_seconds", "Age of the oldest open request", ["status", "environment"])
CONFIG_INFO = Gauge("cmapi_config_info", "Hash of the loaded configuration", ["hash"])
# cmapi_namespaces is a collector over the watch caches (core/kpi.py). cmapi_sync_drift_total is not declared: no code sees an
# OutOfSync state with no open request yet, and a counter with no sample reads as "no drift" (#172, docs/17 "Drift events").


_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


def set_token_expiry(cluster_id: str, expiry: datetime | None, lifetime: int | None = None) -> None:
    if lifetime is None:
        CLUSTER_TOKEN_LIFETIME.remove(cluster_id)
    else:
        CLUSTER_TOKEN_LIFETIME.labels(cluster_id).set(lifetime)
    if expiry is None:
        CLUSTER_TOKEN_EXPIRY.remove(cluster_id)
    else:
        deadline = expiry.timestamp()
        CLUSTER_TOKEN_EXPIRY.labels(cluster_id).set_function(lambda: deadline - time.time())


_CLUSTER_HTTP = ContextVar("cmapi_cluster_http", default=False)


@contextmanager
def cluster_http_call() -> Iterator[None]:
    """Mark the transport call whose URL comes from an import Secret."""
    token = _CLUSTER_HTTP.set(True)
    try:
        yield
    finally:
        _CLUSTER_HTTP.reset(token)


def _public_log_record(record: logging.LogRecord) -> bool:
    return not (_CLUSTER_HTTP.get() and record.name.partition(".")[0] in {"httpx", "httpcore"})


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    for handler in logging.getLogger().handlers:
        handler.addFilter(_public_log_record)
    structlog.configure(
        processors=[structlog.contextvars.merge_contextvars, structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso", utc=True),
                    structlog.processors.StackInfoRenderer(), structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout), cache_logger_on_first_use=True)


log = structlog.get_logger("cmapi")


def start_metrics(port: int, instance: str, component: str) -> None:
    BUILD_INFO.labels(instance, __version__, component).set(1)
    start_http_server(port)


class MetricsAndRequestIdMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        rid = Headers(scope=scope).get("x-request-id") or uuid.uuid4().hex[:16]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        started = time.perf_counter()
        method = request.method if request.method in _METHODS else "OTHER"
        status: int | None = None

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-Id"] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except ClientDisconnect:
            raise
        except Exception:
            if status is None:
                status = 500
            raise
        finally:
            # Cancellation/disconnect before headers has no HTTP status to count.
            # For a stream/background failure after headers, count the status actually sent.
            if status is not None:
                # The template without a convertor ("{request_id}", not "{request_id:request_id}"): the document's path.
                route = getattr(scope.get("route"), "path_format", "unmatched")
                HTTP_REQUESTS.labels(method, route, str(status)).inc()
                HTTP_DURATION.labels(method, route).observe(time.perf_counter() - started)
                caller = getattr(request.state, "caller", None)
                log.info("http", method=request.method, route=route, status=status,
                         caller_sub=getattr(caller, "sub", None), client=getattr(caller, "client_id", None),
                         ms=round((time.perf_counter() - started) * 1000, 1))
            structlog.contextvars.clear_contextvars()


def instrument(app: FastAPI) -> None:
    app.add_middleware(MetricsAndRequestIdMiddleware)
