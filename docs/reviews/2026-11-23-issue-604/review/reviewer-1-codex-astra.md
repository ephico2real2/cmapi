**Request changes on PR #621.** The static mounts now handle the reported cases in #604, #619 and #620, and all four requested mutants were caught. Two defects remain in `http_date`. It accepts invalid dates that can turn a `200` into a `304` or `412`, and its RFC 850 cutoff can put a timestamp in the wrong century.

I reviewed the supplied `base/` and `head/` exports. I made no file changes and ran no Git commands. Line numbers below refer to `head/` unless marked otherwise.

## Findings

### 1. Invalid HTTP dates decide requests, and `:60` compares equal to `:59`

[core/etag.py:104](</Users/olasumbo/gitRepos/workbench/cmapi/review-621/head/cmapi/src/cmapi/core/etag.py:104>) explicitly discards the weekday. [Line 121](</Users/olasumbo/gitRepos/workbench/cmapi/review-621/head/cmapi/src/cmapi/core/etag.py:121>) clamps **every** second from 60 through 99 to 59 and accepts years before 1900. I ran the following cases against `not_modified` with `Last-Modified: Sun, 06 Nov 1994 08:49:37 GMT`.

| Request field | Head result | Required result |
|---|---:|---:|
| `If-Modified-Since: Sun, 06 Nov 1994 08:49:99 GMT` | 304 | 200 |
| `If-Modified-Since: Mon, 06 Nov 1994 08:49:37 GMT` | 304 | 200 |
| `If-Unmodified-Since: Sun, 01 Jan 1899 00:00:00 GMT` | 412 | 200 |

