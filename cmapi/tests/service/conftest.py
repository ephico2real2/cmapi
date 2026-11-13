"""Fixtures for the service tests: a real PostgreSQL (CMAPI_TEST_DATABASE_URL, default the throwaway
postgres:16-alpine container on port 55432 named in CRC-BUILD-STATUS.md "Resume"; CI runs the same image
as a service), and fakes for the Git host, the cluster and the validator, so the pipeline, the routers
and the worker jobs run end to end without a cluster.

The fakes implement the same contracts as the adapters (HostGitProvider, KubeClient) and keep
their state in memory; the tests below drive every lifecycle path through them.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT.parent / "examples"
sys.path.insert(0, str(ROOT / "src"))

from cmapi.core.auth import Authenticator, Jwks                      # noqa: E402
from cmapi.core.clients.kube import KubeClient, KubeError            # noqa: E402
from cmapi.core.context import build_context                        # noqa: E402
from cmapi.core.db import Database                                  # noqa: E402
from cmapi.core.db.migrate import run as migrate                    # noqa: E402
from cmapi.core.git.base import HostGitProvider                     # noqa: E402
from cmapi.core.ports import Finding, PrRef, PrStatus               # noqa: E402
from cmapi.core.registry import ImportSource                        # noqa: E402
from cmapi.main import create_app                                   # noqa: E402
from cmapi.settings import Settings                                 # noqa: E402

DB_URL = os.environ.get("CMAPI_TEST_DATABASE_URL", "postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi")
ISSUER = "https://keycloak.test/realms/cmapi"
AUDIENCE = "cmapi-nonprod"


# --------------------------------------------------------------------------- tokens

class Keys:
    def __init__(self):
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "test-kid-1"
        pub = self.private.public_key()
        self.jwk = {**jwt.algorithms.RSAAlgorithm.to_jwk(pub, as_dict=True), "kid": self.kid, "use": "sig", "alg": "RS256"}
        self.pem = self.private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption())

    def token(self, username: str, *, roles=(), groups=(), employee_id="1001", sub=None, aud=AUDIENCE, iss=ISSUER,
              exp_in=300, client="cmapi-portal", extra: Mapping[str, Any] | None = None, kid=None, alg="RS256") -> str:
        now = int(time.time())
        claims = {"iss": iss, "aud": [aud, "account"], "sub": sub or f"sub-{username}", "azp": client, "iat": now,
                  "exp": now + exp_in, "preferred_username": username, "email": f"{username}@ephico2real.com",
                  "given_name": username.title(), "family_name": "Doe", "groups": list(groups),
                  "resource_access": {aud: {"roles": list(roles)}}}
        if employee_id:
            claims["employee_id"] = employee_id
        claims.update(extra or {})
        if alg == "none":
            return jwt.encode(claims, key=None, algorithm="none", headers={"kid": kid or self.kid})
        return jwt.encode(claims, self.pem, algorithm=alg, headers={"kid": kid or self.kid})


@pytest.fixture(scope="session")
def keys() -> Keys:
    return Keys()


# --------------------------------------------------------------------------- fakes

class FakeGit(HostGitProvider):
    """An in-memory Git host: branches are dicts of files; a PR is a record with statuses."""

    def __init__(self):
        self.branches: dict[str, dict[str, str]] = {"main": {"README.md": "cluster-configs (test)\n"}}
        self.heads: dict[str, str] = {"main": "a" * 40}
        self.main_history: list[str] = ["a" * 40]
        self.prs: dict[int, dict[str, Any]] = {}
        self.statuses: dict[str, dict[str, str]] = {}
        self.commits: list[str] = ["aaaaaaaa initial"]
        self.based_on: dict[str, dict[str, str]] = {}
        self.repository = "cmapi/cluster-configs-test"
        self.default_branch = "main"
        self.web_url = "https://git.test"
        self.down = False

    def _check(self):
        if self.down:
            from cmapi.core.git.base import GitUnavailable
            raise GitUnavailable("fake git is down")

    def _sha(self, branch: str) -> str:
        import hashlib
        h = hashlib.sha1(("".join(sorted(f"{k}={v}" for k, v in self.branches[branch].items()))).encode()).hexdigest()
        self.heads[branch] = h
        if branch == "main":
            self.main_history.append(h)
        return h

    def branch_head(self, branch):
        self._check()
        return self.heads.get(branch) if branch in self.branches else None

    def read_folder(self, path, ref=None):
        self._check()
        ref = ref or "main"
        branch = ref if ref in self.branches else next((b for b, h in self.heads.items() if h == ref), None)
        if branch is None:
            from cmapi.core.git.base import GitUnavailable
            raise GitUnavailable(f"no branch {ref}")
        files = {p: t for p, t in self.branches[branch].items() if p.startswith(path) and p.endswith(".yaml")}
        return files, self.heads[branch]

    def contains(self, revision, sha):
        self._check()
        history = self.main_history
        return revision == sha or (revision in history and sha in history and history.index(sha) <= history.index(revision))

    def changed_paths(self, head):
        self._check()
        branch = next(b for b, h in self.heads.items() if h == head)
        before, after = self.based_on.get(branch, self.branches[branch]), self.branches[branch]
        return {p for p in set(before) | set(after) if before.get(p) != after.get(p)}

    def find_pr(self, branch):
        for n, p in self.prs.items():
            if p["branch"] == branch and p["state"] == "open":
                return PrRef(n, p["url"], branch, self.heads[branch])
        return None

    def open_pr(self, branch, files, title, body, base_sha):
        self._check()
        if (pr := self.find_pr(branch)) is not None:
            return pr
        assert base_sha == self.heads["main"], "PR opened against a stale base"
        self.branches[branch] = dict(self.branches["main"])
        self.based_on[branch] = dict(self.branches["main"])
        for p, t in files.items():
            if t is None:
                self.branches[branch].pop(p, None)
            else:
                self.branches[branch][p] = t
        head = self._sha(branch)
        n = len(self.prs) + 1
        self.prs[n] = {"branch": branch, "state": "open", "title": title, "body": body, "url": f"https://git.test/pulls/{n}",
                       "merge_sha": None}
        return PrRef(n, self.prs[n]["url"], branch, head)

    def pr_status(self, pr):
        self._check()
        p = self.prs[pr.number]
        head = self.heads[pr.branch] if pr.branch in self.heads else pr.head_sha
        checks = {k: ("success" if v == "success" else "pending" if v == "pending" else "failure")
                  for k, v in self.statuses.get(head, {}).items()}
        return PrStatus(state=p["state"], checks=checks, merge_sha=p["merge_sha"])

    def set_check(self, sha, context, state, description, target_url=None):
        self._check()
        self.statuses.setdefault(sha, {})[context] = state

    def merge(self, pr, expected_head):
        self._check()
        p = self.prs[pr.number]
        assert self.heads[pr.branch] == expected_head, "head moved"
        required = self.statuses.get(expected_head, {})
        assert all(required.get(c) == "success" for c in ("ci/kubeconform", "ci/kyverno", "cmapi/check")), "protection refused the merge"
        self.branches["main"] = dict(self.branches[pr.branch])
        merge_sha = self._sha("main")
        p["state"], p["merge_sha"] = "merged", merge_sha
        self.commits.append(f"{merge_sha[:8]} Merge {pr.branch}")
        del self.branches[pr.branch]
        return merge_sha

    def close(self, pr, comment):
        self.prs[pr.number]["state"] = "closed"
        self.prs[pr.number]["comment"] = comment

    def log(self, n=20):
        return list(reversed(self.commits))[:n]

    # test helper: a hand edit on the bot branch after approval
    def tamper(self, branch: str, path: str, text: str) -> None:
        self.branches[branch][path] = text
        self._sha(branch)


class FakeKube(KubeClient):
    """One cluster in memory: namespaces, quotas and limit ranges, applied by the deliverer."""

    def __init__(self, cluster_id="CRC", identity="system:serviceaccount:cmapi-system:cmapi-reader"):
        self.cluster_id, self.identity = cluster_id, identity
        self.objects: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.rv = 1
        self.applied: list[str] = []
        self.unreachable = False

    def close(self):
        pass

    def _k(self, kind, ns, name):
        return (kind, ns or "", name)

    def version(self):
        if self.unreachable:
            from cmapi.core.clients.kube import ClusterUnreachable
            raise ClusterUnreachable("fake cluster down")
        return "v1.35.6-fake"

    def whoami(self):
        return self.identity

    def list(self, kind, namespace=None, label_selector=None, resource_version=None):
        items = [o for (k, ns, _), o in self.objects.items() if k == kind and (namespace is None or ns == namespace)]
        return {"items": items, "metadata": {"resourceVersion": str(self.rv)}}

    def get_object(self, kind, namespace, name):
        return self.objects.get(self._k(kind, namespace, name))

    def watch(self, kind, resource_version, timeout_seconds=300):
        time.sleep(0.05)
        return iter(())

    def apply(self, doc, field_manager="cmapi-deliverer"):
        kind, meta = doc["kind"], doc["metadata"]
        key = self._k(kind, meta.get("namespace"), meta["name"])
        obj = dict(doc)
        if kind == "ResourceQuota":
            obj = {**doc, "status": {"hard": dict(doc["spec"]["hard"]), "used": {k: "0" for k in doc["spec"]["hard"]}}}
        if kind == "Namespace":
            obj = {**doc, "status": {"phase": "Active"}}
            obj["metadata"] = {**doc["metadata"], "creationTimestamp": datetime.now(timezone.utc).isoformat()}
        self.objects[key] = obj
        self.rv += 1
        self.applied.append(f"{kind}/{meta.get('namespace', '')}/{meta['name']}")
        return obj

    def delete(self, kind, namespace, name):
        self.objects.pop(self._k(kind, namespace, name), None)
        if kind == "Namespace":
            for key in [k for k in self.objects if k[1] == name]:
                del self.objects[key]
        self.rv += 1

    def add_unmanaged_namespace(self, name: str):
        self.objects[self._k("Namespace", None, name)] = {"kind": "Namespace", "metadata": {"name": name, "labels": {}}}


class FakeValidator:
    def __init__(self):
        self.findings: list[Finding] = []
        self.calls = 0

    def validate(self, files, cluster_id, environment):
        self.calls += 1
        return list(self.findings)


class OneSecret(ImportSource):
    def __init__(self, cluster_id="CRC"):
        self.cluster_id = cluster_id

    def list(self):
        return [{"name": "cmapi-cluster-crc", "labels": {"cmapi.net/secret-type": "cluster", "cmapi.net/cluster-id": self.cluster_id},
                 "annotations": {}, "data": {"apiUrl": "https://fake.cluster:6443", "token": "fake-token-1234567890"}}]


# --------------------------------------------------------------------------- the app

@pytest.fixture(scope="session")
def test_config(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("config")
    for name in ("instance.yaml", "approval-rules.yaml", "authz-roles.yaml", "tiers.yaml", "expiration.yaml"):
        (d / name).write_text((EXAMPLES / "instances" / "nonprod" / name).read_text())
    (d / "metadata-keys.yaml").write_text((EXAMPLES / "cluster-configs" / "policies" / "metadata-keys.yaml").read_text())
    (d / "instance.yaml").write_text((d / "instance.yaml").read_text()
                                     .replace("https://sso.ephico2real.com/realms/ephico2real", ISSUER)
                                     .replace("repository: caas/cluster-configs-nonprod", "repository: cmapi/cluster-configs-test"))
    (d / "clusters.yaml").write_text("clusters:\n  CRC:\n    environment: dev\n    gitopsPath: clusters/CRC\n"
                                     "    labels: {region: us-central}\n    simulatedCapacity: {cpu: 64, memory: 256Gi}\n")
    (d / "capacity.yaml").write_text("overcommit:\n  dev: {cpu: 2.0, memory: 1.25}\n  rnd: {cpu: 2.0, memory: 1.25}\n"
                                     "targets:\n  dev: {commitment: {warn: 0.85, critical: 0.95}}\n  rnd: {commitment: {warn: 0.85, critical: 0.95}}\n")
    (d / "integrations.yaml").write_text("delivery:\n  mode: apply\n  syncTimeout: 30s\nsyncSignal:\n  default: poll\n  pollInterval: 1s\n")
    return d


@pytest.fixture(scope="session")
def database() -> Database:
    os.environ["CMAPI_DATABASE_URL"] = DB_URL
    from cmapi.settings import settings
    settings.cache_clear()
    migrate(["head"])
    return Database(DB_URL)


@pytest.fixture
def fresh_db(database: Database) -> Database:
    with database.engine.begin() as c:
        c.execute(text("TRUNCATE change_requests, request_events, approvals, jobs, audit_events, admin_switches, "
                       "approval_notifications, expiration_notices RESTART IDENTITY CASCADE"))
    return database


@contextmanager
def build_world(config_dir: Path, keys: Keys, monkeypatch):
    """The app on one configuration folder, with fakes wired in: yields (client, ctx, git, kube, validator, keys)."""
    git, kube, validator = FakeGit(), FakeKube(), FakeValidator()
    monkeypatch.setenv("CMAPI_DATABASE_URL", DB_URL)
    s = Settings(config_dir=config_dir, database_url=DB_URL, git_provider="gitea", git_url="https://git.test/api/v1",
                 git_token="t", cursor_key="k", link_key="l", metrics_port=0, imports_dir=None,
                 kube_token_file=Path("/nonexistent"), kube_ca_file=Path("/nonexistent"))
    import cmapi.core.context as context_mod
    monkeypatch.setattr(context_mod, "make_provider", lambda *a, **k: git)
    monkeypatch.setattr(context_mod, "CliValidator", lambda *a, **k: validator)
    ctx = build_context(s, start_registry=False, import_source=OneSecret())
    ctx.registry.client_factory = lambda *a, **k: kube
    ctx.registry.start_caches = True
    ctx.registry.refresh()
    assert ctx.registry.clusters["CRC"].status == "connected", ctx.registry.clusters["CRC"].findings
    ctx.registry.cache("CRC").wait_ready(5)
    ctx.deliverer_factory = lambda cid: kube
    ctx.auth = Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, "https://keycloak.test/certs", fetch=lambda url: [keys.jwk]))
    app = create_app(s, ctx)
    try:
        with TestClient(app) as client:
            yield client, ctx, git, kube, validator, keys
    finally:
        ctx.registry.stop()


@pytest.fixture
def world(test_config: Path, fresh_db: Database, keys: Keys, monkeypatch):
    """The app with fakes wired in: returns (client, ctx, git, kube, validator, keys)."""
    with build_world(test_config, keys, monkeypatch) as w:
        yield w
