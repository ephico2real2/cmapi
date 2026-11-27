"""#531. CRC's own dev bundle is pinned, so a change to the renderer or to CRC's configuration fails in its own pull request.

CRC runs the bundle merged in cmapi-cluster-configs `policies/env/dev/`; the Policies tab holds CRC to the bundle that the running
cmapi renders from CRC's configuration. test_bundle_hash_244 pins the example bundle only, so #499 changed CRC's render with no
failing test and no bundle pull request, and the deploy would have read CRC off the bundle (`hashState: drift`)."""
from cmapi.core.policybundle import PolicyBundle
from cmapi.tools.policies import _render
from conftest import crc_config_dir

# policybundle.git_hash over policies/env/dev/ of cmapi-cluster-configs PR #31 (e8c244c, the render for #746: the label policies
# allow the opt-in label). Before it: a2603db2... of 5926fa2 (PR #21, the render at cmapi a909074).
CRC_DEV_HASH = "cfd8fa167a62afb487a3011c9b9cf3efc024c6720bb24f53779caf78d03a3512"


def test_crcs_dev_bundle_is_the_one_merged_in_cmapi_cluster_configs(tmp_path):
    config = crc_config_dir(tmp_path)
    rendered, _ = _render(config, config / "metadata-keys.yaml")
    got = PolicyBundle(rendered).rendered_hash("dev")
    assert got == CRC_DEV_HASH, (
        f"CRC's dev bundle changed: the render gives {got}, cmapi-cluster-configs holds {CRC_DEV_HASH}. Follow docs/13, "
        "\"cmapi's policy bundle on CRC\": re-render policies/env/ with `cmapi-tools policies render` from CRC's 20-config.yaml, "
        "open and merge the cmapi-cluster-configs pull request, apply it after step 21 of the deploy, and pin the merged "
        "bundle's git_hash here.")
