# Generated Kyverno policy design — cmapi #212

Date: **2026-11-14**. Export: `f18224f3aae4e64bdd64a07b5cb2f109bffb62d6` (`EXPORT-HEAD`). Independent design, native-only evidence.

**Decision:** static configuration-generated v1 ValidatingPolicies, scoped by trusted environment deployment; exact-value PolicyExceptions published only after verified approval; one versioned configuration/policy snapshot at plan, CI and admission. Dynamic ConfigMap context works offline, but requires additional synchronization to guarantee that same snapshot.

TokenSave status/context/read were attempted first. This export is not an initialized graph and the server has no default graph, so source inspection used exported files without modifying indexes or accessing other project trees.

## Authority and scope of this design

The complete issues were read: `ISSUE-212.md:1` through its final line, `ISSUE-213.md:1`, and `ISSUE-211.md:1`. Binding decisions: configuration generates policy; every beyond-tier change adds approval; messages carry configured and offending values; Kyverno is optional per environment; use the pinned v1.20.0 CLI and `policies.kyverno.io/v1`. The coordinator's preference for ConfigMap lookup is a hypothesis, not authority. This is a design deliverable, not a claim to have merged #212 or updated a live document. Application source is unchanged.

The export already contains the #211 API work and #213 modes. `TierCatalog.beyond` excludes custom sizable quota values because those have no fixed tier value (`tiers.py:526`); normal quota-change and environment approvals still apply. A decrease from a fixed custom baseline is also beyond-tier: the comparison is inequality, not only an increase (`tiers.py:530`). Keep that interpretation.

## Primary sources, retrieved/read 2026-11-14

The supplied `kyverno-docs/` copies are the dated v1.20 design baseline. Live primary pages were also opened and fetched; URLs, redirects, SHA-256s, dates and HTML are saved in `experiments/sources/manifest.json`. Documentation can drift: a measured CLI result takes precedence for this binary. Short direct quotations below are each from the linked page, read on **2026-11-14**.

