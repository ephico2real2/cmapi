# Fable's review of PR #239: the adoption design (story #26)

> **Superseded in part.** The owner decided on #26 (2026-11-14, 15:09Z and 15:11Z) that this design has no step about
> any other repository. A7's proposed text for D12, and each sentence here about an old tool or its repository, are
> withdrawn and are not part of the design. The second pass is at the end of this file.

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

---

# Second pass: head `c874e72b510eaa8a97d241e3128415abe9a857c1`

Reviewer: Fable 5.2, 2026-11-14. I read `a2b5854` in full (550 lines) and then the diff from it to `c874e72`, which
changes only D19, §1 item 12 and one paragraph of docs/02. Also read: the design's other files, the PR's diff of `docs/02` against
main, the figure's text, #26's comments of 15:09Z and 15:11Z, #251 and its comments of 15:28Z and 15:31Z. Sources read
again today: Kubernetes "Resource Quotas" and "Limit Ranges", "Server-Side Apply", Argo CD "Sync Options". Nothing was
measured on a cluster (#157). No pytest was run: the PR changes seven files, all under `docs/`.

**Verdict: not yet. Seven texts to change (R1 to R7), none of them large.** R1 and R2 are wrong as written. R3 to R6 are
gaps in the three new decisions. R7 is the owner's "no step about the old repository" rule.

## 1. A1 to A10

| Finding | In the new head | Result |
|---|---|---|
| A1 enforce mode | D6a: the approved plan's snapshot is the base, found by the request ID, checked against the plan hash, never read from the PR; admission by `oldObject`; B7 | Fixed |
| A2 revert and prune | D4: `Prune=confirm` on each ResourceQuota and LimitRange; D11 step 4: no `:revert` (409); B8 | Fixed |
| A3 field ownership | D3a: managers read from `managedFields`; a skipped key that a client-side apply wrote stays in the file; D11 step 3 compares `managedFields`; `cmapi.net/adopt` stays (the owner) | Fixed in the design. docs/02 line 975 still says the label is removed: R1 |
| A4 failure modes | D16, and B1, B3, B10 | Fixed. One row still says "one document each": R6 |
| A5 later decisions | §1 items 5 and 9; `declared-as-annotation`; two test namespaces | Fixed |
| A6 the next update | D6 "One rule for a value that the namespace already has"; the team rule; B9 | Fixed, by the owner's decision 2 |
| A7 the hazard in D12 | D12 withdrawn | Fixed. See R7 for what still names it |
| A8 label tracking | D1 step 3 | Fixed |
| A9 #217 | D11 step 5; D8's string rule | Fixed |
| A10 test plan | §5: each row is there | Fixed |

## 2. The owner's decisions on #26 (15:09Z, 15:11Z)

| Decision | In the design | Result |
|---|---|---|
| `cmapi.net/adopt` stays and is ignored | §1 item 6, D1 step 2, D4, §5 | Carried in the design. Not in docs/02 line 975: R1 |
| A missing required key is never forced, only reported | §1 item 7, D6, B9, §5 | Carried exactly |
| Adoption reads only the live namespace; no step about the old repository | §1 item 8, D2, D7, D12 withdrawn | No step remains in the design, docs/02 or the figure |

The search: `grep -rn "cluster-configs"` over the design, the figure's source, its drawing script and the PR's lines of
docs/02, without `cmapi-cluster-configs`. Every hit is the label value `company.net/provisioner: cluster-configs` or
`recognise: [cluster-configs]` (design lines 20, 30, 77, 181, 496; `source.html:87`; `draft-adoption.py:49`). No hit in
docs/02's new lines. Two places still describe a step: R7.

## 3. Remaining issues, each with the text to change

### R1 (must). docs/02 still says that `cmapi.net/adopt` is removed

`docs/02-technical-design-v2.md:975`, the table of keys:

> | cmapi.net/adopt | Label | "true" | Namespace owner or platform | Opt-in for adoption; removed when adoption completes |

This contradicts the owner's decision 1 (#26, 15:09Z) and the same document's line 1690 ("`cmapi.net/adopt` stays").
**Change to:**

> | cmapi.net/adopt | Label | "true" | Namespace owner or platform | Opt-in for adoption. It stays on the namespace afterwards and is ignored: `cmapi.net/managed` means adopted |

Two smaller lines of docs/02 in the same pass:

- Line 1696: "the owner's decision on #234". The decision is on #215 (comment of 14:25Z). Change `#234` to `#215`.
- Line 1166: "Removing a key from Git removes it from the cluster." D3a and D18 now say when that is not true. **Change
  to:** "Removing a key from Git removes it from the cluster when Argo CD is the key's only field manager; the plan says
  which case holds (Adoption plugin)."

### R2 (must). D17 would call `cpu` and `memory` uninterpreted, and they are the same keys as `requests.cpu` and `requests.memory`

D17 interprets "`requests.cpu`, `requests.memory`, `pods`, `persistentvolumeclaims`, `requests.storage`,
`services.loadbalancers` or `services.nodeports`", and every other name is "excluded from the maths". Kubernetes,
"Resource Quotas", the compute table: `cpu`: "Same as `requests.cpu`"; `memory`: "Same as `requests.memory`". An adopted
quota written `hard: {cpu: "40", memory: 64Gi}` is a common shape. With D17 as written its derived CPU and memory are
null, capacity counts nothing for the namespace, and the plan reports two false `uninterpreted-key` findings.

**Change D17's third bullet to:**

> A key is read by its meaning, not its spelling: `cpu` is `requests.cpu` and `memory` is `requests.memory` ("Same as
> `requests.cpu`", Kubernetes, "Resource Quotas"). The derived number of a key is the smallest `hard` over both
> spellings. The values are compared as quantities, so `1500m` is smaller than `2`. The raw object keeps the spelling it
> has. Any other name (an extended resource, an object count, `limits.*`, a storage class's key) is kept and shown raw,
> left out of the maths, listed in `uninterpreted`, and reported as `uninterpreted-key`.

**Add to B11's test:** "a quota with `cpu: '40'` and another with `requests.cpu: 30` give a derived CPU of 30; `1500m`
against `2` gives `1500m`".

### R3 (should). D17: a key that only scoped quotas hold has no derived number, and the design does not say what that means

**Is "the smallest hard among the unscoped quotas" right?** Yes. Each quota is checked on its own, and a request that
"violates a quota constraint" is refused with 403, so the tightest quota that measures every pod is the namespace's
limit, and a sum would overstate it. A scoped quota measures only the pods that match, so leaving it out of the
namespace's number is also right. `scopes` and `scopeSelector` are both named, and both are kept raw (D9).

**The gap.** A namespace whose only quotas are scoped has a derived value of null. That is common where a namespace has
one quota for `NotTerminating` pods and one for `Terminating` ones. Null must not read as zero or as "no limit" in
capacity and the KPIs.

**Add to D17, after the scoped-quota bullet:**

> When only scoped quotas hold a key, its derived number is null, which means "not known", never zero and never
> unlimited. The adoption plan reports a finding `scoped-only` with the key and the quotas. Capacity does not count the
> namespace for that key and says so in its answer, and the KPIs count it under "not known". A quota with an empty
> `scopes` list and no `scopeSelector` expression is unscoped.

Also add `"scopeSelector"` to the JSON example's quota object, beside `"scopes"`: the text holds it and the view does
not show it.

### R4 (should). D18: the two commits are right by the documentation; four limits are missing

**Is it correct?** By the documents, yes. The first sync applies the same value, which is shared ownership ("When two
or more appliers set a field to the same value, they share ownership of that field"). A changed value is then a
conflict, Argo CD's apply is forced, and a forced apply "changes the value of the field, and removes the field from all
other managers' entries in `managedFields`". The second commit leaves the key out, and a sole owner's omission removes
it. This is not measured, and B12 is the proof.

**Is the brief value acceptable?** For `company.net/provisioner`, yes: a marker that is about to go. The steps in
between are "another value" and then "absent", and a selector on the old value stops matching one sync early, which is
what the request asks for anyway. It is not acceptable for "any adopted label", which D18's first paragraph promises.
`cmapi-removing` on a key with an `enum` or `pattern` is refused by cmapi's own check and, in `enforce`, by the policy
at admission, because a changed value is checked. On a key that a selector or a webhook reads (pod security, mesh
injection, a NetworkPolicy's namespace selector) it changes behaviour for the time between the two syncs.

**Change D18's two-commit item to:**

> When another manager co-owns the label, the removal request takes two merges, never two commits in one merge: Argo CD
> applies only the last revision it sees.
> 1. The first sets the label to `cmapi-removing`. The worker waits for `Synced`, reads `managedFields`, and goes on only
>    when Argo CD's manager is the label's only owner. If it is not, the request fails with `removal-not-owned`, and the
>    label keeps `cmapi-removing` in Git and on the cluster until `:retry` or a request that sets a value.
> 2. The second leaves the label out. The worker checks that it is gone from the live object.
>
> The two-merge removal is offered only when all of these hold; otherwise the plan says "removed from Git; stays on the
> cluster" (D3a), and an operator removes the label on the cluster by hand after the merge:
> - the co-owner is not a controller that still writes the label (it would write it back, and Argo CD and the controller
>   would then fight);
> - `cmapi-removing` is a valid value for the key by the instance's rules and policies, so no rule is switched off for
>   it;
> - the key is not under a prefix that #215 reserves (D7).
>
> The plan of the removal shows the value in between and how long it will be there.

**A way with no value in between, to measure in B12 before the choice is fixed.** Argo CD's migration can take over the
fields of a manager that the annotation `argocd.argoproj.io/client-side-apply-migration-manager` names ("Sync Options",
"Client-Side Apply Migration"). Naming `oc label`'s manager on the Namespace for one sync would move the label to Argo
CD with its value unchanged, and the next commit removes it. Its cost: every field of that manager moves, so each of
them must already be in Git (D3a's rule), and I have not seen it run. If kind shows that it works, it is the safer
mechanism and D18 should prefer it.

**Add to B12's test:** "after the first merge, `managedFields` shows Argo CD as the label's only manager; a label with
an `enum` rule is not offered the two merges".

### R5 (should). D19 and D9: what is missing around the split

**The split itself is right.** One object for each resource, and no default set twice. The reason given follows the
page: every LimitRange's minimum, maximum and ratio hold ("defined in any LimitRange present in the namespace"), and
the defaults are the part that is "not deterministic". That two objects with defaults for different resources both
apply is a reading of that sentence, not a statement of the page. So it needs a proof.

**Add to D19, under "The rendering":**

> Not measured: that a pod with no resources gets the CPU default from `<ns>-limits-cpu` and the memory default from
> `<ns>-limits-memory`. The kind test of the split's pull request shows it, with ten pods, before the split is merged.

**The tier hash and the policies.** "The tier hash, which covers the rendered objects" does not say whether one hash
is on each object. `is_outdated` compares one hash for a namespace (`core/tiers.py:599`). **Change that bullet
to:** "the tier hash: one hash of the tier's whole rendering, written on the ResourceQuota and on both
LimitRanges, so `is_outdated` reads the same value from any of them". For the policies, `policygen.py`'s limit checks
already pass a key that an object does not hold (`{v} == '' || ...`), so a CPU object passes the memory checks. Say so
in the fourth bullet: "each check passes an object that does not hold its key, as today".

**Adopted namespaces can already break the rule that D19 states.** Two adopted LimitRanges that both set
`default.cpu` are exactly the case that Kubernetes calls not deterministic. **Add to D17:**

> Two LimitRanges that set a `default` or a `defaultRequest` for the same resource of the same type are adopted as
> they are, with a finding `duplicate-default` that names both: Kubernetes does not say which one applies.

**A move to a named tier leaves both sets for a time.** D9: the request "replaces the adopted objects with the tier's".
Each adopted object carries `Prune=confirm` (D4). So after that sync the tier's objects exist, and the adopted ones stay
until an operator confirms the prune. Until then every quota and every LimitRange of both sets is enforced, and defaults
can be set twice. **Add to D9's last paragraph:**

> Until the operator confirms the prune of the adopted objects, both sets exist. The tighter value of each key holds,
> and a default may come from either set. The plan of the move says so and lists the keys where the adopted value is
> the tighter one.

**For the owner to confirm.** The comment of 15:28Z says "`tiers.yaml`, the renderer, the tier hash ... follow the
split". D19 keeps the keys of `tiers.yaml` and changes only the renderer. That is the smaller change and I think it is
right. It is a choice within the owner's sentence, so the PR should name it.

**D19 at `c874e72`, after the owner's "We don't enforce limit ranges for storage".** D19 is two objects,
`<ns>-limits-cpu` and `<ns>-limits-memory`, and none for storage. I judge it against that decision and ask for no
storage object. The search `grep -n "limits-storage\|limitRange.pvc\|PersistentVolumeClaim"` over the design finds no
storage LimitRange that cmapi renders: line 361 says that the `PersistentVolumeClaim` item and
`limitRange.pvc.max.storage` leave the tiers' values, the `overridable` list, the `custom` bounds, #211's custom limits
and #212's policies, and that `requests.storage` and `persistentvolumeclaims` govern storage. An adopted storage
LimitRange stays raw, which is right: the decision is about what cmapi renders and checks, not about what it adopts.
docs/02 line 1710 says the same. No leftover in the design text.

What is left of it, outside the design text:

- docs/02 lines 1187, 1195, 1202 and 1210 still show `limitRange.pvc.max.storage` and `pvc: {max: {storage: ...}}` in
  the `tiers.yaml` examples. They are true of the code today (`deploy/helm/cmapi/config/tiers.yaml:33, 46, 71, 93`) and
  change with D19's own pull request. The PR's body should list them, so that they are not forgotten.
- #251's comment of 15:31Z still says "`<ns>-limits-storage` for the PVC item". A new comment should name the decision.
- **Add one sentence to D19's "No LimitRange for storage":** "After that pull request a request with a custom
  `limitRange.pvc.*` value is refused with a problem that names the key." #211 is merged, so such a request is possible
  today, and the design should say what happens to it.

### R6 (should). D8: the move from the old layout is safe only in one commit, and three readers name the old files

**Does the rewrite risk a diff or a prune?** Not by itself. Argo CD knows an object by its group, kind, namespace and
name, not by its file, so the same object in another file is no change. Two conditions make that true:

- The old file goes and the named files come in the same commit. A commit that holds both gives Argo CD the same
  object twice.
- Splitting the old file must not write the objects again in another form (D8's string rule covers this).

Three readers find the files by the old names today: `core/sync.py:144` (`p.endswith("resourcequota.yaml")`, which
`resourcequota-<name>.yaml` does not match), `core/pipeline.py:241-242` and `:398` (`_doc(prev_files,
"resourcequota.yaml")`), and the renderer's own keys (`core/render/manifests.py:134`).

**Change D8's last two sentences of the first paragraph to:**

> A folder written before this layout (`resourcequota.yaml`, `limitrange.yaml`) is still read, as a stream of documents.
> The next change of that namespace removes the old file and writes the named files in one commit, each object's text
> unchanged; no commit holds an object in two files. Argo CD knows an object by its kind and name, so the move changes
> nothing on the cluster and prunes nothing. Each reader of these files finds them by kind, not by file name
> (`core/sync.py`, `core/pipeline.py`, `core/render/manifests.py` name the old files today). A name longer than a file
> name allows is written under a hash of the name, and the plan says so.

**Add to B10's test:** "no commit holds both layouts; the sync check and the quota reader of the worker find the named
files".

**In D16,** the row "More than one ResourceQuota or LimitRange": change "Each is written, one document each (D8)" to
"Each is written to its own file (D8)".

### R7 (should). Two places still describe a step about another repository

The owner (15:11Z): "The adoption design, runbook and docs contain **no step about the old repository** at all (not
'remove it', not 'keep it')."

- **D12's stub:** "The earlier D12 described steps about another tool's repository. The owner's decision (§1, item 8)
  removes it". **Change to:** "### D12. (Withdrawn by the owner's decision, §1 item 8.)", with no second sentence.
- **`docs/reviews/2026-11-14-issue-26-adoption/fable-review.md`,** the copy of my first pass that this PR adds. Its A7
  proposes a runbook ("the operator removes the namespace from the old repository"), and its table row names D12's
  step. It is a record of a review, not the design, but it is in the repository and it reads as a step. **Add at its
  top, under the title:**

  > **Superseded in part.** The owner decided on #26 (2026-11-14, 15:09Z and 15:11Z) that this design has no step about
  > any other repository. A7's proposed text for D12, and each sentence here about an old tool or its repository, are
  > withdrawn and are not part of the design. The second pass is at the end of this file.

  Then append this second pass to that file, so the record in the repository is whole.

## 4. Smaller notes, no change asked before the merge

- #251's "Done when" names `docs/16-data-model.md`. D17 says that no table changes and that docs/16 gets a section
  "when it is built". That is a fair reading; the PR's body should say that docs/16 is not changed by this PR, so #251
  is not closed by it alone.
- docs/02 lines 960 to 961 and 1247 still show `resourcequota.yaml` and `limitrange.yaml` in the folder tree and the
  renderer's row. They are true of the code today and change with B10 and D19's pull request.
- D17's view reads "the live objects from each cluster's watch cache". For a namespace whose live quota differs from
  Git, the derived numbers are the live ones. Say in the view which source each number has when the two differ.

## 5. Sources, read on 2026-11-14

- Kubernetes, "Resource Quotas": <https://kubernetes.io/docs/concepts/policy/resource-quotas/> (`cpu`: "Same as
  `requests.cpu`"; `memory`: "Same as `requests.memory`"; the 403 on a violated constraint). The page's sections on
  scopes were beyond what my fetch returned; R3's statements on scopes rest on the design's own quotation and on how a
  scope selects pods.
- Kubernetes, "Limit Ranges": <https://kubernetes.io/docs/concepts/policy/limit-range/> ("it is not deterministic which
  default value will be applied"; "defined in any LimitRange present in the namespace").
- Kubernetes, "Server-Side Apply": <https://kubernetes.io/docs/reference/using-api/server-side-apply/> (shared
  ownership of an equal value; a forced apply "removes the field from all other managers' entries").
- Argo CD, "Sync Options": <https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/> (server-side apply with
  `--force-conflicts`; Client-Side Apply Migration and its manager annotation).
- #26 (comments of 2026-11-14T15:09:54Z and 15:11:08Z); #251 and its comments of 15:28:07Z and 15:31:23Z.
- cmapi at `c874e72`: `docs/02-technical-design-v2.md:975, 1166, 1696`; `core/sync.py:144`; `core/pipeline.py:241-242,
  398`; `core/render/manifests.py:134`. At #245's head `584e183`: `core/tiers.py:599`, `core/policygen.py:205-226`.
