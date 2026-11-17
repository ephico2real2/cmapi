# #366: the arbitration of two designs

- **Design A** (`design-366-a.md`): a general-purpose Opus 5.5 agent, which also builds.
- **Design B** (`design-366-b.md`, proof in `design-366-b-proof/`): OB3, a separate Opus 5.5 agent.

One model family (Codex out of quota until 2026-11-18 14:09; Fable paused). Written apart.

## The owner's decisions (2026-11-17)

- Build it: operators set `cmapi.net/protected` from the portal.
- `do-not-delete=true` becomes **operator-only**, like `cmapi.net/protected`. Namespaces that carry it keep it.

## Where the designs agree (adopted)

| Point | Both |
|---|---|
| D1 (#374) | Any later change drops `cmapi.net/protected`, because `plan_namespace` carries forward only governed and team keys from Git (`pipeline.py:200-204`). Both measured it. Fixed in this PR first, with its failing test: operator-only keys are carried forward too |
| Namespace read | `NamespaceView` gains `protected` and `protectedBy`, computed by cmapi from the Git labels (the input a delete checks), so the portal never derives it |
| Requests | Each control sends a PATCH that changes only the protection label (removal sends `null`), with dry run, If-Match and Idempotency-Key, through the normal flow and approvals |
| No Switch | PatternFly's Switch saves at once; this change waits for a request and may need approval |
| Create form | A "Protect from deletion" checkbox for operators only |
| Badge | Shown to everyone, with the reason a delete is refused |
| Kyverno off | Nothing changes: both checks are cmapi's |

## Rulings where they differ

| Point | A | B | Ruling |
|---|---|---|---|
| Who is an operator | `authz.is_operator(who)` shared by the pipeline, `/me` and the two inline copies | A new permission `namespaces:protect` through `RolePolicy`; `/me` gives `operator` and `operatorEnvironments`. B measured that the role-name check misses inherited and environment-scoped roles (D3) | **B.** The permission model already decides every other action per environment (docs/14). One `RolePolicy` method serves the pipeline's operator-only check, `/me` and the inline copies |
| Detail control | A Checkbox in a "Deletion protection" card | A Button with a confirm dialog | **B.** Protecting or unprotecting is a request that may wait for approval; an explicit action with a confirmation says so, and shows the request it opened |
| Approvals | Normal rules | Add the protection keys to `sensitiveKeys`: protecting needs no approval, removing protection adds one approver-platform approval (measured with D1 applied) | **B** |
| Values (D4) | Not covered | Any value is stored, including `"false"` | **Accept only `"true"`**, removal by `null`, for both keys; a test for `"false"` refused |
| `do-not-delete` (D2) | Owner's call | Requester can set it | **Owner: operator-only**, as above |
| Badge words | — | "cmapi refuses a delete request" (no Kyverno rule reads the label) | **B** |
| Shared plan/submit hook | Extract the quota form's rules into a shared hook | — | Allowed if the quota tab's checks and mutants still pass unchanged |

## Filed separately

- D5: `GET` on a namespace returns live labels while a delete checks Git — its own issue.
