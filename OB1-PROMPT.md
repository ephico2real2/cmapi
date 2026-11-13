# The prompt for OB1's build-everything run

The owner's prompt, refined on 2026-11-13, for a run by OB1 (Fable 5.2). Paste everything below the line.

---

You are OB1 on cmapi. Build the whole application as designed, deploy it on CRC, test it, and fix every bug you find, in one continuous run. Do not stop to ask me for anything you can find, build, test or decide yourself.

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
- This prompt replaces CLAUDE.md's delivery loop for this run: one design, no second-model design step, reviews only where named above. Every other rule in CLAUDE.md still holds.

## Rules that do not bend
- CRC is shared. Never restart or stop the VM or a shared service (no crc stop, delete or config set). Do not touch the inkcast or corp realms, or group-sync. In Keycloak, change only realm cmapi, with no master admin credential. In LDAP, change only cmapi's own entries. Delete only what cmapi created.
- Before the first realm import, take the pg_dump of Keycloak's database that docs/13 describes. If Keycloak restarts, stop, take no action on it, and tell me.
- Never run a kind cluster during a CRC step. CRC has about 4 GiB of request headroom, and kind on the same Mac competes for it. Run kind before or after a CRC step, never during one.
- No secrets in git, logs, commands or output. TLS verification never off.
- If Claude Code refuses an action, the refusal stands: do not route around it or edit permission settings. Do everything else, and tell me the exact command at the end.
- Things only I can do: trust the two CAs in the keychain (LOCAL-DEV-TRUST.md), create the GitHub App, and make each GHCR package public. Build everything up to each one, then tell me exactly what to do and keep working on what does not depend on it.

## The database: CloudNativePG, and Supabase's Postgres as an option
Keep CloudNativePG as the default database: it is decided and measured on kind. You may also try Supabase's self-hosted Postgres (https://supabase.com/docs/guides/self-hosting, https://github.com/supabase/supabase), but only as an existing PostgreSQL server under docs/12's path, with TLS and verify-full. cmapi needs Postgres alone. Do not deploy Supabase's own auth, API gateway, storage or Studio: Keycloak is the identity provider, and a second one would split who signs in. Supabase documents self-hosting with Docker Compose, so check what running it on CRC would need, its SCCs and images, before you rely on it. If it does not fit within an hour of trying, stay on CloudNativePG and say why in one line.

## When you finish, or must stop
Report in ten lines or fewer: what works and on which cluster (CRC or kind), what failed and is still open, with issue numbers, and exactly what I need to do next.
