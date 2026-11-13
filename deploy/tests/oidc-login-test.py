#!/usr/bin/env python3
"""deploy/oidc-login.py against a stand-in for Keycloak's authorization code flow, over TLS with a test CA.

    python deploy/tests/oidc-login-test.py

The stand-in keeps the rules of the real flow that the script must follow: the session cookie from the authorization
request must come back with the login form, the code verifier must hash to the challenge (RFC 7636, S256), the state
must come back unchanged, and the token endpoint takes the code once, from a public client, with no password and no
client secret. No Keycloak and no container: deploy/tests/realm-test.py runs the script against a real Keycloak.
Standard library and openssl only.
"""
from __future__ import annotations

import base64
import hashlib
import html
import http.server
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "oidc-login.py")
W = tempfile.mkdtemp(prefix="oidc-login-test-")
PASSWORD = "pw-of-the-test-user"
REDIRECT = "https://app.invalid/docs/oauth2-redirect"       # RFC 6761: it can never resolve, so a request to it would fail loudly
fails: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        fails.append(what)


def sh(*cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=W, **kw)


class Idp(http.server.BaseHTTPRequestHandler):
    """One realm, `t`. `mode` changes one answer, to show what the script does with a server that breaks a rule."""
    mode = "normal"
    seen: list[tuple[str, str, dict]] = []
    sessions: dict[str, dict] = {}
    codes: dict[str, dict] = {}

    def log_message(self, *args):
        pass

    def _send(self, status: int, body: str = "", headers: dict | None = None, kind: str = "text/html"):
        data = body.encode()
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _form(self) -> dict:
        return dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()))

    def _cookie(self, name: str) -> str | None:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        Idp.seen.append(("GET", url.path, q))
        if url.path != "/realms/t/protocol/openid-connect/auth":
            return self._send(404, "<title>Not found</title>")
        if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256" or not q.get("code_challenge") or not q.get("state"):
            return self._send(400, '<title>Error</title><div id="kc-error-message"><p class="instruction">Invalid parameter: code_challenge_method</p></div>')
        if q.get("client_id") != "public-app" or q.get("redirect_uri") != REDIRECT:
            return self._send(400, '<div id="kc-error-message"><p class="instruction">Invalid parameter: redirect_uri</p></div>')
        sid = base64.urlsafe_b64encode(os.urandom(9)).decode()
        Idp.sessions[sid] = q
        if Idp.mode == "no-form":
            return self._send(200, "<title>Update Account Information</title><form id=\"kc-update-profile-form\"></form>")
        # As Keycloak writes it: its public origin, and each & of the query as &amp;.
        action = html.escape(f"{PUBLIC}/realms/t/login-actions/authenticate?session_code=abc&execution=def&client_id=public-app&tab_id=xyz")
        self._send(200, f'<title>Sign in</title><form id="kc-form-login" onsubmit="return true" action="{action}" method="post"></form>',
                   {"Set-Cookie": f"AUTH_SESSION_ID={sid}; Version=1; Path=/realms/t/; SameSite=None; Secure; HttpOnly"})

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        form = self._form()
        Idp.seen.append(("POST", url.path, form))
        if url.path == "/realms/t/login-actions/authenticate":
            session = Idp.sessions.get(self._cookie("AUTH_SESSION_ID") or "")
            if session is None:
                return self._send(400, '<div id="kc-error-message"><p class="instruction">Cookie not found. Please make sure cookies are enabled in your browser.</p></div>')
            if form.get("username") == "needs.action" and form.get("password") == PASSWORD:
                return self._send(302, headers={"Location": f"{PUBLIC}/realms/t/login-actions/required-action?execution=UPDATE_PASSWORD"})
            if form.get("username") != "cmapi.viewer" or form.get("password") != PASSWORD:
                return self._send(200, '<form id="kc-form-login" action="x"><span id="input-error" class="pf-m-error" aria-live="polite">Invalid username or password.</span></form>')
            code = base64.urlsafe_b64encode(os.urandom(12)).decode()
            Idp.codes[code] = session
            state = "another-state" if Idp.mode == "wrong-state" else session["state"]
            return self._send(302, headers={"Location": REDIRECT + "?" + urllib.parse.urlencode({"state": state, "session_state": "s", "iss": f"{PUBLIC}/realms/t", "code": code})})
        if url.path == "/realms/t/protocol/openid-connect/token":
            session = Idp.codes.pop(form.get("code", ""), None)
            if form.get("grant_type") != "authorization_code" or "password" in form or "client_secret" in form:
                return self._send(400, json.dumps({"error": "unsupported_grant_type"}), kind="application/json")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
            if session is None or challenge != session["code_challenge"] or form.get("redirect_uri") != REDIRECT or form.get("client_id") != "public-app":
                return self._send(400, json.dumps({"error": "invalid_grant", "error_description": "PKCE verification failed"}), kind="application/json")
            return self._send(200, json.dumps({"access_token": "header.payload.signature", "expires_in": 300, "token_type": "Bearer"}), kind="application/json")
        self._send(404, "<title>Not found</title>")


def run(username: str, password: str | None, *extra: str, issuer: str | None = None) -> subprocess.CompletedProcess:
    Idp.seen.clear()
    return subprocess.run([sys.executable, SCRIPT, "--issuer", issuer or f"{PUBLIC}/realms/t", "--client-id", "public-app", "--redirect-uri", REDIRECT,
                           "--username", username, *extra], input="" if password is None else password + "\n", capture_output=True, text=True, timeout=60)


