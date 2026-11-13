"""/docs/changelog (docs/01, "API documentation"): the changes of the API contract for each released version.

The page reads cmapi/contract/changelog.json, which is packaged with the code. cmapi/contract/changelog.py writes that
file from the released specs in cmapi/contract/released/, with the same tool that the CI contract gate uses (oasdiff), and
CI refuses a file that is not current. Nothing is computed at request time, and nothing is fetched.
"""
from __future__ import annotations

import html
import json
from importlib import resources
from typing import Any

LEVELS = {3: "breaking", 2: "warning", 1: "change"}


def load_changelog() -> dict[str, Any]:
    return json.loads(resources.files("cmapi.contract").joinpath("changelog.json").read_text())


def changelog_html(title: str, build_version: str, data: dict[str, Any] | None = None) -> str:
    data = load_changelog() if data is None else data
    e = html.escape
    parts = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8"/>',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             f"<title>{e(title)} - API changelog</title>",
             "<style>body{font:16px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem}"
             "code{background:#f2f2f2;padding:0 .25rem}.breaking{color:#b00020;font-weight:600}"
             "li{margin:.25rem 0}</style></head><body>",
             f"<h1>{e(title)}: API changelog</h1>",
             f'<p>This build is version <code>{e(build_version)}</code>. The contract is <a href="/openapi.json">/openapi.json</a>; '
             'the reference is <a href="/redoc">/redoc</a>.</p>']
    releases = data.get("releases") or []
    if not releases:
        parts.append('<p id="no-release">No version of the API contract is released yet, so there is no change to list.</p>')
    for rel in releases:
        parts.append(f'<h2 id="v{e(rel["version"])}">{e(rel["version"])}</h2>')
        if rel.get("previous") is None:
            parts.append("<p>The first released contract.</p>")
            continue
        parts.append(f'<p>Changes from <code>{e(rel["previous"])}</code>.</p>')
        changes = rel.get("changes") or []
        if not changes:
            parts.append("<p>No change to the contract.</p>")
            continue
        parts.append("<ul>")
        for ch in changes:
            level = LEVELS.get(ch.get("level"), "change")
            where = " ".join(x for x in (ch.get("operation"), ch.get("path")) if x)
            parts.append(f'<li><span class="{level}">{level}</span> <code>{e(where)}</code> {e(ch.get("text", ""))}</li>')
        parts.append("</ul>")
    parts.append("</body></html>")
    return "\n".join(parts)
