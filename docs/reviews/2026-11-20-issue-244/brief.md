# Design brief: cmapi #244 (design only; no code)

You are one of two independent designers. Another model designs the same thing without seeing yours; the coordinator arbitrates. Write a design, not code.

## The issue
cmapi #244 (full text in `cmapi-244.json` beside this brief): after #212, cmapi renders its Kyverno bundle from its own configuration at plan time, and `cmapi-tools policies check` fails CI when the bundle committed in `cmapi-cluster-configs` (`policies/env/<env>/`) is stale. Someone still has to run `cmapi-tools policies render` and open the pull request by hand when the configuration changes. The owner wants no manual policy work. #212's two designs proposed: on start and on `POST /admin/reload`, cmapi compares its render with `policies/env/<env>/` in Git; when they differ it opens one bot PR, approved by approver-platform (as the tier rerender does for namespaces); each plan records the bundle hash it validated against, and a plan is not published while the cluster's policies Application reports another hash (Codex, Q7).

## Read first (in the cmapi repository, `main`)
- `docs/reviews/2026-11-14-issue-212/README.md` (the arbitration, especially Q5 and Q7), `design-codex.md`, `design-opus.md`.
- docs/02 "Kyverno" section (search "policies Application", "Not built here: the bot's pull request"), docs/02's approval rules and Git delivery sections, docs/14 (roles and permissions), docs/16 (data model), docs/19 (Git connections).
- Code: `cmapi/src/cmapi/tools/policies.py` (render/check), the policy generator (`core/policygen*` or where `policies render` gets its bundle), the Git delivery layer `cmapi/src/cmapi/core/git/` (workspace, base, adapters; it writes only `clusters/<cluster>/` today), `cmapi/src/cmapi/jobs/` (delivery, pr_checks), the approval rules engine, `core/tiers.py` (the tier rerender, if built), `cmapi/src/cmapi/core/db/migrations/`.
- The config repository template: `examples/cluster-configs/` (README, `clusters/*/argocd/policies-application.yaml`, `.github/`), and #429's decision `docs/reviews/2026-11-20-issue-429/README.md` (how CI treats a cmapi request PR vs others).

## What the design must settle (each with options, the choice, and why, citing primary sources read with the date)
1. The trigger: start, `POST /admin/reload`, a periodic check, or a combination; multiple replicas and instances (each instance renders only its own environments) must not open duplicate PRs; idempotency when a PR is already open.
2. The bot's Git path for files outside `clusters/<cluster>/` (`policies/env/<env>/`): branch naming, the commit trailer, how the existing delivery job, sweeper and reconcile handle a non-namespace change, what stays forbidden.
3. The request model: is a policy change a ChangeRequest (plugin, action, approval rule `approver-platform`), with plan, approval and audit like other writes? Data model changes (migration), API surface (new or existing endpoints; contract additive), permissions.
4. The bundle hash: how it is computed (canonical, stable across key order and platforms), where each plan records it, what "the cluster's policies Application reports another hash" means concretely (Argo CD Application status `sync.revision`, a hash annotation on the rendered files, or cmapi reading the cluster's live policies), and what happens to plans and auto-approval while they differ (refuse, warn, or hold) — including clusters in `apply` mode without Argo CD.
5. Failure and edge cases: the render changes again while a policy PR is open; the PR is rejected or closed; Git or the host is down; a hand change to `policies/` (the README allows reviewed policy PRs); an environment set to `off`.
6. Observability: events, metrics, and what the portal's Policies tab shows (bundle expected vs live, already built in #384).
7. A delivery plan: the smallest slices, each independently mergeable, with the test that proves each.

## Output
One file, `design.md`, in your folder: at most about 300 lines; a decision table (question, options, choice, reason, source); concrete names (tables, columns, endpoints, events, metrics, files); the slices; what you could not verify. Cite cmapi files as `path:line` read from the code, never from memory. No code beyond short signatures or YAML shapes.