def main() -> int:
    global PUBLIC
    for args in (("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.crt", "-subj", "/CN=test CA", "-days", "2",
                  "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign"),
                 ("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "s.key", "-out", "s.csr", "-subj", "/CN=localhost"),
                 ("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "o.key", "-out", "other.crt", "-subj", "/CN=other CA", "-days", "2")):
        r = sh("openssl", *args)
        if r.returncode:
            sys.exit(f"openssl {args[0]}: {r.stderr[-300:]}")
    open(os.path.join(W, "san"), "w").write("subjectAltName=DNS:localhost,IP:127.0.0.1\n")
    r = sh("openssl", "x509", "-req", "-in", "s.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-out", "s.crt", "-days", "2", "-extfile", "san")
    if r.returncode:
        sys.exit(f"openssl x509: {r.stderr[-300:]}")
    ca, other = os.path.join(W, "ca.crt"), os.path.join(W, "other.crt")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Idp)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(os.path.join(W, "s.crt"), os.path.join(W, "s.key"))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    PUBLIC = f"https://localhost:{port}"

    r = run("cmapi.viewer", PASSWORD, "--cacert", ca)
    check(r.returncode == 0 and r.stdout == "header.payload.signature\n" and r.stderr == "", f"a sign-in prints the access token and nothing else: {r.returncode} {r.stderr.strip()[:200]}")
    paths = [(m, p) for m, p, _ in Idp.seen]
    check(paths == [("GET", "/realms/t/protocol/openid-connect/auth"), ("POST", "/realms/t/login-actions/authenticate"), ("POST", "/realms/t/protocol/openid-connect/token")],
          f"three requests, and none to the redirect URI: {paths}")
    token_form = Idp.seen[-1][2] if Idp.seen else {}
    check(token_form.get("grant_type") == "authorization_code" and "password" not in token_form and "client_secret" not in token_form,
          "the token request is the authorization code grant of a public client: no password and no client secret")
    check(all("password" not in q for m, _, q in Idp.seen if m == "GET"), "the password is in no query string")

    r = run("cmapi.viewer", "a-wrong-password", "--cacert", ca)
    check(r.returncode == 1 and r.stdout == "" and "Invalid username or password." in r.stderr and "a-wrong-password" not in r.stderr,
          f"a wrong password: exit 1, Keycloak's message, no token, and the password is not printed: {r.stderr.strip()[:160]}")
    check(not any(p.endswith("/token") for _, p, _ in Idp.seen), "and the token endpoint is not called")

    r = run("needs.action", PASSWORD, "--cacert", ca)
    check(r.returncode == 1 and r.stdout == "" and "needs a person" in r.stderr and "required-action" in r.stderr,
          f"a required action stops the script with the reason: {r.stderr.strip()[:160]}")

    Idp.mode = "no-form"
    r = run("cmapi.viewer", PASSWORD, "--cacert", ca)
    check(r.returncode == 1 and "did not show the login form" in r.stderr and "Update Account Information" in r.stderr, f"another page than the login form: {r.stderr.strip()[:160]}")
    Idp.mode = "wrong-state"
    r = run("cmapi.viewer", PASSWORD, "--cacert", ca)
    check(r.returncode == 1 and r.stdout == "" and "another state" in r.stderr, f"a redirect with another state is refused: {r.stderr.strip()[:120]}")
    check(not any(p.endswith("/token") for _, p, _ in Idp.seen), "and its code is not sent to the token endpoint")
    Idp.mode = "normal"

    r = run("cmapi.viewer", None, "--cacert", ca)
    check(r.returncode == 2 and "no password on standard input" in r.stderr and Idp.seen == [], "no password on standard input: exit 2, and no request")
    usage = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True).stdout
    check("--password" not in usage, "the script has no option that takes the password")

    r = run("cmapi.viewer", PASSWORD, "--cacert", other)
    check(r.returncode == 1 and r.stdout == "" and "CERTIFICATE_VERIFY_FAILED" in r.stderr and Idp.seen == [], f"a server that the CA bundle does not cover is refused before any request: {r.stderr.strip()[:140]}")
    r = run("cmapi.viewer", PASSWORD)
    check(r.returncode == 1 and "CERTIFICATE_VERIFY_FAILED" in r.stderr, "without --cacert the system store decides, and it does not know the test CA")
    source = open(SCRIPT).read()
    check("CERT_NONE" not in source and "check_hostname = False" not in source and "_create_unverified_context" not in source, "the script has no way to turn verification off")

    # --base: the issuer's host does not resolve, as in the realm test, and the form's action carries that host.
    PUBLIC = "https://keycloak.invalid"
    r = run("cmapi.viewer", PASSWORD, "--cacert", ca, "--base", f"https://localhost:{port}")
    check(r.returncode == 0 and r.stdout == "header.payload.signature\n", f"--base sends each request to another origin, the form's action also: {r.returncode} {r.stderr.strip()[:200]}")
    r = run("cmapi.viewer", PASSWORD, "--cacert", ca)
    check(r.returncode == 1 and r.stdout == "", "and without --base a host that does not resolve is an error, not a token")
    server.shutdown()
    print(f"oidc-login cases failed: {len(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
