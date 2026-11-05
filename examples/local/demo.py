"""End-to-end run against the local stack: Keycloak tokens -> cmapi -> Git -> k3s.

    python demo.py > transcript.txt
"""
from __future__ import annotations

import json
import subprocess
import time

import httpx

KC = "http://localhost:8080/realms/ephico2real/protocol/openid-connect/token"
API = "http://localhost:8000/api/v1"
CL = "OCP_LOCAL"


def token(user: str | None = None) -> str:
    data = ({"grant_type": "password", "client_id": "cmapi-cli", "username": user, "password": "demo"} if user else
            {"grant_type": "client_credentials", "client_id": "svc-payments-ci", "client_secret": "svc-secret"})
    return httpx.post(KC, data=data).json()["access_token"]


T = {"ola": token("ola"), "amy": token("amy"), "opal": token("opal"), "svc": token()}


def call(who: str, method: str, path: str, body: dict | None = None, **params) -> tuple[int, dict]:
    r = httpx.request(method, API + path, json=body, params=params,
                      headers={"Authorization": f"Bearer {T[who]}"}, timeout=120)
    return r.status_code, r.json()


def show(title: str, status: int, body: dict, keys: list[str] | None = None) -> None:
    print(f"\n### {title}\n-> {status}")
    out = {k: body.get(k) for k in keys} if keys else body
    print(json.dumps(out, indent=2, default=str)[:2500])


def wait(rid: str, until: set[str], who: str = "ola", timeout: int = 90) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, r = call(who, "GET", f"/requests/{rid}")
        if r["status"] in until:
            return r
        time.sleep(1)
    return r


def events(r: dict) -> None:
    for e in r["events"]:
        print(f"   {e['at']}  {e['status']:<17} {e['by']:<15} {e['note']}")


def kubectl(*args: str) -> None:
    out = subprocess.run(["k3s", "kubectl", *args], capture_output=True, text=True,
                         env={"KUBECONFIG": "/etc/rancher/k3s/k3s.yaml", "PATH": "/usr/local/bin:/usr/bin:/bin"})
    print("$ kubectl " + " ".join(args) + "\n" + (out.stdout or out.stderr).rstrip())


NS = {"cmapi.net/team": "payments", "cmapi.net/cost-center": "cc-4410", "app.ephico2real.com/component": "api"}
ZONE = {"network.ephico2real.com/zone": "internal"}
DL = {"cmapi.net/team-dl": "payments-team@ephico2real.com"}

print("# cmapi local end-to-end run")
s, b = call("ola", "GET", "/me")
show("1. Who am I (ola, from the Keycloak token)", s, b, ["username", "roles", "groups", "teams", "identity"])

s, b = call("ola", "GET", "/tiers", environment="dev")
show("2. Tiers offered in dev", s, {"catalogHash": b["catalogHash"],
     "tiers": [(t["name"], t["quota"].get("requests.cpu"), t["quota"].get("requests.memory"), t["hash"])
               for t in b["environments"]["dev"]["tiers"]], "custom": b["environments"]["dev"]["custom"]})

print("\n### 3. Refusals at plan time")
for title, who, body in [
    ("namespace outside ola's binding (ledger-*)", "ola", {"namespace": "ledger-dev", "tier": "small",
                                                            "labels": {**NS, "cmapi.net/team": "ledger"}, "annotations": DL}),
    ("team DL outside the email domains", "ola", {"namespace": "payments-x", "tier": "small", "labels": NS,
                                                   "annotations": {"cmapi.net/team-dl": "payments@other.com"}}),
    ("quota sent with a named tier", "ola", {"namespace": "payments-x", "tier": "medium", "labels": NS,
                                              "annotations": DL, "quota": {"requests.cpu": "20"}}),
    ("a system key set by the caller", "ola", {"namespace": "payments-x", "tier": "small",
                                                "labels": {**NS, "cmapi.net/tier": "large"}, "annotations": DL}),
    ("a service client without onBehalfOf", "svc", {"namespace": "payments-x", "tier": "small", "labels": NS,
                                                     "annotations": DL})]:
    s, b = call(who, "POST", f"/clusters/{CL}/namespaces", body, dryRun="true")
    print(f"- {title}: {s} {b.get('code')} {b.get('errors') or b.get('detail')}")

body = {"namespace": "payments-dev", "tier": "medium", "labels": {**NS, **ZONE},
        "annotations": {**DL, "ops.ephico2real.com/pager": "payments-oncall"}, "expiresAt": "2026-12-15",
        "justification": "Payments service dev namespace"}
s, b = call("ola", "POST", f"/clusters/{CL}/namespaces", body, dryRun="true")
show("4. Dry run: payments-dev, medium, expires 2026-12-15", s,
     {"changes": b["changes"], "capacity": b["capacity"], "approval": b["approval"], "planHash": b["planHash"][:16]})

s, b = call("ola", "POST", f"/clusters/{CL}/namespaces", body)
print(f"\n### 5. Submit payments-dev -> {s} {b['requestId']} {b['status']} ({b['approval']['auto']})")
r = wait(b["requestId"], {"synced", "failed", "rejected"})
events(r)
kubectl("get", "ns", "payments-dev", "--show-labels")
kubectl("get", "resourcequota,limitrange", "-n", "payments-dev")

big = {"namespace": "payments-batch", "tier": "large", "labels": NS, "annotations": DL,
       "justification": "Nightly settlement batch"}
