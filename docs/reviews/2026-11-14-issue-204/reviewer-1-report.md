# Security review — reviewer 1 — cmapi #204

Scope: this branch export only; no containers, clusters, or services except the tests’ loopback servers. All requested application and test files were read in full. Installed with `npm ci` and `npm ci --ignore-scripts` in the generator directory; inspected the installed oidc-client-ts 3.5.0, react-oidc-context 3.3.1, and openapi-fetch 0.17.0 implementations. TokenSave context/status/read were attempted; this export has no initialized graph, so direct source inspection was used.

Original line numbers refer to the supplied export. Application paths below are relative to `cmapi-portal-ui/`; library paths are relative to its `node_modules/`. This is a review deliverable: candidate changes were applied temporarily for validation and the original source/test files are restored afterward. The complete replacement files are in the appendix.

Six findings have a failing-before/passing-after direct regression in `tests/api/portal.test.mjs`; four browser-only findings are **not proven** because Chromium cannot start under the sandbox. The complete requested browser suite did not pass. No real Keycloak behavior is claimed.

| Claim | Verdict on supplied export | Evidence |
|---|---|---|
| C1 | Confirmed as configured; not an immutable library guarantee | auth.ts:23-30; library :1017,1664-1699,1928-1960. Config does not expose disablePKCE or extraQueryParams. The library does expose disablePKCE; source/settings mutation can disable it, as mutants.mjs:15 demonstrates. |
| C2 | Refuted | F1; storage inventory below. No access/refresh token persistence was found in the configured stores. |
| C3 | Confirmed for successful callbacks and fragment safety; refuted for failures (not proven) | auth.ts:14-16,44; F5. |
| C4 | Current hook calls have the stated options; the reusable client's invariant is refuted | client.ts:26-30,49-54; F6. |
| C5 | Refuted | F3 proven; F2 redirect cycle not proven. Normal API retry is bounded to two sends per call. |
| C6 | Initial StrictMode and state-bearing error guards are correct; recovery/other loop claims refuted by source (not proven) | PortalApp.tsx:85-94; F4, F9. |
| C7 | Direct HTTPS/local scheme, user, nonempty query/fragment, and effective root-path checks hold; absolute claim refuted | config.ts:22-36,50-55; F8, F10. Trust in the HTTPS issuer remains necessary. |
| C8 | Confirmed for implemented Requests/permission-bearing tabs and access-token opacity; not literally for all tabs | PortalApp.tsx:34-43,104-106,128-129; hooks.ts:39-49. Null-permission placeholders always show after /me; the other eight tabs are excluded from this review. |
| C9 | Confirmed for this production build | main.tsx:10-12; bundle.test.mjs:14-22; static bundle assertions passed for all 38 sample names. This is not a universal proof against arbitrary future sample code. |
| C10 | Refuted | F7 proven; F1 URL exception. Normal userStore removal and Query cache clearing exist, but do not serialize ongoing renewal. |

## F1 — ID token sent in the logout URL (C2; also limits C10)

**Proven by direct regression (F1 fails on original and passes with fix).** `cmapi-portal-ui/src/portal/PortalApp.tsx:116` calls `signoutRedirect()` with defaults. `node_modules/oidc-client-ts/dist/esm/oidc-client-ts.js:3421-3424` supplies the stored ID token, and `:1779-1780` appends `id_token_hint` to the logout query. This puts identity information in a navigation URL (and potentially issuer access logs/history). The existing test explicitly requires this at `tests/api/portal.test.mjs:357`. An ID token is not an API bearer credential, and this is standard logout behavior, but the absolute no-token-in-any-URL claim is false.

## F2 — Persistent API 401s can cause an endless redirect cycle (C5)

**Not proven:** source evidence and a full browser regression are supplied, but its assertions could not run. `src/api/client.ts:40-45` bounds retries per call, but calls `session.signIn()` after the second 401. `src/portal/PortalApp.tsx:109` redirects unconditionally. A valid issuer session issues another token, callback remounts `/me`, and an API that keeps returning 401 starts the cycle again. The in-memory renewal promise and SignIn ref do not survive navigation. A user-visible stop with an explicit sign-in action is needed.

## F3 — Late concurrent 401 responses trigger additional renewals (C5)

**Proven by direct regression (F3 fails on original and passes with fix).** `src/api/client.ts:22` resets the shared promise as soon as renewal completes; `:40` never checks whether the token used by the failed call has already been replaced. Two calls sent with token A can receive their 401s on opposite sides of the renewal’s completion and rotate twice. This is distinct from two genuinely separate token-expiry episodes.

## F4 — Silent-renewal errors are hidden behind the authenticated branch (C6)

Not proven in a browser in this environment. `src/portal/PortalApp.tsx:92-93` renders SignedIn before checking `auth.error`. react-oidc-context’s ERROR reducer (`dist/esm/react-oidc-context.js:47-54`) retains the previous `isAuthenticated` and user; it does not subscribe to AccessTokenExpired at all (`:232-259`). A rejected automatic renewal leaves a signed-in-looking page with cached API data and no recovery control, even after expiry. An eventual API call can recover through the client’s null-return path, but idle users do not get a recovery UI.

## F5 — Failed callback leaves authorization parameters in the address/history (C3)

Not proven in a browser in this environment. `src/portal/auth.ts:44` only runs after a successful callback: react-oidc-context `:207-217` calls it after awaiting `signinCallback()`, not in finally. A token endpoint failure or an error callback leaves code/state or error/state in the address and current history entry. The fragment validation itself is safe.

## F6 — Request options can override cookie/redirect safety (C4, defense in depth)

**Proven by direct regression (F6 fails on original and passes with fix).** `src/api/client.ts:28-30` clones the incoming Request without enforcing its security properties. The settings at `:53-54` are defaults; openapi-fetch `dist/index.mjs:70-81` spreads per-call init after base options and passes that Request to custom fetch (`:123`). A caller using `{ credentials: "include", redirect: "follow" }` bypasses both properties. Current hooks do not pass these overrides, and this is not an external attacker-controlled option today; the client’s claimed invariant is nevertheless not enforced at the bearer insertion boundary. Origin checking before insertion is correct.

## Execution constraint

`cd cmapi-portal-ui && npx vite build && node tests/api/portal.test.mjs` was run on the original export. Vite succeeded; Chromium launch failed before any browser assertions with `bootstrap_check_in ... Permission denied (1100)` / `mach_port_rendezvous_mac.cc:159`. No approval bypass or additional service was attempted. Browser-dependent findings remain **not proven** unless a later run succeeds. Direct Node regression results are reported separately.

## F7 — A renewal already in flight can restore the user after sign-out (C10)

**Proven by direct regression (F7 fails on original and passes with fix).** `src/portal/PortalApp.tsx:113-116` clears Query and starts logout, but never stops or joins silent renewals. oidc-client-ts `:3426` removes the user; a prior `_useRefreshToken` can subsequently execute `:3161-3163`, storing fresh tokens and raising UserLoaded. That can remount SignedIn with the previous identity while logout is pending or has failed. `queries.clear()` does not serialize the OIDC lifecycle. Stop new renewals, join the one already running, remove its result, then start logout. Repeated sign-out requests must share that operation.

## F8 — HTTPS issuer validation does not validate discovered endpoints (C7, qualified)

**Proven by direct regression (F8 fails on original and passes with fix).** `src/portal/config.ts:33-35,55` validates the configured issuer, but `src/portal/auth.ts:23` supplies only authority, leaving discovery trusted. oidc-client-ts `:878-880,907-918,1931` consumes arbitrary discovered endpoint URLs without validating their schemes. A config selecting an HTTPS issuer whose metadata advertises `http://insecure.example/auth` sends sign-in there; an HTTP token endpoint receives code/verifier or refresh tokens. This requires control of the selected issuer/discovery response; it is not a bypass of the HTTPS check for the literal apiUrl or issuer fields. If C7 assumes honest issuer metadata, that narrower claim holds. Explicit endpoint validation is needed for the unconditional wording.

## F9 — An issuer error without state is treated as a fresh page (C6)

**Not proven** in a browser. `src/portal/PortalApp.tsx:88` relies on `hasAuthParams()`. react-oidc-context `:76-85` requires a truthy state and a code/error; `?error=access_denied` does not qualify, so initialization finds no user and SignIn automatically redirects. If an issuer keeps answering error without state, each navigation creates a new asked ref and repeats. This is a malformed issuer response, not the normal state-bearing error path. Recognize incomplete callback parameters, scrub them and require an explicit recovery action.

## F10 — Empty query/fragment delimiters bypass config checks (C7; low, configuration correctness)

**Proven by direct regression (F10 fails on original and passes with fix).** `src/portal/config.ts:35-36` tests URL.search/hash truthiness but returns the original string. `new URL("https://api.test?").search` and `new URL("https://api.test#").hash` are empty, so both values are accepted. openapi-fetch concatenates the API path onto that raw base URL; the resulting request goes to `/` with the API path in its query or fragment. It stays on the API origin, so this is not cross-origin token disclosure. Reject delimiters even when their value is empty.

## Configured storage inventory (C2)

The following are all configured writes in oidc-client-ts 3.5.0; a WebStorageStateStore uses the `oidc.` prefix (`:941-952`).

