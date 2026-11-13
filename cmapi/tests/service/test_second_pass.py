"""Second pass on 53c0340: each test asserts the correct outcome."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import threading
import time

import psycopg
import pytest
from sqlalchemy import text

from cmapi.core.db.repo import JobRepo, LeaseLost
from cmapi.core.identity.claims import Person
from cmapi.core.identity.directory import CachedDirectory, InMemoryDirectory
from cmapi.worker import Worker
from conftest import DB_URL
from test_flow import AMY, NS, OLA, auth, run_jobs
from test_review_d_delivery import run_until, status
from test_review_e_recovery import lease_expired

ROOT = pathlib.Path(__file__).resolve().parents[3]


def argocd(ctx, **k):
    ctx.delivery = type(ctx.delivery)(mode="argocd", poll_seconds=0, **k)


def app(revision, sync="Synced", resources=None, op=None):
    return {"status": {"sync": {"status": sync, "revision": revision}, "health": {"status": "Healthy"}, "resources": resources or [],
                       "operationState": op or {"phase": "Succeeded"}}}


def argo_applied(git, kube):
    """What Argo CD would do with main: apply every object, and report each one in status.resources."""
    import yaml
    res = []
    for p, t in git.branches["main"].items():
        if p.endswith(".yaml"):
            for d in yaml.safe_load_all(t):
                kube.apply(d)
                res.append({"kind": d["kind"], "name": d["metadata"]["name"], "namespace": d["metadata"].get("namespace"), "status": "Synced"})
    return res


# ------------------------------------------------------------------ C8: what ships on CRC
def test_argocd_delete_ends_when_the_namespace_is_gone_without_any_cmapi_call(world):
    """docs: 'in argocd delivery the confirmation happens in Argo CD and the worker observes it'."""
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    argocd(ctx)
    run_until(ctx, "watch_sync")
    res = argo_applied(git, kube)
    kube.get = lambda path, params=None: app(git.heads["main"], resources=res)
    run_jobs(ctx)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    rid = client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY))
    run_jobs(ctx)
    assert status(client, keys, rid)["status"] == "awaiting_prune"
    kube.delete("Namespace", None, "payments-dev")           # the operator confirmed in Argo CD; Argo CD pruned it
    w = Worker(ctx, "w")
    for _ in range(3):
        lease_expired(ctx)
        w.run_one()
    v = status(client, keys, rid)
    assert v["status"] == "synced", f"{v['status']}: the namespace is gone and the request holds its lock"


def test_argocd_later_merge_does_not_fail_an_earlier_request(world):
    """status.sync.revision is the head of main: one more merge and it never equals this request's merge sha."""
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    argocd(ctx, sync_timeout_seconds=0)
    res = argo_applied(git, kube)
    git.branches["main"]["README.md"] = "another request merged after this one\n"
    later = git._sha("main")
    git.commits.append(f"{later[:8]} later")
    kube.get = lambda path, params=None: app(later, resources=res)
    time.sleep(0.01)
    lease_expired(ctx); Worker(ctx, "w").run_one()
    v = status(client, keys, rid)
    assert v["status"] == "synced", (v["status"], v["events"][-1]["note"])


def test_argocd_another_namespaces_pending_prune_does_not_fail_this_request(world):
    """One root Application: a namespace waiting for Prune=confirm leaves the whole Application OutOfSync."""
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    argocd(ctx, sync_timeout_seconds=0)
    import yaml
    res = [{"kind": "Namespace", "name": "old-team", "status": "OutOfSync", "requiresPruning": True}]
    for p, t in git.branches["main"].items():
        if p.endswith(".yaml"):
            for d in yaml.safe_load_all(t):
                kube.apply(d)
                res.append({"kind": d["kind"], "name": d["metadata"]["name"], "namespace": d["metadata"].get("namespace"), "status": "Synced"})
    kube.get = lambda path, params=None: app(git.heads["main"], sync="OutOfSync", resources=res,
                                             op={"phase": "Running", "message": "waiting for pruning confirmation of /Namespace/old-team"})
    time.sleep(0.01)
    lease_expired(ctx); Worker(ctx, "w").run_one()
    v = status(client, keys, rid)
    assert v["status"] == "synced", (v["status"], v["events"][-1]["note"][:160])


