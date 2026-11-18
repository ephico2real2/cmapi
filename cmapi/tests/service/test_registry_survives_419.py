"""#419: one cluster's answer, or one Secret, never stops discovery, the start or the relist (docs/02 "Discovery": "A Secret
that fails becomes a finding on that cluster; it never stops the rest"). An answer the client cannot read is bad-response
(docs/02 "Client rules").

The clusters are real KubeClients over an httpx MockTransport, the chokepoint every cluster call goes through. The harness
and the first two tests are OB3's, from its review of PR #415. It lives with the service tests for their dependencies
(structlog, which the reference-code job does not install) and needs no database:

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_registry_survives_419.py -q -W ignore
"""
from __future__ import annotations

import base64
import threading
from pathlib import Path

import httpx
import pytest

from cmapi.core.clients.kube import KubeClient
from cmapi.core.registry import READER_IDENTITY, ClusterPolicy, ClusterRegistry, HubImportSource, ImportSource

TOKEN = "eyJhbGciOiJSUzI1NiJ9.reader-token-419"


def good(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if p == "/version":
        return httpx.Response(200, json={"gitVersion": "v1.35.6"})
    if p.endswith("/users/~"):
        return httpx.Response(200, json={"metadata": {"name": READER_IDENTITY}})
    if p == "/api/v1/namespaces":
        return httpx.Response(200, json={"items": [], "metadata": {"resourceVersion": "1"}})
    return httpx.Response(404)


def html_proxy(request: httpx.Request) -> httpx.Response:
    """A proxy or login page in front of the API server: 200, and not JSON."""
    return httpx.Response(200, text="<html>Sign in</html>", headers={"content-type": "text/html"})


def answering(path: str, response: httpx.Response):
    """`good`, except that `path` gets `response`."""
    def handler(request: httpx.Request) -> httpx.Response:
        return response if request.url.path == path else good(request)
    return handler


class Source(ImportSource):
    def __init__(self, secrets):
        self.secrets = secrets

    def list(self):
        return list(self.secrets)


def secret(cid: str, **data: str) -> dict:
    return {"name": f"cmapi-cluster-{cid.lower()}", "labels": {"cmapi.net/cluster-id": cid}, "annotations": {},
            "data": {"apiUrl": f"https://{cid.lower()}.example:6443", "token": TOKEN, **data}}


def registry(handlers: dict, secrets: list[dict], closed: list[str] | None = None) -> ClusterRegistry:
    def factory(cluster_id, api_url, token, ca_file, *, insecure=False):
        c = KubeClient(cluster_id, api_url, token, ca_file, insecure=insecure)
        c._client = httpx.Client(base_url=c.api_url, headers=c._client.headers, transport=httpx.MockTransport(handlers[cluster_id]))
        if closed is not None:
            close = c.close
            c.close = lambda: (closed.append(cluster_id), close())[1]
        return c
    policies = {cid: ClusterPolicy(cid, "rnd", f"clusters/{cid}") for cid in handlers}
    return ClusterRegistry(policies, Source(secrets), client_factory=factory, start_caches=False)


def test_one_unparseable_cluster_does_not_stop_the_others():
    """OB3: docs/02 "Discovery": "A Secret that fails becomes a finding on that cluster; it never stops the rest"."""
    reg = registry({"BAD": html_proxy, "GOOD": good}, [secret("BAD"), secret("GOOD")])
    reg.refresh()
    assert reg.clusters["GOOD"].status == "connected"
    assert reg.clusters["BAD"].status != "connected" and reg.clusters["BAD"].findings


def test_start_survives_an_unparseable_cluster():
    """OB3: at start the first pass runs in the caller (ClusterRegistry.start, then build_context): it must not raise."""
    reg = registry({"BAD": html_proxy}, [secret("BAD")])
    reg.relist_seconds = 3600
    try:
        reg.start()
    finally:
        reg.stop()
    assert reg.clusters["BAD"].status != "connected"


@pytest.mark.parametrize("path,response,finding", [
    ("/version", httpx.Response(200, text="<html>Sign in</html>", headers={"content-type": "text/html"}),
     "bad response on /version (200): not JSON (text/html)"),
    ("/version", httpx.Response(200, json=["v1.35.6"]), "bad response on /version (200): a JSON array, not an object"),
    ("/apis/user.openshift.io/v1/users/~", httpx.Response(200, json={"metadata": {}}),
     "identity check: bad response on /apis/user.openshift.io/v1/users/~ (200): no metadata.name"),
    ("/apis/user.openshift.io/v1/users/~", httpx.Response(200, json={"metadata": "x"}),
     "identity check: bad response on /apis/user.openshift.io/v1/users/~ (200): no metadata.name"),
    ("/apis/user.openshift.io/v1/users/~", httpx.Response(200, content=b"\xff\xfe{"),
     "identity check: bad response on /apis/user.openshift.io/v1/users/~ (200): not JSON (no content type)"),
    ("/api/v1/namespaces", httpx.Response(200, content=b'{"items": ['),
     "bad response on /api/v1/namespaces (200): not JSON (no content type)"),
    ("/api/v1/namespaces", httpx.Response(200, content=b"null"),
     "bad response on /api/v1/namespaces (200): a JSON null, not an object"),
], ids=["version-html", "version-list", "users-no-name", "users-metadata-not-object", "users-not-utf8", "namespaces-cut",
        "namespaces-null"])
def test_each_unreadable_answer_is_bad_response_and_the_next_cluster_connects(path, response, finding):
    closed: list[str] = []
    reg = registry({"BAD": answering(path, response), "GOOD": good}, [secret("BAD"), secret("GOOD")], closed)
    reg.refresh()
    assert (reg.clusters["BAD"].status, reg.clusters["BAD"].findings) == ("bad-response", [finding])
    assert reg.clusters["GOOD"].status == "connected"
    assert closed == ["BAD"]                    # the failed check's client is closed; the connected one is kept


def test_the_selfsubjectreview_fallback_without_a_username_is_bad_response():
    """Plain Kubernetes has no users/~ (404): the identity comes from a SelfSubjectReview, which must name a user."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users/~"):
            return httpx.Response(404)
        if request.url.path.endswith("/selfsubjectreviews"):
            return httpx.Response(201, json={"status": {}})
        return good(request)
    reg = registry({"K8S": handler}, [secret("K8S")])
    reg.refresh()
    assert reg.clusters["K8S"].status == "bad-response"
    assert reg.clusters["K8S"].findings == [
        "identity check: bad response on /apis/authentication.k8s.io/v1/selfsubjectreviews (201): no status.userInfo.username"]


def test_an_api_url_that_urlparse_refuses_is_a_finding():
    """urlparse raises ValueError on a malformed IPv6 host: a parse finding, and the next cluster is checked."""
    reg = registry({"V6": good, "GOOD": good}, [secret("V6", apiUrl="https://[::1:6443"), secret("GOOD")])
    reg.refresh()
    assert (reg.clusters["V6"].status, reg.clusters["V6"].findings) == ("invalid-secret", ["apiUrl is not a URL"])
    assert reg.clusters["GOOD"].status == "connected"


def test_ca_data_that_is_base64_but_no_certificate_is_invalid_ca_data():
    """`_valid_ca_data` checks the encoding only; httpx loads the trust store when the client is made, and an SSLError there
    escaped the check. The real KubeClient constructor runs here, so the file is really loaded."""
    fake = "-----BEGIN CERTIFICATE-----\naGVsbG8gd29ybGQ=\n-----END CERTIFICATE-----\n"
    reg = registry({"CA": good, "GOOD": good}, [secret("CA", caData=fake), secret("GOOD")])
    reg.refresh()
    assert reg.clusters["CA"].status == "invalid-secret"
    assert reg.clusters["CA"].findings[0].startswith("invalid caData: ")
    assert reg.clusters["GOOD"].status == "connected"


def test_a_hub_bundle_that_cannot_be_read_names_the_trust_store(tmp_path: Path):
    reg = registry({"HUB": good}, [secret("HUB")])
    reg.trusted_bundle = str(tmp_path / "missing.crt")
    reg.refresh()
    assert reg.clusters["HUB"].status == "cert-verify-failed"
    assert reg.clusters["HUB"].findings[0].endswith("; trust store: the hub bundle")


def test_a_secret_value_that_is_not_utf8_is_a_finding_on_that_cluster_only(tmp_path: Path):
    """Through the hub's own list: one Secret with a binary value made `_secret` raise, so the whole list failed and the
    previous set was kept for every cluster (a new or rotated Secret was never seen)."""
    def b64(s: str | bytes) -> str:
        return base64.b64encode(s if isinstance(s, bytes) else s.encode()).decode()

    def k8s_secret(cid: str, token: str | bytes) -> dict:
        return {"metadata": {"name": f"cmapi-cluster-{cid.lower()}", "labels": {"cmapi.net/cluster-id": cid}},
                "data": {"apiUrl": b64(f"https://{cid.lower()}.example:6443"), "token": b64(token)}}

    def hub(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [k8s_secret("BIN", b"\xff\xfe binary"), k8s_secret("GOOD", TOKEN)]})

    (tmp_path / "token").write_text("hub-token")
    source = HubImportSource("https://hub.example:6443", tmp_path / "token", tmp_path / "no-ca.crt", "cmapi-imports")
    source.client = httpx.Client(base_url="https://hub.example:6443", transport=httpx.MockTransport(hub))
    reg = registry({"BIN": good, "GOOD": good}, [])
    reg.source = source
    reg.refresh()
    assert (reg.clusters["BIN"].status, reg.clusters["BIN"].findings) == ("invalid-secret", ["field token is not base64 of UTF-8 text"])
    assert reg.clusters["GOOD"].status == "connected"


def test_an_unforeseen_fault_of_one_check_is_a_finding_and_the_rest_are_checked():
    """The net in `refresh`: a fault `_check` does not classify (here a cache factory that raises) is a finding."""
    reg = registry({"ODD": good, "GOOD": good}, [secret("ODD"), secret("GOOD")])

    def nodes_factory(st, client):
        if st.cluster_id == "ODD":
            raise RuntimeError("node cache could not be made")
        return None
    reg.nodes_factory = nodes_factory
    reg.refresh()
    assert reg.clusters["ODD"].status == "unreachable"
    assert reg.clusters["ODD"].findings == ["the check failed: RuntimeError: node cache could not be made"]
    assert reg.clusters["GOOD"].status == "connected"


def test_the_relist_thread_survives_a_pass_that_raises():
    """The relist thread runs `refresh` every `relist_seconds`; a pass that raises must not end it."""
    reg = registry({"GOOD": good}, [secret("GOOD")])
    passes, third = [], threading.Event()
    refresh = reg.refresh

    def flaky_refresh():
        passes.append(1)
        if len(passes) == 3:
            third.set()
        if len(passes) == 2:
            raise RuntimeError("one pass fails")
        refresh()
    reg.refresh = flaky_refresh
    reg.relist_seconds = 0.01
    try:
        reg.start()                         # pass 1, in the caller
        assert third.wait(5), f"the relist stopped after {len(passes)} passes"
    finally:
        reg.stop()
    assert reg.clusters["GOOD"].status == "connected"


# ---- OB3, review of PR #422


def test_a_check_that_fails_after_the_probe_closes_its_client():
    """docs/02 "Discovery": "A failed check closes its client". The net in `refresh` catches a fault after the probe (a cache
    factory that raises); the client the check made must be closed there too, not left to the garbage collector."""
    closed: list[str] = []
    reg = registry({"ODD": good, "GOOD": good}, [secret("ODD"), secret("GOOD")], closed)

    def nodes_factory(st, client):
        if st.cluster_id == "ODD":
            raise RuntimeError("node cache could not be made")
        return None
    reg.nodes_factory = nodes_factory
    reg.refresh()
    assert reg.clusters["ODD"].status == "unreachable" and reg.clusters["ODD"].client is None
    assert closed == ["ODD"]
    assert reg.clusters["GOOD"].status == "connected"


def test_a_json_nested_past_the_recursion_limit_is_bad_response():
    """json.loads raises RecursionError, which is no ValueError: the answer is unreadable, so it is bad-response, not the
    net's `unreachable`."""
    deep = b"[" * 100_000 + b"]" * 100_000
    reg = registry({"BAD": answering("/version", httpx.Response(200, content=deep)), "GOOD": good}, [secret("BAD"), secret("GOOD")])
    reg.refresh()
    assert (reg.clusters["BAD"].status, reg.clusters["BAD"].findings) == (
        "bad-response", ["bad response on /version (200): not JSON (no content type)"])
    assert reg.clusters["GOOD"].status == "connected"


@pytest.mark.parametrize("token", ["eyJhbGciOiJSUzI1NiJ9.reader-token-419\n", "eyJhbGciOiJSUzI1NiJ9.reader tok",
                                   "eyJhbGciOiJSUzI1NiJ9.réader-token"], ids=["trailing-newline", "inner-space", "non-ascii"])
def test_a_token_no_http_header_can_carry_is_a_parse_finding(token):
    """`kubectl create token` ends its output with a newline, and `--from-file` keeps it: h11 refuses the header and the
    cluster read `unreachable`; a non-ASCII token raised in the client's constructor and fell to the net. Both are the
    Secret's fault: invalid-secret, and no client is made."""
    made: list[str] = []
    reg = registry({"TOK": good, "GOOD": good}, [secret("TOK", token=token), secret("GOOD")])
    factory = reg.client_factory
    reg.client_factory = lambda cid, *a, **k: (made.append(cid), factory(cid, *a, **k))[1]
    reg.refresh()
    assert (reg.clusters["TOK"].status, reg.clusters["TOK"].findings) == (
        "invalid-secret", ["token has whitespace or a character an HTTP header cannot carry"])
    assert made == ["GOOD"] and reg.clusters["GOOD"].status == "connected"


@pytest.mark.parametrize("field,value", [("labels", "x"), ("labels", {"cmapi.net/cluster-id": ["A", "B"]}),
                                         ("annotations", "x")], ids=["labels-text", "cluster-id-list", "annotations-text"])
def test_a_secret_with_a_malformed_metadata_field_never_stops_the_pass(tmp_path: Path, field, value):
    """CMAPI_IMPORTS_DIR reads YAML that no API server validated: labels or annotations that are not a mapping raised out of
    `refresh` (outside the per-cluster net) and stopped the start."""
    import yaml
    from cmapi.core.registry import DirImportSource
    bad = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "cmapi-cluster-bad", "labels": {"cmapi.net/cluster-id": "BAD"}},
           "stringData": {"apiUrl": "https://bad.example:6443", "token": TOKEN}}
    bad["metadata"][field] = value
    ok = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "cmapi-cluster-good", "labels": {"cmapi.net/cluster-id": "GOOD"}},
          "stringData": {"apiUrl": "https://good.example:6443", "token": TOKEN}}
    (tmp_path / "s.yaml").write_text(yaml.safe_dump_all([bad, ok]))
    reg = registry({"BAD": good, "GOOD": good}, [])
    reg.source = DirImportSource(tmp_path)
    reg.relist_seconds = 3600
    try:
        reg.start()
    finally:
        reg.stop()
    assert reg.clusters["GOOD"].status == "connected"
