# PR #735 (closes #732): reviewer 2 (Opus 5.5, high)

I did not write #735. I read `BRIEF.md`, `r1-report.md`, every line of `r1-outputs/fix.diff` and `pr.diff`, and the changed
code on `head/` around each line. I worked in `r2-work/` (head + Codex's patch, then narrowed). PostgreSQL on
`127.0.0.1:55432` was reachable from here (database `cmapi_r2_735`), so the database-backed tests that reviewer 1 could not
run were run (they are the evidence for the API path below). All results below are from this machine; no cluster was used.

**Deliverable:** [`r2-outputs/final.diff`](r2-outputs/final.diff), one patch against `head/`. It applies with
`patch -p1 -F0` to a fresh copy of `head/` (exit 0, no `.orig`/`.rej`), and the patched copy is byte-identical to
`r2-work/` ([fresh-apply.log](r2-outputs/fresh-apply.log)).

## The ruling, and what the code must do

The coordinator's ruling (#732, from the owner's decision 2 on #26): a change may add a *missing* `value.from` key only with
exactly the derived value, and a *missing* `namespacePrefix` key only with exactly a start of the name; anything else is
refused; the remedy texts say "a request can add it". The rendered Kyverno policy already admits exactly these additions
(`policygen.py:226-230`: derived is `_same || (present && value == want)`; `:239-241` and `:244-247`: the prefix adds
`startsWith(value + '-')`, the pattern and the label syntax), so the API and the policy agree on the positive cases. I checked that, since a PATCH the API
accepts but the policy refuses would fail at validation.

## Verdicts on reviewer 1's findings

Each is confirmed by a test that fails on `head/` and passes with `final.diff`.

| # | Finding | Verdict | Proof on head | Reachable how |
|---|---|---|---|---|
| F1 | An exact derived *label* is accepted on PATCH without the label syntax that create applies | **Confirmed** | `test_a_new_exact_derived_label_must_still_be_a_valid_label[west coast]`, `[a*64]` fail on head: create gives `invalid_value`, PATCH gives `[]` ([head-core-732.log](r2-outputs/head-core-732.log)) | A `requiredLabels` key with `value: {from: instance}` (or `environment`) and an instance name that is not a label value. `config.py` does not validate `instance.name`, and the renderer writes it only as an annotation (`manifests.py:197`), so nothing else catches it. Kubernetes would then refuse the merged manifest at apply. |
| F2 | An empty source lets PATCH add a key that create would leave absent | **Confirmed** | `test_an_empty_source_fills_no_value_to_add` fails on head: `filled` omits the key (`_fill_derived` tests `sources.get(...)` for truth), but `_addition` tested `is not None`, so `""` was accepted and the key still reads as missing afterwards | Only with an empty instance name or environment: a configuration edge. The one-token fix makes PATCH use create's own condition. |
| F3 | The finding advertises "a request can add it" for a fixed or automatic key that Git holds as `""`, and that request is refused | **Confirmed** | `missing_required` counts `""` as missing (`not maps[kind].get(key)`), `remedy` then offers the addition, and `_fixed_key_error` refuses it because `held == ""` is not `None`. R1's [head-findings.log](r1-outputs/head-findings.log) shows it; my service test `test_a_fixed_key_that_git_holds_empty_is_reported_as_kept_since_a_change_cannot_replace_it` fails on head (asserts the exact messages and that both advertised requests are refused). |  Any adopted namespace whose live object had `name: ""` or `company.net/mnemonic: ""`. |
| F4 | The portal stand-in says "a request can add it" and refuses every addition | **Confirmed** | The PR changed only the stand-in's message (`standin.mjs:834`); `node --test tests/api/standin.test.mjs` with the added case: 6 pass, 1 fail on head, 422 on all three additions ([head-standin.log](r2-outputs/head-standin.log)) | Every portal test run against the stand-in. |

I retract nothing of reviewer 1's findings. I narrow parts of its patch below.

## Codex's patch, line by line: kept, narrowed, dropped

**`metadata.py`**

- `_fixed_key_error`: after an accepted addition, return `_syntax(...)`'s error. **Kept.** It gives PATCH the same
  `invalid_value` code that create gives for the same value (the test asserts both), in two lines.
- `_fixed_key_error` else branch: pass `sources` to `remedy`. **Kept**: the refusal of a removal now names the value.
- `_addition`: `expected is not None` -> `expected`. **Kept**: the same truth test as `_fill_derived` and `derived()`.
- `remedy`: Codex added two branches ("the {source} supplies no value to add" when `sources is not None and not expected`;
  "supplies a value that is invalid for this {kind}") and kept `sources` optional. **Narrowed** to one condition and one
  message, and `sources` made a required parameter (every caller now passes it, so the `None` path and the
  `sources is not None` guard were dead weight):

  ```python
      def remedy(self, kind: str, key: str, sources: Mapping[str, str]) -> str:
          ...
          if rule.derived:
              expected = sources.get(rule.derived)
              if not expected or self._syntax(key, expected, kind):
                  # As at create, which fills nothing from an empty target and refuses a value that is not a valid label.
                  return f"a change cannot add it: the {rule.derived} gives no valid value"
              return f"a request can add it with the value cmapi derives from the {rule.derived} ({expected})"
  ```

  This keeps the guarantee that motivated F3 (the remedy never offers an addition that a change refuses) for F1 and F2's
  configurations too; `test_the_remedy_never_offers_an_addition_that_a_change_refuses` fails on head and passes now.

**`pipeline.py`**

- `_held_key_findings` takes the caller's `sources` instead of rebuilding them with a second `environment_of` registry
  read. **Kept**: it is shorter, and the finding now uses the same target dict the validator used (`pipeline.py:306`), so
  the two cannot drift. `sources["namespace"] == ns` and `environment_of` returns the same `st.policy.environment` that
  `_plan_namespace` read, so the output is unchanged for every existing case (behaviour-preservation: the 49 head service
  tests still pass, below).
- The "empty in Git" branch for fixed and automatic keys. **Kept** as written. Plain required keys held as `""` keep
  "a request can add it", which is true for them (any valid value is accepted).

**Portal stand-in (`standin.mjs`)**

- **Narrowed.** Codex compiled the patterns of three fixture schemas into a module-level `fixturePatterns` map, ran them
  with `new RegExp(..., "u")`, checked enums and label syntax, and left the docstring saying "No configured pattern runs
  here" (now false). The stand-in's create check, `createMetadata`, runs no pattern, enum or label syntax by design (its
  docstring: "an operator's pattern can backtrack, and cmapi matches with RE2"). I made the PATCH check mirror
  `createMetadata` exactly: a derived key equal to its non-empty source, or a prefix that the name starts with plus `-`.
  Two lines replace Codex's 21 (the map, the helper and the block), and the docstring is true again. Codex's `sources` and its remedy-mirroring messages are
  kept.
