Review result: **two findings**. The six guards prevent the reported local-app writes. However, authentication order differs from production, and the README overstates production’s dry-run support.

All execution and edits used copies under `review-artifacts/` inside the export. No git commands or pushes were run; `head/` and `base/` were not edited.

**1. [P3] Authenticate before rejecting dry-run requests**

Location: `head/examples/local/app.py:172–181`; the incorrect production comparison is also encoded in `head/cmapi/tests/core/test_local_dry_run_613.py:53–55`.

The request-only route dependency executes before the endpoint’s `Depends(caller)`. Consequently, an unauthenticated request such as:

```http
POST /api/v1/requests/missing:cancel?dryRun=true
```

gets **400**, while the same request without `dryRun` gets **401**.

**Production’s authentication-first behavior is confirmed.** `head/cmapi/src/cmapi/main.py:114–127` installs sign-in as an include dependency. Its caller rejects a missing token at `head/cmapi/src/cmapi/core/auth.py:200–205`. Running the actual `create_app` factory, with external services replaced, produced:

| Credentials | Production `:cancel?dryRun=true` | Request lookup |
|---|---:|---:|
| Missing | 401 | Not called |
| Invalid | 401 | Not called |
| Accepted by test authenticator | 404 from mocked lookup | Called once |

Evidence: [production probe output](/Users/olasumbo/gitRepos/workbench/cmapi/review-618/review-artifacts/production_probe.txt:1).

**Important snapshot discrepancy:** the supplied production source does **not** contain `refuse_dry_run`. Its `_register` registers the endpoint without guard dependencies (`head/cmapi/src/cmapi/core/docs.py:251–285`). Searching both production snapshots found no guard or `dry-run-not-supported` implementation. Thus, “production signs in first” is verified, but “its guard follows” cannot be verified from this export. Authenticated production cancel actually reached the mocked lookup.

The example should match production’s authentication-first boundary. This is a consistency defect, not a demonstrated sensitive-information disclosure: the unauthenticated 400 reveals that the matched operation rejects dry runs, but contains no request existence, namespace state, identity, or permission information. The guard runs before `find` (`app.py:177–178`, `426–429`); the local OpenAPI documentation is also public by default (`app.py:187–188`).

Full replacement guard:

```python
def refuse_dry_run(request: Request, _who: Identity = Depends(caller)) -> None:
    """After authentication, reject any dryRun on a write without a preview (#613)."""
    if "dryRun" in request.query_params:
        raise Problem.bad_request(
            "dry-run-not-supported",
            "This call has no dry run: send it without dryRun",
        )
```

Keep `NO_DRY_RUN` and all six route decorators unchanged. FastAPI’s default dependency caching allows the endpoint to reuse the authenticated caller.

The existing cancel test must also stop requiring unauthenticated 400. Its full replacement is:

```python
def test_a_cancel_with_dry_run_is_refused_before_the_request_is_looked_up(local):
    client = TestClient(local.app)
    for value in ("false", "true", "All", ""):
        refused(client.post(f"/api/v1/requests/missing:cancel?dryRun={value}"))

    r = client.post("/api/v1/requests/missing:cancel")
    assert (r.status_code, r.json()["code"]) == (404, "object-not-found"), r.text

    # Authentication precedes the guard, as production sign-in does.
    local.app.dependency_overrides.clear()
    r = client.post("/api/v1/requests/missing:cancel?dryRun=true")
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated"), r.text
    assert client.post("/api/v1/requests/missing:cancel").status_code == 401
```

Additional regression test, using the PR’s existing `local` fixture:

```python
from unittest.mock import Mock

import jwt
import pytest
from fastapi.testclient import TestClient

from test_local_dry_run_613 import local

CASES = [
    ("POST", "/api/v1/clusters/OCP_LOCAL/namespaces/x/expiration:extend",
     {"days": 1}),
    ("DELETE", "/api/v1/clusters/OCP_LOCAL/namespaces/x", None),
    ("POST", "/api/v1/requests/missing:approve", {}),
    ("POST", "/api/v1/requests/missing:reject", {"comment": "no"}),
    ("POST", "/api/v1/requests/missing:cancel", None),
    ("POST", "/api/v1/admin/prune:confirm", {"namespace": "x"}),
]


@pytest.mark.parametrize("method,url,body", CASES)
@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer broken"}]
)
def test_authentication_precedes_guard(
    local, monkeypatch, method, url, body, headers
):
    local.app.dependency_overrides.clear()
    monkeypatch.setattr(
        local.JWKS,
        "get_signing_key_from_jwt",
        Mock(side_effect=jwt.InvalidTokenError("invalid test token")),
    )
    response = TestClient(local.app).request(
        method, url + "?dryRun=true", json=body, headers=headers
    )
    assert (response.status_code, response.json()["code"]) == (
        401, "unauthenticated"
    ), response.text
    local.CLUSTER.delete_namespace.assert_not_called()
```

**Measured:** all 12 authentication cases failed before this fix and passed afterward. See [before results](/Users/olasumbo/gitRepos/workbench/cmapi/review-618/review-artifacts/additional_before.txt:1) and [fixed results](/Users/olasumbo/gitRepos/workbench/cmapi/review-618/review-artifacts/fixed.txt:1).

**2. [P2] README promises production safety behavior absent from this snapshot**

Location: `head/examples/local/README.md:31` and `50–51`.

The production column says delete previews and production follows the same rejection rule. Both claims are false for the exported source:

- Production delete declares no dry-run parameter and explicitly plans with `dry_run=False`, then submits (`head/cmapi/src/cmapi/plugins/namespaces/router.py:336–353`).
- Production `_register` attaches no dry-run guard (`head/cmapi/src/cmapi/core/docs.py:274–285`).
- The production probe demonstrated that authenticated cancel with `dryRun=true` proceeds to lookup.

