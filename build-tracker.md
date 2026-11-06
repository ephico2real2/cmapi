# cmapi build tracker

What is done, what is in progress, what remains, and which cluster proved each thing. The next-step instructions are in
[`HANDOVER-AND-RESUME.md`](HANDOVER-AND-RESUME.md). Last updated 2026-11-06 by the coordinator, from `git`, `gh` and `oc`, after PR #89 merged, during Wave 1's design.

**Proof** says where a result came from: **CI** is GitHub Actions on the named run, **kind** is a throwaway cluster on the
Mac, **CRC** is OpenShift Local. "None" means it has not run anywhere. A kind pass never counts as a CRC pass.

## Where it stands

| | |
|---|---|
| Merged to `main` | PR #40 and PR #89 (plain YAML) |
| In progress | Wave 1 (#94). Design arbitrated in `docs/reviews/2026-11-06-wave1-design/README.md`. Next, the implementer builds it. Nothing is applied to CRC |
| On CRC | No cmapi workload. Namespace `cmapi` holds Secret `cmapi-ldap-bind` and OpenShift's own generated Secrets. LDAP holds the bind user and the `cmapi-*` groups |
| Next action | The implementer builds Wave 1 from that design, then the review flow in `CLAUDE.md`. Tell the owner before anything is applied to CRC |
| Running | Nothing at this update. `cmapi-test-pg` stays up for the service tests |
| Whole app | Not done. The thin slice ends at Wave 5, and the product scope at Wave 9 |

## Done

| What | Proof | Where |
|---|---|---|
| Service: API, worker jobs `open_pr`, `pr_checks`, `watch_sync`, `prune`, `channel_notify`, `open_revert`, migrations 0001 to 0003 | CI: 312 service tests. kind: api and worker Ready, `/readyz` 200, `kind-test.sh` exit 0. Not on CRC | `cmapi/` |
| Plain YAML, `render.sh`, `secrets.sh`, `kind-test.sh`, existing-PostgreSQL guide, `manifests` CI job (#88, #90, PR #89) | kind on Podman: `kind-test.sh` exit 0, image built from `f3ebd9a`; migrate connection `pg_stat_ssl True TLSv1.3`. CI: kubeconform, and the policy blocking another namespace on Docker-backed kind. **No pod has started under the policy on podman kind.** Not on CRC | `deploy/manifests/`, `deploy/`, `docs/12`, `docs/reviews/2026-11-05-pr89/` |
| Deployment design: one merged design with rulings | kind: Argo CD 3.5.6, three accident tests, no namespace lost | `docs/reviews/2026-11-05-deployment-design.md` |
| Reference modules | CI `reference-code`: 121 tests | `examples/src`, `examples/tests`. Their copy in `cmapi/src/cmapi/core` has `cmapi/tests/core`, which no CI job runs: None until one does |
| Image | Built locally. Not published | `cmapi/Containerfile` |
| Portal UI on mock data (no sign-in, no API call) | CI: `portal-ui`. **Must not be deployed as the portal** | `cmapi-portal-ui/` |
| Portal mockup | CI: 8 tests | `mockups/portal/` |
| Three review passes on the service | Opus and Codex; auth, token and admission on passes 2 and 3 were Opus only | `docs/reviews/2026-11-05-pr40.md` |
| LDAP bind user `cmapi-ldap-bind`, `cmapi-*` groups | CRC. Federation not login-tested | `docs/11` |
| Branch protection on `main`: `reference-code`, `service`, `portal-mockup`, `portal-ui`, `manifests` | GitHub | |

## Remaining, in waves

Each row is one or more pull requests through the delivery loop in `CLAUDE.md`. Waves 2 and 3 can run in parallel. Wave 4
needs 3, Wave 5 needs 2 to 4, and Waves 6 and 7 need 5.

| Wave | Work | Issues | Owner step | State |
|---|---|---|---|---|
| 0 | Plain YAML merged | #88, #90 | None | **Done** |
| 1 | **Interim deployment on CRC:** `oc apply`, image in CRC's internal registry by digest, realm import, reader baseline, Routes, screenshots. No real namespace request yet. Also: `secrets.sh` checks `GET <issuer>` so it cannot mint values behind a kept realm; `cmapi-imports` namespace; the two Keycloak URLs. Prove the Route through the NetworkPolicy: CRC's router uses `HostNetwork` on one node (read with `oc`), so the same-node rule should allow it, which is inferred until it answers. **The other realms stay unaffected and undeleted, and a backup of the Keycloak database comes first (see the risks)** | #94, #96 | Trust the two CAs in the login keychain for Chrome; sign in once as an LDAP person | Design done, build next |
| 2 | Argo CD on kind: bootstrap, narrowed role, policies, approver. Per-namespace ApplicationSet, `Delete=confirm`, `core/sync.py`, `watch_sync`, `docs/01`. Tests `e5`, approver, and `scale` before the layout merges | #65, #64 | None | Pending |
| 3 | GitHub adapter, App auth, `pr_status`, config repo checks, a real PR on `cluster-configs-nonprod`. Gitea removed | #87, #60, #61, #59, #97 | Create and install the GitHub App | Pending |
| 4 | End-to-end CI on kind; release to GHCR with attestation, `deployed/crc`, rollback. Charts removed, each test mapped to its YAML replacement | #85 | Make each GHCR package public | Pending |
| 5 | Argo CD on CRC adopting Wave 1's objects. A real request through a real PR, then a delete, screenshots. `apply` removed. **Thin slice done** | #64, #65, #85, #84 | None | Pending |
| 6 | Portal on the API: OIDC PKCE, TanStack Query, its own image. New namespace, Requests and Approvals first. Team DL field | #33 | None | Pending |
| 7 | CLI and `cmapi-sdk`. `cmapi-capacity`, the real capacity guard, quotas (phase 3) | #62 | None | Pending |
| 8 | Service accounts, grants, tokens (phase 4). Lifecycle, policies, operations, OpenTelemetry, the remaining KPIs (phase 5). LDAP hardening. **Load test: the proof that KPIs work, and the budgets at 5,000 namespaces.** A month of KPI data is a later check on real use, not a gate | #35, #36, #92 | Decide #35 and #36 | Pending |
| 9 | One Helm chart per component under `helm/`, none for Keycloak or LDAP. Final walk from a clean start using only the guide (admin, non-admin, CLI). Phase 6 | | None | Pending |

### Not built, by area (`docs/08` section 4)

- **Service:** config hot reload, most KPIs, metadata plugin, OpenTelemetry, route rate limits, the LDAP directory provider.
- **Endpoints:** expirations, tiers, quota writes beyond the namespace PATCH, metadata, service accounts, grants, SCC grants, tokens, policies, cluster import, capacity and placement, adoption, reports, operations, admin reload.
- **Worker jobs:** `expire_check`, `reservation_expiry`, `policy_report_sweep`, `import_clusters`, `reconcile`, `kpi_export`, `outbox_publish`, `operations`.
- **`cmapi-capacity`:** all of it.
- **Portal:** every API call, sign-in, its Containerfile.
- **CLI and SDK:** not started.

### Stories and epics

Issues #7 to #12 are the epics and #13 to #29 the stories. The owner decided, on 2026-11-05: a pull request links with `Part of #N`, and a story closes only after the owner approves, with a comment citing the proof for each criterion and the cluster it ran on. An epic closes when all its stories have. No story has closed.

| Linked so far | Stories |
|---|---|
| PR #40 | #13, #14, #15, #16, #17, #18, #19, #25, #27 (partial) |
| PR #4 | #20 (mock data only) |
| PR #89 | #28 (deployment only) |

Paperclip, the source these drafts were published from, is off for now. Reading the five items it never published to GitHub is parked in #93. Issue #6 records these decisions. Its language review requirement stands and has not been done for any story; closing comments say so.

## Open risks

| Risk | What is known | Guard |
|---|---|---|
| `keycloak-0` on CRC restarted at 20:17:02 UTC on 2026-11-05 (exit 143, then failed probes) | cmapi changed nothing in `keycloak`. A kind cluster was running on the Mac at that time, so test load is not ruled out. Cause unknown. A later short kind run left the count at 1 | No kind cluster during a CRC step. Record the restart count around each one |
| A realm import may restart the shared Keycloak, which has one instance | corp, inkcast-staging and inkcast-prod were imported on 10-28, 10-28 and 11-04 without restarting `keycloak-0`. Red Hat reports restarts on 22.x, 24.x and 26.0.x; CRC runs 26.6.7. The one measured restart took 2 min 42 s for every realm | The owner requires the other realms unaffected and not deleted, and no long outage. Exact names only; compare each realm's status and public key hash before and after; poll through the import; if it restarts, stop and take no action on Keycloak. A `pg_dump` first, approved by the owner, kept outside git and deleted once verified |
| An import can start long after its Job is created | `inkcast-prod`'s started about 6.5 days after, `inkcast-staging`'s 5h51m. Cause not known | Bound the wait, and be able to withdraw our own import |
| One review family | Fable is paused. Codex is the only other family, and OpenAI's filter stopped Codex on auth and admission checks earlier | Each PR states who reviewed. Flag any PR touching auth or admission |
| A bad merge in the config repo puts every Application into deletion | Measured on kind: no namespace lost, but a person must remove each finalizer | `path-authority` check, approver guard, alert (Wave 2 and 3) |
| Argo CD's cluster-wide read of ConfigMaps | 535 on CRC, mostly other projects' | Wave 2 tests narrowing |
| Network policies break DNS on podman kind | Measured, cause unknown. `kind-test.sh` deletes the policy on podman kind only; it ships unchanged. CI's Docker-backed kind shows it blocks another namespace, on a running pod | CRC decides |
| Memory on CRC | Requests 15,525 Mi of 19,543 Mi. The plan adds 832 Mi with Argo CD. An import Job requests 1,700 Mi while it runs, so it must not be scheduled alongside cmapi's 576 Mi | Stop if headroom is under 2 GiB. Import first, alone |

## Open bugs

#87 `pr_status` misses check runs. #96 `realm_sync` reads an unreachable directory as success. #97 a private-CA-only bundle fails GitHub TLS. #91 connections to CNPG are encrypted but do not verify the server, no wave yet. #94 Wave 1. #59, #60, #61, #62, #64, #65, #84, #85 as in the waves. #33 Team DL. #35, #36 LDAP.
