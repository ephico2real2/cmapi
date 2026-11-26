"""#695 review: the private docs take from the caller's read bucket, and the team's token is spent only for a change request
that is recorded, on PostgreSQL with real connections. The buckets themselves are tests/core/test_ratelimit_review_695.py."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from cmapi.core.db.models import ChangeRequestRow
from cmapi.core.db.repo import RequestRepo
from cmapi.core.errors import Problem
from cmapi.core.ratelimit import DEFAULTS, Limit, RateLimiter
from conftest import build_world
from test_api_docs import DOCS_PATHS, _config as docs_config
from test_rate_limits_689 import CONTRACT, NS, REQUESTER, URL, auth, limited  # noqa: F401  (limited is a fixture)

ONE_TEAM_TOKEN = [{"team": {"perMinute": 1, "burst": 1}}]


def _team_tokens_left(ctx, team: str) -> int:
    """Empties the team's bucket and says how many tokens it held. The tests' clock does not move, so none refills."""
    left = 0
    while ctx.limiter.take("team", team) is None:
        left += 1
    return left


def _recorded(ctx) -> int:
    with ctx.db.session() as s:
        return s.scalar(select(func.count()).select_from(ChangeRequestRow))


def test_each_operation_that_takes_a_token_charges_its_caller_once_from_its_class(world, monkeypatch):
    """Reviewer 1's dispatch check, kept as a guard: every operation of the contract, and the HEAD of each GET, takes one
    token of the class that `x-cmapi-rate-limit` names from the token's subject; the routes without a token take none."""
    client, ctx, *_, keys = world
    calls = []
    monkeypatch.setattr(ctx.limiter, "take", lambda kind, sub: calls.append((kind, sub)))
    headers = auth(keys, "viewer", roles=[], groups=[])
    for template, operations in json.loads(CONTRACT.read_text())["paths"].items():
        path = re.sub(r"\{[^}]+\}", "example", template)
        for op, details in operations.items():
            kind = {"/api/v1/quotas:export": "export", "/api/v1/quotas:suggest": "suggest"}.get(
                template, "read" if op == "get" else "write")
            for method in (op, "head") if op == "get" else (op,):
                calls.clear()
                client.request(method, path, headers=headers, json={} if "requestBody" in details else None)
                expected = [(kind, "sub-viewer")] if details.get("security") else []
                assert calls == expected, (method, template, calls)
                assert details.get("x-cmapi-rate-limit") == (kind if expected else None), template
    for path in ["/healthz", "/readyz", "/problems", "/problems/rate-limited", *DOCS_PATHS, "/docs/oauth2-redirect"]:
        calls.clear()
        client.get(path)
        assert calls == [], path


def test_private_docs_take_from_the_callers_read_bucket(test_config, tmp_path, keys, monkeypatch):
    """docs.public: false makes the seven docs paths take a token; head checked the token and counted nothing, so a caller
    could fetch the 877 KB /openapi.json without limit. A call with no token is still 401 and takes nothing."""
    with build_world(docs_config(test_config, tmp_path, {"public": False}), keys, monkeypatch) as world:
        client, ctx, *_ = world
        ctx.limiter = RateLimiter(limits={**DEFAULTS, "read": Limit(1, 1)}, clock=lambda: 0.0)
        headers = auth(keys, "reader", roles=[], groups=[])
        assert client.get("/api/v1/me", headers=headers).status_code == 200      # the read bucket's one token
        for path in DOCS_PATHS:
            for method in ("GET", "HEAD"):
                assert client.request(method, path).status_code == 401, (method, path)
                r = client.request(method, path, headers=headers)
                assert r.status_code == 429 and r.headers["Retry-After"] == "60", (method, path, r.status_code)


@pytest.mark.parametrize("limited", ONE_TEAM_TOKEN, indirect=True)
def test_a_submit_that_fails_after_its_insert_gives_the_team_token_back(limited, monkeypatch):
    from cmapi.plugins.namespaces import router

    world, _ = limited
    client, ctx, *_, keys = world

    def fail(*_args):
        raise Problem(503, "validator-unavailable", "the transaction fails after its INSERT", extra={"retryAfter": 60})

    with monkeypatch.context() as m:
        m.setattr(router, "record_warned", fail)
        assert client.post(URL, json=NS, headers=auth(keys, "ola", **REQUESTER)).status_code == 503
    assert _recorded(ctx) == 0
    assert client.post(URL, json=NS, headers=auth(keys, "ola", **REQUESTER)).status_code == 202


