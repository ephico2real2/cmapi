# cmapi: handover and resume

Read this first to continue the build from a new session, with nothing else in hand. The tracker is
[`build-tracker.md`](build-tracker.md), the rules are [`CLAUDE.md`](CLAUDE.md), and the measured log is
[`CRC-BUILD-STATUS.md`](CRC-BUILD-STATUS.md). Updated on 2026-11-13, before the owner cleared the session.

**The next run.** The owner plans a run by OB1 (Fable 5.2) with the prompt in [`OB1-PROMPT.md`](OB1-PROMPT.md): build the whole application as designed, deploy and test it on CRC and kind, and fix bugs as they appear, documenting features as they land. That prompt replaces `CLAUDE.md`'s delivery loop for that run only. The owner, 2026-11-13: "change ob1 to use fable 5.2". So the Fable pause is lifted for OB1's run, and OB1 writes the code itself. Start the session with `claude --model claude-fable-5-2` in the worktree, since the prompt cannot set the model. Everywhere else the pause and "Who does what" below still apply. The owner, 2026-11-13: "let ob1 knows that it has full autonomy". The prompt says so in its own section, "You have full autonomy". Then: "do not ask me questions yourself bacsie i might fell asleep - i give you the mandate to make decisions here for ob1". The coordinator's decisions for the points below that say "ask the owner" are in the prompt's "Decided for you": the second pass runs on Codex alone without C8; #91 lands before the CRC run; the hooks are applied without showing the owner the diff; `keycloak-tls` is not reissued; mail stays off. That list wins over this file where they differ. Later the same day the owner added: the `/agile` records for every issue, writing in Simplified Technical English, diagrams with `/visual`, new docs for authorization (docs/14) and the Keycloak integration (docs/15), the data model and API contract with real sample payloads, and every bug filed and fixed at once. OB1 owns all of it end to end, with web search allowed. The prompt's "Records, language and diagrams" and "Authorization, Keycloak, the data model and the API contract" hold the detail. The API-docs defects #127 to #134 are filed under #13. The `/simple` STE skill the owner named is not in diagram-kit, so the prompt gives ASD-STE100's core rules until it appears.

**Two more owner instructions, 2026-11-13, sent to OB1 through the coordinator after the run began.** First: "also if is important that we have diagrams as well." Diagrams are a required deliverable: the list of figures is in the prompt, under "Records, language and diagrams". Second: "we can use postgress for cache as well if needed so we don't have to use redis or vakkey". cmapi adds no Redis and no Valkey, and a shared cache uses cmapi's PostgreSQL: the detail is in the prompt, under "The database: CloudNativePG".

**The cache reference, 2026-11-13.** The owner: "check my inkcaskhq/kvpg". That is `github.com/inkcasthq/kvpg`, read by the coordinator at `f654a121820f`. It is the reference for a cmapi cache in PostgreSQL, not a dependency: cmapi keeps its contract v1 in a small Python store, on a logged table, only if a shared cache is needed. Never change kvpg and file nothing there. The owner then widened it: "ob1 is free the python equiavlanet to add a similar or use an existing public one as well". So OB1 can build the store or use a public Python library that passes the checks in the prompt. No choice is made yet, because no shared cache is needed yet. The detail is in the prompt, under "The database: CloudNativePG".

## Where these files are

This file and `build-tracker.md` are at the root of the repository, on `main` from PR #89. Keep them current on the working branch. The auto-memory note `project-cmapi-resume-point` points here.

To start the next session, paste this:

> On branch `ldap-rbac-names`, in the worktree `/Users/olasumbo/gitRepos/cmapi-design-crc`, read `HANDOVER-AND-RESUME.md`, `build-tracker.md` and `docs/reviews/2026-11-06-pr112/README.md` in full, then continue from the next action in the tracker. Check the state
> first. Update both documents as you go.

## The goal

Build all of cmapi and deploy it on CRC (OpenShift Local) on this Mac: the service, the portal on the real API, the `cmapi`
CLI and `cmapi-sdk`, with a full end-to-end walk from a clean start and screenshots of the running app.

## State on 2026-11-13, at the end of OB1's run: read this first

OB1 (Fable 5.2) ran as a background agent of the coordinator from about 08:45 to 11:30 UTC, with a stop from 09:45 to 10:24 UTC (`403 authentication_failed`, nothing lost). Its resume file is `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/resume.md`, and its reports are in that folder, outside git.

