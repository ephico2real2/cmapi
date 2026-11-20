# Implementation plan: the API documentation standard, the namespace contract and the New namespace form

Status: **plan for the owner's review** (2026-11-20). The design is `namespace_metadata.md` (beside this file). The
mockups are its section 10: portal https://claude.ai/artifact/3nDGzZm2ZJpSjKu4rRr1pb, Swagger
https://claude.ai/artifact/2AYqUotuYe1qpPwCgDM1wP, ReDoc https://claude.ai/artifact/ECf6nW9rNXfym1qjMxjN8F.

**The owner's rule for the code:** no complicated logic. Every piece is methodical and small enough that a junior
engineer can follow the workflow from the request to the answer. Section 2 turns that into checkable rules.

---

## 1. Who does what

| Role | Who | Does |
|---|---|---|
| Implementer | Opus 5.5 at `high`, one background agent per phase | Writes the code, tests, generated files and docs of a phase, as one PR with the full code in the diff |
| Reviewer | Codex `gpt-6.2-astra` at `xhigh` | Reviews each PR against this plan and the design; returns each finding with its full fix and a test that fails before and passes after |
| Coordinator | Opus 5.5 (the main session) | Writes each phase's brief; runs what Codex cannot (PostgreSQL, browser suites, CRC); rules on every finding with its test; merges on green CI |

Every PR: `Closes` or `Part of` its issue; `review:fable` label (Fable reviews later, as decided for /houston-mayday work);
no attribution lines.

---

## 2. Code rules (the owner's "junior engineer" rule, made checkable)

| # | Rule | Checked by |
|---|---|---|
| C1 | One function does one step, named for that step (`check_namespace_suffix`, not `validate2`). No function longer than about 40 lines | Review |
| C2 | Rules live in data (the configuration and small tables), never in branches spread through the code. A new key or a new problem code is a table row, not new logic | Review; the contract lint (Phase 2) |
| C3 | Each phase states its workflow in its PR as a numbered list from request to answer, with the file and function of each step | Review |
| C4 | No metaprogramming, no clever comprehensions over three levels, no hidden global state. Plain loops and early returns | Review |
| C5 | Every error has one registered problem code with one example; no new code unless the registry lacks the case | The contract lint |
| C6 | Every behaviour has a test named for it (`test_a_name_without_the_environment_suffix_is_refused`) that fails before and passes after | Review; CI |
| C7 | The portal computes nothing the API does not also check; the API is the authority, the portal only helps | Review |
| C8 | Comments say why, in one line. No dead or commented-out code | Review |

---

## 3. The documentation standard (for all 40 operations, Swagger UI and ReDoc)

Measured on CRC's live `/openapi.json` (2026-11-20): 40 operations in 10 tags, `x-tagGroups` present, and every response
of every operation already has an example. So the standard is mostly about **consistency**, enforced by a test.

| # | Every operation has | Today |
|---|---|---|
| S1 | A `summary` (a short verb phrase) and a `description` (what it does, when to use it, what it changes) | Yes (`DocumentedRouter` refuses a route without docs) |
| S2 | One tag, inside one `x-tagGroups` group | Yes |
| S3 | `x-cmapi-permission` (the permission a caller needs) and the security scheme | Yes |
| S4 | Every parameter with type, location, required flag, rule (`pattern`, `enum`, `maximum`) and an example | Partly: the lint lists the gaps |
| S5 | A request body (writes) with `required`, each field's type, format, rule, description and example; filled-in and default fields marked by `x-cmapi-derived-from` and `x-cmapi-default-from` | Partly: filled-in keys are hidden (A1) |
| S6 | One complete Example Value for the request, generated from configuration or a recorded sample, never written by hand | Yes (recorded samples) |
| S7 | **Every status it can return**, each with its media type (`application/json` or `application/problem+json`) | Yes |
| S8 | **One named example per problem code**, named by the code, with `type`, `title`, `status`, `detail` and `code`; Swagger UI shows them in its Examples dropdown and ReDoc in its example selector | Yes for this operation; the lint checks all |
| S9 | Its `x-` extensions visible: Swagger UI `showExtensions: true` and `showCommonExtensions: true`; ReDoc `showExtensions: true` | **No**: only `persistAuthorization` is set (`main.py:272`) |
| S10 | A curl sample (`x-codeSamples`) that runs as written against the example | Yes |

