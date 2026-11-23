**Reviewer 1 verdict: request changes.** A single `dryRun=true` now stops production DELETE before submission, and the nine production writes without preview support reject `dryRun`. Two cases still matter before merge. A repeated `dryRun` can turn a preview into a real write, and DELETE can return a successful plan for a namespace that already has an open change. The decision record also gets the authentication order wrong. **An unauthenticated, well-formed request gets 401.**

I reviewed the exported base and head, ran the supplied Python against both, and made the mutations in memory. I did not invoke Git, modify a repository, or push. Below, `src/` means `head/cmapi/src/cmapi/`, `tests/` means `head/cmapi/tests/service/`, and `decision` means `head/docs/reviews/2026-11-23-issue-602/README.md`.

## 1. High — a repeated `dryRun` can still dispatch a real write

`src/routers/__init__.py:22` declares `dryRun` as a scalar Boolean. The installed FastAPI uses `getlist` for sequence fields and `get` for scalars at `fastapi/dependencies/utils.py:721–723`. At `src/plugins/namespaces/router.py:350–359`, the resulting single value decides whether DELETE submits.

**Measured:** With a valid token, key and matching ETag, `dryRun=false&dryRun=true` returned 200 and called `_submit` zero times. Reversing the order called `_submit` once. I replaced `_submit` with a sentinel so the experiment could distinguish dispatch from persistence. On the exported base, even a single `dryRun=true` reached that sentinel. On head, a single `dryRun=true` returned 200. An empty value on a supported route returned 422.

A client that requests a preview and an HTTP wrapper that appends its default `dryRun=false` can therefore recreate #602. The same scalar is used by create, change and the three expiry writes at `src/plugins/namespaces/router.py:262,286,388,411,424`. The nine unsupported writes already handle duplicates correctly because they test key presence at `src/core/docs.py:244`.

**Fix.** Reject repeated values on the six supported writes. Keep the existing Boolean parameter, its OpenAPI schema, and the nine-route presence guard. Add this function to `src/core/docs.py` and replace the dependency assignment at line 294 with the block below. I exercised this dependency in memory. Both orders returned 422, a single `true` returned 200, and none reached `_submit`.

```python
def require_single_dry_run(request: Request) -> None:
    if len(request.query_params.getlist("dryRun")) > 1:
        raise Problem.unprocessable("validation-failed", "Send dryRun at most once.")
```

```python
            if guarded:
                kwargs["dependencies"] = [Depends(refuse_dry_run)]
            elif method in WRITE_METHODS and dry_run_model is not None:
                kwargs["dependencies"] = [Depends(require_single_dry_run)]
```

**Regression test** for `test_delete_dry_run_602.py`. The original code reaches submission on the first iteration.

```python
def test_repeated_dry_run_cannot_submit(world, monkeypatch):
    client, _, _, _, _, keys = world
    etag = created(world)
    headers = {**auth(keys, "ola", **OLA), "If-Match": f'"{etag}"'}

    def unexpected_submit(*args, **kwargs):
        raise AssertionError("ambiguous dryRun reached submission")

    monkeypatch.setattr("cmapi.plugins.namespaces.router._submit", unexpected_submit)
    for query in ("dryRun=true&dryRun=false", "dryRun=false&dryRun=true"):
        response = client.delete(f"{ONE}?{query}", headers=headers)
        assert (response.status_code, response.json()["code"]) == (422, "validation-failed")
```

## 2. Medium — an already-held namespace previews successfully

`src/plugins/namespaces/router.py:355–359` returns the plan before checking whether another request holds the namespace. A real, fresh-key submission hits the unique open-namespace index at `src/core/db/models.py:199`, then returns 409 `change-pending` and the holder ID at `src/core/db/repo.py:185–198`. This is a counterexample to the parity claim in `LIVE-DOC-EDITS.md:31` and the route description at `src/plugins/namespaces/router.py:346–348`.

**Failure scenario, inferred from those paths:** Open a delete that awaits approval. While it is pending, Git still has the namespace and its matching ETag. A second caller with write permission can preview the same delete and get 200. Submitting it with a fresh key gets 409. This requires no race. It also means the preview can disclose the file-name and approval summary in a state where the corresponding fresh submission would return only a conflict. PostgreSQL prevented an end-to-end measurement here.

