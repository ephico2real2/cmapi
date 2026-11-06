# Review of PR #89, and the coordinator's rulings

Reviewed at `d21599a` by Opus 5.5 (`opus/`) and Codex (`codex/`), independently, on exports. **The rulings below are decided and not yet applied:** the owner stopped work before the implementer changed anything, so the branch still has every defect listed. Patches were made against `d21599a`. Neither reviewer's fixes have been cross-checked yet.

Verdict from both: do not apply this to the shared cluster until H1 and H2 are fixed. Merging alone writes nothing to a cluster.

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

1. Apply the rulings. New commits only. **Remove `opus/patches/` in the commit that applies them,** so patch files do not reach `main` looking like pending work; git history and `opus/answer.md` keep the record. None of the nine was applied at `8fe5408` (`git apply --check --reverse` on each).
2. Run the whole `deploy/kind-test.sh` on a real `cmapi-test` cluster to exit 0, with the image built from the branch. It has never exited 0 on record, and the patched script has only run on stubs. Record `keycloak-0`'s restart count before and after.
3. Run `codex/review-tests/` and `opus/tests/` against the fixed tree. Where a Codex test expects Codex's exact form and not the behaviour (ruling 3), say so; do not bend the code to it.
4. CI green on that exact head, all five jobs.
5. Cross-check: Codex on the applied Opus fixes and the checksum, a separate Opus reviewer on the rest. With Fable paused, Codex is the one outside family.
6. Merge, then add `manifests` to the required checks. GitHub already shows this PR as mergeable (`CLEAN`), because branch protection requires CI and not a review. The review gate is held by these steps alone, so do not merge on GitHub's word.

## Refusals, recorded

The permission check refused the Opus reviewer's download and local run of `kubeconform`. That stands, and CI runs it. So patch 06's pinned schemas and the patched manifests have not been through kubeconform until CI does.
