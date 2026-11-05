"""Cross-check at 87d5e1a: each test states the correct outcome, and failed on that head."""
from __future__ import annotations

import pathlib
import re
import subprocess

import httpx
import pytest
import yaml
from sqlalchemy import text

from cmapi.core.clients.kube import ClusterUnreachable, KubeError
from cmapi.core.db import older_than_required
from cmapi.core.db.repo import JobRepo
from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.core.ports import AppStatus
from cmapi.core.sync import not_synced
from cmapi.worker import MAX_ATTEMPTS, Worker
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs
from test_review_d_delivery import run_until, status
from test_review_e_recovery import lease_expired
from test_second_pass import _awaiting, _stubs, app, argo_applied, argocd

ROOT = pathlib.Path(__file__).resolve().parents[3]
CHART, CRC = ROOT / "deploy/helm/cmapi", ROOT / "deploy/environments/crc.yaml"
DIG = "sha256:" + "a" * 64
FOLDER = "clusters/CRC/namespaces/payments-dev/"
BODY = {k: v for k, v in NS.items() if k != "namespace"}


def _run(ctx, n):
    w = Worker(ctx, "w")
    for _ in range(n):
        lease_expired(ctx); w.run_one()


def test_a_retry_of_an_apply_delete_nobody_confirmed_deletes_nothing(world):
    """Apply mode's one gate on a delete is POST /admin/prune:confirm. A delete whose watch_sync failed reaches sync_failed
    before anyone confirmed it, and :retry only looks again: only the confirmation removes the namespace."""
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h); run_jobs(ctx)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    rid = client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY))
    assert run_until(ctx, "watch_sync") == "watch_sync"
    st = ctx.registry.clusters.pop("CRC")
    _run(ctx, MAX_ATTEMPTS + 1)
    ctx.registry.clusters["CRC"] = st
    assert status(client, keys, rid)["status"] == "sync_failed"
    assert client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **OPAL)).status_code == 200
    _run(ctx, 3)
    assert kube.get_object("Namespace", None, "payments-dev") is not None, "a :retry deleted a namespace nobody confirmed"
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed" and "prune:confirm" in v["events"][-1]["note"], v["events"][-1]
    r = client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev"}, headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 200, r.text
    _run(ctx, 3)
    assert kube.get_object("Namespace", None, "payments-dev") is None
    assert status(client, keys, rid)["status"] == "synced"


def test_argocd_a_removed_object_still_live_keeps_the_request_waiting(world):
    """A plan removes a file. Argo CD still reports its object, OutOfSync and requiresPruning: the removal is not delivered."""
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h); run_jobs(ctx)
    git.tamper("main", FOLDER + "extra-binding.yaml", yaml.safe_dump(
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding", "metadata": {"name": "old-admin", "namespace": "payments-dev"},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "admin"},
         "subjects": [{"kind": "User", "name": "left-the-company"}]}))
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    r = client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={**BODY, "labels": {**NS["labels"], "cmapi.net/cost-center": "cc-4411"}},
                     headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 202, r.text
    rid = r.json()["requestId"]
    if r.json()["status"] == "pending_approval":
        client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY))
    assert run_until(ctx, "watch_sync") == "watch_sync"
    argocd(ctx)
    res = argo_applied(git, kube)
    stale = {"kind": "RoleBinding", "name": "old-admin", "namespace": "payments-dev", "status": "OutOfSync", "requiresPruning": True}
    kube.get = lambda path, params=None: app(git.heads["main"], sync="OutOfSync", resources=[*res, stale])
    _run(ctx, 1)
    v = status(client, keys, rid)
    assert v["status"] == "merged" and "old-admin" in v["events"][-1]["note"], (v["status"], v["events"][-1]["note"])
    kube.get = lambda path, params=None: app(git.heads["main"], resources=res)    # pruned: it has left the Application
    _run(ctx, 1)
    assert status(client, keys, rid)["status"] == "synced"


