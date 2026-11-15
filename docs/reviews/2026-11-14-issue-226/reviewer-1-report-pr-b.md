# Security review — reviewer 1, cmapi #226 PR-B / PR #247

Reviewed export `8ff035220bda62b7e7b62fae3919420698e76f6b` against PR #238 (`0bae57b`) using `change.diff` and the previous [reviewer 1 report](docs/reviews/2026-11-14-issue-226/reviewer-1-report.md).

**Three findings: two medium issues in the security proof scripts, and one low hardening issue in the new portal Deployment (also present in the chart).** The plain NetworkPolicies, Routes, host configuration, rendering, and Deployment settings otherwise match the chart's CRC/Route behavior. I found no new ordinary-pod ingress bypass in the supplied policies themselves.

Original application, deployment, and test files are unchanged. Full proposed code is in [after/](review-artifacts/after/); [all-fixes.diff](review-artifacts/all-fixes.diff) contains every proposed source/test-harness change. Each finding below links its complete patch and executed regression. These patches apply to this export and have disjoint files. All tests of cluster scripts used stubs; no container, cluster, or database was started.

## Finding 1 — kind can succeed without either NetworkPolicy

**Medium; C7 refuted. Locations:** `deploy/kind-test.sh:89-95`, `205-206`, `227`; missing negative checks alongside `168-191`. This PR extends the existing DNS workaround to delete the new front-door policy too.

On the detected podman/kind DNS failure, the script deletes both `cmapi-metrics` and `cmapi-front-door`, excludes the policy file from the second apply, then returns success. Even without that workaround, it never attempts a forbidden connection: port-forward bypasses NetworkPolicy, and the portal-to-API request is an allowed connection. Thus an open API port, an open front-door port, or both can pass the supposed security proof. Existing `deploy/tests/kind-test-stubbed.sh:47-50,79-80` explicitly expects the deletion path to succeed.

**Complete fix and updated existing tests:** [finding-1-fix.diff](review-artifacts/finding-1-fix.diff). Full resulting script: [kind-test.sh](review-artifacts/after/deploy/kind-test.sh).

The fix fails with an explicit inconclusive-enforcement message on the DNS problem and keeps both policies installed. It creates an unlabelled probe pod in `cmapi` (outside the router namespace), attempts TCP connections to actual API/portal pod IPs on 8080, and requires a timeout for each forbidden connection. Execution errors and connection refusal are failures. An allowed request from the front door to the API checks that the API is available. The ordinary functional checks still verify the portal through port-forward. The existing kind stub suite now expects DNS failure to fail and includes missing-policy and exec-error cases.

**Executed regression:** `python3.13 review-artifacts/regression.py before` and `after`, function `finding1`. [Full test code](review-artifacts/regression.py). The five scenarios use the real `kind-test.sh` on stubbed kind/kubectl/podman/curl/sleep; they never invoke a cluster or database.

| Scenario | Before | After |
|---|---|---|
| Enforced policy and working application | exit 0 | exit 0 |
| Direct API access allowed | **exit 0, wrong** | exit 1 |
| Direct front-door access allowed | **exit 0, wrong** | exit 1 |
| DNS workaround would remove policies | **exit 0, wrong** | exit 1 |
| Probe execution fails | **exit 0, wrong** | exit 1 |

**Four failed regression assertions before, zero after.** [Before summary](review-artifacts/kind-before.txt), [after summary](review-artifacts/kind-after.txt), [original DNS success](review-artifacts/before-kind-dns-removal.txt), [fixed DNS failure](review-artifacts/after-kind-dns-removal.txt).

This changes the test contract deliberately: a runtime that cannot enforce the supplied policy is no longer a successful security run. The new checks' verdict logic is exercised here; real CNI behavior still requires a future authorized cluster run.

## Finding 2 — np-reach interprets execution/HTTP failures as enforced denial

**Medium; C7 refuted. Location:** `deploy/tests/np-reach-test.sh:41-43`, consumed by `49-60`. The PR expands this existing classifier to the new front-door checks.