| Source | Short quotation | Design consequence |
|---|---|---|
| [Kyverno ValidatingPolicy](https://kyverno.io/docs/policy-types/validating-policy/) (`kyverno-docs/validating-policy.mdx:276`) | “If both message and messageExpression are defined, the messageExpression takes precedence.” | Emit a generic fallback and a CEL message expression; verify offline. |
| [Kyverno CEL libraries](https://kyverno.io/docs/policy-types/cel-libraries/) (`cel-libraries.mdx:13`) | “retrieve Kubernetes resources from the cluster” | `resource.Get` is external state, not a value embedded in a policy. |
| [Kyverno CLI guide](https://kyverno.io/docs/subprojects/kyverno-cli/) (`kyverno-cli.mdx:681`) | “This file contains a mock ConfigMap” | Offline context substitutes for the admission lookup; it must correspond to the admission ConfigMap. |
| [kyverno apply](https://kyverno.io/docs/kyverno-cli/reference/kyverno_apply/) (`kyverno_apply.md:58`) | “File containing context data for CEL policies” | The actual flag is `--context-file`. |
| [kyverno test](https://kyverno.io/docs/kyverno-cli/reference/kyverno_test/) | “Run tests from a local filesystem or a remote git repository.” | Store policy/resource/expected-result fixtures and run the real CLI. |
| [Policy exceptions](https://kyverno.io/docs/guides/exceptions/) (`exceptions.md:11`) | “PolicyExceptions are disabled by default.” | Platform enables exceptions only in a controlled namespace, with narrow write access. |
| [Migration to CEL](https://kyverno.io/docs/guides/migration-to-cel/) | “This guide helps you migrate from ClusterPolicy to the new CEL-based policy types.” | Do not introduce a legacy ClusterPolicy/JMESPath context design. |
| [JMESPath to CEL](https://kyverno.io/docs/guides/jmespath-to-cel/) | “use the `%` operator directly (integers only)” | A quantity step needs exact normalization, not float modulo. |
| [GeneratingPolicy](https://kyverno.io/docs/policy-types/generating-policy/) (`generating-policy.mdx:15`) | “The GeneratingPolicy enables the creation and cloning of Kubernetes resources using Common Expression Language (CEL) expressions.” | Useful for cluster-side clones, but would introduce an extra writer for cmapi's approved manifests. |
| [Policy packaging example](https://kyverno.io/docs/guides/pod-security/) | “kustomize build https://github.com/kyverno/policies/pod-security” | Upstream supplies Kustomize manifests and a Helm policies chart; cmapi can still publish plain generated manifests. |
| [MutatingPolicy](https://kyverno.io/docs/policy-types/mutating-policy/) (`mutating-policy.mdx:3`) | “Mutate new or existing resources” | Do not silently alter approved quota or metadata at admission. |
| [Kubernetes ValidatingAdmissionPolicy](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/#message-expression) | “message expression must evaluate to a string.” | The same object/variables can feed a readable message. Native VAP also requires bindings; do not conflate VAP binding actions with Kyverno's spec actions. |
| [Kubernetes CEL](https://kubernetes.io/docs/reference/using-api/cel/#kubernetes-quantity-library) | “quantity(string) Quantity” | Compare parsed quantities, never lexicographic quantity strings. Test the engine's actual quantity functions. |

Legacy ConfigMap context (`context[].configMap` / `apiCall`), JMESPath `{{…}}` substitutions, Helm escaping of those substitutions, and Kustomize patch overlays are rejected as the implementation here. They would add another language or renderer and do not satisfy the owner's new-type decision. The v1 equivalent is CEL `variables` plus `resource.Get`; external HTTP/API lookup can similarly use a CEL library but is not needed. `GeneratingPolicy` and `MutatingPolicy` remain optional platform tools for unrelated cloned data/defaults; they do not replace the bot's reviewed render/plan/hash path (`render/manifests.py:8`, `:60`, `:205`). The current upstream [PSS guide](https://kyverno.io/docs/guides/pod-security/) demonstrates Kustomize rendering and a parameterized Helm policy chart (`policyType: ValidatingPolicy`, `podSecurityStandard`). That validates render-time packaging as an established pattern. It does not require cmapi to use those chart-specific schemas. The v1.20 GeneratingPolicy docs also describe YAML-first templates and structural CEL interpolation with `(( ... ))`; that is cluster resource generation, a separate concern from compiling policy configuration into Git. No Helm or Kustomize command was run; no performance comparison is claimed.

## Q1 — choose static generated policies

Choose **(a)** for metadata, tiers, mode, allowlists and expiry. Templates/code live with cmapi. Configuration is resolved through `MetadataKeys` and `TierCatalog`, then emitted as deterministic plain YAML with inline constants. A configuration change regenerates the policy; nobody edits numbers in a policy. The reviewed bot PR publishes the output to cluster-configs, and Argo CD applies it. “Dynamic” to the owner means enforcement changes with configured values without manual policy work; it does not require an admission-time data lookup.

**The coordinator's offline concern is refuted; its dynamic preference is rejected for consistency reasons.** Approach (b) works in v1.20.0 offline. `experiments/probe.py` and its individual logs establish:

| Input / run | CLI result |
|---|---|
| Correct Context, name `good` | pass 1, fail 0, error 0; exit 0 |
| Correct Context, name `bad` | fail 1; message `expected=good; actual=bad`; exit 1 |
| No `--context-file` | error 1, fail 0; exit 1 |
| Nonexistent context file | `Error: open …/absent.yaml: no such file or directory`; exit 1 |
| Context with empty resources | error 1; exit 1 |
| A bare ConfigMap as context file | unknown field `data`; exit 1 |
| `--context-path` (a typo in guide prose) | unknown flag; exit 1 |
| `failurePolicy: Ignore` and no offline context | still error 1 / exit 1: CLI output is not an admission simulation of failure handling |

Exact working context (also saved as `experiments/context.yaml`):

```yaml
apiVersion: cli.kyverno.io/v1alpha1
kind: Context
metadata:
  name: policy-context
spec:
  resources:
    - apiVersion: v1
      kind: ConfigMap
      metadata:
        namespace: cmapi-system
        name: policy-values
      data:
        name: good
```

The policy variable is `resource.Get("v1", "configmaps", "cmapi-system", "policy-values")`; the expression is `object.metadata.name == variables.config.data.name`. Run with `tools/bin/kyverno apply experiments/dynamic.yaml --resource experiments/probe-ns.yaml --context-file experiments/context.yaml`. A ConfigMap holds strings, so a structured catalog would require serialized data plus explicit parsing. Do not confuse `--context-file` with kubeconfig `--context`, a values file, `--parameter-resource`, or a native VAP `paramKind`/`paramRef` binding.

Both approaches can fail closed in **enforce**, for matched resources with installed policy, `failurePolicy: Fail`, and a webhook configured to fail on transport errors. Missing dynamic context demonstrably fails offline. Admission failure handling is a source-backed design requirement, **not measured against a cluster**. `audit` intentionally reports rather than denies, and `off` provides no Kyverno admission gate. Missing policy installation itself is not made safe by `failurePolicy`; monitor desired policy count/hash and readiness.

Static provides the same inputs and object-local verdict at plan, CI and admission **when the exact policy bundle hash is deployed**. Dynamic provides the same answer only if the offline Context and the admission ConfigMap are the exact same immutable data version; an independently updated live ConfigMap can disagree with an approved plan. An immutable, hash-named ConfigMap and synchronized policy/data rollout could solve that, but adds a data artifact, read permissions, lookup failure, ordering and retention. There is no benefit for these small catalogs that justifies those dependencies. Static also requires rollout tracking: an Argo sync delay is not instantaneous consistency. Block publication/commit of plans requiring a new bundle until the target policy application reports that bundle healthy; replan on stale hashes. Do not compare a plan validated with a new local config to a cluster still running the old bundle.

`experiments/timings.json`: five process-inclusive failing applies each, median about **0.592 s static / 0.601 s dynamic** on this machine. This tiny sample does not establish a material speed difference and says nothing about admission latency. Consistency and provenance decide the choice.

## Q2 — generic messages and lossless findings

`messageExpression` works offline. Human output prints the expanded message, and `--policy-report --output-format json` produces a parseable `openreports.io/v1alpha1` **ClusterReport** with `results[].message`, `policy`, `rule`, `result`, resource identity, and `properties["cel.validationIndex"]`. See `dynamic-report.log`, `company-fail-report.log`, `dev-quota-fail-report.log`. Example:

```json
{"policy":"cmapi-dev-quota-bounds","rule":"validation","result":"fail","message":"bounds.requests.cpu: requests.cpu in dev: min=2, max=32, step=1; actual=\"40\"","properties":{"cel.validationIndex":"3","process":"background scan"}}
```

Today's `CliValidator._kyverno` saves only the last nonempty output line, typically `pass: 0, fail: 1, …`, and truncates to 300 characters (`validate/__init__.py:115`). **Change this.** Read JSON reports; map `(policy, validationIndex)` through a generated manifest to a stable rule ID and fields. Keep `result.message` verbatim as the finding detail. Use the observed API kind, not a hard-coded old `wgpolicyk8s.io` report assumption. Reject malformed JSON, compiler failures, unexplained nonzero exits, `error` results, zero applicable rules and unknown skips as validator/configuration errors; never turn them into an ordinary violation warning in audit.

A shared rule descriptor owns key, environment, tier, min/max/step/enum/pattern/domains, stable rule ID and message template. Generation uses those values for the expression and CEL message; the Python validation adapter uses them for problem `errors[]` with structured `key`, `value`, `min`, `max`, `step`, `expected`, `environment`, `bundleHash`, and the same rendered detail. The portal displays the API detail and fields instead of independently substituting numbers. Existing `KeyRule.text` (`metadata.py:54`) is useful for metadata; `TierError` already carries bounds (`tiers.py:431`). Refactor those formatting paths to use the same descriptor; preserve registered outer RFC 9457 problem codes. The current pipeline mapping is `pipeline.py:270`.

Use static `message` as a fallback with the same configured values and `messageExpression` to add the actual value. Do not use legacy `{{…}}` in a v1 CEL message. `json.marshal(actual)` supports strings, lists and maps and quotes the offending string. A naïve `string(list)` failed compilation in this CLI; saved as `company-first-compile-failure.log`. Optional lookups use `[?"key"]`, not `.?["key"]`; the failed version is saved in `quota-first-compile-failure.log`.

The prototype emits precise key/value messages, but its bounds text is deliberately simple (`min=…, max=…, step=…`). Production wording should add the configured route to request an approved override. If the **hard maximum** is exceeded, do not promise that ordinary override approval can bypass it: explain that the value is invalid and needs a reviewed bounds change. A within-bounds tier-default violation can say “ask for a custom tier with approval.” There is no independent portal wording or hard-coded numeric message.

## Q3 — modes belong to configuration, not CLI exit-code semantics

| Effective mode (`PolicySettings.mode_for`) | Rendered `validationActions` | Plan | PR CI | Admission |
|---|---|---|---|---|---|
| enforce | `[Deny]` | violations are errors/refuse | violations fail | denies violations |
| audit | `[Audit]` | violations are warnings, visible to approvers; approval continues | report violations; do not fail for a violation | allows, writes reports |
| off / engine none | **nothing** | skip Kyverno entirely, still Python and kubeconform | skip Kyverno entirely, still own checks | no cmapi policy/exception remains |

`policy.py:31` resolves engine none, environment override, default; `config.py:112` parses the instance setting; `context.py:97` passes it to `CliValidator`; `validate/__init__.py:68` skips off and demotes findings from Kyverno for audit. Preserve startup checking for a missing enabled CLI (`:48`), and its runtime missing-binary error. Off must also skip compilation and CLI presence checks. If a config used only by Kyverno is invalid, it must not require a CLI while off, but Python-required config remains validated.

Measured `actions-deny.log`, `actions-audit.log`, `actions-warn.log`, `actions-warn-audit.log`: all apply the false expression, print `fail: 1`, `warn: 0`, and exit 1. **The CLI ignores `validationActions` as an enforcement disposition**. Do not use `[Warn]` as a substitute for implementing audit in cmapi/CI. The wrappers read the trusted instance config snapshot, verify it agrees with generated actions and bundle manifest, then map only actual policy violations to the mode. Compilation/evaluation/I/O errors remain configuration errors in every enabled mode. This is a deliberate correction to today's wrapper, which can demote a zero-rule/compiler finding when it has source `kyverno`.

Admission reads the generated spec, not `instance.yaml`. Off must prune the old per-environment policies and associated exceptions via the policy Application; simply ceasing to render YAML without Argo pruning leaves enforcement active. Mode transitions are reviewed config changes, with platform review for leaving enforce and protected CODEOWNERS/branch rules (`ISSUE-213.md`; docs/02:1889). Policy mode/hash must appear in integrations, plans, dry runs, CI reports and metrics. Audit adds warnings, not a bypass of Python's metadata/tier safety checks.

## Q4 — exact rule inventory and offline boundary

The production generator emits the checks classified **object-local** below into CEL; they must have CLI fixtures and also remain available through Python validation when Kyverno is off (#213 overrides docs/02:1865's older “Python validators keep only…” sentence). “Possible” is not a claim the production feature is implemented. The runnable core and measured subset are explicitly identified later.

### Metadata

Source: `metadata.py:85` constructor, `:202` classification, `:246` request validation, `:301` syntax, `:310` governed checks; company configuration `metadata-keys.company.yaml:30` onwards. Metadata policies target **Namespace**; do not require company namespace keys on ResourceQuota, SA or RoleBinding.

| Generated rule | Object-local offline? / other work |
|---|---|
| Each required label and annotation exists and is nonempty | Yes. Required derived keys are populated by renderer and also checked. |
| Each configured `pattern` uses full-match semantics; each `enum` is exact, string-valued membership | Yes. Wrap regex for full match, reject unsupported Python-vs-RE2 constructs during config compile; never silently weaken one. |
| `format: email-in-domains` | Yes. Same local-part syntax and case-insensitive exact domain list as `identity/checks.py:35`; no directory lookup, no DL membership check. Default configuration measured. |
| `format: url` on annotations only | Yes in principle: HTTP/HTTPS, authority present, no whitespace, equivalent to `urlsplit` rule. **Translator equivalence was not measured; prototype raises explicitly**. Must add conformance corpus before production. Formats on labels already fail config loading. |
| `namespacePrefix` | Yes: namespace starts with value + `-` (not “key equals authenticated caller's team”). Pattern and prefix both apply. |
| `value.from: namespace` | Yes: equal `object.metadata.name`. |
| `value.from: environment`, `instance`, `cluster` | Yes with trusted compiled constants, not values derived from other self-writable labels. Environment and instance are bundle inputs. A cluster-derived key gets a cluster-specific metadata overlay with that cluster ID; common env rules stay shared. No cluster API call. |
| Declared extra keys | Validate when present; optional keys accepting any value still get Kubernetes metadata syntax checks. |
| `allowOther.prefixes` | Yes. Match the DNS **prefix**, not a substring of the whole key. `""` means unprefixed only; `*.company.net/` includes `work.company.net/x`, not `company.net/x`. Unknown keys outside allowed prefixes fail. |
| `allowOther.max` | Yes. Count only class `team` keys, after merging final object. Required/governed/system/operator/reserved/adoption keys do not consume the “other” cap. |
| `maxValueBytes`, `maxBytesTotal` | Yes: UTF-8 **value bytes** of only team annotations; not character count, key bytes, governed annotations or all Kubernetes annotations. `size(bytes(v))`; sum over matching values. Tested at 4096/4098 bytes and 65536/69632 total. Kubernetes's separate total annotation limit still applies. |
| Key DNS prefix/name syntax and label value syntax | Python + kubeconform + native Kubernetes API; a generated namespace syntax guard can repeat it where needed. Object-local, but no need to hand-copy Kubernetes schemas. Kubeconform is still required for offline syntax. The prototype does not claim a standalone policy is a full Kubernetes schema validator. |
| System keys, operatorOnly, reservedPrefixes, adoptionLabels | Generate a class/exclusion set for value rules, limits and system invariants. **Do not globally forbid their presence.** Renderer writes system keys and Argo annotations; OpenShift/controllers add reserved keys (docs/02:1198). Request authority and sensitive edits remain Python plus CI/RBAC. A trusted-writer admission rule can inspect userInfo/oldObject, but that is not a one-new-object-only offline check and requires an explicit identity fixture. |
| `sensitiveKeys`, operator permission, adoption recognition | Python approval/authorization/adoption facts; not mere final-state validation. `metadata.py:363` compares before/after. CI recomputes from base and PR head. |

Company-specific generated value rules are: label `name` = namespace; label and annotation `company.net/app-environment` = trusted `rnd` in the demonstration; `company.net/mnemonic` matches `^[a-z]{3}$` and prefixes namespace; `company.net/lob` in `[amgsst]`; `company.net/cl` in `["0","1","2","3"]`; optional `company.net/mnemonic-group-contact` and `company.net/mnemonic-confluence` accept Kubernetes label values (they are not URLs/emails). Both other-key sets allow unprefixed or `*.company.net/`, cap 50; annotations cap 4096 each and 65536 total. Required system cluster-id is preserved separately. No hard-coded cmapi.net/team or team-dl is imposed when this company file replaces the default.

### Tiers and bounds

Never implement inheritance/merge a second time. Use `TierCatalog.resolve/offered/bounds` (`tiers.py:391`), which already merges defaults → tier → effective env override and custom → effective env custom. `dev` inherits `rnd` (`examples/config/tiers.yaml:101`). The environment's **custom bounds apply to custom values**; named tiers must equal their own resolved definitions, even if a named tier exceeds an environment's custom bound. Otherwise a policy could reject an offered named tier.

Quota keys: **requests.cpu, requests.memory, pods** (sizable), plus **persistentvolumeclaims, requests.storage, services.loadbalancers, services.nodeports** (overridable). For custom, require all sizable values; the final rendered object also has the fixed defaults/overridable quota keys. Generate: offered tier; canonical required key set/no extra unconfigured quota keys; valid nonnegative quantities; min/max/exact step; named-tier equality; custom non-sizable tier-default equality unless covered by a separately authorized exact exception. Do not exempt bounds just because an annotation names a key. A known-tier label is required; absence or an unknown tier fails.

| Environment | CPU min/max/step | Memory min/max/step | Pods min/max/step |
|---|---|---|---|
| rnd | 2 / 32 / 1 | 4Gi / 64Gi / 1Gi | 10 / 300 / 10 |
| dev | 2 / 32 / 1 | 4Gi / 64Gi / 1Gi | 10 / 300 / 10 |
| qa | 2 / 48 / 1 | 4Gi / 128Gi / 1Gi | 10 / 400 / 10 |
| uat | 2 / 64 / 1 | 4Gi / 256Gi / 1Gi | 10 / 500 / 10 |
| prod | 2 / 128 / 1 | 4Gi / 512Gi / 1Gi | 10 / 1000 / 10 |

All environments inherit these other maxima: PVCs 100, requests.storage 2Ti, LoadBalancers 2, NodePorts 10. No explicit minimum or step for these: Kubernetes nonnegative/count semantics still apply, without inventing a config step. LimitRange adjustable keys are exactly:

| Limit key | Each environment's current maximum |
|---|---|
| limitRange.container.defaultRequest.cpu | 16 |
| limitRange.container.defaultRequest.memory | 32Gi |
| limitRange.container.default.cpu | 16 |
| limitRange.container.default.memory | 32Gi |
| limitRange.container.max.cpu | 16 |
| limitRange.container.max.memory | 32Gi |
| limitRange.pvc.max.storage | 500Gi |

Min/defaultRequest/default/max per resource must be nondecreasing, comparing every present pair, not just adjacent fields that happen to exist. Container and PVC entries must have the configured shape and no duplicate types; reject unconfigured keys/parts, preserve absence of optional `min`. Non-overcommittable resources (hugepages and non-native extended resources) require defaultRequest = default when both exist (`tiers.py:99`); CPU/memory may differ. Every configured bound above is object-local on one LimitRange. Current custom defaults: container request 100m/256Mi, default 500m/512Mi, max 2/4Gi; PVC max 50Gi. Named values include dev medium max 4/8Gi, dev large max 8/16Gi, and uat/prod medium 8/16Gi, large 16/32Gi (`tiers.yaml:48`, `:65`, `:107`). Generate default equality from resolved objects rather than hard-coding these.

**Cross-object checks stay Python**: container max must fit that namespace's requests.cpu/memory quota; a quota limit and request in different objects cannot be compared from one offline input; quota vs current usage, aggregate capacity and placement also need outside data. A `ResourceQuota` that itself contains limits and requests can check limits ≥ requests locally; Pod/container resource requests/limits are likewise object-local if the platform elects workload validation. Today's actual hand-written files contain **no** limit/request check despite the docs saying the bundle checks it. For the objects cmapi actually renders, “limits never below requests” means the LimitRange ordering above; do not pretend a cross-object fit check became offline just by copying a quota into an untrusted annotation.

Catalog validity (offered tiers, inheritance cycles, unique order, tier growth, bound validity, arbitrary quantity validity, every configurable key has a maximum, catalog/approval tier-name agreement) remains loader/Python startup validation (`tiers.py:243`, `:300`; `config.py:103`). Approval facts and authorization remain Python (docs/02:1893). Kyverno off keeps all necessary safety checks.

**Exact quantity measurement:** `quantity("24000m").compareTo(quantity("24")) == 0` passes, but `.isInteger()` is false and `.asInteger()` produces an evaluation error (`quantity-probe-run.log`). `.sign()` is not registered (`quantity-sign-failure.log`) even though the live Kubernetes CEL docs list it. Use `compareTo(quantity("0"))` for sign. For step, the runnable prototype enumerates the finite exact multiples between bounds and tests `compareTo == 0`; it accepts `24000m` for 24 CPU and rejects `24500m` for a 1-CPU step, without float precision loss. The configured domains are small; the prototype refuses an enumeration over 4096 candidates instead of silently weakening validation. Benchmark and compile-check total CEL cost before production; an exact rational quantity translator is the alternative for unusually large domains. This limitation is technical and explicit, not a new approval veto.

### Other rendered objects and expiry

`render/manifests.py:140` emits Namespace, ResourceQuota, LimitRange, optional ServiceAccounts and RoleBindings (including SCC ClusterRole grants), plus token-issuer RoleBinding. There is **no rendered NetworkPolicy** today. Metadata is flexible under its stanzas; expiry follows expiration config and never prod; quota/LR fields are exactly those listed above. SA names, grants and SCC selections are configurable only through their existing validated APIs/allowlists and approval rules, not arbitrary spec patches. The token-issuer roleRef/subject is a system invariant, not team-overridable. No arbitrary Namespace status/finalizer/RBAC privilege override is introduced by #212.

Generate the existing prod expiry rule unchanged in meaning: forbid the **presence**, even empty, of annotation `cmapi.net/expires-at`, label `cmapi.net/expiry`, or label `cleanup.kyverno.io/ttl`; CREATE and UPDATE, all Namespaces. No expiry rule in other environments. `expiry_policy` and four fixtures measure this.

Keep DNS/reserved namespace checks, SA-subject-only/same-namespace, ClusterRole and SCC allowlists, protected deletion as separate existing/planned rule families described in docs/02:1891. They are not present in today's two hand-written policies and must not be reported as existing behavior. Most final-object conditions can be CEL with inline allowlists; protected DELETE needs DELETE request/oldObject, and caller namespace-admin, capacity, existence, concurrent requests, approval and cluster state stay Python. No new workload/network policy is justified by this issue alone.

Network recommendation: preserve the #211 API's bounded LoadBalancer/NodePort quota overrides and require **both beyondTier and networkExposure** approval slots when their conditions hold (`pipeline.py:292`). Keep low defaults of zero and maxima 2/10; neither grant exposes a Service by itself. Platform/network reviewers own higher exposure and future NetworkPolicy templates. If NetworkPolicy flexibility is added later, use reviewed profiles with explicit ingress/egress facts; do not allow an unbounded arbitrary networking manifest because a tier annotation exists. This recommendation is not a new owner decision.

## Q5 — approved overrides: choose narrow PolicyExceptions over self-attestation

Option (a), hard bounds plus `cmapi.net/beyond-tier` and request ID, is **not proof of approval**. A hand edit in Git can change both field and annotation; a cluster writer can set both in one admission request. The existing renderer records comma-separated key names on each RQ/LR, not the approved value, approver identity or a signature (`tiers.py:631`). `TierCatalog.rendered_overrides` reconstructs values from those self-declared keys (`:537`). Preserve these annotations for explainability, but never treat “has a request ID” as authorization. Current Python's trust in approved values from the base Git tree depends on protected Git provenance (`pipeline.py:239`); CI must not trust a newly edited annotation in the PR head as that provenance.

Choose **(b)**, with separate policies and a tightly controlled exception namespace:

1. Bounds/order/shape, prod expiry and metadata policies are independent from tier-default equality policies. Normal override exceptions reference **only the equality policy**. No broad exception for “all checks on namespace X”.
2. Each exception matches exact GVK, cluster by its deployment scope, namespace, object name, tier and the complete approved governed spec (or a canonical exact per-field set with no extra fields). Restrict writer RBAC to the approval publisher/policy Argo controller; no team may create or change a PolicyException or the policies themselves. Scope all such writes through a protected Git directory with mandatory platform review. Ordinary namespace write access is insufficient to create an exception.
3. For even tighter isolation, emit one equality policy per overridable key; then an exception can reference only those policies/keys. The executable probe uses one per object family but pins the entire approved spec in its exception. Pinning only the request ID or a label selector is rejected.
4. cmapi verifies request/plan hash, requester and distinct eligible approvers, all extra beyond-tier and network exposure slots, environment, base revision and exact proposed field/value set before publishing the exception. CI independently derives the delta from the **trusted base**, resolves the same catalog version, recomputes `beyondTierKeys` including decreases, checks normal and added approval slots against the trusted ledger/attestation, and rejects unauthorized policy/config/exception changes. Git CODEOWNERS approval is required for the relevant directories but is not a substitute for matching a cmapi request to its exact values. A request ID that merely exists is insufficient.
5. At plan time, extra approval has not happened yet. Evaluate against **provisional, in-memory candidate exceptions** pinned to the plan's exact values so valid requests can reach approval. Mark them proposed; never publish them or report approval complete. The worker publishes the identical exception only after all slots are satisfied. CI on an approval PR validates the published/approved artifact. A malicious hand edit cannot reuse the provisional path. Plan/commit changes revalidate hashes and expire stale approval.
6. Apply exceptions before the changed object (separate Argo policy/exception Application with a health barrier before namespace sync, not a sync wave assumed to order unrelated Applications). Revoke/replace old exceptions after the new state is healthy. Delete obsolete exceptions with the namespace. Preserve an approval ID as a separate immutable audit reference; last-change request IDs may legitimately change on unrelated later edits (`render/manifests.py:206`).

Measured in `exception_probe.py`: PVC 30 instead of custom default 20 fails with the annotation alone. With an exact-spec exception it returns skip, exit 0; PVC 31 fails, another namespace fails, and CPU 40 still fails the separate dev bounds policy even with the exception passed. JSON names the exception (`override-exception.log`). The CLI supports this offline, but live exception flags, allowed namespace and RBAC are **not tested here**. An intentional skip is success only if it names an expected, authorized exception in the bundle manifest; an unknown skip is an error.

A cluster-admin who can change policy/exception resources can bypass either design. That is the platform trust boundary. Restricting annotation writes alone does not solve it; an identity-based admission gate on managed RQ/LR writes and canonical Namespace system fields is a useful complement. Offline object validation cannot establish the identity/approval history; that remains trusted Python/CI input.

**Previously approved values:** existing code intentionally grandfathers unchanged approved custom values even after bounds lower or a key becomes non-overridable (`tiers.py:431`, `:459`; `pipeline.py:275`). Preserve this with a separate, generated **grandfather record** from trusted approved history, pinned to object identity, key, quantity and old approval/catalog hash. Compile an exact disjunct for that value into the affected bound/key rule, or use a separately scoped per-key bounds exception only for that previously approved value. Never let a new request create such a disjunct from its own annotation, and never exempt ordering or structural validity. Changing that value is checked against current bounds and adds new approval. Avoid `oldObject == newObject` alone: an attacker could pre-seed bad state and have it grandfathered. The probe does **not** implement or measure grandfather rollout; this is required before replacement policies can ship without violating #214 behavior. A hard-bounds shrink PR must inventory existing approved values and include its generated grandfather artifacts.

## Q6 — trusted environment is the deployment scope

Choose a policy per environment deployed **only to that environment's clusters**, extending the `env/prod/` model. Bounds constants are compiled from the cluster registry's trusted environment, not `object.metadata.labels["cmapi.net/env"]`. A self-writable label would let an attacker select prod's 128-CPU ceiling on a dev cluster. An admission policy cannot establish its own trust by checking a label against another label on the same object.

Keep `cmapi.net/env` for display and add a consistency check against the compiled environment on Namespaces. Quota/LR do not currently carry that label (`tiers.py:614`), which is another reason not to dispatch bounds by it. A per-cluster metadata overlay checks cluster-derived keys against a configured constant. A label change cannot select a different deployed policy.

Plan time gets environment from the selected registered cluster (`pipeline.py:318` shows this for deletes; the create/update planner similarly uses the registry), and CI maps `clusters/<id>/…` using the protected cluster registry, not object labels or PR-supplied mode claims. Admission has only the one correct environment bundle. A mixed-environment cluster would require a platform-controlled namespace-to-environment assignment and a new design; the current cluster registry assigns one environment per cluster. Do not deploy every environment's policy to every cluster with label selectors.

Current source shipping needs attention: docs/02:1915 promises a policy source pinned by tag in each cluster root Application; the actual sample `examples/cluster-configs/clusters/OCP_GF15/argocd/root-application.yaml:14` has **only** `clusters/OCP_GF15/namespaces`, recurse true. It does not actually apply `policies/`. Complete the bootstrap with a separate policies Application (platform-owned project allowed to write policies, not the team namespace AppProject), sourcing exactly `policies/generated/env/dev/` and any cluster identity overlay, plus a restricted exceptions Application. Keep the namespace Application reading namespace folders. Do not point a recursive Argo source at the entire policies root: metadata config, tests and all other environments are not Kubernetes manifests to apply. Environment off must remove/prune the previous source's resources.

## Q7 — generation, agreement, publication and module design

### Layout and ownership

```text
cmapi/src/cmapi/core/policygen/
    __init__.py           # orchestration and Bundle API
    model.py              # RuleSpec/RuleRegistry/BundleSnapshot
    metadata.py           # MetadataKeys -> object rules
    tiers.py              # TierCatalog -> bounds, equality, ordering rules
    messages.py           # descriptors -> CEL and Python detail templates
    approval.py           # trusted approved record -> exact PolicyException
    reports.py            # strict JSON report -> Findings
    templates/            # resource-kind/match skeletons; no environment constants
cmapi/tests/core/test_policygen_agreement.py
cmapi/policies/tests/     # independent fixtures/mutation cases, no live lookups
cluster-configs/
    policies/metadata-keys.yaml           # configuration, not applied as a CR
    policies/generated/env/<env>/        # only Kubernetes policy YAML
        metadata.yaml
        namespace-env.yaml
        quota-bounds.yaml
        limit-bounds.yaml
        quota-tier-values.yaml
        limit-tier-values.yaml
        deny-expiry.yaml                 # prod only
    policies/generated/clusters/<id>/    # identity/derived-cluster overlay when required
    policies/exceptions/<cluster>/<ns>/  # approved exact exceptions, separate authority
    policy-lock/<instance>/manifest.json # input SHAs, compiler version, policy SHA, rule map, modes
    policy-tests/<instance>/             # kyverno Test manifests and resources, not synced
    config/<instance>/                   # reviewed tiers/instance/approval config snapshot or immutable refs
    clusters/<id>/argocd/                # bootstrap sources with explicit env paths + immutable revision
```

Use the actual instance layout when wiring config paths; the tree's `config/<instance>` above is a proposed colocated source snapshot, not an assertion it already exists. `examples/config/tiers.yaml` is the combined reference; instances have their own served environments. Catalog constants belong in generated output in **cluster-configs**, not a single organization-specific copy baked in an image. The image carries compiler/templates, CLI v1.20.0 and its checksum/version, and test/reference bundles for image self-test only. API/worker load the exact committed bundle snapshot (mounted/fetched by hash) and config snapshot; generate it in memory to verify agreement. Do not validate against image fallback policies while admitting with a different bundle. No generated production policy needs to be duplicated inside the image.

The configuration owner edits tiers/metadata/mode through a reviewed config PR. The bot runs the compiler and opens/updates its normal PR with generated output, lock manifest, fixtures/results and bootstrap revision updates. CI regenerates and requires byte agreement, then runs unit and Kyverno tests on the exact proposed head. After review/merge, tag the immutable bundle revision and update each cluster's policy source pin through the normal reviewed path. The API reports the hash/tag it validates against and refuses to silently activate a new policy-bearing config before its matching bundle is published and healthy on the target cluster. On a config reload, stage/validate/compile all inputs, reject the whole candidate on error and keep the previous snapshot (`config.py:15`); do not swap metadata, catalog and policy one at a time.

A template/compiler code change follows the same path even when config is unchanged. No generation at cluster admission and no mutation of reviewed object specs. Namespace request PRs include only approved per-request exception artifacts plus their object changes, not arbitrary edits to the generic policy bundle. Separate privileged Git authority prevents the namespace bot from freely weakening all policies.

### Public interfaces (proposed production API)

```python
@dataclass(frozen=True)
class BundleScope:
    instance: str
    environment: str
    cluster_id: str | None = None

@dataclass(frozen=True)
class BundleSnapshot:
    files: Mapping[str, str]          # relative path -> exact UTF-8 bytes
    manifest: Mapping[str, object]    # input hashes, modes, CLI/compiler version, policy hash and rule registry
    digest: str

def compile_rules(config: InstanceConfig, scope: BundleScope) -> tuple[RuleSpec, ...]: ...
def render_bundle(config: InstanceConfig, scopes: Sequence[BundleScope]) -> BundleSnapshot: ...
def assert_agreement(config: InstanceConfig, bundle: BundleSnapshot) -> None: ...
def compile_approved_exceptions(records: Sequence[ApprovedOverride], bundle: BundleSnapshot) -> Mapping[str, str]: ...
def provisional_exceptions(plan: Plan, bundle: BundleSnapshot) -> Mapping[str, str]: ...
def parse_report(stdout: str, stderr: str, exit_code: int, *,
                 manifest: Mapping[str, object], mode: str,
                 resource_paths: Mapping[tuple[str, str, str, str], str]) -> list[Finding]: ...
```

`ApprovedOverride` is a trusted record containing cluster, namespace, GVK/name, tier, key/value set, request ID, plan hash, input/bundle hash and verified approvals; raw object annotations cannot construct one. `RuleSpec` carries both validation semantics and message fields. `assert_agreement` checks complete paths/bytes and manifest inputs, including obsolete file removal; matching only a catalog-hash annotation is insufficient.

Integration: `load_instance` keeps its existing `PolicySettings.parse`, `MetadataKeys` and `TierCatalog` paths (`config.py:85–116`), then builds/stages a bundle with them. `context.py:97` passes the immutable snapshot/provider into `CliValidator`, replacing its unrestricted `rglob('*.yaml')` of arbitrary config files. Validator uses manifest policy paths for **exact environment/cluster**, invokes policy report JSON on every rendered resource kind, and supplies authorized/provisional exceptions as appropriate. Keep `validate(files, cluster_id, environment) -> list[Finding]` stable; add the bundle and request-evaluation context to construction or a typed evaluation argument rather than teaching callers to forge exception files. The worker uses the same snapshot digest captured in the plan and validates final PR-head content; a changed relevant bundle/config/base requires replan or explicit revalidation and renewed approval if facts changed.

Kubeconform still runs first for every non-deleted rendered document. The validator must include ResourceQuota, LimitRange and each document in multi-document SA/RoleBinding files, not only filenames ending `namespace.yaml`. Use the report's GVK/namespace/name plus an index to recover the real file path; the temporary flattened path is not a user-facing path. Matching one aggregate policy against one object gives one result even with many validations; `validationIndex` identifies the reported failing expression. Do not assume policy count equals number of constraints. `wrong-kind-human.log` measures a quota policy applied to a Namespace: it says `Applying 1 policy rule(s)` but returns all-zero counts and exit 0. With JSON report mode, stdout is empty (not even a JSON report), also exit 0. Therefore the original zero-rule text guard alone cannot prove a resource was checked; use the manifest kind/coverage matrix and nonempty applicable results as well.

### Agreement tests and policy test coverage

The executable code is `experiments/generator.py`; the agreement test is `experiments/agreement_test.py`, reproduced below. It uses the **real existing loaders**, not a second YAML merge implementation. It compares committed policy output, deliberately changes `rnd` CPU max from 32 to 24 (dev inherits it), proves stale output fails, and runs the compiled new policy at CPU 24, 25, 24000m and 24500m. It verifies both verdict and changed maximum/offending value in the message. A deliberate negative invocation exits with `AssertionError: dev quota policy is stale; regenerate with the reviewed configuration` (`agreement-deliberate-stale.log`). Production should repeat this mutation for each configuration field family, environment inheritance, metadata enum/domain/pattern/limits, resolved tier values and mode, with the same byte-agreement test over the entire generated tree.

`experiments/test_matrix.py` writes actual `cli.kyverno.io/v1alpha1` Test manifests, policies, resources and expected outcomes under `experiments/tests/`. Each uses `isValidatingPolicy: true`; results are keyed by policy and resource identity. `test-case-ledger.json` records what each case tests. The original matrix has 122 cases: company required/derived/enum/pattern/prefix/count/UTF-8 limits, default metadata email and optional patterns, every dev quota bound/missing/negative/malformed/off-step value, every current LimitRange bound, ordering, duplicate type, tier-default equality and all three prod expiry keys including empty values. A configured optional unconstrained extra label has no value violation to invent: presence/absence pass and Kubernetes syntax is a schema concern. The non-overcommit rule gets independent synthetic hugepages/extended-resource tests; normal native ephemeral-storage defaults may differ.

Required production additions (not falsely claimed measured here): URL corpus; unsupported regex/glob diagnostics; request-vs-controller write identity fixtures; all environments/tiers and grandfather records; arbitrary catalog key-set/shape changes; protected DELETE; tampered approval ledger/provenance; off with no binary; startup missing/mismatched CLI; audit evaluation errors; zero matched rules; unknown/unauthorized exception; original head/base retry; multi-document resource attribution; Argo source selection, prune/off, readiness and exception rollout. Existing core tests cover the #213 missing/off/audit wrapper behaviors (`test_policy_modes.py:73–106`), and the new agreement test covers mode-generated actions. The expanded matrix additionally executes every resolved named/custom tier in every environment, along with dynamic Context and tight-exception cases; the final run totals are recorded below. Service tests are intentionally not run in this design task.

### Runnable core status

The complete core is pasted later and saved as Python. It measures current company/default metadata, all current dev bounds, tier defaults, LimitRange order/shape and prod expiry. It **is a prototype, not a drop-in production compiler**. Not yet implemented: a byte-stable BundleSnapshot/registry/hash manifest, URL translator, full regex dialect validation, trusted identity admission gates, arbitrary future extra resource/part shape equality, automatic grandfather exceptions, publisher/Argo lifecycle and portal integration. `exact_exception` demonstrates exact-spec pinning but lacks production approval record verification; never call it on untrusted input in a service. Its namespace/name/tier are pinned and its policy ref fixes the targeted family; production adds explicit GVK/cluster/approval provenance and stable audit annotations. The code only uses known custom tier name `custom`; production should derive the unique custom tier from `ResolvedTier.custom`.

The finite step enumeration is measured; its maximum size of 4096 is a prototype safeguard requiring an explicit alternate exact translator for larger domains. `tier_values_policy` verifies configured values and allowed-part/resource sets for current LimitRanges. Production must generalize this to arbitrary future shapes and verify semantic equality and Kubernetes normalization at admission; raw quantity-string equality is insufficient. Extra-resource behavior therefore remains an explicitly unmeasured implementation gap. A checked-in example passing the saved tests is not proof of all the production requirements in this paragraph.

## Q8 — compatibility ledger

| Today's behavior and evidence | Disposition |
|---|---|
| require-team-metadata is v1 ValidatingPolicy, Deny; CREATE/UPDATE, all Namespace objects; presence of team, cluster-id labels and team-dl annotation (`cmapi/policies/require-team-metadata.yaml:1`) | Keep v1/type/operations and the default required keys; actions become configured. Company config replaces team/DL keys intentionally. Preserve structural cluster-id requirement separately. |
| Presence-only rule permits **empty strings**, does not check email/domain/team syntax and emits one static message | Change: generated stanza rules require nonempty required values and check configured rules. This closes the difference from existing Python metadata validation (`metadata.py:277`). `old-metadata.log` measures empty values passing today. Messages become parameterized. |
| No managed-label selector, namespace exemption or delete rule in either existing file | Preserve scope of the existing metadata/prod-expiry rules. Do not claim existing protected-delete behavior. Any platform namespace exclusions need a reviewed explicit rule; do not silently add a mutable `managed=true` selector that a caller can remove. |
| Prod policy denies presence of expires-at annotation, expiry label, cleanup TTL label, including empty; CREATE/UPDATE; fixed message; identical example behavior | Keep the three keys, presence semantics, operations and prod-only deployment; generate the text/actions. Both production and example copies are exercised (`old-prod.log`, `example-prod.log`). |
| No quota or LimitRange rule in today's actual hand-written files, despite docs/02:1281 | Add generated tier/bounds/order/default policies; record this as new enforcement. Do not claim behavior preserved for an absent rule. |
| `CliValidator.__init__` scans every `*.yaml` recursively (`validate/__init__.py:43`) | Change to manifest-selected generated CRs, exact env/cluster paths; exclude metadata config, test fixtures and lock files. Empty enabled bundle is configuration error. |
| Empty/deleted files ignored; no live files returns no findings (`:57`) | Keep. Deletion authorization/protected namespace is a separate Python/DELETE path, not a CREATE manifest check. |
| Temporary file flattening; default 60-second subprocess timeout; captured stdout/stderr (`:41`, `:53`, `:61`) | Keep bounded execution and original path mapping; convert timeout/launch failures into explicit retriable unavailable/config errors, not crashes or fabricated policy violations. |
| Kubeconform strict, summary, JSON, all live files; optional schema location/K8s version; maps filenames (`:76`) | Keep all options and actual file attribution. |
| Missing kubeconform -> source cmapi error; unreadable output -> cmapi error; invalid/schema error -> finding; nonzero with no findings -> error (`:76–98`) | Keep. Audit does not downgrade cmapi/schema infrastructure failures. |
| Schema download failure raises ValidatorUnavailable; pipeline returns 503/retryAfter 60 (`:92`, `pipeline.py:264`) | Keep. An unavailable check is not a refusal verdict. |
| Off skips only Kyverno; engine none requires no binary; Python+kubeconform continue (`:68`, `policy.py:31`) | Keep; generator/CI/admission pruning now completes off behavior. |
| Enabled env missing Kyverno at startup raises PolicyEngineMissing; missing at runtime source cmapi error (`:48`, `:104`) | Keep. Also verify pinned version at startup, rather than accepting any executable on PATH. |
| Audit changes source kyverno findings to warnings; source cmapi stays error (`:71`) | Keep for actual violations. Change for compiler/context/zero-rule/evaluation failures: classify infrastructure errors separately so audit cannot hide them. |
| `_kyverno` runs only `*namespace.yaml`; no namespace file returns nothing (`:101`) | Change: validate all supported kinds/docs to enforce generated quota/LR rules; require matching-policy coverage where expected. |
| env/prod paths run only in prod; prod currently sees all non-prod paths too (`:106`) | Keep prod-expiry restriction; change selection to exactly the registered environment. Other env directories must never leak into prod. |
| Each policy is applied separately to each Namespace, no cluster flag (`:110`) | Keep offline semantics; permit batching by applicable kind for process efficiency and parse reports per resource. No live lookup. |
| Text `Applying 0 policy rule` is a failure, even on CLI exit 0 (`:112`) | Keep explicitly, plus manifest/coverage/report-empty checks for JSON mode, which suppresses the human preamble. v1.20 applies the supplied v1 policies. |
| Nonzero exit OR missing literal `fail: 0` is failure; last line, 300 chars is detail (`:114–116`) | Replace brittle summary parsing with strict JSON results, whole expanded message and validation-index rule mapping. Nonzero errors still fail closed in enabled modes; intentional authorized exception skips are allowed. |
| Findings have source/rule/file/message and feed policy-violation errors; severity controls refusal (`pipeline.py:266`) | Keep RFC 9457 outer behavior and errors[] attribution. Add structured rule fields/hash without silently changing unrelated problem codes. |
| Claimed image/worker exact PR-head check (`validate` module docstring) | Preserve intent and bind bundle/config hash as well as manifest head. This export/design did not run the service or external Git checks. |

## Risks and owner questions

1. **Live rollout is unmeasured.** Exact CLI agreement does not prove webhook transport failures, defaulting, RBAC, Argo prune or exceptions deployment. Require an isolated platform integration exercise later; do not use the shared service PostgreSQL for this task.
2. **Grandfathering is required for parity.** Bounds tightening, catalog key removal and exceptions must be reconciled from trusted approvals before turning on new checks. An annotation is not enough. Is the owner comfortable with preserving old approved values exactly, as current #214 code does, while new values use current bounds? The design preserves it by default.
3. **Policy authority and scope.** Which platform-controlled identity/namespace can publish exceptions, and do any current clusters host multiple environments? The design assumes one registered environment per cluster and a dedicated exception namespace. Tenant writers must not edit policies/exceptions. Global Namespace rules currently apply to platform Namespaces too; platform-specific exclusions must be explicit and reviewed if needed. New quota policies similarly need a reviewed management scope: avoid using a removable managed label as the only guard.
4. **CEL parity and budget.** Regex dialects, URL parsing, quantity normalization/step enumeration, Unicode and added LR resource types need conformance and cost tests. Exact string equality is not quantity equality. The measured milli-CPU edge case is a release-test regression requirement.
5. **Approval publication.** Exception-before-object ordering, revocation and new-bundle readiness must gate writes; an asynchronous config watch alone cannot guarantee equal enforcement at all three points. Need platform agreement on a separate privileged policy/exception publishing role and health barrier.
6. **Network approvals.** Preserve low network-exposure bounds and #211 facts. Confirm the group that supplies the additional network/platform approval; do not broaden NetworkPolicy or arbitrary RBAC overrides in this change.

No owner decision is needed to establish that dynamic context works offline, that audit mode needs wrapper logic, or that annotation-only approval is forgeable: those are resolved here. The remaining questions affect deployment authority, migration and platform scope.

### Proposed documentation replacements

Replace docs/02:1281 with: “The Kyverno bundle is generated from the same validated tier catalog and metadata configuration that cmapi uses. It contains resolved values and environment bounds, so plan time, PR CI and admission evaluate the same immutable bundle. Python keeps the validation required when Kyverno is off, plus cross-object, authority and approval checks.” Amend “Policy in one place” to describe shared rule descriptors and both Python/CEL consumers; #213 requires Python safety even without the CLI. Replace the recursive policy-root bootstrap sketch with explicit per-environment policy sources and off/prune behavior. These are proposed text changes in this design, not changes to the external live document.

## Complete generated examples and actual CLI transcripts

These are the **complete final YAML documents**, not sketches or omitted validations. Company metadata uses the owner’s company file and a trusted `rnd` environment; the dev quota policy uses inherited resolved bounds. The quota document is the bounds layer; pair it with the separate tier-default equality policy and authorized exception layer described above. These examples are unchanged files from the saved experiment, not manually rewritten policy YAML.

### Company metadata (`experiments/generated/company-metadata.yaml`)

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: cmapi-rnd-metadata
spec:
  failurePolicy: Fail
  validationActions:
  - Deny
  matchConstraints:
    resourceRules:
    - apiGroups:
      - ''
      apiVersions:
      - v1
      operations:
      - CREATE
      - UPDATE
      resources:
      - namespaces
  validations:
  - expression: (("company.net/app-environment" in variables.labels && variables.labels["company.net/app-environment"]
      != "")) && (("company.net/app-environment" in variables.labels && variables.labels["company.net/app-environment"]
      == "rnd"))
    message: 'metadata.label.company.net/app-environment: company.net/app-environment:
      set by cmapi from the environment'
    messageExpression: '"metadata.label.company.net/app-environment: company.net/app-environment:
      set by cmapi from the environment; actual=" + json.marshal(("company.net/app-environment"
      in variables.labels ? variables.labels["company.net/app-environment"] : "<missing>"))'
  - expression: (("company.net/cl" in variables.labels && variables.labels["company.net/cl"]
      != "")) && (variables.labels["company.net/cl"] in ["0","1","2","3"])
    message: 'metadata.label.company.net/cl: company.net/cl: one of [''0'', ''1'',
      ''2'', ''3'']'
    messageExpression: '"metadata.label.company.net/cl: company.net/cl: one of [''0'',
      ''1'', ''2'', ''3'']; actual=" + json.marshal(("company.net/cl" in variables.labels
      ? variables.labels["company.net/cl"] : "<missing>"))'
  - expression: (("company.net/lob" in variables.labels && variables.labels["company.net/lob"]
      != "")) && (variables.labels["company.net/lob"] in ["amgsst"])
    message: 'metadata.label.company.net/lob: company.net/lob: one of [''amgsst'']'
    messageExpression: '"metadata.label.company.net/lob: company.net/lob: one of [''amgsst''];
      actual=" + json.marshal(("company.net/lob" in variables.labels ? variables.labels["company.net/lob"]
      : "<missing>"))'
  - expression: (("company.net/mnemonic" in variables.labels && variables.labels["company.net/mnemonic"]
      != "")) && (variables.labels["company.net/mnemonic"].matches("^(?:^[a-z]{3}$)$"))
      && (object.metadata.name.startsWith(variables.labels["company.net/mnemonic"]
      + "-"))
    message: 'metadata.label.company.net/mnemonic: company.net/mnemonic: must match
      ^[a-z]{3}$; the start of the namespace name, before its first ''-'''
    messageExpression: '"metadata.label.company.net/mnemonic: company.net/mnemonic:
      must match ^[a-z]{3}$; the start of the namespace name, before its first ''-'';
      actual=" + json.marshal(("company.net/mnemonic" in variables.labels ? variables.labels["company.net/mnemonic"]
      : "<missing>"))'
  - expression: '!("company.net/mnemonic-confluence" in variables.labels) || (true)'
    message: 'metadata.label.company.net/mnemonic-confluence: company.net/mnemonic-confluence:
      any value'
    messageExpression: '"metadata.label.company.net/mnemonic-confluence: company.net/mnemonic-confluence:
      any value; actual=" + json.marshal(("company.net/mnemonic-confluence" in variables.labels
      ? variables.labels["company.net/mnemonic-confluence"] : "<missing>"))'
  - expression: '!("company.net/mnemonic-group-contact" in variables.labels) || (true)'
    message: 'metadata.label.company.net/mnemonic-group-contact: company.net/mnemonic-group-contact:
      any value'
    messageExpression: '"metadata.label.company.net/mnemonic-group-contact: company.net/mnemonic-group-contact:
      any value; actual=" + json.marshal(("company.net/mnemonic-group-contact" in
      variables.labels ? variables.labels["company.net/mnemonic-group-contact"] :
      "<missing>"))'
  - expression: (("name" in variables.labels && variables.labels["name"] != "")) &&
      (("name" in variables.labels && variables.labels["name"] == object.metadata.name))
    message: 'metadata.label.name: name: set by cmapi from the namespace'
    messageExpression: '"metadata.label.name: name: set by cmapi from the namespace;
      actual=" + json.marshal(("name" in variables.labels ? variables.labels["name"]
      : "<missing>"))'
  - expression: variables.labelsOther.all(k, (!k.contains('/') || (k.contains('/')
      && k.split('/')[0].matches("^.*\\.company\\.net$"))))
    message: 'metadata.label.prefix: other key prefixes allowed: ['''', ''*.company.net'']'
    messageExpression: '"metadata.label.prefix: other key prefixes allowed: ['''',
      ''*.company.net'']; actual=" + json.marshal(variables.labelsOther)'
  - expression: size(variables.labelsTeam) <= 50
    message: 'metadata.label.count: at most 50 other labels'
    messageExpression: '"metadata.label.count: at most 50 other labels; actual=" +
      json.marshal(size(variables.labelsTeam))'
  - expression: (("company.net/app-environment" in variables.annotations && variables.annotations["company.net/app-environment"]
      != "")) && (("company.net/app-environment" in variables.annotations && variables.annotations["company.net/app-environment"]
      == "rnd"))
    message: 'metadata.annotation.company.net/app-environment: company.net/app-environment:
      set by cmapi from the environment'
    messageExpression: '"metadata.annotation.company.net/app-environment: company.net/app-environment:
      set by cmapi from the environment; actual=" + json.marshal(("company.net/app-environment"
      in variables.annotations ? variables.annotations["company.net/app-environment"]
      : "<missing>"))'
  - expression: variables.annotationsOther.all(k, (!k.contains('/') || (k.contains('/')
      && k.split('/')[0].matches("^.*\\.company\\.net$"))))
    message: 'metadata.annotation.prefix: other key prefixes allowed: ['''', ''*.company.net'']'
    messageExpression: '"metadata.annotation.prefix: other key prefixes allowed: ['''',
      ''*.company.net'']; actual=" + json.marshal(variables.annotationsOther)'
  - expression: size(variables.annotationsTeam) <= 50
    message: 'metadata.annotation.count: at most 50 other annotations'
    messageExpression: '"metadata.annotation.count: at most 50 other annotations;
      actual=" + json.marshal(size(variables.annotationsTeam))'
  - expression: variables.annotationsTeam.all(k, size(bytes(variables.annotations[k]))
      <= 4096)
    message: 'metadata.annotation.value-bytes: at most 4096 UTF-8 bytes per other
      annotation'
    messageExpression: '"metadata.annotation.value-bytes: at most 4096 UTF-8 bytes
      per other annotation; actual=" + json.marshal(variables.annotationsTeam.map(k,
      size(bytes(variables.annotations[k]))))'
  - expression: variables.annotationsTeam.map(k, size(bytes(variables.annotations[k]))).sum()
      <= 65536
    message: 'metadata.annotation.total-bytes: at most 65536 UTF-8 value bytes in
      other annotations'
    messageExpression: '"metadata.annotation.total-bytes: at most 65536 UTF-8 value
      bytes in other annotations; actual=" + json.marshal(variables.annotationsTeam.map(k,
      size(bytes(variables.annotations[k]))).sum())'
  - expression: '"cmapi.net/cluster-id" in variables.labels && variables.labels["cmapi.net/cluster-id"]
      != ""'
    message: 'metadata.cluster-id: cmapi.net/cluster-id must be present and nonempty'
    messageExpression: '"metadata.cluster-id: cmapi.net/cluster-id must be present
      and nonempty; actual=" + json.marshal(variables.labels[?"cmapi.net/cluster-id"].orValue("<missing>"))'
  variables:
  - name: labels
    expression: object.metadata.?labels.orValue({})
  - name: labelsOther
    expression: variables.labels.filter(k, ! (k in ["cmapi.net/beyond-tier","cmapi.net/cluster-id","cmapi.net/env","cmapi.net/expires-at","cmapi.net/expiry","cmapi.net/instance","cmapi.net/managed","cmapi.net/protected","cmapi.net/request-id","cmapi.net/requested-by","cmapi.net/requested-by-user","cmapi.net/tier","cmapi.net/tier-hash","company.net/app-environment","company.net/cl","company.net/lob","company.net/mnemonic","company.net/mnemonic-confluence","company.net/mnemonic-group-contact","company.net/provisioner","name"])
      && !((k.contains('/') && k.split('/')[0].matches("^kubernetes\\.io$")) || (k.contains('/')
      && k.split('/')[0].matches("^.*\\.kubernetes\\.io$")) || (k.contains('/') &&
      k.split('/')[0].matches("^k8s\\.io$")) || (k.contains('/') && k.split('/')[0].matches("^openshift\\.io$"))
      || (k.contains('/') && k.split('/')[0].matches("^.*\\.openshift\\.io$")) ||
      (k.contains('/') && k.split('/')[0].matches("^argocd\\.argoproj\\.io$")) ||
      (k.contains('/') && k.split('/')[0].matches("^.*\\.kyverno\\.io$")) || (k.contains('/')
      && k.split('/')[0].matches("^redhatcop\\.redhat\\.io$"))))
  - name: labelsTeam
    expression: variables.labelsOther.filter(k, (!k.contains('/') || (k.contains('/')
      && k.split('/')[0].matches("^.*\\.company\\.net$"))))
  - name: annotations
    expression: object.metadata.?annotations.orValue({})
  - name: annotationsOther
    expression: variables.annotations.filter(k, ! (k in ["cmapi.net/beyond-tier","cmapi.net/cluster-id","cmapi.net/env","cmapi.net/expires-at","cmapi.net/expiry","cmapi.net/instance","cmapi.net/managed","cmapi.net/protected","cmapi.net/request-id","cmapi.net/requested-by","cmapi.net/requested-by-user","cmapi.net/tier","cmapi.net/tier-hash","company.net/app-environment"])
      && !((k.contains('/') && k.split('/')[0].matches("^kubernetes\\.io$")) || (k.contains('/')
      && k.split('/')[0].matches("^.*\\.kubernetes\\.io$")) || (k.contains('/') &&
      k.split('/')[0].matches("^k8s\\.io$")) || (k.contains('/') && k.split('/')[0].matches("^openshift\\.io$"))
      || (k.contains('/') && k.split('/')[0].matches("^.*\\.openshift\\.io$")) ||
      (k.contains('/') && k.split('/')[0].matches("^argocd\\.argoproj\\.io$")) ||
      (k.contains('/') && k.split('/')[0].matches("^.*\\.kyverno\\.io$")) || (k.contains('/')
      && k.split('/')[0].matches("^redhatcop\\.redhat\\.io$"))))
  - name: annotationsTeam
    expression: variables.annotationsOther.filter(k, (!k.contains('/') || (k.contains('/')
      && k.split('/')[0].matches("^.*\\.company\\.net$"))))
```

### Dev quota bounds (`experiments/generated/dev-quota-bounds.yaml`)

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: cmapi-dev-quota-bounds
spec:
  failurePolicy: Fail
  validationActions:
  - Deny
  matchConstraints:
    resourceRules:
    - apiGroups:
      - ''
      apiVersions:
      - v1
      operations:
      - CREATE
      - UPDATE
      resources:
      - resourcequotas
  validations:
  - expression: variables.tier in ["small","medium","large","custom"]
    message: 'quota.tier: tier offered in dev: [''small'', ''medium'', ''large'',
      ''custom'']'
    messageExpression: '"quota.tier: tier offered in dev: [''small'', ''medium'',
      ''large'', ''custom'']; actual=" + json.marshal(variables.tier)'
  - expression: variables.tier != "custom" || (has(object.spec.hard) && "persistentvolumeclaims"
      in object.spec.hard && (isQuantity(object.spec.hard["persistentvolumeclaims"])
      && quantity(object.spec.hard["persistentvolumeclaims"]).compareTo(quantity("0"))
      >= 0 && quantity(object.spec.hard["persistentvolumeclaims"]).compareTo(quantity("100"))
      <= 0))
    message: 'bounds.persistentvolumeclaims: persistentvolumeclaims in dev: min=0,
      max=100, step=any'
    messageExpression: '"bounds.persistentvolumeclaims: persistentvolumeclaims in
      dev: min=0, max=100, step=any; actual=" + json.marshal((has(object.spec.hard)
      && "persistentvolumeclaims" in object.spec.hard ? object.spec.hard["persistentvolumeclaims"]
      : "<missing>"))'
  - expression: variables.tier != "custom" || (has(object.spec.hard) && "pods" in
      object.spec.hard && (isQuantity(object.spec.hard["pods"]) && quantity(object.spec.hard["pods"]).compareTo(quantity("0"))
      >= 0 && quantity(object.spec.hard["pods"]).compareTo(quantity("10")) >= 0 &&
      quantity(object.spec.hard["pods"]).compareTo(quantity("300")) <= 0 && ["10.000000000","20.000000000","30.000000000","40.000000000","50.000000000","60.000000000","70.000000000","80.000000000","90.000000000","100.000000000","110.000000000","120.000000000","130.000000000","140.000000000","150.000000000","160.000000000","170.000000000","180.000000000","190.000000000","200.000000000","210.000000000","220.000000000","230.000000000","240.000000000","250.000000000","260.000000000","270.000000000","280.000000000","290.000000000","300.000000000"].exists(candidate,
      quantity(object.spec.hard["pods"]).compareTo(quantity(candidate)) == 0)))
    message: 'bounds.pods: pods in dev: min=10, max=300, step=10'
    messageExpression: '"bounds.pods: pods in dev: min=10, max=300, step=10; actual="
      + json.marshal((has(object.spec.hard) && "pods" in object.spec.hard ? object.spec.hard["pods"]
      : "<missing>"))'
  - expression: variables.tier != "custom" || (has(object.spec.hard) && "requests.cpu"
      in object.spec.hard && (isQuantity(object.spec.hard["requests.cpu"]) && quantity(object.spec.hard["requests.cpu"]).compareTo(quantity("0"))
      >= 0 && quantity(object.spec.hard["requests.cpu"]).compareTo(quantity("2"))
      >= 0 && quantity(object.spec.hard["requests.cpu"]).compareTo(quantity("32"))
      <= 0 && ["2.000000000","3.000000000","4.000000000","5.000000000","6.000000000","7.000000000","8.000000000","9.000000000","10.000000000","11.000000000","12.000000000","13.000000000","14.000000000","15.000000000","16.000000000","17.000000000","18.000000000","19.000000000","20.000000000","21.000000000","22.000000000","23.000000000","24.000000000","25.000000000","26.000000000","27.000000000","28.000000000","29.000000000","30.000000000","31.000000000","32.000000000"].exists(candidate,
      quantity(object.spec.hard["requests.cpu"]).compareTo(quantity(candidate)) ==
      0)))
    message: 'bounds.requests.cpu: requests.cpu in dev: min=2, max=32, step=1'
    messageExpression: '"bounds.requests.cpu: requests.cpu in dev: min=2, max=32,
      step=1; actual=" + json.marshal((has(object.spec.hard) && "requests.cpu" in
      object.spec.hard ? object.spec.hard["requests.cpu"] : "<missing>"))'
  - expression: variables.tier != "custom" || (has(object.spec.hard) && "requests.memory"
      in object.spec.hard && (isQuantity(object.spec.hard["requests.memory"]) && quantity(object.spec.hard["requests.memory"]).compareTo(quantity("0"))
      >= 0 && quantity(object.spec.hard["requests.memory"]).compareTo(quantity("4Gi"))
      >= 0 && quantity(object.spec.hard["requests.memory"]).compareTo(quantity("64Gi"))
      <= 0 && ["4294967296.000000000","5368709120.000000000","6442450944.000000000","7516192768.000000000","8589934592.000000000","9663676416.000000000","10737418240.000000000","11811160064.000000000","12884901888.000000000","13958643712.000000000","15032385536.000000000","16106127360.000000000","17179869184.000000000","18253611008.000000000","19327352832.000000000","20401094656.000000000","21474836480.000000000","22548578304.000000000","23622320128.000000000","24696061952.000000000","25769803776.000000000","26843545600.000000000","27917287424.000000000","28991029248.000000000","30064771072.000000000","31138512896.000000000","32212254720.000000000","33285996544.000000000","34359738368.000000000","35433480192.000000000","36507222016.000000000","37580963840.000000000","38654705664.000000000","39728447488.000000000","40802189312.000000000","41875931136.000000000","42949672960.000000000","44023414784.000000000","45097156608.000000000","46170898432.000000000","47244640256.000000000","48318382080.000000000","49392123904.000000000","50465865728.000000000","51539607552.000000000","52613349376.000000000","53687091200.000000000","54760833024.000000000","55834574848.000000000","56908316672.000000000","57982058496.000000000","59055800320.000000000","60129542144.000000000","61203283968.000000000","62277025792.000000000","63350767616.000000000","64424509440.000000000","65498251264.000000000","66571993088.000000000","67645734912.000000000","68719476736.000000000"].exists(candidate,
      quantity(object.spec.hard["requests.memory"]).compareTo(quantity(candidate))
      == 0)))
    message: 'bounds.requests.memory: requests.memory in dev: min=4Gi, max=64Gi, step=1Gi'
    messageExpression: '"bounds.requests.memory: requests.memory in dev: min=4Gi,
      max=64Gi, step=1Gi; actual=" + json.marshal((has(object.spec.hard) && "requests.memory"
      in object.spec.hard ? object.spec.hard["requests.memory"] : "<missing>"))'
  - expression: variables.tier != "custom" || (has(object.spec.hard) && "requests.storage"
      in object.spec.hard && (isQuantity(object.spec.hard["requests.storage"]) &&
      quantity(object.spec.hard["requests.storage"]).compareTo(quantity("0")) >= 0
      && quantity(object.spec.hard["requests.storage"]).compareTo(quantity("2Ti"))
      <= 0))
    message: 'bounds.requests.storage: requests.storage in dev: min=0, max=2Ti, step=any'
    messageExpression: '"bounds.requests.storage: requests.storage in dev: min=0,
      max=2Ti, step=any; actual=" + json.marshal((has(object.spec.hard) && "requests.storage"
      in object.spec.hard ? object.spec.hard["requests.storage"] : "<missing>"))'
  - expression: variables.tier != "custom" || (has(object.spec.hard) && "services.loadbalancers"
      in object.spec.hard && (isQuantity(object.spec.hard["services.loadbalancers"])
      && quantity(object.spec.hard["services.loadbalancers"]).compareTo(quantity("0"))
      >= 0 && quantity(object.spec.hard["services.loadbalancers"]).compareTo(quantity("2"))
      <= 0))
    message: 'bounds.services.loadbalancers: services.loadbalancers in dev: min=0,
      max=2, step=any'
    messageExpression: '"bounds.services.loadbalancers: services.loadbalancers in
      dev: min=0, max=2, step=any; actual=" + json.marshal((has(object.spec.hard)
      && "services.loadbalancers" in object.spec.hard ? object.spec.hard["services.loadbalancers"]
      : "<missing>"))'
  - expression: variables.tier != "custom" || (has(object.spec.hard) && "services.nodeports"
      in object.spec.hard && (isQuantity(object.spec.hard["services.nodeports"]) &&
      quantity(object.spec.hard["services.nodeports"]).compareTo(quantity("0")) >=
      0 && quantity(object.spec.hard["services.nodeports"]).compareTo(quantity("10"))
      <= 0))
    message: 'bounds.services.nodeports: services.nodeports in dev: min=0, max=10,
      step=any'
    messageExpression: '"bounds.services.nodeports: services.nodeports in dev: min=0,
      max=10, step=any; actual=" + json.marshal((has(object.spec.hard) && "services.nodeports"
      in object.spec.hard ? object.spec.hard["services.nodeports"] : "<missing>"))'
  - expression: has(object.spec.hard) && object.spec.hard.all(k, k in ["persistentvolumeclaims","pods","requests.cpu","requests.memory","requests.storage","services.loadbalancers","services.nodeports"])
    message: 'quota.keys: only configured quota keys'
    messageExpression: '"quota.keys: only configured quota keys; actual=" + json.marshal(object.spec.hard)'
  variables:
  - name: tier
    expression: object.metadata.?labels.orValue({})[?"cmapi.net/tier"].orValue("")
```

### Passing and failing resources

`experiments/generated/company-pass.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: abc-rnd
  labels:
    name: abc-rnd
    company.net/app-environment: rnd
    company.net/mnemonic: abc
    company.net/lob: amgsst
    company.net/cl: '1'
    cmapi.net/cluster-id: OCP_GF15
  annotations:
    company.net/app-environment: rnd
```

`experiments/generated/company-fail.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: abc-rnd
  labels:
    name: abc-rnd
    company.net/app-environment: rnd
    company.net/mnemonic: abc
    company.net/lob: amgsst
    company.net/cl: '9'
    cmapi.net/cluster-id: OCP_GF15
  annotations:
    company.net/app-environment: rnd
```

`experiments/generated/dev-quota-pass.yaml`:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: abc-dev-quota
  namespace: abc-dev
  labels:
    cmapi.net/cluster-id: OCP_GF15
    cmapi.net/managed: 'true'
    cmapi.net/tier: custom
  annotations:
    cmapi.net/instance: nonprod
    cmapi.net/request-id: req-212
    cmapi.net/tier-hash: 2a59cdd0a70e
spec:
  hard:
    requests.cpu: '4'
    requests.memory: 8Gi
    pods: '20'
    persistentvolumeclaims: '20'
    requests.storage: 200Gi
    services.loadbalancers: '0'
    services.nodeports: '0'
```

`experiments/generated/dev-quota-fail.yaml`:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: abc-dev-quota
  namespace: abc-dev
  labels:
    cmapi.net/cluster-id: OCP_GF15
    cmapi.net/managed: 'true'
    cmapi.net/tier: custom
  annotations:
    cmapi.net/instance: nonprod
    cmapi.net/request-id: req-212
    cmapi.net/tier-hash: 2a59cdd0a70e
spec:
  hard:
    requests.cpu: '40'
    requests.memory: 8Gi
    pods: '20'
    persistentvolumeclaims: '20'
    requests.storage: 200Gi
    services.loadbalancers: '0'
    services.nodeports: '0'
```

### Commands and output

Executed from the export root. `exit=…` is the captured process return code, added by the experiment recorder.

```text
$ tools/bin/kyverno apply experiments/generated/company-metadata.yaml --resource experiments/generated/company-pass.yaml

Applying 1 policy rule(s) to 1 resource(s)...

pass: 1, fail: 0, warn: 0, error: 0, skip: 0 

exit=0

$ tools/bin/kyverno apply experiments/generated/company-metadata.yaml --resource experiments/generated/company-fail.yaml

Applying 1 policy rule(s) to 1 resource(s)...
policy cmapi-rnd-metadata -> resource /Namespace/abc-rnd failed:
1 - validation metadata.label.company.net/cl: company.net/cl: one of ['0', '1', '2', '3']; actual="9"

pass: 0, fail: 1, warn: 0, error: 0, skip: 0 

exit=1

$ tools/bin/kyverno apply experiments/generated/dev-quota-bounds.yaml --resource experiments/generated/dev-quota-pass.yaml

Applying 1 policy rule(s) to 1 resource(s)...

pass: 1, fail: 0, warn: 0, error: 0, skip: 0 

exit=0

$ tools/bin/kyverno apply experiments/generated/dev-quota-bounds.yaml --resource experiments/generated/dev-quota-fail.yaml

Applying 1 policy rule(s) to 1 resource(s)...
policy cmapi-dev-quota-bounds -> resource abc-dev/ResourceQuota/abc-dev-quota failed:
1 - validation bounds.requests.cpu: requests.cpu in dev: min=2, max=32, step=1; actual="40"

pass: 0, fail: 1, warn: 0, error: 0, skip: 0 

exit=1
```

## Full executable design core

This is the complete measured prototype from `experiments/generator.py`; limitations are listed in Q7. All production integration APIs above remain proposed. No application module has been replaced by this file.

```python
"""Executable design core; no cluster or application mutations. See DESIGN.md for scope."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping
import json, re
from decimal import ROUND_CEILING, ROUND_FLOOR
import yaml
from cmapi.core.metadata import MetadataKeys
from cmapi.core.tiers import TierCatalog, qty
from cmapi.core.policy import PolicySettings


def cel(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


@dataclass(frozen=True)
class Rule:
    id: str
    expression: str
    message: str
    actual: str

    def validation(self) -> dict[str, str]:
        return {'expression': self.expression, 'message': self.id + ': ' + self.message,
                'messageExpression': cel(self.id + ': ' + self.message + '; actual=') + ' + json.marshal(' + self.actual + ')'}


def policy(name: str, resource: str, rules: list[Rule], mode: str,
           variables: list[dict[str, str]] | None = None) -> dict | None:
    if mode == 'off':
        return None
    actions = {'enforce': ['Deny'], 'audit': ['Audit']}[mode]
    if not rules:
        raise ValueError('an enabled policy must contain validations')
    spec = {'failurePolicy': 'Fail', 'validationActions': actions,
            'matchConstraints': {'resourceRules': [{'apiGroups': [''], 'apiVersions': ['v1'],
                'operations': ['CREATE', 'UPDATE'], 'resources': [resource]}]},
            'validations': [r.validation() for r in rules]}
    if variables:
        spec['variables'] = variables
    return {'apiVersion': 'policies.kyverno.io/v1', 'kind': 'ValidatingPolicy',
            'metadata': {'name': name}, 'spec': spec}


def prefix_expr(key: str, patterns: list[str] | tuple[str, ...]) -> str:
    """Match DNS prefix exactly as fnmatchcase for supported configuration globs."""
    # '*' includes dots, so *.company.net excludes bare company.net, as Python does.
    pieces = []
    for p in patterns:
        p = p.rstrip('/')
        if any(c in p for c in '?['):
            raise ValueError('unimplemented prefix glob: ' + p)
        if p == '':
            pieces.append("!" + key + ".contains('/')")
        else:
            pattern = '^' + re.escape(p).replace(r'\*', '.*') + '$'
            pieces.append(f"({key}.contains('/') && {key}.split('/')[0].matches({cel(pattern)}))")
    return '(' + ' || '.join(pieces or ['false']) + ')'


def metadata_policy(keys: MetadataKeys, env: str, mode: str,
                    sources: Mapping[str, str]) -> dict | None:
    rules: list[Rule] = []
    variables = []
    for kind, field in [('label', 'labels'), ('annotation', 'annotations')]:
        alias = 'variables.' + field
        variables.append({'name': field, 'expression': f'object.metadata.?{field}.orValue({{}})'})
        for key, r in sorted(keys.rules[kind].items()):
            value = f'{alias}[{cel(key)}]'
            actual = f'({cel(key)} in {alias} ? {value} : "<missing>")'
            present = f'{cel(key)} in {alias}'
            predicates = []
            if r.required:
                predicates.append(f'({present} && {value} != "")')
            if r.derived:
                expected = 'object.metadata.name' if r.derived == 'namespace' else cel(sources[r.derived])
                predicates.append(f'({present} && {value} == {expected})')
            if r.enum is not None:
                predicates.append(f'{value} in {cel(r.enum)}')
            if r.pattern:
                # Startup must reject regex unsupported by RE2; Python uses fullmatch.
                predicates.append(f'{value}.matches({cel("^(?:" + r.pattern + ")$")})')
            if r.namespace_prefix:
                predicates.append(f'object.metadata.name.startsWith({value} + "-")')
            if r.format == 'email-in-domains':
                predicates.append(f"({value}.matches(\"^[A-Za-z0-9!#$%&'*+/=?^_`{{|}}~.\\\\-]+@[^@]+$\") && "
                                  f'{value}.split("@")[1].lowerAscii() in {cel(keys.email_domains)})')
            if r.format == 'url':
                raise ValueError('URL parser equivalence needs a separately tested translator')
            check = ' && '.join('(' + p + ')' for p in predicates) or 'true'
            if not r.required and not r.derived:
                check = f'!({present}) || ({check})'
            rules.append(Rule(f'metadata.{kind}.{key}', check,
                              key + ': ' + r.text(keys.email_domains), actual))
        # These classes can legitimately exist on rendered/live objects; requester authority is checked in Python/RBAC.
        exempt = sorted(set(keys.rules[kind]) | set(keys.system) | set(keys.operator_only) |
                        (set(keys.adoption_labels) if kind == 'label' else set()))
        reserved = prefix_expr('k', keys.reserved_prefixes)
        allowed = prefix_expr('k', keys.allow_other[kind].prefixes)
        team = f'! (k in {cel(exempt)}) && !{reserved}'
        variables.append({'name': field + 'Other', 'expression': f'{alias}.filter(k, {team})'})
        other = 'variables.' + field + 'Other'
        variables.append({'name': field + 'Team', 'expression': f'{other}.filter(k, {allowed})'})
        team_keys = 'variables.' + field + 'Team'
        rules.append(Rule(f'metadata.{kind}.prefix', f'{other}.all(k, {allowed})',
                          'other key prefixes allowed: ' + str(list(keys.allow_other[kind].prefixes)), f'{other}'))
        limit = keys.allow_other[kind]
        rules.append(Rule(f'metadata.{kind}.count', f'size({team_keys}) <= {limit.max}',
                          f'at most {limit.max} other {field}', f'size({team_keys})'))
        if kind == 'annotation':
            rules.append(Rule('metadata.annotation.value-bytes',
                f'{team_keys}.all(k, size(bytes({alias}[k])) <= {limit.max_value_bytes})',
                f'at most {limit.max_value_bytes} UTF-8 bytes per other annotation', f'{team_keys}.map(k, size(bytes({alias}[k])))'))
            rules.append(Rule('metadata.annotation.total-bytes',
                f'{team_keys}.map(k, size(bytes({alias}[k]))).sum() <= {limit.max_bytes_total}',
                f'at most {limit.max_bytes_total} UTF-8 value bytes in other annotations',
                f'{team_keys}.map(k, size(bytes({alias}[k]))).sum()'))
    # Today's hard-coded cluster-id requirement is renderer structure, independent of company key names.
    rules.append(Rule('metadata.cluster-id',
        '"cmapi.net/cluster-id" in variables.labels && variables.labels["cmapi.net/cluster-id"] != ""',
        'cmapi.net/cluster-id must be present and nonempty',
        'variables.labels[?"cmapi.net/cluster-id"].orValue("<missing>")'))
    return policy('cmapi-' + env + '-metadata', 'namespaces', rules, mode, variables)


def bound_rule(key: str, value: str, lo: str | None, hi: str | None, step: str | None,
               guard: str, env: str) -> Rule:
    tests = [f'isQuantity({value})', f'quantity({value}).compareTo(quantity("0")) >= 0']
    if lo is not None:
        tests.append(f'quantity({value}).compareTo(quantity({cel(lo)})) >= 0')
    if hi is not None:
        tests.append(f'quantity({value}).compareTo(quantity({cel(hi)})) <= 0')
    if step:
        # v1.20 quantity('24000m').isInteger() is false even though compareTo('24') == 0.
        # Enumerate exact multiples inside the finite bounds; never use floating point for modulo.
        st = qty(step)
        if st <= 0 or hi is None:
            raise ValueError('steps require a positive step and finite maximum')
        first = int((qty(lo or '0') / st).to_integral_value(rounding=ROUND_CEILING))
        last = int((qty(hi) / st).to_integral_value(rounding=ROUND_FLOOR))
        if last - first + 1 > 4096:
            raise ValueError('step domain too large for prototype; needs an exact quantity translator')
        domain = [format(st * i, 'f') for i in range(first, last + 1)]
        tests.append(f'{cel(domain)}.exists(candidate, quantity({value}).compareTo(quantity(candidate)) == 0)')
    return Rule('bounds.' + key, guard + ' && (' + ' && '.join(tests) + ')',
                f'{key} in {env}: min={lo or "0"}, max={hi}, step={step or "any"}',
                '(' + guard + ' ? ' + value + ' : "<missing>")')


def quota_bounds(catalog: TierCatalog, env: str, mode: str) -> dict | None:
    b = catalog.bounds(env)
    rules = []
    for key in sorted(set(catalog.sizable + catalog.overridable_quota)):
        value = f'object.spec.hard[{cel(key)}]'
        guard = f'has(object.spec.hard) && {cel(key)} in object.spec.hard'
        rule = bound_rule(key, value, b.min.get(key), b.max.get(key), b.step.get(key), guard, env)
        # Named tiers use their resolved catalog values; custom bounds must not accidentally cap named tiers.
        rules.append(Rule(rule.id, 'variables.tier != "custom" || (' + rule.expression + ')', rule.message, rule.actual))
    offered = [r.name for r in catalog.offered(env)]
    rules.insert(0, Rule('quota.tier', f'variables.tier in {cel(offered)}',
                         'tier offered in ' + env + ': ' + str(offered), 'variables.tier'))
    rules.append(Rule('quota.keys', f'has(object.spec.hard) && object.spec.hard.all(k, k in {cel(sorted(set(catalog.sizable + catalog.overridable_quota)))})',
                      'only configured quota keys', 'object.spec.hard'))
    return policy('cmapi-' + env + '-quota-bounds', 'resourcequotas', rules, mode,
        [{'name': 'tier', 'expression': 'object.metadata.?labels.orValue({})[?"cmapi.net/tier"].orValue("")'}])


def expiry_policy(env: str, mode: str) -> dict | None:
    if env != 'prod': return None
    return policy('cmapi-prod-deny-expiry', 'namespaces', [Rule('expiry.prod',
        '! ("cmapi.net/expires-at" in object.metadata.?annotations.orValue({})) && '
        '! ("cmapi.net/expiry" in object.metadata.?labels.orValue({})) && '
        '! ("cleanup.kyverno.io/ttl" in object.metadata.?labels.orValue({}))',
        'Production namespaces never expire: remove cmapi.net/expires-at, cmapi.net/expiry and cleanup.kyverno.io/ttl',
        'object.metadata')], mode)


def generate(catalog: TierCatalog, keys: MetadataKeys, settings: PolicySettings,
             sources: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    result = {}
    for env in catalog.environments():
        mode = settings.mode_for(env)
        if mode == 'off': continue
        for name, doc in [('metadata', metadata_policy(keys, env, mode, sources[env])),
                          ('quota-bounds', quota_bounds(catalog, env, mode)),
                          ('deny-expiry', expiry_policy(env, mode)),
                          ('limit-bounds', limit_bounds(catalog, env, mode)),
                          ('quota-tier-values', tier_values_policy(catalog, env, mode, 'quota')),
                          ('limit-tier-values', tier_values_policy(catalog, env, mode, 'limit'))]:
            if doc:
                result[f'policies/generated/env/{env}/{name}.yaml'] = yaml.safe_dump(doc, sort_keys=False, width=10000)
    return result


def tier_values_policy(catalog: TierCatalog, env: str, mode: str, kind: str) -> dict | None:
    """Separately exemptible equality policy. A tight exception may skip this, never bounds/order."""
    rules = []
    tier = 'object.metadata.?labels.orValue({})[?"cmapi.net/tier"].orValue("")'
    for r in catalog.offered(env):
        if kind == 'quota':
            expected = r.quota
            checks = [f'{cel(k)} in object.spec.hard && quantity(object.spec.hard[{cel(k)}]).compareTo(quantity({cel(v)})) == 0'
                      for k, v in sorted(expected.items())]
            actual = 'object.spec.hard'
        else:
            expected = r.limit_range
            checks = []
            for k, parts in sorted(expected.items()):
                k8s = {'container':'Container','pvc':'PersistentVolumeClaim'}[k]
                for part in ['min','defaultRequest','default','max']:
                    if part in parts:
                        checks.append(f'object.spec.limits.filter(x, x.type == {cel(k8s)}).all(x, has(x.{part}) && x.{part}.all(k, k in {cel(sorted(parts[part]))}))')
                    else:
                        checks.append(f'object.spec.limits.filter(x, x.type == {cel(k8s)}).all(x, !has(x.{part}))')
                for part, vals in sorted(parts.items()):
                    for res, v in sorted(vals.items()):
                        checks.append(f'object.spec.limits.exists(x, x.type == {cel(k8s)} && has(x.{part}) && '
                            f'{cel(res)} in x.{part} && quantity(x.{part}[{cel(res)}]).compareTo(quantity({cel(v)})) == 0)')
            actual = 'object.spec.limits'
        rules.append(Rule('tier.' + r.name, f'({tier}) != {cel(r.name)} || (' + ' && '.join(checks) + ')',
                          f'{env}/{r.name} {kind} catalog values: ' + cel(expected), actual))
    return policy(f'cmapi-{env}-{kind}-tier-values', 'resourcequotas' if kind == 'quota' else 'limitranges',rules,mode)


def limit_bounds(catalog: TierCatalog, env: str, mode: str) -> dict | None:
    b = catalog.bounds(env)
    rules = []
    for key in catalog.overridable_limits:
        _, kind, part, res = key.split('.')
        k8s = {'container':'Container','pvc':'PersistentVolumeClaim'}[kind]
        value = f'x.{part}[{cel(res)}]'
        guard = f'has(x.{part}) && {cel(res)} in x.{part}'
        r = bound_rule(key,value,b.min.get(key),b.max.get(key),b.step.get(key),guard,env)
        expr = f'variables.tier != "custom" || object.spec.limits.exists(x, x.type == {cel(k8s)} && ({r.expression}))'
        rules.append(Rule(r.id, expr, r.message, 'object.spec.limits'))
    # Check every pair present, including gaps in the chain. Absent min is legal; all configured defaults must exist.
    parts = ['min','defaultRequest','default','max']
    comparisons=[]
    for i, lo in enumerate(parts):
        for hi in parts[i+1:]:
            comparisons.append(f'!has(x.{lo}) || !has(x.{hi}) || x.{lo}.all(k, '
                               f'! (k in x.{hi}) || quantity(x.{lo}[k]).compareTo(quantity(x.{hi}[k])) <= 0)')
    rules.append(Rule('limits.order','object.spec.limits.all(x, ' + ' && '.join('('+s+')' for s in comparisons) + ')',
                      'min <= defaultRequest <= default <= max for each resource', 'object.spec.limits'))
    expected = {k: [r for r in sorted({res for t in catalog.offered(env) for vals in t.limit_range.get(k,{}).values() for res in vals})]
                for k in ['container','pvc']}
    shape = []
    for kind,k8s in [('container','Container'),('pvc','PersistentVolumeClaim')]:
        shape.append(f'object.spec.limits.filter(x, x.type == {cel(k8s)}).size() == 1')
        shape.append(f'object.spec.limits.filter(x, x.type == {cel(k8s)}).all(x, '
            + ' && '.join(f'(!has(x.{part}) || x.{part}.all(k, k in {cel(expected[kind])}))' for part in parts) + ')')
    shape.append('object.spec.limits.all(x, x.type in ["Container","PersistentVolumeClaim"])')
    rules.append(Rule('limits.shape',' && '.join(shape),'one Container and one PVC item; configured resources only','object.spec.limits'))
    # Kubernetes non-overcommittable resource defaults must equal requests (ephemeral-storage, hugepages and extended resources).
    rules.append(Rule('limits.non-overcommit',
        'object.spec.limits.all(x, !has(x.default) || !has(x.defaultRequest) || x.default.all(k, '
        '!(k.startsWith("hugepages-") || (k.contains("/") && !k.contains("kubernetes.io/"))) || !(k in x.defaultRequest) || '
        'quantity(x.default[k]).compareTo(quantity(x.defaultRequest[k])) == 0))',
        'non-overcommittable resources need defaultRequest == default','object.spec.limits'))
    rules.append(Rule('limits.tier',f'variables.tier in {cel([r.name for r in catalog.offered(env)])}',
                      'tier must be offered in ' + env, 'variables.tier'))
    return policy(f'cmapi-{env}-limit-bounds','limitranges',rules,mode,
        [{'name':'tier','expression':'object.metadata.?labels.orValue({})[?"cmapi.net/tier"].orValue("")'}])


def exact_exception(name: str, namespace: str, policy_name: str, resource: Mapping[str, Any]) -> dict:
    """Use only after trusted approval verification; annotation alone is never an approval."""
    m=resource['metadata']
    cond=(f'object.metadata.namespace == {cel(m["namespace"])} && object.metadata.name == {cel(m["name"])} && '
          f'object.metadata.labels["cmapi.net/tier"] == {cel(m["labels"]["cmapi.net/tier"])} && '
          f'object.spec == {cel(resource["spec"])}')
    return {'apiVersion':'policies.kyverno.io/v1','kind':'PolicyException',
        'metadata':{'name':name,'namespace':namespace},'spec':{
        'policyRefs':[{'name':policy_name,'kind':'ValidatingPolicy'}],
        'matchConditions':[{'name':'exact-approved-object','expression':cond}]}}
```

### Full agreement test

`experiments/agreement_test.py`:

```python
from pathlib import Path
import copy, json, subprocess
import pytest, yaml
from generator import quota_bounds, metadata_policy, generate
from cmapi.core.tiers import TierCatalog
from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
ROOT=Path(__file__).resolve().parents[1]
ENVS={'rnd','dev','qa','uat','prod'}
K=ROOT/'tools/bin/kyverno'
RAW=yaml.safe_load((ROOT/'examples/config/tiers.yaml').read_text())

def assert_agrees(raw, rendered):
    catalog=TierCatalog(raw, ENVS)
    # Byte comparison detects changed messages as well as changed predicates.
    expected=yaml.safe_dump(quota_bounds(catalog,'dev','enforce'),sort_keys=False)
    assert rendered == expected, 'dev quota policy is stale; regenerate with the reviewed configuration'

def test_committed_policy_agrees():
    assert_agrees(RAW,(ROOT/'experiments/generated/dev-quota-bounds.yaml').read_text())

def test_company_policy_agrees():
    keys=MetadataKeys.load(ROOT/'examples/cluster-configs/policies/metadata-keys.company.yaml')
    expected=metadata_policy(keys,'rnd','enforce',{'environment':'rnd','cluster':'OCP_GF15','instance':'nonprod'})
    assert yaml.safe_load((ROOT/'experiments/generated/company-metadata.yaml').read_text()) == expected

def test_stale_policy_is_detected():
    raw=copy.deepcopy(RAW)
    raw['environments']['rnd']['custom']['max']['requests.cpu']='24' # dev inherits rnd
    with pytest.raises(AssertionError,match='stale'):
        assert_agrees(raw,(ROOT/'experiments/generated/dev-quota-bounds.yaml').read_text())

def test_changed_configuration_changes_verdict_and_message(tmp_path):
    raw=copy.deepcopy(RAW);raw['environments']['rnd']['custom']['max']['requests.cpu']='24'
    doc=quota_bounds(TierCatalog(raw,ENVS),'dev','enforce')
    pol=ROOT/'experiments/agreement-policy.yaml';pol.write_text(yaml.safe_dump(doc,sort_keys=False))
    resource=yaml.safe_load((ROOT/'experiments/generated/dev-quota-pass.yaml').read_text())
    # Independent boundary expectations, verified by the real engine (not a second template assertion).
    evidence=[]
    for amount,expected in [('24','pass'),('25','fail'),('24000m','pass'),('24500m','fail')]:
        resource['spec']['hard']['requests.cpu']=amount
        res=ROOT/'experiments'/('agreement-resource-'+amount+'.yaml');res.write_text(yaml.safe_dump(resource))
        r=subprocess.run([str(K),'apply',str(pol),'--resource',str(res),'--policy-report','--output-format','json'],capture_output=True,text=True)
        report=json.loads(r.stdout)
        (ROOT/'experiments'/('agreement-'+amount+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        result=report['results'][0]
        assert result['result']==expected
        assert r.returncode == (0 if expected=='pass' else 1)
        if expected=='fail':
            assert 'max=24' in result['message'] and amount in result['message']
        evidence.append({'amount':amount,'expected':expected,'report':report,'exit':r.returncode})
    (ROOT/'experiments/agreement-boundaries.json').write_text(json.dumps(evidence,indent=2)+'\n')

def test_modes_generate_no_off_policy():
    catalog=TierCatalog(RAW,ENVS)
    keys=MetadataKeys.load(ROOT/'examples/cluster-configs/policies/metadata-keys.company.yaml')
    sources={e:{'environment':e,'instance':'sample','cluster':'fixture'} for e in ENVS}
    assert generate(catalog,keys,PolicySettings(engine='none'),sources)=={}
    settings=PolicySettings(default_mode='enforce',environments={'rnd':'audit','dev':'off'})
    docs=generate(catalog,keys,settings,sources)
    assert not any('/dev/' in p for p in docs)
    for path,text in docs.items():
        action=yaml.safe_load(text)['spec']['validationActions']
        assert action == (['Audit'] if '/rnd/' in path else ['Deny'])

if __name__=='__main__':
    import sys
    if '--demonstrate-stale' in sys.argv:
        raw=copy.deepcopy(RAW);raw['environments']['rnd']['custom']['max']['requests.cpu']='24'
        assert_agrees(raw,(ROOT/'experiments/generated/dev-quota-bounds.yaml').read_text())
```

### Report-to-finding adapter core

`experiments/parse_report.py`; tested by `experiments/report_test.py`. This minimal adapter proves message preservation and error/audit handling; production must add manifest index/rule mapping, complete resource identity coverage, approved exception identity checks and input-size limits.

```python
"""Measured report adapter core; production adds manifest/resource identity coverage."""
import json
from cmapi.core.ports import Finding


def parse_report(stdout: str, stderr: str, exit_code: int, *, mode: str,
                 path: str, known_exceptions: frozenset[str] = frozenset()) -> list[Finding]:
    if mode == 'off':
        return []
    if mode not in ('enforce','audit'):
        raise ValueError(mode)
    def error(message):
        return [Finding('cmapi', 'validator', path, message)]
    if 'Applying 0 policy rule' in stdout + stderr:
        return error('policy not understood by the CLI (0 rules applied)')
    try:
        report = json.loads(stdout)
        if report['kind'] not in ('Report','ClusterReport'): raise ValueError('unexpected report kind')
        results = report['results']
        if not isinstance(results,list) or not results: raise ValueError('no results')
        if sum(report['summary'].values()) != len(results): raise ValueError('summary mismatch')
    except (ValueError, KeyError, TypeError, AssertionError):
        return error('Kyverno report unreadable or no applicable rules: ' + (stderr or stdout)[:300])
    out=[]
    violated=False
    for result in results:
        status=result.get('result')
        if status == 'pass': continue
        if status == 'skip' and result.get('properties',{}).get('exceptions') in known_exceptions:
            continue
        if status not in ('fail','warn'):
            return error('Kyverno ' + str(status) + ': ' + result.get('message','unknown evaluation result'))
        violated=True
        # Stable production rule IDs come from policy + validationIndex in the manifest.
        rule=result['policy']+':'+result.get('properties',{}).get('cel.validationIndex',result.get('rule','validation'))
        out.append(Finding('kyverno',rule,path,result.get('message',''),
                           severity='warning' if mode == 'audit' else 'error'))
    if exit_code not in (0,1) or (exit_code != 0 and not violated):
        return error('Kyverno failed without a policy violation: '+str(exit_code)+' '+stderr[:300])
    return out
```

## What was run, results, and reproducibility

All artifacts, scripts, fixtures, dependency records, source snapshots and logs are under `experiments/`. No container, Kubernetes cluster, database, service test or external publication was started. No source under `cmapi/src` or configuration under `examples/` was modified.

The default `python3` had no PyYAML. I created `experiments/venv`, installed PyYAML, pydantic and pytest there, and saved the installer output and observed versions (`dependencies.log`, `requirements-observed.txt`). Those observed native versions differ from the application image's exact dependency pins; this is not a container/image verification. All Kyverno evaluations used the supplied **v1.20.0 darwin binary** (build commit `f666af06e9bd310c7e730f1523c0430e90371a89`), without `--cluster`.

```sh
# Setup (already performed; installer output saved)
python3 -m venv experiments/venv
experiments/venv/bin/python -m pip install PyYAML pydantic pytest

# Behavior probes, preserving their outputs in per-command .log files
experiments/venv/bin/python experiments/probe.py
experiments/venv/bin/python experiments/cel_probe.py
experiments/venv/bin/python experiments/quantity_probe.py
PYTHONPATH=cmapi/src experiments/venv/bin/python experiments/generated_probe.py
PYTHONPATH=cmapi/src experiments/venv/bin/python experiments/exception_probe.py
PYTHONPATH=cmapi/src experiments/venv/bin/python experiments/final_probes.py
experiments/venv/bin/python experiments/coverage_probe.py

# Regenerate the policy tests and supplemental context/exception cases
PYTHONPATH=cmapi/src experiments/venv/bin/python experiments/test_matrix.py
PYTHONPATH=cmapi/src experiments/venv/bin/python experiments/supplemental_tests.py
tools/bin/kyverno test experiments/tests --require-tests
# Final recorded result: 235 tests passed, 0 failed, exit 0 (kyverno-tests.log).

PYTHONPATH=cmapi/src:experiments experiments/venv/bin/python -m pytest \
  experiments/agreement_test.py experiments/report_test.py -q --basetemp=experiments/pytest-tmp
# 12 passed, exit 0 (design-tests.log).

PYTHONPATH=cmapi/src:experiments experiments/venv/bin/python \
  experiments/agreement_test.py --demonstrate-stale
# Expected exit 1; asserts the old rendered policy disagrees with the changed inherited CPU bound.

# Existing core suite, run from cmapi/ only
cd cmapi
PYTHONPATH=src:tests/core ../experiments/venv/bin/python -m pytest tests/core -q
# 227 passed in 6.39 s, exit 0 (../experiments/core-tests.log).
```

`fetch_sources.py` retrieves primary documentation and records SHA-256s; it is a network read, not a cluster operation. `required_examples.py` executes the four displayed apply commands. `finalize.py` assembles this document from the saved code, YAML and transcripts. `timing-*.log` and `timings.json` contain all five static/dynamic timing samples. First-attempt errors and the fixes they motivated are retained in `setup-failures.log`, `company-first-compile-failure.log`, `quota-first-compile-failure.log`, `quantity-sign-failure.log`, `generated-probe-first-failures.log`, `generated-probe-encode-failures.log`, `agreement-first-failure.log`, and `final-probes-first-failure.log`.

Measured: CLI v1 application, exact Context format and missing-context failure, dynamic message/report preservation, ignored action dispositions, current metadata and tier policies, every offered environment/tier equality branch, quantities/steps, expiry presence semantics, tightly scoped exception matching and independent bounds, wrong-kind vacuity, agreement drift detection, report parsing, and the existing native core suite. **Not measured:** live admission (including Kubernetes defaulting), Argo synchronization/prune, exception RBAC, deployment failurePolicy behavior, URL/regex dialect parity beyond these fixtures, grandfather migration, portal/approval integration, service suite or GitHub checks on a repository head. This is an export, not a repository, so no claim is made about GitHub checks or a commit/PR created here.
