#!/usr/bin/env python3
"""deploy/tests/front-door-test.py: the front door's nginx configuration (cmapi-portal-ui/nginx/), run by nginx itself.

It renders the template as the image does at start (only the CMAPI_* names and NGINX_LOCAL_RESOLVERS, as
NGINX_ENVSUBST_FILTER says), runs "nginx -t" on it, then starts nginx in front of three stand-in API pods on 127.0.0.1
and measures each location: where it sends a request, the headers of the answer, what reaches the API, which requests
go to another pod after a failure, and what the access log keeps. It also runs 16-cmapi-check-env.envsh with good and
bad values.

    --nginx PATH     an nginx binary on this machine (1.30.6 is what the image runs)
    --image IMAGE    the cmapi-portal image, run by --engine (docker or podman) on the host network; Linux only. This also
                     runs the image's own entrypoint, envsubst and check script on "nginx -t", and lists the image's files.

The stand-ins replace the upstream's one "server ... resolve" line with three plain servers. The line as written is
checked by "nginx -t" first, and the test fails if the template no longer has exactly that one line.
Each nginx run and each request has a timeout; the whole run takes about 40 s.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "cmapi-portal-ui" / "nginx"
TEMPLATE = SRC / "templates" / "cmapi.conf.template"
ENV_FILTER = re.compile(r"^(CMAPI_|NGINX_LOCAL_RESOLVERS)")  # the Containerfile's NGINX_ENVSUBST_FILTER
PORTAL_HOST = "cmapi.apps-crc.testing"
MOCKUP_HOST = "cmapi-mockup.apps-crc.testing"
OIDC = "https://keycloak.apps-crc.testing"
GOOD_ENV = {
    "CMAPI_API_UPSTREAM": "cmapi-api-pods.cmapi.svc.cluster.local:8080",
    "CMAPI_PORTAL_HOST": PORTAL_HOST,
    "CMAPI_MOCKUP_HOST": MOCKUP_HOST,
    "CMAPI_OIDC_ORIGIN": OIDC,
    "NGINX_LOCAL_RESOLVERS": "127.0.0.1",
}
UPSTREAM_LINE = "server ${CMAPI_API_UPSTREAM} resolve max_fails=2 fail_timeout=10s;"
OWASP_PERMISSIONS = (
    "accelerometer=(), autoplay=(), camera=(), cross-origin-isolated=(), display-capture=(), encrypted-media=(), "
    "fullscreen=(), geolocation=(), gyroscope=(), keyboard-map=(), magnetometer=(), microphone=(), midi=(), payment=(), "
    "picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), sync-xhr=(self), usb=(), web-share=(), "
    "xr-spatial-tracking=(), clipboard-read=(), clipboard-write=(), gamepad=(), hid=(), idle-detection=(), "
    "interest-cohort=(), serial=(), unload=()")
COMMON = {
    "strict-transport-security": "max-age=63072000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-resource-policy": "same-origin",
    "x-permitted-cross-domain-policies": "none",
    "x-dns-prefetch-control": "off",
    "permissions-policy": OWASP_PERMISSIONS,
}
CSP_PORTAL = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self' data:; "
              f"connect-src 'self' {OIDC}; form-action 'self' {OIDC}; frame-src 'none'; frame-ancestors 'none'; "
              "base-uri 'self'; object-src 'none'")
CSP_DOCS = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            f"font-src 'self' data:; connect-src 'self' {OIDC}; worker-src 'self' blob:; form-action 'self' {OIDC}; "
            "frame-src 'none'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
CSP_API = "default-src 'none'; frame-ancestors 'none'"
CSP_MOCKUP = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
              "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data:; "
              "font-src 'self' data: https://fonts.gstatic.com; connect-src 'self'; form-action 'none'; frame-src 'none'; "
              "frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
TIMEOUT = 10

failures: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        failures.append(what)


def envsubst(text: str, env: dict[str, str]) -> str:
    """GNU envsubst with a SHELL-FORMAT list: $NAME and ${NAME} of the listed names only, the rest left as they are."""
    names = {k: v for k, v in env.items() if ENV_FILTER.search(k)}
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)",
                  lambda m: names.get(m.group(1) or m.group(2), m.group(0)), text)


# ---------------------------------------------------------------------------------------------------- the stand-in pods
class Pod:
    """One stand-in API pod. mode: ok, reset (reads the request, then closes with no answer), or 503."""

    def __init__(self, name: str, mode: str = "ok") -> None:
        self.name, self.mode = name, mode
        self.seen: list[dict] = []
        self.peers: set[int] = set()
        pod = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_a) -> None:
                pass

            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                pod.peers.add(self.client_address[1])
                pod.seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers.items()),
                                 "body": body.decode("utf-8", "replace")})
                failure = self.headers.get("X-Test-Failure") or pod.mode
                if failure == "timeout":
                    time.sleep(2)
                    self.close_connection = True
                    return
                if failure == "reset":
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                status = int(failure) if failure in ("502", "503", "504") else int(self.headers.get("X-Test-Status") or 200)
                out = json.dumps({"pod": pod.name, "path": self.path}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                if self.path.startswith("/openapi.json"):
                    self.send_header("Cache-Control", "no-cache")
                if self.headers.get("X-Test-Frame"):
                    self.send_header("X-Frame-Options", "SAMEORIGIN")
                if self.headers.get("X-Test-Security"):
                    for key in (*COMMON, "content-security-policy", "cross-origin-opener-policy"):
                        self.send_header(key, "attacker-value")
                self.end_headers()
                self.wfile.write(out)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_LOCK = _serve

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


# --------------------------------------------------------------------------------------------------------- nginx runs
class Nginx:
    def __init__(self, args: argparse.Namespace, work: Path) -> None:
        self.args, self.work = args, work

    def mime_types(self) -> str:
        if self.args.image:
            return "/etc/nginx/mime.types"
        return str(Path(self.args.nginx).resolve().parent.parent / "conf" / "mime.types")

    def command(self, conf: Path, *extra: str, name: str | None = None) -> list[str]:
        if self.args.image:
            # The runner's own user: the work folder is private to it (mkdtemp), and nginx writes its log and temp files there.
            run = [self.args.engine, "run", "--rm", "--network", "host", "--user", f"{os.getuid()}:{os.getgid()}",
                   "-v", f"{self.work}:{self.work}", "--entrypoint", "nginx"]
            if name:
                run += ["--name", name]
            return run + [self.args.image, "-e", "stderr", "-c", str(conf), *extra]
        return [self.args.nginx, "-e", "stderr", "-p", str(self.work), "-c", str(conf), *extra]

    def write(self, env: dict[str, str], port: int | None = None, servers: list[str] | None = None) -> Path:
        """The configuration as the image writes it, with absolute paths moved under the work folder. With servers
        (host:port), the upstream's resolve line becomes one plain server line each; with port, nginx listens there."""
        d = Path(tempfile.mkdtemp(dir=self.work))
        for sub in ("conf.d", "cmapi", "run"):
            (d / sub).mkdir()
        (d / "html").symlink_to(self.work / "html")
        site = envsubst(TEMPLATE.read_text(), env)
        if servers is not None:
            line = envsubst(UPSTREAM_LINE, env)
            if site.count(line) != 1:
                raise SystemExit(f"the template no longer has exactly one line '{UPSTREAM_LINE}'")
            site = site.replace(line, "\n    ".join(f"server {s} max_fails=2 fail_timeout=10s;" for s in servers))
        if port is not None:
            site = re.sub(r"listen 8080( default_server)?;", lambda m: f"listen 127.0.0.1:{port}{m.group(1) or ''};", site)

        def move(text: str) -> str:
            return (text.replace("/etc/nginx/cmapi/", f"{d}/cmapi/").replace("/etc/nginx/conf.d/", f"{d}/conf.d/")
                    .replace("/etc/nginx/mime.types", self.mime_types()).replace("/usr/share/nginx/html", f"{d}/html")
                    .replace("/dev/stdout", f"{d}/access.log").replace("/tmp/", f"{d}/run/"))

        (d / "conf.d" / "cmapi.conf").write_text(move(site))
        for f in (SRC / "cmapi").glob("*.conf"):
            (d / "cmapi" / f.name).write_text(move(f.read_text()))
        main = move((SRC / "nginx.conf").read_text())
        if port is not None:
            # One worker, as the image's autotune gives a pod with a CPU limit of one or less: each worker keeps its own
            # upstream connections, so the keepalive count below is only exact with one.
            if main.count("worker_processes auto;") != 1:
                raise SystemExit("nginx.conf no longer has exactly one 'worker_processes auto;'")
            main = main.replace("worker_processes auto;", "worker_processes 1;")
        (d / "nginx.conf").write_text(main)
        return d

    def test(self, d: Path) -> subprocess.CompletedProcess:
        return subprocess.run(self.command(d / "nginx.conf", "-t"), capture_output=True, text=True, timeout=60)

    def start(self, d: Path, port: int) -> subprocess.Popen:
        name = f"cmapi-front-door-test-{os.getpid()}-{port}" if self.args.image else None
        proc = subprocess.Popen(self.command(d / "nginx.conf", "-g", "daemon off;", name=name),
                                stdout=subprocess.DEVNULL, stderr=open(d / "error.log", "w"))
        proc.cmapi_name = name  # type: ignore[attr-defined]
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                return proc
            except OSError:
                if proc.poll() is not None:
                    raise SystemExit(f"nginx stopped: {(d / 'error.log').read_text()}")
                time.sleep(0.1)
        raise SystemExit("nginx did not listen within 10 s")

    def stop(self, proc: subprocess.Popen) -> None:
        if getattr(proc, "cmapi_name", None):
            subprocess.run([self.args.engine, "stop", "-t", "5", proc.cmapi_name], capture_output=True, timeout=30)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(port: int, method: str, path: str, host: str = PORTAL_HOST, headers: dict | None = None,
            body: bytes | None = None) -> tuple[int, dict[str, list[str]], bytes]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=TIMEOUT)
    try:
        c.request(method, path, body=body, headers={"Host": host, **(headers or {})})
        r = c.getresponse()
        got: dict[str, list[str]] = {}
        for k, v in r.getheaders():
            got.setdefault(k.lower(), []).append(v)
        return r.status, got, r.read()
    finally:
        c.close()