---

## 4. Phases, in order

Each phase is one PR, merged before the next starts, because each builds on the one before. Phases 4 and 5 touch
different files and may run in parallel once Phase 3 is merged.

### Phase 1: the API contract for the namespace (design A1–A11)

| Step | File | What |
|---|---|---|
| 1.1 | `core/metadata.py` | Load `namespaceSuffix` (one key at most), `default: {from: K}` (K names an existing key of the same kind; no chains) and the optional `allowOther.example`; refuse a bad config at start with one `ConfigError` line each |
| 1.2 | `core/metadata.py` | One function per check, in this order: fill filled-in keys → fill defaults → check the prefix → check the suffix → check each key's rule → check extra keys. Each returns a list of `errors` entries; nothing else |
| 1.3 | `core/docs.py` (`_document_metadata`, `metadata_example`, `example_namespace`) | Filled-in keys required and shown (drop `readOnly`); `x-cmapi-default-from`; `x-cmapi-prefix-from` and `x-cmapi-suffix-from` on `namespace`; examples from the configuration, including one extra key and `expiresAt` |
| 1.4 | `plugins/expiration/rules.py`, `core/models.py`, `core/docs.py` | `expiration.yaml` gains `enabled` (default `true`, per environment); `prod: {enabled: false}` loads, `prod: {enabled: true}` is refused (the #222 backstop stays). `expiresAt`: description and `x-cmapi-expiration` per environment. The namespace keeps getting `cmapi.net/expires-at` and `cmapi.net/expiry: managed` when a date is set |
| 1.5 | The dry-run answer | `metadata.labels` and `metadata.annotations` give each value with its `source` |
| 1.6 | `cmapi/contract/` | Regenerate `openapi.json`, the samples and docs/04 with the generators; one `accepted-breaking.txt` line per filled-in key that became required |
| 1.7 | Tests (`tests/service/`) | One test per behaviour (C6): prefix, suffix, default kept/filled, filled-in key left out/right/wrong, extra key allowed/refused, expiry in the past/beyond 180/prod, the loader refusals |

### Phase 2: the contract lint, then every operation brought to the standard

| Step | File | What |
|---|---|---|
| 2.1 | `tests/service/test_api_standard.py` (new) | A table-driven test over the generated document: for each operation, each of S1–S10 is a named check with a clear failure line ("POST /api/v1/x: response 409 has no example named idempotency-replay") |
| 2.2 | The routers | Fix every gap the lint lists, operation by operation, using only the existing helpers (`problem_responses`, `DocumentedRouter`); no new mechanism |
| 2.3 | `cmapi/contract/` | Regenerate; the change is additive (oasdiff) |

### Phase 3: Swagger UI and ReDoc settings

| Step | File | What |
|---|---|---|
| 3.1 | `main.py` (the `/docs` page) | `swagger_ui_parameters`: `persistAuthorization`, `showExtensions`, `showCommonExtensions`, `displayRequestDuration`, `docExpansion: "list"`, `defaultModelsExpandDepth: 1`, `defaultModelExpandDepth: 3`, `tryItOutEnabled: false` |
| 3.2 | The `/redoc` page (`docs/redoc-start.js`) | `showExtensions: true`, `requiredPropsFirst: true`, `expandResponses: "200,202"`, `sortPropsAlphabetically: false`, `hideDownloadButton: false`; telemetry stays off |
| 3.3 | Tests | The page tests check each setting is served; the existing CSP and no-CDN tests stay green |

### Phase 4: the portal's New namespace form (design P1–P12)

| Step | File | What |
|---|---|---|
| 4.1 | `src/portal/metadataForm.ts` | Read the schemas of `GET /api/v1/metadata-keys`: fields, titles, rules, `x-cmapi-*` markers, `x-cmapi-other-keys`, `x-cmapi-expiration`. One small function per marker |
| 4.2 | `src/portal/NamespaceNameField.tsx` (new) | PatternFly InputGroup: locked prefix, the desired-name input, locked suffix; the full name and its length |
| 4.3 | `src/portal/MetadataFields.tsx` | Named fields from the schema; filled-in fields locked; a default field that copies its source until edited |
| 4.4 | `src/portal/ExtraKeysSection.tsx` (new) | ExpandableSection, **closed and empty by default**; two key/value tables; row checks from `propertyNames`, `additionalProperties`, `x-cmapi-other-keys` |
| 4.5 | `src/portal/ExpiryField.tsx` (new) | PatternFly DatePicker, empty by default; "in N days"; warning past `maxLifetimeDays`; replaced by a note on prod; **No expiry** clears it |
| 4.6 | `src/portal/NewNamespaceTab.tsx`, `plan.ts` | The live preview; **Check** (dry run) then **Submit**; Submit off after any change |
| 4.7 | Tests (`tests/api/portal.test.mjs`, `mutants.mjs`) | Each P-rule a browser check at 390, 820 and 1440 px in both themes; a mutant per check, each with its own check filter (#474) |

### Phase 5: CRC configuration, the Kyverno bundle and the deploy

| Step | What |
|---|---|
| 5.1 | CRC's `metadata-keys.yaml` per the design's section 8, after the owner confirms it |
| 5.2 | Re-render the Kyverno bundle and deliver it to `cmapi-cluster-configs` by PR |
| 5.3 | One CRC deploy (after #398's automatic token renewal is merged); screenshots of Swagger, ReDoc and the form through the Route |

---

## 5. Race conditions and timing, and how each is closed

| # | Race | Closed by |
|---|---|---|
| R1 | Someone edits the form after **Check** and submits a body the dry run never saw | Submit is disabled by any change, so the portal only sends a checked body. The server re-plans and fully checks every create anyway, so even an unchecked body cannot get through invalid. (Create takes no `If-Match` today; only PATCH and DELETE do. Binding a create to its dry run would be a new header, more logic than this needs) |
| R2 | A double click or a retry sends the create twice | `Idempotency-Key` is made once per checked body; the same key returns the first answer (24 h) |
| R3 | Two people create the same name at once | The open-request lock (`uq_cr_open_namespace`) lets one in; the other gets 409 `change-pending` |
| R4 | The configuration changes (a pod restarts with new metadata keys) while a form is open | The form reads `GET /api/v1/metadata-keys` with its ETag; the dry run validates against the server's current rules, so a stale form fails Check, not Submit; the form offers to reload its fields |
| R5 | The Team default overwrites a value the person typed | Once the Team field is edited, the default never writes it again (a flag, set on the first edit) |
| R6 | The cluster changes after the name was typed | The suffix follows the cluster at once and the preview and Check use the new name; Submit is off until checked again |
| R7 | The expiry date crosses midnight, or the browser's time zone differs from the server's | Dates are calendar dates (no time); "in N days" is computed from the server's `today` (the expirations answer already carries it), not the browser clock; the server checks again |
| R8 | A dry run answer arrives after a newer one (slow network) | Each Check carries a counter; the form shows only the answer of the latest Check (TanStack Query keys by the body's hash) |
| R9 | The generated Swagger examples drift from the code | The contract tests compare the committed document and samples with what the code serves; CI fails on any difference |

---

## 6. Review and proof per phase

| Phase | Proof before merge |
|---|---|
| 1 | Service tests (coordinator runs the full suite with PostgreSQL); the contract gate with the accepted lines; docs/04 regenerated |
| 2 | The lint passes for all 40 operations; oasdiff additive |
| 3 | The page tests; a browser look at `/docs` and `/redoc` locally |
| 4 | The portal browser suite and its mutants (coordinator runs them; Codex cannot launch a browser) |
| 5 | The CRC walk with screenshots through the Route |

Each phase: Codex `gpt-6.2-astra` `xhigh` review of the PR → findings with fix and test → the coordinator re-runs each
finding's test failing before and passing after → applies accepted fixes → merges on green CI.

---

## 7. Issues

| Issue | Covers |
|---|---|
| #479 (rewritten from the design) | Phase 1 and Phase 4 for the namespace |
| #480: the documentation standard | Phases 2 and 3 for all operations |
| #365 | The extra-key editor (Phase 4.4); closed by the Phase 4 PR |
| #473, #474 | Portal test fixes picked up in Phase 4 |
