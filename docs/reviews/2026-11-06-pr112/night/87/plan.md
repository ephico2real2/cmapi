READ FROM CODE — Review plan: inspect commit.txt and change.diff first; exported head is the baseline, with no live GitHub or cluster operations.

- C1: check run conclusions and empty statuses.
- C2: cross-source collisions, both timestamp orders, and reruns.
- C3: check run pagination and hidden failures.
- C4: endpoint errors fail closed.
- C5: GitHub versus Gitea/other-provider posting semantics.
- C6: missing required context is pending.
- C7: three mutations against the named test module.

PROPOSAL NOT OPERATED — For each defect, provide a complete patch and executable regression test with before/after results. Record exact commands and logs, update verdicts and resume after each ID. No production edits, commits, pushes, secrets, real GitHub calls or cluster operations.
