#!/usr/bin/env python3
"""Fetch the base images of a Containerfile into an OCI layout before the build, with retries, each checked by digest (#663).

Why. CI builds on docker/setup-buildx-action's docker-container driver, whose BuildKit pulls each FROM image itself. BuildKit
v0.35.1 retries a 5xx, an EOF or a reset connection (util/resolver/retryhandler/retry.go, retryError), not a 4xx, and neither
docker/build-push-action v7.4.0 nor docker/setup-buildx-action v4.4.1 has a retry input. A 401 from registry.redhat.io's
anonymous token endpoint stopped images-pr on PR #659 (run 45492928616, job 138795724679), and the re-run of the same commit
passed. A `docker pull` beforehand would not help: that driver "can't load an image from the Docker store as it's isolated"
(docs.docker.com, "Named contexts with GitHub Actions").

What. Each image a FROM names is fetched with skopeo: the manifest the FROM pins, and for an index the one manifest of
--platform, with that manifest's config and layers. Each fetch is tried --attempts times, waiting --delay seconds and then
twice as long each time: skopeo's own --retry-times does not retry an unauthorized answer (containers/common pkg/retry,
IsErrorRetryable). One failure is never tried again: a manifest or blob that is not its digest, because another attempt cannot
make wrong bytes right. skopeo checks each blob against its digest as it copies it, and the manifest of a copy against the
digest asked for; `inspect --raw` checks the manifest in skopeo 1.24.1 and not in 1.13.3, the runner's, so this script checks
the pinned manifest against its SHA-256 itself. So a retry can only add verified bytes. BuildKit checks each again as it
reads it from the layout (containerd content.Copy, with the digest it expects).

The script prints one build context per image, `<FROM ref>=oci-layout://<layout>@<digest>`, for build-push-action's
build-contexts. BuildKit then reads that image from the layout, through the build's session, and does not ask a registry for
it (`docker buildx build --build-context`, "Source an image from a local OCI layout compliant directory").

The layout holds the registry's own bytes. skopeo copies each image straight into it (oci:), and --preserve-digests makes
it keep the manifest it fetched, a Docker v2s2 one too, or fail. For an index this script adds the index itself, and the
layout holds only the --platform manifest's blobs; the OCI image layout allows a layout to miss referenced blobs (image-spec
v1.1.1, image-layout.md). BuildKit finds each image by its digest and does not read the layout's index.json.

Only a FROM image is fetched. An image named by COPY --from= or RUN --mount=from= would be pulled by BuildKit itself, with
no retry and no check here, so the script refuses one: make it a FROM stage. It refuses a `# syntax=` parser directive for
the same reason: BuildKit pulls that frontend image itself (frontend/dockerfile/builder, forwardGateway).

Python standard library and the skopeo on PATH. TLS stays as skopeo's defaults: this script has no switch to turn it off.
usage: base-images.py --containerfile FILE --layout DIR --platform OS/ARCH[/VARIANT] --attempts N --delay SECONDS
Exit 1 on any failure, naming the image and the check that failed; 2 on a wrong argument.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

INDEX_TYPES = {"application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"}
MANIFEST_TYPES = {"application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"}
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
FROM = re.compile(r"\s*FROM\s+(?:--platform=\S+\s+)?(?P<ref>\S+)(?:\s+AS\s+(?P<stage>\S+))?\s*", re.IGNORECASE)
SKOPEO_TIMEOUT = 600  # seconds for one skopeo command; a hung transfer counts as a failed attempt
# An image another instruction names: COPY --from=, RUN --mount=...,from=. BuildKit pulls it unless it is a stage.
OTHER_FROM = re.compile(r"(?:--from=|--mount=(?:\S*,)?from=)([^\s,]+)", re.IGNORECASE)
# A parser directive, as BuildKit reads one: `# syntax=` (or `// syntax=`) sends the build to that frontend image.
DIRECTIVE = re.compile(r"(?:#|//)\s*(syntax|escape|check)\s*=\s*\S", re.IGNORECASE)
# skopeo's own digest checks, as it words them: a blob (containers/image copy/digesting_reader.go), a manifest
# (internal/image/unparsed.go), a config (internal/image/docker_schema2.go and oci.go: "Download config.json digest … does not
# match expected …" in v5.26.2, "config validation failed: blob digest … does not match expected …" in v5.41.2).
MISMATCH = re.compile(r"Digest did not match|does not match provided manifest digest|does not match expected")


class Refused(Exception):
    """A check failed, or every attempt did: the build must not start."""


def base_images(containerfile: str) -> list[str]:
    """Each registry image the Containerfile's FROM lines name, in order, once. A stage name or scratch is not one."""
    stages, refs = set(), []
    # utf-8-sig: BuildKit drops a byte-order mark before it reads the first line (parser.go, discardBOM), so a FROM behind
    # one is still a FROM to the build.
    with open(containerfile, encoding="utf-8-sig") as f:
        lines = f.readlines()
    # The parser directives lead the file, after a #! line if there is one (parser/directives.go, parseDirective).
    start = 1 if lines and lines[0].startswith("#!") else 0
    for n, line in enumerate(lines[start:], start + 1):
        directive = DIRECTIVE.match(line)
        if not directive:
            break
        if directive[1].lower() == "syntax":
            raise Refused(f"{containerfile}:{n}: a syntax directive makes BuildKit pull that frontend image itself, with no "
                          "retry and no check here; remove it")
    for n, line in enumerate(lines, 1):
        if not re.match(r"\s*FROM\b", line, re.IGNORECASE):
            if not line.lstrip().startswith("#"):
                for other in OTHER_FROM.findall(line):
                    if not other.isdigit() and other.lower() not in stages:
                        raise Refused(f"{containerfile}:{n}: from={other} names an image, not a stage; only a FROM image "
                                      "is fetched and checked here, so make it a FROM stage")
            continue
        m = FROM.fullmatch(line.rstrip("\n"))
        if not m:
            raise Refused(f"{containerfile}:{n}: a FROM line this script cannot read: {line.strip()}")
        ref = m["ref"]
        if ref.lower() not in stages and ref.lower() != "scratch":
            if "$" in ref:
                raise Refused(f"{containerfile}:{n}: FROM {ref} is set by an ARG, so its digest cannot be checked here")
            if not SHA256.fullmatch(ref.partition("@")[2]):
                raise Refused(f"{containerfile}:{n}: FROM {ref} is not pinned by a sha256 digest")
            if ref not in refs:
                refs.append(ref)
        if m["stage"]:
            stages.add(m["stage"].lower())
    if not refs:
        raise Refused(f"{containerfile}: no FROM line names a registry image")
    return refs


