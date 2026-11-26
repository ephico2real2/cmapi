# Reviewer 2 (Opus 5.5 high) of cmapi PR #722: #719 and #720

PostgreSQL 16 on `127.0.0.1:55432` was reachable, using database `cmapi_r2_722`. Every result below was measured there, on plain copies `r2-head/` and `r2-base/`, with the brief's commands. Each tree ran from its own `cmapi/` folder. Nothing in the repository, on GitHub or on a cluster was changed.

## What the design says

- docs/01:260 (head snapshot, 2026-11-26): "reverted | :revert on a sync_failed request; the revert is a new request through the same approval rules".
- docs/01:534: "A matching request still goes to humans when it is a delete [...] when the plan has warnings, or when the team's daily allowance is used."
- docs/01:544: "An extension within the limits follows the environment's change rule; going past them, or making a namespace permanent, adds approver-platform." docs/01:550: "Total lifetime | 180 days from creation".
- docs/02:1345: "networkExposure (the new quota has more services.loadbalancers or services.nodeports than Git holds; for a new namespace, more than the tier gives)". docs/02:1349: "The tier's value of services.loadbalancers and services.nodeports stays 0."
- docs/01:262: "Git cannot bypass cmapi. The bot is the only account that can merge under clusters/."
- `pr_checks.py:102`: "In audit a Kyverno finding is a warning [...]: the plan showed it and the approvers accepted it, so the PR check reports it and does not fail".
- `routers/requests.py:257`: `c.cfg.roles.require(who, "requests:retry", row.env)`.

## Measurements: head and base, same scenario

The measurement script is `r2-outputs/test_r2_722_measure.py`. Raw output is in `r2-outputs/measure-r2-head.jsonl` and `r2-outputs/measure-r2-base.jsonl`.

| Case | Forward | base | head |
|---|---|---|---|
| S0: revert of the delete of a clean small dev namespace | dev-create, auto, 0 | **dev-change, 1 approver-platform (sensitiveKeyChanged)** | dev-create, auto:baseline-rnd-namespace, 0 |
| M1: the same, with a validator warning | dev-create, 1, no auto | dev-change, 1 (from the sensitive key, by accident) | **dev-create, auto, 0** (warnings `[]`, validator not called) |
| M4: the same, with expires-at 200 days out | dev-create, 2 (expirationBeyondLimits) | dev-change, 1 | **dev-create, auto, 0** |
| M4b: the same, with an expired date (10 days ago) | (refused at create) | dev-change, 1 | dev-create, auto, 0 |
| M2: facts of the S0 revert | no tierChange, no quotaIncreasePct, keyClasses [governed] | tierChange up, quotaIncreasePct 100.0 | tierChange up, quotaIncreasePct 100.0, keyClasses [governed, reserved, system] |
| H1: prev with a quota and no namespace.yaml (hand-made), Namespace protected now | — | update, dev-change, 1 (sensitiveKeyChanged) | the same as base |
| H2: cluster moved dev to rnd before the revert | rnd-create, auto | update under dev, 1 | create under **dev**, auto, clusterLabels from today |
| M5: team label removed from Git (hand edit), revert of create | — | delete, team payments (row.team) | the same as base |
| M3a: second unscoped quota with nodeports 0; catalog drops the key; label change | — | dev-change, none-required | dev-change, +1 networkExposure |
| M3b: the same second quota; catalog raises nodeports to 1; label change | — | **+1 networkExposure** | +1 networkExposure |

## Findings and rulings

