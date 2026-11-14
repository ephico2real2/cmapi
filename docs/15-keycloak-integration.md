# The Keycloak integration

This document says what cmapi creates in Keycloak, and how a caller gets a token that cmapi accepts. It says only what the manifests and the code do. A part that is designed and not built has the words "not built". A result names the cluster it came from.

Keycloak holds the users and their group membership, and maps each group to a cmapi role. LDAP gives the users and the groups to Keycloak through a read-only federation. cmapi defines the names: [`docs/14-authorization.md`](14-authorization.md) has the contract.

**cmapi installs no Keycloak and no LDAP server.** On CRC both exist and other projects use them ([`docs/11`](11-existing-identity-services.md)). cmapi changes only realm `cmapi`, and it has no credential of realm `master`.

## Two steps make the realm

| Step | What | Who runs it | Source |
|---|---|---|---|
| The import | The realm, its settings, the client scopes, the clients, the client roles, the group tree and two service accounts | The RHBK operator, once, from a `KeycloakRealmImport`. An existing realm stays as it is | `deploy/manifests/environments/crc/realm/10-realm-import.yaml` |
| The sync | The user profile, the roles of the two service accounts, the group-to-role mappings, the LDAP federation with its mappers, and the local test users | The Job `cmapi-realm-sync`, with the realm's own client `cmapi-realm-admin` | `cmapi/src/cmapi/tools/realm_sync.py`, `deploy/manifests/environments/crc/realm/20-realm-sync.yaml` |

The import holds no secret. Each client secret is a placeholder that the import reads from Secret `cmapi-realm-secrets`, which `deploy/secrets.sh` writes (`10-realm-import.yaml:1-3`). The steps to run both are in [`docs/13-crc-deployment.md`](13-crc-deployment.md), steps 11 to 21.

## The clients

Nine clients are in the import. The table is read from the file.

| Client | Type | Flow | Used by | Note |
|---|---|---|---|---|
| `cmapi-nonprod` | Confidential, bearer only | None: it issues no token | The API. It is the audience of each token and holds the eight client roles | The audience name is `cmapi-<instance>` |
| `cmapi-portal` | Public | Authorization Code with PKCE (`S256`) | The portal | Redirects: `https://cmapi-portal.apps-crc.testing/` and `https://cmapi-portal.apps-crc.testing/index.html`, exact (see "The redirect URIs of the portal"). The portal's sign-in is built and not yet run on a real Keycloak: see "The portal's sign-in" |
| `cmapi-docs` | Public | Authorization Code with PKCE (`S256`) | Swagger UI at `/docs` | Redirect: `https://cmapi-api.apps-crc.testing/docs/oauth2-redirect`. Session: 1 hour idle, 8 hours at most |
| `cmapi-cli` | Public | Device authorization | The `cmapi` CLI | `offline_access` is optional. The CLI is not built |
| `cmapi-automation` | Confidential | Client credentials | An AI agent or a script, by the client's service account | The service account holds `cmapi-onboarding` only |
| `svc-payments-ci` | Confidential | Client credentials | A sample pipeline | One client for each pipeline |
| `cmapi-directory` | Confidential | Client credentials | The API's people search | Realm-management roles `view-users` and `query-users` only |
| `cmapi-realm-admin` | Confidential | Client credentials | The Job `cmapi-realm-sync`, and the rollback's realm delete | Realm-management role `realm-admin`, in realm `cmapi` only |
| `admin-cli` | Public | None | Nobody | Disabled. Keycloak makes it in each realm, and it would take a password with no secret |

No public client accepts a password. The password of a person from LDAP goes only into Keycloak's own sign-in page.

## The scopes, the mappers and the audience

Each client that gets a token for the API has the default scopes `basic`, `cmapi-identity`, `cmapi-audience`, `roles`, `profile` and `email`.