def skopeo(*args: str) -> bytes:
    return subprocess.run(["skopeo", *args], check=True, capture_output=True, timeout=SKOPEO_TIMEOUT).stdout


def retried(what: str, attempts: int, delay: float, action):
    """action(), tried up to attempts times with a doubling wait. A Refused from it is final, and so is a digest that
    skopeo found wrong: the same bytes would come again."""
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            why = (stderr.strip().splitlines() or [f"timed out after {SKOPEO_TIMEOUT} s"])[-1]
            if MISMATCH.search(stderr):
                raise Refused(f"{what}: not tried again: {why}") from e
            if attempt == attempts:
                raise Refused(f"{what}: failed {attempts} times; the last: {why}") from e
            wait = delay * 2 ** (attempt - 1)
            print(f"{what}: attempt {attempt} of {attempts} failed ({why}); trying again in {wait:g} s", file=sys.stderr)
            time.sleep(wait)


def media_type(doc: dict) -> str:
    # An OCI index or manifest may leave mediaType out (image-spec, image-index.md and manifest.md: "SHOULD").
    return doc.get("mediaType") or ("application/vnd.oci.image.index.v1+json" if "manifests" in doc
                                    else "application/vnd.oci.image.manifest.v1+json")


def platform_entry(index: dict, platform: str, ref: str) -> dict:
    """The one entry of the index for platform; none or several is a refusal, so BuildKit can only pick that one."""
    want = platform.split("/")
    matches = [e for e in index.get("manifests", []) if media_type(e) in MANIFEST_TYPES
               and [(e.get("platform") or {}).get(k, "") for k in ("os", "architecture", "variant")][:len(want)] == want]
    if len(matches) != 1:
        raise Refused(f"{ref}: the index has {len(matches)} image manifests for {platform}, not one")
    return matches[0]


