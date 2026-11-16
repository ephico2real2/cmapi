# Security review: nginx front door — reviewer 1

Export `9250712c046cb6c7306a0f4fe5ba57db2d0bfd37` (`EXPORT-HEAD`), compared with main `962d7f8` using `change.diff`.

**Two reproduced regressions:** C5 accepts multiline configuration injection; C6 omits the Route policy needed to replace untrusted forwarded headers. **Two additional findings are not proven by execution:** missing headers on health/early-error responses (C2), and GET timeout failover suppressed by the retry deadline (C3). Their source evidence and proposed runtime tests are included, but nginx cannot initialize inside this session's sandbox.

The export's application, chart, and test files remain unchanged. All proposed changes are isolated under `review-artifacts/`. [all-fixes-and-tests.diff](review-artifacts/all-fixes-and-tests.diff) contains all four fixes and their new cases in the two requested test files. Each individual complete patch applies independently to this export; use the combined patch when taking all findings. All five patches passed `patch --dry-run -p1`. Do not apply the independent patches sequentially: their changes to the shared harness overlap.

## What ran

No container, cluster, database, or database-dependent service tests were started. Only the specifically permitted chart test file was passed to pytest, with `--noconftest` to avoid loading unrelated test infrastructure.

| Command / check | Result |
|---|---|
| `python3 deploy/tests/front-door-test.py --nginx "$PWD/nginx-1.30.6/sbin/nginx"` | Blocked before HTTP checks: nginx cannot perform `sysctlbyname(net.inet.tcp.sendspace)`; even `nginx -t` fails. [Output](review-artifacts/nginx-baseline.txt). |
| `python3 -m pytest cmapi/tests/service/test_front_door_chart.py -q` | Default Python 3.14 lacks pytest. |
| `python3.13 -m pytest --noconftest cmapi/tests/service/test_front_door_chart.py -q` | **11 passed in 3.94s**. [Output](review-artifacts/chart-baseline.txt). |
| `python3 review-artifacts/run_env_cases.py before` / `after` | Original environment cases plus new C5 case: **67 checks; 13 failed before, 0 failed after**. [Before](review-artifacts/env-before.txt), [after](review-artifacts/env-after.txt). |
| `python3.13 -m pytest --noconftest review-artifacts/before/cmapi/tests/service/test_front_door_chart.py -q` | **1 failed, 11 passed in 4.33s**; the new Route forwarding policy assertion fails. [Output](review-artifacts/chart-before.txt). |
| Same command with `after` | **12 passed in 3.87s**. [Output](review-artifacts/chart-after.txt). |
| New `case_review_error_headers` and `case_review_retry_matrix`, each against before/after configuration copies | Both phases blocked at nginx initialization. No passing HTTP result is claimed. [Both runs](review-artifacts/nginx-review-cases.txt). |
| `python3.13 review-artifacts/asgi_probe.py` | Socket-free uvicorn **0.32.1** + Starlette **0.41.3** probes passed. These use a minimal equivalent router, not cmapi's database-backed app. [Code](review-artifacts/asgi_probe.py), [output](review-artifacts/asgi-probe.txt). |
| `skopeo inspect --override-os linux --override-arch amd64 --config docker://docker.io/nginxinc/nginx-unprivileged@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03`, then `skopeo copy ... dir:review-artifacts/base-image` | Inspected image configuration and selected tar members only; **never ran the image**. Preserved [configuration](review-artifacts/image-config.json), [manifest](review-artifacts/image-manifest.json), [file evidence](review-artifacts/image-files.txt), and [entrypoint files](review-artifacts/image-evidence/). Downloaded layer blobs were removed afterward. |
| `python3 -m py_compile` on both patched test files | Passed. |

The dependency probe installed uvicorn/Starlette into `review-artifacts/python-deps` only. The environment regressions still use only the standard library and `/bin/sh`.

TokenSave exploration/status/read were attempted first. This export is not an initialized graph and the server could not read it without a registered project, so source inspection used the local files; no graph was initialized or updated, and no other project was consulted.

## Finding 1 — Reject multiline values before the line-oriented regex (C5; medium; reproduced)

**Location:** `cmapi-portal-ui/nginx/16-cmapi-check-env.envsh:15–24`; substitution sites include `cmapi-portal-ui/nginx/templates/cmapi.conf.template:45,49,69,78,163`.

`grep -Eqx` succeeds when **any input line** matches. It does not require that the environment value consist of exactly one line. All four CMAPI variables accepted a valid first line followed by arbitrary text. For example:

