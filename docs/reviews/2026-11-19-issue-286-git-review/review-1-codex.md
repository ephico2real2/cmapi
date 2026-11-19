# Adversarial review of cmapi Git delivery

Reviewed the supplied `./main` archive, identified by the coordinator as main `b8ee59e`, against the design record and all 17 arbitration rulings. The archive has no Git object database, so the commit identity is supplied provenance, not an independently verified object hash. All source locations below refer to **unpatched main**, relative to `./main`. Abbreviated core/, jobs/, routers/ and worker.py references share the prefix cmapi/src/cmapi/. Review and proposed fixes only: no GitHub network calls or cluster contact, and no push, merge or publication of the project repository. Test fixtures alone push to disposable file:// repositories. Real Git tests used disposable file:// repositories; HTTP tests used in-process MockTransport.

**Recommendation: do not certify G1–G8 as a group. Nine findings have executable regression tests and complete fixes in `codex-fixes.patch`.** The patch is a review artifact, not a claim that every distributed crash/interleaving has been proved. It intentionally makes unsupported Gitea operations fail closed and has the operational limits described below.

## Verdicts

A composite claim is refuted when one component has a counterexample. “Confirmed” below applies only to the named Git layer and evidence described, not to unavailable database or live-host tests.

| Claim | Verdict | Evidence and limits |
|---|---|---|
| G1 locking and no repeated external effect | **REFUTED as a composite.** | The namespace index includes applied/merge_failed: `cmapi/src/cmapi/core/db/migrations/versions/0005_applied_and_merge_failed_hold_the_lock.py:26` and `:21`; model `core/db/models.py:18`; lifecycle `core/lifecycle.py:93`. `core/db/repo.py:249` claims jobs with SKIP LOCKED; `:262` takes a job-row lock for the generation check and `:268` fences. Those are sound structural components; actual PostgreSQL mutual exclusion was blocked. F8 demonstrates a repeated external comment despite fencing. A fence held in the same DB transaction need not be repeated before every call to retain its job-row lock, but it does not make a successful host POST atomic with the DB commit. |
| G2 leases/adoption/deletion | **REFUTED across adapters; confirmed for tested GitWorkspace paths.** | `core/git/workspace.py:420` builds a force-with-lease push, `:462` uses the empty lease, `:357` checks adoption, `:452` refuses foreign trailers, and `:522` implements conditional deletion. The real-Git control passes on both trees. F7 disproves the all-adapter claim: Gitea adopts without that test and performs unconditional REST deletion (`core/git/gitea.py:63`, `:111`). Also, the user's “otherwise replaced” must be narrowed by arbitration ruling 3: foreign heads are refused, only this request's stale attempt may be replaced. |
| G3 merge safety | **REFUTED as a composite.** | The measured exit-1/no-tree rule is correctly implemented in `core/git/workspace.py:496`; local Git 2.55.0 measurement reproduced it. GitHub sends the checked head as the merge `sha` (`core/git/github.py:206`), preventing head TOCTOU on that request. This is not a lock on the default branch. F5 disproves complete hand-merge adoption; F6 disproves universal enforcement of the post-merge folder check. |
| G4 apply before merge and failure states | **REFUTED literally; normal ordering is implemented.** | `jobs/pr_checks.py:142` selects apply for non-deletes; `jobs/apply.py:94` applies, `:122` records APPLIED and queues merge afterward; `jobs/merge.py:38` requires applied/merge_failed for this route. Deletes merge first, then `jobs/watch_sync.py:78` waits for prune, consistent with ruling 4. Apply failures after the marker deliberately become **sync_failed**, not merge_failed (`jobs/apply.py:48`; `worker.py:156`). That is an operator-actionable lock-holding state, not a defect to “fix” into merge_failed. Merge failures after a successful apply become merge_failed (`worker.py:162`). PostgreSQL flow tests were blocked. F5/F6 are additional delivery-state defects. |
| G5 reproducible commits and retry no-op | **CONFIRMED for GitWorkspace.** | `core/git/workspace.py:410` sets both dates from approved_at; `:412` supplies the message through stdin; `:448` adopts the existing approved commit before building. The real-Git regression checks both epoch dates, identical SHA and no second push, passing on main and fixed. This does not certify Gitea REST commits: `core/git/gitea.py:86` does not supply dates, and its existing-branch protocol differs (F7). |
| G6 credentials | **REFUTED.** | F1, F2 and F4 demonstrate error/history, recursive/short-secret redaction and permissions gaps. Positive evidence: `core/git/transport.py:111` builds a clean environment; `:126` places a quoted credential-helper path, not the HTTPS token, in config; `:132` constructs SSH options with StrictHostKeyChecking=yes and fixed known_hosts. The inherited ASKPASS/SSH-command test passes on both trees. The SSH key contents are not put in argv; its **path** is. Actual SSH/HTTPS server and database-history tests could not run. |
| G7 request inputs cannot inject options or escape storage | **REFUTED.** | F3 proves a repository symlink escapes the worktree despite lexical `check_path`; F9 proves a leading-dash folder is parsed as a sparse-checkout option. Positive components: `core/git/transport.py:102` rejects traversal; `core/git/workspace.py:343` restricts cluster/request directory components, `:404` uses -- for add, `:412` passes commit messages via stdin. Renderer paths normally start with clusters/, so the top-level leading-dash case is a Git-layer contract failure, not a demonstrated API namespace-validation bypass. |
| G8 every-line retry/restart recovery | **REFUTED.** | F5 demonstrates an unadopted hand merge; F8 demonstrates duplicate retry effects; F7's REST branch handling cannot satisfy the Git-layer retry contract. `jobs/git_reconcile.py:60` cleans final/unknown rows, `:80` leaves cluster-ahead states alone, `:89` requeues stalled approved work, and `:94` only counts certain pr_open stalls. Reconcile does **not** itself reclaim job leases or release namespace locks: worker claim/DB transaction recovery does that (`core/db/repo.py:248`, `worker.py:106`). The “restart at any line” universal claim is not established by this bounded review or by the proposed patch. |

## Findings, scenarios, complete fixes and regressions

The complete implementation of **every** fix and **every** regression below is in the single -p1 patch, reproduced in full in Appendix C. No pseudocode or omitted additions are required. Test names refer to the new `cmapi/tests/test_codex_git_review.py`. Its repository operations use real Git; job-helper tests use small repository/job doubles and the production lifecycle transition function. They are not substitutes for PostgreSQL concurrency tests.

### F1 — High: host errors carry registered credentials into worker logs and request history

**Location:** `cmapi/src/cmapi/core/git/base.py:136`, `:142`; `core/git/github.py:182`; `worker.py:133`, `:153`, `:173`.

A host response or HTTP transport error echoes the API token. `Op` sanitizes its own event, but the raised GitUnavailable/PlatformRefused still holds the raw message. Worker exception logging and error events then persist it. A transport exception is also chained with its raw message. Tests on main show the synthetic token in the exception for 403, 502 and transport failures; the worker sinks are established by the cited source, not by a database run.

**Full fix:** sanitize the GitUnavailable exception boundary and PlatformRefused.host_message; suppress the raw HTTP exception chain. Host response bodies remain unmodified for control-flow classification. Appendix C: `core/git/base.py`.

**Tests:** `test_host_error_never_contains_registered_token[403]`, `[502]`, `test_http_transport_error_never_contains_registered_token`: **3 fail on main; 3 pass fixed**.

### F2 — Medium: redaction is shallow, ignores short credentials, and is order-sensitive for overlaps

**Location:** `cmapi/src/cmapi/core/git/oplog.py:29`, `:36`, `:84`.

Short configured credentials never register, and a dictionary nested in an event/list bypasses redaction. Iterating an unordered set can replace a shorter credential prefix before its longer registered value, leaving a suffix visible. The deterministic regression demonstrates the short/nested cases; the overlapping-prefix hazard follows from the replacement loop and is not claimed as a separately deterministic baseline failure.

**Full fix:** register all nonempty values, take a locked snapshot, use one longest-first escaped regex substitution, and recursively sanitize dictionary keys/values and sequences. Register the SSH key text as defense in depth. Parse raw Git stderr before sanitizing it, so a short credential such as t cannot change “couldn't find remote ref” or “stale info” into an unrecognizable classifier. Appendix C: `oplog.py`, relevant `workspace.py` hunks. The existing API-no-workspace test expectation now uses redact() because its token is deliberately t.

**Test:** `test_nested_short_and_overlapping_secrets`: **fails main; passes fixed**. Actual Git retry/adoption control passes with the new redactor. Limitation: substring redaction of a one-character credential necessarily makes some operator text harder to read.

### F3 — High: a checked-out symlink lets a plan overwrite a file outside the worktree

**Location:** `cmapi/src/cmapi/core/git/workspace.py:397`–`:403`; lexical checks at `:350`; folder reads deliberately ignore symlink blobs at `:281`.

Put namespace.yaml in main as a symlink to a writable file outside the worktree. The manifest reader omits it, so it can look like an absent manifest. `_build` then follows that symlink with write_text. The later “nothing to commit” error does not undo the external file overwrite. The regression uses a real committed symlink and proves the outside sentinel changes on main, even though push_branch raises.

**Full fix:** reject any symlink in the target's components inside the checkout before writes or deletes. Validate the unstripped folder as a repository path. Appendix C: `workspace.py` `_check_files`/`_build`.

**Test:** `test_repository_symlink_cannot_overwrite_outside_worktree`: **fails main; passes fixed**, with the outside sentinel unchanged after the fixed refusal. This protects repository-provided symlinks; hostile concurrent mutation by another process with the same UID is not a proven security boundary.

### F4 — Medium: configured workdir and private home inherit public traversal permissions

**Location:** `cmapi/src/cmapi/core/git/workspace.py:107`–`:117`.

With an explicit workdir and umask 022, mkdir creates 0755 directories and the lock is 0644. Other local UIDs with access to the volume can traverse and read checkout/mirror contents and private home files. This does not prove that the mounted credential files themselves become world-readable.

**Full fix:** private 0700 root/home and 0600 lock; if a root-owned fsGroup-writable volume refuses chmod, create an owned `.private-<uid>` child, refusing a symlink there. Appendix C: `workspace.py` constructor. The fsGroup fallback is source-reviewed but not tested under a second real UID here.

**Test:** `test_workspace_is_private_under_permissive_umask`: **fails main; passes fixed** after a real branch build.

### F5 — High: a hand merge after checks is failed rather than adopted by the apply job

**Location:** `cmapi/src/cmapi/jobs/apply.py:65`–`:80`; `_stop` at `:48`; lifecycle table `core/lifecycle.py:80`.

Checks pass and queue apply. A person merges the PR and deletes its branch before apply runs. Main's apply job treats branch absence as head movement, transitions to failed and schedules cleanup rather than recording the merge and continuing delivery. Keeping the branch also fails the base comparison after main already contains the plan. A retry of sync_failed after a partial apply needs the same adoption path.

**Full fix:** inspect PR state before branch checks, and inspect again on branch/base-check failures; adopt merged PRs through the common post-merge verifier. Allow SYNC_FAILED -> MERGED for adoption during retry, retaining the lock. Appendix C: `jobs/apply.py`, `core/lifecycle.py`, lifecycle test update.

**Tests:** `test_hand_merge_between_checks_and_apply_is_adopted[pr_open]` and `[sync_failed]`: **2 fail main; 2 pass fixed**. The fixed tests verify merge_sha and exactly the watch_sync/cleanup continuation, without a new merge or cluster write.

