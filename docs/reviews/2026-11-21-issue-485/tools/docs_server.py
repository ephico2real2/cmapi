"""Serve cmapi's real /docs, /redoc and /openapi.json (main.api_app + main._add_docs) for a browser look, with no database:
the docs routes read only the configuration. Usage: docs_server.py <metadata-keys.yaml> <port>."""
import sys
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from fastapi.responses import JSONResponse

import cmapi.main as main_mod
from cmapi.core.errors import type_base
from cmapi.tools.openapi import load

cfg = load(Path(sys.argv[1]), None)
app, authed = main_mod.api_app(cfg, cfg.raw_instance["instance"]["auth"]["issuer"], cluster_environments={"CRC": "dev"})
ctx = SimpleNamespace(cfg=cfg)
base = type_base(cfg.raw_instance["instance"])
problem_response = lambda p, headers=None: JSONResponse(p.body(base), status_code=p.status, media_type="application/problem+json")
main_mod._add_problem_pages(app, ctx, base)
main_mod._add_docs(app, ctx, {}, authed, problem_response)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
