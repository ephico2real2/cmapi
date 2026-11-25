#!/usr/bin/env python3
"""Each download of CI and of the cmapi image survives one transient answer (#609).

Every curl download of the workflows, of cmapi/Containerfile and of the two scripts that fetch CNPG is run, with its own
flags, against a local server that answers 503 to the first request for each path and the file after. The download must
then exit 0 with the file's bytes. Before #609 the flags had no `--retry`, so curl stopped at the 503 with exit 22, as a
GitHub 503 stopped images-pr on PR #608 (run 45248911791). curl's manual, `--retry`: a transient error is "a timeout, an
FTP 4xx response code or an HTTP 408, 429, 500, 502, 503, 504, 522 or 524 response code".

A curl is a probe, not a download, when it writes the status code (-w), throws the body away (-o /dev/null) or is read
into a variable ($(curl ...)). Any other curl in these files must read as one of the two forms below, or the test fails
and names the line: a download it cannot read is not one it may skip.

The base images of every image build survive the same (#663). docker/build-push-action's BuildKit pulled
registry.access.redhat.com's UBI itself and stopped at one 401 from registry.redhat.io's anonymous token endpoint (PR #659, run
45492928616); BuildKit retries a 5xx, not a 4xx. Each command of ci.yml that runs deploy/base-images.py is run, with its own
--platform, --attempts and --delay, against a stub registry whose token endpoint answers 401 to the first two requests. It
must exit 0 with each FROM image in its layout, every blob under its own SHA-256, and print one build context per image. The
same command must fail when every attempt is refused, when a blob or manifest is not the pinned digest, and when a FROM is
not pinned by digest. Before #663 ci.yml ran no such command, so this part fails and names the gap.

Python standard library, and the curl and skopeo on PATH. usage: download-retry-test.py. Exit 1 on any failure.
"""
import gzip
import hashlib
import http.server
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILES = [".github/workflows/ci.yml", ".github/workflows/api-contract-report.yml", "cmapi/Containerfile",
         "examples/cluster-configs/.github/workflows/ci.yml",
         # The CNPG manifest: kind-test-stubbed.sh fetches it in the manifests job, kind-test.sh on a real kind run.
         "deploy/kind-test.sh", "deploy/tests/kind-test-stubbed.sh"]
BODY = b"the downloaded file\n"
# A download, on one line: curl, its flags, then `-o <file> <url>` or `<url> -o <file>`.
DOWNLOAD = re.compile(r"\bcurl((?:\s+(?!-o\s)-[-\w]+(?:\s+\d+)?)*)\s+(?:-o\s+\S+\s+(?P<url>\S+)|(?P<url_first>\S.*?)\s+-o\s+\S+)")
PROBE = re.compile(r"\s-w\s|-o\s+/dev/null\b|\$\(\s*curl\b")


class FlakyOnce(http.server.BaseHTTPRequestHandler):
    """503 to the first GET of each path, then the file: one transient failure, as GitHub's releases answered."""
    seen: set = set()

    def do_GET(self):
        first = self.path not in self.seen
        self.seen.add(self.path)
        self.send_response(503 if first else 200)
        body = b"busy\n" if first else BODY
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def downloads():
    for rel in FILES:
        for n, line in enumerate(open(os.path.join(ROOT, rel)), 1):
            if line.lstrip().startswith("#") or not re.search(r"\bcurl\s", line) or PROBE.search(line):
                continue
            m = DOWNLOAD.search(line)
            url = m and (m["url"] or m["url_first"])
            if not url or url.startswith("-"):
                raise SystemExit(f"  FAIL {rel}:{n}: a curl download this test cannot read: {line.strip()}")
            yield f"{rel}:{n}", shlex.split(m.group(1)), url


