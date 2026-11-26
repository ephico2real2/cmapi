# #732: a request can add a missing derived or prefix key (PR #735)

**The ruling** (issue #732, 2026-11-26) rests on the owner's decision 2 on #26: "Later updates go through without it; it stays a finding until someone chooses to add it."
- A change to an existing namespace may add a missing automatic key with exactly the derived value, or a missing `namespacePrefix` key with exactly the name's start.
- Any other value is still refused.

**Reviewers:**
- **Reviewer 1:** Codex gpt-6.2-astra xhigh. The brief planned one reviewer; it requested changes.
- **Reviewer 2:** Opus 5.5 high, on PostgreSQL. Added under the owner's rule that every Codex patch gets a full Opus read.

| Finding | Ruling |
|---|---|
| F1: an invalid derived label is accepted (when the instance name is not a valid label) | **Fixed** |
| F2: an empty source is accepted (empty instance name or environment) | **Fixed** |
| F3: the finding offers a repair that is then refused, for a key Git holds as `""` | **Fixed**: the finding now says a change cannot add it |
| F4: the portal stand-in refuses valid additions | **Fixed**, cut to two lines by reviewer 2 |
| Reviewer 2: the derived-name test never checked the written label | **Fixed**: assertions on the rendered file and on `metadataDiff` |

**Kept as is (#481), with the question for the owner in #736:** a fixed key that Git holds as `""` stays a finding, because a change can neither replace nor remove it. Treating an empty value as missing would be a one-condition change.

**Follow-ups:**
- The portal's change tab still locks fixed and automatic keys (`namespaceChange.ts`). So "a request can add it" holds for the API, but not yet in the portal: a story #26 follow-up.
- No load-time check of `instance.name`. This predates the PR, and goes to Backlog #736.

**Runs (reviewer 2):**
- service tests: 61 passed;
- `tests/core`: 921 passed, 115 skipped;
- stand-in: 7 passed;
- mutants: 10 of 10 killed.
