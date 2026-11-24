"""What app.routes holds after include_router, and what a 405 / HEAD look like (FastAPI 0.137 router tree)."""
import fastapi, starlette
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

r = APIRouter()
@r.get("/things/{x}")
def get_thing(x: str): return {"x": x}
@r.patch("/things/{x}")
def patch_thing(x: str): return {"x": x}
app = FastAPI()
app.include_router(r, dependencies=[Depends(lambda: None)])
@app.get("/direct")
def direct(): return {}
print("fastapi", fastapi.__version__, "starlette", starlette.__version__)
for route in app.routes:
    print(" ", type(route).__module__ + "." + type(route).__name__, getattr(route, "path", None), getattr(route, "methods", None))
print("APIRoute in app.routes:", [r.path for r in app.routes if isinstance(r, APIRoute)])
# add HEAD to every GET APIRoute found in app.routes, as cmapi's _serve_head_with_get does
for route in app.routes:
    if isinstance(route, APIRoute) and "GET" in route.methods:
        route.methods.add("HEAD")
c = TestClient(app)
for m, p in [("HEAD", "/things/a"), ("HEAD", "/direct"), ("PUT", "/things/a")]:
    resp = c.request(m, p)
    print(m, p, resp.status_code, resp.headers.get("allow"))
if hasattr(fastapi.routing, "iter_route_contexts"):
    print("iter_route_contexts exists")
