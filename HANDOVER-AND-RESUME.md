# cmapi: handover and resume

**Resume here.** This top section is the current state, written by the coordinator on 2026-11-23. It supersedes
every section below it, which is kept as history. The tracker is [`build-tracker.md`](build-tracker.md), the issues are
[`issue-register.md`](issue-register.md), and the rules are [`CLAUDE.md`](CLAUDE.md).

## Resume here: 2026-11-23, 23:59Z (the owner is switching accounts)

Written by the coordinator (Opus 5.5) from `gh`, `git`, the run records and the review folders. Supersedes the
2026-11-22 07:50Z section below. Every path under `workbench/` is `/Users/olasumbo/gitRepos/workbench/cmapi/`.

### 1. Where it stands

| Item | State |
|---|---|
| `main` | `78ec33e` (PR #618) |
| CRC | Runs `365b4b9` (OB1 run 37, `workbench/ob1-run37/resume.md`). api and worker `cmapi@sha256:885dac5838dc…`, portal `cmapi-portal@sha256:9795fd146d2d…`, both from CI by digest. alembic `0008`. keycloak-0 0 restarts during the run. Import token expires 2026-11-30T22:51:48Z. `main` is ahead only by #618, which changes `examples/` and is not in the image, so CRC needs no deploy for it |
| Open PRs | #617, #621, #622 (each has reviewer 1's report; all three are "request changes"). Branch `fix/605-head` is pushed, its PR is not open yet |
| Local jobs left running at the switch | #605's full service suite (writes `workbench/wt-605-outputs/full-suite.txt` when done), then `workbench/review-617/r2-outputs/queue-coordinator.sh` (the rest of reviewer 2's #617 runs; it prints `QUEUE-DONE`). If either is gone (`pgrep -fl "[p]ytest.*tests/service"` empty and the file empty or no `QUEUE-DONE` in the outputs), run it again |
| Owner items | Say yes or no to the diagram-kit `/agile` update with this week's Sonnet lessons. Run `~/.claude/tools/sweep-stale.py --sweep` yourself: Claude Code refused it for the agent; it ends stale Codex brokers (about 860 MB) |

### 2. Merged on 2026-11-22 and 23 (18 PRs)

| PR | Closes | What |
|---|---|---|
| #557 | | Records of 2026-11-22 |
| #559 | #556, #558, #561 | Swagger UI fits 390 px |
| #562, #564, #566, #572, #576, #577 | #560, #563, #565, #567-#570, #574, #575 | Docs: docs/14 routes without a token; the namespace ETag; `docs/GLOSSARY.md` (new); docs drift; docs/08 database KPIs |
| #579 | #571, #578, #580 | If-Match: a list passes, `*` is 428 (the owner's decision), a weak tag never matches |
| #588 | #583, #584, #585 | If-None-Match lists; unambiguous folder ETags (v2 hash); complete caData blocks |
| #589 | #581, #582, #586, #587 | The If-Match surface says and does what the code does |
| #599 | #591, #594, #595, #597 | caData with a non-ASCII line loads |
| #598 | #590, #593, #596 | Conditional reads: If-Match first (412 before 304); CORS reads every Vary line |
| #601 | #592, #611, #612 | An Idempotency-Key belongs to its caller: migration 0008, expand then contract (the owner's decisions) |
| #607 | #602, #606 | DELETE `?dryRun=true` is a dry run; a write with no dry run refuses `dryRun` (400); a repeated `dryRun` is 422 |
| #608 | #600 | Portal check 20 waits for the filtered rows |
| #610 | #609 | Every CI and image download retries |
| #618 | #613 | `examples/local` refuses `dryRun` on writes with no dry run, after sign-in |

Deployed: run 35 (`9876fee`), run 36 (`8d74f1a`, migration 0008 applied), run 37 (`365b4b9`). Run 37 proved #602 and
#606 live with no real write: requests 19 → 19, the `change_requests` md5 unchanged.

Live docs (edit them first, then the exports): Technical Design v2 rev 393, Design and Architecture rev 196.

### 3. Next, in order

Each PR follows the delivery loop in `CLAUDE.md`. Reviewer 1 is Codex `gpt-6.2-astra` xhigh. Reviewer 2 is a separate
Opus 5.5 high agent: it checks reviewer 1's snippets on the real database and returns one patch. The coordinator applies
it with `patch -p1 -F0`, runs the tests, commits the review record under `docs/reviews/2026-11-23-issue-N/review/`, posts
the rulings and merges on green.

1. **PR #617** (#614 the migrator's `migrated` event, #615 the lock test). Worktree `workbench/wt-614`.
   - Reviewer 1: `workbench/review-617/codex-result.txt`. It found three things:
     - the event depends on `CMAPI_LOG_LEVEL` (with `WARNING`, a successful run is silent);
     - docs/12 overstates what the times measure;
     - the #615 test has a scheduling margin and accepts exit 0.
   - Reviewer 2: `workbench/review-617/r2-report.md` and `r2-outputs/fix.diff`. Its rulings:
     - the migrator always logs at INFO, and a `migrate_failed` event carries only the error class and SQLSTATE;
     - the docs/12 text is replaced with a shorter one;
     - a real-database timing test replaces reviewer 1's mock test;
     - the #615 test is narrowed.
   - **Not finished:** the report still has `__NAME__` blanks (`__NOFAIL__`, `__LEAK__`, `__EXIT0HEAD__`, `__MARGIN__`, `__HEADRUNS__`, `__R1RUNS__`, `__EXIT0R1__`, `__R2RUNS__`, `__EXIT0R2__`, `__N__`). They are filled from the outputs of `queue-coordinator.sh`: `mutants.txt`, `after-r2-614-secondpass.txt`, `repeat615.txt` and `after-r2-migrate-related.txt`.
   - Then the coordinator applies `fix.diff`.
2. **PR #621** (#604 static files and If-Match, #619 If-Unmodified-Since, #620 If-Modified-Since). Worktree `workbench/wt-604`.
   - Reviewer 1: `workbench/review-621/codex-result.txt`, "request changes". There are two defects in `http_date`: it accepts invalid dates, which can turn a 200 into a 304 or a 412, and its RFC 850 two-digit-year cutoff is wrong.
   - Next: reviewer 2.
3. **#605** (HEAD on every GET). Branch `fix/605-head` is stacked on #621; worktree `workbench/wt-605`.
   - Reviewer 1 has reviewed it before the PR exists: `workbench/review-605/codex-result.txt`, "request changes". Two findings matter:
     - an authenticated HEAD on the quota export writes the same audit row as a GET;
     - HEAD on POST-only paths that share a GET's path (`:approve`, `:reject`, `:cancel`, `:retry`, `:revert`) answers 401 from the GET route, not 405.
   - **The coordinator's full suite fails one test** (2026-11-24 01:14Z, `workbench/wt-605-outputs/full-suite.txt`: 1 failed, 2530 passed). The failing test is `test_review_c_authz.py::test_declared_permission_is_the_enforced_one_and_every_route_answers`. It lists HEAD on public GET routes as routes that answer without a token: `/api/v1/version` 200, `/docs` 503, `/docs/swagger.css` 200 and others. Decide in the review whether the test's public set should take HEAD wherever it takes GET (RFC 9110 §9.3.2), or whether the code is wrong. Fix it in this branch before the PR, with the failing test as the proof.
   - Next: reviewer 2, then open the PR with `workbench/wt-605-outputs/pr-body.md`. Fill its blanks:
     - BEFORE and BEFORE_FULL: `before.txt`, 9 of 9 failed;
     - AFTER and FULLSUITE: `full-suite.txt`, after the authz fix above (it was 1 failed, 2530 passed);
     - MUTANTS: `mutants.txt`, M1 to M5 killed;
     - CONTRACT: `openapi.json` unchanged, 0 diff lines;
     - CITATIONS: 0 problems.
   - Retarget the PR to `main` when #621 merges.
4. **PR #622** (#616 a delete removes the whole folder, #623 the contract README). Worktree `workbench/wt-616`.
   - Reviewer 1: `workbench/review-622/codex-result.txt`, "request changes", 7 findings. The blocker: the pre-merge checks (`jobs/pr_checks.py`, `workspace.py` merge check) still read the direct-manifest `tree_files`. A file added to `main` before the merge survives, and it is found only after the merge (`jobs/merge.py`).
   - Next: reviewer 2.
5. **#603** (#592 release 2: migration 0009, refuse while pairs are live, invert the window test). Start it after #617 merges: both touch the migration code.
6. **Deploy run 38** after 1 to 4 merge. Use run 37 as the template (`workbench/ob1-run37/resume.md` and its tools). Gate on load and on no running suite.
   - Prove #605 and #621 on the wire with curl HEAD and conditionals on `/openapi.json` and `/static/swagger/...`.
   - Prove #617: the `migrated` line in `oc logs <api pod> -c migrate`.
   - Prove #622 with a dry run only. Never a real delete.

### 4. How to run things here (lessons of 2026-11-23)

- **The idle gate.** Gate a test run on two things: no other suite running (`pgrep -f "[p]ytest.*tests/service"` and
  `pgrep -f "[n]pm test"` find nothing), and the 1-minute load under **16**. The old limit of 8 sat below the CRC VM's
  own floor (9 to 12 with no suite running), so three agents waited 50 to 108 minutes. Check each agent at its due time;
  a gate wait longer than one suite (about 35 minutes) is a stall.
- **The Bash tool is zsh:** `for x in $LIST` and `set -- $b` do not word-split. Use arrays, or a script file run with bash.
- **Codex jobs.** Look up a job from the folder it started in. The companion script is
  `~/.claude/plugins/cache/*/codex/*/scripts/codex-companion.mjs`, used as `status <job>` and `result <job>`.
  `workbench/codex-wait-3.sh` is a working waiter.
- **One scratch folder per agent**, named in the brief. Never the shared scratchpad.
- **Codex cannot reach PostgreSQL**, open sockets or write to git. Reviewer 2 (Opus) or the coordinator runs those parts.

### 5. For Sonnet 5.5, resuming its work

Sonnet drafts the records and the agile updates from what is built. The coordinator checks every line before it posts or merges. Its jobs:

1. **After each merge:**
   - add the PR to the tracker's "Current" table, with its proof (CI run, suite counts, CRC run);
   - label the issues it closes `Done`, and `Local-Deploy` once a CRC run proves them;
   - regenerate `issue-register.md` with `scripts/issue-register.sh`. Never edit it by hand.
2. **After a CRC run:** copy the version, digests, alembic revision and each live table from `workbench/ob1-runN/resume.md` into this section and the tracker. Copy them; do not round or summarize.
3. **Stories (#13 to #29) and epic #481:** an issue closes only after the owner approves. The closing comment cites the proof for each acceptance criterion and the cluster it ran on.
4. **Sources:** read the code, `gh` and the run records, never memory. Say what was measured, what was inferred and what was not tested. Commits carry no `Co-Authored-By` or "Generated with" lines.

## Resume here: 2026-11-22, after 07:50Z (superseded by the section above)

Drafted by Sonnet 5.5 from `origin/main`, `gh` and the live `/api/v1/version` answer; checked by the coordinator. Supersedes the 05:05Z section below.

| Item | State |
|---|---|
| `main` | `5c01876` (PR #555). No open PRs |
| CRC | Runs `5c01876` (`/api/v1/version` answered `{"version":"0.2.0","commit":"5c01876086","component":"api"}`; the #484 closing comment calls it run 33) |
| Stories #483, #484, #485 | Approved by the owner on 2026-11-22 through `/decide`, and closed (07:46:58Z, 07:47:01Z, 07:47:03Z) |
| Epic #481 | Open. Its one open child is #482 (spike, In-Progress); #483, #484 and #485 are closed. #486 (the rollout window, In-Progress) belongs to #13, not #481 |
| New defect | #556: "Swagger UI (/docs) scrolls sideways by 149 px at 390 px". Open, `bug`, `sev:low`, a sub-issue of #485 |

**What the owner decided (the last comment of each story, quoted):**
- #483: "Prove 428 live, then approve".
- #484: "Approve #484".
- #485: "Approve, file the 390 px scroll".

**428, proven live on CRC** (`5c01876`, 2026-11-22 07:46:23Z, as `cmapi.requester`, from the #483 closing comment):
- `PATCH /api/v1/clusters/CRC/namespaces/cmap-live-g-dev?dryRun=true`, without `If-Match`.
- The answer: HTTP 428, `code: precondition-required`.
- `GET /api/v1/requests` total: 19 before and 19 after. It was a dry run, with no Git change.
- The check is `core/pipeline.py:217` (`require_if_match`), just before the 412 at :218-219.

**The "Waiting for the owner" list of the 05:05Z section is answered.** Nothing waits for the owner now.

**Next, in order:**
1. #556: fix the 149 px sideways scroll of Swagger UI at 390 px. Located on CRC on 2026-11-22 (the #556 comment): the overflow appears only with the PATCH operation open, and it is the Extensions table, whose cells hold the long `x-codeSamples` JSON with no wrap (`scrollWidth` 539 at 390). Fix it in the page cmapi serves, not in the vendor bundle. The proof opens the PATCH operation at 390 px and asserts `scrollWidth <= clientWidth`; it fails today and passes after; 1440 px stays at 0.
2. #482 (the spike, the last open child of #481; #481 closes when it is done) and #486 (the rollout window, part of #13). Both are open and In-Progress.
3. The other open defects (`gh issue list -R ephico2real2/cmapi --state open --label bug`). Each goes through `fix-defect`, in the session it is found.

Observed on #485, not defects: neither Swagger UI nor ReDoc has a dark theme, and ReDoc's logo is refused by cmapi's CSP on purpose (`main.py` l.313-316).

## Resume here: 2026-11-22, after 05:05Z (superseded by the section above)

Drafted by Sonnet 5.5 from `origin/main`, `gh` and OB1's run 32 record (`workbench/cmapi/ob1-run32/resume.md`); checked by the coordinator. Supersedes the 2026-11-21 08:30Z section below.

| Item | State |
|---|---|
| `main` | `8f387bf` (PR #553). No open PRs |
| CRC | Runs `4999dee` (OB1 run 32, steps 0 to 22 between 22:47Z and 22:57Z on 2026-11-21). api and worker `cmapi@sha256:67f43526...`, portal `cmapi-portal@sha256:a18734ce...`, both imported from GHCR by digest (#545). alembic `0006`. keycloak-0 restarts unchanged (4). Import token expires 2026-11-28T22:55:21Z |
| Not yet deployed | #550, #553 (migration `0007`, run by step 21) and #554 (test-only). Run 33 deploys `8f387bf` |
| CRC policies | The dev bundle is 40/40, `hashState: current`, hash `a2603db2...`, no bundle apply needed (run 32, `logs/clusters-hash-after.txt`) |
| Test namespace | `cmap-live-g-dev` (protected, cost-center `cc-4410`, team `cmapi-live`), kept. `cmapi-live-a` to `-f` untouched. 0 open requests |
| Keycloak | CPU request 2 (was 1); memory 1 Gi request, 2 Gi limit. Ready 23:42:07Z with all five realms at 200 |
| Monitoring | Off (the owner, 2026-11-20). Steps 23 to 25 wait for it (#489) |
| Guard | Step 5 no longer builds on the Mac (#545). The watch must be read before each live scenario: run 32 ran scenarios after its stop file (23:11:29Z) |

**What happened on 2026-11-21 evening (facts, with sources):**
- Run 31 and run 32's first attempt were stopped by the guard in step 5, the local image build. In the first attempt, 58 containers in 42 namespaces had a last termination between 18:03Z and 18:31Z (resume.md, "STOP"). #545 (PR #548, `4999dee`): CI builds and attests both images; step 5 imports the digest. Second attempt: step 5 rc 0, no build, no restart outside cmapi.
- Keycloak CPU: the owner asked for more resources. First patch 23:30:13Z; **the coordinator's watcher bug (zsh word splitting) rolled it back**, so the five realms had **two outages, not one**. Re-applied 23:41:12Z, Ready 23:42:07Z, all five realms 200 (`tasks/bu7aebp1k.output`, `bhsovz54t.output`).
- The guard's stop at 23:11:29Z, one missed 3-s check of realm inkcast-prod: scenario 1's revert and scenarios 2 to 4 ran after it. All ended clean (#484 comment, 23:30Z).
- Defect found live and fixed: #551 (`request_events.at` was the transaction's start), PR #553, migration `0007`.

**Merged since the last tracker update (`2997652`, PR #539):**
- #541: the project rules: Sonnet 5.5 drafts documentation and the coordinator oversees it; "Research, then ask". diagram-kit PR #82 is merged (the `/decide` skill and the `agile` as-built method).
- #542 (#485): Swagger and ReDoc docs for the namespace-change operations.
- #544 (#543): the secrets mutation harness runs scripts through Bash (ETXTBSY).
- #540 (#537, #538): the Policies tab, collapsible and paged.
- #547 (#546): docs/13's test namespace names follow CRC's name rule.
- #548 (#545): CI builds the images; step 5 imports by digest.
- #550 (#549): owner secret steps prompt for the token (`deploy/owner-secret.py`).
- #554 (#552): portal checks wait for what an action renders.
- #553 (#551): request events record their own time.

**Waiting for the owner (each comment is a draft posted 2026-11-22T04:12Z):**
1. #484: approval of the Namespaces tab, and whether the gaps (axe, 820 px, keyboard, Remove and Undo, a Submit-side 412 on CRC) may stay on the stand-in and CI.
2. #483: approval of the PATCH contract, and whether 428 may stay CI-proven or needs a live request without `If-Match`.
3. #485: approval of Swagger and ReDoc, and whether the three observations (no dark theme, Swagger UI sideways scroll at 390 px, ReDoc logo refused by the CSP) are accepted or need a follow-up.

**Next, in order:**
1. The owner's approvals above. A story closes only after the owner approves, with a comment citing the proof for each acceptance criterion and the cluster it ran on.
2. Run 33: deploy `8f387bf` on CRC (step 21 runs migration `0007`), with the watch read before each live scenario. Steps 23 to 25 wait for monitoring.
3. The open defects (`gh issue list -R ephico2real2/cmapi --state open --label bug`, 53 on 2026-11-22). In-Progress: #509, #507, #504, #493, #489, #487, #486, #235, #149, #62. Blocked on the owner: #157, #36, #35. In-QA: #169. The rest are Backlog: #474, #473, #461, #376, #373, #372, #321, #315, #314, #309, #292, #291, #287, #276, #273, #266, #265, #264, #263, #260, #259, #258, #257, #256, #250, #248, #243, #237, #236, #220, #207, #189, #170, #167, #150, #147, #60, #59, #33. Each goes through `fix-defect`, in the session it is found.

**Keycloak rollback time (coordinator's measurement):** the watcher started at 23:30:13Z with a 600 s limit, so it patched the CPU request back at about 23:40:13Z; the replacement pod started at 23:40:19Z (read with `oc` at 23:40:45Z). The zsh cause is the coordinator's own diagnosis (memory `feedback-zsh-word-splitting`). This section is written after 05:05Z, the merge of #553.

## Resume here: 2026-11-21, 08:30Z (superseded by the section above)

Supersedes the 2026-11-20 10:15Z section below.

| Item | State |
|---|---|
| `main` | `9ad4de8` (PR #499); PR #525 (#524) merging on green CI |
| CRC | Runs `cd01af1` (OB1 run 30, `workbench/cmapi/ob1-run30/resume.md`), since 05:13:23Z. api and worker `cmapi@sha256:2ef25696...`, portal `cmapi-portal@sha256:4c3b1ec6...`. keycloak-0 restarts unchanged (4). Import token expires 2026-11-28T05:13Z |
| CRC policies | The dev bundle at cmapi `cd01af1` is applied (cmapi-cluster-configs #19, merge `b1a5a35ade`): 40 policies, `hashState: current`, 84 pass and 0 fail; the Policies tab reads "0 failing · 0 clusters off the bundle" (`ob1-run30/screens/p2-after510-policies-1440-light-chrome.png`). The stale `cmapi-metadata-dev-label-cmapi-net-rightsizing-pattern` was deleted by name |
| Monitoring | Off (the owner, 2026-11-20, Mac memory). Steps 23 to 25 of each run wait for it (#489) |
| kind | Deleted |
| Open | Story #484 (Namespaces tab): the implementer (Opus 5.5 high) is building it from the epic-481 design §6 |

**Live on CRC (run 30, installed Chrome, `cmapi.requester`, nothing submitted):** a namespace name with an empty
middle is `abc-dev`, and `payments` gives `abc-payments-dev`; both dry runs answer 200. The middle `-x` is refused at
the field ("Start and end with a letter or digit."), and no request is sent (#511, #512).

**Merged on 2026-11-21:**
- #514 (#512): a namespace middle starts and ends with a letter or digit, in the API, the Kyverno rule, the stand-in and the portal.
- #517 (#516), and cmapi-cluster-configs #20: `ci/kyverno` fails an audit violation only in the namespace folders a pull request changes; others warn; with no first-parent diff, every folder counts as changed.
- cmapi-cluster-configs #19 and #515 (#510): CRC's bundle re-rendered for the metadata keys of #505, and docs/13 says that a change to the configuration needs its bundle pull request before the deploy.
- #519 (#518), #522 (#508, #521): portal check timing. The P9 cause was in the product: the pattern time limit also timed the worker's start-up. Check 7 and the workflow check are split by view.
- #520 (#513), #525 (#524): tests that needed the Kyverno CLI on PATH, or that ran another checkout's `cmapi-tools`.
- #499 (#491, #494, #495, #496, #497, #501, #523): the review defects of #492, reviewed by Codex `gpt-6.2-astra` xhigh, then Fable; `clusterTokens.duration` is at most 2^32 seconds.

**Next, in order:**
1. #484: the coordinator's checks, then Codex `gpt-6.2-astra` high, then Fable; merge on green.
2. Run 31 on CRC with #484 and everything merged since `cd01af1`, with screenshots of the Namespaces tab.
3. #485 (Swagger and ReDoc for the namespace-change operations), #486, #487, #489, #493.
4. The owner chooses the calm mockup variant or the approved one (artifact `9atTm9MrQBFcDCnWMxQLwm`).

**Lessons recorded today:**
- A merge of `main` into a branch, never a rebase of a pushed one: Claude Code refused a `--force-with-lease`.
- A draft PR's red CI is still a finding: #499's service job had failed on a pinned hash before the review.
- A reviewer's "fails on main too" is checked on `main` before it is accepted (retracted for `test_bundle_hash_244`).

## Resume here: 2026-11-20, 10:15Z (superseded by the section above)

Supersedes the 2026-11-19 19:40Z section below.

| Item | State |
|---|---|
| `main` | `fb727b5` (PR #478) |
| CRC | Runs `fb727b5` (OB1 run 27, `workbench/cmapi/ob1-run27/`). api and worker `cmapi@sha256:170d838a...`, portal `cmapi-portal@sha256:272e5224...`, 0 restarts. Live checks 1 to 6 passed. #477: CRC `hashState` current. **Step 23 stopped rc 1** on the first Thanos query: `openshift-monitoring` was scaled to 0/0 at 08:31:47Z during the CRC recovery (a shared service; not touched; #489). Steps 23 (its last line deletes `cmapi-system/cmapi-reader-token`), 24 and 25 (deletes the Keycloak backup) wait for monitoring to come back; then run steps 12, 13, 14, 23, 24 and 25 (docs/13 line 622). Earlier, at about 08:28Z, CRC went down: all cmapi pods' probes timed out and keycloak-0 restarted (4 restarts, last at 08:25:56Z). Another agent recovered it |
| kind | **Deleted.** The owner shut it down ("shut down the kind for now"; `podman stop` at 08:14Z). docs/13 step 2 refuses a deploy while any kind cluster exists, and Claude Code refused `down.sh` for the agent (#487), so the owner ran `deploy/kind-import/down.sh --stale` themselves. Verified: no kind cluster, no `cmapi-imports/cmapi-cluster-kind-cmapi-test`. `cmapi-test-pg` (the test database) still runs. Recreate with `up.sh` only when the owner asks |
| Open PRs | #488 (#479 Phase 1, draft, `review:fable`): implementer's report in; next are the coordinator's checks and the Codex astra xhigh review, after run 27 |

**Merged since run 26:**
- #469 and #478 (#398): CRC's import uses a TokenRequest token; cmapi renews import tokens itself. `clusterTokens {duration, renewBefore | renewBeforePercentage}` is set per instance and per cluster; the rule is halfway at the earliest and 10 minutes before expiry at the latest; the manual path is kept as the fallback. Fable reviewed it, by the owner's exception.
- #471 (#470), #472 (#407), #475 (#429).
- #476 (#244 design) and #477 (#244 S1: bundle hash and `hashState`, Fable-reviewed).

**#398 proven live on CRC** (comment on #398; `workbench/cmapi/token-test-20261120/`):
- a 20m import written by the manual fallback at 09:54:21Z;
- the worker renewed it at 10:05:08Z (due 10:04:20Z) with a 7d token, `renewals_total` success 1;
- the api and worker held it by 10:09:12Z.

**Designed today (owner's requirements):**
- **#479, namespace contract and form:** `docs/reviews/2026-11-20-issue-479/` in PR #488.
  - The name is `<mnemonic>-<name>-<env>`, with both ends locked.
  - The required company keys are added, and the mnemonic fills the team by default.
  - Extra keys go in a closed toggle, empty by default.
  - The expiry calendar is optional, with `enabled: false` for prod. `maxLifetimeDays` never sets a date.
  - The Swagger and ReDoc standard is #480.
- **Epic 8 (#481), change the metadata of existing namespaces:** `docs/reviews/2026-11-20-epic-481-metadata-patch/` (this PR), with stories #483 to #485.

**Next, in order:**
1. When monitoring is back: finish run 27 (steps 12, 13, 14, 23, 24, 25).
2. #488: the coordinator's full suite and contract gate; Codex `gpt-6.2-astra` xhigh review; ruling; merge. Then #479 Phases 2 to 5 (Phase 5 needs the owner's answers on design §8).
3. #483, #484, #485.

**Owner items:** design §8 of #479; the live Claude Docs of docs/01 and docs/02; Kyverno audit → enforce; #244 S2 to S8; #473, #474, #486, #487, #489; restoring CRC's `openshift-monitoring`.

## Resume here: 2026-11-19, 19:40Z (after OB1 run 26; superseded)

Supersedes the 18:00Z section below. Since then: PRs #465 (#396, #397) and #467 merged with every GitHub check passed; OB1
run 26 deployed `main` `7122ec6` on CRC.

| Item | State |
|---|---|
| `main` | `7122ec6` (PR #467) |
| CRC | Runs `7122ec6` (OB1 run 26, `workbench/cmapi/ob1-run26/`): every step rc 0, 25 proof lines passed, watch 0 breaches; api/worker `cmapi@sha256:058da740...`, portal `cmapi-portal@sha256:1b6c8c92...`; keycloak-0 0 restarts; alembic 0006 |
| kind | `KIND_CMAPI_TEST` re-imported by up.sh. **Token expires 2026-11-26T19:27:14Z; rerun `deploy/kind-import/up.sh <cmapi-cluster-configs checkout>` by 2026-11-25T09:51:14Z** |
| Open PRs | None. Nothing running |

**Proven live on CRC (run 26):** `GET /api/v1/clusters` shows `statusSince`, `secretName`, `tokenExpiresAt`, `lastProbeAt`
and `trust` for both clusters (CRC's `tokenExpiresAt` null: #398); `POST /api/v1/clusters/{id}:probe` 200 for operator,
403 for viewer and requester, 404 for an unknown cluster; `cmapi_cluster_token_expiry_seconds` has a KIND_CMAPI_TEST
series and none for CRC; Policies and Capacity render for both clusters (31/31 policies on each; screenshots in
`ob1-run26/screens/`). **Not tested live:** the Git delivery changes (#453, #457 to #460), #455, and a finding appearing
and clearing (#462).

**Next, in order:** mayday job i398 (#398, briefed: see the 18:00Z section for the launch command), then #407, #429 and
#244; then records. Waiting for the owner: the live Claude Docs of docs/01 and docs/02; Kyverno audit → enforce; Fable
reviews of #462 to #465.

## Resume here: 2026-11-19, 18:00Z (stopped by the owner; superseded by the section above)

The owner stopped work at 17:56Z ("Stop current job and do an handover and resume docs"). Read this, then the 17:30Z
section below it, which still holds for how work ships (/houston-mayday) and today's lessons.

| Item | State |
|---|---|
| `main` | `3db1fa8` (PR #466, records) |
| CRC | Still runs `b8ee59e` (OB1 run 25). **Not deployed:** #443, #453, #455, #457 to #460, #462 to #464, #466 |
| kind | `KIND_CMAPI_TEST` (rnd), imported. **Token renew by 2026-11-24T17:30Z** (`deploy/kind-import/up.sh <cmapi-cluster-configs checkout>`) |
| Running | Nothing. The merge waiter of #465 was stopped; no Codex job, no test suite, no deploy is running |

**Stopped mid-way: PR #465 (#396, #397), head `2e5b2f5`, ready for review, labelled `review:fable`, NOT merged.**
- Ruled: round 2's F1, F2 and F4 to F7 accepted; F3 refused (`tlsServerName` is public by the owner's D3 of #434).
- The coordinator's full service suite found two faults; Codex sol fixed both, and the coordinator accepted them:
  `68132a7` (F2 masked raw import values below #420's 8-character minimum, so a 1-character test token turned
  `invalid caData` into `invalid caDa***a`) and `2e5b2f5` (the probe operation added to `MOCKUP-CONTRACT.md` and the
  portal-architecture README).
- Full service suite at `2e5b2f5` on this Mac: **1711 passed, 6 failed**. The 6 are `test_contract_report_337`, which fail
  only here (the `workbench/cmapi/ob1-run/venv` has an old `cmapi-tools` without `openapi render`); CI passes them.
- CI on `2e5b2f5` was running when work stopped (api-contract and portal-mockup passed; the rest pending).
- **To resume:** check `gh pr checks 465`. If every check passed and the head is still `2e5b2f5`, merge it
  (`gh pr merge 465 --merge`), then close #397 by hand if GitHub closed only #396 (it closes only the first `Closes` line).
  If `portal-ui` failed, re-run it once (known flake #347/#410); any other failure goes back to a mayday fix job.

**Briefed, not started: mayday job i398 (#398, CRC's own import token never expires).**
- Briefs pass `brief_check`: `workbench/cmapi/mayday/i398-r1/brief.md` and `i398-r2/brief.md`; plants in `workbench/cmapi/mayday-plants/i398-r*.md`. #398 has `review:fable`.
- Round 1 moves `deploy/crc-reader-import.sh` to a TokenRequest token with both annotations, removes the legacy
  `cmapi-reader-token` Secret if nothing reads it, and records the renewal path. No cluster access in the job; the CRC
  deploy applies it later.
- **To start** (after #465 merges, from an updated `main`): rebuild both briefs with `make_brief.py`, then
  `DRAFT_REPO=ephico2real2/cmapi CODEX_MODEL=gpt-6.2-astra LABELS=review:fable run-pair.sh workbench/cmapi/mayday i398 high high <cmapi-design> cmapi fix/398-crc-import-token main`.

**Next after that, in order:** mayday #407 (portal paged tabs), #429 and #244 (cluster-configs CI); then one CRC deploy
of everything merged since `b8ee59e` (`down.sh` first, `up.sh` after, which renews kind's token); then records.

**Housekeeping for a quiet moment:** `git worktree list` shows 76 worktrees under `workbench/cmapi/`, most for merged
branches. Prune by the Border rules (merged, no open PR, checked just before removal, logged with the SHA).

**Waiting for the owner:** the live Claude Docs of docs/01 and docs/02; Kyverno audit → enforce, per environment; Fable
reviews of every `review:fable` PR (#462, #463, #464, #465) when Fable resumes.

## Resume here: 2026-11-19, 17:30Z (superseded by the section above)

Read this, then the 03:30Z section below it. Sections 4 and 6 to 10 of 2026-11-16 still hold.

| Item | State |
|---|---|
| `main` | `fcb49bb` (PR #464) |
| CRC | Still runs `b8ee59e` (OB1 run 25). **Not deployed:** #443, #453, #455, #457 to #460, #462 to #464 |
| kind | `KIND_CMAPI_TEST` (rnd), imported. **Token renew by 2026-11-24T17:30Z** (`deploy/kind-import/up.sh <cmapi-cluster-configs checkout>`) |
| Podman VM | 4 CPU / 5 GiB (was 8 / 8; the owner chose "Shrink Podman VM" for the Mac's load) |
| In flight | PR #465 (#396 + #397, mayday job i396, astra high): both rounds done, round 2's F1, F2 and F4 to F7 accepted, F3 refused (`tlsServerName` is public by the owner's D3 of #434). The coordinator's full service suite is running; then ready, merge on green CI |

**How work ships now: /houston-mayday** (the owner, 2026-11-19: "use houston may day skills from diagram kit ... codex
astra high and sol (for not complex task)", "Tag all work done with houston mayday with further fable review", "We are
going to merge it and we will just review them later"):
- Claude writes the mission heads (`workbench/cmapi/mayday/heads/<job>-r1.md`, `-r2.md`) and planted answers outside
  the job folder (`workbench/cmapi/mayday-plants/`), builds each brief with `make_brief.py` and checks it with `brief_check.py --plants`.
- `run-pair.sh` with `DRAFT_REPO=ephico2real2/cmapi`, `CODEX_MODEL=gpt-6.2-astra` (complex) or `gpt-6.1-sol` (simple), and `LABELS=review:fable`.
  Round 1 builds and round 2 reviews adversarially; the result is a draft PR.
- Opus (the coordinator) rules from `status.txt` and round 2's `verdicts.md`, checks each round against its plants, runs the
  database and socket tests the sandbox cannot, rewrites the PR body (who wrote what, the ruling), marks it ready and merges on
  green CI at the pinned head. The `review:fable` label marks the PR and issue for a later Fable review. It does not block the merge.

**Merged today by /houston-mayday:**

| Issue | PR | What | Ruling |
|---|---|---|---|
| #417 | #463 | The cluster status `environment-not-served` (never set) removed; a test checks that every listed status has a producer. The 422 problem code is unchanged | Round 2's F1 refused and reverted: its test started a nested pytest that exits on the shared test-database lock |
| #456 | #462 | A cluster import finding is logged once when it appears and once when it clears; recovery at info; first import silent; serialized transitions | F1 to F3 accepted. CI then failed: the tests used `capture_logs()`, blind once structlog caches the logger (`cache_logger_on_first_use`, `core/observability.py:86`). `d351e5e` (Codex sol) replaces the registry's `log` instead |
| #403 | #464 | `statusSince` on `GET /api/v1/clusters` (additive); Capacity and Policies date a disconnected cluster from it | F1, F2 accepted. CI then failed #393's test: F2 moved `read_quotas` off `quota_watch`, the `cache()` seam. `b3980fd` (Codex sol) restores main's lookup |

**Also merged since run 25:** #443 (records), #453 (#424, Git clients' response bodies redacted), #455 (#421, a list without
`items` no longer retires every cluster), #457 to #460 (the Codex review of Git delivery, #444 to #452).

**Next, in order:**
1. Merge #465 (#396, #397).
2. Mayday jobs, one at a time, each `review:fable`: #398 (CRC's import token, astra), #407 (portal paged tabs, astra),
   #429 and #244 (cluster-configs CI and render-on-change, astra).
3. One CRC deploy of everything merged since `b8ee59e`: `down.sh` first, `up.sh` after (renews kind's token).
4. Records after the deploy.
5. Fable reviews of every `review:fable` PR, when the owner resumes Fable.

**Waiting for the owner:**
- the live Claude Docs of docs/01 and docs/02;
- Kyverno audit → enforce, per environment.

**Lessons recorded today:**
- Run the **full** service suite (about 20 minutes, `suite.sh` with no file list) before pushing a mayday branch. Both CI
  failures today were in tests outside the targeted set.
- Test log events by replacing the module's `log`, never with `structlog.testing.capture_logs()`.
- A test must not start a nested pytest: it takes the shared test-database lock (exit 75).
- On this Mac, 6 `test_contract_report_337` tests fail because `workbench/cmapi/ob1-run/venv` has an old `cmapi-tools`
  without `openapi render`. CI passes them. Refresh that venv before relying on a local full run.
- Codex's sandbox cannot create `.git/index.lock` in a worktree. The coordinator commits its change unchanged and says so.

## Resume here: 2026-11-19, 03:30Z (superseded by the section above)

Read this, then the 2026-11-18 sections below it. Sections 4 and 6 to 10 of 2026-11-16 still hold.

| Item | State |
|---|---|
| `main` | `b8ee59e` (PR #435) |
| CRC | Runs `b8ee59e` (OB1 run 25, `workbench/cmapi/ob1-run25/`): 25 proof lines passed; keycloak-0 0 restarts; cmapi's Kyverno bundle applied (31 dev, audit, pass 84) |
| kind | `KIND_CMAPI_TEST` (rnd): Kyverno and 31 rnd policies; import with `tlsServerName: host.crc.testing`. **Token renew by 2026-11-24T17:30Z** (`up.sh <cmapi-cluster-configs checkout>`); every CRC deploy runs `down.sh` first and `up.sh` after |
| Cluster TLS trust | Live (#434): `insecure` allowed per environment by `instance.clusterTLS.environments.<env>.insecureSkipTLSVerify` (default false, prod may set it); `caData`; else the system store + `CMAPI_TRUSTED_CA_FILE` (the OpenShift-injected `cmapi-trusted-ca`, 147 CAs, plus an operator ConfigMap) |
| diagram-kit | #64 (contracts first) and #72 (light only) merged by the owner |

**Next, in order:**
1. Records: issue work tags set by the `/agile` rules (2026-11-19).
2. #424 (SEC: Git client response bodies unredacted) and #421 (a list answer without `items` retires every cluster).
3. A Codex review of #288/#299 (Git delivery code, Opus-only so far).
4. A story: #21 snapshots, for the Capacity tab's usage side.

**Waiting for the owner:**
- the live Claude Docs of docs/01 and docs/02;
- Kyverno audit → enforce, per environment (now possible).

**Lessons recorded:**
- A merge waiter pins the reviewed head and needs every check passed.
- fstrim and image builds are #157 load; resume without rebuild when the images are already pushed.
- Codex runs with its working directory inside the review folder (its sandbox writes only there).

## Resume here: 2026-11-18, 18:00Z (superseded by the section above)

Read this, then the 07:00Z section below it. Sections 4, 6 to 10 of 2026-11-16 still hold.

| Item | State |
|---|---|
| `main` | `721cb64` (PR #423) |
| CRC | Runs `721cb64` (OB1 run 24, `workbench/cmapi/ob1-run24/`). Steps through 22 passed; **step 23 stopped** on `cmapi-db-1` restarted at 15:44:56Z, before the run, caused by the cleanup's fstrim (#157). The stop file is in place, the step-13 backup is kept, and steps 24 and 25 are not run. The owner chose: fix the proof (#425, PR #426), then resume from step 12 |
| kind | **Down** (down.sh ran in run 24). `up.sh` after step 24 re-imports it and renews the 7-day token |
| Portal | All nine tabs on the API; story #302 closed by the owner |
| diagram-kit | #64 (contracts first) and #72 (light only): CI green, the owner merges |

**Next, in order:** review and merge #426; resume run 24 from step 12 (new watch), then 22, 23, the live checks (Quotas
pager, Capacity, Policies, clusters, Swagger), 24, `up.sh`, 25. Then the open defects (#396, #397, #398, #403, #407, #410,
#417, #418, #421, #424) and the #413 leftovers (docs/08 section 4, a not-imported sample, figures #418 and #209).

**Lessons recorded today:**
- A merge waiter checks every check passed and pins the reviewed head.
- fstrim of the Podman VM is heavy load for CRC (#157).
- Agents run local tests only through `suite.sh`, never whole suites.

## Resume here: 2026-11-18, 07:00Z (superseded by the section above)

Start the next session as section 1 of the 2026-11-16 state says, then read this section, then the earlier 2026-11-18
section below it, then "State on 2026-11-17". Sections 4, 6 to 10 of 2026-11-16 still hold.

### Where it stands

| Item | State |
|---|---|
| `main` | `1537977` (PR #400) |
| CRC | Runs `1537977` (OB1 run 23, `workbench/cmapi/ob1-run23/`). `crc-proof.sh` all passed (25 lines, now with the reader's report and node grants). Alembic 0006; 4 pods Ready, 0 restarts; keycloak-0 0 restarts (one probe timeout during the image build). `kyvernoVersion` v1.20.0 (#388 fixed live) |
| Portal | **All 9 tabs on the API.** Capacity added (#400): CRC's group shows 56 % CPU and 45 % memory against the simulated 64 cores / 256 Gi, the node's 7.8 cores / 19.1 Gi beside it, every figure matching `oc`. Policies (#384) shows CRC "off the bundle" (cmapi's bundle is not delivered) and kind "Kyverno not installed" |
| kind | `cmapi-test` on this Mac (podman), imported into CRC as `KIND_CMAPI_TEST`: environment `rnd`, `writes: false` (#399). Reached at 192.168.86.110:16443; pf anchor `com.apple/cmapi-kind` blocks the port from the LAN (lab-only, lost on reboot). **Token expires 2026-11-25T06:22:52Z: rerun `deploy/kind-import/up.sh` before 2026-11-23T20:46Z.** Every CRC deploy runs `down.sh` first and `up.sh` after (owner) |
| Kyverno on CRC | v1.20.0, scoped to managed namespaces, failing open (#386) |
| Agents | None running |

### What was done since the earlier 2026-11-18 section

| Issue | PR | What | Proof |
|---|---|---|---|
| #388 | #390 | `KYVERNO_VERSION` as a global ARG, so the image sets `CMAPI_KYVERNO_VERSION` | CI; podman build; review OB3 (no findings); CRC run 23 |
| #387 | #391 | The CRC proof reads the served report group and checks the reader may list each report kind | CI; review OB3 (1 fix); CRC run 23 |
| #393 | #394 | Unknown or refused committed quota is `unknown`, never `fits` and fresh; `cpu`/`requests.cpu` counted once | CI; review OB3 (1 fix) |
| #302 (Capacity) | #400 | `GET /api/v1/capacity` and the tab: a ledger per cluster, a Node watch, simulated basis with allocatable beside it, stale kept and marked. Two designs, arbitrated, with the owner's four answers (`docs/reviews/2026-11-18-issue-302-capacity/`) | CI; review OB3 (4 findings fixed: a cache-rebuild race that read fits, three config faults); CRC run 23 |
| #15 | #399, #401 | kind imported as a second cluster (scripts `deploy/kind-import/`); docs/02 says the hub-to-cluster network path is a site prerequisite cmapi consumes | CI; review OB3 (3 fixes); run 22 and 23 |

**The owner's decisions (2026-11-18):** Capacity's check stays on `simulatedCapacity` with allocatable shown beside it;
`nodes` read for cmapi-reader everywhere; ship Capacity live without snapshots (#21 later); stale clusters keep their
last figures, marked; kind reached on the LAN with a pf rule; delete kind before each CRC deploy, re-create after.

### What is next, in order

1. **#347** (portal CI flake, three re-runs in two days) and #392.
2. Story #302: all its tabs are live; the owner approves its closure (proof per criterion on the issue).
3. Open defects: #395 (pin substring), #396 (TLS mode and expiry in `/clusters`), #397 (probe route), #398 (CRC's import
   token never expires), #402 (Policies double read), #403 ("unreachable since"), #404 (empty not-imported detail), and the
   earlier list (#353, #357, #360 to #364, #372, #373, #375 to #377, #379 to #381); deferred #382, #383; follow-up #365.
4. Deliver cmapi's policy bundle to CRC (not asked yet).

## Resume here: 2026-11-18 (earlier; superseded by the section above)

Start the next session as section 1 of the 2026-11-16 state says, then read this section, then "State on 2026-11-17"
below it for the #328 program and the owner's decisions of that day. Sections 4, 6 to 10 of 2026-11-16 still hold.

### Where it stands

| Item | State |
|---|---|
| `main` | `6565d9d` (PR #384). CI green on its head 39aa002 (one re-run of `portal-ui` for the known flake #347) |
| CRC | Runs `6565d9d` (OB1 run 21, `workbench/cmapi/ob1-run21/`): `crc-proof.sh` all passed (24 lines); alembic 0006; 4 pods Ready, 0 restarts; keycloak-0 0 restarts. The run stopped once at step 22 when realm `corp` missed one 3 s watch poll during the rollout (no restart, snapshot equal to s0; evidence on #157); the owner said resume |
| Kyverno on CRC | **Installed** 2026-11-17 at the owner's request: v1.20.0 (chart 3.10.0), namespace `kyverno`, `deploy/kyverno/crc-values.yaml`, docs/13 "Kyverno" (#386). Webhooks see only `cmapi.net/managed=true` namespaces and fail open; background and cleanup controllers off. cmapi's policy bundle is **not delivered** to CRC, so the Policies tab shows CRC "off the bundle", 31 missing |
| Portal | 8 of 9 tabs on the API: Policies added (#384). Capacity is next (#302) |
| Agents | Implementer on #388 and #387 (two PRs) |

### What was done on 2026-11-17 and 18

| Issue | PR | What | Proof |
|---|---|---|---|
| #337 | #370 | Report-only API contract diff of a Helm values change (`cmapi-tools openapi render`, reusable workflow) | CI; review OB3 |
| #366, #374 | #378 | Operators protect a namespace from deletion from the portal (`namespaces:protect`, `/me` operator, `protectedBy`); removing protection needs approver-platform; `do-not-delete` operator-only | CI; review OB3; CRC run 20 (req-20261117-0004 and -0005, cluster-configs PRs #15, #16; delete refused 422 `namespace-protected`) |
| #302 (Policies) | #384 | `GET /api/v1/policies/results` and `/rejections`; the Policies tab; migration 0006 `policy_rejections` (username only, retention 90 days by default); `cmapi.net/policy-digest`; the `Policy` schema. Two designs, arbitrated (`docs/reviews/2026-11-17-issue-302-policies/`) | CI; kind with Kyverno v1.20.0 audit; review OB3 (4 findings, fixed: unknown counts null, chunked list memory 276 to 71 MiB, drift totals, an unused gauge); CRC run 21: results, a stored refusal (username only), the tab at 1440 and 390 px |
| — | #386 | Kyverno on CRC: the values and what was measured | CRC: a no-op probe policy showed the scoped, fail-open webhook |
| #385 | in #384 | A migration test named 0004 "a later release" | CI |

**The owner's decisions:** `do-not-delete` is operator-only; the contract report runs where the Helm values live; stored
refusals show the username only (never email, employee ID or justification); deploy, then Policies; install Kyverno on CRC.

### What is next, in order

1. #388 (the image's `CMAPI_KYVERNO_VERSION` is empty, so the pinned-CLI start check is off and the tab says no CLI is
   pinned) and #387 (docs/13 claims a proof line `crc-proof.sh` lacks): PRs being built, then review, merge, deploy.
2. **Portal slice 4, Capacity** (#302).
3. Deliver cmapi's policy bundle to CRC through cluster-configs, so the Policies tab shows real results (not yet asked).
4. Open defects: #347, #353, #357, #360 to #364, #372, #373, #375 to #377, #379 to #381; deferred: #382, #383; follow-up #365.

### Waiting for the owner

- The live Claude Docs of docs/01 and docs/02: this account cannot read them. Open the doc's "Start chat", or share edit
  access. docs/02 still says "cmapi-operator and above" and lacks `do-not-delete`.

## State on 2026-11-17 (superseded by the section above)

Start the next session as section 1 of the 2026-11-16 state below says, then read this section first: it replaces that
state's sections 2, 3 and 5. Sections 4, 6 to 10 still hold, with the changes listed here.

### Where it stands

| Item | State |
|---|---|
| `main` | `7ba5d78` (PR #368). CI green on every merge of the day (last full run on `main`: c7ab6c4, all 7 jobs) |
| CRC | Runs `7ba5d78` (deployed 2026-11-17, OB1 run 19, `workbench/cmapi/ob1-run19/`): `crc-proof.sh` all passed; Swagger shows the required keys; `/api/v1/metadata-keys` 200 + 304; the New namespace form refused a Team DL outside the domain on its field and created `cmapi-live-f` (req-20261117-0003, cluster-configs PR #14, synced in 25 s). keycloak-0 0 restarts. **Kyverno is not installed on CRC**, so the audit default and PolicyReports are not checked there, and the cluster-configs bundle was not re-rendered. The first build stalled the node for 29 s (#157) and a test user was locked during the proof (#373) |
| Portal | 7 of 9 tabs on the API: Expiration added (#318). New namespace now builds its fields from the instance's metadata config (#336). Policies and Capacity are next (#302) |
| Agents | #337 (step 7 below): two designs, then the build |

### What was done on 2026-11-17: required labels and annotations (#328)

The owner asked for #328 to be designed before it was built (2026-11-16). Two designs, one model family (Codex out of
quota until 2026-11-18 14:09, Fable paused), arbitrated in `docs/reviews/2026-11-16-issue-328/arbitration.md`. Built in
this order, each PR reviewed by OB3 (Opus 5.5), each review's fixes applied unchanged after the coordinator re-ran their
tests, each review record in `docs/reviews/`:

| Step | Issues | PR | What it does |
|---|---|---|---|
| 1 | #330, #331 | #340, #341 | The validator refuses a key with an empty prefix (`/foo`); `*` no longer admits unprefixed keys. A held invalid key can still be removed |
| 2 | #335 | #339 | Helm values `metadata:` (the whole file), with `values.schema.json`; `configFiles` stays as a fallback |
| 2b | #342, #343 | #344 | **Kyverno defaults to audit** (owner); cmapi's own checks refuse, with or without Kyverno; the 422 lists Kyverno's findings beside cmapi's |
| 3 | #332, #338 | #346 | The loader refuses patterns outside the common subset of Python `re`, RE2 and ECMA-262; one anchored pattern shared by validator, Kyverno and schema; config shape checks |
| 4 | #328, #334 | #350 | Required labels and annotations are schema fields in `/openapi.json` and Swagger, generated per instance; generated examples; 14 accepted breaking lines |
| 5 | #333, #345, #356 | #354 | Kyverno covers allowOther prefixes and limits; no false `fail` in background scans; policy names within 63; OLM and Pipelines prefixes reserved |
| — | #348, #349 | #351, #352 | Values matched with RE2 (linear time; `google-re2` added); curl samples accepted |
| — | #358 | #359 | Company profile (owner): line of business free text, critical level 0 to 6, mnemonic 3 or 4 letters |
| — | #355 | #367 | YAML written so Kubernetes tools read every string as a string (`y`, `n`, timestamps) |
| 6 | #336 | #368 | `GET /api/v1/metadata-keys`; the New namespace form from the config, pattern checks in a Web Worker |
| 7 | #337 | open | A report-only contract diff in the cluster-configs CI |

**The owner's decisions of 2026-11-17** (also in memory):

- Kyverno runs in **audit** by default for its detail; cmapi's core logic holds every rule and refuses, and works with
  `policy.engine: none`. The portal's Policies tab shows the clusters' PolicyReports (#302).
- The keys are set through the Helm values (#335). The read path for Git hosts is **Git with the bot's key** (host-neutral);
  a PR adapter per host is still needed for open, status and merge (section 6, item 1 of the 2026-11-16 state: decided).
- Sample values (`abc`, `amgsst`) are examples, never rules. Company LOB is free text, CL 0 to 6, mnemonic 3 or 4 letters.
- The five #328 questions: accept the 14 breaking lines; the portal form from the config; refuse a required key with no
  `example`; a report-only diff in the config repo's CI; clients generated from each instance's own `/openapi.json`.

### What is next, in order

1. **#337** (PR #370, in review) and **#366** (protect from deletion, building; with #374), then deploy them to CRC.
2. **Portal slice 4, Policies** (#302 and its comments: PolicyReport results, plan-time Kyverno warnings, the mode of each
   environment), then **Capacity**.
3. **Open defects from today:** #347 (portal flake: PatternFly tab scroll-button transitions), #353 (a lone surrogate in an
   annotation with no rule), #357 (CI does not build the API image), #360 to #364, #362 (the "any value" wording).
4. **Follow-ups:** #365 (editor for allowOther keys), #366 (operator flag on `/me`, owner to confirm).
5. Then the 2026-11-16 list from its item 2 on: portal fixes, Git follow-ups, GitLab and Bitbucket adapters, the queue.

### Waiting for the owner

- The live Claude Docs of docs/01 and docs/02 (the exports in the repository are updated; the live docs are not in this
  account's list or not owned by it).
- #366: may operators set `cmapi.net/protected` from the portal?
- Titles for the company keys in the New namespace form (none today; the keys show).
- From 2026-11-16: the leaner process (mutants once per slice), a Gitea validation, `cmapi-live-a`'s expiry.

## State on 2026-11-16, 19:33Z (sections 2, 3 and 5 superseded by the section above)

### 1. How to start the next session

Open Claude Code in `/Users/olasumbo/gitRepos/cmapi-design` and say:

> Read `HANDOVER-AND-RESUME.md` and `build-tracker.md` on `main` (section "Resume here"), check the state with the commands
> in section 9, then continue with the first item of section 5.

The coordinator's memory notes in `~/.claude/projects/-Users-olasumbo-gitRepos-cmapi-design/memory/` load by themselves and
hold the standing rules (section 7).

### 2. Where it stands

| Item | State |
|---|---|
| `main` | `0c0fcb0` (PR #316). No PR open except this records PR, which merges with this update |
| CRC | cmapi `525ca27` runs on CRC: api, worker, portal and cmapi-db. `crc-proof.sh` passed there. keycloak-0 has had 0 restarts since the CR fix of 2026-11-15 |
| Git delivery | The Git layer over **SSH** with the bot's key, plus a thin PR adapter for GitHub (#286). Proven with real requests |
| Portal | 6 of 9 tabs on the API and live on CRC: Requests, New namespace, Approvals, Workflow, Quotas, KPIs. Expiration, Policies and Capacity are next (#302) |
| Agents | None running |

### 3. What was done (2026-11-14 to 2026-11-16)

**The full request flow on CRC.**
- #269 (full flow, apply mode) and #270 (BUG-64, backup) merged.
- #272 (BUG-65, one test session per database) merged.
- #277 (crc-proof fixes: BUG-67, BUG-68, BUG-70) merged.
- docs/13 was run from a clean start (OB1 run 9), and every proof passed on CRC.

**Git delivery redesigned (#286).**
- **Why:** the owner's fine-grained token could not read GitHub's Checks API (BUG-69 #279), so the bot's PRs never merged. The owner then said Git delivery must not depend on GitHub features: "a token or ssh keys", always a PR, never a push to `main`.
- **Design:** Fable 5.2 and OB1 (Opus 5.5) each designed it alone, and the coordinator arbitrated. The record is the comment on #286 and `docs/reviews/2026-11-15-issue-286/`.
- **What was built:** PR #288 (`21a7f47`):
  - a Git layer: a bare partial clone in an emptyDir, a worktree per request at `<workdir>/<cluster>/<requestId>`, and branch `cmapi/<cluster>/<requestId>`;
  - a thin PR adapter;
  - apply before merge, with the new states `applied` and `merge_failed`;
  - the sweeper and `git_reconcile`;
  - structured `git_op` logs.
- **Review:** 7 findings fixed, among them a cancel-versus-merge race. BUG-74 #293 (job-claim order) was found and fixed while validating.
- **Superseded:** #285 (GitHub statuses) and cmapi-cluster-configs#3 are closed.

**The identity is the machine user `cmapi-git-bot`.**

| Object | Holds | Mounted in |
|---|---|---|
| Secret `cmapi-git-bot` | The API token, for the PR only | api and worker |
| Secret `cmapi-git-bot-ssh` | `kubernetes.io/ssh-auth`, the private key | worker only |
| ConfigMap `cmapi-git-bot-known-hosts` | GitHub's ed25519, ecdsa and rsa host keys | worker only |

- The owner made the SSH key on 2026-11-16, and CRC has used SSH since PR #299 (`0a805b0`). Fingerprint: `SHA256:R7En1nykzQtx0+6OB46qo+i8B+PK1m3ZaWmkMRPw+gY`.
- `/etc/passwd` stays `0644`: CRI-O adds the pod's UID. nss_wrapper is used only where no runtime adds it.

**The portal.**
- **Slice 2** (#300, PR #305): New namespace, Approvals and Workflow. The review found 4 defects, among them the Idempotency-Key per body and a submit of an unplanned form.
- **Slice 3** (#301, PR #313): Quotas and KPIs. The review found 1 defect: a 412 did not lead to reading the namespace again.
- Both are proven live on CRC with Playwright through the real Keycloak sign-in. Screenshots: `cmapi-portal-ui/screenshots/slice-2-crc/` and `slice-3-crc/`.

**Docs.**

| Doc | What it holds |
|---|---|
| docs/19 | How to connect cmapi to Git: bot, token, SSH, known_hosts, rotation, troubleshooting |
| docs/14, "Who a request is from" | The RBAC figure, in its light theme; the test users |
| docs/04 | How to choose an Idempotency-Key |
| docs/18 | Where `emailDomains` is set |
| Figures | `docs/diagrams/git-delivery/` and `docs/diagrams/rbac-identity/` |

**Requests proven live on CRC.**

| Requests | Config repo PRs |
|---|---|
| req-20261115-0001, req-20261115-0003 | #5, #6 |
| req-20261116-0001, over SSH | #7 |
| req-20261116-0002 to req-20261116-0005, from the portal | #8 to #11 |

Namespaces `cmapi-live-a` to `cmapi-live-e` exist and are the proof; leave them.

**Cleanup.**
- Secret `cmapi-git` (the owner's token) is deleted; nothing read it.
- 72 merged branches deleted. The two closed-PR branches are kept at `refs/pull/285/head` and `refs/pull/165/head`.
- 78 worktrees removed.

### 4. The direction (decided, do not reopen)

**Delivery.**
- Plain Git with one credential: SSH key or token.
- A thin PR or MR adapter for each host: GitHub (built), Gitea (built), GitLab and Bitbucket (next).
- Always a PR; cmapi never pushes to `main`.
- The gate is cmapi's own plan-time kubeconform and Kyverno checks plus approval. Host CI is off by default; when on, cmapi reads commit statuses only, never GitHub's Checks API.
- In apply mode: apply, confirm by a read, then merge, pinned to the applied sha. In argocd mode, and for every delete: merge first.

**Storage.** Git stays the store of desired state; PostgreSQL holds the workflow state. The owner's alternatives were weighed and rejected for now: a PVC, PostgreSQL as the store, OCI, SeaweedFS.

**Identity.**
- A person submits as themselves: the request records the token's `sub`, username and employee_id.
- A tool submits for a person with `onBehalfOf` (built: `core/identity/checks.py`). A person sending `onBehalfOf` is refused.
- Token exchange (RFC 8693) is the proposed stronger form.

**Diagrams.** diagram-kit `/visual`, rendered with `~/gitRepos/diagram-kit/.venv/bin/diagram-render`. Both themes are rendered, and **only the light theme is embedded and published** (the owner's choice).

### 5. What is next, in order

1. **Portal slice 4 (#302): API first, then each tab.** Start with **Expiration**: a list endpoint of namespaces by expiry, since `expiresAt` and `:extend` exist. Then **Policies** (Kyverno results and rejections), then **Capacity** (the snapshots). Each endpoint goes through the contract gate: OpenAPI, samples and docs/04.
2. **Portal fixes:** #309 (the text says Argo CD and host CI in apply mode), #307 (the Workflow scenario button keeps its first status), #306 (ProgressStep warnings).
3. **Git delivery follow-ups:** #289 (the chart mounts the Git layer), #273 (the chart's CRC values), #294 (BUG-75, event timestamps out of order), #295 (BUG-76), #291 (BUG-72, a mode switch stalls), #292 (BUG-73, the citation tool).
4. **GitLab (#286 PR-B), then Bitbucket (PR-C).** The owner's read-path decision (section 6, item 1) comes before PR-B.
5. **The rest of the queue:** #282 (Idempotency-Key in Swagger, CLI and SDK), #283 (Swagger token lifetime), #276 (PERF, the first plan took 27.7 s), #287, #303, #304, #310, #311, #312, #314, #315, #225 (2-3 replicas), #228, #236, #237, #248, #249, #256-#260, #263-#266, #207-#209, #200.

### 6. Decisions only the owner can make

1. **Before PR-B:** how the API pod reads the repository at plan time. Through Git with the bot's credential (host-neutral), or each host's read API (as PR-A does for GitHub).
2. **#290:** a revert of a change that was applied and never merged. Fable proposed a `restore_apply` job.
3. **Real people.** Realm `cmapi`'s LDAP users filter `(uid=cmapi.*)` admits only the 13 test users. Widening it to the real directory is a decision for each environment.
4. **The bot's own token.** Secret `cmapi-git-bot` still holds a copy of the owner's token, so PRs show `ephico2real2` as author; the commits already name `cmapi-git-bot`. To change it, make a fine-grained token as `cmapi-git-bot` (docs/19, section 2) and load it with that section's `oc apply` lines.
5. **Earlier, still open:** diagram-kit PR 64 (merge), #227 (branch protection needs GitHub Pro), the KPI targets, #149, #150, #167, 409 vs 422 for an idempotency replay, the problem type host.

### 7. Who does what, and how a change ships

| Role | Who |
|---|---|
| Implementer | Opus 5.5 at `high`, a fresh background agent per task, briefed with the issue, files and claims |
| Designs | Two independent designs (two model families when Fable has quota), arbitrated by the coordinator, for anything structural |
| Review | One adversarial review per PR, by a separate Opus 5.5 or Codex (interchangeable). Every finding has its full fix as a patch and a test that fails before and passes after |
| Coordinator | Applies the accepted fixes, runs the before and after tests itself, merges when GitHub CI is green on the exact head, deploys to CRC through a briefed agent, and keeps these records |
| Docs | Sonnet 5.5 |

Fable is paused unless the owner asks; the owner used it on 2026-11-15 with about 6% of its quota left. CI is **GitHub Actions only**; local CI is not used.

**Standing rules, learned this session (also in memory):**
- Don't idle on an owner input: check what it really gates, and run the rest.
- Never a "quick fix" on a hypothesis: find the true layer, and run the proof before and after.
- Before a delete, prove it is merged. A branch from a closed PR is listed, not deleted.
- Order-dependent tests mean the full suite is not proof: run the failing files alone.
- Never trust a tool's "fix" hint: read the diff. `doc-citations --write` once recorded the wrong text.
- Read a figure's PNGs before calling it done, and render with the kit's own renderer.
- No Co-Authored-By or "Generated with" lines, ever.

### 8. Rules that do not bend

- **CRC is shared.** Change only realm `cmapi` and `cmapi-*` LDAP entries. Test namespaces on CRC use `cmapi-` names only.
- Never restart the VM or a shared service. Delete only what cmapi created.
- No secrets in git, logs or command lines: tokens go from the clipboard on stdin, and passwords from the Secret on stdin.
- TLS verification is always on.
- A permission refusal stands.

### 9. Check the state before acting

```bash
git -C /Users/olasumbo/gitRepos/cmapi-design fetch -q && git -C /Users/olasumbo/gitRepos/cmapi-design log --oneline -1 origin/main
gh pr list --state open
curl -s https://cmapi.apps-crc.testing/api/v1/version          # expect commit 525ca27 (or newer, if deployed since)
oc get pods -n cmapi
oc get pod keycloak-0 -n keycloak -o jsonpath='{.status.containerStatuses[0].restartCount}'   # 0
oc logs deploy/cmapi-worker -n cmapi | grep -m1 ssh_key_fingerprint
```

**Where things are.**
- **The repository:** `/Users/olasumbo/gitRepos/cmapi-design` (`main`).
- **The records:** these three files, on `main`.
- **Agent notes and logs:** `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run*` and `review-*`. The CRC runs are `ob1-run9`, `ob1-run11`, `ob1-run13` and `ob1-run15`; each has a `resume.md`, `run.sh` and `live-ui.mjs`.
- **The test DB lock:** `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run5/tools/suite.sh` (one service-suite session at a time).
- **The diagram renderer:** `~/gitRepos/diagram-kit/.venv/bin/diagram-render`.

### 10. The stories (#13 to #29) and which need a Fable review

A story closes only on the owner's approval, with the proof for each acceptance criterion (CLAUDE.md). None is closed yet. Read from GitHub on 2026-11-16: the sub-issue counts are closed of total.

| Story | Subject | Sub-issues | Built and proven | Left |
|---|---|---|---|---|
| #13 | Production service, durable request store | 20 of 23 | Service, PostgreSQL (CNPG), API docs; CRC | 3 open sub-issues |
| #14 | OIDC identity, directory, roles | 5 of 8 | PKCE, client credentials, `onBehalfOf`, RBAC; 13 LDAP users on CRC | Realm users filter for real people (owner); token exchange (proposed) |
| #15 | Cluster imports, live read endpoints | 0 of 0 | Not started as a story | Not broken into issues |
| #16 | Telemetry and KPI baseline | 6 of 7 | `/admin/kpi`, KPIs tab live on CRC | #147 (30-day window), #311; KPI targets (owner) |
| #17 | Namespace plans, metadata, submission | 2 of 2 | Plans, metadata (#215), LimitRanges; New namespace tab live | Owner approval to close |
| #18 | Approval decisions, protected Git delivery | 6 of 13 | Approvals; Git delivery #286 live over SSH; #61 closed today | #286 PR-B and PR-C, #289-#291, #59, #60, #200, #227, #228, #249 |
| #19 | Worker recovery, Argo sync, history | 1 of 2 | Recovery, apply mode on CRC | Argo CD mode not run on CRC (Wave 5) |
| #20 | Signed-in portal | 12 of 23 | 6 of 9 tabs live on CRC | #302 (slice 4), #304, #306, #307, #309 and older UX items |
| #21 | Capacity snapshots, safe placement | 0 of 2 | Capacity snapshots in the API | #303 (placement API), the Capacity tab (#302) |
| #22 | Quota plans, usage, auto-approval | 4 of 7 | Quota plans, custom tier, Kyverno modes; Quotas tab live | #211, #232, #287, #310 |
| #23 | ServiceAccounts, allowlisted grants | 0 of 0 | Not started | Not broken into issues |
| #24 | ServiceAccount token issuance | 0 of 0 | Not started | Not broken into issues |
| #25 | Expiration, controlled deletion | 0 of 0 | `:extend` and prune exist | Expiration list API and tab (#302) |
| #26 | Adoption, policy visibility, recoverable ops | 0 of 3 | Adoption design (#239, Fable-reviewed) | Build (#250 D17 and on), Policies tab (#302), #290 |
| #27 | Reports, efficiency, notifications | 0 of 0 | Not started | Not broken into issues |
| #28 | Releases, SDK, operational readiness | 0 of 7 | Plain manifests and CRC runbook (docs/13) | Chart (#289, #273), CLI and SDK, #225 replicas |
| #29 | Rightsizing, placement backtests | 0 of 0 | Not started | Not broken into issues |

**Which work needs a Fable review.** CLAUDE.md wants a second model family on each change. Fable reviewed everything up to PR #245 on 2026-11-14, and #286's design (D1, D2 and D4). Since then, Codex reviewed #247 and #255, which counts as a second family. **Opus alone reviewed work that Opus wrote** in the PRs below, so those have had no review from another family. Ranked by risk:

| Rank | Story | PRs (Opus wrote, Opus reviewed) | Why | Size |
|---|---|---|---|---|
| 1 | #18 (#286) | #288 Git layer and PR adapter (+5,661 lines), #299 SSH | Delivery to Git and to the cluster: the lock, `applied` and `merge_failed`, leases, secrets handling. Fable reviewed the design, not the code | Large |
| 2 | #20 and #22 | #305 portal slice 2, #313 portal slice 3 | Writes from the browser: Idempotency-Key, plan then submit, If-Match. The Opus reviews found 4 and 1 real defects, so another family may find more | Medium |
| 3 | #18 | #269 full flow (deliverer ClusterRole and VAP), #272 test-DB lock | RBAC of the worker on the cluster | Small |
| 4 | #13 and #94 | #270 backup checks, #277 crc-proof | Scripts; proven on CRC many times | Small, low risk |

No Fable review needed: the docs-only PRs (#274, #284, #296, #297, #298, #308, #316), and #247 and #255 (Codex).

**Brief for Fable,** with the precise-artifact rule (CLAUDE.md): give it the exact PR, the file and line ranges, and the claims to confirm or refute. For #288, reuse the 11 claims of the Opus review (`workbench/cmapi/review-288/`); Fable checks them independently and adds its own. For #305 and #313, reuse C1-C9 and C1-C8 (`review-305/`, `review-313/`). Every finding needs its full fix and a test that fails before and passes after. Fable's quota was about 6% on 2026-11-15: run rank 1 first, narrowly, writing findings to a file as it goes.

---

## History: the states before 2026-11-16 (superseded by "Resume here")

## State on 2026-11-15, 05:00Z: read this first

This section supersedes the older sections below where they differ. In particular, "Local CI is the merge gate" and the #157 stop are no longer in force.

**The current rules** (the owner, 2026-11-14):

| Rule | The owner's decision |
|---|---|
| CI | GitHub Actions is the only CI and the merge gate ("Ok great dont use it", "Use github"). Local CI is not used. PR #165 was closed for this reason |
| Who codes | Opus 5.5 at `high` codes and designs. Fable is stopped |
| Review | One adversarial review per PR, by Codex `gpt-6.1-sol` or a separate Opus 5.5 at `high`. The two are interchangeable. The reviewer writes the full fix and a test for each finding |
| Applying the review | The coordinator applies the review's fixes, validates them with a before run and an after run, and merges ("You do the change yourself after 1st review and validate it") |
| Docs | Sonnet 5.5 writes the docs |

**Keycloak (#157).** With the owner's approval, the shared Keycloak CR now has a 1000m cpu request and a liveness `failureThreshold` of 10. Before that, the liveness probe killed Keycloak when CPU starved it. The patch restarted Keycloak once for every realm. Since then, keycloak-0 has had 0 restarts through OB1 run 9's steps 0 to 10, measured before and after each step. Add these CR values to any repository that manages that CR.

**Merged since the table below:**

| PR | Commit | What |
|---|---|---|
| #234 | `72b5094` | #215: configurable metadata |
| #240 | `20500db` | #213: Kyverno engine and mode for each environment, CLI v1.20.0 |
| #245 | `6f8ec6d` | #212: Kyverno policies rendered from the configuration |
| #239 | `62cbffd` | The adoption design for story #26 (D1 to D19), docs/02 "Adoption", the figure |
| #238 | `7ddfd10` | #226 PR-A: the nginx front door. Closes #206 |
| #247 | `f11d2b4` | #226 PR-B: the front door in the plain manifests. The Route has `haproxy.router.openshift.io/timeout: 130s`, because nginx's worst case is 2 tries × (2 s + 60 s) = 124 s |
| #255 | `1e67e64` | #253: separate CPU and memory LimitRanges (`<ns>-limits-cpu`, `<ns>-limits-memory`). The storage LimitRange is off by default and turned on by `storageLimitRange.enabled: true`. The review's F1 to F5 are applied, with tests |
| #254 | `9407d8e` | Docs pass: `docs/18-configuration.md`, data-model columns. The gaps it found are filed as #256 to #260 and #263 to #266 |
| #270 | `379dea8` | BUG-64 #268: the backup's checks read the dump to its end, so `oc exec` ends cleanly on CRI-O |
| #269 | `a91ffdc` | #267, #97: the full request flow on CRC (GitHub, `writes: true`, `delivery.mode: apply`), a least-privilege `cmapi-deliverer`, and a separate CA trust for the Git provider. The review's F1 is applied by the coordinator: its test went from 1 failed to 1 passed, and the full service suite passed 897 |
| #272 | `08f7fe5` | BUG-65 #271: one service-test session per database, by an advisory lock. A second session exits with 75. The review's five fixes are applied by the coordinator: its test went from 5 failed to 7 passed. The proof rows were run again and their logs saved in `workbench/cmapi/ob1-run8/logs/` |
| cmapi-cluster-configs#1 | (merged) | The config repository's CI posts `ci/kubeconform` and `ci/kyverno` |

**CRC: OB1 run 9, on `main` 08f7fe5** (`workbench/cmapi/ob1-run9/resume.md`, run from the worktree `workbench/cmapi/crc-run9`):
- **Rollback.** Run 8's objects stopped step 3. The coordinator ruled for a clean slate, so OB1 ran `deploy/crc-rollback.sh --yes` (exit 0). It removed only cmapi's objects, plus the 13 test users, the 10 groups and their Secret from LDAP. The digest of the rest of the directory, `e924078d4c39`, was the same before and after. The other realms showed no difference.
- **Steps 0 to 10** of docs/13 then passed on the empty slate, with images `cmapi@sha256:ef422cd1…` and `cmapi-portal@sha256:0bc6a847…`.
- **Step 11 waits for the owner** to load Secret `cmapi/cmapi-git` (key `token`). The token is fine-grained, for `ephico2real2/cmapi-cluster-configs` only, with an expiry. Its permissions are Contents RW, Pull requests RW, Commit statuses RW, Checks R and Metadata R. OB1 checks for the Secret every 5 min until 06:35Z.
- **Not run yet:** steps 11 to 25 and all the live tests.

**Filed this round:** #273 BUG-66 (low, Backlog): `deploy/environments/crc.yaml` still names the Gitea stand-in and `delivery.mode: argocd`. Only the Helm path reads it.

**Next:**
1. The CRC run completes, then the live tests: sign-in, Requests, the namespace flows ending in a bot PR and an apply, the LimitRanges with the D19 pod-defaults proof, metadata, Kyverno, KPIs, ReDoc and Swagger, the Route timeout. Each gets a screenshot through the Route.
2. Then the queue: D17 (#250), #228, #225, #236, #237, #220, #248, #249, #256 to #260, #263 to #266, #273, Wave 6, #207 to #209, #200.

**The owner's open items:**
- diagram-kit PR 64 (merge)
- #227 branch protection (needs GitHub Pro)
- the KPI targets
- #149, #150 and #167
- 409 or 422 for an idempotency replay with another body
- the host for the problem type base

## Where these files are

This file and `build-tracker.md` are at the root of the repository, on `main` from PR #89. Keep them current on the working branch. The auto-memory note `project-cmapi-resume-point` points here.

To start the next session, paste this:

> On branch `ldap-rbac-names`, in the worktree `/Users/olasumbo/gitRepos/cmapi-design-crc`, read `HANDOVER-AND-RESUME.md`, `build-tracker.md` and `docs/reviews/2026-11-06-pr112/README.md` in full, then continue from the next action in the tracker. Check the state
> first. Update both documents as you go.

## The goal

Build all of cmapi and deploy it on CRC (OpenShift Local) on this Mac: the service, the portal on the real API, the `cmapi`
CLI and `cmapi-sdk`, with a full end-to-end walk from a clean start and screenshots of the running app.

## State on 2026-11-13, at the end of OB1's run: read this first

OB1 (Fable 5.2) ran as a background agent of the coordinator from about 08:45 UTC on 2026-11-13. It had two stops, and lost nothing at either: from 09:45 to 10:24 UTC (`403 authentication_failed`), and from about 11:45 to 13:53 UTC (Fable's 5-hour usage limit). At each resume OB1 read `git status`, `podman ps`, `pgrep` and the pull requests' checks before it went on. Its resume file is `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/resume.md`, and its reports are in that folder, outside git.

### The shared Keycloak restarted: #157 (PERF-01). The owner decides what comes next

`keycloak-0` was killed at 08:58:42 UTC (exit 137) and ran again from 08:59:37 UTC. OB1's first kind run for #91 was running on this Mac at that time, with other test jobs, at a load average of 13 to 16. OB1 found the restart at 11:10 UTC, in the read-only checks before the CRC run. Later kind runs gave failed probes and no restart. Each realm answered 200 at 11:10 UTC. cmapi wrote nothing to namespace `keycloak`.

As the prompt says for a Keycloak restart, OB1 stopped all CRC work, took no action on Keycloak and reports it. So **the Wave 1 run on CRC did not start.** OB1 also runs no kind cluster on this Mac again. The owner decides two things:

1. Whether the CRC run starts after this restart.
2. How kind proofs run while CRC is up on the same Mac. The options are in #157.

### Local CI is the merge gate, from 14:57 UTC on 2026-11-13

The owner: "use local ci for all work and forget the githiub", and "tell ob1 to use this going forward". The rule is in `OB1-PROMPT.md`, "Local CI is the merge gate". Each pull request that OB1 merged before that time had GitHub Actions green on its exact head. From then on the gate is `act-ci.sh` of `/setup-local-ci`, with each job at exit 0 on the exact head, and the pull request says so.

### What is done

| Item | State |
|---|---|
| PR #112 | Merged as `99093d8`: #118, the second pass by Codex `gpt-6.1-sol` with three fixes (#136, #137, #138), CI green on the exact head |
| The `/agile` sweep | Done for each open issue. Milestones `W1` to `W9`. `issue-register.md` has 0 open issues without a work tag |
| The API documentation of `docs/01` (#127 to #134) | PR #135, merged: tags and groups, curl samples, ETag, `/docs/changelog`, the CI job `api-contract` with oasdiff, `docs.public`, no CDN |
| `docs/14`, `docs/15`, `docs/16`, #141 (BUG-30) | PR #153, merged. Codex read the fix of #141 and found no defect. The figures of `docs/14` and `docs/16` are drawn |
| #139 (BUG-29), #142 (BUG-31) | PR #140 and PR #152, merged |
| `docs/04` and the OpenAPI examples from a run, #154, #155 | PR #156, merged as `30f29bb`. `test_api_samples.py` records a real request and response for each operation, and `docs/04`, Swagger UI and ReDoc show the same ones. The token recipes of the old `docs/04` are in `docs/15` |
| #91 (SEC-04) | PR #158, merged as `513ea67`, CI green on its head. Proven on kind; not on CRC |
| The architecture figures from the mockup | PR #160, merged as `0cd0d57`: five figures, light and dark, in `docs/diagrams/portal-architecture/`, and the system figure in `docs/08`. They say "realm cmapi: not on CRC yet" |
| #87 (BUG-11) | PR #162, merged as `c66a249`: `pr_status` reads check runs, with Codex's two passes ruled in `docs/reviews/2026-11-13-issue-87/README.md`. Proven on a mock of GitHub only (#61) |
| #151 (BUG-36) | PR #161, merged |
| #145, #146, #164 (BUG-32, BUG-33, BUG-39) | PR #163, merged as `48920d5`, GitHub's six jobs green on head `9101c47`. Local CI exit 0 for reference-code, portal-mockup, portal-ui and api-contract (with the #169 fix: "Job succeeded"); service ran natively at `2c628f2` (557 passed); manifests not run locally |
| #148 (UX-02) | PR #168, merged as `290ac5f`, GitHub's six jobs green on `efd2d2d`, `manifests` among them. No local CI (paused). #149 stays open for the owner's choice of the mockup's sample names |
| The KPI review (story #16) | PR #177, merged as `b83391c` (#173 to #176 closed): `docs/17-kpis.md` with 21 KPIs (7 live, 3 built, 11 designed after #171; 7, 4, 10 after #172), each with its question, formula, source, proposed target, alert and status; Rebuild recovery removed with the owner's words, and Docs coverage, Stability, Event-loop health, Validation reject rate and the mixed lead time removed with reasons. `GET /admin/kpi` typed in OpenAPI; `test_kpis.py` ties the response to docs/17 (4 of 5 failed before). Service suite 562 passed natively. Live Claude Docs edited: Design and Architecture rev 165, Technical Design v2 rev 294. Filed under #16: #171 (self-service rate not computable), #172 (drift and namespaces metrics never fed), #173 to #176 (close with #177). The null CPU and memory of the macOS sample is not a bug: macOS has no cgroup v2 files |
| #144 plugins.yaml (OB1 run 2) | PR #180, merged as `8afac6d`, GitHub six jobs green on `bf23abd`; `test_plugins_switch.py` 23 failed on main, 41 pass; service suite 588 passed natively; Codex rulings in `docs/reviews/2026-11-13-issue-144/`. New: `GET /api/v1/admin/plugins`, problem `plugin-disabled`, metric `cmapi_plugin_disabled_total` |
| #143 Spectral lint | PR #188, merged as `da1dfdf` (GitHub green on `3ddc4a1`); its first lint run found 334 errors in the served document, #179 (BUG-48), fixed in the same PR |
| #183, #178 | PR #191 (`b07b2fa`): the samples test compares status, media type, method, path and problem fields exactly. PR #192 (`ea955c0`): `scripts/doc-citations.py` and `docs/citations.lock.json`, run by the service suite; 28 of 89 citations were stale on `8afac6d`. A branch that moves a cited line runs `python scripts/doc-citations.py --relocate` |
| #181 SEC-06, #185, #186 | Merged: PR #190 (`8071d9d`; no client takes the password grant; the realm test passed on a real Keycloak in GitHub's manifests job, run 43511671215), PR #193 (`fc30854`, alembic check), PR #194 (`a29e683`, the UI map test). Codex reviewed #181 (five fixes accepted) |
| #184 SEC-07, #196 | PR #195, merged as `9a5a9d6`: `typ: at+jwt` in the JOSE header (RFC 9068); the realm test passed on a real Keycloak in GitHub's manifests job (run 43521078691 on `079ecf4`); Codex's five findings applied |
| Live docs, old group names | Fixed by OB1 run 3: Design and Architecture rev 183 (14 names), Technical Design v2 rev 327 (22 names) and 328 (#182); 0 hits for `-leads` and `-approvers` |
| #182, #187, #171 | Merged: PR #197 (`c28d504`: `/problems/<code>` pages, `problems.typeBase`, CRC base is the API Route), PR #201 (`f0decd0`: spike #187, decision in `docs/reviews/2026-11-13-spike-187/`, a contract test of the adapters against the providers' descriptions, no mock server now), PR #198 (`ae62d3a`: `approvals.counted_for`, migration 0004, self-service rate is live; docs/17 is 7 live, 3 built, 11 designed). The required database revision is 0004 |
| #199, #172 | Merged: PR #202 (`188f69c`, GitHub's compare lists at most 300 files; Codex found no defect), PR #203 (`89ecb07`: `cmapi_namespaces` fed by a collector over the watch caches; the unfed `cmapi_sync_drift_total` removed until Argo CD's view exists). docs/17 is 7 live, 4 built, 10 designed. For #198, #202 and #203 main had moved after the green run: OB1 ran the full suite on the merged tree locally and checked the tree hash; GitHub's checks ran on main after the merge |
| Filed for later | #200 (task, W3: the adapters' contract test in the suite), #204 (task, W6: the first slice of Wave 6, sign-in with OIDC PKCE and the Requests tab on `GET /requests`) |
| #204, the first slice of Wave 6 (OB1 run 4) | PR #210, merged as `418e934`, GitHub six checks green on `762d7ae`. `cmapi-portal-ui` has two builds (`dist/` on the API, `dist-demo/` the mockup's stand-in); sign-in by Authorization Code with PKCE through `cmapi-portal`, tokens in memory; the frame and the Requests tab run on `GET /me` and `GET /requests` with types from the contract; the other tabs say they are not on the API yet. Proven only on this Mac against a stand-in issuer and API: browser suites in Chromium 156 and Chrome 157, 36 of 36 mutants killed, screenshots at three widths in both themes. Codex: ten findings applied. Not proven on a real Keycloak, kind or CRC. Filed under #20: #205 SEC-09 (wildcard redirect URIs), #206 (no CORS: the portal cannot call a deployed API), #207, #208, #209 |
| Owner decisions on 2026-11-13, evening | #211 custom LimitRange gated by approval, with extra approval for anything beyond the tier; #212 Kyverno policies generated from the configuration, messages filled from it; #213 Kyverno optional (enforce, audit, off per environment), cmapi works without it; the clusters run the latest Kyverno (v1.20.0) with the `policies.kyverno.io/v1` types, and the CLI pin moves to match. All under story #22 |
| Owner decisions on 2026-11-14 | #215 configurable metadata (requiredLabels, requiredAnnotations, extraLabels, extraAnnotations, adoptionLabels; keep both `cmapi.net/env` and `company.net/app-environment`); keep **three** instances (nonprod rnd/dev, staging qa/uat, prod); #222 email links hard-code `#nonprod` (bug), and `prod` is the one environment name with meaning in code; #217 Argo CD server-side diff and ignoreDifferences (W2); #225 resilience: 2 or 3 replicas of the API and worker per instance, shared state in PostgreSQL, a native multi-process test; #226 keep **nginx** as the single front door (one origin, settles #206 without CORS), configured to best practice by research |
| cmapi-cluster-configs | Created 2026-11-14 and renamed by the owner to `ephico2real2/cmapi-cluster-configs` (the organisation's existing `cluster-configs` is left alone; rename everywhere: #228), private, `main` (README, `clusters/`, `policies/metadata-keys.yaml`). Branch protection refused on the free plan (HTTP 403): owner step #227 (GitHub Pro or an organisation recommended). Adoption (story #26): read namespaces labelled `cmapi.net/adopt` from the cluster and import their Namespace, ResourceQuota and LimitRange as raw YAML, as-is, under tier `custom`, not mapped to a named tier; test plan on #26 |
| OB1 run 5 (Fable), handed back 2026-11-14 when Fable usage ran out | Merged: PR #223 (`073f776`, #221: main was red for `418e934` in portal-ui; the axe check now waits for the theme transition), PR #224 (`a5fe2e6`, #214 and part of #211: custom LimitRange and overridable quota keys on the custom tier, facts `beyondTier`, `beyondTierKeys`, `networkExposure`, decision record `docs/reviews/2026-11-14-issue-211/`, Codex's five defects fixed). Open: PR #218 (#205, exact redirect URIs, head `33a39fa`) and PR #219 (#216 and part of #206: CORS off unless `cors.allowedOrigins` lists an origin, head `968f01f`), both reviewed by Codex, both need main merged in and a new GitHub run; merge #218 then #219. Unfinished: branch `configurable-metadata` holds only #222's fix. Filed #220 (SEC-10, Keycloak's own clients keep wildcard redirects). The Kyverno v1.20.0 CLI is verified on this Mac at `workbench/cmapi/ob1-run5/tools/bin/kyverno` (applies v1, messageExpression and variables work offline, ignores validationActions). `workbench/cmapi/ob1-run5/resume.md` |
| Who codes, from 2026-11-14 | Opus 5.5 at high (Fable out of usage). Fable reviews that work when it has quota, and designs the adoption strategy (#26) |
| OB1 run 6 (Opus 5.5 high), task 1 | Merged: PR #218 (`31e1cb3`, #205 exact redirect URIs; GitHub run 43573177299 green on `338143d`), PR #219 (`962d7f8`, #216; CORS off unless listed; GitHub run 43575167086 green on `ea53de1`). Found while building #226 through a native nginx 1.30.6: #229 BUG-57 (/redoc empty: the ReDoc 3.0.1 bundle is an ES module loaded as a classic script) and #230 SEC-11 (ReDoc 3.0.1 bundles DOMPurify 3.4.16, GHSA-cg2g-xh64-v4q7; pin moves to ReDoc 3.1.0), both on branch `redoc-module`. #206 stays open for the front door (#226) |
| OB1 run 6, later | Merged: PR #233 (`0c70b0e`, #222 email links; Fable approved after one round). Open, green, in Fable review: #231 (ReDoc; #229, #230, #235 telemetry off and a CSP on /redoc), #238 (nginx front door PR-A, closes #206, #241), #239 (adoption design for #26), #240 (#213 Kyverno modes, CLI v1.20.0, v1 policies), #245 (#212 policies rendered from configuration; stacked on #240 and #234). #234 (#215) has Fable's F1 to F4 applied; the owner moved the two optional contact keys to annotations. #247 (#226 PR-B, plain manifests) has a Codex security review to apply. Filed: #236, #237, #242 (owner choice: PolicyException per approved beyond-tier value), #243, #244, #246 |
| Fable reviews, 2026-11-14 | #231 merged as `f0b143d` after Fable's second pass. Fable found: #240 F1 high (in audit, the worker's PR check failed and closed an approved request's PR), F2, F3 (unquoted `mode: off` read as false); #245 F2, F3; #238 F1 to F7 (gzip on API answers, an auth code in the error log, the Route's 30 s timeout, header size, Ingress exposure, ReDoc CSP directives, old hosts); #239 A1 to A10. All accepted and applied by OB1; short Fable checks follow. Filed: #248 (adoption in enforce mode needs the approved snapshot as base), #249 (audit on the config repo's external CI), #250 (two-document resourcequota.yaml crashes updates). Owner decisions on #26: `cmapi.net/adopt` stays and is ignored; a missing required key is never forced, only reported; adoption reads only the live namespace, and the old `cluster-configs` repository does not exist for cmapi |
| Contracts findings (diagram-kit PR 64) | Filed by OB1 run 2: #181 SEC-06 password grant (sev:high, W1; in progress: client credentials for cmapi-automation, no client keeps direct access grants, bot-user removed, test users signed in by authorization code with PKCE), #182 to #187. Also #178 (stale file:line citations in docs/14 to 16) |
| #167 (UX-04) | Filed by OB1, Backlog, W6: a pending request is on the Approvals and Expiration tabs and not in the request list. Not fixed: the new row needs a scenario link |
| Filed for later waves | #143, #144, #147, #149, #150 |

### What is not done

- **Wave 1 on CRC, and each wave after it.** No cmapi workload is on CRC. The read-only checks of 11:10 UTC: `oc whoami` is `kubeadmin`, namespace `cmapi` has no workload, both `cmapi-ldap-bind` Secrets are there, the CloudNativePG CRD is there, and node memory requests are 15,525 Mi (79%).
- `docs/15` has no real token, no sign-in sequence figure and no CRC result. Each is marked in the document.
- The CRC screenshots of `/docs` and `/redoc`, which also need the owner's keychain step.
- The stories #13 to #29 have no new proof comment.

### Order from here

1. The owner reads #157 and decides.
2. Local CI and kind stay paused: keycloak-0 restarted a third time at 15:38:00Z under container load (#157, title widened to container load). The owner decides #157. The first OB1 run handed back after PR #177 (14 PRs merged on 2026-11-13; its report is `workbench/cmapi/ob1-run/resume.md`). OB1 run 2 handed back at 22:40Z (7 PRs merged; main `a29e683`; `workbench/cmapi/ob1-run2/resume.md`). OB1 run 3 handed back (6 PRs merged, main `89ecb07`; `workbench/cmapi/ob1-run3/resume.md`). OB1 run 4 handed back after PR #210 (`workbench/cmapi/ob1-run4/resume.md`). OB1 run 6 (Opus 5.5 high) order: merge #218 then #219; #222 (on branch configurable-metadata); #226 (nginx, closes #206); #215 with #213 and #212; #228 (rename); #225; #220; the portal items of #211; the rest of Wave 6; #207 to #209; #200. Not adoption (Fable designs it). Owner choices also open: the real host for the problem type base. New: #189 SEC-08 (the local demo still uses the password grant; W9). Owner to note: the live Design and Architecture document says group path `/cmapi/cmapi-onboarding` where the export says `/cmapi/app-cmapi-rbac-onboarding`; with no containers on this Mac. diagram-kit PR 64 (/app-architect contracts) waits for the owner's merge. diagram-kit PR 62 is merged (`dc86877`); PR 63 waits for the owner's merge (Claude Code refused the coordinator's). Owner choices also open: the status of an idempotency replay with another body (409 today, the IETF draft says 422) The owner decides each KPI target (all proposed), #149, #150 and #167. diagram-kit PR 62 (#169) and PR 63 (#170) wait for the owner's merge.
3. The CRC run from `docs/13`, from a clean checkout of `main`.

**A refusal that stands.** Claude Code refused the download of the oasdiff binary to this Mac ("Code from External"). So oasdiff runs in CI only. The exact command is in OB1's `recommendations.md`.

**A lesson for the documents.** `docs/14`, `docs/15` and `docs/16` cite code as `file:line`. PR #152 moved lines in `core/db/repo.py`, and the citations of `docs/16` were wrong until this update. Check them after each change to a cited file.

## Where it stopped

- `main` is at `5dfdea3`: PR #40, #89, #95, #98, #111 and #114. Nothing from them is on CRC yet.
- **Wave 1 (#94): code merged, not run on CRC.** Realm `cmapi` does not exist yet. PR #112 (draft, branch `ldap-rbac-names`, worktree `/Users/olasumbo/gitRepos/cmapi-design-crc`) sets the group names `app-cmapi-rbac-<role>` and the `cmapi.<role>` test users, the owner's decision, and must land before the one-shot import. Until it merges, **this file and the tracker on that branch are the current ones; `main`'s are older.**
- **Exactly where the review stands:** `docs/reviews/2026-11-06-pr112/README.md`. Reviewer 2's eleven patches are validated, accepted and on the branch, one commit each, `47ddb4f` to `0bde88c`. CI was green on all 5 jobs at `0bde88c`, and again at `9535ad2`, read on 2026-11-07. At `5f041b3`, which changed only documents, `manifests` failed in its "Tools" step: `curl: (22) ... 503`, downloading a tool before any test ran. The failed job was re-run on 2026-11-13, with the result not read yet. Any later commit needs its own run before CI is cited.
- **What PR #112 still needs, in order:**
  1. **#118:** apply `docs/reviews/2026-11-06-pr112/night/118/118.patch`, unchanged, one commit, with `Closes #118`. Opus 5.5 wrote it. Codex and the coordinator proved it, and the record gives each result. Its timing claim H5 did not finish, and Linux is left to CI.
  2. **The second pass:** the owner stopped it before it began, on the night of 2026-11-06. **Ask the owner whether it still runs.** Its brief is `second-pass-brief.md`, with `@@HEAD@@`, `@@COMMITS@@` and `@@GRAPH_ROOT@@` to fill. It was planned as Codex and Cursor. Codex finished #118's proofs, so name that in the brief or give #118's claim (C8) to Cursor.
  3. Mark the draft ready, CI green on the exact head, merge.
- **The first CRC run: the owner's go-ahead is given,** on the night of 2026-11-06: "go ahead with the CRC run after #112 merges". So once #112 merges, follow `docs/13` from a clean checkout of the merged commit. Nothing else may be running on the Mac, and no kind cluster. The owner still has to do the Chrome steps, and has reported no keychain result yet.
- **Merging:** the owner, 2026-11-06: "i want you to merge once all things clear". Merge when CI is green on the exact head and the review has passed.
- **Tokens:** the owner: "pls make sure we are NOT wasting claude token". Put long work on Codex and Cursor, and let the main session wake on a waiter, not poll. Report only what changed. One Claude agent at a time, only on what blocks the next step.
- **Other issues run alongside, on Codex and Cursor:** the owner, 2026-11-06: "you also need to continue working on other issues". #87 and #91 are no longer parked. Both were stopped midway:
  - **#87:** reviewer 1's answer is in `night/87/`. **Two findings, not yet re-checked by the coordinator:** C1, `neutral` and `skipped` read as failures, unlike GitHub's required checks; C3, a commit with 1,001 check suites hides a failure. Patches `C3.patch` and `C5.patch` are saved. C5, C6 and C7 were not reached, and its baseline log was contaminated by overlapping runs, so run it again serially. It needs its own empty database in `cmapi-test-pg`.
  - **#91:** Codex's continuation of the WIP on branch `fix-cnpg-verify-full` is `night/91/91-on-top-of-wip.patch`, which includes a new test file. It removed a measurement the WIP had claimed in `docs/08` without having run it. H1, H2 and H4 are PLAUSIBLE until the kind proof runs (K1). Its commands were not written before the stop, so write them from #91's "How to prove it". The coordinator has to run it, since Codex's sandbox has no container runtime. Never during a CRC step. It changes how the app connects to the database, so decide whether it goes before or after the first CRC run.
- **Defects:** the owner's process is `.claude/skills/fix-defect/SKILL.md`. Every defect gets an issue, including on an unmerged pull request.
- **The owner's keychain step:** commands in `LOCAL-DEV-TRUST.md`. No result reported yet. Keycloak's certificate has no Extended Key Usage, so Chrome may refuse it.
- **Branch protection requires CI, not a review.** GitHub will show a pull request as mergeable with its review unfinished. The review gate is held by the delivery loop alone, so do not merge on GitHub's word.
- No cmapi workload on CRC, and `/realms/cmapi` answers 404 (read earlier on the night of 2026-11-06). Check before trusting this: `oc get all -n cmapi`. No agent, test or kind cluster was running at this update, and `cmapi-test-pg` is the only container, up for the service tests. `keycloak-0` was still at 1 restart.
- **Pending: an automatic handover, from diagram-kit.** The owner asked on 2026-11-07 for the handover, the resume and the build tracker to run by themselves and survive `/compact`, auto-compact and `/clear`: through Claude Code hooks (Stop, PreCompact, SessionStart) in this project's `.claude/settings.json`, a note per topic at `claude-resumes/`, kept out of git, and a self-check script. This project has no such skills: the only project skill is `fix-defect`, and these two files are kept by hand. The owner then said another session builds the skills in diagram-kit: **diagram-kit PR #38**, "Make the handover automatic: handover, build-tracker and resume-work, with four hooks", **merged on 2026-11-10**. The local `main` in `/Users/olasumbo/gitRepos/diagram-kit` has the skills at `skill/handover/` (with `scripts/`), `skill/build-tracker/` and `skill/resume-work/`. **Not applied here yet:** read the three in full, then apply them. Show the owner the settings diff before saving it, and confirm each hook against the official hooks documentation. Until then, keep these two files current by hand, as before.
- **Not in this repository, for the owner to decide:** `claude-config` PR #3 (the tokensave entries in its settings) is open. A restore from that repository's `main` removes tokensave's hooks and permissions, and sets `model` to Fable. `~/.tokensave-fork-backup-20261106` holds copies of the agents' configs, `.claude.json` among them: delete it once the setup is settled.
- **CRC runs on this Mac, `olas-MacBook-Pro.local`,** and `crc status` here shows it running OpenShift 4.22.14. The owner's "remote MacBook" is this same Mac, as seen from the one they developed on before moving here. There is no second machine to plan around.

## Resume

1. Check the state, read-only:
   ```bash
   gh pr list --state open
   gh pr checks 112
   git log --oneline -5 origin/main
   oc get all -n cmapi
   oc get pod keycloak-0 -n keycloak
   oc describe node crc | grep -E '^\s+memory\s'
   KIND_EXPERIMENTAL_PROVIDER=podman kind get clusters
   ```
2. Read `docs/reviews/2026-11-06-pr112/README.md`, then carry on from the tracker's next action through the delivery loop in `CLAUDE.md`.
3. In the present order: Wave 1 on CRC, then the remaining waves.

## Who does what

The owner's latest words decide. On 2026-11-05: "Let us stop using fable for now", then "Use opus 5.5 high". On the night of 2026-11-06: "we won't use fable tonight but use opus and codex and cursor agent for review", "we can move codex to gpt-6.1-sol", and, about #118, to hand it to Codex. Whether Cursor stays a reviewer after that night is the owner's to say. The roles and the rest of this table are `CLAUDE.md`'s.

| Role | Who |
|---|---|
| Implementer | Opus 5.5 at `high`: a fresh `general-purpose` agent with `model: opus`, `effort: high`, working in the worktree |
| Reviewer 1 | Codex (`codex exec -m gpt-6.1-sol`, CLI 0.167.0, with read and write access to its export; 0.144.1 answered `model_not_found`). Returns the full code of each fix and test |
| Another reviewer, that night | Cursor's agent, `cursor agent -p`, planned on `grok-4.7-high` for a third family. Probe the name first: only its default model has answered here so far. Its job folder has no network or container runtime |
| Reviewer 2 | A separate Opus 5.5 agent at `high` that did not write the step, on an export. Checks each of reviewer 1's snippets against the design and the code and updates it, and reports with full code what reviewer 1 missed |
| Coordinator | The main session: briefs, re-checks every verdict, arbitrates, records, merges. Applies reviewer 2's resulting fixes narrowly, and sends back any that do not fit. Authors no application code |

Agents do not survive a session, so a new session starts fresh ones with a full brief. Codex's run script shape: `cd "$W" && codex exec --skip-git-repo-check -m gpt-6.1-sol -c model_reasoning_effort="high" -s workspace-write -c sandbox_workspace_write.network_access=true -C "$W" "$(cat "$W/brief.md")"`, with stdin from `/dev/null`, in the background, with one waiter on its pid. The scratchpad is not kept, so anything worth keeping goes in the repository.

**Every brief, from `agent-report` in diagram-kit:** paste the brief standard, because the owner requires agents to write structured reports as they go. Two lessons from that night: give the report folder as an **absolute path**, since a job working inside `head` wrote `head/report/`, which looked like no report at all; and say that new files go in the patch, since a plain `git diff` misses them. Also from there: `fix-defect`, `adversarial-review` and `codex-arbiter`'s lessons for the arbiter. `sweep-stale` reports leftover processes, and `--sweep` is asked for first. The agents' graph is tokensave: `.tokensave/` is in both checkouts, excluded through `.git/info/exclude`, and this session's own tools load only in a new session.

## Decisions that bind the work

- **Plain YAML first.** One Helm chart per independently running component comes later under `helm/`, none for Keycloak or LDAP.
- **CloudNativePG** (open source, 1.30.1 on CRC) by default, with `docs/12-existing-postgresql.md` for an existing server.
- **GitHub, Actions and GHCR, no Gitea.** Actions pushes the image, tests that digest and commits it to branch `deployed/crc`. Argo CD follows that branch, since Argo CD does not watch registries.
- **Argo CD Core 3.5.6** in `cmapi-argocd`, one Application per namespace through an ApplicationSet, with `Prune=confirm,Delete=confirm` on the Namespace, not one root Application. Measured on kind.
- **`cluster-configs-nonprod` is public.** GitHub refuses branch protection on private repos on this account (403). Requester names and emails there are world-readable, which is acceptable only because CRC's directory is fake.
- **The worker posts `cmapi/check`; Actions posts `ci/*`,** each pinned by `app_id`. Codex's signed permit is the recorded next step on #60.
- **Wave 1 is interim:** `oc apply` with the image in CRC's internal registry. Argo CD adopts those objects in Wave 5.
- **Stories close on the owner's approval,** with the proof for each criterion cited. Paperclip is off for now. A load test (#92) proves the KPIs; a month of data is a later check. See the tracker's "Stories and epics".

The full reasoning is in `docs/reviews/2026-11-05-deployment-design.md`, with the coordinator's nine rulings at its end. Those rulings change some of the tables above them, so read them.

## Rules that do not bend

- Autonomy: research and choose best practice instead of asking. Every bug gets an issue, then a fix with a test that fails before and passes after.
- A Claude Code permission refusal stands. Do not route around it or edit permission settings. Report the exact command.
- No secrets in git, logs, reports or command lines. TLS verification never off.
- **The other realms must stay unaffected and undeleted, and a restart must not bleed long** (the owner, 2026-11-06). See the tracker's risks. Before the first import, take the `pg_dump` of the Keycloak database the owner approved: outside git, deleted once verified, restored only on the owner's decision.
- **CRC is shared.** Never restart the VM or a shared service, no `crc stop/delete/config set`. Do not touch `inkcast`, `corp` or group-sync. In `keycloak`, only realm `cmapi` and its import resources, with no master admin credential. In LDAP, only `cmapi-*` additions. Delete only what cmapi created.
- kind clusters are named with the `cmapi-` prefix and use `KIND_EXPERIMENTAL_PROVIDER=podman`, an explicit `--kubeconfig`, node image v1.35.8. **Never run one during a CRC step.**
- Reviewers work on an export, never in a repository. Keep Codex's briefs narrow: its Wave 1 design cost 401,608 tokens and its narrow code review 174,046, and the owner does not want them wasted. Throwaway containers need a bind check, a marker guard, their own ports and an explicit `--kubeconfig`.
- Cite CI only from a run whose `headSha` equals the head, after it finished.
- No Co-Authored-By or "Generated with" lines. Never force-push or rewrite history.
- Report what was measured, what was inferred and what was not tested. Say which cluster each result came from.

## Steps only the owner can take

| When | What |
|---|---|
| Any time | Apply the automatic handover: the four hooks and the three skill links. See "The automatic handover: checked, and waiting for the owner" |
| Wave 1 | For the Chrome proofs: trust the two CAs in the login keychain ([`LOCAL-DEV-TRUST.md`](LOCAL-DEV-TRUST.md)), and sign in once as an LDAP person |
| Wave 3 | Create the GitHub App from the manifest flow, and install it on `cluster-configs-nonprod` only |
| Wave 4 | Make each GHCR package public, after its first push |
| Wave 8 | Decide #35 and #36 (LDAP) |

### The automatic handover: checked, and waiting for the owner

OB1 checked diagram-kit's four hooks against the hooks reference (<https://code.claude.com/docs/en/hooks>, read on 2026-11-13). Each one matches it:

| Hook | The skill's block | The reference |
|---|---|---|
| Stop | `handover.py stop`, timeout 10 | "`decision: "block"`, `reason`"; the inputs `stop_hook_active` and `background_tasks`; "Claude Code applies an 8-consecutive-continuation cap" |
| PreCompact | matcher `manual\|auto`, `handover.py precompact`, timeout 10 | Matcher values "`manual`, `auto`"; "Claude Code uses its stdout as instructions for the compaction summary. Keep that stdout under 10,000 characters per hook" |
| SessionStart | matcher `startup\|resume\|clear\|compact`, `handover.py session-start`, timeout 10 | Values "`startup`, `resume`, `clear`, `compact`, `fork`"; "The `additionalContext` field passes a string from your hook into Claude's context window" |
| PostToolUse | matcher `Bash`, `handover.py post-tool`, timeout 5 | The matcher filters on the tool name; `timeout` is "Seconds before canceling." |

OB1 did not apply them. The change is to Claude Code's configuration: a new `.claude/settings.json` with hooks in this repository, and three links in `~/.claude/skills`. OB1 runs as a background agent, and its rules do not let an agent's message authorize a configuration change. The decision to apply without showing the diff reached OB1 through the coordinator, not from the owner directly. So this is an owner step:

1. Make the links: `for s in handover build-tracker resume-work; do ln -s /Users/olasumbo/gitRepos/diagram-kit/skill/$s ~/.claude/skills/$s; done`. On 2026-11-13, `~/.claude/skills` has none of the three.
2. Create `.claude/settings.json` in this repository with the `hooks` block of `/Users/olasumbo/gitRepos/diagram-kit/skill/handover/SKILL.md`, section 5, unchanged. The repository has no `.claude/settings.json` today, so the diff is that whole block.
3. Add `claude-resumes/` to `.gitignore`.
4. Start a new session, and check `/hooks`.

Until then, keep this file and `build-tracker.md` current by hand.

## Environment facts

- CRC: OpenShift 4.22.14, Kubernetes 1.35.6. Node requests 15,525 Mi of 19,543 Mi allocatable. 277 listable kinds.
- Keycloak: namespace `keycloak`, RHBK 26.6.7, `KeycloakRealmImport` is `k8s.keycloak.org/v2beta1`. One instance. Route passthrough, certificate from ClusterIssuer `enterprise-ca`, so its public CA is `ca.crt` in Secret `keycloak-tls`, not the ingress CA. LDAP: namespace `ldap-testing`, base `dc=ephico2real,dc=com`.
- Internal registry route: `default-route-openshift-image-registry.apps-crc.testing`.
- Mac: hostname `olas-MacBook-Pro.local`, Intel Core i9-9980HK (`x86_64`), macOS 15.8.1, Homebrew in `/usr/local`, 32 GiB, podman machine at 8 GiB, Docker off. `cmapi-test-pg` on port 55432 is the service tests' database. The tokensave fork was updated on 2026-11-13 to `9455c2a`, built with Homebrew's rust 1.98.1, and checked by `/tokensave-fork`'s steps. Its database is now at schema 3, with the copy from before the update at `~/.tokensave/global.db.before-update-20261113T080610Z`. Installed on 2026-11-06: the tokensave fork at `~/.cargo/bin`, pandoc 3.12.1 at `~/.local/bin`, Codex CLI 0.167.0 with `model = "gpt-6.1-sol"` as its default. Python 3.12 is `/usr/local/bin/python3.12`, as CI uses.
- zsh does not split words, and a bare `=====` or `echo ===` fails there, which stopped three commands that night. Use bash for scripts.

## Not proven anywhere yet

Real Argo CD on CRC, RHBK's import of the realm, kubelet and SCC admission on CRC, Routes, the GitHub adapter against GitHub, LDAP federation login, Prometheus scraping, network policies on OVN-Kubernetes, the rollback on a real run.

## Keep this current

Update this file and `build-tracker.md` in the pull request that changes what they say. Before ending a session, re-read both against `git`, `gh` and `oc`.
