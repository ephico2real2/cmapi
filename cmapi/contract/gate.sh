#!/usr/bin/env bash
# The contract gate (#131): fail when the head document breaks the base document.
# Usage: contract/gate.sh <base openapi.json> <head openapi.json>
# oasdiff's ERR level is a definite breaking change. accepted-breaking.txt names the ones that were accepted, each with its reason.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BASE=${1:?base document}
HEAD=${2:?head document}
OASDIFF=${OASDIFF:-oasdiff}
"$OASDIFF" breaking --fail-on ERR --err-ignore "$HERE/accepted-breaking.txt" "$BASE" "$HEAD"
