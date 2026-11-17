"""#333 and #345: the rendered Kyverno policies check the keys that no stanza declares, never refuse what cmapi accepts, and
keep the oldObject ratchet out of the background scan.

#333. cmapi's validator (MetadataKeys.validate) refuses a key outside the allowed classes, more other keys than
allowOther.max, and annotation values over maxValueBytes or maxBytesTotal. Before #333 the rendered policies checked only
the declared keys, so a namespace changed outside cmapi was held to none of these. The agreement test runs the corpus of
#328 (metadata_corpus.py, on its six configurations) through the real CLI: each map that the rendered policies refuse,
validate() refuses too, so Kyverno is never the only guard. validate() takes no policy setting, so the same set is refused
with `policy.engine: none` (tests/service/test_metadata_other_keys_333_api.py proves it through the API).

#345. A background scan evaluates a policy as a CREATE with no oldObject (Kyverno v1.20.0,
pkg/controllers/report/utils/scanner.go), so a policy that keeps a value through oldObject would report every kept value
as a failure. Each such policy has `evaluation.background.enabled: false`; the others keep the scan. The cluster run is in
docs/reviews/2026-11-17-issue-333/.

The CLI is the image's pin (v1.20.0): skipped without `kyverno` on PATH, and failing instead under CMAPI_REQUIRE_KYVERNO=1.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from cmapi.core.metadata import KINDS, MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import index_of, policy_name, render_bundle
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec
from cmapi.core.tiers import TierCatalog
from cmapi.core.validate import CliValidator, _held
from conftest import ALL_ENVS, EX
from metadata_corpus import cases, good, verdict
from test_metadata_schema_328 import CONFIGS, raw
from test_policygen import COMPANY, SHIPPED, kyverno, write  # noqa: F401  (kyverno is a fixture)

REFERENCE = {"namespace": "payments-dev", "environment": "dev", "cluster": "CRC", "instance": "nonprod"}


@pytest.fixture(scope="module")
def catalog() -> TierCatalog:
    return TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)


def namespace(catalog: TierCatalog, keys: MetadataKeys, sources: dict, labels: dict, annotations: dict) -> dict:
    """The Namespace that cmapi renders for a request, as the pipeline renders it (core/pipeline.py, plan_namespace)."""
    spec = NamespaceSpec(namespace=sources["namespace"], cluster_id=sources["cluster"], instance=sources["instance"],
                         env=sources["environment"], tier="small", request_id="req-1", requested_by_user="ola",
                         requested_by_email="ola@ephico2real.com", labels=labels, annotations=annotations)
    files = ManifestRenderer(catalog, keys).render(spec)
    return yaml.safe_load(next(t for p, t in files.items() if p.endswith("/namespace.yaml")))


class Namespaces:
    """namespace() for many requests of one configuration, without a YAML round trip each (about 12 ms): the renderer
    writes the request's keys, then the keys derived from the target, then its own keys, each later one winning
    (core/render/manifests.py, render). The renderer's own keys come from one render with no request key, and
    `check` holds the result equal to namespace() on a sample of the corpus."""

    def __init__(self, catalog: TierCatalog, keys: MetadataKeys, sources: dict):
        self.catalog, self.keys = catalog, keys
        base = namespace(catalog, keys, sources, {}, {})["metadata"]
        derived = dict(zip(KINDS, keys.derived(sources)))
        self.own = {kind: {k: v for k, v in (base.get(f"{kind}s") or {}).items() if k not in derived[kind]}
                    for kind in KINDS}

    def __call__(self, sources: dict, labels: dict, annotations: dict) -> dict:
        derived = dict(zip(KINDS, self.keys.derived(sources)))
        meta = {"name": sources["namespace"]}
        for kind, sent in (("label", labels), ("annotation", annotations)):
            meta[f"{kind}s"] = {**sent, **derived[kind], **self.own[kind]}
        return {"apiVersion": "v1", "kind": "Namespace", "metadata": meta}

    def check(self, sources: dict, labels: dict, annotations: dict) -> None:
        fast = self(sources, labels, annotations)["metadata"]
        slow = namespace(self.catalog, self.keys, sources, labels, annotations)["metadata"]
        assert {k: slow.get(k) for k in ("name", "labels", "annotations")} == fast, (fast, slow)


def failed(kyverno: str, policies: Path, docs: list[dict], tmp: Path) -> dict[str, list[tuple[str, str]]]:
    """{namespace: [(policy, message)]} of the failed results of one `kyverno apply` on the docs; any other result than
    pass, skip or fail stops the test (a policy that the CLI could not evaluate is a defect of the bundle)."""
    tmp.mkdir(parents=True, exist_ok=True)
    res = tmp / "resources.yaml"
    res.write_text("\n---\n".join(json.dumps(d) for d in docs) + "\n")   # JSON is YAML, and much faster to write
    r = subprocess.run([kyverno, "apply", str(policies), "--resource", str(res), "-p", "--output-format", "json"],
                       capture_output=True, text=True, timeout=600)
    report = json.loads(r.stdout)
    out: dict[str, list[tuple[str, str]]] = {}
    for result in report["results"]:
        assert result["result"] in ("pass", "skip", "fail"), result
        if result["result"] == "fail":
            out.setdefault(result["resources"][0]["name"], []).append((result["policy"], result.get("message", "")))
    return out


# --------------------------------------------------------------------------------------------- #345, without the CLI
@pytest.mark.parametrize("path, env, instance", [(SHIPPED, "dev", "nonprod"), (COMPANY, "rnd", "nonprod"),
                                                 (SHIPPED, "prod", "prod")])
def test_a_policy_that_reads_oldobject_is_not_run_by_the_background_scan(catalog, path, env, instance):
    """#345: each policy whose verdict reads oldObject (the ratchet) has evaluation.background.enabled false, and each
    other policy keeps the background scan (the CRD's default, true)."""
    files = render_bundle(catalog, MetadataKeys.load(path), PolicySettings(), {env}, instance)
    ratchet, scanned = set(), set()
    for rel, text in files.items():
        if not rel.endswith(".yaml"):
            continue
        for doc in yaml.safe_load_all(text):
            spec = doc["spec"]
            used = " ".join([*(v["expression"] for v in spec["validations"]),
                             *(v["expression"] for v in spec["variables"] if v["name"] != "update")])
            background = ((spec.get("evaluation") or {}).get("background") or {}).get("enabled", True)
            reads_old = "oldObject" in used or "variables.update" in used
            assert background is not reads_old, doc["metadata"]["name"]
            (ratchet if reads_old else scanned).add(doc["metadata"]["name"])
    # Every declared key, the system keys and the bounds keep their value through oldObject; the order of a LimitRange,
    # production's expiry and the keys that no stanza declares do not.
    index = index_of(files)
    assert {n for n in ratchet} == {n for n, c in index.items() if c["rule"] not in ("order", "absent") and c["key"]}
    assert {index[n]["rule"] for n in scanned} >= {"order", "prefix", "max"}


# ----------------------------------------------------------------------------------------------- #333, with the CLI
def test_each_new_rule_names_its_keys_and_its_configuration(kyverno, catalog, tmp_path):
    keys = MetadataKeys.load(SHIPPED)
    bundle = write(tmp_path / "b", render_bundle(catalog, keys, PolicySettings(), {"dev"}, "nonprod"))
    base = namespace(catalog, keys, REFERENCE, {"cmapi.net/team": "payments"},
                     {"cmapi.net/team-dl": "payments-team@ephico2real.com"})
    outside = copy.deepcopy(base)
    outside["metadata"]["name"] = "outside"
    outside["metadata"]["labels"].update({"other.example/x": "1", "cmapi.net/foo": "2"})
    outside["metadata"]["annotations"].update({"big": "é" * 2049})                   # 4098 bytes, 2049 characters
    many = copy.deepcopy(base)
    many["metadata"]["name"] = "many"
    many["metadata"]["labels"].update({f"k{i}": "v" for i in range(51)})
    many["metadata"]["annotations"].update({f"x.ephico2real.com/a{i}": "a" * 4000 for i in range(17)})
    got = failed(kyverno, bundle / "env/dev", [outside, many], tmp_path / "r")
    assert sorted(got["outside"]) == [
        ("cmapi-metadata-dev-annotation-other-keys-max-value-bytes",
         "the annotations big are over 4096 bytes (extraAnnotations.allowOther.maxValueBytes)"),
        ("cmapi-metadata-dev-label-other-keys-prefix",
         'the label keys cmapi.net/foo, other.example/x are not declared in metadata-keys.yaml, and are outside '
         'extraLabels.allowOther.prefixes ["", "*.ephico2real.com/"]'),
    ]
    assert sorted(got["many"]) == [
        ("cmapi-metadata-dev-annotation-other-keys-max-bytes-total",
         "the other annotations hold 68000 bytes; at most 65536 (extraAnnotations.allowOther.maxBytesTotal)"),
        ("cmapi-metadata-dev-label-other-keys-max",
         "there are 51 other labels (keys under extraLabels.allowOther.prefixes); at most 50 (extraLabels.allowOther.max)"),
    ]
    # cmapi refuses each of them on its own.
    for labels, annotations, code in (({"other.example/x": "1"}, {}, "invalid_key"), ({}, {"big": "é" * 2049}, "annotations_too_large"),
                                      ({f"k{i}": "v" for i in range(51)}, {}, "too_many_keys")):
        errors = keys.validate({"cmapi.net/team": "payments", **labels},
                               {"cmapi.net/team-dl": "payments-team@ephico2real.com", **annotations},
                               operator=False, sources=REFERENCE)
        assert code in {e["code"] for e in errors}, errors


def test_the_keys_that_the_platform_cmapi_and_an_operator_write_are_allowed_and_not_counted(kyverno, catalog, tmp_path):
    """System, operator-only and reserved keys are allowed on the object: the renderer, an operator's approved request
    and the platform write them (the API server's kubernetes.io/metadata.name, OpenShift's annotations). Who sent one is
    not on the object, so refusing them to a requester stays cmapi's check. 50 other labels is the limit, not over it."""
    keys = MetadataKeys.load(SHIPPED)
    bundle = write(tmp_path / "b", render_bundle(catalog, keys, PolicySettings(), {"dev"}, "nonprod"))
    ns = namespace(catalog, keys, REFERENCE, {"cmapi.net/team": "payments", **{f"k{i}": "v" for i in range(50)}},
                   {"cmapi.net/team-dl": "payments-team@ephico2real.com"})
    ns["metadata"]["labels"].update({"kubernetes.io/metadata.name": "payments-dev", "pod-security.kubernetes.io/enforce":
                                     "baseline", "cmapi.net/protected": "true", "company.net/provisioner": "cluster-configs"})
    ns["metadata"]["annotations"].update({"openshift.io/sa.scc.mcs": "s0:c26,c5", "openshift.io/sa.scc.uid-range":
                                          "1000670000/10000", "argocd.argoproj.io/tracking-id": "x"})
    assert failed(kyverno, bundle / "env/dev", [ns], tmp_path / "r") == {}


def test_the_keys_that_the_renderer_writes_are_allowed_whatever_the_file_calls_them(kyverno, catalog, tmp_path):
    """A file whose system list leaves out a key that the renderer writes, and whose reserved prefixes leave out Argo CD's:
    the policies read the keys from the renderer itself, so the namespace that cmapi renders passes."""
    data = raw(SHIPPED)
    data["system"] = [k for k in data["system"] if k not in ("cmapi.net/instance", "cmapi.net/request-id")]
    data["reservedPrefixes"] = [p for p in data["reservedPrefixes"] if not p.startswith("argocd")]
    keys = MetadataKeys(data)
    bundle = write(tmp_path / "b", render_bundle(catalog, keys, PolicySettings(), {"dev"}, "nonprod"))
    ns = namespace(catalog, keys, REFERENCE, {"cmapi.net/team": "payments"},
                   {"cmapi.net/team-dl": "payments-team@ephico2real.com"})
    assert {"cmapi.net/instance", "argocd.argoproj.io/sync-options"} <= set(ns["metadata"]["annotations"])
    assert failed(kyverno, bundle / "env/dev", [ns], tmp_path / "r") == {}


def test_a_refused_create_returns_the_kyverno_finding_beside_cmapis(kyverno, catalog, tmp_path):
    """The owner's ask on #333: in audit, the validator's finding for the refused body names the source, the policy, the
    file and the key; the pipeline lists it beside cmapi's own errors (core/pipeline.py, plan_namespace, #342)."""
    keys = MetadataKeys.load(SHIPPED)
    policy = PolicySettings(default_mode="audit")
    v = CliValidator(tmp_path / "none", kubeconform="true", policy=policy, environments={"dev"},
                     bundle=render_bundle(catalog, keys, policy, {"dev"}, "nonprod"))
    labels = {"cmapi.net/team": "payments", "other.example/x": "1"}
    annotations = {"cmapi.net/team-dl": "payments-team@ephico2real.com"}
    assert keys.validate(labels, annotations, operator=False, sources=REFERENCE) == \
        [{"code": "invalid_key", "key": "other.example/x", "detail": "prefix not allowed"}]
    spec = NamespaceSpec(namespace="payments-dev", cluster_id="CRC", instance="nonprod", env="dev", tier="small",
                         request_id="(planned)", requested_by_user="ola", requested_by_email="ola@ephico2real.com",
                         labels=labels, annotations=annotations)
    files = ManifestRenderer(catalog, keys).render(spec)
    found = [f for f in v.validate(files, "CRC", "dev") if f.source == "kyverno"]
    assert [(f.rule, f.path, f.severity, f.message) for f in found] == [
        ("cmapi-metadata-dev-label-other-keys-prefix", "clusters/CRC/namespaces/payments-dev/namespace.yaml", "warning",
         'the label keys other.example/x are not declared in metadata-keys.yaml, and are outside '
         'extraLabels.allowOther.prefixes ["", "*.ephico2real.com/"]')]


@pytest.mark.parametrize("prefixes, key, kyverno_refuses", [(["*"], "foo", True), (["*"], "/foo", True),
                                                            (["", "*"], "/foo", False)])
def test_the_star_prefix_and_an_empty_prefix_331_330(kyverno, catalog, tmp_path, prefixes, key, kyverno_refuses):
    """#331: under ["*"] a key with no prefix is refused by both. #330: cmapi refuses "/foo" (an empty prefix) in every
    configuration; the policies read it as classify() does, as a key with no prefix, so they admit it where "" is
    allowed. The API server refuses it before any admission webhook (IsLabelKey), so only plan time sees it."""
    keys = MetadataKeys({**raw(SHIPPED), "extraLabels": {**raw(SHIPPED)["extraLabels"], "allowOther": {"prefixes": prefixes}}})
    bundle = write(tmp_path / "b", render_bundle(catalog, keys, PolicySettings(), {"dev"}, "nonprod"))
    ns = namespace(catalog, keys, REFERENCE, {"cmapi.net/team": "payments", key: "x"},
                   {"cmapi.net/team-dl": "payments-team@ephico2real.com"})
    got = failed(kyverno, bundle / "env/dev", [ns], tmp_path / "r")
    assert bool(got) is kyverno_refuses, got
    assert keys.validate({"cmapi.net/team": "payments", key: "x"}, {"cmapi.net/team-dl": "payments-team@ephico2real.com"},
                         operator=False, sources=REFERENCE)


# ------------------------------------------------------------------------------------------- the agreement (#333)
@pytest.mark.parametrize("name", list(CONFIGS))
def test_each_map_that_the_rendered_policies_refuse_cmapi_refuses(kyverno, catalog, tmp_path, name):
    """The corpus of #328 through the rendered policies of the case's environment and through validate(). A create is
    the namespace that cmapi renders for the body. A patch is the namespace rendered over what Git holds, and a failure
    on a key whose value the previous version holds is dropped, as cmapi drops it at plan time (core/validate, _held)
    and the policy at admission (oldObject)."""
    load, base = CONFIGS[name]
    keys = load()
    bundle = render_bundle(catalog, keys, PolicySettings(), {base["environment"]}, base["instance"])
    index = index_of(bundle)
    policies = write(tmp_path / "b", bundle) / "env" / base["environment"]
    render = Namespaces(catalog, keys, base)
    rows = []
    for i, case in enumerate(cases(keys)):
        # One namespace for each case; a namespacePrefix key's example ("abc") starts each name.
        sources = {**base, "namespace": f"{base['namespace'].split('-')[0]}-c{i}"}
        other = "annotation" if case.kind == "label" else "label"
        current = {case.kind: {}, other: {}}
        if case.op == "patch":
            current = {case.kind: {**good(keys, case.kind), **case.held}, other: good(keys, other)}
        sent = {case.kind: dict(case.body), other: good(keys, other) if case.op == "create" else {}}
        result = {k: keys.merge_patch(current[k], sent[k]) for k in KINDS}
        new = render(sources, result["label"], result["annotation"])
        old = render(sources, current["label"], current["annotation"]) if case.op == "patch" else None
        if i % 250 == 0:
            render.check(sources, result["label"], result["annotation"])
        rows.append((case, sources, new, old))
    batches = [rows[i:i + 2000] for i in range(0, len(rows), 2000)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda b: failed(kyverno, policies, [r[2] for r in b[1]], tmp_path / f"r{b[0]}"),
                                enumerate(batches)))
    fails = {k: v for r in results for k, v in r.items()}
    counts = {"cases": len(rows), "cmapi refuses": 0, "kyverno refuses": 0, "both": 0, "cmapi only": 0}
    kyverno_only, only = [], {}                     # only: the codes of the maps that cmapi alone refuses
    for case, sources, new, old in rows:
        refused = [p for p, _ in fails.get(sources["namespace"], []) if not (old and _held(index[p], new, old))]
        errors = verdict(keys, case, sources)
        counts["cmapi refuses"] += bool(errors)
        counts["kyverno refuses"] += bool(refused)
        counts["both"] += bool(errors) and bool(refused)
        counts["cmapi only"] += bool(errors) and not refused
        if errors and not refused:
            for code in {e["code"] for e in errors}:
                only[code] = only.get(code, 0) + 1
        if refused and not errors:
            kyverno_only.append((case.kind, case.op, dict(case.body), refused))
    log = os.environ.get("CMAPI_AGREEMENT_LOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps({"config": name, **counts, "kyverno only": len(kyverno_only),
                                "codes of cmapi only": dict(sorted(only.items()))}) + "\n")
    assert kyverno_only == [], (counts, kyverno_only[:5])
    assert counts["kyverno refuses"] > 0, counts


# ----------------------------------------------------------------------------------------------- #356, without the CLI
@pytest.mark.parametrize("path", [SHIPPED, COMPANY])
def test_each_policy_name_fits_kyvernos_report_label(catalog, path):
    """#356: Kyverno labels a report vpol.kyverno.io/<policy name>, whose name part is at most 63 characters; one longer
    name made the API server refuse the background scan's report of every resource. Names stay unique and stable."""
    keys = MetadataKeys.load(path)
    names = [n for env in sorted(ALL_ENVS) for n in index_of(render_bundle(catalog, keys, PolicySettings(), {env},
                                                                          "prod" if env == "prod" else "nonprod"))]
    assert names and all(len(n) <= 63 for n in names), [n for n in names if len(n) > 63]
    assert len(names) == len(set(names))
    long = "cmapi-limits-rnd-limit-limitrange-container-defaultrequest-memory-max"
    assert policy_name(long) == policy_name(long) != policy_name(long + "x")
    assert len(policy_name(long)) <= 63 and policy_name("cmapi-quota-rnd-quota-requests-cpu-max") == \
        "cmapi-quota-rnd-quota-requests-cpu-max"
