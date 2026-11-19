# Adversarial review: cmapi PR #435

Verdict: request changes. Reviewed the supplied `head/` archive identified by the requester as 9cad597; the archive has no Git metadata, so that identity is supplied, not independently authenticated. No push, merge, cluster contact, permission changes, or edits to `head/` were performed. Fixes were exercised in `fixed/`. Paths below are relative to `head/` unless explicitly labelled as review artifacts.

The later owner decisions in `docs/reviews/2026-11-18-issue-434/README.md` govern: prod may allow insecure and expiry is outside this issue. Earlier conflicting recommendations in analysis.md are not treated as requirements. TokenSave context/status rejected this archive as uninitialized; its read tool also lacked a default graph. Source inspection was read-only; no index was created.

## Runs and reproduction

All pytest runs used the requested interpreter and options. No PostgreSQL tests were selected, skipped, or attempted. MockTransport, generated certificates, and SSL MemoryBIO were used for the new tests; they make no network connections.

```sh
# R1 — original head tests; also attempted once before saving this output
cd head/cmapi
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_cluster_trust_434.py tests/service/test_cluster_trust_chart_434.py -q -p no:cacheprovider --tb=short
# 13 failed, 31 passed; review-runs/baseline-head.txt
# Every failure: PermissionError [Errno 1] Operation not permitted at socket.bind.

# R2 — adversarial regressions against unchanged head
cd head/cmapi
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest ../../review-tests/test_adversarial_435.py -q -p no:cacheprovider
# 6 failed, 12 passed; review-runs/adversarial-head.txt

# R3 — same tests against patched isolated copy
cd fixed/cmapi
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest ../../review-tests/test_adversarial_435.py -q -p no:cacheprovider
# 18 passed; review-runs/adversarial-fixed.txt

# R4 — final tests at their patch destination, plus chart/manifests
cd fixed/cmapi
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_adversarial_435.py tests/service/test_cluster_trust_chart_434.py -q -p no:cacheprovider
# 27 passed; review-runs/final-fixed.txt

# R5 — additional existing regressions on patched copy
cd fixed/cmapi
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_cluster_trust_434.py tests/service/test_cluster_trust_chart_434.py tests/service/test_cluster_token_client_420.py -k 'not no_error_of_the_client and not finding_and_its_log and not transport_error_that_shows' -q -p no:cacheprovider --tb=short
# 13 failed (same socket.bind restriction), 37 passed, 37 deselected
# review-runs/regression-fixed.txt

# R6 — patch applicability, no modifications to head
cd head
patch -p1 --dry-run < ../codex-fixes.patch
# exit 0, all six files accepted
```

Complete captured outputs are in `review-runs/`. The full fixes and test code are in the single `-p1` patch, reproduced below. `review-tests/test_adversarial_435.py` is the identical external test file used for the before/after comparison; the patch installs it at `cmapi/tests/service/test_adversarial_435.py`.


The paired R2/R3 results for finding tests were:

```text
                                                      head       fixed
F1 auxiliary_clients...[hub]                           FAIL       PASS
F1 auxiliary_clients...[deliverer]                     FAIL       PASS
F2 token_rotation_same_suffix_replaces_all_caches       FAIL       PASS
F3 bundle_stat_failure_is_not_missing                  FAIL       PASS
F4 missing_bundle_context_is_not_cached                FAIL       PASS
F5 ca_data_reflected_by_api_is_redacted                 FAIL       PASS
Other adversarial checks                               12 PASS    12 PASS
Total                                                  6F/12P     18P
```

## Findings

### F1 — High: auxiliary bearer clients accept plaintext API URLs

Locations: `cmapi/src/cmapi/core/registry.py:182-189`; `cmapi/src/cmapi/jobs/watch_sync.py:33-41`; `cmapi/src/cmapi/core/clients/kube.py:84-98`.

Failure scenario: an operator configures CMAPI_KUBE_API_URL as HTTP, or a mounted deliverer apiUrl contains HTTP. Unlike the managed import check (`core/registry.py:281-282`), these paths create bearer clients without requiring HTTPS. An SSLContext does not add TLS to an HTTP URL. The hub reader or privileged deliverer token can therefore be transmitted in plaintext without an allowed insecure mode. This is a pre-existing auxiliary URL-validation gap, still present in the reviewed trust surface; it is not demonstrated as a new regression introduced by this PR. Exploitation requires configuration or deliverer-secret influence (or operator error); a normal managed import cannot trigger it.

