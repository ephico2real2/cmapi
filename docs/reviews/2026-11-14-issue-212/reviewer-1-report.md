# Reviewer 1 — cmapi #212 rendered admission bundle

Reviewed export `c67a8f4e9bd72c3f72282864737bddb580d1291e` and `change.diff`, under the README arbitration. Findings refer to the original export; candidate fixes, complete code, before/after tests and CLI evidence are in `review/`. The working source and rendered examples contain the candidate fixes; original files are preserved in `review/original/`.

## Findings

### F1 [P1] Encode non-BMP strings as CEL Unicode scalars (C5)

`cmapi/src/cmapi/core/policygen.py:56`: `json.dumps` defaults to ASCII escaping. A YAML annotation enum containing `😀` is valid configuration, but becomes `"\ud83d\ude00"`; the pinned CLI refuses the policy with `invalid unicode code point`. This prevents the bundle from compiling. Quotes, backslashes, BMP text and newlines passed the same probe. Evidence: `review/probe.py`, `review/probe.log`, `review/probes/literal-2.yaml` (CLI exit 1). Fix and regression test follow below.

## Execution and constraints

- TokenSave context/status/read attempted: this export has no initialized graph; direct source reads used instead, without indexing another folder.
- `tools/bin/kyverno version`: v1.20.0, commit f666af06e9bd310c7e730f1523c0430e90371a89.
- Requested system `python3 -m pytest tests/core -q`: could not start, because system Python has no pytest. Created `.review-venv` locally and installed native test dependencies; these are not the image's pinned Python dependencies.
- `PYTHONPATH=cmapi/src .review-venv/bin/python review/probe.py`: real offline CLI literal probes above. No container, cluster, database or service tests.

### F2 [P2] Quote configured text in message expressions (C5)

`policygen.py:152` inserts `said` into a CEL single-quoted literal. A declared annotation derived from instance and instance `owner's instance` makes the bundle fail compilation. Instance names are read without syntax validation (`core/config.py:65-66,116`). `:133,186-187,209-210` similarly interpolate environment and bound text. Bounds are quantity-validated, keys are syntax-validated, but that is not literal encoding. `test_configured_instance_is_quoted_in_messages` fails before the fix; real CLI stderr is retained under `review/before/`.

### F3 [P2] Governed label syntax differs between Python and the rendered bundle (C4)

`policygen.py:154-172`: shipped `cmapi.net/team: aa-` and `cmapi.net/app: -aa` pass the generated pattern policy; Python rejects them through `metadata.py:305-307`. The pattern itself permits both values. These are actual shipped-configuration counterexamples, measured by the CLI. Kubernetes would also reject these label values, so this is a checker-agreement defect rather than an admission bypass of Kubernetes syntax checks. Tests: `test_shipped_label_value_agreement` (2 failures).

### F4 [P2] URL rules implement a different acceptance set (C4)

`policygen.py:118-119`: Go's URL parser rejects `https://example.com/%zz`, which Python's stated scheme/authority/whitespace rule accepts. Conversely, CEL `\\s` is ASCII and accepts a non-breaking space in `https://example.com/a\u00a0b`, which Python's `isspace()` rejects. Tests add a supported URL annotation rule to the company configuration and measure both counterexamples through the real CLI (`test_url_rule_agreement`, 2 failures). Fix the generated check to implement the documented Python predicate rather than add Go URL parsing restrictions.

### F5 [P3] The hold predicate accepts non-string metadata and invalid amounts (C1)

`core/validate/__init__.py:201`: numeric, boolean and null values equal to their previous YAML values are treated as held strings. `test_held_metadata_requires_strings` gives six failing cases. Schema validation independently rejects these at normal plan time, which limits impact, but the claimed predicate is false. Likewise, `_same_amount` (`:215-220`) treats identical invalid quantity text as the same amount. `test_held_requires_a_real_amount` fails for quota and limit keys before the fix (`review/before-amount.log`). The caller protects real CEL errors from being held, so this fallback does not suppress those errors; the fix makes the predicate itself honor C1.

### F6 [P2] A changed LimitRange relation is dropped when its upper key is unchanged (C1/C2 agreement)

`core/validate/__init__.py:176-178,206-211`: `_held` applies to `order` checks too. Change `defaultRequest.cpu` from `250m` to `1`, keeping `default.cpu=500m`. The CLI correctly fails the new relation; passing Git's previous folder suppresses that finding because the indexed upper key is unchanged. The admission expression explicitly never ratchets order (`policygen.py:211-219`), so this validator can return a clean verdict on an invalid changed relation. The separate Python tier-order checks may independently reject it; this is not a demonstrated bypass of the entire plan pipeline. This does not reopen D9: the relation changed. `test_limit_order_violation_is_never_held` fails before the fix.

