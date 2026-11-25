---
name: fix-defect
description: How every defect or bug found on cmapi gets handled - logged as a GitHub issue with a research mandate and a severity, linked to its parent issue; High, Medium and security defects are fixed in the session by a background agent and reviewed (reviewer 1 only for small non-security fixes, else reviewer 1 and reviewer 2), Low ones go to Backlog and are batched; then validated and tested by the coordinator as arbiter before it merges. Use whenever a defect, bug, failing check or wrong behaviour is found, by anyone, at any stage, including in a review, in CI or on a pull request not merged yet.
---

# /fix-defect: every defect is logged, researched, reviewed and proven

The owner's rule, 2026-11-06. No defect is fixed or dropped without an issue, however small and whoever found it. That includes a reviewer's finding on an unmerged pull request, and a CI failure.

The main session is the arbiter. It files, briefs, validates, tests, decides and merges. It does not write the fix.

## 1. Log it, at once

File the issue as soon as the defect is seen, before fixing anything:

- **What is wrong**, **where** (`file:line`), and **how to prove it** (a command or test that fails today).
- **Measured or inferred:** say which, and which cluster or environment it came from. Say so if it has not been reproduced yet.
- **Research mandate:** `Research: search the primary sources, compare the options, choose the industry best practice, fix the cause rather than the symptom, and record the choice and its sources.` Search first, then read each primary source itself and quote it with its URL and date; a search summary or the model's memory is not a source (the owner, 2026-11-20).
- **Parent:** `Part of #N`, naming the wave issue or story it belongs to.

Then comment on the parent with the new issue's number, so the parent shows everything found under it. Add the issue to `build-tracker.md`'s open bugs when the tracker is next updated.

**Triage on filing.** This is the owner's rule from 2026-11-25; see `CLAUDE.md`, "File every defect; fix by severity; stories first".

- **Fix now** when the defect is High or Medium, touches security (auth, tokens, crypto, supply chain, image builds, migrations), or blocks a story's proof. Label it `In-Progress` and go to step 2 in the same session.
- **Fix later** when the defect is Low and not about security. Label it `sev:low` and `Backlog`. Fix it with other Low defects in one batched pull request when there is room, or at once if it sits in lines the current change already edits.
- **Say the severity and why** in the issue.

## 2. Research and fix, in a background agent

Start a fresh agent per `CLAUDE.md`, "Who does what", in the background. Related defects may share one agent, with one issue per defect. Its brief:

- The issue numbers, and an isolated worktree or branch.
- The research mandate: primary sources first, and the options it rejected, with why.
- A test that fails before the fix and passes after. The test exercises real behaviour; searching a file for a string doesn't count.
- The limits: nothing written to CRC, LDAP or Keycloak; explicit `--kubeconfig`; no secrets; a permission refusal stands.
- Report the solution, its sources, each test's before and after, and what is measured, inferred and not tested.
- Long runs (suites, mutants, builds, rollouts) go in the background, and the agent waits for their notification. Never a sleep or `until` loop: each wake re-reads the whole context.

## 3. Review, the same way as all reviews

From `CLAUDE.md` and `adversarial-review`, on exports, never in a repository:

1. **Reviewer 1** (Codex): a narrow brief of exact files and claims, returning the full code of each fix and test.
2. **Reviewer 2** (a separate Opus 5.5 at `high`, not the author): checks each of reviewer 1's snippets against the design and the code, updates them, and reports with full code what reviewer 1 missed.

**Size the review by risk** (the owner, 2026-11-25):
- **Reviewer 1 only** for a small fix: about 50 lines or fewer of code and manifests (tests and records not counted) that touches no security, auth, token, crypto, supply-chain, image-build or migration code.
- **Both reviewers** for everything else.
- **Say which in the brief and in the PR.**

Anything new a reviewer finds goes back to step 1, gets its own issue, and is triaged there: Low and not about security goes to Backlog, unless it sits in the lines the pull request already changes.

## 4. Arbitrate: validate and test

Reports are claims until checked. Before accepting anything, the coordinator:

- Reproduces the failure, and reads every line a patch removes from a test.
- Applies the patches to a fresh export, with no fuzz, and runs the full suites itself, mutants included.
- Decides each fix with its reason. A failing test stands unless it is shown to be wrong, and a finding with one is never dismissed by opinion.
- Applies accepted patches unchanged, one commit each. A patch that doesn't fit goes back to reviewer 2.

## 5. Close it

- The pull request says `Closes #N` for each defect, `Part of #parent`, and who wrote what.
- Save the review record in `docs/reviews/`.
- Merge once CI is green on the exact head and the review has passed (the owner, 2026-11-06). Merging does not authorize anything on CRC.
- Close a defect only through its merged fix, with the proof cited. Stories close only on the owner's approval.

## 6. Clean up after the merge

The owner, 2026-11-25. Scratch from reviews had grown to 45 GB in the workbench and slowed the Mac.

Once the pull request has merged and its review record is in `docs/reviews/`, the coordinator removes that pull request's scratch in the same session:

- **Remove** the reviewers' export `workbench/cmapi/review-<PR>/`, the implementer's `workbench/cmapi/wt-<issue>-outputs/`, and its worktree (`git worktree remove`).
- **First save** any uncommitted change in the worktree, with `git diff`, into `workbench/cmapi/worktree-archive-<date>/`.
- **Keep:**
  - the shared test environments (the venv built from `main`'s lock);
  - the latest two CRC run folders;
  - anything that belongs to a pull request or issue that is still open.
- **Never remove** a path that another running agent named in its brief.

`~/.claude/skills/sweep-stale/sweep-stale.py --workbench <dir>` (diagram-kit's `sweep-stale` skill) reports any folder whose pull request or issue is closed, as a safety net. It deletes only when told to.

## Report faithfully

Tell the owner what was found, what was fixed and how it was proven, and what isn't proven yet. A defect that can't be fixed yet stays open and is named as open.
