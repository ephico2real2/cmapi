# H6 — WIP scope audit

READ FROM CODE — All 14 files from wip.diff reviewed. The TLS implementation remains the supplied WIP: no application rewrite, new controller, new CA copy or Helm change.

| WIP file | Disposition and reason |
| --- | --- |
| cmapi/tests/service/test_database_tls.py | READ FROM CODE — retain: manifests/render contract checks plus real-libpq plaintext refusal tests. Static checks are not TLS proof. Runtime suite requires PostgreSQL and remains NOT REACHED here. Its sslmode=disable case is an existing WIP proxy for URI precedence, not proof of docs/12 TLS; it was not run. |
| cmapi/tests/service/test_plain_manifests.py | READ FROM CODE — retain: old assertion forbade PGSSLROOTCERT and must follow the fix. |
| deploy/crc-proof.sh | READ FROM CODE — retain: checks effective libpq sslmode in CRC processes; server-side ssl alone cannot prove verification. CRC operation remains NOT REACHED. |
| deploy/kind-test.sh | MEASURED — retain and repair F1: proof for all four container environments, negative CA and server-side application sessions. Generator regression now fails before and passes after the repair. |
| deploy/manifests/README.md | READ FROM CODE — retain: explains CA source and renewal, shared by environments. |
| deploy/manifests/components/cmapi/20-api.yaml | READ FROM CODE — retain: api and its migrate TLS defaults and public CA projection are the fix. |
| deploy/manifests/components/cmapi/30-worker.yaml | READ FROM CODE — retain: worker and its migrate need the same fix. |
| deploy/tests/crc-scripts-test.sh | MEASURED — retain: executes CRC proof failure branches for non-verifying or unobservable connections. WIP suite exit 0. |
| deploy/tests/doc12-test.py | READ FROM CODE — retain: updates doc consistency assertions; existing executable doc tests exercise password/URI and restore semantics. The added string assertions are not behavioral TLS evidence. |
| deploy/tests/external-db-test.sh | READ FROM CODE — retain: external TLS compatibility with CNPG CA absent and explicit URI CA precedence needs runtime proof. NOT REACHED here. |
| deploy/tests/kind-test-stubbed.sh | MEASURED — retain: exercises proof rejection paths for plaintext, unverified TLS, wrong CA and missing server sessions. |
| deploy/tests/kind-test-stubs/kubectl | READ FROM CODE — retain: supplies scenarios required by the expanded proof harness. |
| docs/08-code-status.md | READ FROM CODE — remove WIP change: it presented an unfinished kind run as a completed verify-full/bad-CA measurement. Restore this line to supplied main semantics; do not manufacture a passing runtime result. |
| docs/12-existing-postgresql.md | MEASURED — retain: external runbook needs accurate libpq-default explanation. All four executable blocks identical to main. |

READ FROM CODE — No other WIP change is unrelated to #91. Existing Helm charts remain an explicitly retired deployment path (docs/08); they do not receive this fix and should not be included in an unqualified claim that all historical manifests are secured.

MEASURED — The stub suite's exit status is 0, but this sandbox denies pgrep's process-list access. Its port-forward cleanup count therefore is not reliable evidence of cleanup; the TLS failure-branch cases still execute. This inherited limitation is unrelated to #91 and is not expanded into a process-management change.