### F6 — High: post-merge folder mismatch is not a gate on all paths

**Location:** `cmapi/src/cmapi/jobs/merge.py:138`–`:152`; `jobs/pr_checks.py:59`–`:65`; delete shortcut `jobs/watch_sync.py:78`.

The merge job logs a mismatched merge tree before any apply, then queues normal delivery anyway. The pr_checks hand-merge fast path skips the merge-folder read entirely. For creates/updates watch_sync has a later main-folder guard, but that checks current main rather than the actual merge tree; for deletes it reaches awaiting_prune before any such guard. A later main change could otherwise mask that this merge did not fulfill the plan.

**Full fix:** share `_merged` with pr_checks, and make a missing/mismatched merge folder become sync_failed in every route, without queueing watch_sync. Keep merge_sha and the lock for operator action. After a merge has happened, sync_failed is more accurate than pretending the merge itself did not happen. Appendix C: `jobs/merge.py`, `jobs/pr_checks.py`.

**Tests:** `test_wrong_merge_tree_never_queues_delivery[pr_open]` and `test_hand_merge_during_pr_checks_uses_postmerge_check`: **2 fail main; 2 pass fixed**. `[applied]` is a **passing control on both**; main already enforces that case.

### F7 — High: Gitea bypasses adoption and uses unconditional branch deletion

**Location:** `cmapi/src/cmapi/core/git/gitea.py:63`–`:69`, `:111`–`:119`; architecture exclusion `core/git/__init__.py:26`.

An existing PR is sufficient to adopt an arbitrary branch head without trailers, parent or folder checks. Without a PR, the adapter deletes the existing branch unconditionally. Cleanup separately reads the head then performs REST DELETE, which can erase a person's concurrent push between those requests. This contradicts arbitration rulings 3 and 8 even though the implementation labels Gitea a stand-in.

**Full fix:** fail closed on existing-branch adoption/replacement and on deletion of an existing ref, with explicit errors requiring Git transport. No unconditional delete remains in these paths. Appendix C: `core/git/gitea.py`.

**Tests:** `test_gitea_never_deletes_or_adopts_an_unverified_existing_branch[push]` and `[delete]`: **2 fail main; 2 pass fixed**. The baseline deletion sends DELETE, observed in MockTransport. The concurrent-loss scenario is an inference from that unconditional endpoint; no live Gitea service was contacted.

**Operational limitation:** this is a safety fix, not full Gitea migration. Interrupted REST pushes may require an operator, existing refs are not automatically removed, and cleanup will report failure. To provide automatic retry plus conditional mutation on this adapter, move it onto GitWorkspace in a separate, deployment-tested change. Do not describe this patch as restoring all of G2/G8 for Gitea.

### F8 — Low: a lost successful comment response duplicates the comment on retry

**Location:** `cmapi/src/cmapi/core/git/github.py:218`–`:225`; callers `jobs/merge.py:52`, `jobs/delivery.py:131`.

The host persists the comment but returns 502, or the worker stops after the POST. The next attempt posts the same comment again. A lease fence only serializes ownership; it cannot roll back a host-side append.

**Full fix:** read all pages of existing comments and adopt an exact matching body before POST. Update the offline GitHub stub to implement the corresponding GET. Appendix C: `core/git/github.py`, `tests/service/gitserver.py`.

**Test:** `test_lost_comment_response_is_adopted_on_retry`: **fails main with two stored comments; passes fixed with one**.

**Limit:** this fixes sequential retry after response loss. Read-before-POST is not an atomic host idempotency key; two independently authorized concurrent writers could still race. Therefore the patch does not establish universal exactly-once semantics. It also adds a comments-read dependency; live-host permission compatibility was not checked under this no-GitHub-contact review.

### F9 — Medium: sparse-checkout parses a leading-dash folder as an option

**Location:** `cmapi/src/cmapi/core/git/workspace.py:390`; unlike git add at `:404`, sparse-checkout has no -- separator.

A BranchRequest with folder -folder reaches git sparse-checkout set --cone -folder. Git interprets it as options and exits; the approved branch cannot be delivered. This is a demonstrated option-parsing/availability failure, not demonstrated arbitrary shell execution. Normal namespace renderer paths have a clusters/ prefix.

**Full fix:** add -- before the sparse-checkout folder. Appendix C: `workspace.py`.

**Test:** `test_leading_dash_folder_is_a_path_not_an_option`: **fails main; passes fixed**, builds a real commit, and reads back exactly the requested file.

## Runs and reproduction

Interpreter in every pytest command:
`/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python`.

The same regression source was temporarily copied to `main/cmapi/tests/test_codex_git_review.py` to avoid pytest discovering the fixed tree's pyproject.toml/pythonpath. It was removed after the baseline run; production source under main was never patched. Work was done under `./fixed`. Generated __pycache__ directories were removed before patch generation. An earlier cross-tree-path invocation imported fixed code and was discarded as invalid baseline evidence. An early unbounded service run was interrupted during its database wait; all service results below use the bounded run instead.

Baseline, from `main/cmapi` (regression source only temporarily installed):

```sh
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/test_codex_git_review.py -q -p no:cacheprovider
```

**Observed: 14 failed, 3 passed.** Complete output is in Appendix A; each substantive failing assertion and source traceback is retained. Tokens appearing there are synthetic test strings.

Fixed, from `fixed/cmapi`:

```sh
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/test_codex_git_review.py -q -p no:cacheprovider
```

```text
.................                                                        [100%]
17 passed in 9.17s
```

Final lifecycle plus regression check, from fixed/cmapi:

```sh
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/core/test_lifecycle_expiration.py tests/test_codex_git_review.py -q -p no:cacheprovider
```

```text
.........................................                                [100%]
41 passed in 13.03s
```

Existing offline tests, from fixed/cmapi (exact selection):

```sh
CMAPI_MIGRATE_WAIT_SECONDS=0 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_git_layer.py tests/service/test_github_statuses.py tests/service/test_review_288_f4.py -k 'not second_request and not 7_2_a and not 7_2_c and not 7_2_d and not 7_2_e and not 7_2_f and not 7_2_g and not 7_2_h and not 7_2_i and not 7_2_j_merge and not 7_2_k and not 7_2_l and not 7_2_m and not 7_2_n and not 7_2_o and not 7_5_e and not 7_6 and not test_ssh_with and not test_ssh_to and not 7_3_c_a_refusal' -q -p no:cacheprovider
```

```text
...............................................................          [100%]
=============================== warnings summary ===============================
../../../ob1-run/venv/lib/python3.12/site-packages/starlette/testclient.py:40
  /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/starlette/testclient.py:40: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = typing.Callable[[], typing.ContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
63 passed, 34 deselected, 1 warning in 46.17s
```

Native exit-code measurement, in a throwaway bare repository (no remote):

```text
git version 2.55.0
git merge-tree --write-tree x y
exit: 1
stdout: ''
stderr: 'merge-tree: x - not something we can merge\n'
```

## Blocked checks and coordinator handoff

The full selected service invocation, on main, was:

```sh
CMAPI_MIGRATE_WAIT_SECONDS=0 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_git_layer.py tests/service/test_github_statuses.py tests/service/test_review_288_f4.py -q -p no:cacheprovider
```

Observed on main: **3 failed, 63 passed, 31 errors**. PostgreSQL setup reports `connection to server at 127.0.0.1, port 55432 failed: Operation not permitted`. The two actual SSH tests fail binding 127.0.0.1 with PermissionError. The third failure is the existing refusal-log test: it searches stdout for JSON but standalone execution has the default plain structlog renderer (StopIteration). It fails on both main and fixed and is not evidence of a new Git defect.

An intermediate fixed full invocation produced **4 failed, 62 passed, 31 errors**: the same three failures plus the API-no-workspace regex expecting an unredacted one-letter fixture token. That test expectation was corrected to use redact(); the final selected offline invocation above passes all 63 runnable cases. An earlier fixed run exposed that redacting before Git stderr classification damaged absent-ref/lease handling for short credentials; the final patch classifies raw text first. Intermediate failing runs are not presented as final validation.

The exact main tests blocked or failed are listed below. In particular the coordinator must rerun migration/index enforcement, two-worker leases, cancellation races, crash-after-push/PR/apply/merge, reconcile/orphan recovery, live SSH pinning, and HTTPS credential transport tests. `test_review_288_f1.py`, `_f2.py`, `_f3.py`, `_f5.py`, `_f6.py`, `_f7.py` and `test_review_e_recovery.py` also require PostgreSQL for their world/layer fixtures; they were source-inspected, not certified by an execution here. `_f4.py` ran in the offline selection. No local-socket PostgreSQL alternative was attempted or permissions changed.

```text
FAILED tests/service/test_git_layer.py::test_7_3_c_a_refusal_logs_status_and_message_and_never_the_token
FAILED tests/service/test_git_layer.py::test_ssh_with_the_bots_key_and_a_pinned_host_key_pushes_the_request_branch
FAILED tests/service/test_git_layer.py::test_ssh_to_a_host_whose_key_is_not_pinned_is_refused
ERROR tests/service/test_git_layer.py::test_7_1_c_a_second_request_is_409_while_the_first_is_applied_or_merge_failed[applied]
ERROR tests/service/test_git_layer.py::test_7_1_c_a_second_request_is_409_while_the_first_is_applied_or_merge_failed[merge_failed]
ERROR tests/service/test_git_layer.py::test_7_2_a_b_apply_mode_applies_from_the_branch_before_the_merge
ERROR tests/service/test_git_layer.py::test_7_2_a_change_and_delete_in_apply_mode_and_the_delete_merges_first
ERROR tests/service/test_git_layer.py::test_7_2_a_argocd_mode_merges_first_then_waits_for_the_sync
ERROR tests/service/test_git_layer.py::test_7_2_c_f1_a_merge_that_keeps_failing_after_the_apply_holds_the_lock_and_retry_reaches_synced
ERROR tests/service/test_git_layer.py::test_7_2_d_an_unmanaged_namespace_fails_before_any_write_and_main_is_untouched
ERROR tests/service/test_git_layer.py::test_7_2_e_an_apply_that_fails_after_it_started_is_sync_failed_and_retry_reaches_synced
ERROR tests/service/test_git_layer.py::test_7_2_f_a_crash_right_after_each_effect_ends_with_one_commit_one_pr_one_merge[ws-push_branch]
ERROR tests/service/test_git_layer.py::test_7_2_f_a_crash_right_after_each_effect_ends_with_one_commit_one_pr_one_merge[gh-open_pr]
ERROR tests/service/test_git_layer.py::test_7_2_f_a_crash_right_after_each_effect_ends_with_one_commit_one_pr_one_merge[gh-merge]
ERROR tests/service/test_git_layer.py::test_7_2_f_a_crash_after_apply_started_applies_again_and_never_fails
ERROR tests/service/test_git_layer.py::test_7_2_f_the_host_merged_and_the_answer_was_lost_the_merge_is_adopted
ERROR tests/service/test_git_layer.py::test_7_2_g_a_branch_pushed_by_an_attempt_is_adopted_from_a_new_workdir_with_no_push
ERROR tests/service/test_git_layer.py::test_7_2_g_this_requests_stale_branch_is_replaced_with_a_lease_and_a_foreign_one_is_refused
ERROR tests/service/test_git_layer.py::test_7_2_g_a_ref_that_moves_between_the_read_and_the_push_is_a_rejected_lease
ERROR tests/service/test_git_layer.py::test_7_2_h_the_commit_is_reproducible_and_its_trailers_parse
ERROR tests/service/test_git_layer.py::test_7_2_i_a_conflicting_main_before_the_apply_is_superseded_with_its_paths_and_nothing_applied
ERROR tests/service/test_git_layer.py::test_7_2_i_a_conflict_after_the_apply_is_merge_failed_never_superseded
ERROR tests/service/test_git_layer.py::test_7_2_j_merge_tree_that_cannot_run_is_retried_and_nothing_is_applied_or_merged
ERROR tests/service/test_git_layer.py::test_7_2_k_a_head_moved_before_the_apply_fails_and_after_it_is_merge_failed
ERROR tests/service/test_git_layer.py::test_7_2_l_a_person_merges_the_pr_while_pr_open_and_watch_sync_applies_from_main
ERROR tests/service/test_git_layer.py::test_7_2_m_a_person_closes_the_pr_after_the_apply_and_a_new_pr_opens_from_the_same_branch
ERROR tests/service/test_git_layer.py::test_7_2_n_cancel_in_approved_and_pr_open_closes_and_deletes_and_after_an_apply_is_409
ERROR tests/service/test_git_layer.py::test_7_2_n_cancel_racing_the_apply_waits_for_its_marker_and_is_refused
ERROR tests/service/test_git_layer.py::test_7_2_o_retry_picks_the_job_of_each_state
ERROR tests/service/test_git_layer.py::test_7_5_e_the_reconciler_closes_and_deletes_orphans_and_leaves_hands_off_states
ERROR tests/service/test_git_layer.py::test_7_5_e_a_young_branch_is_left_alone
ERROR tests/service/test_git_layer.py::test_7_6_a_d_one_git_op_per_operation_with_the_fields_and_counters_moving_by_one
ERROR tests/service/test_git_layer.py::test_7_6_c_the_token_is_in_no_argv_environment_file_or_log
ERROR tests/service/test_git_layer.py::test_7_6_c_https_refuses_a_server_the_bundle_does_not_trust
```

