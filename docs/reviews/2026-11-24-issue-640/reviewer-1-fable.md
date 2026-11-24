# PR #659 (closes #640): reviewer 1 report

Reviewer 1, adversarial, Fable 5.2, 2026-11-24. The change was written by Opus 5.5; I did not write it. Everything ran in
the export `review-659/` on this Mac: no git repository, GitHub or cluster was touched, and no Keycloak was started.

## Result

The change does what #640 needs. The realm is decoded once from the issuer and encoded once at each URL, the `iss`
comparison is untouched, and the realm `cmapi` sends the same bytes as on main. Three findings, none High. Each has its
full fix and tests in `r1-outputs/fix.diff` (304 lines, four files, applies to a fresh copy of `head/` with `patch -p1 -F0`).

| # | Finding | Level | Decided by |
|---|---|---|---|
| 1 | `realm_sync.main` has no test: put back to `rsplit`, all 28 tests pass and the Job would send `cmapi%2520640` | Medium | Mutant M3a survived (`03-mutants-head-tests.txt`) |
| 2 | `split_issuer` accepts what is not an issuer: a trailing `/`, a further path, a query, a fragment, a space, a stray `%`. The non-UTF-8 error does not name the issuer | Low | 16 new cases fail on head (`05-new-tests-on-head-source.txt`) |
| 3 | A realm `.` or `..` leaves the realm's path: `..` is sent as `GET /admin/users` | Low | 3 new cases fail on head; `04-probe-split-head.txt` |

