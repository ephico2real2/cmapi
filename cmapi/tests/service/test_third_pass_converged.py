"""Third pass, converged, at 87d5e1a: the coordinator's rulings on the cross-check, each asserted as specified.

The prune's inability to read a cluster is bounded by time (delivery.syncTimeout, one clock from the first failed
read), never by attempts or by the phase of the registry's relist; a refusal, a removed cluster and a bug stay
bounded by attempts; a namespace seen present is the operator's wait. The fence runs before every external side
effect. The realm Secret fails closed, with the realm CR's own apiVersion. An empty controller identity in argocd
mode fails to render unless acknowledged. A reused clean tag is verified by its stamp."""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import httpx
import pytest
import yaml
from sqlalchemy import text

from cmapi.core.clients.kube import ClusterUnreachable
from cmapi.core.db import older_than_required
from cmapi.core.db.repo import JobRepo
from cmapi.core.errors import Problem
from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.core.ports import AppStatus
from cmapi.core.sync import not_synced
from cmapi.worker import MAX_ATTEMPTS, Worker
from test_flow import NS, OLA, auth
from test_review_d_delivery import run_until, status
from test_review_e_recovery import lease_expired
from test_second_pass import _awaiting, _stubs

ROOT = pathlib.Path(__file__).resolve().parents[3]
CHART, CRC = ROOT / "deploy/helm/cmapi", ROOT / "deploy/environments/crc.yaml"
DIG = "sha256:" + "a" * 64
REALM_KEYS = ("CMAPI_REALM_ADMIN_SECRET", "CMAPI_DIRECTORY_SECRET", "CMAPI_SVC_PAYMENTS_CI_SECRET", "CMAPI_AUTOMATION_SECRET")


def _run(ctx, n):
    w = Worker(ctx, "w")
    for _ in range(n):
        lease_expired(ctx); w.run_one()


def _job(ctx):
    with ctx.db.session() as s:
        return s.execute(text("select done_at is null, attempts, payload->>'unreachable_since' from jobs where kind='prune'")).one()


# ------------------------------------------------------------------ the prune: time-bounded inability to read
def test_reader_that_never_connects_is_bounded(world):
    """Codex 5 under the ruling: a reader that never connects ends in sync_failed when the clock runs out, not after
    MAX_ATTEMPTS. With the clock run out at once (syncTimeout 0) the first poll decides; the attempts stay unspent."""
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    ctx.delivery = type(ctx.delivery)(mode="argocd", poll_seconds=0, sync_timeout_seconds=0)
    ctx.registry.cache = lambda cid: (_ for _ in ()).throw(Problem(503, "cluster-not-connected", f"{cid} is connecting"))
    _run(ctx, 1)
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed", v["status"]
    assert "could not be read for 0 s" in v["events"][-1]["note"] and "connecting" in v["events"][-1]["note"], v["events"][-1]["note"]
    assert _job(ctx)[:2] == (False, 1), "ended by the clock, on the first claim, not by the attempts"


def test_an_unreachable_cluster_past_the_sync_timeout_is_sync_failed_with_attempts_unspent(world):
    """The same bound for an unreachable cluster: the outcome is the clock, never the number of polls or the relist."""
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    ctx.delivery = type(ctx.delivery)(mode="argocd", poll_seconds=0, sync_timeout_seconds=0)
    kube.get_object = lambda *a, **k: (_ for _ in ()).throw(ClusterUnreachable("the API server is down"))
    _run(ctx, 1)
    v = status(client, keys, rid)
    assert v["status"] == "sync_failed" and "ClusterUnreachable" in v["events"][-1]["note"], v["events"][-1]["note"]
    assert _job(ctx)[:2] == (False, 1), "ended by the clock, on the first claim, not by the attempts"


