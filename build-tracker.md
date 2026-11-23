# cmapi build tracker

What is done, what is in progress, what remains, and which cluster proved each thing. The next-step instructions are in
[`HANDOVER-AND-RESUME.md`](HANDOVER-AND-RESUME.md). Last updated 2026-11-22 (see "Current"); first written on the night of 2026-11-06 by the coordinator, from `git`, `gh` and the proofs' logs, when the owner stopped all work to resume later.

**2026-11-15, 05:00Z.** `main` is at `08f7fe5`. The PRs merged since, the CRC state and the next steps are in the handover's section "State on 2026-11-15". In short:

| Item | State | Proof |
|---|---|---|
| The full request flow (#267, #97) | Merged in #269 | CI. Not yet run on CRC |
| LimitRanges (#253) | Merged in #255 | CI. Not yet run on CRC |
| Metadata (#215) | Merged in #234 | CI. Not yet run on CRC |
| Kyverno (#212, #213) | Merged in #240 and #245 | CI and the Kyverno CLI on this Mac |
| The front door (#226) | Merged in #238 and #247 | CI. Not yet run on CRC |
| CRC, docs/13 | Steps 0 to 10 pass on a clean slate | CRC, OB1 run 9 |
| CRC, docs/13 | Steps 11 to 25 wait for the owner's Secret `cmapi-git` | None |

**Proof** says where a result came from: **CI** is GitHub Actions on the named run, **kind** is a throwaway cluster on the
Mac, **CRC** is OpenShift Local. "None" means it has not run anywhere. A kind pass never counts as a CRC pass.


## Current: 2026-11-22, after 07:50Z

`main` is `5c01876` (PR #555). CRC runs `5c01876` (`/api/v1/version`, read 2026-11-22). No open PRs. The owner approved stories #483, #484 and #485 on 2026-11-22 through `/decide`, and all three are closed. Epic #481 is open, with #482 and #486 open.

| Area | Issue | State | Proof |
|---|---|---|---|
| PATCH contract | #483 (story) | Approved by the owner and closed 2026-11-22 (07:46:58Z). Decision: "Prove 428 live, then approve" | **428 proven live on CRC**, `5c01876`, 07:46:23Z, as `cmapi.requester`: a dry-run PATCH without `If-Match` on `cmap-live-g-dev` answered HTTP 428 `precondition-required`; requests 19 before and 19 after. Run 32: a real PATCH end to end four times (req-20261121-0002 to 0005, config PRs #23 to #26), with 409, 412 and `If-Match` live |
| Namespaces tab | #484 (story) | Approved by the owner and closed 2026-11-22 (07:47:01Z). Decision: "Approve #484" | Live on CRC, run 32: the lookup, Submit, Pending, In sync, Drift, 412 with the per-key choice, 409, the mnemonic chip, the operator-only reason. CI: T1 to T9 at 390, 820 and 1440 px in both themes, each with its mutant. CI only: axe, the 820 px width, keyboard use, Remove and Undo, the sensitive mark |
| Swagger and ReDoc for the namespace-change operations | #485 (story) | Approved by the owner and closed 2026-11-22 (07:47:03Z). Decision: "Approve, file the 390 px scroll" | 36 live checks on CRC in run 32 at 1440 and 390 px, plus the CI proof of PR #542. No dark theme in either viewer; ReDoc's logo is refused by the CSP on purpose |
| Swagger UI (`/docs`) scrolls sideways by 149 px at 390 px | #556 (bug, `sev:low`, sub-issue of #485) | Open, filed 2026-11-22 07:46:40Z. Next | Found in CRC run 32 (`doc32` checks). The proof to write: load `/docs` at 390 px and assert `scrollWidth <= clientWidth`; fails today, passes after; 1440 px unchanged |
| Epic 8: change the metadata of existing namespaces | #481 | Open | Children open: #482 (spike, In-Progress), #486 (rollout window, In-Progress) |

Everything else of the 05:05Z section stands, apart from the rows of #483, #484 and #485 and the state of `main` and CRC. Run 33 deployed `5c01876`.

## Previous: 2026-11-22, after 05:05Z (superseded by the section above)

`main` is `8f387bf` (PR #553). CRC runs `4999dee` (OB1 run 32, deployed 22:47Z to 22:57Z on 2026-11-21): api and worker `cmapi@sha256:67f43526...`, portal `cmapi-portal@sha256:a18734ce...`, alembic `0006`, the dev bundle 40/40 `current` (hash `a2603db2...`). Monitoring is off (#489). Merged after `4999dee` and **not yet deployed**: #550, #553 (migration `0007`) and #554. No open PRs. Run 33 deploys `8f387bf`.

| Area | Issue | State | Proof |
|---|---|---|---|
| CRC deploy step 5 built both images on the Mac and starved the cluster | #545 | Merged #548 (`4999dee`): CI builds both images, pushes them to GHCR by digest with an artifact attestation; step 5 imports the digest and builds nothing | Run 31 and run 32's first attempt were stopped by the guard in step 5; in run 32's first attempt 58 containers in 42 namespaces restarted (18:03Z to 18:31Z), among them kube-apiserver, Kyverno and cmapi's own. **CRC run 32, second attempt:** step 5 rc 0 in about 20 s, no `podman build` process in any 5-s sample, no restart outside cmapi after it, 0 BREACH from the first watch line to step 22. CI on `4999dee`: success |
| Test names in docs/13 broke CRC's name rule | #546 | Merged #547 (`e03898c`) | Dry run of `cmapi-live-g` answered 422 on CRC; docs/13 now names `cmap-live-g-dev`; `doc13-test.py` rejects 70 mutants (65 before) |
| Policies tab: collapsible sections, Results by policy last and paged | #537, #538 | Merged #540 (`20be856`); **live on CRC** | **CRC run 32**, Chrome 158, 10 checks, console 0: Results by policy closed, page height at 1440 px 1122 (run 31: 5662); at 50 a page, "1–50 of 80" and "51–80 of 80", rows in the answer's order |
| Namespaces tab type-ahead lists, operator-only reason names the environment | #535, #532 | Merged #536, #534; **live on CRC** | **CRC run 32**, requester, 8 checks, console 0: each option seen at its own centre by `elementFromPoint`, none inside a card; reason "Needs namespaces:protect in dev. Changing this key needs one more approval." The key shows only on a protected namespace (resume l.80-84) |
| Swagger UI and ReDoc for the namespace-change operations | #485 (story) | Merged #542 (`93fa9da`, "Part of #485"); **live on CRC**; waits for the owner's approval | **CRC run 32**, 36 of 36 checks for 409, 412, 428, the `mergePatch` body example and the Extensions, at 1440 and 390 px in both schemes. Observed, not defects: no dark theme in either page, Swagger UI scrolls sideways 149 px at 390, ReDoc's logo is refused by the CSP |
| Namespaces tab live scenarios | #484 (story) | The four scenarios ran on `cmap-live-g-dev` (protected, created through the form: req-20261121-0001, PR #22); the story waits for the owner's approval | **CRC run 32**: (1) Submit to In sync, req-20261121-0002, PR #23, revert req-20261121-0003 (PR #24); (2) drift by `oc label` shown and cleared; (3) 412 on a Check, "now cc-4412, yours cc-4413", Keep my edit then a new Check 200 (req-20261121-0004, 0005, PRs #25, #26); (4) 409 change-pending on Submit, A's req-20261121-0006 cancelled. 0 open requests at the end. Not proven live: axe, a Submit-side 412, a human approval (dev changes need none: `change: 0`) |
| PATCH contract | #483 (story) | Reopened 2026-11-21; the story waits for the owner's approval and for the 428 question | **CRC run 32**: a real PATCH (no `dryRun`) went from request to In sync four times; 409 and 412 live. **428 not proven live**: the portal always sends `If-Match`, so no request without it was sent |
| `request_events.at` was the transaction's start, so a timeline ran out of order | #551 | Merged #553 (`8f387bf`); next deploy, step 21 runs migration `0007` | Found live in run 32: req-20261121-0001 `applied` before `apply_started`. On a fresh PostgreSQL 16, 2 tests failed before; 43 passed after, with the migration round trip |
| Owner secret steps read the token from the clipboard | #549 | Merged #550 (`fd60926`); docs only until the next deploy | `doc13-test.py` failed 44 cases before, passes after; the owner's `cmapi-ghcr-pull` Secret was made by hand and the coordinator checked its type, registry and user |
| Portal checks read a value once after an action | #552 | Merged #554 (`128e38e`), part of #508 | Test-only. 972 assertions before and after, verbatim; full `npm test` exit 0 in 976 s, 139 portal checks |
| Secrets mutation harness ETXTBSY race | #543 | Merged #544 (`adfcdad`) | 32 mutants, 0 wrong; new `mutate-secrets-test.py` passes with both scripts held open for writing |
| Project rules | — | Merged #541 (`ce81e5e`): Sonnet 5.5 drafts the documentation and the coordinator oversees it; "Research, then ask" (diagram-kit PR #82, merged, holds the `/decide` skill and the `agile` as-built method) | Docs only |
| Run 32's guard stop | — | The first attempt stopped at step 5 at 18:14:25Z; the second attempt's watch wrote `$STOP` at 23:11:29Z (one missed 3-s check of realm inkcast-prod, answered 1 s later) while Part 3 ran. Scenario 1's revert and scenarios 2 to 4 ran after it, against the owner's rule; all ended clean and reverted (#484 comment, 23:30Z) | Snapshot at 23:16:22Z against s0: "no difference"; keycloak-0 restarts 4 throughout; no restart outside cmapi from before step 0 to the end |
| Keycloak CPU request raised from 1 to 2 (the owner's request); memory stays 1 Gi request, 2 Gi limit | — | Applied. **The realms had two outages, not one; the second was caused by the coordinator's watcher bug** (a zsh word-splitting fault) | First patch 23:30:13Z; the watcher then reported "NOT READY in 10 min" and rolled the change back, and all five realms answered 000. Re-applied 23:41:12Z; `keycloak-0` Ready 23:42:07Z (53 s), all five realms 200 (`tasks/bu7aebp1k.output`, `bhsovz54t.output`). When the rollback was applied is not found in either file |

## Previous: 2026-11-21, 15:40Z

`main` is `6066ec3`. CRC runs `a909074` (OB1 run 31, since 13:04Z), with the dev bundle 40/40 `current` (cmapi-cluster-configs merge `5926fa2`). Monitoring is off (#489). Open: #537 in build. Run 32 (#534, #536, #537) waits for #537.

| Area | Issue | State | Proof |
|---|---|---|---|
| Namespaces tab | #484 (story) | Merged #529 (`a909074`); **live on CRC**; the story waits for the owner's approval | T1–T9 at 390, 820 and 1440 px in both themes, each with its own mutant; Codex `gpt-6.2-astra` 8 findings, Fable narrowed them (finding 3 rejected per design §5); 484 checks 28/28, mutants 11/11, core 844. **CRC run 31**: as `cmapi.requester`, `cmapi-live-a` In sync, fixed keys locked, a cost-center dry run 200 with If-Match; as `cmapi.operator`, the operator-only keys editable; requests 13 before and after |
| Patch-plan cache, undeclared-key edits, screenshots rewritten by the suite | #527, #528, #530 | Merged #529 | #528 additive (oasdiff: no breaking change) |
| CRC bundle changed by #499 with no bundle PR | #531 | cmapi-cluster-configs #21 (`5926fa2`), cmapi #533 (`63df5cd`) | `policies check` exit 0; `test_crc_bundle_pin_531` fails at cd01af1's pin and passes now; **CRC run 31**: 40 policies, digests the files', `hashState: current`, 84 pass, Policies tab "0 clusters off the bundle" |
| Operator-only reason names the environment | #532 | Merged #534 (`ba104c6`); next deploy | Core 4 failed before, 432 passed after; service 46 passed; Opus review, docs/14 citations fixed; the test moved to tests/service (the reference-code job) |
| Lookup and Quotas type-ahead lists clipped by their card | #535 | Merged #536 (`6066ec3`); next deploy | Found live on CRC in run 31. `elementFromPoint` checks fail before and pass after; Codex review: lists close on Tab, blur and outside click; mutants 7/7 killed; `npm test` green |
| Policies tab: collapsible, Results by policy last and paged (1, 2, 3 … N; 25, 50, 100) | #537 | In build (owner's request; layout chosen by the owner) | None yet |
| Run 31 stopped by its guard under load, then resumed | — | Resumed on the owner's go after the load stayed below 12 | Keycloak realms slow at load 20–31 (the CRC VM); keycloak-0 restarts 4 throughout; nothing applied before the stop |

## Previous: 2026-11-21, 08:30Z

`main` is `9ad4de8`. CRC runs `cd01af1` (OB1 run 30), with the dev bundle 40/40 `current`. Monitoring is off (#489). Open: story #484 in build.

| Area | Issue | State | Proof |
|---|---|---|---|
| Namespace middle starts and ends with a letter or digit | #512 | Merged #514 | Core 822 passed with the Kyverno CLI; browser check and its mutant killed; Fable F1, F2 applied; **CRC run 30**: `-x` refused at the field |
| Team-wide names `<mnemonic>-<env>` | #511 | Merged, live | **CRC run 30**: `abc-dev` dry run 200 |
| CRC bundle stale after #505 | #510 | cmapi-cluster-configs #19, cmapi #515 | **CRC**: 40 policies ready, digests the files', `hashState: current`, 84 pass 0 fail; Policies tab 26 checks passed |
| ci/kyverno fails folders a PR does not change | #516 | Merged #517, cmapi-cluster-configs #20 | 23 passed with the Kyverno CLI; #19's ci/kyverno passed after |
| P12 expiry check flake | #518 | Merged #519 | Old check fails CI's exact error with a 300 ms delayed clear; new passes; broken button fails |
| P9 miss, check 7 and workflow check near 90 s | #508, #521 | Merged #522 | P9: 7 of 7 missed before, 7 of 7 passed after at CPU throttle 25; check 7 91.3 s to 25/25/30/8 s; 5 mutants killed; Codex and Opus reviews |
| Kyverno CLI tests without kyverno | #513 | Merged #520 | 19 passed, 0 failed without it; 48 passed with it |
| Contract report tests ran another checkout's tool | #524 | PR #525 | 6 failed before, 11 passed after |
| Review defects of #492 and the token duration cap | #491, #494–#497, #501, #523 | Merged #499 | Codex astra xhigh 5 findings, Fable narrowed them and found #523; core 840 passed; test_bundle_hash_244 20 of 20; CI all checks |
| Namespaces tab | #484 | In build | None yet |

## Previous: 2026-11-20, 10:15Z

`main` is `fb727b5`. CRC runs `fb727b5` (OB1 run 27; steps 23 to 25 wait for CRC monitoring, #489). kind is deleted by the owner (#487). Open: PR #488 (draft).

| Area | Issue | State | Proof |
|---|---|---|---|
| Automatic import-token renewal, `clusterTokens` parameters, manual fallback | #398 | Merged #469, #478; #398 closed | CI (all checks); full service suite on this Mac; Fable review; **CRC live**: 20m import renewed by the worker at 10:05:08Z (due 10:04:20Z), api and worker on the new 7d token by 10:09:12Z |
| Bundle hash S1, `hashState` | #244 | Merged #477 (S1 of S8) | CI; Fable review; CRC run 27: `hashState` current |
| ci/kyverno on non-bot PRs | #429 | Merged #475 | CI |
| Paged tabs busy state | #407 | Merged #472 | CI (portal-ui) |
| Deterministic secret forms | #470 | Merged #471 | CI |
| Namespace contract Phase 1 (required keys, name rule, expiry `enabled`) | #479 | PR #488, draft | Implementer: 43 new tests fail on main, pass on the branch; service suite in two halves 992 + 771 passed; contract gate pass. Coordinator checks and review pending |
| Change metadata of existing namespaces | #481 to #485 | Designed (#482), not started | None |

## Previous: 2026-11-19, 19:40Z

`main` is `7122ec6`. CRC runs `7122ec6` (OB1 run 26). kind re-imported; token renew by 2026-11-25T09:51:14Z. No open PRs.

| Area | Issue | State | Proof |
|---|---|---|---|
| Cluster diagnostics, token-expiry metric, `POST /clusters/{id}:probe` | #396, #397 | Merged #465; live | CI (all checks); CRC run 26 live checks 2 to 4 |
| `statusSince`, transition logging, dead status removed, Git delivery review, redaction, list without items | #403, #456, #417, #444 to #452, #424, #421 | Live on CRC | CRC run 26: version 7122ec6, proof all passed; the Git delivery paths and #455 not exercised live |

## Previous: 2026-11-19, 18:00Z (stopped by the owner)

`main` is `3db1fa8`. CRC still runs `b8ee59e`. Nothing is running.

| Area | Issue | State | Proof |
|---|---|---|---|
| Cluster diagnostics, token-expiry metric, `POST /clusters/{id}:probe` | #396, #397 | **PR #465 ready, not merged** (head `2e5b2f5`); CI was pending when stopped | Mayday astra; round 2: 6 fixes accepted, F3 refused; 2 faults from the coordinator's full suite fixed (`68132a7`, `2e5b2f5`); full suite 1711 passed, 6 local-venv failures |
| CRC's own import token: TokenRequest and annotations | #398 | Briefed (i398), not started | None |

The rest of the 17:30Z section below holds.

## Earlier: 2026-11-19, 17:30Z

`main` is `fcb49bb`. CRC still runs `b8ee59e` (run 25); the merges below are not deployed. kind's token: renew before
2026-11-24T17:30Z. Work ships through /houston-mayday (Codex builds and reviews, Opus rules), labelled `review:fable`.

| Area | Issue | State | Proof |
|---|---|---|---|
| Git clients: host response bodies redacted | #424 | Merged #453 | CI; review |
| A list answer without `items` no longer retires every cluster | #421 | Merged #455 | CI; review |
| Codex review of Git delivery: workspace symlinks, delivery states, credentials, Gitea adoption | #444 to #452 | Merged #457, #458, #459, #460 | CI; Codex review, OB3 corrections; guard test for test placement (#458) |
| Cluster status `environment-not-served` removed (never set) | #417 | Merged #463 | Mayday sol; coordinator 166 passed (PostgreSQL); CI |
| Import finding logged on appear and clear, not on every relist | #456 | Merged #462 | Mayday sol; coordinator full suite; CI after the logger fix `d351e5e` |
| `statusSince`: "since" is when the status began | #403 | Merged #464 | Mayday astra; coordinator full suite 1692 passed (6 local-venv failures, see handover); CI after `b3980fd` |
| Cluster diagnostics (Secret, token expiry, last probe), token-expiry metric, `POST /clusters/{id}:probe` | #396, #397 | In review: PR #465 | Mayday astra; round 2: 6 fixes accepted, 1 refused; coordinator full suite running |
| Podman VM shrunk to 4 CPU / 5 GiB | — | Done | `podman machine inspect` |

**Open, next:** #398, #407, #429, #244 (mayday), then one CRC deploy. Also open: #410, #418, #413 leftovers.

## Earlier: 2026-11-19, 03:30Z

`main` is `b8ee59e`. CRC runs `b8ee59e` (OB1 run 25), proven live. kind (`KIND_CMAPI_TEST`, rnd) is imported with
Kyverno and the rnd bundle. **kind's token expires 2026-11-26T03:06:53Z: rerun `deploy/kind-import/up.sh <cluster-configs
checkout>` before 2026-11-24T17:30Z.**

| Area | Issue | State | Proof |
|---|---|---|---|
| CRC proof: restarts before the run reported, not failed; init containers; unreadable NetworkPolicy fails | #425 | Merged #426 | CI; review OB3 (2 fixes); CRC runs 24, 25 |
| cmapi's Kyverno bundle on CRC (31 dev policies, audit) | #428 | Done: cluster-configs #17 (bundle re-rendered, #249 closed), #431 (docs/13 platform step) | Investigation; review OB3; applied and verified on CRC: 31/31 ready, pass 84, fail 0 |
| Kyverno reports controller 128/256 Mi on CRC | #428 | Merged #432; helm revision 2 | CRC: 96 Mi peak under the bundle |
| Kyverno and the rnd bundle on kind (`up.sh` installs them) | #430 | Merged #433 | Review OB3 (HELM_KUBE* override fixed); kind: 31/31 ready |
| Cluster TLS trust: one mode per cluster (insecure per environment by configuration, caData, trusted = system store + injected/operator bundles), `tlsServerName`, `/clusters` trust source | #434 | Merged #435 | Analysis from primary sources, owner decisions D1-D7; review Codex (reviewer 1) + OB3 (reviewer 2): 6 fixes, 2 rejected on measurements; CRC run 25: injected bundle 147 CAs, both clusters `trust.source: caData`, kind `serverName: host.crc.testing` |
| Swagger required fields per instance | #350 | Live | Run 24 check 5 |
| **Epic 7: agent access to cmapi over MCP** (the owner's proposal) | #436 | Filed: spike #437 (INV-01, the MCP spec and authorization), stories #438-#442 (INV-02 to INV-06), milestone W7, all Backlog | None yet |
| Issue states by the `/agile` rules | — | Done: all 131 open issues have exactly one work tag (Backlog 98, In-Progress 27, Blocked 5, In-QA 1) and one `status:` label; both integrity counts 0 | `workbench/cmapi/records-2026-11-19/work-tags.tsv` |
| diagram-kit: `/app-architect` contracts first; light-theme diagrams only | — | **Merged by the owner** (diagram-kit #64, #72) | diagram-kit CI |

**Run 25 note:** the image build stalled CRC for about 36 s at 02:25Z. The shared router restarted once, and Kyverno
restarted. Keycloak did not restart, and no cmapi pod did. The guard stopped the run. The owner chose "resume, no
rebuild", and the run finished. Evidence is on #157.

**Filed 2026-11-18/19 and open:** #396, #397, #398, #403, #407, #410, #417, #418, #421, #424, #429. The #413 leftovers are
docs/08 section 4, a not-imported sample, and the figures #418 and #209.

## Earlier: 2026-11-18, 18:00Z

`main` is `721cb64`. CRC runs `721cb64` (OB1 run 24), but its proofs stopped at step 23 on a restart from before the run
(#425, fix in PR #426). kind is down until run 24 resumes.

| Area | Issue | State | Proof |
|---|---|---|---|
| Portal CI flakes: the settle wait, the Quotas pager | #347, #392, #312, #317 | Merged #406 | CI; 0 of 50 under throttle; review OB3 (1 fix) |
| Story #302 (Expiration, Policies, Capacity) | #302 | **Closed** by the owner | Proof comment on #302 |
| Figures light theme only (docs) | — | Merged #408 | CI |
| Caches read once | #402 | Merged #409 | CI; review OB3 (1 fix) |
| The not-imported state | #404 | Merged #411 | CI; review OB3 |
| Kyverno pin, exact match | #395 | Merged #412 | CI; review OB3; CRC run 24 (env and binary v1.20.0) |
| Docs: contract, payloads, components (Sonnet 5.5 writers) | #413 | Merged #414, #415, #416 | CI; OB3 fact-check (17 statements corrected) |
| One bad cluster answer stops discovery | #419 | Merged #422 | CI; review OB3 (4 fixes) |
| SEC: the token in cluster findings | #420 | Merged #423 | CI; review OB3 (no findings) |
| Swagger required fields per instance | #350 | Live on CRC | Run 24 check 5: `required` equals the config |
| The proof fails on a restart from before the run | #425 | PR #426, in CI | None |
| diagram-kit: contracts first in /app-architect | — | diagram-kit #64, refreshed, **waiting for the owner's merge** | CI |
| diagram-kit: light-theme diagrams only | — | diagram-kit #72, **waiting for the owner's merge** | CI |
| Disk cleanup (owner's rules) | — | Done: free 97 → 135 GiB | `workbench/cmapi/cleanup-2026-11-18/` |

Filed today and open: #396, #397, #398, #403, #407, #410, #417, #418, #421, #424, #425. The fstrim of the cleanup restarted
cmapi-db-1, cmapi-portal and Kyverno's controllers (not Keycloak): recorded on #157.

## Earlier: 2026-11-18, 07:00Z

CRC runs `1537977` (OB1 run 23). All nine portal tabs are on the API.

| Area | Issue | State | Proof |
|---|---|---|---|
| Kyverno version pin in the image | #388 | Merged #390 | CI; CRC |
| CRC proof: report group and grants | #387 | Merged #391 | CI; CRC |
| Capacity check: unknown never fits | #393 | Merged #394 | CI; review OB3 |
| Portal slice 4: Capacity API and tab | #302 | Merged #400 (`1537977`) | CI; review OB3; CRC run 23 |
| kind as a second cluster, imported | #15 | Merged #399, #401 | CI; review OB3; runs 22 and 23 |
| Portal CI flake | #347, #392 | Next | None |

Filed 2026-11-18: #392, #395 to #398, #402 to #404.

## Earlier: 2026-11-18

The plan is in `HANDOVER-AND-RESUME.md`, "Resume here: 2026-11-18". CRC runs `6565d9d` (OB1 run 21).

| Area | Issue | State | Proof |
|---|---|---|---|
| Contract report in the values repository's CI | #337 | Merged #370 | CI; review OB3; throwaway PR #371 |
| Protect a namespace from deletion | #366, #374 | Merged #378 (`abad314`) | CI; review OB3; CRC run 20 |
| Kyverno v1.20.0 on CRC, scoped and failing open | #302 | Merged #386 | CRC (probe policy) |
| Portal slice 4: Policies API and tab | #302 | Merged #384 (`6565d9d`) | CI; kind (Kyverno audit); review OB3; CRC run 21 (results, a stored refusal, the tab) |
| A migration test's stale revision | #385 | Fixed in #384 | CI |
| The image's Kyverno version pin is empty | #388 | Building | None |
| docs/13 claims a proof line that crc-proof.sh lacks | #387 | Building | None |
| Portal slice 4: Capacity | #302 | Next | None |

Filed 2026-11-17 and 18: #372, #373, #375 to #377, #379 to #383, #387, #388.

## Earlier: 2026-11-17

The plan and the owner's decisions are in `HANDOVER-AND-RESUME.md`, "Resume here: 2026-11-17". Proof: CI is GitHub Actions
on the exact head; kind is the throwaway `cmapi-test` cluster; none of these runs on CRC yet (CRC runs `9ba33b2`).

| Area | Issue | State | Proof |
|---|---|---|---|
| Expiration list API and tab | #318 | Merged #322 (`9ba33b2`) | CI; CRC (deployed 2026-11-16) |
| #328 design: two designs and the arbitration | #328 | Merged #329 | Records |
| Validator: empty prefix, `*` prefix | #330, #331 | Merged #340, #341 | CI; review OB3 |
| Helm `metadata:` values with `values.schema.json` | #335 | Merged #339 | CI; kind (engine none) |
| Kyverno audit by default; CI check on audit | #342, #343 | Merged #344 | CI; review OB3 |
| Pattern subset, shared anchored pattern, config shape | #332, #338 | Merged #346 | CI; three-engine corpus |
| Required labels and annotations in the OpenAPI schema | #328, #334 | Merged #350 | CI; equivalence corpus, Swagger screenshots (local) |
| Kyverno coverage, background scans, policy names | #333, #345, #356 | Merged #354 | CI; kind (Kyverno v1.20.0, audit) |
| RE2 matching; curl samples | #348, #349 | Merged #351, #352 | CI; image stage built by hand (amd64) |
| Company profile: LOB, CL, mnemonic | #358 | Merged #359 | CI; Kyverno CLI |
| YAML quoting for Kubernetes tools | #355 | Merged #367 | CI; Go YAML readers |
| New namespace form from the metadata config | #336 | Merged #368 (`7ba5d78`) | CI; Chromium 156, nginx CSP, axe |
| Contract report in the cluster-configs CI | #337 | In progress | None |
| Portal slice 4: Policies, Capacity | #302 | Next after the CRC deploy | None |

Open bugs filed on 2026-11-17: #347, #353, #357, #360, #361, #362, #363, #364. Follow-ups: #365, #366.

## Earlier: 2026-11-16, 19:33Z

The next steps and the owner's decisions are in [`HANDOVER-AND-RESUME.md`](HANDOVER-AND-RESUME.md), "Resume here". **Proof** is where the result was measured. CI is GitHub Actions on the exact head. CRC means a live run (OB1 runs 9, 11, 13 and 15, logs in `workbench/cmapi/ob1-run*`).

| Area | Issue | State | Proof |
|---|---|---|---|
| Full request flow (apply mode) | #267, #97 | Merged #269 | CI; CRC, docs/13 from a clean start (run 9) |
| Git delivery: Git layer and PR adapter | #286 | Merged #288 (`21a7f47`) | CI 916 service and 361 core tests; CRC requests via PRs #5 and #6 |
| Git over SSH (bot key) | #286 | Merged #299 (`0a805b0`) | CRC: req-20261116-0001, PR #7, worker fingerprint logged |
| GitLab adapter | #286 PR-B | Not started; waits for the owner's read-path decision | None |
| Bitbucket adapter | #286 PR-C | Not started | None |
| Chart mounts for the Git layer | #289 | Not started | None |
| Portal slice 1: sign-in and Requests | #204 | Merged #210 | CI; CRC |
| Portal slice 2: New namespace, Approvals, Workflow | #300 | Merged #305 (`130ff6c`) | CI; CRC with Playwright, PRs #8 and #9 (run 13) |
| Portal slice 3: Quotas, KPIs | #301 | Merged #313 (`525ca27`) | CI; CRC with Playwright, PRs #10 and #11 (run 15) |
| Portal slice 4: Expiration, Policies, Capacity | #302 | Next: the list APIs first | None |
| crc-proof.sh | #275, #278, #280 | Merged #277 | CRC: passed at 21a7f47, 130ff6c and 525ca27 |
| Docs: connecting to Git | — | Merged #296 (docs/19) | doc13-test, doc-citations |
| Docs: who a request is from, RBAC figure | #14 | Merged #297 and #298 | `onBehalfOf` tests 2 passed; CRC proof lines quoted |

## All issues and milestones

The full register is [`issue-register.md`](issue-register.md), generated by `scripts/issue-register.sh` from GitHub. Run the script again after each change to an issue or a milestone. The counts below are read at 2026-11-13T14:54Z.

- 135 issues: 49 open and 86 closed. Milestones `W1` to `W9` exist, one for each wave, with no due date: the owner gives the dates.
- Each open issue has one type label, one `status:` label, one work tag, a parent and a body in the `/agile` form. Each open defect has a `sev:` label and an ID. The last IDs in use are `BUG-39`, `SEC-05`, `UX-03` and `PERF-01`.
- Work tags of the open issues: 25 `Backlog`, 20 `In-Progress`, 0 `In-QA`, 4 `Blocked`. Open issues without exactly one work tag: 0.
- #6 (the plan) has no parent. #6 and the epics #7 to #12 have no milestone, because an epic spans milestones.
- OB1's agent did the sweep on 2026-11-13. The reason for each class, parent and milestone is in OB1's report folder (`agile/mapping.md`), which is not in git.

### Class of each issue

All 135 issues, open and closed, by the class questions of `/agile`, section 2.

| Category | INV only | TDT only | Both | No class | Total |
| --- | --- | --- | --- | --- | --- |
| SEC | 1 | 2 | 1 | 1 | 5 |
| BUG | 23 | 6 | 1 | 9 | 39 |
| PERF | 0 | 0 | 0 | 1 | 1 |
| UX | 1 | 0 | 0 | 2 | 3 |
| Other work | 72 | 1 | 1 | 13 | 87 |
| Total | 97 | 9 | 3 | 26 | 135 |

100 issues are `INV` and 12 are `TDT`. The 26 issues with no class are fixes that bring existing behaviour back and add nothing, the plan and the epics, and the parked item #93. Only open defects have an ID, so the closed defects of earlier reviews are in "Other work".

### Blocked

| Issue | Blocker | What unblocks it |
|---|---|---|
| #157 PERF-01 | The shared Keycloak restarted while a kind cluster ran on this Mac | The owner's decision on the CRC run and on where kind proofs run |
| #35 SEC-01 | The LDAP server is not cmapi's. The owner decides | The owner's decision on the admin passwords in the ConfigMap |
| #36 BUG-08 | The same | The owner's decision on the reapply of `ldap-acls` |
| #93 | Paperclip is off | The owner turns Paperclip on, or closes the item |

## OB1's run, 2026-11-13

**The merge gate is local CI, from 14:57 UTC on 2026-11-13** (the owner: "use local ci for all work and forget the githiub"). In this tracker, **CI** as a proof then means `act-ci.sh` of `/setup-local-ci` on this Mac, unless a row names a GitHub run. `OB1-PROMPT.md`, "Local CI is the merge gate", has the rule.

The state of each item of the run is in [`HANDOVER-AND-RESUME.md`](HANDOVER-AND-RESUME.md), "State on 2026-11-13, during OB1's run". The session stopped two times and lost nothing: from 09:45 to 10:24 UTC (`403 authentication_failed`) and from about 11:45 to 13:53 UTC (Fable's 5-hour usage limit). The table "Where it stands" below is the state before the run, except where the handover says otherwise.

## Where it stands

| | |
|---|---|
| Merged to `main` | PR #40, #89, #95, #98, #111, #114, and on 2026-11-13 by OB1: PR #112 (LDAP group names, test users, second pass; `99093d8`), PR #140 (BUG-29), PR #135 (the API documentation of `docs/01`), PR #152 (BUG-31), PR #153 (`docs/14`, `docs/15`, `docs/16`, BUG-30; `f62d448`), PR #158 (#91, SEC-04; `513ea67`), PR #160 (the figures from the mockup; `0cd0d57`), PR #156 (`docs/04` and the examples from a run; `30f29bb`), PR #161, PR #162 (#87, BUG-11; `c66a249`), PR #159 (records) |
| In progress | Wave 1 (#94): the code is merged, and the CRC run from `docs/13` is next. #91 (SEC-04) is merged (PR #158), proven on kind: before the fix `prefer` with a plaintext fallback, after it `verify-full` and a refusal. **The CRC run is stopped: `keycloak-0` restarted on 2026-11-13 (#157), and the owner decides** |
| On CRC | No cmapi workload, and realm `cmapi` does not exist (read 2026-11-06). OB1 has not touched CRC yet. Namespace `cmapi` holds Secret `cmapi-ldap-bind` and OpenShift's own generated Secrets. LDAP holds the bind user and the old `cmapi-*` groups, which step 10 of `docs/13` removes |
| Next action | **The owner reads #157 (PERF-01) first.** Meanwhile OB1 merges PR #163 and PR #168 when local CI and GitHub's required checks are green (oasdiff 1.37.0 is on this Mac, read at 15:26 UTC, and #163's contract gate passes locally), then #149, #150, #144, #143. After the owner's go-ahead: then the CRC run of Wave 1 from `docs/13`, from a clean checkout of `main`, with no kind cluster on this Mac. Then the proofs of #94 and of the API docs on CRC, the real token for `docs/15`, and Wave 2 |
| Running | See `HANDOVER-AND-RESUME.md`, "State on 2026-11-13" |
| Whole app | Not done. The thin slice ends at Wave 5, and the product scope at Wave 9 |

## Done

| What | Proof | Where |
|---|---|---|
| Service: API, worker jobs `open_pr`, `pr_checks`, `watch_sync`, `prune`, `channel_notify`, `open_revert`, migrations 0001 to 0003 | CI: 312 service tests. kind: api and worker Ready, `/readyz` 200, `kind-test.sh` exit 0. Not on CRC | `cmapi/` |
| Plain YAML, `render.sh`, `secrets.sh`, `kind-test.sh`, existing-PostgreSQL guide, `manifests` CI job (#88, #90, PR #89) | kind on Podman: `kind-test.sh` exit 0, image built from `f3ebd9a`; migrate connection `pg_stat_ssl True TLSv1.3`. CI: kubeconform, and the policy blocking another namespace on Docker-backed kind. **No pod has started under the policy on podman kind.** Not on CRC | `deploy/manifests/`, `deploy/`, `docs/12`, `docs/reviews/2026-11-05-pr89/` |
| Deployment design: one merged design with rulings | kind: Argo CD 3.5.6, three accident tests, no namespace lost | `docs/reviews/2026-11-05-deployment-design.md` |
| Reference modules | CI `reference-code`: 121 tests | `examples/src`, `examples/tests`. Their copy in `cmapi/src/cmapi/core` has `cmapi/tests/core`, which no CI job runs: None until one does |
| Image | Built locally. Not published | `cmapi/Containerfile` |
| Portal UI on mock data (no sign-in, no API call) | CI: `portal-ui`. **Must not be deployed as the portal** | `cmapi-portal-ui/` |
| Portal mockup | CI: 8 tests | `mockups/portal/` |
| Three review passes on the service | Opus and Codex; auth, token and admission on passes 2 and 3 were Opus only | `docs/reviews/2026-11-05-pr40.md` |
| Wave 1's code: CRC manifests, guards, backup, rollback, runbook, `realm_sync` `requireSync`; review fixes #99 to #108 | CI run 42231442774 at `d56a14d`. Realm on community Keycloak 26.6.4 only. **Not on CRC** | `deploy/`, `docs/13`, `docs/reviews/2026-11-06-wave1-review/` |
| LDAP bind user `cmapi-ldap-bind`, old `cmapi-*` groups (to be replaced by #110) | CRC. Federation not login-tested | `docs/11` |
| Branch protection on `main`: `reference-code`, `service`, `portal-mockup`, `portal-ui`, `manifests` | GitHub | |

## Remaining, in waves

Each row is one or more pull requests through the delivery loop in `CLAUDE.md`. Waves 2 and 3 can run in parallel. Wave 4
needs 3, Wave 5 needs 2 to 4, and Waves 6 and 7 need 5.

| Wave | Work | Issues | Owner step | State |
|---|---|---|---|---|
| 0 | Plain YAML merged | #88, #90 | None | **Done** |
| 1 | **Interim deployment on CRC:** `oc apply`, image in CRC's internal registry by digest, realm import, reader baseline, Routes, screenshots. No real namespace request yet. Also: `secrets.sh` checks `GET <issuer>` so it cannot mint values behind a kept realm; `cmapi-imports` namespace; the two Keycloak URLs. Prove the Route through the NetworkPolicy: CRC's router uses `HostNetwork` on one node (read with `oc`), so the same-node rule should allow it, which is inferred until it answers. **The other realms stay unaffected and undeleted, and a backup of the Keycloak database comes first (see the risks)** | #94, #110, #109 | Trust the two CAs (`LOCAL-DEV-TRUST.md`); go-ahead for the CRC run; sign in once as test user `cmapi.requester` | Code merged (#98). Names in review (#112). CRC run needs the owner's go-ahead |
| 2 | Argo CD on kind: bootstrap, narrowed role, policies, approver. Per-namespace ApplicationSet, `Delete=confirm`, `core/sync.py`, `watch_sync`, `docs/01`. Tests `e5`, approver, and `scale` before the layout merges | #65, #64 | None | Pending |
| 3 | GitHub adapter, App auth, `pr_status`, config repo checks, a real PR on `cluster-configs-nonprod`. Gitea removed | #87, #60, #61, #59, #97 | Create and install the GitHub App | Pending |
| 4 | End-to-end CI on kind; release to GHCR with attestation, `deployed/crc`, rollback. Charts removed, each test mapped to its YAML replacement | #85 | Make each GHCR package public | Pending |
| 5 | Argo CD on CRC adopting Wave 1's objects. A real request through a real PR, then a delete, screenshots. `apply` removed. **Thin slice done** | #64, #65, #85, #84 | None | Pending |
| 6 | Portal on the API: OIDC PKCE, TanStack Query, its own image. New namespace, Requests and Approvals first. Team DL field | #33 | None | Pending |
| 7 | CLI and `cmapi-sdk`. `cmapi-capacity`, the real capacity guard, quotas (phase 3) | #62 | None | Pending |
| 8 | Service accounts, grants, tokens (phase 4). Lifecycle, policies, operations, OpenTelemetry, the remaining KPIs (phase 5). LDAP hardening. **Load test: the proof that KPIs work, and the budgets at 5,000 namespaces.** A month of KPI data is a later check on real use, not a gate | #35, #36, #92 | Decide #35 and #36 | Pending |
| 9 | One Helm chart per component under `helm/`, none for Keycloak or LDAP. Final walk from a clean start using only the guide (admin, non-admin, CLI). Phase 6 | | None | Pending |

### Not built, by area (`docs/08` section 4)

- **Service:** config hot reload, most KPIs, metadata plugin, OpenTelemetry, route rate limits, the LDAP directory provider.
- **Endpoints:** expirations, tiers, quota writes beyond the namespace PATCH, metadata, service accounts, grants, SCC grants, tokens, policies, cluster import, capacity and placement, adoption, reports, operations, admin reload.
- **Worker jobs:** `expire_check`, `reservation_expiry`, `policy_report_sweep`, `import_clusters`, `reconcile`, `kpi_export`, `outbox_publish`, `operations`.
- **`cmapi-capacity`:** all of it.
- **Portal:** every API call, sign-in, its Containerfile.
- **CLI and SDK:** not started.

### Stories and epics

Issues #7 to #12 are the epics and #13 to #29 the stories. The owner decided, on 2026-11-05: a pull request links with `Part of #N`, and a story closes only after the owner approves, with a comment citing the proof for each criterion and the cluster it ran on. An epic closes when all its stories have. No story has closed.

| Linked so far | Stories |
|---|---|
| PR #40 | #13, #14, #15, #16, #17, #18, #19, #25, #27 (partial) |
| PR #4 | #20 (mock data only) |
| PR #89, PR #98 | #28 (deployment only) |
| PR #112 | #14 (role groups and test users) |

Paperclip, the source these drafts were published from, is off for now. Reading the five items it never published to GitHub is parked in #93. Issue #6 records these decisions. Its language review requirement stands and has not been done for any story; closing comments say so.

## Open risks

| Risk | What is known | Guard |
|---|---|---|
| Token spend | The owner stopped a side agent as waste on 2026-11-06, and that night: "pls make sure we are NOT wasting claude token". Two implementers and reviewers each used about 1M fresh input tokens plus 350,000 to 470,000 output | Long work on Codex and Cursor. One Claude agent at a time, only on what blocks the next step. Narrow briefs; agents run only the suites their change touches; the coordinator runs the full suites once, wakes on a waiter, and does not poll |
| **`keycloak-0` restarted again, at 08:58:42 UTC on 2026-11-13 (exit 137), #157** | It ran again from 08:59:37 UTC. OB1's first kind run for #91 was running on the Mac, with the service suite and Codex's container tests, at a load average of 13 to 16. Later kind runs alone (10:26 to 11:05 UTC) gave failed probes of `keycloak-0`, `postgres-0` and `mailpit`, and no restart. cmapi wrote nothing to `keycloak`. Each realm answered 200 at 11:10 UTC. Both restarts on record came while a kind cluster ran on this Mac | **No kind cluster on this Mac while CRC is up, until the owner decides.** OB1 stopped all CRC work and took no action on Keycloak |
| `keycloak-0` on CRC restarted at 20:17:02 UTC on 2026-11-05 (exit 143, then failed probes) | cmapi changed nothing in `keycloak`. A kind cluster was running on the Mac at that time, so test load is not ruled out. Cause unknown. A later short kind run left the count at 1 | No kind cluster during a CRC step. Record the restart count around each one |
| A realm import may restart the shared Keycloak, which has one instance | corp, inkcast-staging and inkcast-prod were imported on 10-28, 10-28 and 11-04 without restarting `keycloak-0`. Red Hat reports restarts on 22.x, 24.x and 26.0.x; CRC runs 26.6.7. The one measured restart took 2 min 42 s for every realm | The owner requires the other realms unaffected and not deleted, and no long outage. Exact names only; compare each realm's status and public key hash before and after; poll through the import; if it restarts, stop and take no action on Keycloak. A `pg_dump` first, approved by the owner, kept outside git and deleted once verified |
| Keycloak's certificate has no Extended Key Usage | macOS's own check refuses it even with the right CA (measured); the ingress certificate passes. Chrome's result is unknown until the owner tries | If Chrome refuses it, reissuing `keycloak-tls` touches the shared Keycloak: the owner's decision |
| An import can start long after its Job is created | `inkcast-prod`'s started about 6.5 days after, `inkcast-staging`'s 5h51m. Cause not known | Bound the wait, and be able to withdraw our own import |
| One review family | Fable is paused. Codex is the only other family that has reviewed so far, and OpenAI's filter stopped Codex on auth and admission checks earlier. Cursor's agent was added that night and has only answered a probe | Each PR states who reviewed. Flag any PR touching auth or admission |
| A bad merge in the config repo puts every Application into deletion | Measured on kind: no namespace lost, but a person must remove each finalizer | `path-authority` check, approver guard, alert (Wave 2 and 3) |
| Argo CD's cluster-wide read of ConfigMaps | 535 on CRC, mostly other projects' | Wave 2 tests narrowing |
| Network policies break DNS on podman kind | Measured, cause unknown. `kind-test.sh` deletes the policy on podman kind only; it ships unchanged. CI's Docker-backed kind shows it blocks another namespace, on a running pod | CRC decides |
| Memory on CRC | Requests 15,525 Mi of 19,543 Mi. The plan adds 832 Mi with Argo CD. An import Job requests 1,700 Mi while it runs, so it must not be scheduled alongside cmapi's 576 Mi | Stop if headroom is under 2 GiB. Import first, alone |

## Open bugs

`issue-register.md` is the full list, with the severity, the class, the parent and the milestone of each. In short, on 2026-11-13:

- **Closed by OB1's merges:** #109, #110, #113, #115 to #126, #136 to #138 (PR #112); #139 (PR #140); #127 to #134 (PR #135); #142 (PR #152).
- **Fixed in an open pull request:** #145, #146 and #164 (PR #163). Closed by OB1's later merges: #141 (PR #153), #91 (PR #158), #154 and #155 (PR #156), #87 (PR #162), #151 (PR #161).
- **Open, for Wave 1:** #94 (the CRC run).
- **Open, for later waves:** #59 to #62, #64, #65, #84, #85, #97 (Waves 2 to 5); #33, #148 to #150 (Wave 6, the portal on the API); #147 (Wave 8); #143 (Spectral lint), #144 (`plugins.yaml`); #92 (the load test).
- **Blocked on the owner:** #157 (PERF-01, the Keycloak restart), #35, #36, #93.
