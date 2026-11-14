# Review: values beyond the tier and the approval gate (cmapi issues #211 and #214)

You are reviewer 1. You work in this folder only: it is an export of commit `869fc29`, not a repository. `change.diff` is the diff of `cmapi/src` against the base `418e934`. Write each finding to `REPORT.md` in this folder (absolute path: this folder) as you go. Do not start a container, a kind cluster or a network service. Do not run `tests/service` (it needs a shared PostgreSQL that another session uses). You can run the core tests: `cd cmapi/tests/core && PYTHONPATH=../../src python3 -m pytest . -q` (needs pyyaml, pydantic, pytest; if they are not installed, read and reason, and say so).

## What the change is for
The owner's rule: approval is the gate of a capability. cmapi refuses only a value that is not valid, and each value that differs from the namespace's tier needs an extra approval; auto-approval never covers it unless a policy says so. `docs/reviews/2026-11-14-issue-211/README.md` is the decision record. Read it first.

## The files to read, in full
- `cmapi/src/cmapi/core/tiers.py` (`quota_for`, `limits_for`, `beyond`, `rendered_overrides`, `render`, `_build`, `_out_of_bounds`)
- `cmapi/src/cmapi/core/pipeline.py`, `plan_namespace` and `submit` (lines 180 to 350)
- `cmapi/src/cmapi/core/approvals.py` (`decide`, `_auto`, `added_for`), `cmapi/src/cmapi/core/expression.py`
- `cmapi/src/cmapi/core/render/manifests.py`, `cmapi/src/cmapi/jobs/open_pr.py`
- `examples/config/tiers.yaml`, `examples/config/approval-rules.yaml`
- `cmapi/tests/core/test_tiers.py`, `test_approvals.py`, `cmapi/tests/service/test_custom_tier_change.py`

## The claims. Confirm or refute each one, with the file and the line.
- C1. No request can get a ResourceQuota or LimitRange value that differs from its tier's value without the fact `beyondTier` being true in the facts that `decide` receives, except a value that the namespace's folder in Git already holds. Look for a path that skips it: a value equal as a string but not as a quantity (or the reverse), a key in a different spelling, a named tier, a change from a named tier to custom or back, `quota` with a non-sizable key on PATCH, `expiration:extend`, a limit kind or part that `flatten_limits` and `limit_key_parts` treat differently, values such as `"+4"`, `"4.0"`, `"4e0"`, `"0"`, `""`, a number in place of a string.
- C2. `pipeline.py`: `approved` holds only values that Git holds for this namespace. A caller cannot put a value there. Check `rendered_overrides` against a hand-made annotation `cmapi.net/beyond-tier` in the request's own `annotations` or `labels` (can a caller set that key on any object? see `core/metadata.py` and `metadata-keys.yaml`), and against a namespace whose old tier was a named tier.
- C3. `approvals.py:_auto`: with `beyondTier` true, no policy returns `auto:<policy>` unless its `match.beyondTier` is exactly `true`; `none-required` (0 approvers) is still possible for an environment whose rule is 0 and that has no beyond-tier threshold. Say if that last case breaks the owner's rule ("extra approval for anything beyond the tier"), and give the fix with its test if so.
- C4. `pipeline.py:submit` decides again with `team_auto_today`. The second decision uses the same facts, so `beyondTier` cannot be lost between plan and submit. `open_pr.py` renders again from the stored spec: the stored `approved`, `quota` and `limit_range` give the same files as the plan, and a catalog change between plan and commit cannot widen what was approved without the plan-hash check failing.
- C5. `tiers.py:_out_of_bounds` and the `approved` exemption: a value is exempt only when it equals, as a quantity, the value in Git for the same key. A caller cannot use the exemption to get a new out-of-bounds value.
- C6. `tiers.py:limits_for`: after the merge, for each kind and resource the values are in the order min, defaultRequest, default, max, and a container max is not above `requests.<resource>` of the same request. Find an input that gives a LimitRange that the Kubernetes API server refuses (ValidateLimitRange) or that makes each pod unschedulable, and that cmapi accepts.
- C7. `networkExposure` is true each time a request raises `services.loadbalancers` or `services.nodeports` above the value in Git (or above the tier's value for a new namespace). Look at a PATCH that raises it from an approved 1 to 2, a change from a named tier to custom, and a catalog whose tier value is not "0".
- C8. `tiers.py:_build`: a catalog that passes cannot make `quota_for`, `limits_for`, `beyond` or `render` raise an exception that is not a `TierError` (which would be a 500 or a wrong 422) for a well-formed request. Look at `qty` on bounds, a `step` of "0", an overridable limit key whose kind the tier does not have, and `limit_key_parts` returning None in `limits_for`.
- C9. Behaviour that the change must not alter: a request on a named tier, and a custom request with the three sizable keys only, render the same files as on the base (same bytes, so the same plan hash), and get the same approval requirement. `cmapi/tests/core/test_tiers.py::test_render_matches_the_example_namespace_folder` covers one case; look for a difference in others (key order in `spec.hard`, an annotation, a facts key that a threshold reads).

## For each finding
Give: the claim it breaks, the file and line, why it is wrong, the full code of the fix (a unified diff against this export), and a test in the form of `cmapi/tests/core/test_tiers.py`, `test_approvals.py` or `tests/service/test_custom_tier_change.py` that fails before the fix and passes after it. Run the core tests that you add. A finding with no failing test is listed as "not proven". New files go in full in the report. Also list what you checked and found correct, one line each.

## Not in this review
The portal, the Kyverno policies (#212, #213), the wording of the documents, and whether the network keys should open at all (the record has that decision).
