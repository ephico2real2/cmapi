"""The sample request and response of each operation, taken from a run and not written by hand (docs/04, the OpenAPI examples).

One scenario walks the whole API on the service suite's world: a namespace from a dry run to synced, a change that
needs an approval, a rejection, a cancellation, a failed request and its retry, a sync failure and its revert, a delete
to its prune, and each read. A recorder keeps one sample for each operationId and one for each problem code it meets.

cmapi/src/cmapi/contract/samples.json holds them. Values such as request IDs, times, etags and cursors differ at each
run, so this test compares the shape of each sample (keys and types) with the committed file, and fails when an
operation has no sample. To write the file again after a change to the API: CMAPI_WRITE_SAMPLES=1 with this test,
then CMAPI_WRITE_CONTRACT=1 with test_api_docs.py (the examples are in the OpenAPI document), then scripts/api-examples-doc.py.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from cmapi.core.identity.claims import Person
from cmapi.core.identity.directory import CachedDirectory, InMemoryDirectory
from test_flow import AMY, NS, OLA, OPAL, run_jobs

SAMPLES = Path(__file__).resolve().parents[2] / "src" / "cmapi" / "contract" / "samples.json"
ADMIN = dict(roles=["cmapi-admin"], groups=["/cmapi/app-cmapi-rbac-admin"])


class Recorder:
    def __init__(self, client, keys):
        self.client, self.keys = client, keys
        self.operations: dict[str, dict[str, Any]] = {}
        self.problems: dict[str, dict[str, Any]] = {}

    def call(self, op: str, method: str, path: str, who: tuple[str, dict] | None, *, json_body: Any = None,
             headers: dict[str, str] | None = None, key: bool = False, keep: bool = True):
        """One call. The token never goes into a sample: the Authorization header is recorded as `Bearer $TOKEN`."""
        sent = dict(headers or {})
        if key:
            sent["Idempotency-Key"] = str(uuid.uuid4())
        real = dict(sent)
        if who is not None:
            real["Authorization"] = f"Bearer {self.keys.token(who[0], **who[1])}"
            sent = {"Authorization": "Bearer $TOKEN", **sent}
        r = self.client.request(method, path, json=json_body, headers=real)
        kind = r.headers.get("content-type", "").split(";")[0]
        body: Any = r.json() if kind.endswith("json") else r.text
        sample = {"request": {"method": method, "path": path, "headers": sent, **({"body": json_body} if json_body is not None else {})},
                  "response": {"status": r.status_code, "contentType": kind,
                               "headers": {k: r.headers[k] for k in ("etag", "www-authenticate", "content-disposition") if k in r.headers},
                               "body": body}}
        if kind == "application/problem+json":
            self.problems.setdefault(body["code"], {"operationId": op, **sample})
        elif keep:
            self.operations.setdefault(op, sample)
        return r


# GET /admin/kpi reports each figure as a number, or as the text "unavailable" where the machine cannot measure it (a Mac has no
# cgroup files, a Linux runner does). So for that one sample only the keys are compared, not the type of each value.
MEASURED_OR_UNAVAILABLE = {"admin_kpi"}


def shape(value: Any, keys_only: bool = False) -> Any:
    """Keys and types, without the values: what a sample must keep from one run to the next."""
    if isinstance(value, dict):
        return {k: shape(v, keys_only) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0], keys_only)] if value else []
    return "value" if keys_only else type(value).__name__


def shapes(data: dict[str, Any]) -> dict[str, Any]:
    return {kind: {name: shape(sample, keys_only=name in MEASURED_OR_UNAVAILABLE) for name, sample in data[kind].items()}
            for kind in ("operations", "problems")}


def differences(a: Any, b: Any, path: str = "") -> list[str]:
    """Where two shapes differ, as paths: the assertion's own diff of two large dicts does not show it."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = [f"{path}.{k}: only in the committed file" for k in a.keys() - b.keys()]
        out += [f"{path}.{k}: only in this run" for k in b.keys() - a.keys()]
        for k in a.keys() & b.keys():
            out += differences(a[k], b[k], f"{path}.{k}")
        return sorted(out)
    if isinstance(a, list) and isinstance(b, list) and a and b:
        return differences(a[0], b[0], f"{path}[0]")
    return [] if a == b else [f"{path}: committed {a!r}, this run {b!r}"]


