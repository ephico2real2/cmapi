# #628: design.md of epic #481 says what the build does

PR #642 brings `design.md` and `second-pass.md` of epic #481 into line with the code at `aceaded`. It covers rows 1, 2, 3, 5, 6, 7, 9 and 10 of #628. Rows 4 and 8 wait for the owner's ruling on #627.

## Who wrote what

| Role | Who | What |
|---|---|---|
| Implementer | Sonnet 5.5 | The first edits, and `test_design_481_matches_build.py`. Owner, 2026-11-21: Sonnet drafts the documentation. |
| Reviewer 1 | Codex `gpt-6.1-sol` (a docs change) | `review/reviewer-1-codex-sol.md`: two Medium findings (F1, F2) and one Low (F3). |
| Reviewer 2 | A separate Opus 5.5 agent at high | `review/reviewer-2-opus.md`: rules on each finding, and finds two more. |
| Coordinator | Opus 5.5 | Applied reviewer 2's patch, ran the tests, made the rulings. |

## Rulings (coordinator)

| Finding | Ruling |
|---|---|
| F1. The `in-sync` row conflicts with the corrected drift row. | **Accepted, with reviewer 2's wording.** No request is open, the comparison ran, the cluster has the namespace, and each governed, extra and operator-only key matches. Source: `plugins/namespaces/state.py:22-36`, `core/metadata.py:71`. |
| F2. The test checks words, not rules. | **Accepted in part.** The example's `edits` are checked through the real `undeclared_edits`, on the shipped company configuration. Codex's two tests that pin whole sentences are rejected: they pin wording, not meaning (over-build only if it is the only solution). Reviewer 2 ran 10 mutants: the PR's test misses all 10, and the new test kills all 10 (`r2-outputs/mutants.txt`). |
| F3. Long and passive sentences. | **Accepted in part.** ASD-STE100 rewrites are kept where they are accurate. The `git.edits` and `liveOnlyKeys` paragraphs are corrected: they now name the key classes, say that the default applies only when the stanza is absent, and say that the match is case-sensitive (`fnmatchcase`). The history in `second-pass.md` is kept as the records give it. |
| Reviewer 2: the read example mixes the two shipped configurations. | **Accepted.** The doc now says that the example shows one entry of `git.edits`, and `cmapi.net/managed` is added to `git.labels`. |
| Reviewer 2: If-Match matches a strong tag only. | **Accepted.** The doc now says "passes when one strong tag is the current etag" (`core/pipeline.py:136-147`). |
| Reviewer 2: the namespace read's docstring has the same gap as F1, and it is served in the API document. | **Filed as #643.** That change touches the contract, and its `unknown` wording depends on #627. |

## Coordinator's run

| Check | Result |
|---|---|
| `test_design_481_matches_build.py` | 4 failed and 6 passed before reviewer 2's patch; 10 passed after. |
| With the doc-citation, namespace-change-doc, namespace-etag-doc and data-model-doc tests | 38 passed. |
| `doc-citations.py --check` | 0 problems. |

The full service suite was not run on this change: CRC run 38 held the machine. The change touches two review documents and adds one test. CI runs the full suite on the PR head.