def _merged_with_app(client, ctx, git, kube, keys, **k):
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    argocd(ctx)
    return rid, argo_applied(git, kube)


def test_argocd_own_object_out_of_sync_keeps_waiting(world):
    client, ctx, git, kube, validator, keys = world
    rid, res = _merged_with_app(client, ctx, git, kube, keys)
    res[0]["status"] = "OutOfSync"
    kube.get = lambda path, params=None: app(git.heads["main"], resources=res)
    lease_expired(ctx); Worker(ctx, "w").run_one()
    assert status(client, keys, rid)["status"] == "merged"


def test_argocd_on_a_revision_before_the_merge_keeps_waiting(world):
    client, ctx, git, kube, validator, keys = world
    rid, res = _merged_with_app(client, ctx, git, kube, keys)
    kube.get = lambda path, params=None: app("a" * 40, resources=res)
    lease_expired(ctx); Worker(ctx, "w").run_one()
    assert status(client, keys, rid)["status"] == "merged"


# ------------------------------------------------------------------ C3: a stale worker's side effects
def test_a_stale_open_pr_does_not_close_the_pr_the_live_worker_owns(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    real = git.read_folder
    done = {}

    def paused(*a, **k):
        out = real(*a, **k)
        if not done:
            done["x"] = 1
            lease_expired(ctx)                    # the first worker is paused past its lease here
            assert Worker(ctx, "w2").run_one()    # the second opens the PR and commits pr_open
        return out
    git.read_folder = paused
    Worker(ctx, "w1").run_one()
    git.read_folder = real
    v = status(client, keys, rid)
    assert v["status"] == "pr_open" and git.prs[1]["state"] == "open", (v["status"], git.prs[1]["state"])


def test_lease_lost_in_the_failure_path_does_not_escape_run_one(world):
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    real = git.read_folder

    def paused_then_fail(*a, **k):
        lease_expired(ctx)
        with ctx.db.session() as s:
            JobRepo(s).claim("w2")
        raise RuntimeError("the Git call failed after the pause")
    git.read_folder = paused_then_fail
    Worker(ctx, "w1").run_one()                   # must log lease_lost, not raise
    git.read_folder = real
    with ctx.db.session() as s:                   # and record nothing over the new owner's claim
        row = s.execute(text("select locked_by, locked_until, last_error from jobs where kind='open_pr'")).one()
    assert row[0] == "w2" and row[1] is not None and row[2] is None, row


def test_a_stale_worker_does_not_merge(world):
    """The commit is fenced; the merge happens before the commit. A pause before it must not reach the Git host."""
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    assert run_until(ctx, "pr_checks") == "pr_checks"
    real_validate, real_merge = validator.validate, git.merge
    merges = []
    git.merge = lambda *a: merges.append(a) or real_merge(*a)

    def paused(*a, **k):
        lease_expired(ctx)
        with ctx.db.session() as s:
            JobRepo(s).claim("w2")
        return real_validate(*a, **k)
    validator.validate = paused
    Worker(ctx, "w1").run_one()
    assert merges == [], "a worker that lost its lease merged"


def test_the_same_worker_id_reclaiming_is_still_a_new_lease(world):
    """A container restart in one pod keeps CMAPI_WORKER_ID = the pod name: only the generation tells the two apart."""
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    with ctx.db.session() as s:
        j = JobRepo(s).claim("pod-1"); gen, jid = j.lease_generation, j.job_id
    lease_expired(ctx)
    with ctx.db.session() as s:
        s.execute(text("update jobs set locked_until = now() + interval '1 hour' where job_id <> :j"), {"j": jid})
        assert JobRepo(s).claim("pod-1").job_id == jid
    with ctx.db.session() as s:
        with pytest.raises(LeaseLost):
            JobRepo(s).assert_lease(jid, "pod-1", gen)


def test_a_hung_handler_does_not_hold_the_lease_for_ever(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    import cmapi.worker as wm
    monkeypatch.setattr(wm, "LEASE_SECONDS", 1)
    monkeypatch.setattr(wm, "MAX_JOB_SECONDS", 2, raising=False)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    with ctx.db.session() as s:
        s.execute(text("update jobs set locked_until = now() + interval '1 hour' where kind='approval_timeout'"))
    release = threading.Event()
    started = threading.Event()
    real = git.read_folder

    def hang(*a, **k):
        started.set()
        release.wait(8)
        raise RuntimeError("released")
    git.read_folder = hang
    t = threading.Thread(target=lambda: Worker(ctx, "w1").run_one(), daemon=True)
    t.start()
    started.wait(5)
    
    claimed = None
    deadline = time.time() + 6
    while time.time() < deadline and claimed is None:
        with ctx.db.session() as s:
            j = JobRepo(s).claim("w2", 60)
            claimed = j.job_id if j else None
        time.sleep(0.2)
    release.set()
    t.join(10)
    git.read_folder = real
    assert claimed is not None, "a wedged handler keeps renewing its lease: no other worker can ever take the job"


# ------------------------------------------------------------------ C4: the prune
def _awaiting(ctx, client, keys, mode="argocd"):
    if mode == "argocd":
        ctx.delivery = type(ctx.delivery)(mode="argocd", poll_seconds=0)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='awaiting_prune', action='delete'"))
        rid = s.execute(text("select request_id from change_requests")).scalar()
        JobRepo(s).enqueue("prune", request_id=rid, cluster_id="CRC")
        s.execute(text("delete from jobs where kind='open_pr'"))
    return rid


def _pending(ctx):
    with ctx.db.session() as s:
        return s.execute(text("select count(*) from jobs where kind='prune' and done_at is null")).scalar()


# A failing read, a cluster gone from the config, a 403 and a bug were "waits" in this pass's first draft (the job
# never exhausted, the request never left awaiting_prune). The converged contract bounds them: each ends in
# sync_failed with the reason, and :retry enqueues the prune again. test_second_pass_converged holds those tests.


def test_an_unmanaged_namespace_at_prune_leaves_a_way_out(world):
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    kube.add_unmanaged_namespace("payments-dev")
    lease_expired(ctx); Worker(ctx, "w").run_one()
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed", f"{v['status']}, no job left and no transition out: the name is locked for ever"


# ------------------------------------------------------------------ C2: the private submitter
def test_dry_run_on_behalf_of_works(world):
    client, ctx, git, kube, validator, keys = world
    ctx.pipeline.directory = CachedDirectory(InMemoryDirectory([Person(username="jane", email="jane@ephico2real.com", sub="sub-jane")]))
    bot = dict(roles=["cmapi-onboarding"], groups=[], sub="sub-bot")
    r = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json={**NS, "onBehalfOf": "jane"}, headers=auth(keys, "bot-user", **bot))
    assert r.status_code == 200, r.text[:300]
    assert "sub-bot" not in r.text


# ------------------------------------------------------------------ C5: migrations
BASE = DB_URL.split("?")[0]


def _schema(name):
    return f"{BASE}?options=-csearch_path%3D{name}"


@pytest.fixture
def schema():
    c = psycopg.connect(BASE, autocommit=True)
    c.execute("DROP SCHEMA IF EXISTS sp CASCADE"); c.execute("CREATE SCHEMA sp")
    yield _schema("sp")
    c.execute("DROP SCHEMA sp CASCADE"); c.close()


def migrate(url, *args, timeout=60):
    return subprocess.run([sys.executable, "-c", "import sys; from cmapi.core.db.migrate import run; run(sys.argv[1:])", *args],
                          env={**os.environ, "CMAPI_DATABASE_URL": url, "PYTHONPATH": str(ROOT/"cmapi/src"), "PYTHONDONTWRITEBYTECODE": "1"},
                          capture_output=True, text=True, timeout=timeout)


def test_rollback_image_init_container_on_a_newer_schema_starts(schema):
    """A later release migrated; the owner rolls back. /readyz says 'a newer revision counts as past': so must the init."""
    assert migrate(schema, "head").returncode == 0
    c = psycopg.connect(BASE, autocommit=True)
    c.execute("update sp.alembic_version set version_num='0004'")
    r = migrate(schema, "head")
    c.close()
    assert r.returncode == 0, r.stderr.strip().splitlines()[-1][:200]


def test_migrate_gives_up_behind_a_long_transaction_instead_of_stalling_every_reader(schema):
    """ALTER TABLE waits for ACCESS EXCLUSIVE behind an old worker's open transaction; every later reader queues behind it."""
    assert migrate(schema, "0002").returncode == 0
    old = psycopg.connect(_schema("sp")); old.execute("select * from jobs limit 1")      # an old pod's open transaction
    p = subprocess.Popen([sys.executable, "-c", "from cmapi.core.db.migrate import run; run(['head'])"],
                         env={**os.environ, "CMAPI_DATABASE_URL": schema, "PYTHONPATH": str(ROOT/"cmapi/src"), "PYTHONDONTWRITEBYTECODE": "1", "CMAPI_MIGRATE_LOCK_TIMEOUT": "2s"},
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(1.5)
    r = psycopg.connect(_schema("sp"), autocommit=True); r.execute("set statement_timeout='1500ms'")
    blocked = False
    try:
        r.execute("select count(*) from jobs").fetchone()
    except psycopg.errors.QueryCanceled:
        blocked = True
    r.close()
    try:
        p.wait(8); exited = True
    except subprocess.TimeoutExpired:
        p.kill(); exited = False
    old.rollback(); old.close()
    print(f"[measure] migrate behind an open transaction: a reader blocked={blocked}, migrate exited within 10 s={exited}")
    assert exited, "migrate waits for ever, and every query on the table queues behind it"


def test_a_migration_that_fails_leaves_the_last_good_revision_and_the_lock_free(schema):
    assert migrate(schema, "0002").returncode == 0
    c = psycopg.connect(BASE, autocommit=True)
    c.execute("alter table sp.jobs add column lease_generation text")    # 0003 will collide with this
    r = migrate(schema, "head")
    assert r.returncode != 0
    assert c.execute("select version_num from sp.alembic_version").fetchone()[0] == "0002"
    assert c.execute("select count(*) from pg_locks where locktype='advisory' and objid=727364 and granted").fetchone()[0] == 0
    c.close()


def test_migrate_twice_is_a_no_op(schema):
    assert migrate(schema, "head").returncode == 0
    r = migrate(schema, "head")
    assert r.returncode == 0 and "migrated to head" in r.stdout


# ------------------------------------------------------------------ C8, C9: charts and scripts
import shutil, stat, yaml
DIG = "sha256:" + "a" * 64
CHART, CRC = ROOT/"deploy/helm/cmapi", ROOT/"deploy/environments/crc.yaml"


def helm(*a):
    return subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", *a], capture_output=True, text=True)


def test_the_policy_can_contain_argo_cds_controller():
    who = "system:serviceaccount:cmapi-argocd:argocd-application-controller"
    r = helm("-f", str(CRC), "--set", f"cmapi.digest={DIG}", "--set", "trustedCA.certificates=x", "--set", "delivery.mode=argocd", "--set", "delivery.hubDeliverer.enabled=false",
             "--set", f"argocd.controllerServiceAccount={who}", "--set", "argocd.namespace=cmapi-argocd")
    assert r.returncode == 0, r.stderr
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    vap = [d for d in docs if d["kind"] == "ValidatingAdmissionPolicy"]
    assert vap and who in vap[0]["spec"]["matchConditions"][0]["expression"]
    assert not [d for d in docs if d["kind"] in ("ClusterRole", "ClusterRoleBinding")], "no write identity for cmapi itself"


# The test that read one Application per namespace pinned the name cluster-configs-CRC-payments-dev, which the API
# server refuses (upper case): removed in the third pass; test_third_pass_fixes holds the one with the real rule.


def test_docs_sign_in_for_the_bot_carries_the_client_secret():
    # The recipe moved from docs/04 to docs/15 when docs/04 became the samples of a run: the same check, on the same recipe.
    text_ = (ROOT/"docs/15-keycloak-integration.md").read_text()
    block = text_[text_.index("client_id=cmapi-automation"):][:200]
    assert "client_secret" in block, "401 unauthorized_client on real Keycloak 26.6.4"


def test_secrets_survive_namespace_deletion_by_reading_the_keycloak_copy():
    assert 'lookup "v1" "Secret" $r.namespace "cmapi-realm-secrets"' in (CHART/"templates/secrets.yaml").read_text()


STUB = r"""#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$STUBLOG"
case "$(basename "$0")" in
  podman)
    # build records the GIT_COMMIT build-arg; run (the stamp check) and oc exec read it back, as the real image would
    if [ "$1" = build ]; then for a in "$@"; do case "$a" in GIT_COMMIT=*) printf '%s' "${a#GIT_COMMIT=}" > "$STATE/commit" ;; esac; done; fi
    [ "$1" = push ] && touch "$STATE/pushed.$(date +%s%N)" && touch "$STATE/image"
    # a run of a registry image by digest reads the registry's stamp (registry-commit, when a test set one)
    if [ "$1" = run ]; then case "$*" in *@sha256:*) cat "$STATE/registry-commit" 2>/dev/null || cat "$STATE/commit" ;; *) cat "$STATE/commit" ;; esac; fi ;;
  oc)
    case "$*" in
      "whoami") echo admin ;; "whoami -t") echo tok ;;
      get\ istag*jsonpath*) echo sha256:$(printf 'b%.0s' {1..64}) ;;
      get\ istag*) [ -e "$STATE/image" ] || exit 1 ;;
      get\ secret\ keycloak-tls*) printf '%s' "-----BEGIN CERTIFICATE-----" | base64 ;;
      get\ cm*) echo "-----BEGIN CERTIFICATE-----" ;;
      get\ secret\ cmapi-reader-token*token*) printf 'c2VjcmV0dG9r' ;;
      get\ secret\ cmapi-reader-token*ca*) printf 'Y2E=' ;;
      apply*) f="${@: -1}"; cp "$f" "$STATE/applied.$(basename "$f")" ;;
      exec*) cat "$STATE/commit" ;;
    esac ;;
esac
exit 0
"""


def _stubs(tmp_path):
    bindir = tmp_path/"bin"; bindir.mkdir()
    state = tmp_path/"state"; state.mkdir()
    for tool in ("podman", "oc", "helm"):
        f = bindir/tool; f.write_text(STUB); f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return {**os.environ, "PATH": f"{bindir}:{pathlib.Path(sys.executable).parent}:{os.environ['PATH']}", "STUBLOG": str(tmp_path/"log"), "STATE": str(state),
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}, state


def test_release_runs_twice_in_a_row(tmp_path):
    """The second run reuses the clean tag after reading its stamp (test_third_pass_converged has the mismatch)."""
    repo = tmp_path/"repo"; (repo/"cmapi").mkdir(parents=True)
    shutil.copytree(ROOT/"deploy", repo/"deploy"); shutil.copy(ROOT/"cmapi/pyproject.toml", repo/"cmapi/pyproject.toml")
    env, state = _stubs(tmp_path)
    for cmd in (["git", "init", "-q"], ["git", "add", "."], ["git", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, env=env, check=True)
    for n in (1, 2):
        r = subprocess.run(["bash", "deploy/release-crc.sh", "--no-portal"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"run {n}: {r.stderr[-200:]}"
    assert len(list(state.glob("pushed.*"))) == 1
    assert (tmp_path/"log").read_text().count("helm upgrade --install") == 2


def test_the_baseline_an_owner_needs_is_a_command(tmp_path):
    repo = tmp_path/"repo"; (repo/"examples").mkdir(parents=True)
    shutil.copytree(ROOT/"deploy", repo/"deploy"); shutil.copytree(ROOT/"examples/baseline", repo/"examples/baseline")
    docs = [d for d in yaml.safe_load_all((repo/"examples/baseline/cmapi-reader-rbac.yaml").read_text()) if d]
    names = {(d["kind"], d["metadata"]["name"]) for d in docs}
    assert {("Namespace", "cmapi-system"), ("ClusterRole", "cmapi-token-issuer"), ("Secret", "cmapi-reader-token")} <= names, names
    env, state = _stubs(tmp_path)
    r = subprocess.run(["bash", "deploy/baseline-crc.sh"], cwd=repo, env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr[-300:]
    secret = yaml.safe_load(next(state.glob("applied.tmp*")).read_text())
    assert secret["metadata"]["labels"] == {"cmapi.net/secret-type": "cluster", "cmapi.net/cluster-id": "CRC"} and set(secret["data"]) == {"apiUrl", "token", "caData"}
    assert "c2VjcmV0dG9r" not in (tmp_path/"log").read_text(), "the token reached an argument"


def test_migrate_waits_for_a_database_that_is_not_up_yet():
    """The first install: CNPG has written its Secret and the primary is not listening. A late listener must succeed."""
    import socket
    from urllib.parse import urlparse
    u = urlparse(BASE)
    probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
    stop, waited = threading.Event(), threading.Event()

    def forward():
        # The listener comes up only after cmapi-migrate has said that it waits. A fixed sleep raced the subprocess's start on a loaded machine (#139).
        if not waited.wait(timeout=30):
            return
        srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(("127.0.0.1", port)); srv.listen(8); srv.settimeout(0.3)
        def pipe(a, b):
            try:
                while True:
                    d = a.recv(65536)
                    if not d:
                        break
                    b.sendall(d)
            except OSError:
                pass
            finally:
                for x in (a, b):
                    try: x.close()
                    except OSError: pass
        while not stop.is_set():
            try:
                c, _ = srv.accept()
            except OSError:
                continue
            t = socket.create_connection((u.hostname, u.port))
            threading.Thread(target=pipe, args=(c, t), daemon=True).start()
            threading.Thread(target=pipe, args=(t, c), daemon=True).start()
        srv.close()
    threading.Thread(target=forward, daemon=True).start()
    c = psycopg.connect(BASE, autocommit=True); c.execute("DROP SCHEMA IF EXISTS spw CASCADE"); c.execute("CREATE SCHEMA spw")
    url = f"postgresql://{u.username}:{u.password}@127.0.0.1:{port}{u.path}?options=-csearch_path%3Dspw"
    p = subprocess.Popen([sys.executable, "-c", "from cmapi.core.db.migrate import run; run(['head'])"],
                         env={**os.environ, "CMAPI_DATABASE_URL": url, "PYTHONPATH": str(ROOT/"cmapi/src"), "PYTHONDONTWRITEBYTECODE": "1", "CMAPI_MIGRATE_WAIT_SECONDS": "30"},
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = []
    for line in p.stdout:                       # ends when the process closes its stdout
        out.append(line)
        if "waiting for the database" in line:
            waited.set()
    try:
        rc, err = p.wait(timeout=60), p.stderr.read()
    finally:
        stop.set(); waited.set()
        if p.poll() is None:
            p.kill()
    stdout = "".join(out)
    c.execute("DROP SCHEMA spw CASCADE"); c.close()
    assert rc == 0, (err.strip().splitlines() or ["no stderr"])[-1][:160]
    assert "waiting for the database" in stdout and "s3" not in stdout


# ------------------------------------------------------------------ C11: what the chart tests could not see
def _vap():
    r = helm("-f", str(CRC), "--set", f"cmapi.digest={DIG}", "--set", "trustedCA.certificates=x", "--set", "delivery.mode=apply", "--set", "delivery.hubDeliverer.enabled=true", "--set", "delivery.hubDeliverer.acknowledgeDirectWrites=true")
    assert r.returncode == 0, r.stderr
    return next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == "ValidatingAdmissionPolicy")["spec"]


def test_the_managed_label_is_read_from_the_old_object_on_update():
    """The label-first attack (measured on 1.33.5 and 1.35.6) is stopped only by reading oldObject."""
    labels = next(v["expression"] for v in _vap()["variables"] if v["name"] == "labels")
    assert "oldObject.metadata.labels" in labels and 'request.operation == "CREATE" ? object.metadata.labels' in labels


def test_each_rule_of_the_policy_is_really_a_rule():
    exprs = [v["expression"] for v in _vap()["validations"]]
    joined = " ".join(exprs)
    assert "true ||" not in joined
    assert 'object.roleRef.name == "cmapi-token-issuer"' in joined and 's.namespace == "cmapi-system"' in joined
    assert "variables.newLabels.all(k" in joined and "!k.matches(variables.reservedKey)" in joined


def test_the_policy_matches_the_writer_and_denies():
    spec = _vap()
    assert spec["matchConditions"][0]["expression"] == 'request.userInfo.username == "system:serviceaccount:cmapi:cmapi-worker"'
    r = helm("-f", str(CRC), "--set", f"cmapi.digest={DIG}", "--set", "trustedCA.certificates=x", "--set", "delivery.mode=apply", "--set", "delivery.hubDeliverer.enabled=true", "--set", "delivery.hubDeliverer.acknowledgeDirectWrites=true")
    binding = next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == "ValidatingAdmissionPolicyBinding")
    assert binding["spec"]["validationActions"] == ["Deny"] and spec["failurePolicy"] == "Fail"


def test_both_workloads_migrate_before_they_start():
    r = helm("-f", str(CRC), "--set", f"cmapi.digest={DIG}", "--set", "trustedCA.certificates=x")
    for d in yaml.safe_load_all(r.stdout):
        if d and d["kind"] == "Deployment":
            assert d["spec"]["template"]["spec"]["initContainers"][0]["command"] == ["cmapi-migrate", "head"], d["metadata"]["name"]


def test_docs_do_not_claim_a_span_export_that_does_not_exist():
    assert "in-process span export" not in (ROOT/"docs/10-architecture-review.md").read_text()


def test_gitea_deletes_a_stale_branch_before_reopening():
    from cmapi.core.git.gitea import GiteaProvider
    import httpx
    calls = []
    exists = {"branch": True}

    def handler(req):
        calls.append((req.method, req.url.path))
        p = req.url.path
        if req.method == "GET" and p.endswith("/pulls"):
            return httpx.Response(200, json=[])
        if req.method == "GET" and "/branches/" in p:
            return httpx.Response(200, json={"commit": {"id": "b" * 40}}) if exists["branch"] else httpx.Response(404, json={})
        if req.method == "DELETE":
            exists["branch"] = False
            return httpx.Response(204)
        if req.method == "POST" and p.endswith("/branches"):
            exists["branch"] = True
            return httpx.Response(201, json={})
        if req.method == "GET" and "/contents/" in p:
            return httpx.Response(404, json={})
        if req.method == "POST" and p.endswith("/contents"):
            return httpx.Response(201, json={})
        if req.method == "POST" and p.endswith("/pulls"):
            return httpx.Response(201, json={"number": 9, "html_url": "u", "head": {"ref": "br", "sha": "c" * 40}})
        return httpx.Response(500)
    g = GiteaProvider("https://g.test/api/v1", "o/r", "t")
    g._client = httpx.Client(base_url="https://g.test/api/v1", transport=httpx.MockTransport(handler))
    g.open_pr("br", {"clusters/CRC/namespaces/a/namespace.yaml": "x"}, "t", "b", "a" * 40)
    assert ("DELETE", "/api/v1/repos/o/r/branches/br") in calls, "a closed PR's branch is reused with whatever was pushed to it"
