"""One structured log event per Git or platform operation (#286, "Logging for merge problems").

Each event carries the request it served (request_id, cluster, namespace, branch, attempt, set once per job with git_context),
the op (fetch, worktree, commit, push, pr_open, pr_state, merge_check, merge, cleanup, ...), the shas the op saw (main_sha,
base_sha, head_sha), its outcome and duration, and on a failure the Git exit code with redacted stderr, or the host's HTTP
status and message. A conflict adds the conflicted paths. Each event also counts in cmapi_git_operations_total{op,result}.

No secret reaches a log line: every value the event carries passes through redact(), which removes each secret registered
with register_secret() (the Git token, the platform token) wherever it appears.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from cmapi.core.observability import GIT_DURATION, GIT_OPS, log

_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("cmapi_git_context", default={})
_SECRETS: set[str] = set()
_SECRETS_LOCK = threading.Lock()
CONTEXT_KEYS = ("request_id", "cluster", "namespace", "branch", "attempt")


def register_secret(value: str | None) -> None:
    """A value that must never be logged. Short values are refused: redacting a three-letter word would garble every line."""
    if value and len(value) >= 8:
        with _SECRETS_LOCK:
            _SECRETS.add(value)


def redact(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    for secret in _SECRETS:
        value = value.replace(secret, "***")
    return value


@contextmanager
def git_context(**fields: Any) -> Iterator[None]:
    """The request a job serves, added to every operation's event inside the block."""
    token = _CONTEXT.set({**_CONTEXT.get(), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def current_context() -> dict[str, Any]:
    return dict(_CONTEXT.get())


class Op:
    """with Op("merge_check", head_sha=h) as op: ...; op.set(main_sha=m, conflicts=[...]); op.outcome = "conflict".

    The outcome is ok when the block ends normally, failure when it raises, or what the block set (refused, conflict,
    skipped). An exception is logged and re-raised, never swallowed."""

    def __init__(self, op: str, **fields: Any):
        self.op, self.fields, self.outcome = op, dict(fields), None

    def set(self, **fields: Any) -> "Op":
        self.fields.update(fields)
        return self

    def __enter__(self) -> "Op":
        self.started = time.perf_counter()
        return self

    def __exit__(self, kind, exc, tb) -> bool:
        duration = time.perf_counter() - self.started
        outcome = self.outcome or ("ok" if exc is None else "failure")
        GIT_OPS.labels(self.op, outcome).inc()
        GIT_DURATION.labels(self.op).observe(duration)
        event = {**current_context(), **self.fields, "op": self.op, "outcome": outcome, "duration_ms": round(duration * 1000, 1)}
        if exc is not None:
            event["error"] = f"{type(exc).__name__}: {exc}"
        event = {k: redact(v) if not isinstance(v, list) else [redact(x) for x in v] for k, v in event.items()}
        (log.info if outcome in ("ok", "skipped") else log.warning)("git_op", **event)
        return False
