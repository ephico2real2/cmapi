"""What cmapi's ConditionalStaticFiles answers to each Range header (#649), on the installed Starlette.

Run from cmapi/ with PYTHONPATH=src: python <this file>. It mounts the class itself over a 17-byte file, as the service
tests' bundles fixture does, so it needs no database.
"""
import tempfile
import warnings
from pathlib import Path

warnings.simplefilter("ignore")
import starlette
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from cmapi.main import ConditionalStaticFiles

RANGES = ["bytes=1-2", "bytes=-5", "bytes=99-", "oops", "bytes=5-1", "widgets=1-2", "bytes=0-0,5-6",
          "bytes=" + "0" * 16_000 + "a-"]

with tempfile.TemporaryDirectory() as d:
    Path(d, "b.js").write_text("/* test bundle */")
    client = TestClient(Starlette(routes=[Mount("/static", ConditionalStaticFiles(directory=d))]))
    whole = client.get("/static/b.js")
    print("starlette", starlette.__version__)
    print(f"  GET no Range: {whole.status_code} accept-ranges={whole.headers.get('accept-ranges')!r} "
          f"content-length={whole.headers['content-length']}")
    for value in RANGES:
        for method in ("GET", "HEAD"):
            r = client.request(method, "/static/b.js", headers={"Range": value})
            print(f"  {method:4} Range {value[:16]!r:18}: {r.status_code} content-range={r.headers.get('content-range')!r} "
                  f"accept-ranges={r.headers.get('accept-ranges')!r} content-type={r.headers.get('content-type')!r} "
                  f"content-length={r.headers.get('content-length')} body={r.content[:40]!r}")
    r = client.get("/static/b.js", headers={"Range": "bytes=1-2", "If-None-Match": whole.headers["etag"]})
    print(f"  GET Range 'bytes=1-2' + If-None-Match: {r.status_code} body={r.content!r}")
