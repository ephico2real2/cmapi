# #708: concurrent plans run at most the validator's slots of Kyverno at once; the others answer 503 `validator-busy`

The implementer's record: Opus 5.5 at `high`, 2026-11-26, on `fix/708-kyverno-concurrency` from main `cab292f`. The defect is
High and touches availability and security (OWASP API4), so the change gets two reviewers; their records go beside this one.

## What was wrong

OB1 run 43 on CRC (2026-11-26, main `cab292f373`; `ob1-run43/logs/c43-pool696/`): twelve `POST
/api/v1/clusters/CRC/namespaces?dryRun=true` at once, as `cmapi.requester`, all answered 502 from the front door after 9.8 s.
The node journal: "kyverno invoked oom-killer", "memory: usage 524288kB, limit 524288kB", "Killed process 864824 (cmapi-api)",
"going to be killed due to memory.oom.group set". The OOM task table of the API container's cgroup held one `cmapi-api` (134
MiB RSS) and **twelve `kyverno` processes** (34 to 87 MiB each, still growing). Container status: exit 137, restartCount 0 to 1.

Each plan runs kubeconform and `kyverno apply` with `subprocess.run` (`core/validate/__init__.py`, `CliValidator._run`), from
`Pipeline._plan_namespace`. The create route is a sync `def`, so it runs in AnyIO's worker threads, 40 by default, and nothing
bounded how many plans ran the CLI at once. One caller's `write` bucket allows a burst of 30 (#689), so the rate limits do not
prevent it.

## Sources

Each fetched 2026-11-26.

