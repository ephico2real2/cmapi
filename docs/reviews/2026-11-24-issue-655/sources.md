# #655: the primary sources, fetched 2026-11-24

Each decision of #655 rests on the sentence quoted under it. Copies of the fetched pages are in the implementer's outputs
folder (`wt-655-outputs/sources/`), not in the repository.

## The advisories

- **The set on main's pins**, `pip-audit -s osv` (OSV, https://osv.dev) on a venv of `cmapi[test]` at main `5962830`:
  `outputs/advisories-main-pins.txt`. Every GHSA ID was then read with `gh api /advisories/<GHSA>` (the GitHub Advisory
  Database API): `outputs/ghsa-summary.txt`.
- **The chosen versions are in none**, by two databases (`outputs/advisories-chosen-versions.txt`):
  `POST https://api.osv.dev/v1/query` for `pyjwt 2.15.1` and `pytest 9.2.0` returns no vulnerability, and
  `gh api "/advisories?ecosystem=pip&affects=<name>@<version>"` returns none for both spellings of each name.
- **`gh api /advisories -f affects=` misses advisories filed under another capitalisation.** Measured on PyJWT 2.10.1:
  `affects=pyjwt@2.10.1` returns 8 advisories and `affects=PyJWT@2.10.1` returns 8 others; OSV returns all 16, and PYSEC-2025-183. This is why the
  CI job uses OSV through pip-audit and not that API.
- **PYSEC-2025-183 (CVE-2025-45768)** has no fix version. Its OSV record
  (https://api.osv.dev/v1/vulns/PYSEC-2025-183) says: "pyjwt v2.10.1 was discovered to contain weak encryption. NOTE: this is
  disputed by the Supplier because the key length is chosen by the application that uses the library", with the range
  `introduced 0, last_affected 2.10.1`. 2.15.1 is outside it, so no ignore entry is needed.

## PyJWT 2.10.1 to 2.15.1

https://raw.githubusercontent.com/jpadilla/pyjwt/2.15.1/CHANGELOG.rst. The entries that touch cmapi's use:

- 2.11.0: "Validate key against allowed types for Algorithm family"; "Add minimum key length validation for HMAC and RSA keys
  (CWE-326). Warns by default via `InsecureKeyLengthWarning`". cmapi verifies with the RSA public key object of a 2048-bit
  realm key, which passes both.
- 2.12.0: "Validate the crit (Critical) Header Parameter defined in RFC 7515 §4.1.11" (GHSA-752w-5fwx-jx9f).
- 2.13.0: "Reject empty HMAC keys outright"; "Reject non-`http(s)` URI schemes in `PyJWKClient`".
- 2.14.0: "Reject automatic redirects when `PyJWKClient` fetches a JWKS"; "Handle deeply nested and malformed JWS/JWK input
  without uncaught recursion errors or whole-set parsing failures"; "Enforce compact JWS encoding rules during decoding".
- 2.15.0: "Wrap recursion errors from deeply nested JWT payloads in `DecodeError` instead of exposing a raw `RecursionError`";
  "a key whose components have the wrong type raises `InvalidKeyError`".
- 2.15.1: "Accept trailing Base64URL `=` padding when decoding JWS segments".

None of them changes an API that cmapi calls (`jwt.get_unverified_header`, `jwt.decode` with a key object and
`algorithms=["RS256"]`, `jwt.PyJWK`, `jwt.algorithms.RSAAlgorithm.to_jwk` in the tests); the targeted tests pass unchanged.

## pytest 8.3.4 to 9.2.0

https://raw.githubusercontent.com/pytest-dev/pytest/9.2.0/doc/en/changelog.rst, "Removals and backward incompatible breaking
changes" of 8.4.0, 9.0.0, 9.1.0 and 9.2.0. The ones a suite can meet: "Tests will now fail, instead of raising a warning, if
they return any value other than None" (8.4.0); "PytestRemovedIn9Warning deprecation warnings are now errors by default"
(9.0.0); "The `indirect`, `ids` and `scope` arguments of `Metafunc.parametrize()` ... are now keyword-only" (9.2.0).
GHSA-6w46-j5rx-g56g ("pytest has vulnerable tmpdir handling") is fixed in 9.0.3.

## The standards

- RFC 7515, section 4.1.11 (https://www.rfc-editor.org/rfc/rfc7515#section-4.1.11): "If any of the listed extension Header
  Parameters are not understood and supported by the recipient, then the JWS is invalid."
- RFC 7517, section 5 (https://www.rfc-editor.org/rfc/rfc7517#section-5): "Implementations SHOULD ignore JWKs within a JWK Set
  that use "kty" (key type) values that are not understood by them, that are missing required members, or for which values
  are out of the supported ranges." (#656)

## The lock and the install

- pip, "Secure installs" (https://pip.pypa.io/en/stable/topics/secure-installs/): "Enable Hash-checking Mode, by passing
  --require-hashes" and "Disallow source distributions, by passing --only-binary :all:"; "Hashes are required for all
  dependencies"; "To be safe, install your project using pip and --no-deps."
- pip-tools README (https://github.com/jazzband/pip-tools), "Cross-environment usage": "users must execute `pip-compile` **on
  each Python environment separately** to generate a `requirements.txt` valid for each said environment."
- uv, "Resolution" (https://docs.astral.sh/uv/concepts/resolution/): "Universal resolution is also available in uv's pip
  interface, i.e., uv pip compile, with the --universal flag. The resulting requirements file will contain markers to
  indicate which platform each dependency is relevant for."
- uv, "Locking environments" (https://docs.astral.sh/uv/pip/compile/): "When using an output file, uv will consider the
  versions pinned in an existing output file. If a dependency is pinned it will not be upgraded on a subsequent compile run."
- uv, "Exporting a lockfile" (https://docs.astral.sh/uv/concepts/projects/export/): "In general, we recommend against using
  both a uv.lock and a requirements.txt file."
- uv, settings, `exclude-newer` (https://docs.astral.sh/uv/reference/settings/): "Accepts RFC 3339 timestamps ..., a
  "friendly" duration (e.g., 24 hours, 1 week, 30 days)". `cmapi/lock.sh` uses "14 days", the owner's two-week rule.
- PEP 751 (https://peps.python.org/pep-0751/), `pylock.toml`: Status "Final". pip 26.3's own help: "pylock.toml support is
  experimental", and the base image's pip is 24.2.

## The audit

- pip-audit README (https://github.com/pypa/pip-audit): exit code "`1`: One or more known vulnerabilities were found";
  `--strict`: "fail the entire audit if dependency collection fails on any dependency"; `-s osv` queries
  https://api.osv.dev/v1/query.
- OSV-Scanner (https://google.github.io/osv-scanner/): "provides an officially supported frontend to the OSV database that
  connects a project's list of dependencies with the vulnerabilities that affect them."
