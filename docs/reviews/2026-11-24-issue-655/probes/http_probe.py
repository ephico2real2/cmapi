"""Over real HTTP: uvicorn as cmapi runs it (main.run: http=auto, so httptools), cmapi's bearer dependency and Authenticator,
and a token whose header is nested past the depth at which PyJWT 2.10.1 lets RecursionError escape (#655)."""
import base64, socket, subprocess, sys, textwrap, time
import httpx, uvicorn
port = (s := socket.socket(), s.bind(("127.0.0.1", 0)), s.getsockname()[1])[2]; s.close()
app = textwrap.dedent('''
    from fastapi import Depends, FastAPI, Request
    from fastapi.responses import JSONResponse
    from cmapi.core.auth import Authenticator, Jwks, caller_dependency, oauth2_scheme
    from cmapi.core.errors import Problem
    from conftest import AUDIENCE, ISSUER, Keys
    keys = Keys()
    app = FastAPI()
    app.state.auth = Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, "https://keycloak.test/certs", fetch=lambda u: [keys.jwk]))
    @app.exception_handler(Problem)
    async def problem(request: Request, p: Problem):
        return JSONResponse({"status": p.status, "code": p.code}, status_code=p.status)
    @app.get("/who")
    def who(caller=Depends(caller_dependency(oauth2_scheme(ISSUER)))):
        return {"sub": caller.sub}
''')
import os, tempfile
d = tempfile.mkdtemp(); open(os.path.join(d, "probe_app.py"), "w").write(app)
env = {**os.environ, "PYTHONPATH": os.pathsep.join([d, os.environ["PYTHONPATH"]])}
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "probe_app:app", "--port", str(port), "--log-level", "critical"], env=env,
                       stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try: httpx.get(f"http://127.0.0.1:{port}/who"); break
        except httpx.TransportError: time.sleep(0.1)
    import jwt
    print(f"PyJWT {jwt.__version__}, uvicorn {uvicorn.__version__}")
    def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    for depth in (1_000, 9_997, 20_000, 100_000):
        tok = f"{b64(b'{\"alg\":\"RS256\",\"kid\":\"test-kid-1\",\"x\":' + b'[' * depth + b']' * depth + b'}')}.{b64(b'{}')}.{b64(b'sig')}"
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/who", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
            print(f"depth {depth}, Authorization {len(tok) + 7} bytes: HTTP {r.status_code} {r.text[:80]}")
        except httpx.HTTPError as e:
            print(f"depth {depth}, Authorization {len(tok) + 7} bytes: {type(e).__name__} {e}")
finally:
    srv.terminate(); srv.wait()
