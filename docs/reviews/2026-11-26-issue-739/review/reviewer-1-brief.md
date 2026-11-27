# Reviewer 1 brief: cmapi PR #742 (closes #739, part of story #26), self-service adoption. An authorization change: two reviewers.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high wrote it. Reviewer 2 (Opus) checks your fixes after you, on PostgreSQL.
- Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-742/` (`head/`, `base/`, `pr.diff`). Exclude `examples/` (symlinks) when you diff.
- Read in full:
  - `head/docs/reviews/2026-11-26-issue-739/README.md`;
  - the adoption design `head/docs/reviews/2026-11-14-issue-26-adoption/README.md`: D10, the new D20, decision 2, and the "PR #733 review" section;
  - `head/docs/reviews/2026-11-26-issue-732/README.md`;
  - docs/14's adoption rows.
- Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The owner's decision, 2026-11-26:** "adopting a namespace is very easy and promote self services ... ask for additional required metadata via the same form or screen so that adoption can be triggered via the api as well with the required fields." The coordinator's reading is on #26:
- requesters with `namespaces:write` may request an adoption;
- approval stays as D10 says;
- missing metadata is optional at adoption and is never forced (decision 2);
- existing keys are never changed by adoption (D3, "as-is");
- it can be added later with the #732 rule.

**The claim:**
1. The 3 adoption routes require `namespaces:write`, through one constant, `ADOPT_PERMISSION`, which is both declared and enforced.
2. `:adopt` takes optional `labels` and `annotations` for keys the live namespace lacks.
   - They are checked by the #732 change rule.
   - A key the namespace already has gets 422 `adoption-key-held`.
   - Each supplied key is rendered and removes its `missing-required-key` finding.
3. `missingKeys` is on each candidate, on the plan's `adoption`, and on `GET namespace` as `git.missingKeys`.
4. The portal has a "Missing metadata" section in the Adopt form, and an "Add missing metadata" alert that opens the change form, unlocking a missing derived or prefix key pre-filled with its exact value.

**Confirm or refute, with tests:**
1. **Authorization.**
   - Can a requester adopt outside their environments? Every route must check the cluster's environment grant, including the replay path (#736 B-2 already notes the replay ordering on all routes, so do not re-report that).
   - Is `x-cmapi-permission` on each operation, and is it what the handler enforces?
   - Did any approval count or auto-approval behaviour change for requesters? It must not. Compare base and head approval slots for the same plan.
   - `selfApproval: true` in dev and rnd lets a requester who is also an approver approve their own adoption. This matches D10 and the shipped rules, and it is put to the owner separately. Report it only if head makes it worse than base.
2. **Supplied metadata.**
   - Can a supplied key overwrite a live key (case, prefixes, label against annotation)?
   - Can it inject a reserved `cmapi.net/*` key, an invalid value, or a derived value that is not exact?
   - Does it survive the D16 re-reads and the delivery uid and resourceVersion checks, without being flagged as drift?
   - Is the supplied metadata part of the approved plan hash, so that a body changed after approval is refused?
3. **The follow-up path.** Is "Add missing metadata" only the #732 PATCH, adding no new write path? Does unlocking keys in `namespaceChange.ts` happen only for a missing derived or prefix key?
4. **Behaviour beyond the purpose:** the existing adoption, create and PATCH behave as on base for an operator, and for a requester apart from the new permission.
5. **The tests can fail.** Run them on base and head, plus mutants of the permission constant, the held-key check and the exact-value rule.

**How to run.** Your sandbox may not reach PostgreSQL; if so, say it at the top and do not substitute SQLite. Service tests run from a tree's `cmapi/`:

`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_742 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`

Core tests: `PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q`.

**Severity and fixes.**
- High and Medium findings need the full fix and a test that fails before and passes after.
- Keep fixes narrow, and **separate anything that predates the PR**.
- Low findings, and anything outside the changed lines, go to Backlog.

Quote the design and primary sources. No repository, GitHub or cluster changes. End with a five-line summary.
