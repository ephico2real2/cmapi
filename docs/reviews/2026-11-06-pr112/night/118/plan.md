# Plan, issue #118 (doc13-test.py false failures from a late `crc-guard.py watch` log)

Order of work:

| Order | ID | Claim (as in the brief; not assumed true) | How it is tested |
|---|---|---|---|
| 1 | H3 | The `watching`-failing false alarm at 0.02 s comes from an earlier case's process, not the same case | Baseline harness, each case tags its stub lines with a case number, read the tag of the offending line |
| 2 | H4 | CI at 44083ff failed for this reason and no other | `gh run view 42249576037`, read-only |
| 3 | H1 | With both races closed, no delay from 0.02 to 1.0 s produces a false failure in 8 runs each | Fixed harness, sweep at 13 delays |
| 4 | H2 | A mutant where a failed `snapshot` does not stop step 12 fails the test, also when `watch` logs late | New mutants, delayed and not, on baseline and on the fix |
| 5 | H5 | The fix adds less than 10 s to the runtime | Timed full runs, baseline and fix |
