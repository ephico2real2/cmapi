#!/usr/bin/env python3
"""Sign a test user in to a Keycloak realm as a browser does, and print the access token.

    printf '%s' "$password" | deploy/oidc-login.py --issuer https://keycloak.apps-crc.testing/realms/cmapi \\
        --client-id cmapi-docs --redirect-uri https://cmapi-api.apps-crc.testing/docs/oauth2-redirect \\
        --username cmapi.viewer --cacert "$CMAPI_CRC_CA"

The flow is the authorization code grant with PKCE (RFC 7636, S256) through a public client: the request to the
authorization endpoint, Keycloak's own login form, the redirect with the code, then the token endpoint. The password
goes only to Keycloak's login form, as it does from a browser. No client of realm `cmapi` takes the resource owner
password grant, which RFC 9700 section 2.4 forbids (#181).

The script is for the test identities of the proofs (deploy/crc-proof.sh, deploy/tests/realm-test.py). It reads the
password from standard input, so that it is in no argument and no environment variable, and it prints nothing else but
the token. It follows no redirect: the redirect URI is read from the Location header and never requested. It stops with
a reason, and with no secret in it, when Keycloak shows another page than the login form (a required action, a consent
page, a second factor): those need a person.

--base gives another origin to send the requests to when the issuer's own host does not resolve from here (the realm
test runs Keycloak on 127.0.0.1 with the public hostname configured). TLS is verified always; --cacert adds a CA bundle.
Python standard library only.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import secrets
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Mapping

FORM = re.compile(r'<form\b[^>]*\bid="kc-form-login"[^>]*>', re.I)
ACTION = re.compile(r'\baction="([^"]+)"', re.I)
# Keycloak's own message elements, by theme generation: the field error, then the page alert.
MESSAGES = (re.compile(r'id="input-error[^"]*"[^>]*>(.*?)</', re.I | re.S),
            re.compile(r'class="[^"]*kc-feedback-text[^"]*"[^>]*>(.*?)</', re.I | re.S),
            re.compile(r'class="[^"]*pf-v5-c-alert__title[^"]*"[^>]*>(.*?)</', re.I | re.S),
            re.compile(r'id="kc-error-message"[^>]*>\s*<p[^>]*>(.*?)</p>', re.I | re.S))


class LoginError(Exception):
    """The sign-in did not give a token. The text never holds a password, a code or a token."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):          # a redirect is an answer to read, never a request to make
        return None


