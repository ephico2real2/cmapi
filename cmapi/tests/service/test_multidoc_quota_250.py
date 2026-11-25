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
from cmapi.jobs.delivery import spec_from
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


# Reviewer 1 of #682. A value that PyYAML's standard tags cannot construct: the resolver reads 2026-02-30 as a timestamp, and
# datetime.date raises ValueError, which is no yaml.YAMLError (PyYAML 6.0.2, lib/yaml/constructor.py).
BAD_VALUE = ("apiVersion: v1\nkind: Namespace\nmetadata:\n  name: payments-dev\n  annotations:\n"
             "    example.com/review-by: 2026-02-30\n")


@pytest.mark.parametrize("call", ["get", "patch", "delete"])
def test_680_a_value_that_yaml_cannot_construct_is_a_409_that_names_it(world, call):
    client, ctx, git, kube, validator, keys = world
    created(world)
    tag = etag(world)
    main = git.branches["main"]
    main[BASE + "namespace.yaml"] = BAD_VALUE
    git._sha("main")
    headers = {**auth(keys, "ola", **OLA), "If-Match": tag}
    r = {"get": lambda: client.get(ONE, headers=headers),
         "patch": lambda: client.patch(ONE + "?dryRun=true", json=LABEL, headers=headers),
         "delete": lambda: client.delete(ONE + "?dryRun=true", headers=headers)}[call]()
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "folder-not-yaml" and r.json()["paths"] == [BASE + "namespace.yaml"], r.text
    assert "not a valid timestamp at line 6, column 28" in r.json()["detail"], r.text
    assert "2026-02-30" not in r.json()["detail"]                  # the place, never the file's text


@pytest.mark.parametrize("text, line", [("a: 2026-02-30\n", 1), ("kind: X\nv: !!int abc\n", 2), ("kind: X\nv: !!bool maybe\n", 2),
                                        ("kind: X\nv: !!timestamp nope\n", 2)])
def test_the_reader_refuses_a_value_its_tag_cannot_construct_as_yaml(text, line):
    with pytest.raises(yaml.YAMLError) as caught:
        kube_yaml.load_all(text)
    assert caught.value.problem_mark.line + 1 == line


def test_a_limitrange_named_like_cmapis_but_not_rendered_by_cmapi_is_kept_in_git_and_on_the_cluster(world):
    """<ns>-limits-gpu with no cmapi.net/tier-hash is a team's object, not a rendering of a tier: a label change keeps it."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    gpu = {"apiVersion": "v1", "kind": "LimitRange", "metadata": {"name": f"{NAME}-limits-gpu", "namespace": NAME},
           "spec": {"limits": [{"type": "Container", "default": {"nvidia.com/gpu": "1"}}]}}
    path = BASE + f"limitrange-{NAME}-limits-gpu.yaml"
    git.branches["main"][path] = kube_yaml.dump(gpu, sort_keys=False)
    git._sha("main")
    kube.apply(gpu)
    plan = patch(world, LABEL)
    assert plan.status_code == 200, plan.text
    assert plan.json()["changes"] == {BASE + "namespace.yaml": "changed"}, plan.json()["changes"]
    r = patch(world, LABEL, dry_run=False)
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    assert docs(git.branches["main"][path]) == [gpu]
    assert ("LimitRange", NAME, f"{NAME}-limits-gpu") in kube.objects


def test_a_limitrange_that_cmapi_rendered_and_no_longer_renders_is_removed(world):
    """The other side: a <ns>-limits-storage that a tier rendered (it carries the tier hash) goes when the switch is off."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    main = git.branches["main"]
    storage = yaml.safe_load(main[BASE + f"limitrange-{NAME}-limits-cpu.yaml"])
    storage["metadata"]["name"] = f"{NAME}-limits-storage"
    storage["spec"] = {"limits": [{"type": "PersistentVolumeClaim", "max": {"storage": "10Gi"}}]}
    main[BASE + f"limitrange-{NAME}-limits-storage.yaml"] = kube_yaml.dump(storage, sort_keys=False)
    git._sha("main")
    plan = patch(world, LABEL)
    assert plan.status_code == 200, plan.text
    assert plan.json()["changes"][BASE + f"limitrange-{NAME}-limits-storage.yaml"] == "removed", plan.json()["changes"]


def test_a_second_copy_of_cmapis_quota_is_not_written_over_the_rendered_one(world):
    """A stale copy of <ns>-quota in resourcequota.yaml beside the named file: the plan renders the quota, and the copy goes."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    main = git.branches["main"]
    own = yaml.safe_load(main[BASE + f"resourcequota-{OWN}.yaml"])
    stale = yaml.safe_load(yaml.safe_dump(own))
    stale["spec"]["hard"]["requests.cpu"] = "64"
    main[BASE + "resourcequota.yaml"] = kube_yaml.dump(stale, sort_keys=False)
    git._sha("main")
    plan = patch(world, LABEL)
    assert plan.status_code == 200, plan.text
    # The named file may take this request's ID (the renderer keeps an ID only for an object equal to the one Git holds, and
    # Git holds two); its spec is the one rendered, never the copy's.
    assert plan.json()["changes"][BASE + "resourcequota.yaml"] == "removed", plan.json()["changes"]
    assert quotas_in(plan.json()["files"])[OWN][1]["spec"] == own["spec"]


def test_a_tier_sent_to_a_namespace_with_no_tier_label_and_two_quotas_is_refused(world):
    client, ctx, git, kube, validator, keys = world
    created(world)
    main = git.branches["main"]
    held = main[BASE + "namespace.yaml"]
    main[BASE + "namespace.yaml"] = held.replace("    cmapi.net/tier: small\n", "")
    assert main[BASE + "namespace.yaml"] != held
    one_file(world, [COMPUTE, BEST_EFFORT], keep_own=False)
    r = patch(world, {"tier": "medium"})
    assert r.status_code == 409 and r.json()["code"] == "several-resource-quotas", r.text
    assert patch(world, LABEL).status_code == 200                  # a change that sends no tier still passes


def test_a_kept_object_whose_name_is_no_file_name_stays_in_the_folder(world):
    """A name with "/" (the API server refuses it, a hand-written file can hold it) never makes a path outside the folder."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    odd = quota("../../other/x", {"pods": "1"})
    one_file(world, [EXTRA, odd], keep_own=True)
    plan = patch(world, LABEL)
    assert plan.status_code == 200, plan.text
    paths = list(plan.json()["changes"])
    assert all(p.startswith(BASE) and "/" not in p.removeprefix(BASE) for p in paths), paths
    assert any(name == "../../other/x" for name in quotas_in(plan.json()["files"])), plan.json()["files"].keys()


