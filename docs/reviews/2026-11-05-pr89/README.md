# Review of PR #89, and the coordinator's rulings

Reviewed at `d21599a` by Opus 5.5 (`opus/`) and Codex (`codex/`), independently, on exports. **The rulings below are applied at `d6c063e`** by a separate Opus 5.5 implementer. The measured results are in `results/`, and the test record is `docs/reviews/2026-11-05-plain-manifests-test.md`.

Verdict from both on `d21599a`: do not apply this to the shared cluster until H1 and H2 are fixed. Merging alone writes nothing to a cluster.

## Rulings

1. Opus's patches 01 to 08 are accepted, subject to the items below. Their tests go in the repo: `cmapi/tests/service/test_plain_manifests.py`, `deploy/secrets-test.sh`, `deploy/render-test.sh`; the other scripts CI can run go under `deploy/tests/` and into job `manifests`.
2. Codex's `test-empty-realm.sh` case must pass: an existing `cmapi-realm-secrets` with empty `data` stops without a write. Check whether patch 02 covers it.
3. **A config change restarts the app: neither proposal.** Opus only documented the loss. Codex's versioned immutable ConfigMaps need four hand edits in step, and forgetting one is the failure being fixed. `deploy/render.sh` writes a `checksum/config` annotation into the api and worker pod templates: SHA-256 over the environment's `cmapi-env`, `cmapi-config` and `cmapi-trust` files, in a stable order, from a placeholder that fails the render if left. Tests: filled; changing any of the three changes it in both Deployments; two renders identical; mockup untouched. The README's "one substitution" sentence and patch 07's text change to match.
4. Patch 09 is accepted. Measured on PostgreSQL 16: `PGSSLROOTCERT` with a CA that does not cover the server makes `sslmode=prefer` fall back to plaintext silently, while the URI's `sslrootcert` still verifies an external server and refuses a wrong CA, so the earlier guard's intent holds. Its effect on CNPG was inferred: measure `pg_stat_ssl` on kind with the migrate container's exact env, and stop if it is not TLS. File a new issue: connections to CNPG are encrypted but do not verify the server; the fix is `verify-full` with CNPG's CA. Not in this PR.
5. Also take Codex's `runs-on: ubuntu-24.04` for job `manifests`.
6. Fix #90 here, with a test on the `ERROR:` text, and add `Closes #90` to the PR body.
7. Opus's stated limit (import and both Secrets deleted while the realm stays, so the script mints values) moves to Wave 1, which has the issuer URL: an unauthenticated `GET <issuer>` shows whether the realm exists.
8. Patch 08 (tracker): its reference-modules correction is applied by hand; its other lines are overtaken by the coordinator's updates to the tracker, so **do not apply patch 08**. Patch 09 goes on top of patches 01 to 07; on the current head, 01 to 07 pass `git apply --check` individually.

## Still to do on this PR

Done at `d6c063e`: the rulings applied and `opus/patches/` removed; `deploy/kind-test.sh` exit 0 on real kind at `16fa0fedcb`; both reviewers' earlier tests run (`results/`); CI run 42174316759 green on that head, all five jobs.

1. Second review, in the owner's flow: Codex first, on an export of `d6c063e`, returning full code. A separate Opus checks each snippet against the design and the code, updates it, and adds what Codex missed. With Fable paused, Codex is the one outside family.
2. The coordinator applies the resulting fixes narrowly, as new commits, with the tests from the review.
3. Rerun `deploy/kind-test.sh` to exit 0 if a fix touches the manifests, `render.sh`, `secrets.sh` or `kind-test.sh`.
4. CI green on that exact head, all five jobs.
5. Merge, then add `manifests` to the required checks. GitHub already shows this PR as mergeable (`CLEAN`), because branch protection requires CI and not a review. The review gate is held by these steps alone, so do not merge on GitHub's word.

Codex's six findings at `d6c063e`, not yet checked by reviewer 2 and not applied:

| Severity (Codex's) | Where | Finding |
|---|---|---|
| Medium | `deploy/render.sh` | A failed render destroys the last good render and leaves a marked partial tree |
| Medium | `deploy/secrets.sh` | Reads of later Secrets happen after three Secrets are written, so an empty late Secret stops too late |
| Medium | `40-networkpolicy.yaml` | The Route rule uses the older router label. CRC's `openshift-ingress` carries both labels (read with `oc`), so it works here |
| Medium | `deploy/kind-test.sh` | A partial `kind create` failure leaks the cluster |
| Medium | `docs/12` section 5 | `pg_restore` can leave the target partly restored after an error |
| High | `test_plain_manifests.py`, `render-test.sh` | A workload image from another repository survives the image guards |

## Refusals, recorded

The permission check refused the Opus reviewer's download and local run of `kubeconform`. That stands, and CI runs it. So patch 06's pinned schemas and the patched manifests have not been through kubeconform until CI does.
