OB3 (reviewer 2) on cmapi PR #435 (Closes #434, cluster TLS trust), head 9cad597 as the archive review-435/head (no .git: identity as supplied).
Depth: DEEP = F4 and F5 (cost: measured both sides), N1 (tlsServerName through an HTTP proxy: real CONNECT proxy + real TLS), thread safety (16-thread stress with atomic bundle swaps). MEDIUM = F1, F2, F3, N2, N3 (real TLS servers through the registry). SHALLOW = clusterTLS validation, metric cardinality (source reading + existing tests) -- the ones a second model should re-check first.

Copies: ob3/h = head (+ the review tests), ob3/p = head + codex-fixes.patch, ob3/f = head + ob3-fixes.patch (diff -r confirmed f == head+patch). Interpreter /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python 3.12.14, OpenSSL 3.6.4, httpx 0.28.1, httpcore 1.0.9; cmapi imported from the copy (runs/probe_*.txt line 1: ".../ob3/<copy>/cmapi/src/cmapi/__init__.py"). Sockets bind here: the 13 TLS tests Codex could not run all ran.

== Codex's findings
F1 KEPT, CHANGED (Medium, not High: needs an operator-set http CMAPI_KUBE_API_URL or a deliverer Secret's apiUrl). Holds on head (runs/head-suite.log: test_auxiliary_clients...[hub|deliverer] FAILED). CRC's hub URL https://kubernetes.default.svc passes (test_the_in_cluster_hub_url_is_still_accepted, passes head and fixed). Only stub using http: test_cluster_token_client_420.py:129, patched to https (its MockTransport replaces the client, unchanged). Changed: require_https(url, source) names the setting or the mounted file (CMAPI_KUBE_API_URL / /etc/cmapi/deliverer/<id>/apiUrl) -- Codex's "Kubernetes apiUrl must be https" did not say which; imports sorted. Effect on start: an http CMAPI_KUBE_API_URL now stops build_context with that ValueError (fail fast); on the deliverer it is a recorded job failure (worker.py:131 net).
F2 KEPT (Medium). head: st.client is old (runs/review-tests-h.txt line for test_a_rotated_token...). Fix as Codex's (sha256 of the whole token); no raw token: fp lives only in self._fingerprints (registry.py:255/325/340, compared, never logged). Added: docs/02:681 and README G6 still said token[-12:]; patched. Test also asserts no 12-char suffix in any fingerprint.
F3 KEPT (Low-Medium). Codex's unit test plus mine at the registry: EACCES on the bundle path -> C1 (trusted) cert-verify-failed with finding "the trusted CA bundle <path> (CMAPI_TRUSTED_CA_FILE) cannot be read: [Errno 13] Permission denied", C2 (caData) still connected. On head C1 is "connected" (the bundle silently left the store; the system CA signed it). Wording "cannot be read" (it is stat, not the load). docs/18:788 updated.
F4 REJECTED. Head's keyed cache already re-reads a bundle that appears: existing test_a_missing_injected_bundle_is_read_again_at_the_next_check passes on head (runs/head-suite.log). README G2 and docs/18:788 (the shipped design) say keyed, not "not cached" (analysis.md's earlier wording). Codex's fix disables the cache whenever any listed path is missing, which is CRC's and kind's normal state (20-api.yaml:124 lists the injected and the optional operator bundle; cmapi-cluster-ca is absent): measured runs/probe_f4f5.txt head 0.06 ms/call, 1 shared context of 200; Codex 40.40 ms/call, 200 distinct contexts, +123.9 MiB RSS. Guard test test_a_missing_bundle_keeps_one_shared_context passes head, FAILS on Codex's patch (runs/review-tests-p.txt).
F5 REJECTED. caData never leaves cmapi (it is never sent to the server, unlike the token of #420), it is a public CA certificate, no doc contract forbids it in findings (docs/02:754, analysis section 4 item 5 name the token only), and the only way a server "reflects" it is serving its own public CA. Cost of the fix measured (runs/probe_f4f5.txt): KubeClient._error 0.37 ms -> 13.08 ms (4 KiB proxy page, 3-cert caData) and redact up to 1932 ms per call with a 280 KB caData and a 64 KiB body (runs/probe_ctx.txt): the trailing-prefix loop of redact.py:52-55 is quadratic in the form length. No test (nothing to fix); if the coordinator keeps C7 as a caData contract, it needs a non-quadratic form set, not Codex's.
Codex's guard tests that pass on head: kept the non-redundant ones (refused import builds no client, threaded cache + rotation), dropped duplicates of test_cluster_trust_434/420 and the unused imports; the IP-SAN MemoryBIO test dropped: it exercises OpenSSL's IP-ID matching on a hand-built context; the only cmapi code it reaches is the request hook.

== What Codex missed (all with fix + test in ob3-fixes.patch; head FAIL / fixed PASS in runs/review-tests-h.txt vs runs/review-tests-f.txt)
N1 Low-Medium. tlsServerName is dropped behind an HTTP proxy. httpcore 1.0.9 _sync/http_proxy.py:312 starts the tunnel's TLS with "server_hostname": self._remote_origin.host and never reads request.extensions["sni_hostname"] (connection.py:107 and socks_proxy.py:218 do). KubeClient keeps httpx's trust_env, so with HTTPS_PROXY on the pods every verifying cluster with tlsServerName fails. Measured with a real CONNECT proxy: head "[SSL: CERTIFICATE_VERIFY_FAILED] ... IP address mismatch" for caData and trusted modes and for the watch stream (test_tls_server_name_holds_through_an_http_proxy_tunnel[caData|trusted], test_a_watch_stream_uses_tls_server_name[proxy]); direct watch stream passes on head (the hook does reach stream()). Fails closed (no trust widened), hence not High. Fix: trust._NamedContext, an SSLContext subclass whose wrap_socket/wrap_bio use the configured name; ca_data_context and trusted_context take server_name (trusted cache keyed by (paths, name)); hook kept for insecure SNI. Guard: the name never trusts more through the proxy (other CA still cert-verify-failed).
N2 Low. Verify flags: bare PROTOCOL_TLS_CLIENT on 3.12 = check_hostname True, CERT_REQUIRED, minimum TLSv1_2, verify_flags VERIFY_X509_TRUSTED_FIRST only (runs/probe_ctx.txt; same in the image: runs/image-ssl-paths.txt). Without VERIFY_X509_PARTIAL_CHAIN a caData or bundle holding the issuing intermediate (not its root) fails, while client-go's CertPool (and Python 3.13's create_default_context) treat every loaded cert as an anchor: runs/probe_chain.txt "caData = intermediate only, head context: CERTIFICATE_VERIFY_FAILED", "+ PARTIAL_CHAIN: ok", "unrelated CA + PARTIAL_CHAIN: CERTIFICATE_VERIFY_FAILED". Fix in _client_context (all verifying contexts). VERIFY_X509_STRICT deliberately not added (would refuse certificates without AKI, e.g. the suite's own test CAs; out of scope).
N3 Low. tlsServerName "api.example.test." passes valid_server_name (rstrip) but OpenSSL matches it as written: runs/probe_chain.txt "trailing dot: CERTIFICATE_VERIFY_FAILED"; and "api.example.test.." is accepted (head: status unreachable, not invalid-secret). Fix: removesuffix(".") in valid_server_name, and the registry drops one root dot before building Trust.

== Brief items (part 2), verdicts
- Verify flags: CONFIRMED check_hostname True, CERT_REQUIRED, minimum TLSv1_2 on every verifying context (probe_ctx.txt; image runs/image-ssl-paths.txt: Python 3.12.15, OpenSSL 3.5.9, min 771); REFUTED as client-go parity: no PARTIAL_CHAIN (N2). New test pins all four.
- System store: CONFIRMED trust.py:66-70 uses openssl_cafile/openssl_capath, never load_default_certs/set_default_verify_paths (which read SSL_CERT_FILE). In the local image localhost/cmapi:sha-282fb89d45 (run offline, --network=none; not the PR head's image) openssl_cafile=/etc/pki/tls/cert.pem -> /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem, 118 anchors, capath /etc/pki/tls/certs.
- tlsServerName on every request: CONFIRMED direct for request and stream (watch test [direct] passes head); every cache (WatchCache, NodeCache, ReportCache) shares the one KubeClient (kube.py:97 is the only httpx.Client in core/clients); REFUTED behind an HTTP proxy (N1).
- clusterTLS validation (SHALLOW): clustertls.py:41-53 refuses unserved env, non-mapping, unknown key, non-bool (isinstance bool: "true" and 1 refused), prod allowed; existing tests test_a_bad_cluster_tls_stops_the_start / ..._prod_included pass on head.
- Metric cardinality (SHALLOW): cmapi_cluster_tls_insecure has the one label cluster_id (observability.py:66), set at each _set and zeroed on not-imported (registry.py:466): bounded by import Secrets, as cmapi_cluster_status. No finding.
- Trust cache thread safety: CONFIRMED by stress (tools/stress_trust.py on the fixed copy): 16 threads x 40 real TLS checks, 719 atomic bundle swaps meanwhile: ok=640, errors={}, 1 cache entry (runs/stress_trust.txt). Builds race outside the lock (duplicate work, last write wins), harmless.

== Runs (tools/suite.sh, PYTHONDONTWRITEBYTECODE=1, -p no:cacheprovider, --basetemp under ob3)
- Head, 434 + chart_434 + 419 + 420 + Codex's tests: 6 failed (Codex's F1x2,F2,F3,F4,F5), 123 passed, the 13 socket tests included (runs/head-suite.log). Same on Codex's patch: 129 passed (runs/codexpatch-suite.log).
- Head with my review tests: 13 failed (exactly the 13 finding tests), 122 passed (runs/head-suite-with-review-tests.log). Fixed: 135 passed (runs/final-suite.log).
- Per test: runs/review-tests-h.txt (13F/11P), runs/review-tests-p.txt (Codex patch 12F/12P: F4 guard fails there), runs/review-tests-f.txt (24P).
- Full tests/service with PostgreSQL 55432: fixed 8 failed / 1396 passed (runs/full-service-final.*); head 27 failed / 1395 passed (runs/full-service-head.*) = the same 8 + 19 review tests. The 8 are environmental, identical on both: 6 test_contract_report_337 (venv cmapi-tools has no openapi subcommand), test_doc_citations and test_every_shell_script... (git ls-files: the archive has no .git).

== Not checked
CRC, kind, OpenShift injection; the PR head's own image; SOCKS and HTTPS (TLS-in-TLS) proxies end to end (wrap_bio path only unit-probed: probe_chain.txt last lines); Go's trailing-dot rule (no network, not cited); the portal suite. N1's insecure mode keeps SNI from the hook only, so behind a proxy its SNI is the URL host (nothing is verified there).

== Housekeeping
No tracked file touched; no git command run; review-435/head and Codex's files untouched. Created and deleted: ob3/h, ob3/p, ob3/f, ob3/tmp, ob3/bt-*. Kept: review-435/ob3-fixes.patch, ob3/tools/{probe_ctx,probe_f4f5,probe_chain,stress_trust}.py, ob3/runs/*, ob3/out.txt. Re-create the copies: rsync -a --exclude __pycache__ --exclude node_modules head/ X/ && (cd X && patch -p1 < ../ob3-fixes.patch).

== Full fixes patch (review-435/ob3-fixes.patch, -p1 against head, supersedes codex-fixes.patch)
diff -ruN a/cmapi/src/cmapi/core/clients/kube.py b/cmapi/src/cmapi/core/clients/kube.py
--- a/cmapi/src/cmapi/core/clients/kube.py	2026-11-18 18:32:32
+++ b/cmapi/src/cmapi/core/clients/kube.py	2026-11-18 19:03:23
@@ -101,7 +101,9 @@
     def _name_server(name: str) -> Callable[[httpx.Request], None]:
         """kubeconfig's tls-server-name: the name sent in SNI and checked against the certificate, for a cluster reached by an
         address its certificate does not name. It is RFC 9525's reference identity, from the import and never from the server;
-        httpcore takes the request extension `sni_hostname` as the TLS server_hostname, on every request and stream."""
+        httpcore takes the request extension `sni_hostname` as the TLS server_hostname, on every request and stream of a direct
+        connection. Its HTTP-proxy tunnel ignores the extension, so a verifying mode also carries the name in its SSLContext
+        (trust._NamedContext); the hook remains for the insecure mode's SNI."""
         def hook(request: httpx.Request) -> None:
             request.extensions["sni_hostname"] = name
         return hook
diff -ruN a/cmapi/src/cmapi/core/clients/trust.py b/cmapi/src/cmapi/core/clients/trust.py
--- a/cmapi/src/cmapi/core/clients/trust.py	2026-11-18 18:32:32
+++ b/cmapi/src/cmapi/core/clients/trust.py	2026-11-18 19:03:29
@@ -23,6 +23,7 @@
 import ssl
 import threading
 from dataclasses import dataclass
+from urllib.parse import urlsplit
 
 TRUSTED_CA_ENV = "CMAPI_TRUSTED_CA_FILE"
 # RFC 1123 host names: labels of letters, digits and hyphens, neither first nor last a hyphen; at most 253 characters.
@@ -34,24 +35,66 @@
     the registry's net for a client that cannot be made catches it; the message names the file and the variable."""
 
 
+def require_https(api_url: str, source: str) -> None:
+    """Refuses an API URL that would carry a bearer token in clear text, before any client holds the token. The managed
+    imports refuse the same in the registry's parse; this is for the hub reader and the deliverer, whose URL comes from
+    `source` (a setting or a mounted file), named in the error. The URL itself is not echoed: it may hold userinfo."""
+    try:
+        parsed = urlsplit(api_url)
+        valid = parsed.scheme == "https" and bool(parsed.hostname) and not (parsed.username or parsed.password)
+    except ValueError:                      # a malformed IPv6 host, such as https://[::1:6443
+        valid = False
+    if not valid:
+        raise ValueError(f"{source} must be an https URL with a host and no userinfo")
+
+
 def valid_server_name(name: str) -> bool:
-    """Whether `name` can be kubeconfig's tls-server-name: a DNS name or an IP address literal (RFC 9525's DNS-ID and IP-ID)."""
+    """Whether `name` can be kubeconfig's tls-server-name: a DNS name or an IP address literal (RFC 9525's DNS-ID and IP-ID).
+    A DNS name may end in one root dot, which the registry drops before use (OpenSSL does not match api.example.test. to a
+    certificate for api.example.test)."""
     try:
         ipaddress.ip_address(name)
         return True
     except ValueError:
         pass
-    return 0 < len(name) <= 253 and all(_LABEL.fullmatch(label) for label in name.rstrip(".").split("."))
+    return 0 < len(name) <= 253 and all(_LABEL.fullmatch(label) for label in name.removesuffix(".").split("."))
 
 
-def _client_context() -> ssl.SSLContext:
-    """A client context with no anchors: PROTOCOL_TLS_CLIENT verifies the chain and the host name by default."""
-    return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
+class _NamedContext(ssl.SSLContext):
+    """A client context that sends and checks one server name, whatever host the transport hands it.
 
+    kubeconfig's tls-server-name has to hold on every path to the cluster. httpcore takes the request extension
+    `sni_hostname` on a direct or SOCKS connection, but its HTTP-proxy tunnel starts TLS with the URL's host (httpcore 1.0.9,
+    _sync/http_proxy.py, TunnelHTTPConnection.handle_request), so with HTTPS_PROXY set the name would be dropped and a
+    cluster reached by an address its certificate does not name would fail. httpcore's sync backend calls `wrap_socket`,
+    and `wrap_bio` for TLS inside a TLS proxy, so the name set here is the TLS server_hostname on each of those paths."""
 
-def ca_data_context(ca_data: str) -> ssl.SSLContext:
+    server_name: str | None = None
+
+    def wrap_socket(self, sock, server_side=False, do_handshake_on_connect=True, suppress_ragged_eofs=True,
+                    server_hostname=None, session=None):
+        return super().wrap_socket(sock, server_side, do_handshake_on_connect, suppress_ragged_eofs,
+                                   self.server_name or server_hostname, session)
+
+    def wrap_bio(self, incoming, outgoing, server_side=False, server_hostname=None, session=None):
+        return super().wrap_bio(incoming, outgoing, server_side, self.server_name or server_hostname, session)
+
+
+def _client_context(server_name: str | None = None) -> ssl.SSLContext:
+    """A client context with no anchors: PROTOCOL_TLS_CLIENT verifies the chain and the host name, TLS 1.2 at least.
+
+    VERIFY_X509_PARTIAL_CHAIN makes every certificate loaded an anchor, as client-go's CertPool does: a caData or a bundle
+    that holds an intermediate CA and not its root verifies, as it does for kubectl and Argo CD. Python 3.13's
+    create_default_context sets the same flag; 3.12, the image's, does not."""
+    ctx = _NamedContext(ssl.PROTOCOL_TLS_CLIENT)
+    ctx.server_name = server_name
+    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
+    return ctx
+
+
+def ca_data_context(ca_data: str, server_name: str | None = None) -> ssl.SSLContext:
     """The caData of an import Secret as the only anchors, in memory. ssl.SSLError when it holds no certificate."""
-    ctx = _client_context()
+    ctx = _client_context(server_name)
     ctx.load_verify_locations(cadata=ca_data)
     return ctx
 
@@ -71,15 +114,21 @@
 
 
 def _signature(path: str) -> tuple[str, int, int] | None:
+    """A bundle's (path, size, mtime), or None for one that is not there or is empty. Any other failure to stat it (a
+    directory the process cannot enter, a symlink loop) is no absence: it raises TrustBundleError naming the file, so the
+    trusted clusters stop with that finding instead of being verified against a smaller store."""
     try:
         st = os.stat(path)                  # follows the ..data symlink of a ConfigMap volume, so a refill changes it
-    except OSError:
+    except FileNotFoundError:
         return None
+    except OSError as exc:
+        raise TrustBundleError(f"the trusted CA bundle {path} ({TRUSTED_CA_ENV}) cannot be read: {exc}") from exc
     return (path, st.st_size, st.st_mtime_ns) if st.st_size else None
 
 
-# One entry for each list of paths: the signature it was built from and the context.
-_cache: dict[tuple[str, ...], tuple[tuple, ssl.SSLContext]] = {}
+# One entry for each list of paths and server name: the signature it was built from and the context. A bundle that is not
+# there is cached too: the signature changes when it appears, so it is read at the next check either way.
+_cache: dict[tuple[tuple[str, ...], str | None], tuple[tuple, ssl.SSLContext]] = {}
 _cache_lock = threading.Lock()
 
 
@@ -94,16 +143,16 @@
     return (_system_locations(), tuple(s for s in (_signature(p) for p in bundle_paths(raw)) if s))
 
 
-def trusted_context(raw: str | None = None) -> ssl.SSLContext:
+def trusted_context(raw: str | None = None, server_name: str | None = None) -> ssl.SSLContext:
     """The system store, then each bundle of `raw` (default: CMAPI_TRUSTED_CA_FILE) that is there, in turn."""
-    paths = tuple(bundle_paths(raw))
+    entry = (tuple(bundle_paths(raw)), server_name)
     key = trusted_signature(raw)
     with _cache_lock:
-        cached = _cache.get(paths)
+        cached = _cache.get(entry)
     if cached is not None and cached[0] == key:
         return cached[1]
     (cafile, capath), bundles = key
-    ctx = _client_context()
+    ctx = _client_context(server_name)
     if cafile or capath:
         ctx.load_verify_locations(cafile=cafile, capath=capath)
     for path, _, _ in bundles:
@@ -112,7 +161,7 @@
         except (OSError, ValueError) as exc:
             raise TrustBundleError(f"the trusted CA bundle {path} ({TRUSTED_CA_ENV}) does not load: {exc}") from exc
     with _cache_lock:
-        _cache[paths] = (key, ctx)
+        _cache[entry] = (key, ctx)
     return ctx
 
 
@@ -132,8 +181,8 @@
         if self.source == "insecure":
             return False
         if self.source == "caData":
-            return ca_data_context(self.ca_data or "")
-        return trusted_context(self.bundles)
+            return ca_data_context(self.ca_data or "", self.server_name)
+        return trusted_context(self.bundles, self.server_name)
 
     def fingerprint(self) -> str:
         """Changes when anything the client verifies with changes (G6): the mode, the caData, the server name, the bundles."""
diff -ruN a/cmapi/src/cmapi/core/registry.py b/cmapi/src/cmapi/core/registry.py
--- a/cmapi/src/cmapi/core/registry.py	2026-11-18 18:32:32
+++ b/cmapi/src/cmapi/core/registry.py	2026-11-18 19:03:23
@@ -24,6 +24,7 @@
 
 import base64
 import binascii
+import hashlib
 import re
 import ssl
 import threading
@@ -42,7 +43,7 @@
 from cmapi.core.clients.nodes import NodeCache
 from cmapi.core.clients.policyreports import ReportCache
 from cmapi.core.clients.redact import redact, secret_forms
-from cmapi.core.clients.trust import Trust, file_context, trusted_context, valid_server_name
+from cmapi.core.clients.trust import Trust, file_context, require_https, trusted_context, valid_server_name
 from cmapi.core.errors import Problem
 from cmapi.core.observability import CLUSTER_STATUS, CLUSTER_TLS_INSECURE, log
 from cmapi.core.tiers import qty
@@ -180,6 +181,7 @@
     """Lists Secrets in the hub's cmapi-imports namespace with the pod's own ServiceAccount."""
 
     def __init__(self, api_url: str, token_file: Path, ca_file: Path, namespace: str):
+        require_https(api_url, "CMAPI_KUBE_API_URL")       # before the token is read: never sent in clear text
         self.namespace = namespace
         token = token_file.read_text().strip()
         self._forms = secret_forms(token)
@@ -302,11 +304,15 @@
                             f"instance.clusterTLS.environments.{where}.insecureSkipTLSVerify is false")
         if findings:
             return self._set(st, "invalid-secret", findings, None, secret)
