# PR #576, reviewer 2 (Opus 5.5, high), 2026-11-23

PR #576 covers #565 and #570: the descriptions of the namespace `etag` and the declared `ETag` header. The head is 9dabcb7. I did not write it. Every path below is relative to `/Users/olasumbo/gitRepos/workbench/cmapi/review-576/`. I worked in `r2/`, a copy of `head/`. No git repository was touched and nothing was pushed. The throwaway `git init` in `head-git/` and `r2-git/` is explained under "What I ran".

## Verdict

Both of Codex's findings hold against the code. I accept both, with shorter wording than Codex proposed. I accept the fragility note on test 4, and I prove it with a mutation.

The patch is `r2-outputs/fix.diff`, against head 9dabcb7. `patch -p1` applies it cleanly from the repository root; checked on a fresh copy, and every file came out byte-identical to `r2/`. It changes five files:

- `cmapi/src/cmapi/core/models.py`
- `cmapi/src/cmapi/plugins/namespaces/router.py`
- `cmapi/tests/service/test_namespace_etag_doc_565.py`
- `cmapi/contract/openapi.json` (regenerated)
- `cmapi-portal-ui/src/api/schema.generated.ts` (regenerated)

Codex missed three things, all outside the PR's own lines. They are under "What Codex missed": a design-doc line that repeats #565's error, an RFC 9110 conformance gap in If-Match, and a FakeGit fidelity gap.

## Finding 1: the replay exception. Confirmed; accepted with shorter wording

**The code.**
- On a replay, `router.py:320-324` (PATCH), `:342-345` (DELETE) and `:363-366` (`_expiry_write`: `:extend`, `:set`, `:makePermanent`) call only `require_if_match(etag, ...)` and then `return replay`.
- `require_if_match` (`core/pipeline.py:103-109`) checks only that the header is present. The comparison, `if_match.strip('"') != etag` → 412, happens only in `plan_namespace` (`pipeline.py:218`) and `plan_delete` (`:434`). A replay never reaches either.

**It is deliberate.**
- The docstring of `require_if_match` (`pipeline.py:106-107`): "The ETag comparison is not repeated there, so a retry carrying its first ETag still gets its stored answer after Git moved".
- The route's own description says the same (`router.py:307-308`).
- `tests/service/test_if_match_before_replay_495.py::test_a_patch_retry_with_its_first_etag_is_still_replayed_after_git_moved` already proves it.

**RFC 9110 allows it.** Section 13.1.1, fetched 2026-11-23 from https://www.rfc-editor.org/rfc/rfc9110.txt: "Alternatively, if the request is a state-changing operation that appears to have already been applied to the selected representation, the origin server MAY respond with a 2xx (Successful) status code (i.e., the change requested by the user agent has already succeeded, but the user agent might not be aware of it, perhaps because the prior response was lost...)". So the field's flat "another value is 412" is false for replays. The behaviour itself is correct.

**Wording.** Codex's version is correct but long: "For a new request, …; an Idempotency-Key replay requires the header but returns the stored answer without comparing its value again". The rule is to over-build only when that is the only solution. The field description only has to stop being absolute. The detail ("still requires If-Match") is already in the operation's description at `router.py:307-308`. Chosen (`models.py:393-399`):

> …another value is 412 `precondition-failed`, except on an Idempotency-Key replay, which returns the request that key opened.

"Returns the request that key opened" is literally what `_replay` returns: `request_view(repo, row)` (`router.py:97`).

**The header description does not need it.** It makes no 412 claim: "Send it unchanged as `If-Match`…". It also points the reader to the body's `etag`, which carries the rule. Adding the clause there would be over-building.

## Finding 2: which files the tag covers. Confirmed; accepted, with "the `.yaml` files directly in the namespace's folder"

**Every real reader takes only regular `.yaml` files directly in the folder:**

