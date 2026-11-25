"""#250: a namespace folder whose files hold several documents, and a folder with several ResourceQuotas.

The adoption design's D8 and D9 (docs/reviews/2026-11-14-issue-26-adoption/README.md): a folder of the old layout is read as a
stream of documents and moves to one file for each object at its next change, each object unchanged; a request that names no
object leaves every ResourceQuota and LimitRange that is not cmapi's own unchanged; with several ResourceQuotas a change of
the quota is refused with a problem that names them.

Before the fix: a label change wrote only cmapi's <ns>-quota and removed the file that held the other ResourceQuota, so
the sync pruned it from the cluster; with two quotas and none of them cmapi's, it removed both and added <ns>-quota; a quota
change was planned over one of them; and a namespace.yaml with a second document (a trailing `---`) answered 500.
"""
from __future__ import annotations

import pytest
import yaml

from cmapi.core import kube_yaml
from test_flow import NS, OLA, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces"
NAME = NS["namespace"]
ONE = f"{URL}/{NAME}"
BASE = f"clusters/CRC/namespaces/{NAME}/"
OWN = f"{NAME}-quota"
LABEL = {"labels": {"cmapi.net/cost-center": "cc-9000"}}


def quota(name: str, hard: dict[str, str], **spec) -> dict:
    """A ResourceQuota that cmapi did not render: no cmapi.net/ key, as an adopted or hand-written one is."""
    return {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": {"name": name, "namespace": NAME},
            "spec": {"hard": hard, **spec}}


EXTRA = quota("payments-dev-objects", {"count/deployments.apps": "20", "services.loadbalancers": "0"})
COMPUTE = quota("compute", {"requests.cpu": "3", "requests.memory": "6Gi"})
BEST_EFFORT = quota("best-effort", {"pods": "5"}, scopes=["BestEffort"])


def docs(text: str | None) -> list[dict]:
    """The objects of a file, read here without the reader under test, so each test fails on the old code for its own reason."""
    return [d for d in yaml.safe_load_all(text or "") if isinstance(d, dict)]


def created(world) -> None:
    """payments-dev on tier small, created, merged and synced: auto-approved in dev."""
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    assert client.get(f"/api/v1/requests/{r.json()['requestId']}", headers=auth(keys, "ola", **OLA)).json()["status"] == "synced"


def one_file(world, docs: list[dict], *, keep_own: bool) -> dict[str, dict]:
    """Write the folder's ResourceQuotas as one resourcequota.yaml of several documents, as a folder of the old layout or a
    hand edit holds them, and put the other ones on the cluster too. Returns each quota by name, as Git now holds it."""
    client, ctx, git, kube, validator, keys = world
    main = git.branches["main"]
    own = yaml.safe_load(main.pop(BASE + f"resourcequota-{OWN}.yaml"))
    if not keep_own:
        kube.delete("ResourceQuota", NAME, OWN)
    all_docs = ([own] if keep_own else []) + docs
    main[BASE + "resourcequota.yaml"] = kube_yaml.dump_all(all_docs, sort_keys=False)
    git._sha("main")
    for d in docs:
        kube.apply(d)
    return {d["metadata"]["name"]: d for d in all_docs}


