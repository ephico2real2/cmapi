# The prompt for OB1's build-everything run

The owner's prompt, refined on 2026-11-13, for a run by OB1 (Fable 5.2). Paste everything below the line.

The owner, 2026-11-13: "change ob1 to use fable 5.2". That lifts the Fable pause for this run only. The session's model is set when it starts, not by this prompt, so start it pinned to the exact model id, and check that `/status` shows Fable 5.2 before pasting:

```bash
cd /Users/olasumbo/gitRepos/cmapi-design-crc && claude --model claude-fable-5-2
```

---

You are OB1 on cmapi, running on Fable 5.2. Build the whole application as designed, deploy it on CRC, test it, and fix every bug you find, in one continuous run.

## You have full autonomy
I give you full autonomy on cmapi for this run. You own it end to end: the records, the design documents, the code, the tests, the deployment on CRC and the final walk. Keep working without asking me. Align each choice with current industry best practice, and use web search freely to find it and to check it (the owner, 2026-11-13: "ob1 can google and it is fine"). Cite the sources you used in the repository. When you reach a point where you would ask, research it instead: search the web, read the primary sources, choose the industry best practice rather than the easy option, fix the cause rather than the symptom, then do it, and write the decision and its sources in the repository. The only limits are the rules that do not bend below, and the few steps that only I can take, which are listed there. I may be asleep, so never wait on me: the handover's "ask the owner" points are decided below.

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
Document each feature as it lands, in the same commit or pull request: what it does, how to run and use it, and what was measured, with the cluster each result came from (CRC or kind). Update the existing docs where a feature belongs to them (docs/01, docs/02, docs/13 and the guides) rather than adding new files. Add a new file only for something with no home yet, or one the owner asked for (docs/14 and docs/15, below). Never document a feature before it works: no design notes, plans or review write-ups ahead of the code. Keep HANDOVER-AND-RESUME.md and build-tracker.md current at each point where losing this session would lose work, so the run can resume.

## Records, language and diagrams
The owner asked for these on 2026-11-13. They apply to every issue, document and pull request in this run.
- **Agile records.** Read `/Users/olasumbo/gitRepos/diagram-kit/skill/agile/SKILL.md` and `LEGEND.md` in full and follow them. Each issue has a type label, one `status:` label, one work tag (`Backlog`, `In-Progress`, `Blocked`, `In-QA`, `Done`), a `sev:` label on each defect, its class after the class questions, and a sub-issue link to its parent with `Part of #N` as the first line. A defect's title starts with its ID: `BUG-08` is the next free number, and `SEC`, `PERF` and `UX` start at 01. The labels exist in cmapi from 2026-11-13. The repository is on a personal account, so it has no issue types, and the type label carries the type. Keep the progress labels true after each merge and each new pull request, as section 8 of the skill says.
- **Every open issue clearly defined.** The owner: "all issues open here ... must be clearly define". Sweep all open issues: give each the labels above, a parent link, and a body in the skill's form (`templates/bodies.md`) that says what is wrong or wanted, where, and how a test proves it. Do the class sweep of section 6, and put the class table of section 7 in `build-tracker.md`.
- **Simplified Technical English.** The owner asked for the `/simple` STE skill from diagram-kit. It does not exist there on 2026-11-13: not in `skill/`, not on any branch, not in an open pull request, and not on this Mac. If it appears in diagram-kit, load it and follow it. Until then, write every issue, document and pull request to the core rules of ASD-STE100 (Issue 9, January 2025): no more than 20 words in an instruction and 25 in a description; active voice; one instruction for each sentence; one topic for each paragraph, with no more than six sentences; no noun cluster of more than three words; each word in one meaning only. The official text was not reachable (asd-ste100.org answered 403). The rules above come from Wikipedia's article on Simplified Technical English, so check them against the standard if you can reach it.
- **Diagrams.** Draw them with diagram-kit's `/visual` skill (`skill/visual/SKILL.md`, rendered by `diagram-render`), in light and dark, into `docs/diagrams/`, as the existing figures are. Draw the overall architecture from the mockup (`mockups/portal/Main.dc.html`, read in full): each portal tab and action, the API endpoint it calls, the service and worker parts behind it, Keycloak, LDAP, PostgreSQL, Git and Argo CD. Use solid boxes for what is built and dashed boxes for what is not, per the legend.
- **Diagrams are required.** The owner, 2026-11-13: "also if is important that we have diagrams as well." Each new or changed document that explains a flow, a structure or a contract gets a diagram. Draw it with `/visual`, render it with `diagram-render` into `docs/diagrams/`, in light and dark. At least these: the overall architecture from the mockup; an authorization decision flow for `docs/14`; a Keycloak sign-in sequence to a permitted call for `docs/15` (a PKCE flow for the portal and for Swagger UI); an entity-relationship diagram of the service's PostgreSQL tables for the data-model document; and a request lifecycle from an API call to the Git pull request, the Argo CD sync and the resource, updated where `docs/diagrams/request-lifecycle.png` no longer matches the code. Use solid boxes for built parts and dashed boxes for unbuilt parts, per the figure elements in `LEGEND.md`. Each figure is an item in the definition of done of its document.

