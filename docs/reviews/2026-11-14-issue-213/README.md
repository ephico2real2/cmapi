# #213: Kyverno optional, a mode for each environment, and the CLI at v1.20.0

OB1 run 6 (Opus 5.5 at high) wrote the code, the tests and this record on 2026-11-14. Fable reviews it later.

## The owner's decisions

- 2026-11-13: "we should be able to enable or disable kyverno, and also have two modes (enforcing or audit). the cmapi
  would work with or without kyverno though."
- 2026-11-13: the clusters run the latest Kyverno with the `policies.kyverno.io/v1` policy types; the CLI pin moves to
  match, to the exact patch, and a later patch is a reviewed bump (#213's comment).

## Decisions

| Question | Decision | Why |
|---|---|---|
| Where the setting lives | `policy` in `instance.yaml` (chart value `instance.policy`): `engine`, a default `mode`, and `environments` | The issue's shape. One instance file, so a change of mode is one reviewed change |
| No `policy` key | Kyverno enforces in each environment (superseded on 2026-11-17 by #342: audit, below) | cmapi's behaviour before #213; no instance changes behaviour |
| What audit does at plan time | Each Kyverno finding becomes a warning; the request goes on to approval | The issue. The pipeline already lets warnings through and lists them on the plan; `warnings` is a fixed guard of auto-approval (`core/approvals.py`), so an approver sees each one |
| A missing binary | A start error when a served environment runs Kyverno; a finding of cmapi (an error in every mode) when it disappears later | The issue: "a configuration error at startup, not a refusal of every request". An image that loses its binary must not pass plans in audit |
| What off does | No Kyverno run; kubeconform and cmapi's own checks run | The issue. cmapi's own checks never depended on Kyverno |
| The policy types | `policies.kyverno.io/v1` for the policies of `cmapi/policies/` and `examples/cluster-configs/policies/` | The owner. The v1.20 CLI applies their rules (measured below). The "0 rules applied" guard stays |
| `examples/local/` | Unchanged (`v1beta1`, Kyverno 1.16.2 pinned in its `run.sh`) | It is the older local demo stack with its own pin; with `v1` its 1.16 CLI would apply 0 rules |
| CODEOWNERS for the instance file | Not added | The repository is on a personal account with no branch protection (#227), so GitHub would not enforce a code owner's review. docs/02 states the review rule |
| The rendered policies' `validationActions` | Not here: #212 renders them from the mode | The policies are hand-written until #212's generator |

## Measured

The Kyverno CLI v1.20.0 (darwin build, `ob1-run5/tools/bin/kyverno`, its tarball's SHA-256 equal to the release's
`checksums.txt`), with cmapi's own `CliValidator`, on this Mac, on a namespace in `prod` that misses the team keys and
carries `cmapi.net/expiry`:

| Mode | Kyverno findings |
|---|---|
| enforce | `deny-expiry-in-prod` (error), `require-team-metadata` (error) |
| audit | the same two, each a warning |
| off | none, and no kyverno run |

A namespace with the team keys and no expiry: no finding. No run reported "Applying 0 policy rule(s)". The linux build's
SHA-256 in `cmapi/Containerfile` (`06b8f3ca...942e2`) is the release's `checksums.txt` entry for
`kyverno-cli_v1.20.0_linux_x86_64.tar.gz`; v1.20.0 was published 2026-11-12 (`gh release view v1.20.0 -R kyverno/kyverno`).

| Test | Before (main) | After |
|---|---|---|
| `cmapi/tests/core/test_policy_modes.py` (15: defaults, modes, bad settings, each mode with stub binaries, the start check, a binary missing while planning) | fails at import (no `core/policy.py`) | 15 passed |
| `cmapi/tests/service/test_policy_modes_api.py` (enforce refuses; audit sends to approval with the warning; off plans and submits with no binary and is auto-approved by the dev rule; the integrations endpoint and the metric; the chart passes the setting) | fails | see the pull request |

`test_the_charts_rendered_config_loads_with_the_real_adapters` (`test_review_h_tools_migrate.py`) puts a stub `kyverno`
on PATH: the chart's default enforces Kyverno, the image holds the binary, and the start check now needs one.

Not measured: the image build (no container, #157), a cluster's admission with the v1 types (kind and CRC wait on #157).

## Sources, read on 2026-11-14

- Kyverno policy types: <https://kyverno.io/docs/policy-types/overview/> ("All policy types below use
  `policies.kyverno.io/v1`"), as quoted on #213 by the coordinator.
- Kyverno v1.20.0 release and its `checksums.txt`: <https://github.com/kyverno/kyverno/releases/tag/v1.20.0>.
- OB1 run 5's measurements of the v1.20.0 CLI (`workbench/cmapi/ob1-run5/kyverno-exp/`): it applies v1 rules,
  `messageExpression` works offline, and `validationActions` is ignored by the CLI, so cmapi's mode turns a finding into
  a warning itself.

## Fable's review

Fable 5.2 reviewed PR #240 at `0248031` (`fable-review.md`). It found three defects, and the coordinator accepted all three.
They are applied unchanged, with Fable's tests (`tests/core/test_fable_review_240.py`, 8 failed before, and
`tests/service/test_fable_review_240.py`):

| # | Finding | Fix |
|---|---|---|
| F1 (high) | In audit, the PR check failed and closed the PR of a request that was approved with its warning | The PR check fails only on an error; it reports an audit warning, as the cluster's Audit action does |
| F2 | In audit, a policy that would not compile or evaluate, and the "0 rules applied" guard, became warnings | They are cmapi findings, errors in each mode |
| F3 | An unquoted `mode: off` is YAML's boolean false and stopped the start | false is the mode off |

Filed from the review: #249, about audit on the GitHub external-CI path. The workflow of the configuration repository
must report and not fail (Wave 3).

## 2026-11-17: audit by default (#342)

The owner, 2026-11-17: "Kyverno should be in audit mode. The core logic like we said should be in the cmapi core logic
itself." (On #213, 2026-11-13: "the cmapi would work with or without kyverno though.") Opus 5.5 wrote the change, with one
model family.

| Question | Decision | Why |
|---|---|---|
| No `policy` key, or no `mode` | Each environment audits (`DEFAULT_MODE`, `core/policy.py`); a bad `mode` falls back to audit while the start stops | The owner. `enforce` and `off` stay, per environment |
| The rendered policies in audit | `validationActions: [Audit, Warn]`, as #212 rendered audit | The v1.20.0 CRD: "Audit" records the failure "in the created reports", "Warn" reports it "to the request client in HTTP Warning headers", and "Deny" and "Warn" "may not be used together". `[Audit]` alone was rejected: it drops the warning that Argo CD and `oc` show, and gains nothing |
| Who refuses | cmapi's own checks (names, tiers and bounds, metadata keys) in every mode and with `engine: none` | The owner. They ran before Kyverno already; this change keeps them first |
| A metadata refusal and Kyverno | The refused body is still rendered and validated, and the 422 lists the validator's findings in `findings` beside cmapi's `errors`; anything that fails after the refusal leaves the refusal as it was | The issue: "with the Kyverno warning listed beside it". A refusal before the render (name, tier) has no `findings` |
| cmapi's findings about Kyverno itself | Errors in every mode, unchanged (F2 above) | The issue |
| `ci/kyverno` of cluster-configs (`kyverno_check.py`) | Audit is no `Deny` in `validationActions` (#343) | It took only `[Audit]` as audit, so cmapi's `[Audit, Warn]` failed the PR; its test had rewritten `Deny` to `[Audit]` by hand and hid it |
| The `warnings` guard of auto-approval (`core/approvals.py`, `FIXED_GUARDS`) | Kept | With cmapi's checks complete, a Kyverno warning on a body that cmapi passes means Kyverno is stricter than cmapi: a hand-written policy of `/etc/cmapi/policies` that cmapi does not model, or a disagreement that #333's agreement test must catch. The cluster will report the namespace either way, so a person approves it. Removing the guard would auto-approve what the clusters' PolicyReports show as failing. The fallback is counted (`cmapi_auto_approval_fallbacks_total{guard="warnings"}`) |

Options rejected: keep `enforce` as the default (the owner's decision); `engine: none` by default (the owner wants Kyverno
in audit, and the clusters' PolicyReports feed the portal's Policies tab); drop the `warnings` guard (above).

What audit changes for a hand edit: a hand edit of cluster-configs that bypasses the API (for example an expiry on a prod
namespace) is reported in CI and at admission, not refused, unless the environment's mode is `enforce`. cmapi treats a prod
namespace as permanent whatever it carries (`ExpirationRules.state`). An instance that wants Kyverno to refuse hand edits sets
`enforce` for those environments.

Sources, read on 2026-11-17:

- The ValidatingPolicy CRD of Kyverno v1.20.0, `config/crds/policies.kyverno.io/policies.kyverno.io_validatingpolicies.yaml`
  at the tag `v1.20.0` of <https://github.com/kyverno/kyverno>: `validationActions` is a required set of `Deny`, `Audit` and
  `Warn`, with the definitions quoted above; `evaluation.background.enabled` defaults to true.
- Kyverno, Policy Reports: <https://kyverno.io/docs/policy-reports/>: "A ValidatingPolicy with `validationActions: [Audit]`
  allows a non-compliant resource to be created and records the failure in a report", and "Reports can contain results from
  admission processing and from background scans".
- Kubernetes, ValidatingAdmissionPolicy: <https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/>,
  "Validation actions", which Kyverno's field follows: `[Warn, Audit]` is the documented pair for warning and auditing.

Not measured: a cluster's admission and PolicyReport with the Audit bundle (no kind or CRC run in this change).
