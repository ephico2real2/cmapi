# PR #112 (#110, #109): review, unfinished

Saved when the owner cleared the session on 2026-11-06, so it survives the scratchpad.

- `reviewer-1-codex.md`: Codex at `be66382`, 109,091 tokens. Two findings: #115, #116.
- `reviewer-2-opus.md`: reviewer 2's answer. Finding 1 amended, finding 2's fix accepted with a real test, and new defects #119, #120, #121, #122, #123, #124, #125, #126.
- `reviewer-2-proposed/`: its eleven patches against `be66382`, with `APPLY.md`. All apply in order with `patch -p1 --fuzz=0` on the export.
- `reviewer-2-tools/`: its proof runner and patch builder, with paths from the old scratchpad.

**Reviewer 2 stopped before finishing, and says not to apply the set as ready. The coordinator has validated none of it.**

## To finish, per `.claude/skills/fix-defect/SKILL.md`, step 4

Not run on this patch set:

1. The service suite, so the tests in patches 01 and 02 have not run and may fail.
2. Patch 02's before and after.
3. `ldap-identities-test.sh` with its mutants: stopped after the first, and patch 07 moves code they edit.
4. `mutate-secrets.py`.
5. `ldap-identities-test.sh failures` on the final tree, under `/bin/dash`, and again on `be66382` to replace the "before" log.
6. `shellcheck` on the final tree.

**#118 is not settled.** CI's `manifests` job failed in `doc13-test.py` at `44083ff`. Reviewer 2 reports `doc13` rc 0 on its set on this Mac, but the implementer's local run passed too, so only CI on the final head can settle it.

Not tested: Docker, a real cluster, the real directory. The real server answering 32 for `ou=TrustedApplications`, which patch 11 now requires, is inferred. **Owner's decision, when it matters:** where channel mail goes; `cmapi-approver-platform@...` is not a real list, and SMTP is off on CRC and kind.