```text
CMAPI_PORTAL_HOST = cmapi.apps-crc.testing
; location = /injected { return 200 injected; } #
```

The checker prints `started` with exit 0. Substitution at template line 78 produces `server_name cmapi.apps-crc.testing`, then a terminating semicolon and an additional `location` directive. The trailing `#` comments out the template's semicolon. This defeats the claim that these are single configuration values. Exploitation requires control over deployment environment values; this is not injection from an HTTP request. Validation bypass is executed and proven; actual startup of an injected nginx configuration is not measured because of the sandbox.

The fix rejects LF in each value before any per-line regex runs. Existing regexes then reject semicolons, braces, quotes, spaces, dollar signs, directive fragments, and misplaced wildcards. A literal word such as `include` inside an otherwise valid DNS label is harmless and is correctly allowed; the tests use ` include /tmp/attacker.conf` as the directive attempt.

Full production fix against this export:

```diff
--- a/cmapi-portal-ui/nginx/16-cmapi-check-env.envsh
+++ b/cmapi-portal-ui/nginx/16-cmapi-check-env.envsh
@@ -2,12 +2,24 @@
 # Sourced by the image's docker-entrypoint.sh after 15-local-resolvers.envsh and before 20-envsubst-on-templates.sh.
 # The template takes these values as they are, so a missing or malformed one would give a front door that starts and
 # routes wrongly. Each is checked here, and the container stops with the name of the value at fault.
-# Sourced, not run: "exit" ends the entrypoint itself, so nginx does not start.
+# Sourced inside the entrypoint pipeline: exit fails its last stage; set -e stops nginx startup.
 
 cmapi_refuse() {
   echo "$0: ERROR: $1" >&2
   exit 1
 }
+
+# grep -x matches individual lines. Reject line breaks before testing any value.
+cmapi_single_line() {
+  case "$2" in
+    *'
+'*) cmapi_refuse "$1 must be a single line" ;;
+  esac
+}
+cmapi_single_line CMAPI_API_UPSTREAM "${CMAPI_API_UPSTREAM:-}"
+cmapi_single_line CMAPI_PORTAL_HOST "${CMAPI_PORTAL_HOST:-}"
+cmapi_single_line CMAPI_MOCKUP_HOST "${CMAPI_MOCKUP_HOST:-}"
+cmapi_single_line CMAPI_OIDC_ORIGIN "${CMAPI_OIDC_ORIGIN:-}"
 
 # A DNS name in lower case (RFC 1123 labels), with no anchors, so each check below can add a port.
 cmapi_host='[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*'
```
Full fix **and test code**: [finding-1-complete.diff](review-artifacts/finding-1-complete.diff). Test-only diff: [finding-1-tests.diff](review-artifacts/finding-1-tests.diff).

**New case:** `case_review_env_single_line` in `deploy/tests/front-door-test.py`. It checks three multiline forms and nine metacharacter/directive suffixes for each CMAPI variable, then tests valid, invalid, and multiline values through the same `set -e` / last-stage `while` pipeline shape as the image. The original 16 environment checks also run.

**Actual output:**

```text
BEFORE (exit 1):
  FAIL CMAPI_API_UPSTREAM: rejects multiline suffix '\n; location = /injected { return 200 injected; } #'
  FAIL CMAPI_API_UPSTREAM: rejects multiline suffix '\ninclude /tmp/attacker.conf; #'
  FAIL CMAPI_API_UPSTREAM: rejects multiline suffix '\n'
  FAIL CMAPI_PORTAL_HOST: rejects multiline suffix '\n; location = /injected { return 200 injected; } #'
  FAIL CMAPI_PORTAL_HOST: rejects multiline suffix '\ninclude /tmp/attacker.conf; #'
  FAIL CMAPI_PORTAL_HOST: rejects multiline suffix '\n'
  FAIL CMAPI_MOCKUP_HOST: rejects multiline suffix '\n; location = /injected { return 200 injected; } #'
  FAIL CMAPI_MOCKUP_HOST: rejects multiline suffix '\ninclude /tmp/attacker.conf; #'
  FAIL CMAPI_MOCKUP_HOST: rejects multiline suffix '\n'
  FAIL CMAPI_OIDC_ORIGIN: rejects multiline suffix '\n; location = /injected { return 200 injected; } #'
  FAIL CMAPI_OIDC_ORIGIN: rejects multiline suffix '\ninclude /tmp/attacker.conf; #'
  FAIL CMAPI_OIDC_ORIGIN: rejects multiline suffix '\n'
  FAIL entrypoint pipeline permits valid values only: 'cmapi.apps-crc.testing\n; location = /injected { return 200 injected; } #'
front door environment cases failed: 13

AFTER (exit 0):
  ok   entrypoint pipeline permits valid values only: 'cmapi.apps-crc.testing'
  ok   entrypoint pipeline permits valid values only: 'bad host'
  ok   entrypoint pipeline permits valid values only: 'cmapi.apps-crc.testing\n; location = /injected { return 200 injected; } #'
front door environment cases failed: 0
```

