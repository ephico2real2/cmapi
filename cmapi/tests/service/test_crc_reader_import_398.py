"""Exercise the CRC import with synthetic credentials and no Kubernetes connection."""
import base64
import datetime
import json
import os
import runpy
import subprocess
import time
from contextlib import nullcontext
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
# Public certificate from a synthetic test CA.
CA = """-----BEGIN CERTIFICATE-----
MIIBjTCCATOgAwIBAgIUL0sbduezC+DyIOOOpW8qbtyK/WUwCgYIKoZIzj0EAwIw
HDEaMBgGA1UEAwwRSXNzdWUgMzk4IHRlc3QgQ0EwHhcNMjYxMTE5MjM0MjQzWhcN
MzYxMTE2MjM0MjQzWjAcMRowGAYDVQQDDBFJc3N1ZSAzOTggdGVzdCBDQTBZMBMG
ByqGSM49AgEGCCqGSM49AwEHA0IABEH/hoLKDMvW51q87TeoaY3zMR6Bj+Hu9JM/
DW5S9GktNtu95foo5zyB6rxsZhqDfITHCBrH1E94xbZSr/z+YuqjUzBRMB0GA1Ud
DgQWBBTkiNsQUVPs0VHMH/25TIMWARtMozAfBgNVHSMEGDAWgBTkiNsQUVPs0VHM
H/25TIMWARtMozAPBgNVHRMBAf8EBTADAQH/MAoGCCqGSM49BAMCA0gAMEUCIDKI
EvCTujdUDPf0V+AWg/aLYVty8/45mhdSJbwF0MFNAiEAmbASRW7wAjOYm9urKl98
hXPEcpNnW9sacEtIjX4sLN0=
-----END CERTIFICATE-----
"""
REQUEST = ["create", "token", "cmapi-reader", "-n", "cmapi-system", "--duration=168h"]
OLD_SECRET = ["get", "secret", "cmapi-reader-token", "-n", "cmapi-system", "-o", "json"]
STUB = r"""#!/usr/bin/env python3
import base64, json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open("calls", "a") as log:
    print(json.dumps(args), file=log)
version = Path("version")
if args[:3] == ["get", "secret", "cmapi-cluster-crc"]:
    assert args[3:] == ["-n", "cmapi-imports", "--ignore-not-found", "-o", "jsonpath={.metadata.resourceVersion}"]
    print(version.read_text() if version.exists() else os.environ.get("INITIAL_VERSION", "1"))
elif args[:2] == ["create", "token"]:
    if os.environ.get("WORKER_WINS"):
        version.write_text("2")
        Path("applied").write_text('{"winner":"concurrent"}')
    print(os.environ["ISSUED_TOKEN"])
    if os.environ.get("CLIENT_DIAGNOSTICS"):
        print(os.environ["ISSUED_TOKEN"], file=sys.stderr)
    if os.environ.get("ISSUER_EXIT"):
        sys.exit(1)
elif args == ["get", "configmap", "kube-root-ca.crt", "-n", "cmapi-system", "-o", r"jsonpath={.data.ca\.crt}"]:
    print(os.environ["ISSUER_CA"], end="")
elif args == ["get", "secret", "cmapi-reader-token", "-n", "cmapi-system", "-o", "json"]:
    print(json.dumps({"data": {"token": "bGVnYWN5", "ca.crt": "Y2E="}}))
elif args[0] in ("apply", "create") and args[-2:] == ["-f", "-"]:
    document = json.load(sys.stdin)
    current = version.read_text() if version.exists() else os.environ.get("INITIAL_VERSION", "1")
    observed = document["metadata"].get("resourceVersion")
    if (args[0] == "create" and current) or (observed is not None and observed != current):
        sys.exit(1)
    if any(document["data"]["token"] in arg for arg in [*args, *os.environ.values()]):
        sys.exit("encoded credential in client argv or environment")
    if os.environ.get("CLIENT_DIAGNOSTICS"):
        print(document["data"]["token"], file=sys.stderr)
        if os.environ["CLIENT_DIAGNOSTICS"] == "reject":
            sys.exit(1)
    Path("applied").write_text(json.dumps(document))
else:
    sys.exit("unexpected client call: " + repr(args))
"""


