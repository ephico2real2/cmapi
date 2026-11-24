"""Fixtures for the service tests: a real PostgreSQL (CMAPI_TEST_DATABASE_URL, default the throwaway
postgres:16-alpine container on port 55432 named in CRC-BUILD-STATUS.md "Resume"; CI runs the same image
as a service), and fakes for the Git host, the cluster and the validator, so the pipeline, the routers
and the worker jobs run end to end without a cluster.

The fakes implement the same contracts as the adapters (HostGitProvider, KubeClient) and keep
their state in memory; the tests below drive every lifecycle path through them.
"""
from __future__ import annotations

import os
import re
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

# One session per database (#271). fresh_db truncates the request tables before each test, so a second session on the same
# database deletes this one's rows mid-test, and a test fails with a 404 that is not the code's. A session-level advisory
# lock, held on its own connection until the session ends, turns that into an immediate refusal that names the cause.
SESSION_LOCK_KEY = 0x636D617069  # "cmapi" in ASCII
SESSION_LOCK_EXIT = 75  # EX_TEMPFAIL of sysexits.h, "try again later": pytest's own codes are 0 to 5, and 3 is its internal error
_SESSION_LOCK = pytest.StashKey[Any]()
_SESSION_LOCK_TRIED = pytest.StashKey[bool]()


def _hold_the_database(session: pytest.Session) -> None:
    import psycopg

    if session.config.stash.get(_SESSION_LOCK_TRIED, False):
        return
    session.config.stash[_SESSION_LOCK_TRIED] = True
    # SQLAlchemy's form (postgresql+psycopg://) works for the app's engine; libpq wants the plain scheme.
    conninfo = re.sub(r"^postgres(?:ql)?\+\w+://", "postgresql://", DB_URL)
    try:
        conn = psycopg.connect(conninfo, autocommit=True, connect_timeout=5)
    except psycopg.Error:
        # No database, or a URL libpq cannot read (its message quotes the URL, password and all, so it is not shown): the
        # tests that need the database fail on their own, as they did before the lock.
        return
    if not conn.execute("select pg_try_advisory_lock(%s)", (SESSION_LOCK_KEY,)).fetchone()[0]:
        where = f"{conn.info.host}:{conn.info.port}/{conn.info.dbname}"  # from the connection: never the URL's credentials
        conn.close()
        pytest.exit(f"another service-test session holds the database {where} (advisory lock {SESSION_LOCK_KEY}): its fixtures "
                    "truncate the request tables, so two sessions would delete each other's rows. Wait for it to end, or set "
                    "CMAPI_TEST_DATABASE_URL to a database of your own.", returncode=SESSION_LOCK_EXIT)
    session.config.stash[_SESSION_LOCK] = conn


def pytest_sessionstart(session: pytest.Session) -> None:
    _hold_the_database(session)  # before collection, when this file is an initial conftest (pytest tests/service, ...)


def pytest_collection_finish(session: pytest.Session) -> None:
    # pytest calls pytest_sessionstart only for initial conftests. `pytest tests` from cmapi/ loads this file while collecting,
    # after the session started, so the lock is taken here instead: still before any fixture or test runs.
    _hold_the_database(session)


