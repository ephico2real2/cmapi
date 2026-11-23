"""#591: caData with a line that is not ASCII, such as an issuer's name above the certificate, ended `unreachable` with
"the check failed: TypeError".

Python's ssl (https://docs.python.org/3.12/library/ssl.html, read 2026-11-23): "The cadata object, if present, is either an
ASCII string of one or more PEM-encoded certificates or a bytes-like object of DER-encoded certificates." CPython 3.12
(Modules/_ssl.c, load_verify_locations) encodes a str with PyUnicode_AsASCIIString and raises that TypeError when it cannot.
RFC 7468 (https://www.rfc-editor.org/rfc/rfc7468.html, read 2026-11-23), section 2: "Data before the encapsulation
boundaries are permitted, and parsers MUST NOT malfunction when processing such data"; section 5.2: "Many tools are known to
emit explanatory text before the BEGIN and after the END lines". OpenSSL and Go's x509.CertPool (client-go's) load such a
value, and curl's Mozilla bundle has a title in UTF-8 (measured, recorded on the pull request). So the check loads it; a
character that is not ASCII inside a block, CERTIFICATE or X509 CERTIFICATE, is still refused as `invalid caData`.

Each case goes through `ClusterRegistry._check_import` with a client factory that calls `Trust.verify()`, the real loader.
"""
from __future__ import annotations

import pytest

from test_crc_reader_import_398 import CA            # a real certificate, of a synthetic CA
from test_registry_ca_bundle import Reader

BEGIN, END = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"


def _check_import(ca_data: str) -> tuple[str, list[str], int | None]:
    """The status, the findings, and how many certificates the loader put in the context (None when none was made)."""
    from cmapi.core.registry import ClusterPolicy, ClusterRegistry

    loaded: list[int] = []

    def client(cluster_id, api_url, token, trust, insecure=False):
        loaded.append(trust.verify().cert_store_stats()["x509"])
        return Reader()

    policy = ClusterPolicy(cluster_id="CRC", environment="dev", gitops_path="clusters/CRC", writes=False)
    registry = ClusterRegistry({"CRC": policy}, None, client_factory=client, start_caches=False)
    secret = {"name": "crc-import", "data": {"apiUrl": "https://kubernetes.default.svc", "token": "t", "caData": ca_data},
              "annotations": {}}
    registry._check_import(registry.get("CRC"), [secret])
    st = registry.get("CRC")
    return st.status, st.findings, loaded[0] if loaded else None


@pytest.mark.parametrize("ca_data", [
    "# Issuer: CN=Zürich Root CA\n" + CA,
    CA + "# Ausgestellt für Zürich\n",
    ("# Issuer: CN=Zürich Root CA\n" + CA).replace("\n", "\r\n"),
    # The shape of curl's cacert.pem (https://curl.se/ca/cacert.pem, 2026-11-05 edition, line 41): a title, then a rule.
    "NetLock Arany (Class Gold) Főtanúsítvány\n========================================\n" + CA,
    CA + "Zürich\n" + CA,
], ids=["comment-before", "comment-after", "crlf", "curl-bundle-title", "between-two-blocks"])
def test_explanatory_text_that_is_not_ascii_connects(ca_data):
    """The certificate loads and the text beside it is skipped, as OpenSSL and client-go do."""
    status, findings, loaded = _check_import(ca_data)
    assert (status, findings) == ("connected", [])
    assert loaded == 1


def _second_ca() -> str:
    """Another self-signed CA, so that a count of two proves both blocks were loaded."""
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Issue 591 second CA")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_an_x509_certificate_block_beside_such_text_still_loads():
    """OpenSSL's PEM_read_bio_X509 also reads the older label `X509 CERTIFICATE` (check_pem, PEM_STRING_X509_OLD), and loads
    it today beside a CERTIFICATE block. Text that is not ASCII outside both blocks is skipped, so both CAs are anchors."""
    old_label = _second_ca().replace("BEGIN CERTIFICATE", "BEGIN X509 CERTIFICATE").replace("END CERTIFICATE",
                                                                                              "END X509 CERTIFICATE")
    assert _check_import(CA + "# Issuer: CN=Zürich Root CA\n" + old_label) == ("connected", [], 2)


