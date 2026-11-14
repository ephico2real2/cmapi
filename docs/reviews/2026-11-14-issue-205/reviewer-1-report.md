# SEC-09 / issue #205 — reviewer 1

Export: `c99887a7ee8e9d8affe164cd00b9db4d9d826ab9` (`EXPORT-HEAD`); base: `418e934`; reviewed `change.diff` and all requested file sections.

**Result: one low-severity finding in the chart's optional local-realm configuration.** The shipped CRC portal/docs allowlists are exact HTTPS URIs. No wildcard or non-loopback HTTP bypass was found for those CRC values.

## F1 — Require an explicit port for HTTP loopback redirects (low)

**Claim affected:** C4's guarantee against semantically wildcard redirects; this is a port-matching exception, not a second wildcard character. **Location:** `deploy/helm/cmapi/templates/keycloak-realm.yaml:37`, the optional `(:[0-9]+)?` port. Both lists at line 29 are affected.

The chart accepts `http://localhost/`, `http://127.0.0.1/` and `http://[::1]/`. Keycloak retries HTTP loopback matches with port 80, which its URI builder omits. Thus registering `http://localhost/` also permits `http://localhost:49152/`. A local listener can receive a redirect on an unregistered port. The CRC defaults contain no HTTP loopback URI, so this finding requires custom chart values.

