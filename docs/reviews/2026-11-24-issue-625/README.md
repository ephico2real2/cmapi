# #625 and #632: GitHub `read_folder` reads the folder's tree

PR #631. `GitHubProvider.read_folder` read the Contents listing of a manifest folder.

## What was wrong

- **#625.** The Contents API "has an upper limit of 1,000 files for a directory. If you need to retrieve more files, use
  the Git Trees API" (GitHub REST docs, Repository contents, API version 2022-11-28, fetched 2026-11-23). A folder past
  the cap was read short.
- **#632.** Reviewer 1 (Codex `gpt-6.2-astra` xhigh) found four more defects below the cap, and reviewer 2 (Opus 5.5 high)
  found a fifth. Each was measured on api.github.com (`review/reviewer-2-opus.md`, sources in
  `workbench/cmapi/review-631/r2-outputs/sources/`):
  1. A 403 on the listing read as an empty folder, so a managed namespace read as missing. A 403 on a file raised
     `KeyError`.
  2. A file over 1 MB answers 200 with `content: ""` and `encoding: none`, so a large manifest read as empty text.
  3. A listing types a submodule named `*.yaml` `"file"`; reading it gives `"type": "submodule"` and no content.
  4. `#`, `?` and `%` in a name were sent unencoded. RFC 3986, section 3.3: "The path is terminated by the first
     question mark ("?") or number sign ("#") character".
  5. A listing types a symlink to a file `"file"`, and reading it returns the target's text. The worker and the
     past-cap path skip symlinks, but this path read them, so a symlink could pull another namespace's manifest into a
     plan. No field of the Contents read tells the link apart.

## The fix

The fix is reviewer 2's design, which replaces reviewer 1's per-file patch. Reviewer 1's patch fails the symlink test
(`codex-variant.txt`).

- **Find the folder.** One Contents request with `Accept: application/vnd.github.object+json` returns the folder's
  object and its tree sha.
  - **Measured on torvalds/linux `include/linux`:** the object's `sha` (`9089cf2`) is the tree's sha. The object lists
    1,000 entries, and `git/trees/9089cf2` lists all 1,615, with `truncated: false`.
- **Read the tree.** `read_folder` reads that tree and keeps the regular `.yaml` entries (mode `100644` or `100755`), as
  `workspace._folder` does.
- **Read each manifest.** Each is read from `git/blobs/{sha}`. "The content in the response will always be Base64
  encoded", for blobs up to 100 MB (REST docs, Git blobs).
- **Encode the path.** The folder path goes through `urllib.parse.quote`.
- **Status codes.** 404 is an empty folder. Any other status raises `GitUnavailable`, because GitHub documents 403 for
  rate limits too.
- **Removed:** the 1,000-entry branch, `CONTENTS_DIRECTORY_LIMIT` and `_tree_manifests`.
- **Request cost.** M+2 requests for M manifests. Before the fix, the cost was M+1 below the cap and M+6 past it.

## Tests

- `test_github_read_folder_632.py` (new). On head `4367c93`: 10 failed, 15 passed. With the fix, all pass.
- Reviewer 2 ran 7 mutants, and all 7 were killed (`review/reviewer-2-mutants.txt`). The symlink cases kill reviewer 1's
  mode-filter mutant (finding 5).
- The mocks in the #625 and one-commit tests answer the object form. Their assertions are unchanged.

## Rulings (coordinator, Opus 5.5)

| Finding | Ruling |
|---|---|
| 1 to 5 | Accepted: each has a test that fails before and passes after. |
| Reviewer 2's 6 | Accepted. The live probe shows that the Contents API types a symlink `"file"`. |
| Reviewer 2's 7 | Accepted. The comment in `workspace.py` is corrected. |
| Reviewer 2's 8 | Accepted. A file path reads as `{}`, as the worker reads it. No caller passes one. |

**Outside this change.** A branch name goes into a URL path unquoted, in both the GitHub and Gitea providers. It is filed
as #638 and fixed on its own branch.

## Coordinator's run

Reviewer 2's patch was applied with `patch -p1 -F0` and merged with `main`.

- **The full service suite** in database `cmapi_wt616`, from 2026-11-24T10:05:14Z to 10:38:28Z. It ran after the gate
  (no other suite, 1-minute load 8.01): **2597 passed in 1986.32 s**.
- `doc-citations.py --check`: 0 problems.

## Not tested

- A live GitHub read of a name with `#`, `?` or `%`.
- A live 403.
- A file over 100 MB.
- A delete on a real repository through this path.
