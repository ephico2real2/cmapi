# Reviewer 2 (Opus 5.5, high) · cmapi PR #750 · head 3f84120a

**Verdict: request changes, with the patch below.** All four findings are confirmed against the code. I rate their severity
lower than reviewer 1 did. I cut about half of reviewer 1's patch, and one of the cut parts would have broken the owner's
self-service goal. The final patch is [`r2-outputs/final.diff`](r2-outputs/final.diff), 17 files, about 74 KB. Most of that
is the five regenerated example bundles. The CRC bundle patch is [`r2-outputs/cluster-configs.diff`](r2-outputs/cluster-configs.diff).

The work tree was `r2-work/`, a fresh export of 3f84120a. `r2-head/` is a second, untouched export used for the runs on the
unfixed head. Every run used PostgreSQL `cmapi_r2_750` on 127.0.0.1:55432, which I created for this review.

## The owner's intent stands

On run 46's fixture, with the required keys supplied, the plan lists 9 findings (8 `skipped-key`, 1 `not-adopted`) and needs
**1** approval on head and with the fix. The test is `test_run_46s_namespace_with_every_required_key_needs_only_the_base_approval`,
on PostgreSQL. With the fix, a raw quota key inside the bound a site sets also stays at 1 (`[10-1]`). Reviewer 1's patch did
not keep the intent in full; see the step check under "Cut from reviewer 1's patch".

## Verdict on each finding

| # | Reviewer 1 | My verdict | Evidence (fails on 3f84120a, passes with the fix) |
|---|---|---|---|
| H1 | High | **Confirmed; Medium.** The design table says "`policy-ratcheted`, and each finding of the validator, Yes". The validator sets `Finding.rule` to the policy's name (`validate/__init__.py`, the `Finding("kyverno", res.get("policy", ""), ...)` lines). Hand-written policies under `policies_dir` choose their own names (`settings.py:22`). An audit warning from a policy named `skipped-key` was therefore not counted. Only a site's own naming can cause this; a requester cannot. | service `test_a_validator_finding_counts_whatever_its_policy_is_named`: head needs 1, the fix needs 2 |
| H2 | High | **Confirmed; Medium. The regression is the PR's.** `tiers.yaml` accepts any non-limit quota key under `overridable`, with `custom.max`. `object_findings` skipped `_bound` for a key cmapi does not interpret, which predates the PR. On base that key's `uninterpreted-key` finding counted, so the plan needed 2 approvals (reviewer 1 measured this). Head makes the code informational and needs 1. D5 says "Each value outside the custom tier's bounds ... is a finding `beyond-custom-bounds`". The fix needs 3: adoption, findings and beyondTier. The PR's design line "No rule of cmapi's bounds it, so there is nothing to break" is false whenever a site sets a bound. | service `test_a_raw_quota_key_is_checked_against_the_bound_the_site_gives_it[11-3]`: head needs 1, the fix needs 3. `[10-1]` stays at 1 on both |
| H3 | High | **Confirmed; Medium.** The case needs a skip-prefix key that only `argocd-controller` or `cmapi-deliverer` owns through `Apply`, on a namespace that is still a candidate. That is uncommon, but the effect is a pod-security label removed on the first sync. | service `test_a_key_that_only_a_delivery_applies_stays_in_git_and_adds_the_approver[argocd-controller and cmapi-deliverer]`; core `test_a_key_that_only_a_delivery_applied_is_kept_and_no_other_is` |
| M1 | Medium | **Confirmed; Low to Medium, fixed because the PR introduced it.** The PR's (a) added the key to the policies' fixed allow-list, so `cmapi.net/adopt: <any value>` passed both label policies. Before the PR every value of that key was refused. Your brief to reviewer 1 defined "exact" as the key with the value that `adoption.yaml` configures. Nothing reads a different value, so the harm is a gap in label hygiene. | core `_check_selector` tests (3 fail on head). cel-go over 60 CREATE/UPDATE cases: 10 fail on head, 0 with the fix. The Kyverno-CLI test skips here because there is no pinned CLI; CI runs it |

### H3: what this PR introduced, and what predates it

Two sources were fetched and quoted. Kubernetes, "Server-Side Apply" (fetched 2026-11-27): "If the field is not owned by any
other field managers, it is either deleted from the live object or reset to its default value". Argo CD, "Sync Options"
(fetched 2026-11-27): "Argo CD's server-side apply manager (`argocd-controller`)".

