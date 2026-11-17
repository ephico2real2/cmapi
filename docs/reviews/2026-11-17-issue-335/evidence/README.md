# #335: the evidence

Measured on 2026-11-17 by the implementer (Opus 5.5), on the Mac and on a `cmapi-test` kind cluster (kind v0.33.0, podman,
node `kindest/node:v1.35.8`). Nothing ran on CRC.

| File | What it is |
|---|---|
| `render-defaults.diff.txt` | `helm template` with the defaults and `deploy/environments/crc.yaml`, main 9ba33b2 against this branch, Secrets dropped (their values are random per render): no difference over 29 documents. Made with `render-nosecrets.sh` |
| `kind/proof.sh` | The kind proof as it ran (its paths are the implementer's workbench). Installs the stand-ins (`support.yaml`: a PostgreSQL 16 and a JWKS server), the Gitea stand-in chart `deploy/helm/cmapi-git`, the reader baseline and import Secret of the plain manifests, then this chart with `values-kind-335.yaml`, and posts two creates |
| `kind/values-kind-335.yaml` | `instance.policy.engine: none`, and `metadata`: the chart's `config/metadata-keys.yaml` plus the required label `acme.example/owner` |
| `kind/mint.py` | A throwaway signing key and the requester's token. The key is written to `kind/keys/` (git-ignored) and never leaves the machine |
| `kind/proof-run.log` | The run: the rendered ConfigMap requires `acme.example/owner` and `cmapi.net/team`; a create without `acme.example/owner` gets 422 `policy-violation`, `missing_required_key`; the same body with it passes (`?dryRun=true`, 200) |
| `kind/proof-refused-upgrade.log` | `helm upgrade` with `requiredLabel` misspelled: refused by `values.schema.json`, the release stays at its revision and the API pod is not replaced |

The issue expected the code `validation-failed`. On main a missing required label is refused by the metadata validator with
422 `policy-violation` (`core/metadata.py`, `Problem.policy_violation`); `validation-failed` is the code of a body that fails
the request schema, which #328's generated schema adds for the required keys.

Runs 1 to 7 of `proof.sh` stopped earlier, each for a reason in the setup (one because the script was edited while it ran); the others are recorded in the script's comments: a digest
reference that `kind load` does not create (ErrImageNeverPull), a re-generated database password, a re-generated signing
key under the same `kid`, the cluster not imported (503), no Git host (502), and a bot Secret that the chart writes itself.
