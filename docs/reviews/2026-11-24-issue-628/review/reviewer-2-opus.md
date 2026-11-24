# PR #642: reviewer 2 (Opus 5.5, high)

Scope: `pr.diff` (174 lines), `codex-report.md`, `experiments/proposed_test.py`, and Codex's corrected `design.md` and
`second-pass.md`, all read in full. Code read in `head/cmapi/src/cmapi/`. No git repository, GitHub or cluster touched.
The test needs no database. All runs use the command of the brief, with `PYTHONDONTWRITEBYTECODE=1`.

Outputs (in `review-642/`):
- `r2/`: head with my rulings applied.
- `r2-outputs/fix.diff`: one patch against `head/`. It has 3 files and 173 lines.
- `r2-outputs/before.txt`: my test on head's docs. Result: **4 failed, 6 passed**.
- `r2-outputs/after.txt`: my test on `r2/`. Result: **10 passed**.
- `r2-outputs/check.txt`: the patch on a fresh copy of `head/` gives a tree identical to `r2/` (`diff -r`), and the test
  gives **10 passed**.
- `r2-outputs/mutants.py`, `mutants.txt`, `mutants/<name>/{head,r2}.log`: ten mutants, each run with the PR's test on
  head and with my test on r2.
- PR test on head, unchanged: **8 passed**.

Apply the patch from the repository root, or from a copy of `head/`: `patch -p1 -F0 < review-642/r2-outputs/fix.diff`.
Its headers are `head/…` and `r2/…`, so `-p1` strips them to repository paths.

## Rulings

### F1, the `in-sync` row: accepted, with my text

Evidence from the code:
- `plugins/namespaces/state.py:22-28`. The order is: `pending` if a request is open; `drift` if
  `compared and (drifted or not on_cluster)`; `in-sync` if `compared`; otherwise `unknown`.
- `plugins/namespaces/state.py:36`. `compared = git is not None and live_fresh`.
- `core/metadata.py:71`. `NAMED_CLASSES = ("governed", "team", "operatorOnly")`.
- `core/metadata.py:991-1000`. `drifted_keys` compares every key in `NAMED_CLASSES` and skips `is_live_only` keys.
  Its docstring says "Each governed, extra or operator-only key".

So `in-sync` needs four things: no open request, a comparison, the namespace on the cluster, and no differing key among
the governed, extra and operator-only keys. Head's row ("the same governed and extra keys") leaves out operator-only keys
and the namespace being on the cluster. It contradicts the drift row next to it.

I used Codex's "cmapi can compare Git with the cluster" for the comparison condition, because the code names it
`compared` (`state.py:36`). I did not write "the watch is fresh" or "Git holds the folder", because #627 may change the
`unknown` row (rows 4 and 8 of #628). I changed two things in Codex's row:
- I removed "except for keys that match `liveOnlyKeys`". The paragraph under the table already says that the comparison
  leaves those keys out, and the drift row does not repeat it either.
- I gave `drift` and `in-sync` the same opening, so each row reads as the other one turned around.

No cell in this table ends with a period, so the new cells do not end with one either.

Final rows:

```
| `drift` | No request is open, and cmapi can compare Git with the cluster. A governed, extra or operator-only key differs, or the cluster does not have the namespace. `driftedKeys` lists each key that differs |
| `in-sync` | No request is open, and cmapi can compare Git with the cluster. The cluster has the namespace. Each governed, extra and operator-only key has the same value in Git and on the cluster |
```

"Extra" keeps the code's own wording (`core/metadata.py:992`, the `NamespaceSync.drifted_keys` description in
`core/models.py`, and `plugins/namespaces/router.py:228`). In code, a key of an extra stanza is "governed" and an
`allowOther` key is "team" (`core/metadata.py:16-17`). The design uses "extra" for the second group everywhere. I did not
rename it.

Test: `test_in_sync_is_the_drift_row_turned_around`. It kills mutant M6, which is head's row. The PR's test misses M6.

### F2, the test strength: accepted in part

Codex's direction is right: check the read's example against the code that builds the read. I kept one check of that
kind, made stronger. I rejected the two exact-sentence tests.

