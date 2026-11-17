#!/bin/bash
# helm template of the chart with the CRC site file, every Secret dropped (their values are random per render).
# Usage: render-nosecrets.sh <worktree> <out> [extra helm args...]
set -euo pipefail
WT=$1; OUT=$2; shift 2
DIG=sha256:$(printf 'a%.0s' $(seq 1 64))
helm template cmapi "$WT/deploy/helm/cmapi" -n cmapi -f "$WT/deploy/environments/crc.yaml" \
  --set cmapi.digest=$DIG --set cmapi_portal.digest=$DIG --set trustedCA.certificates=x "$@" |
  /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -c '
import sys, yaml
docs = [d for d in yaml.safe_load_all(sys.stdin) if d and d.get("kind") != "Secret"]
sys.stdout.write(yaml.safe_dump_all(docs, sort_keys=True, width=200))' > "$OUT"
