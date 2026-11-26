# CRC reads usage from Thanos, with the reader's least grant

Part of #22. The owner turned OpenShift monitoring back on for CRC on 2026-11-26, cluster and user-workload monitoring. Until then
CRC ran `capacity.yaml` `usage: {"source":"none"}` (#489), so every quota-change plan and every Quotas row said insufficient data.

**Measured by the coordinator on CRC, 2026-11-26.** Thanos Querier answers through Route `thanos-querier` in
`openshift-monitoring`, with the router CA, a kubeadmin token and `/api/v1/query`: `count(up)` 69, `count(kube_resourcequota)` 108.

## What changes on CRC

| File | Change |
|---|---|
| `deploy/manifests/environments/crc/20-config.yaml` | `usage: {"source":"thanos"}`. No `thanosUrl`: the design's default is the Route (docs/02, "Capacity plugin": "at the thanos-querier Route in openshift-monitoring, or at the optional thanosUrl override") |
| `deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml` | In `openshift-monitoring`: Role and RoleBinding `cmapi-reader-thanos-route` (`get` on Route `thanos-querier` alone), and RoleBinding `cmapi-reader-metrics-api` of the platform's Role `cluster-monitoring-metrics-api`, each to `cmapi-system/cmapi-reader` |
| `deploy/crc-rollback.sh` | Deletes the three, each by name. The platform's Role stays |
| `deploy/crc-proof.sh` | Proves the two grants by cmapi's own bindings, and a query with a reader token |

Not changed: kind (`environments/kind`, no OpenShift monitoring), `examples/`, and the chart's default (`source: none`). The trust
of the query is the import's, `kube-root-ca.crt`, which holds the ingress CA, as #310's review measured
([`../2026-11-25-issue-310/README.md`](../2026-11-25-issue-310/README.md), Codex H1): no code changes.

## Why this grant, and not `cluster-monitoring-view`

`docs.redhat.com` answered 403 to every fetch from this machine (Akamai "Access Denied", also for 4.17). The sources below are the
documentation's own source, `openshift/openshift-docs` branch `enterprise-4.22` at commit `19e40afdd86b` (2026-11-25), and the
monitoring operator's, `openshift/cluster-monitoring-operator` branch `release-4.22` at `7e452df90f68`, read 2026-11-26.

1. **Which roles OpenShift 4.22 names.** `modules/monitoring-granting-users-permissions-for-core-platform-monitoring.adoc`
   (<https://github.com/openshift/openshift-docs/blob/enterprise-4.22/modules/monitoring-granting-users-permissions-for-core-platform-monitoring.adoc>):

   > `cluster-monitoring-metrics-api` | Users with this role have the ability to access Thanos Querier API endpoints. Additionally,
   > it grants access to the core platform Prometheus API and user-defined Thanos Ruler API endpoints. | `openshift-monitoring`

   > `cluster-monitoring-view` | Users with this cluster role have the same access rights as `cluster-monitoring-metrics-api` role,
   > with additional permissions, providing access to the `/federate` endpoint for the user-defined Prometheus.

2. **How it is granted.** `modules/monitoring-granting-user-permissions-using-the-cli.adoc`: "Whichever role or cluster role you
   choose, you must bind it against a specific project as a cluster administrator", with
   `oc adm policy add-role-to-user <role> <user> -n <namespace> --role-namespace <namespace>`. The RoleBinding in the manifest is that
   command as YAML, applied by docs/13's step 7, never by hand.

3. **What the Route checks.** The Route `thanos-querier` sends to port `web`, kube-rbac-proxy (`assets/thanos-querier/route.yaml`,
   `deployment.yaml`). Its authorization (`assets/thanos-querier/kube-rbac-proxy-web-secret.yaml`):

   ```yaml
   "authorization":
     "resourceAttributes":
       "apiGroup": "monitoring.coreos.com"
       "name": "k8s"
       "namespace": "openshift-monitoring"
       "resource": "prometheuses"
       "subresource": "api"
   ```

   kube-rbac-proxy maps a `GET` to the verb `get` (`openshift/kube-rbac-proxy` `release-4.22`, `pkg/proxy/proxy.go`:
   `case "GET": apiVerb = "get"`). cmapi sends only `GET` (`KubeClient.monitoring_get`). The same config was read on CRC, 4.22.14.

4. **What each role holds** (`assets/cluster-monitoring-operator/`, the same on CRC):
   - `cluster-monitoring-api-role.yaml`: Role `cluster-monitoring-metrics-api` in `openshift-monitoring`, one rule, `get`, `create`,
     `update` on `prometheuses/api` named `k8s`. Exactly the check in 3; `create` and `update` are a `POST` or `PUT` of the same query
     API, no other data.
   - `cluster-role-view.yaml`: ClusterRole `cluster-monitoring-view`, the same rule plus `get` on `namespaces`, bound cluster-wide.
     `get` on `namespaces` is the check of the user-defined Prometheus's `/federate`
     (`assets/prometheus-user-workload/kube-rbac-proxy-federate-secret.yaml`).

The namespaced Role is the narrowest documented platform role for the Querier API. A custom Role could grant only the GET
verb cmapi uses. The reader already holds cluster-wide `get` on `namespaces` for its watch cache, which satisfies the
separate user-workload `/federate` authorization check. Step 23 checks the namespace boundary of the new metrics grant
by asking for the same `prometheuses/api` name `k8s` in another namespace.

5. **The 4.22 doc's other sentence.** `modules/monitoring-about-accessing-monitoring-web-service-apis.adoc`: "To access Thanos Ruler
   and Thanos Querier service APIs, the requesting account must have `get` permission on the namespaces resource, which can be granted
   by binding the `cluster-monitoring-view` cluster role to the account." The operator's code for 4.22 (3) checks `prometheuses/api`,
   not `namespaces`, on the Querier's Route. The reader holds `get` on `namespaces` anyway, so this does not change the outcome. Step
   23's query with the reader's own token is the measurement.

**The Route's `get`.** `capacity/thanos.py` reads `/apis/route.openshift.io/v1/namespaces/openshift-monitoring/routes/thanos-querier`
(`ROUTE_PATH`) when `clusters.yaml` names no `thanosUrl`. A Role in `openshift-monitoring` with `resourceNames: [thanos-querier]` is
narrower than the baseline's ClusterRole rule for the same name in every namespace (`examples/baseline/cmapi-reader-rbac.yaml`).
Setting `thanosUrl` instead would drop this one grant, at the cost of a host written into the configuration that the Route already
holds; the design's default is the Route, so CRC follows it.

## Measured on CRC, 2026-11-26, read only

- `oc get clusterversion`: 4.22.14. Role `cluster-monitoring-metrics-api` and the kube-rbac-proxy config are as in 3 and 4.
- A cmapi-api pod resolves `thanos-querier-openshift-monitoring.apps-crc.testing` to `192.168.127.2` and connects on 443; cmapi's
  NetworkPolicies are ingress only.
- **CRC already grants monitoring to everyone.** ClusterRoleBinding `openshift-coo-cluster-monitoring-view` (Helm release
  `openshift-coo`, chart `openshift-coo-0.5.2`, created 2026-10-28, another project's) binds `cluster-monitoring-view` to
  `system:authenticated`. So `oc auth can-i get prometheuses.monitoring.coreos.com/k8s --subresource=api -n openshift-monitoring
  --as=system:serviceaccount:cmapi-system:cmapi-reader` says `yes` today, without cmapi's grant. It is not cmapi's to change. The
  proof therefore asks a SubjectAccessReview with the reader's own groups and without `system:authenticated` (impersonation always
  adds that group). Before this change it answered `false` for both reads; a positive control (`telemeter-client`) answered
  `true ... ClusterRoleBinding "telemeter-client-view"`, and the reader's own `create serviceaccounts/token` answered
  `true ... RoleBinding "cmapi-reader-renew/cmapi-system"`, the reason format the proof matches.
- `oc apply --server-side --dry-run=server` of the three objects: each `serverside-applied (server dry run)`, nothing persisted.

Not done here: applying them, which is run 45's step 7, and the proof's reads with them, step 23.

**Filed:** #724, the reference baseline (`examples/baseline/cmapi-reader-rbac.yaml`) and docs/01 and docs/02 still bind the reader
cluster-wide to `cluster-monitoring-view` and grant the Route name in every namespace; the same narrower grant fits there. Not
changed here: docs/02 is a live Claude Doc, edited there first.

## Tests

| Test | main | this change |
|---|---|---|
| `test_crc_reads_usage_from_thanos_and_kind_reads_none` | fails | passes |
| `test_crc_reader_may_query_thanos_through_the_namespaced_monitoring_role_alone` | fails | passes |
| `test_crc_rollback_names_every_object_the_run_creates` | passes | failed with the three objects and the old rollback; passes with the rollback naming them |
| `deploy/tests/crc-scripts-test.sh`: the proof stops without the Route grant, with the query allowed only by a binding to everyone, with the same named metrics API permission extending to the user-workload namespace, with a positive count carrying a store warning, with no or zero `kube_resourcequota` | n/a | each stops |

## Review and the coordinator's rulings (2026-11-26)

**Reviewer 1:** Codex gpt-6.2-astra xhigh (`review/reviewer-1-codex.md`). It **confirmed the RBAC**:
- `cluster-monitoring-metrics-api` is the smallest documented platform role;
- the Route `get` is required, because no `thanosUrl` is set;
- the rollback removes exactly the three new objects.

Its findings, all fixed with Codex's patch:
- **Medium:** the negative SubjectAccessReview asked about `prometheuses/api` `user-workload`, which a broad grant would not have matched either, so it could certify a false isolation. It now checks the boundary correctly.
- **Medium:** the reader smoke test used the workstation CA, omitted `partial_response=false`, and ignored the status and warnings. A Thanos answer cmapi treats as unavailable could pass it. It now checks them.
- **Low:** an edit to a comment in the kind ConfigMap triggered a rollout. Reverted.

**Reviewer 2:** PR #724, which is stacked on this branch, gives cmapi's reader the same grant on every onboarded cluster. It gets two reviewers over the same RBAC, which is the second look at it. This PR's code change after review is limited to the proof scripts and that comment.

**OpenShift 4.18+:** the Role and the Thanos Querier web proxy's check are identical on release-4.18 and release-4.22 (see the PR comment).

**Owner, 2026-11-26:** "cmapi must grant it own permission to the pods with or without openshift coo". This PR grants cmapi's own RoleBindings, and the proof excludes `system:authenticated`.

**Run:**
- `crc-scripts-test.sh`: 0 failed;
- plain manifests, usage review and reader import: 116 passed;
- render: 0 failed;
- shellcheck: clean;
- citations: 0 problems.