The actual pinned image entrypoint at `review-artifacts/image-evidence/docker-entrypoint.sh:17–39` sorts the scripts and sources executable `.envsh` files in the final pipeline stage. Its `set -e` is at line 4. Exiting the sourced validator fails that stage; the parent entrypoint exits before `exec` at line 47. There is **no additional exit-status bypass** from the subshell. The image's resolver script is 15, the validator is installed executable as 16 (`Containerfile:51`), and substitution is 20. The discovered issue is acceptance of multiline values, not incorrect ordering or ignored failure.

## Finding 2 — Give both servers default response headers (C2; low; **not proven**)

**Location:** `cmapi-portal-ui/nginx/templates/cmapi.conf.template:76–102,161–176`.

Neither server defines default security headers; both `/healthz` locations omit their header include. Thus the configuration provides none of the common headers or CSP for health responses. Errors generated before selecting a location also have no server-level fallback. This refutes the literal “every answer” claim by source inspection. The ordinary asset/API/docs locations have their own correct includes; this is not a blanket inheritance failure affecting all 404/413/502/504 responses.

The fix establishes the appropriate portal/mockup header defaults at each server. Existing location includes remain: locations that add Cache-Control or their own CSP must still define the complete applicable header set. nginx's normal inheritance rule means these are replacements at the location level, not duplicate values.

Full production fix against this export:

```diff
--- a/cmapi-portal-ui/nginx/templates/cmapi.conf.template
+++ b/cmapi-portal-ui/nginx/templates/cmapi.conf.template
@@ -76,6 +76,7 @@
 server {
     listen 8080 default_server;
     server_name ${CMAPI_PORTAL_HOST};
+    include /etc/nginx/cmapi/headers-portal.conf;
     root /usr/share/nginx/html/portal;
     index index.html;
     access_log /dev/stdout cmapi_json;
@@ -161,6 +162,7 @@
 server {
     listen 8080;
     server_name ${CMAPI_MOCKUP_HOST};
+    include /etc/nginx/cmapi/headers-mockup.conf;
     root /usr/share/nginx/html/mockup;
     access_log /dev/stdout cmapi_json;
     absolute_redirect off;
```
Full fix **and test code**: [finding-2-complete.diff](review-artifacts/finding-2-complete.diff). Test-only diff: [finding-2-tests.diff](review-artifacts/finding-2-tests.diff).

**New case:** `case_review_error_headers` in `deploy/tests/front-door-test.py`. It requests both health endpoints, an early 400, static 404, body-limit 413, upstream 401/500, nginx 502/504, and upstream attempts to supply every common security header plus CSP/COOP. Only the read timeout is shortened to make the 504 case quick; the header hierarchy is unchanged.

**Before and after output:** both stopped at initialization, so this finding has no observed failing/passing HTTP regression and is **not proven**, as required by the brief.

```text
before case_review_error_headers
review C2: health, early errors, static and upstream errors
BLOCKED: nginx stopped: 2026/11/14 02:56:53 [alert] 57857#0: sysctlbyname(net.inet.tcp.sendspace) failed (1: Operation not permitted)
BLOCKED: nginx stopped: 2026/11/14 02:56:54 [alert] 57893#0: sysctlbyname(net.inet.tcp.sendspace) failed (1: Operation not permitted)
after case_review_error_headers
review C2: health, early errors, static and upstream errors
BLOCKED: nginx stopped: 2026/11/14 02:56:54 [alert] 57940#0: sysctlbyname(net.inet.tcp.sendspace) failed (1: Operation not permitted)
BLOCKED: nginx stopped: 2026/11/14 02:56:54 [alert] 57967#0: sysctlbyname(net.inet.tcp.sendspace) failed (1: Operation not permitted)
```

## Finding 3 — The retry deadline prevents GET read-timeout failover (C3; medium; **not proven**)

**Location:** `cmapi-portal-ui/nginx/cmapi/proxy.conf:18`, in combination with `proxy-api.conf:4` (60 seconds) and `proxy-docs.conf:4` (15 seconds).

