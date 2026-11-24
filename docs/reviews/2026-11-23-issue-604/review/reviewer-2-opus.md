# Reviewer 2 (Opus 5.5, high) on PR #621: head 447234e, base 78ec33e

Closes #604, #619 and #620. Reviewer 1 (Codex gpt-6.2-astra xhigh) asked for changes: two defects in `http_date`. I read its
report, the diff and the RFCs in full. I checked each finding with a test that fails on head and passes on my patched copy
(`r2/`). Every result below is from `cmapi_r2_621` on the local PostgreSQL 16 at `127.0.0.1:55432`. No cluster was used.

**Verdict:** request changes. Both of reviewer 1's findings stand. I adopt its microsecond ordering key and its leap-second
check, and narrow its RFC 850 fix. I also correct the existing test that the fix breaks, and two docs.
The patch is `r2-outputs/fix.diff`. It applies to 447234e with `patch -p1 -F0` from the repository root.

## Sources, fetched 2026-11-24 (UTC)

The RFC text files were fetched with `curl` into `r2-outputs/rfc/`.

- RFC 9110, https://www.rfc-editor.org/rfc/rfc9110.txt
  - §5.6.7: "A recipient that parses a timestamp value in an HTTP field MUST accept all three HTTP-date formats."
  - §5.6.7: "time-of-day = hour ":" minute ":" second ; 00:00:00 - 23:59:60 (leap second)"
  - §5.6.7: "The semantics of day-name, day, month, year, and time-of-day are the same as those defined for the Internet
    Message Format constructs with the corresponding name ([RFC5322], Section 3.3)."
  - §5.6.7: "Recipients of a timestamp value in rfc850-date format, which uses a two-digit year, MUST interpret a timestamp
    that appears to be more than 50 years in the future as representing the most recent year in the past that had the same
    last two digits."
  - §5.6.7: "Recipients of timestamp values are encouraged to be robust in parsing timestamps unless otherwise restricted by
    the field definition." The two date fields do restrict it:
  - §13.1.3: "A recipient MUST ignore the If-Modified-Since header field if the received field value is not a valid
    HTTP-date, the field value has more than one member, or if the request method is neither GET nor HEAD."
  - §13.1.4: "A recipient MUST ignore the If-Unmodified-Since header field if the received field value is not a valid
    HTTP-date (including when the field value appears to be a list of dates)."
  - §13.1.4: "An origin server that evaluates an If-Unmodified-Since condition MUST NOT perform the requested method if the
    condition evaluates to false."
  - §13.2.2: "A recipient cache or origin server MUST evaluate the request preconditions defined by this specification in
    the following order". Steps 1 to 4 are If-Match, If-Unmodified-Since, If-None-Match and If-Modified-Since.
- RFC 5322 §3.3, https://www.rfc-editor.org/rfc/rfc5322.txt
  - "The year is any numeric year 1900 or later."
  - "A date-time specification MUST be semantically valid. That is, the day-of-week (if included) MUST be the day implied
    by the date, the numeric day-of-month MUST be between 1 and the number of days allowed for the specified month (in the
    specified year), the time-of-day MUST be in the range 00:00:00 through 23:59:60 (the number of seconds allowing for a
    leap second; see [RFC1305])".
- What other servers do, read from their source on the same date:
  - nginx `src/core/ngx_parse_time.c` skips the day name and refuses `sec > 59`.
  - Go `src/time/format.go`: "The day of the week is checked for syntax but it is otherwise ignored."

  So the day-name check is stricter than nginx and Go. The RFC chain above still makes it a MUST for these two fields, and it
  costs one line. The coordinator may rule otherwise. The finding table shows what changes if the check is dropped (M1).

## Reviewer 1's findings

