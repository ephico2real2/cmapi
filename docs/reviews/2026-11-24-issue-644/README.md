# #644 and #646: the framework's own answers are RFC 9457 problems

PR #645. Opus 5.5 (high) implemented it.

- **#644:** the router's own 404 and 405 answers were FastAPI's `{"detail": ...}` JSON. OB1 run 38 found it on CRC.
- **#646:** FastAPI's 400 for a body it could not read, and StaticFiles' 401, were the same JSON. The implementer of #644
  found it.

## The fix

- **The router's 404 and 405.** These are now `not-found` and `method-not-allowed` problems, as `application/problem+json`.
  - The 405 keeps the `Allow` header from #634.
  - A HEAD request gets no content.
  - A route's own `Problem`, such as `object-not-found`, is unchanged. Starlette 0.41.3 checks the status handlers before the
    class handlers (`_exception_handler.py:46-50`).
- **Every other framework `HTTPException`.** One class handler, `framework_refusal`, judges it by its cause:
  - A client that disconnected gets no answer.
  - A body the JSON decoder cannot read gets 422 `validation-failed`, with `json_invalid`. That is cmapi's answer for a body
    that is not JSON (#164).
  - A 400 that has no cause gets 400 `bad-request`.
  - Any other cause or status gets 500 `internal-error`, and the cause is logged.
  - A status below 400 keeps FastAPI's answer.
- **CORS.** CORS now lists `Allow` in `Access-Control-Expose-Headers`.
- **docs/02.** It now says what the JSON decoder accepts. RFC 8259 §8.1's "MUST be encoded using UTF-8" binds the sender, and
  §9 says "A JSON parser MAY accept non-JSON forms".

## Review

- **Reviewer 1:** Codex `gpt-6.2-astra` xhigh (`review/reviewer-1-codex-astra.md`). It asked for changes to #646, and listed 7
  findings.
- **Reviewer 2:** Opus 5.5 high (`review/reviewer-2-opus.md`).
  - **Upheld, with narrowed fixes:**
    - the cause-based 400;
    - the docs/02 sentence, corrected rather than enforced;
    - `Allow` exposed through CORS;
    - the two doc gaps.
  - **Declined:** the wire-level HEAD test. No cmapi mutant needs it.
  - **Moved to their own issues:** the two static-file findings.
    - #649 is High: `/static` reaches CVE-2025-62727, an unauthenticated quadratic Range parse. The coordinator checked the
      advisory with `gh api /advisories` (GHSA-7f5h-v6xp-fcq8).
    - #650: a file that the process can stat but cannot open answers 200.
  - **Mutants:** 9 of 10 were killed. M2 is equivalent: uvicorn's source shows it cannot be told apart.
- **The root cause behind #649.** Starlette 0.41.3 is named in six advisories. #651 upgrades FastAPI and Starlette (PR #654).
- **The coordinator's rulings (Opus 5.5).** Reviewer 2's rulings are accepted. The coordinator applied its patch with
  `patch -p1 -F0`, merged `main`, and relocated 8 docs/14 citations.

## The coordinator's run

The full service suite ran in database `cmapi_wt616`, from 2026-11-24T15:47:01Z to 16:25:14Z. Result: 2663 passed and 19
failed.

The log shows PostgreSQL's "sorry, too many clients already". Other agents' test runs had filled the shared server's 100
connections. A 500 `internal-error` is what the API answers when it cannot get a connection.

The coordinator ran the six failing files again:
- once while another agent's run still held the connections: 15 failed, with the same error;
- once with only 14 of 100 connections in use: **122 passed, 0 failed**.

An earlier run of the full suite, from 14:04Z to 14:50Z, was also crowded. Its two named failing files passed 13 of 13 when
run alone.

`doc-citations.py --check` reports 0 problems.
