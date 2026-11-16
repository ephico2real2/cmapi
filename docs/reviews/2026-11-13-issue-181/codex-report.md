# cmapi PR #190 / SEC-06 review, head 31d625b

Second-reader report. Four requested claims are refuted (C1, C2, C3, C7); C4, C5, C6, C8 and C9 are confirmed within their stated source/configuration scope; C10's live execution remains plausible. Two additional findings concern the Helm-generated admin-cli and removal of configured plugin controls. Every reported defect has an executed failing regression and a passing fix, reproduced as full code below.

Scope: head/ and change.diff in this folder. No containers or database connections. TokenSave context/status/read were attempted; this export is not indexed and the server has no default graph, so inspection used read-only shell tools. Proposed fixes were applied only to copies under report/; production source files in head/ were not edited. Keycloak source citations use 26.6.4, the line named by the shipped test; live RHBK/Keycloak interoperability was not measured.

## C1 — REFUTED: error output is not secret-safe (P2)

The normal flow puts the password in one form POST and never includes it in the authorization query or token request. `head/deploy/oidc-login.py:96` says `data = urllib.parse.urlencode(form).encode()`, and `:136` is the only request with `{"username": username, "password": password, "credentialId": ""}`. The CLI reads stdin at `:169`, has no password option at `:160-167`, and writes only the successful access token to stdout at `:179`. The new tests inspect the actual requests, not just the source.

The guarantee about errors is false. `head/deploy/oidc-login.py:69-70` is:

```python
text = re.sub(r"<[^>]+>", " ", html.unescape(found.group(1)))
return " ".join(text.split())[:200]
```

`:72` also copies the page title. Neither operation redacts secrets. `:141` inserts `_page_message(page)` into LoginError, and `:177` prints that exception to stderr. HTML entity decoding makes an entity-encoded secret printable too. `:140` prints the redirect path; `:146` and `:155` print arbitrary OAuth error descriptions. Those can carry the authorization code or tokens. Truncating text does not remove them.

Executed counterexample: the local login form receives `private-password-181`, then responds with an `input-error` element echoing it. The CLI exits 1 and stderr contains `the sign-in of viewer was refused (HTTP 200): private-password-181 private-code-181 private-token-181`. An echoing title, token error description, callback error description, and required-action path all fail the same secret-output assertion. This is a deterministic counterexample to the script's guarantee; it does not allege that the shipped stock theme normally echoes a password.

