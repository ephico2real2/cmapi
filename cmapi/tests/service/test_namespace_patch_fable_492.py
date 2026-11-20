"""The third review of #492 (#483), through the API on the service suite's world with PostgreSQL: the routes' side of
tests/core/test_namespace_patch_fable_492.py. The configuration is the #479 design's company.net file."""
from __future__ import annotations

from test_namespace_contract_479 import MINIMAL, URL, design_config, design_world  # noqa: F401  (fixtures)
from test_namespace_patch_contract_483 import (NS, create, errors_of, headers, lookup, patch, planned_namespace, read,
                                               relist)
from test_namespace_patch_review_492 import edit_git


def test_a_change_can_remove_a_label_that_git_holds_under_an_annotations_key(design_world):
    client, ctx, git, kube, validator, keys = design_world
    metadata = ctx.cfg.metadata
    key = next(k for k in metadata.rules["annotation"]
               if k not in metadata.rules["label"] and metadata.classify(k, "label") in ("team", "disallowed"))
    create(design_world)
    edit_git(design_world, lambda meta: meta["labels"].update({key: "legacy"}))
    kept = patch(design_world, {"labels": {"company.net/cl": "0"}})
    assert planned_namespace(kept)["labels"][key] == "legacy"                        # D6: kept when not named
    r = patch(design_world, {"labels": {key: None}})
    assert r.status_code == 200, r.text
    assert key not in planned_namespace(r)["labels"]
    assert r.json()["metadataDiff"] == {"labels": {key: {"before": "legacy", "after": None, "source": "request"}},
                                        "annotations": {}}                           # the annotation of that key stays
    assert errors_of(patch(design_world, {"labels": {key: "again"}})) == [("invalid_key", key)]


def test_a_namespace_in_git_that_the_cluster_does_not_have_is_drift_never_in_sync(design_world):
    client, ctx, git, kube, validator, keys = design_world
    metadata = ctx.cfg.metadata
    create(design_world)
    del kube.objects[("Namespace", "", NS)]                                          # deleted by hand on the cluster
    relist(ctx)
    assert ctx.registry.cache("CRC").namespace(NS) is None                          # the relist dropped it
    assert read(design_world)["sync"]["state"] == "drift"                            # as before: each key, live null

    def only_system(meta: dict) -> None:
        meta["labels"] = {k: v for k, v in meta["labels"].items() if metadata.classify(k, "label") == "system"}
        meta["annotations"] = {k: v for k, v in meta["annotations"].items()
                               if metadata.classify(k, "annotation") == "system"}

    edit_git(design_world, only_system)                                              # Git holds no key to compare
    assert read(design_world)["sync"] == {"state": "drift", "openRequest": None, "driftedKeys": []}



# --------------------------------------------------- S-1: q is at most 63 characters, the longest name or label value

def test_a_q_longer_than_a_name_is_the_routes_validation_error(design_world):
    assert lookup(design_world, "q=" + "a" * 63).status_code == 200
    r = lookup(design_world, "q=" + "a" * 64)
    assert r.status_code == 422 and r.json()["code"] == "validation-failed", r.text


# --------------------------------------------------- S-2: a change on a cluster whose environment moved says so

def environment_moved(r) -> list[str]:
    assert r.status_code == 200, r.text
    return [f["message"] for f in r.json()["findings"] if f["rule"] == "environment_moved"]


def test_a_change_says_when_gits_environment_is_not_the_clusters_and_a_create_never_does(design_world):
    client, ctx, git, kube, validator, keys = design_world
    created = client.post(URL + "?dryRun=true", json=MINIMAL, headers=headers(keys))
    assert environment_moved(created) == []                                          # a create: nothing in Git yet
    create(design_world)
    assert environment_moved(patch(design_world, {"labels": {"company.net/cl": "0"}})) == []   # the same environment
    edit_git(design_world, lambda meta: meta["labels"].update({"cmapi.net/env": "rnd"}))      # Git from an rnd cluster
    r = patch(design_world, {"labels": {"company.net/cl": "0"}})
    assert environment_moved(r) == ["Git holds the environment rnd and the cluster is now dev: this change writes dev"]
    assert planned_namespace(r)["labels"]["cmapi.net/env"] == "dev"                  # the system label follows the cluster
