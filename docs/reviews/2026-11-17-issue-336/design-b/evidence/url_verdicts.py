"""The validator's verdict on candidate URL values of company.net/mnemonic-confluence (format url)."""
import json, sys
from pathlib import Path
import cmapi.core.metadata as m
keys = m.MetadataKeys.load(Path(sys.argv[1]) / "examples/cluster-configs/policies/metadata-keys.company.yaml")
values = ["https://wiki.company.net/abc", "https://a%zz/", "https://ex_ample.com/", "https://a..b/", "https://-x-/", "https://x:abc/",
          "https://x:99999/", "http://x", "https://x y/", "https://[::1]/", "https://[::1", "https://x/%zz", "https://ü.example/", "ftp://x"]
out = {v: not keys.validate({}, {"company.net/mnemonic-confluence": v}, operator=False, require_governed=False) for v in values}
(Path(__file__).parent / "url_verdicts.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
