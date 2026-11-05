# Existing identity services on CRC

On this CRC, cmapi uses an **existing LDAP server** and an **existing Keycloak**. It installs neither. Both serve other
projects, so cmapi adds only what it owns, and changes nothing else on them.

Checked on 2026-11-05.

| Service | Where | cmapi adds | cmapi never touches |
|---|---|---|---|
| Existing Keycloak | Namespace `keycloak`, CR `keycloak`, `https://keycloak.apps-crc.testing`, RHBK operator | Realm `cmapi`, through one `KeycloakRealmImport` named `cmapi`, and the Secret `cmapi-realm-secrets` in the same namespace that holds the import's placeholders (generated client secrets, the same values as Secret `cmapi-keycloak` in `cmapi`) | The other realms, the `Keycloak` CR, its operator and database, the master admin credential |
| Existing LDAP server | Namespace `ldap-testing`, OpenLDAP, `openldap-service` on 389 and 636, base `dc=ephico2real,dc=com` | The ten `cmapi-*` groups in `ou=Groups` | Other groups, every person in `ou=People`, `ou=TrustedApplications` |

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

Defined in [`examples/cmapi-sso/ldap/cmapi-groups.ldif`](../examples/cmapi-sso/ldap/cmapi-groups.ldif), and applied by
[`examples/cmapi-sso/ldap/apply-groups.sh`](../examples/cmapi-sso/ldap/apply-groups.sh). The names come from the roles table
in [`02-technical-design-v2.md`](02-technical-design-v2.md) and the approving groups in `approval-rules.yaml`.

| LDAP group | Role in cmapi | Example member |
|---|---|---|
| `cmapi-viewers` | `cmapi-viewer` | charlie.brown |
| `cmapi-requesters` | `cmapi-requester` | john.doe, jane.smith |
| `cmapi-onboarding` | `cmapi-onboarding` | charlie.brown |
| `cmapi-prod-approvers` | `cmapi-approver`; approves prod | jane.smith |
| `cmapi-qa-leads` | `cmapi-approver`; approves qa | bob.wilson |
| `cmapi-uat-leads` | `cmapi-approver`; approves uat | bob.wilson |
| `cmapi-platform-leads` | `cmapi-approver`; thresholds and sensitive changes | bob.wilson |
| `cmapi-platform-operators` | `cmapi-operator`, `cmapi-approver` | alice.cooper |
| `cmapi-platform-admins` | `cmapi-admin` | alice.cooper |
| `cmapi-auditors` | `cmapi-auditor` | charlie.brown |

- The design writes `cmapi-{team}-viewers` and `cmapi-{team}-requesters` as typical names. Access is by role with no team
  scoping, so one group per role is enough here, and the realm file already names `cmapi-requesters`.
- `groupOfNames` requires a member, so each group has an example person already in the directory. They are examples.
- jane.smith is in both `cmapi-requesters` and `cmapi-prod-approvers`, which lets a test show the self-approval rule.
- A token carries these as `/cmapi/cmapi-<name>` (`authz.GROUP_PATH`). The realm's LDAP group mapper has to filter on
  `(cn=cmapi-*)` and place them under `/cmapi`.

### Running it

```sh
examples/cmapi-sso/ldap/apply-groups.sh
```

A second run changes nothing. The script uses the admin password already in the server's environment (ConfigMap
`ldap-config`), so the password never leaves the pod. Note that this password sits in a ConfigMap, not a Secret.

### What the change affected

| Check | Result |
|---|---|
| Groups in `ou=Groups` | 43 before, 53 after |
| Hash of every other group's name and members | `f99c22d9fa25` before and after |
| A second run | Exit 0, no change |
| OpenShift groups named `cmapi*` | 0 |

No other consumer picks these groups up, because each filters on its own names:

| Consumer | Filter |
|---|---|
| GroupSync `app-ocp-rbac-group-groupsync` | `cn=app-ocp-rbac-*` |
| GroupSync `bda-rbac-groupsync` | `cn=bda-rbac-*` |
| Keycloak realm `corp` | `cn=app-ocp-rbac-ocp-*` |

### Removing them

Delete only the entries named in the LDIF, each by its full `dn`.

### The bind user

Realm `cmapi` binds as its own read-only user, `cmapi-ldap-bind` in `ou=TrustedApplications`, and borrows no other project's
credential. [`examples/cmapi-sso/ldap/apply-bind-user.sh`](../examples/cmapi-sso/ldap/apply-bind-user.sh) creates it.

**Status: not created.** The Claude Code auto mode classifier refused the script twice, as a change to a shared resource. See
issue #34. Until it runs, LDAP federation is unproven.

The server's rules are exhaustive, so a user they do not name gets "No such object (32)", which looks like missing data. The
script adds the user to the rules for `ou=People` and `ou=Groups` only, as one atomic modify, then fails unless the user can
read those two and cannot read password hashes or `ou=TrustedApplications`, or write. Its password is generated, kept in
Secret `cmapi-ldap-bind` in namespaces `cmapi` and `keycloak`, and never appears on a command line.

### Employee IDs

Nobody in this directory has `employeeNumber`, which the realm file maps to `employee_id`. `instance.yaml` sets
`requireEmployeeId: true`, so a person's write would get 422 `identity-incomplete`. The people are not changed. On this
deployment, the `cmapi` realm's mapper reads `uidNumber` instead, which the example people have as `posixAccount` entries.
This is a value for this directory only. A real directory maps its real employee ID.

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

Realm `cmapi` is created by the build, not by this page. `docs/08-code-status.md` and `CRC-BUILD-STATUS.md` say what exists.