Every unsuccessful `kubectl exec ... wget` becomes `blocked`; diagnostics are discarded. The no-policy positive controls run only before policy application. After that phase, an exec authorization/transport failure for the otherwise forbidden probes can produce exactly the expected matrix, while the front-door-to-API permitted probe still works. The test passes even if the network would allow all connections. Connection refusal and HTTP 503 also count as proof of policy enforcement. An HTTP response proves a server was reached.

**Complete fix:** [finding-2-fix.diff](review-artifacts/finding-2-fix.diff). Full resulting script: [np-reach-test.sh](review-artifacts/after/deploy/tests/np-reach-test.sh).

The fix accepts the pinned image's `wget: download timed out` diagnostic only, rejects other errors as inconclusive, and repeats a reachable, unselected control-pod request from the same source after a timeout. It retains the no-policy positive matrix, the allowed front-door-to-API check, and the port-forward checks. This follows the stricter approach already used in `crc-proof.sh:94-100`.

**Executed regression:** `python3.13 review-artifacts/regression.py before finding2` and `after finding2`. [Full test code](review-artifacts/regression.py), function `finding2`. All kubectl, curl, and sleep calls are local stubs; there are no network listeners.

| Scenario | Before | After |
|---|---|---|
| Correct allow/drop matrix | exit 0 | exit 0 |
| Missing API enforcement | exit 1 | exit 1 |
| Missing front-door enforcement | exit 1 | exit 1 |
| Forbidden probes fail at exec | **exit 0, wrong** | exit 1 |
| Forbidden probes get connection refused | **exit 0, wrong** | exit 1 |
| Forbidden probes get HTTP 503 | **exit 0, wrong** | exit 1 |
| Timeout but source cannot reach control | **exit 0, wrong** | exit 1 |

**Four failed assertions before, zero after.** [Before](review-artifacts/np-before.txt), [after](review-artifacts/np-after.txt). In the [original exec-error run](review-artifacts/before-np-exec-error.txt), the final line is `np cases failed: 0`; the [fixed run](review-artifacts/after-np-exec-error.txt) reports five inconclusive probes and fails.

## Finding 3 — front door leaves automatic API token mounting enabled

**Low; C6 hardening gap. Locations:** `deploy/manifests/components/portal/10-front-door.yaml:42-94`; also `deploy/helm/cmapi/templates/portal.yaml:50-93`.

Neither Pod template sets `automountServiceAccountToken: false` or names a dedicated ServiceAccount. In the normal default configuration Kubernetes assigns `cmapi/default` and injects API credentials. nginx serves files, resolves DNS, and proxies HTTP without using the Kubernetes API. Compromise of nginx therefore exposes an unnecessary token, with whatever rights the site's default ServiceAccount has. This export grants it no elevated rights; this is not a demonstrated privilege escalation. A site-wide ServiceAccount setting or admission policy could already suppress the token, but the templates do not guarantee that.

The explicit volume is a ConfigMap, with no Secret reference. Modern automatic service-account credentials normally use a projected token volume: absence of an explicit Secret mount does not establish absence of credentials. See Kubernetes' [default ServiceAccount and credential automount behavior](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/#opt-out-of-api-credential-automounting).

**Complete fix:** [finding-3-fix.diff](review-artifacts/finding-3-fix.diff), applied to both plain and chart templates to preserve parity:

```yaml
    spec:
      automountServiceAccountToken: false
      securityContext:
        # existing settings
```

**Executed regression:** `python3.13 review-artifacts/regression.py before finding3` and `after finding3`. [Full test code](review-artifacts/regression.py), function `finding3`, loads the plain Deployment and actual `helm template` output for CRC and asserts the Pod-level opt-out in both.

**Two failed assertions before, zero after.** [Before](review-artifacts/token-before.txt), [after](review-artifacts/token-after.txt). This proves the rendered safeguard, not a live admission/mount result. The chart omission predates this PR; the new plain Deployment carries it forward.

## Claim-by-claim verdicts

