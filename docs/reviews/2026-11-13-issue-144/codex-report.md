# Review of issue #144, head a5ac4a5

Scope: the local `head/` export and `change.diff` only. No network, container, or PostgreSQL connection is used. TokenSave context/status/read rejected this unindexed export, so evidence comes from direct local source inspection. Paths below are relative to this review folder unless stated otherwise. Application/database tests are supplied for the author and are **NOT RUN** here; database-free configuration tests are run separately.


Verdicts: C1 CONFIRMED; C2 REFUTED (expired-key cleanup writes before the guard); C3 CONFIRMED; C4 REFUTED (type validation); C5 REFUTED only for the extra configured bit, with authorization confirmed; C6 CONFIRMED; C7 CONFIRMED. One additional documentation example defect is reproduced below.

Database-free validation: unchanged author configuration tests 17 passed; new regressions before fixes: C2 1 failed, C4 22 failed/23 passed, example 1 failed; after fixes in a separate copy: 47 passed. Logs are in report/c2-before.txt, report/c4-before.txt, report/extra-before.txt, report/existing-config-tests.txt and report/after-fixes.txt. The export was not edited. All proposed new fix/test files appear below in full.

## C1 — CONFIRMED: authorization precedes override disclosure

Evidence:

- `head/cmapi/src/cmapi/core/pipeline.py:175-176`: `self.cfg.roles.require(who, "namespaces:create" if action == "create" else "namespaces:write", env)` followed by `self.check_plugin_offered("namespaces", env)`.
- `head/cmapi/src/cmapi/core/pipeline.py:289-290`: `self.cfg.roles.require(who, "namespaces:write", env)` followed by `self.check_plugin_offered("namespaces", env)`.
- `head/cmapi/src/cmapi/plugins/namespaces/router.py:138`, `:162`, `:184`, `:201`: the write routes also depend on `require("namespaces:create")` or `require("namespaces:write")` before their bodies run.
- `head/cmapi/src/cmapi/routers/__init__.py:45-52`: `c.cfg.roles.require(who, permission)` runs in that dependency; an exception is re-raised.
- `head/cmapi/src/cmapi/core/authz.py:157-165`: `require` returns only when `self.allowed(who, permission, env)`; otherwise raises 403 `environment-forbidden` or `forbidden`.

A caller with no write permission receives 403 before `_replay` or the planner. A caller whose role grants writes only in another environment receives 403 from the planner before the override check. There is no demonstrated 422 `plugin-disabled` disclosure to such a caller. A successful idempotency replay skips the planner but does not reveal an override.

## C2 — REFUTED (P2): expired idempotency keys cause a committed row write before the guard

The normal new-request path is guarded correctly: POST and PATCH call `plan_namespace` before `_submit`; DELETE calls `plan_delete`; expiration:extend calls `plan_namespace(action="update", reason="expiration:extend")`. Those planners check the override before cache/Git access, row insertion, audit creation, or job enqueueing. But `_replay` has a hidden database write.

Evidence:

- `head/cmapi/src/cmapi/plugins/namespaces/router.py:146-153`: `replay = _replay(c, who, key, raw)` precedes `plan = c.pipeline.plan_namespace(...)` and `return _submit(...)`.
- `head/cmapi/src/cmapi/plugins/namespaces/router.py:170-177`, `:188-193`, `:212-217`: the same replay-before-plan order applies to PATCH, DELETE and expiration:extend.
- `head/cmapi/src/cmapi/plugins/namespaces/router.py:54-62`: `_replay` opens `with c.db.session() as s:`, calls `row = repo.by_idempotency(who.sub, key)`, and returns either `None` or `request_view(repo, row)`.
- `head/cmapi/src/cmapi/core/db/repo.py:121-126`: that lookup first executes `self.s.execute(update(ChangeRequestRow) ... .values(idempotency_key=None, idempotency_fingerprint=None, updated_at=ChangeRequestRow.updated_at))`, matching an expired key, then SELECTs it.
- `head/cmapi/src/cmapi/core/db/__init__.py:45-48`: the context manager does `yield s` followed by `s.commit()`. `_replay` therefore commits before the planner runs.
- `head/cmapi/src/cmapi/core/pipeline.py:176`, `:290`: only then does `self.check_plugin_offered("namespaces", env)` reject the disabled write.

Reproduction: create a request; make its `created_at` older than 24 hours; turn on the dev override; submit another write with that caller/key. `_replay` clears the old row's key and fingerprint and commits. The planner subsequently returns 422 `plugin-disabled`. No new request or job is inserted and no Git call is necessary, but an existing row **has been written** before the guard, contrary to the absolute claim.

