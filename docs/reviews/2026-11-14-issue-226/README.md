# #226 and #206: nginx as the front door of each instance, one origin

OB1 run 6 (Opus 5.5 at high) wrote the code, the tests and this record on 2026-11-14. Fable reviews it later.
This change decides which origins and paths reach the API, so it gets a second reader (Codex): see "Review" below.

## The owner's decisions

- #226, 2026-11-14: "let's keep nginx for now and we can google how best to configure it very well." Each instance
  gets one front door: nginx serves the portal at `/` and sends the API's paths to the API pods, on one origin.
- #206: the portal must reach a deployed API. With one origin it needs no CORS. #219 made CORS off unless
  `cors.allowedOrigins` lists an origin; that stays.

## What is built

| Part | Where |
|---|---|
| The image: nginx 1.30.6 (stable) with the portal's build and the mockup | `cmapi-portal-ui/Containerfile` |
| The configuration, as code: the main file, one site template, and the included files | `cmapi-portal-ui/nginx/` |
| A start check that refuses a missing or malformed value | `cmapi-portal-ui/nginx/16-cmapi-check-env.envsh` |
| The chart: the front door Deployment, its Service and NetworkPolicy, the API's headless Service, one Route or Ingress for the instance and one for the mockup; the API has no Route or Ingress of its own | `deploy/helm/cmapi/templates/portal.yaml`, `exposure.yaml`, `api.yaml`, `monitoring.yaml` |
| CRC's values: the instance's host is `cmapi.apps-crc.testing` | `deploy/environments/crc.yaml` |
| The tests | `deploy/tests/front-door-test.py`, `cmapi-portal-ui/tests/front-door.test.mjs`, `cmapi/tests/service/test_front_door_chart.py` |

Not in this pull request: the plain manifests (`deploy/manifests/`), `deploy/render.sh` and the Wave 1 scripts still
use the API's own Route `cmapi-api.apps-crc.testing`. They move to the front door in the next pull request of #226,
which closes it: branch `front-door-plain`, recorded in "The plain manifests" below.

## Decisions, with the options not taken

### One host for the instance

The front door's host carries the portal at `/`, the API at `/api/v1`, Swagger UI at `/docs`, ReDoc at `/redoc`, the
OpenAPI document and the problem pages. The CLI, the SDK and the pipelines use the same host. On CRC it is
`cmapi.apps-crc.testing`, so `publicUrl`, `portalUrl`, the realm's redirect URIs and the problem type base name it.

| Option | Why not |
|---|---|
| Keep the API's own Route beside the front door | A second way in skips the front door's security headers, its access log and its limits. The NetworkPolicy now lets only the front door's pods reach the API port, so that Route could not work |
| Name the host after the portal (`cmapi-portal`) | The host serves the whole instance, as the production names do (`cmapi.ephico2real.com`, `cmapi-staging.ephico2real.com`) |

RFC 10017, section 9.4, calls one application per origin a best practice. The portal keeps its tokens in memory, not in
storage, and each kind of page gets its own Content-Security-Policy (below). Those two hold the risk that Swagger UI,
ReDoc and the portal share an origin. `docs/15`, "The portal's origin and the API", gives the comparison.

### The API pods through a headless Service

nginx resolves `cmapi-api-pods.<namespace>.svc.<cluster domain>`, a headless Service, with `server ... resolve`. Its DNS
answer lists the ready API pods only. So nginx balances over each pod, sends a failed idempotent request to another
pod, and stops sending to a pod that fails (`max_fails=2 fail_timeout=10s`). `resolver ... valid=5s` bounds how long a
pod that left the Service can still get a new request. The resolver is the pod's own DNS server, from
`/etc/resolv.conf`, through the image's `15-local-resolvers.envsh`.

| Option | Why not |
|---|---|
| The API's ClusterIP Service | nginx sees one address. A failure marks the whole API down for `fail_timeout`, and a retry can reach the same pod |
| A list of pod addresses | Pods come and go: the list would need a reload |

nginx 1.27.3 made `resolve` and the upstream `resolver` part of the open-source build (ngx_http_upstream_module).

### Retries only for idempotent requests

