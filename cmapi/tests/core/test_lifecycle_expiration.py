from datetime import date, timedelta

import pytest

from cmapi.core.errors import Problem
from cmapi.core.lifecycle import Event as E, State as S, allowed_events, holds_lock, transition
from cmapi.plugins.expiration.rules import ExpirationRules, ExpiryInfo
from conftest import ALL_ENVS, EX, INSTANCES

TODAY = date(2026, 11, 4)


# ---- lifecycle
def test_happy_path_create():
    s = None
    for ev, want in [(E.PLAN_NEEDS_APPROVAL, S.PENDING_APPROVAL), (E.APPROVED, S.APPROVED),
                     (E.PR_OPENED, S.PR_OPEN), (E.MERGED, S.MERGED), (E.SYNCED, S.SYNCED)]:
        t = transition(s, ev)
        assert t.after == want
        s = t.after
    assert t.releases_lock and t.releases_reservation


def test_delete_waits_for_prune():
    t = transition(S.MERGED, E.PRUNE_PENDING)
    assert t.after == S.AWAITING_PRUNE and t.releases_reservation and not t.releases_lock
    assert transition(S.AWAITING_PRUNE, E.PRUNE_CONFIRMED).releases_lock


def test_refusals():
    with pytest.raises(Problem) as e:
        transition(S.APPROVED, E.APPROVED)
    assert e.value.code == "not-pending"
    with pytest.raises(Problem):
        transition(S.PR_OPEN, E.CANCEL)                 # too late to cancel
    with pytest.raises(Problem) as e:
        transition(S.PENDING_APPROVAL, E.CANCEL, actor_is_requester=False)
    assert e.value.code == "forbidden"


def test_retry_and_sync_failed():
    t = transition(S.FAILED, E.RETRY)
    assert t.after == S.APPROVED and holds_lock(t.after)
    t = transition(S.MERGED, E.SYNC_TIMEOUT)
    assert t.after == S.SYNC_FAILED and holds_lock(S.SYNC_FAILED) and t.releases_reservation
    assert set(allowed_events(S.SYNC_FAILED)) == {E.RETRY, E.SYNCED, E.REVERT}


def test_every_terminal_state_releases_everything():
    for st in (S.SYNCED, S.REJECTED, S.CANCELLED, S.TIMEOUT, S.SUPERSEDED, S.FAILED):
        assert not holds_lock(st)


# ---- expiration
@pytest.fixture(scope="module")
def exp():
    return ExpirationRules.load(EX / "config/expiration.yaml", ALL_ENVS)


@pytest.mark.parametrize("instance,envs", INSTANCES.items())
def test_instance_files_load(instance, envs):
    r = ExpirationRules.load(EX / f"instances/{instance}/expiration.yaml", envs)
    assert not r.allows("prod")


def ns(**kw):
    base = dict(namespace="ledger-rnd", environment="rnd", created=TODAY - timedelta(days=60),
                expires_at=TODAY + timedelta(days=20))
    return ExpiryInfo(**{**base, **kw})


def test_prod_never_expires(exp):
    with pytest.raises(Problem) as e:
        exp.plan_create("prod", TODAY + timedelta(days=10), TODAY)
    assert e.value.code == "expiration-not-allowed"
    assert exp.plan_create("prod", None, TODAY) is None
    with pytest.raises(ValueError):
        ExpirationRules({"environments": {"prod": {}}})


def test_extend_limits(exp):
    p = exp.plan_extend(ns(), TODAY, days=30)
    assert p.new_date == TODAY + timedelta(days=50) and p.extra_approvals == ()
    with pytest.raises(Problem) as e:
        exp.plan_extend(ns(), TODAY, days=31)
    assert e.value.code == "expiration-limit"
    old = ns(created=TODAY - timedelta(days=170))
    assert exp.plan_extend(old, TODAY, days=20).extra_approvals == ("platform-leads",)


def test_set_and_make_permanent(exp):
    with pytest.raises(Problem):
        exp.plan_set(ns(), TODAY + timedelta(days=10), TODAY)          # already has a date
    assert exp.plan_set(ns(expires_at=None), TODAY + timedelta(days=30), TODAY).new_date
    assert exp.plan_make_permanent(ns()).extra_approvals == ("platform-leads",)


@pytest.mark.parametrize("days,state", [(None, "permanent"), (40, "active"), (14, "expiring"), (1, "expiring"),
                                        (0, "grace"), (-6, "grace"), (-7, "pending_delete")])
def test_states(exp, days, state):
    e = None if days is None else TODAY + timedelta(days=days)
    assert exp.state(ns(expires_at=e), TODAY) == state


def test_expire_check(exp):
    items = [ns(namespace="a", expires_at=TODAY + timedelta(days=7), notices_sent=frozenset({14})),
             ns(namespace="b", expires_at=TODAY - timedelta(days=10), notices_sent=frozenset({14, 7, 1})),
             ns(namespace="c", expires_at=TODAY - timedelta(days=10), notices_sent=frozenset({1})),
             ns(namespace="d", expires_at=TODAY - timedelta(days=10), notices_sent=frozenset({14, 7}),
                open_request=True),
             ns(namespace="p", environment="prod", expires_at=None)]
    out = exp.expire_check(items, TODAY)
    assert out.notify == [("a", 7)]
    assert [d["namespace"] for d in out.open_delete] == ["b"]
    assert out.open_delete[0]["reason"] == "expired" and out.open_delete[0]["noticesSent"] == 3
    assert dict(out.held) == {"c": "noticesSentAtLeast2", "d": "noOpenRequest"}


# ---- regressions from the code review
def test_retry_reacquires_and_sync_failed_retry_rewatches():
    t = transition(S.FAILED, E.RETRY)
    assert t.acquires_lock and t.acquires_reservation
    t = transition(S.SYNC_FAILED, E.RETRY)
    assert t.after == S.SYNC_FAILED and not t.releases_reservation and not t.acquires_reservation
    t = transition(S.SYNC_FAILED, E.REVERT)
    assert t.after == S.REVERTED and t.releases_lock          # the revert request can take the lock


def test_operator_may_cancel():
    assert transition(S.PENDING_APPROVAL, E.CANCEL, actor_is_requester=False, actor_is_operator=True).after == S.CANCELLED


def test_grace_starts_on_the_date(exp):
    out = exp.expire_check([ns(namespace="g", expires_at=TODAY, notices_sent=frozenset({14, 7, 1}))], TODAY)
    assert out.entered_grace == ["g"] and out.notify == []


def test_short_expiry_still_gets_the_one_day_notice(exp):
    out = exp.expire_check([ns(namespace="s", expires_at=TODAY + timedelta(days=1))], TODAY)
    assert out.notify == [("s", 1)]
