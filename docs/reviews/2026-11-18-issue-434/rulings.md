# #435 review: the coordinator's rulings

- **Reviewer 1:** Codex, another model family, on head 9cad597. Report: `review-1-codex.md`.
- **Reviewer 2:** OB3 (Opus 5.5). It checked each of Codex's fixes against the design and the code, ran the 13 TLS tests
  that Codex's sandbox could not run, and reported what Codex missed. Report: `review-2-ob3.md`.
- **Applied:** OB3's patch, unchanged. It supersedes Codex's patch.

## Coordinator's check (2026-11-18)

OB3's tests on the head code, then on the head with OB3's patch, through `suite.sh`. The files were the two review
tests (`test_cluster_trust_review_435.py`, the updated `test_cluster_token_client_420.py`), then `test_cluster_trust_434.py`,
`test_cluster_trust_chart_434.py` and `test_registry_survives_419.py`.

| Code | Result |
|---|---|
| Head | 13 failed (the finding tests), 122 passed |
| Head with OB3's patch | 135 passed |

## Rulings

| Finding | By | Ruling |
|---|---|---|
| F1: the hub reader and the deliverer send a bearer token over `http://` | Codex (High); OB3: Medium, the gap predates #434 | **Accepted.** `require_https` names `CMAPI_KUBE_API_URL` or the deliverer's apiUrl file without echoing the URL. `https://kubernetes.default.svc` is still accepted |
| F2: the fingerprint holds only `token[-12:]`, so a rotated token with the same ending keeps the old client and caches | Codex | **Accepted.** It now holds the SHA-256 of the whole token, in memory only. docs/02 is corrected |
| F3: a bundle that cannot be read (EACCES, EIO) was skipped as if missing, so the trust store silently shrank | Codex | **Accepted.** The cluster is now `cert-verify-failed`, with a finding that names the file |
| F4: a context built while a bundle is missing is still cached | Codex | **Rejected, on OB3's evidence.** The protected property, picking up a bundle that appears later, holds on the head: the cache key includes each file's signature, and the existing test passes. Codex's fix stops caching whenever a listed path is missing, which is the normal state on CRC and kind. Measured: 0.06 ms to 40.4 ms per call, and +124 MiB RSS for 200 contexts. OB3's guard test passes on the head and fails on Codex's patch. docs/18 already says "skipped and read again at the next check", which is the behaviour |
| F5: `caData` echoed by a server reaches findings | Codex (Low) | **Rejected, on OB3's evidence.** `caData` is a public CA certificate and is never sent to the server; no design document forbids it in findings (the claim came from the coordinator's brief, not the design). The fix cost up to 1.9 s per redact call (a quadratic prefix loop). The token redaction of #420 is unchanged |
| N1: behind `HTTPS_PROXY`, httpcore 1.0.9 starts the tunnel's TLS with the URL host and drops `tlsServerName` (it fails closed) | OB3 | **Accepted.** `trust._NamedContext` carries the name; the trusted cache is keyed by (paths, name). Proven with a real CONNECT proxy |
| N2: no `VERIFY_X509_PARTIAL_CHAIN`, so a caData or bundle holding only the issuing intermediate fails, where client-go accepts it | OB3 | **Accepted** |
| N3: a `tlsServerName` with a trailing dot never verifies; one with two dots is accepted | OB3 | **Accepted.** One root dot is dropped, more are refused |

**Confirmed, with no finding:**
- The system store is OpenSSL's build-time path: 118 anchors in the image.
- The hostname check, `CERT_REQUIRED` and minimum TLS 1.2 are all on.
- The trust cache is thread-safe: 16 threads, 640 TLS checks and 719 bundle swaps, 0 errors.

**Not checked:** CRC, kind and OpenShift (the injected bundle filling); SOCKS proxies; the image built from this PR.