### F7 [P1] Report faults and non-pass results can disappear (C6)

`core/validate/__init__.py:153-155,174-175,184`: `warn`, an unknown status, and a missing status are counted as seen then silently discarded, so the missing-result guard cannot catch them. An exit 2 with valid JSON is not independently rejected. Non-list `results` can silently become empty or crash on a null entry. Regression cases: `test_non_pass_skip_results_are_errors` and `test_cli_faults_fail_closed`; exit 2 with no JSON and a missing results key already pass. These tests stub process output to exercise fault paths; they do not claim that this CLI naturally emits every malformed form. A complete passing report with exit 2 also returns no findings before the fix (`test_exit_two_with_complete_passing_report_is_error`). In addition, `_matched_kinds` (`:238`) ignores resource `*`: mixing an unknown-version wildcard policy with the generated bundle produces no guard finding. `test_missing_wildcard_policy_result_is_guard_error` reproduces that loss with the real CLI in audit mode and an unchanged previous folder (`review/before-wildcard.log`). The fix expands the wildcard to all checked core kinds.

### F8 [P2] Finding-to-file mapping omits namespace (C6)

`core/validate/__init__.py:161,166`: two valid ResourceQuotas with identical names in different namespaces both map to the last file, and the first file gets spurious missing-result guards. `test_findings_use_namespace_in_identity` reproduces this with the real CLI. Normal callers validate one namespace folder, limiting exposure today; the mapping claim is nevertheless false.

### F9 [P1] Render can overwrite hand-written or another instance's files (C7)

`tools/policies.py:76-80`: the deletion set respects environment ownership and the generated mark, but the write loop overwrites an existing unmarked file at a generated path. A symlink at `env/rnd` also makes writes reach another instance's directory. Both are reproduced entirely in local temporary folders by `test_render_preserves_handwritten_collision` and `test_render_does_not_follow_environment_symlink`. Preflight all target paths before any removal or write.

Baseline core suite: **252 passed** (`review/baseline-core.log`). Initial regression run: **22 failed, 2 passed** (`review/before.log`). Every finding above has at least one failing regression.

## Claim-by-claim assessment of the original export

All line numbers below refer to `review/original/` copies of the named source files, or to the unchanged plan/PR code. The original rendered YAML is preserved in `review/original/env/`.