| Write site | Destination/key | Contents and lifecycle |
|---|---|---|
| OidcClient.createSigninRequest, library :1963-1965 | sessionStorage, `oidc.<state-id>` | SigninState JSON (:1583-1601): id, data `{hash: location.hash}`, created epoch seconds, request_type `si:r`, code_verifier, authority, client_id, redirect_uri, scope `openid`, extraTokenParams `{}`, response_mode `query`. Undefined url_state/client_secret/skipUserInfo/nonce fields are omitted. The generated challenge is not serialized. No access, refresh or ID token. An iframe fallback without a refresh token writes an analogous `si:s` transaction; no ID hint by default (:3140-3143). |
| OidcClient.readSigninResponseState, :1975, called by processSigninResponse :1983-1985 | sessionStorage removal | Removes transaction before token exchange/validation; failed exchanges also consume the matching transaction. Initial UserManager.signinCallback reads it without removing (:3189-3193). Abandoned transactions can remain until stale-state cleanup removes them after 15 minutes on a later request (:985,1526-1553,1963). Tab close ends sessionStorage. |
| UserManager.storeUser, :3535-3543; called by _buildUser :3329 and _useRefreshToken :3162 | **InMemoryWebStorage only**, `oidc.user:<issuer>:<clientId>` | User JSON (:2347-2358): id_token, session_state, access_token, refresh_token, token_type, scope, profile, expires_at. Writes occur at initial login and each successful renewal; removal is at removeUser/logout. These serialized tokens never go to the browser's Web Storage under the supplied userStore. |
| OidcClient.createSignoutRequest, :2128-2132 | sessionStorage **only if sign-out state/url_state is supplied** | Base State JSON (:1512-1520): id, data, created, request_type, url_state. **No write on the portal's current argument-free signoutRedirect**, because SignoutRequest only creates state when state_data or url_state exists (:1785-1794). No tokens in this JSON. |

There are no other configured persistent writes: DPoP/IndexedDB code (:3597-3645) is inactive because dpop is unset; neither library writes cookies here; react-oidc-context keeps its user/error state in React memory (:17-54,265-272). Its navigation wrappers swallow exceptions and return null (:172-190), which is why the portal's actual failed `signinSilent` normally reaches client.ts's no-fresh-token branch instead of throwing out of renewOnce. Token endpoint POSTs carry tokens as request bodies, which is distinct from storing them. **Logout's ID-token query is the C2 exception (F1).** The issuer's own cookies, browser internals and server logs are not under these stores' control.

## What was checked and found correct

- C1: auth.ts:27-30 and library :1664-1699 produce code/S256/state; no PortalConfig option is spread into OIDC settings.
- C2 (storage portion): auth.ts:33,36 routes tokens to memory and transactions to sessionStorage; the direct initial-login/transaction-removal test passes on both versions.
- C3 (success/fragment portion): auth.ts:14-16,44 uses replaceState and a literal fragment; even `#//other.test` and encoded punctuation remain same-origin fragments in the direct test.
- C4 (current callers/origin): client.ts:26 checks the actual constructed Request URL before inserting a bearer; hooks.ts:45,59 pass only signal/parameters; default omit/error reach the custom fetch through openapi-fetch :70-81,123 and survive Request.clone.
- C5 (per-call bound): client.ts:37-46 sends at most the first attempt plus one repeated attempt; no recursion occurs inside authFetch itself.
- C6 (initial guard): PortalApp.tsx:85-91 uses a ref plus loading/navigator/error guards; react-oidc-context :198-231 independently guards callback initialization against StrictMode effect replay.
- C6 (normal error callback): hasAuthParams requires code/error and state; with a state-bearing error, AuthProvider sets auth.error and the SignIn effect does not redirect automatically.
- C7 (ordinary values): config.ts:22-36,50-55 rejects nonlocal HTTP, other schemes, credentials, populated queries/fragments and effective API paths; localhost/127.0.0.1/[::1] HTTP exceptions pass direct tests.
- C8 (implemented Requests tab): PortalApp.tsx:39,128-129 takes requests:read from /me; hooks.ts:39-49 obtains /me; no portal code decodes access-token claims; the library decodes ID tokens, not the access token, at :1469-1495.
- C8 (boundary): PortalApp.tsx:38,41-42,129 deliberately admits needs:null placeholders; this does not establish permissions for the excluded eight tabs.
- C9: main.tsx:10-12 is a Vite build-time constant branch; bundle.test.mjs:14-22 passed its static assertions for 38 sample names and the two logic markers.
- C10 (ordinary cleanup): PortalApp.tsx:101,115 creates a QueryClient per SignedIn mount and clears it on explicit sign-out; library :3426,2971-2975 removes the memory user and cancels token timers, apart from the F7 race.
- problem.ts:28-30 uses HTTP status as authority and React renders the supplied problem detail as text; hooks.ts:31-34 treats 403 separately and Query retry is disabled at PortalApp.tsx:101.
- main.tsx, route.ts and RequestsTab.tsx were read for entry-point, query-cache, callback fragment and request-cancellation context; no review of the excluded routing/image/tab work is claimed.
- mutants.mjs was read in full; its current cases exercise several happy paths but not staggered 401s, in-flight logout, perpetual 401s, failed callback cleanup or malformed error callbacks; its final git status command (:69) also assumes a repository and cannot run as written in this export.

## Fix/test mapping and validation

The appendix is the **full code** of one combined candidate patch and the full `tests/api/portal.test.mjs` replacement; no new application module is required. Tests use the installed real libraries. The direct branch mocks fetch and a redirect navigator without starting any server. Browser tests use the existing loopback stand-ins.

| Finding | Full fix in appendix | Regression in portal.test.mjs | Observed result |
|---|---|---|---|
| F1, C2 | auth.ts: PortalUserManager.signoutRedirect drains renewal and removes user before library logout; existing logout assertion updated | `F1 logout has no token in its URL` | Original FAIL (id_token_hint true); fixed PASS |
| F2, C5 | PortalApp.tsx: terminal API failure goes to a recovery screen; only a user click initiates another redirect | `F2 persistent API 401s stop for an explicit sign-in` | **Not proven**; browser blocked before assertions |
| F3, C5 | client.ts: retain replacement promise for a rejected token, reuse a newer current token, and coalesce terminal recovery | `F3 staggered 401s share the replacement token` | Original FAIL (2 renewals); fixed PASS (1) |
| F4, C6 | PortalApp.tsx: check auth.error before authenticated branch; clear query cache when SignedIn unmounts | `F4 automatic renewal failure has a visible recovery action` | **Not proven**; browser blocked before assertions |
| F5, C3 | PortalApp.tsx: error effect replaces callback URL after failure | `F5 failed callbacks scrub the current address and history entry` | **Not proven**; browser blocked before assertions |
| F6, C4 | client.ts: enforce omit/error when constructing the actual bearer Request | `F6 bearer insertion enforces credentials and redirect` | Original FAIL (include); fixed PASS (omit/error and origin refusal) |
| F7, C10 | auth.ts: serialize automatic/API silent renewal, stop new renewals and join existing renewal before user removal; PortalApp hides API UI during logout | `F7 an in-flight renewal cannot restore a signed-out user` | Original FAIL (fresh previous-person User reachable); fixed PASS (null) |
| F8, C7 | auth.ts: validate metadata endpoint schemes at the library MetadataService boundary before use | `F8 discovery cannot downgrade sign-in or token endpoints` | Original FAIL (no rejection); fixed PASS (all 3 endpoint cases) |
| F9, C6 | PortalApp.tsx: detect callback code/error without state, stop auto sign-in, scrub query and offer explicit retry | `F9 an issuer error without state cannot trigger automatic sign-in` | **Not proven**; browser blocked before assertions |
| F10, C7 | config.ts: reject query/fragment delimiters even for empty values | `F10 config rejects empty query and fragment delimiters` | Original FAIL (no exception); fixed PASS |

Observed commands, all from cmapi-portal-ui:

```sh
# Dependencies installed as requested (generator command run in tools/openapi-types):
npm ci
(cd tools/openapi-types && npm ci --ignore-scripts)

# Required command attempted on original and candidate:
npx vite build && node tests/api/portal.test.mjs
# Vite PASS; browser launch FAIL: macOS bootstrap_check_in Permission denied (1100).

# Before: F1/F3/F6/F7/F8 FAIL; two correctness tests PASS.
REVIEW_NODE_ONLY=1 node tests/api/portal.test.mjs
# Original F10 also run separately: FAIL.
REVIEW_NODE_ONLY=1 REVIEW_CASE=F10 node tests/api/portal.test.mjs

# After combined candidate: all six regression tests + two correctness tests PASS.
REVIEW_NODE_ONLY=1 node tests/api/portal.test.mjs
npx tsc --noEmit                  # PASS
npx vite build                   # PASS

# Test fixture for the bundle check; demo itself was not reviewed:
npx vite build --mode demo --outDir dist-demo
node tests/api/bundle.test.mjs
# Static sample/logic assertions PASS (38 names); browser portion launch FAIL as above.
```