def etag(world) -> str:
    client, ctx, git, kube, validator, keys = world
    r = client.get(ONE, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    return r.json()["etag"]


def patch(world, body: dict, *, dry_run: bool = True):
    client, ctx, git, kube, validator, keys = world
    return client.patch(ONE + ("?dryRun=true" if dry_run else ""), json=body,
                        headers={**auth(keys, "ola", **OLA), "If-Match": etag(world)})


def quotas_in(files: dict[str, str | None]) -> dict[str, tuple[str, dict]]:
    """Each ResourceQuota that the plan's folder holds: name -> (the file's name, the object)."""
    out = {}
    for path, text in files.items():
        for d in docs(text):
            if d["kind"] == "ResourceQuota":
                out[d["metadata"]["name"]] = (path.removeprefix(BASE), d)
    return out


def test_a_label_change_keeps_both_quotas_of_one_file_unchanged_each_in_its_own_file_and_on_the_cluster(world):
    client, ctx, git, kube, validator, keys = world
    created(world)
    held = one_file(world, [EXTRA], keep_own=True)
    plan = patch(world, LABEL)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    # D8: the old file goes and each object gets its own, in the same plan; no other quota or LimitRange file changes.
    assert body["changes"] == {BASE + "namespace.yaml": "changed", BASE + "resourcequota.yaml": "removed",
                               BASE + f"resourcequota-{OWN}.yaml": "added",
                               BASE + "resourcequota-payments-dev-objects.yaml": "added"}, body["changes"]
    planned = quotas_in(body["files"])
    assert planned == {OWN: (f"resourcequota-{OWN}.yaml", held[OWN]),
                       "payments-dev-objects": ("resourcequota-payments-dev-objects.yaml", EXTRA)}
    r = patch(world, LABEL, dry_run=False)
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    assert client.get(f"/api/v1/requests/{r.json()['requestId']}", headers=auth(keys, "ola", **OLA)).json()["status"] == "synced"
    # The apply delivery prunes the objects of a removed file that no file keeps: both quotas stay on the cluster.
    assert kube.objects[("ResourceQuota", NAME, "payments-dev-objects")]["spec"] == EXTRA["spec"]
    assert kube.objects[("ResourceQuota", NAME, OWN)]["spec"] == held[OWN]["spec"]
    main = git.branches["main"]
    assert BASE + "resourcequota.yaml" not in main
    assert docs(main[BASE + "resourcequota-payments-dev-objects.yaml"]) == [EXTRA]


def test_a_quota_already_in_its_own_file_keeps_its_text(world):
    """A ResourceQuota that cmapi does not own, alone in its named file: the plan does not touch the file."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    text = "# written by hand\n" + yaml.safe_dump(EXTRA, sort_keys=True)
    git.branches["main"][BASE + "resourcequota-payments-dev-objects.yaml"] = text
    git._sha("main")
    plan = patch(world, LABEL)
    assert plan.status_code == 200, plan.text
    assert plan.json()["changes"] == {BASE + "namespace.yaml": "changed"}       # the file is not touched, byte for byte


@pytest.mark.parametrize("tier", ["small", "custom"])
def test_two_quotas_and_none_of_them_cmapis_a_label_change_keeps_every_quota_and_limitrange(world, tier):
    client, ctx, git, kube, validator, keys = world
    created(world)
    if tier == "custom":
        main = git.branches["main"]
        main[BASE + "namespace.yaml"] = main[BASE + "namespace.yaml"].replace("cmapi.net/tier: small", "cmapi.net/tier: custom")
        git._sha("main")
    one_file(world, [COMPUTE, BEST_EFFORT], keep_own=False)
    before = dict(git.branches["main"])
    plan = patch(world, LABEL)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["changes"] == {BASE + "namespace.yaml": "changed", BASE + "resourcequota.yaml": "removed",
                               BASE + "resourcequota-compute.yaml": "added",
                               BASE + "resourcequota-best-effort.yaml": "added"}, body["changes"]
    assert quotas_in(body["files"]) == {"compute": ("resourcequota-compute.yaml", COMPUTE),
                                        "best-effort": ("resourcequota-best-effort.yaml", BEST_EFFORT)}
    for path, text in before.items():                 # the LimitRanges are the files Git holds
        if "/limitrange-" in path:
            assert body["files"].get(path, text) == text
    # No quota is added, raised or exposed: the plan sizes nothing.
    assert body["capacity"]["cpu"] == 0 and body["capacity"]["memory"] == 0
    assert body["beyondTier"] is None and body["approval"]["auto"] == "none-required", body["approval"]
    assert patch(world, LABEL, dry_run=False).status_code == 202


@pytest.mark.parametrize("change", [{"tier": "medium"}, {"tier": "custom", "quota": {"requests.cpu": "4", "requests.memory": "8Gi",
                                                                                      "pods": "20"}}])
def test_a_quota_change_beside_another_quota_is_refused_naming_both(world, change):
    client, ctx, git, kube, validator, keys = world
    created(world)
    one_file(world, [EXTRA], keep_own=True)
    for dry_run in (True, False):
        r = patch(world, change, dry_run=dry_run)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "several-resource-quotas", r.text
        assert r.json()["resourceQuotas"] == ["payments-dev-objects", OWN], r.text
        assert OWN in r.json()["detail"] and "payments-dev-objects" in r.json()["detail"]
    assert client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["page"]["total"] == 1   # the create only


def test_with_no_quota_of_cmapis_a_limits_change_is_refused_too(world):
    client, ctx, git, kube, validator, keys = world
    created(world)
    main = git.branches["main"]
    main[BASE + "namespace.yaml"] = main[BASE + "namespace.yaml"].replace("cmapi.net/tier: small", "cmapi.net/tier: custom")
    one_file(world, [COMPUTE, BEST_EFFORT], keep_own=False)
    r = patch(world, {"limitRange": {"container": {"max": {"cpu": "1"}}}})
    assert r.status_code == 409 and r.json()["code"] == "several-resource-quotas", r.text
    assert r.json()["resourceQuotas"] == ["best-effort", "compute"]


def test_a_limitrange_that_cmapi_does_not_own_is_kept(world):
    """D9: a request that names no object leaves it unchanged, LimitRanges too."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    defaults = {"apiVersion": "v1", "kind": "LimitRange", "metadata": {"name": "gpu-defaults", "namespace": NAME},
                "spec": {"limits": [{"type": "Container", "default": {"nvidia.com/gpu": "1"}}]}}
    main = git.branches["main"]
    main[BASE + "limitrange.yaml"] = kube_yaml.dump(defaults, sort_keys=False)
    git._sha("main")
    plan = patch(world, LABEL)
    assert plan.status_code == 200, plan.text
    assert plan.json()["changes"] == {BASE + "namespace.yaml": "changed", BASE + "limitrange.yaml": "removed",
                                      BASE + "limitrange-gpu-defaults.yaml": "added"}
    assert docs(plan.json()["files"][BASE + "limitrange-gpu-defaults.yaml"]) == [defaults]


