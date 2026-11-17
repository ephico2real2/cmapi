# #328: the labels and annotations of a namespace as schema fields

Design only. No code is changed by this pull request. OB1 run 18 (Opus 5.5 at `high`) wrote it on 2026-11-16, from
`origin/main` at `9ba33b2`. Every number below was measured on this Mac with no cluster, unless it says otherwise. The
measurement harness (scripts, full documents, all screenshots) is in
`/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run18/measure/`; the parts small enough to commit are in `evidence/`.

## 1. The decision, in short

- **Shape.** `labels` and `annotations` of `NamespaceCreate` and `NamespacePatch` become objects with `properties` (one
  per declared key, with its `pattern` or `enum`, `minLength`, `maxLength`, `description`, `examples`), `required` (the
  required keys that the requester sends, create only), `propertyNames` (which other keys `allowOther` admits) and
  `additionalProperties` (the value rule of those other keys). Derived keys stay in `properties` with `readOnly: true`.
  `labels` or `annotations` is in `NamespaceCreate.required` when its kind has a required key that the requester sends.
- **Why `propertyNames` and not `patternProperties` with `additionalProperties: false`.** Both are precise for a JSON
  Schema validator. Measured on generators: with `additionalProperties: false`, `datamodel-code-generator` 0.97.0 makes a
  model that refuses every extra key that cmapi accepts, and `openapi-python-client` 0.30.0 makes a class that cannot hold
  one. With `propertyNames`, both keep the extras. Swagger UI 5.34.1 shows `propertyNames`; ReDoc 3.1.0 does not, and
  the description already says the rule.
- **One source.** One new function, `MetadataKeys.json_schema(kind, op)` in `core/metadata.py`, builds each schema from
  the same `KeyRule` objects that `validate()` checks and `policygen` renders. A differential test runs one corpus of
  bodies through `validate()` and through the schema. Every body that `validate()` accepts must pass the schema
  (measured on the prototype: 0 failures in 2,652 bodies on four configurations).
- **Breaking by oasdiff's rules: yes, 14 lines**, all on the two namespace writes. The API's behaviour does not change:
  cmapi already refuses each of these bodies with 422. The 14 lines go in `accepted-breaking.txt`, before 1.0.
- **Drift found on main, to fix with this change:** the examples, the curl sample and Swagger UI's "Try it out" body
  of an instance with another configuration are bodies that instance refuses (measured), and the portal's form hard-codes
  `cmapi.net/team` and `cmapi.net/team-dl`.

## 2. What the issue asks

#328 (the owner, 2026-11-16: "You didn't put it in the Swagger"): on `9ba33b2`, `NamespaceCreate.labels` and
`.annotations` are free-form maps (`additionalProperties: {type: string}`), and the required keys are only in the
description. Fix: build the two schemas from the instance's metadata configuration, with a property per required and
optional key, its `pattern` (or the email form for DL keys), `required` for the required keys, and the extra keys still
allowed. `labels`/`annotations` are required on `NamespaceCreate` when any key is required. The served `/openapi.json`
reflects the instance's configuration; the committed contract shows the reference configuration. Proof: a contract test
(the reference `labels.required` contains `cmapi.net/team`, its pattern matches the validator's, and a JSON Schema
validator refuses a create without it) and a Swagger UI screenshot on CRC.

## 3. Discovery

### 3.1 Where each rule is enforced today

One file, `metadata-keys.yaml`, is loaded once (`core/config.py:91-97`) into a `MetadataKeys`
(`core/metadata.py:84-125`). Four consumers read it. They are not generated from one function each: each reads the
`KeyRule` objects in its own way.

