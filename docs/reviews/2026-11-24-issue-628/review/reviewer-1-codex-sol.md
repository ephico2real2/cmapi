# PR #642 — reviewer 1 (adversarial)

Recommendation: revise. Two Medium findings and one Low finding; no High finding. The new drift wording is correct, and the suggested objection to `cmapi.net/managed` is **refuted** by the implementation.

All source references below are relative to `head/`. I read all of `pr.diff`. I used no Git commands, GitHub, database, or cluster. Head and base were not edited. Experiments and proposed corrections are under `experiments/`. TokenSave context/status both rejected this export as uninitialized; I inspected source directly without initializing or updating an index.

## Findings and complete corrections

### F1 — Medium: the adjacent `in-sync` row omits two conditions

Location: `docs/reviews/2026-11-20-epic-481-metadata-patch/design.md:154` (unchanged adjacent text made inconsistent by the corrected drift row at 153).

Matching governed and extra keys is insufficient: an operator-only key can differ, or an otherwise empty namespace can be absent from the cluster. `plugins/namespaces/state.py:22` checks an open request first; `:24` returns drift when comparison succeeds and a key differs **or** the namespace is absent. `core/metadata.py:71` defines `NAMED_CLASSES = ("governed", "team", "operatorOnly")`; `:997` filters the comparison by these classes and `liveOnlyKeys`. This is a real omission, although the preceding “in this order” rule reduces the ambiguity for a careful reader.

Replace the full row with:

> | `in-sync` | cmapi can compare Git with the cluster, the namespace exists on the cluster, and no request is open. The governed, extra and operator-only keys match, except for keys that match `liveOnlyKeys`. |

Fail-before/pass-after regression: `test_in_sync_includes_every_compared_class` in [the complete proposed test file](experiments/proposed_test.py). It fails on head and passes on the corrected copy. The current suite passes even if the row says “have different governed and extra keys” (`survive-wrong-insync`). Direct pure-function probes measured operator-only differences and an absent empty namespace as `drift`; see [probes.txt](experiments/probes.txt).

### F2 — Medium: the regression test checks words without checking several claimed rules

Locations: `cmapi/tests/service/test_design_481_matches_build.py:42`, `:47`, `:63`, `:64`, `:74`.

The test does not assert the row-1 422 outcome at all. The list assertion checks only “A list of tags”; the removable assertion checks only that the word occurs somewhere. Edit validation checks types and mode/removable but does not compare the reason or sensitive flag with generated rules. Measured mutants that all retain **8 passing tests**:

- List: “passes only when all are the current etag”.
- Row 1: `200 accepted` instead of `422 validation-failed`.
- Removable prose: “a change may set it and never remove it”.
- Drift: “An open request exists” instead of “No request is open”.
- Edit reason: “You may change it.” instead of “Managed by cmapi.”

These are gaps in the intended regression protection, not evidence that the corresponding head prose is wrong. Strengthen the existing test with scoped rule assertions and a comparison to `MetadataKeys.edit_rule`; [proposed_test.py](experiments/proposed_test.py) contains the **complete replacement file**, including imports, fixtures and existing tests. The added functions are:

```python
def test_in_sync_includes_every_compared_class(design):
    row = next(x for x in design.splitlines() if x.startswith("| `in-sync` |"))
    assert "operator-only" in row
    assert "namespace exists on the cluster" in row
    assert "no request is open" in row
    assert "liveOnlyKeys" in row


def test_read_edit_rules_match_build(design):
    from cmapi.core.metadata import MetadataKeys
    from cmapi.core.models import KeyEdit
    block = re.search(r"```json\n(.*?)```", _section(design, "### 4.2 The read"), re.S).group(1)
    edit = json.loads(block)["git"]["edits"]["labels"]["cmapi.net/managed"]
    keys = MetadataKeys({"system": ["cmapi.net/managed"]})
    expected = KeyEdit.model_validate(keys.edit_rule("label", "cmapi.net/managed"))
    assert KeyEdit.model_validate(edit) == expected


def test_prose_contracts(design):
    text = " ".join(design.split())
    assert "passes when one is the current etag" in text
    assert "cmapi returns 422 `validation-failed` if the body includes `name` or `namespace`." in text
    assert "A change may remove that key with `null`. The change cannot set or change its value" in text
    drift = next(x for x in design.splitlines() if x.startswith("| `drift` |"))
    assert "No request is open" in drift


def test_active_short_replacements(design, second_pass):
    text = " ".join(design.split())
    assert "No request is open, and cmapi can compare Git with the cluster." in text
    assert "The path names the namespace. The tab has no row for it." in text
    assert "cmapi excludes live-only keys from the comparison." in text
    assert "The owner replaced row 3 the same day (#482). Discovery has no permission filter." in " ".join(second_pass.split())
```

