# #640: the Keycloak realm in a URL path, decoded once and encoded once

Part of #481. Found by reviewer 2 of PR #639 (#638). Implemented by Opus 5.5 at `high`, 2026-11-24.

## What was wrong, measured

On a disposable Keycloak 26.6.4 in podman (`quay.io/keycloak/keycloak@sha256:0aae0de7…`, the digest `deploy/tests/realm-test.py`
pins), never the shared Keycloak on CRC. Full output: [`proof-before-and-after.log`](proof-before-and-after.log), made by
[`proof/proof.sh`](proof/proof.sh).

- Keycloak serves the realm `cmapi 640` with the issuer `…/realms/cmapi%20640`, and `pct%41é` with `…/realms/pct%2541%C3%A9`.
- `core/context.py` took the issuer's last segment as the realm, still encoded. The token request put it in the path unchanged,
  which is the right bytes (`POST /realms/cmapi%20640/protocol/openid-connect/token -> 200`). The user lookups encoded it a second
  time: `GET /admin/realms/cmapi%2520640/users?... -> 404`. `_users` reads a 404 as "no such user", so `get_user`,
  `find_by_employee_id` and `search` returned `None`, `None` and `[]` with no error.
- `tools/realm_sync.py` put the issuer's segment unchanged into every path, so its requests were right on the wire. It printed the
  encoded segment as the realm's name (`realm cmapi%20640 at …: in sync`).
- The realm `cmapi` needs no encoding, so CRC is not affected today.

**Retraction.** The issue says the token request "does not encode it at all". The measurement refutes that as a defect: the token
request sends the issuer's segment as it is, and that segment is already encoded, so its bytes were right. The defect was only the
second encoding in the user lookups. Realm-sync had no wire defect.

## The fix

- `keycloak_admin.split_issuer(issuer)` returns `(base, realm name)`. It decodes the segment once, with `unquote(..., errors="strict")`,
  and refuses an issuer with no realm segment or a segment that is not UTF-8.
- `keycloak_admin.realm_segment(name)` encodes the name once, with `quote(name, safe="")`, so a "/" is `%2F` too.
- Every place a realm goes into a URL path uses them: `KeycloakAdminDirectory` (token request and user lookups), `core/context.py`,
  and `realm_sync` (`main`, `wait_for_realm`, `Realm._bearer`, `Realm.call`). A realm name is now always the decoded name inside
  cmapi, and the encoding happens only where a URL is built.

Other places that name a realm in a URL were checked and left alone. `deploy/crc-guard.py` and `deploy/tests/realm-test.py` use fixed
realm names that need no encoding. `deploy/oidc-login.py` and the JWKS URL use the whole issuer as a URL and never take the realm out.

## Sources, read 2026-11-24

- RFC 3986, section 2.4, <https://www.rfc-editor.org/rfc/rfc3986#section-2.4>: "Once produced, a URI is always in its
  percent-encoded form", and "Implementations must not percent-encode or decode the same string more than once". Section 3.3:
  `segment = *pchar`.
- OpenID Connect Discovery 1.0, <https://openid.net/specs/openid-connect-discovery-1_0.html>. Section 3, `issuer`: "URL using the
  https scheme with no query or fragment components that the OP asserts as its Issuer Identifier". Section 4.3: "The issuer value
  returned MUST be identical to the Issuer URL that was used as the prefix". So the issuer is a URL, and its realm segment is a URL
  part, not the realm's name.
- Keycloak 26.6.0, `services/src/main/java/org/keycloak/services/Urls.java`,
  <https://github.com/keycloak/keycloak/blob/26.6.0/services/src/main/java/org/keycloak/services/Urls.java>:
  `realmIssuer` is `realmBase(baseUri).path("{realm}").build(realmName).toString()`, and `tokenEndpoint` builds
  `{realm}/protocol/openid-connect/token` the same way.
- Jakarta REST 3.0 `UriBuilder`, <https://jakartaee.github.io/rest/apidocs/3.0.0/jakarta/ws/rs/core/UriBuilder.html>: "URI template
  names and delimiters are never encoded but their values are encoded when a URI is built". `build(Object...)`: "All '%' characters
  in the stringified values will be encoded" and "By default all '/' characters in the stringified values will be encoded in path
  templates".
- Keycloak 26.6.0, `ReservedCharValidator`,
  <https://github.com/keycloak/keycloak/blob/26.6.0/server-spi-private/src/main/java/org/keycloak/utils/ReservedCharValidator.java>:
  `RESERVED_CHARS_PATTERN = Pattern.compile("[:/?#@!$&()*+,;=\\[\\]\\\\]")`. `RealmManager.createRealm` and `importRealm` call
  `ReservedCharValidator.validate` on the name
  (<https://github.com/keycloak/keycloak/blob/26.6.0/services/src/main/java/org/keycloak/services/managers/RealmManager.java>).
  So a realm name cannot hold `: / ? # @ ! $ & ( ) * + , ; = [ ] \`, and may hold a space, `%`, and any other character. The fix
  does not rely on that rule: `safe=""` keeps any name one segment.

## Options considered

1. **Decode once at the edge, encode once at each URL (chosen).** It matches RFC 3986, section 2.4, and keeps one meaning for
   "realm" in cmapi: the name, as Keycloak stores it and as its admin API decodes `{realm}`.
2. Drop the `quote` in `_users` and pass the issuer's segment everywhere. It would fix the bytes, but cmapi would then carry a
   URL fragment named "realm", print it as the name, and a caller that passes a real name (tests, a future setting) would be
   wrong again. Rejected: it moves the symptom.
3. Take the realm from a separate setting. Rejected: a second source of truth that can disagree with the issuer that tokens are
   checked against.

## Tests

`cmapi/tests/service/test_keycloak_realm_in_url_path_640.py` asserts the raw request target that a real local HTTP server
received, for `cmapi`, `cmapi 640`, `pct%41`, `café`, `a/b`, `a#b` and `a?b`: through `KeycloakAdminDirectory` on the HTTP function
the API uses, through `build_context` from `instance.yaml`'s issuer, and through realm-sync's `wait_for_realm` and `Realm`.

- Before the fix, on `5962830`: 21 failed, 7 passed ([`tests-before-fix.txt`](tests-before-fix.txt)). The `build_context` cases
  for `cmapi 640`, `pct%41` and `café` fail on the double encoding Keycloak answered with 404.
- After the fix: the new file and the identity, realm-sync and URL-path files around it, 262 passed, and
  `tests/core/test_identity_metadata.py`, 21 passed ([`tests-after-fix.txt`](tests-after-fix.txt)). The whole service suite
  was not run here; CI runs it.

## Not tested

- CRC: nothing ran there. CRC's realm is `cmapi`, whose bytes do not change.
- A realm name with a character Keycloak refuses (`/`, `#`, `?`) was tested only against the local server, since Keycloak cannot
  create one.
- LDAP federation and the test-user step of realm-sync were off in the podman run; they build their paths through the same
  `Realm.call`.
