"""The cross-check: what the two reviews' disagreements needed proving."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import threading

import pytest
import yaml
from sqlalchemy import text

from cmapi.core.db.repo import RequestRepo
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs
from test_review_a_concurrency import LEAD, pending
from test_review_d_delivery import run_until, status
from test_review_e_recovery import lease_expired
from cmapi.worker import Worker

ROOT = pathlib.Path(__file__).resolve().parents[3]
CHART, CRC = ROOT/"deploy/helm/cmapi", ROOT/"deploy/environments/crc.yaml"
DIG = "sha256:" + "a"*64


def helm(*args):
    return subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", *args], capture_output=True, text=True)


def rendered(*args):
    r = helm("-f", str(CRC), "--set", f"cmapi.digest={DIG}", "--set", "trustedCA.certificates=x", *args)
    assert r.returncode == 0, r.stderr
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def test_cancel_during_a_reject_has_one_winner(world, monkeypatch):
    """A lock taken only by approve and reject: cancel reads pending, waits on the row, then overwrites rejected.
    (A cancel after an approve is legal, approved to cancelled; a cancel after a reject is not.)"""
    from cmapi.core.db.repo import AuditRepo
    client, ctx, git, kube, validator, keys = world
    rid = pending(client, keys, seats=1, ctx=ctx)
    real = AuditRepo.record
    box = {}

    def record(self, actor, action, target, detail=None):
        out = real(self, actor, action, target, detail)
        if action == "request.reject" and "t" not in box:
            box["t"] = threading.Thread(target=lambda: box.__setitem__("c", client.post(f"/api/v1/requests/{rid}:cancel", headers=auth(keys, "ola", **OLA))))
            box["t"].start()
            box["t"].join(1.0)
        return out
    monkeypatch.setattr(AuditRepo, "record", record)
    r = client.post(f"/api/v1/requests/{rid}:reject", json={"comment": "no"}, headers=auth(keys, "bob", **LEAD()))
    box["t"].join()
    monkeypatch.undo()
    v = status(client, keys, rid)
    assert (r.status_code, box["c"].status_code, v["status"]) == (200, 409, "rejected"), (r.status_code, box["c"].status_code, v["status"], [e["event"] for e in v["events"]])


def test_cancel_while_the_pr_opens_is_not_overwritten_and_the_pr_closes(world):
    """The worker's write: a cancel commits during the Git call; pr_open must not overwrite it, and the PR must not merge."""
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    real = git.open_pr
    box = {}

    def open_pr(*a, **k):
        pr = real(*a, **k)
        box["r"] = client.post(f"/api/v1/requests/{rid}:cancel", headers=auth(keys, "ola", **OLA))
        return pr
    git.open_pr = open_pr
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert box["r"].status_code == 200 and v["status"] == "cancelled", (box["r"].status_code, v["status"])
    assert git.prs[1]["state"] == "closed" and "clusters/CRC/namespaces/payments-dev/namespace.yaml" not in git.branches["main"]


def _delete_pending_prune(client, ctx, keys):
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    run_jobs(ctx)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    rid = client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY))
    run_jobs(ctx)
    assert client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev"}, headers=auth(keys, "opal", **OPAL)).status_code == 200
    return rid


def test_terminating_is_not_terminal_and_makes_no_event_per_poll(world):
    client, ctx, git, kube, validator, keys = world
    rid = _delete_pending_prune(client, ctx, keys)
    key = ("Namespace", "", "payments-dev")
    deletes = []

    def stuck(kind, ns, name):
        deletes.append(name)
        kube.objects[key]["status"] = {"phase": "Terminating"}
    real = kube.delete
    kube.delete = stuck
    w = Worker(ctx, "w")
    for _ in range(8):
        lease_expired(ctx)
        w.run_one()
    v = status(client, keys, rid)
    assert v["status"] == "awaiting_prune", v["status"]
    assert len(deletes) == 1 and sum(e["event"] == "pruned" for e in v["events"]) == 1, (len(deletes), len(v["events"]))
    kube.delete = real
    del kube.objects[key]
    lease_expired(ctx)
    w.run_one()
    assert status(client, keys, rid)["status"] == "synced"


def test_retry_after_a_smuggled_branch_does_not_merge_it(world):
    """Real Gitea keeps a closed PR's branch (measured), and a new PR adopts its head, so head == pr.head_sha alone passes."""
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "pr_checks") == "pr_checks"
    branch = git.prs[1]["branch"]
    where = "clusters/CRC/namespaces/victim/rolebindings.yaml"
    git.tamper(branch, where, "kind: RoleBinding\n")
    real_open = git.open_pr

    def keeps_branch(br, files, title, body, base_sha):         # what a host does when no one deletes the branch
        n = len(git.prs) + 1
        git.prs[n] = {"branch": br, "state": "open", "title": title, "body": body, "url": f"https://git.test/pulls/{n}", "merge_sha": None}
        from cmapi.core.ports import PrRef
        return PrRef(n, git.prs[n]["url"], br, git.heads[br])
    git.open_pr = keeps_branch
    # the PR record now carries the moved head, as after a :retry of a closed PR
    with ctx.db.session() as s:
        s.execute(text("""update change_requests set status='approved', pr=null where request_id=:r"""), {"r": rid})
        s.execute(text("update jobs set done_at=now() where kind='pr_checks'"))
        from cmapi.core.db.repo import JobRepo
        JobRepo(s).enqueue("open_pr", request_id=rid, cluster_id="CRC")
    run_jobs(ctx)
    assert where not in git.branches["main"], f"status {status(client, keys, rid)['status']}: the smuggled file reached main"