### The shared Keycloak restarted: #157 (PERF-01). The owner decides what comes next

`keycloak-0` was killed at 08:58:42 UTC (exit 137) and ran again from 08:59:37 UTC. OB1's first kind run for #91 was running on this Mac at that time, with other test jobs, at a load average of 13 to 16. OB1 found the restart at 11:10 UTC, in the read-only checks before the CRC run. Later kind runs gave failed probes and no restart. Each realm answered 200 at 11:10 UTC. cmapi wrote nothing to namespace `keycloak`.

As the prompt says for a Keycloak restart, OB1 stopped all CRC work, took no action on Keycloak and reports it. So **the Wave 1 run on CRC did not start.** OB1 also runs no kind cluster on this Mac again. The owner decides two things:

1. Whether the CRC run starts after this restart.
2. How kind proofs run while CRC is up on the same Mac. The options are in #157.

### What is done

| Item | State |
|---|---|
| PR #112 | Merged as `99093d8`: #118, the second pass by Codex `gpt-6.1-sol` with three fixes (#136, #137, #138), CI green on the exact head |
| The `/agile` sweep | Done for each open issue. Milestones `W1` to `W9`. `issue-register.md` has 0 open issues without a work tag |
| The API documentation of `docs/01` (#127 to #134) | PR #135, merged: tags and groups, curl samples, ETag, `/docs/changelog`, the CI job `api-contract` with oasdiff, `docs.public`, no CDN |
| `docs/14`, `docs/15`, `docs/16`, #141 (BUG-30) | PR #153, merged. Codex read the fix of #141 and found no defect. The figures of `docs/14` and `docs/16` are drawn |
| #139 (BUG-29), #142 (BUG-31) | PR #140 and PR #152, merged |
| `docs/04` and the OpenAPI examples from a run, #154, #155 | PR #156, open. Its first CI run failed on Linux in the samples test. A fix is pushed (`1ec2f20`), and its CI result is not read yet |
| #91 (SEC-04) | PR #158, open, proven on kind. Its CI result is not read yet |
| The architecture figures from the mockup | Five figures, light and dark, on branch `diagrams` (`3cad6ed`, pushed, no pull request). They say "realm cmapi: not on CRC yet" |
| Filed for later waves | #143, #144, #145 to #151 |

### What is not done

- **Wave 1 on CRC, and each wave after it.** No cmapi workload is on CRC. The read-only checks of 11:10 UTC: `oc whoami` is `kubeadmin`, namespace `cmapi` has no workload, both `cmapi-ldap-bind` Secrets are there, the CloudNativePG CRD is there, and node memory requests are 15,525 Mi (79%).
- `docs/15` has no real token, no sign-in sequence figure and no CRC result. Each is marked in the document.
- The CRC screenshots of `/docs` and `/redoc`, which also need the owner's keychain step.
- The stories #13 to #29 have no new proof comment.

### Order from here

1. The owner reads #157 and decides.
2. Read CI on PR #156 and PR #158 (`gh pr checks`). Merge each when each job has passed on its head. If #156's samples test fails again, its message now names the path that differs.
3. Open a pull request for branch `diagrams`, after the figures say the true state of CRC.
4. The CRC run from `docs/13`, from a clean checkout of `main`.

**A refusal that stands.** Claude Code refused the download of the oasdiff binary to this Mac ("Code from External"). So oasdiff runs in CI only. The exact command is in OB1's `recommendations.md`.

**A lesson for the documents.** `docs/14`, `docs/15` and `docs/16` cite code as `file:line`. PR #152 moved lines in `core/db/repo.py`, and the citations of `docs/16` were wrong until this update. Check them after each change to a cited file.

## Where it stopped

- `main` is at `5dfdea3`: PR #40, #89, #95, #98, #111 and #114. Nothing from them is on CRC yet.
- **Wave 1 (#94): code merged, not run on CRC.** Realm `cmapi` does not exist yet. PR #112 (draft, branch `ldap-rbac-names`, worktree `/Users/olasumbo/gitRepos/cmapi-design-crc`) sets the group names `app-cmapi-rbac-<role>` and the `cmapi.<role>` test users, the owner's decision, and must land before the one-shot import. Until it merges, **this file and the tracker on that branch are the current ones; `main`'s are older.**
- **Exactly where the review stands:** `docs/reviews/2026-11-06-pr112/README.md`. Reviewer 2's eleven patches are validated, accepted and on the branch, one commit each, `47ddb4f` to `0bde88c`. CI was green on all 5 jobs at `0bde88c`, and again at `9535ad2`, read on 2026-11-07. At `5f041b3`, which changed only documents, `manifests` failed in its "Tools" step: `curl: (22) ... 503`, downloading a tool before any test ran. The failed job was re-run on 2026-11-13, with the result not read yet. Any later commit needs its own run before CI is cited.
- **What PR #112 still needs, in order:**
  1. **#118:** apply `docs/reviews/2026-11-06-pr112/night/118/118.patch`, unchanged, one commit, with `Closes #118`. Opus 5.5 wrote it. Codex and the coordinator proved it, and the record gives each result. Its timing claim H5 did not finish, and Linux is left to CI.
  2. **The second pass:** the owner stopped it before it began, on the night of 2026-11-06. **Ask the owner whether it still runs.** Its brief is `second-pass-brief.md`, with `@@HEAD@@`, `@@COMMITS@@` and `@@GRAPH_ROOT@@` to fill. It was planned as Codex and Cursor. Codex finished #118's proofs, so name that in the brief or give #118's claim (C8) to Cursor.
  3. Mark the draft ready, CI green on the exact head, merge.
- **The first CRC run: the owner's go-ahead is given,** on the night of 2026-11-06: "go ahead with the CRC run after #112 merges". So once #112 merges, follow `docs/13` from a clean checkout of the merged commit. Nothing else may be running on the Mac, and no kind cluster. The owner still has to do the Chrome steps, and has reported no keychain result yet.
- **Merging:** the owner, 2026-11-06: "i want you to merge once all things clear". Merge when CI is green on the exact head and the review has passed.
- **Tokens:** the owner: "pls make sure we are NOT wasting claude token". Put long work on Codex and Cursor, and let the main session wake on a waiter, not poll. Report only what changed. One Claude agent at a time, only on what blocks the next step.
- **Other issues run alongside, on Codex and Cursor:** the owner, 2026-11-06: "you also need to continue working on other issues". #87 and #91 are no longer parked. Both were stopped midway:
  - **#87:** reviewer 1's answer is in `night/87/`. **Two findings, not yet re-checked by the coordinator:** C1, `neutral` and `skipped` read as failures, unlike GitHub's required checks; C3, a commit with 1,001 check suites hides a failure. Patches `C3.patch` and `C5.patch` are saved. C5, C6 and C7 were not reached, and its baseline log was contaminated by overlapping runs, so run it again serially. It needs its own empty database in `cmapi-test-pg`.
  - **#91:** Codex's continuation of the WIP on branch `fix-cnpg-verify-full` is `night/91/91-on-top-of-wip.patch`, which includes a new test file. It removed a measurement the WIP had claimed in `docs/08` without having run it. H1, H2 and H4 are PLAUSIBLE until the kind proof runs (K1). Its commands were not written before the stop, so write them from #91's "How to prove it". The coordinator has to run it, since Codex's sandbox has no container runtime. Never during a CRC step. It changes how the app connects to the database, so decide whether it goes before or after the first CRC run.
- **Defects:** the owner's process is `.claude/skills/fix-defect/SKILL.md`. Every defect gets an issue, including on an unmerged pull request.
- **The owner's keychain step:** commands in `LOCAL-DEV-TRUST.md`. No result reported yet. Keycloak's certificate has no Extended Key Usage, so Chrome may refuse it.
- **Branch protection requires CI, not a review.** GitHub will show a pull request as mergeable with its review unfinished. The review gate is held by the delivery loop alone, so do not merge on GitHub's word.
- No cmapi workload on CRC, and `/realms/cmapi` answers 404 (read earlier on the night of 2026-11-06). Check before trusting this: `oc get all -n cmapi`. No agent, test or kind cluster was running at this update, and `cmapi-test-pg` is the only container, up for the service tests. `keycloak-0` was still at 1 restart.
- **Pending: an automatic handover, from diagram-kit.** The owner asked on 2026-11-07 for the handover, the resume and the build tracker to run by themselves and survive `/compact`, auto-compact and `/clear`: through Claude Code hooks (Stop, PreCompact, SessionStart) in this project's `.claude/settings.json`, a note per topic at `claude-resumes/`, kept out of git, and a self-check script. This project has no such skills: the only project skill is `fix-defect`, and these two files are kept by hand. The owner then said another session builds the skills in diagram-kit: **diagram-kit PR #38**, "Make the handover automatic: handover, build-tracker and resume-work, with four hooks", **merged on 2026-11-10**. The local `main` in `/Users/olasumbo/gitRepos/diagram-kit` has the skills at `skill/handover/` (with `scripts/`), `skill/build-tracker/` and `skill/resume-work/`. **Not applied here yet:** read the three in full, then apply them. Show the owner the settings diff before saving it, and confirm each hook against the official hooks documentation. Until then, keep these two files current by hand, as before.
- **Not in this repository, for the owner to decide:** `claude-config` PR #3 (the tokensave entries in its settings) is open. A restore from that repository's `main` removes tokensave's hooks and permissions, and sets `model` to Fable. `~/.tokensave-fork-backup-20261106` holds copies of the agents' configs, `.claude.json` among them: delete it once the setup is settled.
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

The owner's latest words decide. On 2026-11-05: "Let us stop using fable for now", then "Use opus 5.5 high". On the night of 2026-11-06: "we won't use fable tonight but use opus and codex and cursor agent for review", "we can move codex to gpt-6.1-sol", and, about #118, to hand it to Codex. Whether Cursor stays a reviewer after that night is the owner's to say. The roles and the rest of this table are `CLAUDE.md`'s.

| Role | Who |
|---|---|
| Implementer | Opus 5.5 at `high`: a fresh `general-purpose` agent with `model: opus`, `effort: high`, working in the worktree |
| Reviewer 1 | Codex (`codex exec -m gpt-6.1-sol`, CLI 0.167.0, with read and write access to its export; 0.144.1 answered `model_not_found`). Returns the full code of each fix and test |
| Another reviewer, that night | Cursor's agent, `cursor agent -p`, planned on `grok-4.7-high` for a third family. Probe the name first: only its default model has answered here so far. Its job folder has no network or container runtime |
| Reviewer 2 | A separate Opus 5.5 agent at `high` that did not write the step, on an export. Checks each of reviewer 1's snippets against the design and the code and updates it, and reports with full code what reviewer 1 missed |
| Coordinator | The main session: briefs, re-checks every verdict, arbitrates, records, merges. Applies reviewer 2's resulting fixes narrowly, and sends back any that do not fit. Authors no application code |

Agents do not survive a session, so a new session starts fresh ones with a full brief. Codex's run script shape: `cd "$W" && codex exec --skip-git-repo-check -m gpt-6.1-sol -c model_reasoning_effort="high" -s workspace-write -c sandbox_workspace_write.network_access=true -C "$W" "$(cat "$W/brief.md")"`, with stdin from `/dev/null`, in the background, with one waiter on its pid. The scratchpad is not kept, so anything worth keeping goes in the repository.

**Every brief, from `agent-report` in diagram-kit:** paste the brief standard, because the owner requires agents to write structured reports as they go. Two lessons from that night: give the report folder as an **absolute path**, since a job working inside `head` wrote `head/report/`, which looked like no report at all; and say that new files go in the patch, since a plain `git diff` misses them. Also from there: `fix-defect`, `adversarial-review` and `codex-arbiter`'s lessons for the arbiter. `sweep-stale` reports leftover processes, and `--sweep` is asked for first. The agents' graph is tokensave: `.tokensave/` is in both checkouts, excluded through `.git/info/exclude`, and this session's own tools load only in a new session.

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
| Any time | Apply the automatic handover: the four hooks and the three skill links. See "The automatic handover: checked, and waiting for the owner" |
| Wave 1 | For the Chrome proofs: trust the two CAs in the login keychain ([`LOCAL-DEV-TRUST.md`](LOCAL-DEV-TRUST.md)), and sign in once as an LDAP person |
| Wave 3 | Create the GitHub App from the manifest flow, and install it on `cluster-configs-nonprod` only |
| Wave 4 | Make each GHCR package public, after its first push |
| Wave 8 | Decide #35 and #36 (LDAP) |

### The automatic handover: checked, and waiting for the owner

OB1 checked diagram-kit's four hooks against the hooks reference (<https://code.claude.com/docs/en/hooks>, read on 2026-11-13). Each one matches it:

| Hook | The skill's block | The reference |
|---|---|---|
| Stop | `handover.py stop`, timeout 10 | "`decision: "block"`, `reason`"; the inputs `stop_hook_active` and `background_tasks`; "Claude Code applies an 8-consecutive-continuation cap" |
| PreCompact | matcher `manual\|auto`, `handover.py precompact`, timeout 10 | Matcher values "`manual`, `auto`"; "Claude Code uses its stdout as instructions for the compaction summary. Keep that stdout under 10,000 characters per hook" |
| SessionStart | matcher `startup\|resume\|clear\|compact`, `handover.py session-start`, timeout 10 | Values "`startup`, `resume`, `clear`, `compact`, `fork`"; "The `additionalContext` field passes a string from your hook into Claude's context window" |
| PostToolUse | matcher `Bash`, `handover.py post-tool`, timeout 5 | The matcher filters on the tool name; `timeout` is "Seconds before canceling." |

OB1 did not apply them. The change is to Claude Code's configuration: a new `.claude/settings.json` with hooks in this repository, and three links in `~/.claude/skills`. OB1 runs as a background agent, and its rules do not let an agent's message authorize a configuration change. The decision to apply without showing the diff reached OB1 through the coordinator, not from the owner directly. So this is an owner step:

1. Make the links: `for s in handover build-tracker resume-work; do ln -s /Users/olasumbo/gitRepos/diagram-kit/skill/$s ~/.claude/skills/$s; done`. On 2026-11-13, `~/.claude/skills` has none of the three.
2. Create `.claude/settings.json` in this repository with the `hooks` block of `/Users/olasumbo/gitRepos/diagram-kit/skill/handover/SKILL.md`, section 5, unchanged. The repository has no `.claude/settings.json` today, so the diff is that whole block.
3. Add `claude-resumes/` to `.gitignore`.
4. Start a new session, and check `/hooks`.

Until then, keep this file and `build-tracker.md` current by hand.

## Environment facts

- CRC: OpenShift 4.22.14, Kubernetes 1.35.6. Node requests 15,525 Mi of 19,543 Mi allocatable. 277 listable kinds.
- Keycloak: namespace `keycloak`, RHBK 26.6.7, `KeycloakRealmImport` is `k8s.keycloak.org/v2beta1`. One instance. Route passthrough, certificate from ClusterIssuer `enterprise-ca`, so its public CA is `ca.crt` in Secret `keycloak-tls`, not the ingress CA. LDAP: namespace `ldap-testing`, base `dc=ephico2real,dc=com`.
- Internal registry route: `default-route-openshift-image-registry.apps-crc.testing`.
- Mac: hostname `olas-MacBook-Pro.local`, Intel Core i9-9980HK (`x86_64`), macOS 15.8.1, Homebrew in `/usr/local`, 32 GiB, podman machine at 8 GiB, Docker off. `cmapi-test-pg` on port 55432 is the service tests' database. The tokensave fork was updated on 2026-11-13 to `9455c2a`, built with Homebrew's rust 1.98.1, and checked by `/tokensave-fork`'s steps. Its database is now at schema 3, with the copy from before the update at `~/.tokensave/global.db.before-update-20261113T080610Z`. Installed on 2026-11-06: the tokensave fork at `~/.cargo/bin`, pandoc 3.12.1 at `~/.local/bin`, Codex CLI 0.167.0 with `model = "gpt-6.1-sol"` as its default. Python 3.12 is `/usr/local/bin/python3.12`, as CI uses.
- zsh does not split words, and a bare `=====` or `echo ===` fails there, which stopped three commands that night. Use bash for scripts.

## Not proven anywhere yet

Real Argo CD on CRC, RHBK's import of the realm, kubelet and SCC admission on CRC, Routes, the GitHub adapter against GitHub, LDAP federation login, Prometheus scraping, network policies on OVN-Kubernetes, the rollback on a real run.

## Keep this current

Update this file and `build-tracker.md` in the pull request that changes what they say. Before ending a session, re-read both against `git`, `gh` and `oc`.
