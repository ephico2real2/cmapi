# #366 design A: operators set `cmapi.net/protected` from the portal

Designer A, Opus 5.5 (high), 2026-11-17, from origin/main 7ba5d78. Paths are under `cmapi/src/cmapi/` unless they say
otherwise. "Measured" means a run on this machine; the probe is `workbench/cmapi/ob-366/probe_protected_drop.py`, run
with the service suite's `world` fixture (PostgreSQL 16 on 127.0.0.1:55432, `policy.engine: none`), then removed.

## 0. What the code does today (measured and read)

| Fact | Where | How known |
|---|---|---|
| "Operator" is `"cmapi-operator" in roles or "cmapi-admin" in roles`, computed inline | `core/pipeline.py:187` | read |
| The same set is written out again three times | `routers/requests.py:178`, `plugins/directory/__init__.py:24` | read |
| A requester's create or PATCH that sends `cmapi.net/protected` (also `null`) is 403 `forbidden` | `core/metadata.py:863`, `:938-940` | probe: requester `{"cmapi.net/protected": null}` → 403 |
| A delete of a namespace whose Git labels match `protected.labels` is 422 `namespace-protected`, also with `reason: expired` (checked before the reason) | `core/approvals.py:153`, `core/pipeline.py:379` | probe: requester DELETE → 422 `namespace-protected` |
| `expire_check` holds a protected namespace (`notProtected`); no job runs `expire_check` yet | `plugins/expiration/rules.py:208`; MOCKUP-CONTRACT.md "no `expire_check` job" | read |
| `protected.labels` on every shipped instance: `cmapi.net/protected=true`, `do-not-delete=true` | `deploy/helm/cmapi/config/approval-rules.yaml:60-63`, crc and kind `20-config.yaml` | read |
| `do-not-delete` has no prefix, so it is a **team** key (`allowOther` prefix `""`): any requester can set and remove it | `deploy/helm/cmapi/config/metadata-keys.yaml` `allowOther` | probe: requester PATCH `do-not-delete=true` → 200 |
| The mockup has no protected badge, toggle or checkbox; "not protected" appears only as an expiry guard in a scenario | `mockups/portal/Main.dc.html:1627-1629` | grep for `protect` |
| The portal's namespace detail is the Quotas tab's `Detail` (on `GET .../namespaces/{ns}`); there is no delete UI | `cmapi-portal-ui/src/portal/QuotasTab.tsx` `Detail` | read |

### D1, a defect this feature depends on (measured)

`plan_namespace` keeps only the **governed and team** keys from Git (`core/pipeline.py:201-204`), and the renderer writes
`spec.labels` plus the system keys. So **every later PATCH drops `cmapi.net/protected`** unless it sends it again.
Probe: an operator created `payments-dev` with `cmapi.net/protected=true` (Git held it), then a requester's dry-run PATCH
of `cmapi.net/cost-center` rendered a `namespace.yaml` without it, auto-approved (`dev-change`, `none-required`). A quota
change, an `:extend` and a `:set` take the same path. Also: the operator's removal reports `keyClasses: []` (the key
is in neither `before` nor `after` of `change_facts`, `pipeline.py:307`), so an auto policy limited by `keyClasses`
matches it and `sensitiveKeys` can never see it.

**Fix (cause, not symptom):** keep `operatorOnly` keys from Git too: `classify(k, kind) in ("governed", "team",
"operatorOnly")` for `cur_l` and `cur_a`. Then the merge patch keeps the key unless the request removes it, `validate`
treats the key as held (so `null` removes it, and still only for an operator), and `change_facts` reports
`["operatorOnly"]` on both add and removal. A requester still cannot send the key at all. Without this fix the toggle
would protect a namespace until its next quota or expiry change. I propose its own issue (fix-defect), child of #366,
fixed in this PR with its own failing tests, the PR saying `Closes #366` and `Closes #<D1>`.

## 1. `GET /api/v1/me` gains `operator` (one source)

- `core/authz.py`: `OPERATOR_ROLES = frozenset({"cmapi-operator", "cmapi-admin"})` and
  `def is_operator(who: Identity) -> bool: return bool(OPERATOR_ROLES & who.roles)`, with a docstring: who may set an
  `operatorOnly` key, cancel another person's request and see an employee ID; by role name, in every environment, as
  today.
