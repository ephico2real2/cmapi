# Review of #206 and #216: CORS on the API, and the catch-all 500

One second reader, as the rule for a change of who can call the API says: Codex `gpt-6.1-sol`, on an export of `6ec368f`, on 2026-11-14. [`brief.md`](brief.md) has the seven claims. [`reviewer-1-report.md`](reviewer-1-report.md) is its report, unchanged, with the full code of each fix. Fable 5.2 wrote the change, ran each test and ruled.

## What changed after the export, apart from the review

The owner decided on 2026-11-14 (#226) that each instance gets one front door, nginx, with the portal and the API on one origin. So the reviewed default (the origin of `portalUrl`) is gone: CORS is off unless `cors.allowedOrigins` lists an origin. `docs/15`, "The portal's origin and the API", has the decision. #206 closes with #226, not here.

## The rulings

| Finding | Claim | Ruling | Before | After |
|---|---|---|---|---|
| F1 `urlsplit` is not a browser's URL parser. `portalUrl: https://portal.example.com\@evil.example/` gave the origin `https://evil.example`; a host with a space, port 0 and a non-ASCII host passed | C1 | Accepted, with another fix. The fallback to `portalUrl` is removed (see above), and a listed origin is no longer parsed: it must match the exact text form of an origin (lower-case ASCII host, no default port). The reviewer's fix kept the parser and added checks | The values of `test_a_value_that_is_not_an_exact_origin_stops_the_start` marked F1 pass the check | Each is refused |
| F2 An answer for an origin that is not listed, or for no origin, has no `Vary: Origin`. A shared cache can give that copy to the listed origin | C2 | Accepted, with the reviewer's fix (`OriginVaryCORSMiddleware`) | 2 cases of `test_each_answer_varies_on_origin_so_a_cache_keeps_the_copies_apart` fail | Pass |
| F3 The two `BaseHTTPMiddleware` layers turn a cancelled request into `RuntimeError("No response returned.")`, which the catch-all logs as `unhandled`; a client that goes away during the request body becomes a 500 | C5 | Accepted, with the reviewer's fix: both layers are plain ASGI middleware. A cancellation goes on unchanged, a client that went away gets no answer, and an answer that has started is not replaced | `test_a_cancelled_request_goes_on_as_a_cancellation_and_is_not_a_500` fails. The reviewer's disconnect test passes on the old code in the service suite: it stays as a guard | Pass |

Confirmed with no finding: C3 (the API reads no cookie; each write needs the bearer token, so a page of an origin that is not listed changes no state), C4 for each ordinary answer (a problem, a validation refusal, a 404, a 429 and the catch-all 500 have the CORS header), C6 and C7.

## What the review says that is not fixed here

- A failure inside the catch-all itself (for example the logger) still gives Starlette's plain 500 with no CORS header. No test makes that happen.
- Not each write has `Idempotency-Key`: `POST /requests/{id}:cancel` has none. It needs the bearer token, so the conclusion of C3 holds.

## Not proven

A browser, and a real shared cache. The reviewer ran its own scratch tests on a small ASGI application; it did not run the service suite. Fable 5.2 ran the service suite on this Mac. No second reviewer read the fixes after they were applied.
