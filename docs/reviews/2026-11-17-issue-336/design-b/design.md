# #336 design B: the New namespace form from the instance's metadata config

Designer B (OB3, Opus 5.5), 2026-11-17. Written apart from design A, which I did not read.
Base: `origin/main` c7ab6c4 (exported with `git archive` into `notes/main`; the local `main` checkout is 9ba33b2 and
predates #328, #332, #348 and #359, so nothing here is read from it).
Evidence: `evidence/` beside this file. Every number below comes from a script there and its log (see
`evidence/README.md` for the commands). What is not measured is marked **not measured**.

## 1. The problem, as the data shows it

| Fact | Source |
|---|---|
| The form sends `labels: {"cmapi.net/team": team}` and `annotations: {"cmapi.net/team-dl": dl}`, whatever the instance's config | `cmapi-portal-ui/src/portal/NewNamespaceTab.tsx:145-152` |
| On the company config that body is refused with 5 errors: two `invalid_key` (prefix not allowed) and three `missing_required_key` (mnemonic, lob, cl) | `evidence/bodies.log`, line 6 |
| The same body passes on the reference config (`[]`) | `evidence/bodies.log`, last line |
| `/openapi.json` exists only when `docs.enabled` is true | `cmapi/src/cmapi/main.py:183-184` |
| The committed contract's TypeScript type of `NamespaceCreate.labels` makes `"cmapi.net/team"` a required property, so a body built from another config does not type-check: the compile-time copy of the same hard-coding | `docs/reviews/2026-11-16-issue-328/evidence/runs/tsc-dynamic-record.txt` |
| The portal's QueryClient: `retry: false, refetchOnWindowFocus: false, staleTime: 15_000` | `cmapi-portal-ui/src/portal/PortalApp.tsx:118` |
| `samples.json` is written with `sort_keys=True`, so a recorded body's `properties` are in alphabetical order, not the config's | `cmapi/tests/service/test_api_samples.py:345` |

## 2. What the measurements decided

| Question | Measured | Consequence |
|---|---|---|
| Does each schema `pattern` read the same in ECMA-262 (`u` flag) as in the validator (RE2)? | 21,537 verdicts on 15,450 values of the 10 requester-set keys of both configs: **0 differ** (`client_check.log`) | The browser can run the API's patterns with `new RegExp(p, "u")` |
| Is the proposed client check ever stricter than `MetadataKeys.validate()`? | **0** of 15,450 cases. Looser in 5, each the empty value of an optional key, which the form never sends (`client_check.log`) | The form never refuses a value that cmapi accepts, on both configs |
| Can the HTML `pattern` attribute carry them? | 9 of the 12 distinct patterns do not compile with the `v` flag that HTML uses. Chromium 156 then applies **no** constraint: `NOT A TEAM!`, `x@other.com`, `ftp://x` and `free text!` are `valid: true`, with only a console line (`browser.log`). HTML: "if compilation throws, the element has no compiled pattern regular expression" (WHATWG, `#the-pattern-attribute`) | No `pattern` attribute, ever |
| Is `<input type=url>` safe for the url format? | It refuses 3 values that cmapi accepts (`https://a%zz/`, `https://x:abc/`, `https://x:99999/`) (`browser_url.log`) | The url format uses `type="text" inputMode="url"` |
| Is `<input type=email>` safe for email-in-domains? | It refuses `é@company.net`, which cmapi refuses too; it trims spaces and sends an IDN domain as punycode (`browser.log`). WHATWG's local-part set equals `_EMAIL_LOCAL` (`metadata.py:331`); the domain must be a configured ASCII domain (`_DOMAIN`, `metadata.py:46`), so punycode never turns a refused value into an accepted one | `type="email"` stays (today's field, and the mockup's) |
| Can an operator's pattern freeze the browser? | main's loader accepts `^(a+)+b$`, `^(a\|a)*b$` and the everyday `^(?:[a-z0-9]+-?)*[a-z0-9]$` (`redos-loader.log`). V8 needs 944 ms for the last one on 26 characters, x4 per 2 more (`redos-v8.log`); a label value may hold 63 | Each pattern check runs in a Web Worker with a time limit; a check that runs out is "not checked here", and cmapi decides |
| Does the `u` flag matter? | Not on this corpus (0 differences without it, `noflag.log`), but `^[^/]{1,3}$` on `😀😀` is false without `u`, true with it and true in RE2 | `u`, for code points as RE2 and Python count |
| How big is the answer? | 3,397 bytes (reference) and 6,137 bytes (company), compact. A config of 500 + 500 keys and 200 domains: 7.4 MiB, 582 ms to build, because each email key repeats the whole domain regex; 2,000 + 2,000 keys and 1,000 domains: 142 MiB and 11.5 s (`large.log`). The client parses and compiles the 500-key body in 50 ms | The body is built once per process and cached with its ETag. The API compresses nothing (nginx `gzip off` for `/api/`, `cmapi.conf.template:117-120`), so the cap is the config's own size; the repeat is open question 4 |

## 3. Decisions

### D1. The route: `GET /api/v1/metadata-keys`, permission `objects:read`, in the core router

- **Path.** The issue's name, after the file it serves (`metadata-keys.yaml`). One instance has one file; it is not per
  cluster or per environment, so the path takes no parameter.
- **Router.** `routers/me.py` (plugin `core`, group Operations), beside `/me` and `/clusters`. The core routers are
  always on (`core/plugins.py:37-38`), like the metadata config itself (`cfg.metadata`, read by the core pipeline).
  The namespaces router cannot hold it: its prefix is `/api/v1/clusters/{cluster_id}`
  (`plugins/namespaces/router.py:23`), and a plugin has one router (`core/plugins.py:117-124`). A new plugin would be
  missing on every instance whose `plugins.yaml` lists `enabled` explicitly, and the form would get 404 there.
- **Permission** `objects:read`, as `GET /api/v1/tiers` (`plugins/tiers/__init__.py:17`): the least read permission,
  held by every built-in role (docs/14, the table at line 42). `require()` checks it with no environment
  (`routers/__init__.py:48`), and `RolePolicy.permissions(who, None)` takes every held grant, so a role limited to rnd
  reads it (a test proves it, T6). Not `permission=None`: with `docs.public: false` the owner chose that the rules are
  not public, and a token of the realm with no cmapi role should not read them either.
- **Not per caller.** The answer is the instance's, the same for every caller, as `/openapi.json` is. Filtering the
  operator-only keys by role would make it vary by token (`Vary: Authorization`) and put a permission decision in a
  read; the portal does not need it (D4).
- **Independent of docs.** It is under `/api/v1`, behind the token, whatever `docs.enabled` and `docs.public` say.

### D2. The shape: the #328 schemas, exactly, and nothing built beside them

```json
{"labels": <MetadataKeys.json_schema("label", "create")>, "annotations": <MetadataKeys.json_schema("annotation", "create")>}
```

- One generator: `json_schema` is what `_document_metadata` puts into `NamespaceCreate.properties.labels` and
  `.annotations` (`core/docs.py`, `_document_metadata`). The route adds nothing and removes nothing. The API document
  wraps the same object with `title`, `description` and `examples` of the map; a contract test (T3) holds the route's
  body equal to the document's two properties with those three keys taken away, for both configs. So there is no
  second rule source to drift.
- A JSON Schema 2020-12 object is OpenAPI 3.1's own dialect (OpenAPI 3.1.0, Schema Object), so any client can read it
  with a standard validator. The `x-cmapi-*` keywords are annotations to such a validator (JSON Schema 2020-12 Core,
  "Extending JSON Schema": unknown keywords SHOULD be treated as annotations).
- Rejected: a purpose-built list (`[{key, kind, required, pattern, ...}]`). It is a second reading of the rules, which
  is the drift the arbitration ruled out ("no second rule source").
- `create` only. The patch schemas join the answer (a new property, not a breaking change) when a label editor needs
  them (open question 3).

### D3. Caching: built once, served with a strong ETag, `Cache-Control: private, no-cache`

- The body's bytes and their ETag are computed once per loaded `MetadataKeys` (a cache keyed by the object), as
  `/openapi.json` caches its document (`main.py:218-226`).
- `ETag` is a hash of exactly the bytes served (RFC 9110 8.8.3); `If-None-Match` answers `304` by the weak comparison
  (RFC 9110 13.1.2), with the helper `/openapi.json` uses (`main.py:326-331`, moved to `core/etag.py`).
- `private` because the request carries `Authorization` (RFC 9111 3.5, 5.2.2.7); `no-cache` so the browser revalidates
  before each reuse (RFC 9111 5.2.2.4). The ETag is exposed to the portal already (`core/cors.py:31`). Whether
  Chromium revalidates this fetch from its private cache is **not measured**; the design does not depend on it.
- The portal's query: key `["metadata-keys"]`, the app's `staleTime` (15 s), and `refetchOnWindowFocus: true` for this
  query only, so rules that changed while the tab was in the background reach the form when the person comes back.

### D4. How each key class renders

| Class (from the schema) | The form |
|---|---|
| Required, set by the requester (`required[]`, no `readOnly`) | An input, `isRequired`; label `"{title or key} (required)"` |
| Optional, declared (in `properties`, not in `required`, no `readOnly`, no `x-cmapi-operator-only`) | An input in a collapsed `ExpandableSection` of its kind; label `"{title or key} (optional)"`; an empty value is not sent |
| Derived (`readOnly: true`, `x-cmapi-derived-from`) | A read-only `TextInput` (`readOnlyVariant="default"`), label = key, value = what cmapi will write: the namespace name, the environment, the chosen cluster's ID, or `GET /me`'s `instance` (`routers/me.py:21`), never `config.json`'s. **Never sent** (D8) |
| Operator-only (`x-cmapi-operator-only`) | Not shown and never sent. The portal does not compute a permission from a role (MOCKUP-CONTRACT, "Permissions"; the skill, section 4); not sending a key is always allowed |
| Any other allowed key (`propertyNames`, `additionalProperties`, `x-cmapi-other-keys`) | Not offered in this issue. A free-form "other labels" editor is its own issue (open question 3) |
| System, reserved, adoption | Not in `properties`; never shown or sent |

- **Control per rule.** `enum` → `FormSelect` with a first option `value=""` labelled "—" (already the form's empty
  option), so a required enum is a native `required` select; the example is never preselected. Format
  `email-in-domains` → `type="email"`. Format `url` → `type="text" inputMode="url"` (section 2). Anything else →
  `type="text"`, `spellCheck={false}`, `autoComplete="off"`.
- **Words.** Label: the rule's `title` when the config gives one (D5), else the key. The helper text: the key in
  `<code>` when a title is shown, then the schema `description` (the operator's words and the rule's, as Swagger shows
  them). The first `examples` value is the input's placeholder, never its value: JSON Schema 2020-12 Validation 9.5
  calls examples "sample JSON values", not defaults (9.2), and MOCKUP-CONTRACT already starts these fields empty.
- **Sections.** Two `FormSection`s, "Labels" and "Annotations", each with its fields in a two-column `Grid`
  (`md={6}`). A key can be both (the company's `company.net/app-environment`); the section names which one a field is
  (WCAG 2.2, 2.4.6 Headings and Labels; 1.3.1).
- **Order.** Required fields in the order of `required[]` (an array, so its order survives JSON and JavaScript), then
  derived, then optional in `properties` order. JavaScript puts integer-like property names first (`"2024"` is a
  valid label key), so `properties` order is cosmetic only and nothing depends on it.
- **IDs.** `ns-label-0`, `ns-annotation-3`: by kind and index, never the key, so no config text reaches an `id`, an
  `aria-describedby` list or a CSS selector.
- **Layout.** Environment; Region | Cluster; Labels; Annotations; Namespace name; Tier; Expires; Justification. The
  mockup's "Team" sat beside Region because the name follows it; here the key fields come before the name for the
  same reason. The "Requested by … from your sign-in." line becomes its own hint under Annotations.
- **The suggested name.** `{value}-{environment}` from the required label with `x-cmapi-namespace-prefix` (the
  company's mnemonic: `abc-rnd`, the owner's sample); with none, from the first entry of `labels.required` that the
  person fills (the reference: `cmapi.net/team`, `payments-dev`, the mockup's behaviour, test 9 unchanged). A name the
  person types always wins. Open question 2 asks the owner to confirm the fallback.

### D5. Two additions to the #328 generator: `title` and `x-cmapi-rule`

- `title`, an optional text field of a rule in `metadata-keys.yaml`, emitted as the property's JSON Schema `title`
  (Validation 9.1: title is short, description explains). It gives the mockup's labels ("Team", "Team DL") from the
  config instead of a map of key names in the portal.
- `x-cmapi-rule`: `rule.text(email_domains)`, the words the validator puts in a refusal's `detail`
  (`metadata.py:520-535`, `:867-868`). The form's error text uses them, so the browser and the API say the same thing.
- Both are annotations: oasdiff does not count them as breaking (the #328 gate), and `validate()` does not read them.
- Rejected: a portal map from the two reference keys to the mockup's words. It is a second place that knows key
  names, and it would keep saying "Team DL (required)" on an instance where that key became optional.

### D6. The reference config takes the mockup's words

`cmapi.net/team`: `title: Team`, description "Who owns it, for cost and notices: any team name. Not checked against
who you are; your Keycloak roles decide what you may do". `cmapi.net/team-dl`: `title: Team DL`, description "Your
team's distribution list, in one of the organisation's email domains (emailDomains); format only". These are the
mockup's hints (`mockups/portal/Main.dc.html:445`, `:472`), so the reference instance shows the mockup's words from its
own config. The company sample keeps no titles, so its fields show the keys: the fallback is tested too.

### D7. Client-side checks: the server's published rules, never stricter, time-bounded

The skill says validation logic belongs to the server and is ported into the page only as a test fixture
(section 5). This design ports no logic: the page evaluates the keywords the server publishes, and a differential test
(T12) proves on every value of the corpus that it never refuses what the validator accepts. cmapi stays the authority.

For one field, the first failure wins, in the validator's own order (`_syntax`, then `_governed`):

1. Empty: required → `Required: {x-cmapi-rule}` (the validator's `missing_required_key` detail); optional → no error,
   not sent.
2. A label: `labels.additionalProperties` (`maxLength` 63, the label-value `pattern`) → "Not a valid label value"
   (the validator's `invalid_value` detail, `metadata.py:891`).
3. `enum` → cannot fail: a select.
4. Each `pattern` of the property and of its `allOf`, except the label-value one already checked → `Not valid:
   {x-cmapi-rule}`. Run with `new RegExp(p, "u")`, in a worker (below).
5. `x-cmapi-namespace-prefix` and a name: `{name} does not start with {value}-` (the validator's words,
   `metadata.py:920`).
6. `maxLength`/`minLength` count code points (`[...value].length`), as JSON Schema does ("characters as defined by
   RFC 8259", Validation 6.3.1) and as Python does.

**The worker.** `src/portal/patternWorker.ts`, a module worker that Vite emits as its own file, so the portal's CSP
(`script-src 'self'`, no `worker-src`, which falls back to `script-src`: CSP Level 3, worker-src) allows it with no
`blob:`. One request: `{id, pattern, value}` → `{id, ok}`, the `RegExp` compiled once per pattern. The page waits
200 ms; past that it ends the worker, starts a new one, marks the pattern slow for the session and answers `null`
("not checked here"). A `null` shows no error; the dry run gives the API's verdict. Checks run 150 ms after the last
keystroke and are awaited before a dry run or a submit.

**Blocking.** Each input gets `setCustomValidity(message)` from the check, so the native validation that the form
already relies on (`noValidate={false}`, test 9 "the browser's own checks") blocks Submit and focuses the first invalid
field. Dry run, a `type="button"` that native validation skips, calls `form.reportValidity()` first and plans only a
valid form. The error is also shown as text under the field (below).

### D8. What the form sends

`labels` and `annotations` hold exactly the shown requester fields with a non-empty value, both maps always present
(the reference schema requires both; the company's accepts `{}`). Never a derived key: the validator accepts the same
value and refuses another (`bodies.log`: `name: "abc"` → `derived_key`), so sending it only adds a way to be wrong.
Never an empty optional key (`bodies.log`: `""` for the URL key → `invalid_value`). Never an operator-only key
(`bodies.log`: → `operator_only_key`, a 403).

The body's TypeScript type: `CreateBody = Omit<NamespaceCreate, "labels" | "annotations"> & { labels:
Record<string, string>; annotations: Record<string, string> }`, cast to `NamespaceCreate` in one place in `hooks.ts`,
with the reason: the committed contract types the reference config's keys, and the instance's keys come from this
route.

### D9. The API's refusal, mapped to the fields

`ApiProblem` keeps the problem's `errors` (RFC 9457 allows extension members; cmapi's are `{code, key, kind?, detail?}`,
`core/errors.py:32`). For a refused dry run or submit:

| `errors[]` item | Shown |
|---|---|
| `key` names a shown field (`kind` too when given; else the label field first) | Under that field, its `detail` (or its `code` when there is no detail), `validated="error"` |
| `missing_required_key`, `invalid_key` or `derived_key` for a key the form does not show | In the callout, and the form reads the rules again (D10) |
| Anything else (`reserved_key`, `too_many_keys`, `annotations_too_large`, a rendered-file finding) | In the callout's list, `{key or kind}: {detail or code}` |

The callout stays the mockup's "Refused: {code}" with the problem's `detail`, and gains the list, each item a link
button that focuses its field (an error summary). A 403 for an operator-only key is a `forbidden` problem with its
detail (`metadata.py:928-930`), shown the same way. An edit to the form clears them, as it clears the plan today.

### D10. A config change while the form is open

The API loads the file at start, and a change restarts the pods (`checksum/config`, arbitration "Where the rules are
set"). So an open form can hold rules that an instance no longer has. Three things meet it:

1. The query is read again on window focus and on each opening of the tab (D3).
2. A refusal that names a key the form does not show reads the rules again (D9).
3. When the rules change after the form loaded, the form re-renders from the new rules: values of keys that remain
   stay, a new key is empty, a removed key's value is dropped and never sent. A warning `Alert` (isInline) says "The
   label and annotation rules of this instance changed. Check the fields below." (the skill's `conflict` state). The
   body changes, so the plan on the page is hidden, as for any edit.

During a rolling update two pods can answer with two configs; the form follows the last answer and the API decides.

### D11. States

The route is a third read of the form, beside the clusters and the tiers. It follows the form's states
(MOCKUP-CONTRACT, "The states of the Workflow, New namespace and Approvals tabs"): loading → "Loading the form…";
403 → "You do not have permission to request a namespace." with the detail; 5xx or no answer → "The form did not
load." and "Try again", which reloads all three; 401 → the client's renewal. An answer that is not the expected shape
(no `labels.properties`, a property that is not an object) is an error with the cause "The metadata rules of this
instance are not in the form this portal reads.", never a form with fields missing.

### D12. Accessibility (WCAG 2.2)

| Criterion | How |
|---|---|
| 1.3.1, 4.1.2 | Each input has a `<label for>` through `FormGroup fieldId`; required inputs carry `required` (`aria-required`); the read-only ones `readonly`, not `disabled`, so a screen reader reads them and they keep their contrast |
| 3.3.2 Labels or Instructions | "(required)"/"(optional)" in the label text, not an asterisk alone; the rule in the helper text before any error |
| 3.3.1 Error Identification, 3.3.3 Error Suggestion | The error under the field in text, `aria-invalid` through `validated="error"`, `HelperTextItem variant="error"` (icon and text, so not colour alone: 1.4.1), linked by `aria-describedby`; the message names the rule |
| 4.1.3 Status Messages | The refused callout is an inline `Alert`; the rules-changed warning too. The worker's "not checked here" says nothing |
| 2.4.3 Focus Order | Native validation focuses the first invalid field; the error summary's buttons move focus to their field |
| 1.4.3 Contrast | The placeholder (an example) is text: axe's colour check runs on the form at 390 and 1440 px in both themes (T20). Whether axe measures placeholder contrast is **not measured**; the implementer reads the computed colour once and records it |

## 4. Threats, and what meets each

| Threat | Met by | Test |
|---|---|---|
| A value the form allows and cmapi refuses | The client check is a subset of the server's; what it cannot see (count and bytes of other keys, a pattern that ran out of time, a lone surrogate) cmapi refuses and D9 shows | T12, T15 |
| A value the form refuses and cmapi accepts | 0 in 15,450 cases; no `type=url`, no `pattern` attribute | T12, M4, M12 |
| A pattern that reads otherwise in the browser | `u` flag, 0/21,537 differences; the `v`-flag `pattern` attribute is never used | T12, M4 |
| An operator's pattern that backtracks | The worker and its 200 ms limit | T16, M5 |
| A derived key the person tries to edit | Read-only, never sent, its value shown | T13, M6, M7 |
| Operator-only keys | Not shown, not sent | T13, M10 |
| A config change while the form is open | D10 | T17, M13 |
| A very large config | Built once and cached; 50 ms of client work at 500 + 500 keys | T5 (cache), `large.log` |
| docs disabled | The route does not depend on docs | T4 |
| Unauthenticated, no permission, limited to one environment | 401; 403 and the forbidden state; 200 | T6, T18 |
| A config whose answer the portal cannot read | D11's error state, never a partial form | T19 |
| A new schema keyword the portal ignores | The contract test fails | T21 |
| HTML or script in a description | Rendered as React text; never `dangerouslySetInnerHTML` | Code read |

## 5. Options rejected

| Option | Why not |
|---|---|
| Read `/openapi.json` from the portal | Off when `docs.enabled` is false (the issue's reason), and behind other rules when `docs.public` is false |
| A purpose-built field list | A second rule source (D2) |
| A plugin of its own, or the namespaces plugin | 404 on instances with an explicit `enabled` list; the namespaces router's prefix is per cluster (D1) |
| `permission=None` | Exposes the rules to any token of the realm, against `docs.public: false` |
| The HTML `pattern` attribute | 9 of 12 patterns do not compile with `v`; Chromium then checks nothing (`browser.log`) |
| `type="url"` | Stricter than cmapi on 3 values (`browser_url.log`) |
| Patterns on the main thread | 944 ms at 26 characters for a pattern the loader accepts (`redos-v8.log`) |
| A static "safe regex" check (star height) | `(a\|a)*` has star height 1 and backtracks as badly; only a time limit holds for every pattern |
| Prefilling with the example | An example is not a default (Validation 9.2, 9.5); a person could submit the sample team |
| Showing operator-only keys to operators | The portal would decide a permission from a role name; nothing in this issue needs it |
| A portal map of the reference keys to the mockup's words | Two places know key names; it lies when an instance changes a key (D5) |

## 6. The answer, exactly

The body for each config, as this design specifies it (main's generator with D5's two additions and the reference
config with D6's words), is in `evidence/designed-response-reference.json` (3,397 bytes compact) and
`evidence/designed-response-company.json` (6,137 bytes compact), produced by `evidence/designed_response.py`. The
answers of main's generator as it is, without D5 and D6, are `evidence/response-*.json`. The reference body in full:

```json
{
  "labels": {
    "type": "object",
    "properties": {
      "cmapi.net/team": {"type": "string", "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
        "allOf": [{"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$"}],
        "maxLength": 63, "minLength": 1, "title": "Team",
        "description": "Who owns it, for cost and notices: any team name. Not checked against who you are; your Keycloak roles decide what you may do. Must match ^[a-z0-9-]{2,40}$.",
        "x-cmapi-rule": "must match ^[a-z0-9-]{2,40}$", "examples": ["payments"]},
      "cmapi.net/cost-center": {"type": "string", "pattern": "^(?:^cc-[0-9]{4}$)$",
        "allOf": [{"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$"}],
        "maxLength": 63, "description": "Must match ^cc-[0-9]{4}$.", "x-cmapi-rule": "must match ^cc-[0-9]{4}$", "examples": ["cc-4410"]},
      "cmapi.net/app": {"type": "string", "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
        "allOf": [{"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$"}],
        "maxLength": 63, "description": "Links an app's environments. Must match ^[a-z0-9-]{2,40}$.", "x-cmapi-rule": "must match ^[a-z0-9-]{2,40}$"},
      "cmapi.net/rightsizing": {"type": "string", "pattern": "^(?:^(auto|manual)$)$",
        "allOf": [{"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$"}],
        "maxLength": 63, "description": "Opt-in to automatic rnd and qa decreases. Must match ^(auto|manual)$.", "x-cmapi-rule": "must match ^(auto|manual)$"},
      "cmapi.net/protected": {"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$", "maxLength": 63,
        "description": "cmapi-operator and above only: a requester gets 403 forbidden.", "x-cmapi-operator-only": true}
    },
    "required": ["cmapi.net/team"],
    "propertyNames": {"maxLength": 317,
      "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$",
      "not": {"pattern": "^[^/]{254}"},
      "anyOf": [{"enum": ["cmapi.net/team", "cmapi.net/cost-center", "cmapi.net/app", "cmapi.net/rightsizing", "cmapi.net/protected"]},
                {"pattern": "^(?:[^/]+|[^/]*\\.ephico2real\\.com/[^/]+)$"}]},
    "additionalProperties": {"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$", "maxLength": 63},
    "x-cmapi-other-keys": {"prefixes": ["", "*.ephico2real.com/"], "max": 50}
  },
  "annotations": {
    "type": "object",
    "properties": {
      "cmapi.net/team-dl": {"type": "string",
        "pattern": "^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[eE][pP][hH][iI][cC][oO]2[rR][eE][aA][lL]\\.[cC][oO][mM])$",
        "minLength": 1, "title": "Team DL",
        "description": "Your team's distribution list, in one of the organisation's email domains (emailDomains); format only. An address in ['ephico2real.com'].",
        "x-cmapi-rule": "an address in ['ephico2real.com']", "examples": ["payments-team@ephico2real.com"], "x-cmapi-format": "email-in-domains"},
      "cmapi.net/protected": {"type": "string", "description": "cmapi-operator and above only: a requester gets 403 forbidden.", "x-cmapi-operator-only": true}
    },
    "required": ["cmapi.net/team-dl"],
    "propertyNames": {"maxLength": 317,
      "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$",
      "not": {"pattern": "^[^/]{254}"},
      "anyOf": [{"enum": ["cmapi.net/team-dl", "cmapi.net/protected"]}, {"pattern": "^(?:[^/]+|[^/]*\\.ephico2real\\.com/[^/]+)$"}]},
    "additionalProperties": {"type": "string", "maxLength": 4096},
    "x-cmapi-other-keys": {"prefixes": ["", "*.ephico2real.com/"], "max": 50, "maxValueBytes": 4096, "maxBytesTotal": 65536}
  }
}
```

The company body, in the same form (the URL regex shortened here to `<_URL>`; the file has it whole):

```json
{
  "labels": {
    "type": "object",
    "properties": {
      "name": {"type": "string", "readOnly": true, "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$", "maxLength": 63,
        "description": "A copy of the namespace name. Set by cmapi from the namespace. A request may send the same value, never another.",
        "x-cmapi-rule": "set by cmapi from the namespace", "x-cmapi-derived-from": "namespace"},
      "company.net/app-environment": {"type": "string", "readOnly": true, "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$", "maxLength": 63,
        "description": "The environment of the namespace's cluster. Set by cmapi from the environment. A request may send the same value, never another.",
        "x-cmapi-rule": "set by cmapi from the environment", "x-cmapi-derived-from": "environment"},
      "company.net/mnemonic": {"type": "string", "pattern": "^(?:^[a-z]{3,4}$)$",
        "allOf": [{"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$"}], "maxLength": 63, "minLength": 1,
        "description": "The team's mnemonic: the start of the namespace name. Must match ^[a-z]{3,4}$; the start of the namespace name, before its first '-'.",
        "x-cmapi-rule": "must match ^[a-z]{3,4}$; the start of the namespace name, before its first '-'", "examples": ["abc"], "x-cmapi-namespace-prefix": true},
      "company.net/lob": {"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$", "maxLength": 63, "minLength": 1,
        "description": "Line of business, as free text. Any value.", "x-cmapi-rule": "any value", "examples": ["amgsst"]},
      "company.net/cl": {"type": "string", "maxLength": 63, "enum": ["0", "1", "2", "3", "4", "5", "6"], "minLength": 1,
        "description": "Critical level. One of ['0', '1', '2', '3', '4', '5', '6'].", "x-cmapi-rule": "one of ['0', '1', '2', '3', '4', '5', '6']", "examples": ["1"]},
      "cmapi.net/protected": {"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$", "maxLength": 63,
        "description": "cmapi-operator and above only: a requester gets 403 forbidden.", "x-cmapi-operator-only": true}
    },
    "required": ["company.net/mnemonic", "company.net/lob", "company.net/cl"],
    "propertyNames": {"maxLength": 317,
      "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$",
      "not": {"pattern": "^[^/]{254}"},
      "anyOf": [{"enum": ["name", "company.net/app-environment", "company.net/mnemonic", "company.net/lob", "company.net/cl", "cmapi.net/protected"]},
                {"pattern": "^(?:[^/]+|[^/]*\\.company\\.net/[^/]+)$"}]},
    "additionalProperties": {"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$", "maxLength": 63},
    "x-cmapi-other-keys": {"prefixes": ["", "*.company.net/"], "max": 50}
  },
  "annotations": {
    "type": "object",
    "properties": {
      "company.net/app-environment": {"type": "string", "readOnly": true,
        "description": "Set by cmapi from the environment. A request may send the same value, never another.",
        "x-cmapi-rule": "set by cmapi from the environment", "x-cmapi-derived-from": "environment"},
      "company.net/mnemonic-group-contact": {"type": "string",
        "pattern": "^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[cC][oO][mM][pP][aA][nN][yY]\\.[nN][eE][tT])$",
        "description": "The mnemonic's group contact. An address in ['company.net'].", "x-cmapi-rule": "an address in ['company.net']",
        "examples": ["abc-team@company.net"], "x-cmapi-format": "email-in-domains"},
      "company.net/mnemonic-confluence": {"type": "string", "pattern": "<_URL>",
        "description": "The mnemonic's Confluence space. An http or https URL.", "x-cmapi-rule": "an http or https URL",
        "examples": ["https://wiki.company.net/abc"], "x-cmapi-format": "url"},
      "cmapi.net/protected": {"type": "string", "description": "cmapi-operator and above only: a requester gets 403 forbidden.", "x-cmapi-operator-only": true}
    },
    "propertyNames": {"maxLength": 317,
      "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$",
      "not": {"pattern": "^[^/]{254}"},
      "anyOf": [{"enum": ["company.net/app-environment", "company.net/mnemonic-group-contact", "company.net/mnemonic-confluence", "cmapi.net/protected"]},
                {"pattern": "^(?:[^/]+|[^/]*\\.company\\.net/[^/]+)$", "not": {"anyOf": [{"enum": ["name"]}]}}]},
    "additionalProperties": {"type": "string", "maxLength": 4096},
    "x-cmapi-other-keys": {"prefixes": ["", "*.company.net/"], "max": 50, "maxValueBytes": 4096, "maxBytesTotal": 65536}
  }
}
```

What the form shows from them:

| Config | Labels | Annotations | Body after filling the required fields |
|---|---|---|---|
| Reference | Team (required); Optional labels (3): cmapi.net/cost-center, cmapi.net/app, cmapi.net/rightsizing | Team DL (required) | `{"labels": {"cmapi.net/team": "payments"}, "annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"}}`: today's body, byte for byte |
| Company | company.net/mnemonic (required), company.net/lob (required), company.net/cl (required, a select); read-only `name` = the namespace, `company.net/app-environment` = the environment | read-only `company.net/app-environment`; Optional annotations (2): the group contact (`type=email`), the Confluence space (`inputMode=url`) | `{"labels": {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}, "annotations": {}}`, namespace `abc-rnd`: `validate()` returns `[]` (`bodies.log`) |

## 7. Changes, file by file

### cmapi (Python)

**`cmapi/src/cmapi/core/metadata.py`**

- `_RULE_FIELDS` gains `"title"`; `KeyRule` gains `title: str | None = None`; `_add` checks it in the existing loop
  (`("title", str)` beside description and example) and passes `title=spec.get("title")`.
- `_rule_schema`, after the `words` list:

```python
        if rule.title is not None:
            out["title"] = rule.title
        out["description"] = " ".join(w[:1].upper() + w[1:].rstrip(".") + "." for w in words)
        # The words of a refusal's detail (validate, missing_required_key), so a client says what the API says (#336).
        out["x-cmapi-rule"] = rule.text(self.email_domains)
```

- `_nullable` moves `title` out of the inner schema with `description` and `examples`
  (`for k in ("title", "description", "examples")`), so a patch's property keeps its words at the `anyOf` level.
- A new method, the one the route serves:

```python
    def keys_view(self) -> dict[str, Any]:
        """GET /api/v1/metadata-keys (#336): the schemas of NamespaceCreate's labels and annotations, the same objects that
        the API document holds (_document_metadata), without the document's words around them. For a client such as the
        portal when /openapi.json is off (docs.enabled: false)."""
        return {"labels": self.json_schema("label", "create"), "annotations": self.json_schema("annotation", "create")}
```

**`cmapi/src/cmapi/core/etag.py`** (new): `etag_of(body: bytes) -> str` (the quoted 32-hex SHA-256 prefix
`main.py:225` uses) and `etag_matches(if_none_match, etag)` (the body of `main.py:326-331`). `main.py` imports both and
drops its private copies. Then `python scripts/doc-citations.py --relocate` and `--check`: `main.py:142-144`, `:169`
and `:122-123` are cited (docs/citations.lock.json).

**`cmapi/src/cmapi/core/models.py`**: the response model.

```python
class MetadataKeysView(Api):
    """The instance's rules for the labels and annotations of a new namespace (metadata-keys.yaml)."""
    labels: dict[str, Any] = Field(
        description="JSON Schema 2020-12 of NamespaceCreate.labels on this instance: the same object as in the API document",
        examples=[{"type": "object", "properties": {"cmapi.net/team": {"type": "string", "pattern": "^(?:^[a-z0-9-]{2,40}$)$"}},
                   "required": ["cmapi.net/team"]}])
    annotations: dict[str, Any] = Field(
        description="JSON Schema 2020-12 of NamespaceCreate.annotations on this instance",
        examples=[{"type": "object", "properties": {"cmapi.net/team-dl": {"type": "string", "x-cmapi-format": "email-in-domains"}},
                   "required": ["cmapi.net/team-dl"]}])
```

**`cmapi/src/cmapi/routers/me.py`**: appended after `clusters` (line 28), so the cited lines 15-21 do not move.

```python
@functools.lru_cache(maxsize=4)          # one entry per loaded MetadataKeys: a process holds one
def _keys_document(keys: MetadataKeys) -> tuple[bytes, str]:
    body = json.dumps(keys.keys_view(), separators=(",", ":"), ensure_ascii=False).encode()
    return body, etag_of(body)


@router.read("/metadata-keys", summary="The rules of labels and annotations", permission="objects:read",
             response_model=MetadataKeysView)
def metadata_keys(request: Request, who: Identity = Depends(require("objects:read")),
                  c: AppContext = Depends(ctx)) -> Response:
    """The instance's metadata-keys.yaml as the JSON Schema of a new namespace's labels and annotations: each declared
    key with its rule, which keys are required, which cmapi sets (readOnly) and which only cmapi-operator may set. The
    same schemas as NamespaceCreate in the API document, here also when docs.enabled is false. cmapi checks every
    request against the file itself; this answer describes it."""
    body, etag = _keys_document(c.cfg.metadata)
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)
```

`CORE["description"]` (`core/docs.py:120-122`) adds "and the rules of its labels and annotations".

**Config files** (D6): `examples/cluster-configs/policies/metadata-keys.yaml`, its copy
`deploy/helm/cmapi/config/metadata-keys.yaml` (identical today), `examples/local/config/metadata-keys.yaml` and the CRC
copy in `deploy/manifests/environments/crc/20-config.yaml:338`: `title` and the mockup's description on the two keys.
**`deploy/helm/cmapi/values.schema.json`**: the rule definition (`additionalProperties: false`, line 129) gains
`"title": {"type": "string", "description": "A short label for a form; the key when absent"}`.
**`docs/18-configuration.md`**: `title` in the rule fields. **`docs/14-authorization.md:88`**: `GET
/api/v1/metadata-keys` in the `objects:read` row. **`docs/02`**/**`docs/04`**: the route, regenerated with
`scripts/api-examples-doc.py`.

**Contract**: `cmapi/contract/openapi.json` (the new path and the D5/D6 words), `cmapi/src/cmapi/contract/samples.json`
(a recorded `core_metadata_keys`, added to the walk in `test_api_samples.py` beside `tiers_tiers`).

### cmapi-portal-ui (TypeScript)

| File | Change |
|---|---|
| `src/api/schema.generated.ts`, `permissions.generated.ts` | `npm run api:types` |
| `src/api/problem.ts` | `ApiProblem.errors: ProblemItem[]` (`{code: string; key?: string; kind?: string; detail?: string}`), read from the body when it is an array of objects; others dropped |
| `src/api/hooks.ts` | `useMetadataKeys()` (D3); `Outcome` `refused` gains `errors`; `CreateBody` and the one cast (D8) in `usePlan` and `useSubmitNamespace` |
| `src/portal/metadataForm.ts` (new) | `fieldsOf(view): MetaField[]` (parse and shape check, D11); `bodyOf(fields, values)` (D8); `checkField(field, value, ctx, patternCheck)` (D7); `nameSuggestion(fields, values, env)` (D4); `errorsByField(errors, fields)` (D9). Pure functions, no React |
| `src/portal/patternWorker.ts` (new), `src/portal/patterns.ts` (new) | The worker and its client with the 200 ms limit (D7) |
| `src/portal/NewNamespaceTab.tsx` | The `team` and `dl` state and their two fields go; a `values: Record<string, string>` keyed `kind:key`; the two `FormSection`s; the states of D11; D9's mapping; D10's warning |
| `MOCKUP-CONTRACT.md` | The New namespace rows of section "Where the portal's New namespace tab differs": D4's sections, labels, placeholders, read-only keys, optional groups, the layout, the name rule, D7's words, D10's warning; the "Tabs" table adds `GET /api/v1/metadata-keys` (a path in backticks is not read as a dataset name by `tests/contract.test.mjs`) |
| `tests/api/standin.mjs` | `GET /api/v1/metadata-keys` from `state.metadataKeys` (the recorded sample) with `objects:read`; `state.metadataKeys` can be set to the company fixture; the create checks the body against a list of required keys taken from the served schema and answers the recorded 422 shape otherwise |
| `tests/api/metadata-keys.company.json` (new) | The company body, written by T7 |
| `tests/api/portal.test.mjs`, `tests/api/mutants.mjs` | Section 8 |

`docs/09-portal-ui-testing.md` takes the measured counts after the run, as for each slice.

## 8. Tests

Each fails on main c7ab6c4 for the reason given; each new portal check must be killed by its mutants.

### Service and core (pytest, `policy.engine: none` as the arbitration asks)

| # | Test | Fails before because |
|---|---|---|
| T1 | `GET /api/v1/metadata-keys` as `cmapi-requester` on the reference instance: 200, body == `cfg.metadata.keys_view()`, `labels.required == ["cmapi.net/team"]`, `annotations.required == ["cmapi.net/team-dl"]` | 404: no route |
| T2 | The same on an instance loaded with `metadata-keys.company.yaml`: `labels.required == [mnemonic, lob, cl]`, `name` and `company.net/app-environment` `readOnly` | 404 |
| T3 | Contract, both configs: the route's `labels`/`annotations` == `/openapi.json`'s `NamespaceCreate.properties.labels`/`.annotations` minus `title`, `description`, `examples` | 404 |
| T4 | `docs.enabled: false`: `/openapi.json` 404 and the route 200 with the same body | 404 |
| T5 | ETag and caching: 200 with `ETag` and `Cache-Control: private, no-cache`; the same `If-None-Match` → 304 with no body; `W/` and `*` forms → 304; a second call does not call `json_schema` again (a spy) | 404 |
| T6 | 401 with `WWW-Authenticate` and no token; 403 `forbidden` for a role with no `objects:read`; 200 for a role limited to rnd | 404 |
| T7 | `tests/api/metadata-keys.company.json` == `MetadataKeys.load(company).keys_view()` (exact; `CMAPI_WRITE_FIXTURES=1` writes it) | No such method or file |
| T8 | `title`: a rule with `title: Team` → the property's `title`; `title: 3` is refused at load ("title must be text"); the patch schema keeps it outside the `anyOf` | `title` is an unknown field: the loader refuses the file |
| T9 | `x-cmapi-rule` == `rule.text(domains)` for each declared key of both configs, and == the `detail` of `missing_required_key` for each required one | No such keyword |
| T10 | Helm: `helm lint` with a `metadata:` block whose rule has `title` passes; with `titel` fails (`values.schema.json`) | `title` is refused by `additionalProperties: false` |
| T11 | `check_documented` passes with the route (startup); `samples.json` has `core_metadata_keys` | No sample: `test_api_samples` fails for the missing operation |

### Portal (`tests/api/portal.test.mjs`, the stand-in API)

| # | Check | Fails before because |
|---|---|---|
| T12 | Differential, in Node (no browser): `clientCheck` of `metadataForm.ts` on `evidence/corpus.py`'s corpus (regenerated in CI from both configs) is never stricter than the validator's verdict: 0 cases. Runs in `tests/api/direct.test.mjs` | No `metadataForm.ts` |
| T13 | **Company config** (the issue's proof): the fields are the mnemonic, lob and cl inputs (required), `name` and `company.net/app-environment` read-only with `abc-rnd` and `rnd`; no `cmapi.net/protected`, no `cmapi.net/team`; typing `ABC` in the mnemonic shows "Not valid: must match ^[a-z]{3,4}$; …" and Submit and Dry run send nothing; `abc` with name `xyz-rnd` shows "xyz-rnd does not start with abc-"; a valid form's dry-run body is exactly D8's company body | The form shows Team and Team DL, and sends the hard-coded keys |
| T14 | **Reference config**: the fields are "Team (required)" and "Team DL (required)" with the mockup's hints; the optional group holds 3 labels; the dry-run body is today's (test 9's assertion stays as it is); the name suggestion is `payments-dev` | The labels say "Team" and "Team DL (required)" from code, not from the API (passes only after the D6 change; before it, the check of the route call fails: no `GET /api/v1/metadata-keys`) |
| T15 | Server errors: the stand-in answers a dry run with 422 `policy-violation` and `errors` for `company.net/lob` (invalid_value), `cmapi.net/x` (reserved_key) and a missing key the form does not show: the first is under the lob field, the second in the callout list, the third makes the page call the route again | `ApiProblem` drops `errors` |
| T16 | ReDoS: a stand-in config with `^(?:[a-z0-9]+-?)*[a-z0-9]$` on a required label; typing 40 characters ending in `!`: within 1 s the page answers a `page.evaluate(() => 1)` and the Justification field takes a key; the field shows no client error; the dry run shows the API's refusal | No worker: the main thread is busy for minutes |
| T17 | Config change: after the form loads, the stand-in serves another config; a window focus reloads it; a removed key's field and value are gone from the next dry-run body, a new required key is empty and required, and the warning shows | The form has no rules to reload |
| T18 | States: the route's 403 → the forbidden state with its detail; its 500 → "The form did not load." and Try again reloads it; the rnd-only requester gets the form | No route call |
| T19 | A malformed answer (`labels: []`) → the error state with D11's cause, no form | No route call |
| T20 | Layout at 390, 820 and 1440 px in both themes and axe at phone and desktop width, on both configs (the existing check 7, run a second time with the company fixture) | The company form does not exist |
| T21 | Contract, in `tests/contract.test.mjs`: every keyword of every `properties` entry of both fixtures is one that `metadataForm.ts` reads or lists as ignored | No list |
| T22 | Parity (check 6): the New namespace strings with the reference config, with D4's and D7's additions listed in `ADDED` and in MOCKUP-CONTRACT.md | The labels and hints change |

### Mutants (`tests/api/mutants.mjs`), each named to the check that must kill it

| # | Mutant | Killed by |
|---|---|---|
| M1 | A field dropped: `fields.slice(1)` where the required fields render (the issue's mutant) | T13 |
| M2 | The hard-coded body back: `labels: { "cmapi.net/team": ... }` | T13 |
| M3 | The pattern check returns `null` | T13 |
| M4 | The pattern as an `<input pattern>` and no worker check | T13 (`ABC` is sent) |
| M5 | The pattern test on the main thread | T16 |
| M6 | Derived keys added to the body | T13 (body) |
| M7 | Derived inputs not read-only | T13 |
| M8 | Empty optional keys sent | T14 (body) |
| M9 | `errors` not mapped to fields | T15 |
| M10 | Operator-only keys shown | T13 |
| M11 | No prefix check | T13 |
| M12 | `type="url"` for the url format | T13 (the stand-in config's Confluence value `https://wiki.company.net:abc/x`, which cmapi accepts, must reach the dry run) |
| M13 | No reload on a refusal that names an unknown key | T15 |
| M14 | The example as the value instead of the placeholder | T13 (the mnemonic must start empty) |
| M15 | Length counted in UTF-16 units | T12 |

## 9. Open questions for the coordinator and the owner

1. **`title` in `metadata-keys.yaml` (D5, D6).** It touches the loader, the Helm schema, docs/18 and the four config
   copies. Without it the reference form shows `cmapi.net/team (required)` instead of the mockup's "Team", recorded
   in MOCKUP-CONTRACT. I recommend `title`. Should the company sample also get titles (Mnemonic, Line of business,
   Critical level)? I left them out so the key fallback is tested; it is the owner's file (#358).
2. **The suggested name's fallback** (D4): the first required label when no key has `namespacePrefix`. It keeps the
   mockup's `payments-dev`; on another config it can suggest an odd name (`cc-4410-dev`), which the person sees and
   can change. The other choice is no suggestion without `namespacePrefix`, which changes test 9.
3. **Out of scope here:** a free-form editor for `allowOther` keys, and the patch schemas for the Quotas tab's label
   changes. Each is its own issue.
4. **The email regex repeated per key** (`large.log`: 7.4 MiB at 500 + 500 keys and 200 domains). Realistic configs
   are 3–6 KiB. A `$defs` entry with one `$ref` per email key would remove the repeat, in `/openapi.json` too; it is a
   change of the #328 generator and its contract gate, so a separate issue if the owner wants it.
5. **Backtracking in other clients.** The loader accepts patterns that backtrack exponentially in any ECMA-262
   engine (`redos-loader.log`). cmapi is safe (RE2, #348) and the portal is bounded (D7), but a client that validates
   the `/openapi.json` body with Ajv is not. A docs/18 note under "Patterns", or a load-time warning for nested
   quantifiers (a heuristic, not a guarantee): the coordinator's call.
6. **Seen while measuring, not in scope:** the url format accepts `https://x:abc/` and `https://a%zz/`
   (`browser_url.log`), which no URL parser accepts. Worth an issue only if a consumer of that annotation parses it.