| # | Reviewer 1's claim | Ruling | Evidence |
|---|---|---|---|
| 1a | A second of 61 to 99 is read as :59, so an invalid date decides the read | **Confirmed** | Probe row R1-1a: head 304, RFC 200. Pytest `test_if_modified_since_is_step_4` (`NOT_VALID_FUTURE`) fails on head |
| 1b | The day name is not checked, so `Mon, 06 Nov 1994` decides the read | **Confirmed**, in all three formats | Probe rows R1-1b and "wrong weekday rfc850/asctime": head 304 or 412, RFC 200. Pytest `NOT_VALID_PAST`/`NOT_VALID_FUTURE` |
| 1c | A year before 1900 is accepted, so `If-Unmodified-Since: ... 1899` answers 412 | **Confirmed** | Probe row R1-1c: head 412, RFC 200. Pytest `test_if_unmodified_since_is_step_2` fails on head |
| 1d | `:60` compares equal to `:59`, so the parser loses the order | **Narrowed** | No reachable decision changes. Last-Modified comes from Starlette's `formatdate`, which never writes :60, and no whole second lies between :59 and :60. Probe "leap" rows give the RFC answer on head too. I still adopt reviewer 1's key, which costs nothing and drops that dependency |
| 1e | (reviewer 2) `:60` before 23:59 on a month's last day is accepted | **New, confirmed** | Probe rows "R2 :60 not at 23:59" and "leap mid-month": head 304, RFC 200. Reviewer 1's code fixes it, but its report does not name it |
| 2 | The RFC 850 cutoff compares the year only | **Confirmed**, fix **narrowed** | Clock frozen at 2026-11-23T12:00:00Z: `Tuesday, 23-Nov-76 12:00:01 GMT` is 2076 on head and 1976 by the RFC. Pytest `test_more_than_50_years_ahead_is_to_the_second` fails on head |
| 2b | The existing test hardcodes `Sunday`, so it fails with the day-name check | **Confirmed** | `original-test-under-fix.txt`: both inputs parse to `None` under the fix (6 Nov 2036 and 6 Nov 1986 are Thursdays) |
| - | Confirmed behaviour table (steps 1 to 4, Range, 304 metadata, the 412 Problem, one evaluation, ReDoS) | **Accepted, not rerun** | I checked the parts my patch touches. Pytest reran the 44 static cases and the 590 table on the patched copy |
| - | Four mutants of the evaluator killed | **Accepted** | Not rerun. My own mutants of the parser fix are below |

### Narrowing 2: keep head's century rule and compare to the second

Reviewer 1 replaced head's "this century, else the one before" with a sliding window, `limit - (limit - yy) % 100`.
Today both rules give the same year for every two-digit value. They differ only after 2050. In 2060, `05` is 2005 on head
and 2105 on reviewer 1's rule. Section 5.6.7 decides only the "more than 50 years in the future" case, and both rules meet
it. A fix changes only what it fixes, so I keep head's rule and change the comparison from the year to the whole timestamp.
That is one condition:

```python
        if (year, _MONTHS.index(month) + 1, int(day), int(hour), int(minute), int(second)) > \
                (now.year + 50, now.month, now.day, now.hour, now.minute, now.second):
            year -= 100
```

Comparing to `now.second` without its microseconds is exact. An HTTP-date has whole seconds, so `t > now + 50y` holds
exactly when `t > floor(now) + 50y`. The tuple form also needs no "50 years after 29 February", which `datetime.replace`
cannot build.

### Narrowing: the seconds check

Reviewer 1's `s > 60` is redundant. A second from 61 to 99 is not `leap`, so `datetime()` raises `ValueError` and the
function returns `None`. Mutant M3 shows the tests still catch a return of head's clamp.

## Final code

`core/etag.py`: two lines above `if_match_tags` (`from calendar import monthrange`, and `_DAYS` with `_DAY_NAME` built from
it), and this `http_date`:

```python
def http_date(value: str) -> datetime | None:
    """The instant, in UTC, of a value that is exactly one valid HTTP-date (RFC 9110 section 5.6.7), or None.

    Section 5.6.7 gives day-name, day, month, year and time-of-day the semantics of RFC 5322 section 3.3, where "A date-time
    specification MUST be semantically valid": the day name is the day of the date, "The year is any numeric year 1900 or
    later", and the time is 00:00:00 to 23:59:60. So a wrong day name, 31 Feb, 1899, 25:00:00 or :61 is no HTTP-date, and
    13.1.3 and 13.1.4 ignore it. A leap second, :60, is the last second of a month only, and is kept apart from :59: one
    microsecond after it, as an HTTP-date has whole seconds, so it sorts before the next midnight, even in year 9999.

    A two-digit year of an rfc850-date is in this century, unless the timestamp is then more than 50 years ahead, to the
    second: then it is the century before ("MUST interpret a timestamp that appears to be more than 50 years in the future
    as representing the most recent year in the past that had the same last two digits")."""
    if m := _IMF_FIXDATE.fullmatch(value):
        day, month, year, hour, minute, second = m.groups()
    elif m := _RFC850_DATE.fullmatch(value):
        day, month, two_digits, hour, minute, second = m.groups()
        now = datetime.now(timezone.utc)
        year = now.year - now.year % 100 + int(two_digits)
        if (year, _MONTHS.index(month) + 1, int(day), int(hour), int(minute), int(second)) > \
                (now.year + 50, now.month, now.day, now.hour, now.minute, now.second):
            year -= 100
    elif m := _ASCTIME_DATE.fullmatch(value):
        month, day, hour, minute, second, year = m.groups()
    else:
        return None
    y, mo, d, h, mi, s = int(year), _MONTHS.index(month) + 1, int(day), int(hour), int(minute), int(second)
    leap = s == 60
    if y < 1900 or (leap and (d, h, mi) != (monthrange(y, mo)[1], 23, 59)):
        return None
    try:
        instant = datetime(y, mo, d, h, mi, 59 if leap else s, int(leap), tzinfo=timezone.utc)
    except ValueError:                                  # 31 Feb, 24:00:00, :61 to :99
        return None
    return instant if value[:3] == _DAYS[instant.weekday()] else None
```