def fixture_token(issued_at, lifetime):
    claims = {"sub": "system:serviceaccount:cmapi-system:cmapi-reader", "iat": issued_at, "exp": issued_at + lifetime}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"stub.{payload}.stub"


def import_crc(work, issued_at, lifetime=24 * 3600, ca=CA):
    for name in ("oc", "kubectl"):
        client = work / name
        client.write_text(STUB)
        client.chmod(0o755)
    token = fixture_token(issued_at, lifetime)
    env = dict(os.environ, PATH=f"{work}:{os.environ['PATH']}", CMAPI_OC="oc", KUBECONFIG=os.devnull,
               ISSUED_TOKEN=token, ISSUER_CA=ca)
    result = subprocess.run([ROOT / "deploy/crc-reader-import.sh"], cwd=work, env=env,
                            check=True, capture_output=True, text=True, timeout=10)
    assert token not in result.stdout + result.stderr + (work / "calls").read_text()
    return json.loads((work / "applied").read_text()), token, result.stderr


def test_requests_and_renews_the_reader_token(tmp_path):
    now = int(time.time())
    for issued_at in (now - 1, now):
        (tmp_path / "calls").write_text("")
        secret, token, _ = import_crc(tmp_path, issued_at)
        calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
        assert OLD_SECRET not in calls, calls
        assert calls.count(REQUEST) == 1, calls
        [apply] = [args for args in calls if args[0] == "apply"]
        assert {"--server-side", "--field-manager=crc-reader-import.sh", "--force-conflicts"} <= set(apply)
        assert secret["metadata"]["name"] == "cmapi-cluster-crc"
        assert secret["metadata"]["namespace"] == "cmapi-imports"
        assert secret["metadata"]["labels"] == {"cmapi.net/secret-type": "cluster", "cmapi.net/cluster-id": "CRC",
                                                "app.kubernetes.io/part-of": "cmapi"}
        data = {key: base64.b64decode(value).decode() for key, value in secret["data"].items()}
        assert data["token"] == token
        assert data["apiUrl"] == "https://kubernetes.default.svc"
        assert data["caData"] == CA


def test_records_granted_expiry_and_prints_renewal_deadline(tmp_path):
    issued_at = int(time.time())
    lifetime = 24 * 3600  # The API can grant less than the requested seven days.
    secret, _, message = import_crc(tmp_path, issued_at, lifetime)
    annotations = secret["metadata"].get("annotations", {})
    assert annotations.get("cmapi.net/managed-by") == "cluster-baseline", annotations

    def utc(seconds):
        return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert annotations["cmapi.net/token-expires-at"] == utc(issued_at + lifetime)
    assert utc(issued_at + lifetime * 0.8) in message


def test_server_grant_over_seven_days_leaves_existing_import_intact(tmp_path):
    issued_at = int(time.time())
    previous, _, _ = import_crc(tmp_path, issued_at)
    with pytest.raises(subprocess.CalledProcessError):
        import_crc(tmp_path, issued_at, lifetime=7 * 24 * 3600 + 1)
    assert json.loads((tmp_path / "applied").read_text()) == previous

@pytest.mark.parametrize("outcome", ["accept", "reject"])
def test_sensitive_client_diagnostics_are_private(tmp_path, monkeypatch, outcome):
    stage = tmp_path / "tmp"
    stage.mkdir()
    monkeypatch.setenv("TMPDIR", str(stage))
    monkeypatch.setenv("CLIENT_DIAGNOSTICS", outcome)
    monkeypatch.setenv("SHELLOPTS", "allexport:xtrace")
    monkeypatch.setenv("import_document", "inherited")
    now = int(time.time())
    if outcome == "reject":
        with pytest.raises(subprocess.CalledProcessError) as exc:
            import_crc(tmp_path, now)
        output = exc.value.stdout + exc.value.stderr
        assert "apply" in output.lower()
    else:
        _, _, output = import_crc(tmp_path, now)
    token = fixture_token(now, 24 * 3600)
    assert token not in output
    assert base64.b64encode(token.encode()).decode() not in output
    assert list(stage.iterdir()) == []