@pytest.mark.parametrize("limited", [{"team": {"perMinute": 1, "burst": 2}}], indirect=True)
def test_a_lost_race_to_the_same_key_replays_the_winner_and_gives_the_team_token_back(limited, monkeypatch):
    """The retry's first lookup misses the winner, its INSERT meets an index, and `_submit` answers with the winner (#592).
    It recorded nothing, so the team's token comes back and a third request still has one."""
    world, _ = limited
    client, ctx, *_, keys = world
    headers = auth(keys, "ola", **REQUESTER)
    first = client.post(URL, json=NS, headers=headers)
    assert first.status_code == 202, first.text
    lookup, misses = RequestRepo.by_idempotency, [True]
    with monkeypatch.context() as m:
        m.setattr(RequestRepo, "by_idempotency", lambda *a: None if misses and misses.pop() else lookup(*a))
        again = client.post(URL, json=NS, headers=headers)
    assert again.status_code == 202 and again.json()["requestId"] == first.json()["requestId"], again.text
    other = client.post(URL, json={**NS, "namespace": "payments-two-dev"}, headers=auth(keys, "ola", **REQUESTER))
    assert other.status_code == 202, other.text


@pytest.mark.parametrize("limited", ONE_TEAM_TOKEN, indirect=True)
def test_a_retry_refused_by_the_team_gets_the_request_its_key_already_made(limited, monkeypatch):
    """The winner committed after the retry's first lookup, and spent the team's last token: the retry's answer is the
    winner's request, as a lost race to the INSERT is, not a 429 for a request that exists."""
    world, _ = limited
    client, *_, keys = world
    headers = auth(keys, "ola", **REQUESTER)
    first = client.post(URL, json=NS, headers=headers)
    assert first.status_code == 202, first.text
    lookup, misses = RequestRepo.by_idempotency, [True]
    monkeypatch.setattr(RequestRepo, "by_idempotency", lambda *a: None if misses and misses.pop() else lookup(*a))
    replay = client.post(URL, json=NS, headers=headers)
    assert replay.status_code == 202 and replay.json()["requestId"] == first.json()["requestId"], replay.text


@pytest.mark.parametrize("limited", [{"team": {"perMinute": 1, "burst": 5}}], indirect=True)
def test_concurrent_submits_spend_exactly_the_tokens_of_the_requests_recorded(limited, monkeypatch):
    """8 creates for one team at once, through the app's thread pool and PostgreSQL's advisory lock; each odd one fails
    after its INSERT and rolls back. 5 tokens for 8 requests, and only 4 are even, so at least 1 odd one took a token:
    whatever the interleaving, the bucket ends with 5 less the requests recorded. 8, under the pool's 10 connections:
    more submits at once than that starve the pool on head (the review's follow-up, pool starvation)."""
    from cmapi.plugins.namespaces import router

    world, _ = limited
    client, ctx, *_, keys = world
    real = router.record_warned

    def fail_odd(s, c, plan, request_id):
        if int(plan.namespace.split("-")[1].removeprefix("n")) % 2:
            raise Problem(503, "validator-unavailable", "the transaction fails after its INSERT", extra={"retryAfter": 60})
        return real(s, c, plan, request_id)

    monkeypatch.setattr(router, "record_warned", fail_odd)

    def create(i: int) -> int:
        body = {**NS, "namespace": f"payments-n{i}-dev"}
        return client.post(URL, json=body, headers=auth(keys, f"user{i}", **REQUESTER)).status_code

    with ThreadPoolExecutor(8) as pool:
        statuses = list(pool.map(create, range(8)))
    recorded = _recorded(ctx)
    assert set(statuses) <= {202, 429, 503} and statuses.count(503) >= 1, statuses
    assert recorded == statuses.count(202), (recorded, statuses)
    assert _team_tokens_left(ctx, "payments") == 5 - recorded, statuses


@pytest.mark.parametrize("limited", ONE_TEAM_TOKEN, indirect=True)
def test_a_team_transfer_charges_the_team_that_the_request_records(limited):
    """The team of a change request is its cmapi.net/team after the change: the row's `team`, the team whose auto-approvals
    of the day it counts (pipeline.submit), and the team it is counted under in the KPI report. The team's bucket is that
    team's too, so a request opened for billing is billing's, whoever held the namespace before."""
    world, clock = limited
    client, ctx, git, *_, keys = world
    headers = auth(keys, "ola", **REQUESTER)
    rendered = client.post(URL + "?dryRun=true", json=NS, headers=headers)
    assert rendered.status_code == 200
    git.branches["main"].update(rendered.json()["files"])
    path = f"{URL}/{NS['namespace']}"
    etag = client.get(path, headers=headers).headers["etag"]
    assert ctx.limiter.take("team", "billing") is None                  # billing's one token is gone
    patch = {"labels": {"cmapi.net/team": "billing"}}
    refused = client.patch(path, json=patch, headers={**auth(keys, "ola", **REQUESTER), "If-Match": etag})
    assert refused.status_code == 429 and "team billing" in refused.json()["detail"], refused.text
    clock.now += 60                                                     # billing has a token again
    opened = client.patch(path, json=patch, headers={**auth(keys, "ola", **REQUESTER), "If-Match": etag})
    assert opened.status_code == 202, opened.text
    with ctx.db.session() as s:
        assert s.scalar(select(ChangeRequestRow.team)) == "billing"
    assert _team_tokens_left(ctx, "payments") == 1                      # payments was not charged
