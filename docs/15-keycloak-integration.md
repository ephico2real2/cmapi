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
| `cmapi-automation` | Confidential | Client credentials | An AI agent or a script, by the client's service account | The service account holds `cmapi-onboarding` only |
| `svc-payments-ci` | Confidential | Client credentials | A sample pipeline | One client for each pipeline |
| `cmapi-directory` | Confidential | Client credentials | The API's people search | Realm-management roles `view-users` and `query-users` only |
| `cmapi-realm-admin` | Confidential | Client credentials | The Job `cmapi-realm-sync`, and the rollback's realm delete | Realm-management role `realm-admin`, in realm `cmapi` only |
| `admin-cli` | Public | None | Nobody | Disabled. Keycloak makes it in each realm, and it would take a password with no secret |

No public client accepts a password. The password of a person from LDAP goes only into Keycloak's own sign-in page.

## The scopes, the mappers and the audience

Each client that gets a token for the API has the default scopes `basic`, `cmapi-identity`, `cmapi-audience`, `roles`, `profile` and `email`.

| Scope | Mapper | Claim in the access token | cmapi reads it as |
|---|---|---|---|
| `cmapi-audience` | Audience | `aud` contains `cmapi-nonprod` | The audience check (`cmapi/src/cmapi/core/auth.py:170-172`) |
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

The group tree is `/cmapi` with ten groups under it, `app-cmapi-rbac-<role>`, each with its client roles. `docs/14`, "The contract in one table", lists them. The import creates the tree (`10-realm-import.yaml:391-445`), and the sync sets the same mapping from `CMAPI_REALM_GROUPS` (`20-realm-sync.yaml:36-37`), so a later change of the mapping needs no new import.

## The LDAP federation

The sync creates one LDAP provider in realm `cmapi` (`realm_sync.py:202-273`).

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

cmapi accepts a token until its `exp`, with a leeway of 30 seconds (`auth.py:146`, `:165-166`). It keeps the signing keys for 10 minutes, and keeps verifying with the last good keys when Keycloak does not answer (`auth.py:1-8`).

## How cmapi reaches Keycloak

| Need | URL on CRC | Why |
|---|---|---|
| The issuer in each token | `https://keycloak.apps-crc.testing/realms/cmapi` | The public name. cmapi compares `iss` with it and does not call it |
| The signing keys (JWKS) | `https://keycloak-service.keycloak.svc:8443/realms/cmapi/protocol/openid-connect/certs` | The Service in the cluster, so no pod calls the edge Route |
| The people search | `https://keycloak-service.keycloak.svc:8443`, as client `cmapi-directory` | The same |

Both calls verify Keycloak's certificate against the CA in ConfigMap `cmapi-trust` (`deploy/manifests/environments/crc/30-trust.yaml`). TLS verification is never off.

## From sign-in to a permitted call

Swagger UI uses Authorization Code with PKCE through the public client `cmapi-docs` (`cmapi/src/cmapi/main.py:60-61`, `core/auth.py:189-194`). The portal will use the same flow through `cmapi-portal`: that part is not built.

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

An AI agent or a script signs in as the client `cmapi-automation`, also with the client credentials grant. Its service account holds the role `cmapi-onboarding`, so it can create a namespace and follow its requests. cmapi sees the caller `cmapi-automation` of the kind `service`.

```bash
TOKEN=$(curl -s "$KC/token" \
  -d grant_type=client_credentials -d client_id=cmapi-automation -d client_secret="$AUTOMATION_CLIENT_SECRET" \
  | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/me" | jq .access
```

Keep each secret in a variable that comes from a secret store, and never on a command line that a log records.

### The type of an access token

cmapi accepts a token only when its JOSE header says `typ: at+jwt` or `application/at+jwt`. RFC 9068, section 4: the resource server "MUST verify that the "typ" header value is "at+jwt" or "application/at+jwt"" and must "reject tokens carrying any other value". An ID token and a refresh token have another type, so neither can be a bearer credential.