| Claim | Assessment and evidence |
|---|---|
| C1 | **Refuted in part.** Metadata equality does not require strings (`validate:192-201`, F5). Order findings can be dropped on an unchanged upper key even though the relation changed (`:176-178,206-211`, F6). The caller does correctly require an indexed non-null key, handle `error` before `_held`, and create guard findings after the result loop (`:168-183`); expiry's null index key is generated at `policygen:270-273`. Ordinary equal strings, absent-in-both keys, and equivalent quantities work; existing `test_a_value_that_git_already_holds_is_not_refused_and_a_changed_one_is` exercises `40`/`40000m`/`41` with the real CLI. |
| C2 | **Ratchet expressions confirmed for metadata and maximum checks, with qualifications.** `_same` (`policygen:95-99`) compares presence as well as value, guarded by `variables.update`; the variable is `request.operation == 'UPDATE' && has(oldObject.metadata)` (`:78-80`). Quota maxima compare amounts (`:180-187`); limit maxima guard old access in a ternary (`:205-210`). The four order checks (`:213-219`) deliberately have no exemption: the condition is a relation, not just the indexed upper value (F6 fixes Python accordingly). Every active validation read is protected by presence/conditional logic; `_limit_value` guards both the map key and the filtered list before `[0]` (`:191-195`). Original quota **message** expressions (`:186`) do index the key without an explicit guard; they are evaluated only on a failing validation, which implies that key was present. The candidate fix guards those message reads too. CLI binding tests evaluate copied expressions with null old objects on CREATE and old values on UPDATE; this confirms CEL behavior, not live controller wiring. |
| C3 | **Confirmed for the supplied expressions.** The exact common match expression is `policygen:233-236`; metadata, quota and limits all use it (`:254-260`). Membership precedes indexing, and old metadata is behind the UPDATE test. The unmanaged Namespace probes cover absent labels, an empty label map, and a map lacking the managed key; these are `skip`, never `error`. Copied-CEL UPDATE probes remove the managed label on all three resource kinds and still match through the old object. Removing it from a Namespace fails the required-managed check. |
| C4 | **Refuted.** F3 supplies two counterexamples using the unmodified shipped configuration; Python rejects invalid label syntax while Kyverno's configured pattern accepts it. F4 supplies supported URL-format counterexamples. Python's URL implementation (`metadata:328-331`) actually tests a nonempty **authority** (`netloc`), rather than `hostname`; the candidate generator follows that predicate. Existing company tests cover enum, prefix and derived namespace/environment mismatches; the shipped email rule uses the same ASCII local-part alphabet and case-insensitive ASCII domain list (`identity/checks:26-35`; `policygen:109-115`). The fixes cover the measured disagreements; this review does not assert general Python-regex/RE2 equivalence for arbitrary future patterns. |
| C5 | **Refuted.** F1 and F2. Full f-string audit below. |
| C6 | **Refuted.** F7 and F8. No JSON, missing `results`, CEL errors and ordinary missing-result guards already become source `cmapi` errors; `validate:103-105` downgrades only source `kyverno`. A mode of `off` runs no Kyverno at all (`:101-102`), so “each mode” can only mean each mode that runs the engine. The candidate handles unexpected statuses, malformed result containers and exceptional exits, and maps by kind/namespace/name. |
| C7 | **Deletion selection is confirmed; the overall preservation promise is refuted.** `tools/policies:35-41,74-75` delete only marked YAML or reserved `index.json` under owned `env/<env>/` paths. `environment_of` uses an anchored path expression (`policygen:322-327`). The unchecked write paths can overwrite unmarked YAML or follow an environment symlink (F9). The fix preflights all writes and removals before mutation. Existing render/check tests verify another instance's prod environment survives nonprod rendering. |
| C8 | **Confirmed by source inspection.** Plan reads `prev_files` from `_read_folder` (`pipeline:152-156,188`) and passes that exact mapping at `:263`; request-body labels/annotations are read separately at `:202-205`. The GitHub and Gitea adapters default `read_folder` to their configured default branch and pin its head before reading (`core/git/github:62-76`, `gitea:40-50`). PR checks deliberately read the proposed tree from head (`jobs/pr_checks:56-57`) and the previous tree from `ctx.git.default_branch` (`:72`), passing only the latter as `previous` (`:73`); `core/git/base:101-103` preserves the supplied ref. Neither base argument comes from requester data or from the PR head. No service execution or external Git writes were used. |

The Argo Application (`examples/cluster-configs/clusters/OCP_GF15/argocd/policies-application.yaml:17-20,25-26`) selects `policies/env/dev`, includes only YAML, and enables prune. It excludes `index.json`. Actual Argo pruning remains unmeasured, as in the arbitration.

## C5: every CEL-building f-string with configuration-derived content

This table uses original `policygen.py` line numbers. “CEL fragment” means the string is assembled by this generator, not supplied by the configuration as executable CEL. Configuration-derived interpolation in policy names, descriptions and filenames (`:255-285`) is YAML/JSON data, not CEL.

