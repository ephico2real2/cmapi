# The reader's own Thanos grants on every cluster, and the import check of them

Closes #724, Part of #22. Stacked on #726, which gave CRC's reader these grants.

**The owner, 2026-11-26:** "cmapi must grant it own permission to the pods with or without openshift coo", and "when we onboard a
cluster to cmapi. The service account must have right to the remote cluster thanos." On CRC every authenticated user already
reads Thanos through another project's ClusterRoleBinding, `openshift-coo-cluster-monitoring-view` (#726's measurement). cmapi must
never depend on it, on any cluster.

## What changes

| Where | Change |
|---|---|
| `examples/baseline/cmapi-reader-rbac.yaml`, the reader baseline of every OpenShift cluster | ClusterRoleBinding `cmapi-reader-monitoring` to `cluster-monitoring-view` removed, and the ClusterRole's rule for Route `thanos-querier` in every namespace removed. Added in `openshift-monitoring` alone: Role and RoleBinding `cmapi-reader-thanos-route` (`get` on that Route), RoleBinding `cmapi-reader-metrics-api` of the platform's Role `cluster-monitoring-metrics-api` (both as #726), and Role and RoleBinding `cmapi-reader-grant-check` (`create` on `localsubjectaccessreviews`). Every other object and rule is unchanged |
| `deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml` | `cmapi-reader-grant-check` added; the five objects in `openshift-monitoring` are the baseline's (a test holds them equal) |
| `deploy/crc-rollback.sh`, `deploy/crc-proof.sh` | The rollback deletes the two new objects by name. The proof checks the review grant by its own RoleBinding, and that `GET /api/v1/clusters` shows CRC connected with no usage finding |
| `core/registry.py`, `core/clients/kube.py` | With `usage.source: thanos`, the capability check asks whether the reader holds its two grants (below). A missing one is a finding on a cluster that stays connected |
| `capacity/thanos.py`, `capacity/usage.py`, `core/context.py` | A cluster with a usage finding is not queried; its usage is `unavailable` with the finding as the reason. The registry learns the source from `capacity.yaml` |
| `deploy/kind-import/reader.yaml` | Unchanged, by decision (below) |
| `deploy/helm/cmapi/values.yaml` | The `capacity.usage` comment no longer says "needs cluster-monitoring-view", and says the grant lives on each managed cluster, in the baseline, not in the chart. `templates/reader-renew.yaml` renders only the reader's token renewal, for a hub that is also a managed cluster; the chart deploys cmapi, not the managed clusters' reader, so it renders no monitoring grant |
| docs/01, docs/02 (exports of live docs), docs/05, docs/06, docs/13, docs/18, the mockup's onboarding text | Each sentence that named `cluster-monitoring-view` for the reader |

## The sources, OpenShift 4.18 and later

`docs.redhat.com` answered 403 to this machine for #726; the sources are the documentation's own and the operators', read
2026-11-26 through the GitHub API. The owner has no 4.18 cluster, so for 4.18 these are the evidence; CRC (4.22.14) is the
measured one.

1. **The role OpenShift names.** `openshift/openshift-docs`, `modules/monitoring-granting-users-permissions-for-core-platform-monitoring.adoc`,
   identical in this row on `enterprise-4.18` (commit `814e3f6ce0ad`, 2026-11-25) and `enterprise-4.22` (`19e40afdd86b`,
   2026-11-25) (<https://github.com/openshift/openshift-docs/blob/enterprise-4.18/modules/monitoring-granting-users-permissions-for-core-platform-monitoring.adoc>):

   > `cluster-monitoring-metrics-api` | Users with this role have the ability to access Thanos Querier API endpoints. Additionally,
   > it grants access to the core platform Prometheus API and user-defined Thanos Ruler API endpoints. | `openshift-monitoring`

   > `cluster-monitoring-view` | Users with this cluster role have the same access rights as `cluster-monitoring-metrics-api` role,
   > with additional permissions, providing access to the `/federate` endpoint for the user-defined Prometheus. | Must be bound
   > with `ClusterRoleBinding` to gain access to the `/federate` endpoint for the user-defined Prometheus.

   The two branches differ in that file only in the Alertmanager rows' wording ("in the *Administrator* perspective").
2. **How it is bound.** `modules/monitoring-granting-user-permissions-using-the-cli.adoc`, the same on both branches: "Whichever
   role or cluster role you choose, you must bind it against a specific project as a cluster administrator", with
   `oc adm policy add-role-to-user <role> <user> -n <namespace> --role-namespace <namespace>`. The baseline's RoleBinding is that.
3. **What the Querier checks, and what the Role holds.** `openshift/cluster-monitoring-operator`, `release-4.18` (`87b50fc0c80f`,
   2026-10-24) and `release-4.22` (`7e452df90f68`, 2026-10-19): `assets/cluster-monitoring-operator/cluster-monitoring-api-role.yaml`
   is byte for byte the same on both, Role `cluster-monitoring-metrics-api` in `openshift-monitoring`, `get`, `create`, `update` on
   `prometheuses/api` named `k8s`. `assets/thanos-querier/kube-rbac-proxy-web-secret.yaml` differs only in its version label, and
   authorizes `resourceAttributes` `apiGroup: monitoring.coreos.com`, `name: k8s`, `namespace: openshift-monitoring`,
   `resource: prometheuses`, `subresource: api`. `openshift/kube-rbac-proxy` `release-4.18` (`f72b2ec69dc8`), `pkg/proxy/proxy.go`:
   `case "GET": apiVerb = "get"`, with `User: u`, the token's authenticated user and all its groups.
4. **The other sentence of the docs.** `modules/monitoring-about-accessing-monitoring-web-service-apis.adoc`, the same on both:
   "To access Thanos Ruler and Thanos Querier service APIs, the requesting account must have `get` permission on the namespaces
   resource, which can be granted by binding the `cluster-monitoring-view` cluster role to the account." The operator's code (3)
   checks `prometheuses/api` on the Querier's Route, not `namespaces`, on both branches, and #726 measured a query on CRC with the
   namespaced grant. The reader also holds `get` on `namespaces` cluster-wide in the baseline (and in CRC's reader), so the
   sentence is met either way.

## The import check: why a LocalSubjectAccessReview

The owner asked that onboarding prove the reader can reach Thanos, and the coordinator that the check not rely on
`system:authenticated`. A live query cannot tell: kube-rbac-proxy reviews the token's own user with all its groups (3), so on CRC
it passes without cmapi's grants. A SelfSubjectAccessReview cannot either: it is the caller's own user and groups. Reading the
RoleBindings by name would tie the check to cmapi's names and repeat RBAC's evaluation in cmapi.

A SubjectAccessReview names the user and the groups to judge, and the API server judges exactly those: kubernetes
`pkg/registry/authorization/util/helpers.go`, `AuthorizationAttributesFrom`, builds `user.DefaultInfo{Name: spec.User,
Groups: spec.Groups, ...}` (`release-1.31` `fa33e07f6a06`, identical in `openshift/kubernetes` `release-4.18` `b930000f05a2`).
#726's proof measured it on CRC: with the reader's ServiceAccount groups and without `system:authenticated`, both reads answered
`false` before the grants. Its namespaced kind needs only a grant in that namespace (`staging/src/k8s.io/api/authorization/v1/types.go`):

> LocalSubjectAccessReview checks whether or not a user or group can perform an action in a given namespace. Having a namespace
> scoped resource makes it much easier to grant namespace scoped policy that includes permissions checking.

`pkg/registry/authorization/localsubjectaccessreview/rest.go` refuses a review whose namespace is not the request's, so the Role
`cmapi-reader-grant-check` reviews `openshift-monitoring` alone. It can tell whether any user may do something there; the baseline's
reader already reads every Role and RoleBinding cluster-wide, so that discloses nothing new on a baseline cluster. CRC's reader does
not read RBAC, and this is the one new view it gets.

So, with `usage.source: thanos`, check 6 also: reads discovery of `monitoring.coreos.com/v1` (no OpenShift monitoring: one
finding); then reviews `get` on Route `thanos-querier` (not with a `thanosUrl`) and `get` on `prometheuses/api` `k8s`, both in
`openshift-monitoring`, for `system:serviceaccount:cmapi-system:cmapi-reader` with `system:serviceaccounts` and
`system:serviceaccounts:cmapi-system`. Each missing grant is a finding `usage: missing grant in openshift-monitoring: ...`, a 403 on
the review is `usage: the reader's grants could not be checked: missing grant ... create localsubjectaccessreviews (...)`, and any
other failure of the review is a finding too: a grant that is unknown is not taken as held.

**Not a refusal.** docs/01's check 6 says "reach Thanos. A 403 names the missing grant", and docs/02's usage design is that a
plan without usage "carries usage: unavailable", never a refused cluster. So the cluster stays `connected`, every read works, the
finding is on `GET /api/v1/clusters` with the fix "Apply the reader's openshift-monitoring grants of
examples/baseline/cmapi-reader-rbac.yaml on the cluster", and its usage is `unavailable` with the finding as the reason. The shipped
approval rule adds the platform approver on `usage == "unavailable"`, as for any Thanos failure.

## kind

`deploy/kind-import/reader.yaml` gets nothing. kind runs no OpenShift monitoring: no `openshift-monitoring` namespace to hold a
Role, no `monitoring.coreos.com` API, no Querier. The kind instance (`environments/kind/20-config.yaml`) reads `usage.source:
none`, so its check never runs. The CRC instance imports the kind cluster too and reads `thanos`, so `KIND_CMAPI_TEST` shows, still
connected, the one finding `usage: the cluster serves no monitoring.coreos.com/v1, so it has no OpenShift monitoring`. Before this
change its plans already had usage `unavailable` (the Route could not be read); now the reason says why.

## Tests

| Test | main + #726 | this change |
|---|---|---|
| `test_reader_thanos_grants_724.py::test_the_baseline_grants_thanos_in_openshift_monitoring_alone` | fails (cluster-monitoring-view bound cluster-wide) | passes |
| `::test_crc_and_the_design_grant_what_the_baseline_grants`, `::test_the_check_reviews_what_the_baseline_grants` | fail | pass |
| `::test_a_missing_grant_is_a_finding_on_a_connected_cluster` (3 cases, each with a grant to `system:authenticated`) | fails | passes |
| `::test_with_the_grants_the_cluster_has_no_finding`, `::test_a_reader_that_may_not_ask_has_a_finding_not_a_pass`, `::test_a_cluster_without_openshift_monitoring_says_so`, `::test_a_probe_rechecks_the_grants`, `::test_a_usage_finding_is_logged_as_a_warning_from_the_first_import`, `::test_the_usage_of_a_cluster_with_a_finding_is_unavailable_with_its_reason`, `::test_the_instance_asks_for_the_grants_when_it_reads_usage`, `::test_the_source_name_is_read_once_for_the_registry_and_the_source`, `::test_with_a_thanos_url_the_route_is_not_reviewed` | fail | pass |
| `::test_without_live_usage_nothing_is_asked` (the six checks' calls unchanged with `none`) | fails (no `usage_grants` parameter) | passes |
| `::test_the_baseline_keeps_every_other_grant` | fails (the ClusterRole's Route rule) | passes |
| `::test_kind_has_no_openshift_monitoring_and_no_grant_for_it` (the decision for kind) | passes | passes |
| `deploy/tests/crc-scripts-test.sh`: the proof stops without the review grant, with a usage finding on CRC, and with CRC not connected | n/a | each stops, with its own message |

Before: the new file on #726's head (`7aa2c553`), with the constants it imports from `core/registry.py` stubbed so that each test runs: 18 failed, 1 passed (kind's). After: 19 passed. Both runs are in the pull request.