| Scope | Mapper | Claim in the access token | cmapi reads it as |
|---|---|---|---|
| `cmapi-audience` | Audience | `aud` contains `cmapi-nonprod` | The audience check (`cmapi/src/cmapi/core/auth.py:170-172`) |
| `roles` | Client roles | `resource_access.cmapi-nonprod.roles` | The roles of the caller (`cmapi/src/cmapi/core/identity/claims.py:54`) |
| `cmapi-identity` | Group membership, full path | `groups`, for example `/cmapi/app-cmapi-rbac-requester` | The approving groups (`claims.py:66`) |
| `cmapi-identity` | User attribute `employeeId` | `employee_id` | The requester's record (`claims.py:64`) |
| `cmapi-identity` | User attribute `middleName` | `middle_name` | The requester's record |
| `profile` | Username, first name, last name | `preferred_username`, `given_name`, `family_name` | The username and the record |
| `email` | Email | `email` | The record |
| `basic` | Subject | `sub` | The stable ID of the caller |

`groups` and `employee_id` are in the access token only, not in the ID token. A token for another instance has another audience, so cmapi refuses it with 401.

## The roles and the groups

The eight client roles of `cmapi-nonprod` are `cmapi-viewer`, `cmapi-onboarding`, `cmapi-requester`, `cmapi-approver`, `cmapi-operator`, `cmapi-admin`, `cmapi-auditor` and `cmapi-approval-relay`. The realm has no realm role of cmapi.

The group tree is `/cmapi` with ten groups under it, `app-cmapi-rbac-<role>`, each with its client roles. `docs/14`, "The contract in one table", lists them. The import creates the tree (`10-realm-import.yaml:391-445`), and the sync sets the same mapping from `CMAPI_REALM_GROUPS` (`20-realm-sync.yaml:36-37`), so a later change of the mapping needs no new import.

## The LDAP federation

The sync creates one LDAP provider in realm `cmapi` (`realm_sync.py:202-273`).

| Setting | Value on CRC | Effect |
|---|---|---|
| Edit mode | `READ_ONLY` | Keycloak writes nothing to LDAP |
| Connection | `ldaps://ldaps-ldap-testing.apps-crc.testing:443`, bind user `cmapi-ldap-bind` | TLS with the truststore of the Keycloak CR. The bind user reads only |
| Users filter | `(uid=cmapi.*)` | The realm reads only the 13 test users. No real person is in realm `cmapi` |
| Groups mapper | Filter `(cn=app-cmapi-rbac-*)`, placed under `/cmapi`, read-only | A group in LDAP becomes `/cmapi/<name>`, which has the client roles |
| `employee-id` mapper | LDAP `uidNumber` to the attribute `employeeId` | The claim `employee_id` |
| Sync | Changed users each 15 minutes, a full sync each 24 hours; cache 15 minutes | A change in LDAP reaches a token in 15 minutes at most |
| Guard | `requireSync: true`, `expectUsers: 13` | The Job fails if the first sync reads nobody, or a number other than 13 |

A person's membership changes in LDAP, never in Keycloak. cmapi's own LDAP entries are the ten groups, the bind user and the test users (`docs/11`).

## Token lifetimes

From the realm settings in the import (`10-realm-import.yaml`, under `realm:`).

| Setting | Value |
|---|---|
| Access token | 5 minutes |
| SSO session | 8 hours idle, 12 hours at most |
| SSO session with "remember me" | 7 days idle, 30 days at most |
| Offline session (the CLI) | 30 days idle, 90 days at most |
| Refresh token | Used once: `revokeRefreshToken` with no reuse |
| Swagger UI's client session | 1 hour idle, 8 hours at most |
| Wrong passwords | Temporary lockout after 10 failures, in this realm only, never in LDAP |

cmapi accepts a token until its `exp`, with a leeway of 30 seconds (`auth.py:146`, `:165-166`). It keeps the signing keys for 10 minutes, and keeps verifying with the last good keys when Keycloak does not answer (`auth.py:1-8`).

## How cmapi reaches Keycloak

| Need | URL on CRC | Why |
|---|---|---|
| The issuer in each token | `https://keycloak.apps-crc.testing/realms/cmapi` | The public name. cmapi compares `iss` with it and does not call it |
| The signing keys (JWKS) | `https://keycloak-service.keycloak.svc:8443/realms/cmapi/protocol/openid-connect/certs` | The Service in the cluster, so no pod calls the edge Route |
| The people search | `https://keycloak-service.keycloak.svc:8443`, as client `cmapi-directory` | The same |

Both calls verify Keycloak's certificate against the CA in ConfigMap `cmapi-trust` (`deploy/manifests/environments/crc/30-trust.yaml`). TLS verification is never off.

