# The configuration of cmapi

This document says what an operator can set, and what each setting does. It says only what the code does. Each statement names the file that it comes from. Default values come from the code, never from an example file. A part that is designed and not built has the words "not built".

An instance of cmapi has three kinds of setting:

| Kind | Where | Read by |
|---|---|---|
| Files of the instance | `config/*.yaml`, mounted at `/etc/cmapi/config` | `cmapi/src/cmapi/core/config.py` (`load_instance`) and `cmapi/src/cmapi/core/context.py` (`build_context`) |
| Environment variables of the process | `CMAPI_*` | `cmapi/src/cmapi/settings.py` (`Settings`) |
| Helm values | `deploy/helm/cmapi/values.yaml` | The chart. It writes the files and the variables above |

## How cmapi reads its configuration

1. `load_instance` reads `instance.yaml` and the files below it, and checks each file against the others. It collects every problem and stops the process with all of them (`ConfigError`, `core/config.py`).
2. cmapi reads the files one time, at start. A reload is not built: the permission `admin:reload` exists and no route uses it (`docs/14`, "What is not built"). A change takes effect when the pods start again. The chart does that: each pod carries a hash of the ConfigMap as an annotation (`deploy/helm/cmapi/templates/api.yaml`, `worker.yaml`).
3. The files that the loader reads, and what happens when one is missing:

| File | Needed | If the file is missing |
|---|---|---|
| `instance.yaml` | Yes | The process stops |
| `approval-rules.yaml`, `tiers.yaml`, `expiration.yaml`, `authz-roles.yaml` | Yes | The process stops (`_read`, `core/config.py`) |
| `metadata-keys.yaml` | Yes | The process stops. The default path is `<config dir>/metadata-keys.yaml`. `CMAPI_METADATA_KEYS` sets another path (`settings.py`) |
| `clusters.yaml` | Yes | The process stops (`load_policies`, `core/registry.py`) |
| `plugins.yaml` | No | Each built-in plugin is enabled (`core/plugins.py`) |
| `integrations.yaml`, `capacity.yaml` | No | An empty mapping: each key takes the default of this document (`_yaml`, `core/context.py`) |

## The three instances

The owner runs three instances, one for each network zone. An instance serves the environments that its `allowedEnvironments` lists. The names are the owner's choice, and cmapi takes each name from the configuration (`docs/02`, "The names of instances and environments").

| Instance | `instance.name` | `allowedEnvironments` | Token audience | Git repository |
|---|---|---|---|---|
| Non-production | `nonprod` | `rnd`, `dev` | `cmapi-nonprod` | `caas/cluster-configs-nonprod` |
| Staging | `staging` | `qa`, `uat` | `cmapi-staging` | `caas/cluster-configs-staging` |
| Production | `prod` | `prod` | `cmapi-prod` | `caas/cluster-configs-prod` |

Source: `examples/instances/nonprod/instance.yaml`, `examples/instances/staging/instance.yaml`, `examples/instances/prod/instance.yaml`. Each instance has its own set of files. The other files of an instance name only its own environments: `tiers.yaml` has an entry for each environment, `approval-rules.yaml` has rules for each environment, and `expiration.yaml` names the environments that can expire. A file that names an environment that the instance does not serve stops the start (`core/config.py`, `core/tiers.py`, `core/approvals.py`).

