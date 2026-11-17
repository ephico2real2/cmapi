"""PROBE (not committed): does a PATCH that does not resend cmapi.net/protected drop it from Git?"""
import yaml
from test_flow import NS, OLA, OPAL, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces"
ONE = f"{URL}/payments-dev"


def ns_yaml(files):
    return yaml.safe_load(next(t for p, t in files.items() if p.endswith("/namespace.yaml")))


def test_probe(world):
    client, ctx, git, kube, validator, keys = world
    body = {**NS, "labels": {**NS["labels"], "cmapi.net/protected": "true"}}
    r = client.post(URL, json=body, headers=auth(keys, "opal", **OPAL))
    print("create", r.status_code, r.json().get("status"), r.json().get("code"))
    run_jobs(ctx)
    g = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()
    git_ns = yaml.safe_load(git.branches["main"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"])
    print("git labels", git_ns["metadata"]["labels"])
    etag = g["etag"]
    d = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    print("delete", d.status_code, d.json().get("code"))
    p = client.patch(ONE + "?dryRun=true", json={"labels": {"cmapi.net/cost-center": "cc-9999"}},
                     headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    print("requester patch", p.status_code)
    plan = p.json()
    print("protected kept after a requester PATCH:", "cmapi.net/protected" in ns_yaml(plan["files"])["metadata"]["labels"])
    print("approval", plan["approval"]["rule"], plan["approval"]["auto"], plan["approval"]["reasons"])
    u = client.patch(ONE + "?dryRun=true", json={"labels": {"cmapi.net/protected": None}},
                     headers={**auth(keys, "opal", **OPAL), "If-Match": etag})
    print("operator unprotect", u.status_code, u.json().get("approval", {}).get("auto"), u.json().get("approval", {}).get("reasons"))
    rq = client.patch(ONE + "?dryRun=true", json={"labels": {"cmapi.net/protected": None}},
                      headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    print("requester unprotect", rq.status_code, rq.json().get("code"))
    dnd = client.patch(ONE + "?dryRun=true", json={"labels": {"do-not-delete": "true"}},
                       headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    print("requester do-not-delete", dnd.status_code, dnd.json().get("code"), dnd.json().get("errors"))
    print("operator-ok me", sorted(client.get("/api/v1/me", headers=auth(keys, "opal", **OPAL)).json()))
