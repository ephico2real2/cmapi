"""Probes for #366 design B: what the API does today with cmapi.net/protected."""
import yaml
from test_flow import NS, OLA, OPAL, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces"


def _ns_labels(git):
    return yaml.safe_load(git.branches["main"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"])["metadata"]["labels"]


def _etag(client, keys):
    return client.get(f"{URL}/payments-dev", headers=auth(keys, "ola", **OLA)).json()["etag"]


def test_probe_requester_create_with_protected_is_403(world):
    client, ctx, git, kube, validator, keys = world
    body = {**NS, "labels": {**NS["labels"], "cmapi.net/protected": "true"}}
    r = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    print("requester create protected:", r.status_code, r.json().get("type"), r.json().get("detail"))


def test_probe_requester_do_not_delete(world):
    client, ctx, git, kube, validator, keys = world
    body = {**NS, "labels": {**NS["labels"], "do-not-delete": "true"}}
    r = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    print("requester create do-not-delete:", r.status_code)
    run_jobs(ctx)
    r = client.delete(f"{URL}/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": _etag(client, keys)})
    print("requester delete of do-not-delete ns:", r.status_code, r.json().get("type"))


def test_probe_operator_protects_then_requester_patch(world):
    client, ctx, git, kube, validator, keys = world
    client.post(URL, json=NS, headers=auth(keys, "ola", **OLA)); run_jobs(ctx)
    r = client.patch(f"{URL}/payments-dev", json={"labels": {"cmapi.net/protected": "true"}},
                     headers={**auth(keys, "opal", **OPAL), "If-Match": _etag(client, keys)})
    print("operator protect PATCH:", r.status_code, r.json().get("status"), r.json().get("approval"))
    run_jobs(ctx)
    print("labels after protect:", _ns_labels(git).get("cmapi.net/protected"))
    r = client.delete(f"{URL}/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": _etag(client, keys)})
    print("delete while protected:", r.status_code, r.json().get("type"))
    r = client.patch(f"{URL}/payments-dev", json={"labels": {"cmapi.net/cost-center": "cc-9999"}},
                     headers={**auth(keys, "ola", **OLA), "If-Match": _etag(client, keys)})
    print("requester unrelated PATCH:", r.status_code, r.json().get("status"))
    run_jobs(ctx)
    print("labels after requester PATCH:", _ns_labels(git).get("cmapi.net/protected"))
    r = client.delete(f"{URL}/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": _etag(client, keys)})
    print("delete after requester PATCH:", r.status_code, r.json().get("type"), r.json().get("status"))


def test_probe_operator_unprotect_with_none(world):
    client, ctx, git, kube, validator, keys = world
    client.post(URL, json=NS, headers=auth(keys, "ola", **OLA)); run_jobs(ctx)
    client.patch(f"{URL}/payments-dev", json={"labels": {"cmapi.net/protected": "true"}},
                 headers={**auth(keys, "opal", **OPAL), "If-Match": _etag(client, keys)}); run_jobs(ctx)
    r = client.patch(f"{URL}/payments-dev", json={"labels": {"cmapi.net/protected": None}},
                     headers={**auth(keys, "ola", **OLA), "If-Match": _etag(client, keys)})
    print("requester unprotect (null):", r.status_code, r.json().get("type"))
    r = client.patch(f"{URL}/payments-dev", json={"labels": {"cmapi.net/protected": "false"}},
                     headers={**auth(keys, "opal", **OPAL), "If-Match": _etag(client, keys)})
    print("operator protected=false:", r.status_code, r.json().get("type"), r.json().get("errors") or r.json().get("detail"))


def test_probe_me(world):
    client, ctx, git, kube, validator, keys = world
    me = client.get("/api/v1/me", headers=auth(keys, "opal", **OPAL)).json()
    print("me keys:", sorted(me), "access keys:", sorted(me["access"]))
