Draft only: not filed. Starlette asks for bugs to start as a "Potential Issue" discussion
(https://github.com/Kludex/starlette/discussions; docs/contributing.md, "Contributions should generally start out with a
discussion. Possible bugs may be raised as a "Potential Issue" discussion", read 2026-11-25), and issue templates are off
(.github/ISSUE_TEMPLATE/config.yml: `blank_issues_enabled: false`).

---

Title: FileResponse sends `http.response.start` (200, Content-Length) before it opens the file; an unreadable file gives a truncated 200

Category: Potential Issue

**What happens.** `FileResponse._handle_simple` (and `_handle_single_range`, `_handle_multiple_ranges`) sends
`http.response.start` and only then opens the file (`responses.py`, main at 63d868e, lines 428-435; the same in 1.10.0,
lines 426-433). `StaticFiles.lookup_path` only `os.stat`s the path, which needs search permission on the directory but no
read permission on the file. So a file that the process can stat but not open, for example mode 0600 owned by another user,
or one replaced or removed between the stat and the open, gives a `200` with the file's `Content-Length`, then the
`PermissionError` from `anyio.open_file`, after the response has started. No middleware can turn it into an error response,
and the server closes the connection with no body bytes.

StaticFiles already maps a `PermissionError` raised during lookup to 401 (#1220), so the intent is that an unreadable file is
an error response, not a truncated 200.

**Reproduction** (Starlette 1.10.0, uvicorn 0.32.1, Python 3.12, macOS, as a non-root user):

```python
import os, socket, tempfile, threading, time
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

root = tempfile.mkdtemp()
path = os.path.join(root, "bundle.js")
with open(path, "wb") as f:
    f.write(b"x" * 100_000)
os.chmod(path, 0o000)

app = Starlette(routes=[Mount("/static", StaticFiles(directory=root))])
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
while not server.started:
    time.sleep(0.05)
port = server.servers[0].sockets[0].getsockname()[1]

s = socket.create_connection(("127.0.0.1", port))
s.sendall(b"GET /static/bundle.js HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
data = b""
while chunk := s.recv(65536):
    data += chunk
head, _, body = data.partition(b"\r\n\r\n")
print(head.decode())
print("body bytes:", len(body))
```

Output:

```
HTTP/1.1 200 OK
content-type: text/javascript; charset=utf-8
accept-ranges: bytes
content-length: 100000
...
body bytes: 0
```

and the server logs `PermissionError: [Errno 13] Permission denied` from `_open_file` (responses.py:418) inside
`_handle_simple` (responses.py:433).

**Expected.** The file is opened before the response starts, so a failure to open it is an ordinary exception (StaticFiles:
its 401, or a 500) rather than a 200 with a cut body. One way: open the file in `__call__` before choosing the handler and
pass the open file to the handlers (closing it in a `finally`); `http.response.pathsend` would keep its current path, as it
opens nothing itself.

**Related.** #3594 (closed by its author, not merged) opened static files before building the response, for a different
reason (a path-replacement race), and would have fixed this order as a side effect.