- `standin.test.mjs`: Codex's case kept; `[mnemonic, "abc-ledger"]` (a pattern refusal the stand-in does not model) replaced
  by `[mnemonic, "ledger"]` (not a start) and `[env, "rnd"]` (a wrong derived value).

**Tests and docs**

- `tests/core/test_missing_metadata_values_732.py`: Codex's 49 cases kept (exact accept, case, whitespace, fullwidth and
  Cyrillic look-alikes, truncation, extension, removal, a held legacy or empty value, suffix stays fixed, enum on a
  delimited prefix); one remedy test added (2 cases).
- `test_namespace_patch_review_492.py`: Codex's F3 test asserted only that the messages contain "is empty in Git". **Made
  exact**, and it now sends the two requests the old message advertised and asserts both are refused, so the test proves the
  "agrees with patch" that its name claimed.
- `docs/14-authorization.md` and `docs/citations.lock.json`: relocated with `scripts/doc-citations.py --relocate` in a
  git-initialised copy (the export has no `.git`, which the script needs). `--check` reports 0 problems after.
  `metadata.py:1367` -> `:1370` (Codex had `:1372`, for its longer `remedy`); `pipeline.py:550` -> `:553` and `:780` ->
  `:783` as Codex had.

## What reviewer 1 missed, in the changed lines

1. **The derived addition was never shown to be written.** `test_a_request_adds_the_missing_derived_name_with_its_derived_value_only`
   (`tests/service/test_add_missing_key_732.py`) checked only that the finding goes away, and the finding is computed from
   the request's merged maps (`pipeline.py:429`), not from the rendered file. The renderer, on a change, keeps only the
   derived keys that Git holds (`manifests.py:210-213`), so a regression that dropped the sent value would have passed.
   Fix, in `final.diff`:

   ```python
       ns = yaml.safe_load(right.json()["files"][f"clusters/CRC/namespaces/{NS}/namespace.yaml"])
       assert ns["metadata"]["labels"]["name"] == NS             # the renderer writes it: Git lacked it, so none is kept
       assert right.json()["metadataDiff"]["labels"]["name"] == {"before": None, "after": NS, "source": "request"}
   ```

   It passes on PostgreSQL (below). It is a test gap, not a code defect: the renderer does write it.
2. **Codex's stand-in docstring became false** ("No configured pattern runs here" above code that runs patterns). Fixed
   by the narrowing above.
3. **The portal cannot make the repair that the finding now offers.** `cmapi-portal-ui/src/portal/namespaceChange.ts:76`
   locks every field with `derivedFrom`, or with edit mode `fixed` or `automatic`, on the change tab, whether Git holds the
   key or not. So "a request can add it" is true of the API and not of the portal. The lock predates #735, and the
   change is a portal feature for story #26, so it is not in `final.diff`. **Recommended:** file a follow-up for story #26
   (the change tab offers a missing automatic key as its derived value, and a missing prefix key as a start of the name,
   when `git` lacks the key).

