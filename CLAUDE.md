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
3. Fable builds it, and every line is read.
4. A functional test on the running environment, its output saved, and a screenshot for a visible change.
5. An adversarial review (`adversarial-review`) by two model families, each returning the full fix and its test, and each
   reviewer's fixes cross-checked by the other. Never the author.
6. The docs, the testing record and the diagrams updated from measured numbers.
7. Merged only when CI is green and the review passed.

The end-to-end walk on CRC is the gate on calling the whole done. Run it from a clean start, using only the guide. Each
deployment step takes screenshots of the working app through its Route in Chrome, and they go in the PR.

### Who does what

The owner's decision, on 2026-11-05:

| Role | Who | Does |
|---|---|---|
| Implementer | Fable | Writes all code, tests and charts. The only one who changes application code |
| Reviewers | Opus and Codex | Design each step independently, review the code, and generate the fix and test for each finding. Each cross-checks the other's fixes |
| Coordinator | The main session | Writes the briefs, re-checks every verdict, arbitrates, records decisions, merges. Writes no application code |

A reviewer's fix is a proposal. Fable applies it only after the coordinator has accepted it. Fable may reject one with a written
reason, and the coordinator decides.

Reviewers work on an export, never in a repository. If Fable is out of quota, stop coding and report it. Do not hand the code to
another model.

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

`PW_CHANNEL=chrome` runs the browser suites in the installed Chrome. `docs/09-portal-ui-testing.md` records the method.

Commit messages and pull requests carry no `Co-Authored-By` or "Generated with" lines.
