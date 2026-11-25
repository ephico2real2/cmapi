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
twice as long each time, whatever the error: skopeo's own --retry-times does not retry an unauthorized answer
(containers/common pkg/retry, IsErrorRetryable). skopeo checks the manifest against the pinned digest and each blob against
its digest as it fetches them, and fails the attempt when one does not match. This script then checks every manifest and blob
against its SHA-256 again before it goes in the layout, and a mismatch there is final. So a retry can only add verified bytes.

The script prints one build context per image, `<FROM ref>=oci-layout://<layout>@<digest>`, for build-push-action's
build-contexts. BuildKit then reads that image from the layout, through the build's session, and does not ask a registry for
it (`docker buildx build --build-context`, "Source an image from a local OCI layout compliant directory").

The layout holds the registry's own bytes. skopeo writes the manifest it fetched unchanged to a dir: directory
(--preserve-digests makes it fail rather than change one), and this script files each blob under its digest. A copy to an
oci: layout instead would convert a Docker v2s2 manifest, as the UBI base is, to OCI and change its digest
(containers/image oci/layout: an OCI layout destination takes only OCI manifest types). An index keeps only the --platform
manifest's blobs; the OCI image layout allows a layout to miss referenced blobs (image-spec v1.1.1, image-layout.md).

Python standard library and the skopeo on PATH. TLS stays as skopeo's defaults: this script has no switch to turn it off.
usage: base-images.py --containerfile FILE --layout DIR --platform OS/ARCH[/VARIANT] --attempts N --delay SECONDS
Exit 1 on any failure, naming the image and the check that failed.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

INDEX_TYPES = {"application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"}
MANIFEST_TYPES = {"application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"}
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
FROM = re.compile(r"\s*FROM\s+(?:--platform=\S+\s+)?(?P<ref>\S+)(?:\s+AS\s+(?P<stage>\S+))?\s*", re.IGNORECASE)
SKOPEO_TIMEOUT = 600  # seconds for one skopeo command; a hung transfer counts as a failed attempt


class Refused(Exception):
    """A check failed, or every attempt did: the build must not start."""


def base_images(containerfile: str) -> list[str]:
    """Each registry image the Containerfile's FROM lines name, in order, once. A stage name or scratch is not one."""
    stages, refs = set(), []
    with open(containerfile) as f:
        for n, line in enumerate(f, 1):
            if not re.match(r"\s*FROM\b", line, re.IGNORECASE):
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


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def skopeo(*args: str) -> bytes:
    return subprocess.run(["skopeo", *args], check=True, capture_output=True, timeout=SKOPEO_TIMEOUT).stdout


def retried(what: str, attempts: int, delay: float, action):
    """action(), tried up to attempts times with a doubling wait; a Refused from it is final and not retried."""
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            why = (stderr.strip().splitlines() or [f"timed out after {SKOPEO_TIMEOUT} s"])[-1]
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


def put_blob(layout: str, digest: str, src: str) -> None:
    dest = os.path.join(layout, "blobs", "sha256", digest.split(":", 1)[1])
    if os.path.exists(dest):
        os.remove(src)  # the same digest was filed by an earlier image, and was checked then
    else:
        os.replace(src, dest)


def fetch(ref: str, layout: str, platform: str, attempts: int, delay: float) -> tuple[str, int, str]:
    """Files the image that ref pins into the layout; returns the pinned manifest's (media type, size, digest)."""
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

    work = os.path.join(layout, "work")

    def copy():
        shutil.rmtree(work, ignore_errors=True)  # each attempt starts from nothing
        skopeo("copy", "--quiet", "--preserve-digests", f"docker://{repo}@{image}", f"dir:{work}")

    retried(f"{ref}: the {platform} image {image}", attempts, delay, copy)
    manifest_path = os.path.join(work, "manifest.json")
    if sha256_file(manifest_path) != image:
        raise Refused(f"{ref}: the copied manifest is not {image}")
    with open(manifest_path, "rb") as f:
        manifest = json.load(f)
    for blob in [manifest["config"], *manifest["layers"]]:
        path = os.path.join(work, checked_digest(ref, blob["digest"]).split(":", 1)[1])
        if not os.path.isfile(path) or os.path.getsize(path) != blob["size"] or sha256_file(path) != blob["digest"]:
            raise Refused(f"{ref}: the blob {blob['digest']} is missing, or its size or SHA-256 does not match")
        put_blob(layout, blob["digest"], path)
    put_blob(layout, image, manifest_path)
    if image != pinned:
        index_path = os.path.join(work, "index.json")
        with open(index_path, "wb") as f:
            f.write(raw)
        put_blob(layout, pinned, index_path)
    shutil.rmtree(work)
    print(f"{ref}: {len(manifest['layers'])} layers of {image} for {platform}, each checked by SHA-256", file=sys.stderr)
    return kind, len(raw), pinned


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
        refs = base_images(a.containerfile)
        os.makedirs(os.path.join(layout, "blobs", "sha256"))
        descriptors = []
        for ref in refs:
            try:
                kind, size, digest = fetch(ref, layout, a.platform, a.attempts, a.delay)
            except (ValueError, KeyError, TypeError) as e:
                raise Refused(f"{ref}: a manifest this script cannot read ({e!r})") from e
            descriptors.append({"mediaType": kind, "digest": digest, "size": size,
                                "annotations": {"org.opencontainers.image.ref.name": ref}})
    except (Refused, OSError) as e:
        print(f"base-images: {e}", file=sys.stderr)
        return 1
    with open(os.path.join(layout, "oci-layout"), "w") as f:
        json.dump({"imageLayoutVersion": "1.0.0"}, f)
    with open(os.path.join(layout, "index.json"), "w") as f:
        json.dump({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": descriptors}, f)
    for d in descriptors:
        print(f"{d['annotations']['org.opencontainers.image.ref.name']}=oci-layout://{layout}@{d['digest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