def test_a_reader_not_connected_within_the_bound_waits_with_one_clock_and_one_event(world):
    """Opus F5's shape for the other wait: within syncTimeout the request waits, the reason lands once, the clock is in
    the job, and a success clears it so a later outage starts its own."""
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    ctx.delivery = type(ctx.delivery)(mode="argocd", poll_seconds=0, sync_timeout_seconds=600)
    real = ctx.registry.cache
    ctx.registry.cache = lambda cid: (_ for _ in ()).throw(Problem(503, "cluster-not-connected", f"{cid} is connecting"))
    _run(ctx, MAX_ATTEMPTS + 3)
    v = status(client, keys, rid)
    assert v["status"] == "awaiting_prune", (v["status"], v["events"][-1])
    assert sum(e["event"] == "prune_waiting" for e in v["events"]) == 1
    pending, attempts, since = _job(ctx)
    assert (pending, attempts) == (True, 0) and since is not None
    ctx.registry.cache = real
    _run(ctx, 1)
    assert _job(ctx)[2] is None, "a successful read must clear the clock"
    kube.delete("Namespace", None, "payments-dev")
    _run(ctx, 1)
    assert status(client, keys, rid)["status"] == "synced"


def test_a_retry_after_the_bound_starts_a_new_clock(world):
    client, ctx, git, kube, validator, keys = world
    rid = _awaiting(ctx, client, keys)
    ctx.delivery = type(ctx.delivery)(mode="argocd", poll_seconds=0, sync_timeout_seconds=0)
    real = kube.get_object
    kube.get_object = lambda *a, **k: (_ for _ in ()).throw(ClusterUnreachable("down"))
    _run(ctx, 1)
    assert status(client, keys, rid)["status"] == "sync_failed"
    from test_flow import OPAL
    assert client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **OPAL)).status_code == 200
    with ctx.db.session() as s:
        assert s.execute(text("select payload->>'unreachable_since' from jobs where kind='prune' and done_at is null")).scalar() is None
    kube.get_object = real
    kube.delete("Namespace", None, "payments-dev")
    _run(ctx, 1)
    assert status(client, keys, rid)["status"] == "synced"


# ------------------------------------------------------------------ Codex 2: the fence before external side effects
def test_stale_pr_checks_posts_no_status(world):
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    assert run_until(ctx, "pr_checks") == "pr_checks"
    real_validate = validator.validate
    posted = []
    real_set_check = git.set_check
    git.set_check = lambda *a, **k: (posted.append(a), real_set_check(*a, **k))[1]

    def lose_lease(*args, **kwargs):
        lease_expired(ctx)
        with ctx.db.session() as session:
            assert JobRepo(session).claim("w2") is not None
        return real_validate(*args, **kwargs)

    validator.validate = lose_lease
    Worker(ctx, "w1").run_one()
    assert posted == [], "a stale worker overwrote commit statuses"


def test_stale_channel_notify_sends_no_message(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "tier": "large"}, headers=auth(keys, "ola", **OLA))
    assert run_until(ctx, "channel_notify") == "channel_notify"
    import importlib
    module = importlib.import_module("cmapi.jobs.channel_notify")     # the package attribute of that name is the function
    real_view = module.request_view
    sent = []

    class Channel:
        name = "test"

        def notify_pending(self, view, groups):
            sent.append((view["requestId"], groups))
            return {"recipients": ["test"]}

    def lose_lease(*args, **kwargs):
        lease_expired(ctx)
        with ctx.db.session() as session:
            assert JobRepo(session).claim("w2") is not None
        return real_view(*args, **kwargs)

    monkeypatch.setattr(module, "request_view", lose_lease)
    monkeypatch.setattr(module, "channels_for", lambda ctx: [Channel()])
    Worker(ctx, "w1").run_one()
    assert sent == [], "a stale worker sent an approval notification"


# ------------------------------------------------------------------ Codex 1 and 6: the adapters and the gap tests
@pytest.mark.parametrize("provider", [GiteaProvider, GitHubProvider])
def test_contains_treats_an_unknown_other_source_revision_as_not_contained(provider):
    git = provider("https://git.test/api/v1", "owner/repo", "token")
    git._client = httpx.Client(base_url="https://git.test/api/v1", transport=httpx.MockTransport(lambda r: httpx.Response(404, json={"message": "not found"})))
    assert git.contains("f" * 40, "a" * 40) is False


@pytest.mark.parametrize("provider", [GiteaProvider, GitHubProvider])
def test_contains_keeps_a_git_5xx_retryable(provider):
    git = provider("https://git.test/api/v1", "owner/repo", "token")
    git._client = httpx.Client(base_url="https://git.test/api/v1", transport=httpx.MockTransport(lambda r: httpx.Response(503, text="unavailable")))
    with pytest.raises(GitUnavailable):
        git.contains("f" * 40, "a" * 40)


