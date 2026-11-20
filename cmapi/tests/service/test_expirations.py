"""GET /api/v1/expirations and the expiry writes beside :extend (#318, portal slice 4a).

The list reads `cmapi.net/expires-at` from the watch cache; the writes plan from Git under If-Match. The last tests prove
that the two agree: a date set through the API is the date that the list shows once the request is synced.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

import cmapi.plugins.expiration.router as expiration_mod
from cmapi.core.db.models import ExpirationNoticeRow
from test_flow import AMY, NS, OLA, auth, run_jobs

TODAY = date(2026, 11, 16)
BOT_RND = dict(roles=["cmapi-bot-rnd"], groups=[])                 # objects:read in rnd only: outside the CRC cluster's dev
RELAY = dict(roles=["cmapi-approval-relay"], groups=[])             # requests:read and approvals:relay, no objects:read


def day(n: int) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


def put(kube, name: str, *, expires: str | None = None, team: str = "payments", created: str = "2026-10-01T09:00:00Z",
        managed: bool = True, env: str = "dev") -> None:
    """A namespace on the fake cluster, as Argo CD or the deliverer leaves it: labels, the expiry annotation, the creation time."""
    labels = {"cmapi.net/env": env, "cmapi.net/team": team, **({"cmapi.net/managed": "true"} if managed else {})}
    ann = {"cmapi.net/expires-at": expires} if expires is not None else {}
    kube.objects[("Namespace", "", name)] = {"kind": "Namespace", "metadata": {"name": name, "labels": labels, "annotations": ann,
                                                                              "creationTimestamp": created}}


@pytest.fixture
def fleet(world, monkeypatch):
    """One namespace in each state and on each date edge, the day fixed at TODAY. Rules of dev: notices at 14, 7, 1; grace 7."""
    client, ctx, git, kube, validator, keys = world
    monkeypatch.setattr(expiration_mod, "today", lambda: TODAY)
    put(kube, "perm-dev")                                    # no date
    put(kube, "far-dev", expires=day(15))                    # past the first notice: active
    put(kube, "notice-dev", expires=day(14), team="ledger")  # the first notice: expiring
    put(kube, "tomorrow-dev", expires=day(1))                # expiring
    put(kube, "today-dev", expires=day(0), team="ledger")    # the date itself is the first day of grace
    put(kube, "past-dev", expires=day(-1))                   # grace
    put(kube, "lastgrace-dev", expires=day(-6))              # the last day of grace
    put(kube, "gone-dev", expires=day(-7), team="ledger")    # grace is over: pending_delete
    put(kube, "other-ns", managed=False, expires=day(3))     # not managed by cmapi: never listed
    ctx.registry.cache("CRC")._list("Namespace")
    return world


def page(client, keys, query: str = "", who=OLA, user: str = "ola"):
    r = client.get(f"/api/v1/expirations{query}", headers=auth(keys, user, **who))
    assert r.status_code == 200, r.text
    return r.json()


def names(body) -> list[str]:
    return [i["name"] for i in body["items"]]


def test_each_state_and_the_date_edges(fleet):
    client, ctx, git, kube, validator, keys = fleet
    body = page(client, keys, "?sort=name")
    rows = {i["name"]: i for i in body["items"]}
    assert set(rows) == {"perm-dev", "far-dev", "notice-dev", "tomorrow-dev", "today-dev", "past-dev", "lastgrace-dev", "gone-dev"}
    want = {"perm-dev": ("permanent", None), "far-dev": ("active", 15), "notice-dev": ("expiring", 14), "tomorrow-dev": ("expiring", 1),
            "today-dev": ("grace", 0), "past-dev": ("grace", -1), "lastgrace-dev": ("grace", -6), "gone-dev": ("pending_delete", -7)}
    assert {n: (r["state"], r["daysLeft"]) for n, r in rows.items()} == want
    assert body["today"] == TODAY.isoformat()
    assert rows["perm-dev"]["expiresAt"] is None and rows["perm-dev"]["graceEnds"] is None and rows["perm-dev"]["lifetimeDays"] is None
    assert rows["past-dev"]["graceEnds"] == day(6), "the first day after the 7 days of grace, from the date"
    assert rows["far-dev"]["created"] == "2026-10-01" and rows["far-dev"]["lifetimeDays"] == (TODAY + timedelta(days=15) - date(2026, 10, 1)).days
    assert rows["far-dev"]["env"] == "dev" and rows["far-dev"]["team"] == "payments" and rows["far-dev"]["clusterId"] == "CRC"
    assert body["rules"] == {"dev": {"maxExtensionDays": 30, "maxLifetimeDays": 180, "notifyDaysBefore": [14, 7, 1], "graceDays": 7}}
    assert body["facets"] == {"attention": 6, "expiring": 2, "grace": 3, "pending_delete": 1, "active": 1, "permanent": 1}


def test_most_urgent_first_by_default_and_by_name_on_request(fleet):
    client, ctx, git, kube, validator, keys = fleet
    assert names(page(client, keys)) == ["lastgrace-dev", "past-dev", "today-dev", "tomorrow-dev", "notice-dev", "gone-dev", "far-dev", "perm-dev"]
    assert names(page(client, keys, "?sort=name")) == sorted(names(page(client, keys)))
    bad = client.get("/api/v1/expirations?sort=used", headers=auth(keys, "ola", **OLA))
    assert bad.status_code == 400 and bad.json()["code"] == "invalid-sort"


def test_cursor_paging_forward_and_back_and_the_cursor_is_bound_to_the_filters(fleet):
    client, ctx, git, kube, validator, keys = fleet
    everything = names(page(client, keys))
    first = page(client, keys, "?limit=3")
    assert names(first) == everything[:3] and first["page"] == {**first["page"], "total": 8, "from": 1, "to": 3, "prevCursor": None}
    second = page(client, keys, f"?limit=3&cursor={first['page']['nextCursor']}")
    assert names(second) == everything[3:6] and second["page"]["from"] == 4
    third = page(client, keys, f"?limit=3&cursor={second['page']['nextCursor']}")
    assert names(third) == everything[6:] and third["page"]["nextCursor"] is None
    back = page(client, keys, f"?limit=3&cursor={third['page']['prevCursor']}")
    assert names(back) == everything[3:6]
    moved = client.get(f"/api/v1/expirations?limit=3&state=grace&cursor={first['page']['nextCursor']}", headers=auth(keys, "ola", **OLA))
    assert moved.status_code == 400 and moved.json()["code"] == "invalid-cursor"
    assert client.get("/api/v1/expirations?limit=0", headers=auth(keys, "ola", **OLA)).json()["code"] == "invalid-limit"


def test_every_filter(fleet):
    client, ctx, git, kube, validator, keys = fleet
    assert names(page(client, keys, "?state=attention&sort=name")) == ["gone-dev", "lastgrace-dev", "notice-dev", "past-dev", "today-dev", "tomorrow-dev"]
    for state, want in {"expiring": ["notice-dev", "tomorrow-dev"], "grace": ["lastgrace-dev", "past-dev", "today-dev"],
                        "pending_delete": ["gone-dev"], "active": ["far-dev"], "permanent": ["perm-dev"]}.items():
        body = page(client, keys, f"?state={state}&sort=name")
        assert names(body) == want, state
        assert body["facets"]["attention"] == 6, "a chosen state keeps the other chips' counts"
    bad = client.get("/api/v1/expirations?state=soon", headers=auth(keys, "ola", **OLA))
    assert bad.status_code == 422 and bad.json()["code"] == "validation-failed" and "pending_delete" in bad.json()["detail"]
    assert names(page(client, keys, "?team=ledger&sort=name")) == ["gone-dev", "notice-dev", "today-dev"]
    assert names(page(client, keys, "?q=past")) == ["past-dev"]
    assert names(page(client, keys, "?q=LEDG&sort=name")) == ["gone-dev", "notice-dev", "today-dev"], "the team label, any case"
    assert names(page(client, keys, "?env=rnd")) == [] and len(names(page(client, keys, "?env=dev"))) == 8
    assert names(page(client, keys, "?clusterId=OTHER")) == [] and len(names(page(client, keys, "?clusterId=CRC"))) == 8
    ledger = page(client, keys, "?team=ledger")
    assert ledger["facets"] == {"attention": 3, "expiring": 1, "grace": 1, "pending_delete": 1, "active": 0, "permanent": 0}


def test_notices_and_the_open_request_come_from_the_database(fleet):
    client, ctx, git, kube, validator, keys = fleet
    with ctx.db.session() as s:
        for threshold in (14, 7, 7):                          # the same threshold twice is one notice
            s.add(ExpirationNoticeRow(cluster_id="CRC", namespace="tomorrow-dev", expires_at=day(1), threshold_days=threshold))
        s.add(ExpirationNoticeRow(cluster_id="CRC", namespace="tomorrow-dev", expires_at=day(1), threshold_days=1, ok=False))
        s.add(ExpirationNoticeRow(cluster_id="CRC", namespace="tomorrow-dev", expires_at=day(-30), threshold_days=1))
        s.add(ExpirationNoticeRow(cluster_id="CRC", namespace="past-dev", expires_at=day(-1), threshold_days=0))
    rows = {i["name"]: i for i in page(client, keys)["items"]}
    assert rows["tomorrow-dev"]["noticesSent"] == 2, "14 and 7 for this date: not a failed send, not an older date"
    assert rows["past-dev"]["noticesSent"] == 0, "the grace notice is not one of the notices before the date"
    assert all(r["openRequest"] is None for r in rows.values())


def test_a_value_that_is_not_a_date_is_listed_and_does_not_fail_the_list(fleet):
    client, ctx, git, kube, validator, keys = fleet
    put(kube, "odd-dev", expires="soon")
    ctx.registry.cache("CRC")._list("Namespace")
    row = next(i for i in page(client, keys)["items"] if i["name"] == "odd-dev")
    assert row["expiresAt"] == "soon" and row["daysLeft"] is None and row["state"] == "permanent"


def test_a_caller_outside_the_environment_sees_no_row_and_no_rule(fleet):
    client, ctx, git, kube, validator, keys = fleet
    body = page(client, keys, who=BOT_RND, user="bot")
    assert body["items"] == [] and body["rules"] == {} and body["page"]["total"] == 0
    assert body["facets"] == {"attention": 0, "expiring": 0, "grace": 0, "pending_delete": 0, "active": 0, "permanent": 0}


def test_a_caller_without_objects_read_is_refused(fleet):
    client, ctx, git, kube, validator, keys = fleet
    r = client.get("/api/v1/expirations", headers=auth(keys, "relay", **RELAY))
    assert r.status_code == 403 and r.json()["code"] == "forbidden" and "objects:read" in r.json()["detail"]
    assert client.get("/api/v1/expirations").status_code == 401


def test_an_environment_where_nothing_expires_and_nothing_kept_a_date_is_left_out(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    monkeypatch.setattr(expiration_mod, "today", lambda: TODAY)
    put(kube, "perm-dev")
    ctx.registry.cache("CRC")._list("Namespace")
    monkeypatch.setattr(ctx.cfg.expiration, "envs", {})       # as on prod: expiration.yaml has no entry for the environment
    body = page(client, keys)
    assert body["items"] == [] and body["rules"] == {}


@pytest.mark.parametrize("off", ["no entry", "enabled: false"])
def test_where_expiration_is_off_a_namespace_that_kept_a_date_is_listed_with_make_permanent_only(fleet, monkeypatch, off):
    """The coordinator's ruling on F02 (#479): the kept date shows, and Make permanent is the one write offered."""
    client, ctx, git, kube, validator, keys = fleet
    envs = ctx.cfg.expiration.envs
    monkeypatch.setattr(ctx.cfg.expiration, "envs", {} if off == "no entry" else {**envs, "dev": replace(envs["dev"], enabled=False)})
    body = page(client, keys, "?sort=name")
    assert names(body) == ["far-dev", "gone-dev", "lastgrace-dev", "notice-dev", "past-dev", "today-dev", "tomorrow-dev"]
    rows = {i["name"]: i for i in body["items"]}
    assert rows["far-dev"]["expiresAt"] == day(15) and rows["far-dev"]["daysLeft"] == 15
    assert all(r["actions"] == ["makePermanent"] and r["state"] == "permanent" and r["graceEnds"] is None
               for r in rows.values()), "no notice and no delete where expiration is off"
    assert body["rules"] == {}


