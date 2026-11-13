# Research, issue #118

## H1: closing both races. The choice, and what was rejected

The two races need two different things, because H3 measured them as two causes.

**Race across cases: every process must be gone before the case's log is read.**

| Option | Result |
|---|---|
| **Chosen: an inherited pipe.** `pass_fds` gives the script a pipe's write end, every descendant inherits it, and the harness waits for end-of-file on the read end | No polling and no timing. Ends the moment the last process does |
| `wait` in the script | Rejected. MEASURED: `( /bin/sleep 0.5 & ); wait` returned after 0.021 s, against 0.526 s for `/bin/sleep 0.5 & wait`. A step's `nohup ... &` is a child of the step's subshell, and `wait` covers the shell's own children |
| One `$CALLS` per case | Rejected alone. MEASURED by the coordinator (issue table): 7 of 8 still fail at 0.02 s. It also leaves a process writing during `shutil.rmtree` (READ FROM CODE) |
| Polling a process group with `killpg(pgid, 0)` | Rejected. PROPOSAL NOT OPERATED. It is a poll loop, and it needs a new session for the script. The pipe gets the same answer from the kernel in one blocking call |
| A fixed sleep | Rejected by the brief, and it only moves the race |
| The `watch` stub writing to its own file | Rejected alone. It still needs the wait above, and it loses the record of the step after a stop beginning a watch unless that is attributed some other way |

**Race within a case: a call must be dated by who began it, not by when it logged.**

| Option | Result |
|---|---|
| **Chosen: `export CALLS="$CALLS.next"` where the `next` mark was.** A process keeps the environment it was forked with, so what the step began logs to the step's file however late, and only what the next step begins reaches the next file | No timing. READ FROM the Bash manual, below, and MEASURED by H1 and the variants |
| The `next` mark, read after everything has ended | Rejected. The pipe alone does not help: the line is still after the mark. MEASURED by variant `no-pipe`/`no-split` in `tests.md` |
| Filtering `crc-guard.py watch` out of `after` | Rejected by the brief: it would blind the test to a step after a stop beginning a watch |
| Marking the step's text with a line after each `&` | Rejected. PROPOSAL NOT OPERATED. It changes the block being tested, which the test exists to run as pasted, and needs a parser for what is a background command |
| A `DEBUG` trap logging each command before its fork | Rejected. PROPOSAL NOT OPERATED. It depends on where bash runs the trap, on both bash 3.2 and 5, for a harness that needs one fact |
| Ordering lines by process id | Rejected. PROPOSAL NOT OPERATED. Process ids wrap, and their order is no promise |

**The rule on the watch, since a failure's position in the log says nothing about it.** The old rule ignored a `watch` line wherever it fell, so a watch that began after a failed `snapshot`, or before it, was caught only when it happened to log after the mark. Now the log is complete by the time it is read, the test asks whether a watch began at all, and only `crc-guard.py watching` may fail with one begun.

| Option | Result |
|---|---|
| **Chosen: by name, only `watching` may fail with a watch begun** | Catches both a watch started past a remembered failure and a watch moved before the snapshot. If someone adds a command between the watch and `watching`, the test fails until this rule is changed. That is loud, and it is the safe direction |
| Allowed if the failed command comes after the watch in the step's text | Rejected. It passes the mutant that moves the watch before `snapshot`, which is one of the two cases it exists for (READ FROM CODE) |
| Allowed if the failed command's line follows the watch's line in the log | Rejected. That is the race again |

### Sources

| Source | Establishes | Status |
|---|---|---|
| POSIX `read()`, https://pubs.opengroup.org/onlinepubs/9799919799/functions/read.html | "If no process has the pipe open for writing, read() shall return 0 to indicate end-of-file." With writers and no `O_NONBLOCK`, the read blocks | WEB RESULT, and MEASURED by the variants |
| Python `subprocess`, https://docs.python.org/3/library/subprocess.html | "pass_fds is an optional sequence of file descriptors to keep open between the parent and child." It forces `close_fds` true, the default. On `run()` timeout "the child process will be killed", which is the direct child only, so the pipe wait needs its own limit | WEB RESULT, and MEASURED |
| Bash manual, Job Control Builtins, https://www.gnu.org/software/bash/manual/html_node/Job-Control-Builtins.html | `wait` waits for "the child process specified by each id" or, with none, "all running background jobs" | WEB RESULT, and MEASURED above |
| Bash manual, Environment, https://www.gnu.org/software/bash/manual/html_node/Environment.html | "Executed commands inherit the environment", to which `export` adds. So a command forked before the `export` cannot see it | WEB RESULT, and MEASURED |

**Not established by a source:** that `nohup` keeps the inherited descriptor open. MEASURED on macOS `/usr/bin/nohup` only: H1 and the variants pass and fail as they should. Not run on Linux, which CI uses. If a `nohup` closed it, the wait would be lost for that process and the false failures of race 1 would come back on that platform.
