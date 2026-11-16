# Review of #205 (SEC-09): exact redirect URIs of the portal client

One second reader, as the rule for a change to sign-in says: Codex `gpt-6.1-sol`, on an export of `c99887a`, on 2026-11-14. [`brief.md`](brief.md) has the six claims. [`reviewer-1-report.md`](reviewer-1-report.md) is its report, unchanged. Fable 5.2 wrote the change, ran each test and ruled.

## The rulings

| Finding | Claim | Ruling | Before | After |
|---|---|---|---|---|
| F1 The chart took `http://localhost/` with no port. Keycloak matches a loopback URI with no port against each port (`RedirectUtils`, Keycloak 26.6.4, lines 96 to 98), so a listener on another port could get the redirect | C4 | Accepted, with the reviewer's fix: `http` needs a loopback host and an explicit port. The CRC realm has no `http` URI, so the finding is about a local realm | 6 cases of `test_the_chart_refuses_a_redirect_uri_that_is_not_exact` fail | Pass |
| Not a finding of the reviewer, from its table of C4: the guard took `https://`, `https:///callback`, a URI with a space or a newline, an upper-case host, and a host with no path | C4 | Fable 5.2 made the guard a full match: `https://host[:port]/path` with a lower-case host and no space. No bypass was shown; the values are not ones that a browser sends | 6 more cases fail | Pass |

Confirmed with no finding: C1 (no client of the import has `*`, and Keycloak has no pattern character other than a `*` at the end), C2 (the two URIs are each value that the portal sends from the root of its host), C3 (`+` gives the two URIs for logout and the one origin for Keycloak's CORS), C5 (the guard reads each redirect list that the chart renders) and C6 (no script, test or document step used the `localhost` URI).

## What the review found outside the change

- **Keycloak's own clients.** A realm gets `security-admin-console`, `account` and `account-console` from Keycloak, each with a redirect URI that ends in `*`. The import does not name them. This is #220 (SEC-10).
- **A portal that is not at the root of its host.** The two URIs are for `https://<portal>/`. A portal on another port or below a path sends another address, and that address must be in `portalRedirects`. `docs/15` says so.

## Not proven

Keycloak's own answer to a redirect URI that is not in the list. The reviewer read the tagged source; no Keycloak ran (#157). No second reviewer read the fixes after they were applied.
