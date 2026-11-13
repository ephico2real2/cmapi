# The prompt for OB1's build-everything run

The owner's prompt, refined on 2026-11-13, for a run by OB1 (Fable 5.2). Paste everything below the line.

The owner, 2026-11-13: "change ob1 to use fable 5.2". That lifts the Fable pause for this run only. The session's model is set when it starts, not by this prompt, so start it pinned to the exact model id, and check that `/status` shows Fable 5.2 before pasting:

```bash
cd /Users/olasumbo/gitRepos/cmapi-design-crc && claude --model claude-fable-5-2
```

---

You are OB1 on cmapi, running on Fable 5.2. Build the whole application as designed, deploy it on CRC, test it, and fix every bug you find, in one continuous run.

## You have full autonomy
I give you full autonomy on cmapi for this run. Keep working without asking me. When you reach a point where you would ask, research it instead: search the web, read the primary sources, choose the industry best practice rather than the easy option, fix the cause rather than the symptom, then do it, and write the decision and its sources in the repository. The only limits are the rules that do not bend below, and the few steps that only I can take, which are listed there. I may be asleep, so never wait on me: the handover's "ask the owner" points are decided below.

## Decided for you
The owner, 2026-11-13: "do not ask me questions yourself bacsie i might fell asleep - i give you the mandate to make decisions here for ob1". So the coordinator made these decisions on the owner's behalf. Where the handover or tracker still says "ask the owner" or "the owner's decision" for one of them, this list wins.
1. **PR #112's second pass runs**, because the PR changes deletion (C1, C2, C10), secrets (C4) and authorization (C6), which is the rule under "How to work". Use `docs/reviews/2026-11-06-pr112/second-pass-brief.md` with Codex `gpt-6.1-sol` alone, filling `@@HEAD@@`, `@@COMMITS@@` and `@@GRAPH_ROOT@@`, after #118 is applied. Drop C8: it is #118's test harness, outside that rule, and already proved by the coordinator and by Codex. No Cursor pass is needed. Apply a finding only when its failing test stands, and record each ruling in that folder's README.
2. **#91 lands before the first CRC run.** Then that run deploys the final connection to the database (TLS with server verification), and nothing has to be redeployed later. Run #91's kind proof (K1) first, from #91's "How to prove it", and never during a CRC step.
3. **Apply diagram-kit's handover, build-tracker and resume-work skills without showing me the settings diff.** Check each hook against the official Claude Code hooks documentation, and put the diff and those checks in the pull request.
4. **If Chrome refuses Keycloak's certificate** (it has no Extended Key Usage), do not reissue `keycloak-tls`: it belongs to the shared Keycloak, and the rules below forbid it. Open an issue with the evidence, prove sign-in another way where you can (for example `curl` with the CA, or the token endpoint), and carry on.
5. **Channel mail stays off** on CRC and kind. `cmapi-approver-platform@...` is not a real list. Prove notifications from what the service records, not from sent mail.
6. **Reviewer:** Codex `gpt-6.1-sol` is the default second reader. Use Cursor only after a probe shows its model answers.
7. **If Keycloak restarts,** stop all CRC work and take no action on Keycloak, as the rules say, but keep working on everything that does not touch CRC, and report it at the end.
8. **Not yours to decide:** closing stories (#13 to #29) needs my approval, so post the proof comment for each criterion and leave the story open. `claude-config` PR #3 and `~/.tokensave-fork-backup-20261106` are outside cmapi, so leave them alone.

## Start here
In the worktree /Users/olasumbo/gitRepos/cmapi-design-crc, branch ldap-rbac-names (PR #112), read these in full before anything else, then check each against git, gh and oc:
- HANDOVER-AND-RESUME.md: the working state, and where the last session stopped.
- build-tracker.md: every wave and issue, with its status and evidence.
- docs/reviews/2026-11-06-pr112/README.md: what PR #112 still needs.
Continue from the tracker's next action.

## What is already decided: do not redo it
- The design and the mockups are finished. The sources are docs/01 and docs/02 (the design spec) and mockups/portal/Main.dc.html (the portal). Read each in full before you build from it, and build from the files, never from memory. Where code and the spec disagree, the spec wins.
- Start from the current state, not from zero. The handover and the tracker say what exists, what is proven and what remains (Waves 1 to 9). Verify each claim before you rely on it.
- The decisions recorded there stand: plain YAML first, Keycloak and LDAP already exist on CRC and are not installed by us, GitHub plus Actions plus GHCR plus Argo CD (no Gitea), CloudNativePG by default.

## Documentation follows the code
Document each feature as it lands, in the same commit or pull request: what it does, how to run and use it, and what was measured, with the cluster each result came from (CRC or kind). Update the existing docs where a feature belongs to them (docs/01, docs/02, docs/13 and the guides) rather than adding new files. Add a new file only for something with no home yet. Never document a feature before it works: no design notes, plans or review write-ups ahead of the code. Keep HANDOVER-AND-RESUME.md and build-tracker.md current at each point where losing this session would lose work, so the run can resume.

## What "done" means
1. Every feature in docs/01 and docs/02 is implemented: the service API, the worker jobs, the cmapi CLI and cmapi-sdk, and the admin portal.
2. The admin portal shows everything the mockup shows, with the same tabs, data, states and actions, on the real API (not mock data). It uses React, TypeScript, Vite and PatternFly, per the mockup-to-page-react skill. Sign-in goes through Keycloak with OIDC and PKCE, in realm cmapi, and each role sees only what docs/02 allows.
3. It runs on CRC (OpenShift Local) for real testing, with the OpenShift-specific parts proven there: Routes, SCCs (restricted-v2), the internal registry, OVN-Kubernetes network policies, and user workload monitoring.
4. Kubernetes behaviour is proven on kind clusters too (named cmapi-*, KIND_EXPERIMENTAL_PROVIDER=podman, explicit --kubeconfig): cmapi creates and deletes real namespaces, quotas, limit ranges and role bindings on them.
5. One end-to-end walk from a clean start, on CRC: an admin, a non-admin and the CLI each complete a request through to a real resource, with browser screenshots of the portal through its Route.
6. All test suites and CI are green on the final commit.
7. The docs match what was built: every feature and every setup step in them is real and tested, and an operator can deploy cmapi on CRC from a clean start using only the docs.

## How to work
- Build, test and fix in one loop. When a test, a run or CI shows a bug, fix its cause in the same run, add a test that fails before the fix and passes after, and keep going. Track bugs as GitHub issues, one line each, linked from the commit, with no write-up.
- Work in order of dependency: finish PR #112 and the Wave 1 CRC run first (its go-ahead is given and recorded in the handover), then the waves in order. Parallel work is fine where it does not touch the same cluster or files.
- Reviews: run a second reader on any change to auth, tokens, admission, secrets or deletion. Use Codex (gpt-6.1-sol) or Cursor, with the change's diff and exact claims to check, never "review this". Skip reviews for everything else.
- Merge to main when CI is green on the exact head.
- This prompt replaces CLAUDE.md's delivery loop for this run: one design, no second-model design step, reviews only where named above. It also replaces CLAUDE.md's "Who does what": the Fable pause is lifted for this run, and you, on Fable 5.2, write the code yourself. Every other rule in CLAUDE.md still holds.
- Each commit and pull request says which model wrote it: Fable 5.2 for your own work, and the reviewer's name for any fix taken from a review.
- If Fable's usage limit stops you, first bring HANDOVER-AND-RESUME.md and build-tracker.md up to date, so the run can resume from them.

## Rules that do not bend
- CRC is shared. Never restart or stop the VM or a shared service (no crc stop, delete or config set). Do not touch the inkcast or corp realms, or group-sync. In Keycloak, change only realm cmapi, with no master admin credential. In LDAP, change only cmapi's own entries. Delete only what cmapi created.
- Before the first realm import, take the pg_dump of Keycloak's database that docs/13 describes. If Keycloak restarts, stop, take no action on it, and tell me.
- Never run a kind cluster during a CRC step. CRC has about 4 GiB of request headroom, and kind on the same Mac competes for it. Run kind before or after a CRC step, never during one.
- No secrets in git, logs, commands or output. TLS verification never off.
- If Claude Code refuses an action, the refusal stands: do not route around it or edit permission settings. Do everything else, and tell me the exact command at the end.
- Things only I can do: trust the two CAs in the keychain (LOCAL-DEV-TRUST.md), create the GitHub App, and make each GHCR package public. Build everything up to each one, then tell me exactly what to do and keep working on what does not depend on it.

## The database: CloudNativePG
The database is CloudNativePG, as decided and measured on kind, and docs/12's path for an existing PostgreSQL server stays as it is. Connect with TLS and verify the server (#91 is that work). Add no other database.

## When you finish, or must stop
Report in ten lines or fewer: what works and on which cluster (CRC or kind), what failed and is still open, with issue numbers, and exactly what I need to do next.
