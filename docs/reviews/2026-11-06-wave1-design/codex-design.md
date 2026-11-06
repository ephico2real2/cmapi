> **Status: one of two independent designs for Wave 1 (#94), by Codex on an export of `9fd230a`. Arbitrated in `README.md`; most of its choices were not taken.** It predates the owner's requirements on the other realms and the backup. Nothing here has been applied.

# cmapi Wave 1 (#94) — independent deployment design

Status: design only, based on export `9fd230a` and the coordinator’s read-only CRC facts dated 2026-11-06. I did not run `oc`, `crc`, or `kind`, use a kubeconfig, or contact the cluster. “Measured” means measured by the coordinator and supplied in the brief, or measured locally from the export; other claims are marked inferred/proposed.

## Decisions

### 1. Files, render contract, and guards

Complete proposed inventory:

```
deploy/manifests/README.md                         changed
deploy/manifests/bootstrap/40-reader/reader.yaml  new; human applied
deploy/manifests/bootstrap/70-realm/cmapi.yaml    new; human applied, CR removed after Done
deploy/manifests/components/**                    unchanged
deploy/manifests/environments/kind/**             unchanged
deploy/manifests/environments/crc/00-namespaces.yaml new
deploy/manifests/environments/crc/10-env.yaml        new
deploy/manifests/environments/crc/20-config.yaml     new
deploy/manifests/environments/crc/30-trust.yaml      new
deploy/manifests/environments/crc/40-routes.yaml     new
deploy/manifests/environments/crc/50-monitoring.yaml new
deploy/render.sh, render-test.sh                  changed
deploy/secrets.sh, secrets-test.sh                changed
deploy/release-crc.sh, baseline-crc.sh            replaced
deploy/release-crc-test.sh, baseline-crc-test.sh  new
deploy/request-headroom.sh                        new
deploy/request-headroom-test.sh                   new
deploy/realm-delete-crc.sh                        new
deploy/realm-delete-crc-test.sh                   new
deploy/kind-test.sh                               unchanged
```

This follows D4 (`docs/reviews/2026-11-05-deployment-design.md:311-333`) and final rulings 2, 3, 5, 6, 7 and 9 (`:483-499`). Bootstrap is outside `render.sh`, hence outside future Argo ownership. `render.sh` copies only `components/` and one environment.

For CRC, `render.sh crc IMAGE OUT --trust-bundle FILE` copies the environment, replaces its sole trust placeholder, then hashes the *materialised* files declaring `cmapi-env`, `cmapi-config`, and `cmapi-trust`. It finally replaces image/checksum placeholders and atomically swaps output. Source components must contain exactly four exact cmapi image placeholders: API init/main and worker init/main (`components/cmapi/20-api.yaml`, `30-worker.yaml`). Counts 3 or 5 fail. Realm bootstrap has no cmapi image, so the count stays four.

### 2. Image

`release-crc.sh` builds with Podman and `GIT_COMMIT=9fd230a`, saves an archive, and uses Skopeo to push a temporary commit tag to the exposed registry Route. Authentication is `oc whoami -t | skopeo login --password-stdin`, with a temporary auth file; the token is never argv or output. The ingress CA is supplied through Skopeo’s certificate directory and TLS verification stays enabled. The script reads the resulting ImageStreamTag manifest digest and prints only:

```
image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:<64 hex>
```

Registries receive a manifest under a tag; the issue’s “push by digest” must mean deploy the resolved digest. Pods use OpenShift’s same-project generated image-pull integration, which the coordinator observed in `cmapi`. `render.sh` accepts only this repository/digest (or the existing GHCR repository/digest for non-CRC deployment tests).

Primary sources: [OpenShift exposed registry](https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/registry/securing-exposing-registry), [registry access/project-qualified repositories](https://docs.redhat.com/de/documentation/openshift_container_platform/4.22/html/registry/accessing-the-registry), and [`podman-login` password-stdin/authfile/cert-dir](https://docs.podman.io/en/v6.1.3/markdown/podman-login.1.html). I infer Skopeo is safer than a Podman remote push on macOS because its local copy command consistently accepts the certificate directory.

### 3. Trust

The run reads public CA data into a mode-0700 temporary directory: it resolves the Keycloak serving Secret from `Keycloak/keycloak.spec.http.tlsSecret` and reads that Secret’s `ca.crt`; it reads the ingress CA from measured `openshift-config-managed/default-ingress-cert` key `ca-bundle.crt`; and it appends an explicitly named external-DB CA if one is configured. Wave 1 uses CNPG, so there is no external DB CA. Preflight fails on an empty Secret reference/key; it never guesses a Secret name.

The checked-in CRC trust manifest contains only `CMAPI_TRUST_BUNDLE`. Render replaces it with validated PEM *before* the three-file checksum. Thus a CA rotation changes `checksum/config` and rolls API/worker. A cluster-only injected bundle is rejected because it would change without the repository checksum knowing. OpenShift notes that trusted-CA injection owns/replaces ConfigMap data in [Configuring a custom PKI](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/configuring_network_settings/configuring-a-custom-pki).

Mac checks of Routes use the ingress CA with `--cacert`; pods use the Keycloak serving CA for the Service URL. For Chrome, import the ingress public CA into the user login keychain, record its fingerprint and whether it was newly imported, then remove only a newly imported certificate. No `-k`, `--insecure`, or browser bypass.

### 4. Realm

The initial `RealmRepresentation` contains client scopes/clients/roles, realm-local service-account grants, groups, and read-only LDAP federation/mappers. Its six placeholders come from Secrets in `keycloak`: four generated-once client values in `cmapi-realm-secrets` plus owner-provided `bindDN` and `password` in `cmapi-ldap-bind`. The coordinator confirmed the owner Secret only in `cmapi`; therefore `secrets.sh` create-only copies those two values into `keycloak` when absent, labels the copy as script-managed, and never generates LDAP credentials. A partial or differing existing copy stops. No secret is in Git. These are not image placeholders.

No Wave 1 `realm-sync` Job is needed. The chart Job updated user profile, service roles, group mappings, LDAP/mappers/full sync, and optional local test users (`deploy/helm/cmapi/templates/jobs.yaml:45-102`; `cmapi/src/cmapi/tools/realm_sync.py:228-243`). Service roles, groups, and LDAP/mappers move into the import. Declarative user-profile customization, local users, and full sync are deferred; the LDAP mapper still supplies `employeeId` during login-on-demand. Later mutation of an existing realm does require the authenticated reconciler.

Before *any* secret write, `secrets.sh` performs `GET <issuer>` from the Mac with explicit CA. Only 404 means absent. 200 means present. Any other status, DNS/TLS/timeout/curl failure, malformed URL, or empty result stops. A failed check is never “no realm.” This implements ruling 7. The export does not: `deploy/secrets.sh:17-18` admits that deleting the import and both copies can mint behind a kept realm.

RHBK creates a one-shot import Job; an existing realm is not overwritten; deleting the CR does not delete the realm; deleting the successful CR cleans its Job/Pod. Source: [RHBK 26.6 Operator Guide, Importing a Realm](https://docs.redhat.com/en/documentation/red_hat_build_of_keycloak/26.6/html-single/operator_guide/index). Wait for `Done=True`; `HasErrors=True`, timeout, or any `keycloak-0` start-time/restart-count change stops. Then delete the import CR. Rerun with issuer 200 keeps secrets and skips import. Removal uses only the realm-local `cmapi-realm-admin` client to delete realm `cmapi`; no master credential.

### 5. Delivery mode

Run `delivery.mode: argocd`, with GitHub provider configured but no credential, and mark cluster `CRC` `writes: false`. Do not use `apply`: it is a real cluster writer (`cmapi/src/cmapi/core/sync.py:3-13,58-82`). There is no disabled third mode (`sync.py:29-48`). `build_context` constructs the Git adapter without a network call (`core/context.py:70-118`). With no requests, the worker performs database housekeeping and idles; it does not call Git or delivery. Any Wave 1 request is a stop condition.

### 6. Reader baseline

Plain YAML creates `cmapi-system`, `cmapi-reader`, its token Secret, and only: `/version:get`; namespaces/ResourceQuotas/LimitRanges `get,list,watch`; `selfsubjectreviews:create`. These cover registry connect, identity fallback, capability and watches (`core/registry.py:1-16,38,82-100`). The old baseline’s nodes, SAs, RBAC, users/groups, SCC, group-sync, Argo, policy, Route and monitoring reads are unjustified.

`baseline-crc.sh` applies the YAML, waits for controller-filled token/CA, and streams a create-only import Secret through stdin. Secret values are never argv/output. Existing import stops rather than being overwritten.

### 7. Routes and NetworkPolicy

Two Routes, both edge TLS with insecure redirect: `cmapi-api` -> HTTP 8080 and `cmapi-mockup` -> nginx HTTP. There is no real portal Route. Swagger redirect is exactly `https://cmapi-api.apps-crc.testing/docs/oauth2-redirect`. Mockup proof is captioned **“Static mockup; no API or sign-in is connected.”** The manifest already calls it static (`components/portal/10-mockup.yaml:1`).

Existing policy explicitly permits 8080 from the ingress-labelled namespace/same namespace and 9090 from `openshift-user-workload-monitoring` (`40-networkpolicy.yaml:1-31`). The router is measured HostNetwork on the one node; whether traffic attribution matches the rule is implementation-sensitive, so Route-after-policy is a measurement, not a YAML claim. Prometheus must also be observed. Source: [OpenShift NetworkPolicy](https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/network_security/network-policy) and [Routes/TLS termination](https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/ingress_and_load_balancing/routes).

### 8. Monitoring

ServiceMonitors for API/worker and the PrometheusRule move from `deploy/helm/cmapi/templates/monitoring.yaml` into CRC plain YAML. Scrape needs no Secret: metrics are unauthenticated but policy-limited. Proof queries Thanos through `oc get --raw`, using current `oc` authentication without an explicit token. Both `up` values must be 1. Source: [OpenShift user-workload monitoring](https://docs.redhat.com/en/documentation/monitoring_stack_for_red_hat_openshift/4.22/html/configuring_user_workload_monitoring/index).

### 9. First run and rollback

Exact runbook appears after the file appendix. Order is: no-kind/context/absence/headroom guards; top-before; Keycloak snapshot; CA extraction; build/push/digest/render; namespaces; issuer-guarded secrets; realm import and restart guard; reader baseline; config/policy; DB; workloads; Routes/monitoring; proofs; top-after/final restart guard. Every failed guard stops immediately.

Rollback deletes realm `cmapi` first with its realm-local client, then exact cmapi-owned names. It never deletes pre-existing namespace `cmapi`, the owner’s `cmapi-ldap-bind`, generated dockercfg, another realm/import, `inkcast`, `corp`, or group-sync. CNPG’s 2 Gi PVC uses the measured Retain class: PVC deletion leaves a Released PV and backing data. Kubernetes documents this in [Persistent Volumes — Retain](https://kubernetes.io/docs/concepts/storage/persistent-volumes/); CNPG documents its PVC/storage model in [CloudNativePG storage](https://cloudnative-pg.io/docs/current/storage/). Leave/report that exact PV for storage-owner reclamation. The issue’s “return to today’s state” cannot honestly include physical storage cleanup without that separate destructive action; deleting only the PV API object would hide remaining hostpath data.

### 10. Tests

Podman-kind/CI can prove YAML/schema, CNPG, security-context compatibility (not SCC choice), process start, migrations, ready/version, DB TLS, exact-four guard, digest allowlist, trust-checksum behavior, all script success/failure paths, secret idempotence and issuer 404/200/500/TLS-error behavior. It cannot prove Routes, `restricted-v2`, internal registry integration, RHBK import/restart, real LDAP, user-workload Prometheus, OVN HostNetwork policy, CRC headroom/top, or Retain cleanup. Existing Podman-kind removes NetworkPolicy for its known limitation, so cannot prove “started under policy.” Keep `deploy/kind-test.sh` and CI job `manifests` green.

OpenShift’s `restricted-v2` requirements (namespace UID range, RuntimeDefault seccomp, drop capabilities) are authoritative in [Managing security context constraints](https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/authentication_and_authorization/managing-pod-security-policies); the actual SCC annotation remains a CRC measurement.

Each new script has stub tests with deliberate failures. Render tests add missing/malformed bundle, trust count/checksum, and image counts 3/5. Secret tests add 404, 200, 500 and connection failure, checking no non-404 write. Release tests fail build/login/copy/digest and scan argv/output for token. Baseline tests fail existing Secret/missing token and assert stdin-only data.

### 11. Memory

Steady scheduling requests are 576 Mi: API `max(96 init,160 app)=160`; worker `max(96,128)=128`; CNPG 256; mockup 32. Against measured 4,018 Mi headroom, 3,442 Mi remains, 1,394 Mi above the 2 Gi stop. Limits total 1,536 Mi. The operator-generated import Job is transient and unspecified, so repeat headroom immediately before import. Other objects add no pod request.

### 12. Shared-cluster risks/guards

* Keycloak restart: start-time/restart snapshots before/after/final; stop on change; never patch/restart it.
* Pressure: recompute request headroom initially and immediately before import; stop under 2 Gi; top before/after.
* Router/monitoring policy: require observed Route and both scrape targets after policy.
* Registry collision: namespace-scoped ImageStream, commit tag, resolved digest, no global prune.
* Secret split brain: issuer check before writes, create-only, no values logged.
* LDAP: read-only, `cmapi-*` filter, no LDAP writes/master credential.
* DB/PV: exact 2 Gi claim, record retained PV, never touch `cmapi-test-pg`.
* Other projects: absence preflights, exact-name deletion, no VM/shared-service restart.
* Mixed state: any running kind cluster stops CRC.

## Corrections and evidence boundaries

`build-tracker.md:43` states the intended issuer check, but the exported script lacks it. Old `release-crc.sh` puts `oc whoami -t` behind `-p` and uses Helm; both violate the standing rules/ruling 9. Old `baseline-crc.sh:10-32` applies broad RBAC and handles secret data in shell substitutions. Chart CRC values enable Gitea/write-oriented bootstrap (`deploy/environments/crc.yaml:47-67`) and are source material, not Wave 1 desired state. The earlier D4 table mentions realm-sync, but final rulings do not require it; a complete initial import suffices, while later mutation remains future work. The issue’s Route-through-policy statement is unproven until measured on this HostNetwork CRC.

I read in full every prompt-named file, all `deploy/manifests/`, the named chart templates/values/scripts, and `cmapi/src/cmapi/tools`; I traced context/delivery/worker/registry/docs/version code. I measured four image placeholders and manifest requests locally. I could not check the cluster, LDAP contents, actual Keycloak TLS Secret/key, operator Job resources, Chrome trust, or CRC proof commands.

---

## Exact proposed file contents

### `deploy/manifests/bootstrap/40-reader/reader.yaml`

```yaml
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
  - nonResourceURLs: [/version]
    verbs: [get]
  - apiGroups: [""]
    resources: [namespaces, resourcequotas, limitranges]
    verbs: [get, list, watch]
  - apiGroups: [authentication.k8s.io]
    resources: [selfsubjectreviews]
    verbs: [create]
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

### `deploy/manifests/bootstrap/70-realm/cmapi.yaml`

This is intentionally a bootstrap CR, never rendered and never Argo-managed.

```yaml
apiVersion: k8s.keycloak.org/v2beta1
kind: KeycloakRealmImport
metadata:
  name: cmapi
  namespace: keycloak
  labels: {app.kubernetes.io/part-of: cmapi}
spec:
  keycloakCRName: keycloak
  placeholders:
    CMAPI_REALM_ADMIN_SECRET: {secret: {name: cmapi-realm-secrets, key: CMAPI_REALM_ADMIN_SECRET}}
    CMAPI_DIRECTORY_SECRET: {secret: {name: cmapi-realm-secrets, key: CMAPI_DIRECTORY_SECRET}}
    CMAPI_SVC_PAYMENTS_CI_SECRET: {secret: {name: cmapi-realm-secrets, key: CMAPI_SVC_PAYMENTS_CI_SECRET}}
    CMAPI_AUTOMATION_SECRET: {secret: {name: cmapi-realm-secrets, key: CMAPI_AUTOMATION_SECRET}}
    CMAPI_LDAP_BIND_DN: {secret: {name: cmapi-ldap-bind, key: bindDN}}
    CMAPI_LDAP_BIND_PASSWORD: {secret: {name: cmapi-ldap-bind, key: password}}
  realm:
    realm: cmapi
    displayName: cmapi
    enabled: true
    accessTokenLifespan: 300
    ssoSessionIdleTimeout: 28800
    ssoSessionMaxLifespan: 43200
    rememberMe: true
    revokeRefreshToken: true
    refreshTokenMaxReuse: 0
    attributes:
      userProfileEnabled: "true"
    clientScopes:
      - name: basic
        protocol: openid-connect
        attributes: {include.in.token.scope: "false", display.on.consent.screen: "false"}
        protocolMappers:
          - {name: sub, protocol: openid-connect, protocolMapper: oidc-sub-mapper, config: {access.token.claim: "true", introspection.token.claim: "true"}}
      - name: roles
        protocol: openid-connect
        attributes: {include.in.token.scope: "false", display.on.consent.screen: "false"}
        protocolMappers:
          - {name: client-roles, protocol: openid-connect, protocolMapper: oidc-usermodel-client-role-mapper, config: {multivalued: "true", user.attribute: foo, access.token.claim: "true", claim.name: "resource_access.${client_id}.roles", jsonType.label: String}}
      - name: profile
        protocol: openid-connect
        attributes: {include.in.token.scope: "true", display.on.consent.screen: "false"}
        protocolMappers:
          - {name: username, protocol: openid-connect, protocolMapper: oidc-usermodel-attribute-mapper, config: {user.attribute: username, claim.name: preferred_username, jsonType.label: String, access.token.claim: "true", id.token.claim: "true", userinfo.token.claim: "true"}}
          - {name: given-name, protocol: openid-connect, protocolMapper: oidc-usermodel-attribute-mapper, config: {user.attribute: firstName, claim.name: given_name, jsonType.label: String, access.token.claim: "true", id.token.claim: "true", userinfo.token.claim: "true"}}
          - {name: family-name, protocol: openid-connect, protocolMapper: oidc-usermodel-attribute-mapper, config: {user.attribute: lastName, claim.name: family_name, jsonType.label: String, access.token.claim: "true", id.token.claim: "true", userinfo.token.claim: "true"}}
      - name: email
        protocol: openid-connect
        attributes: {include.in.token.scope: "true", display.on.consent.screen: "false"}
        protocolMappers:
          - {name: email, protocol: openid-connect, protocolMapper: oidc-usermodel-attribute-mapper, config: {user.attribute: email, claim.name: email, jsonType.label: String, access.token.claim: "true", id.token.claim: "true", userinfo.token.claim: "true"}}
      - name: web-origins
        protocol: openid-connect
        attributes: {include.in.token.scope: "false", display.on.consent.screen: "false"}
        protocolMappers:
          - {name: allowed-web-origins, protocol: openid-connect, protocolMapper: oidc-allowed-origins-mapper, config: {access.token.claim: "true"}}
      - {name: offline_access, protocol: openid-connect, attributes: {include.in.token.scope: "true", display.on.consent.screen: "true"}}
      - name: cmapi-identity
        protocol: openid-connect
        attributes: {include.in.token.scope: "false", display.on.consent.screen: "false"}
        protocolMappers:
          - name: employee_id
            protocol: openid-connect
            protocolMapper: oidc-usermodel-attribute-mapper
            config: {user.attribute: employeeId, claim.name: employee_id, jsonType.label: String, access.token.claim: "true", userinfo.token.claim: "true"}
          - name: groups
            protocol: openid-connect
            protocolMapper: oidc-group-membership-mapper
            config: {claim.name: groups, full.path: "true", access.token.claim: "true", userinfo.token.claim: "true"}
      - name: cmapi-audience
        protocol: openid-connect
        attributes: {include.in.token.scope: "false", display.on.consent.screen: "false"}
        protocolMappers:
          - name: audience
            protocol: openid-connect
            protocolMapper: oidc-audience-mapper
            config: {included.client.audience: cmapi-nonprod, access.token.claim: "true", id.token.claim: "false"}
    roles:
      client:
        cmapi-nonprod:
          - {name: cmapi-viewer}
          - {name: cmapi-onboarding}
          - {name: cmapi-requester}
          - {name: cmapi-approver}
          - {name: cmapi-operator}
          - {name: cmapi-admin}
          - {name: cmapi-auditor}
          - {name: cmapi-approval-relay}
    clients:
      - clientId: cmapi-nonprod
        name: cmapi nonprod API
        enabled: true
        publicClient: false
        bearerOnly: true
        standardFlowEnabled: false
        directAccessGrantsEnabled: false
        defaultClientScopes: [basic, cmapi-identity, cmapi-audience, roles, profile, email]
      - clientId: cmapi-docs
        name: cmapi Swagger UI
        enabled: true
        publicClient: true
        standardFlowEnabled: true
        directAccessGrantsEnabled: false
        attributes: {pkce.code.challenge.method: S256}
        redirectUris: ["https://cmapi-api.apps-crc.testing/docs/oauth2-redirect"]
        webOrigins: ["https://cmapi-api.apps-crc.testing"]
        defaultClientScopes: [basic, cmapi-identity, cmapi-audience, roles, profile, email, web-origins]
      - clientId: cmapi-cli
        name: cmapi CLI
        enabled: true
        publicClient: true
        standardFlowEnabled: false
        directAccessGrantsEnabled: false
        attributes: {oauth2.device.authorization.grant.enabled: "true"}
        defaultClientScopes: [basic, cmapi-identity, cmapi-audience, roles, profile, email]
        optionalClientScopes: [offline_access]
      - clientId: cmapi-automation
        name: cmapi automation
        enabled: true
        publicClient: false
        secret: "${CMAPI_AUTOMATION_SECRET}"
        standardFlowEnabled: false
        directAccessGrantsEnabled: true
        defaultClientScopes: [basic, cmapi-identity, cmapi-audience, roles, profile, email]
      - clientId: svc-payments-ci
        enabled: true
        publicClient: false
        secret: "${CMAPI_SVC_PAYMENTS_CI_SECRET}"
        serviceAccountsEnabled: true
        standardFlowEnabled: false
        directAccessGrantsEnabled: false
        defaultClientScopes: [basic, cmapi-identity, cmapi-audience, roles, profile, email]
      - clientId: cmapi-directory
        enabled: true
        publicClient: false
        secret: "${CMAPI_DIRECTORY_SECRET}"
        serviceAccountsEnabled: true
        standardFlowEnabled: false
        directAccessGrantsEnabled: false
      - clientId: cmapi-realm-admin
        enabled: true
        publicClient: false
        secret: "${CMAPI_REALM_ADMIN_SECRET}"
        serviceAccountsEnabled: true
        standardFlowEnabled: false
        directAccessGrantsEnabled: false
    users:
      - username: service-account-cmapi-realm-admin
        enabled: true
        serviceAccountClientId: cmapi-realm-admin
        clientRoles: {realm-management: [realm-admin]}
      - username: service-account-cmapi-directory
        enabled: true
        serviceAccountClientId: cmapi-directory
        clientRoles: {realm-management: [view-users, query-users]}
    groups:
      - name: cmapi
        path: /cmapi
        subGroups:
          - {name: cmapi-viewers, path: /cmapi/cmapi-viewers, clientRoles: {cmapi-nonprod: [cmapi-viewer]}}
          - {name: cmapi-requesters, path: /cmapi/cmapi-requesters, clientRoles: {cmapi-nonprod: [cmapi-requester]}}
          - {name: cmapi-onboarding, path: /cmapi/cmapi-onboarding, clientRoles: {cmapi-nonprod: [cmapi-onboarding]}}
          - {name: cmapi-prod-approvers, path: /cmapi/cmapi-prod-approvers, clientRoles: {cmapi-nonprod: [cmapi-approver]}}
          - {name: cmapi-qa-leads, path: /cmapi/cmapi-qa-leads, clientRoles: {cmapi-nonprod: [cmapi-approver]}}
          - {name: cmapi-uat-leads, path: /cmapi/cmapi-uat-leads, clientRoles: {cmapi-nonprod: [cmapi-approver]}}
          - {name: cmapi-platform-leads, path: /cmapi/cmapi-platform-leads, clientRoles: {cmapi-nonprod: [cmapi-approver]}}
          - {name: cmapi-platform-operators, path: /cmapi/cmapi-platform-operators, clientRoles: {cmapi-nonprod: [cmapi-operator, cmapi-approver]}}
          - {name: cmapi-platform-admins, path: /cmapi/cmapi-platform-admins, clientRoles: {cmapi-nonprod: [cmapi-admin]}}
          - {name: cmapi-auditors, path: /cmapi/cmapi-auditors, clientRoles: {cmapi-nonprod: [cmapi-auditor]}}
    userFederationProviders:
      - displayName: ldap
        providerName: ldap
        priority: 0
        fullSyncPeriod: 86400
        changedSyncPeriod: 900
        config:
          enabled: "true"
          vendor: other
          editMode: READ_ONLY
          importEnabled: "true"
          syncRegistrations: "false"
          authType: simple
          bindDn: "${CMAPI_LDAP_BIND_DN}"
          bindCredential: "${CMAPI_LDAP_BIND_PASSWORD}"
          connectionUrl: ldaps://ldaps-ldap-testing.apps-crc.testing:443
          usersDn: ou=People,dc=ephico2real,dc=com
          usernameLDAPAttribute: uid
          rdnLDAPAttribute: uid
          uuidLDAPAttribute: entryUUID
          userObjectClasses: inetOrgPerson
          searchScope: "1"
          useTruststoreSpi: always
          connectionPooling: "true"
          pagination: "false"
          cachePolicy: MAX_LIFESPAN
          maxLifespan: "900000"
    userFederationMappers:
      - {name: username, federationProviderDisplayName: ldap, federationMapperType: user-attribute-ldap-mapper, config: {ldap.attribute: uid, user.model.attribute: username, read.only: "true", always.read.value.from.ldap: "false", is.mandatory.in.ldap: "true"}}
      - {name: email, federationProviderDisplayName: ldap, federationMapperType: user-attribute-ldap-mapper, config: {ldap.attribute: mail, user.model.attribute: email, read.only: "true", always.read.value.from.ldap: "true", is.mandatory.in.ldap: "false"}}
      - {name: first-name, federationProviderDisplayName: ldap, federationMapperType: user-attribute-ldap-mapper, config: {ldap.attribute: givenName, user.model.attribute: firstName, read.only: "true", always.read.value.from.ldap: "true", is.mandatory.in.ldap: "false"}}
      - {name: last-name, federationProviderDisplayName: ldap, federationMapperType: user-attribute-ldap-mapper, config: {ldap.attribute: sn, user.model.attribute: lastName, read.only: "true", always.read.value.from.ldap: "true", is.mandatory.in.ldap: "true"}}
      - {name: employee-id, federationProviderDisplayName: ldap, federationMapperType: user-attribute-ldap-mapper, config: {ldap.attribute: uidNumber, user.model.attribute: employeeId, read.only: "true", always.read.value.from.ldap: "true", is.mandatory.in.ldap: "false"}}
      - name: groups
        federationProviderDisplayName: ldap
        federationMapperType: group-ldap-mapper
        config:
          groups.dn: ou=Groups,dc=ephico2real,dc=com
          groups.ldap.filter: (cn=cmapi-*)
          group.name.ldap.attribute: cn
          group.object.classes: groupOfNames
          membership.ldap.attribute: member
          membership.attribute.type: DN
          membership.user.ldap.attribute: uid
          mode: READ_ONLY
          groups.path: /cmapi
          user.roles.retrieve.strategy: LOAD_GROUPS_BY_MEMBER_ATTRIBUTE
```

The legacy `userFederationProviders`/`userFederationMappers` representation must be validated against the installed 26.6.7 CRD/importer in a non-shared test before CRC. The Java API still exposes these `RealmRepresentation` fields ([RealmRepresentation](https://www.keycloak.org/docs-api/26.5.7/javadocs/org/keycloak/representations/idm/RealmRepresentation.html)); I could not execute the operator import here. If schema/import validation disproves it, the safe fallback is one realm-local sync Job, which deliberately changes the image placeholder count to five and must be reviewed—not an improvised CRC run.

### `deploy/manifests/environments/crc/00-namespaces.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: cmapi-imports
  labels: {app.kubernetes.io/part-of: cmapi}
```

Namespace `cmapi` is deliberately absent because it already exists.

### `deploy/manifests/environments/crc/10-env.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cmapi-env
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
data:
  CMAPI_GIT_PROVIDER: github
  CMAPI_GIT_URL: https://api.github.com
  CMAPI_GIT_DEFAULT_BRANCH: main
  CMAPI_LOG_LEVEL: INFO
  CMAPI_OIDC_JWKS_URL: https://keycloak-service.keycloak.svc:8443/realms/cmapi/protocol/openid-connect/certs
  CMAPI_KEYCLOAK_ADMIN_URL: https://keycloak-service.keycloak.svc:8443
```

### `deploy/manifests/environments/crc/20-config.yaml`

This is deliberately minimal and read-only rather than copying the chart’s write-capable CRC demo configuration.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cmapi-config
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
data:
  instance.yaml: |
    instance:
      name: nonprod
      displayName: Non-production
      allowedEnvironments: [rnd]
      publicUrl: https://cmapi-api.apps-crc.testing
      portalUrl: ""
      auth:
        issuer: https://keycloak.apps-crc.testing/realms/cmapi
        audience: cmapi-nonprod
      namespaces:
        reservedPatterns: ["ocp-*", "kubernetes-*"]
      identity:
        adminClient: cmapi-directory
        directory: keycloak
        cacheSeconds: 900
        requireEmployeeId: true
        requireOnBehalfOf: false
      git:
        repository: ephico2real2/cluster-configs-nonprod
        webUrl: https://github.com
      directory: {}
      docs: {enabled: true}
  clusters.yaml: |
    clusters:
      CRC:
        environment: rnd
        gitopsPath: clusters/CRC
        writes: false
        labels: {region: local}
        simulatedCapacity: {cpu: 8, memory: 16Gi}
  integrations.yaml: |
    delivery:
      mode: argocd
      syncTimeout: 10m
      argocd:
        namespace: cmapi-argocd
        rootApplication: cluster-configs-{clusterId}
    syncSignal: {default: poll, pollInterval: 30s}
    operations: {engine: builtin}
    events: {publisher: none}
    notifier: {smtp: {}}
  capacity.yaml: |
    mode: embedded
    snapshotInterval: 30m
    overcommit: {rnd: {cpu: 1, memory: 1}}
    targets: {rnd: {commitment: {critical: 0.95, warn: 0.85}, utilisation: {critical: 0.9, warn: 0.75}}}
  approval-rules.yaml: |
    defaults: {required: 1, group: platform-leads, timeoutHours: 24, selfApproval: false}
    environments:
      rnd: {create: 1, change: 1, delete: 1}
    autoApproval: {enabled: false, policies: []}
  authz-roles.yaml: |
    roles: {}
  tiers.yaml: |
    apiVersion: cmapi.net/v1
    kind: TierCatalog
    sizable: [requests.cpu, requests.memory, pods]
    tiers:
      small:
        order: 1
        description: Wave 1 read-only demonstration tier
        quota: {requests.cpu: "2", requests.memory: 4Gi, pods: "10"}
    environments:
      rnd: {offered: [small]}
  expiration.yaml: |
    environments: {}
  metadata-keys.yaml: |
    system: [cmapi.net/cluster-id, cmapi.net/managed, cmapi.net/request-id]
    operatorOnly: [cmapi.net/protected]
    reservedPrefixes: [kubernetes.io, k8s.io, openshift.io, argocd.argoproj.io]
    governed: {}
    team: {allowedPrefixes: [""]}
```

### `deploy/manifests/environments/crc/30-trust.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cmapi-trust
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
data:
  ca-bundle.crt: |
    CMAPI_TRUST_BUNDLE
```

### `deploy/manifests/environments/crc/40-routes.yaml`

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: cmapi-api
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi, app.kubernetes.io/component: api}
spec:
  host: cmapi-api.apps-crc.testing
  to: {kind: Service, name: cmapi-api, weight: 100}
  port: {targetPort: http}
  tls: {termination: edge, insecureEdgeTerminationPolicy: Redirect}
  wildcardPolicy: None
---
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: cmapi-mockup
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi, app.kubernetes.io/component: mockup}
  annotations: {cmapi.net/content: "static-mockup-no-api-or-sign-in"}
spec:
  host: cmapi-mockup.apps-crc.testing
  path: /
  to: {kind: Service, name: cmapi-mockup, weight: 100}
  port: {targetPort: http}
  tls: {termination: edge, insecureEdgeTerminationPolicy: Redirect}
  wildcardPolicy: None
```

### `deploy/manifests/environments/crc/50-monitoring.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cmapi-api
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
spec:
  selector:
    matchLabels: {app.kubernetes.io/name: cmapi-api, app.kubernetes.io/component: api}
  endpoints: [{port: metrics, path: /metrics, interval: 30s}]
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
  endpoints: [{port: metrics, path: /metrics, interval: 30s}]
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
          expr: sum(rate(cmapi_http_requests_total{status=~"5..",namespace="cmapi"}[5m])) / sum(rate(cmapi_http_requests_total{namespace="cmapi"}[5m])) > 0.02
          for: 10m
          labels: {severity: critical}
          annotations: {summary: "cmapi 5xx above 2% for 10 minutes"}
        - alert: CmapiIdpUnavailable
          expr: sum(increase(cmapi_idp_unavailable_total{namespace="cmapi"}[5m])) > 0
          for: 5m
          labels: {severity: critical}
          annotations: {summary: "cmapi cannot reach Keycloak signing keys"}
        - alert: CmapiGitUnavailable
          expr: sum(rate(cmapi_git_operations_total{result="failure",namespace="cmapi"}[5m])) / sum(rate(cmapi_git_operations_total{namespace="cmapi"}[5m])) > 0.20
          for: 5m
          labels: {severity: critical}
          annotations: {summary: "Git operation failures above 20% for 5 minutes"}
        - alert: CmapiWorkerNotLooping
          expr: absent(cmapi_worker_last_loop_timestamp_seconds{namespace="cmapi"}) or (time() - max(cmapi_worker_last_loop_timestamp_seconds{namespace="cmapi"})) > 120
          for: 2m
          labels: {severity: critical}
          annotations: {summary: "cmapi worker loop has not run for 120 seconds"}
        - alert: CmapiClusterUnreachable
          expr: cmapi_cluster_status{status="unreachable",namespace="cmapi"} == 1
          for: 10m
          labels: {severity: warning}
          annotations: {summary: "Cluster {{ $labels.cluster_id }} unreachable for 10 minutes"}
        - alert: CmapiSyncStuck
          expr: cmapi_open_change_requests_oldest_age_seconds{status="sync_failed",namespace="cmapi"} > 0
          for: 5m
          labels: {severity: warning}
          annotations: {summary: "A request is in sync_failed"}
        - alert: CmapiPruneStuck
          expr: cmapi_open_change_requests_oldest_age_seconds{status="awaiting_prune",namespace="cmapi"} > 86400
          for: 5m
          labels: {severity: warning}
          annotations: {summary: "A delete has awaited prune for over a day"}
        - alert: CmapiWorkerBacklog
          expr: sum(cmapi_jobs_pending{namespace="cmapi"}) > 100
          for: 15m
          labels: {severity: warning}
          annotations: {summary: "More than 100 cmapi jobs pending"}
        - alert: CmapiMemoryNearLimit
          expr: cmapi_process_memory_bytes / cmapi_process_memory_limit_bytes > 0.8
          for: 15m
          labels: {severity: warning}
          annotations: {summary: "{{ $labels.component }} above 80% memory limit"}
        - alert: CmapiAutoApprovalPaused
          expr: cmapi_auto_approval_paused{namespace="cmapi"} == 1
          for: 24h
          labels: {severity: info}
          annotations: {summary: "Auto-approval has been paused for 24 hours"}
        - alert: CmapiCpuThrottled
          expr: rate(cmapi_process_cpu_throttled_periods_total[5m]) / rate(cmapi_process_cpu_periods_total[5m]) > 0.01
          for: 30m
          labels: {severity: warning}
          annotations: {summary: "{{ $labels.component }} throttled in over 1% of CPU periods"}
        - alert: CmapiPodRestarting
          expr: increase(kube_pod_container_status_restarts_total{namespace="cmapi",container=~"api|worker"}[15m]) > 0
          labels: {severity: warning}
          annotations: {summary: "A cmapi container restarted"}
```

### `deploy/render.sh`

```bash
#!/usr/bin/env bash
# Plain manifests in; materialised plain manifests out. CRC additionally requires --trust-bundle FILE.
set -euo pipefail
ALLOW_TAG=false; TRUST_BUNDLE=; ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-tag) ALLOW_TAG=true; shift;;
    --trust-bundle) TRUST_BUNDLE=${2:?file after --trust-bundle}; shift 2;;
    *) ARGS+=("$1"); shift;;
  esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}
ENV_NAME=${1:?environment}
IMAGE=${2:?cmapi image}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${3:-$HERE/rendered/$ENV_NAME}
PLACEHOLDER='ghcr.io/ephico2real2/cmapi@sha256:DIGEST'
CHECKSUM_PLACEHOLDER=CMAPI_CONFIG_CHECKSUM
TRUST_PLACEHOLDER=CMAPI_TRUST_BUNDLE
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi | cut -d' ' -f1; }
config_checksum() {
  local name files
  for name in cmapi-env cmapi-config cmapi-trust; do
    files=$(grep -lE "^  name: ${name}\$" "$1"/*.yaml 2>/dev/null || true)
    case "$files" in
      "") echo "ERROR: no file in $1 declares ConfigMap $name" >&2; exit 1;;
      *$'\n'*) echo "ERROR: more than one file in $1 declares ConfigMap $name" >&2; exit 1;;
    esac
    printf '%s %s\n' "$name" "$(sha256 <"$files")"
  done | sha256
}

if ! [[ "$IMAGE" =~ ^(ghcr\.io/ephico2real2/cmapi|image-registry\.openshift-image-registry\.svc:5000/cmapi/cmapi)@sha256:[0-9a-f]{64}$ ]]; then
  if [ "$ALLOW_TAG" = true ] && [ "$ENV_NAME" = kind ]; then :
  else echo "ERROR: deployment image must be an allowed repository with a 64-hex digest" >&2; exit 1; fi
fi
[ "$ENV_NAME" = kind ] || [ "$ALLOW_TAG" = false ] || { echo 'ERROR: --allow-tag is kind-only' >&2; exit 1; }
SRC_ENV="$HERE/manifests/environments/$ENV_NAME"
[ -d "$SRC_ENV" ] || { echo "ERROR: no environment $ENV_NAME" >&2; exit 1; }
count=$(grep -RhoF "$PLACEHOLDER" "$HERE/manifests/components" | wc -l | tr -d ' ')
[ "$count" = 4 ] || { echo "ERROR: source must contain exactly four cmapi image placeholders, got $count" >&2; exit 1; }

if { [ -e "$OUT" ] || [ -L "$OUT" ]; } && { [ ! -d "$OUT" ] || { [ -n "$(ls -A "$OUT")" ] && [ ! -e "$OUT/.cmapi-render" ]; }; }; then
  echo "ERROR: $OUT is not an earlier render; not replacing it" >&2; exit 1
fi
OUT=${OUT%/}; OUT_PARENT=$(dirname "$OUT"); mkdir -p "$OUT_PARENT"
WORK=$(mktemp -d "$OUT_PARENT/.$(basename "$OUT").render.XXXXXX")
cleanup() { rc=$?; if [ -e "$WORK/old" ] && [ ! -e "$OUT" ]; then mv "$WORK/old" "$OUT"; fi; rm -rf "$WORK"; exit "$rc"; }
trap cleanup EXIT
NEW=$WORK/new; mkdir "$NEW"; : > "$NEW/.cmapi-render"
cp -R "$HERE/manifests/components" "$NEW/components"
cp -R "$SRC_ENV" "$NEW/environment"

trust_count=$(grep -RhoF "$TRUST_PLACEHOLDER" "$NEW/environment" | wc -l | tr -d ' ')
if [ "$ENV_NAME" = crc ]; then
  [ "$trust_count" = 1 ] || { echo "ERROR: CRC must contain exactly one trust placeholder, got $trust_count" >&2; exit 1; }
  [ -r "$TRUST_BUNDLE" ] || { echo 'ERROR: CRC requires readable --trust-bundle FILE' >&2; exit 1; }
  openssl crl2pkcs7 -nocrl -certfile "$TRUST_BUNDLE" >/dev/null 2>&1 || { echo 'ERROR: trust bundle is not valid PEM certificates' >&2; exit 1; }
  python3 - "$NEW/environment/30-trust.yaml" "$TRUST_BUNDLE" <<'PY'
from pathlib import Path
import sys
manifest, bundle = map(Path, sys.argv[1:])
text = manifest.read_text()
needle = "    CMAPI_TRUST_BUNDLE\n"
if text.count(needle) != 1:
    raise SystemExit("ERROR: trust placeholder is not one indented scalar line")
pem = bundle.read_text()
if not pem.endswith("\n"):
    pem += "\n"
manifest.write_text(text.replace(needle, "".join("    "+line for line in pem.splitlines(True))))
PY
elif [ "$trust_count" -ne 0 ]; then
  echo "ERROR: trust placeholder is CRC-only" >&2; exit 1
fi

CHECKSUM=$(config_checksum "$NEW/environment")
find "$NEW" -name '*.yaml' -print0 | while IFS= read -r -d '' f; do
  sed -i.bak -e "s|${PLACEHOLDER}|${IMAGE}|g" -e "s|${CHECKSUM_PLACEHOLDER}|${CHECKSUM}|g" "$f" && rm -f "$f.bak"
done
if grep -rnE "sha256:DIGEST|${CHECKSUM_PLACEHOLDER}|${TRUST_PLACEHOLDER}" "$NEW" >/dev/null; then
  echo 'ERROR: unfilled placeholder' >&2; exit 1
fi
printf '%s\n' "$IMAGE" > "$NEW/IMAGE"
if [ -e "$OUT" ]; then mv "$OUT" "$WORK/old"; fi
mv "$NEW" "$OUT"
echo "rendered: $OUT for $ENV_NAME with $IMAGE"
```

### `deploy/release-crc.sh`

```bash
#!/usr/bin/env bash
# Build locally and push to CRC. Prints only the in-cluster digest reference on stdout.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/.." && pwd)
COMMIT=; REGISTRY_CA=
while [ $# -gt 0 ]; do case "$1" in
  --commit) COMMIT=$2; shift 2;;
  --registry-ca) REGISTRY_CA=$2; shift 2;;
  *) echo "unknown argument: $1" >&2; exit 2;;
esac; done
[[ "$COMMIT" =~ ^[0-9a-f]{7,40}$ ]] || { echo 'ERROR: --commit must be a git SHA' >&2; exit 2; }
[ -r "$REGISTRY_CA" ] || { echo 'ERROR: --registry-ca must be readable' >&2; exit 2; }
openssl crl2pkcs7 -nocrl -certfile "$REGISTRY_CA" >/dev/null 2>&1 || { echo 'ERROR: registry CA is invalid' >&2; exit 2; }
if command -v kind >/dev/null && [ -n "$(KIND_EXPERIMENTAL_PROVIDER=podman kind get clusters 2>/dev/null)" ]; then echo 'ERROR: a kind cluster is running' >&2; exit 1; fi
[ "$(oc config current-context)" = crc-admin ] || { echo 'ERROR: not crc-admin context' >&2; exit 1; }
HOST=$(oc get route default-route -n openshift-image-registry -o jsonpath='{.spec.host}')
[ -n "$HOST" ] || { echo 'ERROR: registry Route has no host' >&2; exit 1; }
W=$(mktemp -d); chmod 700 "$W"; cleanup() { rm -rf "$W"; podman image rm "localhost/cmapi-design-$COMMIT" >/dev/null 2>&1 || true; }; trap cleanup EXIT
mkdir -p "$W/certs"; cp "$REGISTRY_CA" "$W/certs/ca.crt"; : > "$W/auth.json"; chmod 600 "$W/auth.json"
podman build --build-arg "GIT_COMMIT=$COMMIT" -t "localhost/cmapi-design-$COMMIT" -f "$ROOT/cmapi/Containerfile" "$ROOT/cmapi" >&2
podman save --format docker-archive -o "$W/cmapi.tar" "localhost/cmapi-design-$COMMIT"
oc create imagestream cmapi -n cmapi --dry-run=client -o yaml | oc apply -f - >/dev/null
oc whoami -t | skopeo login --username unused --password-stdin --authfile "$W/auth.json" --cert-dir "$W/certs" "$HOST" >/dev/null
skopeo copy --dest-authfile "$W/auth.json" --dest-cert-dir "$W/certs" "docker-archive:$W/cmapi.tar" "docker://$HOST/cmapi/cmapi:$COMMIT" >&2
for _ in $(seq 1 60); do
  DIGEST=$(oc get imagestreamtag "cmapi:$COMMIT" -n cmapi -o jsonpath='{.image.metadata.name}' 2>/dev/null || true)
  [[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] && break
  sleep 1
done
[[ "${DIGEST:-}" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo 'ERROR: ImageStreamTag did not resolve a digest' >&2; exit 1; }
printf 'image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@%s\n' "$DIGEST"
```

### `deploy/baseline-crc.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CLUSTER_ID=${1:-CRC}; IMPORTS=${2:-cmapi-imports}
[[ "$CLUSTER_ID" =~ ^[A-Z0-9_]+$ ]] || { echo 'ERROR: invalid cluster id' >&2; exit 2; }
[ "$(oc config current-context)" = crc-admin ] || { echo 'ERROR: not crc-admin context' >&2; exit 1; }
oc apply --server-side --field-manager=cmapi-wave1 -f "$HERE/manifests/bootstrap/40-reader/reader.yaml"
NAME=cmapi-cluster-$(printf '%s' "$CLUSTER_ID" | tr '[:upper:]_' '[:lower:]-')
if oc get secret "$NAME" -n "$IMPORTS" >/dev/null 2>&1; then echo "ERROR: $IMPORTS/$NAME already exists; not overwriting" >&2; exit 1; fi
W=$(mktemp -d); chmod 700 "$W"; trap 'rm -rf "$W"' EXIT
for _ in $(seq 1 60); do
  oc get secret cmapi-reader-token -n cmapi-system -o json > "$W/token.json"
  python3 - "$W/token.json" <<'PY' >/dev/null 2>&1 && break || true
import json,sys
d=json.load(open(sys.argv[1])).get("data",{})
assert d.get("token") and d.get("ca.crt")
PY
  sleep 1
done
python3 - "$W/token.json" "$CLUSTER_ID" "$IMPORTS" "$NAME" <<'PY' | oc create -f - >/dev/null
import base64,json,sys,yaml
src=json.load(open(sys.argv[1]))["data"]
doc={"apiVersion":"v1","kind":"Secret","metadata":{"name":sys.argv[4],"namespace":sys.argv[3],
     "labels":{"app.kubernetes.io/part-of":"cmapi","cmapi.net/secret-type":"cluster","cmapi.net/cluster-id":sys.argv[2]}},
     "type":"Opaque","data":{"apiUrl":base64.b64encode(b"https://kubernetes.default.svc").decode(),
     "token":src["token"],"caData":src["ca.crt"]}}
sys.stdout.write(yaml.safe_dump(doc,sort_keys=False))
PY
echo "baseline created: $IMPORTS/$NAME"
```

### `deploy/secrets.sh`

```bash
#!/usr/bin/env bash
# Idempotent secret creation. Never rotates, prints a value, or puts one in argv.
set -euo pipefail
NS=cmapi; REALM_NS=keycloak; KEY=; APP_ID=; INST_ID=; KUBECTL=oc; LDAP_BIND=true; ISSUER=; ISSUER_CA=
while [ $# -gt 0 ]; do case "$1" in
  --namespace) NS=$2; shift 2;;
  --realm-namespace) REALM_NS=$2; shift 2;;
  --kubectl) KUBECTL=$2; shift 2;;
  --issuer) ISSUER=$2; shift 2;;
  --issuer-ca) ISSUER_CA=$2; shift 2;;
  --github-app-key) KEY=$2; shift 2;;
  --github-app-id) APP_ID=$2; shift 2;;
  --github-installation-id) INST_ID=$2; shift 2;;
  --no-ldap-bind) LDAP_BIND=false; shift;;
  *) echo "unknown argument $1" >&2; exit 2;;
esac; done
# shellcheck disable=SC2086
kc() { $KUBECTL "$@"; }
PAIRS='realmAdminClientSecret:CMAPI_REALM_ADMIN_SECRET directoryClientSecret:CMAPI_DIRECTORY_SECRET svcPaymentsCiSecret:CMAPI_SVC_PAYMENTS_CI_SECRET automationClientSecret:CMAPI_AUTOMATION_SECRET'
rnd() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48; }
b64() { printf '%s' "$1" | base64 | tr -d '\n'; }
get() { kc get secret "$2" -n "$1" --ignore-not-found -o json; }
keys_of() { printf '%s' "$1" | python3 -c 'import json,sys; s=sys.stdin.read(); print("\n".join(k for k,v in ((json.loads(s) if s else {}).get("data") or {}).items() if v))'; }
apply_secret() {
  { printf 'apiVersion: v1\nkind: Secret\ntype: Opaque\nmetadata: {name: %s, namespace: %s, labels: {app.kubernetes.io/part-of: cmapi, cmapi.net/managed-by: secrets-script}}\ndata:\n' "$2" "$1"
    while read -r k v; do printf '  %s: %s\n' "$k" "$v"; done; } | kc create -f - >/dev/null
  echo "wrote Secret $1/$2"
}

# Authoritative realm check. A transport failure or non-404 is never absence.
if [ -z "$ISSUER" ]; then
  [ "$LDAP_BIND" = false ] || { echo 'ERROR: --issuer and --issuer-ca are required outside the kind-only --no-ldap-bind mode' >&2; exit 2; }
  case "$(kc config current-context 2>/dev/null)" in kind-*) ;; *) echo 'ERROR: issuer check may be omitted only on a kind context' >&2; exit 2;; esac
  realm_http=unchecked
else
  [ -r "$ISSUER_CA" ] || { echo 'ERROR: --issuer-ca must be readable' >&2; exit 2; }
  case "$ISSUER" in https://*/realms/cmapi) ;; *) echo 'ERROR: --issuer must be an https cmapi issuer URL' >&2; exit 2;; esac
  curl_out=$(mktemp); trap 'rm -f "$curl_out"' EXIT
  rc=0
  realm_http=$(curl --silent --show-error --output "$curl_out" --write-out '%{http_code}' --connect-timeout 10 --max-time 20 --cacert "$ISSUER_CA" "$ISSUER") || rc=$?
  [ "$rc" -eq 0 ] || { echo "ERROR: issuer check failed (curl rc=$rc); refusing to infer realm absence" >&2; exit 1; }
  case "$realm_http" in 200|404) ;; *) echo "ERROR: issuer check returned HTTP $realm_http; refusing to infer realm absence" >&2; exit 1;; esac
