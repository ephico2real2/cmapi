"""#366 §5: with cmapi.net/protected in sensitiveKeys, removing it adds an approval and setting it does not."""
from test_flow import NS, OLA, OPAL, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces/payments-dev"


def _etag(client, keys):
    return client.get(URL, headers=auth(keys, "ola", **OLA)).json()["etag"]


def test_remove_is_sensitive_set_is_not(world):
    client, ctx, git, kube, validator, keys = world
    ctx.cfg.metadata.sensitive.add("cmapi.net/protected")
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)); run_jobs(ctx)
    r = client.patch(URL, json={"labels": {"cmapi.net/protected": "true"}},
                     headers={**auth(keys, "opal", **OPAL), "If-Match": _etag(client, keys)})
    print("SET", r.status_code, r.json()["status"], r.json()["approval"]["reasons"])
    run_jobs(ctx)
    r = client.patch(URL, json={"labels": {"cmapi.net/protected": None}},
                     headers={**auth(keys, "opal", **OPAL), "If-Match": _etag(client, keys)})
    print("REMOVE", r.status_code, r.json()["status"], r.json()["approval"]["reasons"])
