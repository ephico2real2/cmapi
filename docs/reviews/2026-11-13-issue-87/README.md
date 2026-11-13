# #87 (BUG-11): the review of `pr_status` and check runs

`pr_status` on GitHub reads check runs as well as commit statuses, and on GitHub the worker waits for `ci/*` and posts only `cmapi/check`. The change decides whether a pull request can merge, so it has a second reader.

| Who | What |
|---|---|
| Opus 5.5 at `high` | The change, commit `f196902` |
| Codex `gpt-6.1-sol`, 2026-11-06 | Claims C1 to C4 (`docs/reviews/2026-11-06-pr112/night/87/`), stopped by the owner before C5 |
| Codex `gpt-6.1-sol`, 2026-11-13 | Claims C5 to C8, on an export with its C3 fix applied. `brief.md`, `verdicts.md`, `fixes.md` and `tests.md` in this folder. 96,220 tokens |
| OB1, Fable 5.2 | The rulings, a run of each of Codex's tests before and after its fix, the port change for C5, and this record |

## The rulings

| Claim | Codex | Ruling |
|---|---|---|
| C1. Which conclusions pass | REFUTED as "equal to GitHub": `neutral` and `skipped` fail here, and GitHub's required checks accept them | No change. The stricter rule is deliberate: `ci/*` is the evidence that the validation ran, and a skipped run validated nothing. The code's docstring says so |
| C2. A stale success beside a newer failure | CONFIRMED | Stands |
| C3. More check suites than the endpoint returns | REFUTED | **Accepted.** GitHub's commit endpoint covers the 1,000 newest suites. Codex's fix reads each suite when a commit has more. Its regression: `'success' == 'failure'` before, passed after, run by OB1 |
| C4. An error never reads as green | CONFIRMED | Stands |
| C5. The worker waits on GitHub, and the stand-in is unchanged | CONFIRMED, with 12 cases compared against `main` | Stands. Codex's first proposal, `getattr(ctx.git, "external_ci", False)`, is **not applied**: a default of False makes the worker post `ci/*` itself. The flag is now on the `GitProvider` port, and a provider without it fails the job. Codex attacked this ruling and found no real provider path that it harms |
| C6. A context that has not reported is pending | REFUTED | **Accepted.** A check run with status `completed` and no conclusion read as a failure, and the worker closed the pull request. It now reads as pending. 3 tests failed without the fix and 105 passed with it, run by OB1 |
| C7. No test passes without its code | REFUTED | **Accepted, a test only.** Three mutants were killed. A fourth, which removes the check that the head is the approved one, survived. Codex's added test kills it |
| C8. No merge on GitHub with only `cmapi/check` green | PLAUSIBLE | Stands as PLAUSIBLE. The worker's gate is measured on a mock. GitHub's own branch protection is not measured: it needs the GitHub App of Wave 3, an owner step (#61) |

## Not tested

GitHub itself. Each result here is on a mock transport and the fake of the service suite, on macOS with PostgreSQL 16 on `127.0.0.1:55432`. #61 stays open for the first run against GitHub.