fi

# Read and validate every object before the first create.
ours=$(get "$NS" cmapi-keycloak); theirs=$(get "$REALM_NS" cmapi-realm-secrets); keys_existing=$(get "$NS" cmapi-keys)
if [ "$LDAP_BIND" = true ]; then lb_ours=$(get "$NS" cmapi-ldap-bind); lb_theirs=$(get "$REALM_NS" cmapi-ldap-bind); fi
gh_existing=$(get "$NS" cmapi-github-app)
verdict=$(OURS="$ours" THEIRS="$theirs" PAIRS="$PAIRS" python3 - <<'PY'
import json,os
pairs=[x.split(":") for x in os.environ["PAIRS"].split()]
oe,te=bool(os.environ["OURS"]),bool(os.environ["THEIRS"])
o=(json.loads(os.environ["OURS"]) if oe else {}).get("data",{}) or {}
t=(json.loads(os.environ["THEIRS"]) if te else {}).get("data",{}) or {}
om=[a for a,b in pairs if not o.get(a)]; tm=[b for a,b in pairs if not t.get(b)]
if not oe and not te: print("generate")
elif te and tm: print("partial realm copy, missing "+",".join(tm))
elif oe and om: print("partial namespace copy, missing "+",".join(om))
elif te and not oe: print("from-realm")
elif oe and not te: print("from-ours")
else:
 d=[a for a,b in pairs if o[a]!=t[b]]; print("same" if not d else "copies differ on "+",".join(d))
PY
)
case "$verdict" in generate|from-realm|from-ours|same) ;; *) echo "ERROR: $verdict; nothing generated" >&2; exit 1;; esac
[ "$verdict" != generate ] || [ "$realm_http" != 200 ] || { echo 'ERROR: realm exists but both secret copies are absent; refusing to mint' >&2; exit 1; }
[ "$verdict" != generate ] || [ "$realm_http" = 404 ] || [ "$realm_http" = unchecked ] || { echo 'ERROR: realm absence was not proven' >&2; exit 1; }
if [ -n "$keys_existing" ]; then for k in cursorKey linkKey; do keys_of "$keys_existing" | grep -qx "$k" || { echo "ERROR: cmapi-keys lacks $k" >&2; exit 1; }; done; fi
if [ "$LDAP_BIND" = true ]; then
  [ -n "$lb_ours" ] || { echo "ERROR: owner Secret $NS/cmapi-ldap-bind missing" >&2; exit 1; }
  for k in bindDN password; do keys_of "$lb_ours" | grep -qx "$k" || { echo "ERROR: $NS/cmapi-ldap-bind lacks $k" >&2; exit 1; }; done
  ldap_copy=false
  if [ -z "$lb_theirs" ]; then ldap_copy=true
  else
    for k in bindDN password; do keys_of "$lb_theirs" | grep -qx "$k" || { echo "ERROR: $REALM_NS/cmapi-ldap-bind lacks $k" >&2; exit 1; }; done
    OURS="$lb_ours" THEIRS="$lb_theirs" python3 -c 'import json,os; o=json.loads(os.environ["OURS"])["data"]; t=json.loads(os.environ["THEIRS"])["data"]; d=[k for k in ("bindDN","password") if o[k]!=t[k]]; raise SystemExit("ERROR: cmapi-ldap-bind copies differ" if d else 0)'
  fi