Remaining boundaries: GitHub head pinning does not freeze main between merge_check and the host merge. A changed result must be detected afterward. No statement in this review proves live host API semantics/permissions beyond the supplied adapters and MockTransport contracts. The fsGroup fallback, secret rotation during a running Git subprocess, simultaneous independent comment writers, and every possible DB-loss interleaving remain unverified; these are limitations/hypotheses, not additional reproduced findings. In particular, the mount-reading HTTPS helper and startup-only token registration (`transport.py:127`, `workspace.py:101`) deserve a token-rotation stderr test before claiming universal G6 coverage.

Apply the review artifact only to a separate copy for coordinator validation:

```sh
cd main
patch --dry-run -p1 -i ../codex-fixes.patch
# After review, in a disposable copy: patch -p1 -i /absolute/path/codex-fixes.patch
```

Patch validation against unchanged main completed with exit 0:

```text
patching file 'cmapi/src/cmapi/core/git/base.py'
patching file 'cmapi/src/cmapi/core/git/gitea.py'
patching file 'cmapi/src/cmapi/core/git/github.py'
patching file 'cmapi/src/cmapi/core/git/oplog.py'
patching file 'cmapi/src/cmapi/core/git/workspace.py'
patching file 'cmapi/src/cmapi/core/lifecycle.py'
patching file 'cmapi/src/cmapi/jobs/apply.py'
patching file 'cmapi/src/cmapi/jobs/merge.py'
patching file 'cmapi/src/cmapi/jobs/pr_checks.py'
patching file 'cmapi/tests/core/test_lifecycle_expiration.py'
patching file 'cmapi/tests/service/gitserver.py'
patching file 'cmapi/tests/service/test_git_layer.py'
patching file 'cmapi/tests/test_codex_git_review.py'
```

## Appendix A — complete baseline regression output