For an unexpired, matching key, replay does return the existing request even while the override is on. It returns a current view of the stored request, not necessarily immutable bytes from the original response. The UPDATE matches zero rows in that case; no new request/event/audit/job or Git operation occurs. A different fingerprint gives 409. This successful replay is not a new write. For an expired key, it is not a successful replay: the cleanup write occurs even though the new write is rejected.

`dryRun` is implemented only for create and PATCH: `_idem` at `router.py:41-43` says `if dry_run: return None`, and `_replay` at `:52-53` then returns without a DB session. DELETE and expiration:extend do not accept/use a `dry_run` argument (`:183-184`, `:200-202`); appending `?dryRun=true` does not make them dry runs, and they retain the same guarded normal-write path. This is pre-existing behavior, not introduced by the diff. The supplied test checks all four operations with and without that query parameter.

Fix: make idempotency lookup SELECT-only, and clear expired keys after planning, inside `Pipeline.submit` after its serialization lock. Keep cleanup atomic with insertion so legitimate key reuse still works. The complete executable fix and tests follow. Apply the fix to a source directory, e.g. `python report/fix_c2.py <project>/cmapi/src`. No change has been applied to `head/`.

Validation: `test_c2_lookup.py` **failed before** with `Replay lookup attempted DML: UPDATE change_requests ...` and **passed after** against a copy under `report/fixed/`. It uses a fake Session and cannot connect to a DB. The full request-level tests below are **NOT RUN** because they require PostgreSQL; copy them into `cmapi/tests/service/` for the author to run with an exclusive database. Before the fix, the expired-key cases for every non-dry write, plus DELETE/extend with the ignored dryRun query, fail the snapshot assertion; after the fix they should pass. The live-replay and authorized-expired-key-reuse cases protect the intended behavior.

Full new file `report/fix_c2.py`:

```python
"""Move idempotency expiry cleanup into the authorized submit transaction."""
from pathlib import Path
import sys


def apply(source: Path):
    path = source / "cmapi/core/db/repo.py"
    text = path.read_text()
    start = text.index("    def by_idempotency(")
    end = text.index("    def auto_approvals_today(", start)
    replacement = '''    def by_idempotency(self, requester_sub: str, key: str) -> ChangeRequestRow | None:
        """Read a held key without changing rows before authorization and planning."""
        return self.s.scalars(select(ChangeRequestRow).where(
            ChangeRequestRow.requester_sub == requester_sub,
            ChangeRequestRow.idempotency_key == key,
            ChangeRequestRow.created_at >= func.now() - text(f"interval '{IDEMPOTENCY_HOURS} hours'"))).first()

    def clear_expired_idempotency(self, requester_sub: str, key: str) -> None:
        """Release an expired key only in the transaction submitting an authorized plan."""
        self.s.execute(update(ChangeRequestRow)
                       .where(ChangeRequestRow.requester_sub == requester_sub, ChangeRequestRow.idempotency_key == key,
                              ChangeRequestRow.created_at < func.now() - text(f"interval '{IDEMPOTENCY_HOURS} hours'"))
                       .values(idempotency_key=None, idempotency_fingerprint=None, updated_at=ChangeRequestRow.updated_at))

'''
    path.write_text(text[:start] + replacement + text[end:])
    path = source / "cmapi/core/pipeline.py"
    text = path.read_text()
    old = "        rid = repo.next_id()              # takes the day's advisory lock: submits are serial from here to the commit\n"
    new = old + '''        if idempotency_key is not None:
            repo.clear_expired_idempotency(who.sub, idempotency_key)
'''
    assert text.count(old) == 1
    path.write_text(text.replace(old, new))


if __name__ == "__main__":
    apply(Path(sys.argv[1]))
```

Full new file `report/test_c2_lookup.py`:

```python
"""Database-free proof that replay lookup must not execute DML."""
from cmapi.core.db.repo import RequestRepo


class NoRows:
    def first(self):
        return None


class ReadOnlySession:
    def execute(self, statement):
        assert statement.is_select, f"Replay lookup attempted DML: {statement}"
        return NoRows()

    def scalars(self, statement):
        assert statement.is_select
        return NoRows()


def test_replay_lookup_does_not_write_before_the_planner():
    assert RequestRepo(ReadOnlySession()).by_idempotency("sub-ola", "expired-key") is None
```

Full new file `report/test_c2_app.py`:

```python
"""Author-run service regressions. NOT RUN in this review: requires PostgreSQL.

Place in cmapi/tests/service to use its conftest.py; run against an exclusive test DB.
"""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from cmapi.core.db.models import AuditEventRow, ChangeRequestRow, JobRow, RequestEventRow
from cmapi.core.db.repo import utcnow
from cmapi.core.plugins import PluginSwitch
from test_flow import NS, OLA, auth

BASE = "/api/v1/clusters/CRC/namespaces"
DISABLED = {"enabled": ["namespaces"], "overrides": {"nonprod": {"dev": {"disabled": ["namespaces"]}}}}


def snapshot(ctx, rid):
    with ctx.db.session() as session:
        row = session.get(ChangeRequestRow, rid)
        return (row.idempotency_key, row.idempotency_fingerprint,
                tuple(session.scalar(select(func.count()).select_from(model))
                      for model in (ChangeRequestRow, RequestEventRow, JobRow, AuditEventRow)))


def no_git(*args, **kwargs):
    pytest.fail("A disabled write or an idempotency replay reached Git")


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("method, suffix, body", [
    ("POST", "", NS),
    ("PATCH", "/payments-dev", {"tier": "medium"}),
    ("DELETE", "/payments-dev", None),
    ("POST", "/payments-dev/expiration:extend", {"days": 7}),
])
def test_disabled_write_keeps_expired_key_and_all_rows(world, monkeypatch, method, suffix, body, dry_run):
    client, ctx, git, _, _, keys = world
    headers = auth(keys, "ola", **OLA)
    created = client.post(BASE, json=NS, headers=headers)
    assert created.status_code == 202, created.text
    rid = created.json()["requestId"]
    with ctx.db.session() as session:
        session.get(ChangeRequestRow, rid).created_at = utcnow() - timedelta(hours=25)
    ctx.cfg.plugins = PluginSwitch(DISABLED, "nonprod", {"dev", "rnd"})
    before = snapshot(ctx, rid)
    monkeypatch.setattr(git, "read_folder", no_git)
    monkeypatch.setattr(git, "open_pr", no_git)
    path = BASE + suffix + ("?dryRun=true" if dry_run else "")
    result = client.request(method, path, json=body, headers={**headers, "If-Match": '"0000000000000000"'})
    assert result.status_code == 422, result.text
    assert result.json()["code"] == "plugin-disabled"
    assert snapshot(ctx, rid) == before


def test_live_replay_still_returns_existing_request_without_new_writes(world, monkeypatch):
    client, ctx, git, _, _, keys = world
    headers = auth(keys, "ola", **OLA)
    created = client.post(BASE, json=NS, headers=headers)
    assert created.status_code == 202, created.text
    rid = created.json()["requestId"]
    before = snapshot(ctx, rid)
    ctx.cfg.plugins = PluginSwitch(DISABLED, "nonprod", {"dev", "rnd"})
    monkeypatch.setattr(git, "read_folder", no_git)
    monkeypatch.setattr(git, "open_pr", no_git)
    replay = client.post(BASE, json=NS, headers=headers)
    assert replay.status_code == 202, replay.text
    assert replay.json()["requestId"] == rid
    assert snapshot(ctx, rid) == before


def test_authorized_submission_can_reuse_expired_key(world):
    client, ctx, _, _, _, keys = world
    headers = auth(keys, "ola", **OLA)
    created = client.post(BASE, json=NS, headers=headers)
    assert created.status_code == 202, created.text
    old_rid = created.json()["requestId"]
    with ctx.db.session() as session:
        session.get(ChangeRequestRow, old_rid).created_at = utcnow() - timedelta(hours=25)
    replacement = client.post(BASE, json={**NS, "namespace": "payments-next"}, headers=headers)
    assert replacement.status_code == 202, replacement.text
    assert replacement.json()["requestId"] != old_rid
    with ctx.db.session() as session:
        assert session.get(ChangeRequestRow, old_rid).idempotency_key is None
        assert session.get(ChangeRequestRow, replacement.json()["requestId"]).idempotency_key == headers["Idempotency-Key"]
```

## C3 — CONFIRMED: disabled quotas router is not mounted

Evidence:

- `head/cmapi/src/cmapi/main.py:94-96`: `authed_routers = (me.router, requests.router, admin.router, *ctx.cfg.plugins.routers())`, then `app.include_router(r, dependencies=[Depends(authed)])`.
- `head/cmapi/src/cmapi/core/plugins.py:109-112`: `for name, target in BUILT_IN.items():` and `if name in self.enabled:` guard the import and append.
- `head/cmapi/src/cmapi/plugins/quotas/__init__.py:21`: `prefix="/api/v1"`; its complete route set is `@router.read("/quotas", ...)` at line 98, `@router.read("/quotas:suggest", ...)` at line 118, and `@router.read("/quotas:export", ...)` at line 126.
- Local source search finds `include_router` only at `head/cmapi/src/cmapi/main.py:91`, `:92`, `:96`; there is no separate quotas inclusion.

