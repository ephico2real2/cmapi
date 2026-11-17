# #337: the arbitration of two designs

- **Design A** (`design-337-a.md`): a general-purpose Opus 5.5 agent, which also builds.
- **Design B** (`design-337-b.md`): OB3, a separate Opus 5.5 agent.

One model family (Codex out of quota until 2026-11-18 14:09; Fable paused). Written apart.

## The owner's ruling on where the report runs (2026-11-17)

Design B found that a running cmapi reads `metadata-keys.yaml` from its ConfigMap, built from the Helm values (#335);
`cluster-configs` only holds a copy (`git_bootstrap.py:121-130`). Asked where the report should run, the owner chose
**where the values live**: the CI of the repository that holds the instance's Helm values, shipped as a reusable workflow
any values repository can call. For CRC that is this repository (`deploy/environments/crc.yaml` and the chart's
`config/metadata-keys.yaml`). No report is added to cluster-configs.

## Where the designs agree (adopted)

| Point | Both |
|---|---|
| Generator | A new `cmapi-tools openapi render`, from a behaviour-preserving split of `create_app`, so CI and the served document come from one path; offline (no DB, no network, no kyverno). The render of the test config is byte-identical to `cmapi/contract/openapi.json` (a test) |
| Report | oasdiff 1.37.0 (the `api-contract` pin and SHA-256) `changelog` in markdown to the job summary, with a notice annotation; no PR comment (a fork's token is read-only; `pull_request_target` ruled out) |
| Exit | Never fails on a change (no `--fail-on`); fails loudly when the tool, a pin, the base, or the head config is broken |
| Trigger | `pull_request` with a `paths` filter; never a required check (a path-skipped required check stays pending) |

## Rulings where they differ or left a choice

| Point | Ruling |
|---|---|
| Name and place | A reusable workflow (`workflow_call`) in this repository, called by its own CI on PRs that change `deploy/environments/**` or `deploy/helm/cmapi/config/metadata-keys.yaml` or `deploy/helm/cmapi/values.yaml`. Base and head inputs are the `metadata-keys.yaml` that `helm template` renders into the ConfigMap for each values file, so the report covers both the `metadata:` block and `configFiles` |
| Instance without `--config-dir` | B: the packaged reference instance, so every difference comes from `metadata-keys.yaml` |
| cmapi version | In this repository the tool runs from the checkout itself (no pin needed). The reusable workflow takes a 40-hex `cmapi-ref` input for other repositories (A's fail-loud pin) |
| oasdiff hardening | A: run from an empty working directory with `--allow-external-refs=false` (a planted `.oasdiff.yaml` changed the exit code, measured) |
| Live proof | Tests as both designs list, plus one throwaway PR in this repository that adds a required label to `deploy/environments/crc.yaml`, closed unmerged, with the job summary captured |
