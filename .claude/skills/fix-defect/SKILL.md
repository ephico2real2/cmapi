---
name: fix-defect
description: How every defect or bug found on cmapi gets handled - logged as a GitHub issue with a research mandate, linked to its parent issue, researched and fixed by a background agent, reviewed by reviewer 1 and reviewer 2, then validated and tested by the coordinator as arbiter before it merges. Use whenever a defect, bug, failing check or wrong behaviour is found, by anyone, at any stage, including in a review, in CI or on a pull request not merged yet.
---

# /fix-defect: every defect is logged, researched, reviewed and proven

The owner's rule, 2026-11-06. No defect is fixed or dropped without an issue, however small and whoever found it. That includes a reviewer's finding on an unmerged pull request, and a CI failure.

The main session is the arbiter. It files, briefs, validates, tests, decides and merges. It does not write the fix.

## 1. Log it, at once

File the issue as soon as the defect is seen, before fixing anything:

- **What is wrong**, **where** (`file:line`), and **how to prove it** (a command or test that fails today).
- **Measured or inferred:** say which, and which cluster or environment it came from. Say so if it has not been reproduced yet.
- **Research mandate:** `Research: search the primary sources, compare the options, choose the industry best practice, fix the cause rather than the symptom, and record the choice and its sources.`
- **Parent:** `Part of #N`, naming the wave issue or story it belongs to.

Then comment on the parent with the new issue's number, so the parent shows everything found under it. Add the issue to `build-tracker.md`'s open bugs when the tracker is next updated.

## 2. Research and fix, in a background agent

Start a fresh agent per `CLAUDE.md`, "Who does what", in the background. Related defects may share one agent, with one issue per defect. Its brief:

- The issue numbers, and an isolated worktree or branch.
- The research mandate: primary sources first, and the options it rejected, with why.
- A test that fails before the fix and passes after. The test exercises real behaviour; searching a file for a string doesn't count.
- The limits: nothing written to CRC, LDAP or Keycloak; explicit `--kubeconfig`; no secrets; a permission refusal stands.
- Report the solution, its sources, each test's before and after, and what is measured, inferred and not tested.

## 3. Review, the same way as all reviews

From `CLAUDE.md` and `adversarial-review`, on exports, never in a repository:

1. **Reviewer 1** (Codex): a narrow brief of exact files and claims, returning the full code of each fix and test.
2. **Reviewer 2** (a separate Opus 5.5 at `high`, not the author): checks each of reviewer 1's snippets against the design and the code, updates them, and reports with full code what reviewer 1 missed.

Anything new a reviewer finds goes back to step 1 and gets its own issue.

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

## Report faithfully

Tell the owner what was found, what was fixed and how it was proven, and what isn't proven yet. A defect that can't be fixed yet stays open and is named as open.
