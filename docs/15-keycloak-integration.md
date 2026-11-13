# The Keycloak integration

This document says what cmapi creates in Keycloak, and how a caller gets a token that cmapi accepts. It says only what the manifests and the code do. A part that is designed and not built has the words "not built". A result names the cluster it came from.

Keycloak holds the users and their group membership, and maps each group to a cmapi role. LDAP gives the users and the groups to Keycloak through a read-only federation. cmapi defines the names: [`docs/14-authorization.md`](14-authorization.md) has the contract.

**cmapi installs no Keycloak and no LDAP server.** On CRC both exist and other projects use them ([`docs/11`](11-existing-identity-services.md)). cmapi changes only realm `cmapi`, and it has no credential of realm `master`.

## Two steps make the realm

| Step | What | Who runs it | Source |
|---|---|---|---|
| The import | The realm, its settings, the client scopes, the clients, the client roles, the group tree and two service accounts | The RHBK operator, once, from a `KeycloakRealmImport`. An existing realm stays as it is | `deploy/manifests/environments/crc/realm/10-realm-import.yaml` |
| The sync | The user profile, the roles of the two service accounts, the group-to-role mappings, the LDAP federation with its mappers, and the local test users | The Job `cmapi-realm-sync`, with the realm's own client `cmapi-realm-admin` | `cmapi/src/cmapi/tools/realm_sync.py`, `deploy/manifests/environments/crc/realm/20-realm-sync.yaml` |

The import holds no secret. Each client secret is a placeholder that the import reads from Secret `cmapi-realm-secrets`, which `deploy/secrets.sh` writes (`10-realm-import.yaml:1-3`). The steps to run both are in [`docs/13-crc-deployment.md`](13-crc-deployment.md), steps 11 to 21.

## The clients

Nine clients are in the import. The table is read from the file.

| Client | Type | Flow | Used by | Note |
|---|---|---|---|---|
| `cmapi-nonprod` | Confidential, bearer only | None: it issues no token | The API. It is the audience of each token and holds the eight client roles | The audience name is `cmapi-<instance>` |
| `cmapi-portal` | Public | Authorization Code with PKCE (`S256`) | The portal | Redirects: `https://cmapi-portal.apps-crc.testing/*` and `http://localhost:5173/*`. The portal's sign-in is not built |
| `cmapi-docs` | Public | Authorization Code with PKCE (`S256`) | Swagger UI at `/docs` | Redirect: `https://cmapi-api.apps-crc.testing/docs/oauth2-redirect`. Session: 1 hour idle, 8 hours at most |
| `cmapi-cli` | Public | Device authorization | The `cmapi` CLI | `offline_access` is optional. The CLI is not built |
| `cmapi-automation` | Confidential | Password grant | Local Keycloak accounts such as `bot-user`, and the proofs of `deploy/crc-proof.sh` | The only client that takes a password |
| `svc-payments-ci` | Confidential | Client credentials | A sample pipeline | One client for each pipeline |
| `cmapi-directory` | Confidential | Client credentials | The API's people search | Realm-management roles `view-users` and `query-users` only |
| `cmapi-realm-admin` | Confidential | Client credentials | The Job `cmapi-realm-sync`, and the rollback's realm delete | Realm-management role `realm-admin`, in realm `cmapi` only |
| `admin-cli` | Public | None | Nobody | Disabled. Keycloak makes it in each realm, and it would take a password with no secret |

No public client accepts a password. The password of a person from LDAP goes only into Keycloak's own sign-in page.

## The scopes, the mappers and the audience

Each client that gets a token for the API has the default scopes `basic`, `cmapi-identity`, `cmapi-audience`, `roles`, `profile` and `email`.