+        # The root dot of a fully qualified name names the same host; OpenSSL matches the name as written, so it is dropped.
+        server_name = server_name.removesuffix(".") if server_name else None
         trust = (Trust("insecure", server_name=server_name) if insecure
                  else Trust("caData", ca_data=ca_data, server_name=server_name) if ca_data
                  else Trust("trusted", server_name=server_name, bundles=self.trusted_ca_file))
         try:
-            fp = f"{api_url}|{d['token'][-12:]}|{trust.fingerprint()}"
+            # The whole token, as a SHA-256: a rotated token that ends in the same characters still gives the caches the new
+            # client. The digest stays in memory, compared and never shown.
+            fp = f"{api_url}|{hashlib.sha256(d['token'].encode()).hexdigest()}|{trust.fingerprint()}"
             # The client builds the SSL context: a caData of valid base64 that is no certificate fails now, not at a call (#419),
             # and so does a bundle of CMAPI_TRUSTED_CA_FILE that does not load (TrustBundleError, which names it).
             client = self.client_factory(cluster_id, api_url, d["token"], trust, insecure=insecure)
diff -ruN a/cmapi/src/cmapi/jobs/watch_sync.py b/cmapi/src/cmapi/jobs/watch_sync.py
--- a/cmapi/src/cmapi/jobs/watch_sync.py	2026-11-18 18:32:32
+++ b/cmapi/src/cmapi/jobs/watch_sync.py	2026-11-18 19:03:23
@@ -26,6 +26,7 @@
     from pathlib import Path
 
     from cmapi.core.clients.kube import KubeClient
