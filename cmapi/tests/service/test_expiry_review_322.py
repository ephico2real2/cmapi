"""OB3 review of #322: each test fails on cba02d7 and passes with the fix in the review."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import cmapi.plugins.expiration.router as expiration_mod
from test_expirations import TODAY, created_namespace, fleet, page, write  # noqa: F401  (fleet is a fixture)
from test_flow import OLA, auth


def _age(kube, ctx, name: str, days: int) -> None:
    """The namespace on the cluster was created `days` ago, as its creationTimestamp says."""
    obj = kube.objects[("Namespace", "", name)]
    obj["metadata"]["creationTimestamp"] = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx.registry.cache("CRC")._list("Namespace")


def test_f1_set_past_the_lifetime_from_creation_adds_approver_platform(world):
    client, ctx, git, kube, validator, keys = world
    etag = created_namespace(client, ctx, keys)
    _age(kube, ctx, "payments-dev", 175)
    until = (date.today() + timedelta(days=20)).isoformat()          # 195 days from creation, past 180
    dry = write(client, keys, "set", {"until": until}, etag, dry=True)
    assert dry.status_code == 200, dry.text
    assert [s["group"] for s in dry.json()["approval"]["slots"]] == ["approver-platform"], dry.json()["approval"]


def test_f1_extend_past_the_lifetime_from_creation_adds_approver_platform(world):
    client, ctx, git, kube, validator, keys = world
    etag = created_namespace(client, ctx, keys, expiresAt=(date.today() + timedelta(days=10)).isoformat())
    _age(kube, ctx, "payments-dev", 175)
    dry = write(client, keys, "extend", {"days": 7}, etag, dry=True)  # 175 + 17 = 192 days from creation
    assert dry.status_code == 200, dry.text
    assert [s["group"] for s in dry.json()["approval"]["slots"]] == ["approver-platform"], dry.json()["approval"]


def test_f1_within_the_lifetime_adds_nothing(world):
    client, ctx, git, kube, validator, keys = world
    etag = created_namespace(client, ctx, keys, expiresAt=(date.today() + timedelta(days=10)).isoformat())
    _age(kube, ctx, "payments-dev", 30)
    dry = write(client, keys, "extend", {"days": 7}, etag, dry=True)
    assert dry.status_code == 200 and dry.json()["approval"]["slots"] == [], dry.text


def test_f2_extend_until_moves_an_existing_date(world):
    client, ctx, git, kube, validator, keys = world
    etag = created_namespace(client, ctx, keys, expiresAt=(date.today() + timedelta(days=10)).isoformat())
    want = (date.today() + timedelta(days=17)).isoformat()
    dry = write(client, keys, "extend", {"until": want}, etag, dry=True)
    assert dry.status_code == 200, dry.text
    assert f"cmapi.net/expires-at: '{want}'" in dry.json()["files"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"]
    too_far = write(client, keys, "extend", {"until": (date.today() + timedelta(days=41)).isoformat()}, etag, dry=True)
    assert too_far.status_code == 422 and too_far.json()["code"] == "expiration-limit", too_far.text


def test_f2_extend_until_on_a_permanent_namespace_is_not_a_set(world):
    client, ctx, git, kube, validator, keys = world
    etag = created_namespace(client, ctx, keys)
    r = write(client, keys, "extend", {"until": (date.today() + timedelta(days=10)).isoformat()}, etag, dry=True)
    assert r.status_code == 422 and r.json()["code"] == "expiration-not-set", r.text


def test_f3_a_cursor_from_another_day_is_refused(fleet, monkeypatch):
    client, ctx, git, kube, validator, keys = fleet
    first = page(client, keys, "?limit=3")
    monkeypatch.setattr(expiration_mod, "today", lambda: TODAY + timedelta(days=1))
    r = client.get(f"/api/v1/expirations?limit=3&cursor={first['page']['nextCursor']}", headers=auth(keys, "ola", **OLA))
    print("next day, page 2:", r.status_code, [i["name"] for i in r.json().get("items", [])])
    assert r.status_code == 400 and r.json()["code"] == "invalid-cursor", r.text