This behavior is source-verified in [Keycloak 26.6.4 RedirectUtils, lines 96–98](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/utils/RedirectUtils.java#L96) and [KeycloakUriBuilder, line 495](https://github.com/keycloak/keycloak/blob/26.6.4/common/src/main/java/org/keycloak/common/util/KeycloakUriBuilder.java#L495). It is also present in 26.0.0. Confidence: high from source; no live Keycloak experiment was performed.

**Fix:** require an explicit port in the HTTP loopback exception. This preserves the existing `:5173` developer example and positive test. The full diff below adds all six failing cases to the existing parameterized chart test: both guarded lists, each of the three loopback hosts.

```diff
--- a/deploy/helm/cmapi/templates/keycloak-realm.yaml
+++ b/deploy/helm/cmapi/templates/keycloak-realm.yaml
@@ -34,8 +34,8 @@
 {{- if contains "#" $uri }}
 {{- fail (printf "keycloak.realm.%s: %q has a fragment, which a redirect URI must not have (RFC 6749, section 3.1.2)" $key $uri) }}
 {{- end }}
-{{- if not (or (hasPrefix "https://" $uri) (regexMatch "^http://(localhost|127\\.0\\.0\\.1|\\[::1\\])(:[0-9]+)?/" $uri)) }}
-{{- fail (printf "keycloak.realm.%s: %q must be an https URI. http is for localhost only" $key $uri) }}
+{{- if not (or (hasPrefix "https://" $uri) (regexMatch "^http://(localhost|127\\.0\\.0\\.1|\\[::1\\]):[0-9]+/" $uri)) }}
+{{- fail (printf "keycloak.realm.%s: %q must be an https URI. http is for localhost with an explicit port only" $key $uri) }}
 {{- end }}
 {{- end }}
 {{- end }}
--- a/cmapi/tests/service/test_review_g_chart.py
+++ b/cmapi/tests/service/test_review_g_chart.py
@@ -180,6 +180,12 @@
     ("docsRedirects", "https://cmapi-api.apps-crc.testing/docs/*", "has a wildcard"),
     ("portalRedirects", "http://cmapi-portal.apps-crc.testing/", "must be an https URI"),
     ("portalRedirects", "http://localhost.evil.example/", "must be an https URI"),
+    ("portalRedirects", "http://localhost/", "must be an https URI"),
+    ("portalRedirects", "http://127.0.0.1/", "must be an https URI"),
+    ("portalRedirects", "http://[::1]/", "must be an https URI"),
+    ("docsRedirects", "http://localhost/", "must be an https URI"),
+    ("docsRedirects", "http://127.0.0.1/", "must be an https URI"),
+    ("docsRedirects", "http://[::1]/", "must be an https URI"),
     ("portalRedirects", "cmapi-portal://callback", "must be an https URI"),
     ("portalRedirects", "https://cmapi-portal.apps-crc.testing/#x", "has a fragment"),
 ])
```

**Regression proof:** with the six added cases and the exported guard, **6 failed, 10 passed**; with the proposed guard, **16 passed**. The ten existing SEC-09 cases remain green, including the explicit-port localhost positive case. This is a failing chart-policy test before the fix and a passing test after it; server matching is verified from source. The source and test files were restored afterward; this report contains the proposed change.

Command used for both runs, from `cmapi/` after adding the six rows:

```sh
PYTHONPATH=src:tests/service python3.13 -m pytest --noconftest \
  tests/service/test_plain_manifests.py::test_crc_public_clients_take_exact_redirect_uris_only \
  tests/service/test_review_g_chart.py::test_the_chart_gives_the_portal_client_exact_redirect_uris \
  tests/service/test_review_g_chart.py::test_the_chart_refuses_a_redirect_uri_that_is_not_exact \
  tests/service/test_review_g_chart.py::test_the_chart_takes_a_localhost_redirect_for_a_local_realm \
  -q -W ignore
```

## Claim decisions

### C1 — Confirmed for the clients explicitly exported/rendered; qualify “realm”

`deploy/environments/crc.yaml:35–36`, chart `keycloak-realm.yaml:165,175`, and plain import `10-realm-import.yaml:261–265,285–288` contain only the two portal HTTPS URIs and the exact docs callback. The other explicitly declared clients have no redirect URI. The all-client wildcard assertions in `test_plain_manifests.py:270–271` and `test_review_g_chart.py:175` pass.

For these absolute HTTPS values, Keycloak compares the whole string. It has no additional glob/regex character; query delimiters, dots and `+` in a URI do not become patterns. There are separate relative-resolution and HTTP-loopback exceptions; F1 concerns the latter. Confidence is high after checking [RedirectUtils 26.6.4, lines 55–66 and 163–220](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/utils/RedirectUtils.java#L163), against 26.0.0 as well.

If “no client of the CRC realm” means every client on a running Keycloak, that broader statement is false: omitted built-ins are created by Keycloak. For example `security-admin-console` gets `/admin/cmapi/console/*`; `account` and `account-console` get account-path wildcards. These are not chart-rendered clients or a regression introduced here. See [RealmManager 26.0.0, lines 164–178, 383–429 and 503–512](https://github.com/keycloak/keycloak/blob/26.0.0/services/src/main/java/org/keycloak/services/managers/RealmManager.java#L503). The static tests establish properties of the import, not an exhaustive live realm inventory.

### C2 — Confirmed for root hosting; other addresses require explicit registration

`cmapi-portal-ui/src/portal/auth.ts:92` computes `location.origin + location.pathname`; lines 96–97 use it for both redirect parameters, and line 66 sends the configured logout value. Consequently both `/` and `/index.html` are possible, with query and fragment removed. `docs/15-keycloak-integration.md:179` accurately describes these root-hosted addresses.

Evaluated the same expression using Node's WHATWG `URL` implementation, without starting a server:

| Address of the page | Value sent for either redirect parameter | CRC match |
|---|---|---|
| `https://cmapi-portal.apps-crc.testing` | `https://cmapi-portal.apps-crc.testing/` | Yes |
| `https://cmapi-portal.apps-crc.testing/index.html?x=1#requests` | `https://cmapi-portal.apps-crc.testing/index.html` | Yes |
| `https://CMAPI-PORTAL.APPS-CRC.TESTING/` | `https://cmapi-portal.apps-crc.testing/` | Yes: browser lowercases host |
| `https://cmapi-portal.apps-crc.testing:443/` | `https://cmapi-portal.apps-crc.testing/` | Yes: browser removes default port |
| `https://cmapi-portal.apps-crc.testing:8443/` | Same address including `:8443` | No |
| `https://cmapi-portal.apps-crc.testing/index.html/` | Same address including trailing slash | No |
| `https://cmapi-portal.apps-crc.testing/portal/index.html` | Same address including `/portal/index.html` | No |

A concrete failing address is **`https://cmapi-portal.apps-crc.testing:8443/`**, if the built portal is exposed there: its `redirect_uri` is absent from the list and would get `Invalid parameter: redirect_uri`. The subdirectory example is also relevant to builds: `cmapi-portal-ui/vite.config.ts:4–5` intentionally permits serving the bundle from any folder. These are conditional serving examples, not claims that a listener or a portal deployment currently exists. Root hosting is the claim's premise; this is not a defect in that allowlist.

### C3 — Confirmed; `+` has two attribute-specific inheritance meanings

Chart `keycloak-realm.yaml:164–166` and plain import `10-realm-import.yaml:259–265` configure exactly `+`, with no additional entries.

For logout it adds the client's registered redirect URIs to any separately configured logout URIs, giving exactly the two portal URLs here. It is not “any logout URI.” See [OIDCAdvancedConfigWrapper 26.6.4, lines 432–455](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/OIDCAdvancedConfigWrapper.java#L432).

For `webOrigins` it replaces the marker with origins extracted from HTTP(S) redirect URIs, alongside any separately configured origins. Here the resulting set is exactly `{https://cmapi-portal.apps-crc.testing}`. It is not `*` and does not grant all origins. See [WebOriginsUtils 26.6.4, lines 30–43](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/utils/WebOriginsUtils.java#L30). Neither attribute gives `+` another unrestricted-access meaning. No API CORS assessment was made.

### C4 — Refuted for semantic exactness by F1; tested exclusion boundaries otherwise hold

At `keycloak-realm.yaml:37`, the Go template string's `\\.` and `\\[`/`\\]` produce RE2 `\.` and `\[`/`\]`. The dots and IPv6 brackets are escaped correctly. The initial `^` and the required slash immediately after the optional numeric port constrain the HTTP authority; the expression intentionally does not anchor the path's end.

Actual `helm template` results on the export:

| List entry | Result |
|---|---|
| `http://localhost` | Rejected: required slash absent |
| `http://localhost/` | Accepted; implicit arbitrary-port behavior is F1 |
| `http://localhost:5173/` | Accepted |
| `http://127.0.0.1:5173/index.html` | Accepted |
| `http://[::1]:5173/` | Accepted |
| `http://localhost.evil.example/` | Rejected |
| `http://localhost@evil.example/` | Rejected |
| `http://127.0.0.1.evil.example/` | Rejected |
| `http://127x0x0x1/` | Rejected; confirms literal dots |
| `HTTPS://cmapi-portal.apps-crc.testing/` | Rejected; policy is stricter than scheme case-insensitivity |
| Empty string | Rejected |
| Number, null, boolean, mapping, nested list | Rejected by the string type error at line 31; no rendered bypass, although not a tailored `fail` message |
| `https://cmapi-portal.apps-crc.testing/a b` | Accepted |
| `https://cmapi-portal.apps-crc.testing/` followed by a literal newline | Accepted |
| `http://localhost/a b` or the same base followed by a newline | Accepted |
| `https://` or `https:///callback` | Accepted |
| `https://cmapi-portal.apps-crc.testing/*` | Rejected at line 32 |
| `https://cmapi-portal.apps-crc.testing/#x` | Rejected at line 35 |
| `https://cmapi-portal.apps-crc.testing/%2A` | Accepted; encoded asterisk is not a wildcard |
| `https://cmapi-portal.apps-crc.testing/?x=1` | Accepted; exact query-bearing URI |

The guard is not a complete URI syntax validator. Spaces/newlines and hostless HTTPS-prefix strings are accepted, so do not claim that every passing value is usable. A wildcard or remote-HTTP bypass from these malformed values is **not proven**; they are not counted as additional security findings. Empty lists/default `[]` likewise are not checked for browser-login usability (`values.yaml:71–72`).

### C5 — Confirmed; no such chart-rendered client exists

The guard reads `portalRedirects` and `docsRedirects` at `keycloak-realm.yaml:29–30`; the only rendered `redirectUris` occur at lines 165 and 175, reading those exact keys. No declared client in lines 141–226 has `rootUrl`, `baseUrl` or `adminUrl`. In particular `cmapi-cli` at lines 178–186 uses device flow and has no redirect URI. Therefore there is no chart-rendered client with one of the requested unguarded fields to name.

`auth.adminUrl` in `values.yaml:54` configures backend access to Keycloak; it is not a client `adminUrl`. Keycloak-created built-ins described under C1 are a separate runtime boundary, not missing chart list validation. The guard is conditional on realm import being enabled (`keycloak-realm.yaml:1`), as is the resource itself.

### C6 — Confirmed within the requested search scope

Searched `deploy/`, `docs/13-crc-deployment.md`, `cmapi-portal-ui/` and `.github/workflows/ci.yml` for port 5173, localhost, client IDs and redirect parameters, and inspected the relevant callers. No script, test or document step in that scope requires the removed shared-realm localhost wildcard.

The live-realm test signs in as `cmapi-docs` with its exact HTTPS callback (`deploy/tests/realm-test.py:132–139`); CRC proof does likewise (`deploy/crc-proof.sh:92`), and CI invokes that realm test (`.github/workflows/ci.yml:204–205`). Portal tests configure their own issuer allowlist from `portal.page` (`cmapi-portal-ui/tests/api/portal.test.mjs:18–21`); the stand-in compares it exactly (`standin.mjs:94,136`), independently of the CRC import. CI runs those tests at `.github/workflows/ci.yml:89–90`. A manually configured localhost browser pointed at the shared realm deliberately loses access, as documented in `docs/15-keycloak-integration.md:186`; no repository step promising that workflow was found.

## Validation and limits

- TokenSave context/status/read cannot serve this unindexed export; used direct reads without initializing an index or querying another checkout.
- Helm is available; default `python3` lacks pytest. Python 3.13 has pytest 9.0.2 and PyYAML 6.0.2.
- The prescribed test invocation with Python 3.13 stops during `conftest.py` loading because PyJWT is missing.
- Running the two permitted files with `--noconftest` gives **78 passed, 2 failed**: `test_the_local_realm_users_are_in_groups_the_realm_has` lacks SQLAlchemy; `test_every_console_script_resolves` lacks FastAPI, prometheus_client and SQLAlchemy. These are environment failures, not SEC-09 assertions.
- The four requested SEC-09 test functions expand to **10 passing cases** on the untouched export; F1's added cases and proposed fix produce the before/after results above.
- Used only local Helm rendering and local Python/Node processes; no container, cluster, database or network service was started. No browser/server integration test was run. Java has no installed runtime, so Keycloak behavior was checked against tagged source.
- Review changes retained: `REPORT.md` only; the trial chart/test modifications were restored.

## Checked and found correct

- CRC values and plain import register the same two portal URLs and exact docs callback (`crc.yaml:35–36`; import lines 262–263,286).
- Both portal redirect parameters use the page's origin and pathname (`auth.ts:92,96–97`).
- Logout `+` inherits the two redirects; CORS `+` derives the single portal origin (chart lines 164–166).
- Literal wildcards and fragments fail before rendering (chart lines 31–35).
- The HTTP regex rejects lookalike hosts and user-info tricks, and its template escaping is correct (chart line 37).
- Both chart-rendered redirect lists are guarded; there are no client URL fields bypassing that loop (chart lines 29–30,165,175).
- The new plain-manifest test checks every declared client's redirects for wildcards (test lines 270–271).
- The three new chart test functions cover CRC output, bad values and explicit-port loopback acceptance (test lines 170–200).
- The portal redirect documentation correctly states the root-hosted URLs and local-development realm choice (docs/15 lines 177–189).
- The requested deployment, portal and CI search reveals no dependency on the removed shared-realm localhost wildcard.