def test_not_synced_rejects_a_planned_object_missing_from_application_status():
    app = AppStatus(cluster_id="CRC", revision="a" * 40, sync="Synced", health="Healthy", phase="Succeeded", resources=())
    files = {"clusters/CRC/namespaces/payments-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: payments-dev\n"}
    assert not_synced(app, files) == ["Namespace/payments-dev: not in the Application"]


def test_unknown_revision_with_the_required_numeric_prefix_is_not_future():
    with pytest.raises(ValueError, match="unknown schema revision"):
        older_than_required("0003_from_later_release")


# ------------------------------------------------------------------ Codex 4: the realm Secret fails closed
def _chart_copy(tmp_path, imp_obj: str, realm_obj: str):
    """The chart with its two lookups replaced by literals: helm template has no cluster to look anything up in."""
    chart = tmp_path / "chart"
    shutil.copytree(CHART, chart)
    f = chart / "templates/secrets.yaml"
    t = f.read_text()
    old_imp = '{{- $impObj := lookup "v1" "Secret" $r.namespace "cmapi-realm-secrets" | default dict -}}'
    old_realm = '{{- $realmObj := lookup $r.apiVersion "KeycloakRealmImport" $r.namespace $r.realm | default dict -}}'
    assert t.count(old_imp) == 1 and t.count(old_realm) == 1
    f.write_text(t.replace(old_imp, f"{{{{- $impObj := {imp_obj} -}}}}").replace(old_realm, f"{{{{- $realmObj := {realm_obj} -}}}}"))
    return chart


def _render(chart, *sets):
    a = [x for s in sets for x in ("--set", s)]
    return subprocess.run(["helm", "template", "cmapi", str(chart), "-n", "cmapi", "-f", str(CRC), "--set", f"cmapi.digest={DIG}", "--set", f"cmapi_portal.digest={DIG}", "--set", "trustedCA.certificates=x", *a],
                          capture_output=True, text=True)


def _full_secret(*keys):
    return "dict \"data\" (dict " + " ".join(f'"{k}" ("{k.lower()}" | b64enc)' for k in keys) + ")"


def test_a_realm_without_its_secret_refuses_to_mint(tmp_path):
    r = _render(_chart_copy(tmp_path, "dict", 'dict "kind" "KeycloakRealmImport"'))
    assert r.returncode != 0 and "refusing to mint" in r.stderr, r.stderr[-300:]


def test_a_partial_realm_secret_refuses_to_rotate(tmp_path):
    r = _render(_chart_copy(tmp_path, _full_secret("CMAPI_REALM_ADMIN_SECRET"), 'dict "kind" "KeycloakRealmImport"'))
    assert r.returncode != 0 and "missing CMAPI_DIRECTORY_SECRET" in r.stderr, r.stderr[-300:]


def test_a_first_install_and_a_kept_copy_both_render(tmp_path):
    """Nothing to look up: a first install mints. Realm and Secret both there: F12's fallback reuses every value."""
    assert _render(_chart_copy(tmp_path / "first", "dict", "dict")).returncode == 0
    r = _render(_chart_copy(tmp_path / "kept", _full_secret(*REALM_KEYS), 'dict "kind" "KeycloakRealmImport"'))
    assert r.returncode == 0, r.stderr[-300:]
    sec = next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == "Secret" and d["metadata"]["name"] == "cmapi-keycloak")
    import base64
    assert base64.b64decode(sec["data"]["directoryClientSecret"]).decode() == "cmapi_directory_secret"


def test_the_realm_lookup_uses_the_version_the_realm_cr_uses():
    """One value for both, keycloak.realmImport.apiVersion, which CRC serves (v2beta1, measured by the coordinator).
    A lookup with another version finds nothing and the fail-closed check never fires."""
    secrets = (CHART / "templates/secrets.yaml").read_text()
    realm = (CHART / "templates/keycloak-realm.yaml").read_text()
    assert 'lookup $r.apiVersion "KeycloakRealmImport" $r.namespace $r.realm' in secrets
    assert "$r := .Values.keycloak.realmImport" in secrets and "apiVersion: {{ $r.apiVersion }}" in realm
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    assert values["keycloak"]["realmImport"]["apiVersion"] == "k8s.keycloak.org/v2beta1"
    r = subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", "-f", str(CRC), "--set", f"cmapi.digest={DIG}", "--set", f"cmapi_portal.digest={DIG}", "--set", "trustedCA.certificates=x"], capture_output=True, text=True)
    cr = next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == "KeycloakRealmImport")
    assert cr["apiVersion"] == values["keycloak"]["realmImport"]["apiVersion"]


