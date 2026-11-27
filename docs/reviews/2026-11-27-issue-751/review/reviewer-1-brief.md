# Reviewer 1 brief: cmapi PR #752 (closes #751, part of stories #18 and #19), deliverer-agnostic delivery, `delivery.mode: gitops`. A delivery and write path: two reviewers.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high designed and wrote it alone, so this PR had one model family. Reviewer 2 (Opus) checks your fixes after you, on PostgreSQL.
- Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-752/` (`head/`, `base/`, `pr.diff`).
- Read in full: `head/docs/reviews/2026-11-27-issue-751/README.md` (the design, D1 onward), `coordinator-assessment.md` and `should-cmapi-apply-directly.md` in the same folder.
- Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The owner's decisions, 2026-11-27:**
- "It shouldn't matter what apply the rendered yaml".
- Asked whether to build a deliverer-agnostic mode next: "Build gitops mode now".
- Asked whether the design choice made sense: "Yes".

**The claim:**
- **The mode.** A new `delivery.mode: gitops`: cmapi merges, then confirms by a full read of the approved plan (`core/plan_read.py`), whatever applies the folder. The read covers the Namespace's governed labels and annotations, every ResourceQuota, every LimitRange (after the API server's defaulting, ported from `SetDefaults_LimitRangeItem`) and each removed object's absence.
- **Every mode.** All three modes use the read. `argocd` keeps its Argo CD gate, and stays the default.
- **Optional deliverer signal** (`delivery.signal`, Argo CD or Flux): it shows beside the differences and is never required.
- **Timeouts.** At `syncTimeout`, `sync_failed` names the differences. If only unpruned objects remain, the request waits in `awaiting_prune` with a notice to an operator.
- **Config checks.** An unknown mode or signal stops the start. The chart requires `delivery.gitops.delivererServiceAccount`, unless the operator acknowledges an uncontained deliverer.
- **Case 2 was retracted:** the namespace lock (`OPEN_STATES`, `uq_cr_open_namespace`) holds through `merged`, `awaiting_prune` and `sync_failed`.

**Confirm or refute, with tests:**
1. **False `synced`.** Can the read ever confirm a plan that was not fully applied?
   - Check `liveOnlyKeys` and the D3 skip rules, too broad or too narrow.
   - Check quantity canonicalisation (`qty`) and the LimitRange defaulting port against the Kubernetes source: fetch `pkg/apis/core/v1/defaults.go`, `SetDefaults_LimitRangeItem`, at the release that OpenShift 4.18 uses (Kubernetes 1.31) and quote it.
   - Check an object present but of a different kind or name.
2. **False failure.** Do server-added keys, Argo CD tracking labels and annotations, Kyverno mutations, or a ResourceQuota's `status` fields ever block a correct apply? Check `liveOnlyKeys` covers Argo CD's tracking (`argocd.argoproj.io/*`, `app.kubernetes.io/instance`).
3. **Deletes and prune.** Is absence read correctly: NotFound against a `Terminating` namespace? Does `awaiting_prune` ever loop forever, or skip the operator notice?
4. **The `argocd` and `apply` modes** behave as on base, except the stricter read. Does that stricter read break an existing CRC `apply` flow (labels that cmapi does not render but the deliverer adds)?
5. **Config.** Fail-closed on unknown modes; backward compatibility for configs without `delivery.mode`; the chart guard.
6. **The tests can fail.** Run them on base and head, plus mutants of the read's comparisons and of the timeout and prune branch.

**How to run.** Your sandbox may not reach PostgreSQL; if so, say it at the top and do not substitute SQLite. Service tests, from a tree's `cmapi/`:

`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_752 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`

Core tests: `PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q`. Chart: `bash deploy/render-test.sh`.

**Severity and fixes.**
- High and Medium findings need the full fix and a test that fails before and passes after.
- Keep fixes narrow, and **separate anything that predates the PR**.
- Low findings, and anything outside the changed lines, go to Backlog.

Quote the primary sources (Kubernetes, Argo CD, Flux) with their URLs. No repository, GitHub or cluster changes. End with a five-line summary.
