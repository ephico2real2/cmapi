# #144: the review of the plugin switch

The change adds a refusal to the write path (`plugin-disabled`) and a new admin read, `GET /api/v1/admin/plugins`. So it has a second reader.

| Who | What |
|---|---|
| OB1, Fable 5.2 | The change, commit `a5ac4a5`, then the fixes of this review, the rulings and this record |
| Codex `gpt-6.1-sol`, 2026-11-13, 102,579 tokens | Seven claims on an export of `a5ac4a5`: `brief.md`. Its report with the full code of each fix and test: `codex-report.md` |

## The rulings

| Claim | Codex | Ruling |
|---|---|---|
| C1. The permission check comes before the override | CONFIRMED | Stands |
| C2. No write before the override check | REFUTED: `RequestRepo.by_idempotency` clears an expired idempotency key, and commits, before the planner runs | **Not applied.** The cleanup is the documented behaviour of #142: "cleared here, in the caller's transaction" (`core/db/repo.py`, `by_idempotency`). It runs after the route's permission check. It changes only a key that is past its 24 hours, which `docs/02` says holds nothing ("the same key and caller return the original ChangeRequest for 24 hours"). No request, event, job or Git write comes from it, and no call to the API can see it. Codex's test fails because it demands a lookup with no UPDATE, which no document asks for. Its fix moves the cleanup into `Pipeline.submit`, which changes the idempotency path outside the scope of #144. Codex confirms the part that matters: with a live key, a replay returns the stored request and writes nothing |
| C3. A plugin that is not enabled has no route | CONFIRMED | Stands |
| C4. A YAML value of another type cannot pass | REFUTED: `overrides: []`, `false`, `0` and `''` passed as "no override", the same for the block of the instance; an instance key that is not a text was ignored; two unknown keys of different types raised a `TypeError` that the loader does not collect | **Accepted.** Codex's fix is applied to `core/plugins.py` unchanged, except the words of its two messages. Its cases are in `test_plugins_switch.py`: 7 failed on `a5ac4a5` and each passes now. No case enabled a plugin wrongly |
| C5. `GET /api/v1/admin/plugins` needs a token and `clusters:read`, and shows nothing more | Authorization CONFIRMED. REFUTED on one field: `configured` says whether the instance has the file | No change. Codex: "not an authorization vulnerability". The field is there on purpose, so that an operator knows why each plugin is enabled. Codex finds that the override environments are not sensitive under `docs/14` |
| C6. Without the file, the routers and their order are as before | CONFIRMED | Stands |
| C7. No worker job calls a planner | CONFIRMED | Stands |
| Extra. The example in the docstring of `core/plugins.py` disabled `quotas`, which the code refuses | REFUTED | **Accepted.** The example disables `namespaces` |

## Not tested

Codex did not connect to the test database, because another suite used it. Its request-level tests for C2 and C5 are in its report and were not run. Each result here is on the service suite's fakes, on macOS with PostgreSQL 16 on `127.0.0.1:55432`. Nothing ran on a cluster.
