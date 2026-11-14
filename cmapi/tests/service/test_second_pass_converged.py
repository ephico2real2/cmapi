"""Second pass, converged: the contracts both reviewers settled on, each asserted as it is now specified.

Argo CD confirms a request only when Git main still holds the plan, a compared revision contains the merge, and
this folder's own objects are Synced. A prune waits for two things only (a reader not connected yet, a namespace
still there); every other failure is bounded and ends in sync_failed, which :retry can leave. A schema revision
this code does not know is ready only by the four-digit convention. The chart and scripts carry the rest."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import textwrap

import psycopg
import pytest
import yaml
from sqlalchemy import text

from cmapi.core.clients.kube import KubeError
from cmapi.core.db import REQUIRED_REVISION, older_than_required
from cmapi.worker import MAX_ATTEMPTS, Worker
from test_flow import NS, OLA, OPAL, auth
from test_review_d_delivery import run_until, status
from test_review_e_recovery import lease_expired
from test_second_pass import BASE, _awaiting, _pending, _stubs, app, argo_applied, argocd, helm, migrate, schema  # noqa: F401

ROOT = pathlib.Path(__file__).resolve().parents[3]
CHART, CRC = ROOT / "deploy/helm/cmapi", ROOT / "deploy/environments/crc.yaml"
DIG = "sha256:" + "a" * 64
APPLY = ("--set", "delivery.mode=apply", "--set", "delivery.hubDeliverer.enabled=true", "--set", "delivery.hubDeliverer.acknowledgeDirectWrites=true")


def _merged(client, ctx, git, kube, keys):
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    argocd(ctx, sync_timeout_seconds=0)
    return rid, argo_applied(git, kube)


def _prune_jobs(ctx):
    with ctx.db.session() as s:
        return s.execute(text("select kind, done_at is null, attempts from jobs where kind in ('prune','watch_sync') order by job_id")).all()


# ------------------------------------------------------------------ Argo CD: the status contract
def test_argocd_refuses_when_main_no_longer_holds_the_plan(world):
    """A later change to the folder is a new request, not this one: Argo CD syncing it must not confirm this one."""
    client, ctx, git, kube, validator, keys = world
    rid, res = _merged(client, ctx, git, kube, keys)
    folder_file = next(p for p in git.branches["main"] if "payments-dev" in p and p.endswith(".yaml"))
    git.branches["main"][folder_file] += "\n# changed on main after the merge\n"
    kube.get = lambda path, params=None: app(git.heads["main"], resources=res)
    lease_expired(ctx); Worker(ctx, "w").run_one()
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed", v["status"]
    assert "differs from the approved plan" in v["events"][-1]["note"]


def test_argocd_multi_source_revisions_count(world):
    """A multi-source Application reports status.sync.revisions and no revision; any of them holding the merge counts."""
    client, ctx, git, kube, validator, keys = world
    rid, res = _merged(client, ctx, git, kube, keys)
    head = git.heads["main"]
    kube.get = lambda path, params=None: {"status": {"sync": {"status": "Synced", "revisions": ["f" * 40, head]}, "health": {"status": "Healthy"},
                                                     "resources": res, "operationState": {"phase": "Succeeded"}}}
    lease_expired(ctx); Worker(ctx, "w").run_one()
    v = status(client, keys, rid)
    assert v["status"] == "synced", (v["status"], v["events"][-1]["note"])


def test_argocd_an_older_revision_than_the_merge_keeps_waiting(world):
    """Argo CD still at the revision before the merge: the folder is Synced for the old content, so nothing is confirmed."""
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    argocd(ctx)
    res = argo_applied(git, kube)
    before_merge = git.main_history[-2]
    kube.get = lambda path, params=None: app(before_merge, resources=res)
    lease_expired(ctx); Worker(ctx, "w").run_one()
    v = status(client, keys, rid)
    assert v["status"] == "merged" and "none holding" in v["events"][-1]["note"], (v["status"], v["events"][-1]["note"])


# ------------------------------------------------------------------ the prune: bounded, never stranded
@pytest.mark.parametrize("make_error", [
    pytest.param(lambda: KubeError(403, "/api/v1/namespaces/x", "forbidden"), id="forbidden"),
    pytest.param(lambda: TypeError("a bug"), id="programming-error"),
])
def test_a_prune_that_keeps_failing_ends_in_sync_failed_with_a_way_out(world, make_error):
    """After MAX_ATTEMPTS the request is sync_failed with the reason, the job is done, and :retry enqueues a prune,
    not a watch_sync, which confirms the absence."""
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    real = kube.get_object
    kube.get_object = lambda *a, **k: (_ for _ in ()).throw(make_error())
    w = Worker(ctx, "w")
    for _ in range(MAX_ATTEMPTS + 2):
        lease_expired(ctx); w.run_one()
    kube.get_object = real
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed", v["status"]
    assert f"after {MAX_ATTEMPTS} attempts" in v["events"][-1]["note"] and type(make_error()).__name__ in v["events"][-1]["note"], v["events"][-1]["note"]
    assert _prune_jobs(ctx) == [("prune", False, MAX_ATTEMPTS)], _prune_jobs(ctx)
    r = client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 200, r.text
    assert _prune_jobs(ctx)[-1] == ("prune", True, 0), _prune_jobs(ctx)
    lease_expired(ctx); w.run_one()
    assert status(client, keys, rid)["status"] == "synced"


def test_a_prune_retried_onto_an_unmanaged_namespace_stays_sync_failed(world):
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    kube.add_unmanaged_namespace("payments-dev")
    lease_expired(ctx); Worker(ctx, "w").run_one()
    assert status(client, keys, rid)["status"] == "sync_failed"
    assert client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **OPAL)).status_code == 200
    lease_expired(ctx); Worker(ctx, "w").run_one()
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed" and v["events"][-1]["event"] == "refused", (v["status"], v["events"][-1])
    assert _pending(ctx) == 0


def test_a_cluster_gone_from_config_is_bounded_too(world):
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    st = ctx.registry.clusters.pop("CRC")
    w = Worker(ctx, "w")
    for _ in range(MAX_ATTEMPTS + 2):
        lease_expired(ctx); w.run_one()
    ctx.registry.clusters["CRC"] = st
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed" and "cluster" in v["events"][-1]["note"].lower(), (v["status"], v["events"][-1]["note"])
    assert _pending(ctx) == 0


def test_a_reader_not_connected_yet_is_a_wait_with_one_event(world):
    """Within syncTimeout a reader not connected is a wait: attempts stay at zero and the reason lands once
    (test_third_pass_converged has the bound: the clock run out ends in sync_failed)."""
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    from cmapi.core.errors import Problem
    real = ctx.registry.cache
    ctx.registry.cache = lambda cid: (_ for _ in ()).throw(Problem(503, "cluster-not-connected", f"{cid} is connecting"))
    w = Worker(ctx, "w")
    for _ in range(MAX_ATTEMPTS + 2):
        lease_expired(ctx); w.run_one()
    ctx.registry.cache = real
    v = status(client, keys, rid)
    assert v["status"] == "awaiting_prune", v["status"]
    assert _prune_jobs(ctx) == [("prune", True, 0)], _prune_jobs(ctx)
    assert len([e for e in v["events"] if e["event"] == "prune_waiting"]) == 1


# ------------------------------------------------------------------ schema revisions
def _history(tmp_path, *revisions):
    """A migration history of this repository's shape, built in tmp_path: (revision, down_revision) pairs."""
    from alembic.script import ScriptDirectory
    versions = tmp_path / "versions"; versions.mkdir(exist_ok=True)
    for rev, down in revisions:
        (versions / f"{rev}.py").write_text(textwrap.dedent(f'''
            revision = {rev!r}
            down_revision = {down!r}
            def upgrade(): pass
            def downgrade(): pass
        '''))
    return ScriptDirectory(str(tmp_path), version_locations=[str(versions)])


