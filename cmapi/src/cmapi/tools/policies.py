"""`cmapi-tools policies`: the Kyverno bundle rendered from an instance's configuration (#212).

    cmapi-tools policies render --config-dir DIR --metadata-keys FILE --out DIR
    cmapi-tools policies check  --config-dir DIR --metadata-keys FILE --dir DIR

`render` writes what core/policygen.py renders for the instance in DIR (its tiers.yaml, metadata-keys.yaml and
instance.yaml `policy`), and removes each rendered file that the configuration no longer gives. Each instance owns the
folders env/<env>/ of its own environments, so the instances of one cluster-configs repository render into one folder. `check` exits 1 and
names each file that differs, is missing or is left over, so CI refuses a hand edit of a rendered policy and a
configuration change that was not rendered again. A file under DIR that cmapi did not render is never touched.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cmapi.core.config import load_instance
from cmapi.core.policygen import environment_of, render_bundle

MARK = "# Rendered by cmapi"


def _render(config_dir: str, metadata_keys: str) -> tuple[dict[str, str], set[str]]:
    cfg = load_instance(config_dir, metadata_keys)
    return render_bundle(cfg.tiers, cfg.metadata, cfg.policy, cfg.allowed_environments, cfg.name), cfg.allowed_environments


def _rendered_on_disk(root: Path, environments: set[str]) -> dict[str, str]:
    """The files under env/<env>/ of root, for the instance's own environments, that cmapi rendered: a policy with the
    mark, or the folder's index.json. Another instance's environments share the folder and are not this one's."""
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for f in sorted(root.rglob("*")):
        rel = str(f.relative_to(root))
        if not f.is_file() or environment_of(rel) not in environments:
            continue
        text = f.read_text()
        if (f.suffix == ".yaml" and text.startswith(MARK)) or f.name == "index.json":
            out[rel] = text
    return out


def diff(want: dict[str, str], have: dict[str, str]) -> list[str]:
    lines = [f"missing: {p}" for p in sorted(set(want) - set(have))]
    lines += [f"differs: {p}" for p in sorted(set(want) & set(have)) if want[p] != have[p]]
    lines += [f"left over: {p}" for p in sorted(set(have) - set(want))]
    return lines


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="cmapi-tools policies", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    for name, target in (("render", "--out"), ("check", "--dir")):
        p = sub.add_parser(name)
        p.add_argument("--config-dir", required=True)
        p.add_argument("--metadata-keys", required=True)
        p.add_argument(target, required=True, dest="root")
    args = ap.parse_args(argv)
    want, environments = _render(args.config_dir, args.metadata_keys)
    root = Path(args.root)
    have = _rendered_on_disk(root, environments)
    if args.command == "check":
        problems = diff(want, have)
        for line in problems:
            print(line)
        if problems:
            sys.exit(f"{len(problems)} rendered policy files do not match the configuration: "
                     "run cmapi-tools policies render")
        print(f"{len(want)} rendered policy files match the configuration")
        return
    for rel in sorted(set(have) - set(want)):
        (root / rel).unlink()
    for rel, text in want.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if have.get(rel) != text:
            f.write_text(text)
    print(f"rendered {len(want)} files into {root}")