The direct branch requires Node with built-in TypeScript stripping (run here on v26.9.0). `REVIEW_CASE=F2`, `F4`, `F5` or `F9` selects one browser regression; without that variable the entire original suite plus added regressions runs. The old 401 test is updated to click the explicit recovery action, and the logout test no longer requires an ID token in the URL.

These fixes change recovery UX deliberately: terminal authentication failures require a sign-in click, and logout without an ID-token hint may require confirmation at a real issuer. Real Keycloak confirmation behavior is not tested by the stand-in. Endpoint validation addresses the discovered HTTP-endpoint case; it is not a way for a SPA to control arbitrary redirects that a trusted issuer performs after navigation, or a substitute for trusting the configured HTTPS services. C10's absolute “nothing reachable” wording cannot be established for browser HTTP caches, other tabs, browser history internals or server-side token revocation by queries.clear; the tested fix specifically prevents the in-memory renewal resurrection. No broader claim of secure erasure or revocation is made.

## Complete candidate replacement files

Apply all four application replacements together, then replace the existing test file with the full version below. The supplied export's originals are restored in the folder; the candidate lives in this report for review. No new permanent source or test files are introduced. Original sources and tests were verified restored byte for byte, and the restored production build also passed.

### `src/portal/auth.ts`

```typescript
// The portal's sign-in: OpenID Connect Authorization Code with PKCE, through the public client of config.json.
// RFC 10017 (BCP 212, OAuth 2.0 for Browser-Based Applications) is the standard for each choice here.
import { InMemoryWebStorage, UserManager, WebStorageStateStore } from "oidc-client-ts";
import type { SigninSilentArgs, SignoutRedirectArgs, User, UserManagerSettings } from "oidc-client-ts";
import type { AuthProviderProps } from "react-oidc-context";
import type { PortalConfig } from "./config";

/** What the portal keeps through the redirect to the issuer: the view to return to. */
export interface ReturnState {
  hash: string;
}

/** Only a fragment of this page is a place to return to. The value comes back through storage, so it is checked. */
function returnHash(user: User | undefined): string {
  const state = user?.state as Partial<ReturnState> | undefined;
  return typeof state?.hash === "string" && /^#[\w/?=&%.~+-]*$/.test(state.hash) ? state.hash : "";
}

/** Serializes automatic/API renewals and drains them before removing the user at sign-out. */
class PortalUserManager extends UserManager {
  private pendingRenewal: Promise<User | null> | undefined;
  private pendingSignout: Promise<void> | undefined;
  private closing = false;

  constructor(...args: ConstructorParameters<typeof UserManager>) {
    super(...args);
    const service = this.metadataService;
    const getMetadata = service.getMetadata.bind(service);
    service.getMetadata = async () => {
      const metadata = await getMetadata();
      for (const key of ["authorization_endpoint", "token_endpoint", "end_session_endpoint", "userinfo_endpoint", "jwks_uri"] as const) {
        const endpoint = metadata[key];
        if (!endpoint) continue;
        const url = new URL(endpoint);
        const local = url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
        if (url.protocol !== "https:" && !local) throw new Error(`OIDC ${key} must be an https URL.`);
        if (url.username || url.password) throw new Error(`OIDC ${key} must have no user.`);
      }
      return metadata;
    };
  }

  override signinSilent(args?: SigninSilentArgs): Promise<User | null> {
    if (this.closing) return Promise.resolve(null);
    return this.pendingRenewal ??= super.signinSilent({ ...args, silentRequestTimeoutInSeconds: args?.silentRequestTimeoutInSeconds ?? this.settings.silentRequestTimeoutInSeconds }).finally(() => { this.pendingRenewal = undefined; });
  }

  override signoutRedirect(args?: SignoutRedirectArgs): Promise<void> {
    if (this.pendingSignout) return this.pendingSignout;
    this.closing = true;
    this.stopSilentRenew();
    this.pendingSignout = (async () => {
      await this.pendingRenewal?.catch(() => undefined);
      // Removing the user first prevents oidc-client-ts from adding its ID token to the URL.
      await this.removeUser();
      await super.signoutRedirect({ ...args, id_token_hint: undefined });
    })().finally(() => { this.pendingSignout = undefined; });
    return this.pendingSignout;
  }
}

export function oidcSettings(config: PortalConfig): AuthProviderProps {
  // The redirect URI is this page without its query and fragment. The realm lists it for the client.
  const page = location.origin + location.pathname;
  const settings: UserManagerSettings = {
    authority: config.issuer,
    client_id: config.clientId,
    redirect_uri: page,
    post_logout_redirect_uri: page,
    response_type: "code",
    response_mode: "query",
    // The realm gives the client its scopes as defaults (audience, roles, identity), so the portal asks for no more.
    scope: "openid",
    // Tokens stay in the memory of this page (RFC 10017 section 8.4): nothing is written to localStorage or
    // sessionStorage, and nothing is left on disk (section 8.6). A reload signs in again through the issuer's session.
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    // The PKCE verifier and the state must survive the redirect. sessionStorage holds them for this tab only, and
    // oidc-client-ts removes the entry when the code is exchanged. Its own default is localStorage.
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    // The access token lives 5 minutes. The library renews it with the refresh token before it ends.
    automaticSilentRenew: true,
    requestTimeoutInSeconds: 10,
    // No check_session iframe: browsers block the third-party cookie that it needs.
    monitorSession: false,
    // The portal reads the person from GET /api/v1/me, not from the userinfo endpoint.
    loadUserInfo: false,
  };
  return {
    userManager: new PortalUserManager(settings),
    // The code and the state are used once. Take them out of the address bar and the history.
    onSigninCallback: (user) => history.replaceState(null, "", location.pathname + returnHash(user))
  };
}
```

### `src/portal/config.ts`

```typescript
// The portal's runtime settings. The deployment writes config.json beside index.html, so one build serves each instance
// and no issuer, client or API address is compiled into the bundle.

export interface PortalConfig {
  /** The public URL of this instance's API, without a path. */
  apiUrl: string;
  /** The OIDC issuer: the URL of the Keycloak realm. */
  issuer: string;
  /** The portal's public client in that realm. */
  clientId: string;
  /** The name of this instance, for example nonprod. */
  instance: string;
  /** The name of this instance for a sentence, for example Non-production. */
  displayName: string;
  /** The environments that this instance serves. */
  environments: string[];
}

/** config.json is missing or wrong. The portal shows the message and starts nothing. */
export class ConfigError extends Error {}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** An absolute https URL. Plain http is for a developer's own machine only, where no certificate exists. */
function serviceUrl(value: unknown, name: string): string {
  if (typeof value !== "string" || !value) throw new ConfigError(`config.json has no ${name}.`);
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConfigError(`config.json: ${name} is not a URL.`);
  }
  const local = url.protocol === "http:" && LOCAL_HOSTS.has(url.hostname);
  if (url.protocol !== "https:" && !local) throw new ConfigError(`config.json: ${name} must be an https URL.`);
  if (url.username || url.password || url.href.includes("?") || url.href.includes("#")) throw new ConfigError(`config.json: ${name} must have no user, query or fragment.`);
  return value.replace(/\/+$/, "");
}

function text(value: unknown, name: string): string {
  if (typeof value !== "string" || !value.trim()) throw new ConfigError(`config.json has no ${name}.`);
  return value;
}

export function parseConfig(raw: unknown): PortalConfig {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) throw new ConfigError("config.json is not a JSON object.");
  const o = raw as Record<string, unknown>;
  const environments = o.environments ?? [];
  if (!Array.isArray(environments) || environments.some((e) => typeof e !== "string")) throw new ConfigError("config.json: environments must be a list of names.");
  const instance = text(o.instance, "instance");
  const apiUrl = serviceUrl(o.apiUrl, "apiUrl");
  // The API's paths start at the root of its host (/api/v1/...), so a path here would send each call to the wrong place.
  if (new URL(apiUrl).pathname !== "/") throw new ConfigError("config.json: apiUrl must have no path.");
  return {
    apiUrl,
    issuer: serviceUrl(o.issuer, "issuer"),
    clientId: text(o.clientId, "clientId"),
    instance,
    displayName: typeof o.displayName === "string" && o.displayName ? o.displayName : instance,
    environments: environments as string[]
  };
}

export async function loadConfig(signal?: AbortSignal): Promise<PortalConfig> {
  let response: Response;
  try {
    // no-store: a changed ConfigMap must reach the next page load, not a cached copy.
    response = await fetch(new URL("config.json", document.baseURI), { cache: "no-store", credentials: "omit", signal });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ConfigError("config.json did not load.");
  }
  if (!response.ok) throw new ConfigError(`config.json did not load (HTTP ${response.status}).`);
  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    throw new ConfigError("config.json is not JSON.");
  }
  return parseConfig(raw);
}
```

### `src/api/client.ts`