November 6, 1994 was Sunday. RFC 9110 incorporates RFC 5322’s date-component semantics. RFC 5322 says “A date-time specification MUST be semantically valid.” It requires the weekday to agree, gives 1900 as the minimum year, and permits a leap second. Both conditional date fields require an invalid value to be ignored. The promise in `docs/04-api-examples.md:20` and `docs/GLOSSARY.md:56` therefore fails for all three rows. [RFC 9110 §5.6.7](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.7) · [RFC 5322 §3.3](https://www.rfc-editor.org/rfc/rfc5322.html#section-3.3) · [RFC 9110 §13.1.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.3) · [§13.1.4](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.4)

The leap-second probe also returned exactly the same UTC `datetime` for `Sat, 31 Dec 2016 23:59:59 GMT` and `Sat, 31 Dec 2016 23:59:60 GMT`. I retract the crash hypothesis. The observed defect is loss of ordering in the parser. I did not observe Starlette emitting `:60` as a file modification time. [RFC 9110 §5.6.7](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.7) · [Starlette responses.py:320](</Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/starlette/responses.py:320>)

### 2. The RFC 850 cutoff compares only the year

[core/etag.py:112](</Users/olasumbo/gitRepos/workbench/cmapi/review-621/head/cmapi/src/cmapi/core/etag.py:112>) drops the current month, day and time before evaluating the cutoff. RFC 9110 applies the rule to a **timestamp** “more than 50 years in the future”. I froze the clock at `2026-11-23 12:00:00 UTC`. Exactly 50 years ahead correctly resolved to 2076. One second beyond the boundary also resolved to 2076 on head, when it should resolve to 1976. For a file modified in 2026, that century error reverses the `If-Modified-Since` decision. [RFC 9110 §5.6.7](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.7) · [§13.1.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.3)

The existing test at [test_static_preconditions_604.py:140](</Users/olasumbo/gitRepos/workbench/cmapi/review-621/head/cmapi/tests/service/test_static_preconditions_604.py:140>) passes on head. Its offsets are 10 and 60 years, so neither exercises the boundary. It also hardcodes Sunday for both inputs. In the review year, both resolved November 6 dates are Thursdays. I ran the existing test against the weekday-validating fix and confirmed that the hardcoded weekday makes it fail.

### Full fix for findings 1 and 2

Both findings affect the same parser. This is the full replacement I ran in memory, using the existing three compiled patterns. The leap-second value is an ordering key internal to the comparison. Ordinary HTTP dates have no fractional seconds, so it sorts strictly between `23:59:59` and the next midnight without overflowing at year 9999.

```python
from calendar import monthrange


def http_date(value: str) -> datetime | None:
    """UTC comparison key for one HTTP-date, or None for an invalid field."""
    if m := _IMF_FIXDATE.fullmatch(value):
        day, month, year, hour, minute, second = m.groups()
    elif m := _RFC850_DATE.fullmatch(value):
        day, month, short_year, hour, minute, second = m.groups()
        now = datetime.now(timezone.utc)
        limit = now.year + 50
        year = limit - (limit - int(short_year)) % 100
        tail = (_MONTHS.index(month) + 1, int(day), int(hour), int(minute), int(second))
        if year == limit and tail > (now.month, now.day, now.hour, now.minute, now.second):
            year -= 100
    elif m := _ASCTIME_DATE.fullmatch(value):
        month, day, hour, minute, second, year = m.groups()
    else:
        return None

    y, mo, d = int(year), _MONTHS.index(month) + 1, int(day)
    h, mi, s = int(hour), int(minute), int(second)
    if y < 1900 or s > 60:
        return None
    leap = s == 60
    if leap and (h, mi, d) != (23, 59, monthrange(y, mo)[1]):
        return None
    try:
        # HTTP-date has no fractions. Reserve a point between :59 and midnight.
        result = datetime(y, mo, d, h, mi, 59 if leap else s, int(leap), tzinfo=timezone.utc)
    except ValueError:
        return None
    if value[:3] != ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[result.weekday()]:
        return None
    return result
```

These three regression tests failed on head and passed with the replacement. I also checked each invalid-field case individually on head to obtain the results in the table.

```python
from datetime import datetime, timezone
from unittest.mock import patch

from starlette.datastructures import Headers

from cmapi.core import etag


def test_invalid_date_does_not_decide_the_read():
    lm = "Sun, 06 Nov 1994 08:49:37 GMT"
    invalid = [
        ("if-modified-since", "Sun, 06 Nov 1994 08:49:99 GMT"),
        ("if-modified-since", "Mon, 06 Nov 1994 08:49:37 GMT"),
        ("if-unmodified-since", "Sun, 01 Jan 1899 00:00:00 GMT"),
    ]
    for field, value in invalid:
        assert not etag.not_modified(Headers({field: value}), '"x"', lm)


def test_leap_second_order():
    parse = etag.http_date
    assert (parse("Sat, 31 Dec 2016 23:59:59 GMT")
            < parse("Sat, 31 Dec 2016 23:59:60 GMT")
            < parse("Sun, 01 Jan 2017 00:00:00 GMT"))


def test_rfc850_cutoff():
    class Clock(datetime):
        @classmethod
        def now(cls, tz):
            return cls(2026, 11, 23, 12, tzinfo=tz)

    with patch.object(etag, "datetime", Clock):
        assert etag.http_date("Monday, 23-Nov-76 12:00:00 GMT").year == 2076
        assert etag.http_date("Tuesday, 23-Nov-76 12:00:01 GMT").year == 1976
```

For the existing test, replace lines 141–143 with the following. I verified this passes with the fixed parser, along with the existing IMF-fixdate and asctime assertions on lines 144–146.

```python
    for year in (now.year + 10, now.year - 40):
        expected = datetime(year, 11, 6, 8, 49, 37, tzinfo=timezone.utc)
        assert http_date(rfc850_date(expected)) == expected
```

## Confirmed behavior

I used the specified Python and `PYTHONPATH`. For the HTTP runs I used the production `create_app`, mounts, exception handler and Starlette 0.41.3. I substituted two existing export files for the JS bundles because the sandbox refused fixture-directory creation. The four API-route checks used an in-memory identity and empty cluster registry. The production-fixture pytest IDs still outstanding are listed below.

| Verdict | File and run evidence |
|---|---|
| **confirmed — steps 1–4, wildcards and tag comparisons** | `core/etag.py:78–83,95–98,153–169`. All 19 cases from `test_read_preconditions_590_593.py:38–58` passed on both static mounts. Stale `If-Match` beat matching `If-None-Match` with 412. Weak `If-Match` failed, weak `If-None-Match` matched, and standalone `*` behaved correctly in both fields. Repeated tag lines matched the second member. The governing rules are the “strong comparison” and “weak comparison” requirements and the ordered evaluation algorithm. [§13.1.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1) · [§13.1.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.2) · [§13.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.2.2) |
| **confirmed — date precedence and method scope** | `core/etag.py:159–169`, `starlette/staticfiles.py:113–114`. A stale `If-Unmodified-Since` beat matching `If-None-Match` with 412. Adding matching `If-Match` to the stale date gave 200. Nonmatching `If-None-Match` beside a future `If-Modified-Since` gave 200. Equal-date HEAD gave 304 with zero bytes. POST gave 405 before entering the evaluator. The method restriction is enforced by the caller. [§13.1.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.3) · [§13.1.4](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.4) · [§13.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.2.2) |
| **confirmed — ordinary dates, one-second precision, future dates and duplicate lines** | `core/etag.py:39–46,127–131,161,169`, `starlette/responses.py:318–326`. On both mounts, for IMF-fixdate, RFC 850 and asctime, the installed tests exercised one second before, equal, and one second after the file date. `If-Unmodified-Since` gave `412/200/200`, and `If-Modified-Since` gave `200/304/304`. A valid year-9999 date gave 200 and 304 respectively. A comma-list, two date lines, junk and lowercase date text were ignored in the exercised cases. Acceptance of the invalid dates in finding 1 is the exception. [§5.6.7](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.7) · [§13.1.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.3) · [§13.1.4](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.4) |
| **confirmed — all four #590 reads retain their behavior** | `main.py:274–287`, `routers/me.py:78–84`, `plugins/capacity/router.py:219–225`. Each route passed all 19 old HTTP cases, plus a future `If-Modified-Since` and a stale `If-Unmodified-Since`. Both date-only requests returned 200 on every route. None passed a third argument or emitted `Last-Modified`. Only `main.py:53` supplies one. I also compared `base/core/etag.py:94–99` with head for 192 header combinations without `Last-Modified`. Every boolean and serialized 412 agreed. [§13.1.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.3) · [§13.1.4](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.4) |
| **confirmed — Range and If-Range survive the override** | `starlette/staticfiles.py:176–181`, `starlette/responses.py:343–360,433`. On each mount, `bytes=0-2` returned 206 with the correct three bytes and `Content-Range`. Matching `If-Range` by ETag and by date both gave 206. A stale tag gave the full-length 200. Matching `If-None-Match` with Range gave 304, and stale `If-Match` with Range gave 412. [§13.2.2, step 5](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.2.2) |
| **confirmed — the application-level 304 has the required metadata** | `starlette/staticfiles.py:22–36`. Both 200s contained ETag and Last-Modified and omitted Cache-Control. Both 304s carried the same ETag, omitted Last-Modified and Cache-Control, and had zero content bytes. I retract the hypothesis that omission of Last-Modified violates §15.4.5. Its mandatory list is conditional on the corresponding 200 and excludes Last-Modified. Cache-Control is on the list. Starlette’s allowlist includes it. These were ASGI responses, so the run makes no claim about wire-server-added Date. [§15.4.5](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.4.5) |
| **confirmed — the 412 is the application Problem, with one precondition evaluation** | `core/etag.py:157,162`, `main.py:52–53,191–192,205–207,261–263`, `starlette/staticfiles.py:178–181`. Both stale-tag and stale-date failures returned `application/problem+json`, status 412, code `precondition-failed`, the current unquoted `etag`, and the corresponding detail. I installed a raising spy on Starlette’s original method. Per mount, eight existing-file GET/HEAD requests made eight cmapi calls and zero original-method calls. POST and a missing-file GET made zero additional calls and returned 405 and 404 respectively. I retract the double-evaluation hypothesis. [§13.2.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.2.1) · [§13.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.2.2) |
| **confirmed — bounded date matching, UTC, and no exception on the tested odd inputs** | `core/etag.py:39–46,108–124`. Each full-match expression has fixed-width fields or finite alternatives. For 10,000 calls per size, a date with 100, 10,000 and 1,000,000 trailing spaces took `0.0169`, `0.0167` and `0.0162` seconds respectively. All returned `None`. A snowman, year `0000` and five-digit year `10000` returned `None`. Year `9999` parsed. The same asctime string returned `08:49:37+00:00` under UTC, America/Chicago and Asia/Kolkata. I retract the date-regex ReDoS and local-time conversion hypotheses. [§5.6.7](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.6.7) |

## Mutation results

**Confirmed — all four requested mutants were killed.** I changed only in-memory copies of the evaluator and ran the PR’s test functions against both mounted files. All 44 static cases passed on unmodified head and again with the proposed parser fix.

| Mutant | Failing assertion on each mount |
|---|---|
| Remove step 2 | `test_if_unmodified_since_is_step_2`, line 102. The stale date returned 200 instead of 412. |
| Evaluate step 4 before step 3 | `test_if_modified_since_is_step_4`, line 128. The future date overrode the nonmatching ETag and returned 304 instead of 200. |
| Accept the first date of a list | Both date tests, lines 113 and 131. The list incorrectly decided the request. |
| Use strong comparison for `If-None-Match` | Cases 12 and 13 of `test_a_static_file_evaluates_if_match_first`, line 71, from `test_read_preconditions_590_593.py:51–52`. Both returned 200 instead of 304. |

## Pytest IDs for the coordinator

Pytest collected 45 IDs in `tests/service/test_static_preconditions_604.py`. The unmodified `test_a_two_digit_year_more_than_50_years_ahead_is_in_the_past` **passed under pytest**. The remaining **44 IDs need the original fixtures**. A direct pytest attempt failed creating the temporary directory inside the export. A separate PostgreSQL connection attempt to `127.0.0.1:55432` returned `Operation not permitted`. The relevant fixtures are at `test_api_docs.py:42–50` and `conftest.py:424–437,469–473`.

The following is the exact parameterized ID list in compact form. Prefix every ID with `tests/service/test_static_preconditions_604.py::`. Expand each `PATH` once as `/static/swagger/swagger-ui-bundle.js` and once as `/static/redoc/redoc.standalone.js`.

```text
test_a_static_file_evaluates_if_match_first[if_match0-if_none_match0-412-PATH]
test_a_static_file_evaluates_if_match_first[if_match1-if_none_match1-412-PATH]
test_a_static_file_evaluates_if_match_first[if_match2-if_none_match2-412-PATH]
test_a_static_file_evaluates_if_match_first[if_match3-if_none_match3-304-PATH]
test_a_static_file_evaluates_if_match_first[if_match4-if_none_match4-304-PATH]
test_a_static_file_evaluates_if_match_first[if_match5-if_none_match5-412-PATH]
test_a_static_file_evaluates_if_match_first[if_match6-if_none_match6-412-PATH]
test_a_static_file_evaluates_if_match_first[if_match7-if_none_match7-200-PATH]
test_a_static_file_evaluates_if_match_first[if_match8-if_none_match8-200-PATH]
test_a_static_file_evaluates_if_match_first[if_match9-if_none_match9-200-PATH]
test_a_static_file_evaluates_if_match_first[if_match10-if_none_match10-200-PATH]
test_a_static_file_evaluates_if_match_first[if_match11-if_none_match11-200-PATH]
test_a_static_file_evaluates_if_match_first[if_match12-if_none_match12-304-PATH]
test_a_static_file_evaluates_if_match_first[if_match13-if_none_match13-304-PATH]
test_a_static_file_evaluates_if_match_first[if_match14-if_none_match14-412-PATH]
test_a_static_file_evaluates_if_match_first[if_match15-if_none_match15-412-PATH]
test_a_static_file_evaluates_if_match_first[if_match16-if_none_match16-200-PATH]
test_a_static_file_evaluates_if_match_first[if_match17-if_none_match17-200-PATH]
test_a_static_file_evaluates_if_match_first[if_match18-if_none_match18-304-PATH]
test_the_cases_of_issue_604[PATH]
test_if_unmodified_since_is_step_2[PATH]
test_if_modified_since_is_step_4[PATH]
```

Codex session ID: 01a20b04-ccfd-7571-a469-6b2e92409bf5
Resume in Codex: codex resume 01a20b04-ccfd-7571-a469-6b2e92409bf5