s, b = call("ola", "POST", f"/clusters/{CL}/namespaces", big)
print(f"\n### 6. payments-batch, large -> {s} {b['requestId']} {b['status']}; needs {b['approval']['slots']}"
      f"; auto-approval stopped by: {b['approval']['autoFallback']}")
rid = b["requestId"]
s, x = call("ola", "POST", f"/requests/{rid}:approve", {})
print(f"- ola (a requester, no approver role) tries to approve: {s} {x.get('code')}")
s, x = call("opal", "POST", f"/requests/{rid}:approve", {})
print(f"- opal (approver, but in platform-operators, not platform-leads): {s} {x.get('code')}")
s, x = call("amy", "GET", "/requests", status="pending_approval", approver="me")
print(f"- amy's queue: {[i['requestId'] for i in x['items']]}")
s, x = call("amy", "POST", f"/requests/{rid}:approve", {"comment": "batch sizing reviewed"})
print(f"- amy approves: {s} -> {x['status']}")
events(wait(rid, {"synced", "failed"}))

s, b = call("svc", "POST", f"/clusters/{CL}/namespaces",
            {"namespace": "payments-ci-dev", "tier": "small", "labels": NS, "annotations": DL, "onBehalfOf": "1001"})
print(f"\n### 7. svc-payments-ci on behalf of employee 1001 -> {s} {b['requestId']} {b['status']}")
print(f"- recorded requester: {b['requester']['requester']['username']} ({b['requester']['requester']['employeeId']}),"
      f" submitted by {b['requester'].get('submittedByClient')}")
wait(b["requestId"], {"synced", "failed"})
kubectl("get", "ns", "payments-ci-dev", "-o", "jsonpath={.metadata.labels.cmapi\\.net/requested-by-user}{\"\\n\"}")

s, b = call("ola", "PATCH", f"/clusters/{CL}/namespaces/payments-dev", {"tier": "large"}, dryRun="true")
show("8a. Tier change payments-dev medium -> large (dry run)", s, {"changes": b["changes"], "approval": b["approval"]})
s, b = call("ola", "PATCH", f"/clusters/{CL}/namespaces/payments-dev", {"tier": "large"})
r = wait(b["requestId"], {"synced", "failed"})
print(f"8b. submitted {b['requestId']} -> {r['status']}")
kubectl("get", "resourcequota", "payments-dev-quota", "-n", "payments-dev", "-o",
        "jsonpath={.spec.hard}{\"  tier-hash=\"}{.metadata.annotations.cmapi\\.net/tier-hash}{\"\\n\"}")

s, b = call("ola", "POST", f"/clusters/{CL}/namespaces/payments-dev/expiration:extend", {"days": 40})
print(f"\n### 9. Extend payments-dev by 40 days -> {s} {b.get('code')}: {b.get('detail')}")
s, b = call("ola", "POST", f"/clusters/{CL}/namespaces/payments-dev/expiration:extend", {"days": 30})
r = wait(b["requestId"], {"synced", "failed"})
print(f"- by 30 days -> {b['requestId']} {r['status']}")
kubectl("get", "ns", "payments-dev", "-o", "jsonpath={.metadata.annotations.cmapi\\.net/expires-at}{\"\\n\"}")

s, b = call("ola", "PATCH", f"/clusters/{CL}/namespaces/payments-dev", {"labels": {"network.ephico2real.com/zone": "dmz"}})
print(f"\n### 10. Sensitive key network.ephico2real.com/zone internal -> dmz -> {s} {b['status']}; "
      f"slots {[(x['group'], x['count']) for x in b['approval']['slots']]}; reasons {b['approval']['reasons']}")
call("amy", "POST", f"/requests/{b['requestId']}:approve", {"comment": "zone change agreed"})
print(f"- after amy: {wait(b['requestId'], {'synced', 'failed'})['status']}")

s, b = call("ola", "GET", "/quotas", limit=2)
print(f"\n### 11. GET /quotas (limit 2) -> total {b['page']['total']}, facets {b['facets']}")
for i in b["items"]:
    print(f"   {i['name']:<16} tier={i['tier']:<6} cpu={i['cpu']} memory={i['memory']} expires={i['expiresAt']}")
s, b2 = call("ola", "GET", "/quotas", limit=2, cursor=b["page"]["nextCursor"])
print(f"   next page: {[i['name'] for i in b2['items']]} (from {b2['page']['from']} to {b2['page']['to']})")

s, b = call("ola", "DELETE", f"/clusters/{CL}/namespaces/payments-ci-dev")
print(f"\n### 12. Delete payments-ci-dev -> {s} {b['requestId']} {b['status']}; slots {b['approval']['slots']}")
call("amy", "POST", f"/requests/{b['requestId']}:approve", {"comment": "CI namespace no longer used"})
r = wait(b["requestId"], {"awaiting_prune", "failed"})
print(f"- merged, then: {r['status']} (Prune=confirm)")
kubectl("get", "ns", "payments-ci-dev")
s, x = call("opal", "POST", "/admin/prune:confirm", {"namespace": "payments-ci-dev"})
print(f"- opal confirms the prune -> {s} {x['status']}")
events(x)

s, b = call("ola", "GET", "/admin/git-log")
print("\n### 13. cluster-configs-nonprod history (bot PRs, merged --no-ff)")
print("\n".join(b["log"]))
kubectl("get", "ns", "-l", "cmapi.net/managed=true", "-L", "cmapi.net/tier,cmapi.net/env,cmapi.net/team")
