"""#444, #445, #447 (Codex's F1, F2, F4 of the Git delivery review, as OB3 corrected them), on top of #453 (#424).

#453 already routes every host answer through HostGitProvider.host_text (core/clients/redact.py: every form of the token, the
Basic-auth password and its base64, redacted before the cut) and gives oplog.redact the full form set. The controls below pass
on #453 alone and show which parts of F1 and F2 it makes moot. What it leaves, and this patch adds: no raw HTTP cause chained
to a Git error (the worker logs the traceback), redaction at any depth of an event, and a Git workdir private to its UID.
Offline: file:// Git and httpx.MockTransport only."""
from __future__ import annotations

import json
import os
import stat
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from cmapi.core.git.base import BranchRequest, GitUnavailable
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.core.git.oplog import Op, redact, register_secret
from cmapi.core.git.workspace import GitWorkspace
from cmapi.core.ports import PrRef
from gitserver import bare_repo

FOLDER = "clusters/CRC/namespaces/demo/"
TOKEN = "ob3-echo-token-0123456789abcdef"


@pytest.fixture
def secrets(monkeypatch):
    """A registry of its own (#453 keeps the forms in oplog._FORMS), so no test sees another's secrets."""
    import cmapi.core.git.oplog as oplog

    monkeypatch.setattr(oplog, "_FORMS", ())
    return oplog


def github(handler) -> GitHubProvider:
    provider = GitHubProvider("https://offline.invalid", "o/r", TOKEN)
    provider._client.close()
    provider._client = httpx.Client(base_url="https://offline.invalid", transport=httpx.MockTransport(handler))
    return provider


def pr_state(provider) -> GitUnavailable:
    with pytest.raises(GitUnavailable) as caught:
        provider.pr_status(PrRef(1, "", "cmapi/CRC/r1", "a" * 40))
    return caught.value


# ---------------------------------------------------------------- #444 (F1): what #453 makes moot, then what it leaves

@pytest.mark.parametrize("code", [403, 502])
def test_moot_on_453_a_host_error_that_echoes_the_token(code):
    error = pr_state(github(lambda request: httpx.Response(code, json={"message": "echo " + TOKEN})))
    assert TOKEN not in str(error) and TOKEN not in getattr(error, "host_message", "")


def test_moot_on_453_a_token_cut_by_the_message_limit():
    error = pr_state(github(lambda request: httpx.Response(502, text="e" * 190 + TOKEN)))
    assert TOKEN[:10] not in str(error)


def test_moot_on_453_a_basic_auth_password_echoed_json_escaped():
    password = 'pa"ss/w0rd\\long-secret'
    provider = GiteaProvider("https://offline.invalid/api/v1", "o/r", "", basic_auth=("bot", password))
    provider._client.close()
    provider._client = httpx.Client(base_url="https://offline.invalid/api/v1", transport=httpx.MockTransport(
        lambda request: httpx.Response(502, text=json.dumps({"message": "denied for " + password}))))
    with pytest.raises(GitUnavailable) as caught:
        provider.branch_head("main")
    assert json.dumps(password)[1:-1] not in str(caught.value)


def test_a_transport_error_is_not_chained_to_its_raw_text():
    """#453 redacts the message but keeps `from exc`: traceback.format_exc(), which the worker logs on job_failed (worker.py),
    then prints the h11 error with the header value in it."""
    def fail(request):
        raise httpx.LocalProtocolError(f"Illegal header value b'Bearer {TOKEN}\\n'")
    error = pr_state(github(fail))
    trace = "".join(traceback.format_exception(error))
    assert TOKEN not in str(error)
    assert TOKEN not in trace, "the cause's text is in the logged traceback"


# ---------------------------------------------------------------- #445 (F2): what #453 makes moot, then what it leaves

def test_moot_on_453_overlapping_secrets_are_replaced_longest_first(secrets):
    for value in ("abcdefgh", "abcdefgh-SUFFIX"):
        register_secret(value)
    assert redact("x abcdefgh-SUFFIX y") == "x *** y"


def test_kept_from_main_a_value_shorter_than_eight_characters_is_not_a_credential(secrets):
    """core/clients/redact.py's MIN_SECRET (#423). Codex registered every non-empty value: with the fixtures' one-letter
    token "t", "Host key verification failed" became "Hos*** key verifica***ion failed" and an SSH test failed."""
    register_secret("t")
    assert redact("Host key verification failed") == "Host key verification failed"


def test_a_structure_is_redacted_at_any_depth(secrets):
    register_secret(TOKEN)
    assert redact({"nested": [TOKEN, {"x": TOKEN}], "t": (TOKEN,)}) == {"nested": ["***", {"x": "***"}], "t": ("***",)}


def test_an_op_event_redacts_a_nested_field(secrets, capsys):
    register_secret(TOKEN)
    with Op("pr_state") as op:
        op.set(detail={"echo": [TOKEN]}, rows=[{"body": TOKEN}])
    assert TOKEN not in capsys.readouterr().out


# ---------------------------------------------------------------- #447 (F4): the workdir is private, in exact modes

def req() -> BranchRequest:
    return BranchRequest("CRC", "req-1", FOLDER, "hash", "create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
                         {FOLDER + "namespace.yaml": "kind: Namespace\n"}, {}, datetime(2026, 1, 1, tzinfo=timezone.utc))


def modes(ws: GitWorkspace) -> tuple[int, int, int]:
    return (stat.S_IMODE(ws.root.stat().st_mode), stat.S_IMODE(ws._home.stat().st_mode),
            stat.S_IMODE((ws.root / ".lock").stat().st_mode))


def test_the_workdir_home_and_lock_are_private_under_a_permissive_umask(tmp_path):
    bare = bare_repo(tmp_path)
    workdir = tmp_path / "worker"
    workdir.mkdir()
    workdir.chmod(0o777)
    old = os.umask(0o022)
    try:
        ws = GitWorkspace(bare.as_uri(), workdir=workdir)
        try:
            ws.push_branch(req())
            assert modes(ws) == (0o700, 0o700, 0o600)
        finally:
            ws.dispose()
    finally:
        os.umask(old)


def refuse_chmod_of(monkeypatch, workdir: Path) -> None:
    """An emptyDir: 0777 and root's, so this UID's chmod of it is refused. Simulated for that one path."""
    real = Path.chmod

    def chmod(self, mode, *a, **k):
        if self == workdir:
            raise PermissionError(1, "Operation not permitted", str(self))
        return real(self, mode, *a, **k)
    monkeypatch.setattr(Path, "chmod", chmod)


def test_a_workdir_this_uid_cannot_chmod_holds_a_private_child(tmp_path, monkeypatch):
    bare = bare_repo(tmp_path)
    workdir = tmp_path / "emptydir"
    workdir.mkdir()
    refuse_chmod_of(monkeypatch, workdir)
    ws = GitWorkspace(bare.as_uri(), workdir=workdir)
    try:
        assert ws.root == workdir / f".private-{os.getuid()}"
        assert modes(ws) == (0o700, 0o700, 0o600)
    finally:
        ws.dispose()


def test_a_private_child_that_is_a_symlink_is_refused(tmp_path, monkeypatch):
    from cmapi.core.git.transport import GitConfigError

    bare = bare_repo(tmp_path)
    workdir = tmp_path / "emptydir"
    workdir.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (workdir / f".private-{os.getuid()}").symlink_to(tmp_path / "elsewhere")
    refuse_chmod_of(monkeypatch, workdir)
    with pytest.raises(GitConfigError, match="not a directory of this process's UID"):
        GitWorkspace(bare.as_uri(), workdir=workdir)
