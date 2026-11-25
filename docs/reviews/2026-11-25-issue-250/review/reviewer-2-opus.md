# PR #682 (closes #250, #680): reviewer 2 (Opus 5.5 high)

- **Reviewed:** `head/` (033f667), reviewer 1's report and `r1-outputs/fix.diff` (F1 to F6), the PR's record
  `docs/reviews/2026-11-25-issue-250/README.md`, and D3, D8, D9 and D19 of the adoption design, each read in full.
- **Where things ran:** the service suite's fakes on PostgreSQL `127.0.0.1:55432/cmapi_r2_682`, PyYAML 6.0.2 with
  libyaml, Python 3.12.14 (`wt-655-outputs/venv-merged`). No cluster, no repository, no GitHub was touched.
- **Copies:** `r2-work/` is `head/` plus `r1-outputs/fix.diff` (`patch -p1 -F0`, clean) plus my changes. `r2-headrun/` is
  `head/` with only the final test file, for the runs on head.
- **Outputs:** `r2-outputs/`. `fix.diff` is the complete patch against `head/` (reviewer 1's F1 to F6, amended, plus
  mine). It applies to a fresh copy of `head/` with `patch -p1 -F0`, and the result is byte-identical to `r2-work/` (cmp).

## A correction to how runs on "head" are made

`tests/service/conftest.py:30` runs `sys.path.insert(0, str(ROOT / "src"))`, so the copy's own `src` always wins over
`PYTHONPATH`. My first "head" run, with `PYTHONPATH=<head>/src`, therefore ran the fixed source, and I retract it. Every
head result below comes from `r2-headrun/`, a copy of `head/` itself. Reviewer 1's head results came from a head copy too
(11 failures, consistent with mine).

## B1: ruling, measured, fixed

### Measured

`r2-outputs/test_r2_probes_682.py`, run on `head/` (`probes-b1-head.txt`) and on reviewer 1's fixed copy
(`probes-b1-r1fixed.txt`). The two outputs are identical apart from timestamps, so reviewer 1's fix does not touch B1.

