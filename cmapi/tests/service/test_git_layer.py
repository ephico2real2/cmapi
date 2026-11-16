"""#286: the Git layer and GitHub's PR adapter on it, against real repositories. The test plan is Fable's design, section 7
(7.1 to 7.6), as the arbitration of #286 chose it.

Git is never faked here: a real bare repository over file://, https:// (git http-backend behind TLS and Basic auth) and ssh://
(a throwaway sshd with a pinned host key). The platform is gitserver.StubGitHub, GitHub's PR paths over that same repository,
whose merge is a real merge commit, refused on a conflict, and which fails a named call on request. Every test fails on main
(77d069e): there is no Git layer, no request branch cmapi/<cluster>/<requestId>, no applied or merge_failed, and no merge check."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from conftest import DB_URL, FakeKube, FakeValidator, OneSecret
from cmapi.core.auth import Authenticator, Jwks
from cmapi.core.clients.kube import KubeError
from cmapi.core.context import build_context
from cmapi.core.db.models import OPEN_STATES, JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo, utcnow
from cmapi.core.errors import Problem
from cmapi.core.git import GitHubProvider, make_provider
from cmapi.core.git.base import BranchRequest, GitUnavailable
from cmapi.core.git.transport import GitConfigError, nss_wrapper, parse_remote
from cmapi.core.git.workspace import BranchMoved, BranchRefused, GitWorkspace, request_branch
from cmapi.core.lifecycle import Event as E, State as S, holds_lock, transition, _LOCK, _T
from cmapi.core.observability import GIT_OPS, MERGE_CONFLICTS, PLATFORM_REQUESTS
from cmapi.main import create_app
from cmapi.settings import Settings
from fastapi.testclient import TestClient
from gitserver import SSHD, GitHttps, StubGitHub, bare_repo, git, main_files, main_log, make_ca_and_server_cert, person_commit, sshd
from test_flow import AMY, NS, OLA, OPAL, auth

ISSUER = "https://keycloak.test/realms/cmapi"
AUDIENCE = "cmapi-nonprod"
API = "https://github.test"
FOLDER = "clusters/CRC/namespaces/payments-dev"
TOKEN = "github_pat_TestOnlyNeverReal_9f2c41d7e8b3"


def ops(op: str, result: str) -> float:
    return GIT_OPS.labels(op, result)._value.get()


def secret_dir(root: Path, name: str = "cmapi-git-bot", **keys: str) -> Path:
    d = root / name
    d.mkdir(exist_ok=True)
    names = {"ssh_privatekey": "ssh-privatekey", "ssh_publickey": "ssh-publickey"}
    for k, v in keys.items():
        (d / names.get(k, k)).write_text(v)
    return d


# --------------------------------------------------------------------------- the world: API, worker, real Git, stub platform

def drive(ctx, limit: int = 40) -> list[str]:
    """Run each due job through the worker's own run_one, as the worker does, until nothing is due. A job that waits or retries
    is made due again at once; the worker's failure handling (backoff, five attempts) applies."""
    from cmapi.worker import Worker

    w = Worker(ctx, "test-worker")
    ran = []
    for _ in range(limit):
        with ctx.db.session() as s:
            job = s.query(JobRow).filter(JobRow.done_at.is_(None), JobRow.kind != "git_reconcile").order_by(JobRow.job_id).first()
            kind = job.kind if job else None
        if kind is None or not w.run_one():
            break
        ran.append(kind)
        with ctx.db.session() as s:
            for j in s.query(JobRow).filter(JobRow.done_at.is_(None)):
                j.run_after, j.locked_until = utcnow(), None
    return ran


@pytest.fixture
def layer(test_config, fresh_db, keys, monkeypatch, tmp_path):
    bare = bare_repo(tmp_path)
    config = tmp_path / "config"
    config.mkdir()
    for f in test_config.iterdir():
        (config / f.name).write_text(f.read_text())
    inst = (config / "instance.yaml").read_text()
    (config / "instance.yaml").write_text(inst.replace("repository: cmapi/cluster-configs-test",
                                                       f"repository: cmapi/cluster-configs-test\n    url: file://{bare}"))
    monkeypatch.setenv("CMAPI_DATABASE_URL", DB_URL)
    validator, kube = FakeValidator(), FakeKube()
    s = Settings(config_dir=config, database_url=DB_URL, git_provider="github", git_url=API, git_token=TOKEN, cursor_key="k",
                 link_key="l", metrics_port=0, imports_dir=None, component="worker", git_workdir=tmp_path / "workdir",
                 git_credentials_dir=tmp_path / "no-secret", kube_token_file=Path("/nonexistent"), kube_ca_file=Path("/nonexistent"))
    import cmapi.core.context as context_mod
    monkeypatch.setattr(context_mod, "CliValidator", lambda *a, **k: validator)
    ctx = build_context(s, start_registry=False, import_source=OneSecret())
    assert isinstance(ctx.git, GitHubProvider) and ctx.git.workspace is not None and not ctx.git.post_statuses
    host = StubGitHub(bare)
    ctx.git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(host), headers=ctx.git._client.headers)
    ctx.registry.client_factory = lambda *a, **k: kube
    ctx.registry.start_caches = True
    ctx.registry.refresh()
    ctx.registry.cache("CRC").wait_ready(5)
    ctx.deliverer_factory = lambda cid: kube
    ctx.auth = Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, "https://keycloak.test/certs", fetch=lambda url: [keys.jwk]))
    with TestClient(create_app(s, ctx)) as client:
        w = SimpleNamespace(client=client, ctx=ctx, bare=bare, host=host, kube=kube, validator=validator, keys=keys, tmp=tmp_path)
        w.view = lambda rid: client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
        w.events = lambda rid: [e["event"] for e in w.view(rid)["events"]]
        w.create = lambda ns=NS: client.post("/api/v1/clusters/CRC/namespaces", json=ns, headers=auth(keys, "ola", **OLA)).json()["requestId"]
        w.retry = lambda rid: client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **OPAL))
        yield w
    ctx.shutdown()


def argocd(w):
    w.ctx.delivery = replace(w.ctx.delivery, mode="argocd")


def merge_parents(bare: Path) -> list[str]:
    return git("--git-dir", str(bare), "rev-list", "--parents", "-n1", "main", cwd=bare, home=bare.parent).split()[1:]


def once(monkeypatch, cls, name, *, before=False, error=RuntimeError):
    """The named method raises once: after doing its work (a crash right after the effect), or before."""
    real, fired = getattr(cls, name), []

    def wrapper(self, *a, **k):
        if fired:
            return real(self, *a, **k)
        fired.append(1)
        if before:
            raise error(f"crash before {name}")
        out = real(self, *a, **k)
        raise error(f"crash after {name}")

    monkeypatch.setattr(cls, name, wrapper)
    return fired


# --------------------------------------------------------------------------- 7.1 the state machine