def test_each_row_offers_the_expiry_writes_its_namespace_takes(fleet):
    client, ctx, git, kube, validator, keys = fleet
    rows = {i["name"]: i for i in page(client, keys)["items"]}
    assert rows["perm-dev"]["actions"] == ["set"]
    assert rows["far-dev"]["actions"] == rows["gone-dev"]["actions"] == ["extend", "makePermanent"]


# --------------------------------------------------------------------------- the writes, and the agreement of list and Git

def created_namespace(client, ctx, keys, name="payments-dev", **extra):
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": name, **extra}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    if r.json()["status"] == "pending_approval":
        client.post(f"/api/v1/requests/{r.json()['requestId']}:approve", json={}, headers=auth(keys, "amy", **AMY))
    run_jobs(ctx)
    ctx.registry.cache("CRC")._list("Namespace")
    return client.get(f"/api/v1/clusters/CRC/namespaces/{name}", headers=auth(keys, "ola", **OLA)).json()["etag"]


def write(client, keys, path: str, body: dict, etag: str | None, *, dry: bool = False, key: str | None = None):
    headers = auth(keys, "ola", **OLA)
    headers["Idempotency-Key"] = key or str(uuid.uuid4())
    if etag is not None:
        headers["If-Match"] = f'"{etag}"'
    return client.post(f"/api/v1/clusters/CRC/namespaces/payments-dev/expiration:{path}{'?dryRun=true' if dry else ''}", json=body, headers=headers)


