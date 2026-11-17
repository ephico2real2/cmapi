# #333 and #345: the rendered Kyverno policies, the keys that no stanza declares, and the background scan

Step 5 of the #328 plan (`docs/reviews/2026-11-16-issue-328/arbitration.md`). Opus 5.5 (`high`), the implementer, wrote
the code, the tests and this record on 2026-11-17. One model family for this step: Codex is out of quota until
2026-11-18 and Fable is paused by the owner.

The owner's rules for it (2026-11-17): Kyverno audits by default (#342) and is there for the extra detail of its
findings; cmapi's own logic holds every rule and refuses, with or without Kyverno. The portal's Policies tab shows the
clusters' PolicyReport results, so they must be right.

## What was wrong

- **#333.** `MetadataKeys.validate` refuses a key outside the allowed classes (`invalid_key`, "prefix not allowed"), more
  other keys than `allowOther.max` (`too_many_keys`) and annotation values over `maxValueBytes` or `maxBytesTotal`
  (`annotations_too_large`). The rendered policies checked only the declared keys, so a namespace changed outside cmapi
  was held to none of these. On main 31e0794 the bundle was byte-identical for `allowOther.prefixes` `["", "*.ephico2real.com/"]`,
  `["*"]` and `[]` (the issue's measurement).
- **#345.** Each declared-key policy and each bound keeps a value that the namespace already holds, through `oldObject`
  at admission. A background scan builds its request as a CREATE with no `oldObject` and no user
  (`pkg/controllers/report/utils/scanner.go`, the `celengine.Request(..., admissionv1.Create, authenticationv1.UserInfo{},
  &resource, nil, ...)` call at lines 142-155 of v1.20.0), so it reported each kept value as `fail`.

## What changed

| Where | Change |
|---|---|
| `core/policygen.py` `_other_key_checks` | For labels and for annotations: `cmapi-metadata-<env>-<kind>-other-keys-prefix` fails on a key that `classify` calls `disallowed`, `...-other-keys-max` on more other keys than `allowOther.max`. For annotations: `...-max-value-bytes` and `...-max-bytes-total`, in UTF-8 bytes (`size(bytes(v))`), as `validate` counts them (`len(v.encode())`). Each message names the keys (sorted) and the setting |
| `core/policygen.py` `_under`, `_written` | The globs are `metadata._glob_regex`, the loader's own regex of a glob, not a second version. The keys that the renderer writes come from one render of the renderer itself |
| `core/policygen.py` `Check.reads_old`, `_policy` | A policy whose validation reads `oldObject` or `variables.update` gets `evaluation.background.enabled: false` (#345). Read from the CEL itself, so a check cannot gain the ratchet and keep the scan |
| `core/policygen.py` `policy_name` (#356, found on kind) | A policy name over 63 characters becomes its first characters and 8 hex digits of its SHA-256. Kyverno labels each report `vpol.kyverno.io/<policy name>` (`pkg/utils/report/metadata.go`, `PolicyLabel`), and a label's name part is at most 63 characters (Kubernetes, "Labels and Selectors", syntax and character set), so one longer name made the API server refuse the background scan's report of every resource. A shorter name is unchanged; 14 of the 156 names of the example bundle change |
| `examples/cluster-configs/policies/env/*` | Re-rendered with `cmapi-tools policies render` for nonprod, staging and prod |
| `docs/18-configuration.md`, `docs/02-technical-design-v2.md` | The new policies, the classes the object may hold, the background setting |

`core/metadata.py` is not changed: `_glob_regex` is imported from it as it is.

## The decisions

### Which keys the policies allow on the object

The policies mirror `classify(key, kind)` in its order: a `system` key, an `operatorOnly` key, an adoption label (labels),
a declared key of that kind, then a reserved prefix, then an `allowOther` prefix. Only `disallowed` fails. A system,
operator-only or reserved key is allowed on the namespace: cmapi's renderer writes the system keys and Argo CD's
`argocd.argoproj.io/sync-options`, an operator's approved request writes `cmapi.net/protected`, and the platform writes
the rest (the API server's `kubernetes.io/metadata.name`, OpenShift's `openshift.io/sa.scc.*`). The object does not say
who wrote a key, and at admission the requester is Argo CD's service account, so "a requester may not send it" stays
cmapi's own check (`reserved_key`, `operator_only_key`), as docs/02 said before ("What stays in Python").

So a controller that writes keys outside `reservedPrefixes` gets a report. OLM's operator-group label, for example, is
`olm.operatorgroup.uid/<uid>` (`OperatorGroupLabelPrefix = "olm.operatorgroup.uid/"`,
<https://pkg.go.dev/github.com/operator-framework/api/pkg/operators/v1>): an OpenShift site lists that prefix in
`reservedPrefixes` (docs/18 says so).

The keys that the renderer writes are allowed and never counted whatever the file calls them: `validate` never sees
them, so counting one would refuse what cmapi accepts. They are read from a render (`_written`), so a site whose `system`
list leaves out `cmapi.net/instance`, or whose reserved prefixes leave out Argo CD's, still gets a bundle that passes
what cmapi renders (`test_the_keys_that_the_renderer_writes_are_allowed_whatever_the_file_calls_them`).

The bounds of each set lean the safe way: the allowed set uses the wider regex of a glob (`exact=False`), and the counted
set uses the exact or narrower regex of an `allowOther` glob and the wider one of a reserved glob, so the policies never
refuse or count a key that `validate` admits or does not count.

A key that `classify` reads as having no prefix (none, or a leading `/`) is admitted only by `""`, as #331 decided.
`/foo` is refused by cmapi (#330) and by the API server (`IsLabelKey`) before any admission webhook, so the policies
read it as `classify` does and do not repeat the syntax check: a key that Git holds from before #330 can still be kept.

### No ratchet for the other keys

The prefix, count and byte policies do not keep a value through `oldObject`, and they keep the background scan. cmapi
does not keep these either: the pipeline carries only governed and team keys from Git (`plan_namespace`, `cur_l`), so
a disallowed key is dropped at the next change, and `validate` counts the limits on the result, so an over-limit
namespace is refused at its next change. A `fail` for them is a true report.

### #345: `evaluation.background.enabled: false` on each policy that reads `oldObject`

| Option | Verdict |
|---|---|
| **`evaluation.background.enabled: false` on the policies whose verdict reads `oldObject`** | **Chosen.** The CRD of v1.20.0: "Enabled controls if rules are applied to existing resources during a background scan ... The value must be set to "false" if the policy rule uses variables that are only available in the admission review request (e.g. user name)." The docs (Policy Reports): "Policies relying on admission-only information ... must disable background evaluation." It fixes the cause: the scan no longer evaluates a rule whose meaning needs the previous object. Each policy carries one check, so this is per rule |
| A CEL guard that skips the kept-value rules in a scan | Rejected: a scan and the CLI build the same request (CREATE, `oldObject` nil, empty `UserInfo`; `cmd/cli/kubectl-kyverno/processor/policy_processor.go`, `AdmissionRequestShape` and `celengine.Request`), and cmapi's CLI run passes no `--userinfo`. A guard that skips the scan would skip cmapi's plan-time check too. Guessing from an empty `request.userInfo.username` would be a heuristic on an undocumented detail |
| `background: false` on every policy | Rejected: the other-key policies, the LimitRange order and `deny-expiry-in-prod` do not read `oldObject`, and their scan finds a namespace that drifted or predates the bundle |
| Mark a kept value in the result, for the Policies tab to tell it apart | Rejected as the fix: the result's `process` property is set from the policy's settings, not from the run (`pkg/utils/report/results.go`, `selectProcess`), so a result does not say whether a scan or an admission made it, and every value that a namespace holds is "kept" by cmapi's definition (the previous version in Git holds it). Kept as a later choice for the Policies tab: listing held values from Git, which cmapi can read |

What it means for the PolicyReport: the reports controller keeps one result per policy and resource, the latest by
timestamp (`pkg/controllers/report/aggregate/utils.go`, `MergeReports`, `mergeLatestResult`). A ratcheted policy's result
is the one of the latest admission: `pass` for a value that was valid when admitted or that an UPDATE kept, `fail` for a
value that was new and broke the rule. A namespace that no admission has seen under the bundle has no result from these
policies; cmapi's plan lists a held key until a request fixes it (#26). A missing required key that a later configuration
added is held the same way: it is a plan finding, not a PolicyReport failure.

Sources, read on 2026-11-17 (the code at tag v1.20.0, commit f666af06e9bd, cloned to the workbench):

- `pkg/controllers/report/utils/scanner.go`, `ScanResource`: the scan's request, and `filterMatchConditionSkips`.
- `config/crds/policies.kyverno.io/policies.kyverno.io_validatingpolicies.yaml`: `evaluation.background.enabled`.
- `pkg/cel/policies/filter.go`, `RemoveNoneBackgroundPolicies`, used by `pkg/controllers/report/background/controller.go`.
- `cmd/cli/kubectl-kyverno/processor/policy_processor.go`: the CLI's request, which does not filter on the setting
  (measured: the v1.20.0 CLI evaluates a policy with `background.enabled: false`).
- `pkg/controllers/report/aggregate/utils.go` and `controller.go` (`backReconcile`): the merge of admission and scan results.
- `pkg/utils/report/results.go`, `selectProcess`.
- Kyverno, Policy Reports: <https://kyverno.io/docs/policy-reports/>.
- Kyverno, ValidatingPolicy: <https://kyverno.io/docs/policy-types/validating-policy/>.

## Measured

### The agreement (#333)

`tests/core/test_policygen_coverage_333.py::test_each_map_that_the_rendered_policies_refuse_cmapi_refuses`, on this Mac
with the Kyverno CLI v1.20.0, on the corpus of #328 (`metadata_corpus.cases`) and its six configurations. Each case's
Namespace is the one cmapi renders (held equal to `ManifestRenderer.render` on every 250th case); a patch drops a failure
on a key whose value the previous version holds, with cmapi's own `_held`. "Before" is the same test with main
31e0794's `core/policygen.py` (`-o pythonpath=tests/core`, so pytest's `src` does not shadow it).

| Configuration | Maps | cmapi refuses | Kyverno refuses, before | Kyverno refuses, after | Both | Kyverno only | Codes of the maps that cmapi alone refuses (after) |
|---|---|---|---|---|---|---|---|
| `reference` | 12,079 | 10,998 | 563 | 6,428 | 6,428 | 0 | invalid_key 1570, invalid_value 969, operator_only_key 203, reserved_key 1828 |
| `company` | 12,544 | 11,122 | 618 | 6,490 | 6,490 | 0 | derived_key 264, invalid_key 1158, invalid_value 1200, operator_only_key 191, reserved_key 1819 |
| `company-f2` | 12,540 | 11,385 | 618 | 6,006 | 6,006 | 0 | derived_key 264, invalid_key 1910, invalid_value 1195, operator_only_key 191, reserved_key 1819 |
| `star` | 12,071 | 8,427 | 563 | 2,482 | 2,482 | 0 | invalid_key 2092, invalid_value 1822, operator_only_key 203, reserved_key 1828 |
| `star-and-none` | 12,083 | 7,851 | 563 | 715 | 715 | 0 | invalid_key 3096, invalid_value 2009, operator_only_key 203, reserved_key 1828 |
| `globs` | 12,057 | 10,423 | 563 | 7,064 | 7,064 | 0 | invalid_key 51, invalid_value 1084, operator_only_key 203, reserved_key 2021 |

Kyverno refused no map that cmapi accepts, before or after. A map counts once under each of its codes, so the codes add up to more than the maps. What cmapi alone refuses, broken down for `reference` in
`evidence/cmapi-only-reference.txt`: a key or a label value that Kubernetes refuses before admission (`invalid_key` with
a team-class key, `invalid_value` "not a valid label value"), who sent a key (`reserved_key` for system and reserved keys,
`operator_only_key`), a derived key with another value (the renderer writes the right one), and a removal (`null`) of a
key that the namespace does not hold, which leaves nothing on the object. Logs: `evidence/agreement-before.jsonl`,
`evidence/agreement-after.jsonl`. `validate()` takes no policy setting, so cmapi refuses the same set with
`policy.engine: none`; `tests/service/test_metadata_other_keys_333_api.py` proves it through the API for one body of each
new rule (CI's `service` job).

The tests, before and after:

| Test | main 31e0794 | After |
|---|---|---|
| `test_policygen_coverage_333.py` (16, run against main's generator) | 7 failed (the three #345 bundles, the new rules' messages, the 422's Kyverno finding, `foo` and `/foo` under `["*"]`); 9 passed (the agreement, which held on main's narrower bundle, and the two "allowed" checks) | 16 passed |
| `test_each_policy_name_fits_kyvernos_report_label` (#356) | `policy_name` absent; 3 of the 25 names of `env/dev` are over 63 | passed |
| `tests/service/test_metadata_other_keys_333_api.py` (4) | passes on main too: cmapi refused these bodies already; it guards `engine: none` | CI `service` |
| The related core tests (`test_policygen`, `test_review_212`, `test_config_repo_ci`, `test_limitrange_split`, `test_fable_review_240`/`245`, `test_policy_modes`, `test_review_255`, `test_metadata_pattern_subset_332`) | | 227 passed |

### On the `cmapi-test` kind cluster

kind v0.33.0 on Podman, node `kindest/node:v1.35.8`, Kyverno v1.20.0 from the release's `install.yaml` (SHA-256 in
`evidence/kind/install.yaml.sha256`; the release's `checksums.txt` lists only the CLI archives). The dev bundle of the
reference keys, audit. The inputs come from `evidence/kind/gen.py`, the run from `evidence/kind/proof.sh`; outputs in
`evidence/kind/`. The cluster was deleted after.

| Step | Result |
|---|---|
| main 31e0794's bundle | The reports controller cannot write the background scan's report of `payments-dev`: `metadata.labels: Invalid value: "vpol.kyverno.io/cmapi-limits-dev-limit-limitrange-container-default-memory-order": name part must be no more than 63 bytes` (`main-31e0794-report-refused.log`). Filed and fixed here as #356 |
| #345 before: the branch's bundle without `evaluation.background` | `payments-dev` created with `cmapi.net/cost-center: cc-4410` (pass), then the rule tightened to `^cc-[0-9]{5}$` in place: the background scan reports `fail`, "the label cmapi.net/cost-center is "cc-4410"; it must be: must match ^cc-[0-9]{5}$" (`before.log`) |
| #345 after: the branch's bundle | `orders-dev` created the same way, the rule tightened: the scan ran (the other-key policies' results are newer), and the cost-center result stays `pass` from admission (`after.log`) |
| The upgrade path | `payments-dev`'s `fail` from the scan stays after the fixed bundle is applied, until the next admission: `kubectl label namespace payments-dev cmapi.net/app=billing`, an UPDATE that keeps `cc-4410`, turns it to `pass` (`outside.log`) |
| #333: a change outside cmapi | `kubectl label namespace orders-dev other.example/x=1 cmapi.net/team=orders`: admitted with `Warning: Policy cmapi-metadata-dev-label-other-keys-prefix failed: the label keys other.example/x are not declared in metadata-keys.yaml, and are outside extraLabels.allowOther.prefixes ["", "*.ephico2real.com/"]`; the PolicyReport holds that `fail` with the same message (from the scan), and `cc-4410`, kept by the UPDATE, `pass` (`outside.log`) |

## Not tested

- CRC and OpenShift: not run. The OLM label is from the operator-framework source, not from a cluster.
- Argo CD applying a namespace: not run; admission was driven with `kubectl apply` and `kubectl label`.
- The `enforce` mode on the cluster: the proof ran in audit, the default.
- The Policies tab of the portal (#302) reading these reports: not run.
- #355 (found here, filed, not fixed): the renderer writes `y`, `Y`, `n` and `N` unquoted, so kubectl, the Kyverno CLI
  and (inferred) Argo CD read them as booleans. With #333 such a team annotation makes the byte policies fail to evaluate
  at plan time (a cmapi error), where on main the namespace would fail later at sync. The agreement test writes JSON, so
  it measures the policies against `validate()` and not this renderer defect.
