"""Strong entity tags of a served body, and the If-None-Match check (RFC 9110, 8.8.3 and 13.1.2).

One implementation for every answer that cmapi serves from bytes it builds once: /openapi.json and /openapi.yaml
(main.py) and GET /api/v1/metadata-keys (routers/me.py, #336). Two replicas on the same configuration give the same tag.
"""
from __future__ import annotations

import hashlib


def etag_of(body: bytes) -> str:
    """A strong ETag: a quoted hash of exactly the bytes served, so it changes with every change of the representation."""
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """If-None-Match against the tag, by the weak comparison RFC 9110 13.1.2 asks for: W/"x" matches "x", and * any."""
    if not if_none_match:
        return False
    candidates = [c.strip() for c in if_none_match.split(",")]
    return "*" in candidates or etag in [c.removeprefix("W/") for c in candidates]
