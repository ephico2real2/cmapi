# Test record

MEASURED — All commands below run from `head` unless explicitly stated. Environment: `KUBECONFIG=../empty-kubeconfig`, `TMPDIR=../tmp` (absolute paths exported by the runner), `PYTHONDONTWRITEBYTECODE=1`. No container runtime or kind run is available. Full output goes in `report/logs/`.

MEASURED — WIP, folder `head`: `deploy/render-test.sh`; exit 0. Output: [wip-render.log](logs/wip-render.log).

MEASURED — WIP, folder `head`: `deploy/tests/crc-scripts-test.sh`; exit 0. Output: [wip-crc.log](logs/wip-crc.log).

MEASURED — F1 before fix, folder `head`: `python deploy/tests/db-probe-test.py`; exit 1. Full output: [F1-before.log](logs/F1-before.log). Executes the actual proof pod generator; no server.

MEASURED — WIP, folder `head`: `deploy/tests/kind-test-stubbed.sh`; exit 0. Output: [wip-kind-stub.log](logs/wip-kind-stub.log).

MEASURED — WIP, folder `head`: `python deploy/tests/doc12-test.py docs/12-existing-postgresql.md`; exit 0. Output: [wip-doc12.log](logs/wip-doc12.log).

MEASURED — F1 after fix, folder `head`: `python deploy/tests/db-probe-test.py`; exit 0, all 16 generated-pod cases pass. Output: [F1-after.log](logs/F1-after.log).

MEASURED — H4, folder `head`: docs/12 reconstructed with `patch -p1 --fuzz=0 -R` using its supplied wip.diff section; Python compares every fenced executable block to WIP; exit 0. Output: [H4-semantics.log](logs/H4-semantics.log).

MEASURED — H5, folder `head`: `deploy/render.sh crc image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa report/crc-render`; exit 0. Output: [H5-render.log](logs/H5-render.log). Digest is a synthetic render-only value; no image pull.

MEASURED — H5 resource calculation exit 0. Output: [H5-memory.log](logs/H5-memory.log). This is manifest arithmetic, not cluster capacity measurement.

MEASURED — folder `head`: `shellcheck deploy/kind-test.sh deploy/crc-proof.sh deploy/tests/crc-scripts-test.sh deploy/tests/external-db-test.sh deploy/tests/kind-test-stubbed.sh deploy/tests/kind-test-stubs/kubectl`; exit 0. Output: [shellcheck.log](logs/shellcheck.log).
