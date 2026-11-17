"""#366: operators protect a namespace from deletion; #374: a later change keeps the protection.

Each test runs on an instance with no Kyverno (instance.yaml `policy.engine: none`): the operator-only check
(core/metadata.py) and the delete refusal (core/approvals.py) are cmapi's own, in every policy mode.
"""
from __future__ import annotations

import shutil

import pytest
import yaml

from conftest import build_world
from test_flow import NS, OLA, OPAL, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces"
ONE = f"{URL}/payments-dev"
FOLDER = "clusters/CRC/namespaces/payments-dev/namespace.yaml"


@pytest.fixture
def world(test_config, fresh_db, keys, monkeypatch, tmp_path):
    """The service suite's world on a copy of its config with `policy.engine: none`."""
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    inst["instance"]["policy"] = {"engine": "none"}
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    with build_world(d, keys, monkeypatch) as w:
        assert w[1].cfg.policy.engine == "none"
        yield w


def etag_of(client, keys) -> str:
    return client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]


def git_labels(git) -> dict:
    return yaml.safe_load(git.branches["main"][FOLDER])["metadata"]["labels"]


def patch(client, keys, body, user="ola", who=OLA, dry_run=False):
    return client.patch(ONE + ("?dryRun=true" if dry_run else ""), json=body,
                        headers={**auth(keys, user, **who), "If-Match": etag_of(client, keys)})


def created(world, labels=None, user="ola", who=OLA) -> None:
    """payments-dev, created by `user` with the extra labels, approved at once (baseline-rnd-namespace) and synced."""
    client, ctx, git, *_, keys = world
    r = client.post(URL, json={**NS, "labels": {**NS["labels"], **(labels or {})}}, headers=auth(keys, user, **who))
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)


# ---------------------------------------------------------------- #374: a change keeps the protection


def test_a_requesters_change_keeps_the_protection_and_the_delete_stays_refused(world):
    """#374: before the fix, the cost-center change re-rendered namespace.yaml without cmapi.net/protected."""
    client, ctx, git, *_, keys = world
    created(world, {"cmapi.net/protected": "true"}, "opal", OPAL)
    assert git_labels(git)["cmapi.net/protected"] == "true"
    r = patch(client, keys, {"labels": {"cmapi.net/cost-center": "cc-9999"}})
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    labels = git_labels(git)
    assert labels["cmapi.net/cost-center"] == "cc-9999" and labels.get("cmapi.net/protected") == "true", labels
    d = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": etag_of(client, keys)})
    assert d.status_code == 422 and d.json()["code"] == "namespace-protected", d.text


def planned_labels(plan: dict) -> dict:
    return yaml.safe_load(next(t for p, t in plan["files"].items() if p.endswith("/namespace.yaml")))["metadata"]["labels"]


@pytest.mark.parametrize("route", ["expiration:extend", "expiration:set", "expiration:makePermanent"])
def test_an_expiry_change_keeps_the_protection(world, route):
    """#374: :extend, :set and :makePermanent plan through plan_namespace too. :set gives a permanent namespace its date;
    the other two change a date that exists."""
    from datetime import date, timedelta
    client, ctx, git, *_, keys = world
    day = lambda n: (date.today() + timedelta(days=n)).isoformat()   # noqa: E731
    if route == "expiration:set":
        created(world, {"cmapi.net/protected": "true"}, "opal", OPAL)
    else:
        r = client.post(URL, json={**NS, "labels": {**NS["labels"], "cmapi.net/protected": "true"}, "expiresAt": day(10)},
                        headers=auth(keys, "opal", **OPAL))
        assert r.status_code == 202 and r.json()["status"] == "approved", r.text
        run_jobs(ctx)
    body = {"expiration:extend": {"days": 5}, "expiration:set": {"until": day(10)}, "expiration:makePermanent": {}}[route]
    r = client.post(f"{ONE}/{route}?dryRun=true", json=body, headers={**auth(keys, "ola", **OLA), "If-Match": etag_of(client, keys)})
    assert r.status_code == 200, r.text
    assert planned_labels(r.json()).get("cmapi.net/protected") == "true", planned_labels(r.json())


# ---------------------------------------------------------------- #366: who is an operator


ADMIN = dict(roles=["cmapi-admin"], groups=[])
VIEWER = dict(roles=["cmapi-viewer"], groups=[])
APPROVER = dict(roles=["cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-platform"])
ONBOARDING = dict(roles=["cmapi-onboarding"], groups=[])
PLATFORM = dict(roles=["cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-platform"])


