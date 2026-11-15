"""#286: the Git layer (core/git/workspace.py) with GitHub's PR adapter on it, against real repositories.

Git is never faked here: a real bare repository over file://, https:// (git http-backend behind TLS and Basic auth) and
ssh:// (a throwaway sshd with a pinned host key). The platform is a stub of GitHub's PR API over the same bare repository
(gitserver.StubGitHub), whose merge is a real merge commit, refused on a conflict. Every test fails on main: the Git layer,
the request branch cmapi/<cluster>/<requestId>, apply before merge and the merge check are not there."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import httpx
import pytest

from conftest import DB_URL, FakeKube, FakeValidator, OneSecret
from cmapi.core.auth import Authenticator, Jwks
from cmapi.core.context import build_context
from cmapi.core.git import GitHubProvider, make_provider
from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.transport import GitConfigError, nss_wrapper, parse_remote
from cmapi.core.git.workspace import BranchRefused, GitWorkspace, request_branch
from cmapi.core.observability import GIT_OPS
from cmapi.main import create_app
from fastapi.testclient import TestClient
from gitserver import (SSHD, GitHttps, StubGitHub, bare_repo, git, main_files, main_log, main_message, make_ca_and_server_cert,
                       person_commit, sshd)
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs

from cmapi.settings import Settings

ISSUER = "https://keycloak.test/realms/cmapi"
AUDIENCE = "cmapi-nonprod"
API = "https://github.test"
FOLDER = "clusters/CRC/namespaces/payments-dev"
TOKEN = "github_pat_TestOnlyNeverReal_9f2c41d7e8b3"


def secret_dir(root: Path, **keys: str) -> Path:
    d = root / "cmapi-git"
    d.mkdir(exist_ok=True)
    for k, v in keys.items():
        (d / ("ssh-privatekey" if k == "ssh_privatekey" else k)).write_text(v)
    return d


def ops(op: str, result: str) -> float:
    return GIT_OPS.labels(op, result)._value.get()


# --------------------------------------------------------------------------- the flow through the API and the worker

@pytest.fixture
def layer(test_config, fresh_db, keys, monkeypatch, tmp_path):
    """The app on provider github, built by build_context with a real Git layer on a file:// repository, and GitHub's PR API
    stubbed over that same repository."""
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
    workdir = tmp_path / "workdir"
    s = Settings(config_dir=config, database_url=DB_URL, git_provider="github", git_url=API, git_token=TOKEN, cursor_key="k",
                 link_key="l", metrics_port=0, imports_dir=None, git_workdir=workdir, git_credentials_dir=tmp_path / "no-secret",
                 kube_token_file=Path("/nonexistent"), kube_ca_file=Path("/nonexistent"))
    import cmapi.core.context as context_mod
    monkeypatch.setattr(context_mod, "CliValidator", lambda *a, **k: validator)
    ctx = build_context(s, start_registry=False, import_source=OneSecret())
    assert isinstance(ctx.git, GitHubProvider) and ctx.git.workspace.root == workdir and not ctx.git.external_ci
    host = StubGitHub(bare)
    ctx.git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(host))
    ctx.registry.client_factory = lambda *a, **k: kube
    ctx.registry.start_caches = True
    ctx.registry.refresh()
    ctx.registry.cache("CRC").wait_ready(5)
    ctx.deliverer_factory = lambda cid: kube
    ctx.auth = Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, "https://keycloak.test/certs", fetch=lambda url: [keys.jwk]))
    with TestClient(create_app(s, ctx)) as client:
        yield client, ctx, bare, host, kube, validator, keys, tmp_path
    ctx.shutdown()


def view(client, keys, rid):
    return client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()


def test_create_applies_from_the_branch_then_merges_the_pr_and_removes_the_worktree(layer, monkeypatch):
    client, ctx, bare, host, kube, validator, keys, _ = layer
    r = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    rid = r.json()["requestId"]
    branch = f"cmapi/CRC/{rid}"
    assert run_jobs(ctx, limit=1) == ["open_pr"]
    worktree = ctx.git.workspace.root / "CRC" / rid
    assert worktree.is_dir() and (worktree / FOLDER / "namespace.yaml").exists(), "a worktree at <workdir>/<cluster>/<requestId>"
    assert not (worktree / "clusters/CRC/namespaces/other").exists(), "only the request's folder is checked out"
    assert host.head(branch) and main_log(bare) == ["seed"], "the branch is pushed, main is not"
    message = git("--git-dir", str(bare), "log", "-1", "--format=%B", branch, cwd=bare, home=bare.parent)
    assert f"Cmapi-Request: {rid}" in message and "Cmapi-Plan-Hash: " in message and "Cmapi-Requester: ola" in message
    seen_main_at_apply = []
    real_apply = kube.apply

    def apply(doc):
        seen_main_at_apply.append(main_files(bare, FOLDER))
        return real_apply(doc)

    monkeypatch.setattr(kube, "apply", apply)
    assert run_jobs(ctx) == ["pr_checks", "deliver_pr"]
    v = view(client, keys, rid)
    assert v["status"] == "synced", [(e["event"], e["note"]) for e in v["events"]]
    assert [e["event"] for e in v["events"]] == ["plan_auto_approved", "pr_opened", "ci", "deliver_queued", "applied", "merged", "synced"]
    assert seen_main_at_apply and all(m == {} for m in seen_main_at_apply), "applied before the merge: main did not hold it yet"
    assert v["pr"]["branch"] == branch and host.prs[1]["merged"]
    assert main_log(bare)[0] == f"Merge {branch}" and f"{FOLDER}/namespace.yaml" in main_files(bare, FOLDER)
    assert host.head(branch) is None, "the merged branch is deleted"
    assert not worktree.exists(), "git worktree remove after the merge"
    assert not any("check-runs" in p for _, p in host.requests)


def test_change_and_delete_each_get_their_own_branch_and_pr(layer):
    client, ctx, bare, host, kube, validator, keys, _ = layer
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    run_jobs(ctx)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    change = client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"tier": "medium"},
                          headers={**auth(keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    run_jobs(ctx)
    assert view(client, keys, change)["status"] == "synced"
    assert "requests.cpu: '16'" in main_files(bare, FOLDER)[f"{FOLDER}/resourcequota-payments-dev-quota.yaml"]
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    delete = client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    assert client.post(f"/api/v1/requests/{delete}:approve", json={}, headers=auth(keys, "amy", **AMY)).json()["status"] == "approved"
    run_jobs(ctx)
    assert view(client, keys, delete)["status"] == "awaiting_prune", "a delete merges first and waits for the prune"
    assert main_files(bare, FOLDER) == {}
    assert client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev"}, headers=auth(keys, "opal", **OPAL)).status_code == 200
    run_jobs(ctx)
    assert view(client, keys, delete)["status"] == "synced"
    merges = [s for s in main_log(bare) if s.startswith("Merge cmapi/CRC/")]
    assert len(merges) == 3 and len(host.prs) == 3, "three requests, three branches, three merged PRs"
    assert not list((ctx.git.workspace.root / "CRC").iterdir()), "no worktree left"


def test_two_requests_on_two_namespaces_have_two_worktrees_and_both_merge(layer):
    client, ctx, bare, host, kube, validator, keys, _ = layer
    a = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    b = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": "orders-dev"}, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_jobs(ctx, limit=2) == ["open_pr", "open_pr"]
    root = ctx.git.workspace.root / "CRC"
    assert sorted(p.name for p in root.iterdir()) == sorted([a, b])
    assert not (root / a / "clusters/CRC/namespaces/orders-dev").exists() and not (root / b / FOLDER).exists(), "no cross-contamination"
    run_jobs(ctx)
    assert view(client, keys, a)["status"] == view(client, keys, b)["status"] == "synced"
    assert main_files(bare, FOLDER) and main_files(bare, "clusters/CRC/namespaces/orders-dev")


def test_a_conflicting_main_is_refused_with_its_paths_logged_and_nothing_applied(layer, capsys):
    client, ctx, bare, host, kube, validator, keys, tmp = layer
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_jobs(ctx, limit=2) == ["open_pr", "pr_checks"]
    person_commit(bare, {f"{FOLDER}/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata: {name: payments-dev, labels: {x: y}}\n"},
                  "a person edits main by hand", tmp)
    before = ops("merge_check", "conflict")
    capsys.readouterr()
    run_jobs(ctx)
    v = view(client, keys, rid)
    assert v["status"] == "failed", [(e["event"], e["note"]) for e in v["events"]]
    refusal = next(e for e in v["events"] if e["event"] == "merge_refused")
    assert f"{FOLDER}/namespace.yaml" in refusal["note"], "the timeline names the conflicted path"
    assert not kube.applied, "the merge check ran before the apply: nothing applied"
    assert main_log(bare)[0] == "a person edits main by hand" and not host.prs[1]["merged"] and host.prs[1]["state"] == "closed"
    assert "was refused" in host.comments[-1][1]
    assert ops("merge_check", "conflict") == before + 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{") and '"git_op"' in line]
    check = next(e for e in lines if e["op"] == "merge_check" and e["outcome"] == "conflict")
    assert check["conflicts"] == [f"{FOLDER}/namespace.yaml"] and check["request_id"] == rid and check["cluster"] == "CRC"
    assert check["namespace"] == "payments-dev" and check["branch"] == f"cmapi/CRC/{rid}"
    assert len(check["main_sha"]) == 40 and len(check["head_sha"]) == 40 and "duration_ms" in check and "attempt" in check
    assert not (ctx.git.workspace.root / "CRC" / rid).exists()


def test_a_branch_that_exists_without_the_requests_trailers_is_refused_and_left_alone(layer):
    client, ctx, bare, host, kube, validator, keys, tmp = layer
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    branch = f"cmapi/CRC/{rid}"
    stranger = person_commit(bare, {"README.md": "someone else's\n"}, "not cmapi's", tmp)
    git("--git-dir", str(bare), "update-ref", f"refs/heads/{branch}", stranger, cwd=bare, home=tmp)
    git("--git-dir", str(bare), "update-ref", "refs/heads/main", f"{stranger}~1", cwd=bare, home=tmp)
    run_jobs(ctx)
    v = view(client, keys, rid)
    assert v["status"] == "failed" and any(e["event"] == "branch_refused" for e in v["events"])
    assert host.head(branch) == stranger, "the branch is not overwritten" and not host.prs


def test_a_retry_after_the_push_reuses_the_branch_that_carries_its_trailers(layer, monkeypatch):
    client, ctx, bare, host, kube, validator, keys, _ = layer
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    real = GitHubProvider.find_pr

    def die_after_the_push(self, branch):
        raise GitUnavailable("the host went away right after the push")

    monkeypatch.setattr(GitHubProvider, "find_pr", die_after_the_push)
    run_jobs(ctx, limit=1)
    pushed = host.head(f"cmapi/CRC/{rid}")
    assert pushed and not host.prs
    monkeypatch.setattr(GitHubProvider, "find_pr", real)
    from test_review_e_recovery import lease_expired
    lease_expired(ctx)
    run_jobs(ctx)
    assert view(client, keys, rid)["status"] == "synced"
    assert host.prs[1]["sha"] == pushed, "the same commit: the branch was reused, not written again"


def test_the_sweeper_removes_what_is_not_in_flight_and_keeps_what_is(layer):
    client, ctx, bare, host, kube, validator, keys, _ = layer
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    run_jobs(ctx, limit=1)
    root = ctx.git.workspace.root
    orphan = root / "CRC" / "req-20000101-0001"
    orphan.mkdir(parents=True)
    (orphan / "left-behind").write_text("x")
    before = ops("cleanup", "ok")
    from cmapi.jobs.git_sweep import git_sweep
    with ctx.db.session() as s:
        from cmapi.core.db.repo import JobRepo
        job = JobRepo(s).enqueue("git_sweep")
        git_sweep(ctx, s, job)
    assert not orphan.exists() and (root / "CRC" / rid).exists(), "the request in flight keeps its worktree"
    assert ops("cleanup", "ok") == before + 1
    with ctx.db.session() as s:
        from sqlalchemy import text
        assert s.execute(text("select count(*) from jobs where kind='git_sweep' and done_at is null")).scalar() == 1
    ctx.git.workspace._lock.acquire()               # a Git operation running: the sweeper does not touch anything
    try:
        assert ctx.git.workspace.sweep(set()).skipped
    finally:
        ctx.git.workspace._lock.release()
    assert (root / "CRC" / rid).exists()
    assert ctx.git.workspace.sweep(set()).removed == [f"CRC/{rid}"]


def test_argocd_mode_merges_first_after_the_merge_check(layer):
    client, ctx, bare, host, kube, validator, keys, _ = layer
    from dataclasses import replace
    ctx.delivery = replace(ctx.delivery, mode="argocd")
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    ran = run_jobs(ctx, limit=2)
    assert ran == ["open_pr", "pr_checks"]
    v = view(client, keys, rid)
    assert v["status"] == "merged" and not kube.applied, "argocd follows main: merge first, then wait for the sync"
    assert main_log(bare)[0] == f"Merge cmapi/CRC/{rid}"


# --------------------------------------------------------------------------- the Git layer alone

def test_merge_tree_exit_codes_on_this_git(tmp_path):
    """git-merge-tree(1), EXIT STATUS: 0 clean, 1 conflicted, anything else an error. merge_check reads them so."""
    bare = bare_repo(tmp_path, {f"{FOLDER}/namespace.yaml": "a\n"})
    ws = GitWorkspace(f"file://{bare}", credentials_dir=tmp_path / "none")
    base = {f"{FOLDER}/namespace.yaml": "a\n"}
    head, reused = ws.prepare("CRC", "req-1", FOLDER, {f"{FOLDER}/namespace.yaml": "b\n"}, "x\n\nCmapi-Request: req-1\nCmapi-Plan-Hash: h\n", "h")
    assert not reused
    clean = ws.merge_check(head, FOLDER, base)
    assert clean.ok and clean.tree
    person_commit(bare, {f"{FOLDER}/namespace.yaml": "c\n"}, "conflict", tmp_path)
    conflicted = ws.merge_check(head, FOLDER, base)
    assert conflicted.conflicts == (f"{FOLDER}/namespace.yaml",) and conflicted.folder_moved and not conflicted.ok
    assert ws.prepare("CRC", "req-1", FOLDER, {}, "", "h") == (head, True), "the branch carries req-1's trailers: reused"
    with pytest.raises(BranchRefused):
        ws.prepare("CRC", "req-1", FOLDER, {}, "", "another-plan")
    ws.dispose()


def test_paths_outside_the_folder_are_refused_before_git_runs(tmp_path):
    bare = bare_repo(tmp_path)
    ws = GitWorkspace(f"file://{bare}", credentials_dir=tmp_path / "none")
    for path in ("../escape.yaml", "/abs.yaml", f"{FOLDER}/.git/config", "clusters/CRC/namespaces/other/x.yaml"):
        with pytest.raises(ValueError):
            ws.prepare("CRC", "req-1", FOLDER, {path: "x\n"}, "m\n", "h")
    with pytest.raises(ValueError, match="cannot name a folder"):
        ws.worktree_path("CRC", "../req")
    assert main_log(bare) == ["seed"]
    ws.dispose()


def test_one_workdir_has_one_owner(tmp_path):
    bare = bare_repo(tmp_path)
    first = GitWorkspace(f"file://{bare}", workdir=tmp_path / "wd", credentials_dir=tmp_path / "none")
    with pytest.raises(GitConfigError, match="another process"):
        GitWorkspace(f"file://{bare}", workdir=tmp_path / "wd", credentials_dir=tmp_path / "none")
    first.dispose()
    GitWorkspace(f"file://{bare}", workdir=tmp_path / "wd", credentials_dir=tmp_path / "none").dispose()


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
        GitWorkspace("ssh://git@git.example/r.git", credentials_dir=empty)
    (empty / "ssh-privatekey").write_text("key")
    with pytest.raises(GitConfigError, match="needs known_hosts"):
        GitWorkspace("git@git.example:r.git", credentials_dir=empty)


def test_an_arbitrary_uid_gets_nss_wrapper_for_ssh_and_etc_passwd_stays_as_it_is(tmp_path):
    """"No user exists for uid 1001" (measured in the image): ssh then runs with nss_wrapper and a passwd file of its own."""
    lib = tmp_path / "libnss_wrapper.so"
    lib.write_bytes(b"")
    env = nss_wrapper(tmp_path / "home", uid=987654321, gid=0, libs=(str(lib),))
    assert env["LD_PRELOAD"] == str(lib)
    assert Path(env["NSS_WRAPPER_PASSWD"]).read_text().startswith("cmapi:x:987654321:0:")
    assert nss_wrapper(tmp_path / "home", uid=os.getuid()) == {}, "a UID with an entry needs nothing"
    with pytest.raises(GitConfigError, match="libnss_wrapper is not installed"):
        nss_wrapper(tmp_path / "home", uid=987654321, gid=0, libs=(str(tmp_path / "absent.so"),))


# --------------------------------------------------------------------------- HTTPS: the token, TLS, and no leak

class Recorder:
    """Every git process the Git layer starts, with its argv and environment. subprocess.run is one function for the whole
    process, so the test servers' own git calls pass too: the layer's are those run in its home or worktrees."""

    def __init__(self, monkeypatch, root: Path):
        import cmapi.core.git.workspace as ws

        self.calls: list[tuple[list[str], dict[str, str]]] = []
        real = subprocess.run

        def run(args, *a, **kw):
            if str(kw.get("cwd") or "").startswith(str(root)):
                self.calls.append((list(args), dict(kw.get("env") or {})))
            return real(args, *a, **kw)

        monkeypatch.setattr(ws.subprocess, "run", run)


def test_https_with_a_token_and_the_token_is_in_no_argv_environment_file_or_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CMAPI_GIT_TOKEN", TOKEN)
    monkeypatch.setenv("GIT_TRACE", "1")
    monkeypatch.setenv("GIT_SSL_NO_VERIFY", "1")
    bare = bare_repo(tmp_path)
    secret = secret_dir(tmp_path, token=TOKEN + "\n", username="bot")
    wd = tmp_path / "wd"
    record = Recorder(monkeypatch, wd)
    with GitHttps(tmp_path, "bot", TOKEN) as server:
        ws = GitWorkspace(server.url(), workdir=wd, credentials_dir=secret, ca_bundle=server.ca)
        files, main = ws.read_folder(FOLDER)
        head, _ = ws.prepare("CRC", "req-1", FOLDER, {f"{FOLDER}/namespace.yaml": "kind: Namespace\n"},
                             "create\n\nCmapi-Request: req-1\nCmapi-Plan-Hash: h\n", "h")
        assert ws.merge_check(head, FOLDER, {}).ok
        assert server.authorized > 0 and server.refused > 0, "Git asked without, was refused, then sent the token from the helper"
        on_disk = b"".join(p.read_bytes() for p in wd.rglob("*") if p.is_file())
        ws.remove("CRC", "req-1")
        ws.dispose()
    assert git("--git-dir", str(bare), "rev-parse", "cmapi/CRC/req-1", cwd=bare, home=tmp_path) == head
    assert main_log(bare) == ["seed"], "nothing pushed to main"
    assert {argv[1] for argv, _ in record.calls} >= {"clone", "fetch", "worktree", "commit", "push", "merge-tree"} or \
        {a for argv, _ in record.calls for a in argv[1:3]} >= {"clone", "push"}
    for argv, env in record.calls:
        assert TOKEN not in " ".join(argv), f"the token is in no argv: {argv[:3]}"
        assert all(TOKEN not in v for v in env.values()), "the token is in no environment"
        assert not {k for k in env if k.startswith("CMAPI_")} and "GIT_TRACE" not in env and "GIT_SSL_NO_VERIFY" not in env
    assert TOKEN.encode() not in on_disk, "the token is in no file of the workdir: mirror config, worktree config, index"
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err and '"op": "push"' in out.out


def test_https_refuses_a_server_the_bundle_does_not_trust(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_SSL_NO_VERIFY", "1")
    bare_repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    wrong_ca, _, _ = make_ca_and_server_cert(other, "elsewhere")
    with GitHttps(tmp_path, "x-access-token", TOKEN) as server:
        ws = GitWorkspace(server.url(), credentials_dir=secret_dir(tmp_path, token=TOKEN), ca_bundle=wrong_ca)
        with pytest.raises(GitUnavailable, match="(?i)certificate|SSL"):
            ws.read_folder(FOLDER)
        assert server.authorized == 0, "nothing was sent to a server that was not verified"
        ws.dispose()


def test_a_host_api_refusal_logs_its_status_and_message_and_never_the_token(tmp_path, capsys):
    def refuse(request):
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(403, json={"message": f"Resource not accessible by personal access token {TOKEN}"})

    gh = GitHubProvider(API, "o/r", TOKEN)
    gh._client = httpx.Client(base_url=API, transport=httpx.MockTransport(refuse), headers=gh._client.headers)
    capsys.readouterr()
    with pytest.raises(GitUnavailable):
        gh.find_pr("cmapi/CRC/req-1")
    out = capsys.readouterr().out
    event = json.loads(next(line for line in out.splitlines() if '"git_op"' in line))
    assert event["op"] == "pr_find" and event["outcome"] == "refused" and event["status"] == 403
    assert "Resource not accessible" in event["message"] and TOKEN not in out and "***" in event["message"]


def test_host_ci_off_reads_no_status_and_on_reads_statuses_never_check_runs():
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
    assert off.pr_status(pr).checks == {} and not off.external_ci
    on = GitHubProvider(API, "o/r", "t", host_checks=True)
    on._client = httpx.Client(base_url=API, transport=httpx.MockTransport(handle))
    assert dict(on.pr_status(pr).checks) == {"ci/kyverno": "success"}
    assert not any("check" in p.split("/")[-1] for p in seen if not p.endswith("/status"))


# --------------------------------------------------------------------------- SSH: a pinned host key

needs_sshd = pytest.mark.skipif(SSHD is None and not os.environ.get("CMAPI_TEST_REQUIRE_SSHD"),
                                reason="no sshd on this machine; CI sets CMAPI_TEST_REQUIRE_SSHD so a missing one fails there")


@needs_sshd
def test_ssh_with_a_pinned_host_key_pushes_the_request_branch(tmp_path):
    bare = bare_repo(tmp_path)
    with sshd(tmp_path) as server:
        secret = secret_dir(tmp_path, ssh_privatekey=Path(server["key"]).read_text(), known_hosts=server["known_hosts"])
        os.chmod(secret / "ssh-privatekey", 0o600)
        ws = GitWorkspace(f"{server['url']}{bare}", credentials_dir=secret)
        head, _ = ws.prepare("CRC", "req-1", FOLDER, {f"{FOLDER}/namespace.yaml": "kind: Namespace\n"},
                             "create\n\nCmapi-Request: req-1\nCmapi-Plan-Hash: h\n", "h")
        assert ws.branch_head("cmapi/CRC/req-1") == head and ws.merge_check(head, FOLDER, {}).ok
        ws.dispose()
    assert main_log(bare) == ["seed"]
    assert (secret / "known_hosts").read_text() == server["known_hosts"], "nothing is ever added to known_hosts"


@needs_sshd
def test_ssh_to_a_host_whose_key_is_not_pinned_is_refused(tmp_path):
    bare = bare_repo(tmp_path)
    with sshd(tmp_path) as server:
        other = tmp_path / "other-host"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other)], check=True)
        other_key = " ".join(Path(str(other) + ".pub").read_text().split()[:2])
        for known in (f"[127.0.0.1]:{server['port']} {other_key}\n", f"[git.example]:22 {other_key}\n"):
            d = tmp_path / f"s{len(known)}"
            d.mkdir()
            (d / "ssh-privatekey").write_text(Path(server["key"]).read_text())
            os.chmod(d / "ssh-privatekey", 0o600)
            (d / "known_hosts").write_text(known)
            ws = GitWorkspace(f"{server['url']}{bare}", credentials_dir=d)
            with pytest.raises(GitUnavailable, match="(?i)host key"):
                ws.read_folder(FOLDER)
            assert (d / "known_hosts").read_text() == known, "the unknown key was not added"
            ws.dispose()
    assert main_log(bare) == ["seed"]


def test_make_provider_builds_github_on_the_git_layer(tmp_path):
    bare = bare_repo(tmp_path)
    gh = make_provider("github", API, "o/r", "t", git_url=f"file://{bare}", credentials_dir=tmp_path / "none")
    assert isinstance(gh.workspace, GitWorkspace) and gh.workspace.remote.url == f"file://{bare}"
    assert gh.read_folder(FOLDER)[0] == {} and gh.log()[0].endswith("seed")
    gh.dispose()
    assert request_branch("CRC", "req-20261115-0002") == "cmapi/CRC/req-20261115-0002"
