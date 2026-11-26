# Reviewer 2 (Opus 5.5 high) · cmapi PR #709 (closes #708) · request changes, with the narrowed patch

Head `b8e7971`, base main `cab292f`, reviewer 1 Codex gpt-6.2-astra xhigh (`r1-report.md`, `r1-outputs/fix.diff`).
Every database case ran on **PostgreSQL 16 at `127.0.0.1:55432`** (`cmapi_r2_709`), in this export, with the brief's
Python 3.12.14 venv. Cluster: none (no kind, no CRC). The real CLIs ran in podman (`applehv` machine, amd64, cgroup v2) in the
image's base `ubi9/python-312-minimal@sha256:b99faaad…`, with the pinned kyverno v1.20.0 `linux_x86_64` (tarball SHA-256
`06b8f3ca…`, the Containerfile's) and kubeconform v0.6.7 from the implementer's `wt-708-outputs/measure/dl/`. Neither CLI is
installed on the Mac (`which kyverno kubeconform`: not found).

The final patch is [`r2-outputs/fix.diff`](r2-outputs/fix.diff) (432 lines, 13 files, SHA-256 `a5788905…af82`). It applied
to a fresh copy of `head/` with `patch -p1 -F0`, and the result was identical to `r2-final/` (`diff -r -x __pycache__`).

## Primary sources (read 2026-11-26)