```text
FFFFFFF.FFFFF..FF                                                        [100%]
=================================== FAILURES ===================================
__________________ test_nested_short_and_overlapping_secrets ___________________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x106106c00>

    def test_nested_short_and_overlapping_secrets(monkeypatch):
        import cmapi.core.git.oplog as op
        monkeypatch.setattr(op, '_SECRETS', set())
        for value in ('tiny', 'abcdefgh', 'abcdefgh-SUFFIX'):
            register_secret(value)
>       assert redact({'nested': ['tiny', {'x': 'abcdefgh-SUFFIX'}]}) == {'nested': ['***', {'x': '***'}]}
E       AssertionError: assert {'nested': ['...fgh-SUFFIX'}]} == {'nested': ['...{'x': '***'}]}
E         
E         Differing items:
E         {'nested': ['tiny', {'x': 'abcdefgh-SUFFIX'}]} != {'nested': ['***', {'x': '***'}]}
E         Use -v to get more diff

tests/test_codex_git_review.py:27: AssertionError
_____________ test_host_error_never_contains_registered_token[403] _____________

code = 403

    @pytest.mark.parametrize('code', [403, 502])
    def test_host_error_never_contains_registered_token(code):
        token = 'codex-echo-token-0123456789'
        provider = GitHubProvider('https://offline.invalid', 'o/r', token)
        provider._client.close()
        provider._client = httpx.Client(base_url='https://offline.invalid', transport=httpx.MockTransport(
            lambda request: httpx.Response(code, json={'message': 'echo ' + token})))
        try:
            with pytest.raises(GitUnavailable) as caught:
                provider.pr_status(PrRef(1, '', 'cmapi/CRC/r1', HEAD))
>           assert token not in str(caught.value)
E           assert 'codex-echo-...n-0123456789' not in 'PR 1: 403 {...0123456789"}'
E             
E             'codex-echo-token-0123456789' is contained here:
E               PR 1: 403 {"message":"echo codex-echo-token-0123456789"}

tests/test_codex_git_review.py:40: AssertionError
----------------------------- Captured stdout call -----------------------------
2026-11-18 22:59:07 [warning  ] git_op                         attempt=None branch=None cluster=None duration_ms=1.1 host_request_id=None http_status=403 job_id=None job_kind=None lease_generation=None message='{"message":"echo ***"}' method=GET namespace=None op=pr_state outcome=refused path=/repos/o/r/pulls/1 platform=github pr_number=None request_id=None worker=None
_____________ test_host_error_never_contains_registered_token[502] _____________

code = 502

    @pytest.mark.parametrize('code', [403, 502])
    def test_host_error_never_contains_registered_token(code):
        token = 'codex-echo-token-0123456789'
        provider = GitHubProvider('https://offline.invalid', 'o/r', token)
        provider._client.close()
        provider._client = httpx.Client(base_url='https://offline.invalid', transport=httpx.MockTransport(
            lambda request: httpx.Response(code, json={'message': 'echo ' + token})))
        try:
            with pytest.raises(GitUnavailable) as caught:
                provider.pr_status(PrRef(1, '', 'cmapi/CRC/r1', HEAD))
>           assert token not in str(caught.value)
E           assert 'codex-echo-...n-0123456789' not in 'pr_state: t...0123456789"}'
E             
E             'codex-echo-token-0123456789' is contained here:
E               ge":"echo codex-echo-token-0123456789"}

tests/test_codex_git_review.py:40: AssertionError
----------------------------- Captured stdout call -----------------------------
2026-11-18 22:59:07 [warning  ] git_op                         attempt=None branch=None cluster=None duration_ms=0.7 error='GitUnavailable: pr_state: the Git host answered 502: {"message":"echo ***"}' host_request_id=None http_status=502 job_id=None job_kind=None lease_generation=None message='{"message":"echo ***"}' method=GET namespace=None op=pr_state outcome=retry path=/repos/o/r/pulls/1 platform=github pr_number=None request_id=None worker=None
__________ test_http_transport_error_never_contains_registered_token ___________

    def test_http_transport_error_never_contains_registered_token():
        token = 'codex-transport-token-0123456789'
        provider = GitHubProvider('https://offline.invalid', 'o/r', token)
        provider._client.close()
        def fail(request):
            raise httpx.ConnectError('echo ' + token)
        provider._client = httpx.Client(base_url='https://offline.invalid', transport=httpx.MockTransport(fail))
        try:
            with pytest.raises(GitUnavailable) as caught:
                provider.pr_status(PrRef(1, '', 'cmapi/CRC/r1', HEAD))
>           assert token not in str(caught.value)
E           AssertionError: assert 'codex-trans...n-0123456789' not in 'pr_state: C...n-0123456789'
E             
E             'codex-transport-token-0123456789' is contained here:
E               pr_state: ConnectError: echo codex-transport-token-0123456789

tests/test_codex_git_review.py:56: AssertionError
----------------------------- Captured stdout call -----------------------------
2026-11-18 22:59:07 [warning  ] git_op                         attempt=None branch=None cluster=None duration_ms=0.5 error='GitUnavailable: pr_state: ConnectError: echo ***' job_id=None job_kind=None lease_generation=None method=GET namespace=None op=pr_state outcome=retry path=/repos/o/r/pulls/1 platform=github pr_number=None request_id=None worker=None
__________ test_repository_symlink_cannot_overwrite_outside_worktree ___________

tmp_path = PosixPath('/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_repository_symlink_cannot0')

    def test_repository_symlink_cannot_overwrite_outside_worktree(tmp_path):
        bare = bare_repo(tmp_path)
        outside = tmp_path / 'outside.yaml'
        outside.write_text('must survive\n')
        work = tmp_path / 'person'
        git('clone', '--quiet', str(bare), str(work), cwd=tmp_path, home=tmp_path)
        (work / FOLDER).mkdir(parents=True)
        (work / REL).symlink_to(outside)
        git('add', '--all', cwd=work, home=tmp_path)
        git('commit', '--quiet', '-m', 'symlink manifest', cwd=work, home=tmp_path)
        git('push', '--quiet', 'origin', 'main', cwd=work, home=tmp_path)
        ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / 'worker')
        try:
            with pytest.raises(GitFailed):
                ws.push_branch(req())
>           assert outside.read_text() == 'must survive\n'
E           AssertionError: assert 'kind: Namespace\n' == 'must survive\n'
E             
E             - must survive
E             + kind: Namespace

tests/test_codex_git_review.py:83: AssertionError
----------------------------- Captured stdout call -----------------------------
2026-11-18 22:59:09 [info     ] git_layer                      author='cmapi-git-bot <cmapi-git-bot@noreply.invalid>' ssh_key_fingerprint=None transport=file url=file:///private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_repository_symlink_cannot0/cluster-configs.git workdir=/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_repository_symlink_cannot0/worker
2026-11-18 22:59:10 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=131.4 job_id=None job_kind=None lease_generation=None main_sha=b24bf563f47f4b77e1d33cfa246934dd4b4673d5 namespace=None op=fetch outcome=ok platform=None pr_number=None ref=main refspec=+refs/heads/main:refs/remotes/origin/main request_id=None worker=None
2026-11-18 22:59:10 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=404.5 job_id=None job_kind=None lease_generation=None namespace=None op=clone outcome=ok platform=None pr_number=None refspec=+refs/heads/main:refs/remotes/origin/main request_id=None url=file:///private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_repository_symlink_cannot0/cluster-configs.git worker=None
2026-11-18 22:59:10 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=80.5 job_id=None job_kind=None lease_generation=None main_sha=b24bf563f47f4b77e1d33cfa246934dd4b4673d5 namespace=None op=fetch outcome=ok platform=None pr_number=None ref=main refspec=+refs/heads/main:refs/remotes/origin/main request_id=None worker=None
2026-11-18 22:59:10 [info     ] git_op                         absent=True attempt=None branch=None cluster=None duration_ms=97.3 job_id=None job_kind=None lease_generation=None namespace=None op=fetch outcome=ok platform=None pr_number=None ref=cmapi/CRC/req-1 refspec=+refs/heads/cmapi/CRC/req-1:refs/cmapi-fetched/CRC/req-1 request_id=None worker=None
2026-11-18 22:59:10 [info     ] git_op                         action=add attempt=None base_sha=b24bf563f47f4b77e1d33cfa246934dd4b4673d5 branch=None cluster=None duration_ms=275.4 job_id=None job_kind=None lease_generation=None namespace=None op=worktree outcome=ok path=/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_repository_symlink_cannot0/worker/CRC/req-1 platform=None pr_number=None request_id=None worker=None
2026-11-18 22:59:10 [warning  ] git_op                         attempt=None base_sha=b24bf563f47f4b77e1d33cfa246934dd4b4673d5 branch=None cluster=None duration_ms=65.6 error='GitFailed: the plan changes nothing on b24bf563: nothing to commit' exit_code=None job_id=None job_kind=None lease_generation=None namespace=None op=commit outcome=error plan_hash=hash platform=None pr_number=None request_id=None stderr= worker=None
_______________ test_workspace_is_private_under_permissive_umask _______________

tmp_path = PosixPath('/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_workspace_is_private_unde0')

    def test_workspace_is_private_under_permissive_umask(tmp_path):
        bare = bare_repo(tmp_path)
        old = os.umask(0o022)
        ws = None
        try:
            ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / 'worker')
            ws.push_branch(req())
>           assert stat.S_IMODE(ws.root.stat().st_mode) == 0o700
E           AssertionError: assert 493 == 448
E            +  where 493 = <built-in function S_IMODE>(16877)
E            +    where <built-in function S_IMODE> = stat.S_IMODE
E            +    and   16877 = os.stat_result(st_mode=16877, st_ino=225897486, st_dev=16777220, st_nlink=6, st_uid=501, st_gid=20, st_size=192, st_atime=1795064351, st_mtime=1795064351, st_ctime=1795064351).st_mode
E            +      where os.stat_result(st_mode=16877, st_ino=225897486, st_dev=16777220, st_nlink=6, st_uid=501, st_gid=20, st_size=192, st_atime=1795064351, st_mtime=1795064351, st_ctime=1795064351) = stat()
E            +        where stat = PosixPath('/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_workspace_is_private_unde0/worker').stat
E            +          where PosixPath('/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_workspace_is_private_unde0/worker') = <cmapi.core.git.workspace.GitWorkspace object at 0x10777b470>.root

tests/test_codex_git_review.py:95: AssertionError
----------------------------- Captured stdout call -----------------------------
2026-11-18 22:59:11 [info     ] git_layer                      author='cmapi-git-bot <cmapi-git-bot@noreply.invalid>' ssh_key_fingerprint=None transport=file url=file:///private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_workspace_is_private_unde0/cluster-configs.git workdir=/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_workspace_is_private_unde0/worker
2026-11-18 22:59:11 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=130.7 job_id=None job_kind=None lease_generation=None main_sha=de022b8588191e1b540df8225d60e1818d850444 namespace=None op=fetch outcome=ok platform=None pr_number=None ref=main refspec=+refs/heads/main:refs/remotes/origin/main request_id=None worker=None
2026-11-18 22:59:11 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=349.2 job_id=None job_kind=None lease_generation=None namespace=None op=clone outcome=ok platform=None pr_number=None refspec=+refs/heads/main:refs/remotes/origin/main request_id=None url=file:///private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_workspace_is_private_unde0/cluster-configs.git worker=None
2026-11-18 22:59:11 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=84.2 job_id=None job_kind=None lease_generation=None main_sha=de022b8588191e1b540df8225d60e1818d850444 namespace=None op=fetch outcome=ok platform=None pr_number=None ref=main refspec=+refs/heads/main:refs/remotes/origin/main request_id=None worker=None
2026-11-18 22:59:11 [info     ] git_op                         absent=True attempt=None branch=None cluster=None duration_ms=73.4 job_id=None job_kind=None lease_generation=None namespace=None op=fetch outcome=ok platform=None pr_number=None ref=cmapi/CRC/req-1 refspec=+refs/heads/cmapi/CRC/req-1:refs/cmapi-fetched/CRC/req-1 request_id=None worker=None
2026-11-18 22:59:11 [info     ] git_op                         action=add attempt=None base_sha=de022b8588191e1b540df8225d60e1818d850444 branch=None cluster=None duration_ms=244.1 job_id=None job_kind=None lease_generation=None namespace=None op=worktree outcome=ok path=/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_workspace_is_private_unde0/worker/CRC/req-1 platform=None pr_number=None request_id=None worker=None
2026-11-18 22:59:12 [info     ] git_op                         adopted=False attempt=None base_sha=de022b8588191e1b540df8225d60e1818d850444 branch=None cluster=None duration_ms=132.6 files_changed=1 head_sha=fe98adb622fc9122380ae57a31be559868b2efc7 job_id=None job_kind=None lease_generation=None namespace=None op=commit outcome=ok plan_hash=hash platform=None pr_number=None request_id=None worker=None
2026-11-18 22:59:12 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=187.5 forced=False head_sha=fe98adb622fc9122380ae57a31be559868b2efc7 job_id=None job_kind=None lease_generation=None lease_sha=None namespace=None op=push outcome=ok platform=None pr_number=None request_id=None result=created worker=None
_____________ test_wrong_merge_tree_never_queues_delivery[pr_open] _____________

status = 'pr_open'

    @pytest.mark.parametrize('status', ['pr_open', 'applied'])
    def test_wrong_merge_tree_never_queues_delivery(status):
        module = importlib.import_module('cmapi.jobs.merge')
        r = row()
        r.status = status
        repo, jobs = Repo(), Jobs()
        ctx = NS(git=NS(tree_files=lambda sha, folder: {REL: 'unapproved'}, cleanup=lambda *a: None))
        module._merged(ctx, repo, jobs, r, NS(), MERGE, adopted=True)
>       assert r.status == 'sync_failed'
E       AssertionError: assert 'merged' == 'sync_failed'
E         
E         - sync_failed
E         + merged

tests/test_codex_git_review.py:142: AssertionError
_________ test_hand_merge_between_checks_and_apply_is_adopted[pr_open] _________

status = 'pr_open'

    @pytest.mark.parametrize("status", ["pr_open", "sync_failed"])
    def test_hand_merge_between_checks_and_apply_is_adopted(status):
        module = importlib.import_module('cmapi.jobs.apply')
        r = row()
        r.status = status
        repo, jobs = Repo(), Jobs()
        if status == 'sync_failed':
            repo.events = lambda rid: [NS(event='apply_started', detail={'head': HEAD})]
        ctx = NS(git=NS(pr_status=lambda pr: PrStatus('merged', {}, MERGE, HEAD),
                        branch_head=lambda branch: None, close=lambda *a: None, tree_files=lambda sha, folder: {REL: 'approved'},
                        cleanup=lambda *a: None))
        module._apply(ctx, repo, jobs, r, NS(payload={'head': HEAD}))
>       assert r.status == 'merged'
E       AssertionError: assert 'failed' == 'merged'
E         
E         - merged
E         + failed

tests/test_codex_git_review.py:158: AssertionError
_______ test_hand_merge_between_checks_and_apply_is_adopted[sync_failed] _______

status = 'sync_failed'

    @pytest.mark.parametrize("status", ["pr_open", "sync_failed"])
    def test_hand_merge_between_checks_and_apply_is_adopted(status):
        module = importlib.import_module('cmapi.jobs.apply')
        r = row()
        r.status = status
        repo, jobs = Repo(), Jobs()
        if status == 'sync_failed':
            repo.events = lambda rid: [NS(event='apply_started', detail={'head': HEAD})]
        ctx = NS(git=NS(pr_status=lambda pr: PrStatus('merged', {}, MERGE, HEAD),
                        branch_head=lambda branch: None, close=lambda *a: None, tree_files=lambda sha, folder: {REL: 'approved'},
                        cleanup=lambda *a: None))
        module._apply(ctx, repo, jobs, r, NS(payload={'head': HEAD}))
>       assert r.status == 'merged'
E       AssertionError: assert 'sync_failed' == 'merged'
E         
E         - merged
E         + sync_failed

tests/test_codex_git_review.py:158: AssertionError
____________ test_hand_merge_during_pr_checks_uses_postmerge_check _____________

    def test_hand_merge_during_pr_checks_uses_postmerge_check():
        module = importlib.import_module('cmapi.jobs.pr_checks')
        r = row()
        repo, jobs = Repo(), Jobs()
        ctx = NS(git=NS(pr_status=lambda pr: PrStatus('merged', {}, MERGE, HEAD),
                        tree_files=lambda sha, folder: {REL: 'unapproved'}, cleanup=lambda *a: None))
        module._pr_checks(ctx, repo, jobs, r, NS())
>       assert r.status == 'sync_failed'
E       AssertionError: assert 'merged' == 'sync_failed'
E         
E         - sync_failed
E         + merged

tests/test_codex_git_review.py:170: AssertionError
____ test_gitea_never_deletes_or_adopts_an_unverified_existing_branch[push] ____

operation = 'push'

    @pytest.mark.parametrize('operation', ['push', 'delete'])
    def test_gitea_never_deletes_or_adopts_an_unverified_existing_branch(operation):
        from cmapi.core.git.gitea import GiteaProvider
        from cmapi.core.git.workspace import BranchRefused
        calls = []
        def host(request):
            calls.append(request.method)
            if request.method == 'DELETE':
                return httpx.Response(204)
            if '/branches/' in request.url.path:
                return httpx.Response(200, json={'commit': {'id': HEAD}})
            if request.url.path.endswith('/pulls'):
                return httpx.Response(200, json=[{'number': 1, 'head': {'ref': 'cmapi/CRC/req-1', 'sha': HEAD}}])
            raise AssertionError(request.url)
        provider = GiteaProvider('https://offline.invalid', 'o/r', 'test-token')
        provider._client.close()
        provider._client = httpx.Client(base_url='https://offline.invalid', transport=httpx.MockTransport(host))
        try:
            if operation == 'push':
>               with pytest.raises(BranchRefused):
E               Failed: DID NOT RAISE <class 'cmapi.core.git.workspace.BranchRefused'>

tests/test_codex_git_review.py:193: Failed
----------------------------- Captured stdout call -----------------------------
2026-11-18 22:59:13 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=0.7 host_request_id=None http_status=200 job_id=None job_kind=None lease_generation=None method=GET namespace=None op=branch_head outcome=ok path=/repos/o/r/branches/main platform=gitea pr_number=None request_id=None worker=None
2026-11-18 22:59:14 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=0.6 host_request_id=None http_status=200 job_id=None job_kind=None lease_generation=None method=GET namespace=None op=branch_head outcome=ok path=/repos/o/r/branches/cmapi/CRC/req-1 platform=gitea pr_number=None request_id=None worker=None
2026-11-18 22:59:14 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=0.6 host_request_id=None http_status=200 job_id=None job_kind=None lease_generation=None method=GET namespace=None op=find_pr outcome=ok path=/repos/o/r/pulls platform=gitea pr_number=None request_id=None worker=None
___ test_gitea_never_deletes_or_adopts_an_unverified_existing_branch[delete] ___

operation = 'delete'

    @pytest.mark.parametrize('operation', ['push', 'delete'])
    def test_gitea_never_deletes_or_adopts_an_unverified_existing_branch(operation):
        from cmapi.core.git.gitea import GiteaProvider
        from cmapi.core.git.workspace import BranchRefused
        calls = []
        def host(request):
            calls.append(request.method)
            if request.method == 'DELETE':
                return httpx.Response(204)
            if '/branches/' in request.url.path:
                return httpx.Response(200, json={'commit': {'id': HEAD}})
            if request.url.path.endswith('/pulls'):
                return httpx.Response(200, json=[{'number': 1, 'head': {'ref': 'cmapi/CRC/req-1', 'sha': HEAD}}])
            raise AssertionError(request.url)
        provider = GiteaProvider('https://offline.invalid', 'o/r', 'test-token')
        provider._client.close()
        provider._client = httpx.Client(base_url='https://offline.invalid', transport=httpx.MockTransport(host))
        try:
            if operation == 'push':
                with pytest.raises(BranchRefused):
                    provider.push_request_branch(req())
            else:
>               with pytest.raises(GitUnavailable, match='conditionally delete'):
E               Failed: DID NOT RAISE <class 'cmapi.core.git.base.GitUnavailable'>

tests/test_codex_git_review.py:196: Failed
----------------------------- Captured stdout call -----------------------------
2026-11-18 22:59:14 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=0.6 host_request_id=None http_status=200 job_id=None job_kind=None lease_generation=None method=GET namespace=None op=branch_head outcome=ok path=/repos/o/r/branches/cmapi/CRC/req-1 platform=gitea pr_number=None request_id=None worker=None
2026-11-18 22:59:14 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=0.5 host_request_id=None http_status=204 job_id=None job_kind=None lease_generation=None method=DELETE namespace=None op=delete_branch outcome=ok path=/repos/o/r/branches/cmapi/CRC/req-1 platform=gitea pr_number=None request_id=None worker=None
________________ test_lost_comment_response_is_adopted_on_retry ________________

    def test_lost_comment_response_is_adopted_on_retry():
        comments = []
        def host(request):
            if request.method == 'GET':
                return httpx.Response(200, json=[{'body': body} for body in comments])
            assert request.method == 'POST'
            import json
            comments.append(json.loads(request.content)['body'])
            return httpx.Response(502 if len(comments) == 1 else 201)
        provider = GitHubProvider('https://offline.invalid', 'o/r', 'test-token')
        provider._client.close()
        provider._client = httpx.Client(base_url='https://offline.invalid', transport=httpx.MockTransport(host))
        pr = PrRef(1, '', 'cmapi/CRC/req-1', HEAD)
        try:
            with pytest.raises(GitUnavailable):
                provider.comment(pr, 'cmapi: merge failed; retry required')
            provider.comment(pr, 'cmapi: merge failed; retry required')
>           assert comments == ['cmapi: merge failed; retry required']
E           AssertionError: assert ['cmapi: merg...try required'] == ['cmapi: merg...try required']
E             
E             Left contains one more item: 'cmapi: merge failed; retry required'
E             Use -v to get more diff

tests/test_codex_git_review.py:262: AssertionError
----------------------------- Captured stdout call -----------------------------
2026-11-18 22:59:17 [warning  ] git_op                         attempt=None branch=None cluster=None duration_ms=1.1 error='GitUnavailable: pr_comment: the Git host answered 502: ' host_request_id=None http_status=502 job_id=None job_kind=None lease_generation=None message= method=POST namespace=None op=pr_comment outcome=retry path=/repos/o/r/issues/1/comments platform=github pr_number=None request_id=None worker=None
2026-11-18 22:59:17 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=0.5 host_request_id=None http_status=201 job_id=None job_kind=None lease_generation=None method=POST namespace=None op=pr_comment outcome=ok path=/repos/o/r/issues/1/comments platform=github pr_number=None request_id=None worker=None
_______________ test_leading_dash_folder_is_a_path_not_an_option _______________

tmp_path = PosixPath('/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_leading_dash_folder_is_a_0')

    def test_leading_dash_folder_is_a_path_not_an_option(tmp_path):
        from dataclasses import replace
        bare = bare_repo(tmp_path)
        ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / 'worker')
        try:
            request = replace(req(), folder='-folder', files={'-folder/namespace.yaml': 'kind: Namespace\n'})
>           pushed = ws.push_branch(request)

tests/test_codex_git_review.py:273: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/cmapi/core/git/workspace.py:461: in push_branch
    head = self._build(req, folder, main)
src/cmapi/core/git/workspace.py:390: in _build
    self._run("sparse-checkout", "set", "--cone", folder, cwd=path)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <cmapi.core.git.workspace.GitWorkspace object at 0x10906c0b0>
cwd = PosixPath('/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_leading_dash_folder_is_a_0/worker/CRC/req-1')
input = None, ok = (0,), git_dir = False

    def _run(self, *args: str, cwd: Path | None = None, input: bytes | None = None, ok: tuple[int, ...] = (0,),
             git_dir: bool = False, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
        argv = [self._binary, *((f"--git-dir={self.mirror}",) if git_dir else ()), *args]
        try:
            p = subprocess.run(argv, input=input, capture_output=True, env=dict(env or self._env), cwd=cwd or self._home,
                               timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise GitFailed(f"git {args[0]} did not finish in {self.timeout:.0f} s") from exc
        except OSError as exc:
            raise GitFailed(f"git {args[0]}: {type(exc).__name__}: {exc}") from exc
        if p.returncode not in ok:
            err = redact(p.stderr.decode(errors="replace").strip())[-2000:]
>           raise GitFailed(f"git {args[0]} exited {p.returncode}: {err[-400:]}", p.returncode, err)
E           cmapi.core.git.workspace.GitFailed: git sparse-checkout exited 129: ch `f'
E           usage: git sparse-checkout set [--[no-]cone] [--[no-]sparse-index] [--skip-checks] (--stdin | <patterns>)
E           
E               --[no-]cone           initialize the sparse-checkout in cone mode
E               --[no-]sparse-index   toggle the use of a sparse index
E               --skip-checks         skip some sanity checks on the given paths that might give false positives
E               --stdin               read patterns from standard in