| Scope | Mapper | Claim in the access token | cmapi reads it as |
|---|---|---|---|
| `cmapi-audience` | Audience | `aud` contains `cmapi-nonprod` | The audience check (`cmapi/src/cmapi/core/auth.py:158-160`) |
| `roles` | Client roles | `resource_access.cmapi-nonprod.roles` | The roles of the caller (`cmapi/src/cmapi/core/identity/claims.py:54`) |
| `cmapi-identity` | Group membership, full path | `groups`, for example `/cmapi/app-cmapi-rbac-requester` | The approving groups (`claims.py:66`) |
| `cmapi-identity` | User attribute `employeeId` | `employee_id` | The requester's record (`claims.py:64`) |
| `cmapi-identity` | User attribute `middleName` | `middle_name` | The requester's record |
| `profile` | Username, first name, last name | `preferred_username`, `given_name`, `family_name` | The username and the record |
| `email` | Email | `email` | The record |
| `basic` | Subject | `sub` | The stable ID of the caller |

`groups` and `employee_id` are in the access token only, not in the ID token. A token for another instance has another audience, so cmapi refuses it with 401.

## The roles and the groups

The eight client roles of `cmapi-nonprod` are `cmapi-viewer`, `cmapi-onboarding`, `cmapi-requester`, `cmapi-approver`, `cmapi-operator`, `cmapi-admin`, `cmapi-auditor` and `cmapi-approval-relay`. The realm has no realm role of cmapi.

The group tree is `/cmapi` with ten groups under it, `app-cmapi-rbac-<role>`, each with its client roles. `docs/14`, "The contract in one table", lists them. The import creates the tree (`10-realm-import.yaml:375-429`), and the sync sets the same mapping from `CMAPI_REALM_GROUPS` (`20-realm-sync.yaml:36-37`), so a later change of the mapping needs no new import.

## The LDAP federation

The sync creates one LDAP provider in realm `cmapi` (`realm_sync.py:146-217`).

| Setting | Value on CRC | Effect |
|---|---|---|
| Edit mode | `READ_ONLY` | Keycloak writes nothing to LDAP |
| Connection | `ldaps://ldaps-ldap-testing.apps-crc.testing:443`, bind user `cmapi-ldap-bind` | TLS with the truststore of the Keycloak CR. The bind user reads only |
| Users filter | `(uid=cmapi.*)` | The realm reads only the 13 test users. No real person is in realm `cmapi` |
| Groups mapper | Filter `(cn=app-cmapi-rbac-*)`, placed under `/cmapi`, read-only | A group in LDAP becomes `/cmapi/<name>`, which has the client roles |
| `employee-id` mapper | LDAP `uidNumber` to the attribute `employeeId` | The claim `employee_id` |
| Sync | Changed users each 15 minutes, a full sync each 24 hours; cache 15 minutes | A change in LDAP reaches a token in 15 minutes at most |
| Guard | `requireSync: true`, `expectUsers: 13` | The Job fails if the first sync reads nobody, or a number other than 13 |

A person's membership changes in LDAP, never in Keycloak. cmapi's own LDAP entries are the ten groups, the bind user and the test users (`docs/11`).

## Token lifetimes

From the realm settings in the import (`10-realm-import.yaml`, under `realm:`).

| Setting | Value |
|---|---|
| Access token | 5 minutes |
| SSO session | 8 hours idle, 12 hours at most |
| SSO session with "remember me" | 7 days idle, 30 days at most |
| Offline session (the CLI) | 30 days idle, 90 days at most |
| Refresh token | Used once: `revokeRefreshToken` with no reuse |
| Swagger UI's client session | 1 hour idle, 8 hours at most |
| Wrong passwords | Temporary lockout after 10 failures, in this realm only, never in LDAP |

cmapi accepts a token until its `exp`, with a leeway of 30 seconds (`auth.py:135`, `:153-154`). It keeps the signing keys for 10 minutes, and keeps verifying with the last good keys when Keycloak does not answer (`auth.py:1-8`).

## How cmapi reaches Keycloak