Proof: R2 `test_auxiliary_clients_refuse_http_before_client_creation[hub]` and `[deliverer]` both fail because HTTP client construction proceeds; R3/R4 both pass after the fix. Mocked constructors record the bearer-client construction without issuing requests. Actual network interception is a failure scenario inferred from that construction, not an attempted attack.

Full fix: the patch adds `require_https` (checks scheme, host, absence of userinfo without echoing the URL) and calls it in HubImportSource and both built-in deliverer branches before constructing clients. Direct KubeClient remains a low-level API; its managed callers perform the gate. The injected deliverer_factory is trusted application/test code. The existing hub #420 test is changed to an HTTPS constructor URL; its MockTransport continues testing the same error redaction. All code and tests are reproduced in the patch appendix.

### F2 — Medium: same-suffix token rotation keeps old client and all caches

Location: `cmapi/src/cmapi/core/registry.py:309`, adoption comparison at `:325-340`.

Failure scenario: rotate a token while retaining its last 12 characters. The fresh token passes probes, but its client is closed at `:343-347`; the existing watch, node, and report caches keep the previous credential. The registry can report connected while ongoing reads use a revoked/expired credential, or continue using an old still-authorized identity. Arbitrary tokens are accepted, so this need not involve a cryptographic JWT suffix collision. This is an inherited fingerprint defect that the expanded rotation claim leaves unresolved.

Proof: R2 `test_token_rotation_same_suffix_replaces_all_caches` fails (`st.client is old[0]`); R3/R4 pass, checking all three caches and stop calls for node/report caches.

Full fix: hash the entire token with SHA-256 and put that digest in the fingerprint instead of `token[-12:]`. No raw credential is added to a log or metric. Complete production change and regression test are in the patch appendix.

### F3 — Medium: bundle inspection errors silently select a smaller trust store

Location: `cmapi/src/cmapi/core/clients/trust.py:73-78`, filtering at `:94`, loading at `:105-113`.

Failure scenario: a configured operator bundle's parent cannot be traversed (EACCES), or stat encounters EIO/ELOOP. `_signature` treats every OSError as absence; the bundle disappears from the context and fingerprint. A cluster signed by a remaining system/operator anchor can continue instead of receiving the required finding naming the failed file. This is silent narrowing, not a demonstrated fallback to insecure or widening of trust.

Proof: R2 `test_bundle_stat_failure_is_not_missing` injects EACCES for one path after a valid bundle and fails because no TrustBundleError is raised; R3/R4 pass. Separately R2 `test_bad_trusted_bundle_stops_cluster_and_names_path` passes for an existing malformed PEM: load errors already stop the cluster. Thus the defect is specifically the earlier inspection error path.

Full fix: skip only FileNotFoundError; wrap other stat errors in TrustBundleError with the path and CMAPI_TRUSTED_CA_FILE. Existing registry OSError handling stops caches and reports cert-verify-failed (`core/registry.py:313-316`, `:397-399`). Complete code and regression test are in the appendix.

### F4 — Low: missing-bundle contexts are cached despite the stated no-cache rule

Location: `cmapi/src/cmapi/core/clients/trust.py:94`, `:114-115`.

Failure scenario: an injected bundle is absent at startup. The resulting partial store is inserted into `_cache`. This contradicts the explicit missing-file/no-cache requirement. Impact is limited: every lookup recomputes signatures, so normal subsequent file appearance still invalidates this entry; this finding does NOT claim permanent stale trust or token exposure.

Proof: R2 `test_missing_bundle_context_is_not_cached` fails because `(raw,)` is present in `_cache`; R3/R4 pass.

Full fix: cache only when every configured bundle has a nonempty signature; otherwise remove any prior entry for the path list. The existing documented empty-file skip remains unchanged. Complete code and test are in the appendix.

### F5 — Low: reflected caData reaches error messages and potentially findings/logs