| Reader | Lines | Filter |
|---|---|---|
| GitHub | `core/git/github.py:74-75` | contents API entries with `type == "file"` and a name ending in `.yaml`. A directory listing is not recursive |
| Gitea | `core/git/gitea.py:69-70` | entries of the folder's own tree (not recursive) with type `blob`, mode `100644`/`100755` and a name ending in `.yaml` |
| Local workspace | `core/git/workspace.py:299-308`, `:321-325` | `git ls-tree <treeish> -- <path>/` (not recursive), `blob`, mode `100644`/`100755`, `.yaml`. Its docstring says "The .yaml files directly in path" |

- `core/git/base.py:200` is abstract. There is no other backend: `core/git/` holds `base`, `github`, `gitea`, `workspace`, `oplog` and `transport`.
- `folder()` ends with `/` (`core/render/manifests.py:61-62`), so a sibling such as `payments-dev2/` never bleeds in.
- `folder_etag` (`pipeline.py:98-100`) hashes `plan_hash` of that mapping. `plan_hash` covers each path and its content (`manifests.py:92-97`).
- So a `README.md`, a `.yml`, a symlink or a file in a subfolder never changes the tag. Adding, removing or editing a direct `.yaml` file always changes it.

**Wording.** Codex proposed "It tracks the files read from the namespace's folder in Git; changes to other files need not change it". It is true, but it is vague to a client, who cannot know which files are "read". "The namespace's YAML files" would be clearer, but it is not quite true: a `.yml` file is YAML and is ignored, and so is a `.yaml` file in a subfolder. Chosen, in both descriptions (`models.py:396-397`, `router.py:207`):

> It changes when the `.yaml` files directly in the namespace's folder in Git change.

This states when the tag changes, which is how a validator behaves. It says nothing about how the tag is built, so it stays within the PR's RFC 9110 section 8.8.3.1 rationale.

I considered also saying "on the default branch", since a request's branch does not move the tag until it merges. I did not add it: it is over-building, and "in Git" already means the source of truth.

## Codex's proposed tests: run (Codex could not)

I wrote both of Codex's tests as proposed (`r2-outputs/test_codex_proposed_576.py`). FakeGit's API was as Codex assumed: `git.branches["main"][path] = …` followed by `git._sha("main")`. No changes were needed.

| Run | Result |
|---|---|
| Codex's tests on head (`r2-outputs/codex-tests-on-head.txt`) | 2 failed, at the string asserts only. The behaviour asserts pass: a replay with the old tag after Git moved is 202 with the same `requestId`, and a `README.md` leaves the tag unchanged |
| The same tests with my string asserts (`r2-outputs/test_codex_proposed_576_r2asserts.py`), plus the #495 file (`r2-outputs/codex-tests-r2-asserts.txt`) | on head: 2 failed, 7 passed. On the fix: 9 passed |

**What I shipped instead (in `test_namespace_etag_doc_565.py`):**

- `test_the_namespace_etag_says_a_replay_is_not_compared`: text only. It asserts that "412 `precondition-failed`" and "Idempotency-Key replay" are in `NamespaceView.etag`. I dropped Codex's behavioural setup, because it duplicates `test_if_match_before_replay_495.py::test_a_patch_retry_with_its_first_etag_is_still_replayed_after_git_moved` line for line. The docstring names that test as the behaviour proof.
- `test_the_etag_changes_with_the_yaml_files_of_the_folder_and_says_so`: behaviour plus text. No other test covers this behaviour. After a create:
  - adding `README.md` and `notes.yml` leaves the body tag and the header unchanged;
  - editing `namespace.yaml` changes the tag, and the header stays the body value quoted. This is a positive control, which Codex's test lacked;
  - both descriptions contain "`.yaml` files directly in the namespace's folder".

  It does not test a nested subfolder file, because FakeGit diverges there (see M3).

## Test quality: the first three tests match strings. Acceptable, with a rule

Prose cannot be checked for meaning, so a stronger test is not practical. The right shape for documentation is a stated contract of required phrases, where each claim the phrases make is proven by a behaviour test:

| Claim | Proven by |
|---|---|
| 412 | test 4 |
| the replay exception | the #495 test |
| which files | the new files test |

The patch follows that shape. Codex's point stands that "If-Match always succeeds" would pass tests 1-3. With the patch, that rewrite now fails `test_the_namespace_etag_says_a_replay_is_not_compared`, because "412 `precondition-failed`" is required. I would not add more phrase checks.

