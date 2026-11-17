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

One environment name has a meaning in code: `prod`. A namespace in `prod` never expires. `expiration.yaml` cannot have an entry for `prod` (`plugins/expiration/rules.py`), and the rendered policies add `deny-expiry-in-prod` for `prod` only (`core/policygen.py`, `_env_files`).

---

## `instance.yaml`

The file has one key, `instance`. The chart writes it from the values `instance.*`, `auth.*` and `git.*` (`deploy/helm/cmapi/templates/config.yaml`). Examples: `examples/instances/*/instance.yaml`.

How to make the bot account, its token and its SSH key, and how to switch `instance.git.url` to SSH: [`docs/19`](19-setup-connections-to-git.md).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `instance.name` | text | None. Needed | The name of the instance. It is in each log line, in each metric, in each request, and in the links of the email channel (`core/channels.py`) |
| `instance.displayName` | text | None | A name for people. The chart writes it. No Python code reads it |
| `instance.allowedEnvironments` | list of text | None. Needed | The environments that the instance serves. A write to another environment answers 422 `environment-not-served`, with the address of the instance that serves it when `directory` names one (`core/pipeline.py`, `check_env_served`) |
| `instance.publicUrl` | text (URL) | None | The address of the API. It is in the links of the pull request checks and in the examples of the API document (`jobs/pr_checks.py`, `main.py`) |
| `instance.portalUrl` | text (URL) | `""` | The address of the portal. The email channel uses it for its links (`core/channels.py`) |
| `instance.auth.issuer` | text (URL) | None. Needed | The Keycloak realm. A token with another `iss` is refused |
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
| `instance.directory` | mapping | none | Where to send a caller for the other environments. Each entry has `url`, `environments` and an optional `portalUrl`. cmapi puts them in the 422 answer `environment-not-served` (`core/pipeline.py`) |
| `instance.cors.allowedOrigins` | list of origins | `[]` | The origins of other hosts that can call the API from a browser. With no key or an empty list, CORS is off. An origin is `https://host[:port]`, in lower case, or `http://localhost`, `http://127.0.0.1` or `http://[::1]`, with no path and no default port. A wildcard stops the start (`core/cors.py`) |
| `instance.problems.typeBase` | text (URL) | `https://cmapi.ephico2real.com/problems/` | The base of each problem `type` URI (RFC 9457). It is an absolute http or https URL with no query and no fragment (`core/errors.py`) |
| `instance.docs.enabled` | boolean | `true` | `false` turns off `/docs`, `/redoc` and the OpenAPI documents (`main.py`) |
| `instance.docs.public` | boolean | `true` | `false` makes each of those pages need a valid token (`main.py`, `_add_docs`) |
| `instance.policy` | mapping | See "The policy engine" | The policy engine and a mode for each environment |

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
- When a served environment runs Kyverno and the image has no `kyverno` binary, cmapi does not start (`PolicyEngineMissing`, `core/validate/__init__.py`). When the variable `CMAPI_KYVERNO_VERSION` is set, the binary must be that version. The image sets it (`cmapi/Containerfile`: v1.20.0).
- `GET /api/v1/admin/integrations` reports the engine, the mode of each environment, and the Kyverno version (`routers/admin.py`). The metric `cmapi_policy_mode{environment, mode}` is 1 for each (`core/context.py`).
- The policies come from the configuration, not from files that a person writes. `core/policygen.py` renders them from `metadata-keys.yaml`, `tiers.yaml` and `instance.yaml` `policy`, as `policies.kyverno.io/v1` `ValidatingPolicy` objects. A hand-written policy in `CMAPI_POLICIES_DIR` (default `/etc/cmapi/policies`) runs with them (`core/validate/__init__.py`).
- To write the rendered files into the cluster-configs repository, run `cmapi-tools policies render --config-dir <dir> --metadata-keys <file> --out <dir>`. `cmapi-tools policies check --config-dir <dir> --metadata-keys <file> --dir <dir>` fails when a file differs from the render (`cmapi/src/cmapi/tools/policies.py`). The rendered files of an instance are the folders `env/<env>/` of its own environments. The decision record is `docs/reviews/2026-11-14-issue-212/` and `docs/reviews/2026-11-14-issue-213/`.

