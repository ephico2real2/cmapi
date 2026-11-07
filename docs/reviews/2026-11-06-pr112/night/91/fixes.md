# F1 — Pre-fix bad-CA proof did not inject a CA

READ FROM CODE — Root cause: `db_pod` replaced only the `cmapi-db-ca` Secret projection. Pre-fix manifests have neither that projection nor PGSSLROOTCERT. Consequently the promised before-fix negative test did not actually supply an unrelated CA.

READ FROM CODE — Full fix: always mount the kind trust ConfigMap at a dedicated probe-only directory, override only PGSSLROOTCERT to that path for the negative probe, and preserve the deployment's PGSSLMODE (including its absence before the fix). The positive probe remains unchanged. The ConfigMap is kind's standalone test CA, not CNPG's CA. Application manifests and external-server behavior are untouched.

MEASURED — Full test: `python deploy/tests/db-probe-test.py` with the Python/environment in tests.md. It executes the shell's actual `db_pod` generator through a fake kubectl transport. For api/worker, init/main, WIP/pre-fix shapes, positive/negative: resolve the generated mount and effective CA path to its projected source, check the sslmode is preserved, and positive env/volumes remain identical. This checks executable pod generation, not a string search or actual TLS. Before: exit 1, api migrate/pre-fix negative had no projected CA at libpq's effective path. After: exit 0, all 16 cases pass. Full logs: `logs/F1-before.log`, `logs/F1-after.log`. Patch: `patches/F1.patch`, based on the supplied WIP baseline; apply with `patch -p1 --fuzz=0`.

PROPOSAL NOT OPERATED — The generated pods' libpq handshake and refusal still require kind; this local test does not prove either.
