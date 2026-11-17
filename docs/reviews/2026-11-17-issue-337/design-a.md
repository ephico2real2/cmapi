# #337 design A: a report-only API contract diff in the cluster-configs CI

Designer A, Opus 5.5 at `high`, 2026-11-17, on `origin/main` 7ba5d78 (worktree `wt-337`). Every number below was measured
in the implementer's notes folder `ob-337/` (outside the repository) unless it cites a source.

## 1. What the issue asks, and what the code has today

- #337: when a pull request in a cluster-configs repository changes `metadata-keys.yaml`, render the instance's OpenAPI
  document before and after with `cmapi-tools`, run oasdiff, post a report, never fail the PR. Proof: a PR adding a
  required label shows the new required field; a PR not touching the file runs no report.
- `cmapi-tools` has `git-bootstrap`, `realm-sync`, `docs-assets`, `policies`. **No command renders the document.**
- The document is built in `main.create_app` (`build_openapi(app, plugins, public_url, problem_base, ctx.cfg.metadata)`),
  which needs a full `AppContext` from `build_context`. Measured: `build_context` with no database, Keycloak or cluster
  stops twice on things the document never reads: `clusters.yaml` missing (FileNotFoundError), then
  `PolicyEngineMissing: kyverno is not installed` (from `CliValidator`). So the CLI cannot go through `build_context`.
