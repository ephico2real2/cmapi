# cmapi build tracker

What is done, what is in progress, what remains, and which cluster proved each thing. The next-step instructions are in
[`HANDOVER-AND-RESUME.md`](HANDOVER-AND-RESUME.md). Last updated 2026-11-05 evening by the coordinator, from `git`, `gh` and `oc`, when the owner stopped work.

**Proof** says where a result came from: **CI** is GitHub Actions on the named run, **kind** is a throwaway cluster on the
Mac, **CRC** is OpenShift Local. "None" means it has not run anywhere. A kind pass never counts as a CRC pass.

## Where it stands

| | |
|---|---|
| Merged to `main` | PR #40, merge commit `1f30ab1` |
| In progress | PR #89 (`manifests-plain-yaml`, #88). Reviewed by Opus and Codex: **not safe to apply until its fixes land.** Rulings decided, fixes not applied. See `docs/reviews/2026-11-05-pr89/README.md` |
| On CRC | No cmapi workload. Namespace `cmapi` holds Secret `cmapi-ldap-bind` and OpenShift's own generated Secrets. LDAP holds the bind user and the `cmapi-*` groups |
| Next action | Apply the rulings on PR #89: steps in `docs/reviews/2026-11-05-pr89/README.md`. Patches 01 to 07, then 09, not 08. Remove the patches folder in that commit |
| Running | Nothing: no agents, kind clusters or Codex processes. `cmapi-test-pg` stays up for the service tests |
| Whole app | Not done. The thin slice ends at Wave 5, and the product scope at Wave 9 |

## Done

| What | Proof | Where |
|---|---|---|
| Service: API, worker jobs `open_pr`, `pr_checks`, `watch_sync`, `prune`, `channel_notify`, `open_revert`, migrations 0001 to 0003 | CI: 291 service tests. None on a real cluster until kind below | `cmapi/` |
| Reference modules | CI `reference-code`: 121 tests | `examples/src`, `examples/tests`. Their copy in `cmapi/src/cmapi/core` has `cmapi/tests/core`, which no CI job runs: None until one does |
| Image | Built locally. Not published | `cmapi/Containerfile` |
| Portal UI on mock data (no sign-in, no API call) | CI: `portal-ui`. **Must not be deployed as the portal** | `cmapi-portal-ui/` |
| Portal mockup | CI: 8 tests | `mockups/portal/` |
| Three review passes on the service | Opus and Codex; auth, token and admission on passes 2 and 3 were Opus only | `docs/reviews/2026-11-05-pr40.md` |
| LDAP bind user `cmapi-ldap-bind`, `cmapi-*` groups | CRC. Federation not login-tested | `docs/11` |
| Branch protection on `main`: `reference-code`, `service`, `portal-mockup`, `portal-ui` | GitHub | |

## In progress