NEW = [(S.PR_OPEN, E.APPLIED, S.APPLIED), (S.PR_OPEN, E.SYNC_TIMEOUT, S.SYNC_FAILED), (S.PR_OPEN, E.CANCEL, S.CANCELLED),
       (S.APPLIED, E.MERGED, S.MERGED), (S.APPLIED, E.MERGE_FAILED, S.MERGE_FAILED), (S.MERGE_FAILED, E.MERGED, S.MERGED),
       (S.MERGE_FAILED, E.RETRY, S.MERGE_FAILED), (S.SYNC_FAILED, E.APPLIED, S.APPLIED)]


@pytest.mark.parametrize("before, event, after", NEW)
def test_7_1_a_each_new_transition_gives_its_state(before, event, after):
    assert transition(before, event).after is after


@pytest.mark.parametrize("state", [S.APPLIED, S.MERGE_FAILED])
@pytest.mark.parametrize("event", [E.CANCEL, E.PR_FAILED, E.BASE_CHANGED, E.PR_OPENED, E.SYNCED, E.REVERT])
def test_7_1_a_the_cluster_ahead_of_main_cannot_be_cancelled_failed_or_superseded(state, event):
    with pytest.raises(Problem) as exc:
        transition(state, event, actor_is_operator=True)
    assert exc.value.status == 409


def test_7_1_b_applied_and_merge_failed_hold_the_lock_and_the_index_says_so():
    assert holds_lock(S.APPLIED) and holds_lock(S.MERGE_FAILED)
    assert set(OPEN_STATES) == {s.value for s in _LOCK}
    assert all(s in {k[0] for k in _T} | {None} or s in _LOCK for s in (S.APPLIED, S.MERGE_FAILED))


@pytest.mark.parametrize("state", ["applied", "merge_failed"])
def test_7_1_c_a_second_request_is_409_while_the_first_is_applied_or_merge_failed(layer, state):
    rid = layer.create()
    with layer.ctx.db.session() as s:
        s.execute(text("update change_requests set status = :st where request_id = :r"), {"st": state, "r": rid})
    r = layer.client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(layer.keys, "ola", **OLA))
    assert r.status_code == 409 and r.json()["code"] == "change-pending"


# --------------------------------------------------------------------------- 7.2 the jobs

def test_7_2_a_b_apply_mode_applies_from_the_branch_before_the_merge(layer, monkeypatch):
    w = layer
    seen = []
    real = w.kube.apply
    monkeypatch.setattr(w.kube, "apply", lambda doc: (seen.append((len(w.host.merges), main_files(w.bare, FOLDER))), real(doc))[1])
    rid = w.create()
    assert drive(w.ctx) == ["push_branch", "open_pr", "pr_checks", "apply", "merge", "git_cleanup"]
    v = w.view(rid)
    assert v["status"] == "synced", [(e["event"], e["note"]) for e in v["events"]]
    assert seen and all(merges == 0 and on_main == {} for merges, on_main in seen), "every write came before the merge"
    assert w.events(rid)[:6] == ["plan_auto_approved", "branch_pushed", "pr_opened", "ci", "apply_started", "applied"]
    applied_head = next(e for e in v["events"] if e["event"] == "applied")
    assert merge_parents(w.bare)[1] == w.host.prs[1]["sha"], "the merge commit's second parent is the applied head"
    assert f"{FOLDER}/namespace.yaml" in main_files(w.bare, FOLDER)
    assert w.host.head(f"cmapi/CRC/{rid}") is None, "git_cleanup deleted the branch with a lease"
    assert not (w.ctx.git.workspace.root / "CRC" / rid).exists(), "the worktree is gone"
    assert not w.host.statuses, "host CI off: no commit status posted"
    assert applied_head