**Fix.** Check the existing holder after planning and before returning the DELETE preview. `RequestRepo.open_for` is already a plain SELECT at `src/core/db/repo.py:116–119`. This detects an existing conflict without reserving anything. Continue to enforce the unique index on the real write because the holder can change after the preview. Replace lines 357–359 with:

```python
    if dry_run:
        with c.db.session() as session:
            holder = RequestRepo(session).open_for(cluster_id, ns)
            if holder is not None:
                raise Problem.conflict(
                    "change-pending",
                    f"{holder.request_id} holds {ns}",
                    requestId=holder.request_id,
                )
        return JSONResponse(PlanView.model_validate(plan.view()).model_dump(by_alias=True), status_code=200)
    return _submit(c, who, plan, key, raw, None)
```

**Regression test** for `test_delete_dry_run_602.py`:

```python
def test_delete_preview_reports_an_existing_holder(world):
    client, ctx, _, _, _, keys = world
    etag = created(world)
    first = {**auth(keys, "ola", **OLA), "If-Match": f'"{etag}"'}
    opened = client.delete(ONE, headers=first)
    assert opened.status_code == 202
    holder = opened.json()["requestId"]
    before = rows(ctx)

    fresh = {**auth(keys, "ola", **OLA), "If-Match": f'"{etag}"'}
    for url in (f"{ONE}?dryRun=true", ONE):
        response = client.delete(url, headers=fresh)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "change-pending"
        assert response.json()["requestId"] == holder
    assert rows(ctx) == before
```