The retry-selection deadline is 10 seconds. When a first pod stays silent until either read timeout, that deadline has already expired, so nginx returns 504 instead of selecting the healthy pod, even for GET. A delayed 502/503/504 arriving after the deadline has the same limitation. The deadline does not interrupt the initial read at 10 seconds; it is checked when deciding whether to attempt another upstream. This follows nginx 1.30.6's `ngx_http_upstream_test_next` and `ngx_http_upstream_next`, which compare elapsed time with `next_upstream_timeout`. [Pinned upstream implementation](https://raw.githubusercontent.com/nginx/nginx/release-1.30.6/src/http/ngx_http_upstream.c).

The fix removes that elapsed-time restriction while retaining `proxy_next_upstream_tries 2`, all per-operation timeouts, and the non-idempotent guard. Two silent API attempts can now each consume the 60-second read timeout; outer router/client deadlines still apply. This tradeoff is necessary if the advertised behavior includes retry after the configured first read timeout.

Full production fix against this export:

```diff
--- a/cmapi-portal-ui/nginx/cmapi/proxy.conf
+++ b/cmapi-portal-ui/nginx/cmapi/proxy.conf
@@ -15,7 +15,8 @@
 # a POST, PATCH or LOCK once it was sent (no "non_idempotent"): a create must not run twice.
 proxy_next_upstream error timeout http_502 http_503 http_504;
 proxy_next_upstream_tries 2;
-proxy_next_upstream_timeout 10s;
+# Two tries bound retries; an elapsed limit below proxy_read_timeout would suppress timeout failover.
+proxy_next_upstream_timeout 0;
 # The front door sets these headers once. An API response that set one too would send the browser two values.
 proxy_hide_header Strict-Transport-Security;
 proxy_hide_header X-Content-Type-Options;
```
Full fix **and test code**: [finding-3-complete.diff](review-artifacts/finding-3-complete.diff). Test-only diff: [finding-3-tests.diff](review-artifacts/finding-3-tests.diff).

**New case:** `case_review_retry_matrix` in `deploy/tests/front-door-test.py`. It records requests arriving at two stand-in pods for GET/POST/PATCH/LOCK/DELETE/PUT after a reset, read timeout, and 502/503/504. Each attempt carries a unique query marker. It expects one delivery for POST/PATCH/LOCK and two for GET/DELETE/PUT. To keep the matrix bounded, the current 60-second timeout / 10-second deadline relationship is scaled to 1 second / 150 milliseconds. The fixed zero deadline remains zero. The original harness tested only reset + GET/POST, with no timeout case.

**Before and after output:** initialization was blocked for both, so the predicted GET failure and corrected behavior were not observed. This finding is **not proven** under the brief's execution standard.

```text
BLOCKED: nginx stopped: 2026/11/14 02:56:53 [alert] 57857#0: sysctlbyname(net.inet.tcp.sendspace) failed (1: Operation not permitted)
before case_review_retry_matrix
review C3: reset, read timeout, 502/503/504 across all method classes
BLOCKED: nginx stopped: 2026/11/14 02:56:54 [alert] 57893#0: sysctlbyname(net.inet.tcp.sendspace) failed (1: Operation not permitted)
BLOCKED: nginx stopped: 2026/11/14 02:56:54 [alert] 57940#0: sysctlbyname(net.inet.tcp.sendspace) failed (1: Operation not permitted)
after case_review_retry_matrix
review C3: reset, read timeout, 502/503/504 across all method classes
BLOCKED: nginx stopped: 2026/11/14 02:56:54 [alert] 57967#0: sysctlbyname(net.inet.tcp.sendspace) failed (1: Operation not permitted)
```

## Finding 4 — Replace forwarded headers at the Route boundary (C6; medium; chart regression reproduced)

**Location:** `deploy/helm/cmapi/templates/exposure.yaml:39–42` (missing forwarding-policy annotation); `cmapi-portal-ui/nginx/templates/cmapi.conf.template:29–34`; `cmapi-portal-ui/nginx/cmapi/proxy.conf:6–9`; `cmapi/src/cmapi/main.py:292–293`.