Locations: `cmapi/src/cmapi/core/clients/kube.py:85`, `:112-117`, `:246-248`; `cmapi/src/cmapi/core/registry.py:394-395`, `:408-409`; API view at `:107-110`.

Failure scenario: a cluster/proxy response includes the supplied public CA PEM. KubeClient redacts only the bearer token before truncating the response body. The PEM prefix survives in a KubeError; probe findings can then be logged and served by /clusters, whose second redaction pass also removes only token forms. A CA certificate is public material, so this is a violation of the explicit no-caData output contract rather than private-key disclosure. It does not demonstrate a #420 bearer-token regression.

Proof: R2 `test_ca_data_reflected_by_api_is_redacted` uses a 500 MockTransport response containing the PEM and fails with `500 on /version: -----BEGIN CERTIFICATE-----...`; R3/R4 pass. R2 `test_tls_error_token_redaction` passes on head for a TLS error containing the token.

Full fix: add `secret_forms(trust.ca_data)` to KubeClient's existing redaction forms and redact caData as well as token in the registry second pass. Redaction still occurs before KubeError truncation. Complete code and regression test are in the appendix. This covers full/escaped PEM reflection and the existing trailing-prefix rule; arbitrary substrings embedded in unrelated fields are not a general data-loss-prevention guarantee.

## Verdicts for C1–C8

Each verdict is limited to inspected production paths and the runs cited; passing examples are not a proof of all thread schedules or deployments.

