"""PR #733's review: an adoption's direct writes (delivery mode apply) carry the uid and resourceVersion that the plan read, so
the API server refuses an object replaced or changed between cmapi's last read and its write (story #26, D16). Fakes for Git
and the cluster; no database.

Kubernetes, release-1.31: an apply patch whose uid names no existing object is a Conflict (patch.go, "uid mismatch: the
provided object specified uid ..., and no existing object was found"); another uid on an existing object is refused as an
immutable field (objectmeta.go, ValidateImmutableField of metadata.uid); a resourceVersion that is not the stored one is a
Conflict (store.go, OptimisticLockErrorMsg)."""
from datetime import datetime, timezone
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml

from cmapi.core.adoption import AdoptionSettings, Owner, adopted_files, snapshot, snapshot_hash
from cmapi.core.clients.kube import KubeError
from cmapi.core.metadata import MetadataKeys
from cmapi.core.render.manifests import plan_hash
from cmapi.jobs import delivery

SETTINGS = AdoptionSettings()
apply_job = import_module("cmapi.jobs.apply")
watch_sync = import_module("cmapi.jobs.watch_sync")


def _world():
    """An approved adoption of one Namespace and one ResourceQuota, its row, and a context whose cluster holds the objects
    exactly as the plan read them."""
    ns = {"apiVersion": "v1", "kind": "Namespace",
          "metadata": {"name": "abc-rnd", "uid": "ns-uid", "resourceVersion": "7", "labels": {"cmapi.net/adopt": "true"}}}
    rq = {"kind": "ResourceQuota", "metadata": {"name": "jobs", "namespace": "abc-rnd", "uid": "rq-uid", "resourceVersion": "8"},
          "spec": {"hard": {"pods": "12"}}}
    snap, _ = snapshot(ns, [rq], [], SETTINGS)
    files, _ = adopted_files(snap, Owner("CRC", "cmapi", "rnd", "custom", "r1", "amy", None), MetadataKeys({}))
    base = snap.files("CRC")
    stored = {"identity": snap.identity, "snapshot": base, "snapshotHash": snapshot_hash(base, snap.identity), "keys": [],
              "label": SETTINGS.label, "value": SETTINGS.value}
    row = SimpleNamespace(plugin="adoption", action="adopt", namespace="abc-rnd", request_id="r1", cluster_id="CRC",
                          status="pr_open", requirement={}, created_at=datetime.now(timezone.utc), plan={"adoption": stored, "files": files, "prev": {}}, plan_hash=plan_hash(files),
                          pr={"branch": "request", "head": "12345678", "number": 1, "url": "https://git.invalid/1"})
    ctx = Mock()
    ctx.pipeline.live_objects.side_effect = lambda cluster, name: (ns, [rq], [])
    ctx.git.branch_head.return_value = row.pr["head"]
    ctx.git.tree_files.return_value = files
    return ctx, row, ns, rq


def _apply(ctx, row, client, repo, jobs, *, resuming=False):
    client.get_object.side_effect = lambda kind, ns, name: ctx.pipeline.live_objects("CRC", name)[0]
    with patch.object(watch_sync, "_deliverer", return_value=client), \
            patch.object(apply_job, "apply_started", return_value=row.pr["head"] if resuming else None), \
            patch.object(apply_job, "mark_apply_started", return_value=True), \
            patch.object(apply_job, "confirmed_by_read", return_value=(True, "ok")):
        apply_job._apply(ctx, repo, jobs, row, SimpleNamespace(payload={}))


def _sent(client):
    return [(c.args[0]["kind"], c.args[0]["metadata"].get("uid"), c.args[0]["metadata"].get("resourceVersion"))
            for c in client.apply.call_args_list]


def test_each_adopted_object_is_written_with_the_uid_and_resource_version_of_the_plan():
    ctx, row, _, _ = _world()
    client, repo = Mock(), Mock()
    repo.events.return_value = []
    _apply(ctx, row, client, repo, Mock())
    assert _sent(client) == [("Namespace", "ns-uid", "7"), ("ResourceQuota", "rq-uid", "8")]


