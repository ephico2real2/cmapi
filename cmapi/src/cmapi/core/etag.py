"""Entity tags (RFC 9110, 8.8.3): the strong tag of a served body, the If-None-Match check (13.1.2), and the tags that an
If-Match value lists (13.1.1).

etag_of and etag_matches serve every answer that cmapi builds once from bytes: /openapi.json and /openapi.yaml (main.py)
and GET /api/v1/metadata-keys (routers/me.py, #336). Two replicas on the same configuration give the same tag.
if_match_tags reads If-Match for the writes to a namespace (core/pipeline.py, check_if_match, #571).
"""
from __future__ import annotations

import hashlib
import re

# RFC 9110 section 8.8.3: entity-tag = [ weak ] opaque-tag, opaque-tag = DQUOTE *etagc DQUOTE, and etagc is any visible
# character but DQUOTE, or obs-text. A list element (section 5.6.1.2) is OWS, an entity-tag or nothing, OWS, then a comma
# or the end. A tag may hold a comma, so a list is read element by element, never split on ",".
# The OWS after a tag sits inside the tag's group, so only one [ \t]* can take a run of whitespace. Two in a row would share
# it, and a run that does not end its element would be retried at every split: a quadratic parse (#580).
_LIST_ELEMENT = re.compile(r'[ \t]*(?:(W/)?"([\x21\x23-\x7e\x80-\xff]*)"[ \t]*)?(?:,|\Z)')
# One strong tag sent without its quotes: etagc characters, no comma.
_UNQUOTED_TAG = re.compile(r'[\x21\x23-\x2b\x2d-\x7e\x80-\xff]+')


def etag_of(body: bytes) -> str:
    """A strong ETag: a quoted hash of exactly the bytes served, so it changes with every change of the representation."""
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """If-None-Match against the tag, by the weak comparison RFC 9110 13.1.2 asks for: W/"x" matches "x", and * any."""
    if not if_none_match:
        return False
    candidates = [c.strip() for c in if_none_match.split(",")]
    return "*" in candidates or etag in [c.removeprefix("W/") for c in candidates]


def if_match_tags(if_match: str) -> list[str]:
    """The strong entity tags that an If-Match value lists, without their quotes: [] when it lists none.

    RFC 9110 section 13.1.1: `If-Match = "*" / #entity-tag`, compared by the strong comparison, so a weak tag (W/"x") is
    left out: it never matches. Empty list elements are skipped (section 5.6.1.2). A value that is not a list of entity
    tags lists none, so its condition is false (13.1.1: "Otherwise, the condition is false"). One strong tag sent without
    its quotes is still read as that tag, as cmapi always has (section 2.4: a recipient "MAY attempt to recover a usable
    protocol element from an invalid construct"). "*" is not a tag: require_if_match refuses it before (core/pipeline.py)."""
    if if_match != "*" and not if_match.startswith("W/") and _UNQUOTED_TAG.fullmatch(if_match):
        return [if_match]
    tags: list[str] = []
    pos = 0
    while pos < len(if_match):
        element = _LIST_ELEMENT.match(if_match, pos)
        if element is None:
            return []
        weak, tag = element.groups()
        if tag is not None and weak is None:
            tags.append(tag)
        pos = element.end()
    return tags
