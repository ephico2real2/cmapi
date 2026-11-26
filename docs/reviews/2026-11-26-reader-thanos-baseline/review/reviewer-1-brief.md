# Reviewer 1 brief: cmapi PR #734 (closes #724, part of story #22), the reader's own Thanos grants on every cluster. RBAC and security: two reviewers.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high wrote it. Reviewer 2 (Opus) checks your fixes after you, on PostgreSQL.
- Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-734/` (`head/`, `base/`, `pr.diff`).
- Read `head/docs/reviews/2026-11-26-reader-thanos-baseline/README.md` in full.
- Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The owner's words, 2026-11-26:** "cmapi must grant it own permission to the pods with or without openshift coo", and "when we onboard a cluster to cmapi. The service account must have right to the remote cluster thanos". cmapi must support OpenShift 4.18 and later.

**The claim:**
- The baseline for every managed OpenShift cluster (`examples/baseline/cmapi-reader-rbac.yaml`) drops the cluster-wide `cluster-monitoring-view` binding and the all-namespaces Route rule.
- In their place it grants, in `openshift-monitoring` only: `get` on Route `thanos-querier`, a RoleBinding of the platform Role `cluster-monitoring-metrics-api`, and `create localsubjectaccessreviews` (`cmapi-reader-grant-check`).
- Import check 6 (`core/registry.py`), when `usage.source: thanos`: discovery of `monitoring.coreos.com/v1`, then a LocalSubjectAccessReview for each grant. Each review names only the reader's ServiceAccount groups, never `system:authenticated`, and skips the Route when the cluster has a `thanosUrl`.
- A missing grant becomes a `usage:` finding. The cluster stays connected, and its usage reads `unavailable` with the finding as the reason, with no Thanos query. The check also runs on `:probe`.
- CRC's reader manifests and the CRC proof follow.

**Confirm or refute, with tests:**
1. **Least privilege.** Is `create localsubjectaccessreviews` in `openshift-monitoring` the narrowest way to check the grants? Compare SelfSubjectAccessReview, which needs no grant and does not include `system:authenticated` only if you can prove so. What can a holder learn with it? Quote the Kubernetes `release-1.31` authorization docs or source.
2. **Correctness on OpenShift 4.18 and the newest:** the Role name `cluster-monitoring-metrics-api`, kube-rbac-proxy's check on `prometheuses/api` `k8s`, and the Route name. Read the pinned `release-4.18` sources the README cites.
3. **The finding's effects:** usage `unavailable` must not block namespace creation or reads (docs/01: a create makes no Thanos query). Does `:probe` clear the finding once the grant is applied? Does a transient API error during the review produce a wrong finding, or a crash?
4. **Behaviour beyond the purpose:** clusters with `usage.source: none` and kind are unchanged. CRC's proof still passes its checks (`deploy/tests/crc-scripts-test.sh`).
5. **The tests can fail.** Run them on base and head, plus mutants of the group list (adding `system:authenticated`) and of the skip of the Route review.

**How to run.** Your sandbox may not reach PostgreSQL; if so, say it at the top and do not substitute SQLite. Service tests, from a tree's `cmapi/`:

`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_734 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`

Core tests: `PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q`. Shell tests: `bash deploy/tests/crc-scripts-test.sh`.

**Severity and fixes.**
- High and Medium findings need the full fix and a test that fails before and passes after.
- Keep fixes narrow, and **separate anything that predates the PR**.
- Low findings outside the changed lines go to Backlog.

Fetch and quote primary sources: the URL, the ref and the sentence. No repository, GitHub or cluster changes. End with a five-line summary.
