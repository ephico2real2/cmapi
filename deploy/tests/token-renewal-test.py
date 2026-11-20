#!/usr/bin/env python3
"""Compare the worker policy and the script's printed deadline using one named case table (stdlib only)."""
import base64
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cmapi/src"))
from cmapi.core.cluster_tokens import ReaderGrant, READER_IDENTITY, TokenPolicy


def main():
    ca_file = sys.argv[1]
    cases = json.loads((ROOT / "deploy/tests/token-renewal-cases.json").read_text())
    for case in cases:
        values = case["values"]
        env = {k: v for k, v in os.environ.items() if not k.startswith("CMAPI_TOKEN_")}
        for key, variable in (("duration", "CMAPI_TOKEN_DURATION"), ("renewBefore", "CMAPI_TOKEN_RENEW_BEFORE"),
                              ("renewBeforePercentage", "CMAPI_TOKEN_RENEW_BEFORE_PERCENTAGE")):
            if key in values:
                env[variable] = str(values[key])
        issued = int(time.time())
        expires = issued + case["lifetime"]
        payload = json.dumps({"sub": READER_IDENTITY, "iat": issued, "exp": expires}).encode()
        token = "stub." + base64.urlsafe_b64encode(payload).decode().rstrip("=") + ".synthetic"
        if "error" in case:
            try:
                TokenPolicy().override(values)
            except ValueError as exc:
                assert case["error"] in str(exc), case["name"]
            else:
                raise AssertionError(case["name"] + ": worker accepted invalid policy")
            # Validation must refuse before reading stdin, requesting a token or writing a Secret.
            args = ["--request-duration"]
        else:
            policy = TokenPolicy().override(values)
            deadline = ReaderGrant(issued, expires).renewal_time(policy)
            assert math.isclose(deadline - issued, case["deadline"], abs_tol=0.000001), case["name"]
            args = ["TEST", "https://reader.invalid", ca_file]
        result = subprocess.run([sys.executable, str(ROOT / "deploy/kind-import/import-secret.py"), *args],
                                input=token, text=True, capture_output=True, env=env)
        if "error" in case:
            assert result.returncode != 0 and not result.stdout, case["name"]
            assert case["error"] in result.stderr, case["name"]
        else:
            assert result.returncode == 0, case["name"] + ": " + result.stderr
            printed = datetime.fromtimestamp(deadline, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            assert result.stderr.endswith("automatic renewal due " + printed + "\n"), case["name"]
            assert json.loads(result.stdout)["kind"] == "Secret", case["name"]
        print("  ok   renewal rule: " + case["name"])


if __name__ == "__main__":
    main()
