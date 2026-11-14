# #212: Kyverno policies rendered from cmapi's configuration

OB1 run 6 (Opus 5.5 at high) wrote the code, the tests and this record on 2026-11-14. Two designs were made
independently, from two model families:

- `design-opus.md`, by Opus 5.5, written before Opus read the other design.
- `design-codex.md`, by Codex `gpt-6.1-sol`, from the brief in `ob1-run6/codex-212/brief.md`. It holds its own
  experiments and 235 `kyverno test` cases, run with the same CLI.

This README arbitrates the two designs. Fable reviews the pull request.

## The owner's decisions

- #212, 2026-11-13: "i don't wanna manage kyverno policy manually - so is there a way that the policy are auto generate
  based on the configured stuff and it can change dynamically?"
- #212, 2026-11-13: "we need extra approval for custom<STUFFs> that is beyond what set in tiers". This is built by #211.
  The approval facts are `beyondTier` and `beyondTierKeys`.
- #212, 2026-11-13: "Kyverno messages can be parameterized so too to use the configured values as generic message".
- #213: Kyverno is optional, with a mode for each environment. The generator takes `validationActions` from the mode,
  and renders nothing for an environment that is off.
- #213: the latest Kyverno, the `policies.kyverno.io/v1` types, and the CLI pinned at v1.20.0.

## Measured (Kyverno CLI v1.20.0, this Mac, no cluster: #157)

Both designs measured these, each separately. The files are in `experiments/` and in Codex's export.

| # | Finding |
|---|---|
| M1 | A static ValidatingPolicy with the bounds inline, `quantity()` comparisons and a `messageExpression` works offline. `65536Mi` is not above `64Gi`, and `24000m` equals `24` (Codex). |
| M2 | The CLI ignores `validationActions`. `[Deny]`, `[Audit]`, `[Warn]` and `[Audit, Warn]` each print `fail: 1` and exit 1. `--audit-warn` "Currently has no effect". |
| M3 | `-p --output-format json` writes an `openreports.io/v1alpha1` ClusterReport, with the policy, the resource and the expanded message for each result. It does not print "Applying N policy rule(s)". |
| M4 | One call with a folder of policies and several resources gives one result for each policy and each matched resource. |
| M5 | Two resources with the same kind, namespace and name make the CLI panic, with exit 2 and no JSON. |
| M6, M7 | `resource.Get()` from a ConfigMap works offline with `--context-file`. Without the file, the result is `error`, exit 1. Codex adds: a context file that does not exist, a Context with no resources, and a bare ConfigMap each exit 1, and `failurePolicy: Ignore` changes nothing offline. |
| M8 | The CLI evaluates as CREATE, and `oldObject` has no metadata. No flag supplies an old object. |
| M9 | Kyverno reports only the first failed validation of a policy (Opus, while building: 3 results for 9 broken keys). With one policy for each check, all 9 are reported. |
| M10 | A matchCondition that indexes a missing label is an `error` result ("no such key"), not a skip (Opus). The rendered conditions test with `in` first. |
| M11 | A policy with an apiVersion that the CLI does not know gives no result. With no other policy, the CLI exits 0 and writes no report (Opus). |
| M12 | `isURL('/path')` is true, so a URL check also needs the scheme and the host. `json.marshal()` quotes a value in a message. `.sign()` of a quantity is not registered, and `asInteger()` of `24000m` is an error (Codex). |

## Arbitration

