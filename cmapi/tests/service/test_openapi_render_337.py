"""#337: `cmapi-tools openapi render` writes the document that an instance serves, offline, through the code that serves it.

The committed contract is what the service suite's test instance serves (test_api_docs.py holds it current), so a render
equal to it byte for byte is a render equal to the served document. No database, identity provider, cluster, Git host or
Kyverno is used: no connection may open, no kyverno is on PATH, and no database URL is set.
"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest
import yaml

import cmapi.main
from cmapi.tools import openapi as tool
from cmapi.tools import run
from conftest import EXAMPLES, ISSUER, ROOT

CONTRACT = ROOT / "contract" / "openapi.json"
REFERENCE_KEYS = EXAMPLES / "cluster-configs/policies/metadata-keys.yaml"


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """No connection, no kyverno, no database: what CI has when it renders a document."""
    def refuse(self, address):
        raise AssertionError(f"the render opened a connection to {address}")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    monkeypatch.delenv("CMAPI_DATABASE_URL", raising=False)


def render(tmp_path: Path, *args: str) -> Path:
    out = tmp_path / "openapi.json"
    run(["openapi", "render", *args, "--out", str(out)])
    return out


def test_the_packaged_reference_instance_renders_the_committed_contract(offline, tmp_path):
    """With no --config-dir: the reference instance, which the contract report of a values change uses on both sides."""
    out = render(tmp_path, "--metadata-keys", str(REFERENCE_KEYS))
    assert out.read_bytes() == CONTRACT.read_bytes()


def test_an_instances_own_files_render_what_it_serves(offline, tmp_path, test_config):
    out = render(tmp_path, "--metadata-keys", str(test_config / "metadata-keys.yaml"), "--config-dir", str(test_config))
    assert out.read_bytes() == CONTRACT.read_bytes()


def test_the_packaged_reference_instance_is_the_service_suites_test_instance():
    """reference_instance/ is examples/instances/nonprod with conftest's issuer and repository, as test_config writes it."""
    packaged = sorted(p.name for p in tool.REFERENCE_INSTANCE.glob("*.yaml"))
    assert packaged == ["approval-rules.yaml", "authz-roles.yaml", "expiration.yaml", "instance.yaml", "tiers.yaml"]
    for name in packaged:
        want = yaml.safe_load((EXAMPLES / "instances/nonprod" / name).read_text())
        if name == "instance.yaml":
            want["instance"]["auth"]["issuer"] = ISSUER
            want["instance"]["git"]["repository"] = "cmapi/cluster-configs-test"
        assert yaml.safe_load((tool.REFERENCE_INSTANCE / name).read_text()) == want, name


def test_a_refused_configuration_exits_3_with_the_loaders_message(offline, tmp_path, capsys):
    """Exit 3 tells a configuration that an instance would refuse at start from a tool that broke."""
    old = tmp_path / "metadata-keys.yaml"
    old.write_text("governed: {}\n")
    with pytest.raises(SystemExit) as exc:
        render(tmp_path, "--metadata-keys", str(old))
    assert exc.value.code == tool.REFUSED
    assert "the configuration is refused" in capsys.readouterr().err
    assert not (tmp_path / "openapi.json").exists()


def test_a_render_that_is_not_a_document_fails_and_writes_nothing(offline, tmp_path, monkeypatch):
    """A render that lost its paths would read as "no changes" in a report; it is a broken tool, not exit 0 or 3."""
    # #479: openapi_document also takes the instance's cluster environments (from --config-dir's clusters.yaml).
    monkeypatch.setattr(cmapi.main, "openapi_document", lambda cfg, clusters=None: {"openapi": "3.1.0", "paths": {}})
    with pytest.raises(RuntimeError, match="the document has no paths"):
        render(tmp_path, "--metadata-keys", str(REFERENCE_KEYS))
    assert not (tmp_path / "openapi.json").exists()


@pytest.mark.parametrize("doc, enabled, problem", [
    ({"openapi": "3.0.3", "paths": {"/x": {}}}, False, "not 3.1.x"),
    ({"openapi": "3.1.0", "paths": {"/x": {}}}, True, "no POST /api/v1/clusters/{cluster_id}/namespaces"),
])
def test_the_self_check(doc, enabled, problem):
    assert any(problem in p for p in tool.problems_of(doc, enabled))


def test_a_missing_file_is_named(tmp_path):
    with pytest.raises(SystemExit, match="does not exist"):
        render(tmp_path, "--metadata-keys", str(tmp_path / "nope.yaml"))