The Route leaves the forwarding policy at the router default. OpenShift's router template defaults to `append` and adds X-Forwarded-Proto rather than replacing a caller's value. nginx combines repeated generic request headers with a comma; `https, https` or `http, https` does not match the map's single `https`, so it forwards the pod's `http` scheme. A slash-correction redirect can consequently contain `Location: http://...` on the public HTTPS host. X-Forwarded-For retains a caller-controlled leftmost element as well; uvicorn's `*` trust uses that element for the ASGI client address. Network isolation establishes the immediate peer, not the origin of each value in a header chain. [Router 4.22 source, defaults and forwarding branches](https://raw.githubusercontent.com/openshift/router/release-4.22/images/router/haproxy/conf/haproxy-config.template), [nginx 1.30.6 header-variable implementation](https://raw.githubusercontent.com/nginx/nginx/release-1.30.6/src/http/ngx_http_variables.c), [uvicorn 0.32.1 proxy middleware](https://raw.githubusercontent.com/encode/uvicorn/0.32.1/uvicorn/middleware/proxy_headers.py).

The fix makes the TLS edge set authoritative X-Forwarded-* values for both Routes. nginx's existing append then adds only the router peer to the sanitized XFF chain. With an intentional additional proxy ahead of the router, the site would need an explicit trusted-proxy arrangement; this chart configures a direct edge Route.

Full production fix against this export:

```diff
--- a/deploy/helm/cmapi/templates/exposure.yaml
+++ b/deploy/helm/cmapi/templates/exposure.yaml
@@ -40,6 +40,8 @@
   name: {{ $site.subdomain }}
   namespace: {{ $.Release.Namespace }}
   labels: {{- include "cmapi.labels" $ | nindent 4 }}
+  annotations:
+    haproxy.router.openshift.io/set-forwarded-headers: replace
 spec:
   {{- if $site.host }}
   host: {{ $site.host }}
```
Full fix **and test code**: [finding-4-complete.diff](review-artifacts/finding-4-complete.diff). Test-only diff: [finding-4-tests.diff](review-artifacts/finding-4-tests.diff).

**New test:** `test_route_replaces_untrusted_forwarded_headers` in `cmapi/tests/service/test_front_door_chart.py`. It checks the actual rendered Route objects, for the instance and mockup. This reproduces the missing chart guarantee and proves that the fix renders it. It does not claim to have run HAProxy.

**Before output:**

```text
...........F                                                             [100%]
=================================== FAILURES ===================================
_______________ test_route_replaces_untrusted_forwarded_headers ________________

crc = [{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'annotations': {'helm.sh/resource-policy': 'keep'}, 'labels': ...ernetes.io/part-of': 'cmapi', 'cmapi.net/instance': 'nonprod', ...}, 'name': 'cmapi-jobs', 'namespace': 'cmapi'}}, ...]

    def test_route_replaces_untrusted_forwarded_headers(crc):
        routes = find(crc, "Route")
        assert len(routes) == 2
        for route in routes:
            annotations = route["metadata"].get("annotations", {})
>           assert annotations.get("haproxy.router.openshift.io/set-forwarded-headers") == "replace", route["metadata"]["name"]
E           AssertionError: cmapi
E           assert None == 'replace'
E            +  where None = <built-in method get of dict object at 0x1057fa040>('haproxy.router.openshift.io/set-forwarded-headers')
E            +    where <built-in method get of dict object at 0x1057fa040> = {}.get

review-artifacts/before/cmapi/tests/service/test_front_door_chart.py:148: AssertionError
=========================== short test summary info ============================
FAILED review-artifacts/before/cmapi/tests/service/test_front_door_chart.py::test_route_replaces_untrusted_forwarded_headers
1 failed, 11 passed in 4.33s
```

**After output:**

```text
............                                                             [100%]
12 passed in 3.87s
```

The socket-free pinned ASGI probe separately observed these consequences after supplying the values that nginx would forward:

```text
HTTP/1.1 307 Temporary Redirect
location: http://cmapi.apps-crc.testing/api/v1/version
```

and an ASGI `client` host of `attacker` for `X-Forwarded-For: attacker, 203.0.113.8, 10.0.0.5`. That probe's JSON response echoes the address only to inspect middleware behavior; cmapi itself does not return this probe response.

**Current API impact and attacker scope:**

