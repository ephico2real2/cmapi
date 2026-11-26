# Reviewer 1 brief: cmapi PR #714 (closes #710), catalog drift. Security, two reviewers.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high wrote it. Reviewer 2 (Opus) checks your fixes after you.

## The export

Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-714/`:
- `head/` is the PR head;
- `base/` is main `2992944`;
- `pr.diff` excludes the `examples/` symlinks.

Read `head/docs/reviews/2026-11-26-issue-710/README.md` in full. Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`. Edit only a copy (`r1-work/`). When you diff the export, exclude `examples/`: `examples/src/cmapi` and `examples/tests` are symlinks, so a recursive diff doubles each file.

## The defect and the claim

**#710:** when the tier catalog no longer matches what Git holds, a label-only change re-rendered the quota from the catalog. The capacity delta was (0, 0), `quotaIncreasePct` was 0, and no approval was needed. Measured: Git held `requests.cpu: 1`, and the change rendered 8.

**The fix:** every change takes its old quota from what Git holds (`core/pipeline.py`), not from `quota_for(env, old_tier)`. A create has none. The capacity delta, #707's usage read, `compare` (`quotaIncreasePct`, `tierChange`) and `networkExposure` all use it. Also:
- a Namespace with no tier label now gets `quotaIncreasePct`;
- the `old_hard or hard` fallback is removed, so a quota where Git holds none counts as 100%.

**Design basis:** docs/02 "Changing a tier", and D9 (`docs/reviews/2026-11-14-issue-26-adoption/README.md`), as the record quotes them.

## Confirm or refute each point, with a test that decides it

1. **No path is left** where a raise of a hard quota escapes the capacity check or the approval rules. Check: create; tier move; metadata change; an explicit `quota` override; `limitRange`; a several-quota folder (#250 and #685's rules); a namespace whose `<ns>-quota` is missing in Git; the revert job; and the expiry delete (#699).
2. **Behaviour beyond the purpose.** Removing `old_hard or hard` makes a quota where Git holds none count as 100%. Does that now require an approval that the design does not want, for example on an adopted namespace or a first quota? Quote docs/02.
3. **Lowering a quota through drift:** is it sized correctly, and does it not reserve?
4. **#707's usage gate** now reads the same baseline. Is it consistent?
5. **Tests can fail.** Run on base and head, plus mutants: the catalog baseline restored, the fallback restored, and `networkExposure` left on the catalog.

## How to run

**Your sandbox may not reach PostgreSQL.** If so, say it at the top. Do not substitute SQLite.

From a tree's `cmapi/`, service tests:

```
CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_714 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider
```

Core tests, in the reference venv only (it has no structlog):

```
PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q
```

## Severity and fixes

- Mark each finding High, Medium or Low.
- Every High or Medium finding, and every Low one inside the changed lines, needs its **full code fix and a test that fails before and passes after**. Check it applies to a fresh `head/` copy with `patch -p1 -F0`.
- Other Low findings go to Backlog.

Research first: quote the design lines, each with its URL or file and the date you read it. No repository, GitHub or cluster changes. No secrets. End with a five-line summary.