def checked_digest(ref: str, digest) -> str:
    """A digest read from a manifest, before it names a file or an image: only sha256 and its 64 hex digits."""
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise Refused(f"{ref}: a manifest names {digest!r}, not a sha256 digest")
    return digest


def fetch(ref: str, layout: str, platform: str, attempts: int, delay: float) -> None:
    """Copies the image that ref pins into the layout: the pinned manifest, and for an index its one image for platform."""
    name, _, pinned = ref.partition("@")
    repo = re.sub(r":[^/]*$", "", name)  # containers/image takes a tag or a digest, not both; the digest is what is checked
    raw = retried(f"{ref}: the manifest", attempts, delay, lambda: skopeo("inspect", "--raw", f"docker://{repo}@{pinned}"))
    if "sha256:" + hashlib.sha256(raw).hexdigest() != pinned:
        raise Refused(f"{ref}: the registry's manifest does not match the pinned digest")
    top = json.loads(raw)
    kind = media_type(top)
    if kind in INDEX_TYPES:
        image = checked_digest(ref, platform_entry(top, platform, ref).get("digest"))
    elif kind in MANIFEST_TYPES:
        image = pinned
    else:
        raise Refused(f"{ref}: the manifest is a {kind}, not an image or an index")
    # skopeo checks the manifest against the digest asked for and each blob against its own, and files them under their
    # digests; --preserve-digests makes it keep a Docker v2s2 manifest as it is, or fail. An OCI layout cannot hold
    # signatures (oci/layout/oci_dest.go: "Pushing signatures for OCI images is not supported"), so where registries.d names
    # a lookaside for the registry, as Fedora's containers-common does for registry.access.redhat.com, a copy that kept
    # them would fail every attempt. This script checks no signature, so none is copied.
    retried(f"{ref}: the {platform} image {image}", attempts, delay,
            lambda: skopeo("copy", "--quiet", "--preserve-digests", "--remove-signatures", f"docker://{repo}@{image}", f"oci:{layout}"))
    if image != pinned:  # the index itself, so that the build can be given the pinned digest; its bytes were checked above
        with open(os.path.join(layout, "blobs", "sha256", pinned.split(":", 1)[1]), "wb") as f:
            f.write(raw)
    print(f"{ref}: {image} for {platform}, in the layout", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--containerfile", required=True)
    p.add_argument("--layout", required=True, help="the OCI layout directory to create; it must not exist yet")
    p.add_argument("--platform", required=True, help="the build's platform, for example linux/amd64")
    p.add_argument("--attempts", required=True, type=int)
    p.add_argument("--delay", required=True, type=float, help="seconds before the second attempt; each later wait doubles")
    a = p.parse_args()
    if a.attempts < 1 or a.delay < 0 or not re.fullmatch(r"[a-z0-9]+/[a-z0-9]+(/[a-z0-9]+)?", a.platform):
        p.error("--attempts must be at least 1, --delay not negative, and --platform OS/ARCH[/VARIANT]")
    layout = os.path.abspath(a.layout)
    try:
        if ":" in layout:
            raise Refused(f"--layout {layout}: skopeo's oci: transport reads what follows a colon as a tag")
        refs = base_images(a.containerfile)
        os.makedirs(layout)
        for ref in refs:
            try:
                fetch(ref, layout, a.platform, a.attempts, a.delay)
            except (ValueError, KeyError, TypeError) as e:
                raise Refused(f"{ref}: a manifest this script cannot read ({e!r})") from e
    except (Refused, OSError) as e:
        print(f"base-images: {e}", file=sys.stderr)
        return 1
    for ref in refs:
        print(f"{ref}=oci-layout://{layout}@{ref.partition('@')[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