- What the document reads (read in `main.py`, `core/docs.py`, `core/auth.py`, `core/plugins.py`): `cfg.name`,
  `cfg.allowed_environments` (title, description), `instance.publicUrl` (servers, curl samples), `instance.auth.issuer`
  (the OAuth2 scheme's URLs), `instance.problems.typeBase`, `cfg.plugins.routers()` (which routes exist), `cfg.metadata`.
  Nothing of tiers, approvals, roles, expiration, clusters, the DB, Git or Kyverno.
- Measured feasibility: with the validator stubbed (the probe, `ob-337/probe.py`), `create_app(...).openapi()` on the
  service suite's test configuration is **byte-identical** to the committed `cmapi/contract/openapi.json` (`cmp`: equal).
- The cluster-configs template (`examples/cluster-configs/.github/`) installs no cmapi today; its two jobs are the check
  runs the worker waits for (`pr_checks.CI_CONTEXTS = [ci/kubeconform, ci/kyverno]`). The worker reads only those two names
  (`pr_checks.py:67`), so a third job never holds a bot PR.
- The live repository `ephico2real2/cmapi-cluster-configs` (private) has `policies/metadata-keys.yaml` and one `ci.yml`.
- No cmapi image on GHCR: `https://ghcr.io/token?scope=repository:ephico2real2/cmapi:pull` answers `DENIED` (measured).

## 2. The generator: `cmapi-tools openapi render`

1. **Refactor, behaviour-preserving.** Move the document-shaping half of `create_app` into one function in `main.py`,
   `api_app(cfg, lifespan=None) -> tuple[FastAPI, dict[str, DocumentedRouter]]`: the `FastAPI(...)` construction (title,
   version, description, `openapi_url=None`, ...), the router inclusion with the `authed` dependency built from
   `cfg.raw_instance` `auth.issuer`, `check_documented`, `_add_servers` (reads `cfg` only), `plugin_routers`, and an
   `openapi` closure over `build_openapi(...)`. `create_app` calls it, then adds what is runtime only (middleware, handlers,
   `app.state.ctx/auth`, problem pages, docs routes). `openapi_document(cfg) -> dict` = `api_app(cfg)[0].openapi()`.
   One code path for served and rendered, so they cannot drift.
2. **The command.** `cmapi-tools openapi render --metadata-keys FILE [--config-dir DIR] --out FILE`, writing
   `json.dumps(doc, indent=2, sort_keys=True) + "\n"` (the committed contract's exact bytes). With `--config-dir`, the
   instance is `load_instance(DIR, FILE)`: the document that instance serves. Without it, a **neutral instance** built in
   code (`name: report`, issuer `https://issuer.invalid/realms/report` (RFC 2606 `.invalid`), every built-in plugin, no
   `publicUrl`), so the labels and annotations part is exactly the file's and the rest is labelled as not this site's.
   Reason: a cluster-configs repository holds `metadata-keys.yaml` but not the instance files (instance.yaml lives in
   the Helm values or `20-config.yaml`), and in a base-vs-head diff every non-metadata part is equal on both sides, so it
   cancels out. A site that keeps its instance files in the repository sets `--config-dir` and gets its own document.
   `--metadata-keys` alone is loaded with `MetadataKeys.load`, so the loader's own refusal (#332, #338) is the message.
3. Registered in `tools/__init__.py` `COMMANDS` as `"openapi": "cmapi.tools.openapi"`; lazy import as for the others.

## 3. The report: where it runs and what it prints

**A separate workflow file**, `examples/cluster-configs/.github/workflows/contract-report.yml`:

```yaml
on:
  pull_request:
    branches: [main]
    paths: [policies/metadata-keys.yaml]
permissions:
  contents: read
jobs:
  report:
    name: report/api-contract          # not ci/*: the worker never waits for it
```

- **Why a workflow-level `paths` filter, in its own file.** It is the native trigger filter: the workflow does not start
  when the file is untouched, which is the issue's "runs no report". A `paths` filter on `ci.yml` would also skip the two
  required checks. GitHub: for a PR the filter uses a three-dot diff; it may miss a match only when the diff has more than
  3,000 files; a skipped workflow's checks stay "Pending" and block a PR only if they are **required** (workflow syntax,
  `on.<push|pull_request>.paths`). So the doc says: never make `report/api-contract` a required check.
- **`pull_request`, never `pull_request_target`.** GitHub: fork PRs get a read-only `GITHUB_TOKEN` and no secrets under
  `pull_request`; `pull_request_target` "must not explicitly check out untrusted code" (secure use reference). The report
  needs the PR's file, so `pull_request` is the only safe trigger. No secret is used.
- **Base and head.** `actions/checkout` (same pin, `persist-credentials: false`, `fetch-depth: 2`) checks out
  `refs/pull/N/merge`; `GITHUB_SHA` is that merge commit (events reference). Base = `git show HEAD^1:policies/metadata-keys.yaml`
  (the base branch tip), head = the working tree (what the merge will make). Exactly the change that merging makes.
- **Where the report goes: the job summary plus one annotation, no PR comment.** `$GITHUB_STEP_SUMMARY` takes GitHub
  Markdown up to 1 MiB per step (workflow commands reference); it needs no write permission, so it works on fork PRs.
  One `::warning file=policies/metadata-keys.yaml::N breaking API changes (M required properties added); see the job
  summary` when oasdiff finds ERR or WARN, `::notice` otherwise, so it shows on the file in the PR's Files tab. A PR
  comment needs `pull-requests: write`, which fork PRs never get under `pull_request`; getting it means
  `pull_request_target` or a second `workflow_run` workflow (secure use: "privilege separation"), more surface for a report.
  Rejected; recorded as the upgrade path if the owner wants comments.
- **oasdiff output.** Two runs of oasdiff 1.37.0 (the version and SHA-256 `cmapi/.github/workflows/ci.yml` pins), both
  with `--allow-external-refs=false` (oasdiff `docs/EXTERNAL-REFS.md`: the SSRF mitigation for untrusted specs):
  `changelog -f markdown` for the summary (every level: a reader sees optional additions too), and `changelog -f json`
  to count levels (3 ERR, 2 WARN, 1 INFO) for the annotation. Never `--fail-on`, never `--open` (it uploads to oasdiff.com).
  Measured on base = reference file, head = + `requiredLabels: cmapi.net/data-class: {enum: [...], example: internal}`:

  ```
  ### POST /api/v1/clusters/{cluster_id}/namespaces
  - :warning: added the new required request property `labels/cmapi.net/data-class`
  -  added the new `cmapi.net/data-class` enum value to the request property `labels/propertyNames/anyOf[subschema #1]`
  ### PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}
  -  added the new optional request property `labels/anyOf[subschema #1]/cmapi.net/data-class`
  ```
  and `oasdiff breaking`: `1 error ... [new-required-request-property]`; exit 0 without `--fail-on`. Same file both
  sides: "No changes detected", exit 0.
- **Run oasdiff from an empty directory.** oasdiff reads `.oasdiff.{json,yaml,...}` from the working directory
  (`docs/CONFIG-FILES.md`). Measured: a planted `.oasdiff.yaml` with `fail-on: INFO` in the cwd turns the same run into
  exit 1. A PR could add one; the script runs oasdiff with `cwd=$RUNNER_TEMP/oasdiff` (empty), so it cannot.

## 4. Never fail the PR on a change; fail loudly when the tool breaks

The logic is a script beside `kyverno_check.py`, `examples/cluster-configs/.github/scripts/contract_report.py`
(standard library only), so it is tested as code, not as YAML:

| Case | Exit | Output |
|---|---|---|
| Any API change, breaking or not | 0 | Summary + `::warning` or `::notice` |
| No change (comment, reorder) | 0 | "No changes detected" in the summary |
| File added (no base) | 0 | `::notice`: no base document; the head document's required keys listed |
| File removed | 0 | `::warning`: no head document to compare |
| Head file does not load (the loader refuses it) | 1 | `::error file=policies/metadata-keys.yaml::` + the loader's problems: this file stops the instance at start |
| Base does not load, `cmapi-tools` missing or crashing, oasdiff missing or non-zero (measured: 102 on a broken document) | 1 | `::error::` naming the step and its stderr |

Exit 1 makes `report/api-contract` red, which is "loud"; it is not a required check, so the PR still merges. A change of
required keys never makes it red. `set -euo pipefail` in the workflow's shell steps; the script checks each subprocess.

## 5. Pinning

- **cmapi**: `pip install "cmapi @ git+https://github.com/ephico2real2/cmapi@<40-hex commit>#subdirectory=cmapi"`, with
  Python 3.12 via `actions/setup-python` (same pin). The repository is public (measured). The commit is the one env var
  `CMAPI_COMMIT` at the top, with a comment: set it to the `org.opencontainers.image.revision` of the image your instances
  run, so the report renders as they do. Once the image is on GHCR, `docker run ghcr.io/...cmapi@sha256:...` is the better
  form (the exact artifact); recorded as the follow-up, not built now (no image to pin).
  The template's value: the commit of this PR that adds the command (merges here keep commits: `Merge pull request #368`).
- **oasdiff**: v1.37.0 by URL and SHA-256 `eac87307...cbca3c`, the project's existing pin (latest is v1.38.0; a bump
  is its own change for both). **Actions**: by commit, as `ci.yml`.

## 6. Tests (each fails on 7ba5d78, passes after)

In `cmapi/tests/service/` (the `service` job installs cmapi; no database used by these):
1. `cmapi-tools openapi render --config-dir <test config> --metadata-keys <reference file>` writes bytes equal to
   `contract/openapi.json`. With the existing committed-contract test, rendered == served.
2. `contract_report.py` on base = reference file, head = + a required label: exit 0, the summary holds
   ``added the new required request property `labels/cmapi.net/data-class` `` and a `::warning file=policies/metadata-keys.yaml`.
3. Same file both sides: exit 0, "No changes detected", `::notice`.
4. Broken tool: `CMAPI_TOOLS` pointing at a stub that exits 2, and an oasdiff stub that exits 102: each exit 1 with
   `::error`. Head file the loader refuses: exit 1, `::error file=policies/metadata-keys.yaml`.
5. A `.oasdiff.yaml` with `fail-on: INFO` in the caller's cwd: still exit 0.
6. Workflow structure (`tests/core/test_config_repo_ci.py`, extended): the new workflow is `pull_request` only (no
   `pull_request_target` in any template workflow), `paths == ["policies/metadata-keys.yaml"]`, `permissions ==
   {contents: read}`, job name not in `CI_CONTEXTS`, no `--fail-on`/`--open` in it, oasdiff version and SHA-256 equal to
   `.github/workflows/ci.yml`'s, `CMAPI_COMMIT` 40 hex, actions by commit. The existing names test keeps `ci.yml` exact.

Oasdiff tests skip with no `oasdiff` on PATH; `CMAPI_REQUIRE_OASDIFF=1` in the `service` job fails instead, which gets
the same pinned oasdiff step as `api-contract`.

**Live proof (needs the coordinator's ruling).** Two throwaway PRs in `ephico2real2/cmapi-cluster-configs`, each adding
the workflow: (a) + a required label: screenshot of the job summary; (b) + a README line: no `report/api-contract` run.
Both closed unmerged, branches deleted. The CRC worker only follows its own bot PRs (`hostChecks: false`), so neither
touches CRC. Alternative: a fresh private scratch repository.

## 7. Docs

`docs/18-configuration.md`, under the generated-clients paragraph: the report, how to read it, `CMAPI_COMMIT`, "never
required". `examples/README.md` rows for the workflow and the script. `cmapi/contract/README.md`: the gate sees the
reference file; site files get the report. `tools/__init__.py` docstring.

## 8. For the coordinator to rule

1. Neutral instance when `--config-dir` is absent (A's choice) vs requiring the instance files in the repository.
2. Job summary + annotation (A) vs a PR comment via a second `workflow_run` workflow.
3. Where the live proof runs (section 6).
4. The template's `CMAPI_COMMIT`: this PR's commit (A) vs a placeholder that fails loudly until a site sets it.
