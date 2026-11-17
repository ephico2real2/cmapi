"""#366: a change that does not name cmapi.net/protected keeps it; only an operator removes it."""
import yaml
from test_flow import NS, OLA, OPAL, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces/payments-dev"


def _etag(client, keys):
    return client.get(URL, headers=auth(keys, "ola", **OLA)).json()["etag"]


def _protected(git):
    doc = yaml.safe_load(git.branches["main"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"])
    return doc["metadata"]["labels"].get("cmapi.net/protected")


def test_a_requester_change_keeps_protection_and_the_delete_stays_refused(world):
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)); run_jobs(ctx)
    r = client.patch(URL, json={"labels": {"cmapi.net/protected": "true"}},
                     headers={**auth(keys, "opal", **OPAL), "If-Match": _etag(client, keys)})
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    assert _protected(git) == "true"
    r = client.patch(URL, json={"labels": {"cmapi.net/cost-center": "cc-9999"}},
                     headers={**auth(keys, "ola", **OLA), "If-Match": _etag(client, keys)})
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    assert _protected(git) == "true"
    r = client.delete(URL, headers={**auth(keys, "ola", **OLA), "If-Match": _etag(client, keys)})
    assert r.status_code == 422 and r.json()["type"].endswith("/namespace-protected"), r.text
    r = client.patch(URL, json={"labels": {"cmapi.net/protected": None}},
                     headers={**auth(keys, "opal", **OPAL), "If-Match": _etag(client, keys)})
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    assert _protected(git) is None
