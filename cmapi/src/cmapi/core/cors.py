"""Which browser origins can call the API from another origin (CORS). docs/15, "The portal's origin and the API".

The owner's decision of 2026-11-14 (#226): one front door for each instance, nginx, serves the portal and the API on ONE
origin. A page of that origin needs no CORS header, so CORS is OFF unless instance.yaml lists an origin in
`cors.allowedOrigins`. A second origin is the exception: a developer's portal on localhost, or another portal host.
RFC 10017 (BCP 212), section 6.3.3.4, for that case: "The authorization server and the resource server MUST send necessary
CORS headers".

When an origin is listed, the policy is the narrow one:

- Only the listed origins, each compared as exact text. Never `*`.
- No credentials. The API reads no cookie, so `Access-Control-Allow-Credentials` is never sent, and a browser's cookies give a
  page of another origin nothing.
- Only the request headers that the API reads, and only the response headers that a client needs.
- `Vary: Origin` on each answer, also on one with no CORS header, so a shared cache keeps the two apart.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Message, Receive, Scope, Send

METHODS = ["GET", "POST", "PATCH", "DELETE"]
# Each makes the request one that needs a preflight, so no page of an origin that is not listed can send it at all.
REQUEST_HEADERS = ["Authorization", "Content-Type", "Idempotency-Key", "If-Match", "If-None-Match", "X-Request-Id"]
# ETag is the value of If-Match on a change; Retry-After and WWW-Authenticate say what to do after a 429, a 503 or a 401;
# X-Request-Id is the line to look for in the logs.
EXPOSED_HEADERS = ["ETag", "Location", "Retry-After", "WWW-Authenticate", "X-Request-Id"]
MAX_AGE = 600           # seconds a browser keeps a preflight answer; WebKit's ceiling is 600, Chromium's is 7200

# An origin as a browser writes it: lower-case ASCII host (punycode for another script), no default port, nothing after it.
# urlsplit is not a browser's URL parser ("https://a.example\\@evil.example" has two readings), so no URL is parsed here:
# a value either has this exact form or it stops the start.
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HTTPS = re.compile(rf"https://(?P<host>{_LABEL}(?:\.{_LABEL})*)(?::(?P<port>[1-9][0-9]{{0,4}}))?")
_LOCAL = re.compile(r"http://(?:localhost|127\.0\.0\.1|\[::1\])(?::(?P<port>[1-9][0-9]{0,4}))?")


class CorsConfigError(ValueError):
    """instance.yaml names an origin that is not one. cmapi refuses to start, with each problem listed."""


def _problem(value: Any) -> str | None:
    """Why a value of cors.allowedOrigins is not an origin that cmapi accepts, or None."""
    if not isinstance(value, str) or not value:
        return "is not text"
    if "*" in value:
        return "has a wildcard: list each origin"
    if value == "null":
        return "is the opaque origin `null`, which each sandboxed page and local file has"
    https, local = _HTTPS.fullmatch(value), _LOCAL.fullmatch(value)
    if value.startswith("http://") and not local:
        return "must be https: http is for localhost, 127.0.0.1 and [::1] only"
    match = https or local
    if not match:
        return ("must be an origin as a browser sends it: https://host or https://host:port, with a lower-case ASCII host "
                "and no path, query, fragment or user")
    port = match.group("port")
    if port and (int(port) > 65535 or int(port) == (443 if https else 80)):
        return "has a port that a browser does not send: leave out the default port, and use 1 to 65535"
    return None


def allowed_origins(instance: Mapping[str, Any]) -> list[str]:
    """The origins of another host that can call this instance from a browser: `cors.allowedOrigins` of instance.yaml.

    No key, or an empty list: CORS is off, and the API sends no CORS header. The portal behind the instance's front door is
    on the API's own origin and needs none (#226).
    """
    cors = instance.get("cors")
    if cors is None:
        return []
    if not isinstance(cors, Mapping):
        raise CorsConfigError("instance.yaml cors must be a mapping with allowedOrigins")
    listed = cors.get("allowedOrigins", [])
    if not isinstance(listed, list):
        raise CorsConfigError("instance.yaml cors.allowedOrigins must be a list of origins")
    problems = [f"{value!r} {problem}" for value in listed if (problem := _problem(value))]
    if problems:
        raise CorsConfigError("instance.yaml cors.allowedOrigins: " + "; ".join(problems))
    return list(dict.fromkeys(listed))


class OriginVaryCORSMiddleware(CORSMiddleware):
    """Starlette's CORS middleware, with `Vary: Origin` on each answer.

    Starlette adds it only to an answer for a listed origin. An answer for another origin, or for no origin, then has no
    Vary, and a shared cache can give that copy, which has no CORS header, to the listed origin (review finding F2).
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def vary_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                varied = {v.strip().lower() for v in headers.get("vary", "").split(",")}
                if "origin" not in varied and "*" not in varied:
                    headers.add_vary_header("Origin")
            await send(message)

        await super().__call__(scope, receive, vary_send)
