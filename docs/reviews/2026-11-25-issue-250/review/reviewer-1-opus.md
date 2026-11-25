# PR #682 (closes #250, #680): reviewer 1 (Opus 5.5 high, in Codex's place)

- **Head reviewed:** `head/` = `033f667`; base `base/` = main `c2b89f5`; `pr.diff` read in full (1388 lines), with the
  implementer's `docs/reviews/2026-11-25-issue-250/README.md`.
- **Where things ran:** the service suite's fakes on PostgreSQL `127.0.0.1:55432/cmapi_r1_682` (mine), PyYAML 6.0.2 from
  `wt-655-outputs/venv-merged`. No cluster, no repository, no GitHub was touched.
- **Outputs:** `r1-outputs/` (every run is a file there; `fix.diff` is the proposed fix; `sources/` holds the fetched pages).

## Verdict

The PR's core is right and its tests can fail: the PR's 13 tests fail 13/13 on base and pass 13/13 on head, and five
mutants are each killed. I found two Medium defects and four Low ones in the changed lines, each with a fix and a test in
`r1-outputs/fix.diff`, and six Low items for Backlog. With the fix, the test file has 25 cases: 11 of the 12 new ones fail on
the PR head, and the twelfth is a guard that passes on both, on purpose. On the fixed copy, all 25 pass, and so do
`test_api_standard.py`, 7 related service files, and 12 core files.

| # | Severity | Finding | Measured on head |
|---|---|---|---|
| F1 | Medium | #680 is incomplete: a value that a standard tag cannot construct (a plain `2026-02-30`) still answers 500 | GET 500 `internal-error` (probe P1) |
| F2 | Medium | A team's LimitRange named `<ns>-limits-gpu` is claimed by its name: a label change removes it from Git and prunes it from the cluster | changes `limitrange-payments-dev-limits-gpu.yaml: removed`; object gone after sync (P2) |
| F3 | Low | `tier` sent to a namespace whose Namespace has no tier label, with 2 quotas, passes: the label becomes `medium` and nothing is rendered | 200, tier label `medium` (P3) |
| F4 | Low | A second copy of `<ns>-quota` (old-layout file beside the named one) is "kept" and written over the rendered quota | label change plans `requests.cpu: 64` (P4) |
| F5 | Low | A kept object whose name has `/` makes a plan path outside the folder | path `.../payments-dev/resourcequota-../../other/x.yaml` (P6) |
| F6 | Low (docs) | README: the quota quote does not support "each binds"; the behaviour change "other kinds in `namespace.yaml` are dropped" is not listed | P5, P5b |

## Primary sources (fetched 2026-11-25 16:21Z, saved under `r1-outputs/sources/`)

- **Kubernetes, Resource Quotas**
  (`https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/policy/resource-quotas.md`)
  - Line 39 says: "A cluster administrator creates at least one ResourceQuota for each namespace." The implementer's quote
    is exact.
  - The page does not say in words that every quota binds. It shows a namespace with three quotas (`pods-high`,
    `pods-medium`, `pods-low`, lines 607-625).
  - The binding rule is in the quota admission design
    (`kubernetes/design-proposals-archive/.../admission_control_resource_quota.md`, line 164): "It makes decisions by
    evaluating the incoming object against all defined **ResourceQuota.Status.Hard** resource limits in the request
    namespace."
  - The source agrees (`staging/src/k8s.io/apiserver/pkg/admission/plugin/resourcequota/controller.go`, `CheckRequest`,
    lines 604-625). It loops over every quota the request touches and returns `exceeded quota: <name>` at the first one
    it exceeds.
  - **Answer:** yes, all of them are enforced. The README's "each binds" was supported only by cmapi's own code, and
    F6 adds the quote.
- **Kubernetes, Limit Ranges** (`.../concepts/policy/limit-range.md`)
  - Line 52: "does not exceed resource minimum, maximum and ratio defined in any LimitRange present in the namespace".
  - Line 62: "If two or more LimitRange objects exist in the namespace, it is not deterministic which default value will
    be applied." The implementer's quote is exact.