def test_the_application_cmapi_reads_has_a_name_kubernetes_accepts(world):
    """As shipped, crc.yaml names cluster-configs-{clusterId} and the cluster id is CRC. Measured on 1.35.6: creating
    cluster-configs-CRC is refused (lowercase RFC 1123), and reading it is 404 for ever, Argo CD installed or not."""
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    assert run_until(ctx, "watch_sync") == "watch_sync"
    values = yaml.safe_load(CRC.read_text())
    ctx.delivery = type(ctx.delivery)(mode="argocd", poll_seconds=0, argocd_namespace=values["argocd"]["namespace"],
                                      argocd_root_application=values["argocd"]["rootApplication"])
    seen = []
    kube.get = lambda path, params=None: seen.append(path) or app(git.heads["main"])
    _run(ctx, 1)
    name = seen[0].rsplit("/", 1)[1]
    assert seen[0].startswith("/apis/argoproj.io/v1alpha1/namespaces/cmapi-argocd/applications/")
    assert re.fullmatch(r"[a-z0-9]([-a-z0-9.]*[a-z0-9])?", name) and name == "cluster-configs-crc", name


def test_a_previous_document_with_no_name_is_not_an_object():
    """The previous folder is whatever Git held: a kustomization.yaml must not fail the job."""
    a = AppStatus(cluster_id="CRC", revision="r", sync="Synced", health="Healthy", phase=None,
                  resources=(("Namespace", "", "n", "Synced"),))
    assert not_synced(a, {"f/namespace.yaml": "kind: Namespace\nmetadata: {name: n}\n"},
                      {"f/kustomization.yaml": "kind: Kustomization\nresources: []\n", "f/list.yaml": "- a\n"}) == []


def test_argocd_a_neighbour_with_the_same_kind_and_name_does_not_count(world):
    """Mutant survivor at 87d5e1a: dropping the namespace from the key passed every test."""
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    argocd(ctx)
    res = argo_applied(git, kube)
    elsewhere = [{**r, "namespace": "other-team"} if r.get("namespace") else r for r in res]
    kube.get = lambda path, params=None: app(git.heads["main"], resources=elsewhere)
    _run(ctx, 1)
    assert status(client, keys, rid)["status"] == "merged"


def test_a_stale_worker_does_not_delete_the_namespace(world):
    """Mutant survivor at 87d5e1a: removing the fence before the prune's delete passed every test."""
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h); run_jobs(ctx)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    rid = client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY)); run_jobs(ctx)
    assert client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev"}, headers=auth(keys, "opal", **OPAL)).status_code == 200
    real_read, real_delete = kube.get_object, kube.delete
    deletes = []
    kube.delete = lambda *a, **k: deletes.append(a) or real_delete(*a, **k)

    def paused(*a, **k):                       # the pause is before the fence: the fence holds the row afterwards
        kube.get_object = real_read
        lease_expired(ctx)
        with ctx.db.session() as s:
            JobRepo(s).claim("w2")
        return real_read(*a, **k)
    kube.get_object = paused
    Worker(ctx, "w1").run_one()
    assert deletes == [], "a worker that lost its lease deleted the namespace"


