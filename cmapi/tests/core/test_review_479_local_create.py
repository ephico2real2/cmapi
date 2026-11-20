from pathlib import Path
from unittest.mock import Mock

import pytest

from cmapi.core.errors import Problem
from cmapi.core.metadata import MetadataKeys
from conftest import person


def test_local_create_validates_and_renders_the_filled_maps(ex, monkeypatch):
    import importlib.util

    local = ex / "local"
    monkeypatch.syspath_prepend(str(local))
    import adapters
    monkeypatch.setattr(adapters, "LocalGit", Mock())
    # Dataclasses in the local app use its module name while importing.
    import sys
    spec = importlib.util.spec_from_file_location("review_local_app", local / "app.py")
    app = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, app)
    spec.loader.exec_module(app)
    monkeypatch.setattr(app.CFG, "metadata", MetadataKeys({"requiredLabels": {
        "owner": {"example": "abc"}, "team": {"example": "payments", "default": {"from": "owner"}},
        "env": {"value": {"from": "environment"}, "namespaceSuffix": True}}}))
    monkeypatch.setattr(app.CFG.roles, "require", Mock())
    monkeypatch.setattr(app.CLUSTER, "namespace", lambda ns: None)
    app.GIT.read_folder.return_value = {}, "head"
    monkeypatch.setattr(app, "requester_for", lambda *args: Mock())
    def capture(spec, previous):
        assert spec.labels == {"owner": "abc", "team": "abc", "env": spec.env}
        raise Rendered()
    class Rendered(Exception):
        pass
    monkeypatch.setattr(app.RENDER, "render", capture)
    env = app.CLUSTERS["OCP_LOCAL"]["environment"]
    body = {"namespace": "abc-payments-" + env, "labels": {"owner": "abc"}}
    with pytest.raises(Rendered):
        app.plan_namespace(person("ola"), "OCP_LOCAL", body, action="create")
    with pytest.raises(Problem) as result:
        app.plan_namespace(person("ola"), "OCP_LOCAL", {**body, "namespace": "abc-payments-else"}, action="create")
    assert [e["key"] for e in result.value.errors] == ["env"]