Failure scenario: an operator follows the README’s production comparison and sends an otherwise valid production delete with `dryRun=true`, expecting a preview. That query parameter does not select a preview; the code proceeds toward submission. This conclusion follows from the source; I did not perform a real deletion.

Full replacement README table row:

```markdown
| Dry run | After authentication, `?dryRun=true` on a create or a change returns the plan and records nothing; every other write rejects any `dryRun` with 400 `dry-run-not-supported`. | Create, change and the three expiry calls preview. Delete has no preview; this snapshot does not yet reject `dryRun` on other writes. |
```

Full replacement final bullet:

```markdown
- **A write with no dry run ignored `dryRun`.** FastAPI drops a query parameter that a route does not declare, so
  `:cancel?dryRun=true` cancelled and `prune:confirm?dryRun=true` deleted the namespace. The expiry extend, the delete,
  `:approve`, `:reject`, `:cancel` and `prune:confirm` now refuse it after authentication with 400
  `dry-run-not-supported` (#613).
```

This documentation regression test checks the advertised production delete preview against the actual registered route:

```python
def test_readme_does_not_advertise_a_production_delete_preview(local):
    import re
    from cmapi.main import api_app

    app, _ = api_app(local.CFG, local.ISSUER)
    route = next(
        r for r in app.routes
        if getattr(r, "path", None)
        == "/api/v1/clusters/{cluster_id}/namespaces/{ns}"
        and "DELETE" in getattr(r, "methods", set())
    )
    production = next(
        line for line in (local.HERE / "README.md").read_text().splitlines()
        if line.startswith("| Dry run |")
    ).split("|")[3]
    advertises_delete_preview = re.search(
        r"\ba delete\b.*\balso preview\b", production, re.I
    )
    supports_delete_preview = any(
        p.alias == "dryRun" for p in route.dependant.query_params
    )
    assert not advertises_delete_preview or supports_delete_preview, production
```

**Measured:** this test failed against the original README and passed after replacement. Evidence: [before](/Users/olasumbo/gitRepos/workbench/cmapi/review-618/review-artifacts/readme_before.txt:1), [after](/Users/olasumbo/gitRepos/workbench/cmapi/review-618/review-artifacts/fixed.txt:1). This is a targeted documentation check, not proof of a complete production safety contract.

**Remaining claims**

**Confirmed — every local HTTP write either supports a preview or has a guard.** The complete inventory is:

| Method and route | Behavior | Source |
|---|---|---|
| POST `/api/v1/clusters/{cluster_id}/namespaces` | Preview for `dryRun=true`; returns before submission | `head/examples/local/app.py:368–373` |
| PATCH `/api/v1/clusters/{cluster_id}/namespaces/{ns}` | Preview for `dryRun=true`; returns before submission | `app.py:376–382` |
| POST `/api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:extend` | Guarded | `app.py:385–388` |
| DELETE `/api/v1/clusters/{cluster_id}/namespaces/{ns}` | Guarded | `app.py:391–414` |
| POST `/api/v1/requests/{rid}:approve` | Guarded | `app.py:437–449` |
| POST `/api/v1/requests/{rid}:reject` | Guarded | `app.py:452–458` |
| POST `/api/v1/requests/{rid}:cancel` | Guarded | `app.py:461–467` |
| POST `/api/v1/admin/prune:confirm` | Guarded before cluster deletion | `app.py:470–479` |

The route-enumeration test verifies two preview routes and six guarded routes (`head/cmapi/tests/core/test_local_dry_run_613.py:77–90`). Additional execution confirmed all six reject `true`, `false`, `All`, and empty values, and both previews return without calling `submit`. These 26 additional cases passed before any fix.

**Confirmed — the problem body matches production’s serialization shape.** The local handler uses the shared `Problem.body()` and `application/problem+json` (`head/examples/local/app.py:201–203`), as production does (`head/cmapi/src/cmapi/main.py:174–177`). The body is:

```json
{
  "type": "https://cmapi.ephico2real.com/problems/dry-run-not-supported",
  "title": "dry run not supported",
  "status": 400,
  "detail": "This call has no dry run: send it without dryRun",
  "code": "dry-run-not-supported"
}
```

Empty `errors` is omitted by the shared serializer (`head/cmapi/src/cmapi/core/errors.py:38–43`). Production can configure a different type URI base. An identical **production dry-run refusal** cannot be confirmed because that implementation is absent here.

**Confirmed — removing any single guard makes the supplied test fail.** I ran each mutant independently in the export copy, restoring the app between runs:

| Removed guard | Result |
|---|---|
| Expiry extend | 1 failed, 3 passed |
| Delete | 1 failed, 3 passed |
| Approve | 1 failed, 3 passed |
| Reject | 1 failed, 3 passed |
| Cancel | 2 failed, 2 passed |
| Prune confirm | 2 failed, 2 passed |

All six are caught by the route dependency assertion at `test_local_dry_run_613.py:87`; cancel and prune also fail behavioral tests. This confirms guard-removal sensitivity, not behavioral coverage of every possible guard defect.

The unmodified PR test returned **4 passed**. After applying the proposed fixes only to the export copy, the supplied tests plus reviewer checks returned **43 passed**. The commands used the specified Python with `-B -m pytest -p no:cacheprovider`; the mutation runner and per-mutant logs are preserved in [review-artifacts](/Users/olasumbo/gitRepos/workbench/cmapi/review-618/review-artifacts/run_mutants.py:1).

Codex session ID: 01a20a8c-4c34-7883-9618-25eddc20de8d
Resume in Codex: codex resume 01a20a8c-4c34-7883-9618-25eddc20de8d