def one(headers: dict[str, list[str]], name: str) -> str | None:
    values = headers.get(name)
    return values[0] if values and len(values) == 1 else (None if not values else f"{len(values)} values: {values}")


def expect_headers(headers: dict[str, list[str]], want: dict[str, str | None], what: str) -> None:
    for name, value in want.items():
        got = one(headers, name)
        check(got == value, f"{what}: {name}" + ("" if got == value else f" is {value!r}, got {got!r}"))


def access_log(d: Path) -> list[dict]:
    p = d / "access.log"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []


# ----------------------------------------------------------------------------------------------------------- the cases
def site_files(work: Path) -> None:
    portal = work / "html" / "portal"
    (portal / "assets").mkdir(parents=True)
    (portal / "index.html").write_text("<!doctype html><title>portal index</title>")
    (portal / "config.json").write_text('{"instance": "nonprod"}')
    (portal / "assets" / "index-AbC123.js").write_text("console.log('portal');\n" * 200)
    (work / "html" / "mockup").mkdir(parents=True)
    (work / "html" / "mockup" / "portal.html").write_text("<!doctype html><title>mockup</title>")


def case_syntax(ng: Nginx) -> None:
    print("nginx -t on the template as the image renders it (the upstream's resolve line unchanged)")
    r = ng.test(ng.write(GOOD_ENV))
    check(r.returncode == 0, f"nginx -t passes ({(r.stderr or '').strip().splitlines()[-1:]})")
    r = ng.test(ng.write({**GOOD_ENV, "CMAPI_PORTAL_HOST": "cmapi.*", "CMAPI_MOCKUP_HOST": "cmapi-mockup.*"}))
    check(r.returncode == 0, f"nginx -t passes with the wildcard server names ({(r.stderr or '').strip().splitlines()[-1:]})")