- **Predates the PR (base e091d23f):** such a key was left out of Git, kept=False, with the false reason "only server components own it".
- **Introduced by the PR:**
  1. the reason now promises "... so it stays on the cluster", which is false here;
  2. the code `skipped-key` is no longer counted, so the plan drops from 2 approvals to 1.

**My fix, and why it goes past the letter of the brief.** I route that one case into the existing `skipped-key-kept` path. The
key stays in Git, the reason is true, and the code counts. This also ends the omission that predates the PR. A fix limited to
the text and the count would need a new finding code for a key the plan knowingly drops, which is more code in order to keep a
known defect. Keeping a key in Git is always safe: its value is the live one, so the applier only co-owns it.

I cut reviewer 1's delivery-mode plumbing. It touched `Pipeline.__init__`, `context.py` and `snapshot()`, and moved the lines
cited in docs/14, docs/21 and `citations.lock.json`. In its place is a fixed set, `DELIVERY_APPLY_MANAGERS = {"argocd-controller", "cmapi-deliverer"}`.
A key owned only by the manager that does not apply in this mode is kept as well, which is conservative and costs one counted
finding in a rare case. A service test holds the set equal to `clients.kube.APPLY_FIELD_MANAGER`. The set is written out in
`adoption.py` because that module must not import the HTTP client: `venv-ref` has no `structlog`, and the import broke core.

**If you want the letter of the brief instead,** this case goes to the Backlog, and the PR still needs a counted code for it.
I recommend the patch as it is.

## Cut from reviewer 1's patch, and why

| Reviewer 1's part | Cut | Why |
|---|---|---|
| A step check added to `_bound` for every key | **Cut** | **It breaks the owner's intent.** The shipped `custom.step` is `{requests.cpu: "1", requests.memory: 1Gi, pods: "10"}` (examples/instances/*/tiers.yaml:101; CRC 20-config.yaml:332). With reviewer 1's tree, `object_findings` turns `pods: "25"` or `requests.cpu: "2500m"` into `beyond-custom-bounds` plus beyondTier, so 3 approvals. My tree gives no finding (probe: `scratchpad/step_probe.py`, run on `r1-outputs/applied` and `r2-work`). Step is a request's granularity, and D5 names "bounds". Whether adoption should check step is a design question for the owner, not a defect |
| `if key != meaning: _bound(... key ...)` | Narrowed to `meaning is None` | The aliasing case of an overridable `cpu` is not realistic |
| The redundant early `return` in `_bound` | Cut | — |
| The delivery-mode plumbing, and the line moves in docs/14, docs/21 and `citations.lock.json` | Cut | See H3. The H1 edit keeps `pipeline.py` at the same line count. `scripts/doc-citations.py --check` reports 0 problems (run in a throwaway git copy) |
| `test_adoption_approval_boundary.py`, which used a Mock registry and was not run on PostgreSQL | Cut | Replaced by tests in the existing `tests/service/test_adoption_findings_746.py`, through the real API on PostgreSQL |
| policygen docstring: dropped "Who sent a system, operator-only, reserved or opt-in key is not on the object..." | Restored | A documentation regression |
| M1 API shape | Kept, slightly simplified | `render_bundle(..., adoption_label, adoption_value)` with the default `ADOPT_VALUE`. `_env_files` and `_other_key_checks` take one `opt_in` pair. `ADOPT_LABEL, ADOPT_VALUE` share one line, so the cited `adoption.py:42` does not move |

## Hashes, pins and the bundle: all consistent

- **Example bundles:** re-rendered for nonprod, staging and prod through `cmapi.tools.policies.main render`. They are byte-identical to reviewer 1's applied render.
- **`test_bundle_hash_244.DEV_HASH`:** e6e291ee… becomes `c7869bb7f8936c28454ec8e27b7fc0a100a10c003e2d1ee1a30d79ae537f45f8`. Reviewer 1 changed the bundle but did not repin this, so its patch would fail this service test.
- **`test_crc_bundle_pin_531.CRC_DEV_HASH`:** cfd8fa16… becomes `e7716f300a89918a1f12d02bf7126cd43831b2c69a10f3646217c1b75020de18`. I computed it and it matches reviewer 1. docs/13 names `e7716f30...` and records `cfd8fa16...` as #31's first render.
- **`cluster-configs.diff`:** made from my render of CRC's `20-config.yaml` at head, whose dev hash is cfd8fa16, the #31 pin. It changes `policies/env/dev` and `policies/env/rnd`. Its hunks are identical to reviewer 1's. Applied with `patch -p1 -F0` to the head render, it reproduces my fix's render byte for byte, with dev hash e7716f30.
- **cluster-configs PR #31 needs this re-render pushed before this PR merges.** I could not check that the base is #31 at e8c244c: there is no local clone, and I made no GitHub changes. I inferred it from the head pin.