- **Python 3.12 `subprocess.run`** (<https://docs.python.org/3.12/library/subprocess.html>): "If the timeout expires, the
  child process will be killed and waited for. The TimeoutExpired exception will be re-raised after the child process has
  terminated." `start_new_session`: "If start_new_session is true the setsid() system call will be made in the child process
  prior to the execution of the subprocess." `Popen.kill()`: "On POSIX OSs the function sends SIGKILL to the child." The
  installed 3.12.14 source of `run` (read with `inspect`): on POSIX, after `process.kill()`, it calls only `process.wait()`
  ("POSIX _communicate already populated the output so far"), so it never waits for a pipe held by a grandchild.
- **POSIX.1-2024, `kill()`** (<https://pubs.opengroup.org/onlinepubs/9799919799/functions/kill.html>): "If pid is negative,
  but not -1, sig shall be sent to all processes ... whose process group ID is equal to the absolute value of pid".
  **`setsid()`** (<https://pubs.opengroup.org/onlinepubs/9799919799/functions/setsid.html>): "The process group ID of the
  calling process shall be set equal to the process ID of the calling process." "The calling process shall be the only process
  in the new process group and the only process in the new session."
- **Linux `pid_namespaces(7)`** (<https://man7.org/linux/man-pages/man7/pid_namespaces.7.html>): init "becomes the parent of
  any child processes that are orphaned"; "Only signals for which the "init" process has established a signal handler can be
  sent to the "init" process".
- **RFC 9457** (<https://www.rfc-editor.org/rfc/rfc9457.html>), section 3.1.4: "The "detail" string, if present, ought to
  focus on helping the client correct the problem, rather than giving debugging information." Section 5: "when actually
  generating a problem ... the details given must also be scrutinized. Risks include leaking information that can be exploited
  to compromise the system".
- **AnyIO, "Working with threads"** (<https://anyio.readthedocs.io/en/stable/threads.html>): "The default AnyIO worker thread
  limiter has a value of 40"; on cancellation "the thread will still continue running – only its outcome will be ignored."
- **Python `threading.Semaphore.acquire`**, installed 3.12.14 source: `while self._value == 0:` is the only stop. So a
  fractional value never reaches exactly 0 and never stops a holder.
- `head/cmapi/Containerfile:140`: `ENTRYPOINT ["cmapi-api"]` (PID 1 is the Python app; no tini). `head/cmapi/src/cmapi/main.py:625`:
  `uvicorn.run(... factory=True ...)` with no `workers`, so one server process per API container.

## Verdicts on reviewer 1's findings

| # | R1 | My severity | Verdict | In the final patch |
|---|---|---|---|---|
| M1 | Medium: timeout kills only the direct CLI | **Low, Backlog** | Premise refuted by measurement for the pinned CLIs | Cut |
| M2 | Medium: Helm schema omits `api.validator` | Low (inside changed lines) | Confirmed | Kept, narrowed |
| L1 | Constructor accepts fractional permits | Low (inside) | Confirmed: unbounded | Kept, narrowed |
| L2 | 503 detail discloses slots and wait | Low (inside) | Confirmed | Kept; problem-doc change reverted |
| L3 | Busy counter counted on a metadata 422 | Low (inside) | Confirmed | Kept; test rewritten |
| L4 | `kyverno version` probe outside the slots | not a defect | Refuted: runs once, before serving | Cut |
| L5 | Metric-scan test breaks | **Medium** (CI red) | Confirmed | Kept, simplified |

### M1: process-group kill on a CLI timeout. Refuted as Medium; Low, Backlog

**Measured, real binaries, in the image's base, `--cpus=1 --memory=512m`** (`r2-outputs/helpers/`):

- `strace -f -e trace=execve,fork,vfork,clone,clone3` (strace 6.12, `strace-results.txt`):

  | Command | execve | clone with CLONE_THREAD | clone without | fork/vfork |
  |---|---|---|---|---|
  | `kyverno apply` on the CRC bundle and `cmap-z39-dev` | 1 (itself) | 6 | **0** | **0** |
  | `kyverno version` | 1 | 5 | **0** | **0** |
  | `kubeconform -strict -summary -output json` | 1 | 5 | **0** | **0** |

- A `/proc` scan every 5 ms of every process whose parent chain, process group or session reaches the CLI (`proctree.py`,
  `proctree-results.jsonl`): `descendants: {}` in 3 `kyverno apply`, 2 `kyverno version` and 2 kubeconform runs (2310, 462,
  425, ... polls). Each CLI is one Go process with 5 or 6 threads.

So neither pinned CLI starts a helper: killing the direct child kills everything the plan started. On head, a hung
single-process CLI is killed and its slot comes back (measured: a stub that sleeps 30 s with `timeout=2.0` raised
`TimeoutExpired after 2.90 s`, `os.kill(pid, 0)` gave `ProcessLookupError`, and `slots.hold()` succeeded at once). This
matches the Python source quoted above. Codex's head reproduction used a Python stub that calls `os.fork()` on purpose; it
proves the mechanism, not that it occurs. `_run` is also **not changed by this PR**: `sed -n '/def _run/,/def validate/p'` of
base and head is identical.

**Is `start_new_session` plus `killpg` safe in the container?** Mostly yes, but it buys nothing here:
- *Signals and PID 1.* `setsid()` makes the CLI's process group ID equal to its PID and holds only it (POSIX quote above).
  So `killpg(proc.pid, SIGKILL)` reaches that group only. It never reaches `cmapi-api` (PID 1), which keeps its own group.
- *Zombies.* PID 1 is the Python app (Containerfile:140, no tini). A killed helper's parent is gone, so the helper is reparented
  to PID 1 (`pid_namespaces(7)`), and Python does not wait for children it did not start. It stays a zombie, with or without
  `killpg`. The patch does not change this; with the measured CLIs there is no helper to leave behind.
- *Behaviour beyond its purpose.* The CLI leaves the terminal's session, so a Ctrl-C of a local `cmapi-api` no longer
  reaches a running kyverno, and `_run` is replaced by about 15 lines of `Popen` handling on every call.

The owner's rule is to build the complex version only when nothing simpler holds. The measurement shows the simpler version
holds, so the change is cut. **Backlog (Low, no fix):** if a later pinned CLI starts helpers, which the image's pin check
(#395) would show at its upgrade, run a CLI in its own session and kill its group on a timeout. A container init that reaps
(`tini`) belongs to the same change.

### M2: the chart's schema has no `api.validator`. Confirmed; Low, inside the changed lines

Measured, Helm v4.3.1, `helm template` with `deploy/environments/crc.yaml`:

| Values | head | final |
|---|---|---|
| `queue: 41` | rc 0, renders `CMAPI_VALIDATOR_QUEUE "41"` (the API then stops at its start: Settings `le=40`) | rc 1, schema error |
| `waitSecond: 3` (typo) | rc 0, the default `"15"` silently | rc 1 |
| `concurrency: 1.5` | rc 0, renders `"1.5"` | rc 1 |
| `concurrency 2, queue 6, waitSeconds 7.5` | rc 0 | rc 0, same env |

The Python check still stops a bad value at the start, so the harm is a rollout that fails rather than an outage. That makes it
Low, not Medium. It is inside the changed lines, and #683/#689 set the precedent of describing new values in
`values.schema.json` (`instance.http`), so the fix is kept. **Code** (`deploy/helm/cmapi/values.schema.json`):

```json
    "api": {
      "type": "object",
      "required": ["validator"],
      "properties": {
        "validator": {
          "description": "The policy check's slots in each API pod (#708): CMAPI_VALIDATOR_CONCURRENCY, _QUEUE and _WAIT_SECONDS, with the bounds of Settings in cmapi/src/cmapi/settings.py (docs/18, \"The validator's slots\")",
          "type": "object",
          "additionalProperties": false,
          "required": ["concurrency", "queue", "waitSeconds"],
          "properties": {
            "concurrency": {"type": "integer", "minimum": 1, "maximum": 40},
            "queue": {"type": "integer", "minimum": 0, "maximum": 40},
            "waitSeconds": {"type": "number", "minimum": 0, "maximum": 60}
          }
        }
      }
    },
```

**Narrowed:**
- I added the `description`.
- I updated the `$comment` list (Codex's).
- `docs/18`, "The chart", now says Helm refuses an out-of-range value.

**Tests** (`tests/service/test_helm_metadata_values.py`):
- `test_validator_values_out_of_settings_range_stop_the_render[10 cases]` fails on head in all 10 cases and passes on final.
- `test_validator_values_in_range_reach_the_api_settings[3]` passes on both: it is the guard that the schema refuses nothing
  that Settings accepts.
- I removed Codex's unrelated assertion on the two containers' `command`.

### L1: fractional or boolean permits. Confirmed (unbounded); Low, inside

Measured on head: `ValidatorSlots(1.5, 0, 0)` admitted **5 of 5** nested holders, so it is unbounded. `ValidatorSlots(True, 0, 0)`
was accepted. The production path is safe, because `Settings.validator_concurrency: int` refuses `"1.5"`, but the class is the
bound. **Code** (`core/validate/__init__.py`):

```python
        # Whole numbers only: threading.Semaphore stops a holder only at a value of exactly 0, so a concurrency of 1.5 never
        # stops one. type() is not isinstance(), so a bool is refused too.
        if (type(concurrency) is not int or concurrency < 1 or type(queue) is not int or queue < 0
                or not math.isfinite(wait_seconds) or wait_seconds < 0):
            raise ValueError("validator slots need a whole concurrency of at least 1, a whole queue of at least 0 and a "
                             f"finite wait of at least 0 seconds, not {concurrency!r}, {queue!r} and {wait_seconds!r}")
```

**Narrowed from Codex's version:**
- I dropped the copied 40 and 60 upper bounds. They are deployment facts (AnyIO's pool, nginx's timeout), held by Settings and
  now by the schema, and a third copy would drift.
- I restored the values in the message, which makes the error easy to debug.

**Test:** `test_slots_refuse_a_bound_that_is_not_one[1.5-0-0, 1-0.5-0, True-0-0]` fails on head (3 failures,
`mix-core.log`) and passes on final.

### L2: the 503 detail discloses the pod's slots and wait. Confirmed; Low, inside

Head answers `"The policy check is busy: 1 running and 4 waiting in this pod; try again in 15 s"` and `"No policy check slot of
this pod came free in 0.3 s; ..."`. RFC 9457 §3.1.4 and §5 (quoted above) and the coordinator's brief ("must not leak
internals") apply. **Code:** `ValidatorBusy.public_detail` (above) is the detail, and `pipeline.py` sends it:

```python
                raise Problem(503, "validator-busy", ValidatorBusy.public_detail,
                              extra={"retryAfter": exc.retry_after}) from exc
```

The exception's own message keeps the counts for the worker's job error. `docs.py` `PROBLEMS` and the five OpenAPI examples in
`contract/openapi.json` change to match, and `test_api_contract` passes.

**Cut:**
- Codex's rewrite of `problem_docs.ACTIONS["validator-busy"]`. That page is static documentation with no instance's numbers,
  and the rewrite deleted "Nothing was done", which tells a client that a retry is safe.

**Tests** (service, PostgreSQL):
- `test_a_busy_answer_names_no_slot_count_or_wait[queue-full, wait-timeout]` runs on the `world` fixture, so it has a
  migrated database. Codex's version ran without `fresh_db`.
- The detail assertions of the burst and wait tests.
- All four fail on head (`mix-service.log`: the head detail strings) and pass on final.

### L3: `cmapi_validator_busy_total` counts a 503 that was a 422. Confirmed; Low, inside

Measured on head: `busy_count('queue-full')` went from 8 to **9** for an answer that was 422 `policy-violation`. **Code** (`pipeline.py`):

```python
            except ValidatorBusy as exc:
                if refusal is not None:
                    raise  # the metadata 422 found above is the answer (the handler below), so no 503 is counted
                # Every slot of this pod is taken (#708): the plan is not refused, it is to be sent again.
```

**Test:** `test_a_metadata_refusal_with_no_free_slot_is_its_422_and_counts_no_503` (on `world`) fails on head with
`assert 9.0 == 8.0` and passes on final. The 422 and its body are unchanged: on head too, the outer handler turned the 503 into
the refusal.

### L4: `kyverno version` probe outside the slots. Refuted as a defect

The probe runs once, in `CliValidator.__init__` from `build_context`. In the API that is uvicorn's app factory, called before
the server serves. In the worker, it runs before its loop. So it never overlaps a plan in its process. Measured: **72.0, 71.6
and 71.4 MiB** peak RSS and 0.7 to 0.8 s (`kyverno-version-rss.txt`); next to the app's 134 MiB that is far under 512 MiB.

Codex's fix added a `hold(observe_wait=...)` parameter and a startup failure mode (`ValidatorBusy` while building the context),
for no measured gain. I cut it, and with it Codex's rewrite of `test_the_settings_size_the_slots_of_the_process`, which existed
only to cover that change. Head's version of the test stays. It already fails if the observer wiring is removed: `on_wait=None`
gives no observation.

### L5: the metric-scan test fails on head. Confirmed; Medium (it turns CI red)

Measured on head, PostgreSQL: `FAILED test_policy_reports_unit_302.py::test_every_metric_that_observability_declares_is_recorded_somewhere`
(`head-related.log`). The scan wants `NAME.observe(`, and context.py passes `VALIDATOR_WAIT.observe` as a callback. A red test
blocks the merge gate, so I raise it to Medium. **Code:** one general pattern instead of Codex's `on_wait=`-specific second regex:

```python
    # Called, or passed as a callback: core/context.py gives VALIDATOR_WAIT.observe to the validator's slots (#708).
    assert len(names) > 20 and [n for n in names if not re.search(rf"\b{n}\.(labels|inc|set|observe)\b", code)] == []
```

**Tests:** it fails on head and passes on final. Mutant `r2-mut3` (final with `on_wait=VALIDATOR_WAIT.observe` removed) fails
it with `['VALIDATOR_WAIT'] == []`, so the scan still catches a metric that is never recorded.

## What Codex missed

1. **Its patch turns `test_doc_citations` red (Medium).** The changes to `pipeline.py` move two lines that `docs/14-authorization.md`
   cites (`pipeline.py:523` and `:607`). Measured on a git-initialised copy of Codex's tree: `doc-citations: 2 problems` ("moved
   to line 524 / 608"). Head has 0 problems. The final patch carries the output of `scripts/doc-citations.py --relocate`
   (`docs/14-authorization.md` and `docs/citations.lock.json`, 2 lines each): **0 problems**, and `test_doc_citations.py`
   passes on the patched copy. (In this export the test fails on any tree, because `git ls-files` needs a repository. That
   is not a defect of the code.)
2. **M1's premise was never measured.** The finding rested on a stub that forks. The pinned CLIs start no process (strace
   above).
3. **Behaviour beyond the purpose in R1's patch:**
   - `problem_docs` lost the retry-safety guidance.
   - The constructor lost its diagnostic values and copied the deployment bounds.
   - `_run` changed how signals reach the CLI.
   - `hold()` grew a parameter.

   All are cut.
4. **The `/readyz` proof under the burst** was not tested by anyone. I added
   `test_readyz_answers_while_twelve_dry_runs_hold_the_validator` (below).
5. **Cut tests:**
   - Codex's client-disconnect test (raw ASGI, asyncio and limiter tokens). It proves what AnyIO already guarantees: the
     sync thread "will still continue running", and `with self.slots.hold()` releases when `validate` returns.
   - Codex's process-group test (M1, cut).
   - Codex's version-probe test (L4, cut).
6. **Kept tests that pass on head** (regression guards for the brief's claims 1 and 2, not findings):
   - `test_one_admission_covers_both_commands`: kubeconform inside the slot, with one wait.
   - `test_timeout_restores_the_entire_queue`: no admission leaks on the wait-timeout path. No head test catches that, because
     head's retry comes after the outer hold is released.
   - `test_failed_observer_restores_both_permits`.
   - `test_pr_checks_uses_the_worker_contexts_validator_slots`, to which I added a docstring.
7. **A trap in the export:** `examples/src/cmapi -> ../../cmapi/src/cmapi` and `examples/tests -> ../cmapi/tests/core` are
   symlinks. A recursive `diff` of two trees doubles each changed file. `patch` then meets the second copy, reports "Reversed
   (or previously applied) patch detected! Assume -R? [y]", and **reverses** the change. My first draft of the diff did exactly
   that; the final diff excludes `examples/`. Anyone who builds or applies a diff of this export should exclude it.

## The brief's checks

**Twelve-request burst over HTTP on PostgreSQL.** On head, `test_validator_busy_708.py` gave 11 passed, including the burst and
the 202 create (`head-busy.log`). On final, 3 runs of the burst, the `/readyz` test and the 202 create
(`burst-readyz-3runs.log`, load 11 to 21) each gave:

| Run | Answers | Kyverno peak | `/readyz` probes | codes | median | max |
|---|---|---|---|---|---|---|
| 1 | 5 × 200, 7 × 503 | 1 | 75 | {200} | 0.035 s | 0.580 s |
| 2 | 5 × 200, 7 × 503 | 1 | 72 | {200} | 0.034 s | 0.450 s |
| 3 | 5 × 200, 7 × 503 | 1 | 75 | {200} | 0.035 s | 0.645 s |

Every 503 is `validator-busy`, `application/problem+json`, with `Retry-After: 15`. The test asserts `/readyz` under the probe's
`timeoutSeconds: 3` (`templates/api.yaml:73`).

The stub kyverno is a Python script (as in the PR's tests). The memory of the real CLI under the slots on CRC is not measured
here; that is the coordinator's deployed run.

**Every path running the CLIs goes through the slots.** I listed with `grep` every `subprocess.`, `._run(`, `_kubeconform(`,
`_kyverno(`, `.validate(` and `CliValidator(` in `head/cmapi/src`:
- The CLIs run only in `CliValidator._run`.
- `_run` is called by `_kubeconform` and `_kyverno` (only from `validate`, inside `with self.slots.hold()`) and by the startup
  version probe (L4).
- `validate` is called by `Pipeline._plan_namespace` (create, change and three expiry routes, and their dry runs; five
  operations list `validator-busy` in `openapi.json`) and by `jobs/pr_checks.py:102` (the worker's own context).
- `build_context` is called once per process (`main.py:235` and `worker.py:212`), so there is one `ValidatorSlots` per process.
- The other subprocesses are `git` and `ssh-keygen` (core/git), outside #708.

## Verification record

| Tree | Command | Result |
|---|---|---|
| head | core: slots, import, kyverno pin | 35 passed |
| head | service `test_validator_busy_708.py` (PG) | 11 passed |
| head | service, 13 related files (PG) | 393 passed, **2 failed**: metric scan (L5), citations (needs a git repository: 0 problems on a git copy of head) |
| head source + final tests (`r2-mix`) | core | 20 passed, **3 failed** (L1) |
| `r2-mix` | service: busy, helm, metric, delivery (PG) | 100 passed, **15 failed**: 4 detail (L2), 1 counter (L3), 10 helm (M2) |
| final | core: same 3 files | **41 passed** |
| final | service: busy and 12 related files (PG) | **412 passed** |
| final, patched fresh copy, git-initialised | `doc-citations.py --check`; `test_doc_citations.py` and `test_delivery_states_review.py` | 0 problems; 21 passed |
| final minus observer wiring (`r2-mut3`) | metric scan | fails, as it must |
| Codex's tree, git-initialised | `doc-citations.py --check` | 2 problems (missed item 1) |

The logs are in `r2-outputs/logs/`, and the CLI measurements in `r2-outputs/helpers/`. Database `cmapi_r2_709` was used; the
extra `cmapi_r2_709_mix` I created was dropped.

## Backlog (Low, no fix)

- **B1.** A process-group kill on a CLI timeout, with a reaping init, if a pinned CLI ever starts helpers (M1 above).
- **B2.** Two CLIs in a row with a 60 s timeout each, plus a 15 s wait, can pass nginx's 60 s `proxy_read_timeout`. This
  predates the PR (Codex's claim 4).
- **B3.** `core/docs.py`'s shared 503 description says "unresponsive dependency", which does not fit a local overload (Codex's
  backlog item).
- **B4.** The portal shows a 503 `validator-busy` like any problem and does not wait for `Retry-After` itself (the PR's
  README, "Not tested").

## Who wrote what

Reviewer 2, Opus 5.5 at `high`, wrote this report and `r2-outputs/`. The final patch is Codex's fix.diff, narrowed:
- **Kept from Codex:** the schema, `public_detail`, the 422 guard, the OpenAPI and `docs.py` examples, the constructor type
  check, three core tests, the worker test, two Helm tests, and the docs/18 intent.
- **Mine:** the narrowing, the metric-scan pattern, the two service tests rewritten on `world`, the `/readyz` burst test, the
  citation relocation, and the docs/18 wording.

No repository, GitHub or cluster changes.

## Five-line summary

1. Reviewer 1's Medium 1 is refuted by measurement: strace of the pinned kyverno 1.20.0 and kubeconform 0.6.7 shows 0 helper
   processes, and head already kills and reaps a hung CLI and frees its slot. Moved to Backlog, fix cut.
2. Confirmed and kept, narrowed: the Helm schema (Low), integer-only permits (Low; 1.5 was unbounded), a fixed public 503
   detail (Low), no busy count on a 422 (Low), and the metric-scan repair (Medium: head's CI is red).
3. Codex missed that its patch breaks `test_doc_citations` (docs/14 cites moved pipeline lines). The final patch carries the
   `--relocate` output: 0 problems.
4. On PostgreSQL, the 12-request burst gave 5 × 200 and 7 × 503 with `Retry-After: 15` and a kyverno peak of 1, three times;
   `/readyz` stayed 200, max 0.645 s. Final: 41 core and 412 service passed. 18 new assertions fail on head.
5. `r2-outputs/fix.diff` (13 files) applies with `patch -p1 -F0` and is identical to `r2-final/`. Exclude the `examples/`
   symlinks from any recursive diff of the export.
