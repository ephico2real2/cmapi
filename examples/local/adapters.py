"""Local adapters for the ports in cmapi.core.ports.

    LocalGit          GitProvider  bare repo + bot clone; a "PR" is a branch, merged --no-ff with an expected head
    LocalValidator    Validator    kubeconform + the Kyverno CLI on the rendered files (fails on 0 rules applied)
    KubeCluster       KubeReader + the Argo CD stand-in: applies merged folders server-side, holds deletes
                      until an operator confirms the prune. Any cluster kubectl can reach: k3s, kind, or an
                      existing one (KUBECONFIG and an optional context)
    SimulatedCapacity CapacityBackend: commitment against the size in config/clusters.yaml
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import yaml

from cmapi.core.ports import CapacityResult, Finding, PrRef
from cmapi.core.tiers import qty

ENV = {**os.environ,
       "GIT_AUTHOR_NAME": "cmapi-bot", "GIT_AUTHOR_EMAIL": "cmapi-bot@ephico2real.com",
       "GIT_COMMITTER_NAME": "cmapi-bot", "GIT_COMMITTER_EMAIL": "cmapi-bot@ephico2real.com"}


def run(*cmd: str, cwd: str | Path | None = None, check: bool = True, stdin: str | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, input=stdin)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


class LocalGit:
    def __init__(self, bare: str, work: str, seed: Mapping[str, str]):
        self.bare, self.work = Path(bare), Path(work)
        if not self.bare.exists():
            run("git", "init", "--bare", "-b", "main", str(self.bare))
            seed_dir = Path(tempfile.mkdtemp())
            run("git", "init", "-b", "main", cwd=seed_dir)
            for path, text in seed.items():
                (seed_dir / path).parent.mkdir(parents=True, exist_ok=True)
                (seed_dir / path).write_text(text)
            run("git", "add", "-A", cwd=seed_dir)
            run("git", "commit", "-m", "cluster-configs: initial layout", cwd=seed_dir)
            run("git", "push", str(self.bare), "main", cwd=seed_dir)
        if not self.work.exists():
            run("git", "clone", str(self.bare), str(self.work))

    def _sync_main(self) -> None:
        run("git", "fetch", "-q", "origin", cwd=self.work)
        run("git", "checkout", "-q", "main", cwd=self.work)
        run("git", "reset", "-q", "--hard", "origin/main", cwd=self.work)

    def head(self) -> str:
        self._sync_main()
        return run("git", "rev-parse", "HEAD", cwd=self.work).strip()

    def read_folder(self, path: str, ref: str = "main") -> tuple[dict[str, str], str]:
        self._sync_main()
        base = self.work / path
        files = {str(p.relative_to(self.work)): p.read_text() for p in base.rglob("*.yaml")} if base.exists() else {}
        return files, run("git", "rev-parse", "HEAD", cwd=self.work).strip()

    def open_pr(self, branch: str, files: Mapping[str, str | None], title: str, body: str, base_sha: str) -> PrRef:
        self._sync_main()
        run("git", "checkout", "-q", "-B", branch, cwd=self.work)
        for path, text in files.items():
            f = self.work / path
            if text is None:
                if f.exists():
                    f.unlink()
            else:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text)
        run("git", "add", "-A", cwd=self.work)
        run("git", "commit", "-q", "-m", title, "-m", body, cwd=self.work)
        run("git", "push", "-q", "-f", "origin", branch, cwd=self.work)
        head = run("git", "rev-parse", "HEAD", cwd=self.work).strip()
        return PrRef(number=abs(hash(branch)) % 1000, url=f"file://{self.bare}#{branch}", branch=branch, head_sha=head)

    def tree_files(self, ref: str, folder: str) -> dict[str, str]:
        names = run("git", "ls-tree", "-r", "--name-only", ref, "--", folder, cwd=self.work).split()
        return {n: run("git", "show", f"{ref}:{n}", cwd=self.work) for n in names}

    def merge(self, pr: PrRef, expected_head: str) -> str:
        self._sync_main()
        actual = run("git", "rev-parse", f"origin/{pr.branch}", cwd=self.work).strip()
        if actual != expected_head:
            raise RuntimeError("PR head moved since the checks ran")
        run("git", "merge", "-q", "--no-ff", f"origin/{pr.branch}", "-m", f"Merge {pr.branch}", cwd=self.work)
        run("git", "push", "-q", "origin", "main", cwd=self.work)
        run("git", "push", "-q", "origin", "--delete", pr.branch, cwd=self.work)
        return run("git", "rev-parse", "HEAD", cwd=self.work).strip()

    def log(self, n: int = 20) -> str:
        self._sync_main()
        return run("git", "log", "--oneline", "--graph", f"-{n}", cwd=self.work)


class LocalValidator:
    def __init__(self, policies_dir: str):
        self.policies = sorted(str(p) for p in Path(policies_dir).glob("*.yaml"))

    def validate(self, files: Mapping[str, str | None], cluster_id: str, environment: str) -> list[Finding]:
        out: list[Finding] = []
        live = {p: t for p, t in files.items() if t}
        if not live:
            return out
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for p, t in live.items():
                f = Path(d) / p.replace("/", "__")
                f.write_text(t)
                paths.append(str(f))
            r = subprocess.run(["kubeconform", "-strict", "-summary", "-output", "json", *paths],
                               capture_output=True, text=True, env=ENV)
            for res in json.loads(r.stdout or "{}").get("resources", []):
                if res.get("status") in ("statusInvalid", "statusError"):
                    out.append(Finding("kubeconform", "schema", res["filename"], res.get("msg", "")))
            ns_files = [p for p in paths if p.endswith("namespace.yaml")]
            policies = [p for p in self.policies if environment == "prod" or "env/prod" not in p
                        and "deny-expiry-in-prod" not in p]
            for pol in policies:
                for nf in ns_files:
                    r = subprocess.run(["kyverno", "apply", pol, "--resource", nf], capture_output=True,
                                       text=True, env=ENV)
                    text = r.stdout + r.stderr
                    if "Applying 0 policy rule" in text:
                        out.append(Finding("kyverno", Path(pol).stem, nf, "policy not understood by the CLI (0 rules)"))
                    elif "fail: 0" not in text:
                        out.append(Finding("kyverno", Path(pol).stem, nf, text.strip().splitlines()[-1]))
        return out


class KubeCluster:
    """KubeReader plus the Argo CD stand-in for this local run.

    Talks to the cluster only through kubectl, so k3s, kind and an existing cluster are the same code:
    `kubeconfig` and `context` pick the cluster, `kubectl` the binary (k3s ships one as `k3s kubectl`).
    """

    def __init__(self, cluster_id: str, kubeconfig: str | None = None, context: str | None = None,
                 kubectl: str = "kubectl"):
        self.cluster_id = cluster_id
        self.cmd = [*kubectl.split(), *(["--context", context] if context else [])]
        self.env = {**ENV, **({"KUBECONFIG": kubeconfig} if kubeconfig else {})}

    def kubectl(self, *args: str, stdin: str | None = None, check: bool = True) -> str:
        p = subprocess.run([*self.cmd, *args], env=self.env, capture_output=True, text=True, input=stdin)
        if check and p.returncode != 0:
            raise RuntimeError(f"kubectl {' '.join(args)}: {p.stderr.strip() or p.stdout.strip()}")
        return p.stdout

    def server_version(self) -> str:
        return json.loads(self.kubectl("version", "-o", "json"))["serverVersion"]["gitVersion"]

    def apply_folder(self, files: Mapping[str, str]) -> None:
        docs = "---\n".join(t for _, t in sorted(files.items(), key=lambda kv: not kv[0].endswith("namespace.yaml")))
        self.kubectl("apply", "--server-side", "--field-manager=argocd-standin", "-f", "-", stdin=docs)

    def prune_objects(self, namespace: str, removed: list[str], previous: Mapping[str, str]) -> None:
        for path in removed:
            for d in yaml.safe_load_all(previous[path]):
                if d and d["kind"] != "Namespace":
                    self.kubectl("delete", d["kind"].lower(), d["metadata"]["name"], "-n", namespace,
                                 "--ignore-not-found")

    def delete_namespace(self, namespace: str) -> None:
        self.kubectl("delete", "namespace", namespace, "--wait=false", "--ignore-not-found")

    def namespace(self, name: str) -> dict[str, Any] | None:
        out = self.kubectl("get", "namespace", name, "-o", "json", check=False)
        return json.loads(out) if out.strip() else None

    def quota(self, cluster_id: str, namespace: str) -> dict[str, Any] | None:
        out = self.kubectl("get", "resourcequota", f"{namespace}-quota", "-n", namespace, "-o", "json", check=False)
        return json.loads(out) if out.strip() else None

    def managed_namespaces(self) -> list[dict[str, Any]]:
        out = json.loads(self.kubectl("get", "namespaces", "-l", "cmapi.net/managed=true", "-o", "json"))
        quotas = json.loads(self.kubectl("get", "resourcequota", "-A", "-l", "cmapi.net/managed=true", "-o", "json"))
        by_ns = {q["metadata"]["namespace"]: q for q in quotas["items"]}
        rows = []
        for ns in out["items"]:
            m, q = ns["metadata"], by_ns.get(ns["metadata"]["name"], {})
            hard, used = q.get("spec", {}).get("hard", {}), q.get("status", {}).get("used", {})
            def pct(k: str) -> float:
                return float(qty(used.get(k, "0")) / qty(hard[k])) if k in hard and qty(hard[k]) else 0.0
            rows.append({"name": m["name"], "clusterId": m["labels"].get("cmapi.net/cluster-id"),
                         "env": m["labels"].get("cmapi.net/env"), "team": m["labels"].get("cmapi.net/team"),
                         "tier": m["labels"].get("cmapi.net/tier"),
                         "cpu": [used.get("requests.cpu", "0"), hard.get("requests.cpu")],
                         "memory": [used.get("requests.memory", "0"), hard.get("requests.memory")],
                         "pods": [used.get("pods", "0"), hard.get("pods")],
                         "used": max(pct("requests.cpu"), pct("requests.memory"), pct("pods")),
                         "expiresAt": m.get("annotations", {}).get("cmapi.net/expires-at"),
                         "tierHash": q.get("metadata", {}).get("annotations", {}).get("cmapi.net/tier-hash")})
        return rows


class SimulatedCapacity:
    def __init__(self, clusters_yaml: str, cluster: KubeCluster):
        cfg = yaml.safe_load(Path(clusters_yaml).read_text())
        self.clusters, self.over, self.targets = cfg["clusters"], cfg["overcommit"], cfg["targets"]["commitment"]
        self.k = cluster

    def check(self, cluster_id: str, environment: str, cpu_delta: float, memory_delta: float) -> CapacityResult:
        size = self.clusters[cluster_id]["simulatedCapacity"]
        committed_cpu = sum(qty(r["cpu"][1] or "0") for r in self.k.managed_namespaces())
        committed_mem = sum(qty(r["memory"][1] or "0") for r in self.k.managed_namespaces())
        cap_cpu = qty(size["cpu"]) * Decimal(str(self.over["cpu"]))
        cap_mem = qty(size["memory"]) * Decimal(str(self.over["memory"]))
        ratios = {"cpu": (committed_cpu + Decimal(str(cpu_delta))) / cap_cpu,
                  "memory": (committed_mem + Decimal(str(memory_delta))) / cap_mem}
        worst = max(ratios, key=ratios.get)
        r = float(ratios[worst])
        status = "exceeded" if r > 1 else "warn" if r >= self.targets["warn"] else "fits"
        return CapacityResult(status, True, worst, {k: round(float(v), 3) for k, v in ratios.items()})
