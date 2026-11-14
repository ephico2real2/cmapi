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
from typing import Any

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
AUTHZ_DENIED = Counter("cmapi_authz_denied_total", "Permission refusals", ["permission"])
ENV_NOT_SERVED = Counter("cmapi_environment_not_served_total", "Requests for another instance's environment", ["environment"])
PLUGIN_DISABLED = Counter("cmapi_plugin_disabled_total", "Writes refused because plugins.yaml disables the plugin in the environment",
                          ["plugin", "environment"])
GIT_OPS = Counter("cmapi_git_operations_total", "Git host calls", ["operation", "result"])
GIT_DURATION = Histogram("cmapi_git_operation_duration_seconds", "Git host call duration", ["operation"])
JOBS_PENDING = Gauge("cmapi_jobs_pending", "Jobs waiting to run", ["kind"])
JOB_FAILURES = Counter("cmapi_job_failures_total", "Jobs that raised", ["kind"])
LEAD_TIME = Histogram("cmapi_change_lead_time_seconds", "Submit to synced", ["plugin", "action", "approval"],
                      buckets=(30, 60, 120, 300, 600, 1800, 3600, 14400, 86400))
APPROVAL_WAIT = Histogram("cmapi_approval_wait_seconds", "pending_approval to approved", ["rule"],
                          buckets=(60, 300, 900, 3600, 14400, 28800, 86400, 172800))
AUTO_APPROVALS = Counter("cmapi_auto_approvals_total", "Auto-approved requests", ["policy", "environment"])
AUTO_FALLBACKS = Counter("cmapi_auto_approval_fallbacks_total", "Matching policies stopped by a guard", ["guard"])
AUTO_PAUSED = Gauge("cmapi_auto_approval_paused", "1 when the kill switch is on")
CLUSTER_STATUS = Gauge("cmapi_cluster_status", "1 for the cluster's current import status", ["cluster_id", "status"])
CLUSTER_CALLS = Counter("cmapi_cluster_api_calls_total", "Cluster API calls", ["cluster_id", "result"])
OPEN_REQUEST_AGE = Gauge("cmapi_open_change_requests_oldest_age_seconds", "Age of the oldest open request", ["status", "environment"])
CONFIG_INFO = Gauge("cmapi_config_info", "Hash of the loaded configuration", ["hash"])
# cmapi_namespaces is a collector over the watch caches (core/kpi.py). cmapi_sync_drift_total is not declared: no code sees an
# OutOfSync state with no open request yet, and a counter with no sample reads as "no drift" (#172, docs/17 "Drift events").


_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
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
                route = getattr(scope.get("route"), "path", "unmatched")
                HTTP_REQUESTS.labels(method, route, str(status)).inc()
                HTTP_DURATION.labels(method, route).observe(time.perf_counter() - started)
                caller = getattr(request.state, "caller", None)
                log.info("http", method=request.method, route=route, status=status,
                         caller_sub=getattr(caller, "sub", None), client=getattr(caller, "client_id", None),
                         ms=round((time.perf_counter() - started) * 1000, 1))
            structlog.contextvars.clear_contextvars()


def instrument(app: FastAPI) -> None:
    app.add_middleware(MetricsAndRequestIdMiddleware)