def case_routes(ng: Nginx) -> None:
    print("routes, headers, forwarded values, the log")
    pods = [Pod("a"), Pod("b"), Pod("c")]
    port = free_port()
    d = ng.write(GOOD_ENV, port, [f"127.0.0.1:{p.port}" for p in pods])
    proc = ng.start(d, port)
    try:
        def where(path: str, host: str = PORTAL_HOST) -> str:
            before = sum(len(p.seen) for p in pods)
            status, _h, body = request(port, "GET", path, host)
            if sum(len(p.seen) for p in pods) > before:
                return "api"
            return f"static {status} {body[:40]!r}"

        for path in ("/api/v1/version", "/api/v1/requests?state=open&limit=5", "/openapi.json", "/openapi.yaml",
                     "/problems", "/problems/policy-violation", "/docs", "/docs/oauth2-redirect", "/docs/changelog",
                     "/redoc", "/static/swagger/swagger-ui-bundle.js", "/static/redoc/redoc.standalone.js"):
            check(where(path) == "api", f"{path} goes to the API")
        seen = [s["path"] for p in pods for s in p.seen]
        check("/api/v1/requests?state=open&limit=5" in seen, "the API gets the path and the query string unchanged")
        for path in ("/readyz", "/metrics", "/apifoo", "/static/other.js", "/docsfoo", "/openapi.json.bak"):
            got = where(path)
            check(got.startswith("static 200") and "portal index" in got, f"{path} is not proxied: the portal's page ({got})")
        check(where("/assets/missing-0.js").startswith("static 404"), "a missing asset is 404, not the page")
        status, h, body = request(port, "GET", "/healthz")
        check(status == 200 and body == b"ok\n", "/healthz answers ok")
        check(where("/", MOCKUP_HOST).startswith("static 200") and "mockup" in where("/", MOCKUP_HOST),
              "the mockup host serves portal.html at /")
        check(where("/api/v1/version", MOCKUP_HOST).startswith("static 404"), "the mockup host proxies nothing")
        check(where("/api/v1/version", "other.example") == "api", "an unknown host gets the instance's site (default_server)")

        # Headers, exactly, for each kind of answer.
        _s, h, _b = request(port, "GET", "/")
        expect_headers(h, {**COMMON, "content-security-policy": CSP_PORTAL, "cross-origin-opener-policy": "same-origin",
                           "cache-control": "no-cache", "server": "nginx"}, "the portal's page")
        _s, h, _b = request(port, "GET", "/config.json")
        expect_headers(h, {"cache-control": "no-cache", "content-security-policy": CSP_PORTAL,
                           "content-type": "application/json"}, "config.json")
        _s, h, _b = request(port, "GET", "/assets/index-AbC123.js", headers={"Accept-Encoding": "gzip"})
        expect_headers(h, {**COMMON, "cache-control": "public, max-age=31536000, immutable", "content-encoding": "gzip",
                           "content-security-policy": CSP_PORTAL}, "a hashed asset")
        _s, h, _b = request(port, "GET", "/api/v1/version", headers={"Accept-Encoding": "gzip"})
        expect_headers(h, {**COMMON, "content-security-policy": CSP_API, "cache-control": "no-store",
                           "cross-origin-opener-policy": None, "content-encoding": None}, "an API answer")
        _s, h, _b = request(port, "GET", "/openapi.json")
        expect_headers(h, {"cache-control": "no-cache", "content-security-policy": CSP_API},
                       "/openapi.json keeps the API's own Cache-Control")
        s401, h, _b = request(port, "GET", "/api/v1/me", headers={"X-Test-Status": "401"})
        check(s401 == 401, "an API 401 passes through")
        expect_headers(h, {**COMMON, "content-security-policy": CSP_API}, "an API 401")
        _s, h, _b = request(port, "GET", "/api/v1/version", headers={"X-Test-Frame": "1"})
        expect_headers(h, {"x-frame-options": "DENY"}, "an API header that the front door sets is sent once")
        _s, h, _b = request(port, "GET", "/docs")
        expect_headers(h, {**COMMON, "content-security-policy": CSP_DOCS, "cross-origin-opener-policy": None}, "/docs")
        _s, h, _b = request(port, "GET", "/", host=MOCKUP_HOST)
        expect_headers(h, {**COMMON, "content-security-policy": CSP_MOCKUP}, "the mockup")

        # What reaches the API.
        for p in pods:
            p.seen.clear()
        request(port, "GET", "/api/v1/version", headers={
            "X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.7", "X-Request-Id": "client-id.1_A",
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01", "Authorization": "Bearer SECRET-TOKEN"})
        got = next(s for p in pods for s in p.seen)["headers"]
        got = {k.lower(): v for k, v in got.items()}
        check(got.get("host") == PORTAL_HOST, f"the API gets the public Host ({got.get('host')})")
        check(got.get("x-forwarded-proto") == "https", "the API gets the router's X-Forwarded-Proto")
        check(got.get("x-forwarded-host") == PORTAL_HOST, "the API gets X-Forwarded-Host")
        check(got.get("x-forwarded-for") == "203.0.113.7, 127.0.0.1", f"X-Forwarded-For appends the peer ({got.get('x-forwarded-for')})")
        check(got.get("x-request-id") == "client-id.1_A", "a well-formed X-Request-Id is kept")
        check(got.get("traceparent", "").startswith("00-4bf92f35"), "traceparent reaches the API")
        check(got.get("authorization") == "Bearer SECRET-TOKEN", "the Authorization header reaches the API")
        check(got.get("connection") in (None, ""), f"no Connection header to the API, so keepalive is used ({got.get('connection')})")
        for p in pods:
            p.seen.clear()
        request(port, "GET", "/api/v1/version", headers={"X-Request-Id": "bad id with spaces"})
        rid = {k.lower(): v for k, v in next(s for p in pods for s in p.seen)["headers"].items()}.get("x-request-id", "")
        check(re.fullmatch(r"[0-9a-f]{32}", rid) is not None, f"a malformed X-Request-Id is replaced by nginx's ({rid})")
        request(port, "GET", "/api/v1/version", headers={"X-Forwarded-Proto": "gopher"})

        # Keepalive: sequential requests share upstream connections.
        for p in pods:
            p.peers.clear()
        for _ in range(12):
            request(port, "GET", "/api/v1/version")
        conns = sum(len(p.peers) for p in pods)
        check(conns <= len(pods), f"12 requests over {len(pods)} pods used {conns} upstream connections (keepalive)")

        # Size limit.
        before = sum(len(p.seen) for p in pods)
        status, _h, _b = request(port, "POST", "/api/v1/requests", body=b"x" * (2 * 1024 * 1024),
                                 headers={"Content-Type": "application/json"})
        check(status == 413 and sum(len(p.seen) for p in pods) == before, f"a 2 MiB body is refused with 413 ({status})")

        # The log: one JSON object for each request, no query string, no credential.
        request(port, "GET", "/?code=AUTHZ-CODE-SECRET&state=s1")
        time.sleep(0.3)
        log = access_log(d)
        raw = (d / "access.log").read_text()
        check(len(log) > 20 and all("request_id" in e and "status" in e for e in log), f"the access log is JSON ({len(log)} lines)")
        check("AUTHZ-CODE-SECRET" not in raw, "the authorization code in the query string is not logged")
        check("SECRET-TOKEN" not in raw, "the Authorization header is not logged")
        check(any(e["request_id"] == "client-id.1_A" and e["traceparent"].startswith("00-4bf92f35") for e in log),
              "the log has the request id and the traceparent")
        check(not any(e["uri"] == "/healthz" for e in log), "/healthz is not logged")
    finally:
        ng.stop(proc)
        for p in pods:
            p.stop()


def case_retries(ng: Nginx) -> None:
    print("another pod after a failure: GET yes, POST never")
    for method in ("GET", "POST"):
        bad, good = Pod("bad", "reset"), Pod("good")
        port = free_port()
        d = ng.write(GOOD_ENV, port, [f"127.0.0.1:{p.port}" for p in (bad, good)])
        proc = ng.start(d, port)
        try:
            results = [request(port, method, "/api/v1/requests", body=(f'{{"n": {i}}}'.encode() if method == "POST" else None),
                               headers={"Content-Type": "application/json"})[0] for i in range(6)]
            time.sleep(0.3)
            log = [e for e in access_log(d) if e["method"] == method]
            if method == "GET":
                check(all(s == 200 for s in results), f"every GET is answered 200 when one pod fails ({results})")
                check(any("," in e["upstream_addr"] for e in log), "a GET that failed on one pod went to the other (log)")
            else:
                bodies = [s["body"] for s in bad.seen + good.seen if s["method"] == "POST"]
                check(len(bodies) == 6 and len(set(bodies)) == 6, f"each POST reached exactly one pod ({len(bodies)} of 6)")
                check(502 in results, f"a POST that failed on a pod is answered 502, not sent again ({results})")
                check(not any("," in e["upstream_addr"] for e in log), "no POST went to a second pod (log)")
        finally:
            ng.stop(proc)
            bad.stop()
            good.stop()


def case_env_check() -> None:
    print("16-cmapi-check-env.envsh, sourced as the entrypoint does")
    script = SRC / "16-cmapi-check-env.envsh"

    def run(env: dict[str, str]) -> subprocess.CompletedProcess:
        clean = {"PATH": "/usr/bin:/bin", **env}
        return subprocess.run(["/bin/sh", "-c", f'. "{script}"; echo started'], env=clean, capture_output=True,
                              text=True, timeout=10)

    r = run(GOOD_ENV)
    check(r.returncode == 0 and "started" in r.stdout, f"good values start ({r.stderr.strip()})")
    r = run({**GOOD_ENV, "CMAPI_OIDC_ORIGIN": "https://keycloak.apps-crc.testing:8443"})
    check(r.returncode == 0, "an issuer origin with a port starts")
    r = run({**GOOD_ENV, "CMAPI_PORTAL_HOST": "cmapi.*", "CMAPI_MOCKUP_HOST": "cmapi-mockup.*"})
    check(r.returncode == 0, "the wildcard server names of a Route with no host start (the chart's default)")
    for name, value in (("CMAPI_API_UPSTREAM", ""), ("CMAPI_API_UPSTREAM", "cmapi-api-pods.cmapi.svc"),
                        ("CMAPI_API_UPSTREAM", "x:8080; include /etc/passwd"), ("CMAPI_PORTAL_HOST", ""),
                        ("CMAPI_PORTAL_HOST", "Cmapi.example"), ("CMAPI_PORTAL_HOST", "*.example"), ("CMAPI_PORTAL_HOST", "cmapi.*.x"),
                        ("CMAPI_MOCKUP_HOST", "a b"),
                        ("CMAPI_OIDC_ORIGIN", ""), ("CMAPI_OIDC_ORIGIN", "http://keycloak.example"),
                        ("CMAPI_OIDC_ORIGIN", "https://keycloak.example/realms/cmapi"),
                        ("CMAPI_OIDC_ORIGIN", "https://keycloak.example; script-src *"), ("NGINX_LOCAL_RESOLVERS", "")):
        r = run({**GOOD_ENV, name: value})
        check(r.returncode != 0 and name in r.stderr and "started" not in r.stdout, f"{name}={value!r} stops the start")


def case_image(args: argparse.Namespace) -> None:
    print(f"the image {args.image}: its own entrypoint, envsubst and check script, then nginx -T")
    # The image finds its own DNS server (15-local-resolvers.envsh), so NGINX_LOCAL_RESOLVERS is not passed.
    good = {k: v for k, v in GOOD_ENV.items() if k != "NGINX_LOCAL_RESOLVERS"}
    envs = [x for k, v in good.items() for x in ("-e", f"{k}={v}")]
    r = subprocess.run([args.engine, "run", "--rm", *envs, args.image, "nginx", "-T"], capture_output=True, text=True, timeout=120)
    check(r.returncode == 0, f"the image starts nginx -T with good values ({r.stderr.strip().splitlines()[-1:]})")
    dump = r.stdout
    files = re.findall(r"^# configuration file (\S+):", dump, re.M)
    check("/etc/nginx/conf.d/cmapi.conf" in files and "/etc/nginx/conf.d/default.conf" not in files,
          f"conf.d holds cmapi.conf only ({[f for f in files if 'conf.d' in f]})")
    check("${CMAPI_" not in dump and "${NGINX_" not in dump, "every value of the template was filled")
    check("$host" in dump and "$uri" in dump, "nginx's own variables are left as they are")
    check(re.search(r"^\s*resolver \S+ valid=5s;", dump, re.M) is not None, "the resolver is the pod's DNS server")
    bad = [x for k, v in {**good, "CMAPI_OIDC_ORIGIN": "http://keycloak.example"}.items() for x in ("-e", f"{k}={v}")]
    r = subprocess.run([args.engine, "run", "--rm", *bad, args.image, "nginx", "-t"],
                       capture_output=True, text=True, timeout=120)
    check(r.returncode != 0 and "CMAPI_OIDC_ORIGIN" in (r.stdout + r.stderr), "a bad value stops the image's start")
    r = subprocess.run([args.engine, "run", "--rm", "--entrypoint", "sh", args.image, "-c",
                        "test -f /usr/share/nginx/html/portal/index.html && test -f /usr/share/nginx/html/mockup/portal.html"
                        " && ls /usr/share/nginx/html/portal/assets | grep -q . && id -u"],
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0 and r.stdout.strip() == "101", f"the image holds the portal and the mockup, user 101 ({r.stdout.strip()})")


def render(args: argparse.Namespace) -> int:
    """Writes a configuration for another test (cmapi-portal-ui/tests/front-door.test.mjs) and prints, as JSON, the
    command that runs nginx on it in the foreground. The folder holds html/portal and html/mockup for that test to fill."""
    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    (out / "html").mkdir(parents=True, exist_ok=True)
    env = {"CMAPI_API_UPSTREAM": "standin.invalid:1", "CMAPI_PORTAL_HOST": args.portal_host,
           "CMAPI_MOCKUP_HOST": args.mockup_host, "CMAPI_OIDC_ORIGIN": args.oidc_origin, "NGINX_LOCAL_RESOLVERS": "127.0.0.1"}
    ng = Nginx(args, out)
    d = ng.write(env, args.listen, [args.upstream])
    r = ng.test(d)
    if r.returncode != 0:
        raise SystemExit(f"nginx -t failed: {r.stderr}")
    print(json.dumps({"command": ng.command(d / "nginx.conf", "-g", "daemon off;"), "html": str(out / "html"),
                      "accessLog": str(d / "access.log")}))
    return 0



def case_review_env_single_line() -> None:
    print("review C5: full environment values and the entrypoint pipeline")
    script = SRC / "16-cmapi-check-env.envsh"
    for name in ("CMAPI_API_UPSTREAM", "CMAPI_PORTAL_HOST", "CMAPI_MOCKUP_HOST", "CMAPI_OIDC_ORIGIN"):
        for suffix in ("\n; location = /injected { return 200 injected; } #", "\ninclude /tmp/attacker.conf; #", "\n"):
            value = GOOD_ENV[name] + suffix
            r = subprocess.run(["/bin/sh", "-c", '. "$1"; echo started', "review", str(script)],
                               env={"PATH": "/usr/bin:/bin", **GOOD_ENV, name: value},
                               capture_output=True, text=True, timeout=10)
            check(r.returncode != 0 and "started" not in r.stdout,
                  f"{name}: rejects multiline suffix {suffix!r}")
        for suffix in (";", "{", '"', "'", " ", "$host", " include /tmp/attacker.conf", "*", ".*.evil"):
            r = subprocess.run(["/bin/sh", "-c", '. "$1"; echo started', "review", str(script)],
                               env={"PATH": "/usr/bin:/bin", **GOOD_ENV, name: GOOD_ENV[name] + suffix},
                               capture_output=True, text=True, timeout=10)
            check(r.returncode != 0 and "started" not in r.stdout,
                  f"{name}: rejects suffix {suffix!r}")
    # Same last-stage while pipeline and set -e as the image, with a harmless stand-in for envsubst/nginx.
    pipeline = """set -e
find "$1" -type f -print | sort -V | while read -r f; do
  case "$f" in
    *.envsh) . "$f" ;;
    *.sh) "$f" ;;
  esac
done
echo nginx-started
"""
    with tempfile.TemporaryDirectory(prefix="entrypoint-review-") as tmp:
        scripts = Path(tmp)
        shutil.copy2(script, scripts / script.name)
        later = scripts / "20-envsubst-on-templates.sh"
        later.write_text("#!/bin/sh\necho envsubst-ran\n")
        later.chmod(0o755)
        for value, allowed in ((PORTAL_HOST, True), ("bad host", False),
                               (PORTAL_HOST + "\n; location = /injected { return 200 injected; } #", False)):
            r = subprocess.run(["/bin/sh", "-c", pipeline, "review", str(scripts)],
                               env={"PATH": "/usr/bin:/bin", **GOOD_ENV, "CMAPI_PORTAL_HOST": value},
                               capture_output=True, text=True, timeout=10)
            check((r.returncode == 0 and "envsubst-ran" in r.stdout and "nginx-started" in r.stdout) if allowed else
                  (r.returncode != 0 and "envsubst-ran" not in r.stdout and "nginx-started" not in r.stdout),
                  f"entrypoint pipeline permits valid values only: {value!r}")


def case_review_error_headers(ng: Nginx) -> None:
    print("review C2: health, early errors, static and upstream errors")
    pod = Pod("headers")
    port = free_port()
    d = ng.write(GOOD_ENV, port, [f"127.0.0.1:{pod.port}"])
    # Speed up the 504 only; keep the shipped header hierarchy.
    conf = d / "cmapi" / "proxy-api.conf"
    conf.write_text(conf.read_text().replace("proxy_read_timeout 60s;", "proxy_read_timeout 1s;"))
    proc = ng.start(d, port)
    try:
        for host, csp in ((PORTAL_HOST, CSP_PORTAL), (MOCKUP_HOST, CSP_MOCKUP)):
            status, headers, _ = request(port, "GET", "/healthz", host)
            check(status == 200, f"health status {host}")
            expect_headers(headers, {**COMMON, "content-security-policy": csp}, f"health {host}")
        # Bad escapes can be rejected before Host is parsed: use the default server's policy.
        status, headers, _ = request(port, "GET", "/%00")
        check(status == 400, "bad escape status on default server")
        expect_headers(headers, {**COMMON, "content-security-policy": CSP_PORTAL}, "early 400")
        for status_want, path, kwargs in (
            (404, "/assets/missing.js", {}),
            (413, "/api/v1/requests", {"method": "POST", "body": b"x" * (2 * 1024 * 1024)}),
            (401, "/api/v1/me", {"headers": {"X-Test-Status": "401"}}),
            (500, "/api/v1/version", {"headers": {"X-Test-Status": "500"}}),
            (502, "/api/v1/version", {"headers": {"X-Test-Failure": "reset"}}),
            (504, "/api/v1/version", {"headers": {"X-Test-Failure": "timeout"}}),
        ):
            method = kwargs.pop("method", "GET")
            status, headers, _ = request(port, method, path, **kwargs)
            check(status == status_want, f"expected status {status_want}, got {status}")
            expect_headers(headers, COMMON, f"status {status_want}")
        for path, csp in (("/api/v1/version", CSP_API), ("/docs", CSP_DOCS)):
            _, headers, _ = request(port, "GET", path, headers={"X-Test-Security": "1"})
            expect_headers(headers, {**COMMON, "content-security-policy": csp}, "upstream security values hidden")
    finally:
        ng.stop(proc)
        pod.stop()


def case_review_retry_matrix(ng: Nginx) -> None:
    print("review C3: reset, read timeout, 502/503/504 across all method classes")
    for failure in ("reset", "timeout", "502", "503", "504"):
        for method in ("GET", "POST", "PATCH", "LOCK", "DELETE", "PUT"):
            bad, good = Pod("bad", failure), Pod("good")
            port = free_port()
            d = ng.write(GOOD_ENV, port, [f"127.0.0.1:{p.port}" for p in (bad, good)])
            # A 1 s read timeout with the same 1:6 ratio to the retry budget makes this bounded.
            for file in (d / "cmapi").glob("*.conf"):
                text = file.read_text().replace("proxy_read_timeout 60s;", "proxy_read_timeout 1s;")
                text = text.replace("proxy_next_upstream_timeout 10s;", "proxy_next_upstream_timeout 150ms;")
                file.write_text(text)
            proc = ng.start(d, port)
            try:
                tag = f"/api/v1/version?case={failure}-{method}"
                status, _, _ = request(port, method, tag, body=b"{}")
                bad_seen = [s for s in bad.seen if s["path"] == tag]
                good_seen = [s for s in good.seen if s["path"] == tag]
                retryable = method in ("GET", "DELETE", "PUT")
                check(len(bad_seen) == 1 and len(good_seen) == int(retryable) and
                      ((status == 200) == retryable), f"{method} after {failure}: status={status}, "
                      f"bad={len(bad_seen)}, good={len(good_seen)}")
            finally:
                ng.stop(proc)
                bad.stop()
                good.stop()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--nginx")
    g.add_argument("--image")
    ap.add_argument("--engine", default="docker")
    sub = ap.add_subparsers(dest="mode")
    r = sub.add_parser("render", help="write a configuration for the browser test and print the command that runs it")
    r.add_argument("--out", required=True)
    r.add_argument("--listen", type=int, required=True)
    r.add_argument("--upstream", required=True, help="host:port of the stand-in API")
    r.add_argument("--oidc-origin", required=True)
    r.add_argument("--portal-host", required=True)
    r.add_argument("--mockup-host", required=True)
    args = ap.parse_args()
    if args.nginx and not shutil.which(args.nginx):
        raise SystemExit(f"no nginx at {args.nginx}")
    if args.mode == "render":
        return render(args)
    with tempfile.TemporaryDirectory(prefix="front-door-") as tmp:
        work = Path(tmp).resolve()
        site_files(work)
        ng = Nginx(args, work)
        case_syntax(ng)
        case_routes(ng)
        case_retries(ng)
        case_env_check()
        case_review_env_single_line()
        case_review_error_headers(ng)
        case_review_retry_matrix(ng)
        if args.image:
            case_image(args)
    print(f"front door cases failed: {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
