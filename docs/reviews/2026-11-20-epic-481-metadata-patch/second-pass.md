# Second pass on the #482 design (Opus 5.5, coordinator, 2026-11-20)

Read in full: `design.md` (Codex `gpt-6.2-astra`, high, 2026-11-20). Measured against the owner's standing rule (plain,
methodical code a junior engineer can follow; rules in data) and the decisions already taken for create (#479).

## Kept
- **Patch format:** JSON Merge Patch semantics inside the two maps of the existing `PATCH` (`application/json`, the `NamespacePatch` envelope). Omitted keeps, a value sets, member `null` removes.
- **Which keys change:** decided per (kind, key) from `metadata-keys.yaml`, in the design's order: path identity, `system`, reserved and adoption, `operatorOnly` (needs `namespaces:protect`), `value.from` (automatic), `namespacePrefix` and `namespaceSuffix` (fixed), required (change, never remove), named extras and `allowOther` (add, change, remove), and `sensitiveKeys` (one more approval per request).
- **Contract:**
  - `If-Match` with the folder ETag (428 without it, 412 when stale);
  - the one-open-request lock (409 `change-pending`);
  - the dry run's `metadataDiff` (`before`, `after`, `source` per key, effective changes only);
  - the 202 `ChangeRequest`;
  - no new problem codes.
- **Expiry:** stays on the existing expiration operations; the tab shows it read-only.
- **Definition of done:** the stories' DoD (§6), minus the parts ruled out below.

## Ruled out or simplified
| # | Proposal | Ruling | Why |
|---|---|---|---|
| 1 | `If-Checked-Plan` header and a `checkToken` digest | Rejected | `If-Match` pins the folder, the server re-plans and re-checks every submit, the portal disables Submit after any change. Same as create's R1 |
| 2 | Refuse writes from an old configuration generation during rollout | Rejected | Every pod checks against its own loaded rules on every request; a config change restarts the pods |
| 3 | `?forWrite=true` on three reads | Simplified | The portal filters clusters by the environments where `GET /api/v1/me` grants `namespaces:write`, and uses the existing namespace list. One additive field: the detail read returns `gitLabels` and `gitAnnotations` from the same Git read as its ETag |
| 4 | `GET /metadata-keys?operation=patch` | Simplified | One response; each key gains `x-cmapi-edit: {mode: fixed or automatic or required or optional, reason}` (additive) |
| 5 | Per-key "Use current / Keep my edit" merge on 412 | **Kept for overlapping keys** (revised) | Re-applying blindly would overwrite another person's change to the same key (a lost update). Only keys both sides changed ask the choice; a new Check is required |

Row 3 was replaced the same day: no permission filter on discovery (the owner, #482), and the read's field is `git: {labels, annotations}` (design.md §4.2).

## Order
#479 Phase 1 (loader and rule model in `core/metadata.py`) merges first. Then #483 (contract), #484 (tab, reusing #479's field components), #485 (Swagger and ReDoc to the #480 standard).

## Live cluster state (owner, 2026-11-20)
The detail read gains the Git labels and annotations (same read as the ETag) and `sync: {state: in-sync|pending|drift|unknown, openRequest, driftedKeys}`. The tab shows Git (desired), Live (cluster) and Your change, a status strip and per-key markers. Concurrency is already guarded: one open request per namespace (409) and If-Match on the folder ETag (412).
