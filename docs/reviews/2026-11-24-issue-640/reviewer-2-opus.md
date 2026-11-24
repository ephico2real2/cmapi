# PR #659 (closes #640): reviewer 2 report

Reviewer 2 was Opus 5.5 at `high`, on 2026-11-24. I did not write the change or reviewer 1's review. Everything ran in the
export `review-659/` on this Mac. No git repository, GitHub or cluster was touched, and no Keycloak was started (see the
ruling on finding 3 for why none was needed). Database: `cmapi_r2_659` only.

## Result

| # | Finding | Reviewer 1 | Ruling | Decided by |
|---|---|---|---|---|
| 1 | `realm_sync.main` has no test | Medium | **Accepted** | Mutant M3a survives the PR's 28 tests and is killed by reviewer 1's test (6 failed) |
| 2 | `split_issuer` accepts non-issuers | Low | **Accepted, with a gap closed** | 16 cases of reviewer 1 fail on head; my 3 cases fail on reviewer 1's fix |
| 3 | A realm `.` or `..` leaves the realm's path | Low | **Accepted** | 6 cases fail on head; httpx sends `..` as `/admin/users` (measured) |
| R2-1 | Finding 2's fix accepts a query or fragment *before* the last `/realms/`, and the directory then sends its client secret to another realm's path | (missed) | **New, Low** | 3 cases fail on reviewer 1's fix and pass with mine; mutant R1 survives reviewer 1's 62 tests |

The patch is `r2-outputs/fix.diff` (353 lines). It is reviewer 1's `fix.diff` with my changes on top, built as one patch
against `head/` from `cmapi/` and `docs/` only. It applies to a fresh copy of `head/` with `patch -p1 -F0`, and the
patched copy equals `r2/` (`diff -r`, bytecode excluded). It changes four files:

- `cmapi/src/cmapi/core/identity/keycloak_admin.py`
- `cmapi/tests/service/test_keycloak_realm_in_url_path_640.py`
- `docs/18-configuration.md`
- `docs/reviews/2026-11-24-issue-640/README.md`

## Sources, fetched 2026-11-24

Saved in `r2-outputs/sources/`. Each file I fetched is byte for byte the same as reviewer 1's copy (`cmp`): RFC 3986,
7519 and 9068, OIDC Discovery, and Keycloak 26.6.4's `Urls.java`, `ReservedCharValidator.java`, `RealmManager.java` and
`RealmAdminResource.java`. I read each quote in its source. **Every quote reviewer 1 relies on is there as written, and
none is refuted.**