def test_argocd_a_merged_request_with_no_merge_sha_fails_closed(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    argocd(ctx)
    res = argo_applied(git, kube)
    with ctx.db.session() as s:
        s.execute(text("update change_requests set merge_sha=null where request_id=:r"), {"r": rid})
    before_the_merge = git.main_history[0]
    kube.get = lambda path, params=None: app(before_the_merge, resources=res)
    _run(ctx, 1)
    assert status(client, keys, rid)["status"] == "merged", "confirmed against a revision nothing compared"


@pytest.mark.parametrize("provider", ["gitea", "github"])
def test_contains_says_no_for_a_revision_this_repository_does_not_hold(provider):
    """Real Gitea 1.25.5 answers 404 for a chart version or another repository's sha. A multi-source Application reports
    those beside the Git revision, and any() over a frozenset reaches them in hash order: 404 must not read as an outage."""
    code = {"code": 404}

    def handler(req):
        return httpx.Response(code["code"], json={"message": "not found"})
    g = GiteaProvider("https://g.test/api/v1", "o/r", "t") if provider == "gitea" else GitHubProvider("https://g.test", "o/r", "t")
    g._client = httpx.Client(base_url="https://g.test/api/v1", transport=httpx.MockTransport(handler))
    assert g.contains("1.2.3", "a" * 40) is False
    code["code"] = 500
    with pytest.raises(GitUnavailable):
        g.contains("1.2.3", "a" * 40)


@pytest.mark.parametrize("garbage", ["head", "heads", "base", "0003@head", "٠٠٠٤", "0003_foo"])
def test_a_symbol_or_a_foreign_digit_is_not_a_schema_revision(garbage):
    with pytest.raises(ValueError):
        older_than_required(garbage)


def test_a_cluster_outage_within_the_sync_timeout_waits_and_the_job_recovers(world):
    """Same failure, same bound as watch_sync: on CRC the import list fails with the API, so the relist never turns this
    into a wait, and five attempts are 200 s of backoff."""
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    ctx.delivery = type(ctx.delivery)(mode=ctx.delivery.mode, poll_seconds=0, sync_timeout_seconds=600)
    real = kube.get_object
    kube.get_object = lambda *a, **k: (_ for _ in ()).throw(ClusterUnreachable("the API server is down"))
    _run(ctx, MAX_ATTEMPTS + 3)
    v = status(client, keys, rid)
    assert v["status"] == "awaiting_prune", (v["status"], v["events"][-1])
    assert sum(e["event"] == "prune_waiting" for e in v["events"]) == 1, "the reason lands once"
    with ctx.db.session() as s:
        assert s.execute(text("select payload->>'unreachable_since' is not null, attempts from jobs where kind='prune'")).one() == (True, 0)
    kube.get_object = real
    _run(ctx, 1)
    with ctx.db.session() as s:
        assert s.execute(text("select payload->>'unreachable_since' from jobs where kind='prune'")).scalar() is None, "a later outage starts its own clock"
    kube.delete("Namespace", None, "payments-dev")
    _run(ctx, 1)
    assert status(client, keys, rid)["status"] == "synced"


def test_a_refusal_is_still_bounded_inside_the_sync_timeout(world):
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    ctx.delivery = type(ctx.delivery)(mode=ctx.delivery.mode, poll_seconds=0, sync_timeout_seconds=600)
    kube.get_object = lambda *a, **k: (_ for _ in ()).throw(KubeError(403, "/api/v1/namespaces/x", "forbidden"))
    _run(ctx, MAX_ATTEMPTS + 1)
    assert status(client, keys, rid)["status"] == "sync_failed"


@pytest.mark.parametrize("listed,creates", [(True, False), (False, True)])
def test_the_gitea_hook_creates_the_administrator_only_when_it_is_missing(tmp_path, listed, creates):
    """Runs the rendered script against a stub CLI. Mutant survivor at 87d5e1a: a hook that always creates passed every
    test, and on the real image a second start would fail on 'user already exists' and kill the container."""
    r = subprocess.run(["helm", "template", "cmapi-git", str(ROOT / "deploy/helm/cmapi-git"), "-n", "cmapi"], capture_output=True, text=True)
    dep = next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == "Deployment")
    script = dep["spec"]["template"]["spec"]["containers"][0]["lifecycle"]["postStart"]["exec"]["command"][2]
    script = script.replace("/tmp/users", str(tmp_path / "users"))
    row = "1   gitea-admin   cmapi-admin@invalid.example   true   true   false" if listed else "ID   Username   Email"
    stub = tmp_path / "gitea"
    stub.write_text(f'#!/bin/sh\ncase "$3" in list) echo "{row}" ;; create) echo create >> "{tmp_path}/calls" ;; esac\n')
    stub.chmod(0o755)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "CMAPI_GIT_ADMIN_USER": "gitea-admin", "CMAPI_GIT_ADMIN_PASSWORD": "x"}
    assert subprocess.run(["/bin/sh", "-ec", script], env=env, capture_output=True, text=True, timeout=20).returncode == 0
    assert (tmp_path / "calls").exists() is creates


@pytest.mark.parametrize("key", ["CMAPI_REALM_ADMIN_SECRET", "CMAPI_DIRECTORY_SECRET", "CMAPI_SVC_PAYMENTS_CI_SECRET", "CMAPI_AUTOMATION_SECRET"])
def test_each_realm_secret_falls_back_to_the_keycloak_copy(key):
    """Mutant survivor at 87d5e1a: dropping the admin secret's fallback passed. Measured on 1.35.6 with the fallback in
    place: the namespace's copy deleted, a failed install and a good one restore all four values unchanged."""
    assert f'| default (index $imp "{key}") | default (randAlphaNum 48' in (CHART / "templates/secrets.yaml").read_text()