def test_an_object_changed_between_the_last_read_and_the_write_is_refused_and_nothing_is_written():
    """The window that head's comment called closed: the read passes, then the quota changes before the write."""
    ctx, row, ns, rq = _world()
    client, repo, jobs = Mock(), Mock(), Mock()
    repo.events.return_value = []
    jobs.fence.side_effect = lambda: rq["metadata"].update(resourceVersion="9")       # after the read, before the write
    written = []

    def api_server(doc):                       # the preconditions as the API server checks them
        current = ns if doc["kind"] == "Namespace" else rq
        if doc["metadata"].get("resourceVersion") not in (None, current["metadata"]["resourceVersion"]):
            raise KubeError(409, doc["metadata"]["name"], "the object has been modified")
        written.append(doc["kind"])

    client.apply.side_effect = api_server
    _apply(ctx, row, client, repo, jobs)
    assert "ResourceQuota" not in written
    assert "adoption-plan-stale" in repo.move.call_args.args[3]


def test_a_resumed_apply_skips_what_cmapi_wrote_and_refuses_a_replacement():
    ctx, row, ns, rq = _world()
    files = row.plan["files"]
    path = next(p for p in files if p.endswith("/namespace.yaml"))
    written = yaml.safe_load(files[path])
    written["metadata"].update(uid="ns-uid", resourceVersion="10")           # cmapi's own write moved it on
    ctx.pipeline.live_objects.side_effect = lambda cluster, name: (written, [rq], [])
    found, writes = delivery.adoption_writes(ctx, row, files, resuming=True)
    assert found is None and set(writes) == set(files) - {path}
    assert yaml.safe_load(next(iter(writes.values())))["metadata"]["resourceVersion"] == "8"
    written["metadata"]["uid"] = "another"                                     # deleted and made again
    found, writes = delivery.adoption_writes(ctx, row, files, resuming=True)
    assert found.code == "stale" and writes == {}


def test_a_resumed_apply_never_writes_over_a_change_made_by_someone_else():
    ctx, row, ns, rq = _world()
    rq["metadata"]["resourceVersion"], rq["spec"]["hard"]["pods"] = "11", "20"
    found, writes = delivery.adoption_writes(ctx, row, row.plan["files"], resuming=True)
    assert found.code == "stale" and writes == {}


def test_after_the_merge_a_namespace_that_is_gone_is_not_made_again():
    """Head checked the uid only of a present, unmanaged Namespace: a missing one was created from Git."""
    ctx, row, _, _ = _world()
    row.status, row.merge_sha, row.merged_at = "merged", "main", datetime.now(timezone.utc)
    ctx.pipeline.live_objects.side_effect = lambda cluster, name: (None, [], [])
    ctx.git.read_folder.return_value = row.plan["files"], "main"
    client, repo, jobs = Mock(), Mock(), Mock()
    client.get_object.return_value = None
    repo.get.return_value = row
    with patch.object(watch_sync, "RequestRepo", return_value=repo), patch.object(watch_sync, "JobRepo", return_value=jobs), \
            patch.object(watch_sync, "_mode", return_value="apply"), patch.object(watch_sync, "_deliverer", return_value=client), \
            patch.object(watch_sync, "confirmed_by_read", return_value=(True, "ok")):
        watch_sync.watch_sync(ctx, Mock(), Mock(payload={}, request_id=row.request_id))
    client.apply.assert_not_called()
    assert "adoption-plan-stale" in repo.move.call_args.args[3]


def test_after_the_merge_a_managed_replacement_namespace_is_refused_too():
    """A replacement that carries cmapi.net/managed skipped head's uid check."""
    ctx, row, ns, rq = _world()
    row.status, row.merge_sha, row.merged_at = "merged", "main", datetime.now(timezone.utc)
    ns["metadata"].update(uid="another", labels={"cmapi.net/adopt": "true", "cmapi.net/managed": "true"})
    ctx.git.read_folder.return_value = row.plan["files"], "main"
    client, repo, jobs = Mock(), Mock(), Mock()
    client.get_object.return_value = ns
    repo.get.return_value = row
    with patch.object(watch_sync, "RequestRepo", return_value=repo), patch.object(watch_sync, "JobRepo", return_value=jobs), \
            patch.object(watch_sync, "_mode", return_value="apply"), patch.object(watch_sync, "_deliverer", return_value=client), \
            patch.object(watch_sync, "confirmed_by_read", return_value=(True, "ok")):
        watch_sync.watch_sync(ctx, Mock(), Mock(payload={}, request_id=row.request_id))
    client.apply.assert_not_called()
    assert "adoption-plan-stale" in repo.move.call_args.args[3]