fi
if [ -n "$gh_existing" ]; then
  for k in appId installationId privateKey; do keys_of "$gh_existing" | grep -qx "$k" || { echo "ERROR: cmapi-github-app lacks $k" >&2; exit 1; }; done
elif [ -n "$KEY" ]; then
  [ -n "$APP_ID" ] && [ -n "$INST_ID" ] || { echo 'ERROR: GitHub key needs both ids' >&2; exit 2; }
  [ -r "$KEY" ] || { echo 'ERROR: GitHub key unreadable' >&2; exit 2; }
  mode=$(stat -c '%a' "$KEY" 2>/dev/null || stat -f '%Lp' "$KEY"); case "$mode" in *[1-7][0-7]|*[0-7][1-7]) echo "ERROR: $KEY is mode $mode; make it 0600" >&2; exit 2;; esac
fi

case "$verdict" in
  generate)
    lines=''; for p in $PAIRS; do lines+="${p%%:*} $(b64 "$(rnd)")"$'\n'; done
    while read -r a v; do [ -n "$a" ] || continue; for p in $PAIRS; do [ "${p%%:*}" = "$a" ] && echo "${p##*:} $v"; done; done <<<"$lines" | apply_secret "$REALM_NS" cmapi-realm-secrets
    printf '%s' "$lines" | apply_secret "$NS" cmapi-keycloak;;
  from-realm)
    THEIRS="$theirs" PAIRS="$PAIRS" python3 -c 'import json,os; t=json.loads(os.environ["THEIRS"])["data"]; [(print(p.split(":")[0],t[p.split(":")[1]])) for p in os.environ["PAIRS"].split()]' | apply_secret "$NS" cmapi-keycloak;;
  from-ours)
    OURS="$ours" PAIRS="$PAIRS" python3 -c 'import json,os; o=json.loads(os.environ["OURS"])["data"]; [(print(p.split(":")[1],o[p.split(":")[0]])) for p in os.environ["PAIRS"].split()]' | apply_secret "$REALM_NS" cmapi-realm-secrets;;
  same) echo 'realm secrets: both copies present and equal';;