- An outside caller through the default Route can prepend XFF data and trigger the scheme fallback with a supplied XFP header. Host/X-Forwarded-Host are replaced by nginx's `$host`; the router restricts which public Host routes reach this instance. The practical answer change identified here is an automatic slash redirect using HTTP. No current cmapi authorization decision uses this client address.
- An ordinary pod in another namespace cannot directly reach the Route-mode front door or API under these policies. A pod in a namespace carrying the ingress label can reach the front door with chosen Host/XFP/XFF values; the policy trusts that entire namespace, not a router process identity. Someone able to create matching portal-labelled pods in the application namespace can also satisfy the API ingress selector. Those label/namespace privileges are part of the trust boundary.
- With `exposure: Ingress`, `monitoring.yaml:44–48` omits the source restriction by design, so any cluster pod can directly reach nginx, choose its Host and forwarded values, and influence absolute redirects. This Route annotation fixes the Route-mode finding; it does not establish a trust boundary for arbitrary Ingress controllers.
- `main.py:173,283–286` builds documentation servers from configured `publicUrl`; problem type URLs use configured `problem_base` (`main.py:125–128`). JWT issuer/audience and subject-based authorization are configured independently. I found no route that uses forwarded headers to replace those settings, authorize a caller, or select a backend.

## Verdict on each claim

| Claim | Verdict and file/line evidence |
|---|---|
| **C1** | **Supported by inspection and the pinned backend probe; end-to-end nginx unverified.** Locations are the explicit allowlist at `cmapi.conf.template:105–135`; `proxy.conf:4` forwards the original URI. nginx normalizes for matching; uvicorn decodes once and Starlette does not remove dot segments before matching application routes. These representations can differ, but I found no path that reaches an unlisted API route. More detail below. |
| **C2** | **Refuted by the header omission in finding 2, not proven by runtime test.** `/healthz` has no includes (`cmapi.conf.template:98–102,172–176`) and neither server has defaults. Elsewhere `headers-common.conf:5–12` uses `always`, each header-producing location includes a complete header block, and `proxy.conf:20–29` hides all eight common headers plus CSP/COOP. Expected error headers are supported by the configuration, but 404/413/502/504 and API 401/500 were not exercised in nginx here. |
| **C3** | **Partly supported; GET timeout retry refuted by finding 3, not proven by runtime test.** `proxy.conf:16–18` omits `non_idempotent` and caps attempts at two; nginx 1.30.6 guards already-sent POST/PATCH/LOCK on both transport and HTTP-status retry paths. Reset/immediate status failures can retry GET; read timeout exceeds the retry deadline. DELETE/PUT analysis is below. |
| **C4** | **Supported by inspection; live log output unverified.** `cmapi.conf.template:15–20` uses `escape=json`, logs `$uri` without query arguments, and never references Authorization or Cookie. The request-ID regex at lines 24–27 admits only 1–64 ASCII allowed characters; fallback is nginx's generated ID, forwarded at `proxy.conf:10`. The API reads and echoes that ID at `observability.py:85–96`. Caller-supplied quotes/control characters in other logged fields are JSON-escaped, not new log records. |
| **C5** | **Refuted, reproduced:** finding 1. Ordinary single-line metacharacter values are rejected, but a valid line makes multiline values pass. The stock entrypoint ordering/failure propagation is correct (`image-evidence/docker-entrypoint.sh:4,17–39,47`). |
| **C6** | **Refuted at the default router header boundary:** finding 4. Trusting a router peer does not sanitize an appended client prefix. The chart regression reproduces the missing `replace` policy; the pinned ASGI probe demonstrates scheme/client consequences. No live router or nginx chain was executed. |
| **C7** | **Correct for the rendered single release with NetworkPolicy enabled and Route exposure.** `monitoring.yaml:11–27` selects API/worker components and admits same-namespace portal labels on 8080; `monitoring.yaml:40–50` admits only ingress-labelled namespaces on 8080 to portal labels. `_helpers.tpl:14–17` matches deployment labels. `api.yaml:101–112` makes the headless Service select API name/component only. Worker/jobs use internal adapters, not cmapi HTTP (`worker.yaml:48`; `jobs.yaml:31,76–85`). These are namespace/label controls; see scope qualifications below. |
| **C8** | **Supported for arbitrary UID + group 0 under the stated SCC; image was inspected, not run.** Both FROMs are digests (`Containerfile:11,21`), stock site removed at line 47, group-write permissions at line 55, final non-root USER at line 56. Runtime pid/temp paths are `/tmp` (`nginx.conf:11,22–26`), logs are stderr/stdout (`nginx.conf:12`, template lines 81/165). Image default UID 101 has GID 101 in passwd; group 0 is the arbitrary-UID OpenShift scenario, not the base user's default primary group. |
| **C9** | **Supported as a bounded graceful drain, not a guarantee that every request completes.** Hook `portal.yaml:82` waits 5 seconds, sends quit, and waits for nginx to exit; grace is 30 seconds at line 53, worker drain is 20 seconds at `nginx.conf:9`. Pinned Alpine 3.24.2 contains `/usr/bin/pgrep -> /bin/busybox` (`image-files.txt:2`). Normal kubelet stop signalling occurs after preStop; the hook waits out the drain first. A premature SIGTERM would interrupt draining; SIGQUIT remains graceful. Requests longer than the drain window may be cut. No live shutdown run here. |

