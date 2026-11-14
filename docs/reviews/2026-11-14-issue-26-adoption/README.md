# Story #26: the adoption design

OB1 run 6 (Opus 5.5 at high) wrote this design on 2026-11-14, from the owner's decisions on #26. Fable 5.2 reviewed it
(`fable-review.md`, findings A1 to A10), and this version applies all ten and the owner's three later decisions (§1,
items 6 to 8). It is a design: no adoption code exists yet (`cmapi/src/cmapi/plugins/` has no adoption plugin), and
building it stays in Wave 8 (D14). Each decision says why, and where a fact comes from. docs/02, "Adoption plugin", holds
the short form of this design.

## 1. The owner's decisions (#26, 2026-11-14)

1. cmapi's Git repository is `cmapi-cluster-configs` (#228).
2. "cmapi reads the cluster, finds the namespaces labelled `cmapi.net/adopt`, and extracts each one's Namespace,
   ResourceQuota and LimitRange."
3. "they would be custom as the existing ones don't have to match our standard tiers. we will migrate the raw yaml
   as-is." An adopted namespace gets tier `custom` with its quota and LimitRange unchanged, not mapped to a named tier.
   Only server-set fields and the configured skip prefixes are dropped. cmapi adds its system keys. Values outside the
   custom bounds are adopted as they are and reported.