esac
if [ -z "$keys_existing" ]; then printf 'linkKey %s\ncursorKey %s\n' "$(b64 "$(rnd)")" "$(b64 "$(rnd)")" | apply_secret "$NS" cmapi-keys; else echo 'cmapi-keys: present, kept'; fi
if [ "$LDAP_BIND" = true ]; then
  if [ "$ldap_copy" = true ]; then
    OURS="$lb_ours" python3 -c 'import json,os; d=json.loads(os.environ["OURS"])["data"]; [print(k,d[k]) for k in ("bindDN","password")]' | apply_secret "$REALM_NS" cmapi-ldap-bind
  else echo 'cmapi-ldap-bind: present and equal'; fi
fi
if [ -n "$gh_existing" ]; then echo 'cmapi-github-app: present, kept'
elif [ -n "$KEY" ]; then printf 'appId %s\ninstallationId %s\nprivateKey %s\n' "$(b64 "$APP_ID")" "$(b64 "$INST_ID")" "$(base64 <"$KEY" | tr -d '\n')" | apply_secret "$NS" cmapi-github-app; fi
```

`render-test.sh` changes line 37 to `rm -rf "$D/manifests/environments/crc"; cp -R ...`, then adds the trust/count cases described in decision 10. `secrets-test.sh` adds `--issuer`/`--issuer-ca` to CRC-like cases and a local issuer stub. Their existing full bodies remain otherwise byte-for-byte; these are test-harness changes, not deployment decisions. The two new stub tests are short wrappers around fake `oc`, `podman`, and `skopeo` commands and must assert both success and each named failure before merge.

### `deploy/manifests/README.md`

```markdown
# Plain deployment manifests