def test_7_2_a_change_and_delete_in_apply_mode_and_the_delete_merges_first(layer):
    w = layer
    h = auth(w.keys, "ola", **OLA)
    w.create()
    drive(w.ctx)
    etag = w.client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    change = w.client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"tier": "medium"},
                            headers={**auth(w.keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    drive(w.ctx)
    assert w.view(change)["status"] == "synced"
    assert "requests.cpu: '16'" in main_files(w.bare, FOLDER)[f"{FOLDER}/resourcequota-payments-dev-quota.yaml"]
    etag = w.client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    delete = w.client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**auth(w.keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    w.client.post(f"/api/v1/requests/{delete}:approve", json={}, headers=auth(w.keys, "amy", **AMY))
    ran = drive(w.ctx)
    assert "apply" not in ran and "merge" in ran, "a delete merges first (the arbitration, row 4)"
    assert w.view(delete)["status"] == "awaiting_prune" and main_files(w.bare, FOLDER) == {}
    w.client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev"}, headers=auth(w.keys, "opal", **OPAL))
    drive(w.ctx)
    assert w.view(delete)["status"] == "synced"
    assert len(w.host.merges) == 3 and w.host.opened == 3


def test_7_2_a_argocd_mode_merges_first_then_waits_for_the_sync(layer):
    argocd(layer)
    rid = layer.create()
    ran = drive(layer.ctx, limit=5)
    assert ran[:4] == ["push_branch", "open_pr", "pr_checks", "merge"] and "apply" not in ran
    assert layer.view(rid)["status"] == "merged" and not layer.kube.applied
    assert main_log(layer.bare)[0] == f"Merge cmapi/CRC/{rid}"


def test_7_2_c_f1_a_merge_that_keeps_failing_after_the_apply_holds_the_lock_and_retry_reaches_synced(layer):
    w = layer
    rid = w.create()
    w.host.fail["merge"] = "always"
    drive(w.ctx)
    v = w.view(rid)
    assert v["status"] == "merge_failed", [(e["event"], e["note"]) for e in v["events"]]
    assert w.host.prs[1]["state"] == "open" and w.host.head(f"cmapi/CRC/{rid}"), "the PR and the branch are kept"
    assert w.kube.get_object("Namespace", None, "payments-dev") is not None, "the cluster holds the plan"
    assert main_files(w.bare, FOLDER) == {}, "main does not"
    again = w.client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(w.keys, "ola", **OLA))
    assert again.status_code == 409 and again.json()["code"] == "change-pending"
    cancel = w.client.post(f"/api/v1/requests/{rid}:cancel", headers=auth(w.keys, "ola", **OLA))
    assert cancel.status_code == 409, "never cancelled from merge_failed"
    del w.host.fail["merge"]
    assert w.retry(rid).status_code == 200
    drive(w.ctx)
    assert w.view(rid)["status"] == "synced" and f"{FOLDER}/namespace.yaml" in main_files(w.bare, FOLDER)


def test_7_2_d_an_unmanaged_namespace_fails_before_any_write_and_main_is_untouched(layer):
    w = layer
    w.kube.objects[("Namespace", "", "payments-dev")] = {"metadata": {"name": "payments-dev", "labels": {}}}
    rid = w.create()
    drive(w.ctx)
    v = w.view(rid)
    assert v["status"] == "failed" and "apply_started" not in w.events(rid)
    assert w.host.prs[1]["state"] == "closed" and w.host.head(f"cmapi/CRC/{rid}") is None and main_log(w.bare) == ["seed"]


def test_7_2_e_an_apply_that_fails_after_it_started_is_sync_failed_and_retry_reaches_synced(layer, monkeypatch):
    w = layer
    real, calls = w.kube.apply, []

    def third_fails(doc):
        calls.append(doc)
        if len(calls) == 3:
            raise KubeError(422, "/apis", "admission refused the third object")
        return real(doc)

    monkeypatch.setattr(w.kube, "apply", third_fails)
    rid = w.create()
    drive(w.ctx)
    assert w.view(rid)["status"] == "sync_failed" and "apply_started" in w.events(rid)
    assert w.host.prs[1]["state"] == "open" and w.host.head(f"cmapi/CRC/{rid}"), "the PR and the branch are kept"
    assert w.client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(w.keys, "ola", **OLA)).status_code == 409
    assert w.client.post(f"/api/v1/requests/{rid}:revert", headers=auth(w.keys, "opal", **OPAL)).status_code == 409, \
        "nothing in Git to revert before a merge: the owner decides (row 15)"
    monkeypatch.setattr(w.kube, "apply", real)
    assert w.retry(rid).status_code == 200
    assert "apply" in drive(w.ctx)
    assert w.view(rid)["status"] == "synced"


@pytest.mark.parametrize("cls, name", [("ws", "push_branch"), ("gh", "open_pr"), ("gh", "merge")])
def test_7_2_f_a_crash_right_after_each_effect_ends_with_one_commit_one_pr_one_merge(layer, monkeypatch, cls, name):
    w = layer
    target = GitWorkspace if cls == "ws" else GitHubProvider
    fired = once(monkeypatch, target, name)
    rid = w.create()
    drive(w.ctx, limit=60)
    assert fired, f"{name} ran"
    assert w.view(rid)["status"] == "synced", [(e["event"], e["note"]) for e in w.view(rid)["events"]]
    assert w.host.opened == 1 and len(w.host.merges) == 1, "exactly one PR and one merge"
    assert git("--git-dir", str(w.bare), "rev-list", "--count", "main^2", "^main^1", cwd=w.bare, home=w.tmp) == "1", "one commit on the branch"


def test_7_2_f_a_crash_after_apply_started_applies_again_and_never_fails(layer, monkeypatch):
    w = layer
    import importlib; apply_mod = importlib.import_module("cmapi.jobs.apply")
    real = apply_mod.confirmed_by_read
    crashed = []

    def crash_once(*a, **k):
        if not crashed:
            crashed.append(1)
            raise RuntimeError("the worker died after the apply")
        return real(*a, **k)

    monkeypatch.setattr(apply_mod, "confirmed_by_read", crash_once)
    rid = w.create()
    drive(w.ctx, limit=60)
    assert crashed and w.view(rid)["status"] == "synced"
    assert w.events(rid).count("apply_started") == 1, "the marker was committed once, in its own transaction"


def test_7_2_f_the_host_merged_and_the_answer_was_lost_the_merge_is_adopted(layer):
    w = layer
    w.host.fail["merge"] = "after"
    rid = w.create()
    drive(w.ctx, limit=60)
    assert w.view(rid)["status"] == "synced" and len(w.host.merges) == 1
    assert "adopted" in next(e["note"] for e in w.view(rid)["events"] if e["event"] == "merge_verified")


def test_7_2_g_a_branch_pushed_by_an_attempt_is_adopted_from_a_new_workdir_with_no_push(layer, tmp_path):
    w = layer
    rid = w.create()
    assert drive(w.ctx, limit=1) == ["push_branch"]
    branch = f"cmapi/CRC/{rid}"
    sha = w.host.head(branch)
    reflog_before = git("--git-dir", str(w.bare), "rev-list", "--all", "--count", cwd=w.bare, home=w.tmp)
    with w.ctx.db.session() as s:
        row = RequestRepo(s).get(rid)
        from cmapi.jobs.delivery import branch_request
        req = branch_request(w.ctx, row)
    fresh = GitWorkspace(f"file://{w.bare}", workdir=tmp_path / "another-pod", credentials_dir=tmp_path / "none")
    pushed = fresh.push_branch(req)
    assert (pushed.result, pushed.head) == ("adopted", sha) and w.host.head(branch) == sha
    assert git("--git-dir", str(w.bare), "rev-list", "--all", "--count", cwd=w.bare, home=w.tmp) == reflog_before, "no push"
    fresh.dispose()


def test_7_2_g_this_requests_stale_branch_is_replaced_with_a_lease_and_a_foreign_one_is_refused(layer, tmp_path):
    w = layer
    rid = w.create()
    drive(w.ctx, limit=1)
    branch = f"cmapi/CRC/{rid}"
    with w.ctx.db.session() as s:
        from cmapi.jobs.delivery import branch_request
        req = branch_request(w.ctx, RequestRepo(s).get(rid))
    ws = w.ctx.git.workspace
    assert ws.push_branch(req).result == "adopted", "main moving on does not make the branch stale: the merge check decides"
    # This request's own earlier attempt, for another plan: its trailers name the request, so it is replaced with a lease.
    stale = person_commit(w.bare, {"README.md": "an earlier attempt\n"},
                          f"an earlier attempt\n\nCmapi-Request-Id: {rid}\nCmapi-Plan-Hash: an-older-plan", tmp_path)
    git("--git-dir", str(w.bare), "update-ref", f"refs/heads/{branch}", stale, cwd=w.bare, home=tmp_path)
    git("--git-dir", str(w.bare), "update-ref", "refs/heads/main", f"{stale}~1", cwd=w.bare, home=tmp_path)
    replaced = ws.push_branch(req)
    assert replaced.result == "replaced" and replaced.head != stale and w.host.head(branch) == replaced.head
    # A person's commit on the branch: refused, and left exactly as it is.
    foreign = person_commit(w.bare, {"README.md": "a person\n"}, "a person's work", tmp_path)
    git("--git-dir", str(w.bare), "update-ref", f"refs/heads/{branch}", foreign, cwd=w.bare, home=tmp_path)
    with pytest.raises(BranchRefused):
        ws.push_branch(req)
    assert w.host.head(branch) == foreign


def test_7_2_g_a_ref_that_moves_between_the_read_and_the_push_is_a_rejected_lease(layer, tmp_path, monkeypatch):
    w = layer
    rid = w.create()
    ws = w.ctx.git.workspace
    with w.ctx.db.session() as s:
        from cmapi.jobs.delivery import branch_request
        req = branch_request(w.ctx, RequestRepo(s).get(rid))
    real = GitWorkspace._push

    def someone_first(self, path, branch, head, lease, result):
        other = person_commit(w.bare, {"README.md": "raced\n"}, "raced", tmp_path)
        git("--git-dir", str(w.bare), "update-ref", f"refs/heads/{branch}", other, cwd=w.bare, home=tmp_path)
        return real(self, path, branch, head, lease, result)

    monkeypatch.setattr(GitWorkspace, "_push", someone_first)
    with pytest.raises(BranchMoved, match="lease"):
        ws.push_branch(req)


def test_7_2_h_the_commit_is_reproducible_and_its_trailers_parse(layer, tmp_path):
    w = layer
    rid = w.create()
    with w.ctx.db.session() as s:
        from cmapi.jobs.delivery import branch_request
        req = branch_request(w.ctx, RequestRepo(s).get(rid))
    shas = []
    for name in ("pod-a", "pod-b"):
        ws = GitWorkspace(f"file://{w.bare}", workdir=tmp_path / name, credentials_dir=tmp_path / "none")
        main = ws.fetch_main()
        shas.append(ws._build(req, FOLDER, main))
        trailers = ws.trailers(shas[-1])
        ws.dispose()
    assert shas[0] == shas[1]
    assert trailers == {"Cmapi-Request-Id": [rid], "Cmapi-Plan-Hash": [req.plan_hash]}


def test_7_2_i_a_conflicting_main_before_the_apply_is_superseded_with_its_paths_and_nothing_applied(layer, capsys):
    w = layer
    rid = w.create()
    assert drive(w.ctx, limit=2) == ["push_branch", "open_pr"]
    person_commit(w.bare, {f"{FOLDER}/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata: {name: payments-dev}\n"}, "by hand", w.tmp)
    before = MERGE_CONFLICTS.labels("pr_checks")._value.get()
    capsys.readouterr()
    drive(w.ctx)
    v = w.view(rid)
    assert v["status"] == "superseded" and not w.kube.applied
    note = next(e["note"] for e in v["events"] if e["event"] == "merge_check")
    assert f"{FOLDER}/namespace.yaml" in note
    assert MERGE_CONFLICTS.labels("pr_checks")._value.get() == before + 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{") and '"git_op"' in line]
    check = next(e for e in lines if e["op"] == "merge_check" and e["outcome"] == "refused")
    assert check["conflict_paths"] == [f"{FOLDER}/namespace.yaml"] and check["request_id"] == rid
    assert check["reason"] == note, "the timeline's reason is the log's (7.6-b)"
    assert len(check["main_sha"]) == 40 and len(check["head_sha"]) == 40


def test_7_2_i_a_conflict_after_the_apply_is_merge_failed_never_superseded(layer, monkeypatch):
    w = layer
    rid = w.create()
    import importlib; merge_mod = importlib.import_module("cmapi.jobs.merge")
    real = merge_mod._merge

    def conflict_first(ctx, repo, jobs, row, job):
        person_commit(w.bare, {f"{FOLDER}/namespace.yaml": "kind: Namespace\nmetadata: {name: payments-dev}\n"}, "by hand", w.tmp)
        return real(ctx, repo, jobs, row, job)

    monkeypatch.setattr(merge_mod, "_merge", conflict_first)
    drive(w.ctx)
    v = w.view(rid)
    assert v["status"] == "merge_failed" and "superseded" not in [e["status"] for e in v["events"]]
    assert w.host.prs[1]["state"] == "open" and any("did not happen" in c for _, c in w.host.comments)


def test_7_2_j_merge_tree_that_cannot_run_is_retried_and_nothing_is_applied_or_merged(layer, monkeypatch):
    w = layer
    rid = w.create()
    drive(w.ctx, limit=2)
    ws = w.ctx.git.workspace
    real = GitWorkspace._m

    def broken(self, *args, **kw):
        if args and args[0] == "merge-tree":
            return subprocess.CompletedProcess(args, 2, b"", b"fatal: simulated")
        return real(self, *args, **kw)

    monkeypatch.setattr(GitWorkspace, "_m", broken)
    with pytest.raises(GitUnavailable, match="merge-tree exited 2"):
        ws.merge_check(w.host.head(f"cmapi/CRC/{rid}"), FOLDER, {}, {})
    drive(w.ctx, limit=3)
    assert w.view(rid)["status"] == "pr_open" and not w.kube.applied and not w.host.merges


def test_7_2_j_exit_one_with_no_tree_is_an_error_not_a_conflict(tmp_path):
    """Measured on git 2.52.0 and 2.55.0: "not something we can merge" exits 1 (the arbitration, row 10)."""
    bare = bare_repo(tmp_path)
    ws = GitWorkspace(f"file://{bare}", credentials_dir=tmp_path / "none")
    main = ws.fetch_main()
    real = ws._m

    def no_tree(*args, **kw):
        if args and args[0] == "merge-tree":
            return subprocess.CompletedProcess(args, 1, b"", b"merge-tree: x - not something we can merge")
        return real(*args, **kw)

    ws._m = no_tree
    with pytest.raises(GitUnavailable, match="with no tree"):
        ws.merge_check(main, FOLDER, {}, {})
    ws.dispose()


def test_7_2_k_a_head_moved_before_the_apply_fails_and_after_it_is_merge_failed(layer, monkeypatch):
    w = layer
    rid = w.create()
    drive(w.ctx, limit=3)              # push_branch, open_pr, pr_checks: apply is next
    branch = f"cmapi/CRC/{rid}"
    moved = person_commit(w.bare, {"README.md": "x\n"}, "x", w.tmp)
    git("--git-dir", str(w.bare), "update-ref", f"refs/heads/{branch}", moved, cwd=w.bare, home=w.tmp)
    drive(w.ctx)
    assert w.view(rid)["status"] == "failed" and not w.kube.applied
    # After the apply: the merge is pinned to the applied head, so a moved head is merge_failed and nothing new merges.
    w2 = w.create({**NS, "namespace": "orders-dev"})
    import importlib; merge_mod = importlib.import_module("cmapi.jobs.merge")
    real = merge_mod._merge

    def move_first(ctx, repo, jobs, row, job):
        other = person_commit(w.bare, {"README.md": "y\n"}, "y", w.tmp)
        git("--git-dir", str(w.bare), "update-ref", f"refs/heads/{row.pr['branch']}", other, cwd=w.bare, home=w.tmp)
        return real(ctx, repo, jobs, row, job)

    monkeypatch.setattr(merge_mod, "_merge", move_first)
    drive(w.ctx)
    assert w.view(w2)["status"] == "merge_failed" and not w.host.merges


def test_7_2_l_a_person_merges_the_pr_while_pr_open_and_watch_sync_applies_from_main(layer):
    w = layer
    rid = w.create()
    drive(w.ctx, limit=2)
    import httpx as _h
    w.host(_h.Request("PUT", f"{API}/repos/cmapi/cluster-configs-test/pulls/1/merge",
                      content=json.dumps({"sha": w.host.head(f"cmapi/CRC/{rid}")}).encode()))
    drive(w.ctx)
    events = w.events(rid)
    assert w.view(rid)["status"] == "synced" and "apply_started" not in events, "adopted: no apply before this merge"
    assert events.index("merged") < events.index("applied"), "watch_sync applied from main after the person's merge"
    assert "Namespace//payments-dev" in w.kube.applied


def test_7_2_m_a_person_closes_the_pr_after_the_apply_and_a_new_pr_opens_from_the_same_branch(layer, monkeypatch):
    w = layer
    rid = w.create()
    import importlib; merge_mod = importlib.import_module("cmapi.jobs.merge")
    real = merge_mod._merge

    def closed_first(ctx, repo, jobs, row, job):
        if w.host.prs[1]["state"] == "open":
            w.host.prs[1]["state"] = "closed"
            git("--git-dir", str(w.bare), "update-ref", "-d", f"refs/heads/{row.pr['branch']}", cwd=w.bare, home=w.tmp)
        return real(ctx, repo, jobs, row, job)

    monkeypatch.setattr(merge_mod, "_merge", closed_first)
    drive(w.ctx)
    v = w.view(rid)
    assert v["status"] == "synced" and "pr_reopened" in w.events(rid)
    assert w.host.prs[2]["merged"] and w.host.prs[2]["sha"] == w.host.prs[1]["sha"], "the same commit, re-created bit for bit"


def test_7_2_n_cancel_in_approved_and_pr_open_closes_and_deletes_and_after_an_apply_is_409(layer):
    w = layer
    a = w.create()
    drive(w.ctx, limit=1)
    assert w.client.post(f"/api/v1/requests/{a}:cancel", headers=auth(w.keys, "ola", **OLA)).status_code == 200
    drive(w.ctx)
    assert w.view(a)["status"] == "cancelled" and w.host.head(f"cmapi/CRC/{a}") is None
    b = w.create({**NS, "namespace": "orders-dev"})
    drive(w.ctx, limit=3)
    assert w.client.post(f"/api/v1/requests/{b}:cancel", headers=auth(w.keys, "ola", **OLA)).status_code == 200
    drive(w.ctx)
    pr_b = next(p for p in w.host.prs.values() if p["ref"] == f"cmapi/CRC/{b}")
    assert pr_b["state"] == "closed" and w.host.head(f"cmapi/CRC/{b}") is None
    c = w.create({**NS, "namespace": "search-dev"})
    with w.ctx.db.session() as s:
        RequestRepo(s).event(RequestRepo(s).get(c), "apply_started", "test", "", {"head": "x"})
        s.execute(text("update change_requests set status='pr_open', pr='{\"number\": 9, \"url\": \"u\", \"branch\": \"b\", \"head\": \"x\"}' where request_id=:r"), {"r": c})
    r = w.client.post(f"/api/v1/requests/{c}:cancel", headers=auth(w.keys, "ola", **OLA))
    assert r.status_code == 409 and "apply has started" in r.json()["detail"]


def test_7_2_n_cancel_racing_the_apply_waits_for_its_marker_and_is_refused(layer, monkeypatch):
    w = layer
    rid = w.create()
    drive(w.ctx, limit=3)
    import importlib; apply_mod = importlib.import_module("cmapi.jobs.apply")
    real, answers = apply_mod.mark_apply_started, []

    def mark_while_cancelling(ctx, request_id, head):
        with ctx.db.session() as s:
            RequestRepo(s).get_for_update(request_id)          # the apply holds the row ...
            t = threading.Thread(target=lambda: answers.append(w.client.post(f"/api/v1/requests/{rid}:cancel",
                                                                             headers=auth(w.keys, "ola", **OLA))))
            t.start()
            t.join(1.0)
            assert t.is_alive(), "... so the cancel waits"
            RequestRepo(s).event(RequestRepo(s).get(request_id), "apply_started", "cmapi-deliverer", "", {"head": head})
        t.join(10)
        return True

    monkeypatch.setattr(apply_mod, "mark_apply_started", mark_while_cancelling)
    drive(w.ctx)
    assert answers and answers[0].status_code == 409
    assert w.view(rid)["status"] == "synced"


def test_7_2_o_retry_picks_the_job_of_each_state(layer):
    w = layer
    cases = {"failed": "push_branch", "merge_failed": "merge"}
    for state, kind in cases.items():
        rid = w.create({**NS, "namespace": f"r-{state.replace('_', '-')}"})
        with w.ctx.db.session() as s:
            s.execute(text("update jobs set done_at = now() where request_id = :r"), {"r": rid})
            s.execute(text("update change_requests set status = :st, pr = '{\"number\": 1, \"url\": \"u\", \"branch\": \"b\", \"head\": \"h\"}' "
                           "where request_id = :r"), {"st": state, "r": rid})
        assert w.retry(rid).status_code == 200, state
        with w.ctx.db.session() as s:
            assert JobRepo(s).pending(kind, rid) is not None, (state, kind)


# --------------------------------------------------------------------------- 7.3 the platform adapter (GitHub)

def test_7_3_a_c_e_the_github_adapter_against_the_stub(tmp_path):
    bare = bare_repo(tmp_path)
    host = StubGitHub(bare, "o/r")
    gh = GitHubProvider(API, "o/r", TOKEN)
    gh._client = httpx.Client(base_url=API, transport=httpx.MockTransport(host), headers=gh._client.headers)
    assert gh.find_pr("cmapi/CRC/req-1") is None
    person_commit(bare, {"README.md": "x\n"}, "x", tmp_path)
    head = git("--git-dir", str(bare), "rev-parse", "main", cwd=bare, home=tmp_path)
    git("--git-dir", str(bare), "update-ref", "refs/heads/cmapi/CRC/req-1", head, cwd=bare, home=tmp_path)
    git("--git-dir", str(bare), "update-ref", "refs/heads/main", f"{head}~1", cwd=bare, home=tmp_path)
    pr = gh.open_pr("cmapi/CRC/req-1", head, "t", "b")
    assert gh.open_pr("cmapi/CRC/req-1", head, "t", "b") == pr and host.opened == 1, "open twice returns the same PR"
    from cmapi.core.git.base import HeadMoved, PlatformRefused
    with pytest.raises(HeadMoved):
        gh.merge(pr, "f" * 40)
    assert not host.merges, "a wrong sha merges nothing"
    host.fail["pr_state"] = "x"
    assert gh.merge(pr, head) and gh.pr_status(pr).state == "merged"
    gh.close(pr, "twice")
    gh.close(pr, "twice")
    assert [p.number for p in gh.list_open("cmapi/")] == []
    host.fail["pr_open"] = "always"
    with pytest.raises(GitUnavailable):
        gh.open_pr("cmapi/CRC/req-2", head, "t", "b")
    assert not any(TOKEN in p for _, p in host.requests), "the token is never in a path"


def test_7_3_c_a_refusal_logs_status_and_message_and_never_the_token(capsys):
    def refuse(request):
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(403, json={"message": f"Resource not accessible by personal access token {TOKEN}"})

    gh = GitHubProvider(API, "o/r", TOKEN)
    gh._client = httpx.Client(base_url=API, transport=httpx.MockTransport(refuse), headers=gh._client.headers)
    before = PLATFORM_REQUESTS.labels("github", "pr_find", "4xx")._value.get()
    capsys.readouterr()
    from cmapi.core.git.base import PlatformRefused
    with pytest.raises(PlatformRefused):
        gh.find_pr("cmapi/CRC/req-1")
    out = capsys.readouterr().out
    event = json.loads(next(line for line in out.splitlines() if '"git_op"' in line))
    assert event["op"] == "pr_find" and event["outcome"] == "refused" and event["http_status"] == 403
    assert "***" in event["message"] and TOKEN not in out
    assert PLATFORM_REQUESTS.labels("github", "pr_find", "4xx")._value.get() == before + 1


def test_7_3_host_ci_off_reads_no_status_and_on_reads_statuses_never_check_runs():
    seen = []

    def handle(request):
        seen.append(request.url.path)
        if request.url.path.endswith("/pulls/7"):
            return httpx.Response(200, json={"state": "open", "merged": False, "head": {"sha": "c" * 40, "ref": "cmapi/CRC/r1"}})
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"statuses": [{"context": "ci/kyverno", "state": "success"}]})
        raise AssertionError(request.url.path)

    from cmapi.core.ports import PrRef
    pr = PrRef(7, "u", "cmapi/CRC/r1", "c" * 40)
    off = GitHubProvider(API, "o/r", "t")
    off._client = httpx.Client(base_url=API, transport=httpx.MockTransport(handle))
    assert off.pr_status(pr).checks == {} and not off.external_ci and not off.post_statuses
    on = GitHubProvider(API, "o/r", "t", host_checks=True)
    on._client = httpx.Client(base_url=API, transport=httpx.MockTransport(handle))
    assert dict(on.pr_status(pr).checks) == {"ci/kyverno": "success"} and on.post_statuses
    assert not any("check-runs" in p or "check-suites" in p for p in seen)


