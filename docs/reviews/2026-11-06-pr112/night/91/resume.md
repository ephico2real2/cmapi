READ FROM CODE — Plan initialized. No implementation changed yet. Next: H1, read changed deployment/test files and run permitted WIP tests. All edits remain under head; no cluster or real server will be contacted.

READ FROM CODE — H1 inspected: all four plain-manifest DB clients use CNPG uri plus PGSSLMODE=verify-full and PGSSLROOTCERT pointing to the projected CA. The only Kubernetes Job in the plain deployment is realm-sync (identity services, not a database client). Legacy Helm is a separate, explicitly retired deployment path and is outside this implementation; do not claim every arbitrary deployment is secured. No application connection code changed; sqlalchemy_url preserves query parameters. Runtime enforcement remains unmeasured without kind.

READ FROM CODE — H2: Cluster name cmapi-db implies cmapi-db-ca; ca.crt only is projected, no subPath, default public-certificate readability. Optional is necessary for docs/12 and fails closed under verify-full when absent. Nothing restarts app pods on this Secret's change; kubelet eventually updates files and new connections re-read them. CNPG's routine renewal keeps its key; arbitrary key replacement is not a zero-downtime guarantee. Research sources saved. Runtime rotation is NOT REACHED.

READ FROM CODE — H3 complete: operator URI hostname is cmapi-db-rw.cmapi, explicitly covered by default server SANs. Source pinned to v1.30.1; no custom certificate or service override in the Cluster. Live certificate inspection is NOT REACHED.

MEASURED — F1 fixed and recorded: executable generator regression fails before (exit 1) and passes after (16 cases, exit 0). Dedicated probe CA now works on pre-fix as well as WIP specs, preserving sslmode. Patch and full test recorded. Next H4 semantic diff and H5 CRC.

MEASURED — H4: every docs/12 executable block identical to main. Documented external verify-full/bundle behavior preserved by libpq URI precedence; insecure or incomplete URIs intentionally become stricter. Existing doc12 test is running in the initial test batch; real external TLS is NOT REACHED. WIP external-db-test still needs its coordinator run and does not itself prove compatibility here.

MEASURED — H5 complete for local scope: CRC render exit 0, effective requests 160+128+256+32 = 576 Mi; realm-sync adds 96 Mi = 672 Mi. READ FROM CODE — docs/13 steps 17/18 create/await CNPG before workloads, so operator CA generation precedes clients; resource requests, security contexts, sequence and HTTP bundle unchanged. CRC operation is NOT REACHED.

READ FROM CODE — H6 all 14 files audited in scope.md. Removed the WIP's unsupported docs/08 runtime measurement (restored main's line). Remaining WIP changes relate to #91. New changes are the F1 generator repair/test and required reports. Final shellcheck and stubbed kind rerun in progress; mutation suite still running. Real kind, migration observation, rotation and external TLS remain NOT REACHED.
