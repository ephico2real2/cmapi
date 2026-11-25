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
same command must fail when every attempt is refused, and when a FROM, an image another instruction names, or a syntax
directive's frontend image would be pulled by BuildKit itself. A layer, a config, a manifest, an index and an index's platform
manifest that are not their digest must be refused on the first attempt, with the workflow's own --attempts. The UBI stub has
a signature in a lookaside store, as registry.access.redhat.com has where Fedora's registries.d names it; an OCI layout cannot
hold one. The script's own check of the pinned manifest is run against a skopeo that adds a byte after the real one has
finished, and its TLS against the same stub with no setting that allows plain HTTP. Before #663 ci.yml ran no such command, so
this part fails and names the gap.

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
import shutil
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
        if path.startswith("/sigstore/"):  # a lookaside signature store is a plain web server, with no token
            with cls.lock:
                cls.requested.append(path)
            if path not in cls.content:
                return self.reply(404, "text/plain", b"not found\n", with_body)
            return self.reply(200, "application/octet-stream", cls.content[path][1], with_body)
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


def stub_image(name: str, kind: str, payload: bytes, times: int = 1) -> tuple[str, list]:
    """One linux/amd64 image of one gzipped layer, listed `times` times: its manifest digest and its content entries."""
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w") as t:
        info = tarfile.TarInfo("etc/stub")
        info.size = len(payload)
        t.addfile(info, io.BytesIO(payload))
    layer = gzip.compress(tar.getvalue(), mtime=0)
    config = json.dumps({"architecture": "amd64", "os": "linux",
                         "rootfs": {"type": "layers", "diff_ids": [digest_of(tar.getvalue())] * times}}).encode()
    docker = kind == V2S2
    manifest = json.dumps({"schemaVersion": 2, "mediaType": kind,
                           "config": {"mediaType": "application/vnd.docker.container.image.v1+json" if docker
                                      else "application/vnd.oci.image.config.v1+json",
                                      "digest": digest_of(config), "size": len(config)},
                           "layers": [{"mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip" if docker
                                       else "application/vnd.oci.image.layer.v1.tar+gzip",
                                       "digest": digest_of(layer), "size": len(layer)}] * times}).encode()
    entries = [(f"/v2/{name}/blobs/{digest_of(config)}", ("application/octet-stream", config)),
               (f"/v2/{name}/blobs/{digest_of(layer)}", ("application/octet-stream", layer)),
               (f"/v2/{name}/manifests/{digest_of(manifest)}", (kind, manifest))]
    return digest_of(manifest), entries