def test_revision_validation_by_the_history_and_the_convention(tmp_path, monkeypatch):
    import cmapi.core.db as db
    script = _history(tmp_path, ("0001", None), ("0002", "0001"), ("0003", "0002"), ("0004", "0003"), ("0009_divergent", "0001"))
    monkeypatch.setattr(db, "script_directory", lambda: script)
    # The cases below are written for a required revision of 0003 in this made-up history. The real value follows the newest
    # migration (test_pr40_convergence.py::test_required_revision_is_the_newest_migration).
    monkeypatch.setattr(db, "REQUIRED_REVISION", "0003")
    assert older_than_required("0001") is True and older_than_required("0002") is True
    assert older_than_required("0003") is False
    assert older_than_required("0004") is False, "a known descendant"
    assert older_than_required("0010_from_a_later_release") is False, "unknown, but a later number by the convention"
    assert older_than_required("0005") is False
    with pytest.raises(ValueError, match="divergent"):
        older_than_required("0009_divergent")
    for garbage in ("abc", "00ff", "0002x", "", "0003 ", "9999-later", "0001_Upper"):
        with pytest.raises(ValueError, match="unknown schema revision"):
            older_than_required(garbage)


def test_readiness_refuses_garbage_and_a_divergent_revision(world, monkeypatch):
    client, ctx, *_ = world
    monkeypatch.setattr(ctx.db, "schema_version", lambda: "deadbeef")
    r = client.get("/readyz")
    assert r.status_code == 503 and "unknown schema revision" in r.json()["schema"], r.text
    monkeypatch.setattr(ctx.db, "schema_version", lambda: "0004")
    assert client.get("/readyz").status_code == 200


