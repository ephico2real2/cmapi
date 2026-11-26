"""#689: the token buckets of core/ratelimit.py, with a clock the test moves. The routes' use of them is
tests/service/test_rate_limits_689.py."""
from __future__ import annotations

import pytest

from cmapi.core.errors import Problem
from cmapi.core.ratelimit import DEFAULTS, MAX_BUCKETS, Limit, RateLimiter, parse_rate_limits, rate_class


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_bucket_gives_its_burst_then_one_token_for_each_period():
    clock = Clock()
    rl = RateLimiter(limits={"write": Limit(6, 3)}, clock=clock)      # a token each 10 s
    assert [rl.take("write", "ola") for _ in range(3)] == [None, None, None]
    refusal = rl.take("write", "ola")
    assert (refusal.kind, refusal.key, refusal.retry_after, refusal.first) == ("write", "ola", 10, True)
    assert rl.take("write", "ola").first is False                       # the same run of refusals
    clock.now += 9.9
    assert rl.take("write", "ola").retry_after == 1                     # whole seconds, never 0
    clock.now += 0.1
    assert rl.take("write", "ola") is None                              # after Retry-After, a token
    assert rl.take("write", "ola").first is True                        # a new run after a token was given


def test_each_caller_and_each_class_has_its_own_bucket():
    rl = RateLimiter(limits={**DEFAULTS, "read": Limit(60, 1), "write": Limit(60, 1)}, clock=Clock())
    assert rl.take("read", "ola") is None
    assert rl.take("read", "ola") is not None
    assert rl.take("read", "amy") is None
    assert rl.take("write", "ola") is None


def test_the_problem_says_who_is_limited_and_when_to_try_again():
    rl = RateLimiter(limits={**DEFAULTS, "team": Limit(1, 1)}, clock=Clock())
    rl.take("team", "payments")
    p = rl.take("team", "payments").problem()
    assert isinstance(p, Problem) and (p.status, p.code, p.extra) == (429, "rate-limited", {"retryAfter": 60})
    assert p.detail == "Too many new requests for team payments; try again in 60 s"


def test_the_buckets_stay_at_most_max_buckets_and_the_least_recently_used_goes_first():
    clock = Clock()
    rl = RateLimiter(limits={"read": Limit(60, 2)}, clock=clock)
    rl.take("read", "ola")
    rl.take("read", "ola")                            # ola's bucket is empty
    for i in range(MAX_BUCKETS - 1):
        assert rl.take("read", f"caller-{i}") is None
    assert len(rl._buckets) == MAX_BUCKETS
    assert rl.take("read", "ola") is not None         # used last of all but the newest: it keeps its state
    assert rl.take("read", "new") is None             # a full table drops the least recently used, never refuses
    assert len(rl._buckets) == MAX_BUCKETS and ("read", "caller-0") not in rl._buckets


def test_rate_class_follows_the_custom_method_then_the_http_method():
    assert [rate_class(m, p) for m, p in [("GET", "/api/v1/quotas:suggest"), ("GET", "/api/v1/quotas:export"),
                                         ("POST", "/api/v1/capacity:place"), ("PATCH", "/api/v1/x"), ("GET", "/api/v1/x")]] \
        == ["suggest", "export", "place", "write", "read"]


def test_the_limits_of_instance_yaml_go_over_the_defaults():
    limits, problems = parse_rate_limits({"write": {"burst": 5}, "export": {"perMinute": 0.5}})
    assert problems == []
    assert limits["write"] == Limit(60, 5) and limits["export"] == Limit(0.5, 2) and limits["read"] == DEFAULTS["read"]
    assert parse_rate_limits(None) == (DEFAULTS, [])


@pytest.mark.parametrize("raw, message", [
    ([], "http.rateLimits must be a mapping"),
    ({"default": {}}, "unknown classes ['default']"),
    ({"read": {"perMinute": -1}}, "perMinute is a number of calls a minute"),
    ({"read": {"perMinute": float("inf")}}, "not inf"),
    ({"read": {"perMinute": float("nan")}}, "not nan"),
    ({"read": {"perMinute": "60"}}, "not '60'"),
    ({"read": {"burst": 2**53}}, "burst is a whole number of calls, 1 to 9007199254740991, not 9007199254740992"),
    ({"read": {"burst": 1.0}}, "not 1.0"),
    ({"read": {"burst": False}}, "not False"),
])
def test_a_limit_that_is_not_valid_is_named(raw, message):
    limits, problems = parse_rate_limits(raw)
    assert any(message in p for p in problems), problems
    assert limits["read"] == DEFAULTS["read"]          # a bad value never becomes a limit
