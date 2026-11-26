# #739: self-service adoption, and the missing metadata asked for in the same form

**The owner's decision, 2026-11-26, on #26:** "We need flexibility so that the workflow is very intuitive and workflow worked
without to many complications so that adopting a namespace is very easy and promote self services. We can always have a
follow-up with them and ask for additional required metadata via the same form or screen so that adoption can be triggered via
the api as well with the required fields."

The design is D20 of `docs/reviews/2026-11-14-issue-26-adoption/README.md`. This record says what was chosen where the
decision left room, and why.

## The choices

| Question | Choice | Why |
|---|---|---|
| Which permission makes a requester able to adopt | The three routes need `namespaces:write` in the cluster's environment. `adoption:write` is not given to the requester role | The coordinator's reading on #26: "The approval rules gate it ... not a narrower permission". Adopting one namespace is a change of a namespace, the same permission as a PATCH. `adoption:write` stays for #252's scan of a whole cluster, an operator's operation. The declared permission (`x-cmapi-permission`) and the enforced one are the same constant, `ADOPT_PERMISSION`, and `test_review_c_authz` compares them |
| Does approval change | No | D10 and the shipped rules. A supplied key can only lower the findings count, by making the namespace follow the rules |
| How supplied keys are checked | `Pipeline._metadata_refusal` with `existing=True` over what the adoption writes to Git | The rule of a change that adds a key to an existing namespace (#732): a derived key only with its value, the name's start only for the prefix key, and every other rule of a create |
| A key the namespace already has | 422 `adoption-key-held`, `keys` names each one; also for an empty key and one under a skip prefix | D3 "as-is": the adoption never changes a key. A problem type of its own, so a client can tell it from a rule's refusal; RFC 9457 3.2 lets a problem type add members ("Problem type definitions MAY extend the problem details object with additional members") |
| `null` in the maps | Refused by the body's schema (`dict[str, str]`), 422 `validation-failed` | An adoption adds keys; it removes none (a merge patch's `null`, RFC 7396, belongs to a change) |
| Idempotency | The maps are in the body's fingerprint only when they add a key | An adoption that adds none keeps the fingerprint it had before #739 |
| The team fact | From the namespace as adopted, with a supplied `cmapi.net/team` | As a change computes it from the result (`_plan_namespace`); D6 "until a request sets the team" |
| Which value the form offers for the prefix key | The shortest start of the name that keeps the key's own rule (`MetadataKeys.exact_value`) | `_addition` accepts any such start; the shortest is the mnemonic of the company's sample (`abc` of `abc-rnd`). The server computes it, so the portal never guesses |
| Where the portal gets the keys | The candidates list (`missingKeys` of each candidate) and the namespace read (`git.missingKeys`) | The form shows the fields before the first Check, so the first dry run already carries them: no extra step and no second request |
| Read-only fields | PatternFly `TextInput` with `readOnlyVariant="default"`, not `isDisabled` | It stays in the tab order and is read by a screen reader, as the create form's automatic fields (#479 P3). PatternFly: "`readOnlyVariant`: Sets the input as readonly and determines the readonly styling" |
| "Add missing metadata" on the Namespaces tab | An alert over the table opens the same panel over the change's draft; the table's row of each key shows "In Missing metadata above" while it is open | One input for each key on the page, so no two inputs share a name; the change then goes through Check and Submit as any change |

## Sources, read on 2026-11-26

- RFC 9457, "Problem Details for HTTP APIs", 3.1.1 and 3.2: <https://www.rfc-editor.org/rfc/rfc9457.html>. "Consumers MUST
  use the "type" URI ... as the problem type's primary identifier"; "Clients consuming problem details MUST ignore any such
  extensions that they don't recognize".
- PatternFly, "Text input", the read-only example and `readOnlyVariant`: <https://www.patternfly.org/components/forms/text-input/>.
- #26, the owner's decision and the coordinator's reading (the last comment); #732 and PR #735, the change rule; this repository's
  `core/metadata.py` (`_fixed_key_error`, `_addition`, `remedy`).

## Found on the way

- `tests/service/test_add_missing_key_732.py` imports `approve_both` from `test_adoption_26.py`, which `feat/26-adoption` renamed
  to `approve_all` in its review fixes (b173497f). Merged together, the file fails at import. Fixed here; PR #735 needs the same
  line when it takes `feat/26-adoption`.
- docs/14 counted 0 routes for `adoption:write` and listed adoption among the routes not built, while PR #733 had built three
  under it. Corrected here with the move to `namespaces:write`.

## Tests

Each fails before the change (with `cmapi/src` stashed) and passes after it:

- `cmapi/tests/service/test_self_service_adoption_739.py`: 14 tests, all 14 fail before;
- `cmapi/tests/service/test_adoption_26.py::test_a_requester_may_adopt` (was `test_only_adoption_write_may_adopt`);
- `cmapi/tests/core/test_missing_keys_739.py`: 19 tests, all 19 fail before;
- the portal checks 739-A, 739-B, 739-H, 739-N, 739-F and 739-L in `cmapi-portal-ui/tests/api/portal.test.mjs`.