def test_migrate_refuses_a_revision_it_cannot_place(schema):
    """A rolled-back image on a later release's database starts (the convention); on garbage it must not."""
    assert migrate(schema, "head").returncode == 0
    c = psycopg.connect(BASE, autocommit=True)
    later = f"{int(REQUIRED_REVISION) + 1:04d}"                 # the number of the next release's migration, by the convention
    c.execute("update sp.alembic_version set version_num=%s", (later,))
    r = migrate(schema, "head")
    assert r.returncode == 0 and "later release" in r.stdout, (r.returncode, r.stdout, r.stderr[-200:])
    c.execute("update sp.alembic_version set version_num='deadbeef'")
    r = migrate(schema, "head")
    c.close()
    assert r.returncode != 0 and "refusing to migrate" in r.stderr, (r.returncode, r.stderr[-300:])


# ------------------------------------------------------------------ chart, values and scripts
def _docs(*a):
    r = helm("-f", str(CRC), "--set", f"cmapi.digest={DIG}", "--set", f"cmapi_portal.digest={DIG}", *a)
    assert r.returncode == 0, r.stderr
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def test_crc_values_run_argocd_and_acknowledge_nothing():
    """CRC runs argocd with no direct-write acknowledgement; the policy it renders binds Argo CD's controller, never
    a cmapi identity (test_third_pass_converged::test_crc_names_the_controller_and_binds_the_policy_to_it)."""
    values = yaml.safe_load(CRC.read_text())
    assert values["delivery"]["mode"] == "argocd" and "hubDeliverer" not in values["delivery"], values["delivery"]
    assert values["argocd"]["namespace"] == "cmapi-argocd"
    docs = _docs("--set", "trustedCA.certificates=x")
    assert not [d for d in docs if d["kind"] in ("ClusterRole", "ClusterRoleBinding")], "CRC renders a write identity for cmapi"
    assert [d for d in docs if d["kind"] == "ConfigMap" and "argocd" in d["data"].get("integrations.yaml", "")]


def test_the_migrate_init_container_trusts_what_the_main_container_trusts():
    for name in ("cmapi-api", "cmapi-worker"):
        spec = next(d for d in _docs("--set", "trustedCA.certificates=x") if d["kind"] == "Deployment" and d["metadata"]["name"] == name)["spec"]["template"]["spec"]
        init = spec["initContainers"][0]
        env = {e["name"]: e.get("value") for e in init["env"]}
        assert env["PGSSLROOTCERT"] == "/etc/cmapi/ca/ca-bundle.crt" and env["SSL_CERT_FILE"] == env["PGSSLROOTCERT"], name
        mounts = {m["name"]: m["mountPath"] for m in init.get("volumeMounts", [])}
        assert mounts.get("trust") == "/etc/cmapi/ca", f"{name}: the init container verifies an external TLS database against nothing"
        assert any(v["name"] == "trust" for v in spec["volumes"]), name
    bare = helm("--set", f"cmapi.digest={DIG}", "--set", f"cmapi_portal.digest={DIG}", "--set", "portal.enabled=false", "--set", "argocd.controllerServiceAccount=system:serviceaccount:argocd:argocd-application-controller")
    assert bare.returncode == 0, bare.stderr
    for d in yaml.safe_load_all(bare.stdout):
        if d and d["kind"] == "Deployment":
            init = d["spec"]["template"]["spec"]["initContainers"][0]
            assert "PGSSLROOTCERT" not in {e["name"] for e in init["env"]} and not init.get("volumeMounts")