- **Kubernetes, `KubeletConfiguration.singleProcessOOMKill`**
  (<https://raw.githubusercontent.com/kubernetes/kubernetes/master/staging/src/k8s.io/kubelet/config/v1beta1/types.go>):
  "singleProcessOOMKill, if true, will prevent the `memory.oom.group` flag from being set for container cgroups in cgroups v2.
  This causes processes in the container to be OOM killed individually instead of as a group." "On cgroup v2 linux, null /
  absent, true and false are allowed. The default value is false." So any child that passes the limit takes the API with it.
- **OWASP API Security Top 10 2023, API4**
  (<https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption>): "An API is vulnerable if at
  least one of the following limits is missing or set inappropriately (e.g. too low/high):" among them "Execution timeouts",
  "Maximum allocable memory", "Maximum number of processes". How To Prevent: "Use a solution that makes it easy to limit memory,
  CPU, number of restarts, file descriptors, and processes".
- **Python, `threading`** (<https://docs.python.org/3/library/threading.html>): `Semaphore.acquire`: "When invoked with a
  *timeout* other than `None`, it will block for at most *timeout* seconds. If acquire does not complete successfully in that
  interval, return `False`." "When invoked with *blocking* set to `False`, do not block." Semaphore example: "Semaphores are
  often used to guard resources with limited capacity, for example, a database server. In any situation where the size of the
  resource is fixed, you should use a bounded semaphore." "The use of a bounded semaphore reduces the chance that a programming
  error which causes the semaphore to be released more than it's acquired will go undetected."
- **Python, `subprocess.run`** (<https://docs.python.org/3/library/subprocess.html>): "If the timeout expires, the child
  process will be killed and waited for." The existing 60 s timeout bounds one run, not how many run.
- **AnyIO, "Working with threads"** (<https://anyio.readthedocs.io/en/stable/threads.html>): "The default AnyIO worker thread
  limiter has a value of 40, meaning that any calls to `to_thread.run_sync()` without an explicit limiter argument will cause
  a maximum of 40 threads to be spawned." (anyio 4.16.0 in the pod, run 43's `crash/anyio-limiter.txt`.)
- **FastAPI, "Concurrency and async / await"** (<https://fastapi.tiangolo.com/async/>): "When you declare a *path operation
  function* with normal `def` instead of `async def`, it is run in an external threadpool that is then awaited". `/readyz` is
  such a function (`routers/health.py`), so it shares those 40 threads with the plans.
- **Google SRE book, "Addressing Cascading Failures"** (<https://sre.google/sre-book/addressing-cascading-failures/>),
  "Queue management": "it is usually better to have small queue lengths relative to the thread pool size (e.g., 50% or less)",
  "Usually, if the queue is full, the server will reject new requests"; "Load shedding": "For example, one effective approach is to
  return an HTTP 503 (service unavailable) to any incoming request when there are more than a given number of client requests
  in flight"; "It's usually wise to set a deadline."
- **RFC 9110, section 15.6.4** (<https://www.rfc-editor.org/rfc/rfc9110.txt>): "The 503 (Service Unavailable) status code
  indicates that the server is currently unable to handle the request due to a temporary overload or scheduled maintenance,
  which will likely be alleviated after some delay. The server MAY send a Retry-After header field (Section 10.2.3) to suggest
  an appropriate amount of time for the client to wait before retrying the request."
- **nginx, `ngx_http_proxy_module`** (<https://nginx.org/en/docs/http/ngx_http_proxy_module.html>): "Default:
  proxy_read_timeout 60s"; "If the proxied server does not transmit anything within this time, the connection is closed." The
  front door (`cmapi-portal-ui/nginx/templates/cmapi.conf.template`) sets none, so a plan must answer within 60 s.
- **Kyverno CLI, `kyverno apply`** (<https://kyverno.io/docs/kyverno-cli/reference/kyverno_apply/>): no option for memory,
  caching or a server mode. `--concurrent` is "Number of concurrent workers for resource loading (default 1)".
- **Kyverno, ValidatingPolicy** (<https://kyverno.io/docs/policy-types/validating-policy>): "A Kyverno Engine SDK is planned
  for a subsequent release." "To evaluate JSON policies, use the Kyverno CLI."
- **Go, "A Guide to the Go Garbage Collector"** (<https://tip.golang.org/doc/gc-guide>): the memory limit "sets a maximum on the
  total amount of memory that the Go runtime can use"; "The Go runtime makes no guarantees that it will maintain this memory
  limit under all circumstances"; near it the GC thrashes, which "effectively stalls the program".

## The measurement

`measure/run.sh` and `measure/measure.py`, 2026-11-26, in the image's base (UBI 9 python-312-minimal, by digest) on a 4-CPU
x86_64 podman machine, with the pinned CLI v1.20.0 `linux_x86_64` (SHA-256 `06b8f3ca...`, the Containerfile's) and kubeconform
v0.6.7. The policies are `cmapi-tools policies render` of the CRC ConfigMap (`deploy/manifests/environments/crc/20-config.yaml`)
for `dev`; the resources are the rendered folder of `cmap-z39-dev`, run 43's name: the Namespace, the ResourceQuota and the two
LimitRanges, as `CliValidator._kyverno` passes them. Each run reported 50 results (45 pass, 5 fail: the hand-made spec lacks
some required keys) and exited 1, as a run with a failure does. Each child's peak RSS is `wait4`'s `ru_maxrss`; the cgroup's
peak is `/sys/fs/cgroup/memory.peak` of the container, which also holds the measuring Python.

| Run | Peak RSS of each `kyverno` | cgroup peak | Wall | CPU of each |
|---|---|---|---|---|
| 1 at a time, no limits (5 runs) | 151.0, 152.6, 152.9, 153.2, 157.7 MiB | 172.2 to 178.0 MiB | 3.0 to 5.5 s | not recorded |
| 1, `--cpus=1 --memory=512m` (3 runs) | 156.0, 157.9, 158.2 MiB | 176.1 to 179.9 MiB | 2.8 to 6.0 s | 2.59 to 5.39 s |
| 1, cpu 1, `GOGC=50` | 145.7 MiB | 166.7 MiB | 4.5 s | 4.27 s |
| 1, cpu 1, `GOMEMLIMIT=96MiB` | 154.2 MiB | 174.5 MiB | 3.8 s | 3.56 s |
| 2 at once, no limits | 147.5, 147.0 MiB | 247.6 MiB | 4.9 s | |
| 2 at once, cpu 1 | 153.9, 153.5 MiB | 260.3 MiB | 6.7 s | 3.30, 3.35 s |
| 4 at once, no limits | 150.5 to 153.7 MiB | 412.7 MiB | 17.6 s | |
| 12 at once, no limits | 128.7 to 156.3 MiB (sum 1666.2) | 914.4 MiB | 121.0 s | |
| kubeconform, 1 (2 runs) | 15.6, 16.1 MiB | 22.9, 23.1 MiB | 0.3, 0.4 s | |

The Mac's load was 12 to 18 while these ran, so the times vary; the memory does not. Runs at once share the binary's pages,
so each run past the first adds about 70 to 80 MiB to the cgroup. With CRC's 134 MiB for the API's own process:

- one slot: about 134 + 180 = **310 MiB** of the 512 MiB limit;
- two: about 134 + 260 = 395 MiB, with CPU limit 1 and no gain in throughput (two runs: 6.7 s wall for 6.65 s of CPU);
- four: about 134 + 413 = 547 MiB, over the limit, as the twelve on CRC were.

## The decision

**A bound on concurrent runs in each process, with a short queue and a bounded wait; 503 `validator-busy` with `Retry-After`
beyond it.** `ValidatorSlots` (`core/validate/__init__.py`) holds two `threading.BoundedSemaphore`s: `_running`, the slots
(`CMAPI_VALIDATOR_CONCURRENCY`, default 1), taken with a timeout (`CMAPI_VALIDATOR_WAIT_SECONDS`, default 15); and `_admitted`,
the slots plus the queue (`CMAPI_VALIDATOR_QUEUE`, default 4), taken without blocking. `CliValidator.validate` holds one slot
around both CLIs of a plan, so a plan waits once. `Pipeline` turns `ValidatorBusy` into 503 `validator-busy` with `retryAfter`;
`main.py`'s `problem_response` already sends it as `Retry-After` (#694).

- **Why a semaphore.** It holds at any scale: each pod runs at most its slots, whatever the callers, the replicas or the rate
  limits do. The memory of a pod is then the app plus the slots, which an operator sizes with `limits.memory`.
- **Why a queue as well as a wait.** A waiting plan holds one of the 40 threads that `/readyz` and every sync route share. Twelve
  or thirty plans waiting 15 s would hold most of them, and a failing readiness probe takes the pod out of the Service. The
  queue keeps at most 1 + 4 of 40 threads in the validator (the SRE book's "50% or less" with room to spare); a plan beyond it
  is refused at once and holds none.
- **Why one slot.** The measurement above: one slot leaves about 200 MiB of the 512 MiB limit; a second leaves about 115 MiB
  and gains nothing at CPU limit 1.
- **Why 15 s and 4.** A run takes 2.6 to 5.4 s of the one CPU, so four queued plans finish in about 10 to 22 s; 15 s serves
  most of them, under the front door's 60 s `proxy_read_timeout` (nginx's default; `cmapi.conf.template` sets none).
  `Retry-After` is the wait, rounded up: about the time the queue that refused the plan takes to drain.
- **The worker** runs one job at a time (`Worker.run`, one `run_one` per turn of its loop), so its PR checks use one slot
  whatever the setting. A `ValidatorBusy` there is an exception like `ValidatorUnavailable`, and a job that raises "is retried
  with backoff (5, 15, 45, 135, 405 s)" (`worker.py`).
- **Memory is not raised.** The owner allowed it "if needed" (2026-11-26); one slot plus the app fits, so it is not.

### The options not taken

- **In-process evaluation.** Kyverno has no library: "A Kyverno Engine SDK is planned for a subsequent release" and "To evaluate
  JSON policies, use the Kyverno CLI". A Python CEL evaluator would check other semantics than the clusters run, which the
  pinned CLI exists to avoid (#212, #395).
- **A persistent validator process.** `kyverno apply` has no server or daemon mode (its option list). A Kyverno admission
  server would be a second deployment to run and secure for each instance, and would still need a bound on concurrent work.
- **Caching results.** It helps only identical inputs. Twelve different names, or a person typing into the form, still start
  one run each; it is not a bound, and a cache keyed on the files and the bundle adds its own invalidation.
- **A smaller CLI.** `GOGC=50` and `GOMEMLIMIT=96MiB` changed the peak by 8 % at most (145.7 and 154.2 MiB against 156 to 158),
  since most of it is the CLI's start; a memory limit below the live heap thrashes, by Go's own guide.
- **Raising the memory alone.** It moves the number of plans that kill the pod, from 4 to 6 or 10, and the rate limits allow 30.

## The tests

Each stub `kyverno` is a Python script that counts the copies of itself running, under an exclusive `fcntl.flock`, keeps the
highest count, and sleeps while it counts itself: the tests read the peak of real child processes.

| Test | Before the fix (main `cab292f`'s `cmapi/src`, stashed) | After |
|---|---|---|
| `tests/core/test_validator_slots_708.py`: twelve plans at once with the defaults | **fails: "12 kyverno processes ran at once"** | passes: peak 1, at least five plans pass, the others `ValidatorBusy` `queue-full`, retry 15 |
| the same file: a configured concurrency of 2 and 3 is the peak; a wait past the wait; a full queue; a failing check gives its slot back; no files take no slot; the wait is reported; bad bounds; Retry-After | fail (`ValidatorSlots` does not exist) | pass (17 in all) |
| `tests/service/test_validator_busy_708.py`: twelve dry runs at once through the API | **fails: "12 kyverno processes ran at once"** | passes: peak 1; each answer 200 with the plan, or 503 `validator-busy`, `application/problem+json`, `Retry-After: 15` |
| the same file: a dry run that waits past the wait | fails | passes: 503, `Retry-After: 1`, `cmapi_validator_busy_total{reason="wait-timeout"}` +1, then the same dry run 200 |
| the same file: the settings reach the one validator, and its wait is observed; out-of-range settings stop the start; the defaults | fail | pass |
| the same file: a create with a free slot is unchanged (202, one run) | passes | passes: the normal path, unchanged |
| `tests/core/test_config_import_693.py`: `cmapi.core.validate` imports with no structlog and no prometheus_client | (new case) | passes |

The outputs are in the implementer's `wt-708-outputs/` (`before-core.txt`, `before-service.txt`, `after-*.txt`).

## Not tested

- **CRC.** The proof the issue names (twelve dry runs at once; restartCount unchanged; each answer 200 or 503 with
  `Retry-After`; `memory.peak`) needs this change deployed, which is the coordinator's run.
- **kind.** Not run; the change has no manifest other than the chart's three variables.
- The portal shows a 503 as it shows any problem; it does not wait for `Retry-After` by itself.

## Who wrote what

Opus 5.5 at `high` (the implementer) wrote the code, the tests, docs/18's section, the chart values and this record. The
reviewers' records go beside it.

## Review and the coordinator's rulings (2026-11-26)

**Reviewers.**
- **Reviewer 1:** Codex gpt-6.2-astra xhigh. Its sandbox had no PostgreSQL.
- **Reviewer 2:** Opus 5.5 high, on PostgreSQL 16, with the real pinned kyverno v1.20.0 and kubeconform v0.6.7 in the image's UBI 9 base under podman.

| Codex finding | Ruling |
|---|---|
| Medium 1: process-group kill on timeout | **Refuted by measurement.** Under strace, each CLI is one process: 1 execve, threads only (`CLONE_THREAD`), and no forks. Head already kills and reaps a hung CLI and frees its slot (2.90 s against a 2 s timeout). `killpg` would not prevent zombies under PID 1 without an init either. Backlog. |
| Medium 2: the Helm schema omits `api.validator` | **Fixed, Low** (in the changed lines). |
| Low 1: fractional or bool permits | **Fixed.** Integers only. `1.5` let 5 of 5 holders in. |
| Low 2: the 503 detail discloses slot counts | **Fixed** with `public_detail`. The problem-doc retry guidance ("Nothing was done") is kept. |
| Low 3: the busy counter counts on a 422 | **Fixed.** |
| Low 4: the version probe runs outside the slots | **Not a defect.** It runs once at startup, before uvicorn serves; 72 MiB. |
| Low 5: the metric-scan test fails | **Fixed, Medium.** CI was red on head. |

**Reviewer 2 also:**
- relocated the two docs/14 citations that Codex's patch broke;
- added `test_readyz_answers_while_twelve_dry_runs_hold_the_validator`.

**The burst on PostgreSQL** (final tree, 3 runs): 5 × 200 and 7 × 503 `validator-busy` with `Retry-After: 15` each time, a kyverno peak of 1, and every `/readyz` 200 (max 0.645 s).

The Low items are in the Backlog issue named in the PR.