`proxy_next_upstream error timeout http_502 http_503 http_504`, with `proxy_next_upstream_tries 2` and
`proxy_next_upstream_timeout 0`: the two tries bound the retries, and a time limit below `proxy_read_timeout` would stop a
GET that timed out on one pod from going to another (Codex's finding F3). nginx does not pass a POST, PATCH or LOCK to another server once it was sent
(ngx_http_proxy_module), and `non_idempotent` is not set. A create must not run twice: the Idempotency-Key of the API
is the client's way to repeat a write, not the front door's.

### Keepalive to the API

From nginx 1.29.7, proxying uses HTTP/1.1 with up to 32 idle connections for each worker by default
(ngx_http_upstream_module, `keepalive`), so the configuration sets no `proxy_http_version`, `Connection` or `keepalive`
line. A mutant test proved that those three lines changed nothing on 1.30.6, so they were removed. The one setting is
`keepalive_timeout 4s` in the upstream: uvicorn 0.32.1 (the pin) closes an idle connection after 5 s
(`timeout_keep_alive`), and nginx must close first. Otherwise a request can go out on a connection that uvicorn is
closing, and a POST that fails that way is not sent again.

### Timeouts and limits

| Setting | Value | Why |
|---|---|---|
| `proxy_connect_timeout` | 2 s | The pods are in the same namespace; a slow connect goes to another pod |
| `proxy_read_timeout`, API | 60 s | A plan with a dry run renders and validates the namespace's files |
| `proxy_read_timeout`, pages | 15 s | HTML and bundles |
| `client_max_body_size` | 1 MiB (also nginx's default, written to show the intent) | Each API body is a small JSON document; a larger one gets 413 and never reaches the API |
| `client_header_timeout`, `client_body_timeout` | 10 s | A slow client holds no worker connection for long |
| `worker_shutdown_timeout` | 20 s | A graceful stop ends within the pod's grace period |

### No rate limit in nginx

The limits that cmapi configures are per caller, by the token's subject, in the API (`cmapi/src/cmapi/core/ratelimit.py`).
#225 moves that limiter to PostgreSQL, so the limit holds whatever the replica count. nginx cannot see the subject
without validating the token, and `limit_req` keeps its counters in each nginx pod, so with N front door pods a caller
gets about N times the limit: the defect that #225 fixes in the API. So there is one source of truth for the limits:
the API. A limit for each client address, against a flood, belongs to the router if the platform wants one
(`haproxy.router.openshift.io/rate-limit-connections`, OpenShift's route annotations; DISA's OpenShift STIG V-257555
asks for it on application routes). That is the platform team's choice; it is not set here.

### The security headers, once

From the OWASP Secure Headers Project, `ci/headers_add.json` (`last_update_utc` 2026-10-18 07:04:36), on every
answer, also on errors (`always`): `Strict-Transport-Security: max-age=63072000; includeSubDomains`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`,
`Cross-Origin-Resource-Policy: same-origin`, `X-Permitted-Cross-Domain-Policies: none`, `X-DNS-Prefetch-Control: off`,
and OWASP's `Permissions-Policy` list. nginx drops the `add_header` lines of an outer level once a location has one
("inherited from the previous configuration level if and only if there are no add_header directives defined on the
current level", ngx_http_headers_module), so each location includes the common file again. A header that the front
door sets is hidden from the API's answer (`proxy_hide_header`), so the browser gets one value.

| Page | Content-Security-Policy | Why it differs from OWASP's `default-src 'self'` |
|---|---|---|
| The portal | `script-src 'self'; style-src 'self'`, `connect-src` and `form-action` add the issuer's origin, `frame-src 'none'`, `frame-ancestors 'none'` | The portal fetches tokens from the issuer and signs out with a form POST to it. It renews with the refresh token, not an iframe |
| Swagger UI, the problem pages | adds `'unsafe-inline'` for scripts and styles, and `worker-src blob:` | FastAPI's Swagger UI page starts from an inline script |
| ReDoc (`/redoc`) | the API's own policy for the page, `REDOC_CSP` in `cmapi/src/cmapi/main.py`: `default-src 'none'`, `script-src 'self' 'unsafe-eval'`, `connect-src 'self'`, `worker-src 'self' blob:` (Fable's review of PR #231) | The page has no inline script (#235). ReDoc's search workers need `'unsafe-eval'`: without it none starts (measured). The test checks that the two strings are equal |
| JSON and YAML of the API | `default-src 'none'; frame-ancestors 'none'` | Nothing in an API answer may load or run anything (OWASP REST Security Cheat Sheet) |
| The mockup | adds `'unsafe-inline'`, `'unsafe-eval'`, and Google Fonts' two hosts | The mockup is one file with its runtime inline; the runtime compiles the mockup's components; its design loads two fonts from Google Fonts. The mockup is the design source, so it is not changed |

OWASP headers not set, each with its reason:

| Header | Why not |
|---|---|
| `Cross-Origin-Embedder-Policy: require-corp` | The portal needs no cross-origin isolation, and the header blocks each cross-origin resource that does not opt in |
| `Cross-Origin-Opener-Policy` on Swagger UI | Swagger UI signs in through a popup, and its redirect page must reach `window.opener`. The portal and the mockup have `same-origin` |
| `Clear-Site-Data` | It belongs on a sign-out answer. The portal keeps its tokens in memory, so a sign-out leaves nothing to clear |
| `Cache-Control: no-store` on everything | Hashed assets are cached for a year (below). API answers get `no-store` when the API sets no `Cache-Control` of its own |
| CSP `upgrade-insecure-requests` | HSTS and the Route's `Redirect` policy already make every request https, and one origin has no http link to upgrade |

Not done, to do later: hashes for the inline scripts of Swagger UI, so that the docs pages need no `'unsafe-inline'`.
FastAPI writes the instance's sign-in settings into that script, so its hash differs for each instance; the API would
have to send the header.

### Caching and compression

Vite puts a content hash in each asset's name, so `/assets/` answers `Cache-Control: public, max-age=31536000,
immutable`. `index.html` and `config.json` answer `no-cache`: they name the current assets and the instance. gzip is on
for the static files only. `gzip_proxied` stays off, so no API answer that can carry a reflected value is compressed.
The image has no brotli module.

### The log and the request id

One JSON object for each request (`escape=json`), with the request id, `traceparent`, the client's
`X-Forwarded-For`, the upstream address and the times. The log has `$uri`, never the query string: the portal's sign-in
returns to `/?code=...&state=...`, and an authorization code must not reach a log. No header with a credential is
logged. A well-formed `X-Request-Id` from the caller (1 to 64 of `A-Za-z0-9._-`) is passed to the API; any other value
is replaced by nginx's own id. `traceparent` goes to the API unchanged; nginx makes no span of its own.

Not done: a metrics endpoint for Prometheus. The open-source nginx gives `stub_status`, a text page that Prometheus
cannot read without an exporter. An exporter sidecar is one more image to pin and patch, and the API's own metrics
count each request already. Revisit with the load test of Wave 8.

### A graceful stop

The image stops on SIGQUIT, nginx's graceful stop. The pod's `preStop` waits 5 s, so the router and the endpoints drop
the pod first, then runs `nginx -s quit` and waits for nginx to end, whatever signal the container runtime sends next.
`worker_shutdown_timeout 20s` bounds the open connections, inside `terminationGracePeriodSeconds: 30`.

### The configuration as code, in the image

The image holds the configuration; the chart passes four values. The image's own `20-envsubst-on-templates.sh` fills
the template at start, with `NGINX_ENVSUBST_FILTER` so that only the `CMAPI_*` names and `NGINX_LOCAL_RESOLVERS` are
filled and nginx's own variables stay. `16-cmapi-check-env.envsh` runs first and stops the start with the name of a
value that is missing or malformed. The stock `default.conf` is removed: if the template were not written, nginx would
start with no site and fail its readiness probe, not serve the stock page.

| Option | Why not |
|---|---|
| A ConfigMap with the whole nginx configuration, from the chart | The plain manifests would need a copy, and the copy can drift. In the image, one file is tested by `nginx -t` and by the route tests |

### TLS

The Route terminates TLS (edge) and redirects http to https, as for the API before. Inside the namespace the front door
speaks HTTP to the API, and the NetworkPolicy lets only the front door's pods reach the API port. TLS verification is
off nowhere. Re-encryption to the pods needs a serving certificate for each pod (OpenShift's service CA, another CA on
kind): a later option.

### nginx now, Envoy later

The owner chose nginx. It serves the static files itself, which Envoy does not, and the image was already pinned. The
stable branch (1.30) gets only critical fixes; the mainline (1.31) adds features that this front door does not use.

## Measured, on this Mac (no cluster, no container: #157)

- `deploy/tests/front-door-test.py --nginx <nginx 1.30.6 built from nginx.org's signed source>`: 330 checks, 0 failed (316 at the review fixes; the `/redoc` checks added 11; #241 added 3), with the work folder
  under `/var/folders/` and under `/tmp/`. #241 (BUG-58): on the GitHub runner the work folder is under `/tmp/`, and the
  harness moved the paths it had already moved, so nginx loaded no server and never listened; the old code fails the
  new checks (2 failed), the new code passes them. The syntax check now also reads `nginx -T` for both servers.
  The upstream, the routes, the headers of each kind of page and of `/healthz` and nginx's own errors (400, 404, 413,
  502, 504), what reaches the API, retries (a GET, DELETE or PUT goes to the other pod after a reset, a read timeout,
  a 502, 503 or 504; a POST, PATCH or LOCK never does), keepalive (12 requests over 3 pods used 3 connections), the log,
  and the start check, also against values with a line break.
- The same test against mutants of the configuration: each of these failed it: `non_idempotent` added, one
  `proxy_hide_header` removed, `$request_uri` in the log, the common headers left out of the portal's locations, a docs
  location renamed, the start check taking `http://`.
- `cmapi-portal-ui/tests/front-door.test.mjs` in Chromium (Playwright 1.64.1): the portal signs in through the stand-in
  issuer and lists requests through `/api/v1` with no `Origin` header (same origin, no CORS), signs out with a form POST
  to the issuer, and Swagger UI, the problem pages and the mockup render, each with no CSP violation. ReDoc renders and
  its search (Ctrl+K) lists results, with one violation: the refused Redocly logo, which no option removes. The check
  found #229 (BUG-57, `/redoc` empty on main), #235 (ReDoc's telemetry) and the mockup's Google Fonts. With
  `'unsafe-eval'` removed from the `/redoc` policy, the ReDoc check fails (no search worker).
- `cmapi/tests/service/test_front_door_chart.py`: the chart's hosts, values, Services and policies.

Not measured: the image's build and its entrypoint (no container here; GitHub's `front-door` job runs
`front-door-test.py --image` on the built image); the front door on kind or CRC (#157); Swagger UI's Authorize popup;
the router's behaviour with a pod that stops.

## Sources, each read on 2026-11-14

- nginx.org: ngx_http_upstream_module (`resolve` from 1.27.3 in the open-source build, `keepalive` by default from
  1.29.7), ngx_http_proxy_module (`proxy_next_upstream`, non-idempotent methods), ngx_http_headers_module (`add_header`
  inheritance, `always`), ngx_http_core_module (`absolute_redirect`, wildcard `server_name`, `client_max_body_size`,
  `server_tokens`). <https://nginx.org/en/docs/>. nginx 1.30 is the stable branch, 1.30.6 its newest release
  (<https://nginx.org/2026.html>).
- nginxinc/nginx-unprivileged at revision `bb7393196554` (the image's `org.opencontainers.image.revision`): the
  Dockerfile (`STOPSIGNAL SIGQUIT`, `USER 101`, group 0), `docker-entrypoint.sh`, `15-local-resolvers.envsh`,
  `20-envsubst-on-templates.sh`, `30-tune-worker-processes.sh`. Image `1.30.6-alpine3.24`, published 2026-10-19,
  manifest list `sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03`.
- OWASP Secure Headers Project, `ci/headers_add.json`, <https://github.com/OWASP/www-project-secure-headers>.
- RFC 10017 (BCP 212), sections 6.3.3.4 and 9.4, <https://www.rfc-editor.org/rfc/rfc10017>.
- uvicorn 0.32.1, `Config(timeout_keep_alive=5)`, read from the installed package.
- OpenShift Container Platform, "Configuring Routes", route annotations
  (<https://docs.redhat.com/en/documentation/openshift_container_platform/4.5/html/networking/configuring-routes>; the
  4.22 page was not read), and DISA STIG V-257555.

## Review

Codex (`gpt-6.1-sol`, CLI 0.167.0) reviewed export `9250712` from `brief.md`; its report is `reviewer-1-report.md`, and
its combined patch is `review-artifacts/all-fixes-and-tests.diff` (the other artifacts it names stayed in its export).
Its sandbox could not start nginx, so it proved F1 and F4 by test and left F2 and F3 "not proven". OB1 ran every new
test natively against nginx 1.30.6, first with only the tests applied, then with the fixes:

| Finding | Claim | Before the fix (measured here) | After | Ruling |
|---|---|---|---|---|
| F1: a value with a line break passes the start check, because `grep -x` matches each line | C5 | 13 cases failed (each of the four values with three suffixes, and the entrypoint pipeline) | passed | Accepted. The check refuses a value with a line break first |
| F2: `/healthz` and nginx's early errors (a 400 before a location is chosen) have no security headers | C2 | the headers of `/healthz` on both hosts and of the early 400 were missing | passed | Accepted. Each server includes its header file at server level as well |
| F3: `proxy_next_upstream_timeout 10s` is below `proxy_read_timeout`, so a GET that times out is not sent to the other pod | C3 | GET, DELETE and PUT after a read timeout: 504, the healthy pod never asked | 200 from the healthy pod | Accepted. The time limit is 0; two tries bound the retries |
| F4: the Route appends the client's `X-Forwarded-*` to the router's, so a client can prefix the values that the API reads | C6 | `test_route_replaces_untrusted_forwarded_headers` failed | passed | Accepted. Both Routes set `haproxy.router.openshift.io/set-forwarded-headers: replace` (Red Hat's route-specific annotations: append is the default; replace keeps only the router's values) |

C1 (path confusion), C4, C7, C8 and C9: Codex found them correct, with the qualifications in its report (one release
per namespace for the NetworkPolicy; a request longer than the 20 s drain can be cut).

## The plain manifests (the second pull request of #226)

OB1 run 6's implementer for this half (Opus 5.5 at high) wrote the code, the tests and this section on 2026-11-14, on
branch `front-door-plain`, stacked on PR #238. The plain manifests do what the chart does; the tests in
`cmapi/tests/service/test_plain_manifests.py` render the chart with `deploy/environments/crc.yaml` and compare object by object.

| Part | Where |
|---|---|
| The front door's Deployment and Service, the same as the chart's | `deploy/manifests/components/portal/10-front-door.yaml` |
| The headless `cmapi-api-pods` | `deploy/manifests/components/cmapi/20-api.yaml` |
| `cmapi-metrics` (only the front door reaches 8080) and `cmapi-front-door` (only the router reaches the front door) | `deploy/manifests/components/cmapi/40-networkpolicy.yaml` |
| The hosts, the issuer's origin and `config.json` of each environment | `environments/crc/60-portal.yaml`, `environments/kind/40-portal.yaml` |
| Two Routes to the front door, none to the API | `environments/crc/40-routes.yaml` |
| The second image and the second checksum | `deploy/render.sh --portal-image`, `deploy/render-test.sh` |
| The front door's image built and pushed | `deploy/crc-image.sh cmapi-portal` |

### Decisions, with the options not taken

**The environment's values in one ConfigMap, read by name.** `cmapi-portal-config` holds `CMAPI_PORTAL_HOST`,
`CMAPI_MOCKUP_HOST`, `CMAPI_OIDC_ORIGIN` and `config.json`. The Deployment names each variable with `configMapKeyRef`, so
its env names are the chart's, line for line, and a test compares them.

| Option | Why not |
|---|---|
| `envFrom` on the ConfigMap | Its key `config.json` is no environment variable name. Kubernetes: "If any keys do not meet the rules, those keys are not made available to your container, though the Pod is allowed to start" (kubernetes.io, ConfigMaps, read 2026-11-14). A second ConfigMap only for that would split one environment's front door in two |
| More placeholders that `render.sh` fills with the hosts | Templating in the render. The render fills images and checksums only |

`CMAPI_API_UPSTREAM` stays in the component: `cmapi-api-pods.cmapi.svc.cluster.local:8080`. Every file here assumes
namespace `cmapi` and cluster domain `cluster.local`. nginx's resolver does not use the pod's search domains, so the name is whole.

**A checksum of the front door's own.** `render.sh` fills `CMAPI_PORTAL_CONFIG_CHECKSUM` with a SHA-256 over
`cmapi-portal-config`, by the same method as the api's. nginx reads its hosts once, at start, and `config.json` is mounted
by `subPath`: "A container using a ConfigMap as a subPath volume mount will not receive ConfigMap updates" (kubernetes.io,
ConfigMaps, read 2026-11-14). So without it a changed host or `config.json` would change nothing until a restart.

| Option | Why not |
|---|---|
| One checksum over the four ConfigMaps | A change to the portal's `config.json` would restart the api and the worker, and a change to `cmapi-config` the front door |
| Mount the whole ConfigMap as a directory, which Kubernetes updates | nginx's root holds the portal's build; a directory mount over it would hide the build. The env values need a restart anyway |

**`--portal-image` is required.** Every environment runs the front door. A positional third image would move the out dir,
so an old call `render.sh crc <image> <out dir>` would read the out dir as an image. With a flag the old call fails at once
and names what is missing. Each image is checked against its own repository: the API's image is refused as the front door's, and the
other way round.

**The mockup's ConfigMap and `deploy/mockup-configmap.sh` are gone.** The HTML is in the `cmapi-portal` image
(`cmapi-portal-ui/Containerfile` copies `mockups/portal/dist/portal.html`), built from the same commit as the rest. So
the script, its CI check, and the server-side apply that the 300 KB ConfigMap needed have no reason left. Server-side apply
stays, as Argo CD applies.

**The two policies in one file.** `40-networkpolicy.yaml` holds both. docs/13's step 21 applies it before the workloads,
so the api, the worker and the front door each start under their policy. `kind-test.sh` deletes both on podman-kind's DNS
fault, which hits every pod that a policy selects. Its control pod for that fault is now the database's (`getent` in
`cmapi-db-1`), since the front door is selected now. Not measured: no kind cluster (#157).

**The front door runs as the namespace's `default` account, as the chart's does.** docs/13's step 8 now waits for that
account's pull secret too, since the image is in the internal registry. Suggested, not done here, for the chart and the plain
manifests together: a `cmapi-portal` account with `automountServiceAccountToken: false`, since nginx needs no API token.

**`crc-proof.sh` through the front door.** `/readyz` and `/metrics` are not the API's paths, so through the Route they
answer the portal's page; the proof checks `200 text/html` for both, where it checked 404 before. `/healthz` is the front
door's own. The portal's page must carry the front door's HSTS, `nosniff` and Content-Security-Policy. The policy probe needs
a control that no policy selects: before, the mockup's pod; now every pod of cmapi's is selected, so the proof starts
`cmapi-np-target` in `cmapi` and deletes it after (the rollback names it too). The probe is then blocked from both the API's
port and the front door's. The probe image stays nginx 1.29 by digest: its BusyBox wget's `download timed out` is the measured
sign of a dropped connection.

### BUG-60 (#246)

The rollback guard (`test_crc_rollback_names_every_object_the_run_creates`) ended each name at `\b`, so
`route.route.openshift.io cmapi-mockup` counted as Route `cmapi`. With this change's names that became reachable. Measured: with
`"route.route.openshift.io cmapi"` and `"service cmapi-api"` taken out of `crc-rollback.sh`, the old guard reported nothing
missing; the fixed guard reports both. The name now ends at a quote, white space or the end of a line, in `rollback_missing`,
and `test_the_rollback_guard_tells_a_name_from_a_longer_one` holds it.

## Reviewer 1 on PR-B (Codex `gpt-6.1-sol`, PR #247 head `8ff0352`)

Codex checked seven claims (`reviewer-1-report-pr-b.md`; its fixes are `review-artifacts/pr-b-all-fixes.diff`) and
confirmed C1 to C6: the two policies, the Routes, the realm's redirect URIs, `render.sh` and the Deployment match the
chart. It found three defects, each with a stub test that failed before (9 assertions) and passes after:

| # | Finding | Decision |
|---|---|---|
| F1 | `kind-test.sh` passed with both NetworkPolicies deleted (the podman-kind DNS workaround), and never tried a forbidden connection | Accepted. An unlabelled pod in `cmapi` must be refused both 8080 ports, and the front door must reach the API. On the DNS failure the run now fails. One change to Codex's fix: `KIND_TEST_WITHOUT_NETPOL=true` keeps the earlier workaround as an explicit choice, so the other checks can still run on podman-kind, and the run then says "NetworkPolicy NOT PROVED". A test in `kind-test-stubbed.sh` covers it |
| F2 | `np-reach-test.sh` counted an exec failure, a refused connection or an HTTP 503 as a blocked connection | Accepted unchanged: only the BusyBox timeout counts, with a reachable control from the same source after it |
| F3 | The front door's pod mounts a service account token that nginx never uses | Accepted unchanged, in the chart and the plain manifests: `automountServiceAccountToken: false` |