def test_set_gives_a_permanent_namespace_a_date_and_the_list_shows_the_date_that_git_holds(world):
    client, ctx, git, kube, validator, keys = world
    etag = created_namespace(client, ctx, keys)
    until = (date.today() + timedelta(days=20)).isoformat()
    dry = write(client, keys, "set", {"until": until, "justification": "One sprint"}, etag, dry=True)
    assert dry.status_code == 200, dry.text
    assert dry.json()["changes"] == {"clusters/CRC/namespaces/payments-dev/namespace.yaml": "changed"}
    assert f"cmapi.net/expires-at: '{until}'" in dry.json()["files"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"]
    assert client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["page"]["total"] == 1, "the dry run wrote nothing"
    assert write(client, keys, "set", {"until": until}, None).json()["code"] == "precondition-required"
    assert write(client, keys, "set", {"until": until}, "stale").json()["code"] == "precondition-failed"
    r = write(client, keys, "set", {"until": until, "justification": "One sprint"}, etag)
    assert r.status_code == 202 and r.json()["status"] == "approved" and r.json()["reason"] == "expiration:set", r.text
    listed = client.get("/api/v1/expirations", headers=auth(keys, "ola", **OLA)).json()["items"]
    assert [(i["name"], i["expiresAt"], i["openRequest"]) for i in listed] == [("payments-dev", None, r.json()["requestId"])], \
        "until the cluster has the date the row shows the request that holds it"
    run_jobs(ctx)
    ctx.registry.cache("CRC")._list("Namespace")
    row = client.get("/api/v1/expirations", headers=auth(keys, "ola", **OLA)).json()["items"][0]
    assert (row["expiresAt"], row["daysLeft"], row["state"], row["openRequest"]) == (until, 20, "active", None)
    in_git = git.branches["main"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"]
    assert f"cmapi.net/expires-at: '{until}'" in in_git, "the list and Git hold one date"
    again = write(client, keys, "set", {"until": until}, client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=auth(keys, "ola", **OLA)).json()["etag"])
    assert again.status_code == 422 and again.json()["code"] == "expiration-already-set"


def test_extend_has_a_dry_run_and_the_list_follows_the_extension(world):
    client, ctx, git, kube, validator, keys = world
    etag = created_namespace(client, ctx, keys, expiresAt=(date.today() + timedelta(days=10)).isoformat())
    dry = write(client, keys, "extend", {"days": 7}, etag, dry=True)
    assert dry.status_code == 200 and dry.json()["approval"]["slots"] == [], dry.text
    want = (date.today() + timedelta(days=17)).isoformat()
    assert f"cmapi.net/expires-at: '{want}'" in dry.json()["files"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"]
    assert len(client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["items"]) == 1
    r = write(client, keys, "extend", {"days": 7}, etag)
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)
    ctx.registry.cache("CRC")._list("Namespace")
    row = client.get("/api/v1/expirations", headers=auth(keys, "ola", **OLA)).json()["items"][0]
    assert (row["expiresAt"], row["daysLeft"], row["state"]) == (want, 17, "active")


def test_make_permanent_needs_approver_platform_and_removes_the_date(world):
    client, ctx, git, kube, validator, keys = world
    etag = created_namespace(client, ctx, keys, expiresAt=(date.today() + timedelta(days=10)).isoformat())
    dry = write(client, keys, "makePermanent", {}, etag, dry=True)
    assert dry.status_code == 200, dry.text
    assert [s["group"] for s in dry.json()["approval"]["slots"]] == ["approver-platform"]
    assert "cmapi.net/expires-at" not in dry.json()["files"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"]
    r = write(client, keys, "makePermanent", {"justification": "In production use"}, etag)
    assert r.status_code == 202 and r.json()["status"] == "pending_approval" and r.json()["reason"] == "expiration:makePermanent", r.text
    assert client.post(f"/api/v1/requests/{r.json()['requestId']}:approve", json={}, headers=auth(keys, "amy", **AMY)).status_code == 200
    run_jobs(ctx)
    ctx.registry.cache("CRC")._list("Namespace")
    row = client.get("/api/v1/expirations", headers=auth(keys, "ola", **OLA)).json()["items"][0]
    assert (row["expiresAt"], row["state"]) == (None, "permanent")
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=auth(keys, "ola", **OLA)).json()["etag"]
    again = write(client, keys, "makePermanent", {}, etag)
    assert again.status_code == 422 and again.json()["code"] == "expiration-not-set"


def test_one_key_on_set_and_on_extend_until_is_two_requests_not_a_replay(world):
    client, ctx, git, kube, validator, keys = world
    etag = created_namespace(client, ctx, keys)
    until, key = (date.today() + timedelta(days=20)).isoformat(), str(uuid.uuid4())
    first = write(client, keys, "set", {"until": until}, etag, key=key)
    assert first.status_code == 202, first.text
    assert write(client, keys, "set", {"until": until}, etag, key=key).json()["requestId"] == first.json()["requestId"], "the same call is a replay"
    other = write(client, keys, "extend", {"until": until}, etag, key=key)
    assert other.status_code == 409 and other.json()["code"] == "idempotency-replay"


def test_a_caller_without_namespaces_write_cannot_set_or_make_permanent(world):
    client, ctx, git, kube, validator, keys = world
    viewer = dict(roles=["cmapi-viewer"], groups=[])
    for path, body in (("set", {"until": "2027-01-01"}), ("makePermanent", {})):
        r = client.post(f"/api/v1/clusters/CRC/namespaces/payments-dev/expiration:{path}", json=body,
                        headers={**auth(keys, "val", **viewer), "If-Match": '"x"'})
        assert r.status_code == 403 and r.json()["code"] == "forbidden", path


def test_the_creation_time_is_read_with_and_without_a_z():
    assert expiration_mod._created({"creationTimestamp": "2026-10-01T09:00:00Z"}) == date(2026, 10, 1)
    assert expiration_mod._created({"creationTimestamp": datetime(2026, 10, 2, 23, 0, tzinfo=timezone.utc).isoformat()}) == date(2026, 10, 2)
    assert expiration_mod._created({}) is None and expiration_mod._created({"creationTimestamp": "yesterday"}) is None


def test_a_date_kept_where_expiration_is_now_off_is_made_permanent_from_the_list(world, monkeypatch):
    """End to end (#479, ruling on F02): dated while dev took expiry; dev turned off; the list offers Make permanent; it plans."""
    client, ctx, git, kube, validator, keys = world
    until = (date.today() + timedelta(days=20)).isoformat()
    etag = created_namespace(client, ctx, keys, expiresAt=until)
    envs = ctx.cfg.expiration.envs
    monkeypatch.setitem(envs, "dev", replace(envs["dev"], enabled=False))
    row = next(i for i in page(client, keys)["items"] if i["name"] == "payments-dev")
    assert row["expiresAt"] == until and row["actions"] == ["makePermanent"]
    planned = write(client, keys, "makePermanent", {"justification": "dev no longer expires"}, etag, dry=True)
    assert planned.status_code == 200, planned.text
    assert "cmapi.net/expires-at" not in planned.json()["files"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"]
    extended = write(client, keys, "extend", {"days": 5}, etag, dry=True)
    assert extended.status_code == 422 and extended.json()["code"] == "expiration-not-allowed"