## Test 4's stale tag: fragile. Proven and fixed

The fixture's real tag is deterministic: `7a243337bc851f98` on two separate runs. That is the natural value for someone to copy into the example, since "an example must look like a real value". I set both examples to it (a mutation in a scratch copy):

- the original test 4 failed with `assert (200 == 412)`;
- the fixed test 4 passed.

**Fix (`test_namespace_etag_doc_565.py:100-103`):** the stale `If-Match` is the create plan's tag, `"0"`, which the same test already asserts is `folder_etag({})`. Two reasons:

- It is a tag the folder really had before the create, so it is a realistic stale value.
- `folder_etag` returns `"0"` only for an empty folder (`pipeline.py:100`), and the line above asserts a 16-hex tag. It can never match, whatever the example is.

I preferred it to `"0000000000000000"`, which is a valid 16-hex value. It is astronomically unlikely to match, but "never" cannot be proven for it.

## Outputs

After the fix, I regenerated:

- `openapi.json`: `CMAPI_WRITE_CONTRACT=1 … pytest tests/service/test_api_docs.py -k committed_contract`. Only the two descriptions changed.
- `schema.generated.ts`: `npm run api:types` with the generator's node_modules symlinked read-only from `wt-565`. Only the two comments changed, and `permissions.generated.ts` is unchanged. `npm run api:types -- --check` printed "ok - the API types match cmapi/contract/openapi.json".

`r2-outputs/suites-before-after.txt` holds the runs of `test_namespace_etag_doc_565.py`, `test_api_docs.py`, `test_api_standard.py` and `test_doc_citations.py`, on database `cmapi_r2_576`:

```
== head-git   (head code + the new test file)
FAILED tests/service/test_namespace_etag_doc_565.py::test_the_namespace_etag_says_a_replay_is_not_compared
FAILED tests/service/test_namespace_etag_doc_565.py::test_the_etag_changes_with_the_yaml_files_of_the_folder_and_says_so
2 failed, 219 passed in 52.68s
== r2-git     (the fix)
221 passed in 52.86s
```

`python3 scripts/doc-citations.py --check` (`r2-outputs/doc-citations.txt`): head "doc-citations: 0 problems", exit 0; fix "doc-citations: 0 problems", exit 0. `router.py` keeps its line count, so the `:232` citation still holds. `models.py` grows by 2 lines, and no citation points into it after line 393.

`scripts/api-examples-doc.py --check` on the fix: exit 0.

## What Codex missed

### M1. docs/02 still describes the etag as a Git SHA: the same error as #565, in the design doc

- `docs/02-technical-design-v2.md:131`: "GET returns an ETag (the Git blob SHA of the object's file)". The built value is `folder_etag`, a hash over the folder's direct `.yaml` files, and the descriptions now say it is opaque.
- `:934` (`base_etag CHAR(40) -- Git blob SHA …`) is a design column that was never built: `base_etag` does not occur anywhere in `cmapi/`.
- Codex's "no public namespace-tag description still says commit or SHA" covered the OpenAPI document only.
- `docs/02` exports a live Claude Doc, so per CLAUDE.md the live doc is edited first. Proposed text for row 131:

> | Optimistic concurrency | GET returns an ETag, opaque (RFC 9110 section 8.8.3.1): it changes when the `.yaml` files directly in the object's folder in Git change. PUT, PATCH and DELETE need If-Match, else 428; a stale ETag returns 412; an Idempotency-Key replay returns its request without comparing it |

For `:934`, mark the column as not built, or describe it as "the etag the change was planned against". The coordinator's call.

### M2. Pre-existing, outside this PR: If-Match `*` and a list of tags are 412 on an existing namespace

**Measured on head** (`r2-outputs/if-match-forms-probe.txt`), PATCH with `?dryRun=true`:

| If-Match | Answer |
|---|---|
| `*` | 412 |
| `"0", "<current>"` | 412 |
| `W/"<current>"` | 412 (correct: the comparison must be strong) |
| `"<current>"` | 200 |

