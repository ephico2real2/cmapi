#!/usr/bin/env python3
"""Print the generated part of docs/04-api-examples.md: each operation with its curl sample and the request and
response that a run of the service suite recorded.

    python scripts/api-examples-doc.py            print it
    python scripts/api-examples-doc.py --write    replace the text between the marker lines of docs/04
    python scripts/api-examples-doc.py --check    exit 1 when docs/04 is not current

It reads cmapi/contract/openapi.json and cmapi/src/cmapi/contract/samples.json, so it needs no database and no
package beside the standard library. A long list in a response is cut to its first item, and the text says so.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "04-api-examples.md"
BEGIN, END = "<!-- examples:begin -->\n", "<!-- examples:end -->"


def cut(value, notes: list[str], path: str = "body"):
    """The value with each list cut to its first item. notes gets one line for each list that was cut."""
    if isinstance(value, dict):
        return {k: cut(v, notes, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 1:
            notes.append(f"`{path}` has {len(value)} items in the run. The first is shown.")
        return [cut(value[0], notes, f"{path}[0]")] if value else []
    return value


def block(lang: str, text: str) -> list[str]:
    return [f"```{lang}", text.rstrip("\n"), "```", ""]


def shown(body) -> tuple[str, str, list[str]]:
    if isinstance(body, str):
        lines = body.splitlines()
        notes = [f"The run returned {len(lines)} lines. The first 3 are shown."] if len(lines) > 3 else []
        return "text", "\n".join(lines[:3]), notes
    notes: list[str] = []
    return "json", json.dumps(cut(body, notes), indent=2), notes


def render() -> str:
    spec = json.loads((ROOT / "cmapi" / "contract" / "openapi.json").read_text())
    samples = json.loads((ROOT / "cmapi" / "src" / "cmapi" / "contract" / "samples.json").read_text())
    ops = {}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            ops[op["operationId"]] = (method.upper(), path, op)
    tags = {t["name"]: t for t in spec["tags"]}
    out: list[str] = []
    for group in spec["x-tagGroups"]:
        out += [f"## {group['name']}", ""]
        for tag in group["tags"]:
            out += [f"{tags[tag]['description']}", ""]
            for op_id, (method, path, op) in sorted(ops.items(), key=lambda kv: (kv[1][1], kv[1][0])):
                if op["tags"] != [tag]:
                    continue
                out += [f"### {op['summary']}", "", f"`{method} {path}`", ""]
                permission = op.get("x-cmapi-permission")
                out += [f"Permission: `{permission}`." if permission else
                        ("Permission: none. A valid token is necessary." if op.get("security") else "Permission: none, and no token."), ""]
                out += block("bash", op["x-codeSamples"][0]["source"])
                for key in (op_id, f"{op_id}:dryRun"):
                    sample = samples["operations"].get(key)
                    if sample is None:
                        continue
                    request, response = sample["request"], sample["response"]
                    out += [f"The run sent `{request['method']} {request['path']}`" + (" with this body:" if "body" in request else "."), ""]
                    if "body" in request:
                        out += block("json", json.dumps(request["body"], indent=2))
                    lang, text, notes = shown(response["body"])
                    headers = "".join(f", `{k}: {v}`" for k, v in sorted(response["headers"].items()))
                    out += [f"The answer was {response['status']} (`{response['contentType']}`{headers}):", ""]
                    out += block(lang, text)
                    out += [n for n in notes] + ([""] if notes else [])
                if op_id not in samples["operations"]:
                    refusals = [c for c, p in samples["problems"].items() if p["operationId"] == op_id]
                    out += [f"The run has no successful call of this operation. Its recorded answer is the problem `{refusals[0]}`, under \"Problems\"."
                            if refusals else "The run has no call of this operation.", ""]
    out += ["## Problems", "",
            "Each refusal is an RFC 9457 problem with the media type `application/problem+json`. These are the ones that the run met.", ""]
    for code, p in samples["problems"].items():
        request, response = p["request"], p["response"]
        out += [f"### {response['status']} `{code}`", "", f"`{request['method']} {request['path']}`" + (", with a body" if "body" in request else "") +
                (", with no token" if "Authorization" not in request["headers"] else "") + ":", ""]
        out += block("json", json.dumps(response["body"], indent=2))
    return "\n".join(out).rstrip("\n") + "\n"


def main() -> None:
    text = render()
    if len(sys.argv) == 1:
        sys.stdout.write(text)
        return
    doc = DOC.read_text()
    if BEGIN not in doc or END not in doc:
        sys.exit("api-examples-doc: docs/04-api-examples.md has lost its marker lines")
    head, rest = doc.split(BEGIN, 1)
    current, tail = rest.split(END, 1)
    if sys.argv[1] == "--check":
        if current != text:
            sys.exit("api-examples-doc: docs/04-api-examples.md is not current: run scripts/api-examples-doc.py --write")
    elif sys.argv[1] == "--write":
        DOC.write_text(head + BEGIN + text + END + tail)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
