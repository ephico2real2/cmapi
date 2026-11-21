#!/bin/zsh
# A/B of the P9 miss at CPU throttling 25, view 390 light, N runs each: before (origin/main's patterns) and after.
cd <worktree>/cmapi-portal-ui
S=<scratch>
O=<notes>
cp src/portal/patterns.ts $S/patterns.after.ts; cp src/portal/patternWorker.ts $S/patternWorker.after.ts
for side in before after; do
  if [ $side = before ]; then git show origin/main:cmapi-portal-ui/src/portal/patterns.ts > src/portal/patterns.ts; git show origin/main:cmapi-portal-ui/src/portal/patternWorker.ts > src/portal/patternWorker.ts;
  else cp $S/patterns.after.ts src/portal/patterns.ts; cp $S/patternWorker.after.ts src/portal/patternWorker.ts; fi
  npx vite build >/dev/null 2>&1
  for i in 1 2 3 4 5 6 7 8; do
    PROBE=1 PROBE_THROTTLE=25 PROBE_VIEW="390 light" CHECK="479-P9" node tests/api/portal.test.mjs > $O/ab-$side-$i.log 2>&1
    echo "$side $i exit=$? $(grep -oE 'PROBE-OK.*terminates [0-9]+|error is [^,]*, not [^ ]*' $O/ab-$side-$i.log | head -1)" | tee -a $O/ab-summary.txt
  done
done
cp $S/patterns.after.ts src/portal/patterns.ts; cp $S/patternWorker.after.ts src/portal/patternWorker.ts; npx vite build >/dev/null 2>&1
echo done >> $O/ab-summary.txt