def test_each_operation_has_a_sample_from_a_run(world):
    client, ctx, git, kube, validator, keys = world
    people = [Person(username="ola", email="ola@ephico2real.com", sub="sub-ola", given_name="Ola", family_name="Adeyemi", employee_id="1001"),
              Person(username="amy", email="amy@ephico2real.com", sub="sub-amy", given_name="Amy", family_name="Lee", employee_id="1002")]
    ctx.directory = ctx.pipeline.directory = CachedDirectory(InMemoryDirectory(people))
    rec = Recorder(client, keys)
    ola, amy, opal, admin = ("ola", OLA), ("amy", AMY), ("opal", OPAL), ("ada", ADMIN)
    base = "/api/v1/clusters/CRC/namespaces"

    # ---- reads that need nothing
    rec.call("core_version", "GET", "/api/v1/version", None)
    rec.call("core_me", "GET", "/api/v1/me", ola)
    rec.call("core_clusters", "GET", "/api/v1/clusters", ola)
    rec.call("tiers_tiers", "GET", "/api/v1/tiers?environment=dev", ola)
    rec.call("directory_search", "GET", "/api/v1/directory/users?q=ola", ola)
    rec.call("directory_get_user", "GET", "/api/v1/directory/users/ola", ola)
    rec.call("admin_integrations", "GET", "/api/v1/admin/integrations", ola)
    rec.call("admin_switch_state", "GET", "/api/v1/admin/auto-approval", ola)

    # ---- a namespace: the dry run, the create, then the worker to synced
    rec.call("namespaces_create_namespace:dryRun", "POST", f"{base}?dryRun=true", ola, json_body=NS)
    created = rec.call("namespaces_create_namespace", "POST", base, ola, json_body=NS, key=True)
    assert created.status_code == 202, created.text
    rid = created.json()["requestId"]
    run_jobs(ctx)
    rec.call("requests_get_request", "GET", f"/api/v1/requests/{rid}", ola)
    rec.call("requests_get_events", "GET", f"/api/v1/requests/{rid}/events", ola)
    rec.call("requests_approval_status", "GET", f"/api/v1/requests/{rid}/approval-status", ola)
    for kind in ("Namespace", "ResourceQuota"):               # the fake cluster's watch does not stream: read the cache's lists again, as test_flow does
        ctx.registry.cache("CRC")._list(kind)
    rec.call("namespaces_list_namespaces", "GET", base, ola)
    one = rec.call("namespaces_get_namespace", "GET", f"{base}/payments-dev", ola)
    etag = one.json()["etag"]
    rec.call("quotas_quotas", "GET", "/api/v1/quotas?limit=25", ola)
    rec.call("quotas_suggest", "GET", "/api/v1/quotas:suggest?q=pay", ola)
    rec.call("quotas_export", "GET", "/api/v1/quotas:export", ola)
    rec.call("admin_git_log", "GET", "/api/v1/admin/git-log", opal)
    rec.call("admin_kpi", "GET", "/api/v1/admin/kpi", opal)

    # ---- a change that needs an approval, and its approval
    change = rec.call("namespaces_update_namespace", "PATCH", f"{base}/payments-dev", ola, json_body={"tier": "large", "justification": "Load test next sprint"},
                      headers={"If-Match": f'"{etag}"'}, key=True)
    assert change.status_code == 202 and change.json()["status"] == "pending_approval", change.text
    rec.call("requests_list_requests", "GET", "/api/v1/requests?status=pending_approval&approver=me", amy)
    approved = rec.call("requests_approve", "POST", f"/api/v1/requests/{change.json()['requestId']}:approve", amy, json_body={"comment": "sizing reviewed"})
    assert approved.status_code == 200, approved.text
    run_jobs(ctx)

    # ---- a namespace with an expiry, and an extension of it; then a request that is rejected, and one that its requester cancels
    from datetime import date, timedelta
    sprint = client.post(base, json={**NS, "namespace": "sprint-dev", "expiresAt": (date.today() + timedelta(days=20)).isoformat()},
                         headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}", "Idempotency-Key": str(uuid.uuid4())})
    assert sprint.status_code == 202, sprint.text
    if sprint.json()["status"] == "pending_approval":
        client.post(f"/api/v1/requests/{sprint.json()['requestId']}:approve", json={}, headers={"Authorization": f"Bearer {keys.token('amy', **AMY)}"})
    run_jobs(ctx)
    etag = client.get(f"{base}/sprint-dev", headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}"}).json()["etag"]
    ext = rec.call("namespaces_extend", "POST", f"{base}/sprint-dev/expiration:extend", ola, json_body={"days": 7, "justification": "Another sprint"},
                   headers={"If-Match": f'"{etag}"'}, key=True)
    assert ext.status_code == 202, ext.text
    if ext.json()["status"] == "pending_approval":
        rec.call("requests_reject", "POST", f"/api/v1/requests/{ext.json()['requestId']}:reject", amy, json_body={"comment": "Ask again nearer the date"})
    run_jobs(ctx)
    second = client.post(base, json={**NS, "namespace": "ledger-dev", "tier": "large"},
                         headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}", "Idempotency-Key": str(uuid.uuid4())})
    assert second.status_code == 202 and second.json()["status"] == "pending_approval", second.text
    if "requests_reject" not in rec.operations:
        third = client.post(base, json={**NS, "namespace": "billing-dev", "tier": "large"},
                            headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}", "Idempotency-Key": str(uuid.uuid4())})
        rec.call("requests_reject", "POST", f"/api/v1/requests/{third.json()['requestId']}:reject", amy, json_body={"comment": "Use the medium tier"})
    rec.call("requests_cancel", "POST", f"/api/v1/requests/{second.json()['requestId']}:cancel", ola)

    # ---- the kill switch
    rec.call("admin_pause", "POST", "/api/v1/admin/auto-approval:pause", admin, json_body={"reason": "incident 1234"})
    rec.call("admin_resume", "POST", "/api/v1/admin/auto-approval:resume", admin, json_body={"reason": "incident 1234 closed"})

    # ---- a request whose pull request was changed by someone else fails; an operator retries it
    run_jobs(ctx)
    failing = client.post(base, json={**NS, "namespace": "search-dev"},
                          headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}", "Idempotency-Key": str(uuid.uuid4())})
    frid = failing.json()["requestId"]
    if failing.json()["status"] == "pending_approval":        # the day's auto-approvals for the team are used up
        client.post(f"/api/v1/requests/{frid}:approve", json={}, headers={"Authorization": f"Bearer {keys.token('amy', **AMY)}"})
    for _ in range(6):                                        # one job at a time, until the pull request is open and not yet checked
        ran = run_jobs(ctx, limit=1)
        if ran == ["open_pr"] or not ran:
            break
    view = client.get(f"/api/v1/requests/{frid}", headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}"}).json()
    assert view["pr"], view["status"]
    path = "clusters/CRC/namespaces/search-dev/resourcequota.yaml"
    git.tamper(view["pr"]["branch"], path, git.branches[view["pr"]["branch"]][path].replace("requests.cpu: '8'", "requests.cpu: '80'"))
    run_jobs(ctx)
    retried = rec.call("requests_retry", "POST", f"/api/v1/requests/{frid}:retry", opal)
    assert retried.status_code == 200, retried.text
    run_jobs(ctx)

    # ---- revert is only for a request whose sync failed: on a synced one it is refused, and that refusal is the sample of invalid-transition
    rec.call("requests_revert", "POST", f"/api/v1/requests/{frid}:revert", opal)

    # ---- a delete: approved, merged, then the prune that an operator confirms
    etag = client.get(f"{base}/search-dev", headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}"}).json()["etag"]
    deleted = rec.call("namespaces_delete_namespace", "DELETE", f"{base}/search-dev", ola, headers={"If-Match": f'"{etag}"'}, key=True)
    assert deleted.status_code == 202, deleted.text
    client.post(f"/api/v1/requests/{deleted.json()['requestId']}:approve", json={}, headers={"Authorization": f"Bearer {keys.token('amy', **AMY)}"})
    run_jobs(ctx)
    pruned = rec.call("admin_prune_confirm", "POST", "/api/v1/admin/prune:confirm", opal, json_body={"namespace": "search-dev", "clusterId": "CRC"})
    assert pruned.status_code == 200, pruned.text
    run_jobs(ctx)

    # ---- a request whose sync fails, and its revert: another party makes the namespace on the cluster after the plan, so the
    # delivery refuses to take it over (jobs/watch_sync.py), and an operator reverts the request
    lost = client.post(base, json={**NS, "namespace": "orders-dev"},
                       headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}", "Idempotency-Key": str(uuid.uuid4())})
    assert lost.status_code == 202, lost.text
    lrid = lost.json()["requestId"]
    if lost.json()["status"] == "pending_approval":
        client.post(f"/api/v1/requests/{lrid}:approve", json={}, headers={"Authorization": f"Bearer {keys.token('amy', **AMY)}"})
    kube.add_unmanaged_namespace("orders-dev")
    run_jobs(ctx)
    state = client.get(f"/api/v1/requests/{lrid}", headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}"}).json()
    assert state["status"] == "sync_failed", state["status"]
    reverted = rec.call("requests_revert", "POST", f"/api/v1/requests/{lrid}:revert", opal)
    assert reverted.status_code == 200, reverted.text
    run_jobs(ctx)

    # ---- the dry run of a change: the plan of a PATCH, with nothing written
    etag = client.get(f"{base}/payments-dev", headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}"}).json()["etag"]
    planned = rec.call("namespaces_update_namespace:dryRun", "PATCH", f"{base}/payments-dev?dryRun=true", ola,
                       json_body={"tier": "medium", "justification": "A smaller size after the load test"}, headers={"If-Match": f'"{etag}"'})
    assert planned.status_code == 200, planned.text

    # ---- the refusals a client meets most
    rec.call("core_me", "GET", "/api/v1/me", None)                                                            # 401
    rec.call("admin_pause", "POST", "/api/v1/admin/auto-approval:pause", ola, json_body={"reason": "x"})     # 403
    rec.call("requests_get_request", "GET", "/api/v1/requests/req-00000000-0000", ola)                        # 404
    rec.call("namespaces_create_namespace", "POST", base, ola, json_body=NS)                                  # 400: no Idempotency-Key
    rec.call("namespaces_create_namespace", "POST", base, ola, json_body=NS, key=True)                        # 409: exists
    rec.call("namespaces_update_namespace", "PATCH", f"{base}/payments-dev", ola, json_body={"tier": "small"}, key=True)   # 428
    rec.call("namespaces_update_namespace", "PATCH", f"{base}/payments-dev", ola, json_body={"tier": "small"}, headers={"If-Match": '"stale"'}, key=True)  # 412
    rec.call("namespaces_create_namespace", "POST", base, ola, json_body={**NS, "namespace": "kube-tools"}, key=True)      # 422 reserved
    rec.call("quotas_quotas", "GET", "/api/v1/quotas?sort=nope", ola)                                         # 400 invalid-sort

    data = {"operations": dict(sorted(rec.operations.items())), "problems": dict(sorted(rec.problems.items()))}
    spec = client.get("/openapi.json").json()
    wanted = {op["operationId"] for ops in spec["paths"].values() for op in ops.values()}
    have = {k.split(":")[0] for k in rec.operations} | {p["operationId"] for p in rec.problems.values()}
    assert wanted - have == set(), f"no sample for {sorted(wanted - have)}"
    # A refusal that a client meets must be one that the operation's documentation names.
    by_id = {op["operationId"]: op for ops in spec["paths"].values() for op in ops.values()}
    undeclared = [f"{p['operationId']}: {code}" for code, p in rec.problems.items()
                  if code not in ((by_id[p["operationId"]]["responses"].get(str(p["response"]["status"])) or {})
                                  .get("content", {}).get("application/problem+json", {}).get("examples", {}))]
    assert undeclared == [], f"an operation answered a problem that its documentation does not declare: {undeclared}"
    if os.environ.get("CMAPI_WRITE_SAMPLES") == "1":
        SAMPLES.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    committed = json.loads(SAMPLES.read_text())
    changed = differences(shapes(committed), shapes(json.loads(json.dumps(data))))
    assert changed == [], ("the samples changed shape: run this test with CMAPI_WRITE_SAMPLES=1, then the two steps in this file's "
                           "docstring. Where: " + "; ".join(changed[:12]))
    assert "Bearer ey" not in SAMPLES.read_text(), "a token is in the samples"
