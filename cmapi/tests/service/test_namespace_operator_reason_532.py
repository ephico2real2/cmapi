"""#532: namespace-specific operator-only reasons, without PostgreSQL or a cluster."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import yaml
from fastapi import Response

from cmapi.core.authz import RolePolicy
from cmapi.core.errors import Problem
from cmapi.core.metadata import MetadataKeys
from cmapi.core.identity.claims import Identity
from cmapi.plugins.namespaces import router


# In tests/service, not tests/core: it drives the namespaces router, whose imports need the service's dependencies
# (prometheus_client), and tests/core is also the reference-code job's suite (examples/tests links to it).
def person(username, *, roles=()):
    return Identity(sub=f"sub-{username}", username=username, kind="user", client_id="cmapi-portal",
                    email=f"{username}@ephico2real.com", given_name=username.title(), family_name="Doe",
                    employee_id="E100", roles=frozenset(roles), groups=frozenset())


@pytest.mark.parametrize("environment, reason", [
    ("dev", "Needs namespaces:protect in dev."),
    ("customer-sandbox", "Needs namespaces:protect in customer-sandbox."),
])
def test_requester_reads_operator_only_reason_from_namespace_clusters_environment(monkeypatch, environment, reason):
    metadata = MetadataKeys({"operatorOnly": ["shield"]})
    who = person("requester", roles=["cmapi-requester"])
    roles = RolePolicy()
    assert not roles.allowed(who, "namespaces:protect", environment)
    # A legacy label must not override the cluster's policy, nor may an absent live namespace hide Git's rule.
    doc = {"apiVersion": "v1", "kind": "Namespace",
           "metadata": {"name": "payments-dev", "labels": {"shield": "true", "cmapi.net/env": "old"}}}
    files = {"clusters/cluster/namespaces/payments-dev/namespace.yaml": yaml.safe_dump(doc)}
    # name: InstanceConfig.name, which the read passes as the "instance" source of a derived key's value (#739).
    context = SimpleNamespace(
        cfg=SimpleNamespace(name="nonprod", metadata=metadata, roles=roles,
                            approvals=SimpleNamespace(protected_by=lambda labels: [])),
        registry=SimpleNamespace(get=lambda cluster: SimpleNamespace(policy=SimpleNamespace(environment=environment))),
        pipeline=SimpleNamespace(_read_folder=lambda cluster, ns: (files, "revision")),
        db=SimpleNamespace(session=lambda: nullcontext(None)),
    )
    monkeypatch.setattr(router, "RequestRepo", lambda session: SimpleNamespace(open_holders=lambda cluster: {}))
    monkeypatch.setattr(router, "_live_namespace", lambda *args: (None, False))
    view = router.get_namespace("cluster", "payments-dev", Response(), who, context)
    # Before #532 the portal fell back to the cluster-independent metadata-keys rule.
    generic = metadata.keys_view()["labels"]["properties"]["shield"]["x-cmapi-edit"]
    rule = view["git"]["edits"]["labels"].get("shield", generic)
    assert rule["reason"] == reason


@pytest.mark.parametrize("kind", ["label", "annotation"])
def test_namespace_operator_only_reason_keeps_the_sensitive_approval_suffix(kind):
    metadata = MetadataKeys({"operatorOnly": ["shield"], "sensitiveKeys": ["shield"]})
    held = {"label": {}, "annotation": {}}
    held[kind]["shield"] = "true"
    assert metadata.undeclared_edits(held, "dev")[kind + "s"]["shield"] == {
        "mode": "optional", "reason": "Needs namespaces:protect in dev. Changing this key needs one more approval.",
        "sensitive": True,
    }


@pytest.mark.parametrize("kind", ["label", "annotation"])
def test_namespace_patch_error_uses_the_same_environment_reason(kind):
    metadata = MetadataKeys({"operatorOnly": ["shield"]})
    sent = {"label": {}, "annotation": {}}
    sent[kind]["shield"] = "true"
    with pytest.raises(Problem) as caught:
        metadata.check(sent["label"], sent["annotation"], operator=False, existing=True,
                       sources={"environment": "dev"})
    assert caught.value.status == 403
    assert caught.value.detail == "Needs namespaces:protect in dev. Keys: shield."


def test_metadata_keys_without_a_cluster_keeps_the_generic_operator_only_reason():
    metadata = MetadataKeys({"operatorOnly": ["shield"], "sensitiveKeys": ["shield"]})
    for name in ("labels", "annotations"):
        assert metadata.keys_view()[name]["properties"]["shield"]["x-cmapi-edit"]["reason"] == \
            "Needs namespaces:protect in the namespace's environment. Changing this key needs one more approval."