def me(client, keys, user, who) -> dict:
    r = client.get("/api/v1/me", headers=auth(keys, user, **who))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("user, who, operator, where", [
    ("vic", VIEWER, False, []), ("oni", ONBOARDING, False, []), ("ola", OLA, False, []), ("amy", APPROVER, False, []),
    ("opal", OPAL, True, "all"), ("ada", ADMIN, True, "all"),
])
def test_me_says_who_is_an_operator(world, user, who, operator, where):
    client, *_, keys = world
    body = me(client, keys, user, who)
    assert (body["operator"], body["operatorEnvironments"]) == (operator, where)
    assert ("namespaces:protect" in body["access"]["permissions"]) is operator


@pytest.fixture
def roles_world(test_config, fresh_db, keys, monkeypatch, tmp_path):
    """Two roles of an instance's own authz-roles.yaml: one that inherits cmapi-operator, and namespaces:protect in rnd only."""
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    inst["instance"]["policy"] = {"engine": "none"}
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    roles = yaml.safe_load((d / "authz-roles.yaml").read_text())
    roles["roles"]["cmapi-ops"] = {"inherits": ["cmapi-operator"]}
    roles["roles"]["cmapi-protect-rnd"] = {"permissions": ["namespaces:protect"], "environments": ["rnd"]}
    (d / "authz-roles.yaml").write_text(yaml.safe_dump(roles))
    with build_world(d, keys, monkeypatch) as w:
        yield w


def test_an_operator_is_a_permission_not_a_role_name(roles_world):
    """A role that inherits cmapi-operator is an operator; namespaces:protect in rnd only is an operator in rnd only, so a
    protected create on the dev cluster CRC is refused (403) though /me says operator."""
    client, ctx, *_, keys = roles_world
    ops = dict(roles=["cmapi-ops"], groups=[])
    assert (me(client, keys, "oz", ops)["operator"], me(client, keys, "oz", ops)["operatorEnvironments"]) == (True, "all")
    r = client.post(URL, json={**NS, "labels": {**NS["labels"], "cmapi.net/protected": "true"}}, headers=auth(keys, "oz", **ops))
    assert r.status_code == 202, r.text
    rnd_only = dict(roles=["cmapi-requester", "cmapi-protect-rnd"], groups=[])
    body = me(client, keys, "rae", rnd_only)
    assert (body["operator"], body["operatorEnvironments"]) == (True, ["rnd"])
    r = client.post(URL, json={**NS, "namespace": "payments-two", "labels": {**NS["labels"], "cmapi.net/protected": "true"}},
                    headers=auth(keys, "rae", **rnd_only))
    assert r.status_code == 403 and r.json()["code"] == "forbidden", r.text


