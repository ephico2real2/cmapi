#!/usr/bin/env python3
"""The API contract report of a Helm values change (#337): what a change of metadata-keys.yaml does to the API document.

    report.py --base DIR --head DIR --values GLOB [--values GLOB ...] --chart-base DIR --chart-head DIR
              [--helm-args "ARGS"] [--summary FILE] [--cmapi COMMIT]

A running cmapi reads metadata-keys.yaml from its ConfigMap, which `helm template` renders from the chart and the site's
values file (the value `metadata`, the text `configFiles."metadata-keys.yaml"`, or the chart's config/metadata-keys.yaml;
#335). For each values file that GLOB matches in DIR (the base tree, then the head tree), this renders the ConfigMap with
the chart of that side, takes its metadata-keys.yaml, and, where the two differ, renders the API document of each with
`cmapi-tools openapi render` on its packaged reference instance, so every difference comes from metadata-keys.yaml. oasdiff
compares the two. The changelog goes to the job summary (GitHub-flavoured Markdown), with one annotation on the values file.

Report only: a change of required keys is the operator's decision (#328, question 4), so a change, breaking or not, exits
0. The report exits 1, loudly, when it cannot say what changed: helm, cmapi-tools or oasdiff failed or is missing, a side's
metadata-keys.yaml is refused by cmapi's loader (an instance with it would not start), or a render is not a document.

oasdiff runs from an empty working directory, because it reads a .oasdiff.* file from there and a pull request could add
one (measured: `fail-on: INFO` in it turned a report into exit 1), and with --allow-external-refs=false, its documented
guard for documents that a pull request shapes (oasdiff docs/EXTERNAL-REFS.md). Never --fail-on, never --open.

The tools: CMAPI_TOOLS (default cmapi-tools), HELM (helm), OASDIFF (oasdiff), each split as a command line. Python standard
library and PyYAML only.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REFUSED = 3                      # cmapi-tools openapi: the loader refuses the configuration
LEVELS = {3: "error", 2: "warning", 1: "info"}   # oasdiff's JSON levels: ERR, WARN, INFO
SUMMARY_LIMIT = 900_000          # GitHub keeps 1 MiB of summary for each step
TIMEOUT = 300


class Failed(Exception):
    """The report cannot say what changed. The message names the step and what it printed."""


@dataclass
class Report:
    sections: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    failed: bool = False


def _command(env: str, default: str) -> list[str]:
    return shlex.split(os.environ.get(env) or default)


def _run(argv: list[str], what: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, capture_output=True, text=True, cwd=cwd, timeout=TIMEOUT)
    except FileNotFoundError as exc:
        raise Failed(f"{what}: {argv[0]} is not installed ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise Failed(f"{what}: {argv[0]} did not finish in {TIMEOUT} s") from exc


def _tail(text: str, lines: int = 12) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _escape_data(text: str) -> str:
    """The message of a workflow command (GitHub's toolkit, command.ts escapeData)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def annotation(level: str, file: str, title: str, message: str) -> str:
    return f"::{level} file={_escape_property(file)},title={_escape_property(title)}::{_escape_data(message)}"


def metadata_keys(chart: Path, values: Path, helm_args: list[str], what: str) -> str:
    """The metadata-keys.yaml that `helm template` writes into the instance's ConfigMap for this values file."""
    r = _run([*_command("HELM", "helm"), "template", "cmapi", str(chart), "-n", "cmapi", "-f", str(values), *helm_args],
             f"helm template of {what}")
    if r.returncode != 0:
        raise Failed(f"helm template of {what} exited {r.returncode}:\n{_tail(r.stderr)}")
    found = [d["data"]["metadata-keys.yaml"] for d in yaml.safe_load_all(r.stdout)
             if isinstance(d, dict) and d.get("kind") == "ConfigMap"
             and "metadata-keys.yaml" in ((d.get("data") or {})) and "instance.yaml" in (d.get("data") or {})]
    if len(found) != 1:
        raise Failed(f"helm template of {what} gave {len(found)} instance ConfigMaps with metadata-keys.yaml, not 1")
    return found[0]


def openapi(keys: str, work: Path, side: str, values: str) -> Path:
    """The API document of the reference instance with this metadata-keys.yaml."""
    src, out = work / f"{side}-metadata-keys.yaml", work / f"{side}-openapi.json"
    src.write_text(keys)
    r = _run([*_command("CMAPI_TOOLS", "cmapi-tools"), "openapi", "render", "--metadata-keys", str(src), "--out", str(out)],
             f"cmapi-tools openapi render of the {side} of {values}")
    if r.returncode == REFUSED:
        raise Failed(f"cmapi refuses the {side} metadata-keys.yaml of {values}, so an instance with it would not start:\n"
                     f"{_tail(r.stderr)}")
    if r.returncode != 0 or not out.is_file():
        raise Failed(f"cmapi-tools openapi render of the {side} of {values} exited {r.returncode}:\n{_tail(r.stderr)}")
    return out


def oasdiff(fmt: str, base: Path, head: Path, empty: Path) -> str:
    r = _run([*_command("OASDIFF", "oasdiff"), "changelog", "--allow-external-refs=false", "-f", fmt, str(base), str(head)],
             f"oasdiff changelog -f {fmt}", cwd=empty)
    if r.returncode != 0:
        raise Failed(f"oasdiff changelog -f {fmt} exited {r.returncode}:\n{_tail(r.stderr or r.stdout)}")
    return r.stdout


def nested(markdown: str) -> str:
    """oasdiff's changelog under this report's heading of the values file: its headings three levels down, one blank line
    between blocks."""
    out: list[str] = []
    for line in markdown.strip().splitlines():
        line = "###" + line if line.startswith("#") else line.rstrip()
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out)


