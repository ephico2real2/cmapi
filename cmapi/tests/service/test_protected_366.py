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
