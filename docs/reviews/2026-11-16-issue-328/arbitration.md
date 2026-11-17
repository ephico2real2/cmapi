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

## The order of work

1. #330 and #331: the two validator defects, each with a failing test first.
2. #332: the pattern check at load.
3. #328: the schema generator, with #334's generated examples, and the 14 accepted lines.
4. #333: Kyverno coverage.
5. The portal form from the config: its own issue, after the owner's answer below.

## For the owner, each with a recommendation

1. **Accept the 14 breaking lines** in the contract before 1.0. They only describe requests the server already refuses.
   Recommended: yes.
2. **Portal form from the config**, in its own issue, through a new API route, because `/openapi.json` is off when
   `docs.enabled` is false. Recommended: yes.
3. **A required key with no `example` in the config:** refuse the config at load, or make one up from its pattern.
   Recommended: refuse at load, with a clear message. A made-up example can be a value the team would not use.
4. **A report-only contract diff in the config repository's CI** when `metadata-keys.yaml` changes, so an operator sees
   the API change before it ships. Recommended: yes.
5. **Generated clients** for an instance with its own keys come from that instance's `/openapi.json`; the committed
   contract stays on the reference config. Recommended: yes.
