"""RFC 9457 problems. Every refusal in cmapi is one of these, so the API, the portal and the
CLI read one shape: {type, title, status, detail, code, errors[]}."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

# The default base of each problem type URI: a placeholder host, like every ephico2real.com name. The contract's examples use it.
BASE = "https://cmapi.ephico2real.com/problems/"


def type_base(instance: Mapping[str, Any]) -> str:
    """The base of the problem type URIs of this instance: instance.yaml `problems.typeBase`, or BASE.

    RFC 9457, section 3.1.1: the type URI is "the problem type's primary identifier", and absolute URIs are recommended. So an
    organisation sets one base for all its instances, and a client sees the same type from each. Each instance serves the
    documentation at /problems/<code> (core/problem_docs.py), so the base resolves when its host points at an instance.
    """
    base = (instance.get("problems") or {}).get("typeBase") or BASE
    parts = urlsplit(base) if isinstance(base, str) else None
    if parts is None or parts.scheme not in ("https", "http") or not parts.netloc or parts.query or parts.fragment:
        raise ValueError(f"instance.yaml problems.typeBase must be an absolute http(s) URI with no query and no fragment: {base!r}")
    return base if base.endswith("/") else base + "/"


@dataclass
class Problem(Exception):
    status: int
    code: str                       # the problem type's last path segment, e.g. policy-violation
    detail: str
    errors: list[dict[str, Any]] = field(default_factory=list)   # per-item codes, e.g. reserved_key
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.detail)

    def body(self, base: str = BASE) -> dict[str, Any]:
        out = {"type": base + self.code, "title": self.code.replace("-", " "), "status": self.status,
               "detail": self.detail, "code": self.code}
        if self.errors:
            out["errors"] = self.errors
        return {**out, **self.extra}

    # the problem types the modules raise
    @classmethod
    def policy_violation(cls, detail: str, errors: list[dict[str, Any]]) -> "Problem":
        return cls(422, "policy-violation", detail, errors)

    @classmethod
    def unprocessable(cls, code: str, detail: str, **extra: Any) -> "Problem":
        return cls(422, code, detail, extra=extra)

    @classmethod
    def conflict(cls, code: str, detail: str, **extra: Any) -> "Problem":
        return cls(409, code, detail, extra=extra)

    @classmethod
    def forbidden(cls, detail: str, code: str = "forbidden") -> "Problem":
        return cls(403, code, detail)

    @classmethod
    def bad_request(cls, code: str, detail: str) -> "Problem":
        return cls(400, code, detail)

    @classmethod
    def too_many(cls, detail: str, retry_after: int) -> "Problem":
        return cls(429, "rate-limited", detail, extra={"retryAfter": retry_after})
