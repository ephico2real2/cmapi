"""PR #699 review: the Notifier's TLS, the reserved worker identity in directory attribution, and utc_day's range. No
database: smtplib is replaced at its class, so nothing leaves the machine.

RFC 8314, section 5.3: "MUAs MUST validate TLS server certificates according to [RFC7817] and PKIX [RFC5280]." CPython
3.12's smtplib wraps the socket of `starttls()` with no context in `ssl._create_stdlib_context()`, which is CERT_NONE.
"""
from __future__ import annotations

import smtplib
import ssl
from unittest.mock import MagicMock, Mock

import pytest

from cmapi.core.channels import EmailChannel, EmailNotifier
from cmapi.core.clients.trust import trusted_context
from cmapi.core.errors import Problem
from cmapi.core.identity.checks import resolve_requester
from cmapi.core.identity.claims import Person
from cmapi.plugins.expiration.rules import utc_day

TO = ["payments-team@ephico2real.com"]


@pytest.fixture
def relay(monkeypatch):
    """smtplib.SMTP and SMTP_SSL replaced by one recording connection; the login comes from the environment."""
    conn = MagicMock()
    plain, implicit = Mock(return_value=conn), Mock(return_value=conn)
    monkeypatch.setattr(smtplib, "SMTP", plain)
    monkeypatch.setattr(smtplib, "SMTP_SSL", implicit)
    monkeypatch.setenv("CMAPI_SMTP_USER", "cmapi")
    monkeypatch.setenv("CMAPI_SMTP_PASSWORD", "not-a-secret")
    return conn, plain, implicit


def _calls(conn) -> list[str]:
    return [c[0] for c in conn.method_calls]


@pytest.mark.parametrize("config", [{}, {"starttls": True}, {"tls": "starttls"}])
def test_starttls_with_a_verified_certificate_before_the_login_and_the_message(relay, config):
    conn, plain, implicit = relay
    EmailNotifier({"host": "relay.example", **config}).send(TO, "notice", "body")
    plain.assert_called_once_with("relay.example", 25, timeout=10)
    implicit.assert_not_called()
    context = conn.starttls.call_args.kwargs["context"]
    assert context is trusted_context(), "the project's trust: system store and CMAPI_TRUSTED_CA_FILE, not SSL_CERT_FILE"
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    calls = _calls(conn)
    assert calls.index("starttls") < calls.index("login") < calls.index("send_message"), calls


def test_implicit_tls_verifies_from_the_first_byte(relay):
    conn, plain, implicit = relay
    EmailNotifier({"host": "relay.example", "tls": "implicit"}).send(TO, "notice", "body")
    plain.assert_not_called()
    assert implicit.call_args.args == ("relay.example", 465)
    assert implicit.call_args.kwargs["context"] is trusted_context() and implicit.call_args.kwargs["timeout"] == 10
    assert "starttls" not in _calls(conn) and "send_message" in _calls(conn)


@pytest.mark.parametrize("config", [{"starttls": False}, {"tls": "none"}, {"tls": "plain"}])
def test_a_clear_text_setting_is_refused_before_any_connection(relay, config):
    _, plain, implicit = relay
    with pytest.raises(ValueError, match="RFC 8314"):
        EmailNotifier({"host": "relay.example", **config})
    plain.assert_not_called()
    implicit.assert_not_called()


def test_a_relay_without_starttls_gets_no_login_and_no_message(relay):
    conn, _, _ = relay
    conn.starttls.side_effect = smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server.")
    with pytest.raises(smtplib.SMTPNotSupportedError):
        EmailNotifier({"host": "relay.example"}).send(TO, "notice", "body")
    assert "login" not in _calls(conn) and "send_message" not in _calls(conn)
    conn.close.assert_called()


@pytest.mark.parametrize("failure", [smtplib.SMTPServerDisconnected("gone"), ConnectionResetError("reset")])
def test_a_quit_that_fails_after_the_relay_took_the_message_is_no_failure(relay, failure):
    """RFC 5321, section 6.1: the 250 reply to DATA is the relay "accepting responsibility for delivering or relaying the
    message". Reporting the QUIT as a failure would send the notice again."""
    conn, _, _ = relay
    conn.quit.side_effect = failure
    EmailNotifier({"host": "relay.example"}).send(TO, "notice", "body")
    conn.send_message.assert_called_once()
    conn.close.assert_called()


def test_the_approval_email_channel_sends_through_the_same_verified_tls(relay):
    conn, _, _ = relay
    EmailChannel({"host": "relay.example"}, "https://portal", b"k", {}, instance="nonprod")._send(TO, "s", "b")
    assert conn.starttls.call_args.kwargs["context"] is trusted_context()


@pytest.mark.parametrize("person", [Person("cmapi-expire-check", None, sub="u-1"),
                                    Person("someone", None, sub="cmapi-expire-check"),
                                    Person("CMAPI-Expire-Check", None, sub="u-2")])
def test_a_directory_entry_named_like_the_worker_is_no_requester(person):
    directory = Mock()
    directory.get_user.return_value = person
    with pytest.raises(Problem) as refused:
        resolve_requester(Mock(kind="service", roles=frozenset()), person.username, directory)
    assert refused.value.code == "unknown-user"


def test_an_offset_beyond_the_date_range_is_an_unknown_day():
    assert utc_day("0001-01-01T00:00:00+01:00") is None
    assert utc_day("9999-12-31T23:59:59-01:00") is None
    assert str(utc_day("2026-11-17T23:30:00-02:00")) == "2026-11-18"