| Source | Where | Sentence, as read |
|---|---|---|
| RFC 3986 §2.4 | https://www.rfc-editor.org/rfc/rfc3986.txt | "Implementations must not percent-encode or decode the same string more than once" |
| RFC 3986 §3.3 | same | `segment = *pchar`; `pchar = unreserved / pct-encoded / sub-delims / ":" / "@"`; "The path segments "." and "..", also known as dot-segments, are defined for relative reference within the path name hierarchy" |
| RFC 3986 §5.2.4 | same | "a "remove_dot_segments" routine for interpreting and removing the special "." and ".." complete path segments from a referenced path" |
| RFC 3986 §2.1 | same | `pct-encoded = "%" HEXDIG HEXDIG`; "If two URIs differ only in the case of hexadecimal digits used in percent-encoded octets, they are equivalent." |
| OIDC Discovery 1.0 §3 | https://openid.net/specs/openid-connect-discovery-1_0.html | `issuer`: "URL using the https scheme with no query or fragment components that the OP asserts as its Issuer Identifier. ... This also MUST be identical to the iss Claim value in ID Tokens issued from this Issuer." |
| OIDC Discovery 1.0 §4.3 | same | "The issuer value returned MUST be identical to the Issuer URL that was used as the prefix to /.well-known/openid-configuration" |
| OIDC Discovery 1.0 §4 | same | "If the Issuer value contains a path component, any terminating / MUST be removed before appending /.well-known/openid-configuration." (So a generic OIDC issuer may end in `/`. Keycloak's never does; see `Urls.realmIssuer`.) |
| RFC 9068 §4 | https://www.rfc-editor.org/rfc/rfc9068.txt | "The issuer identifier for the authorization server (which is typically obtained during discovery) MUST exactly match the value of the "iss" claim." |
| RFC 7519 §2 (StringOrURI) | https://www.rfc-editor.org/rfc/rfc7519.txt | "StringOrURI values are compared as case-sensitive strings with no transformations or canonicalizations applied." |
| Keycloak 26.6.4 `Urls.java` | https://raw.githubusercontent.com/keycloak/keycloak/26.6.4/services/src/main/java/org/keycloak/services/Urls.java | l.166-167 `realmIssuer(URI baseUri, String realmName) { return realmBase(baseUri).path("{realm}").build(realmName).toString(); }`. No trailing `/` is appended |
| Keycloak 26.6.4 `ReservedCharValidator.java` | https://raw.githubusercontent.com/keycloak/keycloak/26.6.4/server-spi-private/src/main/java/org/keycloak/utils/ReservedCharValidator.java | `RESERVED_CHARS_PATTERN = Pattern.compile("[:/?#@!$&()*+,;=\\[\\]\\\\]")`. `/` is refused, so **a realm name cannot end with `/`**. `.` is not in the pattern |
| Keycloak 26.6.4 `RealmManager.java` | `.../services/managers/RealmManager.java` | `createRealm`: `ReservedCharValidator.validate(name)` (l.132). `importRealm`: `if (StringUtil.isBlank(rep.getRealm())) throw new ModelException("Realm name cannot be empty")` (l.586-587), a duplicate check, then `validate(rep.getRealm())` (l.598) |
| Keycloak 26.6.4 `RealmAdminResource.java` | `.../resources/admin/RealmAdminResource.java` | `updateRealm`: `ReservedCharValidator.validate(rep.getRealm())` (l.477) |
| Keycloak 26.6.4 `RealmsAdminResource.java` | `.../resources/admin/RealmsAdminResource.java` | `POST /admin/realms` calls `exportImportManager.importRealm(requestBody)`: no further name check |
| Keycloak hostname guide | https://www.keycloak.org/server/hostname | "your reverse proxy might expose Keycloak at a different context path ... `bin/kc.[sh|bat] start --hostname https://my.keycloak.org:123/auth`"; `hostname`: "Can be a full URL, or just a hostname" |
| Keycloak all-config | https://www.keycloak.org/server/all-config | `http-relative-path`: "Set the path relative to / for serving resources. The path must start with a /." |

**Can a Keycloak realm be named `.`, `..`, or end with `/`?** Ending with `/`: no. `ReservedCharValidator` refuses `/`
on create, import and update. Empty: no on import, which is the REST create path (`StringUtil.isBlank`). `.` and `..`: no
check in these four files refuses them. By the source, then, Keycloak can create them. **Not measured** on a running
Keycloak; the ruling below does not depend on it.

## Runs (test file `tests/service/test_keycloak_realm_in_url_path_640.py`)

`r2-outputs/04-runs-before-after.txt`:

| Tree | Result |
|---|---|
| head (the PR's 28 tests) | 28 passed |
| head source + reviewer 1's tests | 19 failed, 43 passed (reproduces reviewer 1's `05`) |
| head + reviewer 1's fix (`r2` before my changes) | 62 passed |
| head source + final tests | 22 failed, 43 passed |
| reviewer 1's source + final tests | **3 failed**, 62 passed: the three cases of R2-1 |
| final (`r2/`) | **65 passed** |

I also ran the suites around the change on the final tree. These are the 14 service files that use `keycloak_admin`,
`realm_sync`, `split_issuer`, `directory_client_secret` or `build_context` (the #640 file among them): **486 passed** in
454 s. `tests/core/test_identity_metadata.py`: **21 passed** (`r2-outputs/06-surrounding-suites-final.txt`).

## Rulings

### Finding 1 (Medium): `realm_sync.main` test: accepted

Mutant M3a puts `main` back to `issuer.rsplit("/realms/", 1)`. Then `Realm` encodes an already encoded segment, so the
Job sends `cmapi%2520640`. On the PR's 28 tests M3a **survives** (28 passed). On the final file it is **killed**
(6 failed) by `test_realm_sync_main_takes_the_realm_from_the_issuer` (`r2-outputs/05-mutants.txt`). The test kills a
named mutant that the PR's tests miss, so it stays. It also kills M3e (no `rstrip`, 4 failed), which pins reviewer 1's
open decision 2.

### Finding 2 (Low): refusing non-issuers at start: accepted, and it refuses no working deployment

Every issuer form cmapi documents or ships passes `split_issuer` on the final tree (`r2-outputs/02-probe-split-head-and-fable.txt`):

| Issuer | Where | Result |
|---|---|---|
| `https://keycloak.apps-crc.testing/realms/cmapi` | CRC: `deploy/environments/crc.yaml:19`, `deploy/manifests/environments/crc/20-config.yaml:24`, `docs/15` | accepted |
| `https://sso.ephico2real.com/realms/ephico2real` | chart default `deploy/helm/cmapi/values.yaml:63`, `examples/config/instance.yaml:12` | accepted |
| `https://keycloak.kind.invalid/realms/cmapi` | `deploy/manifests/environments/kind/20-config.yaml:19` | accepted |
| `http://localhost:8080/realms/ephico2real` | docs (local) | accepted |
| `https://sso.example.test/auth/realms/cmapi` | Keycloak with `http-relative-path=/auth` | accepted, base `.../auth` |
| `https://gw.example.test/idp/kc/realms/cmapi` | front door with a path prefix (`hostname` as a full URL with a path) | accepted, base `.../idp/kc` |
| `https://sso.example.test:8443/auth/realms/cmapi%20640` | port, prefix, encoded name | accepted, realm `cmapi 640` |

Every issuer in the tree was inventoried with a grep over `docs deploy cmapi examples cmapi-portal-ui/src README.md`.
Every real one has the form `<scheme>://<host>[:port]/realms/<plain name>`. `docs/18` and `docs/15` name no other
form. `deploy/secrets.sh:34` already accepts only `^https://[^/?#]+/realms/cmapi$` on CRC.

The issuers that are newly refused never worked: `Authenticator` compares `iss` with the configured issuer as written
(`core/auth.py:165`, PyJWT `payload["iss"] != issuer`), and nothing normalizes the issuer (grep: no `rstrip` in
`auth.py`, `context.py`, `settings.py` or `main.py`). Keycloak's `iss` comes from `Urls.realmIssuer`, which has no
trailing `/`, no query and no fragment. So with any of these issuers every token was already refused with 401 on main.
The refusal turns a broken instance into a start error that names the issuer.

### R2-1 (Low, missed by reviewer 1): a query or fragment before the last `/realms/`

Reviewer 1's rule checks only the text after the last `/realms/`. Its docstring and its `docs/18` row say "a query or a
fragment" is refused, but on reviewer 1's fix (`r2-outputs/03-probe-query-base-fable.txt`, raw targets on a local server):

```
'not-cmapi?x=/realms/cmapi'    realm 'cmapi', base '/realms/not-cmapi?x=': sent ['POST /realms/not-cmapi?x=/realms/cmapi/protocol/openid-connect/token'], then DirectoryUnavailable(token request failed: 405)
'not-cmapi#/realms/cmapi'      realm 'cmapi', base '/realms/not-cmapi#': sent ['POST /realms/not-cmapi'], then DirectoryUnavailable(token request failed: 405)
```

These are the bad issuers `deploy/secrets-test.sh:200` already uses. The directory's client-credentials POST goes to
another realm's path on the same host. OIDC Discovery §3 says the issuer has "no query or fragment components", so the
fix refuses `?` or `#` anywhere in the issuer. Fix, in `split_issuer`:

```python
    base, sep, segment = issuer.rpartition("/realms/")
    try:
        if not sep or "?" in issuer or "#" in issuer or not _SEGMENT.fullmatch(segment):
            raise ValueError("it is not <base>/realms/<realm> with no query or fragment, the realm one percent-encoded path "
                             "segment")
        realm = unquote(segment, errors="strict")           # UnicodeDecodeError is a ValueError
        realm_segment(realm)                                # refuses "", "." and ".."
    except ValueError as exc:
        raise ValueError(f"not a Keycloak issuer, {issuer!r}: {exc}") from exc
    return base, realm
```

The docstring now says the same:

```python
    Anything else raises ValueError, which names the issuer, when cmapi starts: a "?" or "#" anywhere, since an issuer has
    "no query or fragment components" (OpenID Connect Discovery 1.0, section 3), and after the last `/realms/` a trailing
    "/", a further path, a "%" that starts no encoded octet, octets that are not UTF-8, and the dot-segments "." and "..".
    None of them is an issuer Keycloak serves, and each would otherwise send requests to a path outside the realm."""
```

Tests: two cases in `test_split_issuer_refuses_what_names_no_realm`, and one in
`test_build_context_refuses_a_bad_issuer_at_start`:

```python
    "https://sso.example.test/realms/other?x=/realms/cmapi",   # a query or fragment before the last /realms/ too
    "https://sso.example.test/realms/other#/realms/cmapi",     # (deploy/secrets-test.sh refuses both)
...
@pytest.mark.parametrize("tail", ["cmapi/", "cmapi/account", "cmapi%20640?x=1", "..", "100%", "other?x=/realms/cmapi"])
```

All three fail on reviewer 1's source and pass on the final one. Mutant R1, which is reviewer 1's condition, survives
reviewer 1's 62 tests and is killed by the final 65 (3 failed). R2 (no `?` check) and R3 (no `#` check) are each killed.

### Finding 3 (Low): the `.`, `..` and empty guard: accepted

- Measured (`r2-outputs/01-probe-dots.txt`, httpx 0.28.1): `/admin/realms/../users` is sent as `/admin/users`, and
  `/admin/realms/./users` as `/admin/realms/users`. Reviewer 1's claim stands.
- Can Keycloak create such a realm? By the 26.6.4 source, yes for `.` and `..`, and no for an empty name (above). Not
  measured.
- The ruling does not need that answer, so I started no Keycloak. Even if such a realm exists, it cannot serve cmapi.
  cmapi's JWKS URL `<issuer>/protocol/openid-connect/certs` with issuer `.../realms/..` is sent as
  `/protocol/openid-connect/certs` (measured, same probe). No token could be verified, so no working deployment uses one.
- Over-build check (the owner's rule, "over-build only if it is the only solution"): does dropping the guard lose a
  guarantee? Yes. `realm_segment`'s contract is "a realm name as one URL path segment", and without the guard it breaks
  that contract for three inputs. No simpler form keeps it: `quote` cannot encode `.` (it is unreserved), and `%2E` is
  equivalent to `.` (RFC 3986 §2.3, §6.2.2.2). The guard is one `if`, it lives where the segment is built, and it costs
  nothing at run time.
- Mutants M13 (no dot refusal, 6 failed), R4 (`.` allowed, 2 failed) and M14 (`split_issuer` not calling
  `realm_segment`, 4 failed) are each killed.

### Reviewer 1's open decisions

1. **A bad issuer stops the start only when the Keycloak directory is on.** I recommend keeping this as it is. With the
   directory off, cmapi takes no realm out of the issuer. It uses the issuer only as written: the exact `iss` comparison,
   the default JWKS URL (which `CMAPI_OIDC_JWKS_URL` can replace) and the API document's sign-in URLs. In that mode it
   need not be Keycloak's `<base>/realms/<realm>` form, and an OIDC issuer may end in `/` (Discovery §4). Parsing it
   always would add a refusal outside #640 for instances that start today, such as kind (`keycloak.kind.invalid`,
   "the process starts"). I added one sentence to the `docs/18` row that says so.
2. **`realm_sync.main` still strips a trailing `/`.** I recommend keeping the strip. With it, the Job's requests are
   right, so dropping it would change behaviour with no defect to fix. The API's own start check and `deploy/secrets.sh`
   already refuse that issuer where it matters, and M3e shows that reviewer 1's test pins the strip.

## What reviewer 1 missed, besides R2-1

- **The PR's test-module docstring.** Reviewer 1 wrote that the sentence "a name stays one segment whatever it holds" is
  refuted by `.` and `..`, but left it in the file. It now names the three exceptions.
- **`docs/18` was incomplete.** The `instance.auth.issuer` row listed neither a fragment, nor octets that are not UTF-8,
  nor `.` and `..`, and said nothing of the directory-off case. The `CMAPI_KEYCLOAK_ADMIN_URL` row said "up to
  `/realms/`" where the code takes the last one. Both rows are corrected.
- **The review record.** It has a reviewer 2 section, including the statement that the realm-name checks are read from
  the source and were not tried on a running Keycloak.

## Mutants of the final fix (`r2-outputs/mutants.py`, `r2-outputs/05-mutants.txt`)

Against the PR's own 28 tests, three mutants survive: M3a (`main` back to `rsplit`), M6 (`partition`) and R1 (no
`?`/`#` check before the last `/realms/`). Against reviewer 1's 62 tests, R1 still survives. Against the final 65 tests,
**all 24 are killed**:

```
killed    M1 split_issuer: drop the unquote: 18 failed, 47 passed
killed    M2 realm_segment: safe='/': 3 failed, 62 passed
killed    M3a realm_sync.main: back to rsplit: 6 failed, 59 passed
killed    M3b Realm._bearer: no realm_segment: 6 failed, 59 passed
killed    M3c Realm.call: no realm_segment: 6 failed, 59 passed
killed    M3d wait_for_realm: no realm_segment: 6 failed, 59 passed
killed    M3e realm_sync.main: no rstrip: 4 failed, 61 passed
killed    M4 context.py: realm straight from the issuer (main's defect): 9 failed, 56 passed
killed    M5 unquote without errors='strict': 1 failed, 64 passed
killed    M6 partition, not rpartition: 2 failed, 63 passed
killed    M7 directory token request: no realm_segment: 5 failed, 60 passed
killed    M8 directory lookups: quote() default safe: 1 failed, 64 passed
killed    M9 decode twice: 4 failed, 61 passed
killed    M10 head's check only (no pattern, no ?/#): 14 failed, 51 passed
killed    M11 pattern: a lone '%' allowed: 3 failed, 62 passed
killed    M12 pattern: white space allowed: 1 failed, 64 passed
killed    M13 realm_segment: no dot refusal: 6 failed, 59 passed
killed    M14 split_issuer: realm_segment not called: 4 failed, 61 passed
killed    M15 context.py: iss compared with a decoded issuer: 3 failed, 62 passed
killed    R1 reviewer 1's check: no ?/# before the last /realms/: 3 failed, 62 passed
killed    R2 no '?' check: 2 failed, 63 passed
killed    R3 no '#' check: 1 failed, 64 passed
killed    R4 realm_segment: '.' allowed: 2 failed, 63 passed
killed    R5 error does not name the issuer: 21 failed, 44 passed
```

## Not tested

- No Keycloak was started. Whether 26.6.4 accepts a realm `.` or `..` was read from the source, not measured.
- CRC: nothing ran there. CRC's issuer is unchanged and accepted.
- The whole service suite was not run, as instructed. CI runs it.
- The portal and the chart were read, not run. Neither takes the realm out of the issuer: the portal passes the issuer to
  its OIDC library as `authority`, and the chart's front door takes only the scheme and host.

## Files

- `r2-outputs/fix.diff`: the one patch against `head/`.
- `r2-outputs/sources/`: what was fetched.
- `r2-outputs/01-probe-dots.txt`, `02-probe-split-head-and-fable.txt`, `03-probe-query-base-fable.txt`: wire and parser probes.
- `r2-outputs/04-runs-before-after.txt`, `05-mutants.txt`, `06-surrounding-suites-final.txt`: test runs.
- Scripts: `r2-outputs/run.sh`, `mutants.py`, `probe_dots.py`, `probe_split.py`, `probe_query_base.py`.
- `r2/`: head with the final patch applied. `r2-outputs/work/`: the trees used for the before and after runs and the
  mutants.
