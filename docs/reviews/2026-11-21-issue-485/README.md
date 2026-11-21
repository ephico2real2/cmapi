# #485: Swagger and ReDoc for the namespace-change operations

Part of #481. The definition of done is section 8 of
`docs/reviews/2026-11-20-epic-481-metadata-patch/design.md`: "The PATCH and the extended reads in the #480 standard:
every status, one named example per problem code, the merge-patch example with a `null` removal, `x-cmapi-edit`, the
Extensions; both renderers checked."

## What changed, and where

All of it is written through the code's own documentation mechanism. `contract/openapi.json`, `samples.json`,
`docs/04-api-examples.md` and the portal types are generated from it, none by hand.

| Part | Where it is written | Proof |
|---|---|---|
| The PATCH description: merge patch, `null` removal, `metadataDiff`, If-Match, 412, 428, 409, the per-key 422 codes, `namespaces:protect` | the docstring of `update_namespace`, `plugins/namespaces/router.py` | `test_the_change_description_says_merge_patch_if_match_and_the_refusals` |
| Every status described, one named example per problem code | `core/docs.py` (`problem_responses`), unchanged; the codes are the route's | `test_the_change_describes_every_status_and_names_one_example_per_code`, and `test_api_standard.py` S7 and S8 |
| The change's own answers recorded from a run: 400, 401, 403, 404, 409 (held and replay), 412, 422 (one entry for each key, `no-change`, `validation-failed`), 428 | `test_api_samples.py` (the section "the refusals of a change and of its reads"); `samples.json` `operationProblems` | `test_the_policy_violation_of_a_change_is_the_answer_of_a_change_with_one_entry_for_each_key` |
| The merge-patch example with a `null` removal, and the tier example, as named bodies; the curl sample sends the merge patch | `_document_patch_examples` and `metadata_merge_patch`, `core/docs.py` | `test_the_body_examples_are_a_merge_patch_with_a_null_removal_that_the_instance_accepts`, on the three metadata-keys files |
| The reads: `git`, `git.edits`, `removable`, the operator-only reason naming the environment (#532), `sync`, the ETag | the docstring of `get_namespace`, the `KeyEdit`, `GitKeyEdits` and `GitMetadata` fields, `core/models.py` | `test_the_read_documents_git_edits_the_removable_flag_and_the_sync_states` |
| The discovery list: `q`, `mnemonic`, `limit`, `total`, `facets` | unchanged from #483, held by the test | `test_the_discovery_list_documents_q_mnemonic_limit_and_the_facets` |
| `x-cmapi-edit` on every key of `GET /api/v1/metadata-keys` | unchanged from #483, held by the test | `test_metadata_keys_gives_every_property_x_cmapi_edit_and_says_so` |
| The Extensions (`x-cmapi-permission`, `x-cmapi-plugin`, `x-plugin-version`, `x-codeSamples`) | `DocumentedRouter`, unchanged | `test_the_extensions_of_the_change_and_of_its_reads` |
| `ProblemDetail.errors`: the item codes and their members | `core/models.py` | the schema in `openapi.json` |

A problem code that two operations answer (`policy-violation`, `forbidden`, `object-not-found`, `cluster-not-found`,
`unauthenticated`, `idempotency-key-required`, `validation-failed`) had one recorded sample, the first operation's, so the
change showed the create's 422. `samples.json` now has `operationProblems`, keyed `<operationId>:<code>`, for the second and
later operations. `add_recorded_examples` applies it and `docs/04` lists it under Problems.

## Sources

Fetched on 2026-11-21 from the RFC Editor (`https://www.rfc-editor.org/rfc/rfcNNNN.txt`), and quoted in the operation's
description by section:

- RFC 7396 (JSON Merge Patch), section 1: "Null values in the merge patch are given special meaning to indicate the removal
  of existing values in the target." The section's own words also say the rest of the target is left "untouched".
- RFC 9110, section 13.1.1: "The "If-Match" header field makes the request method conditional on the recipient origin server
  either having at least one current representation of the target resource, when the field value is "*", or having a current
  representation of the target resource that has an entity tag matching a member of the list of entity tags provided in the
  field value." Section 15.5.13: "The 412 (Precondition Failed) status code indicates that one or more conditions given in
  the request header fields evaluated to false when tested on the server".
- RFC 6585, section 3: "The 428 status code indicates that the origin server requires the request to be conditional." The
  task named RFC 9110 for 428, but 428 is not in RFC 9110: it is RFC 6585, and the description cites it as that.
- RFC 9457, section 3: "When serialized in a JSON document, that format is identified with the "application/problem+json"
  media type." Each problem response has that media type only (`problem_responses`, unchanged).

## The renderers

`tools/docs_server.py` serves the real `/docs`, `/redoc` and `/openapi.json` with no database (the method of #480).
`tools/shots.mjs` drives the installed Chrome and prints what each control shows. Its output is `browser-check.txt`, the
pictures are in `screenshots/`.
