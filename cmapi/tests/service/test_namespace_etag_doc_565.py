"""#565: the OpenAPI document says what a namespace's etag is for, and its examples have the form the API returns.

The etag of a namespace is `folder_etag` (core/pipeline.py): an opaque hash of its folder in Git, not a Git commit.
RFC 9110 section 8.8.3.1: "Since the value is opaque, there is no need for the client to be aware of how each entity tag
is constructed", so each description says how to use the value (send it back in If-Match) and never what it is made of.
JSON Schema 2020-12 Validation section 9.5: `examples` illustrate usage, so each one must look like a value the API
really returns: 16 lowercase hexadecimal characters, or "0" for a folder that is not in Git."""
from __future__ import annotations

import re
from typing import Any, Iterator

from cmapi.core.pipeline import folder_etag

from test_flow import NS, OLA, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces/payments-dev"
GET_NAMESPACE = "/api/v1/clusters/{cluster_id}/namespaces/{ns}"
# The two forms folder_etag returns: a 16-hex hash of a folder in Git, or "0" for an empty one.
FORM = re.compile(r"[0-9a-f]{16}|0")
# Words that promise the value's internals. The value is not a commit, and a client must not rely on how it is built.
INTERNALS = re.compile(r"\b(commit|sha(-?\d+)?|hash)\b", re.IGNORECASE)


def _namespace_etag_schemas(spec: dict) -> dict[str, dict]:
    """Each `etag` property of a component schema, by schema name. Every one of them is a namespace's (#565)."""
    return {name: schema["properties"]["etag"] for name, schema in spec["components"]["schemas"].items()
            if "etag" in schema.get("properties", {})}


def _etag_example_values(node: Any) -> Iterator[Any]:
    """Every value of an `etag` key inside the examples of the document's operations (the recorded samples)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "etag" and not isinstance(value, dict):
                yield value
            yield from _etag_example_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _etag_example_values(item)


def _get_namespace_etag_header(spec: dict) -> dict:
    return spec["paths"][GET_NAMESPACE]["get"]["responses"]["200"].get("headers", {}).get("ETag", {})


def test_each_namespace_etag_property_says_how_to_use_it_and_shows_a_real_value(world):
    client, *_ = world
    spec = client.get("/openapi.json").json()
    props = _namespace_etag_schemas(spec)
    assert set(props) == {"NamespaceView", "PlanView"}, f"a new etag property: check it is the namespace's: {sorted(props)}"
    for name, prop in props.items():
        description = prop.get("description", "")
        assert "If-Match" in description, f"{name}.etag does not say to send it in If-Match: {description!r}"
        assert not INTERNALS.search(description), f"{name}.etag promises what the value is made of: {description!r}"
        assert prop.get("examples"), f"{name}.etag has no example"
        for example in prop["examples"]:
            assert FORM.fullmatch(example), f"{name}.etag example {example!r} is not a value folder_etag returns"


def test_the_get_namespace_answer_documents_its_etag_header_with_a_quoted_real_value(world):
    client, *_ = world
    header = _get_namespace_etag_header(client.get("/openapi.json").json())
    assert header, "GET a namespace sets an ETag header that the document does not declare"
    assert "If-Match" in header.get("description", "") and not INTERNALS.search(header["description"]), header
    examples = header["schema"].get("examples") or []
    assert examples, header
    for example in examples:
        assert example.startswith('"') and example.endswith('"') and FORM.fullmatch(example[1:-1]), example


def test_each_recorded_etag_in_the_document_has_the_documented_form(world):
    client, *_ = world
    spec = client.get("/openapi.json").json()
    recorded = [v for v in _etag_example_values(spec["paths"]) if v is not None]
    assert recorded, "the recorded samples show no etag"
    assert all(isinstance(v, str) and FORM.fullmatch(v) for v in recorded), recorded


def test_a_real_etag_has_the_form_of_the_documented_example_and_works_as_documented(world):
    """Behaviour, not only text: the value that GET returns is shaped like the documented example, the header carries the
    same value quoted, and sending it back in If-Match, as the descriptions say, is what a change accepts."""
    client, ctx, git, kube, validator, keys = world
    spec = client.get("/openapi.json").json()
    documented = _namespace_etag_schemas(spec)["NamespaceView"]["examples"][0]

    plan = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))
    assert plan.status_code == 200, plan.text
    assert plan.json()["etag"] == folder_etag({}) == "0"     # a create plan: the folder is not in Git yet
    assert client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).status_code == 202
    run_jobs(ctx)

    got = client.get(URL, headers=auth(keys, "ola", **OLA))
    assert got.status_code == 200, got.text
    etag = got.json()["etag"]
    assert FORM.fullmatch(etag) and len(etag) == len(documented), (etag, documented)
    header_example = _get_namespace_etag_header(spec)["schema"]["examples"][0]
    assert got.headers["etag"] == f'"{etag}"' and len(got.headers["etag"]) == len(header_example)

    stale = client.patch(f"{URL}?dryRun=true", json={"tier": "medium"},
                         headers={**auth(keys, "ola", **OLA), "If-Match": header_example})
    assert stale.status_code == 412 and stale.json()["etag"] == etag, stale.text
    fresh = client.patch(f"{URL}?dryRun=true", json={"tier": "medium"},
                         headers={**auth(keys, "ola", **OLA), "If-Match": got.headers["etag"]})
    assert fresh.status_code == 200 and fresh.json()["etag"] == etag, fresh.text
