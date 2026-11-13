#!/usr/bin/env bash
# The Spectral lint of the OpenAPI document (#143, docs/01 "API documentation", CI gate 1).
# Usage: contract/lint.sh [document]        default: contract/openapi.json
# It fails on an error of cmapi's ruleset (spectral/.spectral.yaml) and on a warning of Spectral's own OpenAPI rules.
# Spectral comes from spectral/package-lock.json: run `npm ci --ignore-scripts` in contract/spectral one time.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DOCUMENT=${1:-$HERE/openapi.json}
SPECTRAL=$HERE/spectral/node_modules/.bin/spectral
[ -x "$SPECTRAL" ] || { echo "lint: Spectral is not installed: run 'npm ci --ignore-scripts' in $HERE/spectral" >&2; exit 2; }
"$SPECTRAL" lint "$DOCUMENT" --ruleset "$HERE/spectral/.spectral.yaml" --fail-severity warn "${@:2}"
