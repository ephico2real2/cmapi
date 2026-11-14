#!/usr/bin/env python3
"""deploy/tests/front-door-docs-standin.py <port> <static dir>: the API's HTML pages for the front door's browser test.

It serves /docs, /docs/oauth2-redirect, /docs/changelog, /redoc, /openapi.json, /openapi.yaml, /problems and their
bundles with cmapi's own route functions (cmapi.main._add_docs and _add_problem_pages), so the browser test of
cmapi-portal-ui/tests/front-door.test.mjs loads the pages that the API serves, under the front door's
Content-Security-Policy. The OpenAPI document is the committed contract (cmapi/contract/openapi.json). It needs no
database and no configuration. The static dir holds the bundles of `cmapi-tools docs-assets`.
Run with PYTHONPATH=cmapi/src.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

port, static = int(sys.argv[1]), sys.argv[2]
# cmapi.main reads the bundles' folder when it is imported.
os.environ["CMAPI_STATIC_DIR"] = static

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from cmapi.core.errors import Problem  # noqa: E402
from cmapi.main import _add_docs, _add_problem_pages  # noqa: E402

CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "cmapi" / "contract" / "openapi.json").read_text())
BASE = "https://cmapi.ephico2real.com/problems/"
ctx = SimpleNamespace(cfg=SimpleNamespace(name="nonprod"))
# The same Swagger UI sign-in settings as create_app in cmapi/src/cmapi/main.py.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None,
              swagger_ui_init_oauth={"clientId": "cmapi-docs", "usePkceWithAuthorizationCodeGrant": True, "scopes": "openid"})
app.openapi = lambda: CONTRACT  # type: ignore[method-assign]


def problem_response(p: Problem, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(p.body(BASE), status_code=p.status, media_type="application/problem+json", headers=headers)


_add_problem_pages(app, ctx, BASE)  # type: ignore[arg-type]
_add_docs(app, ctx, {}, None, problem_response)  # type: ignore[arg-type]
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