```typescript
// The portal's one client of the API. Its paths, parameters and answers are typed from the OpenAPI document.
import createClient from "openapi-fetch";
import type { Client } from "openapi-fetch";
import type { paths } from "./schema.generated";

/** The signed-in session, as the client needs it. The page keeps the tokens; the client only asks for one. */
export interface Session {
  /** The access token now, if the person is signed in. */
  token(): string | undefined;
  /** One renewal with the refresh token. Gives the new access token, or nothing if the issuer refused. */
  renew(): Promise<string | undefined>;
  /** Requests interactive sign-in recovery; the UI requires a user gesture. */
  signIn(): Promise<void>;
}

export type Api = Client<paths>;

export function createApi(apiUrl: string, session: Session): Api {
  const origin = new URL(apiUrl).origin;
  let renewal: Promise<string | undefined> | undefined;
  let replacement: { rejected: string; token: Promise<string | undefined> } | undefined;
  let signingIn: Promise<void> | undefined;
  const signInOnce = () => (signingIn ??= session.signIn());
  // Each call that meets an expired token waits for the same renewal: the realm refuses a refresh token used twice.
  const renewOnce = () => (renewal ??= Promise.resolve().then(() => session.renew()).catch(() => undefined).finally(() => { renewal = undefined; }));

  async function authFetch(request: Request): Promise<Response> {
    // The token goes to the API of config.json and to no other origin.
    if (new URL(request.url).origin !== origin) throw new Error(`Refused a call to ${new URL(request.url).origin}: it is not the API.`);
    const send = (token: string) => {
      const attempt = new Request(request.clone(), { credentials: "omit", redirect: "error" });
      attempt.headers.set("Authorization", `Bearer ${token}`);
      return fetch(attempt);
    };
    const token = session.token() ?? await renewOnce();
    if (!token) {
      await signInOnce();
      throw new Error("Not signed in.");
    }
    const first = await send(token);
    if (first.status !== 401) return first;
    // 401: the session ended, or the token did. One silent renewal, then the same call again.
    // A late 401 for a token already replaced joins that recovery even after it settled.
    if (replacement?.rejected !== token) {
      const current = session.token();
      replacement = { rejected: token, token: current && current !== token ? Promise.resolve(current) : renewOnce() };
    }
    const fresh = await replacement.token;
    if (fresh) {
      const second = await send(fresh);
      if (second.status !== 401) return second;
    }
    await signInOnce();
    return first;
  }

  return createClient<paths>({
    baseUrl: apiUrl,
    fetch: authFetch,
    // Bearer token only: no cookie goes to the API, and a redirect never carries the token to another place.
    credentials: "omit",
    redirect: "error"
  });
}
```

### `src/portal/PortalApp.tsx`

```tsx
// The portal on the API: config.json, sign-in through the issuer, then the mockup's page frame and tabs.
import {
  Alert, AlertActionLink, Bullseye, Button, Content, EmptyState, EmptyStateActions, EmptyStateBody, EmptyStateFooter, Flex, FlexItem, Masthead,
  MastheadBrand, MastheadContent, MastheadMain, Page, PageSection, Stack, Tab, Tabs, TabTitleText, Title
} from "@patternfly/react-core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentType, ReactNode } from "react";
import { AuthProvider, hasAuthParams, useAuth } from "react-oidc-context";
import { createApi } from "../api/client";
import type { Session } from "../api/client";
import { ApiProvider, useMe } from "../api/hooks";
import { PERMISSION } from "../api/permissions.generated";
import { Small } from "../components/ui";
import { oidcSettings } from "./auth";
import type { ReturnState } from "./auth";
import { ConfigError, loadConfig } from "./config";
import type { PortalConfig } from "./config";
import { RequestsTab } from "./RequestsTab";
import { useRoute } from "./route";
import type { TabId, TabProps } from "./route";

interface TabDef {
  id: TabId;
  label: string;
  /** The permission of the tab's first call. A tab whose calls are not built has none yet. */
  needs: string | null;
  panel?: ComponentType<TabProps>;
}

const NO_PARAMS = new URLSearchParams();

// The mockup's tabs and their order. A tab shows only when GET /api/v1/me says that the person holds its permission.
const TABS: TabDef[] = [
  { id: "workflow", label: "Workflow", needs: PERMISSION["GET /api/v1/requests/{request_id}/events"] },
  { id: "new", label: "New namespace", needs: PERMISSION["POST /api/v1/clusters/{cluster_id}/namespaces"] },
  { id: "quotas", label: "Quotas", needs: PERMISSION["GET /api/v1/quotas"] },
  { id: "expiration", label: "Expiration", needs: null },
  { id: "requests", label: "Requests", needs: PERMISSION["GET /api/v1/requests"], panel: RequestsTab },
  { id: "approvals", label: "Approvals", needs: PERMISSION["POST /api/v1/requests/{request_id}:approve"] },
  { id: "policies", label: "Policies", needs: null },
  { id: "capacity", label: "Capacity", needs: null },
  { id: "kpis", label: "KPIs", needs: PERMISSION["GET /api/v1/admin/kpi"] }
];

const Waiting = ({ children }: { children: string }) => <Bullseye><span role="status">{children}</span></Bullseye>;

function Blocked({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <Bullseye>
      <EmptyState titleText={title} headingLevel="h1" status="danger">
        <EmptyStateBody>{body}</EmptyStateBody>
        {action && <EmptyStateFooter><EmptyStateActions>{action}</EmptyStateActions></EmptyStateFooter>}
      </EmptyState>
    </Bullseye>
  );
}

export function PortalApp() {
  const [boot, setBoot] = useState<{ config?: PortalConfig; error?: string }>({});
  useEffect(() => {
    const control = new AbortController();
    loadConfig(control.signal).then(
      (config) => setBoot({ config }),
      (error: unknown) => {
        if (!control.signal.aborted) setBoot({ error: error instanceof ConfigError ? error.message : "config.json did not load." });
      }
    );
    return () => control.abort();
  }, []);
  // With no issuer and no API there is nothing to show: this build holds no sample data.
  if (boot.error) return <Blocked title="The portal is not configured." body={boot.error} />;
  if (!boot.config) return <Waiting>Loading the portal…</Waiting>;
  return <Configured config={boot.config} />;
}

function Configured({ config }: { config: PortalConfig }) {
  const settings = useMemo(() => oidcSettings(config), [config]);
  return <AuthProvider {...settings}><SignIn config={config} /></AuthProvider>;
}

/** Sends a person with no session to the issuer, and shows the portal only to a signed-in person. */
function SignIn({ config }: { config: PortalConfig }) {
  const auth = useAuth();
  const asked = useRef(false);
  const [sessionEnded, setSessionEnded] = useState(false);
  const [callbackError] = useState(() => {
    const params = new URLSearchParams(location.search);
    return (params.has("error") || params.has("code")) && !params.get("state")
      ? "The sign-in response has no state. Sign in again to continue." : undefined;
  });
  const signIn = () => auth.signinRedirect({ state: { hash: location.hash } satisfies ReturnState });
  useEffect(() => {
    if (hasAuthParams() || auth.isAuthenticated || auth.activeNavigator || auth.isLoading || auth.error || callbackError || sessionEnded || asked.current) return;
    asked.current = true;
    void signIn();
  });
  useEffect(() => {
    if ((auth.error && hasAuthParams()) || callbackError) history.replaceState(null, "", location.pathname);
  }, [auth.error, callbackError]);
  // A session failure requires a user gesture. Redirecting automatically here can loop across page loads.
  if (sessionEnded || auth.error || callbackError) return <Blocked title="Sign-in did not complete." body={auth.error?.message ?? callbackError ?? "The API refused this session. Sign in again to continue."} action={<Button onClick={() => void signIn()}>Sign in again</Button>} />;
  if (auth.isAuthenticated) return <SignedIn config={config} onSessionEnded={() => setSessionEnded(true)} />;
  return <Waiting>Signing in…</Waiting>;
}

function SignedIn({ config, onSessionEnded }: { config: PortalConfig; onSessionEnded: () => void }) {
  const auth = useAuth();
  const [signingOut, setSigningOut] = useState(false);
  const latest = useRef(auth);
  latest.current = auth;
  const [queries] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 15_000 } } }));
  const sessionEnded = useRef(onSessionEnded);
  sessionEnded.current = onSessionEnded;
  useEffect(() => () => queries.clear(), [queries]);
  const api = useMemo(() => {
    const session: Session = {
      token: () => {
        const user = latest.current.user;
        return user && !user.expired ? user.access_token : undefined;
      },
      renew: async () => (await latest.current.signinSilent())?.access_token,
      signIn: async () => { sessionEnded.current(); }
    };
    return createApi(config.apiUrl, session);
  }, [config.apiUrl]);
  const signOut = () => {
    // Nothing that the API sent stays in memory for the next person on this browser.
    setSigningOut(true);
    queries.clear();
    void auth.signoutRedirect();
  };
  if (signingOut) return <Waiting>Signing out…</Waiting>;
  return (
    <QueryClientProvider client={queries}>
      <ApiProvider value={api}><Portal config={config} onSignOut={signOut} /></ApiProvider>
    </QueryClientProvider>
  );
}

function Portal({ config, onSignOut }: { config: PortalConfig; onSignOut: () => void }) {
  const me = useMe();
  const { route, go } = useRoute();
  const held = me.state === "ok" ? new Set(me.data.access.permissions) : null;
  const tabs = held ? TABS.filter((tab) => tab.needs === null || held.has(tab.needs)) : [];
  const active = tabs.find((tab) => tab.id === route.tab) ?? tabs[0];

  const masthead = (
    <Masthead>
      <MastheadMain>
        <MastheadBrand>
          <Title headingLevel="h2" size="lg">cmapi <Small>Cluster Management Portal</Small></Title>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Flex alignItems={{ default: "alignItemsCenter" }} justifyContent={{ default: "justifyContentSpaceBetween" }} style={{ width: "100%" }}>
          <FlexItem><Small>{config.instance} · {config.environments.join(", ")}</Small></FlexItem>
          <Flex alignItems={{ default: "alignItemsCenter" }}>
            <a href={`${config.apiUrl}/docs`}>Swagger</a>
            <a href={`${config.apiUrl}/redoc`}>ReDoc</a>
            {me.state === "ok" && <Stack><b>{me.data.username}</b><Small>{me.data.roles.join(" · ")} (Keycloak roles)</Small></Stack>}
            <Button variant="link" isInline onClick={onSignOut}>Sign out</Button>
          </Flex>
        </Flex>
      </MastheadContent>
    </Masthead>
  );

  return (
    <Page masthead={masthead}>
      <PageSection>
        {me.state === "loading" && <span role="status">Loading your access…</span>}
        {(me.state === "error" || me.state === "forbidden") && (
          <Alert variant="danger" isInline title="Your access did not load." actionLinks={<AlertActionLink onClick={me.reload}>Try again</AlertActionLink>}>
            {me.state === "error" ? me.cause : me.detail}
          </Alert>
        )}
        {active && (
          <Tabs activeKey={active.id} onSelect={(_, key) => go(key as TabId)} aria-label="Portal sections" mountOnEnter unmountOnExit>
            {tabs.map(({ id, label, panel: Panel }) => (
              <Tab key={id} eventKey={id} title={<TabTitleText>{label}</TabTitleText>}>
                <div style={{ paddingBlockStart: "var(--pf-t--global--spacer--md)" }}>
                  {Panel
                    ? <Panel config={config} params={id === route.tab ? route.params : NO_PARAMS} setParams={(values) => go(id, values)} />
                    : <EmptyState titleText="This tab is not on the API yet." headingLevel="h1"><EmptyStateBody>It shows data when its API calls are built.</EmptyStateBody></EmptyState>}
                </div>
              </Tab>
            ))}
          </Tabs>
        )}
        <Content component="small">
          Times are UTC. This is the {config.displayName} instance: API {config.apiUrl}, portal {location.origin}.
        </Content>
      </PageSection>
    </Page>
  );
}
```