| Rule | API plan (`metadata.py`) | Kyverno (`policygen.py`) | OpenAPI (`docs.py`) | Portal (`NewNamespaceTab.tsx`) |
|---|---|---|---|---|
| Key syntax (prefix DNS subdomain at most 253, name at most 63 of `[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?`) | `_syntax` `:307-311` | no | no | no |
| Label value syntax (at most 63, empty allowed) | `_syntax` `:312-313` | declared label keys only, `:178-181` | no | no |
| Required key present and not empty | `validate` `:284-293`; held for an existing namespace that already lacked it `:290-291` | `:169-170`, ratcheted by `_same` `:103-107` | prose only `docs.py:378-392` | two fixed fields, `:148-149`, `:200-202`, `:232-234` |
| `pattern` (Python `re.fullmatch`) | `_governed` `:338-339` | anchored `^(?:p)$` in RE2 `:112-114` | prose only | no |
| `enum` | `:340-341` | `:115-116` | prose only | no |
| `format: email-in-domains` (one `@`, a local part of the characters of `_LOCAL`, `identity/checks.py:26`, a domain in `emailDomains`, case-insensitive) | `:331-333`, `identity/checks.py:29-34` | `:117-123` | prose only | `type="email"` on the DL field only |
| `format: url` (http/https, a host, no whitespace) | `:334-337` | `:124-130` | prose only | no |
| `namespacePrefix` | `:342-344` | `:173-175` | prose only | no |
| Derived key (`value.from`): same value accepted, another or a removal refused | `:321-327`; filled by `derived` `:236-243` | `:153-166` | prose only | no |
| `allowOther` prefixes (`fnmatchcase` on the key's prefix; `""` = no prefix) | `classify` `:228-233` | **no** | prose only | no |
| `allowOther.max`, `maxValueBytes`, `maxBytesTotal` | `:296-304` | **no** | prose (max only) | no |
| System, reserved, adoption keys refused | `classify` `:217-230`, `validate` `:276-277` | **no** | no | no |
| `operatorOnly` (403 for a requester) | `:280-281`, `check` `:352-354` | **no** | no | no |
| A key of the other kind only is refused | `validate` `:270-275` | no | no | no |

Findings:

- **Kyverno checks a subset.** The rendered policies check the declared keys and the system-required ones; they do
  not check the `allowOther` prefixes, the limits, or the refused classes. That is a known boundary (plan time is the
  full check), not drift: the two agree on what both check (`test_policygen.py:217`,
  `test_python_and_kyverno_refuse_the_same_value`).
- **The portal does not read the configuration.** It sends `labels: {"cmapi.net/team": team}` and
  `annotations: {"cmapi.net/team-dl": dl}` (`NewNamespaceTab.tsx:148-149`). With the owner's company file, every create
  from the portal is refused (`cmapi.net/team` is outside `*.company.net/`, and three required keys are missing). This
  is drift today, independent of #328.
- **The pattern dialects differ.** The configuration's `pattern` is Python `re`; Kyverno's is RE2 (policygen anchors
  it); JSON Schema's is ECMA-262 (section 4.1 below). Measured in `evidence/runs/regex-dialect.txt`: on 11 generated
  patterns and 30 values, the only disagreement between Python `re.search` and Node `RegExp(p, "u")` is a trailing
  `\n` (Python's `$` matches before it). cmapi itself uses `fullmatch`, which refuses it, so ECMA agrees with cmapi.
  Python's `jsonschema` library uses `re.search` for `pattern`, so a Python-only test would not see this; the test in
  section 8 runs the patterns in an ECMA engine too.
- **Every shipped deployment has the reference keys.** The `requiredLabels` to `emailDomains` text of
  `deploy/helm/cmapi/config/metadata-keys.yaml` and the CRC ConfigMap (`deploy/manifests/environments/crc/20-config.yaml:338-371`)
  is byte-identical to `examples/cluster-configs/policies/metadata-keys.yaml` (md5 `06e46fa6…`), and the prototype's
  schemas for CRC and for the reference file are identical (`cmp`). The kind ConfigMap differs by one trailing blank
  line, and `examples/local/config/metadata-keys.yaml` by one comment.

### 3.2 How the OpenAPI document is produced

- **Served.** `main.py:178`: `build_openapi(app, plugins, public_url, problem_base, ctx.cfg.metadata)`, once per process,
  from this instance's configuration. `docs.py:351-375` builds FastAPI's document, then the curl samples
  (`:365-370`), then `_document_metadata` (`:372-373`, `:401-410`: the description of the four maps, and the examples
  of the two `NamespaceCreate` maps from `metadata_example`), then the recorded samples (`:374`, `:461-485`).
- **It already varies by instance.** Measured: the same app with the company file serves a document that differs from
  the reference in exactly four `description` fields and the two `NamespaceCreate` examples
  (`measure/served-company.json`, `measure/test_dump_served.py`). The `info.description` and the server URL also come
  from the instance.
- **Committed.** `cmapi/contract/openapi.json` is the document of the service suite's test instance, whose
  `metadata-keys.yaml` is the reference file (`tests/service/conftest.py:386`).
  `test_the_committed_contract_is_the_document_this_code_serves` (`test_api_docs.py:372-380`) keeps the two equal.
  Measured: the reference served document equals the committed contract byte for byte.
- **Gate.** `contract/gate.sh`: `oasdiff breaking --fail-on ERR --err-ignore accepted-breaking.txt <base> <head>`, on the
  committed file of the base branch and the head (oasdiff 1.37.0). It sees only the reference configuration. A change to
  an organisation's own `metadata-keys.yaml` never reaches it.
- **Lint.** `contract/lint.sh` (Spectral, cmapi's ruleset) runs on the committed file. `oas3-valid-media-example` checks
  each media example against its schema.
- **Samples.** `contract/samples.json` is a recording of the service suite (reference keys); `add_recorded_examples`
  puts each recorded request body into the operation's media `example`. `scripts/api-examples-doc.py` writes docs/04
  from the committed document and the samples.

**Drift measured on main**, with the company file (`measure/served-company.json`):

| Where | What it shows | The company instance |
|---|---|---|
| `POST …/namespaces` media `example` (recorded) | `labels: {cmapi.net/cost-center, cmapi.net/team}`, `annotations: {cmapi.net/team-dl}` | refuses it |
| `x-codeSamples` curl of the same operation | `labels: {cmapi.net/team}`, built before `_document_metadata` runs | refuses it |
| Swagger UI "Try it out" body | the recorded media `example` (measured in the pinned Swagger UI) | refuses it |
| `NamespacePatch.labels.examples` | `{cmapi.net/cost-center: cc-4410}`, fixed in `models.py:250` | refuses it |

### 3.3 How the pinned Swagger UI and ReDoc render each shape (measured)

Pins: Swagger UI 5.34.1 and ReDoc 3.1.0 (`cmapi/Containerfile:18-21`; the downloaded archives' SHA-256 match the pins).
Each candidate was put into a copy of the served document and rendered with the parameters FastAPI 0.115.6 passes
(`showExtensions`, `showCommonExtensions`, `deepLinking`, `persistAuthorization`), headless Chromium, through
`measure/shoot.mjs` and `measure/shoot-redoc.mjs`.

| Shape | Swagger UI 5.34.1 (request body, Schema tab) | ReDoc 3.1.0 |
|---|---|---|
| main: `additionalProperties: {type: string}` | "object", no keys (`swagger-main-create-schema.png`) | "object", "Show property" |
| `properties` + `required` | each key, a red `*` on required ones, `matches <pattern>`, `[1, 63] characters`, examples, `x-cmapi-*` under "Extension Keywords" | each key with "required", the pattern (cut, "Show pattern"), "non-empty", examples |
| `patternProperties` + `additionalProperties: false` | a row titled `/<regex>/` with its value rule, then "Additional properties forbidden" (`swagger-reference-patternProperties-create-schema.png`) | a row `labels.^(?:…)$` marked "pattern property" (`redoc-reference-patternProperties-create-2.png`) |
| `propertyNames` + `additionalProperties: <value rule>` | "Additional properties string ≤ 63 characters matches …" and "Property names: Any of: Enum […] / string matches …" (`swagger-reference-chosen-inline-create-schema.png`) | "`<property name>` string, additional property" only; **`propertyNames` is not shown** (`redoc-reference-propertyNames-create-2.png`) |
| `readOnly: true` (derived keys) | **not shown** in the request body (company: no `name`, no `company.net/app-environment`; `swagger-company-chosen-inline-create-schema.png`) | not shown in the request body |
| `maxProperties` | a badge "≤ 55 properties" (the bound counts declared keys too, so it reads as a wrong limit) | "<= 55 properties" |
| "Try it out" body | the media `example`, whatever the schema says | n/a |

### 3.4 What client generators make of each shape (measured)

| Generator | `patternProperties` + `false` | `propertyNames` + value rule | open map |
|---|---|---|---|
| openapi-typescript 7.13.0 (the portal's, `tools/openapi-types/package.json`) | `{ "cmapi.net/team": string; …optional } & { [key: string]: string }` | same | same |
| datamodel-code-generator 0.97.0, defaults | `extra='forbid'`: **refuses** `team.ephico2real.com/owner` and `owner`, which cmapi accepts; it warns "additionalProperties is false beside patternProperties, so the generated model rejects the keys the patterns admit" | `extra='allow'`, extras typed with the label-value rule: accepts what cmapi accepts, and also `other.example/x` (cmapi refuses) | accepts all |
| datamodel-code-generator, `--generate-schema-validators` | precise | ignores `propertyNames` | n/a |
| openapi-python-client 0.30.0 | **no `additional_properties`**: a caller cannot send an extra key | `additional_properties: dict[str, str]` | same |

Results: `evidence/runs/python-generators.txt`. For openapi-typescript, `readOnly` derived keys become `readonly … ?`,
and an `enum` becomes a union (`"company.net/cl": "0" | "1" | "2" | "3"`;
`evidence/runs/openapi-typescript-company-NamespaceCreate.ts`).

A config-driven form that holds `Record<string, string>` no longer compiles against the generated type once the
reference keys are required (`evidence/runs/tsc-dynamic-record.txt`: "Property '"cmapi.net/team"' is missing in type
'Record<string, string>'"). Section 10 deals with that.

## 4. Research

Read on 2026-11-16.

### 4.1 JSON Schema 2020-12 and OpenAPI 3.1

- Core, 10.3.2.2 `patternProperties`: "Each property name of this object SHOULD be a valid regular expression, according
  to the ECMA-262 regular expression dialect."
- Core, 10.3.2.3 `additionalProperties`: "Validation with "additionalProperties" applies only to the child values of
  instance names that do not appear" in `properties` or match `patternProperties`.
- Core, 10.3.2.4 `propertyNames`: "If the instance is an object, this keyword validates if every property name in the
  instance validates against the provided schema."
- Core, 11.3 `unevaluatedProperties`: like `additionalProperties`, but it also sees the properties that adjacent
  subschemas (`allOf`, `$ref`, …) evaluated.
- Validation, 6.3.3 `pattern`: "This string SHOULD be a valid regular expression, according to the ECMA-262 regular
  expression dialect." A pattern is not anchored.
- Validation, 6.5.3 `required`: valid "if every item in the array is the name of a property in the instance".
- Validation, 6.5.4 `dependentRequired`: a requirement that applies only when a named property is present.
- Validation, 9.4 `readOnly`: "attempts by an application to modify the value of this property are expected to be
  ignored or rejected" (an annotation; validators do not refuse it).
- Validation, 7.2.1: `format` as an assertion "MUST be disabled by default".
- OpenAPI 3.1.0, 4.4: the Schema Object "is a superset of JSON Schema Specification Draft 2020-12". 4.9: an extension
  field name "MUST begin with `x-`".

Sources: <https://json-schema.org/draft/2020-12/json-schema-core>, <https://json-schema.org/draft/2020-12/json-schema-validation>,
<https://spec.openapis.org/oas/v3.1.0>.

### 4.2 Kubernetes key and value syntax

- kubernetes.io, "Labels and Selectors", "Syntax and character set": "The name segment is required and must be 63
  characters or less, beginning and ending with an alphanumeric character (`[a-z0-9A-Z]`) with dashes (`-`), underscores
  (`_`), dots (`.`), and alphanumerics between. The prefix is optional. If specified, the prefix must be a DNS subdomain
  … not longer than 253 characters in total". A valid label value "must be 63 characters or less (can be empty), unless
  empty, must begin and end with an alphanumeric character … could contain dashes (`-`), underscores (`_`), dots (`.`),
  and alphanumerics between."
- kubernetes.io, "Annotations": the same key rule; "the total size of all annotations on a single object (keys and
  values combined) must not exceed 256 KiB"; values have no character-set restriction.
- `kubernetes/apimachinery` `pkg/api/validation/objectmeta.go`: `TotalAnnotationSizeLimitB int = 256 * (1 << 10)`;
  `ValidateAnnotations` checks `IsQualifiedName(strings.ToLower(k))`.

cmapi's `_DNS1123_SUB` and `_NAME` (`metadata.py:32-33`) are these rules. The schema's key and value patterns in
section 6 are the same rules in ECMA-262; the prefix length (253) is left to the server, so the schema accepts a
superset there.

### 4.3 Publishing a schema that depends on configuration

- The Kubernetes API server serves its own document: "The Kubernetes API server serves an aggregated OpenAPI v2 spec via
  the `/openapi/v2` endpoint", and the document "also includes any extensibility components that a cluster supports"
  (kubernetes.io, "The Kubernetes API"). CRD schemas "are published as OpenAPI v3 and OpenAPI v2 from Kubernetes API
  server" (kubernetes.io, "Extend the Kubernetes API with CustomResourceDefinitions", "Publish Validation Schema in
  OpenAPI"). So each cluster serves the schema of what it has installed; clients that need it (`kubectl explain`) read
  that cluster's document. cmapi's served `/openapi.json` per instance is the same pattern, and it is already in place.
- oasdiff compares two documents, not configurations. `contract/README.md` quotes its `docs/BREAKING-CHANGES.md`:
  "Errors are definite breaking changes which should be avoided".

### 4.4 Options rejected

| Option | Why not |
|---|---|
| Leave the maps open and keep the prose (main) | The issue: Swagger UI shows no fields, and generators and validators know nothing of the required keys |
| `properties` + `required` + `additionalProperties: {type: string}` only | No rule for the other keys' names or values; a validator accepts `kubernetes.io/x`, which cmapi refuses |
| `patternProperties` + `additionalProperties: false` | Precise and shown by both renderers, but two common Python generators break extras by default (3.4); and oasdiff 1.37.0 does not report the move to `additionalProperties: false` at all (measured: no line for it in `evidence/runs/oasdiff-candidate-patternProperties.txt`), so a later change would pass the gate unseen |
| `unevaluatedProperties` | Same as `additionalProperties` when nothing composes the schema; less tool support; no gain |
| `dependentRequired` | No rule of the configuration makes one key required only when another is present |
| `maxProperties` for `allowOther.max` | The limit counts only the other keys; a bound on all keys is either wrong or loose, and Swagger UI shows it as the limit ("≤ 55 properties", measured). The limit stays in the description and in `x-cmapi-other-keys` |
| `format: email` for `email-in-domains` | cmapi accepts local parts such as `.a` and `a..b` that the RFC 5321 dot-string form refuses; a client that asserts `format: email` would refuse a body that cmapi accepts. A `pattern` with the domains is exact |
| `format: uri` for `url` | cmapi accepts what `urlsplit` takes with an http or https scheme and a host (`metadata.py:334-337`), which includes non-ASCII characters and a stray `%` that RFC 3986 does not allow (from the code; not measured); a client that asserts `format: uri` would refuse those. A prefix `pattern` is sound, and `x-cmapi-format: url` names the rule |
| Named components (`NamespaceCreateLabels`, …) referenced from the four properties | oasdiff 1.37.0 then compares the PATCH map's `anyOf` by identity and reports "removed `subschema #1`" and nothing of the patterns or `propertyNames` inside (measured, `evidence/runs/oasdiff-candidate-propertyNames.txt`: the candidates were measured as named components); Spectral's `cmapi-net-keys-only-in-labels` flags the components' examples (measured, 2 errors, on `measure/doc-reference-chosen.json`). Inline schemas keep FastAPI's titles (`Labels`, `Annotations`) and give the gate one line per real change |
| A static, configuration-free contract (no keys in the committed document) | The committed document is the reference instance's served document by design (`test_api_docs.py:372`); the issue asks for the reference keys there |
| `type: ["string", "null"]` for the nullable PATCH values | oasdiff reports it as "list-of-types was narrowed by removing types `null`" against FastAPI's `anyOf` form (measured). `anyOf: [{…}, {type: null}]` is what FastAPI writes everywhere else |

## 5. The rule-to-schema map

`MetadataKeys.json_schema(kind, op)` (new, `core/metadata.py`, beside `KeyRule.text` so the words and the schema of a
rule live together). Inputs: the loaded `MetadataKeys` (its `rules`, `allow_other`, `system`, `operator_only`,
`reserved_prefixes`, `adoption_labels`, `email_domains`), the kind (`label` | `annotation`), and the operation
(`create` | `patch`). Output: one JSON Schema object. `docs._document_metadata` puts it under
`NamespaceCreate.properties.<field>` (create) or `NamespacePatch.properties.<field>.anyOf[0]` (patch), keeps the
current `title`, `description` and `examples`, and adds the field to `NamespaceCreate.required` when the schema has a
`required` list.

| Configuration | Schema |
|---|---|
| A key of `requiredLabels`/`requiredAnnotations` without `value` | in `properties` and in `required` (create); `minLength: 1` (empty counts as missing, `metadata.py:287`); on PATCH not nullable (sending `null` removes it, which cmapi refuses) |
| A key of `extraLabels.keys`/`extraAnnotations.keys` | in `properties`; on PATCH `anyOf: [<rule>, {type: null}]` |
| `pattern: P` | `pattern: "^(?:P)$"`, as policygen anchors it for RE2 (`policygen.py:114`) |
| `enum` | `enum` |
| `format: email-in-domains` | a `pattern`: `^`, the character class of `_LOCAL` (`identity/checks.py:26`) with `+`, `@`, then one of the domains and `$`, each ASCII letter of a domain written `[xX]` (JSON Schema's ECMA-262 has no `(?i)`); plus `x-cmapi-format: email-in-domains`. Section 6 has it written out |
| `format: url` | `pattern: "^[Hh][Tt][Tt][Pp][Ss]?://[^/?#]+"` (sound: it accepts a URL with whitespace, which cmapi refuses), plus `x-cmapi-format: url` |
| No value rule | a label: the label-value pattern; an annotation: any string |
| Any label key | `maxLength: 63` |
| `namespacePrefix: true` | `x-cmapi-namespace-prefix: true` and a sentence in the description. JSON Schema 2020-12 has no comparison between two values |
| `value: {from: …}` (derived) | in `properties`, `readOnly: true`, `x-cmapi-derived-from`, the label-value pattern for a label; never in `required`. It stays in `properties` so a client that sends back what it read (the same value, accepted by `metadata.py:323-324`) is not refused by the schema |
| `operatorOnly` keys | in `properties` of both kinds (cmapi accepts them in either, `classify` `:219-220`), `x-cmapi-operator-only: true`. A schema cannot know the caller's role |
| `description`, `example` of a rule | `description`, `examples: [example]` |
| `allowOther.prefixes` | `propertyNames: {anyOf: [{enum: <declared keys>}, <other keys>]}`, where `<other keys>` is the ECMA pattern of the prefixes (`""` = a key with no prefix; `*` = `[a-z0-9.-]*`; a glob that matches the empty string, such as `*`, also admits keys with no prefix, as `fnmatchcase("", "*")` does) |
| What `classify` refuses first, when a prefix admits it | `<other keys>` becomes `{allOf: [<pattern>, {not: {anyOf: [{enum: <system, adoption and other-kind-only keys the pattern matches>}, {pattern: <reserved prefixes whose glob meets an allowOther glob>}]}}]}`. Only what the prefixes could admit is listed, so the reference file gets no exclusion at all |
| The value of another key | `additionalProperties`: a label: the label-value pattern and `maxLength: 63`; an annotation: `maxLength: <maxValueBytes>` (a character count is at most the byte count, so this is sound); PATCH: `anyOf` with `null` |
| `allowOther.max`, `maxBytesTotal` | not expressible; in the description (as today) and `x-cmapi-other-keys: {prefixes, max, maxValueBytes, maxBytesTotal}` |

What stays loose, by design: a requester sending an operator-only key (a role), a derived key with another value and a
`namespacePrefix` mismatch (both compare two values), more than `allowOther.max` other keys, and other annotations
over `maxBytesTotal` together (both count only some keys).

## 6. The schemas in full

Generated by the prototype from the real loader (`measure/proto/schema_chosen.py`, not for the repository), not typed
by hand. The JSON files are `evidence/schemas/reference-and-crc.json` and `evidence/schemas/company.json`; the two
documents with them in place are `evidence/samples/`.

### 6.1 The reference configuration, which is also CRC's (measured identical)

`NamespaceCreate.labels` (`NamespaceCreate.required` becomes `["annotations", "labels", "namespace"]`):

```json
{
  "type": "object",
  "properties": {
    "cmapi.net/team": {
      "type": "string",
      "description": "Ownership and cost; any team, not checked against the caller",
      "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
      "maxLength": 63,
      "minLength": 1,
      "examples": [
        "payments"
      ]
    },
    "cmapi.net/cost-center": {
      "type": "string",
      "pattern": "^(?:^cc-[0-9]{4}$)$",
      "maxLength": 63,
      "examples": [
        "cc-4410"
      ]
    },
    "cmapi.net/app": {
      "type": "string",
      "description": "Links an app's environments",
      "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
      "maxLength": 63
    },
    "cmapi.net/rightsizing": {
      "type": "string",
      "description": "Opt-in to automatic rnd and qa decreases",
      "pattern": "^(?:^(auto|manual)$)$",
      "maxLength": 63
    },
    "cmapi.net/protected": {
      "type": "string",
      "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
      "maxLength": 63,
      "description": "cmapi-operator and above only; a requester gets 403",
      "x-cmapi-operator-only": true
    }
  },
  "required": [
    "cmapi.net/team"
  ],
  "propertyNames": {
    "anyOf": [
      {
        "enum": [
          "cmapi.net/team",
          "cmapi.net/cost-center",
          "cmapi.net/app",
          "cmapi.net/rightsizing",
          "cmapi.net/protected"
        ]
      },
      {
        "pattern": "^(?:(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)|(?:[a-z0-9.-]*\\.ephico2real\\.com/[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?))$"
      }
    ]
  },
  "additionalProperties": {
    "type": "string",
    "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
    "maxLength": 63
  },
  "x-cmapi-other-keys": {
    "prefixes": [
      "",
      "*.ephico2real.com/"
    ],
    "max": 50
  }
}
```

`NamespaceCreate.annotations`:

```json
{
  "type": "object",
  "properties": {
    "cmapi.net/team-dl": {
      "type": "string",
      "description": "The team's mail list, an address in one of emailDomains",
      "pattern": "^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[eE][pP][hH][iI][cC][oO]2[rR][eE][aA][lL]\\.[cC][oO][mM])$",
      "x-cmapi-format": "email-in-domains",
      "minLength": 1,
      "examples": [
        "payments-team@ephico2real.com"
      ]
    },
    "cmapi.net/protected": {
      "type": "string",
      "description": "cmapi-operator and above only; a requester gets 403",
      "x-cmapi-operator-only": true
    }
  },
  "required": [
    "cmapi.net/team-dl"
  ],
  "propertyNames": {
    "anyOf": [
      {
        "enum": [
          "cmapi.net/team-dl",
          "cmapi.net/protected"
        ]
      },
      {
        "pattern": "^(?:(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)|(?:[a-z0-9.-]*\\.ephico2real\\.com/[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?))$"
      }
    ]
  },
  "additionalProperties": {
    "type": "string",
    "maxLength": 4096
  },
  "x-cmapi-other-keys": {
    "prefixes": [
      "",
      "*.ephico2real.com/"
    ],
    "max": 50,
    "maxValueBytes": 4096,
    "maxBytesTotal": 65536
  }
}
```

`NamespacePatch.labels` (this object is `anyOf[0]`; `anyOf[1]` stays `{"type": "null"}`):

```json
{
  "type": "object",
  "properties": {
    "cmapi.net/team": {
      "type": "string",
      "description": "Ownership and cost; any team, not checked against the caller",
      "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
      "maxLength": 63,
      "minLength": 1,
      "examples": [
        "payments"
      ]
    },
    "cmapi.net/cost-center": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^(?:^cc-[0-9]{4}$)$",
          "maxLength": 63
        },
        {
          "type": "null"
        }
      ],
      "examples": [
        "cc-4410"
      ]
    },
    "cmapi.net/app": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
          "maxLength": 63
        },
        {
          "type": "null"
        }
      ],
      "description": "Links an app's environments"
    },
    "cmapi.net/rightsizing": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^(?:^(auto|manual)$)$",
          "maxLength": 63
        },
        {
          "type": "null"
        }
      ],
      "description": "Opt-in to automatic rnd and qa decreases"
    },
    "cmapi.net/protected": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
          "maxLength": 63
        },
        {
          "type": "null"
        }
      ],
      "description": "cmapi-operator and above only; a requester gets 403",
      "x-cmapi-operator-only": true
    }
  },
  "propertyNames": {
    "anyOf": [
      {
        "enum": [
          "cmapi.net/team",
          "cmapi.net/cost-center",
          "cmapi.net/app",
          "cmapi.net/rightsizing",
          "cmapi.net/protected"
        ]
      },
      {
        "pattern": "^(?:(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)|(?:[a-z0-9.-]*\\.ephico2real\\.com/[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?))$"
      }
    ]
  },
  "additionalProperties": {
    "anyOf": [
      {
        "type": "string",
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "maxLength": 63
      },
      {
        "type": "null"
      }
    ]
  },
  "x-cmapi-other-keys": {
    "prefixes": [
      "",
      "*.ephico2real.com/"
    ],
    "max": 50
  }
}
```

`NamespacePatch.annotations`:

```json
{
  "type": "object",
  "properties": {
    "cmapi.net/team-dl": {
      "type": "string",
      "description": "The team's mail list, an address in one of emailDomains",
      "pattern": "^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[eE][pP][hH][iI][cC][oO]2[rR][eE][aA][lL]\\.[cC][oO][mM])$",
      "x-cmapi-format": "email-in-domains",
      "minLength": 1,
      "examples": [
        "payments-team@ephico2real.com"
      ]
    },
    "cmapi.net/protected": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "description": "cmapi-operator and above only; a requester gets 403",
      "x-cmapi-operator-only": true
    }
  },
  "propertyNames": {
    "anyOf": [
      {
        "enum": [
          "cmapi.net/team-dl",
          "cmapi.net/protected"
        ]
      },
      {
        "pattern": "^(?:(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)|(?:[a-z0-9.-]*\\.ephico2real\\.com/[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?))$"
      }
    ]
  },
  "additionalProperties": {
    "anyOf": [
      {
        "type": "string",
        "maxLength": 4096
      },
      {
        "type": "null"
      }
    ]
  },
  "x-cmapi-other-keys": {
    "prefixes": [
      "",
      "*.ephico2real.com/"
    ],
    "max": 50,
    "maxValueBytes": 4096,
    "maxBytesTotal": 65536
  }
}
```

### 6.2 The owner's company configuration (`metadata-keys.company.yaml`)

`NamespaceCreate.required` becomes `["labels", "namespace"]`: the only required annotation is derived.

`NamespaceCreate.labels`:

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "A copy of the namespace name. Set by cmapi from the namespace; a request may send the same value, never another",
      "readOnly": true,
      "x-cmapi-derived-from": "namespace",
      "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
      "maxLength": 63
    },
    "company.net/app-environment": {
      "type": "string",
      "description": "The environment of the namespace's cluster. Set by cmapi from the environment; a request may send the same value, never another",
      "readOnly": true,
      "x-cmapi-derived-from": "environment",
      "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
      "maxLength": 63
    },
    "company.net/mnemonic": {
      "type": "string",
      "description": "The team's mnemonic: the start of the namespace name. The namespace name must start with this value and a '-'",
      "pattern": "^(?:^[a-z]{3}$)$",
      "maxLength": 63,
      "minLength": 1,
      "x-cmapi-namespace-prefix": true,
      "examples": [
        "abc"
      ]
    },
    "company.net/lob": {
      "type": "string",
      "description": "Line of business",
      "enum": [
        "amgsst"
      ],
      "maxLength": 63,
      "minLength": 1,
      "examples": [
        "amgsst"
      ]
    },
    "company.net/cl": {
      "type": "string",
      "description": "Critical level",
      "enum": [
        "0",
        "1",
        "2",
        "3"
      ],
      "maxLength": 63,
      "minLength": 1,
      "examples": [
        "1"
      ]
    },
    "cmapi.net/protected": {
      "type": "string",
      "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
      "maxLength": 63,
      "description": "cmapi-operator and above only; a requester gets 403",
      "x-cmapi-operator-only": true
    }
  },
  "required": [
    "company.net/mnemonic",
    "company.net/lob",
    "company.net/cl"
  ],
  "propertyNames": {
    "anyOf": [
      {
        "enum": [
          "name",
          "company.net/app-environment",
          "company.net/mnemonic",
          "company.net/lob",
          "company.net/cl",
          "cmapi.net/protected"
        ]
      },
      {
        "pattern": "^(?:(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)|(?:[a-z0-9.-]*\\.company\\.net/[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?))$"
      }
    ]
  },
  "additionalProperties": {
    "type": "string",
    "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
    "maxLength": 63
  },
  "x-cmapi-other-keys": {
    "prefixes": [
      "",
      "*.company.net/"
    ],
    "max": 50
  }
}
```

`NamespaceCreate.annotations`:

```json
{
  "type": "object",
  "properties": {
    "company.net/app-environment": {
      "type": "string",
      "readOnly": true,
      "description": "Set by cmapi from the environment; a request may send the same value, never another",
      "x-cmapi-derived-from": "environment"
    },
    "company.net/mnemonic-group-contact": {
      "type": "string",
      "description": "The mnemonic's group contact",
      "pattern": "^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[cC][oO][mM][pP][aA][nN][yY]\\.[nN][eE][tT])$",
      "x-cmapi-format": "email-in-domains",
      "examples": [
        "abc-team@company.net"
      ]
    },
    "company.net/mnemonic-confluence": {
      "type": "string",
      "description": "The mnemonic's Confluence space",
      "pattern": "^[Hh][Tt][Tt][Pp][Ss]?://[^/?#]+",
      "x-cmapi-format": "url",
      "examples": [
        "https://wiki.company.net/abc"
      ]
    },
    "cmapi.net/protected": {
      "type": "string",
      "description": "cmapi-operator and above only; a requester gets 403",
      "x-cmapi-operator-only": true
    }
  },
  "propertyNames": {
    "anyOf": [
      {
        "enum": [
          "company.net/app-environment",
          "company.net/mnemonic-group-contact",
          "company.net/mnemonic-confluence",
          "cmapi.net/protected"
        ]
      },
      {
        "allOf": [
          {
            "pattern": "^(?:(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)|(?:[a-z0-9.-]*\\.company\\.net/[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?))$"
          },
          {
            "not": {
              "anyOf": [
                {
                  "enum": [
                    "name"
                  ]
                }
              ]
            }
          }
        ]
      }
    ]
  },
  "additionalProperties": {
    "type": "string",
    "maxLength": 4096
  },
  "x-cmapi-other-keys": {
    "prefixes": [
      "",
      "*.company.net/"
    ],
    "max": 50,
    "maxValueBytes": 4096,
    "maxBytesTotal": 65536
  }
}
```

`NamespacePatch.labels`:

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "A copy of the namespace name. Set by cmapi from the namespace; a request may send the same value, never another",
      "readOnly": true,
      "x-cmapi-derived-from": "namespace",
      "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
      "maxLength": 63
    },
    "company.net/app-environment": {
      "type": "string",
      "description": "The environment of the namespace's cluster. Set by cmapi from the environment; a request may send the same value, never another",
      "readOnly": true,
      "x-cmapi-derived-from": "environment",
      "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
      "maxLength": 63
    },
    "company.net/mnemonic": {
      "type": "string",
      "description": "The team's mnemonic: the start of the namespace name. The namespace name must start with this value and a '-'",
      "pattern": "^(?:^[a-z]{3}$)$",
      "maxLength": 63,
      "minLength": 1,
      "x-cmapi-namespace-prefix": true,
      "examples": [
        "abc"
      ]
    },
    "company.net/lob": {
      "type": "string",
      "description": "Line of business",
      "enum": [
        "amgsst"
      ],
      "maxLength": 63,
      "minLength": 1,
      "examples": [
        "amgsst"
      ]
    },
    "company.net/cl": {
      "type": "string",
      "description": "Critical level",
      "enum": [
        "0",
        "1",
        "2",
        "3"
      ],
      "maxLength": 63,
      "minLength": 1,
      "examples": [
        "1"
      ]
    },
    "cmapi.net/protected": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
          "maxLength": 63
        },
        {
          "type": "null"
        }
      ],
      "description": "cmapi-operator and above only; a requester gets 403",
      "x-cmapi-operator-only": true
    }
  },
  "propertyNames": {
    "anyOf": [
      {
        "enum": [
          "name",
          "company.net/app-environment",
          "company.net/mnemonic",
          "company.net/lob",
          "company.net/cl",
          "cmapi.net/protected"
        ]
      },
      {
        "pattern": "^(?:(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)|(?:[a-z0-9.-]*\\.company\\.net/[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?))$"
      }
    ]
  },
  "additionalProperties": {
    "anyOf": [
      {
        "type": "string",
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "maxLength": 63
      },
      {
        "type": "null"
      }
    ]
  },
  "x-cmapi-other-keys": {
    "prefixes": [
      "",
      "*.company.net/"
    ],
    "max": 50
  }
}
```

`NamespacePatch.annotations`:

```json
{
  "type": "object",
  "properties": {
    "company.net/app-environment": {
      "type": "string",
      "readOnly": true,
      "description": "Set by cmapi from the environment; a request may send the same value, never another",
      "x-cmapi-derived-from": "environment"
    },
    "company.net/mnemonic-group-contact": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[cC][oO][mM][pP][aA][nN][yY]\\.[nN][eE][tT])$",
          "x-cmapi-format": "email-in-domains"
        },
        {
          "type": "null"
        }
      ],
      "description": "The mnemonic's group contact",
      "examples": [
        "abc-team@company.net"
      ]
    },
    "company.net/mnemonic-confluence": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^[Hh][Tt][Tt][Pp][Ss]?://[^/?#]+",
          "x-cmapi-format": "url"
        },
        {
          "type": "null"
        }
      ],
      "description": "The mnemonic's Confluence space",
      "examples": [
        "https://wiki.company.net/abc"
      ]
    },
    "cmapi.net/protected": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "description": "cmapi-operator and above only; a requester gets 403",
      "x-cmapi-operator-only": true
    }
  },
  "propertyNames": {
    "anyOf": [
      {
        "enum": [
          "company.net/app-environment",
          "company.net/mnemonic-group-contact",
          "company.net/mnemonic-confluence",
          "cmapi.net/protected"
        ]
      },
      {
        "allOf": [
          {
            "pattern": "^(?:(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)|(?:[a-z0-9.-]*\\.company\\.net/[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?))$"
          },
          {
            "not": {
              "anyOf": [
                {
                  "enum": [
                    "name"
                  ]
                }
              ]
            }
          }
        ]
      }
    ]
  },
  "additionalProperties": {
    "anyOf": [
      {
        "type": "string",
        "maxLength": 4096
      },
      {
        "type": "null"
      }
    ]
  },
  "x-cmapi-other-keys": {
    "prefixes": [
      "",
      "*.company.net/"
    ],
    "max": 50,
    "maxValueBytes": 4096,
    "maxBytesTotal": 65536
  }
}
```

## 7. The examples, the curl sample and "Try it out"

All three must be bodies that this instance accepts, and Spectral's `oas3-valid-media-example` now checks it: with the
new schemas and the recorded example left as it is, the company document has 4 errors
(`evidence/runs/spectral-company-served-after.txt`).

1. `build_openapi` runs `_document_metadata` before it builds the curl samples, so `sample_request` reads the
   instance's examples (today it runs after, `docs.py:365-373`).
2. `add_recorded_examples` keeps a recorded request body only when this instance's `MetadataKeys.validate` accepts its
   `labels` and `annotations`; otherwise it replaces those two maps with `metadata_example` (create) or with a patch
   example from the first optional key that has an `example` (patch). The reference instance keeps its recordings, so
   the committed contract's examples and docs/04 do not change.
3. `NamespacePatch.labels.examples` comes from the same patch example, not `models.py:250`. For the reference file it is
   `{"cmapi.net/cost-center": "cc-4410"}`, as today.

## 8. One source, and the test that fails on drift

| Consumer | Source after this change |
|---|---|
| API plan | `MetadataKeys.validate` (unchanged) |
| Kyverno | `policygen._metadata_checks` over `keys.rules` (unchanged) |
| OpenAPI | `MetadataKeys.json_schema` over the same `rules`, `allow_other` and classes |
| Portal | today hard-coded; see section 10 |

The tests:

- **Differential (the drift test).** `tests/core/test_metadata_schema.py`: for each of the reference file, the company
  file, and two synthetic files (company with `allowOther: ["", "company.net/"]`, the F2 case of PR #234; reference
  with `allowOther: ["", "*"]` and `["*"]`), one corpus: each declared key at good, bad, empty, too-long and
  case-changed values, `null` on PATCH, each required key left out, and 20 other keys (allowed, refused prefixes,
  reserved, system, adoption, other-kind-only, bad syntax). For each body: if `validate()` accepts it, the schema must
  accept it (soundness); if the schema accepts and `validate()` refuses, the only allowed refusal codes are
  `operator_only_key`, `derived_key`, a `namespacePrefix` `invalid_value`, and the two count limits `too_many_keys` and
  a total-size `annotations_too_large` (precision; the corpus adds a case for each). Measured on the prototype:
  2,652 bodies (603 reference, 723 company, 723 and 603 synthetic), 0 unsound; 2,410 agree exactly, and the 242 loose
  ones are all `operator_only_key` or `derived_key`
  (`evidence/runs/differential-*.txt`). The first run on the `"*"` file found 16 unsound cases (`fnmatchcase("", "*")`
  is true), fixed in the prototype; that is the kind of drift this test is for. On main's open maps the same corpus
  (reference file) gives 100 agreeing and 503 loose cases, among them `missing_required_key`, `invalid_value`,
  `invalid_key` and `reserved_key` (`evidence/runs/differential-main-schema.txt`), so the precision half fails.
- **ECMA dialect.** The same corpus through each generated pattern in Node (`new RegExp(p, "u")`, as Ajv uses) and
  Python `re.fullmatch`; they must agree. A run in the contract CI job, which already has Node for Spectral.
- **Kyverno agreement** stays `test_policygen.py:217`.

## 9. The contract gate

The change is breaking by oasdiff 1.37.0's rules. Measured with the gate's own command on the committed contract and the
reference document with the new schemas (`evidence/runs/oasdiff-chosen.txt`): 14 errors, and with these 14 lines added
to `accepted-breaking.txt`, `gate.sh` returns 0 (`evidence/runs/accepted-breaking-proposed.txt`):

```
POST /api/v1/clusters/{cluster_id}/namespaces added the new required request property `annotations/cmapi.net/team-dl`
POST /api/v1/clusters/{cluster_id}/namespaces added the new required request property `labels/cmapi.net/team`
POST /api/v1/clusters/{cluster_id}/namespaces the request property `annotations` became required
POST /api/v1/clusters/{cluster_id}/namespaces the request property `labels` became required
POST /api/v1/clusters/{cluster_id}/namespaces the `annotations/additionalProperties` request property's maxLength was set to `4096`
POST /api/v1/clusters/{cluster_id}/namespaces the `labels/additionalProperties` request property's maxLength was set to `63`
POST /api/v1/clusters/{cluster_id}/namespaces added the pattern `^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$` to the request property `labels/additionalProperties`
POST /api/v1/clusters/{cluster_id}/namespaces added 'propertyNames' constraint to the request property `annotations`
POST /api/v1/clusters/{cluster_id}/namespaces added 'propertyNames' constraint to the request property `labels`
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} the `annotations/anyOf[subschema #1]/additionalProperties/anyOf[subschema #1]` request property's maxLength was set to `4096`
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} the `labels/anyOf[subschema #1]/additionalProperties/anyOf[subschema #1]` request property's maxLength was set to `63`
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} added the pattern `^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$` to the request property `labels/anyOf[subschema #1]/additionalProperties/anyOf[subschema #1]`
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} added 'propertyNames' constraint to the request property `annotations/anyOf[subschema #1]`
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} added 'propertyNames' constraint to the request property `labels/anyOf[subschema #1]`
```

These are the lines oasdiff printed on the prototype; the implementer copies the lines it prints on the real head, as
`contract/README.md` says.

Reason line for the file: "#328, before the first release: the labels and annotations of the namespace writes now
carry the rules of metadata-keys.yaml as schema. cmapi already refused each body these rules refuse (422
policy-violation); only the document changes." Each rule is a rule cmapi already applied: the change makes the document
tell the truth, it does not refuse a body that was accepted. A body sent without `labels` is still read by FastAPI as
`{}` and refused by the metadata check, as today, so the 422 code a client sees does not change.

Other gates: the Spectral lint passes on the new reference document (measured, `lint.sh`, 0 problems). The new
optional properties, with their patterns, are INFO in oasdiff (`new-optional-request-property`, measured with
`oasdiff changelog`), so they are not in the list. A change to an organisation's own `metadata-keys.yaml` never reaches this gate (section 11, question 3).

docs/04: the committed contract's recorded examples do not change (section 7), so `api-examples-doc.py --check` is
expected to pass unchanged; the implementer proves it.

## 10. The portal

The New namespace form does not read the schema, `/me` or the configuration. It has a fixed Team field and a fixed Team
DL field (`NewNamespaceTab.tsx:83`, `:87`, `:148-149`, `:200-202`, `:232-234`), and its types come from the committed
contract through openapi-typescript (`scripts/api-types.mjs`).

After this change, with no portal change: `npm run api:types` regenerates `schema.generated.ts` with
`labels: { "cmapi.net/team": string; … } & { [key: string]: string }`. The form's literal body still compiles. The form
still sends only the two reference keys, so on an instance with other keys it is refused, as today.

The form built from the configuration is its own piece of work, and this design does not build it:

- It cannot read `/openapi.json`: `docs.enabled: false` turns that route off (`main.py:116`, `:183`), and the document
  is large. It needs the same schemas from an API route that the portal can always call.
- Its body type must be `Omit<NamespaceCreate, "labels" | "annotations"> & { labels: Record<string, string>;
  annotations: Record<string, string> }`, because a `Record` built at run time does not satisfy the generated type
  (measured, `tsc-dynamic-record.txt`).

## 11. Questions for the owner

1. **Accept the 14 breaking lines before 1.0?** Recommendation: yes. No accepted body changes; only the document
   becomes accurate. Version 0.2.0 has no released contract (`contract/released/` is empty).
2. **The portal's form from the configuration: in #328, or its own issue?** Recommendation: its own issue, linked to
   #20 and #302, with a route such as `GET /api/v1/metadata-keys` that returns
   `{labels: {create, patch}, annotations: {create, patch}}` from `json_schema`, so the form, Swagger UI and the plan all
   read one source. The portal's hard-coded fields are drift today (section 3.1) whatever #328 does.
3. **A contract report for an organisation's configuration change?** `metadata-keys.yaml` changes never reach the
   gate. Recommendation: a `cmapi-tools openapi render --config-dir` that writes the served document offline (as
   `cmapi-tools policies render` does for Kyverno), and a report-only step in the configuration repository's CI that
   runs `oasdiff breaking` between the document of the old and the new file. Report, not fail: approval is the gate for
   a configuration change (#215, item 4).
4. **Restrict `pattern` to what Python, RE2 and ECMA-262 read the same way?** One pattern now reaches three engines.
   Recommendation: yes, as its own issue: the loader refuses inline flags, `(?P<…>)`, `\A`, `\Z`, lookaround,
   backreferences, and `\d`, `\w`, `\s`, `\b` (Unicode-dependent in Python, ASCII in RE2 and in ECMA without `u`). No
   shipped file uses any of them. It refuses files that load today, which is why it is the owner's call.

## 12. The tests that will prove it

Each fails on `9ba33b2` and passes after, unless it says otherwise.

| Test | Asserts | On main |
|---|---|---|
| `tests/service/test_api_docs.py` (the issue's) | the committed contract: `NamespaceCreate.properties.labels.required == ["cmapi.net/team"]`; its `pattern` is `"^(?:" + rule.pattern + ")$"` of the loaded rule; `NamespaceCreate.required` has `labels` and `annotations`; a `Draft202012Validator` on the document refuses a create without `cmapi.net/team` and accepts the recorded example | fails: no `properties` |
| `tests/service/test_metadata_stanzas_api.py`, company fixture | the served document: `labels.required == [mnemonic, lob, cl]`; `name` and `company.net/app-environment` are `readOnly`; `annotations` is not in `NamespaceCreate.required` | fails |
| same file | the served create example, the curl body and the patch example each pass a dry run (200) on the company instance | fails: they hold `cmapi.net/team` |
| `tests/core/test_metadata_schema.py` | the differential corpus of section 8 on four configurations | precision half fails |
| contract CI: ECMA dialect run | each generated pattern agrees with `re.fullmatch` on the corpus | new guard |
| Spectral on the company document | `contract/lint.sh` on the served company document: 0 problems | passes on main (nothing to check); fails on the new schemas without section 7 (measured, 4 errors) |
| `contract/gate.sh` | passes with the 14 lines | n/a |
| `api-types.mjs --check`, the portal's `npm test` | regenerated types; the form compiles | n/a |
| `api-examples-doc.py --check` | docs/04 unchanged | n/a |

**Screenshots on CRC** (through the Route, in Chrome, signed in): `/docs`, "Create a namespace", Schema tab with
`labels` and `annotations` expanded (the red `*` on `cmapi.net/team` and `cmapi.net/team-dl`, their patterns, "Property
names"); the same operation's "Try it out" body; "Change a namespace", Schema tab; `/redoc`, "Create a namespace",
the request body. The measured local renders of the same document are in `evidence/screenshots/`
(`swagger-reference-chosen-inline-*.png`, `redoc-reference-chosen-inline-create-2.png`).

## 13. What was measured, inferred, and not done

- Measured on this Mac: the served documents for the reference and company files (service app on the fakes, PostgreSQL
  on 55432); the renders in Swagger UI 5.34.1 and ReDoc 3.1.0 in headless Chromium; oasdiff 1.37.0; Spectral with the
  repository's ruleset; openapi-typescript 7.13.0 with TypeScript 5.9.3; datamodel-code-generator 0.97.0;
  openapi-python-client 0.30.0; `jsonschema` 4.26.0; Node 26.9 `RegExp`.
- Inferred, not measured: that CRC serves the reference schemas (its ConfigMap's keys equal the reference file's, and the
  prototype's output for both is identical; CRC was not called); that Swagger UI does not validate a "Try it out" body
  against the schema before it sends it.
- Not done: no code in the repository; no kind or CRC run; the prototype generator and the corpus are in the notes
  folder only, for the implementer to start from.