| Case (folder's only quota is not `<ns>-quota`) | Request | On head and on reviewer 1's copy |
|---|---|---|
| `compute` (`requests.cpu: 3`, `requests.memory: 6Gi`), tier small | label change | 200. Plan: `resourcequota.yaml` removed, `resourcequota-payments-dev-quota.yaml` added with `requests.cpu: 8`, `requests.memory: 16Gi`, `pods: 50` and more; capacity `cpu: 0.0, memory: 0.0`; approval `dev-change`, `none-required`. After the sync, the only live quota is `payments-dev-quota`: `compute` was pruned |
| the same | annotation change | the same: `compute` replaced and pruned |
| `best-effort` (`scopes: [BestEffort]`, `pods: 5`), tier small | label change | the scoped quota becomes the unscoped tier quota (8 CPU, 50 pods) and is pruned from the cluster |
| `compute`, tier custom | label change | 422 `policy-violation` "A custom tier needs every sizable key": the namespace cannot take a label change at all |
| `compute`, tier small | `{"tier": "medium"}` | 200, `<ns>-quota` with `requests.cpu: 16` (D9's "as today" path; see Backlog R2-B2) |

Kubernetes, "Resource Quotas" (the page reviewer 1 fetched, `r1-outputs/sources/resource-quotas.md`, line 423): "A quota
will only measure usage for a resource if it matches the intersection of enumerated scopes." So the replacement of the
`BestEffort` quota also changes which pods are counted.

### Severity: High

- **It deletes an object cmapi does not own,** from Git and, in the apply delivery, from the cluster (measured above).
  With Argo CD the object leaves Git too. Argo CD's own prune was not measured.
- **It changes capacity where no approval rule can see it.** The plan's capacity facts compare the tier's quota with
  itself (`pipeline.py`: `old_hard = ... self.cfg.tiers.quota_for(env, old_tier)` when the tier is not custom), so a raise
  from 3 to 8 CPU is sized as 0. The capacity check and every capacity rule are skipped, and the change is approved as a
  label change. The owner's rule is that approval is the gate. Here, a requester with only `namespaces:write` can undo a
  tighter quota that a platform admin set in Git, with the cheapest request there is.
- **It contradicts the design and the PR's own claim.** D9: "Any other request, a change of a label for example, leaves
  every object unchanged." The PATCH description says "every other one in the folder is kept as Git holds it".
- **The precondition is a documented state, not an exotic one.** cmapi itself always names its quota `<ns>-quota`: every
  `tiers.render` since the first one (84ea126) does. But the folder is read "by hand" too (`render/manifests.py` docstring;
  D8). D9 also names "exactly one object of the kind" as the normal adopted case, and adoption is the next build.
- I rate it High rather than Medium because it bypasses the approval gate and deletes on the cluster. The trigger is a
  label change, not a crafted request. The only mitigation is that the plan's file list shows the swap to a reviewer who
  reads files.

### Fix: D9's rule, kept narrow

The line of D9 that I follow is: "Any other request, a change of a label for example, leaves every object unchanged."

I also keep D9's "When the namespace has exactly one object of the kind, the name may be left out, as today". So a change
of the quota, the tier or the limits still acts on the lone quota, as #253 does. Its in-place form is D9's build item B3.

- **`render/manifests.py`:**
  - `quotas_kept(quotas, namespace, *, changes_quota=True)` is true when the folder holds ResourceQuotas, none is named
    `<ns>-quota`, and either there are several or the request changes no quota, tier or limits.
  - The renderer reads it from a new `NamespaceSpec.changes_quota: bool = True`. The default keeps a stored plan rendering
    as its hash was taken (`jobs/delivery.py` `rendered` re-renders the stored spec and checks the hash). A test proves
    this.
  - The precedent for a defaulted spec field is #211/#214 (869fc29).
- **`pipeline.py`:**
  - `changes_quota = action == "create" or bool(quota) or moved or bool(limits)`, computed from the body before the custom
    values are merged in.
  - `moved` is reviewer 1's F3 expression, moved above it.
  - It is passed to `quotas_kept` and to the spec.
  - The existing `quotas_held` branch then sizes nothing (no delta, no exposure, `QuotaChange("same"/"custom")`), as the
    PR already does for several quotas.
- **Behaviour preserved:**
  - With `changes_quota=True`, `quotas_kept` equals the old `len(quotas) > 1 and own_quota(...) is None`: no quotas gives
    False, a `<ns>-quota` among them gives False, and otherwise the result is `len > 1`.
  - A create always renders the tier.
  - The refusal condition for several quotas is unchanged.
- **Docs:** `own_quota`'s and the module's docstrings, README decisions 2 and 3, the tests count and the behaviour list,
  and docs/02's #250 paragraph.

The code is in `r2-outputs/fix.diff`. The core of it:

```python
# render/manifests.py
    # The request changes the quota, the tier or the limits, or creates the namespace. False keeps a folder's ResourceQuotas
    # that hold no <ns>-quota, a lone one too (quotas_kept). True by default: a plan stored before #250 renders as it did.
    changes_quota: bool = True

def quotas_kept(quotas: list[dict[str, Any]], namespace: str, *, changes_quota: bool = True) -> bool:
    if not quotas or any(_name(d) == f"{namespace}-quota" for d in quotas):
        return False
    return len(quotas) > 1 or not changes_quota
...
        if quotas_kept(quotas, spec.namespace, changes_quota=spec.changes_quota):

# pipeline.py
            moved = action != "create" and tier != old_tier and (old_tier is not None or bool(body.get("tier")))
            changes_quota = action == "create" or bool(quota) or moved or bool(limits)
            quotas_held = quotas_kept(quotas, ns, changes_quota=changes_quota)
            if len(quotas) > 1 and (quota or moved or (quotas_held and limits)):
                raise several_quotas(ns, quotas, kept=quotas_held)
...
                                 scc_grants=_grants(prev_files, scc=True), changes_quota=changes_quota)
```

### Tests (in `test_multidoc_quota_250.py`)

- **`test_a_label_change_keeps_a_lone_quota_that_is_not_cmapis_and_renders_no_tier_quota_over_it`**, run 3 times:
  `small`/`compute`, `custom`/`compute` and `small`/`best-effort`.
  - It asserts the plan's changes: only the move of the old-layout file, and no `<ns>-quota`.
  - It also asserts capacity 0, the sync, the quota on the cluster with its spec, no `<ns>-quota` live, and the LimitRange
    files byte-identical.
  - All 3 cases fail on head and pass with the fix.
- **`test_a_tier_move_still_acts_on_a_lone_quota_that_is_not_cmapis`** is a guard and passes on both. It pins #253's
  behaviour until B3. B3's pull request changes it on purpose.
- **`test_a_plan_stored_before_b1s_fix_renders_as_it_did`** is a guard and passes on both.
- **Mutants** (`r2-outputs/mutants.py`, `mutants.txt`): every mutant is killed.

| Mutant | Tests that fail |
|---|---|
| MB1, `changes_quota = True` (head's rule) | 3 |
| MB2, `changes_quota = False` | 1 (the tier-move guard) |
| MB3, the spec default `False` | 1 (the stored-plan guard) |
| MB4, the renderer ignores the spec | 3 |
| MB5, a lone quota is never kept | 3 |

## Reviewer 1's findings, each checked

### F1 (Medium): accept, and extend with R2-F7

- **Re-checked in the source:** `r1-outputs/sources/pyyaml-constructor.py` (PyYAML 6.0.2).
  - `construct_document` (lines 54-65) finishes each mapping's generator outside `construct_object`.
  - But `construct_mapping` builds every key and value with `self.construct_object(...)` (lines 139 and 143), so the
    override catches a bad value at any depth. Reviewer 1's nested-annotation test proves it.
- **Fuzzed** (`r2-outputs/f1_fuzz.py`; `f1-fuzz-head.txt` and `f1-fuzz-fixed.txt`): 26 inputs.
  - **Escape on head:** a plain `2026-02-30`, `+25:00` offset, `0000-01-01`, `!!int abc`, `!!float abc`, `!!bool maybe`,
    `!!timestamp nope`, and a plain or `!!int` integer of 4301 digits. The last is Python 3.12's integer-string limit,
    measured: ValueError "Exceeds the limit (4300 digits)". Reviewer 1 did not list it, and it is a plain scalar, so a long
    number in an annotation is enough.
  - **With F1,** each of these is a ConstructorError.
  - **Already a YAMLError on head and on the fix:** `!!python/object:...` and `!!python/name:...` (SafeLoader:
    "could not determine a constructor for the tag"), a custom tag, `!!binary` with a byte that is not ASCII, a node of the
    wrong kind for its tag, an unhashable key, a merge of a scalar, and an undefined alias (ComposerError).
  - **Not an error at all:** `!!binary '%%%'` gives `b''`. A duplicate key `a: 1\na: 2` gives `{'a': 2}`:
    `construct_mapping` (lines 137-145) assigns `mapping[key] = value` with no duplicate check. So no 500 and no 409 comes
    from either.
  - **Still a 500 with F1:** a file nested about 500 deep raises RecursionError (`b4-depth-head.txt`: flow list, flow map
    and block map, Python's limit 1000). See R2-F7.
- **Is the detail free of file values?**
  - F1's own problem string holds only the tag's short name. That name comes from a fixed set, because an unknown tag
    fails earlier in `construct_undefined`.
  - PyYAML's own strings can still echo a tag, an alias, or one character of a `!!binary` value (measured: "can't encode
    character '\xe9' in position 3"). This is reviewer 1's observation, and I agree it is acceptable.

### F2 (Medium): accept

- **The hash is written on every rendering.** `cmapi.net/tier-hash` is in the shared `annotations` dict that `tiers.render`
  copies onto the ResourceQuota and onto each LimitRange:
  - at head (`core/tiers.py:741-742`, and the LimitRange takes `dict(annotations)`);
  - at fd36e66 and at `d5d8bb4^` (read with `git show` in the main repository, read-only);
  - at the first render, 84ea126 (2026-11-04: the `<ns>-limits` LimitRange took `dict(annotations)` with the hash).
- **Only a hand-written example lacked it.** `git log -S"cmapi.net/tier-hash"` reaches 72d082b and fd36e66 over
  `cmapi/src`, and 84ea126 over `examples`; no code ever wrote a LimitRange without it. The only object without the hash is the hand-written example that came before
  any code: `84ea126^:examples/.../resourcequota.yaml` in docs/01's sample. No code ever wrote it, and no folder is seeded
  from `examples/cluster-configs/clusters` (searched `deploy/` and `docs/`).
- **Fixtures:** every LimitRange fixture carries the hash. That covers `examples/cluster-configs/.../limitrange-*.yaml`,
  `samples.json` and `tests/core/test_limitrange_split.py`. The old-layout `<ns>-limits` fixture there is derived from a
  rendered object; `test_limitrange_split.py` gave 21 passed and 1 skipped, kyverno, on the fixed copy.
- **Nothing in the path drops the hash.** `MetadataKeys.ordered` (`metadata.py:1401-1404`) only sorts.
- **Not checked:** CRC's real cluster-configs folders (no cluster or repository access).
- **Risk for an unseen folder:** a hand-stripped hash on a name that the tier renders now is still replaced (reviewer 1's
  `rendered` set). Only a stripped `<ns>-limits-storage` or old `<ns>-limits` would be kept.

### F3 (Low): accept

- The expression is reused by my B1 fix.
- One wrinkle, which I leave alone: with no tier label, sending `tier: small` counts as a move, while sending no tier does
  not.

### F4 (Low): accept

The `rendered` exclusion is right: an object of a rendered name is the same Kubernetes object.

### F5 (Low): accept

### F6 (Low, docs): accept

I extended the README further for B1 and R2-F7, and set the tests count from my runs.

## What reviewer 1 missed

- **B1's severity.** Reviewer 1 measured the case but rated it Backlog Low. It is High: see above. Reviewer 1 also did not
  measure three things:
  - the scoped-quota case;
  - the tier-custom case, where every label change answers 422;
  - the annotation-change case.
- **R2-F7 (Low, inside the changed lines and #680's claim): a deeply nested file still answers 500.**
  - Measured on head: GET 500 `internal-error`.
  - Reviewer 1 had this as Backlog B4. It is #680's exact claim ("A folder file that does not parse is 409
    folder-not-yaml"), and the reader and `_read_folder` are the PR's new lines.
  - Python 3.12, "Built-in Exceptions" (https://docs.python.org/3.12/library/exceptions.html, read 2026-11-25):
    RecursionError "is raised when the interpreter detects that the maximum recursion depth (see
    `sys.getrecursionlimit()`) is exceeded". It is a RuntimeError, so the stack is unwound when it is caught.
  - **Fix:** `load_all` turns it into `yaml.MarkedYAMLError(problem="a document nested deeper than the reader can read")`,
    so `folder_not_yaml` names the file. With no mark, it gives no line.
  - **Test:** `test_680_a_folder_file_nested_deeper_than_the_reader_can_read_is_a_409` fails on head (500) and passes with
    the fix.
- **The 4301-digit integer** as another plain-scalar ValueError (see F1). It is covered by F1's fix and needs no change of
  its own.
- **The test-harness trap** above: `PYTHONPATH` cannot select the source under test.

## Backlog (Low; described, no fix)

- **R2-B1.** The PATCH description in `plugins/namespaces/router.py:322-326` (and so `contract/openapi.json`) still speaks
  only of several ResourceQuotas and `<ns>-limits-*` by name. It is true after the fix, but it does not mention the lone
  quota or the tier hash. Changing it means rendering the contract again, so it should go with B3.
- **R2-B2.** A move of the tier or a quota change with a lone quota that is not cmapi's is sized against the tier's
  quota, not the quota that Git holds. Measured: small to medium beside `compute` (3 CPU) sizes as 8 to 16. The quota is
  also replaced rather than patched in place. This is D9's build item B3, and #253's behaviour, kept on purpose here (and
  pinned by the guard test).
- **R2-B3.** A folder object whose `metadata` is not a mapping (`metadata: x`) raises AttributeError in `_name` and in the
  request-ID loop, which gives a 500. Base has the same request-ID loop (`base/.../manifests.py:206`), so this predates the
  PR.
- **R2-B4.** A duplicate key is read as last-wins by PyYAML (measured). Whether Argo CD or the API server refuses such a
  file was not researched. File it for #680's follow-up if a refusal is wanted.
- **Reviewer 1's B2, B3, B5 and B6 stand.** B4 is now R2-F7, fixed.

## Runs

- **Test file on head** (`r2-outputs/tests-on-head.txt`): 15 failed, 16 passed of 31. The 15 are reviewer 1's 11, my 3 B1 cases and R2-F7; the 3 guards pass on both, on purpose (16 = the PR's 13 + 3 guards).
- **Test file on the fix, with `test_api_standard.py`** (`tests-on-fixed.txt`): 208 passed (the 31 cases + `test_api_standard.py`).
- **Related service suites on the fix** (`related-service-on-fixed.txt`): 145 passed: custom tier change, 255 apply, storage switch, flow, delete dry run 602, deliverer, CRC environment, review D delivery, API samples, PATCH review 492, capacity 302.
- **Core tests on the fix** (`core-on-fixed.txt`): 181 passed, 57 skipped (no kyverno on PATH): limitrange split, render/listquery/config, tiers, review 255, YAML quoting 355, policygen, review 212, lifecycle expiration.
- **Mutants:** `mutants.txt`, all killed.
- **Not run:** the whole service suite (the coordinator runs it), any cluster, and Argo CD's prune.
