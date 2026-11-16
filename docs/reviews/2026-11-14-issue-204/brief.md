# Security review: the portal's OIDC PKCE sign-in and its API client (cmapi issue #204)

You are reviewer 1. You work in this folder only: it is an export of the branch, not a repository. Write each finding to `REPORT.md` in this folder as you go. Do not start a container, a kind cluster or any network service other than the loopback servers of the tests.

## The files to read, in full
- `cmapi-portal-ui/src/portal/auth.ts` (the OIDC settings)
- `cmapi-portal-ui/src/portal/config.ts` (the run-time settings and their checks)
- `cmapi-portal-ui/src/api/client.ts` (the bearer token, the 401 path)
- `cmapi-portal-ui/src/api/problem.ts`, `src/api/hooks.ts`
- `cmapi-portal-ui/src/portal/PortalApp.tsx` (the sign-in gate, the session object, sign-out, tabs by permission)
- `cmapi-portal-ui/src/portal/route.ts`, `src/portal/RequestsTab.tsx`, `src/main.tsx`
- `cmapi-portal-ui/tests/api/standin.mjs`, `portal.test.mjs`, `bundle.test.mjs`, `mutants.mjs`
- For the libraries' real behaviour: `cmapi-portal-ui/node_modules/oidc-client-ts/dist/esm/oidc-client-ts.js` and `node_modules/react-oidc-context/dist/esm/*.js` (run `npm ci` in `cmapi-portal-ui` and `npm ci --ignore-scripts` in `cmapi-portal-ui/tools/openapi-types` first).

## The claims. Confirm or refute each one, with the file and the line.
- C1. `auth.ts:oidcSettings`: the authorization request always has `response_type=code`, `code_challenge_method=S256` and a `state`, and no option of the settings can turn PKCE off at run time.
- C2. No access token, refresh token or ID token is written to `localStorage`, `sessionStorage`, IndexedDB, a cookie or a URL by the portal or by the two libraries as configured (`userStore` in memory, `stateStore` in sessionStorage). Name each place where oidc-client-ts 3.5.0 writes to storage with these settings, and what it writes.
- C3. After the callback, the code and the state are out of the address and the history entry (`onSigninCallback`), and `returnHash` cannot be used to navigate to another origin or to run script (it only accepts a fragment that matches `^#[\w/?=&%.~+-]*$`).
- C4. `client.ts:authFetch` sends the bearer token only to the origin of `apiUrl`, with `credentials: "omit"` and `redirect: "error"`. Check how openapi-fetch 0.17.0 passes these options and the custom `fetch`.
- C5. `client.ts`: on a 401 there is exactly one renewal for all concurrent calls, the call is repeated one time, and a second 401 or a failed renewal leads to `signinRedirect`. No loop is possible (for example a renewal that succeeds and an API that always answers 401).
- C6. `PortalApp.tsx:SignIn`: `signinRedirect` cannot be called in a loop (React StrictMode, `auth.error`, a callback URL with `error=`), and a failed silent renewal while the person is signed in does not leave the page in a broken state.
- C7. `config.ts:parseConfig`: a `config.json` cannot make the portal send a token or a sign-in to a non-https origin (except localhost), and `apiUrl` with a path, user, query or fragment is refused.
- C8. `PortalApp.tsx`: a tab shows only with its permission from `GET /api/v1/me`, and the browser reads no claim of the access token anywhere.
- C9. `main.tsx` and `bundle.test.mjs`: the portal build cannot contain the mockup's sample logic.
- C10. Sign-out (`signoutRedirect`) and `queries.clear()`: nothing of the API's data or the tokens stays reachable for the next person.

## For each finding
Give: the claim it breaks, the file and line, why it is wrong, the full code of the fix, and a test in `tests/api/portal.test.mjs` or `bundle.test.mjs` form that fails before the fix and passes after it. Run it: `cd cmapi-portal-ui && npx vite build && node tests/api/portal.test.mjs`. A finding with no failing test is listed as "not proven". Put new files in full in the report. Also list what you checked and found correct, in one line each.

## Not in this review
The other eight tabs, the demo build, the image and Route of the portal, CORS on the API (#206), the wildcard redirect URIs of the realm (#205), two tabs (#208), and the RFC 10017 choice between a browser-only client and a backend for frontend (the design of docs/02 is the browser-only client).