These are the deployment source of truth. No Helm or Kustomize is used here.

* `components/`: reusable cmapi, CNPG, and static-mockup objects.
* `environments/kind/`: throwaway tests.
* `environments/crc/`: Wave 1 config, trust placeholder, Routes, monitoring.
* `bootstrap/40-reader/`: person-applied reader baseline.
* `bootstrap/70-realm/`: person-applied one-shot realm import; never Argo-managed.

Run `deploy/render.sh ENV IMAGE [OUT]`. CRC additionally requires `--trust-bundle FILE`; render materialises that public PEM before hashing `cmapi-env`, `cmapi-config`, and `cmapi-trust`. Deployment images use digests. `--allow-tag` is kind-only.

The exact cmapi image placeholder appears four times: init/main in API and worker. Changing that count is a reviewed workload decision. Bootstrap is not rendered. Secrets come from `deploy/secrets.sh`, never this tree.
```

### `deploy/request-headroom.sh`

```bash
#!/usr/bin/env bash
# Read-only requested-memory guard. Usage: request-headroom.sh [minimum Mi, default 2048].
set -euo pipefail
MIN=${1:-2048}; [[ "$MIN" =~ ^[0-9]+$ ]] || { echo 'ERROR: minimum must be MiB' >&2; exit 2; }
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
oc get node -o json > "$W/nodes.json"; oc get pods -A -o json > "$W/pods.json"
python3 - "$W/nodes.json" "$W/pods.json" "$MIN" <<'PY'
import json,re,sys
def q(v):
 m=re.fullmatch(r"([0-9.]+)([KMGTE]i)?",v or "0"); assert m,v
 return float(m[1])*{"":1,"Ki":2**10,"Mi":2**20,"Gi":2**30,"Ti":2**40}.get(m[2] or "",1)
