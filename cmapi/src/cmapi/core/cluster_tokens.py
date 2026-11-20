"""Import token policy shared by the worker and the standalone bootstrap writers (stdlib only)."""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

READER_IDENTITY = "system:serviceaccount:cmapi-system:cmapi-reader"
MIN_WINDOW = 300
DEFAULT_PERCENTAGE = 20
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def duration_seconds(value: str) -> int:
    if not isinstance(value, str) or not (match := re.fullmatch(r"([0-9]+)([dhms])", value)):
        raise ValueError("duration needs an integer and one of d, h, m, s")
    return int(match[1]) * _UNITS[match[2]]


@dataclass(frozen=True)
class TokenPolicy:
    duration: int = 7 * 86400
    renew_before: int | None = None
    percentage: int | None = DEFAULT_PERCENTAGE

    def window(self, lifetime: int) -> float:
        if self.renew_before is not None:
            # A capped grant must leave time for normal use before starting another rotation.
            if lifetime < self.duration and lifetime - self.renew_before < MIN_WINDOW:
                return lifetime * DEFAULT_PERCENTAGE / 100
            return self.renew_before
        return lifetime * self.percentage / 100

    def override(self, values: dict) -> TokenPolicy:
        if not isinstance(values, dict) or values.keys() - {"duration", "renewBefore", "renewBeforePercentage"}:
            raise ValueError("clusterTokens must be a mapping of duration and renewal settings")
        if "renewBefore" in values and "renewBeforePercentage" in values:
            raise ValueError("choose only one of renewBefore and renewBeforePercentage")
        duration = duration_seconds(values["duration"]) if "duration" in values else self.duration
        before, percent = self.renew_before, self.percentage
        if "renewBefore" in values:
            before, percent = duration_seconds(values["renewBefore"]), None
        if "renewBeforePercentage" in values:
            before, percent = None, values["renewBeforePercentage"]
            if type(percent) is not int or not 0 < percent < 100:
                raise ValueError("renewBeforePercentage must be an integer from 1 to 99")
        if not 600 <= duration <= (2**63 - 1) // 1_000_000_000:
            raise ValueError("duration must be at least 10m and fit a Kubernetes duration")
        policy = TokenPolicy(duration, before, percent)
        if not MIN_WINDOW <= policy.window(duration) < duration:
            raise ValueError("renewal window must be at least 5m and shorter than duration")
        return policy


@dataclass(frozen=True)
class ReaderGrant:
    issued: int
    expires: int

    @classmethod
    def parse(cls, token: str) -> ReaderGrant:
        try:
            if not isinstance(token, str) or not re.fullmatch(r"[!-~]+", token):
                raise ValueError
            header, payload, signature = token.split(".")
            if not header or not signature or not re.fullmatch(r"[A-Za-z0-9_-]+", payload):
                raise ValueError
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if claims["sub"] != READER_IDENTITY:
                raise ValueError
            issued, expires = claims["iat"], claims["exp"]
            if type(issued) is not int or type(expires) is not int or not 0 <= issued < expires:
                raise ValueError
        except (TypeError, ValueError, KeyError, RecursionError):
            raise ValueError("invalid reader token subject or lifetime") from None
        return cls(issued, expires)

    def renewal_time(self, policy: TokenPolicy) -> float:
        return self.expires - max(MIN_WINDOW, policy.window(self.expires - self.issued))

    def check_new(self, policy: TokenPolicy, now: float) -> None:
        if self.issued > now or self.expires - self.issued > policy.duration:
            raise ValueError("reader token lifetime outside requested duration")
        if now >= self.renewal_time(policy):
            raise ValueError("reader token has already reached its renewal deadline")
