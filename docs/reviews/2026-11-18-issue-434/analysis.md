# #434 analysis: how cmapi trusts a cluster's API server

Written 2026-11-18 by the #434 implementer (Opus 5.5, high), before any design or code. Saved by the coordinator, because
the harness refused the subagent's write. Sources were read on 2026-11-18.

"Measured" means a run on this Mac, saved in `workbench/cmapi/fix-434/analysis-probe.txt`. The probe is a local TLS
server on 127.0.0.1 whose certificate is signed by a test CA "B" and names only `api.example.test`. Versions: Python
3.12.14, OpenSSL 3.6.4, httpx 0.28.1.

## 1. Primary sources

**S1: kubeconfig v1 `Cluster`** (kubernetes.io/docs/reference/config-api/kubeconfig.v1)
- `certificate-authority-data`: "contains PEM-encoded certificate authority certificates. Overrides CertificateAuthority".
- `insecure-skip-tls-verify`: "skips the validity check for the server's certificate. This will make your HTTPS
  connections insecure."
- `tls-server-name`: "used to check server certificate. If TLSServerName is empty, the hostname used to contact the
  server is used."

**S2: client-go `rest/config.go` `TLSClientConfig`**
- `Insecure`: "Server should be accessed without verifying the TLS certificate. For testing only."
- `ServerName`: "passed to the server for SNI and is used in the client to check server certificates against."
- "CAData takes precedence over CAFile".

**S3: client-go `transport/transport.go`**
- `HasCA() && Insecure` is an error: "specifying a root certificates file with the insecure flag is not allowed".
- `rootCertPool`: "When caData is not empty, it will be the ONLY information used in the CertPool"; with no caData,
  the system roots are used.
- ServerName is copied as given. Insecure together with ServerName is not refused.

**S4: Argo CD cluster Secret `tlsClientConfig`**
- Fields: `insecure`, `caData`, `serverName`, `certData`, `keyData`. These are client-go's fields, so S3 applies.
- `argocd-tls-certs-cm` covers repository servers, not clusters.

**S5: OCM `cluster/v1/types.go` `ClientConfig.CABundle`**
- "the ca bundle to connect to apiserver of the managed cluster. System certs are used if it is not set."

**S6: kubeadm join**
- `--discovery-token-ca-cert-hash sha256:<hex>` validates "the public key of the root certificate authority". The hash
  is taken "over the bytes of the Subject Public Key Info (SPKI) object (as in RFC7469)".
- `--discovery-token-unsafe-skip-ca-verification` "weakens the kubeadm security model since other nodes can potentially
  impersonate the Kubernetes Control Plane."

**S7: Rancher/SUSE, "Updating the Rancher certificate"**
- `CATTLE_CA_CHECKSUM` is the SHA-256 of the CA certificate. It must be updated when the private CA changes.

**S8: OpenShift, "Configuring a custom PKI" (4.2 to 4.22)**
- `proxy/cluster.spec.trustedCA` names a ConfigMap in `openshift-config`.
- The Cluster Network Operator merges the contents of `trustedCA` with the RHCOS trust bundle. It injects the result
  into any empty ConfigMap labelled `config.openshift.io/inject-trusted-cabundle: "true"`, under the key `ca-bundle.crt`.
- Labelling a ConfigMap that already holds data replaces that data.
- Do not combine the label with `service.beta.openshift.io/inject-cabundle`.
- The time the operator takes to fill the ConfigMap was not measured.

**S9: RFC 5280 §6**
- "The selection of a trust anchor is a matter of policy".
- "The certificate validity period includes the current time."

**S10: RFC 9525**
- "The Common Name RDN MUST NOT be used to identify a service".
- The reference identity comes from the client's input, independently of what the server presents.
- "An IP-ID reference identifier MUST exactly match the value of an iPAddress entry in subjectAltName."

