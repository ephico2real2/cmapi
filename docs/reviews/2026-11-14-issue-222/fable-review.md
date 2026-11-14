# Fable review of PR #233 (ephico2real2/cmapi)

Reviewer: Fable 5.2. Head `ba9e3e2`, main `962d7f8`. Reviewed on 2026-11-14 in a `git archive` export; nothing was pushed or edited in the repository.

Who wrote what: `c8f20de` (`core/channels.py` and `tests/service/test_email_links.py`) is Fable 5.2's, cherry-picked from an earlier run. `ba9e3e2` (docs/02, the three `instance.yaml` comments, `values.yaml`) is Opus 5.5's. Both were reviewed. The code change is therefore reviewed by the same model family that wrote it, so it is not an independent read of `channels.py`.

## Verdict: changes needed (small)

The change to `channels.py` does what #222 asks, and nothing in the PR changes behaviour beyond the two links. Two things should change before merge: the tests do not fail on the old code for the reason they claim (F2), and one comment and one docs sentence say something the shipped portal does not do (F1, F4). F1's code fix and F3 are separate defects that this PR exposes; they can go to their own issues.

All pytest runs went through `ob1-run5/tools/suite.sh` (the lock), on the Mac's test database, not on kind or CRC.

## The five checks

| # | Question | Result |
|---|---|---|
| 1 | Where does the name come from? | `ctx.cfg.name`, which is `instance.name` of `instance.yaml` (`core/config.py:63,112`). It is the same value the API answers as `instance` (`routers/health.py:58`, `routers/me.py:21`). It cannot be another instance's name: one process loads one `instance.yaml`. |
| 1 | Can it be empty, or unsafe in a fragment? | Yes to both. Nothing checks it: see F3. |
| 2 | Do the tests pass on the head? | Yes: `5 passed in 0.85s`. |
| 2 | Do they fail on main's `channels.py`? | Yes, 5 failed, but for the wrong reason: see F2. |
| 2 | Both links, three instances? | Yes: both links, for `prod`, `staging`, `nonprod` and `emea-lab`. |
| 3 | The four citations | All four are right at `ba9e3e2`: `core/config.py:108`, `core/render/manifests.py:92` (in `render`; #222 said 90, the docs give no line), `plugins/expiration/rules.py:87`, `core/validate/__init__.py:84` (in `_kyverno`). |
| 3 | Is the list complete? | Yes for the service's Python. `grep -rnE "[\"'](prod\|nonprod\|staging\|production)[\"']" cmapi/src` returns those four sites, plus five `examples=["nonprod"]` in OpenAPI fields. One literal instance name is read elsewhere: see F4. |
| 4 | #232 and its source | GitLab is quoted correctly (five tiers, guessed from the name, `deployment_tier` overrides; fetched 2026-11-14). The design has one contradiction: see F5. |
| 5 | Behaviour beyond the links | None. `EmailChannel` has one caller (`channels_for`, `channels.py:89`); the rest is comments and docs. |

## Findings

### F1. Medium. The shipped portal does not read `#<instance>/<tab>`; both links open the first tab

`cmapi/src/cmapi/core/channels.py:39` (the comment "The portal's address has the instance first") and `:47`, `:80`; `cmapi-portal-ui/src/portal/route.ts:22-25`.

Not caused by this PR: `#nonprod/approvals` has the same fault on main. But the PR's comment and test name ("each link opens the view of the instance that sent it") state it as true. `#<instance>/<tab>` is the address of the demo build only (`src/model/usePortal.ts:8`, options `nonprod`, `staging`, `prod`). `vite build` ships `PortalApp`, which uses `route.ts` and reads `#<tab>?query`.

Evidence (the `read()` of `route.ts` at `ba9e3e2`, run in node):

```
$ node route-probe.mjs
#prod/approvals?request=req-1&link=1.abc -> {"tab":null,"request":"req-1"}
#nonprod/requests?request=req-1 -> {"tab":null,"request":"req-1"}
#approvals?request=req-1&link=1.abc -> {"tab":"approvals","request":"req-1"}
```

A null tab falls to `tabs[0]` (`PortalApp.tsx:146`). Also not built: no tab reads `request` or `link` (`RequestsTab.tsx:18-19` reads only `q` and `state`).

Fix, in `cmapi-portal-ui/src/portal/route.ts`, replacing `read()`:

```ts
function read(): Route {
  const [path, query = ""] = location.hash.slice(1).split("?");
  // An emailed link has the instance first ("#prod/approvals?request=…", core/channels.py). The tab is the last segment.
  const name = path.slice(path.lastIndexOf("/") + 1);
  return { tab: (TAB_IDS as readonly string[]).includes(name) ? (name as TabId) : null, params: new URLSearchParams(query) };
}
```

Test, measured (`pr-233-files/route-probe-fixed.mjs`, the old and new logic on six hashes):

```
  before: #prod/approvals?request=req-1&link=1.abc -> null, wanted approvals
  before: #emea-lab/requests?request=req-1 -> null, wanted requests
before: 4 passed, 2 failed
after: 6 passed, 0 failed
```

The check for `tests/api/portal.test.mjs`, after the check at line 339. Written, not run (it needs the portal build and Playwright):

```js
  await check("an emailed link, with the instance first, opens its tab", async () => {
    const { page } = await fresh({ user: "approver" });
    await page.goto(`${portal.page}#prod/approvals?request=req-1&link=1.abc`);
    const selected = await page.getByRole("tab", { selected: true }).innerText();
    assert.equal(selected, "Approvals");
  });