| Question | Opus | Codex | Decision | Why |
|---|---|---|---|---|
| Q1. Static or dynamic | Static, values inline | Static, values inline. Codex refutes the claim that (b) cannot work offline (M6), and rejects (b) because the live ConfigMap can drift from the approved plan | **Static** | Both designs agree. One file gives one answer at the three points, and a change of a value is a reviewed change of the bundle. docs/02 "Keeping it offline" already decided this, and the measurements confirm it |
| Q2. Messages and findings | `messageExpression` with the configured value; parse the JSON report | The same, plus a shared rule descriptor that also feeds Python's problem detail and the portal | **JSON report, one policy for each check, and a message that names the key, the value and the configured value.** The index (`env/<env>/index.json`) maps each policy to its key and rule | M9 forces one policy for each check, so the index needs no `cel.validationIndex`. A shared descriptor for Python's messages is a refactor of `core/metadata.py` and `core/tiers.py` that the issue does not need. The agreement test checks that both checkers refuse the same values |
| The message of a hard bound | The owner's example: "ask for a custom tier with approval" | Approval cannot lift a hard maximum, so do not promise that | **Codex**: "…is above the rnd maximum of 32; a bound of tiers.yaml, which approval does not lift" | The maximum of `custom` bounds every tier. Approval adds approvers for a value beyond the tier (#211), but it never admits a value above the maximum (`TierCatalog._out_of_bounds`) |
| Q3. Modes | `[Deny]`; `[Audit, Warn]`; nothing | `[Deny]`; `[Audit]`; nothing, and Argo CD must prune | **`[Deny]`, `[Audit, Warn]`, and no files for off.** `cmapi-tools policies render` removes the files of an environment that is off, and the policies Application prunes them | `Warn` also tells kubectl and Argo CD about the finding, at no cost. Codex's prune point is right, and the example Application has `prune: true` |
| Errors in audit | (not covered) | A CEL error, a missing report or a missing result is a fault, never a warning | **Codex.** These findings have source `cmapi`, so audit keeps them errors | Audit must not hide a broken bundle |
| Q4. Metadata scope | Required keys, value rules, `namespacePrefix` and derived keys in Kyverno. Reserved prefixes, `allowOther` and its limits stay in Python | `allowOther` and its limits in Kyverno too, counting only the keys of class team | **Opus** for this pull request | A live Namespace carries keys that operators add (for example `operators.coreos.com/` from OLM), and no stanza lists them. At admission an `allowOther` rule would refuse them, and a new operator would break the sync of every namespace. Python checks what a requester sends |
| Q4. Bounds | The maximum of each key; the order of the LimitRange | Also the minimum, the step (by listing the exact multiples), named-tier equality and the shape | **The maximum and the order.** The minimum and the step stay in Python, and so does tier equality (Q5) | The minimum and the step bound custom values only, and a ResourceQuota names its tier in a label that the object itself sets. CEL has no exact modulo for a quantity (M12). Codex's listing of the multiples works, but it adds up to 4096 literals for each key |
| Q4. Scope of the metadata policies | Managed namespaces (`cmapi.net/managed`, new or old) | Do not rely on a label that a writer can remove | **Managed namespaces, matched on the new object or the old one** | Removing the label on an UPDATE is still checked, because the old object matches. A new namespace without the label is not one that cmapi manages. The required company keys on every namespace would refuse `openshift-*`. `deny-expiry-in-prod` still matches every namespace, as before |
| Q5. Approved overrides | The bounds always; the annotation explains an override but does not prove approval | Self-attestation can be forged; publish an exact PolicyException after approval, with a policy of tier equality | **The bounds always, and no tier-equality policy at admission in this pull request.** The question goes to the owner as #242 | Codex is right that the annotation proves nothing. The approval is proved by cmapi's check on the bot's PR: the request is approved and the head equals the plan hash. Kubernetes' `admin` role "does not allow write access to resource quota or to the namespace itself" (the RBAC reference, <https://kubernetes.io/docs/reference/access-authn-authz/rbac/>, read 2026-11-14), so the writers of a ResourceQuota at admission are platform administrators, who can also write a PolicyException. The reference does not say the same of a LimitRange: not measured, and a cluster check of `kubectl auth can-i update limitranges` as a project admin belongs to the CRC proof. Exceptions need a protected namespace, a publisher role, an order before the namespace sync, and revocation. That is a platform decision, not a change for this issue |
| Q6. Environment at admission | A folder for each environment, synced only to its clusters; `cmapi.net/env` checked against the folder | The same; plus a policy for each cluster when a key derives from the cluster | **A folder for each environment.** A key with `value.from: cluster` is checked against `cmapi.net/cluster-id` as consistency only, and #243 tracks the policy for each cluster | Both agree on the folder. No shipped configuration derives a key from the cluster |
| Codex: the example root Application syncs no policies | — | Found: `root-application.yaml` syncs only `clusters/OCP_GF15/namespaces` | **Fixed here**: `examples/cluster-configs/clusters/OCP_GF15/argocd/policies-application.yaml` syncs `policies/env/dev/*.yaml` with prune | docs/02 promised the sync, but the example did not have it |
| Q7. Where plan time gets the bundle | Render in memory from the running configuration | Use the committed bundle by its hash, and refuse a configuration whose bundle is not published and healthy | **In memory, plus `cmapi-tools policies check` in CI.** #244 tracks the bot PR on a configuration change and the bundle hash in each plan | The check makes a stale bundle in Git fail CI. Publishing and gating need the bot's Git path outside `clusters/` |
| Q7. Agreement tests | Python and Kyverno refuse the same values; a changed bound changes the policy | The same, with 235 `kyverno test` cases | **pytest with the real CLI** (`tests/core/test_policygen.py`), run in CI with the pinned CLI, which fails rather than skips | The pytest cases cover each rule family, with the rendered owner sample and the repository's example folder |
| D9. A value that Git already holds | At plan time, drop a failure on a key that the previous version holds; at admission, the same with `oldObject` | Do not grandfather with `oldObject` alone, because an earlier bad state would be grandfathered; use records of approved values | **Opus** | `TierCatalog._out_of_bounds` grandfathers from Git, and Codex agrees that the base of Git is trusted. At admission, an old value was admitted earlier, by the cluster's own policy or before it existed. A background scan (no `oldObject`) still reports each such value in the policy reports. Records of approved values are a second store of approval that can drift from Git |
| Version of the CLI | (not covered) | Check the pinned version at start | **Codex**: with `CMAPI_KYVERNO_VERSION` set (the image sets it), cmapi refuses to start with another version | An unpinned CLI evaluates the bundle differently from the clusters |