**What RFC 9110 says.** Section 13.1.1 (same fetch): "the origin server MUST evaluate the If-Match condition per Section 13.2 prior to performing the method". The evaluation rules are "1. If the field value is "*", the condition is true if the origin server has a current representation for the target resource. 2. If the field value is a list of entity tags, the condition is true if any of the listed tags match the entity tag of the selected representation."

The cause is `if_match.strip('"') != etag` at `pipeline.py:218` and `:434`.

The fix is `r2-outputs/if-match-forms.diff`, against head:

```python
def if_match_holds(if_match: str, etag: str) -> bool:
    """RFC 9110 section 13.1.1: "*" holds for a namespace that exists, and a list holds when one of its tags equals the
    current one by the strong comparison (section 8.8.3.2), so a weak tag never does. A tag sent without its quotes, as
    clients have always been allowed to, still counts."""
    if if_match.strip() == "*":
        return True
    return any(not tag.startswith("W/") and tag.strip('"') == etag for tag in (t.strip() for t in if_match.split(",")))
```

Both sites become `if not if_match_holds(if_match, etag):`.

The bare-tag leniency is kept on purpose. Several tests send the tag unquoted, for example `test_flow.py:263` and `test_custom_tier_change.py:76`.

The test is `r2-outputs/test_if_match_forms.py`, parametrized over 7 forms:

| Code | Result |
|---|---|
| head | 2 failed (`*`, the list), 5 passed |
| with the fix | the 7 forms pass, and with the #495, #565, `test_flow`, `test_custom_tier_change` and `test_expirations` files, 84 passed |

**Two notes for whoever files it:**

- The helper moves `pipeline.py` by 9 lines, so the `docs/14:177` citations (`pipeline.py:198`, `:424`) need `doc-citations.py --relocate` or a hand edit in that PR.
- Refusing `*` on purpose, for example with 428 and a documented reason, is the alternative, and the owner's research ruling decides between them. Silently treating a true condition as 412 is the conformance gap either way.

### M3. Test double: FakeGit reads nested `.yaml` files; every real reader takes direct children only

`tests/service/conftest.py:176` filters `p.startswith(path) and p.endswith(".yaml")`, so it also includes `payments-dev/sub/x.yaml`. GitHub, Gitea and the workspace never do (Finding 2). The proposed fix is `r2-outputs/fakegit-direct-files.diff`:

```python
        files = {p: t for p, t in self.branches[branch].items()            # direct .yaml files only, as every real reader
                 if p.startswith(path) and "/" not in p[len(path):] and p.endswith(".yaml")}
```

Result on `test_flow.py`, `test_namespace_etag_doc_565.py`, `test_git_layer.py` and `test_if_match_before_replay_495.py`: 111 passed in 234.79 s. Not run on the full service suite. With it, the files test could also assert that a nested `.yaml` file leaves the tag unchanged.

## What I ran, and what I did not

**Ran:**
- Codex's two tests: as proposed, and with my asserts, before and after the fix.
- The two new tests, before and after.
- The four required test files, before and after.
- `doc-citations.py --check`, before and after.
- `api-examples-doc.py --check`.
- `npm run api:types`, and `--check`.
- The test 4 mutation.
- The If-Match forms probe, and its fix and test in a separate copy.
- The FakeGit change on four test files.

**About the throwaway git repositories.** `doc-citations.py` and `test_doc_citations.py` need `git ls-files`. So I created two throwaway repositories, `head-git/` and `r2-git/` (`git init` + `git add -A`, no commits), in my own copies. This is the same thing `test_doc_citations.py` does in `tmp_path`. No existing repository was touched.

**Database.** I created `cmapi_r2_576` on the shared PostgreSQL at 127.0.0.1:55432, using the conftest's test credentials. It is left in place, and the coordinator may drop it.

**Did not run:**
- the full service suite;
- Spectral (`contract/lint.sh`), `lint-test.py`, `gate-test.sh` and oasdiff. The change touches description strings only, but they were not run;
- a browser view of Swagger UI or ReDoc;
- anything on CRC, LDAP or Keycloak.

No permission refusals.
