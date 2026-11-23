"""#607 review: a write that has a dry run takes `dryRun` once.

FastAPI binds a scalar query parameter to one value, the last (Starlette's QueryParams), so before the fix
`dryRun=true&dryRun=false` opened a real request on each of the six writes, and the reverse order was a preview. A client
whose HTTP layer adds `dryRun=false` to a preview would have written. Now more than one `dryRun` is 422 `validation-failed`,
as `dryRun=maybe` is, and nothing is submitted (Kubernetes: a dryRun value that a call does not accept is 422 Invalid,
apiserver endpoints/handlers/create.go, ValidateCreateOptions).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from test_flow import AMY, NS, OLA, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces"


def created(world, name: str, **extra) -> str:
    """A namespace in Git and on the cluster; its etag."""
    client, ctx, *_, keys = world
    r = client.post(URL, json={**NS, "namespace": name, **extra}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    if r.json()["status"] == "pending_approval":
        client.post(f"/api/v1/requests/{r.json()['requestId']}:approve", json={}, headers=auth(keys, "amy", **AMY))
    run_jobs(ctx)
    ctx.registry.cache("CRC")._list("Namespace")
    return client.get(f"{URL}/{name}", headers=auth(keys, "ola", **OLA)).json()["etag"]


def requests(ctx) -> int:
    with ctx.db.session() as s:
        return s.execute(text("SELECT count(*) FROM change_requests")).scalar_one()


def the_six(world) -> list[tuple[str, str, dict | None, str | None]]:
    """(method, path, body, etag) of each write with a dry run, each one that would be accepted on its own."""
    dated = created(world, "payments-dev", expiresAt=(date.today() + timedelta(days=10)).isoformat())
    permanent = created(world, "orders-dev")
    one, other = f"{URL}/payments-dev", f"{URL}/orders-dev"
    return [("POST", URL, {**NS, "namespace": "ledger-dev"}, None),
            ("PATCH", one, {"labels": {"cmapi.net/cost-center": "cc-4411"}}, dated),
            ("DELETE", one, None, dated),
            ("POST", f"{one}/expiration:extend", {"days": 5}, dated),
            ("POST", f"{other}/expiration:set", {"until": (date.today() + timedelta(days=20)).isoformat()}, permanent),
            ("POST", f"{one}/expiration:makePermanent", {}, dated)]


def test_a_repeated_dry_run_is_refused_on_each_write_and_submits_nothing(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    writes = the_six(world)
    submitted = []
    monkeypatch.setattr("cmapi.plugins.namespaces.router._submit", lambda *a, **k: submitted.append(a) or {})
    before = requests(ctx)
    for method, path, body, etag in writes:
        for query in ("dryRun=true&dryRun=false", "dryRun=false&dryRun=true", "dryRun=true&dryRun=true"):
            headers = auth(keys, "ola", **OLA) | ({"If-Match": f'"{etag}"'} if etag else {})
            r = client.request(method, f"{path}?{query}", json=body, headers=headers)
            assert not submitted, f"{method} {path}?{query} reached _submit: the last dryRun decided, and it wrote"
            assert (r.status_code, r.json()["code"]) == (422, "validation-failed"), (method, path, query, r.text)
            assert r.json()["errors"] == [{"field": "query.dryRun", "message": "send it at most once",
                                           "code": "too_many_values"}], r.text
    assert requests(ctx) == before


def test_one_dry_run_is_read_as_fastapi_reads_a_boolean(world):
    """One `dryRun` is unchanged: `1` is a preview, an empty value is 422 as before, and each write still previews."""
    client, ctx, git, kube, validator, keys = world
    before = requests(ctx)
    for method, path, body, etag in the_six(world):
        headers = auth(keys, "ola", **OLA) | ({"If-Match": f'"{etag}"'} if etag else {})
        for query, status in (("dryRun=true", 200), ("dryRun=1", 200), ("dryRun=", 422)):
            r = client.request(method, f"{path}?{query}", json=body, headers=headers)
            assert r.status_code == status, (method, path, query, r.text)
            if status == 200:
                assert "planHash" in r.json() and "requestId" not in r.json(), r.text
    assert requests(ctx) == before + 2               # the two namespaces that the_six created, and nothing else


def test_the_document_says_dry_run_is_sent_once(world):
    client, *_ = world
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/api/v1/clusters/{cluster_id}/namespaces/{ns}"]["delete"]
    dry = next(p for p in op["parameters"] if p["name"] == "dryRun")["description"]
    assert "at most once" in dry and "422 `validation-failed`" in dry, dry
    assert "validation-failed" in op["responses"]["422"]["content"]["application/problem+json"]["examples"]
    assert "writes nothing" not in op["responses"]["200"]["description"]
    assert "opens no change request" in op["responses"]["200"]["description"]
