# #337: the API contract report of a Helm values change

Pull request #370, part of #328 (arbitration question 4). Opus 5.5 wrote design A and every commit; OB3 (Opus 5.5) wrote
design B; the coordinator wrote the arbitration. One model family: Codex was out of quota until 2026-11-18 and Fable is
paused.

| File | What it is |
|---|---|
| [`design-a.md`](design-a.md) | Design A: the report in the cluster-configs CI, the offline generator, the oasdiff hardening (measured) |
| [`design-b.md`](design-b.md) | Design B: the same report, and the finding that a running cmapi reads `metadata-keys.yaml` from its Helm values (#335), not from cluster-configs |
| [`arbitration.md`](arbitration.md) | The coordinator's rulings and the owner's: the report runs where the values live, as a reusable workflow |
| `evidence/` | The new tests on main 7ba5d78 and on the branch, and a local report of a required label |

## What was built

- `cmapi-tools openapi render` (`cmapi/src/cmapi/tools/openapi.py`), on `main.api_app`, split out of `create_app`.
- `cmapi/contract/report.py`, run by the reusable `.github/workflows/api-contract-report.yml`, which this repository calls
  from `.github/workflows/values-contract-report.yml`.
- docs/18, "The contract report of a values change".

Two choices beyond the arbitration: the caller's paths include `deploy/helm/cmapi/templates/config.yaml`, the template
that writes the ConfigMap's `metadata-keys.yaml`; and the reusable workflow installs cmapi without `-e`, so each run also
proves that the package carries its reference instance.

## Measured

On the Mac, helm 4.3.1, oasdiff 1.37.0, Python 3.12:

| Test file | main 7ba5d78 | branch |
|---|---|---|
| `cmapi/tests/service/test_openapi_render_337.py` | collection error, no `cmapi.tools.openapi` (`before-render.log`) | 8 passed |
| `cmapi/tests/service/test_contract_report_337.py` | 11 failed, no `report.py` (`before-report.log`) | 11 passed (`after-service.log`) |
| `cmapi/tests/core/test_contract_report_workflow_337.py` | 7 failed, 1 passed (`before-workflow.log`) | 8 passed (`after-workflow.log`) |

The one test that passes on main is the guard that no workflow runs on `pull_request_target`; it holds there too.

`local-report-required-label.md` is the report of `crc.yaml` with `requiredLabels.cmapi.net/data-class` added through
`metadata:`: one `new-required-request-property` error, exit 0.

Not run locally: the service suite as a whole and the committed-contract test, which need the shared PostgreSQL on 55432;
CI runs them.

## The live run on GitHub

Throwaway pull request #371, based on this branch, added `requiredLabels.cmapi.net/data-class` to
`deploy/environments/crc.yaml` through `metadata:`. `values-contract-report` ran on it (run 44148501411): the job passed,
its summary lists "added the new required request property `labels/cmapi.net/data-class`" under
`POST /api/v1/clusters/{cluster_id}/namespaces` (`evidence/live-pr371-job-summary.jpg`), and the check run carries the
warning on `deploy/environments/crc.yaml` (`evidence/live-pr371.md`). #370 changes none of the paths, and no
`values-contract-report` run exists for it. #371 was closed unmerged and its branch deleted; its `ci` run was cancelled.

The run also shows GitHub's warning that `azure/setup-helm` v4.3.1 targets Node.js 20, which GitHub forces onto Node.js 24.
The service job uses the same pin; a bump of that action is its own change.
