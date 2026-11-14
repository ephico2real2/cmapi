# Fable's review of PR #239: the adoption design (story #26)

Reviewer: Fable 5.2, 2026-11-14. Head `3e121a1`. Read in full: `docs/reviews/2026-11-14-issue-26-adoption/README.md`
(289 lines), the PR's diff of `docs/02`, #26 with its six comments, #215's comment of 14:25Z, #217, PR #245's body and
`cmapi/src/cmapi/core/policygen.py` and `core/pipeline.py` at #245's head `584e183`.

**Verdict: changes requested before the merge.** The fourteen decisions follow the owner's rules, and none contradicts
them. Five things are missing or not correct as written (A1 to A5), and each can change a live namespace or stop an
adoption. A6 to A10 are smaller.

Nothing here was measured on a cluster (no kind, no CRC: #157). Each statement about Argo CD, Kubernetes and OpenShift
comes from the documentation cited, read today. Each statement about cmapi comes from the file and line cited.

## What was checked against the owner's rules

| Rule (#26) | In the design | Result |
|---|---|---|
| Opt-in by `cmapi.net/adopt` | D1 step 4; `adoptionLabels` never selects | Holds |
| Reads each namespace live from the cluster | D2 | Holds |
| Namespace, ResourceQuota, LimitRange as raw YAML, tier `custom`, never mapped | D3, D5, D8 | Holds |
| Drops only server-set fields and the skip prefixes | D3 | Holds for what goes to Git. It adds two prefixes to the owner's two, as configuration, with sources. What happens to a dropped key on the live object is not designed: A3 |
| Every difference from #215 is a finding, never changed | D6 | Holds at adoption. The first update changes `name` and must add missing keys: A6 |
| `cmapi-cluster-configs`; the old `cluster-configs` never touched | D2, D8, D12 | Holds for cmapi. D12's runbook step tells a person to change the old repository: A7 |
| The owner's sample (#26, 07:57Z) | §1.5, §5 | Written before the 14:28Z correction: A5 |
| The two contact keys move to annotations (#215, 14:25Z) | Not in the design | Written before the decision: A5 |

## Findings

### A1 (high). The design does not say how an adoption passes the policies in enforce mode

**What the design says.** D11 step 1: "Git CI runs the policies on it like any other folder (the instance's mode:
#213)". D5 and D6 say that a value beyond the bounds and a missing required key are adopted. The words `oldObject`,
"ratchet" and "enforce" are not in the design.

**Why that is not enough.** PR #245 (head `584e183`) renders the policies with a ratchet:

- At admission, a key is not checked when it "is unchanged from oldObject on an UPDATE: present with the same value, or
  absent in both" (`policygen.py:99`); a quota key the same way (`quantity(...).compareTo(...) == 0`, line 192). The
  policies match when `cmapi.net/managed` is `true` on the object or on `oldObject` (lines 243 to 244).
- At plan time and in the PR check, the validator gets `previous=prev_files`, the folder in Git
  (`pipeline.py:263`), and "the CLI evaluates as CREATE with an empty oldObject ... so offline every key is checked"
  (`policygen.py:82`).

An adoption has no folder in Git, so `prev_files` is empty. In enforce mode every adopted difference fails at plan
time, and the plan is refused. D5 and D6 then cannot happen.

**Design text to add** (a new decision, "D15. The policies, in each mode"):

> **At plan time and in the pull request's check.** An adoption has no earlier version in Git. The adoption plugin
> gives the validator, as `previous`, the three kinds of objects as it read them from the cluster, after D3. In the pull
> request's check, `previous` is the snapshot stored in the approved request's plan, found by the request ID and checked
> against the plan's hash. It is never a file of the pull request. So the check drops only the failures that the approvers
> saw. Each failure that the ratchet drops stays in the plan as a finding `policy-ratcheted`, with the policy's name.
> After the merge, Git holds the base, and a later request is checked as any other.
>
> **At admission.** The first sync is an UPDATE of each object. #245's policies do not check a key whose value equals
> `oldObject`'s, or that is absent in both. So the adopted differences pass while the live object still equals the
> snapshot (D16 keeps that true). The keys that cmapi adds are new, so they are checked, and cmapi writes them valid. If
> an adopted ResourceQuota or LimitRange was deleted after the read, Argo CD creates it, there is no `oldObject`, and the
> policy checks every key: the sync fails and the request fails. This is the wanted result.
>
> **Not measured.** #245 records that the ratchet at admission is not measured. The kind test must run with the
> environment in enforce mode (§5).

**Is the ratchet correct for adoption?** Yes, on two conditions that the design must state. The base must be the
approved snapshot and not something the pull request carries. The live object must still equal the snapshot at the
sync (A4).

### A2 (high). A revert of a failed adoption prunes the quota and the LimitRange, and offers the namespace for deletion

**What the design says.** D11 step 3: after a failed check "the namespace stays as it is on the cluster: the Namespace's
`argocd.argoproj.io/sync-options` holds `Prune=confirm`, so a revert of the folder cannot prune it without an operator's
confirmation".

**Why that is not enough.**

- The root Application syncs with `prune: true` and `selfHeal: true`
  (`examples/cluster-configs/clusters/OCP_GF15/argocd/root-application.yaml:24-26`).
- A failed request goes to `sync_failed`, and `POST /requests/{id}:revert` "restores the folder as it was before the
  plan" (`cmapi/src/cmapi/routers/requests.py:201-207`). Before an adoption there was no folder. So the revert removes
  the folder.
- Only the Namespace carries `Prune=confirm` (D4). The adopted ResourceQuota and LimitRange are now tracked by Argo CD
  and carry no such option, so Argo CD prunes them at once. They existed before cmapi.
- The Namespace then waits for "Confirm Pruning". An operator who confirms deletes a namespace, and each workload in
  it, that cmapi never created.

**Design text to change** (D11 step 3, and D4):

> Each adopted ResourceQuota and LimitRange also carries `argocd.argoproj.io/sync-options: Prune=confirm`, so nothing
> that existed before the adoption is removed without an operator's confirmation. A request of plugin `adoption` in
> `sync_failed` does not take `:revert` (409 `invalid-transition`): a revert of an adoption would remove the folder, and
> Argo CD would then prune objects that cmapi did not create. The operator's ways out are `:retry` after the cause is
> removed, or the release runbook: [the steps that take the folder out of Git and leave the live objects, to be written
> and proven on kind]. The page that confirms a prune names an adopted namespace as "existed before cmapi".

Add a build item and a test: "a failed adoption, then `:revert`: 409; the three live objects are unchanged".

Source: Argo CD, "Sync Options": a resource-level `Prune` option "will always override a Prune sync policy defined in the
Application"; `Prune=confirm` holds the sync until someone confirms.

### A3 (high). Field ownership decides what the first sync removes, and the design does not cover it

**What the design says.** D4: cmapi "removes `cmapi.net/adopt`", and "the full list of live differences after the first
sync is: the keys above, the removed `cmapi.net/adopt`, and the tracking annotation". D3 drops the skip-prefix keys
from the file. D11 says `ServerSideApply=true` makes field ownership explicit. D7: a requester "may remove" a kept key
with `null`.

**Why that is not correct as written.**

1. *A key left out of the file is removed only when no other manager owns it.* "If you remove a field from a manifest
   and apply that manifest, Server-Side Apply checks if there are any other field managers that also own the field. If
   the field is not owned by any other field managers, it is either deleted from the live object or reset to its default
   value" (Kubernetes, "Server-Side Apply"). `cmapi.net/adopt` is set by a person with `oc label` or `oc apply`, each
   under its own manager name (to be read from `managedFields` on kind). Argo CD's manager never owned it. So leaving it out of the file does not remove it,
   and the test plan's "`cmapi.net/adopt` is gone" would fail.
2. *Argo CD's client-side apply migration is on by default.* On a server-side apply sync it transfers "field ownership
   from the client-side apply manager to Argo CD's server-side apply manager" and removes the old manager's entry (Argo
   CD, "Sync Options", "Client-Side Apply Migration"). The page gives an annotation to name another manager and does not
   name the default one; I take it to be kubectl's client-side apply manager, which the kind test must confirm. The test
   plan makes its namespaces with `oc apply`, and an old pipeline probably did too. After the transfer Argo CD alone owns
   each field that `oc apply` wrote. The same sync then removes each of those fields that the file leaves out: every
   skip-prefix key that the old YAML held. `kubectl.kubernetes.io/last-applied-configuration` is harmless. A
   `pod-security.kubernetes.io/enforce` label from the old YAML is not: its removal changes the namespace's pod
   security. D11's check finds this only after it happened.
3. *With the migration off,* the old manager keeps co-owning each key that the file holds. A later removal from Git
   (D7's `null`) then does not remove the key from the cluster, and docs/02's "Removing a key from Git removes it from
   the cluster" (line 1166) is not true for an adopted namespace.

**Design text to add** (to D3 and D4, and a build item B7 with kind tests):

> **Who owns each key.** The plan reads `metadata.managedFields` before it drops it, and records the manager of each
> label and annotation. A skip-prefix key is left out of the file only when its manager is not one that Argo CD's
> client-side apply migration takes over. A key that such a manager wrote stays in the file as it is, with a finding
> `skipped-key-kept`, because leaving it out would remove it from the cluster on the first sync.
>
> **`cmapi.net/adopt`.** [One of these, decided by the owner and proven on kind.] (a) The label stays on the namespace.
> It has no effect once `cmapi.net/managed` is there, because D1 checks "managed" before "opt-in". D4's list and the
> worker's check then say "kept". (b) cmapi removes it in two commits: the first sets it to another value, so that Argo
> CD's forced apply becomes its only owner; the second leaves it out.
>
> **The migration.** [On or off, decided and measured.] The kind test shows, for a namespace made with `oc apply` and one
> labelled with `oc label`: the managers before and after, each key that the first sync removed, and what a later `null`
> does on the cluster.

Decision 3 of the owner says cmapi "removes `cmapi.net/adopt`". Option (a) changes that, so the owner decides.
The worker's comparison (D11 step 3) should also compare `managedFields`, with the change of owner listed as allowed.

### A4 (high). The failure modes are not designed

The design has no section for them. D11 step 3 compares the live objects after the sync "with the snapshot that the
plan took". That check cannot see a change made between the read and the sync, because the sync writes the snapshot's
values back: afterwards live equals snapshot. A quota that an administrator raised in that time is lowered again, with
no finding.

**Design text to add** (a new decision, "D16. What can go wrong between the read and the sync"):

> | Case | What cmapi does |
> |---|---|
> | An object changed after the read | The plan stores each object's `uid` and `resourceVersion`. cmapi reads again when the request is approved, when the bot opens the pull request, and in the pull request's check. A difference fails the request with `adoption-plan-stale`, and the operator plans again. cmapi never writes the old values over the new ones. The time between the last read and the sync is not covered: the runbook says so, and the check is a required one, so that the merge follows it at once |
> | The namespace was deleted and made again | Its `uid` differs: the same refusal |
> | The namespace is `Terminating` | Not a candidate (D1) |
> | A second adoption of the same namespace | The open-request lock refuses it with 409 (`uq_cr_open_namespace`, docs/02). After the merge the folder exists, and after the sync the namespace is managed: D1 step 2 skips it. `adoption:scan` lists such a namespace as skipped and goes on |
> | `cmapi.net/adopt` removed before the merge | The same three reads see it. The request is cancelled with `adoption-label-removed`, and the bot closes the pull request: the label is the consent. After the merge the removal has no effect, and the runbook says so |
> | No ResourceQuota, or no LimitRange | No file for that kind, and a finding `no-resourcequota` or `no-limitrange`. A later quota request adds the object, and its plan shows it as added |
> | More than one ResourceQuota or LimitRange | Each is written, one document each (D8). Every reader of these files must take several documents |
> | An object deleted after the read, before the sync | Argo CD would create it again. The reads above refuse the request first; in enforce mode admission also refuses the create (D15) |

On "more than one": today `core/pipeline.py:394` reads `resourcequota.yaml` with `yaml.safe_load`, which raises
`ComposerError: expected a single document in the stream` on a file with two documents (run with the suite's PyYAML).
So after such an adoption every update of the namespace, also one that changes only a label, would answer 500. B3's
test covers only the refused quota change. Add to B3: "an update of a label on a namespace with two ResourceQuotas
passes, and both documents are unchanged".

### A5 (medium). Two owner decisions are later than the design

The design's commit is from 10:08Z. Later:

- #215, 14:25Z: `company.net/mnemonic-group-contact` and `company.net/mnemonic-confluence` "move to annotations ...
  Existing namespaces that carry them as labels keep those labels at adoption (raw as-is), each reported as a finding".
- #26, 14:28Z: "`name: aao-rnd` in the sample above was a typo ... Keep one test namespace with a deliberate mismatch,
  to prove the finding, and make the others correct."

**Design text to change.**

- §1 item 5, and docs/02's "(the owner's sample: `name: aao-rnd` on `abc-rnd`)": say that the mismatch was a typo, and
  that the rule stands for a real namespace with one.
- D6's table: a new row, `declared-as-annotation`: "a label whose key the stanzas declare as an annotation; kept as it
  is. On the sample: the two contact keys". Their `empty-value` row goes, because the label stanza that would call
  them empty no longer exists.
- D7: say what the first update does with such a label. It is not a key "that cmapi does not own" in the sense of D7,
  since a requester can set the same key as an annotation. Proposed: "the label stays until a request removes it with
  `null`; setting the annotation does not remove the label; the finding stays in each plan while the label is there".
- §5: at least two namespaces. One has the wrong `name` label, to prove `derived-mismatch`. The other has the right
  one. Both carry the two contact keys as empty labels. The row "An update after the adoption (set
  `company.net/mnemonic-group-contact`)" now sets the annotation, and its expected result says what happens to the
  label.

### A6 (medium). "A missing required key does not block adoption": safe at adoption, not settled for the next update

**At adoption: sound.** It follows "as-is" and "no change to the live object". The risk is held by the approval (D10
asks one more approver when there are findings). It needs A1, or enforce mode refuses the plan.

**For the next update: two rules disagree.** D6 says "the first change through cmapi must add the key
(`missing_required_key` refuses it otherwise)". #245's ratchet does not check a key that is "absent in both"
(`policygen.py:99`), in CI and at admission, and #245 says this "matches `TierCatalog._out_of_bounds`". So the Python
check would refuse what the policies pass. The owner's words are "Fixing it later is an ordinary update request, checked
and approved as usual". They do not say that an unrelated update must fix it.

D6's rule has a cost that the design does not name. An urgent quota change of an adopted namespace waits until someone
supplies, for example, `company.net/lob`. The same update also rewrites the `name` label (D7), which is a live change
that the requester did not ask for.

**Design text to change** (D6 and D7): state one rule for all three places (Python, CI, admission), and its reason.
Proposed, for the owner to decide: "A key that the last version in Git already had wrong, or lacked, is not checked
again while it does not change. Each plan lists it as a finding until a request fixes it. A request that touches the
key must give a valid value." With this rule the derived `name` label also stays until a request sets it, and D7's
exception goes.

A second gap: with the shipped configuration a namespace can be adopted without `cmapi.net/team`. `team` is a fact for
the approval rules and for the daily allowance (`core/pipeline.py`, `plan.facts.get("team")`). Say who approves a later
request of a namespace with no team (proposed: `approver-platform`), and that no automatic approval covers it.

### A7 (medium). `company.net/provisioner` kept as a key cmapi does not own: safe for cmapi, with one hazard in D12

**Keeping it: sound.** Removing it would change the live object. cmapi never selects by it (D1). After the adoption
"managed" is checked first, so the reports no longer show the namespace as "recognised".

**The hazard.** The label still tells the old tool that the namespace is its own. D12's runbook step is "remove the
namespace from the old repository before you approve". If the old pipeline deletes what leaves its repository, that
step deletes the namespace. cmapi cannot know how the old tool behaves.

**Design text to change** (D12):

> Before anything else, the operator finds out what the old tool does when a namespace leaves its repository, and turns
> off its deletion for that namespace. Then the adoption runs while the old tool still applies the same values: two
> writers of equal values do not fight. After the sync, the operator removes the namespace from the old repository. The
> finding `made-by-other-tool` carries these steps in this order.

**B2's rule** ("cmapi keeps each key in Git that it does not own ... a requester may remove one but not set it") is
sound in principle. Two additions:

- Removal from Git removes the key from the cluster only when Argo CD is its only owner (A3). The design must say
  which case holds, or the plan must say "removed from Git; stays on the cluster".
- A kept key can be a powerful one: `openshift.io/node-selector`, `scheduler.alpha.kubernetes.io/defaultTolerations`,
  `argocd.argoproj.io/managed-by`, `security.openshift.io/scc.podSecurityLabelSync`. After the adoption Git holds it and
  self-heal puts it back. It was there before, so nothing is gained at adoption. Proposed: a key under a prefix that
  #215 reserves is removed only by an operator, and the adoption's plan lists every kept key with its manager, also when
  `allowOther` admits it and it is no finding.

### A8 (low). D1 step 3 can skip a namespace that no Application tracks

`app.kubernetes.io/instance` is a recommended Kubernetes label that Helm and kustomize users set by hand. It is Argo
CD's tracking label only when the instance is configured for label tracking; the default is the annotation (Argo CD,
"Resource Tracking"). **Change:** "the `app.kubernetes.io/instance` label counts only when the hub's Argo CD uses label
tracking (`application.resourceTrackingMethod`); otherwise it is a finding, not a skip."

### A9 (low). D11 step 4 rests on #217, which is open and not measured

#217 says "Nothing of this is measured". At the time of the pull request the root Application does not hold the
folder yet, and cmapi's cluster client only reads. **Change:** say who makes the diff and with which right (for
example `argocd app diff` of the root Application at the pull request's revision, with server-side diff), and what is
shown if #217 does not deliver it: cmapi's own diff of the files against the snapshot before the merge, with the
worker's check after the sync as the proof.

One fact supports "no diff after the takeover" and belongs in D11: the files are what the API server returned, so
quantities are already in the form that the server gives back. A second one needs a test in B1: the YAML writer must
keep `'1'`, `''` and `"true"` as strings. A file with `company.net/cl: 1` is refused by the API server.

### A10 (low). The test plan

It keeps the owner's rules: test namespaces only, kind then CRC, opt-in, cleanup of its own objects. Add:

| Case | Expected |
|---|---|
| The environment in enforce mode (A1) | The plan passes with `policy-ratcheted` findings; the first sync is admitted; a sync that also changes a wrong value is refused |
| Made with `oc apply`, and labelled with `oc label` (A3) | The managers before and after; each key the sync removed; the state of `cmapi.net/adopt` |
| A quota changed after the plan (A4) | `adoption-plan-stale`; the live value is not written over |
| The label removed after the approval (A4) | The request is cancelled; the pull request is closed |
| A second `:adopt` while the first is open (A4) | 409 |
| No ResourceQuota; two ResourceQuotas (A4) | The findings; an update of a label passes with two |
| A failed adoption, then `:revert` (A2) | 409; the three live objects unchanged |
| The second namespace, with the right `name` label (A5) | No `derived-mismatch` |

Also: the test refuses to run when a namespace of its names exists already, and it records each `uid` it made, so the
cleanup removes only those. The before-and-after comparison uses `oc get -o yaml --show-managed-fields`. D3 asks this
review to confirm the `pod-security.kubernetes.io/` prefix on CRC: not done, because no cluster may be used (#157). It
stays a row of the CRC test.

## Smaller notes

- D4 adds `cmapi.net/env` and does not say from where. In the code the environment is the cluster's
  (`core/pipeline.py`, `env = st.policy.environment`). Say so, and add a finding when `company.net/app-environment`
  names another one.
- D4 sets `argocd.argoproj.io/sync-options` on the Namespace. Say what happens when the namespace already has that
  annotation with another value (proposed: a finding, and cmapi's value is written, because `Prune=confirm` is the
  guard).
- D10 changes docs/02's old rule (one namespace admin approves in rnd and qa) to one approver of `approver-platform`
  in each environment. It is stricter and fits the risk. Name the change in the pull request, since it replaces a
  written rule.
- The figure (`docs/diagrams/adoption/source.html`) and docs/02's short form repeat the design, so they change with it:
  box 4 ("name: aao-rnd is not the namespace name; two empty values") with A5, box 8 ("the removed adopt label") with
  A3, and a step for the reads of D16.
- The section "What the build must add" is B1 to B6, six build items. The brief calls them boundaries; they are not.

## Sources, each read on 2026-11-14

- Kubernetes, "Server-Side Apply": <https://kubernetes.io/docs/reference/using-api/server-side-apply/> (a field left
  out of a manifest; shared ownership; a forced apply "removes the field from all other managers' entries").
- Argo CD, "Sync Options": <https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/> (Client-Side Apply
  Migration, on by default; `Prune=false`; `Prune=confirm`; `FailOnSharedResource`; server-side apply with
  `--force-conflicts`).
- #26 and its comments; #215's comment of 2026-11-14T14:25:31Z; #217; PR #245's body.
- cmapi at #245's head `584e183`: `core/policygen.py:82, 99, 192, 243-244`; `core/pipeline.py:258, 263`.
- cmapi at `3e121a1`: `core/pipeline.py:189, 394`; `routers/requests.py:201-216`;
  `examples/cluster-configs/clusters/OCP_GF15/argocd/root-application.yaml:24-26`; `docs/02-technical-design-v2.md:902,
  1166`.