def compare(rel: str, args: argparse.Namespace, helm_args: list[str], work: Path, report: Report) -> None:
    """One values file: its section of the summary and its annotation."""
    base_file, head_file = args.base / rel, args.head / rel
    if not head_file.is_file():
        report.sections.append(f"### `{rel}`\n\nRemoved by this change: no document to compare.\n")
        report.annotations.append(annotation("notice", rel, "API contract", "Removed: no API document to compare"))
        return
    head = metadata_keys(args.chart_head, head_file, helm_args, f"the head of {rel}")
    if not base_file.is_file():
        openapi(head, work, "head", rel)
        report.sections.append(f"### `{rel}`\n\nAdded by this change: no base document to compare. Its metadata-keys.yaml "
                               "loads and renders.\n")
        report.annotations.append(annotation("notice", rel, "API contract", "Added: no base API document to compare"))
        return
    base = metadata_keys(args.chart_base, base_file, helm_args, f"the base of {rel}")
    if base == head:
        report.sections.append(f"### `{rel}`\n\nmetadata-keys.yaml is the same on both sides: the API document does not "
                               "change.\n")
        return
    empty = Path(tempfile.mkdtemp(prefix="oasdiff-", dir=work))
    base_doc, head_doc = openapi(base, work, "base", rel), openapi(head, work, "head", rel)
    changes = json.loads(oasdiff("json", base_doc, head_doc, empty) or "[]")
    markdown = oasdiff("markdown", base_doc, head_doc, empty)
    counts = {name: sum(1 for c in changes if c.get("level") == level) for level, name in LEVELS.items()}
    breaking = counts["error"] + counts["warning"]
    line = (f"{counts['error']} breaking (error), {counts['warning']} possibly breaking (warning), "
            f"{counts['info']} other changes")
    report.sections.append(f"### `{rel}`\n\n{line}.\n\n{nested(markdown)}\n")
    report.annotations.append(annotation("warning" if breaking else "notice", rel, "API contract",
                                         f"{line}: see the job summary of this run"))


def summary_text(report: Report, cmapi: str | None) -> str:
    head = ["## API contract report", "",
            "What this change of `metadata-keys.yaml` does to the API document. Each side is rendered by "
            "`cmapi-tools openapi render` on the packaged reference instance with the `metadata-keys.yaml` that "
            "`helm template` writes into the ConfigMap, so every difference below comes from that file. oasdiff lists "
            "breaking changes as errors.", "",
            "**Report only.** A change of required keys is the operator's decision (#328, question 4); it never fails "
            "this check. Generate a client for an instance from that instance's own `/openapi.json` (docs/18).", ""]
    if cmapi:
        head += [f"cmapi `{cmapi}`.", ""]
    text = "\n".join(head) + "\n" + "\n".join(report.sections)
    if len(text.encode()) > SUMMARY_LIMIT:
        text = text.encode()[:SUMMARY_LIMIT].decode(errors="ignore") + "\n\n(cut at 900 kB: GitHub keeps 1 MiB per step)\n"
    return text


def expand(tree: Path, patterns: list[str]) -> set[str]:
    return {p.relative_to(tree).as_posix() for pattern in patterns for p in tree.glob(pattern) if p.is_file()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=Path, required=True, help="the tree of the base branch")
    ap.add_argument("--head", type=Path, required=True, help="the tree that the change makes")
    ap.add_argument("--values", action="append", required=True, help="a glob of values files, relative to each tree")
    ap.add_argument("--chart-base", type=Path, required=True, help="the cmapi chart for the base side")
    ap.add_argument("--chart-head", type=Path, required=True, help="the cmapi chart for the head side")
    ap.add_argument("--helm-args", default="", help="more arguments of helm template, such as render-only placeholders")
    ap.add_argument("--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY") or None,
                    help="where the Markdown goes; default $GITHUB_STEP_SUMMARY, else standard output")
    ap.add_argument("--cmapi", help="the cmapi commit that renders, for the summary")
    args = ap.parse_args(argv)
    report = Report()
    files = sorted(expand(args.base, args.values) | expand(args.head, args.values))
    if not files:
        report.failed = True
        report.annotations.append(annotation("error", ".github", "API contract report",
                                             f"no values file matches {args.values} on either side"))
    with tempfile.TemporaryDirectory(prefix="contract-report-") as tmp:
        for rel in files:
            work = Path(tmp) / rel.replace("/", "_")
            work.mkdir()
            try:
                compare(rel, args, shlex.split(args.helm_args), work, report)
            except Failed as exc:
                report.failed = True
                report.sections.append(f"### `{rel}`\n\n**The report failed.**\n\n```\n{exc}\n```\n")
                report.annotations.append(annotation("error", rel, "API contract report failed", str(exc)))
    text = summary_text(report, args.cmapi)
    if args.summary:
        with args.summary.open("a") as f:
            f.write(text + "\n")
    else:
        print(text)
    for line in report.annotations:
        print(line)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
