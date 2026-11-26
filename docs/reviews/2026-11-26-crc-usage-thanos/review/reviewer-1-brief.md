# Reviewer brief: cmapi PR #726 (part of #22), CRC's usage source set to Thanos, with least-privilege RBAC. Security (RBAC).

You are the reviewer, from the Codex model family, adversarial. Opus 5.5 high wrote it. Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-726/` (`head/`, `base/`, `pr.diff`). When you diff, exclude `examples/`. Read `head/docs/reviews/2026-11-26-crc-usage-thanos/README.md`. Write `r1-report.md`, and put any fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The change.**
- CRC's `capacity.yaml` gets `usage: {"source":"thanos"}`, using the default Route discovery.
- In `openshift-monitoring` only, `environments/crc/reader/00-cmapi-reader.yaml` adds:
  - Role and RoleBinding `cmapi-reader-thanos-route`: `get` on the one Route;
  - RoleBinding `cmapi-reader-metrics-api` to the platform Role `cluster-monitoring-metrics-api`.
- `crc-rollback.sh` deletes all three; `crc-proof.sh` checks them with a SubjectAccessReview that leaves out `system:authenticated`.
- docs/13 and docs/18 are updated.

**Confirm or refute:**
1. **Least privilege.** Is `cluster-monitoring-metrics-api` the smallest documented role for querying Thanos Querier on OpenShift 4.22? Quote the openshift-docs and cluster-monitoring-operator sources at their 4.22 branches. Is the Route `get` needed at all?
2. **Rollback** removes exactly what was added, and nothing shared.
3. **Plain manifests and render:** the tests cover the change, and fail on base.
4. **Scope:** kind, examples and the chart are unchanged.
5. Anything that would make cmapi fail closed or open wrongly when Thanos is down.

**How to run.** Manifest and config tests, from `head/cmapi`: `PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`. Also `deploy/render-test.sh` and `deploy/tests/*.sh`, if they run without a cluster.

**Severity and fixes.** High and Medium findings need the full fix and a test. Keep it narrow. No repository, GitHub or cluster changes. End with a five-line summary.