def pytest_sessionfinish(session: pytest.Session) -> None:
    conn = session.config.stash.get(_SESSION_LOCK, None)
    if conn is not None:
        conn.close()  # the advisory lock is the connection's: closing it releases the lock


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
              exp_in=300, client="cmapi-portal", extra: Mapping[str, Any] | None = None, kid=None, alg="RS256",
              typ: str | None = "at+jwt") -> str:
        """`typ` is the JOSE header: an access token of cmapi's realm has at+jwt (RFC 9068). None removes the header type."""
        now = int(time.time())
        claims = {"iss": iss, "aud": [aud, "account"], "sub": sub or f"sub-{username}", "azp": client, "iat": now,
                  "exp": now + exp_in, "preferred_username": username, "email": f"{username}@ephico2real.com",
                  "given_name": username.title(), "family_name": "Doe", "groups": list(groups),
                  "resource_access": {aud: {"roles": list(roles)}}}
        if employee_id:
            claims["employee_id"] = employee_id
        claims.update(extra or {})
        headers = {"kid": kid or self.kid, "typ": typ}      # PyJWT deletes a header typ that is None, and writes JWT when the key is absent
        if alg == "none":
            return jwt.encode(claims, key=None, algorithm="none", headers=headers)
        return jwt.encode(claims, self.pem, algorithm=alg, headers=headers)


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
        self.owners: dict[str, tuple[str, str]] = {}
        self.based_on_sha: dict[str, str] = {}
        self.pushes: list[str] = []
        self.submodules: set[str] = set()          # paths whose entry is a submodule (a gitlink), for list_folder

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

    def _branch_of(self, ref):
        self._check()
        ref = ref or "main"
        # Only a branch that still exists: a merged branch is deleted and its head stays in self.heads, and a later head with
        # the same content has the same hash here (#154).
        branch = ref if ref in self.branches else next((b for b, h in self.heads.items() if h == ref and b in self.branches), None)
        if branch is None:
            from cmapi.core.git.base import GitUnavailable
            raise GitUnavailable(f"no branch {ref}")
        return branch

    def read_folder(self, path, ref=None):
        branch = self._branch_of(ref)
        # The .yaml files directly in the folder, as github.py, gitea.py and workspace.py list one folder, not its subfolders (#578).
        prefix = path.rstrip("/") + "/"
        files = {p: t for p, t in self.branches[branch].items()
                 if p.startswith(prefix) and "/" not in p[len(prefix):] and p.endswith(".yaml")}
        return files, self.heads[branch]

    def list_folder(self, path, ref=None):
        """Every path under the folder, at any depth, as the real listings give it (#616). A path in submodules is one."""
        branch = self._branch_of(ref)
        prefix = path.rstrip("/") + "/"
        return ({p: ("commit" if p in self.submodules else "blob") for p in self.branches[branch] if p.startswith(prefix)},
                self.heads[branch])

    def contains(self, revision, sha):
        self._check()
        history = self.main_history
        return revision == sha or (revision in history and sha in history and history.index(sha) <= history.index(revision))

    def changed_paths(self, head):
        self._check()
        branch = next(b for b, h in self.heads.items() if h == head and b in self.branches)      # as in read_folder (#154)
        before, after = self.based_on.get(branch, self.branches[branch]), self.branches[branch]
        return {p for p in set(before) | set(after) if before.get(p) != after.get(p)}

    def find_pr(self, branch):
        for n, p in self.prs.items():
            if p["branch"] == branch and p["state"] == "open":
                return PrRef(n, p["url"], branch, self.heads[branch])
        return None

    def push_request_branch(self, req):
        """The Git layer's contract (#286), in memory: the branch from main with the plan's files. A branch that exists is
        adopted when it is this request's with these files, replaced when it is this request's stale attempt, refused otherwise."""
        from cmapi.core.git.base import PushResult
        from cmapi.core.git.workspace import BranchRefused, request_branch

        self._check()
        branch = request_branch(req.cluster_id, req.request_id)
        base = self.heads["main"]
        want = dict(self.branches["main"])
        for p, t in req.files.items():
            if t is None:
                want.pop(p, None)
            else:
                want[p] = t
        if branch in self.branches:
            owner = self.owners.get(branch)
            if owner == (req.request_id, req.plan_hash) and self.branches[branch] == want:
                return PushResult(self.heads[branch], self.based_on_sha.get(branch, base), "adopted")
            if not owner or owner[0] != req.request_id:
                raise BranchRefused(f"branch {branch} exists and its head is not cmapi's commit for {req.request_id}")
        self.branches[branch] = want
        self.based_on[branch] = dict(self.branches["main"])
        self.based_on_sha[branch] = base
        self.owners[branch] = (req.request_id, req.plan_hash)
        self.pushes.append(branch)
        return PushResult(self._sha(branch), base, "created")

    def open_pr(self, branch, head, title, body):
        self._check()
        if (pr := self.find_pr(branch)) is not None:
            return pr
        assert branch in self.branches and self.heads[branch] == head, "PR opened on a head that is not the pushed one"
        n = len(self.prs) + 1
        self.prs[n] = {"branch": branch, "state": "open", "title": title, "body": body, "url": f"https://git.test/pulls/{n}",
                       "merge_sha": None}
        return PrRef(n, self.prs[n]["url"], branch, head)

    def comment(self, pr, text):
        self.prs[pr.number].setdefault("comments", []).append(text)

    def delete_branch(self, branch, expected):
        if branch not in self.branches:
            return True
        if self.heads.get(branch) != expected:
            return False
        del self.branches[branch]
        return True

    def list_open(self, prefix):
        return [PrRef(n, p["url"], p["branch"], self.heads.get(p["branch"], "")) for n, p in self.prs.items()
                if p["state"] == "open" and p["branch"].startswith(prefix)]

    def list_branches(self, prefix):
        return {b: self.heads[b] for b in self.branches if b.startswith(prefix)}

    def branch_time(self, sha):
        return 0

    def request_of(self, sha):
        branch = next((b for b, h in self.heads.items() if h == sha and b in self.branches), None)
        return (self.owners.get(branch) or (None,))[0]

    def pr_status(self, pr):
        self._check()
        p = self.prs[pr.number]
        head = self.heads[pr.branch] if pr.branch in self.heads else pr.head_sha
        checks = {k: ("success" if v == "success" else "pending" if v == "pending" else "failure")
                  for k, v in self.statuses.get(head, {}).items()}
        return PrStatus(state=p["state"], checks=checks, merge_sha=p["merge_sha"], head_sha=head)

    def set_check(self, sha, context, state, description, target_url=None):
        self._check()
        self.statuses.setdefault(sha, {})[context] = state

    def merge(self, pr, expected_head):
        self._check()
        p = self.prs[pr.number]
        assert self.heads[pr.branch] == expected_head, "head moved"
        required = self.statuses.get(expected_head, {})
        assert all(required.get(c) == "success" for c in ("ci/kubeconform", "ci/kyverno", "cmapi/check")), "protection refused the merge"
        base = self.based_on.get(pr.branch)
        if base is None:
            self.branches["main"] = dict(self.branches[pr.branch])
        else:
            # A merge, as a host makes it: main keeps what it gained since the branch left it, and takes the branch's own
            # changes. Copying the branch over main would drop a path added to main before the merge (#616).
            merged, branch = dict(self.branches["main"]), self.branches[pr.branch]
            for path in set(base) | set(branch):
                if base.get(path) != branch.get(path):
                    if path in branch:
                        merged[path] = branch[path]
                    else:
                        merged.pop(path, None)
            self.branches["main"] = merged
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
    """One cluster in memory: namespaces, quotas and limit ranges, applied by the deliverer.

    #302: `served_groups` is what API discovery serves (empty: Kyverno is not installed, as on CRC), `forbidden_kinds` the
    kinds whose list answers 403, and `calls` each discovery and list call by kind, so a test can show that no call was made.
    A list with `limit` pages by `continue`, as the API server does."""

    def __init__(self, cluster_id="CRC", identity="system:serviceaccount:cmapi-system:cmapi-reader"):
        self.cluster_id, self.identity = cluster_id, identity
        self.objects: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.rv = 1
        self.applied: list[str] = []
        self.unreachable = False
        self.served_groups: set[str] = set()
        self.forbidden_kinds: set[str] = set()
        self.calls: list[str] = []

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

    def served(self, group_version):
        self.calls.append(f"discovery {group_version}")
        if self.unreachable:
            from cmapi.core.clients.kube import ClusterUnreachable
            raise ClusterUnreachable("fake cluster down")
        return group_version in self.served_groups

    def list(self, kind, namespace=None, label_selector=None, resource_version=None, *, limit=None, continue_=None):
        self.calls.append(kind)
        if kind in self.forbidden_kinds:
            raise KubeError(403, f"list {kind}", "forbidden")
        items = [o for (k, ns, _), o in self.objects.items() if k == kind and (namespace is None or ns == namespace)]
        if limit is None:
            return {"items": items, "metadata": {"resourceVersion": str(self.rv)}}
        items.sort(key=lambda o: (o["metadata"].get("namespace", ""), o["metadata"]["name"]))
        start = int(continue_ or 0)
        more = start + limit < len(items)
        return {"items": items[start:start + limit],
                "metadata": {"resourceVersion": str(self.rv), **({"continue": str(start + limit)} if more else {})}}

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
        self.previous: list = []        # the previous folder that each call gave (#212: a held value is not refused)

    def validate(self, files, cluster_id, environment, previous=None):
        self.calls += 1
        self.previous.append(previous)
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
                       "approval_notifications, expiration_notices, policy_rejections RESTART IDENTITY CASCADE"))
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
    ctx.registry.clusters["CRC"].nodes.wait_ready(5)      # #302: the node watch's first list, so no test races it
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