alloc=sum(q(n["status"]["allocatable"]["memory"]) for n in json.load(open(sys.argv[1]))["items"])
used=0
for p in json.load(open(sys.argv[2]))["items"]:
 if not p.get("spec",{}).get("nodeName") or p.get("status",{}).get("phase") in ("Succeeded","Failed"): continue
 app=sum(q(c.get("resources",{}).get("requests",{}).get("memory","0")) for c in p["spec"].get("containers",[]))
 init=max([q(c.get("resources",{}).get("requests",{}).get("memory","0")) for c in p["spec"].get("initContainers",[])]+[0])
 used += max(app,init)+q(p["spec"].get("overhead",{}).get("memory","0"))
head=(alloc-used)/2**20
print(f"requested-memory headroom: {head:.0f} Mi")
assert head >= int(sys.argv[3]),f"STOP: {head:.0f} Mi is below {sys.argv[3]} Mi"
PY
```

`request-headroom-test.sh` supplies fixed node/pod JSON through a stub `oc`: one case leaves 2049 Mi and passes, one leaves 2047 Mi and fails, and one verifies init scheduling uses `max(sum(app),max(init))` plus overhead. This new test must be committed in full with the implementation.

### `deploy/realm-delete-crc.sh`

```bash
#!/usr/bin/env bash
# Delete only realm cmapi using its own realm-admin client; secrets travel on stdin only.
set -euo pipefail
ISSUER=; CA=; KUBECTL=oc
while [ $# -gt 0 ]; do case "$1" in
  --issuer) ISSUER=$2; shift 2;;
  --ca) CA=$2; shift 2;;
  --kubectl) KUBECTL=$2; shift 2;;
  *) echo "unknown argument $1" >&2; exit 2;;
