# PR #735 review — request changes

**PostgreSQL was unreachable.** The sandbox denied the TCP connection to `127.0.0.1:55432` with `Operation not permitted`. All three adoption service tests stopped in database setup. Adoption through sync, authenticated PATCH submission, and persistence therefore remain unverified in this run. All database attempts used the PostgreSQL database in the brief. [Service test output](r1-outputs/postgres.log)

For valid target values, the production metadata checker implements #732. It accepts a missing automatic key with the exact source string and a missing prefix key with a rule-valid start followed by a hyphen. Git still wins when it holds a value. I would request changes for the following cases before merge.

## Findings

1. **P2 — PATCH can add a derived label that creation rejects.** I loaded a nonprod instance named `west coast` with a required label derived from `instance`. Creating with that label produces `invalid_value`. On head, adding the identical label to an existing namespace produces no metadata error. A 64-character value has the same result. The success return at `cmapi/src/cmapi/core/metadata.py:1164` skips Kubernetes label syntax after equality succeeds. This lets an invalid manifest past cmapi's own check. The fix checks syntax for new values and preserves legacy echoes. The same source remains valid for an annotation. [Loaded configuration and results](r1-outputs/instance-label.log) · [Regression tests](r1-outputs/fixed/cmapi/tests/core/test_missing_metadata_values_732.py)
2. **P2 — An empty source can add a key that creation would leave absent.** With an empty instance source, `MetadataKeys.filled` omits the derived annotation. At `metadata.py:1179`, PATCH treats the empty string as an available source and accepts a request to write it. A required key written this way still appears missing. The fix uses the same source-availability condition as creation and explains when the target supplies no usable value. [Head results](r1-outputs/head-probes.log)
3. **P2 — The finding offers a repair that #481 refuses.** With `name: ""` or an empty mnemonic already in Git, `missing_required` reports the key. At `cmapi/src/cmapi/core/pipeline.py:509`, the plan says “a request can add it.” Sending the exact derived value or a valid prefix then fails because the key is present. The fix keeps the warning and explains that Git holds an empty value. It also uses the target already selected for validation, removing a second registry read while formatting findings. Genuinely absent keys keep their actionable remedy. [Head findings](r1-outputs/head-findings.log) · [Fixed findings](r1-outputs/fixed-findings.log)
4. **P3 — The portal test API rejects both legal additions.** In `cmapi-portal-ui/tests/api/standin.mjs:833`, the only success path for a name key is an echo. A dry-run PATCH adding the missing name, mnemonic and derived environment to `abc-ledger-dev` returns 422 on all three, even though the message says a request can add them. The fix returns 200 and reports each addition in `metadataDiff`. The regression test also checks refusals for the wrong case, a partial segment, a delimited prefix that breaks the configured pattern, and removal. The stand-in uses patterns from its shipped fixtures, consistent with its limited test scope. [Head response](r1-outputs/head-standin.log) · [Fixed run](r1-outputs/fixed-standin.log)

## Rulings and controls

| Question | Observed result |
| --- | --- |
| Exact automatic value | Labels and annotations accepted exact namespace, environment, cluster and instance sources. Case changes, leading and trailing spaces, fullwidth and Cyrillic look-alikes, truncation, added text, and removal were refused. The source edge cases above qualify this result. |
| Exact namespace prefix | For `abc-pay-dev`, both `abc` and `abc-pay` are complete starts under an unrestricted rule. An enum allowing only `abc` refuses `abc-pay`. The checker also refused `ab`, an interior segment, the whole name, case, whitespace and look-alikes. This follows the create rule that the value must be followed by a hyphen. |
| Existing Git values | A different legacy value, including an empty string, prevents replacement even by today's exact target. Removal of an automatic key yields `derived_key`. Removal of a required prefix yields `missing_required_key`. The existing suites also checked legacy echoes and the optional-prefix removal rule. |
| Creation and other #481 rules | The selected controls passed on both snapshots. They cover create-time derivation, defaults, both ends of the name, required and optional edits, system/reserved/operator rules, disallowed-key removal, sensitive changes, and metadata diffs. A missing suffix-only key remained fixed. |
| Finding lifecycle | For genuinely absent keys the production finding builder returned separate label and annotation warnings with “a request can add it.” On the fixed copy the builder returned no such warnings once the keys were supplied. The builder and validator ran directly. The database-backed lifecycle is still open. |

## Test evidence

| Run | Base (#733) | Head (#735) | Fixed copy |
| --- | --- | --- | --- |
| Same two PR core test files from head | 2 failed, 35 passed, 1 skipped | 37 passed, 1 skipped | Included below |
| 49 independent core cases | 14 failed, 35 passed | 3 failed, 46 passed | 49 passed |
| Each snapshot's create and #481 core suites | 123 passed, 2 skipped | 123 passed, 2 skipped | 123 passed, 2 skipped |
| Service documentation tests without a database dependency | — | 9 passed | 9 passed |
| Stand-in suite with the added PATCH case | — | 1 failed, 6 passed | 7 passed |

The two PR tests that failed on base were the legal mnemonic addition and the legal derived-name addition. In the independent suite, base refused all twelve intended positive cases. Two other base failures asserted the create-compatible error code for an invalid derived label. The three head failures reproduced findings 1 and 2. The two core skips require a Kyverno executable. These rows overlap and should not be summed. [Base PR tests](r1-outputs/base-pr-tests.log) · [Head PR tests](r1-outputs/head-pr-tests.log) · [Base probes](r1-outputs/base-probes.log) · [Fixed core run](r1-outputs/fixed-tests.log) · [Fixed documentation run](r1-outputs/fixed-docs.log)

**All nine mutants were killed.** Each ran separately against a fresh version of head's PATCH comparison. The unmodified control passed all 46 selected cases. Mutations covered case folding, trimming, NFKC normalization, partial derived equality, dropping the prefix delimiter, matching an interior segment, folding prefix case, skipping the prefix's own rule, and allowing a held value to be overwritten. The three known failures on unmodified head were excluded from mutation scoring. [Mutant definitions and runner](r1-outputs/mutants.py) · [Failing assertions per mutant](r1-outputs/mutants.log)

## Patch and reproduction

The patch is relative to `head/` and includes the regression tests. I applied it to a fresh copy, compared that entire tree to the tested copy, and verified that the relocated documentation citations still point to their locked source text. I inspected the supplied snapshots directly because the review tree has no TokenSave index. [Fix](r1-outputs/fix.diff) · [Patched copy](r1-outputs/fixed/)

From the review directory, these commands reproduce the independent comparison and the mutations. Select either snapshot for `tree`. The explicit pytest configuration keeps the external test file from selecting the fixed copy's source path.

```sh
core_python=/Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python
tree=head
(cd "$tree/cmapi" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$core_python" -m pytest \
  -c /dev/null --noconftest ../../r1-outputs/fixed/cmapi/tests/core/test_missing_metadata_values_732.py \
  -q -W ignore -p no:cacheprovider)
"$core_python" r1-outputs/mutants.py
node --test r1-outputs/fixed/cmapi-portal-ui/tests/api/standin.test.mjs
```
