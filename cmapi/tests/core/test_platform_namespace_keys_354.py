"""PR #354 review (OB3): keys that a platform controller writes on a namespace that cmapi created are reserved, so the
other-keys policies of #333 never report them as a failure (the portal's Policies tab reads those PolicyReports).

The API server, the Pod Security label syncer, OpenShift's SCC allocator and Argo CD write under kubernetes.io/,
*.kubernetes.io/, *.openshift.io/, openshift.io/ and argocd.argoproj.io/, which every shipped file reserves. Two more write
outside them, on namespaces that teams own:
- OLM labels each target namespace of an OperatorGroup that does not target all namespaces with
  olm.operatorgroup.uid/<uid> (operator-lifecycle-manager, pkg/controller/operators/olm/operator.go, syncNamespace).
- OpenShift Pipelines' RBAC loop labelled every non-system namespace with
  openshift-pipelines.tekton.dev/namespace-reconcile-version (tektoncd/operator, pkg/reconciler/openshift/tektonconfig/rbac.go,
  namespaceVersionLabel; newer releases remove it on upgrade, older ones keep writing it).
A requester was refused these keys before (disallowed) and is refused them after (reserved): only the object side changes.

No kyverno CLI is needed: the test reads the regexes of the rendered labelOutside variable as Kyverno's RE2 would
(k.matches is a search; each pattern starts with ^).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import render_bundle
from cmapi.core.tiers import TierCatalog
from conftest import ALL_ENVS, EX

ROOT = EX.parent
PLATFORM_LABELS = ["olm.operatorgroup.uid/7c5b3c3e-8f2d-4a71-9a1f-0d6c2f1e5a10",
                   "openshift-pipelines.tekton.dev/namespace-reconcile-version"]


def _files() -> list[tuple[str, MetadataKeys]]:
    out = []
    for rel in ("examples/cluster-configs/policies/metadata-keys.yaml", "examples/cluster-configs/policies/metadata-keys.company.yaml",
                "examples/local/config/metadata-keys.yaml", "deploy/helm/cmapi/config/metadata-keys.yaml"):
        out.append((rel, MetadataKeys.load(ROOT / rel)))
    for rel in ("deploy/manifests/environments/crc/20-config.yaml", "deploy/manifests/environments/kind/20-config.yaml"):
        doc = next(d for d in yaml.safe_load_all((ROOT / rel).read_text()) if d and "metadata-keys.yaml" in (d.get("data") or {}))
        out.append((rel, MetadataKeys(yaml.safe_load(doc["data"]["metadata-keys.yaml"]))))
    return out


FILES = _files()


@pytest.mark.parametrize("rel, keys", FILES, ids=[r for r, _ in FILES])
def test_platform_written_namespace_labels_are_reserved(rel, keys):
    assert {k: keys.classify(k, "label") for k in PLATFORM_LABELS} == {k: "reserved" for k in PLATFORM_LABELS}


@pytest.mark.parametrize("rel, keys", FILES[:1] + FILES[4:5], ids=[FILES[0][0], FILES[4][0]])
def test_the_rendered_prefix_policy_allows_them(rel, keys):
    catalog = TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)
    bundle = render_bundle(catalog, keys, PolicySettings(), {"dev"}, "nonprod")
    doc = next(d for d in yaml.safe_load_all(bundle["env/dev/cmapi-metadata-dev.yaml"])
               if d["metadata"]["name"] == "cmapi-metadata-dev-label-other-keys-prefix")
    expr = next(v["expression"] for v in doc["spec"]["variables"] if v["name"] == "labelOutside")
    regexes = [bytes(r, "ascii").decode("unicode_escape") for r in re.findall(r'k\.matches\("((?:[^"\\]|\\.)*)"\)', expr)]
    assert regexes, expr
    assert [k for k in PLATFORM_LABELS if not any(re.search(r, k) for r in regexes)] == []
