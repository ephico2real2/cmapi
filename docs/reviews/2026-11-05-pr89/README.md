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

## The steps on this PR

All of it is done. At `d6c063e`: the rulings applied and `opus/patches/` removed; `deploy/kind-test.sh` exit 0 on real kind at `16fa0fedcb`; both reviewers' earlier tests run (`results/`).

Then a second review, in the owner's flow, on exports of `d6c063e`: Codex returned findings with full code (`second-review/codex-answer.md`). A separate Opus checked each against the design and the code, updated it, and added what Codex missed (`second-review/opus-answer.md`, which holds the final code in full). The coordinator accepted all eight resulting patches and applied them unchanged, one commit each, `0ec0e99` to `f3ebd9a`. With Fable paused, Codex was the one outside family.

| # | Finding | Codex's severity | Final | Reviewer 2's verdict |
|---|---|---|---|---|
| 1 | A failed render destroys the last good one | Medium | Low | Amended: Codex's fix changed the render's mode from 755 to 700 |
| 2 | Late Secret checks run after writes | Medium | Low | Code accepted, tests strengthened |
| 3 | The Route rule uses the older router label | Medium | Low | The documented label as the single selector; CRC's `openshift-ingress` carries both (read with `oc`) |
| 4 | A partial `kind create` leaks the cluster | Medium | Low | Amended: Codex's fix could delete another run's cluster |
| 5 | `pg_restore` can leave a partial target | Medium | Medium | Fix replaced: Codex's failed every time on PostgreSQL 16 (measured) |
| 6 | An unreviewed image survives the guards | High | Low | Amended: it guards against a mistake, since whoever edits the manifests can edit the guard |
| N1 | The shipped restore exits 1 on a PostgreSQL 16 target | | Medium | Fixed with 5 |
| N2 | The dump does not wait for the worker, and the row counts are only printed | | Medium | Fixed |
| N3 to N9 | A kubeconfig the run did not create deleted; a test that passes with every namespace allowed; the guard's blind spots; surviving render mutants; a password on an argument list; no apply order in the README; `link/` deleting its target | | Low | Fixed |

The proof on the applied tree is in `results/second-review/` and in `docs/reviews/2026-11-05-plain-manifests-test.md`. CI run 42183308668 was green on `f3ebd9a`, all five jobs, with the first kubeconform run on these manifests. The final head is cited on the PR.

Not proven, carried to Wave 1: the Route through the NetworkPolicy on CRC. The router there uses `HostNetwork` on one node (read with `oc`), so the same-node rule should allow it, which is inferred until the Route answers.

## Refusals, recorded

The permission check refused the Opus reviewer's download and local run of `kubeconform`. That stands, and CI runs it. So patch 06's pinned schemas and the patched manifests have not been through kubeconform until CI does.
