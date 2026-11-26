"""The namespace-change documentation states only what the API does (#485, review of PR #542). In tests/service: it imports the app and router, whose dependencies the reference-code job does not install."""
import copy
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from cmapi.core.docs import _accepted_patch, add_recorded_examples, load_samples
from cmapi.core.errors import Problem
from cmapi.core.metadata import MetadataKeys
from cmapi.core.pipeline import Pipeline
from cmapi.main import openapi_document
from cmapi.plugins.namespaces import router
from cmapi.tools.openapi import cluster_environments, load

ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "examples/cluster-configs/policies"
PATCH = "namespaces_update_namespace"
PATH = "/api/v1/clusters/{cluster_id}/namespaces/{ns}"


def document(path):
    cfg = load(path, None)
    return openapi_document(cfg, cluster_environments(cfg, None))


def test_try_it_out_never_removes_a_now_required_key(tmp_path):
    raw = yaml.safe_load((POLICIES / "metadata-keys.yaml").read_text())
    raw["requiredLabels"]["cmapi.net/cost-center"] = raw["extraLabels"]["keys"].pop("cmapi.net/cost-center")
    keys = MetadataKeys(raw)
    recorded = load_samples()["operations"][f"{PATCH}:dryRun"]["request"]["body"]
    assert not _accepted_patch(keys, recorded), "the recorded null removes a required key"
    path = tmp_path / "metadata-keys.yaml"
    path.write_text(yaml.safe_dump(raw))
    op = document(path)["paths"][PATH]["patch"]
    media = op["requestBody"]["content"]["application/json"]
    body = next(iter(media["examples"].values()))["value"] if "examples" in media else media["example"]
    # Check independently of the documentation helper, using the planner's required-key rules.
    assert not keys.validate(body.get("labels", {}), body.get("annotations", {}), operator=False, existing=True)
    assert json.dumps(body) in op["x-codeSamples"][0]["source"]



def test_problem_recordings_stay_with_their_operation_and_keep_the_fallback():
    code = "object-not-found"
    samples = load_samples()
    original = samples["problems"][code]
    own = samples["operationProblems"][f"{PATCH}:{code}"]
    ids = [original["operationId"], PATCH, "without_recording"]
    fallback = {"value": {"code": code, "detail": "fallback"}}
    spec = {"paths": {f"/{i}": {"get": {"operationId": op, "responses": {"404": {"content": {
        "application/problem+json": {"examples": {code: copy.deepcopy(fallback)}}}}}}} for i, op in enumerate(ids)}}
    add_recorded_examples(spec, {"problems": {code: original}, "operationProblems": {f"{PATCH}:{code}": own}})
    shown = [spec["paths"][f"/{i}"]["get"]["responses"]["404"]["content"]["application/problem+json"]["examples"][code]
             for i in range(3)]
    assert shown == [{"value": original["response"]["body"]}, {"value": own["response"]["body"]}, fallback]



@pytest.mark.parametrize("exists,etag,status", [(False, None, 404), (False, '"stale"', 404),
                                               (True, None, 428), (True, '"stale"', 412)])
def test_if_match_documentation_follows_the_planner_order(exists, etag, status):
    pipeline = Mock(spec=Pipeline)
    pipeline.registry, pipeline.cfg = Mock(), Mock()
    files = {"folder/namespace.yaml": "kind: Namespace\nmetadata:\n  name: payments-dev\n"} if exists else {}
    pipeline._read_folder.return_value = (files, "a" * 40)
    with pytest.raises(Problem) as caught:
        Pipeline._plan_namespace(pipeline, Mock(), "CRC", {"namespace": "payments-dev"}, action="update", if_match=etag)
    assert caught.value.status == status
    description = document(POLICIES / "metadata-keys.yaml")["paths"][PATH]["patch"]["description"]
    section = description.split("**If-Match.**", 1)[1].split("**Refusals.**", 1)[0]
    assert section.index("404") < section.index("428") < section.index("412")



def test_if_match_documentation_explains_replay_after_git_moves(monkeypatch):
    stored = object()
    monkeypatch.setattr(router, "_replay", lambda *args: stored)
    assert router.update_namespace("CRC", "payments-dev", router.NamespacePatch(tier="medium"),
                                   key="retry-key", etag='"old"', who=Mock(), c=Mock()) is stored
    with pytest.raises(Problem) as caught:
        router.update_namespace("CRC", "payments-dev", router.NamespacePatch(tier="medium"),
                                key="retry-key", etag=None, who=Mock(), c=Mock())
    assert caught.value.status == 428
    description = document(POLICIES / "metadata-keys.yaml")["paths"][PATH]["patch"]["description"]
    assert "replay still requires If-Match" in description
    assert "does not compare it again" in description



def test_automatic_key_documentation_explains_existing_namespace_values():
    keys = MetadataKeys(yaml.safe_load((POLICIES / "metadata-keys.company.yaml").read_text()))
    key = "company.net/app-environment"
    assert keys.edit_rule("label", key)["mode"] == "automatic"
    assert keys.merge_patch({key: "rnd"}, {}) == {key: "rnd"}
    assert keys.merge_patch({}, {}) == {}
    errors = keys.validate({key: "dev"}, {}, operator=False, existing=True,
                           current_labels={key: "rnd"}, sources={"environment": "dev"})
    assert any(e["code"] == "derived_key" for e in errors)
    description = document(POLICIES / "metadata-keys.company.yaml")["paths"][PATH]["patch"]["description"]
    assert "filled at creation" in description
    assert "a request can add a missing one with the derived value" in " ".join(description.split())


def test_docs04_recognizes_an_operation_with_only_an_operation_problem(tmp_path, monkeypatch):
    script = ROOT / "scripts/api-examples-doc.py"
    module_spec = importlib.util.spec_from_file_location("api_examples_doc_review", script)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    samples = load_samples()
    op_id = "namespaces_get_namespace"
    del samples["operations"][op_id]
    assert not any(p["operationId"] == op_id for p in samples["problems"].values())
    assert any(p["operationId"] == op_id for p in samples["operationProblems"].values())
    for relative, content in (("cmapi/contract/openapi.json", (ROOT / "cmapi/contract/openapi.json").read_text()),
                              ("cmapi/src/cmapi/contract/samples.json", json.dumps(samples))):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    output = module.render()
    summary = json.loads((ROOT / "cmapi/contract/openapi.json").read_text())["paths"][PATH]["get"]["summary"]
    section = output.split(f"### {summary}\n", 1)[1].split("### ", 1)[0]
    assert "The run has no successful call of this operation. Its recorded answer is the problem" in section
    assert "The run has no call of this operation." not in section

