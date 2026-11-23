"""The preconditions of the Swagger UI and ReDoc files under /static (main.py, ConditionalStaticFiles; core/etag.py,
not_modified), #604 and the two date defects found while fixing it, #619 and #620.

RFC 9110 (https://www.rfc-editor.org/rfc/rfc9110.txt, read 2026-11-23), section 13.2.2: "A recipient cache or origin server
MUST evaluate the request preconditions defined by this specification in the following order": If-Match (step 1), then
If-Unmodified-Since when If-Match is absent (step 2), both answering 412 when false, then If-None-Match (step 3) and
If-Modified-Since when If-None-Match is absent (step 4), both answering 304. Starlette 0.41.3's StaticFiles.is_not_modified
(starlette/staticfiles.py:199-220) reads only If-None-Match and If-Modified-Since, so:

- #604: a stale If-Match answered 200, or 304 beside a matching If-None-Match, and `If-None-Match: *` answered 200.
- #619: If-Unmodified-Since was never read. Section 13.1.4: "An origin server that evaluates an If-Unmodified-Since
  condition MUST NOT perform the requested method if the condition evaluates to false."
- #620: If-Modified-Since was read with email.utils.parsedate, which takes the first date of a list and so answered 304.
  Section 13.1.3: "A recipient MUST ignore the If-Modified-Since header field if the received field value is not a valid
  HTTP-date, the field value has more than one member". Section 13.1.4 says the same of If-Unmodified-Since.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import pytest

from test_api_docs import bundles  # noqa: F401  (the fixture: the files the image holds)
from test_read_preconditions_590_593 import CASES

PATHS = ["/static/swagger/swagger-ui-bundle.js", "/static/redoc/redoc.standalone.js"]
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
LONG_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def imf_fixdate(t: datetime) -> str:
    return f"{DAYS[t.weekday()]}, {t.day:02d} {MONTHS[t.month - 1]} {t.year} {t:%H:%M:%S} GMT"


def rfc850_date(t: datetime) -> str:
    return f"{LONG_DAYS[t.weekday()]}, {t.day:02d}-{MONTHS[t.month - 1]}-{t.year % 100:02d} {t:%H:%M:%S} GMT"


def asctime_date(t: datetime) -> str:
    return f"{DAYS[t.weekday()]} {MONTHS[t.month - 1]} {t.day:2d} {t:%H:%M:%S} {t.year}"


def _check(r, status: int, first) -> None:
    assert r.status_code == status, (r.request.headers, r.status_code, r.text[:300])
    etag = first.headers["etag"]
    if status == 412:
        # The problem of every other 412 of the API (RFC 9457), with the file's current tag without its quotes.
        assert r.headers["content-type"] == "application/problem+json"
        body = r.json()
        assert (body["code"], body["status"], body["etag"]) == ("precondition-failed", 412, etag[1:-1])
    elif status == 304:
        assert (r.content, r.headers["etag"]) == (b"", etag)
    else:
        assert r.content == first.content and r.headers["etag"] == etag


# ---------------------------------------------------------------- #604 the entity-tag preconditions, as on every read

@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("if_match, if_none_match, status", CASES)
def test_a_static_file_evaluates_if_match_first(bundles, world, path, if_match, if_none_match, status):
    """The same table as the conditional reads (test_read_preconditions_590_593.py, #590): one evaluator for both."""
    client, *_ = world
    first = client.get(path)
    assert first.status_code == 200 and first.headers["etag"], first.text
    etag = first.headers["etag"]
    lines = [("If-Match", v.format(etag=etag, tag=etag[1:-1])) for v in if_match] + \
            [("If-None-Match", v.format(etag=etag, tag=etag[1:-1])) for v in if_none_match]
    _check(client.get(path, headers=lines), status, first)


@pytest.mark.parametrize("path", PATHS)
def test_the_cases_of_issue_604(bundles, world, path):
    """The four answers that the issue names, one by one."""
    client, *_ = world
    first = client.get(path)
    etag = first.headers["etag"]
    _check(client.get(path, headers={"If-Match": '"stale"'}), 412, first)
    _check(client.get(path, headers={"If-Match": '"stale"', "If-None-Match": etag}), 412, first)
    _check(client.get(path, headers={"If-None-Match": "*"}), 304, first)
    _check(client.get(path, headers={"If-None-Match": etag}), 304, first)
    _check(client.get(path), 200, first)


# ---------------------------------------------------------------- #619 and #620 the date preconditions

def _dates(first) -> tuple[datetime, datetime, datetime]:
    """The file's Last-Modified, a second before it and a second after it."""
    changed = parsedate_to_datetime(first.headers["last-modified"])
    return changed, changed - timedelta(seconds=1), changed + timedelta(seconds=1)


@pytest.mark.parametrize("path", PATHS)
def test_if_unmodified_since_is_step_2(bundles, world, path):
    client, *_ = world
    first = client.get(path)
    etag = first.headers["etag"]
    changed, before, after = _dates(first)
    for fmt in (imf_fixdate, rfc850_date, asctime_date):        # section 5.6.7: "MUST accept all three HTTP-date formats"
        _check(client.get(path, headers={"If-Unmodified-Since": fmt(before)}), 412, first)
        _check(client.get(path, headers={"If-Unmodified-Since": fmt(changed)}), 200, first)   # "earlier than or equal to"
        _check(client.get(path, headers={"If-Unmodified-Since": fmt(after)}), 200, first)
    # Step 2 comes before If-None-Match, which would have answered 304.
    _check(client.get(path, headers={"If-Unmodified-Since": imf_fixdate(before), "If-None-Match": etag}), 412, first)
    # 13.1.4: "A recipient MUST ignore If-Unmodified-Since if the request contains an If-Match header field".
    _check(client.get(path, headers={"If-Unmodified-Since": imf_fixdate(before), "If-Match": etag}), 200, first)
    # ... and when it is not one valid HTTP-date: a list, a second line, another syntax, an impossible day.
    for value in (f"{imf_fixdate(before)}, {imf_fixdate(before)}", f"{imf_fixdate(before)}, junk",
                  imf_fixdate(before).lower(), imf_fixdate(before).replace(" GMT", " +0000"), "Mon, 31 Feb 2000 00:00:00 GMT",
                  "junk", ""):
        _check(client.get(path, headers={"If-Unmodified-Since": value}), 200, first)
    two_lines = [("If-Unmodified-Since", imf_fixdate(before)), ("If-Unmodified-Since", imf_fixdate(before))]
    _check(client.get(path, headers=two_lines), 200, first)


@pytest.mark.parametrize("path", PATHS)
def test_if_modified_since_is_step_4(bundles, world, path):
    client, *_ = world
    first = client.get(path)
    changed, before, after = _dates(first)
    for fmt in (imf_fixdate, rfc850_date, asctime_date):
        _check(client.get(path, headers={"If-Modified-Since": fmt(changed)}), 304, first)
        _check(client.get(path, headers={"If-Modified-Since": fmt(after)}), 304, first)
        _check(client.get(path, headers={"If-Modified-Since": fmt(before)}), 200, first)
    # 13.1.3: "A recipient MUST ignore If-Modified-Since if the request contains an If-None-Match header field".
    _check(client.get(path, headers={"If-Modified-Since": imf_fixdate(after), "If-None-Match": '"other"'}), 200, first)
    # ... "if the received field value is not a valid HTTP-date, the field value has more than one member".
    for value in (f"{imf_fixdate(after)}, {imf_fixdate(after)}", f"{imf_fixdate(after)}, junk", "junk"):
        _check(client.get(path, headers={"If-Modified-Since": value}), 200, first)
    two_lines = [("If-Modified-Since", imf_fixdate(after)), ("If-Modified-Since", imf_fixdate(after))]
    _check(client.get(path, headers=two_lines), 200, first)


def test_a_two_digit_year_more_than_50_years_ahead_is_in_the_past():
    """Section 5.6.7: a recipient of an rfc850-date "MUST interpret a timestamp that appears to be more than 50 years in the
    future as representing the most recent year in the past that had the same last two digits"."""
    from cmapi.core.etag import http_date
    now = datetime.now(timezone.utc)
    near, far = (now.year + 10) % 100, (now.year + 60) % 100
    assert http_date(f"Sunday, 06-Nov-{near:02d} 08:49:37 GMT").year == now.year + 10
    assert http_date(f"Sunday, 06-Nov-{far:02d} 08:49:37 GMT").year == now.year + 60 - 100
    assert http_date("Sun, 06 Nov 1994 08:49:37 GMT") == datetime(1994, 11, 6, 8, 49, 37, tzinfo=timezone.utc)
    assert http_date("Sun Nov  6 08:49:37 1994") == datetime(1994, 11, 6, 8, 49, 37, tzinfo=timezone.utc)
    assert http_date("Sun Nov 6 08:49:37 1994") is None                 # date3 is 2DIGIT or SP 1DIGIT