**S11: OWASP TLS and Pinning cheat sheets**
- HPKP is deprecated.
- "There is almost no situation where you should consider pinning".
- "Do not give the user an option to proceed and bypass the pin".
- "Implementing pinning validation from scratch should be avoided".
- "For internal applications, an internal CA can be used."

**S12: Python `ssl`**
- `create_default_context()` loads OpenSSL's default verify paths. `SSL_CERT_FILE` overrides the CA file among them.
- Since Python 3.7, OpenSSL matches the hostname or IP address during the handshake.

**S13: httpx 0.28.1**
- `verify=True` uses `SSL_CERT_FILE`, else `SSL_CERT_DIR`, else certifi.
- `verify=<str>` is deprecated.
- `verify=<SSLContext>` is used as given.
- A per-request `extensions={"sni_hostname": ...}` sets the TLS server name.

**Measured**
1. `load_verify_locations` adds to the store: 187 CAs, then 188, then 189.
2. Calling the server by 127.0.0.1 with the right CA fails: "IP address mismatch".
3. The same call with `sni_hostname=api.example.test` returns 200.
4. With that override but the wrong CA, the call still fails.
5. The default context with B loaded on top returns 200.
6. `create_default_context()` holds 187 CAs. With `SSL_CERT_FILE=b.pem` set, it holds 1.
7. `verify=True` (certifi) does not trust B.
8. `verify=False` returns 200.

## 2. Trust model: the owner's three modes

| Mode | When | Trust anchors | `trust.source` |
|---|---|---|---|
| insecure | `insecure: "true"`, and the environment allows it | none | `insecure`, `downgrade: true` |
| caData | `caData` is present | those PEMs only: they replace the system roots and never add to them (S1, S3, S4) | `caData` |
| trusted | neither | the system store, then the injected bundle, then each operator bundle, all loaded into one context | `trusted` |

