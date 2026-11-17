# #328: the arbitration of two designs

Two independent designs, written apart, neither reading the other:

- **Design A** ([`design-a.md`](design-a.md), evidence in [`evidence/`](evidence/)): OB1 run 18, Opus 5.5.
- **Design B** ([`design-b.md`](design-b.md), evidence in [`evidence/design-b/`](evidence/design-b/)): OB3, a separate Opus agent.

Both come from one model family. Codex was briefed for design B and could not run: its usage limit holds until
2026-11-18. Fable is paused by the owner. So this step had one model family, and this record says so.

The coordinator decided each point below. Where the designs disagreed on a fact, the coordinator ran it on `main` (9ba33b2).

## Where the designs agree (adopted)

| Point | Both designs |
|---|---|
| Shape of each map | `properties` per declared key (pattern or enum, length, description, example), `required` on create, `propertyNames` for the allowed key classes, `additionalProperties` for the value rule of other allowed keys |
| Derived keys (cmapi fills them) | `readOnly: true`, not in `required` |
| Create | `NamespaceCreate.required` gains `labels` and `annotations` when the config has a required key |
| Patch | A required key or a derived key cannot be removed: no `null` branch for it; other keys keep `anyOf: [rule, {type: null}]` |
| Generation | One function in `core/metadata.py` builds the schemas from the instance's metadata config. The committed contract uses the reference config; each instance serves its own |
| Contract gate | Breaking by oasdiff 1.37.0's rules, 14 lines for `accepted-breaking.txt` under #328. No body that cmapi accepts today is refused afterwards (A: 2,652 bodies on four configs; B: 5,385 cases) |
| Portal | Hard-codes the two CRC keys today; building the form from the config is its own issue |

## Where they differ, and the ruling

| Point | A | B | Ruling |
|---|---|---|---|
| `null` on patch, in which form | `anyOf: [rule, {type: null}]`, because oasdiff reports `type: [string, null]` against FastAPI's `anyOf` form as narrowing (measured) | "no `null` branch" for required keys | **A's form**, measured against the gate. B agrees on which keys get no `null` |
| Pattern dialects | Measured on generated patterns: only a trailing-newline difference | Measured on what the loader accepts: `\Z`, `(?i)`, `(?P<..>)`, lookahead and backreferences all load on main, and RE2 refuses them | **Both are true; B's is the stronger finding.** The loader refuses a pattern outside the common subset of Python `re`, RE2 and ECMA-262, and anchors it once as `^(?:P)$` (A). Filed as #332 |
| Value regexes for formats (email, URL) | Per-key patterns from config | One `value_regex` per rule, written in the common subset; 630 verdicts, 0 differences across the three engines | **B**, so the validator, Kyverno and the schema share one string, not three hand-written versions |
| The label key `/foo` | Not found | The validator accepts it; Kubernetes refuses an empty prefix | **Confirmed by the coordinator:** `validate({'/foo': 'x', 'cmapi.net/team': 'payments'}, …)` returns `[]` on main. Filed as #330, fixed before #328 |
| `*` prefix admits unprefixed keys | Found: `fnmatchcase('', '*')` is `True` | Not found | **Confirmed by the coordinator** on main. Filed as #331, fixed before #328 |
| Kyverno coverage | Kyverno does not check `allowOther` prefixes, limits, reserved, system or operator-only keys | Not covered | **Adopted.** Filed as #333 |
| Served examples | With the company config, the served examples and the curl sample are bodies the instance refuses | Samples unchanged | **A**, measured. Examples are generated from the config's keys. Filed as #334, part of #328's generator |
| `propertyNames` in ReDoc | ReDoc 3.1.0 does not show it; readers rely on the description | Not measured in ReDoc | Keep the description text beside the schema |

## Where the rules are set: the values file

Neither design says how an operator sets the keys. The coordinator read the chart on `main` (9ba33b2):

