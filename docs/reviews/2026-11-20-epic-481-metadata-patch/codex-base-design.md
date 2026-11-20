# Change a namespace’s metadata

Design decision for #482 · 20 November 2026 · for owner review before #483–485. The editor proposes a change to the namespace folder in Git. A successful submission gives the caller a request to track. Approval, the bot PR and delivery follow the existing update path.

**Inputs.** Owner #481, spike #482, and the #479 create design, especially §§2–5, 7 and 9. Code citations below are relative to the supplied cmapi checkout, main at `d55a7c2`, inspected 2026-11-20. Examples use the company.net configuration in #479 §3.1. The five external references are primary sources, read on that same date.

## 1. Which PATCH format?

| Option | What the caller sends | Decision |
|---|---|---|
| JSON Merge Patch | Object members with their literal Kubernetes keys. Omission keeps a value, a string sets it, and member-level JSON null deletes it. | Use these semantics inside the two metadata maps. They directly express every requested edit. [RFC 7396 §2](https://www.rfc-editor.org/rfc/rfc7396#section-2) |
| JSON Patch | Ordered add, replace, remove and test operations using JSON Pointer paths. A slash in a qualified key needs escaping. | Positional operations and per-path tests add little for two string maps already guarded by a folder version. [RFC 6902 §§3–4](https://www.rfc-editor.org/rfc/rfc6902#section-3) |
| Kubernetes strategic merge | Uses resource-specific strategies and merge keys, especially for lists. kubectl also supports JSON Patch and JSON Merge Patch. | Neither map needs Kubernetes list semantics. cmapi targets its own Git change-request API. [Kubernetes patch types](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/update-api-object-kubectl-patch/) |

**Wire decision.** Keep `PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}`, `Content-Type: application/json` and the flat `NamespacePatch` envelope. The RFC’s whole-document media type is `application/merge-patch+json`. cmapi’s envelope also carries request instructions and its own quota semantics, so this design documents the existing media type and the scope of the merge. Clients send changes only. A whole map omitted, empty, or explicitly null keeps that map (legacy behavior). A null **inside** a map removes just that member. An empty string is a value where permitted. Removing an absent, permitted optional key makes no difference. Reject arrays, nested metadata values, unknown body fields and a body-supplied namespace with 422 `validation-failed`. A valid request with no effective change gets 422 `no-change`.

Today the body also takes `tier`, `quota`, `limitRange`, `onBehalfOf` and `justification`. Keep those callers, including combined metadata/quota PATCHes. The portal sends only changed metadata and optional justification. Identity comes from the signed token, subject to the existing service delegation rules. See `cmapi/src/cmapi/core/models.py:22`, `cmapi/src/cmapi/core/models.py:252`, `cmapi/src/cmapi/plugins/namespaces/router.py:182` and the working tier example in `docs/04-api-examples.md:549`.

## 2. Which keys can change?

**Options.** A separate editable-key list would duplicate Helm configuration and drift on a domain change. Use the existing classifier and #479’s rule objects to produce a decision per **(kind, key)**. Keep label and annotation independent even when their names match. The following is the rule order and the text people see. [#479 §§2–3](namespace_metadata.md#2-the-rules)

| Input from the target or metadata-keys.yaml | Allowed on an existing namespace | Reason or help shown in the form |
|---|---|---|
| Namespace path identity | Display locked | “Kubernetes identifies this namespace by its name. An existing namespace cannot be renamed.” |
| `system` | Locked for everyone, including operators. Refuse even an echo. | “cmapi manages this key.” Show all present values, including expiry, tier, request and identity stamps. Expiry is managed through the expiration operations. |
| `reservedPrefixes`, adoption label, or disallowed key | Preserve existing Git values, lock them and refuse writes | “Reserved for the platform”, “Identifies the provisioning system”, or “This prefix is outside the configured policy”. Live-only controller metadata is outside the Git edit. |
| `operatorOnly` | Locked unless the caller also holds `namespaces:protect` in this environment. Operators may add, change and remove in a dedicated field per kind. | “Requires namespaces:protect in dev” (substitute the environment). For a protection label offer the value configured in approval-rules.yaml or Remove. In the example that is the string `"true"` for `cmapi.net/protected` and `do-not-delete`. |
| `value.from` | Automatic, locked. Omission lets cmapi fill the target value. An exact target echo passes. Refuse null or a different value. | “Copied from the namespace name” for label `name`. “Copied from the cluster environment” for both app-environment entries. Apply the same rule to cluster and instance sources. |
| `namespacePrefix` / `namespaceSuffix` | Pin an entered naming key to the existing value. A derived suffix follows the target-derived rule above. Exact echo allowed. Refuse a different value, removal or manual first assignment of a missing fixed key. | “Forms the prefix of this namespace’s fixed name” for mnemonic. Show the corresponding suffix reason on the environment label. The #479 prefix/suffix and full DNS name rules apply to creation. An edit cannot rename a legacy namespace to repair it. |
| `requiredLabels`, `requiredAnnotations`, after fixed rules | Add a missing key or change to a valid nonempty value. Refuse removal. | “Required on the namespace.” Includes Team, Line of business, Critical level and Team DL. Team defaults from mnemonic on create. Omission on update keeps the Git value, including a previously chosen Team. |
| Named `extraLabels.keys` / `extraAnnotations.keys` | Add, change, remove | Optional fields, e.g. Cost center, App, Rightsizing, Group contact and Confluence page. An explicit Remove action distinguishes deletion from an allowed empty string. |
| `allowOther` of the matching kind | Add, change, remove within policy | Show configured prefixes, Kubernetes key and label-value syntax, per-kind count and UTF-8 annotation byte limits. In §3.1 these are 50 **other** keys per kind, 4,096 bytes per other annotation value and 65,536 bytes in total. |
| `sensitiveKeys` (overlay) | The change still has to be authorized. Add one platform approval for any effective addition, replacement or deletion on an **update**, once per request. | “Changing this key adds one approver-platform approval.” Team, CL and the protection keys are examples when listed in the instance. An echo adds nothing. |

Keep #234’s adoption rule. An untouched missing required key or legacy name mismatch is a finding. Show what Git actually has, validate changed values, and permit unrelated work. Required editable keys can be repaired individually. Leave a missing fixed mnemonic to adoption remediation. Derived fields that the renderer fills or corrects must appear in the preview with their target source. Preserve held reserved/adoption metadata across rendering. A held extra with legacy invalid syntax that still classifies as an allowed extra can be deleted under the existing validation exception.

**Changes to main.** Classification, merged required checks, limits, protected values and target-derived checks exist in `cmapi/src/cmapi/core/metadata.py:795`, `cmapi/src/cmapi/core/metadata.py:826`, `cmapi/src/cmapi/core/metadata.py:902` and `cmapi/src/cmapi/core/pipeline.py:340`. Add the fixed-key comparison against the Git baseline. Prefix matching alone cannot pin a missing or changed key. Preserve held metadata across the current input filter and render merge at `cmapi/src/cmapi/core/pipeline.py:210` and `cmapi/src/cmapi/core/render/manifests.py:142`. Today first assignment is excluded from sensitive facts. Extend it for updates only, using the actual per-kind diff. Reuse the existing approval rule and group from data. See `cmapi/src/cmapi/core/metadata.py:955` and `deploy/helm/cmapi/config/approval-rules.yaml:50`.

## 3. What does the contract return?

**Options.** Returning a replacement namespace immediately misrepresents approval and Git delivery. Keep the existing 200 plan and 202 request. Add a typed `metadataDiff` to the update plan, alongside the filename-to-status `changes` map and filename-to-content `files`. This also lets #479 implement its create-specific provenance view independently. Existing shapes are in `cmapi/src/cmapi/core/pipeline.py:69`, `cmapi/src/cmapi/core/models.py:162` and `cmapi/src/cmapi/core/models.py:262`.

**Read contract proposed for #483.** Add opt-in `?forWrite=true` on the cluster list, namespace list and namespace detail reads. Retain their normal read grants, and additionally enforce the PATCH write grant in the target environment. Cluster choices must be writable, served and offer the plugin. Namespace choices must belong to that cluster and have a managed Git namespace manifest. Return pending targets with `openRequest` so the user can see the holder. A detail read rechecks access and existence. In this projection take `labels`, `annotations`, name and summaries from the same Git-folder read as the ETag. Use the regular response models. Ignore stale responses from earlier selections. The default cluster list includes imports and the default namespace reads use the watch cache, even though the detail ETag comes from Git. See `cmapi/src/cmapi/routers/me.py:33`, `cmapi/src/cmapi/plugins/namespaces/router.py:112` and `cmapi/src/cmapi/plugins/namespaces/router.py:128`.

Add `GET /api/v1/metadata-keys?operation=patch`. Its `labels` and `annotations` schemas match the PATCH maps’ object branches. Preserve the default create representation and its A5 equality test. Derive non-nullable required-in-result fields, allowed other keys, sensitive marks, lock reasons and system/reserved/adoption classifications from the same loaded policy. Put per-property `x-cmapi-edit` (mode, reason, requiredInResult, sensitive) on named keys and the classifier data for held/other keys on the map. Use the target environment’s operator grant and configured protection-label values for operator controls. The representation ETag covers every rule it exposes, including protection values. Source data, schema generator and existing conditional read are at `cmapi/src/cmapi/core/metadata.py:986` and `cmapi/src/cmapi/routers/me.py:40`.

**Check.** Example target is `/api/v1/clusters/CRC/namespaces/abc-payments-dev`. Its detail GET returns `ETag: "3f9a1c0b7e2d4a68"` and body `etag` without quotes. Send the quoted header on **both** calls. It identifies folder content, independently of commits elsewhere in the repo. A missing header gives 428, a stale one 412. Use one concrete strong tag. Neither a weak tag nor a wildcard establishes a checked folder version. Preserve compatibility with existing clients sending the bare body token. See `cmapi/src/cmapi/core/pipeline.py:95`, `cmapi/src/cmapi/core/pipeline.py:197` and [RFC 9110 §§8.8.3, 13.1.1](https://www.rfc-editor.org/rfc/rfc9110#section-13.1.1).

```http
PATCH /api/v1/clusters/CRC/namespaces/abc-payments-dev?dryRun=true
Authorization: Bearer <access-token>
Content-Type: application/json
If-Match: "3f9a1c0b7e2d4a68"
```

```json
{
  "labels": {"company.net/cl": "2", "cmapi.net/cost-center": null},
  "annotations": {"runbook.company.net/url": "https://wiki.company.net/abc/runbook"},
  "justification": "Raise the critical level, retire the cost code and add the on-call runbook."
}
```

**200 application/json.** Full illustrative plan for that body. Diff maps contain only effective per-key changes, sorted within each kind. Null as an endpoint means absent. `source` explains the after value or the deletion instruction, using `request` for a user action and #479’s `namespace`, `environment`, `cluster`, `instance` or `default:<key>` for generated values when applicable. Do not reapply create defaults. Diff the governed and extra namespace metadata, including operator fields, after rendering. Renderer bookkeeping such as the new request ID belongs in the file preview.

```json
{
  "etag": "3f9a1c0b7e2d4a68",
  "checkToken": "a17b4c891e17aa10f739bbc52f200ca07081c6832b67b56de6650c7fbfbd830b",
  "planHash": "325690adc71558c8c3211108f8657ea132b075582df7239c8ded1233caa55df4",
  "metadataDiff": {
    "labels": {
      "cmapi.net/cost-center": {"before": "cc-4410", "after": null, "source": "request"},
      "company.net/cl": {"before": "1", "after": "2", "source": "request"}
    },
    "annotations": {
      "runbook.company.net/url": {"before": null, "after": "https://wiki.company.net/abc/runbook", "source": "request"}
    }
  },
  "changes": {"clusters/CRC/namespaces/abc-payments-dev/namespace.yaml": "changed"},
  "files": {"clusters/CRC/namespaces/abc-payments-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: abc-payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: small\n    cmapi.net/requested-by-user: sam\n    name: abc-payments-dev\n    company.net/app-environment: dev\n    company.net/mnemonic: abc\n    company.net/lob: amgsst\n    company.net/cl: '2'\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: sam@company.net\n    company.net/app-environment: dev\n    cmapi.net/team-dl: payments-team@company.net\n    runbook.company.net/url: https://wiki.company.net/abc/runbook\n"},
  "capacity": {"status": "fits", "fresh": true, "bindingResource": null},
  "approval": {"rule": "dev-change", "auto": null, "autoFallback": null, "selfApproval": true, "timeoutHours": 8,
    "slots": [{"group": "approver-platform", "count": 1, "reason": "Sensitive key changed"}],
    "remaining": [{"group": "approver-platform", "needed": 1}], "approvals": [],
    "reasons": ["dev change: 0 from approver-platform", "Sensitive key changed"]},
  "requester": {"requester": {"sub": "sub-sam", "username": "sam", "email": "sam@company.net", "givenName": "Sam",
    "middleName": null, "familyName": "Lee", "employeeId": "1001", "kind": "user", "clientId": "cmapi-portal"},
    "automated": false, "submittedBy": null, "submittedByClient": null},
  "findings": [], "beyondTier": null
}
```

**Submit.** Send the identical JSON above to the same PATCH path with `dryRun=false` (the default), the same Authorization, Content-Type and If-Match, plus the two headers below. Require Idempotency-Key on submit only (1–100 characters). The portal always echoes the proposed optional check token. Existing API callers may still submit directly under current policy. See `cmapi/src/cmapi/plugins/namespaces/router.py:54`.

```http
Idempotency-Key: 6546de8b-b236-4154-8aa1-41d697ea1103
If-Checked-Plan: a17b4c891e17aa10f739bbc52f200ca07081c6832b67b56de6650c7fbfbd830b
```

**202 application/json.** The request holds the namespace lock. In this example it needs one approval. The stored plan hash reflects the assigned request ID. The checked hash describes planning-time files. See `cmapi/src/cmapi/core/pipeline.py:408`.

```json
{
  "requestId": "req-20261120-0007", "instance": "nonprod", "clusterId": "CRC", "env": "dev",
  "namespace": "abc-payments-dev", "plugin": "namespaces", "action": "update", "reason": null,
  "justification": "Raise the critical level, retire the cost code and add the on-call runbook.",
  "status": "pending_approval", "createdAt": "2026-11-20T15:30:00Z", "updatedAt": "2026-11-20T15:30:00Z",
  "baseSha": "c53e954a6f900f28b57959cfcb5c11526b6e040e",
  "planHash": "48fd721782ec4cae3422c3447f720ada7c9fa42af21daf68e20f320f78ba82c9",
  "approval": {"rule": "dev-change", "auto": null, "autoFallback": null, "selfApproval": true, "timeoutHours": 8,
    "slots": [{"group": "approver-platform", "count": 1, "reason": "Sensitive key changed"}],
    "remaining": [{"group": "approver-platform", "needed": 1}], "approvals": [],
    "reasons": ["dev change: 0 from approver-platform", "Sensitive key changed"]},
  "requester": {"requester": {"sub": "sub-sam", "username": "sam", "email": "sam@company.net", "givenName": "Sam",
    "middleName": null, "familyName": "Lee", "employeeId": "1001", "kind": "user", "clientId": "cmapi-portal"},
    "automated": false, "submittedBy": null, "submittedByClient": null},
  "files": {"clusters/CRC/namespaces/abc-payments-dev/namespace.yaml": "changed",
    "clusters/CRC/namespaces/abc-payments-dev/resourcequota-abc-payments-dev-quota.yaml": "unchanged",
    "clusters/CRC/namespaces/abc-payments-dev/limitrange-abc-payments-dev-limits-cpu.yaml": "unchanged",
    "clusters/CRC/namespaces/abc-payments-dev/limitrange-abc-payments-dev-limits-memory.yaml": "unchanged",
    "clusters/CRC/namespaces/abc-payments-dev/token-issuer-rolebinding.yaml": "unchanged"},
  "events": [{"at": "2026-11-20T15:30:00Z", "event": "plan_needs_approval", "status": "pending_approval",
    "by": "sam", "note": "waiting for [('approver-platform', 1)]"}],
  "pr": null, "mergeSha": null, "beyondTier": null,
  "links": {"self": "/api/v1/requests/req-20261120-0007", "events": "/api/v1/requests/req-20261120-0007/events"}
}
```

**Failures.** Use the instance’s RFC 9457 `application/problem+json` and registered codes. Registry and route declarations are in `cmapi/src/cmapi/core/docs.py:33`, `cmapi/src/cmapi/core/docs.py:147` and `cmapi/src/cmapi/plugins/namespaces/router.py:31`. Include the two already registered delegation errors reachable through `cmapi/src/cmapi/core/identity/checks.py:76` in the PATCH declaration. No new problem or per-key code is needed.

| Status | PATCH problem codes | Caller action |
|---|---|---|
| 400 | idempotency-key-required | Supply a valid key on submit. |
| 401 | unauthenticated | Sign in again. |
| 403 | forbidden, environment-forbidden | Check write/protect grants in the selected environment. |
| 404 | cluster-not-found, object-not-found | Refresh the target choices. |
| 409 | change-pending, idempotency-replay | Follow the holder via requestId, or use a fresh key for a different intent. |
| 412 | precondition-failed | Read the current target and rules, then review and check again (§5). |
| 422 | policy-violation, validation-failed, no-change, invalid-team-dl | Fix the named field/row, payload or empty diff. |
| 422 | cluster-not-writable, environment-not-served, plugin-disabled, capacity-exceeded, identity-incomplete, unknown-user, unknown-serviceaccount, on-behalf-of-not-allowed, on-behalf-of-required | Show the service’s detail and relevant target, identity or capacity guidance. |
| 428 | precondition-required | GET the detail and send its ETag. |
| 502 / 503 | git-unavailable (502), cluster-unreachable, validator-unavailable (503) | Keep the draft. Retry Check when available. Use the original idempotency key after an ambiguous submit. |

```json
{
  "type": "https://cmapi.ephico2real.com/problems/policy-violation", "title": "policy violation",
  "status": 422, "code": "policy-violation", "detail": "Metadata refused",
  "errors": [
    {"kind": "label", "key": "company.net/mnemonic", "code": "invalid_value", "detail": "Forms the prefix of this namespace’s fixed name."},
    {"kind": "label", "key": "name", "code": "derived_key", "detail": "cmapi sets name from the namespace (abc-payments-dev)"},
    {"kind": "annotation", "key": "cmapi.net/team-dl", "code": "missing_required_key", "detail": "A team address in company.net is required."}
  ],
  "findings": []
}
```

A stale-folder refusal names the version the planner saw. The client still fetches the values that belong to it. A checked-decision mismatch uses the same registered code with the discriminator `"precondition": "checked-plan"`.

```json
{
  "type": "https://cmapi.ephico2real.com/problems/precondition-failed", "title": "precondition failed",
  "status": 412, "code": "precondition-failed", "detail": "The namespace changed in Git since you read it",
  "etag": "3f9a1c0b7e2d4a69"
}
```

Use `reserved_key` for system/reserved writes, `invalid_key` for the wrong kind, disallowed prefix or syntax, `invalid_value` for value rules, `too_many_keys` and `annotations_too_large` for limits. Supply kind/key on each addressable field error and kind on aggregate errors. An operator-only attempt gives 403 `forbidden` immediately. See `cmapi/src/cmapi/core/metadata.py:852`, `cmapi/src/cmapi/core/metadata.py:879`, `cmapi/src/cmapi/core/metadata.py:933` and `cmapi/src/cmapi/core/errors.py:38`.

## 4. How does the tab work?

**Options.** Free text permits typos and a long unfiltered list exposes irrelevant targets. Choose the #479 form layout with a cluster single select, then a single-select typeahead over the authorized namespace results. Keyboard navigation, explicit selection, no-match text and a clear action support large lists. Typed text never creates a target. [PatternFly Select, Typeahead](https://www.patternfly.org/components/menus/select/#typeahead)

1. Choose the cluster, then select a namespace. Use the write-filtered reads from §3 and the grant for that environment. Loading, empty and access-denied states have no editable draft. A target switch clears the plan and prompts before discarding edits.
2. Show Git values, ETag and any open request. Group the locked identity, automatic and managed keys with their reasons. Render named fields from the selected operation’s schema, including both kinds of app-environment. Reuse #479’s pattern-validation Web Worker, generated enums, email domains and URL rules. Required means “must survive the merge”. A held missing required field stays distinguishable from a user deletion.
3. Show current other keys in their own editable list. **Additional labels and annotations (optional)** is a closed disclosure containing two initially empty tables for *new* keys. Opening it sends nothing. Add inserts a blank row with placeholders. Removing a draft row abandons it. Removing an existing key stages null with Undo. Closing retains edits. Validate as the person types, report duplicates on the row, and count merged keys and UTF-8 bytes.
4. Preview only effective changes, with kind, key, before, after and source. Distinguish absent, empty string and removed. Check calls dry run, replaces the estimate with the server diff, findings and approval, then enables Submit. Any edit, target change, response for an older draft or new ETag invalidates Check. A 202 shows the request ID and tracking link. An ambiguous response is retried with the same key.
5. A 412 at Check or Submit rereads the namespace and schema. Keep intent visible. Show current Git values and the draft side by side, mark overlaps, and require an explicit choice for each conflicting key before Check. A 409 shows the holding request and disables submit until the target is read again. Quotas already reads the ETag, shows the holder and rereads on 412/428 at `cmapi-portal-ui/src/portal/QuotasTab.tsx:421`, `cmapi-portal-ui/src/portal/QuotasTab.tsx:455` and `cmapi-portal-ui/src/portal/QuotasTab.tsx:526`.

[Open the standalone portal mockup](mock-change-namespace.html). Choose CRC and the payments namespace. Change Critical level to see the added approval. After Check, use the mock’s “Simulate external change” control and Submit to exercise the 412 recovery.

## 5. Which races need a guard?

**Options.** Last-write-wins loses edits. A browser lock misses other clients. A dry-run reservation would block people who only preview. Use a Git folder precondition, an atomic database lock on submit, and a checked-plan comparison for the portal. [RFC 9110 §13.2](https://www.rfc-editor.org/rfc/rfc9110#section-13.2)

| Race | Check and outcome |
|---|---|
| Live cache lags Git, or Git changes after load | Read the Git projection and folder ETag together. Each PATCH reads the latest folder and checks If-Match before merging. 412 includes current body `etag`. Reread both resources, retain only touched keys, drop edits already satisfied, and ask “Use current” / “Keep my edit” where both versions changed. A new Check is mandatory. |
| Two editors check the same version | Both read-only checks may pass. The unique partial index on (cluster_id, namespace) arbitrates concurrent inserts, across namespace actions. Exactly one new request wins. The loser receives 409 with the holder while open, or 412 once Git moved. An unrelated namespace proceeds. See `cmapi/src/cmapi/core/db/models.py:194`, `cmapi/src/cmapi/core/db/repo.py:148`. |
| A request is already pending | Show `openRequest` on selection. Proposed dry-run preflight also returns 409 for a known holder. It takes no lock. Submit relies on the index, including the delivery states that still hold it. Reload after closure. |
| Git changes after planning but before delivery | Compare the folder again immediately before recording a new intent. Git and SQL have no joint transaction. Keep the captured base/files and the worker’s folder check, plan-hash verification and PR merge check. A later conflicting change supersedes the request before delivery. See `cmapi/src/cmapi/jobs/push_branch.py:1`, `cmapi/src/cmapi/jobs/pr_checks.py:15`. |
| Rules, grants or approval change during editing | Revalidate schema ETag before Check and on reload. Use one loaded policy snapshot per plan. Always redo authorization, classification, validation, rendering and approval on submit. A now-forbidden or invalid edit gets its normal 403/422. For otherwise valid changes the portal sends If-Checked-Plan. Compare under the submit transaction after the final daily approval calculation and before assigning the render’s request ID. Mismatch gives 412 with `precondition: "checked-plan"`. Refresh rules and show the new decision. |
| Configuration rollout serves different pod generations | Compute checkToken as a deterministic digest over actor, target, normalized body, folder ETag, effective policy revision, planned file hash and material decision (approval, capacity verdict, findings). Identical replicas agree. Include all effective metadata and approval inputs. During a rollout admit writes only on the active configuration generation, or drain old writers before cutover. A superseded generation cannot accept an old check. Pin the accepted decision and render inputs for delivery, and supersede if rerender or merge checks fail. |
| Double click, timeout or late response | Bind the displayed plan to target, body, ETag and current edit generation. Discard late responses, disable Submit in flight. On retry, authenticate and verify target access first, then replay the caller’s already-recorded request for the same intent before comparing old preconditions or checking the holder. A new intent gets a fresh key. Scope fingerprints by method/route, target and body and preserve existing replay records. See `cmapi/src/cmapi/plugins/namespaces/router.py:64`. |

## 6. What proves delivery?

**Options.** Screenshots alone cannot prove what reached Git or which submissions won a race. Use service, schema and concurrency tests for #483, browser interaction tests for #484, and generated-contract plus renderer checks for #485. Each story uses the same example request and dry run. [#479 delivery and documentation standard](namespace_metadata.md#9-delivery)

**#483 · contract and policy.** Deliver write-filtered reads, the patch schema, checked-plan header, diff and documented errors. Implement one function per step: read target, check version, classify submitted keys, validate intent, merge each map, validate merged limits, preserve/render the namespace, build the diff, calculate approval, compare the checked decision, record the request. Reuse existing parser, validator, render, auth and request repository. Put deployment-specific keys, domains, limits, protection values and approval groups in their existing data files.

- Run the same corpus against two domains and an altered prefix/sensitive list. Cover add/change/remove/echo/absent, null vs empty, map-null compatibility, legacy findings, required removal, fixed first assignment, both kinds of a derived key, kind collisions, expiry bypass, protected value and environment-specific operator grants.
- Compare plan and rendered Git maps, deltas, source and approval. Multiple sensitive differences add one slot. Test UTF-8 boundaries, limits on merged maps, adoption markers, preserved governed/extra keys, legacy quota overrides, SA/grants, and a metadata-only no-op. Verify dry run writes no request, lock or job.
- Integration tests for write-filtered lists/direct reads, stale live cache, missing/stale If-Match on both paths, two concurrent submissions, open delete/update, same-key retry, reused key with other intent, policy reload after Check, changed approval inside submit, old writer during rollout and worker supersession. Assert exact status/code, request count, job count and holder.
- Validate both success examples against the operation models, run the OpenAPI gate against base/release and explain any intentional compatibility change. Default create schemas still satisfy A5. Existing quota and API clients submit without If-Checked-Plan.

**#484 · portal.** Deliver the new tab, shared #479 field/disclosure components, Git-based editor and Check/Submit state handling. Use the dry-run approval response as authoritative. Map server field errors to (kind, key) and surface aggregate and dependency errors next to Check.

- Browser tests at 390, 820 and 1440 px, keyboard-only search/selection, visible focus, labels and live feedback. Exercise empty results, writable vs read-only environment, operator vs ordinary user, closed/empty new rows, edit/remove existing extras, explicit empty value, invalid input, count/byte limits and sensitive approval.
- Verify exact sparse JSON, headers, 200 then 202, no initial submit, invalidation after every edit, late response, 409 holder, 412 at Check and Submit, overlapping and disjoint drafts and retry after a lost 202. Confirm a second Check and explicit Submit are required after recovery.

**#485 · Swagger and ReDoc.** Generate both from the same registered operation and the active instance’s data per #480. Apply the same standard to the changed read operations and their query variants. Keep a single generator in `cmapi/src/cmapi/core/docs.py:96` and `cmapi/src/cmapi/core/docs.py:141`. Use Swagger's extension display settings at `cmapi/src/cmapi/main.py:272` and native example selectors in both renderers.

```text
Swagger UI   Namespaces and metadata
PATCH  /api/v1/clusters/{cluster_id}/namespaces/{ns}    Change a namespace
Parameters   cluster_id* string path · ns* string path · dryRun boolean query (false)
             bearer authorization · If-Match* string header · Idempotency-Key string header (submit*)
             If-Checked-Plan string header (checked submit)
Request body*  application/json   [Example Value] [Schema]   ▾ Metadata change / Quota change
Schema       NamespacePatch → labels → company.net/cl   string enum 0…6    required in result
                             → cmapi.net/cost-center    string(pattern) | null
                             → other key                string(label value) | null
Responses    200 Plan + metadataDiff  · 202 ChangeRequest
             400 401 403 404 409 412 422 428 502 503    expand status → Examples ▾ → problem+json
             412 Examples ▾ Folder changed / Checked decision changed
Extensions   x-cmapi-permission = namespaces:write   x-cmapi-plugin = namespaces
             x-plugin-version = instance version     x-codeSamples = curl with headers and full body
```

```text
ReDoc   Navigation                 Operation and schema                     Samples
        Namespaces and metadata    PATCH Change a namespace                 Request  [Payload | curl]
          Change a namespace       Security, path/query/header parameters   Example ▾ Metadata change
                                   Expand labels and annotations            Same JSON as §3
                                   Type, enum, pattern, lock reason, null   Response [200 | 202 | 400 | …]
                                   Expand 422 → problem codes               Example ▾ policy-violation
                                   Extensions and other-key limits         kind, key, detail, findings
```

- Generate realistic examples from config, include member-null removal, the complete responses above and one named example **per code per status** in §3. Show required path/body, conditional headers, all patch fields’ types, formats and rules, `x-cmapi-edit`, derived/prefix/suffix/default markers and `x-cmapi-other-keys`. Mark required *in result* separately from required *in the sparse request*. Generate a complete curl sample. Regenerate docs/04, contract and portal types.
- Compare operation codes with the registry and reachable handlers. Validate media types, examples, extensions, parameter locations, default create and patch schema equality to their respective projections. Render both docs UIs and verify example selection for 200/202, both 409s, 412/428 and per-key 422. Capture screenshots and run the existing documentation citation and contract gates.

**Order beside #479.** Coordinator reviews #482 first. Land #479 phase 1’s loader, derived/default and naming rules in core/metadata.py first. Rebase #483’s update checks onto that rule model. Pair #479 phase 2’s schema work with #483’s PATCH projection and settle the shared PlanView compatibility tests before either generator ships. #484 follows the #483 contract and reuses the components from #479 phase 3 in a separate tab. #485 can prepare examples against #483 fixtures while #484 proceeds, then integrate with #479 phase 2/#480’s shared core/docs.py generator and capture both docs renderings. Use #479 phase 4’s selected CRC configuration and re-rendered policies for joint acceptance, and phase 5 for final cross-references in docs/02, 04, 14 and 18. CRC domain, naming and sensitive CL selections remain owner configuration choices.
