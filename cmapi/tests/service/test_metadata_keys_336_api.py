"""#336: GET /api/v1/metadata-keys, the rules of a new namespace's labels and annotations, for the portal's New namespace form.

The answer is MetadataKeys.json_schema(kind, "create") of the instance's own file: the same objects as NamespaceCreate's
labels and annotations in /openapi.json (no second rule source), served also when docs.enabled is false. Built once per
process, with a strong ETag over the exact bytes, Cache-Control: private, no-cache, and 304 on If-None-Match. Permission
objects:read, as GET /api/v1/tiers, which the same form already needs.

Run on the reference file (the committed contract's) and on the owner's company file, each with no Kyverno (instance.yaml
`policy.engine: none`, the `instance` fixture of #328).
"""
from __future__ import annotations

import hashlib
import json

from cmapi.core.metadata import MetadataKeys
from conftest import build_world
from test_api_docs import _config
from test_flow import OLA, auth
from test_metadata_schema_328_api import document, instance  # noqa: F401  (the fixture, parametrised on both files)

ROUTE = "/api/v1/metadata-keys"
WORDS = ("title", "description", "examples")      # what the API document puts around each map, and the route does not


def get(client, keys, headers=None, user="ola", **who):
    return client.get(ROUTE, headers={**auth(keys, user, **(who or OLA)), **(headers or {})})


def test_the_route_answers_the_instances_rules(instance):
    """T1, T2: 200 with the file's create schemas; the reference requires Team and Team DL, the company its three labels."""
    name, (client, ctx, *_, keys) = instance
    r = get(client, keys)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/json"
    body = r.json()
    assert body == ctx.cfg.metadata.keys_view() == {"labels": ctx.cfg.metadata.json_schema("label", "create"),
                                                    "annotations": ctx.cfg.metadata.json_schema("annotation", "create")}
    labels, annotations = body["labels"], body["annotations"]
    if name == "reference":
        assert labels["required"] == ["cmapi.net/team"] and annotations["required"] == ["cmapi.net/team-dl"]
        assert labels["properties"]["cmapi.net/team"]["title"] == "Team"
        assert annotations["properties"]["cmapi.net/team-dl"]["title"] == "Team DL"
        assert annotations["properties"]["cmapi.net/team-dl"]["x-cmapi-format"] == "email-in-domains"
    else:
        assert labels["required"] == ["company.net/mnemonic", "company.net/lob", "company.net/cl"]
        assert "required" not in annotations, "the company's only required annotation is derived"
        for derived, source in (("name", "namespace"), ("company.net/app-environment", "environment")):
            assert labels["properties"][derived]["readOnly"] is True
            assert labels["properties"][derived]["x-cmapi-derived-from"] == source
        assert labels["properties"]["company.net/mnemonic"]["x-cmapi-namespace-prefix"] is True
        assert labels["properties"]["company.net/cl"]["enum"] == ["0", "1", "2", "3", "4", "5", "6"]
        assert "cmapi.net/team" not in labels["properties"]
    assert labels["properties"]["cmapi.net/protected"]["x-cmapi-operator-only"] is True


def test_the_route_is_the_api_documents_namespace_create_labels_and_annotations(instance):
    """T3, the contract: one generator. Each map equals /openapi.json's NamespaceCreate property without the words that
    the document puts around it; a second source of the rules would drift from it."""
    name, (client, ctx, *_, keys) = instance
    served = get(client, keys).json()
    create = document(client)["components"]["schemas"]["NamespaceCreate"]["properties"]
    for field in ("labels", "annotations"):
        documented = {k: v for k, v in create[field].items() if k not in WORDS}
        assert served[field] == documented, (name, field)
        assert set(create[field]) - set(served[field]) == set(WORDS), (name, field)


def test_the_documents_example_of_the_route_is_this_instances_answer(instance):
    """The sample is recorded on the reference file. On the company instance its example would show keys that the
    instance does not have (the defect of #334): the document shows this instance's own answer."""
    name, (client, ctx, *_, keys) = instance
    op = document(client)["paths"][ROUTE]["get"]
    assert op["responses"]["200"]["content"]["application/json"]["example"] == ctx.cfg.metadata.keys_view()
    assert op["x-cmapi-permission"] == "objects:read"
    if name == "company":
        assert "cmapi.net/team" not in json.dumps(op["responses"]["200"]["content"]["application/json"]["example"])


def test_docs_disabled_keeps_the_route(test_config, tmp_path, fresh_db, keys, monkeypatch):
    """T4: the reason for the route. With docs.enabled false, /openapi.json is gone and the form still reads its rules."""
    with build_world(_config(test_config, tmp_path, {"enabled": False}), keys, monkeypatch) as (client, ctx, *_):
        assert client.get("/openapi.json").status_code == 404
        r = get(client, keys)
        assert r.status_code == 200 and r.json() == ctx.cfg.metadata.keys_view(), r.text


def test_a_strong_etag_and_304(world, monkeypatch):
    """T5: the ETag is a hash of exactly the bytes served; If-None-Match answers 304 with no body, by the weak comparison
    (RFC 9110 13.1.2, so W/ and * match); another tag gets the body. The body is built once per loaded file."""
    client, ctx, *_, keys = world
    calls = []
    real = MetadataKeys.json_schema

    def counted(self, kind, op):
        calls.append((kind, op))
        return real(self, kind, op)

    monkeypatch.setattr(MetadataKeys, "json_schema", counted)
    first = get(client, keys)
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag == '"' + hashlib.sha256(first.content).hexdigest()[:32] + '"', etag     # RFC 9110 8.8.3: of the exact bytes
    assert first.headers["cache-control"] == "private, no-cache"
    for tag in (etag, f"W/{etag}", "*", f'"other", {etag}'):
        again = get(client, keys, {"If-None-Match": tag})
        assert again.status_code == 304 and again.content == b"", tag
        assert again.headers["etag"] == etag and again.headers["cache-control"] == "private, no-cache", tag
    other = get(client, keys, {"If-None-Match": '"0123"'})
    assert other.status_code == 200 and other.content == first.content
    assert calls == [("label", "create"), ("annotation", "create")], "built once, then served from the cache"


def test_the_permission_is_objects_read(world):
    """T6: no token is 401 with WWW-Authenticate; a role without objects:read is 403; a viewer and a role limited to one
    environment read it (the answer is the instance's, the same for every caller)."""
    client, ctx, *_, keys = world
    r = client.get(ROUTE)
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer") and r.json()["code"] == "unauthenticated"
    relay = get(client, keys, user="relay", roles=["cmapi-approval-relay"], groups=[])
    assert relay.status_code == 403 and relay.json()["code"] == "forbidden", relay.text
    assert "objects:read" in relay.json()["detail"]
    bodies = {get(client, keys, user=u, roles=[role], groups=[]).content
              for u, role in (("viewer", "cmapi-viewer"), ("bot", "cmapi-bot-rnd"), ("ola", "cmapi-requester"))}
    assert len(bodies) == 1, "one answer for every caller"