- **PyYAML 6.0.2** (`lib/yaml/__init__.py` at tag 6.0.2)
  - `safe_load`: "Parse the first YAML document in a stream" (line 119).
  - `safe_load_all`: "Parse all YAML documents in a stream and produce corresponding Python objects" (line 129).
  - `composer.py`, line 38: "Ensure that the stream contains no more documents", then `ComposerError("expected a single
    document in the stream"` (line 41).
  - These quotes are exact.
  - **Not in the README, and the source of F1:** `constructor.py` `construct_yaml_timestamp` calls
    `datetime.date(year, month, day)` (line 330). It raises Python's ValueError, which is not a YAMLError.
  - `error.py` `Mark.__str__` prints `line+1, column+1` (line 40). The PR does the same.
- **RFC 9110 §15.5.10**, from `rfc9110.txt`: "The 409 (Conflict) status code indicates that the request could not be
  completed due to a conflict with the current state of the target resource. This code is used in situations where the
  user might be able to resolve the conflict and resubmit the request. The server SHOULD generate content that includes
  enough information for a user to recognize the source of the conflict." The quote is exact, and 409 fits both new codes.

## The seven points

### 1. Folder parses that do not use `load_all`

- **What I searched:**
  - `grep -rn "safe_load\|yaml\.load\|load_all\|YAMLError" head/cmapi/src`;
  - every caller of `objects_of`, `read_folder`, `namespace_doc`, `_read_folder` and `removable_folder`;
  - `read_folder` itself, which reads only the `.yaml` files directly in the folder (`core/git/workspace.py:336`).
- **What remains, none of it a folder file:**
  - the policy bundle: `policybundle.py:68,122` and `validate/__init__.py:327,337`;
  - configuration files: `config.py`, `registry.py`, `metadata.py`, `tiers.py`, `approvals.py`, `context.py`,
    `expiration/rules.py`, `tools/git_bootstrap.py`;
  - `manifests._without_request_id`, a deep copy `safe_load(safe_dump(doc))` of an object already loaded.
- **Readers that do not parse:** `push_branch`, `open_pr` and `watch_sync` read the folder only to compare text.
  `pr_checks` parses main's folder through `validate(previous=base)`, which uses `load_all` (Backlog B2).
- **Answer:** no folder parse is left outside `load_all`.

### 2. Can a change still drop or rewrite a ResourceQuota or LimitRange that cmapi does not own?

The cases ran on head with the fakes and the apply delivery.

- **Kept, as the PR intends:**
  - a label change with `EXTRA` beside `<ns>-quota`: the PR's test, plus P9;
  - an annotation change: P9, where `payments-dev-objects` is still on the cluster with its spec after the sync;
  - two quotas with none of them cmapi's: the PR's test;
  - a LimitRange named `gpu-defaults`: the PR's test.
