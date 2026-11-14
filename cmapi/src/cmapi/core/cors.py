"""Which browser origins can call the API (CORS). docs/15, "The portal's origin and the API", has the decision and its sources.

The portal is a browser application on its own origin, and it sends the access token in the Authorization header. RFC 10017
(BCP 212), section 6.3.3.4: "The authorization server and the resource server MUST send necessary CORS headers". Section 9.4
recommends one origin for each application, so the API does not move behind the portal's host.

The policy is the narrow one:

- Only the origins of instance.yaml: `cors.allowedOrigins`, or the origin of `portalUrl` when that key is absent. Never `*`.
- No credentials. The API reads no cookie, so `Access-Control-Allow-Credentials` is never sent, and a browser's cookies give a
  page of another origin nothing.
- Only the request headers that the API reads, and only the response headers that a client needs.
"""
from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

METHODS = ["GET", "POST", "PATCH", "DELETE"]
# Each makes the request one that needs a preflight, so no page of an origin that is not listed can send it at all.
REQUEST_HEADERS = ["Authorization", "Content-Type", "Idempotency-Key", "If-Match", "If-None-Match", "X-Request-Id"]
# ETag is the value of If-Match on a change; Retry-After and WWW-Authenticate say what to do after a 429, a 503 or a 401;
# X-Request-Id is the line to look for in the logs.
EXPOSED_HEADERS = ["ETag", "Location", "Retry-After", "WWW-Authenticate", "X-Request-Id"]
MAX_AGE = 600           # seconds a browser keeps a preflight answer; Chrome's ceiling is 7200, and Firefox's is 86400
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


class CorsConfigError(ValueError):
    """instance.yaml names an origin that is not one. cmapi refuses to start, with each problem listed."""


def origin_of(url: str) -> str:
    """scheme://host[:port] of a URL, as a browser writes the Origin header (lower case, no default port, no path)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    default = {"https": 443, "http": 80}.get(parts.scheme)
    port = f":{parts.port}" if parts.port and parts.port != default else ""
    return f"{parts.scheme}://{host}{port}"


def _problem(value: Any) -> str | None:
    """Why a value of cors.allowedOrigins is not an origin that cmapi accepts, or None."""
    if not isinstance(value, str) or not value:
        return "is not text"
    if "*" in value:
        return "has a wildcard: list each origin"
    if value == "null":
        return "is the opaque origin `null`, which each sandboxed page and local file has"
    try:
        parts = urlsplit(value)
        parts.port                       # raises on a port that is not a number
    except ValueError as exc:
        return f"is not a URL ({exc})"
    if parts.scheme not in ("https", "http") or not parts.hostname:
        return "must be https://host or https://host:port"
    if parts.username or parts.password or parts.path or parts.query or parts.fragment or value.endswith(("/", "?", "#")):
        return "must be scheme://host[:port] only: no path, no query, no fragment, no user"
    if parts.scheme == "http" and parts.hostname.lower() not in {h.strip("[]") for h in LOCAL_HOSTS}:
        return "must be https: http is for localhost only"
    if value != origin_of(value):
        return f"must be written as the browser sends it: {origin_of(value)}"
    return None


def allowed_origins(instance: Mapping[str, Any]) -> list[str]:
    """The origins that can call this instance from a browser, from instance.yaml.

    `cors.allowedOrigins` is the list. When instance.yaml has no `cors.allowedOrigins`, the list is the origin of `portalUrl`:
    the portal is the browser client that the design names. An empty list turns CORS off: the API then sends no CORS header.
    """
    cors = instance.get("cors")
    if cors is not None and not isinstance(cors, Mapping):
        raise CorsConfigError("instance.yaml cors must be a mapping with allowedOrigins")
    if cors is None or "allowedOrigins" not in cors:
        portal = instance.get("portalUrl")
        if not portal:
            return []
        origin = origin_of(str(portal))
        problem = _problem(origin)
        if problem:
            raise CorsConfigError(f"instance.yaml portalUrl {portal!r} gives the origin {origin!r}, which {problem}. "
                                  "Set cors.allowedOrigins, or correct portalUrl")
        return [origin]
    listed = cors["allowedOrigins"]
    if not isinstance(listed, list):
        raise CorsConfigError("instance.yaml cors.allowedOrigins must be a list of origins")
    problems = [f"{value!r} {problem}" for value in listed if (problem := _problem(value))]
    if problems:
        raise CorsConfigError("instance.yaml cors.allowedOrigins: " + "; ".join(problems))
    return list(dict.fromkeys(listed))