Keycloak 26 writes the header `typ: JWT` on each access token, ID token and refresh token (a logout token has `logout+jwt`), and `at+jwt` on the access token of a client that has the attribute `access.token.header.type.rfc9068` (`DefaultTokenManager.type`, Keycloak 26.6.4). cmapi's realm sets the attribute on each client that gets a token for cmapi: `cmapi-portal`, `cmapi-docs`, `cmapi-cli`, `cmapi-automation` and each pipeline client. The API's own client (`cmapi-nonprod` on CRC) has it also. That client gets no token, but Keycloak's V1 token exchange writes the header type of the target client (`V1TokenExchangeProvider.setClientToContext`), and cmapi's realm turns no token exchange on. `cmapi-directory` and `cmapi-realm-admin` do not have it, because their tokens go to Keycloak's own admin API. For a realm that was imported before this rule (#184), and for a client that was added by hand, the Job `cmapi-realm-sync` sets the attribute on each client that has the client scope `cmapi-audience`, as a default or an optional scope. The sync does not find a client that gets the audience from a mapper of its own: set the attribute on that client by hand.

A new pipeline client needs the attribute, or cmapi answers 401 "Token is not an access token". For a Keycloak that cannot set it, `auth.acceptLegacyTokenType: true` in `instance.yaml` makes cmapi accept Keycloak's older form also: the header `JWT` together with the claim `typ: Bearer`. A token with no `typ` claim never passes that way. In the Helm chart the setting is the value `auth.acceptLegacyTokenType`.

**An upgrade of a deployment that is older than #184.** The old realm writes the header `JWT`, and the new API refuses it. Use this order:

1. Run the Job `cmapi-realm-sync` of the new image while the old API still serves. The Job needs no API.
2. Wait for the lifetime of an access token (`accessTokenLifespan`, 300 seconds in cmapi's realm), or make each client get a new token. The sync cannot change a token that Keycloak has signed. A refresh after the sync gives a token with the new header.
3. Roll out the new API.

If the API must roll out first, set `auth.acceptLegacyTokenType: true` for that time. Remove the setting when the old tokens have expired. The chart runs the sync as a `post-upgrade` hook, after the new pods start. So a chart upgrade across #184 needs the setting for the upgrade, or the sync run by hand first. The first deployment on CRC (`docs/13`) imports a new realm and runs the sync before the workloads.

### No password grant

No client of realm `cmapi` takes the resource owner password grant. RFC 9700, section 2.4: "The resource owner password credentials grant [RFC6749] MUST NOT be used." The grant gives a person's password to the client, and it cannot ask for a second factor. Each client of the import says `directAccessGrantsEnabled: false`, the disabled `admin-cli` also. For a realm that was imported before this rule (#181), the Job `cmapi-realm-sync` turns the grant off on each client, gives `cmapi-automation` its service account, and removes the local test account `bot-user`.

A person's password goes only into Keycloak's sign-in page. The proofs must still sign in the 13 LDAP test users with no browser. `deploy/oidc-login.py` does it as a browser does: the authorization code grant with PKCE (RFC 7636, S256) through the public client `cmapi-docs`. It sends the password to Keycloak's login form, reads the code from the redirect, and gets the token from the token endpoint. It is for test identities only, and it stops when Keycloak shows another page than the login form. The password comes on standard input:

```bash
printf '%s\n' "$PASSWORD" | deploy/oidc-login.py --issuer "$KC_ISSUER" --client-id cmapi-docs \
  --redirect-uri https://cmapi-api.apps-crc.testing/docs/oauth2-redirect --username cmapi.viewer --cacert "$CMAPI_CRC_CA"
```

## A real token

Not captured yet. The claims of a real access token, with no secret and no signature, come from the Wave 1 run on CRC: one test user from LDAP through `cmapi-docs`, as `deploy/crc-proof.sh` does for each of the 13 with `deploy/oidc-login.py`.

## Proof

| What | Where it ran | Result |
|---|---|---|
| The import and the sync on Keycloak, beside other realms | Community Keycloak 26.6.4 and an LDAP stand-in in containers, by `deploy/tests/realm-test.py` in the CI job `manifests` | Passed on PR #112's head. Read the run of the commit that merged it |
| The same on RHBK 26.6.7 | CRC | Not run yet |
| Each of the 13 test users signs in, and its token has the groups and roles of the table | CRC, `deploy/crc-proof.sh` | Not run yet |
| Sign-in to Swagger UI with PKCE and one Try it out call | CRC, in Chrome | Not run yet. It needs the owner's keychain step (`LOCAL-DEV-TRUST.md`) |