# --------------------------------------------------------------------------- 7.4 concurrency

def _requests(ws: GitWorkspace, n: int) -> list[BranchRequest]:
    when = datetime(2026, 11, 15, tzinfo=timezone.utc)
    return [BranchRequest("CRC", f"req-20261115-{i:04d}", f"clusters/CRC/namespaces/ns-{i}", f"h{i}",
                          f"create ns-{i}\n\nCmapi-Request-Id: req-20261115-{i:04d}\nCmapi-Plan-Hash: h{i}\n",
                          {f"clusters/CRC/namespaces/ns-{i}/namespace.yaml": f"kind: Namespace\nmetadata: {{name: ns-{i}}}\n"}, {}, when)
            for i in range(n)]


def test_7_4_a_b_twenty_requests_in_eight_threads_on_one_workdir_and_the_sweeper_between(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    bare = bare_repo(tmp_path)
    ws = GitWorkspace(f"file://{bare}", workdir=tmp_path / "wd", credentials_dir=tmp_path / "none")
    reqs = _requests(ws, 20)
    errors, sweeps, stop = [], [], threading.Event()

    def sweeper():
        while not stop.is_set():
            sweeps.append(ws.sweep({(r.cluster_id, r.request_id) for r in reqs}).result)

    t = threading.Thread(target=sweeper)
    t.start()
    with ThreadPoolExecutor(8) as pool:
        for fut in [pool.submit(ws.push_branch, r) for r in reqs]:
            try:
                fut.result()
            except Exception as exc:                 # noqa: BLE001 - every failure is the finding
                errors.append(repr(exc))
    stop.set()
    t.join()
    assert not errors, errors
    heads = git("--git-dir", str(bare), "for-each-ref", "--format=%(refname)", "refs/heads/cmapi/", cwd=bare, home=tmp_path).splitlines()
    assert len(heads) == 20
    assert subprocess.run(["git", "--git-dir", str(ws.mirror), "fsck", "--no-progress"], capture_output=True,
                          env={"PATH": os.environ["PATH"], "GIT_CONFIG_GLOBAL": os.devnull}).returncode == 0
    assert not list(ws.mirror.rglob("*.lock")), "no lock file left"
    assert set(sweeps) <= {"ok", "skipped"} and "skipped" in sweeps, "the sweeper only skipped or ran between operations"
    assert sorted(f"{c}/{r}" for c, r in ws.worktrees()) == sorted(f"CRC/{r.request_id}" for r in reqs)
    ws.dispose()


def test_7_4_c_d_a_stale_worker_on_another_pod_cannot_push_over_the_branch(tmp_path):
    bare = bare_repo(tmp_path)
    a = GitWorkspace(f"file://{bare}", workdir=tmp_path / "pod-a", credentials_dir=tmp_path / "none")
    b = GitWorkspace(f"file://{bare}", workdir=tmp_path / "pod-b", credentials_dir=tmp_path / "none")
    req = _requests(a, 1)[0]
    first = a.push_branch(req)
    assert b.push_branch(req) == replace(first, result="adopted"), "the second pod adopts: one commit, nothing pushed"
    # A stale writer that read "no branch" and pushes late: its empty lease is rejected, the branch is unchanged.
    with pytest.raises(BranchMoved):
        b._push(b.root, request_branch("CRC", req.request_id), first.base, "", "created")
    assert git("--git-dir", str(bare), "rev-parse", f"refs/heads/cmapi/CRC/{req.request_id}", cwd=bare, home=tmp_path) == first.head
    a.dispose()
    b.dispose()


def test_7_4_e_a_fetch_never_moves_a_checked_out_branch(tmp_path):
    bare = bare_repo(tmp_path)
    ws = GitWorkspace(f"file://{bare}", credentials_dir=tmp_path / "none")
    req = _requests(ws, 1)[0]
    head = ws.push_branch(req).head
    person_commit(bare, {"README.md": "moved\n"}, "moved", tmp_path)
    ws.fetch_main()
    wt = ws.worktree_path("CRC", req.request_id)
    assert git("rev-parse", "HEAD", cwd=wt, home=tmp_path) == head
    ws.dispose()


# --------------------------------------------------------------------------- 7.5 cleanup

def test_7_5_a_b_a_final_state_removes_the_worktree_and_the_sweeper_the_rest_and_skips_when_busy(tmp_path):
    bare = bare_repo(tmp_path)
    ws = GitWorkspace(f"file://{bare}", credentials_dir=tmp_path / "none")
    reqs = _requests(ws, 3)
    for r in reqs:
        ws.push_branch(r)
    ws.remove("CRC", reqs[0].request_id)
    assert not ws.worktree_path("CRC", reqs[0].request_id).exists()
    ws._lock.acquire()
    try:
        t = threading.Thread(target=lambda: setattr(ws, "_last", ws.sweep(set())))
        t.start()
        t.join()
        assert ws._last.result == "skipped" and len(ws.worktrees()) == 2, "busy: nothing removed"
    finally:
        ws._lock.release()
    before = ops("cleanup", "ok")
    result = ws.sweep({("CRC", reqs[1].request_id)})
    assert result.removed == [f"CRC/{reqs[2].request_id}"] and result.kept == [f"CRC/{reqs[1].request_id}"]
    assert ops("cleanup", "ok") == before + 1
    ws.dispose()


def test_7_5_c_start_up_repairs_stale_locks_and_a_wrong_refspec_is_fetched_again(tmp_path):
    bare = bare_repo(tmp_path)
    wd = tmp_path / "wd"
    ws = GitWorkspace(f"file://{bare}", workdir=wd, credentials_dir=tmp_path / "none")
    ws.push_branch(_requests(ws, 1)[0])
    ws.dispose()
    (wd / "repo.git" / "index.lock").write_text("")
    (wd / "repo.git" / "refs" / "remotes" / "origin" / "main.lock").write_text("")
    again = GitWorkspace(f"file://{bare}", workdir=wd, credentials_dir=tmp_path / "none")
    assert not list((wd / "repo.git").rglob("*.lock")) and again.read_folder(FOLDER)[0] == {}
    again._m("config", "--replace-all", "remote.origin.fetch", "+refs/*:refs/*")
    again.dispose()
    third = GitWorkspace(f"file://{bare}", workdir=wd, credentials_dir=tmp_path / "none")
    third.fetch_main()
    assert third._m("config", "--get-all", "remote.origin.fetch").stdout.decode().split() == ["+refs/heads/main:refs/remotes/origin/main"]
    third.dispose()


def test_7_5_d_above_eighty_percent_of_the_size_limit_the_workdir_is_fetched_again(tmp_path):
    bare = bare_repo(tmp_path)
    ws = GitWorkspace(f"file://{bare}", credentials_dir=tmp_path / "none", size_limit=10_000)
    ws.push_branch(_requests(ws, 1)[0])
    assert ws.sweep(set()).result == "recloned" and not ws.mirror.exists()
    assert ws.read_folder(FOLDER)[1], "the next operation fetches again"
    ws.dispose()


def test_7_5_e_the_reconciler_closes_and_deletes_orphans_and_leaves_hands_off_states(layer):
    w = layer
    keep = w.create()
    drive(w.ctx, limit=3)
    with w.ctx.db.session() as s:
        s.execute(text("update change_requests set status='merge_failed' where request_id=:r"), {"r": keep})
    orphan = person_commit(w.bare, {"README.md": "o\n"}, "o\n\nCmapi-Request-Id: req-20000101-0001\nCmapi-Plan-Hash: x", w.tmp)
    git("--git-dir", str(w.bare), "update-ref", "refs/heads/cmapi/CRC/req-20000101-0001", orphan, cwd=w.bare, home=w.tmp)
    git("--git-dir", str(w.bare), "update-ref", "refs/heads/main", f"{orphan}~1", cwd=w.bare, home=w.tmp)
    import importlib; rec = importlib.import_module("cmapi.jobs.git_reconcile")
    rec.GRACE_SECONDS = -1
    from cmapi.jobs.git_reconcile import git_reconcile
    with w.ctx.db.session() as s:
        job = JobRepo(s).enqueue("git_reconcile")
        git_reconcile(w.ctx, s, job)
    assert w.host.head("cmapi/CRC/req-20000101-0001") is None, "an orphan with no row: deleted"
    assert w.host.head(f"cmapi/CRC/{keep}") and w.host.prs[1]["state"] == "open", "merge_failed: hands off"
    rec.GRACE_SECONDS = 900


def test_7_5_e_a_young_branch_is_left_alone(layer):
    w = layer
    orphan = person_commit(w.bare, {"README.md": "o\n"}, "o\n\nCmapi-Request-Id: req-20000101-0002\nCmapi-Plan-Hash: x", w.tmp)
    git("--git-dir", str(w.bare), "update-ref", "refs/heads/cmapi/CRC/req-20000101-0002", orphan, cwd=w.bare, home=w.tmp)
    from cmapi.jobs.git_reconcile import git_reconcile
    with w.ctx.db.session() as s:
        git_reconcile(w.ctx, s, JobRepo(s).enqueue("git_reconcile"))
    assert w.host.head("cmapi/CRC/req-20000101-0002") == orphan


# --------------------------------------------------------------------------- 7.6 logging, and the secrets

def test_7_6_a_d_one_git_op_per_operation_with_the_fields_and_counters_moving_by_one(layer, capsys):
    w = layer
    capsys.readouterr()
    before = ops("push", "ok")
    rid = w.create()
    drive(w.ctx)
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{") and '"git_op"' in line]
    mine = [e for e in lines if e.get("request_id") == rid]
    order = [e["op"] for e in mine]
    for op in ("fetch", "worktree", "commit", "push", "pr_open", "pr_state", "merge_check", "apply", "merge", "branch_delete"):
        assert op in order, op
    assert order.index("push") < order.index("pr_open") < order.index("apply") < order.index("merge") < order.index("branch_delete")
    always = ("request_id", "cluster", "namespace", "branch", "op", "attempt", "outcome", "duration_ms", "job_id", "job_kind",
              "worker", "lease_generation", "platform")
    for e in mine:
        assert all(k in e for k in always), (e["op"], [k for k in always if k not in e])
    assert ops("push", "ok") == before + 1, "one push, counted once"


@pytest.fixture
def https_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("CMAPI_GIT_TOKEN", TOKEN)
    monkeypatch.setenv("GIT_TRACE", "1")
    monkeypatch.setenv("GIT_SSL_NO_VERIFY", "1")
    bare_repo(tmp_path)
    with GitHttps(tmp_path, "cmapi-git-bot", TOKEN) as server:
        yield server, secret_dir(tmp_path, token=TOKEN + "\n", username="cmapi-git-bot")


def test_7_6_c_the_token_is_in_no_argv_environment_file_or_log(https_layer, tmp_path, monkeypatch, capsys):
    import cmapi.core.git.workspace as wsmod

    server, secret = https_layer
    wd = tmp_path / "wd"
    calls = []
    real = subprocess.run

    def record(args, *a, **kw):
        if str(kw.get("cwd") or "").startswith(str(wd)):
            calls.append((list(args), dict(kw.get("env") or {})))
        return real(args, *a, **kw)

    monkeypatch.setattr(wsmod.subprocess, "run", record)
    capsys.readouterr()
    ws = GitWorkspace(server.url(), workdir=wd, credentials_dir=secret, ca_bundle=server.ca)
    req = _requests(ws, 1)[0]
    head = ws.push_branch(req).head
    assert ws.merge_check(head, req.folder, {}, req.files).ok and ws.delete_branch(request_branch("CRC", req.request_id), head)
    on_disk = b"".join(p.read_bytes() for p in wd.rglob("*") if p.is_file())
    ws.dispose()
    assert server.authorized > 0 and server.refused > 0, "Git asked without, was refused, then sent the token from the helper"
    assert {argv[1] for argv, _ in calls} >= {"push", "ls-remote"} or any("push" in argv for argv, _ in calls)
    for argv, env in calls:
        assert TOKEN not in " ".join(argv)
        assert all(TOKEN not in v for v in env.values())
        assert not {k for k in env if k.startswith("CMAPI_")} and "GIT_TRACE" not in env and "GIT_SSL_NO_VERIFY" not in env
    assert TOKEN.encode() not in on_disk, "not in repo.git/config, a worktree's config, the index or any file"
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err and '"op": "push"' in out.out


def test_7_6_c_https_refuses_a_server_the_bundle_does_not_trust(https_layer, tmp_path):
    server, secret = https_layer
    other = tmp_path / "other"
    other.mkdir()
    wrong_ca, _, _ = make_ca_and_server_cert(other, "elsewhere")
    ws = GitWorkspace(server.url(), credentials_dir=secret, ca_bundle=wrong_ca)
    with pytest.raises(GitUnavailable, match="(?i)certificate|SSL"):
        ws.read_folder(FOLDER)
    assert server.authorized == 0, "nothing was sent to a server that was not verified"
    ws.dispose()


# --------------------------------------------------------------------------- SSH: the bot's key, a pinned host key

needs_sshd = pytest.mark.skipif(SSHD is None and not os.environ.get("CMAPI_TEST_REQUIRE_SSHD"),
                                reason="no sshd on this machine; CI sets CMAPI_TEST_REQUIRE_SSHD so a missing one fails there")


def _ssh_mounts(tmp_path: Path, server: dict, known: str | None = None) -> tuple[Path, Path]:
    key = secret_dir(tmp_path, "cmapi-git-bot-ssh", ssh_privatekey=Path(server["key"]).read_text(),
                     ssh_publickey=Path(str(server["key"]) + ".pub").read_text())
    os.chmod(key / "ssh-privatekey", 0o600)
    hosts = secret_dir(tmp_path, f"known-{len(known or '')}", known_hosts=known or server["known_hosts"])
    return key, hosts


@needs_sshd
def test_ssh_with_the_bots_key_and_a_pinned_host_key_pushes_the_request_branch(tmp_path):
    bare = bare_repo(tmp_path)
    with sshd(tmp_path) as server:
        key, hosts = _ssh_mounts(tmp_path, server)
        ws = GitWorkspace(f"{server['url']}{bare}", credentials_dir=tmp_path / "none", ssh_dir=key, known_hosts_dir=hosts)
        assert ws._creds.fingerprint.startswith("SHA256:")
        req = _requests(ws, 1)[0]
        head = ws.push_branch(req).head
        assert ws.branch_head(request_branch("CRC", req.request_id)) == head
        ws.dispose()
    assert main_log(bare) == ["seed"]
    assert (hosts / "known_hosts").read_text() == server["known_hosts"], "nothing is ever added to known_hosts"


@needs_sshd
def test_ssh_to_a_host_whose_key_is_not_pinned_is_refused(tmp_path):
    bare = bare_repo(tmp_path)
    with sshd(tmp_path) as server:
        other = tmp_path / "other-host"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other)], check=True)
        other_key = " ".join(Path(str(other) + ".pub").read_text().split()[:2])
        for known in (f"[127.0.0.1]:{server['port']} {other_key}\n", f"[git.example]:22 {other_key}\n"):
            key, hosts = _ssh_mounts(tmp_path, server, known)
            ws = GitWorkspace(f"{server['url']}{bare}", credentials_dir=tmp_path / "none", ssh_dir=key, known_hosts_dir=hosts)
            with pytest.raises(GitUnavailable, match="(?i)host key"):
                ws.read_folder(FOLDER)
            assert (hosts / "known_hosts").read_text() == known
            ws.dispose()


