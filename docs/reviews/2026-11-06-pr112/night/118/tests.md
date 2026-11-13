# Tests

## H3, on the baseline harness (commit 3f4b2e7)
Folder: `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/87a649b8-ffcb-4a8a-b61b-8ed3c119287a/scratchpad/agent-118`
Command: `KUBECONFIG=$PWD/empty-kubeconfig ../pr112/venv/bin/python scripts/h3.py tree`, Python 3.12.14, bash 5.3.20. `scripts/h3.py` patches the source in memory: the stub sleeps, then appends `$CASE` (inherited at fork) to `$CALLS.origin`, then logs. Exit 0. Full log: `logs/h3-baseline.log`.
MEASURED, 8 runs of step 12 at each delay:

| Delay | Failing case | Forked by | Runs |
|---|---|---|---|
| 0.02 s | `watching` failing | the same case | 8 of 8 |
| 0.1 s | `gate` failing | 1 case back (the nothing-failing run) | 8 of 8 |
| 0.3 s | `snapshot` failing (CI's message) | 2 cases back (the nothing-failing run) | 1 of 8 |

## H4, the CI log
Commands: `gh run view 42249576037 --repo ephico2real2/cmapi --json headSha,displayTitle,conclusion,jobs` and `--log-failed`. Exit 0.
READ FROM THE LOG: headSha `44083ffdbecad8d1724dbff23e0d6032cc399927`, conclusion failure. Jobs failed: `reference-code` (step Test: `tests/test_approvals.py::test_a_stored_requirement_keeps_its_group_path`, `ModuleNotFoundError: No module named 'sqlalchemy'`, `1 failed, 136 passed`) and `manifests` (step `docs/13's run`).
`manifests`, log line 1057: `FAIL crc-guard.py snapshot /tmp/doc13-run.g6pd3biu/deploy/rendere failing: the step after 12 ran crc-guard.py watch /tmp/doc13-run.g6pd3biu/deploy/rendered/wave1-run/watch.log /`, then `doc13 cases failed: 1, mutants survived: 0`.
Established: the doc13 step's only failure was that line, and the message is the same as the one reproduced at 0.3 s under H3, there from a process 2 cases back. Not established: which process wrote the line on CI. The log does not carry it and the job cannot be rerun from here.

## Verification environment, resumed work
All commands below use `/bin/bash` from the workspace root unless another folder is stated. `source scripts/test-env.sh` sets `PY` to the owner-specified Python and exports the absolute `KUBECONFIG`, `TMPDIR`, and `PYTHONDONTWRITEBYTECODE=1`. The script is saved alongside the test drivers. Long output goes to `report/logs/`. TokenSave status/context rejected this uninitialized `tree` project; read-only inspection used the requested git diff and this test file only. No index update was attempted.

## H8 — Linux runtime and POSIX contract
Folder: workspace root. Exact command: `source scripts/test-env.sh; "$PY" scripts/h8-runtime.py > report/logs/final-h8-runtime.log 2>&1`. Probe exit 0 (individual `docker info` exit 1; `podman info` exit 125; nerdctl absent). MEASURED: macOS 15.8.1, no answering container runtime. Docker socket access denied; Podman socket connection not permitted. No runtime was started, stopped or configured. Linux execution is NOT REACHED.

READ FROM CODE (API contract, not Linux execution): the pipe is never written to, so read readiness indicates EOF when its last writer closes. POSIX says an empty pipe blocks while a writer remains; zero writers yields EOF. `select` includes EOF in read readiness. `exec` preserves descriptors unless FD_CLOEXEC is set; Python `pass_fds` retains the write descriptor in the child. `nohup` specifies SIGHUP handling and standard-stream redirection; that specification alone is not an observed guarantee for this Ubuntu utility chain. Open Group pages returned HTTP 403; the POSIX text was read from its licensed reproduction:

- [POSIX read](https://man7.org/linux/man-pages/man3/read.3p.html), DESCRIPTION, empty pipes.
- [POSIX select/pselect](https://man7.org/linux/man-pages/man3/pselect.3p.html), DESCRIPTION, readiness and EOF.
- [POSIX exec](https://man7.org/linux/man-pages/man3/exec.3p.html), DESCRIPTION, open descriptors and FD_CLOEXEC.
- [POSIX nohup](https://man7.org/linux/man-pages/man1/nohup.1p.html), DESCRIPTION, signal and standard streams.
- [Python subprocess](https://docs.python.org/3/library/subprocess.html#subprocess.Popen), `pass_fds`.

PROPOSAL NOT OPERATED: repeat H1/H2 on ubuntu-24.04 when an authorized Linux runner is available.

## H7 — new regression on pre-fix logic, in a copy
Folder: workspace root. Exact command: `source scripts/test-env.sh; "$PY" scripts/h7-check.py > report/logs/final-h7-before.log 2>&1`. Exit 1, expected. Full output: `logs/final-h7-before.log`. Copy retained at `tmp/h7-before.py`.

READ FROM CODE: the driver restores the baseline's `subprocess.run`, single-file `next` marker attribution, and permissive watch rule in a copy of the final file. It retains only the new regression cases and delay/filter seams required to run them; it does not edit tree. This tests pre-fix logic, not an unmodified baseline executable (which has no delay API or new tests).

MEASURED: the actual new regression block reports `FAIL the watch logging 0.02 s late: ... watching ... failing: the step after 12 ran crc-guard.py watch ...`. The driver prints the explicit diagnosis `FAIL within-case late-logging race: step 12 background watch attributed to the next step`. One failed case and three surviving late mutants; no false failure at 0.1/0.3 s in this single pre-fix repetition. This one negative control establishes test sensitivity; it does not measure a failure rate.

## H1 — final code, step 12 only
Folder: workspace root. Exact command: `source scripts/test-env.sh; "$PY" scripts/final-sweep.py tree h1 0.02 0.05 0.1 0.25 0.3 0.6 1.0 > report/logs/final-h1.log 2>&1`. Exit 0. Full output: `logs/final-h1.log`.

READ FROM CODE: the saved driver loads definitions without executing the whole test, then calls `run_blocks(doc, steps_of(doc), [12], watch_delay=d)` eight times per delay. The default failure coverage remains enabled, including the existing dirty-checkout check. The driver asserts expectations through its exit status.

MEASURED: 0 of 8 false failures at each requested delay; all 56 step-12 runs pass. Final output: `Failed expectations: 0`.

## H2 — late mutants on final code
Folder: workspace root. Exact command: `source scripts/test-env.sh; "$PY" scripts/final-sweep.py tree h2 0.02 0.1 0.3 > report/logs/final-h2.log 2>&1`. Exit 0. Full output: `logs/final-h2.log`.

READ FROM CODE: the driver substitutes each of the three `LATE_MUTANTS`, calls step-12-only `run_blocks` eight times per delay with full default failure coverage, and requires the mutant's specific expected diagnostic. MEASURED: each mutant caught 8/8 at each delay, 72/72 total. Snapshot/watch ordering mutants report `step 12 began the watch all the same`; the next-step mutant reports `the step after 12 ran crc-guard.py watch`. Final output: `Failed expectations: 0`.

## Patch reproduction
Folder: workspace root. Exact commands: `git -C tree diff -- deploy/tests/doc13-test.py > report/patches/118.patch`; `git -C tree show HEAD:deploy/tests/doc13-test.py > tmp/final-patch-check/deploy/tests/doc13-test.py`; `( cd tmp/final-patch-check && patch -p1 --fuzz=0 --batch < ../../report/patches/118.patch )`; `cmp tmp/final-patch-check/deploy/tests/doc13-test.py tree/deploy/tests/doc13-test.py`; `git -C tree diff --check`. MEASURED: each exit 0; patch applies with zero fuzz, resulting file byte-identical. Log: `logs/final-patch-apply.log`.

H5 sample baseline 1, MEASURED. Folder: `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/87a649b8-ffcb-4a8a-b61b-8ed3c119287a/scratchpad/agent-118/tmp/final-baseline`. Exact child command: `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/87a649b8-ffcb-4a8a-b61b-8ed3c119287a/scratchpad/pr112/venv/bin/python deploy/tests/doc13-test.py docs/13-crc-deployment.md`, inherited `scripts/test-env.sh`. Output: `logs/final-h5-baseline-1.log`. Exit 1; elapsed 2.048 s. Last line: `doc13 cases failed: 3, mutants survived: 0`. Load/CPU samples: `logs/final-h5-times.jsonl`.

H5 baseline sample 1 is INVALID and excluded. MEASURED: it exited 1 after 2.048 s with missing `deploy/tests/crc-scripts-test.sh`, `ldap-identities-test.sh`, and `crc-backup-test.sh`; no full test ran. READ FROM CODE: baseline preparation omitted sibling test paths. Corrected the baseline copy by symlinking all sibling test paths, leaving `doc13-test.py` from git show HEAD. The fix run already in progress is valid. A replacement baseline sample 4 will run after the sequential driver finishes; valid comparisons use baseline 2,3,4 and fix 1,2,3. The invalid log/measurement is retained, clearly excluded.

H5 sample fix 1, MEASURED. Folder: `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/87a649b8-ffcb-4a8a-b61b-8ed3c119287a/scratchpad/agent-118/tree`. Exact child command: `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/87a649b8-ffcb-4a8a-b61b-8ed3c119287a/scratchpad/pr112/venv/bin/python deploy/tests/doc13-test.py docs/13-crc-deployment.md`, inherited `scripts/test-env.sh`. Output: `logs/final-h5-fix-1.log`. Exit 0; elapsed 168.113 s. Last line: `doc13 cases failed: 0, mutants survived: 0`. Load/CPU samples: `logs/final-h5-times.jsonl`.

## H6 — whole final test
MEASURED: reuses the first complete fix timing run above, same exact command and environment, exit 0, ending `doc13 cases failed: 0, mutants survived: 0`. Full output: `logs/final-h5-fix-1.log`.

H5 sample baseline 2, MEASURED. Folder: `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/87a649b8-ffcb-4a8a-b61b-8ed3c119287a/scratchpad/agent-118/tmp/final-baseline`. Exact child command: `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/87a649b8-ffcb-4a8a-b61b-8ed3c119287a/scratchpad/pr112/venv/bin/python deploy/tests/doc13-test.py docs/13-crc-deployment.md`, inherited `scripts/test-env.sh`. Output: `logs/final-h5-baseline-2.log`. Exit 0; elapsed 188.298 s. Last line: `doc13 cases failed: 0, mutants survived: 0`. Load/CPU samples: `logs/final-h5-times.jsonl`.