| Claim | Verdict and source evidence |
|---|---|
| **C1** | **Confirmed for ordinary pod-network traffic under an enforcing CNI and the supplied policies, with the qualifications below.** Plain `components/cmapi/40-networkpolicy.yaml:10-27` selects API/worker components, admits only same-namespace `cmapi-portal` + `portal` labels on TCP 8080, and preserves the monitoring-namespace-only TCP 9090 rule (`15-19`). `42-50` selects portal pods and admits TCP 8080 only from namespaces carrying `policy-group.network.openshift.io/ingress: ""`. A same-labelled portal pod in another namespace cannot match the API's namespace-local podSelector. Chart `templates/monitoring.yaml:10-27,39-50` is equivalent with exposure `Route`; `values.yaml:215,247-249` supplies Route and enabled policies. Actual Helm/plain specs compare equal in the passing permitted test. The chart's **Ingress** variant intentionally omits `from` (`44-48`), so parity is with CRC/Route, not every chart mode. |
| **C2** | **Labels are the ordinary pod-to-API admission boundary; “the only way” is too absolute.** `40-networkpolicy.yaml:23-27` checks labels and namespace, not Deployment ownership, image, or ServiceAccount. Anyone authorized to create arbitrary Pods in `cmapi`, or create/update a controller whose Pod template they control, can supply both labels. Someone allowed to patch pod labels can relabel an existing pod; exec/ephemeral-container access to an actual portal pod also gives its network identity. Standard namespace `edit`/`admin` grants or cluster-admin commonly suffice, if bound; ordinary application/Keycloak roles do not grant Kubernetes Pod creation. The export cannot identify live human/group bindings. The shipped RBAC grants API/worker only Secret reads in **cmapi-imports** (`components/cmapi/10-imports-reader.yaml:5-22`); the CRC reader lists pods and PVCs only (`environments/crc/reader/00-cmapi-reader.yaml:33-48`). It grants none of these accounts `create pods` in `cmapi`. Chart `templates/rbac.yaml:42-62` has the same imports grant, and its selector helper (`templates/_helpers.tpl:14-17`) supplies the same portal labels for release `cmapi`. **Chart and plain manifests are equal in this label/RBAC trust boundary.** Matching labels also enter the portal Service (`components/portal/10-front-door.yaml:15`), so namespace workload-write rights must be trusted. |
| **C3** | **Confirmed.** `environments/crc/40-routes.yaml:16-22,31-37`: exactly `cmapi.apps-crc.testing` and `cmapi-mockup.apps-crc.testing`, both to Service `cmapi-portal`, named port `http`, edge TLS, HTTP Redirect, forwarded headers `replace`. No direct API Route is supplied. Chart `templates/exposure.yaml:43-57` matches. Headless `cmapi-api-pods` is `clusterIP: None`, selects API name/component labels, and exposes only 8080 (`components/cmapi/20-api.yaml:16-26`); chart `templates/api.yaml:99-110` agrees. |
| **C4** | **Confirmed for the import/configuration, not proof of updating an existing realm.** `environments/crc/realm/10-realm-import.yaml:261-265` gives portal redirects exactly `/` and `/index.html` on `https://cmapi.apps-crc.testing`; `285-288` gives docs exactly `/docs/oauth2-redirect` on the same host. `webOrigins: ["+"]` derives those redirect origins; it is not an all-origin `*`. Logout uses the same redirect-derived `+` (`259`). `change.diff` changes only the old portal/API host names in these entries, adding no wildcard. `environments/crc/20-config.yaml:18-19,31` agrees on publicUrl, portalUrl, and `/problems/` type base. `crc/60-portal.yaml:15-21` agrees on portal host and apiUrl; mockup remains separate at `16`. The import is explicitly once-only and leaves an existing realm unchanged (`realm/10-realm-import.yaml:1-7`); no live realm migration was run. |
| **C5** | **Confirmed for this export's declared render placeholders and ConfigMap layout.** `render.sh:29,52-63` requires a portal reference and accepts exactly its own GHCR/internal-registry repository with 64 lowercase hex digest; the escape hatch at `55` requires both kind and `--allow-tag` (it is intentionally broader than validating tag syntax). `89-97` fills/rejects the two image and two checksum placeholders, including detecting unsupported `.yml` placeholders. Realm `${...}` values deliberately remain for Keycloak's secret substitution. `37-50,66` hashes the entire file declaring `cmapi-portal-config`, by content, and `92` fills the annotation (`components/portal/10-front-door.yaml:38-41`). CRC `60-portal.yaml:14-28` and kind `40-portal.yaml:11-25` contain all three nginx configuration inputs plus config.json, so every supplied value change affects the hash; unrelated image/API/realm/Route changes do not. Comments and other bytes in the same file can cause harmless extra restarts. This is a byte-level checksum, not a semantic YAML checksum; arbitrary future ConfigMap layouts must still match the name discovery or fail. `render-test.sh:33-54,97-161,180-187` exercises repository separation, tags/digests, checksums, changed portal files, unfilled placeholders and missing/duplicate maps; the suite passed. No concrete missed portal input was found. |
| **C6** | **Deployment parity confirmed; credential opt-out is missing in both (Finding 3).** Plain `components/portal/10-front-door.yaml:43-45,47,52-89` matches chart `templates/portal.yaml:51-89`: four env names/upstream, `/healthz` readiness/liveness at 5/30 seconds, exact preStop hook, 30-second grace, non-root, RuntimeDefault seccomp, no privilege escalation, all capabilities dropped, 10m/32Mi requests and 200m/128Mi limits, and read-only config.json subPath mount. Environment values are ConfigMap references in plain versus literal chart values, and resolve equally. Chart `values.yaml:195-200,254-261` sets the same resources/security and **readOnlyRootFilesystem: false**; omission in plain has that same default. No whole-filesystem read-only guarantee is claimed. The only explicit volume is the portal ConfigMap (`90-94`); neither template needs an API token, but neither disables its automatic mount. |
| **C7** | **Refuted as a statement about all three scripts.** Kind has no forbidden-connection check and can remove policies (Finding 1). `np-reach-test.sh:56-60` has the requested foreign/same-namespace negative matrix but its failure classifier can falsely pass (Finding 2). **CRC meets the requested bounded checks:** `crc-proof.sh:83-93` starts an outside-namespace probe and requires a reachable unselected cmapi control; `96-103` requires dropped connections to both Services and rejects exec, DNS, refused-connection and HTTP errors; `100` requires a working routed API after each timeout. Missing policies fail at the explicit gets (`45-54`) or at a successful direct connection (`98`); its stub suite exercises direct API/front-door access and non-timeout failures and passed. CRC does not test a separate same-namespace unlabelled attacker, so it alone is not a complete same-namespace matrix or proof about every API replica. |