## Backlog (predates the PR)

- `instance.yaml`'s `instance.name` has no validation (`config.py:171` passes `me["name"]` through). A metadata-keys file with
  a label `value: {from: instance}` and an instance name that is not a label value breaks every create with
  `invalid_value`. A load-time check (the name a DNS-1123 label, or at least a label value when a label derives from it)
  would surface it at start-up. Low.
- The portal change-tab lock in "missed" item 3, if the coordinator does not take it as a story #26 feature.

## Open question for the coordinator (a design choice, not a defect)

A fixed or automatic key that Git holds as `""` is reported as missing, and stays reported forever: a change cannot
replace Git's value (#481), and cannot remove it (`derived_key`, or `missing_required_key` for a required prefix). Only a
direct Git edit clears it. `final.diff` keeps #481's rule, as the brief says ("a key present in Git with a different
value: still refused"), and makes the finding say so. If the owner's "until someone chooses to add it" should cover an
empty value too, the change is one condition in `_fixed_key_error` (`held` falsy instead of `held is None`), and the
rendered policy already admits it (`present && value == want` passes for `"" -> want`). I did not make that change.

## Test evidence

All on this machine; PostgreSQL 16 on `127.0.0.1:55432`, database `cmapi_r2_735`. Service tests use
`wt-655-outputs/venv-merged`; core tests use only `venv-ref`. No cluster was used.

| Run | Head (#735) | With `final.diff` |
|---|---|---|
| Service: `test_add_missing_key_732`, `test_namespace_patch_review_492`, `test_namespace_patch_contract_483`, `test_api_namespace_change_doc_rules` (PostgreSQL) | 49 passed ([head-service.log](r2-outputs/head-service.log)): the PR's own adoption tests pass, which reviewer 1 could not run | 61 passed, plus `test_doc_citations` below ([r2-service.log](r2-outputs/r2-service.log)) |
| The R2 service tests against head's source | 1 failed (the F3 test: head says "lacks it: a request can add it with the value cmapi derives from the namespace (abc-payments-dev)"), 13 passed; the rendered-`name` assertion passes on head too, as a test gap should ([head-service-r2-tests.log](r2-outputs/head-service-r2-tests.log)) | passes |
| `tests/core/test_missing_metadata_values_732.py` | 5 failed (F1 x2, F2, remedy x2), 46 passed ([head-core-732.log](r2-outputs/head-core-732.log)) | 51 passed |
| Full `tests/core` (`venv-ref`) | not rerun | 921 passed, 115 skipped, 0 failed ([r2-core-full.log](r2-outputs/r2-core-full.log)) |
| Fresh `head/` copy + `final.diff`: the three #732/#481 core files, `test_policygen`, `test_adoption_26` | | 124 passed, 29 skipped ([fresh-core.log](r2-outputs/fresh-core.log)) |
| Stand-in `node --test tests/api/standin.test.mjs` | 6 passed, 1 failed (422 on all three additions) ([head-standin.log](r2-outputs/head-standin.log)) | 7 passed, on `r2-work` and on the fresh copy ([r2-standin.log](r2-outputs/r2-standin.log), [fresh-standin.log](r2-outputs/fresh-standin.log)) |
| `test_doc_citations::test_each_citation...` | fails: the export has no `.git` and the script runs `git ls-files` ([head-doc-citations.log](r2-outputs/head-doc-citations.log)) | fails the same way, for the same reason. In a git-initialised copy of `r2-work`, `scripts/doc-citations.py --check` exits 0 after `--relocate`. CI, with `.git`, is the real gate |

**Mutants** ([mutants.sh](r2-outputs/mutants.sh), [mutants.log](r2-outputs/mutants.log)): each mutation runs on a fresh copy of
`r2-work`, and the control passes. All 10 were killed: the F2 truth test reverted, the F1 syntax return dropped, the
remedy's invalid-source and empty-source guards each dropped, case-folded derived equality, the prefix without its `-`,
the F3 branch disabled (killed by the PostgreSQL service test), and in the stand-in the derived addition removed, the prefix
without its `-`, and case folding. (On the first run the prefix mutant matched two places in the file and was never
applied. I fixed the runner to say NOT APPLIED instead of SURVIVED, and the rerun kills it.)

**Who wrote what.** The #735 code and tests: Opus 5.5 (the implementer). `fix.diff`: Codex gpt-6.2-astra xhigh (reviewer 1).
`final.diff`: Codex's patch, narrowed by me (reviewer 2, Opus 5.5 high), plus one `remedy` test, the exact F3 service test,
the rendered-`name` assertion, and the relocated citations.