- `pipeline.py:187` calls `is_operator(who)`. `routers/me.py` returns `"operator": is_operator(who)`. The other two
  copies (`requests.py:178`, `directory._operator`) call it too: the same set, so no behaviour change, and one place to
  change it.
- `core/models.py` `Me.operator: bool`, described "May set the operator-only labels and annotations of
  metadata-keys.yaml (cmapi.net/protected). The portal shows the operator controls from this; the API checks on each
  write." Regenerate `cmapi/contract/openapi.json`, `schema.generated.ts`, the `/me` sample.
- Not changed: a custom role in `authz-roles.yaml` that `inherits: [cmapi-operator]` is not an operator, as today. Recorded
  in docs/14, not altered (a behaviour change for another issue if the owner wants it).

## 2. The namespace says whether it is protected (one source)

`NamespaceView` gains `protected: bool` and `protectedBy: list[str]` (the `protected.labels` entries that match, such as
`["cmapi.net/protected=true"]`). `ApprovalRules.protected_by(labels) -> list[str]`; `is_protected` becomes
`bool(protected_by(labels))`, so the delete refusal and the view share one function. On `GET .../namespaces/{ns}` they
are computed from the labels of `namespace.yaml` in Git, the input `plan_delete` reads, falling back to the live labels
for a namespace not in Git; on the list, from the live labels (no Git read per row). The portal never decides which
labels protect: an instance's `approval-rules.yaml` does.

## 3. The portal

**Badge (everyone who sees the detail).** In the Quotas `Detail` panel, a `Pill` "Protected" beside `tier-outdated`, and
under the ResourceQuota table one line: "cmapi refuses a delete of {ns} (422 namespace-protected), also the delete after
it expires: it carries {protectedBy joined}." When `protectedBy` holds a label other than `cmapi.net/protected=true`
(`do-not-delete=true`), the line adds "A team label; any change that removes it ends the protection."

**Operator control.** A third card, "Deletion protection · {ns}", shown when `me.operator` and the person has
`PATCH /namespaces/{ns}`'s permission and the instance's `/metadata-keys` marks `cmapi.net/protected`
`x-cmapi-operator-only`. A PatternFly `Checkbox` "Protect from deletion", checked from the namespace's live
`labels["cmapi.net/protected"] === "true"`, a Justification, "Plan change" and "Submit change". Not a `Switch`:
PatternFly says a switch saves at once, and "Use checkboxes when additional action is required to save" — this change
waits for its plan, its approvals and its PR. The same open-request callout as the quota form.

The request: `PATCH /api/v1/clusters/{c}/namespaces/{ns}` with `{"labels": {"cmapi.net/protected": "true"}}` or
`{"labels": {"cmapi.net/protected": null}}` (RFC 7396: `null` removes), `If-Match` the namespace's etag, an
`Idempotency-Key` per change, dry run first. The approval card is the plan's. Same environment `change` rule,
thresholds and auto policies as any change; with D1 fixed, an instance that lists `cmapi.net/protected` in
`sensitiveKeys` makes the removal need approver-platform with no new code (docs/18 gets that sentence).

To keep one implementation of the write rules (plan before submit, 412/428 re-read and re-plan, one key per change, one
submit at a time), I extract them from `ChangeForm` into a hook `usePlannedPatch(row, etag, body, reread)` that both
forms use. Behaviour-preserving: the existing quota tests and mutants must stay green unchanged.

**Create checkbox.** In New namespace, after Expires, a `FormGroup` "Deletion protection" with a `Checkbox` "Protect from
deletion", shown under the same three conditions (no PATCH permission needed: create). Checked adds
`labels["cmapi.net/protected"] = "true"` to the body; unchecked sends no key. Hint: "Operators only. cmapi refuses a delete
of this namespace, also after it expires, until an operator removes the label." With an expiry date and the box checked,
the hint adds "The delete after {date} will be held while it is protected." `metadataForm.ts` exposes the operator-only
keys it reads (`form.operatorOnly`) so the box keys off the instance's rules, and the field list still never offers them.

A requester never sees either control; the API still answers 403 (§5).

## 4. Edge cases