Also added, passing before and after: tests for the `iss` comparison and the JWKS URL (claim 2), and for a Keycloak path
that itself holds `/realms/` (mutant M6, `partition` for `rpartition`, survived the PR's tests).

## Sources, fetched 2026-11-24

Saved in `r1-outputs/sources/`. Every quote in the implementer's record was found as written. Nothing in the record is
refuted by a source.

| Source | URL | Sentence |
|---|---|---|
| RFC 3986, 2.4 | https://www.rfc-editor.org/rfc/rfc3986.txt | "Once produced, a URI is always in its percent-encoded form." and "Implementations must not percent-encode or decode the same string more than once, as decoding an already decoded string might lead to misinterpreting a percent data octet as the beginning of a percent-encoding" |
| RFC 3986, 3.3 | same | `segment = *pchar`, `pchar = unreserved / pct-encoded / sub-delims / ":" / "@"`; "The path segments "." and "..", also known as dot-segments, are defined for relative reference within the path name hierarchy" |
| RFC 3986, 2.1 | same | `pct-encoded = "%" HEXDIG HEXDIG`; "If two URIs differ only in the case of hexadecimal digits used in percent-encoded octets, they are equivalent." |
| RFC 3986, 5.2.4 | same | the "remove_dot_segments" routine is "for interpreting and removing the special "." and ".." complete path segments from a referenced path" |
| OIDC Discovery 1.0, 3 | https://openid.net/specs/openid-connect-discovery-1_0.html | `issuer`: "URL using the https scheme with no query or fragment components that the OP asserts as its Issuer Identifier. ... This also MUST be identical to the iss Claim value in ID Tokens issued from this Issuer." |
| OIDC Discovery 1.0, 4.3 | same | "The issuer value returned MUST be identical to the Issuer URL that was used as the prefix to /.well-known/openid-configuration to retrieve the configuration information. This MUST also be identical to the iss Claim value in ID Tokens issued from this Issuer." |
| RFC 9068, 4 | https://www.rfc-editor.org/rfc/rfc9068.txt | "The issuer identifier for the authorization server (which is typically obtained during discovery) MUST exactly match the value of the "iss" claim." |
| RFC 7519, 2 and 4.1.1 | https://www.rfc-editor.org/rfc/rfc7519.txt | "StringOrURI values are compared as case-sensitive strings with no transformations or canonicalizations applied."; "The "iss" value is a case-sensitive string containing a StringOrURI value." |
| Keycloak 26.6.4 `Urls.java` | https://raw.githubusercontent.com/keycloak/keycloak/26.6.4/services/src/main/java/org/keycloak/services/Urls.java | line 166: `public static String realmIssuer(URI baseUri, String realmName) { return realmBase(baseUri).path("{realm}").build(realmName).toString(); }` |
| Jakarta REST `UriBuilder` | https://jakartaee.github.io/rest/apidocs/3.0.0/jakarta/ws/rs/core/UriBuilder.html (and `UriBuilder.java` at tag 3.1.0) | "URI template names and delimiters are never encoded but their values are encoded when a URI is built"; `build(Object...)`: "All '%' characters in the stringified values will be encoded." and "By default all '/' characters in the stringified values will be encoded in path templates" |
| Keycloak 26.6.4 `ReservedCharValidator.java` | https://raw.githubusercontent.com/keycloak/keycloak/26.6.4/server-spi-private/src/main/java/org/keycloak/utils/ReservedCharValidator.java | `RESERVED_CHARS_PATTERN = Pattern.compile("[:/?#@!$&()*+,;=\\[\\]\\\\]")` |
| Keycloak 26.6.4 `RealmManager.java`, `RealmAdminResource.java` | same repository and tag, `services/src/main/java/org/keycloak/services/managers/RealmManager.java`, `.../resources/admin/RealmAdminResource.java` | `ReservedCharValidator.validate(name)` in `createRealm` (line 132), `validate(rep.getRealm())` in `importRealm` (line 598) and in the realm update (`RealmAdminResource` line 477) |
| Keycloak 26.6.4, where `iss` comes from | `.../protocol/oidc/grants/ClientCredentialsGrantType.java` line 107, `.../endpoints/AuthorizationEndpoint.java` line 341, `.../OIDCWellKnownProvider.java` line 117 | each calls `Urls.realmIssuer(..., realm.getName())`: the token's `iss` and the discovery `issuer` are built by the same function |

What I add to the record:

- The record cites the tag 26.6.0 and the proof ran 26.6.4. `Urls.java`, `ReservedCharValidator.java` and
  `RealmManager.java` are byte for byte the same at both tags (`cmp`).
- The record lists `createRealm` and `importRealm`. The realm update (a rename) validates the name too.
- The implementer's retraction stands: on main the token request sent the issuer's own segment, which was right
  (`proof-before-and-after.log` line 34, `POST /realms/cmapi%20640/protocol/openid-connect/token -> 200`).
- One statement in the PR's test file is refuted: "a name stays one segment whatever it holds". The names `.` and `..`
  do not (finding 3).
- A note on "21 failed, 7 passed" on main, which I reproduced (`02-base-640.txt`). Ten of the 21 are `AttributeError`
  (no `split_issuer`), and the four realm-sync failures come from the test giving `Realm` the name where main's `main`
  gave it the segment. They do not show a wire defect in main's realm-sync, which agrees with the record.

## The five claims

### 1. One encode, one decode, everywhere: confirmed

Every place in `cmapi/src` where a realm or the issuer goes into a URL:

| Place | What goes in | Verdict |
|---|---|---|
| `core/context.py:150` | `split_issuer(issuer)`: the one decode for the API and the worker | Once |
| `core/identity/keycloak_admin.py:60`, `:75` | `realm_segment(self.realm)`: token request and user lookups | Once |
| `tools/realm_sync.py:340` | `split_issuer(issuer)`: the one decode for the Job | Once, but untested (finding 1) |
| `tools/realm_sync.py:80`, `:91`, `:105` | `realm_segment(...)`: sign-in, every admin call, the wait | Once |
| `core/context.py:85`, the JWKS URL | `f"{issuer}/protocol/openid-connect/certs"`: the issuer as written | Never decoded, never encoded. Measured: `GET /realms/cmapi%20640/protocol/openid-connect/certs` |
| `core/context.py:87`, `core/auth.py:165` | `Authenticator(issuer, ...)`, PyJWT `issuer=self.issuer` | The issuer as written (claim 2) |
| `core/auth.py:192-193`, Swagger's OAuth URLs | `f"{issuer}/protocol/openid-connect/auth"` and `/token` | The issuer as written (by reading) |
| `routers/health.py:60`, `main.py:181` | the issuer as text | Not a URL use |

Outside `cmapi/src`, by reading: the portal passes `config.issuer` to its OIDC library as `authority`
(`cmapi-portal-ui/src/portal/auth.ts:94`); the chart's front door takes only the scheme and host
(`deploy/helm/cmapi/templates/portal.yaml:10`, `:68`); the chart gives the Job `auth.issuer` unchanged
(`templates/jobs.yaml:78`). `deploy/secrets.sh:34` accepts only `/realms/cmapi`. None takes the realm out of the issuer.
The other paths in `realm_sync` hold only Keycloak's own IDs.

### 2. The issuer comparison stays exact: confirmed

`test_a_tokens_iss_is_compared_with_the_issuer_as_written` builds the context from `instance.yaml` with the issuer
`<base>/realms/cmapi%20640` and a real JWKS endpoint. A token with that `iss` is accepted. Tokens with
`.../realms/cmapi 640`, `.../realms/cmapi%2520640`, the issuer plus `/`, and `caf%c3%a9` for `caf%C3%A9` are each refused
with 401 "Token issuer is not trusted". It passes on head and with the fix. Mutant M15 (compare with a decoded issuer)
fails it. PyJWT 2.10.1 compares with `payload["iss"] != issuer` (`jwt/api_jwt.py:423`).

### 3. `split_issuer` refusals

| Issuer | On head | With the fix |
|---|---|---|
| No `/realms/` | `ValueError` at start | Same, and the message says why |
| Trailing `/` | Accepted: realm `cmapi/`, sent as `cmapi%2F` | Refused at start. `realm_sync.main` still drops the `/` first, as on main |
| Two `/realms/` | The last one is the realm: `.../realms/realms/realms` gives base `.../realms`, realm `realms`. Right for a Keycloak under `http-relative-path` | Same, now tested |
| A segment with `%2F` | Accepted: name `a/b`, sent again as `a%2Fb` | Same. Not a defect: it goes out as it came in, and Keycloak cannot create the realm |
| Not UTF-8 after decoding | `UnicodeDecodeError` at start, which does not name the issuer | `ValueError` at start, naming the issuer |

A bad issuer stops the start: `build_context` raises before `create_app` returns. That holds only when the Keycloak
directory is on (`identity.directory: keycloak` and `CMAPI_DIRECTORY_CLIENT_SECRET` set), on main as on head. With the
directory off the issuer is not parsed, and a wrong one shows as 401 on every token. I left that alone: it is outside
#640, and parsing it always would be a new refusal for instances that run today.

### 4. Tests on real bytes: confirmed, with one gap

The tests read `self.path` of a `http.server` handler behind a real socket, sent by httpx: the raw request target.

- On main's source: 21 failed, 7 passed. On head: 28 passed.
- Mutants against the PR's 28 tests (`03-mutants-head-tests.txt`): drop the `unquote`, killed (10 failed); `safe="/"`,
  killed (3); `Realm._bearer`, `Realm.call` and `wait_for_realm` unconverted, each killed (4); `context.py` back to main,
  killed (3). **Survived: `realm_sync.main` back to `rsplit`, and `partition` for `rpartition`.**
- With the fix, 19 mutants against the 62 tests, all killed (`06-mutants-fixed.txt`).

### 5. No change for the realm `cmapi`: confirmed

`capture_cmapi.py` records each request whole (request line, headers, body) on a local server: the directory's sign-in
and three lookups, then `realm_sync.main`'s wait, sign-in, a GET and a PUT. The eight requests are identical on main, on
head and with the fix (`07-bytes-realm-cmapi-*.txt`, one SHA-256: `d3616604…3435d`). The values in those files that look
like secrets are fixed test strings.

## Findings and fixes

All code is in `r1-outputs/fix.diff`. The source change is one file, `cmapi/src/cmapi/core/identity/keycloak_admin.py`:

```python
# One path segment of a URI that is not empty: no "/", "?" or "#", which end a segment (RFC 3986, section 3.3), no white
# space, and "%" only as the start of a percent-encoded octet (section 2.1: pct-encoded = "%" HEXDIG HEXDIG).
_SEGMENT = re.compile(r"(?:[^/?#%\s]|%[0-9A-Fa-f]{2})+")


def split_issuer(issuer: str) -> tuple[str, str]:
    base, sep, segment = issuer.rpartition("/realms/")
    try:
        if not sep or not _SEGMENT.fullmatch(segment):
            raise ValueError("it is not <base>/realms/<realm>, with the realm as one percent-encoded path segment")
        realm = unquote(segment, errors="strict")           # UnicodeDecodeError is a ValueError
        realm_segment(realm)
    except ValueError as exc:
        raise ValueError(f"not a Keycloak issuer, {issuer!r}: {exc}") from exc
    return base, realm


def realm_segment(realm: str) -> str:
    if realm in ("", ".", ".."):
        raise ValueError(f"not a realm name that can be one URL path segment: {realm!r}")
    return quote(realm, safe="")
```

(The docstrings are in the patch.)

### Finding 1 (Medium): `realm_sync.main` is not tested

The PR's realm-sync test calls `wait_for_realm` and `Realm` with the name. Nothing runs `main`, where the name is taken
from the issuer. With `main` put back to `issuer.rsplit("/realms/", 1)`, all 28 tests pass, and the Job would send
`/realms/cmapi%2520640`, because `Realm` now encodes. Main did not have that defect, so this line is the one place where
the PR can regress realm-sync unseen.

Fix: `test_realm_sync_main_takes_the_realm_from_the_issuer`, eight cases. It runs `main` from its environment against the
local server, with the steps replaced by one admin call, and asserts the three raw targets and the last printed line
(`realm cmapi 640 at <base>: in sync`). Four cases give the issuer a trailing `/`, which `main` drops as before. It passes
on head (the code is right) and fails on the mutant (6 failed).

### Finding 2 (Low): `split_issuer` accepts what is not an issuer

On head (`04-probe-split-head.txt`):

- `.../realms/cmapi/` gives the realm `cmapi/`, sent as `/admin/realms/cmapi%2F/users`.
- `.../realms/cmapi/extra`, `cmapi?x=1` and `cmapi#f` become the names `cmapi/extra`, `cmapi?x=1`, `cmapi#f`.
- `.../realms/100%` and `a%zzb` are kept as names, since `unquote` leaves a `%` that starts no octet.
- `.../realms/caf%E9` raises `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9`, with no word about the issuer.

None is an issuer Keycloak serves, and none can equal a token's `iss`, so the instance is broken either way. The fix
makes it say so at start: `not a Keycloak issuer, '<the issuer>': <why>`. The rule is RFC 3986's, not Keycloak's
validator: one segment that is not empty, with `%` only before two hexadecimal digits. Characters outside ASCII are
still allowed as written. White space is refused: a URI has none, and Keycloak was measured to write a space as `%20`.

Tests: `test_split_issuer_refuses_what_names_no_realm` (13 cases; 11 fail on head, the non-UTF-8 one on the message) and
`test_build_context_refuses_a_bad_issuer_at_start` (5 cases, all fail on head; each also asserts that no request was
sent).

### Finding 3 (Low): the realm `.` or `..` leaves the realm's path

`quote("..", safe="")` is `..`, and httpx removes dot-segments: the realm `..` is sent as `GET /admin/users`, and `.` as
`GET /admin/realms/users`. Fix: `realm_segment` refuses `.`, `..` and an empty name, and `split_issuer` calls it, so the
refusal comes at start. Test: `test_a_dot_segment_is_not_sent_as_a_realm` (3 cases, all fail on head), which also asserts
that the directory and `Realm` send nothing. Not measured: whether Keycloak can create such a realm.
`ReservedCharValidator` does not refuse a dot.

### Not a finding: `partition` for `rpartition` survived

`test_split_issuer_takes_the_last_realms_segment` (4 cases) covers a base path that holds `/realms/`, and lower-case
hexadecimal digits. It passes on head and kills the mutant.

### Docs in the patch

- `docs/18-configuration.md`, the `instance.auth.issuer` row: the form of the issuer and what stops the start.
- `docs/reviews/2026-11-24-issue-640/README.md`: a section for this review.

## Runs

| Run | Result | File |
|---|---|---|
| PR's test file on head | 28 passed | `01-head-640.txt` |
| PR's test file on main's source | 21 failed, 7 passed | `02-base-640.txt` |
| Mutants, PR's tests | 11 killed, 2 survived | `03-mutants-head-tests.txt` |
| Extended test file on head's source | 19 failed, 43 passed | `05-new-tests-on-head-source.txt` |
| Mutants, extended tests, with the fix | 19 killed, 0 survived | `06-mutants-fixed.txt` |
| Realm `cmapi`, whole requests, main, head, fixed | identical | `07-bytes-realm-cmapi-*.txt` |
| Surrounding suites on a fresh copy of head with `fix.diff` applied | 487 passed in 11 service files (the extended #640 file, 62 tests, among them), and 21 passed in `tests/core/test_identity_metadata.py` | `08-suites-on-patched-head.txt` |

Database: `cmapi_r1_659` only. Scripts: `run.sh`, `mutants.py`, `mutants_fixed.py`, `probe_split.py`, `capture_cmapi.py`.

## Not tested

- No Keycloak was started: no finding needed one. So nothing here was measured on a real Keycloak beyond the
  implementer's log.
- That a real Keycloak token carries `iss` `.../realms/cmapi%20640`. The implementer's log shows the discovery `issuer`
  only. The source says both come from `Urls.realmIssuer`.
- Whether Keycloak answers 404 for `/realms/cmapi%2F/...`, and whether it can create a realm named `.` or `..`.
- CRC: nothing ran there.
- The whole service suite: not run, as instructed.
- The portal and the chart with an encoded issuer: read, not run.