def stub_content():
    """ubi: one Docker v2s2 manifest, as the UBI base is. node: an OCI index of linux/arm64, linux/amd64 and an attestation,
    as the docker.io bases are, where only the amd64 image is served; arm64 comes first, so the platform must be read.
    twice: an image whose manifest lists one layer twice, as an image with two identical layers does."""
    ubi, content = stub_image("ubi", V2S2, b"ubi\n")
    amd64, node = stub_image("node", OCI_MANIFEST, b"node amd64\n")
    content += node
    arm64 = digest_of(b"the arm64 manifest, never served")
    index = json.dumps({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [
        {"mediaType": OCI_MANIFEST, "digest": arm64, "size": 100, "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
        {"mediaType": OCI_MANIFEST, "digest": amd64, "size": len(dict(node)[f"/v2/node/manifests/{amd64}"][1]),
         "platform": {"os": "linux", "architecture": "amd64"}},
        {"mediaType": OCI_MANIFEST, "digest": digest_of(b"an attestation"), "size": 100,
         "platform": {"os": "unknown", "architecture": "unknown"}}]}, indent=2).encode()  # indented, so a script that re-serializes it files other bytes
    content.append((f"/v2/node/manifests/{digest_of(index)}", (OCI_INDEX, index)))
    twice, entries = stub_image("twice", OCI_MANIFEST, b"twice\n", times=2)
    # ubi's signature, where a registries.d lookaside for this host points: <lookaside>/<repo>@sha256=<hex>/signature-1
    # (containers-registries.d(5)). Its first byte is OpenPGP's, so skopeo reads it as a simple signing signature
    # (internal/signature/signature.go, FromBlob); its content is never verified: no policy here asks for a signature.
    entries.append((f"/sigstore/ubi@sha256={ubi.split(':')[1]}/signature-1",
                    ("application/octet-stream", b"\xa3 a signature, never verified")))
    return dict(content + entries), ubi, digest_of(index), arm64, twice


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


# The real skopeo, then one byte more after "inspect": skopeo's own check has passed by then (1.24.1) or was never made
# (1.13.3), so only base-images.py's can refuse it.
LYING_SKOPEO = """#!{python}
import os, subprocess, sys
r = subprocess.run([os.environ["REAL_SKOPEO"], *sys.argv[1:]], capture_output=True)
out = r.stdout + (b" " if r.returncode == 0 and sys.argv[1] == "inspect" else b"")
sys.stdout.buffer.write(out)
sys.stderr.buffer.write(r.stderr)
sys.exit(r.returncode)
"""


def layout_ok(layout: str) -> bool:
    blobs = os.path.join(layout, "blobs", "sha256")
    return all(digest_of(open(os.path.join(blobs, b), "rb").read()) == "sha256:" + b for b in os.listdir(blobs))


def layout_holds(layout: str, digest: str, platform: str) -> bool:
    """What BuildKit reads from the layout for a context's digest: that blob, and for an index the platform's manifest, then
    the manifest's config and every layer."""
    def blob(d):
        path = os.path.join(layout, "blobs", "sha256", d.split(":", 1)[1])
        return json.loads(open(path, "rb").read()) if os.path.isfile(path) else None
    doc = blob(digest)
    if doc and "manifests" in doc:
        want = platform.split("/")[:2]
        entry = [e for e in doc["manifests"] if [(e.get("platform") or {}).get(k) for k in ("os", "architecture")] == want]
        doc = blob(entry[0]["digest"]) if len(entry) == 1 else None
    return bool(doc) and all(os.path.isfile(os.path.join(layout, "blobs", "sha256", b["digest"].split(":", 1)[1]))
                             for b in [doc["config"], *doc["layers"]])


def base_images_case() -> list:
    fails = []

    def check(ok, label):
        print(("  ok   " if ok else "  FAIL ") + label)
        if not ok:
            fails.append(label)

    commands = base_commands()
    check(bool(commands), "ci.yml fetches the base images before it builds an image (deploy/base-images.py)")
    content, ubi, node, arm64, twice = stub_content()
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
            os.makedirs(os.path.join(conf_dir, "registries.d"))
            open(os.path.join(conf_dir, "registries.d", "stub.yaml"), "w").write(
                f"docker:\n  {host}:\n    lookaside: http://{host}/sigstore\n")
            open(auth, "w").write("{}")
            os.makedirs(os.path.join(tmp, "docker"))
            env = {k: v for k, v in os.environ.items() if k != "CONTAINERS_REGISTRIES_CONF"}
            env.update(HOME=os.path.join(tmp, "home"), REGISTRY_AUTH_FILE=auth, DOCKER_CONFIG=os.path.join(tmp, "docker"))

            def containerfile(name, *lines, bom=""):
                path = os.path.join(tmp, name)
                open(path, "w", encoding="utf-8").write(bom + "".join(f"{line}\n" for line in lines))
                return path

            # As the two Containerfiles are: stages, and COPY --from= a stage by its name. And by its number, and a mount. A
            # parser directive that is not syntax, and a syntax line after the directives, which is only a comment.
            pinned = containerfile("Containerfile", "# escape=\\", "# The stub's bases.",
                                   f"FROM {host}/ubi@{ubi} AS tools", "# syntax=a-comment-here", f"FROM {host}/node@{node} AS build",
                                   "FROM tools", f"FROM {host}/ubi@{ubi}", "COPY --from=tools /etc/stub /a",
                                   "COPY --from=0 /etc/stub /b", "RUN --mount=type=bind,from=build,target=/m true")

            def fresh(served=None, failures=0):
                StubRegistry.content = served or content
                StubRegistry.token_failures, StubRegistry.token_requests, StubRegistry.requested = failures, 0, []

            def last(r):
                return r.stderr.strip().splitlines()[-1:]

            ubi_manifest, node_index = f"/v2/ubi/manifests/{ubi}", f"/v2/node/manifests/{node}"
            ubi_layer = "/v2/ubi/blobs/" + json.loads(content[ubi_manifest][1])["layers"][0]["digest"]
            ubi_config = "/v2/ubi/blobs/" + json.loads(content[ubi_manifest][1])["config"]["digest"]
            node_amd64 = "/v2/node/manifests/" + next(e["digest"] for e in json.loads(content[node_index][1])["manifests"]
                                                      if e["platform"]["architecture"] == "amd64")
            lying = os.path.join(tmp, "lying")
            os.makedirs(lying)
            open(os.path.join(lying, "skopeo"), "w").write(LYING_SKOPEO.format(python=sys.executable))
            os.chmod(os.path.join(lying, "skopeo"), 0o755)
            lying_env = {**env, "REAL_SKOPEO": shutil.which("skopeo") or "skopeo", "PATH": lying + os.pathsep + env["PATH"]}
            os.makedirs(os.path.join(tmp, "strict-home"))
            # The lookaside is read: a copy into an OCI layout that keeps signatures fails, so the cases below that copy the
            # UBI stub would fail without --remove-signatures.
            fresh()
            r = subprocess.run(["skopeo", "copy", "--quiet", "--preserve-digests", f"docker://{host}/ubi@{ubi}",
                                f"oci:{os.path.join(tmp, 'signed')}"], capture_output=True, text=True, env=env, timeout=600)
            check(r.returncode != 0 and "Pushing signatures for OCI images is not supported" in r.stderr
                  and any(p.startswith("/sigstore/ubi@") for p in StubRegistry.requested),
                  f"the stub's signature store is read, and an OCI layout refuses its signature: exit {r.returncode} {last(r)}")
            for i, (where, flags) in enumerate(commands):
                attempts, delay = int(flags["--attempts"]), float(flags["--delay"])
                fresh(failures=TOKEN_FAILURES)
                layout = os.path.join(tmp, f"layout-{i}")
                r = run_base(flags, pinned, layout, env)
                expect = sorted([f"{host}/ubi@{ubi}=oci-layout://{layout}@{ubi}", f"{host}/node@{node}=oci-layout://{layout}@{node}"])
                check(r.returncode == 0 and sorted(r.stdout.split()) == expect and layout_ok(layout)
                      and all(layout_holds(layout, d, flags["--platform"]) for d in (ubi, node))
                      and not os.path.exists(os.path.join(layout, "blobs", "sha256", arm64.split(":")[1]))
                      and not [p for p in StubRegistry.requested if arm64 in p] and StubRegistry.token_requests > TOKEN_FAILURES
                      and f"trying again in {delay:g} s" in r.stderr and f"trying again in {2 * delay:g} s" in r.stderr,
                      f"{where}: {' '.join(f'{k} {v}' for k, v in flags.items() if k not in ('--containerfile', '--layout'))}: "
                      f"each FROM image in the layout after {TOKEN_FAILURES} refused token requests and a wait that doubles, "
                      f"every blob under its "
                      f"SHA-256, only the {flags['--platform']} image: exit {r.returncode} {last(r)}")

                fresh(failures=attempts)
                r = run_base(flags, pinned, os.path.join(tmp, f"refused-{i}"), env)
                check(r.returncode == 1 and f"failed {attempts} times" in r.stderr and "unauthorized" in last(r)[0] and not r.stdout,
                      f"{where}: fails, with no build context, when all {attempts} attempts are refused: exit {r.returncode} {last(r)}")

                # A layer, a config, a manifest, an index and the platform's manifest of an index that are not their digest:
                # refused by skopeo (1.24.1 also checks the pinned manifest) or by base-images.py's own check. With the
                # workflow's own --attempts, and asked for once: another attempt cannot make wrong bytes right.
                ubi_only = containerfile(f"Ubi-{i}", f"FROM {host}/ubi@{ubi}")
                node_only = containerfile(f"Node-{i}", f"FROM {host}/node@{node}")
                for n, (what, path, kind, data, file) in enumerate((
                        ("a layer that is not its digest", ubi_layer, content[ubi_layer][0], gzip.compress(b"other", mtime=0), ubi_only),
                        ("a config that is not its digest", ubi_config, content[ubi_config][0], content[ubi_config][1] + b" ", ubi_only),
                        ("the platform's manifest of an index, not the digest the index names", node_amd64, OCI_MANIFEST,
                         content[node_amd64][1] + b" ", node_only),
                        ("a manifest that is not the pinned digest", ubi_manifest, V2S2, content[ubi_manifest][1] + b" ", ubi_only),
                        ("an index that is not the pinned digest", node_index, OCI_INDEX, content[node_index][1] + b" ", node_only))):
                    fresh({**content, path: (kind, data)})
                    r = run_base(flags, file, os.path.join(tmp, f"wrong-{i}-{n}"), env)
                    asked = StubRegistry.requested.count(path)
                    # One attempt: no "trying again". A config is read twice in that attempt, so the count is not 1 for it.
                    check(r.returncode == 1 and not r.stdout and re.search(r"did not match|does not match", last(r)[0]) is not None
                          and asked >= 1 and "trying again" not in r.stderr,
                          f"{where}: refuses {what}, in one attempt of {attempts}: asked {asked}, exit {r.returncode} {last(r)}")

                # base-images.py's own check, where skopeo's has passed: a skopeo that adds one byte after the real one.
                fresh()
                r = run_base(flags, ubi_only, os.path.join(tmp, f"lying-{i}"), lying_env)
                check(r.returncode == 1 and not r.stdout and "the registry's manifest does not match the pinned digest" in last(r)[0]
                      and "trying again" not in r.stderr,
                      f"{where}: its own check refuses a byte added to the pinned manifest after skopeo's: exit {r.returncode} {last(r)}")

                # TLS: the same stub, which speaks plain HTTP, with no registries.conf that allows it. skopeo must stop
                # before any request for a token or for content; a script that turned TLS off would be served.
                fresh()
                r = run_base(flags, ubi_only, os.path.join(tmp, f"tls-{i}"), {**env, "HOME": os.path.join(tmp, "strict-home")},
                             **{"--attempts": "1"})
                check(r.returncode == 1 and not r.stdout and not StubRegistry.requested and not StubRegistry.token_requests
                      and re.search(r"HTTPS client|TLS handshake", last(r)[0]) is not None,
                      f"{where}: asks a registry that speaks plain HTTP for nothing: exit {r.returncode} {last(r)}")

                fresh()
                listed = os.path.join(tmp, f"listed-{i}")
                r = run_base(flags, containerfile(f"Twice-{i}", f"FROM {host}/twice@{twice}"), listed, env)
                check(r.returncode == 0 and layout_ok(listed) and layout_holds(listed, twice, flags["--platform"])
                      and len(os.listdir(os.path.join(listed, "blobs", "sha256"))) == 3,
                      f"{where}: takes an image whose manifest lists one layer twice: exit {r.returncode} {last(r)}")

                # skopeo's oci: transport ends the path at the first colon (containers-transports(5)), so such a layout
                # would be written somewhere else than the build context names.
                fresh()
                r = run_base(flags, ubi_only, os.path.join(tmp, f"co:lon-{i}"), env)
                check(r.returncode == 1 and not r.stdout and "a colon" in last(r)[0] and not StubRegistry.requested,
                      f"{where}: refuses a layout path with a colon: exit {r.returncode} {last(r)}")

                for n, (what, why, lines, bom) in enumerate((
                        ("a FROM that is not pinned by digest", "is not pinned by a sha256 digest", [f"FROM {host}/ubi:latest"], ""),
                        ("an unpinned FROM behind a byte-order mark, which BuildKit drops", "is not pinned by a sha256 digest",
                         [f"FROM {host}/ubi:latest", f"FROM {host}/ubi@{ubi}"], "\ufeff"),
                        ("COPY --from= an image", "names an image, not a stage",
                         [f"FROM {host}/ubi@{ubi}", f"COPY --from={host}/node:latest /etc/stub /a"], ""),
                        ("RUN --mount= from an image", "names an image, not a stage",
                         [f"FROM {host}/ubi@{ubi}", f"RUN --mount=type=bind,from={host}/node@{node},target=/m true"], ""),
                        ("a syntax directive, whose frontend image BuildKit pulls", "a syntax directive",
                         ["# syntax=docker/dockerfile:1", f"FROM {host}/ubi@{ubi}"], ""),
                        ("a syntax directive after a #! line and another directive", "a syntax directive",
                         ["#!/usr/bin/env buildctl", "# check=error=true", "#SYNTAX = docker/dockerfile:1", f"FROM {host}/ubi@{ubi}"], "\ufeff"))):
                    fresh()
                    r = run_base(flags, containerfile(f"Unpinned-{i}-{n}", *lines, bom=bom), os.path.join(tmp, f"no-{i}-{n}"), env)
                    check(r.returncode == 1 and not r.stdout and why in r.stderr and not StubRegistry.requested,
                          f"{where}: refuses {what}: exit {r.returncode} {last(r)}")
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
