# Security review: nginx as the front door of each instance (cmapi issues #226 and #206)

You are reviewer 1. You work in this folder only: it is an export of the commit in `EXPORT-HEAD`, not a repository.
`change.diff` is the whole change against main `962d7f8`. Write each finding to `REPORT.md` in this folder as you go.
Do not start a container, a cluster or a database, and do not run `cmapi/tests/service` (it needs a shared PostgreSQL
that another session uses). You CAN run nginx: `nginx-1.30.6/sbin/nginx` is nginx 1.30.6 built on this Mac from
nginx.org's signed source, the version that the image runs. The harness runs it:

    python3 deploy/tests/front-door-test.py --nginx "$PWD/nginx-1.30.6/sbin/nginx"

It needs only the Python standard library and takes about 40 s. `cmapi/tests/service/test_front_door_chart.py` needs
`helm` (on PATH) and PyYAML, and no database: you may run that file alone. Say what you ran.

## The files to read, in full
- `cmapi-portal-ui/nginx/nginx.conf`, `cmapi-portal-ui/nginx/templates/cmapi.conf.template`,
  `cmapi-portal-ui/nginx/cmapi/*.conf`, `cmapi-portal-ui/nginx/16-cmapi-check-env.envsh`
- `cmapi-portal-ui/Containerfile`
- `deploy/helm/cmapi/templates/portal.yaml`, `exposure.yaml`, `api.yaml` (the Service `-api-pods`), `monitoring.yaml`
  (the two NetworkPolicies), `deploy/helm/cmapi/values.yaml` (exposure, portal), `deploy/environments/crc.yaml`
- `deploy/tests/front-door-test.py`, `cmapi/tests/service/test_front_door_chart.py`
- `cmapi/src/cmapi/main.py` (`uvicorn.run(... proxy_headers=True, forwarded_allow_ips="*")`), `cmapi/src/cmapi/core/observability.py`
  (how `X-Request-Id` is read)
- `docs/reviews/2026-11-14-issue-226/README.md` (the decisions and the options not taken)

## The claims. Confirm or refute each one, with the file and the line.
- C1. Only the paths that the template lists reach the API: `/api/`, `/openapi.json`, `/openapi.yaml`, `/problems`,
  `/problems/`, `/docs`, `/docs/`, `/redoc`, `/static/swagger/`, `/static/redoc/`. No request can make the API serve
  another route (for example `/readyz`, `/healthz` of the API, `/api/v1/version` is fine) through one of those
  locations. Try path confusion: `..`, `%2e%2e`, `%2F`, `//`, `;`, a backslash, a NUL, `/docs/..%2Freadyz`,
  `/static/swagger/..%2f..%2freadyz`, `/problems/%2e%2e/readyz`. Note that `proxy_pass http://cmapi_api;` has no URI
  part, so nginx passes the request URI as the client sent it, while nginx matched the location on its normalized
  form: say if nginx and Starlette (0.41.3, under uvicorn 0.32.1) can read one URI as two different paths.
- C2. Every answer of the instance's host has the OWASP headers of `headers-common.conf`, also a 404, a 413, a 502 and
  a 504 that nginx makes itself, and an API 401 or 500. No location drops them through `add_header` inheritance. An
  API answer cannot add a second value of any header that the front door sets, or replace the front door's
  Content-Security-Policy. The CSP of each kind of page is the one the record gives, and the portal's pages never get
  the docs' `'unsafe-inline'`.
- C3. A POST, PATCH or LOCK is never sent to a second API pod, also when the first pod resets the connection after it
  got the request, times out (`proxy_read_timeout`), or answers 502, 503 or 504. A GET is. Say if `DELETE` or `PUT`
  (idempotent by RFC 9110, retried by nginx) is unsafe for any route of the API (`cmapi/src/cmapi/routers/`,
  `cmapi/src/cmapi/plugins/*/router.py`).
- C4. The access log never holds a credential or an authorization code: no query string, no `Authorization`, no
  cookie. A caller cannot forge or break a log line (the `escape=json` format, the `X-Request-Id` map). A
  malformed `X-Request-Id` never reaches the API.
- C5. No value of the four `CMAPI_*` variables can change nginx's configuration beyond the one value, because
  `16-cmapi-check-env.envsh` refuses it first: try a `;`, a `{`, a newline, a quote, a space, `$`, `include`, a
  wildcard other than a trailing `.*`. Say if the image's entrypoint can start nginx with an unchecked value (the
  order of `/docker-entrypoint.d/` scripts; `.envsh` is sourced, and the scripts run in a `find | sort -V | while`
  pipeline under `set -e`).
- C6. `X-Forwarded-Proto`, `X-Forwarded-Host` and `X-Forwarded-For` that reach the API are trustworthy enough for
  what the API does with them (uvicorn trusts every peer, `forwarded_allow_ips="*"`), given that the NetworkPolicy
  lets only the front door's pods reach the API port, and only the router reach the front door. Name what an
  attacker inside the cluster, or outside through the router, could change in the API's answers.
- C7. The chart's NetworkPolicies match the pods they mean: `-metrics` lets only pods with the front door's labels
  reach the API's port 8080; `-front-door` lets only the router's namespace (label
  `policy-group.network.openshift.io/ingress`) reach the front door with Route exposure. No other pod of the chart
  (worker, jobs, the realm sync) needs the API's port. The headless Service `-api-pods` selects the API pods only.
- C8. The image runs as a non-root user with group 0 under OpenShift's restricted-v2 SCC (an arbitrary UID), the
  entrypoint can write `/etc/nginx/conf.d` and `nginx.conf`, the stock `default.conf` is gone, and nginx writes only
  under `/tmp`. The two base images are pinned by digest.
- C9. A graceful stop: the preStop hook, `worker_shutdown_timeout 20s` and `terminationGracePeriodSeconds: 30` let
  open requests finish; nginx stops taking new connections after 5 s. Say if `pgrep` exists in the image's Alpine
  base, and what happens when `nginx -s quit` runs while the kubelet then sends SIGTERM or SIGQUIT.

## For each finding
Give: the claim it breaks, the file and line, why it is wrong, the full code of the fix (a unified diff against this
export), and a test that fails before the fix and passes after it, as a new case of `deploy/tests/front-door-test.py`
or `cmapi/tests/service/test_front_door_chart.py`, with the output of both runs. A finding with no failing test is
listed as "not proven". Also list what you checked and found correct, one line each.

## Not in this review
The choice of nginx over Envoy, of one origin over CORS (docs/15 has it), the plain manifests (`deploy/manifests/`,
the next pull request of #226), and ReDoc's page (#229, a separate pull request).