| Function / original line(s) | Interpolated input | Validation before rendering / encoding |
|---|---|---|
| `cel:51` | map keys and values | Recursive `cel()`; string keys are stringified, without a syntax requirement. String values hit F1. |
| `_meta:92` | `obj`, metadata field | Generator-controlled object identifiers and `_FIELD`'s closed label/annotation mapping; no configured raw text. |
| `_same:98,99` | key and metadata-map CEL fragments | Metadata key syntax is checked by `MetadataKeys._add`; key literal uses `cel`, fragments are generator-controlled. |
| `_value_rule:106` | value CEL, configured regex | Regex compiles with Python `re` in `_add:165-170`; it is anchored and passed through `cel`. This does not validate RE2 compatibility. |
| `_value_rule:108` | value CEL, enum list | Nonempty string-list validation in `_add:143-151`, including syntax for label enum values; every member passes through `cel`. |
| `_value_rule:113,114` | value CEL and configured email domains | Email format requires a nonempty domain list; domains are lowercased in `MetadataKeys.__init__` and encoded with `cel`. The local regexp is generator-controlled. No domain-name syntax validation. |
| `_value_rule:118,119` | value CEL only | No raw configured literal; value is a generated guarded map access. URL implementation disagrees with Python (F4). |
| `_metadata_checks:128` | metadata key CEL / `_same` | Closed system keys, encoded with `cel`; `:129` is a system-key-only message. |
| `_metadata_checks:131` | environment | Environment literal uses `cel`; membership in the instance's configured environments is checked, but no literal/name syntax validation is performed on environment names. |
| `_metadata_checks:132,133` | environment in message | **No `cel` on the interpolated environment**; `ENV_LABEL` is a constant. Fixed by encoding the entire prose string. |
| `_metadata_checks:138,139` | key and value CEL fragments | Declared key syntax validated; key literal uses `cel`; other syntax is generator-controlled. |
| `_metadata_checks:145,146` | cluster-id read | Constant key, guarded by membership; no raw configured literal. |
| `_metadata_checks:148` | derived environment/instance literal | `rule.derived` is checked against `DERIVED_FROM` in `_add:138-142`; the actual string is encoded with `cel`. The separate `said` prose at this line is not itself CEL until `:152`. |
| `_metadata_checks:149,150,151` | presence/value/wanted CEL fragments | Key literal and derived string are encoded as above. |
| `_metadata_checks:152` | key (`where`) and source value (`said`) in message | Key syntax is validated; derived source selector is closed; **instance/environment text in `said` is not syntax-validated or encoded**. F2. |
| `_metadata_checks:157,159,161,162,171` | key/value/rule CEL fragments | Key encoded, regex/enum/domain literals encoded as above, constant `'-'` only for the prefix check. |
| `_metadata_checks:172` | key in `where`, configured rule description in `words` | Key syntax prevents quotes/backslashes; `words` includes regex/enum/domain text and correctly uses `cel`. The key prose still bypasses `cel`; the fix encodes it too. |
| `_quota_checks:183,184,185` | quota key/max through `k,mx`, generated fragments | Tier catalog checks bound quantities; quota keys are checked against catalog rules. Both key and bound literals use `cel`. |
| `_quota_checks:186,187` | key, environment, maximum in message | **No `cel`**. Key and maximum are catalog/quantity-validated; environment is not syntax-validated. Fixed by encoding prose. |
| `_limit_value:193,194,195` | limit kind, field, resource | Kind and field are from `LIMIT_KINDS` / `LIMIT_PARTS`, checked by `limit_key_parts`. Type/resource strings use `cel`; `obj` is a fixed generator parameter. Only the closed field identifier is inserted as syntax. |
| `_limits_checks:205,206,207,208` | bound and generated value fragments | Bound quantity validated and encoded with `cel`; generated old access is conditional. |
| `_limits_checks:209,210` | key, environment, maximum in message | **No `cel`**, same caveats as quota messages; fixed. |
| `_limits_checks:215,217,218,219` | order expressions and messages | Kind, field and resource here are constants from closed loops, not configuration text. |
| `_expiry_checks:226` | expiry key | Constant key encoded with `cel`. |
| `_MANAGED_NS:233,234,235` | managed key and map fragments | Constant key encoded with `cel`; old access is guarded by UPDATE. |

Configuration descriptions/examples are not interpolated into CEL. The fix also rejects isolated surrogate code points explicitly: CEL string values are Unicode scalars, so a Python string containing an isolated surrogate cannot be represented faithfully. Non-BMP scalar characters, quotes, backslashes, newlines and BMP non-ASCII text compile and round-trip in the real CLI regression.

## Complete fixes and regression tests

The [full code of all three fixed modules and the complete tests](review/FIXES.md) is included without excerpts or omitted bodies. [fixes.patch](review/fixes.patch) includes the source changes, regression tests and regenerated YAML for all five environments. The original source/YAML remain under [review/original](review/original/). The working source files are changed solely to run and provide these candidate fixes; no commit or PR was created.

| Finding | Full fix code | Test that failed before and passed after |
|---|---|---|
| F1 | `review/fixed/policygen.py`: `cel` | `test_non_bmp_configured_enum_compiles` |
| F2 | same file: `_metadata_checks`, `_quota_checks`, `_limits_checks` message construction | `test_configured_instance_is_quoted_in_messages` |
| F3 | same file: `_metadata_checks` label syntax predicate | `test_shipped_label_value_agreement` (2 cases) |
| F4 | same file: `_value_rule`, URL branch | `test_url_rule_agreement` (2 cases) |
| F5 | `review/fixed/validate.py`: `_held`, `_same_amount` | `test_held_metadata_requires_strings` (6), `test_held_requires_a_real_amount` (2) |
| F6 | same file: `_held` rejects `rule == 'order'` | `test_limit_order_violation_is_never_held` |
| F7 | same file: `_kyverno`, `_matched_kinds` | `test_non_pass_skip_results_are_errors` (3), malformed-result/exit cases in `test_cli_faults_fail_closed`, `test_exit_two_with_complete_passing_report_is_error`, `test_missing_wildcard_policy_result_is_guard_error` |
| F8 | same file: namespace included in both identity lookups | `test_findings_use_namespace_in_identity` |
| F9 | `review/fixed/policies.py`: `main` preflight | `test_render_preserves_handwritten_collision`, `test_render_does_not_follow_environment_symlink` |