| Case | Behaviour | Proof |
|---|---|---|
| Expiry delete of a protected namespace | `decide` refuses it before the reason test (422 `namespace-protected`); `expire_check` holds it (`notProtected`). Protecting does not clear the expiry; the badge and the create hint say the delete is held | T8 |
| Protected by `do-not-delete=true` only | Badge shows it with the team-label sentence; the operator box is unchecked and unchecking `cmapi.net/protected` cannot unprotect it. Whether `do-not-delete` should be operator-only is the owner's call (a config change, out of scope): I will raise it, not change it | T7 |
| Requester crafts the label (create, PATCH set, PATCH `null`) | 403 `forbidden`, before render | T2 |
| Requester's ordinary change of a protected namespace | Keeps the label (D1 fix) | T4, T6 |
| Kyverno off (`policy.engine: none`) | Unchanged: the operator-only check is cmapi's (`metadata.check`) and the delete refusal is cmapi's (`decide`), in every policy mode. Kyverno cannot tell who asked, so it never enforced operator-only; a hand edit of Git meets the cmapi PR check | every service test runs with `engine: none` |
| Operator protects a namespace with an open request | 409 `change-pending`, shown as the lock callout | existing |
| Instance whose rules do not list `cmapi.net/protected=true` | Badge follows `protectedBy`, so it stays truthful; the control is offered only where the key is operator-only | T3 variant |

## 5. Tests (each fails before, passes after) and mutants

Service, `tests/service/test_protected_366.py`, `world` fixture (`policy.engine: none`):

- T1 `/me.operator` per role: viewer, onboarding, requester, approver false; operator, admin true. One source:
  monkeypatch `authz.is_operator` to `False` and both `/me` and an operator's protected create (403) follow it.
- T2 requester: create with the label, PATCH `"true"`, PATCH `null`: each 403 `forbidden`, nothing stored.
- T3 operator create with the label → synced; `GET` gives `protected: true`, `protectedBy: ["cmapi.net/protected=true"]`;
  DELETE by requester and by operator → 422 `namespace-protected`.
- T4 (D1) requester PATCH of `cmapi.net/cost-center` keeps `cmapi.net/protected: "true"` in the planned `namespace.yaml`.
- T5 (D1) operator PATCH `null` removes it, and the stored facts say `keyClasses: ["operatorOnly"]`; after sync,
  `protected: false` and DELETE → 202.
- T6 (D1) `:extend` of a protected namespace keeps the label.
- T7 `do-not-delete=true` by a requester → `protectedBy: ["do-not-delete=true"]`, DELETE 422.
- T8 `plan_delete(reason="expired")` of a protected namespace → 422 `namespace-protected`.

Unit: `test_approvals.py` `protected_by` order and no match; `test_authz` `is_operator`.

Portal, `tests/api` on the stand-in API, Chromium and installed Chrome: badge with its sentence for each `protectedBy`;
box shown for an operator, absent for a requester and for `operator: true` without the key in the rules; the PATCH body
`"true"` / `null` with `If-Match` and one key; the create body with and without the label; `axe` clean. Screenshots at
1440 and 390 px, light and dark.

Mutants (added to `npm run test:mutants`; each must fail a named test): the control shown without `operator`; the create
box without `operator`; the badge hidden; `null` sent as `"false"`; checked state from `protectedBy` instead of the
label; the create body always sends the key. Service mutants run by hand and recorded: `cur_l` back to governed/team
(T4-T6 fail); `is_operator` returns `False` in `me.py` only (T1 fails); `protected_by` from live labels in `GET` (T3's
Git-only case fails).

## 6. Records

docs/14 (`operator` in "See your own access", who is an operator), docs/04 or the API page for `NamespaceView`,
docs/18 (`sensitiveKeys` and `cmapi.net/protected`), MOCKUP-CONTRACT.md (the badge, the card, the create box: not in the
mockup; docs/02 "the portal shows only the actions that a person can take"), docs/09 testing record, the citations lock
(`scripts/doc-citations.py --relocate`). Both designs and the ruling go to `docs/reviews/2026-11-17-issue-366/`.

## Sources

- PatternFly, Switch design guidelines: "Use checkboxes when additional action is required to save a user's selections",
  https://www.patternfly.org/components/switch/design-guidelines
- RFC 7396, JSON Merge Patch, section 1: a `null` member removes the target member.
- RFC 9110, 13.1.1 If-Match (the etag rules the forms already follow, docs/04).
- docs/02, "the portal shows only the actions that a person can take" (as cited in MOCKUP-CONTRACT.md).
