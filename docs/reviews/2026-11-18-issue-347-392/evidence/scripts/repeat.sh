#!/bin/sh
# repeat.sh <worktree> <label> <runs> -- runs tests/api/zz-stress.test.mjs <runs> times with the environment given (OUT, CHECK, VIEW,
# WIDTH, CPU_RATE, JITTER_MS, API_DELAY_MS) and writes <label>.log (each failure's assertion) and <label>.count (failures of runs).
set -u
wt=$1 label=$2 runs=$3
out=${OUT:?set OUT to the directory for the counts and logs}
cd "$wt/cmapi-portal-ui"
: > "$out/$label.log"
fails=0
i=0
while [ $i -lt "$runs" ]; do
  i=$((i + 1))
  if ! node tests/api/zz-stress.test.mjs > "$out/.run.txt" 2>&1; then
    fails=$((fails + 1))
    { echo "== run $i failed"; grep -m1 -A3 -E "Error|not ok" "$out/.run.txt"; } >> "$out/$label.log"
  fi
done
echo "$label: $fails failed of $runs runs (CHECK=${CHECK:-} VIEW=${VIEW:-} WIDTH=${WIDTH:-} CPU_RATE=${CPU_RATE:-1} JITTER_MS=${JITTER_MS:-0} API_DELAY_MS=${API_DELAY_MS:-0}) at $(date -u +%FT%TZ) on $(git -C "$wt" rev-parse --short HEAD)" | tee "$out/$label.count"