Complete test source: [cmapi/tests/core/test_review_212.py](cmapi/tests/core/test_review_212.py). It also tests CREATE with a null old object, UPDATE presence/equality and amount equivalence, unmanaged Namespace skips, label removal on all three kinds, error results with unchanged invalid values, and expiry without an indexed key. The copied-expression binding mechanism is documented in `admission_fixture`; earlier fixture compilation mistakes were corrected before running against the original source again. The before/after results below use the corrected fixture.

The [original rnd expression audit](review/rendered-rnd-cel.md) retains every generated validation, match condition, variable and message expression. All 26 checks were inspected: 8 metadata, 7 quota maxima, 7 limit maxima and 4 limit-order relations. The full duplicated expressions are retained to make the guarded reads and the missing-key cases reviewable.

## What ran and final results

All commands ran inside this export. Python is native 3.14; installed dependency versions are recorded in [review/python-dependencies.txt](review/python-dependencies.txt). This is native validation, not image validation. No container, cluster, database, service suite, live admission controller or Argo sync was started. `kubeconform="true"` in adapter tests deliberately isolates the Kyverno adapter; it is not a schema-validation claim.

1. `tools/bin/kyverno version`: **v1.20.0**, build commit `f666af06e9bd310c7e730f1523c0430e90371a89`.
2. System `python3 -m pytest tests/core -q` with the requested PATH/PYTHONPATH could not start: pytest missing. Created `.review-venv` using `python3 -m venv .review-venv`; installed `pytest pyyaml pydantic pyjwt httpx prometheus-client` with that environment's pip.
3. Original source, before adding regressions:
   ```sh
   cd cmapi
   PATH=$PWD/../tools/bin:$PATH PYTHONPATH=src:tests/core \
     ../.review-venv/bin/python -m pytest tests/core -q
   ```
   **252 passed**; [baseline-core.log](review/baseline-core.log).
4. Literal CLI probes: `PYTHONPATH=cmapi/src .review-venv/bin/python review/probe.py`; [probe.log](review/probe.log). Every real CLI invocation uses `kyverno apply ... -p --output-format json`, offline and without a cluster flag. Retained fixtures and stderr/stdout are under `review/probes`, `review/before-final` and `review/final-tests`.
5. Restored original modules, with the final corrected admission fixture:
   ```sh
   # From cmapi/
   PATH=$PWD/../tools/bin:$PATH PYTHONPATH=src:tests/core \
     ../.review-venv/bin/python -m pytest tests/core/test_review_212.py -q \
     --basetemp=../review/before-final
   ```
   **23 failed, 20 passed**; [before-final.log](review/before-final.log). The two subsequently added amount predicates give **2 failed, 1 passed** including the unkeyed-expiry confirmation ([before-amount.log](review/before-amount.log)); the subsequently added real-CLI wildcard guard gives **1 failed** ([before-wildcard.log](review/before-wildcard.log)). Together: **26 distinct regression failures, 21 passing claim probes**, on the original implementation. No claim is made that all 47 ran in a single before invocation.
6. Restored/applied candidate fixes and invoked `cmapi.tools.policies.main` with `render`, then `check`, for each of `nonprod`, `staging`, `prod`, using its `examples/instances/<instance>` config, the shipped `metadata-keys.yaml`, and `examples/cluster-configs/policies` as output/input. **8, 8, 5 files matched** respectively; another instance's environments are preserved. These are the same entry-point arguments as `cmapi-tools policies render/check`; the command module was called through native Python.
7. Final permitted full core suite, with all fixes, all 47 review tests and regenerated examples:
   ```sh
   cd cmapi
   PATH=$PWD/../tools/bin:$PATH PYTHONPATH=src:tests/core \
     ../.review-venv/bin/python -m pytest tests/core -q \
     --basetemp=../review/final-tests
   ```
   **299 passed in 76.00 seconds**, exit 0; [final-core.log](review/final-core.log). No skips or remaining failures.

TokenSave tooling suggestion: file a sanitized issue at <https://github.com/aovestdipaperino/tokensave> for `tokensave_read` requiring a registered graph even when given an absolute unindexed path, despite advertising reads of any path. Omit project paths and code from the issue.
