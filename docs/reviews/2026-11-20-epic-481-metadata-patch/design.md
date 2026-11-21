# Change the metadata of an existing namespace: design

Epic #481 · spike #482 · stories #483 (contract), #484 (portal tab), #485 (Swagger and ReDoc).
Status: **final design for build** (2026-11-20). Base design by Codex `gpt-6.2-astra` (`codex-base-design.md`, beside this file);
second pass and this final version by the coordinator (Opus 5.5), with the owner's decisions of 2026-11-20. Reviews
follow the build: Codex `gpt-6.2-astra` high, then Fable.

**Mockup:** the Namespaces tab, https://claude.ai/artifact/1cmy5F8UVbmgF5aFQ1wNU9 (private to the owner until shared).

The create design is `docs/reviews/2026-11-20-issue-479/namespace_metadata.md` ("#479" below). This design reuses its
rules, keys, look and standard, and never contradicts them.

---

## 1. The owner's requirements

| # | Requirement | Where |
|---|---|---|
| M1 | Change or add metadata on an existing namespace, like a Kubernetes patch | §3, §4 |
| M2 | Static keys cannot change: the namespace name, `name`, app-environment and the mnemonic | §3 |
| M3 | An API contract and a portal UI, in the #480 standard for Swagger and ReDoc | §4, §6, §8 |
| M4 | A new tab, **Namespaces** (the owner's name), that asks for the cluster, then the namespace | §6 |
| M5 | Git is the store, so two people cannot change a namespace at the same time | §5 |
| M6 | Show the cluster's live state beside Git, with drift highlighted | §4.2, §6 |
| M8 | Auto lookup after choosing the cluster, with the mnemonic as a helper and a filter | §4.4, §6 T1 |
| M7 | Plain, methodical code a junior engineer can follow; complex only where it is the only way to keep a guarantee | §7 |

---

## 2. The flow, from the person to the cluster

1. The person opens the **Namespaces** tab, picks a cluster, then a
   namespace (a search over that cluster's managed namespaces).
2. The portal reads the namespace: its Git metadata and folder ETag, its live metadata, and its sync state (§4.2).
3. The person edits the changeable fields. Fixed keys are shown locked, with the reason.
4. **Check** sends the change as a dry run (`PATCH …?dryRun=true` with `If-Match`). cmapi answers with the before/after
   diff and the approval that will apply.
5. **Submit** sends the same body (with `If-Match` and an `Idempotency-Key`). cmapi records one request, which holds the
   namespace until it finishes: approval, the bot's pull request to `cmapi-cluster-configs`, merge, and sync to the
   cluster, exactly as a create.
6. The tab shows the request; its live state moves from **Pending** to **In sync** when the cluster has the change.

---

## 3. Which keys can change

Decided per (kind, key) from `metadata-keys.yaml`, never from a list in code. Checked in this order; the first match wins.

| Order | Key class (from configuration) | On an existing namespace | Reason shown |
|---|---|---|---|
| 1 | The namespace name (the path) | Fixed | "A namespace cannot be renamed." |
| 2 | `system` | Fixed, for everyone | "Managed by cmapi." (expiry: "Change it with Extend, Set expiry or Make permanent.") |
| 3 | `reservedPrefixes`, `adoptionLabels`, or a key no stanza allows | Fixed; kept as it is in Git. A key no stanza allows may be **removed** (`null`), never set or changed (coordinator ruling on #492 M2: otherwise, with Kyverno enforcing, a namespace holding one could never be changed). Since #497 the policy keeps such a key while its value is unchanged, so a change that leaves it passes too | "Reserved for the platform." / "Marks how the namespace was first made." / "Not allowed by this instance's rules." |
| 4 | `operatorOnly` | Changeable only with `namespaces:protect` in that environment; fixed otherwise | "Needs namespaces:protect in dev." |
| 5 | `value: {from: …}` (`name`, app-environment) | Automatic: fixed; an exact echo is accepted | "Copied from the namespace name." / "Copied from the cluster's environment." |
| 6 | `namespacePrefix` (mnemonic), `namespaceSuffix` | Fixed; an exact echo is accepted | "Part of the namespace's fixed name." |
| 7 | `requiredLabels`, `requiredAnnotations` (the rest) | Change to a valid value; never remove | "Required on every namespace." |
| 8 | `extraLabels.keys`, `extraAnnotations.keys` | Add, change, remove | — |
| 9 | `allowOther` | Add, change, remove, within the prefixes and limits | — |
| + | `sensitiveKeys` (on top of 7–9) | Any effective change adds **one** approver-platform approval per request | "Changing this key needs one more approval." |

A missing required key on an old namespace (adoption, #234) is shown as a finding and can be added. A missing fixed key
(e.g. no mnemonic on an adopted namespace) is not repaired here; that is adoption's job (story #26).

---

## 4. The API contract

### 4.1 The change: `PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}` (exists; extended)

- **Format.** JSON Merge Patch semantics (RFC 7396) inside the two maps of today's `NamespacePatch` body
  (`application/json`): a key left out is kept, a value sets it, `null` removes it. Other body fields (`tier`, `quota`,
  `limitRange`, `justification`, `onBehalfOf`) are unchanged.
- **Headers.** `If-Match: "<etag>"` (required: 428 without it, 412 when Git moved), `Idempotency-Key` (required on submit:
  400 without it), `Authorization`.
- **Permission.** `namespaces:write` in the target environment; `namespaces:protect` too for an operator-only key.
- **Answers.** 200 with the plan (dry run) or 202 with the request. The plan gains `metadataDiff` (additive):

```json
{
  "metadataDiff": {
    "labels": {
      "company.net/cl":        {"before": "1",       "after": "2",  "source": "request"},
      "cmapi.net/cost-center": {"before": "cc-4410", "after": null, "source": "request"}
    },
    "annotations": {
      "runbook.company.net/url": {"before": null, "after": "https://wiki.company.net/abc/runbook", "source": "request"}
    }
  }
}
```

`metadataDiff` holds only effective changes; `null` as `before` means added, as `after` means removed.

- **Errors.** Registered codes only, no new code. 400 `idempotency-key-required`; 401 `unauthenticated`; 403 `forbidden`,
  `environment-forbidden`; 404 `cluster-not-found`, `object-not-found`; 409 `change-pending` (with the holding request),
  `idempotency-replay`; 412 `precondition-failed` (with the current `etag`); 422 `policy-violation` (one `errors` entry per
  key: `reserved_key`, `invalid_key`, `invalid_value`, `derived_key`, `missing_required_key`, `too_many_keys`,
  `annotations_too_large`), `validation-failed`, `no-change`, and the identity and target codes the route already
  declares; 428 `precondition-required`; 502 `git-unavailable`; 503 `cluster-unreachable`, `validator-unavailable`.

**Request example (Check):**

```http
PATCH /api/v1/clusters/CRC/namespaces/abc-payments-dev?dryRun=true
Authorization: Bearer <token>
Content-Type: application/json
If-Match: "3f9a1c0b7e2d4a68"
```

```json
{
  "labels": { "company.net/cl": "2", "cmapi.net/cost-center": null },
  "annotations": { "runbook.company.net/url": "https://wiki.company.net/abc/runbook" },
  "justification": "Raise the critical level, retire the cost code and add the on-call runbook."
}
```

Submit sends the same body without `dryRun`, with the same `If-Match` and an `Idempotency-Key`.

### 4.2 The read: `GET /api/v1/clusters/{cluster_id}/namespaces/{ns}` (exists; extended, additive)

Today it returns the live namespace and the folder ETag. It gains the Git metadata and the sync state, so the tab can
show Git and the cluster side by side:

```json
{
  "name": "abc-payments-dev",
  "etag": "3f9a1c0b7e2d4a68",
  "labels":      { "…": "live, from the watch cache (as today)" },
  "annotations": { "…": "live (as today)" },
  "git": {
    "labels":      { "company.net/cl": "1", "cmapi.net/cost-center": "cc-4410", "…": "…" },
    "annotations": { "cmapi.net/team-dl": "payments-team@company.net", "…": "…" }
  },
  "sync": {
    "state": "drift",
    "openRequest": null,
    "driftedKeys": [ { "kind": "label", "key": "company.net/lob", "git": "amgsst", "live": "amgsst-old" } ]
  }
}
```

`sync.state` is decided in one small function, in this order:

| State | When |
|---|---|
| `pending` | An open request holds the namespace (`openRequest` gives its ID and status), or Git was merged and the cluster does not have it yet |
| `drift` | No request is open and a governed or extra key differs between Git and the live namespace (each one in `driftedKeys`) |
| `in-sync` | Git and the live namespace have the same governed and extra keys |
| `unknown` | The cluster's watch is not fresh (as the Policies tab's states) |

Keys cmapi or other controllers write only on the cluster (not in Git) are left out of the comparison (a small,
configurable ignore list: `kubernetes.io/metadata.name`, `openshift.io/*`, Argo CD tracking keys).

### 4.3 `GET /api/v1/metadata-keys` (exists; extended, additive)

Each key gains `x-cmapi-edit: {"mode": "fixed" | "automatic" | "required" | "optional", "reason": "…", "sensitive": bool}`
from §3, so the portal shows fixed keys locked with their reason without a list of its own. One response, the same for
create and change.

### 4.4 Discovery within the cluster: `GET /api/v1/clusters/{cluster_id}/namespaces` (exists; extended, additive)

The owner (2026-11-20): auto lookup after choosing the cluster, with the mnemonic as a helper and a filter. Today this
list has no search. It gains, additively (no parameter answers as today):

| Parameter | Meaning |
|---|---|
| `q` | Text the name, team or app contains; names starting with it rank first |
| `mnemonic` | Exact mnemonic (the value of the key with `namespacePrefix: true`, so any company's key works) |
| `limit` | 10 by default, at most 50 |

The answer gains `total` and `facets: {mnemonics: {<mnemonic>: <count>}}` (that cluster's mnemonics, for the current
filters except `mnemonic`), and each item gains `mnemonic`, `team` and `sync` (§4.2's state). Served from the cluster's
watch cache by the same query code as `GET /api/v1/quotas` (one implementation). The mnemonic is read from the label
whose key has `namespacePrefix: true`; nothing names a company.

---

## 5. Two people, one namespace (M5)

| Case | Guard (already built unless marked) | What the person sees |
|---|---|---|
| Two people submit at once | One open request per namespace (unique index on `(cluster_id, namespace)`) | The second gets 409 `change-pending` with the holder's request ID; the tab shows "abc-payments-dev is held by req-… (pending approval)" |
| Someone's request merged into Git while this person edited | `If-Match` on the folder ETag | 412 at Check or Submit. The tab reloads Git, re-applies the person's changes, and for each key **both** changed asks "Use current" or "Keep my edit" (the only way to avoid a lost update). A new Check is required |
| A hand change on the cluster (`kubectl label`) | Live vs Git comparison (new, §4.2) | "Drift" with the key and both values; the person's change applies to Git, which Argo CD or apply restores |
| The configuration changes during an edit | The server re-checks every submit with its own rules | A now-refused change gets its 422 on that key |
| A double click or a lost answer | `Idempotency-Key` (24 h) | The same request comes back |

The configuration rollout window (an old pod accepting a write the new rules forbid) is cross-cutting and tracked as #486.

---

## 6. The portal tab: Namespaces (M4, M6)

The tab is where people browse their namespaces and change one. "New namespace" stays the create tab beside it
(later it may become a **+ New** button inside Namespaces).

```
 Namespaces ────────────────────────────────────────────────────────────────────────────────
  Cluster     [ CRC (dev)          ▾ ]   only clusters where you hold namespaces:write
  Namespace   [ abc-pay…            🔍 ]  → abc-payments-dev · abc-payments-rnd …

  ● Drift   1 key on the cluster differs from Git · no open request            [ Reload ]

  ┌ Key                          │ Git (desired)        │ Live (cluster)       │ Your change          ┐
  │ Name                🔒        │ abc-payments-dev     │ abc-payments-dev  ✓  │ Part of the fixed name│
  │ App environment     🔒        │ dev                  │ dev               ✓  │ Copied from the cluster│
  │ Mnemonic            🔒        │ abc                  │ abc               ✓  │ Part of the fixed name│
  │ Line of business *           │ amgsst               │ amgsst-old  ⚠ drift │ [ amgsst          ]   │
  │ Critical level *  (sensitive)│ 1                    │ 1                 ✓  │ [ 2 ▾ ]  changed      │
  │ Team *            (sensitive)│ payments             │ payments          ✓  │ [ payments        ]   │
  │ Cost center                  │ cc-4410              │ cc-4410           ✓  │ [ removed ]  ↺ Undo   │
  │ Team DL *                    │ payments-team@…      │ payments-team@… ✓    │ [ payments-team@… ]   │
  │ Expires             🔒        │ 2026-12-15           │ 2026-12-15        ✓  │ Use Extend / Set expiry│
  └──────────────────────────────────────────────────────────────────────────────────────────┘
  Existing additional keys:  team.company.net/squad = checkout   [ edit ] [ remove ]

  ▸ Add labels and annotations (optional) · none          ← closed and empty by default

  ┌ Your change ───────────────────────────────────────────────────────────────┐
  │ label company.net/cl          1 → 2                   (sensitive: +1 approval)│
  │ label cmapi.net/cost-center   cc-4410 → (removed)                            │
  │ annotation runbook.company.net/url   (new) → https://wiki.company.net/abc/…   │
  └─────────────────────────────────────────────────────────────────────────────┘
  Justification * [ Raise the critical level, retire the cost code … ]
                                         [ Check (dry run) ]   [ Submit ] (off until checked)
```

| # | Behaviour |
|---|---|
| T1 | **Cluster first**: every cluster `GET /api/v1/clusters` lists (no per-permission filter for now; the owner, 2026-11-20: "don't complicate this"; the PATCH still checks the caller's permission). Choosing one shows that cluster's **mnemonic chips with counts** (§4.4 facets). **Namespace lookup** is a PatternFly typeahead: 2+ letters, 250 ms after the last key, `q` (+ `mnemonic`, `limit=10`); if the first word typed is one of the cluster's mnemonics, its chip turns on by itself (`abc pay` = abc's namespaces containing pay). Results show team and sync state; ↑↓ and Enter open one; only the latest answer is shown; "Recent in <cluster>" from the browser. Typed text never creates a target |
| T2 | Loading a namespace reads §4.2 and the schema of §4.3; fixed keys show 🔒 with their reason; sensitive keys are marked |
| T3 | Three columns, Git, Live and Your change, and a status strip: **In sync**, **Pending** (request ID, status, link), **Drift** (count; each drifted key marked ⚠ with both values), **Unknown** |
| T4 | Changeable fields reuse #479's field components and checks as you type; removing an existing optional key stages `null` with Undo |
| T5 | Existing extra keys are listed with edit and remove; new ones go in the **closed, empty** "Add labels and annotations" section (#479 P9) |
| T6 | The change box lists only effective changes, before → after, with sensitive marks; Justification is required |
| T7 | **Check** sends the dry run; the server's `metadataDiff` and approval replace the estimate; **Submit** stays off until checked and goes off after any change |
| T8 | 409: show the holder and disable Submit until reloaded. 412: reload, re-apply, ask per overlapping key, require a new Check |
| T9 | After 202: show the request with its link; the strip turns **Pending**, then **In sync** when the cluster has the change (refresh on demand, no polling loop) |

---

## 7. Code rules (the owner's)

Plain and methodical: one function per step, named for it; rules in data (`metadata-keys.yaml`, the ignore list),
never scattered branches; no new problem codes; each behaviour has a named test failing before and passing after; the
PR states the workflow as a numbered list from request to answer, with file and function per step. The only
deliberately complex part is the per-key choice after 412, which is the only way to prevent a lost update.

---

## 8. Stories and their definition of done

| Story | Done when |
|---|---|
| **#483 Contract** | §4.4's lookup (`q`, `mnemonic`, `limit`, facets, ranking; the list without parameters unchanged); merge-patch semantics in both maps; the key classes of §3 from data, each with a test (fixed, automatic, operator-only, required, optional, extra, sensitive, adoption finding); `metadataDiff` in the dry run; the detail read's `git` and `sync` (in-sync, pending by open request, pending by unsynced merge, drift by a hand label, unknown); `x-cmapi-edit` in `metadata-keys`; 409, 412, 428 and per-key 422 tests; the contract regenerated; oasdiff additive |
| **#484 Portal tab: Namespaces** | T1–T9 as browser checks at 390, 820 and 1440 px in both themes; each with a mutant killed by its own check; the 409 and 412 paths; keyboard selection; screenshots |
| **#485 Swagger and ReDoc** | The PATCH and the extended reads in the #480 standard: every status, one named example per problem code, the merge-patch example with a `null` removal, `x-cmapi-edit`, the Extensions; both renderers checked |

Order: #479 Phase 1 merges first (it owns the loader and rule model in `core/metadata.py`). Then #483, #484, #485, each
one PR. Each PR: built by Opus 5.5 high; reviewed by Codex `gpt-6.2-astra` high; then Fable (on its token budget); the
coordinator runs what Codex and Fable cannot (PostgreSQL, browser), rules on every finding with its test, merges on
green CI.
