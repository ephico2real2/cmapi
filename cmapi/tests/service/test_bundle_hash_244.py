"""#244 S1. The example Git tree, the in-memory render and the cluster's watch."""
from pathlib import Path

import pytest
import yaml

from cmapi.core import policybundle
from cmapi.core.clients.policyreports import LivePolicy
from cmapi.core.policygen import DIGEST, policy_digest
from cmapi.plugins.policies import router as policies
from conftest import build_world
from test_policies_302 import KYVERNO, RESULTS, _config, get, live_bundle, sync

DEV = Path(__file__).resolve().parents[3] / "examples/cluster-configs/policies/env/dev"
DEV_HASH = "1d05d32730f241fc36287e6b97780dc60f1844c074b33661876bb4cc561c573f"


def test_versioned_hash_orders_pairs_and_changes_with_one_digest():
    pairs = [("é", "def"), ("a", "abc")]
    assert policybundle.bundle_hash(pairs) == "72071f08e12ef174c76b11e19ebd8337bb73869dfda516ceadce9496ea18932f"
    assert policybundle.bundle_hash(pairs) == policybundle.bundle_hash([list(pairs[1]), pairs[0]])
    assert policybundle.bundle_hash(pairs) != policybundle.bundle_hash([("é", "fed"), ("a", "abc")])
    assert policybundle.bundle_hash([]) is None


def test_example_git_hash_ignores_file_order_unmarked_yaml_and_index():
    files = {p.name: p.read_text() for p in DEV.iterdir()}
    files["hand-written.yaml"] = files["cmapi-metadata-dev.yaml"].split("\n", 1)[1]
    files["index.json"] = "ignored"
    result = policybundle.git_hash(dict(reversed(files.items())))
    assert (result.digest, result.tampered) == (DEV_HASH, False)
    tree = {f"policies/env/dev/{p}": text for p, text in files.items()}
    tree["clusters/CRC/example.yaml"] = files["cmapi-quota-dev.yaml"]
    assert policybundle.git_hash(tree) == result
    with pytest.raises(ValueError, match="one environment"):
        policybundle.git_hash({**tree, "policies/env/rnd/extra.yaml": files["cmapi-quota-dev.yaml"]})
    empty = policybundle.git_hash({"hand-written.yaml": files["hand-written.yaml"]})
    assert (empty.digest, empty.tampered) == (None, False)


def test_git_recomputes_marked_documents_even_when_the_annotation_was_kept():
    text = (DEV / "cmapi-quota-dev.yaml").read_text()
    docs = list(yaml.safe_load_all(text))
    header = text.splitlines()[0] + "\n"
    result = policybundle.git_hash({"quota.yaml": text})
    reordered = header + yaml.safe_dump_all(reversed(docs), sort_keys=True)
    assert policybundle.git_hash({"quota.yaml": reordered}) == result
    old = docs[0]["metadata"]["annotations"][DIGEST]
    docs[0]["spec"]["validationActions"] = ["Deny"]
    changed = policybundle.git_hash({"quota.yaml": header + yaml.safe_dump_all(docs)})
    assert docs[0]["metadata"]["annotations"][DIGEST] == old != policy_digest(docs[0])
    assert changed.tampered and changed.digest != result.digest
    docs[0]["metadata"]["annotations"][DIGEST] = policy_digest(docs[0])
    repaired = policybundle.git_hash({"quota.yaml": header + yaml.safe_dump_all(docs)})
    assert repaired.digest == changed.digest and not repaired.tampered


def test_rendered_hash_includes_only_generated_policies_from_this_render(tmp_path):
    files = {f"env/dev/{p.name}": p.read_text() for p in DEV.glob("*.yaml")}
    text = files["env/dev/cmapi-quota-dev.yaml"]
    files.update({"env/rnd/rnd.yaml": text, "shared.yaml": text})
    disk = tmp_path / "env/dev"
    disk.mkdir(parents=True)
    (disk / "obsolete.yaml").write_text(text)
    bundle = policybundle.PolicyBundle(files, policies_dir=tmp_path)
    assert bundle.rendered_hash("dev") == DEV_HASH
    assert bundle.rendered_hash("absent") is None
    live = [LivePolicy(n, p.digest, True, (), None) for n, p in bundle.for_environment("dev").items()]
    live.append(LivePolicy("user-policy", None, False, (), None))
    assert policybundle.live_hash(live) == DEV_HASH
    assert policybundle.live_hash([]) is None