@pytest.mark.parametrize("case", ["passphrase", "rsa", "garbage", "mismatch"])
def test_an_ssh_key_that_batch_mode_cannot_use_or_that_mismatches_stops_the_start(tmp_path, case):
    d = tmp_path / "k"
    d.mkdir()
    kind, pw = ("rsa", "") if case == "rsa" else ("ed25519", "secret-pass" if case == "passphrase" else "")
    subprocess.run(["ssh-keygen", "-q", "-t", kind, "-N", pw, "-f", str(d / "ssh-privatekey")], check=True)
    if case == "garbage":
        (d / "ssh-privatekey").write_text("not a key\n")
    if case == "mismatch":
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "other")], check=True)
        (d / "ssh-publickey").write_text(Path(str(tmp_path / "other") + ".pub").read_text())
    else:
        (d / "ssh-privatekey.pub").unlink(missing_ok=True)
    hosts = secret_dir(tmp_path, "kh", known_hosts="[git.example]:22 ssh-ed25519 AAAA\n")
    with pytest.raises(GitConfigError, match={"passphrase": "passphrase", "rsa": "not ed25519", "garbage": "does not parse",
                                              "mismatch": "not the public key"}[case]):
        GitWorkspace("git@git.example:o/r.git", credentials_dir=tmp_path / "none", ssh_dir=d, known_hosts_dir=hosts)


