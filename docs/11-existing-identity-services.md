# Existing identity services on CRC

On this CRC, cmapi uses an **existing LDAP server** and an **existing Keycloak**. It installs neither. Both serve other
projects, so cmapi adds only what it owns, and changes nothing else on them.

Checked on 2026-11-05.

| Service | Where | cmapi adds | cmapi never touches |
|---|---|---|---|
| Existing Keycloak | Namespace `keycloak`, CR `keycloak`, `https://keycloak.apps-crc.testing`, RHBK operator | Realm `cmapi`, through one `KeycloakRealmImport` named `cmapi`, applied once and deleted once Done (the operator's guide says to), and the Secret `cmapi-realm-secrets` in the same namespace that holds the import's placeholders (generated client secrets, the same values as Secret `cmapi-keycloak` in `cmapi`). Creating any realm also adds a client `cmapi-realm` to `master` (measured). Removing them: [`docs/13`](13-crc-deployment.md), "Rollback" | The other realms, the `Keycloak` CR, its operator and database, the master admin credential |
| Existing LDAP server | Namespace `ldap-testing`, OpenLDAP, `openldap-service` on 389 and 636, base `dc=ephico2real,dc=com` | The ten `app-cmapi-rbac-*` groups in `ou=Groups`, the 13 `cmapi.<role>` test users in `ou=People`, the bind user in `ou=TrustedApplications` | Other groups, every other person in `ou=People`, the rest of `ou=TrustedApplications` |

The chart deploys neither service. It takes the issuer as a value. A site with its own Keycloak and directory does the
same, with its own values.

## Existing Keycloak

- **Issuer for this deployment:** `https://keycloak.apps-crc.testing/realms/cmapi`. The production design's realm name
  stays `ephico2real`.
- **Why a realm import:** the operator creates the realm, so cmapi needs no admin credential for the shared instance. The
  operator group targets only `keycloak`, so the import has to live in that namespace. Other projects' realms were made
  the same way. Use API version `k8s.keycloak.org/v2beta1`.
- **Capabilities measured:** device flow for `cmapi login`, and PKCE S256 for the portal.
- **Trust:** the Route is passthrough. Its certificate comes from ClusterIssuer `enterprise-ca`
  (`CN=LDAP Enterprise Root CA`), which a machine's system trust does not accept. The service, the portal and the CLI must
  each be given that CA. TLS verification is never turned off.

## Existing LDAP server

### The groups

The owner's decision, 2026-11-06: one group per role, named `app-cmapi-rbac-<role>`. No GroupSync and no OpenShift Group mirroring; a dedicated GroupSync may come later.

Defined in [`examples/cmapi-sso/ldap/cmapi-groups.ldif`](../examples/cmapi-sso/ldap/cmapi-groups.ldif). `cmapi-approval-relay` has no group: it is for channel integrations, and goes on a client.

| LDAP group | Client roles on `cmapi-nonprod` | Name in approval rules | Test users |
|---|---|---|---|
| `app-cmapi-rbac-viewer` | `cmapi-viewer` | | `cmapi.viewer` |
| `app-cmapi-rbac-onboarding` | `cmapi-onboarding` | | `cmapi.onboarding` |
| `app-cmapi-rbac-requester` | `cmapi-requester` | | `cmapi.requester`, `cmapi.selfapprove` |
| `app-cmapi-rbac-approver-prod` | `cmapi-approver` | `approver-prod` | `cmapi.approver-prod`, `cmapi.approver-prod2`, `cmapi.selfapprove` |
| `app-cmapi-rbac-approver-qa` | `cmapi-approver` | `approver-qa` | `cmapi.approver-qa` |
| `app-cmapi-rbac-approver-uat` | `cmapi-approver` | `approver-uat` | `cmapi.approver-uat` |
| `app-cmapi-rbac-approver-platform` | `cmapi-approver` | `approver-platform` | `cmapi.approver-platform` |
| `app-cmapi-rbac-operator` | `cmapi-operator`, `cmapi-approver` | | `cmapi.operator` |
| `app-cmapi-rbac-admin` | `cmapi-admin` | | `cmapi.admin` |
| `app-cmapi-rbac-auditor` | `cmapi-auditor` | | `cmapi.auditor` |

- A token carries a group as its Keycloak path, `/cmapi/app-cmapi-rbac-<name>`. The realm's LDAP group mapper filters on `(cn=app-cmapi-rbac-*)` and places them under `/cmapi`.
- An approval rule names a short name. `identity.groupPath` in `instance.yaml` joins the two, by default `/cmapi/app-cmapi-rbac-{name}`, and the service stops at startup if it cannot name a group. A site with its own directory sets its own: `examples/local` keeps `/cmapi/cmapi-{name}` this way. A request stores the path it was decided under with its slots, so changing the setting does not move the approvers of an open request; a row stored before this setting reads as the old `/cmapi/cmapi-{name}`, the constant it was decided under.
- `groupOfNames` requires a member, and every group has at least one. Every member is a test user, so no real person is in a cmapi group.

### The test users

Thirteen users `cmapi.<role>`, from [`test-identities.tsv`](../examples/cmapi-sso/ldap/test-identities.tsv), which also says what each one's token must hold. Each is an `inetOrgPerson`, `posixAccount` and `shadowAccount` directly under `ou=People`, since the realm's search scope is one level, with mail `<uid>@ephico2real.com`, `gidNumber` 1000, home `/home/<uid>` and `uidNumber` from 10100 (10007 is the highest in use, measured on 2026-11-06).

The realm on CRC reads these users and nobody else: `usersFilter` in `CMAPI_REALM_LDAP`, which `realm_sync.py` sets as `customUserSearchFilter`, is `(uid=cmapi.*)`. So a real person cannot sign in to it, and it holds no way to guess a real person's password. `expectUsers` fails the sync unless it read exactly 13. With no `usersFilter`, the realm reads everyone in `usersDn`.

`cmapi.approver-prod2` exists because a prod delete needs two. `cmapi.selfapprove` requests and approves prod, for the self-approval rule. `cmapi.noaccess` is in no group, and must get 403.

Passwords are `openssl rand -hex 24`, kept in Secret `cmapi-ldap-test-users` in namespace `cmapi`, one key per uid, and stored in LDAP only as a hash `slappasswd` makes in the pod. They travel on stdin, never on a command line, and neither a password nor a hash is printed.

### Running it

```sh
examples/cmapi-sso/ldap/apply-test-identities.sh                      # the groups, the users, the Secret. A second run changes nothing
examples/cmapi-sso/ldap/apply-test-identities.sh --remove-old-groups  # the ten groups these replace
```

On CRC these are steps 9 and 10 of [`docs/13`](13-crc-deployment.md). It uses the admin password already in the server's environment (ConfigMap `ldap-config`), through a 0600 file in the pod and `-y`, so it never leaves the pod or reaches a command line. Note that this password sits in a ConfigMap, not a Secret. `apply-groups.sh` adds the groups alone, for a site that brings its own users.

**It fails, and never warns,** unless, measured before and after:

- a digest of every other entry's name and non-password attributes under `ou=People` and `ou=Groups`, `memberOf` included, is unchanged;
- the members of `app-ssb-autobahnusers` are unchanged;
- no `cmapi.*` user matches OpenShift's login filter, `(&(uid=*)(memberOf=cn=app-ssb-autobahnusers,ou=Groups,dc=ephico2real,dc=com))`, and the filter finds someone, or finding no `cmapi.*` user would prove nothing;
- the bind user reads the 10 groups, their members and the 13 users, and sees no hash;
- each user signs in to LDAP with the Secret's password.

Before it writes, it also refuses a `uidNumber` another entry holds, and any entry with one of these names that it would not write itself, such as a real person in a new group.

### Removing them

- **The ten old groups.** `--remove-old-groups` deletes `cmapi-viewers`, `cmapi-requesters`, `cmapi-onboarding`, `cmapi-prod-approvers`, `cmapi-qa-leads`, `cmapi-uat-leads`, `cmapi-platform-leads`, `cmapi-platform-operators`, `cmapi-platform-admins` and `cmapi-auditors`, each by its full `dn`, from a list in the script. It takes no name from outside, refuses an old name that is not a `groupOfNames`, and refuses to start until every new group and test user is exactly what the first form writes. They were created on 2026-11-05 with real people as example members, and those people are otherwise untouched: if the server's `memberOf` overlay tracks `member`, they lose those values, which is the removal itself.
- **The test identities.** `--remove-test-identities` deletes the 10 groups and 13 users each by its full `dn`, then the Secret by name, and refuses, deleting none, if an entry at one of those names is not what the first form writes. `deploy/crc-rollback.sh` calls it. It restores nothing.

### Who else could see them

No other consumer picks these groups or users up, because each filters on its own names. Read on CRC on 2026-11-06:

| Consumer | Filter | Sees `app-cmapi-rbac-*` or `cmapi.*` |
|---|---|---|
| GroupSync `app-ocp-rbac-group-groupsync` | `cn=app-ocp-rbac-*` | No |
| GroupSync `bda-rbac-groupsync` | `cn=bda-rbac-*` | No |
| Keycloak realm `corp` | groups `cn=app-ocp-rbac-ocp-*`, users behind the gate | No |
| OpenShift's identity provider `ldap-local` | `(&(uid=*)(memberOf=cn=app-ssb-autobahnusers,...))` | No: no test user is in that group, and the script fails if one is |

A dedicated GroupSync may come later. Nothing mirrors these groups into OpenShift today.

### What is measured, and what is not

Not run on CRC: nothing in this section has been applied to the real server. [`deploy/tests/ldap-identities-test.sh`](../deploy/tests/ldap-identities-test.sh) runs the script against a real OpenLDAP of the server's image, `osixia/openldap:1.5.0`, with a stub `oc`, rules shaped as the server's ConfigMap `ldap-acls`, and the `memberOf` overlay both ways, since which way the server's is configured cannot be read from outside the pod. [`deploy/tests/realm-test.py`](../deploy/tests/realm-test.py) holds each user's token against the table on Keycloak 26.6.4, and shows that a person outside the filter cannot sign in. The server's own rules and overlay, RHBK, and `ldaps` through Keycloak's truststore are what the CRC run proves.

The previous groups' numbers, for the record, from 2026-11-05: 43 groups before and 53 after, the hash of every other group's name and members `f99c22d9fa25` before and after, a second run rc 0, and 0 OpenShift groups named `cmapi*`.

### The bind user

Realm `cmapi` binds as its own read-only user, `cmapi-ldap-bind` in `ou=TrustedApplications`, and borrows no other project's
credential. [`examples/cmapi-sso/ldap/apply-bind-user.sh`](../examples/cmapi-sso/ldap/apply-bind-user.sh) creates it.

**Status: created on 2026-11-05** by the coordinator with the owner's explicit permission, run twice (rc 0 both; #34, closed
with the measurements): `cn=cmapi-ldap-bind,ou=TrustedApplications,dc=ephico2real,dc=com` read `ou=People` and the ten
old `cmapi-*` groups, saw no password hash, cannot read `ou=TrustedApplications`, and a write fails (exit 50); the server's rules
are still five, two of them extended by the one `by dn=... read` line. Secret `cmapi-ldap-bind` (`bindDN`, `password`) is in
namespaces `cmapi` and `keycloak`. **Keycloak federating through this user is unproven**: no realm has been imported yet, and
no login through the federation has been tested. The script is tracked as executable since #86 (it was `100644`, so running
it by its path failed with rc 126; `sh <path>` worked).

