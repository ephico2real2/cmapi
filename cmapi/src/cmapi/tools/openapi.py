"""`cmapi-tools openapi`: the API document of an instance, built offline from its configuration (#337).

    cmapi-tools openapi render --metadata-keys FILE [--config-dir DIR] --out FILE

`render` writes the document that an instance with these files serves at /openapi.json, through the code that serves it
(`cmapi.main.api_app`), in the form of cmapi/contract/openapi.json: sorted keys, two-space indent, one final newline. It
needs no database, identity provider, cluster, Git host or Kyverno, and opens no connection.

With no --config-dir the instance is the reference instance packaged beside this module (reference_instance/: the
service suite's test instance, whose document is the committed contract). Rendered for two metadata-keys.yaml files on
that one instance, every difference between the two documents comes from metadata-keys.yaml. The contract report of a
Helm values change runs it that way (cmapi/contract/report.py).

Exit 0: written. Exit 3: the configuration is refused, and the loader's message is on stderr; an instance with these
files would not start. Any other exit: the tool failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from cmapi.core.config import load_instance

REFERENCE_INSTANCE = Path(__file__).with_name("reference_instance")
REFUSED = 3
# What every document of an instance that serves the namespaces plugin holds; a render that lost it is a broken tool, and
# a report on it would say "no changes" about a document that says nothing.
NAMESPACES = "/api/v1/clusters/{cluster_id}/namespaces"


class Refused(Exception):
    """The instance's loader refuses the configuration."""


def problems_of(doc: dict[str, Any], namespaces_enabled: bool) -> list[str]:
    """Why a rendered document cannot be the one an instance serves: empty when it can."""
    problems = []
    if not str(doc.get("openapi", "")).startswith("3.1."):
        problems.append(f"openapi is {doc.get('openapi')!r}, not 3.1.x")
    paths = doc.get("paths") or {}
    if not paths:
        problems.append("the document has no paths")
    elif namespaces_enabled and "post" not in (paths.get(NAMESPACES) or {}):
        problems.append(f"the namespaces plugin is enabled and the document has no POST {NAMESPACES}")
    return problems


def load(metadata_keys: Path, config_dir: Path | None) -> Any:
    """The instance's configuration, as cmapi loads it at start. Raises Refused when that load would stop the instance."""
    try:
        return load_instance(config_dir or REFERENCE_INSTANCE, metadata_keys)
    except (ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        # ValueError covers the loader's ConfigError; KeyError and TypeError a file without a stanza the loader reads.
        raise Refused(f"{type(exc).__name__}: {exc}") from exc


def render(cfg: Any) -> str:
    """The document's text, checked to be one that an instance serves."""
    # Imported here: cmapi.main brings in the whole API, which only this command of cmapi-tools needs.
    from cmapi.main import openapi_document
    doc = openapi_document(cfg)
    problems = problems_of(doc, "namespaces" in cfg.plugins.enabled)
    if problems:
        raise RuntimeError("the rendered document is not one that an instance serves: " + "; ".join(problems))
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="cmapi-tools openapi", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("render", help="write the instance's OpenAPI document")
    p.add_argument("--metadata-keys", required=True, type=Path, help="the instance's metadata-keys.yaml")
    p.add_argument("--config-dir", type=Path, help="the instance's other files; default: the packaged reference instance")
    p.add_argument("--out", required=True, type=Path, help="where to write the document")
    args = ap.parse_args(argv)
    for path in (args.metadata_keys, args.config_dir):
        if path is not None and not path.exists():
            sys.exit(f"cmapi-tools openapi: {path} does not exist")
    try:
        cfg = load(args.metadata_keys, args.config_dir)
    except Refused as exc:
        print(f"cmapi-tools openapi: the configuration is refused: {exc}", file=sys.stderr)
        sys.exit(REFUSED)
    text = render(cfg)
    args.out.write_text(text)
    print(f"wrote {args.out} ({len(text)} bytes)")
