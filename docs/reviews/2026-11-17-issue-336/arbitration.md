# #336: the arbitration of two designs

- **Design A** (`design-336-a/design.md`, evidence beside it): a general-purpose Opus 5.5 agent.
- **Design B** (`design-336-b/design.md`, evidence beside it): OB3, a separate Opus 5.5 agent.

Both come from one model family: Codex's usage limit holds until 2026-11-18 14:09, and Fable is paused by the owner.
The designs were written apart; neither read the other. The coordinator ruled on each point below, from the designs'
own measurements, on origin/main c7ab6c4.

## Where the designs agree (adopted)

| Point | Both designs |
|---|---|
| Route | `GET /api/v1/metadata-keys` on the core router, permission `objects:read` (the permission of `/tiers`, which the form already needs) |
| Shape | `labels` and `annotations` are exactly `MetadataKeys.json_schema(kind, "create")`, the objects `/openapi.json` serves; a contract test holds them equal. No second rule source. Works when docs are disabled |
| Caching | Built once per process (a config change restarts the pods); a strong ETag over the exact bytes; `304` on `If-None-Match` |
| HTML `pattern` | Never: HTML compiles it with the `v` flag, and most served patterns do not compile there (A: 6 of 8 and 6 of 7; B: 9 of 12), so the browser silently checks nothing (B measured in Chromium 156) |
| Derived keys | Shown read-only with the value cmapi will write, never sent |
| Operator-only keys | Not offered |
| `title` | A new optional rule field, emitted as JSON Schema `title`; the reference config gets `Team` and `Team DL`, so the CRC form keeps the mockup's words |
| Errors | `ApiProblem` keeps `errors[]`; each error with a key goes to its field; a summary that takes focus; `aria-invalid` and helper text linked by `aria-describedby` |
| Authority | cmapi's validator decides; the form only helps, and never refuses what cmapi accepts (A: 0 of 12,197 maps; B: 0 of 15,450 values) |

## Where they differ, and the ruling

| Point | A | B | Ruling |
|---|---|---|---|
| Client checks: engine and thread | `@cfworker/json-schema` 4.1.6 on the served schema, on the page's thread | The served keywords evaluated per field, each pattern run in a Web Worker with a 200 ms limit; a check that runs out is "not checked here" and the dry run decides | **B.** B measured that the loader accepts the everyday pattern `^(?:[a-z0-9]+-?)*[a-z0-9]$`, which V8 needs 944 ms for on 26 characters, x4 per 2 more; a label value may hold 63. Any pattern check on the page's thread can freeze the form. A's concern stands, that a hand-written evaluator can drift from JSON Schema: so the build adds a contract test that fails when `json_schema` emits a keyword the form does not evaluate, beside B's differential test over the corpus. Rejected: A's library inside B's worker, a new 13-day-old dependency for keywords (`propertyNames`, `additionalProperties`) that the form's fields do not need while free keys are not offered |
| Cache-Control | `no-cache` | `private, no-cache` | **B.** The response answers an authenticated request (RFC 9111, `private`) |
| `configHash` in the body | Yes | No | **B.** The ETag already identifies the bytes |
| Other allowed (`allowOther`) keys | Offered in a collapsed group with the count and byte limits | Not offered; a free-form editor is its own issue | **B.** Today's form offers none either; an editor is its own issue (#365) |
| Error words | The form's own messages per keyword | `x-cmapi-rule`: the validator's own words, emitted by the generator | **B.** The browser and the API say the same thing. `x-cmapi-rule` is an annotation: oasdiff does not count it as breaking |
| A config change while the form is open | Not covered | Re-read on focus and on a refusal naming an unknown key; re-render, keep values of remaining keys, drop removed ones, an inline warning | **B** |
| Suggested name | From the namespacePrefix key | From the namespacePrefix key; without one, the first required label (keeps `payments-dev` and test 9) | **B**, recorded as a default the owner can change |
| `type=url` | Not measured | Refuses 3 URLs cmapi accepts; use `type="text" inputMode="url"` | **B** |

## Recorded defaults (the owner may change them)

1. `cmapi.net/protected` is not offered on the form. A's proposal (an `operator` flag on `GET /me`) is its own issue (#366).
2. Titles: the reference config gets `Team` and `Team DL`. The company sample gets none, so the key fallback is tested.
3. The suggested name's fallback is the first required label.

## Filed from the designs (each its own issue)

- docs/02 says `/tiers` sends an ETag and needs `namespaces:read`; the code sends none and needs `objects:read` (A1): #360.
- `core/config.py` and docs/02 describe a ConfigMap reload that is not built (A2): #361.
- A label key with no value rule is described as "any value", though the label syntax applies (A3): #362.
- The `url` format accepts `https://x:abc/` and `https://a%zz/`, which no URL parser accepts (B6): #363.
- The email regex is repeated for each email key in the schema (7.4 MiB at 500 + 500 keys); a `$defs` entry would remove it (B4): #364.
- A free-form editor for `allowOther` keys; #365; an `operator` flag on `/me` for operator-only keys: #366.

In scope for the build: A4 (`Hint` has no id for `aria-describedby`), and a docs/18 note that patterns can backtrack in
ECMA-262 clients such as Ajv (B5).