---

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
| `system` | list of keys | `[]` | Keys that only the renderer sets. A request that sends one is refused (`reserved_key`) |
| `operatorOnly` | list of keys | `[]` | Keys that `cmapi-operator` and above can set. A requester gets 403 |
| `reservedPrefixes` | list of prefixes | `[]` | Prefixes of Kubernetes, OpenShift and platform controllers. A trailing `/` is allowed, and `*` matches (`fnmatch`). A request that sends such a key is refused (`reserved_key`) |
| `requiredLabels` | mapping of key to rule | `{}` | Labels that each namespace carries |
| `requiredAnnotations` | mapping of key to rule | `{}` | Annotations that each namespace carries |
| `extraLabels` | mapping | `{}` | `keys`: optional labels, each with a rule. `allowOther`: any other label under a prefix |
| `extraAnnotations` | mapping | `{}` | The same, for annotations |
| `adoptionLabels` | mapping of key to `{recognise: [values]}` | `{}` | Labels that mark a namespace that another tool made. A requester cannot set them: the class of such a key is `reserved`. Today cmapi reads only the keys, for that class. The adoption that reads the values (story #26) is not built |
| `sensitiveKeys` | list of keys | `[]` | A change of the value of one of these keys adds the fact `sensitiveKeyChanged`. The first time that a key is set is not a change |
| `emailDomains` | list of domains | `[]` | The mail domains for a key with `format: email-in-domains`. A key of that format needs at least one domain |

Where `emailDomains` is set: in each deployment's metadata configuration. On CRC it is `deploy/manifests/environments/crc/20-config.yaml`, key `emailDomains`; on kind it is the same key in `deploy/manifests/environments/kind/20-config.yaml`. The examples are `examples/cluster-configs/policies/metadata-keys.yaml` (`[ephico2real.com]`, a placeholder) and the company profile `metadata-keys.company.yaml` (`[company.net]`). To change it on CRC, edit that key, apply the ConfigMap, then `oc rollout restart deploy/cmapi-api deploy/cmapi-worker -n cmapi`. The domain is checked for format only: cmapi never looks a DL up.

The old stanzas `governed` and `team` stop the start. The error names the new stanzas (`MetadataKeys.__init__`). So a file of the old format cannot silently stop requiring a key.

The shape of the file is checked too (#338), so that a typo cannot load as a file with fewer rules:

- A top-level key that is not one of the ten stanzas above stops the start, and the error names the nearest stanza: `unknown stanza 'requiredLabel': did you mean requiredLabels?`.
- A list stanza (`system`, `operatorOnly`, `reservedPrefixes`, `sensitiveKeys`, `emailDomains`) must be a list of text. A text such as `emailDomains: ephico2real.com` is refused; before #338 it loaded as its characters (`['e', 'p', 'h', ...]`).
- A mapping stanza (`requiredLabels`, `requiredAnnotations`, `extraLabels`, `extraAnnotations`, `adoptionLabels`), and `keys` and `allowOther` in an extra stanza, must be a mapping. An `adoptionLabels` entry has the one field `recognise`.
- Each `emailDomains` entry must be a domain name: labels of letters, digits and `-`, joined by `.`, as the chart's `values.schema.json` says.
- An empty stanza (`operatorOnly:` with nothing after it) is an empty list or mapping. The file itself must be a mapping: an empty file stops the start.

### The rule of one key

A key of `requiredLabels`, `requiredAnnotations` or `extraLabels.keys` or `extraAnnotations.keys` has a rule. Give one of `value`, `pattern`, `enum` and `format`. A key with none takes any value.

| Field | Type | Meaning |
|---|---|---|
| `value: {from: ...}` | `namespace`, `environment`, `cluster` or `instance` | cmapi sets the value from the target of the request. A request can send the same value. Any other value, or a removal, is refused (`derived_key`). A key with `value` takes no `pattern`, `enum`, `format` or `namespacePrefix` |
| `pattern` | regular expression | The whole value must match. Written in the subset that Python, Kyverno and the API document read alike: see "Patterns" below |
| `enum` | list of text | The value is one of these. A label value must be a valid label value |
| `format` | `email-in-domains` or `url` | `email-in-domains`: an address with one `@`, a local part of ``[A-Za-z0-9!#$%&'*+/=?^_`{\|}~.-]``, and a domain in `emailDomains`, in any case of its ASCII letters. `url`: `http://` or `https://` in any case, a host with no `/`, `?`, `#`, whitespace or character whose NFKC form holds `/`, `?`, `#`, `@` or `:` (as `℀`, CVE-2019-9636), and a `[` only as `[userinfo@][IPv6 address]` with an optional `:port` after it, then optionally a path, query or fragment with no whitespace. Whitespace is what Python's `str.isspace()` calls whitespace. Each format is one regex (`value_regex` in `core/metadata.py`), which cmapi matches and the rendered Kyverno policy matches too (#332). A format is for annotations only: a label value is at most 63 characters of `[A-Za-z0-9_.-]`, so it cannot hold an address or a URL |
| `namespacePrefix` | boolean | The namespace name starts with the value and a `-`. For the value `abc`, the namespace `abc-rnd` passes |
| `description`, `example` | text | Text for people and for the API document. A required key that cmapi does not derive needs an `example`, and every `example` must pass its key's own rule (the owner's answer to #328, question 3) |

The loader refuses each of these, and the start stops:

- A key that is a system, operator-only or reserved key.
- A key declared two times as the same kind.
- An invalid label or annotation key, or an unknown field.
- A `pattern` that does not compile, that is empty, or that is outside the subset below (#332).
- More than one of `pattern`, `enum` and `format`.
- A required key with no `example`, unless it has `value`. An `example` that its key's rule refuses, or that is not text.
- A `description` that is not text, and a `namespacePrefix` that is not `true` or `false`.
- A format on a label, and `email-in-domains` with no `emailDomains`.
- An `adoptionLabels` key that a stanza declares, or that is a system or operator-only key.
- An `adoptionLabels` entry whose `recognise` is not a list of label values.

A key can be a label and an annotation at the same time, each with its own rule.

### Patterns

Each `pattern` is read by RE2 in cmapi's validator (the whole value must match; `value_matches` in `core/metadata.py`, #348) and in the rendered Kyverno policies (CEL `matches()`), and by ECMA-262 or Python's `re` in each client of the API document (a JSON Schema `pattern`, #328). cmapi anchors a pattern once, as `^(?:P)$` (`anchored` in `core/metadata.py`), and the loader refuses a pattern that any of the three would read differently, with the key, the construct and its position: `extraAnnotations.company.net/code: pattern '^\\d{4}$' is outside the subset that Python re, RE2 (Kyverno) and ECMA-262 (the API document) read alike: \d (Python also matches the digits of other scripts): write [0-9], at character 2 (docs/18, "Patterns")`.

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
| `operatorOnly` | Is in `operatorOnly` | Refused for a requester (403) |
| `reserved` | Is in `adoptionLabels` (as a label), or has a prefix of `reservedPrefixes` | Refused |
| `governed` | Is declared in a required or extra stanza | Allowed, with its rule |
| `team` | Has a prefix of `allowOther` | Allowed, within the limits |
| `disallowed` | Is none of these | Refused (`invalid_key`) |

A key that a stanza declares for the other kind only is refused even when `allowOther` admits its prefix. For example, a label `company.net/mnemonic-confluence` is refused as "an annotation" when only `extraAnnotations` declares it (`MetadataKeys.validate`).

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

- **The block is the whole file**, not a patch of the chart's file. Write each of the ten stanzas of the table above, `{}` or `[]` when one is empty. The schema refuses a block that leaves one out, so a partial block cannot silently drop the reserved keys or the required ones.
- **Empty (`metadata: {}`, the default):** the chart's `config/metadata-keys.yaml`, or the full text in `configFiles."metadata-keys.yaml"`. That text stays the fallback, and the schema does not read inside it.
- **Both set:** the render fails: `metadata and configFiles."metadata-keys.yaml" both set metadata-keys.yaml: set one of them`.
- **What the schema refuses:** an unknown or misspelled stanza or field (`additionalProperties: false` at each level, so the old stanzas `governed` and `team` too); a missing stanza; a wrong type (a text for a list, a limit that is not a whole number of zero or more); a key that is not a valid label or annotation key, including an empty prefix such as `/foo`; a `format` on a label; more than one of `pattern`, `enum` and `format`; `value.from` with a source other than `namespace`, `environment`, `cluster` or `instance`, or beside a `pattern`, `enum`, `format` or `namespacePrefix: true`; an empty `enum`, or a label `enum` value that a label cannot hold; an `adoptionLabels` entry with no `recognise`; a rule or an `example` that is not text; a required key with no `example` and no `value` (#332); a domain that is not a DNS name. The loader still checks what JSON Schema cannot: that a `pattern` compiles and is in the subset of "Patterns" above (its grammar nests parentheses, which the schema's own `pattern` keyword cannot describe), that an `example` passes its key's rule, that `email-in-domains` has a domain, that a key is not reserved or declared twice.
- `configFiles` takes only the five names of the chart's files. Another name, such as `metadata-key.yaml`, is refused; before #335 the chart ignored it and rendered its own file.

An example, a site that requires its own owner label beside the reference keys (`deploy/environments/<site>.yaml`):

```yaml
metadata:
  system: [cmapi.net/cluster-id, cmapi.net/managed, cmapi.net/request-id, cmapi.net/requested-by,
           cmapi.net/requested-by-user, cmapi.net/tier, cmapi.net/instance, cmapi.net/env, cmapi.net/tier-hash,
           cmapi.net/beyond-tier, cmapi.net/expiry, cmapi.net/expires-at]
  operatorOnly: [cmapi.net/protected]
  reservedPrefixes: [kubernetes.io/, "*.kubernetes.io/", k8s.io/, openshift.io/, "*.openshift.io/",
                     argocd.argoproj.io/, "*.kyverno.io/", redhatcop.redhat.io/]
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
  sensitiveKeys: [cmapi.net/team]
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
| A required key that cmapi does not derive | A property in `required` (create only), with `minLength: 1`; the map itself is in `NamespaceCreate.required`. On a patch it has no `null` branch, since a patch cannot remove it |
| An optional key | A property; on a patch, `anyOf` with `null`, which removes it |
| `pattern`, `format` | `pattern`: the one regex that cmapi and the rendered Kyverno policy match too (`value_regex`, "Patterns" above), and `x-cmapi-format` for a format. A label also gets the label-value syntax and `maxLength: 63` |
| `enum` | `enum` |
| `value: {from: ...}` | A property with `readOnly: true` and `x-cmapi-derived-from`, never required, with no `null` branch on a patch. Swagger UI hides a read-only property in a request body |
| `namespacePrefix` | `x-cmapi-namespace-prefix: true`, and the rule in words |
| `description`, `example` | `description` (with the rule in words) and `examples` |
| `operatorOnly` | A property with `x-cmapi-operator-only: true` |
| `allowOther` | `propertyNames`: a declared key, or a key under an allowed prefix that is not a system key, an adoption label, a key of the other kind or under a reserved prefix. `additionalProperties`: the value rule of those keys. `x-cmapi-other-keys`: the prefixes and the limits |

What JSON Schema cannot say is in the description of the map, which ReDoc shows (ReDoc 3.1.0 does not show `propertyNames`): who may set an operator-only key, that a derived value must equal the request's target, that a `namespacePrefix` value starts the namespace name, the count of other keys (`max`), the sizes in bytes (`maxValueBytes`, `maxBytesTotal`; the schema's `maxLength` counts characters, a bound that holds because a character is at least one byte), and on a patch the 253 characters of a key's prefix (a create refuses a longer one with a second pattern under `not`). On a patch, `propertyNames` checks the class of a key and not its syntax: a key that Git holds from before #330, such as `/foo`, can still be removed with `null`, and JSON Schema cannot tie a key's name to its value.

The schema documents cmapi's own check; it never replaces it. cmapi refuses each body with or without Kyverno (`policy.engine: none` included), and a client that checks the schema first only learns of a refusal sooner. Each map that cmapi accepts passes the schema: `cmapi/tests/core/test_metadata_schema_328.py` runs one corpus of about 12,000 maps for each file through both, on the shipped files and on four synthetic ones, and `cmapi/tests/service/test_metadata_schema_328_api.py` runs it on each instance's served document.

The examples in the document are this instance's too (#334): the `labels` and `annotations` examples are the `example` of each required key, the namespace example starts with the example of a `namespacePrefix` key and `-` (`abc-dev` with the company file), and the patch example is the first optional key that has an example. Swagger UI's "Try it out" body and the curl sample of each write are one body, built from them: the recorded request (`contract/samples.json`, recorded on the reference file), whose labels and annotations are replaced with them when the instance refuses its own (#349).

**Generated clients.** The committed contract, `cmapi/contract/openapi.json`, is the document of the reference file (`examples/cluster-configs/policies/metadata-keys.yaml`), and the contract gate sees only that file. A client for an instance with its own keys is generated from that instance's own document, for example `curl -fsS https://<instance-route>/openapi.json -o openapi.json` and then the generator (the portal uses openapi-typescript 7.13.0, through `cmapi-portal-ui/scripts/api-types.mjs`). An instance with `docs.enabled: false` serves no document.

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
| `protected.labels` | list of `key=value` | `[]` | A namespace with one of these labels is protected: a delete is refused (`namespace-protected`) |
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
| `capacity`, `capacityFresh` | `fits`, `warn`, `exceeded` or `unknown`, and whether the data is fresh | `core/capacity_backend.py` |
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
| `guards` | list | `[]` | Extra guards: `noOpenRequest`, `notProtected`, `noExtensionInLast24h`, `noticesSentAtLeast2`. An unknown guard stops the start. Three of them read facts that only the daily expiry check sets, and that check is not built. So today `noOpenRequest` and `noExtensionInLast24h` always pass, and `noticesSentAtLeast2` always stops the policy. `notProtected` reads the fact `protected` of a delete |

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

The file is needed. The code is `cmapi/src/cmapi/plugins/expiration/rules.py`. An environment with no entry refuses each expiry field with 422 `expiration-not-allowed`. `prod` cannot have an entry. The daily expiry check that sends the notices and opens the delete (`ExpirationRules.expire_check`) is in the code, and no job runs it: it is not built. So today cmapi reads only `allowedAtCreate`, `maxExtensionDays`, `maxLifetimeDays`, and whether an environment has an entry.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `defaults.allowedAtCreate` | boolean | `true` | A new namespace can have an expiry date |
| `defaults.maxExtensionDays` | integer | `30` | One extension adds at most this many days |
| `defaults.maxLifetimeDays` | integer | `180` | A date past this many days from creation sets the fact `expirationBeyondLimits`. `:makePermanent` sets it too. The reference `approval-rules.yaml` adds one approver of `approver-platform` for the fact |
| `defaults.notifyDaysBefore` | list of integers | `[14, 7, 1]` | The days before the date for a notice. Read only by the daily expiry check, which is not built |
| `defaults.graceDays` | integer | `7` | The namespace still runs and can be extended for this many days from the date. Read only by the daily expiry check, which is not built |
| `defaults.deleteAfterGrace` | boolean | `true` | The daily expiry check opens a delete after the grace. The check is not built |
| `defaults.minNoticesBeforeDelete` | integer | `2` | The notices that must go before the delete. Read only by the daily expiry check, which is not built |
| `environments.<env>` | mapping | `{}` | The same keys as `defaults`, for one environment. An empty mapping means "the defaults" |

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
| `enabled` | list of plugin names | Each built-in plugin: `namespaces`, `tiers`, `directory`, `quotas` | The plugins whose routes the API mounts. A plugin that is not listed has no route and no line in the API document |
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
| `notifier.smtp.host` | text | None | The SMTP host. Without it, only the portal channel is active |
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
| `environment` | text | None. Needed | An environment that the instance serves. Another value stops the start |
| `gitopsPath` | text | `clusters/<clusterId>` | Shown in `GET /api/v1/clusters`. No built code uses it for the folder: the folder is always `clusters/<clusterId>/namespaces/<namespace>/` (`folder`, `core/render/manifests.py`) |
| `writes` | boolean | `true` | `false` makes the cluster read only |
| `syncSignal` | text | `poll` | No built code reads it. `notify` is not built |
| `delivery` | `argocd` or `apply` | The `delivery.mode` of `integrations.yaml` | The delivery mode of this cluster (`jobs/watch_sync.py`) |
| `thanosUrl` | text | None | No built code reads it |
| `labels` | mapping | `{}` | Labels that `match.clusterSelector` reads. `GET /api/v1/clusters` shows them |
| `metadata`, `placement` | mapping | `{}` | No built code reads them |
| `simulatedCapacity` | mapping with `cpu` and `memory` | None | The size of the cluster for the built-in capacity check. Without it the capacity answer is `unknown`, so the guard `capacity` stops each auto-approval of a create or a change |

`capacity.yaml` keys that built code reads (`core/capacity_backend.py`, `core/context.py`, `core/kpi.py`): `overcommit.<env>.cpu` and `.memory` (default 1.0), `targets.<env>.commitment.warn` (default `0.85`), and `kpi.thresholds`. The other keys of the reference file are designed for the capacity service, which is not built.

---

## Environment variables

`cmapi/src/cmapi/settings.py` holds most variables: the name is `CMAPI_` and the field name in upper case. Some modules read a variable directly, and the table names the module for each of those. The variables of the chart Jobs (realm sync, Git bootstrap) are in `cmapi/src/cmapi/tools/`. The chart sets them (`deploy/helm/cmapi/templates/_helpers.tpl`, `api.yaml`, `worker.yaml`). A value that is a secret comes from a Kubernetes Secret.

| Variable | Default | Meaning |
|---|---|---|
| `CMAPI_CONFIG_DIR` | `/etc/cmapi/config` | The folder of the files above |
| `CMAPI_METADATA_KEYS` | `<config dir>/metadata-keys.yaml` | Another path for `metadata-keys.yaml` |
| `CMAPI_POLICIES_DIR` | `/etc/cmapi/policies` | Hand-written Kyverno policies that run with the rendered ones |
| `CMAPI_CA_BUNDLE` | None | A PEM bundle that cmapi trusts for Keycloak and the clusters, and for Git unless `CMAPI_GIT_CA_BUNDLE` is set |
| `CMAPI_DATABASE_URL` | `""` | `postgresql://user:password@host:5432/db`. A secret |
| `CMAPI_DATABASE_POOL_SIZE` | `5` | The pool of connections of one process |
| `CMAPI_OIDC_JWKS_URL` | `<issuer>/protocol/openid-connect/certs` | Where to read the signing keys |
| `CMAPI_OIDC_LEEWAY_SECONDS` | `30` | The clock leeway for `exp` and `iat` |
| `CMAPI_KEYCLOAK_ADMIN_URL` | The issuer, up to `/realms/` | The base of the Keycloak admin API |
| `CMAPI_DIRECTORY_CLIENT_SECRET` | `""` | The secret of the `cmapi-directory` client. A secret |
| `CMAPI_GIT_PROVIDER` | `gitea` | `gitea` or `github` |
| `CMAPI_GIT_URL` | `""` | The API URL of the Git host |
| `CMAPI_GIT_TOKEN` | `""` | The bot account's API token, from Secret `cmapi-git-bot`, for the host's API. A secret. No git process gets it from the environment |
| `CMAPI_GIT_USER`, `CMAPI_GIT_PASSWORD` | `""` | Basic authentication instead of a token. A secret |
| `CMAPI_GIT_DEFAULT_BRANCH` | `main` | The branch that the bot's PRs merge into. Nothing is ever pushed to it |
| `CMAPI_GIT_CREDENTIALS_DIR` | `/etc/cmapi/git-bot` | Secret `cmapi-git-bot` as files: `token`. Git over HTTPS reads it through a credential helper (#286) |
| `CMAPI_GIT_SSH_DIR` | `/etc/cmapi/git-bot-ssh` | Secret `cmapi-git-bot-ssh` (`kubernetes.io/ssh-auth`): `ssh-privatekey`, an ed25519 key with no passphrase, and optionally `ssh-publickey`. Worker only |
| `CMAPI_GIT_KNOWN_HOSTS_DIR` | `/etc/cmapi/git-bot-known-hosts` | ConfigMap `cmapi-git-bot-known-hosts`: `known_hosts`, every key type the host publishes. Worker only |
| `CMAPI_GIT_WORKDIR` | A temporary folder | The worker's Git workdir: the mirror `repo.git` and one worktree per request. The plain manifests mount an emptyDir with `sizeLimit: 1Gi` |
| `CMAPI_GIT_WORKDIR_LIMIT_BYTES` | `1073741824` | The emptyDir's `sizeLimit`: above 80 % the sweeper removes the workdir, to be fetched again |
| `CMAPI_GIT_CA_BUNDLE` | None: the trust of `CMAPI_CA_BUNDLE` | The PEM bundle the Git provider alone trusts, as an explicit TLS context that `SSL_CERT_FILE` cannot change. A file that is not there stops the process at start. CRC sets the image's system bundle, `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`, since its `CMAPI_CA_BUNDLE` holds Keycloak's private CA alone (#97) |
| `CMAPI_CURSOR_KEY` | `""` | The key that signs list cursors. Empty: cmapi signs with the fixed text `unset-cursor-key` (`core/context.py`), the same on each instance. A secret |
| `CMAPI_LINK_KEY` | `""` | The key that signs the links of the email channel. Empty: cmapi signs with the fixed text `unset-link-key` (`core/channels.py`). A secret |
| `CMAPI_IMPORTS_NAMESPACE` | `cmapi-imports` | The hub namespace that holds the cluster import Secrets |
| `CMAPI_IMPORTS_DIR` | None | Reads import Secrets from YAML files in this folder, for tests |
| `CMAPI_KUBE_TOKEN_FILE`, `CMAPI_KUBE_CA_FILE`, `CMAPI_KUBE_API_URL` | The service account files, and `https://kubernetes.default.svc` | How cmapi reads the import Secrets of the hub |
| `CMAPI_COMPONENT` | `api` | `api`, `worker` or `capacity`. The label `component` of the metrics |
| `CMAPI_LOG_LEVEL` | `INFO` | The log level |
| `CMAPI_BIND_PORT`, `CMAPI_METRICS_PORT` | `8080`, `9090` | The ports of the API and of the metrics |
| `CMAPI_WORKER_POLL_SECONDS` | `2.0` | How often the worker looks for a due job |
| `CMAPI_WORKER_ID` | The host name | The name of the worker in a lease |
| `CMAPI_KYVERNO_VERSION` | None | When set, the `kyverno` binary must be this version, or cmapi does not start (`core/validate/__init__.py`). The image sets it |
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
| `capacity.mode`, `.snapshotInterval`, `.overcommit`, `.targets` | | `embedded`, `30m` | `capacity.yaml` |
| `notifier.smtp` | mapping | `{}` | `integrations.yaml` `notifier.smtp`. Empty: the email channel is off |
| `database.cnpg.enabled`, `.name`, `.instances`, `.storage`, `.storageClass`, `.imageName`, `.resources`, `.parameters` | | CloudNativePG with 1 instance and 2Gi | The PostgreSQL cluster. See `docs/12` |
| `database.existingSecret` | text | `""` | With CNPG off: a Secret with the key `uri`. Needed then |
| `api.*`, `worker.*`, `portal.*`, `migrate.*` | | | `replicas`, `resources` and `logLevel` of each workload, and the `migrate` init container |
| `exposure` | `Route` or `Ingress` | `Route` | `Route` for OpenShift, `Ingress` for plain Kubernetes. `Ingress` needs `ingress.<site>.host` |
| `route.*`, `ingress.*` | | Empty hosts | The hosts and the TLS of each site: `api`, `portal`, `mockup` |
| `trustedCA.certificates`, `trustedCA.injected.enabled` | | `""`, `false` | A PEM bundle that the pods trust, or the bundle that OpenShift injects |
| `monitoring.serviceMonitor`, `.prometheusRule`, `.perses` | | `enabled: false` | The scrape, the alerts and the dashboards |
| `networkPolicy.enabled`, `.monitoringNamespace` | | `true`, `openshift-user-workload-monitoring` | The network policies |
| `securityContext`, `containerSecurityContext`, `podDisruptionBudget` | | Restricted | Non-root, no capabilities, the runtime default seccomp profile |
| `metadata` | mapping | `{}` | `metadata-keys.yaml` as structured values: the whole file, each stanza written out. Checked by `values.schema.json`. Empty: the chart's file, or `configFiles."metadata-keys.yaml"`. Setting both fails (see "Setting the keys through the Helm values") |
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

## The bot account on each host

The identity is one machine user account, `cmapi-git-bot`, on each host (the owner's decision of 2026-11-15, #286): its SSH key for Git, its token for the PR. A deploy key is the alternative where the host allows writes with one. Read on 2026-11-15; a row marked *not verified* is not yet checked at its host's documentation.

| Host | Bot account: SSH | Bot account: API | Alternative | Source |
|---|---|---|---|---|
| GitHub | the machine user's SSH key | its fine-grained token: Contents and Pull requests read and write | a deploy key with write access, for SSH | [GitHub, deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) |
| GitLab | the service account's SSH key | its token | a read-write deploy key made by the service account; a project access token for the API | [GitLab, deploy keys](https://docs.gitlab.com/user/project/deploy_keys/) |
| Bitbucket Cloud | the bot account's own SSH key | its API token, or a repository access token | none for writes: repository and project access keys are read-only | [Atlassian, access keys](https://support.atlassian.com/bitbucket-cloud/kb/difference-between-repository-project-and-workspace-access-keys/) |
| Bitbucket Data Center | the bot user's SSH key | its HTTP access token | an access key with write access | *not verified* |
| Gitea | the bot user's SSH key | its token | a deploy key with write access | *not verified* |
