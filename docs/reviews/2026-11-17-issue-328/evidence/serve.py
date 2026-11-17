"""Local run for the #328 screenshots only: the cmapi API on the service suite's fakes (PostgreSQL on 55432), with the
pinned Swagger UI 5.34.1 bundle, on one metadata-keys.yaml. Usage: serve.py <reference|company> <port>"""
import os, shutil, sys, tempfile
from pathlib import Path
os.environ["CMAPI_STATIC_DIR"] = str(Path(__file__).parent / "static")
sys.path[:0] = [str(Path(__file__).parent.parent / "wt-328/cmapi/tests/service"), str(Path(__file__).parent.parent / "wt-328/cmapi/src")]
import pytest, uvicorn, yaml
import conftest
from conftest import EXAMPLES, Keys, build_world

name, port = sys.argv[1], int(sys.argv[2])
d = Path(tempfile.mkdtemp()) / "config"
d.mkdir()
for f in ("instance.yaml", "approval-rules.yaml", "authz-roles.yaml", "tiers.yaml", "expiration.yaml"):
    (d / f).write_text((EXAMPLES / "instances" / "nonprod" / f).read_text())
src = {"reference": "metadata-keys.yaml", "company": "metadata-keys.company.yaml"}[name]
shutil.copy(EXAMPLES / "cluster-configs/policies" / src, d / "metadata-keys.yaml")
inst = yaml.safe_load((d / "instance.yaml").read_text().replace("https://sso.ephico2real.com/realms/ephico2real", conftest.ISSUER))
inst["instance"]["policy"] = {"engine": "none"}
inst["instance"]["publicUrl"] = f"http://127.0.0.1:{port}"
(d / "instance.yaml").write_text(yaml.safe_dump(inst))
(d / "clusters.yaml").write_text("clusters:\n  CRC:\n    environment: dev\n    gitopsPath: clusters/CRC\n    simulatedCapacity: {cpu: 64, memory: 256Gi}\n")
(d / "capacity.yaml").write_text("overcommit:\n  dev: {cpu: 2.0, memory: 1.25}\n")
(d / "integrations.yaml").write_text("delivery:\n  mode: apply\n  syncTimeout: 30s\nsyncSignal:\n  default: poll\n  pollInterval: 1s\n")
mp = pytest.MonkeyPatch()
with build_world(d, Keys(), mp) as (client, ctx, *_):
    uvicorn.run(client.app, host="127.0.0.1", port=port, log_level="warning")
