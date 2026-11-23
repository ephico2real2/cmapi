#!/usr/bin/env python3
"""Each download of CI and of the cmapi image survives one transient answer (#609).

Every `curl ... -o <file> <url>` of the workflows and of cmapi/Containerfile is run, with its own flags, against a local
server that answers 503 to the first request for each path and the file after. The download must then exit 0 with the
file's bytes. Before #609 the flags had no `--retry`, so curl stopped at the 503 with exit 22, as a GitHub 503 stopped
images-pr on PR #608 (run 45248911791). curl's manual, `--retry`: a transient error is "a timeout, an FTP 4xx response
code or an HTTP 408, 429, 500, 502, 503, 504, 522 or 524 response code".

Python standard library and the curl on PATH only. usage: download-retry-test.py. Exit 1 on any failure.
"""
import http.server
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILES = [".github/workflows/ci.yml", ".github/workflows/api-contract-report.yml", "cmapi/Containerfile",
         "examples/cluster-configs/.github/workflows/ci.yml"]
BODY = b"the downloaded file\n"
# A download: curl, its flags, -o, the output, the URL. Each one in these files is written on one line.
DOWNLOAD = re.compile(r"\bcurl((?:\s+-[-\w]+(?:\s+\d+)?)*)\s+-o\s+(\S+)\s+(\S+)")


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
            m = DOWNLOAD.search(line)
            if m:
                yield f"{rel}:{n}", shlex.split(m.group(1)), m.group(3)


def main() -> int:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FlakyOnce)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fails, found = [], list(downloads())
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
    if len(found) < 15:
        print(f"  FAIL only {len(found)} downloads found: the pattern no longer matches the files")
        fails.append("count")
    print(f"{len(found)} downloads, {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