With `enabled: [namespaces, tiers, directory]`, GET `/api/v1/quotas`, `/api/v1/quotas:suggest`, and `/api/v1/quotas:export` all resolve to 404, including query-string variants. The author’s test covers list and export but omits suggest. This conclusion is from code; no app was run.

## C4 — REFUTED (P2): malformed structures can disappear; mixed unknown keys escape as TypeError

Evidence:

- `head/cmapi/src/cmapi/core/plugins.py:49`: `for key in sorted(set(raw) - {"enabled", "overrides"}):` compares unknown keys without constraining their types. YAML containing both `1: ignored` and `extra: ignored` raises `TypeError: '<' not supported between instances of 'str' and 'int'`.
- `head/cmapi/src/cmapi/core/plugins.py:55`: `overrides = raw.get("overrides") or {}` changes `[]`, `false`, `0`, and `''` into `{}` before the Mapping check.
- `head/cmapi/src/cmapi/core/plugins.py:59`: `mine = overrides.get(instance) or {}` does the same for a malformed current-instance block. Non-string instance keys are never checked and cannot match the ordinary string `instance`; e.g. `overrides: {7: {dev: {disabled: [namespaces]}}}` is accepted while `offers("namespaces", "dev")` stays true.
- `head/cmapi/src/cmapi/core/plugins.py:65-69`: an environment outside `allowed_environments` is reported with its path; a null environment block is refused by `not isinstance(block, Mapping)`.
- `head/cmapi/src/cmapi/core/plugins.py:84-86`: `if not isinstance(value, list) or not all(isinstance(v, str) for v in value):` appends a path-specific error and returns **before** `dict.fromkeys`, safely rejecting booleans, integers and nested lists.
- `head/cmapi/src/cmapi/core/config.py:70-74`: `except (ValueError, CatalogError) as exc:` collects validation failures; the mixed-key TypeError escapes it.

Observed results for the requested inputs (through both PluginSwitch and the real configuration loader):

| Input | Result before fix |
|---|---|
| `enabled: null` | ValueError naming `enabled`; loader produces ConfigError naming plugins.yaml |
| `enabled: [1, true]` | Same |
| `enabled: {namespaces: true}` | Same |
| `overrides: {nonprod: [dev]}` with valid enabled | ValueError naming `overrides.nonprod` |
| `overrides: {nonprod: {dev: null}}` | ValueError naming `overrides.nonprod.dev` |
| `overrides: {nonprod: {dev: {disabled: null}}}` | ValueError naming `overrides.nonprod.dev.disabled` |
| `overrides: {nonprod: {dev: {disabled: [[namespaces]]}}}` | Same; no unhashable-list exception |
| Environment key `on:` | PyYAML reads True; ValueError naming `overrides.nonprod.True`, even when the allowed string environment is `on` |
| Environment key `7:` | ValueError naming `overrides.nonprod.7` |
| Instance key `7:` (also `on:`) | Accepted and silently ignored; no diagnostic |
| Empty list/false/zero/empty-string overrides or current-instance block | Accepted and silently normalized to no override |
| Top-level unknown keys `1:` and `extra:` together | Uncaught TypeError |

There is no observed coercion that wrongly enables an entry of `enabled`: `_names` is sound for these YAML types. The failures are structural validation and error collection. Numeric/boolean instance keys are schema mistakes, not evidence of a cross-instance security bypass: the current instance is still a distinct string name. The problem is that the advertised fail-fast validation silently accepts those mistakes. Null optional overrides/current-instance blocks are retained as harmless empty blocks by the proposed fix, while null `disabled` remains invalid.

Fix: normalize only None, reject other non-mappings (including falsey ones), validate instance/environment key types, and sort unknown keys with `key=repr` so diagnostics cannot raise comparison TypeError. Continue to leave other instances' environment blocks unvalidated, as the documented shared-file design requires.

Validation: `report/test_c4_validation.py` ran without a DB against the unchanged export: **22 failed, 23 passed** (the failures occur at both the direct constructor and loader for the 11 accepted/error-escape cases). The same full file against the fixed source copy: **45 passed**. Original author tests restricted to the three sample loads and loader validation tests: **17 passed, 9 deselected**, on the unchanged export. No database fixture was selected. Complete fix and test files follow; run `python report/fix_c4.py <project>/cmapi/src` to apply the fix.

Full new file `report/fix_c4.py`:

```python
"""Apply the C4 fix to a supplied cmapi source directory (not to the export by default)."""
from pathlib import Path
import sys


def apply(source: Path):
    path = source / "cmapi/core/plugins.py"
    text = path.read_text()
    old = 'for key in sorted(set(raw) - {"enabled", "overrides"}):'
    new = 'for key in sorted(set(raw) - {"enabled", "overrides"}, key=repr):'
    assert text.count(old) == 1
    text = text.replace(old, new)
    old = '''        overrides = raw.get("overrides") or {}
        if not isinstance(overrides, Mapping):
            problems.append("overrides: must be a mapping of instance, then environment")
            overrides = {}
        mine = overrides.get(instance) or {}
        if not isinstance(mine, Mapping):
            problems.append(f"overrides.{instance}: must be a mapping of environment to `disabled`")
            mine = {}
        for env, block in mine.items():
            where = f"overrides.{instance}.{env}"
            if env not in allowed_environments:
'''
    new = '''        overrides = raw.get("overrides")
        if overrides is None:
            overrides = {}
        if not isinstance(overrides, Mapping):
            problems.append("overrides: must be a mapping of instance, then environment")
            overrides = {}
        for key in overrides:
            if not isinstance(key, str):
                problems.append(f"overrides.{key}: instance key must be a string")
        mine = overrides.get(instance)
        if mine is None:
            mine = {}
        if not isinstance(mine, Mapping):
            problems.append(f"overrides.{instance}: must be a mapping of environment to `disabled`")
            mine = {}
        for env, block in mine.items():
            where = f"overrides.{instance}.{env}"
            if not isinstance(env, str):
                problems.append(f"{where}: environment key must be a string")
                continue
            if env not in allowed_environments:
'''
    assert text.count(old) == 1
    path.write_text(text.replace(old, new))


if __name__ == "__main__":
    apply(Path(sys.argv[1]))
```

Full new file `report/test_c4_validation.py`:

```python
"""Database-free regression tests for malformed plugins.yaml values."""
from pathlib import Path

import pytest
import yaml

from cmapi.core.config import ConfigError, load_instance
from cmapi.core.plugins import PluginSwitch

EXAMPLES = Path(__file__).resolve().parents[1] / "head" / "examples"
ALL = "[namespaces, tiers, directory, quotas]"

CASES = [
    ("enabled: null", "enabled"),
    ("enabled: [1, true]", "enabled"),
    ("enabled: {namespaces: true}", "enabled"),
    (f"enabled: {ALL}\noverrides: {{nonprod: [dev]}}", "overrides.nonprod"),
    (f"enabled: {ALL}\noverrides: {{nonprod: {{dev: null}}}}", "overrides.nonprod.dev"),
    (f"enabled: {ALL}\noverrides: {{nonprod: {{dev: {{disabled: null}}}}}}", "overrides.nonprod.dev.disabled"),
    (f"enabled: {ALL}\noverrides: {{nonprod: {{dev: {{disabled: [[namespaces]]}}}}}}", "overrides.nonprod.dev.disabled"),
    (f"enabled: {ALL}\noverrides: {{nonprod: {{on: {{disabled: [namespaces]}}}}}}", "overrides.nonprod.True"),
    (f"enabled: {ALL}\noverrides: {{nonprod: {{7: {{disabled: [namespaces]}}}}}}", "overrides.nonprod.7"),
    (f"enabled: {ALL}\noverrides: {{7: {{dev: {{disabled: [namespaces]}}}}}}", "overrides.7"),
    (f"enabled: {ALL}\noverrides: {{on: {{dev: {{disabled: [namespaces]}}}}}}", "overrides.True"),
    (f"enabled: {ALL}\noverrides: []", "overrides"),
    (f"enabled: {ALL}\noverrides: false", "overrides"),
    (f"enabled: {ALL}\noverrides: 0", "overrides"),
    (f"enabled: {ALL}\noverrides: ''", "overrides"),
    (f"enabled: {ALL}\noverrides: {{nonprod: []}}", "overrides.nonprod"),
    (f"enabled: {ALL}\noverrides: {{nonprod: false}}", "overrides.nonprod"),
    (f"enabled: {ALL}\noverrides: {{nonprod: 0}}", "overrides.nonprod"),
    (f"enabled: {ALL}\noverrides: {{nonprod: ''}}", "overrides.nonprod"),
    (f"enabled: {ALL}\n1: ignored\nextra: ignored", "unknown key"),
]


@pytest.mark.parametrize("text, place", CASES)
def test_malformed_yaml_value_names_its_place(text, place):
    with pytest.raises(ValueError) as caught:
        PluginSwitch(yaml.safe_load(text), "nonprod", {"dev", "rnd", "on"})
    assert place in str(caught.value)


@pytest.mark.parametrize("text, place", CASES)
def test_loader_collects_the_error_as_plugins_yaml(tmp_path, text, place):
    source = EXAMPLES / "instances" / "nonprod"
    for name in ("instance.yaml", "approval-rules.yaml", "authz-roles.yaml", "tiers.yaml", "expiration.yaml"):
        (tmp_path / name).write_text((source / name).read_text())
    (tmp_path / "plugins.yaml").write_text(text)
    metadata = EXAMPLES / "cluster-configs" / "policies" / "metadata-keys.yaml"
    with pytest.raises(ConfigError) as caught:
        load_instance(tmp_path, metadata)
    assert any(p.startswith("plugins.yaml: ") and place in p for p in caught.value.problems)


@pytest.mark.parametrize("overrides", [None, {}, {"nonprod": None}, {"nonprod": {}}])
def test_empty_optional_overrides_remain_valid(overrides):
    switch = PluginSwitch({"enabled": ["namespaces"], "overrides": overrides}, "nonprod", {"dev"})
    assert switch.offers("namespaces", "dev")


def test_other_instances_environments_are_not_validated():
    switch = PluginSwitch({"enabled": ["namespaces"], "overrides": {
        "prod": {"prod": {"disabled": ["namespaces"]}},
        "nonprod": {"dev": {"disabled": ["namespaces"]}},
    }}, "nonprod", {"dev"})
    assert not switch.offers("namespaces", "dev")
```

