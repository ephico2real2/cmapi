"""Import token policy shared by the worker and the standalone bootstrap writers (stdlib only)."""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

READER_IDENTITY = "system:serviceaccount:cmapi-system:cmapi-reader"
# Exceed the registry relist (300 s, relist_seconds) plus the scan delay so every API pod reads the new token before expiry.
MIN_WINDOW = 600
# A cluster stamps `iat` with its own clock. Allow it to run this far ahead of the worker or the operator.
CLOCK_SKEW = 60
DEFAULT_PERCENTAGE = 20
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def duration_seconds(value: str) -> int:
    if not isinstance(value, str) or not (match := re.fullmatch(r"([0-9]+)([dhms])", value)):
        raise ValueError(f"duration {value!r} needs an integer and one of d, h, m, s")
    return int(match[1]) * _UNITS[match[2]]


@dataclass(frozen=True)
class TokenPolicy:
    duration: int = 7 * 86400
    renew_before: int | None = None
    percentage: int | None = DEFAULT_PERCENTAGE

    def window(self, lifetime: int) -> float:
        if self.renew_before is not None:
            if lifetime < self.duration:
                return lifetime * DEFAULT_PERCENTAGE / 100
            return self.renew_before
        return lifetime * self.percentage / 100

    def override(self, values: dict) -> TokenPolicy:
        if not isinstance(values, dict) or values.keys() - {"duration", "renewBefore", "renewBeforePercentage"}:
            raise ValueError("clusterTokens must be a mapping of duration and renewal settings")
        if "renewBefore" in values and "renewBeforePercentage" in values:
            raise ValueError(f"renewBefore {values['renewBefore']!r} and renewBeforePercentage {values['renewBeforePercentage']!r} are exclusive")
        duration = duration_seconds(values["duration"]) if "duration" in values else self.duration
        before, percent = self.renew_before, self.percentage
        if "renewBefore" in values:
            before, percent = duration_seconds(values["renewBefore"]), None
        if "renewBeforePercentage" in values:
            before, percent = None, values["renewBeforePercentage"]
        if not 2 * MIN_WINDOW <= duration <= (2**63 - 1) // 1_000_000_000:
            raise ValueError(f"duration {duration}s must be at least 20m and fit a Kubernetes duration")
        if before is not None and not MIN_WINDOW <= before < duration / 2:
            raise ValueError(f"renewBefore {before}s must be at least 10m and less than half of duration {duration}s")
        if before is None and (type(percent) is not int or not 1 <= percent <= 50):
            raise ValueError(f"renewBeforePercentage {percent!r} must be an integer from 1 to 50")
        return TokenPolicy(duration, before, percent)


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
        lifetime = self.expires - self.issued
        deadline = self.expires - policy.window(lifetime)  # Start with the wanted window before expiry.
        deadline = max(deadline, self.issued + lifetime / 2)  # Never renew before halfway through the grant.
        deadline = min(deadline, self.expires - MIN_WINDOW)  # Leave at least ten minutes for relists and the scan delay.
        return deadline

    def check_new(self, policy: TokenPolicy, now: float) -> None:
        if self.issued > now + CLOCK_SKEW or self.expires - self.issued > policy.duration:
            raise ValueError("reader token lifetime outside requested duration")
        if now >= self.renewal_time(policy):
            raise ValueError("reader token has already reached its renewal deadline")
