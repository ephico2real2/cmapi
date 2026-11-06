"""The reader's import Secret carries the service account's ca.crt as caData (deploy/crc-reader-import.sh). That is usually a bundle of several certificates, and base64 padding may end
any of them, so the six checks must read each block by itself. Needs no database, and no certificate: the check is on the encoding, and TLS reads the file later."""
from __future__ import annotations

import base64

import pytest

from cmapi.core.registry import READER_IDENTITY, ClusterPolicy, ClusterRegistry


class Reader:
    def __init__(self, *args, **kw):
        pass

    def version(self):
        return "v1.35.0"

    def whoami(self):
        return READER_IDENTITY

    def list(self, kind, **kw):
        return {"items": []}

    def close(self):
        pass


def check(ca_data):
    policy = ClusterPolicy(cluster_id="CRC", environment="dev", gitops_path="clusters/CRC", writes=False)
    registry = ClusterRegistry({"CRC": policy}, None, client_factory=Reader, start_caches=False)
    return registry._check("CRC", {"data": {"apiUrl": "https://kubernetes.default.svc", "token": "t", "caData": ca_data}, "annotations": {}})


def pem(size):
    """A block whose base64 ends in one '=' (size % 3 == 2), two (size % 3 == 1) or none."""
    body = base64.b64encode(bytes(range(256)) * (size // 256) + bytes(range(size % 256))).decode()
    lines = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN CERTIFICATE-----\n{lines}\n-----END CERTIFICATE-----\n"


@pytest.mark.parametrize("sizes", [[1000], [1001], [1002], [1000, 1001, 1002, 1003, 1004], [1001, 1000], [1002, 1002, 1002]], ids=str)
def test_one_certificate_or_a_bundle_connects(sizes):
    st = check("".join(pem(s) for s in sizes))
    assert (st.status, st.findings) == ("connected", [])


@pytest.mark.parametrize("ca_data", [
    "not base64 at all!",
    "-----BEGIN CERTIFICATE-----\n!!!!\n-----END CERTIFICATE-----\n",
    pem(1000) + "-----BEGIN CERTIFICATE-----\nAAA=AAA\n-----END CERTIFICATE-----\n",
], ids=["no-pem", "garbage-block", "garbage-second-block"])
def test_what_is_not_base64_is_still_refused(ca_data):
    st = check(ca_data)
    assert st.status == "invalid-secret" and st.findings == ["invalid caData"]