The server's rules are exhaustive, so a user they do not name gets "No such object (32)", which looks like missing data. The
script adds the user to the rules for `ou=People` and `ou=Groups` only, as one atomic modify, then fails unless the user can
read those two and cannot read password hashes or `ou=TrustedApplications`, or write. Its password is generated, kept in
Secret `cmapi-ldap-bind` in namespaces `cmapi` and `keycloak`, and never appears on a command line.

### Employee IDs

Nobody in this directory has `employeeNumber`, which the realm file maps to `employee_id`. `instance.yaml` sets
`requireEmployeeId: true`, so a person's write would get 422 `identity-incomplete`. The people are not changed. On this
deployment, the `cmapi` realm's mapper reads `uidNumber` instead, which the test users have as `posixAccount` entries.
This is a value for this directory only. A real directory maps its real employee ID.

## Existing Kyverno

cmapi installs no Kyverno. When an instance's `policy` runs Kyverno in an environment (`enforce` or `audit`, docs/02 "Policy in one place", #213), each cluster of that environment runs Kyverno v1.20.0 or later, installed by the platform, so that the `policies.kyverno.io/v1` types of cmapi's bundle are admitted the way the API's CLI (pinned at v1.20.0 in `cmapi/Containerfile`) checks them at plan time. `GET /api/v1/admin/integrations` reports that version as `policy.kyvernoVersion`. An instance with `engine: none`, or every environment `off`, needs no Kyverno on its clusters and no kyverno binary in its image.