esac; done
[ "$ISSUER" = https://keycloak.apps-crc.testing/realms/cmapi ] || { echo 'ERROR: refusing any issuer except CRC realm cmapi' >&2; exit 2; }
[ -r "$CA" ] || { echo 'ERROR: --ca must be readable' >&2; exit 2; }
W=$(mktemp -d); chmod 700 "$W"; trap 'rm -rf "$W"' EXIT
# shellcheck disable=SC2086
$KUBECTL get secret cmapi-realm-secrets -n keycloak -o json > "$W/secret.json"
chmod 600 "$W/secret.json"
python3 - "$ISSUER" "$CA" "$W/secret.json" <<'PY'
import base64,json,ssl,sys,urllib.error,urllib.parse,urllib.request
issuer,ca,path=sys.argv[1:]
doc=json.load(open(path)); raw=doc.get("data",{}).get("CMAPI_REALM_ADMIN_SECRET")
if not raw: raise SystemExit("ERROR: realm-admin secret missing")
secret=base64.b64decode(raw).decode()
ctx=ssl.create_default_context(cafile=ca)
form=urllib.parse.urlencode({"grant_type":"client_credentials","client_id":"cmapi-realm-admin","client_secret":secret}).encode()
req=urllib.request.Request(issuer+"/protocol/openid-connect/token",data=form,method="POST")
with urllib.request.urlopen(req,context=ctx,timeout=20) as r: token=json.load(r)["access_token"]
base=issuer.rsplit("/realms/",1)[0]
req=urllib.request.Request(base+"/admin/realms/cmapi",method="DELETE",headers={"Authorization":"Bearer "+token})
with urllib.request.urlopen(req,context=ctx,timeout=20) as r:
 if r.status not in (200,204): raise SystemExit("ERROR: delete returned "+str(r.status))
try:
 urllib.request.urlopen(issuer,context=ctx,timeout=20)
except urllib.error.HTTPError as e:
 if e.code==404: print("deleted realm cmapi"); raise SystemExit(0)
 raise
raise SystemExit("ERROR: issuer still exists after delete")
PY
```

`realm-delete-crc-test.sh` uses a local TLS stub and fake `oc`: 204-delete then issuer-404 passes; token 401, delete 403, issuer still 200, missing Secret key, and TLS trust failure each fail; it scans argv/output for the fixture secret/token. No CRC or real realm is involved.

---

## Exact CRC runbook

```bash
set -euo pipefail
test "$(git rev-parse HEAD 2>/dev/null || printf 9fd230a)" = 9fd230a || { echo 'STOP: wrong source'; exit 1; }
if command -v kind >/dev/null && [ -n "$(KIND_EXPERIMENTAL_PROVIDER=podman kind get clusters 2>/dev/null)" ]; then echo 'STOP: kind is running'; exit 1; fi
test "$(oc config current-context)" = crc-admin || { echo 'STOP: wrong context'; exit 1; }
oc whoami | grep -qx kubeadmin || { echo 'STOP: wrong principal'; exit 1; }
for n in cmapi-imports cmapi-system; do if oc get ns "$n" >/dev/null 2>&1; then echo "STOP: $n exists"; exit 1; fi; done
if oc get keycloakrealmimport cmapi -n keycloak >/dev/null 2>&1; then echo 'STOP: import exists'; exit 1; fi
deploy/request-headroom.sh 2048
oc adm top node | tee output/crc-top-before.txt
KEYCLOAK_BEFORE=$(oc get pod keycloak-0 -n keycloak -o jsonpath='{.metadata.uid}{" "}{.status.startTime}{" "}{.status.containerStatuses[?(@.name=="keycloak")].restartCount}')
printf '%s\n' "$KEYCLOAK_BEFORE" > output/keycloak-before.txt

W=$(mktemp -d); chmod 700 "$W"; trap 'rm -rf "$W"' EXIT
KEYCLOAK_TLS_SECRET=$(oc get keycloak keycloak -n keycloak -o jsonpath='{.spec.http.tlsSecret}')
[ -n "$KEYCLOAK_TLS_SECRET" ] || { echo 'STOP: Keycloak CR has no spec.http.tlsSecret'; exit 1; }
oc get secret "$KEYCLOAK_TLS_SECRET" -n keycloak -o jsonpath='{.data.ca\.crt}' | base64 -d > "$W/keycloak-ca.crt"
oc get configmap default-ingress-cert -n openshift-config-managed -o jsonpath='{.data.ca-bundle\.crt}' > "$W/ingress-ca.crt"
openssl crl2pkcs7 -nocrl -certfile "$W/keycloak-ca.crt" >/dev/null
openssl crl2pkcs7 -nocrl -certfile "$W/ingress-ca.crt" >/dev/null
cp "$W/keycloak-ca.crt" "$W/cmapi-ca-bundle.crt"; printf '\n' >> "$W/cmapi-ca-bundle.crt"; sed -e '$a\' "$W/ingress-ca.crt" >> "$W/cmapi-ca-bundle.crt"

IMAGE=$(deploy/release-crc.sh --commit 9fd230a --registry-ca "$W/ingress-ca.crt")
deploy/render.sh crc "$IMAGE" deploy/rendered/crc --trust-bundle "$W/cmapi-ca-bundle.crt"
test "$(grep -RhoF 'ghcr.io/ephico2real2/cmapi@sha256:DIGEST' deploy/manifests/components | wc -l | tr -d ' ')" = 4
oc apply --server-side --field-manager=cmapi-wave1 -f deploy/rendered/crc/environment/00-namespaces.yaml
deploy/secrets.sh --issuer https://keycloak.apps-crc.testing/realms/cmapi --issuer-ca "$W/ingress-ca.crt"

deploy/request-headroom.sh 2048
oc apply --server-side --field-manager=cmapi-wave1 -f deploy/manifests/bootstrap/70-realm/cmapi.yaml
oc wait -n keycloak --for='condition=Done=true' keycloakrealmimport/cmapi --timeout=10m || { oc get keycloakrealmimport cmapi -n keycloak -o yaml; echo 'STOP: realm import failed'; exit 1; }
KEYCLOAK_AFTER=$(oc get pod keycloak-0 -n keycloak -o jsonpath='{.metadata.uid}{" "}{.status.startTime}{" "}{.status.containerStatuses[?(@.name=="keycloak")].restartCount}')
test "$KEYCLOAK_AFTER" = "$KEYCLOAK_BEFORE" || { echo 'STOP: keycloak-0 changed'; exit 1; }
curl --fail --silent --show-error --cacert "$W/ingress-ca.crt" https://keycloak.apps-crc.testing/realms/cmapi >/dev/null
oc delete keycloakrealmimport cmapi -n keycloak --wait=true

deploy/baseline-crc.sh CRC cmapi-imports
oc apply --server-side --field-manager=cmapi-wave1 -f deploy/rendered/crc/environment/10-env.yaml -f deploy/rendered/crc/environment/20-config.yaml -f deploy/rendered/crc/environment/30-trust.yaml
oc apply --server-side --field-manager=cmapi-wave1 -f deploy/rendered/crc/components/cmapi/00-serviceaccounts.yaml -f deploy/rendered/crc/components/cmapi/10-imports-reader.yaml -f deploy/rendered/crc/components/cmapi/40-networkpolicy.yaml
oc apply --server-side --field-manager=cmapi-wave1 -f deploy/rendered/crc/components/database-cnpg/cluster.yaml
oc wait -n cmapi --for=condition=Ready cluster/cmapi-db --timeout=10m
oc apply --server-side --field-manager=cmapi-wave1 -f deploy/rendered/crc/components/cmapi/20-api.yaml -f deploy/rendered/crc/components/cmapi/30-worker.yaml
oc apply --server-side --field-manager=cmapi-wave1 -f deploy/rendered/crc/components/portal
oc apply --server-side --field-manager=cmapi-wave1 -f deploy/rendered/crc/environment/40-routes.yaml -f deploy/rendered/crc/environment/50-monitoring.yaml
for d in cmapi-api cmapi-worker cmapi-mockup; do oc rollout status -n cmapi "deployment/$d" --timeout=5m; done
```

## Exact proof commands

```bash
oc get pods -n cmapi -l app.kubernetes.io/part-of=cmapi -o json > "$W/cmapi-pods.json"
python3 - "$W/cmapi-pods.json" <<'PY'
import json,sys
pods=json.load(open(sys.argv[1]))["items"]; assert pods
for p in pods:
 assert p["metadata"].get("annotations",{}).get("openshift.io/scc")=="restricted-v2",p["metadata"]["name"]
 cs=p.get("status",{}).get("containerStatuses",[])
 assert cs and all(x["ready"] and x["restartCount"]==0 for x in cs),p["metadata"]["name"]
print("restricted-v2, Ready, zero restarts:",", ".join(p["metadata"]["name"] for p in pods))
PY

# The Route response after policy is the NetworkPolicy proof on this CRC.
test "$(curl --silent --output /dev/null --write-out '%{http_code}' --cacert "$W/ingress-ca.crt" https://cmapi-api.apps-crc.testing/readyz)" = 200
curl --fail --silent --show-error --cacert "$W/ingress-ca.crt" https://cmapi-api.apps-crc.testing/api/v1/version > output/version.json
python3 -c 'import json; assert json.load(open("output/version.json"))["commit"]=="9fd230a"'

# Application-style DB connection. Secret URI is an env value, not argv/output.
sed "s|CMAPI_PROOF_IMAGE|$IMAGE|" <<'YAML' | oc create -f -
apiVersion: v1
kind: Pod
metadata: {name: cmapi-pg-ssl-proof, namespace: cmapi, labels: {app.kubernetes.io/part-of: cmapi}}
spec:
  restartPolicy: Never
  securityContext: {runAsNonRoot: true, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: proof
      image: CMAPI_PROOF_IMAGE
      command: [python, -c, "import os,psycopg; c=psycopg.connect(os.environ['CMAPI_DATABASE_URL']); print(c.execute(\"select ssl,version from pg_stat_ssl where pid=pg_backend_pid()\").fetchone())"]
      env:
        - {name: CMAPI_DATABASE_URL, valueFrom: {secretKeyRef: {name: cmapi-db-app, key: uri}}}
      securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
YAML
oc wait -n cmapi --for=jsonpath='{.status.phase}'=Succeeded pod/cmapi-pg-ssl-proof --timeout=2m
oc logs -n cmapi cmapi-pg-ssl-proof | tee output/pg-stat-ssl.txt
grep -q '(True,' output/pg-stat-ssl.txt
oc delete pod cmapi-pg-ssl-proof -n cmapi --wait=true

# No explicit Prometheus credential; oc proxies current authentication.
oc get --raw '/api/v1/namespaces/openshift-monitoring/services/https:thanos-querier:9091/proxy/api/v1/query?query=up%7Bnamespace%3D%22cmapi%22%2Cservice%3D~%22cmapi-%28api%7Cworker%29%22%7D' > output/prometheus-up.json
python3 -c 'import json; r=json.load(open("output/prometheus-up.json"))["data"]["result"]; assert len(r)==2 and all(x["value"][1]=="1" for x in r)'

oc adm top node | tee output/crc-top-after.txt
KEYCLOAK_FINAL=$(oc get pod keycloak-0 -n keycloak -o jsonpath='{.metadata.uid}{" "}{.status.startTime}{" "}{.status.containerStatuses[?(@.name=="keycloak")].restartCount}')
test "$KEYCLOAK_FINAL" = "$KEYCLOAK_BEFORE" || { echo 'STOP: keycloak-0 changed'; exit 1; }
```

Chrome proof: import the extracted ingress CA into the user login keychain; open `https://cmapi-api.apps-crc.testing/docs`; Authorize with a known LDAP-only identity; execute `GET /api/v1/me`; retain the HTTP-200 screenshot without a password. Since the import defines no local human users, successful first login is LDAP evidence; optionally record a non-empty `federationLink` via the realm-local directory client. Open `https://cmapi-mockup.apps-crc.testing/portal.html` and retain a screenshot captioned “Static mockup; no API or sign-in is connected.” Remove it only if newly imported for this run.

## Exact rollback boundary

First run `deploy/realm-delete-crc.sh --issuer https://keycloak.apps-crc.testing/realms/cmapi --ca "$W/ingress-ca.crt"`. It uses the realm-local client, deletes only `/admin/realms/cmapi`, and requires issuer 404. It must run before deleting that Secret. A master credential is forbidden.

Then record the bound PVC/PV and delete only these exact names:

```bash
oc get pvc -n cmapi -l cnpg.io/cluster=cmapi-db -o json > output/cmapi-pvc-before-rollback.json
oc delete route cmapi-api cmapi-mockup -n cmapi --ignore-not-found
oc delete servicemonitor cmapi-api cmapi-worker -n cmapi --ignore-not-found
oc delete prometheusrule cmapi -n cmapi --ignore-not-found
oc delete deployment cmapi-api cmapi-worker cmapi-mockup -n cmapi --ignore-not-found
oc delete service cmapi-api cmapi-worker cmapi-mockup -n cmapi --ignore-not-found
oc delete configmap cmapi-env cmapi-config cmapi-trust cmapi-mockup -n cmapi --ignore-not-found
oc delete networkpolicy cmapi-metrics -n cmapi --ignore-not-found
oc delete cluster cmapi-db -n cmapi --ignore-not-found --wait=true
oc delete pvc -n cmapi -l cnpg.io/cluster=cmapi-db --ignore-not-found --wait=true
oc delete service cmapi-db-r cmapi-db-ro cmapi-db-rw -n cmapi --ignore-not-found
oc delete secret cmapi-db-app cmapi-db-ca cmapi-db-server cmapi-db-replication -n cmapi --ignore-not-found
oc delete rolebinding cmapi-imports-reader -n cmapi-imports --ignore-not-found
oc delete role cmapi-imports-reader -n cmapi-imports --ignore-not-found
oc delete serviceaccount cmapi-api cmapi-worker cmapi-jobs -n cmapi --ignore-not-found
oc delete secret cmapi-keys cmapi-keycloak -n cmapi --ignore-not-found
oc delete imagestream cmapi -n cmapi --ignore-not-found
oc delete secret cmapi-realm-secrets -n keycloak --ignore-not-found
if [ "$(oc get secret cmapi-ldap-bind -n keycloak -o jsonpath='{.metadata.labels.cmapi\.net/managed-by}' 2>/dev/null || true)" = secrets-script ]; then oc delete secret cmapi-ldap-bind -n keycloak; fi
oc delete clusterrolebinding cmapi-reader --ignore-not-found
oc delete clusterrole cmapi-reader --ignore-not-found
oc delete namespace cmapi-system cmapi-imports --wait=true
```

Do **not** delete namespace `cmapi`, `cmapi-ldap-bind`, generated dockercfg, any other realm/import, or any unrelated object. Find the exact PV recorded for the cmapi claim and report it `Released`; because the storage class is `Retain`, leave it for explicit storage-owner reclamation rather than hiding residual hostpath data by deleting only the PV object.
