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

## Change the API

1. Change the code and its tests.
2. In `cmapi/`, write the document again: `CMAPI_WRITE_CONTRACT=1 PYTHONPATH=src:tests/service python -m pytest tests/service/test_api_docs.py -q -W ignore -k committed_contract`.
3. Commit `contract/openapi.json` with the code.

The CI job `api-contract` compares that file with the file on the base branch. A breaking change fails the job. An added endpoint or an added optional field passes.

## Accept a breaking change

Do this only before version 1.0, or for a new major version. Add the line that oasdiff prints for the change to `accepted-breaking.txt`, with the reason and the issue number on the line above it.

## Release a version

Copy `openapi.json` to `released/<version>.json`. Then run `python contract/changelog.py` and commit both files. The job fails when `changelog.json` is not current.

## The tool

oasdiff 1.37.0 does both jobs: the gate (`oasdiff breaking`) and the changelog (`oasdiff changelog`). CI downloads the release archive and checks its SHA-256, as it does for its other tools. Source: <https://github.com/oasdiff/oasdiff/blob/main/docs/BREAKING-CHANGES.md>, read on 2026-11-13: "Errors are definite breaking changes which should be avoided".