**Refusals** (status `invalid-secret`; each finding names the field or the setting):
- `insecure` together with `caData` (S3's own error).
- `insecure` where the environment does not allow it. This is checked before the client is built, so the token is never
  sent.
- `insecure` set to anything other than `"true"` or `"false"`.
- `caData` that holds no certificate.
- A server name that is neither a DNS name nor an IP literal.

A server name together with `insecure` is allowed: it sets only the name sent in the TLS handshake (SNI).

**The system store.** Pods set `SSL_CERT_FILE` to `cmapi-trust`, which replaces the OpenSSL bundle (measurement 6).
Recommendation: load the image's OpenSSL build-time defaults explicitly, so no environment variable changes cluster
trust. This is the rule #97 set for Git.

**Fallback bundles: `CMAPI_TRUSTED_CA_FILE`**
- A colon-separated list of paths, loaded one after another into one context.
- A missing file is skipped, and the result is not cached, because OpenShift fills the injected ConfigMap late.
- A file that exists but fails to load is a finding naming that path.
- The context is cached per value of the variable, and rebuilt when a file's mtime or size changes.
- Chart: `trustedCA.injected` (an empty ConfigMap with the label, mounted as optional) and `trustedCA.existingConfigMap`
  (made by the operator, never templated).
- Under Argo CD, the injected ConfigMap needs `ServerSideApply=true` and `ignoreDifferences` on `/data`.

**Server name: `tlsServerName` in the import Secret** (kubeconfig `tls-server-name`, client-go `ServerName`, Argo CD
`serverName`)
- It is the reference identity of RFC 9525. It sets SNI and the name check, and never changes the trust anchors
  (measurements 3 and 4).
- The kind import would name `host.crc.testing`, so the hand-added IP SAN would no longer be needed.

**Rotation and expiry**
- Show the `notAfter` of the server certificate that was verified, and the earliest `notAfter` in `caData`.
- A change to `caData`, `insecure` or the server name must rebuild the client and the caches (G6).

## 3. Decision 1: the flag

**(a) Skip verification entirely**
- Prior art: kubeconfig `insecure-skip-tls-verify`; client-go and Argo CD call it `insecure`.
- Exposure: an attacker on the network path can take the reader token at any time.
- Rotation: nothing breaks. State to keep: none. It is already built.

**(b) Pin the certificate on first contact (TOFU)**
- Exposure: the token is open to a man-in-the-middle on the first contact.
- Rotation: every new certificate is refused until someone re-pins it. This is why HPKP failed.
- It needs the pin kept in the database, a re-pin operation, and a hand-written chain check. Python 3.12 has no
  verified-chain API.

**(c) A root fingerprint supplied by the operator**
- Prior art: kubeadm's CA hash, Rancher's `CATTLE_CA_CHECKSUM`.
- It needs the same knowledge as `caData`, plus a hand-written chain check, and many servers do not send their root.

**Recommendation: (a), named `insecure`.**
- No alias. It is allowed only where the environment's setting allows it, and is off by default everywhere.
- It is refused together with `caData`.
- It is shown as `trust: {source: insecure, downgrade: true}`, with the metric `cmapi_cluster_tls_insecure`.
- The event `cluster_tls_mode` is logged once each time the mode changes.

**The setting:** `instance.clusterTLS.environments.<env>.insecureSkipTLSVerify`, following the spelling of APIService's
`insecureSkipTLSVerify`.

## 4. What must never happen
1. A token sent over unverified TLS where the environment does not allow it.
2. A token sent after a trust store failed to load: there is never a fallback to `verify=False`.
3. Certificates taken from values or Git into the new fallback.
4. `caData` widened to the system store.
5. A token in a finding or a log (#420).

## 5. Gaps on main 0b97bcb
| Gap | Where | What |
|---|---|---|
| G1 | `registry.py:50`, `:298-299` | `INSECURE_ALLOWED={"rnd"}` is hard-coded |
| G2 | `registry.py:302`, `context.py:119` | With no `caData`, the only trust is `CMAPI_CA_BUNDLE`, which on CRC is Keycloak's CA |
| G3 | `kube.py:79` | Uses the deprecated `verify=<str>`; `verify=True` means certifi or `SSL_CERT_FILE` |
| G4 | `kube.py:75-81` | No server-name override |
| G5 | `registry.py:252-263` | `caData` is written to mkstemp files that are never removed |
| G6 | `registry.py:317-318` | The fingerprint ignores the `caData` content, `insecure` and the server name. Found by reading; not yet tested |
| G7 | `registry.py:104-107`, contract `ClusterView` | No trust source, downgrade mark or expiry |
| G8 | `registry.py:309`, `:353` | Findings say "the hub bundle" for what is `CMAPI_CA_BUNDLE` |
| G9 | `jobs/watch_sync.py:37-41` | The deliverer client uses `ca.crt` or certifi |
| G10 | `registry.py:184` | The hub import source uses `verify=str` |
| G11 | `settings.py:23`, docs/18:724 | `CMAPI_CA_BUNDLE` is documented as cluster trust |
| G12 | helm `values.yaml:241-247` | `injected.enabled` labels `cmapi-trust` itself; there is no `existingConfigMap` and no `CMAPI_TRUSTED_CA_FILE` |
| G13 | plain manifests | No injected ConfigMap, no mount, no variable |
| G14 | docs/02:665-668, :734-742, :753; docs/18:724, :796 | Need updating |

The CRC and kind imports both carry `caData`, so the change in G2 does not affect them.

## 6. The owner's decisions

| | Decision | Recommendation |
|---|---|---|
| D1 | The flag | (a), named `insecure` |
| D2 | The setting | `instance.clusterTLS.environments.<env>.insecureSkipTLSVerify`, false by default; prod never allows it |
| D3 | `tlsServerName` | Add it |
| D4 | `CMAPI_CA_BUNDLE` | Remove it from cluster trust |
| D5 | Existing `trustedCA.certificates` and `30-trust.yaml` | Keep them |
| D6 | Expiry | Report it now |
| D7 | The system store | The image's OpenSSL defaults |