`value[:3]` works for all three formats because each long day name starts with its short one.

The tests in `test_static_preconditions_604.py`, all in `fix.diff`:

- `NOT_VALID_PAST` is added to the ignored values of `test_if_unmodified_since_is_step_2`. It holds a wrong day name in
  each format, `:99`, `:60` at 08:49 and 1899. On head each of these answers 412.
- `NOT_VALID_FUTURE` is added to `test_if_modified_since_is_step_4`. It holds a wrong day name, `:99` and `:60` on 15
  December, all in 9999. On head each of these answers 304.
- `test_a_two_digit_year_more_than_50_years_ahead_is_in_the_past` builds its dates with `rfc850_date(expected)`, so they have
  the right day names. This is reviewer 1's change.
- `test_more_than_50_years_ahead_is_to_the_second` is new. It freezes the clock at 2026-11-23 12:00:00 and checks exactly 50
  years, one second past, 31 Dec 76, 75 and 99.
- `test_a_leap_second_is_after_59_and_before_the_next_day` is new. It covers the three formats, 30 June, year 9999 with no
  overflow, and `23:58:60`, `30 Dec 23:59:60` and `:61`, each refused.

## Runs

The gate (`r2-outputs/gate.sh`) ran before each pytest run. Its line, with the 1-minute load, heads each output.

| File | What | Result |
|---|---|---|
| `r2-outputs/probe-before.txt` | 26 decision and parse rows on the head parser | 9 rows differ from the RFC |
| `r2-outputs/probe-after.txt` | The same rows on the patched parser | 0 differ |
| `r2-outputs/pytest-before.txt` | `test_static_preconditions_604.py` (r2 tests) on the head parser | 6 failed, 41 passed. The failures are both paths of step 2 and step 4 (the `NOT_VALID_*` values), the cutoff test and the leap-second test. Gate load 10.14 |
| `r2-outputs/pytest-after.txt` | 22 files that touch `core/etag.py`, including `test_api_standard.py`, `test_api_docs.py`, `test_api_samples.py`, 590/593, 581, 571 and 604 | 671 passed in 564 s. Gate load 9.35. This ran the code with reviewer 1's redundant `s > 60`, which I then removed |
| `r2-outputs/pytest-after-final.txt` | The same 22 files on the final code | 671 passed in 549 s. Gate load 8.44 at the start and 8.61 at the end |
| `r2-outputs/mutants.txt` | 8 mutants of the fix against `test_static_preconditions_604.py` | 8 of 8 killed: M1 day name, M2 1900 floor, M3 head's :59 clamp, M4 :60 at any time, M5 :60 on any day, M6 :60 equal to :59, M7 head's year-only cutoff, M8 exactly 50 years as the past. Gate load 7.78. The file was restored and is byte-identical to the patch |
| `r2-outputs/doc-citations.txt` | `scripts/doc-citations.py --check` on head and on r2, through `run-doc-citations.py`, which lists files from disk because the export is no git repository | 0 problems on both |
| - | `scripts/api-examples-doc.py --check` on r2 | exit 0 |

## What reviewer 1 missed

1. **`:60` outside the last second of a month.** Head reads `Sun, 06 Nov 1994 08:49:60 GMT` as :59, and so lets it decide a
   request (304 on head, 200 by the RFC). Reviewer 1's code refuses it, but its report and tests do not name the case. My
   `NOT_VALID_PAST`, `NOT_VALID_FUTURE` and the leap-second test cover it, and mutants M4 and M5 confirm they catch it.
2. **The sliding window changes behaviour beyond the finding**, after 2050 (see "Narrowing 2"). This is not adopted.
3. **`s > 60` is dead code** once `min(s, 59)` is gone (see "Narrowing: the seconds check").
4. **The docs promise what head does not do.** docs/04 ("Conditional reads") and the glossary said only "not one
   HTTP-date". They now say what a valid one is. The glossary sentence "so a list of dates or a second line is (#619, #620)"
   loses its verb in the middle of the row, and now reads "and so are a list of dates and a second line".
5. **The docs/02 citation of `if_match_tags` is off by one on head.** It says `etag.py:86-97`, but the function is 86-98.
   With the two new lines it is 88-100. This is a docs/02 change, so the passage is in `r2-outputs/LIVE-DOC-EDITS.md` for the
   live doc.

No defect was found outside this PR.

## Who wrote what

Reviewer 2 (Opus 5.5, high) wrote every line of `fix.diff`. Reviewer 1's parser was the starting point for the leap-second
key and check and the day-name check. The test change for `test_a_two_digit_year...` is reviewer 1's, as written.