Paths abbreviated in this table are beneath `deploy/manifests/` or `deploy/helm/cmapi/` as indicated.

**Scope of C1/C2:** NetworkPolicies admit the union of applicable policies; another allow policy could widen access. All pods in an ingress-labelled namespace are trusted, not just a particular router Deployment. Policy-changing or namespace-label-changing administrators can widen that trust. Traffic from a pod's own node, host-network behavior, and authorized port-forward/proxy access are not excluded by these pod/namespace selectors. Plain policy comments already disclose probes/port-forward and CRC's host-network router (`40-networkpolicy.yaml:20-34`); these are shared baseline limitations, not newly introduced fixes. See Kubernetes' [policy semantics and host-network limitations](https://kubernetes.io/docs/concepts/services-networking/network-policies/). No live namespace RBAC, admission state, or CNI enforcement was queried.

## What ran

| Command | Result / evidence |
|---|---|
| `bash deploy/render-test.sh` | Passed, `render cases failed: 0`. [Log](review-artifacts/render-baseline.txt). |
| `bash deploy/tests/kind-test-stubbed.sh` | Passed, `wrong: 0`. [Log](review-artifacts/kind-baseline.txt). `pgrep` cannot enumerate processes in this sandbox, so its printed zero leftover-process count is not verified. This does not affect the ingress regressions. |
| `bash deploy/tests/crc-scripts-test.sh` | Passed, `crc script cases failed: 0`. [Log](review-artifacts/crc-baseline.txt). Its temporary fixture repository is created by the test under its temp directory; the export was not turned into a repository. |
| `cd cmapi && PYTHONPATH=src:tests/service python3 -m pytest tests/service/test_plain_manifests.py -q` | Could not start: default Python 3.14 has no pytest. [Log](review-artifacts/pytest-baseline.txt). |
| Same command using `python3.13` | Collection failed on service conftest's unrelated missing `jwt` dependency. [Log](review-artifacts/pytest-py313.txt). |
| `cd cmapi && PYTHONPATH=src:tests/service python3.13 -m pytest --noconftest tests/service/test_plain_manifests.py -q` | **69 passed, 1 failed**. The failure imports realm_sync through package initializers requiring missing `sqlalchemy`; no database was contacted. [Log](review-artifacts/pytest-static.txt). |
| Same static command with `-k 'not test_the_local_realm_users_are_in_groups_the_realm_has'` | **69 passed, 1 deselected** for that unavailable import. Includes actual Helm/plain parity checks. [Log](review-artifacts/pytest-available.txt). No database-dependent tests were run. |
| `python3.13 review-artifacts/regression.py before` / `after` | Initial 13 assertions: **9 fail before / 0 after** (kind 4, np 3, token 2). [Before](review-artifacts/regression-before.txt), [after](review-artifacts/regression-after.txt). |
| `python3.13 review-artifacts/regression.py before finding2` / `after finding2` | Extended 7-scenario NP regression, including a failing protected-phase control: **4 fail before / 0 after**. [Before](review-artifacts/np-before.txt), [after](review-artifacts/np-after.txt). |
| `python3.13 review-artifacts/regression.py before finding3` / `after finding3` | **2 fail before / 0 after**, actual plain and Helm Pod templates. [Before](review-artifacts/token-before.txt), [after](review-artifacts/token-after.txt). |
| `bash review-artifacts/after/deploy/tests/kind-test-stubbed.sh` | Passed, `wrong: 0`, including the four added ingress-proof failures and changed DNS expectations. [Log](review-artifacts/kind-fixed-suite.txt). The same sandbox limitation on pgrep applies. |
| `patch --dry-run -p1 < review-artifacts/all-fixes.diff` | Passed for all six changed files. [Log](review-artifacts/patch-check.txt). |
| `bash -n` on proposed kind-test, np-reach-test, kind stub test and kubectl stub | Passed. |