One environment name has a meaning in code: `prod`. A namespace in `prod` never expires. `expiration.yaml` can have an entry for `prod` only with `enabled: false` (`plugins/expiration/rules.py`, #479), and the rendered policies add `deny-expiry-in-prod` for `prod` only (`core/policygen.py`, `_env_files`).

---

## `instance.yaml`

The file has one key, `instance`. The chart writes it from the values `instance.*`, `auth.*`, `git.repository` and `git.webUrl` (`deploy/helm/cmapi/templates/config.yaml`). The chart has no value for `instance.git.url`, `username`, `commitEmail`, `hostChecks` or `postStatus`: set them in the ConfigMap of the plain manifests (`deploy/manifests/environments/crc/20-config.yaml` sets `url`, `username` and `hostChecks`). Examples: `examples/instances/*/instance.yaml`.

How to make the bot account, its token and its SSH key, and how to switch `instance.git.url` to SSH: [`docs/19`](19-setup-connections-to-git.md).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `instance.name` | text | None. Needed | The name of the instance. It is in each log line, in each metric, in each request, and in the links of the email channel (`core/channels.py`) |
| `instance.displayName` | text | None | A name for people. The chart writes it. No Python code reads it |
| `instance.allowedEnvironments` | list of text | None. Needed | The environments that the instance serves. A write to another environment answers 422 `environment-not-served`, with the address of the instance that serves it when `directory` names one (`core/pipeline.py`, `check_env_served`) |
| `instance.publicUrl` | text (URL) | None | The address of the API. It is in the links of the pull request checks and in the examples of the API document (`jobs/pr_checks.py`, `main.py`) |
| `instance.portalUrl` | text (URL) | `""` | The address of the portal. The email channel uses it for its links (`core/channels.py`) |
| `instance.auth.issuer` | text (URL) | None. Needed | The Keycloak realm, as the realm's `.well-known/openid-configuration` gives it in `issuer`: `<base>/realms/<realm>`, with the realm's name percent-encoded (the realm `cmapi 640` is `.../realms/cmapi%20640`). A token with another `iss` is refused, and the comparison is exact. With the Keycloak directory on, cmapi does not start when the issuer holds a `?` or `#` anywhere, or when the part after the last `/realms/` is not one path segment: a `/` at the end, a further path, a space, a `%` that starts no encoded octet, octets that are not UTF-8, or `.` or `..` (`core/identity/keycloak_admin.py`, #640). With the directory off the issuer is not parsed: it is used only as written, for the `iss` comparison, the default `CMAPI_OIDC_JWKS_URL` and the sign-in URLs of the API document (`core/context.py`, `core/auth.py`) |
| `instance.auth.audience` | text | None. Needed | The client of the instance, for example `cmapi-nonprod`. A token for another audience is refused. The roles come from `resource_access.<audience>.roles` (`core/identity/claims.py`) |
| `instance.auth.acceptLegacyTokenType` | boolean | `false` | `true` accepts the header `typ` `JWT` together with the claim `typ` `Bearer`. Set it for a Keycloak that cannot write the header `at+jwt` (RFC 9068). See `docs/14`, "Step 1" |
| `instance.namespaces.reservedPatterns` | list of shell globs | `[]` | Names that nobody can ask for, added to the built-in list `default`, `openshift`, `openshift-*`, `kube-*`, `cmapi-system` and `cmapi-imports` (`core/naming.py`) |
| `instance.identity.directory` | `keycloak` | `keycloak` | The directory provider. `keycloak` is the only provider that is built. With another value, cmapi has no directory, and a request that names `onBehalfOf` answers 422 `unknown-user`, "No directory is configured" (`core/context.py`, `core/identity/checks.py`) |
| `instance.identity.adminClient` | text | `cmapi-directory` | The Keycloak client that reads users. It needs `view-users` and `query-users` only. Its secret is `CMAPI_DIRECTORY_CLIENT_SECRET`. Without the secret, cmapi has no directory |
| `instance.identity.cacheSeconds` | integer | `900` | How long a directory answer stays in the memory of a process (`core/context.py`) |
| `instance.identity.requireEmployeeId` | boolean | `true` | A person's token needs the claim `employee_id`. Without it: 422 `identity-incomplete` (`resolve_requester`, `core/identity/checks.py`) |
| `instance.identity.requireOnBehalfOf` | boolean | `false` | `true` makes a service client name the person that the request is for |
| `instance.identity.automationRoles` | list of roles | `[cmapi-onboarding]` | A caller with one of these roles needs no `employee_id` |
| `instance.identity.groupPath` | text | `/cmapi/app-cmapi-rbac-{name}` | The path of the Keycloak group that an approving group of `approval-rules.yaml` names. It starts with `/` and holds `{name}` one time. A bad value stops the start (`core/authz.py`, `check_group_path`) |
| `instance.git.repository` | text | None. Needed | The cluster-configs repository of the instance, as `owner/name` |
| `instance.git.webUrl` | text (URL) | The API URL of the Git host | The address of the repository for people |
| `instance.git.url` | text (URL) | `<webUrl>/<repository>.git` | The URL the worker's Git layer clones and pushes (#286): `https://host/path`, `ssh://git@host[:port]/path` or `git@host:path`. cmapi refuses `http://` and `git://` (no TLS), and a user or a token in an `https` URL (`core/git/transport.py`, `parse_remote`) |
| `instance.git.username` | text | `x-access-token` | For Git over HTTPS: the username sent with the token. The bot account's name, `cmapi-git-bot`, on GitHub |
| `instance.git.commitEmail` | text | `cmapi-git-bot@noreply.invalid` | The email of the commits' author and committer, `cmapi-git-bot`. Set it to the bot account's no-reply address on its host |
| `instance.git.hostChecks` | boolean | `false` | Host CI: when `true`, the worker waits for `ci/kubeconform` and `ci/kyverno` as commit statuses of the host, and posts its own. Never GitHub's Checks API |
| `instance.git.postStatus` | boolean | `false` | Post the worker's checks as commit statuses even with host CI off. Needs Commit statuses write |
| `instance.directory` | mapping | none | Where to send a caller for the other environments. Each entry has `url`, `environments` and an optional `portalUrl`. cmapi puts them in every 422 answer `environment-not-served`, and leaves out a URL that the entry does not give (`environment_not_served`, `core/config.py`; #671). `environments` is a list, and `url` and `portalUrl` are absolute http(s) URLs: another shape stops the start (`_directory_problems`) |
| `instance.cors.allowedOrigins` | list of origins | `[]` | The origins of other hosts that can call the API from a browser. With no key or an empty list, CORS is off. An origin is `https://host[:port]`, in lower case, or `http://localhost`, `http://127.0.0.1` or `http://[::1]`, with no path and no default port. A wildcard stops the start (`core/cors.py`) |
| `instance.http.maxRequestBodyBytes` | integer (bytes) | `1048576` (1 MiB) | The most bytes of request content that the API reads (#683). A request whose `Content-Length` is larger answers 413 `content-too-large` before any of it is read, with no sign-in; content with no length (chunked) is counted as it arrives and refused at the limit. The answer's `maxBytes` gives the value. A whole number from 1 to 9007199254740991 (2^53 - 1, the largest integer that JSON carries exactly; RFC 7493, section 2.2); another value, or another key under `http`, stops the start (`core/http_settings.py`), and the chart's schema refuses it. See "The request body limit" |
| `instance.problems.typeBase` | text (URL) | `https://cmapi.ephico2real.com/problems/` | The base of each problem `type` URI (RFC 9457). It is an absolute http or https URL with no query and no fragment (`core/errors.py`) |
| `instance.docs.enabled` | boolean | `true` | `false` turns off `/docs`, `/redoc` and the OpenAPI documents (`main.py`) |
| `instance.docs.public` | boolean | `true` | `false` makes each of those pages need a valid token (`main.py`, `_add_docs`) |
| `instance.policy` | mapping | See "The policy engine" | The policy engine and a mode for each environment |
| `instance.clusterTLS` | mapping | `{}` | Which environments may read a cluster with TLS verification off. See "Cluster trust" |

### The request body limit

`instance.http.maxRequestBodyBytes` bounds what one request makes the API read and parse (#683; OWASP API Security Top 10
2023, API4). Its default, 1 MiB, comes from the largest create body that the reference `metadata-keys.yaml` takes at its
maximums: 50 team labels and 50 team annotations with the longest keys (317 characters), and 64 KiB of annotation values
(`allowOther.maxBytesTotal`). That body is 102,581 bytes in ASCII, and 430,701 bytes when each value byte is a control
character, which `json.dumps` writes as a six-byte `\uXXXX` escape (measured; `docs/reviews/2026-11-25-issue-683`). So
1 MiB is 2.4 times the worst encoding. Kubernetes sizes its own limit the same way: 3 MiB, twice etcd's 1.5 MiB request
(`MaxRequestBodyBytes`, `k8s.io/apiserver/pkg/server/config.go`).

- **Raise it** when an instance raises `allowOther.maxBytesTotal` or `max` in its `metadata-keys.yaml`: allow about six times
  the annotation bytes, plus the keys.
- **The front door** (`cmapi-portal-ui/nginx/templates/cmapi.conf.template`) refuses more than 1 MiB itself
  (`client_max_body_size 1m`), before the API. A value above 1 MiB serves only callers that reach the API's port directly (#687).
- **The OpenShift router** has no setting for the size of a request body: neither a Route annotation nor an
  IngressController tuning option (the review record quotes both). The front door and the API set the limit.
- A 422 `validation-failed` names at most 20 errors (`main.py`, `MAX_VALIDATION_ERRORS`), whatever the body holds.

### The policy engine

`instance.policy` decides whether Kyverno runs, and in which mode, for each environment. The code is `cmapi/src/cmapi/core/policy.py`. The chart value is `instance.policy`.

```yaml
policy:
  engine: kyverno          # kyverno | none
  mode: audit              # audit | enforce | off, for each environment that `environments` does not name
  environments:
    prod: {mode: enforce}
```

| Key | Type | Default | Allowed values |
|---|---|---|---|
| `policy.engine` | text | `kyverno` | `kyverno`, `none` |
| `policy.mode` | text | `audit` | `audit`, `enforce`, `off` |
| `policy.environments.<env>.mode` | text | The value of `policy.mode` | `enforce`, `audit`, `off`. The environment must be one that the instance serves |
| `policy.reports.maxResultsPerCluster` | integer, 1 to 1,000,000 | `20000` | The rows of fail, warn and error that the Policies tab keeps for each cluster (#302). Past it, rows are counted and not listed, and the cluster's state is `capped`. 20,000 rows took 9.4 MiB in CPython (design B of #302, M17) |
| `policy.rejections.retentionDays` | integer, 1 to 3650 | `90` | How long a stored refusal of cmapi is kept (#302, the arbitration: one key for each instance). The worker's daily job `rejections_prune` deletes older rows, and `GET /api/v1/policies/rejections?since=` takes `1d` to this many days |

With no `policy` key, each environment audits (#342). The owner, 2026-11-17: "Kyverno should be in audit mode. The core logic like we said should be in the cmapi core logic itself." cmapi's own checks (names, tiers and their bounds, metadata keys) refuse a request in every mode and with `engine: none`; Kyverno reports beside them. An unknown key, an unknown value, and an environment that the instance does not serve each stop the start. `engine: none` runs no policy in any environment. With `engine: none`, an `environments` key, or a `mode` other than `off`, is an error (`PolicySettings.parse`).

| Mode | At plan time in cmapi | In the rendered policies | In CI on the pull request |
|---|---|---|---|
| `audit` (the default) | A Kyverno finding is a warning on the plan. The request goes to approval, and a warning keeps the auto-approval policies from applying | `validationActions: [Audit, Warn]`: admitted, recorded in the PolicyReport, and returned to the client as a warning | Reports and does not fail |
| `enforce` | A Kyverno finding refuses the plan with `policy-violation` | `validationActions: [Deny]` | Fails |
| `off` | No Kyverno run. kubeconform and the checks of cmapi still run | No policy files for the environment | No Kyverno run. The Kyverno status reports `success` |

Sources: `core/policy.py`, `core/validate/__init__.py` (`CliValidator.validate`), `core/policygen.py` (`ACTIONS`, `render_bundle`).

- A finding of cmapi about Kyverno itself (no binary, a policy that it cannot evaluate, a policy that gives no result) is an error in every mode (#213, F2).
- A body that breaks a metadata rule gets `422 policy-violation` from cmapi in every mode. cmapi still renders and validates the refused body, so the problem lists the validator's findings beside its `errors` in `findings`: in `audit`, Kyverno's warning on the same value. A refusal that comes before the render (a name, a tier and its bounds) has no `findings` (`core/pipeline.py`, `plan_namespace`).

- YAML 1.1 reads an unquoted `off` as the boolean `false`. cmapi reads `false` as `off` for a mode, and `true` stays an error (`_mode`, `core/policy.py`). Write `"off"` in quotes for clarity.
- When a served environment runs Kyverno and the image has no `kyverno` binary, cmapi does not start (`PolicyEngineMissing`, `core/validate/__init__.py`). When the variable `CMAPI_KYVERNO_VERSION` is set and a served environment runs Kyverno, the binary must be that version: the `Version:` line of `kyverno version`, compared whole, so `v1.20.0-rc1` is not `v1.20.0` (#395, #412; `CliValidator`, `kyverno_version`, `core/validate/__init__.py`). A binary of another version stops the start with `PolicyEngineMissing`. The image sets it (`cmapi/Containerfile`: v1.20.0).
- `GET /api/v1/admin/integrations` reports the engine, the mode of each environment, and the Kyverno version (`routers/admin.py`). The metric `cmapi_policy_mode{environment, mode}` is 1 for each (`core/context.py`).
- The Policies tab (#302) reads each cluster's PolicyReports and ClusterPolicyReports (`wgpolicyk8s.io/v1alpha2`) and its ValidatingPolicies through cmapi-reader, watched beside the cluster's watch cache (`core/clients/policyreports.py`). With `engine: none`, or an environment in `off`, no report is read and the cluster's state is `engine-off` or `mode-off`. Each rendered policy carries `cmapi.net/policy-digest`, the SHA-256 of its canonical JSON without that annotation (`policy_digest`, `core/policygen.py`): a copy on a cluster with another digest, a missing policy, or `validationActions` other than the mode's, is the state `drift`. The reader's ClusterRole needs `get`, `list` and `watch` on `policyreports`, `clusterpolicyreports` and `validatingpolicies` (`deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml`).
- The policies come from the configuration, not from files that a person writes. `core/policygen.py` renders them from `metadata-keys.yaml`, `tiers.yaml` and `instance.yaml` `policy`, as `policies.kyverno.io/v1` `ValidatingPolicy` objects. A hand-written policy in `CMAPI_POLICIES_DIR` (default `/etc/cmapi/policies`) runs with them (`core/validate/__init__.py`).
- The rendered metadata policies check each declared key, and the keys that no stanza declares (#333): for labels and for annotations, `cmapi-metadata-<env>-<kind>-other-keys-prefix` reports a key that `classify` calls `disallowed`, and `...-other-keys-max` more other keys than `allowOther.max`; for annotations, `...-max-value-bytes` and `...-max-bytes-total` report the bytes over `maxValueBytes` and `maxBytesTotal`. Each message names the keys and the setting, for example `the label keys other.example/x are not declared in metadata-keys.yaml, and are outside extraLabels.allowOther.prefixes ["", "*.ephico2real.com/"]`. A `system`, `operatorOnly` or reserved key is allowed on the namespace, since cmapi's renderer, an operator's request or the platform writes it; that a requester may not send one stays cmapi's own check. So a controller that labels namespaces outside `reservedPrefixes` gets a `fail` in the PolicyReport, which the portal's Policies tab shows. The shipped files reserve the two such controllers measured on OpenShift: OLM labels each target namespace of an OperatorGroup that does not target all namespaces `olm.operatorgroup.uid/<uid>` (operator-lifecycle-manager, `syncNamespace`), and OpenShift Pipelines' older RBAC loop labelled every non-system namespace `openshift-pipelines.tekton.dev/namespace-reconcile-version` (tektoncd/operator, `pkg/reconciler/openshift/tektonconfig/rbac.go`). Add the prefix of any other controller that labels or annotates team namespaces.
- A policy that keeps a value through `oldObject` (each declared key, `cmapi.net/cluster-id`, `cmapi.net/managed`, `cmapi.net/env`, and the bounds of a ResourceQuota and a LimitRange) has `evaluation.background.enabled: false` (#345): it reports at admission, where an UPDATE that keeps a value passes, and the background scan, which has no `oldObject`, does not run it. The other policies (the other keys, the order of a LimitRange, `deny-expiry-in-prod`) are also scanned in the background. A policy name over 63 characters is shortened to its first characters and 8 hex digits of its SHA-256, since Kyverno labels each report with the policy's name (#356). The decision record is `docs/reviews/2026-11-17-issue-333/`.
- To write the rendered files into the cluster-configs repository, run `cmapi-tools policies render --config-dir <dir> --metadata-keys <file> --out <dir>`. `cmapi-tools policies check --config-dir <dir> --metadata-keys <file> --dir <dir>` fails when a file differs from the render (`cmapi/src/cmapi/tools/policies.py`). The rendered files of an instance are the folders `env/<env>/` of its own environments. The decision record is `docs/reviews/2026-11-14-issue-212/` and `docs/reviews/2026-11-14-issue-213/`.

---

### Cluster import token lifetime

`instance.clusterTokens` defaults to `{duration: 7d, renewBeforePercentage: 20}`. A cluster's
`clusterTokens` entry in `clusters.yaml` inherits the instance settings. Specifying either renewal
setting replaces the inherited renewal setting. The Helm values use the same keys.

```yaml
instance:
  clusterTokens: {duration: 7d, renewBefore: 24h}
clusters:
  KIND_CMAPI_TEST:
    environment: rnd
    clusterTokens: {duration: 1h, renewBeforePercentage: 20}
```

Durations use an unsigned whole number and one suffix, `d`, `h`, `m` or `s`. For example, `7d` and
`168h` request the same duration. Request at least 20 minutes (`duration` ≥ `20m`, twice the
minimum renewal window) and observe the target API server's configured maximum. Kubernetes may
grant a shorter lifetime. Choose one of `renewBefore` and `renewBeforePercentage`; setting both
is refused at startup. `renewBefore` must be at least `10m` and strictly less than half of
`duration`. `renewBeforePercentage` must be an integer from 1 to 50, inclusive. These limits
also apply after inheriting instance settings.

The wanted window is `renewBefore` if set, otherwise the configured percentage (default 20) of
the JWT's **actual** lifetime (`exp - iat`). If the server grants less than `duration`, an
absolute `renewBefore` is replaced by 20% of that actual lifetime. Renewal is due at `exp - window`,
clamped to no earlier than `iat + lifetime / 2` and no later than `exp - 600`. The ten-minute
minimum exceeds the registry relist (300 seconds) plus the scan delay so every API pod reads the
new token before expiry. Bootstrap and manual recovery compute the same deadline. A new grant
already due for renewal is refused. A cluster clock up to 60 seconds ahead is allowed when checking
a new token. A full seven-day grant at 20% renews at 5.6 days, the one-hour example at 48 minutes,
and a twenty-minute grant at 10 minutes. A capped grant of either 86,700 or 86,699 seconds with
`renewBefore: 24h` renews at 80% of the grant, without a threshold jump.

When the chart manages the reader grant in an existing `cmapi-system` namespace, set
`reader.installRenewalRole: true`. The CRC and kind baseline manifests include this grant.

For the first import or manual recovery, pass the same settings to the script through
`CMAPI_TOKEN_DURATION` and, if needed, `CMAPI_TOKEN_RENEW_BEFORE` or `CMAPI_TOKEN_RENEW_BEFORE_PERCENTAGE`.
For example, run `CMAPI_TOKEN_DURATION=1h deploy/kind-import/up.sh <checkout>`.

### Cluster trust

How cmapi verifies each cluster's API server: one mode per cluster, from its import Secret (docs/02, "TLS: one mode per cluster";
#434). The analysis, its sources and the owner's decisions are in `docs/reviews/2026-11-18-issue-434/`.

| Mode | When | Trusted |
|---|---|---|
| `insecure` | The Secret says `insecure: "true"`, and `instance.clusterTLS` allows the cluster's environment | Nothing is verified. A deliberate downgrade |
| `caData` | The Secret has `caData` | That CA alone, never widened to the system store (client-go's rule) |
| `trusted` | Neither | The image's system store, then each bundle of `CMAPI_TRUSTED_CA_FILE`, in turn |

```yaml
clusterTLS:
  environments:
    rnd: {insecureSkipTLSVerify: true}
```

| Key | Type | Default | Allowed values |
|---|---|---|---|
| `clusterTLS.environments.<env>.insecureSkipTLSVerify` | boolean | `false` for each environment | `true` lets a cluster of `<env>` be read with `insecure: "true"`. Any served environment may, prod included (the owner, 2026-11-18). An environment that the instance does not serve, an unknown key or a value that is not a boolean stops the start (`core/clustertls.py`) |

An import Secret with `insecure: "true"` in an environment that does not allow it is `invalid-secret`, with the finding
`insecure is not allowed for environment <env>: instance.clusterTLS.environments.<env>.insecureSkipTLSVerify is false`, and no
client is built, so the token is never sent. A cluster read insecure shows `trust: {source: insecure, downgrade: true}` in
`GET /api/v1/clusters` and `cmapi_cluster_tls_insecure{cluster_id} 1`, and a change of mode logs `cluster_tls_mode` once (a
warning when insecure takes effect). The name is Kubernetes' for the same meaning: APIService `spec.insecureSkipTLSVerify`,
kubeconfig `insecure-skip-tls-verify`.

**The system store** is the image's own: OpenSSL's build-time cafile and capath (`ssl.get_default_verify_paths()`,
`openssl_cafile` and `openssl_capath`), loaded by path. It is not what `SSL_CERT_FILE` names: the pods set that variable to
`cmapi-trust`, Keycloak's CA alone, and it would replace the system store (measured, `analysis.md`).

**The bundles** (`CMAPI_TRUSTED_CA_FILE`, colon-separated): on OpenShift, the bundle injected into an empty ConfigMap labelled
`config.openshift.io/inject-trusted-cabundle: "true"`, which the Cluster Network Operator fills with the RHCOS trust bundle merged
with `proxy/cluster.spec.trustedCA`; and a ConfigMap that an operator makes for a CA the cluster does not know, never templated
from values. A path that is not there, or an empty file, is skipped and read again at the next check, since OpenShift fills the
injected ConfigMap after the pods start. A file that is there and does not load makes the cluster `cert-verify-failed`, with a
finding that names the file. A changed bundle is read at the next check, with no restart, and gives the cluster a new client.

| Where | The injected bundle | The operator's bundle |
|---|---|---|
| Chart | `trustedCA.injected.enabled: true`: ConfigMap `<release>-trusted-ca`, shipped empty | `trustedCA.existingConfigMap: {enabled: true, name: <yours>, key: ca-bundle.crt}` |
| Plain manifests | `environments/crc/35-trusted-ca.yaml`: ConfigMap `cmapi-trusted-ca`, shipped empty | ConfigMap `cmapi-cluster-ca`, key `ca-bundle.crt`, when you make it |
| Mounted at | `/etc/cmapi/trusted-ca/injected/ca-bundle.crt`, optional | `/etc/cmapi/trusted-ca/operator/<key>`; optional in the plain manifests, required in the chart (a name you gave that is missing stops the pods) |

```bash
oc create configmap cmapi-cluster-ca --from-file=ca-bundle.crt=/path/to/ca.pem -n cmapi
```

**Under Argo CD**, the injected ConfigMap carries `argocd.argoproj.io/sync-options: ServerSideApply=true`, so that the operator
keeps ownership of the data it writes. That is not enough alone: Argo CD sees data that the manifest lacks and, with self-heal,
would empty the bundle. The Application needs:

```yaml
spec:
  ignoreDifferences:
    - group: ""
      kind: ConfigMap
      name: cmapi-trusted-ca          # <release>-trusted-ca from the chart
      jsonPointers: [/data]
```

## `tiers.yaml`

The tier catalog: the quota and the limits of each tier, in each environment. The code is `cmapi/src/cmapi/core/tiers.py`. The chart file is `deploy/helm/cmapi/config/tiers.yaml`. The examples are `examples/instances/*/tiers.yaml`. The decision record for custom limits is `docs/reviews/2026-11-14-issue-211/README.md`. A key that is not in the schema stops the start (`extra="forbid"`).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `apiVersion` | text | None. Needed | Must be `cmapi.net/v1` |
| `kind` | text | None. Needed | Must be `TierCatalog` |
| `sizable` | list of quota keys | None. Needed | The quota keys that a custom-tier request must send, and that `PATCH .../quota` can change. The reference catalog has `requests.cpu`, `requests.memory` and `pods` |
| `overridable` | list of keys | `[]` | More keys that a custom-tier request can change. A quota key has its Kubernetes name (`requests.storage`). A limit key is `limitRange.<container\|pvc>.<min\|defaultRequest\|default\|max>.<resource>`. A key cannot be in `sizable` and `overridable`, and cannot be listed two times |
| `defaults` | mapping with `quota` and `limitRange` | `{}` | Values that each tier gets unless it sets its own |
| `tiers.<name>.order` | integer | None. Needed | The rank of the tier. Each order is unique. The sizable values must grow with the order |
| `tiers.<name>.description` | text | `""` | Text for people |
| `tiers.<name>.custom` | boolean | `false` | Marks the one custom tier. A catalog can have one. A custom tier fixes no sizable key |
| `tiers.<name>.quota` | mapping of key to quantity | `{}` | The `ResourceQuota` values. A tier that is not custom needs each sizable key |
| `tiers.<name>.limitRange` | mapping | `{}` | The `LimitRange` values, as `container` or `pvc`, then `min`, `defaultRequest`, `default` or `max`, then a resource |
| `custom.min`, `custom.max`, `custom.step` | mapping of key to quantity | `{}` | The bounds of custom values. Each `overridable` key needs a `custom.max` in each environment that offers the custom tier. A `min` cannot be above its `max`, and each `min` and `max` sits on its `step` |
| `environments.<env>.offered` | list of tier names | Each tier | The tiers that the environment offers |
| `environments.<env>.inherit` | text | None | The environment takes the settings of the named environment. Its own keys win. A loop of `inherit` stops the start |
| `environments.<env>.tiers.<name>` | mapping | `{}` | A partial `quota` and `limitRange` of one tier in this environment |
| `environments.<env>.custom` | mapping | `{}` | A partial `min`, `max` and `step` for this environment |

Resolution, later wins, and maps merge key by key: `defaults`, then `tiers.<name>`, then `environments.<env>.tiers.<name>`. The bounds: `custom`, then `environments.<env>.custom`.

The catalog must have an entry for each served environment and none for another one. The loader also checks these rules, and each failure stops the start:

- The container values keep the order `min <= defaultRequest <= default <= max` for `cpu` and for `memory`.
- A container `max` for a resource is not above the `requests.<resource>` of its tier (or `custom.min` for the custom tier), so one container at its limit fits.
- A resource that cannot overcommit (an extended resource or huge pages) has `defaultRequest` equal to `default`.

The start also stops when a tier has a value above the `custom.max` of its environment, in an environment whose policy mode is not `off`. The rendered policies would refuse that tier at admission (`_check_offered` in `core/policygen.py`, called from `build_context` in `core/context.py`).

### Values beyond the tier: approval is the gate

The owner's rule: approval is the gate of a capability. cmapi refuses a value that is not valid, and it sends each other value to the approval rules (`docs/reviews/2026-11-14-issue-211/README.md`).

| Case | What cmapi does | Source |
|---|---|---|
| A named tier, with a `quota` or a `limitRange` in the request | Refuses: `quota-with-named-tier`, `limits-with-named-tier` | `TierCatalog.quota_for`, `limits_for` |
| A custom tier, with a key that is not `sizable` or `overridable` | Refuses: `quota-key-not-sizable`, `limit-key-not-overridable` | `quota_for`, `limits_for` |
| A custom tier, with a value outside `custom.min`, `custom.max` or off its `step` | Refuses: `custom-out-of-bounds` | `_out_of_bounds` |
| A custom tier, with limits in the wrong order, or a container `max` above the namespace's `requests.<resource>` | Refuses: `limit-order-invalid`, `limit-exceeds-quota` | `limits_for` |
| A custom tier, with a valid value of a key that is not `sizable`, and that differs from the tier's value | The value is beyond the tier. cmapi sets the facts `beyondTier` and `beyondTierKeys`, and writes the keys in the annotation `cmapi.net/beyond-tier` on the object. A `sizable` key is never beyond the tier | `TierCatalog.beyond`, `render` |
| A request that raises `services.loadbalancers` or `services.nodeports` above the value that Git holds (or the tier, for a new namespace) | The fact `networkExposure` is `true` | `core/pipeline.py`, `EXPOSURE_KEYS` in `core/tiers.py` |

A value that Git already holds is not checked against the bounds again, and is not beyond the tier a second time. So a later, lower bound does not refuse a change to an old namespace (`_out_of_bounds`).

The facts go to `approval-rules.yaml`. See "Approval rules" below.

The switch of the storage `LimitRange` is not documented here. It is the work of an open pull request (#253).

---

## `metadata-keys.yaml`

The rules for the labels and the annotations that a requester sets on a namespace. The code is `cmapi/src/cmapi/core/metadata.py`. The same file feeds the rendered Kyverno policies, so plan time, CI and admission use the same rules (`core/policygen.py`). The chart file is `deploy/helm/cmapi/config/metadata-keys.yaml`; with Helm, a site sets its own as the value `metadata` (see "Setting the keys through the Helm values"). The decision record is `docs/reviews/2026-11-14-issue-215/README.md`.

### The keys of the file

| Key | Type | Default | Meaning |
|---|---|---|---|
| `system` | list of keys | `[]` | Keys that only the renderer sets. A request that sends one is refused (`reserved_key`). `cmapi.net/expiry` and `cmapi.net/expires-at` are system keys whether the list names them or not: only `expiresAt` writes them (#479) |
| `operatorOnly` | list of keys | `[]` | Keys that only an operator (`namespaces:protect`, docs/14) can set or remove. Another caller gets 403. A change that does not name such a key keeps the value that Git holds (#374). The shipped files list the labels of `protected.labels`, `cmapi.net/protected` and `do-not-delete`, so only an operator protects a namespace (#366) |
| `reservedPrefixes` | list of prefixes | `[]` | Prefixes of Kubernetes, OpenShift and platform controllers. A trailing `/` is allowed, and `*` matches (`fnmatch`). A request that sends such a key is refused (`reserved_key`) |
| `requiredLabels` | mapping of key to rule | `{}` | Labels that each namespace carries |
| `requiredAnnotations` | mapping of key to rule | `{}` | Annotations that each namespace carries |
| `extraLabels` | mapping | `{}` | `keys`: optional labels, each with a rule. `allowOther`: any other label under a prefix |
| `extraAnnotations` | mapping | `{}` | The same, for annotations |
| `adoptionLabels` | mapping of key to `{recognise: [values]}` | `{}` | Labels that mark a namespace that another tool made. A requester cannot set them: the class of such a key is `reserved`. Today cmapi reads only the keys, for that class. The adoption that reads the values (story #26) is not built |
| `sensitiveKeys` | list of keys | `[]` | A change of the value of one of these keys adds the fact `sensitiveKeyChanged`, once per request: a value that Git holds changes or goes, or a change of an existing namespace adds a required or extra key (#481). The first value of a create, and the first set of an operator-only key, are not a change. The shipped files list `cmapi.net/protected` and `do-not-delete`: protecting a namespace needs no extra approval, and removing the protection adds one approver-platform approval (#366) |
| `emailDomains` | list of domains | `[]` | The mail domains for a key with `format: email-in-domains`. A key of that format needs at least one domain |
| `liveOnlyKeys` | list of key globs | `[kubernetes.io/metadata.name, "openshift.io/*", "argocd.argoproj.io/*", app.kubernetes.io/instance]` | Keys that the cluster or its controllers write on a live namespace and Git never holds. `GET .../namespaces/{ns}` compares each governed, extra and operator-only key of Git with the live namespace (`sync`, #481) and leaves these out, so they are never drift. `*` matches as in `fnmatch`. Without the stanza, the default applies; an empty list compares every such key. System and reserved keys are never compared |

Where `emailDomains` is set: in each deployment's metadata configuration. On CRC it is `deploy/manifests/environments/crc/20-config.yaml`, key `emailDomains`; on kind it is the same key in `deploy/manifests/environments/kind/20-config.yaml`. The examples are `examples/cluster-configs/policies/metadata-keys.yaml` (`[ephico2real.com]`, a placeholder) and the company profile `metadata-keys.company.yaml` (`[company.net]`). To change it on CRC, edit that key, apply the ConfigMap, then `oc rollout restart deploy/cmapi-api deploy/cmapi-worker -n cmapi`. The domain is checked for format only: cmapi never looks a DL up.

The old stanzas `governed` and `team` stop the start. The error names the new stanzas (`MetadataKeys.__init__`). So a file of the old format cannot silently stop requiring a key.

The shape of the file is checked too (#338), so that a typo cannot load as a file with fewer rules:

- A top-level key that is not one of the eleven stanzas above stops the start, and the error names the nearest stanza: `unknown stanza 'requiredLabel': did you mean requiredLabels?`.
- A list stanza (`system`, `operatorOnly`, `reservedPrefixes`, `sensitiveKeys`, `emailDomains`) must be a list of text. A text such as `emailDomains: ephico2real.com` is refused; before #338 it loaded as its characters (`['e', 'p', 'h', ...]`).
- A mapping stanza (`requiredLabels`, `requiredAnnotations`, `extraLabels`, `extraAnnotations`, `adoptionLabels`), and `keys` and `allowOther` in an extra stanza, must be a mapping. An `adoptionLabels` entry has the one field `recognise`.
- Each `emailDomains` entry must be a domain name: labels of letters, digits and `-`, joined by `.`, as the chart's `values.schema.json` says.
- An empty stanza (`operatorOnly:` with nothing after it) is an empty list or mapping. The file itself must be a mapping: an empty file stops the start.

### The rule of one key

A key of `requiredLabels`, `requiredAnnotations` or `extraLabels.keys` or `extraAnnotations.keys` has a rule. Give one of `value`, `pattern`, `enum` and `format`. A key with none takes any value.

| Field | Type | Meaning |
|---|---|---|
| `value: {from: ...}` | `namespace`, `environment`, `cluster` or `instance` | cmapi sets the value from the target of the request. A create may leave the key out (cmapi fills it in) or send the same value. Any other value, or a removal, is refused (`derived_key`). On a change of an existing namespace (PATCH and the expiry calls), the key keeps the value that Git holds, even when the target has moved since the create, and a namespace that lacks the key keeps lacking it (adoption adds it, #26): only Git's own value may be sent back (#481). When Git's `cmapi.net/env` is not the cluster's environment any more, the system label follows the cluster and the plan has the warning `environment_moved` (#492). A key with `value` takes no `pattern`, `enum`, `format`, `namespacePrefix` or `default` |
| `pattern` | regular expression | The whole value must match. Written in the subset that Python, Kyverno and the API document read alike: see "Patterns" below |
| `enum` | list of text | The value is one of these. A label value must be a valid label value |
| `format` | `email-in-domains` or `url` | `email-in-domains`: an address with one `@`, a local part of ``[A-Za-z0-9!#$%&'*+/=?^_`{\|}~.-]``, and a domain in `emailDomains`, in any case of its ASCII letters. `url`: `http://` or `https://` in any case, a host with no `/`, `?`, `#`, whitespace or character whose NFKC form holds `/`, `?`, `#`, `@` or `:` (as `℀`, CVE-2019-9636), and a `[` only as `[userinfo@][IPv6 address]` with an optional `:port` after it, then optionally a path, query or fragment with no whitespace. Whitespace is what Python's `str.isspace()` calls whitespace. Each format is one regex (`value_regex` in `core/metadata.py`), which cmapi matches and the rendered Kyverno policy matches too (#332). A format is for annotations only: a label value is at most 63 characters of `[A-Za-z0-9_.-]`, so it cannot hold an address or a URL |
| `namespacePrefix` | boolean | The namespace name starts with the value and a `-`. For the value `abc`, the namespace `abc-rnd` passes. On a change of an existing namespace (PATCH), the key keeps the value that Git holds, since a change cannot rename: sending that value back is accepted, and another value or a removal is refused (`invalid_value`: "part of the namespace's fixed name"). A change cannot add the key to a namespace that lacks it; adoption does (#481). `GET .../namespaces` reads its value as each namespace's `mnemonic`. One key at most |
| `namespaceSuffix` | boolean | The namespace name ends with a `-` and the value (#479). On the key `value: {from: environment}`, a `dev` cluster takes `abc-payments-dev` and refuses `abc-payments-rnd` (`invalid_value` on this key: "abc-payments-rnd does not end with -dev"). With a `namespacePrefix` value of `abc`, both `abc-payments-dev` and the team-wide name `abc-dev` pass. An empty segment (`abc--dev`) is refused on the suffix key. Checked on a create; on a change the key keeps the value that Git holds, as `namespacePrefix` says (a filled-in one accepts only its exact Git value, `derived_key` otherwise). A key has `namespacePrefix` or `namespaceSuffix`, not both. One key at most |
| `default: {from: <key>}` | a key | When a create leaves this key out, cmapi copies the value of `<key>` into it; a sent value is kept (#479). `<key>` is a declared key of the same kind with no `default` of its own, so there is no chain. It may be a `value` key: cmapi fills that one first. An empty `<key>` fills nothing, so a required key left empty is reported missing. `cmapi.net/team` with `default: {from: company.net/mnemonic}` is `abc` when the request sends only the mnemonic `abc` |
| `title` | text | A short label for the key on a form, such as the portal's New namespace form: the reference file gives `cmapi.net/team` the title `Team` and `cmapi.net/team-dl` the title `Team DL`. With none, the form shows the key itself. The API document carries it as the property's JSON Schema `title` (#336) |
| `description`, `example` | text | Text for people and for the API document. A required key that cmapi does not derive needs an `example`, and every `example` must pass its key's own rule (the owner's answer to #328, question 3). A form shows the description under the field and the example as the field's placeholder, never as its value |

The loader refuses each of these, and the start stops:

- A key that is a system, operator-only or reserved key.
- A key declared two times as the same kind.
- An invalid label or annotation key, or an unknown field.
- A `pattern` that does not compile, that is empty, or that is outside the subset below (#332).
- More than one of `pattern`, `enum` and `format`.
- A required key with no `example`, unless it has `value`. An `example` that its key's rule refuses, or that is not text.
- A `title` or `description` that is not text, an empty `title`, and a `namespacePrefix` or `namespaceSuffix` that is not `true` or `false`.
- A second key with `namespacePrefix`, or a second with `namespaceSuffix`, and one key with both.
- A `default` that is not `{from: <key>}`, or whose key is not declared, is of the other kind, or has a `default` itself.
- An `allowOther.example` key that `allowOther` does not admit (outside its prefixes, a declared, system or reserved key), a value that is not a valid value of the kind, more keys than `max`, or annotation values over `maxValueBytes` or `maxBytesTotal`.
- A format on a label, and `email-in-domains` with no `emailDomains`.
- An `adoptionLabels` key that a stanza declares, or that is a system or operator-only key.
- An `adoptionLabels` entry whose `recognise` is not a list of label values.

A key can be a label and an annotation at the same time, each with its own rule.

### Patterns

Each `pattern` is read by RE2 in cmapi's validator (the whole value must match; `value_matches` in `core/metadata.py`, #348) and in the rendered Kyverno policies (CEL `matches()`), and by ECMA-262 or Python's `re` in each client of the API document (a JSON Schema `pattern`, #328). cmapi anchors a pattern once, as `^(?:P)$` (`anchored` in `core/metadata.py`), and the loader refuses a pattern that any of the three would read differently, with the key, the construct and its position: `extraAnnotations.company.net/code: pattern '^\\d{4}$' is outside the subset that Python re, RE2 (Kyverno) and ECMA-262 (the API document) read alike: \d (Python also matches the digits of other scripts): write [0-9], at character 2 (docs/18, "Patterns")`.

A pattern in the subset can still backtrack in an engine that backtracks. RE2 cannot (see the last paragraph of this section), but ECMA-262's engines do: a client that checks a value against the API document's schema in the browser or in Node, such as Ajv or `@cfworker/json-schema`, runs `new RegExp(pattern, "u")`, and `^(?:[a-z0-9]+-?)*[a-z0-9]$`, an everyday pattern for a name of parts, takes V8 944 ms on a 26-character value that ends in `!`, and four times as long for each two characters more (measured for #336, `docs/reviews/2026-11-17-issue-336/design-b/evidence/redos-v8.log`). The loader does not refuse such a pattern: no static check holds for every pattern (`(a|a)*` backtracks as badly as `(a+)+`), and cmapi itself is safe. So a client that checks a configured pattern itself must bound the time of the check: the portal runs each pattern in a Web Worker and stops it after 200 ms, says nothing about that field, and lets cmapi's answer to the dry run decide (#336). Prefer patterns with one way to match a value: `^[a-z0-9]+(-[a-z0-9]+)*$` accepts the same values as the pattern above (equal on all 21,845 strings of `a`, `b`, `0` and `-` up to 7 characters) and takes V8 under 1 ms on 10,001 characters (`docs/reviews/2026-11-17-issue-336/evidence/backtrack-equivalent.log`).

The subset is RFC 9485's interoperable regular expressions (I-Regexp) without `\p{..}` and `.`, with `^` and `$` where they change nothing:

| Allowed | Notes |
|---|---|
| A character, as itself | Any character other than `^ $ \ . * + ? ( ) [ ] { } \|` |
| `\^ \$ \\ \. \* \+ \? \( \) \[ \] \{ \} \\| \/`, and `\n \r \t` | `\-` only inside a class |
| `[...]` and `[^...]`, with ranges such as `a-z` | A `-` first, last, or as `\-`. A `[`, `]` or `\` inside as `\[`, `\]`, `\\`. No `&&`, `\|\|`, `~~` or `--` |
| `(...)`, `(?:...)` and `\|` | |
| `*`, `+`, `?`, `{n}`, `{n,}`, `{n,m}`, each optionally lazy (`*?`) | A count is at most 1000, and nested counts multiplied are at most 1000 (RE2's limit) |
| `^` at the start and `$` at the end of the pattern, or of a top-level alternative | `^a$\|^b$` is allowed; `(^a)` and `a$b` are not |

Refused, with what to write instead: `.` (ECMA-262 leaves out `\r`, U+2028 and U+2029: write `[^\n\r]`), `\d \w \s \b` and their capitals (write the class, as `[0-9]`), `\A \Z \z` (write `^` and `$`), inline flags as `(?i)`, named groups, lookaround, backreferences, atomic groups and possessive quantifiers, POSIX classes as `[[:alpha:]]`, `\p{..}`, character codes as `\x41` (write the character), `{,n}` (write `{0,n}`), and an unescaped `]`, `{` or `}`. The decision record, with its sources and the three-engine measurement, is `docs/reviews/2026-11-17-issue-332-338/README.md`.

cmapi matches with RE2 (Google's `google-re2` binding), so the time of a check is linear in the value whatever the pattern: a pattern such as `(a+)+b`, which is in the subset, cannot hold a worker on a crafted value, as it did with Python's backtracking `re` (1.4 s on 25 characters, doubling with each one). A value with a lone surrogate (`\ud800` in the JSON) never matches a pattern or a format: a Kubernetes string cannot hold one. A pattern whose program is beyond RE2's memory budget (8 MiB, for example a hundred `[^a]{1000}` in a row) stops the start with RE2's reason. The decision record is `docs/reviews/2026-11-17-issue-348/README.md`.

### `allowOther`

`allowOther` admits keys that no stanza declares, under a prefix.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `prefixes` | list of text | `[]` | The allowed prefixes. `""` allows a key with no prefix, and nothing else does. A `*` matches, as in `*.company.net/`, but only a key that has a prefix: `["*"]` admits any prefix that is not reserved, and no key without one (#331). With no prefix, cmapi refuses each other key (`invalid_key`, "prefix not allowed") |
| `max` | integer | `50` | The most other keys of this kind |
| `maxValueBytes` | integer | `4096` | Annotations only. The most bytes of one value |
| `maxBytesTotal` | integer | `65536` | Annotations only. The most bytes of all other annotation values |
| `example` | mapping of key to text | `{}` | Optional extra keys that the API document's create example shows, so it says that extra keys go in the same `labels` and `annotations` maps (#479). Each must be one that `allowOther` admits. An example only: nothing requires it |

The checks run in this order on a create (`MetadataKeys.validate`, #479): fill each `value` key that the request leaves out; fill each `default` key that it leaves out; the namespace name's prefix; its suffix; each sent key's syntax, class and rule, and each required key; the count and bytes of the other keys. A value that breaks its own rule gets that one error, not a prefix or suffix error too. Every refusal is an entry of `errors` in the 422 `policy-violation` problem.

### The classes of a key

Before any class, each key that a request sends must be a key that Kubernetes accepts, or it is refused (`invalid_key`):
the rule of apimachinery's `IsLabelKey`, which the API server applies to label keys and, lowercased, to annotation keys.
A key is a name of at most 63 characters, with an optional prefix and one `/`. When there is a `/`, the prefix before it
must be a DNS subdomain of at most 253 characters, so `/foo` (an empty prefix) and `a/b/c` are refused (#330). The loader
refuses a declared key or an adoption label that breaks the rule. cmapi applies the rule to annotation keys as written,
not lowercased, so it refuses an annotation prefix with capitals (`Example.com/abc`) that the API server would accept.

`MetadataKeys.classify` gives each key one class. The approval rules read the class as the fact `keyClasses`.

| Class | A key that | Through the API |
|---|---|---|
| `system` | Is in `system` | Refused |
| `operatorOnly` | Is in `operatorOnly` | Refused for a caller that is not an operator (403) |
| `reserved` | Is in `adoptionLabels` (as a label), or has a prefix of `reservedPrefixes`, even when `operatorOnly` names it too (#481) | Refused |
| `governed` | Is declared in a required or extra stanza | Allowed, with its rule |
| `team` | Has a prefix of `allowOther` | Allowed, within the limits |
| `disallowed` | Is none of these | Refused (`invalid_key`). A change may remove one that Git holds (`null`), which brings the namespace within the rules; the rendered other-keys policies report every change that keeps it (#492) |

A key that a stanza declares for the other kind only is refused even when `allowOther` admits its prefix. For example, a label `company.net/mnemonic-confluence` is refused as "an annotation" when only `extraAnnotations` declares it (`MetadataKeys.validate`). A change may remove such a label that Git holds (`null`), as a `disallowed` one (#492).

A required key that is missing or empty refuses the plan with `missing_required_key`. For an existing namespace that already lacks a required key, a request that does not touch the key is not refused: cmapi holds it, as the rendered policies do. A request that sends the key must give a valid value (`validate`, argument `existing`).

### What the code reads by name

Some key names are in the code, not only in the file. The `system` list of the reference files names each key that the renderer writes, so a requester cannot send one (`reserved_key`). Keep each of them in `system`.

| Name | Where | Effect |
|---|---|---|
| `cmapi.net/cluster-id`, `cmapi.net/managed`, `cmapi.net/env`, `cmapi.net/tier`, `cmapi.net/requested-by-user` (labels) | `core/render/manifests.py`, `core/tiers.py` (`render`) | The renderer writes them on each namespace. The ResourceQuota and the LimitRange carry `cmapi.net/cluster-id`, `cmapi.net/managed` and `cmapi.net/tier` |
| `cmapi.net/instance`, `cmapi.net/request-id`, `cmapi.net/requested-by`, `cmapi.net/tier-hash`, `cmapi.net/beyond-tier` (annotations) | `core/render/manifests.py`, `core/tiers.py` (`render`) | The renderer writes them. `cmapi.net/tier-hash` and `cmapi.net/beyond-tier` are on the ResourceQuota and the LimitRange |
| `cmapi.net/expiry` (label), `cmapi.net/expires-at` (annotation) | `core/render/manifests.py`, `core/pipeline.py` | The renderer writes them for a namespace with an expiry date. The planner reads `cmapi.net/expires-at` and `cmapi.net/tier` back from Git |
| `cmapi.net/team` | `core/pipeline.py`, `plugins/quotas/__init__.py`, `plugins/namespaces/router.py` | The label gives the fact `team` of a plan, and the column `change_requests.team`. The limit `maxPerTeamPerDay` counts requests for this value (`RequestRepo.auto_approvals_today`). A namespace with no such label has no team, and no daily allowance applies to it (#258) |
| `cmapi.net/team-dl` | `core/metadata.py` (`_governed`) | A bad address in this key is refused with the code `invalid-team-dl`. A bad address in each other key of the format `email-in-domains` is refused with `invalid_value` |
| `cmapi.net/app` | `plugins/quotas/__init__.py` | The quota list shows it as `app` |
| `cmapi.net/cluster-id`, `cmapi.net/managed` | `core/policygen.py` (`SYSTEM_REQUIRED`) | The rendered policies require both on a managed namespace |
| `cmapi.net/env` | `core/policygen.py` (`ENV_LABEL`) | The rendered policy for an environment requires `cmapi.net/env` to equal that environment |
| `cmapi.net/expires-at`, `cmapi.net/expiry`, `cleanup.kyverno.io/ttl` | `core/policygen.py` (`EXPIRY_KEYS`) | The rendered policy `deny-expiry-in-prod` refuses each of them in `prod` |

A file that does not declare `cmapi.net/team` is valid. Then the per-team allowance does not apply (the fact `team` is empty and `Pipeline.submit` skips the count). The owner's company example declares no `cmapi.net/team`, so with that file no namespace has a team in cmapi's sense.

### Setting the keys through the Helm values

With the Helm chart, an operator sets the file as the structured value `metadata` (#335). The chart writes it as `metadata-keys.yaml` into the `cmapi-config` ConfigMap, and the `checksum/config` annotation restarts the API and the worker on a change. The chart's `values.schema.json` checks the block on `helm install`, `helm upgrade`, `helm lint` and `helm template`, so a malformed block is refused before any pod starts. The loader stays the final check at start.

The rules of the value:

- **The block is the whole file**, not a patch of the chart's file. Write each of the stanzas of the table above, `{}` or `[]` when one is empty. Only `liveOnlyKeys` (#481) may be left out: the loader's default applies, so a block written before it still installs and upgrades. The schema refuses a block that leaves out any other, so a partial block cannot silently drop the reserved keys or the required ones.
- **Empty (`metadata: {}`, the default):** the chart's `config/metadata-keys.yaml`, or the full text in `configFiles."metadata-keys.yaml"`. That text stays the fallback, and the schema does not read inside it.
- **Both set:** the render fails: `metadata and configFiles."metadata-keys.yaml" both set metadata-keys.yaml: set one of them`.
- **What the schema refuses:** an unknown or misspelled stanza or field (`additionalProperties: false` at each level, so the old stanzas `governed` and `team` too); a missing stanza other than `liveOnlyKeys`; a wrong type (a text for a list, a limit that is not a whole number of zero or more); a key that is not a valid label or annotation key, including an empty prefix such as `/foo`; a `format` on a label; more than one of `pattern`, `enum` and `format`; `value.from` with a source other than `namespace`, `environment`, `cluster` or `instance`, or beside a `pattern`, `enum`, `format`, `namespacePrefix: true` or `default`; a `namespaceSuffix` that is not a boolean; a `default` that is not `{from: <key>}`; an `allowOther.example` key that is not a valid key or, for labels, a value that is not a label value; an empty `enum`, or a label `enum` value that a label cannot hold; an `adoptionLabels` entry with no `recognise`; a rule or an `example` that is not text; a required key with no `example` and no `value` (#332); a domain that is not a DNS name. The loader still checks what JSON Schema cannot: that a `pattern` compiles and is in the subset of "Patterns" above (its grammar nests parentheses, which the schema's own `pattern` keyword cannot describe), that an `example` passes its key's rule, that `email-in-domains` has a domain, that a key is not reserved or declared twice.
- `configFiles` takes only the five names of the chart's files. Another name, such as `metadata-key.yaml`, is refused; before #335 the chart ignored it and rendered its own file.

An example, a site that requires its own owner label beside the reference keys (`deploy/environments/<site>.yaml`):

```yaml
metadata:
  system: [cmapi.net/cluster-id, cmapi.net/managed, cmapi.net/request-id, cmapi.net/requested-by,
           cmapi.net/requested-by-user, cmapi.net/tier, cmapi.net/instance, cmapi.net/env, cmapi.net/tier-hash,
           cmapi.net/beyond-tier, cmapi.net/expiry, cmapi.net/expires-at]
  operatorOnly: [cmapi.net/protected, do-not-delete]
  reservedPrefixes: [kubernetes.io/, "*.kubernetes.io/", k8s.io/, openshift.io/, "*.openshift.io/",
                     argocd.argoproj.io/, "*.kyverno.io/", redhatcop.redhat.io/,
                     olm.operatorgroup.uid/, openshift-pipelines.tekton.dev/]
  requiredLabels:
    cmapi.net/team:     {pattern: "^[a-z0-9-]{2,40}$", example: payments}
    acme.example/owner: {pattern: "^[a-z]{2,20}$", description: "The owning group", example: payments}
  requiredAnnotations:
    cmapi.net/team-dl:  {format: email-in-domains, example: payments-team@acme.example}
  extraLabels:
    keys: {}
    allowOther: {prefixes: ["", "*.acme.example/"], max: 50}
  extraAnnotations:
    keys: {}
    allowOther: {prefixes: ["", "*.acme.example/"], max: 50, maxValueBytes: 4096, maxBytesTotal: 65536}
  adoptionLabels: {}
  sensitiveKeys: [cmapi.net/team, cmapi.net/protected, do-not-delete]
  liveOnlyKeys: [kubernetes.io/metadata.name, "openshift.io/*", "argocd.argoproj.io/*", app.kubernetes.io/instance]
  emailDomains: [acme.example]
```

Check a values file before an upgrade with `helm lint deploy/helm/cmapi -f deploy/environments/<site>.yaml -f deploy/images.lock.yaml`. The `system` list above is the reference list: keep each key that the renderer writes in it (see "What the code reads by name").

The plain manifests do not change: on CRC and kind the file stays the text of `metadata-keys.yaml` in `deploy/manifests/environments/<env>/20-config.yaml`, with no schema in front of it, and the loader is the check there.

**Why this shape.** Helm validates the final merged values against `values.schema.json` on install, upgrade, lint and template ([Helm, "Schema Files"](https://helm.sh/docs/topics/charts/#schema-files)). The chart keeps the default empty and takes the block as the whole file, as cert-manager's chart does with `config` (`config: {}`, rendered with `toYaml` into its `config.yaml`, with a draft-07 schema: [values.yaml](https://github.com/cert-manager/cert-manager/blob/master/deploy/charts/cert-manager/values.yaml), [controller-config.yaml](https://github.com/cert-manager/cert-manager/blob/master/deploy/charts/cert-manager/templates/controller-config.yaml)). Two other shapes were rejected:

- **The reference file as the default of `metadata` in `values.yaml`**, as the Prometheus chart does with `serverFiles` ([values.yaml](https://github.com/prometheus-community/helm-charts/blob/main/charts/prometheus/values.yaml)). Helm merges a map of a site's values into the default map, so a site's `requiredLabels` would add to `cmapi.net/team` rather than replace it, and removing a key takes a `null` for it. The rendered file would then differ from the site's own `metadata-keys.yaml` in its cluster-configs repository, from which its Kyverno policies are rendered. A default block also could not tell "the site set both" from "the site set the text", so the fallback could not stay.
- **The block merged over the chart's file in the template.** The same union problem, and the schema could not require a stanza, since it sees only the site's part.

The schema is draft-07: Helm up to 3.18 validates with `xeipuuv/gojsonschema` (drafts 4, 6 and 7), Helm 3.19 and 4 with `santhosh-tekuri/jsonschema` v6 (drafts 4 to 2020-12) (`go.mod` of [v3.18.0](https://github.com/helm/helm/blob/v3.18.0/go.mod) and [v3.19.0](https://github.com/helm/helm/blob/v3.19.0/go.mod)). Measured on 3.19.0 (CI) and 4.3.1; Helm 3.18 and older were not run. Key maps use `patternProperties` with `additionalProperties: false`, not `propertyNames`: on Helm 4.3.1 a `propertyNames` refusal names the right key but a wrong, changing location (measured on a two-property chart).

### The keys in each instance's Swagger UI and ReDoc

Each instance's API document (`/openapi.json`, which `/docs` and `/redoc` show) carries that instance's keys as schema: `labels` and `annotations` of `NamespaceCreate` and `NamespacePatch` are generated from its `metadata-keys.yaml` by `MetadataKeys.json_schema` in `core/metadata.py` (#328). The file reaches the document this way:

1. **Helm:** the value `metadata` (or the text `configFiles."metadata-keys.yaml"`, or the chart's own file when both are empty) is written into the `cmapi-config` ConfigMap. **Plain manifests:** the text of `metadata-keys.yaml` in `deploy/manifests/environments/<env>/20-config.yaml` is that ConfigMap.
2. The ConfigMap is mounted read-only at `/etc/cmapi/config`, and the API loads the file once at start (`core/config.py`).
3. The API builds its document from it at start (`main.py`, `build_openapi` with `ctx.cfg.metadata`). A change of the keys shows after a restart: with Helm, the `checksum/config` annotation restarts the pods; with the plain manifests, apply the ConfigMap and run `oc rollout restart deploy/cmapi-api deploy/cmapi-worker -n cmapi`.

What the schema says, for each map:

| From the file | In the schema |
|---|---|
| A required key | A property in `required` (create only); the map itself is in `NamespaceCreate.required`. A key that cmapi does not fill in also has `minLength: 1`. On a patch it has no `null` branch, since a patch cannot remove it |
| An optional key | A property; on a patch, `anyOf` with `null`, which removes it |
| `pattern`, `format` | `pattern`: the one regex that cmapi and the rendered Kyverno policy match too (`value_regex`, "Patterns" above), and `x-cmapi-format` for a format. A label also gets the label-value syntax and `maxLength: 63` |
| `enum` | `enum` |
| `value: {from: ...}` | A required property with `x-cmapi-derived-from` and the words "filled in by cmapi from the ...; you may leave it out", with no `null` branch on a patch. It is not `readOnly`, which Swagger UI hides in a request body (#479, A1): the owner wants these keys shown. cmapi still fills in one that a create leaves out, so the schema is stricter than cmapi there, on purpose |
| `default: {from: ...}` | `x-cmapi-default-from` and "Default: the value of ..." in the description |
| `namespacePrefix` | `x-cmapi-namespace-prefix: true`, and the rule in words. `NamespaceCreate.namespace` gets `x-cmapi-prefix-from` |
| `namespaceSuffix` | `x-cmapi-namespace-suffix: true`, and the rule in words. `NamespaceCreate.namespace` gets `x-cmapi-suffix-from` and both forms, `<prefix key>-<desired name>-<suffix key>` and `<prefix key>-<suffix key>`, in its description when a prefix key is configured |
| `title` | `title` |
| `description`, `example` | `description` (with the rule in words) and `examples`. Each declared key also has `x-cmapi-rule`: the rule in the words that a refusal's `detail` uses (`missing_required_key`), so a client says what the API says |
| `operatorOnly` | A property with `x-cmapi-operator-only: true` |
| Every declared and operator-only key | `x-cmapi-edit: {mode, reason, sensitive}`: how the key may change on an existing namespace (#481). `mode` is `fixed` (a `namespacePrefix` or `namespaceSuffix` key), `automatic` (`value: {from: ...}`), `required`, or `optional` (an extra key, and an operator-only key for a caller with `namespaces:protect`); `reason` is the words a person sees, such as "Part of the namespace's fixed name."; `sensitive` is true for a key of `sensitiveKeys`, whose change adds one approval. The same on a create and a change: `MetadataKeys.edit_rule` decides it from the file, in the order of the #481 design, section 3 |
| `allowOther` | `propertyNames`: a declared key, or a key under an allowed prefix that is not a system key, an adoption label, a key of the other kind or under a reserved prefix. `additionalProperties`: the value rule of those keys. `x-cmapi-other-keys`: the prefixes, limits and any sensitive additional keys |

The same two maps are served on their own by `GET /api/v1/metadata-keys` (#336), with the permission `objects:read`, also when `docs.enabled` is false: `{"labels": ..., "annotations": ..., "x-cmapi-expiration": ...}`, the first two exactly the objects of `NamespaceCreate` above without their `title`, `description` and `examples` (a service test holds the two equal on the reference and the company file), and the third the `x-cmapi-expiration` of `NamespaceCreate.expiresAt` (`expiration.yaml` below, #479), so the `ETag` changes when a rule in the answer does (`maxExtensionDays` is not in it: `GET /api/v1/expirations` serves it). The portal's New namespace form builds its fields from it. The first request builds the answer and caches it for the loaded files, which a change restarts the pods to load. It has a strong `ETag` over its bytes and `Cache-Control: private, no-cache`. `If-Match` is read first (#590): `If-Match: *` passes, and any other value must list the `ETag`, by the strong comparison, or the answer is `412`. Then a matching `If-None-Match` answers `304`.

What JSON Schema cannot say is in the description of the map, which ReDoc shows (ReDoc 3.1.0 does not show `propertyNames`): who may set an operator-only key, that a derived value must equal the request's target, that a `namespacePrefix` value starts the namespace name, the count of other keys (`max`), the sizes in bytes (`maxValueBytes`, `maxBytesTotal`; the schema's `maxLength` counts characters, a bound that holds because a character is at least one byte), and on a patch the 253 characters of a key's prefix (a create refuses a longer one with a second pattern under `not`). On a patch, `propertyNames` checks the class of a key and not its syntax: a key that Git holds from before #330, such as `/foo`, can still be removed with `null`, and JSON Schema cannot tie a key's name to its value.

The schema documents cmapi's own check; it never replaces it. cmapi refuses each body with or without Kyverno (`policy.engine: none` included), and a client that checks the schema first only learns of a refusal sooner. Each map that cmapi accepts passes the schema, except a create that leaves out a key that cmapi fills in (`value` or `default`), which the schema lists as required (#479): `cmapi/tests/core/test_metadata_schema_328.py` runs one corpus of about 12,000 maps for each file through both, on the shipped files and on four synthetic ones, and `cmapi/tests/service/test_metadata_schema_328_api.py` runs it on each instance's served document.

The examples in the document are this instance's too (#334, #479): the `labels` and `annotations` examples are the `example` of each declared key that has one, the value of each `value` key for the example's target, and the `allowOther.example` keys. The namespace example is `<prefix example>-<desired name>-<environment>`: the example of a `namespacePrefix` key and `-` start it (`abc-payments-dev` with the company file), and with a `namespaceSuffix` key it ends with the environment. The example's cluster is `CRC` when `clusters.yaml` lists it as writable, or else the first writable cluster there, with that cluster's environment; with none, it is `CRC` and the first of `allowedEnvironments`. The create operation's `cluster_id` example and its curl sample name the same cluster; `cmapi-tools openapi render` reads the `clusters.yaml` of `--config-dir` the same way. The patch example is the first optional key that has an example. Swagger UI's "Try it out" body and the curl sample of each write are one body, built from them: the recorded request (`contract/samples.json`, recorded on the reference file) with this instance's namespace, labels and annotations on a create, and on a patch its labels and annotations replaced when the instance refuses its own (#349). The default create example is permanent. When the example environment accepts expiration at create, Swagger and ReDoc also offer a dated example. Choose a future date before sending it.

**Generated clients.** The committed contract, `cmapi/contract/openapi.json`, is the document of the reference file (`examples/cluster-configs/policies/metadata-keys.yaml`), and the contract gate sees only that file. A client for an instance with its own keys is generated from that instance's own document, for example `curl -fsS https://<instance-route>/openapi.json -o openapi.json` and then the generator (the portal uses openapi-typescript 7.13.0, through `cmapi-portal-ui/scripts/api-types.mjs`). An instance with `docs.enabled: false` serves no document.

### The contract report of a values change

The contract gate sees only the reference file. A site's own change of its keys reaches the API through its Helm values, so the report of that change runs where the values live (#337, the owner's ruling of 2026-11-17). It shows, on the pull request, what the change does to the instance's API document. It never fails the pull request: a change of required keys is the operator's decision (#328, question 4).

**The document offline.** `cmapi-tools openapi render --metadata-keys <file> [--config-dir <dir>] --out <file>` writes the document that an instance with these files serves, through the code that serves it (`main.api_app`), with no database, identity provider, cluster, Git host or Kyverno. With `--config-dir`, the instance's own files; without it, the reference instance packaged with cmapi (`cmapi/src/cmapi/tools/reference_instance/`), whose document is the committed contract. Exit `3` means cmapi's loader refuses the files, so an instance with them would not start; any other non-zero exit is a broken tool. A test holds both renders byte-equal to `cmapi/contract/openapi.json`.

**The report.** `.github/workflows/api-contract-report.yml` is a reusable workflow. For each values file, on the base branch and on the change, it runs `helm template` and takes the `metadata-keys.yaml` of the instance's ConfigMap, so the value `metadata`, the text `configFiles."metadata-keys.yaml"` and the chart's own file all count. Where the two differ, it renders each side's document on the reference instance, so every difference comes from `metadata-keys.yaml`, and runs oasdiff 1.37.0's `changelog` on the pair (`cmapi/contract/report.py`). The changelog goes to the job summary, with one annotation on the values file: a warning when oasdiff finds a breaking change, such as a new required label, a notice otherwise.

| What happens | The job |
|---|---|
| Any change of the API, breaking or not | Passes; the summary lists each change |
| A change that leaves `metadata-keys.yaml` as it was | Passes; no document is compared |
| A values file added or removed | Passes, with a notice |
| `helm template`, `cmapi-tools` or oasdiff fails or is missing, or cmapi refuses either side's file | Fails, with an error annotation that names the step |

In this repository `.github/workflows/values-contract-report.yml` calls it on a pull request that changes `deploy/environments/**`, the chart's `config/metadata-keys.yaml`, `values.yaml` or `templates/config.yaml`. Each side renders with its own chart and the change's own `cmapi-tools`.

A site's values repository calls it the same way, pinned by commit, with `cmapi-ref` set to the commit of the cmapi that its instances run (the image's `org.opencontainers.image.revision`); both sides then render with that cmapi's chart and code:

```yaml
on:
  pull_request:
    paths: [environments/**]
permissions:
  contents: read
jobs:
  api-contract:
    uses: ephico2real2/cmapi/.github/workflows/api-contract-report.yml@<40-hex commit>
    with:
      values-files: environments/*.yaml
      cmapi-ref: <the same commit>
      helm-args: --set cmapi.digest=sha256:<64 a> --set cmapi_portal.digest=sha256:<64 a> --set trustedCA.certificates=x
```

`helm-args` carries what `helm template` requires and only a deploy passes, such as the image digests and the CA bundle; the ConfigMap reads none of them.

- **Never a required check.** A workflow that its `paths` filter skips leaves a required check pending, which blocks the pull request ([workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), `on.<push|pull_request>.paths`). The filter can also miss a change in a pull request of more than 3,000 files.
- **Fork pull requests.** The trigger is `pull_request`: a fork's `GITHUB_TOKEN` is read-only and no secret is passed ([events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)), and the report needs neither. `pull_request_target` is never used: it must not check out untrusted code ([secure use](https://docs.github.com/en/actions/reference/security/secure-use)). A pull request that edits the workflow can make its own report say anything; the report is advice, and review of `.github/` is the control.
- **Why a summary and not a comment.** A job summary needs no write permission and holds 1 MiB of Markdown for each step ([workflow commands](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands)). A comment needs `pull-requests: write`, which a fork's pull request never gets under `pull_request`.
- **oasdiff's own files.** oasdiff reads a `.oasdiff.*` file from its working directory (its `docs/CONFIG-FILES.md`), and a pull request could add one: measured, `fail-on: INFO` there turned a report into exit 1. The report runs oasdiff from an empty directory, with `--allow-external-refs=false` (its `docs/EXTERNAL-REFS.md`), never with `--fail-on` or `--open`.

The `## Info` line "a breaking change was detected but the version is still 0.2.0" is expected: both sides are one cmapi version. Generate a client from the instance's own `/openapi.json` (above), not from the report. The decision record is `docs/reviews/2026-11-17-issue-337/`.

### The example of the owner's company

`examples/cluster-configs/policies/metadata-keys.company.yaml` is the owner's sample namespace `abc-rnd`. `company.net` stands for the company's domain. The test `cmapi/tests/core/test_metadata_stanzas.py` renders the sample from this file. The company's keys on the namespace are these. The namespace also carries the `cmapi.net/` system keys:

- `company.net/mnemonic`: 3 or 4 lowercase letters (`^[a-z]{3,4}$`), the start of the namespace name. `abc` is an example: `abcd-rnd` with the mnemonic `abcd` passes too, and the 3-letter mnemonics stay valid.
- `company.net/lob`: the line of business, free text. `amgsst` is an example, not a list: any value that a label can hold passes (at most 63 characters of letters, digits, `-`, `_` and `.`, starting and ending with a letter or a digit), and the key is required.
- `company.net/cl`: the critical level, `"0"` to `"6"`.

The owner's decision on #358 (2026-11-17). Before it, the file listed `lob` as `[amgsst]`, `cl` as `"0"` to `"3"`, and the mnemonic as 3 letters.

```yaml
kind: Namespace
metadata:
  name: abc-rnd
  labels:
    name: abc-rnd                       # derived from the namespace
    company.net/app-environment: rnd    # derived from the environment of the cluster
    company.net/mnemonic: abc           # required: 3 or 4 letters, the start of the namespace name (abc is an example)
    company.net/lob: amgsst             # required: line of business, free text (amgsst is an example)
    company.net/cl: '1'                 # required: critical level, 0 to 6
  annotations:
    company.net/app-environment: rnd                                # derived
    company.net/mnemonic-group-contact: abc-team@company.net       # optional: an address in emailDomains
    company.net/mnemonic-confluence: https://wiki.company.net/abc  # optional: an http or https URL
```

```yaml
requiredLabels:
  name:                        {value: {from: namespace}, description: "A copy of the namespace name"}
  company.net/app-environment: {value: {from: environment}}
  company.net/mnemonic:        {pattern: "^[a-z]{3,4}$", namespacePrefix: true}
  company.net/lob:             {description: "Line of business, as free text"}
  company.net/cl:              {enum: ["0", "1", "2", "3", "4", "5", "6"]}
requiredAnnotations:
  company.net/app-environment: {value: {from: environment}}
extraLabels:
  keys: {}
  allowOther: {prefixes: ["", "*.company.net/"], max: 50}
extraAnnotations:
  keys:
    company.net/mnemonic-group-contact: {format: email-in-domains}
    company.net/mnemonic-confluence:    {format: url}
  allowOther: {prefixes: ["", "*.company.net/"], max: 50, maxValueBytes: 4096, maxBytesTotal: 65536}
adoptionLabels:
  company.net/provisioner: {recognise: [cluster-configs]}
sensitiveKeys: [company.net/mnemonic, company.net/lob]
emailDomains: [company.net]
```

This is an excerpt. The file also has the `system`, `operatorOnly` and `reservedPrefixes` lists of the reference file, and a `description` and an `example` for most keys.

The owner's decisions behind it:

- `name` is derived from the namespace name. The sample text `aao-rnd` was a typo (#215).
- The two contact keys are annotations, with the formats `email-in-domains` and `url`. A label cannot hold an address or a URL (#234). The design: an existing namespace that carries them as labels keeps those labels when it is adopted. Adoption (story #26) is not built.
- `cmapi.net/env` (the system key that cmapi, the approval rules and Kyverno read) stays beside the company's `company.net/app-environment`. Both come from the environment (#215).
- `company.net/provisioner: cluster-configs` marks a namespace that the earlier process made. A requester cannot set it (#228).

---

## `approval-rules.yaml`

The rules that decide how many approvals a request needs, from which group, and when a policy approves a request by itself. The code is `cmapi/src/cmapi/core/approvals.py` and `cmapi/src/cmapi/core/expression.py`. The chart file is `deploy/helm/cmapi/config/approval-rules.yaml`. The examples are `examples/instances/*/approval-rules.yaml`.

The loader needs rules for each served environment. A rule for an environment that the instance does not serve stops the start. An auto-approval policy that names a tier that is not in `tiers.yaml` stops the start (`core/config.py`).

### The order of the decision

`ApprovalRules.decide` evaluates in this order:

1. The count of the environment for the kind of the action, and its approving group.
2. The first namespace pattern that matches. It can waive the kind or raise the count. An expiry delete skips the patterns.
3. Each threshold whose `when` is true adds approvers.
4. Auto-approval, when the master switch is on and the kill switch is off.

A requirement is a list of slots, one for each approving group. The ledger fills the slots with the approvers, and it re-solves the matching at each approval (`ApprovalLedger`).

### The keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `defaults.required` | integer | `0` | The count when an environment gives none for the kind |
| `defaults.group` | text | `approver-platform` | The approving group when a rule gives none. It is also the group of the platform team for the self-service rate (`docs/17`) |
| `defaults.timeoutHours` | integer | `24` | A request that waits longer than this becomes `timeout` (the worker job `approval_timeout`) |
| `defaults.selfApproval` | boolean | `false` | `true` lets the requester approve the request |
| `environments.<env>.create`, `.change`, `.delete` | integer | `required` of the environment | The approvals for each kind of action. A kind is `create`, `delete`, or any other action as `change` (`action_kind`) |
| `environments.<env>.required`, `.group`, `.timeoutHours`, `.selfApproval` | | The `defaults` | The same keys as `defaults`, for one environment |
| `namespacePatterns[].match` | shell glob | None | A namespace name pattern. The first match wins |
| `namespacePatterns[].required` | integer | None | The count for a matching name. The request needs the larger of this count and the count of the environment, from the group of the pattern |
| `namespacePatterns[].group` | text | The group of the environment | The approving group for the pattern |
| `namespacePatterns[].waive` | list of `create`, `change`, `delete` | `[]` | The kinds that need no approval for a matching name |
| `namespacePatterns[].reason` | text | `""` | Text in the `reasons` of the request |
| `thresholds[].when` | expression | None | A condition on the facts. See "The facts" |
| `thresholds[].add` | integer | `1` | The approvers to add. `add: 0` is a rule that answers and adds no approver |
| `thresholds[].group` | text | `defaults.group` | The group of the added approvers |
| `thresholds[].reason` | text | The `when` text | Text in the `reasons` of the request |
| `protected.labels` | list of `key=value` | `[]` | A namespace whose labels in Git match one of these is protected: a delete request is refused (`namespace-protected`), also the delete after it expires. A request may set such a label only to the listed value, or remove it with `null` (`invalid_value` otherwise). `GET` on a namespace gives `protected` and `protectedBy` from them (#366). List only operator-only keys here, or a requester can protect a namespace |
| `autoApproval.enabled` | boolean | `false` | The master switch for auto-approval |
| `autoApproval.maxPerTeamPerDay` | integer | `20` | The most auto-approvals for one team in a day (UTC). cmapi counts at submit, for a request with a team. `0` stops each auto-approval, also of a request with no team |
| `autoApproval.policies[]` | list | `[]` | The policies. See below |

### The facts

A `when` line reads these facts. The names are fixed in the code. An unknown name stops the start (`KNOWN_FACTS`, `core/expression.py`). A fact that is absent has no value. `==` and `!=` compare it as usual: when `reason` is absent, `reason != "expired"` is true. `<`, `<=`, `>`, `>=`, `in` and `not in` with an absent fact give no answer. A line with no answer is false, also under `not`. So a missing number never adds or waives an approval.

| Fact | Meaning | Set by |
|---|---|---|
| `plugin`, `action`, `environment`, `namespace`, `clusterId`, `reason`, `team`, `tier` | The request | `core/pipeline.py` |
| `tierChange` | `up`, `down`, `same`, `to-custom`, `from-custom` or `custom`. Set for a change of an existing namespace only | `TierCatalog.compare` |
| `quotaIncreasePct` | The largest increase of a sizable key, in percent. Set for a change of an existing namespace only | `QuotaChange.quota_increase_pct` |
| `quotaBelowRequested` | A new quota is below what the pods request now. It is always `false` today: `TierCatalog.compare` takes the usage as an argument, and the planner does not pass it (`core/pipeline.py`, #256) | `QuotaChange.facts` |
| `requestToPeakRatio` | Request against the peak use. A rule that reads it never fires today (#257) | Not set by any built code |
| `capacity`, `capacityFresh` | `fits`, `warn`, `exceeded` or `unknown`, and whether the data is fresh. `unknown`, not fresh, when the cluster has no `simulatedCapacity`, no watch cache, ResourceQuotas not listed yet, ResourceQuota reads refused (401 or 403), or a ResourceQuota watch with no good read for 30 minutes (#393). What is committed comes from the cluster's quota ledger: per namespace the smallest unscoped managed quota, scoped quotas left out (#302) | `core/capacity_backend.py`, `core/capacity_ledger.py` |
| `namespaceAgeDays`, `pods`, `pvcs`, `protected` | The namespace for a delete | `Pipeline.plan_delete` |
| `keyClasses`, `sensitiveKeyChanged` | The classes of the changed keys, and a change of a `sensitiveKeys` key | `MetadataKeys.change_facts` |
| `expirationAction`, `expirationBeyondLimits` | The expiry change, and whether it is past `maxLifetimeDays` or is `:makePermanent` | `plugins/expiration/rules.py` |
| `beyondTier` | A custom-tier value differs from the tier | `Pipeline.plan_namespace` |
| `beyondTierKeys` | The keys that differ | `Pipeline.plan_namespace` |
| `networkExposure` | The request raises `services.loadbalancers` or `services.nodeports` | `Pipeline.plan_namespace` |
| `warnings`, `requesterClient`, `automated` | The findings of the validator, the client of a service caller, and whether the caller is automated | `core/pipeline.py` |
| `clusterRoles` | The cluster roles of a grant | Not set by any built code (#257). `match.clusterRoles` reads it |

`clusterLabels` is not a fact for a `when` line: a line that names it stops the start. Only `match.clusterSelector` of an auto-approval policy reads the labels of the cluster.

### Approval is the gate for a value beyond the tier

A request with `beyondTier` always gets an answer from a rule (`ApprovalRules._added`):

- A threshold that reads `beyondTier`, `beyondTierKeys` or `networkExposure` and is true adds its approvers. The reference files add one approver of `approver-platform` for `beyondTier`, and one more for `networkExposure`.
- When no true threshold reads one of those facts, cmapi adds one approver of `defaults.group` with the reason "Value beyond the tier". An instance that removes the rule does not open the gate by accident.
- A rule that means no extra approver says `add: 0`.
- An auto-approval policy covers a beyond-tier request only when two things are true. The policy has `match.beyondTier: true`, or the guard `beyond-tier` stops it. And no rule adds an approver for the request, or the guard `rules-added-approvers` stops it (`ApprovalRules._auto`). So the instance also needs a true threshold that reads `beyondTier` with `add: 0`. The reference files add one approver for `beyondTier`, so with them no policy covers a beyond-tier request (`test_auto_approval_covers_a_value_beyond_the_tier_only_when_the_policy_says_so`, `cmapi/tests/core/test_approvals.py`).

The plan, the dry run and the request show each key with the tier's value and the requested value, and the approvals that the keys add (`beyondTier` in the view).

### Auto-approval policies

Each item of `autoApproval.policies` has:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | text | None | The name. The approver of a request is `auto:<name>` |
| `enabled` | boolean | `true` | `false` turns the policy off |
| `match.plugin` | text | Any | The plugin of the request |
| `match.actions`, `match.environments`, `match.tiers` | list of text | Any | The values that match. `"*"` matches any |
| `match.reason` | text | Any | The `reason` of the request. `expired` is for the expiry delete |
| `match.keyClasses` | list of text | Any | The classes that the changed keys can have. All the classes of the request must be in this list |
| `match.clusterRoles` | list of text | Any | The roles that a service-account grant can have. No built code sets the fact `clusterRoles` (#257), and a request with no roles passes each list, so today this match excludes no request |
| `match.clusterSelector.matchLabels` | mapping | Any | Labels that the cluster must have |
| `match.beyondTier` | `true` | Not set | Lets the policy cover a request with a value beyond the tier |
| `requester.clients` | list of text | Any | The clients that can use the policy |
| `guards` | list | `[]` | Extra guards: `noOpenRequest`, `notProtected`, `noExtensionInLast24h`, `noticesSentAtLeast2`. An unknown guard stops the start. Three of them read facts that the daily `expire_check` sets on the delete it opens (#263): `openRequestOnNamespace`, `lastExtensionHoursAgo` (whole hours since the last `:extend` or `:set` was asked, whatever became of it) and `noticesSent`. On a delete that a person asks for they are absent, so `noOpenRequest` and `noExtensionInLast24h` pass and `noticesSentAtLeast2` stops the policy. `notProtected` reads the fact `protected` of a delete |

The first enabled policy that matches the request decides. When a guard stops that policy, cmapi does not try the next policy (`ApprovalRules._auto`). A policy approves only when no fixed guard and none of its own guards stops it. The fixed guards are in `FIXED_GUARDS` and `ApprovalRules._auto`, in this order:

| Guard | Stops the policy when |
|---|---|
| `paused` | The kill switch is on (`POST /api/v1/admin/auto-approval:pause`) |
| `delete` | The action is a delete, unless the policy is the expiry policy |
| `beyond-tier` | The request has a value beyond the tier, and the policy lacks `match.beyondTier: true` |
| `rules-added-approvers` | A namespace pattern or a threshold added an approver |
| `capacity` | A create or a change of a namespace or quota lacks the capacity answer `fits` on fresh data |
| `warnings` | The plan has a finding with warning severity (for example a Kyverno finding in `audit` mode) |
| `team-allowance` | The team reached `maxPerTeamPerDay` |

The guard that stopped a policy is stored in `change_requests.requirement` as `autoFallback`, and counted in `cmapi_auto_approval_fallbacks_total{guard}`.

---

## `expiration.yaml`

The file is needed. The code is `cmapi/src/cmapi/plugins/expiration/rules.py`. An environment with no entry, or with `enabled: false`, refuses each expiry field with 422 `expiration-not-allowed`, except `:makePermanent` of a namespace that has a date. `prod` can have an entry only with `enabled: false` (the owner's #222 decision: production never expires); `prod` with `enabled: true` stops the start, and the renderer refuses an expiry in `prod` too. The worker's daily job `expire_check` (`jobs/expire_check.py`, #263) reads the other keys: it sends the notices, records the grace and opens the delete after it. It acts only on a cluster that takes writes, in an environment that this instance serves and whose expiration is on, so never in `prod`. Every day is a UTC day (#321): the date in `cmapi.net/expires-at` is compared with today's UTC date, and a namespace's creation day is the UTC date of its `creationTimestamp`. The job runs when the worker starts and then every 24 hours; after a run that could not finish (a cluster whose namespaces were not listed in the last relist window, a failed email, Git or the cluster unreachable for a delete), the next run comes in 15 minutes. The constants are `EXPIRE_CHECK_EVERY` and `EXPIRE_CHECK_RETRY`, not configuration. A run that sends nothing new is harmless: each notice, grace and delete is recorded in `expiration_notices`, and a second run reads it first.

What a notice is: when `integrations.yaml` sets `notifier.smtp.host`, an email to the namespace's team DL (`cmapi.net/team-dl`). Without it, no message leaves cmapi: the notice is recorded with the detail `portal: the Expiration tab`, and `GET /api/v1/expirations` counts it in `noticesSent`, as approval prompts are recorded for the portal when there is no SMTP. A failed email is recorded as not sent, is not counted, and goes again on the next run.

What the delete is: the normal delete request, planned from Git (`Pipeline.plan_expiry_delete`) with the reason `expired` and the requester `cmapi-expire-check`, a service identity that no person holds. The approval rules decide it: the `expired-namespace` auto-approval policy when its guards pass, or else the environment's `delete` rule with its approvers (the namespace patterns and the delete threshold do not apply to it). A bot PR removes the folder, and Argo CD waits for an operator's prune confirmation (`awaiting_prune`). A guard of the check that fails (an open request, a protected namespace, an extension asked today, fewer than `minNoticesBeforeDelete` notices), a refusal of the plan, or a date in Git that is not the cluster's holds the delete: the log line `expiry_delete_held` names the guard, and the next run tries again. The counter `cmapi_expiry_actions_total{action, environment}` counts each `notice`, `notice_failed`, `grace`, `delete_opened`, `delete_held` and `error`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `defaults.enabled` | boolean | `true` | The environment takes expiry dates. `false` is the same as no entry: each expiry field is refused (`expiration-not-allowed`), and a new namespace there carries neither `cmapi.net/expires-at` nor `cmapi.net/expiry`. A namespace that got a date while it was `true` keeps the date unchanged on every other change, and `:makePermanent` still removes it; `:extend` and `:set` are refused. Set it per environment to turn expiry off in one (#479) |
| `defaults.allowedAtCreate` | boolean | `true` | A new namespace can have an expiry date |
| `defaults.maxExtensionDays` | integer | `30` | One extension adds at most this many days |
| `defaults.maxLifetimeDays` | integer | `180` | A date past this many days from creation sets the fact `expirationBeyondLimits`. `:makePermanent` sets it too. The reference `approval-rules.yaml` adds one approver of `approver-platform` for the fact |
| `defaults.notifyDaysBefore` | list of integers | `[14, 7, 1]` | The days before the date for a notice, each sent once. A run sends the nearest threshold not yet sent, so a short expiry still gets its 1-day notice and a missed run never sends a stale one |
| `defaults.graceDays` | integer | `7` | The namespace still runs and can be extended for this many days from the date: the date and the 6 days after it. `expire_check` records the grace once and opens the delete on the day after |
| `defaults.deleteAfterGrace` | boolean | `true` | `expire_check` opens a delete request after the grace. `false`: it sends the notices and records the grace, and opens nothing |
| `defaults.minNoticesBeforeDelete` | integer | `2` | The notices that must have gone before `expire_check` opens the delete |
| `environments.<env>` | mapping | `{}` | The same keys as `defaults`, for one environment. An empty mapping means "the defaults" |

When `expiresAt` is set, the namespace carries the annotation `cmapi.net/expires-at` (the ISO date) and the label `cmapi.net/expiry: managed` (`core/render/manifests.py`, `ManifestRenderer.render`). The API document says each served environment's rules on `NamespaceCreate.expiresAt` (#479, A11): `x-cmapi-expiration: {"environments": {"<env>": {"enabled": true, "allowedAtCreate": ..., "maxLifetimeDays": ..., "notifyDaysBefore": [...], "graceDays": ...}}}`, and `{"enabled": false}` alone for an environment that takes no expiry, so the portal shows the field off there. Its description says the same in words.

---

## `authz-roles.yaml`

Which Keycloak role grants which permission, for the instance. The full table of roles, permissions and routes is in `docs/14`. The code is `cmapi/src/cmapi/core/authz.py` (`RolePolicy`).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `roles.<role>.permissions` | list of text | For a built-in role with no `permissions` and no `inherits`: its built-in permissions. Otherwise none | Replaces the permissions of the role |
| `roles.<role>.inherits` | list of roles | `[]` | Adds the permissions of the named roles. A built-in role with `inherits` and no `permissions` loses its own built-in permissions: name them in `permissions`. A role does not take the `environments` of a role that it inherits |
| `roles.<role>.environments` | list of text | Each served environment | Limits the role to some environments |

A role that the file does not name keeps its built-in permissions. A permission that no built-in role has, an environment that the instance does not serve, and a role that inherits itself each stop the start.

---

## `plugins.yaml`

Optional. The code is `cmapi/src/cmapi/core/plugins.py`. The chart does not mount this file today (`deploy/helm/cmapi/templates/config.yaml` lists the files that it mounts), so a Helm instance enables each built-in plugin.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | list of plugin names | Each built-in plugin, which is each key of `BUILT_IN` in `core/plugins.py:28-36`: `namespaces`, `tiers`, `directory`, `quotas`, `expiration`, `policies` and `capacity`. With no file, `core/plugins.py:49` enables all of them | The plugins whose routes the API mounts. A plugin that is not listed has no route and no line in the API document |
| `overrides.<instance>.<env>.disabled` | list of plugin names | None | Stops the writes of an enabled plugin in one environment of one instance. The reads stay. The write answers 422 `plugin-disabled` |

The loader checks only the block of its own instance. Each of these mistakes stops the start:

- A name that is not a built-in plugin, or a name of a core router.
- An environment that the instance does not serve.
- An unknown key.
- An override that changes nothing: the plugin is not enabled, or it has no write.

Only `namespaces` has a write today (`WRITERS`). `GET /api/v1/admin/plugins` shows the state.

---

## `integrations.yaml`

Optional. The code that reads it is `cmapi/src/cmapi/core/sync.py` (`DeliveryConfig.from_integrations`), `cmapi/src/cmapi/core/channels.py` and `cmapi/src/cmapi/routers/admin.py`. The chart writes it from the values `delivery.*`, `argocd.*` and `notifier.*` (`deploy/helm/cmapi/templates/config.yaml`).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `delivery.mode` | `argocd` or `apply` | `argocd` | `argocd`: Argo CD on each cluster applies the folder, and cmapi only reads. `apply`: the worker applies the approved folder itself, with server-side apply. `apply` is a deviation that a site must accept (`core/sync.py`) |
| `delivery.syncTimeout` | duration | `30m` | The wait for a merged request to be `Synced` before it becomes `sync_failed` |
| `delivery.argocd.namespace` | text | `openshift-gitops` | The namespace of the Argo CD root Application |
| `delivery.argocd.rootApplication` | text | `cluster-configs-{clusterId}` | The name of the root Application. `{clusterId}` becomes the cluster ID in lower case with `_` as `-` |
| `syncSignal.pollInterval` | duration | `30s` | How often the worker reads the Application |
| `syncSignal.default`, `syncSignal.reconcileInterval` | text | None. With no `syncSignal` key the route reports `{default: poll}` | Reported by `GET /api/v1/admin/integrations`. No other code reads them. The value `notify` is not built |
| `operations.*` | mapping | `engine: builtin` | Reported by `GET /api/v1/admin/integrations`. No built code runs an operation engine |
| `events.*` | mapping | `publisher: none` | Reported by the same route. No built code publishes events |
| `notifier.smtp.host` | text | None | The SMTP host. Without it, only the portal channel is active, and expiry notices are recorded for the Expiration tab without an email |
| `notifier.smtp.port` | integer | `25` | The SMTP port |
| `notifier.smtp.from` | text | `cmapi@ephico2real.com` | The sender address |
| `notifier.smtp.starttls` | boolean | `false` | Use STARTTLS |
| `notifier.smtp.domain` | text | `ephico2real.com` | The domain of the group address `cmapi-<group>@<domain>` when `groupMail` has no entry |
| `notifier.groupMail` | mapping of group to address | `{}` | The address for each approving group |

A duration is a number with `s`, `m` or `h`, or a whole number of seconds (`_seconds`, `core/sync.py`). The SMTP user and password come from the environment (`CMAPI_SMTP_USER`, `CMAPI_SMTP_PASSWORD`), never from the file. The email carries a signed link that opens the request in the portal. The email never approves (`core/channels.py`).

---

## `clusters.yaml` and `capacity.yaml`

`clusters.yaml` has one key, `clusters`: a list of entries, or a mapping of cluster ID to entry (`load_policies`, `core/registry.py`). A file with the list or the mapping at the top level does not work: a mapping gives no cluster, and a list stops the start with an `AttributeError`. Each cluster has:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `clusterId` | text | None | The ID, in the list form |
| `environment` | text | None. Needed | An environment that the instance serves. Another value stops the start (`load_policies`), before imports are checked. The import Secret does not supply an environment |
| `gitopsPath` | text | `clusters/<clusterId>` | Shown in `GET /api/v1/clusters`. No built code uses it for the folder: the folder is always `clusters/<clusterId>/namespaces/<namespace>/` (`folder`, `core/render/manifests.py`) |
| `writes` | boolean | `true` | `false` makes the cluster read only |
| `syncSignal` | text | `poll` | No built code reads it. `notify` is not built |
| `delivery` | `argocd` or `apply` | The `delivery.mode` of `integrations.yaml` | The delivery mode of this cluster (`jobs/watch_sync.py`) |
| `thanosUrl` | text | None | No built code reads it |
| `labels` | mapping | `{}` | Labels that `match.clusterSelector` reads. `GET /api/v1/clusters` shows them |
| `metadata`, `placement` | mapping | `{}` | No built code reads them |
| `simulatedCapacity` | mapping with `cpu` and `memory` | None | The size of the cluster for the built-in capacity check, which counts the hard `requests.cpu` and `requests.memory` (or `cpu` and `memory`, the same resources; the smaller when a quota has both) of the ResourceQuotas labelled `cmapi.net/managed: "true"`: in each namespace the smallest unscoped one, never their sum, and no scoped quota (`scopes` or `scopeSelector`), since a scoped quota bounds only the pods of its scope (#302, docs/16). Without it, or while those quotas are not known (#393), the capacity answer is `unknown`, so the guard `capacity` stops each auto-approval of a create or a change. The Capacity tab measures against it when it is set, labelled "simulated", with the nodes' allocatable beside it; without it, against the allocatable (the owner, 2026-11-18). Both `cpu` and `memory` are needed, each a Kubernetes quantity above 0; another value stops the start (`load_policies`) |

`capacity.yaml` keys that built code reads (`core/capacity.py` `CapacitySettings`, `core/kpi.py`). A value of the wrong type, an `overcommit` of 0, and a top-level or per-environment entry that is not a mapping stop the start, naming each one:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `overcommit.<env>.cpu`, `.memory` | number above 0 | 1.0 | What the managed quotas may commit, as a multiple of the cluster's size. The plan's check and `GET /api/v1/capacity` use the same value; the API says `overcommitDefault: true` for an environment the file does not set |
| `targets.<env>.commitment.warn` | number | `0.85` | The commitment at which the plan's capacity answer is `warn`, and a cluster or group of the Capacity tab is `warn` |
| `targets.<env>.commitment.critical` | number | `0.95` | The commitment at which a cluster of the Capacity tab is `critical`. Above 1 it is `over` (#302) |
| `countTaints` | list of taint keys | `[]` | The taint keys whose `NoSchedule` and `NoExecute` nodes still count toward allocatable (`core/clients/nodes.py`, #302). By default a node counts when it is Ready, not cordoned, and has no such taint, so control-plane nodes with `node-role.kubernetes.io/master:NoSchedule` do not count. A single-node cluster such as CRC has no taint and counts |
| `kpi.thresholds` | mapping | `memoryPercent: 80`, `cpuPercent: 80`, `throttledPercent: 1`, `dbConnectionsPercent: 80`, `dbVolumePercent: 80`, `backupMaxAgeHours: 26` | Reported by `GET /api/v1/admin/kpi` as `thresholds` (`kpi_report`, `core/kpi.py`). A non-empty mapping replaces the whole default; an empty one gives the default. Unlike the keys above, it is not checked at start (`CapacitySettings` does not read `kpi`): a value that is not a mapping of numbers starts, and `GET /api/v1/admin/kpi` then fails (`KpiView.thresholds` is `dict[str, float]`). The chart writes no `kpi` key into `capacity.yaml` |

The chart and the plain manifests also write `mode`, `snapshotInterval` and `targets.<env>.utilisation`. No built code reads them. The other keys of the reference file are designed for the capacity service, which is not built. The Capacity tab reads each connected cluster's nodes through cmapi-reader, which needs `get`, `list` and `watch` on `nodes` (`deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml`); without it the cluster's nodes are `forbidden` and the tab shows the commitment against `simulatedCapacity` only. The API process watches the nodes; the worker does not.

---

## Environment variables

`cmapi/src/cmapi/settings.py` holds most variables: the name is `CMAPI_` and the field name in upper case. Some modules read a variable directly, and the table names the module for each of those. The variables of the chart Jobs (realm sync, Git bootstrap) are in `cmapi/src/cmapi/tools/`. The chart sets them (`deploy/helm/cmapi/templates/_helpers.tpl`, `api.yaml`, `worker.yaml`). A value that is a secret comes from a Kubernetes Secret.

| Variable | Default | Meaning |
|---|---|---|
| `CMAPI_CONFIG_DIR` | `/etc/cmapi/config` | The folder of the files above |
| `CMAPI_METADATA_KEYS` | `<config dir>/metadata-keys.yaml` | Another path for `metadata-keys.yaml` |
| `CMAPI_POLICIES_DIR` | `/etc/cmapi/policies` | Hand-written Kyverno policies that run with the rendered ones |
| `CMAPI_CA_BUNDLE` | None | A PEM bundle that cmapi trusts for Keycloak, and for Git unless `CMAPI_GIT_CA_BUNDLE` is set. Not a cluster's trust since #434 (the owner's decision D4): see `CMAPI_TRUSTED_CA_FILE` |
| `CMAPI_TRUSTED_CA_FILE` | `""` | Colon-separated PEM bundles that a cluster with no caData is verified against, after the image's system store (see "Cluster trust"). A path that is not there is skipped and read again at the next check; a file that does not load, or a path that cannot be read for another reason (a directory the process cannot enter), makes that cluster `cert-verify-failed`, with a finding that names the file and ends `; trust store: trusted (the system store and CMAPI_TRUSTED_CA_FILE)`, and the other clusters are still checked (`core/clients/trust.py`, #434) |
| `CMAPI_DATABASE_URL` | `""` | `postgresql://user:password@host:5432/db`. A secret |
| `CMAPI_DATABASE_POOL_SIZE` | `5` | The pool of connections of one process |
| `CMAPI_OIDC_JWKS_URL` | `<issuer>/protocol/openid-connect/certs` | Where to read the signing keys |
| `CMAPI_OIDC_LEEWAY_SECONDS` | `30` | The clock leeway for `exp` and `iat` |
| `CMAPI_KEYCLOAK_ADMIN_URL` | The issuer, up to its last `/realms/` | The base of the Keycloak admin API |
| `CMAPI_DIRECTORY_CLIENT_SECRET` | `""` | The secret of the `cmapi-directory` client. A secret |
| `CMAPI_GIT_PROVIDER` | `gitea` | `gitea` or `github` |
| `CMAPI_GIT_URL` | `""` | The API URL of the Git host |
| `CMAPI_GIT_TOKEN` | `""` | The bot account's API token, from Secret `cmapi-git-bot`, for the host's API. A secret. No git process gets it from the environment. It appears in no error, request event, log line or API answer: a host that echoes it gets `***` in its place, before the text is cut (`HostGitProvider.host_text`, #424) |
| `CMAPI_GIT_USER`, `CMAPI_GIT_PASSWORD` | `""` | Basic authentication instead of a token. A secret, redacted as the token is, and so is the header's base64 of user:password (#424) |
| `CMAPI_GIT_DEFAULT_BRANCH` | `main` | The branch that the bot's PRs merge into. Nothing is ever pushed to it |
| `CMAPI_GIT_CREDENTIALS_DIR` | `/etc/cmapi/git-bot` | Secret `cmapi-git-bot` as files: `token`. Git over HTTPS reads it through a credential helper (#286) |
| `CMAPI_GIT_SSH_DIR` | `/etc/cmapi/git-bot-ssh` | Secret `cmapi-git-bot-ssh` (`kubernetes.io/ssh-auth`): `ssh-privatekey`, an ed25519 key with no passphrase, and optionally `ssh-publickey`. Worker only |
| `CMAPI_GIT_KNOWN_HOSTS_DIR` | `/etc/cmapi/git-bot-known-hosts` | ConfigMap `cmapi-git-bot-known-hosts`: `known_hosts`, every key type the host publishes. Worker only |
| `CMAPI_GIT_WORKDIR` | A temporary folder | The worker's Git workdir: the mirror `repo.git` and one worktree per request. The plain manifests mount an emptyDir with `sizeLimit: 1Gi` |
| `CMAPI_GIT_WORKDIR_LIMIT_BYTES` | `1073741824` | The emptyDir's `sizeLimit`: above 80 % the sweeper removes the workdir, to be fetched again |
| `CMAPI_GIT_CA_BUNDLE` | None: the trust of `CMAPI_CA_BUNDLE` | The PEM bundle the Git provider alone trusts, as an explicit TLS context that `SSL_CERT_FILE` cannot change. A file that is not there stops the process at start. CRC sets the image's system bundle, `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`, since its `CMAPI_CA_BUNDLE` holds Keycloak's private CA alone (#97) |
| `CMAPI_CURSOR_KEY` | `""` | The key that signs list cursors. Empty: cmapi signs with the fixed text `unset-cursor-key` (`core/context.py`), the same on each instance. A secret |
| `CMAPI_LINK_KEY` | `""` | The key that signs the links of the email channel. Empty: cmapi signs with the fixed text `unset-link-key` (`core/channels.py`). A secret |
| `CMAPI_IMPORTS_NAMESPACE` | `cmapi-imports` | The hub namespace that holds the cluster import Secrets. A Secret that cannot be checked is a finding on its own cluster in `GET /api/v1/clusters`; it never stops the start or the 5-minute relist of the others (`ClusterRegistry.refresh`, #419) |
| `CMAPI_IMPORTS_DIR` | None | Reads import Secrets from YAML files in this folder, for tests |
| `CMAPI_KUBE_TOKEN_FILE`, `CMAPI_KUBE_CA_FILE`, `CMAPI_KUBE_API_URL` | The service account files, and `https://kubernetes.default.svc` | How cmapi reads the import Secrets of the hub. Neither this token nor the token of an import Secret appears in an error, a cluster finding or a log line: each is replaced with `***` before the text is cut (`core/clients/redact.py`, #420) |
| `CMAPI_COMPONENT` | `api` | `api`, `worker` or `capacity`. The label `component` of the metrics |
| `CMAPI_LOG_LEVEL` | `INFO` | The log level of the api and the worker. `cmapi-migrate` does not read it: it logs at `INFO`, so its result event is always written (docs/12, section 4) |
| `CMAPI_BIND_PORT`, `CMAPI_METRICS_PORT` | `8080`, `9090` | The ports of the API and of the metrics |
| `CMAPI_WORKER_POLL_SECONDS` | `2.0` | How often the worker looks for a due job |
| `CMAPI_WORKER_ID` | The host name | The name of the worker in a lease |
| `CMAPI_KYVERNO_VERSION` | None | When set and a served environment runs Kyverno, the `kyverno` binary must be exactly this version (the whole `Version:` line of `kyverno version`, #395, #412), or cmapi does not start (`core/validate/__init__.py`). `GET /api/v1/admin/integrations` reports it as `policy.kyvernoVersion` (`core/policy.py`, `view`). The image sets it from `KYVERNO_VERSION` in `cmapi/Containerfile` (#390) |
| `CMAPI_KUBECONFORM_SCHEMAS` | None | The `-schema-location` of kubeconform (`core/context.py`) |
| `CMAPI_KUBERNETES_VERSION` | None | The `-kubernetes-version` of kubeconform (`core/context.py`) |
| `CMAPI_SMTP_USER`, `CMAPI_SMTP_PASSWORD` | None | The SMTP login of the email channel. cmapi logs in only when both are set (`core/channels.py`). The chart does not set them. A secret |
| `CMAPI_STATIC_DIR` | `/opt/app-root/static` | The folder of the Swagger UI and ReDoc files of `/docs` and `/redoc` (`main.py`). The image sets it |
| `CMAPI_GIT_COMMIT` | `unknown` | The commit of the build, in `GET /api/v1/version` and in the build metric (`routers/health.py`, `main.py`). The image sets it |
| `CMAPI_MIGRATE_WAIT_SECONDS` | `540` | How long `cmapi-migrate` waits for the database (`core/db/migrate.py`) |
| `CMAPI_MIGRATE_LOCK_TIMEOUT` | `30s` | The PostgreSQL `lock_timeout` of a migration (`core/db/migrations/env.py`) |

---

## Helm values

`deploy/helm/cmapi/values.yaml` holds each default, with comments. The values of this table are those of the main branch at the time of writing. The pull requests of the front door (#238 and #247) add values to `values.yaml`. This part does not list them.

| Value | Type | Default | Meaning |
|---|---|---|---|
| `cmapi.repository`, `cmapi.tag`, `cmapi.digest` | text | The OpenShift registry, `""`, `""` | The image of the API and the worker. The chart refuses to render without a digest |
| `cmapi_portal.repository`, `.tag`, `.digest` | text | | The same for the portal |
| `instance.*` | | | The keys of `instance.yaml` above. `instance.reservedPatterns` is `instance.namespaces.reservedPatterns` in the file |
| `instance.policy` | mapping | `{}` | `engine`, `mode` and `environments` (see "The policy engine") |
| `instance.clusterTLS` | mapping | `{}` | `environments.<env>.insecureSkipTLSVerify` (see "Cluster trust") |
| `auth.issuer`, `auth.audience`, `auth.acceptLegacyTokenType` | | | `instance.auth.*` |
| `auth.jwksUrl`, `auth.adminUrl` | text | `""` | `CMAPI_OIDC_JWKS_URL` and `CMAPI_KEYCLOAK_ADMIN_URL`, for an internal Service address |
| `auth.directorySecret` | text | `cmapi-keycloak` | The Secret with the key `directoryClientSecret` |
| `keycloak.realmImport.*`, `keycloak.realm.*`, `keycloak.sync.*` | | `enabled: false` | The realm as code on CRC, and the sync Job. A site with its own realm keeps them off. The chart refuses a wildcard, a fragment, or http (except localhost) in a redirect URI |
| `git.provider` | `gitea`, `github` | `gitea` | `CMAPI_GIT_PROVIDER` |
| `git.apiUrl`, `git.webUrl` | text | The Gitea Service | `CMAPI_GIT_URL`, `instance.git.webUrl` |
| `git.repository` | text | `cmapi/cluster-configs-nonprod` | `instance.git.repository` |
| `git.defaultBranch` | text | `main` | `CMAPI_GIT_DEFAULT_BRANCH` |
| `git.credentialSecret` | text | `cmapi-git-bot` | The Secret with `token`, or `username` and `password`. The chart does not mount the Git layer's files yet; the plain manifests do (#286) |
| `git.bootstrap.enabled`, `.clusterIds` | | `false`, `[CRC]` | On CRC and kind: creates the organisation, the repository, its seed and the branch protection |
| `clusters` | mapping | One entry, `CRC` | `clusters.yaml` |
| `imports.namespace`, `imports.createNamespace` | | `cmapi-imports`, `true` | `CMAPI_IMPORTS_NAMESPACE`, and whether the chart creates it |
| `delivery.mode`, `.syncTimeout`, `.pollInterval` | | `argocd`, `30m`, `30s` | `integrations.yaml` `delivery` and `syncSignal` |
| `delivery.hubDeliverer.enabled`, `.acknowledgeDirectWrites` | boolean | `false`, `false` | `delivery.mode: apply` makes the worker a cluster-wide writer. The chart refuses `apply` unless `acknowledgeDirectWrites` is `true`. `enabled` gives the worker the writer ClusterRole (`templates/rbac.yaml`) |
| `argocd.namespace`, `argocd.rootApplication` | text | `openshift-gitops`, `cluster-configs-{clusterId}` | `integrations.yaml` `delivery.argocd` |
| `argocd.controllerServiceAccount` | text | `""` | Needed in `argocd` mode: `system:serviceaccount:<namespace>:<name>` of the Argo CD controller. The chart refuses an empty value unless `argocd.acknowledgeUncontainedController` is `true` |
| `capacity.mode`, `.snapshotInterval`, `.overcommit`, `.targets`, `.countTaints` | | `embedded`, `30m`, the `rnd` and `dev` entries of `values.yaml`, `[]` | `capacity.yaml`. No built code reads `mode` and `snapshotInterval`. The chart writes `countTaints` only when it is not empty |
| `notifier.smtp` | mapping | `{}` | `integrations.yaml` `notifier.smtp`. Empty: the email channel is off |
| `database.cnpg.enabled`, `.name`, `.instances`, `.storage`, `.storageClass`, `.imageName`, `.resources`, `.parameters` | | CloudNativePG with 1 instance and 2Gi | The PostgreSQL cluster. See `docs/12` |
| `database.existingSecret` | text | `""` | With CNPG off: a Secret with the key `uri`. Needed then |
| `api.*`, `worker.*`, `portal.*`, `migrate.*` | | | `replicas`, `resources` and `logLevel` of each workload, and the `migrate` init container |
| `exposure` | `Route` or `Ingress` | `Route` | `Route` for OpenShift, `Ingress` for plain Kubernetes. `Ingress` needs `ingress.<site>.host` |
| `route.*`, `ingress.*` | | Empty hosts | The hosts and the TLS of each site: `api`, `portal`, `mockup` |
| `trustedCA.certificates` | text | `""` | A PEM bundle for Keycloak, Git and the database: ConfigMap `<release>-trust`, named by `CMAPI_CA_BUNDLE`, `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` and `PGSSLROOTCERT`. Not a cluster's trust (#434) |
| `trustedCA.injected.enabled` | boolean | `false` | An empty ConfigMap `<release>-trusted-ca` that OpenShift fills, mounted optional and named first in `CMAPI_TRUSTED_CA_FILE` (see "Cluster trust"). With `certificates` empty, the pods also trust it for Keycloak, Git and the database, as `injected.enabled` did before #434, when it labelled `<release>-trust` itself |
| `trustedCA.existingConfigMap.enabled`, `.name`, `.key` | | `false`, `""`, `ca-bundle.crt` | A ConfigMap that you make, mounted and named second in `CMAPI_TRUSTED_CA_FILE`. Never templated from values. `enabled` with no `name` fails the render |
| `monitoring.serviceMonitor`, `.prometheusRule`, `.perses` | | `enabled: false` | The scrape, the alerts and the dashboards |
| `networkPolicy.enabled`, `.monitoringNamespace` | | `true`, `openshift-user-workload-monitoring` | The network policies |
| `securityContext`, `containerSecurityContext`, `podDisruptionBudget` | | Restricted | Non-root, no capabilities, the runtime default seccomp profile |
| `metadata` | mapping | `{}` | `metadata-keys.yaml` as structured values: the whole file, each stanza written out but `liveOnlyKeys`, which may be left out. Checked by `values.schema.json`. Empty: the chart's file, or `configFiles."metadata-keys.yaml"`. Setting both fails (see "Setting the keys through the Helm values") |
| `configFiles.<name>` | text | `{}` | The full text of `approval-rules.yaml`, `authz-roles.yaml`, `tiers.yaml`, `expiration.yaml` or `metadata-keys.yaml`, to use in place of the file of the chart. Another name is refused |

A site sets its own values in `deploy/environments/<site>.yaml`, and passes the file with `-f`. The chart refuses an image with no digest, so deploy from `deploy/images.lock.yaml`.

---

## Where each decision is recorded

| Decision | Record |
|---|---|
| Kyverno optional, with a mode for each environment | `docs/reviews/2026-11-14-issue-213/README.md` |
| The policies rendered from the configuration | `docs/reviews/2026-11-14-issue-212/README.md` |
| The metadata stanzas, and the company example | `docs/reviews/2026-11-14-issue-215/README.md` |
| The metadata keys as Helm values, with `values.schema.json` | This file, "Setting the keys through the Helm values" (#335) |
| Custom limits, values beyond the tier, approval as the gate | `docs/reviews/2026-11-14-issue-211/README.md` |
| The names of instances and environments, and `prod` | `docs/02`, "The names of instances and environments" (#232) |
| The links of the email channel name the instance | `docs/reviews/2026-11-14-issue-222/README.md` |
| Git delivery: a Git layer and a thin PR adapter, apply before merge | `docs/reviews/2026-11-15-issue-286/README.md` |
| The validator matches a pattern with RE2, in linear time | `docs/reviews/2026-11-17-issue-348/README.md` |
| Capacity from the watch: the ledger in memory (no table), the node cache, `countTaints`, `simulatedCapacity` (#302) | `docs/reviews/2026-11-18-issue-302-capacity/` |
| Kyverno in audit by default; cmapi's own checks refuse (#342) | `docs/reviews/2026-11-17-issue-342/` |

## The bot account on each host

The identity is one machine user account, `cmapi-git-bot`, on each host (the owner's decision of 2026-11-15, #286): its SSH key for Git, its token for the PR. A deploy key is the alternative where the host allows writes with one. Read on 2026-11-15; a row marked *not verified* is not yet checked at its host's documentation.

| Host | Bot account: SSH | Bot account: API | Alternative | Source |
|---|---|---|---|---|
| GitHub | the machine user's SSH key | its fine-grained token: Contents and Pull requests read and write | a deploy key with write access, for SSH | [GitHub, deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) |
| GitLab | the service account's SSH key | its token | a read-write deploy key made by the service account; a project access token for the API | [GitLab, deploy keys](https://docs.gitlab.com/user/project/deploy_keys/) |
| Bitbucket Cloud | the bot account's own SSH key | its API token, or a repository access token | none for writes: repository and project access keys are read-only | [Atlassian, access keys](https://support.atlassian.com/bitbucket-cloud/kb/difference-between-repository-project-and-workspace-access-keys/) |
| Bitbucket Data Center | the bot user's SSH key | its HTTP access token | an access key with write access | *not verified* |
| Gitea | the bot user's SSH key | its token | a deploy key with write access | *not verified* |