## Why Keycloak access stays inside cmapi

Decided on 2026-11-05: Keycloak access stays a module of `cmapi-core`, as `docs/01` and `docs/02` say. There is no separate
service for it.

- **Token checks stay in-process either way.** Local validation adds no network round trip, where introspection adds
  5 to 50 ms and makes the API depend on Keycloak being up ([Skycloak](https://skycloak.io/blog/keycloak-token-introspection-vs-local-validation/)).
  Short-lived access tokens narrow the revocation gap, and this design uses 5 minutes.
- **What would move is small.** Only the directory lookups could move: a few cached lookups an hour, and they keep working
  from the cache when Keycloak is down.
- **A split has to earn its cost.** Martin Fowler's [MonolithFirst](https://www.goodreads.com/author_blog_posts/8479044-bliki-monolithfirst)
  and the [microservice premium](https://www.infoq.com/news/2015/05/microservices-premium) say a service pays for itself only
  when complexity demands it, and `app-architect` says no microservices by default.
- **Least privilege is met without one.** The admin client holds `view-users` and `query-users` only. If that credential
  should not sit in the API pods, the calls can move to the worker behind the same port.

The searches found no source comparing a wrapper service with in-process admin calls. This rests on the general guidance
above and on this design's own numbers. Revisit it if several applications come to need the same directory data.

## Not covered here

The runbook that creates realm `cmapi` is [`docs/13-crc-deployment.md`](13-crc-deployment.md). It has not been run yet, so the
realm does not exist yet; `CRC-BUILD-STATUS.md` is the deployment record and `docs/08-code-status.md` says what the code holds.
