# #366 design B (OB3, Opus 5.5): operators set `cmapi.net/protected` from the portal

Read in full: issue #366 and the owner's scope comment; `core/approvals.py`, `core/metadata.py`, `core/pipeline.py`,
`core/authz.py`, `routers/me.py`, `plugins/namespaces/router.py`, `core/render/manifests.py`; docs/14; the portal's
`QuotasTab.tsx` (the only namespace detail), `NewNamespaceTab.tsx`, `ExpirationTab.tsx`, `api/hooks.ts`;
`MOCKUP-CONTRACT.md`; `Main.dc.html` 612-683 (the quota detail) and 1617-1635 (the expiry delete). Probes ran on a clone in
my scratch directory against PostgreSQL :55432 with the service suite's `world` fixture; import check: `cmapi.__file__` =
the clone's `src/cmapi/__init__.py`. Probes, tests, logs and the patch: `workbench/cmapi/design-366-b-proof/`.

## 0. Measured today (the premise the design rests on)

| # | Probe (tests/service, clone) | Result |
|---|---|---|
| P1 | requester POST with `cmapi.net/protected: "true"` | 403 `forbidden` "Only cmapi-operator may set cmapi.net/protected" |
| P2 | operator PATCH `{labels:{cmapi.net/protected:"true"}}` on dev | 202 approved, 0 approvals (`dev-change`); Git label `true` |
| P3 | requester DELETE of it | 422 `namespace-protected` |
| **P4** | **requester PATCH `{labels:{cmapi.net/cost-center:"cc-9999"}}` (protected untouched)** | **202 approved; Git label gone (`None`)** |
| **P5** | **requester DELETE after P4** | **202 `pending_approval`: the protection is lost** |
| P6 | requester POST with `do-not-delete: "true"` | 202; its DELETE is 422 `namespace-protected` |
| P7 | requester PATCH `{cmapi.net/protected: null}` | 403 |
| P8 | operator PATCH `{cmapi.net/protected:"false"}` | 202: any value is stored |
| P9 | `GET /me` keys | `access, client, groups, identity, instance, kind, roles, username` (no operator flag) |

## 1. Defects found first (each a `fix-defect` issue, parent #366; #366 must not ship before D1)

**D1 (high): every change drops `cmapi.net/protected`.** `pipeline.py:200-201` keeps only `governed`/`team` keys of the
Git namespace as `cur_l`, so `merge_patch(cur_l, labels)` (`:210`) and the renderer (`manifests.py:145`, labels =
`spec.labels` + derived + system) write the folder without it. Any change by anyone (a tier, a label, `:extend`, `:set`)
silently unprotects (P4, P5). A portal toggle on top of this is a lie. Fix, proved on the clone:

```python
# cmapi/src/cmapi/core/pipeline.py, plan_namespace, replacing lines 200-201
        # operator-only keys (cmapi.net/protected) are carried forward like governed and team keys: a change that does not
        # name them keeps them; only an operator's merge patch sets or removes them (validate refuses anyone else).
        cur_l = {k: v for k, v in (prev_ns or {}).get("metadata", {}).get("labels", {}).items()
                 if self.cfg.metadata.classify(k, "label") in ("governed", "team", "operatorOnly")}
```

Test (`tests/service/test_protected_kept_366.py`): operator protects; requester PATCHes cost-center; assert the Git label is
still `true` and DELETE is 422 `namespace-protected`; operator PATCHes `null`; assert removed. **Before: fails**
(`assert None == 'true'`, `kept-before.log`). **After: passes** (`kept-after.log`). Whole service suite with the fix: 938 passed (`suite-after-d1.log`).

**D2 (medium): protection is not operator-only.** `protected.labels` has `do-not-delete=true` (approval-rules.yaml:60-63),
and `do-not-delete` classifies `team` (unprefixed, `allowOther.prefixes: [""]`). A requester can protect (P6), and so dodge
the expiry delete (`rules.py:208` `notProtected`), and can remove it. Fix: add `do-not-delete` to `operatorOnly`, and a
start-up cross-check: every key in `approvals.protected.labels` must be `operatorOnly`, else refuse to start (the loader
already refuses old formats the same way, `metadata.py:88-91`). With D1, a namespace that has it keeps it.

**D3 (medium): `operator` is a role name, not a permission.** `pipeline.py:187` tests the literal strings
`cmapi-operator`/`cmapi-admin`. docs/14 and `authz.py:76-135` let an instance define roles that `inherits:
[cmapi-operator]` (not operator here) and scope `cmapi-operator` to `environments: [rnd]` (still operator in prod for this
check). See §2 for the one function.