def test_the_design_is_the_default_and_apply_must_be_acknowledged():
    plain = helm("--set", f"cmapi.digest={DIG}", "--set", "portal.enabled=false")
    assert plain.returncode == 0, plain.stderr
    assert "cmapi-deliverer" not in plain.stdout, "a default install gives the worker a cluster-wide write identity"
    bare = helm("--set", f"cmapi.digest={DIG}", "--set", "portal.enabled=false", "--set", "delivery.mode=apply")
    assert bare.returncode != 0 and "acknowledgeDirectWrites" in bare.stderr


def test_crc_keeps_apply_only_by_saying_so():
    docs = rendered()
    assert [d for d in docs if d["kind"] == "ClusterRole" and d["metadata"]["name"] == "cmapi-deliverer"]


def test_policy_refuses_what_the_first_version_let_through():
    vap = next(d for d in rendered() if d["kind"] == "ValidatingAdmissionPolicy")
    exprs = " ".join(v["expression"] for v in vap["spec"]["validations"])
    for needle in ("openshift-.*", "kube-.*", "ocp-.*", "cmapi-reader", "newLabels", "newAnnotations"):
        assert needle in exprs, needle


def test_tag_alone_does_not_render():
    r = helm("-f", str(CRC), "--set", "cmapi.tag=mutable", "--set", "trustedCA.certificates=x")
    assert r.returncode != 0 and "cmapi.digest is required" in r.stderr
    r = helm("-f", str(CRC), "--set", "cmapi.digest=sha256:short", "--set", "trustedCA.certificates=x")
    assert r.returncode != 0 and "not a sha256 digest" in r.stderr
    images = [c["image"] for d in rendered() if d["kind"] in ("Deployment", "Job") for c in d["spec"]["template"]["spec"]["containers"]]
    assert images and all("@sha256:" in i for i in images), images


def test_worker_alert_sees_a_worker_that_is_gone():
    rule = next(d for d in rendered() if d["kind"] == "PrometheusRule")
    expr = next(r for g in rule["spec"]["groups"] for r in g["rules"] if r["alert"] == "CmapiWorkerNotLooping")["expr"]
    assert "absent(cmapi_worker_last_loop_timestamp_seconds" in expr


def test_cli_client_is_not_a_password_client():
    realm = next(d for d in rendered() if d["kind"] == "KeycloakRealmImport")["spec"]["realm"]
    assert next(c for c in realm["clients"] if c["clientId"] == "cmapi-cli")["directAccessGrantsEnabled"] is False


def test_http_log_carries_no_name(world, capfd):
    client, ctx, git, kube, validator, keys = world
    capfd.readouterr()
    client.get("/api/v1/me", headers=auth(keys, "unique-person", sub="opaque-77", **OLA))
    out = capfd.readouterr().out
    http = [l for l in out.splitlines() if '"event": "http"' in l]
    assert http and "unique-person" not in http[-1] and "opaque-77" in http[-1], http[-1:]


STUB = r'''#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$STUBLOG"
case "$(basename "$0")" in
  podman)
    if [ "$1" = build ]; then for a in "$@"; do [ "$a" = cmapi-portal-ui/Containerfile ] && { echo "no such file: $a" >&2; exit 125; }; done; fi
    if [ "$1" = run ]; then git rev-parse --short=10 HEAD; fi ;;
  oc)
    case "$*" in
      "whoami") echo admin ;; "whoami -t") echo tok ;;
      get\ istag*jsonpath*) echo sha256:$(printf 'b%.0s' {1..64}) ;;
      get\ istag*) exit 1 ;;
      get\ secret*) printf '%s' "-----BEGIN CERTIFICATE-----" | base64 ;;
      get\ cm*) echo "-----BEGIN CERTIFICATE-----" ;;
      exec*) git rev-parse --short=10 HEAD ;;
    esac ;;
esac
exit 0
'''


def test_no_portal_release_runs_end_to_end_with_stubbed_tools(tmp_path):
    repo = tmp_path/"repo"
    (repo/"cmapi").mkdir(parents=True)
    shutil.copytree(ROOT/"deploy", repo/"deploy")
    shutil.copy(ROOT/"cmapi/pyproject.toml", repo/"cmapi/pyproject.toml")
    bindir = tmp_path/"bin"; bindir.mkdir()
    for tool in ("podman", "oc", "helm"):
        f = bindir/tool; f.write_text(STUB); f.chmod(f.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bindir}:{pathlib.Path(sys.executable).parent}:{os.environ['PATH']}", "STUBLOG": str(tmp_path/"log"),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for cmd in (["git", "init", "-q"], ["git", "add", "."], ["git", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, env=env, check=True)
    r = subprocess.run(["bash", "deploy/release-crc.sh", "--no-portal"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    log = (tmp_path/"log").read_text()
    assert "cmapi-portal" not in log, [l for l in log.splitlines() if "portal" in l]
    lock = yaml.safe_load((repo/"deploy/images.lock.yaml").read_text())
    assert set(lock) == {"cmapi"} and lock["cmapi"]["digest"].startswith("sha256:")
    assert "helm upgrade --install" in log and "images.lock.yaml" in log and "trustedCA.certificates=" in log
    # the same chart renders from that lock with the portal off
    out = subprocess.run(["helm", "template", "cmapi", str(repo/"deploy/helm/cmapi"), "-n", "cmapi", "-f", str(repo/"deploy/environments/crc.yaml"), "-f", str(repo/"deploy/images.lock.yaml"), "--set", "trustedCA.certificates=x"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