+    from cmapi.core.clients.trust import require_https
 
     if ctx.deliverer_factory is not None:
         return ctx.deliverer_factory(cluster_id)
@@ -33,10 +34,12 @@
     secret_dir = Path(f"/etc/cmapi/deliverer/{cluster_id}")
     if (secret_dir / "token").exists():
         api_url = (secret_dir / "apiUrl").read_text().strip()
+        require_https(api_url, str(secret_dir / "apiUrl"))
         ca = secret_dir / "ca.crt"
         return KubeClient(cluster_id, api_url, (secret_dir / "token").read_text().strip(),
                           str(ca) if ca.exists() else None)
     if s.kube_token_file.exists():
+        require_https(s.kube_api_url, "CMAPI_KUBE_API_URL")
         return KubeClient(cluster_id, s.kube_api_url, s.kube_token_file.read_text().strip(),
                           str(s.kube_ca_file) if s.kube_ca_file.exists() else None)
     raise RuntimeError(f"no deliverer credential for {cluster_id}")
diff -ruN a/cmapi/tests/service/test_cluster_token_client_420.py b/cmapi/tests/service/test_cluster_token_client_420.py
--- a/cmapi/tests/service/test_cluster_token_client_420.py	2026-11-18 18:32:32
+++ b/cmapi/tests/service/test_cluster_token_client_420.py	2026-11-18 19:05:28
@@ -126,7 +126,7 @@
     """The hub's own ServiceAccount token, in HubImportSource: its error is what `imports_list_failed` logs."""
     token = "SeCrEt-hub-token\nwith-newline-0123456789"
     (tmp_path / "token").write_text(token)
