# Review brief: cmapi PR for issue #144 (plugins.yaml), head a5ac4a5

You are the second reader of one change. Work only in this folder. `head/` is an export of the commit (not a git repository). `change.diff` is the diff of the source and the new test file against the base. Do not use the network. Do not start a container. Do NOT connect to the PostgreSQL on 127.0.0.1:55432: another test run uses that database now, and a second run would truncate its tables. A test that needs no database (the configuration loader, `PluginSwitch`) can run with `PYTHONPATH=head/cmapi/src:head/cmapi/tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest -p no:cacheprovider`. For a claim that needs the app, reason from the code, write the full test, and say that it was not run: the author runs it.

Write your report to the ABSOLUTE path `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run2/review-144/report/report.md` as you go, one section per claim: verdict CONFIRMED or REFUTED, the evidence as `file:line` with the quoted lines, and for each REFUTED claim the full code of a fix and the full code of a test that fails before the fix and passes after it. A finding with no failing test does not count. Put new files in the report as full text.

## The change
`head/cmapi/src/cmapi/core/plugins.py` (new) reads `config/plugins.yaml`. `core/config.py` loads it. `main.py` mounts only the routers of enabled plugins. `core/pipeline.py` refuses a write of a plugin that an override disables in the cluster's environment. `routers/admin.py` adds `GET /api/v1/admin/plugins`.

## Claims to confirm or refute, exactly

C1. Authorization order. In `head/cmapi/src/cmapi/core/pipeline.py`, `Pipeline.plan_namespace` (about lines 169 to 177) and `Pipeline.plan_delete` (about lines 284 to 291) call `self.cfg.roles.require(...)` BEFORE `self.check_plugin_offered("namespaces", env)`. Expected: a caller without the permission gets 403 and never learns the override. Refute it with a request that returns 422 `plugin-disabled` to a caller who lacks the permission.

C2. No bypass of an override. Every route of `head/cmapi/src/cmapi/plugins/namespaces/router.py` that writes (POST create, PATCH, DELETE, POST expiration:extend, with and without `dryRun`) reaches `check_plugin_offered` before it writes a row, enqueues a job or calls Git. In particular check `_replay` (idempotency replay, lines 53 to 64), which runs BEFORE the planner: say whether a replay of an earlier key returns the stored request while the override is on, and whether that is a write. Expected: a replay returns an existing request and writes nothing new.

C3. A plugin that is not enabled is unreachable. With `enabled: [namespaces, tiers, directory]`, no route of `plugins/quotas/__init__.py` is mounted by `create_app` in `head/cmapi/src/cmapi/main.py` (lines 90 to 101), and nothing else includes that router. Expected: 404 for each quotas path.

C4. The validation in `PluginSwitch.__init__` and `PluginSwitch._names` (`core/plugins.py`) cannot be passed by a YAML value of another type so that a plugin is wrongly enabled, an override is silently dropped, or the process raises an exception that is not `ValueError` (config.py's `build` catches only `ValueError` and `CatalogError`). Try: `enabled: null`, `enabled: [1, true]`, `enabled: {namespaces: true}`, `overrides: {nonprod: [dev]}`, `overrides: {nonprod: {dev: null}}`, `overrides: {nonprod: {dev: {disabled: null}}}`, `overrides: {nonprod: {dev: {disabled: [[namespaces]]}}}`, an environment key that YAML reads as a boolean (`on:`) or a number, and the instance key as a number. Expected: each is a `ValueError` whose text names the place, or is handled with no wrong enablement.

C5. `GET /api/v1/admin/plugins` (`routers/admin.py`, function `plugins`) needs a valid token and the permission `clusters:read`, as `GET /api/v1/admin/integrations` does, and returns nothing that a holder of `clusters:read` could not already read from `/openapi.json` plus the names in `BUILT_IN`, except the override environments. Say whether the override environments are sensitive given `docs/14-authorization.md`.

C6. Behaviour without the file is unchanged. With no `plugins.yaml`, `create_app` mounts the same routers in the same order as before the change: me, requests, admin, namespaces, tiers, directory, quotas (see the removed line in `change.diff`).

C7. The worker. `head/cmapi/src/cmapi/worker.py` and `head/cmapi/src/cmapi/jobs/` never call `plan_namespace` or `plan_delete`, so an override cannot stop a job of a request that was approved before the override. Expected: confirmed, and say if any job would now raise.

Also report anything else in `change.diff` that is wrong, with the same standard of proof.
