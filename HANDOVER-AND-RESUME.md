# cmapi: handover and resume

Read this first to continue the build from a new session, with nothing else in hand. The tracker is
[`build-tracker.md`](build-tracker.md), the rules are [`CLAUDE.md`](CLAUDE.md), and the measured log is
[`CRC-BUILD-STATUS.md`](CRC-BUILD-STATUS.md). Updated 2026-11-06, when the owner cleared the session during PR #112's review.

## Where these files are

This file and `build-tracker.md` are at the root of the repository, on `main` from PR #89. Keep them current on the working branch. The auto-memory note `project-cmapi-resume-point` points here.

To start the next session, paste this:

> Read `HANDOVER-AND-RESUME.md` and `build-tracker.md` in full, then continue from the next action in the tracker. Check the state
> first. Update both documents as you go.

## The goal

Build all of cmapi and deploy it on CRC (OpenShift Local) on this Mac: the service, the portal on the real API, the `cmapi`
CLI and `cmapi-sdk`, with a full end-to-end walk from a clean start and screenshots of the running app.

## Where it stopped

- `main` holds PR #40, PR #89, PR #95 and PR #98 (`9e1860e`), unless a later row of the tracker says otherwise. Nothing from them is on CRC yet.
- **Wave 1 (#94): code merged, not run on CRC.** Realm `cmapi` does not exist yet. PR #112 (draft, branch `ldap-rbac-names`, worktree `/Users/olasumbo/gitRepos/cmapi-design-crc`) sets the group names `app-cmapi-rbac-<role>` and the `cmapi.<role>` test users, the owner's decision, and must land before the one-shot import. Until it merges, **this file and the tracker on that branch are the current ones; `main`'s are older.**
- **Exactly where the review stopped:** `docs/reviews/2026-11-06-pr112/README.md`. Reviewer 2's eleven patches are saved there, unvalidated. CI is red at `44083ff`: `reference-code` (#117) and `manifests` (#118, not diagnosed).
- **Merging:** the owner, 2026-11-06: "i want you to merge once all things clear". Merge when CI is green on the exact head and the review has passed. This does not cover CRC: **the first CRC run still needs the owner's go-ahead, not yet given.**
- **Tokens:** the owner, 2026-11-06: background agents were "wasting tokens". One agent at a time, only on what blocks the next step. #87 and #91 are parked until Wave 1 is on CRC.
- **Defects:** the owner's process is `.claude/skills/fix-defect/SKILL.md`. Every defect gets an issue, including on an unmerged pull request.
- **The owner's keychain step:** commands in `LOCAL-DEV-TRUST.md`. No result reported yet. Keycloak's certificate has no Extended Key Usage, so Chrome may refuse it.
- **Branch protection requires CI, not a review.** GitHub will show a pull request as mergeable with its review unfinished. The review gate is held by the delivery loop alone, so do not merge on GitHub's word.
- No cmapi workload on CRC. Check before trusting this: `oc get all -n cmapi`. `cmapi-test-pg` stays up for the service tests. `keycloak-0` was still at 1 restart at this update.
- **CRC runs on this Mac, `olas-MacBook-Pro.local`,** and `crc status` here shows it running OpenShift 4.22.14. The owner's "remote MacBook" is this same Mac, as seen from the one they developed on before moving here. There is no second machine to plan around.

## Resume

1. Check the state, read-only:
   ```bash
   gh pr list --state open
   gh pr checks 112
   git log --oneline -5 origin/main
   oc get all -n cmapi
   oc get pod keycloak-0 -n keycloak
   oc describe node crc | grep -E '^\s+memory\s'
   KIND_EXPERIMENTAL_PROVIDER=podman kind get clusters
   ```
2. Read `docs/reviews/2026-11-06-pr112/README.md`, then carry on from the tracker's next action through the delivery loop in `CLAUDE.md`.
3. In the present order: Wave 1 on CRC, then the remaining waves.

## Who does what

The owner's latest words decide. On 2026-11-05: "Let us stop using fable for now", then "Use opus 5.5 high".

| Role | Who |
|---|---|
| Implementer | Opus 5.5 at `high`: a fresh `general-purpose` agent with `model: opus`, `effort: high`, working in the worktree |
| Reviewer 1 | Codex (`codex exec -m gpt-5.6-sol`, with read and write access to its export). Returns the full code of each fix and test. The PR states that this is the one outside family |
| Reviewer 2 | A separate Opus 5.5 agent at `high` that did not write the step, on an export. Checks each of reviewer 1's snippets against the design and the code and updates it, and reports with full code what reviewer 1 missed |
| Coordinator | The main session: briefs, re-checks every verdict, arbitrates, records, merges. Applies reviewer 2's resulting fixes narrowly, and sends back any that do not fit. Authors no application code |

Agents do not survive a session, so a new session starts fresh ones with a full brief. Codex's run script shape: `cd "$W" && codex exec --skip-git-repo-check -m gpt-5.6-sol -c model_reasoning_effort="high" -s workspace-write -c sandbox_workspace_write.network_access=true -C "$W" "$(cat "$W/brief.md")"`, with stdin from `/dev/null`, in the background. The scratchpad is not kept, so anything worth keeping goes in the repository.

## Decisions that bind the work

- **Plain YAML first.** One Helm chart per independently running component comes later under `helm/`, none for Keycloak or LDAP.
- **CloudNativePG** (open source, 1.30.1 on CRC) by default, with `docs/12-existing-postgresql.md` for an existing server.
- **GitHub, Actions and GHCR, no Gitea.** Actions pushes the image, tests that digest and commits it to branch `deployed/crc`. Argo CD follows that branch, since Argo CD does not watch registries.
- **Argo CD Core 3.5.6** in `cmapi-argocd`, one Application per namespace through an ApplicationSet, with `Prune=confirm,Delete=confirm` on the Namespace, not one root Application. Measured on kind.
- **`cluster-configs-nonprod` is public.** GitHub refuses branch protection on private repos on this account (403). Requester names and emails there are world-readable, which is acceptable only because CRC's directory is fake.
- **The worker posts `cmapi/check`; Actions posts `ci/*`,** each pinned by `app_id`. Codex's signed permit is the recorded next step on #60.
- **Wave 1 is interim:** `oc apply` with the image in CRC's internal registry. Argo CD adopts those objects in Wave 5.
- **Stories close on the owner's approval,** with the proof for each criterion cited. Paperclip is off for now. A load test (#92) proves the KPIs; a month of data is a later check. See the tracker's "Stories and epics".

The full reasoning is in `docs/reviews/2026-11-05-deployment-design.md`, with the coordinator's nine rulings at its end. Those rulings change some of the tables above them, so read them.

## Rules that do not bend

- Autonomy: research and choose best practice instead of asking. Every bug gets an issue, then a fix with a test that fails before and passes after.
- A Claude Code permission refusal stands. Do not route around it or edit permission settings. Report the exact command.
- No secrets in git, logs, reports or command lines. TLS verification never off.
- **The other realms must stay unaffected and undeleted, and a restart must not bleed long** (the owner, 2026-11-06). See the tracker's risks. Before the first import, take the `pg_dump` of the Keycloak database the owner approved: outside git, deleted once verified, restored only on the owner's decision.
- **CRC is shared.** Never restart the VM or a shared service, no `crc stop/delete/config set`. Do not touch `inkcast`, `corp` or group-sync. In `keycloak`, only realm `cmapi` and its import resources, with no master admin credential. In LDAP, only `cmapi-*` additions. Delete only what cmapi created.
- kind clusters are named with the `cmapi-` prefix and use `KIND_EXPERIMENTAL_PROVIDER=podman`, an explicit `--kubeconfig`, node image v1.35.8. **Never run one during a CRC step.**
- Reviewers work on an export, never in a repository. Keep Codex's briefs narrow: its Wave 1 design cost 401,608 tokens and its narrow code review 174,046, and the owner does not want them wasted. Throwaway containers need a bind check, a marker guard, their own ports and an explicit `--kubeconfig`.
- Cite CI only from a run whose `headSha` equals the head, after it finished.
- No Co-Authored-By or "Generated with" lines. Never force-push or rewrite history.
- Report what was measured, what was inferred and what was not tested. Say which cluster each result came from.

## Steps only the owner can take

| When | What |
|---|---|
| Wave 1 | For the Chrome proofs: trust the two CAs in the login keychain ([`LOCAL-DEV-TRUST.md`](LOCAL-DEV-TRUST.md)), and sign in once as an LDAP person |
| Wave 3 | Create the GitHub App from the manifest flow, and install it on `cluster-configs-nonprod` only |
| Wave 4 | Make each GHCR package public, after its first push |
| Wave 8 | Decide #35 and #36 (LDAP) |

## Environment facts

- CRC: OpenShift 4.22.14, Kubernetes 1.35.6. Node requests 15,525 Mi of 19,543 Mi allocatable. 277 listable kinds.
- Keycloak: namespace `keycloak`, RHBK 26.6.7, `KeycloakRealmImport` is `k8s.keycloak.org/v2beta1`. One instance. Route passthrough, certificate from ClusterIssuer `enterprise-ca`, so its public CA is `ca.crt` in Secret `keycloak-tls`, not the ingress CA. LDAP: namespace `ldap-testing`, base `dc=ephico2real,dc=com`.
- Internal registry route: `default-route-openshift-image-registry.apps-crc.testing`.
- Mac: hostname `olas-MacBook-Pro.local`, 32 GiB, podman machine at 8 GiB, Docker off. `cmapi-test-pg` on port 55432 is the service tests' database.
- zsh does not split words, and `echo ===` fails there. Use bash for scripts.

## Not proven anywhere yet

Real Argo CD on CRC, RHBK's import of the realm, kubelet and SCC admission on CRC, Routes, the GitHub adapter against GitHub, LDAP federation login, Prometheus scraping, network policies on OVN-Kubernetes, the rollback on a real run.

## Keep this current

Update this file and `build-tracker.md` in the pull request that changes what they say. Before ending a session, re-read both against `git`, `gh` and `oc`.
