"""Exercise the CRC import with synthetic credentials and no Kubernetes connection."""
import base64
import datetime
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CA = "-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n"
REQUEST = ["create", "token", "cmapi-reader", "-n", "cmapi-system", "--duration=168h"]
OLD_SECRET = ["get", "secret", "cmapi-reader-token", "-n", "cmapi-system", "-o", "json"]
STUB = r"""#!/usr/bin/env python3
import base64, json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open("calls", "a") as log:
    print(json.dumps(args), file=log)
if args[:2] == ["create", "token"]:
    print(os.environ["ISSUED_TOKEN"])
    if os.environ.get("CLIENT_DIAGNOSTICS"):
        print(os.environ["ISSUED_TOKEN"], file=sys.stderr)
    if os.environ.get("ISSUER_EXIT"):
        sys.exit(1)
elif args == ["get", "configmap", "kube-root-ca.crt", "-n", "cmapi-system", "-o", r"jsonpath={.data.ca\.crt}"]:
    print(os.environ["ISSUER_CA"], end="")
elif args == ["get", "secret", "cmapi-reader-token", "-n", "cmapi-system", "-o", "json"]:
    print(json.dumps({"data": {"token": "bGVnYWN5", "ca.crt": "Y2E="}}))
elif args[0] == "apply" and args[-2:] == ["-f", "-"]:
    document = json.load(sys.stdin)
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


def import_crc(work, issued_at, lifetime=24 * 3600):
    for name in ("oc", "kubectl"):
        client = work / name
        client.write_text(STUB)
        client.chmod(0o755)
    token = fixture_token(issued_at, lifetime)
    env = dict(os.environ, PATH=f"{work}:{os.environ['PATH']}", CMAPI_OC="oc", KUBECONFIG=os.devnull,
               ISSUED_TOKEN=token, ISSUER_CA=CA)
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
    assert [args[0] for args in calls] == ["get", "create"]
