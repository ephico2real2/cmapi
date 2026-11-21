#!/usr/bin/env python3
"""ci/kyverno of a cmapi cluster-configs repository: each namespace folder under clusters/ through the Kyverno bundle that cmapi
renders for that namespace's environment (`cmapi-tools policies render` into policies/env/<env>/, #212).

    kyverno_check.py [<repository root>] [--kyverno PATH] [--pull-request-event PATH]

The environment of a folder is its Namespace's label cmapi.net/env, which cmapi derives. The policies of policies/env/<env>/ run on
the folder's Namespace, ResourceQuota and LimitRange documents, as cmapi's own validator runs them (core/validate). The mode of
the environment is in the bundle itself: a rendered policy without Deny in validationActions ([Audit, Warn], audit, the default
since #342) reports a failure as a warning on cmapi's request PRs, main pushes and local runs. On other PRs an audit violation
fails only in namespace folders changed between the merge under test and its first parent; unchanged folders warn (#429, #516).
If that diff is unavailable, every folder is treated as changed. A Deny violation fails in every case. An environment with no
rendered policy runs Kyverno off.

It fails, as cmapi's validator does, when the CLI cannot evaluate a policy (result error), gives no report, or gives no result for
a file of a kind a policy matches: the 1.16 CLI applied no rule to a policies.kyverno.io/v1 document and said nothing (docs/08).
Not done here: cmapi's ratchet, which keeps a value the previous version of an object already held. So a folder cmapi adopted with
a value beyond today's bounds fails here and passes in cmapi; every folder cmapi created holds only values within its bounds.

Exit 0 pass, 1 a finding, 2 usage. Each finding is a GitHub annotation on its file.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

CHECKED = {"namespaces": "Namespace", "resourcequotas": "ResourceQuota", "limitranges": "LimitRange"}


def _docs(path: Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]


def _policies(root: Path, env: str) -> dict[str, tuple[Path, dict]]:
    """The rendered Kyverno policies of one environment, by name."""
    out: dict[str, tuple[Path, dict]] = {}
    for f in sorted((root / "policies" / "env" / env).glob("*.yaml")):
        for d in _docs(f):
            if str(d.get("apiVersion", "")).startswith("policies.kyverno.io/"):
                out[d["metadata"]["name"]] = (f, d)
    return out


def _matched_kinds(policy: dict) -> set[str]:
    rules = ((policy.get("spec") or {}).get("matchConstraints") or {}).get("resourceRules") or []
    return {CHECKED[r] for rule in rules for r in rule.get("resources", []) if r in CHECKED}


def is_cmapi_pr(root: Path, event: Path) -> bool:
    """Match the single commit cmapi writes on cmapi/<cluster>/<requestId>. These markers are unsigned."""
    pr = json.loads(event.read_text())["pull_request"]
    head = pr["head"]
    branch = re.fullmatch(r"cmapi/[^/]+/([^/]+)", head["ref"])
    if pr.get("commits") != 1 or not branch or not head["repo"] or head["repo"]["id"] != pr["base"]["repo"]["id"]:
        return False
    # Inspect the event's head, even though the manifests under test are from GitHub's synthetic merge.
    # A NUL between trailer values makes duplicate trailers fail the exact comparison too.
    commit = subprocess.check_output([
        "git", "show", "-s", "--format=format:%P%x00%an%x00%cn%x00%ae%x00%ce%x00"
        "%(trailers:key=Cmapi-Request-Id,valueonly,separator=%x00)",
        "--end-of-options", head["sha"], "--",
    ], cwd=root)
    parents, author, committer, author_email, committer_email, request_id = commit.split(b"\0", 5)
    return (len(parents.split()) == 1 and author == committer == b"cmapi-git-bot"
            and author_email == committer_email and request_id == branch[1].encode())


def check_folder(root: Path, folder: Path, kyverno: str, *, fail_audit: bool = False) -> tuple[list[str], list[str]]:
    """(errors, warnings) of one namespace folder, each as a GitHub annotation."""
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731
    files = {f: _docs(f) for f in sorted(folder.glob("*.yaml"))}
    namespaces = [d for docs in files.values() for d in docs if d.get("kind") == "Namespace"]
    if len(namespaces) != 1:
        return [f"::error file={rel(folder)}::{len(namespaces)} Namespace documents in the folder, not 1"], []
    env = ((namespaces[0].get("metadata") or {}).get("labels") or {}).get("cmapi.net/env")
    if not env:
        return [f"::error file={rel(folder)}::the Namespace has no label cmapi.net/env, so no environment's bundle applies"], []
    policies = _policies(root, env)
    if not policies:
        return [], [f"::warning file={rel(folder)}::no rendered policy under policies/env/{env}: Kyverno is off in {env}"]
    checked = {f: docs for f, docs in files.items() if any(d.get("kind") in CHECKED.values() for d in docs)}
    several = [f for f, docs in checked.items() if len(docs) != 1]
    if several:
        return [f"::error file={rel(f)}::a file of a checked kind holds more than one document" for f in several], []
    by_object = {(d["kind"], (d.get("metadata") or {}).get("namespace", ""), d["metadata"]["name"]): f
                 for f, (d,) in checked.items()}
    r = subprocess.run([kyverno, "apply", *sorted({str(p) for p, _ in policies.values()}), "--resource",
                        ",".join(str(f) for f in checked), "-p", "--output-format", "json"],
                       capture_output=True, text=True, timeout=300)
    try:
        results = json.loads(r.stdout)["results"]
        assert isinstance(results, list)
    except (ValueError, KeyError, TypeError, AssertionError):
        tail = [ln for ln in (r.stderr or r.stdout).splitlines() if ln.strip()]
        return [f"::error file={rel(folder)}::kyverno exited {r.returncode} with no report: {(tail[0] if tail else '')[:200]}"], []
    errors, warnings, seen = [], [], set()
    for res in results:
        objs = res.get("resources") or []
        name = res.get("policy")
        if name not in policies or len(objs) != 1:
            errors.append(f"::error file={rel(folder)}::kyverno result for {name!r} names no single known resource")
            continue
        o = objs[0]
        f = by_object.get((o.get("kind"), o.get("namespace", ""), o.get("name")))
        if f is None:
            errors.append(f"::error file={rel(folder)}::kyverno result of {name} refers to an unknown resource")
            continue
        seen.add((name, f))
        result, message = res.get("result"), (res.get("message") or "")[:300]
        if result in ("pass", "skip"):
            continue
        # The cluster denies only with Deny: cmapi renders audit as [Audit, Warn] (core/policygen.py), and Deny never comes
        # with Warn (the ValidatingPolicy CRD). A policy with no actions is not audit: it fails, as an unknown result does.
        actions = policies[name][1]["spec"].get("validationActions")
        audit = isinstance(actions, list) and bool(actions) and "Deny" not in actions
        if result == "fail" and audit and not fail_audit:
            warnings.append(f"::warning file={rel(f)}::{name} (audit): {message}")
        elif result == "fail":
            errors.append(f"::error file={rel(f)}::{name}: {message}")
        else:      # error, or a result this script does not know: the policy was not evaluated, in any mode
            errors.append(f"::error file={rel(f)}::{name} could not be evaluated ({result}): {message}")
    for name, (_, policy) in policies.items():
        for f, (doc,) in checked.items():
            if doc["kind"] in _matched_kinds(policy) and (name, f) not in seen:
                errors.append(f"::error file={rel(f)}::{name} gave no result for this file: the CLI did not understand the policy")
    return errors, warnings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--kyverno", default="kyverno")
    ap.add_argument("--pull-request-event", type=Path, help="GitHub pull_request event JSON for the merge under test")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    fail_audit = a.pull_request_event is not None and not is_cmapi_pr(root, a.pull_request_event)
    changed_dirs = None
    if fail_audit:
        print("ci/kyverno: this PR is outside cmapi's request flow; audit violations fail the check in changed namespace folders")
        try:
            paths = subprocess.check_output(["git", "diff", "--name-only", "-z", "HEAD^1", "HEAD"],
                                            cwd=root, text=True, stderr=subprocess.PIPE).split("\0")
            changed_dirs = {parent for path in paths if path for parent in Path(path).parents}
        except (subprocess.CalledProcessError, OSError):
            print("ci/kyverno: first-parent diff unavailable; treating every namespace folder as changed")
    folders = sorted(p for p in root.glob("clusters/*/namespaces/*") if p.is_dir())
    errors, warnings = [], []
    for folder in folders:
        folder_changed = changed_dirs is None or folder.relative_to(root) in changed_dirs
        e, w = check_folder(root, folder, a.kyverno, fail_audit=fail_audit and folder_changed)
        errors += e
        warnings += w
    for line in warnings + errors:
        print(line)
    print(f"ci/kyverno: {len(folders)} namespace folders, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
