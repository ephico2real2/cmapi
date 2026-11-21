# 429 · What should ci/kyverno do on a hand-made PR?

**Decision.** Fail `ci/kyverno` when a rendered policy reports a violation on a PR outside cmapi's request flow, including in `[Audit, Warn]`. Report the policy, file and Kyverno message on the PR. On a cmapi request PR, its approvers have already seen the plan's findings. An audit violation remains a warning there, and a Deny violation fails. A policy that cannot compile or gives no result for a matched file fails in either flow. An environment with no rendered bundle still reports that Kyverno is off.

The check evaluates the proposed merge tree, including all namespace folders. As corrected by #516, audit violations fail a hand-made PR only in namespace folders changed between the test merge and its first parent (`git diff --name-only HEAD^1 HEAD`); unchanged folders warn, and an unavailable diff treats every folder as changed and says so in the output. A clean policy-maintenance PR can pass without a cmapi request. Local runs and pushes to main continue to report according to the rendered cluster mode. Issue #227 tracks enforcement of merge restrictions. A failed check gives the reviewer evidence to decline a merge even while a writer can override it.

## Options considered

| Option | Consequence |
| --- | --- |
| Fail a policy violation on each non-bot PR (chosen) | Gives the reviewer a failing file annotation on the path that bypasses cmapi's validation. Reuses the deployed bundle and keeps the approval semantics of #249, #342 and #343. |
| Require `cmapi/check` on every PR | The worker knows the approved request and posts this status on its head. A maintainer's policy PR has no such request, even when valid. The repository lacks the branch protection that would require the status. Making `ci/kyverno` wait for it would also create a cycle when host CI is enabled. |
| Rely on the README's prohibition on hand edits | Documents who may write `clusters/`, but a violating hand edit still receives the same green check. The README also explicitly allows reviewed changes to `policies/`. |
| Fail audit findings on bot PRs too | Would reject a finding that the configured audit mode allows an approver to accept. Changing the cluster to Deny would also change admission for an issue confined to PR feedback. |

## Recognising a cmapi request

The bot pushes one single-parent commit to `cmapi/<cluster>/<requestId>` in the base repository. The workflow reads GitHub's event payload for the head repository, branch, SHA and number of PR commits. A fork or a count other than one takes the strict path, including a human change followed by a bot-authored commit. Depth 3 includes GitHub's test merge, the event head and the head's parents. Git checks the parent count, identity and parsed trailers on the event head. A merge on the PR branch takes the strict path even when that merge is the only commit unique to the PR. Kyverno reads manifests from the merge checkout.

The author and committer must both be `cmapi-git-bot` with the same email, as cmapi's Git writer sets them. Exactly one `Cmapi-Request-Id` trailer must match the request ID in the branch name. The email is configurable. The PR author's login identifies the owner whose token opens the PR. Neither field establishes that cmapi wrote the commit.

A copied trailer on a human-authored commit still produces a failing check for a violation. The same applies to a trailer mentioned in the message body, a duplicate trailer or an ID for another request. **These markers are unsigned.** A writer in the base repository who imitates the complete commit and branch convention can receive the bot's audit warning. The markers select CI severity. Approval and exact plan verification belong to the worker's `cmapi/check`. Authenticating the bot independently would require a trusted identity, for example verifying a signature against the bot's own key.

## Evidence

Sources read on **2026-11-19**.

- The config repository's README says “People do not edit it by hand” and “changed by reviewed pull requests” for policy changes. Its “No branch protection” section records the GitHub plan constraint. Read from the local checkout at this commit. [Config repository README](https://github.com/ephico2real2/cmapi-cluster-configs/blob/3e4bad30202f273b5ad452247e0d0db82f0916f6/README.md)
- The handover records “the commits already name `cmapi-git-bot`” and explains why the owner's login appears on bot PRs. The Git writer specifies “one commit on its parent” and supplies the branch, configurable author email and request trailer. [Handover, 2026-11-16 §6 item 4](../../../HANDOVER-AND-RESUME.md) · [Git workspace](../../../cmapi/src/cmapi/core/git/workspace.py) · [Commit message](../../../cmapi/src/cmapi/jobs/delivery.py)
- The worker documents “The local validators still run once CI has finished”. It waits for host CI when enabled, verifies the approved head and plan, then posts the status when configured. [Worker PR checks](../../../cmapi/src/cmapi/jobs/pr_checks.py)
- The pinned checkout action defines `fetch-depth` as “Number of commits to fetch” with default 1. [actions/checkout action definition](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/action.yml)
- Kyverno's pinned CLI reference describes `--policy-report` as “Generates policy report when passed”. It also documents that `--audit-warn` “Currently has no effect”. Reading the per-resource JSON report lets CI distinguish a violation from an evaluation error without rewriting admission policy. [Kyverno v1.20.0 apply reference](https://github.com/kyverno/kyverno/blob/v1.20.0/docs/user/cli/commands/kyverno_apply.md)
- GitHub documents “After enabling required status checks, all required status checks must pass before collaborators can merge changes into the protected branch.” It identifies a verified signature as evidence that “The commit is signed and the signature was successfully verified.” These are separate controls for enforcing merge requirements and authenticating an author. [GitHub branch protection](https://github.com/github/docs/blob/main/content/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches.md) · [GitHub commit signatures](https://github.com/github/docs/blob/main/content/authentication/managing-commit-signature-verification/about-commit-signature-verification.md)

On main (`05859d12`), Kyverno v1.20.0 produced `1 namespace folders, 0 errors, 1 warnings` and exit 0 on the same invalid team label under both authors. The script and workflow accepted no PR origin input. The live private repository's checks could not be read on 2026-11-19. The observed result is from a local fixture.