# ------------------------------------------------------------------ Opus F3 under the ruling: empty must be acknowledged
def test_an_empty_controller_identity_in_argocd_mode_fails_unless_acknowledged():
    r = _render(CHART, "argocd.controllerServiceAccount=")
    assert r.returncode != 0 and "acknowledgeUncontainedController" in r.stderr, r.stderr[-300:]
    r = _render(CHART, "argocd.controllerServiceAccount=", "argocd.acknowledgeUncontainedController=true")
    assert r.returncode == 0, r.stderr[-300:]
    assert not [d for d in yaml.safe_load_all(r.stdout) if d and d["kind"].startswith("ValidatingAdmissionPolicy")]


def test_crc_names_the_controller_and_binds_the_policy_to_it():
    values = yaml.safe_load(CRC.read_text())
    assert values["argocd"]["controllerServiceAccount"] == "system:serviceaccount:cmapi-argocd:argocd-application-controller"
    r = _render(CHART)
    assert r.returncode == 0, r.stderr[-300:]
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    vap = [d for d in docs if d["kind"] == "ValidatingAdmissionPolicy"]
    assert vap and values["argocd"]["controllerServiceAccount"] in vap[0]["spec"]["matchConditions"][0]["expression"]
    assert not [d for d in docs if d["kind"] in ("ClusterRole", "ClusterRoleBinding")], "no write identity for cmapi itself"


# ------------------------------------------------------------------ Codex 3 under the ruling: a reused tag is verified by its stamp
def _release_repo(tmp_path):
    repo = tmp_path / "repo"; (repo / "cmapi").mkdir(parents=True)
    shutil.copytree(ROOT / "deploy", repo / "deploy"); shutil.copy(ROOT / "cmapi/pyproject.toml", repo / "cmapi/pyproject.toml")
    env, state = _stubs(tmp_path)
    for cmd in (["git", "init", "-q"], ["git", "add", "."], ["git", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, env=env, check=True)
    return repo, env, state


def test_a_reused_clean_tag_must_carry_this_commits_stamp(tmp_path):
    """Measured: the build is not reproducible byte for byte (podman build --no-cache of one commit gives another image
    id), so a digest comparison would fail every rerun. The registry's image is pulled by digest and its stamp read."""
    repo, env, state = _release_repo(tmp_path)
    r = subprocess.run(["bash", "deploy/release-crc.sh", "--no-portal"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    (state / "registry-commit").write_text("0000000000")           # the registry's image under this tag stamps another commit
    r = subprocess.run(["bash", "deploy/release-crc.sh", "--no-portal"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "not pushed again" not in r.stdout, r.stdout
    assert "stamps" in r.stderr and "0000000000" in r.stderr, r.stderr[-300:]
    assert "helm upgrade --install" not in (tmp_path / "log").read_text().splitlines()[-1]
    (state / "registry-commit").unlink()
    r = subprocess.run(["bash", "deploy/release-crc.sh", "--no-portal"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "verified" in r.stdout, (r.stdout, r.stderr[-300:])
    assert len(list(state.glob("pushed.*"))) == 1


# ------------------------------------------------------------------ #86: a documented script must be runnable by its path
def test_every_shell_script_under_examples_and_deploy_is_executable():
    """Measured 2026-11-05: apply-bind-user.sh was tracked as 100644, so its documented command failed with rc 126."""
    out = subprocess.run(["git", "ls-files", "-s", "examples", "deploy"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    wrong = []
    for line in out.splitlines():
        mode, _blob, _stage, path = line.split(None, 3)
        f = ROOT / path
        if f.suffix == ".sh" or (f.is_file() and f.read_bytes()[:2] == b"#!" and b"sh" in f.read_bytes().split(b"\n", 1)[0]):
            if mode != "100755":
                wrong.append(f"{path} is {mode}")
    assert not wrong, wrong
