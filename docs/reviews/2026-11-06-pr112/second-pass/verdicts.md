# Second-pass claim verdicts

C1: CONFIRMED | MEASURED: interrupted fifth ldapadd exits 52 with four users; removal exits 0 and rerun exits 0; differing description refuses all deletes. logs/C1.log; head/examples/cmapi-sso/ldap/apply-test-identities.sh:224.

C2: REFUTED | READ FROM CODE: prerequisites require every new entry same, but ldapdelete has no -r (head/examples/cmapi-sso/ldap/apply-test-identities.sh:190). MEASURED: a child under the final old group causes exit 66 after nine earlier deletions, logs/C2.log.

C3: REFUTED | MEASURED: cut prints a constant then exits 52, yet script exits 0, writes 23 entries and compares zero digests; logs/C3.log. READ FROM CODE: echo hides cut status at head/examples/cmapi-sso/ldap/apply-test-identities.sh:121,128.

C4: CONFIRMED | MEASURED: /bin/dash and /bin/bash each exit 52 on failed openssl with no Secret and identical LDAP digest; logs/C4.log; head/examples/cmapi-sso/ldap/apply-test-identities.sh:300.

C5: PLAUSIBLE | MEASURED: real stand-in answers 32, both injected read failures produce 52 and are rejected; logs/quiet-case-audit.log, logs/C5.log. Production NOT REACHED; docs/reviews/2026-11-06-pr112/README.md:61 calls it inferred.

C6: PLAUSIBLE | MEASURED: legacy decoding, serializer round trip and both service tests pass; historical main constant matches, logs/C6-unit.log and logs/C6-service.log. READ FROM CODE: every non-null requirement_to_json writes groupPath (head/cmapi/src/cmapi/core/db/repo.py:38); RequestRepo.insert accepts a caller-supplied row unchanged (:135). No actual application caller omitting the path was demonstrated within the named-file scope, so a universal new-row claim is unproven.

C7: CONFIRMED | MEASURED: Keycloak DER matches with extra CA, bundle has three CAs, no-extra bundle byte-identical to reversed patch 10; logs/C7.log, tests/C7.py exits 0; head/deploy/crc-trust.sh:84.

C9: CONFIRMED | MEASURED: all 16 refusal cases fail for their named causes, with clean controls and reasons audited; silent openssl invocation separately marked. logs/C9.log, logs/C9/, logs/quiet-case-audit.log; tests.md contains per-case results.

C10: REFUTED | MEASURED: step 9 succeeds; an extra group description blocks step 10 and LDAP rollback without guidance; rollback first issues 32 simulated Kubernetes deletes. logs/C10.log; head/deploy/crc-rollback.sh:29-57.

MEASURED: tally 4 CONFIRMED, 3 REFUTED, 2 PLAUSIBLE, 0 wholly NOT REACHED. Production part of C5 is NOT REACHED. C8 excluded.

PROPOSAL NOT OPERATED: full fixes and full behavioural regressions are in fixes.md and patches/C2.patch, patches/C3.patch, patches/C10.patch. Each exact added test exits 1 before and 0 after. Apply in C2, C3, C10 order; fuzz-0 combined application was measured. No change was applied to head, committed or pushed.

MEASURED: 8 graph calls; 68 shell tool calls (54 executions, 14 polls). GitHub read calls: 3.
