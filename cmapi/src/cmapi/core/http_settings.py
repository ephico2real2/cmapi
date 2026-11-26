"""instance.yaml `http`: the most bytes of request content that the API reads (#683), and the problem that refuses more.

    http:
      maxRequestBodyBytes: 1048576
      rateLimits: {write: {perMinute: 60, burst: 30}}

`rateLimits` is read by core/ratelimit.py, parse_rate_limits (#689).

The middleware that enforces the limit is core/bodylimit.py. This module holds what the config and the API document read,
with the standard library and core/errors.py only: core/config.py and core/docs.py are loaded by the tools and the reference
code, which install examples/local/requirements.txt, without structlog or the web layer (#693).
"""
from __future__ import annotations

from typing import Any, Mapping

from cmapi.core.errors import Problem

# The default limit, 1 MiB. The largest create that the reference metadata-keys.yaml takes, at its maximums (50 team labels
# and 50 team annotations with the longest keys, 64 KiB of annotation values), is 430,701 bytes when each value byte is a
# control character that json.dumps writes as a six-byte \uXXXX escape, and 102,581 bytes in ASCII (measured, the review
# record). So 1 MiB is 2.4 times the worst encoding, as Kubernetes allows twice its largest object (3 MiB for etcd's
# 1.5 MiB, k8s.io/apiserver pkg/server/config.go). It is also the front door's limit (client_max_body_size 1m).
DEFAULT_MAX_REQUEST_BODY_BYTES = 1024 * 1024

# The largest limit: the largest integer that JSON carries exactly, 2**53 - 1 (RFC 7493, section 2.2: a receiver cannot be
# expected to treat a larger integer "as an exact value"). The chart passes the value through JSON (toJson), which writes
# 1e21 or more as "1e+21", a string to PyYAML, and rounds a value above it (review 691, F2).
MAX_LIMIT = 2**53 - 1


def parse_http(raw: Any) -> tuple[int, list[str]]:
    """instance.yaml `http`: the limit, and the problems that stop the start."""
    if raw is None:
        return DEFAULT_MAX_REQUEST_BODY_BYTES, []
    if not isinstance(raw, Mapping):
        return DEFAULT_MAX_REQUEST_BODY_BYTES, ["instance.yaml: http must be a mapping, such as {maxRequestBodyBytes: 1048576}"]
    problems = []
    unknown = set(raw) - {"maxRequestBodyBytes", "rateLimits"}
    if unknown:
        problems.append(f"instance.yaml: http has unknown fields {sorted(unknown)}")
    value = raw.get("maxRequestBodyBytes", DEFAULT_MAX_REQUEST_BODY_BYTES)
    # bool is an int in Python; "maxRequestBodyBytes: yes" is not a limit
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LIMIT:
        problems.append(f"instance.yaml: http.maxRequestBodyBytes is a whole number of bytes, 1 to {MAX_LIMIT}, not {value!r}")
        value = DEFAULT_MAX_REQUEST_BODY_BYTES
    return value, problems


def too_large(max_bytes: int) -> Problem:
    """The problem of a request whose content is over the limit."""
    return Problem(413, "content-too-large", f"The request content is larger than {max_bytes} bytes, the most that this "
                                             "instance reads", extra={"maxBytes": max_bytes})
