# #349: each curl sample sends a body that the instance accepts

Part of #328 (found building #334). Written by Opus 5.5 (`high`), the implementer. One model family for this step.

**The defect.** The curl sample (`x-codeSamples`) of a write was put together by `core/docs.py` `_example_of` from each
property's first example. `POST .../namespaces` sent `"tier": "small"` with the field example of `limitRange`, and the
`PATCH` sample `"tier": "large"` with it; `limitRange` is taken on the custom tier only, so every instance refused both
bodies with 422 `policy-violation` (`limits-with-named-tier`). A property example cannot say that it needs another field's
value.

## The choice

**The curl sample sends the media type's `example` of the request body when the document has one**, and puts a body
together from the property examples only for an operation that no run recorded. That `example` is the request that the
service suite sent and the instance accepted (`contract/samples.json`), with this instance's labels and annotations in
place of the reference file's (#334). Swagger UI's "Try it out", ReDoc's request sample and the curl sample now send the
same body. `build_openapi` adds the recorded examples before the curl samples are written.

Why: OpenAPI 3.1, Media Type Object, `example`: "Example of the media type", which, "if referencing a `schema` which
contains an example, ... SHALL override the example provided by the schema". A whole-body example is the place where a
document says a body that holds together across fields; Schemathesis runs a document's explicit examples first, before it
generates bodies from the schema.

### Rejected

| Option | Why not |
|---|---|
| A per-model example (`json_schema_extra` on `NamespaceCreate`) | A body written by hand, and `_example_of` would return it before reading the labels and annotations that `_document_metadata` sets per instance (#334): the company instance would show the reference file's keys |
| Leave out a field whose example needs another field's value | `docs.py` would have to know the tier rule (limitRange on custom only), a second copy of a rule of `core/tiers.py` |
| Change `LIMIT_RANGE_EXAMPLE` or `tier`'s example to `custom` | A custom create needs every sizable quota key too (`quota` is `examples=[None]`), so the body would be refused for another reason |

## Tests, before (main 31e0794) and after

| Test | Main | Branch |
|---|---|---|
| `tests/service/test_metadata_schema_328_api.py::test_each_example_of_a_namespace_write_is_a_body_that_this_instance_accepts`, reference and company, `policy.engine: none`, no `kyverno` on PATH; the curl body sent whole (the `pop("limitRange")` of #350 removed) | 2 fail: the create curl dry run answers 422 `policy-violation` on each instance | 2 pass: create and patch curl dry runs answer 200, and each curl body equals the "Try it out" body |
| `tests/service/test_api_docs.py::test_each_operation_has_one_curl_sample_that_the_app_accepts`, now refusing `policy-violation` too | fails: the create sample answers 422 `policy-violation` | passes |
| The two files in full | 3 fail, 28 pass | 31 pass |

`cmapi/contract/openapi.json` and `docs/04-api-examples.md` are written again from the served document: only the curl
samples of the writes that a run recorded change.

## Sources, read on 2026-11-17

- OpenAPI 3.1.0, Media Type Object, <https://spec.openapis.org/oas/v3.1.0.html#media-type-object>.
- Schemathesis, data generation, <https://schemathesis.readthedocs.io/en/stable/explanations/data-generation/>: the
  explicit examples phase runs first.

## Not tested here

- The patch sample on main: the create sample fails first in the test, so the patch's 422 on main is the issue's
  measurement, not this run's.
- CRC and kind: nothing ran on a cluster. Two service files ran locally; CI's `service` job is the full run.
