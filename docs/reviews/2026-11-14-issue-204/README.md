# Review of #204: the portal's sign-in and its API client

One second reader, as the rule for a change to sign-in and tokens says: Codex `gpt-6.1-sol`, on an export of `30365ce`, on 2026-11-14. [`brief.md`](brief.md) holds the ten claims. [`reviewer-1-report.md`](reviewer-1-report.md) is its report, unchanged, with the full code of each fix. Fable 5.2 wrote the change, ran each test and ruled. A finding stands when its test fails before the fix and passes after it.

Codex could not start a browser in its sandbox (`bootstrap_check_in ... Permission denied (1100)`). It ran its six direct tests there. Fable 5.2 ran each test on this Mac, before and after, in Chromium 156.

## The rulings

| Finding | Claim | Ruling | Before | After |
|---|---|---|---|---|
| F1 The ID token is in the logout URL | C2 | Accepted, with a different fix. Codex removed `id_token_hint`. OpenID Connect RP-Initiated Logout 1.0, section 2, says that the hint is RECOMMENDED, that the issuer "MUST ask the End-User this question if an id_token_hint was not provided", and that issuers "MUST support the use of the HTTP GET and POST methods". So the portal sends the hint in the body of a form POST (`auth.ts`, `signoutRedirect` and `leave`). No token is in a URL, and the issuer asks no question | Direct F1 fails; "sign out" fails | Pass |
| F2 An API that always answers 401 makes a redirect cycle | C5 | Accepted. After one renewal and one more 401, the page shows "Sign-in did not complete." with "Sign in again". A redirect needs a click | `CHECK=F2` fails (timeout: the page never stops) | Pass |
| F3 Two late 401 answers renew two times | C5 | Accepted | Direct F3 fails (2 renewals) | Pass (1) |
| F4 A failed automatic renewal leaves a page that looks signed in | C6 | Accepted. `auth.error` is read before `isAuthenticated`, and the Query cache is cleared when the signed-in page goes | `CHECK=F4` fails | Pass |
| F5 A failed callback leaves `code` or `error` in the address | C3 | Accepted | `CHECK=F5` fails | Pass |
| F6 A call can override `credentials` and `redirect` | C4 | Accepted. The request that carries the token is built with `omit` and `error` | Direct F6 fails | Pass |
| F7 A renewal in flight can store a user after sign-out | C10 | Accepted. Sign-out stops renewal and waits for the one in flight | Direct F7 fails | Pass |
| F8 Discovery can name an `http` endpoint | C7 | Accepted. Each endpoint of the issuer's metadata must be `https` (or `http` on localhost) | Direct F8 fails | Pass |
| F9 An `error` with no `state` starts a new sign-in | C6 | Accepted | `CHECK=F9` fails | Pass |
| F10 `https://api.test?` and `https://api.test#` pass the config check | C7 | Accepted | Direct F10 fails | Pass |

Confirmed with no finding: C1 (PKCE `S256` and a state on each request, as configured), C8 (tabs by `GET /api/v1/me`, no claim read in the browser) and C9 (no sample logic in the portal build). The report lists each place where `oidc-client-ts` 3.5.0 writes to storage with these settings: the sign-in transaction in `sessionStorage`, and the user in memory only.

The saved outputs of each run are in the run folder of OB1, outside git (`review-before-*.log`, `review-after-portal.log`).

## What changed in the code after the review

- `src/portal/auth.ts`: a `PortalUserManager` (one renewal at a time, the metadata check, sign-out by POST).
- `src/api/client.ts`: the replacement token for a refused one, one recovery for all calls, `omit` and `error` on the request itself.
- `src/portal/PortalApp.tsx`: the recovery screen, the callback checks, "Signing out…".
- `src/portal/config.ts`: the empty query and fragment.
- `tests/api/direct.test.mjs` (new, the reviewer's direct tests), `tests/api/portal.test.mjs` (four checks added, two changed), `tests/api/standin.mjs` (logout by POST).

## Not proven

- Each result is against the stand-in issuer. Keycloak's answer to a logout by POST is not measured (#157 stops the container).
- No second reviewer read the fixes after they were applied. The reviewer's own tests and the 15 browser checks pass on them.
