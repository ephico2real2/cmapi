# #337 design B (OB3, Opus 5.5): a report-only API contract diff in cluster-configs CI

Design only, read on origin/main 7ba5d78. *Measured* = run on a since-deleted scratch clone of 7ba5d78 with oasdiff 1.37.0 (main CI's pin).

## 1. What I found first (it changes the design)

1. **cluster-configs holds no instance config.** `examples/cluster-configs/` has `policies/metadata-keys.yaml`, but no
   `instance.yaml`, `tiers.yaml` or `plugins.yaml`. The full document comes from `create_app` → `build_openapi(app,
   plugins, public_url, problem_base, ctx.cfg.metadata)` (`main.py:176-181`, `core/docs.py:356`), and that call needs an
   instance config. So CI can't build "the instance's" document from this repository alone.
2. **`build_context` is the wrong layer for an offline tool** (*measured*). I socket-blocked
   `create_app(s, build_context(s, start_registry=False))` with `examples/instances/nonprod` and the reference keys. It
   failed with `PolicyEngineMissing: kyverno is not installed, and the environments ['dev', 'rnd'] run Kyverno`
   (`core/validate/__init__.py:76`). After I set `policy.engine: none`, it built a 508,205-byte document, with no
   socket opened and no DB or secret. The document needs config only; the context also brings up the DB, validator,
   Git and IdP.
3. **The instance does not read this file at run time.** `Settings.metadata_keys_path` defaults to
   `<config_dir>/metadata-keys.yaml`, which is the ConfigMap that the Helm values fill (#335).
   `git_bootstrap._policies` *copies* the file into `cluster-configs/policies/` (`git_bootstrap.py:121-130`). docs/02
   §1005 calls the cluster-configs file the one source, and on main that holds only by convention. The report has to
   say this. A follow-up issue (§8) closes the gap.

## 2. Building the document offline: `cmapi-tools openapi`

Add a fifth command to `cmapi/src/cmapi/tools/__init__.py` `COMMANDS`, following the `policies` pattern:

    cmapi-tools openapi --metadata-keys FILE [--config-dir DIR] --out FILE

- **One generation path.** Split the document assembly out of `create_app` into
  `cmapi.main.openapi_app(cfg: InstanceConfig) -> FastAPI`. It needs only `load_instance()` output: the title,
  `oauth2_scheme(issuer)`, the routers of `cfg.plugins.routers()`, `_add_servers`, `problem_base` and `cfg.metadata`.
  `create_app` calls it, and the tool calls it. The served document and CI's document can't drift, because there is
  one function.
- **No context.** No `build_context`, `Database`, `Jwks`, registry, Kyverno or Git, so no network and no secrets.
- **`--config-dir` is optional.** Without it, the tool uses the reference instance that ships as package data
  (`cmapi/tools/reference-instance/`, the files the service suite's `test_config` uses). Base and head are rendered
  with the same instance files, so **every difference in the report comes from `metadata-keys.yaml`**.
  `build_openapi` already routes the keys through `_document_metadata`, the recorded examples,
  `_document_metadata_keys_example` and the curl samples. Limitation, shown in the report header: an instance that
  disables the namespaces plugin does not serve the paths shown.
- **Exit codes, so CI can tell a refused config from a broken tool:**
  - 0: written.
  - 3: the loader refused the config. The `MetadataKeys` or `load_instance` message goes to stderr.
  - Anything else: the tool broke.
- **A self-check before writing.** The output has `openapi: 3.1.*`, and has
  `paths["/api/v1/clusters/{cluster_id}/namespaces"].post`. A tool that silently renders an empty document fails this
  check, where it would otherwise report "No changes".

## 3. Which oasdiff output (measured on 1.37.0)

I added `cmapi.net/cost-owner: {pattern: "^[a-z]{2,20}$", example: finance}` to `requiredLabels`, rendered base and
head, and ran:

| Command | Output | rc |
|---|---|---|
| `oasdiff breaking base.json head.json` | `error [new-required-request-property] … POST /api/v1/clusters/{cluster_id}/namespaces … added the new required request property \`labels/cmapi.net/cost-owner\`` | 0 |
| `oasdiff changelog -f markdown base.json head.json` | `## API Changes`, `### POST …namespaces`, `- :warning: added the new required request property \`labels/cmapi.net/cost-owner\``, plus the propertyNames enum line, and the PATCH optional property and enum lines | 0 |
| `oasdiff changelog base.json base.json` | `No changes detected` | 0 |
| `oasdiff changelog base.json nope.json` | (load error) | **102** |

**Choice: `changelog -f markdown` is the body of the report.** It is a superset of `breaking`: the breaking lines
carry `:warning:`, and the optional and additive changes are listed too. An operator adding an optional key also
wants to see it. **`breaking -f singleline` gives the headline count** ("N breaking"). Both run without `--fail-on`,
so oasdiff's exit code reflects only whether the tool worked (measured: rc 0 with 1 error, rc 102 on a load failure).
The `## Info` line ("a breaking change was detected but the version is still 0.2.0") is expected: both sides are one
cmapi version. The report explains it in one sentence and doesn't filter it out.

## 4. Where the report goes: the job summary, plus an artifact. Not a PR comment

- **Job summary (`$GITHUB_STEP_SUMMARY`)** needs no token permission. It shows on the run summary page and the PR's
  check details. The limit is 1 MiB per step, and at most 20 step summaries are shown per job (GitHub, workflow
  commands). The markdown changelog of my measured case is a few hundred bytes. If the summary would pass 900 KiB,
  it is cut with a pointer to the artifact.
- **Artifact** (`actions/upload-artifact`, pinned by SHA) holds `base.json`, `head.json`, `changelog.md`,
  `breaking.txt` and `versions.txt` (cmapi image digest, oasdiff version, the two config SHAs). Anyone can re-run the
  diff locally from it.
- **One `::warning title=API contract::N breaking changes, see the job summary` line** when N > 0. It is an
  annotation and does not fail the step.
- **Why not a PR comment.** A comment needs a token that can write to PRs. Under `pull_request` from a fork,
  "The `GITHUB_TOKEN` has read-only permissions" (GitHub, events that trigger workflows). The comment would fail on
  every fork PR. Getting write access means `pull_request_target`, which §6 rules out. A summary works the same for
  every PR at `contents: read`. A comment could later come from a separate `workflow_run` workflow that reads the
  artifact as data only. That is out of scope and listed in §8.

## 5. The workflow: `examples/cluster-configs/.github/workflows/api-contract-report.yml`

It is a separate workflow, not a job in `ci.yml`, for three reasons:
- `paths` is a workflow-level filter.
- `ci.yml`'s job names are a contract: cmapi's worker waits for `ci/kubeconform` and `ci/kyverno` (`ci.yml:1-5`,
  `pr_checks.py`).
- This check must **never be required**. GitHub: when a workflow is skipped by path filtering, "checks associated
  with that workflow will remain in a 'Pending' state. A pull request that requires those checks … will be blocked."
  The docs/18 setup step and `git-bootstrap`'s branch protection must not list `ci/api-contract-report`, and a test
  asserts that.

```yaml
name: api-contract-report
on:
  pull_request:
    branches: [main]
    paths: [policies/metadata-keys.yaml]
permissions:
  contents: read
concurrency: {group: api-contract-report-${{ github.event.pull_request.number }}, cancel-in-progress: true}
jobs:
  report:
    name: ci/api-contract-report
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    env:
      CMAPI_IMAGE: ghcr.io/ephico2real2/cmapi@sha256:<digest of the cmapi release the instances run>
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: {fetch-depth: 2, persist-credentials: false}   # the merge commit and its first parent, the base tip
      - name: oasdiff v1.37.0
        run: |   # the same tarball and SHA-256 as cmapi's own api-contract job
          curl -fsSL -o oasdiff.tar.gz https://github.com/oasdiff/oasdiff/releases/download/v1.37.0/oasdiff_1.37.0_linux_amd64.tar.gz
          echo "eac87307d31d08c36800c58a409c247f1c5db37fbb72e2544402f22a87cbca3c  oasdiff.tar.gz" | sha256sum -c -
          tar xzf oasdiff.tar.gz oasdiff && sudo mv oasdiff /usr/local/bin/ && oasdiff --version
      - name: Render base and head, report, never gate
        run: .github/scripts/api_contract_report.sh   # §5.1; reads only env and files, no ${{ }} in shell
      - uses: actions/upload-artifact@<SHA of its release tag> # vX.Y.Z
        if: always()
        with: {name: api-contract-report, path: report/, if-no-files-found: error}
```

### 5.1 `api_contract_report.sh` (`set -euo pipefail`)

1. **Base and head.** `HEAD` is GitHub's merge commit `refs/pull/N/merge`, and `HEAD^1` is the base tip it merged
   onto (GitHub: `GITHUB_SHA` "is the last merge commit"). So the diff is what main serves after the merge.
   - `git show HEAD^1:policies/metadata-keys.yaml > base.yaml`. If the base has no such file, the report says
     "no base document: this change adds the file". It then renders the head only and exits 0, mirroring
     `ci.yml:209-213` of cmapi.
   - `git show HEAD:policies/metadata-keys.yaml > head.yaml`. If the PR deletes the file, the report says so and the
     job **fails**, because no instance starts without it.
2. **Render each side** with `podman/docker run --rm --network none --read-only -v "$PWD/in:/in:ro"
   -v "$PWD/report:/out" "$CMAPI_IMAGE" cmapi-tools openapi --metadata-keys /in/<side>.yaml --out /out/<side>.json`.
   `--network none` enforces the "offline, no secrets" claim at run time; it isn't just stated. The job gets no
   secrets: none are referenced.
   - Base exits 3: report "base config is refused by this cmapi: no diff", then exit 0. The PR may be the fix.
   - Head exits 3: report the loader's message, then exit 1. The instance would refuse it at start.
   - Any other non-zero, a failed self-check, or oasdiff rc ≠ 0: exit 1 with "the report tool failed", which is red.
3. `oasdiff breaking -f singleline` → `breaking.txt` (count lines); `oasdiff changelog -f markdown` → `changelog.md`.
4. **Write the summary.** It has:
   - A header with the cmapi image digest and the oasdiff version.
   - The reference-instance caveat (§2).
   - The ConfigMap caveat (§1.3): "this file reaches an instance only through its Helm values `metadata:`".
   - `changelog.md`.
   - A closing line: "Report only: a required key is the operator's decision (#328 question 4). Generate clients from
     the instance's own `/openapi.json` (question 5)."
5. Exit 0 whatever the changes are. **The job is red only when the tool, the pin or the head config is broken. A
   breaking change never makes it red.** Because the check is not required, even red doesn't block a merge, and
   a reviewer reads red as "fix the CI or the config".

## 6. Fork safety

- **Trigger is `pull_request`, never `pull_request_target`.** GitHub Security Lab: `pull_request_target` "still has
  the read/write repository token in memory", and checking out the PR under it is "a dangerous practice". Under
  `pull_request` a fork gets a read-only token and no secrets, and this job needs neither.
- **What a fork controls.**
  - The YAML is parsed with `yaml.safe_load` in a `--network none`, read-only container. Patterns are checked by the
    loader's RE2-common-subset rule (#332), and RE2 runs in linear time. The worst case is CPU, which
    `timeout-minutes: 10` bounds.
  - **Residual risk:** under `pull_request` the workflow file itself comes from the merge commit, so a fork PR can
    edit the pins or the script and make its own report say anything. The report is advisory, so it needs no
    integrity guarantee. Code review of `.github/` changes is the control, plus GitHub's "require approval for fork
    workflows" setting. docs/18 says so.
- **No `${{ github.event.* }}` in `run:`.** It is a script-injection vector, and the script uses `git` on `HEAD`/`HEAD^1`.
- **GHCR access.** The image must be public, or `packages: read` must be granted to this repository. A private
  package with fork PRs can't be pulled with a read-only token. That is a precondition in docs/18. If the pull
  fails, the job goes red ("tool broke") rather than skipping silently.

## 7. Tests (each fails before, passes after)

| # | Where | Proves |
|---|---|---|
| T1 | `cmapi/tests/service/test_api_docs.py` | `cmapi-tools openapi --config-dir <test_config> --metadata-keys <reference>` is byte-equal to `contract/openapi.json`. This proves one generation path (fails today: no such command) |
| T2 | `cmapi/tests/core/test_tools_openapi.py` | Same render with `socket.socket.connect` patched to raise, `PATH` without `kyverno`, and `Settings` with no DB URL. It succeeds, which proves the §1.2 failure is gone. Exit 3 and the loader's message on an old-format file. The self-check exits non-zero on an empty `paths` |
| T3 | same | Base = reference, head = reference + `requiredLabels.cmapi.net/cost-owner`. `oasdiff breaking` lists `new-required-request-property` with `labels/cmapi.net/cost-owner`, and `changelog -f markdown` has the `:warning:` line. Both exit 0, matching my measurement in §3 |
| T4 | `cmapi/tests/test_cluster_configs_workflow.py` (static) | The workflow's `on` is exactly `pull_request` with `paths: [policies/metadata-keys.yaml]`. `permissions == {contents: read}`. No `pull_request_target`. Every `uses:` is `@<40 hex>`. oasdiff's version and SHA equal those in cmapi's `.github/workflows/ci.yml`. No `${{` inside `run:`. `ci.yml`'s two job names are unchanged. `git_bootstrap`'s branch-protection contexts don't contain `ci/api-contract-report` |
| T5 | `api_contract_report.sh` run locally (bash, against fixture commits in a temp git repo) | Fixture PR A adds a required label: the summary contains "added the new required request property \`labels/…\`", and rc 0. A PR deleting the file gives rc 1. A broken oasdiff (`OASDIFF=false`) gives rc 1 and "the report tool failed". A base with no file gives rc 0 and "no base document" |
| T6 | A real cluster-configs test repository on GitHub (`act` does not model `paths` faithfully; I did not measure this) | PR A (required label) gets a run, a green job and the summary line. PR B, touching only `clusters/…/namespace.yaml`, gets **no run**: `gh run list --workflow api-contract-report.yml --json headBranch` shows A's branch and not B's. Screenshot of A's summary in the PR |

The paths filter has one documented hole: "if the generated diff contains more than 3,000 files", a matching file
outside the first 3,000 does not trigger (GitHub, workflow syntax). I retract my first assumption of 300 files; the
docs say 3,000. A cluster-configs PR that size is not a realistic case, and docs/18 notes it.

## 8. Out of scope, for the coordinator to file
1. **One source of `metadata-keys.yaml`** (§1.3). Either `git-bootstrap`/CI checks that the cluster-configs copy
   equals the deployed Helm `metadata:` render, or the instance reads the file from Git. Until then the report
   describes what the file *would* serve.
2. A `workflow_run` commenter that posts the artifact's `changelog.md` as a PR comment, if the owner wants comments.
   It treats the artifact as data and never checks out PR code.

## Sources

- GitHub workflow syntax (paths, three-dot diff, 3,000 files, skipped workflow leaves a required check Pending), events that trigger workflows (fork `pull_request`: read-only token, no secrets; `GITHUB_SHA` is the merge commit), workflow commands (summary: 1 MiB per step, 20 per job): https://docs.github.com/en/actions/reference/workflows-and-actions/ `workflow-syntax`, `events-that-trigger-workflows`, `workflow-commands`
- GitHub Security Lab, "Preventing pwn requests": https://securitylab.github.com/resources/github-actions-preventing-pwn-requests/
- oasdiff 1.37.0, measured locally (`changelog --help`; rc 0 and 102 as in §3). In this repository: `contract/gate.sh`, `.github/workflows/ci.yml`, `main.py`, `core/docs.py`, `core/context.py`, `tools/policies.py`, `tools/git_bootstrap.py`, arbitration question 4.
