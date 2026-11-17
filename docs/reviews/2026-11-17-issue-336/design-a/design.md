# #336, design A: the New namespace form from the instance's metadata config

Designer A, Opus 5.5 at high, 2026-11-17. Written from `origin/main` at c7ab6c4, exported to `src/` beside this file
(`git archive origin/main`). No repository was changed. Every number below comes from a script in `scripts/`, and its
output is in `evidence/`. What was measured, what was inferred and what was not tested is said at each point.

## 1. The decisions

| # | Point | Decision |
|---|---|---|
| D1 | Route | `GET /api/v1/metadata-keys`, on the core router (plugin `core`, prefix `/api/v1`), beside `/me` and `/clusters` |
| D2 | Permission | `objects:read`, the permission of `GET /api/v1/tiers`, which the same form already needs |
| D3 | Response | `{jsonSchemaDialect, configHash, labels, annotations}`. `labels` and `annotations` are **the same objects** that `/openapi.json` serves at `NamespaceCreate.properties.labels` and `.annotations`, built by one function that `_document_metadata` and the route both call. No second rule source, no form-specific shape |
| D4 | Caching | Strong `ETag` over the exact bytes, `Cache-Control: no-cache`, `304` on a matching `If-None-Match`. Built once per process, since the config is read only at start and a change restarts the pods |
| D5 | Rendering | Each property becomes one field, chosen from the schema's own keywords (section 5). Derived keys show read-only and are never sent. Declared optional keys and the `allowOther` keys go in one collapsed `FormFieldGroupExpandable`. Operator-only keys are not offered (open question Q1) |
| D6 | Labels of fields | A new optional rule field `title` (JSON Schema's `title`). The reference config gets `title: Team` and `title: Team DL`, so the CRC form keeps the mockup's words. Without a title the key is the label |
| D7 | Client validation | `@cfworker/json-schema` 4.1.6 (an interpreter: no `eval`, so it runs under the portal's CSP; `new RegExp(p, "u")`) on the served schema, plus the two checks that the schema carries as `x-cmapi-*`: `namespacePrefix` and the `allowOther` count and bytes. No HTML `pattern` attribute and no native `required` on these fields |
| D8 | Server errors | `ApiProblem` keeps `errors[]`. Each error with a `key` goes to that key's field; the rest go to the form-level error summary |
| D9 | Accessibility | PatternFly field-level errors (`validated="error"`, `aria-invalid`, helper text linked by `aria-describedby`), an error summary in an inline danger `Alert` that takes focus on a refused submit, with a link to each field |
| D10 | Proof | Both configs, end to end: a Python service test holds the route equal to the schema and writes the portal's fixtures; a direct Node test runs the portal's own validator over the #328 corpus with the server's verdicts; browser checks on the standin serve each config; mutants drop a field, a pattern, the prefix check and the error mapping |

## 2. The premises, checked on `origin/main` c7ab6c4

| Premise | Where | Verified |
|---|---|---|
| The form hard-codes the two CRC keys | `cmapi-portal-ui/src/portal/NewNamespaceTab.tsx:145-152` (`labels: {"cmapi.net/team": team}`, `annotations: {"cmapi.net/team-dl": dl}`), fields at `:200-203` and `:232-235` | Read |
| `/openapi.json` can be off | `cmapi/src/cmapi/main.py:116` `docs_enabled`, `:183` `if docs_enabled: _add_docs(...)`; FastAPI's own `openapi_url=None` at `:119` | Read |
| The #328 generator is one function | `MetadataKeys.json_schema(kind, op)`, `cmapi/src/cmapi/core/metadata.py:960-991`; `_document_metadata` in `core/docs.py:429-451` wraps it with `title`, `description` and `examples` | Read, and run (section 4) |
| Every value regex is anchored once, in the subset that Python `re`, RE2 and ECMA-262 read alike | `metadata.py:285-288` `anchored`, `:357-366` `value_regex`, `:61-283` the subset (#332) | Read; and the served patterns all compile with the `u` flag (section 6) |
| Config is read once at start; a change restarts the pods | `core/config.py:63-119` loads once; no reload code exists (`grep -i reload\|watch` finds none in `core/`); arbitration of #328, "Where the rules are set", item 4 (`checksum/config`) | Read. Note: `config.py:16-17` and docs/02 still describe a ConfigMap watch that is not built (section 13, finding A2) |
| The API's documents already use ETag plus `no-cache` | `main.py:218-236` (strong tag, hash of the served bytes), `:326-331` `_etag_matches` (weak comparison) | Read |
| The front door sets `no-store` on an API answer with no `Cache-Control`, and keeps one that the API sets | `cmapi-portal-ui/nginx/templates/cmapi.conf.template:36-41`, `nginx/cmapi/proxy-api.conf:7` | Read |
| The portal's CSP forbids `eval` | `cmapi.conf.template:44-46`: `script-src 'self'` | Read |
| `ApiProblem` drops `errors[]` today | `cmapi-portal-ui/src/api/problem.ts:28-31` | Read |
| The operator-only rule is role based, in the pipeline | `core/pipeline.py:187` `operator = "cmapi-operator" in who.roles or "cmapi-admin" in who.roles` | Read |
| The derived keys' sources | `core/pipeline.py:207` `{"namespace": ns, "environment": env, "cluster": cluster_id, "instance": self.cfg.name}`; `GET /api/v1/me` returns `instance: c.cfg.name` (`routers/me.py:18-20`) | Read |
| CRC runs the reference config | `deploy/manifests/environments/crc/20-config.yaml` `metadata-keys.yaml` equals `examples/cluster-configs/policies/metadata-keys.yaml` and the chart's `config/metadata-keys.yaml`, parsed | Run: `True`, `True` |

## 3. The route

### 3.1 Path, place and permission

`GET /api/v1/metadata-keys`, in a new module `cmapi/src/cmapi/routers/metadata.py` with
`router = DocumentedRouter("core", prefix="/api/v1", **CORE)`, included in `main.py`'s `authed_routers`.

- **Why core, not the namespaces plugin.** The namespaces router's prefix is `/api/v1/clusters/{cluster_id}`
  (`plugins/namespaces/router.py:24`), and the rules are one per instance, not per cluster. `core/plugins.py:28-34` gives
  each plugin one router. `metadata-keys.yaml` is loaded by core config whatever plugins are on, and `plugin_routers`
  already accepts two routers of `core` when they agree (`health.version_router` and `me.router` do).
- **Why this path.** It names the file and the rules (docs/02 line 1005, "Key classes live in one file"), and it is the
  issue's own example. A JSON-Schema-specific path (`/schemas/...`) was rejected: the resource is the instance's key rules,
  the schema is its representation.
- **Why `objects:read`.** Each built-in role but `approval-relay` holds it (docs/14, table at line 39). The New namespace
  form already fails closed on it through `GET /api/v1/tiers` (`plugins/tiers/__init__.py:17`), so the route adds no new
  way for the form to be refused. `permission=None` (valid token only, as `/me`) was the alternative: the rules are not
  secret (the same schema is in `/openapi.json`, which is public by default), but docs/14 holds `/me` as the one exception,
  and a route that declares a permission is checked by `test_declared_permission_is_the_enforced_one_and_every_route_answers`.
  `namespaces:create` was rejected: a viewer could not read the rules that its namespaces follow.
- **Problems.** `unauthenticated` and `forbidden` only (added by `DocumentedRouter` for a route with a permission). It has no
  other failure: the config is loaded at start, or the service does not start.

### 3.2 The response

```python
# core/models.py
class MetadataKeysView(Api):
    """The labels and annotations that a create of this instance takes, as JSON Schema (#336)."""
    json_schema_dialect: str = Field(alias="jsonSchemaDialect", examples=["https://json-schema.org/draft/2020-12/schema"],
        description="The dialect of `labels` and `annotations`. Keywords that start with x-cmapi- are annotations that a "
                    "validator ignores (JSON Schema Core 2020-12, section 6.5)")
    config_hash: str = Field(alias="configHash", examples=["e1e2c26ce01c06d0"],
        description="SHA-256 of metadata-keys.yaml, first 16 hex digits: the hash in cmapi_config_info")
    labels: dict[str, Any] = Field(examples=[...the reference config's labels object...],
        description="The JSON Schema of NamespaceCreate.labels on this instance: the object that /openapi.json serves there")
    annotations: dict[str, Any] = Field(examples=[...], description="The same, of NamespaceCreate.annotations")
```

`check_documented` (`core/docs.py:193-208`) needs a description and an example on each required field; the model gives both.
`labels` and `annotations` are open objects in the contract, so `openapi-typescript` types them as
`{[key: string]: unknown}`, and the portal reads them through one runtime guard (section 5.1), as `tiersOf` reads the
catalog's open objects (`NewNamespaceTab.tsx:30-43`).

**One generator, two callers.** `_document_metadata` (`core/docs.py:429-451`) builds the field object inline today. It moves
into one public function, called by `_document_metadata` and by the route:

```python
# core/docs.py
def metadata_field_schema(keys: MetadataKeys, kind: str, op: str, title: str) -> dict[str, Any]:
    """NamespaceCreate.<field> (op=create) or the object branch of NamespacePatch.<field> (op=patch), as /openapi.json and
    GET /api/v1/metadata-keys serve it (#328, #336): json_schema() with the title, the words beside it and the examples."""
```

The route's `labels` is `metadata_field_schema(keys, "label", "create", "Labels")`. This is a refactor of
`_document_metadata`: it must leave `/openapi.json` byte-equal. **Measured** (`scripts/proposed.py`, run in
`evidence/proposed-run.txt`): the route body's `labels` and `annotations`, built this way, equal what origin/main's own
`_document_metadata` writes into `NamespaceCreate.properties`, for both configs: `True`, `True`.

`emailDomains` is not a separate field: it is in each address `pattern` and in the description (`An address in
['company.net']`). A second copy would be a second place to read the rule from. `patch` schemas are left out: nothing in the
portal edits labels yet (Q3).

**The route's own example in `/openapi.json`.** `add_recorded_examples` puts the sample of a run on the reference config into
the 200 example (`core/docs.py:502-527`). On a company instance that example would show keys the instance does not have,
the defect #334 fixed for the create body. So `_document_metadata` also sets the 200 example of
`GET /api/v1/metadata-keys` to this instance's own body.

### 3.3 The exact response bodies

Generated by origin/main's own code (`scripts/proposed.py`); the files are the pretty-printed bodies, the served bytes are
the same JSON compact. Full text: `evidence/response-reference.json` (5,322 bytes pretty, 3,814 compact) and
`evidence/response-company.json` (8,763 pretty, 7,218 compact). Appendix A holds both in full.

| Config | labels: properties (required in bold) | annotations: properties (required in bold) | allowOther |
|---|---|---|---|
| Reference (CRC) | **`cmapi.net/team`** (pattern), `cmapi.net/cost-center` (pattern), `cmapi.net/app` (pattern), `cmapi.net/rightsizing` (pattern), `cmapi.net/protected` (operator-only) | **`cmapi.net/team-dl`** (email-in-domains), `cmapi.net/protected` | `""`, `*.ephico2real.com/`, max 50; annotations 4096 B each, 65536 B total |
| Company | `name` (derived from namespace), `company.net/app-environment` (derived from environment), **`company.net/mnemonic`** (pattern, namespacePrefix), **`company.net/lob`** (label syntax), **`company.net/cl`** (enum 0 to 6), `cmapi.net/protected` | `company.net/app-environment` (derived), `company.net/mnemonic-group-contact` (email-in-domains), `company.net/mnemonic-confluence` (url), `cmapi.net/protected` | `""`, `*.company.net/`, max 50; same byte limits |

(`evidence/key-classes.txt`.) The company annotations have no required key, so their schema has no `required`.

## 4. Caching

| Header | Value | Why |
|---|---|---|
| `ETag` | `"<first 32 hex of SHA-256 of the served bytes>"`, strong | RFC 9110 section 8.8.3: a strong validator changes with every change of the representation. The same function as `/openapi.json` (`main.py:218-226`), so two replicas on the same config give the same tag |
| `Cache-Control` | `no-cache` | RFC 9111 section 5.2.2.4: a cache may store the answer but must revalidate before each reuse. A pod restarted with a new config answers with a new tag at the next read, with no wait. `max-age` was rejected: across a rolling restart it would let a tab keep old rules for its whole age |
| `304` | On `If-None-Match` matching by the weak comparison (RFC 9110 sections 13.1.2 and 15.4.5), with the same `ETag` and `Cache-Control` and no body | Reuses `main.py`'s `_etag_matches`, moved to `core/docs.py` as public `etag_matches` with the tag helper, so the two documents and the route share one implementation |

No `Vary` beyond the CORS middleware's `Vary: Origin`: the body does not depend on the caller. RFC 9111 section 3.5 keeps a
shared cache from storing an answer to a request with `Authorization` unless told otherwise, and this route does not tell
it; only the browser's private cache stores it.

The bytes and the tag are computed once per process, on the first call (as `documents` in `main.py:218-226`), since the
config does not change without a restart (section 2). The front door keeps the route's own `Cache-Control`
(`cmapi.conf.template:36-41`).

**Measured, the premise that the browser revalidates** (`scripts/revalidate.mjs`, `evidence/revalidate-run.txt`):
Chromium 156.0.8078.4, a page on one loopback origin, the API on another, `fetch` with `Authorization` twice. The API saw
the first GET with no `If-None-Match` and the second with `If-None-Match: "abc123"`, answered 304, and the page's `fetch`
saw `200` with the body both times. `If-None-Match` added by the HTTP cache caused no preflight (the stand-in API did not
allow that header). So TanStack Query's default `staleTime: 0` costs a 304 on each mount or focus, and the portal needs no
cache code of its own.

## 5. The form

### 5.1 One parser, one validator, one body builder: `src/portal/metadataForm.ts`

A pure module, testable by Node's type stripping as `tests/api/direct.test.mjs` tests `auth.ts`:

- `fieldsOf(view): MetaField[]` reads `labels` and `annotations`: for each property, in the served order (declaration order
  in the file), `{kind, key, title, required, derivedFrom, namespacePrefix, operatorOnly, enum, example, description,
  schema}`. It throws a named error when the body is not an object of the expected shape; the hook turns that into the form's
  "The form did not load." with the cause.
- `checkValue(field, value)` and `checkMap(kind, map, namespace)` validate with `@cfworker/json-schema`'s `Validator`
  (draft `2020-12`) on the served subschema or map schema, compiled once per schema object. Then the two checks that the
  schema states as `x-cmapi-*` and JSON Schema cannot evaluate: `x-cmapi-namespace-prefix` (the namespace starts with
  `value + "-"`) and `x-cmapi-other-keys` (count of keys outside `properties` at most `max`; for annotations each value at most
  `maxValueBytes` and all at most `maxBytesTotal` in UTF-8, by `TextEncoder`). Each reads the served data, not a constant.
- `bodyOf(fields, values, others)` gives `labels` and `annotations`: each non-derived field with a non-empty value, plus
  the other keys. An empty optional field is left out, never sent as `""` (`""` breaks a declared pattern on the server).
  A derived key is never sent: cmapi fills it (`metadata.py:899-905`), and sending it adds only a way to be refused.
- `fieldErrors(problem, fields)` maps `errors[]` (section 7).

### 5.2 Each key class

| Class, as the schema says it | Control | Behaviour |
|---|---|---|
| Required (`required` of the map) | `TextInput`, or `FormSelect` for an enum; `FormGroup isRequired` (asterisk) and `aria-required="true"` | Empty is "Required." (PatternFly's words for a blank required field). Shown in the main form, in the place of today's Team and Team DL |
| Derived (`readOnly: true`, `x-cmapi-derived-from`) | `TextInput readOnlyVariant="default"` with the value cmapi will set | The value: `namespace` the name field, `environment` the chosen environment, `cluster` the chosen cluster, `instance` `/me`'s `instance`. Helper text is the schema's description ("Set by cmapi from the namespace…"). Read-only, not disabled, so it stays in the tab order and is announced (WAI-ARIA `aria-readonly`). Never sent |
| Declared optional | As required, without the mark | In the collapsed group "Optional labels and annotations" |
| Operator-only (`x-cmapi-operator-only`) | Not offered | Q1. The free-key rows refuse a declared key, so one cannot be typed there either |
| `allowOther` (`propertyNames`, `additionalProperties`, `x-cmapi-other-keys`) | Rows of key and value `TextInput`s with Remove, and "Add label" / "Add annotation", in the same collapsed group | A key is checked against `propertyNames` and must not be a declared key ("{key} has its own field"); a value against `additionalProperties`. "Add" is disabled at `max`. The byte limits are checked on the annotation rows |
| `enum` | `FormSelect` with a first empty option "Choose a value" (no default, so nothing is sent that the person did not choose) | PatternFly's select for a list longer than a few options (the company's `cl` has seven) |
| `pattern` | `TextInput type="text"` | Checked by the served pattern only |
| `x-cmapi-format: email-in-domains` | `TextInput type="text" inputMode="email" autoComplete="off"` | `type="email"` is dropped on purpose: it would add the browser's own address check beside the served pattern, a second rule |
| `x-cmapi-format: url` | `TextInput type="text" inputMode="url"` | As above |
| `x-cmapi-namespace-prefix` | As its control | The namespace must start with `value-`; the error shows on this key's field, as the server reports it on the key (`metadata.py:918-920`). The name's helper text says "Starts with {value}-" |

**Labels of fields (D6).** The config has no human name for a key (`_RULE_FIELDS`, `metadata.py:53`). JSON Schema Validation
2020-12 section 9.1 gives `title` for exactly this ("can be used to decorate a user interface with information about the
data produced by this user interface. A title will preferably be short"). So a rule takes an optional `title`, and
`_rule_schema` emits it. The label is the title, with the key in `FormGroup labelInfo` as code, so the person sees which
key they set; without a title the key is the label. Titles for the shipped files: reference `cmapi.net/team: Team`,
`cmapi.net/team-dl: Team DL`, `cost-center: Cost center`, `app: App`, `rightsizing: Rightsizing`; company `name: Name`,
`app-environment: Environment`, `mnemonic: Mnemonic`, `lob: Line of business`, `cl: Critical level`,
`mnemonic-group-contact: Group contact`, `mnemonic-confluence: Confluence space` (Q2 asks the owner to confirm the words).

**Helper text.** The property's `description` (the config's description and the rule in words, as the API document
says it), then "For example {examples[0]}." when the rule has one. Linked to the input by `aria-describedby`, replaced by the
error while there is one (PatternFly form guidelines).

**The namespace name's suggestion.** Today the name is `team-env` until the person types one (`NewNamespaceTab.tsx:141`, the
mockup's `nsName`). Kept, generalised: the suggestion is `{value}-{env}` of the key with `x-cmapi-namespace-prefix`, or, when
the config has none, of the first required label in the served order. On the reference config that is `cmapi.net/team`, so
`payments-dev` as today; on the company config `company.net/mnemonic`, so `abc-rnd`, the name that `docs.example_namespace`
gives the API document. It is a suggestion only; nothing is checked by it.

**Unchanged.** Environment, Region, Cluster, Name, Tier, Expires, Justification, Dry run and Submit, the plan, the
Idempotency-Key rules (#282), and `Form noValidate={false}` for the name and the date's `min` and `max` (MOCKUP-CONTRACT,
"Dates are TextInput type=date"). The sentence "Requested by {user} ({email}), from your sign-in." moves from the Team DL hint
to the hint under the metadata fields, since it is about the system key `requested-by`, not the DL.

### 5.3 The hook

`useMetadataKeys()` in `src/api/hooks.ts`: `queryKey: ["metadata-keys"]`, default `staleTime`, `GET /api/v1/metadata-keys`,
then `fieldsOf`. `NewNamespaceTab` adds it to its loading, forbidden and error gates with `clusters` and `tiers`
(`NewNamespaceTab.tsx:108-133`), so a 403 or 5xx of the route shows the form's existing states and words.

## 6. Client-side validation

**The authority stays the server.** The form only refuses what cmapi would refuse; it never accepts on its own authority,
since the dry run is required before Submit (`NewNamespaceTab.tsx:158-166`).

**Library (D7).** Options, with what decided:

| Option | Verdict |
|---|---|
| Ajv 8 (`ajv/dist/2020`) at run time | Rejected. Ajv compiles a schema to code; its security page: the CSP "`script-src` directive must include `'unsafe-eval'`", which "is NOT recommended". The portal's CSP is `script-src 'self'` (`cmapi.conf.template:44-46`). Ajv's standalone mode compiles at build time, and the schema here is per instance at run time (`evidence/ajv-csp.txt`) |
| HTML `pattern` and `required` attributes | Rejected. The HTML standard compiles `pattern` with `RegExpCreate(pattern, "v")`, and a pattern that does not compile is no constraint at all. **Measured** (`evidence/v-flag-run.txt`, Node 26.9.0): 6 of the 8 distinct served patterns of the reference config and 6 of 7 of the company's are SyntaxErrors under `v` (`[^/]` and `/` in a class, `-` first in a class). GOV.UK's validation pattern: browser messages "cannot be made consistent" and should be turned off for accessible ones |
| A hand-written interpreter of the keywords that `json_schema` emits | Rejected. A second implementation of JSON Schema's semantics (`anyOf`, `not`, `propertyNames`, `allOf`), which a future keyword would silently break |
| **`@cfworker/json-schema` 4.1.6** | **Chosen.** MIT, no dependencies; drafts 4 to 2020-12; an interpreter (no `eval` or `new Function` in its `dist/esm`, scanned); `pattern` is `new RegExp($pattern, 'u').test(instance)` (`src/validate.ts:1183`), the reading #332 proved equal to Python `re` and RE2 on the subset; errors carry `keywordLocation` and `instanceLocation`. 22,678 bytes minified, 6,384 gzip with one import (esbuild 0.25.0) |

The served patterns are anchored `^(?:P)$` (`metadata.py:285-288`), so the library's `test` (a search) is a whole match.
4.1.6 was published 2026-11-04; the exact version is pinned with its integrity in `package-lock.json` (Q5 on the
release age).

**Measured agreement** (`scripts/client-leg.mjs`, `evidence/client-leg-run.txt`). The create half of the #328 corpus
(`cmapi/tests/core/metadata_corpus.py`, `cases`), each map with `validate()`'s verdict on origin/main, against the served
create schema read by `@cfworker/json-schema` 4.1.6 in Node 26.9.0, plus the prefix check and the `x-cmapi-other-keys` limits:

| Config | Maps | Accepted by `validate()` | Client agrees | Unsound: server accepts, client refuses | Loose: client lets through, server refuses |
|---|---|---|---|---|---|
| Reference | 5,978 | 508 | 5,886 | **0** | 92 `operator_only_key` |
| Company | 6,219 | 736 | 5,988 | **0** | 135 `derived_key`, 96 `operator_only_key` |

Every served pattern compiles with `u` (17 occurrences on the reference, 15 on the company). The two loose classes are the
two the form cannot see and never sends: the caller's role, and a derived key with another value (the form sends none).
Without the count and byte checks the loose column also held 2 `too_many_keys` and 5 or 7 `annotations_too_large`, which
is why the form reads `x-cmapi-other-keys`.

**Messages.** For the first failure, in the server's order (`_syntax` then `_governed`, `metadata.py:882-921`):

| Failure | Message |
|---|---|
| Empty and required (`required`, `minLength`) | "Required." |
| A label value that fails the map's `additionalProperties` (the label syntax, served) | "A label value: at most 63 letters, digits, '-', '_' or '.', starting and ending with a letter or a digit." |
| `enum` | "One of {enum, joined by ', '}." |
| `maxLength` | "At most {n} characters." |
| `pattern` of the key's rule | "Not valid. {description}" (the description holds the rule in words: "Must match ^[a-z]{3,4}$", "An address in ['company.net']", "An http or https URL") |
| namespacePrefix | "The namespace {name} must start with {value}-." |
| A free key | "{key} is not a key that this instance allows: {words of x-cmapi-other-keys}" or "{key} has its own field" |
| Count, bytes | "At most {max} other labels.", "At most {maxValueBytes} bytes.", "All other annotations together at most {maxBytesTotal} bytes." |

**When.** On blur of a field; then on each change while it shows an error; and all fields on Dry run and on Submit
(PatternFly: "On loss of focus or on submission"). Dry run and Submit send nothing while a field has an error.

## 7. Server errors to fields

`ApiProblem` (`problem.ts`) gains `errors: ProblemError[]` (from `ProblemDetail.errors`), and `Outcome`'s `refused` carries
them. `fieldErrors(problem, fields)`:

| Server error (docs/02 line 1202, `metadata.py:835-879`) | Goes to |
|---|---|
| `invalid_value`, `invalid-team-dl`, `missing_required_key`, `derived_key`, `invalid_key`, `reserved_key` with a `key` that is a rendered field (matched on `kind` when the error has one, else every field of that key) | That field: `validated="error"`, the server's `detail` as the message, or the code's words when it has none |
| The same, with a key of a free row | That row |
| No `key`, or a key that is not on the form (`too_many_keys`, `annotations_too_large`, a Kyverno warning beside cmapi's in audit mode, #342) | The form's error summary |
| 403 `forbidden` "Only cmapi-operator may set …" | The existing "Refused: forbidden" callout |

The existing callouts stay ("Refused: {code}" for a dry run, "Not submitted" for a create); the field errors are added under
them. A refused dry run's field errors clear when the person edits that field.

## 8. Accessibility (WCAG 2.2)

| Criterion | How |
|---|---|
| 1.3.1, 3.3.2 Labels or Instructions | Each control has a `FormGroup` label (title or key); required marked by the asterisk and `aria-required`; the rule in helper text linked by `aria-describedby` |
| 3.3.1 Error Identification | The field in error has `aria-invalid="true"`, `validated="error"`, and the message in its helper text, by id in `aria-describedby` |
| 3.3.3 Error Suggestion | Each message says the valid form (section 6), not "Invalid input" (PatternFly) |
| 2.4.3 Focus Order, 4.1.3 Status Messages | A refused Dry run or Submit opens the collapsed group if a field in it is in error, shows the error summary (inline danger `Alert`, below the heading, a list of links to each field), and moves focus to it (GOV.UK validation pattern). A server refusal is announced by the existing `Alert` |
| 4.1.2 Name, Role, Value | Read-only derived fields are `readOnly` inputs, not disabled, so they are announced |
| Checked | axe (`@axe-core/playwright` 4.14.0, as the suite runs today) at 390 and 1440 px on the company form with an error shown |

Today's `Hint` (`components/ui.tsx:185-187`) has no id, so no input points to it; the new fields fix it for themselves, and
section 13 (A4) suggests the same for the other fields.

## 9. The proof cases

| Case | What it shows | Where |
|---|---|---|
| Reference (CRC) | The fields Team and Team DL, required, with the mockup's words; the optional group with `cost-center`, `app`, `rightsizing`; the dry-run body byte-equal to today's (`{"cmapi.net/team": "payments"}`, `{"cmapi.net/team-dl": "payments-team@ephico2real.com"}`, test 9 of `portal.test.mjs` line 549) | Standin and CRC |
| Company | Mnemonic, Line of business, Critical level (select 0 to 6); `name` and Environment read-only with `abc-rnd` and `rnd`; the optional Group contact and Confluence space; `ABC` refused in the browser with nothing sent; `xyz-rnd` with mnemonic `abc` refused; a contact in another domain refused; the body has no derived key | Standin, and kind with the company file (CRC runs the reference config and is shared, so the company file is not put on it) |

## 10. Options rejected (beyond those in the tables)

| Option | Why not |
|---|---|
| A form-specific response (`{fields: [{key, label, type, …}]}`) | A second serializer of the rules beside `json_schema`, free to drift from it; the issue asks for "the same function as the #328 schema" |
| The form reads `/openapi.json` | Off with `docs.enabled: false` (`main.py:183`); behind sign-in or not depending on `docs.public`; 100s of KB for two objects |
| Serving `json_schema(kind, "create")` alone, without the words and examples | Then the route's object differs from `/openapi.json`'s, and equality (the contract test) becomes a "subset" check; the words are the help text |
| Building the body from `examples` | An example is a sample, not a default; the person's own values are sent |
| Rendering derived keys as a list outside the form | They are part of what lands on the namespace; read-only fields show it where the person looks |
| `staleTime: Infinity` in TanStack Query | A tab kept across a restart with new rules would plan with old fields; `no-cache` and the 304 already make each read cheap |

## 11. Change list, file by file

**Service (`cmapi/`)**

| File | Change |
|---|---|
| `src/cmapi/core/metadata.py` | `title` in `_RULE_FIELDS`, `KeyRule.title`, type check in `_add` (text), `_rule_schema` emits `title` when set |
| `src/cmapi/core/docs.py` | `metadata_field_schema(keys, kind, op, title)` out of `_document_metadata`; `metadata_keys_body(keys, config_hash)`; the route's 200 example per instance; `etag_of(body)` and `etag_matches(...)` moved from `main.py` |
| `src/cmapi/core/models.py` | `MetadataKeysView` |
| `src/cmapi/routers/metadata.py` (new) | `GET /api/v1/metadata-keys`, `objects:read`, the cached bytes, ETag, `no-cache`, 304 |
| `src/cmapi/main.py` | Include the router; use `docs.etag_of` / `etag_matches` |
| `src/cmapi/contract/samples.json`, `contract/openapi.json`, `contract/changelog` entry | Regenerated (`CMAPI_WRITE_SAMPLES=1`, `CMAPI_WRITE_CONTRACT=1`); oasdiff: additions only (a path, a schema, `title`s) |
| `tests/service/test_api_samples.py` | Record `core_metadata_keys`, and one refused dry run (`cmapi.net/team: "Payments"`) so `policy-violation` has a recorded sample |
| `tests/service/test_metadata_keys_336_api.py` (new) | Section 12, S1 to S8 |
| `tests/core/test_metadata_title_336.py` (new) | `title` loads, is text, is emitted; a non-text title is refused |

**Config and chart**

| File | Change |
|---|---|
| `examples/cluster-configs/policies/metadata-keys.yaml`, `deploy/helm/cmapi/config/metadata-keys.yaml`, `deploy/manifests/environments/crc/20-config.yaml`, `examples/local/config/metadata-keys.yaml` | The reference titles (section 5.2) |
| `examples/cluster-configs/policies/metadata-keys.company.yaml` | The company titles |
| `deploy/helm/cmapi/values.schema.json` | `title: {"type": "string"}` in `definitions.rule.properties` (its `additionalProperties: false` would refuse it otherwise) |

**Portal (`cmapi-portal-ui/`)**

| File | Change |
|---|---|
| `package.json`, `package-lock.json` | `@cfworker/json-schema` exact `4.1.6` |
| `src/api/schema.generated.ts`, `permissions.generated.ts` | `npm run api:types` |
| `src/api/problem.ts` | `errors` on `ApiProblem` |
| `src/api/hooks.ts` | `useMetadataKeys`; `errors` in `Outcome.refused` |
| `src/portal/metadataForm.ts` (new) | Section 5.1 |
| `src/portal/MetadataFields.tsx` (new) | The fields, the optional group, the free rows, the error summary |
| `src/portal/NewNamespaceTab.tsx` | Drop `team`, `dl` and the two hard-coded keys; the hook in the gates; values by key; the name suggestion; `bodyOf`; checks before Dry run and Submit; field errors from a refusal |
| `tests/api/standin.mjs` | `GET /api/v1/metadata-keys` from `state.metadataKeys` (default: the recorded sample) with ETag, `no-cache` and 304; records `if-none-match` |
| `tests/api/fixtures/metadata-keys.company.json` (new, generated) | The company body and the compact create corpus with verdicts (about 186 KB, measured on the compact encoding), written and checked by S7 |
| `tests/api/fixtures/metadata-keys.reference.json` (new, generated) | The same for the reference (about 165 KB) |
| `tests/api/direct.test.mjs`, `tests/api/portal.test.mjs`, `tests/api/mutants.mjs` | Section 12 |
| `MOCKUP-CONTRACT.md` | New namespace rows: fields from `GET /api/v1/metadata-keys`; helper text from the config; key in the label info; the optional group and other keys; error summary; `useMetadataKeys` in the hooks list |

**Docs**: docs/02 (the route in the API table and "Labels and annotations"; the live doc first, per CLAUDE.md), docs/04 (the
recorded example), docs/14 (`objects:read` routes), docs/18 (`title`; the route), docs/09 (the testing record from measured
numbers), `HANDOVER-AND-RESUME.md` and `build-tracker.md` by the coordinator.

## 12. Tests, and how each fails before

Python (`tests/service/test_metadata_keys_336_api.py`, parametrised on the two configs with #328's `instance` fixture, which
runs with `policy.engine: none`):

| # | Test | Fails before because |
|---|---|---|
| S1 | The route's `labels` and `annotations` **equal** `/openapi.json`'s `NamespaceCreate.properties.labels` and `.annotations`, object for object | 404 |
| S2 | The body validates as `MetadataKeysView`; `configHash == ctx.cfg.hashes["metadata-keys.yaml"]`; `jsonSchemaDialect` is 2020-12 | 404 |
| S3 | ETag is `"` + 32 hex of SHA-256 of the exact body + `"`; `Cache-Control: no-cache`; `If-None-Match` with the tag, and with `W/` + tag, gives 304 with no body and the same headers; another tag gives 200 | 404 |
| S4 | With `docs.enabled: false`: `/openapi.json` 404 and the route 200 with the same body | 404 |
| S5 | No token 401; a token without `objects:read` 403; `cmapi.viewer` 200 | 404 |
| S6 | The #328 corpus through the **route's** create schemas (`metadata_corpus.run`, create cases): 0 unsound, 0 unexplained | 404 |
| S7 | The portal fixtures equal the route's body and the corpus verdicts on that config (`CMAPI_WRITE_PORTAL_FIXTURES=1` writes them) | No fixture |
| S8 | `/openapi.json`'s 200 example of the route is this instance's body (the company instance shows no `cmapi.net/team`) | No route; then the reference sample, until `_document_metadata` sets it |
| S9 | `/openapi.json` on the reference config equals the committed contract but for the route's additions (the refactor of `_document_metadata` changes nothing else) | Holds before; it guards the refactor |
| C1 | `title`: loaded, emitted as `title`, a non-text one refused (`tests/core`) | `unknown fields ['title']` |

Portal, direct (`tests/api/direct.test.mjs`, Node type stripping, no browser):

| # | Test | Fails before because |
|---|---|---|
| D1 | `fieldsOf` on each fixture: the keys, kinds, required, derived sources, prefix, enum, titles, in order | No module |
| D2 | `checkMap` over each fixture's corpus: 0 unsound; the loose rows only `operator_only_key` and `derived_key` (the measured section 6 result, in the portal's own code) | No module |
| D3 | `bodyOf` leaves out empty optional fields and derived keys, and keeps free rows | No module |
| D4 | `fieldErrors` on the recorded `policy-violation` sample and on errors with and without `kind` and `key` | No module; `errors` dropped by `problemOf` |

Portal, browser (`tests/api/portal.test.mjs`, on the standin, with `fresh({metadataKeys})`):

| # | Check | Fails before because |
|---|---|---|
| P1 | 18 reference: the fields of `GET /api/v1/metadata-keys` (Team, Team DL required; the optional group's three labels), one call, and the dry-run body equal to today's | The tab never calls the route |
| P2 | 18 company: Mnemonic, Line of business, Critical level; `name` = `abc-rnd` and Environment = `rnd` read-only; `ABC` gives "Not valid…" on blur with `aria-invalid`, and Dry run and Submit send nothing (`api.state.seen` has no POST) and focus the error summary; `xyz-rnd` refused on the mnemonic; a contact `abc@other.net` refused; fixed, the body is exactly `{labels: {mnemonic, lob, cl}}` with no `name` or `app-environment` | The tab shows Team and Team DL and sends `cmapi.net/team` |
| P3 | 18 server errors: an injected 422 `policy-violation` with an error on a rendered key, one on a free row's key and one with no key: each on its field or in the summary; a 403 operator-only shows the existing callout | Errors not on the fields; `errors` dropped |
| P4 | 18 states: the route's 403 shows "You do not have permission to request a namespace."; its 5xx "The form did not load." with Try again | The route is not read |
| P5 | 18 caching: the second opening of the tab sends `If-None-Match` with the tag and gets 304; the fields are the same | No ETag from the standin, no route |
| P6 | 7 (existing) extended: the company form, with an error shown, at 390, 820 and 1440 px in each theme, and axe at 390 and 1440 | Not rendered |
| P7 | 6 and 9 (existing) updated: the parity list gets the new strings; check 9's "browser's own checks" asserts the PatternFly error and `aria-required` instead of `el.required` (a deliberate change, D7) | Text differs |

Mutants (`tests/api/mutants.mjs`, each with the check that must fail):

| Mutant | Must fail |
|---|---|
| A declared field dropped (`fieldsOf` skips the first required property) | P1, P2, D1 |
| A pattern not checked (the subschema validator returns valid) | P2, D2 |
| The label-syntax check skipped | D2 |
| namespacePrefix not checked | P2, D2 |
| A derived key sent | P2, D3 |
| An empty optional field sent as `""` | P1, D3 |
| `errors[]` dropped in `problemOf` again | P3, D4 |
| The free rows admit a declared key | P2 |
| The count limit not read from `x-cmapi-other-keys` | D2 |
| The hard-coded CRC labels back in the body | P2 |

## 13. Adjacent findings (for the coordinator; each would be its own issue under fix-defect)

| # | Finding | Evidence |
|---|---|---|
| A1 | docs/02 says `GET /api/v1/tiers` has the catalog hash as its ETag and needs `namespaces:read`; the code sends no ETag header and needs `objects:read` | docs/02 lines 1274, 1311; `plugins/tiers/__init__.py:17`; `grep ETag` finds only `catalogHash` in the body (`core/tiers.py:267`, comment "ETag of GET /api/v1/tiers") |
| A2 | `core/config.py:16-17` and docs/02 line 2157 describe a ConfigMap watch and reload; none exists, and the arbitration of #328 says a change restarts the pods | `grep -i "reload\|watch"` over `core/` |
| A3 | The rule text of a label key with no value rule is "any value" (`metadata.py:535`), though the label syntax applies; the API document shows `company.net/lob (any value)`. docs/18 line 392 says it right | `test_metadata_stanzas_api.py:65` holds the current words |
| A4 | `Hint` (`components/ui.tsx:185-187`) has no id, so no input's `aria-describedby` points to its helper text | Read |

## 14. Open questions for the owner

| # | Question | Recommendation |
|---|---|---|
| Q1 | May an operator set `cmapi.net/protected` from the portal's create form? Today no form offers it | Yes, through a new `operator: boolean` on `GET /api/v1/me`, computed by the function that `pipeline.py:187` uses (factored out), so the portal shows operator-only fields without reading a role itself. A separate issue |
| Q2 | The titles' words for the company keys (section 5.2) | As listed; the owner's sample names them so |
| Q3 | A labels and annotations editor on an existing namespace (PATCH) | Later; the route would add `?op=patch` with `metadata_field_schema(…, "patch", …)` |
| Q4 | The reference descriptions differ from the mockup's hints ("Ownership and cost; any team, not checked against the caller" against "Who owns it, for cost and notices: any team name. …") | Keep the config's words (they are the API document's); MOCKUP-CONTRACT lists the difference |
| Q5 | `@cfworker/json-schema` 4.1.6 is 13 days old today | Pin 4.1.6 with its lockfile integrity (it reaches 14 days on 2026-11-18, before any merge); 4.1.1 (2025-01-31) is the older fallback, same API |

Not tested here: the route itself (not written), the portal changes, CRC. Measured: the generator's bodies and the
`_document_metadata` equality, the client validator against the corpus, the `v`-flag compile, the browser's revalidation, the
library's size and absence of `eval`.

## Reproduce

From this folder: `<venv>/bin/python scripts/proposed.py` (a venv with PyYAML, google-re2, FastAPI and jsonschema; the
run used `workbench/cmapi/ob-358/venv`) writes `evidence/response-*.json` and `evidence/corpus-*.json` (kept gzipped here,
2.3 MB each uncompressed); `node scripts/client-leg.mjs "$PWD/evidence/cfworker" limits` runs the client leg on
`evidence/cfworker/node_modules/@cfworker/json-schema` 4.1.6 (installed with `--ignore-scripts`);
`node scripts/revalidate.mjs` runs the browser revalidation with the portal's Playwright and Chromium.

## 15. Sources

- OpenAPI 3.1.0, section 4.8.1 (`jsonSchemaDialect`) and 4.8.24 (Schema Object: JSON Schema 2020-12): https://spec.openapis.org/oas/v3.1.0
- JSON Schema Core 2020-12, section 6.4 (regular expressions, ECMA-262) and 6.5 (unknown keywords as annotations); Validation 2020-12, sections 6.3.3 (`pattern`), 9.1 (`title`, `description`), 9.4 (`readOnly`): https://json-schema.org/draft/2020-12
- RFC 9110, sections 8.8.3 (ETag), 13.1.2 (If-None-Match, weak comparison), 15.4.5 (304): https://www.rfc-editor.org/rfc/rfc9110
- RFC 9111, sections 3.5 (authenticated requests) and 5.2.2.4 (`no-cache`): https://www.rfc-editor.org/rfc/rfc9111
- RFC 6901 (JSON Pointer, `~1` for `/` in `instanceLocation`): https://www.rfc-editor.org/rfc/rfc6901
- HTML Standard, the `pattern` attribute (`RegExpCreate(pattern, "v")`): https://html.spec.whatwg.org/multipage/input.html#the-pattern-attribute (`evidence/html-pattern-v-flag.txt`)
- Ajv, Security, Content Security Policy: https://ajv.js.org/security.html (`evidence/ajv-csp.txt`)
- @cfworker/json-schema README and source 4.1.6: https://github.com/cfworker/cfworker/tree/main/packages/json-schema
- PatternFly 6, Form design guidelines (validation on blur or submit, field-level errors, inline alert, "Required"): https://www.patternfly.org/components/forms/form/design-guidelines
- GOV.UK Design System, Validation pattern (turn off HTML5 validation, error summary with focus): https://design-system.service.gov.uk/patterns/validation/
- WCAG 2.2, SC 1.3.1, 2.4.3, 3.3.1, 3.3.2, 3.3.3, 4.1.2, 4.1.3: https://www.w3.org/TR/WCAG22/

## Appendix A: the exact bodies

Pretty-printed here; the route serves the same JSON compact (`separators=(",", ":")`). Generated by
`scripts/proposed.py` from origin/main c7ab6c4, before the `title` field of D6 (which adds a `title` to each titled
property and nothing else).

### A.1 Reference (CRC) config

```json
{
  "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
  "configHash": "f5779009659b7800",
  "labels": {
    "type": "object",
    "properties": {
      "cmapi.net/team": {
        "type": "string",
        "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
        "allOf": [
          {
            "type": "string",
            "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$"
          }
        ],
        "maxLength": 63,
        "minLength": 1,
        "description": "Ownership and cost; any team, not checked against the caller. Must match ^[a-z0-9-]{2,40}$.",
        "examples": [
          "payments"
        ]
      },
      "cmapi.net/cost-center": {
        "type": "string",
        "pattern": "^(?:^cc-[0-9]{4}$)$",
        "allOf": [
          {
            "type": "string",
            "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$"
          }
        ],
        "maxLength": 63,
        "description": "Must match ^cc-[0-9]{4}$.",
        "examples": [
          "cc-4410"
        ]
      },
      "cmapi.net/app": {
        "type": "string",
        "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
        "allOf": [
          {
            "type": "string",
            "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$"
          }
        ],
        "maxLength": 63,
        "description": "Links an app's environments. Must match ^[a-z0-9-]{2,40}$."
      },
      "cmapi.net/rightsizing": {
        "type": "string",
        "pattern": "^(?:^(auto|manual)$)$",
        "allOf": [
          {
            "type": "string",
            "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$"
          }
        ],
        "maxLength": 63,
        "description": "Opt-in to automatic rnd and qa decreases. Must match ^(auto|manual)$."
      },
      "cmapi.net/protected": {
        "type": "string",
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "maxLength": 63,
        "description": "cmapi-operator and above only: a requester gets 403 forbidden.",
        "x-cmapi-operator-only": true
      }
    },
    "required": [
      "cmapi.net/team"
    ],
    "propertyNames": {
      "maxLength": 317,
      "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$",
      "not": {
        "pattern": "^[^/]{254}"
      },
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
          "pattern": "^(?:[^/]+|[^/]*\\.ephico2real\\.com/[^/]+)$"
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
    },
    "title": "Labels",
    "description": "Required: `cmapi.net/team` (must match ^[a-z0-9-]{2,40}$). Optional: `cmapi.net/cost-center` (must match ^cc-[0-9]{4}$); `cmapi.net/app` (must match ^[a-z0-9-]{2,40}$); `cmapi.net/rightsizing` (must match ^(auto|manual)$). Any other key with no prefix, `*.ephico2real.com/`, at most 50.",
    "examples": [
      {
        "cmapi.net/team": "payments"
      }
    ]
  },
  "annotations": {
    "type": "object",
    "properties": {
      "cmapi.net/team-dl": {
        "type": "string",
        "pattern": "^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[eE][pP][hH][iI][cC][oO]2[rR][eE][aA][lL]\\.[cC][oO][mM])$",
        "minLength": 1,
        "description": "The team's mail list, an address in one of emailDomains. An address in ['ephico2real.com'].",
        "examples": [
          "payments-team@ephico2real.com"
        ],
        "x-cmapi-format": "email-in-domains"
      },
      "cmapi.net/protected": {
        "type": "string",
        "description": "cmapi-operator and above only: a requester gets 403 forbidden.",
        "x-cmapi-operator-only": true
      }
    },
    "required": [
      "cmapi.net/team-dl"
    ],
    "propertyNames": {
      "maxLength": 317,
      "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$",
      "not": {
        "pattern": "^[^/]{254}"
      },
      "anyOf": [
        {
          "enum": [
            "cmapi.net/team-dl",
            "cmapi.net/protected"
          ]
        },
        {
          "pattern": "^(?:[^/]+|[^/]*\\.ephico2real\\.com/[^/]+)$"
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
    },
    "title": "Annotations",
    "description": "Required: `cmapi.net/team-dl` (an address in ['ephico2real.com']). Optional: none. Any other key with no prefix, `*.ephico2real.com/`, at most 50, each value at most 4096 bytes and all of them at most 65536 bytes in UTF-8.",
    "examples": [
      {
        "cmapi.net/team-dl": "payments-team@ephico2real.com"
      }
    ]
  }
}
```

### A.2 Company config

```json
{
  "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
  "configHash": "e1e2c26ce01c06d0",
  "labels": {
    "type": "object",
    "properties": {
      "name": {
        "type": "string",
        "readOnly": true,
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "maxLength": 63,
        "description": "A copy of the namespace name. Set by cmapi from the namespace. A request may send the same value, never another.",
        "x-cmapi-derived-from": "namespace"
      },
      "company.net/app-environment": {
        "type": "string",
        "readOnly": true,
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "maxLength": 63,
        "description": "The environment of the namespace's cluster. Set by cmapi from the environment. A request may send the same value, never another.",
        "x-cmapi-derived-from": "environment"
      },
      "company.net/mnemonic": {
        "type": "string",
        "pattern": "^(?:^[a-z]{3,4}$)$",
        "allOf": [
          {
            "type": "string",
            "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$"
          }
        ],
        "maxLength": 63,
        "minLength": 1,
        "description": "The team's mnemonic: the start of the namespace name. Must match ^[a-z]{3,4}$; the start of the namespace name, before its first '-'.",
        "examples": [
          "abc"
        ],
        "x-cmapi-namespace-prefix": true
      },
      "company.net/lob": {
        "type": "string",
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "maxLength": 63,
        "minLength": 1,
        "description": "Line of business, as free text. Any value.",
        "examples": [
          "amgsst"
        ]
      },
      "company.net/cl": {
        "type": "string",
        "maxLength": 63,
        "enum": [
          "0",
          "1",
          "2",
          "3",
          "4",
          "5",
          "6"
        ],
        "minLength": 1,
        "description": "Critical level. One of ['0', '1', '2', '3', '4', '5', '6'].",
        "examples": [
          "1"
        ]
      },
      "cmapi.net/protected": {
        "type": "string",
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "maxLength": 63,
        "description": "cmapi-operator and above only: a requester gets 403 forbidden.",
        "x-cmapi-operator-only": true
      }
    },
    "required": [
      "company.net/mnemonic",
      "company.net/lob",
      "company.net/cl"
    ],
    "propertyNames": {
      "maxLength": 317,
      "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$",
      "not": {
        "pattern": "^[^/]{254}"
      },
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
          "pattern": "^(?:[^/]+|[^/]*\\.company\\.net/[^/]+)$"
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
    },
    "title": "Labels",
    "description": "Required: `company.net/mnemonic` (must match ^[a-z]{3,4}$; the start of the namespace name, before its first '-'); `company.net/lob` (any value); `company.net/cl` (one of ['0', '1', '2', '3', '4', '5', '6']). Optional: none. Any other key with no prefix, `*.company.net/`, at most 50. Set by cmapi, not by the requester: `name` (set by cmapi from the namespace); `company.net/app-environment` (set by cmapi from the environment). A request may send the same value, never another.",
    "examples": [
      {
        "company.net/mnemonic": "abc",
        "company.net/lob": "amgsst",
        "company.net/cl": "1"
      }
    ]
  },
  "annotations": {
    "type": "object",
    "properties": {
      "company.net/app-environment": {
        "type": "string",
        "readOnly": true,
        "description": "Set by cmapi from the environment. A request may send the same value, never another.",
        "x-cmapi-derived-from": "environment"
      },
      "company.net/mnemonic-group-contact": {
        "type": "string",
        "pattern": "^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[cC][oO][mM][pP][aA][nN][yY]\\.[nN][eE][tT])$",
        "description": "The mnemonic's group contact. An address in ['company.net'].",
        "examples": [
          "abc-team@company.net"
        ],
        "x-cmapi-format": "email-in-domains"
      },
      "company.net/mnemonic-confluence": {
        "type": "string",
        "pattern": "^[hH][tT][tT][pP][sS]?://(?:[^/?#\\[\\]\\t-\\r\u001c-    -     　⁇⁈⁉℀℁℅℆⩴︓︖﹕﹖﹟﹫＃／：？＠]+|(?:[^/?#\\[\\]\\t-\\r\u001c-    -     　⁇⁈⁉℀℁℅℆⩴︓︖﹕﹖﹟﹫＃／：？＠]*@)?\\[(?:(?:[0-9A-Fa-f]{1,4}:){6}(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(?:\\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3})|::(?:[0-9A-Fa-f]{1,4}:){5}(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(?:\\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3})|(?:[0-9A-Fa-f]{1,4})?::(?:[0-9A-Fa-f]{1,4}:){4}(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(?:\\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3})|(?:(?:[0-9A-Fa-f]{1,4}:){0,1}[0-9A-Fa-f]{1,4})?::(?:[0-9A-Fa-f]{1,4}:){3}(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(?:\\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3})|(?:(?:[0-9A-Fa-f]{1,4}:){0,2}[0-9A-Fa-f]{1,4})?::(?:[0-9A-Fa-f]{1,4}:){2}(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(?:\\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3})|(?:(?:[0-9A-Fa-f]{1,4}:){0,3}[0-9A-Fa-f]{1,4})?::[0-9A-Fa-f]{1,4}:(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(?:\\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3})|(?:(?:[0-9A-Fa-f]{1,4}:){0,4}[0-9A-Fa-f]{1,4})?::(?:[0-9A-Fa-f]{1,4}:[0-9A-Fa-f]{1,4}|(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(?:\\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3})|(?:(?:[0-9A-Fa-f]{1,4}:){0,5}[0-9A-Fa-f]{1,4})?::[0-9A-Fa-f]{1,4}|(?:(?:[0-9A-Fa-f]{1,4}:){0,6}[0-9A-Fa-f]{1,4})?::)\\](?::[^/?#@\\[\\]\\t-\\r\u001c-    -     　⁇⁈⁉℀℁℅℆⩴︓︖﹕﹖﹟﹫＃／：？＠]*)?)(?:[/?#][^\\t-\\r\u001c-    -     　]*)?$",
        "description": "The mnemonic's Confluence space. An http or https URL.",
        "examples": [
          "https://wiki.company.net/abc"
        ],
        "x-cmapi-format": "url"
      },
      "cmapi.net/protected": {
        "type": "string",
        "description": "cmapi-operator and above only: a requester gets 403 forbidden.",
        "x-cmapi-operator-only": true
      }
    },
    "propertyNames": {
      "maxLength": 317,
      "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$",
      "not": {
        "pattern": "^[^/]{254}"
      },
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
          "pattern": "^(?:[^/]+|[^/]*\\.company\\.net/[^/]+)$",
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
    },
    "title": "Annotations",
    "description": "Required: none. Optional: `company.net/mnemonic-group-contact` (an address in ['company.net']); `company.net/mnemonic-confluence` (an http or https URL). Any other key with no prefix, `*.company.net/`, at most 50, each value at most 4096 bytes and all of them at most 65536 bytes in UTF-8. Set by cmapi, not by the requester: `company.net/app-environment` (set by cmapi from the environment). A request may send the same value, never another.",
    "examples": [
      {}
    ]
  }
}
```
