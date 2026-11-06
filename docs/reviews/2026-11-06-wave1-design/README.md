# Wave 1 design (#94): arbitration

Two independent designs on exports of `main` at `9fd230a`: Codex (`codex-design.md`) and a separate Opus 5.5 (`opus-design.md`). The coordinator read both and decided as below. **Where a ruling and a design differ, the ruling holds.** Opus's design is the base, because it ran what Codex's only reasoned about; each row gives the reason. Nothing here has been applied to CRC.

Neither design is the implementation. The implementer builds from `opus-design.md`, and its code goes through the review flow in `CLAUDE.md`. Codex's design was finished before the owner's requirements on the other realms and the backup reached it, so sections 13 and 14 of Opus's design stand alone on those.

## Rulings

| # | Question | Codex | Opus | Ruling and reason |
|---|---|---|---|---|
| 1 | Where the trust bundle lives | Render reads the cluster's CAs through `--trust-bundle` | In Git, written once by `crc-trust.sh`; `render.sh` unchanged | **Opus.** Argo CD in Wave 5 renders in CI with no cluster access, so the file must be in Git. A public certificate is fine in a public repo. A rotated CA fails closed and goes through Git, where the checksum sees it |
| 2 | What the bundle holds | Keycloak's CA and the ingress CA | Keycloak's CA only | **Opus.** No Wave 1 pod calls an edge Route. Add the next CA with the wave that needs it (#97) |
| 3 | `realm-sync` in Wave 1 | Not needed; LDAP in the import through legacy fields it could not run | Needed; one try, `requireSync` | **Opus.** Measured on real Keycloak 26.6.4 with an LDAP stand-in, 24 of 24. Without the user profile `employee_id` never reaches a token, and a wrong LDAP URL in a one-shot import would mean deleting the realm |
| 4 | Import memory | Unspecified | `spec.resources` 768 Mi request, 1 Gi limit; the default stays as a fallback | **Opus.** Measured peak about 735 MB. RHBK serves the field (read with `oc explain`). If its image needs more, the Job is killed, the wait withdraws it, and the 1,700 Mi default still fits alone at 2,318 Mi left |
| 5 | Order | Realm before workloads | Image first, then realm alone, then workloads | **Opus.** No build load beside an import, and the riskiest step runs on the quietest cluster |
| 6 | Issuer check | Before any Secret write | Only when about to mint, and at steps 4 and 13 | **Opus.** The other verdicts mint nothing, so a later run must not need Keycloak up. Anything but Keycloak's own 404 or a matching 200 stops |
| 7 | Delivery | `argocd`, no provider detail | `argocd`, `writes: false`, provider `github`, `https://git-not-configured.invalid` | **Opus.** Three separate stops, and no Gitea. The code needs a provider kind, and `.invalid` can never resolve |
| 8 | Reader rights | Three resources | Five, adding Pods and PVCs | **Opus.** Taken from the calls in the code: `pipeline.py:153-154` lists them |
| 9 | Image scripts | Replace `release-crc.sh` and `baseline-crc.sh` | New `crc-*` scripts; the old ones stay until the charts go | **Opus.** Ruling 3 of the deployment design keeps them until then, and neither is reused |
| 10 | Prometheus proof | `oc get --raw` through the API server's proxy | Thanos Querier's Route, token on stdin | **Opus.** An API server proxy does not forward the caller's token, so Codex's call would likely get 401 (inferred). Opus's has a test |
| 11 | Route proof | Route answers after the policy | Adds a probe that must reach the mockup and be blocked from the api | **Opus.** A Route answers with no enforcement as well, which is how podman kind has behaved |
| 12 | Rollback and realm `cmapi` | Deletes it first with the realm's own client | Leaves it unless `--delete-realm --owner-approved` | **Opus.** Deleting a realm is the owner's call. Both found the coordinator's premise wrong: the realm's own client can delete it, measured on 26.6.4. RHBK is not measured |
| 13 | Guards | Context and principal check, `--field-manager` | Snapshot, watch, gate, withdrawal | **Opus's, plus Codex's two:** `preflight` also checks the context and principal, and every apply uses `--field-manager=cmapi-wave1` |

## The owner's requirements

The other realms must not be affected, `inkcast` and `corp` must not be deleted, and a restart must not bleed long (2026-11-06). Sections 13 and 14 of `opus-design.md` carry this:

- **Nothing else changes.** Every write or delete in `keycloak` names a cmapi object, with tests that fail on a broad delete.
- **Proof.** Each realm's status and public key hash, the other imports, `keycloak-0`, `postgres-0` and the Keycloak CR, compared at each step. A difference stops the run.
- **Watching.** Every realm polled every 5 s. A breach writes a stop file that every later step checks.
- **A restart.** cmapi stops and takes no action on Keycloak. **At 300 s still unready, the owner is told at once,** against a 2 min 42 s baseline. It can only be bounded, not ruled out: Keycloak has one instance, and the cause of the one measured restart is unknown. The import itself should not cause one: 26.6.7's source says so, while 26.0.8's did restart.
- **A pending import** is withdrawn by name if not started in 300 s, since an earlier one here waited about 6.5 days.
- **Backup.** A read-only `pg_dump` immediately before the import, proven with a full read because `--list` passes a truncated file. Restoring is the owner's decision alone.

**What a realm's public key cannot show:** a change to a client inside a realm. Seeing that needs an admin credential, which stays forbidden. Creating any realm also adds one client, `cmapi-realm`, to `master` (measured). That is the one known change outside realm `cmapi`.

## The open questions, read from CRC by the coordinator on 2026-11-06

| Question | Answer |
|---|---|
| Does RHBK serve `KeycloakRealmImport.spec.resources`? | Yes (`oc explain`). The field's text says "inherited from the Keycloak CR", while the Job measured here requests the operator's 1,700 Mi. The server dry run is the check |
| Can cmapi's pods reach Keycloak? | Yes. `keycloak-network-policy`, owned by the Keycloak CR, allows 8443 and 9000 from anywhere. Nothing needs changing in that namespace |
| Will federation work over this path? | Likely: `corp` uses the same `ldaps://ldaps-ldap-testing.apps-crc.testing:443`, `useTruststoreSpi: always`, `uid`, `inetOrgPerson`, and the truststore `ldap-root-ca` is on the Keycloak CR |
| Is `cmapi-ldap-bind` in both namespaces? | Yes, with `bindDN` and `password`. Codex's copying step is not needed |
| How does the backup authenticate? | Red Hat's `postgresql-16` image: `POSTGRESQL_USER` and `POSTGRESQL_PASSWORD` from Secret `keycloak-db`, read inside the pod. `pg_dump` 16.15 and `pg_restore` are in the pod. Limit 512 Mi, using 52 Mi. Whether its local socket accepts that user is the first run's check; if not, the run stops at that step |
| Is an LDAP person's password available? | No. Five `userPassword` values in `ldap-structure` are hashed. The sixth is not hashed; it was not printed and is not used here, and #35 covers that ConfigMap |

## Steps only the owner can take

The tracker said Wave 1 had none. It has two, both for the Chrome proofs, when the time comes:

1. Trust the two CAs in the login keychain, since neither is on this Mac and macOS asks for a password. They come out again afterwards. Clicking through a warning would be TLS verification off.
2. Sign in once as an LDAP person, typing the password into Chrome, so it reaches nobody else. If that is not wanted, the LDAP login proof is reported as not done.

## Found along the way

- #96: `realm_sync` reads an unreachable directory as success, and a Job ends Complete with no federation. Fixed in Wave 1.
- #97: `settings.verify` goes to the Git provider, so a private-CA-only bundle fails GitHub's TLS. For Wave 3.
- `secrets.sh`'s advice to keep the import conflicts with the operator's guide. Wave 1 changes it.
- `render-test.sh:37` nests `crc/kind/` once `environments/crc` exists. Wave 1 removes the line.
- The pinned CRDs catalog has no Route schema, so kubeconform skips Route and a test holds its shape.

## Not proven before CRC

RHBK's Job on `spec.resources`; `restricted-v2`; the internal registry and its pull; OVN-Kubernetes enforcing the policy; the router through it; `ldaps` through Keycloak's truststore on a new realm; user workload monitoring; a real restart's recovery. `crc-proof.sh` has run only on stubs. Opus's measurements used community Keycloak 26.6.4, since 26.6.7 is not on quay, so that RHBK behaves the same is inferred.
