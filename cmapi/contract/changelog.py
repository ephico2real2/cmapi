#!/usr/bin/env python3
"""Write src/cmapi/contract/changelog.json from the released documents in contract/released/.

    python contract/changelog.py            write the file
    python contract/changelog.py --check    exit 1 when the file is not what this would write

Each release lists the changes from the release before it, as `oasdiff changelog` reports them: the same tool as the
contract gate (gate.sh), so the page /docs/changelog and the gate cannot disagree. Levels: 3 breaking, 2 warning, 1 change.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEVELS = {"ERR": 3, "WARN": 2, "INFO": 1, 3: 3, 2: 2, 1: 1}


def version_key(path: Path) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+(\.\d+)*", path.stem):
        sys.exit(f"changelog: {path.name} is not named <version>.json")
    return tuple(int(x) for x in path.stem.split("."))


def changes(base: Path, head: Path) -> list[dict]:
    out = subprocess.run([os.environ.get("OASDIFF", "oasdiff"), "changelog", "--format", "json", str(base), str(head)],
                         check=True, capture_output=True, text=True).stdout
    items = json.loads(out) if out.strip() else []
    if isinstance(items, dict):                    # newer formats wrap the list
        items = items.get("changes") or []
    result = []
    for it in items or []:
        level = LEVELS.get(it.get("level"))
        if level is None or not it.get("text"):
            sys.exit(f"changelog: oasdiff returned a change this script cannot read: {it}")
        result.append({"level": level, "operation": it.get("operation", ""), "path": it.get("path", ""),
                       "id": it.get("id", ""), "text": it["text"]})
    return sorted(result, key=lambda c: (-c["level"], c["path"], c["operation"], c["id"], c["text"]))


def build(released: Path) -> dict:
    files = sorted(released.glob("*.json"), key=version_key)
    releases = []
    for i, f in enumerate(files):
        previous = files[i - 1] if i else None
        releases.append({"version": f.stem, "previous": previous.stem if previous else None,
                         "changes": changes(previous, f) if previous else []})
    return {"releases": releases}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--released", type=Path, default=HERE / "released")
    ap.add_argument("--out", type=Path, default=HERE.parent / "src" / "cmapi" / "contract" / "changelog.json")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = json.dumps(build(a.released), indent=2) + "\n"
    if a.check:
        if not a.out.exists() or a.out.read_text() != text:
            sys.exit(f"changelog: {a.out} is not current: run python contract/changelog.py and commit the file")
        return
    a.out.write_text(text)


if __name__ == "__main__":
    main()
