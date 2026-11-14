# #212: design 1 of 2 (Opus 5.5 at high, OB1 run 6)

This design was written on 2026-11-14 before the author read the other design (Codex `gpt-6.1-sol`,
`design-codex.md`). The README of this folder arbitrates the two. Each measurement used the Kyverno CLI v1.20.0
(darwin build, `Git commit ID: f666af06e9bd310c7e730f1523c0430e90371a89`) on this Mac, with no cluster (#157). The
files are in `experiments/`.

## What was measured

| # | Run | Result |
|---|---|---|
| M1 | `kyverno apply quota-pol.yaml --resource rq-bad.yaml`: a static ValidatingPolicy with the dev bounds inline, `quantity()` comparisons and a `messageExpression` | `fail: 1`, message `beyond the dev maximum: requests.cpu 40 > 32`. `requests.memory: 65536Mi` is not above `64Gi`, so `quantity()` compares the values, not the text. `rq-ok.yaml`: `pass: 1` |
| M2 | The same policy with `validationActions: [Audit]`, and with `[Audit, Warn]` | Exit 1 and `fail: 1` in each case. The CLI ignores `validationActions`. `--audit-warn` says "Currently has no effect; ValidatingPolicy audit support is tracked by kyverno/kyverno#16485" |
| M3 | `-p --output-format json` | An `openreports.io/v1alpha1` ClusterReport, with one result for each policy and resource. Each result has `policy`, `rule: validation`, `properties["cel.validationIndex"]`, the resource's kind, namespace and name, `result` and `message`. The line "Applying N policy rule(s)" is not printed in this mode |
| M4 | One call with a folder of two policies and three resources (`bundle/`, a ResourceQuota that fails, one that passes, and a Namespace that fails deny-expiry-in-prod) | One report, with 3 results and the right result for each. Today `CliValidator` starts one process for each policy and each file |
| M5 | Two resources with the same kind, namespace and name in one call | The CLI panics (`resourcequotas "quota" already exists`), exit 2, and writes no JSON |
| M6 | `cm-pol.yaml`: the bounds come from a ConfigMap through `resource.Get()` and `yaml.parse()`, with `--context-file ctx.yaml` | It gives the same results as M1 |
| M7 | M6 with no `--context-file` | `error: 1` (`no such key: data`), exit 1. Offline, a missing context is an error, not a pass |
| M8 | `oldObject` and `request.operation` in the CLI (`old-pol2.yaml`) | `op=CREATE`, and `oldObject` has no metadata. The CLI has no flag for an old object |

## Decisions

### D1. Static policies, with the values inline (option a of the issue)

cmapi renders each policy from the configuration, with every value written into the policy as a CEL literal.

- The same file gives the same answer at all three points: at plan time, in CI and at admission (M1, M4). None of
  them reads anything at run time.
- When a configuration value changes, the rendered policy changes. That change is a reviewed Git change, so the
  bundle tag that docs/02 names still identifies exactly what each cluster enforces.
- Option b (a ConfigMap read with `resource.Get()`) works offline only with a context file (M6). It fails as an
  error when the file is missing (M7), which is closed but is a different result than at admission. At admission it
  also needs read access to ConfigMaps for Kyverno, and a ConfigMap that each cluster must have before the policy.
  Then a value can change on one cluster without a change of the bundle tag. docs/02 already decided "Allowlists live
  inside the policies as lists, not as ConfigMap lookups". M6 and M7 confirm that decision, so this design keeps it.

Rejected: option b, and a mix of the two. The owner's "it can change dynamically" is met because cmapi re-renders the
policies when the configuration changes (D7). A person never edits a policy.

### D2. Messages from the same values

- Each validation has a `messageExpression` that names the key, the offending value and the configured value, for
  example `requests.cpu 40 is above the dev maximum of 32; ask for a custom tier with approval`. M1 shows that
  `messageExpression` works offline.
- The configured value enters the message as the same literal that the expression compares. The generator writes it
  once, as a CEL variable, so the policy and its message cannot disagree.
- cmapi reads the JSON report (M3), not the text output. Each failed result becomes one `Finding`: the policy name,
  the file of the resource (matched by kind, namespace and name), and the message. The plan's problem detail and the
  portal show that message unchanged.
- cmapi's own checks of the same rules (`core/metadata.py`, `core/tiers.py`) keep their own messages. The agreement
  test (D7) feeds the same bad values to both and checks that both refuse them. It does not check that the text is
  the same.

### D3. Modes

| Mode of an environment | `validationActions` in its rendered policies | Plan time (cmapi) | CI on the PR |
|---|---|---|---|
| `enforce` | `[Deny]` | A finding refuses the plan | Fails |
| `audit` | `[Audit, Warn]`: a policy report, and a warning to the client (kubectl, Argo CD) | A finding is a warning | Reports, does not fail |
| `off` | No files for that environment | No Kyverno run | No Kyverno step for that environment |

The CLI ignores `validationActions` (M2). So cmapi keeps reading the mode from `instance.yaml` (#213), and CI reads
it from the rendered policy's `validationActions`. A policy whose actions do not contain `Deny` is reported but does
not fail the job.

### D4. Scope: which rules Kyverno checks

A rule goes into Kyverno only when it can be checked on one object, offline, on the full live object. A live object
also carries keys that the platform adds (`kubernetes.io/metadata.name`, `openshift.io/sa.scc.*`, the Argo CD
tracking annotation). So a rule about what a requester may *send* stays in Python.

| Rule | Source | Kyverno | Python |
|---|---|---|---|
| A required label or annotation is present and not empty | `requiredLabels`, `requiredAnnotations` | Yes | Yes (`core/metadata.py`) |
| A declared key's value matches its `pattern`, `enum`, `format` (email-in-domains with `emailDomains`; url) | the stanzas | Yes | Yes |
| `namespacePrefix`: the value is the start of the namespace name | the stanzas | Yes | Yes |
| A derived key equals its source: `namespace` is `object.metadata.name`; `environment` and `instance` are constants of the rendered environment; `cluster` is the label `cmapi.net/cluster-id` | the stanzas | Yes | Yes |
| `cmapi.net/env` equals the environment of the policy's folder | D6 | Yes | Renderer |
| Reserved prefixes, system and operator-only keys, `allowOther` and its limits, adoption labels | the stanzas | No: a live object carries platform keys, and these rules are about the request | Yes |
| Sensitive keys (an extra approver) | `sensitiveKeys` | No: an approval fact | Yes |
| Each quota key at or below the environment's custom maximum (`quantity()`) | `tiers.yaml` `custom.max` and `environments.<env>.custom.max` | Yes | Yes |
| A sizable key at or above the custom minimum, and on its step, when the tier is `custom` | `custom.min`, `custom.step` | Yes, for a ResourceQuota labelled `cmapi.net/tier: custom` | Yes |
| LimitRange: each `limitRange.*` key at or below its maximum; `default` not below `defaultRequest`; `max` not below `default` | `custom.max`, the LimitRange | Yes | Yes |
| `limitRange.container.max.cpu` never above the request's own `requests.cpu` | two objects | No | Yes |
| Each value that differs from the tier is named in `cmapi.net/beyond-tier` | the tiers of the environment, inline | Yes | Yes (renderer) |
| Production namespaces never carry expiry metadata | deny-expiry-in-prod | Yes, rendered for `prod` only | Yes |

The generator refuses a configuration in which an offered named tier is above the environment's maximum, because the
rendered policy would then refuse that tier at admission.

### D5. Approved overrides: the annotation, not a PolicyException

Decision: option a. The ResourceQuota and the LimitRange carry `cmapi.net/beyond-tier` (the renderer already writes
it, #211) and `cmapi.net/request-id`. The policy checks two things: each value is within the environment's bounds,
whatever the annotation says; and each value that differs from the tier is named in the annotation.

- A hand edit in Git cannot get an unapproved value past the PR check. cmapi's check on the PR confirms that the
  request ID is approved and that the PR head matches the plan hash (docs/02, step 4 of the approval flow).
- A person with write access on the cluster can change the annotation, so the annotation does not prove approval at
  admission. The bounds still hold, because no annotation lifts them.
- A PolicyException exempts a resource from all of a policy's validations, not from one value. It is a separate
  object that someone must create and later remove, and Kyverno's own guidance is to restrict who can create one
  (`kyverno-docs/exceptions.md`). It would widen what is allowed, where the annotation only explains it.

Rejected: a PolicyException for each override, and a policy for each namespace.

### D6. The environment at admission: one folder for each environment

Each environment's policies go in `policies/generated/env/<env>/`. Each cluster's root Application includes only the
folder of its own environment, as `env/prod/` works today. The label `cmapi.net/env` is set by the object, so a label
must not choose the bounds. The policy also checks that `cmapi.net/env` equals its folder's environment, which catches
a namespace that claims another environment.

Rejected: one policy for all environments that selects the bounds by the label.

### D7. Where the generator runs, and what proves agreement

- **Module.** `cmapi/src/cmapi/core/policygen/`, a pure function:
  `render_bundle(catalog: TierCatalog, keys: MetadataKeys, policy: PolicySettings, environments: set[str], instance: str) -> dict[str, str]`.
  It returns a map of relative path to YAML text: one file for each rule family and each environment that is not off,
  and a `kyverno-test.yaml` with its resources for each environment.
- **Plan time.** `CliValidator` runs the bundle that cmapi rendered from its own loaded configuration, written to a
  temporary folder, together with the hand-written policies that `policies_dir` still holds. Plan time therefore
  always agrees with the running configuration.
- **cluster-configs.** `cmapi-tools policies render --config-dir … --metadata-keys … --out policies/generated` writes the
  same files. `cmapi-tools policies check` fails when the committed files differ from a fresh render. CI runs the check
  on every pull request.
- **A change of configuration.** On start and on `POST /admin/reload`, cmapi compares its render with
  `policies/generated/env/<env>/` in Git. When they differ, it opens one bot PR, as `tiers-rerender` does for
  namespaces, with the approval of `approver-platform`. The policies therefore follow the configuration with no hand
  edit. This is the second PR of #212. The first PR builds the generator, plan time, the CLI, the check and the tests.
- **Tests.** `tests/core/test_policygen.py`: for each rule, the generator's own `kyverno-test.yaml` cases (one passing
  and one failing resource for each rule, made from the configuration, for example the key's `example` and a value
  outside its `enum`) pass with `kyverno test`. The agreement test changes one configuration value (a bound, an
  `enum`, a pattern), renders again, and checks two things: the old good resource now fails exactly where the value
  moved, and cmapi's Python check refuses the same value.

### D8. Behaviour preserved

| Today | After |
|---|---|
| `require-team-metadata` (hand-written, `cmapi/policies/`): `cmapi.net/team`, `cmapi.net/cluster-id` and `cmapi.net/team-dl` present | Rendered from the stanzas. `cmapi.net/team` and `cmapi.net/team-dl` are required keys. `cmapi.net/cluster-id` is a system key that the renderer always writes, and the generator adds a rule for each system key that the renderer writes on a Namespace. Kept |
| `deny-expiry-in-prod` (hand-written, in both bundles) | Rendered for `prod` only, with the same three keys and the same message. Kept |
| `CliValidator` fails a run with "Applying 0 policy rule(s)" | That line is not printed in the JSON mode (M3). The new guard: a policy that matches a kind among the files must give one result for each such file. Fewer results is a finding "policy not understood by the CLI". Kept in substance |
| A policy under `env/prod` runs only for `prod` | A policy under `env/<env>` runs only for `<env>`. Widened, same rule |
| A missing binary is a cmapi finding | Kept |
| One process for each policy and each file | One process for each plan (M4). Changed, for speed |
| Exit 2, or no JSON (M5) | A cmapi finding (an error in each mode), never a pass. New |

### D9. A value that is already approved is not checked again, at all three points

`TierCatalog._out_of_bounds` (`core/tiers.py`) does not check a value that Git already holds against the bounds again,
so a later, lower bound does not refuse a change of a label on a namespace that was approved before. A rendered
policy has to do the same, or it refuses what cmapi passes:

- **At admission.** Argo CD's sync of an unchanged object is still an UPDATE that admission sees. So each rule is one
  validation for each key, and it passes when `request.operation == 'UPDATE'` and the key's value in `oldObject` is
  the same (a missing key that was also missing counts as the same). This also lets an adopted namespace keep its
  values (#26: findings, never changes) through its first sync, which is an UPDATE.
- **At plan time and in CI.** The CLI always evaluates as CREATE (M8). The generator writes an index next to the
  bundle: for each policy and `cel.validationIndex`, the key, its kind and the rule. cmapi maps each failed result to
  its key through that index (M3 gives the index), and drops a failure on a key whose value is the same in the
  current Git version of the object. CI does the same against the PR's base, with `cmapi-tools policies ci --base`.
  The three points then give the same answer for the same old and new object.

The agreement test covers this case: a value above a lowered bound passes when it is unchanged, and fails when it
changes.

## Risks and open questions

1. **Adoption (#26, PR #239) and admission.** Without D9, a rendered metadata policy in `enforce` would refuse the
   adoption's first sync of a namespace such as the owner's sample (`name: aao-rnd`, two empty values). D9 settles it
   at admission. In CI, an adoption PR has no base version of the file, so the adoption plan's approved findings must
   be the base. That is a point for the adoption design (#239), which the coordinator has.
2. The second PR (the bot PR on a configuration change) depends on the Git path for a file outside
   `clusters/<cluster>/`. That is new for the bot.
3. `cmapi.net/cluster-id` as the source of a `cluster`-derived key at admission is only a consistency check. The
   cluster's own ID is not visible to an admission policy.
