# Security review: exact redirect URIs of the public client cmapi-portal (cmapi issue #205, SEC-09)

You are reviewer 1. You work in this folder only: it is an export of the commit in `EXPORT-HEAD`, not a repository. `change.diff` is the whole change against the base `418e934`. Write each finding to `REPORT.md` in this folder as you go. Do not start a container, a cluster or a network service. Do not run `cmapi/tests/service` with a database. You can run: `cd cmapi && PYTHONPATH=src:tests/service python3 -m pytest tests/service/test_plain_manifests.py tests/service/test_review_g_chart.py -q -W ignore` (needs pytest, pyyaml and `helm` on PATH; these two files open no database). If a tool is not there, read and reason, and say so.

## The files to read, in full
- `deploy/helm/cmapi/templates/keycloak-realm.yaml` lines 1 to 45 (the new guard) and the clients `cmapi-portal` and `cmapi-docs`
- `deploy/helm/cmapi/values.yaml` (`keycloak.realm`), `deploy/environments/crc.yaml`
- `deploy/manifests/environments/crc/realm/10-realm-import.yaml`, the clients `cmapi-portal` and `cmapi-docs`
- `cmapi-portal-ui/src/portal/auth.ts` (which `redirect_uri` and `post_logout_redirect_uri` the portal sends)
- `docs/15-keycloak-integration.md`, section "The redirect URIs of the portal"
- `cmapi/tests/service/test_plain_manifests.py::test_crc_public_clients_take_exact_redirect_uris_only`, and the three new tests at the end of `cmapi/tests/service/test_review_g_chart.py`

## The claims. Confirm or refute each one, with the file and the line.
- C1. After the change no client of the CRC realm (plain manifests and chart with `deploy/environments/crc.yaml`) has a redirect URI with `*`, and Keycloak 26 treats each of the listed URIs as an exact string (no pattern character other than `*` exists in Keycloak's matching: check `RedirectUtils` of Keycloak 26 from your knowledge, and say how sure you are).
- C2. The two URIs `https://cmapi-portal.apps-crc.testing/` and `https://cmapi-portal.apps-crc.testing/index.html` are each value that `cmapi-portal-ui/src/portal/auth.ts` can send as `redirect_uri` or `post_logout_redirect_uri` when the portal is served at the root of its host. Name a URL of the built portal (a path, a trailing slash, an upper-case host, a port) from which sign-in would now fail with `Invalid parameter: redirect_uri`.
- C3. `post.logout.redirect.uris: "+"` and `webOrigins: ["+"]` with exact redirect URIs give exactly the two URIs for logout and exactly the origin `https://cmapi-portal.apps-crc.testing` for Keycloak's CORS. Say if `+` has another meaning in Keycloak 26 for either attribute.
- C4. The chart guard (`fail`) cannot be passed by a value that Keycloak would read as a wildcard or as a non-https URI: check the regular expression for `http://localhost`, hosts such as `http://localhost.evil.example/`, `http://localhost@evil.example/`, `http://127.0.0.1.evil.example/`, `HTTPS://`, a URI with a space or a newline, an empty string, and a list entry that is not a string. Helm's `regexMatch` is Go RE2 and the pattern is inside a Go template string: check the escaping as written in the file.
- C5. The guard covers each list of redirect URIs that the chart renders for a public client. Name a client of the chart with a redirect URI or a `rootUrl`, `baseUrl` or `adminUrl` that the guard does not read.
- C6. Removing `http://localhost:5173/*` breaks no script, test or document step of the repository (search `deploy/`, `docs/13-crc-deployment.md`, `cmapi-portal-ui/`, `.github/workflows/ci.yml`).

## For each finding
Give: the claim it breaks, the file and line, why it is wrong, the full code of the fix (a unified diff against this export), and a test in the form of the tests named above that fails before the fix and passes after it. Run it if the tools are there. A finding with no failing test is listed as "not proven". Also list what you checked and found correct, one line each.

## Not in this review
CORS on the API (#206), the portal's code other than the two values it sends, and the choice between a browser-only client and a backend for frontend.
