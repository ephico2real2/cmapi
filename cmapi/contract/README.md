# The API contract

This folder holds the contract of the cmapi API and the tools that guard it. The design is `docs/01`, section "API documentation: Swagger UI and ReDoc".

| File | What it is |
|---|---|
| `openapi.json` | The OpenAPI 3.1 document that the code serves, for the test instance of the service suite. A test keeps it current |
| `released/<version>.json` | The document of each released version. A release adds one file. No version is released yet |
| `accepted-breaking.txt` | The breaking changes that the gate lets through, one for each line, each with its reason above it |
| `gate.sh` | Compares two documents with oasdiff. It fails on a breaking change |
| `gate-test.sh` | Proves the gate: a removed response field must fail, and an added one must pass |
| `changelog.py` | Writes `../src/cmapi/contract/changelog.json` from `released/`. `/docs/changelog` serves that file |
| `spectral/` | Spectral, pinned by `package-lock.json`, cmapi's ruleset `.spectral.yaml`, and its functions in `functions/` |
| `lint.sh` | Lints a document with the ruleset. It fails on an error of cmapi's rules and on a warning of Spectral's own OpenAPI rules |
| `lint-test.py` | Proves the ruleset: the committed document must pass, and a document that breaks one rule must fail with that rule |

## Change the API

1. Change the code and its tests.
2. In `cmapi/`, write the document again: `CMAPI_WRITE_CONTRACT=1 PYTHONPATH=src:tests/service python -m pytest tests/service/test_api_docs.py -q -W ignore -k committed_contract`.
3. Lint the document: `(cd contract/spectral && npm ci --ignore-scripts)` one time, then `contract/lint.sh`. A new rule gets a case in `lint-test.py`.
4. Commit `contract/openapi.json` with the code.

The CI job `api-contract` compares that file with the file on the base branch. A breaking change fails the job. An added endpoint or an added optional field passes.

## Accept a breaking change

Do this only before version 1.0, or for a new major version. Add the line that oasdiff prints for the change to `accepted-breaking.txt`, with the reason and the issue number on the line above it.

## Release a version

Copy `openapi.json` to `released/<version>.json`. Then run `python contract/changelog.py` and commit both files. The job fails when `changelog.json` is not current.

## The lint

`docs/01` names a Spectral lint as the first CI gate on the document. `spectral/.spectral.yaml` extends Spectral's own OpenAPI ruleset (`spectral:oas`) and adds cmapi's rules, each with the prefix `cmapi-`:

| Group of `docs/01` | Rules |
|---|---|
| operationId | `operation-operationId`, `operation-operationId-unique`, `cmapi-operation-id-of-plugin` |
| tags | `operation-tags`, `operation-tag-defined`, `tag-description`, `cmapi-operation-one-tag`, `cmapi-tag-in-one-group` |
| examples | `cmapi-parameter-example`, `cmapi-body-example`, `oas3-valid-media-example` |
| problem responses | `cmapi-problem-media-type`, `cmapi-problem-schema`, `cmapi-problem-example`, `cmapi-secured-operation-problems` |
| no inline schemas | `cmapi-no-inline-schema` |
| `cmapi.net/` keys only in label examples | `cmapi-net-keys-only-in-labels` |

Spectral resolves each `$ref` before it runs a rule. The two rules that must see the reference itself say `resolved: false`. `info-contact` is off, because the document names no person and no address.

To change Spectral's version, change it in `spectral/package.json`, run `npm install --ignore-scripts` there, and commit both files. Sources, read on 2026-11-13 at the tag `v6.17.1` of <https://github.com/stoplightio/spectral>: `docs/guides/4a-rules.md` for the form of a rule and `resolved`, and `docs/guides/5-custom-functions.md` for the functions, `functionsDir` and `context.path`.

## The tool

oasdiff 1.37.0 does both jobs: the gate (`oasdiff breaking`) and the changelog (`oasdiff changelog`). CI downloads the release archive and checks its SHA-256, as it does for its other tools. Source: <https://github.com/oasdiff/oasdiff/blob/main/docs/BREAKING-CHANGES.md>, read on 2026-11-13: "Errors are definite breaking changes which should be avoided".
