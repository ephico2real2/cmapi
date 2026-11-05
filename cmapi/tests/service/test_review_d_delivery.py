"""C5, C6: what lands, what can be smuggled, what gets taken over."""
from __future__ import annotations

import yaml
import pytest
from sqlalchemy import text

from cmapi.core.db.repo import JobRepo, utcnow
from cmapi.jobs import HANDLERS
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs

PATH = "clusters/CRC/namespaces/payments-dev/"


def run_until(ctx, kind_stop, limit=10):
    """Run jobs until the next due job is kind_stop, leaving it unclaimed."""
    for _ in range(limit):
        with ctx.db.session() as s:
            nxt = s.execute(text("select kind from jobs where done_at is null and kind<>'approval_timeout' order by run_after, job_id limit 1")).scalar()
        if nxt in (None, kind_stop):
            return nxt
        with ctx.db.session() as s:
            j = JobRepo(s).claim("t")
            jid, k = j.job_id, j.kind
        with ctx.db.session() as s:
            j = s.get(type(j), jid)
            HANDLERS[k](ctx, s, j)
            if j.done_at is None:
                j.locked_until, j.run_after = None, utcnow()
    return None


def status(client, keys, rid):
    return client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()


def test_namespace_created_by_someone_else_after_the_plan_is_not_taken_over(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    kube.add_unmanaged_namespace("payments-dev")          # another project's namespace appears before delivery
    kube.objects[("Namespace", "", "payments-dev")]["metadata"]["labels"] = {"owner": "other-project"}
    run_jobs(ctx)
    live = kube.objects[("Namespace", "", "payments-dev")]["metadata"]["labels"]
    assert live == {"owner": "other-project"}, f"labels now {live}, applied {kube.applied}"
    assert not [a for a in kube.applied if "payments-dev" in a], kube.applied
    assert status(client, keys, rid)["status"] != "synced"


def test_prune_refuses_a_namespace_that_is_not_managed(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    run_jobs(ctx)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    rid = client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY))
    run_jobs(ctx)
    assert status(client, keys, rid)["status"] == "awaiting_prune"
    # somebody replaced it: the live namespace no longer carries the managed label
    kube.objects[("Namespace", "", "payments-dev")]["metadata"]["labels"] = {"owner": "other-project"}
    assert client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev"}, headers=auth(keys, "opal", **OPAL)).status_code == 200
    run_jobs(ctx, limit=3)
    assert ("Namespace", "", "payments-dev") in kube.objects, "an unmanaged namespace was deleted"


@pytest.mark.parametrize("where", ["clusters/CRC/namespaces/victim/rolebindings.yaml", "clusters/OTHER/namespaces/x/namespace.yaml",
                                   ".github/workflows/x.yml"])
def test_a_file_pushed_outside_the_folder_after_approval_is_refused(world, where):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "pr_checks") == "pr_checks"
    branch = git.prs[1]["branch"]
    git.tamper(branch, where, "kind: RoleBinding\nsmuggled: true\n")
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "failed", f"status {v['status']}, smuggled file on main: {where in git.branches['main']}"
    assert where not in git.branches["main"]


def test_body_values_cannot_inject_yaml(world):
    client, ctx, git, kube, validator, keys = world
    evil = "x\n---\napiVersion: v1\nkind: Namespace\nmetadata: {name: kube-system}\n"
    r = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json={**NS, "annotations": {**NS["annotations"], "note": evil}},
                    headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    docs = list(yaml.safe_load_all(r.json()["files"][PATH + "namespace.yaml"]))
    assert len(docs) == 1 and docs[0]["metadata"]["name"] == "payments-dev" and docs[0]["metadata"]["annotations"]["note"] == evil


@pytest.mark.parametrize("name", ["../other", "a/b", "A", "x" * 64, "-x", "x-", ".", "..", "kube-system", "openshift-x", "default", "cmapi-system", "cmapi-imports"])
def test_create_refuses_names(world, name):
    client, ctx, git, kube, validator, keys = world
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": name}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422, (name, r.status_code)


@pytest.mark.parametrize("key,val", [("kubernetes.io/metadata.name", "x"), ("pod-security.kubernetes.io/enforce", "privileged"),
                                     ("openshift.io/node-selector", "x"), ("argocd.argoproj.io/managed-by", "x"),
                                     ("cmapi.net/managed", "false"), ("security.openshift.io/scc.podSecurityLabelSync", "false")])
def test_reserved_metadata_refused(world, key, val):
    client, ctx, git, kube, validator, keys = world
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "labels": {**NS["labels"], key: val}}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422, (key, r.status_code)
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "annotations": {**NS["annotations"], key: val}}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422, (key, r.status_code)


