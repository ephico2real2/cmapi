# Applying the final set to `d6c063e`

From the repository root, in this order. Each is `patch -p1`, against `d6c063e` plus the earlier ones. No patch adds a file, so no mode needs setting, and CI runs every test through a step it already has.

```bash
F=<the review export>
for p in 01-render-atomic 02-secrets-preflight 03-router-selector 04-kind-ownership 05-doc12-restore 06-image-guard 07-render-test-gaps 08-doc12-argv-and-apply-order; do
  patch -p1 --batch < "$F/$p.patch" || break
done
```

Patch 02 already holds Codex's `secrets.sh` hunks, so do not also apply Codex's `secrets-preflight.patch`. None of Codex's other patches is applied.

## Each patch: the test that fails before and passes after

"Before" means the patch's test against the product file as it was, since a test file and the code it tests arrive together. Outputs are in `logs/proof/`.

| Patch | Findings | Command, from the root | Before: revert this file | Result before | Result after |
|---|---|---|---|---|---|
| `01-render-atomic` | 1, N9 | `deploy/render-test.sh` | `deploy/render.sh` | rc 1, `render cases failed: 5` | rc 0, `failed: 0` |
| `02-secrets-preflight` | 2 | `STUB_DIR=$(mktemp -d) STUB_PY=python3 STUB_KUBECTL=$PWD/deploy/tests/secrets-stub/kubectl-stub.py STUB_NO_CRD=true deploy/secrets-test.sh $PWD/deploy/tests/secrets-stub/stub.sh` (a Python with PyYAML) | `deploy/secrets.sh` | rc 1, `secrets cases failed: 18` | rc 0, `secrets cases failed: 0` |
| `03-router-selector` | 3, N4 | `python -m pytest --noconftest cmapi/tests/service/test_plain_manifests.py -k api_port` | `deploy/manifests/components/cmapi/40-networkpolicy.yaml` | 1 failed | 1 passed |
| `04-kind-ownership` | 4, N3 | `deploy/tests/kind-test-stubbed.sh` | `deploy/kind-test.sh` | rc 1, `wrong: 4` | rc 0, `wrong: 0` |
| `05-doc12-restore` | 5, N1, N2 | `python deploy/tests/doc12-test.py docs/12-existing-postgresql.md` | `docs/12-existing-postgresql.md` | rc 1, `doc cases failed: 9` | rc 0, `doc cases failed: 0` |
| `06-image-guard` | 6, N5 | `python -m pytest --noconftest cmapi/tests/service/test_plain_manifests.py -k image`, and `deploy/render-test.sh` | Nothing: a guard needs a mutant. In `20-api.yaml`, replace the first placeholder with `ghcr.io/evil/cmapi@sha256:` and 64 `e`, and run both on patch 05's tree and on patch 06's | Both pass on the mutant | Both fail on the mutant; both pass on the clean tree |
| `07-render-test-gaps` | N6 | `deploy/render-test.sh` | Four mutants of `render.sh`: `output/work/mutate-render.py <deploy dir>` | 4 survive | 4 killed |
| `08-doc12-argv-and-apply-order` | N7, N8 | `python deploy/tests/doc12-test.py docs/12-existing-postgresql.md`; `python -m pytest --noconftest cmapi/tests/service/test_plain_manifests.py -k readme` | `docs/12-existing-postgresql.md`; `deploy/manifests/README.md` | `doc cases failed: 3`; 1 failed | `failed: 0`; 1 passed |

`--noconftest` is what I ran, because the conftest points at `cmapi-test-pg`. Job `service` runs these under the real conftest.

## After all are applied

Measured here on a fresh copy with all eight (`logs/proof-summary.txt`):

```text
render-test        rc=0  render cases failed: 0
secrets-test       rc=0  secrets cases failed: 0
ci-guard           rc=0  ci cases failed: 0
doc12              rc=0  doc cases failed: 0
kind-stubbed       rc=0  wrong: 0
mutate-secrets     rc=0  mutants: 22, wrong: 0
mockup-check       rc=0  mockup ConfigMap is current
plain-manifests    rc=0  21 passed in 3.21s
shellcheck         rc=0  
```

Still to run, because I could not or was not allowed to:

1. CI on the exact head, all five jobs. That is the first time these reach `kubeconform`, `np-reach-test.sh` and `secrets-test.sh` on a real kind cluster, job `service` under its real conftest, and `ci-guard.py` on the hosted runner.
2. `deploy/kind-test.sh` end to end on a `cmapi-test` cluster, as the review README's item 2 already requires. The changes to the cluster-creation lines and `finish` have only run on stubs.
3. On the first CRC walk, the Route through the new selector. Before it, read-only: `oc get ingresscontroller default -n openshift-ingress-operator -o jsonpath='{.status.endpointPublishingStrategy.type}'`. If it says `HostNetwork`, the Route should still work on one node; the manifest's comment says why, and that reasoning is inferred until the Route answers.
4. Docs for the coordinator: `docs/reviews/2026-11-05-plain-manifests-test.md` and `docs/08-code-status.md` state results from before these patches. I did not edit them. Patch 05 does update `docs/12` section 6 from these measurements.