4. The test plan: test namespaces only, opt-in, kind then CRC, no change to the live object.
5. The input a typical namespace gives (the owner's sample, 07:57Z): `abc-rnd`, its company labels,
   `company.net/provisioner: cluster-configs`, two empty optional labels, and the annotation `company.net/app-environment`.
   At 14:28Z the owner said that the sample's `name: aao-rnd` was a typo: keep one test namespace with a deliberate
   mismatch, to prove the finding, and make the others correct.
6. **`cmapi.net/adopt` stays on the live namespace** (owner's decision on #26, after Fable's review). It is ignored after
   the adoption: `cmapi.net/managed` means adopted, and cmapi stays read-only on the clusters. This replaces "cmapi removes
   `cmapi.net/adopt`" in item 3.
7. **A required key missing at adoption is never forced, only reported.** Each plan lists it until a request sets it. This
   replaces the earlier rule that the first update must add it.
8. **cmapi reads the namespace state, and nothing else.** From cmapi's standpoint no earlier repository exists: the
   adoption reads only the live namespace from the cluster, and this design has no step about another repository.
   `company.net/provisioner: cluster-configs` is only a label value: kept as it is, recognised by `adoptionLabels`,
   never followed.
9. The two contact keys are annotations now (#215, 14:25Z): an existing namespace that carries them as labels keeps those
   labels at adoption, and each is a finding.
10. **ResourceQuota and LimitRange are adopted free-form** (#251): any number of each, with any content, each kept raw
    under its own name, one file per object. The database and the API views hold a list of objects, plus derived numbers
    where a value maps (D17).
11. **`company.net/provisioner` can be kept or removed after adoption** by an approved request, from Git and from the
    live namespace (#251; D18).
12. **Separate LimitRange objects for CPU and memory are the company standard, in cmapi's own rendering too** (#251,
    15:28Z; D19). "We don't enforce limit ranges for storage" (#251, later the same day): storage is governed only by
    the ResourceQuota keys `requests.storage` and `persistentvolumeclaims`.
13. Admin operations on an onboarded cluster (filter namespaces by any metadata, bulk changes as approved requests with a
    dry run, KPIs on adopted namespaces) are a later feature, #252 (Wave 8). D18's removal is one of its operations.

## 2. The design in one paragraph

An operator, or the namespace's admin, asks cmapi to adopt a namespace that carries `cmapi.net/adopt: "true"`. cmapi reads
the live Namespace, every ResourceQuota and every LimitRange of it from the cluster, drops only what the API server sets and
the keys under the skip prefixes that no other tool would remove, and writes them to `cmapi-cluster-configs` exactly as they
are, with tier `custom` and its own system keys added. Each difference from the instance's rules (#215's stanzas, the
custom tier's bounds) is a finding in the plan, never a change. The request is approved like any other, the bot opens the
pull request, and on the merge the cluster's Argo CD takes the namespace over. The worker then checks that the live
objects changed only by the keys this design lists, or the request fails, and nothing that existed before is removed.

![The adoption flow](../../diagrams/adoption/adoption.light.png)

## 3. Decisions

### D1. Which namespaces are candidates

A namespace is a candidate when each step passes, in this order (docs/02's order, kept):

1. Not a built-in exclusion (`default`, `openshift`, `openshift-*`, `kube-*`), and not a configured one (`adoption.yaml`:
   names, globs, label selectors, global or for an environment or a cluster; exclusions add up, never subtract). Not
   `Terminating`.
2. Not managed already: no `cmapi.net/managed: "true"`, and no folder in Git. Since `cmapi.net/adopt` stays on the
   namespace (§1, item 6), this step is what makes the label inert after the adoption.
3. **Not tracked by another Argo CD Application.** A namespace whose `argocd.argoproj.io/tracking-id` annotation names an
   Application that is not cmapi's is skipped, with the Application named. The `app.kubernetes.io/instance` label counts
   only when the hub's Argo CD uses label tracking (`application.resourceTrackingMethod: label`). Otherwise it is a
   recommended label that Helm and kustomize users set by hand, and it is a finding, not a skip (Argo CD, "Resource
   Tracking": the annotation is the default). Two GitOps owners of one object fight: Argo CD's `FailOnSharedResource`
   exists because a sync must "fail ... whenever it finds a resource in the current Application" that is "already applied
   in the cluster by another Application" (Argo CD, "Sync Options").
4. **Opt-in:** `cmapi.net/adopt: "true"` (quoted: a label value is a string).

`adoptionLabels` (#215; for example `company.net/provisioner: {recognise: [cluster-configs]}`) never selects a namespace by
itself. It marks a namespace that another tool made: the unmanaged-namespaces report and `GET .../adoption/candidates`
show it as "recognised", so an operator knows which ones to label. Opt-in stays the gate (the owner's decision 2).

### D2. What cmapi reads, and from where

From the cluster, through cmapi's per-cluster read client: the Namespace, every ResourceQuota and every LimitRange in it,
each with its `uid`, `resourceVersion` and `metadata.managedFields`. Nothing else is adopted. ServiceAccounts,
RoleBindings and SCC grants stay unmanaged: the owner's decision names three kinds, and Argo CD does not prune an object
it never tracked. The plan reports how many of the other kinds the namespace has, so a later request can bring them in
(the namespaces plugin already manages ServiceAccounts and grants). The cluster is the only source (§1, item 8).

### D3. Raw, as it is: what is dropped, and who owns each key

The object is written to Git as YAML with these fields removed, and nothing else:

| Removed | Why |
|---|---|
| `metadata.uid`, `resourceVersion`, `generation`, `creationTimestamp`, `managedFields`, `selfLink`, `deletionTimestamp`, `deletionGracePeriodSeconds` | The API server sets them (the owner's list, plus the other read-only metadata of the same kind) |
| `status` | Server-set |
| A Namespace's `spec.finalizers` (`[kubernetes]`) | The API server sets it on each namespace; a namespace has no other `spec` field |
| Each label or annotation under a skip prefix of `adoption.yaml`, when D3a allows it | The owner's decision 3 |

The default skip prefixes of `adoption.yaml` (`skip.keyPrefixes`):

| Prefix | Source |
|---|---|
| `openshift.io/sa.scc.` | The owner. OpenShift writes the UID and SELinux ranges |
| `kubectl.kubernetes.io/` | The owner. `kubectl.kubernetes.io/last-applied-configuration` is a client-side apply's copy of the whole object |
| `kubernetes.io/metadata.name` | Recommended. "The Kubernetes control plane sets an immutable label `kubernetes.io/metadata.name` on all namespaces" (Kubernetes, "Namespaces") |
| `pod-security.kubernetes.io/` | Recommended. On OpenShift a controller synchronises these labels, and a hand change stops the synchronisation for that label (OpenShift 4.22, "Understanding and managing pod security admission"). The CRC test confirms it (§5) |

The two recommended prefixes are configuration, not code: an organisation that wants them in Git removes them from
`adoption.yaml`.

**D3a. Who owns each key (Fable's A3).** A key left out of the file is not always left alone on the cluster:

- Server-side apply removes a field that a manifest leaves out only when no other manager owns it ("If the field is not
  owned by any other field managers, it is either deleted from the live object or reset to its default value",
  Kubernetes, "Server-Side Apply").
- Argo CD's client-side apply migration is on by default. On a server-side sync it moves "field ownership from the
  client-side apply manager to Argo CD's server-side apply manager" (Argo CD, "Sync Options", "Client-Side Apply
  Migration"). After that, Argo CD alone owns each field that a `kubectl apply` wrote, and the same sync removes each one
  that the file leaves out. A `pod-security.kubernetes.io/enforce` label that an old `kubectl apply` wrote would go, and
  the namespace's pod security would change.

So the plan reads `metadata.managedFields` (D2) and records the manager of each label and annotation:

- A key under a skip prefix is left out of the file only when its managers are server components (the API server,
  OpenShift's controllers) that Argo CD's migration does not take over. Then leaving it out changes nothing on the
  cluster.
- A key under a skip prefix that a client-side apply manager wrote stays in the file as it is, with a finding
  `skipped-key-kept` that names the manager, because leaving it out would remove it from the cluster on the first sync.
- cmapi's Applications set the migration as the measurement on kind decides (§5): on, with the rule above, or off, with
  the old manager co-owning each key it wrote. Either way, the plan says for each key whether a later removal from Git
  removes it from the cluster ("removed from Git; stays on the cluster" when another manager still owns it).

### D4. What cmapi adds, and the only differences on the live object

On the Namespace, the keys that cmapi's renderer writes on each namespace it manages (`core/render/manifests.py`): the
labels `cmapi.net/managed: "true"`, `cmapi.net/cluster-id`, `cmapi.net/env` (the environment of the cluster in the
registry, as `core/pipeline.py` takes it; a `company.net/app-environment` that names another one is a finding
`environment-mismatch`), `cmapi.net/tier: custom`, `cmapi.net/requested-by-user` (who asked for the adoption), and the
annotations `cmapi.net/instance`, `cmapi.net/request-id`, `cmapi.net/requested-by` (that person's address) and
`argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true`. A namespace that already has that annotation with
another value gets a finding `sync-options-replaced`, and cmapi's value is written, because `Prune=confirm` is the guard
of D11. `cmapi.net/adopt` stays (§1, item 6).

On each ResourceQuota and LimitRange: the labels `cmapi.net/managed`, `cmapi.net/cluster-id` and `cmapi.net/tier: custom`,
and the annotations `cmapi.net/instance`, `cmapi.net/request-id` and `argocd.argoproj.io/sync-options: Prune=confirm`
(Fable's A2: nothing that existed before the adoption is removed without an operator's confirmation). Not
`cmapi.net/tier-hash`, because an adopted object is not a rendering of a tier, and not `cmapi.net/beyond-tier`: the
adoption request's plan records the keys beyond the custom bounds instead (D5), so that an adopted object gains no
annotation that reads as an approval it never had.

No new object: the renderer's `cmapi-token-issuer` RoleBinding is not part of an adoption. The first update of the
namespace through cmapi adds it, and that plan shows it.

Argo CD's annotation tracking adds `argocd.argoproj.io/tracking-id` to each object it applies. So the full list of live
differences after the first sync is: the keys above, the tracking annotation, and the change of field managers that D3a
names. "No change to the live object" in the test plan means: no other difference, which the worker checks (D11).

### D5. Tier custom, values as they are

The namespace gets tier `custom`. Each ResourceQuota and LimitRange is written as it is, whatever its keys, scopes or
number of objects. cmapi does not map it to the nearest named tier (the owner's decision 3 replaces docs/02's "Mapped to
the nearest tier"). Each value outside the custom tier's bounds for the environment (`tiers.yaml`) is a finding
`beyond-custom-bounds`, with the key, the value and the bound, and the request's facts carry `beyondTier` and
`beyondTierKeys` as a request of #211 does. Nothing is changed. A later change through cmapi is checked and approved as
usual (the owner's rule: approval is the gate).

### D6. Labels and annotations: every key as it is, each difference a finding

Every label and annotation that D3 does not drop goes to Git as it is, also when it breaks a rule. cmapi checks the
Namespace's keys against the instance's `metadata-keys.yaml` (#215) and reports, never changes:

| Finding | Example on the owner's sample |
|---|---|
| `derived-mismatch`: a `value.from` key whose value is not the derived one | the test namespace with the deliberate mismatch, `name: aao-rnd` on `abc-rnd` (§5); the sample's own was a typo (§1, item 5) |
| `missing-required-key` | none on the sample with the company configuration; `cmapi.net/team` with the shipped one |
| `invalid-value`: breaks its `pattern`, `enum`, `format` or `namespacePrefix` | none on the sample |
| `declared-as-annotation`: a label whose key the stanzas declare as an annotation | `company.net/mnemonic-group-contact` and `company.net/mnemonic-confluence` (§1, item 9) |
| `empty-value`: a declared key with an empty value | none on the sample |
| `unknown-key`: a key that no stanza declares and `allowOther` does not admit | none with the company configuration; each `company.net/` key with the shipped one |
| `adoption-label` | `company.net/provisioner: cluster-configs` (recognised, kept: D7) |
| `skipped-key`, `skipped-key-kept` | D3a |
| `policy-ratcheted` | each failure of a rendered policy that D6a holds, with the policy's name |

**One rule for a value that the namespace already has** (the owner's decision 7, Fable's A6). A key that the last version
of the namespace already had wrong, or lacked, is not checked again while it does not change, in Python, in CI and at
admission alike:

- **cmapi's own check:** `core/metadata.py` does not refuse a missing required key that the current version also lacks,
  nor a value that it already holds.
- **The rendered policies (#212):** they hold a key whose value equals the old one, and a key that is absent in both
  (`policygen.py`).

Each plan lists such a key as a finding until a request fixes it. A request that touches the key must give a valid
value. A missing required key therefore never blocks the adoption or a later, unrelated request. The derived `name`
label stays as it is until a request sets it, and the plan of that request shows the change. This replaces docs/02's "A
missing required governed key blocks adoption" and the earlier "the first update must add it".

**A namespace with no team.** With the shipped configuration a namespace can be adopted without `cmapi.net/team`, which
the approval rules and the daily allowance read. A later request of such a namespace is approved by `approver-platform`,
and no automatic approval covers it, until a request sets the team.

**A label that is now an annotation** (§1, item 9). It stays in Git as a label, and each plan reports it. Setting the
annotation does not remove the label: a request removes it with `null`.

### D6a. The rendered policies and an adoption (#248, Fable's A1)

The Kyverno bundle of #212 (PR #245) does not refuse a value that Git already holds. At plan time and in the PR check, a
failure on a key whose value the previous version of the object holds is dropped. An adoption has no previous version in
Git, so in `enforce` its plan and its PR check would refuse each value that D6 keeps and reports.

**At plan time and in the PR check, the base is the approved plan's snapshot.** It is never taken from the PR.
1. The adoption plan gives the validator, as `previous`, the three kinds of objects as it read them from the cluster,
   after D3. It stores that snapshot in the request's plan, which the plan hash covers.
2. The PR check finds the snapshot by the request ID and checks it against the plan's hash. It never reads `previous`
   from a file of the pull request.
3. So the check drops only the failures that the approvers saw. Each failure that it drops stays in the plan as a finding
   `policy-ratcheted`, with the policy's name.
4. After the merge, Git holds the base, and a later request is checked as any other.

**At admission,** the first sync is an UPDATE of each object. The policies do not check a key whose value equals
`oldObject`'s, or that is absent in both. So the adopted differences pass while the live object still equals the snapshot,
which D16 keeps true. The keys that cmapi adds are new, so they are checked, and cmapi writes them valid. If an adopted
ResourceQuota or LimitRange was deleted after the read, Argo CD would create it with no `oldObject`. The policy then
checks every key, and the request fails. D16 refuses this case earlier.

**Not measured:** the ratchet at admission (#245 records it). The kind test runs with the environment in `enforce` (§5).

### D7. `company.net/provisioner`, and every key that cmapi does not own

**It stays as it is** (the owner's question b, and §1, item 8). It is a label value, nothing more. Removing it or
rewriting it would change the live object. cmapi records the adoption in what it already writes: the change request
(`plugin: adoption`), its `cmapi.net/request-id` annotation on the namespace, and the Git history of the folder.

One rule holds for the namespace's whole life, which the build must add (B2): **cmapi keeps each key in Git that it does
not own.** Today the renderer builds a namespace's labels from the requester's keys and its own system keys, so on the
first update it would drop `company.net/provisioner` and each other key that the instance's stanzas do not declare. After
the change:
- A key in Git that is neither a system key nor settable by the requester is carried over unchanged on each update.
- The requester may remove it with a merge patch `null`, a removal that is checked and approved as usual, but may not
  set it. The plan says whether the removal reaches the cluster (D3a).
- A key under a prefix that #215 reserves, such as `openshift.io/node-selector`,
  `scheduler.alpha.kubernetes.io/defaultTolerations` or `argocd.argoproj.io/managed-by`, is removed only by an operator.
  It was there before the adoption, and self-heal now keeps it, so nothing is gained or lost at adoption. The adoption's
  plan lists every kept key with its manager, also when `allowOther` admits it and it is no finding.

### D8. The repository and the folder

The folder is `clusters/<cluster>/namespaces/<namespace>/` in `cmapi-cluster-configs`, with `namespace.yaml` and **one
file for each ResourceQuota and each LimitRange, named after the object**: `resourcequota-<name>.yaml` and
`limitrange-<name>.yaml` (#251). One object in one file means that no reader needs to take several documents, which
closes #250, and that a request names the object it changes by its file. The same layout serves cmapi's own tier
namespaces (D19). A folder written before this layout (`resourcequota.yaml`, `limitrange.yaml`) is still read, as a stream of
documents, and the next change of that namespace writes the named files instead. Argo CD sees the same objects, by kind
and name, so moving an object from one file to another changes nothing on the cluster.

The YAML writer keeps each string a string: `'1'`, `''` and `"true"` stay quoted, because the API server refuses
`company.net/cl: 1`. The quantities are what the API server returned, so Argo CD sees no difference after the takeover
(Fable's A9).

### D9. A later change of an adopted quota or LimitRange

An adopted object stays raw until a request changes it. A request names the object by its kind and name
(`resourceQuotas: {<name>: {hard: {...}}}`, `limitRanges: {<name>: {...}}`), and cmapi changes that object in place: it sets
the keys that the request names and keeps each other field (scopes, `scopeSelector`, other item types, other keys). When
the namespace has exactly one object of the kind, the name may be left out, as today. With several and no name, the plan
refuses it with a problem that names the objects. A request can also add an object or remove one by name, each shown in
the plan. Any other request, a change of a label for example, leaves every object unchanged.

The namespace stays on tier `custom`. It moves to a named tier only when a request asks for it, never automatically:
that request replaces the adopted objects with the tier's (D19's names), and its plan shows each object and field that
goes.

### D17. The data model of adopted quotas and LimitRanges (#251)

**What is held.** cmapi does not predict the shape of an adopted object. Each ResourceQuota and LimitRange is kept as the
raw YAML that the API server returned, minus D3, under its own name, with any content that Kubernetes allows. That
includes `hard` with any resource name (extended resources, `count/<resource>.<group>` object counts), `scopes`,
`scopeSelector` ("A quota will only measure usage for a resource if it matches the intersection of enumerated scopes",
Kubernetes, "Resource Quotas"), and LimitRange items of each `type` with `min`, `max`, `default`, `defaultRequest` and
`maxLimitRequestRatio`. cmapi checks only that each is a valid Kubernetes object (kubeconform), and the rendered policies
check the keys they know (#212).

**Where it is held.** Git holds the objects (D8). The database holds no copy of them: the request's plan stores the files
and the snapshot (D6a), and the API's quota views read the live objects from each cluster's watch cache, as they do today
(`plugins/quotas`). So nothing in `docs/16-data-model.md`'s tables changes for the objects themselves. What changes is the
shape that the API returns for a namespace:

```json
{
  "resourceQuotas": [
    {"name": "abc-rnd-quota", "scopes": [], "hard": {"requests.cpu": "40", "count/deployments.apps": "20"},
     "used": {"requests.cpu": "12"}, "raw": "<the object as YAML>"}
  ],
  "limitRanges": [{"name": "abc-rnd-limits-cpu", "raw": "<the object as YAML>"}],
  "derived": {"cpu": ["12", "40"], "memory": [null, null], "pods": [null, null]},
  "uninterpreted": ["count/deployments.apps"]
}
```

**The derived numbers** that capacity, the quota view and the KPIs use come from the objects by one rule:
- Every ResourceQuota is enforced on its own: a request that "violates a quota constraint" is refused with 403
  (Kubernetes, "Resource Quotas"). So the hard limit of a key for the whole namespace is the **smallest** `hard` value of
  that key among the quotas that have **no scope and no scopeSelector**, not their sum. `used` comes from the same quota.
- A quota with a scope measures only the matching objects, so it is shown, and it is not counted in the namespace's
  numbers.
- A key that cmapi does not interpret (an extended resource, an object count, any name that is not `requests.cpu`,
  `requests.memory`, `pods`, `persistentvolumeclaims`, `requests.storage`, `services.loadbalancers` or
  `services.nodeports`) is kept and shown raw. It is excluded from the maths and listed in `uninterpreted`, and the
  adoption plan reports it as a finding `uninterpreted-key`.

The quota view's `cpu`, `memory` and `pods` columns, and the capacity reservation of a later request, use `derived`. The
data model doc (docs/16) gets a section on this view when it is built.

### D18. Keep or remove `company.net/provisioner` after the adoption (#251)

The label stays at the adoption (D7). Later, an approved request can remove it from Git and from the live namespace. The
request is an ordinary metadata change with `null` for the key, for one namespace, or many through #252's bulk
operation. The same mechanism serves any adopted label that is to go later.

**Why the removal reaches the cluster.** Under server-side apply, a field that a manifest leaves out is removed only when
no other manager owns it (D3a). The label is in the adopted file (D7), so the first sync makes Argo CD's server-side apply
manager an owner of it. Whether it is the **only** owner depends on who wrote it:
- If a client-side `kubectl apply` wrote it, Argo CD's client-side apply migration, on by default, moves that ownership
  to Argo CD's manager on the first sync (D3a). Argo CD is then the only owner, and the removal from Git removes it from
  the cluster.
- If another manager wrote it (`oc label`, a controller), that manager keeps a share, because an apply of the same value
  is shared ownership, not a conflict. The removal from Git would then leave it on the cluster. So the adoption plan
  records the label's managers (D2), and the removal plan says which case holds. When another manager co-owns the label,
  the removal request takes two commits:
  1. The first sets the label to another value (`cmapi-removing`). Argo CD's forced apply (`--force-conflicts`) then
     takes it, because a forced apply "removes the field from all other managers' entries" (Kubernetes, "Server-Side
     Apply").
  2. After that sync, the second commit leaves it out, and Argo CD, now the only owner, removes it.

  The adoption itself never changes the label (D4).

**Proof** (when #157 allows): on kind, adopt a namespace made with `kubectl apply` and one labelled with `oc label`. Read
`--show-managed-fields` after the first sync. Then remove the label by a request, and show that it is gone from the live
object in both cases.

### D19. cmapi's own LimitRanges: one for CPU, one for memory, none for storage (the owner's decisions on #251)

**What Kubernetes does with several LimitRanges.**
- Each is enforced: usage must "not exceed resource minimum, maximum and ratio defined in any LimitRange present in the
  namespace" (Kubernetes, "Limit Ranges").
- Their defaults are not merged: "If two or more LimitRange objects exist in the namespace, it is not deterministic which
  default value will be applied" (the same page).

So several LimitRanges are safe only when no two set a default for the same resource of the same type.

**The rendering.** cmapi renders a tier's limits as two LimitRange objects, each owning one resource name, so no two set
the same default:

| Object | Holds |
|---|---|
| `<ns>-limits-cpu` | the `Container` item's `min`, `max`, `default`, `defaultRequest` (and `maxLimitRequestRatio`, if set) of `cpu` |
| `<ns>-limits-memory` | the same for `memory` |

**No LimitRange for storage** (the owner: "We don't enforce limit ranges for storage"). The `PersistentVolumeClaim` item
and its key `limitRange.pvc.max.storage` leave the tiers' values, `tiers.yaml`'s `overridable` list and `custom` bounds,
#211's custom limits (merged in #224, so the D19 pull request removes the key there and records it), and #212's generated
policies. Storage is governed only by the ResourceQuota keys `requests.storage` and `persistentvolumeclaims`.

The container keys of `tiers.yaml` stay as they are (`limitRange.container.max.cpu`, ...), so the approval facts and the
bounds of CPU and memory do not change. Only the renderer maps each key to its object. What follows the split:
- the tier hash, which covers the rendered objects;
- the plan diff and the dry run, which show each object;
- the quota view, which lists each LimitRange;
- #212's generated policies, which check each object's keys, with the order checks inside the CPU and memory objects.

**No migration.** Nothing of cmapi runs on a cluster yet (#157), so the old single `<ns>-limits` object needs no live
migration. The examples, tests, docs and recorded samples change.

**Where it is built:** its own pull request, after this design is approved and after #245 (the generated policies)
merges, because it changes `core/tiers.py`, `core/render/manifests.py` and `core/policygen.py` together. Adoption is
unchanged by it: adopted LimitRanges stay raw, any number, under their own names, a storage LimitRange too.

### D10. Who may ask, and the approval

- **Who:** a person with `adoption:write` (cmapi-operator), or the namespace's admin on that cluster, checked with a
  SubjectAccessReview (docs/02, kept). The read ClusterRole gets `create` on `subjectaccessreviews`.
- **One request for each namespace**, plugin `adoption`, action `adopt`, with the findings in its plan.
- **Facts** for `approval-rules.yaml`: `environment`, `findings` (the count by code), `beyondTier`, `beyondTierKeys`,
  `trackedElsewhere` (always false for a request that exists: D1 skips those).
- **Default rules** in the shipped `approval-rules.yaml`: one approver of `approver-platform` in each environment, and one
  more when the plan has findings. Auto-approval never covers an adoption unless a rule names it. This replaces docs/02's
  earlier rule, in which one namespace admin approved in rnd and qa. The new rule is stricter, and the pull request names
  the change.

### D11. The sync and the check after it

1. The bot opens the pull request with the folder. CI runs the policies on it with the snapshot as the base (D6a).
2. On the merge, the cluster's root Application applies the folder. cmapi's Applications use:
   - `ServerSideApply=true`. Argo CD then "applies with `kubectl apply --server-side --force-conflicts`" ("Sync Options"),
     so field ownership is explicit (D3a).
   - `FailOnSharedResource=true`, so that a namespace that another Application owns fails the sync instead of being taken.
     D1 skips such a namespace first; this is the second layer.
3. The worker reads the live objects after `Synced` and `Healthy`, and compares each with the plan's snapshot, its
   `managedFields` included. Only D4's differences and D3a's change of managers are allowed. Any other difference fails
   the request with a finding that names the field.
4. **A failed adoption is never reverted** (Fable's A2). A request of plugin `adoption` in `sync_failed` does not take
   `:revert` (409 `invalid-transition`). A revert would remove the folder, and Argo CD would then prune objects that
   cmapi did not create. Each adopted object carries `Prune=confirm` (D4), so nothing is removed without an operator's
   confirmation in any case ("Resources such as Namespaces are critical and should not be pruned without confirmation",
   Argo CD, "Sync Options"). The operator's way out is `:retry` after the cause is removed. The page that confirms a
   prune names an adopted namespace as "existed before cmapi", and the build proves on kind the steps that take a folder
   out of Git and leave the live objects, before any operator needs them.
5. **The diff before the merge** (Fable's A9). #217 is open and not measured. Until it delivers, the pull request's
   check shows cmapi's own diff of the files against the snapshot, and the worker's check after the sync (step 3) is the
   proof. With #217, the check shows Argo CD's server-side diff of the root Application at the pull request's revision
   (`argocd app diff`, with the read right that #217 grants).

### D12. (Withdrawn)

The earlier D12 described steps about another tool's repository. The owner's decision (§1, item 8) removes it:
adoption reads only the live namespace, and `company.net/provisioner` is a label value that `adoptionLabels` recognises.

### D13. The endpoints (docs/02's set, kept)

- `GET /api/v1/clusters/{cluster}/adoption/candidates`: labelled, not excluded, not managed, not tracked elsewhere; each with
  "recognised" when an adoption label matches.
- `GET .../adoption/skipped`: labelled but skipped, with the rule (exclusion, managed, tracked by another Application).
- `POST .../namespaces/{ns}:adopt`, with `?dryRun=true`: the plan, its findings and the files.
- `POST .../adoption:scan`: a plan for each candidate; `dryRun` is true unless the caller sets it false. A namespace that
  is open in another request, or managed, is listed as skipped, and the scan goes on.
- `GET /api/v1/reports/unmanaged-namespaces`: managed, candidates, recognised, unlabelled, excluded, for each cluster.
  Unlabelled namespaces are reported, never adopted.

### D14. When it is built

Wave 8, as planned. It needs: #215 (the stanzas the findings use; PR #234), #212 (the rendered policies; PR #245), #217
(Argo CD's server-side diff), Argo CD on CRC (Wave 5), and #157's decision for the kind and CRC tests. Nothing in this
design moves earlier work.

### D16. What can go wrong between the read and the sync (Fable's A4)

The worker's check after the sync (D11) cannot see a change made between the read and the sync, because the sync writes
the snapshot's values back. So the plan stores each object's `uid` and `resourceVersion`, and cmapi reads again before
each step:

| Case | What cmapi does |
|---|---|
| An object changed after the read | cmapi reads again when the request is approved, when the bot opens the pull request, and in the pull request's check. A difference fails the request with `adoption-plan-stale`, and the operator plans again. cmapi never writes the old values over the new ones. The time between the last read and the sync is not covered: the runbook says so, and the check is a required one, so that the merge follows it at once |
| The namespace was deleted and made again | Its `uid` differs: the same refusal |
| The namespace is `Terminating` | Not a candidate (D1) |
| A second adoption of the same namespace | The open-request lock refuses it with 409 (`uq_cr_open_namespace`, docs/02). After the merge the folder exists, and after the sync the namespace is managed: D1 step 2 skips it |
| `cmapi.net/adopt` removed before the merge | The same reads see it. The request is cancelled with `adoption-label-removed`, and the bot closes the pull request: the label is the consent. After the merge the label has no effect (§1, item 6) |
| No ResourceQuota, or no LimitRange | No file for that kind, and a finding `no-resourcequota` or `no-limitrange`. A later quota request adds the object, and its plan shows it as added |
| More than one ResourceQuota or LimitRange | Each is written, one document each (D8); D9's rules apply |
| An object deleted after the read, before the sync | The reads above refuse the request first; in `enforce` admission also refuses the create (D6a) |

## 4. What the build must add (each with a test that fails before it)

| # | What | Test |
|---|---|---|
| B1 | The adoption plugin: D1 to D5, D8, D10, D13, D16 | The plan of the owner's sample: the files equal the live objects minus D3 plus D4; the findings of D6; `'1'`, `''` and `"true"` stay strings |
| B2 | The renderer keeps keys in Git that it does not own (D7); a merge patch may remove them | An update of an adopted namespace keeps `company.net/provisioner`; a `null` removes it; setting it is refused |
| B3 | A change of an adopted quota or LimitRange patches the named object in place (D9) | An adopted ResourceQuota with `scopes` keeps them after a quota change; with two ResourceQuotas, a request that names one changes only it, and one with no name is refused with a problem; an update of a label leaves both unchanged |
| B10 | One file for each object, named after it, and the reader of the earlier layout (D8; closes #250) | A folder with two ResourceQuotas: an update of a label passes; the next change writes `resourcequota-<name>.yaml` files; Argo CD's diff of the rename is empty (kind) |
| B11 | The derived numbers and `uninterpreted` (D17) | Two unscoped quotas give the smaller `requests.cpu`; a scoped quota is listed and not counted; `count/deployments.apps` is in `uninterpreted` and in the findings |
| B12 | The removal of an adopted label from the cluster (D18) | On kind, for a label written by `kubectl apply` and one written by `oc label`: removed by a request, gone from the live object |
| B4 | The worker's check after the sync, `managedFields` included (D11) | A live object with one more changed field fails the request with that field named |
| B5 | `adoption.yaml` with the skip prefixes of D3, and D3a's rule on managers | A key under each prefix that a server component owns is skipped; one that `kubectl apply` wrote is kept with `skipped-key-kept` |
| B6 | `FailOnSharedResource=true` on cmapi's Applications (Wave 5's ApplicationSet) | A namespace in another Application fails the sync (kind) |
| B7 | The adoption plan's base for the rendered policies (D6a, #248) | The test namespace with `name: aao-rnd` passes the plan and the PR check in `enforce`, with `policy-ratcheted`; a PR whose head carries another base is not believed; a changed value is refused |
| B8 | No revert of a failed adoption (D11) | A failed adoption, then `:revert`: 409; the three live objects are unchanged |
| B9 | One rule for a value the namespace already has (D6) | An update of an adopted namespace that lacks `company.net/lob` and changes only the quota passes, with the finding listed; a request that sets `company.net/lob` to an invalid value is refused |

**A bug that this design found, filed apart:** `core/pipeline.py` reads `resourcequota.yaml` with `yaml.safe_load`, which
raises `ComposerError: expected a single document in the stream` on a file with two documents. A folder with two
ResourceQuotas then answers 500 on every update (Fable's A4). It is #250 (BUG-61). B10's named files close it, and its
test fails before the fix.

## 5. The test plan (the owner's, made concrete)

Test namespaces only, made for the test with `oc apply` of a plain YAML file and labelled with `oc label`, exactly in the
owner's shape. Never inkcast, corp, group-sync or another project's namespace. On kind first, then on CRC; both wait on
#157. The test refuses to run when a namespace of its names exists already, and it records each `uid` it made, so the
cleanup removes only those.

Two namespaces. `abc-rnd` carries the deliberate mismatch `name: aao-rnd`. `abd-rnd` carries the right `name: abd-rnd`.
Both carry the two contact keys as empty labels:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: abc-rnd
  labels:
    name: aao-rnd                      # the deliberate mismatch (abd-rnd has its own name)
    company.net/app-environment: rnd
    company.net/mnemonic: abc
    company.net/lob: amgsst
    company.net/cl: '1'
    company.net/provisioner: cluster-configs
    company.net/mnemonic-group-contact: ''
    company.net/mnemonic-confluence: ''
    cmapi.net/adopt: "true"
  annotations:
    company.net/app-environment: rnd
```

Each has one ResourceQuota (a value above the custom bound for `rnd`, and a `scopes` list) and one LimitRange (a `Pod`
item that cmapi does not model). The instance uses `metadata-keys.company.yaml`, and the environment runs in `enforce`.
The before-and-after comparison uses `oc get -o yaml --show-managed-fields`.

| Case | Expected |
|---|---|
| Plan (`dryRun`) | Files: the three objects minus D3, plus D4. Findings: `derived-mismatch` (`name`, on `abc-rnd` only), two `declared-as-annotation`, `adoption-label`, `beyond-custom-bounds` (the quota key), and `policy-ratcheted` for each held failure. No change on the cluster |
| `abd-rnd`'s plan | No `derived-mismatch` |
| The same namespace without `cmapi.net/adopt` | Not a candidate; in the report as "recognised, unlabelled" |
| A namespace in another Argo CD Application | Skipped, with the Application named |
| Approve, merge, sync, in `enforce` | The first sync is admitted. The live objects differ from the snapshot only by D4 and D3a. `cmapi.net/adopt` is still there. The managers before and after are recorded, with each key that the sync removed (none expected) |
| A sync that also changes a wrong value | Refused at admission in `enforce` |
| A quota changed after the plan | `adoption-plan-stale`; the live value is not written over |
| `cmapi.net/adopt` removed after the approval | The request is cancelled; the pull request is closed |
| A second `:adopt` while the first is open | 409 |
| No ResourceQuota; two ResourceQuotas, one with a scope and one with `count/deployments.apps` | The findings, with `uninterpreted-key`; one file for each object; the derived CPU comes from the unscoped quota; an update of a label passes |
| A LimitRange for CPU and another for memory | Both adopted under their names, unchanged |
| Remove `company.net/provisioner` by a request after the adoption | Gone from Git and from the live namespace (D18) |
| A failed adoption, then `:revert` | 409; the three live objects are unchanged |
| An update after the adoption (set the annotation `company.net/mnemonic-group-contact`) | The annotation is set; the label of the same key stays until a request removes it with `null`; `name` stays `aao-rnd` (D6); `company.net/provisioner` stays; the quota's `scopes` stay |
| A missing required key (remove `company.net/lob` before the plan) | Adopted, with `missing-required-key`; a later quota change passes with the finding listed (D6) |
| A key changed by hand on the cluster after the adoption | Reverted by Argo CD's self-heal if the key is in Git (docs/02, "On the cluster") |
| On CRC: a namespace whose `pod-security.kubernetes.io/` labels OpenShift's controller wrote | Skipped as D3 says, and unchanged on the cluster after the sync |
| Cleanup | The test removes only the namespaces (by `uid`) and the folders it made |

## 6. Sources, each read on 2026-11-14

- Argo CD, "Sync Options" (`FailOnSharedResource`, `ServerSideApply`, Client-Side Apply Migration, `Prune=confirm`):
  <https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/>.
- Argo CD, "Resource Tracking" (annotation tracking is the default; `argocd.argoproj.io/tracking-id`):
  <https://argo-cd.readthedocs.io/en/stable/user-guide/resource_tracking/>.
- Kubernetes, "Server-Side Apply" (a field left out of a manifest; shared ownership):
  <https://kubernetes.io/docs/reference/using-api/server-side-apply/>.
- Kubernetes, "Namespaces", automatic labelling: <https://kubernetes.io/docs/concepts/overview/working-with-objects/namespaces/>.
- OpenShift Container Platform 4.22, "Understanding and managing pod security admission":
  <https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/authentication_and_authorization/understanding-and-managing-pod-security-admission>.
- cmapi: docs/02 "Adoption plugin", `core/metadata.py` (#215, PR #234), `core/render/manifests.py`, `core/pipeline.py`,
  `core/policygen.py` (#212, PR #245), `routers/requests.py`, docs/reviews/2026-11-14-issue-211/.
- Fable's review: `fable-review.md` in this folder.

## 7. For the reviewer

The choices that most need a second reader:
- D3a: who owns each key, and the migration, which kind decides.
- D6: one rule for a value the namespace already has.
- D6a: the base for the policies.
- D11 step 4: no revert of an adoption.
- D16: the reads before each step.
- D17: the data model of free-form quotas and LimitRanges, and the derived numbers (the smallest unscoped `hard`).
- D18: removing an adopted label from the cluster under server-side apply.
- D19: cmapi's own LimitRanges, one object for CPU and one for memory, and none for storage.
