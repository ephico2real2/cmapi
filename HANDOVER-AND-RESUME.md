# cmapi: handover and resume

Read this first to continue the build from a new session, with nothing else in hand. The tracker is
[`build-tracker.md`](build-tracker.md), the rules are [`CLAUDE.md`](CLAUDE.md), and the measured log is
[`CRC-BUILD-STATUS.md`](CRC-BUILD-STATUS.md). Updated 2026-11-05 evening, when the owner stopped work.

## Where these files are

Until PR #89 merges, this file and `build-tracker.md` exist only on branch `manifests-plain-yaml`, in the worktree
`/Users/olasumbo/gitRepos/cmapi-design-crc`, not on `main`. `CLAUDE.md` on `main` does not mention them yet. The auto-memory
note `project-cmapi-resume-point` points here for a session started in `/Users/olasumbo/gitRepos/cmapi-design`.

To start the next session, paste this:

> Read `/Users/olasumbo/gitRepos/cmapi-design-crc/HANDOVER-AND-RESUME.md` and `build-tracker.md` in full, then continue from
> the next action in the tracker. Check the state first. Update both documents as you go.

## The goal

Build all of cmapi and deploy it on CRC (OpenShift Local) on this Mac: the service, the portal on the real API, the `cmapi`
CLI and `cmapi-sdk`, with a full end-to-end walk from a clean start and screenshots of the running app.

## Where it stopped

- `main` is at the PR #40 merge, `1f30ab1`, unless a later row of the tracker says otherwise.
- PR #89 (`manifests-plain-yaml`, `Closes #88`): **not safe to apply yet and not merged.** Opus and Codex both reviewed it at `d21599a`. The owner stopped work after the rulings were decided and before any fix was applied, so every defect is still on the branch. Findings, patches, tests, rulings and the remaining steps are in [`docs/reviews/2026-11-05-pr89/README.md`](docs/reviews/2026-11-05-pr89/README.md). Start there.
- **CI being green on #89 does not mean it is ready.** CI passed on `8fe5408` (run 42138478365, all five jobs), and GitHub shows the PR as mergeable, because branch protection requires CI and not a review. Those runs test the defects as they stand. Do not merge until the review record's steps are done.
- **The nine files in `docs/reviews/2026-11-05-pr89/opus/patches/` are proposals, none applied** (checked with `git apply --check --reverse`). Apply 01 to 07, then 09, and not 08, whose content is already in the tracker. Remove that folder in the same commit. `main` holds no patch files and neither checkout has a stash.
- No cmapi workload on CRC. Check before trusting this: `oc get all -n cmapi`. No agent, kind cluster or Codex process was left running; `cmapi-test-pg` stays up for the service tests. `keycloak-0` was still at 1 restart at the stop.
- **CRC runs on this Mac,** and `crc status` here shows it running OpenShift 4.22.14. The owner's "remote MacBook" is this same Mac, as seen from the one they developed on before moving here. There is no second machine to plan around.

## Resume

1. Check the state, read-only:
   ```bash
   gh pr list --state open
   gh pr checks 89
   git log --oneline -5 origin/main
   oc get all -n cmapi
   oc get pod keycloak-0 -n keycloak
   oc describe node crc | grep -E '^\s+memory\s'
   KIND_EXPERIMENTAL_PROVIDER=podman kind get clusters
   ```
2. Find the first row of `build-tracker.md` not marked done, and carry on from it through the delivery loop in `CLAUDE.md`.
3. In the present order: apply the rulings on #89 and finish the steps in its review record, merge, add `manifests` to the required checks, then Wave 1 on CRC, then the remaining waves.

## Who does what

The owner's latest words decide. On 2026-11-05: "Let us stop using fable for now", then "Use opus 5.5 high".

| Role | Who |
|---|---|
| Implementer | Opus 5.5 at `high`: a fresh `general-purpose` agent with `model: opus`, `effort: high`, working in the worktree |
| Reviewers | Codex (`codex exec -m gpt-5.6-sol`, on an export) and a separate Opus 5.5 agent at `high` that did not write the step. The PR states that this is one outside family |
| Coordinator | The main session: briefs, re-checks every verdict, arbitrates, records, merges. Writes no application code |

