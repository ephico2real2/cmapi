"""RFC 9457 problems. Every refusal in cmapi is one of these, so the API, the portal and the
CLI read one shape: {type, title, status, detail, code, errors[]}."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BASE = "https://cmapi.ephico2real.com/problems/"   # placeholder host, like every ephico2real.com name


@dataclass
class Problem(Exception):
    status: int
    code: str                       # the problem type's last path segment, e.g. policy-violation
    detail: str
    errors: list[dict[str, Any]] = field(default_factory=list)   # per-item codes, e.g. reserved_key
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.detail)

    def body(self) -> dict[str, Any]:
        out = {"type": BASE + self.code, "title": self.code.replace("-", " "), "status": self.status,
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
