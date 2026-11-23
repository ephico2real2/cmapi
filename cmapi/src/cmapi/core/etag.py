"""Entity tags (RFC 9110, 8.8.3): the strong tag of a served body, the If-None-Match check (13.1.2), and the tags that an
If-Match value lists (13.1.1).

etag_of and not_modified serve every answer that cmapi builds once from bytes: /openapi.json and /openapi.yaml (main.py),
GET /api/v1/metadata-keys (routers/me.py, #336) and the capacity read (plugins/capacity/router.py). Two replicas on the same
configuration give the same tag. if_match_tags reads If-Match, for the writes to a namespace (core/pipeline.py,
check_if_match, #571) and for those reads (not_modified, #590). Both fields are read as a list of tags with _listed_tags,
one grammar for the two (#583).
"""
from __future__ import annotations

import hashlib
import re

from starlette.datastructures import Headers

from cmapi.core.errors import Problem

# RFC 9110 section 8.8.3: entity-tag = [ weak ] opaque-tag, opaque-tag = DQUOTE *etagc DQUOTE, and etagc is any visible
# character but DQUOTE, or obs-text. A list element (section 5.6.1.2) is OWS, an entity-tag or nothing, OWS, then a comma
# or the end. A tag may hold a comma, so a list is read element by element, never split on ",".
# The OWS after a tag sits inside the tag's group, so only one [ \t]* can take a run of whitespace. Two in a row would share
# it, and a run that does not end its element would be retried at every split: a quadratic parse (#580).
_LIST_ELEMENT = re.compile(r'[ \t]*(?:(W/)?"([\x21\x23-\x7e\x80-\xff]*)"[ \t]*)?(?:,|\Z)')
# One strong tag sent without its quotes: etagc characters, no comma.
_UNQUOTED_TAG = re.compile(r'[\x21\x23-\x2b\x2d-\x7e\x80-\xff]+')
# The detail of a read's 412 (not_modified); core/docs.py shows it in the document.
STALE_READ = "If-Match does not list the current ETag of this answer: read it again"


def etag_of(body: bytes) -> str:
    """A strong ETag: a quoted hash of exactly the bytes served, so it changes with every change of the representation."""
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def _listed_tags(value: str) -> list[tuple[bool, str]] | None:
    """Each entity tag of a list value, in order, as (weak, opaque-tag without its quotes); None when the value is not a
    list of entity tags. Empty list elements are skipped (RFC 9110 section 5.6.1.2)."""
    tags: list[tuple[bool, str]] = []
    pos = 0
    while pos < len(value):
        element = _LIST_ELEMENT.match(value, pos)
        if element is None:
            return None
        weak, tag = element.groups()
        if tag is not None:
            tags.append((weak is not None, tag))
        pos = element.end()
    return tags


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """True when If-None-Match matches `etag`, a strong tag as etag_of gives it, quoted: the request answers 304.

    RFC 9110 section 13.1.2: `If-None-Match = "*" / #entity-tag`, compared by the weak comparison (section 8.8.3.2), so
    W/"x" matches "x". `*` matches any, as each caller has a current representation. A tag may hold a comma or a `*`, so
    the list is read tag by tag, never split on "," (#583). A value that is not a list of entity tags matches nothing: the
    condition "Otherwise ... is true", and the read answers 200. A field sent on several lines reaches here joined with
    commas (section 5.3), by the caller."""
    if if_none_match is None:
        return False
    if if_none_match.strip(" \t") == "*":          # OWS is SP and HTAB only (section 5.6.3)
        return True
    tags = _listed_tags(if_none_match)
    return tags is not None and any(tag == etag[1:-1] for _, tag in tags)


def if_match_tags(if_match: str) -> list[str]:
    """The strong entity tags that an If-Match value lists, without their quotes: [] when it lists none.

    RFC 9110 section 13.1.1: `If-Match = "*" / #entity-tag`, compared by the strong comparison, so a weak tag (W/"x") is
    left out: it never matches. Empty list elements are skipped (section 5.6.1.2). A value that is not a list of entity
    tags lists none, so its condition is false (13.1.1: "Otherwise, the condition is false"). One strong tag sent without
    its quotes is still read as that tag, as cmapi always has (section 2.4: a recipient "MAY attempt to recover a usable
    protocol element from an invalid construct"). "*" is not a tag: require_if_match refuses it on a write (core/pipeline.py),
    and not_modified lets it hold on a read."""
    if if_match != "*" and not if_match.startswith("W/") and _UNQUOTED_TAG.fullmatch(if_match):
        return [if_match]
    tags = _listed_tags(if_match)
    return [tag for weak, tag in tags if not weak] if tags is not None else []


def not_modified(headers: Headers, etag: str) -> bool:
    """The preconditions of a read whose answer has the strong tag `etag` (quoted, as etag_of gives it), in the order of
    RFC 9110 section 13.2.2. True when the answer is 304; raises a 412 precondition-failed when If-Match is false.

    1. If-Match (section 13.1.1), when present: `*` holds, as the answer exists. Otherwise one strong tag it lists must be
       `etag` (strong comparison: a weak tag never matches), or the read is 412 with the current tag in `etag`, without
       its quotes as on a namespace's 412. An empty value lists no tag, so it is false too. The write policy that refuses
       `*` (core/pipeline.py, require_if_match, #571) is for changes only.
    2. If-None-Match (section 13.1.2): True when it matches, by the weak comparison (etag_matches).

    A field sent on several lines is one list, joined with ", " (section 5.3)."""
    if_match = headers.getlist("if-match")
    if if_match:
        value = ", ".join(if_match)
        if value.strip(" \t") != "*" and etag[1:-1] not in if_match_tags(value):   # OWS is SP and HTAB only (5.6.3)
            raise Problem(412, "precondition-failed", STALE_READ, extra={"etag": etag[1:-1]})
    return etag_matches(", ".join(headers.getlist("if-none-match")), etag)