```

Recommended: file this as its own defect under #222, and in this PR change the comment at `channels.py:39` to say which build reads the address.

### F2. Low. The tests fail on the old code because of the signature, not because of the link

`cmapi/tests/service/test_email_links.py:16,32`.

Evidence (the PR's test on main's `channels.py`, under the lock):

```
5 failed in 0.91s
   1 E       AttributeError: 'EmailChannel' object has no attribute 'instance'
   4 E       TypeError: EmailChannel.__init__() got an unexpected keyword argument 'instance'
```

No assertion about `#nonprod` runs on the old code, so "5 failed before" does not show the defect. The `nonprod` case would pass on the old links.

Fix: add `pr-233-files/test_email_links_by_assertion.py` (through `channels_for` alone, so the old code runs to the assertion):

```python
"""The same claim as test_email_links.py, through channels_for alone, so that the old code fails on the link's text (#222)."""
from __future__ import annotations

import pytest

from cmapi.core.channels import channels_for

REQUEST = {"requestId": "req-20261114-0001", "action": "create", "namespace": "payments-prod", "clusterId": "OCP_P1", "env": "prod",
           "approval": {"reasons": ["prod create: 1 from approver-prod"]},
           "requester": {"requester": {"username": "ola", "email": "ola@ephico2real.com"}}}


@pytest.mark.parametrize("instance", ["prod", "staging", "emea-lab"])
def test_the_running_instance_names_both_links(world, monkeypatch, instance):
    client, ctx, git, kube, validator, keys = world
    monkeypatch.setitem(ctx.integrations, "notifier", {"smtp": {"host": "smtp.test"}})
    monkeypatch.setattr(ctx.cfg, "name", instance)
    monkeypatch.setitem(ctx.cfg.raw_instance["instance"], "portalUrl", "https://portal.example.com/")
    email = next(c for c in channels_for(ctx) if c.name == "email")
    sent = []
    monkeypatch.setattr(email, "_send", lambda to, subject, body: sent.append(body))
    link_id = email.notify_pending(REQUEST, ["approver-prod"])["linkId"]
    email.notify_decision(REQUEST, "approved")
    assert f"https://portal.example.com/#{instance}/approvals?request=req-20261114-0001&link={link_id}" in sent[0]
    assert f"https://portal.example.com/#{instance}/requests?request=req-20261114-0001" in sent[1]
    assert "#nonprod" not in "".join(sent)
```

Measured: on main's `channels.py`, `3 failed in 2.36s`, each an `AssertionError` on the link text (`'https://portal.example.com/#prod/approvals?...' in 'Request req-20261114-0001 ...'`). On the head, it passes (in the 9 passed of F3's first run, and in the 123 passed of the fix run).

### F3. Low. `instance.name` is not checked, and it now goes into a URL as it is

`cmapi/src/cmapi/core/config.py:63,112`; `cmapi/src/cmapi/core/channels.py:47,80`.

An empty name gives `/#/approvals?...`. A name with `?`, `#`, `/`, `&` or a space gives a link whose path or query is wrong. The owner sets the name, so this is a configuration mistake, not an attack. Before this PR the name went only into labels, logs and JSON.

Fix: refuse it at the start (`pr-233-files/pr-233-config.diff`, against `ba9e3e2`):