1. Helm values `configFiles."metadata-keys.yaml"` holds the whole file as one text block; empty means the chart's
   `config/metadata-keys.yaml` (`deploy/helm/cmapi/values.yaml:277-279`, `templates/config.yaml`).
2. The chart writes it into the `cmapi-config` ConfigMap, mounted read-only at `/etc/cmapi/config`.
3. The API loads it once at start (`core/config.py`, `MetadataKeys`). The #328 generator builds the schema from it, so each
   instance's `/openapi.json` shows its own keys.
4. The `checksum/config` annotation on `api` and `worker` (`templates/api.yaml:21`, `worker.yaml:18`) restarts the pods
   when the values change.

On CRC with plain manifests the same file is in `deploy/manifests/environments/crc/20-config.yaml`.

The gap: a typo or a bad regex in that text block is found only when the pod fails at start, because the chart has no
`values.schema.json`. **Ruling:** a structured `metadata:` block in the values, rendered into `metadata-keys.yaml`,
with a `values.schema.json` so Helm refuses a malformed block before any pod starts. The text block stays as a
fallback; setting both fails at render. The loader stays the final check (#332). Filed as #335.

## With or without Kyverno

The owner, 2026-11-17: the application logic in cmapi must work with or without Kyverno.

This holds on `main` by design, and each step below keeps it and proves it:

- `instance.yaml` `policy` (#213, `core/policy.py`) has `engine: none` and the modes `enforce`, `audit` and `off` for
  each environment. With `none` or `off`, no Kyverno runs and cmapi needs no `kyverno` binary.
- cmapi's own validator (`core/metadata.py`, `validate`) is the one authority at plan time. Kyverno is a second check at
  plan time and at admission, and only when it is on.
- The #328 schema is generated from `metadata-keys.yaml`, never from the Kyverno policies.

**Rule for every step:** each new test runs with `policy.engine: none` and must pass there, so cmapi alone refuses each
bad body. #333 adds the agreement test with Kyverno on: on one shared case corpus, each body that the rendered policies
refuse, cmapi also refuses, so Kyverno is never the only guard.

## The order of work (refined 2026-11-17)

| Step | Issues | Why in this place | Runs beside |
|---|---|---|---|
| 1 | #330, then #331 | Validator defects, the base of the generator: the schema must not describe a rule that the validator breaks. Same file, so one agent, two PRs, each with a failing test first | Step 2 |
| 2 | #335 | The Helm values. Touches `deploy/helm/` and `docs/18` only | Step 1 |
| 3 | #332 | The pattern check at load: the common subset of Python `re`, RE2 and ECMA-262, anchored once as `^(?:P)$`, with one `value_regex` for each format (B). It also refuses a required key with no `example` (question 3). The generator emits these patterns, so it comes first | |
| 4 | #328 with #334 | The generator `MetadataKeys.json_schema(kind, op)`, the generated examples and curl sample, the 14 lines in `accepted-breaking.txt`, and the docs (generated clients come from the instance's own `/openapi.json`, question 5) | |
| 5 | #333 | Kyverno coverage of `allowOther`, limits, reserved, system and operator-only keys, and the agreement test with and without Kyverno | #336 |
| 6 | #336 | The portal form from the config, through a read-only API route that the same generator feeds | Step 5 |
| 7 | #337 | A report-only contract diff in the cluster-configs CI | |

Reviewer for each step: OB3 (Opus 5.5), since Codex is out of quota until 2026-11-18; Codex reviews from then on.

## The owner's answers (2026-11-17)

The owner accepted every recommendation: "Let us go with your recommendations".

1. Accept the 14 breaking lines before 1.0: **yes** (step 4).
2. The portal form from the config, its own issue, through a new API route: **yes**, #336.
3. A required key with no `example`: **refuse the config at load** with a clear message (step 3, #332).
4. A report-only contract diff in the config repository's CI: **yes**, #337.
5. Generated clients from the instance's own `/openapi.json`; the committed contract stays on the reference config: **yes** (step 4, docs).
6. The keys are set through the Helm values, as a structured block with `values.schema.json`: **yes**, #335.