# --------------------------------------------------------------------------- configuration and the arbitrary UID

@pytest.mark.parametrize("url, why", [
    ("http://git.example/r.git", "no TLS"), ("git://git.example/r.git", "no TLS"),
    (f"https://bot:{TOKEN}@git.example/r.git", "no user or token"), ("https://bot@git.example/r.git", "no user or token"),
    ("ext::sh -c touch% /tmp/pwned", "white space"), ("ftp://git.example/r.git", "is not an"), ("", "is needed"),
])
def test_a_url_that_could_not_be_used_safely_is_refused(url, why):
    with pytest.raises(GitConfigError, match=why):
        parse_remote(url)


def test_a_credential_the_transport_needs_and_does_not_have_stops_the_start(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(GitConfigError, match="needs the key token"):
        GitWorkspace("https://git.example/r.git", credentials_dir=empty)
    with pytest.raises(GitConfigError, match="needs the key ssh-privatekey"):
        GitWorkspace("ssh://git@git.example/r.git", credentials_dir=empty, ssh_dir=empty, known_hosts_dir=empty)


def test_one_workdir_has_one_owner(tmp_path):
    bare = bare_repo(tmp_path)
    first = GitWorkspace(f"file://{bare}", workdir=tmp_path / "wd", credentials_dir=tmp_path / "none")
    with pytest.raises(GitConfigError, match="another process"):
        GitWorkspace(f"file://{bare}", workdir=tmp_path / "wd", credentials_dir=tmp_path / "none")
    first.dispose()


def test_an_arbitrary_uid_gets_nss_wrapper_for_ssh_and_etc_passwd_stays_as_it_is(tmp_path):
    lib = tmp_path / "libnss_wrapper.so"
    lib.write_bytes(b"")
    env = nss_wrapper(tmp_path / "home", uid=987654321, gid=0, libs=(str(lib),))
    assert env["LD_PRELOAD"] == str(lib) and Path(env["NSS_WRAPPER_PASSWD"]).read_text().startswith("cmapi:x:987654321:0:")
    assert nss_wrapper(tmp_path / "home", uid=os.getuid()) == {}
    with pytest.raises(GitConfigError, match="libnss_wrapper is not installed"):
        nss_wrapper(tmp_path / "home", uid=987654321, gid=0, libs=(str(tmp_path / "absent.so"),))


def test_the_api_process_reads_through_the_host_api_and_has_no_git_layer(tmp_path):
    gh = make_provider("github", API, "o/r", "t", git_layer=False, git_url="file:///nowhere")
    assert gh.workspace is None
    with pytest.raises(GitUnavailable, match="no Git layer"):
        gh.push_request_branch(None)


def test_contains_says_no_for_a_revision_this_repository_does_not_hold(tmp_path):
    """A multi-source Application reports a chart version or another repository's sha beside the Git revision (#141): neither
    is an outage, and neither is contained. A real ancestor is."""
    bare = bare_repo(tmp_path)
    ws = GitWorkspace(f"file://{bare}", credentials_dir=tmp_path / "none")
    first = ws.fetch_main()
    second = person_commit(bare, {"README.md": "2\n"}, "2", tmp_path)
    assert ws.contains(second, first) and not ws.contains(first, second)
    assert ws.contains("1.2.3", first) is False and ws.contains("f" * 40, first) is False
    ws.dispose()
