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

## Review by reviewer 1 (Fable 5.2), 2026-11-24

Three findings, each with its fix and tests in this pull request. The sources above were fetched again and every quote
was found as written; `Urls.java`, `ReservedCharValidator.java` and `RealmManager.java` are byte for byte the same at the
tags 26.6.0 and 26.6.4.

1. **`realm_sync.main` had no test (Medium).** With `main` put back to `issuer.rsplit("/realms/", 1)` all 28 tests passed,
   and the Job would then send `cmapi%2520640`, since `Realm` now encodes. `test_realm_sync_main_takes_the_realm_from_the_issuer`
   runs `main` from its environment against the local server.
2. **`split_issuer` took what is not an issuer (Low).** `.../realms/cmapi/` gave the realm `cmapi/`, sent as `cmapi%2F`;
   a further path, a query, a fragment, a space and a `%` that starts no encoded octet were taken the same way, and the
   error for octets that are not UTF-8 did not name the issuer. The part after the last `/realms/` must now be one path
   segment (RFC 3986, section 3.3: `segment = *pchar`; section 2.1: `pct-encoded = "%" HEXDIG HEXDIG`), and `build_context`
   stops with `not a Keycloak issuer, '<the issuer>': <why>` before any request. `realm_sync.main` still drops a `/` at
   the end of `CMAPI_REALM_ISSUER` first, as before.
3. **A realm `.` or `..` left the realm's path (Low).** `quote` leaves both, and httpx removes a dot-segment (RFC 3986,
   section 5.2.4): the realm `..` was sent as `GET /admin/users`. `realm_segment` refuses `.`, `..` and an empty name. Not
   measured: whether Keycloak can create such a realm; `ReservedCharValidator` does not refuse a dot.

Confirmed, with tests that pass before and after: a token's `iss` is compared with the issuer as `instance.yaml` writes
it (`.../realms/cmapi%20640` is accepted; `.../realms/cmapi 640`, `.../realms/cmapi%2520640` and `.../realms/caf%c3%a9`
for `caf%C3%A9` are refused with 401), and the signing keys are read from `/realms/cmapi%20640/protocol/openid-connect/certs`.
For the realm `cmapi` every request is the same, byte for byte, on `5962830`, on this branch and with these fixes: request
line, headers and body of eight requests of the directory and of `realm_sync.main`, recorded by a local HTTP server.

The `partition` for `rpartition` mutant also survived the first 28 tests; `test_split_issuer_takes_the_last_realms_segment`
now covers a Keycloak path that holds `/realms/` itself.

## Review by reviewer 2 (Opus 5.5, high), 2026-11-24

Reviewer 2 fetched the sources again; each quote reviewer 1 relies on is in the source as written. All three findings are
accepted, and one gap in finding 2's fix is closed here.

- **A query or fragment before the last `/realms/` (Low).** Finding 2's rule looked only at the part after the last
  `/realms/`. `https://kc.test/realms/not-cmapi?x=/realms/cmapi` and `...not-cmapi#/realms/cmapi`, which
  `deploy/secrets-test.sh` already treats as bad issuers, were accepted as the realm `cmapi`, and the directory sent its
  client secret to `POST /realms/not-cmapi`. OpenID Connect Discovery 1.0, section 3, says an issuer has "no query or
  fragment components", so `split_issuer` now refuses a `?` or `#` anywhere in the issuer.
- **No working issuer is refused.** Every issuer in `deploy/`, the chart, `examples/` and `docs/` is accepted. So are
  Keycloak under `http-relative-path` (`/auth/realms/<realm>`) and Keycloak behind a front door with a path prefix (the
  `hostname` option takes a full URL with a path, <https://www.keycloak.org/server/hostname>). The issuers now refused
  never matched a Keycloak token's `iss`, because the comparison is exact.
- **The dot-segment guard stays.** At 26.6.4, `RealmManager.createRealm` and `importRealm` and
  `RealmAdminResource.updateRealm` check a realm's name for blankness (import), a duplicate and `ReservedCharValidator`'s
  characters, and none of those checks refuses `.` or `..`. A running Keycloak was not tried. A realm with that name
  cannot be an issuer anyway:
  httpx sends `.../realms/../protocol/openid-connect/certs` as `/protocol/openid-connect/certs`. The guard is one line and
  turns that into an error at start, and it keeps `realm_segment` true to its contract.
- **Reviewer 1's open decisions.** The issuer is still parsed only when the Keycloak directory is on, because with it off
  the issuer is used only as written. `realm_sync.main` still drops a trailing `/`: the Job's requests are right with it,
  and it behaves as it did on `5962830`.
- The test module's sentence "a name stays one segment whatever it holds" now names its three exceptions.

## Not tested

- CRC: nothing ran there. CRC's realm is `cmapi`, whose bytes do not change.
- A realm name with a character Keycloak refuses (`/`, `#`, `?`) was tested only against the local server, since Keycloak cannot
  create one.
- LDAP federation and the test-user step of realm-sync were off in the podman run; they build their paths through the same
  `Realm.call`.

## The coordinator's rulings and run

- **Rulings (Opus 5.5).** The coordinator accepts reviewer 1's findings 1 to 3 (Fable 5.2) and reviewer 2's R2-1 (Opus 5.5 high). The issuer `.../realms/x?y=/realms/cmapi` sent the client secret to another realm. Both reviewers' recommendations stand on the two open decisions:
  - the issuer is parsed only when the Keycloak directory is on;
  - `realm_sync` keeps stripping the trailing `/`.
- **How the change was put together.** Reviewer 2's patch was applied with `patch -p1 -F0`, and `main` was merged in. The coordinator read the two moved `realm_sync` citations before writing them.
- **The full service suite.** Database `cmapi_coord_659`, on the old pins, on the branch merged with `main` `b97ebb5`. It ran from 2026-11-24T20:48:33Z to 21:34:06Z: **2826 passed in 2718.41 s** (`coord-suite.txt`).
- **After merging #654 (FastAPI 0.162.2, Starlette 1.10.0).** The tests were run on the new pins: the identity, realm-sync, authz, HEAD and API-standard files gave **324 passed** (`merged-newpins.txt`). `doc-citations.py --check` reports 0 problems.
