"""Starlette FileResponse sends http.response.start before it opens the file: a file that os.stat reads but open()
cannot gives a 200 with Content-Length, then a closed connection. Run as a non-root user."""
import os, socket, sys, tempfile, threading, time

import starlette, uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

root = tempfile.mkdtemp()
path = os.path.join(root, "bundle.js")
with open(path, "wb") as f:
    f.write(b"x" * 100_000)
os.chmod(path, 0o000)
print(f"starlette {starlette.__version__}, uvicorn {uvicorn.__version__}, euid {os.geteuid()}, mode {oct(os.stat(path).st_mode & 0o777)}")

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
length = next((int(l.split(b":")[1]) for l in head.split(b"\r\n") if l.lower().startswith(b"content-length")), None)
print(f"--- content-length {length}, body bytes received {len(body)}, then the connection closed")
os.chmod(path, 0o644)
server.should_exit = True
sys.exit(0 if head.startswith(b"HTTP/1.1 200") and length and len(body) < length else 1)
