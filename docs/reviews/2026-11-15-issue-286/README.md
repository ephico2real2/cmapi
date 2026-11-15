# #286: Git delivery through the Git protocol, and a thin PR adapter for each host

OB1 run 10 (Opus 5.5 at `high`) wrote this record on 2026-11-15. Sections 1 to 7 are OB1's own design, written without
Fable's design. Section 0 is what was built: the coordinator's arbitration of the two designs, folded in after it.

## 0. The arbitration, and who designed what

Two designs, each written without the other: Fable 5.2 (`workbench/cmapi/design-286-fable/DESIGN.md`) and OB1 (sections 1 to 7
below, commit `db0738e`). The coordinator (Opus 5.5) arbitrated them (`workbench/cmapi/design-286-arbitration.md`); PR-A
builds the result. Who designed each part:

| Part | Designed by | Where it is built |
|---|---|---|
| The two layers, the bare mirror with one refspec, the worktree path and branch name, the empty lease on the first push, the fence before each effect, the credential objects, the SSH options, nss_wrapper with `/etc/passwd` at 0644 | Both | `core/git/workspace.py`, `transport.py`, `components/cmapi/30-worker.yaml`, `cmapi/Containerfile` |
| The `applied` state and the `apply_started` event in its own transaction; `merge_failed` | Fable (row 1) | `core/lifecycle.py`, `jobs/apply.py`, `jobs/delivery.py`, migration `0005` |
| One external effect per job: push_branch, open_pr, pr_checks, apply, merge, git_cleanup, git_reconcile | Fable (rows 2, 9) | `jobs/` |
| The adoption test; replacement with a lease only for this request's own trailers; a foreign head refused | Fable, with OB1's refusal (row 3) | `GitWorkspace.push_branch`, `_adoptable` |
| Deletes merge first in apply mode | OB1 (row 4) | `jobs/pr_checks.py` |
| The reproducible commit (both dates the approval's) | Fable (row 5) | `GitWorkspace._build` |
| The sweeper per pod, in the worker loop between jobs | Fable's scope, OB1's place (row 6) | `worker.py` `Worker.sweep`, `GitWorkspace.sweep` |
| One Git lock per process, and a process-ownership `flock` | OB1 (row 7) | `GitWorkspace._lock`, `.lock` |
| The branch deleted by a push with a lease, for every adapter | Fable (row 8) | `GitWorkspace.delete_branch`, `jobs/git_cleanup.py` |
| `merge-tree`: exit 1 is a conflict only with a tree OID | OB1, measured (row 10) | `GitWorkspace.merge_check` |
| No status posted while host CI is off | Fable (row 11) | `HostGitProvider.post_statuses`, `jobs/pr_checks.py` |
| Plan-time reads in the API through the host API, for PR-A | OB1 (row 12); the owner decides before PR-B | `GitHubProvider` with no Git layer in the API process |
| Git over HTTPS with the API token on CRC, an interim | OB1 (row 13) | `environments/crc/20-config.yaml` |
| A merge the host already made is adopted | Fable (row 16) | `jobs/merge.py` |
| Log fields and metrics; `redact()` of registered secrets | Fable's set, OB1's mechanism (row 17) | `core/git/oplog.py`, `core/observability.py` |
| `:revert` before a merge, and from `merge_failed` | The owner decides (row 15); PR-A refuses `:revert` with no merge sha | `routers/requests.py` |
| The test plan | Fable, sections 7.1 to 7.6 | `tests/service/test_git_layer.py` |

What changed from OB1's sections below: there is no `deliver_pr` job; the apply and the merge are two jobs, and a request
whose apply started can reach only `applied` or `sync_failed`. The trailer is `Cmapi-Request-Id`. The workdir's repository is
`repo.git`. The worker sweeps between jobs, not as a database job. Section 2.5's per-host table is now verified at each
host's documentation where it says so (docs/13, docs/18). OB1's section 2.3 on deletes stands.

The coordinator's instruction of 2026-11-15 to make `/etc/passwd` group-writable "so CRI-O adds the entry" was retracted by
the coordinator after the CRI-O source was checked (section 3, D3): CRI-O's `GeneratePasswd` returns early at line 222 when
`checkFilePermissions` is true, which is `stat.Mode&0o022 != 0` at line 314. `deploy/tests/image-git-test.sh` refuses an image
whose `/etc/passwd` group or others can write, and the Containerfile's build checks it too.

"Measured" means OB1 ran the command and the log is in `workbench/cmapi/ob1-run10/`. "Read" means a primary source, read on
2026-11-15. "Inferred" means neither.

## 1. What the owner asked for

From #286, 2026-11-15:

- "non complicated format that will work in all git repo and not married to featires in github. what we need is a token or ssh keys."
- "features there are of API integration that we keep ... we need support for gitlab and bitbucket"
- "request is checkout of the main branch using the requestID as the branch and folder name ... create the PR and merge it after request is fullfilled"
- "do we need PVC ... and cleanup that occurs when no job is running"
- "proper logging in case we have merge issues"
- "a direct requst will be wrong": nothing is ever pushed to `main`. Every change is a PR or an MR.

The owner's later decisions, through the coordinator:

- The identity on each host is a machine user account, `cmapi-git-bot`: a GitHub machine user, a GitLab service account,
  or a Bitbucket bot account. Its SSH key and its API token belong to that account, so the account is the author of every
  push and PR.
- The objects are Secret `cmapi-git-bot` (Opaque, key `token`), Secret `cmapi-git-bot-ssh` (`kubernetes.io/ssh-auth`, key
  `ssh-privatekey`, optional `ssh-publickey`, worker only), and ConfigMap `cmapi-git-bot-known-hosts`.
- The branch is `cmapi/<cluster>/<requestId>`, for example `cmapi/CRC/req-20261115-0002`. The worktree is
  `<workdir>/<cluster>/<requestId>`.

## 2. The design: two layers

Renovate's model: one Git layer for every host, and a thin platform adapter for each host for the PR alone
([Renovate platforms](https://docs.renovatebot.com/modules/platform/), [renovate#2774](https://github.com/renovatebot/renovate/pull/2774), read).

| Layer | Does | Code |
|---|---|---|
| Git | fetch, worktree, commit, push of the request branch, the merge check, reads, cleanup. The Git protocol alone | `core/git/workspace.py`, `transport.py` |
| Platform | open the PR, read its state, merge it pinned to a head, comment and close. The host's REST API | `core/git/github.py`; `gitlab.py` (PR-B); `bitbucket.py` (PR-C); `gitea.py` (exists, REST only) |
| Logging | one structured event per operation, counted | `core/git/oplog.py` |

### 2.1 The flow of one request

The owner's steps, as the coordinator wrote them, with what each step checks:

| Step | Command or call | Checks |
|---|---|---|
| 1 | `git fetch origin main` into the mirror | The folder on `origin/main` equals the plan's `prev`, or the request is `superseded` (as today, `jobs/open_pr.py`) |
| 2 | `git worktree add --no-checkout -b cmapi/<cluster>/<requestId> <dir> refs/remotes/origin/main`, then a cone sparse checkout of the request's folder | Never a local `main`, never `git pull`. A branch that already exists on the remote is reused only when its head carries this request's `Cmapi-Request` and `Cmapi-Plan-Hash` trailers; otherwise the request fails with the reason, and the branch is left as it is |
| 3 | Write the folder's files, `git add -- <folder>`, one `git commit`, `git push --force-with-lease=refs/heads/<branch>: origin <branch>` | The plan hash is checked before (as today). The empty lease means the branch must not exist yet, so two workers that both run the job cannot both write it |
| 4 | The PR, through the host API | A PR's head must be the pushed head |
| 5 | The worker's checks (kubeconform, Kyverno, the cmapi check), as `pr_checks` does today | Host CI is optional and off by default (section 2.6) |
| 6 | `delivery.mode: apply`: merge check, apply from the branch, `confirmed_by_read`, merge check again, merge pinned to the applied head. `delivery.mode: argocd`: merge check, merge, then watch Argo CD, as today | Section 2.3 |
| 7 | `git worktree remove` | The local branch goes too. The host deletes the remote branch on merge |

The commit's author and committer are `cmapi-git-bot`, with `instance.git.commitEmail` (default
`cmapi-git-bot@noreply.invalid`: RFC 2606 `.invalid` is never delivered). The trailers carry `Cmapi-Request`,
`Cmapi-Plan-Hash`, `Cmapi-Approval`, `Cmapi-Requester` and `Cmapi-Instance`.

### 2.2 Working storage: the mirror and the worktrees

Measured on 2026-11-15, with git 2.55.0 on this Mac, on a test repository that has `main` and a branch `cmapi/CRC/req-1`
(`ob1-run10` log of the command):

| Layout | Fetch refspec | Refs after the first fetch |
|---|---|---|
| `git clone --mirror --filter=blob:none` | `+refs/*:refs/*`, `remote.origin.mirror true` | `refs/heads/cmapi/CRC/req-1`, `refs/heads/main`. There is no `refs/remotes/origin/main` |
| `git clone --bare --filter=blob:none` | none | `refs/heads/cmapi/CRC/req-1`, `refs/heads/main`, as local branches |
| `git init --bare`, then `remote.origin.url`, `remote.origin.fetch +refs/heads/main:refs/remotes/origin/main`, `remote.origin.promisor true`, `remote.origin.partialclonefilter blob:none`, then `git fetch --filter=blob:none origin` | the one refspec | `refs/remotes/origin/main` (and `origin/HEAD`) |

The third is the design. A fetch then never writes into `refs/heads/cmapi/*`, the branches the worktrees hold. With the first
two layouts, a fetch rewrites or adds a local `refs/heads/cmapi/...`, and `worktree add -b` refuses the name. The
coordinator measured the `--mirror` result too (#286, last comment).

- One mirror per process, at `<workdir>/mirror.git`. The workdir holds a lock file, taken with `flock` at start: a second
  process that names the same workdir does not start.
- One worktree per request, at `<workdir>/<cluster>/<requestId>`. Both parts must match `[A-Za-z0-9][A-Za-z0-9._-]*`, so a
  path parameter cannot leave the workdir.
- A cone sparse checkout of the request's folder. In a partial clone, Git fetches the blobs of that folder alone, so a
  repository with thousands of namespaces costs one folder per request. Measured: the worktree holds `README.md` and the
  request's folder, and no other namespace's folder.

**emptyDir, not a PVC.** The remote is the source of truth, so a lost emptyDir costs one fetch. #225 runs two or three worker
replicas, and an RWO PVC cannot be shared between them; RWX adds a storage dependency for a cache.

Measured on 2026-11-15, three runs each, from this Mac to github.com, of `ephico2real2/cmapi-cluster-configs`. That is a
private repository with 7 commits and 13 files, and GitHub reports its disk usage as 21 KB:

| Clone | Time | Size on disk |
|---|---|---|
| `--bare --filter=blob:none` | 1.06 s, 0.99 s, 0.98 s | 104 KiB |
| `--bare` (full) | 0.93 s, 0.99 s, 0.94 s | 112 KiB |

At this size the clone is a round trip to GitHub, and the filter saves nothing measurable. A repository of 5,000
namespaces is not measured. The `sizeLimit` is 1 Gi: inferred, about 10,000 times the measured size, with room for the
worktrees. When the limit is passed, the kubelet evicts the pod, and the new pod fetches again.

Only the worker has the Git layer. The API process reads through the host API (section 2.5).

### 2.3 Apply before merge, and `merge_failed`

`delivery.mode: apply` (CRC) follows the Atlantis model ([runatlantis.io](https://www.runatlantis.io/), read): apply,
confirm, then merge, so that `main` records only what succeeded. A new job, `deliver_pr`, takes over from `pr_checks` when the
checks pass:

1. The branch head is the head the checks passed on, and the branch's folder is the approved plan.
2. The merge check (section 2.4). It runs before the apply, so nothing is applied that cannot merge.
3. Server-side apply of the folder with the deliverer identity, and removal of the objects the plan drops, as `watch_sync`
   does today. A namespace that exists and is not cmapi-managed is refused, and nothing is applied.
4. `confirmed_by_read`. While the read does not confirm, the job waits at `pollInterval`, up to `syncTimeout`.
5. The merge check again, then the merge, pinned to the applied head (GitHub: `PUT /pulls/{n}/merge` with `sha`).
6. `merged`, then `synced`. The read in step 4 already confirmed the change.

What a failure does depends on whether the cluster holds the change:

| Failure | Cluster holds the change | Result |
|---|---|---|
| At step 1, 2 or 3, before anything is applied | No | `failed`, with the reason. The PR gets a comment and is closed. `main` is untouched. The lock is released, which is safe |
| At step 4 (not confirmed), or 5, after the apply | Yes | `merge_failed` (F1 of Fable's review). The PR and the branch are kept. The job retries with the worker's backoff (5, 15, 45, 135, 405 s). After five attempts it records an event and stops; alert `CmapiMergeFailed` fires on `cmapi_open_request_age_seconds{status="merge_failed"}`. `:retry` runs `deliver_pr` again, pinned to the applied head. The cluster is never rolled back, and the PR is never closed automatically |

`merge_failed` is in `OPEN_STATES` (`core/db/models.py:17`), so it holds the namespace's lock (409 `change-pending`) and the
reservation. Without it, `failed` would release the lock while the cluster holds a change that `main` lacks, and the next
plan, which reads `main` (`jobs/open_pr.py:41-45`), would overwrite it. The lock is a partial unique index, so migration
`0005` recreates `uq_cr_open_namespace` with `merge_failed` in its `WHERE` list. No row can hold `merge_failed` before that
revision, so the new index cannot meet a duplicate. The downgrade refuses while a `merge_failed` row exists.

The transitions: `pr_open` + `merge_failed` gives `merge_failed`; `merge_failed` + `retry` gives `merge_failed` (the job runs
again); `merge_failed` + `merged` gives `merged`.

**Deletes merge first, in both modes.** A delete's "apply" is the prune, and the prune waits for an operator's
`POST /admin/prune:confirm` for an unbounded time (`jobs/watch_sync.py`, `prune`). Holding a PR open for that long, and
merging it after a human step, adds a state and a branch that can go stale, for no gain: until the prune, the namespace
exists in both orders. So a delete merges after the merge check, as today, and then waits in `awaiting_prune`. This is OB1's
choice, open to arbitration.

**`delivery.mode: argocd`** merges first, after the merge check, because Argo CD follows `main`. Then `watch_sync`, as today.

### 2.4 The merge check (D6)

Before each merge (and before the apply), in the mirror:

1. `git fetch origin main`.
2. `git merge-tree --write-tree --name-only -z <origin/main> <head>`.
3. The request's folder on `origin/main` compared with the plan's `prev`. Since one open request per namespace holds the
   folder (`core/db/repo.py`, `change-pending`), a difference is a hand edit or a fault, never a race.

[git-merge-tree(1)](https://git-scm.com/docs/git-merge-tree), EXIT STATUS, read: "For a successful, non-conflicted merge, the
exit status is 0. When the merge has conflicts, the exit status is 1. If the merge is not able to complete (or start) due to
some kind of error, the exit status is something other than 0 or 1."

Measured, against that text:

| Case | git 2.52.0 (the image's `git-core-2.52.0-1.el9`) | git 2.55.0 (this Mac) |
|---|---|---|
| A clean merge | 0 | 0 |
| A conflict | 1 | 1 |
| An unknown ref, or an object that is not there ("not something we can merge") | **1** | **1** |

So exit 1 alone does not mean a conflict. The check counts a result as a conflict only when the exit is 1 and the first field
of stdout is a tree OID (40 hex characters, or 64 for SHA-256). Any other result is an error, logged with its stderr, and
never read as conflict-free. The shas the check passes are always resolved first (`rev-parse --verify`). The WIP code
(`3c4e5a5`) does not yet look at the OID; that is a required fix. Measured output of `-z --name-only` on a conflict:
`<tree>\0<path>\0\0<messages>`.

### 2.5 Credentials (F2, F3, F4, and the bot account)

| Object | Kind | Keys | Mounted in | At | Used by |
|---|---|---|---|---|---|
| `cmapi-git-bot` | Secret, Opaque | `token`, optional `username` | api, worker | `/etc/cmapi/git-bot` (`CMAPI_GIT_CREDENTIALS_DIR`) | The host API. Git over HTTPS too, as an interim transport (below) |
| `cmapi-git-bot-ssh` | Secret, `kubernetes.io/ssh-auth` | `ssh-privatekey`, optional `ssh-publickey` | worker only | `/etc/cmapi/git-bot-ssh` (`CMAPI_GIT_SSH_DIR`) | Git over SSH |
| `cmapi-git-bot-known-hosts` | ConfigMap | `known_hosts`: every key type the host publishes (GitHub: ed25519, ecdsa, rsa) | worker only | `/etc/cmapi/git-bot-known-hosts` (`CMAPI_GIT_KNOWN_HOSTS_DIR`) | ssh's `UserKnownHostsFile` |

- Each is a directory mount with `defaultMode: 0440`, `readOnly: true`, and `items` for the named keys. A `subPath` mount
  never sees an update; a directory mount does, so a `known_hosts` rotation needs no restart. To rotate a host key: add the
  new key, then remove the old one.
- The URL's transport decides the Git credential. Exactly one applies to the transport. A PR provider with no API token
  stops at start. The WIP refusal of both credentials together (`plain.py:135-136` on branch `plain-git`) is dropped.
- **SSH:** `GIT_SSH_COMMAND` with `-F /dev/null`, `-i <key>`, `IdentitiesOnly=yes`, `IdentityAgent=none`,
  `UserKnownHostsFile=<mount>/known_hosts`, `GlobalKnownHostsFile=/dev/null`, `StrictHostKeyChecking=yes`,
  `UpdateHostKeys=no`, `BatchMode=yes` ([ssh_config(5)](https://man.openbsd.org/ssh_config), read). The SSH user is `git`
  (`git@<host>`); the key selects the account. At start cmapi runs `ssh-keygen -y -P ''` on the key. A key that does not
  parse, has a passphrase or is not ed25519 stops the start. So does an `ssh-publickey` that is not that key's. The key's
  SHA256 fingerprint is logged at start.
- **HTTPS:** a `credential.helper` shell snippet set through `GIT_CONFIG_KEY_<n>` and `GIT_CONFIG_VALUE_<n>` (git-config(1),
  read; [gitcredentials(7)](https://git-scm.com/docs/gitcredentials), read). It holds the token file's path, never the token,
  and it is in no argv and no config file. `http.sslVerify=true` is always set, and `http.sslCAInfo` is
  `CMAPI_GIT_CA_BUNDLE` (else `CMAPI_CA_BUNDLE`). This gives the bot's API token to Git, which F2 avoids for SSH. It is the
  interim transport for CRC until the owner adds the bot account's SSH key (the coordinator, 2026-11-15). Recorded as a
  known exception.
- **Each git process** gets an environment built from nothing: `PATH`, a private `HOME`, `LANG=C`,
  `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_SYSTEM=/dev/null`, `GIT_TERMINAL_PROMPT=0`, `GIT_ALLOW_PROTOCOL=<the URL's
  transport>`, `core.hooksPath=/dev/null`, and the author. No `CMAPI_*` variable and no `GIT_*` setting of the worker reaches
  it (the test sets `GIT_TRACE` and `GIT_SSL_NO_VERIFY` in the worker and finds neither).
- **The API process has no Git layer.** F2 puts the SSH key in the worker alone, so plan-time reads (the folder, the branch
  head, the log) in the API go through the host API with the token: GitHub's contents, branches and commits endpoints, as
  before #286. The worker reads through Git. This is OB1's consequence of F2, open to arbitration. The alternative, a second,
  read-only SSH key for the API, adds a key for the owner to manage.

**The per-host table (F3).** The bot account is the default; a deploy key is the alternative. These rows are the review's
claims, and they are **not yet verified** by OB1 at each host's documentation. Each one is checked at its primary source
before it goes into docs/13 and docs/18:

| Host | Bot account (default): SSH | Bot account: API | Alternative: SSH | Alternative: API |
|---|---|---|---|---|
| GitHub | the machine user's SSH key | the machine user's fine-grained token: Contents and Pull requests read and write | a write deploy key | a GitHub App |
| GitLab | the service account's SSH key | the service account's token | a read-write deploy key made by the service account | a project access token |
| Bitbucket Cloud | the bot account's own key (access keys are read-only) | a repository access token, or the bot's API token | none | none |
| Bitbucket Data Center | the bot user's key | the bot user's token | a write access key | a repository-scoped token |
| Gitea | the bot user's key | the bot user's token | a write deploy key | a repository-scoped token |

`main` is protected on each host so that only a merged PR changes it, so the host enforces "never push to `main`" too. On
CRC that is not possible: the private repository is on GitHub's free plan, which refuses branch protection (#227).

### 2.6 Host CI

Optional and off by default (`instance.git.hostChecks: false`). The gate is cmapi's: plan-time kubeconform and Kyverno, the
same checks again in `pr_checks` on the PR head, and approval in cmapi. When it is on, the adapter reads commit statuses
alone, which every host has, and never GitHub's Checks API: a fine-grained token cannot call it (BUG-69, #279). When it is
off, the worker posts `ci/kubeconform`, `ci/kyverno` and `cmapi/check` as commit statuses, as a record. That needs Commit
statuses write on GitHub.

### 2.7 Cleanup (D5 is in section 3)

- **At the end of a PR** (merged, or closed by cmapi): `git worktree remove --force --force`, `git worktree prune`, and the
  local branch is deleted.
- **The sweeper,** job `git_sweep`, every 600 s, recurring. It holds the workspace's lock without waiting: when a Git
  operation of this process holds it, the sweeper logs `skipped` and touches nothing. It removes the folder and the local
  branch of every request that is not in flight (`approved`, `pr_open`, `merge_failed`), runs `git worktree prune`, and runs
  `git gc --auto`. Each pass is one `cleanup` event with the removed paths, counted in `cmapi_git_operations_total`.

### 2.8 Logging

Each Git and platform operation logs one `git_op` event (`core/git/oplog.py`) with:

- `request_id`, `cluster`, `namespace`, `branch` and `attempt`, set once for each job with `git_context`;
- `op`: clone, fetch, worktree, commit, push, pr_open, pr_find, pr_state, status_read, status_write, merge_check, merge,
  branch_delete, pr_comment, pr_close, cleanup;
- `main_sha`, `base_sha`, `head_sha`;
- `outcome` (ok, refused, conflict, absent, skipped, failure) and `duration_ms`;
- on a Git failure, the exit code and redacted stderr; on a host refusal, the HTTP status and the host's message;
- on a conflict, the conflicted paths.

The same reason goes on the request's timeline (`merge_refused`, `branch_refused`, `error`), so `GET /requests/{id}` shows
it. The counter is `cmapi_git_operations_total{op,result}`; the label was `operation`. The alert expressions use only
`result` and `namespace` (`environments/crc/50-monitoring.yaml`, the chart's `monitoring.yaml`), so they keep working.

Every value of an event passes `redact()`, which removes each registered secret (the bot's token, as read at start). A test
proves it on a host refusal whose message echoes the token.

## 3. D3, D5, D6 and D7

### D3: SSH under an arbitrary UID

**Measured, the fault.** In the base image, `ssh` run as UID 1001 with no `/etc/passwd` entry
(`podman run --user 1001 --passwd=false`) stops with `No user exists for uid 1001`, exit 255. OpenSSH looks up its own UID
with `getpwuid()` before it reads any configuration, so neither the account name nor `-F` changes it
(`ob1-run10/imgsize/nss-before-after.log`).

**Read, what OpenShift does.**

- CRI-O, `utils/utils.go` on `main`: `GeneratePasswd` "generates a container specific passwd file, iff uid is not defined in
  the containers /etc/passwd". It returns early when `checkFilePermissions` is true, and that function is true when
  `stat.Mode&0o022 != 0`, that is when group or others can write the file. The coordinator checked the line numbers: the
  return at line 222, the test at line 314.
- Red Hat, ["OpenShift Containers - Modification of /etc/passwd"](https://access.redhat.com/articles/4859371): from
  OpenShift 4.2, CRI-O "inserts the random user for the container into /etc/passwd". A group-writable `/etc/passwd` lets any
  process in the container edit it. Before 4.2, the article names nss_wrapper.

**The fix.**

- `/etc/passwd` stays as the base image has it: 0644, root (measured). CRI-O on OpenShift then adds the pod's UID.
- Where nothing adds it (podman, containerd), the Git layer sets nss_wrapper for ssh's git processes alone, and only when
  `getpwuid()` fails. It writes a private passwd file and group file under its own home, and sets `LD_PRELOAD`,
  `NSS_WRAPPER_PASSWD` and `NSS_WRAPPER_GROUP` in that environment alone. `nss_wrapper-libs-1.1.13-1.el9` is in the UBI 9
  repositories (measured) and gives `/usr/lib64/libnss_wrapper.so`.

**Measured, before and after,** in an image of the base, git-core, openssh-clients and nss_wrapper-libs, run with
`podman run --user 1001 --passwd=false`:

| | Result |
|---|---|
| ssh with no passwd entry | `No user exists for uid 1001`, exit 255 |
| ssh with nss_wrapper and a private passwd file | `connect to host 127.0.0.1 port 1: Connection refused`: past the lookup, to the network |
| `/etc/passwd` after both runs | `-rw-r--r-- root root`, unchanged |

**Rejected:**

| Option | Why |
|---|---|
| `chmod g+w /etc/passwd` in the image, "so CRI-O adds the entry" (the coordinator's instruction of 2026-11-15, retracted by the coordinator after the CRI-O source was checked) | It does the opposite: CRI-O skips a group-writable file (line 222, line 314 above), so the entry would then depend on an entrypoint script. It also lets any process in the container edit `/etc/passwd` (Red Hat 4859371) |
| An entrypoint that appends the UID to a writable `/etc/passwd` | The manifests set `command:`, which replaces the entrypoint. It also needs the writable file |
| A static `/etc/passwd` entry for UID 1001 | It covers only the image's default UID, not a UID that the platform picks |

**Test:** a test that the built image's `/etc/passwd` is not group- or other-writable, so nobody brings it back, and a unit
test of the nss_wrapper environment. The podman run above is the proof under the arbitrary UID. CI cannot run as a UID
without an entry unless the job uses podman.

### D5: concurrency of worktrees

- One process owns a workdir (`flock` on `<workdir>/.lock`). Each worker replica has its own emptyDir, so mirrors are never
  shared.
- Within a process, one lock serialises every Git operation. The worker runs one job at a time, and the sweeper does not
  wait for the lock.
- Two requests always name two namespaces (the lock), so they get two branches and two worktrees. Measured in the test: two
  worktrees side by side, each with only its own folder.
- One job claimed twice after a lease expired: the first push of the branch wins, through the empty lease. The second
  finds the branch with its own trailers and reuses it.
- The fence (`jobs.fence()`) still comes before each external write (push, PR, merge, close).

### D6: `merge-tree` exit codes

Section 2.4. Measured: exit 1 also for "not something we can merge", on 2.52.0 and 2.55.0. So a conflict is exit 1 with a tree
OID as the first field, and every other result is an error.

### D7: cases the issue does not list

| Case | What happens |
|---|---|
| `main` does not exist on the remote (an empty repository) | `GitUnavailable: branch main does not exist`, retried, then failed. The repository needs one commit |
| A person pushes to the request branch after the PR opens | `pr_checks` sees the head moved (as today) and fails. `deliver_pr` checks the head again before the apply and pins the merge |
| A person merges or closes the PR by hand | Before the checks pass, `pr_checks` reads `merged` or `closed`, as today, and a hand merge then goes through `watch_sync`, which applies from `main`. While `deliver_pr` runs, the WIP code finds the branch gone and fails the request: `deliver_pr` must read the PR's state first and take a hand merge as `merged`. Open |
| The host merges, and the worker stops before it records the merge | The job runs again: the PR reads `merged`, and the request moves on (as today) |
| A conflict that appears between the pre-apply check and the merge | `merge_failed`: PR kept, alert, `:retry` |
| The emptyDir is lost or evicted | The next operation fetches again. The worktree of a `pr_open` request is gone, which is harmless: the branch is on the remote, and later steps read it from the mirror |
| A stale `*.lock` file after a crash | The process owns the workdir (flock), so at start it removes the mirror's `*.lock` files. A mirror that is not a repository any more is removed and fetched again |
| Token rotation | The HTTPS helper reads the token file at each call, so Git follows the Secret's update. The platform client reads the token at start, so a rotation still needs `rollout restart` |
| A known_hosts rotation | Directory mount: no restart |
| A path in a plan outside the request's folder | Refused before Git runs (`check_path` and the folder prefix) |

## 4. The options rejected for the whole design

| Option | Why |
|---|---|
| A direct commit to `main` (the first WIP of this issue, branch `plain-git`) | The owner: "a direct requst will be wrong". It also dropped the PR history the owner keeps |
| Dulwich or pygit2 instead of the git CLI | Each adds a PyPI dependency outside RHEL's errata. pygit2's wheel bundles native libgit2 and its SSH library, and the host key check would be cmapi's own code. Dulwich runs `ssh` for SSH anyway. The git CLI and OpenSSH come signed from the UBI repositories |
| The host's Contents and Git Data APIs for writes (before #286) | Married to one host, which is what the owner rejected |
| A PVC for the working storage | Section 2.2 |
| `git clone --mirror` or `--bare` for the cache | Section 2.2: both write `refs/heads/cmapi/*` on fetch |

## 5. The image

Measured with `podman image inspect` on 2026-11-15:

| Image | Size, bytes | Packages |
|---|---|---|
| `ubi9/python-312-minimal@sha256:b99faaad...` | 189,959,254 | none of these |
| + `git-core`, `openssh-clients` | 251,860,494 | `git-core-2.52.0-1.el9`, `openssh-clients-9.9p1-16.el9_9` |
| + `nss_wrapper-libs` | 251,860,529 | `nss_wrapper-libs-1.1.13-1.el9`, 79,462 bytes installed (`rpm -q --qf %{SIZE}`) |

So the image grows by 61,901,275 bytes, almost all git-core and openssh-clients with their dependencies (util-linux, PAM,
cracklib: `imgsize/added.txt`). The two builds differ by 35 bytes although nss_wrapper-libs installs 79,462: other files of
the two builds differ too (inferred: microdnf's state after `clean all`). The figure that matters is the 61.9 MB. `ssh-keygen` comes with `openssh`, a dependency of `openssh-clients`.

## 6. Tests (PR-A)

Against real repositories (file://, HTTPS through `git http-backend` behind TLS and Basic auth, SSH through a throwaway sshd
with a pinned host key), with a stub of GitHub's PR API over the same bare repository whose merge is a real merge commit
(`tests/service/gitserver.py`):

- create, change and delete, each its own branch and PR; apply before merge, with `main` not holding the change at the apply;
- two requests on two namespaces at once: two worktrees, no cross-contamination, both merge;
- a conflicting `main`: refused before the apply, with the path on the timeline and in the log event;
- an applied change whose merge then fails: `merge_failed`, the lock holds (409 `change-pending`), the PR stays open, and
  `:retry` reaches `synced`;
- a branch that exists without this request's trailers: refused and left alone; one with them: reused, no second commit;
- the sweeper: removes what is not in flight, keeps what is, skips while a Git operation runs, logs and counts;
- an unknown host key (wrong key, and host not listed): refused, nothing added to `known_hosts`;
- the SSH key: encrypted, not ed25519, unparseable, and `ssh-publickey` mismatched, each refused at start;
- no token in an argv, an environment, any file of the workdir, or a log line;
- `merge-tree`: clean 0, conflict 1, error 1 with no tree OID read as an error;
- `/etc/passwd` in the built image is not group- or other-writable.

CI runs the SSH tests with `CMAPI_TEST_REQUIRE_SSHD=1`, so a missing sshd fails the job instead of skipping them.

## 7. Open for the arbitration

1. Deletes merge first in apply mode (section 2.3).
2. The API process reads through the host API, with no Git layer (section 2.5).
3. Git over HTTPS uses the API token, on CRC, until the bot's SSH key exists (section 2.5).
4. The per-host table (section 2.5) is not yet verified at each host's documentation.
5. `merge_failed` has no `:revert`: the namespace's lock blocks a revert request. `:retry` is the only way out, or an operator
   merges the PR by hand, which `deliver_pr` then reads as `merged`.