-    source = HubImportSource("http://127.0.0.1:9", tmp_path / "token", tmp_path / "no-ca.crt", "cmapi-imports")
+    source = HubImportSource("https://127.0.0.1:9", tmp_path / "token", tmp_path / "no-ca.crt", "cmapi-imports")
 
     def refuse(request: httpx.Request) -> httpx.Response:
         raise httpx.LocalProtocolError(f"Illegal header value {request.headers['authorization'].encode()!r}")
diff -ruN a/cmapi/tests/service/test_cluster_trust_review_435.py b/cmapi/tests/service/test_cluster_trust_review_435.py
--- a/cmapi/tests/service/test_cluster_trust_review_435.py	1969-12-31 18:00:00
+++ b/cmapi/tests/service/test_cluster_trust_review_435.py	2026-11-18 19:05:52
@@ -0,0 +1,383 @@
+"""The review of #435 (cluster TLS trust, #434): reviewer 1's findings F1 to F3 and reviewer 2's N1 to N3, each a test that fails
+on the pull request's head and passes with the fix, and the guards that keep two rejected fixes (F4, F5) from coming back.
+
+    F1  the hub reader and the deliverer refuse an http API URL before they hold the token
+    F2  a rotated token that ends in the same 12 characters gives the caches the new client
+    F3  a bundle that cannot be read (not one that is missing) stops the trusted clusters with a finding naming it
+    N1  tlsServerName holds through an HTTP proxy's CONNECT tunnel, where httpcore ignores the request's sni_hostname
+    N2  a caData or a bundle that holds an intermediate CA without its root verifies, as a client-go CertPool does
+    N3  a tlsServerName with a root dot is the same host, not a name no certificate matches
+
+Real TLS servers on 127.0.0.1 and a CONNECT proxy on 127.0.0.1; no database:
+
+    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_cluster_trust_review_435.py -q -W ignore
+"""
+from __future__ import annotations
+
+import datetime as dt
+import errno
+import os
+import socket
+import ssl
+import threading
+from concurrent.futures import ThreadPoolExecutor
+from pathlib import Path
+from types import SimpleNamespace
+
+import httpx
+import pytest
+from cryptography import x509
+from cryptography.hazmat.primitives import hashes, serialization
+from cryptography.hazmat.primitives.asymmetric import ec
+from test_cluster_trust_434 import (CA, LOCAL, NAMED_ONLY, TOKEN, Recorder, Server, Source, check, registry, secret, servers,
+                                    system_store)
+
+from cmapi.core.clients import trust as t
+from cmapi.core.clients.kube import KubeClient
+from cmapi.core.registry import HubImportSource
+
+__all__ = ["servers", "system_store"]                   # fixtures of test_cluster_trust_434, used here by name
+
+
+# --------------------------------------------------------------------------- helpers
+
+
+class ConnectProxy:
+    """An HTTP proxy that only tunnels (CONNECT), as a corporate egress proxy does for https. `tunnels` lists each target."""
+
+    def __init__(self):
+        self.listener = socket.create_server(("127.0.0.1", 0))
+        self.url = f"http://127.0.0.1:{self.listener.getsockname()[1]}"
+        self.tunnels: list[str] = []
+        threading.Thread(target=self._accept, daemon=True).start()
+
+    def _accept(self):
+        while True:
+            try:
+                conn, _ = self.listener.accept()
+            except OSError:
+                return
+            threading.Thread(target=self._tunnel, args=(conn,), daemon=True).start()
+
+    def _tunnel(self, conn: socket.socket):
+        head = b""
+        while b"\r\n\r\n" not in head:
+            chunk = conn.recv(4096)
+            if not chunk:
+                conn.close()
+                return
+            head += chunk
+        target = head.split(b" ", 2)[1].decode()
+        self.tunnels.append(target)
+        host, port = target.rsplit(":", 1)
+        upstream = socket.create_connection((host, int(port)))
+        conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
+
+        def pump(src: socket.socket, dst: socket.socket):
+            try:
+                while data := src.recv(65536):
+                    dst.sendall(data)
+            except OSError:
+                pass
+            finally:
+                for s in (src, dst):
+                    try:
+                        s.shutdown(socket.SHUT_RDWR)
+                    except OSError:
+                        pass
+
+        threading.Thread(target=pump, args=(conn, upstream), daemon=True).start()
+        pump(upstream, conn)
+
+    def close(self):
+        self.listener.close()
+
+
+@pytest.fixture
+def proxy(monkeypatch):
+    """HTTPS_PROXY for every client built in the test, as an operator sets it on the pods behind an egress proxy."""
+    p = ConnectProxy()
+    for name in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
+        monkeypatch.delenv(name, raising=False)
+    monkeypatch.setenv("HTTPS_PROXY", p.url)
+    monkeypatch.setenv("https_proxy", p.url)
+    yield p
+    p.close()
+
+
+def _name(cn: str) -> x509.Name:
+    return x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, cn)])
+
+
+def _cert(subject: str, issuer: str, public_key, signer, ca: bool, sans: list[x509.GeneralName] | None = None) -> x509.Certificate:
+    now = dt.datetime.now(dt.timezone.utc)
+    b = (x509.CertificateBuilder().subject_name(_name(subject)).issuer_name(_name(issuer)).public_key(public_key)
+         .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
+         .not_valid_after(now + dt.timedelta(days=1))
+         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
+    if sans:
+        b = b.add_extension(x509.SubjectAlternativeName(sans), critical=False)
+    return b.sign(signer, hashes.SHA256())
+
+
+def _pem(cert: x509.Certificate) -> str:
+    return cert.public_bytes(serialization.Encoding.PEM).decode()
+
+
+def intermediate_chain(tmp: Path, sans: list[x509.GeneralName]) -> tuple[str, Server]:
+    """A root, an intermediate it signs, and a server the intermediate signs that sends leaf and intermediate, as an API server
+    behind a corporate PKI does. Returns the intermediate's PEM alone (no root) and the running server."""
+    root_key, inter_key, leaf_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
+    inter = _cert("intermediate", "root", inter_key.public_key(), root_key, True)
+    leaf = _cert("kube-apiserver", "intermediate", leaf_key.public_key(), inter_key, False, sans)
+    crt, key = tmp / "chain.crt", tmp / "leaf.key"
+    crt.write_text(_pem(leaf) + _pem(inter))
+    key.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
+                                           serialization.NoEncryption()))
+    return _pem(inter), Server(crt, key)
+
+
+# --------------------------------------------------------------------------- F1: no bearer token over http
+
+
+@pytest.mark.parametrize("kind", ["hub", "deliverer-setting", "deliverer-file"])
+def test_the_hub_reader_and_the_deliverer_refuse_an_http_api_url_before_holding_the_token(tmp_path, monkeypatch, kind):
+    """Before: an http CMAPI_KUBE_API_URL, or an http apiUrl in a deliverer Secret, built a client that sends the bearer token
+    in clear text. The managed imports refuse the same in the registry's parse ("apiUrl is not https")."""
+    from cmapi.jobs.watch_sync import _deliverer
+
+    token_file = tmp_path / "token"
+    token_file.write_text("auxiliary-sensitive-token")
+    built: list[dict] = []
+    monkeypatch.setattr(httpx, "Client", lambda **kw: built.append(kw) or SimpleNamespace())
+    settings = SimpleNamespace(kube_token_file=token_file, kube_ca_file=tmp_path / "no-ca.crt",
+                               kube_api_url="http://hub.example.test")
+    deliverer_dir = tmp_path / "deliverer" / "C1"
+    if kind == "deliverer-file":
+        deliverer_dir.mkdir(parents=True)
+        (deliverer_dir / "token").write_text("deliverer-sensitive-token")
+        (deliverer_dir / "apiUrl").write_text("http://spoke.example.test:6443\n")
+    if kind != "hub":
+        # `_deliverer` reads /etc/cmapi/deliverer/<cluster>; the test's directory stands in for it.
+        monkeypatch.setattr("pathlib.Path", lambda p: Path(str(p).replace("/etc/cmapi/deliverer", str(tmp_path / "deliverer"))))
+    with pytest.raises(ValueError) as caught:
+        if kind == "hub":
+            HubImportSource("http://hub.example.test", token_file, tmp_path / "no-ca.crt", "cmapi-imports")
+        else:
+            _deliverer(SimpleNamespace(deliverer_factory=None, settings=settings), "C1")
+    named = str(deliverer_dir / "apiUrl") if kind == "deliverer-file" else "CMAPI_KUBE_API_URL"
+    assert str(caught.value) == f"{named} must be an https URL with a host and no userinfo"
+    assert "hub.example.test" not in str(caught.value) and "spoke.example.test" not in str(caught.value)
+    assert built == []
+
+
+def test_the_in_cluster_hub_url_is_still_accepted(tmp_path):
+    """CRC's and every pod's hub URL, the setting's default: https://kubernetes.default.svc."""
+    (tmp_path / "token").write_text("hub-token-0123456789")
+    source = HubImportSource("https://kubernetes.default.svc", tmp_path / "token", tmp_path / "no-ca.crt", "cmapi-imports")
+    try:
+        assert str(source.client.base_url) == "https://kubernetes.default.svc"
+    finally:
+        source.client.close()
+
+
+# --------------------------------------------------------------------------- F2: the whole token in the fingerprint
+
+
+def test_a_rotated_token_with_the_same_last_12_characters_replaces_the_client_and_every_cache(tmp_path):
+    """Before: the fingerprint held token[-12:], so a rotated token ending the same kept the old client in the watch, node and
+    report caches while the check reported connected with the new one."""
+    ca = CA(tmp_path, "rotation")
+    source = Source(secret("C1", "https://example.test", caData=ca.pem))
+    source.secrets[0]["data"]["token"] = "old-prefix-123456789012"
+
+    class Cache:
+        def __init__(self, client):
+            self.client, self.stopped = client, False
+
+        def stop(self):
+            self.stopped = True
+
+    reg = registry(source, client_factory=Recorder, reports_factory=lambda st, client: Cache(client),
+                   nodes_factory=lambda st, client: Cache(client))
+    try:
+        reg.refresh()
+        st = reg.clusters["C1"]
+        old_client, old_cache, old_reports, old_nodes = st.client, st.cache, st.reports, st.nodes
+        source.secrets[0]["data"]["token"] = "new-prefix-123456789012"
+        reg.refresh()
+        assert st.status == "connected"
+        assert st.client is not old_client and st.cache is not old_cache
+        assert old_reports.stopped and old_nodes.stopped
+        assert st.cache.client is st.reports.client is st.nodes.client is st.client
+        assert all("123456789012" not in fp for fp in reg._fingerprints.values())
+    finally:
+        reg.stop()
+
+
+# --------------------------------------------------------------------------- F3: unreadable is not missing
+
+
+def test_a_bundle_that_cannot_be_read_stops_the_trusted_clusters_with_a_finding_naming_it(tmp_path, servers, system_store,
+                                                                                         monkeypatch):
+    """Before: any OSError of stat (EACCES on a directory the pod cannot enter) read as "not there", so the bundle silently left
+    the store. Now only a missing file is skipped; the trusted cluster is cert-verify-failed naming the file, and a caData
+    cluster is checked as before."""
+    system, _ = system_store
+    servers.append(trusted := system.server(tmp_path, LOCAL))
+    own = CA(tmp_path, "own")
+    servers.append(pinned := own.server(tmp_path, LOCAL))
+    blocked = str(tmp_path / "unreadable" / "ca-bundle.crt")
+    real_stat = os.stat
+
+    def stat(path, *args, **kw):
+        if str(path) == blocked:
+            raise PermissionError(errno.EACCES, "Permission denied", blocked)
+        return real_stat(path, *args, **kw)
+
+    monkeypatch.setattr(t.os, "stat", stat)
+    monkeypatch.setenv("CMAPI_TRUSTED_CA_FILE", blocked)
+    source = Source(secret("C1", trusted.url), secret("C2", pinned.url, caData=own.pem))
+    reg = registry(source)
+    reg.refresh()
+    assert reg.clusters["C1"].status == "cert-verify-failed"
+    assert blocked in reg.clusters["C1"].findings[0] and "Permission denied" in reg.clusters["C1"].findings[0]
+    assert (reg.clusters["C2"].status, reg.clusters["C2"].findings) == ("connected", [])
+
+
+# --------------------------------------------------------------------------- F4 rejected: the keyed cache stays
+
+
+def test_a_missing_bundle_keeps_one_shared_context(tmp_path, system_store):
+    """CRC mounts the operator's ConfigMap optional and absent. The signature already changes when it appears (the test
+    test_a_missing_injected_bundle_is_read_again_at_the_next_check), so the context with it missing is cached and shared:
+    not cached, every trusted cluster would build and hold its own copy of the system store at each check (review of #435)."""
+    present = CA(tmp_path, "present")
+    raw = f"{present.path}:{tmp_path / 'operator' / 'ca-bundle.crt'}"
+    assert t.trusted_context(raw) is t.trusted_context(raw)
+
+
+# --------------------------------------------------------------------------- N1: tlsServerName through an HTTP proxy
+
+
+@pytest.mark.parametrize("mode", ["caData", "trusted"])
+def test_tls_server_name_holds_through_an_http_proxy_tunnel(tmp_path, servers, system_store, proxy, mode):
+    """Before: httpcore's CONNECT tunnel starts TLS with the URL's host and ignores the request's sni_hostname, so behind
+    HTTPS_PROXY a cluster reached by 127.0.0.1 with tlsServerName api.example.test failed: IP address mismatch."""
+    system, _ = system_store
+    ca = system if mode == "trusted" else CA(tmp_path, "cluster")
+    servers.append(srv := ca.server(tmp_path, NAMED_ONLY))
+    extra = {"caData": ca.pem} if mode == "caData" else {}
+    st = check(Source(secret("C1", srv.url, tlsServerName="api.example.test", **extra)))
+    assert (st.status, st.findings) == ("connected", [])
+    assert proxy.tunnels and set(proxy.tunnels) == {srv.url.removeprefix("https://")}
+
+
+def test_tls_server_name_still_guards_the_anchors_through_the_proxy(tmp_path, servers, system_store, proxy):
+    """The name in the context never trusts more: the same server, caData of another CA, still fails behind the proxy."""
+    servers.append(srv := CA(tmp_path, "cluster").server(tmp_path, NAMED_ONLY))
+    st = check(Source(secret("C1", srv.url, tlsServerName="api.example.test", caData=CA(tmp_path, "other").pem)))
+    assert st.status == "cert-verify-failed"
+
+
+@pytest.mark.parametrize("through_proxy", [False, True], ids=["direct", "proxy"])
+def test_a_watch_stream_uses_tls_server_name(tmp_path, servers, system_store, request, through_proxy):
+    """The watch caches read with `stream`, not `request`: the name holds there too, directly and through the proxy."""
+    if through_proxy:
+        request.getfixturevalue("proxy")
+    ca = CA(tmp_path, "cluster")
+    servers.append(srv := ca.server(tmp_path, NAMED_ONLY))
+    client = KubeClient("C1", srv.url, TOKEN, t.Trust("caData", ca_data=ca.pem, server_name="api.example.test"))
+    try:
+        events = list(client.watch("Namespace", "1", timeout_seconds=1))
+    finally:
+        client.close()
+    assert events and events[0]["metadata"]["resourceVersion"] == "1"
+
+
+# --------------------------------------------------------------------------- N2: an intermediate CA is an anchor
+
+
+@pytest.mark.parametrize("mode", ["caData", "trusted"])
+def test_an_intermediate_ca_without_its_root_is_an_anchor(tmp_path, servers, system_store, monkeypatch, mode):
+    """Before: OpenSSL without VERIFY_X509_PARTIAL_CHAIN built the chain to a self-signed root, so a kubeconfig whose
+    certificate-authority-data is the issuing intermediate (which kubectl, client-go and Argo CD accept) was cert-verify-failed."""
+    inter, srv = intermediate_chain(tmp_path, LOCAL)
+    servers.append(srv)
+    if mode == "caData":
+        st = check(Source(secret("C1", srv.url, caData=inter)))
+    else:
+        (bundle := tmp_path / "operator.pem").write_text(inter)
+        monkeypatch.setenv("CMAPI_TRUSTED_CA_FILE", str(bundle))
+        st = check(Source(secret("C1", srv.url)))
+    assert (st.status, st.findings) == ("connected", [])
+
+
+def test_partial_chain_never_trusts_an_unrelated_ca(tmp_path, servers, system_store):
+    _, srv = intermediate_chain(tmp_path, LOCAL)
+    servers.append(srv)
+    st = check(Source(secret("C1", srv.url, caData=CA(tmp_path, "unrelated").pem)))
+    assert st.status == "cert-verify-failed"
+
+
+# --------------------------------------------------------------------------- N3: a root dot
+
+
+def test_a_tls_server_name_with_a_root_dot_names_the_same_host(tmp_path, servers, system_store):
+    """Before: tlsServerName "api.example.test." passed the parse and OpenSSL matched it as written, so no certificate for
+    api.example.test ever verified (cert-verify-failed). The fully qualified form is the same host."""
+    ca = CA(tmp_path, "cluster")
+    servers.append(srv := ca.server(tmp_path, NAMED_ONLY))
+    st = check(Source(secret("C1", srv.url, caData=ca.pem, tlsServerName="api.example.test.")))
+    assert (st.status, st.findings) == ("connected", [])
+    assert st.trust.server_name == "api.example.test"
+
+
+def test_a_tls_server_name_with_two_trailing_dots_is_refused(tmp_path):
+    st = check(Source(secret("C1", "https://127.0.0.1:9", tlsServerName="api.example.test..")))
+    assert st.status == "invalid-secret"
+    assert st.findings == ["tlsServerName is not a DNS name or an IP address"]
+
+
+# --------------------------------------------------------------------------- guards from reviewer 1, kept
+
+
+@pytest.mark.parametrize("data", [{"caData": "not base64!"}, {"caData": "aGVsbG8="}, {"insecure": "yes"},
+                                  {"tlsServerName": "https://bad"}, {"insecure": "true"}],
+                         ids=["caData-not-base64", "caData-no-certificate", "insecure-not-boolean", "bad-server-name",
+                              "insecure-not-allowed"])
+def test_a_refused_import_builds_no_http_client(data, monkeypatch):
+    """Every refusal of the parse and of the TLS mode ends before an HTTP client, so the token is never sent."""
+    def no_client(**kw):
+        raise AssertionError("an HTTP client was built")
+
+    monkeypatch.setattr(httpx, "Client", no_client)
+    st = check(Source(secret("C1", "https://example.test", **data)))
+    assert (st.status, st.client) == ("invalid-secret", None)
+
+
+def test_the_trusted_cache_is_safe_across_threads_and_follows_a_rotation(tmp_path, monkeypatch):
+    from cryptography.hazmat.primitives.serialization import Encoding
+
+    a, b, c = (CA(tmp_path, n) for n in ("a", "b", "c"))
+    monkeypatch.setattr(t, "_system_locations", lambda: (str(a.path), None))
+    raw = f"{b.path}:{c.path}"
+    with ThreadPoolExecutor(max_workers=8) as pool:
+        contexts = list(pool.map(lambda _: t.trusted_context(raw), range(32)))
+    expected = {ca.cert.public_bytes(Encoding.DER) for ca in (a, b, c)}
+    assert all(set(ctx.get_ca_certs(binary_form=True)) == expected for ctx in contexts)
+    old = t.trusted_context(raw)
+    c.path.write_text(a.pem + b.pem)
+    new = t.trusted_context(raw)
+    assert new is not old
+    assert set(new.get_ca_certs(binary_form=True)) == expected - {c.cert.public_bytes(Encoding.DER)}
+
+
+def test_the_verifying_contexts_check_the_chain_and_the_name_at_tls_1_2_or_later(tmp_path):
+    """The flags every verifying mode starts from (`_client_context`): the hub's and the deliverer's ca.crt too."""
+    ca = CA(tmp_path, "flags")
+    for ctx in (t.ca_data_context(ca.pem), t.file_context(str(ca.path)), t.trusted_context(str(ca.path)),
+                t.ca_data_context(ca.pem, "api.example.test")):
+        assert ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
+        assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
+        assert ctx.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
diff -ruN a/docs/02-technical-design-v2.md b/docs/02-technical-design-v2.md
--- a/docs/02-technical-design-v2.md	2026-11-18 18:32:32
+++ b/docs/02-technical-design-v2.md	2026-11-18 19:03:47
@@ -678,7 +678,7 @@
 | `tlsServerName` | kubeconfig `tls-server-name`, client-go `ServerName`, Argo CD `serverName` | The name sent in SNI and checked against the certificate, when the host of `apiUrl` is not a name the certificate holds (a cluster reached by an address or through a tunnel). A DNS name or an IP address. It never changes what is trusted (#434) |
 | `insecure` | client-go `Insecure`, Argo CD `insecure`, kubeconfig `insecure-skip-tls-verify` | `"true"`: no verification. Allowed per environment by configuration (see "TLS: one mode per cluster") |
 
-**Tokens are bounded and rotated by the writer.** The baseline issues TokenRequest tokens with a 7-day lifetime and rewrites the Secret at 80% of that, before expiry and never as a reaction to a failure. Built: cmapi lists the import Secrets at start and every 5 minutes (`relist_seconds=300`, `ClusterRegistry._loop`), builds a client at each check, and replaces the cluster's client and watch caches when the API URL, the last 12 characters of the token or the trust changes: the mode, the caData itself, `tlsServerName`, or a bundle of the trusted mode (`fp`, `_fingerprints` and `Trust.fingerprint`; before #434 only the presence of caData counted, so a rotated CA left the watch caches on the old one). A rotation takes effect within 5 minutes and without a restart. **Not built (#396):** the metric cmapi\_cluster\_token\_expiry\_seconds and its alert. cmapi reads the annotation `cmapi.net/token-expires-at` into `ClusterState.token_expires_at`, and nothing shows or alerts on it.
+**Tokens are bounded and rotated by the writer.** The baseline issues TokenRequest tokens with a 7-day lifetime and rewrites the Secret at 80% of that, before expiry and never as a reaction to a failure. Built: cmapi lists the import Secrets at start and every 5 minutes (`relist_seconds=300`, `ClusterRegistry._loop`), builds a client at each check, and replaces the cluster's client and watch caches when the API URL, the token (a SHA-256 of the whole token, held in memory only; before the review of #435 its last 12 characters, so a rotated token with the same ending kept the old client) or the trust changes: the mode, the caData itself, `tlsServerName`, or a bundle of the trusted mode (`fp`, `_fingerprints` and `Trust.fingerprint`; before #434 only the presence of caData counted, so a rotated CA left the watch caches on the old one). A rotation takes effect within 5 minutes and without a restart. **Not built (#396):** the metric cmapi\_cluster\_token\_expiry\_seconds and its alert. cmapi reads the annotation `cmapi.net/token-expires-at` into `ClusterState.token_expires_at`, and nothing shows or alerts on it.
 
 One writer per Secret is the rule: cmapi has get, list and watch on Secrets in cmapi-imports and nothing more on the hub. A cluster whose token has expired answers 401 to `GET /version`, so it shows `auth_failed` until the baseline writes a fresh one (there is no status `credential-expired`); cmapi has no way to log in itself.
 
@@ -746,10 +746,10 @@
 | Mode (`trust.source`) | When | Trusted | On a verification failure |
 | --- | --- | --- | --- |
 | `insecure` | `insecure: "true"`, and `instance.clusterTLS.environments.<env>.insecureSkipTLSVerify` is true for the cluster's environment | Nothing: no chain, no name, no expiry. `trust.downgrade` is true | Not applicable |
-| `caData` | The Secret carries caData | That CA alone. Never widened to the system store: client-go's rule (caData "will be the ONLY information used in the CertPool"), as Argo CD's | Replace caData in that cluster's import Secret |
+| `caData` | The Secret carries caData | That CA alone. Never widened to the system store: client-go's rule (caData "will be the ONLY information used in the CertPool"), as Argo CD's. Each certificate in it is an anchor, as in a CertPool: an intermediate CA without its root verifies (`VERIFY_X509_PARTIAL_CHAIN`, in every mode that verifies) | Replace caData in that cluster's import Secret |
 | `trusted` | Neither | The image's system store (OpenSSL's build-time cafile and capath, not `SSL_CERT_FILE`, which the pods point at Keycloak's CA), then each bundle of `CMAPI_TRUSTED_CA_FILE` in turn: the hub's injected bundle (an empty ConfigMap labelled `config.openshift.io/inject-trusted-cabundle`, filled by OpenShift with the RHCOS trust bundle merged with `proxy/cluster.spec.trustedCA`) and an operator's ConfigMap | Add the CA to the operator's ConfigMap, or to `proxy/cluster.spec.trustedCA` fleet-wide, or give the cluster caData |
 
-`tlsServerName`, in any mode, is the name sent in SNI and checked against the certificate instead of the host of `apiUrl` (RFC 9525: the reference identity comes from the client's configuration, never from the server). It never changes what is trusted. `CMAPI_CA_BUNDLE` is Keycloak's trust and is not a cluster's (the owner's decision D4, #434). The flag that trusts a cluster's certificate is `insecure`, skip verification, as in Kubernetes (D1): pinning on first contact and an operator-given root fingerprint were weighed and not chosen (analysis section 3). Any environment may allow it, prod included, by configuration; none does by default (D2).
+`tlsServerName`, in any mode, is the name sent in SNI and checked against the certificate instead of the host of `apiUrl` (RFC 9525: the reference identity comes from the client's configuration, never from the server). It never changes what is trusted. It is set on each request (httpcore's `sni_hostname`) and, in a mode that verifies, in the SSL context itself, so it also holds through an HTTP proxy (`HTTPS_PROXY`), whose tunnel ignores the request's name. One root dot (`api.example.com.`) is dropped before use. `CMAPI_CA_BUNDLE` is Keycloak's trust and is not a cluster's (the owner's decision D4, #434). The flag that trusts a cluster's certificate is `insecure`, skip verification, as in Kubernetes (D1): pinning on first contact and an operator-given root fingerprint were weighed and not chosen (analysis section 3). Any environment may allow it, prod included, by configuration; none does by default (D2).
 
 Refused, as `invalid-secret` before any client is built, so the token is never sent: caData together with insecure: "true" (finding `insecure with caData`; client-go refuses the same); `insecure` in an environment whose setting does not allow it (finding `insecure is not allowed for environment <env>: instance.clusterTLS.environments.<env>.insecureSkipTLSVerify is false`); an `insecure` other than `"true"` or `"false"` (finding `insecure is "true" or "false"`); a `tlsServerName` that is not a DNS name or an IP address (finding `tlsServerName is not a DNS name or an IP address`); a caData whose certificate blocks are not valid base64 (finding `invalid caData`; `_valid_ca_data` decodes each block and does not parse the certificate) or whose blocks are valid base64 and no certificate (finding `invalid caData: <the TLS error>`, when the client loads it, #419); an apiUrl that is not https; and a Secret with no apiUrl or no token (finding `missing field <name>`). The finding is a sentence, not a code. A certificate failure has the status `cert-verify-failed`, and the finding names the trust store: `; trust store: caData` or `; trust store: trusted (the system store and CMAPI_TRUSTED_CA_FILE)`. A bundle of `CMAPI_TRUSTED_CA_FILE` that is there and does not load is the same status, with a finding that names the file. One that is not there is skipped and read again at the next check, because OpenShift fills the injected ConfigMap after the pods start. caData is loaded in memory, never written to a file. Each change of a cluster's mode logs `cluster_tls_mode` once (a warning when insecure takes effect, and once when it is cleared), and `cmapi_cluster_tls_insecure{cluster_id}` is 1 while a cluster is read insecure. **Not built (#396):** the expiry of the server's certificate and of caData (the owner's decision D6), and the fix for each mode in the message.
 
diff -ruN a/docs/18-configuration.md b/docs/18-configuration.md
--- a/docs/18-configuration.md	2026-11-18 18:32:32
+++ b/docs/18-configuration.md	2026-11-18 19:03:51
@@ -785,7 +785,7 @@
 | `CMAPI_METADATA_KEYS` | `<config dir>/metadata-keys.yaml` | Another path for `metadata-keys.yaml` |
 | `CMAPI_POLICIES_DIR` | `/etc/cmapi/policies` | Hand-written Kyverno policies that run with the rendered ones |
 | `CMAPI_CA_BUNDLE` | None | A PEM bundle that cmapi trusts for Keycloak, and for Git unless `CMAPI_GIT_CA_BUNDLE` is set. Not a cluster's trust since #434 (the owner's decision D4): see `CMAPI_TRUSTED_CA_FILE` |
-| `CMAPI_TRUSTED_CA_FILE` | `""` | Colon-separated PEM bundles that a cluster with no caData is verified against, after the image's system store (see "Cluster trust"). A path that is not there is skipped and read again at the next check; a file that does not load makes that cluster `cert-verify-failed`, with a finding that names the file and ends `; trust store: trusted (the system store and CMAPI_TRUSTED_CA_FILE)`, and the other clusters are still checked (`core/clients/trust.py`, #434) |
+| `CMAPI_TRUSTED_CA_FILE` | `""` | Colon-separated PEM bundles that a cluster with no caData is verified against, after the image's system store (see "Cluster trust"). A path that is not there is skipped and read again at the next check; a file that does not load, or a path that cannot be read for another reason (a directory the process cannot enter), makes that cluster `cert-verify-failed`, with a finding that names the file and ends `; trust store: trusted (the system store and CMAPI_TRUSTED_CA_FILE)`, and the other clusters are still checked (`core/clients/trust.py`, #434) |
 | `CMAPI_DATABASE_URL` | `""` | `postgresql://user:password@host:5432/db`. A secret |
 | `CMAPI_DATABASE_POOL_SIZE` | `5` | The pool of connections of one process |
 | `CMAPI_OIDC_JWKS_URL` | `<issuer>/protocol/openid-connect/certs` | Where to read the signing keys |
diff -ruN a/docs/reviews/2026-11-18-issue-434/README.md b/docs/reviews/2026-11-18-issue-434/README.md
--- a/docs/reviews/2026-11-18-issue-434/README.md	2026-11-18 18:32:32
+++ b/docs/reviews/2026-11-18-issue-434/README.md	2026-11-18 19:03:47
@@ -25,9 +25,9 @@
 | G1 | `INSECURE_ALLOWED` removed; `ClusterTLSSettings` (`core/clustertls.py`) parses `instance.clusterTLS`, `load_instance` refuses an unknown key, an environment not served or a value that is not a boolean, and `build_context` hands the allowed environments to the registry |
 | G2, D4, D7 | The trusted mode: `trusted_context` (`core/clients/trust.py`) loads the image's system store by path, then each bundle of `CMAPI_TRUSTED_CA_FILE` in turn. A missing or empty bundle is skipped and the context is keyed by the size and time of every path, so a bundle that appears is read at the next check; one that does not load raises `TrustBundleError`, which names it |
 | G3 | `KubeClient` never passes `verify=True` or a path string: an `SSLContext` from the cluster's `Trust`, a file, or the trusted mode |
-| G4, D3 | `tlsServerName`: a request hook sets httpcore's `sni_hostname`, the TLS `server_hostname`, on every request and stream |
+| G4, D3 | `tlsServerName`: a request hook sets httpcore's `sni_hostname`, the TLS `server_hostname`, on every request and stream; a verifying mode's SSL context carries the name too, because httpcore's HTTP-proxy tunnel ignores the extension (review of #435) |
 | G5 | caData is loaded in memory (`cadata=`); no temporary files |
-| G6 | The fingerprint is `apiUrl|token[-12:]|Trust.fingerprint()`: the mode, a SHA-256 of caData, the server name, and the bundles' signature |
+| G6 | The fingerprint is `apiUrl|sha256(token)|Trust.fingerprint()`: the mode, a SHA-256 of caData, the server name, and the bundles' signature. The token was `token[-12:]` until the review of #435 |
 | G7, D1 | `ClusterState.trust` and `ClusterTrust` in the contract (additive: oasdiff `response-optional-property-added`); the metric and the log event |
 | G8 | Findings name `caData` or `trusted (the system store and CMAPI_TRUSTED_CA_FILE)` |
 | G9 | The deliverer client with no `ca.crt` gets the trusted mode through `KubeClient`, not certifi. It does not take the import's mode: its credentials are a separate Secret |
