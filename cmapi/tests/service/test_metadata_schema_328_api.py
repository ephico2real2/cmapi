"""#328 and #334 through the API: each instance serves the labels and annotations of a namespace as schema generated from
its own metadata-keys.yaml, and the examples, the curl samples and the "Try it out" body of the document are bodies that
the instance accepts. Run on the reference file (the committed contract's) and on the owner's company file.

Each instance runs with no Kyverno (instance.yaml `policy.engine: none`, cmapi's real CliValidator, no kyverno binary on
PATH): the schema documents cmapi's own check, which refuses alone (#342).
"""
from __future__ import annotations

import json
import shlex
import shutil
import stat

import pytest
import yaml

from cmapi.core.metadata import anchored, value_regex
from cmapi.core.validate import CliValidator
from conftest import EXAMPLES, build_world
from metadata_corpus import SchemaReader, run
from test_flow import OLA, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces"
FILES = {"reference": "metadata-keys.yaml", "company": "metadata-keys.company.yaml"}


@pytest.fixture(params=list(FILES))
def instance(request, test_config, fresh_db, keys, monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    kubeconform = bin_dir / "kubeconform"
    kubeconform.write_text("#!/bin/sh\necho '{\"resources\": [], \"summary\": {\"valid\": 1}}'\n")
    kubeconform.chmod(kubeconform.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    shutil.copy(EXAMPLES / "cluster-configs/policies" / FILES[request.param], d / "metadata-keys.yaml")
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    inst["instance"]["policy"] = {"engine": "none"}
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    with build_world(d, keys, monkeypatch) as world:
        client, ctx, *_ = world
        assert ctx.cfg.policy.engine == "none" and shutil.which("kyverno") is None
        ctx.pipeline.validator = CliValidator(tmp_path / "policies", policy=ctx.cfg.policy,
                                              environments=ctx.cfg.allowed_environments)
        yield request.param, world


def document(client) -> dict:
    return client.get("/openapi.json").json()


def body_schema(spec: dict, name: str) -> dict:
    """A component of the document as a schema of its own, its references resolved against the document."""
    return {"$ref": f"#/components/schemas/{name}", "components": spec["components"]}


def maps(spec: dict) -> dict[tuple[str, str], dict]:
    props = {op: spec["components"]["schemas"][model]["properties"]
             for op, model in (("create", "NamespaceCreate"), ("patch", "NamespacePatch"))}
    return {(kind, op): props[op][field] if op == "create" else props[op][field]["anyOf"][0]
            for kind, field in (("label", "labels"), ("annotation", "annotations")) for op in ("create", "patch")}


def operation(spec: dict, method: str, path: str) -> dict:
    return spec["paths"][path][method]


def curl_body(op: dict) -> dict:
    """The body of the operation's curl sample, as a shell reads it, whole (#349)."""
    words = shlex.split(op["x-codeSamples"][0]["source"])
    return json.loads(words[words.index("-d") + 1])


def test_the_served_schema_accepts_each_map_that_the_instance_accepts_and_refuses_what_it_can_say(instance):
    """The served schema per instance, against the instance's own validator, on the corpus of tests/core (create and
    patch): sound, and precise but for what JSON Schema cannot say."""
    name, (client, ctx, *_) = instance
    keys = ctx.cfg.metadata
    served = maps(document(client))
    for (kind, op), schema in served.items():
        expected = keys.json_schema(kind, op)
        assert {k: schema[k] for k in expected} == expected, (kind, op)
    sources = {"namespace": "payments-dev" if name == "reference" else "abc-rnd", "environment": "dev", "cluster": "CRC",
               "instance": ctx.cfg.name}
    result = run(keys, served, sources)
    assert result.total > 10000 and result.accepted > 500, (result.total, result.accepted)
    assert result.unsound == [], [(c.kind, c.op, dict(c.body), p) for c, p in result.unsound[:5]]
    assert result.unexplained == [], [(c.kind, c.op, dict(c.body), e) for c, e in result.unexplained[:5]]


def test_the_document_requires_each_required_key_of_this_instance(instance):
    """The issue's proof: a property per key with the validator's pattern, required on create, and a JSON Schema
    validator on the document refuses a create that leaves a required key out."""
    name, (client, ctx, git, kube, validator, keys) = instance
    rules, spec = ctx.cfg.metadata, document(client)
    create = spec["components"]["schemas"]["NamespaceCreate"]
    labels, annotations = create["properties"]["labels"], create["properties"]["annotations"]
    check = SchemaReader().validator(body_schema(spec, "NamespaceCreate"))
    if name == "reference":
        assert {"namespace", "labels", "annotations"} <= set(create["required"])
        assert labels["required"] == ["cmapi.net/team"] and annotations["required"] == ["cmapi.net/team-dl"]
        assert labels["properties"]["cmapi.net/team"]["pattern"] == anchored(rules.rules["label"]["cmapi.net/team"].pattern)
        assert annotations["properties"]["cmapi.net/team-dl"]["pattern"] == \
            value_regex(rules.rules["annotation"]["cmapi.net/team-dl"], rules.email_domains)
        body = {"namespace": "payments-dev", "labels": {"cmapi.net/cost-center": "cc-4410"},
                "annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"}}
    else:
        # #479 (A1): the filled-in keys are required and shown, so the annotations map is required too.
        assert {"labels", "annotations"} <= set(create["required"])
        assert labels["required"] == ["name", "company.net/app-environment", "company.net/mnemonic", "company.net/lob",
                                      "company.net/cl"]
        assert annotations["required"] == ["company.net/app-environment"], "the only required annotation is filled in"
        for derived in ("name", "company.net/app-environment"):
            assert "readOnly" not in labels["properties"][derived]
        body = {"namespace": "abc-dev", "labels": {"company.net/lob": "amgsst", "company.net/cl": "1"}}
    errors = [e.message for e in check.iter_errors(body)]
    assert any("is a required property" in e for e in errors), errors
    r = client.post(URL + "?dryRun=true", json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert {e["code"] for e in r.json()["errors"]} == {"missing_required_key"}, r.json()["errors"]


def test_each_example_of_a_namespace_write_is_a_body_that_this_instance_accepts(instance):
    """#334: the create example ("Try it out"), the create curl sample, and the patch's, each pass the schema and a
    dry run on this instance; the map examples pass their schemas. #349: each curl sample is sent whole (on main 31e0794
    the create and the patch samples sent limitRange with a named tier, and each dry run answered 422
    limits-with-named-tier)."""
    name, (client, ctx, git, kube, validator, keys) = instance
    spec = document(client)
    check = SchemaReader()
    create, patch = operation(spec, "post", "/api/v1/clusters/{cluster_id}/namespaces"), \
        operation(spec, "patch", "/api/v1/clusters/{cluster_id}/namespaces/{ns}")
    for model in ("NamespaceCreate", "NamespacePatch"):
        for field in ("labels", "annotations"):
            prop = spec["components"]["schemas"][model]["properties"][field]
            for example in prop["examples"]:
                assert check.validator(prop).is_valid(example), (model, field, example)
    tried = create["requestBody"]["content"]["application/json"]["examples"]["permanent"]["value"]
    for body in (tried, curl_body(create)):
        assert check.validator(body_schema(spec, "NamespaceCreate")).is_valid(body), body
        r = client.post(URL + "?dryRun=true", json=body, headers=auth(keys, "ola", **OLA))
        assert r.status_code == 200, (body, r.text)
    r = client.post(URL, json=tried, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    ns = tried["namespace"]
    got = client.get(f"{URL}/{ns}", headers=auth(keys, "ola", **OLA))
    assert got.status_code == 200, got.text
    for body in (patch["requestBody"]["content"]["application/json"]["example"], curl_body(patch)):
        assert check.validator(body_schema(spec, "NamespacePatch")).is_valid(body), body
        headers = {**auth(keys, "ola", **OLA), "If-Match": f'"{got.json()["etag"]}"'}
        r = client.patch(f"{URL}/{ns}?dryRun=true", json=body, headers=headers)
        assert r.status_code == 200, (body, r.text)
    if name == "company":
        # #479 (A3): the mnemonic is put before the model's example name, as the design's abc-payments-dev.
        assert tried["namespace"] == "abc-payments-dev" and "cmapi.net/team" not in json.dumps(tried)
    # The curl sample sends the "Try it out" body: the recorded request, with this instance's labels and annotations.
    for op in (create, patch):
        media = op["requestBody"]["content"]["application/json"]
        expected = media["example"] if "example" in media else media["examples"]["permanent"]["value"]
        assert curl_body(op) == expected, op["operationId"]


def test_a_patch_cannot_remove_a_required_or_derived_key_in_the_schema_or_in_the_api(instance):
    name, (client, ctx, git, kube, validator, keys) = instance
    spec = document(client)
    check = SchemaReader().validator(body_schema(spec, "NamespacePatch"))
    tried = operation(spec, "post", "/api/v1/clusters/{cluster_id}/namespaces")["requestBody"]["content"]["application/json"]["examples"]["permanent"]["value"]
    assert client.post(URL, json=tried, headers=auth(keys, "ola", **OLA)).status_code == 202
    run_jobs(ctx)
    ns = tried["namespace"]
    etag = client.get(f"{URL}/{ns}", headers=auth(keys, "ola", **OLA)).json()["etag"]
    removals = {"reference": [("labels", "cmapi.net/team", "missing_required_key"),
                              ("annotations", "cmapi.net/team-dl", "missing_required_key")],
                "company": [("labels", "company.net/mnemonic", "missing_required_key"),
                            ("labels", "name", "derived_key"), ("annotations", "company.net/app-environment", "derived_key")]}
    for field, key, code in removals[name]:
        body = {field: {key: None}}
        assert not check.is_valid(body), body
        headers = {**auth(keys, "ola", **OLA), "If-Match": f'"{etag}"'}
        r = client.patch(f"{URL}/{ns}?dryRun=true", json=body, headers=headers)
        assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
        assert [(e["code"], e["key"]) for e in r.json()["errors"]] == [(code, key)], r.json()["errors"]