| Need | URL on CRC | Why |
|---|---|---|
| The issuer in each token | `https://keycloak.apps-crc.testing/realms/cmapi` | The public name. cmapi compares `iss` with it and does not call it |
| The signing keys (JWKS) | `https://keycloak-service.keycloak.svc:8443/realms/cmapi/protocol/openid-connect/certs` | The Service in the cluster, so no pod calls the edge Route |
| The people search | `https://keycloak-service.keycloak.svc:8443`, as client `cmapi-directory` | The same |

Both calls verify Keycloak's certificate against the CA in ConfigMap `cmapi-trust` (`deploy/manifests/environments/crc/30-trust.yaml`). TLS verification is never off.

## From sign-in to a permitted call

Swagger UI uses Authorization Code with PKCE through the public client `cmapi-docs` (`cmapi/src/cmapi/main.py:60-61`, `core/auth.py:174-179`). The portal will use the same flow through `cmapi-portal`: that part is not built.

```text
Browser (Swagger UI at /docs)            Keycloak, realm cmapi                 cmapi-api
  1 Authorize: make code_verifier and
    code_challenge = S256(verifier)
  2 GET /protocol/openid-connect/auth -->  client cmapi-docs, challenge
  3                                        sign-in page; the person types the
                                           password here; Keycloak binds to LDAP
  4 <-- redirect to /docs/oauth2-redirect with a code
  5 POST /protocol/openid-connect/token --> code + code_verifier (no client secret)
  6 <-- access token: 5 minutes, aud cmapi-nonprod, roles, groups, employee_id
  7 GET /api/v1/me with Authorization: Bearer ------------------------------->  verify offline with the
                                                                                cached signing keys
  8 <------------------------------------------------------------------------  200, or 401 or 403
                                                                                (docs/14)
```

The sequence figure is not drawn yet. It follows the first sign-in on CRC, so that it shows what was measured.

## Get a token from a script

Two clients give a token to a script. Each needs its client secret. The URLs are those of CRC.

```bash
export KC=https://keycloak.apps-crc.testing/realms/cmapi/protocol/openid-connect
export CMAPI=https://cmapi-api.apps-crc.testing/api/v1
```

A pipeline uses its own service client with the client credentials grant. It gets no refresh token, so it asks again for each job:

```bash
TOKEN=$(curl -s "$KC/token" \
  -d grant_type=client_credentials \
  -d client_id=svc-payments-ci \
  -d client_secret="$CMAPI_CLIENT_SECRET" | jq -r .access_token)
```

A local Keycloak account such as `bot-user` signs in through `cmapi-automation` with the password grant. The client secret is necessary: without it Keycloak answers 401 `unauthorized_client` (measured on Keycloak 26.6.4).

```bash
TOKEN=$(curl -s "$KC/token" \
  -d grant_type=password -d client_id=cmapi-automation -d client_secret="$AUTOMATION_CLIENT_SECRET" \
  -d username=bot-user -d password="$BOT_PASSWORD" | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/me" | jq .access
```

Keep each secret in a variable that comes from a secret store, and never on a command line that a log records. A person from LDAP has no such recipe: the password goes only into Keycloak's sign-in page.

## A real token

Not captured yet. The claims of a real access token, with no secret and no signature, come from the Wave 1 run on CRC: one test user from LDAP through `cmapi-automation`, as `deploy/crc-proof.sh` does for each of the 13.

## Proof

| What | Where it ran | Result |
|---|---|---|
| The import and the sync on Keycloak, beside other realms | Community Keycloak 26.6.4 and an LDAP stand-in in containers, by `deploy/tests/realm-test.py` in the CI job `manifests` | Passed on PR #112's head. Read the run of the commit that merged it |
| The same on RHBK 26.6.7 | CRC | Not run yet |
| Each of the 13 test users signs in, and its token has the groups and roles of the table | CRC, `deploy/crc-proof.sh` | Not run yet |
| Sign-in to Swagger UI with PKCE and one Try it out call | CRC, in Chrome | Not run yet. It needs the owner's keychain step (`LOCAL-DEV-TRUST.md`) |
