"""`cmapi-tools docs-assets`: put Swagger UI and ReDoc where /docs and /redoc read them, in a source checkout.

The image holds both bundles (Containerfile). A source checkout does not, and cmapi never loads them from a CDN
(docs/01, "API documentation"). This command fetches the two npm packages that the Containerfile names, at the versions
and SHA-256 values of its ARG lines, so the Containerfile stays the one source of both. A hash that does not match stops
the command before any file is written.

    cmapi-tools docs-assets --static-dir .static [--containerfile cmapi/Containerfile] [--registry https://registry.npmjs.org]

Then start the API with CMAPI_STATIC_DIR set to the same directory.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import tarfile
from pathlib import Path

import httpx

# package, ARG prefix, target folder under the static dir, and the members the Containerfile unpacks: {member: file name}
BUNDLES = (
    ("swagger-ui-dist", "SWAGGER_UI", "swagger-ui", {"package/swagger-ui-bundle.js": "swagger-ui-bundle.js",
                                                     "package/swagger-ui.css": "swagger-ui.css",
                                                     "package/favicon-32x32.png": "favicon-32x32.png"}),
    ("redoc", "REDOC", "redoc", {"package/bundles/redoc.standalone.js": "redoc.standalone.js"}),
)


def pinned(containerfile: Path) -> dict[str, tuple[str, str]]:
    """{ARG prefix: (version, sha256)} from the Containerfile's ARG lines."""
    args = dict(re.findall(r"^ARG\s+([A-Z_0-9]+)=(\S+)\s*$", containerfile.read_text(), flags=re.M))
    out = {}
    for _, prefix, _, _ in BUNDLES:
        try:
            out[prefix] = (args[f"{prefix}_VERSION"], args[f"{prefix}_SHA256"])
        except KeyError as exc:
            raise SystemExit(f"docs-assets: {containerfile} has no ARG {exc.args[0]}") from exc
    return out


def fetch(registry: str, containerfile: Path, static_dir: Path) -> list[Path]:
    pins = pinned(containerfile)
    unpacked: list[tuple[Path, bytes]] = []
    with httpx.Client(follow_redirects=True, timeout=60) as http:
        for package, prefix, folder, members in BUNDLES:
            version, sha = pins[prefix]
            url = f"{registry.rstrip('/')}/{package}/-/{package}-{version}.tgz"
            r = http.get(url)
            if r.status_code != 200:
                raise SystemExit(f"docs-assets: {url} answered {r.status_code}")
            got = hashlib.sha256(r.content).hexdigest()
            if got != sha:
                raise SystemExit(f"docs-assets: {url} has SHA-256 {got}, and the Containerfile pins {sha}. Nothing was written.")
            with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tar:
                for member, name in members.items():
                    f = tar.extractfile(member)
                    if f is None:
                        raise SystemExit(f"docs-assets: {url} has no file {member}")
                    unpacked.append((static_dir / folder / name, f.read()))
    written = []
    for path, data in unpacked:          # only after every hash matched
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append(path)
    return written


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="cmapi-tools docs-assets", description=__doc__.split("\n\n")[0])
    ap.add_argument("--static-dir", required=True, type=Path, help="the directory that CMAPI_STATIC_DIR will name")
    ap.add_argument("--containerfile", type=Path, default=None, help="default: ./Containerfile, then ./cmapi/Containerfile")
    ap.add_argument("--registry", default="https://registry.npmjs.org", help="the npm registry to fetch from")
    a = ap.parse_args(argv)
    containerfile = a.containerfile or next((p for p in (Path("Containerfile"), Path("cmapi/Containerfile")) if p.exists()), None)
    if containerfile is None or not containerfile.exists():
        sys.exit("docs-assets: no Containerfile found; pass --containerfile")
    for path in fetch(a.registry, containerfile, a.static_dir):
        print(path)