Agents do not survive a session, so a new session starts fresh ones with a full brief. Codex's run script shape: `cd "$W" && codex exec --skip-git-repo-check -m gpt-5.6-sol -c model_reasoning_effort="high" -s workspace-write -c sandbox_workspace_write.network_access=true -C "$W" "$(cat "$W/brief.md")"`, with stdin from `/dev/null`, in the background. The scratchpad is not kept, so anything worth keeping goes in the repository.

## Decisions that bind the work

- **Plain YAML first.** One Helm chart per independently running component comes later under `helm/`, none for Keycloak or LDAP.
- **CloudNativePG** (open source, 1.30.1 on CRC) by default, with `docs/12-existing-postgresql.md` for an existing server.
- **GitHub, Actions and GHCR, no Gitea.** Actions pushes the image, tests that digest and commits it to branch `deployed/crc`. Argo CD follows that branch, since Argo CD does not watch registries.
- **Argo CD Core 3.5.6** in `cmapi-argocd`, one Application per namespace through an ApplicationSet, with `Prune=confirm,Delete=confirm` on the Namespace, not one root Application. Measured on kind.
- **`cluster-configs-nonprod` is public.** GitHub refuses branch protection on private repos on this account (403). Requester names and emails there are world-readable, which is acceptable only because CRC's directory is fake.
- **The worker posts `cmapi/check`; Actions posts `ci/*`,** each pinned by `app_id`. Codex's signed permit is the recorded next step on #60.
- **Wave 1 is interim:** `oc apply` with the image in CRC's internal registry. Argo CD adopts those objects in Wave 5.

The full reasoning is in `docs/reviews/2026-11-05-deployment-design.md`, with the coordinator's nine rulings at its end. Those rulings change some of the tables above them, so read them.

## Rules that do not bend

- Autonomy: research and choose best practice instead of asking. Every bug gets an issue, then a fix with a test that fails before and passes after.
- A Claude Code permission refusal stands. Do not route around it or edit permission settings. Report the exact command.
- No secrets in git, logs, reports or command lines. TLS verification never off.
- **CRC is shared.** Never restart the VM or a shared service, no `crc stop/delete/config set`. Do not touch `inkcast`, `corp` or group-sync. In `keycloak`, only realm `cmapi` and its import resources, with no master admin credential. In LDAP, only `cmapi-*` additions. Delete only what cmapi created.
- kind clusters are named with the `cmapi-` prefix and use `KIND_EXPERIMENTAL_PROVIDER=podman`, an explicit `--kubeconfig`, node image v1.35.8. **Never run one during a CRC step.**
- Reviewers work on an export, never in a repository. Throwaway containers need a bind check, a marker guard, their own ports and an explicit `--kubeconfig`.
- Cite CI only from a run whose `headSha` equals the head, after it finished.
- No Co-Authored-By or "Generated with" lines. Never force-push or rewrite history.
- Report what was measured, what was inferred and what was not tested. Say which cluster each result came from.

## Steps only the owner can take

| When | What |
|---|---|
| Wave 3 | Create the GitHub App from the manifest flow, and install it on `cluster-configs-nonprod` only |
| Wave 4 | Make each GHCR package public, after its first push |
| Wave 8 | Decide #35 and #36 (LDAP) |

## Environment facts

- CRC: OpenShift 4.22.14, Kubernetes 1.35.6. Node requests 15,525 Mi of 19,543 Mi allocatable. 277 listable kinds.
- Keycloak: namespace `keycloak`, RHBK 26.6.7, `KeycloakRealmImport` is `k8s.keycloak.org/v2beta1`. LDAP: namespace `ldap-testing`, base `dc=ephico2real,dc=com`.
- Internal registry route: `default-route-openshift-image-registry.apps-crc.testing`.
- Mac: 32 GiB, podman machine at 8 GiB, Docker off. `cmapi-test-pg` on port 55432 is the service tests' database.
- zsh does not split words, and `echo ===` fails there. Use bash for scripts.

## Not proven anywhere yet

Real Argo CD on CRC, RHBK's import of the realm, kubelet and SCC admission on CRC, Routes, the GitHub adapter against GitHub, LDAP federation login, Prometheus scraping, network policies on OVN-Kubernetes, the rollback on a real run.

## Keep this current

Update this file and `build-tracker.md` in the pull request that changes what they say. Before ending a session, re-read both against `git`, `gh` and `oc`.
