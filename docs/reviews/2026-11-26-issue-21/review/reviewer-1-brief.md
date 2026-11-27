# Reviewer 1 brief: cmapi branch feat/21-placement (part of story #21, closes #303), capacity snapshots and safe placement. A migration, a hold on capacity, and a write path: two reviewers.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high wrote it. Reviewer 2 (Opus) checks your fixes after you, on PostgreSQL.
- Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-21/` (`head/`, `base/`, `pr.diff`). When you diff, exclude `examples/`, which holds symlinks.
- Read in full: `head/docs/reviews/2026-11-26-issue-21/README.md` (decisions D1–D13), and docs/02's Placement, Capacity and "Reservations" sections in `head/docs/02-technical-design-v2.md`.
- Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The claim:**
1. **Snapshots.** Worker job `capacity_snapshot` writes rows for the cluster, each zone and each node role, every `snapshotInterval` (15m–60m). Migration 0012 adds `capacity_snapshots`. `GET /api/v1/clusters/{id}/capacity` answers 404 outside the caller's environments, and `POST .../capacity/snapshots:run` is behind `operations:run`.
2. **Placement.** `POST /api/v1/capacity:place`:
   - excludes clusters with a named reason;
   - checks CPU and memory separately, freshness, holds and zone-failure headroom;
   - scores the rest, and holds the first for 15 minutes (201); `dryRun` ranks only.
   - A create's `placementId` turns the hold into the request's own, and a used or lapsed placement refuses the create.
   - A cap of 3 active placements applies per team, or per caller without a team.
3. **No Thanos on create:** zero Thanos calls in the preview, the hold, the dry run and the create.
4. **The portal:** the New namespace tab ranks clusters instead of asking for one.

**Confirm or refute, with tests:**
1. **Overbooking.** Can concurrent placements, or a placement and a direct create, together exceed capacity? Is the hold taken under #725's per-cluster lock in the same transaction? Can a `placementId` be reused, stolen by another caller or team, or replayed through `Idempotency-Key` with a changed body?
2. **Leaks.** Do placement holds expire and stop counting? Does a create that fails after converting the hold release it?
3. **The zone-failure headroom and freshness** match docs/02's numbers and rule. Quote the design.
4. **Authorization.** Is every new route behind the docs/14 permission, with `x-cmapi-permission`? Does the 404 scope hold?
5. **Migration 0012:** up, down and up. Are `REQUIRED_REVISION` and the migration tests updated? (Grep `tests/service` for `'0011'`.)
6. **Behaviour beyond the purpose:**
   - Does a create with an explicit cluster and no `placementId` still work as on base, if the design keeps it?
   - The in-memory placement cap was removed from `core/ratelimit.py`: was it really unused?
7. **The tests can fail.** Run them on base and head, plus mutants of the lock, the expiry and the per-resource check.

**How to run.** Your sandbox may not reach PostgreSQL; if so, say it at the top and do not substitute SQLite. Service tests: from a tree's `cmapi/`, run

`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_21 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`

Core tests: `PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q`.

**Severity and fixes.**
- High and Medium findings need the full fix and a test that fails before and passes after.
- Keep fixes narrow, and **separate anything that predates the change**.
- Low findings, and anything outside the changed lines, go to Backlog.

Quote the design and your primary sources. No repository, GitHub or cluster changes. End with a five-line summary.
