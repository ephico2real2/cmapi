# #366 and #374: operators protect a namespace from deletion

Two designs were written apart and arbitrated by the coordinator. The build follows `arbitration.md`.

| File | What it is | Who wrote it |
|---|---|---|
| `design-a.md` | Design A | A general-purpose Opus 5.5 agent at `high`, which also built the change |
| `design-b.md`, `design-b-proof/` | Design B, its probes, its D1 patch and logs | OB3, a separate Opus 5.5 agent |
| `arbitration.md` | The ruling, with the owner's decisions of 2026-11-17 | The coordinator |
| `evidence/` | The builder's runs: each test before and after, and the service mutants | The builder |

One model family: Codex was out of quota until 2026-11-18 14:09, and Fable is paused.

## What was built

| Ruling | Where |
|---|---|
| #374: a change keeps the operator-only keys that Git holds | `core/pipeline.py`, `plan_namespace` (`kept`) |
| An operator holds `namespaces:protect`; one `RolePolicy.is_operator(who, env)` for the pipeline, `GET /me`, cancel and the directory | `core/authz.py`; `routers/me.py`, `routers/requests.py`, `plugins/directory` |
| `GET /me` gives `operator` and `operatorEnvironments` | `routers/me.py`, `core/models.py` (`Me`) |
| `GET` on a namespace gives `protected` and `protectedBy` from its labels in Git; null on the list | `plugins/namespaces/router.py`, `ApprovalRules.protected_by` |
| A protection label takes only `"true"`, or `null` | `Pipeline._metadata_refusal` (`invalid_value`) |
| `do-not-delete` is operator-only (the owner); both protection keys are `sensitiveKeys` | every shipped `metadata-keys.yaml`, the CRC and kind ConfigMaps, the rendered example bundle |
| The portal: the "Protected" label and why a delete request is refused, to everyone; "Protect from deletion" or "Remove protection" with a dialog for an operator in the environment; the create form's "Protect from deletion" box | `src/portal/QuotasTab.tsx`, `NewNamespaceTab.tsx`, `access.ts` |

Not in this change: D5 (`GET` gives the live labels while a delete checks Git) is #375. B's start-up check, that each key
of `protected.labels` is operator-only, was not ruled; docs/18 says to list only operator-only keys there.

## How it was measured

Service tests on this machine, PostgreSQL 16 on 127.0.0.1:55432 in a database of this run (`cmapi_ob366`), each world with
`policy.engine: none`. Portal checks on the stand-in API (`tests/api/standin.mjs`) in Chromium 156. Nothing ran on a
cluster; the CRC walk is the coordinator's.

| Evidence | Result |
|---|---|
| `evidence/374-before.log`, `374-after.log` | The four #374 tests fail on the parent of the fix and pass after it |
| `evidence/366-before.log` | The new service file on origin/main 7ba5d78: 18 failed, 1 error, 2 passed (the two that hold today: a requester's `cmapi.net/protected` is 403, and the expiry delete of a protected namespace is refused) |
| `evidence/portal-19-before.log` | Each of the six portal checks of #366 that existed then, on origin/main's portal: each fails |
| `evidence/service-mutants.log` | 6 service mutants, 6 killed (`evidence/service_mutants.py`) |
| `evidence/portal-19-after.log`, `portal-19-chrome.log` | The 7 portal checks of #366 pass in Chromium 156 and Chrome 157 |
| `evidence/portal-mutants-366.log` | 11 new portal mutants and 4 whose text moved: one survivor in the first run, killed after the check was strengthened (docs/09) |

## Sources

- PatternFly, Switch design guidelines: "When a user toggles a switch, the change should save automatically", and "Use
  checkboxes when additional action is required to save a user's selections",
  https://www.patternfly.org/components/switch/design-guidelines
- RFC 7396, JSON Merge Patch: `null` removes a member.
- RFC 9110, 13.1.1 If-Match; RFC 9457 problem details (the refusals).
- WCAG 2.2: 3.3.4 (a removal is reviewed before it is sent), 4.1.3 (the outcome is a status message).