## Behaviour, before and after

| Before | After |
|---|---|
| `cmapi/policies/require-team-metadata.yaml` (in the image): `cmapi.net/team`, `cmapi.net/cluster-id` and `cmapi.net/team-dl` present on each Namespace. An empty value passed (Codex, `old-metadata.log`) | Rendered from `metadata-keys.yaml`: each required key present and not empty, and each value on its rule. `cmapi.net/cluster-id` and `cmapi.net/managed` stay required as system keys. Managed namespaces only |
| `deny-expiry-in-prod`, hand-written, in the image and in the example bundle | Rendered for `prod`, with the same three keys, the same presence rule, the same message and the same scope (every namespace) |
| No quota and no LimitRange rule, although docs/02 said "limits never below requests" | New: the maximum of each key, and the order defaultRequest ≤ default ≤ max |
| `kyverno apply` for each policy and each namespace.yaml; the last line of text is the message | One `kyverno apply` for each plan, on namespace.yaml, resourcequota.yaml and limitrange.yaml; the JSON report gives each message |
| "Applying 0 policy rule(s)" is a finding | A policy with no result for a file that it matches is a finding, and so is a run with no report (M11) |
| A policy under `env/prod` ran for prod only; the other paths ran everywhere | A policy under `env/<env>` runs for `<env>` only |
| Audit turned every finding of Kyverno into a warning | Audit turns a violation into a warning. An evaluation error, a missing report and a missing result stay errors |

## Proof

| Test | Before (main) | After |
|---|---|---|
| `cmapi/tests/core/test_policygen.py` (25: each mode; a tier above the maximum; the index; the committed example bundle for each instance; the check refuses a hand edit; the owner's sample in each tier; the example folder `payments-dev`; each rule's message; Python and Kyverno refuse the same 7 values; a changed bound; prod expiry; an unmanaged namespace; the validator's findings; a value that Git holds; audit; the guard; the pinned version) | fails at import (no `core/policygen.py`) | 25 passed |
| `cmapi/tests/core` | 227 passed | 252 passed |
| The reference job, in a virtual environment with only `examples/local/requirements.txt`, as CI runs it | | 251 passed |
| `cmapi/tests/service` | | see the pull request |

Not measured: admission on a cluster (kind and CRC wait on #157), the `oldObject` ratchet at admission (the CLI has
no old object, M8), and Argo CD's prune of the policies Application.

## Sources, read on 2026-11-14

- Kyverno ValidatingPolicy, <https://kyverno.io/docs/policy-types/validating-policy/>: "If both message and
  messageExpression are defined, the messageExpression takes precedence."
- Kyverno CEL libraries, <https://kyverno.io/docs/policy-types/cel-libraries/>: `resource.Get()` "to retrieve Kubernetes
  resources from the cluster".
- Kyverno CLI, <https://kyverno.io/docs/subprojects/kyverno-cli/>, and `kyverno apply`,
  <https://kyverno.io/docs/kyverno-cli/reference/kyverno_apply/>: `--context-file` "File containing context data for CEL
  policies"; `--audit-warn` "Currently has no effect; ValidatingPolicy audit support is tracked by
  https://github.com/kyverno/kyverno/issues/16485".
- Kyverno policy exceptions, <https://kyverno.io/docs/guides/exceptions/>: "PolicyExceptions are disabled by default."
- Kubernetes CEL, <https://kubernetes.io/docs/reference/using-api/cel/>: the quantity library, `quantity(string)`.
- Codex's sources, with their hashes: `ob1-run6/codex-212/experiments/sources/manifest.json`.
