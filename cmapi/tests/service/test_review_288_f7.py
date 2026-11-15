"""PR #288 review, F7: #286 adds (pr_open, CANCEL) to the table (base 77d069e refused :cancel from pr_open). The apply holds the
request row for its marker, but the merge job does not: a :cancel that lands while merge is at the host commits cancelled, the
host merges, and the merge job's MERGED is then refused. The PR is merged, main holds the change (Argo CD syncs it; for a delete
in apply mode, main drops the folder while the namespace stays), and the request reads cancelled with its lock released. Fable's
design, section 2: the job "holds the request row with SELECT ... FOR NO KEY UPDATE from the fence to the commit, so :cancel
(which takes the same lock) and the job cannot interleave"."""
from __future__ import annotations

import threading

from test_flow import OLA, auth
from test_git_layer import argocd, drive, layer  # noqa: F401  (the fixture)


def test_a_cancel_racing_the_merge_waits_for_it_and_is_refused(layer):
    w = layer
    argocd(w)
    rid = w.create()
    answers, threads = [], []

    def cancel_while_the_host_merges(number):
        t = threading.Thread(target=lambda: answers.append(w.client.post(f"/api/v1/requests/{rid}:cancel",
                                                                         headers=auth(w.keys, "ola", **OLA))))
        t.start()
        t.join(2.0)                                       # fixed: blocked on the row the merge job holds; unfixed: done
        threads.append(t)

    w.host.merge_hook = cancel_while_the_host_merges
    drive(w.ctx, limit=6)
    for t in threads:
        t.join(15)
    v = w.view(rid)
    assert w.host.prs[1]["merged"], "the host merged the PR"
    assert answers and answers[0].status_code == 409, (answers[0].status_code, answers[0].text) if answers else "no cancel"
    assert v["status"] in ("merged", "synced"), [(e["event"], e["status"], e["note"]) for e in v["events"]]
