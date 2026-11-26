"""#695 review: the bound on the buckets, the token given back, a rate near 0, with a clock the test
moves. The routes' use of them is tests/service/test_rate_limits_review_695.py."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from cmapi.core.ratelimit import Limit, RateLimiter, parse_rate_limits

# The bound that the review asked for, written out so that this file also runs against a limiter without the constant.
BOUND = 10_000
LARGEST = 2**53 - 1


def test_buckets_that_are_not_full_stay_bounded_and_a_new_caller_is_never_refused_for_room():
    """Head kept every bucket that had not refilled, so 10,001 callers left 10,001 buckets. A table that refused a new key
    when full would let whoever fills it lock every new caller out (nginx removes the least recently used state)."""
    rl = RateLimiter(limits={"read": Limit(60, 1)}, clock=lambda: 0.0)
    for i in range(BOUND + 1):
        assert rl.take("read", f"caller-{i}") is None, i       # each new caller gets its first token
    assert len(rl._buckets) == BOUND
    assert ("read", "caller-0") not in rl._buckets              # the least recently used went
    assert rl.take("read", f"caller-{BOUND}") is not None       # the newest kept its spent bucket


def test_a_token_given_back_can_be_taken_again_and_never_raises_the_burst():
    rl = RateLimiter(limits={"team": Limit(1, 2)}, clock=lambda: 0.0)
    assert rl.take("team", "payments") is None
    assert rl.take("team", "payments") is None
    assert rl.take("team", "payments") is not None
    rl.give_back("team", "payments")
    assert rl.take("team", "payments") is None
    rl.give_back("team", "payments")
    rl.give_back("team", "payments")
    rl.give_back("team", "payments")                            # more than was taken: the bucket stops at its burst
    assert rl.take("team", "payments") is None and rl.take("team", "payments") is None
    assert rl.take("team", "payments") is not None
    rl.give_back("team", "billing")                             # no bucket: nothing to give back, and none is made
    assert ("team", "billing") not in rl._buckets


def test_takes_and_gives_back_from_many_threads_leave_exactly_the_tokens_not_used():
    """200 threads each take a token of a burst of 50, and those with an even number give it back, in any order: what is
    left is the burst less the tokens kept, whatever the interleaving (the clock does not move, so nothing refills)."""
    rl = RateLimiter(limits={"team": Limit(1, 50)}, clock=lambda: 0.0)

    def submit(i: int) -> str:
        if rl.take("team", "payments") is not None:
            return "refused"
        if i % 2 == 0:
            rl.give_back("team", "payments")
            return "given back"
        return "kept"

    with ThreadPoolExecutor(32) as pool:
        outcomes = list(pool.map(submit, range(200)))
    left = 0
    while rl.take("team", "payments") is None:
        left += 1
    assert outcomes.count("kept") > 0 and left == 50 - outcomes.count("kept"), (left, outcomes.count("kept"))


def test_a_rate_near_zero_waits_the_largest_setting_instead_of_raising():
    """60 / 5e-324 is inf, and math.ceil(inf) raises OverflowError: a 500 where a 429 was due."""
    limits, problems = parse_rate_limits({"export": {"perMinute": 5e-324, "burst": 1}})
    assert problems == []
    rl = RateLimiter(limits=limits, clock=lambda: 0.0)
    assert rl.take("export", "ola") is None
    assert rl.take("export", "ola").retry_after == LARGEST