# Reviewer 2 of #682 (B1). own_quota takes "the only one there is" as cmapi's (#253), so a folder whose only ResourceQuota
# is a team's lost it on a change of labels: the plan removed it from Git, the sync pruned it from the cluster, and the tier's
# <ns>-quota took its place (small: requests.cpu 3 -> 8) while the plan sized no change, so no capacity rule saw it. A scoped
# quota became an unscoped one, and on tier custom the change answered 422. D9: "Any other request, a change of a label for
# example, leaves every object unchanged."
@pytest.mark.parametrize("tier, held", [("small", COMPUTE), ("custom", COMPUTE), ("small", BEST_EFFORT)])
def test_a_label_change_keeps_a_lone_quota_that_is_not_cmapis_and_renders_no_tier_quota_over_it(world, tier, held):
    client, ctx, git, kube, validator, keys = world
    created(world)
    main = git.branches["main"]
    if tier == "custom":
        main[BASE + "namespace.yaml"] = main[BASE + "namespace.yaml"].replace("cmapi.net/tier: small", "cmapi.net/tier: custom")
        git._sha("main")
    one_file(world, [held], keep_own=False)
    before = dict(main)
    name = held["metadata"]["name"]
    plan = patch(world, LABEL)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["changes"] == {BASE + "namespace.yaml": "changed", BASE + "resourcequota.yaml": "removed",
                               BASE + f"resourcequota-{name}.yaml": "added"}, body["changes"]
    assert quotas_in(body["files"]) == {name: (f"resourcequota-{name}.yaml", held)}
    assert body["capacity"]["cpu"] == 0 and body["capacity"]["memory"] == 0
    r = patch(world, LABEL, dry_run=False)
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    assert client.get(f"/api/v1/requests/{r.json()['requestId']}", headers=auth(keys, "ola", **OLA)).json()["status"] == "synced"
    assert kube.objects[("ResourceQuota", NAME, name)]["spec"] == held["spec"]
    assert ("ResourceQuota", NAME, OWN) not in kube.objects
    main = git.branches["main"]
    assert docs(main[BASE + f"resourcequota-{name}.yaml"]) == [held] and BASE + f"resourcequota-{OWN}.yaml" not in main
    assert {p: t for p, t in main.items() if "/limitrange-" in p} == {p: t for p, t in before.items() if "/limitrange-" in p}


def test_a_tier_move_still_acts_on_a_lone_quota_that_is_not_cmapis(world):
    """The other side, unchanged by B1's fix: with one ResourceQuota a change of the tier acts on it (#253; D9, "When the
    namespace has exactly one object of the kind, the name may be left out, as today"). The in-place change is D9's B3."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    one_file(world, [COMPUTE], keep_own=False)
    plan = patch(world, {"tier": "medium"})
    assert plan.status_code == 200, plan.text
    planned = quotas_in(plan.json()["files"])
    assert list(planned) == [OWN] and planned[OWN][1]["spec"]["hard"]["requests.cpu"] == "16", planned
    assert plan.json()["changes"][BASE + "resourcequota.yaml"] == "removed"


def test_a_plan_stored_before_b1s_fix_renders_as_it_did(world):
    """A stored spec has no changes_quota: it renders the tier's quota over a lone one, as its plan hash was taken (the
    delivery renders the stored spec again and checks the hash, jobs/delivery.py `rendered`)."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    one_file(world, [COMPUTE], keep_own=False)
    stored = {"namespace": NAME, "cluster_id": "CRC", "instance": "nonprod", "env": "dev", "tier": "small",
              "request_id": "req-1", "requested_by_user": "ola", "requested_by_email": None}
    files = ctx.pipeline.renderer.render(spec_from(stored), previous=dict(git.branches["main"]))
    assert list(quotas_in(files)) == [OWN] and files[BASE + "resourcequota.yaml"] is None


def test_680_a_folder_file_nested_deeper_than_the_reader_can_read_is_a_409(world):
    """Reviewer 2 of #682: PyYAML recurses once for each level of nesting, so a file nested some hundreds deep raised
    RecursionError, no yaml.YAMLError, and GET answered 500 internal-error."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    main = git.branches["main"]
    main[BASE + "namespace.yaml"] += "---\nkind: X\nv: " + "[" * 5000 + "]" * 5000 + "\n"
    git._sha("main")
    r = client.get(ONE, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "folder-not-yaml" and r.json()["paths"] == [BASE + "namespace.yaml"], r.text
    assert "nested deeper than the reader can read" in r.json()["detail"], r.text