Even with this fix, the documentation should promise **planning-check parity**, not identical outcomes for every request. Ignoring the idempotency key on preview is intentional. A real request can fail for a missing, oversized or conflicting key, or replay an earlier request without comparing the current Git ETag. `src/plugins/namespaces/router.py:76–97,350–356`. AIP-163 supports detecting a failure already knowable at validation time. [Google AIP-163](https://google.aip.dev/163)

## 3. The decision record and live-doc edits need narrower claims

| Claim | Result and evidence |
|---|---|
| An unauthenticated action with `?dryRun=true` gets 400 | **Refuted.** `src/main.py:114,125–127` adds sign-in when including each router. FastAPI appends the route dependencies after the include dependencies at `fastapi/routing.py:1288–1290`. The assembled order I measured was `caller`, `refuse_dry_run`, permission dependency, context. Missing credentials raised 401 at `src/core/auth.py:200–204`. Against `:approve`, I measured 401 for absent, true, false, bare and repeated `dryRun`. The comment at `src/core/docs.py:275–276` and `decision:91–94` are wrong. |
| Any request to an unsupported write carrying `dryRun` gets 400 | **Confirmed once authentication and body decoding succeed.** A signed-in caller lacking approval permission got 400 with `dryRun` and 403 without it. Malformed JSON got 422 even without credentials. FastAPI decodes JSON at `fastapi/routing.py:255–262` before dependency solving at line 291. cmapi converts request validation errors to problem details at `src/main.py:194–202`. Qualify `LIVE-DOC-EDITS.md:17,45`. |
| “No row” and “writes nothing” | **Confirmed for the change workflow; refuted literally.** Production authentication supplies `DbKeyStore` at `src/core/context.py:87`. On signing-key refresh, `src/core/auth.py:60–76` calls `save`, which inserts or updates `jwks_keys` at `src/core/db/repo.py:376–382`. A successful preview with a cold key cache called my store's `save` once. The actual database write is inferred from the production store. HTTP telemetry also changes. Qualify `LIVE-DOC-EDITS.md:31,50`, `src/core/docs.py:111`, `src/routers/__init__.py:22–24`, and the glossary at `head/docs/GLOSSARY.md:59`. |
| Every file in the folder is listed | **Refuted.** The providers enumerate direct `.yaml` files at `src/core/git/github.py:69–77` and `src/core/git/gitea.py:68–77`. The renderer maps what the provider returned to `None` at `src/core/render/manifests.py:226–229`. I supplied a `namespace.yaml` and a sibling `README.md` to the fixture Git provider. Only the YAML path appeared in `changes`. Correct `LIVE-DOC-EDITS.md:31`, `decision:49–51`, and `src/plugins/namespaces/router.py:346`. |
| A protected dry-run refusal is counted by `refusals` | **Refuted for `cmapi_plan_refusals_total`.** `src/core/rejections.py:36–38,126–131` filters by `RECORDED`. `namespace-protected` is absent from that set and `src/core/pipeline.py:528–529`. I measured a 422 with a counter delta of **0**. The ordinary HTTP 422 still counts. `decision:44–47` should specify which refusals the counter covers. |
| Six preview routes and nine other writes, with the responses listed in docs/01 and docs/02 | **Confirmed for successful production calls.** I enumerated the assembled app with all seven built-in plugins enabled. The six return plans; the nine action routes have the guard. `:probe` is a POST registered through `router.read`, which the method check correctly catches (`src/routers/me.py:87–98`). `:revert` returns the existing request and queues a worker that subsequently opens another (`src/routers/requests.py:232–254`). “Directly opens a change request” is precise. The stored live and preview DELETE samples both have empty response-header maps; the real body has `links.self` (`src/core/views.py:17–18`, `src/contract/samples.json:1828,1923`). |

**Replacement wording** for the changed claims in docs/01, docs/02, the route description and the decision record:

> The six namespace writes that directly open a change request return 202 with the ChangeRequest and its `links.self`. With `dryRun=true`, a successful call returns 200 with the PlanView. It runs authorization and planning checks, ignores the idempotency key, reserves no namespace, creates no change request, event, audit entry or job, and opens no PR. Authentication caches, request logs and metrics operate normally. A preview cannot guarantee that a later submission will succeed.
>
> A delete plan lists the direct `.yaml` files read from the namespace’s Git folder as `removed`. It renders no file contents. Its capacity result is `fits` with source `delete`, and its approval describes the requirement calculated for the current snapshot.
>
> On the nine writes without preview support, a request that reaches the dry-run guard with any `dryRun` query value receives 400 `dry-run-not-supported`. Sign-in precedes the guard. The endpoint’s permission check follows it. Malformed JSON can fail during decoding before either dependency runs. Only policy refusals in `RECORDED` increment the plan-refusal counter.

For the shared OpenAPI response text, the complete replacement is:

```python
DRY_RUN_RETURNS = (
    "Dry run (`?dryRun=true`): the plan. The call opens no change request, "
    "reserves no namespace, queues no job and opens no pull request."
)
```

**Documentation regression test.** The description assertion fails on head. The HTTP assertions pin the measured ordering and would fail on an implementation that actually behaved as the current decision record says.

```python
def test_dry_run_docs_and_auth_order(world):
    client, _, _, _, _, keys = world
    path = "/api/v1/requests/example:approve?dryRun=true"
    anon = client.post(path, json={})
    assert anon.status_code == 401
    assert "www-authenticate" in anon.headers

    signed_in = client.post(path, json={}, headers=auth(keys, "ola", **OLA))
    assert signed_in.status_code == 400
    assert signed_in.json()["code"] == "dry-run-not-supported"

    op = client.get("/openapi.json").json()["paths"][
        "/api/v1/clusters/{cluster_id}/namespaces/{ns}"
    ]["delete"]
    assert "opens no change request" in op["responses"]["200"]["description"]
    assert "writes nothing" not in op["responses"]["200"]["description"]
```

**Disclosure and status-code judgment.** I found no new unauthenticated route-shape disclosure through the guard on a well-formed request. A signed-in but unauthorized caller can distinguish unsupported previews, including when the OpenAPI document is private (`src/main.py:235–243`). That reveals an operation capability, without looking up a request ID or namespace. Kubernetes also rejects any occurrence of `dryRun` in its unsupported `ConnectResource` handler, including an empty value, but its server authentication and authorization filters wrap the handler. cmapi matches the presence rule and status; the ordering relative to endpoint authorization differs. I would keep 400. cmapi already assigns 400 to unsupported query choices such as sort, cursor and limit at `src/core/docs.py:75–79`. A malformed value for a *supported* Boolean follows its normal 422 binding convention. RFC 9110 allows 400 here and describes 422 in terms of request content. [Kubernetes handler](https://github.com/kubernetes/apiserver/blob/master/pkg/endpoints/handlers/rest.go) · [Kubernetes handler chain](https://github.com/kubernetes/apiserver/blob/master/pkg/server/config.go) · [Kubernetes dry-run authorization](https://kubernetes.io/docs/reference/using-api/api-concepts/#dry-run-authorization) · [RFC 9110 §§15.5.1 and 15.5.21](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.1)

## 4. A separate executable example still accepts unsafe previews

**Confirmed for production:** I found no other declared “do not act” query on its writes. The complete runtime query inventory was `dryRun` on six and no query parameter on the other nine. The supported handlers branch before submit at `src/plugins/namespaces/router.py:277,331,357,380`; the three expiry handlers pass the value through at lines 404, 418 and 431. The guard applies only to POST, PUT, PATCH and DELETE and only without a `dry_run_model` at `src/core/docs.py:237,277–295`. No assembled read had the guard. This guarantee applies to the registered production routes; using a bare FastAPI decorator in a future plugin would bypass `_register`.

**Refuted for the whole export:** `head/examples/local/app.py` runs a second HTTP application against real Git and Kubernetes services (lines 1–15). Its create and patch honor `dryRun` at lines 356–371. Its expiry extension submits unconditionally at lines 373–377, its delete records a request at lines 379–402, and its approve, reject, cancel and prune handlers lack the guard at lines 425–465. In particular, `prune:confirm` calls `CLUSTER.delete_namespace` at line 465. This predates the PR and is outside the production OpenAPI contract. I inspected it statically and did not start that stack.

**Minimal example fix:** refuse the parameter on the six unsupported operations. Add the following dependency after `caller` and replace the six existing decorators with those below. This preserves the example’s existing create and patch previews.

```python
def refuse_unsupported_preview(request: Request, who: Identity = Depends(caller)) -> None:
    if "dryRun" in request.query_params:
        raise Problem(400, "dry-run-not-supported", "This operation has no dry run.")


NO_PREVIEW = [Depends(refuse_unsupported_preview)]
```

```python
@app.post("/api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:extend", status_code=202, dependencies=NO_PREVIEW)
@app.delete("/api/v1/clusters/{cluster_id}/namespaces/{ns}", status_code=202, dependencies=NO_PREVIEW)
@app.post("/api/v1/requests/{rid}:approve", dependencies=NO_PREVIEW)
@app.post("/api/v1/requests/{rid}:reject", dependencies=NO_PREVIEW)
@app.post("/api/v1/requests/{rid}:cancel", dependencies=NO_PREVIEW)
@app.post("/api/v1/admin/prune:confirm", dependencies=NO_PREVIEW)
```

Each decorator above replaces the decorator on its corresponding handler. An example-app regression test can use a missing ID, so it needs no seeded request or live cluster operation. Before the fix, cancel reaches `find` and gives 404 (`examples/local/app.py:416,452`); afterwards it gives 400.

```python
def test_example_cancel_refuses_preview(monkeypatch):
    import app as local
    from fastapi.testclient import TestClient

    monkeypatch.setitem(local.app.dependency_overrides, local.caller, lambda: object())
    response = TestClient(local.app).post("/api/v1/requests/missing:cancel?dryRun=false")
    assert response.status_code == 400
    assert response.json()["code"] == "dry-run-not-supported"
```

## Delete side effects, ordering and plan visibility

- **Confirmed — no change submission on a single supported preview.** `_idem` returns `None` before checking presence or length. `_replay` returns before opening a session, so even its expired-key cleanup UPDATE is skipped (`src/plugins/namespaces/router.py:76–95`, `src/core/db/repo.py:148–155`). The early 200 skips ID allocation, the daily advisory lock, the namespace unique-index claim, request/event insertion, job enqueue, warning recording and the action audit row (`src/core/pipeline.py:492–522`, `src/core/db/repo.py:166–169,177–202`, `src/plugins/namespaces/router.py:100–110`). The live-vs-preview `_submit` sentinel distinguished the two paths in the run. I did not measure database contents.
- **Confirmed — the normal API process reads Git.** `src/core/context.py:129–137` enables the Git workspace for the worker. The API resolves the branch head and performs host reads (`src/core/git/base.py:190–198`, `src/core/git/github.py:66–77`, `src/core/git/gitea.py:35–41,52–77`). The workspace's local mirror fetch and lock are real at `src/core/git/workspace.py:243–249,286–288,321–325`, but they are **not on the normal API path**. Planning reads the namespace cache and lists Pods and PVCs. The cache may take its in-process lock or fall back to a direct GET (`src/core/clients/kube.py:480–482,506–513`, `src/core/pipeline.py:209–218,469–478`). No Kubernetes mutation appears on that path.
- **Confirmed — planning has observable side effects.** `_decide` reads `admin_switches` through `SwitchRepo.get`, updates the auto-pause gauge, and can increment an auto-fallback counter (`src/core/pipeline.py:446–450`, `src/core/context.py:56–61`, `src/core/db/repo.py:353–355`). Environment/plugin refusals have their own counters (`src/core/pipeline.py:183–199`). Response middleware records HTTP count, duration and an access-log event that can contain caller subject and client (`src/core/observability.py:169–176`). Those are distinct from the omitted action audit row. The JWKS persistence exception is detailed above.
- **Confirmed — shared planning order, with the explicit exceptions above.** Sign-in and route permission precede the handler. A real fresh submission additionally checks its key. `plan_delete` checks cluster writability, served environment, environment-scoped permission, plugin availability and requester identity before reading Git. Missing namespace precedes `If-Match`; absent or `*` gives 428, a nonmatching strong tag gives 412, and protection gives 422 after workload reads and approval evaluation (`src/routers/__init__.py:45–55`, `src/core/pipeline.py:129–146,453–488`, `src/core/approvals.py:160–168`). A backend failure can precede the protection verdict. **Measured compound cases:** forbidden caller plus missing namespace/header → 403; authorized missing namespace plus missing header → 404; protected namespace plus stale tag → 412; protected namespace plus matching tag → 422. There is no universal `404 → 428 → 412 → 403 → 422` sequence.
- **Confirmed — ordinary successful previews have the delete’s permission boundary and return no previous file contents.** The view includes the caller/requester projection, approval rule, groups and counts, plan hash, ETag, path names, and a synthetic `fits` capacity result with `source=delete`. It omits `prev`; mappings to `None` disappear from `files` (`src/core/pipeline.py:73–82,149–158,485–489`). A successful real delete returns the same requester projection, approval information and file-name diff (`src/core/views.py:21–31`). I compared the two exported samples: all five file paths, requester, approval and plan hash matched exactly. The preview also returns the already-matched ETag. I found no new file-content or cross-permission disclosure. Finding 2 qualifies parity when submission is already blocked.

## Test quality and mutants

The positive DELETE test is meaningful. It sends a real key, checks the five paths, empty `files`, six table counts and fake Git state, then reuses the key for a real delete (`tests/test_delete_dry_run_602.py:47–70`). The action test checks the request remains pending and subsequently cancels it without `dryRun` (`tests/test_dry_run_refused_606.py:38–50`). Three gaps showed up under mutation:

| In-memory mutant | Measured outcome | Regression assertion that kills it |
|---|---|---|
| Move `require_if_match` ahead of namespace lookup | The existing ordering test passed with seeded fake Git and substituted row accounting. A missing namespace without `If-Match` changed from 404 to 428. The existing missing-namespace case supplies an ETag (`tests/test_delete_dry_run_602.py:84`). | `assert client.delete(f"{URL}/not-there-dev?dryRun=true", headers=bearer(keys)).status_code == 404` |
| Force the delete's `refusals` wrapper to use `dry_run=False` | The protected test still passed; `_store_refusal` received zero calls. Protection is outside `RECORDED`, so that test cannot distinguish the modes (`tests/test_delete_dry_run_602.py:92–98`, `src/core/rejections.py:126–130`). | Inject a `RECORDED` planning error and assert the store is untouched; complete test below. |
| Guard only when exactly one `dryRun` is present | All four existing value assertions and the structural route test passed. The repeated query got through to permission checking and returned 403 in my isolated run. An entirely inert dependency also passed the structural test by itself (`tests/test_dry_run_refused_606.py:42–45,71–85`). | `refused(client.post(f"/api/v1/requests/{rid}:approve?dryRun=true&dryRun=false", json={}, headers=auth(keys, "amy", **AMY)))` |

The implementation fixes for these mutants are the current ordering at `src/core/pipeline.py:461–467`, passing `dry_run=dry_run` at `src/plugins/namespaces/router.py:355`, and the presence test at `src/core/docs.py:244`. Add the assertions above to protect them. Table **counts** alone also miss updates to existing rows; `RejectionRepo.record` can increment an existing row at `src/core/rejections.py:92–98`.

```python
def test_delete_preview_never_stores_a_recordable_planning_refusal(world, monkeypatch):
    from unittest.mock import Mock
    from cmapi.core.errors import Problem

    client, ctx, _, _, _, keys = world
    error = Problem.unprocessable("policy-violation", "Injected planning refusal")
    monkeypatch.setattr(ctx.pipeline, "plan_delete", Mock(side_effect=error))
    store = Mock()
    monkeypatch.setattr("cmapi.core.rejections._store_refusal", store)

    response = client.delete(f"{ONE}?dryRun=true", headers=bearer(keys))
    assert response.status_code == 422
    store.assert_not_called()
```

## Contract and client compatibility

**Confirmed:** I ran `oasdiff` **1.37.0** on `base/cmapi/contract/openapi.json` and `head/cmapi/contract/openapi.json`. `changelog` returned **11 info, 0 warning, 0 error**: DELETE gains one optional query parameter and one 200 response; nine POST operations gain a 400 response. `breaking` reported no breaking changes.

**Refuted as a behavioral compatibility guarantee:** A client wrapper that always sends `dryRun=false` used to execute an unsupported action and now receives 400. A caller sending `dryRun=true` to DELETE now receives `200 PlanView` instead of opening a request and receiving `202 ChangeRequest`. This is an intentional safety change with a client migration: omit `dryRun` on an unsupported operation **only when execution is intended**. A preview client must stop on `dry-run-not-supported`. The portal approve hook already omits the parameter, and its preview hooks explicitly send `true` on supported routes (`head/cmapi-portal-ui/src/api/hooks.ts:227,309,467,621`). External client usage was not measured. I would add that migration text to `decision:103–104` and use it instead of the unconditional “send it without dryRun” advice at `src/core/docs.py:79` and `src/core/problem_docs.py:61`.

## Runs requiring the coordinator

Two unmodified pytest cases passed: `test_api_standard.py::test_the_delete_key_is_described_as_the_delete_checks_it` for both `metadata-keys.yaml` and `metadata-keys.company.yaml`. I also ran both new document/route-inventory test bodies against the assembled head app. Three DELETE refusal/key test bodies passed with fake Git seeded directly and row accounting substituted. Those runs verify routing and planning assertions; they do not verify PostgreSQL persistence.

The normal run of the nine new tests failed **during fixture setup** because the sandbox refused pytest's temporary configuration directory inside the export. An independent connection attempt to PostgreSQL at `127.0.0.1:55432` also returned `Operation not permitted`. These are the exact unverified pytest node IDs:

```text
cmapi/tests/service/test_delete_dry_run_602.py::test_a_delete_dry_run_answers_the_plan_and_writes_nothing
cmapi/tests/service/test_delete_dry_run_602.py::test_a_delete_dry_run_fails_where_the_delete_would
cmapi/tests/service/test_delete_dry_run_602.py::test_a_delete_dry_run_of_a_protected_namespace_is_refused
cmapi/tests/service/test_delete_dry_run_602.py::test_a_delete_dry_run_needs_no_idempotency_key_and_the_delete_still_does
cmapi/tests/service/test_delete_dry_run_602.py::test_the_document_declares_the_delete_dry_run
cmapi/tests/service/test_dry_run_refused_606.py::test_an_approve_or_a_cancel_with_dry_run_is_refused_and_changes_nothing
cmapi/tests/service/test_dry_run_refused_606.py::test_the_admin_writes_with_dry_run_are_refused_and_change_nothing
cmapi/tests/service/test_dry_run_refused_606.py::test_every_write_without_a_dry_run_refuses_one
cmapi/tests/service/test_dry_run_refused_606.py::test_the_writes_that_have_a_dry_run_still_answer_it
```

Codex session ID: 01a20a3e-33cd-76f1-b640-7ace50be99c3
Resume in Codex: codex resume 01a20a3e-33cd-76f1-b640-7ace50be99c3