### `tests/api/portal.test.mjs`

```javascript
#!/usr/bin/env node
// The portal on the API (issue #204), against the built portal (dist/), a stand-in issuer and a stand-in API.
// Stage: built-mocked. It proves what the browser does. It does not prove a sign-in on a real Keycloak or a call to
// the real service. PW_CHANNEL=chrome runs it in the installed Chrome, and PW_HEADED=1 shows the window.
import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { AxeBuilder } from "@axe-core/playwright";
import { chromium } from "playwright";
import { requestsFrom, SAMPLES, servePortal, startApi, startIssuer, USERS } from "./standin.mjs";

const app = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const out = join(app, "test-output", "api");
mkdirSync(out, { recursive: true });

// Reviewer 1: direct tests run before browser launch (Node 22.18+ type stripping).
// REVIEW_NODE_ONLY=1 runs these even where the browser sandbox cannot launch.
if (process.env.REVIEW_NODE_ONLY) {
  const { createApi } = await import("../../src/api/client.ts");
  const { oidcSettings } = await import("../../src/portal/auth.ts");
  const { InMemoryWebStorage, UserManager, User } = await import("oidc-client-ts");
  const defer = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
  const tests = [];
  const test = (name, run) => tests.push([name, run]);
  const originalFetch = globalThis.fetch;
  globalThis.window = { sessionStorage: new InMemoryWebStorage(), localStorage: new InMemoryWebStorage() };
  globalThis.location = { origin: "https://portal.test", pathname: "/index.html" };
  const config = { issuer: "https://issuer.test", apiUrl: "https://api.test", clientId: "portal", instance: "test" };
  const managerFor = () => {
    const props = oidcSettings(config);
    const settings = props.userManager?.settings ?? props;
    const Manager = props.userManager?.constructor ?? UserManager;
    let url;
    const manager = new Manager({ ...settings, automaticSilentRenew: false,
      metadata: { issuer: config.issuer, authorization_endpoint: config.issuer + "/auth",
        token_endpoint: config.issuer + "/token", end_session_endpoint: config.issuer + "/logout" }
    }, { prepare: async () => ({ navigate: async (args) => { url = args.url; return { url }; }, close() {} }) });
    props.userManager?.stopSilentRenew();
    return { manager, url: () => url };
  };
  const oldUser = () => new User({ profile: { sub: "person-A" }, access_token: "access-A",
    refresh_token: "refresh-A", id_token: "id-A", token_type: "Bearer", scope: "openid" });

  test("F1 logout has no token in its URL", async () => {
    const { manager, url } = managerFor();
    await manager.storeUser(oldUser());
    await manager.signoutRedirect();
    const q = new URL(url()).searchParams;
    assert.equal(q.has("id_token_hint"), false);
    assert.equal(q.get("client_id"), "portal");
    assert.equal(await manager.getUser(), null);
  });

  test("F3 staggered 401s share the replacement token", async () => {
    let token = "old", renewals = 0;
    const late401 = defer(), secondStarted = defer();
    const sent = [];
    globalThis.fetch = async (request) => {
      const bearer = request.headers.get("authorization");
      sent.push(bearer);
      if (bearer === "Bearer old" && sent.length === 2) { secondStarted.resolve(); await late401.promise; }
      return bearer === "Bearer old" ? new Response("{}", { status: 401 }) : Response.json({});
    };
    const api = createApi(config.apiUrl, { token: () => token,
      renew: async () => { ++renewals; token = "new"; return token; }, signIn: async () => assert.fail("unexpected sign in") });
    const first = api.GET("/api/v1/me"), second = api.GET("/api/v1/me");
    await secondStarted.promise;
    await first;
    late401.resolve();
    await second;
    assert.equal(renewals, 1);
    assert.deepEqual(sent, ["Bearer old", "Bearer old", "Bearer new", "Bearer new"]);
  });

  test("F6 bearer insertion enforces credentials and redirect", async () => {
    let sent;
    globalThis.fetch = async (request) => { sent = request; return Response.json({}); };
    const api = createApi(config.apiUrl, { token: () => "token", renew: async () => undefined, signIn: async () => {} });
    await api.GET("/api/v1/me", { credentials: "include", redirect: "follow" });
    assert.equal(sent.credentials, "omit");
    assert.equal(sent.redirect, "error");
    await assert.rejects(api.GET("/api/v1/me", { baseUrl: "https://other.test" }), /not the API/);
  });

  test("F7 an in-flight renewal cannot restore a signed-out user", async () => {
    const { manager } = managerFor();
    const entered = defer(), release = defer();
    globalThis.fetch = async () => {
      entered.resolve(); await release.promise;
      return Response.json({ access_token: "access-B", refresh_token: "refresh-B", token_type: "Bearer", scope: "openid" });
    };
    await manager.storeUser(oldUser());
    const renewal = manager.signinSilent();
    await entered.promise;
    const signout = manager.signoutRedirect();
    // removeUser is the exact boundary at which the unprotected implementation loses the race.
    // Give its asynchronous store operations a complete event-loop turn.
    await new Promise((resolve) => setImmediate(resolve));
    release.resolve();
    await Promise.all([renewal, signout]);
    assert.equal(await manager.getUser(), null);
  });

  test("F8 discovery cannot downgrade sign-in or token endpoints", async () => {
    const { parseConfig } = await import("../../src/portal/config.ts");
    const checked = parseConfig(config);
    for (const key of ["authorization_endpoint", "token_endpoint", "end_session_endpoint"]) {
      const props = oidcSettings(checked);
      const Manager = props.userManager?.constructor ?? UserManager;
      const settings = props.userManager?.settings ?? props;
      const manager = new Manager({ ...settings, automaticSilentRenew: false }, {
        prepare: async () => ({ navigate: async ({ url }) => ({ url }), close() {} })
      });
      props.userManager?.stopSilentRenew();
      globalThis.fetch = async () => Response.json({ issuer: checked.issuer,
        authorization_endpoint: checked.issuer + "/auth", token_endpoint: checked.issuer + "/token",
        end_session_endpoint: checked.issuer + "/logout", [key]: "http://insecure.example/endpoint" });
      await assert.rejects(manager.signinRedirect(), /https/);
    }
  });

  test("correct PKCE, transaction storage and callback cleanup", async () => {
    const { manager, url } = managerFor();
    window.sessionStorage.clear(); window.localStorage.clear();
    await manager.signinRedirect({ state: { hash: "#requests?q=pay" } });
    const q = new URL(url()).searchParams;
    assert.equal(q.get("response_type"), "code");
    assert.equal(q.get("code_challenge_method"), "S256");
    assert.match(q.get("code_challenge"), /^[A-Za-z0-9_-]{43}$/);
    assert.ok(q.get("state"));
    const stored = JSON.parse(window.sessionStorage.getItem("oidc." + q.get("state")));
    assert.equal(stored.id, q.get("state"));
    assert.equal(stored.request_type, "si:r");
    assert.equal(stored.code_verifier.length, 96);
    assert.deepEqual(stored.data, { hash: "#requests?q=pay" });
    const id = ["header", Buffer.from(JSON.stringify({ sub: "person-A" })).toString("base64url"), "signature"].join(".");
    globalThis.fetch = async () => Response.json({ access_token: "access-A", refresh_token: "refresh-A",
      id_token: id, token_type: "Bearer", scope: "openid", expires_in: 300 });
    await manager.signinRedirectCallback(`https://portal.test/index.html?code=single-use&state=${q.get("state")}`);
    assert.equal(window.sessionStorage.length, 0);
    assert.equal(window.localStorage.length, 0);
    const memory = await manager.settings.userStore.get(`user:${config.issuer}:portal`);
    for (const token of ["access-A", "refresh-A", id]) assert.ok(memory.includes(token));
    await manager.removeUser();
    const props = oidcSettings(config);
    const targets = [];
    globalThis.history = { replaceState: (_state, _title, target) => targets.push(target) };
    for (const hash of ["#requests?q=pay", "#//other.test/path", "#%0Ajavascript%3Aalert", "javascript:alert(1)", "https://other.test"]) {
      await props.onSigninCallback({ state: { hash } });
      const target = targets.at(-1);
      assert.equal(new URL(target, location.origin).origin, location.origin);
      assert.equal(new URL(target, location.origin).search, "");
      assert.equal(target, "/index.html" + (/^#[\w/?=&%.~+-]*$/.test(hash) ? hash : ""));
    }
    props.userManager?.stopSilentRenew();
  });

  test("correct config service URL boundaries", async () => {
    const { parseConfig } = await import("../../src/portal/config.ts");
    for (const apiUrl of ["http://api.example", "javascript:alert(1)", "https://u:p@api.test", "https://api.test/api", "https://api.test/?q=x", "https://api.test/#x"]) {
      assert.throws(() => parseConfig({ ...config, apiUrl }));
    }
    for (const issuer of ["http://issuer.example/realm", "ftp://issuer.example", "https://u@issuer.test", "https://issuer.test/?q=x", "https://issuer.test/#x"]) {
      assert.throws(() => parseConfig({ ...config, issuer }));
    }
    for (const apiUrl of ["http://localhost:1234", "http://127.0.0.1:1234", "http://[::1]:1234", "https://api.test"]) {
      assert.equal(parseConfig({ ...config, apiUrl }).apiUrl, apiUrl);
    }
  });

  test("F10 config rejects empty query and fragment delimiters", async () => {
    const { parseConfig } = await import("../../src/portal/config.ts");
    for (const suffix of ["?", "#"]) {
      assert.throws(() => parseConfig({ ...config, apiUrl: config.apiUrl + suffix }), /query or fragment/);
      assert.throws(() => parseConfig({ ...config, issuer: config.issuer + suffix }), /query or fragment/);
    }
  });

  let failed = 0;
  for (const [name, run] of tests) {
    if (process.env.REVIEW_CASE && !name.startsWith(process.env.REVIEW_CASE + " ")) continue;
    try { await run(); console.log(`ok - ${name}`); }
    catch (error) { ++failed; console.error(`FAIL - ${name}: ${error.message}`); }
    finally { globalThis.fetch = originalFetch; }
  }
  process.exit(failed ? 1 : 0);
}