| What | State | Proof so far |
|---|---|---|
| Plain YAML, `render.sh`, `secrets.sh`, `kind-test.sh`, existing-PostgreSQL guide, `manifests` CI job (#88, PR #89) | Review done, **fixes to apply**: API port open to every namespace; a failed Secret read treated as absent; `kind-test.sh`, `render.sh` and guide defects | kind: CNPG 1.30.1 healthy, api and worker Ready, `/readyz` 200, ten secrets cases pass in a separate run; `kind-test.sh` as a whole has never exited 0 on record. CI run 42138478365 on `8fe5408`: all five jobs, **on the code with its defects**, so green is not ready. GitHub shows it mergeable because protection requires CI, not a review |
| Deployment design: one merged design with rulings | Goes in with PR #89 | kind: Argo CD 3.5.6, three accident tests, no namespace lost. `docs/reviews/2026-11-05-deployment-design.md` |

## Remaining, in waves

Each row is one or more pull requests through the delivery loop in `CLAUDE.md`. Waves 2 and 3 can run in parallel. Wave 4
needs 3, Wave 5 needs 2 to 4, and Waves 6 and 7 need 5.

| Wave | Work | Issues | Owner step | State |
|---|---|---|---|---|
| 0 | Plain YAML merged | #88, #90 | None | Fixes to apply |
| 1 | **Interim deployment on CRC:** `oc apply`, image in CRC's internal registry by digest, realm import, reader baseline, Routes, screenshots. No real namespace request yet. Also: `secrets.sh` checks `GET <issuer>` so it cannot mint values behind a kept realm; `cmapi-imports` namespace; the two Keycloak URLs | To file | None | Next |
| 2 | Argo CD on kind: bootstrap, narrowed role, policies, approver. Per-namespace ApplicationSet, `Delete=confirm`, `core/sync.py`, `watch_sync`, `docs/01`. Tests `e5`, approver, and `scale` before the layout merges | #65, #64 | None | Pending |
| 3 | GitHub adapter, App auth, `pr_status`, config repo checks, a real PR on `cluster-configs-nonprod`. Gitea removed | #87, #60, #61, #59 | Create and install the GitHub App | Pending |
| 4 | End-to-end CI on kind; release to GHCR with attestation, `deployed/crc`, rollback. Charts removed, each test mapped to its YAML replacement | #85 | Make each GHCR package public | Pending |
| 5 | Argo CD on CRC adopting Wave 1's objects. A real request through a real PR, then a delete, screenshots. `apply` removed. **Thin slice done** | #64, #65, #85, #84 | None | Pending |
| 6 | Portal on the API: OIDC PKCE, TanStack Query, its own image. New namespace, Requests and Approvals first. Team DL field | #33 | None | Pending |
| 7 | CLI and `cmapi-sdk`. `cmapi-capacity`, the real capacity guard, quotas (phase 3) | #62 | None | Pending |
| 8 | Service accounts, grants, tokens (phase 4). Lifecycle, policies, operations, OpenTelemetry (phase 5). LDAP hardening | #35, #36 | Decide #35 and #36 | Pending |
| 9 | One Helm chart per component under `helm/`, none for Keycloak or LDAP. Final walk from a clean start using only the guide (admin, non-admin, CLI). Phase 6 | | None | Pending |

### Not built, by area (`docs/08` section 4)

- **Service:** config hot reload, most KPIs, metadata plugin, OpenTelemetry, route rate limits, the LDAP directory provider.
- **Endpoints:** expirations, tiers, quota writes beyond the namespace PATCH, metadata, service accounts, grants, SCC grants, tokens, policies, cluster import, capacity and placement, adoption, reports, operations, admin reload.
- **Worker jobs:** `expire_check`, `reservation_expiry`, `policy_report_sweep`, `import_clusters`, `reconcile`, `kpi_export`, `outbox_publish`, `operations`.
- **`cmapi-capacity`:** all of it.
- **Portal:** every API call, sign-in, its Containerfile.
- **CLI and SDK:** not started.

Draft issues #6 to #29 are the product backlog and are not edited here.

## Open risks

| Risk | What is known | Guard |
|---|---|---|
| `keycloak-0` on CRC restarted at 20:17:02 UTC on 2026-11-05 (exit 143, then failed probes) | cmapi changed nothing in `keycloak`. A kind cluster was running on the Mac at that time, so test load is not ruled out. Cause unknown. A later short kind run left the count at 1 | No kind cluster during a CRC step. Record the restart count around each one |
| A realm import may restart the shared Keycloak | On this cluster `inkcast-prod` was imported after the container started, and the container kept running. Red Hat reports restarts on 22.x, 24.x and 26.0.x; CRC runs 26.6.7 | Record before and after. If it restarts, stop and report |
| One review family | Fable is paused. Codex is the only other family, and OpenAI's filter stopped Codex on auth and admission checks earlier | Each PR states who reviewed. Flag any PR touching auth or admission |
| A bad merge in the config repo puts every Application into deletion | Measured on kind: no namespace lost, but a person must remove each finalizer | `path-authority` check, approver guard, alert (Wave 2 and 3) |
| Argo CD's cluster-wide read of ConfigMaps | 535 on CRC, mostly other projects' | Wave 2 tests narrowing |
| Network policies break DNS on podman kind | Measured, cause unknown. The test deletes the policy on podman kind only; it ships unchanged | Hosted runner and CRC decide |
| Memory on CRC | Requests 15,525 Mi of 19,543 Mi. The plan adds 832 Mi with Argo CD | Stop if headroom is under 2 GiB |
| PR #89 can be merged by mistake | GitHub shows it as `CLEAN` with its defects still on the branch: protection requires CI, not a review | Hold it to the review record's steps |
| Remote MacBook | The owner mentioned one. It is not the CRC target: CRC runs on this Mac, the owner confirmed. Which machine it is and its purpose are unconfirmed. Tailscale lists `olasumbos-macbook-pro` | Ask before connecting or planning around it |
| CI floats on upstream schema URLs | kubeconform's schema URLs track `master` and `main` | To pin |

## Open bugs

#87 `pr_status` misses check runs. #90 `secrets.sh` error message on Linux. **To file:** connections to CNPG are encrypted but do not verify the server (ruling 4). The Wave 1 issue is also still to file. #59, #60, #61, #62, #64, #65, #84, #85 as in the waves. #33 Team DL. #35, #36 LDAP.