| # | Codex | Severity | Scope | Ruling |
|---|---|---|---|---|
| H1 | Nonempty prev with no Namespace treated as an update | Low | — | **Rejected.** Only a hand edit in Git reaches it. A plan never leaves a folder with files and no namespace.yaml: a create writes it, an update needs it and a delete removes everything (#616). docs/01:262 says the bot alone merges under clusters/. Head and base measured the same: 1 approver-platform (sensitiveKeyChanged), never auto. |
| H2 | Today's cluster labels with the historical environment | Medium | Predates | **Separate.** Base already used `row.env` for every revert. Head adds today's labels, which is correct for a request judged today. On head the moved cluster's revert is auto-approved as `dev-create` while the cluster is rnd. The fix refuses the revert when the cluster's environment is not `row.env` (`:revert` was authorized for `row.env`, requests.py:257), when writes are off, or when the plugin is not offered. |
| M1 | Warning guard dropped on the newly eligible create | Medium | **In scope** | **Fixed.** Head made the restore a create that `baseline-rnd-namespace` can match, with `warnings: []` and no validator call. Base gave 1 by accident; head gives 0, where forward gives 1. The fix validates a restored create against the current folder and carries the findings into `facts.warnings` and the plan. It adds no refusal, because CI still fails an error. The update path predates the PR and is in the separate patch. |
| M2 | Create restore carries change-only facts | Low | **In scope** (head's create path) | **Fixed** (one line). No shipped rule distinguishes them (`quotaIncreasePct > 100` is false at 100.0), but a restore judged as a create should not carry tierChange or quotaIncreasePct. The keyClasses difference (system and reserved keys) is not fixed: no shipped rule reads keyClasses for plugin namespaces, and base's update reverts already have it. It is described only. |
| M3 | #720 counts removal from cmapi's quota while a sibling still bounds the key | Low | — | **Rejected as a defect.** docs/02:1345 compares "the new quota" with Git, quota by quota. Base already flags a numeric raise in cmapi's quota while a sibling binds tighter (M3b, measured on base). Head treats a removed bound the same way, and the error is fail-safe (one extra approver-platform). Codex's fix would make removal namespace-wide and leave raise per-quota, which is inconsistent. It also needs an instance catalog that breaks docs/02:1349 ("stays 0") or a revert to an older render. |
| M4 | Restores miss expiration approvals | Medium | **In scope** for the create; predates for a change | **Fixed** for the create path: head's create classification turned base's accidental 1 into 0, where forward gives 2. The new `ExpirationRules.plan_restore` gives a create's `expirationAction`/`expirationBeyondLimits` and counts the lifetime from the namespace's creation on its cluster, or from today. It does **not** repeat the create-time refusals, so the revert of an expired namespace's delete still opens. The change path (restoring permanent is a :makePermanent; :set; :extend) is in the separate patch. |
| M5 | Missing target team replaced by the parent's team | Low | Predates | **Rejected as a fix.** Head equals base when the label is missing (measured). Codex's `team: None` makes `submit` skip the daily allowance (`pipeline.py`: `if plan.action != "delete" and plan.facts.get("team")`), which is a weakening. For a delete, no shipped rule and no allowance reads team. A missing team on the delete inverse needs a hand edit. Its refusal of a restored create without a required key goes beyond "the same approval rules". |
| L1 | README: "Main also gave 0 approvals" | Low | **In scope** | **Fixed** with the measured numbers: base gave dev-change, 1 approver-platform, "threshold sensitiveKeyChanged". |

## What Codex missed

1. **Codex's own fix breaks legitimate reverts.** It calls `plan_create`, `plan_set` and `plan_extend` at the restore. These refuse a date in the past (`expiration-in-past`) and a step over 30 days (`expiration-limit`). The revert of an expired namespace's delete would fail every attempt. Measured: the mutant "plan_create at restore" fails `test_the_revert_of_the_delete_of_an_expired_namespace_still_opens` (job error). The same mutant fails the lifetime-from-cluster test.
2. **Codex's M5 fix weakens the daily allowance** (above). Its M1 fix adds refusals on validation errors and missing required keys. Those go beyond the design's "same approval rules".
3. **Codex's expiry fix and the PR count the lifetime from different days.** docs/01:550 says "180 days from creation". When the delete did not sync, the namespace is still on the cluster with its original creation day. Counting from today would miss an over-age restore. Test: `test_a_restored_lifetime_counts_from_the_namespace_on_the_cluster`.
4. **The PR's tests let three mutants survive.** Each now has a test: reading the parent team (the fixture's teams were equal), adding delete facts to a change revert (now asserted absent), and LoadBalancer dropped from `exposure_raised` (the revert test is now parametrized over both keys).
5. **H2's real impact on head is an auto-approval under the stale environment** (measured: `dev-create`, auto, on a cluster now rnd), not a slot difference.
6. **Low, described only:** a deterministic refusal in `open_revert` (protected namespace, the environment check) is retried up to MAX_ATTEMPTS before its final error. This predates the PR; capacity-exceeded does the same.
7. **Forensic note on my own patch:** my first draft attached the delete branch's `else` to the new `if action == "create"`, so an update revert took delete facts. I caught it on re-read and fixed it before any result was recorded. `test_the_revert_of_a_change_reads_the_restored_team_and_no_delete_facts` now kills that shape.

## Patches

**`r2-outputs/fix.diff`** (against `head/`; `git apply --check` passes). It touches `pipeline.py` (`restore_facts`), `open_pr.py`, `expiration/rules.py` (`plan_restore`), both PR test files and the README. The new tests are:

- `test_a_restored_create_carries_no_quota_change`
- `test_a_restored_create_with_a_warning_goes_to_the_approvers`
- `test_a_restored_create_past_the_lifetime_adds_approver_platform`
- `test_the_revert_of_the_delete_of_an_expired_namespace_still_opens`
- `test_a_restored_lifetime_counts_from_the_namespace_on_the_cluster`
- `test_the_revert_of_a_change_reads_the_restored_team_and_no_delete_facts`
- the LoadBalancer case of the exposure revert test

**`r2-outputs/separate-revert-hardening.diff`** (on top of fix.diff; checked). It refuses a revert on a cluster that moved environment or has writes off, and checks that the plugin is offered. It validates every restore, not only a create. It gives a change restore its expiry facts: makePermanent adds approver-platform, set and extend are counted by lifetime, and nothing refuses. Its tests are in `tests/service/test_revert_hardening.py` (4).

## Results (PostgreSQL 16, `cmapi_r2_722`)

| Run | Result |
|---|---|
| PR's 6 tests: base / head | 6 failed / 6 passed |
| New in-scope tests on plain head | 5 failed (the 2 test-gap tests pass on head and kill their mutants) |
| fix tree: revert, exposure, sizing, drift, custom tier, recovery, delivery, short names, expiry suites, flow | 195 passed |
| Mutants on the fix (no validation; plan_create at restore; lifetime from today; quota change on create; parent team; delete facts on a change; nodeports only) | 7 of 7 killed |
| Separate tests before / after the separate patch | 4 failed / 4 passed; with the suites above, 199 passed |
| `tests/core` (venv-ref): fix tree / separate tree | 843 passed, 113 skipped / 843 passed, 113 skipped |
| `test_doc_citations` | Fails on plain head too: the copies are not Git checkouts (`git ls-files` exit 128). This is environmental. |

## Five-line summary

1. In scope and fixed: M1 (warning guard), M4 for the create path (lifetime from cluster creation, no refusals), M2 (one line), and the README (base measured at dev-change, 1 approver-platform).
2. In the separate patch: H2 (environment moved or writes off), and M1 and M4 on the change path (makePermanent adds approver-platform). Rejected: H1 (hand edit only; head equals base at 1 slot), M3 (per-quota, as in docs/02:1345, and base flags a numeric raise the same way), M5 (Codex's fix skips the daily allowance).
3. Codex missed that its own fix refuses the revert of an expired namespace's delete (plan_create, past date) and weakens the allowance. It also missed that the lifetime counts from cluster creation, and three surviving mutants of the PR's tests.
4. fix.diff: 195 service tests passed, 7 of 7 mutants killed, core 843 passed and 113 skipped. The new tests fail on plain head (5).
5. separate-revert-hardening.diff: 4 new tests fail before and pass after; 199 service tests passed; core 843 passed and 113 skipped. All runs on PostgreSQL 16, `cmapi_r2_722`.
