# #602: `DELETE .../namespaces/{ns}?dryRun=true` is a dry run

The implementer's record: Opus 5.5 at `high`, 2026-11-23, on `fix/602-delete-dryrun` from `8a5b41c`. The reviews go
beside it when they are done.

## The defect, as measured

Reviewer 2 of PR #599 measured it on head `3f4843b`, and `tests/service/test_delete_dry_run_602.py` repeats it on
`8a5b41c`: `DELETE /api/v1/clusters/CRC/namespaces/payments-dev?dryRun=true`, with If-Match and an Idempotency-Key,
answered 202 `req-20261123-0002`, `action: delete`, `status: pending_approval`, and stored the row. The route declared no
`dryRun` (`plugins/namespaces/router.py`, `delete_namespace`), and FastAPI ignores a query parameter that a route does not
declare. The create, the change and the three expiry calls each declare `dry_run: DryRun` and `dry_run_model=PlanView`.

## Sources, fetched 2026-11-23

- Kubernetes, "API Concepts", section "Dry-run",
  <https://kubernetes.io/docs/reference/using-api/api-concepts/#dry-run> (source:
  `kubernetes/website`, `content/en/docs/reference/using-api/api-concepts.md`, branch `main`): "When you use HTTP verbs
  that can modify resources (`POST`, `PUT`, `PATCH`, and `DELETE`), you can submit your request in a _dry run_ mode."
  And: "Kubernetes guarantees that dry-run requests will not be persisted in storage or have any other side effects."
  And, under "Dry-run authorization": "Authorization for dry-run and non-dry-run requests is identical."
- Google AIP-163, "Change validation", <https://google.aip.dev/163> (source: `aip-dev/google.aip.dev`,
  `aip/general/0163.md`, created 2019-12-16, changelog 2020-10-06): "APIs **may** provide an option to validate, but not
  actually execute, a request". "The API **must** perform permission checks and any other validation that would be
  performed on a "live" request; a request using `validate_only` **must** fail if it determines that the actual request
  would fail." And: "A resource that is declarative-friendly (AIP-128) **must** include a `validate_only` field on methods
  that mutate the resource." A Delete mutates the resource.
- Google's own Delete with `validate_only`: Cloud Run v2, `google/cloud/run/v2/service.proto` in `googleapis/googleapis`,
  branch `master`, `message DeleteServiceRequest`: "Indicates that the request should be validated without actually
  deleting any resources. `bool validate_only = 2;`"
- RFC 9110, <https://www.rfc-editor.org/rfc/rfc9110.html>, section 4.2.1: "The hierarchical path component and optional
  query component identify the target resource within that origin server's namespace." HTTP gives a query parameter no
  meaning of its own: `dryRun` means what cmapi's document says it means. Section 9.3.5 (DELETE) asks for 202 "if the
  action will likely succeed but has not yet been enacted", which the real delete keeps; it says nothing on a preview.

## The choice

| Option | For | Against |
|---|---|---|
| **A delete plan**: `dryRun` and `dry_run_model=PlanView` on the delete route, 200 with the plan | The same rule on every write that opens a change request, as docs/01 ("200 Plan for dry runs ... for every write route") and docs/02 ("?dryRun=true returns 200 with the Plan") already say. Kubernetes takes `dryRun` on DELETE, and AIP-163 and Cloud Run's `DeleteServiceRequest` take `validate_only` on a delete. The route already builds the plan (`plan_delete`) before it submits, so the dry run is the same three lines as the other writes. A caller sees the approval a delete needs, and whether it is refused (protected, stale If-Match), before opening it | One more 200 on the document (additive: oasdiff reports two `info` lines, no breaking change) |
| A 422 for `dryRun` on DELETE | Smaller | It keeps an exception to the rule that docs/01 and docs/02 state, refuses a preview that the two references offer, and gives the caller no way to see a delete's approval before opening the request |

Chosen: the delete plan. The dry run runs the delete's own path up to the submit: the permission (`require`), `_idem`
with `dry_run`, `plan_delete` (cluster, environment, If-Match, protection, the approval rules), and `refusals` with
`dry_run=True`, so a refusal of a dry run is counted and not stored, as on the other writes. It answers before `_submit`,
so it opens no request, writes no event, audit row or job, and pushes nothing to Git. An Idempotency-Key sent with it is not
read, as on the other dry runs, so the same key opens the real delete afterwards.

The plan of a delete: `changes` lists each file of the folder as `removed`, `files` is empty (`Plan.view` keeps only the
files that have content), `etag` is the one If-Match matched, `approval` the approval the delete would need, `capacity`
`fits` with `source: delete`, and `metadata` and `metadataDiff` are null.

## Tests

| Test | Before (`8a5b41c`) | After |
|---|---|---|
| `test_a_delete_dry_run_answers_the_plan_and_writes_nothing` | fails: 202 `req-20261123-0002`, `pending_approval` | passes: 200, the plan, no row in any of six tables, Git unchanged; the same headers without `dryRun` then open the one request |
| `test_a_delete_dry_run_fails_where_the_delete_would` | fails: 400 `idempotency-key-required` | passes: 428 without If-Match and with `*`, 412 on a stale tag, 404 for a namespace not in Git, 403 for an approver |
| `test_a_delete_dry_run_of_a_protected_namespace_is_refused` | fails: 400 | passes: 422 `namespace-protected`, nothing stored |
| `test_a_delete_dry_run_needs_no_idempotency_key_and_the_delete_still_does` | fails: 400 on the dry run | passes: 200; without `dryRun`, and with `dryRun=false`, 400 `idempotency-key-required` |
| `test_the_document_declares_the_delete_dry_run` | fails: no `dryRun` parameter | passes: the optional query parameter, the 200 `PlanView`, the 202, the key's description |

`test_api_standard.py`, `test_the_delete_key_is_described_as_the_delete_checks_it`, asserted the old design (no `dryRun`
in the delete key's description); it now asserts the new one. `test_api_samples.py` records the delete's dry run as
`namespaces_delete_namespace:dryRun`, which fills the 200 of the document.