def _render(*sets):
    a = [x for s in sets for x in ("--set", s)]
    return subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", "-f", str(CRC), "--set", f"cmapi.digest={DIG}", "--set", "trustedCA.certificates=x", *a],
                          capture_output=True, text=True)


@pytest.mark.parametrize("who", ["argocd-application-controller", "cmapi-argocd:argocd-application-controller", "system:serviceaccount:argocd-application-controller"])
def test_the_chart_refuses_an_identity_the_policy_could_never_match(who):
    """Measured on 1.35.6: the short name renders both policy objects and denies nothing."""
    r = _render(f"argocd.controllerServiceAccount={who}")
    assert r.returncode != 0 and "system:serviceaccount:<namespace>:<name>" in r.stderr, r.stderr[-200:]


def test_the_chart_takes_the_real_identity():
    who = "system:serviceaccount:cmapi-argocd:argocd-application-controller"
    r = _render(f"argocd.controllerServiceAccount={who}")
    assert r.returncode == 0, r.stderr[-300:]
    assert any(d and d["kind"] == "ValidatingAdmissionPolicyBinding" for d in yaml.safe_load_all(r.stdout))


def _notes(*sets):
    a = [x for s in sets for x in ("--set", s)]
    r = subprocess.run(["helm", "install", "cmapi", str(CHART), "-n", "cmapi", "--dry-run=client", "-f", str(CRC), "--set", f"cmapi.digest={DIG}", "--set", "trustedCA.certificates=x", *a],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-300:]
    return r.stdout[r.stdout.index("NOTES:"):]


def test_the_install_says_when_nothing_contains_argo_cd():
    """An empty identity renders only when acknowledged (the ruling on F3), and then the NOTES say what that means."""
    assert "no admission policy contains Argo CD" in _notes("argocd.controllerServiceAccount=", "argocd.acknowledgeUncontainedController=true")
    assert "no admission policy contains Argo CD" not in _notes("argocd.controllerServiceAccount=system:serviceaccount:cmapi-argocd:ctrl")


@pytest.mark.parametrize("state,command", [("pending-install", "helm uninstall cmapi"), ("pending-upgrade", "helm rollback cmapi"), ("pending-rollback", "helm rollback cmapi")])
def test_release_stops_on_a_release_a_dead_helm_left_pending_and_names_the_way_out(tmp_path, state, command):
    """Measured on 1.35.6 and Helm 4.3.1: SIGKILL, or the API gone when --atomic would roll back, leaves pending-install."""
    import shutil
    repo = tmp_path / "repo"; (repo / "cmapi").mkdir(parents=True)
    shutil.copytree(ROOT / "deploy", repo / "deploy"); shutil.copy(ROOT / "cmapi/pyproject.toml", repo / "cmapi/pyproject.toml")
    env, _ = _stubs(tmp_path)
    for cmd in (["git", "init", "-q"], ["git", "add", "."], ["git", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, env=env, check=True)
    helm = tmp_path / "bin/helm"
    helm.write_text(f'#!/bin/sh\nif [ "$1" = status ]; then echo \'{{"info":{{"status":"{state}"}}}}\'; exit 0; fi\necho "helm $*" >> "$STUBLOG"\n')
    r = subprocess.run(["bash", "deploy/release-crc.sh", "--no-portal"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and command in r.stderr and state in r.stderr, r.stderr[-300:]
    assert "helm upgrade --install" not in (tmp_path / "log").read_text()


def test_the_docs_say_what_a_request_does_with_no_argo_cd():
    """Measured: waits at merged for syncTimeout, then sync_failed with sync_wait events; not 'stops at merged'."""
    for f in ("CRC-BUILD-STATUS.md", "docs/10-architecture-review.md", "deploy/environments/crc.yaml"):
        doc = (ROOT / f).read_text()
        assert "stops at" not in doc, f"{f} says a request stops at merged"
        assert "sync_failed" in doc, f
    assert "deploy/helm/cmapi-git -n cmapi --create-namespace" in (ROOT / "CRC-BUILD-STATUS.md").read_text(), \
        "measured: without it the guide's first command fails on a clean cluster"