let portal;
const issuer = await startIssuer({ redirectUris: () => [portal.page] });
const api = await startApi({ issuer, portalOrigin: () => portal.origin });
const CONFIG = { apiUrl: api.url, issuer: issuer.url, clientId: "cmapi-portal", audience: "cmapi-nonprod", instance: "nonprod", displayName: "Non-production", environments: ["rnd", "dev"], otherInstances: [] };
portal = await servePortal(join(app, "dist"), () => CONFIG);
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL, headless: !process.env.PW_HEADED });

const recorded = SAMPLES.operations.requests_list_requests.response.body.items[0];
const sixtyOne = requestsFrom(recorded, 61);
const AUTH = `${issuer.url}/protocol/openid-connect/auth`;
// Chrome reports each answer that is not 2xx as a console error. A check that asks for one names its status here.
let expectedStatus = [];

/** A new browser profile: no session, no storage. */
async function fresh({ user = "requester", items = sixtyOne, mode = "ok", width = 1440 } = {}) {
  issuer.state.user = user && USERS[user];
  issuer.state.sessions = true;
  issuer.state.lifetime = 300;
  Object.assign(api.state, { mode, items, delayMs: 0, seen: [] });
  issuer.state.seen.length = 0;
  expectedStatus = [];
  const context = await browser.newContext({ viewport: { width, height: 1000 } });
  const page = await context.newPage();
  page.setDefaultTimeout(8000);
  const errors = [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const status = /status of (\d{3})/.exec(m.text())?.[1];
    if (!status || !expectedStatus.includes(Number(status))) errors.push(`${m.text()} (${m.location().url})`);
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return { context, page, errors };
}
const open = async (page, hash = "#requests") => {
  await page.goto(portal.page + hash);
  await page.locator("[role=tablist]").waitFor();
};
const panel = (page) => page.getByRole("tabpanel");
const rows = (page) => page.locator("table[aria-label=Requests] tbody tr").evaluateAll((trs) => trs.map((tr) => [...tr.children].map((td) => td.innerText.replace(/\s+/g, " ").trim())));
const range = (page) => panel(page).getByText(/ of \d+ · newest first$|^0 requests$/).innerText();
/** Waits for the pager to say `want`. A failure says what the pager and the API's last call were. */
async function waitRange(page, want) {
  try {
    await page.waitForFunction((text) => document.querySelector("[role=tabpanel]")?.innerText.includes(text), want);
  } catch {
    assert.fail(`the pager never said "${want}": it says "${await range(page).catch(() => "nothing")}", and the last call was ${JSON.stringify(api.state.seen.at(-1))}`);
  }
}
const calls = (path) => api.state.seen.filter((c) => c.path === path);
const tabNames = (page) => page.getByRole("tab").allInnerTexts();

// What one request of the API reads as in the table. Written from the mockup's forms, not from the page's code.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function expectedRow(r) {
  const at = new Date(r.updatedAt), time = r.updatedAt.slice(11, 16);
  const today = r.updatedAt.slice(0, 10) === new Date().toISOString().slice(0, 10);
  const need = r.approval.slots.reduce((n, s) => n + s.count, 0), left = r.approval.remaining.reduce((n, s) => n + s.needed, 0);
  const last = r.events.at(-1);
  return [r.requestId, r.clusterId, r.namespace, r.action, r.status, `${last.event} by ${last.by}`, `${r.approval.rule} · ${need - left} of ${need}`,
    r.pr ? `#${r.pr.number}` : "—", today ? time : `${MONTHS[at.getUTCMonth()]} ${at.getUTCDate()} ${time}`, "Open at current step"];
}

// No check may wait without end: a defect in the page must fail the suite, not hang it.
const CHECK_TIMEOUT_MS = 90_000;
const done = [];
async function check(name, run) {
  if (process.env.REVIEW_CASE && !name.startsWith(process.env.REVIEW_CASE + " ")) return;
  let timer;
  const late = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`"${name}" did not end in ${CHECK_TIMEOUT_MS / 1000} s`)), CHECK_TIMEOUT_MS); });
  try {
    await Promise.race([run(), late]);
  } finally {
    clearTimeout(timer);
  }
  done.push(name);
  console.log(`ok - ${name}`);
}

