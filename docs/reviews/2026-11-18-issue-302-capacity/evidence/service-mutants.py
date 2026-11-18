#!/usr/bin/env python3
"""The service mutants of #302 Capacity (the arbitration's "mutants per the arbitration", the server side of designs A §8 and B §7).

Each mutant breaks one rule in cmapi/src, the capacity service tests run through the shared-lock runner, and the run must fail.
The source is restored after each one, and a check at the end says so. Usage, from anywhere:

    service-mutants.py <worktree> <log dir> <suite.sh>

Standard library only. The runner is the workbench's suite.sh, which holds the one service-test database lock.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS = ["tests/service/test_capacity_ledger_302.py", "tests/service/test_capacity_302.py",
         "tests/service/test_capacity_unknown_393.py"]
SRC = "cmapi/src/cmapi/"
# (what it breaks, file, the text, its replacement)
MUTANTS = [
    ("the plan's check uses stale figures as fresh (fresh=True restored)", "core/capacity_backend.py",
     'if read.state != "ok" or read.totals is None:', "if read.totals is None:"),
    ("an unknown commitment is 0 in the API", "plugins/capacity/router.py",
     "committed=totals.committed[r] if totals else None,", "committed=totals.committed[r] if totals else 0,"),
    ("a group averages its clusters' ratios", "core/capacity.py",
     "commitment = round(committed / limit, 4) if limit > 0 else None",
     'commitment = round(sum(f["commitment"] for _, f in rows) / len(rows), 4)'),
    ("headroom is not floored per cluster", "core/capacity.py", 'max(f["headroom"], 0)', 'f["headroom"]'),
    ("the largest placement is the group's sum", "core/capacity.py",
     '"largestPlacement": {"value": floored[0][0], "clusterId": floored[0][1]}}',
     '"largestPlacement": {"value": sum(h for h, _ in floored), "clusterId": floored[0][1]}}'),
    ("a group's status is its best cluster's", "core/capacity.py",
     "return max(known, key=STATUSES.index) if known else None", "return min(known, key=STATUSES.index) if known else None"),
    ("an excluded cluster is summed into its group", "plugins/capacity/router.py", "            if reason is None:",
     "            if True:"),
    ("the environment filter is dropped", "plugins/capacity/router.py", "        if cenv not in envs:", "        if False:"),
    ("the overcommit is ignored", "core/capacity.py", "    limit = limit_of(size, over) if size is not None else None",
     "    limit = limit_of(size, Decimal(1)) if size is not None else None"),
    ("the ETag is over a body with the read's seconds", "plugins/capacity/router.py",
     ".replace(second=0, microsecond=0)", ".replace(microsecond=0)"),
    ("scoped quotas are counted", "core/capacity_ledger.py", "    unscoped = [q for q in quotas if not q.scoped]",
     "    unscoped = list(quotas)"),
    ("a namespace commits its largest quota, not its smallest", "core/capacity_ledger.py",
     "out.append(min(bounds, key=lambda b: (b.hard,", "out.append(max(bounds, key=lambda b: (b.hard,"),
    ("a quota that leaves the cache keeps its share", "core/capacity_ledger.py", "            self._put(key, None)",
     "            pass"),
    ("a node with a NoSchedule taint counts", "core/clients/nodes.py",
     "                and all(t in self.count_taints for t in v.taints))", ")"),
]


def main(worktree: Path, logs: Path, suite: str) -> int:
    logs.mkdir(parents=True, exist_ok=True)
    stale = [what for what, file, old, _ in MUTANTS if (worktree / SRC / file).read_text().count(old) != 1]
    if stale:
        print(f"the text of these mutants is not in the source exactly one time: {stale}")
        return 2
    survived = 0
    for n, (what, file, old, new) in enumerate(MUTANTS, 1):
        path = worktree / SRC / file
        source = path.read_text()
        path.write_text(source.replace(old, new))
        try:
            log = logs / f"service-mutant-{n:02d}.log"
            run = subprocess.run([suite, str(worktree), str(log), *TESTS], capture_output=True, text=True)
            killed = run.returncode != 0
            summary = (run.stdout.strip().splitlines() or ["(no output)"])[-1]
        finally:
            path.write_text(source)
        survived += not killed
        print(f"{'ok  ' if killed else 'FAIL'} {n:02d} {what} - {'killed' if killed else 'SURVIVED'}: {summary}", flush=True)
    dirty = subprocess.run(["git", "-C", str(worktree), "diff", "--stat", "--", SRC], capture_output=True, text=True).stdout
    print(f"{len(MUTANTS)} mutants, {len(MUTANTS) - survived} killed, {survived} survived. "
          f"Source restored: {'yes' if all((worktree / SRC / f).read_text().count(o) == 1 for _, f, o, _ in MUTANTS) else 'NO'}")
    print(dirty.strip() or "(git diff of the source as before the run)")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]))