# The base images (#663): the step that fetches them, as ci.yml writes it: contexts=$(python3 deploy/base-images.py ...).
BASE_STEP = re.compile(r"\$\(\s*python3?\s+deploy/base-images\.py\s+(?P<args>[^)]*)\)")
TOKEN_FAILURES = 2
OCI_INDEX, OCI_MANIFEST = "application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json"
V2S2 = "application/vnd.docker.distribution.manifest.v2+json"


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class StubRegistry(http.server.BaseHTTPRequestHandler):
    """A registry behind a bearer token, as registry.access.redhat.com sent buildx to registry.redhat.io for one. The token
    endpoint answers 401 to the first `token_failures` requests, then gives a token; content needs the token."""
    content: dict = {}           # "/v2/<name>/manifests/<digest>" or ".../blobs/<digest>" -> (media type, bytes)
    token_failures = 0
    token_requests = 0
    requested: list = []
    lock = threading.Lock()

    def do_GET(self):
        self.answer(with_body=True)

    def do_HEAD(self):
        self.answer(with_body=False)

    def answer(self, with_body: bool):
        cls, path = type(self), self.path.split("?", 1)[0]
        if path == "/token":
            with cls.lock:
                cls.token_requests += 1
                refused = cls.token_requests <= cls.token_failures
            if refused:
                return self.reply(401, "application/json", b'{"errors":[{"code":"UNAUTHORIZED"}]}\n', with_body)
            return self.reply(200, "application/json", b'{"token":"stub","access_token":"stub"}', with_body)
        if self.headers.get("Authorization") != "Bearer stub":
            realm = f"http://127.0.0.1:{self.server.server_port}/token"
            return self.reply(401, "application/json", b'{"errors":[{"code":"UNAUTHORIZED"}]}\n', with_body,
                              {"WWW-Authenticate": f'Bearer realm="{realm}",service="stub"'})
        if path == "/v2/":
            return self.reply(200, "application/json", b"{}", with_body)
        with cls.lock:
            cls.requested.append(path)
        if path not in cls.content:
            return self.reply(404, "application/json", b'{"errors":[{"code":"BLOB_UNKNOWN"}]}\n', with_body)
        kind, data = cls.content[path]
        self.reply(200, kind, data, with_body, {"Docker-Content-Digest": path.rsplit("/", 1)[1]})

    def reply(self, status, kind, data, with_body, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if with_body:
            self.wfile.write(data)

    def log_message(self, *_):
        pass


def stub_image(name: str, kind: str, payload: bytes) -> tuple[str, list]:
    """One linux/amd64 image of one gzipped layer: its manifest digest and its content entries."""
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w") as t:
        info = tarfile.TarInfo("etc/stub")
        info.size = len(payload)
        t.addfile(info, io.BytesIO(payload))
    layer = gzip.compress(tar.getvalue(), mtime=0)
    config = json.dumps({"architecture": "amd64", "os": "linux",
                         "rootfs": {"type": "layers", "diff_ids": [digest_of(tar.getvalue())]}}).encode()
    docker = kind == V2S2
    manifest = json.dumps({"schemaVersion": 2, "mediaType": kind,
                           "config": {"mediaType": "application/vnd.docker.container.image.v1+json" if docker
                                      else "application/vnd.oci.image.config.v1+json",
                                      "digest": digest_of(config), "size": len(config)},
                           "layers": [{"mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip" if docker
                                       else "application/vnd.oci.image.layer.v1.tar+gzip",
                                       "digest": digest_of(layer), "size": len(layer)}]}).encode()
    entries = [(f"/v2/{name}/blobs/{digest_of(config)}", ("application/octet-stream", config)),
               (f"/v2/{name}/blobs/{digest_of(layer)}", ("application/octet-stream", layer)),
               (f"/v2/{name}/manifests/{digest_of(manifest)}", (kind, manifest))]
    return digest_of(manifest), entries


def stub_content():
    """ubi: one Docker v2s2 manifest, as the UBI base is. node: an OCI index of linux/amd64, linux/arm64 and an attestation,
    as the docker.io bases are, where only the amd64 image is served."""
    ubi, content = stub_image("ubi", V2S2, b"ubi\n")
    amd64, node = stub_image("node", OCI_MANIFEST, b"node amd64\n")
    content += node
    arm64 = digest_of(b"the arm64 manifest, never served")
    index = json.dumps({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [
        {"mediaType": OCI_MANIFEST, "digest": amd64, "size": len(dict(node)[f"/v2/node/manifests/{amd64}"][1]),
         "platform": {"os": "linux", "architecture": "amd64"}},
        {"mediaType": OCI_MANIFEST, "digest": arm64, "size": 100, "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
        {"mediaType": OCI_MANIFEST, "digest": digest_of(b"an attestation"), "size": 100,
         "platform": {"os": "unknown", "architecture": "unknown"}}]}).encode()
    content.append((f"/v2/node/manifests/{digest_of(index)}", (OCI_INDEX, index)))
    return dict(content), ubi, digest_of(index), arm64


def base_commands():
    """Each distinct base-images.py command of ci.yml, as (line, its flags)."""
    found = {}
    for n, line in enumerate(open(os.path.join(ROOT, ".github/workflows/ci.yml")), 1):
        if line.lstrip().startswith("#") or "deploy/base-images.py" not in line:
            continue
        m = BASE_STEP.search(line)
        args = shlex.split(m["args"]) if m else []
        flags = dict(zip(args[::2], args[1::2]))
        if not m or len(args) % 2 or not {"--containerfile", "--layout", "--platform", "--attempts", "--delay"} <= set(flags):
            raise SystemExit(f"  FAIL .github/workflows/ci.yml:{n}: a base-images.py command this test cannot read: {line.strip()}")
        found.setdefault(m["args"], (f".github/workflows/ci.yml:{n}", flags))
    return list(found.values())


def run_base(flags: dict, containerfile: str, layout: str, env: dict, **override):
    argv = [sys.executable, os.path.join(ROOT, "deploy/base-images.py")]
    for k, v in {**flags, "--containerfile": containerfile, "--layout": layout, **override}.items():
        argv += [k, v]
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=600)


def layout_ok(layout: str) -> bool:
    blobs = os.path.join(layout, "blobs", "sha256")
    return all(digest_of(open(os.path.join(blobs, b), "rb").read()) == "sha256:" + b for b in os.listdir(blobs))


def base_images_case() -> list:
    fails = []

    def check(ok, label):
        print(("  ok   " if ok else "  FAIL ") + label)
        if not ok:
            fails.append(label)

    commands = base_commands()
    check(bool(commands), "ci.yml fetches the base images before it builds an image (deploy/base-images.py)")
    content, ubi, node, arm64 = stub_content()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StubRegistry)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host = f"127.0.0.1:{server.server_port}"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            # The stub speaks plain HTTP: skopeo is told so for this host alone, as a test's setting, in a per-user
            # registries.conf under a HOME of its own. That file is the one both skopeo 1.13.3 (the runner's; containers/image
            # v5.26.2 reads no CONTAINERS_REGISTRIES_CONF) and later versions read. base-images.py has no TLS switch. No
            # credentials are read from this machine.
            conf_dir, auth = os.path.join(tmp, "home", ".config", "containers"), os.path.join(tmp, "auth.json")
            os.makedirs(conf_dir)
            open(os.path.join(conf_dir, "registries.conf"), "w").write(f'[[registry]]\nlocation = "{host}"\ninsecure = true\n')
            open(auth, "w").write("{}")
            os.makedirs(os.path.join(tmp, "docker"))
            env = {k: v for k, v in os.environ.items() if k != "CONTAINERS_REGISTRIES_CONF"}
            env.update(HOME=os.path.join(tmp, "home"), REGISTRY_AUTH_FILE=auth, DOCKER_CONFIG=os.path.join(tmp, "docker"))

            def containerfile(name, *froms):
                path = os.path.join(tmp, name)
                open(path, "w").write("".join(f"FROM {f}\n" for f in froms))
                return path

            pinned = containerfile("Containerfile", f"{host}/ubi@{ubi} AS tools", f"{host}/node@{node} AS build",
                                   "tools", f"{host}/ubi@{ubi}")

            def fresh(served=None, failures=0):
                StubRegistry.content = served or content
                StubRegistry.token_failures, StubRegistry.token_requests, StubRegistry.requested = failures, 0, []

            def last(r):
                return r.stderr.strip().splitlines()[-1:]

            ubi_manifest = f"/v2/ubi/manifests/{ubi}"
            ubi_layer = "/v2/ubi/blobs/" + json.loads(content[ubi_manifest][1])["layers"][0]["digest"]
            for i, (where, flags) in enumerate(commands):
                attempts = int(flags["--attempts"])
                fresh(failures=TOKEN_FAILURES)
                layout = os.path.join(tmp, f"layout-{i}")
                r = run_base(flags, pinned, layout, env)
                expect = sorted([f"{host}/ubi@{ubi}=oci-layout://{layout}@{ubi}", f"{host}/node@{node}=oci-layout://{layout}@{node}"])
                check(r.returncode == 0 and sorted(r.stdout.split()) == expect and layout_ok(layout)
                      and os.path.exists(os.path.join(layout, "blobs", "sha256", ubi.split(":")[1]))
                      and not os.path.exists(os.path.join(layout, "blobs", "sha256", arm64.split(":")[1]))
                      and not [p for p in StubRegistry.requested if arm64 in p] and StubRegistry.token_requests > TOKEN_FAILURES,
                      f"{where}: {' '.join(f'{k} {v}' for k, v in flags.items() if k not in ('--containerfile', '--layout'))}: "
                      f"each FROM image in the layout after {TOKEN_FAILURES} refused token requests, every blob under its "
                      f"SHA-256, only the {flags['--platform']} image: exit {r.returncode} {last(r)}")

                fresh(failures=attempts)
                r = run_base(flags, pinned, os.path.join(tmp, f"refused-{i}"), env)
                check(r.returncode == 1 and f"failed {attempts} times" in r.stderr and "unauthorized" in last(r)[0] and not r.stdout,
                      f"{where}: fails, with no build context, when all {attempts} attempts are refused: exit {r.returncode} {last(r)}")

                # A layer that is not its digest, and a manifest that is not the pinned one: refused, one attempt each, by
                # skopeo ("Digest did not match"; newer versions also check the manifest) or by base-images.py's own check.
                fresh({**content, ubi_layer: (content[ubi_layer][0], gzip.compress(b"other bytes", mtime=0))})
                r = run_base(flags, pinned, os.path.join(tmp, f"blob-{i}"), env, **{"--attempts": "1"})
                check(r.returncode == 1 and not r.stdout and re.search(r"did not match|does not match", last(r)[0]) is not None,
                      f"{where}: refuses a layer that is not its digest: exit {r.returncode} {last(r)}")
                fresh({**content, ubi_manifest: (V2S2, content[ubi_manifest][1] + b" ")})
                r = run_base(flags, pinned, os.path.join(tmp, f"manifest-{i}"), env, **{"--attempts": "1"})
                check(r.returncode == 1 and not r.stdout and re.search(r"did not match|does not match", last(r)[0]) is not None,
                      f"{where}: refuses a manifest that is not the pinned digest: exit {r.returncode} {last(r)}")

                fresh()
                r = run_base(flags, containerfile(f"Tagged-{i}", f"{host}/ubi:latest"), os.path.join(tmp, f"tag-{i}"), env)
                check(r.returncode == 1 and "is not pinned by a sha256 digest" in r.stderr,
                      f"{where}: refuses a FROM that is not pinned by digest: exit {r.returncode} {last(r)}")
    finally:
        server.shutdown()
    return fails


def main() -> int:
    fails, found = [], list(downloads())
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FlakyOnce)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for i, (where, flags, url) in enumerate(found):
                out = os.path.join(tmp, f"{i}.out")
                local = f"http://127.0.0.1:{server.server_port}/{i}"
                # --retry-delay 0 would turn off curl's backoff; the flags are the file's own, so the run waits as CI would.
                r = subprocess.run(["curl", *flags, "-o", out, local], capture_output=True, text=True, timeout=120)
                ok = r.returncode == 0 and open(out, "rb").read() == BODY
                print(("  ok   " if ok else "  FAIL ") + f"{where}: curl {' '.join(flags)} ({url}) after one 503: exit {r.returncode}")
                if not ok:
                    fails.append(where)
    finally:
        server.shutdown()
    if len(found) < 17:
        print(f"  FAIL only {len(found)} downloads found: the pattern no longer matches the files")
        fails.append("count")
    print(f"{len(found)} downloads, {len(fails)} failed")
    base_fails = base_images_case()
    print(f"the base images: {len(base_fails)} failed")
    return 1 if fails or base_fails else 0


if __name__ == "__main__":
    sys.exit(main())
