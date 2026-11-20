import pytest
from cmapi.plugins.expiration.rules import ExpirationRules


@pytest.mark.parametrize("envs", [{}, {"prod": {"enabled": False}}])
def test_defaults_enabled_is_checked_even_when_no_environment_inherits_it(envs):
    with pytest.raises(ValueError, match="enabled is true or false"):
        ExpirationRules({"defaults": {"enabled": "false"}, "environments": envs})