@pytest.mark.parametrize("inside", [" ", " ", "　"], ids=["nbsp", "line-separator", "ideographic-space"])
def test_a_character_that_is_not_ascii_inside_a_block_is_invalid_ca_data(inside):
    """Inside a block it is no base64 (RFC 7468 section 3 is US-ASCII). str.split() took these for whitespace, so the check
    passed them and the loader raised TypeError: now the Secret is refused, before any client is made."""
    lines = CA.split("\n")
    lines[2] = lines[2][:10] + inside + lines[2][10:]
    assert _check_import("\n".join(lines)) == ("invalid-secret", ["invalid caData"], None)


def test_two_distinct_certificates_beside_such_text_are_both_anchors():
    """Two different CAs, so a loader that kept one block of two would count one."""
    assert _check_import(CA + "# Zürich\n" + _second_ca()) == ("connected", [], 2)


def _inside(cert: str, where: str) -> str:
    """`cert` with text that is not ASCII in its body: a line of it, a mixed line, or the end of a base64 line."""
    lines = cert.split("\n")
    if where == "own-line":
        lines.insert(2, "\u00a0")
    elif where == "mixed-line":
        lines.insert(2, "Issuer: Zürich")
    else:
        lines[2] += "\u00a0"
    return "\n".join(lines)


@pytest.mark.parametrize("where", ["own-line", "mixed-line", "end-of-line"])
@pytest.mark.parametrize("label", ["CERTIFICATE", "X509 CERTIFICATE"])
def test_text_that_is_not_ascii_inside_either_label_is_never_repaired(label, where):
    """Beside one good CERTIFICATE block, a second CA, under either label the loader takes, with text that is not ASCII in its
    body. Leaving that line out loaded a certificate that OpenSSL refuses from the same file, and the import said connected
    (#599, reviewer 1). The import is now invalid caData, and the loader by itself never makes the second CA an anchor."""
    import ssl

    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    from cmapi.core.clients.trust import ca_data_context

    second = _second_ca()
    bundle = CA + _inside(second.replace(" CERTIFICATE-----", f" {label}-----"), where)
    assert _check_import(bundle) == ("invalid-secret", ["invalid caData"], None)
    try:
        anchors = ca_data_context(bundle).get_ca_certs(binary_form=True)
    except ssl.SSLError:
        anchors = []
    assert x509.load_pem_x509_certificate(second.encode()).public_bytes(Encoding.DER) not in anchors


@pytest.mark.parametrize("begin, end", [("CERTIFICATE", "X509 CERTIFICATE"), ("X509 CERTIFICATE", "CERTIFICATE")])
def test_a_block_closed_by_the_other_label_is_invalid_ca_data(begin, end):
    """OpenSSL needs the END line of the block's own label (pem_lib.c, get_header_and_data: PEM_R_BAD_END_LINE)."""
    second = _second_ca().replace("BEGIN CERTIFICATE", f"BEGIN {begin}").replace("END CERTIFICATE", f"END {end}")
    assert _check_import(CA + second) == ("invalid-secret", ["invalid caData"], None)


def test_bare_base64_with_a_no_break_space_is_invalid_ca_data():
    """A value with no boundary is read as bare base64: a no-break space in it is no base64, though str.split() drops it."""
    assert _check_import("TQ\u00a0==") == ("invalid-secret", ["invalid caData"], None)


def test_an_ascii_value_reaches_the_loader_unchanged(monkeypatch):
    """The fix leaves every ASCII caData exactly as it was: the same string reaches load_verify_locations."""
    import ssl

    seen: list[object] = []
    real = ssl.SSLContext.load_verify_locations

    def spy(self, cafile=None, capath=None, cadata=None):
        seen.append(cadata)
        return real(self, cafile, capath, cadata)

    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", spy)
    value = "Explanatory text\r\n" + CA.replace("\n", "\r\n")
    assert _check_import(value) == ("connected", [], 1)
    assert seen == [value]
