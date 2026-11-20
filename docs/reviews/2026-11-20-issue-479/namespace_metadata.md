# Namespace metadata: design reference

Status: **proposed, for the owner's review** (2026-11-20). Nothing here is built yet beyond what section 1 marks as
"built today". Tracked as cmapi issue #479 (to be rewritten from this document once approved).

`company.net` stands for any company's domain. Section 3 shows the same configuration for a real domain (`cnn.com`).
Values such as `abc`, `amgsst`, `payments` and `cc-4410` are **examples only**: they appear in `example:` fields, which
Swagger and the portal show as hints, and nothing enforces them.

---

## 1. The owner's requirements

| # | Requirement (owner's words, condensed) | Built today? |
|---|---|---|
| R1 | "in the payload we need fields to be required for metadata for labels and annotations … configure this compulsory but parameterizable … requiredAnnotations (stanza) and requiredLabels (stanza as well)" (2026-11-14) | Yes: the four stanzas (#215, PR #234) |
| R2 | "we are going to set the required fields via values file that feeds to the application configurations" (2026-11-17) | Yes: Helm value `metadata:` (#335, PR #339) |
| R3 | The required fields show in Swagger (2026-11-16, 2026-11-18) | Yes for plain keys (#350). **No** for filled-in keys: they are `readOnly`, never required, and hidden by Swagger UI |
| R4 | Keep the current keys and add `name` (filled automatically from the namespace, required), `company.net/app-environment`, `company.net/mnemonic`, `company.net/lob`, `company.net/cl`, all required in the API, the portal and Swagger (2026-11-20) | **No**: CRC runs only the demo keys |
| R5 | Every namespace name starts with the mnemonic as a prefix: `abc-cmapi-payments-dev`, not `cmapi-payments-dev` (2026-11-20) | The rule exists (`namespacePrefix`, `core/metadata.py:929`); CRC does not use it |
| R6 | The portal's Namespace field has a fixed, non-editable prefix taken from the mnemonic, so nobody types it twice (2026-11-20) | **No** |
| R7 | The portal is reactive: it shows what will be created before the request is submitted; no straight submit (2026-11-20) | Partly: the form plans with a dry run; no live preview |
| R8 | Setting the mnemonic fills `cmapi.net/team` with the same value, which can then be changed (e.g. to `payments`) (2026-11-20) | **No** |
| R9 | The Swagger page has the clean look of the owner's reference: every parameter with its type and location, the body with **Example Value** and **Model/Schema** tabs, every field shown with its type and format, required fields marked (2026-11-20) | Partly |
| R10 | The name ends with the cluster's environment: a cluster onboarded as `rnd` takes only `abc-payments-rnd`, a `dev` cluster only `abc-payments-dev`. The portal locks both ends: `<mnemonic>-<desired name>-<cluster env>` (2026-11-20) | **No** |
| R12 | An optional expiration date chosen from a calendar in the portal; the form shows the date and the number of days until it. For production a flag turns expiration off, so the field is blank. The date is written on the namespace (2026-11-20) | Partly: `expiresAt` exists in the API (`expiration.yaml`); the portal has no calendar on the create form |
| R11 | The portal sets additional labels and annotations as part of the payload, in two separate key/value tables, as the API already allows; people open them with a toggle (2026-11-20) | **No** (filed earlier as #365) |

---

## 2. The rules

1. **Name.** Every namespace name is `<mnemonic>-<desired name>-<cluster env>`, for example `abc-payments-dev` on a
   `dev` cluster and `abc-payments-rnd` on an `rnd` cluster. The mnemonic is the value of the key that has
   `namespacePrefix: true` (`company.net/mnemonic`: 3 or 4 lowercase letters). The environment is the value of the key
   that has `namespaceSuffix: true` (`company.net/app-environment`, filled from the cluster's environment). The whole
   name is a DNS-1123 label of at most 63 characters.
2. **Filled-in keys** (`value: {from: …}`): cmapi sets the value from the request's target (`namespace`,
   `environment`, `cluster`, `instance`). They are **required and shown** everywhere. An API client may leave one out
   (cmapi fills it) or send the right value; any other value is refused (`derived_key`, as today).
3. **Defaults from another key** (new, `default: {from: <key>}`): when a request does not send the key, cmapi fills it
   from the named key; a sent value is kept. `cmapi.net/team` defaults to the mnemonic.
4. **Examples are not rules.** `example:` feeds Swagger's Example Value and the portal's placeholders only.
5. **Identity never comes from the body.** Who asked is taken from the signed token, as today.
6. **Extra keys** go into the same `labels` and `annotations` maps, within `allowOther`: an allowed prefix, the key and
   value syntax, at most 50 per kind, and the annotation byte limits. A key that has its own field, a reserved key, a
   system key and an operator-only key are refused there.
7. **Expiration** (optional; the rules are `expiration.yaml`'s): `expiresAt` is a date. Left out, the namespace
   is permanent. Each environment has an **`enabled` flag** (NEW; `defaults.enabled: true`). With `enabled: false`, or
   no entry, expiration is off there: the field is blank and hidden in the portal and `expiresAt` is refused
   (`expiration-not-allowed`). A namespace dated while it was on keeps its date on every other change; **Make permanent**
   still removes it, and Extend and Set are refused. Production ships with `prod: {enabled: false}`; cmapi also refuses
   `prod: {enabled: true}` at start and never writes an expiry on a prod namespace (the #222 backstop). A date not after today is refused
   (`expiration-in-past`). More than `maxLifetimeDays` (180) after creation is allowed with one more approver-platform
   approval. Notices go to the team DL at 14, 7 and 1 days before; the namespace keeps running `graceDays` (7) after the
   date, then a delete request is opened. **On the namespace**, cmapi writes the annotation
   `cmapi.net/expires-at: "<date>"` and the label `cmapi.net/expiry: managed` (`core/render/manifests.py:155-157`); both
   are system keys, set only through `expiresAt`

---

## 3. The configuration (`values.yaml`, Helm value `metadata:`)

The block is the whole `metadata-keys.yaml` (ten stanzas), checked by the chart's `values.schema.json` at
`helm install`. Three fields are new and marked `# NEW`: `namespaceSuffix` (on the environment key),
`default: {from: …}` (on `cmapi.net/team`) and the optional `allowOther.example`.

### 3.1 For any company (`company.net`)

```yaml
metadata:
  system: [cmapi.net/cluster-id, cmapi.net/managed, cmapi.net/request-id, cmapi.net/requested-by,
           cmapi.net/requested-by-user, cmapi.net/tier, cmapi.net/instance, cmapi.net/env, cmapi.net/tier-hash,
           cmapi.net/beyond-tier, cmapi.net/expiry, cmapi.net/expires-at]          # cmapi writes these; nobody sends them
  operatorOnly: [cmapi.net/protected, do-not-delete]                              # only an operator sets them
  reservedPrefixes: [kubernetes.io/, "*.kubernetes.io/", k8s.io/, openshift.io/, "*.openshift.io/",
                     argocd.argoproj.io/, "*.kyverno.io/", redhatcop.redhat.io/,
                     olm.operatorgroup.uid/, openshift-pipelines.tekton.dev/]

  requiredLabels:
    name:
      value: {from: namespace}                       # filled in by cmapi: a copy of the namespace name
      title: Name
    company.net/app-environment:
      value: {from: environment}                     # filled in by cmapi: the cluster's environment
      namespaceSuffix: true                          # NEW: the namespace name must end with "-<environment>"
      title: App environment
    company.net/mnemonic:
      pattern: "^[a-z]{3,4}$"
      namespacePrefix: true                          # the namespace name must start with "<mnemonic>-"
      title: Mnemonic
      description: "Your team's mnemonic, 3 or 4 lowercase letters; every namespace name starts with it"
      example: abc
    company.net/lob:
      title: Line of business
      description: "Free text, a valid label value"
      example: amgsst
    company.net/cl:
      enum: ["0", "1", "2", "3", "4", "5", "6"]
      title: Critical level
      example: "1"
    cmapi.net/team:
      pattern: "^[a-z0-9-]{2,40}$"
      default: {from: company.net/mnemonic}          # NEW: filled from the mnemonic when not sent; can be changed
      title: Team
      description: "Who owns it, for cost and notices; defaults to the mnemonic"
      example: payments

  requiredAnnotations:
    company.net/app-environment:
      value: {from: environment}                     # filled in by cmapi
    cmapi.net/team-dl:
      format: email-in-domains                       # an address in one of emailDomains
      title: Team DL
      example: payments-team@company.net

  extraLabels:                                       # optional labels
    keys:
      cmapi.net/cost-center: {pattern: "^cc-[0-9]{4}$", title: Cost center, example: cc-4410}
      cmapi.net/app:         {pattern: "^[a-z0-9-]{2,40}$", title: App, description: "Links an app's environments"}
      cmapi.net/rightsizing: {enum: [auto, manual], title: Rightsizing}
    allowOther: {prefixes: ["", "*.company.net/"], max: 50,
                 example: {team.company.net/squad: checkout}}     # NEW (optional): the extra label in the examples

  extraAnnotations:                                  # optional annotations
    keys:
      company.net/mnemonic-group-contact: {format: email-in-domains, title: Group contact}
      company.net/mnemonic-confluence:    {format: url, title: Confluence page}
    allowOther: {prefixes: ["", "*.company.net/"], max: 50, maxValueBytes: 4096, maxBytesTotal: 65536,
                 example: {runbook.company.net/url: "https://wiki.company.net/abc/runbook"}}   # NEW (optional)

  adoptionLabels:                                    # recognises namespaces made the old way (story #26)
    company.net/provisioner: {recognise: [cluster-configs]}

  sensitiveKeys: [cmapi.net/team, company.net/cl, cmapi.net/protected, do-not-delete]   # a change adds one approver-platform approval
  emailDomains: [company.net]
```

### 3.2 The same for `cnn.com`

Only the company's own prefix and domain change; cmapi's keys keep `cmapi.net/`. No code names the domain.

```yaml
metadata:
  # system, operatorOnly, reservedPrefixes: as in 3.1
  requiredLabels:
    name:                    {value: {from: namespace}, title: Name}
    cnn.com/app-environment: {value: {from: environment}, namespaceSuffix: true, title: App environment}
    cnn.com/mnemonic:        {pattern: "^[a-z]{3,4}$", namespacePrefix: true, title: Mnemonic, example: abc}
    cnn.com/lob:             {title: Line of business, description: "Free text, a valid label value", example: amgsst}
    cnn.com/cl:              {enum: ["0", "1", "2", "3", "4", "5", "6"], title: Critical level, example: "1"}
    cmapi.net/team:          {pattern: "^[a-z0-9-]{2,40}$", default: {from: cnn.com/mnemonic}, title: Team, example: payments}
  requiredAnnotations:
    cnn.com/app-environment: {value: {from: environment}}
    cmapi.net/team-dl:       {format: email-in-domains, title: Team DL, example: payments-team@cnn.com}
  extraLabels:
    keys:
      cmapi.net/cost-center: {pattern: "^cc-[0-9]{4}$", title: Cost center, example: cc-4410}
      cmapi.net/app:         {pattern: "^[a-z0-9-]{2,40}$", title: App}
      cmapi.net/rightsizing: {enum: [auto, manual], title: Rightsizing}
    allowOther: {prefixes: ["", "*.cnn.com/"], max: 50}
  extraAnnotations:
    keys:
      cnn.com/mnemonic-group-contact: {format: email-in-domains, title: Group contact}
      cnn.com/mnemonic-confluence:    {format: url, title: Confluence page}
    allowOther: {prefixes: ["", "*.cnn.com/"], max: 50, maxValueBytes: 4096, maxBytesTotal: 65536}
  adoptionLabels:
    cnn.com/provisioner: {recognise: [cluster-configs]}
  sensitiveKeys: [cmapi.net/team, cnn.com/cl, cmapi.net/protected, do-not-delete]
  emailDomains: [cnn.com]
```

### 3.3 What each field does

| Field | Effect | In Swagger | In the portal |
|---|---|---|---|
| `value: {from: …}` | cmapi fills the value; a different one is refused | Required, "cmapi fills it in" | Shown, pre-filled, locked |
| `pattern` / `enum` / `format` | The rule the value must meet | The field's format | Checked as you type |
| `namespacePrefix: true` | The namespace name must start with `<value>-` | Said on `namespace` and on the key | The locked `<mnemonic>-` start of the Namespace field |
| `namespaceSuffix: true` (NEW) | The namespace name must end with `-<value>` (on the environment key: the cluster's environment) | Said on `namespace` and on the key | The locked `-<env>` end of the Namespace field; it follows the chosen cluster |
| `default: {from: <key>}` (NEW) | Filled from another key when not sent; can be changed | "default: the value of <key>" | Copies that key until someone edits it |
| `title`, `description` | Label and help text | Shown | The field's label and hint |
| `example` | A hint, never a rule | Example Value | Placeholder |
| `allowOther` (prefixes, max, byte limits) | Which extra keys a request may add | The `<other key>` row; `propertyNames`, `x-cmapi-other-keys` | The two extra-key tables: allowed prefixes, counters |
| `allowOther.example` (NEW, optional) | One extra key in the examples | Shown in Example Value | Placeholder row |

---

## 4. Changes to the API contract

The request's shape does not change: one `NamespaceCreate` with `namespace`, `tier`, `justification`, `labels` and
`annotations` maps, and the optional `expiresAt`, `quota` and `limitRange`. Named fields and extra keys both go into the
same two maps. What changes is what the schema says about the keys, one endpoint's content, and three checks.

### 4.1 Already in the contract (measured on CRC's live `/openapi.json`, 2026-11-20)

| What | Where | Used for |
|---|---|---|
| Each declared key with its rule (`pattern`, `enum`, email format), `title`, `description`, `examples` | `NamespaceCreate.labels.properties`, `.annotations.properties` (#350) | Swagger's Schema tab; the portal's named fields |
| The required keys | `labels.required`, `annotations.required` | The red **required** marks |
| Extra keys' values: label value ≤ 63 with the label pattern; annotation value ≤ 4096 | `additionalProperties` | The value column of the extra-key tables |
| Extra keys' names: a declared key, or the Kubernetes key syntax under an allowed prefix (`""`, `*.company.net/`); reserved and system keys match neither | `propertyNames` (`anyOf` of the declared keys and the prefix pattern) | The key column of the extra-key tables |
| Extra keys' limits: 50 per kind; annotations 4096 bytes each, 65536 in all | `x-cmapi-other-keys` (JSON Schema cannot count only the undeclared keys) | The counters of the extra-key tables |
| Filled-in keys | `readOnly: true`, `x-cmapi-derived-from` | **Changes in A1** |
| The same two schemas, alone | `GET /api/v1/metadata-keys` (#336) | The portal builds its form from them |
| Error codes for keys and values (`invalid_value`, `derived_key`, `missing_required_key`, `reserved_key`, …) | Entries of `errors` in the RFC 9457 `policy-violation` problem (422) | A refusal shown on its field or row |

### 4.2 The changes

| # | Where | Change | Kind |
|---|---|---|---|
| A1 | `labels`, `annotations` schemas (per instance, from `metadata:`) | Filled-in keys (`value: {from: …}`) become **required and shown**: drop `readOnly`, keep `x-cmapi-derived-from`, description "cmapi fills it in; you may leave it out" | **Breaking** for the contract gate (new required properties): one line each in `cmapi/contract/accepted-breaking.txt`, with its reason and #479 |
| A2 | Same | A key with `default: {from: K}`: listed in `required`, description "default: the value of K", `x-cmapi-default-from: K` | Additive |
| A3 | `NamespaceCreate.namespace` | Description and extensions for the name: `x-cmapi-prefix-from: company.net/mnemonic`, `x-cmapi-suffix-from: company.net/app-environment`; "`<mnemonic>-<desired name>-<cluster env>`, at most 63"; the example built from the configuration's examples and the instance's first environment | Additive |
| A4 | The environment key's schema | `x-cmapi-namespace-suffix: true`, beside the existing prefix marker on the mnemonic key | Additive |
| A5 | `GET /api/v1/metadata-keys` | It returns the same two schemas, so A1–A4 reach the portal by themselves, and `x-cmapi-expiration` of A11 beside them (D15), so its ETag changes when `expiration.yaml` does. Its contract test checks they stay equal to `NamespaceCreate`'s | Additive |
| A6 | Request examples (Swagger, ReDoc, docs/04, the recorded samples) | Generated from the configuration's `example:` values: every required key, the optional keys that have an example, and **one extra label and one extra annotation** from a new optional `allowOther.example` in the configuration, so the Example Value shows that extra keys go in the same maps | Additive |
| A7 | Dry-run answer (`?dryRun=true`) | `metadata.labels` and `metadata.annotations` give each final value with its `source`: `request`, `namespace`, `environment`, or `default:<key>`. Extra keys are `request` | Additive |
| A8 | Validation (`core/metadata.py`) | New: the suffix check on a create (the name must end with `-<env>`, with a desired name between the two ends); `default: {from: K}` filled before the checks. The loader refuses a `from` naming no key, a chain of defaults, a key of the other kind, more than one key with `namespacePrefix` or with `namespaceSuffix`, or one key with both | Behaviour |
| A9 | Errors | No new code. A name that does not end with the environment is `invalid_value` on the environment key ("abc-payments-rnd does not end with -dev"); the rest as today | Behaviour |
| A11 | `NamespaceCreate.expiresAt` | Description from `expiration.yaml` (optional; never in prod; up to `maxLifetimeDays` from creation, more needs one approver-platform approval) and `x-cmapi-expiration: {environments: {<env>: {enabled, allowedAtCreate, maxLifetimeDays, notifyDaysBefore, graceDays}}}` for each environment the instance serves (an unlisted one appears with `enabled: false`), so the portal's calendar reads its limits, and whether it is shown at all, from the contract. `expiration.yaml` gains `enabled` (default `true`); `prod: {enabled: false}` now loads, `prod: {enabled: true}` is refused | Additive |
| A10 | Kyverno bundle | Re-rendered from the new configuration (the new required keys, the prefix and suffix rules); delivered to `cmapi-cluster-configs` | Config repository |

Not changed: the path (`/api/v1/clusters/{cluster_id}/namespaces`), the headers (`Authorization`, `Idempotency-Key`),
`dryRun`, the extra-key rules and limits, tiers, quota, approvals, and the 202 answer (`ChangeRequest`).

### 4.3 The contract gate

`cmapi/contract/gate.sh` compares the new document with the base branch and the newest release (oasdiff). A1 is the
only breaking change. Its accepted lines name each filled-in key that became required. Clients already sending the
right value, or nothing, keep working: the server still fills a missing filled-in key.

---

## 5. The Swagger page: the clean look

The owner's reference shows the look, not fields to copy: every parameter on one row with its type and location, a
required marker, and the body with two tabs. The body's **Example Value** is one complete, realistic JSON request, and
**Model/Schema** lists every field with its type and format.

### 5.1 Parameters

| Name | Type | In | Required |
|---|---|---|---|
| `Authorization` | string | header | yes (the Authorize button: a Bearer token from Keycloak) |
| `Idempotency-Key` | string | header | yes, on writes |
| `cluster_id` | string, pattern `^[A-Z][A-Z0-9_]{1,62}$` | path | yes |
| `dryRun` | boolean | query | no |

### 5.2 Request body `NamespaceCreate` (required): Example Value

```json
{
  "namespace": "abc-payments-dev",
  "tier": "small",
  "justification": "Payments service dev namespace",
  "expiresAt": "2026-12-15",
  "labels": {
    "name": "abc-payments-dev",
    "company.net/app-environment": "dev",
    "company.net/mnemonic": "abc",
    "company.net/lob": "amgsst",
    "company.net/cl": "1",
    "cmapi.net/team": "payments",
    "cmapi.net/cost-center": "cc-4410",
    "team.company.net/squad": "checkout"
  },
  "annotations": {
    "company.net/app-environment": "dev",
    "cmapi.net/team-dl": "payments-team@company.net",
    "runbook.company.net/url": "https://wiki.company.net/abc/runbook"
  }
}
```

### 5.3 Request body: Model / Schema

```
NamespaceCreate {
  namespace*      string   DNS-1123 label, ≤ 63; <mnemonic>-<desired name>-<cluster env>   e.g. abc-payments-dev
  tier            string   a tier from the catalog, or custom                       default: small
  justification   string
  expiresAt       string($date)   optional; after today; never in prod; > 180 days from creation adds one approval
  quota           object   custom tier only
  limitRange      object   custom tier only
  labels* {
    name*                          string   = the namespace name (cmapi fills it in)
    company.net/app-environment*   string   = the cluster's environment (cmapi fills it in); the namespace name ends with it
    company.net/mnemonic*          string   ^[a-z]{3,4}$; the namespace name starts with it   e.g. abc
    company.net/lob*               string   free text, a valid label value                    e.g. amgsst
    company.net/cl*                string   enum [0, 1, 2, 3, 4, 5, 6]                        e.g. 1
    cmapi.net/team*                string   ^[a-z0-9-]{2,40}$; default: company.net/mnemonic e.g. payments
    cmapi.net/cost-center          string   ^cc-[0-9]{4}$                                     e.g. cc-4410
    cmapi.net/app                  string   ^[a-z0-9-]{2,40}$
    cmapi.net/rightsizing          string   enum [auto, manual]
    <other key>                    string   prefix "" or *.company.net/, at most 50
  }
  annotations* {
    company.net/app-environment*   string   = the cluster's environment (cmapi fills it in)
    cmapi.net/team-dl*             string($email)   in company.net         e.g. payments-team@company.net
    company.net/mnemonic-group-contact   string($email)   optional
    company.net/mnemonic-confluence      string($uri)     optional
    <other key>                    string   prefix "" or *.company.net/, at most 50
  }
}
```
`*` = required (shown in red as **required**).

### 5.4 Responses (every status and problem code of this operation, from cmapi's registry)

Each problem code is one **named example** of its status. Swagger UI shows them in its **Examples** dropdown and ReDoc in its example selector (their native controls; no plugin) (RFC 9457 `application/problem+json`, `type` linking to
`/problems/<code>`). The list is the live document's (CRC `/openapi.json`, 2026-11-20); the examples are adapted to the
new naming.

| Status | Codes | When |
|---|---|---|
| 200 | (the plan) | `?dryRun=true`: the plan; nothing is written |
| 202 | (the request) | The request is created and waits for approval |
| 400 | `idempotency-key-required` | No `Idempotency-Key` header on a write |
| 401 | `unauthenticated` | No token, or not valid |
| 403 | `forbidden`, `environment-forbidden` | The permission is missing, or held only in another environment |
| 404 | `cluster-not-found` | Unknown cluster |
| 409 | `change-pending`, `idempotency-replay`, `namespace-exists`, `namespace-exists-unmanaged` | Another request holds the namespace; the key was used for another body; the namespace is already in Git, or on the cluster and not cmapi's |
| 422 | `cluster-not-writable`, `environment-not-served`, `plugin-disabled`, `validation-failed`, `policy-violation`, `capacity-exceeded`, `no-change`, `identity-incomplete`, `unknown-user`, `invalid-team-dl`, `unknown-serviceaccount`, `reserved-namespace`, `invalid-namespace-name`, `expiration-not-allowed`, `expiration-in-past`, `on-behalf-of-not-allowed`, `on-behalf-of-required` | A rule is broken. Metadata refusals (the prefix, the suffix, a filled-in key, a pattern, a missing key, an extra key) are `policy-violation` with one entry per key in `errors` |
| 502 | `git-unavailable` | The Git host failed |
| 503 | `cluster-unreachable`, `validator-unavailable` | A dependency is not answering; retry later |

### 5.5 Extensions

Swagger UI shows the operation's `x-` fields in an **Extensions** section once `showExtensions: true` is set (today only `persistAuthorization` is set, `main.py:272`); `showCommonExtensions: true` also shows `pattern`, `maxLength` and `enum` on parameters:

| Field | Value |
|---|---|
| `x-cmapi-permission` | `namespaces:create` |
| `x-cmapi-plugin`, `x-plugin-version` | `namespaces`, `0.2.0` |
| `x-codeSamples` | a curl sample (toggle) |
| `namespace`: `x-cmapi-prefix-from` (NEW) | `company.net/mnemonic` |
| `namespace`: `x-cmapi-suffix-from` (NEW) | `company.net/app-environment` |
| `labels.name`, `…/app-environment`: `x-cmapi-derived-from` | `namespace`, `environment` (now required and shown) |
| `labels.cmapi.net/team`: `x-cmapi-default-from` (NEW) | `company.net/mnemonic` |
| `labels`, `annotations`: `x-cmapi-other-keys` | prefixes and limits of the extra keys |

---

## 6. Payload mocks

### 6.1 What the portal sends (create, after the check passes)

`POST /api/v1/clusters/CRC/namespaces` with `Authorization: Bearer …` and `Idempotency-Key: 6f1d…`

```json
{
  "namespace": "abc-payments-dev",
  "tier": "small",
  "justification": "Payments service dev namespace",
  "expiresAt": "2026-12-15",
  "labels": {
    "name": "abc-payments-dev",
    "company.net/app-environment": "dev",
    "company.net/mnemonic": "abc",
    "company.net/lob": "amgsst",
    "company.net/cl": "1",
    "cmapi.net/team": "payments",
    "cmapi.net/cost-center": "cc-4410",
    "team.company.net/squad": "checkout"
  },
  "annotations": {
    "company.net/app-environment": "dev",
    "cmapi.net/team-dl": "payments-team@company.net",
    "runbook.company.net/url": "https://wiki.company.net/abc/runbook"
  }
}
```

A minimal API client may send less: cmapi fills `name`, `company.net/app-environment` (both kinds) and, if left out,
`cmapi.net/team` from the mnemonic:

```json
{
  "namespace": "abc-payments-dev",
  "labels": { "company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1" },
  "annotations": { "cmapi.net/team-dl": "payments-team@company.net" }
}
```

### 6.2 The dry-run answer (`?dryRun=true`, 200), shortened

```json
{
  "planHash": "9c41…",
  "metadata": {
    "namespace": "abc-payments-dev",
    "labels": {
      "name":                        {"value": "abc-payments-dev", "source": "namespace"},
      "company.net/app-environment": {"value": "dev", "source": "environment"},
      "company.net/mnemonic":        {"value": "abc", "source": "request"},
      "company.net/lob":             {"value": "amgsst", "source": "request"},
      "company.net/cl":              {"value": "1", "source": "request"},
      "cmapi.net/team":              {"value": "abc", "source": "default:company.net/mnemonic"}
    },
    "annotations": {
      "company.net/app-environment": {"value": "dev", "source": "environment"},
      "cmapi.net/team-dl":           {"value": "payments-team@company.net", "source": "request"}
    }
  },
  "changes": { "clusters/CRC/namespaces/abc-payments-dev/namespace.yaml": "added" },
  "files": { "clusters/CRC/namespaces/abc-payments-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\n…" },
  "capacity": { "status": "fits" },
  "approval": { "rule": "dev-create", "remaining": [{"group": "approver-platform", "needed": 1}] },
  "findings": []
}
```

### 6.3 The create answer (202), shortened

```json
{
  "requestId": "req-20261120-0007",
  "status": "pending_approval",
  "plugin": "namespaces",
  "action": "create",
  "clusterId": "CRC",
  "env": "dev",
  "namespace": "abc-payments-dev",
  "planHash": "9c41…",
  "approval": { "rule": "dev-create", "remaining": [{"group": "approver-platform", "needed": 1}] },
  "links": { "self": "/api/v1/requests/req-20261120-0007" }
}
```

### 6.4 Refusals (422, RFC 9457)

```json
{
  "type": "https://cmapi.apps-crc.testing/problems/policy-violation",
  "title": "policy violation",
  "status": 422,
  "code": "policy-violation",
  "detail": "Metadata refused",
  "errors": [
    {"code": "invalid_value", "key": "company.net/mnemonic", "kind": "label", "detail": "payments-dev does not start with abc-"},
    {"code": "invalid_value", "key": "company.net/app-environment", "kind": "label", "detail": "abc-payments-rnd does not end with -dev (the cluster CRC is dev)"},
    {"code": "derived_key",   "key": "name", "kind": "label", "detail": "must equal the namespace name abc-payments-dev"},
    {"code": "invalid_value", "key": "company.net/cl", "kind": "label", "detail": "one of ['0', '1', '2', '3', '4', '5', '6']"},
    {"code": "missing_required_key", "key": "cmapi.net/team-dl", "kind": "annotation", "detail": "an address in ['company.net']"}
  ],
  "findings": []
}
```
(`policy-violation` is the registered code for a metadata refusal; each refused key is one entry in `errors`.)

---

## 7. The portal: New namespace request

### 7.1 The form

```
 New namespace ─────────────────────────────────────────────────────────────
  Cluster        [ CRC (dev)            ▾ ]
  Mnemonic *     [ abc ]                 3 or 4 lowercase letters
  Namespace *    ┌──────┬──────────────────────┬──────┐
                 │ abc- │ payments             │ -dev │   ← "abc-" from Mnemonic, "-dev" from the cluster: both locked
                 └──────┴──────────────────────┴──────┘
                 Will be created as: abc-payments-dev   (on an rnd cluster: abc-payments-rnd)
  Team *         [ abc ]  ← filled from Mnemonic; you can change it to "payments"
  Line of business * [ amgsst ]
  Critical level *   [ 1 ▾ ]   (0 to 6)
  Team DL *      [ payments-team@company.net ]
  Cost center    [ cc-4410 ]
  Tier           [ small ▾ ]
  Expires        [ 2026-12-15  📅 ]   in 25 days · notices at 14, 7, 1 days · 7 days' grace   [ No expiry ]
                 (calendar: from tomorrow; past 2027-05-19 = 180 days adds one approval; hidden on prod clusters)
  Justification  [ Payments service dev namespace ]

  ▸ Additional labels and annotations (optional) · none                        ← closed and empty by default

  ▾ Additional labels and annotations (optional)                               ← opened: still empty
    Additional labels                                                     0 of 50
    ┌──────────────────────────────┬──────────────────────────┬───┐
    │ Key                          │ Value                    │   │
    ├──────────────────────────────┴──────────────────────────┴───┤
    │ None. Add one only if you need it.                            │
    └───────────────────────────────────────────────────────────────┘
    [ + Add label ]    Allowed: no prefix, or *.company.net/

    Additional annotations                                    0 of 50 · 0 of 65536 bytes
    ┌──────────────────────────────┬──────────────────────────────────────────────┬───┐
    │ Key                          │ Value                                        │   │
    ├──────────────────────────────┴──────────────────────────────────────────────┴───┤
    │ None. Add one only if you need it.                                                │
    └───────────────────────────────────────────────────────────────────────────────────┘
    [ + Add annotation ]

  After "+ Add label", one empty row with placeholder text only (grey, not a value):
    │ e.g. team.company.net/squad  │ e.g. checkout            │ ✕ │

  ┌ Preview: what will be created (updates as you type) ────────────────────┐
  │ Namespace abc-payments-dev on CRC (dev)                                  │
  │   labels:      name=abc-payments-dev            (automatic)              │
  │                company.net/app-environment=dev  (automatic)              │
  │                company.net/mnemonic=abc  company.net/lob=amgsst          │
  │                company.net/cl=1  cmapi.net/team=payments                 │
  │   annotations: company.net/app-environment=dev  (automatic)              │
  │                cmapi.net/team-dl=payments-team@company.net               │
  │   additional:  (none)                                                    │
  │   expires: 2026-12-15 (in 25 days)                                       │
  │            writes cmapi.net/expires-at: "2026-12-15", cmapi.net/expiry: managed │
  │   quota: small        approval: 1 from approver-platform                 │
  └──────────────────────────────────────────────────────────────────────────┘
                                   [ Check (dry run) ]   [ Submit ] (off until the check passes)
```

### 7.2 Behaviour

| # | Behaviour |
|---|---|
| P1 | The form is built from `GET /api/v1/metadata-keys` (A5): fields, titles, rules, order. Nothing about a company is written in the portal's code |
| P2 | The key with `namespacePrefix` (Mnemonic) comes first. The Namespace field is a PatternFly input group: a locked prefix `<mnemonic>-`, an input for the desired name, and a locked suffix `-<cluster env>`. The prefix follows Mnemonic and the suffix follows the chosen cluster; the full name and its length (≤ 63) are shown under it |
| P3 | Filled-in keys (`name`, app environment) are shown, pre-filled and locked, marked "automatic" |
| P4 | A key with `default: {from: K}` (Team) copies K until the person edits it; after that a change of K leaves it alone |
| P5 | Each field checks its rule as you type (pattern, enum, email domain), in a Web Worker as today for patterns |
| P6 | The preview updates as you type, from the same rules as the API, and shows the final labels, annotations, quota and approval |
| P7 | **Check** runs the dry run; its answer replaces the preview (A7). **Submit** stays off until the check passes and is off again after any change, so nothing goes straight to submit |
| P8 | A refusal shows on its field (e.g. the cl field for `invalid_value` on `company.net/cl`) |
| P9 | **Additional labels and annotations** sit in one section that is **closed and empty by default**: no row and no value is pre-filled, so nothing wrong can be sent by accident; a new row has placeholder text only. a toggle (PatternFly ExpandableSection) titled "Additional labels and annotations (optional)", which shows the count of extra keys while closed. Open, it holds two separate key/value tables, Labels and Annotations, each with **Add** and a remove button per row |
| P10 | Each extra row is checked as you type against `propertyNames` and `additionalProperties` of `GET /api/v1/metadata-keys`, with counters from `x-cmapi-other-keys`: allowed prefix, key and value syntax, at most 50 per kind, annotation bytes. A key that has its own field above, a reserved key, a system key, an operator-only key and a duplicate are refused on their row |
| P12 | **Expires** is a date picker (PatternFly DatePicker), empty by default (= permanent). It opens a calendar from tomorrow; beside the date it shows "in N days". Past `maxLifetimeDays` it warns "needs one more approval" instead of refusing. Where the cluster's environment has expiration off (`enabled: false`, e.g. prod) the field is blank and hidden, with the line "Expiration is turned off for this environment". A **No expiry** button clears it. Limits come from `x-cmapi-expiration` (A11) |
| P11 | Extra keys are sent in the same `labels` and `annotations` maps, shown in the preview, and checked by the dry run; closing the section keeps them |

---

## 8. On CRC

Owner's decisions (2026-11-20):

| Item | Decision |
|---|---|
| Configuration | Use section 3.1 with `company.net` keys and `emailDomains: [ephico2real.com]` (the test users' domain); the Team DL example uses that email domain too |
| Namespace names | Follow the designed rule `<mnemonic>-<desired>-<env>`, for example `abc-payments-dev` on CRC (`dev`); no CRC-specific variant |
| Existing namespaces | Keep `cmapi-live-a` … `cmapi-live-f` as they are and report their missing keys and naming violations as findings; rename or delete nothing |
| `company.net/cl` in `sensitiveKeys` | Include it: a change of critical level needs one extra approver-platform approval |

---

## 9. Delivery

| Step | What | Proof |
|---|---|---|
| 1 | Loader and validation: `namespaceSuffix`, `default: {from: …}`, filled-in keys required (A1, A2, A3, A6, A8) | Service tests: fill, keep, refuse; a name that does not end with its own cluster's environment refused (`abc-payments-rnd` on a `dev` cluster). A name is checked against its target cluster only: `abc-payments-qa-dev` is valid on a `dev` cluster, with the desired name `payments-qa`; config refusals |
| 2 | Contract: schema, examples, `metadata-keys` (A1–A5, A7); accepted-breaking lines | Contract tests; oasdiff report; docs/04 regenerated |
| 3 | Portal form, preview and the extra-key section (P1–P11) | Browser checks at 390/820/1440 px, mutants, screenshots |
| 4 | CRC configuration (section 8), Kyverno bundle re-rendered to `cmapi-cluster-configs` (A9) | CRC deploy; Swagger and form screenshots through the Route |
| 5 | docs/02, docs/14 (if any permission), docs/18 | doc-citations clean |

---

## 10. Mockups

All three are claude.ai artifacts, private to the owner's account until shared from their Share menu.

| Mockup | Link | Shows |
|---|---|---|
| Portal: New namespace (`#new`) | https://claude.ai/artifact/3nDGzZm2ZJpSjKu4rRr1pb | The form (P1–P11): the Namespace field with the locked `<mnemonic>-` start and `-<cluster env>` end; Team copying Mnemonic until edited; the filled-in keys locked; checks as you type; the closed, empty "Additional labels and annotations" section with its two key/value tables; the live preview; Check (dry run) before Submit |
| ReDoc: the same operation | https://claude.ai/artifact/ECf6nW9rNXfym1qjMxjN8F | ReDoc's three columns: navigation by tag group; the schema with required marks and rules; every status, opening to its problem codes; request samples (Payload, curl) and response samples with a tab per status and an example selector; the extensions |
| Swagger: `POST /api/v1/clusters/{cluster_id}/namespaces` | https://claude.ai/artifact/2AYqUotuYe1qpPwCgDM1wP | The clean layout (section 5): parameters, request body with Example Value and Schema, every response status with each problem code as a toggle with its example (5.4), and the Extensions table (5.5) |

## 11. Decisions in the design discussion (2026-11-20)

| # | Decision |
|---|---|
| D1 | Keep the current keys (`cmapi.net/team`, `cmapi.net/team-dl`, the optional `cmapi.net/` keys) and add `name`, `company.net/app-environment`, `company.net/mnemonic`, `company.net/lob`, `company.net/cl` as required (R4) |
| D2 | The owner's reference Swagger gives the **format** only (typed fields, Example Value and Model/Schema tabs, required marks, filled examples); none of its fields are copied |
| D3 | The request keeps the real Kubernetes keys inside `labels` and `annotations`; extra keys go in the same maps |
| D4 | The name is `<mnemonic>-<desired name>-<cluster env>`; the API takes the full name and checks both ends; the portal locks both ends (R5, R6, R10) |
| D5 | Filled-in keys (`name`, app environment) are required and shown; cmapi still fills them when an API client leaves them out; a wrong value is refused (`derived_key`) |
| D6 | `cmapi.net/team` defaults to the mnemonic (`default: {from: …}`) and can be changed (R8) |
| D7 | The portal is reactive: live preview, Check (dry run) before Submit, Submit off again after any change (R7) |
| D8 | Additional labels and annotations are set in the portal in two key/value tables, inside a toggle section that is **closed and empty by default**, so nothing wrong is sent by accident (R11) |
| D9 | Every status and problem code of the operation is documented with its own example, behind a toggle, and the operation's `x-` fields in an Extensions table; the codes are cmapi's registry (create has no 428, which belongs to PATCH and DELETE without `If-Match`; a missing Idempotency-Key is 400; metadata refusals are `policy-violation`) |
| D10 | The configuration is the Helm value `metadata:`; nothing about a company is written in code (`company.net` and `cnn.com` in section 3) |

| D11 | An optional expiration date from a calendar; the form shows the date and the days until it (R12, P12, A11) |
| D12 | Problem examples use the native controls of Swagger UI (Examples dropdown) and ReDoc (example selector), not a custom plugin, so the code stays simple |
| D14 | Expiration has a per-environment `enabled` flag in `expiration.yaml`; production ships with it off (field blank and hidden); the #222 name check stays as a backstop. The date is written on the namespace as `cmapi.net/expires-at` with the label `cmapi.net/expiry: managed` |
| D15 | `maxLifetimeDays` is a **limit, never a default**: it never sets a date. Expiration stays optional: no `expiresAt` = a permanent namespace. Defaults belong to the caller (the portal or a ServiceNow form), which reads the rules from the contract (`GET /api/v1/metadata-keys`, `x-cmapi-expiration`) and sends the person's choice; cmapi only checks it. No `defaultLifetimeDays` is added |
| D13 | This format is the **standard for all 40 operations** in Swagger UI and ReDoc; the implementation plan is `swagger_redoc_implementation_plan.md` |

CRC's configuration, naming rule, existing namespace findings and sensitive critical-level key are decided in section 8.

