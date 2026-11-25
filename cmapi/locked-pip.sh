#!/usr/bin/env bash
# Installs the image's pip, from the hashed lock, into the environment of <python> (#657, #658).
#
#   cmapi/locked-pip.sh <python>
#
# A new virtual environment gets the pip that its interpreter bundles (ensurepip), whatever its age: pip 25.0.1 on CI's
# runner, which is in six published advisories. cmapi/requirements.txt pins pip with the SHA-256 of each of its files, as the
# image installs it, so the entry is copied from there and installed with --require-hashes: one version, from one lock,
# with no second number to keep in step. `python -m venv --upgrade-deps` was not used: it takes "the latest version in PyPI"
# (https://docs.python.org/3/library/venv.html), unpinned and unhashed. pip does not take a hash from a constraints file for
# a requirement named on the command line (measured on pip 25.0.1), hence the copy.
set -euo pipefail
python=${1:?usage: cmapi/locked-pip.sh <python>}
lock="$(cd "$(dirname "$0")" && pwd)/requirements.txt"
entry=$(mktemp "${TMPDIR:-/tmp}/locked-pip.XXXXXX")
trap 'rm -f "$entry"' EXIT
# The pip entry: its line and the --hash continuation lines that follow it, up to the first line with no trailing backslash.
awk '/^pip==/ { on = 1 } on { print; if ($0 !~ /\\$/) exit }' "$lock" >"$entry"
if ! grep -q '^pip==' "$entry" || ! grep -q -- '--hash=sha256:' "$entry"; then
  echo "locked-pip.sh: no hashed pip entry in $lock" >&2
  exit 2
fi
"$python" -m pip install --quiet --disable-pip-version-check --require-hashes --no-deps -r "$entry"
"$python" -m pip --version