## What reviewer 1 missed (in the changed lines, or in its own patch)

1. **Its step check raises the approvals of ordinary namespaces.** See above. No fix is needed beyond cutting it. The test `[10-1]` and the probe show the behaviour.
2. **It changed the example bundle without repinning `DEV_HASH`,** so `test_bundle_hash_244` would fail. Fixed in the final patch.
3. **It removed the "Who sent a system ... key" paragraph** from the policygen docstring. Restored.
4. **The empty-managers guard.** It is not a defect in reviewer 1's code: `managers == (x,)` was safe. My first draft had a `KeyError` on a key that `managedFields` lists no owner for, and no existing test caught it (mutant: 51 passed). The core test now asserts `decide() == (False, "no field manager owns it")`.

Reviewer 1's own report notes that it could not reach PostgreSQL. Every number above is from PostgreSQL.

## Backlog: predates #750, Low

**B-1. The ignore of the opt-in label also skips an annotation of that name.** Reviewer 1 found it, and I confirmed it on core:
`adoption_findings({}, {"cmapi.net/adopt": "x"}, ..., ignore={...})` returns `[]`, and without `ignore` it returns `unknown-key`.

Fix, in `cmapi/src/cmapi/core/metadata.py`, `adoption_findings`:
```python
                if (kind == "label" and key in ignore) or key in self.system:
                    continue
```
Also change the docstring's description of `ignore` to say "label keys".

Test, in `cmapi/tests/core/test_adoption_findings_746.py`:
```python
def test_the_opt_in_label_is_ignored_as_a_label_only():
    sources = {"namespace": "x-dev", "environment": "dev"}
    found = REFERENCE.adoption_findings({}, {"cmapi.net/adopt": "x"}, sources, ignore=frozenset({"cmapi.net/adopt"}))
    assert [(f["kind"], f["code"]) for f in found if f["key"] == "cmapi.net/adopt"] == [("annotation", "unknown-key")]
```

**B-2. A custom selector key under an allowed team prefix can be sent by a requester.** Reported by reviewer 1; I did not test
it. Reserving the selector key in the request API is a compatibility decision, not a fix, so it goes to the coordinator.

**Design note, not a defect.** D5 does not say whether `custom.step` applies to an adopted value. I recommend recording that it
does not, because step is a request's granularity; that reading keeps adoption easy. This is the owner's call.

## Runs (all on PostgreSQL `cmapi_r2_750`)

| Run | Tree | Result |
|---|---|---|
| Service: adoption 26, 733 and 746, bundle_hash_244, plain_manifests | head 3f84120a | 122 passed |
| The same, plus 739, policies_302 and policy_bundle_api | r2-work, the fix | **177 passed** |
| The service run above without 739, policies_302 and policy_bundle_api, on a fresh export with `patch -p1 -F0` | r2-verify | 128 passed |
| `tests/core`, with `venv-ref` | r2-work | **978 passed, 117 skipped** |
| The touched core tests (746, 531, policygen, coverage_333, 26, 733), plus service 746 and 244, after the last test edit | r2-verify, fresh export of the final patch | 67 passed, 43 skipped; 32 passed |
| New and changed tests on head | r2-head | Service: 5 fail (H1, H3 ×2, the managers set, H2). Core: 4 fail (M1 ×3, H3) |
| Mutants | r2-mut | All 5 killed: H1 counting by rule, H2 without the raw bound, H3 without the guard, without `Apply`, and without the branch. M1 key-only: 10 cel-go failures, and the 3 core tests fail on head |
| cel-go, 60 generated-policy scenarios (reviewer 1's harness) | head / fix | 10 failed / 0 failed |
| `bash deploy/tests/crc-scripts-test.sh` | r2-work | 291 ok, 0 failed |
| `bash deploy/render-test.sh` | r2-work | 0 failed, rc 0 |
| `scripts/doc-citations.py --check` | r2-work, in a throwaway git copy | 0 problems |

**Not run:**
- **The portal:** it was not changed, so `CHECK=749` was not needed.
- **The pinned Kyverno CLI:** it is not installed here, so its 2 tests skip; CI runs them under `CMAPI_REQUIRE_KYVERNO=1`.
- **The full service suite:** not run, as the brief says.

No command was refused. Nothing was changed in the repository, on GitHub or on a cluster.