```diff
@@ -18,6 +18,7 @@
 from __future__ import annotations
 
 import hashlib
+import re
 from dataclasses import dataclass
 from pathlib import Path
 
@@ -31,6 +32,11 @@
 from cmapi.plugins.expiration.rules import ExpirationRules
 
 
+# The instance's name goes into addresses and labels as it is: the portal's links (core/channels.py), the label
+# cmapi.net/instance, the metrics. An RFC 1123 label is safe in each, so nothing has to escape it.
+INSTANCE_NAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
+
+
 class ConfigError(ValueError):
     def __init__(self, problems: list[str]):
         super().__init__("invalid instance configuration:\n  " + "\n  ".join(problems))
@@ -61,6 +67,11 @@
     problems: list[str] = []
     inst, h_inst = _read(d / "instance.yaml")
     me = inst["instance"]
+    name = me.get("name")
+    if not isinstance(name, str) or not INSTANCE_NAME.fullmatch(name):
+        problems.append(f"instance.yaml: instance.name {name!r} is not a name of lowercase letters, digits and hyphens "
+                        "(at most 63, a letter or digit first and last)")
+        name = str(name)
     allowed = set(me["allowedEnvironments"])
     hashes = {"instance.yaml": h_inst}
 
@@ -94,9 +105,9 @@
     if (d / "plugins.yaml").exists():
-        plugins = build("plugins.yaml", lambda r: PluginSwitch(r, me["name"], allowed))
+        plugins = build("plugins.yaml", lambda r: PluginSwitch(r, name, allowed))
     else:
-        plugins = PluginSwitch(None, me["name"], allowed)
+        plugins = PluginSwitch(None, name, allowed)
@@ -109,4 +120,4 @@
         problems.append("expiration.yaml: prod can never expire")
     if problems:
         raise ConfigError(problems)
-    return InstanceConfig(me["name"], allowed, inst, approvals, roles, tiers, expiration, metadata, plugins, hashes)
+    return InstanceConfig(name, allowed, inst, approvals, roles, tiers, expiration, metadata, plugins, hashes)
```

Test: `pr-233-files/test_instance_name.py` (13 refused names, 6 accepted names that each make one link). Measured: on the head with the F2 test, `13 failed, 9 passed in 3.23s` (the 13 are the refused names). With the fix, with `test_email_links.py`, `test_plugins_switch.py` and `test_cors.py`: `123 passed in 17.77s`. The full service suite was not run with this fix.

This is a new start check, so it changes behaviour beyond #222. It restricts names to lowercase; the coordinator may want a wider pattern. Recommended: its own issue.

### F4. Low. docs/02: "No code reads a literal instance name" has one exception

`docs/02-technical-design-v2.md:2048`.

Evidence:

```
$ grep -n "cmapi-nonprod" cmapi/src/cmapi/tools/realm_sync.py
309:    audience = os.environ.get("CMAPI_REALM_AUDIENCE", "cmapi-nonprod")
```

The chart and the CRC manifest both set the variable (`templates/jobs.yaml:84`, `environments/crc/realm/20-realm-sync.yaml:35`), so only a bare run of the tool uses the default.

Fix: replace the sentence with:

```
No code of the service reads a literal instance name. One tool has a default: `tools/realm_sync.py` takes the audience `cmapi-nonprod` when `CMAPI_REALM_AUDIENCE` is not set, and the chart always sets it.
```

Test: `grep -c "No code reads a literal instance name" docs/02-technical-design-v2.md` gives 1 before and 0 after. The live Technical Design v2 needs the same edit.

### F5. Low. #232: the default and the check contradict each other

Issue #232, "The design to refine".

It says `[prod]` when the key is absent, and "each name must be in `allowedEnvironments`, or the start fails". The `nonprod` and `staging` samples have no `prod` in `allowedEnvironments`, so with both rules they would not start.

Fix: in #232, replace the sentence with:

```
The check that each name is in `allowedEnvironments` applies only when the key is written. When the key is absent, the list is `[prod]` and is not checked, so an instance that does not serve `prod` starts as today.
```

Test, to add to #232's "How a test proves it": `load_instance` on each of `examples/instances/{nonprod,staging,prod}` with no `productionEnvironments` key loads. It fails for `nonprod` and `staging` under the issue's wording as written, and passes with the sentence above. Not run: the feature does not exist yet.

## Not tested

- The Playwright check of F1 and the portal suite.
- The full service suite on the head (GitHub's six checks are reported green by the coordinator; not re-checked here).
- Nothing on kind or CRC.
