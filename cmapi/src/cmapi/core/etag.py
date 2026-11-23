"""Entity tags (RFC 9110, 8.8.3): the strong tag of a served body, the If-None-Match check (13.1.2), and the tags that an
If-Match value lists (13.1.1). With them, the preconditions of a read in the order of section 13.2.2 (not_modified).

etag_of and not_modified serve every answer that cmapi builds once from bytes: /openapi.json and /openapi.yaml (main.py),
GET /api/v1/metadata-keys (routers/me.py, #336) and the capacity read (plugins/capacity/router.py). Two replicas on the same
configuration give the same tag. not_modified also serves the files under /static (main.py, ConditionalStaticFiles, #604),
which have a Last-Modified too, so it reads the two date fields for them (#619, #620). if_match_tags reads If-Match, for the
writes to a namespace (core/pipeline.py, check_if_match, #571) and for those reads (not_modified, #590). Both fields are read
as a list of tags with _listed_tags, one grammar for the two (#583).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

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
# The detail of the 412 of a false If-Unmodified-Since. Only a file under /static has a Last-Modified, and none of those
# is in the document.
CHANGED_SINCE = "This answer changed after the date in If-Unmodified-Since: read it again"

# RFC 9110 section 5.6.7: HTTP-date = IMF-fixdate / rfc850-date / asctime-date, case-sensitive, and "A recipient that parses
# a timestamp value in an HTTP field MUST accept all three HTTP-date formats". Each pattern matches one date exactly, so a
# list of dates or a date followed by anything else is no HTTP-date, which 13.1.3 and 13.1.4 require to be ignored;
# email.utils.parsedate would read the first date of it (#620).
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTH = "|".join(_MONTHS)
_DAY_NAME = "Mon|Tue|Wed|Thu|Fri|Sat|Sun"
_DAY_NAME_L = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
_TIME_OF_DAY = "([0-9]{2}):([0-9]{2}):([0-9]{2})"
_IMF_FIXDATE = re.compile(rf"(?:{_DAY_NAME}), ([0-9]{{2}}) ({_MONTH}) ([0-9]{{4}}) {_TIME_OF_DAY} GMT")
_RFC850_DATE = re.compile(rf"(?:{_DAY_NAME_L}), ([0-9]{{2}})-({_MONTH})-([0-9]{{2}}) {_TIME_OF_DAY} GMT")
_ASCTIME_DATE = re.compile(rf"(?:{_DAY_NAME}) ({_MONTH}) ([0-9]{{2}}| [0-9]) {_TIME_OF_DAY} ([0-9]{{4}})")


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


def http_date(value: str) -> datetime | None:
    """The instant, in UTC, of a value that is exactly one HTTP-date (RFC 9110 section 5.6.7), or None.

    The day name is not checked against the date. A two-digit year of an rfc850-date is in this century, unless that is
    more than 50 years ahead: then it is the century before ("MUST interpret a timestamp that appears to be more than 50
    years in the future as representing the most recent year in the past that had the same last two digits"). A leap
    second (:60, which time-of-day allows) is read as :59. An impossible date, 31 Feb or 25:00:00, is no HTTP-date."""
    if m := _IMF_FIXDATE.fullmatch(value):
        day, month, year, hour, minute, second = m.groups()
    elif m := _RFC850_DATE.fullmatch(value):
        day, month, two_digits, hour, minute, second = m.groups()
        this_year = datetime.now(timezone.utc).year
        year = this_year - this_year % 100 + int(two_digits)
        if year > this_year + 50:
            year -= 100
    elif m := _ASCTIME_DATE.fullmatch(value):
        month, day, hour, minute, second, year = m.groups()
    else:
        return None
    try:
        return datetime(int(year), _MONTHS.index(month) + 1, int(day), int(hour), int(minute), min(int(second), 59),
                        tzinfo=timezone.utc)
    except ValueError:
        return None


def _date_field(headers: Headers, name: str) -> datetime | None:
    """The date of If-Modified-Since or If-Unmodified-Since, or None when the field is absent or must be ignored: on more
    than one line (one field, section 5.3, so a list of dates), or not one HTTP-date (sections 13.1.3 and 13.1.4)."""
    values = headers.getlist(name)
    return http_date(values[0]) if len(values) == 1 else None


def not_modified(headers: Headers, etag: str, last_modified: str | None = None) -> bool:
    """The preconditions of a GET or HEAD whose answer has the strong tag `etag` (quoted, as etag_of gives it) and, for a
    file, the date of `last_modified` (its Last-Modified value), in the order of RFC 9110 section 13.2.2. True when the
    answer is 304; raises a 412 precondition-failed when If-Match or If-Unmodified-Since is false. The 412 has the current
    tag in `etag`, without its quotes as on a namespace's 412.

    1. If-Match (section 13.1.1), when present: `*` holds, as the answer exists. Otherwise one strong tag it lists must be
       `etag` (strong comparison: a weak tag never matches), or the read is 412. An empty value lists no tag, so it is
       false too. The write policy that refuses `*` (core/pipeline.py, require_if_match, #571) is for changes only.
    2. If-Unmodified-Since (section 13.1.4), when If-Match is absent and the answer has a date: 412 when the answer changed
       after the date in the field (#619).
    3. If-None-Match (section 13.1.2), when present: True when it matches, by the weak comparison (etag_matches).
    4. If-Modified-Since (section 13.1.3), when If-None-Match is absent and the answer has a date: True when the answer has
       not changed after the date in the field (#620).

    An answer without a date skips steps 2 and 4: "A recipient MUST ignore the If-Unmodified-Since header field if the
    resource does not have a modification date available" (13.1.4; 13.1.3 says the same of If-Modified-Since). A date field
    that is not one HTTP-date is ignored too (_date_field). A tag field sent on several lines is one list, joined with ", "
    (section 5.3)."""
    if_match = headers.getlist("if-match")
    if if_match:
        value = ", ".join(if_match)
        if value.strip(" \t") != "*" and etag[1:-1] not in if_match_tags(value):   # OWS is SP and HTAB only (5.6.3)
            raise Problem(412, "precondition-failed", STALE_READ, extra={"etag": etag[1:-1]})
    changed = http_date(last_modified) if last_modified is not None else None
    if not if_match and changed is not None:
        unmodified_since = _date_field(headers, "if-unmodified-since")
        if unmodified_since is not None and changed > unmodified_since:
            raise Problem(412, "precondition-failed", CHANGED_SINCE, extra={"etag": etag[1:-1]})
    if_none_match = headers.getlist("if-none-match")
    if if_none_match:
        return etag_matches(", ".join(if_none_match), etag)
    if changed is None:
        return False
    modified_since = _date_field(headers, "if-modified-since")
    return modified_since is not None and changed <= modified_since