The stock Keycloak path uses a static invalid-user error: [AbstractUsernameFormAuthenticator.java, 26.6.4, lines 232-264](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/authentication/authenticators/browser/AbstractUsernameFormAuthenticator.java#L232) returns `Messages.INVALID_USER;`. [The login template, lines 21-23](https://github.com/keycloak/keycloak/blob/26.6.4/themes/src/main/resources/theme/base/login/login.ftl#L21) renders `messagesPerField.getFirstError('username','password')`. Thus an ordinary bad password is not itself an observed stock-theme reflection. Configured themes/authenticators and error pages can supply other text; the helper imposes no secrecy boundary on that text. Whether a particular deployed Keycloak theme reflects a password is untested, and is not needed for the failing script-level test.

Fix: emit local constant diagnostics; retain only a small exact allowlist of useful stock messages. Remove arbitrary error descriptions, redirect paths, URL authorities and raw network exception strings from errors. This protects codes/tokens as well as the password, rather than only replacing the password string. `fix_c1.py` applies to an explicit copy, and is independent of C2/C3.

Regression: `SecurityTests.test_C1_no_response_secrets_in_cli_errors` in the full test below fails in five subcases before this fix and passes after it. The test invokes the real CLI entry point with captured stdin/stdout/stderr and a local HTTP stand-in. All credentials in this report/tests are synthetic.

Full new file `report/fix_c1.py`:

```python
"""Apply C1 to an explicit copy of oidc-login.py; never edits head implicitly."""
from pathlib import Path
import sys


def apply(path):
    source = Path(path).read_text()
    start = source.index('def _page_message(')
    end = source.index('\n\nclass Session:', start)
    source = source[:start] + '''def _page_message(page: str) -> str:
    # Return local constants only. Themes and providers can put credentials in page text.
    safe = {
        "Invalid username or password.": "Invalid username or password.",
        "Cookie not found. Please make sure cookies are enabled in your browser.":
            "Cookie not found. Please make sure cookies are enabled in your browser.",
    }
    for pattern in MESSAGES:
        found = pattern.search(page)
        if found:
            text = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(found.group(1))).split())
            return safe.get(text, "no safe message on the page")
    title = re.search(r"<title>(.*?)</title>", page, re.I | re.S)
    if title and " ".join(html.unescape(title.group(1)).split()) == "Update Account Information":
        return "page titled Update Account Information"
    return "no safe message on the page"
''' + source[end:]
    replacements = {
        'raise LoginError(f"{self.origin} is not HTTPS and not the loopback address: the password would cross the network in clear")':
            'raise LoginError("the target is not HTTPS and not the loopback address: the password would cross the network in clear")',
        'raise LoginError(f"{method} {urllib.parse.urlsplit(self._url(url)).netloc}: {exc}") from None':
            'reason = getattr(exc, "reason", exc)\n            if isinstance(reason, ssl.SSLCertVerificationError):\n                raise LoginError("TLS verification failed (CERTIFICATE_VERIFY_FAILED)") from None\n            raise LoginError("the request failed") from None',
        'raise LoginError(f"the login form posts to {urllib.parse.urlsplit(target).netloc or \'a relative address\'}, which is not under the issuer: the password is not sent")':
            'raise LoginError("the login form is not under the issuer: the password is not sent")',
        'raise LoginError(f"Keycloak asks for another step before the redirect, which needs a person: {urllib.parse.urlsplit(location).path}")':
            'raise LoginError("Keycloak asks for a required-action or another step before the redirect, which needs a person")',
        'raise LoginError(f"the sign-in of {username} was refused (HTTP {status}): {_page_message(page)}")':
            'raise LoginError(f"the sign-in was refused (HTTP {status}): {_page_message(page)}")',
        'raise LoginError(f"the redirect has no code: {answer.get(\'error\', \'no error\')} {answer.get(\'error_description\', \'\')}".strip())':
            'raise LoginError("the redirect has no code")',
        'raise LoginError(f"the token endpoint refused the code (HTTP {status}): {tokens.get(\'error\')} {tokens.get(\'error_description\', \'\')}".strip())':
            'raise LoginError(f"the token endpoint refused the code (HTTP {status})")',
    }
    for old, new in replacements.items():
        assert old in source, old
        source = source.replace(old, new)
    Path(path).write_text(source)


if __name__ == '__main__':
    apply(sys.argv[1])
```

Full new file `report/fix_c1_test_expectations.py`:

```python
"""Update the existing stand-in to expect fixed, secret-safe diagnostics."""
from pathlib import Path
import sys


def apply(path):
    path = Path(path)
    source = path.read_text()
    old_loop = 'for mode, where in (("foreign-action", "elsewhere.invalid"), ("other-realm", f"localhost:{port}")):'
    assert old_loop in source
    source = source.replace(old_loop, 'for mode in ("foreign-action", "other-realm"):')
    old_check = ' and where in r.stderr and '
    assert old_check in source
    source = source.replace(old_check, ' and ')
    path.write_text(source)


if __name__ == '__main__':
    apply(sys.argv[1])
```

Full new file `report/test_oidc_security.py`:

```python
"""No database/container; local stand-in regressions. OIDC_SCRIPT selects original/fixed helper."""
import base64
import contextlib
import hashlib
import html
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import threading
import unittest
import urllib.parse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get('OIDC_SCRIPT', ROOT / 'head/deploy/oidc-login.py'))
spec = importlib.util.spec_from_file_location('oidc_review', SCRIPT)
ol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ol)
PASSWORD = 'private-password-181'
CODE = 'private-code-181'
TOKEN = 'private-token-181'
REDIRECT = 'https://app.invalid/callback'


class Idp(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body='', headers=()):
        data = body.encode()
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.server.seen.append(('GET', self.path, b'', self.headers.get('Cookie')))
        self.server.query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
        if self.server.mode == 'redirect':
            return self.reply(self.server.redirect_status, headers=[('Location', self.server.origin + '/unexpected')])
        action = self.server.action or self.server.issuer + '/login-actions/authenticate?x=1&y=2'
        tag = self.server.raw_form or '<form id="kc-form-login" action="' + html.escape(action, quote=True) + '"></form>'
        self.reply(200, self.server.prefix + tag,
                   [('Set-Cookie', 'AUTH_SESSION_ID=signed.value.route; Path=/realms/cmapi/; Secure; HttpOnly'),
                    ('Set-Cookie', 'KC_AUTH_SESSION_HASH=hash; Path=/realms/cmapi/; Secure'),
                    ('Set-Cookie', 'KC_RESTART=restart; Path=/realms/cmapi/; Secure; HttpOnly')])

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.server.seen.append(('POST', self.path, body, self.headers.get('Cookie')))
        form = dict(urllib.parse.parse_qsl(body.decode()))
        if self.server.mode == 'proxy':
            return self.reply(400)
        if self.path.endswith('/token'):
            if self.server.mode == 'token-error':
                return self.reply(400, json.dumps({'error': 'invalid_grant', 'error_description': CODE + ' ' + TOKEN}))
            return self.reply(200, json.dumps({'access_token': TOKEN}))
        if self.server.mode in ('echo', 'echo-title'):
            text = html.escape(form['password'] + ' ' + CODE + ' ' + TOKEN)
            return self.reply(200, '<span id="input-error">' + text + '</span>' if self.server.mode == 'echo' else '<title>' + text + '</title>')
        state = self.server.query['state']
        if self.server.mode == 'state':
            state = 'wrong-state'
        if self.server.mode == 'redirect-error':
            location = REDIRECT + '?' + urllib.parse.urlencode({'state': state, 'error': 'access_denied', 'error_description': CODE + ' ' + TOKEN})
        elif self.server.mode == 'step':
            location = self.server.issuer + '/login-actions/' + CODE + '/' + TOKEN
        else:
            location = REDIRECT + '?' + urllib.parse.urlencode({'state': state, 'code': CODE})
        self.reply(302, headers=[('Location', location)])


@contextlib.contextmanager
def server():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Idp)
    srv.origin = 'http://127.0.0.1:' + str(srv.server_port)
    srv.issuer = srv.origin + '/realms/cmapi'
    srv.seen, srv.action, srv.prefix, srv.mode, srv.raw_form = [], None, '', 'normal', None
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join()


def login(srv, **kwargs):
    return ol.login(srv.issuer, 'public-app', REDIRECT, 'viewer', PASSWORD, **kwargs)


class SecurityTests(unittest.TestCase):
    def test_C1_no_response_secrets_in_cli_errors(self):
        for mode in ('echo', 'echo-title', 'token-error', 'redirect-error', 'step'):
            with self.subTest(mode=mode), server() as srv:
                srv.mode = mode
                out, err = io.StringIO(), io.StringIO()
                args = ['--issuer', srv.issuer, '--client-id', 'public-app', '--redirect-uri', REDIRECT, '--username', 'viewer']
                with patch('sys.stdin', io.StringIO(PASSWORD + '\n')), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = ol.main(args)
                self.assertEqual(rc, 1)
                self.assertEqual(out.getvalue(), '')
                for secret in (PASSWORD, CODE, TOKEN):
                    self.assertNotIn(secret, err.getvalue())

    def test_C2_dot_segments_get_no_password_or_cookies(self):
        for tail in ('../other/login-actions/authenticate', '%2e%2e/other/login-actions/authenticate',
                     '%252e%252e/other/login-actions/authenticate', 'x/../../other/login-actions/authenticate'):
            for use_base in (False, True):
                with self.subTest(tail=tail, base=use_base), server() as srv:
                    public = 'https://issuer.example/realms/cmapi' if use_base else srv.issuer
                    srv.action = public + '/' + tail
                    try:
                        ol.login(public, 'public-app', REDIRECT, 'viewer', PASSWORD, base=srv.origin if use_base else None)
                    except ol.LoginError:
                        pass
                    self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])

    def test_C2_foreign_hosts_ports_realms_and_second_forms(self):
        with server() as srv:
            for action in ('https://issuer.example.evil/realms/cmapi/login', 'https://issuer.example@evil.example/realms/cmapi/login',
                           'https://issuer.example:444/realms/cmapi/login', 'https://issuer.example/realms/other/login'):
                with self.subTest(action=action):
                    srv.seen.clear()
                    srv.action = action
                    with self.assertRaises(ol.LoginError):
                        ol.login('https://issuer.example/realms/cmapi', 'public-app', REDIRECT, 'viewer', PASSWORD, base=srv.origin)
                    self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])
            srv.action = None
            srv.prefix = '<form id="other-form" action="https://evil.example/login"></form>'
            self.assertEqual(login(srv)['access_token'], TOKEN)
            self.assertTrue(all(urllib.parse.urlsplit(p).hostname is None for _, p, _, _ in srv.seen))

    def test_C2_html_entities_and_action_quote_styles(self):
        for style in ("single", "none"):
            with self.subTest(style=style), server() as srv:
                action = srv.issuer + '/login-actions/authenticate'
                attr = "action='" + action + "'" if style == 'single' else 'action=' + action
                srv.raw_form = '<form id="kc-form-login" ' + attr + '></form>'
                with self.assertRaises(ol.LoginError):
                    login(srv)
                self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])
        with server() as srv:
            srv.raw_form = '<form id="kc-form-login" action="' + srv.issuer + '/&#46;&#46;/other/login-actions/authenticate"></form>'
            try:
                login(srv)
            except ol.LoginError:
                pass
            self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])

    def test_C3_loopback_http_does_not_use_environment_proxy(self):
        with server() as proxy:
            proxy.mode = 'proxy'
            # The intended --base is a different, closed loopback port. A proxy must receive nothing.
            env = {'http_proxy': proxy.origin, 'HTTP_PROXY': proxy.origin, 'no_proxy': '', 'NO_PROXY': ''}
            with patch.dict(os.environ, env, clear=True):
                session = ol.Session('https://issuer.example/realms/cmapi', 'http://127.0.0.1:1', None, timeout=1)
                try:
                    session.request('POST', session.issuer + '/login-actions/authenticate', {'password': PASSWORD})
                except ol.LoginError:
                    pass
            self.assertEqual(proxy.seen, [])

    def test_C3_http_host_checks_and_redirects(self):
        for host in ('localhost.evil.example', '127.0.0.1.evil.example', '127.0.0.1@evil.example', '[::1]@evil.example'):
            for use_base in (False, True):
                with self.subTest(host=host, base=use_base), self.assertRaises((ol.LoginError, ValueError)):
                    ol.Session('https://issuer.example/realms/cmapi' if use_base else 'http://' + host + '/realms/cmapi',
                               'http://' + host if use_base else None, None)
        for status in (301, 302, 303, 307, 308):
            for method in ('GET', 'POST'):
                with self.subTest(status=status, method=method), server() as srv:
                    srv.redirect_status, srv.mode = status, 'redirect'
                    # Use a redirecting GET handler for either method.
                    with patch.object(Idp, 'do_POST', Idp.do_GET):
                        s = ol.Session(srv.issuer, None, None)
                        answer, _, _ = s.request(method, srv.issuer + '/auth', {'password': PASSWORD} if method == 'POST' else None)
                    self.assertEqual(answer, status)
                    self.assertEqual(len(srv.seen), 1)

    def test_C4_pkce_state_and_password_request_count(self):
        for _ in range(100):
            verifier, challenge = ol.pkce_pair()
            self.assertRegex(verifier, r'^[A-Za-z0-9._~-]{43,128}$')
            self.assertEqual(len(base64.urlsafe_b64decode(verifier)), 48)
            self.assertEqual(challenge, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
        with server() as srv:
            self.assertEqual(login(srv)['access_token'], TOKEN)
            bodies = [dict(urllib.parse.parse_qsl(b.decode())) for _, _, b, _ in srv.seen]
            self.assertEqual(sum('password' in b for b in bodies), 1)
            self.assertTrue(all(PASSWORD not in p for _, p, _, _ in srv.seen))
            self.assertEqual(bodies[-1]['redirect_uri'], srv.query['redirect_uri'])
            self.assertEqual(bodies[-1]['client_id'], srv.query['client_id'])
            self.assertEqual(bodies[-1]['code'], CODE)
            self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(bodies[-1]['code_verifier'].encode()).digest()).decode().rstrip('='), srv.query['code_challenge'])
            self.assertIn('KC_AUTH_SESSION_HASH=hash', srv.seen[1][3])
            self.assertIn('AUTH_SESSION_ID=signed.value.route', srv.seen[1][3])
            self.assertIn('KC_RESTART=restart', srv.seen[1][3])
        with server() as srv:
            srv.mode = 'state'
            with self.assertRaises(ol.LoginError):
                login(srv)
            self.assertFalse(any(p.endswith('/token') for _, p, _, _ in srv.seen))


if __name__ == '__main__':
    unittest.main()
```

## C2 — REFUTED: string containment accepts another realm's canonical path (P2)

Evidence: `head/deploy/oidc-login.py:134` tests only `target.startswith(session.issuer + "/")`; `:136` then sends the password there. `:93` rewrites an origin with `url.startswith(self.public_origin)`. These operations do not parse or canonicalize a URL.

With issuer `https://issuer.example/realms/cmapi`, a page can give this action:

```text
https://issuer.example/realms/cmapi/../other/login-actions/authenticate
```

It passes the check. The test's loopback receiver actually receives the password POST at `/realms/cmapi/../other/login-actions/authenticate`, with all three cookies. Its canonical path is `/realms/other/login-actions/authenticate`; [RFC 3986 section 5.2.4](https://www.rfc-editor.org/rfc/rfc3986.html#section-5.2.4) specifies dot-segment removal. The raw and encoded dot-segment variants all cause a POST before any rejection, including when the public issuer is rewritten through `--base`. A server/proxy's precise normalization and whether another real Keycloak realm accepts the session are not measured here; the proven failure is that the helper sends credentials to a URL outside the requested canonical realm. The guard is meant to reject the request before that happens.

The specific cross-host prefix tricks in the brief do not bypass `login()` with this normal issuer: `issuer.example.evil`, userinfo before another host, and a different port fail the full issuer-plus-slash check. Entities are decoded before checking, so `&#47;` does not hide a foreign origin; it can hide the dot-segment attack until decoding. Single-quoted or unquoted actions have no match in the double-quote-only `ACTION` pattern (`head/deploy/oidc-login.py:42`) and fail closed. A second ordinary form with another ID is ignored by `FORM` (`:41`). The regex is not a general HTML parser and does not support those quote styles; that is a compatibility limit, not a password leak. `Session._url()` alone does also rewrite a foreign origin with the same textual prefix, although the existing `login()` guard blocks that particular host attack. Tests cover both the public URL and `--base`.

Fix: compare parsed origins and reject path encodings, dot segments, backslashes, semicolons, controls and repeated slashes before sending. Apply this in `Session._url()` as well as the form check, so every request is confined and the cookie jar shares that boundary. Require `--base` to be an origin. This deliberately restricts the proof helper to ordinary literal Keycloak realm paths; percent-encoded realm names would need a separate canonical representation design.

Regression: `test_C2_dot_segments_get_no_password_or_cookies` fails in eight subcases on head (four paths, with/without `--base`); the entity-encoded dot-segment case is a ninth failure. All pass after C2. The foreign-host/port/realm and second-form controls pass on head. Full test text is repeated here so this claim includes its complete runnable regression.

Full new file `report/fix_c2.py`:

```python
"""Apply URL containment to an explicit copy. Safe Keycloak paths need no percent escapes."""
from pathlib import Path
import sys


HELPER = '''def _checked_url(value: str):
    # Reject characters that parsers/proxies can remove or normalize differently.
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\\\" in value:
        raise LoginError("invalid URL")
    try:
        url = urllib.parse.urlsplit(value)
        port = url.port
    except ValueError:
        raise LoginError("invalid URL") from None
    if url.scheme not in ("https", "http") or not url.hostname or url.username is not None or url.password is not None:
        raise LoginError("invalid URL")
    if url.fragment or "%" in url.path or ";" in url.path or "//" in url.path:
        raise LoginError("invalid URL path")
    if any(p in (".", "..") for p in url.path.split("/")):
        raise LoginError("invalid URL path")
    return url


def _same_origin(left, right) -> bool:
    def origin(url):
        return url.scheme, url.hostname, (url.port if url.port is not None else (443 if url.scheme == "https" else 80))
    return origin(left) == origin(right)


'''


def apply(path):
    source = Path(path).read_text()
    source = source.replace('class Session:', HELPER + 'class Session:', 1)
    source = source.replace('public = urllib.parse.urlsplit(self.issuer)', 'public = _checked_url(self.issuer)\n        if public.query or not public.path.startswith("/realms/"):\n            raise LoginError("invalid realm issuer")', 1)
    source = source.replace('target = urllib.parse.urlsplit(self.origin)', 'target = _checked_url(self.origin)\n        if target.path or target.query:\n            raise LoginError("base must be an origin")', 1)
    old = 'return self.origin + url[len(self.public_origin):] if url.startswith(self.public_origin) else url'
    new = '''target, issuer = _checked_url(url), _checked_url(self.issuer)
        if not _same_origin(target, issuer) or not target.path.startswith(issuer.path + "/"):
            raise LoginError("the request is not under the issuer")
        return self.origin + urllib.parse.urlunsplit(("", "", target.path, target.query, ""))'''
    assert old in source
    source = source.replace(old, new)
    old = 'if not target.startswith(session.issuer + "/"):'
    new = '''parsed, public = _checked_url(target), _checked_url(session.issuer)
    if not _same_origin(parsed, public) or not parsed.path.startswith(public.path + "/"):'''
    assert old in source
    source = source.replace(old, new)
    Path(path).write_text(source)


if __name__ == '__main__':
    apply(sys.argv[1])
```

Full new file `report/test_oidc_security.py`:

```python
"""No database/container; local stand-in regressions. OIDC_SCRIPT selects original/fixed helper."""
import base64
import contextlib
import hashlib
import html
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import threading
import unittest
import urllib.parse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get('OIDC_SCRIPT', ROOT / 'head/deploy/oidc-login.py'))
spec = importlib.util.spec_from_file_location('oidc_review', SCRIPT)
ol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ol)
PASSWORD = 'private-password-181'
CODE = 'private-code-181'
TOKEN = 'private-token-181'
REDIRECT = 'https://app.invalid/callback'


class Idp(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body='', headers=()):
        data = body.encode()
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.server.seen.append(('GET', self.path, b'', self.headers.get('Cookie')))
        self.server.query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
        if self.server.mode == 'redirect':
            return self.reply(self.server.redirect_status, headers=[('Location', self.server.origin + '/unexpected')])
        action = self.server.action or self.server.issuer + '/login-actions/authenticate?x=1&y=2'
        tag = self.server.raw_form or '<form id="kc-form-login" action="' + html.escape(action, quote=True) + '"></form>'
        self.reply(200, self.server.prefix + tag,
                   [('Set-Cookie', 'AUTH_SESSION_ID=signed.value.route; Path=/realms/cmapi/; Secure; HttpOnly'),
                    ('Set-Cookie', 'KC_AUTH_SESSION_HASH=hash; Path=/realms/cmapi/; Secure'),
                    ('Set-Cookie', 'KC_RESTART=restart; Path=/realms/cmapi/; Secure; HttpOnly')])

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.server.seen.append(('POST', self.path, body, self.headers.get('Cookie')))
        form = dict(urllib.parse.parse_qsl(body.decode()))
        if self.server.mode == 'proxy':
            return self.reply(400)
        if self.path.endswith('/token'):
            if self.server.mode == 'token-error':
                return self.reply(400, json.dumps({'error': 'invalid_grant', 'error_description': CODE + ' ' + TOKEN}))
            return self.reply(200, json.dumps({'access_token': TOKEN}))
        if self.server.mode in ('echo', 'echo-title'):
            text = html.escape(form['password'] + ' ' + CODE + ' ' + TOKEN)
            return self.reply(200, '<span id="input-error">' + text + '</span>' if self.server.mode == 'echo' else '<title>' + text + '</title>')
        state = self.server.query['state']
        if self.server.mode == 'state':
            state = 'wrong-state'
        if self.server.mode == 'redirect-error':
            location = REDIRECT + '?' + urllib.parse.urlencode({'state': state, 'error': 'access_denied', 'error_description': CODE + ' ' + TOKEN})
        elif self.server.mode == 'step':
            location = self.server.issuer + '/login-actions/' + CODE + '/' + TOKEN
        else:
            location = REDIRECT + '?' + urllib.parse.urlencode({'state': state, 'code': CODE})
        self.reply(302, headers=[('Location', location)])


@contextlib.contextmanager
def server():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Idp)
    srv.origin = 'http://127.0.0.1:' + str(srv.server_port)
    srv.issuer = srv.origin + '/realms/cmapi'
    srv.seen, srv.action, srv.prefix, srv.mode, srv.raw_form = [], None, '', 'normal', None
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join()


def login(srv, **kwargs):
    return ol.login(srv.issuer, 'public-app', REDIRECT, 'viewer', PASSWORD, **kwargs)


class SecurityTests(unittest.TestCase):
    def test_C1_no_response_secrets_in_cli_errors(self):
        for mode in ('echo', 'echo-title', 'token-error', 'redirect-error', 'step'):
            with self.subTest(mode=mode), server() as srv:
                srv.mode = mode
                out, err = io.StringIO(), io.StringIO()
                args = ['--issuer', srv.issuer, '--client-id', 'public-app', '--redirect-uri', REDIRECT, '--username', 'viewer']
                with patch('sys.stdin', io.StringIO(PASSWORD + '\n')), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = ol.main(args)
                self.assertEqual(rc, 1)
                self.assertEqual(out.getvalue(), '')
                for secret in (PASSWORD, CODE, TOKEN):
                    self.assertNotIn(secret, err.getvalue())

    def test_C2_dot_segments_get_no_password_or_cookies(self):
        for tail in ('../other/login-actions/authenticate', '%2e%2e/other/login-actions/authenticate',
                     '%252e%252e/other/login-actions/authenticate', 'x/../../other/login-actions/authenticate'):
            for use_base in (False, True):
                with self.subTest(tail=tail, base=use_base), server() as srv:
                    public = 'https://issuer.example/realms/cmapi' if use_base else srv.issuer
                    srv.action = public + '/' + tail
                    try:
                        ol.login(public, 'public-app', REDIRECT, 'viewer', PASSWORD, base=srv.origin if use_base else None)
                    except ol.LoginError:
                        pass
                    self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])

    def test_C2_foreign_hosts_ports_realms_and_second_forms(self):
        with server() as srv:
            for action in ('https://issuer.example.evil/realms/cmapi/login', 'https://issuer.example@evil.example/realms/cmapi/login',
                           'https://issuer.example:444/realms/cmapi/login', 'https://issuer.example/realms/other/login'):
                with self.subTest(action=action):
                    srv.seen.clear()
                    srv.action = action
                    with self.assertRaises(ol.LoginError):
                        ol.login('https://issuer.example/realms/cmapi', 'public-app', REDIRECT, 'viewer', PASSWORD, base=srv.origin)
                    self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])
            srv.action = None
            srv.prefix = '<form id="other-form" action="https://evil.example/login"></form>'
            self.assertEqual(login(srv)['access_token'], TOKEN)
            self.assertTrue(all(urllib.parse.urlsplit(p).hostname is None for _, p, _, _ in srv.seen))

    def test_C2_html_entities_and_action_quote_styles(self):
        for style in ("single", "none"):
            with self.subTest(style=style), server() as srv:
                action = srv.issuer + '/login-actions/authenticate'
                attr = "action='" + action + "'" if style == 'single' else 'action=' + action
                srv.raw_form = '<form id="kc-form-login" ' + attr + '></form>'
                with self.assertRaises(ol.LoginError):
                    login(srv)
                self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])
        with server() as srv:
            srv.raw_form = '<form id="kc-form-login" action="' + srv.issuer + '/&#46;&#46;/other/login-actions/authenticate"></form>'
            try:
                login(srv)
            except ol.LoginError:
                pass
            self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])

    def test_C3_loopback_http_does_not_use_environment_proxy(self):
        with server() as proxy:
            proxy.mode = 'proxy'
            # The intended --base is a different, closed loopback port. A proxy must receive nothing.
            env = {'http_proxy': proxy.origin, 'HTTP_PROXY': proxy.origin, 'no_proxy': '', 'NO_PROXY': ''}
            with patch.dict(os.environ, env, clear=True):
                session = ol.Session('https://issuer.example/realms/cmapi', 'http://127.0.0.1:1', None, timeout=1)
                try:
                    session.request('POST', session.issuer + '/login-actions/authenticate', {'password': PASSWORD})
                except ol.LoginError:
                    pass
            self.assertEqual(proxy.seen, [])

    def test_C3_http_host_checks_and_redirects(self):
        for host in ('localhost.evil.example', '127.0.0.1.evil.example', '127.0.0.1@evil.example', '[::1]@evil.example'):
            for use_base in (False, True):
                with self.subTest(host=host, base=use_base), self.assertRaises((ol.LoginError, ValueError)):
                    ol.Session('https://issuer.example/realms/cmapi' if use_base else 'http://' + host + '/realms/cmapi',
                               'http://' + host if use_base else None, None)
        for status in (301, 302, 303, 307, 308):
            for method in ('GET', 'POST'):
                with self.subTest(status=status, method=method), server() as srv:
                    srv.redirect_status, srv.mode = status, 'redirect'
                    # Use a redirecting GET handler for either method.
                    with patch.object(Idp, 'do_POST', Idp.do_GET):
                        s = ol.Session(srv.issuer, None, None)
                        answer, _, _ = s.request(method, srv.issuer + '/auth', {'password': PASSWORD} if method == 'POST' else None)
                    self.assertEqual(answer, status)
                    self.assertEqual(len(srv.seen), 1)

    def test_C4_pkce_state_and_password_request_count(self):
        for _ in range(100):
            verifier, challenge = ol.pkce_pair()
            self.assertRegex(verifier, r'^[A-Za-z0-9._~-]{43,128}$')
            self.assertEqual(len(base64.urlsafe_b64decode(verifier)), 48)
            self.assertEqual(challenge, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
        with server() as srv:
            self.assertEqual(login(srv)['access_token'], TOKEN)
            bodies = [dict(urllib.parse.parse_qsl(b.decode())) for _, _, b, _ in srv.seen]
            self.assertEqual(sum('password' in b for b in bodies), 1)
            self.assertTrue(all(PASSWORD not in p for _, p, _, _ in srv.seen))
            self.assertEqual(bodies[-1]['redirect_uri'], srv.query['redirect_uri'])
            self.assertEqual(bodies[-1]['client_id'], srv.query['client_id'])
            self.assertEqual(bodies[-1]['code'], CODE)
            self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(bodies[-1]['code_verifier'].encode()).digest()).decode().rstrip('='), srv.query['code_challenge'])
            self.assertIn('KC_AUTH_SESSION_HASH=hash', srv.seen[1][3])
            self.assertIn('AUTH_SESSION_ID=signed.value.route', srv.seen[1][3])
            self.assertIn('KC_RESTART=restart', srv.seen[1][3])
        with server() as srv:
            srv.mode = 'state'
            with self.assertRaises(ol.LoginError):
                login(srv)
            self.assertFalse(any(p.endswith('/token') for _, p, _, _ in srv.seen))


if __name__ == '__main__':
    unittest.main()
```

## C3 — REFUTED: environment proxies bypass the loopback cleartext boundary (P1)

The TLS verification portions are correct: `head/deploy/oidc-login.py:88` uses `ssl.create_default_context(cafile=cacert)` for the supplied bundle, or the system context without it. There is no unverified context/flag. The shipped TLS stand-in passes with its CA, fails with another CA and with the system store, and sees no HTTP request for those failures. An additional executed context test (`report/test_tls_bundle.py`) generates one CA, inspects the actual HTTPSHandler context and confirms exactly one trusted certificate, CERT_REQUIRED and hostname checking. Thus the supplied bundle is not supplemented with system roots. The docstring's word "adds" at `:21` should be read as the CLI help's "instead of the system store" at `:166`.

`Session.__init__`, `:84`, compares parsed `target.hostname` with the exact strings `127.0.0.1`, `::1`, `localhost`. Tests confirm refusal of `localhost.evil.example`, `127.0.0.1.evil.example` and userinfo pointing to another host, for both an HTTP issuer and an HTTP base. A malformed bracket/userinfo URL raises ValueError before a request; it is not a bypass. An HTTP issuer on a remote host is rejected unless rewritten to a permitted base. An explicitly selected HTTPS base is trusted as the transport destination.

However `:89` builds urllib's default opener without overriding its environment-driven ProxyHandler:

```python
self.opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context))
```

A process with `http_proxy=http://<proxy-host>:<port>` and no matching `no_proxy` can send the supposed loopback HTTP password POST to that proxy across the network. The exact loopback-name check does not constrain the proxy connection. Executed regression: the base is `http://127.0.0.1:1` (not listening); the test proxy is a different ephemeral loopback listener, selected only by environment. It receives an absolute-form POST with body `password=private-password-181`. No connection to a remote proxy is needed to demonstrate that the destination can be selected this way. In deployment the proxy could be a non-loopback host. The same route can disclose cookies deliberately sent over HTTP to the base.

Fix: install `urllib.request.ProxyHandler({})` to disable implicit proxy use. The explicit `--base` facility already selects the desired route. This leaves TLS verification active.

Redirects: `_NoRedirect.redirect_request`, `:54-55`, returns `None`; `request()` catches HTTPError as an answer at `:103-104`. The added local-server tests exercise GET and POST independently for 301, 302, 303, 307 and 308. Every case returns the original status and records exactly one request. No redirect was followed, including no repeated password POST for 307/308.

Regression: `test_C3_loopback_http_does_not_use_environment_proxy` fails on head and passes with the fix below. The hostname and ten redirect controls pass on head. The full shared test is included below.

Full new file `report/fix_c3.py`:

```python
"""Keep the loopback HTTP exception from using a network proxy."""
from pathlib import Path
import sys


def apply(path):
    source = Path(path).read_text()
    old = 'urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context))'
    new = 'urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect, urllib.request.HTTPSHandler(context=context))'
    assert old in source
    Path(path).write_text(source.replace(old, new))


if __name__ == '__main__':
    apply(sys.argv[1])
```

Full new file `report/test_oidc_security.py`:

```python
"""No database/container; local stand-in regressions. OIDC_SCRIPT selects original/fixed helper."""
import base64
import contextlib
import hashlib
import html
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import threading
import unittest
import urllib.parse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get('OIDC_SCRIPT', ROOT / 'head/deploy/oidc-login.py'))
spec = importlib.util.spec_from_file_location('oidc_review', SCRIPT)
ol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ol)
PASSWORD = 'private-password-181'
CODE = 'private-code-181'
TOKEN = 'private-token-181'
REDIRECT = 'https://app.invalid/callback'


class Idp(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body='', headers=()):
        data = body.encode()
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.server.seen.append(('GET', self.path, b'', self.headers.get('Cookie')))
        self.server.query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
        if self.server.mode == 'redirect':
            return self.reply(self.server.redirect_status, headers=[('Location', self.server.origin + '/unexpected')])
        action = self.server.action or self.server.issuer + '/login-actions/authenticate?x=1&y=2'
        tag = self.server.raw_form or '<form id="kc-form-login" action="' + html.escape(action, quote=True) + '"></form>'
        self.reply(200, self.server.prefix + tag,
                   [('Set-Cookie', 'AUTH_SESSION_ID=signed.value.route; Path=/realms/cmapi/; Secure; HttpOnly'),
                    ('Set-Cookie', 'KC_AUTH_SESSION_HASH=hash; Path=/realms/cmapi/; Secure'),
                    ('Set-Cookie', 'KC_RESTART=restart; Path=/realms/cmapi/; Secure; HttpOnly')])

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.server.seen.append(('POST', self.path, body, self.headers.get('Cookie')))
        form = dict(urllib.parse.parse_qsl(body.decode()))
        if self.server.mode == 'proxy':
            return self.reply(400)
        if self.path.endswith('/token'):
            if self.server.mode == 'token-error':
                return self.reply(400, json.dumps({'error': 'invalid_grant', 'error_description': CODE + ' ' + TOKEN}))
            return self.reply(200, json.dumps({'access_token': TOKEN}))
        if self.server.mode in ('echo', 'echo-title'):
            text = html.escape(form['password'] + ' ' + CODE + ' ' + TOKEN)
            return self.reply(200, '<span id="input-error">' + text + '</span>' if self.server.mode == 'echo' else '<title>' + text + '</title>')
        state = self.server.query['state']
        if self.server.mode == 'state':
            state = 'wrong-state'
        if self.server.mode == 'redirect-error':
            location = REDIRECT + '?' + urllib.parse.urlencode({'state': state, 'error': 'access_denied', 'error_description': CODE + ' ' + TOKEN})
        elif self.server.mode == 'step':
            location = self.server.issuer + '/login-actions/' + CODE + '/' + TOKEN
        else:
            location = REDIRECT + '?' + urllib.parse.urlencode({'state': state, 'code': CODE})
        self.reply(302, headers=[('Location', location)])


@contextlib.contextmanager
def server():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Idp)
    srv.origin = 'http://127.0.0.1:' + str(srv.server_port)
    srv.issuer = srv.origin + '/realms/cmapi'
    srv.seen, srv.action, srv.prefix, srv.mode, srv.raw_form = [], None, '', 'normal', None
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join()


def login(srv, **kwargs):
    return ol.login(srv.issuer, 'public-app', REDIRECT, 'viewer', PASSWORD, **kwargs)


class SecurityTests(unittest.TestCase):
    def test_C1_no_response_secrets_in_cli_errors(self):
        for mode in ('echo', 'echo-title', 'token-error', 'redirect-error', 'step'):
            with self.subTest(mode=mode), server() as srv:
                srv.mode = mode
                out, err = io.StringIO(), io.StringIO()
                args = ['--issuer', srv.issuer, '--client-id', 'public-app', '--redirect-uri', REDIRECT, '--username', 'viewer']
                with patch('sys.stdin', io.StringIO(PASSWORD + '\n')), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = ol.main(args)
                self.assertEqual(rc, 1)
                self.assertEqual(out.getvalue(), '')
                for secret in (PASSWORD, CODE, TOKEN):
                    self.assertNotIn(secret, err.getvalue())

    def test_C2_dot_segments_get_no_password_or_cookies(self):
        for tail in ('../other/login-actions/authenticate', '%2e%2e/other/login-actions/authenticate',
                     '%252e%252e/other/login-actions/authenticate', 'x/../../other/login-actions/authenticate'):
            for use_base in (False, True):
                with self.subTest(tail=tail, base=use_base), server() as srv:
                    public = 'https://issuer.example/realms/cmapi' if use_base else srv.issuer
                    srv.action = public + '/' + tail
                    try:
                        ol.login(public, 'public-app', REDIRECT, 'viewer', PASSWORD, base=srv.origin if use_base else None)
                    except ol.LoginError:
                        pass
                    self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])

    def test_C2_foreign_hosts_ports_realms_and_second_forms(self):
        with server() as srv:
            for action in ('https://issuer.example.evil/realms/cmapi/login', 'https://issuer.example@evil.example/realms/cmapi/login',
                           'https://issuer.example:444/realms/cmapi/login', 'https://issuer.example/realms/other/login'):
                with self.subTest(action=action):
                    srv.seen.clear()
                    srv.action = action
                    with self.assertRaises(ol.LoginError):
                        ol.login('https://issuer.example/realms/cmapi', 'public-app', REDIRECT, 'viewer', PASSWORD, base=srv.origin)
                    self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])
            srv.action = None
            srv.prefix = '<form id="other-form" action="https://evil.example/login"></form>'
            self.assertEqual(login(srv)['access_token'], TOKEN)
            self.assertTrue(all(urllib.parse.urlsplit(p).hostname is None for _, p, _, _ in srv.seen))

    def test_C2_html_entities_and_action_quote_styles(self):
        for style in ("single", "none"):
            with self.subTest(style=style), server() as srv:
                action = srv.issuer + '/login-actions/authenticate'
                attr = "action='" + action + "'" if style == 'single' else 'action=' + action
                srv.raw_form = '<form id="kc-form-login" ' + attr + '></form>'
                with self.assertRaises(ol.LoginError):
                    login(srv)
                self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])
        with server() as srv:
            srv.raw_form = '<form id="kc-form-login" action="' + srv.issuer + '/&#46;&#46;/other/login-actions/authenticate"></form>'
            try:
                login(srv)
            except ol.LoginError:
                pass
            self.assertEqual([m for m, _, _, _ in srv.seen], ['GET'])

    def test_C3_loopback_http_does_not_use_environment_proxy(self):
        with server() as proxy:
            proxy.mode = 'proxy'
            # The intended --base is a different, closed loopback port. A proxy must receive nothing.
            env = {'http_proxy': proxy.origin, 'HTTP_PROXY': proxy.origin, 'no_proxy': '', 'NO_PROXY': ''}
            with patch.dict(os.environ, env, clear=True):
                session = ol.Session('https://issuer.example/realms/cmapi', 'http://127.0.0.1:1', None, timeout=1)
                try:
                    session.request('POST', session.issuer + '/login-actions/authenticate', {'password': PASSWORD})
                except ol.LoginError:
                    pass
            self.assertEqual(proxy.seen, [])

    def test_C3_http_host_checks_and_redirects(self):
        for host in ('localhost.evil.example', '127.0.0.1.evil.example', '127.0.0.1@evil.example', '[::1]@evil.example'):
            for use_base in (False, True):
                with self.subTest(host=host, base=use_base), self.assertRaises((ol.LoginError, ValueError)):
                    ol.Session('https://issuer.example/realms/cmapi' if use_base else 'http://' + host + '/realms/cmapi',
                               'http://' + host if use_base else None, None)
        for status in (301, 302, 303, 307, 308):
            for method in ('GET', 'POST'):
                with self.subTest(status=status, method=method), server() as srv:
                    srv.redirect_status, srv.mode = status, 'redirect'
                    # Use a redirecting GET handler for either method.
                    with patch.object(Idp, 'do_POST', Idp.do_GET):
                        s = ol.Session(srv.issuer, None, None)
                        answer, _, _ = s.request(method, srv.issuer + '/auth', {'password': PASSWORD} if method == 'POST' else None)
                    self.assertEqual(answer, status)
                    self.assertEqual(len(srv.seen), 1)

    def test_C4_pkce_state_and_password_request_count(self):
        for _ in range(100):
            verifier, challenge = ol.pkce_pair()
            self.assertRegex(verifier, r'^[A-Za-z0-9._~-]{43,128}$')
            self.assertEqual(len(base64.urlsafe_b64decode(verifier)), 48)
            self.assertEqual(challenge, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
        with server() as srv:
            self.assertEqual(login(srv)['access_token'], TOKEN)
            bodies = [dict(urllib.parse.parse_qsl(b.decode())) for _, _, b, _ in srv.seen]
            self.assertEqual(sum('password' in b for b in bodies), 1)
            self.assertTrue(all(PASSWORD not in p for _, p, _, _ in srv.seen))
            self.assertEqual(bodies[-1]['redirect_uri'], srv.query['redirect_uri'])
            self.assertEqual(bodies[-1]['client_id'], srv.query['client_id'])
            self.assertEqual(bodies[-1]['code'], CODE)
            self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(bodies[-1]['code_verifier'].encode()).digest()).decode().rstrip('='), srv.query['code_challenge'])
            self.assertIn('KC_AUTH_SESSION_HASH=hash', srv.seen[1][3])
            self.assertIn('AUTH_SESSION_ID=signed.value.route', srv.seen[1][3])
            self.assertIn('KC_RESTART=restart', srv.seen[1][3])
        with server() as srv:
            srv.mode = 'state'
            with self.assertRaises(ol.LoginError):
                login(srv)
            self.assertFalse(any(p.endswith('/token') for _, p, _, _ in srv.seen))


if __name__ == '__main__':
    unittest.main()
```

Full new file `report/test_tls_bundle.py`:

```python
"""Inspect the actual helper's HTTPS context; an explicit cafile must not add system roots."""
import importlib.util
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('oidc_tls_review', ROOT / 'head/deploy/oidc-login.py')
ol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ol)


class BundleTests(unittest.TestCase):
    def test_only_explicit_ca_is_trusted_and_verification_is_required(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'report') as work:
            ca, key = Path(work) / 'ca.pem', Path(work) / 'ca.key'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key), '-out', str(ca),
                            '-subj', '/CN=review-only-181-CA', '-days', '2', '-addext', 'basicConstraints=critical,CA:TRUE'],
                           check=True, capture_output=True)
            session = ol.Session('https://issuer.example/realms/cmapi', None, str(ca))
            handler = next(h for h in session.opener.handlers if isinstance(h, urllib.request.HTTPSHandler))
            context = handler._context
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            roots = context.get_ca_certs()
            self.assertEqual(len(roots), 1)
            self.assertIn((('commonName', 'review-only-181-CA'),), roots[0]['subject'])


if __name__ == '__main__':
    unittest.main()
```

## C4 — CONFIRMED: PKCE, state and code exchange

Evidence: `head/deploy/oidc-login.py:60` uses `secrets.token_bytes(48)` and unpadded URL-safe base64, giving 384 random bits and a 64-character verifier. This meets [RFC 7636 section 4.1](https://www.rfc-editor.org/rfc/rfc7636.html#section-4.1): 43–128 unreserved characters. `:61` computes `base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()`, the S256 transform required in [section 4.2](https://www.rfc-editor.org/rfc/rfc7636.html#section-4.2).

`:122` chooses a fresh 128-bit state; `:123-124` sends that state and `code_challenge_method: S256`. `:143-144`, `if answer.get("state") != state: raise LoginError(...)`, runs before the code is used. `:147-149` exchanges the code with the same `redirect_uri` and `client_id` arguments used at `:123`, and the original verifier. There is no password or client secret in that exchange.

Executed: the shipped TLS stand-in validates S256 and matching identifiers; the added `test_C4_pkce_state_and_password_request_count` checks 100 verifier/challenge pairs, records the successful exchange, and proves that mismatched state prevents any token request. These pass on head. The callback's `startswith(redirect_uri)` check is loose URL matching, but it never requests that callback and still requires the matching state before exchanging the code with the fixed token endpoint; it does not invalidate the specified C4 properties.

## C5 — CONFIRMED for the simple form flow; real deployment interoperability remains unrun

Evidence: `head/deploy/oidc-login.py:108-114` iterates `response.headers.get_all("Set-Cookie")`, keeps each name/value before `;`, and deletes an empty value or a cookie with `max-age=0`. `:100` sends the resulting name/value pairs together. Values containing `=` are preserved by `partition("=")`. A fresh Session exists for one login, so same-name cookies from multiple realms/paths are not needed for the supported flow. Cookie attributes are intentionally ignored and never sent as values.

Keycloak 26.6.4 [AuthenticationSessionManager.java, lines 92-102](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/managers/AuthenticationSessionManager.java#L92) resolves the child using `rootAuth.rootSession().getAuthenticationSession(client, tabId)`. Its lines 190-210 read `get(CookieType.AUTH_SESSION_ID)`, decode the sticky route and validate the signed root ID, then look that root up in the selected realm. [SessionCodeChecks.java, lines 154-174](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/resources/SessionCodeChecks.java#L154) selects the client/tab from the form action and checks the cookie against any auth-session parameter; later code validates `session_code` and execution. Sending the original cookie value is sufficient; the browser's Path/Domain/Secure metadata is not an input to those checks.

[CookieType.java, lines 17-29](https://github.com/keycloak/keycloak/blob/26.6.4/server-spi-private/src/main/java/org/keycloak/cookie/CookieType.java#L17) names `KC_RESTART`, `KC_AUTH_SESSION_HASH` and `AUTH_SESSION_ID`. The hash supports browser JavaScript session detection; it does not replace the root-session cookie. [SessionCodeChecks.java, lines 424-434](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/resources/SessionCodeChecks.java#L424) uses `RestartLoginCookie.getRestartCookie(session)` when restarting an expired/missing authentication session. The helper preserves all three independently. Their expiry/restart paths can require another page, at which point this deliberately single-form helper stops instead of completing an interactive flow.

Executed: the added stand-in sets three separate Secure cookies with the real names and checks their exact values on the form POST, including a signed-looking cookie with a route suffix. That passes over the intentional loopback HTTP base. The shipped TLS stand-in also proves cookie continuity. A real Keycloak run, clustered routing and custom authentication flows were not executed; end-to-end interoperability is PLAUSIBLE, not claimed as measured.

Sending every cookie to an explicitly selected `--base` inherently entrusts that base host with the cookies. Ordinary foreign form hosts are blocked (C2 controls); the C2 dot-segment bug can send them to another canonical realm path on that host, and the C3 proxy bug can expose them to another network host. Ignoring cookie metadata is acceptable only with the URL and direct-transport boundaries fixed; it does not itself provide host confinement.

## C6 — CONFIRMED for declared clients and the service-account import

Plain import evidence: `head/deploy/manifests/environments/crc/realm/10-realm-import.yaml:233,240,254,276,298,316,331,346,357` each state `directAccessGrantsEnabled: false` for all nine declared clients. `:310-317` makes automation confidential, disables standard flow and enables its service account. `:376-381` contains:

```yaml
- username: service-account-cmapi-automation
  enabled: true
  serviceAccountClientId: cmapi-automation
  clientRoles:
    cmapi-nonprod:
    - cmapi-onboarding
```

Helm evidence: `head/deploy/helm/cmapi/templates/keycloak-realm.yaml:129,137,147,157,169,178,189,196` state false for all eight declared clients; `:166-170` sets automation's secret, confidentiality and service-account flag. `:210-213` contains `serviceAccountClientId: cmapi-automation` and `clientRoles: { {{ $aud | quote }}: [cmapi-onboarding] }`.

The exact Helm command in the brief fails at `templates/trust.yaml:2` because the CRC values contain `trustedCA.certificates: ...PLACEHOLDER...`. Repeating it with the additional render-only `--set trustedCA.certificates=` succeeds. PyYAML parses every rendered document, including `clientRoles: { "cmapi-nonprod": [cmapi-onboarding] }`. Inspection of the parsed representation confirms the same automation flags and exactly `{'cmapi-nonprod': ['cmapi-onboarding']}`. No cluster is contacted by Helm template. The output is `report/helm-rendered.yaml` and contains only newly generated throwaway chart values, not deployment credentials.

Keycloak import interpretation is supported directly by 26.6.4 source. [DefaultExportImportManager.java, lines 1008-1026](https://github.com/keycloak/keycloak/blob/26.6.4/model/storage-private/src/main/java/org/keycloak/storage/datastore/DefaultExportImportManager.java#L1008) calls `createRoleMappings(userRep, user, newRealm);` then resolves `serviceAccountClientId` to the client and calls `user.setServiceAccountClientLink(client.getId());`. [RepresentationToModel.java, lines 839-845](https://github.com/keycloak/keycloak/blob/26.6.4/server-spi-private/src/main/java/org/keycloak/models/utils/RepresentationToModel.java#L839) resolves each `clientRoles` key as a client and invokes `createClientRoleMappings(client, user, entry.getValue());`. [RealmManager.java, lines 870-875](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/managers/RealmManager.java#L870) reuses an existing linked service user during post-import setup, creating one only if missing. Thus these entries describe the service users, not independent password users. This is the same mechanism as the two existing directory/admin entries.

Exactly means exactly the audience client's direct application-role mapping; it does not mean the user has no built-in realm defaults or account-management roles. Those are not additional cmapi audience permissions. The import declares no extra audience role for this service user.

For an ordinary newly imported client in the examined 26.6.4 JPA path, [ClientEntity.java, line 145](https://github.com/keycloak/keycloak/blob/26.6.4/model/jpa/src/main/java/org/keycloak/models/jpa/entities/ClientEntity.java#L145) declares `private boolean directAccessGrantsEnabled;`; [JpaRealmProvider.java, lines 895-900](https://github.com/keycloak/keycloak/blob/26.6.4/model/jpa/src/main/java/org/keycloak/models/jpa/JpaRealmProvider.java#L895) initializes standard flow but not that flag, and RepresentationToModel preserves the model flag if the representation omits it. This ordinary default must not be confused with generated `admin-cli`, which is explicitly enabled for direct grants by RealmManager. The Helm file omits that generated client: see the additional Helm finding. The claim about the explicitly declared clients and service-user role mapping is confirmed; the broader claim that a bare Helm import leaves no password client is false.

## C7 — REFUTED: one-page migration and a still-usable legacy user (P2)

Evidence: `head/cmapi/src/cmapi/tools/realm_sync.py:114` reads exactly one page, `rm.get("/clients", params={"max": 500})`. `:117-120` changes the returned full representation and PUTs it. It never asks for `first=500`; a realm with more than 500 clients can retain direct grants and can miss enabling automation entirely. [ClientsResource.java, lines 121-151](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/resources/admin/ClientsResource.java#L121) accepts both first/max and passes them into `realm.getClientsStream(firstResult, maxResults)`. This is real API pagination, not a limit ignored by Keycloak.

Executed regression `test_C7_all_clients_including_after_500`: a stateful admin-API model returns 502 clients with direct grants, puts automation on the last page, and implements those pagination parameters. Head changes 500 and leaves two on; the assertion fails. The fix iterates until an empty page, preserves full representations and is idempotent on a second run. The model also asserts unchanged secrets and unrelated attributes. This proves the sync's pagination defect, not a measured 502-client Keycloak deployment.

For clients actually visited, (b)-(e) are supported. `:282-283` calls `no_password_grant(rm)` before `service_roles(rm, audience)`; `:95` adds the automation/onboarding tuple, `:102` requests the service user, and `:103-106` grants only missing mappings. [ClientResource.java, lines 154-161](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/resources/admin/ClientResource.java#L154) runs `updateClientFromRep(rep, client, session);`. That method calls service-account setup before updating properties; [lines 867-872](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/resources/admin/ClientResource.java#L867) call `new ClientManager(new RealmManager(session)).enableServiceAccount(client);` when needed. [ClientManager.java, lines 160-170](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/managers/ClientManager.java#L160) creates an enabled user only when absent and sets `user.setServiceAccountClientLink(client.getId());`. The subsequent lookup is therefore valid. The small stateful migration test passes on head, including ordering, role assignment, a second run with no additional writes and no secret in output. A real Keycloak migration was not run.

Secrets are CLEAR in this list response on the examined 26.6.4 path, not masked. ClientsResource maps directly through ModelToRepresentation; [ModelToRepresentation.java, lines 896-902](https://github.com/keycloak/keycloak/blob/26.6.4/server-spi-private/src/main/java/org/keycloak/models/utils/ModelToRepresentation.java#L896) uses `rep.setSecret(clientModel.getSecret());` for confidential clients and null for public/bearer-only ones. [RepresentationToModel.determineNewSecret, lines 585-595](https://github.com/keycloak/keycloak/blob/26.6.4/server-spi-private/src/main/java/org/keycloak/models/utils/RepresentationToModel.java#L585) writes a provided secret unchanged; if omitted and a current one exists, it retains the current one. Thus the PUT sends the real unchanged secret back over the existing verified admin transport; it does not replace it with a mask. `realm_sync.py:122` prints only changed client names, and `:107` only names/roles, not representations. Keycloak's [AdminEventBuilder.java, lines 256-272](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/resources/admin/AdminEventBuilder.java#L256) calls `stripSecretsFromRepresentation(value);` before serialization; [StripSecretsUtils.java, lines 174-176](https://github.com/keycloak/keycloak/blob/26.6.4/server-spi-private/src/main/java/org/keycloak/models/utils/StripSecretsUtils.java#L174) masks ClientRepresentation.secret. No new secret disclosure in this PUT/log path was demonstrated. Omitting `secret` is optional hardening, not required for this fix.

The second defect is retirement. `realm_sync.py:261-263` deletes bot-user only inside `test_users()`, and `:286-287` calls that only for `CMAPI_REALM_TEST_USERS=true`. With the flag false, an old enabled bot-user, its password and its role survive. It loses the resource owner password grant, but it can still sign in through a public standard-flow client such as `cmapi-docs` (`10-realm-import.yaml:271-282`). Disabling a client's direct grant is not disabling the user. Keycloak's browser [AbstractUsernameFormAuthenticator.java, lines 216-224](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/authentication/authenticators/browser/AbstractUsernameFormAuthenticator.java#L216) validates the existing local password with `user.credentialManager().isValid(UserCredentialModel.password(password))`. There is no special rule for bot-user. Consequently the old password remains an alternate usable automation credential; the account is not safely inert. Existing issued tokens are also not revoked merely by changing a client grant.

Executed regression `test_C7_old_bot_is_retired_when_test_user_creation_is_off` drives the real `main()` with test-user creation off and a retained enabled legacy user; it fails because no deletion occurs. The fix retires the known obsolete local account outside that flag. Creation/reset of ola/amy/opal remains conditional. This is a migration change to retire the account, not a proposal to enable test-user creation in production. Sites intentionally retaining that username would need to decide its retirement explicitly.

The complete fix and stateful tests follow. Both failing tests pass after the fix; the already-passing small migration/idempotency test continues to pass.

Full new file `report/fix_c7.py`:

```python
"""Paginate the client list and retire the old bot independently of creating test users."""
from pathlib import Path
import sys


REPLACEMENT = '''def no_password_grant(rm: Realm) -> None:
    """Turn off the password grant throughout the existing realm, including later pages."""
    changed = []
    first = 0
    while True:
        clients = rm.get("/clients", params={"first": first, "max": 500}) or []
        if not clients:
            break
        for c in clients:
            want_service = c["clientId"] == "cmapi-automation"
            if c.get("directAccessGrantsEnabled") or (want_service and not c.get("serviceAccountsEnabled")):
                c["directAccessGrantsEnabled"] = False
                if want_service:
                    c["serviceAccountsEnabled"] = True
                rm.call("PUT", f"/clients/{c['id']}", json=c)
                changed.append(c["clientId"])
        first += len(clients)
    print(f"password grant: off on each client{' (changed: ' + ', '.join(sorted(changed)) + ')' if changed else ''}")


def retire_legacy_bot(rm: Realm) -> None:
    """Disabling a client grant does not disable an enabled local user's browser login."""
    for stale in rm.get("/users", params={"username": "bot-user", "exact": "true"}) or []:
        rm.call("DELETE", f"/users/{stale['id']}")
        print("test user bot-user: removed (the automation client signs in by its service account)")
'''


def apply(path):
    source = Path(path).read_text()
    start = source.index('def no_password_grant(')
    end = source.index('\n\ndef groups(', start)
    source = source[:start] + REPLACEMENT + source[end:]
    start = source.index('    # bot-user was a test user')
    end = source.index('    for username, first, middle, last, emp, memberships in TEST_USERS:', start)
    source = source[:start] + source[end:]
    source = source.replace('    no_password_grant(rm)\n', '    no_password_grant(rm)\n    retire_legacy_bot(rm)\n', 1)
    source = source.replace('and step 5 removes the local test account bot-user that signed in with it.',
                            'and retires the local account bot-user independently of test-user creation.')
    Path(path).write_text(source)


if __name__ == '__main__':
    apply(sys.argv[1])
```

Full new file `report/test_realm_sync_security.py`:

```python
"""Stateful admin API model; no HTTP, database, Keycloak or containers."""
import contextlib
import copy
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('SYNC_SCRIPT', ROOT / 'head/cmapi/src/cmapi/tools/realm_sync.py'))
spec = importlib.util.spec_from_file_location('rs_review', SOURCE)
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)
SECRET = 'unchanged-secret-181'


class RealmModel:
    def __init__(self, count=1):
        self.clients = [{'id': str(i), 'clientId': 'client-' + str(i), 'directAccessGrantsEnabled': True, 'secret': SECRET,
                         'serviceAccountsEnabled': False, 'publicClient': False, 'attributes': {'keep': 'unchanged'}} for i in range(count)]
        self.clients[-1]['clientId'] = 'cmapi-automation'
        self.writes = []
        self.bot = {'id': 'old-bot', 'username': 'bot-user', 'enabled': True, 'credentials': [{'type': 'password', 'value': 'old-password'}]}
        self.role = False
        self.sa = False

    def get(self, path, **kwargs):
        params = kwargs.get('params', {})
        if path == '/clients':
            if 'clientId' in params:
                name = params['clientId']
                if name in ('realm-management', 'audience'):
                    return [{'id': name, 'clientId': name}]
                return [copy.deepcopy(c) for c in self.clients if c['clientId'] == name]
            first = params.get('first', 0)
            return copy.deepcopy(self.clients[first:first + params.get('max', len(self.clients))])
        if path.endswith('/roles'):
            return [{'id': 'onboard', 'name': 'cmapi-onboarding'}]
        if path.endswith('/service-account-user'):
            assert self.sa, 'service account was requested before it was enabled'
            return {'id': 'sa'}
        if '/role-mappings/clients/' in path:
            return [{'id': 'onboard', 'name': 'cmapi-onboarding'}] if self.role else []
        if path == '/users':
            return [copy.deepcopy(self.bot)] if self.bot else []
        raise AssertionError(path)

    def call(self, method, path, **kwargs):
        data = kwargs.get('json')
        self.writes.append((method, path, copy.deepcopy(data)))
        if method == 'PUT' and path.startswith('/clients/'):
            client = next(c for c in self.clients if c['id'] == path.rsplit('/', 1)[1])
            client.update(copy.deepcopy(data))
            if client['clientId'] == 'cmapi-automation' and client['serviceAccountsEnabled']:
                self.sa = True  # ClientResource.updateClientServiceAccount / ClientManager.enableServiceAccount
        elif method == 'POST' and '/role-mappings/clients/' in path:
            self.role = True
        elif method == 'DELETE' and path == '/users/old-bot':
            self.bot = None
        else:
            raise AssertionError((method, path))


class SyncSecurityTests(unittest.TestCase):
    def test_C7_all_clients_including_after_500(self):
        realm = RealmModel(502)
        with contextlib.redirect_stdout(io.StringIO()):
            rs.no_password_grant(realm)
        self.assertTrue(all(not c['directAccessGrantsEnabled'] for c in realm.clients))
        self.assertTrue(realm.clients[-1]['serviceAccountsEnabled'])
        self.assertTrue(all(c['secret'] == SECRET and c['attributes'] == {'keep': 'unchanged'} for c in realm.clients))
        count = len(realm.writes)
        with contextlib.redirect_stdout(io.StringIO()):
            rs.no_password_grant(realm)
        self.assertEqual(len(realm.writes), count)

    def test_C7_small_migration_roles_order_idempotency_and_no_secret_output(self):
        realm = RealmModel()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rs.no_password_grant(realm)
            rs.service_roles(realm, 'audience')
            count = len(realm.writes)
            rs.no_password_grant(realm)
            rs.service_roles(realm, 'audience')
        self.assertTrue(realm.sa and realm.role)
        self.assertEqual(len(realm.writes), count)
        self.assertNotIn(SECRET, out.getvalue())
        self.assertEqual(realm.clients[0]['secret'], SECRET)
        self.assertEqual(realm.writes[0][0], 'PUT')
        self.assertEqual(realm.writes[0][2]['attributes'], {'keep': 'unchanged'})

    def test_C7_old_bot_is_retired_when_test_user_creation_is_off(self):
        realm = RealmModel()
        env = {'CMAPI_REALM_ISSUER': 'https://issuer.example/realms/cmapi', 'CMAPI_REALM_ADMIN_CLIENT_SECRET': SECRET,
               'CMAPI_REALM_TEST_USERS': 'false'}
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()):
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(rs, 'Realm', return_value=realm))
                for name in ('wait_for_realm', 'user_profile', 'service_roles', 'groups', 'ldap'):
                    stack.enter_context(patch.object(rs, name, return_value={}))
                rs.main([])
        self.assertIsNone(realm.bot, 'enabled bot-user and its password survive; browser authentication is still available')


if __name__ == '__main__':
    unittest.main()
```

## C8 — CONFIRMED for the identity change and the shipped approval policies

Evidence: `head/cmapi/src/cmapi/core/identity/claims.py:52-59` identifies `preferred_username.startswith("service-account-")`, strips that prefix for the username, sets kind to service and takes client_id from azp. `:54-65` takes exactly the audience client's roles. `core/identity/checks.py:73` is `automated = caller.kind == "service" or bool(set(automation_roles) & set(caller.roles))`. Both old bot-user with cmapi-onboarding and the new service user are automated under the shipped defaults. `:83-95` gives both the same employee-ID exemption, optional onBehalfOf lookup and requireOnBehalfOf behavior. A service user remains automated even with no automation role, but gets no application permissions merely from that classification.

Route authorization is by roles: `head/cmapi/src/cmapi/routers/__init__.py:45-48` invokes `c.cfg.roles.require(who, permission)`, and `core/authz.py:138-145` unions permissions from held roles, without branching on kind. `:21-33` gives onboarding viewer permissions plus namespaces:create and requests:cancel; no namespace change/delete, approval or admin permission is introduced. A source-wide search of identity-kind comparisons found only classification, recorded audit fields and the approval fact described below, not a service-specific route bypass. `core/ratelimit.py:57-62` takes caller/team keys and route kind, with no identity-kind input or special service exemption. This confirms absence of a new kind-specific exemption, not a claim that every defined limiter is wired to every route.

There IS a relevant fact difference: `head/cmapi/src/cmapi/core/pipeline.py:258` and `:304` set `requesterClient` to the client ID only for kind service; it was None for bot-user even though azp was cmapi-automation. `core/approvals.py:213-215` applies configured requester.clients filters to that fact. In `head/examples/instances/nonprod/approval-rules.yaml:60-100` the enabled policies have no client filter. The only client-filtered policy, `baseline-sa-grants`, is disabled at `:102` and allows only svc-payments-ci at `:112-114`. It does not admit cmapi-automation. The fact `automated` is available to threshold expressions (`core/expression.py:31`); both callers set it true. There is no shipped approval relaxation from switching the kind.

Audit data changes: `core/identity/checks.py:64-65` adds submittedByClient for a service submitting for someone else. This does not grant authority. Per-caller identity keys/subs change, naturally starting a different bucket; the rate policy itself has no service-specific allowance.

This is not an equivalence promise for arbitrary site policies. A custom requester.clients allowlist containing cmapi-automation would now match, and a site that intentionally removed onboarding from automationRoles treated the old user differently from a service. Those policy choices need review during migration. Under the files in this export, the identity switch does not widen permissions. The unrelated plugin-control removal below broadens configured writes for callers of either kind and should be fixed independently.

## C9 — CONFIRMED under the shipped realm's nonexistent-account premise

Evidence: `head/deploy/crc-proof.sh:80` submits `grant_type=password&client_id=cmapi-automation&username=no-such-account&password=not-a-password`, and includes the valid client secret through printf/stdin, not curl arguments. `:81` requires exact `unauthorized_client`; `invalid_grant` and `invalid_client` fail the proof. The secret was retrieved into a shell variable at `:74`; the printf here is a shell builtin, not an external process with the secret in argv. Curl receives data on stdin. `:75-77` likewise uses stdin/config input for client credentials and the bearer header.

Keycloak order: [TokenEndpoint.java, lines 130-165](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/endpoints/TokenEndpoint.java#L130) parses the form, validates the realm/grant and authenticates the client, then invokes `return grant.process(context);`. Parsing the form is not looking up the user. [ResourceOwnerPasswordCredentialsGrantType.java, lines 71-75](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/protocol/oidc/grants/ResourceOwnerPasswordCredentialsGrantType.java#L71) tests `if (!client.isDirectAccessGrantsEnabled())` and throws with `OAuthErrorException.UNAUTHORIZED_CLIENT` and BAD_REQUEST. The authentication flow is created and executed only later, at lines 97-117. Thus OFF returns HTTP 400 unauthorized_client before any username lookup or brute-force update.

With the grant ON and the standard direct-grant flow, [ValidateUsername.java, lines 78-82](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/authentication/authenticators/directgrant/ValidateUsername.java#L78) handles a missing user with `if (user == null)`, a dummy hash and HTTP 400 `invalid_grant`. It records USER_NOT_FOUND, with no real user on which to count a password failure. That cannot satisfy the proof's exact unauthorized_client check. The shipped users/LDAP identity table has no no-such-account.

This conclusion assumes the fixed name really is nonexistent, as the brief states. The script does not query to prove absence: on a modified realm containing an actual user named no-such-account and with the grant ON, that account could receive a failed attempt. That is not an observed defect on the provided realm. Omitting username/password altogether would avoid even that collision: the OFF check would still return unauthorized_client, while ON would reach ValidateUsername's missing-username invalid_request response. No real Keycloak endpoint or account was contacted here; the order/error conclusions come from the primary source.

## C10 — PLAUSIBLE: non-vacuous live tests, with a manifest-mutation limitation

The container test was read, never imported or run. It starts containers at module scope (`head/deploy/tests/realm-test.py:42-50`) and is incompatible with this review's constraints. The following are source-based expected outcomes, not measured live-test results.

The password loop at `:180-185` covers every client named in the realm input and the known generated clients. It supplies each confidential client's own secret, and the valid ola/rt-ola credentials. It requires HTTP 400/401 plus unauthorized_client/invalid_client and no access_token. A live client with an effective password grant, valid client authentication and valid user credentials would return 200; the check can fail. Disabled clients may instead return invalid_client, which is appropriate because they cannot sign in at all. This tests usability after the sync, not every flag in the import independently.

(a) If ONLY the import left directAccessGrantsEnabled true for cmapi-automation, these live checks can PASS: `:129` already runs `rs.main([])` twice before the loop, and the good sync switches that flag off. The client-credentials and role checks still pass. The loop therefore does not isolate an import regression. A separate actual static check DOES cover it: `head/cmapi/tests/service/test_plain_manifests.py:269-274` asserts `[c["clientId"] for c in realm["clients"] if c.get("directAccessGrantsEnabled") is not False] == []`. On that mutant it reports `['cmapi-automation'] != []`. This is distinct from claiming the live loop catches the bad input by itself.

(b) If the sync does not turn the grant off, the old-state block exposes it independently of the fresh import: `realm-test.py:198-200` enables direct grants, disables service accounts and creates a complete enabled bot-user with password rt-bot. `:201-202` first requires a real password token (200), establishing the positive control. `:204` reruns the sync; `:208-209` then uses the valid, unlocked ola password and requires HTTP 400 unauthorized_client. A sync leaving direct grants on returns 200 when otherwise repaired, so the assertion reports `after the sync the password grant is refused: 200 None` and records failure. If it also leaves service accounts disabled or crashes, `:204-206` and `:211-213` catch that separately. `:210` checks deletion of bot-user. In 26.6.4 ClientResource disables/removes the service account when the flag is false, so this also tests recreating the role mapping rather than only reusing a still-linked account.

`check()` at `:25-27` appends failures; the end of the file exits nonzero when that list is nonempty. Even though the docstring says "first wrong answer", many wrong assertions accumulate until final exit; they are not silently ignored. Runtime success, the old-state positive control and complete post-import/interoperability behavior remain PLAUSIBLE until a real isolated Keycloak test is run. The no-database stateful C7 tests prove the corresponding Python pagination, ordering and retirement behavior without pretending to execute this live test.

## Additional finding — REFUTED: a fresh Helm realm has no effective password client (P2)

This is a pre-existing Helm/plain-manifest mismatch that the SEC-06 guarantee now needs to close. `head/deploy/helm/cmapi/templates/keycloak-realm.yaml:122-198` defines eight clients and omits admin-cli; the plain import explicitly disables it at `10-realm-import.yaml:228-233`. The Helm comments at `:15` now promise that no client takes the password grant. The chart cannot establish that property on import alone.

Primary source: [RealmManager.java, lines 640-645](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/managers/RealmManager.java#L640) calls setupAdminCli when the representation has no admin-cli. [Lines 227-237](https://github.com/keycloak/keycloak/blob/26.6.4/services/src/main/java/org/keycloak/services/managers/RealmManager.java#L227) create that public client and explicitly run `adminCli.setEnabled(true);` and `adminCli.setDirectAccessGrantsEnabled(true);`. This special generated-client behavior differs from the ordinary new client's default flag. The good realm sync later disables it, but that leaves a window before sync completes and leaves it enabled when sync is disabled/fails. `head/deploy/helm/cmapi/values.yaml:81` defaults sync.enabled to false; enabling a realm import separately must not implicitly enable a password client.

Executed regression renders the real chart and asserts it overrides that generated client. It fails on head because admin-cli is absent. Adding the same disabled entry used by the plain manifest makes it pass. This is a render/source proof, not an executed Keycloak import. The proposed full fix and test follow; the static regression is enough to demonstrate the missing override and its correction.

Full new file `report/fix_extra_helm.py`:

```python
"""Match the plain manifest: explicitly disable the otherwise generated admin-cli."""
from pathlib import Path
import sys


def apply(chart):
    path = Path(chart) / 'templates/keycloak-realm.yaml'
    source = path.read_text()
    old = '    clients:\n      - clientId: {{ $aud }}'
    new = '''    clients:
      - clientId: admin-cli
        name: "Not used in this realm"
        enabled: false
        publicClient: true
        standardFlowEnabled: false
        directAccessGrantsEnabled: false
      - clientId: {{ $aud }}'''
    assert old in source
    path.write_text(source.replace(old, new, 1))


if __name__ == '__main__':
    apply(sys.argv[1])
```

Full new file `report/test_helm_admin_cli.py`:

```python
"""Render only; prove the realm import explicitly overrides Keycloak's generated admin-cli."""
import os
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = Path(os.environ.get('REVIEW_CHART', ROOT / 'head/deploy/helm/cmapi'))


class HelmAdminCliTests(unittest.TestCase):
    def test_import_disables_generated_password_client(self):
        args = ['/usr/local/bin/helm', 'template', 'cmapi', str(CHART), '-n', 'cmapi', '-f', str(ROOT / 'head/deploy/environments/crc.yaml'),
                '--set', 'cmapi.digest=sha256:' + 'a' * 64, '--set', 'trustedCA.certificates=']
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        docs = list(yaml.safe_load_all(result.stdout))
        realm = next(d for d in docs if d and d['kind'] == 'KeycloakRealmImport')['spec']['realm']
        admin = next((c for c in realm['clients'] if c['clientId'] == 'admin-cli'), None)
        self.assertIsNotNone(admin, 'Keycloak creates enabled admin-cli with direct grants unless the import overrides it')
        self.assertIs(admin['enabled'], False)
        self.assertIs(admin['directAccessGrantsEnabled'], False)


if __name__ == '__main__':
    unittest.main()
```

## Additional finding — REFUTED: the diff preserves configured plugin write restrictions (P1)

This security PR also removes the entire plugin switch, independently of the password-grant migration. A site can have `plugins.yaml` disabling namespace writes for nonprod/dev. The previous service refused create/change/delete there with 422 plugin-disabled; this head ignores the file and proceeds into backend work. Authentication and ordinary role checks remain, but an additional configured write restriction is silently lost. The exposure applies to authorized people and automation clients alike.

Evidence:

- `head/cmapi/src/cmapi/core/config.py:79-102` loads approvals/tiers/expiration/roles/metadata and returns InstanceConfig with no plugin configuration; the diff removes the plugins.yaml load and validation.
- `head/cmapi/src/cmapi/main.py:96` unconditionally mounts namespaces, tiers, directory and quotas: `authed_routers = (me.router, requests.router, admin.router, namespaces_router, tiers_router, directory_router, quotas_router)`.
- `head/cmapi/src/cmapi/core/pipeline.py:164-167` goes from environment/role checks straight to `cache = self.registry.cache(cluster_id)`; `:279-281` goes from role/requester resolution straight to reading Git on delete. The diff removes both `self.check_plugin_offered("namespaces", env)` calls and that method.
- `change.diff` deletes `cmapi/src/cmapi/core/plugins.py` entirely, removes PLUGIN_DISABLED, removes the admin plugin endpoint and deletes the plugin-switch tests. The removed module's contract expressly made an override stop writes while keeping reads. This is unrelated to SEC-06 and changes runtime behavior for already-supported configurations.

Executed regression loads the real nonprod configuration with a temporary plugins.yaml disabling namespaces in dev, constructs the real Pipeline without any database, and tries both create and delete. Backend stand-ins deliberately fail if touched. Head fails both subcases because it reaches the registry/Git rather than returning the configured 422; restoring the removed plugin-switch implementation returns 422 plugin-disabled before any backend read and the test passes. This is a test of a configured guard, not a speculative statement about all workloads or approval policies.

Fix: revert only the unrelated service plugin-switch removal, including its contract/sample/docs registry and its original tests. The script below reconstructs those exact base files from the supplied change.diff, verifies the head hunk contents before replacing them, and changes only an explicitly passed copy. It does not revert the SEC-06 identity or realm-sync changes. Full new fix and regression test text follow. The existing example/deployment documentation can be restored in the actual PR as a separate editorial step; the executed fix restores the runtime controls and API contract needed for the regression.

Full new file `report/fix_extra_plugins.py`:

```python
"""Undo only the service's unrelated plugin-switch removal using the supplied complete diff.

Usage: python report/fix_extra_plugins.py report/fixed-head change.diff
The target must be a copy of head. No Git repository or network is used.
"""
from pathlib import Path
import re
import sys

FILES = {
    'cmapi/contract/openapi.json',
    'cmapi/src/cmapi/contract/samples.json',
    'cmapi/src/cmapi/core/config.py',
    'cmapi/src/cmapi/core/docs.py',
    'cmapi/src/cmapi/core/observability.py',
    'cmapi/src/cmapi/core/pipeline.py',
    'cmapi/src/cmapi/core/plugins.py',
    'cmapi/src/cmapi/main.py',
    'cmapi/src/cmapi/plugins/namespaces/router.py',
    'cmapi/src/cmapi/routers/admin.py',
    'cmapi/tests/service/test_api_samples.py',
    'cmapi/tests/service/test_plugins_switch.py',
}


def restore(target, patch):
    target, patch = Path(target), Path(patch)
    sections = patch.read_text().split('diff --git ')[1:]
    seen = set()
    for section in sections:
        name = section.splitlines()[0].split(' b/', 1)[1]
        if name not in FILES:
            continue
        seen.add(name)
        path = target / name
        current = path.read_text().splitlines(keepends=True) if path.exists() else []
        restored, consumed = [], 0
        lines = section.splitlines(keepends=True)
        i = 0
        while i < len(lines):
            match = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', lines[i])
            if not match:
                i += 1
                continue
            start = max(int(match[1]) - 1, 0)
            restored.extend(current[consumed:start])
            consumed = start
            i += 1
            while i < len(lines) and not lines[i].startswith('@@ '):
                line = lines[i]
                if line.startswith((' ', '+')):
                    assert consumed < len(current) and current[consumed] == line[1:], (name, consumed)
                    consumed += 1
                if line.startswith((' ', '-')):
                    restored.append(line[1:])
                i += 1
        restored.extend(current[consumed:])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(restored))
    assert seen == FILES, FILES - seen


if __name__ == '__main__':
    restore(sys.argv[1], sys.argv[2])
```

Full new file `report/test_plugin_regression.py`:

```python
"""Exercise the write refusal before any backend; never constructs a database."""
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from cmapi.core.config import load_instance
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]


class Registry:
    def __init__(self):
        self.backend_reads = 0

    def writable(self, cluster):
        return SimpleNamespace(policy=SimpleNamespace(environment='dev'))

    def read_folder(self, path):
        self.backend_reads += 1
        raise AssertionError('disabled plugin reached Git')

    def cache(self, cluster):
        self.backend_reads += 1
        raise AssertionError('disabled plugin reached a backend')


class PluginRegressionTests(unittest.TestCase):
    def test_disabled_namespaces_refused_before_backend_for_create_and_delete(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'report') as work:
            config = Path(work)
            for path in (ROOT / 'head/examples/instances/nonprod').glob('*.yaml'):
                shutil.copy(path, config / path.name)
            (config / 'plugins.yaml').write_text('enabled: [namespaces, tiers, directory, quotas]\noverrides:\n  nonprod:\n    dev:\n      disabled: [namespaces]\n')
            cfg = load_instance(config, ROOT / 'head/examples/cluster-configs/policies/metadata-keys.yaml')
            who = Identity('bot', 'cmapi-automation', 'service', 'cmapi-automation', roles=frozenset({'cmapi-operator'}))
            registry = Registry()
            pipeline = Pipeline(cfg, registry, registry, None, None, None, [])
            for action in ('create', 'delete'):
                with self.subTest(action=action):
                    with self.assertRaises(Problem) as caught:
                        if action == 'create':
                            pipeline.plan_namespace(who, 'CRC', {'namespace': 'example-app'}, action='create')
                        else:
                            pipeline.plan_delete(who, 'CRC', 'example-app', if_match='etag')
                    self.assertEqual(caught.exception.status, 422)
                    self.assertEqual(caught.exception.code, 'plugin-disabled')
            self.assertEqual(registry.backend_reads, 0)


if __name__ == '__main__':
    unittest.main()
```

## Validation and proposed-file inventory

No container was started. No PostgreSQL connection was made, including none to 127.0.0.1:55432. Tests in report/ run as standalone unittest scripts, outside service conftest fixtures. The shipped realm container test and CRC cluster proof were not run. Source downloads were read-only primary Keycloak 26.6.4 sources and RFCs; local working copies are under report/keycloak-26.6.4/. No graph from another project was used.

The intended OAuth migration is appropriate: [RFC 9700 section 2.4](https://www.rfc-editor.org/rfc/rfc9700.html#section-2.4) says the resource owner password credentials grant `MUST NOT be used`. The report's findings concern the helper's defensive guarantees, complete migration and unrelated regressions, not a reason to retain that grant.

Executed results (all test secrets are synthetic):

| Check | Original head | Proposed fix |
| --- | --- | --- |
| Shipped TLS oidc-login-test.py | PASS, all cases | PASS with secret-safe diagnostic assertions updated by fix_c1_test_expectations.py |
| report/test_oidc_security.py | FAIL: 15 subcase assertions (7 methods) | PASS, 7 methods |
| report/test_realm_sync_security.py | FAIL: later client pages, legacy bot retirement; small migration passes | PASS, 3 tests |
| report/test_tls_bundle.py | PASS, one trusted CA and required verification | Unchanged TLS verification |
| report/test_helm_admin_cli.py | FAIL: missing admin-cli override | PASS |
| report/test_plugin_regression.py | FAIL: both configured write guards bypassed | PASS |
| Exact Helm command from brief | Stops at CRC CA placeholder | Render succeeds with render-only empty CA override |

Commands (run from this review folder):

```sh
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python head/deploy/tests/oidc-login-test.py
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/test_oidc_security.py
OIDC_SCRIPT=report/oidc-login.fixed.py /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/test_oidc_security.py
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/test_realm_sync_security.py
SYNC_SCRIPT=report/realm_sync.fixed.py /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/test_realm_sync_security.py
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/test_helm_admin_cli.py
REVIEW_CHART=report/fixed-head/deploy/helm/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/test_helm_admin_cli.py
PYTHONPATH=head/cmapi/src /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/test_plugin_regression.py
PYTHONPATH=report/fixed-head/cmapi/src /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/test_plugin_regression.py
```

Each C1, C2 and C3 fix was also applied independently to a fresh copy, and its corresponding regression methods passed (report/c1-independent.log, report/c2-independent.log, report/c3-independent.log). The combined fixes passed the shipped TLS stand-in with only the stated diagnostic-assertion update (report/fixed-standin.log).

Before/after logs: report/original-standin.log, report/oidc-before.log, report/oidc-after.log, report/sync-before.log, report/sync-after.log, report/helm-before.log, report/helm-after.log, report/plugins-before.log, report/plugins-after.log, report/tls-bundle.log. These are local test logs, not production logs. The full proposed new fix/test files are reproduced in their corresponding claim sections. oidc-login.fixed.py, realm_sync.fixed.py and fixed-head/ are generated review copies, not proposed new production modules; their changes are fully defined by the included fix programs. The production source files in head/ were not edited.

C1 deliberately removes arbitrary upstream diagnostics. The shipped stand-in's assertions that rejected foreign hosts are named in stderr are updated by the complete fix_c1_test_expectations.py file to expect the new constant rejection text; retaining those authorities would reintroduce an error-output channel. The added tests check confidentiality and actual request destinations instead. The exact stock wrong-password/required-action diagnostics needed by the proof are preserved safely by local constant messages.

Other changed secret paths were inspected: crc-proof.sh uses stdin for the client secret, password and bearer header; realm-test.py passes generated LDAP/local passwords in request bodies/in memory to the helper; deploy/secrets.sh and the Helm secret template stop creating new bot-user credentials. Keeping an already-existing cmapi-test-users Kubernetes Secret can retain its obsolete bot-user key (`deploy/secrets.sh:177-178`), but the key stays inside the existing Secret rather than becoming a new log/argument disclosure. Retiring the corresponding account as in C7 removes its authentication value. Realm YAML uses placeholders rather than literal deployment client secrets. No other new secret-in-log/argv/file finding was demonstrated in change.diff.