src/cmapi/core/git/workspace.py:142: GitFailed
----------------------------- Captured stdout call -----------------------------
2026-11-18 22:59:18 [info     ] git_layer                      author='cmapi-git-bot <cmapi-git-bot@noreply.invalid>' ssh_key_fingerprint=None transport=file url=file:///private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_leading_dash_folder_is_a_0/cluster-configs.git workdir=/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_leading_dash_folder_is_a_0/worker
2026-11-18 22:59:18 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=147.7 job_id=None job_kind=None lease_generation=None main_sha=7b7acd7c18d44ee6f3d330e0539489e936a944e9 namespace=None op=fetch outcome=ok platform=None pr_number=None ref=main refspec=+refs/heads/main:refs/remotes/origin/main request_id=None worker=None
2026-11-18 22:59:18 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=399.4 job_id=None job_kind=None lease_generation=None namespace=None op=clone outcome=ok platform=None pr_number=None refspec=+refs/heads/main:refs/remotes/origin/main request_id=None url=file:///private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_leading_dash_folder_is_a_0/cluster-configs.git worker=None
2026-11-18 22:59:18 [info     ] git_op                         attempt=None branch=None cluster=None duration_ms=89.6 job_id=None job_kind=None lease_generation=None main_sha=7b7acd7c18d44ee6f3d330e0539489e936a944e9 namespace=None op=fetch outcome=ok platform=None pr_number=None ref=main refspec=+refs/heads/main:refs/remotes/origin/main request_id=None worker=None
2026-11-18 22:59:19 [info     ] git_op                         absent=True attempt=None branch=None cluster=None duration_ms=88.1 job_id=None job_kind=None lease_generation=None namespace=None op=fetch outcome=ok platform=None pr_number=None ref=cmapi/CRC/req-1 refspec=+refs/heads/cmapi/CRC/req-1:refs/cmapi-fetched/CRC/req-1 request_id=None worker=None
2026-11-18 22:59:19 [warning  ] git_op                         action=add attempt=None base_sha=7b7acd7c18d44ee6f3d330e0539489e936a944e9 branch=None cluster=None duration_ms=143.5 error="GitFailed: git sparse-checkout exited 129: ch `f'\nusage: git sparse-checkout set [--[no-]cone] [--[no-]sparse-index] [--skip-checks] (--stdin | <patterns>)\n\n    --[no-]cone           initialize the sparse-checkout in cone mode\n    --[no-]sparse-index   toggle the use of a sparse index\n    --skip-checks         skip some sanity checks on the given paths that might give false positives\n    --stdin               read patterns from standard in" exit_code=129 job_id=None job_kind=None lease_generation=None namespace=None op=worktree outcome=error path=/private/var/folders/fg/jr6hdz6962516sgpfclbrvqw0000gn/T/pytest-of-olasumbo/pytest-1088/test_leading_dash_folder_is_a_0/worker/CRC/req-1 platform=None pr_number=None request_id=None stderr="error: unknown switch `f'\nusage: git sparse-checkout set [--[no-]cone] [--[no-]sparse-index] [--skip-checks] (--stdin | <patterns>)\n\n    --[no-]cone           initialize the sparse-checkout in cone mode\n    --[no-]sparse-index   toggle the use of a sparse index\n    --skip-checks         skip some sanity checks on the given paths that might give false positives\n    --stdin               read patterns from standard in" worker=None
=========================== short test summary info ============================
FAILED tests/test_codex_git_review.py::test_nested_short_and_overlapping_secrets
FAILED tests/test_codex_git_review.py::test_host_error_never_contains_registered_token[403]
FAILED tests/test_codex_git_review.py::test_host_error_never_contains_registered_token[502]
FAILED tests/test_codex_git_review.py::test_http_transport_error_never_contains_registered_token
FAILED tests/test_codex_git_review.py::test_repository_symlink_cannot_overwrite_outside_worktree
FAILED tests/test_codex_git_review.py::test_workspace_is_private_under_permissive_umask
FAILED tests/test_codex_git_review.py::test_wrong_merge_tree_never_queues_delivery[pr_open]
FAILED tests/test_codex_git_review.py::test_hand_merge_between_checks_and_apply_is_adopted[pr_open]
FAILED tests/test_codex_git_review.py::test_hand_merge_between_checks_and_apply_is_adopted[sync_failed]
FAILED tests/test_codex_git_review.py::test_hand_merge_during_pr_checks_uses_postmerge_check
FAILED tests/test_codex_git_review.py::test_gitea_never_deletes_or_adopts_an_unverified_existing_branch[push]
FAILED tests/test_codex_git_review.py::test_gitea_never_deletes_or_adopts_an_unverified_existing_branch[delete]
FAILED tests/test_codex_git_review.py::test_lost_comment_response_is_adopted_on_retry
FAILED tests/test_codex_git_review.py::test_leading_dash_folder_is_a_path_not_an_option
14 failed, 3 passed in 12.75s
```

## Appendix B — passing controls

The three cases already passing on main are the applied-state mismatch control, `test_repeated_push_dates_adoption_and_conditional_delete`, and `test_transport_discards_inherited_askpass_and_ssh_command`. The first proves main's after-apply folder guard was already present; the second observes real push argv/dates/adoption/deletion; the third checks the generated environment without opening a socket. The 14 other parameterized cases fail on main and all pass with the patch.

## Appendix C — complete -p1 fix and test code

This is byte-for-byte `codex-fixes.patch`; paths are relative to ./main. All nine findings map to the implementation and complete tests in this patch. The two existing-test updates preserve the new lifecycle behavior and required short-secret redaction; they do not turn a failing regression into a pass by weakening its assertion.

```diff
--- a/cmapi/src/cmapi/core/git/base.py
+++ b/cmapi/src/cmapi/core/git/base.py
@@ -22,7 +22,10 @@
 
 
 class GitUnavailable(RuntimeError):