## C5 — REFUTED narrowly: authorization is correct; file presence is one extra disclosed bit

The valid-token and `clusters:read` requirements are **confirmed**, exactly as integrations:

- `head/cmapi/src/cmapi/main.py:94-96`: the admin router is included with `dependencies=[Depends(authed)]`.
- `head/cmapi/src/cmapi/core/auth.py:185-190`: missing tokens raise `Problem(401, "unauthenticated", "Bearer token required")`; otherwise `request.app.state.auth.authenticate(token)` verifies the token.
- `head/cmapi/src/cmapi/routers/admin.py:171-172`: integrations declares and enforces `permission="clusters:read"` and `Depends(require("clusters:read"))`.
- `head/cmapi/src/cmapi/routers/admin.py:181-182`: plugins declares and enforces the identical permission/dependency.
- `head/cmapi/src/cmapi/routers/__init__.py:45-52`: `c.cfg.roles.require(who, permission)` enforces that dependency; this is executable authorization, not just OpenAPI documentation.

The “nothing else except override environments” portion is literally false:

- `head/cmapi/src/cmapi/routers/admin.py:192`: `return {"instance": c.cfg.name, "configured": switch.configured, "items": core + built_in}` includes **configured**.
- `head/cmapi/src/cmapi/core/plugins.py:44`: `self.configured = raw is not None` records the presence of the configuration file.
- `head/cmapi/src/cmapi/main.py:58-59`: `description=f"The {ctx.cfg.name} instance serves {sorted(ctx.cfg.allowed_environments)}. "` already discloses the instance and its served environments in OpenAPI.
- `head/cmapi/src/cmapi/core/docs.py:332-335`: tags include `{"name": name, ... "x-plugin-version": r.version}` for the mounted plugins.
- `head/cmapi/src/cmapi/core/docs.py:385-395`: recorded examples come from the static `samples` input, ending with `media["example"] = response["body"]`; they are not live values of `switch.configured`.

Absent plugins.yaml and a present file enabling every built-in plugin with no overrides mount identical routers, yield identical OpenAPI documents, and use the same BUILT_IN names. Yet the actual endpoint returns configured=false in one deployment and configured=true in the other. An OpenAPI schema/example saying that a boolean exists does not reveal its live value. All the plugin names, mounted status, core classification and versions are otherwise derivable from OpenAPI plus the known built-in/core distinction. This extra bit is an informational mismatch with the exact claim, **not an authorization vulnerability** or evidence that configuration file presence is secret.

Override environments are operational availability information, not documented secrets under docs/14-authorization.md. `head/docs/14-authorization.md:41` says `clusters:read` is available even to viewers; `:87` explicitly puts both integrations and plugins under that permission. `:170`, `:174-182` describe environment limits for object/request actions and filtered lists, not secrecy of instance deployment metadata. `head/cmapi/src/cmapi/routers/me.py:24-28` already returns `st.view()` for every known cluster to a `clusters:read` holder, and `routers/admin.py:175-178` returns integration modes and the full cluster status map under the same permission. Environment **names** already occur in the OpenAPI description; which plugin stops writes in them is additional useful availability state. Nothing in this authorization document requires treating that state as sensitive or raising this endpoint to an admin-only permission. This does not imply every environment-scoped object is readable: the documented row-level permission checks still apply.

To satisfy the literal no-extra-data claim, remove configured from the response model and response and update its recorded/contract examples and existing default-file test. Keep PluginSwitch.configured internally for startup logging. Alternatively the claim could explicitly permit the configured bit; that would be a specification clarification rather than a security fix. The complete code fix below implements removal, so there is a concrete testable option.

