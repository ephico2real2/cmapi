"""Review of #505 (Fable), finding 1: CRC's metadata-keys.yaml is the design's section 3.1 but for the owner's CRC decisions
(section 8). test_crc_policy_files_are_the_kind_files pinned this file to kind's until #505; this pins it to the design."""
from pathlib import Path

import yaml

from test_plain_manifests import config_file

DESIGN = Path(__file__).resolve().parents[3] / "docs/reviews/2026-11-20-issue-479/namespace_metadata.md"
DOMAIN = "ephico2real.com"


def test_crc_metadata_keys_are_the_designs_section_3_1_with_crcs_email_domain():
    section = DESIGN.read_text().split("### 3.1", 1)[1].split("### 3.2", 1)[0]
    design = yaml.safe_load(section.split("```yaml\n", 1)[1].split("```", 1)[0])["metadata"]
    design["emailDomains"] = [DOMAIN]                                                    # decision 1
    design["requiredAnnotations"]["cmapi.net/team-dl"]["example"] = f"payments-team@{DOMAIN}"
    crc = yaml.safe_load(config_file("crc", "metadata-keys.yaml"))
    assert crc == design
    assert "company.net/cl" in crc["sensitiveKeys"]                                      # decision 4
    names = [key for kind in ("requiredLabels", "requiredAnnotations") for key, rule in crc[kind].items()
             if rule.get("namespacePrefix") or rule.get("namespaceSuffix")]
    assert names == ["company.net/app-environment", "company.net/mnemonic"]              # decision 2: no CRC variant
