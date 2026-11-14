# Fable's review of PR #238: the nginx front door (PR-A of #226)

Reviewer: Fable 5.2, 2026-11-14. Head `0bae57b94ddf437fc023e95c9d8d66cb5b71377b`, on main `0c70b0e`. Nothing was
pushed or merged. The fixes and tests below are in my own worktree
`/Users/olasumbo/gitRepos/workbench/cmapi/fable-review/wt-238-fix`, and as one diff in
`/Users/olasumbo/gitRepos/workbench/cmapi/fable-review/pr-238-files/fixes-and-tests.diff`.

**Verdict: changes requested, all small.** The retries, the keepalive set-up, the headers, the Route's header
replacement, the access log and the graceful stop do what the record says (table below). Two statements of the
decision record are not true of the configuration, each proven by a failing check: API answers are compressed (F1),
and an authorization code can reach a log (F2). One setting cannot take effect on OpenShift (F3). F4 to F7 are low.

## How it was measured

- nginx 1.30.6, the native build of OB1 run 6 (`workbench/cmapi/ob1-run6/nginx/sbin/nginx`), on this Mac. No cluster,
  no container (#157).
- The PR's own harness, unchanged, on the head: `python3 deploy/tests/front-door-test.py --nginx <that binary>`:
  330 checks, 0 failed (`pr-238-files/front-door-full-baseline.txt`). It runs `nginx -t` and `nginx -T` on the rendered
  template.
- My probes: `pr-238-files/probe.py` and `ka.py`, which import the harness and use its stand-in pods.
- With the fixes: the harness with my new case, 339 checks, 0 failed (`front-door-full-after.txt`). The new case alone
  on the PR's configuration: 3 of 9 failed (`front-door-case-before.txt`); with the fixes: 0 failed
  (`front-door-case-after.txt`).
- The chart tests ran under `ob1-run5/tools/suite.sh` (service; only `tests/service/test_front_door_chart.py`).
  Before the chart fixes: 2 failed, 12 passed. After: 14 passed (`pr-238-files/chart-before.log`, `chart-after.log`). The ten test files that render the chart, on the fixed tree: 193 passed. The whole service suite was not run on the fixed tree.
- Not measured: anything on kind or CRC, the built image, a browser. F3 and F5 rest on the documentation cited and on
  the rendered chart.

## What was checked and holds

| Claim | Evidence |
|---|---|
| A non-idempotent request is never repeated | The harness's matrix (reset, read timeout, 502, 503, 504 by GET, POST, PATCH, LOCK, DELETE, PUT): POST, PATCH and LOCK reach one pod. nginx counts DELETE and PUT as idempotent and repeats them. The API has one DELETE and no PUT (`cmapi/contract/openapi.json`: 20 get, 10 post, 1 delete, 1 patch). That DELETE needs an `Idempotency-Key` (`plugins/namespaces/router.py:189`, `_idem(key, False)` answers 400 without one), and a second pod replays the first answer (`_replay`, and the 409 path of `_submit`, lines 65 to 79). So a repeated DELETE opens no second request |
| Retries are bounded | `proxy_next_upstream_tries 2`. Measured: 2 GETs that both pods answer 503 made 4 upstream calls |
| An answer of 502, 503 or 504 that the API itself makes does not take the instance down | I expected two such answers to mark both pods failed, so that the next healthy request gets nginx's 502. Measured, it does not: after two GETs answered 503 by both pods, four healthy GETs got 200 from both pods, and nginx logged no "no live upstreams". I withdraw that concern. What remains is one more upstream call for each such GET, which helps when the cause is in one pod (a signing key that only the other pod has cached) |
| Keepalive to 2 or 3 pods | The harness: 12 requests over 3 pods used 3 connections. Mine: an idle upstream connection is reused after 3.0 s and is closed after 4.6 s (`ka.py`), below uvicorn's 5 s |
| The OWASP headers, once, also on errors | The harness checks each value on 200, 400, 401, 404, 413, 500, 502 and 504, and that a value from the API is hidden. Each header left out has its reason in the record (COEP, COOP on Swagger UI, Clear-Site-Data, `no-store` on assets) |
| `'unsafe-eval'` only where needed | Only in `$cmapi_csp_redoc` (`location = /redoc`) and on the mockup's host. `/static/redoc/` and `/docs` get the docs policy, without it |
| The Route replaces the forwarded headers | `haproxy.router.openshift.io/set-forwarded-headers: replace` on both Routes; the chart test asserts it. nginx then appends the router's address (`$proxy_add_x_forwarded_for`) |
| The access log has no token and no query string | `$uri`, no `Authorization`, no cookie. The harness asserts it for `/?code=...` |
| Graceful stop | preStop: 5 s, then `nginx -s quit`; `worker_shutdown_timeout 20s`; grace period 30 s. A request that runs longer than 20 s at a stop is cut, which the record accepts |
| The policies on OpenShift | API port 8080: only pods of component `portal`, in the same namespace. Front door: only namespaces with `policy-group.network.openshift.io/ingress: ""`. Port 9090: only the monitoring namespace |

## Findings

### F1 (medium). API answers are compressed; the record says none is

- **Where:** `cmapi-portal-ui/nginx/templates/cmapi.conf.template:100-104`;
  `docs/reviews/2026-11-14-issue-226/README.md:134-135`.
- **The claim:** "Static files only: gzip_proxied stays off, so no API response that can carry a reflected value is
  compressed."
- **Evidence:** `GET /api/v1/requests?filter=aaa...` (3000 characters, which the stand-in pod puts in its JSON) with
  `Accept-Encoding: gzip` answers `Content-Encoding: gzip`, 96 bytes. The same request with a `Via` header is not
  compressed, and then a static asset is not compressed either. nginx's documentation: gzip_proxied acts on "proxied
  requests", and "the fact that the request is proxied is determined by the presence of the 'Via' request header field"
  (ngx_http_gzip_module). It does not mean `proxy_pass`. The OpenShift router sends no `Via`.
- **How bad:** the control that the record claims is absent. An attack through it (BREACH) needs a page of another
  origin that can make the browser send an authenticated request. The portal sends its token in a header from memory,
  not a cookie, so I see no working attack today. The fix is one line, and the record's sentence must be true.
- **Fix:** `gzip off;` in `location /api/`. The OpenAPI document and the bundles hold no secret and stay compressed,
  as they are today (the Swagger UI bundle is 1,685,697 bytes in `ob1-run6/docs-static-310/`). Correct the comment at line 100 and the record's sentence to:
  "gzip is on for the static files, the API's pages and bundles and the OpenAPI document. `location /api/` turns it
  off: `gzip_proxied` is about a request with a `Via` header, not about `proxy_pass`."
- **Test:** `case_fable_review`, checks 1 to 4. Before: "FAIL a JSON answer of the API is not compressed
  (Content-Encoding: gzip, 96 bytes)". After: ok.

### F2 (medium). An authorization code can reach nginx's error log

- **Where:** `cmapi-portal-ui/nginx/nginx.conf:12` (`error_log stderr notice`), and
  `cmapi.conf.template:13-14`: "an authorization code must not reach a log".
- **Evidence:** `GET /docs/oauth2-redirect?code=AUTHZ-CODE-SECRET-1&state=s`, with both pods closing the connection,
  writes to stderr:

  ```
  [error] 8095#0: *8 upstream prematurely closed connection while reading response header from upstream, client: 127.0.0.1, server: cmapi.apps-crc.testing, request: "GET /docs/oauth2-redirect?code=AUTHZ-CODE-SECRET-1&state=s HTTP/1.1", upstream: "http://127.0.0.1:53814/docs/oauth2-redirect?code=AUTHZ-CODE-SECRET-1&state=s", host: "cmapi.apps-crc.testing"
  ```

  nginx writes the request line, the upstream URL and the `Referer` of a failed upstream request, and that line has no
  format to set. `/docs/oauth2-redirect` is where Keycloak returns Swagger UI's sign-in, and it is passed to the API.
  The portal's own return (`/?code=...`) is a static file: my probe found no line for it, also for a 404.
- **How bad:** the code is used once, lives for a short time and is bound to PKCE, so the risk is low. But the pod's
  stderr goes to the cluster's log store, and the record says that no code reaches a log.
- **Fix:** an exact location for the redirect page that logs nothing below `crit`. The access log still records the
  502, with both upstream addresses and no query string.
- **Test:** `case_fable_review`, the last three checks. Before: "FAIL the authorization code of a failed
  /docs/oauth2-redirect is not in nginx's error log". After: ok.
- **Left open:** an `/api/` request that fails upstream also has its query string in the error log. The API takes no
  credential in a query (bearer token in the header), so that is a filter value, not a secret. Say so in the record.

### F3 (medium, inferred, not measured on CRC). The router gives up before nginx's own limit

- **Where:** `deploy/helm/cmapi/templates/exposure.yaml:43-44`; `cmapi-portal-ui/nginx/cmapi/proxy-api.conf:4`
  (`proxy_read_timeout 60s`); `proxy.conf:17` (`proxy_next_upstream_tries 2`).
- **Evidence:** the Route sets no `haproxy.router.openshift.io/timeout`, and nothing in the repository does
  (`grep -rn "router.openshift.io/timeout"`: no line). The router's default: "serverTimeout defines how long a
  connection will be held open while waiting for a server/backend response. If unset, the default timeout is 30s"
  (openshift/api, `operator/v1/types_ingresscontroller.go`). So an API call that takes 30 to 60 s gets the router's
  504 page, which has no security header and is not a problem document. nginx's 60 s, and the second try after a read
  timeout (Codex's F3), then never run for a caller behind the Route. The harness cannot see this: it has no router.
- **Fix:** the instance's Route gets `haproxy.router.openshift.io/timeout`, from a new value `route.timeout: 130s`,
  above nginx's worst case (2 tries of 2 s + 60 s = 124 s). The mockup's Route keeps the default.
- **Test:** `test_the_router_waits_longer_than_the_front_door` reads the three numbers from the nginx files and
  compares them with the rendered annotation. Before: failed (no annotation). After: passed.
- **For the coordinator:** the other way is to lower nginx's limits below 30 s. That needs a measured time for the
  slowest call (a plan with a dry run), which the record does not give. Prove either on CRC when #157 allows.

### F4 (low). A bearer token above 8 kB is refused at the front door

- **Where:** `cmapi.conf.template`, the portal's server: no `large_client_header_buffers`, so nginx's default of
  `4 8k` holds, and one header line must fit one buffer.
- **Evidence:** `Authorization: Bearer` + 12000 characters: 400 from nginx. With 7000: 200.
- **How bad:** before this PR the path was router to uvicorn. The front door now has the smallest limit on the path.
  cmapi's tokens carry the caller's groups, and their size on the real realm is not measured, so this is a guard and
  not a seen failure.
- **Fix:** `large_client_header_buffers 4 16k;`.
- **Test:** `case_fable_review`: "a 12 kB Authorization header reaches the API": before 400, after 200. A 20 kB one is
  still refused.

### F5 (low). With Ingress exposure, any pod of the cluster can reach the front door and set the forwarded headers

- **Where:** `deploy/helm/cmapi/templates/monitoring.yaml:44-51`: with `exposure: Ingress` the rule has no `from`.
  The template's comment says so. The PR's body ("only the router reach the front door") holds for a Route only.
- **Evidence:** a request with `X-Forwarded-For: 6.6.6.6`, `X-Forwarded-Proto: https` and `Host: evil.example` reaches
  the stand-in pod as `X-Forwarded-For: 6.6.6.6, 127.0.0.1`, `X-Forwarded-Proto: https`, `Host: evil.example`,
  `X-Forwarded-Host: evil.example` (`probe.py`, P5). uvicorn trusts every peer (`forwarded_allow_ips="*"`,
  `main.py:341`). The API does not read the client's address for a decision today (`grep request.client`: no line), so
  the effect is a false address and scheme in logs and links.
- **Fix:** a value `networkPolicy.ingressNamespace`. Set, only that namespace reaches the front door. Empty, it is
  open as now, and the value's comment says what that allows.
- **Test:** `test_with_ingress_the_front_door_can_be_closed_to_all_but_the_controller`. Before: failed. After: passed.

### F6 (low, fix not tested in a browser). ReDoc's policy leaves three directives to the browser's default

- **Where:** `cmapi.conf.template:49-51` and `cmapi/src/cmapi/main.py:289-290` (the same string).
- **Evidence:** `default-src 'none'` does not cover `frame-ancestors`, `base-uri` and `form-action` (CSP Level 3: they
  have no fallback). The portal's, the docs' and the mockup's policies set all three; the API's sets
  `frame-ancestors`. `X-Frame-Options: DENY` covers framing.
  `/redoc` also has no `Cross-Origin-Opener-Policy`, though it uses no popup.
- **Fix:** append `; frame-ancestors 'none'; base-uri 'none'; form-action 'none'` to `$cmapi_csp_redoc`, to
  `REDOC_CSP` and to the harness's `CSP_REDOC`, and add `add_header Cross-Origin-Opener-Policy "same-origin" always;`
  to `proxy-redoc.conf`.
- **Test:** the harness already fails when the three strings differ (line 387). The proof that ReDoc still renders and
  searches is `cmapi-portal-ui/tests/front-door.test.mjs`, which I did not run. Accept this only after it passes.

### F7 (low, documents). docs/15 still gives the hosts that this PR removes

- **Where:** `docs/15-keycloak-integration.md:25-26` (the redirect URIs `https://cmapi-portal.apps-crc.testing/` and
  `https://cmapi-api.apps-crc.testing/docs/oauth2-redirect`), lines 229 and 276; `docs/13-crc-deployment.md:467`;
  `cmapi-portal-ui/config.example.json:2`; `deploy/oidc-login.py:5`.
- **Evidence:** `deploy/environments/crc.yaml` in this PR sets `https://cmapi.apps-crc.testing/...` for all three. The
  PR's body leaves the plain manifests and the Wave 1 scripts to the next PR, which covers `deploy/crc-proof.sh:10`
  and `deploy/manifests/`. It lists docs/15 as updated.
- **Fix:** replace the two hosts with `cmapi.apps-crc.testing` in those lines of docs/15 and docs/13, and in the two
  examples, or name them in "Not in this PR".
- **Test:** add to `test_the_instance_url_is_the_front_door_for_the_realm_and_the_api`:
  `assert "cmapi-api.apps-crc.testing" not in (ROOT / "docs/15-keycloak-integration.md").read_text()`, and the same for
  `cmapi-portal.apps-crc.testing`. It fails on the head.

## Notes, no change asked

- `portal.replicas` is 1. Every call to the API, the CLI's too, now passes this one pod. On a cluster with more than
  one node, 2 replicas and a spread over nodes fit the 2 or 3 API pods of #225.
- The API pod has no preStop. At a rolling restart uvicorn closes its idle connections at SIGTERM, and a POST that
  nginx sends on one at that moment gets 502 and is not repeated. A short preStop sleep on the API pod closes most of
  it. Not measured here.
- `deploy/tests/front-door-test.py`, the retry matrix, still replaces `proxy_next_upstream_timeout 10s;`, a line that
  no longer exists since Codex's F3. It does nothing.
- The portal's server is the `default_server`, so it passes any `Host` to the API. Behind a Route only the Route's
  hosts arrive.

## The full code of the fixes and the tests

`pr-238-files/fixes-and-tests.diff` applies to `0bae57b` with `git apply`.

```diff
diff --git a/cmapi-portal-ui/nginx/templates/cmapi.conf.template b/cmapi-portal-ui/nginx/templates/cmapi.conf.template
index 2effb50..47d30b2 100644
--- a/cmapi-portal-ui/nginx/templates/cmapi.conf.template
+++ b/cmapi-portal-ui/nginx/templates/cmapi.conf.template
@@ -96,8 +96,10 @@ server {
     client_body_timeout 10s;
     send_timeout 30s;
     keepalive_timeout 65s;
+    # A header line must fit in one buffer, and the default is 8k. An access token grows with the groups in it.
+    large_client_header_buffers 4 16k;
 
-    # Static files only: gzip_proxied stays off, so no API response that can carry a reflected value is compressed.
+    # The static files, the API's pages and bundles and the OpenAPI document. "location /api/" turns it off.
     gzip on;
     gzip_vary on;
     gzip_min_length 1024;
@@ -112,6 +114,10 @@ server {
     # The API: its routes, the OpenAPI document and the problem pages.
     location /api/ {
         include /etc/nginx/cmapi/proxy-api.conf;
+        # No answer of an API route is compressed: one can carry a value that the caller sent next to a secret one.
+        # The server's "gzip on" would compress it: gzip_proxied is about a request that came with a Via header, not
+        # about proxy_pass (ngx_http_gzip_module).
+        gzip off;
     }
     location = /openapi.json {
         include /etc/nginx/cmapi/proxy-api.conf;
@@ -133,6 +139,13 @@ server {
     location /docs/ {
         include /etc/nginx/cmapi/proxy-docs.conf;
     }
+    # Swagger UI's sign-in returns here with "?code=...&state=...". nginx writes the request line and the upstream URL
+    # of a failed upstream request to its error log, query string and all, and that line has no format to set. So
+    # this location logs nothing below "crit"; the access log (no query string) still records the failure.
+    location = /docs/oauth2-redirect {
+        include /etc/nginx/cmapi/proxy-docs.conf;
+        error_log stderr crit;
+    }
     location = /redoc {
         include /etc/nginx/cmapi/proxy-redoc.conf;
     }
diff --git a/cmapi/tests/service/test_front_door_chart.py b/cmapi/tests/service/test_front_door_chart.py
index 092d75e..c2c03c2 100644
--- a/cmapi/tests/service/test_front_door_chart.py
+++ b/cmapi/tests/service/test_front_door_chart.py
@@ -7,6 +7,7 @@ from __future__ import annotations
 
 import json
 import pathlib
+import re
 import shutil
 import subprocess
 
@@ -146,3 +147,31 @@ def test_route_replaces_untrusted_forwarded_headers(crc):
     for route in routes:
         annotations = route["metadata"].get("annotations", {})
         assert annotations.get("haproxy.router.openshift.io/set-forwarded-headers") == "replace", route["metadata"]["name"]
+
+
+def _seconds(conf: str, directive: str) -> int:
+    return int(re.search(rf"^{directive} (\d+)s;", conf, re.M).group(1))
+
+
+def test_the_router_waits_longer_than_the_front_door(crc):
+    """Fable's review, F3. The router's default server timeout is 30 s (IngressController tuningOptions.serverTimeout). Below the
+    front door's own limit, the router answers 504 with its own page first, and nginx's limit and second try never run."""
+    nginx = ROOT / "cmapi-portal-ui/nginx/cmapi"
+    proxy, api = (nginx / "proxy.conf").read_text(), (nginx / "proxy-api.conf").read_text()
+    tries = int(re.search(r"^proxy_next_upstream_tries (\d+);", proxy, re.M).group(1))
+    worst = tries * (_seconds(proxy, "proxy_connect_timeout") + _seconds(api, "proxy_read_timeout"))
+    routes = {r["metadata"]["name"]: r["metadata"]["annotations"] for r in find(crc, "Route")}
+    timeout = routes["cmapi"].get("haproxy.router.openshift.io/timeout")
+    assert timeout is not None and timeout.endswith("s") and int(timeout[:-1]) > worst, (timeout, worst)
+    assert "haproxy.router.openshift.io/timeout" not in routes["cmapi-mockup"]      # a static page: the default is enough
+
+
+def test_with_ingress_the_front_door_can_be_closed_to_all_but_the_controller(tmp_path):
+    """Fable's review, F5. With Ingress exposure the port was open to every pod of the cluster, and nginx passes a caller's
+    X-Forwarded-For and X-Forwarded-Proto on. networkPolicy.ingressNamespace names the controller's namespace."""
+    args = ("-f", str(CRC), "--set", "exposure=Ingress", "--set", "ingress.host=cmapi.example", "--set", "ingress.mockup.host=m.example")
+    door = find(render(tmp_path, *args, "--set", "networkPolicy.ingressNamespace=ingress-nginx"), "NetworkPolicy", "cmapi-front-door")[0]["spec"]
+    assert door["ingress"] == [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}}}],
+                                "ports": [{"port": 8080, "protocol": "TCP"}]}]
+    door = find(render(tmp_path, *args), "NetworkPolicy", "cmapi-front-door")[0]["spec"]
+    assert door["ingress"] == [{"ports": [{"port": 8080, "protocol": "TCP"}]}]      # unset: open, as before, and documented
diff --git a/deploy/helm/cmapi/templates/exposure.yaml b/deploy/helm/cmapi/templates/exposure.yaml
index 2253c76..dfee5cb 100644
--- a/deploy/helm/cmapi/templates/exposure.yaml
+++ b/deploy/helm/cmapi/templates/exposure.yaml
@@ -42,6 +42,11 @@ metadata:
   labels: {{- include "cmapi.labels" $ | nindent 4 }}
   annotations:
     haproxy.router.openshift.io/set-forwarded-headers: replace
+    {{- if eq $site.key "instance" }}
+    # The router's own limit on the wait for an answer is 30 s. It must be above the front door's, or the router
+    # answers 504 with its own page before nginx's limit and second try run (values.yaml, route.timeout).
+    haproxy.router.openshift.io/timeout: {{ $.Values.route.timeout | quote }}
+    {{- end }}
 spec:
   {{- if $site.host }}
   host: {{ $site.host }}
diff --git a/deploy/helm/cmapi/templates/monitoring.yaml b/deploy/helm/cmapi/templates/monitoring.yaml
index 3035256..b0dab1e 100644
--- a/deploy/helm/cmapi/templates/monitoring.yaml
+++ b/deploy/helm/cmapi/templates/monitoring.yaml
@@ -45,6 +45,10 @@ spec:
       from:
         - namespaceSelector:
             matchLabels: {policy-group.network.openshift.io/ingress: ""}
+      {{- else if .Values.networkPolicy.ingressNamespace }}
+      from:
+        - namespaceSelector:
+            matchLabels: {kubernetes.io/metadata.name: {{ .Values.networkPolicy.ingressNamespace }}}
       {{- end }}
       ports:
         - {port: 8080, protocol: TCP}
diff --git a/deploy/helm/cmapi/values.yaml b/deploy/helm/cmapi/values.yaml
index 7ab99bd..e4cd11e 100644
--- a/deploy/helm/cmapi/values.yaml
+++ b/deploy/helm/cmapi/values.yaml
@@ -215,6 +215,9 @@ migrate:                          # the initContainer that migrates the schema b
 exposure: Route
 route:
   host: ""                         # empty: subdomain <release>
+  # How long the router waits for the front door's answer. Above the front door's worst case for the API: two tries of
+  # 2 s to connect and 60 s to answer (cmapi-portal-ui/nginx/cmapi/proxy.conf and proxy-api.conf), 124 s.
+  timeout: 130s
   mockup:
     host: ""                       # empty: subdomain <release>-mockup
 ingress:
@@ -246,6 +249,10 @@ monitoring:
 
 networkPolicy:
   enabled: true
+  # With Ingress exposure: the namespace of the ingress controller, which alone may reach the front door. Empty, the
+  # front door's port is open to every pod of the cluster, and each of them can send X-Forwarded-For and
+  # X-Forwarded-Proto as it likes. With Route exposure the router's namespace is known and this is not used.
+  ingressNamespace: ""
   monitoringNamespace: openshift-user-workload-monitoring
 
 # -------------------------------------------------------------------------- security
diff --git a/deploy/tests/front-door-test.py b/deploy/tests/front-door-test.py
index 8fa2fa0..d938fb3 100755
--- a/deploy/tests/front-door-test.py
+++ b/deploy/tests/front-door-test.py
@@ -649,6 +649,48 @@ def case_review_retry_matrix(ng: Nginx) -> None:
                 good.stop()
 
 
+def case_fable_review(ng: Nginx) -> None:
+    print("Fable's review: no compressed API answer, no query string in nginx's error log, a large bearer token")
+    pods = [Pod("a"), Pod("b")]
+    port = free_port()
+    d = ng.write(GOOD_ENV, port, [f"127.0.0.1:{p.port}" for p in pods])
+    proc = ng.start(d, port)
+    try:
+        # F1: the stand-in answers with the path, so a long path gives a JSON answer above gzip_min_length.
+        long = "/api/v1/requests?filter=" + "a" * 3000
+        status, h, body = request(port, "GET", long, headers={"Accept-Encoding": "gzip"})
+        check(status == 200 and one(h, "content-encoding") is None and len(body) > 3000,
+              f"a JSON answer of the API is not compressed (Content-Encoding: {one(h, 'content-encoding')}, {len(body)} bytes)")
+        for path in ("/openapi.json", "/static/swagger/swagger-ui-bundle.js"):
+            status, h, _b = request(port, "GET", path + "?pad=" + "a" * 3000, headers={"Accept-Encoding": "gzip"})
+            check(status == 200 and one(h, "content-encoding") == "gzip", f"{path}, which holds no secret, stays compressed")
+        status, h, _b = request(port, "GET", "/assets/index-AbC123.js", headers={"Accept-Encoding": "gzip"})
+        check(status == 200 and one(h, "content-encoding") == "gzip", "a static file of the portal is compressed")
+
+        # F4: Keycloak's access token grows with the groups in it; nginx's default refuses a header line above 8k.
+        status, _h, _b = request(port, "GET", "/api/v1/me", headers={"Authorization": "Bearer " + "t" * 12000})
+        check(status == 200, f"a 12 kB Authorization header reaches the API ({status})")
+        status, _h, _b = request(port, "GET", "/api/v1/me", headers={"Authorization": "Bearer " + "t" * 20000})
+        check(status == 400, f"a 20 kB Authorization header is refused ({status})")
+
+        # F2: the Swagger UI sign-in returns to /docs/oauth2-redirect?code=...&state=... . nginx writes the request line
+        # of a failed upstream request to its error log, so that location logs no upstream error.
+        status, _h, _b = request(port, "GET", "/docs/oauth2-redirect?code=AUTHZ-CODE-SECRET&state=STATE-SECRET",
+                                 headers={"X-Test-Failure": "reset"})
+        check(status == 502, f"the redirect page answers 502 when both pods fail ({status})")
+        time.sleep(0.3)
+        errors = (d / "error.log").read_text()
+        check("AUTHZ-CODE-SECRET" not in errors and "STATE-SECRET" not in errors,
+              "the authorization code of a failed /docs/oauth2-redirect is not in nginx's error log")
+        entry = [e for e in access_log(d) if e["uri"] == "/docs/oauth2-redirect"]
+        check(len(entry) == 1 and entry[0]["status"] == 502 and "," in entry[0]["upstream_addr"],
+              "the access log still records the failure and both pods")
+    finally:
+        ng.stop(proc)
+        for p in pods:
+            p.stop()
+
+
 def main() -> int:
     ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
     g = ap.add_mutually_exclusive_group(required=True)
@@ -680,6 +722,7 @@ def main() -> int:
         case_review_env_single_line()
         case_review_error_headers(ng)
         case_review_retry_matrix(ng)
+        case_fable_review(ng)
         if args.image:
             case_image(args)
     print(f"front door cases failed: {len(failures)}")
```
