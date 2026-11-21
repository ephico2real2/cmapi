"""#501: clusterTokens.duration stays within the API server's TokenRequest limit.

kubernetes/kubernetes pkg/apis/authentication/validation/validation.go (read 2026-11-21) refuses
`exp > 1<<32` with "may not specify a duration larger than 2^32 seconds", so 2^32 itself is allowed.
"""
import pytest

from cmapi.core.cluster_tokens import TokenPolicy


@pytest.mark.parametrize("duration", ["49710d", f"{2**32}s"])
def test_a_duration_up_to_two_to_the_32_seconds_is_accepted(duration):
    assert TokenPolicy().override({"duration": duration}).duration <= 2**32


@pytest.mark.parametrize("duration", [f"{2**32 + 1}s", "50000d"])
def test_a_duration_above_two_to_the_32_seconds_is_refused_at_load(duration):
    with pytest.raises(ValueError, match=r"2\^32 seconds"):
        TokenPolicy().override({"duration": duration})