All specifically requested files were read in full, including the realm, CRC configuration, both rendering scripts, all listed operational/proof scripts, and all five chart files. `crc-image.sh` chooses only the two named build contexts/repositories (`16-21,40-48`); `crc-rollback.sh` now names both Services/policies, the front door and ConfigMap, both Routes and both image streams (`35-39,50-55`). They were exercised only through the allowed CRC stub suite.

TokenSave exploration, status and read were attempted first. This export has no initialized graph and the server cannot read it without a registered project; I fell back to local source inspection. No index was initialized/updated, no other checkout was inspected, and no files outside this folder were changed except the permitted suites' temporary fixtures. The only downloaded fixture was the kind suite's pinned CNPG YAML, SHA-256 `37237f145d8138256ea25ae830f87759255665ff08f8d552fdd8224a5ec032fb`; it was never applied to a cluster.

To reproduce the isolated review results, the supplied `before/` and `after/` trees are ready to use:

```sh
python3.13 review-artifacts/regression.py before finding1  # expected failing assertions
python3.13 review-artifacts/regression.py after finding1
python3.13 review-artifacts/regression.py before finding2  # expected failing assertions
python3.13 review-artifacts/regression.py after finding2
python3.13 review-artifacts/regression.py before finding3  # expected failing assertions
python3.13 review-artifacts/regression.py after finding3
```

The regression runner uses only stubs for cluster commands; its token test needs PyYAML and Helm. Production patches have not been applied to the export.