- **Not kept: F2.** A team's `<ns>-limits-gpu` is removed from Git and pruned from the cluster (P2).
- **Rewritten: F4.** A stale copy of `<ns>-quota` replaces the rendered one (P4).
- **A tier move or a `limitRange` change:** refused with 409 as designed (the PR's tests and mutant M4). F3 is the gap,
  for a namespace with no tier label.
- **A delete** removes the whole folder by design (#616).
- **Adopt:** there is no adoption plugin at this head (`plugins/` holds capacity, directory, expiration, namespaces,
  policies, quotas and tiers), so it was not tested.
- **The prune set** (`watch_sync` and `jobs/apply`): the identities in removed files minus those still in the planned
  files. A kept object is written into the planned files, so it is never pruned. Measured: the PR's test and P9.
- **A lone ResourceQuota that is not cmapi's (#253, not changed by this PR):** see Backlog B1.

### 3. Ownership by name

- `<ns>-quota` is the name that `tiers.render` writes. A user object with that name is the same Kubernetes object, so the
  takeover is inherent and correct.
- `<ns>-limits-*` is open-ended, because `limit_object_suffix` gives each container resource its own name. A natural team
  name such as `payments-dev-limits-gpu` is claimed, and on head a label change removes it (P2). That is F2.
- D8 says nothing on ownership.
- D9 says "Any other request, a change of a label for example, leaves every object unchanged."
- README decision 2's reason, "an object with one of those names is the same Kubernetes object anyway", holds only for the
  names the tier renders now.
- **The fix** keeps the prefix, which is still needed to remove cmapi's own stale objects (`<ns>-limits-storage` when the
  switch is off, docs/02 line 1252). It also requires `cmapi.net/tier-hash`, which every tier rendering writes. I checked
  in history that this holds before #253 too: `git show d5d8bb4^:cmapi/src/cmapi/core/tiers.py`, lines 615-628.
- The adoption design's D3 says adopted objects carry no tier hash.
- Any object named like one the tier renders now is still replaced.
- The storage-removal guard test passes on both head and the fix.

### 4. The two behaviour changes

- **A `namespace.yaml` with no `kind: Namespace` reads as no namespace (404).**
  - This is right by D8: "Each reader of these files finds them by kind".
  - A client is hurt only by a `namespace.yaml` without `kind`, which Argo CD cannot apply either.
  - Read in the code, not run: such a folder is no longer 409 `namespace-exists` on create (pipeline lines 279-282), so a
    create renders over it.
- **A LimitRange that cmapi does not own is kept.** This is right by D9. The name-only gap in it is F2.
- **A `namespace.yaml` holding the Namespace plus another kind** (the brief's example):
  - a change used to answer 500, and now writes `namespace.yaml` with the Namespace alone, so the NetworkPolicy leaves Git
    (P5);
  - the same change removes a separate `networkpolicy.yaml` (P5b), so this matches the folder model already in place;
  - a ResourceQuota or LimitRange inside `namespace.yaml` is kept in its own file;
  - the README does not list it, which is F6.

### 5. 409 `folder-not-yaml`

- **The line** comes from `problem_mark.line + 1` and `.column + 1`, which is PyYAML's own convention. The PR's test
  checks "line 4, column 1".
- **The detail** never uses `str(exc)`, so `Mark.get_snippet()` (the file's text) is not echoed.
- **What it can echo:** PyYAML's `problem` string, which can carry one tag, one alias name or one character from the file.
  Measured: `could not determine a constructor for the tag '!s3cr3t-token'` and `found undefined alias 'hunter2'`.
- **Why this is acceptable:** the folder holds only Namespace, ResourceQuota, LimitRange, ServiceAccount and RoleBinding
  manifests, no Secret kind, and the caller already holds `objects:read` on the namespace. It is an observation, not a
  finding.
- **F1's new message** names only the tag's short name and the place, never the value. The test asserts that
  `2026-02-30` is not in `detail`.

### 6. The contract

- `oasdiff breaking base head` reports "No breaking changes" (exit 0), and `oasdiff changelog` reports none
  (`r1-outputs/oasdiff-*.txt`).
- `core/docs.py` PROBLEMS and PROBLEM_EXTRAS hold both codes, and `problem_docs.ACTIONS` holds both actions.
- docs/02 has both table rows.
- `folder-not-yaml` is listed on GET, create, PATCH, DELETE and the expiry actions (all of `WRITE_PROBLEMS`).
- `several-resource-quotas` is listed on PATCH only, and only PATCH can raise it. That stays true with F3's fix, which
  leaves create out on purpose (Backlog B3).
- `test_api_standard.py` passes on the fixed copy: 202 passed together with the 25 cases.

### 7. The tests can fail

- **Base and head:** on base the test file gives 13 failed (`r1-outputs/base-test.txt`); on head, 13 passed
  (`head-test.txt`).
- **Mutants** (each applied to a fresh copy of head, `r1-outputs/mutants.txt`):

| Mutant | Edit | Tests that fail |
|---|---|---|
| M1 | `load_all` keeps only the first document | 7 |
| M2 | every LimitRange counts as cmapi's | 1 |
| M3 | no ResourceQuota is kept | 2 |
| M4 | the 409 `several-resource-quotas` is skipped | 3 |
| M5 | the 409 `folder-not-yaml` is skipped | 3 |

- **M5 was run twice.** The first edit string `if errors:` occurs twice in `pipeline.py`, so it was not applied, and that
  run's "13 passed" is void. The rerun with a unique string is recorded below it in `mutants.txt`.
- **M2 is the weakest:** only one test kills it.

## Findings with fixes (all in `r1-outputs/fix.diff`, 290 lines, from the repository root)

`patch -p1 -F0` applies the diff cleanly to a fresh copy of `head/`, and the result is identical to the fixed copy (checked
with `cmp` and `diff -rq`).

### F1 (Medium): #680 still answers 500 for a value that a standard tag cannot construct

- **Where:** `cmapi/src/cmapi/core/kube_yaml.py` `load_all`. `pipeline._read_folder` catches only `yaml.YAMLError`.
- **Why:** `SafeConstructor` raises Python's own errors. Measured with PyYAML 6.0.2:
  - a plain `2026-02-30` or `2026-13-45` raises ValueError;
  - `!!int abc` raises ValueError;
  - `!!bool maybe` raises KeyError;
  - `!!timestamp nope` raises AttributeError.
- **Measured on head:** a namespace annotation `example.com/review-by: 2026-02-30` answers GET, PATCH and DELETE with 500.
  A hand-edited date is the realistic case.
- **The fix:** `_KubeSafeLoader(yaml.SafeLoader)` overrides `construct_object`. It turns ValueError, TypeError, KeyError
  and AttributeError into `ConstructorError(problem="a value that is not a valid <tag>", problem_mark=node.start_mark)`.
  The answer becomes 409 `folder-not-yaml` "… a value that is not a valid timestamp at line 6, column 28".
  - The output for valid streams is unchanged (checked by the core suite).
  - The loader is still safe: SafeLoader's constructors only.
- **Tests:**
  - `test_680_a_value_that_yaml_cannot_construct_is_a_409_that_names_it[get|patch|delete]`;
  - `test_the_reader_refuses_a_value_its_tag_cannot_construct_as_yaml` (4 cases).
  - All 7 fail on head and pass with the fix.
- **Docs:** the README's decision 5 and the docs/02 paragraph are updated.

### F2 (Medium): a LimitRange is claimed by its name prefix alone

- **Where:** `render/manifests.py` `_own_limit_range`.
- **The fix:** a LimitRange counts as cmapi's only with the prefix and `cmapi.net/tier-hash`. Separately, any
  `(kind, name)` that the tier renders now is never kept, so cmapi's rendered object replaces it.
- **Tests:**
  - `test_a_limitrange_named_like_cmapis_but_not_rendered_by_cmapi_is_kept_in_git_and_on_the_cluster` fails on head
    (the file is removed and the object pruned) and passes with the fix;
  - the guard `test_a_limitrange_that_cmapi_rendered_and_no_longer_renders_is_removed` passes on both.
- **Docs:** README decision 2 and the docs/02 paragraph now name the tier-hash rule.

### F3 (Low): a tier sent to a namespace with no tier label is not refused

- **Where:** `pipeline.py`, the condition `old_tier is not None and tier != old_tier`.
- **The fix:**

```python
moved = action != "create" and tier != old_tier and (old_tier is not None or bool(body.get("tier")))
```

- Behaviour is unchanged when Git holds a tier, and on create, whose documented answers have no such 409.
- A change that sends no tier still passes.
- **Test:** `test_a_tier_sent_to_a_namespace_with_no_tier_label_and_two_quotas_is_refused` fails on head and passes with
  the fix.

### F4 (Low): a stale copy of `<ns>-quota` is written over the rendered quota

- **Where:** `render/manifests.py`, `kept = [d for d in quotas if d is not own]`.
- **How it happens:** `own` is one copy, so the other copy, with the same name, is "kept" and overwrites
  `resourcequota-<ns>-quota.yaml`.
- **Measured on head:** a label change plans `requests.cpu: 64` from the stale copy, while the plan's capacity and
  approval facts were computed from the other copy.
- **The fix:** the same rendered-name exclusion as F2.
- **Test:** `test_a_second_copy_of_cmapis_quota_is_not_written_over_the_rendered_one` fails on head and passes with the
  fix.
- **What the test asserts:** the spec and the removal of the old file. The named file may take the new request ID,
  because the renderer's request-ID keeping sees two copies.

### F5 (Low): a kept object's name with `/` makes a path outside the folder

- **Where:** `object_file`. Before this PR it was reached only with cmapi's own names; it now gets names from Git.
- **What happens on head:** the plan lists `.../payments-dev/resourcequota-../../other/x.yaml`.
  - Read in the code, not run: the workspace's `staged <= set(req.files)` guard would fail the push after approval
    (`workspace.py:482-483`).
  - The API server refuses such a name, so only a hand-written file can hold one.
- **The fix:** `object_file` uses the hash form for an empty name, `.`, `..`, or any name with `/`.
- **Test:** `test_a_kept_object_whose_name_is_no_file_name_stays_in_the_folder` fails on head and passes with the fix.

### F6 (Low, docs): README accuracy

- **The README edit (in `fix.diff`):**
  - adds the quota admission quote and the source line under the Resource Quotas source;
  - adds the dropped-other-kinds behaviour change, with P5 and P5b;
  - adds the ConstructorError note (F1) and the tier-hash rule (F2);
  - makes explicit that a moved object keeps its data but loses the old file's comments. D8 says "each object's text
    unchanged"; the implementer's reason is that Argo CD compares objects, so this is recorded, not reopened.
- **For the coordinator's records:** the README's "13 cases" count is now 25.

## Backlog (Low; described, no fix)

- **B1. A lone ResourceQuota that is not cmapi's is still replaced on a label change.**
  - The cause is `own_quota`'s "the only one there is" (#253). The PR keeps it on purpose (README decision 2).
  - Measured (P8): a folder whose only quota is a team's `compute` (`requests.cpu: 3`). A label change plans
    `<ns>-quota` from tier small (`requests.cpu: 8`), removes `compute` from Git, and prunes it from the cluster.
  - Capacity and approval see no change, because `old_hard` is the tier's own values.
  - This contradicts D9's "a change of a label for example, leaves every object unchanged", and the PATCH description's
    "every other one in the folder is kept".
  - The precondition can come only from a hand edit, because cmapi always writes `<ns>-quota` (pre-#253 too).
  - The right change is the B3 in-place patch of the adoption design. File it as its own issue under B3.
- **B2.** `pr_checks` (`jobs/pr_checks.py:93-101`) handles NotUtf8 in main's folder as `base_changed`. A file that does
  not parse there reaches `validate(previous=base)` and raises inside the job instead. This predates the PR and was read in
  the code, not run.
- **B3. A create into a folder with no `namespace.yaml` and two ResourceQuotas that are not cmapi's.**
  - Measured (P7): `quotas_kept` makes the create render no quota, with capacity delta 0 for tier `large`. The dev-create
    approval rule still applied.
  - Refusing it needs `several-resource-quotas` on the create contract, which is the coordinator's call.
- **B4.** A deeply nested file still raises RecursionError. Measured with PyYAML on a 10,000-level list; not run through
  the API.
- **B5.** A kept LimitRange that is not cmapi's, beside cmapi's own LimitRanges, can make the defaults nondeterministic
  (Limit Ranges, line 62). D9 asks the plan of a tier move to say so; a plain change has no finding for it.
- **B6.** The same object twice in a folder: `several-resource-quotas` lists its name twice, and two kept copies that are
  not cmapi's share one file, where the last one written wins.

## Runs (all files in `r1-outputs/`)

- **The PR's tests:**
  - `base-test.txt`: 13 failed;
  - `head-test.txt`: 13 passed.
- **Probes on head** (`test_r1_probes_682.py`):
  - P1 to P7: `probes-head.txt`;
  - P8 and P9: `probes-p8-p9-head.txt`.
- **The 25-case file on head:** `new-tests-on-head.txt`, 11 failed and 14 passed. The 11 are F1 to F5; the
  storage-removal guard passes on head by design.
- **The fixed copy:**
  - `new-tests-on-fixed.txt`: 25 cases plus `test_api_standard.py`, 202 passed;
  - `core-on-fixed.txt`: 10 core files that touch the renderer, the reader and policygen, 143 passed and 73 skipped;
  - `related-service-on-fixed.txt`: custom tier change, 255 apply, storage switch, flow, delete dry run, deliverer and CRC
    environment, 68 passed;
  - `related-core-on-fixed.txt`: tiers and review_212, 84 passed and 29 skipped.
- **Not run:** the whole service suite (the brief forbids it), any cluster, and Argo CD's diff of the moved files.