@pytest.mark.parametrize("ns", ["%2e%2e", "..", "foo%2Fbar", "UPPER", "kube-system"])
def test_paths_with_odd_namespace_never_reach_outside_the_folder(world, ns):
    client, ctx, git, kube, validator, keys = world
    seen = []
    real = git.read_folder
    git.read_folder = lambda path, ref=None: (seen.append(path), real(path, ref))[1]
    h = {**auth(keys, "ola", **OLA), "If-Match": "0"}
    for m in ("PATCH", "DELETE"):
        r = client.request(m, f"/api/v1/clusters/CRC/namespaces/{ns}", headers=h, **({"json": {"tier": "medium"}} if m == "PATCH" else {}))
        assert r.status_code in (404, 422), (m, ns, r.status_code)
    for p in seen:
        assert ".." not in p, f"read_folder asked for {p}"


def test_username_that_cannot_be_a_label_is_refused_at_plan_time(world):
    client, ctx, git, kube, validator, keys = world
    r = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "John Doe@corp", **OLA))
    assert r.status_code == 422, f"{r.status_code}: the label value would be refused only at apply"


def test_quota_read_back_in_canonical_form_still_confirms(world):
    """The API server returns quantities canonicalised: 5120Mi reads back as 5Gi."""
    client, ctx, git, kube, validator, keys = world
    real = kube.apply

    def apply(doc, field_manager="cmapi-deliverer"):
        obj = real(doc, field_manager)
        if doc["kind"] == "ResourceQuota":
            hard = obj["spec"]["hard"] = dict(obj["spec"]["hard"])
            for k, v in hard.items():
                if v == "5120Mi":
                    hard[k] = "5Gi"
        return obj
    kube.apply = apply
    q = {"requests.cpu": "2", "requests.memory": "5120Mi", "pods": "20"}
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "tier": "custom", "quota": q}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    rid = r.json()["requestId"]
    client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY))
    ctx.delivery = type(ctx.delivery)(mode="apply", poll_seconds=0, sync_timeout_seconds=0)
    run_jobs(ctx)
    v = status(client, keys, rid)
    assert v["status"] == "synced", [e["note"] for e in v["events"]][-2:]


def test_revert_of_a_create_goes_through_prune_and_leaves_no_orphan(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed' where request_id=:r"), {"r": rid})
        s.execute(text("delete from jobs where kind='watch_sync'"))
    for d in ({"kind": "Namespace", "metadata": {"name": "payments-dev", "labels": {"cmapi.net/managed": "true"}}},):
        kube.apply(d)
    r = client.post(f"/api/v1/requests/{rid}:revert", headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 200, r.text
    run_jobs(ctx)
    with ctx.db.session() as s:
        row = s.execute(text("select request_id, status, action from change_requests where request_id<>:r"), {"r": rid}).first()
    assert row is not None, "no revert request"
    if row.status == "pending_approval":
        assert client.post(f"/api/v1/requests/{row.request_id}:approve", json={}, headers=auth(keys, "amy", **AMY)).status_code == 200
        run_jobs(ctx)
        with ctx.db.session() as s:
            row = s.execute(text("select request_id, status, action from change_requests where request_id<>:r"), {"r": rid}).first()
    assert "clusters/CRC/namespaces/payments-dev/namespace.yaml" not in git.branches["main"]
    # a namespace with no folder in Git, no quota, and a request saying synced is the orphan
    assert not (row.status == "synced" and ("Namespace", "", "payments-dev") in kube.objects), (row.status, row.action)


def test_main_differing_from_the_plan_is_not_applied(world):
    """docs: the worker applies only what Git main holds. A direct push to main after the merge must stop the delivery."""
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    git.tamper("main", PATH + "resourcequota.yaml", "kind: ResourceQuota\nedited: true\n")
    run_jobs(ctx)
    assert kube.applied == [], kube.applied
    assert status(client, keys, rid)["status"] == "sync_failed"


def test_prune_confirm_refuses_an_ambiguous_namespace(world):
    client, ctx, git, kube, validator, keys = world
    from test_review_e_recovery import OPAL as _O
    with ctx.db.session() as s:
        for rid, cid in (("r-a", "AAA"), ("r-b", "CRC")):
            s.execute(text("""insert into change_requests(request_id,instance,cluster_id,namespace,env,plugin,action,status,plan,plan_hash,requester,requester_sub,requester_kind,requester_client,requester_username)
                values (:r,'nonprod',:c,'twin','dev','namespaces','delete','awaiting_prune','{"files":{},"prev":{}}'::jsonb,'h','{"requester":{"username":"x","kind":"user"}}'::jsonb,'s','user','c','x')"""), {"r": rid, "c": cid})
    r = client.post("/api/v1/admin/prune:confirm", json={"namespace": "twin"}, headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 422, f"{r.status_code}: picked one of two clusters"
