#!/usr/bin/env bash
# Regenerates the hashed lock files (#655), with uv (0.13.7 or later; https://docs.astral.sh/uv/getting-started/installation/):
#
#   cmapi/requirements.txt        what the image installs: pyproject.toml's dependencies and requirements-image.in
#   cmapi/audit/requirements.txt  the audit's own tools: audit/requirements.in
#
# pyproject.toml stays the source of cmapi's direct pins. The locks add every transitive package at an exact version, with
# the SHA-256 of each of its files on PyPI, so pip's --require-hashes installs exactly those files or fails.
#
#   cmapi/lock.sh                               after a pin changes: every other locked version is kept
#   cmapi/lock.sh --upgrade-package <name>      also moves <name> to its newest release that passes the cooldown
#   cmapi/lock.sh --upgrade                     re-resolves everything
#
# The resolution is universal (one file for the image, CI and a developer's machine; markers select per platform) for
# Python 3.12, the image's. A release newer than UV_EXCLUDE_NEWER (14 days unless set) is not picked: the owner's rule is the
# newest release that is at least two weeks old. For an urgent fix, name the package's own cutoff, for example
# `cmapi/lock.sh --upgrade-package pyjwt --exclude-newer-package pyjwt=2026-11-24T00:00:00Z`, and say why in the pull request.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
command -v uv >/dev/null || { echo "lock.sh: uv is not installed (pip install 'uv>=0.13.7')" >&2; exit 2; }
export UV_EXCLUDE_NEWER="${UV_EXCLUDE_NEWER:-14 days}"
compile() {
  uv pip compile --quiet --universal --python-version 3.12 --generate-hashes --custom-compile-command "cmapi/lock.sh" "$@"
}
compile pyproject.toml requirements-image.in -o requirements.txt "$@"
compile audit/requirements.in -o audit/requirements.txt "$@"
echo "lock.sh: wrote cmapi/requirements.txt and cmapi/audit/requirements.txt (uv $(uv --version | cut -d' ' -f2), releases older than $UV_EXCLUDE_NEWER)"