**Kept, and made stronger: Codex's `test_read_edit_rules_match_build`.** Codex built `MetadataKeys({"system":
["cmapi.net/managed"]})`. That configuration makes the key a system key by construction, so the check assumes its own
answer. It also covers only the one key that it names.

My version loads a configuration file the repository ships, `examples/cluster-configs/policies/metadata-keys.company.yaml`.
The design's examples use the owner's sample keys (`company.net/*`, mnemonic `abc`), and this file configures them. The
test then calls the function the read itself calls, `undeclared_edits` (`plugins/namespaces/router.py:245-246`), on the
example's own `git` maps with environment `dev`. Each entry that the example shows under `git.edits` must be:
1. one that the read builds, which means a key of Git with no rule of its own (`core/metadata.py:953-954`), and
2. equal, as a `KeyEdit`, to what the read builds for that key.

I compare `KeyEdit` models, not dicts, because `removable` defaults to false (`core/models.py:363`) and `edit_rule` leaves
the member out for a key that is not disallowed (`core/metadata.py:943-947`).

This check replaces the PR's `(edit.mode, edit.removable) == ("fixed", False)` and `"git.edits" in design and
"removable" in design`. It kills:
- M5, the wrong reason;
- M7, an edit for a key that Git does not hold, which is head's example;
- M8, an extra edit for the declared key `company.net/cl`;
- M9, `sensitive: true`.

The PR's test misses all four.

**Rejected: `test_prose_contracts` and `test_active_short_replacements`.** They pin whole sentences of the style rewrite,
for example `"cmapi excludes live-only keys from the comparison."`. No meaning mutant needs a whole sentence to be killed.
Their only effect would be that any later rewording of a sentence fails a test.

**Kept: short assertions, each scoped to one row or paragraph, each killing one named mutant:**

| Assertion | Scope | Mutant it kills (the PR's test misses each one) |
|---|---|---|
| `"No request is open" in drift` | drift row | M4: "An open request exists" |
| `"422 \`validation-failed\`" in row` | row 1 of §3 | M2: "gets 200 accepted" |
| `NamespacePatch.model_validate({"namespace": …})` raises | the code | M10: `NamespacePatch` gains a `namespace` field |
| `"may remove that key"`, `"cannot set it"` | the `git.edits` paragraph | M3: "may set that key … cannot remove it" |
| `"passes when one strong tag is the current etag"` | Headers bullet | M1: "passes only when all tags are the current etag" |
| in-sync row: `"No request is open"`, `"operator-only"`, `"The cluster has the namespace"` | in-sync row | M6: head's row |

The `NamespacePatch` check is the only code-bound part of row 1's claim. `extra="forbid"` is at `core/models.py:23`.
`NamespacePatch`, at `core/models.py:252-259`, has no `name` or `namespace` field. `update_namespace` takes it as its
body (`plugins/namespaces/router.py:285`), and `main.py:213-220` maps the validation error to 422 `validation-failed`. I
found no other service test that sends an unknown field to the PATCH.

**Codex's other test details:**
- I agree that `_section` and the padding are not vacuous. They are kept as they were, with `padded` as a separate
  variable, so that `example` stays the parsed JSON.
- `assert view.git is not None` is redundant (Codex's audit, line 61). It is kept as one expression on the validate call,
  because it costs nothing and states the intent.

**Mutant runs** (`r2-outputs/mutants.txt`). Each mutant runs on a fresh copy and then the copy is removed. Head and r2
each get the same meaning change in their own wording.

```
M1-if-match-all-tags                  PR test: 8 passed   r2 test: 1 failed [test_row7_if_match_names_the_list_and_star]
M2-row1-200                           PR test: 8 passed   r2 test: 1 failed [test_row2_no_invented_rename_reason]
M3-removable-set-not-remove           PR test: 8 passed   r2 test: 1 failed [test_removable_says_remove_and_never_set]
M4-drift-open-request                 PR test: 8 passed   r2 test: 1 failed [test_row3_drift_names_operator_only_keys_and_a_missing_namespace]
M5-edit-reason                        PR test: 8 passed   r2 test: 1 failed [test_row5_read_example_validates_against_namespace_view]
M6-in-sync-governed-and-extra-only    PR test: 8 passed   r2 test: 1 failed [test_in_sync_is_the_drift_row_turned_around]
M7-edit-for-a-key-git-does-not-hold   PR test: 8 passed   r2 test: 1 failed [test_row5_read_example_validates_against_namespace_view]
M8-edit-for-a-declared-key            PR test: 8 passed   r2 test: 1 failed [test_row5_read_example_validates_against_namespace_view]
M9-edit-sensitive-true                PR test: 8 passed   r2 test: 1 failed [test_row5_read_example_validates_against_namespace_view]
M10-code-patch-body-takes-namespace   PR test: 8 passed   r2 test: 1 failed [test_row2_no_invented_rename_reason]
```

Each r2 failure is the intended assertion. The `E` lines are in `mutants/*/r2.log`, for example:
- M7: "the read gives no edit for labels cmapi.net/managed";
- M8: "the read gives no edit for labels company.net/cl";
- M10: "DID NOT RAISE".

### F3, the writing: accepted in part. Every sentence was checked against the code.

**Row 1.** Accepted, with one change. Codex wrote "cmapi returns 422 … if the body includes". I wrote "A body with a
`name` or `namespace` field gets 422", which is shorter and still active, and the original column did not name cmapi as
the actor. Evidence: the `extra="forbid"` and handler evidence above.

```
| 1 | The namespace name (the path) | Fixed | — (The path names the namespace. The tab has no row for it. A body with a `name` or `namespace` field gets 422 `validation-failed`.) |
```

**Drift row.** Accepted, as written by Codex, without the closing period. See F1.

**`git.edits` paragraph.** Rewritten by me. I rejected Codex's "For each undeclared or operator-only key in Git". It keeps
the ambiguity that the brief's claim 2 raised: `metadata-keys.yaml` lists `cmapi.net/managed` under `system`, so a reader
takes a system key to be "declared". Yet the example shows a system key in `git.edits`.

The code's actual rule is `key not in self.rules[kind]` (`core/metadata.py:953-954`). `rules` holds only the keys of the
required and extra stanzas (`core/metadata.py:765`). The loader refuses a system, operator-only or reserved key as a rule
(`:711-712`), and it refuses an adoption label that is also a rule (`:656-657`). So the keys in `git.edits` are exactly the
system, reserved, adoption, operator-only and `allowOther` keys, plus the keys that no rule admits. `GitMetadata.edits`
(`core/models.py:379-384`) lists the same classes. `router.py:226-227` says that the other keys' rules are in
`GET /api/v1/metadata-keys`.

Codex's "The change cannot set or change its value" is more complete than head's "never set it". This matches
`core/metadata.py:943` ("may be removed, never set or changed") and `core/models.py:363-364`. I kept that meaning.

I added "The example shows one entry of `git.edits`." Without it, the example reads as complete, and it is not (see "What
Codex missed", item 1).

```
`git.edits` gives the `x-cmapi-edit` of each key in Git that has no rule of its own in `metadata-keys.yaml`: a system,
reserved, adoption, operator-only or `allowOther` key, or a key that no rule admits. `GET /api/v1/metadata-keys` gives
the rules of the other keys (§4.3). The example shows one entry of `git.edits`. `removable: true` marks a key that no
rule admits. A change may remove that key (`null`). A change cannot set it or change its value (#528).
```

**`liveOnlyKeys` paragraph.** Rewritten by me. I rejected two parts of Codex's version:
- "The default is …". It does not say when the default applies. The default applies only when the stanza is absent: an
  explicit list, including an empty one, replaces it (`core/metadata.py:612`).
- "Configure these keys with …". This is an instruction to the operator inside a description of the design.

I also added "case-sensitive", because the match is `fnmatchcase` (`core/metadata.py:989`). "Only the cluster or its
controllers write" follows the code comment at `core/metadata.py:65-66`.

```
The comparison leaves out the keys that only the cluster or its controllers write. The stanza `liveOnlyKeys` of
`metadata-keys.yaml` lists them, as case-sensitive `fnmatch` globs. Without the stanza, the list is
`kubernetes.io/metadata.name`, `openshift.io/*`, `argocd.argoproj.io/*`, `app.kubernetes.io/instance`.
```

**second-pass.md, line 27.** I rejected Codex's text on two points:
- "The owner replaced row 3". The sources attribute only the discovery part to the owner (`README.md:15`, design T1 at
  `design.md:240`). No source in the export says who replaced `gitLabels` with `git: {labels, annotations}`. I kept the
  passive voice for that clause, because the actor is not known. A passive clause is better than an invented actor.
- "The detail read returns `git: {labels, annotations, edits}`", right after "the same day". `edits` came with #528,
  which merged in #529 (`build-tracker.md:89`, in the 2026-11-21 section). It was not part of the 2026-11-20 ruling. My
  text keeps the history right and still names `edits`.

```
Row 3 was replaced the same day. Discovery has no permission filter (the owner, #482). The detail read returns
`git: {labels, annotations}` instead of `gitLabels` and `gitAnnotations` (design.md §4.2). #528 later added `git.edits`.
```

**Tab picture ("every cluster cmapi manages").** No change. It is a label in an ASCII picture. `routers/me.py:36-42`
returns every registry snapshot behind `clusters:read`, with no `namespaces:write` filter.

## What Codex missed

1. **The read's example mixes the two shipped configurations, so its `git.edits` cannot be complete under either one
   (Low; fixed by the note and the test, not by rewriting the example).** I measured `undeclared_edits` for the example's
   Git keys:
   - Under `metadata-keys.company.yaml`, `cmapi.net/cost-center` and the annotation `cmapi.net/team-dl` are "Not allowed by
     this instance's rules." and removable. They are missing from the example's `edits`, which shows `"annotations": { }`.
   - Under `metadata-keys.yaml`, `company.net/cl` is disallowed and removable, and it is missing.

   The example's keys predate this PR, and examples are examples, so I did not rewrite them. Instead:
   - the paragraph now says that the example shows one entry of `git.edits`;
   - `cmapi.net/managed: "true"` is added to `git.labels`, because the read builds `edits` only from the keys that Git
     holds (`core/metadata.py:953`). Codex saw this point and left it as optional;
   - the test checks each entry that is shown, so a wrong or impossible entry fails (M5, M7, M8, M9).

2. **If-Match and weak tags (Low).** "A list of tags passes when one is the current etag" is not true for `W/"<current>"`.
   `core/etag.py` drops weak tags, and `check_if_match` matches only strong tags (`core/pipeline.py:136-147`; its
   docstring says "one strong tag it lists"). Codex measured `W/"current"` as 412 and did not carry it into the text. New
   text: "passes when one strong tag is the current etag". M1 is killed by the scoped assertion.

3. **The `liveOnlyKeys` default and case sensitivity.** These are in the F3 paragraph above (`core/metadata.py:612`,
   `:989`).

4. **Outside the changed lines, for the record only. I did not change these.**
   - The docstring of `plugins/namespaces/router.py:227-229` still says "`in-sync` when none does". It leaves out the
     cluster having the namespace, the same gap as F1, but in code. `state.py:13-20` has it right. If the coordinator
     wants it fixed, it is a one-line docstring change, which needs its own issue under the file-and-fix rule.
   - With both shipped configurations, every default `liveOnlyKeys` glob is also a reserved prefix: `kubernetes.io/`,
     `*.kubernetes.io/`, `openshift.io/` and `argocd.argoproj.io/`. So the comparison already leaves those keys out by
     class (`core/metadata.py:997`), and the stanza matters only for a configuration that admits such a key. This is not a
     defect, and the doc is true as written.

## Full final test (`cmapi/tests/service/test_design_481_matches_build.py`)

```python
"""The design of epic #481 matches the build (#628).

design.md and second-pass.md are the reference of stories #483 to #485. This test holds them to the code, so a later
ruling cannot leave them saying what the build replaced. It needs no database and no cluster.

Rows 4 and 8 of #628 (the `unknown` row of the sync table, and the list's `sync`) wait for the ruling of #627, so they are
not checked here.
"""
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from cmapi.core.metadata import DEFAULT_LIVE_ONLY_KEYS, MetadataKeys
from cmapi.core.models import KeyEdit, NamespacePatch, NamespaceView

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs" / "reviews" / "2026-11-20-epic-481-metadata-patch"
# The design's examples use the owner's sample keys (company.net/*, mnemonic abc), which this file configures.
COMPANY_KEYS = ROOT / "examples" / "cluster-configs" / "policies" / "metadata-keys.company.yaml"


@pytest.fixture(scope="module")
def design() -> str:
    return (DOCS / "design.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def second_pass() -> str:
    return (DOCS / "second-pass.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = re.search(r"^### ", text[start + len(heading):], re.M)
    return text[start:start + len(heading) + nxt.start()] if nxt else text[start:]


def _row(text: str, first_cell: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(f"| {first_cell} |"))


def test_row1_picture_has_no_permission_filter(design):
    assert "only clusters where you hold namespaces:write" not in design
    assert "every cluster cmapi manages" in design


def test_row2_no_invented_rename_reason(design):
    assert "A namespace cannot be renamed." not in design
    row = _row(design, "1")
    assert "tab has no row for it" in row
    assert "422 `validation-failed`" in row
    # The 422 holds because the PATCH body has no name field and refuses a field it does not know.
    with pytest.raises(ValidationError):
        NamespacePatch.model_validate({"namespace": "abc-payments-dev"})


def test_row3_drift_names_operator_only_keys_and_a_missing_namespace(design):
    drift = _row(design, "`drift`")
    assert "No request is open" in drift
    assert "operator-only" in drift
    assert "does not have the namespace" in drift


def test_in_sync_is_the_drift_row_turned_around(design):
    # plugins/namespaces/state.py: in-sync needs the namespace on the cluster, and drifted_keys compares operator-only keys.
    in_sync = _row(design, "`in-sync`")
    assert "No request is open" in in_sync
    assert "operator-only" in in_sync
    assert "The cluster has the namespace" in in_sync


def test_row5_read_example_validates_against_namespace_view(design):
    block = re.search(r"```json\n(.*?)```", _section(design, "### 4.2 The read"), re.S).group(1)
    example = json.loads(block)
    assert set(example["git"]) == {"labels", "annotations", "edits"}
    # The example shows the fields that the read adds; the other fields of the view take their usual values.
    padded = {"clusterId": "CRC", "env": "dev", "team": "payments", "tier": "small", "managed": True,
              "expiresAt": None, "openRequest": None, "mnemonic": "abc", **example}
    assert NamespaceView.model_validate(padded).git is not None
    # Each edit shown is the one the read builds for that key of Git (plugins/namespaces/router.py, undeclared_edits),
    # in the example's environment, dev.
    git = example["git"]
    built = MetadataKeys.load(COMPANY_KEYS).undeclared_edits(
        {"label": git["labels"], "annotation": git["annotations"]}, "dev")
    for kind in ("labels", "annotations"):
        for key, edit in git["edits"][kind].items():
            assert key in built[kind], f"the read gives no edit for {kind} {key}"
            assert KeyEdit.model_validate(edit) == KeyEdit.model_validate(built[kind][key]), key


def test_removable_says_remove_and_never_set(design):
    paragraph = next(p for p in design.split("\n\n") if p.startswith("`git.edits` gives"))
    assert "may remove that key" in paragraph
    assert "cannot set it" in paragraph


def test_row6_names_the_liveonlykeys_stanza_and_its_default(design):
    assert "a small, configurable ignore list" not in design
    assert "liveOnlyKeys" in design
    for key in DEFAULT_LIVE_ONLY_KEYS:
        assert key in design


def test_row7_if_match_names_the_list_and_star(design):
    headers = next(line for line in design.splitlines() if line.startswith("- **Headers.**"))
    following = design[design.index(headers):design.index("- **Permission.**")]
    assert "passes when one strong tag is the current etag" in following
    assert "`*` is 428" in following


def test_row9_second_pass_says_row3_was_replaced(second_pass):
    assert "Row 3 was replaced the same day" in second_pass
    assert "`git: {labels, annotations}`" in second_pass


def test_row10_second_pass_names_unknown(second_pass):
    assert "in-sync|pending|drift|unknown" in second_pass
    assert "in-sync|pending|drift," not in second_pass
```

## Full final doc changes against head

These are the hunks of `r2-outputs/fix.diff` for the two docs.

- `design.md:51`: row 1, as above.
- `design.md:75-76`: the Headers bullet. The second line now ends "… A list of tags in `If-Match` passes when one strong
  tag is the current etag. `*` is 428", and the next line is "  (the owner, #571)."
- `design.md:134`: `"labels": { "company.net/cl": "1", "cmapi.net/cost-center": "cc-4410", "cmapi.net/managed": "true",
  "…": "…" },`
- `design.md:154-155`: the drift and in-sync rows, as above.
- `design.md:158-161`: the `git.edits` paragraph, as above.
- `design.md:163-165`: the `liveOnlyKeys` paragraph, as above.
- `second-pass.md:27-28`: as above.

## Measured or inferred

**Measured:**
- every pytest result above;
- the ten mutant runs;
- `undeclared_edits` output under both shipped configurations;
- the patch applying with `-F0` to a fresh copy of head.

**Read from the source, not run:**
- the HTTP 422 of an unknown field, from `main.py:213-220` and `router.py:285`;
- the If-Match weak-tag 412, which I took from `pipeline.py` and from Codex's measurement.

**Not verified:** the history of #482, #528 and #571 on GitHub. I used only the repository's records.