def test_git_can_explain_behind_only_when_its_hash_is_known():
    assert policies.hash_state("ok", "render", "old", git="old") == "behind"
    assert policies.hash_state("ok", "render", None) == "drift"
    assert policies.hash_state("ok", None, None) == "off"
    assert policies.hash_state("drift", "same", "same") == "current"
    assert policies.hash_state("capped", "same", "same") == "unknown"


def test_cluster_hashes_follow_the_polled_policies(test_config, keys, monkeypatch):
    with build_world(test_config, keys, monkeypatch) as (client, ctx, _, kube, _, _):
        def cluster():
            return get(client, keys, RESULTS)["clusters"][0]

        missing = cluster()
        assert (missing["hashState"], missing["hashes"]) == ("unknown", {"rendered": DEV_HASH, "live": None})
        kube.served_groups = {"wgpolicyk8s.io/v1alpha2"}
        sync(ctx)
        unread = cluster()
        assert (unread["state"], unread["hashState"], unread["hashes"]["live"]) == ("ok", "unknown", None)
        kube.served_groups = set(KYVERNO)
        sync(ctx)
        assert cluster()["hashState"] == "drift"
        live_bundle(kube, ctx)
        sync(ctx)
        current = cluster()
        assert (current["hashState"], current["hashes"]) == ("current", {"rendered": DEV_HASH, "live": DEV_HASH})

        # Extra generated policies count even if this render never contained their names.
        description = next(p.description for p in ctx.bundle.for_environment("dev").values() if p.generated)
        kube.objects[("ValidatingPolicy", "", "obsolete")] = {
            "metadata": {"name": "obsolete", "annotations": {"cmapi.net/generated": "true", DIGEST: "0" * 64,
                                                              policybundle.DESCRIPTION: description}}}
        sync(ctx)
        extra = cluster()
        assert extra["hashState"] == "drift" and extra["hashes"]["live"] != DEV_HASH

        watch = ctx.registry.clusters["CRC"].reports.watch
        later = watch.clock() + watch.RELIST_SECONDS + 1
        monkeypatch.setattr(watch, "clock", lambda: later)
        assert cluster()["hashState"] == "unknown"


@pytest.mark.parametrize("policy", [{"engine": "none"}, {"environments": {"dev": {"mode": "off"}}}])
def test_disabled_cluster_hashes_are_off(test_config, tmp_path, policy, keys, monkeypatch):
    with build_world(_config(test_config, tmp_path, policy), keys, monkeypatch) as (client, _, _, _, _, _):
        [cluster] = get(client, keys, RESULTS)["clusters"]
        assert cluster["hashes"] == {"rendered": None, "live": None}
        assert cluster["hashState"] == "off"


def test_dev_live_hash_ignores_foreign_and_handwritten_policies(test_config, keys, monkeypatch):
    with build_world(test_config, keys, monkeypatch) as (client, ctx, _, kube, _, _):
        kube.served_groups = set(KYVERNO)
        live_bundle(kube, ctx)
        # A prod bundle can reach this dev cluster. Check both its regular generated names and its expiry policy.
        for path in (DEV.parent / "prod").glob("*.yaml"):
            for doc in yaml.safe_load_all(path.read_text()):
                kube.objects[("ValidatingPolicy", "", doc["metadata"]["name"])] = doc
        kube.objects[("ValidatingPolicy", "", "manual")] = {"metadata": {"name": "manual"}}
        sync(ctx)
        [cluster] = get(client, keys, RESULTS)["clusters"]
        assert cluster["hashes"] == {"rendered": DEV_HASH, "live": DEV_HASH}
        assert cluster["hashState"] == "current"