## From sign-in to a permitted call

Swagger UI uses Authorization Code with PKCE through the public client `cmapi-docs` (`cmapi/src/cmapi/main.py:121-122`, `core/auth.py:189-194`). The portal uses the same flow through `cmapi-portal`: see "The portal's sign-in".

```text
Browser (Swagger UI at /docs)            Keycloak, realm cmapi                 cmapi-api
  1 Authorize: make code_verifier and
    code_challenge = S256(verifier)
  2 GET /protocol/openid-connect/auth -->  client cmapi-docs, challenge
  3                                        sign-in page; the person types the
                                           password here; Keycloak binds to LDAP
  4 <-- redirect to /docs/oauth2-redirect with a code
  5 POST /protocol/openid-connect/token --> code + code_verifier (no client secret)
  6 <-- access token: 5 minutes, aud cmapi-nonprod, roles, groups, employee_id
  7 GET /api/v1/me with Authorization: Bearer ------------------------------->  verify offline with the
                                                                                cached signing keys
  8 <------------------------------------------------------------------------  200, or 401 or 403
                                                                                (docs/14)
```

The sequence figure of Swagger UI is not drawn yet. It follows the first sign-in on CRC, so that it shows what was measured.

## The portal's sign-in

The portal (`cmapi-portal-ui`) signs a person in with Authorization Code and PKCE through the public client `cmapi-portal`. The code is `cmapi-portal-ui/src/portal/auth.ts` and `cmapi-portal-ui/src/api/client.ts`. The libraries are `oidc-client-ts` 3.5.0 and `react-oidc-context` 3.3.1, as `docs/02` names them. The second one declares React 16.14 or later as its peer, and the portal runs it on React 19.3.1.

