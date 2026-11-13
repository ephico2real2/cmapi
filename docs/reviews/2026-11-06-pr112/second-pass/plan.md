# Second-pass review plan

PROPOSAL NOT OPERATED: Review only the named scope at head ecc5cb362b99a4c06fc942466890cdbb753b9ca1. C8 is excluded.

1. C1: interrupted creation, removal, rerun; entry ownership and partial state.
2. C2: old-group prerequisites and recursive deletion.
3. C3: measurement failures, including awk, cut and mktemp.
4. C4: openssl failure under dash and bash.
5. C5: OpenLDAP exit checks and production claim.
6. C6: legacy requirement decoding and all scoped writers.
7. C7: mac_ca with and without extra CA.
8. C9: failure-case causes and isolation.
9. C10: documented migration then rollback with extra group attributes.

PROPOSAL NOT OPERATED: Record source observations separately from measured tests; supply complete fixes and behavioural regressions for defects. No commit, push, real cluster access, or venv installation.