def pkce_pair() -> tuple[str, str]:
    """A code verifier and its S256 challenge (RFC 7636, sections 4.1 and 4.2)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _page_message(page: str) -> str:
    for pattern in MESSAGES:
        found = pattern.search(page)
        if found:
            text = re.sub(r"<[^>]+>", " ", html.unescape(found.group(1)))
            return " ".join(text.split())[:200]
    title = re.search(r"<title>(.*?)</title>", page, re.I | re.S)
    return ("page titled " + " ".join(html.unescape(title.group(1)).split())[:120]) if title else "no message on the page"


class Session:
    """The few things of a browser that the flow needs: cookies, no automatic redirect, and TLS verification."""

    def __init__(self, issuer: str, base: str | None, cacert: str | None, timeout: float = 15.0):
        self.issuer = issuer.rstrip("/")
        public = urllib.parse.urlsplit(self.issuer)
        self.public_origin = f"{public.scheme}://{public.netloc}"
        self.origin = (base or self.public_origin).rstrip("/")
        self.timeout = timeout
        self.cookies: dict[str, str] = {}
        context = ssl.create_default_context(cafile=cacert) if cacert else ssl.create_default_context()
        self.opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context))

    def _url(self, url: str) -> str:
        """The address to send to: Keycloak writes its public origin into the form, and --base can replace it."""
        return self.origin + url[len(self.public_origin):] if url.startswith(self.public_origin) else url

    def request(self, method: str, url: str, form: Mapping[str, str] | None = None) -> tuple[int, Mapping[str, str], str]:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        req = urllib.request.Request(self._url(url), data=data, method=method)
        if self.cookies:
            # Each cookie that Keycloak set, also one marked Secure, when --base is plain HTTP on the loopback address.
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        try:
            response = self.opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as answer:            # 302, 400 and 401 are answers of the flow
            response = answer
        except (urllib.error.URLError, OSError) as exc:
            raise LoginError(f"{method} {urllib.parse.urlsplit(self._url(url)).netloc}: {exc}") from None
        with response:
            for header in response.headers.get_all("Set-Cookie") or []:
                name, _, value = header.split(";", 1)[0].partition("=")
                if value == "" or "max-age=0" in header.lower():
                    self.cookies.pop(name.strip(), None)
                else:
                    self.cookies[name.strip()] = value
            return response.status, response.headers, response.read().decode("utf-8", "replace")


def login(issuer: str, client_id: str, redirect_uri: str, username: str, password: str, *, base: str | None = None,
          cacert: str | None = None, scope: str = "openid") -> dict:
    """The token endpoint's answer for this user: access_token, id_token, expires_in. Raises LoginError with the reason."""
    session = Session(issuer, base, cacert)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    query = urllib.parse.urlencode({"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": scope,
                                    "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    status, _, page = session.request("GET", f"{session.issuer}/protocol/openid-connect/auth?{query}")
    form = FORM.search(page)
    if status != 200 or not form:
        raise LoginError(f"the authorization endpoint did not show the login form (HTTP {status}): {_page_message(page)}")
    action = ACTION.search(form.group(0))
    if not action:
        raise LoginError("the login form has no action")
    status, headers, page = session.request("POST", html.unescape(action.group(1)),
                                            {"username": username, "password": password, "credentialId": ""})
    location = headers.get("Location", "")
    if status != 302 or not location.startswith(redirect_uri):
        if status == 302:
            raise LoginError(f"Keycloak asks for another step before the redirect, which needs a person: {urllib.parse.urlsplit(location).path}")
        raise LoginError(f"the sign-in of {username} was refused (HTTP {status}): {_page_message(page)}")
    answer = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(location).query))
    if answer.get("state") != state:
        raise LoginError("the redirect has another state than the request")
    if "code" not in answer:
        raise LoginError(f"the redirect has no code: {answer.get('error', 'no error')} {answer.get('error_description', '')}".strip())
    status, _, body = session.request("POST", f"{session.issuer}/protocol/openid-connect/token",
                                      {"grant_type": "authorization_code", "code": answer["code"], "redirect_uri": redirect_uri,
                                       "client_id": client_id, "code_verifier": verifier})
    try:
        tokens = json.loads(body)
    except ValueError:
        raise LoginError(f"the token endpoint did not answer JSON (HTTP {status})") from None
    if status != 200 or "access_token" not in tokens:
        raise LoginError(f"the token endpoint refused the code (HTTP {status}): {tokens.get('error')} {tokens.get('error_description', '')}".strip())
    return tokens


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Sign a test user in with the authorization code grant and PKCE, and print the access token.")
    parser.add_argument("--issuer", required=True, help="the realm's issuer, as tokens carry it")
    parser.add_argument("--client-id", required=True, help="a public client with the standard flow, such as cmapi-docs")
    parser.add_argument("--redirect-uri", required=True, help="a redirect URI of that client; it is never requested")
    parser.add_argument("--username", required=True)
    parser.add_argument("--base", help="send the requests to this origin instead of the issuer's")
    parser.add_argument("--cacert", help="the CA bundle to trust instead of the system store")
    parser.add_argument("--scope", default="openid")
    args = parser.parse_args(argv)
    password = sys.stdin.readline().rstrip("\n")
    if not password:
        print("oidc-login: no password on standard input", file=sys.stderr)
        return 2
    try:
        tokens = login(args.issuer, args.client_id, args.redirect_uri, args.username, password, base=args.base,
                       cacert=args.cacert, scope=args.scope)
    except LoginError as exc:
        print(f"oidc-login: {exc}", file=sys.stderr)
        return 1
    print(tokens["access_token"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
