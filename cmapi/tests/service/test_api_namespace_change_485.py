"""The namespace-change operations in the documentation standard (#485; docs/reviews/2026-11-20-epic-481-metadata-patch/
design.md, sections 4.1 to 4.4 and 8): the change, the reads that carry what it needs, the discovery list and the key
rules, as Swagger UI and ReDoc show them. test_api_standard.py holds every operation to S1 to S10; this file holds what
these four say beyond it, on the same three metadata-keys files. No database: the document is the one the instance serves.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from test_api_standard import cfg, spec  # noqa: F401  (the fixtures of the standard: three metadata-keys files)

from cmapi.core.docs import PATCH_OPERATION, _accepted_patch
from cmapi.core.docs import load_samples

CLUSTER = "/api/v1/clusters/{cluster_id}/namespaces"
PATCH = ("patch", CLUSTER + "/{ns}")
GET_ONE = ("get", CLUSTER + "/{ns}")
GET_LIST = ("get", CLUSTER)
KEYS = ("get", "/api/v1/metadata-keys")

# Every status and code of the change, from design 4.1 (Errors): the registered codes only, no new one.
CHANGE_CODES = {
    "200": set(), "202": set(),
    "400": {"idempotency-key-required"}, "401": {"unauthenticated"}, "403": {"forbidden", "environment-forbidden"},
    "404": {"cluster-not-found", "object-not-found"}, "409": {"change-pending", "idempotency-replay"},
    "412": {"precondition-failed"}, "428": {"precondition-required"}, "502": {"git-unavailable"},
    "503": {"cluster-unreachable", "validator-unavailable", "validator-busy"},     # validator-busy: #708
}
# Recorded from a run (tests/service/test_api_samples.py), not synthesized, for the answers a client meets on a change.
RECORDED = {"400": "idempotency-key-required", "401": "unauthenticated", "403": "forbidden", "404": "object-not-found",
            "409": "change-pending", "412": "precondition-failed", "428": "precondition-required"}


def op(spec: dict[str, Any], where: tuple[str, str]) -> dict[str, Any]:
    return spec["paths"][where[1]][where[0]]


def codes(response: dict[str, Any]) -> set[str]:
    return set(((response.get("content") or {}).get("application/problem+json") or {}).get("examples") or ())


def test_the_change_describes_every_status_and_names_one_example_per_code(spec):
    change = op(spec, PATCH)
    assert set(change["responses"]) >= set(CHANGE_CODES) | {"422"}
    for status, expected in CHANGE_CODES.items():
        assert codes(change["responses"][status]) >= expected, status
        assert change["responses"][status]["description"].strip(), status
    assert {"policy-violation", "validation-failed", "no-change"} <= codes(change["responses"]["422"])
    for status, code in RECORDED.items():
        shown = change["responses"][status]["content"]["application/problem+json"]["examples"][code]["value"]
        assert shown["code"] == code and shown["status"] == int(status), status


def test_the_change_answer_of_a_held_namespace_names_its_holder_and_a_stale_one_the_etag(spec):
    examples = {s: op(spec, PATCH)["responses"][s]["content"]["application/problem+json"]["examples"] for s in ("409", "412")}
    assert examples["409"]["change-pending"]["value"]["requestId"].startswith("req-")
    assert examples["409"]["idempotency-replay"]["value"]["requestId"].startswith("req-")
    assert examples["412"]["precondition-failed"]["value"]["etag"]


def test_the_policy_violation_of_a_change_is_the_answer_of_a_change_with_one_entry_for_each_key(spec):
    shown = op(spec, PATCH)["responses"]["422"]["content"]["application/problem+json"]["examples"]["policy-violation"]["value"]
    recorded = load_samples()["operationProblems"][f"{PATCH_OPERATION}:policy-violation"]["response"]["body"]
    assert shown == recorded
    found = [(e["code"], e["key"]) for e in shown["errors"]]
    assert len(found) == len(set(found)) >= 4 and {c for c, _ in found} >= {"reserved_key", "invalid_key", "invalid_value"}
    create = op(spec, ("post", CLUSTER))["responses"]["422"]["content"]["application/problem+json"]["examples"]["policy-violation"]
    assert create["value"] != shown, "the change shows the create's refusal"


def test_the_change_description_says_merge_patch_if_match_and_the_refusals(spec):
    text = op(spec, PATCH)["description"]
    for needed in ("RFC 7396", "`null` removes it", "RFC 9110, section 13.1.1", "428", "412", "RFC 6585, section 3",
                   "RFC 9110, section 15.5.13", "metadataDiff", "`before` is `null`", "x-cmapi-edit", "change-pending",
                   "policy-violation", "no-change", "namespaces:protect"):
        assert needed in text, needed


def test_the_body_examples_are_a_merge_patch_with_a_null_removal_that_the_instance_accepts(spec, cfg):
    media = op(spec, PATCH)["requestBody"]["content"]["application/json"]
    assert list(media["examples"]) == ["mergePatch", "tier"] and "example" not in media
    merge = media["examples"]["mergePatch"]["value"]
    sent = {**(merge.get("labels") or {}), **(merge.get("annotations") or {})}
    assert None in sent.values(), "a merge patch example removes a key with null"
    assert len(sent) >= 1 and _accepted_patch(cfg.metadata, merge)
    assert media["examples"]["tier"]["value"] == load_samples()["operations"][PATCH_OPERATION]["request"]["body"]
    assert json.dumps(merge) in op(spec, PATCH)["x-codeSamples"][0]["source"], "the curl sample sends the merge patch"


def test_the_extensions_of_the_change_and_of_its_reads(spec):
    for where, permission in ((PATCH, "namespaces:write"), (GET_ONE, "objects:read"), (GET_LIST, "objects:read"),
                              (KEYS, "objects:read")):
        found = op(spec, where)
        assert found["x-cmapi-permission"] == permission and found["x-cmapi-plugin"] and found["x-plugin-version"], where
        assert f"**Requires** `{permission}`" in found["description"], where


def test_the_read_documents_git_edits_the_removable_flag_and_the_sync_states(spec):
    schemas = spec["components"]["schemas"]
    assert "x-cmapi-edit" in op(spec, GET_ONE)["description"] and "git.edits" in op(spec, PATCH)["description"]
    edit = schemas["KeyEdit"]["properties"]
    assert {"mode", "reason", "sensitive", "removable"} <= set(edit) and all(edit[f]["description"] for f in edit)
    assert "operator-only" in schemas["GitMetadata"]["properties"]["edits"]["description"]
    assert "environment" in schemas["GitMetadata"]["properties"]["edits"]["description"]
    for state in ("in-sync", "pending", "drift", "unknown"):
        assert state in schemas["NamespaceSync"]["properties"]["state"]["description"]
    assert "etag" in op(spec, GET_ONE)["responses"]["200"]["description"].lower() or "ETag" in op(spec, GET_ONE)["responses"]["200"]["description"]
    for code in ("object-not-found", "cluster-not-found"):
        assert code in codes(op(spec, GET_ONE)["responses"]["404"]), code
    assert load_samples()["operationProblems"]["namespaces_get_namespace:object-not-found"]


def test_the_discovery_list_documents_q_mnemonic_limit_and_the_facets(spec):
    found = op(spec, GET_LIST)
    params = {p["name"]: p for p in found["parameters"]}
    assert {"q", "mnemonic", "limit"} <= set(params)
    for name in ("q", "mnemonic", "limit"):
        assert params[name]["description"] and params[name]["schema"].get("examples"), name
        assert params[name]["required"] is False
    assert params["limit"]["schema"]["anyOf"][0]["maximum"] == 50 and params["limit"]["schema"]["anyOf"][0]["minimum"] == 1
    assert "facets" in found["description"] and "total" in found["description"]
    body = found["responses"]["200"]["content"]["application/json"]["example"]
    assert {"items", "total", "facets"} <= set(body) and "mnemonics" in body["facets"]
    assert {"cluster-not-found"} <= codes(found["responses"]["404"]) and "validation-failed" in codes(found["responses"]["422"])


def test_metadata_keys_gives_every_property_x_cmapi_edit_and_says_so(spec):
    found = op(spec, KEYS)
    assert "x-cmapi-edit" in found["description"]
    example = found["responses"]["200"]["content"]["application/json"]["example"]
    for kind in ("labels", "annotations"):
        properties = example[kind]["properties"]
        assert properties, kind
        for key, schema in properties.items():
            edit = schema["x-cmapi-edit"]
            assert edit["mode"] in ("fixed", "automatic", "required", "optional") and "sensitive" in edit, key
            assert "removable" not in edit, f"{key}: a declared key is never removable"