-    pass
+    def __init__(self, message: str):
+        from cmapi.core.git.oplog import redact
+
+        super().__init__(redact(message))
 
 
 class IncompleteList(GitUnavailable):
@@ -35,7 +38,9 @@
 
     def __init__(self, message: str, status: int | None = None, host_message: str = ""):
         super().__init__(message)
-        self.status, self.host_message = status, host_message
+        from cmapi.core.git.oplog import redact
+
+        self.status, self.host_message = status, redact(host_message)
 
 
 class HeadMoved(PlatformRefused):
@@ -124,7 +129,7 @@
 
     def _call(self, operation: str, method: str, path: str, *, ok: tuple[int, ...] = (200, 201, 204),
               log_fields: Mapping[str, Any] | None = None, **kw: Any) -> httpx.Response:
-        from cmapi.core.git.oplog import Op
+        from cmapi.core.git.oplog import Op, redact
         from cmapi.core.observability import PLATFORM_REQUESTS
 
         with Op(operation, method=method, path=path, platform=self.name, **(log_fields or {})) as op:
@@ -133,7 +138,7 @@
             except httpx.HTTPError as exc:
                 PLATFORM_REQUESTS.labels(self.name, operation, "error").inc()
                 op.outcome = "retry"
-                raise GitUnavailable(f"{operation}: {type(exc).__name__}: {exc}") from exc
+                raise GitUnavailable(redact(f"{operation}: {type(exc).__name__}: {exc}")) from None
             PLATFORM_REQUESTS.labels(self.name, operation, f"{r.status_code // 100}xx").inc()
             op.set(http_status=r.status_code, host_request_id=r.headers.get("x-github-request-id") or r.headers.get("x-request-id"))
             if r.status_code >= 500 or r.status_code == 429:
--- a/cmapi/src/cmapi/core/git/gitea.py
+++ b/cmapi/src/cmapi/core/git/gitea.py
@@ -18,6 +18,7 @@
 from typing import Any, Mapping
 
 from cmapi.core.git.base import BranchRequest, CheckState, GitUnavailable, HostGitProvider, PushResult
+from cmapi.core.git.workspace import BranchRefused
 from cmapi.core.ports import PrRef, PrStatus
 
 
@@ -52,8 +53,7 @@
         return files, head
 
     def push_request_branch(self, req: BranchRequest) -> PushResult:
-        """Through Gitea's REST API, not the Git layer: the chart's stand-in. A branch with no open PR is one the bot left or
-        anyone may have pushed to, so it is deleted and written again from the default branch's head."""
+        """The REST stand-in creates a new branch only; an existing ref needs Git's adoption and lease protocol."""
         from cmapi.core.git.workspace import request_branch
 
         branch = request_branch(req.cluster_id, req.request_id)
@@ -61,12 +61,10 @@
         if base is None:
             raise GitUnavailable(f"branch {self.default_branch} does not exist")
         if self.branch_head(branch) is not None:
-            existing = self.find_pr(branch)
-            if existing is not None:
-                return PushResult(existing.head_sha, base, "adopted")
-            r = self._call("delete_branch", "DELETE", f"{self._repo()}/branches/{branch}", ok=(204,))
-            if r.status_code != 204:
-                raise GitUnavailable(f"delete stale branch {branch}: {r.status_code} {r.text[:200]}")
+            # REST cannot atomically replace this ref or prove the full adoption test.
+            # Refuse rather than erase a person's work or adopt unchecked content.
+            raise BranchRefused(f"the Gitea REST stand-in cannot safely adopt or replace existing branch {branch}; "
+                                "a Git transport is required")
         r = self._call("create_branch", "POST", f"{self._repo()}/branches",
                        json={"new_branch_name": branch, "old_ref_name": base}, ok=(201,))
         if r.status_code != 201:
@@ -109,14 +107,11 @@
         self._call("comment", "POST", f"{self._repo()}/issues/{pr.number}/comments", json={"body": text}, ok=(201,))
 
     def delete_branch(self, branch: str, expected: str) -> bool:
-        """Gitea's REST delete is not conditional: the head is read first, and a race in between is the stand-in's to accept."""
-        head = self.branch_head(branch)
-        if head is None:
+        """REST has no compare-and-delete: fail closed until this adapter uses the Git layer."""
+        if self.branch_head(branch) is None:
             return True
-        if head != expected:
-            return False
-        r = self._call("delete_branch", "DELETE", f"{self._repo()}/branches/{branch}", ok=(204, 404))
-        return r.status_code in (204, 404)
+        raise GitUnavailable(f"the Gitea REST stand-in cannot conditionally delete {branch}; "
+                             "a Git push with a lease is required")
 
     def list_open(self, prefix: str) -> list[PrRef]:
         r = self._call("find_pr", "GET", f"{self._repo()}/pulls", params={"state": "open", "limit": 50})
--- a/cmapi/src/cmapi/core/git/github.py
+++ b/cmapi/src/cmapi/core/git/github.py
@@ -216,6 +216,10 @@
         raise PlatformRefused(f"merge PR {pr.number}: {r.status_code} {message}", r.status_code, message)
 
     def comment(self, pr: PrRef, text: str) -> None:
+        # A lost POST response must not append the same cmapi comment on retry.
+        comments = self._pages("pr_comments", f"{self._repo()}/issues/{pr.number}/comments", None)
+        if any(c.get("body") == text for c in comments):
+            return
         r = self._call("pr_comment", "POST", f"{self._repo()}/issues/{pr.number}/comments", json={"body": text}, ok=(201,))
         if r.status_code != 201:
             raise PlatformRefused(f"comment on PR {pr.number}: {r.status_code}", r.status_code, r.text[:300])
--- a/cmapi/src/cmapi/core/git/oplog.py
+++ b/cmapi/src/cmapi/core/git/oplog.py
@@ -27,18 +27,24 @@
 
 
 def register_secret(value: str | None) -> None:
-    """A value that must never be logged. Short values are refused: redacting a three-letter word would garble every line."""
-    if value and len(value) >= 8:
+    """Register every nonempty credential, including short test or local credentials."""
+    if value:
         with _SECRETS_LOCK:
             _SECRETS.add(value)
 
 
 def redact(value: Any) -> Any:
+    if isinstance(value, dict):
+        return {redact(k): redact(v) for k, v in value.items()}
+    if isinstance(value, (list, tuple)):
+        return [redact(v) for v in value]
     if not isinstance(value, str):
         return value
-    for secret in _SECRETS:
-        value = value.replace(secret, "***")
-    return value
+    # One substitution prevents overlapping credentials leaving an unredacted suffix.
+    import re
+    with _SECRETS_LOCK:
+        secrets = sorted(_SECRETS, key=lambda s: (-len(s), s))
+    return re.sub("|".join(re.escape(s) for s in secrets), lambda _: "***", value) if secrets else value
 
 
 @contextmanager
--- a/cmapi/src/cmapi/core/git/workspace.py
+++ b/cmapi/src/cmapi/core/git/workspace.py
@@ -22,6 +22,7 @@
 from __future__ import annotations
 
 import fcntl
+import os
 import re
 import shutil
 import subprocess
@@ -99,14 +100,27 @@
                                                     ssh_dir=Path(ssh_dir) if ssh_dir else None,
                                                     known_hosts_dir=Path(known_hosts_dir) if known_hosts_dir else None)
         register_secret(self._creds.token())
+        if self._creds.key_file:
+            register_secret(self._creds.key_file.read_text().strip())
         self.author = (BOT_NAME, commit_email or BOT_EMAIL)
         self._ca = str(ca_bundle) if ca_bundle else None
         if self._ca and not Path(self._ca).is_file():
             raise GitConfigError(f"the Git CA bundle {self._ca} is not a file")
         owned = workdir is None
         self.root = Path(tempfile.mkdtemp(prefix="cmapi-git-")) if owned else Path(workdir)
-        self.root.mkdir(parents=True, exist_ok=True)
+        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
+        try:
+            self.root.chmod(0o700)
+        except PermissionError:
+            # An emptyDir may be writable through fsGroup but owned by root.
+            # Keep our private storage in a directory created by this UID.
+            self.root = self.root / f".private-{os.getuid()}"
+            if self.root.is_symlink():
+                raise GitConfigError("the private Git workdir must not be a symlink")
+            self.root.mkdir(exist_ok=True, mode=0o700)
+            self.root.chmod(0o700)
         self._lockfile = open(self.root / ".lock", "w")
+        (self.root / ".lock").chmod(0o600)
         try:
             fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
         except OSError as exc:
@@ -114,7 +128,8 @@
             raise GitConfigError(f"{self.root} is the Git workdir of another process: each process has its own") from exc
         self.mirror = self.root / REPO
         self._home = self.root / ".home"
-        self._home.mkdir(exist_ok=True)
+        self._home.mkdir(exist_ok=True, mode=0o700)
+        self._home.chmod(0o700)
         self._lock = threading.RLock()
         self._env = git_environment(self.remote, self._creds, self._home, self._ca, self.author)
         self._tracking = f"refs/remotes/origin/{default_branch}"
@@ -202,8 +217,9 @@
                 self._failed(op, exc)
                 raise
             if p.returncode != 0:
-                err = redact(p.stderr.decode(errors="replace").strip())
-                if "couldn't find remote ref" in err:
+                raw_err = p.stderr.decode(errors="replace").strip()
+                err = redact(raw_err)
+                if "couldn't find remote ref" in raw_err:
                     self._m("update-ref", "-d", target, ok=(0, 1))
                     op.set(absent=True)
                     return None
@@ -347,7 +363,8 @@
         return self.root / cluster_id / request_id
 
     def _check_files(self, req: BranchRequest) -> str:
-        folder = req.folder.strip("/")
+        check_path(req.folder)
+        folder = req.folder
         for path in req.files:
             check_path(path)
             if not path.startswith(folder + "/"):
@@ -387,7 +404,7 @@
                 path.parent.mkdir(parents=True, exist_ok=True)
                 self._m("worktree", "add", "--quiet", "--no-checkout", "-b", branch, str(path), base)
                 # Only the request's folder is checked out: a repository of thousands of namespaces costs one folder.
-                self._run("sparse-checkout", "set", "--cone", folder, cwd=path)
+                self._run("sparse-checkout", "set", "--cone", "--", folder, cwd=path)
                 self._run("checkout", "--quiet", branch, cwd=path)
             except GitFailed as exc:
                 self._failed(op, exc)
@@ -396,6 +413,10 @@
             try:
                 for rel, text in req.files.items():
                     target = path / rel
+                    # Checkout can materialize repository symlinks. Never follow one while writing or deleting.
+                    if any((path / Path(*Path(rel).parts[:i])).is_symlink()
+                           for i in range(1, len(Path(rel).parts) + 1)):
+                        raise GitFailed(f"the plan path {rel} traverses a symlink")
                     if text is None:
                         target.unlink(missing_ok=True)
                     else:
@@ -426,10 +447,11 @@
             if p.returncode == 0:
                 op.set(result=result)
                 return
-            report = redact((p.stdout + p.stderr).decode(errors="replace"))
+            raw_report = (p.stdout + p.stderr).decode(errors="replace")
+            report = redact(raw_report)
             status = next((line for line in report.splitlines() if line.startswith("!\t")), report.strip()[-400:])
             op.set(exit_code=p.returncode, stderr=status[-2000:])
-            if p.returncode == 1 and "stale info" in status:
+            if p.returncode == 1 and "stale info" in raw_report:
                 op.set(result="lease_rejected")
                 op.outcome = "retry"
                 raise BranchMoved(f"push {branch}: the lease on {(lease or 'no branch')[:8]} was refused: {status.strip()}")
@@ -536,9 +558,10 @@
                 p = self._m("push", "--porcelain", "--no-verify", f"--force-with-lease={ref}:{expected}", "origin", f":{ref}",
                             ok=(0, 1, 128))
                 if p.returncode != 0:
-                    err = redact((p.stdout + p.stderr).decode(errors="replace"))[-2000:]
+                    raw_err = (p.stdout + p.stderr).decode(errors="replace")
+                    err = redact(raw_err)[-2000:]
                     op.set(exit_code=p.returncode, stderr=err)
-                    if p.returncode == 1 and "stale info" in err:
+                    if p.returncode == 1 and "stale info" in raw_err:
                         op.outcome = "refused"
                         return False
                     raise GitFailed(f"delete {branch}: {err[-300:]}", p.returncode, err)
--- a/cmapi/src/cmapi/core/lifecycle.py
+++ b/cmapi/src/cmapi/core/lifecycle.py
@@ -77,6 +77,7 @@
     (S.APPLIED, E.MERGE_FAILED): S.MERGE_FAILED,
     (S.MERGE_FAILED, E.MERGED): S.MERGED,
     (S.MERGE_FAILED, E.RETRY): S.MERGE_FAILED,    # the merge job again, pinned to the applied head; never a rollback
+    (S.SYNC_FAILED, E.MERGED): S.MERGED,          # a hand merge adopted while retrying an unfinished apply
     (S.SYNC_FAILED, E.APPLIED): S.APPLIED,        # a :retry of an apply that had not finished (merge_sha null)
     (S.MERGED, E.SYNCED): S.SYNCED,
     (S.MERGED, E.PRUNE_PENDING): S.AWAITING_PRUNE,
--- a/cmapi/src/cmapi/jobs/apply.py
+++ b/cmapi/src/cmapi/jobs/apply.py
@@ -31,7 +31,7 @@
 from cmapi.core.observability import MERGE_CONFLICTS
 from cmapi.core.render.manifests import folder
 from cmapi.core.sync import ApplyDelivery, confirmed_by_read
-from cmapi.jobs.delivery import APPLY_STARTED, apply_started, end_pr, mark_apply_started, mode_of, planned, request_context
+from cmapi.jobs.delivery import APPLY_STARTED, apply_started, end_pr, mark_apply_started, mode_of, planned, pr_of, request_context
 
 
 def apply(ctx: AppContext, s: Session, job: JobRow) -> None:
@@ -62,6 +62,19 @@
 def _apply(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow) -> None:
     from cmapi.jobs.watch_sync import _deliverer, _direct, _managed, _NotYet, _reader_cache
 
+    # A person may merge between checks and this job, deleting the source branch.
+    # Adopt through the same post-merge verification as the merge job.
+    def adopt_merged():
+        state = ctx.git.pr_status(pr_of(row))
+        if state.state != "merged":
+            return False
+        from cmapi.jobs.merge import _merged
+
+        _merged(ctx, repo, jobs, row, job, state.merge_sha or "", adopted=True)
+        return True
+
+    if adopt_merged():
+        return
     head = (job.payload or {}).get("head") or row.pr.get("applied_head") or row.pr["head"]
     started = apply_started(repo, row) == head
     where = folder(row.cluster_id, row.namespace)
@@ -69,11 +82,15 @@
     removed = {p: row.plan["prev"][p] for p, t in row.plan["files"].items() if t is None and p in (row.plan.get("prev") or {})}
     current = ctx.git.branch_head(row.pr["branch"])
     if current != head:
+        if adopt_merged():
+            return
         return _stop(ctx, repo, jobs, row, job, f"the PR head moved from {head[:8]} to {(current or 'nothing')[:8]}", started)
     if ctx.git.tree_files(head, where) != files:
         return _stop(ctx, repo, jobs, row, job, f"the branch's folder at {head[:8]} is not the approved plan", started)
     check = ctx.git.merge_check(head, where, row.plan.get("prev") or {}, row.plan["files"])
     if not check.ok:
+        if adopt_merged():
+            return
         MERGE_CONFLICTS.labels("apply").inc()
         why = check.reason(ctx.git.default_branch)
         repo.event(row, "merge_check", "worker", why[:300], {"caller": "apply", "main": check.main_sha, "head": head,
--- a/cmapi/src/cmapi/jobs/merge.py
+++ b/cmapi/src/cmapi/jobs/merge.py
@@ -141,13 +141,12 @@
     repo.event(row, "merge_verified", "worker", f"{how} {sha[:8]}; the folder at it {'is' if on_main == planned(row) else 'is not'} the plan's",
                {"merge_sha": sha, "adopted": adopted})
     repo.move(row, E.MERGED, "cmapi-bot", f"{how} {sha[:8]}")
-    if after_apply:
-        if on_main == planned(row):
-            repo.move(row, E.SYNCED, "cmapi-deliverer", "applied and confirmed by a read before the merge")
-            approval = "auto" if (row.requirement or {}).get("auto") else "human"
-            LEAD_TIME.labels(row.plugin, row.action, approval).observe((datetime.now(timezone.utc) - row.created_at).total_seconds())
-        else:
-            repo.move(row, E.SYNC_TIMEOUT, "worker", f"the folder at the merge {sha[:8]} is not the applied plan")
+    if on_main != planned(row):
+        repo.move(row, E.SYNC_TIMEOUT, "worker", f"the folder at the merge {sha[:8]} is not the approved plan")
+    elif after_apply:
+        repo.move(row, E.SYNCED, "cmapi-deliverer", "applied and confirmed by a read before the merge")
+        approval = "auto" if (row.requirement or {}).get("auto") else "human"
+        LEAD_TIME.labels(row.plugin, row.action, approval).observe((datetime.now(timezone.utc) - row.created_at).total_seconds())
     else:
         jobs.enqueue("watch_sync", request_id=row.request_id, cluster_id=row.cluster_id)
     ctx.git.cleanup(row.cluster_id, row.request_id)
--- a/cmapi/src/cmapi/jobs/pr_checks.py
+++ b/cmapi/src/cmapi/jobs/pr_checks.py
@@ -57,13 +57,9 @@
         jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
         return
     if status.state == "merged":
-        # A person merged it before any apply: adopted. In apply mode watch_sync then applies from main (Fable 1.1).
-        row.merge_sha = status.merge_sha
-        repo.move(row, E.MERGED, "cmapi-bot", f"merged {(status.merge_sha or '')[:8]} on the host")
-        jobs.done(job)
-        jobs.enqueue("watch_sync", request_id=row.request_id, cluster_id=row.cluster_id)
-        jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
-        return
+        from cmapi.jobs.merge import _merged
+
+        return _merged(ctx, repo, jobs, row, job, status.merge_sha or "", adopted=True)
     # A context nobody has reported yet is pending: the workflow may not have started.
     ci = {c: status.checks.get(c, "pending") for c in CI_CONTEXTS} if ctx.git.external_ci else {}
     ci_failed = [c for c, state in ci.items() if state == "failure"]
--- a/cmapi/tests/core/test_lifecycle_expiration.py
+++ b/cmapi/tests/core/test_lifecycle_expiration.py
@@ -45,7 +45,10 @@
     t = transition(S.MERGED, E.SYNC_TIMEOUT)
     assert t.after == S.SYNC_FAILED and holds_lock(S.SYNC_FAILED) and t.releases_reservation
     # APPLIED: a :retry of an apply that had not finished, before any merge (#286)
-    assert set(allowed_events(S.SYNC_FAILED)) == {E.RETRY, E.SYNCED, E.REVERT, E.APPLIED}
+    assert set(allowed_events(S.SYNC_FAILED)) == {E.RETRY, E.SYNCED, E.REVERT, E.APPLIED, E.MERGED}
+    # An operator's hand merge can be adopted during a retry of a partial apply.
+    adopted = transition(S.SYNC_FAILED, E.MERGED)
+    assert adopted.after == S.MERGED and not adopted.releases_lock
 
 
 def test_a_prune_that_cannot_be_confirmed_ends_in_sync_failed():
--- a/cmapi/tests/service/gitserver.py
+++ b/cmapi/tests/service/gitserver.py
@@ -319,6 +319,10 @@
         body = _json.loads(request.content) if request.content else {}
         if "check-runs" in path or "check-suites" in path:
             raise AssertionError("the adapter must never call the Checks API (BUG-69)")
+        comments_path = _re.fullmatch(r"/issues/(\d+)/comments", path)
+        if comments_path and request.method == "GET":
+            return httpx.Response(200, json=[{"body": body} for n, body in self.comments
+                                            if n == int(comments_path[1])])
         if path == "/pulls" and request.method == "GET":
             want = request.url.params.get("head")
             return httpx.Response(200, json=[self._pr(n) for n, p in self.prs.items()
--- a/cmapi/tests/service/test_git_layer.py
+++ b/cmapi/tests/service/test_git_layer.py
@@ -1000,7 +1000,11 @@
 def test_the_api_process_reads_through_the_host_api_and_has_no_git_layer(tmp_path):
     gh = make_provider("github", API, "o/r", "t", git_layer=False, git_url="file:///nowhere")
     assert gh.workspace is None
-    with pytest.raises(GitUnavailable, match="no Git layer"):
+    import re
+    from cmapi.core.git.oplog import redact
+
+    # Even the deliberately one-character fixture credential is redacted.
+    with pytest.raises(GitUnavailable, match=re.escape(redact("no Git layer"))):
         gh.push_request_branch(None)
 
 
--- /dev/null
+++ b/cmapi/tests/test_codex_git_review.py
@@ -0,0 +1,276 @@
+"""Offline adversarial regressions: file:// Git and MockTransport only."""
+from datetime import datetime, timezone
+from types import SimpleNamespace as NS
+import importlib
+import os
+import stat
+import httpx
+import pytest
+from cmapi.core.git.base import BranchRequest, GitUnavailable
+from cmapi.core.git.github import GitHubProvider
+from cmapi.core.git.oplog import redact, register_secret
+from cmapi.core.git.workspace import GitWorkspace, GitFailed
+from cmapi.core.lifecycle import State as S, transition
+from cmapi.core.ports import PrRef, PrStatus
+from gitserver import bare_repo, git
+
+FOLDER = 'clusters/CRC/namespaces/demo'
+REL = FOLDER + '/namespace.yaml'
+HEAD, MERGE = 'a' * 40, 'b' * 40
+
+
+def test_nested_short_and_overlapping_secrets(monkeypatch):
+    import cmapi.core.git.oplog as op
+    monkeypatch.setattr(op, '_SECRETS', set())
+    for value in ('tiny', 'abcdefgh', 'abcdefgh-SUFFIX'):
+        register_secret(value)
+    assert redact({'nested': ['tiny', {'x': 'abcdefgh-SUFFIX'}]}) == {'nested': ['***', {'x': '***'}]}
+
+
+@pytest.mark.parametrize('code', [403, 502])
+def test_host_error_never_contains_registered_token(code):
+    token = 'codex-echo-token-0123456789'
+    provider = GitHubProvider('https://offline.invalid', 'o/r', token)
+    provider._client.close()
+    provider._client = httpx.Client(base_url='https://offline.invalid', transport=httpx.MockTransport(
+        lambda request: httpx.Response(code, json={'message': 'echo ' + token})))
+    try:
+        with pytest.raises(GitUnavailable) as caught:
+            provider.pr_status(PrRef(1, '', 'cmapi/CRC/r1', HEAD))
+        assert token not in str(caught.value)
+        assert token not in getattr(caught.value, 'host_message', '')
+    finally:
+        provider._client.close()
+
+
+def test_http_transport_error_never_contains_registered_token():
+    token = 'codex-transport-token-0123456789'
+    provider = GitHubProvider('https://offline.invalid', 'o/r', token)
+    provider._client.close()
+    def fail(request):
+        raise httpx.ConnectError('echo ' + token)
+    provider._client = httpx.Client(base_url='https://offline.invalid', transport=httpx.MockTransport(fail))
+    try:
+        with pytest.raises(GitUnavailable) as caught:
+            provider.pr_status(PrRef(1, '', 'cmapi/CRC/r1', HEAD))
+        assert token not in str(caught.value)
+        assert caught.value.__suppress_context__
+    finally:
+        provider._client.close()
+
+
+def req():
+    return BranchRequest('CRC', 'req-1', FOLDER, 'hash',
+                         'create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n',
+                         {REL: 'kind: Namespace\n'}, {}, datetime(2026, 1, 1, tzinfo=timezone.utc))
+
+
+def test_repository_symlink_cannot_overwrite_outside_worktree(tmp_path):
+    bare = bare_repo(tmp_path)
+    outside = tmp_path / 'outside.yaml'
+    outside.write_text('must survive\n')
+    work = tmp_path / 'person'
+    git('clone', '--quiet', str(bare), str(work), cwd=tmp_path, home=tmp_path)
+    (work / FOLDER).mkdir(parents=True)
+    (work / REL).symlink_to(outside)
+    git('add', '--all', cwd=work, home=tmp_path)
+    git('commit', '--quiet', '-m', 'symlink manifest', cwd=work, home=tmp_path)
+    git('push', '--quiet', 'origin', 'main', cwd=work, home=tmp_path)
+    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / 'worker')
+    try:
+        with pytest.raises(GitFailed):
+            ws.push_branch(req())
+        assert outside.read_text() == 'must survive\n'
+    finally:
+        ws.dispose()
+
+
+def test_workspace_is_private_under_permissive_umask(tmp_path):
+    bare = bare_repo(tmp_path)
+    old = os.umask(0o022)
+    ws = None
+    try:
+        ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / 'worker')
+        ws.push_branch(req())
+        assert stat.S_IMODE(ws.root.stat().st_mode) == 0o700
+        assert stat.S_IMODE(ws._home.stat().st_mode) == 0o700
+        assert stat.S_IMODE((ws.root / '.lock').stat().st_mode) == 0o600
+    finally:
+        os.umask(old)
+        if ws:
+            ws.dispose()
+
+
+class Repo:
+    def __init__(self):
+        self.events_seen = []
+    def events(self, request_id):
+        return []
+    def event(self, row, event, by, note='', detail=None):
+        self.events_seen.append(event)
+    def move(self, row, event, by, note=''):
+        row.status = transition(S(row.status), event).after.value
+        self.events_seen.append(event.value)
+
+
+class Jobs:
+    def __init__(self):
+        self.queued = []
+        self.finished = False
+    def fence(self):
+        pass
+    def done(self, job):
+        self.finished = True
+    def enqueue(self, kind, **kw):
+        self.queued.append(kind)
+
+
+def row():
+    return NS(status='pr_open', cluster_id='CRC', namespace='demo', request_id='req-1',
+              action='create', plan={'files': {REL: 'approved'}, 'prev': {}},
+              pr={'number': 1, 'url': '', 'branch': 'cmapi/CRC/req-1', 'head': HEAD}, merge_sha=None)
+
+
+@pytest.mark.parametrize('status', ['pr_open', 'applied'])
+def test_wrong_merge_tree_never_queues_delivery(status):
+    module = importlib.import_module('cmapi.jobs.merge')
+    r = row()
+    r.status = status
+    repo, jobs = Repo(), Jobs()
+    ctx = NS(git=NS(tree_files=lambda sha, folder: {REL: 'unapproved'}, cleanup=lambda *a: None))
+    module._merged(ctx, repo, jobs, r, NS(), MERGE, adopted=True)
+    assert r.status == 'sync_failed'
+    assert 'watch_sync' not in jobs.queued
+
+
+@pytest.mark.parametrize("status", ["pr_open", "sync_failed"])
+def test_hand_merge_between_checks_and_apply_is_adopted(status):
+    module = importlib.import_module('cmapi.jobs.apply')
+    r = row()
+    r.status = status
+    repo, jobs = Repo(), Jobs()
+    if status == 'sync_failed':
+        repo.events = lambda rid: [NS(event='apply_started', detail={'head': HEAD})]
+    ctx = NS(git=NS(pr_status=lambda pr: PrStatus('merged', {}, MERGE, HEAD),
+                    branch_head=lambda branch: None, close=lambda *a: None, tree_files=lambda sha, folder: {REL: 'approved'},
+                    cleanup=lambda *a: None))
+    module._apply(ctx, repo, jobs, r, NS(payload={'head': HEAD}))
+    assert r.status == 'merged'
+    assert r.merge_sha == MERGE
+    assert jobs.queued == ['watch_sync', 'git_cleanup']
+
+
+def test_hand_merge_during_pr_checks_uses_postmerge_check():
+    module = importlib.import_module('cmapi.jobs.pr_checks')
+    r = row()
+    repo, jobs = Repo(), Jobs()
+    ctx = NS(git=NS(pr_status=lambda pr: PrStatus('merged', {}, MERGE, HEAD),
+                    tree_files=lambda sha, folder: {REL: 'unapproved'}, cleanup=lambda *a: None))
+    module._pr_checks(ctx, repo, jobs, r, NS())
+    assert r.status == 'sync_failed'
+    assert 'watch_sync' not in jobs.queued
+
+
+@pytest.mark.parametrize('operation', ['push', 'delete'])
+def test_gitea_never_deletes_or_adopts_an_unverified_existing_branch(operation):
+    from cmapi.core.git.gitea import GiteaProvider
+    from cmapi.core.git.workspace import BranchRefused
+    calls = []
+    def host(request):
+        calls.append(request.method)
+        if request.method == 'DELETE':
+            return httpx.Response(204)
+        if '/branches/' in request.url.path:
+            return httpx.Response(200, json={'commit': {'id': HEAD}})
+        if request.url.path.endswith('/pulls'):
+            return httpx.Response(200, json=[{'number': 1, 'head': {'ref': 'cmapi/CRC/req-1', 'sha': HEAD}}])
+        raise AssertionError(request.url)
+    provider = GiteaProvider('https://offline.invalid', 'o/r', 'test-token')
+    provider._client.close()
+    provider._client = httpx.Client(base_url='https://offline.invalid', transport=httpx.MockTransport(host))
+    try:
+        if operation == 'push':
+            with pytest.raises(BranchRefused):
+                provider.push_request_branch(req())
+        else:
+            with pytest.raises(GitUnavailable, match='conditionally delete'):
+                provider.delete_branch('cmapi/CRC/req-1', HEAD)
+        assert calls and set(calls) == {'GET'}
+    finally:
+        provider._client.close()
+
+
+def test_repeated_push_dates_adoption_and_conditional_delete(tmp_path, monkeypatch):
+    bare = bare_repo(tmp_path)
+    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / 'worker')
+    calls = []
+    real = ws._m
+    def record(*args, **kw):
+        calls.append(args)
+        return real(*args, **kw)
+    monkeypatch.setattr(ws, '_m', record)
+    try:
+        first = ws.push_branch(req())
+        branch = 'cmapi/CRC/req-1'
+        pushes = [a for a in calls if a[0] == 'push']
+        assert f'--force-with-lease=refs/heads/{branch}:' in pushes[0]
+        dates = ws._out('show', '-s', '--format=%at %ct', first.head, git_dir=True)
+        timestamp = int(req().approved_at.timestamp())
+        assert dates == f'{timestamp} {timestamp}'
+        second = ws.push_branch(req())
+        assert second.head == first.head and second.result == 'adopted'
+        assert len([a for a in calls if a[0] == 'push']) == 1
+        assert not ws.delete_branch(branch, 'f' * 40)
+        assert ws.delete_branch(branch, first.head)
+        assert f'--force-with-lease=refs/heads/{branch}:{first.head}' in calls[-1]
+        assert f':refs/heads/{branch}' in calls[-1]
+    finally:
+        ws.dispose()
+
+
+def test_transport_discards_inherited_askpass_and_ssh_command(tmp_path, monkeypatch):
+    from cmapi.core.git.transport import Credentials, Remote, git_environment
+    monkeypatch.setenv('GIT_ASKPASS', '/tmp/evil-helper')
+    monkeypatch.setenv('GIT_SSH_COMMAND', 'ssh -o StrictHostKeyChecking=no')
+    key, hosts = tmp_path / 'key', tmp_path / 'known_hosts'
+    env = git_environment(Remote('ssh://git@offline.invalid/r', 'ssh'),
+                          Credentials(key_file=key, known_hosts=hosts), tmp_path, None, ('bot', 'bot@invalid'))
+    assert 'GIT_ASKPASS' not in env
+    assert 'StrictHostKeyChecking=yes' in env['GIT_SSH_COMMAND']
+    assert 'StrictHostKeyChecking=no' not in env['GIT_SSH_COMMAND']
+    assert 'IdentityAgent=none' in env['GIT_SSH_COMMAND']
+
+
+
+def test_lost_comment_response_is_adopted_on_retry():
+    comments = []
+    def host(request):
+        if request.method == 'GET':
+            return httpx.Response(200, json=[{'body': body} for body in comments])
+        assert request.method == 'POST'
+        import json
+        comments.append(json.loads(request.content)['body'])
+        return httpx.Response(502 if len(comments) == 1 else 201)
+    provider = GitHubProvider('https://offline.invalid', 'o/r', 'test-token')
+    provider._client.close()
+    provider._client = httpx.Client(base_url='https://offline.invalid', transport=httpx.MockTransport(host))
+    pr = PrRef(1, '', 'cmapi/CRC/req-1', HEAD)
+    try:
+        with pytest.raises(GitUnavailable):
+            provider.comment(pr, 'cmapi: merge failed; retry required')
+        provider.comment(pr, 'cmapi: merge failed; retry required')
+        assert comments == ['cmapi: merge failed; retry required']
+    finally:
+        provider._client.close()
+
+
+def test_leading_dash_folder_is_a_path_not_an_option(tmp_path):
+    from dataclasses import replace
+    bare = bare_repo(tmp_path)
+    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / 'worker')
+    try:
+        request = replace(req(), folder='-folder', files={'-folder/namespace.yaml': 'kind: Namespace\n'})
+        pushed = ws.push_branch(request)
+        assert ws.read_folder('-folder', pushed.head)[0] == dict(request.files)
+    finally:
+        ws.dispose()
```
