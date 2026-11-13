#!/usr/bin/env python3
"""Hold each `file:line` citation of the documents to the code that it names (#178).

    python scripts/doc-citations.py --check       exit 1 when a cited range is not the text that the lock holds for it
    python scripts/doc-citations.py --relocate    move each citation whose text is now at one other place in its file
    python scripts/doc-citations.py --write       record the cited text of each citation, after a person read each one
    python scripts/doc-citations.py --list        each citation with the file and the lines that it resolves to

docs/14, docs/15 and docs/16 cite code as `path:line` or `path:start-end`. A change to a cited file moves its lines, and
the citation then points at other code. docs/citations.lock.json holds, for each citation, the text of the cited lines.
--check compares that text with the file. When it differs, the lines moved or the code changed:

- Moved: the same text is at one other place in the file. --relocate writes the new line numbers into the document and
  the lock. No person has to read anything, because the cited text is the same.
- Changed, or at more than one place: a person reads the code and the sentence, corrects the citation, and runs --write.

A citation can name a file in short (`authz.py:47`, `core/db/repo.py:112`) or only a line (`:150`, after a citation of the
same file). A short name is the file of the nearest earlier citation in the document with that ending, or else the one
tracked file with that ending. A name that fits more than one file, with no earlier citation to decide, is an error.
Standard library and git only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("docs/14-authorization.md", "docs/15-keycloak-integration.md", "docs/16-data-model.md")
LOCK = "docs/citations.lock.json"
# `path:12`, `path:12-18` or the continuation `:12`, each in backticks. A path ends in a file extension that starts with a letter,
# so `127.0.0.1:55432` is not a citation.
CITATION = re.compile(r"`(?P<path>[A-Za-z0-9_./-]+\.[A-Za-z][A-Za-z0-9]*)?:(?P<start>\d+)(?:-(?P<end>\d+))?`")


@dataclass
class Citation:
    doc: str
    line: int                 # the line of the document
    span: tuple[int, int]     # where the citation is in that line
    written: str              # the path as the document writes it, or "" for a continuation
    path: str                 # the tracked file
    start: int
    end: int

    @property
    def key(self) -> str:
        return f"{self.doc}|{self.path}|{self.start}-{self.end}"


class CitationError(Exception):
    pass


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files"], check=True, capture_output=True, text=True).stdout
    return [p for p in out.splitlines() if p]


def citations(root: Path, docs: tuple[str, ...] = DOCS) -> list[Citation]:
    files = tracked(root)
    found: list[Citation] = []
    for doc in docs:
        earlier: list[str] = []                      # the files cited so far in this document, newest last
        for number, text in enumerate((root / doc).read_text().splitlines(), 1):
            for m in CITATION.finditer(text):
                written = m.group("path") or ""
                where = f"{doc}:{number}"
                if not written:
                    if not earlier:
                        raise CitationError(f"{where}: `{m.group(0)[1:-1]}` names no file, and no citation comes before it")
                    path = earlier[-1]
                else:
                    path = _resolve(written, earlier, files, where)
                    earlier.append(path)
                start = int(m.group("start"))
                end = int(m.group("end") or start)
                if end < start:
                    raise CitationError(f"{where}: `{m.group(0)[1:-1]}` ends before it starts")
                found.append(Citation(doc, number, m.span(), written, path, start, end))
    return found


def _resolve(written: str, earlier: list[str], files: list[str], where: str) -> str:
    if written in files:
        return written
    for path in reversed(earlier):
        if path.endswith("/" + written):
            return path
    fits = [p for p in files if p.endswith("/" + written)]
    if len(fits) == 1:
        return fits[0]
    if not fits:
        raise CitationError(f"{where}: no tracked file is or ends with {written}")
    raise CitationError(f"{where}: {written} fits {len(fits)} files ({', '.join(sorted(fits)[:4])}): write more of the path")


def cited_text(root: Path, c: Citation) -> list[str] | None:
    """The cited lines without their line ends and trailing spaces, or None when the file is shorter than the range."""
    lines = (root / c.path).read_text().splitlines()
    if c.end > len(lines):
        return None
    return [line.rstrip() for line in lines[c.start - 1:c.end]]


def places(root: Path, path: str, text: list[str]) -> list[int]:
    """Each line number where this text starts in the file."""
    lines = [line.rstrip() for line in (root / path).read_text().splitlines()]
    n = len(text)
    return [i + 1 for i in range(len(lines) - n + 1) if lines[i:i + n] == text]


def load_lock(root: Path) -> dict[str, list[str]]:
    path = root / LOCK
    return json.loads(path.read_text()) if path.exists() else {}


def write_lock(root: Path, lock: dict[str, list[str]]) -> None:
    (root / LOCK).write_text(json.dumps(dict(sorted(lock.items())), indent=1) + "\n")


def check(root: Path) -> list[str]:
    """One line for each citation that does not hold, and one for each entry of the lock that no document cites."""
    lock, problems, seen = load_lock(root), [], set()
    for c in citations(root):
        seen.add(c.key)
        where = f"{c.doc}:{c.line}: `{c.path}:{c.start}{'' if c.end == c.start else f'-{c.end}'}`"
        want = lock.get(c.key)
        if want is None:
            problems.append(f"{where} is not in {LOCK}: read the cited lines, then run --write")
            continue
        have = cited_text(root, c)
        if have == want:
            continue
        at = places(root, c.path, want)
        if len(at) == 1:
            problems.append(f"{where} moved to line {at[0]}: run --relocate")
        elif at:
            problems.append(f"{where} changed, and its text is now at lines {at}: read them, correct the citation, then run --write")
        else:
            problems.append(f"{where} changed: the cited code is not in the file any more. Read the code, correct the citation, then run --write")
    for key in sorted(set(lock) - seen):
        problems.append(f"{LOCK} holds {key}, which no document cites: run --write")
    return problems


def relocate(root: Path) -> tuple[int, list[str]]:
    """Move each citation whose text is at one other place. Returns the count moved and what still needs a person."""
    lock, moved, left = load_lock(root), 0, []
    by_doc: dict[str, list[tuple[Citation, int]]] = {}
    for c in citations(root):
        want = lock.get(c.key)
        if want is None or cited_text(root, c) == want:
            continue
        at = places(root, c.path, want)
        if len(at) == 1:
            by_doc.setdefault(c.doc, []).append((c, at[0]))
        else:
            left.append(f"{c.doc}:{c.line}: `{c.path}:{c.start}`")
    for doc, changes in by_doc.items():
        lines = (root / doc).read_text().split("\n")
        # From the right of each line to its left, so that an earlier span keeps its place.
        for c, new_start in sorted(changes, key=lambda x: (x[0].line, x[0].span[0]), reverse=True):
            new_end = new_start + (c.end - c.start)
            text = lines[c.line - 1]
            numbers = f"{new_start}" if new_end == new_start else f"{new_start}-{new_end}"
            lines[c.line - 1] = text[:c.span[0]] + f"`{c.written}:{numbers}`" + text[c.span[1]:]
            lock[f"{c.doc}|{c.path}|{new_start}-{new_end}"] = lock.pop(c.key)
            moved += 1
        (root / doc).write_text("\n".join(lines))
    if moved:
        write_lock(root, lock)
    return moved, left


def record(root: Path) -> int:
    lock = {}
    for c in citations(root):
        text = cited_text(root, c)
        if text is None:
            raise CitationError(f"{c.doc}:{c.line}: {c.path} has no line {c.end}")
        lock[c.key] = text
    write_lock(root, lock)
    return len(lock)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Hold each file:line citation of docs/14, docs/15 and docs/16 to its code.")
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("check", "relocate", "write", "list"):
        mode.add_argument(f"--{name}", action="store_true")
    parser.add_argument("--root", default=str(ROOT), help="the repository (the tests give a copy)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.list:
            for c in citations(root):
                print(f"{c.doc}:{c.line}\t{c.path}:{c.start}-{c.end}")
            return 0
        if args.write:
            print(f"doc-citations: {record(root)} citations recorded in {LOCK}")
            return 0
        if args.relocate:
            moved, left = relocate(root)
            print(f"doc-citations: {moved} citations moved")
            for line in left:
                print(f"doc-citations: a person must read {line}", file=sys.stderr)
            return 1 if left else 0
        problems = check(root)
    except CitationError as exc:
        print(f"doc-citations: {exc}", file=sys.stderr)
        return 2
    for line in problems:
        print(f"doc-citations: {line}", file=sys.stderr)
    print(f"doc-citations: {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
