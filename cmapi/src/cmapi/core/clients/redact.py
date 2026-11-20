"""Redaction of a credential from error text, before the text is cut (docs/02 "Client rules", #420).

A cluster, or a proxy in front of it, may echo the request in an error body: the Authorization header as sent, or inside a
JSON document, where the token is escaped. That body becomes an error message, a cluster finding that GET /api/v1/clusters
serves to every `clusters:read` caller, and a log line. So every form the token can take in such a text is replaced, and
only then is the text cut: a cut first could split a token and leave a prefix that no full-token match finds
(group-sync-dashboard's lesson, docs/02 "Lessons from group-sync-dashboard").

The forms (`secret_forms`):
- the token as sent;
- JSON-escaped, as Python (`ensure_ascii` on and off), Go's encoding/json (which also escapes <, > and & as \\u003c,
  \\u003e, \\u0026; the Kubernetes API server is Go) and encoders that escape "/" as "\\/" write it; once, and twice for a
  JSON string inside a JSON string;
- the repr of its bytes, which an HTTP library's "illegal header value b'...'" error shows.

A credential a client sends (`sent_forms`) has one more spelling: form-encoded (quote_plus), as httpx writes a form body or a
query string, and as a proxy that echoes a request URL-encodes it. Each of its forms above is removed too.

A text that ends in the start of a form (8 characters or more) loses that start too: a body cut by the server or a proxy.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import quote_plus

MASK = "***"                    # as the Git layer's redaction writes it (core/git/oplog.py)
MIN_SECRET = 8                  # a shorter value is no credential, and replacing it would garble every message
MIN_PREFIX = 8                  # the shortest trailing start of a form that is removed


def order_forms(forms: Iterable[str]) -> tuple[str, ...]:
    """Longest first, then by the string itself so equal-length forms have a deterministic order."""
    return tuple(sorted(forms, key=lambda form: (-len(form), form)))


def _escapes(text: str) -> set[str]:
    """`text` as the body of a JSON string, the way each common encoder writes it."""
    ascii_ = json.dumps(text)[1:-1]
    go = ascii_.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return {ascii_, json.dumps(text, ensure_ascii=False)[1:-1], go, ascii_.replace("/", "\\/"), go.replace("/", "\\/")}


def secret_forms(secret: str | None) -> tuple[str, ...]:
    """Every form of `secret` to remove, longest first (so a longer form is never left half replaced by a shorter one), or
    none for a value shorter than MIN_SECRET."""
    if not secret or len(secret) < MIN_SECRET:
        return ()
    once = _escapes(secret)
    forms = {secret, *once, *(twice for form in once for twice in _escapes(form))}
    raw = secret.encode("utf-8", "backslashreplace")
    forms.add(repr(raw)[2:-1])
    return order_forms(f for f in forms if len(f) >= MIN_SECRET)


def sent_forms(secret: str | None) -> tuple[str, ...]:
    """`secret_forms` of a credential and of its form-encoded spelling, longest first: the one set of forms every client that
    sends a credential removes (the Git hosts, the realm sync, the Git layer's log; #424). A value shorter than MIN_SECRET has
    none in any spelling, as in `secret_forms`."""
    if not secret or len(secret) < MIN_SECRET:
        return ()
    return order_forms({*secret_forms(secret), *secret_forms(quote_plus(secret))})


def redact(text: str, forms: tuple[str, ...]) -> str:
    """`text` without any form of the secret, nor a trailing start of one. Call it on the whole text, then cut."""
    if not forms or not text:
        return text
    for form in forms:
        text = text.replace(form, MASK)
    for form in forms:
        for k in range(min(len(form) - 1, len(text)), MIN_PREFIX - 1, -1):
            if text.endswith(form[:k]):
                return text[:-k] + MASK
    return text


def redact_cut(text: str, forms: tuple[str, ...], limit: int) -> str:
    """Redact, then cut to `limit` characters: the order docs/02 "Client rules" sets."""
    return redact(text, forms)[:limit]
