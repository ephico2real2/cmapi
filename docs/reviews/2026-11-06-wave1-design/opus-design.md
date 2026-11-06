> **Status: one of two independent designs for Wave 1 (#94), the base of the arbitration in `README.md`. Where a ruling there differs, the ruling holds.** Nothing here has been applied.

# cmapi Wave 1 (#94): independent design (Opus 5.5)

Written 2026-11-06 from an export of `main` at `9fd230a`. Labels used throughout: **measured** (I ran it, in this directory or a throwaway container; output in `output/exp/`), **read** (a primary source or the repository, cited), **coordinator** (the coordinator's read-only reads of CRC, as given to me), **inferred**, **not measured**. I ran no `oc`, no `crc`, no kind cluster. Nothing here has touched CRC.

Binding additions from the coordinator while this was written, each covered: the correction on trust and the import's memory, the owner's requirement that other realms are not affected (section 13), the database backup (section 14), and no Gitea (decision 5).

## The decisions in one table

| # | Decision | Reason in one line |
|---|---|---|
| 1 | `environments/crc/` holds top-level files applied first, and `reader/` and `realm/` subfolders each applied by name. `render.sh` does not change. Components stay at 4 image placeholders; CRC adds exactly 1, the realm sync's Job | `render.sh`'s checksum glob and `oc apply -f dir` are both non-recursive, so subfolders are ordered steps and outside the checksum |
| 2 | `podman build`, `podman save`, `skopeo copy` from the Mac; digest from `--digestfile` checked against the image stream. Auth file 0600 from the session's token on stdin | `podman push --cert-dir` is not honoured on this Mac (measured and documented), and the machine VM has no CA |
| 3 | `30-trust.yaml` is in Git, holding `ca.crt` of `keycloak/keycloak-tls` only, written by `deploy/crc-trust.sh --write`. `--check` is a TLS handshake against the Route with the file as the only CA, and reads no Secret | In Git, the checksum knows; a rotated CA fails closed and goes through Git |
| 4 | Import from plain YAML with placeholders, with `spec.resources` set; deleted once Done. `realm-sync` is needed. Issuer check in `secrets.sh`, three outcomes, only when about to mint, from the Mac | The operator cannot update a realm, and a kept import can fire again unattended |
| 5 | `delivery.mode: argocd`, `writes: false`, `CMAPI_GIT_PROVIDER=github`, `CMAPI_GIT_URL=https://git-not-configured.invalid`. No Gitea anywhere | Three independent stops; a plan answers 422 before any Git call; the worker has one recurring job, which touches only the database |
| 6 | Reader as YAML in `reader/`, cut to five resources; import Secret by pipe in `deploy/crc-reader-import.sh` | The ClusterRole in `examples/baseline` reads users, identities and more, which no Wave 1 code calls |
| 7 | Edge Routes, Redirect, for api and mockup; no portal Route. Policy unchanged. Prove it blocks as well as admits | A Route that answers proves nothing unless something was blocked |
| 8 | Monitoring moved verbatim (`PrometheusRule` spec equals the chart's, measured). Proof through Thanos Querier's Route, token on stdin | No exec into a shared pod and nothing on an argument list |
| 9 | Realm first and alone, then workloads. Steps, stops and rollback below | Import plus workloads under the operator's default breaks the stop line |
| 10 | Three new test programs, all with cases shown to fail | Below |
| 11 | 576 Mi steady; 768 Mi transient for the import; peak added 672 Mi | From the manifests, by Kubernetes' effective-request rule |
| 12 | Table of harms and guards | Section 12 |

## 1. Files

New under `deploy/`:

```
deploy/manifests/environments/crc/
  00-namespaces.yaml          cmapi, cmapi-imports
  10-env.yaml                 ConfigMap cmapi-env          (in checksum/config)
  20-config.yaml              ConfigMap cmapi-config       (in checksum/config)
  30-trust.yaml               ConfigMap cmapi-trust        (in checksum/config; written by crc-trust.sh)
  40-routes.yaml              Routes cmapi-api, cmapi-mockup
  50-monitoring.yaml          ServiceMonitors, PrometheusRule
  reader/00-cmapi-reader.yaml cmapi-system, SA, token Secret (no value), ClusterRole, ClusterRoleBinding
  realm/10-realm-import.yaml  KeycloakRealmImport cmapi
  realm/20-realm-sync.yaml    Job cmapi-realm-sync         (the 5th image placeholder)
deploy/crc-guard.py           preflight, headroom, check-import, issuer, snapshot, compare, watch, gate, import-wait
deploy/crc-trust.sh           --write, --check, --mac-ca
deploy/crc-image.sh           build and push; prints the reference
deploy/crc-reader-import.sh   the import Secret
deploy/crc-backup.sh          --inspect, backup, --delete
deploy/crc-proof.sh           every proof a browser is not needed for
deploy/crc-rollback.sh        by-name removal
deploy/tests/crc-guard-test.py     guard cases and mutants
deploy/tests/crc-scripts-test.sh   the scripts on stubs
deploy/tests/realm-test.py         the shipped realm on real Keycloak with an LDAP stand-in
docs/13-crc-deployment.md     sections 9, 13 and 14 of this document as the runbook
```

Changed: `deploy/secrets.sh`, `deploy/secrets-test.sh`, `deploy/tests/mutate-secrets.py`, `deploy/kind-test.sh` (one flag), `deploy/render-test.sh`, `deploy/tests/ci-guard.py`, `.github/workflows/ci.yml`, `cmapi/src/cmapi/tools/realm_sync.py`, `cmapi/tests/service/test_plain_manifests.py`, `cmapi/tests/service/test_review_h_tools_migrate.py`, `deploy/manifests/README.md`, `docs/11-existing-identity-services.md`, `build-tracker.md`, `HANDOVER-AND-RESUME.md`. Unchanged and untouched: `deploy/render.sh`, `deploy/release-crc.sh`, `deploy/baseline-crc.sh`, `deploy/environments/crc.yaml`, the charts, all Gitea code (Wave 3 and 7a per the ruling).

How this fits what exists (read: `deploy/render.sh:26-36,66-71`):

- **`config_checksum`** greps `"$1"/*.yaml`, top level only, for `^  name: <cm>$`. `10-env`, `20-config` and `30-trust` are found; `reader/` and `realm/` are never read. Measured in my tree: a changed `realm/10-realm-import.yaml` leaves the checksum alone, and a change to any of the three changes it (`render-test.sh` cases added).
- **`cp -R`** copies the subfolders into `environment/`, and the `find ... sed` fills placeholders at any depth. `grep -rnE` still catches an unfilled one anywhere.
- **`oc apply --server-side -f environment/`** is not recursive, so it applies the top-level files only. `reader/` and `realm/` are each applied by name in their step. Do not use `-R` on `environment/`; the README says so.
- **Image guards.** `render-test.sh:15-18` and `test_plain_manifests.py` count four over `components` plus `environments/kind`. Neither counts `environments/crc`, so both stay at 4 and need no edit, and the guard's text ("a Job on this image is a decision, and changes this number with it") is honoured by adding its own count: exactly one in `environments/crc`, in `realm/20-realm-sync.yaml`, and five filled for crc (measured).
- **A trap in the existing test:** `render-test.sh:37` does `cp -R .../kind .../crc`. Once `environments/crc` exists that nests `crc/kind/` instead of creating it. The line goes.
- **`kubeconform`:** the pinned CRDs catalog has `keycloakrealmimport_v2beta1`, `servicemonitor_v1`, `prometheusrule_v1`, and **no Route** (404, measured). So `-skip Route`, and `test_crc_routes` holds its shape. I validated every other object here against the same pinned schemas with Python's `jsonschema`: 0 errors (measured; the earlier refusal of a local `kubeconform` stands, so I did not run it, and CI's run is the first).

### Files in full

Everything that decides something follows. Each is also a real file under `output/files/`, and is what I tested.

`deploy/manifests/environments/crc/00-namespaces.yaml`:

```yaml
# cmapi exists on CRC (created by hand on 2026-11-05, holding Secret cmapi-ldap-bind); a clean start needs it, and applying it
# adds only the label. cmapi-imports does not exist. The reader's cmapi-system is in reader/. Wave 2's bootstrap set takes these over.
apiVersion: v1
kind: Namespace
metadata:
  name: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
---
apiVersion: v1
kind: Namespace
metadata:
  name: cmapi-imports
  labels: {app.kubernetes.io/part-of: cmapi}
```


`deploy/manifests/environments/crc/10-env.yaml`:

```yaml
# Environment variables the components read through envFrom on CRC. Wave 1 has no Git host: GitHub arrives in Wave 3. The code
# needs a provider kind to start (settings.py defaults to one that is leaving, so it is named here) and a URL; .invalid never
# resolves (RFC 6761), so nothing can leave for a Git host. clusters.yaml has writes: false, so a request stops at 422 first.
# The pods reach Keycloak through its Service: its certificate names keycloak-service.keycloak.svc. Tokens still carry the
# public issuer, in cmapi-config.
apiVersion: v1
kind: ConfigMap
metadata:
  name: cmapi-env
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
data:
  CMAPI_GIT_PROVIDER: github
  CMAPI_GIT_URL: https://git-not-configured.invalid
  CMAPI_GIT_DEFAULT_BRANCH: main
  CMAPI_LOG_LEVEL: INFO
  CMAPI_OIDC_JWKS_URL: https://keycloak-service.keycloak.svc:8443/realms/cmapi/protocol/openid-connect/certs
  CMAPI_KEYCLOAK_ADMIN_URL: https://keycloak-service.keycloak.svc:8443
```

`20-config.yaml`: `output/files/deploy/manifests/environments/crc/20-config.yaml`, 309 lines. Everything from `capacity.yaml` on is byte for byte `environments/kind`'s (measured, and `test_crc_policy_files_are_the_kind_files` keeps it so). What differs, in full:

```yaml
# The instance files the api and the worker read from /etc/cmapi/config (CMAPI_CONFIG_DIR) on CRC. From approval-rules.yaml on,
# every file is byte for byte environments/kind's (test_crc_policy_files_are_the_kind_files).
# Interim, until Wave 5: delivery.mode argocd, so the worker never writes to a cluster, with writes: false on the one cluster, so
# a namespace request stops at 422 cluster-not-writable before any Git call.
apiVersion: v1
kind: ConfigMap
metadata:
  name: cmapi-config
  namespace: cmapi
  labels:
    app.kubernetes.io/part-of: cmapi
data:
  instance.yaml: |
    instance:
      name: nonprod
      displayName: "Non-production (CRC)"
      allowedEnvironments: ["rnd","dev"]
      publicUrl: "https://cmapi-api.apps-crc.testing"
      portalUrl: ""
      auth:
        issuer: "https://keycloak.apps-crc.testing/realms/cmapi"
        audience: "cmapi-nonprod"
      namespaces:
        reservedPatterns: ["ocp-*","kubernetes-*"]
      identity: {"adminClient":"cmapi-directory","automationRoles":["cmapi-onboarding"],"cacheSeconds":900,"directory":"keycloak","requireEmployeeId":true,"requireOnBehalfOf":false}
      git:
        repository: "ephico2real2/cluster-configs-nonprod"
        webUrl: "https://github.com"
      directory: {"prod":{"environments":["prod"],"url":"https://cmapi.ephico2real.com"},"staging":{"environments":["qa","uat"],"url":"https://cmapi-staging.ephico2real.com"}}
      docs: {"enabled":true}
  clusters.yaml: |
    clusters: {"CRC":{"environment":"dev","gitopsPath":"clusters/CRC","labels":{"region":"us-central"},"simulatedCapacity":{"cpu":64,"memory":"256Gi"},"writes":false}}
  integrations.yaml: |
    delivery:
      mode: argocd
      syncTimeout: 10m
      argocd: {"acknowledgeUncontainedController":false,"controllerServiceAccount":"system:serviceaccount:cmapi-argocd:argocd-application-controller","namespace":"cmapi-argocd","rootApplication":"cluster-configs-{clusterId}"}
    syncSignal:
      default: poll
      pollInterval: 10s
    operations:
      engine: builtin
    events:
      publisher: none
    notifier:
```

`30-trust.yaml` is not in my output, because it must hold the real CA, which only `deploy/crc-trust.sh --write` reads. Its generated shape is in the script below. `test_crc_trust_holds_certificates_only` refuses a private key or kind's stand-in.

`deploy/manifests/environments/crc/40-routes.yaml`:

```yaml
# Edge: the router terminates TLS with the cluster's ingress certificate and speaks HTTP to the pod, which serves no TLS.
# Redirect: plain HTTP on 80 goes to HTTPS, so a token is never sent in the clear. spec.host is explicit because the realm's
# redirect URI and instance.yaml's publicUrl name it. targetPort http only: the metrics port is not reachable through a Route.
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: cmapi-api
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
spec:
  host: cmapi-api.apps-crc.testing
  to: {kind: Service, name: cmapi-api}
  port: {targetPort: http}
  tls: {termination: edge, insecureEdgeTerminationPolicy: Redirect}
---
# The standalone mockup: a static page with no API behind it, not the portal, and not evidence that the application works.
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: cmapi-mockup
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
spec:
  host: cmapi-mockup.apps-crc.testing
  to: {kind: Service, name: cmapi-mockup}
  port: {targetPort: http}
  tls: {termination: edge, insecureEdgeTerminationPolicy: Redirect}
```


`deploy/manifests/environments/crc/50-monitoring.yaml`:

```yaml
# From the chart's templates/monitoring.yaml. Scraped by user workload monitoring (enableUserWorkload: true, measured), whose
# namespace the NetworkPolicy allows on 9090. No credential: /metrics has no auth, and the ServiceMonitors name none.
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cmapi-api
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
spec:
  selector:
    matchLabels: {app.kubernetes.io/name: cmapi-api, app.kubernetes.io/component: api}
  endpoints:
    - port: metrics
      path: /metrics
      interval: 30s
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cmapi-worker
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
spec:
  selector:
    matchLabels: {app.kubernetes.io/name: cmapi-worker, app.kubernetes.io/component: worker}
  endpoints:
    - port: metrics
      path: /metrics
      interval: 30s
---
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cmapi
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
spec:
  groups:
    - name: cmapi.alerts
      rules:
        - alert: CmapiHighErrorRate
          expr: |
            sum(rate(cmapi_http_requests_total{status=~"5..", namespace="cmapi"}[5m]))
              / sum(rate(cmapi_http_requests_total{namespace="cmapi"}[5m])) > 0.02
          for: 10m
          labels: {severity: critical}
          annotations: {summary: "cmapi 5xx above 2% of requests for 10 minutes"}
        - alert: CmapiIdpUnavailable
          expr: sum(increase(cmapi_idp_unavailable_total{namespace="cmapi"}[5m])) > 0
          for: 5m
          labels: {severity: critical}
          annotations: {summary: "Callers are getting idp-unavailable (Keycloak signing keys unreachable)"}
        - alert: CmapiGitUnavailable
          expr: |
            sum(rate(cmapi_git_operations_total{result="failure", namespace="cmapi"}[5m]))
              / sum(rate(cmapi_git_operations_total{namespace="cmapi"}[5m])) > 0.20
          for: 5m
          labels: {severity: critical}
          annotations: {summary: "Git host operation failures above 20% for 5 minutes"}
        - alert: CmapiWorkerNotLooping
          # A Running worker whose loop died would pass its probes while every request stalls; absent() is the
          # worker that is gone or never started, which the age alone cannot see (measured with promtool).
          expr: |
            absent(cmapi_worker_last_loop_timestamp_seconds{namespace="cmapi"})
            or
            (time() - max(cmapi_worker_last_loop_timestamp_seconds{namespace="cmapi"})) > 120
          for: 2m
          labels: {severity: critical}
          annotations: {summary: "The cmapi worker loop has not run for 120 seconds"}
        - alert: CmapiClusterUnreachable
          expr: cmapi_cluster_status{status="unreachable", namespace="cmapi"} == 1
          for: 10m
          labels: {severity: warning}
          annotations: {summary: "Cluster {{ $labels.cluster_id }} unreachable for 10 minutes"}
        - alert: CmapiSyncStuck
          expr: cmapi_open_change_requests_oldest_age_seconds{status="sync_failed", namespace="cmapi"} > 0
          for: 5m
          labels: {severity: warning}
          annotations: {summary: "A request is in sync_failed"}
        - alert: CmapiPruneStuck
          expr: cmapi_open_change_requests_oldest_age_seconds{status="awaiting_prune", namespace="cmapi"} > 86400
          for: 5m
          labels: {severity: warning}
          annotations: {summary: "A delete has waited in awaiting_prune for over a day: no confirmation, or a namespace stuck Terminating"}
        - alert: CmapiWorkerBacklog
          expr: sum(cmapi_jobs_pending{namespace="cmapi"}) > 100
          for: 15m
          labels: {severity: warning}
          annotations: {summary: "More than 100 jobs pending for 15 minutes"}
        - alert: CmapiAutoApprovalPaused
          expr: cmapi_auto_approval_paused{namespace="cmapi"} == 1
          for: 24h
          labels: {severity: info}
          annotations: {summary: "The auto-approval kill switch has been on for 24 hours"}
        - alert: CmapiMemoryNearLimit
          expr: cmapi_process_memory_bytes / cmapi_process_memory_limit_bytes > 0.8
          for: 15m
          labels: {severity: warning}
          annotations: {summary: "{{ $labels.component }} above 80% of its memory limit"}
        - alert: CmapiCpuThrottled
          expr: rate(cmapi_process_cpu_throttled_periods_total[5m]) / rate(cmapi_process_cpu_periods_total[5m]) > 0.01
          for: 30m
          labels: {severity: warning}
          annotations: {summary: "{{ $labels.component }} throttled in more than 1% of CPU periods"}
        - alert: CmapiPodRestarting
          expr: increase(kube_pod_container_status_restarts_total{namespace="cmapi", container=~"api|worker"}[15m]) > 0
          labels: {severity: warning}
          annotations: {summary: "A cmapi container restarted in the last 15 minutes"}
```


`deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml`:

```yaml
# The reader baseline as plain YAML: what cmapi needs to read a cluster, and nothing more. From examples/baseline/cmapi-reader-rbac.yaml,
# cut to what the code calls in Wave 1 (core/registry.py's six checks, core/clients/kube.py's WatchCache KINDS, pipeline.workload_counts).
# The identity check needs no rule here: users/~ and selfsubjectreviews are for every authenticated user. Later waves add their own
# rule in their own pull request. The import Secret holding this token is not YAML: deploy/crc-reader-import.sh writes it.
apiVersion: v1
kind: Namespace
metadata:
  name: cmapi-system
  labels: {app.kubernetes.io/part-of: cmapi}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: cmapi-reader
  namespace: cmapi-system
  labels: {app.kubernetes.io/part-of: cmapi}
---
# Holds no value in Git: the token controller fills it on the cluster.
apiVersion: v1
kind: Secret
metadata:
  name: cmapi-reader-token
  namespace: cmapi-system
  labels: {app.kubernetes.io/part-of: cmapi}
  annotations: {kubernetes.io/service-account.name: cmapi-reader}
type: kubernetes.io/service-account-token
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cmapi-reader
  labels: {app.kubernetes.io/part-of: cmapi}
rules:
  - apiGroups: [""]
    resources: [namespaces, resourcequotas, limitranges]
    verbs: [get, list, watch]
  - apiGroups: [""]                      # counted for the delete thresholds (pods > 20, pvcs > 10)
    resources: [pods, persistentvolumeclaims]
    verbs: [list]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cmapi-reader
  labels: {app.kubernetes.io/part-of: cmapi}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: cmapi-reader}
subjects:
  - {kind: ServiceAccount, name: cmapi-reader, namespace: cmapi-system}
```


`deploy/manifests/environments/crc/realm/10-realm-import.yaml`:

```yaml
# Realm cmapi for the existing Keycloak (docs/11), from the chart's templates/keycloak-realm.yaml. The RHBK operator creates it once:
# the import runs --override=false, so an existing realm is left as it is, and this object neither updates nor deletes one. Client
# secrets are ${...} placeholders the import Job reads from Secret cmapi-realm-secrets, written by deploy/secrets.sh; no secret in Git.
# resources: without them the operator's default is requested, 1700Mi with a 2Gi limit (Utils.addResources, whatever the CRD's text
# says about inheriting). 768Mi is the peak measured for this realm under a 1Gi limit, 735 MB, on Keycloak 26.6.4. One CPU at most: starting a JVM beside a
# single keycloak-0 whose liveness probe gives up after 30 s must not take the node's CPUs. Measured at that limit: see docs/13.
# Applied by name, once, by the steps in docs/13; deleted once Done (the operator's guide says to), so it can never run again unattended.
apiVersion: k8s.keycloak.org/v2beta1
kind: KeycloakRealmImport
metadata:
  name: cmapi
  namespace: keycloak
  labels:
    app.kubernetes.io/part-of: cmapi
spec:
  keycloakCRName: keycloak
  resources:
    requests:
      cpu: 100m
      memory: 768Mi
    limits:
      cpu: '1'
      memory: 1Gi
  labels:
    app.kubernetes.io/part-of: cmapi
  placeholders:
    CMAPI_REALM_ADMIN_SECRET:
      secret:
        name: cmapi-realm-secrets
        key: CMAPI_REALM_ADMIN_SECRET
    CMAPI_DIRECTORY_SECRET:
      secret:
        name: cmapi-realm-secrets
        key: CMAPI_DIRECTORY_SECRET
    CMAPI_SVC_PAYMENTS_CI_SECRET:
      secret:
        name: cmapi-realm-secrets
        key: CMAPI_SVC_PAYMENTS_CI_SECRET
    CMAPI_AUTOMATION_SECRET:
      secret:
        name: cmapi-realm-secrets
        key: CMAPI_AUTOMATION_SECRET
  realm:
    realm: cmapi
    displayName: cmapi (CRC)
    enabled: true
    accessTokenLifespan: 300
    ssoSessionIdleTimeout: 28800
    ssoSessionMaxLifespan: 43200
    rememberMe: true
    ssoSessionIdleTimeoutRememberMe: 604800
    ssoSessionMaxLifespanRememberMe: 2592000
    offlineSessionIdleTimeout: 2592000
    offlineSessionMaxLifespanEnabled: true
    offlineSessionMaxLifespan: 7776000
    revokeRefreshToken: true
    refreshTokenMaxReuse: 0
    clientScopes:
    - name: basic
      protocol: openid-connect
      attributes:
        include.in.token.scope: 'false'
        display.on.consent.screen: 'false'
      protocolMappers:
      - name: sub
        protocol: openid-connect
        protocolMapper: oidc-sub-mapper
        config:
          access.token.claim: 'true'
          introspection.token.claim: 'true'
    - name: roles
      protocol: openid-connect
      attributes:
        include.in.token.scope: 'false'
        display.on.consent.screen: 'false'
      protocolMappers:
      - name: client roles
        protocol: openid-connect
        protocolMapper: oidc-usermodel-client-role-mapper
        config:
          multivalued: 'true'
          user.attribute: foo
          access.token.claim: 'true'
          claim.name: resource_access.${client_id}.roles
          jsonType.label: String
    - name: profile
      protocol: openid-connect
      attributes:
        include.in.token.scope: 'true'
        display.on.consent.screen: 'false'
      protocolMappers:
      - name: username
        protocol: openid-connect
        protocolMapper: oidc-usermodel-attribute-mapper
        config:
          user.attribute: username
          claim.name: preferred_username
          jsonType.label: String
          access.token.claim: 'true'
          id.token.claim: 'true'
          userinfo.token.claim: 'true'
      - name: given name
        protocol: openid-connect
        protocolMapper: oidc-usermodel-attribute-mapper
        config:
          user.attribute: firstName
          claim.name: given_name
          jsonType.label: String
          access.token.claim: 'true'
          id.token.claim: 'true'
          userinfo.token.claim: 'true'
      - name: family name
        protocol: openid-connect
        protocolMapper: oidc-usermodel-attribute-mapper
        config:
          user.attribute: lastName
          claim.name: family_name
          jsonType.label: String
          access.token.claim: 'true'
          id.token.claim: 'true'
          userinfo.token.claim: 'true'
    - name: email
      protocol: openid-connect
      attributes:
        include.in.token.scope: 'true'
        display.on.consent.screen: 'false'
      protocolMappers:
      - name: email
        protocol: openid-connect
        protocolMapper: oidc-usermodel-attribute-mapper
        config:
          user.attribute: email
          claim.name: email
          jsonType.label: String
          access.token.claim: 'true'
          id.token.claim: 'true'
          userinfo.token.claim: 'true'
    - name: web-origins
      protocol: openid-connect
      attributes:
        include.in.token.scope: 'false'
        display.on.consent.screen: 'false'
      protocolMappers:
      - name: allowed web origins
        protocol: openid-connect
        protocolMapper: oidc-allowed-origins-mapper
        config:
          access.token.claim: 'true'
    - name: offline_access
      protocol: openid-connect
      attributes:
        include.in.token.scope: 'true'
        display.on.consent.screen: 'true'
    - name: cmapi-identity
      protocol: openid-connect
      attributes:
        include.in.token.scope: 'false'
        display.on.consent.screen: 'false'
      protocolMappers:
      - config:
          access.token.claim: 'true'
          claim.name: employee_id
          id.token.claim: 'false'
          jsonType.label: String
          user.attribute: employeeId
          userinfo.token.claim: 'true'
        name: employee_id
        protocol: openid-connect
        protocolMapper: oidc-usermodel-attribute-mapper
      - config:
          access.token.claim: 'true'
          claim.name: middle_name
          id.token.claim: 'true'
          jsonType.label: String
          user.attribute: middleName
          userinfo.token.claim: 'true'
        name: middle_name
        protocol: openid-connect
        protocolMapper: oidc-usermodel-attribute-mapper
      - config:
          access.token.claim: 'true'
          claim.name: groups
          full.path: 'true'
          id.token.claim: 'false'
          userinfo.token.claim: 'true'
        name: groups
        protocol: openid-connect
        protocolMapper: oidc-group-membership-mapper
    - name: cmapi-audience
      protocol: openid-connect
      attributes:
        include.in.token.scope: 'false'
        display.on.consent.screen: 'false'
      protocolMappers:
      - config:
          access.token.claim: 'true'
          id.token.claim: 'false'
          included.client.audience: cmapi-nonprod
        name: audience
        protocol: openid-connect
        protocolMapper: oidc-audience-mapper
    roles:
      client:
        cmapi-nonprod:
        - name: cmapi-viewer
          description: clusters:read, objects:read, capacity:read, requests:read
        - name: cmapi-onboarding
          description: Create namespaces only. For people and local automation accounts
        - name: cmapi-requester
          description: Onboarding plus change and delete, quotas, service accounts and grants
        - name: cmapi-approver
          description: requests:approve and requests:reject
        - name: cmapi-operator
          description: Requester plus retry, adoption, reports and operations
        - name: cmapi-admin
          description: Operator plus config, cluster onboarding, reload and the kill switch
        - name: cmapi-auditor
          description: Viewer plus events and audit export
        - name: cmapi-approval-relay
          description: approvals:relay for channel integrations
    clients:
    - clientId: cmapi-nonprod
      name: cmapi nonprod API
      enabled: true
      publicClient: false
      bearerOnly: true
      standardFlowEnabled: false
      directAccessGrantsEnabled: false
      serviceAccountsEnabled: false
      defaultClientScopes:
      - basic
      - cmapi-identity
      - cmapi-audience
      - roles
      - profile
      - email
    - clientId: cmapi-portal
      name: cmapi portal
      enabled: true
      publicClient: true
      standardFlowEnabled: true
      directAccessGrantsEnabled: false
      attributes:
        pkce.code.challenge.method: S256
        post.logout.redirect.uris: +
      redirectUris:
      - https://cmapi-portal.apps-crc.testing/*
      - http://localhost:5173/*
      webOrigins:
      - +
      defaultClientScopes:
      - basic
      - cmapi-identity
      - cmapi-audience
      - roles
      - profile
      - email
      - web-origins
    - clientId: cmapi-docs
      name: cmapi Swagger UI
      enabled: true
      publicClient: true
      standardFlowEnabled: true
      directAccessGrantsEnabled: false
      attributes:
        pkce.code.challenge.method: S256
        client.session.idle.timeout: '3600'
        client.session.max.lifespan: '28800'
      redirectUris:
      - https://cmapi-api.apps-crc.testing/docs/oauth2-redirect
      webOrigins:
      - +
      defaultClientScopes:
      - basic
      - cmapi-identity
      - cmapi-audience
      - roles
      - profile
      - email
      - web-origins
    - clientId: cmapi-cli
      name: cmapi CLI (device flow)
      enabled: true
      publicClient: true
      standardFlowEnabled: false
      directAccessGrantsEnabled: false
      attributes:
        oauth2.device.authorization.grant.enabled: 'true'
      defaultClientScopes:
      - basic
      - cmapi-identity
      - cmapi-audience
      - roles
      - profile
      - email
      optionalClientScopes:
      - offline_access
    - clientId: cmapi-automation
      name: Local automation accounts (bot-user)
      enabled: true
      publicClient: false
      secret: ${CMAPI_AUTOMATION_SECRET}
      standardFlowEnabled: false
      directAccessGrantsEnabled: true
      defaultClientScopes:
      - basic
      - cmapi-identity
      - cmapi-audience
      - roles
      - profile
      - email
    - clientId: svc-payments-ci
      name: Example pipeline client
      enabled: true
      publicClient: false
      secret: ${CMAPI_SVC_PAYMENTS_CI_SECRET}
      standardFlowEnabled: false
      directAccessGrantsEnabled: false
      serviceAccountsEnabled: true
      defaultClientScopes:
      - basic
      - cmapi-identity
      - cmapi-audience
      - roles
      - profile
      - email
    - clientId: cmapi-directory
      name: cmapi directory (read-only admin API)
      enabled: true
      publicClient: false
      secret: ${CMAPI_DIRECTORY_SECRET}
      standardFlowEnabled: false
      directAccessGrantsEnabled: false
      serviceAccountsEnabled: true
      defaultClientScopes:
      - basic
      - roles
    - clientId: cmapi-realm-admin
      name: cmapi realm sync (realm-management)
      enabled: true
      publicClient: false
      secret: ${CMAPI_REALM_ADMIN_SECRET}
      standardFlowEnabled: false
      directAccessGrantsEnabled: false
      serviceAccountsEnabled: true
      defaultClientScopes:
      - basic
      - roles
    users:
    - username: service-account-cmapi-realm-admin
      enabled: true
      serviceAccountClientId: cmapi-realm-admin
      clientRoles:
        realm-management:
        - realm-admin
    - username: service-account-cmapi-directory
      enabled: true
      serviceAccountClientId: cmapi-directory
      clientRoles:
        realm-management:
        - view-users
        - query-users
    groups:
    - name: cmapi
      path: /cmapi
      subGroups:
      - name: cmapi-auditors
        path: /cmapi/cmapi-auditors
        clientRoles:
          cmapi-nonprod:
          - cmapi-auditor
      - name: cmapi-onboarding
        path: /cmapi/cmapi-onboarding
        clientRoles:
          cmapi-nonprod:
          - cmapi-onboarding
      - name: cmapi-platform-admins
        path: /cmapi/cmapi-platform-admins
        clientRoles:
          cmapi-nonprod:
          - cmapi-admin
      - name: cmapi-platform-leads
        path: /cmapi/cmapi-platform-leads
        clientRoles:
          cmapi-nonprod:
          - cmapi-approver
      - name: cmapi-platform-operators
        path: /cmapi/cmapi-platform-operators
        clientRoles:
          cmapi-nonprod:
          - cmapi-operator
          - cmapi-approver
      - name: cmapi-prod-approvers
        path: /cmapi/cmapi-prod-approvers
        clientRoles:
          cmapi-nonprod:
          - cmapi-approver
      - name: cmapi-qa-leads
        path: /cmapi/cmapi-qa-leads
        clientRoles:
          cmapi-nonprod:
          - cmapi-approver
      - name: cmapi-requesters
        path: /cmapi/cmapi-requesters
        clientRoles:
          cmapi-nonprod:
          - cmapi-requester
      - name: cmapi-uat-leads
        path: /cmapi/cmapi-uat-leads
        clientRoles:
          cmapi-nonprod:
          - cmapi-approver
      - name: cmapi-viewers
        path: /cmapi/cmapi-viewers
        clientRoles:
          cmapi-nonprod:
          - cmapi-viewer
```


`deploy/manifests/environments/crc/realm/20-realm-sync.yaml`:

```yaml
# What the import cannot change once the realm exists: the user profile, group-to-role mappings, LDAP federation (read-only) and local
# test users. Signs in as the realm's own cmapi-realm-admin, never the shared instance's master admin; the only other image placeholder
# outside components/. One try and no retries: a Keycloak that is down is not helped by a Job hammering it. Rerun by deleting it by name:
# a Job's template is immutable. requireSync: a federation that did not sync fails the Job, not only a log line.
apiVersion: batch/v1
kind: Job
metadata:
  name: cmapi-realm-sync
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi, app.kubernetes.io/name: cmapi-realm-sync, app.kubernetes.io/component: realm-sync}
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 600
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels: {app.kubernetes.io/part-of: cmapi, app.kubernetes.io/name: cmapi-realm-sync, app.kubernetes.io/component: realm-sync}
    spec:
      restartPolicy: Never
      serviceAccountName: cmapi-jobs
      securityContext:
        runAsNonRoot: true
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: sync
          image: ghcr.io/ephico2real2/cmapi@sha256:DIGEST
          imagePullPolicy: IfNotPresent
          command: [cmapi-tools, realm-sync]
          env:
            - {name: CMAPI_REALM_ISSUER, value: "https://keycloak.apps-crc.testing/realms/cmapi"}
            - {name: CMAPI_REALM_ADMIN_URL, value: "https://keycloak-service.keycloak.svc:8443"}
            - name: CMAPI_REALM_ADMIN_CLIENT_SECRET
              valueFrom: {secretKeyRef: {name: cmapi-keycloak, key: realmAdminClientSecret}}
            - {name: CMAPI_REALM_AUDIENCE, value: cmapi-nonprod}
            - name: CMAPI_REALM_GROUPS
              value: '{"cmapi-auditors":["cmapi-auditor"],"cmapi-onboarding":["cmapi-onboarding"],"cmapi-platform-admins":["cmapi-admin"],"cmapi-platform-leads":["cmapi-approver"],"cmapi-platform-operators":["cmapi-operator","cmapi-approver"],"cmapi-prod-approvers":["cmapi-approver"],"cmapi-qa-leads":["cmapi-approver"],"cmapi-requesters":["cmapi-requester"],"cmapi-uat-leads":["cmapi-approver"],"cmapi-viewers":["cmapi-viewer"]}'
            - {name: CMAPI_REALM_TEST_USERS, value: "true"}
            - name: CMAPI_REALM_LDAP
              value: '{"bindSecret":"cmapi-ldap-bind","connectionUrl":"ldaps://ldaps-ldap-testing.apps-crc.testing:443","employeeIdAttribute":"uidNumber","enabled":true,"groupsDn":"ou=Groups,dc=ephico2real,dc=com","groupsFilter":"(cn=cmapi-*)","requireSync":true,"usersDn":"ou=People,dc=ephico2real,dc=com"}'
            - {name: CMAPI_CA_BUNDLE, value: /etc/cmapi/ca/ca-bundle.crt}
          envFrom:
            - secretRef: {name: cmapi-test-users}
            - secretRef: {name: cmapi-ldap-bind}
          securityContext:
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          resources:
            requests: {cpu: 50m, memory: 96Mi}
            limits: {cpu: 500m, memory: 256Mi}
          volumeMounts:
            - {name: trust, mountPath: /etc/cmapi/ca, readOnly: true}
      volumes:
        - name: trust
          projected:
            sources:
              - configMap:
                  name: cmapi-trust
                  items: [{key: ca-bundle.crt, path: ca-bundle.crt}]
```


## 2. Image

**How it is built and pushed.** `deploy/crc-image.sh`: build with `podman` as `localhost/cmapi:sha-<commit>`, `podman save --format oci-archive` to a 0700 temp dir, then `skopeo copy` from the Mac to the registry route.

Why not `podman push` (`release-crc.sh`'s way): this Mac's `podman` is a remote client. Its documentation says of `--cert-dir`: "This option is not available with the remote Podman client, including Mac and Windows" (read, podman-push.1). Measured against a local TLS registry with its CA in the cert dir: `podman push --cert-dir` is accepted and then fails with a TLS error from inside the VM, and the VM's `/etc/containers/certs.d` is empty. Adding a CA inside the VM would work, but `skopeo` needs no change anywhere: measured, same registry, `skopeo copy --dest-cert-dir` rc 0 in 6 s for the 155 MB archive, `--digestfile` equal to the registry's digest, the `org.opencontainers.image.revision` label preserved, and a wrong CA refused with a certificate error. `skopeo` 1.24.1 is on this Mac. `TLS verification` stays on against the ingress CA from `default-ingress-cert`, since the registry route is reencrypt with the router's certificate (coordinator).

**No credential on a command line, no `gh` token.** `oc whoami -t` is piped into Python, which writes an auth file created 0600 inside the 0700 directory, passed to `skopeo` by path, removed at exit. The test proves the token never reaches an argument. `release-crc.sh:73` has `-p "$(oc whoami -t)"`, a token on an argument list; it is the chart's path and leaves with the charts, and is not reused.

**Digest.** `--digestfile`, compared with `oc get istag cmapi:<tag> -o jsonpath={.image.metadata.name}`; a difference stops the script. Push creates the image stream `cmapi` in namespace `cmapi` (the coordinator confirmed kubeadmin may).

**Pull.** Pods use `image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:...`. A service account in the namespace pulls from its own namespace through the default `system:image-pullers` binding, and the generated dockercfg is attached to the SA (coordinator: those Secrets exist in `cmapi`; inferred for new SAs). One race guarded: admission copies an SA's `imagePullSecrets` into a pod when the pod is created, so a pod created before the controller has filled them would never get them (inferred). So the SAs are applied first and the run waits for the field (step 8).

**`render.sh`** takes it unchanged: its regex already allows the internal registry (`render.sh:37`). `IMAGE=$(deploy/crc-image.sh | tail -1); deploy/render.sh crc "$IMAGE"`.

`deploy/crc-image.sh`:

```bash
#!/usr/bin/env bash
# deploy/crc-image.sh: builds the cmapi image from this commit outside the cluster and pushes it to CRC's internal registry, printing as its last
# line the reference render.sh takes: image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:<digest>. skopeo pushes, because it runs on
# this Mac: podman here is a remote client, so its --cert-dir is not honoured on push and the machine's VM does not trust the route's CA (measured).
# The credential is the current oc session's token, written once to a 0600 file in a 0700 directory removed at exit, passed by path; never an argument,
# and no gh token or GHCR credential is involved. TLS verification stays on, against the ingress CA. An existing sha-<commit> tag is immutable:
# it is reused when its label names this commit, and refused otherwise.
set -euo pipefail
cd "$(dirname "$0")/.."
OC=${CMAPI_OC:-oc}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
INTERNAL=image-registry.openshift-image-registry.svc:5000/cmapi/cmapi
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "ERROR: the working tree has uncommitted changes; the image must name one commit" >&2; exit 1; }
COMMIT=$(git rev-parse --short=10 HEAD); TAG=sha-$COMMIT
VERSION=$(sed -n 's/^version = "\(.*\)"$/\1/p' cmapi/pyproject.toml | head -1)
existing=$(oc_ get istag "cmapi:$TAG" -n cmapi --ignore-not-found -o 'jsonpath={.image.metadata.name} {.image.dockerImageMetadata.Config.Labels.org\.opencontainers\.image\.revision}')
if [ -n "$existing" ]; then
  [ "${existing#* }" = "$COMMIT" ] || { echo "ERROR: cmapi:$TAG in the registry is labelled ${existing#* }, not $COMMIT" >&2; exit 1; }
  echo "$TAG is already in the registry, labelled $COMMIT" >&2
  echo "$INTERNAL@${existing%% *}"; exit 0
fi
W=$(mktemp -d); chmod 700 "$W"; trap 'rm -rf "$W"' EXIT
HOST=$(oc_ get route default-route -n openshift-image-registry -o 'jsonpath={.spec.host}')
mkdir "$W/certs"
oc_ get cm default-ingress-cert -n openshift-config-managed -o 'jsonpath={.data.ca-bundle\.crt}' >"$W/certs/ca.crt"
grep -q 'BEGIN CERTIFICATE' "$W/certs/ca.crt" || { echo "ERROR: no ingress CA read from the cluster" >&2; exit 1; }
# Token on stdin, file created 0600 before a byte is written.
oc_ whoami -t | python3 -c 'import base64,json,os,sys
fd=os.open(sys.argv[2],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
os.write(fd,json.dumps({"auths":{sys.argv[1]:{"auth":base64.b64encode(("unused:"+sys.stdin.read().strip()).encode()).decode()}}}).encode())' "$HOST" "$W/auth.json"
podman build --platform linux/amd64 --build-arg "GIT_COMMIT=$COMMIT" --build-arg "BUILD_VERSION=$VERSION" -t "localhost/cmapi:$TAG" -f cmapi/Containerfile cmapi >&2
built=$(podman image inspect "localhost/cmapi:$TAG" --format '{{index .Labels "org.opencontainers.image.revision"}}')
[ "$built" = "$COMMIT" ] || { echo "ERROR: the image is labelled $built, not $COMMIT" >&2; exit 1; }
podman save --format oci-archive -o "$W/image.tar" "localhost/cmapi:$TAG" >/dev/null
skopeo copy -q --dest-cert-dir "$W/certs" --dest-authfile "$W/auth.json" --digestfile "$W/digest" "oci-archive:$W/image.tar" "docker://$HOST/cmapi/cmapi:$TAG" >&2
digest=$(cat "$W/digest")
registry=$(oc_ get istag "cmapi:$TAG" -n cmapi -o 'jsonpath={.image.metadata.name}')
[ "$digest" = "$registry" ] || { echo "ERROR: pushed $digest, the image stream says $registry" >&2; exit 1; }
echo "$INTERNAL@$digest"
```


## 3. Trust

**What pods need.** `grep` of the service: `CMAPI_OIDC_JWKS_URL` and `CMAPI_KEYCLOAK_ADMIN_URL` go to `keycloak-service.keycloak.svc:8443`, whose certificate is from `enterprise-ca` and names that host (coordinator). No Wave 1 pod calls an edge Route. So the bundle holds one CA: `ca.crt` of `keycloak/keycloak-tls`. The ingress CA that `crc.yaml:93-95` and `release-crc.sh:109-110` added is left out, because nothing in a pod needs it, and every extra CA is one more thing that can rotate. Since Keycloak's Route is passthrough, even a pod using the Route would see the same certificate. An external database's CA is added with `--extra-ca`, as `docs/12` line 44 asks; CNPG's in-cluster connection does not use the bundle (#91 stays open).

**From the cluster, into Git.** `crc-trust.sh --write` runs once, read-only, and the result is committed. It asks for one key with a client-side jsonpath: `oc get secret keycloak-tls -n keycloak -o 'jsonpath={.data.ca\.crt}'`. **Honest limit:** the API has no field filter for a Secret, so `tls.key` reaches `oc`'s memory in that one call. It is not printed, written or logged, and the test asserts that no `-o yaml` or `-o json` is used. That is why `--write` is a one-time step, and why `--check` does not read the Secret at all.

**The checksum.** A bundle living only on the cluster (the injected `config.openshift.io/inject-trusted-cabundle` ConfigMap, or a `render.sh` that reads the cluster) changes behind `checksum/config`. In Git it cannot. The CA expires in 2036 (coordinator). If it rotates anyway:

1. Pods fail closed: JWKS fetches fail, cached keys keep verifying (`auth.py:60-77`), an unknown `kid` is 503 `idp-unavailable`, and `CmapiIdpUnavailable` fires. Verification is never off.
2. `crc-trust.sh --check` fails: it is a real handshake with the file as the only CA. It is the run's first step.
3. `--write`, commit, render: the checksum changes in both Deployments, so applying the environment then the components restarts them.

Argo CD in Wave 5 syncs a rendered tree built in CI with no cluster access, which also requires the file in Git. It is a public certificate and is acceptable in a public repository.

**The Mac's checks.** `crc-trust.sh --mac-ca FILE` writes the bundle of both CAs: that CA for `keycloak.apps-crc.testing` (passthrough) and `default-ingress-cert` for the edge and reencrypt Routes under `apps-crc.testing`. `export CMAPI_CRC_CA=FILE`; every `curl --cacert "$CMAPI_CRC_CA"` and the guard's Python use it. The coordinator confirmed `curl --cacert` works with the CA.

**Python 3.14's stricter default, measured:** `ssl.create_default_context` refused a plain `openssl` CA chain that `curl` accepted, because Python 3.13 on sets `VERIFY_X509_STRICT`. The guard clears that one flag and keeps the hostname and chain checks; the mutant "verification off" is killed by the test with a certificate from another CA.

**Chrome.** Measured: `security find-certificate -c` finds neither `LDAP Enterprise Root CA` nor `ingress-operator` on this Mac, so Chrome will refuse these sites. Clicking through is TLS verification off. So the CAs go into the login keychain, as an **owner's step**, since macOS asks for the password: `security add-trusted-cert -r trustRoot -p ssl -k ~/Library/Keychains/login.keychain-db <pem>`, one per CA, and `security delete-certificate -Z <sha1> ~/Library/Keychains/login.keychain-db` when Wave 1's screenshots are done. Not measured: I did not change this Mac's trust. A CA trusted machine-wide can mint for any site, and both keys live on a test cluster, which is why it comes out again.

`deploy/crc-trust.sh`:

```bash
#!/usr/bin/env bash
# deploy/crc-trust.sh: the CA the pods need, from the cluster into the file checksum/config hashes.
#   --write [--extra-ca FILE]  reads ca.crt from Secret keycloak/keycloak-tls and writes environments/crc/30-trust.yaml. Commit the result.
#                              --extra-ca appends a public CA, an external database's (docs/12).
#   --check                    the file still verifies Keycloak: a real TLS handshake against the Route, with the file as the only CA.
#                              Reads no Secret. Fails on a rotated CA, so the fix goes through Git and the checksum restarts the pods.
#   --mac-ca OUT               writes the bundle this Mac's checks use: that CA (Keycloak's Route is passthrough) and the ingress CA (edge Routes).
# Public certificates only. keycloak-tls also holds tls.key: only the one key is ever asked for, nothing else is written or printed. The API
# has no field filter for a Secret, so the object reaches oc's memory; that is why --write is a one-time step and --check reads no Secret.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/manifests/environments/crc/30-trust.yaml
OC=${CMAPI_OC:-oc}
KEYCLOAK=${CMAPI_KEYCLOAK_URL:-https://keycloak.apps-crc.testing}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
# bundle_of FILE: the PEM blocks of ca-bundle.crt in a trust file.
bundle_of() { sed -n 's/^    //p' "$1"; }
# require_certs: stdin must be PEM certificates, each a CA, and no private key.
require_certs() {
  local pem n; pem=$(cat)
  case "$pem" in *"PRIVATE KEY"*) echo "ERROR: a private key in what should be public certificates" >&2; exit 1;; esac
  n=$(printf '%s\n' "$pem" | grep -c 'BEGIN CERTIFICATE' || true)
  [ "$n" -ge 1 ] || { echo "ERROR: no certificate" >&2; exit 1; }
  printf '%s\n' "$pem" | openssl x509 -noout -text 2>/dev/null | grep -q 'CA:TRUE' || { echo "ERROR: the first certificate is not a CA" >&2; exit 1; }
  printf '%s\n' "$pem"
}
write() {
  local extra=$1 pem
  pem=$(oc_ get secret keycloak-tls -n keycloak -o 'jsonpath={.data.ca\.crt}' | base64 -d)
  pem=$(printf '%s\n' "$pem" | require_certs)
  if [ -n "$extra" ]; then
    # Its own assignment, or set -e would not see require_certs refuse.
    local more; more=$(require_certs <"$extra"); pem=$(printf '%s\n%s\n' "$pem" "$more")
  fi
  { cat <<'HEAD'
# Generated by deploy/crc-trust.sh --write, from Secret keycloak/keycloak-tls key ca.crt (ClusterIssuer enterprise-ca). Public certificates only.
# In Git on purpose: render.sh's checksum/config hashes this file, so a new CA restarts the api and the worker. A bundle kept only on the cluster
# would change behind that checksum. deploy/crc-trust.sh --check says when this file no longer verifies Keycloak.
apiVersion: v1
kind: ConfigMap
metadata:
  name: cmapi-trust
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
data:
  ca-bundle.crt: |
HEAD
    printf '%s\n' "$pem" | sed 's/^/    /'; } >"$OUT.tmp"
  mv "$OUT.tmp" "$OUT"
  echo "wrote $OUT: $(grep -c 'BEGIN CERTIFICATE' "$OUT") certificate(s), $(printf '%s\n' "$pem" | openssl x509 -noout -subject -enddate | tr '\n' ' ')"
}
check() {
  local t rc=0; t=$(mktemp); trap 'rm -f "$t"' RETURN
  bundle_of "$OUT" >"$t"
  code=$(curl -sS -m 15 --cacert "$t" -o /dev/null -w '%{http_code}' "$KEYCLOAK/realms/master") || rc=$?
  [ "$rc" = 0 ] && [ "$code" = 200 ] || { echo "ERROR: $OUT does not verify $KEYCLOAK (curl rc $rc, HTTP ${code:-none}). If the CA rotated: deploy/crc-trust.sh --write, commit, render, apply" >&2; return 1; }
  echo "30-trust.yaml verifies $KEYCLOAK"
}
mac_ca() {
  local out=$1
  ( umask 077; { bundle_of "$OUT"; oc_ get cm default-ingress-cert -n openshift-config-managed -o 'jsonpath={.data.ca-bundle\.crt}'; } >"$out" )
  [ "$(grep -c 'BEGIN CERTIFICATE' "$out")" -ge 2 ] || { echo "ERROR: $out does not hold both CAs" >&2; exit 1; }
  echo "wrote $out"
}
case "${1:-}" in
  --write) if [ "${2:-}" = --extra-ca ]; then write "${3:?file}"; else write ""; fi ;;
  --check) check ;;
  --mac-ca) mac_ca "${2:?output file}" ;;
  *) sed -n '2,8p' "$0" >&2; exit 2 ;;
esac
```


## 4. Realm

**Built without a secret in Git.** `realm/10-realm-import.yaml` is the chart's realm unchanged (measured: `spec.realm` equals `helm template`'s output for `crc.yaml`), with client secrets as `${CMAPI_*}` placeholders and `spec.placeholders` pointing at Secret `cmapi-realm-secrets`, written by `secrets.sh`. Measured: no secret value in the import's log.

**What the operator does (read: `KeycloakRealmImportJobDependentResource.java`, `KeycloakRealmImportController.java`, `Utils.java`, tag 26.6.7; the controller's restart behaviour is the same at `26.6.9-redhat2`. RHBK's 26.6.7 source is not public to me, so that it matches is inferred).**

- A Job named after the CR, `cmapi`, and a Secret `keycloak-cmapi-realm` holding the realm JSON (placeholders unexpanded), both garbage-collected with the CR (`:59`, `SecretDependentResource:42`).
- The Job's pod template is the Keycloak StatefulSet's, with `kc.sh --verbose import --file=... --override=false`, `cache=local` ("The Job should not connect to the cache", `:102`), no probes, `restartPolicy: Never`.
- **No deadline, TTL or `backoffLimit`** is set in `buildJob` (`:124-142`), so a Pending pod waits for ever and a failing Job retries up to Kubernetes' default of six. This is what lets a Job sit 6.5 days (coordinator); the CR has no field to change it (`KeycloakRealmImportSpec`: `keycloakCRName`, `realm`, `resources`, `placeholders`, `labels`).
- **Memory: the CRD's text is wrong about this.** It says "If not specified, the value is inherited from the Keycloak CR". The code, `Utils.addResources:83-97`, fills an unset request and limit from the operator's own default, `kc.operator.keycloak.resources.requests.memory=1700Mi`, `limits=2Gi` (`application.properties:15-16`). That is the coordinator's 1700Mi, and why it differs from `keycloak-0`'s own 1Gi request. **So `spec.resources` controls it, and we set it.** The field is in the pinned catalog's schema (measured); that RHBK serves it is the first thing the preflight checks (`oc explain`, then `--dry-run=server`).
- `status` reads `HasErrors` at the first failed pod (`:139-141`), while the Job may go on trying. So the wait withdraws on `HasErrors`.

**How much it needs, measured** with `quay.io/keycloak/keycloak:26.6` (26.6.4, the newest image here; `26.6.7` is not on quay), the shipped realm, the Job's exact arguments, as a second process on a live server's PostgreSQL:

| Limit | rc | Time | Peak |
|---|---|---|---|
| 512 MB | 0 | 34 s | about 497 MB |
| 1 GB, rerun over the existing realm | 0, `Realm 'cmapi' already exists. Import skipped` | 31 s | about 735 MB |
| 1 GB and 1 CPU | 0 | 79 s | not sampled |

So: `requests: {cpu: 100m, memory: 768Mi}`, `limits: {cpu: "1", memory: 1Gi}`. The request is the measured peak, not an understatement that lies to the scheduler. If RHBK's image differs, the Job is killed at 1Gi, `HasErrors` shows, and the wait withdraws it; then the fallback is to delete the `resources` block, needing 1700 Mi, which fits alone (section 11).

**Rerunning.** Applying the same import against an existing realm changes nothing (measured). But the run never does: step 13 stops unless the issuer says absent.

**Removing it, and when: once Done, by name.** The operator's guide: "Once the realm is imported you should delete the Realm Import CR as that will cleanup the associated Kubernetes Job and Pod resources", and "The Realm Import CR only supports creation of new realms and does not update or delete those" (read, `realm-import.adoc:16-20`). Deleting takes the Job, pod and `keycloak-cmapi-realm`; the realm stays, because no code path in the controller calls Keycloak. Deleting also means that if the completed Job ever went away, the controller could not start the import again unattended (`:117-119` creates a Job when none exists). This reverses "keep the import while the realm exists" in `secrets.sh:17-18`, which ruling 7's issuer check makes unnecessary. The chart kept it, and the other projects keep theirs; that is theirs to decide.

**`realm-sync`: needed in Wave 1.** The import cannot carry what must be able to change, and the issue's proofs need all of it:

- User profile `employeeId` and `middleName`: Keycloak 24 and later drops undeclared attributes, so `employee_id` would never reach a token, and `requireEmployeeId: true` would refuse a person's write.
- LDAP federation, required for the proof. It could go in the import through a placeholder, but a wrong URL then means deleting the realm.
- Test users, for a sign-in with no directory password.

What the chart's Job did and what moves: `templates/jobs.yaml:53-102` moves, with the `cmapi-realm-sync` name, `cmapi-jobs`, its env. **Changed:** one try (`backoffLimit: 0`, not 20) since a Keycloak that is down is not helped by a Job hammering it; a deadline; the Secrets not optional; the config volume dropped, since `realm_sync.py` reads none; `requireSync`. `git-bootstrap` does not move.

**A defect found by running it, fixed here.** `realm_sync.py:189` accepts 200, 400 and 500 from the full sync and exits 0. Worse, measured on 26.6.4: **a directory it cannot reach answers 200 with zero counts**, so a status check would pass too. `requireSync` in the Job's `CMAPI_REALM_LDAP` makes the Job fail unless `added + updated > 0` and `failed` is 0, or if the bind credential is absent. The old behaviour stands without the flag. File this as a bug with its test.

**Measured end to end on real Keycloak 26.6.4 and an OpenLDAP stand-in, with the shipped files (`deploy/tests/realm-test.py`, all 24 cases pass):** import beside a live server, no restart, the new realm served at once; other realms' keys unchanged; sync twice; `john.doe` signs in through LDAP; the token has `iss` `https://keycloak.apps-crc.testing/realms/cmapi` though it was requested on another host, `aud` `cmapi-nonprod`, `employee_id` `10001` from `uidNumber`, `groups` `["/cmapi/cmapi-requesters"]` with a non-`cmapi-*` group filtered out, and role `cmapi-requester`. This is the first time federation has been exercised. **Not** RHBK, the real directory, or `ldaps` through the Route.

**Ruling 7: the issuer check.**

- **Where:** in `secrets.sh`, in the `generate` branch only, ahead of the first write. Every other verdict mints nothing, and needs no Keycloak (case 11i).
- **From where:** the Mac, through the Route, with `--ca-file`. No credential.
- **Outcomes:** `present` is 200 with `realm` equal to the issuer's last segment: stop, a realm exists whose client secrets nobody here knows. `absent` is 404 with exactly `{"error":"Realm does not exist"}` (measured body; the coordinator measured 404 on CRC): go on. **Everything else stops:** a timeout, a certificate failure, a router's 503 during a restart, a 404 that is not Keycloak's, a 200 for another realm. "Could not tell" never mints.
- **Cannot be forgotten:** `--issuer` or `--no-issuer-check` is required, so CRC cannot skip it by leaving a flag off. `kind-test.sh` and the secrets cases pass `--no-issuer-check`.
- **Keycloak down on a first run:** `secrets.sh` stops, having written nothing. Run it again when Keycloak answers. On a later run it does not ask, since nothing would be minted.

**Measured:** 30 of 30 mutants killed by `mutate-secrets.py` on the stub, the 22 existing and 8 new, including "any 404 reads as absent", "a curl failure reads as absent" and "the issuer asked after the first write".

**The image guard's count:** as in section 1: 4 unchanged, plus 1 in `environments/crc`, asserted separately.

The exact changes:

`patches/secrets.sh.diff`:

```diff
--- a/deploy/secrets.sh
+++ b/deploy/secrets.sh
@@ -1,8 +1,9 @@
 #!/usr/bin/env bash
 # deploy/secrets.sh: the Secrets plain YAML cannot generate. Idempotent. Never rotates, never prints a value, never passes
 # one as an argument.
-#   deploy/secrets.sh [--namespace cmapi] [--realm-namespace keycloak] [--kubectl "oc --kubeconfig=..."]
-#                     [--github-app-key FILE --github-app-id N --github-installation-id N] [--no-ldap-bind]
+#   deploy/secrets.sh (--issuer URL [--ca-file FILE] | --no-issuer-check) [--namespace cmapi] [--realm-namespace keycloak]
+#                     [--kubectl "oc --kubeconfig=..."] [--github-app-key FILE --github-app-id N --github-installation-id N]
+#                     [--no-ldap-bind] [--test-users]
 # The realm keeps the values it first imported and an import never overwrites them, so the copy in the Keycloak namespace
 # (cmapi-realm-secrets) is the authority for the four client secrets in cmapi-keycloak:
 #  - both copies absent and no realm import: generate one set, write the realm's copy first, then ours;
@@ -14,15 +15,22 @@
 # cmapi-github-app is validated (appId, installationId, privateKey) and never replaced; a missing one is written from the
 # key file. Written as the deployment design (docs/reviews/2026-11-05-deployment-design.md, D4) decided, from Opus's
 # script with Codex's two checks.
-# A limit: the realm is only known through its import. Deleting KeycloakRealmImport cmapi and both Secrets while the realm
-# stays looks like a first install and mints values the realm refuses; keep the import while the realm exists.
+# Before anything is minted the realm itself is asked, with no credential and with TLS verified: GET <issuer>. Keycloak's own 404 is
+# the only "absent". A 200 stops the run: a realm exists whose client secrets nobody here knows. Anything else (a timeout, a bad
+# certificate, a router's 503 while Keycloak restarts, a 404 that is not Keycloak's) stops it too: "could not tell" is not "no realm".
+# --no-issuer-check is for a cluster with no Keycloak (kind); nothing defaults to it, so CRC cannot skip this by forgetting a flag.
+# --test-users writes cmapi-test-users once (ola, amy, opal, bot-user), for the realm sync; it is never rotated.
 set -euo pipefail
-NS=cmapi; REALM_NS=keycloak; KEY=; APP_ID=; INST_ID=; KUBECTL=oc; LDAP_BIND=true
+NS=cmapi; REALM_NS=keycloak; KEY=; APP_ID=; INST_ID=; KUBECTL=oc; LDAP_BIND=true; ISSUER=; CA_FILE=; ISSUER_CHECK=true; TEST_USERS=false
 while [ $# -gt 0 ]; do case "$1" in
   --namespace) NS=$2; shift 2;; --realm-namespace) REALM_NS=$2; shift 2;; --kubectl) KUBECTL=$2; shift 2;;
   --github-app-key) KEY=$2; shift 2;; --github-app-id) APP_ID=$2; shift 2;; --github-installation-id) INST_ID=$2; shift 2;;
   --no-ldap-bind) LDAP_BIND=false; shift;;
+  --issuer) ISSUER=$2; shift 2;; --ca-file) CA_FILE=$2; shift 2;; --no-issuer-check) ISSUER_CHECK=false; shift;;
+  --test-users) TEST_USERS=true; shift;;
   *) echo "unknown argument $1" >&2; exit 2;; esac; done
+if [ "$ISSUER_CHECK" = true ] && [ -z "$ISSUER" ]; then echo "ERROR: --issuer is required (or --no-issuer-check on a cluster with no Keycloak)" >&2; exit 2; fi
+if [ -n "$CA_FILE" ] && [ ! -r "$CA_FILE" ]; then echo "ERROR: cannot read the CA file $CA_FILE" >&2; exit 2; fi
 # shellcheck disable=SC2086  # KUBECTL may carry --kubeconfig
 kc() { $KUBECTL "$@"; }
 PAIRS="realmAdminClientSecret:CMAPI_REALM_ADMIN_SECRET directoryClientSecret:CMAPI_DIRECTORY_SECRET svcPaymentsCiSecret:CMAPI_SVC_PAYMENTS_CI_SECRET automationClientSecret:CMAPI_AUTOMATION_SECRET"
@@ -42,6 +50,21 @@
   fi
   [ -n "$out" ]
 }
+# issuer_state: "present", "absent", or a reason it cannot tell, for the realm at $ISSUER. --cacert only adds what is verified against; TLS is never off.
+issuer_state() {
+  local body code rc=0
+  body=$(mktemp)
+  code=$(curl -sS -m 15 ${CA_FILE:+--cacert "$CA_FILE"} -o "$body" -w '%{http_code}' "$ISSUER" 2>/dev/null) || rc=$?
+  if [ "$rc" -ne 0 ]; then rm -f "$body"; echo "no answer (curl rc $rc)"; return; fi
+  BODY="$body" CODE="$code" REALM="${ISSUER##*/}" python3 -c 'import json,os
+try: d=json.load(open(os.environ["BODY"]))
+except ValueError: d=None
+c=os.environ["CODE"]
+if c=="200" and isinstance(d,dict) and d.get("realm")==os.environ["REALM"]: print("present")
+elif c=="404" and d=={"error":"Realm does not exist"}: print("absent")
+else: print("HTTP "+c+" that is neither a realm document nor Keycloak'"'"'s own 404")'
+  rm -f "$body"
+}
 # apply_secret NS NAME: stdin is "key base64value" lines. The document goes to kubectl on stdin, so no value reaches an
 # argument list or a process listing. Create, never apply: every write here fills an absent Secret, so a Secret that
 # appeared since the read (a second run, a person) stops the run instead of being overwritten.
@@ -54,6 +77,7 @@
 # otherwise unrelated Secret created by this run.
 ours=$(get "$NS" cmapi-keycloak); theirs=$(get "$REALM_NS" cmapi-realm-secrets)
 keys_existing=$(get "$NS" cmapi-keys)
+users_existing=$(get "$NS" cmapi-test-users)
 if [ "$LDAP_BIND" = true ]; then
   lb_ours=$(get "$NS" cmapi-ldap-bind); lb_theirs=$(get "$REALM_NS" cmapi-ldap-bind)
 fi
@@ -113,6 +137,14 @@
     if realm_import_exists; then
       echo "ERROR: KeycloakRealmImport cmapi exists in $REALM_NS and both Secrets are gone. New values would not match the realm. Read the clients' secrets from the realm, or delete the realm and its import first." >&2; exit 1
     fi
+    if [ "$ISSUER_CHECK" = true ]; then
+      state=$(issuer_state)
+      case "$state" in
+        absent) ;;
+        present) echo "ERROR: realm ${ISSUER##*/} exists at $ISSUER and both Secrets are gone. New values would not match the realm. Read the clients' secrets from the realm, or delete the realm first." >&2; exit 1 ;;
+        *) echo "ERROR: cannot tell whether the realm exists at $ISSUER: $state. Nothing is generated. Run this again when Keycloak answers." >&2; exit 1 ;;
+      esac
+    fi
     lines=""; for p in $PAIRS; do lines+="${p%%:*} $(b64 "$(rnd)")"$'\n'; done
     while read -r a v; do [ -n "$a" ] || continue; for p in $PAIRS; do [ "${p%%:*}" = "$a" ] && echo "${p##*:} $v"; done; done <<<"$lines" | apply_secret "$REALM_NS" cmapi-realm-secrets
     printf '%s' "$lines" | apply_secret "$NS" cmapi-keycloak ;;
@@ -135,6 +167,15 @@
   echo "cmapi-keys: present, kept"
 fi
 
+# Local test users for the realm sync. Generated once: the sync sets these passwords on every run, so they must not change.
+if [ "$TEST_USERS" = true ]; then
+  if [ -z "$users_existing" ]; then
+    printf 'ola %s\namy %s\nopal %s\nbot-user %s\n' "$(b64 "$(rnd)")" "$(b64 "$(rnd)")" "$(b64 "$(rnd)")" "$(b64 "$(rnd)")" | apply_secret "$NS" cmapi-test-users
+  else
+    echo "cmapi-test-users: present, kept"
+  fi
+fi
+
 # The LDAP bind user is the owner's (docs/11, #34): checked, never generated. Both copies must exist, carry bindDN and
 # password, and be equal, or Keycloak's federation and the realm sync would disagree.
 if [ "$LDAP_BIND" = true ]; then
```


`patches/realm_sync.py.diff`:

```diff
--- a/cmapi/src/cmapi/tools/realm_sync.py
+++ b/cmapi/src/cmapi/tools/realm_sync.py
@@ -135,6 +135,8 @@
         return
     if not (bind_dn and bind_pw):
         print(f"LDAP federation: NOT configured, Secret {cfg.get('bindSecret', 'cmapi-ldap-bind')} (bindDN, password) is absent")
+        if cfg.get("requireSync"):
+            sys.exit("LDAP federation is required here and its bind credential is absent")
         return
     realm_info = rm.get("")
     comps = rm.get("/components", params={"type": "org.keycloak.storage.UserStorageProvider"}) or []
@@ -188,6 +190,12 @@
     print("LDAP mappers: username, email, first name, last name, employee-id, groups (/cmapi, cn=cmapi-*)")
     r = rm.call("POST", f"/user-storage/{existing['id']}/sync", params={"action": "triggerFullSync"}, ok=(200, 400, 500))
     print(f"LDAP full sync: {r.status_code} {r.text[:120]}")
+    # A deployment that needs federation says so. The status is not enough: a directory that cannot be reached answers 200 with zero counts (measured on 26.6.4),
+    # so the Job fails unless the sync read at least one user.
+    if cfg.get("requireSync"):
+        counts = r.json() if r.status_code == 200 else {}
+        if counts.get("failed") or not (counts.get("added", 0) + counts.get("updated", 0)):
+            sys.exit(f"LDAP full sync read no user: {r.status_code} {r.text[:120]}")
 
 
 def test_users(rm: Realm, audience: str, group_ids: dict[str, str]) -> None:
```


## 5. Delivery mode

**Setting.** `integrations.yaml`: `delivery.mode: argocd` (as `crc.yaml` and `kind` have it). `clusters.yaml`: `writes: false`, and no per-cluster `delivery`. `cmapi-env`: `CMAPI_GIT_PROVIDER: github`, `CMAPI_GIT_URL: https://git-not-configured.invalid`.

**No Gitea.** The service has no Git host in Wave 1; GitHub arrives in Wave 3. Nothing of Gitea moved: not `crc.yaml`'s `git:` block, not `git-bootstrap`, not `cmapi-git-admin`. `test_crc_nothing_can_write_or_reach_a_git_host_in_wave_1` fails on the words `gitea` or `cmapi-git` anywhere in `environments/crc`. The code still needs a provider kind: `make_provider` refuses an unknown one, and `settings.py:32` defaults to `gitea`, so it must be named. `github` builds a client with no network call (`base.py:27-35`, read). `.invalid` never resolves (RFC 6761), so a Git call cannot leave the cluster. The optional `cmapi-git` Secret refs in the Deployments stay absent. Removing the Gitea code stays in Wave 3.

**What the worker does.** Read, `jobs/__init__.py:21`: the only recurring job is `approval_timeout`, hourly, database only. `open_pr`, `pr_checks`, `watch_sync` and `prune` run only for a request. Three stops prevent one:

1. `plan_namespace` and `plan_delete` call `registry.writable` first (`pipeline.py:162,276`), and `registry.py:320` raises 422 `cluster-not-writable` when `writes` is false, before any Git call.
2. With `writes` true, a plan would reach `read_folder`, fail on `.invalid`, and raise 502 `git-unavailable`.
3. `_mode` is `argocd`, so `watch_sync` only reads, and the worker's SA has no write right (proved with `oc auth can-i`).

The 422 is proved on CRC with `?dryRun=true`, so even a wrong setting could write nothing. `writes` goes to true in Wave 5.

## 6. Reader baseline

**What `baseline-crc.sh` does (read):** applies `examples/baseline/cmapi-reader-rbac.yaml`, waits for the token Secret, writes the import Secret through a temp file. **As plain YAML:** all but the token, in `reader/00-cmapi-reader.yaml`. The import Secret holds a token, so `deploy/crc-reader-import.sh` writes it, through a pipe, with no file. Labels are as `registry.py` reads them; `apiUrl` is `https://kubernetes.default.svc`.

**Least privilege a read needs,** from the code, not the old list:

| Call | Where | Rule |
|---|---|---|
| `GET /version` | `registry.py:210` | none |
| `users/~`, or `selfsubjectreviews` | `kube.py:78-86` | none; for every authenticated user (inferred; the import's status proves it) |
| list, watch, get Namespace, ResourceQuota, LimitRange | `kube.py:162`, `registry.py:229`, `watch_sync` | `get, list, watch` |
| list Pod, PVC in one namespace | `pipeline.py:153-154` | `list` |

So five resources. Dropped from the example, each returning with the wave that uses it, in that PR: `nodes`, `serviceaccounts`, all of RBAC, SCCs, `users, groups, identities`, `clusterresourcequotas`, redhatcop, `oauths`, `applications` (a Role in `cmapi-argocd` per D2), Kyverno, the `thanos-querier` route, `cmapi-reader-monitoring`, `cmapi-token-issuer`. On a shared cluster that is a real reduction: it can no longer read other projects' users, identities and role bindings. `baseline-crc.sh` and `examples/baseline/` stay, per ruling 3.

**Proved:** `/api/v1/clusters` and `cmapi_cluster_status{status="connected"}`, plus `oc auth can-i` both ways in `crc-proof.sh`.

`deploy/crc-reader-import.sh`:

```bash
#!/usr/bin/env bash
# deploy/crc-reader-import.sh: the part of the reader baseline that cannot be plain YAML, the import Secret holding the reader's token. The token goes from one
# Secret to the other through a pipe: no file, no argument. Idempotent. A token Secret the controller has not filled stops it after 30 s.
set -euo pipefail
OC=${CMAPI_OC:-oc}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
for _ in $(seq 1 30); do
  json=$(oc_ get secret cmapi-reader-token -n cmapi-system -o json)
  ready=$(printf '%s' "$json" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("data") or {}; print("yes" if d.get("token") and d.get("ca.crt") else "no")')
  [ "$ready" = yes ] && break
  sleep "${CMAPI_READER_POLL:-1}"
done
[ "$ready" = yes ] || { echo "ERROR: Secret cmapi-reader-token has no token after 30 tries" >&2; exit 1; }
printf '%s' "$json" | python3 -c 'import base64,json,sys
d=json.load(sys.stdin)["data"]
print(json.dumps({"apiVersion":"v1","kind":"Secret","type":"Opaque",
  "metadata":{"name":"cmapi-cluster-crc","namespace":"cmapi-imports","labels":{"cmapi.net/secret-type":"cluster","cmapi.net/cluster-id":"CRC","app.kubernetes.io/part-of":"cmapi"}},
  "data":{"apiUrl":base64.b64encode(b"https://kubernetes.default.svc").decode(),"token":d["token"],"caData":d["ca.crt"]}}))' | oc_ apply --server-side -f - >/dev/null
echo "import Secret cmapi-imports/cmapi-cluster-crc is current"
```


## 7. Routes and NetworkPolicy

| Route | Host | Termination | Why |
|---|---|---|---|
| `cmapi-api` | `cmapi-api.apps-crc.testing` | edge, Redirect | The pod serves HTTP; reencrypt would need a server certificate in the app. Redirect: a token is never sent in the clear |
| `cmapi-mockup` | `cmapi-mockup.apps-crc.testing` | edge, Redirect | A static page, Service `cmapi-mockup`. The chart's `exposure.yaml:22-24` would have pointed it at a portal Service that does not exist here |
| none for the portal | | | The portal on mock data "Must not be deployed as the portal" (tracker) |

**`/docs` and OIDC.** `main.py:96-102` serves Swagger UI with client `cmapi-docs` and PKCE, and FastAPI's page builds the redirect from `window.location.origin`, so `https://cmapi-api.apps-crc.testing/docs/oauth2-redirect`, which is exactly the realm's `redirectUris` (`test_crc_redirect_uri_is_the_docs_route`). `webOrigins: ["+"]` lets the browser call the token endpoint. Uvicorn has `proxy_headers=True`, so the router's `X-Forwarded-Proto` is honoured. The browser's redirect to Keycloak is to the public issuer. The realm also carries `https://cmapi-portal.apps-crc.testing/*` and `http://localhost:5173/*` for later, as the chart has them, since a one-shot import could not add them. `portalUrl` is empty: only the email channel reads it, and none is configured.

**The policy with a `HostNetwork` router.** Kubernetes' documentation: "traffic to and from the node where a Pod is running is always allowed", and for a `hostNetwork` pod, "Traffic to/from hostNetwork pods is treated the same as all other traffic to/from the node IP. (This is the most common implementation.)", while saying the behaviour is "undefined" (read). So on one node, the router reaches 8080 by the node rule, or by the `policy-group.network.openshift.io/ingress` peer if OVN classifies it. OpenShift's page could not be read: `docs.redhat.com` answered 403 and OKD's returned navigation only, so this rests on the repository's earlier read. **Inferred until it answers,** as the tracker says. The file does not change. Kubelet's probes come from the node, so they pass for the same reason.

**The proof must be able to fail.** "The Route answers" also happens if the policy does nothing, which is how podman kind has been behaving. So `crc-proof.sh` creates a throwaway namespace `cmapi-np-probe`, whose pod must reach the mockup, which no policy selects (the control), and must be blocked from `cmapi-api.cmapi.svc:8080`; then removes it. Also `/metrics` is 404 through the Route, and pods started after the policy existed.

**Prometheus.** User workload Prometheus runs in `openshift-user-workload-monitoring`, on the pod network (inferred), matching the policy's first rule on 9090. If it is on the host network the node rule admits it instead. Either way the scrape is the proof.

## 8. Monitoring

`50-monitoring.yaml` is generated from `templates/monitoring.yaml`: the `PrometheusRule` spec equals the chart's rendered spec (measured), with the namespace filled and `{{ $labels.* }}` left for Alertmanager. `render.sh`'s `sed` does not touch them. ServiceMonitors: same selectors, matching the plain Services' labels (`test_crc_monitoring_...`). `kube_pod_container_status_restarts_total` comes through Thanos Ruler (inferred). A `cmapi` alert reaches only Console, since CRC has no receivers (inferred).

**No secret in the scrape:** `/metrics` has no auth (`observability.py`, `start_http_server`), and the ServiceMonitors name no credential; a test holds that. **The proof takes none on an argument:** Thanos Querier's Route with the session's token by `curl --config -` on stdin, verified against the ingress CA: `up{namespace="cmapi",job=~"cmapi-api|cmapi-worker"}` must be 2 series summing to 2, and `cmapi_cluster_status`. I chose this over `oc exec` into `prometheus-user-workload-0`, which is someone else's pod. `job` being the Service's name is inferred; a wrong guess fails visibly.

## 9. The first CRC run

Run by hand, in order, in one bash. Each stop means stop and report. Keep every output: it goes in `docs/reviews/`.

### Before the run, once, read-only (the coordinator)

```bash
deploy/crc-trust.sh --write                       # commit 30-trust.yaml; asks for ca.crt alone
deploy/crc-backup.sh --inspect                    # container, image, env NAMES and sources, limit; never a value
oc explain keycloakrealmimport.spec.resources --api-version=k8s.keycloak.org/v2beta1   # the field exists on RHBK
oc get keycloak keycloak -n keycloak -o jsonpath='{.spec.instances} {.spec.resources} {.spec.truststores} {.spec.networkPolicy}{"\n"}'
oc get networkpolicy -n keycloak -o name
oc get keycloakrealmimport corp -n keycloak -o json | python3 -c 'import json,sys
for c in json.load(sys.stdin)["spec"]["realm"].get("components",{}).get("org.keycloak.storage.UserStorageProvider",[]): print(c["config"].get("connectionUrl"), c["config"].get("useTruststoreSpi"), c["config"].get("usernameLDAPAttribute"), c["config"].get("userObjectClasses"))'
oc get cm ldap-structure -n ldap-testing -o json | python3 -c 'import json,sys; print(sorted(json.load(sys.stdin)["data"]))'
```

These decide four unknowns: that RHBK serves `resources`; whether the Keycloak truststore holds the LDAP CA (`realm_sync` uses `useTruststoreSpi: always`; `corp` already federates, so compare its URL with `ldaps://ldaps-ldap-testing.apps-crc.testing:443`); that people carry `uid`; and how to get one person's LDAP password for the login proof. **That last is not recorded in the repository (grep).** If `ldap-structure` holds only hashes, a person's password comes from the owner, and LDAP stays read-only. If none can be had, the LDAP proof is reported as not done.

Also the owner's step for Chrome, section 3.

### The run

```bash
set -uo pipefail
git status --porcelain; git rev-parse --short=10 HEAD            # clean, the merged commit
RUN=$PWD/deploy/rendered/wave1-run; mkdir -p "$RUN"; R=$PWD/deploy/rendered/crc; STOP=$RUN/stop
G=deploy/crc-guard.py
```

| Step | Command | Guard, and what stops it |
|---|---|---|
| 1 | `deploy/crc-trust.sh --check && deploy/crc-trust.sh --mac-ca "$RUN/crc-ca.pem"; export CMAPI_CRC_CA=$RUN/crc-ca.pem` | The file no longer verifies Keycloak |
| 2 | `$G preflight --needs 768 \| tee "$RUN/preflight.txt"; oc adm top node \| tee "$RUN/top-before.txt"; oc get pv -o name > "$RUN/pv-before.txt"` | Not CRC; **any kind cluster**; headroom minus 768 under 2 GiB; `keycloak-0` or `postgres-0` not Ready |
| 3 | `oc get ns cmapi-imports cmapi-system --ignore-not-found; oc get clusterrole,clusterrolebinding cmapi-reader --ignore-not-found; oc get ns cmapi -o jsonpath='{.metadata.labels}'` | Anything listed that this run has not made: stop and ask whose it is |
| 4 | `$G issuer; [ $? = 10 ]` | Not absent |
| 5 | `IMAGE=$(deploy/crc-image.sh \| tail -1) && deploy/render.sh crc "$IMAGE"` | A failure of any check in the script. **Finished before any Keycloak step,** so its load is never beside an import |
| 6 | `oc apply --server-side -f "$R/environment/"` | Top-level files only, no `-R`. Writes only to `cmapi`, `cmapi-imports` |
| 7 | `oc apply --server-side -f "$R/environment/reader/00-cmapi-reader.yaml" && deploy/crc-reader-import.sh` | Token not filled in 30 tries |
| 8 | `oc apply --server-side -f "$R/components/cmapi/00-serviceaccounts.yaml"; for sa in cmapi-api cmapi-worker cmapi-jobs; do for i in $(seq 1 60); do [ -n "$(oc get sa $sa -n cmapi -o 'jsonpath={.imagePullSecrets}')" ] && break; sleep 1; done; [ -n "$(oc get sa $sa -n cmapi -o 'jsonpath={.imagePullSecrets}')" ] \|\| echo STOP; done` | An SA with no pull secret after 60 s |
| 9 | `deploy/secrets.sh --issuer https://keycloak.apps-crc.testing/realms/cmapi --ca-file "$CMAPI_CRC_CA" --test-users` | Section 4. Writes `cmapi-realm-secrets` in `keycloak`, by name |
| 10 | `$G snapshot "$RUN/s0.json" && nohup $G watch "$RUN/watch.log" "$STOP" "$RUN/s0.json" >"$RUN/watch.out" 2>&1 &` | A realm not 200. From here the watch runs to the end, in the background (`CMAPI_CRC_CA` exported) |
| 11 | `$G gate "$STOP" && deploy/crc-backup.sh` | Section 14. **A failed backup stops the run** |
| 12 | `$G snapshot "$RUN/s1.json" && $G compare "$RUN/s0.json" "$RUN/s1.json"` | Any difference |
| 13 | `I=$R/environment/realm/10-realm-import.yaml; $G gate "$STOP" && $G headroom --needs 768 && $G check-import "$I" && { $G issuer; [ $? = 10 ]; } && oc apply --server-side --dry-run=server -f "$I" && oc apply --server-side -f "$I"` | Stopped; under the line; the file names anything else; the realm not absent; the API refuses `spec.resources` |
| 14 | `$G import-wait "$STOP" \| tee "$RUN/import.txt"` | Section 13: not started in 300 s, withdrawn; failed, withdrawn; running over 300 s, reported, never interrupted |
| 15 | `oc logs job/cmapi -n keycloak --tail=5 \| tee "$RUN/import-log-tail.txt"; sleep 120; $G snapshot "$RUN/s2.json" && $G compare "$RUN/s0.json" "$RUN/s2.json"` | Any difference. 120 s because a restart could lag |
| 16 | `oc delete keycloakrealmimport cmapi -n keycloak && $G issuer; [ $? = 0 ]; $G snapshot "$RUN/s3.json" && $G compare "$RUN/s0.json" "$RUN/s3.json"` | Realm not present afterwards; any difference |
| 17 | `$G gate "$STOP" && $G headroom --needs 672 && oc apply --server-side -f "$R/components/database-cnpg/cluster.yaml" && oc wait cluster.postgresql.cnpg.io/cmapi-db -n cmapi --for=jsonpath='{.status.phase}'='Cluster in healthy state' --timeout=300s` | Stopped; under the line; the database not healthy |
| 18 | `oc apply --server-side -f "$R/components/cmapi/40-networkpolicy.yaml" && oc apply --server-side -R -f "$R/components/cmapi" -f "$R/components/portal"; for d in cmapi-api cmapi-worker cmapi-mockup; do oc rollout status deploy/$d -n cmapi --timeout=600s; done` | A rollout not done. The policy first by itself: `-R` applies files in name order, `20-api` ahead of `40-networkpolicy`, and "started under the policy" must be true from the first moment |
| 19 | `$G gate "$STOP" && oc delete job cmapi-realm-sync -n cmapi --ignore-not-found; oc apply --server-side -f "$R/environment/realm/20-realm-sync.yaml" && oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s; oc logs job/cmapi-realm-sync -n cmapi \| tee "$RUN/realm-sync.txt"` | The Job failing, which now includes a federation that read nobody |
| 20 | `$G snapshot "$RUN/s4.json" && $G compare "$RUN/s0.json" "$RUN/s4.json"` | Any difference |
| 21 | `deploy/crc-proof.sh "$R" \| tee "$RUN/proof.txt"`, then the Chrome proofs | First failure |
| 22 | `$G snapshot "$RUN/s5.json" && $G compare "$RUN/s0.json" "$RUN/s5.json"; touch "$RUN/watch.log.done"; sleep 10; tail -1 "$RUN/watch.log"; oc adm top node \| tee "$RUN/top-after.txt"` | Any difference; the last line not `watch ended rc=0` |
| 23 | Once verified, and the coordinator agrees: `deploy/crc-backup.sh --delete` | The owner's term |

### The issue's proofs

| Proof | How | Where |
|---|---|---|
| Admitted under `restricted-v2` and started under the policy | `crc-proof.sh`: each pod's `openshift.io/scc`, 0 restarts, `status.startTime` after the policy's `creationTimestamp` | Script |
| `/readyz` 200 | `curl --cacert` through the Route | Script |
| `/api/v1/version` names the built commit | Equals `git rev-parse --short=10 HEAD`; api and worker `imageID` hold the digest | Script |
| Route through the policy | The above, and the blocked probe from another namespace, and `/metrics` 404, HTTP redirected | Script |
| `/docs` signed in, `GET /api/v1/me` | **Chrome:** open `/docs`, Authorize, sign in as local user `ola` (password from `oc get secret cmapi-test-users -n cmapi -o 'jsonpath={.data.ola}' \| base64 -d \| pbcopy`), Try it out on `/api/v1/me`, screenshot. Script: `bot-user` by password grant | Both |
| Login through LDAP federation | **Chrome:** same, as an LDAP person; `/me` shows `/cmapi/cmapi-*` groups and `employeeId` = `uidNumber`, screenshot. Before it: `LDAP full sync: 200` with `added` above 0 in the Job's log | Chrome |
| Mockup captioned as static | **Chrome:** `https://cmapi-mockup.apps-crc.testing/portal.html`, screenshot captioned "static mockup, no API behind it" | Chrome |
| `pg_stat_ssl` | `oc exec cmapi-db-1 -n cmapi -c postgres -- psql` from the server's side: every `cmapi` connection on TLS. The migrate container's env: `kind-test.sh:103-116`'s pod, by the same steps, if the coordinator wants ruling 4 repeated | Script |
| Prometheus scraping | Thanos query, section 8 | Script |
| `oc adm top node` before and after | Steps 2 and 22 | Files |


`deploy/crc-proof.sh`:

```bash
#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2086  # the python reads its own variables; $pair is "verb resource"
# deploy/crc-proof.sh <rendered dir>: every proof of issue #94 that a browser is not needed for, through the Routes, with TLS verified against CMAPI_CRC_CA. Prints what it measured and
# exits 1 on the first failure. Saves nothing itself: tee it into the review record. A token never reaches an argument: curl reads headers from stdin (--config -), and no value is printed.
set -euo pipefail
RENDERED=${1:?rendered dir}
CA=${CMAPI_CRC_CA:?the bundle from deploy/crc-trust.sh --mac-ca}
OC=${CMAPI_OC:-oc}
API=${CMAPI_API_URL:-https://cmapi-api.apps-crc.testing}
MOCKUP=${CMAPI_MOCKUP_URL:-https://cmapi-mockup.apps-crc.testing}
KC=${CMAPI_KEYCLOAK_URL:-https://keycloak.apps-crc.testing}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
c() { curl -sS -m 15 --cacert "$CA" "$@"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
say() { echo "proof: $*"; }
image=$(cat "$RENDERED/IMAGE"); digest=${image#*@}

# Admission: each workload pod under restricted-v2, started after the policy existed.
pods=$(oc_ get pods -n cmapi -o json)
printf '%s' "$pods" | python3 -c '
import json,sys
want=sys.argv[1]; items=json.load(sys.stdin)["items"]; bad=[]; seen=set()
for p in items:
    if p["status"].get("phase") in ("Succeeded","Failed"): continue
    comp=p["metadata"].get("labels",{}).get("app.kubernetes.io/component") or p["metadata"].get("labels",{}).get("cnpg.io/cluster","?")
    seen.add(comp); scc=p["metadata"].get("annotations",{}).get("openshift.io/scc")
    restarts=sum(c.get("restartCount",0) for c in p["status"].get("containerStatuses",[]))
    print("  ",p["metadata"]["name"],"scc",scc,"restarts",restarts,"uid",(p["spec"]["containers"][0].get("securityContext") or {}).get("runAsUser"))
    if scc!="restricted-v2": bad.append(p["metadata"]["name"]+" scc "+str(scc))
    if restarts: bad.append(p["metadata"]["name"]+" restarted")
    if comp in ("api","worker") and not all(want in c.get("imageID","") for c in p["status"]["containerStatuses"]): bad.append(p["metadata"]["name"]+" runs another image")
missing={"api","worker","mockup"}-seen
if missing: bad.append("no pod for "+",".join(sorted(missing)))
sys.exit("; ".join(bad) if bad else 0)' "$digest" || fail "pods"
say "pods under restricted-v2, no restarts, api and worker on $digest"
np=$(oc_ get networkpolicy cmapi-metrics -n cmapi -o 'jsonpath={.metadata.creationTimestamp}')
printf '%s' "$pods" | python3 -c '
import json,sys
late=[p["metadata"]["name"] for p in json.load(sys.stdin)["items"] if p["metadata"].get("labels",{}).get("app.kubernetes.io/component") in ("api","worker") and p["status"].get("startTime","")<sys.argv[1]]
sys.exit("started before the policy existed: "+",".join(late) if late else 0)' "$np" || fail "policy order"
say "api and worker started after NetworkPolicy cmapi-metrics ($np)"

# Through the Route, so through the router and the policy.
[ "$(c -o /dev/null -w '%{http_code}' "$API/readyz")" = 200 ] || fail "/readyz"; say "/readyz 200 through the Route"
version=$(c "$API/api/v1/version"); built=$(printf '%s' "$version" | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"])')
[ "$built" = "$(git rev-parse --short=10 HEAD)" ] || fail "/api/v1/version names $built, not HEAD"; say "/api/v1/version names commit $built"
[ "$(c -o /dev/null -w '%{http_code}' "$API/metrics")" = 404 ] || fail "/metrics answers through the Route"; say "/metrics is not on the Route"
[ "$(c -o /dev/null -w '%{http_code}' "$API/api/v1/me")" = 401 ] || fail "/api/v1/me without a token is not 401"; say "/api/v1/me with no token: 401"
[ "$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "http://${API#https://}/readyz")" = 302 ] || fail "HTTP is not redirected"; say "plain HTTP redirects"
[ "$(c -o /dev/null -w '%{http_code}' "$MOCKUP/portal.html")" = 200 ] || fail "the mockup"; say "the mockup answers (static, no API behind it)"

# The policy is enforced: a Route that answers proves nothing if nothing was ever blocked.
probe_ns=cmapi-np-probe; image_probe=docker.io/nginxinc/nginx-unprivileged@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6
cleanup_probe() { oc_ delete namespace "$probe_ns" --ignore-not-found --wait=false >/dev/null 2>&1 || true; }
trap cleanup_probe EXIT
oc_ create namespace "$probe_ns" >/dev/null
oc_ run np-probe -n "$probe_ns" --image="$image_probe" --restart=Never --command -- sleep 300 >/dev/null
oc_ wait pod/np-probe -n "$probe_ns" --for=condition=Ready --timeout=120s >/dev/null || fail "the probe pod did not start"
# The control first: the mockup is in the same namespace and no policy selects it, so this path must work, or "blocked" below would prove nothing.
oc_ exec np-probe -n "$probe_ns" -- wget -q -O /dev/null --timeout=5 http://cmapi-mockup.cmapi.svc:8080/portal.html >/dev/null 2>&1 || fail "the probe cannot reach the unselected mockup: the check below would prove nothing"
if oc_ exec np-probe -n "$probe_ns" -- wget -q -O /dev/null --timeout=5 http://cmapi-api.cmapi.svc:8080/readyz 2>/dev/null; then fail "another namespace reaches 8080: the policy is not enforced"; fi
say "another namespace's pod reaches the mockup and is blocked from the api (the policy is enforced on OVN-Kubernetes)"
cleanup_probe; trap - EXIT

# A sign-in with no browser: the automation client and its bot user, password and secret on stdin.
secret=$(oc_ get secret cmapi-keycloak -n cmapi -o 'jsonpath={.data.automationClientSecret}' | base64 -d)
botpw=$(oc_ get secret cmapi-test-users -n cmapi -o 'jsonpath={.data.bot-user}' | base64 -d)
token=$(printf 'grant_type=password&client_id=cmapi-automation&username=bot-user&scope=openid&client_secret=%s&password=%s' "$secret" "$botpw" | c -X POST --data @- "$KC/realms/cmapi/protocol/openid-connect/token" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])') || fail "no token for bot-user"
me=$(printf 'header = "Authorization: Bearer %s"\n' "$token" | c --config - "$API/api/v1/me")
printf '%s' "$me" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("proof: /api/v1/me:",d["username"],d["roles"]); sys.exit(0 if d["username"]=="bot-user" else 1)' || fail "/api/v1/me"
# The worker must not write: no write right, and a request stops before Git.
for pair in "create namespaces" "patch namespaces" "create rolebindings"; do
  for sa in cmapi-api cmapi-worker; do
    [ "$(oc_ auth can-i $pair --as="system:serviceaccount:cmapi:$sa" 2>/dev/null || true)" = no ] || fail "$sa may $pair"
  done
done
say "api and worker may not create or patch namespaces or create rolebindings"
for pair in "list namespaces" "list resourcequotas"; do [ "$(oc_ auth can-i $pair --as=system:serviceaccount:cmapi-system:cmapi-reader 2>/dev/null || true)" = yes ] || fail "the reader may not $pair"; done
for pair in "get secrets" "create namespaces"; do [ "$(oc_ auth can-i $pair --all-namespaces --as=system:serviceaccount:cmapi-system:cmapi-reader 2>/dev/null || true)" = no ] || fail "the reader may $pair"; done
say "the reader lists what it needs, and reads no Secret and writes nothing"
resp=$(printf 'header = "Authorization: Bearer %s"\nheader = "Content-Type: application/json"\n' "$token" | c --config - -w '\n%{http_code}' -X POST -d '{"namespace":"wave1-proof"}' "$API/api/v1/clusters/CRC/namespaces?dryRun=true")
[ "${resp##*$'\n'}" = 422 ] || fail "a namespace plan answered ${resp##*$'\n'}, not 422"
case "$resp" in *cluster-not-writable*) ;; *) fail "the 422 is not cluster-not-writable";; esac
say "a namespace plan stops at 422 cluster-not-writable; dryRun, so nothing could be written even if it passed"

# The database: every client connection of the application, from the server's side, and the migrate container's environment from kind-test.sh's pod.
db=$(oc_ exec cmapi-db-1 -n cmapi -c postgres -- psql -d cmapi -Atc "select count(*) filter (where s.ssl), count(*) filter (where not s.ssl) from pg_stat_ssl s join pg_stat_activity a using (pid) where a.usename='cmapi'")
case "$db" in *"|0") [ "${db%%|*}" -gt 0 ] || fail "no application connections"; say "pg_stat_ssl: application connections on TLS|not: $db";; *) fail "pg_stat_ssl: $db";; esac

# Prometheus, with no secret on any command line and none in the targets: Thanos Querier's Route, the session's token on stdin.
thanos=$(oc_ get route thanos-querier -n openshift-monitoring -o 'jsonpath={.spec.host}')
query() { printf 'header = "Authorization: Bearer %s"\n' "$(oc_ whoami -t)" | c --config - --get --data-urlencode "query=$1" "https://$thanos/api/v1/query" | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(len(r), sum(float(x["value"][1]) for x in r))'; }
for attempt in $(seq 1 "${CMAPI_PROOF_SCRAPE_TRIES:-20}"); do up=$(query 'up{namespace="cmapi",job=~"cmapi-api|cmapi-worker"}'); [ "$up" = "2 2.0" ] && break; sleep 15; done
[ "$up" = "2 2.0" ] || fail "up for the two targets is: $up"; say "Prometheus scrapes both targets: up = $up (try $attempt)"
[ "$(query 'cmapi_cluster_status{namespace="cmapi",cluster_id="CRC",status="connected"}' | cut -d' ' -f2)" != 0.0 ] || fail "the reader is not connected"; say "cmapi_cluster_status connected"
say "all passed"
```


### Rollback

`deploy/crc-rollback.sh --yes`. It removes, each by name, what Wave 1 added, in dependency order.

**Stays, because it was there before Wave 1:** namespace `cmapi`, its generated Secrets, `cmapi-ldap-bind` in both namespaces, every LDAP entry. Only the label the apply added is removed.

**Stays by design:**

| Left behind | Why | Effect |
|---|---|---|
| Realm `cmapi`, with its federation | The instruction: no master credential. See below | `GET /realms/cmapi` is 200, not 404. Keycloak polls LDAP for it every 15 min (`changedSyncPeriod: 900`) with the read-only bind user, until removed |
| `master`'s client `cmapi-realm` | Creating any realm adds this (measured); it goes with the realm | One more client in `master`. No key or other realm changes |
| `cmapi-realm-secrets` in `keycloak` | The authority for the realm's secrets (`secrets.sh`). A rerun copies from it (verdict `from-realm`) and never mints | One Secret |
| The PV's data | See below | Disk on the node |
| The image's blobs | `oc delete imagestream` removes the tags; blobs stay until the registry is pruned (inferred) | Registry storage |

**Retain.** The class is Retain, WaitForFirstConsumer, no expansion (coordinator). Deleting Cluster and claim leaves the PV `Released` with its data. The script reads the PV's name first, and deletes the PV object only if its `claimRef` is `cmapi/cmapi-db-1` and it is `Released`; the provisioner leaves the directory on the node under Retain (inferred), and cmapi will not write to the node through `oc debug`. A new `Cluster` gets a new PV and a new `cmapi-db-app`; old pods hold a stale password until restarted (`README`, measured earlier). That CNPG removes the PVC with the Cluster is not documented where I looked, so the script deletes the claim by name too.

**Deleting our `KeycloakRealmImport`** removes its Job, pod and Secret, and **does not delete or change the realm** (read, section 4).

**A correction to the premise I was given.** The brief says rollback cannot delete realm `cmapi` without a master admin credential. **Measured otherwise** on Keycloak 26.6.4: `DELETE /admin/realms/cmapi` with a token of the realm's own `cmapi-realm-admin` service client answers **204**. The issuer returns Keycloak's 404. The other realms' public keys are unchanged, `master`'s `cmapi-realm` client is gone, and the same token gets **403** on another realm's read and delete. Read: `RealmAdminResource.deleteRealm:563-570` requires only `manage-realm` on that realm. RHBK is not measured. No master credential is involved, and this stays within "touch only realm cmapi". So rollback has a flag, **off unless asked:** `--delete-realm --owner-approved`. If `cmapi-realm-admin` cannot sign in, the realm stays and no other credential is tried. **That choice is the coordinator's.** The default does what I was told. Nothing in either form touches any other realm: only `cmapi` is ever in the URL.

`deploy/crc-rollback.sh`:

```bash
#!/usr/bin/env bash
# deploy/crc-rollback.sh --yes [--delete-realm --owner-approved]: returns CRC to the state before Wave 1, as far as cmapi can. Every delete names one object: no --all, no selector, no --prune, no -f on a directory.
# Stays: namespace cmapi, its generated Secrets and cmapi-ldap-bind (before Wave 1), the same Secret in keycloak, every LDAP entry, every other project's object.
# Stays by design: realm cmapi and Secret keycloak/cmapi-realm-secrets, the authority for the realm's client secrets (deploy/secrets.sh) while the realm exists. Deleting the import does not delete a realm.
# --delete-realm --owner-approved removes the realm too, with the realm's own cmapi-realm-admin service client, no master credential (measured on Keycloak 26.6.4: 204, the other realms' keys unchanged, and 403 on another realm).
set -euo pipefail
OC=${CMAPI_OC:-oc}
KC=${CMAPI_KEYCLOAK_URL:-https://keycloak.apps-crc.testing}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
YES=false; REALM=false; APPROVED=false
for a in "$@"; do case "$a" in --yes) YES=true;; --delete-realm) REALM=true;; --owner-approved) APPROVED=true;; *) echo "unknown argument $a" >&2; exit 2;; esac; done
[ "$YES" = true ] || { sed -n '2,5p' "$0"; echo "nothing done: pass --yes"; exit 2; }
if [ "$REALM" = true ] && [ "$APPROVED" != true ]; then echo "ERROR: --delete-realm needs --owner-approved" >&2; exit 2; fi
del() { echo "delete $*"; oc_ delete "$@" --ignore-not-found; }

if [ "$REALM" = true ]; then
  # First, while its secret exists. Only this realm's name is ever in the URL.
  CA=${CMAPI_CRC_CA:?the bundle from deploy/crc-trust.sh --mac-ca}
  secret=$(oc_ get secret cmapi-keycloak -n cmapi -o 'jsonpath={.data.realmAdminClientSecret}' | base64 -d)
  [ -n "$secret" ] || { echo "ERROR: no realmAdminClientSecret; the realm stays" >&2; exit 1; }
  token=$(printf 'grant_type=client_credentials&client_id=cmapi-realm-admin&client_secret=%s' "$secret" | curl -sS -m 15 --cacert "$CA" -X POST --data @- "$KC/realms/cmapi/protocol/openid-connect/token" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])') || { echo "ERROR: cmapi-realm-admin cannot sign in; the realm stays, and no other credential is used" >&2; exit 1; }
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$token" | curl -sS -m 30 --cacert "$CA" --config - -o /dev/null -w '%{http_code}' -X DELETE "$KC/admin/realms/cmapi")
  [ "$code" = 204 ] || { echo "ERROR: deleting realm cmapi answered $code; it stays" >&2; exit 1; }
  echo "realm cmapi deleted"
  del secret cmapi-realm-secrets -n keycloak
fi
del keycloakrealmimport cmapi -n keycloak
del job cmapi-realm-sync -n cmapi
del deployment cmapi-api -n cmapi
del deployment cmapi-worker -n cmapi
del deployment cmapi-mockup -n cmapi
# The database: read the PV's name first. The storage class is Retain, so deleting the claim leaves the PV Released, holding the data.
pv=$(oc_ get pvc cmapi-db-1 -n cmapi --ignore-not-found -o 'jsonpath={.spec.volumeName}')
del cluster.postgresql.cnpg.io cmapi-db -n cmapi
oc_ delete pvc cmapi-db-1 -n cmapi --ignore-not-found --wait=true --timeout=120s >/dev/null
if [ -n "$pv" ]; then
  # Only a PV whose claim was this one, and only once it is Released.
  who=$(oc_ get pv "$pv" -o 'jsonpath={.spec.claimRef.namespace}/{.spec.claimRef.name}/{.status.phase}')
  case "$who" in cmapi/cmapi-db-1/Released) del pv "$pv"; echo "note    : the PV's directory stays on the node's disk: the provisioner does not remove data under Retain, and cmapi does not write to the node";;
    *) echo "note    : PV $pv left alone: $who";; esac
fi
for o in "service cmapi-api" "service cmapi-worker" "service cmapi-mockup" "networkpolicy cmapi-metrics" "route.route.openshift.io cmapi-api" "route.route.openshift.io cmapi-mockup" \
         "servicemonitor.monitoring.coreos.com cmapi-api" "servicemonitor.monitoring.coreos.com cmapi-worker" "prometheusrule.monitoring.coreos.com cmapi" \
         "configmap cmapi-env" "configmap cmapi-config" "configmap cmapi-trust" "configmap cmapi-mockup" \
         "secret cmapi-keys" "secret cmapi-keycloak" "secret cmapi-test-users" "serviceaccount cmapi-api" "serviceaccount cmapi-worker" "serviceaccount cmapi-jobs" "imagestream.image.openshift.io cmapi"; do
  # shellcheck disable=SC2086  # "kind name"
  del $o -n cmapi
done
del namespace cmapi-np-probe
del namespace cmapi-imports
del namespace cmapi-system
del clusterrolebinding cmapi-reader
del clusterrole cmapi-reader
oc_ label namespace cmapi app.kubernetes.io/part-of- >/dev/null 2>&1 || true
echo "rollback done. Left behind, each on purpose: see docs/13, Rollback"
```


## 10. Tests

**Before CRC, no cluster (run here; CI on Linux):**

| Test | Proves | Can fail? Measured here |
|---|---|---|
| `render-test.sh`, extended | Five placeholders on crc, one in `environments/crc`; each of three files moves the checksum; the import does not; `kind` still four | 0 failed. Its own cases assert the negatives |
| `test_plain_manifests.py`, 12 new test functions | Each decision above, statically: `writes: false`, no Gitea, redirect equals Route, 576 Mi, reader's five, realm name | 38 passed in my tree |
| `crc-guard-test.py` | All of `crc-guard.py`, on a stub `oc` and a real local TLS server | 15 mutants; result in the measured list |
| `crc-scripts-test.sh` | Image, trust, reader, backup, rollback and proof on stubs. No credential on an argument; deletes only from a fixed list, with the "broad delete" rule shown catching a mutated line; dump's path and content absent from output | 77 checks, 0 failed, including 16 ways the proof must fail. Writing these found real bugs: `--extra-ca` swallowing a refusal, and in the guard a container's empty `running: {}` read as not started |
| `mutate-secrets.py`, 8 new mutants | The issuer check | 30 of 30 killed |
| `realm-test.py` | The shipped realm on real Keycloak, beside other realms, LDAP stand-in | 24 of 24. A broken federation fails the Job |
| `test_review_h`, 2 new | `requireSync` | 6 cases passed, run by path |
| `kubeconform` (CI), `-skip Route` | Schemas | Not run locally: earlier refusal stands. `jsonschema` on the same pins: 0 errors, measured |
| `shellcheck`, `ci-guard.py` | All new scripts are in the job | rc 0, 0 failed, measured |

The `manifests` job runs `realm-test.py` with Docker; `docker.io` and `quay.io` pulls there are not measured. Not measured here either: the `secrets-test.sh` cases against a real API (CI's kind). `crc-proof.sh` has run only on stubs; its first real run is CRC.

**`kind-test.sh` passes:** one change, `--no-issuer-check`. Its stub test stubs `secrets.sh`. Environment `kind` and its renders are byte-identical (measured). Not rerun end to end here: no kind cluster in this brief.

**On kind on Podman, before CRC, with no shared-cluster risk:** `kind-test.sh` as it is, with the image from this commit. Could add: apply `reader/` and run the registry's six checks against kind's API. Not worth more.

**Cannot be proven before CRC:** `restricted-v2`; the internal registry and its pull; RHBK's operator on `spec.resources`, and its Job; that an import does not restart `keycloak-0`; OVN-Kubernetes enforcing the policy; the router; `ldaps` through the Route with Keycloak's truststore; user workload monitoring; real restart recovery. **No kind cluster during a CRC step.**

## 11. Memory

From the manifests, by Kubernetes' rule that a pod's effective request is the larger of the sum of its containers and its largest init container:

| Pod | Containers | Init | Effective |
|---|---|---|---|
| `cmapi-api` | 160 | 96 | 160 |
| `cmapi-worker` | 128 | 96 | 128 |
| `cmapi-db-1` | 256 | | 256 |
| `cmapi-mockup` | 32 | | 32 |
| **Steady** | | | **576 Mi** |

Held by `test_crc_memory_requests_are_the_planned_576_mi`. The tracker's 832 includes 256 for Argo CD, which is not in this wave.

Against 4,018 Mi of headroom (coordinator; re-read at each step), with a stop line of 2,048:

| When | Added | Left | |
|---|---|---|---|
| Import alone, as designed | 768 | **3,250** | Job ends, and a finished pod no longer counts |
| Import alone, if RHBK refuses `resources` | 1,700 | **2,318** | Passes. So realm first in either case |
| Import plus cmapi, operator default | 2,276 | 1,742 | The coordinator's sum, confirmed. **This order is never run** |
| Steady | 576 | **3,442** | |
| Steady plus realm-sync Job | 672 | **3,346** | Peak of the first run |
| Later rollout: surge of api and worker | 864 | 3,154 | `maxSurge: 1` and the default 25%, rounded up |
| CNPG's initdb job | transient 256, before the instance | no further | Inferred |

**Order: realm first, alone.** It needs no workload, and it puts the riskiest step on the quietest cluster. Limits: 1,024 + 512 + 384 + 512 + 128 = 2,560 Mi if all were at their limit at once.

**Real use,** which is what threatens anything: node usage 14,987 Mi (coordinator) of 19,543 allocatable. The import peaked near 735 MB under a 1 GB limit (measured). Measured use of cmapi's own pods on CRC does not exist yet: `oc adm top` in steps 2 and 22 is the first.

## 12. Risks to other projects

| Risk | Guard |
|---|---|
| Wrong realm imported or overwritten | `check-import`, tested on seven wrong files; `--override=false`; issuer must be absent; snapshot compare of every realm's key |
| A broad delete in `keycloak` | Every delete names one object. `crc-scripts-test.sh` holds a fixed list and a static rule, both shown to fail |
| `keycloak-0` restarts | Section 13 |
| Import pending, firing days later | `import-wait` withdraws at 300 s; a small request; the CR deleted once Done |
| A failing import retrying, 6 pods at 1Gi limit | Withdrawn on `HasErrors` |
| Load beside Keycloak: its liveness gives up in 30 s (`period 10 × 3`, read) | Image built before; no kind; the import capped at 1 CPU; backup before, never during, the import |
| Node memory | Headroom at each step; import's request is its measured peak |
| Backup: memory in `postgres-0`'s cgroup, a shared database's OOM | Stops under 128 Mi of room; `pg_dump` 6.2 MB measured on a small DB |
| Backup's copy of every realm's secrets | Section 14 |
| Reader's cluster-wide read | Five resources; no Secret |
| Master realm gets a client | Unavoidable when creating a realm; measured; said here so nobody is surprised |
| New LDAP poll, every 15 minutes, on the shared directory | Read-only bind user, `cmapi-*` groups only; the corp realm does the same |
| Alert noise | `severity: critical` rules exist; Console only (inferred) |
| The policy absent on OVN | Blocked-probe proof |
| Retained PV, disk | Named in rollback; a 2 Gi claim |
| Docker Hub pull of the mockup and probe | By digest; a failed pull stops at the rollout, harming only cmapi |
| Wave 3 finding, no action now | `settings.verify` is passed to the Git provider (`context.py:92-95`), so with `cmapi-trust` holding only a private CA, **GitHub's TLS will fail**. File it against Wave 3 |

## 13. The owner's requirement: other realms unaffected, and a restart does not bleed long

### 13.1 Nothing else deleted or changed

- In `keycloak`, the run writes exactly: Secret `cmapi-realm-secrets` (`create`, stdin, by `secrets.sh`) and `KeycloakRealmImport cmapi` (one named file, one document). Deletes: `oc delete keycloakrealmimport cmapi -n keycloak` and, only with the flag, `oc delete secret cmapi-realm-secrets -n keycloak`. No `--all`, no label selector, no `--prune`, no `oc delete -f` of a directory.
- `crc-guard.py check-import` before the apply requires, on the file's text, exactly one document and exactly one each of `kind: KeycloakRealmImport`, `name: cmapi`, `namespace: keycloak`, `keycloakCRName: keycloak`, `realm: cmapi`, and no other `realm:` or `id:` at that indent.
- **Tests that can fail:** seven wrong files refused; mutants "the realm name is not checked", "a second document is allowed", "withdrawal deletes every import" killed. `test_crc_realm_import_names_cmapi_and_holds_no_secret` holds it in CI too.

### 13.2 Proof the others are unaffected

`crc-guard.py snapshot` with no credential: each of `master, corp, inkcast-prod, inkcast-staging, tutorial` and any realm another import names, HTTP status and SHA-256 of its `public_key`; each other import's UID, creationTimestamp, generation and Done condition; `keycloak-0`'s and `postgres-0`'s UID, container start and restart count; the Keycloak CR's generation. `compare` stops the run on any difference, printing the field. Taken at step 10, then compared at 12, 15, 16, 20, 22. Each field has a test that changing it stops the run (12 cases).

**Honest limits.** A public key shows a realm was replaced, not that a client inside it changed. A realm no import names is invisible without a credential, unless listed. Those need an admin credential, which is forbidden. **The one change to another realm is known and measured:** creating a realm adds a client `cmapi-realm` to `master`. Its key does not change.

### 13.3 Watching

`crc-guard.py watch` from before the backup to the end: **every 5 s**, every realm, and `keycloak-0`, one timestamped line to `watch.log`. 5 s against a 162 s outage gives about 3% resolution; 6 requests per 5 s on public, cached endpoints is negligible beside a Keycloak's normal load (inferred). A non-200, a changed key, or a changed `keycloak-0` writes the stop file, prints `BREACH`, and goes on logging, so the outage's length is on record. Every later step begins with `gate`.

### 13.4 If a restart happens: bound the bleed

1. **Stop at once.** The stop file; every step's `gate` refuses. `import-wait` withdraws our import **only if its container has not started**: that removes a pod, and takes load off a recovering Keycloak. A running import is left to finish.
2. **cmapi takes no action on Keycloak:** no delete, no restart, no CR edit, no scale.
3. **Report any restart to the owner immediately,** as a notice, with `watch.log` and `oc describe pod keycloak-0 -n keycloak`, read-only.
4. **Baseline 2 min 42 s** (coordinator, the one measured restart). **At 300 s still unready, `REPORT TO THE OWNER NOW`,** printed and logged. Why 300 s: nearly twice the only measurement (1.85 times), allowing for a slower start on a node at 76 to 80%, so a normal restart does not raise it; anything longer is not the known restart. It is well before the kubelet's own limit: startup probe `600 × 1 s` (`KeycloakDeploymentDependentResource.java:383-392`, read), after which it would kill and restart the container and so double the outage. The owner should know at 5 minutes, not at 10. One sample is thin; the number should change as measurements arrive.
5. **The run does not resume by itself.** After the owner has heard: snapshot, compare to `s0`. A new `keycloak-0` start is expected to differ; the realms must not.

**cmapi's own pods while Keycloak is down (read, `auth.py`, `health.py`, `keycloak_admin.py`):**

- Bearer tokens already issued keep verifying offline: JWKS is cached for 10 minutes, and past that the last good set keeps verifying (stale on error), persisted in the database. An unknown `kid` is 503 `idp-unavailable`, never 401.
- A new sign-in is impossible, since that is Keycloak's. `/readyz` tests only the database, so the api stays Ready and no pod restarts. Liveness is `/api/v1/version`, with no I/O.
- **No retry storm:** one JWKS fetch per pod per 30 s retry window. The directory answers from its cache, or unavailable.
- The worker never calls Keycloak on its recurring job. `cmapi-realm-sync` has one try. `secrets.sh` would stop, minting nothing.

### 13.5 Keeping restarts unlikely

| What in this plan could cause one | Read or measured |
|---|---|
| The import itself | **Read: no.** 26.6.7's controller, `:134-137`: "no need to restart Keycloak as we're only importing new realms". The same at `26.6.9-redhat2`. **26.0.8's did restart:** `Log.info("Job finished performing a rolling restart of the deployment")`, `rollingRestart(realmCR)`, lines 146-147. That is what the Red Hat article for 26.0.x describes (title read; the body is behind a login). **Measured:** a live server, no restart, on 26.6.4. **Coordinator:** three imports on CRC, no restart |
| A change to the StatefulSet | None. The Keycloak CR is never written; `WatchedResources` hashes only Secrets and ConfigMaps the CR references, and ours are not (read). Compared at every snapshot |
| Import Job's memory beside `keycloak-0` | `keycloak-0`'s 2Gi limit is its own cgroup: another pod cannot use it up. What another pod can cause is node pressure. Kubernetes' order (read): pods over their request first, and `keycloak-0` at 671 Mi of 1Gi is under its request, so it goes last. `oom_score_adj` for a Burstable pod falls as its request rises, so the import at 768 Mi is near `keycloak-0`'s at 1 Gi. The default hard threshold is `memory.available<100Mi` (read; CRC's own setting unread). Real headroom about 4,556 Mi; the import peaks at about 735 MB (measured): no pressure expected |
| CPU beside `keycloak-0` | The Job's JVM starts with `kc.sh` without `--optimized` (`:158`), so it may rebuild. Capped at 1 CPU of about 8 (coordinator's `2017m 25%`, inferred); 79 s, measured |
| Database pressure | Backup finishes first. An import writes a small transaction: `Realm 'cmapi' imported` 5 s after it started reading, measured |
| Other load on the Mac | Image built first, no kind, my throwaway containers removed. The tracker cannot rule out this as the cause of the last restart |

**Can it be avoided, or only bounded? Only bounded.** The one measured restart (exit 143, then failed probes, 35 h after the last import) has no known cause, Keycloak has one instance, and its liveness gives up in 30 s of stall. This plan removes the known triggers. It cannot remove an unknown one.

### 13.6 Withdrawing our import if it has not started

Coordinator: `inkcast-prod`'s Job waited 6.5 days, unattended, cause unknown. Read: nothing in the Job or CR can bound it. So `import-wait` does:

| State | Bound | Action |
|---|---|---|
| Our pod's container not started | 300 s from apply. With headroom checked it should schedule at once, so longer means something is wrong | `oc delete keycloakrealmimport cmapi -n keycloak --wait=true --timeout=60s`. Report the pod's phase |
| Stop file, not started | At once | The same |
| Started, not done | 300 s after start; 79 s measured at this CPU | Report. **Never interrupted** |
| `HasErrors` with a started pod | At once | The same delete, which stops the Job's further attempts |
| `Done`, issuer present | | Go on |
| `Done`, issuer not present | | Stop |

Deleting takes Job, pod and Secret by owner reference, and nothing can start later (read). A race: the pod starts as it is deleted, so the guard reads the issuer afterwards and reports it. Should the realm exist, that is a kept realm, and the secrets already match it.

`deploy/crc-guard.py`:

```python
#!/usr/bin/env python3
"""deploy/crc-guard.py: the guards of the Wave 1 run on CRC, a shared cluster. Python's standard library and `oc` only; reads only, except
`import-wait`, which may delete cmapi's own KeycloakRealmImport by name. Never prints a secret; TLS is always verified against CMAPI_CRC_CA.

  preflight [--needs MI]       this is CRC, no kind cluster, nothing of cmapi's where nothing should be, request headroom
  headroom --needs MI          stop unless request headroom minus MI is at least 2 GiB
  check-import FILE            the one document is KeycloakRealmImport cmapi of realm cmapi, namespace keycloak, Keycloak CR keycloak
  issuer                       realm cmapi: exit 0 present, 10 absent, 20 anything else (never read as absent)
  snapshot FILE                the other realms and their imports, keycloak-0, postgres-0, the Keycloak CR, with no credential
  compare BEFORE AFTER         stop on any difference
  watch LOG STOPFILE BASELINE  poll every realm every 5 s until LOG.done appears; on a breach write STOPFILE and report at 300 s
  gate STOPFILE                exit 1 if the watch has stopped the run
  import-wait STOPFILE         follow our import; withdraw it, by name, if it has not started in time

Exit codes: 0 fine, 1 stop, 2 usage."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

KEYCLOAK = os.environ.get("CMAPI_KEYCLOAK_URL", "https://keycloak.apps-crc.testing")
API_SERVER = os.environ.get("CMAPI_CRC_API", "https://api.crc.testing:6443")
NS = "keycloak"
OURS = "cmapi"
# What the coordinator read on 2026-11-06. A realm no import names is invisible without a credential, so these are always asked for.
KNOWN_REALMS = ("master", "corp", "inkcast-prod", "inkcast-staging", "tutorial")
STOP_LINE_MI = 2048
POLL_SECONDS = float(os.environ.get("CMAPI_GUARD_POLL", "5"))
REPORT_AFTER_SECONDS = float(os.environ.get("CMAPI_GUARD_REPORT_AFTER", "300"))
SCHEDULE_DEADLINE = float(os.environ.get("CMAPI_GUARD_SCHEDULE_DEADLINE", "300"))
RUN_DEADLINE = float(os.environ.get("CMAPI_GUARD_RUN_DEADLINE", "300"))


class Stop(Exception):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def oc(*args: str, check: bool = True) -> str:
    r = subprocess.run([*shlex.split(os.environ.get("CMAPI_OC", "oc")), *args], capture_output=True, text=True, timeout=60)
    if check and r.returncode != 0:
        raise Stop(f"oc {args[0]} {' '.join(a for a in args[1:4])}: {r.stderr.strip()[:300]}")
    return r.stdout


def oc_json(*args: str) -> dict:
    out = oc(*args, "-o", "json")
    return json.loads(out) if out.strip() else {}


def tls() -> ssl.SSLContext:
    ca = os.environ.get("CMAPI_CRC_CA")
    if not ca or not os.path.isfile(ca):
        raise Stop("CMAPI_CRC_CA must name the CA bundle (deploy/crc-trust.sh --mac-ca); TLS verification is never off")
    c = ssl.create_default_context(cafile=ca)
    # Hostname and chain are verified. Python 3.13's stricter default also refuses a chain missing an RFC 5280 extension such as the Authority Key Identifier,
    # which curl accepts (measured here on Python 3.14 with a plain openssl CA), and a false stop on a shared cluster's guard is a failure too.
    c.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return c


def http_get(url: str, timeout: float = 5) -> tuple[int, bytes]:
    """(status, body); status 0 for anything that gave no HTTP answer, a certificate failure included."""
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=tls()) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError, ValueError):
        return 0, b""


def realm_state(name: str, timeout: float = 5) -> dict:
    status, body = http_get(f"{KEYCLOAK}/realms/{name}", timeout)
    key = None
    if status == 200:
        try:
            key = hashlib.sha256(json.loads(body)["public_key"].encode()).hexdigest()
        except (ValueError, KeyError, TypeError):
            status = -1                                     # a 200 that is not a realm document is not a realm
    return {"status": status, "public_key_sha256": key}


def issuer_state() -> str:
    """present, absent or unknown. Only Keycloak's own 404 is absent: a router's 404 or 503, a timeout or a bad certificate is not."""
    status, body = http_get(f"{KEYCLOAK}/realms/{OURS}")
    try:
        doc = json.loads(body)
    except ValueError:
        return "unknown"
    if status == 200 and doc.get("realm") == OURS:
        return "present"
    if status == 404 and doc == {"error": "Realm does not exist"}:
        return "absent"
    return "unknown"


def condition(obj: dict, kind: str) -> str | None:
    for c in obj.get("status", {}).get("conditions", []) or []:
        if c.get("type") == kind:
            return str(c.get("status")).lower()
    return None


def pod_state(name: str) -> dict:
    p = oc_json("get", "pod", name, "-n", NS)
    cs = (p.get("status", {}).get("containerStatuses") or [{}])[0]
    return {"uid": p["metadata"]["uid"], "started": (cs.get("state", {}).get("running") or {}).get("startedAt"),
            "restarts": cs.get("restartCount"), "ready": cs.get("ready")}


def snapshot() -> dict:
    imports = oc_json("get", "keycloakrealmimport", "-n", NS).get("items", [])
    names = set(KNOWN_REALMS) | {i["spec"]["realm"]["realm"] for i in imports if i["metadata"]["name"] != OURS}
    realms = {n: realm_state(n) for n in sorted(names)}
    bad = {n: s["status"] for n, s in realms.items() if s["status"] != 200}
    if bad:
        raise Stop(f"a realm does not answer 200: {bad}")
    return {"realms": realms,
            "imports": {i["metadata"]["name"]: {"uid": i["metadata"]["uid"], "created": i["metadata"]["creationTimestamp"],
                                                "generation": i["metadata"].get("generation"), "done": condition(i, "Done")}
                        for i in imports if i["metadata"]["name"] != OURS},
            "keycloak-0": pod_state("keycloak-0"), "postgres-0": pod_state("postgres-0"),
            "keycloak_cr_generation": oc_json("get", "keycloak", "keycloak", "-n", NS)["metadata"]["generation"]}


def diff(a, b, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(set(a) | set(b)) for d in diff(a.get(k, "<absent>"), b.get(k, "<absent>"), f"{path}/{k}")]
    return [] if a == b else [f"{path}: {a} -> {b}"]


def headroom_mi() -> int:
    node = oc_json("get", "node", "crc")["status"]["allocatable"]["memory"]
    m = re.fullmatch(r"(\d+)(Ki|Mi|Gi)?", node)
    if not m:
        raise Stop(f"allocatable memory {node} is not understood")
    alloc = int(m[1]) * {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, None: 1 / 1048576}[m[2]]
    # The row of "Allocated resources", in non-terminated pods: a finished import no longer counts.
    m = re.search(r"^\s+memory\s+(\d+)(Ki|Mi|Gi)?\s", oc("describe", "node", "crc"), re.M)
    if not m:
        raise Stop("no memory requests in oc describe node crc")
    req = int(m[1]) * {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, None: 1 / 1048576}[m[2]]
    return int(alloc - req)


def need_headroom(needs: int) -> None:
    h = headroom_mi()
    print(f"{now()} request headroom {h} Mi, this step needs {needs} Mi, leaving {h - needs} Mi; the stop line is {STOP_LINE_MI} Mi")
    if h - needs < STOP_LINE_MI:
        raise Stop("under the stop line")


def preflight(needs: int) -> None:
    server = oc("whoami", "--show-server").strip()
    if server != API_SERVER:
        raise Stop(f"oc points at {server}, not {API_SERVER}")
    clusters = subprocess.run(["kind", "get", "clusters"], capture_output=True, text=True,
                              env={**os.environ, "KIND_EXPERIMENTAL_PROVIDER": "podman"}, timeout=30)
    names = [c for c in clusters.stdout.split() if c]
    if clusters.returncode != 0 or names:
        raise Stop(f"a kind cluster exists or cannot be listed: {names or clusters.stderr.strip()[:200]}; none may run during a CRC step")
    need_headroom(needs)
    for ns in ("cmapi-imports", "cmapi-system"):
        if oc("get", "ns", ns, "--ignore-not-found", "-o", "name").strip():
            print(f"note    : namespace {ns} exists: it is cmapi's only if an earlier step of this run made it")
    for pod in ("keycloak-0", "postgres-0"):
        if not pod_state(pod)["ready"]:
            raise Stop(f"{pod} is not Ready")


def check_import(path: str) -> None:
    """On the text, with no YAML library: this runs on a Mac's plain python3 before the one apply into a shared namespace. Each line is
    required exactly, once, and a second document is refused, so no other realm or namespace can hide in the file."""
    text = open(path).read()
    if re.search(r"^---", text, re.M) or re.search(r"^\.\.\.", text, re.M):
        raise Stop(f"{path} holds more than one document")
    required = (r"^kind: KeycloakRealmImport$", r"^metadata:$", r"^  name: cmapi$", r"^  namespace: keycloak$", r"^spec:$",
                r"^  keycloakCRName: keycloak$", r"^  realm:$", r"^    realm: cmapi$")
    for pattern in required:
        if len(re.findall(pattern, text, re.M)) != 1:
            raise Stop(f"{path}: must hold exactly one line matching {pattern}")
    # Any other top-level or metadata name, or a realm key at the realm's indent, would be a second answer to the same question.
    if re.findall(r"^    (?:realm|id): (?!cmapi$).*$", text, re.M):
        raise Stop(f"{path}: spec.realm names a realm other than cmapi")
    print(f"{now()} {os.path.basename(path)}: KeycloakRealmImport cmapi, realm cmapi, namespace keycloak")


def watch(log: str, stop_file: str, baseline_file: str) -> int:
    base = json.load(open(baseline_file))
    realms = sorted(base["realms"])
    breach_since = None
    reported = recovered = False
    rc = 0
    with open(log, "a", buffering=1) as f:
        def say(line: str) -> None:
            f.write(f"{now()} {line}\n")
        say(f"watch: every {POLL_SECONDS:g} s, realms {realms}")
        while not os.path.exists(log + ".done"):
            t0 = time.monotonic()
            problems = []
            statuses = {}
            for r in realms:
                s = realm_state(r, timeout=3)
                statuses[r] = s["status"]
                if s["status"] != 200:
                    problems.append(f"{r}={s['status']}")
                elif s["public_key_sha256"] != base["realms"][r]["public_key_sha256"]:
                    problems.append(f"{r}: public key changed")
            try:
                kc = pod_state("keycloak-0")
                b = base["keycloak-0"]
                if (kc["uid"], kc["restarts"], kc["started"]) != (b["uid"], b["restarts"], b["started"]):
                    problems.append(f"keycloak-0 restarted: {kc}")
                elif not kc["ready"]:
                    problems.append("keycloak-0 not Ready")
            except (Stop, KeyError, subprocess.TimeoutExpired) as e:
                kc = {}
                problems.append(f"keycloak-0 unreadable: {str(e)[:120]}")
            say(f"realms {statuses} keycloak-0 {kc.get('restarts')}/{kc.get('ready')} {'BREACH ' + '; '.join(problems) if problems else 'ok'}")
            down = any(s != 200 for s in statuses.values()) or not kc.get("ready")
            if problems and breach_since is None:
                breach_since = time.monotonic()
                rc = 3
                open(stop_file, "a").close()
                say("STOP: every cmapi step stops now. cmapi takes no action on Keycloak: no delete, no restart. Report to the owner")
                print(f"{now()} BREACH, the run is stopped: {'; '.join(problems)}", flush=True)
            if breach_since is not None:
                waited = time.monotonic() - breach_since
                if down and waited >= REPORT_AFTER_SECONDS and not reported:
                    reported = True
                    say(f"REPORT TO THE OWNER NOW: Keycloak still not back after {int(waited)} s; the one measured restart took 162 s")
                    print(f"{now()} REPORT TO THE OWNER NOW: Keycloak not back after {int(waited)} s", flush=True)
                if not down and not recovered:
                    recovered = True
                    say(f"Keycloak answers again after {int(waited)} s; the run stays stopped")
            time.sleep(max(0.0, POLL_SECONDS - (time.monotonic() - t0)))
        say(f"watch ended rc={rc}")
    return rc


def import_pods() -> list[dict]:
    return oc_json("get", "pods", "-n", NS, "-l", f"job-name={OURS}").get("items", [])


def container_started(pod: dict) -> bool:
    for c in pod.get("status", {}).get("containerStatuses") or []:
        st = c.get("state", {})
        if "running" in st or "terminated" in st:
            return True
    return False


def withdraw(reason: str) -> None:
    """Delete our import, by name and only by name. The operator owns its Job and Secret through owner references (GarbageCollected,
    KeycloakRealmImportJobDependentResource.java:59), so they go with it, and a pod that has not started never will."""
    print(f"{now()} withdrawing KeycloakRealmImport {OURS}: {reason}", flush=True)
    oc("delete", "keycloakrealmimport", OURS, "-n", NS, "--wait=true", "--timeout=60s")
    left = oc("get", "job", OURS, "-n", NS, "--ignore-not-found", "-o", "name").strip()
    print(f"{now()} withdrawn; Job left: {left or 'none'}; realm cmapi is {issuer_state()}", flush=True)


def import_wait(stop_file: str) -> int:
    t0 = time.monotonic()
    started_at = None
    while True:
        kri = oc_json("get", "keycloakrealmimport", OURS, "-n", NS, "--ignore-not-found")
        if not kri:
            raise Stop(f"KeycloakRealmImport {OURS} is not there")
        pods = import_pods()
        started = any(container_started(p) for p in pods)
        if started and started_at is None:
            started_at = time.monotonic()
            print(f"{now()} the import's container started {int(started_at - t0)} s after the apply", flush=True)
        if condition(kri, "Done") == "true" and condition(kri, "HasErrors") != "true":
            state = issuer_state()
            print(f"{now()} import Done after {int(time.monotonic() - t0)} s; realm cmapi is {state}")
            return 0 if state == "present" else 1
        if condition(kri, "HasErrors") == "true" and started:
            # The Job has no backoffLimit of its own (buildJob sets none), so Kubernetes' default of 6 would start more pods.
            withdraw("the import failed; this stops the Job's further attempts")
            return 1
        if not started and os.path.exists(stop_file):
            withdraw("the run is stopped and the import has not started")
            return 1
        if not started and time.monotonic() - t0 > SCHEDULE_DEADLINE:
            phases = [p.get("status", {}).get("phase") for p in pods]
            withdraw(f"not started after {int(SCHEDULE_DEADLINE)} s (pods {phases}); left alone it could start unattended, days later")
            return 1
        if started and time.monotonic() - started_at > RUN_DEADLINE:
            print(f"{now()} the import has run {int(RUN_DEADLINE)} s without finishing. It is not interrupted; report to the owner", flush=True)
            return 1
        time.sleep(POLL_SECONDS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight"); p.add_argument("--needs", type=int, default=0)
    p = sub.add_parser("headroom"); p.add_argument("--needs", type=int, required=True)
    p = sub.add_parser("check-import"); p.add_argument("file")
    sub.add_parser("issuer")
    p = sub.add_parser("snapshot"); p.add_argument("file")
    p = sub.add_parser("compare"); p.add_argument("before"); p.add_argument("after")
    p = sub.add_parser("watch"); p.add_argument("log"); p.add_argument("stop_file"); p.add_argument("baseline")
    p = sub.add_parser("gate"); p.add_argument("stop_file")
    p = sub.add_parser("import-wait"); p.add_argument("stop_file")
    a = ap.parse_args()
    try:
        if a.cmd == "preflight":
            preflight(a.needs)
        elif a.cmd == "headroom":
            need_headroom(a.needs)
        elif a.cmd == "check-import":
            check_import(a.file)
        elif a.cmd == "issuer":
            state = issuer_state()
            print(f"realm cmapi: {state}")
            return {"present": 0, "absent": 10}.get(state, 20)
        elif a.cmd == "snapshot":
            s = snapshot()
            with open(a.file, "w") as f:
                json.dump(s, f, indent=1, sort_keys=True)
            print(f"{now()} snapshot: {len(s['realms'])} realms, {len(s['imports'])} other imports, keycloak-0 restarts {s['keycloak-0']['restarts']}")
        elif a.cmd == "compare":
            d = diff(json.load(open(a.before)), json.load(open(a.after)))
            if d:
                raise Stop("something changed:\n  " + "\n  ".join(d))
            print(f"{now()} no difference: {os.path.basename(a.before)} and {os.path.basename(a.after)}")
        elif a.cmd == "watch":
            return watch(a.log, a.stop_file, a.baseline)
        elif a.cmd == "gate":
            if os.path.exists(a.stop_file):
                raise Stop("the watch has stopped this run; nothing more runs until the owner has been told")
        elif a.cmd == "import-wait":
            return import_wait(a.stop_file)
    except Stop as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```


## 14. The backup of the shared Keycloak database

Owner-approved, on the coordinator's terms. **The step immediately before the import: step 11,** with the watch already running, compared afterwards at step 12.

**The command.** `deploy/crc-backup.sh`. The core is:

```bash
oc exec postgres-0 -n keycloak -c "$CONTAINER" -- sh -c '<$DBENV> exec pg_dump -w -Fc --lock-wait-timeout=30s -U "$U" "$D"' >"$DIR/keycloak-<UTC>.dump"
```

**Authentication. I could not read `postgres-0`'s spec,** since this brief forbids `oc`. So the design has a required first step, and fails closed instead of assuming:

- `deploy/crc-backup.sh --inspect` prints the container, image, the env **names** with where each comes from (a literal is shown as "value not shown"), and limits. The coordinator reads that before the run, and the design's variable list is corrected if it is neither image below.
- The script's in-pod shell takes `POSTGRES_USER`/`POSTGRES_DB`/`POSTGRES_PASSWORD` (official image) or `POSTGRESQL_USER`/`POSTGRESQL_DATABASE`/`POSTGRESQL_PASSWORD` (Red Hat's), and exports `PGPASSWORD` from them. **So any credential is read inside the pod, by the pod's own shell: it is on no argument list on the Mac or in the pod, and in no log.** `-w` fails rather than prompts. The official image also trusts its local socket (measured: `pg_hba.conf` has `local all all trust`), in which case no password is used at all. On Red Hat's image, a local socket may be `peer` for a non-superuser: that fails, `--inspect` tells, and the run stops at this step.
- No credential is read to the Mac. A bad guess is a failed dump and a stopped run.

**The stream.** `pg_dump` to stdout, `oc exec` **without `-t`**, redirected on the Mac. Nothing is written in the pod. `oc exec` passes the remote exit status (inferred; measured with `podman exec`, the same shape: rc 1, 0 bytes, on a bad database).

**Storage.** `~/.cmapi-keycloak-backup/`, 0700, file 0600, `umask 077`, a symbolic link refused. `tmutil addexclusion` on the directory (measured to work), since Time Machine would otherwise copy every realm's secrets where the delete cannot reach. Outside Git. Output names only the directory's basename and counts. `--delete` after the run. **A limit:** deleting a file on APFS does not wipe its blocks, and a local snapshot may hold it (inferred).

**Proving it usable, before the import.** Measured on a real Keycloak database: **`pg_restore --list` is not enough.** A file missing its last 100 bytes lists with rc 0, because the table of contents is at the front. A full read catches it: `pg_restore -f /dev/null` fails with `could not read from input file: end of file`, on both a half file and a file 100 bytes short. So, in order, any failure stops the run and removes the file:

1. Non-empty, and starts with `PGDMP`.
2. `pg_restore --list` lists table data.
3. `pg_restore -f /dev/null` reads to the end.
4. Rows of `realm` in the archive equal `select count(*) from realm`.

**These run on the pod's own `pg_restore`, over `oc exec -i`:** it matches the server's major version, this Mac has no `pg_restore` (measured), and the content goes nowhere it is not already. Nothing is written there. Measured end to end, with `oc exec` stubbed to `podman exec`, on PostgreSQL 16.15: backup passes, modes right, no path or content in the output, realm rows counted with odd ids.

**Full test restore into a throwaway container: not proportionate, so not done on the real dump.** It would write every realm's secrets to a container layer in the podman VM, breaking the owner's term that the contents go nowhere else, and it adds only that the SQL is accepted. That property is measured here on test data instead: a Keycloak dump into an empty PostgreSQL 16, 2 s, its 3 realms back; and `--clean --if-exists --single-transaction` over a changed database, rc 0, rows back as dumped, **but a table created after the dump survives.** So the restore below goes into an empty database. If the owner wants a test restore of the real dump, it is their call.

**What it does to the running Keycloak (read, `app-pgdump.html`):** "pg_dump does not block other users accessing the database (readers or writers)". It holds ACCESS SHARE locks for the length of the dump, one connection, one snapshot. It conflicts only with DDL's ACCESS EXCLUSIVE, which Keycloak does not issue while running (inferred). `--lock-wait-timeout`: "Do not wait forever to acquire shared table locks at the beginning of the dump. Instead fail if unable", measured to fail within 3 s against a held lock at 2 s. That matters because a queued lock request could hold others behind it. **Load:** one connection, whose CPU and memory come out of `postgres-0`'s own cgroup. So it stops if under 128 Mi of room below the limit or under 5 free connections. `pg_dump`'s peak was 6.2 MB on a dump of 260 KB (measured); the real one is bigger. A dump held open also delays vacuum for its seconds.

**A dump failing partway:** the server ends that transaction; nothing changes on it. The script removes the partial file by trap, and **the run stops.** A test on each failure mode leaves no file.

**Restoring (document only; never automatic, and no script does it).** Restoring rolls **every realm** back to that moment: `corp`, `inkcast-*`, users, clients, keys and sessions, losing anything any project did since. **It is the owner's decision alone, and nothing in cmapi's steps ever triggers it.** Rollback of Wave 1 does not need it (section 9). If the owner decides:

1. Say which other projects lose what, and tell them.
2. Stop Keycloak, as the owner: `oc patch keycloak keycloak -n keycloak --type=merge -p '{"spec":{"instances":0}}'`; wait for `keycloak-0` to go. All realms are now down.
3. Move the current database aside, within `postgres-0`, keeping it until the outcome is verified: `ALTER DATABASE <db> RENAME TO <db>_before_restore; CREATE DATABASE <db> OWNER <owner>;`, using the variables as above.
4. Restore into the empty database, from the Mac: `oc exec -i postgres-0 -n keycloak -c <container> -- sh -c '<DBENV> exec pg_restore -w --single-transaction -U "$U" -d "$D"' < <the file>`. Stop on any error, and rename back.
5. Start Keycloak: `{"spec":{"instances":1}}`. Expect at least 2 min 42 s.
6. Compare with `s0.json`, realm by realm. Keep the file until it agrees. Then drop `<db>_before_restore`, and delete the file.

Not measured as a whole: steps 2 and 3 have not been run anywhere.

`deploy/crc-backup.sh`:

```bash
#!/usr/bin/env bash
# shellcheck disable=SC2016  # the single-quoted scripts run in the pod, on the pod's environment, which is the point
# deploy/crc-backup.sh: the owner-approved, read-only backup of the shared Keycloak database, taken as the step immediately before the realm import.
#   --inspect   what the backup would use, from the pod spec: container, image, env NAMES with where each comes from, the memory limit. Never a value.
#   (no flag)   dumps, proves the file usable, and stops the run on any failure.
#   --delete    removes the backup once the run is verified.
# The dump holds every realm's secrets and users. It is never written inside the pod (stdout, over oc exec), never leaves ~/.cmapi-keycloak-backup (0700, file 0600),
# and nothing here prints its path beyond that directory or any of its content: only byte and row counts. Credentials stay in the pod's own environment,
# expanded by the pod's shell: nothing reaches this Mac's argument list or a log. Restoring is the owner's decision, never automatic (docs/13, "Restoring").
set -euo pipefail
OC=${CMAPI_OC:-oc}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
DIR=${CMAPI_BACKUP_DIR:-$HOME/.cmapi-keycloak-backup}
POD=postgres-0; NS=keycloak
MIN_ROOM_MI=${CMAPI_BACKUP_MIN_ROOM_MI:-128}
# Runs inside postgres-0. Which variables exist is the image's: the official image's or Red Hat's. Empty stops it. -w: fail, never prompt.
DBENV='U=${POSTGRES_USER:-${POSTGRESQL_USER:-}}; D=${POSTGRES_DB:-${POSTGRESQL_DATABASE:-}}; P=${POSTGRES_PASSWORD:-${POSTGRESQL_PASSWORD:-}}; [ -n "$U" ] && [ -n "$D" ] || { echo "no database user or name in this environment" >&2; exit 64; }; export PGPASSWORD="$P";'
in_pod() { oc_ exec "$POD" -n "$NS" -c "$CONTAINER" -- sh -c "$DBENV $1"; }
in_pod_stdin() { oc_ exec -i "$POD" -n "$NS" -c "$CONTAINER" -- sh -c "$1"; }
container() { oc_ get pod "$POD" -n "$NS" -o json | python3 -c 'import json,sys
c=json.load(sys.stdin)["spec"]["containers"]
if len(c)!=1: sys.exit("postgres-0 has %d containers; say which by hand" % len(c))
print(c[0]["name"])'; }
inspect() {
  oc_ get pod "$POD" -n "$NS" -o json | python3 -c 'import json,sys
for c in json.load(sys.stdin)["spec"]["containers"]:
    print("container",c["name"],"image",c.get("image"))
    print("memory",c.get("resources",{}))
    for e in c.get("env",[]):
        src=e.get("valueFrom")
        print("env",e["name"],"from "+json.dumps({k:{x:v for x,v in s.items() if x in("name","key")} for k,s in src.items()}) if src else "(literal; value not shown)")
    for e in c.get("envFrom",[]):
        print("envFrom",json.dumps(e))'
}
room_mi() { # limit minus usage, from the metrics API. No limit is plenty; no reading is a stop, not a guess.
  local limit used
  limit=$(oc_ get pod "$POD" -n "$NS" -o 'jsonpath={.spec.containers[0].resources.limits.memory}')
  used=$(oc_ adm top pod "$POD" -n "$NS" --no-headers | awk '{print $3}')
  python3 -c 'import re,sys
def mi(q):
    m=re.fullmatch(r"(\d+)(Ki|Mi|Gi)?",q)
    if not m: sys.exit("cannot read the quantity "+repr(q))
    return int(m[1])*{"Ki":1/1024,"Mi":1,"Gi":1024,None:1/1048576}[m[2]]
print(int(mi(sys.argv[1])-mi(sys.argv[2])) if sys.argv[1] else 999999)' "$limit" "$used"
}
backup() {
  [ ! -L "$DIR" ] || { echo "ERROR: the backup directory is a symbolic link; refusing it" >&2; exit 1; }
  ( umask 077; mkdir -p "$DIR" ); chmod 700 "$DIR"
  # Time Machine must not copy every realm's secrets somewhere the delete cannot reach.
  if command -v tmutil >/dev/null 2>&1; then tmutil addexclusion "$DIR" >/dev/null 2>&1 || echo "note    : could not exclude the backup directory from Time Machine" >&2; fi
  CONTAINER=$(container)
  room=$(room_mi); [ "$room" -ge "$MIN_ROOM_MI" ] || { echo "ERROR: postgres-0 has $room Mi of room under its limit; pg_dump runs in that container's cgroup, and it must not push the shared database towards an OOM kill" >&2; exit 1; }
  slots=$(in_pod 'psql -w -U "$U" -d "$D" -Atc "select current_setting('"'"'max_connections'"'"')::int - count(*) from pg_stat_activity"')
  [ "$slots" -ge 5 ] || { echo "ERROR: only $slots free connections on the shared database" >&2; exit 1; }
  F=$DIR/keycloak-$(date -u +%Y%m%dT%H%M%SZ).dump
  trap 'rm -f "$F" "$F.err"; echo "the partial backup is removed" >&2' ERR INT TERM
  ( umask 077; : >"$F"; : >"$F.err" ); chmod 600 "$F" "$F.err"
  t0=$(date +%s)
  # Custom format, one connection, a snapshot, no lock any writer waits on. --lock-wait-timeout: fail rather than queue behind DDL, because a queued lock would hold others up.
  in_pod 'exec pg_dump -w -Fc --lock-wait-timeout=30s -U "$U" "$D"' >"$F" 2>"$F.err" || { echo "ERROR: the dump failed: $(tail -1 "$F.err" | cut -c1-200)" >&2; false; }
  bytes=$(wc -c <"$F" | tr -d ' ')
  [ "$bytes" -gt 0 ] || { echo "ERROR: the dump is empty" >&2; false; }
  [ "$(head -c 5 "$F")" = PGDMP ] || { echo "ERROR: the dump does not start as a custom-format archive" >&2; false; }
  # Proven on the pod's own pg_restore: the same major version, nothing new holds the content, nothing is written there. --list alone misses a lost tail (measured:
  # a file 100 bytes short lists with rc 0), so the whole archive is read too, to /dev/null.
  entries=$(in_pod_stdin 'pg_restore --list | grep -c "TABLE DATA"' <"$F") || { echo "ERROR: pg_restore --list refused the archive" >&2; false; }
  [ "$entries" -gt 0 ] || { echo "ERROR: no table data in the archive" >&2; false; }
  in_pod_stdin 'pg_restore -f /dev/null' <"$F" 2>>"$F.err" || { echo "ERROR: the archive does not read to its end: $(tail -1 "$F.err" | cut -c1-200)" >&2; false; }
  live=$(in_pod 'psql -w -U "$U" -d "$D" -Atc "select count(*) from realm"')
  dumped=$(in_pod_stdin 'pg_restore -a -t realm -f - | awk "/^COPY /{c=1;next} /^\\\\\\./{c=0} c{n++} END{print n+0}"' <"$F") || dumped=0
  [ "$live" = "$dumped" ] || { echo "ERROR: $live realms in the database, $dumped in the dump" >&2; false; }
  rm -f "$F.err"
  trap - ERR INT TERM
  echo "backup in $(basename "$DIR"): $bytes bytes in $(( $(date +%s) - t0 )) s, $entries tables with data, $dumped realms, read to its end"
}
case "${1:-}" in
  --inspect) inspect ;;
  --delete) [ ! -L "$DIR" ] || { echo "ERROR: the backup directory is a symbolic link" >&2; exit 1; }
            n=$(find "$DIR" -type f -name 'keycloak-*' 2>/dev/null | wc -l | tr -d ' ')
            find "$DIR" -type f -name 'keycloak-*' -delete 2>/dev/null || true; rmdir "$DIR" 2>/dev/null || true; echo "deleted $n file(s) from $(basename "$DIR")" ;;
  "") backup ;;
  *) sed -n '3,6p' "$0" >&2; exit 2 ;;
esac
```


## 15. What I found wrong

| Where | What it says | Evidence |
|---|---|---|
| Coordinator's item 6 | Rollback cannot delete the realm without a master credential | 204 with the realm's own `cmapi-realm-admin`, source agrees, 26.6.4 measured. Section 9. The default still leaves it |
| Keycloak CRD text, and so the brief's reading | Import's resources "inherited from the Keycloak CR" | `Utils.addResources` uses the operator's default 1700Mi/2Gi; that is the coordinator's measured 1700Mi. Settable |
| Coordinator's backup term | "at least `pg_restore --list`" | `--list` passes a truncated file (measured). Full read added |
| `realm_sync.py:189` | A sync "ok" on 200, 400, 500 | An unreachable directory is 200 with zero counts (measured); a Job would be Complete with no federation. **File a bug**; fixed by `requireSync` |
| Tracker, Wave 1 "Owner step: None" | No owner step | Neither CA is in this Mac's keychain (measured); Chrome needs them, and macOS asks for a password. Also possibly a person's LDAP password |
| `secrets.sh:17-18`, README | Keep the import while the realm exists | The operator's guide says delete it; a kept CR can restart a Job if its Job goes; ruling 7's check replaces the need |
| `docs/11` | "one `KeycloakRealmImport` named `cmapi`" stays | Update: applied once, then deleted. Also `master`'s client, which it does not mention |
| `release-crc.sh:73,93` | Token on an argument; `podman push --cert-dir` | Both are against the rules or do not work on this Mac (measured). It leaves with the charts; do not reuse |
| `crc.yaml:93-95` | Bundle includes the ingress CA | No pod needs it in Wave 1; dropped |
| `render-test.sh:37` | `cp -R kind crc` | Nests once `crc` exists. Removed |
| CI's kubeconform | Would stop on `Route` | Not in the pinned catalog (404, measured). `-skip Route`, and a test |
| Issue: "the Route answering through the NetworkPolicy" | As the proof | Passes with no enforcement too. Blocked probe added |
| Red Hat's restart article | Quoted in the tracker as a risk | Right for 26.0.8 (source), not for 26.6.7's source. Keep the guard, since the cause of the one measured restart is unknown |
| `context.py:92-95` with `cmapi-trust` | | GitHub's TLS will fail in Wave 3 with a private-CA-only bundle (read, not run). File it |
| Brief, on the CRC CA | `default-ingress-cert` as Keycloak's CA | Already corrected by the coordinator; `docs/11` had it right |

## 16. Measured, inferred, not checked

**Measured here** (`output/exp/`), on community Keycloak 26.6.4, PostgreSQL 16.15, OpenLDAP stand-in, this Mac:

- Import: three runs and memory, section 4; no restart beside a live server; other realms' keys unchanged; rerun skipped; no secret in the log; `master` gets a client.
- `realm-test.py` 24 of 24 on the final files; sync, LDAP login, claims; `requireSync` on a broken directory; realm self-delete 204, others' 403.
- Issuer's 404 body. `--list` against truncated files. `pg_dump` rc, memory, lock timeout. Test restores. Backup script against real PostgreSQL through a stubbed exec.
- `podman push --cert-dir` failing; `skopeo` by CA, digest, label; a wrong CA refused.
- `nginx-unprivileged` and the cmapi image under an arbitrary UID, group 0, no capabilities: nginx serves 200; `cmapi-tools` runs. Not `restricted-v2`.
- `spec.realm` and `PrometheusRule` equal the chart's; policy files equal kind's; schemas via `jsonschema`.
- Python 3.14's strict flag. No CA in the keychain. `tmutil addexclusion`. `render-test.sh`, `shellcheck`, `ci-guard.py`, `mutate-secrets.py` 30 of 30, `crc-scripts-test.sh` 77 checks, `test_plain_manifests.py` 38 passed. `crc-guard-test.py`: 56 cases, 15 of 15 mutants killed.

**Coordinator's, taken as given:** every fact about CRC, including the corrections.

**Read:** the operator's source at 26.6.7 and 26.0.8 and `26.6.9-redhat2`'s controller; `realm-import.adoc`, `advanced-configuration.adoc`; `RealmAdminResource`; PostgreSQL's `pg_dump` and `pg_restore` pages; Kubernetes' NetworkPolicy and eviction pages; podman-push. Sources saved in `output/sources/`.

**Inferred:** RHBK's operator matches community source at that version; same-namespace image pull and the SA race; the router through the policy; user workload Prometheus's network and its `job` label; `oc exec` exit status; `users/~` for every authenticated user; Thanos Ruler for platform metrics; CNPG's initdb job size; blobs and PV directories remaining; APFS. Scheduling as the cause of the 6.5 days is the coordinator's inference.

**Could not check:** OpenShift's own NetworkPolicy page (403, and navigation only from OKD's); the Red Hat article's body (login); `postgres-0`'s spec; the real LDAP people; `kubeconform` locally (standing refusal); anything on CRC; `crc-proof.sh` against anything real; the full `service` suite (needs its database and full dependencies, and I ran only the static and path-loaded tests).

**No refusals** of any command occurred in this work. I removed all `cmapi-design-*` and `cmapi-rt-*` containers. One render wrote to `/tmp/x-should-not`, and one command made an empty `/tmp/x`; both were outside `output/` by mistake, and both are removed. Test scripts use `mktemp` under the system temp directory and remove what they make. `cmapi-test-pg` was not touched.

## Appendix: the other changes in full


`patches/kind-test.sh.diff`:

```diff
--- a/deploy/kind-test.sh
+++ b/deploy/kind-test.sh
@@ -53,7 +53,7 @@
 rm -f "$T/image.tar"
 k apply -f "$HERE/manifests/environments/kind/00-namespaces.yaml" >/dev/null
 k apply -f "$HERE/manifests/environments/kind/" >/dev/null; say "environments/kind applied"
-"$HERE/secrets.sh" --namespace cmapi --realm-namespace cmapi-imports --kubectl "kubectl --kubeconfig=$KC" --no-ldap-bind
+"$HERE/secrets.sh" --namespace cmapi --realm-namespace cmapi-imports --kubectl "kubectl --kubeconfig=$KC" --no-ldap-bind --no-issuer-check
 "$HERE/render.sh" kind "$IMAGE" "$T/rendered" --allow-tag
 # Server-side: the mockup ConfigMap (300 KB) is over the 256 KiB a client-side apply writes into its last-applied
 # annotation (measured: "metadata.annotations: Too long"); Argo CD applies server-side too (ServerSideApply=true).
```


`patches/secrets-test.sh.diff`:

```diff
--- a/deploy/secrets-test.sh
+++ b/deploy/secrets-test.sh
@@ -12,8 +12,8 @@
 k create ns sect1 >/dev/null 2>&1 || true; k create ns sect2 >/dev/null 2>&1 || true
 # The kubectl command carries its --kubeconfig, so it is one argument: an array, never a word-split string (the first
 # run of this harness split it and secrets.sh refused "--kubeconfig=..." as an unknown argument).
-A=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind)
-B=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL")
+A=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind --no-issuer-check)
+B=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-issuer-check)
 S="$HERE/secrets.sh"
 T=$(mktemp); ALL=$(mktemp); VALUES=$(mktemp); W=$(mktemp -d)
 trap 'rm -rf "$T" "$ALL" "$VALUES" "$W"; k delete ns sect1 sect2 --wait=false >/dev/null 2>&1' EXIT
@@ -51,7 +51,7 @@
 chmod +x "$W/kubectl-failing"
 runf() { # the reads named in $1 fail; the writes still work
   local reads=$1; shift
-  FAIL_READS="$reads" "$S" --namespace sect1 --realm-namespace sect2 --kubectl "$W/kubectl-failing" --no-ldap-bind "$@" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
+  FAIL_READS="$reads" "$S" --namespace sect1 --realm-namespace sect2 --kubectl "$W/kubectl-failing" --no-ldap-bind --no-issuer-check "$@" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
 h() { k get secret cmapi-keycloak -n sect1 -o json 2>/dev/null | python3 -c 'import sys,json,hashlib; d=json.load(sys.stdin)["data"]; print(hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()[:12])' 2>/dev/null || echo none; }
 fails=0
 run() { "$S" "${A[@]}" "$@" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
@@ -173,6 +173,35 @@
 # One line naming the mode: GNU stat -f once put the file system's details in the message (#90), and the rc alone cannot see it.
 grep -qxF "ERROR: $KEYF is mode 644; make it 0600" "$T" || { echo "  FAIL 10c: the ERROR line is not the mode alone"; fails=$((fails+1)); }
 rm -f "$KEYF"
+# 11: ruling 7, the realm asked before anything is minted. A curl stub answers what ISSUER_CODE and ISSUER_BODY say; ISSUER_RC is curl's own failure.
+mkdir -p "$W/bin"; cat >"$W/bin/curl" <<'CURL'
+#!/usr/bin/env bash
+printf '%s\n' "$*" >>"$CURL_LOG"
+[ "${ISSUER_RC:-0}" = 0 ] || exit "$ISSUER_RC"
+out=; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
+printf '%s' "$ISSUER_BODY" >"$out"; printf '%s' "$ISSUER_CODE"
+CURL
+chmod +x "$W/bin/curl"; export CURL_LOG="$W/curl.log"; : >"$CURL_LOG"
+printf 'not a real CA\n' >"$W/ca.pem"
+I=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind --issuer https://kc.test/realms/cmapi --ca-file "$W/ca.pem")
+runi() { PATH="$W/bin:$PATH" ISSUER_CODE=$1 ISSUER_BODY=$2 ISSUER_RC=${3:-0} "$S" "${I[@]}" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
+k delete secret cmapi-keycloak cmapi-keys -n sect1 >/dev/null 2>&1; k delete secret cmapi-realm-secrets -n sect2 >/dev/null 2>&1
+r=$("$S" --namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind >"$T" 2>&1; echo "rc=$? $(tail -1 "$T")"); expect "11a neither --issuer nor --no-issuer-check stops" 2 "$r"; none_written 11a
+r=$(runi 200 '{"realm":"cmapi","public_key":"x"}'); expect "11b the realm exists, both Secrets gone: stops" 1 "$r"; said "11b it says so" "exists at"; none_written 11b
+r=$(runi 503 '<html>Application is not available</html>'); expect "11c a router's 503 during a restart is not absent" 1 "$r"; said "11c it cannot tell" "cannot tell"; none_written 11c
+r=$(runi 404 '<html>not found</html>'); expect "11d a 404 that is not Keycloak's is not absent" 1 "$r"; said "11d it cannot tell" "cannot tell"; none_written 11d
+r=$(runi 200 '{"realm":"corp"}'); expect "11e a 200 for another realm is not this realm, and not absent" 1 "$r"; none_written 11e
+r=$(runi 000 '' 28); expect "11f a timeout is not absent" 1 "$r"; said "11f it cannot tell" "cannot tell"; none_written 11f
+r=$(runi 000 '' 60); expect "11g a certificate failure is not absent" 1 "$r"; none_written 11g
+grep -q -- '--cacert' "$CURL_LOG" || { echo "  FAIL 11: the CA file was not used"; fails=$((fails+1)); }
+if grep -qE -- '(^| )(-k|--insecure)( |$)' "$CURL_LOG"; then echo "  FAIL 11: TLS verification was turned off"; fails=$((fails+1)); fi
+r=$(runi 404 '{"error":"Realm does not exist"}'); expect "11h Keycloak's own 404: generates" 0 "$r"; [ "$(h)" != none ] || { echo "  FAIL 11h: nothing written"; fails=$((fails+1)); }
+: >"$CURL_LOG"; r=$(runi 503 'down'); expect "11i Secrets present: nothing to mint, Keycloak not needed" 0 "$r"; [ ! -s "$CURL_LOG" ] || { echo "  FAIL 11i: asked the issuer when nothing was to be minted"; fails=$((fails+1)); }
+collect
+# 12: the test users are written once and kept.
+r=$(run --test-users); expect "12a test users written" 0 "$r"; U1=$(hs sect1 cmapi-test-users); [ "$U1" != none ] || { echo "  FAIL 12a"; fails=$((fails+1)); }; collect
+r=$(run --test-users); expect "12b test users kept" 0 "$r"; same "12b not rotated" "$U1" "$(hs sect1 cmapi-test-users)"
+k delete secret cmapi-keycloak cmapi-keys cmapi-test-users -n sect1 >/dev/null 2>&1; k delete secret cmapi-realm-secrets -n sect2 >/dev/null 2>&1
 # Nothing secret may have reached the output of any case: every value the cases generated, encoded and decoded, against
 # everything every run printed. The count alone is printed, never a match.
 [ -s "$VALUES" ] || { echo "  FAIL: the scan collected no values"; fails=$((fails+1)); }
```


`patches/mutate-secrets.py.diff`:

```diff
--- a/deploy/tests/mutate-secrets.py
+++ b/deploy/tests/mutate-secrets.py
@@ -61,6 +61,15 @@
     "S a Secret written before the cmapi-ldap-bind check": [(LDAP_CHECK, EARLY_WRITE + LDAP_CHECK)],
     "T a Secret written before the check of an existing app Secret": [(APP_CHECK, APP_CHECK.replace("then\n", "then\n" + EARLY_WRITE))],
     "U a Secret written before the key file's checks": [(KEY_FILE_CHECK, KEY_FILE_CHECK.replace("then\n", "then\n" + EARLY_WRITE))],
+    "W the issuer check is not made": [('    if [ "$ISSUER_CHECK" = true ]; then\n      state=$(issuer_state)', '    if false; then\n      state=$(issuer_state)')],
+    "X anything but a 200 reads as absent": [('        *) echo "ERROR: cannot tell whether the realm exists at $ISSUER: $state. Nothing is generated. Run this again when Keycloak answers." >&2; exit 1 ;;', '        *) ;;')],
+    "Y any 404 reads as absent": [("""elif c=="404" and d=={"error":"Realm does not exist"}: print("absent")""", """elif c=="404": print("absent")""")],
+    "Z a curl failure reads as absent": [('if [ "$rc" -ne 0 ]; then rm -f "$body"; echo "no answer (curl rc $rc)"; return; fi', 'if [ "$rc" -ne 0 ]; then rm -f "$body"; echo absent; return; fi')],
+    "AA forgetting the flag skips the check": [('if [ "$ISSUER_CHECK" = true ] && [ -z "$ISSUER" ]; then echo "ERROR: --issuer is required (or --no-issuer-check on a cluster with no Keycloak)" >&2; exit 2; fi', 'if [ -z "$ISSUER" ]; then ISSUER_CHECK=false; fi')],
+    "AB verification off": [('code=$(curl -sS -m 15 ${CA_FILE:+--cacert "$CA_FILE"} -o', 'code=$(curl -k -sS -m 15 ${CA_FILE:+--cacert "$CA_FILE"} -o')],
+    "AC the issuer is asked after the first write": [
+        ('    if [ "$ISSUER_CHECK" = true ]; then\n      state=$(issuer_state)', '    printf \'CMAPI_REALM_ADMIN_SECRET %s\\n\' "$(b64 "$(rnd)")" | apply_secret "$REALM_NS" cmapi-realm-secrets >/dev/null\n    if [ "$ISSUER_CHECK" = true ]; then\n      state=$(issuer_state)')],
+    "AD the test users rotated on every run": [('  if [ -z "$users_existing" ]; then', '  if true; then')],
     "V the app Secret read after the writes again": [
         ('gh_existing=$(get "$NS" cmapi-github-app)\n', "gh_existing=\n"),
         ("# The GitHub App credential: validated", 'gh_existing=$(get "$NS" cmapi-github-app)\n# The GitHub App credential: validated')],
```


`patches/render-test.sh.diff`:

```diff
--- a/deploy/render-test.sh
+++ b/deploy/render-test.sh
@@ -34,10 +34,28 @@
 want "a tag with --allow-tag on kind" "--allow-tag refused on kind" quiet "$R" kind localhost/cmapi:dev "$W/o3" --allow-tag
 grep -q 'image: localhost/cmapi:dev' "$W/o3/components/cmapi/20-api.yaml" || bad "--allow-tag did not fill the image"
 # --allow-tag means a kind test, never a deployment.
-cp -R "$D/manifests/environments/kind" "$D/manifests/environments/crc"
 if "$R" crc localhost/cmapi:dev "$W/o4" --allow-tag >/dev/null 2>&1; then bad "--allow-tag was accepted for crc"; else ok "--allow-tag is refused for anything but kind"; fi
 # The internal registry's digest is what Wave 1 deploys, by digest; no flag that says "never a deployment".
 want "the internal registry by digest" "the internal registry's digest needs --allow-tag" quiet "$R" crc "$INTERNAL" "$W/o5"
+# Exactly five on CRC: the four, and the realm sync's Job, which only environments/crc carries. Every one filled, and the checksum over CRC's own three files.
+c=$(grep -r "sha256:DIGEST" "$D/manifests/environments/crc" | wc -l | tr -d ' ')
+want "one placeholder in environments/crc" "environments/crc holds $c placeholders, not 1" [ "$c" = 1 ]
+grep -q "sha256:DIGEST" "$D/manifests/environments/crc/realm/20-realm-sync.yaml" || bad "the placeholder is not the realm sync's"
+m=$(grep -rF "$INTERNAL" "$W/o5/components" "$W/o5/environment" | wc -l | tr -d ' ')
+want "five placeholders filled for crc" "$m filled for crc, not 5" [ "$m" = 5 ]
+want "the realm import has no image of ours" "the realm import names the image" sh -c "! grep -q cmapi@ '$W/o5/environment/realm/10-realm-import.yaml'"
+CK=$(grep -h 'checksum/config:' "$W/o5/components/cmapi/20-api.yaml" | sed -E 's/^ *checksum\/config: //')
+for f in 10-env 20-config 30-trust; do
+  cp "$D/manifests/environments/crc/$f.yaml" "$W/keep.yaml"; printf '# changed\n' >>"$D/manifests/environments/crc/$f.yaml"
+  "$R" crc "$INTERNAL" "$W/c5" >/dev/null; B=$(grep -h 'checksum/config:' "$W/c5/components/cmapi/20-api.yaml" | sed -E 's/^ *checksum\/config: //')
+  want "a changed crc $f changes the checksum" "a changed crc $f did not change the checksum" [ "$B" != "$CK" ]
+  cp "$W/keep.yaml" "$D/manifests/environments/crc/$f.yaml"
+done
+# A Route or a rule does not restart the pods, and the realm's files live outside what the checksum reads.
+cp "$D/manifests/environments/crc/realm/10-realm-import.yaml" "$W/keep.yaml"; printf '# changed\n' >>"$D/manifests/environments/crc/realm/10-realm-import.yaml"
+"$R" crc "$INTERNAL" "$W/c5" >/dev/null; B=$(grep -h 'checksum/config:' "$W/c5/components/cmapi/20-api.yaml" | sed -E 's/^ *checksum\/config: //')
+want "the realm import leaves the checksum" "the realm import changed the checksum" [ "$B" = "$CK" ]
+cp "$W/keep.yaml" "$D/manifests/environments/crc/realm/10-realm-import.yaml"
 if "$R" crc "registry.example.com/x@sha256:$(printf 'c%.0s' {1..64})" "$W/o6" >/dev/null 2>&1; then bad "another registry was accepted"; else ok "another registry is refused"; fi
 if "$R" crc "ghcr.io/evil/cmapi@sha256:$(printf 'c%.0s' {1..64})" "$W/o6" >/dev/null 2>&1; then bad "another GHCR repository was accepted"; else ok "another GHCR repository is refused"; fi
 if "$R" crc "ghcr.io/ephico2real2/cmapi@sha256:$(printf 'c%.0s' {1..63})" "$W/o6" >/dev/null 2>&1; then bad "a short digest was accepted"; else ok "a short digest is refused"; fi
```


`patches/ci-guard.py.diff`:

```diff
--- a/deploy/tests/ci-guard.py
+++ b/deploy/tests/ci-guard.py
@@ -24,7 +24,7 @@
 check(all(re.search(r"@[0-9a-f]{40}", s["uses"]) for s in steps if "uses" in s), "actions by full SHA")
 check("https://dl.k8s.io" in runs, "kubectl is pinned too: the runner's floats with the runner image")
 check("deploy/render-test.sh" in runs, "render.sh's result is checked, not only the absence of the placeholder")
-for script in ("deploy/secrets-test.sh", "deploy/tests/ci-guard.py", "deploy/tests/doc12-test.py", "deploy/tests/kind-test-stubbed.sh", "deploy/tests/mutate-secrets.py", "deploy/tests/np-reach-test.sh"):
+for script in ("deploy/secrets-test.sh", "deploy/tests/ci-guard.py", "deploy/tests/doc12-test.py", "deploy/tests/kind-test-stubbed.sh", "deploy/tests/mutate-secrets.py", "deploy/tests/np-reach-test.sh", "deploy/tests/crc-guard-test.py", "deploy/tests/crc-scripts-test.sh", "deploy/tests/realm-test.py"):
     check(script in runs, f"the job runs {script}")
 shellchecked = next(s["run"] for s in steps if s.get("name") == "Shellcheck")
 # The chart path's two scripts leave with the charts (Wave 4), and this job has never checked them.
```


`patches/ci.yml.diff`:

```diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -117,9 +117,9 @@
           chmod +x kubectl && sudo mv kubectl /usr/local/bin/
           kubectl version --client
           # The stubs and the guards read YAML.
-          python -m pip install pyyaml==6.0.2
+          python -m pip install pyyaml==6.0.2 httpx==0.28.1
       - name: Shellcheck
-        run: shellcheck deploy/render.sh deploy/render-test.sh deploy/secrets.sh deploy/secrets-test.sh deploy/mockup-configmap.sh deploy/kind-test.sh deploy/tests/*.sh deploy/tests/kind-test-stubs/* deploy/tests/secrets-stub/stub.sh
+        run: shellcheck deploy/render.sh deploy/render-test.sh deploy/secrets.sh deploy/secrets-test.sh deploy/mockup-configmap.sh deploy/kind-test.sh deploy/crc-image.sh deploy/crc-trust.sh deploy/crc-reader-import.sh deploy/crc-backup.sh deploy/crc-proof.sh deploy/crc-rollback.sh deploy/tests/*.sh deploy/tests/kind-test-stubs/* deploy/tests/secrets-stub/stub.sh
       - name: This job's own guards
         run: python deploy/tests/ci-guard.py .github/workflows/ci.yml
       - name: docs/12's commands and claims
@@ -128,13 +128,19 @@
         run: deploy/tests/kind-test-stubbed.sh
       - name: The secrets cases against mutants of secrets.sh, on a stub
         run: python deploy/tests/mutate-secrets.py
+      - name: The CRC guards, on a stub oc and a local TLS server
+        run: python deploy/tests/crc-guard-test.py
+      - name: The CRC scripts, on a stub oc
+        run: deploy/tests/crc-scripts-test.sh
+      - name: The realm on a real Keycloak and LDAP stand-in, beside other realms
+        run: python deploy/tests/realm-test.py deploy/manifests/environments/crc/realm/10-realm-import.yaml
       - name: The mockup ConfigMap is current
         run: deploy/mockup-configmap.sh --check
       - name: kubeconform on the manifests
         env:
           SCHEMAS: https://raw.githubusercontent.com/yannh/kubernetes-json-schema/102361970337d65537d40141dc29b991b8e95786/{{.NormalizedKubernetesVersion}}-standalone-strict/{{.ResourceKind}}{{.KindSuffix}}.json
           CRDS: https://raw.githubusercontent.com/datreeio/CRDs-catalog/c86448cbf1a840ca62d119259864863897c8748a/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json
-        run: kubeconform -strict -summary -kubernetes-version 1.35.0 -schema-location "$SCHEMAS" -schema-location "$CRDS" deploy/manifests/components deploy/manifests/environments
+        run: kubeconform -strict -summary -skip Route -kubernetes-version 1.35.0 -schema-location "$SCHEMAS" -schema-location "$CRDS" deploy/manifests/components deploy/manifests/environments
       - name: render.sh fills the placeholder and refuses a tag
         env:
           SCHEMAS: https://raw.githubusercontent.com/yannh/kubernetes-json-schema/102361970337d65537d40141dc29b991b8e95786/{{.NormalizedKubernetesVersion}}-standalone-strict/{{.ResourceKind}}{{.KindSuffix}}.json
@@ -143,11 +149,13 @@
           deploy/render.sh kind "ghcr.io/ephico2real2/cmapi@sha256:$(printf 'a%.0s' {1..64})" /tmp/rendered
           # An if, not "! grep": bash -e does not stop on a negated command, so that form could never fail the step.
           if grep -rn 'sha256:DIGEST' /tmp/rendered; then echo "a placeholder was left in the render"; exit 1; fi
-          kubeconform -strict -summary -kubernetes-version 1.35.0 -schema-location "$SCHEMAS" -schema-location "$CRDS" /tmp/rendered
+          kubeconform -strict -summary -skip Route -kubernetes-version 1.35.0 -schema-location "$SCHEMAS" -schema-location "$CRDS" /tmp/rendered
           if deploy/render.sh kind localhost/cmapi:dev /tmp/rendered-tag; then echo "a tag was accepted without --allow-tag"; exit 1; fi
           deploy/render.sh kind localhost/cmapi:dev /tmp/rendered-tag --allow-tag
           # Everything the render must do and must not do, on a throwaway copy: exactly the placeholder, nothing else changed.
           deploy/render-test.sh
+          deploy/render.sh crc "image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:$(printf 'a%.0s' {1..64})" /tmp/rendered-crc
+          kubeconform -strict -summary -skip Route -kubernetes-version 1.35.0 -schema-location "$SCHEMAS" -schema-location "$CRDS" /tmp/rendered-crc
       - name: kind for the secrets cases
         run: |
           curl -fsSL -o kind https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-linux-amd64
```


`cmapi/tests/service/test_plain_manifests.py`, appended:

```python


# ---------------------------------------------------------------- environments/crc (Wave 1)
CRC = ROOT / "deploy/manifests/environments/crc"


def crc_docs(pattern="**/*.yaml"):
    for f in sorted(CRC.glob(pattern)):
        for d in yaml.safe_load_all(f.read_text()):
            if d:
                yield d


def crc(kind, name):
    return next(d for d in crc_docs() if d["kind"] == kind and d["metadata"]["name"] == name)


def config_file(env, name):
    root = ROOT / "deploy/manifests/environments" / env / "20-config.yaml"
    return next(yaml.safe_load_all(root.read_text()))["data"][name]


def test_crc_has_exactly_one_more_image_placeholder_and_it_is_the_realm_sync():
    """Ruling: a Job on this image is a decision. components stays at four (test_every_image_is_the_placeholder_or_a_known_digest); CRC adds the realm sync, nothing else."""
    found = [(d["kind"], d["metadata"]["name"]) for d in crc_docs() for image in images(d) if image == PLACEHOLDER]
    assert found == [("Job", "cmapi-realm-sync")]
    assert [i for d in crc_docs() for i in images(d) if i != PLACEHOLDER] == []


@pytest.mark.parametrize("name", ["approval-rules.yaml", "authz-roles.yaml", "tiers.yaml", "expiration.yaml", "metadata-keys.yaml", "capacity.yaml"])
def test_crc_policy_files_are_the_kind_files(name):
    assert config_file("crc", name) == config_file("kind", name)


def test_crc_nothing_can_write_or_reach_a_git_host_in_wave_1():
    """No GitHub until Wave 3 and no Argo CD until Wave 5: delivery stays argocd, so the worker never writes to a cluster, the one cluster refuses writes, and the Git URL cannot resolve."""
    integrations = yaml.safe_load(config_file("crc", "integrations.yaml"))
    clusters = yaml.safe_load(config_file("crc", "clusters.yaml"))["clusters"]
    assert integrations["delivery"]["mode"] == "argocd"
    assert list(clusters) == ["CRC"] and clusters["CRC"]["writes"] is False and "delivery" not in clusters["CRC"]
    env = crc("ConfigMap", "cmapi-env")["data"]
    assert env["CMAPI_GIT_PROVIDER"] == "github", "settings.py's default is the provider that is leaving"
    assert env["CMAPI_GIT_URL"].endswith(".invalid"), "RFC 6761: it can never resolve"
    text = "\n".join(p.read_text() for p in CRC.rglob("*.yaml")).lower()
    assert "gitea" not in text and "cmapi-git" not in text


def test_crc_pods_reach_keycloak_by_its_service_and_tokens_carry_the_route():
    env = crc("ConfigMap", "cmapi-env")["data"]
    assert env["CMAPI_OIDC_JWKS_URL"] == "https://keycloak-service.keycloak.svc:8443/realms/cmapi/protocol/openid-connect/certs"
    assert env["CMAPI_KEYCLOAK_ADMIN_URL"] == "https://keycloak-service.keycloak.svc:8443"
    assert yaml.safe_load(config_file("crc", "instance.yaml"))["instance"]["auth"]["issuer"] == "https://keycloak.apps-crc.testing/realms/cmapi"


def test_crc_routes():
    """kubeconform skips Route: the pinned CRDs catalog has no schema for it (404, measured). So its shape is held here."""
    routes = {d["metadata"]["name"]: d["spec"] for d in crc_docs() if d["kind"] == "Route"}
    assert set(routes) == {"cmapi-api", "cmapi-mockup"}, "no portal Route: the portal does not run on the API yet"
    for name, spec in routes.items():
        assert set(spec) == {"host", "to", "port", "tls"}
        assert spec["host"] == f"{name}.apps-crc.testing"
        assert spec["to"] == {"kind": "Service", "name": name}
        assert spec["port"] == {"targetPort": "http"}, "never the metrics port"
        assert spec["tls"] == {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"}


def test_crc_redirect_uri_is_the_docs_route():
    realm = crc("KeycloakRealmImport", "cmapi")["spec"]["realm"]
    docs_client = next(c for c in realm["clients"] if c["clientId"] == "cmapi-docs")
    host = crc("Route", "cmapi-api")["spec"]["host"]
    assert docs_client["redirectUris"] == [f"https://{host}/docs/oauth2-redirect"]
    assert yaml.safe_load(config_file("crc", "instance.yaml"))["instance"]["publicUrl"] == f"https://{host}"


def test_crc_realm_import_names_cmapi_and_holds_no_secret():
    kri = crc("KeycloakRealmImport", "cmapi")
    assert (kri["metadata"]["name"], kri["metadata"]["namespace"]) == ("cmapi", "keycloak")
    spec = kri["spec"]
    assert spec["keycloakCRName"] == "keycloak" and spec["realm"]["realm"] == "cmapi" and "id" not in spec["realm"]
    # Without this the operator asks for 1700Mi (Utils.addResources), which with cmapi's 576 Mi is under the stop line.
    assert spec["resources"] == {"requests": {"cpu": "100m", "memory": "768Mi"}, "limits": {"cpu": "1", "memory": "1Gi"}}
    assert {p["secret"]["name"] for p in spec["placeholders"].values()} == {"cmapi-realm-secrets"}
    confidential = [c for c in spec["realm"]["clients"] if "secret" in c]
    assert confidential and all(c["secret"] == "${%s}" % next(k for k in spec["placeholders"] if k in c["secret"]) for c in confidential)
    assert len(list(yaml.safe_load_all((CRC / "realm/10-realm-import.yaml").read_text()))) == 1


def test_crc_realm_sync_is_one_try_and_requires_the_federation():
    job = crc("Job", "cmapi-realm-sync")["spec"]
    assert job["backoffLimit"] == 0 and job["template"]["spec"]["restartPolicy"] == "Never", "no retries against a Keycloak that is down"
    assert job["activeDeadlineSeconds"] <= 600
    container = job["template"]["spec"]["containers"][0]
    e = env(container)
    assert e["CMAPI_REALM_ADMIN_URL"]["value"].startswith("https://keycloak-service.keycloak.svc")
    ldap = __import__("json").loads(e["CMAPI_REALM_LDAP"]["value"])
    assert ldap["requireSync"] is True and ldap["groupsFilter"] == "(cn=cmapi-*)" and ldap["connectionUrl"].startswith("ldaps://")


def test_crc_reader_reads_only_what_the_code_reads():
    from_code = {"namespaces", "resourcequotas", "limitranges", "pods", "persistentvolumeclaims"}
    rules = crc("ClusterRole", "cmapi-reader")["rules"]
    assert {r for rule in rules for r in rule["resources"]} == from_code
    assert all(set(rule["verbs"]) <= {"get", "list", "watch"} for rule in rules) and all(rule["apiGroups"] == [""] for rule in rules)
    token = crc("Secret", "cmapi-reader-token")
    assert "data" not in token and "stringData" not in token, "the controller fills it; no value in Git"
    assert token["type"] == "kubernetes.io/service-account-token"


def test_crc_trust_holds_certificates_only():
    data = crc("ConfigMap", "cmapi-trust")["data"]["ca-bundle.crt"]
    assert "PRIVATE KEY" not in data and data.count("BEGIN CERTIFICATE") >= 1
    assert "kind stand-in" not in (CRC / "30-trust.yaml").read_text()


def test_crc_monitoring_selects_the_services_and_the_policy_lets_it_in():
    services = {d["metadata"]["name"]: d for d in docs() if d["kind"] == "Service"}
    for c in ("api", "worker"):
        sm = crc("ServiceMonitor", f"cmapi-{c}")["spec"]
        svc = services[f"cmapi-{c}"]
        assert sm["selector"]["matchLabels"].items() <= svc["metadata"]["labels"].items()
        assert sm["endpoints"][0]["port"] in {p["name"] for p in svc["spec"]["ports"]}
        assert "bearerTokenSecret" not in sm["endpoints"][0] and "authorization" not in sm["endpoints"][0]
    policy = next(d for d in docs() if d["kind"] == "NetworkPolicy")
    metrics = next(r for r in policy["spec"]["ingress"] if any(p["port"] == 9090 for p in r["ports"]))
    assert metrics["from"] == [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "openshift-user-workload-monitoring"}}}]


def test_crc_memory_requests_are_the_planned_576_mi():
    """docs/13's arithmetic: the stop line is 2 GiB of request headroom. A request raised here must change the plan with it."""
    def mi(q):
        return int(q[:-2]) * (1024 if q.endswith("Gi") else 1)
    total = 0
    for d in docs():
        if d["kind"] == "Deployment":
            spec = d["spec"]["template"]["spec"]
            main = sum(mi(c["resources"]["requests"]["memory"]) for c in spec["containers"])
            init = max([mi(c["resources"]["requests"]["memory"]) for c in spec.get("initContainers", [])] or [0])
            total += max(main, init)                       # Kubernetes' effective request for a pod
        if d["kind"] == "Cluster":
            total += mi(d["spec"]["resources"]["requests"]["memory"])
    assert total == 576
```

`cmapi/tests/service/test_review_h_tools_migrate.py`, appended (add `import importlib` if the module does not):

```python


@pytest.mark.parametrize("sync,expect_exit", [
    ((200, {"added": 3, "updated": 0, "failed": 0}), False),
    ((200, {"added": 0, "updated": 3, "failed": 0}), False),
    ((200, {"added": 0, "updated": 0, "failed": 0}), True),   # what Keycloak 26.6.4 answers for a directory it cannot reach (measured)
    ((200, {"added": 1, "updated": 0, "failed": 1}), True),
    ((500, {"error": "x"}), True),
])
def test_realm_sync_require_sync_fails_on_a_federation_that_read_nobody(sync, expect_exit, monkeypatch):
    import importlib
    rs = importlib.import_module("cmapi.tools.realm_sync")
    status, body = sync

    class RM:
        def get(self, path, **kw):
            return {"id": "r"} if path == "" else ([{"name": "ldap", "id": "c"}] if kw.get("params", {}).get("type", "").endswith("UserStorageProvider") else [])

        def call(self, method, path, **kw):
            return httpx.Response(status, json=body) if "/sync" in path else httpx.Response(204)

    monkeypatch.setenv("bindDN", "cn=x"); monkeypatch.setenv("password", "p")
    cfg = {"enabled": True, "requireSync": True, "connectionUrl": "ldaps://x", "usersDn": "u", "groupsDn": "g"}
    if expect_exit:
        with pytest.raises(SystemExit):
            rs.ldap(RM(), cfg)
    else:
        rs.ldap(RM(), cfg)
    rs.ldap(RM(), {**cfg, "requireSync": False})           # without the flag the old behaviour stands


def test_realm_sync_require_sync_fails_with_no_bind_credential(monkeypatch):
    import importlib
    rs = importlib.import_module("cmapi.tools.realm_sync")
    for k in ("bindDN", "password", "CMAPI_LDAP_BIND_DN", "CMAPI_LDAP_BIND_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit):
        rs.ldap(None, {"enabled": True, "requireSync": True})
    rs.ldap(None, {"enabled": True})
```


`deploy/manifests/README.md`: the table gains a row, `environments/crc/`; lines 19-21 lose "arrive with"; new text:

> `environments/crc/`: `oc apply --server-side -f environment/` applies its top-level files. Never `-R`: `reader/` and `realm/` are applied by name, in the steps of `docs/13-crc-deployment.md`. `30-trust.yaml` is generated by `deploy/crc-trust.sh`. `deploy/secrets.sh` requires `--issuer` or `--no-issuer-check`.

`docs/11`, "cmapi adds" for Keycloak: "Realm `cmapi`, through one `KeycloakRealmImport` named `cmapi`, applied once and deleted once Done (the operator's guide); Secret `cmapi-realm-secrets`. Creating a realm also adds a client `cmapi-realm` to `master`. Removing: section Rollback of `docs/13`."

### The tests in full


`deploy/tests/crc-guard-test.py`:

```python
#!/usr/bin/env python3
"""deploy/tests/crc-guard-test.py [<crc-guard.py>] [--no-mutants]: deploy/crc-guard.py on a stub oc and a local TLS server, each thing it claims it can stop on, then the same cases on
mutants of the guard: a mutant that survives is a claim its test cannot fail on. No cluster. Standard library and openssl only."""
import http.server, json, os, shutil, ssl, stat, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = next((a for a in sys.argv[1:] if not a.startswith("--")), os.path.join(HERE, "..", "crc-guard.py"))
W = tempfile.mkdtemp(prefix="crc-guard-test.")
STATE = os.path.join(W, "state.json")
ARGV = os.path.join(W, "argv.log")
REALMS = ("master", "corp", "inkcast-prod", "inkcast-staging", "tutorial")
OC = r'''#!/usr/bin/env python3
import json,os,sys
s=json.load(open(os.environ["STUB_STATE"])); a=sys.argv[1:]
open(os.environ["STUB_ARGV"],"a").write(" ".join(a)+"\n")
def out(o): print(json.dumps(o)); sys.exit(0)
if a[:2]==["whoami","--show-server"]: print(s["server"]); sys.exit(0)
if a[:2]==["describe","node"]: print("Allocated resources:\n  Resource  Requests  Limits\n  cpu  1m (0%%) 2m (0%%)\n  memory  %dMi (79%%)  9862Mi (50%%)"%s["requests_mi"]); sys.exit(0)
if a[:3]==["get","node","crc"]: out({"status":{"allocatable":{"memory":"%dMi"%s["allocatable_mi"]}}})
if a[:2]==["get","ns"]: sys.exit(0)
if a[:2]==["get","keycloakrealmimport"] and "cmapi" not in a: out({"items":s["imports"]})
if a[:3]==["get","keycloakrealmimport","cmapi"]:
    if s.get("our_import") is None: sys.exit(0)
    out(s["our_import"])
if a[:2]==["get","keycloak"]: out({"metadata":{"generation":s["cr_generation"]}})
if a[:2]==["get","pod"]: out(s["pods"][a[2]])
if a[:2]==["get","pods"]: out({"items":s["import_pods"]})
if a[:2]==["get","job"]: sys.exit(0)
if a[0]=="delete":
    s["our_import"]=None; json.dump(s,open(os.environ["STUB_STATE"],"w")); sys.exit(0)
print("stub: unhandled",a,file=sys.stderr); sys.exit(3)
'''


def base_state():
    pod = lambda uid: {"metadata": {"uid": uid}, "status": {"containerStatuses": [{"ready": True, "restartCount": 1, "state": {"running": {"startedAt": "2026-11-05T20:17:08Z"}}}]}}
    return {"server": "https://api.crc.testing:6443", "requests_mi": 15525, "allocatable_mi": 19543, "cr_generation": 4,
            "imports": [{"metadata": {"name": n, "uid": "u-" + n, "creationTimestamp": "2026-10-28T00:00:00Z", "generation": 1},
                         "spec": {"realm": {"realm": n}}, "status": {"conditions": [{"type": "Done", "status": "True"}]}} for n in REALMS[1:]],
            "pods": {"keycloak-0": pod("k0"), "postgres-0": pod("p0")}, "our_import": None, "import_pods": [],
            "http": {n: [200, json.dumps({"realm": n, "public_key": "key-" + n})] for n in REALMS} | {"cmapi": [404, '{"error":"Realm does not exist"}']}}


def save(s):
    json.dump(s, open(STATE, "w"))


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        s = json.load(open(STATE))
        code, body = s["http"].get(self.path.rsplit("/", 1)[-1], [404, '{"error":"Realm does not exist"}'])
        self.send_response(code); self.end_headers(); self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


def tls_server():
    sh = lambda *a: subprocess.run(a, check=True, capture_output=True, cwd=W)
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.crt", "-subj", "/CN=test CA", "-days", "2")
    sh("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", "s.key", "-out", "s.csr", "-subj", "/CN=localhost")
    open(os.path.join(W, "san"), "w").write("subjectAltName=DNS:localhost\n")
    sh("openssl", "x509", "-req", "-in", "s.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-out", "s.crt", "-days", "2", "-extfile", "san")
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "o.key", "-out", "other.crt", "-subj", "/CN=other", "-days", "2")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(os.path.join(W, "s.crt"), os.path.join(W, "s.key"))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


PORT = tls_server()
open(os.path.join(W, "oc"), "w").write(OC); os.chmod(os.path.join(W, "oc"), 0o755)
os.mkdir(os.path.join(W, "bin"))
KIND = os.path.join(W, "bin", "kind")
open(KIND, "w").write('#!/bin/sh\n[ -z "$STUB_KIND" ] || echo "$STUB_KIND"\n'); os.chmod(KIND, 0o755)
ENV = {**os.environ, "CMAPI_OC": os.path.join(W, "oc"), "STUB_STATE": STATE, "STUB_ARGV": ARGV, "CMAPI_CRC_CA": os.path.join(W, "ca.crt"),
       "CMAPI_KEYCLOAK_URL": f"https://localhost:{PORT}", "PATH": os.path.join(W, "bin") + ":" + os.environ["PATH"],
       "CMAPI_GUARD_POLL": "0.1", "CMAPI_GUARD_REPORT_AFTER": "0.5", "CMAPI_GUARD_SCHEDULE_DEADLINE": "0.4", "CMAPI_GUARD_RUN_DEADLINE": "0.4"}


def run(guard, *args, **env):
    # A guard that never returns is a wrong answer here, not a crash of the test.
    try:
        return subprocess.run([sys.executable, guard, *args], env={**ENV, **env}, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")


IMPORT_OK = """apiVersion: k8s.keycloak.org/v2beta1
kind: KeycloakRealmImport
metadata:
  name: cmapi
  namespace: keycloak
spec:
  keycloakCRName: keycloak
  realm:
    realm: cmapi
    enabled: true
"""


def cases(guard):
    """Yields (label, passed)."""
    save(base_state()); open(ARGV, "w").close()
    # the three answers of the issuer
    yield "issuer: Keycloak's 404 is absent", run(guard, "issuer").returncode == 10
    s = base_state(); s["http"]["cmapi"] = [200, '{"realm":"cmapi","public_key":"k"}']; save(s)
    yield "issuer: a 200 with the realm is present", run(guard, "issuer").returncode == 0
    for label, answer in (("a router's 503", [503, "<html>down</html>"]), ("a router's 404", [404, "<html>nope</html>"]), ("a JSON 404 that is not Keycloak's", [404, '{"error":"HTTP 404 Not Found"}']), ("a 200 for another realm", [200, '{"realm":"corp"}'])):
        s["http"]["cmapi"] = answer; save(s)
        yield f"issuer: {label} is neither", run(guard, "issuer").returncode == 20
    save(base_state())
    yield "issuer: a certificate from another CA is neither", run(guard, "issuer", CMAPI_CRC_CA=os.path.join(W, "other.crt")).returncode == 20
    yield "no CA named: it stops, TLS is never off", run(guard, "issuer", CMAPI_CRC_CA="").returncode != 0 and run(guard, "issuer", CMAPI_CRC_CA="").returncode != 10
    yield "issuer: nothing listening is neither", run(guard, "issuer", CMAPI_KEYCLOAK_URL="https://localhost:9").returncode == 20
    # snapshot and compare, each field the owner named
    a = os.path.join(W, "a.json"); b = os.path.join(W, "b.json")
    r = run(guard, "snapshot", a)
    yield "snapshot succeeds", r.returncode == 0
    if r.returncode:
        return
    snap = json.load(open(a)); yield "snapshot names every realm", set(snap["realms"]) >= set(REALMS)
    yield "snapshot holds no key material, only its hash", "key-corp" not in open(a).read()
    run(guard, "snapshot", b); yield "two snapshots compare equal", run(guard, "compare", a, b).returncode == 0
    def changed(mut):
        s = base_state(); mut(s); save(s); r = run(guard, "snapshot", b)
        return r.returncode != 0 or run(guard, "compare", a, b).returncode == 1
    mutations = {
        "a realm's public key": lambda s: s["http"]["corp"].__setitem__(1, json.dumps({"realm": "corp", "public_key": "another"})),
        "a realm's status": lambda s: s["http"]["inkcast-prod"].__setitem__(0, 500),
        "a realm gone": lambda s: s["http"]["tutorial"].__setitem__(0, 404),
        "an import's uid": lambda s: s["imports"][0]["metadata"].__setitem__("uid", "x"),
        "an import's creationTimestamp": lambda s: s["imports"][1]["metadata"].__setitem__("creationTimestamp", "x"),
        "an import's Done": lambda s: s["imports"][2]["status"]["conditions"][0].__setitem__("status", "False"),
        "an import gone": lambda s: s["imports"].pop(),
        "keycloak-0's uid": lambda s: s["pods"]["keycloak-0"]["metadata"].__setitem__("uid", "x"),
        "keycloak-0's start": lambda s: s["pods"]["keycloak-0"]["status"]["containerStatuses"][0]["state"]["running"].__setitem__("startedAt", "x"),
        "keycloak-0's restart count": lambda s: s["pods"]["keycloak-0"]["status"]["containerStatuses"][0].__setitem__("restartCount", 2),
        "postgres-0's restart count": lambda s: s["pods"]["postgres-0"]["status"]["containerStatuses"][0].__setitem__("restartCount", 2),
        "the Keycloak CR's generation": lambda s: s.__setitem__("cr_generation", 5),
    }
    for label, m in mutations.items():
        yield f"compare stops on {label}", changed(m)
    # our own import does not count as a difference
    s = base_state(); s["imports"].append({"metadata": {"name": "cmapi", "uid": "o", "creationTimestamp": "n", "generation": 1}, "spec": {"realm": {"realm": "cmapi"}}, "status": {}}); save(s); run(guard, "snapshot", b)
    yield "our own import is not a difference", run(guard, "compare", a, b).returncode == 0
    # headroom
    save(base_state())
    yield "headroom 4018 with 768 passes", run(guard, "headroom", "--needs", "768").returncode == 0
    yield "headroom: exactly the stop line passes", run(guard, "headroom", "--needs", str(4018 - 2048)).returncode == 0
    yield "headroom: one over stops", run(guard, "headroom", "--needs", str(4018 - 2048 + 1)).returncode == 1
    s = base_state(); s["requests_mi"] = 17600; save(s)
    yield "headroom under 2 GiB stops with nothing needed", run(guard, "headroom", "--needs", "0").returncode == 1
    # preflight
    save(base_state())
    yield "preflight passes", run(guard, "preflight", "--needs", "768", STUB_KIND="").returncode == 0
    yield "preflight stops on a kind cluster", run(guard, "preflight", STUB_KIND="cmapi-test").returncode == 1
    s = base_state(); s["server"] = "https://127.0.0.1:6443"; save(s)
    yield "preflight stops on another cluster", run(guard, "preflight", STUB_KIND="").returncode == 1
    s = base_state(); s["pods"]["keycloak-0"]["status"]["containerStatuses"][0]["ready"] = False; save(s)
    yield "preflight stops on an unready Keycloak", run(guard, "preflight", STUB_KIND="").returncode == 1
    # the import file
    f = os.path.join(W, "import.yaml")
    def imp(text):
        open(f, "w").write(text); return run(guard, "check-import", f).returncode
    yield "the import file passes", imp(IMPORT_OK) == 0
    for label, text in (("realm corp", IMPORT_OK.replace("    realm: cmapi", "    realm: corp")), ("name corp", IMPORT_OK.replace("  name: cmapi", "  name: corp")),
                        ("another namespace", IMPORT_OK.replace("namespace: keycloak", "namespace: inkcast")), ("another Keycloak CR", IMPORT_OK.replace("keycloakCRName: keycloak", "keycloakCRName: other")),
                        ("a second document", IMPORT_OK + "---\napiVersion: v1\nkind: Secret\n"), ("an id of another realm", IMPORT_OK.replace("    enabled: true", "    id: corp\n    enabled: true")),
                        ("two realm lines", IMPORT_OK.replace("    enabled: true", "    realm: cmapi\n    enabled: true"))):
        yield f"the import file stops on {label}", imp(text) == 1
    # the watch
    save(base_state()); run(guard, "snapshot", a)
    log = os.path.join(W, "w.log"); stop = os.path.join(W, "stop")
    def watch(mut, seconds=1.2):
        for x in (log, log + ".done", stop):
            if os.path.exists(x): os.unlink(x)
        s = base_state(); mut(s); save(s)
        p = subprocess.Popen([sys.executable, guard, "watch", log, stop, a], env=ENV, stdout=subprocess.PIPE, text=True)
        time.sleep(seconds); open(log + ".done", "w").close(); out, _ = p.communicate(timeout=20)
        return p.returncode, open(log).read(), out
    rc, text, _ = watch(lambda s: None, 0.5)
    yield "the watch stays quiet when all is well", rc == 0 and "BREACH" not in text and not os.path.exists(stop)
    yield "the watch's lines are timestamped", text.startswith("20") and "realms {" in text
    rc, text, out = watch(lambda s: s["http"]["corp"].__setitem__(0, 503))
    yield "a realm's 503 stops the run", rc == 3 and os.path.exists(stop) and "BREACH corp=503" in text
    yield "still down at the bound: report to the owner", "REPORT TO THE OWNER NOW" in text and "REPORT TO THE OWNER NOW" in out
    rc, text, _ = watch(lambda s: s["http"]["corp"].__setitem__(1, json.dumps({"realm": "corp", "public_key": "x"})))
    yield "a changed key stops the run", rc == 3 and "public key changed" in text
    rc, text, _ = watch(lambda s: s["pods"]["keycloak-0"]["status"]["containerStatuses"][0].__setitem__("restartCount", 2))
    yield "a restart stops the run", rc == 3 and "keycloak-0 restarted" in text
    yield "gate: stopped", run(guard, "gate", stop).returncode == 1
    if os.path.exists(stop): os.unlink(stop)
    yield "gate: open", run(guard, "gate", stop).returncode == 0
    # the import's wait, and its withdrawal: only ever our own, by name
    def waits(our, pods, stop_set=False):
        open(ARGV, "w").close(); s = base_state(); s["our_import"] = our; s["import_pods"] = pods; save(s)
        if os.path.exists(stop): os.unlink(stop)
        if stop_set: open(stop, "w").close()
        r = run(guard, "import-wait", stop); deletes = [l.strip() for l in open(ARGV) if l.startswith("delete")]
        return r.returncode, deletes
    only_ours = ["delete keycloakrealmimport cmapi -n keycloak --wait=true --timeout=60s"]
    pending = {"status": {"phase": "Pending"}}; running = {"status": {"phase": "Running", "containerStatuses": [{"state": {"running": {}}}]}}
    done = {"metadata": {"name": "cmapi"}, "status": {"conditions": [{"type": "Done", "status": "True"}, {"type": "HasErrors", "status": "False"}]}}
    started = {"metadata": {"name": "cmapi"}, "status": {"conditions": [{"type": "Started", "status": "True"}, {"type": "Done", "status": "False"}, {"type": "HasErrors", "status": "False"}]}}
    errors = {"metadata": {"name": "cmapi"}, "status": {"conditions": [{"type": "HasErrors", "status": "True"}, {"type": "Done", "status": "False"}]}}
    s = base_state(); s["http"]["cmapi"] = [200, '{"realm":"cmapi","public_key":"k"}']; base_http = s["http"]
    rc, d = waits(started, [pending]); yield "not started by the deadline: withdrawn, by name only", rc == 1 and d == only_ours
    rc, d = waits(started, [], stop_set=True); yield "the run stopped, not started: withdrawn", rc == 1 and d == only_ours
    rc, d = waits(started, [running]); yield "running too long: reported, never interrupted", rc == 1 and d == []
    rc, d = waits(errors, [{"status": {"phase": "Failed", "containerStatuses": [{"state": {"terminated": {}}}]}}]); yield "failed: withdrawn, so the Job does not try again", rc == 1 and d == only_ours
    open(ARGV, "w").close(); s = base_state(); s["our_import"] = done; s["import_pods"] = [running]; s["http"]["cmapi"] = base_http["cmapi"]; save(s)
    r = run(guard, "import-wait", stop); yield "Done and the realm answers: passes, deletes nothing", r.returncode == 0 and "delete" not in open(ARGV).read()
    s["http"]["cmapi"] = [404, '{"error":"Realm does not exist"}']; save(s)
    yield "Done but no realm: stops", run(guard, "import-wait", stop).returncode == 1


def score(guard):
    return [(label, bool(ok)) for label, ok in cases(guard)]


MUTANTS = {
    "any 404 is absent": ('if status == 404 and doc == {"error": "Realm does not exist"}:', "if status == 404:"),
    "the snapshot leaves out keycloak-0's restarts": ('"restarts": cs.get("restartCount"), ', ""),
    "the snapshot drops the keys": ('"public_key_sha256": key}', '"public_key_sha256": None}'),
    "compare never differs": ("if d:\n                raise Stop", "if False:\n                raise Stop"),
    "the stop line moves": ("STOP_LINE_MI = 2048", "STOP_LINE_MI = 1024"),
    "no kind check": ("if clusters.returncode != 0 or names:", "if False:"),
    "the realm name is not checked": ('r"^    realm: cmapi$")', 'r"^  realm:$")'),
    "a second document is allowed": ('if re.search(r"^---", text, re.M) or re.search(r"^\\.\\.\\.", text, re.M):', "if False:"),
    "the watch ignores a restart": ('problems.append(f"keycloak-0 restarted: {kc}")', "pass"),
    "the watch never reports": ("if down and waited >= REPORT_AFTER_SECONDS and not reported:", "if False:"),
    "the watch does not stop the run": ("open(stop_file, \"a\").close()", "pass"),
    "a pending import is left to fire": ("if not started and time.monotonic() - t0 > SCHEDULE_DEADLINE:", "if False:"),
    "withdrawal deletes every import": ('oc("delete", "keycloakrealmimport", OURS, "-n", NS, "--wait=true", "--timeout=60s")', 'oc("delete", "keycloakrealmimport", "--all", "-n", NS)'),
    "a running import is killed": ('print(f"{now()} the import has run {int(RUN_DEADLINE)} s without finishing. It is not interrupted; report to the owner", flush=True)', 'withdraw("too long")'),
    "verification off": ("    return c\n", "    c.check_hostname = False; c.verify_mode = ssl.CERT_NONE\n    return c\n"),
}

try:
    rows = score(GUARD)
    bad = [l for l, ok in rows if not ok]
    for l, ok in rows:
        print(("  ok   " if ok else "  FAIL ") + l)
    wrong = 0
    if "--no-mutants" not in sys.argv and not bad:
        text = open(GUARD).read()
        for name, (old, new) in MUTANTS.items():
            assert text.count(old) == 1, (name, old, text.count(old))
            m = os.path.join(W, "mutant.py"); open(m, "w").write(text.replace(old, new))
            f = [l for l, ok in score(m) if not ok]
            print(f"  {'killed  ' if f else 'SURVIVED'} {name}" + (f" ({f[0]})" if f else ""))
            wrong += 0 if f else 1
    print(f"guard cases failed: {len(bad)}, mutants survived: {wrong}")
    sys.exit(1 if bad or wrong else 0)
finally:
    shutil.rmtree(W, ignore_errors=True)
```


`deploy/tests/crc-scripts-test.sh`:

```bash
#!/usr/bin/env bash
# shellcheck disable=SC2015  # ok and bad here never fail, so A && ok || bad is if-then-else
# deploy/tests/crc-scripts-test.sh [<deploy dir>]: deploy/crc-{image,trust,reader-import,backup,rollback,proof}.sh on stubs of oc, podman, skopeo, curl and tmutil, for each thing they claim
# they can stop on, and for what they must never do: a credential on an argument list, a delete that does not name one object, a dump's path or content in the output. No cluster.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); SRC=$(cd "${1:-$HERE/..}" && pwd); W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }; ok() { echo "  ok   $*"; }
want() { local label=$1 rc=$2 got=$3; if [ "$got" = "$rc" ]; then ok "$label"; else bad "$label: rc $got, not $rc"; fi; }
TOKEN=sha256~stub-token-value-never-to-be-seen; SECRETVAL=stub-client-secret-never-to-be-seen; DUMP_MARK=stub-dump-content-never-to-be-seen
mkdir -p "$W/bin" "$W/repo/deploy"; cp "$SRC"/crc-*.sh "$W/repo/deploy/"; cp -R "$SRC/manifests" "$W/repo/deploy/"; export ARGV_LOG=$W/argv.log TOKEN SECRETVAL DUMP_MARK
openssl req -x509 -newkey rsa:2048 -nodes -keyout /dev/null -out "$W/ca.pem" -subj "/CN=stub CA" -days 2 2>/dev/null
openssl req -newkey rsa:2048 -nodes -keyout /dev/null -out "$W/leaf.csr" -subj "/CN=leaf" 2>/dev/null; export STUB_CA=$W/ca.pem
cat >"$W/bin/oc" <<'OC'
#!/usr/bin/env bash
printf 'oc %s\n' "$*" >>"$ARGV_LOG"
s="$*"
case "$s" in
  "get secret keycloak-tls -n keycloak -o jsonpath={.data.ca\.crt}") base64 <"$STUB_CA"; exit 0;;
  "get cm default-ingress-cert"*) cat "$STUB_CA"; exit 0;;
  "get istag cmapi:"*"--ignore-not-found"*) printf '%s' "${STUB_ISTAG:-}"; exit 0;;
  "get istag cmapi:"*) printf '%s' "${STUB_REGISTRY_DIGEST:-sha256:aaaa}"; exit 0;;
  "get route default-route"*) printf 'registry.stub'; exit 0;;
  "get route thanos-querier"*) printf 'thanos.stub'; exit 0;;
  "whoami -t") printf '%s\n' "$TOKEN"; exit 0;;
  "get secret cmapi-reader-token"*) [ -n "${STUB_NO_TOKEN:-}" ] && { echo '{"data":{}}'; exit 0; }; printf '{"data":{"token":"%s","ca.crt":"Y2E="}}\n' "$(printf '%s' "$TOKEN" | base64)"; exit 0;;
  "apply --server-side -f -") cat >"$ARGV_LOG.applied"; exit 0;;
  "get pod postgres-0 -n keycloak -o json") cat <<'J'
{"spec":{"containers":[{"name":"postgres","image":"postgres:16","resources":{"limits":{"memory":"512Mi"}},"env":[{"name":"POSTGRES_USER","valueFrom":{"secretKeyRef":{"name":"kc-db","key":"user"}}},{"name":"POSTGRES_PASSWORD","value":"literal-value-never-to-be-seen"}]}]}}
J
    exit 0;;
  "get pod postgres-0 -n keycloak -o jsonpath"*) printf '512Mi'; exit 0;;
  "adm top pod postgres-0"*) echo "postgres-0 5m ${STUB_DB_USED:-100Mi}"; exit 0;;
  "exec postgres-0"*"select current_setting"*) echo "${STUB_DB_SLOTS:-40}"; exit 0;;
  "exec postgres-0"*"select count(*) from realm"*) echo "${STUB_LIVE_REALMS:-6}"; exit 0;;
  "exec postgres-0"*"pg_dump"*) [ -n "${STUB_DUMP_FAIL:-}" ] && { printf 'PGDMP-part'; echo "pg_dump: error: connection lost" >&2; exit 1; }; [ -n "${STUB_DUMP_EMPTY:-}" ] && exit 0; printf 'PGDMP%s' "$DUMP_MARK"; exit 0;;
  "exec -i postgres-0"*"--list"*) cat >/dev/null; [ -n "${STUB_LIST_FAIL:-}" ] && exit 1; echo 90; exit 0;;
  "exec -i postgres-0"*"-t realm"*) cat >/dev/null; echo "${STUB_DUMP_REALMS:-6}"; exit 0;;
  "exec -i postgres-0"*"pg_restore -f /dev/null"*) cat >/dev/null; [ -n "${STUB_READ_FAIL:-}" ] && { echo "pg_restore: error: could not read from input file: end of file" >&2; exit 1; }; exit 0;;
  "get secret cmapi-keycloak -n cmapi -o jsonpath"*) printf '%s' "$SECRETVAL" | base64; exit 0;;
  "get pvc cmapi-db-1"*) printf 'pv-1'; exit 0;;
  "get pv pv-1"*) printf '%s' "${STUB_PV_WHO:-cmapi/cmapi-db-1/Released}"; exit 0;;
  delete*|label*|"create namespace"*|"run np-probe"*|"wait pod/np-probe"*) exit 0;;
  "get pods -n cmapi -o json") python3 -c 'import json,os
img=os.environ.get("STUB_IMAGE_ID","sha256:aaaa"); scc=os.environ.get("STUB_SCC","restricted-v2"); r=int(os.environ.get("STUB_RESTARTS","0")); start=os.environ.get("STUB_START","2026-11-06T10:00:00Z")
pod=lambda n,c:{"metadata":{"name":n,"labels":{"app.kubernetes.io/component":c},"annotations":{"openshift.io/scc":scc}},"spec":{"containers":[{}]},"status":{"phase":"Running","startTime":start,"containerStatuses":[{"restartCount":r,"imageID":"x@"+img}]}}
print(json.dumps({"items":[pod("a","api"),pod("w","worker"),pod("m","mockup")]}))'; exit 0;;
  "get networkpolicy cmapi-metrics"*) printf '2026-11-06T09:00:00Z'; exit 0;;
  "exec np-probe"*"cmapi-mockup"*) exit "${STUB_CONTROL_RC:-0}";;
  "exec np-probe"*"cmapi-api"*) exit "${STUB_BLOCK_RC:-1}";;
  "get secret cmapi-test-users"*) printf '%s' "$SECRETVAL" | base64; exit 0;;
  "auth can-i"*"--all-namespaces"*) echo "${STUB_READER_WIDE:-no}"; exit 0;;
  "auth can-i"*"cmapi-reader"*) echo yes; exit 0;;
  "auth can-i"*) echo "${STUB_WRITER:-no}"; exit 0;;
  "exec cmapi-db-1"*) echo "${STUB_SSL:-3|0}"; exit 0;;
esac
echo "stub oc: unhandled $s" >&2; exit 3
OC
cat >"$W/bin/podman" <<'P'
#!/usr/bin/env bash
printf 'podman %s\n' "$*" >>"$ARGV_LOG"
case "$1" in image) echo "${STUB_LABEL:-$(git -C "$REPO" rev-parse --short=10 HEAD)}";; esac; exit 0
P
cat >"$W/bin/skopeo" <<'P'
#!/usr/bin/env bash
printf 'skopeo %s\n' "$*" >>"$ARGV_LOG"
while [ $# -gt 0 ]; do case "$1" in --digestfile) printf 'sha256:aaaa' >"$2"; shift;; --dest-authfile) cp "$2" "$ARGV_LOG.auth"; stat -f '%Lp' "$2" 2>/dev/null >"$ARGV_LOG.mode" || stat -c '%a' "$2" >"$ARGV_LOG.mode"; shift;; esac; shift; done; exit "${STUB_SKOPEO_RC:-0}"
P
cat >"$W/bin/curl" <<'P'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >>"$ARGV_LOG"
if [ -n "${STUB_PROOF:-}" ]; then
  # The proof's curl: by URL. Anything on stdin is what a token must travel on, and it is swallowed here.
  url=; code=; for a in "$@"; do case "$a" in http*) url=$a;; esac; done; case "$*" in *-w*) wants=1;; *) wants=;; esac
  [ ! -p /dev/stdin ] || cat >/dev/null
  case "$url" in
    */readyz) code=${STUB_READYZ:-200}; case "$url" in http://*) code=302;; esac;;
    */api/v1/version) printf '{"commit":"%s"}' "${STUB_COMMIT:-$(git -C "$REPO" rev-parse --short=10 HEAD)}"; exit 0;;
    */metrics) code=${STUB_METRICS:-404};;
    */api/v1/me) case "$*" in *--config*) printf '{"username":"bot-user","roles":["cmapi-onboarding"]}'; exit 0;; *) code=401;; esac;;
    */portal.html) code=200;;
    */token) printf '{"access_token":"%s"}' "$TOKEN"; exit 0;;
    */namespaces*) printf '{"code":"%s"}\n%s' "${STUB_PLAN_CODE:-cluster-not-writable}" "${STUB_PLAN:-422}"; exit 0;;
    */api/v1/query*) case "$*" in *cluster_status*) printf '{"data":{"result":[{"value":[0,"1"]}]}}';; *) printf '{"data":{"result":[%s]}}' "${STUB_UP:-{\"value\":[0,\"1\"]\},{\"value\":[0,\"1\"]\}}";; esac; exit 0;;
  esac
  [ -z "$wants" ] || printf '%s' "$code"; exit 0
fi
cat >/dev/null 2>&1 </dev/null
exit_code=${STUB_CURL_RC:-0}; [ "$exit_code" = 0 ] || exit "$exit_code"
out=; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done; [ -z "$out" ] || : >"$out"; printf '%s' "${STUB_CURL_CODE:-200}"
P
printf '#!/bin/sh\nexit 0\n' >"$W/bin/tmutil"
chmod +x "$W/bin/"*; export PATH="$W/bin:$PATH"
cd "$W/repo" || exit 1; git init -q .; git -c user.email=t@t -c user.name=t commit -q --allow-empty -m t; export REPO=$W/repo; mkdir -p cmapi; printf 'version = "0.2.0"\n' >cmapi/pyproject.toml
D=$W/repo/deploy; TRUST=$D/manifests/environments/crc/30-trust.yaml
no_secret() { if grep -qF -e "$TOKEN" -e "$SECRETVAL" -e "$(printf '%s' "$TOKEN" | base64)" "$ARGV_LOG" "$1"; then bad "$2: a credential reached an argument or the output"; else ok "$2: no credential on an argument or in the output"; fi; }
run() { : >"$ARGV_LOG"; "$@" >"$W/out" 2>&1; echo $?; }

# crc-trust.sh
want "trust --write" 0 "$(run "$D/crc-trust.sh" --write)"; grep -q 'BEGIN CERTIFICATE' "$TRUST" || bad "no certificate in the file"
if grep -qE 'tls\.key|-o (yaml|json)( |$)' "$ARGV_LOG"; then bad "trust --write asked for more than ca.crt"; else ok "trust --write asks for ca.crt alone"; fi
grep -q 'name: cmapi-trust' "$TRUST" && [ "$(grep -c 'BEGIN CERTIFICATE' "$TRUST")" = 1 ] && ok "the file declares cmapi-trust" || bad "the trust file"
printf -- '-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n' >"$W/key.pem"
cp "$TRUST" "$W/keep"; want "trust --extra-ca refuses a private key" 1 "$(run "$D/crc-trust.sh" --write --extra-ca "$W/key.pem")"; cmp -s "$TRUST" "$W/keep" && ok "and the file stays" || bad "a refused --write changed the file"
want "trust --check passes" 0 "$(run "$D/crc-trust.sh" --check)"
if grep -q 'keycloak-tls' "$ARGV_LOG"; then bad "--check read the Secret"; else ok "--check reads no Secret"; fi
grep -q -- '--cacert' "$ARGV_LOG" && ok "--check verifies with the file" || bad "--check did not use --cacert"
want "trust --check: a failed handshake stops" 1 "$(STUB_CURL_RC=60 run "$D/crc-trust.sh" --check)"
want "trust --check: not 200 stops" 1 "$(STUB_CURL_CODE=503 run "$D/crc-trust.sh" --check)"
want "trust --mac-ca" 0 "$(run "$D/crc-trust.sh" --mac-ca "$W/mac.pem")"; [ "$(grep -c 'BEGIN CERTIFICATE' "$W/mac.pem")" = 2 ] && ok "both CAs in the Mac's bundle" || bad "the Mac's bundle"
if grep -rqE -- '(^|[^-])(-k |--insecure|--tls-verify=false)' "$D"/crc-*.sh; then bad "TLS verification off in a script"; else ok "no script turns TLS verification off"; fi

# crc-image.sh
want "image: pushes and prints" 0 "$(run "$D/crc-image.sh")"; tail -1 "$W/out" | grep -qE '^image-registry\.openshift-image-registry\.svc:5000/cmapi/cmapi@sha256:' && ok "the last line is the reference render.sh takes" || bad "the image line: $(tail -1 "$W/out")"
no_secret "$W/out" "image"; [ "$(cat "$ARGV_LOG.mode")" = 600 ] && ok "the auth file is 0600" || bad "the auth file's mode"
grep -qF "$(printf 'unused:%s' "$TOKEN" | base64)" "$ARGV_LOG.auth" && ok "the auth file holds the session's token" || bad "the auth file's content"
grep -q -- '--dest-cert-dir' "$ARGV_LOG" && ok "skopeo verifies against the ingress CA" || bad "no --dest-cert-dir"
want "image: a pushed digest the image stream does not know stops" 1 "$(STUB_REGISTRY_DIGEST=sha256:bbbb run "$D/crc-image.sh")"
want "image: a wrong label stops" 1 "$(STUB_LABEL=other run "$D/crc-image.sh")"
want "image: a failed push stops" 1 "$(STUB_SKOPEO_RC=1 run "$D/crc-image.sh")"
want "image: an existing tag of this commit is reused" 0 "$(STUB_ISTAG="sha256:cccc $(git rev-parse --short=10 HEAD)" run "$D/crc-image.sh")"; if grep -q '^skopeo' "$ARGV_LOG"; then bad "it pushed again"; else ok "and not pushed again"; fi
want "image: an existing tag of another commit stops" 1 "$(STUB_ISTAG="sha256:cccc other" run "$D/crc-image.sh")"
printf x >>cmapi/pyproject.toml; git add -A >/dev/null; want "image: a dirty tree stops" 1 "$(run "$D/crc-image.sh")"; git -c user.email=t@t -c user.name=t commit -q -m t2

# crc-reader-import.sh
want "reader import" 0 "$(run "$D/crc-reader-import.sh")"; no_secret "$W/out" "reader import"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); m=d["metadata"]; sys.exit(0 if m["namespace"]=="cmapi-imports" and m["labels"]["cmapi.net/cluster-id"]=="CRC" and m["labels"]["cmapi.net/secret-type"]=="cluster" and set(d["data"])=={"apiUrl","token","caData"} else 1)' "$ARGV_LOG.applied" && ok "the import Secret is what the registry reads" || bad "the import Secret"
want "reader import: an unfilled token stops" 1 "$(CMAPI_READER_POLL=0 STUB_NO_TOKEN=1 run "$D/crc-reader-import.sh")"

# crc-backup.sh
B=$W/backup; export CMAPI_BACKUP_DIR=$B
want "backup --inspect" 0 "$(run "$D/crc-backup.sh" --inspect)"; if grep -q 'literal-value' "$W/out"; then bad "--inspect printed a value"; else ok "--inspect prints names, never a value"; fi
grep -q 'POSTGRES_USER' "$W/out" && ok "--inspect names the variables" || bad "--inspect names nothing"
want "backup" 0 "$(run "$D/crc-backup.sh")"
f=$(find "$B" -type f -name 'keycloak-*.dump'); [ -n "$f" ] && ok "a dump in the directory" || bad "no dump"
m() { stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1"; }; [ "$(m "$B")" = 700 ] && [ "$(m "$f")" = 600 ] && ok "directory 0700, file 0600" || bad "modes $(m "$B") $(m "$f")"
if grep -qF -e "$DUMP_MARK" -e "$f" "$W/out" "$ARGV_LOG"; then bad "the dump's content or path reached the output"; else ok "no content and no path in the output"; fi
if grep -qE 'pg_dump.*(> *[/a-z]|-f )' "$ARGV_LOG"; then bad "the dump is written inside the pod"; else ok "the dump goes to stdout"; fi
if grep -qE 'exec (-[a-z]+ )*-t' "$ARGV_LOG"; then bad "a TTY would corrupt the stream"; else ok "no TTY on the stream"; fi
rm -rf "$B"
stop() { local label=$1; shift; local got; got=$(env "$@" "$D/crc-backup.sh" >"$W/out" 2>&1; echo $?); [ "$got" != 0 ] && ok "backup stops: $label" || bad "backup did not stop: $label"; if find "$B" -type f 2>/dev/null | grep -q .; then bad "$label: left a file"; fi; rm -rf "$B"; }
stop "a dump that fails partway" STUB_DUMP_FAIL=1
stop "an empty dump" STUB_DUMP_EMPTY=1
stop "a list that fails" STUB_LIST_FAIL=1
stop "an archive that does not read to its end" STUB_READ_FAIL=1
stop "realm counts that differ" STUB_DUMP_REALMS=5
stop "too little room under the limit" STUB_DB_USED=450Mi
stop "too few free connections" STUB_DB_SLOTS=2
ln -s "$W" "$B"; got=$("$D/crc-backup.sh" >"$W/out" 2>&1; echo $?); [ "$got" != 0 ] && ok "backup stops: a symbolic link for the directory" || bad "the link was followed"; rm -f "$B"
"$D/crc-backup.sh" >/dev/null 2>&1; want "backup --delete" 0 "$(run "$D/crc-backup.sh" --delete)"; [ ! -e "$B" ] && ok "the backup is gone" || bad "the backup is still there"

# crc-proof.sh
export STUB_PROOF=1 CMAPI_PROOF_SCRAPE_TRIES=1 CMAPI_CRC_CA=$W/mac.pem; P=$W/rendered; mkdir -p "$P"; printf 'image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:aaaa\n' >"$P/IMAGE"
want "proof passes when all is right" 0 "$(run "$D/crc-proof.sh" "$P")"; [ "$(tail -1 "$W/out")" = "proof: all passed" ] || bad "the proof's last line: $(tail -1 "$W/out")"
no_secret "$W/out" "proof"
pstop() { local label=$1; shift; local got; got=$(: >"$ARGV_LOG"; env "$@" "$D/crc-proof.sh" "$P" >"$W/out" 2>&1; echo $?); [ "$got" != 0 ] && ok "proof fails: $label" || bad "proof did not fail: $label"; }
pstop "a pod under another SCC" STUB_SCC=anyuid
pstop "a restart" STUB_RESTARTS=1
pstop "another image running" STUB_IMAGE_ID=sha256:bbbb
pstop "a pod started before the policy" STUB_START=2026-11-06T08:00:00Z
pstop "/readyz not 200" STUB_READYZ=503
pstop "another commit" STUB_COMMIT=other
pstop "/metrics on the Route" STUB_METRICS=200
pstop "the probe reaching the api: the policy not enforced" STUB_BLOCK_RC=0
pstop "the control failing: the block would prove nothing" STUB_CONTROL_RC=1
pstop "a worker that may write" STUB_WRITER=yes
pstop "a reader reading Secrets" STUB_READER_WIDE=yes
pstop "a plan that passes" STUB_PLAN=200
pstop "a 422 of another kind" STUB_PLAN_CODE=validation-failed
pstop "a connection without TLS" "STUB_SSL=3|1"
pstop "no connection at all" "STUB_SSL=0|0"
pstop "a target Prometheus does not scrape" 'STUB_UP={"value":[0,"1"]}'
unset STUB_PROOF

# crc-rollback.sh: every delete names one object, from a fixed list.
want "rollback needs --yes" 2 "$(run "$D/crc-rollback.sh")"; [ ! -s "$ARGV_LOG" ] && ok "and does nothing without it" || bad "it ran without --yes"
want "rollback" 0 "$(run "$D/crc-rollback.sh" --yes)"
check_deletes() { python3 - "$ARGV_LOG" <<'PY'
import re,sys
ok={"keycloakrealmimport cmapi -n keycloak","job cmapi-realm-sync -n cmapi","cluster.postgresql.cnpg.io cmapi-db -n cmapi","pvc cmapi-db-1 -n cmapi","pv pv-1","namespace cmapi-np-probe","namespace cmapi-imports","namespace cmapi-system","clusterrolebinding cmapi-reader","clusterrole cmapi-reader","secret cmapi-realm-secrets -n keycloak"}
ok|={f"{k} {n} -n cmapi" for k,n in [("deployment","cmapi-api"),("deployment","cmapi-worker"),("deployment","cmapi-mockup"),("service","cmapi-api"),("service","cmapi-worker"),("service","cmapi-mockup"),("networkpolicy","cmapi-metrics"),("route.route.openshift.io","cmapi-api"),("route.route.openshift.io","cmapi-mockup"),("servicemonitor.monitoring.coreos.com","cmapi-api"),("servicemonitor.monitoring.coreos.com","cmapi-worker"),("prometheusrule.monitoring.coreos.com","cmapi"),("configmap","cmapi-env"),("configmap","cmapi-config"),("configmap","cmapi-trust"),("configmap","cmapi-mockup"),("secret","cmapi-keys"),("secret","cmapi-keycloak"),("secret","cmapi-test-users"),("serviceaccount","cmapi-api"),("serviceaccount","cmapi-worker"),("serviceaccount","cmapi-jobs"),("imagestream.image.openshift.io","cmapi")]}
bad=[]
for line in open(sys.argv[1]):
    if not line.startswith("oc delete "): continue
    words=[w for w in line[len("oc delete "):].split() if not w.startswith(("--ignore-not-found","--wait","--timeout"))]
    if " ".join(words) not in ok: bad.append(line.strip())
print("\n".join(bad)); sys.exit(1 if bad else 0)
PY
}
if out=$(check_deletes); then ok "rollback deletes only named objects from its list"; else bad "rollback deleted: $out"; fi
if grep -qE 'delete .*(namespace cmapi( |$)|cmapi-ldap-bind|realm-secrets)' "$ARGV_LOG"; then bad "rollback touched namespace cmapi, the bind Secret or the realm's Secret"; else ok "namespace cmapi, cmapi-ldap-bind and the realm's Secret stay"; fi
if grep -qF 'admin/realms' "$ARGV_LOG"; then bad "rollback touched the realm without being asked"; else ok "the realm stays unless asked"; fi
want "rollback: --delete-realm alone is refused" 2 "$(run "$D/crc-rollback.sh" --yes --delete-realm)"
if grep -qE 'delete ' "$ARGV_LOG"; then bad "it deleted something first"; fi
: >"$ARGV_LOG"; STUB_PV_WHO=inkcast/other/Bound "$D/crc-rollback.sh" --yes >"$W/out" 2>&1; if grep -q 'oc delete pv ' "$ARGV_LOG"; then bad "a PV another claim holds was deleted"; else ok "a PV that is not ours stays"; fi
# The static rule, on every script: no broad delete, no prune, ever. It must be able to fail: a copy with --all has to be caught.
broad() { cat "$@" | grep -vE '^[[:space:]]*#' | grep -nE '(oc_|oc|kc) delete .*( --all| -l | --selector| -f | -R)|(^|[[:space:]])del .*( --all| -l | --selector| -f | -R)|--prune'; }
if broad "$D"/crc-*.sh; then bad "a broad delete in a script"; else ok "no broad delete in any script"; fi
printf 'oc_ delete keycloakrealmimport --all -n keycloak\n' >"$W/mut.sh"; if broad "$W/mut.sh" >/dev/null; then ok "and that rule can fail"; else bad "the broad-delete rule caught nothing"; fi

echo "crc script cases failed: $fails"; [ "$fails" = 0 ]
```


`deploy/tests/realm-test.py`:

```python
#!/usr/bin/env python3
"""deploy/tests/realm-test.py <realm import YAML>: realm cmapi from the file that ships, on a real Keycloak, the way the RHBK operator's Job runs it (KeycloakRealmImportJobDependentResource.java:96-158):
a second process on the live server's database, --cache=local, --override=false, the placeholders in its environment. Beside it two other realms, whose public keys must not change. Then realm_sync.py, an LDAP
stand-in, a federated login and its token claims, a rerun, the issuer's own answers, and the realm deleted by its own cmapi-realm-admin. Containers cmapi-rt-*, on 127.0.0.1; removed at the end. CONTAINER=podman on
a Mac, docker in CI. Keycloak's community image: RHBK, its operator and the real directory are what the CRC run proves. Exit 1 on the first wrong answer. Needs pyyaml and httpx. Test values only."""
import base64, hashlib, importlib.util, json, os, secrets, subprocess, sys, tempfile, time
import httpx, yaml

C = os.environ.get("CONTAINER", "docker"); KC = os.environ.get("KC_IMAGE", "quay.io/keycloak/keycloak:26.6"); PORT = os.environ.get("RT_PORT", "18190")
B = f"http://127.0.0.1:{PORT}"; ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
kri = yaml.safe_load(open(sys.argv[1])); realm = kri["spec"]["realm"]
assert kri["kind"] == "KeycloakRealmImport" and realm["realm"] == "cmapi" and kri["metadata"]["namespace"] == "keycloak"
limit = kri["spec"]["resources"]["limits"]["memory"].replace("Gi", "g").replace("Mi", "m"); cpus = str(kri["spec"]["resources"]["limits"]["cpu"])
vals = {k: secrets.token_urlsafe(24) for k in kri["spec"]["placeholders"]}
fails = []
def check(ok, label):
    print(("  ok   " if ok else "  FAIL ") + label, flush=True)
    if not ok: fails.append(label)
def sh(*a, **k): return subprocess.run(a, capture_output=True, text=True, **k)
def pk(n):
    r = httpx.get(f"{B}/realms/{n}", timeout=5); return r.status_code, hashlib.sha256(r.json().get("public_key", "").encode()).hexdigest() if r.status_code == 200 else r.text
def admin(): return httpx.post(f"{B}/realms/master/protocol/openid-connect/token", data={"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "rt-admin"}).json()["access_token"]
DB = ["-e", "KC_DB=postgres", "-e", "KC_DB_URL=jdbc:postgresql://127.0.0.1:5432/kc", "-e", "KC_DB_USERNAME=kc", "-e", "KC_DB_PASSWORD=kc"]
POD = ["--network", "container:cmapi-rt-pg"]
W = tempfile.mkdtemp(prefix="realm-test.")
def cleanup(): sh(C, "rm", "-f", "cmapi-rt-import", "cmapi-rt-kc", "cmapi-rt-ldap", "cmapi-rt-pg")
try:
    cleanup()
    # One network namespace, as a pod is: the database owns it, and only Keycloak's port is published, to 127.0.0.1.
    sh(C, "run", "-d", "--name", "cmapi-rt-pg", "-p", f"127.0.0.1:{PORT}:8080", "-e", "POSTGRES_USER=kc", "-e", "POSTGRES_PASSWORD=kc", "-e", "POSTGRES_DB=kc", "docker.io/library/postgres:16-alpine", check=True)
    time.sleep(5)
    sh(C, "run", "-d", "--name", "cmapi-rt-kc", *POD, "-e", "KC_BOOTSTRAP_ADMIN_USERNAME=admin", "-e", "KC_BOOTSTRAP_ADMIN_PASSWORD=rt-admin", *DB, KC, "start-dev", "--hostname=https://keycloak.apps-crc.testing", "--http-enabled=true", check=True)
    sh(C, "run", "-d", "--name", "cmapi-rt-ldap", *POD, "-e", "LDAP_ORGANISATION=e", "-e", "LDAP_DOMAIN=ephico2real.com", "-e", "LDAP_ADMIN_PASSWORD=rt-ldap", "-e", "LDAP_TLS=false", "docker.io/osixia/openldap:1.5.0", check=True)
    for _ in range(90):
        try:
            if httpx.get(f"{B}/realms/master", timeout=3).status_code == 200: break
        except httpx.HTTPError: pass
        time.sleep(2)
    time.sleep(3)
    ldif = """dn: ou=People,dc=ephico2real,dc=com
objectClass: organizationalUnit
ou: People

dn: ou=Groups,dc=ephico2real,dc=com
objectClass: organizationalUnit
ou: Groups

dn: cn=john.doe,ou=People,dc=ephico2real,dc=com
objectClass: inetOrgPerson
objectClass: posixAccount
cn: john.doe
sn: Doe
uid: john.doe
mail: john.doe@ephico2real.com
uidNumber: 10001
gidNumber: 10000
homeDirectory: /home/john.doe
userPassword: rt-john

dn: cn=app-other,ou=Groups,dc=ephico2real,dc=com
objectClass: groupOfNames
cn: app-other
member: cn=john.doe,ou=People,dc=ephico2real,dc=com

dn: cn=cmapi-requesters,ou=Groups,dc=ephico2real,dc=com
objectClass: groupOfNames
cn: cmapi-requesters
member: cn=john.doe,ou=People,dc=ephico2real,dc=com
"""
    r = sh(C, "exec", "-i", "cmapi-rt-ldap", "ldapadd", "-x", "-H", "ldap://127.0.0.1:389", "-D", "cn=admin,dc=ephico2real,dc=com", "-w", "rt-ldap", input=ldif); check(r.returncode == 0, "the LDAP stand-in is seeded")
    for n in ("corp-rt", "inkcast-rt"):
        httpx.post(f"{B}/admin/realms", headers={"Authorization": f"Bearer {admin()}"}, json={"realm": n, "enabled": True}).raise_for_status()
    others = lambda: {n: pk(n) for n in ("master", "corp-rt", "inkcast-rt")}
    before = others(); started = sh(C, "inspect", "cmapi-rt-kc", "--format", "{{.State.StartedAt}} {{.RestartCount}}").stdout
    # issuer answers, exactly what deploy/secrets.sh and crc-guard.py read as absent
    a = httpx.get(f"{B}/realms/cmapi"); check(a.status_code == 404 and a.json() == {"error": "Realm does not exist"}, f"before the import the issuer is Keycloak's own 404: {a.text}")
    path = os.path.join(W, "cmapi-realm.json"); json.dump(realm, open(path, "w")); os.chmod(W, 0o755); os.chmod(path, 0o644)
    def imp():
        return subprocess.run([C, "run", "--rm", "--name", "cmapi-rt-import", *POD, f"--memory={limit}", f"--cpus={cpus}", "-v", f"{path}:/mnt/realm-import/cmapi-realm.json:ro", *DB, "-e", "KC_CACHE=local", "-e", "KC_HOSTNAME=https://keycloak.apps-crc.testing", "-e", "KC_HTTP_MANAGEMENT_PORT=9900",
                               *sum((["-e", k] for k in vals), []), KC, "--verbose", "import", f"--file=/mnt/realm-import/cmapi-realm.json", "--override=false"], env={**os.environ, **vals}, capture_output=True, text=True, timeout=300)
    t0 = time.time(); r = imp(); log = r.stdout + r.stderr
    check(r.returncode == 0 and "Realm 'cmapi' imported" in log, f"the import succeeds under its own limits, {limit} and {cpus} CPU, in {time.time() - t0:.0f} s")
    check(not any(v in log for v in vals.values()), "no client secret in the import's log")
    a = httpx.get(f"{B}/realms/cmapi"); check(a.status_code == 200 and a.json()["realm"] == "cmapi", "the live server serves the new realm, with no restart")
    check(others() == before, "the other realms' status and public key are unchanged")
    check(sh(C, "inspect", "cmapi-rt-kc", "--format", "{{.State.StartedAt}} {{.RestartCount}}").stdout == started, "the server did not restart")
    key = pk("cmapi")
    r = imp(); check(r.returncode == 0 and "already exists. Import skipped" in r.stdout + r.stderr, "a second import changes nothing: 'already exists'"); check(pk("cmapi") == key and others() == before, "and no key changed")
    # realm_sync.py: by path, so this test needs httpx and not the whole service
    spec = importlib.util.spec_from_file_location("realm_sync", os.path.join(ROOT, "cmapi/src/cmapi/tools/realm_sync.py")); rs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rs)
    job = yaml.safe_load(open(os.path.join(os.path.dirname(sys.argv[1]), "20-realm-sync.yaml")))
    env = {e["name"]: e.get("value") for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
    ldap = json.loads(env["CMAPI_REALM_LDAP"]); check(ldap.get("requireSync") is True, "the Job requires the sync"); ldap["connectionUrl"] = "ldap://127.0.0.1:389"
    env.update(CMAPI_REALM_ADMIN_URL=B, CMAPI_REALM_ADMIN_CLIENT_SECRET=vals["CMAPI_REALM_ADMIN_SECRET"], CMAPI_REALM_LDAP=json.dumps(ldap), bindDN="cn=admin,dc=ephico2real,dc=com", password="rt-ldap", ola="rt-ola", amy="rt-amy", opal="rt-opal", **{"bot-user": "rt-bot"})
    env.pop("CMAPI_CA_BUNDLE"); os.environ.update({k: v for k, v in env.items() if v is not None})
    rs.main([]); rs.main([]); check(True, "realm_sync.py twice, exit 0")
    def login(u, p): return httpx.post(f"{B}/realms/cmapi/protocol/openid-connect/token", data={"grant_type": "password", "client_id": "cmapi-automation", "client_secret": vals["CMAPI_AUTOMATION_SECRET"], "username": u, "password": p, "scope": "openid"})
    claims = lambda t: json.loads(base64.urlsafe_b64decode(t.split(".")[1] + "=" * (-len(t.split(".")[1]) % 4)))
    r = login("john.doe", "rt-john"); check(r.status_code == 200, "a login through LDAP federation")
    if r.status_code == 200:
        c = claims(r.json()["access_token"])
        check(c["iss"] == "https://keycloak.apps-crc.testing/realms/cmapi", "the token carries the public issuer, though it was asked for elsewhere")
        check(c["aud"] == "cmapi-nonprod", "audience"); check(c.get("employee_id") == "10001", "employee_id from uidNumber")
        check(c.get("groups") == ["/cmapi/cmapi-requesters"], f"groups, filtered on cmapi-*: {c.get('groups')}"); check("cmapi-requester" in c["resource_access"]["cmapi-nonprod"]["roles"], "the group's role")
    check(login("john.doe", "wrong").status_code == 401 or login("john.doe", "wrong").status_code == 400, "a wrong LDAP password is refused")
    check(login("bot-user", "rt-bot").status_code == 200, "the local bot user signs in")
    adm = httpx.post(f"{B}/realms/cmapi/protocol/openid-connect/token", data={"grant_type": "client_credentials", "client_id": "cmapi-realm-admin", "client_secret": vals["CMAPI_REALM_ADMIN_SECRET"]}).json()["access_token"]; A = {"Authorization": f"Bearer {adm}"}
    check(httpx.delete(f"{B}/admin/realms/corp-rt", headers=A).status_code == 403, "cmapi-realm-admin cannot delete another realm")
    # A sync that cannot reach LDAP must fail the Job.
    ldap["connectionUrl"] = "ldap://127.0.0.1:1"; os.environ["CMAPI_REALM_LDAP"] = json.dumps(ldap)
    try:
        rs.main([]); check(False, "a federation that cannot sync fails the Job")
    except SystemExit as e:
        check(bool(e.code), f"a federation that cannot sync fails the Job: {str(e.code)[:60]}")
    d = httpx.delete(f"{B}/admin/realms/cmapi", headers=A); check(d.status_code == 204, "cmapi-realm-admin deletes its own realm, with no master credential")
    a = httpx.get(f"{B}/realms/cmapi"); check(a.status_code == 404 and a.json() == {"error": "Realm does not exist"}, "and the issuer is Keycloak's own 404 again")
    check(others() == before, "the other realms' status and public key are unchanged at the end")
finally:
    cleanup()
print(f"realm cases failed: {len(fails)}"); sys.exit(1 if fails else 0)
```