def test_issuer_must_exit_successfully_before_any_apply(tmp_path, monkeypatch):
    now = int(time.time())
    previous, _, _ = import_crc(tmp_path, now - 10)
    (tmp_path / "calls").write_text("")
    monkeypatch.setenv("ISSUER_EXIT", "1")
    with pytest.raises(subprocess.CalledProcessError):
        import_crc(tmp_path, now)
    assert json.loads((tmp_path / "applied").read_text()) == previous
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    assert [args[0] for args in calls] == ["get", "get", "create"]

def test_kind_proof_bootstraps_its_reader_from_the_current_manifest(tmp_path, monkeypatch):
    proof = ROOT / "docs/reviews/2026-11-17-issue-302-policies/evidence/kind/test_kind_proof_302.py"
    run_proof = runpy.run_path(str(proof))["test_kind_proof"]
    token = fixture_token(int(time.time()), 3600)
    manifest = ROOT / "deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml"
    calls = []

    def kubectl(*args):
        calls.append(args)
        if args == ("apply", "--server-side", "-f", str(manifest)):
            return ""
        if list(args) == REQUEST:
            return token + "\n"
        pytest.fail(f"unexpected kind bootstrap call {args}")

    class BootstrapComplete(Exception):
        pass

    def check_import():
        assert registry.source.list()[0]["data"]["token"] == token
        raise BootstrapComplete

    registry = SimpleNamespace(refresh=check_import, _fingerprints={}, clusters={"CRC": SimpleNamespace()})
    (tmp_path / "kubeconfig").write_text(json.dumps({"clusters": [{"cluster": {
        "server": "https://test.invalid", "certificate-authority-data": "Y2E="}}]}))
    world = (None, SimpleNamespace(registry=registry), None, None, None, None)
    for name, value in {"WT": ROOT, "HERE": tmp_path, "kubectl": kubectl,
                        "build_world": lambda *args: nullcontext(world)}.items():
        monkeypatch.setitem(run_proof.__globals__, name, value)
    with pytest.raises(BootstrapComplete):
        run_proof(None, None, None, monkeypatch)
    assert len(calls) == 2

@pytest.mark.parametrize("age", [3000, 3601], ids=["past-renewal", "expired"])
def test_stale_grant_leaves_the_previous_import_in_place(tmp_path, age):
    now = int(time.time())
    previous, _, _ = import_crc(tmp_path, now - 10)
    (tmp_path / "calls").write_text("")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        import_crc(tmp_path, now - age, lifetime=3600)
    assert "renewal deadline" in failure.value.stderr
    assert json.loads((tmp_path / "applied").read_text()) == previous
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    assert [args[0] for args in calls] == ["get", "get", "create"]

def test_malformed_ca_cannot_replace_a_working_import(tmp_path):
    now = int(time.time())
    previous, _, _ = import_crc(tmp_path, now - 10)
    (tmp_path / "calls").write_text("")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        import_crc(tmp_path, now, ca="-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n")
    assert "CA" in failure.value.stderr
    assert json.loads((tmp_path / "applied").read_text()) == previous
    assert all(json.loads(line)[0] != "apply" for line in (tmp_path / "calls").read_text().splitlines())


@pytest.mark.parametrize("initial", ["1", ""], ids=["update", "first-import"])
def test_manual_import_cannot_overwrite_a_concurrent_winner(tmp_path, monkeypatch, initial):
    monkeypatch.setenv("INITIAL_VERSION", initial)
    monkeypatch.setenv("WORKER_WINS", "1")
    with pytest.raises(subprocess.CalledProcessError):
        import_crc(tmp_path, int(time.time()))
    assert json.loads((tmp_path / "applied").read_text()) == {"winner": "concurrent"}


def test_first_import_creates_with_the_bootstrap_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_VERSION", "")
    secret, _, _ = import_crc(tmp_path, int(time.time()))
    assert "resourceVersion" not in secret["metadata"]
    calls = [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
    assert calls[-1] == ["create", "--field-manager=crc-reader-import.sh", "-f", "-"]


def test_bootstrap_accepts_short_grant_with_long_absolute_window(tmp_path, monkeypatch):
    monkeypatch.setenv("CMAPI_TOKEN_DURATION", "7d")
    monkeypatch.setenv("CMAPI_TOKEN_RENEW_BEFORE", "24h")
    now = int(time.time())
    secret, _, diagnostic = import_crc(tmp_path, now, lifetime=3600)
    assert secret["metadata"]["annotations"]["cmapi.net/token-expires-at"] in diagnostic