**D4 (low): any value is stored (P8).** `protected=false` is kept and shows in `labels`, yet `is_protected` says no. Fix:
validate an `operatorOnly` key that `protected.labels` names to the value it lists, or `null` (`invalid_value` otherwise).

**D5 (medium, UI-facing): the badge must read Git.** `get_namespace` builds `labels` from the **live** object
(`router.py:136`), but `plan_delete` reads **Git** (`pipeline.py:343-356`). Between merge and sync, or after an
out-of-band `oc label`, a label-derived badge says the opposite of what DELETE does.

## 2. `GET /api/v1/me`: the operator flag

- **Name and shape**: `operator: boolean` (the owner's scope), plus `operatorEnvironments: "all" | string[]`, because a
  boolean alone shows the toggle where the API answers 403 for an environment-scoped operator (the portal already has this
  problem solved for `:extend` with `grantsIn`, `ExpirationTab.tsx:36-41`).
- **One source**: a new permission `namespaces:protect` in `ROLE_PERMISSIONS` for `cmapi-operator` and `cmapi-admin`,
  and one method `RolePolicy.may_set_operator_keys(who, env=None) -> bool` = `self.allowed(who, "namespaces:protect",
  env)`. `plan_namespace` calls it with `env` (replacing `:187`); `/me` sets `operator = may_set_operator_keys(who)` and
  `operatorEnvironments` from `roles.environments(who, "namespaces:protect")`. Behaviour preserved for the built-in roles
  (both hold it everywhere); D3 fixed. Changed: an `authz-roles.yaml` that lists `permissions:` for `cmapi-operator`
  explicitly must add it (docs/14 gets the row and this note). Checks a permission, never a role name: the docs/14 model.
- **Caching**: `useMe` (`hooks.ts:97-108`) inherits `staleTime: 15_000`, no focus refetch (`PortalApp.tsx:118`). A stale
  flag can only show or hide a control; the API decides on the token of each call. On a 403 from a protect submit, the
  portal invalidates `["me"]` and shows the problem `detail`. No new cache.

## 3. The namespace view: `protected` from the API, never derived

`NamespaceView` gains `protected: boolean` and `protectedBy: string[]` (the `key=value` pairs of `protected.labels` that
match), from a new `ApprovalRules.protected_by(labels)` that `is_protected` then wraps (one source), applied to the
**Git** namespace labels that `get_namespace` already reads (`files`, `router.py:126`). The portal never parses
`labels` for protection: which labels protect is server config (two of them today).

## 4. The portal

**Badge (everyone, detail panel of `QuotasTab.Detail`).** A PatternFly `Label` (status, icon `LockIcon`, color
`orange`) "Protected" in the panel's `pill` slot, next to `tier-outdated`; plus a `Small` line: "cmapi refuses a delete
request for this namespace (422 namespace-protected): `cmapi.net/protected=true`." naming `protectedBy`. Wording is
"cmapi refuses a delete request", never "cannot be deleted": no Kyverno rule reads the label (grep of `cmapi/policies`
and `deploy`: none), so `oc delete` by a cluster-admin or a Git PR outside cmapi is not stopped. Kyverno on or off
changes nothing here. When protected and `expiresAt` is set, add: "Its expiry will not delete it: the delete after grace
is held (notProtected)."

**Control (operators in the namespace's environment).** A `Button` ("Protect from deletion" / "Remove protection",
`variant="secondary"`; remove is `variant="warning"`) that opens a `Modal` (`variant="small"`, `titleIconVariant`
warning for remove) with: the justification `TextArea` (required, as the quota form), the dry-run plan from
`usePatchPlan` (its approval callout via `approvalOf`), and "Submit" / "Cancel". **Not a `Switch`**: PatternFly says a
switch "changes an option and saves it simultaneously" and to use a checkbox or a separate action when "additional
action is required to save" ([Switch](https://www.patternfly.org/components/switch/design-guidelines/),
[Checkbox](https://www.patternfly.org/components/forms/checkbox/design-guidelines/), PF4 archive: switch for
"instantaneous actions without confirmation"). This change is a request that may wait for an approver; a switch that
flips while the namespace is still unprotected misstates state. WCAG 2.2: 4.1.2 (the button's name says the action, the
modal is `aria-modal` with its title as name), 3.3.4 (the remove is reviewed and confirmed before it is sent), 4.1.3 (the
outcome callout is `role="status"`), 2.4.3 (focus returns to the button). When `openRequest` is set the button is
replaced by the existing "Change in progress" callout (409 `change-pending` otherwise). Shown when
`me.operator && grantsIn(access, "namespaces:protect", env)`; requesters see the badge only.

**Request.** `PATCH /api/v1/clusters/{c}/namespaces/{ns}` body `{"labels": {"cmapi.net/protected": "true" | null},
"justification": ...}`, `If-Match` from the namespace read, a fresh `Idempotency-Key`; via `usePatchPlan`/`useSubmitPatch`.
The body names **only** that key: never the form's other labels, never `tier` (so one control cannot carry another
change; the server's D1 fix keeps the rest). Unprotect sends `null`, never `"false"` (D4).

**New namespace.** A PatternFly `Checkbox` "Protect from deletion" (a form field, saved by Submit: the checkbox rule
above), with the hint "Operators only. cmapi will refuse a delete request until an operator removes it." Shown when
`grantsIn(access, "namespaces:protect", cluster.environment)`; when checked, `labels["cmapi.net/protected"]="true"` is
added to the body at `NewNamespaceTab.tsx:148`; unchecked sends nothing (not `"false"`). Hidden for requesters; a crafted
body still gets 403 (P1).

## 5. Approvals

Protect and unprotect are `namespaces:write` changes under the environment's rules (P2: dev change needs 0). Add
`cmapi.net/protected` (and `do-not-delete`) to `sensitiveKeys`: `change_facts` counts a sensitive key only when "an
existing value changes or goes" (`metadata.py:372-374`), so **removal** adds one approver-platform and setting it
does not; the asymmetry the risk calls for, with no new code. Measured with D1 applied (`sensitive.log`): set → 202
`approved`, `dev change: 0`; remove → 202 `pending_approval`, `threshold sensitiveKeyChanged: +1 approver-platform`. It depends on D1 (`before` is `cur_l`; without D1 the
removal is invisible). Self-approval follows `selfApproval` per environment, unchanged.

## 6. Adversarial cases, decided

| Case | Outcome with this design |
|---|---|
| Stale `operator` flag | Control shown or hidden wrongly for ≤15 s; API 403s on the token; portal re-reads `/me` |
| Requester crafts the label (create, PATCH, `null`) | 403 (P1, P7); `do-not-delete` closed by D2 |
| PATCH that protects and changes other keys | Allowed by the API (one request, one plan, one approval); the portal never sends it |
| Unrelated PATCH on a protected namespace | Kept (D1); today lost (P4) |
| Unprotect racing a delete | One open request per namespace (409 `change-pending`) and If-Match 412; the delete is decided on Git at plan time, so it is refused until the unprotect merges |
| Protected namespace that expires | `plan_delete(reason="expired")` reads Git, `decide` raises 422 (`approvals.py:153`) before the `reason != "expired"` branch; the guard `notProtected` holds it. `expire_check` has no caller yet and `ExpiryInfo.protected` defaults False (`rules.py:52`): whoever wires it must fill it from `is_protected` |
| `do-not-delete=true` also listed | The badge names it via `protectedBy`; the remove button only removes `cmapi.net/protected`, so when `do-not-delete` remains the modal says "still protected by do-not-delete=true" |
| Kyverno off | No effect: protection is cmapi's own refusal (docs/02:977 "Blocks delete through the API") |

## 7. Tests

**Service:** `/me` `operator` per role (requester false; operator, admin true; a role inheriting `cmapi-operator` true;
operator scoped to `rnd` gives `operatorEnvironments: ["rnd"]` and 403 on prod); D1 test above; D2 requester
`do-not-delete` 403; D4 `"false"` 422; `NamespaceView.protected/protectedBy` from Git while live differs; remove adds
one approver-platform, set adds none; expired-reason delete of a protected namespace 422.
**Portal (standin):** standin `/me` returns `operator`; badge for requester and operator; button for operator only and
absent for requester and an operator outside the env; modal sends exactly `{"labels":{"cmapi.net/protected":"true"}}`
with If-Match (and `null` to remove); checkbox present for operator, absent for requester, body carries the label only
when checked; axe clean with the modal open; 390/820/1440, both themes.
**Mutants (`tests/api/mutants.mjs`):** button shown without `grantsIn`; body sends `"false"`; body carries a second key;
badge from `labels` instead of `protected`; checkbox sends `"false"` when unchecked; the remove modal without the
`do-not-delete` note. Service mutants: `cur_l` without `operatorOnly`; `/me` from role names.
**Contract:** `MOCKUP-CONTRACT.md` gets rows: the mockup has no badge, no protect control, no checkbox and no delete in
any tab (grep of `Main.dc.html` for `protect`: only the expiry scenario's "not protected" guard, 1627-1629), so each is
an addition named as such.