def test_gitea_creates_the_administrator_the_bootstrap_signs_in_as():
    r = subprocess.run(["helm", "template", "cmapi-git", str(ROOT / "deploy/helm/cmapi-git"), "-n", "cmapi"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    dep = next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] in ("Deployment", "StatefulSet"))
    c = next(c for c in dep["spec"]["template"]["spec"]["containers"] if c["name"] == "gitea")
    assert {"secretRef": {"name": "cmapi-git-admin"}} in c.get("envFrom", []), "the admin credential never reaches the gitea CLI"
    script = " ".join(c["lifecycle"]["postStart"]["exec"]["command"])
    assert "gitea admin user create" in script and "--admin" in script and "--must-change-password=false" in script
    assert "gitea admin user list" in script, "not idempotent: a restart fails on 'user already exists'"
    assert "/app/gitea/gitea" not in script, "the rootless image puts the binary on PATH as gitea"
    assert '--password "$CMAPI_GIT_ADMIN_PASSWORD"' in script, "the password must come from the Secret, never the chart"


def _release_repo(tmp_path):
    repo = tmp_path / "repo"; (repo / "cmapi").mkdir(parents=True)
    shutil.copytree(ROOT / "deploy", repo / "deploy"); shutil.copy(ROOT / "cmapi/pyproject.toml", repo / "cmapi/pyproject.toml")
    env, state = _stubs(tmp_path)
    for cmd in (["git", "init", "-q"], ["git", "add", "."], ["git", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, env=env, check=True)
    return repo, env, state


def test_release_is_atomic_unless_told_otherwise(tmp_path):
    repo, env, state = _release_repo(tmp_path)
    r = subprocess.run(["bash", "deploy/release-crc.sh", "--no-portal"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    log = (tmp_path / "log").read_text()
    assert "--atomic --cleanup-on-fail" in log and "--wait --timeout 10m" in log, log
    r = subprocess.run(["bash", "deploy/release-crc.sh", "--no-portal"], cwd=repo, env={**env, "RELEASE_ATOMIC": "false"}, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    assert "--atomic" not in (tmp_path / "log").read_text().splitlines()[-1]


def test_release_twice_on_a_dirty_tree_never_reuses_the_dirty_tag(tmp_path):
    repo, env, state = _release_repo(tmp_path)
    (repo / "cmapi/pyproject.toml").write_text((repo / "cmapi/pyproject.toml").read_text() + "\n# dirty\n")
    for n in (1, 2):
        r = subprocess.run(["bash", "deploy/release-crc.sh", "--no-portal", "--allow-dirty"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"run {n}: {r.stderr[-300:]}"
        assert "-dirty" in r.stdout and "not pushed again" not in r.stdout, r.stdout
    assert len(list(state.glob("pushed.*"))) == 2, "a dirty tag holds whatever the previous dirty build was: it must be pushed every time"
    r = subprocess.run(["bash", "deploy/release-crc.sh", "--no-portal"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "uncommitted" in r.stderr


def test_the_record_says_what_has_and_has_not_run():
    status_md = (ROOT / "CRC-BUILD-STATUS.md").read_text()
    code_status = (ROOT / "docs/08-code-status.md").read_text()
    review = (ROOT / "docs/10-architecture-review.md").read_text()
    for doc, name in ((status_md, "CRC-BUILD-STATUS.md"), (code_status, "docs/08"), (review, "docs/10")):
        assert "real Argo CD" in doc, f"{name}: does not say that nothing has run on a real Argo CD"
        assert "14 ValidatingAdmissionPolic" not in doc and "14 policies" not in doc, f"{name}: CRC has 13 policies (measured)"
    assert "acknowledgeDirectWrites: true" not in status_md and "`crc.yaml` acknowledges" not in status_md, \
        "the hand-over still tells the owner to acknowledge direct writes on CRC"
    record = (ROOT / "docs/reviews/2026-11-05-pr40.md").read_text()
    assert "gpt-5.6-sol" in record and "openshift-gitops-operator.v1.22.3" in record and "13 policies exist" in record
