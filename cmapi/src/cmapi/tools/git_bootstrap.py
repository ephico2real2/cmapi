"""Set up the Gitea stand-in for the Git host, the way a real GitHub organisation would be prepared
by its administrators: the bot user, the organisation, the cluster-configs repository seeded with
the layout of docs/01, and branch protection on main that requires the three checks
(ci/kubeconform, ci/kyverno, cmapi/check) so nothing merges without them.

Credentials: the Gitea admin (CMAPI_GIT_ADMIN_USER/PASSWORD from Secret cmapi-git-admin, written
by the cmapi-git chart) creates the bot; the bot's credential (CMAPI_GIT_USER/PASSWORD) is what
cmapi then uses. Nothing is printed but names.
"""
from __future__ import annotations

import base64
import os
import sys
import time
from typing import Any

import httpx

from cmapi.jobs.pr_checks import REQUIRED_CONTEXTS
from cmapi.settings import settings

SEED_README = """# cluster-configs

Desired state of every namespace cmapi manages, one folder per cluster under `clusters/<clusterId>/namespaces/`.
Only the cmapi bot merges here; branch protection requires the CI checks and the cmapi check
(approved request, PR head equal to the approved plan hash). Reviews in Git carry no authority: approval
happens in cmapi.
"""


def _wait(client: httpx.Client, attempts: int = 60) -> None:
    for i in range(attempts):
        try:
            r = client.get("/version")
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(min(2 + i, 10))
    sys.exit("the Git host did not answer /version")


def main(argv: list[str]) -> None:
    s = settings()
    api = s.git_url.rstrip("/")
    admin_user, admin_pw = os.environ.get("CMAPI_GIT_ADMIN_USER", ""), os.environ.get("CMAPI_GIT_ADMIN_PASSWORD", "")
    bot_user, bot_pw = os.environ.get("CMAPI_GIT_USER", "cmapi-bot"), os.environ.get("CMAPI_GIT_PASSWORD", "")
    if not (admin_user and admin_pw and bot_pw):
        sys.exit("CMAPI_GIT_ADMIN_USER, CMAPI_GIT_ADMIN_PASSWORD and CMAPI_GIT_PASSWORD are required")
    org, repo = os.environ.get("CMAPI_GIT_REPOSITORY", "").split("/") if os.environ.get("CMAPI_GIT_REPOSITORY") else \
        _repo_from_config(s)
    cluster_ids = [c for c in os.environ.get("CMAPI_GIT_CLUSTER_IDS", "").split(",") if c]
    admin = httpx.Client(base_url=api, auth=(admin_user, admin_pw), timeout=30, verify=s.verify)
    _wait(admin)

    # 1. the bot user
    r = admin.get(f"/users/{bot_user}")
    if r.status_code == 404:
        r = admin.post("/admin/users", json={"username": bot_user, "email": "cmapi-bot@ephico2real.com", "password": bot_pw,
                                             "must_change_password": False, "send_notify": False})
        r.raise_for_status()
        print(f"created user {bot_user}")
    else:
        r.raise_for_status()
        # keep the stored password in force: a rotated Secret reaches Gitea here
        admin.patch(f"/admin/users/{bot_user}", json={"password": bot_pw, "must_change_password": False,
                                                     "login_name": bot_user, "source_id": 0}).raise_for_status()
        print(f"user {bot_user} present")
    bot = httpx.Client(base_url=api, auth=(bot_user, bot_pw), timeout=30, verify=s.verify)

    # 2. the organisation, owned by the bot
    r = bot.get(f"/orgs/{org}")
    if r.status_code == 404:
        bot.post("/orgs", json={"username": org, "visibility": "private"}).raise_for_status()
        print(f"created org {org}")
    else:
        r.raise_for_status()

    # 3. the repository with its seed
    r = bot.get(f"/repos/{org}/{repo}")
    if r.status_code == 404:
        bot.post(f"/orgs/{org}/repos", json={"name": repo, "private": True, "auto_init": False,
                                             "default_branch": s.git_default_branch}).raise_for_status()
        print(f"created repository {org}/{repo}")
        files: dict[str, str] = {"README.md": SEED_README}
        for cid in cluster_ids:
            files[f"clusters/{cid}/namespaces/.keep"] = ""
        policies = _policies(s)
        files.update(policies)
        ops = [{"operation": "create", "path": p, "content": base64.b64encode(t.encode()).decode()} for p, t in files.items()]
        bot.post(f"/repos/{org}/{repo}/contents", json={"branch": s.git_default_branch, "new_branch": s.git_default_branch,
                                                        "message": "cluster-configs: initial layout", "files": ops}).raise_for_status()
        print(f"seeded {len(files)} files")
    else:
        r.raise_for_status()
        print(f"repository {org}/{repo} present")

    # 4. branch protection: no direct push, every required context green before a merge
    body = {"branch_name": s.git_default_branch, "rule_name": s.git_default_branch, "enable_push": False,
            "enable_status_check": True, "status_check_contexts": list(REQUIRED_CONTEXTS),
            "block_on_outdated_branch": False, "enable_merge_whitelist": True, "merge_whitelist_usernames": [bot_user]}
    r = bot.get(f"/repos/{org}/{repo}/branch_protections/{s.git_default_branch}")
    if r.status_code == 404:
        bot.post(f"/repos/{org}/{repo}/branch_protections", json=body).raise_for_status()
        print("branch protection created")
    else:
        r.raise_for_status()
        bot.patch(f"/repos/{org}/{repo}/branch_protections/{s.git_default_branch}", json=body).raise_for_status()
        print("branch protection in force")


def _repo_from_config(s: Any) -> list[str]:
    import yaml
    inst = yaml.safe_load((s.config_dir / "instance.yaml").read_text())["instance"]
    return inst["git"]["repository"].split("/")


def _policies(s: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    base = s.policies_dir
    if base.exists():
        for p in sorted(base.rglob("*.yaml")):
            out[f"policies/{p.relative_to(base)}"] = p.read_text()
    mk = s.metadata_keys_path
    if mk.exists():
        out["policies/metadata-keys.yaml"] = mk.read_text()
    return out
