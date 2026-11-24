# #626: a namespace's folder that holds a name, or a manifest, that is not UTF-8

The implementer's record. Opus 5.5 at `high` wrote it on 2026-11-24, on `fix/626-non-utf8-names` from `ff5e992`. The reviews
will go beside it.

## The defect, as measured

The issue was read from the code. Measured on `ff5e992` (main's `src` plus a stub `NotUtf8` class so the test module imports),
with `cmapi/tests/service/test_non_utf8_names_626.py`, git 2.55.0, PostgreSQL 16.15, on this Mac:

- **The Git layer (the worker).** `workspace._folder` and `_entries` decoded `git ls-tree -z` as strict UTF-8. A name such as
  `b"caf\xe9.yaml"` raised `UnicodeDecodeError` in `read_folder` and in `list_folder` (#616's whole-folder listing), and a
  manifest whose text is Latin-1 raised it in `read_folder`. `changed_paths` raised it on a branch that changes such a name.
- **The plan, where the API reads through the Git layer** (the `layer` fixture, one process with the Git layer): the issue
  said a 500. **I retract that part of the issue.** The answer was **422 `validation-failed`**, its detail Python's codec
  message ("'utf-8' codec can't decode byte 0xe9 in position 93: invalid continuation byte"). `UnicodeDecodeError` is a
  `ValueError`, and `main.py`'s `value_error_handler` turns every `ValueError` into that 422. The caller is blamed for the
  folder's state, and the detail is an implementation message.
- **The plan in production.** The API process has no Git layer (`core/context.py`: `git_layer=settings.component ==
  "worker"`), so it reads GitHub through REST. **I retract "a 500 at the plan" there too:** the read does not fail.
  GitHub answers the name with U+FFFD in place of the byte (below), so `read_folder` returned the manifest
  `caf�.yaml`. A change then planned that path as removed, and a delete listed it, though no such path exists in Git.
  A manifest whose text is not UTF-8 raised `UnicodeDecodeError` in `_blob_text`, so 422 `validation-failed` again.
- **The worker job that pushes.** A name that reached the folder after the plan made `push_branch` raise
  `UnicodeDecodeError` on each of its five attempts. The request then ended `pr_failed` with the codec message.
- **The Gitea stand-in.** Same as GitHub: the name came back with U+FFFD (read from Gitea's source, not measured on a running
  Gitea), and a Latin-1 manifest raised `UnicodeDecodeError`.

16 of the file's 17 tests failed before the fix (`test-before.txt`), and all 17 pass after it (`test-after.txt`). The
one that passes on main is `test_the_gitea_merge_check_reads_a_folder_it_cannot_name_as_not_the_plans`. On main, Gitea's
lossy read returned the U+FFFD name, which already compared unequal to the plan, so main refused that merge by accident. The
test guards the fix's new branch, where the read raises `NotUtf8` and the check reads main's head itself.

### GitHub, measured on api.github.com, 2026-11-24 13:04 UTC

An orphan commit with `ns/caf\xe9.yaml`, `ns/plain.yaml` and `ns/sub/caf\xe9.txt`, built with `git mktree` and pushed to the
throwaway branch `probe/626-latin1-name` of this repository. The answers are in `github-probe/`. No workflow runs on a push
to a branch other than `main`. The branch was deleted after the reads, and `GET branches/probe%2F626-latin1-name` then
answered 404.

| Endpoint (version 2022-11-28) | The name in the answer | The bytes on the wire |
|---|---|---|
| `GET git/trees/{ns tree}` | `caf�.yaml` | `caf\xef\xbf\xbd.yaml` |
| `GET git/trees/{ns tree}?recursive=1` | `caf�.yaml`, `sub/caf�.txt` | the same |
| `GET contents/ns?ref=` (array and object forms) | `ns/caf�.yaml` | the same |

GitHub accepted the push with the name. Each answer was 200, with no error and no flag on the entry. The byte is lost: from
the answer alone, a name that GitHub gave with U+FFFD cannot be told from one that holds U+FFFD itself.

## Sources, fetched 2026-11-24

- **git, `Documentation/i18n.adoc`** (<https://raw.githubusercontent.com/git/git/master/Documentation/i18n.adoc>): "Path names
  are encoded in UTF-8 normalization form C." It continues: "Note that Git at the core level treats path names simply as
  sequences of non-NUL bytes, there are no path name encoding conversions (except on Mac and Windows)", and "many Git-based
  tools simply assume path names to be UTF-8 and will fail to display other encodings correctly."
- **git-ls-tree(1)** (<https://git-scm.com/docs/git-ls-tree>, unchanged since 2.42.0): `-z`: "\0 line termination on output
  and do not quote filenames". OUTPUT FORMAT: "Without the `-z` option, pathnames with "unusual" characters are quoted as
  explained for the configuration variable `core.quotePath`... Using `-z` the filename is output verbatim and the line is
  terminated by a NUL byte."
- **git-config(1), `core.quotePath`** (<https://raw.githubusercontent.com/git/git/master/Documentation/config/core.adoc>):
  "Commands that output paths (e.g. 'ls-files', 'diff'), will quote "unusual" characters in the pathname by enclosing the
  pathname in double-quotes and escaping those characters with backslashes in the same way C escapes control characters
  ... or bytes with values larger than 0x80 (e.g. octal `\302\265` for "micro" in UTF-8)." And: "Many commands can output
  pathnames completely verbatim using the `-z` option. The default value is true."
- **Python, `os`** (<https://docs.python.org/3/library/os.html>, 3.15.2): "On some systems, conversion using the file system
  encoding may fail. In this case, Python uses the surrogateescape encoding error handler, which means that undecodable
  bytes are replaced by a Unicode character U+DCxx on decoding, and these are again translated to the original byte on
  encoding." `os.fsdecode`: "Decode the path-like filename from the filesystem encoding and error handler".
- **Python, `codecs`** (<https://docs.python.org/3/library/codecs.html>, 3.15.2): `'surrogateescape'`: "On decoding, replace
  byte with individual surrogate code ranging from U+DC80 to U+DCFF. This code will then be turned back into the same byte
  when the 'surrogateescape' error handler is used when encoding the data." `'backslashreplace'`: "On decoding, use
  hexadecimal form of byte value with format `\xhh`."
- **PEP 383** (<https://peps.python.org/pep-0383/>): such a string "only 'works' if the data get converted back to bytes with
  the surrogateescape error handler also"; "Encoding the data with the locale's encoding and the (default) strict error
  handler will raise an exception".
- **RFC 9457** (<https://www.rfc-editor.org/rfc/rfc9457>), 3.1.4: "The "detail" string, if present, ought to focus on helping
  the client correct the problem, rather than giving debugging information." It adds: "Consumers SHOULD NOT parse the
  "detail" member for information; extensions are more suitable". 3.2: "Problem type definitions MAY extend the problem
  details object with additional members". 5: "avoid making implementation details such as a stack dump available through
  the HTTP interface".
- **RFC 9110** (<https://www.rfc-editor.org/rfc/rfc9110>), 15.5.10: "The 409 (Conflict) status code indicates that the request
  could not be completed due to a conflict with the current state of the target resource. This code is used in situations
  where the user might be able to resolve the conflict and resubmit the request. The server SHOULD generate content that
  includes enough information for a user to recognize the source of the conflict."
- **Go, `encoding/json`** (<https://pkg.go.dev/encoding/json>): "String values encode as JSON strings coerced to valid UTF-8,
  replacing invalid bytes with the Unicode replacement rune."
- **Gitea 1.25**: `modules/json/json.go` sets `DefaultJSONHandler = JSONiter{jsoniter.ConfigCompatibleWithStandardLibrary}`,
  and that configuration has `EscapeHTML: true` (json-iterator `config.go`). `writeStringSlowPathWithHTMLEscaped`
  (json-iterator `stream_str.go`, line 276) writes `�` when `c == utf8.RuneError && size == 1`. `GitEntry.Path` is a Go
  string (`modules/structs/repo_tree.go`). Read from the source; not measured on a running Gitea.

## The options

1. **Carry the names as bytes.** A plan's files, its `prev`, the request row (PostgreSQL `jsonb`), the API's JSON and the
   portal all hold paths as text. JSON has no bytes (RFC 8259 strings are Unicode). Rejected: it changes every layer, and
   the API process still could not name such a file, because GitHub's and Gitea's REST answers have already lost the byte.
2. **surrogateescape round-tripping** (PEP 383). The Git layer could round-trip `caf\udce9.yaml` back to the bytes for
   `git rm`. Rejected, measured:
   - PostgreSQL 16.15 refuses `{"caf\udce9.yaml": 1}` as `jsonb` ("invalid input syntax for type json").
   - `json.dumps(..., ensure_ascii=False).encode("utf-8")` raises "surrogates not allowed", so the API could not answer it.
   - The plan runs in the API process, on REST, where the name is `caf�.yaml`, not `caf\udce9.yaml`. The worker's
     listing would never equal the plan's, so every such delete would end superseded. PEP 383 says itself that the string
     only works when it is turned back with the same handler, which JSON and the database never do.

   (`surrogateescape-probe.txt`.)
3. **Refuse the folder at the plan, naming each path, and change nothing. Chosen.** A name cmapi carries is valid UTF-8 with
   no U+FFFD, on every provider. This is what git's own documentation expects ("Path names are encoded in UTF-8"), and it
   is the one rule the API process (REST) and the worker (Git) can both check. The person fixes the folder in Git and sends
   the request again.

A delete never skips a file it cannot name: the listing raises before a plan exists.

## What changed

- **`core/git/base.py`.** `NotUtf8(paths, part)`, which is not `GitUnavailable`: Git answered, and a retry reads the same
  folder. Four helpers:
  - `git_name`: raw bytes to text, with a flag for whether the name can be carried. A name that cannot is shown with `\xNN`,
    by `backslashreplace`.
  - `refuse_lost_names`: a REST name with U+FFFD.
  - `manifest_text`: strict UTF-8 for each manifest; it names every manifest that fails.
  - `as_plan`: a comparison with the plan that reads `NotUtf8` as "not the plan's".

  `HostGitProvider.merge_check` (the Gitea stand-in) reads such a main as not the plan's base.
- **`core/git/workspace.py`.** `_listing` keeps each `ls-tree -z` name as bytes. `_folder` refuses a `.yaml` name that cannot
  be carried, and a manifest that is not UTF-8. `_entries` refuses any name, at any depth. `changed_paths` and `_adoptable`
  show such a name escaped and compare it, which is a path outside the plan, never an error. `merge_check` and `_adoptable`
  read such a folder as not the plan's.
- **`core/git/github.py`, `core/git/gitea.py`.** `read_folder` refuses a `.yaml` name with U+FFFD before any blob read, and a
  manifest that is not UTF-8. `list_folder` refuses any path with U+FFFD.
- **`core/pipeline.py`.** `_read_folder` and `removable_folder` answer 409 `folder-not-utf8`. Its `paths` member lists each
  path, and the detail names up to three. This covers every write that plans from the folder, and `GET` of the namespace.
- **`jobs/push_branch.py`.** A folder that cannot be read this way is a folder that changed since the plan: the request is
  superseded (`base_changed`), with the path in the note. No branch is pushed, and nothing is retried.
- **The problem registry.** `folder-not-utf8` is added to `core/docs.py` and `core/problem_docs.py`, and to the namespace
  routes' lists (`WRITE_PROBLEMS`, and `GET` of a namespace). The contract, samples, `docs/04` and the portal's types are
  regenerated.

Why 409 and not 422: the request itself is valid, and the namespace's folder in Git is what conflicts with it. The caller
resolves it in Git and sends the request again, as RFC 9110 describes 409 and as `folder-holds-submodule` (#616) already
does. `paths` is an extension member, so a client reads the paths without parsing `detail` (RFC 9457, 3.1.4 and 3.2).

Why `\xNN` and not git's octal quoting: the escaping is Python's documented `backslashreplace`. Each backslash of a path in
`paths` is doubled first, as Git's own quoting always escapes one (`core.quotePath`: "Double-quotes, backslash and control
characters are always escaped"; `quote.c`, `cq_lookup`), so each shown path stands for one name only (reviewer 1's F4,
widened by reviewer 2 to every path of `paths`). Git shows the same name as `"caf\351.yaml"` with its default
`core.quotePath`; the problem page says so, so a person can match the two.

## The reads after the plan (reviewer 1's findings F1, F2, F3, F7)

- `pr_checks` reads main's folder for the validators before it runs the merge check, so such a name there supersedes the
  request, as the merge check would (F2).
- `merge`'s `_merged` reads the folder at the merge sha after the host merged: such a folder is not the plan's, so the request
  is merged and then `sync_failed`, with the path in the note (F1). Before, it was five errors and then `failed` (argocd) or
  `merge_failed` (apply), with the PR merged on the host. Argo CD syncs such a main all the same: a directory application
  loads every `.yaml` file of the folder whatever the bytes of its name, and reads a text that is not UTF-8 with U+FFFD in
  place of each bad byte (argo-cd `reposerver/repository/repository.go`, `utfutil.OpenFile(manifestPath, utfutil.UTF8)`;
  golang.org/x/text `encoding/unicode`, "Append RuneError to the destination"; read from source, not measured).
- `watch_sync` compares main's folder with the plan through `as_plan`, as the merge check does (F7).
- The Gitea stand-in reads the folder at main's commit before it creates the branch, so a read that fails (such a name, or
  the host) leaves no branch at main's commit, which a retry would refuse as not cmapi's. `push_branch` supersedes on a
  `NotUtf8` from the push itself (F3).

Still the worker's retry, then failure, as for any error, with `NotUtf8: the name of <path> is not UTF-8` in the note: the
reads of a PR head that a person pushed to (`pr_checks`' tree and a delete's head, `apply`'s tree; the request ends
`failed`, or `sync_failed` once an apply started, as a failed check would), the retry of a `sync_failed` delete
(`prune`), and `open_revert`. Each is bounded by the five attempts, and none leaves a lock held without a state that offers
`:retry` or `:revert`.

## Review

Codex reached its usage limit during the review (`gpt-6.2-astra`, back on 2026-11-25). The owner's rule lets a separate Opus agent
take the reviewer's place, so two Opus agents reviewed this change. Neither one wrote it.

- **Reviewer 1:** Opus 5.5, high (`review/reviewer-1-opus.md`). Seven findings: F1 and F2 are Medium, F3 to F7 are Low.
- **Reviewer 2:** Opus 5.5, high (`review/reviewer-2-opus.md`, mutants in `review/reviewer-2-mutants.txt`).
  - It upheld F1, F2, F5, F6 and F7.
  - It replaced F3's fix with "read before you create the branch". This also fixes an older defect: a host error after the
    create left a branch that the retry refused.
  - It completed F4: every shown path doubles each backslash and writes each bad byte as `\xNN`. A round trip of 5,000 names
    proves that each shown path names exactly one file.
  - It retracted, in so many words:
    - reviewer 1's "the reorder breaks the tests";
    - the comment that `git_reconcile` sweeps the branch;
    - the claim that reviewer 1's escape was one-to-one;
    - "pr_failed" as an end state.
  - Its tests: on head, 19 of the review tests fail. After the fix, 438 passed in 16 files, and 13 of 13 mutants were killed.
    The contract renders byte for byte, and oasdiff reports no breaking change.
- **The coordinator's rulings (Opus 5.5):** each finding is accepted as reviewer 2 ruled it. The coordinator applied the
  patch with `patch -p1 -F0` and merged in `main`. The full service suite is recorded below.

- **The full service suite** in database `cmapi_wt605`, from 2026-11-24T16:34:50Z to 17:10:24Z, on the patched branch merged
  with `main` `a2a55f3`: **2684 passed in 2130.30 s**, no failure.
- After `main` gained #645 (`5962830`), the coordinator merged it in and relocated 8 citations. On the merged tree, the #626, #644, #646,
  problem-registry, API-standard, API-docs, samples and #616 tests gave **305 passed**. `doc-citations.py --check`: 0 problems.