**What was measured, and where.** `cmapi-portal-ui/tests/api/portal.test.mjs` runs the built portal in a browser against a stand-in issuer and a stand-in API on this Mac (15 checks, Chromium 156 and installed Chrome 157). `tests/api/direct.test.mjs` runs the settings and the client with the real libraries and no browser (8 tests). Codex reviewed the change: `docs/reviews/2026-11-14-issue-204/README.md` has the ten findings and the rulings. The stand-in issuer keeps the rules of the flow: an exact redirect URI, `S256`, a code that works one time, no client secret, and a refresh token that works one time. No sign-in ran on a real Keycloak, on kind or on CRC: realm `cmapi` is not on CRC, and no container runs on this Mac (#157). The API has no CORS headers yet, so the portal cannot call a deployed API from its own host (#206).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="diagrams/portal-sign-in/portal-sign-in.dark.png">
  <source srcset="diagrams/portal-sign-in/portal-sign-in.light.png">
  <img alt="The portal reads config.json, then sends the browser to Keycloak with a PKCE challenge and a state. Keycloak signs the person in and sends a code back. The portal exchanges the code and its verifier for tokens, keeps them in memory, and calls the API with the access token. On a 401 it renews one time with the refresh token. If Keycloak refuses, the person clicks Sign in again." src="diagrams/portal-sign-in/portal-sign-in.light.png">
</picture>

```text
Portal (browser)                          Keycloak, realm cmapi                 cmapi-api
  1 read config.json: apiUrl, issuer, clientId
  2 GET /.well-known/openid-configuration -->
  3 make code_verifier, code_challenge = S256(verifier), state;
    keep them in sessionStorage of this tab
  4 redirect: GET /auth response_type=code, client_id=cmapi-portal,
    code_challenge, code_challenge_method=S256, state, redirect_uri -->
  5                                        sign-in page; Keycloak binds to LDAP
  6 <-- redirect to the page with code and state
  7 POST /token: code + code_verifier (no client secret, no password) -->
  8 <-- access token (5 minutes), refresh token, ID token: kept in memory only
  9 remove code and state from the address
 10 GET /api/v1/me with Authorization: Bearer -------------------------------->
 11 <------------------------------------------------ 200: username, roles, access.permissions
 12 GET /api/v1/requests?limit=25 --------------------------------------------->
 13 <------------------------------------------------ 200, or 403, or 5xx, or 401 (step 14)
 14 POST /token: refresh_token, one time -->   refused: "Sign in again", then step 4
```

The choices, each with its source:

| Choice | What the portal does | Source |
|---|---|---|
| The flow | Authorization Code with PKCE, `S256`. No implicit flow and no password | RFC 10017 (BCP 212, "OAuth 2.0 for Browser-Based Applications", August 2026), section 7.2: "Browser-based clients MUST use the Authorization Code grant type", and section 6.3.2.1 on PKCE |
| Where the tokens are | In the memory of the page. Nothing in `localStorage`, and no token in `sessionStorage`. A reload signs in again through Keycloak's session cookie | RFC 10017, section 8.4 (in-memory storage), section 8.5 ("localStorage does not protect against unauthorized access from malicious JavaScript") and section 8.6 (browser storage is not always encrypted on disk) |
| The verifier and the state | In `sessionStorage` of the tab, removed at the code exchange. The library's own default is `localStorage` (`oidc-client-ts` 3.5.0, `OidcClientSettingsStore`) | RFC 10017, section 6.3.2.2: the application "MUST prevent CSRF attacks against their redirect URI" |
| The address | The code and the state are removed after the exchange (`onSigninCallback`). The view comes back from the state | `react-oidc-context`, `onSigninCallback` |
| Renewal | The library renews before the 5 minutes end. On a 401 the client renews one time, and each waiting call uses that one renewal. When the renewal is refused, or the API answers 401 again, the page shows "Sign-in did not complete." with "Sign in again": no redirect without a click, so an API that always answers 401 cannot make a cycle | The realm rotates refresh tokens with no reuse (`revokeRefreshToken`, `refreshTokenMaxReuse: 0`). RFC 10017, section 6.3.2.3 |
| Where the token goes | To the origin of `apiUrl` only, with no cookie and no redirect followed | `cmapi-portal-ui/src/api/client.ts` |
| Permissions | From `access.permissions` of `GET /api/v1/me`. The browser reads no claim of the token | `docs/02`, "GET /api/v1/me"; `docs/14` |
| Settings | `config.json` at run time: `issuer` and `apiUrl` must be `https` (or `http` on `localhost`), with no user, query or fragment | `cmapi-portal-ui/src/portal/config.ts` |
| The issuer's endpoints | Each endpoint of the discovery document must be `https` (or `http` on `localhost`), or the sign-in stops | `cmapi-portal-ui/src/portal/auth.ts`; review finding F8 |
| Sign-out | The page waits for a renewal in flight, removes the tokens, and sends a form POST to the end-session endpoint with `id_token_hint`, `client_id` and `post_logout_redirect_uri` in the body. No token is in a URL | OpenID Connect RP-Initiated Logout 1.0, section 2: `id_token_hint` is RECOMMENDED, and issuers "MUST support the use of the HTTP GET and POST methods" |

**Not built, and known.**

- RFC 10017, section 6.3.4.3, says that a browser-only OAuth client "is not recommended for business applications", and section 6.1.4.3 strongly recommends a backend for frontend. The design of `docs/02` is the browser-only client, and the portal is built to it. The owner decides if a backend for frontend replaces it.
- Two browser tabs do not share one renewal, as `docs/02` says they do (#208).
- The Content-Security-Policy header comes with the portal's image and its Route, which are not built.

## The redirect URIs of the portal

The client `cmapi-portal` has two redirect URIs, and each is exact: `<portal>/` and `<portal>/index.html`. The portal has one page, and it sends the address of that page with no query and no fragment (`cmapi-portal-ui/src/portal/auth.ts`, `location.origin + location.pathname`). The sign-out returns to the same two addresses (`post.logout.redirect.uris: +`), and `webOrigins: +` gives Keycloak's own CORS answer to the portal's origin only.

Before #205 the two URIs ended in `/*`, and one was `http://localhost:5173/*`.

| Rule | Source |
|---|---|
| No wildcard | RFC 9700 (BCP 240), section 2.1: "authorization servers MUST utilize exact string matching except for port numbers in localhost redirection URIs of native apps". RFC 10017, section 6.3.3.2.1: "Authorization servers MUST require an exact match of a registered redirect URI". Keycloak does not do this by itself: "You can use wildcards at the end of the URL pattern", and "Exclusive redirect URI patterns are typically more secure" (Server Administration Guide, "Valid Redirect URIs"). So the exact list is cmapi's part |
| No `localhost` in the realm of a shared cluster | The exception of RFC 9700 for `localhost` is for native apps. The portal is not one. Each program on a person's computer can listen on `localhost:5173`. With that URI in the realm, a link could start a sign-in of `cmapi-portal` that ends at that program, and Keycloak asks for no consent when the person has a session. A developer uses a realm of their own for a portal on `localhost`, or the stand-in issuer of the portal's suite (`cmapi-portal-ui/tests/api/standin.mjs`) |
| `https` only | The chart refuses a wildcard, a fragment, a space, an upper-case host, and `http` on a host that is not a loopback host with an explicit port, for `portalRedirects` and `docsRedirects` (`deploy/helm/cmapi/templates/keycloak-realm.yaml`). A local realm can list `http://localhost:5173/`. The port is required: Keycloak matches a loopback URI with no port against each port (`RedirectUtils`, Keycloak 26.6.4) |
| The root of the host | The two URIs are for a portal at `https://<portal>/`. A portal on another port or below a path sends another address, and `portalRedirects` must list it |

Tests: `test_crc_public_clients_take_exact_redirect_uris_only` reads the realm of the plain manifests, and `test_review_g_chart.py` renders the chart with each bad URI (9 of the new tests failed before the change, and 12 more cases came from the review, `docs/reviews/2026-11-14-issue-205/`). Keycloak's own clients of the realm (`account`, `account-console`, `security-admin-console`) keep their wildcards: #220. Not measured: Keycloak's refusal of a redirect URI that is not in the list, because no container can run now (#157). Realm `cmapi` exists on no cluster yet, so no realm has the old URIs.

Sources, read on 2026-11-14: <https://www.rfc-editor.org/rfc/rfc9700>, <https://www.rfc-editor.org/rfc/rfc10017>, and `keycloak/keycloak` at `a29205c77840`, `docs/documentation/server_admin/topics/clients/oidc/con-basic-settings.adoc`.

## The portal's origin and the API

**The decision: one origin for the portal and the API, through the front door of the instance. CORS is off unless an origin is listed.**

The owner decided on 2026-11-14 (#226): each instance gets one front door, nginx, behind the Route. It sends `/api/`, `/docs`, `/redoc`, `/openapi.*` and `/problems/` to the API, and `/` to the portal. So the portal's page and the API have one origin, and the browser needs no CORS header for the portal's calls. The front door is not built yet (#226). Until then the portal of #204 runs against its stand-in API only.

| Option | For | Against |
|---|---|---|
| One origin through the front door (the owner's decision) | No CORS policy to keep correct, and no preflight request before each call. One place for TLS, the security headers and the limits. RFC 10017, section 6.3.3.4: "in the extraordinary scenario where the browser-based OAuth client runs in the same origin as the authorization server or resource server, a CORS policy is not needed" | RFC 10017, section 9.4: "it is considered a best practice to avoid deploying more than one application in a single origin". Swagger UI (`/docs`), ReDoc and the portal then share an origin, so a script error in one page reaches the storage of the other. The portal keeps its tokens in memory, not in storage, and #226 sets a Content-Security-Policy at the front door; these two hold that risk |
| CORS on the API, two origins | Section 9.4, as above. The CLI and the pipelines already call the API's own host | A list of origins to keep correct on each instance, and a preflight for each call with `Authorization` |

**CORS stays in the API as an exception, off by default.** A second origin can still be needed: a developer's portal on `http://localhost:5173`, or a portal on another host. RFC 10017, section 6.3.3.4, for that case: "The authorization server and the resource server MUST send necessary CORS headers (defined in [Fetch]) to enable the application to make the necessary cross-origin requests." The code is `cmapi/src/cmapi/core/cors.py`, on Starlette's `CORSMiddleware` (`cmapi/src/cmapi/main.py`). In the Helm values the key is `instance.cors`.

| Part | Value | Why |
|---|---|---|
| Origins | `cors.allowedOrigins` of `instance.yaml`. No key, or an empty list: the API sends no CORS header at all. `portalUrl` does not turn CORS on | The front door makes the portal same-origin. An origin is listed on purpose |
| The form of an origin | `https://host` or `https://host:port`, with a lower-case ASCII host (punycode for another script) and no default port. `http` only for `localhost`, `127.0.0.1` and `[::1]`. Each other value stops the start of cmapi, with the value named: `*`, `null`, a path, a query, a user, upper case, a trailing dot, a space | A typing error must not open the API to more pages than the list says. The value is matched as text, not parsed: a URL parser and a browser do not read each URL the same way (review finding F1) |
| Credentials | `Access-Control-Allow-Credentials` is never sent | The API reads no cookie. The token is in `Authorization`, which a page of another origin does not have |
| Methods | `GET`, `POST`, `PATCH`, `DELETE` | The methods of the API |
| Request headers | `Authorization`, `Content-Type`, `Idempotency-Key`, `If-Match`, `If-None-Match`, `X-Request-Id` | The headers that the API reads. Each call with `Authorization` needs a preflight, so a page of an origin that is not listed cannot send the call at all |
| Response headers a page can read | `ETag`, `Location`, `Retry-After`, `WWW-Authenticate`, `X-Request-Id` | `ETag` is the value of `If-Match` on a change. The others say what to do after a 401, a 429 or a 503, and which log line to find |
| Preflight cache | `Access-Control-Max-Age: 600` | Ten minutes, which is WebKit's limit |
| `Vary: Origin` | On each answer when CORS is on, also on an answer with no CORS header | A shared cache must not give the copy for one origin to another (review finding F2) |

A preflight from an origin that is not listed gets 400 and no CORS header, and the browser does not send the call. A problem (401, 403, 422, 429) from a listed origin has the header. An exception that no handler takes is the problem `internal-error` (500), made inside the CORS middleware, so it has the header and `X-Request-Id` too (#216). Starlette's own 500 is sent outside each middleware and has neither. A cancelled request and a client that went away are not failures of the service: they get no 500 and no `unhandled` log line (review finding F3).

**Measured**, on this Mac with the service suite (`cmapi/tests/service/test_cors.py`, 55 tests). Not measured: a browser against a deployed API, because no container can run now (#157). The review is in `docs/reviews/2026-11-14-issue-206/`.

**Sources**, each read on 2026-11-14: RFC 10017 (BCP 212, August 2026), sections 6.3.3.4 and 9.4, <https://www.rfc-editor.org/rfc/rfc10017>. The Fetch standard, "CORS protocol", <https://fetch.spec.whatwg.org/#http-cors-protocol>: "`*` is not allowed when credentials are involved". Starlette 0.41.3, `starlette/middleware/cors.py` and `starlette/middleware/base.py`, read from the installed package.

## Get a token from a script

Two clients give a token to a script. Each needs its client secret. The URLs are those of CRC.

```bash
export KC=https://keycloak.apps-crc.testing/realms/cmapi/protocol/openid-connect
export CMAPI=https://cmapi-api.apps-crc.testing/api/v1
```

A pipeline uses its own service client with the client credentials grant. It gets no refresh token, so it asks again for each job:

```bash
TOKEN=$(curl -s "$KC/token" \
  -d grant_type=client_credentials \
  -d client_id=svc-payments-ci \
  -d client_secret="$CMAPI_CLIENT_SECRET" | jq -r .access_token)
```

An AI agent or a script signs in as the client `cmapi-automation`, also with the client credentials grant. Its service account holds the role `cmapi-onboarding`, so it can create a namespace and follow its requests. cmapi sees the caller `cmapi-automation` of the kind `service`.

```bash
TOKEN=$(curl -s "$KC/token" \
  -d grant_type=client_credentials -d client_id=cmapi-automation -d client_secret="$AUTOMATION_CLIENT_SECRET" \
  | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/me" | jq .access
```

Keep each secret in a variable that comes from a secret store, and never on a command line that a log records.

### The type of an access token

cmapi accepts a token only when its JOSE header says `typ: at+jwt` or `application/at+jwt`. RFC 9068, section 4: the resource server "MUST verify that the "typ" header value is "at+jwt" or "application/at+jwt"" and must "reject tokens carrying any other value". An ID token and a refresh token have another type, so neither can be a bearer credential.

Keycloak 26 writes the header `typ: JWT` on each access token, ID token and refresh token (a logout token has `logout+jwt`), and `at+jwt` on the access token of a client that has the attribute `access.token.header.type.rfc9068` (`DefaultTokenManager.type`, Keycloak 26.6.4). cmapi's realm sets the attribute on each client that gets a token for cmapi: `cmapi-portal`, `cmapi-docs`, `cmapi-cli`, `cmapi-automation` and each pipeline client. The API's own client (`cmapi-nonprod` on CRC) has it also. That client gets no token, but Keycloak's V1 token exchange writes the header type of the target client (`V1TokenExchangeProvider.setClientToContext`), and cmapi's realm turns no token exchange on. `cmapi-directory` and `cmapi-realm-admin` do not have it, because their tokens go to Keycloak's own admin API. For a realm that was imported before this rule (#184), and for a client that was added by hand, the Job `cmapi-realm-sync` sets the attribute on each client that has the client scope `cmapi-audience`, as a default or an optional scope. The sync does not find a client that gets the audience from a mapper of its own: set the attribute on that client by hand.

A new pipeline client needs the attribute, or cmapi answers 401 "Token is not an access token". For a Keycloak that cannot set it, `auth.acceptLegacyTokenType: true` in `instance.yaml` makes cmapi accept Keycloak's older form also: the header `JWT` together with the claim `typ: Bearer`. A token with no `typ` claim never passes that way. In the Helm chart the setting is the value `auth.acceptLegacyTokenType`.

**An upgrade of a deployment that is older than #184.** The old realm writes the header `JWT`, and the new API refuses it. Use this order:

1. Run the Job `cmapi-realm-sync` of the new image while the old API still serves. The Job needs no API.
2. Wait for the lifetime of an access token (`accessTokenLifespan`, 300 seconds in cmapi's realm), or make each client get a new token. The sync cannot change a token that Keycloak has signed. A refresh after the sync gives a token with the new header.
3. Roll out the new API.

If the API must roll out first, set `auth.acceptLegacyTokenType: true` for that time. Remove the setting when the old tokens have expired. The chart runs the sync as a `post-upgrade` hook, after the new pods start. So a chart upgrade across #184 needs the setting for the upgrade, or the sync run by hand first. The first deployment on CRC (`docs/13`) imports a new realm and runs the sync before the workloads.

### No password grant

No client of realm `cmapi` takes the resource owner password grant. RFC 9700, section 2.4: "The resource owner password credentials grant [RFC6749] MUST NOT be used." The grant gives a person's password to the client, and it cannot ask for a second factor. Each client of the import says `directAccessGrantsEnabled: false`, the disabled `admin-cli` also. For a realm that was imported before this rule (#181), the Job `cmapi-realm-sync` turns the grant off on each client, gives `cmapi-automation` its service account, and removes the local test account `bot-user`.

A person's password goes only into Keycloak's sign-in page. The proofs must still sign in the 13 LDAP test users with no browser. `deploy/oidc-login.py` does it as a browser does: the authorization code grant with PKCE (RFC 7636, S256) through the public client `cmapi-docs`. It sends the password to Keycloak's login form, reads the code from the redirect, and gets the token from the token endpoint. It is for test identities only, and it stops when Keycloak shows another page than the login form. The password comes on standard input:

```bash
printf '%s\n' "$PASSWORD" | deploy/oidc-login.py --issuer "$KC_ISSUER" --client-id cmapi-docs \
  --redirect-uri https://cmapi-api.apps-crc.testing/docs/oauth2-redirect --username cmapi.viewer --cacert "$CMAPI_CRC_CA"
```

## A real token

Not captured yet. The claims of a real access token, with no secret and no signature, come from the Wave 1 run on CRC: one test user from LDAP through `cmapi-docs`, as `deploy/crc-proof.sh` does for each of the 13 with `deploy/oidc-login.py`.

## Proof

| What | Where it ran | Result |
|---|---|---|
| The import and the sync on Keycloak, beside other realms | Community Keycloak 26.6.4 and an LDAP stand-in in containers, by `deploy/tests/realm-test.py` in the CI job `manifests` | Passed on PR #112's head. Read the run of the commit that merged it |
| The same on RHBK 26.6.7 | CRC | Not run yet |
| Each of the 13 test users signs in, and its token has the groups and roles of the table | CRC, `deploy/crc-proof.sh` | Not run yet |
| Sign-in to Swagger UI with PKCE and one Try it out call | CRC, in Chrome | Not run yet. It needs the owner's keychain step (`LOCAL-DEV-TRUST.md`) |