def test_the_pipeline_and_me_ask_one_function(world, monkeypatch):
    """One source: with RolePolicy.is_operator answering no, /me and the operator-only check both say no."""
    from cmapi.core.authz import RolePolicy
    client, *_, keys = world
    monkeypatch.setattr(RolePolicy, "is_operator", lambda self, who, env=None: False)
    assert me(client, keys, "opal", OPAL)["operator"] is False
    r = client.post(URL, json={**NS, "labels": {**NS["labels"], "cmapi.net/protected": "true"}}, headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 403 and r.json()["code"] == "forbidden", r.text


# ---------------------------------------------------------------- #366: requesters cannot set it; only "true" protects


@pytest.mark.parametrize("key", ["cmapi.net/protected", "do-not-delete"])
def test_a_requester_cannot_protect_or_unprotect(world, key):
    """The owner's decision: do-not-delete is operator-only too. Create, set and remove are each 403, nothing is stored."""
    client, ctx, *_, keys = world
    r = client.post(URL, json={**NS, "labels": {**NS["labels"], key: "true"}}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 403 and r.json()["code"] == "forbidden" and key in r.json()["detail"], r.text
    created(world, {key: "true"}, "opal", OPAL)
    for value in ("true", None):
        r = patch(client, keys, {"labels": {key: value}})
        assert r.status_code == 403 and r.json()["code"] == "forbidden", r.text
    assert client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["items"][0]["action"] == "create"


@pytest.mark.parametrize("key, value", [("cmapi.net/protected", "false"), ("cmapi.net/protected", "yes"), ("do-not-delete", "false")])
def test_only_the_value_that_protects_is_accepted(world, key, value):
    """A value that does not protect would be stored and shown while the namespace stays deletable: 422 invalid_value."""
    client, ctx, *_, keys = world
    r = client.post(URL, json={**NS, "labels": {**NS["labels"], key: value}}, headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert r.json()["errors"] == [{"code": "invalid_value", "key": key, "kind": "label",
                                   "detail": "only 'true', the value that protects; null removes it"}], r.text
    created(world)
    r = patch(client, keys, {"labels": {key: value}}, "opal", OPAL)
    assert r.status_code == 422 and [e["code"] for e in r.json()["errors"]] == ["invalid_value"], r.text


# ---------------------------------------------------------------- #366: the namespace says it, the delete refuses it


def test_a_protected_namespace_says_so_and_its_delete_is_refused(world):
    client, ctx, git, *_, keys = world
    created(world, {"cmapi.net/protected": "true"}, "opal", OPAL)
    view = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()
    assert (view["protected"], view["protectedBy"]) == (True, ["cmapi.net/protected=true"])
    ctx.registry.cache("CRC")._list("Namespace")          # the watch cache sees the synced namespace, as test_flow does
    listed = client.get(URL, headers=auth(keys, "ola", **OLA)).json()["items"]
    assert [(i["name"], i["protected"], i["protectedBy"]) for i in listed] == [("payments-dev", None, None)]
    for user, who in (("ola", OLA), ("opal", OPAL)):
        d = client.delete(ONE, headers={**auth(keys, user, **who), "If-Match": etag_of(client, keys)})
        assert d.status_code == 422 and d.json()["code"] == "namespace-protected", d.text


def test_protection_is_read_from_git_the_input_of_a_delete(world):
    """The labels of GET are the live object's (#375); protected and protectedBy are Git's, as the delete reads them."""
    client, ctx, git, *_, keys = world
    created(world)
    doc = yaml.safe_load(git.branches["main"][FOLDER])
    doc["metadata"]["labels"]["do-not-delete"] = "true"
    git.branches["main"][FOLDER] = yaml.safe_dump(doc)
    view = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()
    assert "do-not-delete" not in view["labels"]
    assert (view["protected"], view["protectedBy"]) == (True, ["do-not-delete=true"])
    d = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": view["etag"]})
    assert d.status_code == 422 and d.json()["code"] == "namespace-protected", d.text


def test_protecting_needs_no_approval_and_removing_it_needs_approver_platform(world):
    """cmapi.net/protected is a sensitiveKeys entry: setting it the first time is not a change, removing it is (#366)."""
    client, ctx, git, *_, keys = world
    created(world)
    r = patch(client, keys, {"labels": {"cmapi.net/protected": "true"}, "justification": "keep it"}, "opal", OPAL)
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)
    assert git_labels(git)["cmapi.net/protected"] == "true"
    r = patch(client, keys, {"labels": {"cmapi.net/protected": None}}, "opal", OPAL)
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    assert r.json()["approval"]["remaining"] == [{"group": "approver-platform", "needed": 1}], r.text
    assert "threshold sensitiveKeyChanged: +1 approver-platform" in r.json()["approval"]["reasons"], r.text
    rid = r.json()["requestId"]
    a = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **PLATFORM))
    assert a.status_code == 200 and a.json()["status"] == "approved", a.text
    run_jobs(ctx)
    assert "cmapi.net/protected" not in git_labels(git)
    assert client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["protected"] is False
    d = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": etag_of(client, keys)})
    assert d.status_code == 202, d.text


def test_the_delete_after_expiry_of_a_protected_namespace_is_refused(world):
    """decide() refuses a protected delete before it reads the reason, so the expiry delete is refused too."""
    from cmapi.core.errors import Problem
    from cmapi.core.identity.claims import Identity
    client, ctx, *_, keys = world
    created(world, {"cmapi.net/protected": "true"}, "opal", OPAL)
    worker = Identity(sub="sub-worker", username="cmapi-worker", kind="service", client_id="cmapi-worker",
                      roles=frozenset({"cmapi-operator"}))
    with pytest.raises(Problem) as refused:
        ctx.pipeline.plan_delete(worker, "CRC", "payments-dev", if_match=None, reason="expired")
    assert refused.value.code == "namespace-protected"
