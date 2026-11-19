# #434: cluster TLS trust, per environment

The analysis is [`analysis.md`](analysis.md): the primary sources, the measurements and the gaps G1 to G14 on main `0b97bcb`. This
file records the owner's decisions, what was built from them, and the tests.

## The owner's decisions (2026-11-18, relayed by the coordinator)

| # | Decision |
|---|---|
| D1 | The flag that trusts a cluster's certificate is skip verification, named `insecure` as in client-go and Argo CD, with no alias. Environment-gated; `trust: {source: insecure, downgrade: true}` in `GET /api/v1/clusters`; the metric `cmapi_cluster_tls_insecure{cluster_id}`; the log event `cluster_tls_mode` once per change of mode |
| D2 | The setting is `instance.clusterTLS.environments.<env>.insecureSkipTLSVerify`, false everywhere by default. Any environment may allow it, prod included |
| D3 | `tlsServerName` is added to the import Secret |
| D4 | `CMAPI_CA_BUNDLE` leaves cluster trust; Keycloak keeps it |
| D5 | `trustedCA.certificates` and CRC's `30-trust.yaml` stay as they are; the new operator bundle is never templated from values |
| D6 | No certificate expiry in this issue: it stays with #396. The rebuild on a change of trust (G6) is in scope |
| D7 | The system store is the image's OpenSSL build-time defaults, loaded by path, not `SSL_CERT_FILE` |

The owner's target model: per cluster exactly one of the flag, `caData`, or the fallback (the system store, the injected bundle and
an operator's ConfigMap).

## What was built, gap by gap

| Gap | Fix |
|---|---|
| G1 | `INSECURE_ALLOWED` removed; `ClusterTLSSettings` (`core/clustertls.py`) parses `instance.clusterTLS`, `load_instance` refuses an unknown key, an environment not served or a value that is not a boolean, and `build_context` hands the allowed environments to the registry |
| G2, D4, D7 | The trusted mode: `trusted_context` (`core/clients/trust.py`) loads the image's system store by path, then each bundle of `CMAPI_TRUSTED_CA_FILE` in turn. A missing or empty bundle is skipped and the context is keyed by the size and time of every path, so a bundle that appears is read at the next check; one that does not load raises `TrustBundleError`, which names it |
| G3 | `KubeClient` never passes `verify=True` or a path string: an `SSLContext` from the cluster's `Trust`, a file, or the trusted mode |
| G4, D3 | `tlsServerName`: a request hook sets httpcore's `sni_hostname`, the TLS `server_hostname`, on every request and stream |
| G5 | caData is loaded in memory (`cadata=`); no temporary files |
| G6 | The fingerprint is `apiUrl|token[-12:]|Trust.fingerprint()`: the mode, a SHA-256 of caData, the server name, and the bundles' signature |
| G7, D1 | `ClusterState.trust` and `ClusterTrust` in the contract (additive: oasdiff `response-optional-property-added`); the metric and the log event |
| G8 | Findings name `caData` or `trusted (the system store and CMAPI_TRUSTED_CA_FILE)` |
| G9 | The deliverer client with no `ca.crt` gets the trusted mode through `KubeClient`, not certifi. It does not take the import's mode: its credentials are a separate Secret |
| G10 | `HubImportSource` uses an `SSLContext` from the hub's `ca.crt` |
| G11 | `Settings.ca_bundle` and docs/18 no longer call it cluster trust; `Settings.trusted_ca_file` is documented |
| G12 | Chart: `trustedCA.injected` is now its own empty ConfigMap `<release>-trusted-ca` (with `ServerSideApply=true`), `trustedCA.existingConfigMap` mounts an operator's ConfigMap by name, both joined into `CMAPI_TRUSTED_CA_FILE`; `instance.clusterTLS` reaches instance.yaml. With `certificates` empty, the injected ConfigMap is still the pods' Keycloak trust, as `injected.enabled` was before |
| G13 | Plain manifests: the api and the worker mount `cmapi-trusted-ca` and `cmapi-cluster-ca`, both optional, and set `CMAPI_TRUSTED_CA_FILE`; CRC gets `35-trusted-ca.yaml`, and `crc-rollback.sh` deletes it by name |
| G14 | docs/02 (the import contract's fields, "TLS: one mode per cluster", Diagnostics), docs/18 ("Cluster trust", the variable, the Helm values), docs/13 (CRC's injected ConfigMap; the kind import's `tlsServerName`) |

Also: `insecure` must be `"true"` or `"false"` (a YAML boolean of `CMAPI_IMPORTS_DIR` still reads as its text). The kind import
(`deploy/kind-import/`) now sends `tlsServerName: host.crc.testing`; a cmapi before #434 ignores the field, and the certificate
names both the address and that name, so the Secret works with either.

## Tests

Outputs in `workbench/cmapi/fix-434/`.

| Test | On main | On the branch |
|---|---|---|
| `cmapi/tests/service/test_cluster_trust_434.py`, the registry against real TLS servers (28 cases first written) | 26 failed, 2 passed (`before-main-summary.txt`). The 2 that pass are guards that hold on both: caData never widens, and the server name never changes the anchors | all passed |
| G6, proved before the fix (`before-main-G6.txt`) | a rotated caData and a new `tlsServerName` kept the client the caches hold (`cache.client is held`) | passed |
| the same file's 7 `clusterTLS` cases, added after | fail: no `core/clustertls.py` | passed |
| `cmapi/tests/service/test_cluster_trust_chart_434.py`, `helm template` and the plain manifests | 9 failed (`before-main-chart.txt`) | 9 passed (`after-chart.txt`) |
| `test_crc_environment.py::test_crc_allows_no_insecure_cluster_and_shows_each_cluster_trust` | fails (no `trust`, no `cluster_tls`) | passed |
| `test_registry_survives_419.py`: the hub-bundle case became the trusted-bundle case (D4) | | passed |
| `deploy/tests/kind-import-test.sh`, `deploy/render-test.sh`, `deploy/tests/crc-scripts-test.sh` (stubs, no cluster) | | 0 failed |
| contract gate against main's `openapi.json` | | no breaking change; one `response-optional-property-added` (`contract-gate.txt`) |

Not tested: anything on CRC or kind (no change was made there); OpenShift's filling of the injected ConfigMap; the portal's own
suite (its generated types gain one optional field); Spectral's lint, which CI runs.

## Who wrote what

Opus 5.5 at `high`, the #434 implementer, wrote the analysis, every file of this pull request, and its tests. The owner made the
decisions above. The review is the coordinator's to run; with Fable paused, Codex is the one outside model family.
