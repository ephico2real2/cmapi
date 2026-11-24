# #638: a branch name, a ref or a path in a URL path is quoted

PR #639. Reviewer 2 (Opus 5.5 high) of PR #631 found the defect and wrote the first fix. The coordinator applied it on
`main` at `baa932b`.

## What was wrong

The Git providers and the bootstrap job put a branch name into a URL path raw. Git accepts `#` and `%` in a branch name:
`git check-ref-format --branch 'release#2'` prints `release#2`. RFC 3986, section 3.3, says: "The path is terminated by
the first question mark ("?") or number sign ("#") character". Section 2.4 makes a `%` that is data `%25`. So a default
branch named `release#2` read the head of `release`, and `rel%41` read `relA`.

## Review

- **Reviewer 1:** Codex `gpt-6.2-astra` at xhigh (`review/reviewer-1-codex-astra.md`). It asked for changes, with 7
  findings.
- **Reviewer 2:** a separate Opus 5.5 agent at high (`review/reviewer-2-opus.md`). It confirmed all 7, lowered two of
  them, and proved its rulings on a disposable Gitea 1.25.5. That is the chart's pinned digest, removed afterwards.

| # | Finding | Ruling (coordinator, Opus 5.5) |
|---|---|---|
| F7, High | `tools/git_bootstrap.py` built its own seed-branch GET and protection GET and PATCH unquoted | Accepted. Measured on Gitea 1.25.5: a second run of git-bootstrap, as the post-upgrade hook runs it, exited 1 for `team/main` and for `release#2` before the fix, and 0 after it |
| F1 | GitHub `branches/{branch}` is one path parameter. GitHub's REST troubleshooting page asks for a slash as `%2F` | Accepted as Low: `quote(branch, safe='')`. Live, unauthenticated, GitHub served both spellings of `release/1.85` on microsoft/vscode with the same sha |
| F2, F4 | Gitea `branch_protections/{name}` takes one segment: a literal slash gets 404 and `%2F` gets 200. A create of an existing rule answers 403, not 422 | Resolved by deleting `GiteaProvider.protect_default_branch`. Nothing in production calls it; git-bootstrap protects the branch with its own code. The owner's rule is to over-build only when it is the only solution |
| F3 | The PR's test asserted the decoded path, which passes on base for `team/main` | Accepted. One module, `test_branch_name_in_url_path.py`, asserts `request.url.raw_path` |
| F5 | Gitea `_blob_sha` left the file path unquoted. Live, `dir/m%41.yaml` returned the blob of `dir/mA.yaml` | Accepted as Low: `quote(path)`. Planned file names come from Kubernetes names, which cannot hold `#`, `?` or `%` |
| F6 | Gitea `contains` left the Argo CD revision unquoted | Accepted as hardening: `quote(revision)` |

- **Slashes.** Gitea routes branches, compare and contents with a `/*` wildcard, so a `/` stays a `/` there.
- **Tests.**
  - The merged module: 14 failed on base, 5 failed on head, 17 passed with the fix.
  - Reviewer 2 ran 11 mutants of the final fix, and all 11 were killed.
- **Filed outside this PR:** #640. The Keycloak directory quotes a realm that it takes from the issuer URL, which is
  already encoded. It is not proven yet.

## Coordinator's run

Reviewer 2's patch was applied with `patch -p1 -F0` on `main` `baa932b`.

- **The full service suite** in database `cmapi_wt605`, from 2026-11-24T11:33:01Z to 12:08:15Z. It ran after the gate
  (no other suite, 1-minute load 9.11): **2630 passed in 2109.04 s**.
- `doc-citations.py --check`: 0 problems.
- No reference to `protect_default_branch` is left outside `docs/reviews/`.

## Not tested

- GitHub branch names with `#` or `%`.
- Gitea DELETE and contents with `%2F`.
- `contains` against a live Argo CD.
- CRC.