The full application counterexample and token/permission parity test below are **NOT RUN**: they use the service suite and fresh_db. The counterexample is expected to fail before at the final equality assertion, with configured false versus true; with the proposed fix it should pass. The OpenAPI equality assertion ensures the test actually demonstrates extra information beyond the specification. Copy the test into `cmapi/tests/service/` for the author to run against an exclusive database. `fix_c5.py` was applied successfully to the local source copy and syntax-checked; no endpoint execution or claim of app-test success is made. Apply it as `python report/fix_c5.py <project>` (the directory containing cmapi/).

Full new file `report/fix_c5.py`:

```python
"""Remove the extra file-presence disclosure to satisfy C5 literally.

Pass the exported project directory (containing cmapi/), not its src directory.
"""
import json
from pathlib import Path
import sys


def apply(project: Path):
    path = project / "cmapi/src/cmapi/routers/admin.py"
    text = path.read_text()
    old = '''    configured: bool = Field(description="False when the instance has no `plugins.yaml`: each built-in plugin is then enabled",
                             examples=[True])
'''
    assert text.count(old) == 1
    text = text.replace(old, "")
    old = '    return {"instance": c.cfg.name, "configured": switch.configured, "items": core + built_in}'
    new = '    return {"instance": c.cfg.name, "items": core + built_in}'
    assert text.count(old) == 1
    path.write_text(text.replace(old, new))
    path = project / "cmapi/src/cmapi/contract/samples.json"
    data = json.loads(path.read_text())
    # The file's top-level container is discovered without assuming its name.
    samples = data if "admin_plugins" in data else next(
        value for value in data.values() if isinstance(value, dict) and "admin_plugins" in value)
    samples["admin_plugins"]["response"]["body"].pop("configured")
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    contract = project / "cmapi/contract/openapi.json"
    if contract.exists():
        spec = json.loads(contract.read_text())
        schema = spec["components"]["schemas"]["PluginList"]
        schema["properties"].pop("configured", None)
        schema["required"] = [key for key in schema["required"] if key != "configured"]
        media = spec["paths"]["/api/v1/admin/plugins"]["get"]["responses"]["200"]["content"]["application/json"]
        if "example" in media:
            media["example"].pop("configured", None)
        contract.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    path = project / "cmapi/tests/service/test_plugins_switch.py"
    text = path.read_text()
    old = '    assert listed["configured"] is False and listed["instance"] == "nonprod"'
    new = '    assert listed["instance"] == "nonprod" and "configured" not in listed'
    assert text.count(old) == 1
    path.write_text(text.replace(old, new))


if __name__ == "__main__":
    apply(Path(sys.argv[1]))
```

Full new file `report/test_c5_app.py`:

```python
"""Author-run service regressions. NOT RUN here: uses build_world/fresh_db.

Place in cmapi/tests/service to use its conftest.py; run against an exclusive test DB.
"""
import pytest
import yaml

from conftest import build_world
from test_flow import auth

ALL = ["namespaces", "tiers", "directory", "quotas"]
VIEWER = {"roles": ["cmapi-viewer"]}


def test_equal_openapi_and_builtin_names_do_not_reveal_file_presence(test_config, tmp_path, fresh_db, keys, monkeypatch):
    outputs = []
    for index, configured in enumerate((False, True)):
        folder = tmp_path / str(index)
        folder.mkdir()
        for original in test_config.iterdir():
            if original.name != "plugins.yaml":
                (folder / original.name).write_text(original.read_text())
        if configured:
            (folder / "plugins.yaml").write_text(yaml.safe_dump({"enabled": ALL}))
        with build_world(folder, keys, monkeypatch) as (client, *_):
            headers = auth(keys, "viewer", **VIEWER)
            spec = client.get("/openapi.json", headers=headers)
            listed = client.get("/api/v1/admin/plugins", headers=headers)
            assert spec.status_code == listed.status_code == 200
            outputs.append((spec.json(), listed.json()))
    assert outputs[0][0] == outputs[1][0], "The counterexample needs identical OpenAPI documents"
    assert outputs[0][1] == outputs[1][1], "plugins.yaml presence is extra information beyond OpenAPI"


@pytest.mark.parametrize("path", ["/api/v1/admin/plugins", "/api/v1/admin/integrations"])
def test_admin_read_requires_valid_token_and_clusters_read(world, path):
    client, _, _, _, _, keys = world
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.get(path, headers=auth(keys, "relay", roles=["cmapi-approval-relay"])).status_code == 403
    assert client.get(path, headers=auth(keys, "viewer", **VIEWER)).status_code == 200
```

## C6 — CONFIRMED: default router order is preserved

Evidence:

- `change.diff:349` (removed source line): `authed_routers = (me.router, requests.router, admin.router, namespaces_router, tiers_router, directory_router, quotas_router)`.
- `head/cmapi/src/cmapi/core/config.py:95-99`: absent file selects `PluginSwitch(None, me["name"], allowed)`.
- `head/cmapi/src/cmapi/core/plugins.py:46`: `raw = raw if raw is not None else {"enabled": list(BUILT_IN)}`.
- `head/cmapi/src/cmapi/core/plugins.py:28-33`: `BUILT_IN` insertion order is `namespaces`, `tiers`, `directory`, `quotas`.
- `head/cmapi/src/cmapi/core/plugins.py:109-112`: routers follow `BUILT_IN.items()`, independent of configured list order.
- `head/cmapi/src/cmapi/main.py:94`: core order remains `me.router, requests.router, admin.router` before the plugins.

The resulting order is me, requests, admin, namespaces, tiers, directory, quotas. Health and version remain ahead of them. This confirms the router-mounting claim, not byte-for-byte unchanged API behavior: the new admin endpoint and documented plugin-disabled response are intentional additions.

## C7 — CONFIRMED: existing jobs do not re-enter either planner

Evidence:

- `head/cmapi/src/cmapi/worker.py:91`, `:101`: `handler = HANDLERS.get(kind)` and `handler(self.ctx, s, job)` dispatch directly to the job handler.
- `head/cmapi/src/cmapi/jobs/__init__.py:10-18`: handlers are `open_pr`, `open_revert`, `pr_checks`, `watch_sync`, `prune`, `approval_timeout`, `channel_notify`.
- `head/cmapi/src/cmapi/jobs/open_pr.py:34`, `:41`, `:45`, `:54`: `plan = row.plan`, `files = plan["files"]`, optional `ctx.pipeline.renderer.render(...)`, and `ctx.git.open_pr(...)` use the stored plan.
- `head/cmapi/src/cmapi/jobs/open_pr.py:107-110`: revert constructs `Plan(...)` directly and calls `ctx.pipeline.submit(...)` with `idempotency_key=None`; it does not call a planner.
- `head/cmapi/src/cmapi/jobs/pr_checks.py:67`: `ctx.pipeline.validator.validate(tree, row.cluster_id, row.env)` calls the validator directly.
- Source search across worker and every jobs module finds no `plan_namespace`, `plan_delete`, or `check_plugin_offered` call. The only calls to the new guard are `head/cmapi/src/cmapi/core/pipeline.py:176`, `:290`.

An override cannot stop an already approved request’s queued work. No job newly raises `plugin-disabled` because of this change; ordinary existing failures (Git unavailable, validation failure, plan hash mismatch, and so on) remain possible. Invalid plugins.yaml can prevent worker context construction at startup, which is distinct from a running handler raising on an override. Application execution was not run.

## Additional finding — REFUTED (P3): the new module's configuration example is valid

Evidence:

- `head/cmapi/src/cmapi/core/plugins.py:3-7` advertises:

  ```yaml
  enabled: [namespaces, quotas, tiers, directory]
  overrides:
    nonprod:
      dev:
        disabled: [quotas]
  ```

- `head/cmapi/src/cmapi/core/plugins.py:35`: `WRITERS: frozenset[str] = frozenset({"namespaces"})`.
- `head/cmapi/src/cmapi/core/plugins.py:75-76`: `elif name in BUILT_IN and name not in WRITERS:` appends `f"{where}.disabled: {name} has no write, so the override changes nothing"`.

Copying the newly added example stops startup instead of demonstrating a supported override. Fix the example to disable namespaces. The database-free test below parses the actual module docstring and constructs PluginSwitch, so it catches drift in the advertised example. It **failed before** with `ValueError: overrides.nonprod.dev.disabled: quotas has no write, so the override changes nothing` and **passed after**. The complete fix/test files follow; run `python report/fix_extra_example.py <project>/cmapi/src` to apply it.

Full new file `report/fix_extra_example.py`:

```python
"""Correct the module's example to disable a plugin that actually writes."""
from pathlib import Path
import sys


def apply(source: Path):
    path = source / "cmapi/core/plugins.py"
    text = path.read_text()
    old = "          disabled: [quotas]"
    assert text.count(old) == 1
    path.write_text(text.replace(old, "          disabled: [namespaces]"))


if __name__ == "__main__":
    apply(Path(sys.argv[1]))
```

Full new file `report/test_extra_example.py`:

```python
"""The module's advertised plugins.yaml example must load and stop a writer."""
import yaml
from cmapi.core import plugins


def test_documented_override_example_is_accepted():
    example = plugins.__doc__.split("\n", 1)[1].split("\n`enabled`", 1)[0]
    switch = plugins.PluginSwitch(yaml.safe_load(example), "nonprod", {"dev"})
    assert not switch.offers("namespaces", "dev")
```