try {
  await check("F2 persistent API 401s stop for an explicit sign-in", async () => {
    const { context, page } = await fresh({ mode: "always401" });
    expectedStatus = [401];
    try {
      await page.goto(`${portal.page}#requests`);
      await page.getByRole("heading", { name: "Sign-in did not complete." }).waitFor();
      await page.waitForTimeout(500);
      assert.equal(issuer.state.seen.filter((s) => s.what === "auth").length, 1);
      assert.equal(calls("/api/v1/me").length, 2);
      api.state.mode = "ok";
      await page.getByRole("button", { name: "Sign in again" }).click();
      await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
      assert.equal(issuer.state.seen.filter((s) => s.what === "auth").length, 2);
    } finally { await context.close(); }
  });

  await check("F4 automatic renewal failure has a visible recovery action", async () => {
    const { context, page } = await fresh();
    expectedStatus = [400];
    try {
      let first = true;
      await page.route(`${issuer.url}/protocol/openid-connect/token`, async (route) => {
        if (!first) return route.continue();
        first = false;
        const response = await route.fetch();
        const body = await response.json();
        await route.fulfill({ response, json: { ...body, expires_in: 2 } });
      });
      await open(page);
      issuer.state.sessions = false;
      await page.getByRole("heading", { name: "Sign-in did not complete." }).waitFor();
      assert.equal(await page.getByRole("table").count(), 0);
      assert.equal(issuer.state.seen.filter((s) => s.what === "auth").length, 1);
      issuer.state.sessions = true;
      await page.getByRole("button", { name: "Sign in again" }).click();
      await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
    } finally { await context.close(); }
  });

  await check("F9 an issuer error without state cannot trigger automatic sign-in", async () => {
    const { context, page } = await fresh();
    try {
      let authorizations = 0;
      await page.route(`${AUTH}*`, (route) => {
        ++authorizations;
        return route.fulfill({ status: 302, headers: { location: `${portal.page}?error=access_denied` }, body: "" });
      });
      await page.goto(`${portal.page}?error=access_denied`);
      await page.getByRole("heading", { name: "Sign-in did not complete." }).waitFor();
      await page.waitForTimeout(500);
      assert.equal(authorizations, 0);
      assert.equal(page.url(), portal.page);
      assert.equal(await page.getByRole("button", { name: "Sign in again" }).count(), 1);
    } finally { await context.close(); }
  });

  await check("F5 failed callbacks scrub the current address and history entry", async () => {
    for (const kind of ["code-exchange", "error"]) {
      const { context, page } = await fresh();
      expectedStatus = [400];
      try {
        if (kind === "code-exchange") {
          await page.route(`${issuer.url}/protocol/openid-connect/token`, (route) => route.fulfill({
            status: 400, contentType: "application/json", body: JSON.stringify({ error: "invalid_grant" })
          }));
          await page.goto(portal.page);
        } else await page.goto(`${portal.page}?error=access_denied&state=unknown`);
        await page.getByRole("heading", { name: "Sign-in did not complete." }).waitFor();
        await page.waitForFunction(() => location.search === "");
        const cdp = await context.newCDPSession(page);
        const history = await cdp.send("Page.getNavigationHistory");
        assert.equal(history.entries[history.currentIndex].url, portal.page);
        assert.equal(issuer.state.seen.filter((s) => s.what === "auth").length, kind === "error" ? 0 : 1);
      } finally { await context.close(); }
    }
  });

  await check("1 no session: the browser goes to the issuer with code, S256, the client and a state; no token in a URL or in storage", async () => {
    const { context, page, errors } = await fresh({ user: null });
    await page.goto(`${portal.page}#requests`);
    await page.waitForURL((url) => url.href.startsWith(AUTH));
    const q = Object.fromEntries(new URL(page.url()).searchParams);
    assert.equal(q.response_type, "code");
    assert.equal(q.client_id, "cmapi-portal");
    assert.equal(q.code_challenge_method, "S256");
    assert.match(q.code_challenge, /^[A-Za-z0-9_-]{43}$/, "the challenge is a SHA-256 in base64url");
    assert.ok(q.state, "a state");
    assert.equal(q.redirect_uri, portal.page, "the redirect URI is the page, with no query and no fragment");
    assert.equal(q.scope, "openid");
    assert.deepEqual(Object.keys(q).filter((k) => /token|password|secret/i.test(k)), [], "no token and no secret in the authorization request");
    assert.equal(calls("/api/v1/me").length + calls("/api/v1/requests").length, 0, "no API call before the sign-in");

    // Now the person signs in at the issuer, and the issuer sends the browser back with a code.
    issuer.state.user = USERS.requester;
    await page.goto(page.url());
    await page.locator("[role=tablist]").waitFor();
    await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
    assert.equal(page.url(), `${portal.page}#requests`, "the code and the state are gone from the address, and the view is back");
    const tokens = issuer.tokens();
    assert.ok(tokens.length >= 2, "the issuer gave an access token and a refresh token");
    const stored = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }));
    assert.deepEqual(stored.local, {}, "localStorage is empty");
    const kept = JSON.stringify(stored.session);
    for (const t of tokens) assert.ok(!kept.includes(t), "no token in sessionStorage");
    assert.ok(!/code_verifier/.test(kept), "the PKCE verifier is removed after the exchange");
    const urls = [...issuer.state.seen.map((s) => s.url ?? ""), ...api.state.seen.map((c) => c.path + JSON.stringify(c.query))].join("\n");
    for (const t of tokens) assert.ok(!urls.includes(t), "no token in a URL");
    assert.deepEqual(issuer.state.seen.filter((s) => s.what === "token").map((s) => s.grant), ["authorization_code"], "one code exchange");
    assert.ok(api.state.seen.every((c) => c.cookie === null), "no cookie goes to the API");
    assert.ok(api.state.seen.every((c) => c.user === "ola"), "each API call carries the person's token");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("2 the Requests tab shows the recorded request of GET /api/v1/requests, cell by cell", async () => {
    const { context, page, errors } = await fresh({ items: [recorded] });
    await open(page);
    assert.deepEqual(await rows(page), [expectedRow(recorded)]);
    assert.equal(await range(page), "1–1 of 1 · newest first");
    assert.match(await page.locator("table[aria-label=Requests] tbody tr .pf-v6-c-label").getAttribute("class"), /pf-m-warning/, "pending_approval has the mockup's warn tone");
    // Open at current step needs the Workflow tab. It is off, and it says why in text that a screen reader links to it.
    const openButton = page.getByRole("button", { name: "Open at current step" });
    assert.equal(await openButton.getAttribute("aria-disabled"), "true");
    assert.match(await page.locator(`#${await openButton.getAttribute("aria-describedby")}`).innerText(), /Workflow tab is not on the API yet/);
    assert.deepEqual(calls("/api/v1/requests")[0].query, { limit: "25" }, "the first page: 25 rows, no filter");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("2 cursor paging: forward to the last page and back, each row one time; search and status are API parameters", async () => {
    const { context, page, errors } = await fresh();
    await open(page);
    const seen = [];
    const ranges = [];
    const next = page.getByRole("button", { name: "Next ›" }).first(), prev = page.getByRole("button", { name: "‹ Previous" }).first();
    assert.equal(await prev.getAttribute("aria-disabled"), "true", "no page before the first");
    // 61 rows are three pages. One more turn than that means that Next did not go off on the last page.
    for (let turn = 0; ; turn++) {
      assert.ok(turn < 3, "Next is off on the last page");
      ranges.push(await range(page));
      seen.push(...(await rows(page)).map((r) => r[0]));
      if (await next.getAttribute("aria-disabled") === "true") break;
      await next.click();
      await waitRange(page, ranges.length === 1 ? "26–50 of 61" : "51–61 of 61");
    }
    assert.deepEqual(ranges, ["1–25 of 61 · newest first", "26–50 of 61 · newest first", "51–61 of 61 · newest first"]);
    assert.deepEqual(seen, sixtyOne.map((r) => r.requestId), "each request one time, newest first");
    await prev.click();
    await waitRange(page, "26–50 of 61");
    assert.deepEqual(await rows(page), sixtyOne.slice(25, 50).map(expectedRow), "the page before, cell by cell");
    // Two moves forward sent two cursors of the API. The move back shows a page that Query still holds (15 seconds).
    assert.equal(calls("/api/v1/requests").filter((c) => c.query.cursor).length, 2, "each new page sends the cursor of the API");

    await page.getByRole("textbox", { name: "Find a request" }).fill("LEDGER");
    await waitRange(page, "1–25 of 30 · newest first");
    const searched = calls("/api/v1/requests").at(-1).query;
    assert.deepEqual(searched, { limit: "25", q: "LEDGER" }, "the search goes to the API, and the page starts again without a cursor");
    assert.ok((await rows(page)).every((r) => r[2].startsWith("ledger-")));
    await page.getByRole("group", { name: "Status" }).getByRole("button", { name: "Open", exact: true }).click();
    const wanted = sixtyOne.filter((r) => r.namespace.startsWith("ledger-") && ["pending_approval", "approved", "pr_open", "merged", "awaiting_prune", "sync_failed"].includes(r.status));
    assert.ok(wanted.length > 0 && wanted.length < 25, "one page of open ledger requests");
    await waitRange(page, `1–${wanted.length} of ${wanted.length} · newest first`);
    assert.deepEqual(calls("/api/v1/requests").at(-1).query, { limit: "25", q: "LEDGER", state: "open" });
    assert.deepEqual(await rows(page), wanted.map(expectedRow));
    assert.equal(new URL(page.url()).hash, "#requests?q=LEDGER&state=open", "the address holds the view");

    // The same address in a new page: the tokens were in memory only, so the portal signs in again and returns to the view.
    const again = await context.newPage();
    await again.goto(page.url());
    await again.locator("table[aria-label=Requests] tbody tr").first().waitFor();
    assert.equal(new URL(again.url()).hash, "#requests?q=LEDGER&state=open");
    assert.equal(await again.getByRole("textbox", { name: "Find a request" }).inputValue(), "LEDGER");
    assert.deepEqual(await rows(again), wanted.map(expectedRow));
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("3 loading, then empty with the mockup's words", async () => {
    const { context, page, errors } = await fresh({ mode: "empty" });
    api.state.delayMs = 700;
    await page.goto(`${portal.page}#requests`);
    await page.getByRole("status").filter({ hasText: "Loading requests…" }).waitFor();
    await panel(page).getByText("No requests on the nonprod instance match this search and filter.").waitFor();
    assert.equal(await range(page), "0 requests");
    assert.equal(await page.getByRole("status").filter({ hasText: "Loading requests…" }).count(), 0);
    assert.deepEqual(await rows(page), []);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("3 a 403 shows the problem's detail and offers no action", async () => {
    const { context, page, errors } = await fresh({ mode: "forbidden" });
    expectedStatus = [403];
    await open(page);
    await panel(page).getByRole("heading", { name: "You do not have permission to see requests." }).waitFor();
    assert.match(await panel(page).innerText(), /Missing permission requests:read: no role in your token grants it/);
    assert.equal(await panel(page).getByRole("button").count(), 0, "no button: no retry, no filter, no row");
    assert.equal(await panel(page).locator("table").count(), 0);
    assert.equal(calls("/api/v1/requests").length, 1, "the portal does not ask again");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("3 a 401: one silent renewal and the same call again; then, with the session ended, sign-in again", async () => {
    const { context, page, errors } = await fresh({ mode: "expire-once" });
    expectedStatus = [401, 400];
    await open(page);
    await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
    assert.deepEqual(issuer.state.seen.filter((s) => s.what === "token").map((s) => s.grant), ["authorization_code", "refresh_token"], "one renewal, with the refresh token");
    assert.equal(issuer.state.seen.filter((s) => s.what === "auth").length, 1, "no second visit to the issuer");
    assert.equal((await rows(page)).length, 25, "the rows are there: the person saw no error");

    // The session ends: the API refuses the token and the issuer refuses the refresh token.
    api.state.mode = "always401";
    issuer.state.sessions = false;
    issuer.state.user = null;
    await page.getByRole("group", { name: "Status" }).getByRole("button", { name: "Closed", exact: true }).click();
    await page.getByRole("heading", { name: "Sign-in did not complete." }).waitFor();
    await page.getByRole("button", { name: "Sign in again" }).click();
    await page.waitForURL((url) => url.href.startsWith(AUTH));
    assert.equal(issuer.state.seen.filter((s) => s.what === "token" && s.grant === "refresh_token").length, 2, "one more renewal try, and no more");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("3 a 5xx shows the problem's detail, and Try again sends the call again", async () => {
    const { context, page, errors } = await fresh({ mode: "error500" });
    expectedStatus = [500];
    await open(page);
    const alert = panel(page).locator(".pf-v6-c-alert");
    await alert.getByText("The requests did not load.").waitFor();
    assert.match(await alert.innerText(), /The database did not answer\./);
    assert.match(await alert.getAttribute("class"), /pf-m-danger/);
    assert.equal(calls("/api/v1/requests").length, 1, "no retry until the person asks");
    api.state.mode = "ok";
    await alert.getByRole("button", { name: "Try again" }).click();
    await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
    assert.equal(await alert.count(), 0);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("5 a role sees the tabs that GET /api/v1/me permits: a viewer, an approver, a requester", async () => {
    // The stand-in's access token is an opaque string, so the browser cannot read a role from it.
    const base = ["Workflow", "Quotas", "Expiration", "Requests", "Policies", "Capacity"];
    const want = {
      viewer: base,
      approver: ["Workflow", "Quotas", "Expiration", "Requests", "Approvals", "Policies", "Capacity"],
      requester: ["Workflow", "New namespace", "Quotas", "Expiration", "Requests", "Policies", "Capacity"]
    };
    for (const [user, tabs] of Object.entries(want)) {
      const { context, page, errors } = await fresh({ user });
      await open(page);
      assert.deepEqual(await tabNames(page), tabs, user);
      assert.match(await page.locator("header").innerText(), new RegExp(`${USERS[user].username}\\s*${USERS[user].role} \\(Keycloak roles\\)`), "the name and the roles come from /me");
      // A tab that the person does not hold is not reachable by its address either.
      await page.goto(`${portal.page}#approvals`);
      await page.reload();
      await page.locator("[role=tablist]").waitFor();
      const selected = await page.getByRole("tab", { selected: true }).innerText();
      assert.equal(selected, tabs.includes("Approvals") ? "Approvals" : "Workflow", `${user}: #approvals`);
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("6 the tab says what the mockup says, and adds only what is listed", async () => {
    const { context, page, errors } = await fresh({ items: [recorded] });
    await open(page);
    // The mockup's block of the tab, as text: each tag out, each {{hole}} a break.
    const mockup = readFileSync(join(app, "..", "mockups", "portal", "Main.dc.html"), "utf8");
    const block = mockup.slice(mockup.indexOf('<sc-if value="{{isRequests}}"'), mockup.indexOf('<sc-if value="{{isApprovals}}"'));
    const attrs = [...block.matchAll(/(?:placeholder|aria-label)="([^"{]+)"/g)].map((m) => m[1]);
    const texts = block.replace(/<[^>]+>/g, "\n").split(/\n|\{\{[^}]+\}\}/).map((s) => s.replace(/\s+/g, " ").trim()).filter(Boolean);
    const chips = ["All", "Open", "Closed"]; // reqFilters in the mockup's logic
    // The mockup's replay buttons open its sample scenarios. The portal has none (MOCKUP-CONTRACT.md).
    const MOCKUP_ONLY = ["Replay a policy rejection", "Replay a wrong-instance request"];
    const fromMockup = [...texts, ...attrs, ...chips].filter((s) => !MOCKUP_ONLY.includes(s));
    assert.ok(fromMockup.length >= 20, `the mockup's block was read (${fromMockup.length} strings)`);
    const read = () => panel(page).evaluate((root) => {
      const found = [];
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) if (walker.currentNode.nodeValue.trim()) found.push(walker.currentNode.nodeValue.replace(/\s+/g, " ").trim());
      root.querySelectorAll("[placeholder]").forEach((el) => found.push(el.getAttribute("placeholder")));
      root.querySelectorAll("[aria-label]").forEach((el) => found.push(el.getAttribute("aria-label")));
      return found;
    });
    // Two states of the tab: one request, and no request. The mockup's sentence for an empty list shows only in the second.
    const shown = await read();
    api.state.mode = "empty";
    await page.getByRole("group", { name: "Status" }).getByRole("button", { name: "Closed", exact: true }).click();
    await waitRange(page, "0 requests");
    shown.push(...await read());
    const squeeze = (text) => text.replace(/\s+/g, "");
    const all = squeeze(shown.join(" "));
    const missing = fromMockup.filter((text) => !all.includes(squeeze(text)));
    assert.deepEqual(missing, [], "each string of the mockup's tab is on the page");
    // What the page adds: the data, PatternFly's own words for a screen reader, and the one line that MOCKUP-CONTRACT.md lists.
    const data = [...expectedRow(recorded), "plan_needs_approval", "by ola", "1–1 of 1 · newest first", "0 requests", "nonprod"];
    const LIBRARY = ["Reset", "Warning alert:"];
    const ADDED = ["Open at current step is off: the Workflow tab is not on the API yet."];
    const known = [...fromMockup, ...data, ...LIBRARY, ...ADDED].sort((x, y) => y.length - x.length);
    const invented = shown.filter((text) => known.reduce((rest, k) => rest.split(k).join(""), text).trim() !== "");
    assert.deepEqual(invented, [], "no string that the mockup does not have");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("7 layout at 390, 820 and 1440 px in each theme, and axe at phone and desktop width", async () => {
    for (const width of [390, 820, 1440]) {
      const { context, page, errors } = await fresh({ width });
      await open(page);
      await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
      for (const theme of ["light", "dark"]) {
        await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
        const layout = await page.evaluate(() => {
          const main = document.querySelector(".pf-v6-c-page__main-container") ?? document.documentElement;
          return { doc: document.documentElement.scrollWidth - document.documentElement.clientWidth, main: main.scrollWidth - main.clientWidth, text: document.body.innerText };
        });
        assert.ok(layout.doc <= 0 && layout.main <= 0, `${width} ${theme}: no sideways scroll (${layout.doc}, ${layout.main})`);
        assert.doesNotMatch(layout.text, /\{\{|undefined|NaN|\[object/, `${width} ${theme}: no leftover placeholder`);
        assert.ok(await page.getByRole("tab", { name: "Requests" }).count(), `${width}: the tab is reachable`);
        await page.screenshot({ path: join(out, `requests-${width}-${theme}.png`), fullPage: true });
        if (width !== 820) {
          const scan = await new AxeBuilder({ page }).analyze();
          assert.deepEqual(scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.html}`), [], `axe at ${width} ${theme}`);
        }
      }
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("sign out ends the session at the issuer", async () => {
    const { context, page, errors } = await fresh();
    await open(page);
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL((url) => url.href.startsWith(AUTH));
    const logout = issuer.state.seen.find((s) => s.what === "logout");
    assert.ok(logout, "the browser went to the end-session endpoint");
    assert.equal(logout.query.post_logout_redirect_uri, portal.page);
    assert.equal(logout.query.id_token_hint, undefined, "no ID token in the logout URL; a real issuer may ask for confirmation");
    assert.equal(logout.query.client_id, "cmapi-portal");
    assert.deepEqual(errors, []);
    await context.close();
  });

  console.log(`ok - portal on the API: ${done.length} checks, ${browser.browserType().name()} ${browser.version()}`);
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  // A check that timed out can still hold the browser: do not wait for it longer than this.
  await Promise.race([browser.close(), new Promise((resolve) => setTimeout(resolve, 5000))]);
  portal.close();
  api.close();
  issuer.close();
  // The servers keep their sockets open for a moment. The result is known, so end now.
  process.exit(process.exitCode ?? 0);
}
```