The full replacement also updates the existing case-sensitive row-1 phrase and the two second-pass phrases to agree with F3 below. The synthetic system configuration tests the illustrated rule; it does not claim to validate every deployment configuration or the completeness of an example with ellipses.

Fail-before/pass-after evidence: all five semantic mutants above survive the original suite. Their equivalent mutations of the corrected docs fail the strengthened tests; restoring the correct text passes. See [strengthened-mutants.txt](experiments/strengthened-mutants.txt). The strengthened suite on uncorrected head is **4 failed, 8 passed**; corrected docs are **12 passed**. Full logs: [before](experiments/before-fixes/pytest.txt), [after](experiments/after-fixes/pytest.txt). Exact-phrase assertions still constrain wording; they do not prove arbitrary prose equivalent to code.

### F3 — Low: new prose is too long and uses passive voice

Locations: `design.md:51`, `:153`, `:157`, `:160`; `second-pass.md:27`. This is a manual short-sentence/active-voice review, not a certified audit of the full ASD-STE100 vocabulary or standard. Row 1 has about 35 whitespace-separated words in one parenthetical sentence; the ignore-list sentence spans three lines. “are left out” and “Row 3 was replaced” are passive. The two new If-Match sentences are short and active enough; the tab picture is a label, not prose.

The new drift row is also one long sentence (about 38 whitespace-separated words). Full replacement:

> | `drift` | No request is open, and cmapi can compare Git with the cluster. A governed, extra or operator-only key differs, or the cluster does not have the namespace. `driftedKeys` lists each key that differs. |

Full replacement for row 1:

> | 1 | The namespace name (the path) | Fixed | — (The path names the namespace. The tab has no row for it. cmapi returns 422 `validation-failed` if the body includes `name` or `namespace`.) |

Full replacement for the `git.edits` paragraph:

> For each undeclared or operator-only key in Git, `git.edits` gives its `x-cmapi-edit` rules.
> A key with `removable: true` has no admitting rule. A change may remove that key with `null`.
> The change cannot set or change its value (#528).

Full replacement for the ignore-list paragraph:

> cmapi excludes live-only keys from the comparison. Configure these keys with `liveOnlyKeys` in `metadata-keys.yaml`.
> This stanza accepts `fnmatch` globs. The default is `kubernetes.io/metadata.name`, `openshift.io/*`,
> `argocd.argoproj.io/*`, `app.kubernetes.io/instance`.

Full replacement for second-pass line 27:

> The owner replaced row 3 the same day (#482). Discovery has no permission filter.
> The detail read returns `git: {labels, annotations, edits}` (design.md §4.2).

Including `edits` also makes the summary match the complete current shape. The historical attribution and date are retained, not independently verified. The row-33 `sync` union has `unknown` correctly; rows 4 and 8 remain outside scope.

Fail-before/pass-after test: `test_active_short_replacements` above fails on head and passes on the corrected docs. This is a regression assertion for the reviewed prose, not an automated STE compliance checker. Complete corrected documents: [design.md](experiments/corrected-docs/docs/reviews/2026-11-20-epic-481-metadata-patch/design.md), [second-pass.md](experiments/corrected-docs/docs/reviews/2026-11-20-epic-481-metadata-patch/second-pass.md).

## Verification of the requested claims

1. **Drift: confirmed**, subject to a fresh comparison and pending taking priority. `plugins/namespaces/state.py:36` sets `compared = git is not None and live_fresh`; `:37` calls `drifted_keys`. `core/metadata.py:996` compares the union of Git/live keys; `:997` includes operator-only keys via `NAMED_CLASSES` and excludes live-only globs; `:999` compares values. Missing namespaces are expressly drift at `plugins/namespaces/state.py:24`, even with no differing keys. See F1 for the inconsistent adjacent row and correction.

2. **Edits/removable: confirmed. The proposed exclusion of system keys is refuted.** `core/metadata.py:953` includes each key present in Git unless `key in self.rules[kind]`. It does **not** exclude `self.system`. `:711` prohibits a system or operator-only key from becoming a declared requester rule. `:909` classifies system keys; `:960` gives fixed/system wording. Thus “undeclared” here means absent from the required/extra rule maps, not absent from every YAML stanza. `cmapi.net/managed` is system **and** undeclared in that sense. `core/models.py:381` explicitly permits a fixed system key in edits. The example's fixed/false/“Managed by cmapi.” values are valid for the shipped policy (`examples/cluster-configs/policies/metadata-keys.yaml:3`). A probe confirmed its inclusion. No substitute key is required.

   `core/metadata.py:945` sets `removable` for disallowed keys, including the legacy spelling/kind case at `:935`. `core/models.py:363` defines removal with null and prohibits setting/changing; `:379` describes undeclared/operator-only entries. `plugins/namespaces/router.py:245` constructs the read with `undeclared_edits(git, environment)`, which preserves environment-specific operator wording (#532 comment at `core/metadata.py:951`). An illustrative removal-only key under the shipped configuration is `legacy.invalid/key`: fixed, “Not allowed by this instance's rules.”, sensitive false, removable true (measured). The read example is abbreviated: the managed key is not explicitly in its Git labels, but the ellipsis permits omitted entries. For a literal complete example add `"cmapi.net/managed": "true"` to `git.labels`; I do not treat an abbreviated example as a complete response.

3. **Defaults/stanza: confirmed.** `core/metadata.py:67`–68 gives exactly `kubernetes.io/metadata.name`, `openshift.io/*`, `argocd.argoproj.io/*`, `app.kubernetes.io/instance`. `:612` reads `liveOnlyKeys` and uses those defaults only when the stanza is absent. `:989` applies `fnmatchcase`. An explicit empty stanza disables these defaults; the PR does not state otherwise.

4. **If-Match: confirmed for a current strong tag in a valid list.** `core/pipeline.py:140` checks the requirement; `:145` fails only if the current etag is not among parsed tags. `:131`–132 rejects bare `*`, padded by SP/HTAB, as 428 `precondition-required`. `core/etag.py:100` drops weak tags. Measured: `"old", "current"` passes, `*` gives 428, `W/"current"` gives 412. The PR sentence does not discuss malformed lists; it should not be read as permitting them.

5. **Row 1: confirmed for top-level name/namespace properties.** `core/models.py:252` inherits `Api`; `:23` sets `extra="forbid"`; `NamespacePatch` has no name or namespace field. Both properties produce `extra_forbidden` in measured model probes. `main.py:213`–221 maps request validation errors to 422 `validation-failed`. The HTTP outcome is inferred from this handler, not measured through an HTTP service. A metadata label whose string happens to be a name is a different case; F3 makes the top-level fields explicit.

   **Tab picture:** `routers/me.py:39` requires `clusters:read`, and `:42` returns every registry snapshot, without a `namespaces:write` filter. “Every cluster” describes this authenticated discovery result; it does not imply anonymous access. I did not run a browser to check the tab.

## Assertion-by-assertion mutation audit

Line numbers refer to the head test. These mutants are defined in [run_review.py](experiments/run_review.py); each has a separate directory/log. Full results: [results.json](experiments/results.json).

| Assertion | Mutant and measured result |
|---|---|
| 38 | Append forbidden permission-filter phrase: fails 38. |
| 39 | Replace “every cluster cmapi manages”: fails 39. |
| 43 | Append “A namespace cannot be renamed.”: fails 43. |
| 44 | Replace “the tab has no row for it”: fails 44. |
| 49 | Delete operator-only from the drift row: fails 49. |
| 50 | Delete missing-namespace clause: fails 50. |
| 56 | Rename `git.edits` to `git.wrong`: fails 56. |
| 61 | **Redundant/unreachable failure through docs.** Setting git to null fails at 56 with TypeError, before 61. If 56 and model validation succeed, git cannot be None. No independent doc mutant kills 61. |
| 63 | Change fixed to optional: fails 63. A removable=true mutation would also violate this tuple. |
| 64 | Remove `git.edits` prose token: fails 64. The second conjunct is independently redundant while the JSON includes `removable`; removing all occurrences can make it false, but is a compound mutation. |
| 68 | Append “a small, configurable ignore list”: fails 68. |
| 69 | Rename all liveOnlyKeys occurrences: fails 69. |
| 71, each iteration | Replace each of the four defaults separately: four failures at 71. |
| 77 | Replace “A list of tags”: fails 77. |
| 78 | Change star status to 200: fails 78. |
| 82 | Replace same-day replacement phrase: fails 82. |
| 83 | Replace nested git shape phrase with gitLabels: fails 83. |
| 87 | Remove unknown from union: fails 87. |
| 88 | Append old `in-sync\|pending\|drift,` phrase while keeping new union: fails 88. |

The line-64 conjunction is one assert but has two operands. The JSON's removable field makes its second operand true in normal fixtures, even if the explanatory prose is deleted. Removing only `"removable": false` still passes: `KeyEdit.removable` defaults to false (`core/models.py:363`). That is valid model behavior, not proof that the field is ignored.

**Slicing is not vacuous.** `_section` at 31–34 starts at the heading and searches for the next line starting `### `. It adds the consumed heading length back to the relative match offset correctly. The partial heading ends before the rest of the title, but the first fenced JSON still belongs to 4.2. Missing headings/fences raise errors; the example is actually parsed. This helper would include `##` headings until a later `###`; that hypothetical does not occur in the present slice.

**Padding is deliberate and limited.** The dictionary at 58–59 fills clusterId/env/team/tier/managed/expiresAt/openRequest/mnemonic; `**example` comes last, so explicit example values win and invalid supplied values are not silently overwritten. It does mean omission of any of these eight fields is not tested. They are intentionally absent in this partial example. Name/labels/annotations/etag/git/sync are not padded. Measured deletion of name or live labels fails validation. The experiment directory names `survive-no-default-fields` and `survive-missing-padded` were hypotheses; their logs correctly record failures, not survivors.

**Nested extra handling is real.** `NamespaceView.git` at `core/models.py:413` uses `GitMetadata`; its required `edits` at `:379` uses `GitKeyEdits`; its label/annotation values at `:368`/`:371` use `KeyEdit`. Each inherits Api's extra-forbid configuration at `:23`. Adding `bogus` inside an edit or setting sensitive to a list fails with nested validation errors. It is neither an ignored extra nor an untyped dictionary. Validation cannot establish configuration-dependent policy truth; F2 addresses that narrower gap.

## Runs and limits

- Requested command from `head/cmapi`, with only `PYTHONDONTWRITEBYTECODE=1` added: **8 passed in 0.13s**.
- Head's test against base's two docs, in an isolated mirror using head source: **8 failed in 0.59s**. No export files were swapped. See [base log](experiments/base-docs/pytest.txt).
- 22 targeted assertion/loop mutants: all fail, but the null-git mutant fails before the redundant assertion as described above.
- Seven semantic/omission mutants survive; nested-extra, invalid-sensitive, deleted-name and deleted-labels mutants fail. Each exact outcome is in results.json.
- Proposed corrected test/docs: **12 passed**. Proposed test on head docs: **4 failed, 8 passed**.

The code probes and pytest outcomes are measured. API handler composition, frontend implications, historical ownership/date, and manual prose judgments are source-based inferences. I did not consult #528/#532 remotely; their behavior is verified from this exported implementation and its comments. Rows 4 and 8 of #628 were not treated as findings.