## Authorization, Keycloak, the data model and the API contract
The owner, 2026-11-13: "cmapi must define the groups contract but keycloak has the user and group role that is mapped to cmapi roles", and "the data model and api documentations should be refine and well documented, with sample payloads". Write these as new documents, since they have no single home yet. Each says only what the code does, with measured proof, and marks any part that is designed but not built.
- **`docs/14-authorization.md`, the authorization module.** cmapi owns the contract: the group names (`app-cmapi-rbac-<role>`, `docs/11` lines 32 to 45), each cmapi role, and each permission that a role grants. Give that mapping as one table, from `cmapi/src/cmapi/core/authz.py` and the realm's import. Say how a request is decided: the token, its claims, the role, the permission (`x-cmapi-permission`), the environment limit, self-approval, and each 401 and 403 with its problem code. Cite each claim with `file:line`.
- **`docs/15-keycloak-integration.md`, the Keycloak integration.** Keycloak holds the users and their group membership, from LDAP federation, and maps each group to a cmapi role. cmapi changes only realm `cmapi`. Say what cmapi creates in the realm: the clients (`cmapi`, `cmapi-docs`, the portal's), the mappers, the audience, the roles and the groups. Give the import, the claims of a real token with no secret in it, the PKCE flow of the portal and of Swagger UI, and token lifetimes. Add one sequence diagram from sign-in to a permitted call.
- **The data model and the API contract.** Document each table of the service and each API resource. For each endpoint, give a sample request and response payload, taken from a real run and not written by hand, and each error with its RFC 9457 body. Put the payloads in the OpenAPI examples too, so that Swagger UI, ReDoc and the docs show the same ones. `docs/04-api-examples.md` holds the current examples: make it match the code. Fix #127 to #134, the API-docs defects filed on 2026-11-13, as part of this.

## The build tracker of all issues and milestones
The owner, 2026-11-13: "keep a build tracker for all issues and milestones created in this repo". `scripts/issue-register.sh` writes `issue-register.md`, a table of every issue and milestone with its type, state, work tag, status, severity, class, parent and milestone. Run it again after each change to an issue or a milestone, and commit the result with that work. `build-tracker.md` links to it and gives its counts. The count "Open without exactly one work tag" must reach 0.
- Create one milestone per wave, `W1` to `W9`, with the wave's work from `build-tracker.md` as its description (`templates/milestone.md` of `/agile`). Give each a due date only when I give one: the skill says never to invent a date. Put each open issue in the one milestone that ships it.

## Definition of done, for each issue and each pull request
An item is done only when all of these hold. Check each one, and cite the evidence in the pull request and in the issue's `Done` comment.
1. **Defined.** The issue is in the `/agile` form: its labels, its parent, and acceptance criteria that each say which test proves them.
2. **Tested.** A defect has a test that fails before the fix and passes after it, both runs shown. A feature has a test for each criterion. Every suite in `CLAUDE.md`'s "Tests" table that the change touches passes on your machine.
3. **Real.** No stub, placeholder, mock data or skipped test stands in for the work. A gap is filed as an issue, not hidden.
4. **Documented.** The docs change in the same pull request, written in Simplified Technical English, with real sample payloads where an API changes. Each route passes `check_documented`, and Swagger UI and ReDoc show it.
5. **Reviewed where the rule asks.** A change to auth, tokens, admission, secrets or deletion has its second reader, with each finding ruled on by a test.
6. **Proven where it runs.** Kubernetes behaviour on a `cmapi-*` kind cluster, and OpenShift behaviour on CRC, each result naming its cluster. A visible change has a screenshot through its Route.
7. **Safe.** No secret in git, logs or commands, TLS verification on, and the shared-services rules kept.
8. **Green.** CI passes on the exact head commit, read after the run finished.
9. **Recorded.** The pull request starts with `Closes #N` or `Part of #N`, names its milestone, and says that Fable 5.2 wrote it. The issue has `Done` with its evidence comment, `issue-register.md` is regenerated, and `build-tracker.md` and `HANDOVER-AND-RESUME.md` say the new state.
10. **Merged** to `main` only when items 1 to 9 hold.

## What "done" means
1. Every feature in docs/01 and docs/02 is implemented: the service API, the worker jobs, the cmapi CLI and cmapi-sdk, and the admin portal.
2. The admin portal shows everything the mockup shows, with the same tabs, data, states and actions, on the real API (not mock data). I like our mockup: keep it faithful, and change its look only where PatternFly replaces it. It uses React, TypeScript, Vite and PatternFly, per the mockup-to-page-react skill. Sign-in goes through Keycloak with OIDC and PKCE, in realm cmapi, and each role sees only what docs/02 allows.
3. **The full API, with Swagger UI and ReDoc on it.** Every endpoint in docs/01 and docs/02 is built, and every one is documented, as docs/01's section "API documentation: Swagger UI and ReDoc" specifies: `/docs` (Swagger UI, with Try it out signing in through Keycloak with PKCE), `/redoc` (grouped by x-tagGroups, with a curl sample per operation), `/openapi.json` and `/openapi.yaml` (OpenAPI 3.1, with an ETag), `/docs/changelog`, and the DocumentedRouter in `core/docs.py` that refuses to start a route that is not fully described, with a CI check that refuses a spec that breaks v1. Both UIs are served from the bundles in the image, never a CDN. Fix #127 (the fallback loads a different ReDoc major than the image) as part of this. For the standard of the descriptions, read the owner's earlier work in `ephico2real2/group-sync-dashboard` at commit `d6827c5314d7`, file `local-development/gsd/api.py`: `create_app` (the app description, assets bundled in the image with a logged CDN fallback, the `/api/docs` redirect) and the endpoint `Query(description=...)` texts, which say what a limit truncates and what `total` counts. It is a reference to read, not code to copy and not a project to change. Where it and docs/01 differ (it puts its docs behind sign-in at `/api`; cmapi's are public at `/docs` and `/redoc`), docs/01 wins. Prove it on CRC with a screenshot of `/docs` and `/redoc` through the Route, and one Try it out call that succeeds with a real token.
4. It runs on CRC (OpenShift Local) for real testing, with the OpenShift-specific parts proven there: Routes, SCCs (restricted-v2), the internal registry, OVN-Kubernetes network policies, and user workload monitoring.
5. Kubernetes behaviour is proven on kind clusters too (named cmapi-*, KIND_EXPERIMENTAL_PROVIDER=podman, explicit --kubeconfig): cmapi creates and deletes real namespaces, quotas, limit ranges and role bindings on them.
6. One end-to-end walk from a clean start, on CRC: an admin, a non-admin and the CLI each complete a request through to a real resource, with browser screenshots of the portal through its Route.
7. All test suites and CI are green on the final commit.
8. The docs match what was built: every feature and every setup step in them is real and tested, and an operator can deploy cmapi on CRC from a clean start using only the docs.

## How to work
- Build, test and fix in one loop. The owner, 2026-11-13: "all bugs must be file as issues and fixed immeditealy". When a test, a run, CI or a reading shows a bug, file it at once, then fix its cause in the same run, with a test that fails before the fix and passes after, and keep going. File each issue in the `/agile` format (see "Records, language and diagrams").
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

## Local CI is the merge gate

The owner, 2026-11-13: "use local ci for all work and forget the githiub", and "tell ob1 to use this going forward". From that point OB1 uses local CI for all work, not GitHub Actions, and does not wait for a GitHub run.
- Read `~/.claude/skills/setup-local-ci/SKILL.md` and `~/.claude/skills/local-ci-web/SKILL.md` in full first. The script is `ci/local/act-ci.sh` (from the coordinator's branch `local-ci`), or `~/.claude/skills/setup-local-ci/act-ci.sh` until that merges. The runner image is `act-runner:ubuntu-24.04`, built for `linux/amd64`.
- Run each job of `.github/workflows/ci.yml` in a clone with no remote, in a folder with the name of the repository, with `-b <base commit of the pull request>` and `-o <a log folder for that run>`. Never run a bare `act`.
- Do not start a kind cluster or touch CRC from these runs. Do not remove the `act-*` containers of a run that you did not start.
- The merge gate: each job exits 0 on the exact head commit. The pull request says that the gate was local CI, with the commit, the result of each job, and the differences from a GitHub run (the skill's section 6).
- The viewer is `http://127.0.0.1:2026/`. The coordinator starts it. Do not stop it.
- If a local job fails for an act or Podman reason, match it to the skill's gotcha table, and file it as a defect.
- The `manifests` job is not run locally. act-ci.sh passes `--container-daemon-socket -` (G1), and the job needs a container engine and a kind cluster. A kind run killed `keycloak-0` on the shared CRC at 08:58:42Z (#157), so no kind runs on this Mac until #157 is decided. The local gate is the other five jobs. A pull request that changes `deploy/`, the `Containerfile` or the manifests job waits for the `manifests` proof.
- Branch protection on `main` still requires the GitHub checks. The coordinator does not change it; that is the owner's choice. So a merge also waits for GitHub's required checks, but OB1 does not sit idle on them: it works on the next item.
- Before and after each local run, read `keycloak-0`'s restart count. If it rises, stop local CI and add the measurement to #157.
- The records (`HANDOVER-AND-RESUME.md`, `build-tracker.md`, `issue-register.md`) belong to the coordinator. OB1 may make a short edit to them when it costs little time. At the end of each task, OB1 sends the coordinator what it did, what is still needed and any blocker. OB1 files its own issues.

## The database: CloudNativePG
The database is CloudNativePG, as decided and measured on kind, and docs/12's path for an existing PostgreSQL server stays as it is. Connect with TLS and verify the server (#91 is that work). Add no other database.

**No Redis and no Valkey.** The owner, 2026-11-13: "we can use postgress for cache as well if needed so we don't have to use redis or vakkey". The coordinator measured that no document, manifest or dependency names either today. The caches that the design names (the Kubernetes watch cache, Keycloak's own user cache) are in-process or belong to Keycloak. If a cache must be shared across replicas (for example a rate-limit counter, idempotency records, a JWKS copy or a capacity snapshot), use the PostgreSQL that cmapi already has: a migration, a TTL or expiry column, a sweep, and LISTEN/NOTIFY if replicas must invalidate. Research the current best practice first (for example UNLOGGED tables and their truncation after a crash), and record the decision and its sources in the repository. Add nothing for a cache that you do not need.

**The reference for that cache: kvpg.** The owner, 2026-11-13: "check my inkcaskhq/kvpg". The repository is `github.com/inkcasthq/kvpg` (inkcasthq, not inkcaskhq). The coordinator read it at commit `f654a121820f`. It is a key-value cache in PostgreSQL for Node.js, Apache-2.0, by the owner. It has a written cache contract v1 (`docs/standard.md`, rules S1 to S14), JSON Schema payloads with samples for 15 operations (`contracts/`), and the table, the SQL and choices D1 to D10 with sources (`docs/design.md`). Its README says "Do not use kvpg in production before release 1.0". Its issues #1, #2 (the store) and #3 (the conformance suite) are open, and it has no tag or release. The coordinator's decision under the owner's mandate: kvpg is the reference for cmapi's cache, not a dependency, because cmapi's service is Python and cannot import a Node.js library. If cmapi needs a cache shared across replicas:
- Build a small Python store in cmapi that keeps kvpg's contract v1 (S1 to S14) and follows its design. Use the table of `docs/design.md`: `key text COLLATE "C"` primary key, `value`, `expires_at timestamptz NOT NULL DEFAULT 'infinity'`, fillfactor 70, `autovacuum_vacuum_scale_factor` 0.01. Expiry uses the database's `now()` (D7). Cleanup is batched with `FOR UPDATE SKIP LOCKED` and the outer `expires_at` check (D8). A prefix is deleted by range (D10). Create the table through cmapi's own migrations (D9: `schemaSql()` is the model).
- Use a logged table, not UNLOGGED. kvpg's D5 says an unlogged table is emptied after a crash and has no rows on a replica, and CloudNativePG runs replicas.
- Test each rule S1 to S14 and each edge in the "Conformance" section of `standard.md` with pytest against the service test database. Each test fails before and passes after. Validate cmapi's payloads against kvpg's `contracts/*.schema.json` and samples where the shapes are the same.
- Cite kvpg at `f654a121820f` in the decision record, and say which of its choices are still "to measure" there (D1, D5 and D6, kvpg issue #7).
- kvpg is the owner's other project: read it, never change it, and file nothing there. Write a defect in kvpg's contract in `recommendations.md` for the owner.
- Add nothing if cmapi needs no shared cache. Record that decision too.

**Build the store, or use a public library.** The owner, 2026-11-13: "ob1 is free the python equiavlanet to add a similar or use an existing public one as well". So, if cmapi needs a shared cache, OB1 can build the small Python store above, or use an existing public Python library that caches in PostgreSQL. Choose by research, and record the choice and its sources here and in `HANDOVER-AND-RESUME.md`. A library must meet all of these, each verified from its source code and documents, not its README alone:
- It is maintained, with a release in the last 12 months and an OSI licence compatible with Apache-2.0.
- It works with cmapi's stack (Python 3.12, the database driver and the SQLAlchemy version that cmapi uses) and with PostgreSQL 16 under CloudNativePG.
- The database clock decides expiry, or a documented reason says why client time is safe here.
- It uses a logged table, created through cmapi's own migrations and not at import time.
- Its connection uses TLS with server verification (#91), and it has no option of its own that turns that off.
- It has a version pin with a hash, as cmapi pins its other dependencies.

Measure the library against kvpg's contract v1 rules (S1 to S14) and its conformance edges with pytest, as for a store of cmapi's own. A rule that it breaks is a defect against that choice, not a reason to weaken the test. If no library passes, build the store. If cmapi needs no shared cache, add neither, and record that.

## When you finish, or must stop
Report in ten lines or fewer: what works and on which cluster (CRC or kind), what failed and is still open, with issue numbers, and exactly what I need to do next.
