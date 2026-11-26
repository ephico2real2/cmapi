# Reviewer brief: cmapi PR #729 (closes #727), the OpenShift 4.18+ support audit. One reviewer.

You are the reviewer, from the Codex model family, adversarial. Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-729/` (`head/`, `base/`, `pr.diff`); exclude `examples/`. Read `head/docs/reviews/2026-11-26-issue-727/README.md` in full. Write `r1-report.md`, and put any fix in `r1-outputs/fix.diff`.

**The owner's requirement:** cmapi must work on OpenShift 4.18 and later. There is no 4.18 cluster in the lab, so the proof is documentation and source only.

**The PR** audits 24 OpenShift dependencies against the openshift/* `release-4.18` and newest branches (openshift-docs `enterprise-4.18` and `enterprise-4.22`). It states "OpenShift 4.18 and later" in docs/13 and docs/18, adds one test (direct-authentication SelfSubjectReview), and retracts a NetworkPolicy comment.

**Check:**
1. Pick at least 6 rows, including the NetworkPolicy policy-group label, the Thanos RBAC, `restricted-v2` and ValidatingAdmissionPolicy. Re-fetch each quoted source at its cited commit and confirm the quote and the verdict.
2. Did the audit miss any OpenShift-specific dependency in `cmapi/src`, `deploy/` or `cmapi-portal-ui`? Use grep for `openshift.io`, `route`, `scc`, `imagestream`, `console` and `monitoring`.
3. Is the stated support range honest about the CloudNativePG and Kyverno operator ranges?
4. Does the new test fail without the fallback?
5. Is the NetworkPolicy comment retraction correct?

**Run:** from `head/cmapi`, `PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`, for the new test file.

**Severity and fixes.** High and Medium findings need the full fix. Keep it narrow. No repository, GitHub or cluster changes. End with a five-line summary.