def test_a_namespace_yaml_with_a_second_document_is_read(world):
    """A trailing `---` is a second, empty document: yaml.safe_load raised ComposerError, and GET and every change answered
    500."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    main = git.branches["main"]
    main[BASE + "namespace.yaml"] += "---\n"
    git._sha("main")
    r = client.get(ONE, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and r.json()["git"]["labels"]["cmapi.net/tier"] == "small", r.text
    plan = patch(world, LABEL)
    assert plan.status_code == 200, plan.text
    assert plan.json()["metadataDiff"] is not None


def test_the_reader_takes_every_object_of_a_stream():
    text = "# head\n---\nkind: A\n---\n---\n- not an object\n---\nkind: B\n...\n---\n"
    assert kube_yaml.load_all(text) == [{"kind": "A"}, {"kind": "B"}]
    assert kube_yaml.load_all(None) == [] and kube_yaml.load_all("") == []


BROKEN = "apiVersion: v1\nkind: Namespace\nmetadata: {name: payments-dev\n"


@pytest.mark.parametrize("call", ["get", "patch", "delete"])
def test_680_a_folder_file_that_is_not_yaml_is_a_409_that_names_it(world, call):
    """#680: a manifest that PyYAML cannot parse made GET and every change of the namespace answer 500 internal-error."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    tag = etag(world)
    main = git.branches["main"]
    main[BASE + "namespace.yaml"] = BROKEN
    git._sha("main")
    headers = {**auth(keys, "ola", **OLA), "If-Match": tag}
    r = {"get": lambda: client.get(ONE, headers=headers),
         "patch": lambda: client.patch(ONE + "?dryRun=true", json=LABEL, headers=headers),
         "delete": lambda: client.delete(ONE + "?dryRun=true", headers=headers)}[call]()
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "folder-not-yaml" and r.json()["paths"] == [BASE + "namespace.yaml"], r.text
    assert "line 4, column 1" in r.json()["detail"], r.text
