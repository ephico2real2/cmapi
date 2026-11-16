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

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(os.environ.get('OIDC_SCRIPT', ROOT / 'deploy/oidc-login.py'))
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