## C1: path confusion examined

The backend was tested with actual uvicorn 0.32.1's h11 protocol and Starlette 0.41.3, in memory with a transport stub and real StaticFiles mounts. It does not run cmapi's app factory or access a database. The front door's nginx normalization was checked against the pinned parser source, not measured in this sandbox. uvicorn's pinned implementation assigns `path = unquote(raw_path.decode("ascii"))`; Starlette matches that path with route regexes and handles StaticFiles inside its mount boundary. [uvicorn decoding](https://raw.githubusercontent.com/encode/uvicorn/0.32.1/uvicorn/protocols/http/h11_impl.py), [Starlette routing](https://raw.githubusercontent.com/encode/starlette/0.41.3/starlette/routing.py), [StaticFiles containment](https://raw.githubusercontent.com/encode/starlette/0.41.3/starlette/staticfiles.py), [nginx 1.30.6 parser](https://raw.githubusercontent.com/nginx/nginx/release-1.30.6/src/http/ngx_http_parse.c).

| Input | Analysis / observed backend behavior |
|---|---|
| `/docs/..%2Freadyz` | nginx decodes the slash and removes `..` for matching, yielding `/readyz`, so the portal fallback is selected. Passing the original directly to uvicorn produces `/docs/../readyz`, which Starlette returns 404 for, not the readiness route. |
| `/static/swagger/..%2f..%2freadyz` | nginx matching yields `/readyz`, outside the proxy locations. The direct backend probe yields `/static/swagger/../../readyz`; StaticFiles returns 404 and does not redispatch into the `/readyz` router. |
| `/problems/%2e%2e/readyz` | nginx matching yields `/readyz`; direct backend path remains `/problems/../readyz` and is 404. |
| `/docs/../readyz`, `/docs/%2e%2e/readyz`, `/docs//../readyz` | Same dot-segment reasoning; all direct backend probes returned 404. |
| `/docs/%252e%252e/readyz` | One decode leaves literal `%2e%2e`; the backend does not decode it again. Probe returned 404. |
| `/api%2Fv1%2Fversion` | Decodes to the permitted `/api/v1/version`; probe returned 200. |
| `//readyz` | nginx merges slashes and takes the portal fallback. The direct backend retained `//readyz` and returned 404. |
| `/docs/..;/readyz` | Semicolon is ordinary path text, not a removed matrix parameter; probe returned 404. |
| `/docs/..\readyz` | On this Unix/Alpine target a backslash is ordinary text, not a slash; probe returned 404. |
| `/docs/%00/readyz` | nginx rejects the decoded NUL. Direct backend probe retained a NUL and did not match readiness; returned 404. |

Thus the two components **can read the same original URI as different path strings**, but that alone is not an allowlist bypass. In particular, the three encoded traversal examples in the brief normalize *out* of the API locations at nginx. Conversely, an original path such as `/x/../docs` can match nginx's `/docs` but fail the backend's exact route match. I found no second backend normalization that would expose `/readyz` or the API's `/healthz`. The public `/healthz` is nginx's own text response (`cmapi.conf.template:98–102`), not the API's health JSON (`routers/health.py:26–29`). This conclusion is source/probe-supported, not a passing full nginx traversal test.

## C3: DELETE and PUT in this API

`DocumentedRouter.write` defaults to POST (`cmapi/src/cmapi/core/docs.py:184–190`). I searched all core routers and plugin router files for method overrides and direct route registration. There is no implemented PUT route. The only implemented DELETE is `plugins/namespaces/router.py:181–194`.

That DELETE requires an Idempotency-Key (`:189`, `_idem` at `:41–48`), checks a caller-scoped replay **before** planning (`:190–192`), and uses `_submit`'s conflict/replay handling (`:65–79`). The database enforces the idempotency key and namespace lock (`core/db/repo.py:148–164`). nginx preserves the original headers on its retry. I found no duplicate destructive side effect from retrying that implemented DELETE with the same key; it submits a change request rather than deleting the live namespace immediately. Missing keys fail before submission. PUT reaches no write handler. This is a code review conclusion; no database replay test was run.

## C7/C8/C9: qualifications that matter

- NetworkPolicies are additive and the `-metrics` destination selector uses only `component in [api, worker]` (`monitoring.yaml:11–13`). It covers the intended release's pods, but it is not isolation between multiple releases in the same namespace: multiple such policies would admit the union of their portals to all matching API pods. The reviewed rendered deployment uses one release in the namespace. Other namespace policies, pod-label spoofing privileges, and node/port-forward access are outside what these selectors can prove.
- Route-mode front-door policy trusts every pod in a matching namespace; it does not identify router pods individually. Ingress mode deliberately has no source restriction. `networkPolicy.enabled=false` removes both policies (`monitoring.yaml:2`); the default is true (`values.yaml:245–247`). I did not report those explicit switches as undisclosed bypasses.
- Image configuration records `User: 101`, `StopSignal: SIGQUIT`, and nginx 1.30.6. The copied base filesystem shows group-writable `/etc/nginx` and `conf.d`, and `nginx.conf` (`image-files.txt:6–8`); the final Containerfile applies those permissions again after COPY. The image's worker autotune script modifies `nginx.conf` with a directory write, supported by these permissions. Runtime nginx writes use `/tmp` plus the standard logging streams; startup template/autotune writes to `/etc/nginx` are intentional.
- Five seconds of preStop delay permits endpoint/router propagation; quit then closes listeners and drains workers for at most 20 seconds. The polling interval can add about a second before the hook returns. A normal kubelet SIGTERM/SIGQUIT comes after the hook, when nginx has already exited. If a TERM arrives during draining from another source, nginx's termination path takes precedence and stops workers promptly; a repeated QUIT preserves graceful behavior. This is visible in nginx 1.30.6's master/worker process loops. [Pinned process-cycle implementation](https://raw.githubusercontent.com/nginx/nginx/release-1.30.6/src/os/unix/ngx_process_cycle.c).

## Checked and found correct

- One public backend per instance: Routes/Ingresses select `-portal`, not `-api` (`exposure.yaml:49,79–80`); 11 original chart tests passed.
- CRC's instance/API/portal URL and realm redirects use `https://cmapi.apps-crc.testing` (`crc.yaml:16–17,36–37,91–94`).
- Headless Service uses `clusterIP: None`, API name/component labels, and HTTP port 8080 only (`api.yaml:101–112`).
- API readiness is excluded from ready endpoint DNS by the default Service behavior; the API's readiness probe is `/readyz` (`api.yaml:64–67`).
- Every ordinary location that adds Cache-Control or CSP includes the full applicable header set (`cmapi.conf.template:105–156,177–185`; header snippets).
- Common headers use `always`, and upstream duplicates/CSP are hidden (`headers-common.conf:5–12`; `proxy.conf:20–29`).
- Portal/docs/API/mockup CSP strings match the decision record; only docs and mockup get inline allowances (`cmapi.conf.template:44–59`; review README:108–113).
- API Cache-Control is preserved when present, otherwise `no-store` is added (`cmapi.conf.template:38–41`; `proxy-api.conf:7`).
- Already-sent POST/PATCH/LOCK cannot retry without `non_idempotent`; it is absent (`proxy.conf:16`; pinned nginx retry implementation).
- Implemented DELETE requires and replays the same idempotency key; PUT has no implemented handler (`plugins/namespaces/router.py:181–194`).
- Access-log format omits query arguments, Authorization, and Cookie and escapes caller fields as JSON (`cmapi.conf.template:15–20`).
- Invalid request IDs are replaced before proxying, and the observability middleware reads that header (`cmapi.conf.template:24–27`; `proxy.conf:10`; `observability.py:85`).
- The entrypoint validates before substitution and propagates rejection out of its final pipeline stage (`Containerfile:51`; extracted entrypoint:17–39).
- Both build/runtime bases are pinned by full digest; default.conf is removed; final USER is non-root (`Containerfile:11,21,47,56`).
- `/etc/nginx` permissions support arbitrary UID with group 0, and pid/temp paths are `/tmp` (`Containerfile:55`; `nginx.conf:11,22–26`).
- The exact pinned Alpine layer contains pgrep; the hook waits for nginx after graceful quit (`image-files.txt:2`; `portal.yaml:82`).

All files requested in the brief were read in full (including all nginx snippets, both test files, main.py, observability.py, the chart files/values, CRC values, and the decision record). Out-of-scope plain manifests, the nginx-vs-Envoy/origin decisions, and the separate ReDoc rendering issue were not treated as findings.
