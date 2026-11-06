# Working on cmapi

## The owner's standing mandate

The owner has given full autonomy on this project. Keep working without asking.

When you reach a point where you would ask, research it instead:

1. Search the web for the options, and read the primary sources.
2. Choose the industry best practice, not the easy solution. Fix the cause, not the symptom.
3. Do it, write the decision and its sources in the repository, and say so in your report.

Every bug gets a GitHub issue. Refine it until it says what is wrong, where, and how to prove it. Then fix it, with a test
that fails before the fix and passes after, and close the issue from the pull request.

## How to build: the delivery loop

The owner's required way of working, from `app-architect`, "Delivering the fixes". Every step goes through it:

1. One issue, one branch from `main`, and one pull request whose body starts `Closes #N`.
2. Two independent designs from two model families, arbitrated into one, with the choice recorded in the PR.
3. The implementer builds it (see "Who does what"), and every line is read.
4. A functional test on the running environment, its output saved, and a screenshot for a visible change.
5. An adversarial review (`adversarial-review`): reviewer 1, then reviewer 2 checking reviewer 1's code, each returning the
   full code of the fix and its test (see "Who does what"). Never the author.
6. The docs, the testing record and the diagrams updated from measured numbers.
7. Merged only when CI is green and the review passed.

The end-to-end walk on CRC is the gate on calling the whole done. Run it from a clean start, using only the guide. Each
deployment step takes screenshots of the working app through its Route in Chrome, and they go in the PR.

### Who does what

The owner's decision, on 2026-11-05:

| Role | Who | Does |
|---|---|---|
| Implementer | Opus 5.5 at `high` | Writes the code, tests and manifests of a step |
| Reviewer 1 | Codex, with read and write access to its export | Designs each step independently, reviews the code, and returns the full code of the fix and test for each finding |
| Reviewer 2 | A separate Opus 5.5 agent at `high` that did not write the step | Checks each of reviewer 1's snippets against the design and the code and updates it, and reports with full code what reviewer 1 missed |
| Coordinator | The main session | Writes the briefs, re-checks every verdict, arbitrates, records decisions, merges. Applies reviewer 2's resulting fixes narrowly. Authors no application code |

The owner, 2026-11-05: "Let us stop using fable for now", then "Use opus 5.5 high". So Fable is paused until the owner says
otherwise, and Opus 5.5 at `high` writes the code. Every pull request says who wrote what (which model wrote which commits or
files). The agent that codes a step does not review it. With Fable paused, Codex is the only outside model family, so the pull
request says the step had one. A second Opus agent reviewing is not independent in the same way.

The owner, 2026-11-05: "each reviwer must produce the full code snippet", and "reviewer 2 will review reviewer 1 code snippet and
update rooted in the design logic and code so that Coordinator can surgically apply the resultant code fix", and "reviewer 2 also
reports what codex missed". A finding without its full code does not count. A fix that does not fit when applied goes back to
reviewer 2; the coordinator does not rewrite it.

A reviewer's fix is a proposal. The coordinator applies it only after accepting it. Where the question is whether a fix or finding
is right, a test decides: the failing test stands unless it is shown to be wrong. A finding with a failing test is never dismissed
by opinion, and the coordinator keeps the final call and records it.

Reviewers work on an export, never in a repository. Codex's read and write access covers its export, so it can write and run its
fixes and tests there.

**Stories.** A pull request that delivers part of a story (#13 to #29) says `Part of #N`. A story closes after the owner approves,
with a comment citing the proof for each acceptance criterion and the cluster it ran on. Paperclip is off for now (#6, #93).

To continue the build from a new session, start with [`HANDOVER-AND-RESUME.md`](HANDOVER-AND-RESUME.md) and
[`build-tracker.md`](build-tracker.md).

### What the mandate does not change

- **Report faithfully.** Say what was measured, what was inferred and what was not tested.
- **A permission refusal stands.** If Claude Code refuses an action, do not route around it, and do not edit permission
  settings to get past it. File an issue with the exact command, do everything else, and put the command in your report.
- **Other projects' work stays theirs.** See "Shared services". The mandate covers cmapi, and it does not reach `inkcast`,
  `corp`, group-sync or anything else on this cluster.
- **No secrets** in git, logs, reports or command lines.

## Design comes from the file

Read the actual file in full before writing from it: never memory or truncated output. `mockups/portal/Main.dc.html` is the
source for the portal mockup, and `docs/01` and `docs/02` are the source for the design. Both docs export live Claude Docs.
Edit the live docs first when those tools are available, then the exports.

## Shared services on CRC

cmapi uses an existing Keycloak and an existing LDAP server, and installs neither.
[`docs/11-existing-identity-services.md`](docs/11-existing-identity-services.md) says what cmapi adds to each. Change only
those things. Never restart the VM or a shared service, and do not delete anything you did not create.

Test on a `cmapi-test` kind cluster as often as you like (`KIND_EXPERIMENTAL_PROVIDER=podman`). CRC is the deployment target,
so the final proof runs there. Say which cluster each result came from.

## Skills

These live in `/Users/olasumbo/gitRepos/diagram-kit/skill/`. Read the one that applies before starting.

| Skill | Use it for |
|---|---|
| `app-architect` | The design standard: inventories, twelve factors, observability, security, delivery, scaling |
| `mockup-to-page-react` | The portal, from the mockup to React, TypeScript, Vite and PatternFly |
| `test-ui` | Proving a UI: DOM and pixels against the reference, recorded walks, mutants, the installed browser |
| `adversarial-review` | Before a change is called ready: two reviewers from other model families, never the author |

## Tests

| Area | Command |
|---|---|
| Portal mockup | In `tests/portal/`: `npm install`, `npx playwright install chromium`, `npm test` |
| React app | In `cmapi-portal-ui/`: `npm install`, `npm test` |
| Reference code | In `examples/`: `PYTHONPATH=src python -m pytest tests -q`, with `local/requirements.txt` installed |
| Service | In `cmapi/`: `PYTHONPATH=src:tests/service python -m pytest tests/service -q -W ignore`, against a PostgreSQL 16 on `127.0.0.1:55432` |
| Plain manifests | `deploy/kind-test.sh <image>` on a `cmapi-test` kind cluster (CNPG 1.30.1, `/readyz`, `/api/v1/version`, the secrets cases); `deploy/secrets-test.sh` alone on any throwaway cluster |

`PW_CHANNEL=chrome` runs the browser suites in the installed Chrome. `docs/09-portal-ui-testing.md` records the method.

Commit messages and pull requests carry no `Co-Authored-By` or "Generated with" lines.