| Claim | Verdict and evidence |
|---|---|
| C1 | **Refuted as universal; managed-reader gate confirmed.** Environment refusal precedes `client_factory` at `core/registry.py:298-312`; probes at `:319`, all watch/node/report cache construction at `:325-339`. Context passes parsed environments at `core/context.py:121-125`. R1 passes the forbidden-insecure no-constructor test and prod setting tests; R2's invalid-import matrix passes without any HTTP constructor. Hub/deliverer have no insecure option and use verifying contexts (`core/registry.py:186-189`, `jobs/watch_sync.py:37-41`), but accept HTTP: F1/R2. They have separate credentials, so they do not need the managed reader's insecure environment gate when HTTPS verification is used. |
| C2 | **Confirmed for context construction; socket verification limited.** `core/clients/trust.py:47-56` constructs an empty PROTOCOL_TLS_CLIENT context and loads cadata only. `core/clients/kube.py:90-98` hands that context to httpx. R2 `test_ca_data_only_and_default_path_ignore_env` checks exact anchor DER, CERT_REQUIRED and check_hostname; in-memory handshakes also exercise the context. Existing real-socket CA-isolation tests were blocked in R1. |
| C3 | **Refuted in inspection-error and missing-cache paths (F3/F4).** Build-time openssl_cafile/capath are chosen explicitly at `core/clients/trust.py:66-70`, loaded at `:105-108`; SSL_CERT_FILE/DIR are not selected. Bundles are loaded sequentially at `:109-113`, with no insecure catch fallback. R2 tests exact system location selection despite both env vars, malformed-file cluster refusal, three anchor sets across 32 calls on eight threads, and bundle replacement invalidation; those pass. Size and nanosecond mtime are in `:75-78` and `:94`. Lookup/publication are locked at `:101-102`, `:114-115`; construction can duplicate outside the lock. This bounded concurrency run found no corrupt context, not a proof of atomic filesystem snapshots. No guarantee for edits preserving both size and mtime is claimed. Missing stat errors and cached partial stores are the reproduced exceptions. Empty files are explicitly skipped by the owner design README and `trust.py:13`, not classified here as invalid PEM. |
| C4 | **Confirmed within tested scope.** `core/registry.py:293-295` validates server names through `core/clients/trust.py:37-44`; `core/clients/kube.py:96-107` sets only the request sni_hostname extension, leaving anchors unchanged. Contexts retain chain and hostname verification (`trust.py:47-56`); only explicitly allowed insecure disables both. R1 passes invalid-name refusals; R2 tests an IP override through the hook and an in-memory handshake: iPAddress SAN succeeds, a DNS SAN spelling the same IP fails. No end-to-end httpcore socket test could run. This is not a claim of complete RFC 9525 conformance (for example Python's default common-name policy is outside the narrow IP-SAN assertion). |
| C5 | **Refuted for token changes (F2).** apiUrl and Trust fingerprint are in `core/registry.py:309`; Trust hashes caData and includes mode/server name at `core/clients/trust.py:138-145`; comparison/adoption at `core/registry.py:325-340`. R1 passes all three existing trust-change rebuild cases; R2 passes API-URL rebuild and bundle-context rotation but fails same-suffix token rotation. New fingerprint fixes this in R3. |
| C6 | **Confirmed for specified refusal cases.** Parse refusals at `core/registry.py:284-304`, malformed PEM handling at `:313-315`; setting parsing at `core/clustertls.py:27-54`, load at `core/config.py:120-125`. R1 passes insecure-with-caData, four invalid boolean strings, denied-environment setting-name test and setting parser cases. R2 invalid-import matrix checks invalid base64, base64-but-not-certificate, nonboolean, invalid name and forbidden insecure without HTTP construction. YAML booleans deliberately normalize to true/false; string values are case-insensitive by current code. |
| C7 | **Refuted for caData reflection (F5); tested bearer redaction holds.** /clusters directly exposes only Trust.view metadata (`core/clients/trust.py:147-148`, `core/registry.py:105-110`), but findings can carry PEMs through the token-only redactor. R2 reproduces this. TLS token redaction test passes in R2; R5 passes the existing socket-free #420 redaction and hub-error cases after the test constructor uses HTTPS. Structured metrics use cluster_id/status, not token/caData (`core/registry.py:405`, `:416`), and mode logging uses mode/server name (`:429-430`). This assumes identifiers/server-name fields are used according to their contract; it does not promise redaction if an operator copies a credential into unrelated metadata. |
| C8 | **Confirmed for rendered chart/plain-manifest assertions.** Empty labelled map at `deploy/helm/cmapi/templates/trust.yaml:28-42`; optional read-only injection at `_helpers.tpl:112-115`, `:137-142`; operator map mounted by supplied name without templating at `:144-149`; joined env at `:84-100`; clusterTLS at `config.yaml:41`. Plain API mounts/env at `deploy/manifests/components/cmapi/20-api.yaml:123-124`, `:155-165`; worker at `30-worker.yaml:112-113`, `:135-136`, `:164-167`; empty CRC map at `deploy/manifests/environments/crc/35-trusted-ca.yaml:6-15`. Nine chart/manifests cases pass in R1/R4. Operator map is intentionally required in Helm and optional in plain manifests; the injected map is optional in both. CMAPI_TRUSTED_CA_FILE is emitted for both workloads when enabled, absent with both features disabled. Cluster construction uses settings.trusted_ca_file (`core/context.py:119-122`, `settings.py:23-27`), never ca_bundle; R2 checks trust contexts ignore SSL_CERT_FILE/DIR. The existing runtime CMAPI_CA_BUNDLE-isolation socket test was blocked, not passed. No live OpenShift injection or cluster operations were attempted. |

`deploy/kind-import/import-secret.py:10-11`, `:30-31` carries caData and optional tlsServerName into the import without mixing anchors; its stderr at `:33` prints expiry metadata, not the credential. This was inspected, not executed against a cluster; no finding is asserted from that inspection alone.

## Full fix and regression-test code

The following is the complete contents of `codex-fixes.patch` (paths relative to `head/`, apply with `patch -p1`). R6 verified applicability. R2/R3 show the required head-fail/fix-pass pairing for every finding; F1 has two parameter cases, giving six failing cases for five findings.

```diff
--- a/cmapi/src/cmapi/core/clients/trust.py
+++ b/cmapi/src/cmapi/core/clients/trust.py
@@ -22,6 +22,7 @@
 import re
 import ssl
 import threading
+from urllib.parse import urlsplit
 from dataclasses import dataclass
 
 TRUSTED_CA_ENV = "CMAPI_TRUSTED_CA_FILE"
@@ -32,6 +33,17 @@
 class TrustBundleError(OSError):
     """A bundle of CMAPI_TRUSTED_CA_FILE that is there and does not load. An OSError, as ssl.SSLError and a missing file are, so
     the registry's net for a client that cannot be made catches it; the message names the file and the variable."""
+
+
+def require_https(api_url: str) -> None:
+    """Refuse plaintext auxiliary API URLs before constructing a bearer client."""
+    try:
+        parsed = urlsplit(api_url)
+        valid = parsed.scheme == "https" and bool(parsed.hostname) and not (parsed.username or parsed.password)
+    except ValueError:
+        valid = False
+    if not valid:
+        raise ValueError("Kubernetes apiUrl must be https with a host and no userinfo")
 
 
 def valid_server_name(name: str) -> bool:
@@ -73,8 +85,10 @@
 def _signature(path: str) -> tuple[str, int, int] | None:
     try:
         st = os.stat(path)                  # follows the ..data symlink of a ConfigMap volume, so a refill changes it
-    except OSError:
+    except FileNotFoundError:
         return None
+    except OSError as exc:
+        raise TrustBundleError(f"the trusted CA bundle {path} ({TRUSTED_CA_ENV}) cannot be inspected: {exc}") from exc
     return (path, st.st_size, st.st_mtime_ns) if st.st_size else None
 
 
@@ -112,7 +126,10 @@
         except (OSError, ValueError) as exc:
             raise TrustBundleError(f"the trusted CA bundle {path} ({TRUSTED_CA_ENV}) does not load: {exc}") from exc
     with _cache_lock:
-        _cache[paths] = (key, ctx)
+        if len(bundles) == len(paths):
+            _cache[paths] = (key, ctx)
+        else:
+            _cache.pop(paths, None)
     return ctx
 
 
--- a/cmapi/src/cmapi/core/clients/kube.py
+++ b/cmapi/src/cmapi/core/clients/kube.py
@@ -83,6 +83,8 @@
         certificate raises ssl.SSLError from the constructor (#419)."""
         self.cluster_id, self.api_url = cluster_id, api_url.rstrip("/")
         self._forms = secret_forms(token)            # what `redact` removes from every error this client builds (#420)
+        if isinstance(trust, Trust):
+            self._forms += secret_forms(trust.ca_data)
         server_name = trust.server_name if isinstance(trust, Trust) else None
         verify: ssl.SSLContext | bool
         if insecure or (isinstance(trust, Trust) and trust.source == "insecure"):
--- a/cmapi/src/cmapi/core/registry.py
+++ b/cmapi/src/cmapi/core/registry.py
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
+from cmapi.core.clients.trust import Trust, file_context, trusted_context, valid_server_name, require_https
 from cmapi.core.errors import Problem
 from cmapi.core.observability import CLUSTER_STATUS, CLUSTER_TLS_INSECURE, log
 from cmapi.core.tiers import qty
@@ -180,6 +181,7 @@
     """Lists Secrets in the hub's cmapi-imports namespace with the pod's own ServiceAccount."""
 
     def __init__(self, api_url: str, token_file: Path, ca_file: Path, namespace: str):
+        require_https(api_url)
         self.namespace = namespace
         token = token_file.read_text().strip()
         self._forms = secret_forms(token)
@@ -306,7 +308,8 @@
                  else Trust("caData", ca_data=ca_data, server_name=server_name) if ca_data
                  else Trust("trusted", server_name=server_name, bundles=self.trusted_ca_file))
         try:
-            fp = f"{api_url}|{d['token'][-12:]}|{trust.fingerprint()}"
+            token_digest = hashlib.sha256(d["token"].encode()).hexdigest()
+            fp = f"{api_url}|{token_digest}|{trust.fingerprint()}"
             # The client builds the SSL context: a caData of valid base64 that is no certificate fails now, not at a call (#419),
             # and so does a bundle of CMAPI_TRUSTED_CA_FILE that does not load (TrustBundleError, which names it).
             client = self.client_factory(cluster_id, api_url, d["token"], trust, insecure=insecure)
@@ -391,7 +394,8 @@
         """Records one check's outcome. `trust` is the mode the check used, None when it ended before one was chosen."""
         # KubeClient redacts its token before any cut (#420). This second pass covers every other way a finding is made:
         # GET /api/v1/clusters serves findings to each clusters:read caller, and the log below writes them.
-        forms = secret_forms((secret.get("data") or {}).get("token"))
+        data = secret.get("data") or {}
+        forms = secret_forms(data.get("token")) + secret_forms(data.get("caData"))
         findings = [redact(f, forms) for f in findings]
         with self._lock:
             if status != "connected" and st.cache is not None:
--- a/cmapi/src/cmapi/jobs/watch_sync.py
+++ b/cmapi/src/cmapi/jobs/watch_sync.py
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
+        require_https(api_url)
         ca = secret_dir / "ca.crt"
         return KubeClient(cluster_id, api_url, (secret_dir / "token").read_text().strip(),
                           str(ca) if ca.exists() else None)
     if s.kube_token_file.exists():
+        require_https(s.kube_api_url)
         return KubeClient(cluster_id, s.kube_api_url, s.kube_token_file.read_text().strip(),
                           str(s.kube_ca_file) if s.kube_ca_file.exists() else None)
     raise RuntimeError(f"no deliverer credential for {cluster_id}")
--- a/cmapi/tests/service/test_cluster_token_client_420.py
+++ b/cmapi/tests/service/test_cluster_token_client_420.py
@@ -126,7 +126,7 @@
     """The hub's own ServiceAccount token, in HubImportSource: its error is what `imports_list_failed` logs."""
     token = "SeCrEt-hub-token\nwith-newline-0123456789"
     (tmp_path / "token").write_text(token)
-    source = HubImportSource("http://127.0.0.1:9", tmp_path / "token", tmp_path / "no-ca.crt", "cmapi-imports")
+    source = HubImportSource("https://127.0.0.1:9", tmp_path / "token", tmp_path / "no-ca.crt", "cmapi-imports")
 
     def refuse(request: httpx.Request) -> httpx.Response:
         raise httpx.LocalProtocolError(f"Illegal header value {request.headers['authorization'].encode()!r}")
--- /dev/null
+++ b/cmapi/tests/service/test_adversarial_435.py
@@ -0,0 +1,233 @@
+import errno
+import ssl
+from pathlib import Path
+from types import SimpleNamespace
+
+import httpx
+import pytest
+from test_cluster_trust_434 import CA, Recorder, Source, registry, secret
+from cmapi.core.clients import trust as t
+from cmapi.core.clients.kube import KubeClient, ClusterUnreachable, KubeError
+from cmapi.core.registry import HubImportSource
+
+
+def test_token_rotation_same_suffix_replaces_all_caches(tmp_path):
+    ca = CA(tmp_path, 'rotation')
+    source = Source(secret('C1', 'https://example.test', caData=ca.pem, token='old-prefix-123456789012'))
+    made = []
+    class Cache:
+        def __init__(self, client):
+            self.client, self.stopped = client, False
+            made.append(self)
+        def stop(self): self.stopped = True
+    reg = registry(source, client_factory=Recorder,
+                   reports_factory=lambda st, client: Cache(client),
+                   nodes_factory=lambda st, client: Cache(client))
+    try:
+        reg.refresh()
+        st = reg.clusters['C1']
+        old = (st.client, st.cache, st.reports, st.nodes)
+        source.secrets[0]['data']['token'] = 'new-prefix-123456789012'
+        reg.refresh()
+        assert st.status == 'connected'
+        assert st.client is not old[0]
+        assert st.cache is not old[1]
+        assert st.reports is not old[2] and old[2].stopped
+        assert st.nodes is not old[3] and old[3].stopped
+        assert st.cache.client is st.reports.client is st.nodes.client is st.client
+    finally: reg.stop()
+
+
+def test_bundle_stat_failure_is_not_missing(tmp_path, monkeypatch):
+    good = CA(tmp_path, 'good')
+    blocked = str(tmp_path / 'operator.pem')
+    real_stat = t.os.stat
+    def stat(path, *a, **kw):
+        if str(path) == blocked:
+            raise PermissionError(errno.EACCES, 'denied', blocked)
+        return real_stat(path, *a, **kw)
+    monkeypatch.setattr(t.os, 'stat', stat)
+    with pytest.raises(t.TrustBundleError, match='operator.pem'):
+        t.trusted_context(f'{good.path}:{blocked}')
+
+
+def test_missing_bundle_context_is_not_cached(tmp_path):
+    raw = str(tmp_path / 'not-yet-mounted')
+    t.trusted_context(raw)
+    assert (raw,) not in t._cache
+
+
+@pytest.mark.parametrize('kind', ['hub', 'deliverer'])
+def test_auxiliary_clients_refuse_http_before_client_creation(tmp_path, monkeypatch, kind):
+    import cmapi.core.clients.kube as km
+    import cmapi.core.registry as rm
+    from cmapi.jobs.watch_sync import _deliverer
+    token_file = tmp_path / 'token'
+    token_file.write_text('auxiliary-sensitive-token')
+    ca = CA(tmp_path, 'aux')
+    calls = []
+    def client(**kw):
+        calls.append(kw)
+        return SimpleNamespace()
+    monkeypatch.setattr(httpx, 'Client', client)
+    with pytest.raises(ValueError, match='https'):
+        if kind == 'hub':
+            HubImportSource('http://example.test', token_file, ca.path, 'imports')
+        else:
+            settings = SimpleNamespace(kube_token_file=token_file, kube_ca_file=ca.path,
+                                       kube_api_url='http://example.test')
+            _deliverer(SimpleNamespace(deliverer_factory=None, settings=settings), 'C1')
+    assert calls == []
+
+
+def test_ca_data_reflected_by_api_is_redacted(tmp_path):
+    ca = CA(tmp_path, 'redaction')
+    client = KubeClient('C1', 'https://example.test', 'sensitive-bearer-token', t.Trust('caData', ca_data=ca.pem))
+    client._client.close()
+    client._client = httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(
+        lambda request: httpx.Response(500, text=ca.pem)))
+    try:
+        with pytest.raises(KubeError) as exc:
+            client.version()
+        assert '-----BEGIN CERTIFICATE-----' not in str(exc.value)
+        assert ca.pem.splitlines()[1] not in str(exc.value)
+    finally: client.close()
+
+
+def test_ca_data_only_and_default_path_ignore_env(tmp_path, monkeypatch):
+    own, extra = CA(tmp_path, 'own'), CA(tmp_path, 'extra')
+    monkeypatch.setenv('SSL_CERT_FILE', str(extra.path))
+    monkeypatch.setenv('SSL_CERT_DIR', str(tmp_path))
+    ctx = t.ca_data_context(own.pem)
+    assert ctx.get_ca_certs(binary_form=True) == [own.cert.public_bytes(__import__('cryptography').hazmat.primitives.serialization.Encoding.DER)]
+    assert ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
+    paths = ssl.get_default_verify_paths()
+    assert t._system_locations() == (
+        paths.openssl_cafile if Path(paths.openssl_cafile).is_file() else None,
+        paths.openssl_capath if Path(paths.openssl_capath).is_dir() else None)
+
+
+def test_tls_error_token_redaction(tmp_path):
+    token = 'sensitive-bearer-token'
+    ca = CA(tmp_path, 'tls-error')
+    client = KubeClient('C1', 'https://example.test', token, t.Trust('caData', ca_data=ca.pem))
+    client._client.close()
+    def fail(request): raise httpx.ConnectError('CERTIFICATE_VERIFY_FAILED ' + token)
+    client._client = httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(fail))
+    try:
+        with pytest.raises(ClusterUnreachable) as exc: client.version()
+        assert token not in str(exc.value)
+        assert 'CERTIFICATE_VERIFY_FAILED' in str(exc.value)
+    finally: client.close()
+
+
+def handshake(client_context, server_context, name):
+    ci, co, si, so = [ssl.MemoryBIO() for _ in range(4)]
+    client = client_context.wrap_bio(ci, co, server_side=False, server_hostname=name)
+    server = server_context.wrap_bio(si, so, server_side=True)
+    done = [False, False]
+    for _ in range(20):
+        for i, peer in enumerate((client, server)):
+            if not done[i]:
+                try:
+                    peer.do_handshake()
+                    done[i] = True
+                except ssl.SSLWantReadError: pass
+        si.write(co.read())
+        ci.write(so.read())
+        if all(done): return
+    raise AssertionError('handshake did not finish')
+
+
+def server_context(tmp_path, ca, san):
+    import datetime as dt
+    from cryptography import x509
+    from cryptography.hazmat.primitives import hashes, serialization
+    from cryptography.hazmat.primitives.asymmetric import ec
+    key = ec.generate_private_key(ec.SECP256R1())
+    now = dt.datetime.now(dt.timezone.utc)
+    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "server")])).issuer_name(ca.cert.subject)
+            .public_key(key.public_key()).serial_number(x509.random_serial_number())
+            .not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(days=1))
+            .add_extension(x509.SubjectAlternativeName([san]), critical=False).sign(ca.key, hashes.SHA256()))
+    crt, pem = tmp_path / 'server.crt', tmp_path / 'server.key'
+    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
+    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
+                                     serialization.NoEncryption()))
+    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
+    ctx.load_cert_chain(crt, pem)
+    return ctx
+
+
+@pytest.mark.parametrize('ip_san', [True, False])
+def test_ip_override_requires_ip_san(tmp_path, ip_san):
+    import ipaddress
+    from cryptography import x509
+    ca = CA(tmp_path, 'ip-san')
+    san = x509.IPAddress(ipaddress.ip_address('192.0.2.1')) if ip_san else x509.DNSName('192.0.2.1')
+    server = server_context(tmp_path, ca, san)
+    client = KubeClient('C1', 'https://example.test', 'token-for-ip-test',
+                        t.Trust('caData', ca_data=ca.pem, server_name='192.0.2.1'))
+    request = httpx.Request('GET', 'https://example.test/version')
+    client._name_server('192.0.2.1')(request)
+    try:
+        assert request.extensions['sni_hostname'] == '192.0.2.1'
+        ctx = t.ca_data_context(ca.pem)
+        if ip_san:
+            handshake(ctx, server, request.extensions['sni_hostname'])
+        else:
+            with pytest.raises(ssl.SSLCertVerificationError):
+                handshake(ctx, server, request.extensions['sni_hostname'])
+    finally: client.close()
+
+
+def test_trusted_bundles_rotation_and_threaded_cache(tmp_path, monkeypatch):
+    from concurrent.futures import ThreadPoolExecutor
+    from cryptography.hazmat.primitives.serialization import Encoding
+    a, b, c = [CA(tmp_path, n) for n in ('a', 'b', 'c')]
+    monkeypatch.setattr(t, '_system_locations', lambda: (str(a.path), None))
+    raw = f'{b.path}:{c.path}'
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
+@pytest.mark.parametrize('data', [{'caData': 'not base64!'}, {'caData': 'aGVsbG8='}, {'insecure': 'yes'},
+                                  {'tlsServerName': 'https://bad'}, {'insecure': 'true'}])
+def test_invalid_import_stops_before_network(data, monkeypatch):
+    def no_client(**kw): raise AssertionError('HTTP client must not be built')
+    monkeypatch.setattr(httpx, 'Client', no_client)
+    reg = registry(Source(secret('C1', 'https://example.test', **data)))
+    reg.refresh()
+    assert reg.clusters['C1'].status == 'invalid-secret'
+    assert reg.clusters['C1'].client is None
+
+
+def test_bad_trusted_bundle_stops_cluster_and_names_path(tmp_path, monkeypatch):
+    bad = tmp_path / 'broken.pem'
+    bad.write_text('not a PEM')
+    def no_client(**kw): raise AssertionError('HTTP client must not be built')
+    monkeypatch.setattr(httpx, 'Client', no_client)
+    reg = registry(Source(secret('C1', 'https://example.test')), trusted_ca_file=str(bad))
+    reg.refresh()
+    st = reg.clusters['C1']
+    assert st.status == 'cert-verify-failed' and st.client is None
+    assert str(bad) in st.findings[0]
+
+
+def test_api_url_rotation_rebuilds_watch_cache():
+    source = Source(secret('C1', 'https://first.example.test'))
+    reg = registry(source, client_factory=Recorder)
+    try:
+        reg.refresh()
+        before = reg.clusters['C1'].cache
+        source.secrets[0]['data']['apiUrl'] = 'https://second.example.test'
+        reg.refresh()
+        assert reg.clusters['C1'].cache is not before
+    finally: reg.stop()

```
