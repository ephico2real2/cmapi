# PR #658 (#655, #656, #657): reviewer 1, Fable 5.2

Read 2026-11-24. Export: `review-658/` (`head/` is the PR head, `base/` is main `5962830`). Opus 5.5 wrote the change; I did
not. Every output named below is in `review-658/r1-outputs/`. The fixes are one patch, `r1-outputs/fix.diff`, which applies
to a fresh copy of `head/` with `patch -p1 -F0` and gives exactly the tree I tested (`build_diff.sh` proves both).

Nothing was built as an image and no cluster was used: the machine's load was 17 to 35 throughout. Tests ran on the
implementer's venvs (`wt-655-outputs/venv-old`: PyJWT 2.10.1, pytest 8.3.4; `venv-new`: 2.15.1, 9.2.0; Python 3.12.14, macOS).
`r1-outputs/fixed/` holds a throwaway `git init`, made only because `scripts/doc-citations.py` needs `git ls-files`.

## Verdict

The upgrade, the lock and the reach claims hold. Six findings, each fixed in `fix.diff` with a test that fails before and
passes after. With the patch: 86 targeted tests pass, 14 of 14 mutants of the #656 fix are killed, and 25 of 25 mutants of the
CI guard are killed (at the PR head 16 of the 21 that apply survive).

| # | Severity | Finding | Before | After |
|---|---|---|---|---|
| F1 | Medium | #656 is only partly fixed: a `kid` that is a list or object, an `alg` that is a list, and `alg: "none"` still fail the whole key set (503 for every token) | 7 new tests fail | pass |
| F2 | Medium | `audit.sh` reports an OSV outage as an advisory, on the first failed query, with no retry | exit 1, "FAILED" | 3 attempts, exit 3, "NOT AUDITED" |
| F3 | Medium | `ci-guard.py` does not check what its labels claim: most weakening mutants pass it | 16 of 21 survive | 0 of 25 survive |
| F4 | Low | The `jwks_key_skipped` log line can hold key material | 1 test fails | pass |
| F5 | Low | A private JWK in the set is loaded as a key; a token of that kid is an `AttributeError` (HTTP 500). Predates the PR | 1 test fails | pass |
| F6 | Low | `audit.sh` installs set 1 without `--only-binary` on Linux, and leaves `cmapi/src/cmapi.egg-info` in the checkout | measured | gone |

Two notes on the record, not findings in code: the README's row for GHSA-8wjv-2p76-3863 (corrected in the patch), and the
implementer's "no kid" test case, which never reached the `KeyError` path (replaced in the patch).

## 1. The reach claims: confirmed

`claim1-old-2.10.1.txt`, `claim1-old-2.10.1-reasons.txt`, `claim1-new-2.15.1.txt`.

- On 2.10.1, `test_pyjwt_advisories_655.py`: 3 failed, 8 passed. The three: the unknown `crit` was accepted ("DID NOT
  RAISE"), and the nested header raised `RecursionError` out of `json/decoder.py`, in the direct call and through the
  FastAPI app. On 2.15.1: 11 passed.
- The eight guards (HS256 keyed with the public key in three forms, the decoder's key object and `["RS256"]`, no redirect,
  http and https only) pass on both versions, so those advisories did not reach cmapi's path. Confirmed.
- pip-audit against OSV (`audit-old.json`, `audit-new.json`): the old set has PyJWT 2.10.1 in 17 IDs (16 GHSA and
  PYSEC-2025-183), pytest 8.3.4 in 1, Starlette 0.41.3 in 7. The new set has only Starlette's 7. OSV returns nothing for
  pyjwt 2.15.1, pytest 9.2.0, pip 26.3 and setuptools 84.2.1, and 12 records (6 GHSA and their PYSEC twins) for pip 24.2 (#657).
- Each of the 22 GHSA records read with `gh api /advisories/<id>` (`sources/ghsa/`, `ghsa-r1-table.txt`): 2.15.1 and 9.2.0 are
  outside every range.

**A correction to the record.** GHSA-8wjv-2p76-3863's range is `>= 2.13.0, < 2.14.0`. 2.10.1 is not in it, and OSV does not
list it for 2.10.1. The header `RecursionError` on 2.10.1 is real (I reproduced it), but it is not that advisory by its
published range. The test file already says "the class of"; the README's table did not. Patched.

### The sources, each fetched and each quote found (`sources/`, 2026-11-24)

Every quote in `sources.md` is in the page I fetched myself: RFC 7515 §4.1.11 and RFC 7517 §5
(`https://www.rfc-editor.org/rfc/rfc7515.txt`, `.../rfc7517.txt`), pip "Secure installs" (four sentences), uv "Resolution",
"Locking environments" and `exclude-newer`, and pip-audit's README (exit code 1, `--strict`). Nothing in `sources.md` is
refuted. One sentence the implementer did not quote matters for the cooldown: uv compares "each individual distribution
artifact (i.e., when each file was uploaded to the package index), not the release date of the package version"
(`https://docs.astral.sh/uv/reference/settings/`).

PyJWT's changelog, 2.10.1 to 2.15.1 (`https://raw.githubusercontent.com/jpadilla/pyjwt/2.15.1/CHANGELOG.rst`), read in full.
cmapi calls `jwt.get_unverified_header`, `jwt.decode` with a key object and `algorithms=["RS256"]`, `jwt.PyJWK`, and in
`examples/local/app.py` `jwt.PyJWKClient`. The changes that could meet them, and why none breaks cmapi: "Validate key
against allowed types for Algorithm family" and the RSA key-length warning (2.11.0; an RSA public key object of 2048 bits),
"Validate `iss` claim is a string" (2.11.0), the `crit` check (2.12.0; intended), "Enforce compact JWS encoding rules"
(2.14.0) with "Accept trailing Base64URL `=` padding" (2.15.1), and "Reject automatic redirects when `PyJWKClient` fetches a
JWKS" (2.14.0; the example's Keycloak URL does not redirect). `test_auth.py` passes on 2.15.1 unchanged.

## 2. #656's skip

**Safe as far as it went (measured on the PR head).** A skipped member is in no dictionary, and `Jwks.key` looks up by kid
only. With the realm's key published broken beside a second good key, a token naming the broken kid is 401 "unknown signing
key" whether the realm's real key or the loaded key signed it, in both orders of the set. A good key and a bad member of the
same kid: the good one verifies, in both orders. A set of only bad keys is 503 `idp-unavailable`, and after a good fetch it
does not replace the keys held. These are new tests, and they pass on the head too.

### F1 (Medium): three shapes still fail the whole set

`probe_656-head-2.15.1.txt`: on PyJWT 2.15.1 a member whose `kid` is a list or an object, or whose `alg` is a list, raises
`TypeError: unhashable type`, and `alg: "none"` raises `NotImplementedError`. Neither is a `PyJWTError`, so they pass the
PR's `except (KeyError, jwt.PyJWTError)`, `_refresh` counts a failed refresh, and every token is 503: the defect of #656.
Also, on 2.10.1 three of the PR's own cases fail, because that version raises other types; the skip depended on the pin.

Fix (`cmapi/src/cmapi/core/auth.py`, F4 and F5 are in the same function):

```python
        keys: dict[str, jwt.PyJWK] = {}
        for k in raw:
            if not isinstance(k, dict) or k.get("use", "sig") != "sig" or k.get("kty") != "RSA":
                continue
            kid = k.get("kid")
            try:
                key = jwt.PyJWK(k)
                if not isinstance(kid, str) or not kid:
                    why = "kid is not a non-empty string"           # a token's kid is one (RFC 7515, section 4.1.4)
                elif not isinstance(key.key, RSAPublicKey):
                    why = "not a public key"                        # private parameters: PyJWT cannot verify with it
                else:
                    keys[kid] = key
                    continue
            except Exception as exc:                                # noqa: BLE001 - whatever PyJWT raises, the member is unusable
                why = type(exc).__name__
            JWKS_KEYS_SKIPPED.inc()
            # Never the exception's message: PyJWT's can print the member itself, with its key material.
            log.warning("jwks_key_skipped", kid=str(kid)[:100], error=why, members=sorted(str(m)[:20] for m in k)[:20])
        return keys
```

Catching every exception is safe here because a skip can only remove a key from the trusted set. One behaviour changes
beyond the stated purpose: a member whose `kid` is null or a number was loaded before (no token could name it, since PyJWT
requires a string `kid`), and is now skipped and counted.

Test: `test_jwks_skip_bad_key_656.py`, 31 tests. On the head's `auth.py`: 9 failed, 22 passed
(`f1-tests-before-head-auth.txt`). On the fix: 31 passed, on 2.15.1 and on 2.10.1 (`tests-after-fixed-on-2.10.1.txt`).

### F4 (Low): key material in the log

`probe_656b.txt`: PyJWT's "Unable to find an algorithm for key: {...}" prints the member, and the PR logs 200 characters of
it. For a public member that is the modulus, which is public. For a member that carries `d` first, the log held the private
exponent's first characters (measured). The fix logs the error's type, the kid and the member's parameter names.
`test_the_log_of_a_skipped_key_has_no_key_material` fails before and passes after. The counter has no label, so it holds nothing.

### F5 (Low, predates the PR): a private JWK in the set

`PyJWK` loads it as a private key object, and PyJWT's RS256 verify then raises `AttributeError` (measured on both versions),
which nothing catches. The fix skips a member that is not a public key. `test_a_member_with_private_parameters_is_skipped`.

### Mutants of the fix (`auth-mutants.txt`): 14 of 14 killed

The first run left one alive (`auth-mutants-run1-m9-survived.txt`: a skipped member takes the last loaded key under its
kid), because my isolation test had the bad key first only. The test now runs both orders, and the mutant dies.

## 3. The lock: confirmed

- **Platform.** The base image's metadata (`podman image inspect`, not run): `amd64`, `linux`, `PYTHON_VERSION=3.12`, UBI
  9.8, so glibc 2.34. `wheels_for_image.py` reads the lock, applies each marker for CPython 3.12 on linux x86_64, and checks
  PyPI's files: 37 packages install in the image, 2 are skipped by marker (colorama and tzdata, Windows only), and all 37
  have a wheel that fits with its SHA-256 in the lock (`wheels-for-image.txt`). 37 is also the count the implementer's run
  in the base image installed. The audit's lock: 29 of 29.
- **Reproducible.** `lock.sh` on the head rewrites both files byte for byte, and from no lock at all it picks the same
  versions (`lock-probes.txt`, cases 1 and 2), so the lock is the newest set at least 14 days old.
- **The cooldown works.** With a longer window, a direct pin younger than the window stops the run: "psycopg[binary]>3.3.6
  was published after the exclude newer time and cmapi depends on psycopg[binary]==3.3.8" (cases 3 to 5). So an urgent pin
  younger than 14 days needs the documented `--exclude-newer-package`; that form runs (case 8), and takes effect per package
  (case 9: psycopg passed, the next young pin was named). An invalid value is refused (case 7). `lock.sh`'s header explains
  it. Not measured: a real pin younger than 14 days, because none exists today.
- **With #654.** Its `pyproject.toml` change merges cleanly with this branch (`merge-with-654.txt`; only
  `docs/citations.lock.json` conflicts, which `scripts/doc-citations.py` regenerates). With its pins, `lock.sh` moves fastapi
  to 0.162.2 and starlette to 1.10.0 and adds annotated-doc 0.0.5 and opentelemetry-api 1.45.2 (`lock-probes-2.txt`, case
  10). All 39 packages have a hashed wheel for the image, and OSV has no record for the four. FastAPI 0.162.2 was uploaded
  2026-11-07, 17 days ago, so it passes the cooldown. I did not re-run the stale-lock `pip check` failure; that is the
  implementer's `audit-2-with-654-stale-lock.txt`.

## 4. The audit job

- **Strict: confirmed.** pip-audit sends the PEP 503 name (`_service/osv.py:66`, `spec.canonical_name`), and OSV ignores
  capitals. A site whose packages are spelt `Python_Jose` and `JUPYTER_CORE` gave the same 7 and 4 advisories as the
  canonical names (`pip-audit-spelling.txt`, `osv-spelling.txt`). pip is audited (pip 26.3 is in the report).
- **Covers what ships: confirmed.** Set 1 is the lock, installed by hash, on the image's platform in CI.
- **Network failure: F2 (Medium).** pip-audit 2.10.1 exits 1 with a traceback for a refused connection and for an HTTP 503
  from OSV (`audit-probes.txt`), the same code as an advisory, and does not retry. The head's `audit.sh` with OSV unreachable
  prints "audit.sh: FAILED" and the three sets, exit 1 (`audit-outage-before-head.txt`): an outage reads as an advisory.
  Fix: `cmapi/audit/osv_audit.py` reads pip-audit's JSON report, which exists only when OSV answered for every package. No
  report is tried three times, then is exit 3. `audit.sh` prints "NOT AUDITED ... Run it again" and exits 3
  (`audit-outage-after-fixed.txt`). With OSV reachable it lists Starlette's 7 once each and exits 1
  (`audit-real-after-fixed.txt`). Test: `cmapi/tests/service/test_dependency_audit_655.py`, 10 tests with a stub pip-audit, no
  network; the file it tests does not exist at the head.
- **F6 (Low).** On Linux set 1 now installs with `--only-binary :all:`, as the image does. cmapi is installed from a copy, so
  the checkout keeps no `src/cmapi.egg-info` (`audit-litter.txt`: the head's run left one; `.gitignore` does not cover it).
- **The gate and the order.** The job is red on this PR today (`gh pr checks 658`: `dependency-audit fail`), and locally the
  only advisories are Starlette's 7. That is the gate working, and it is the right gate, but merging #658 first would make
  `main` red and block every other pull request until #654. The order:
  1. #654 gets green and merges. Its `service` check is failing now.
  2. #658 merges `main`, runs `cmapi/lock.sh`, then `python scripts/doc-citations.py --relocate` and `--write` for the
     citation conflict, and pushes. `dependency-audit` is then green, and #658 merges.
  
  After that, a new advisory in any dependency fails every pull request until it is fixed. That follows from "no ignore
  list" and is the owner's choice; the guard now makes an ignore entry a change to `ci-guard.py` too.

## 5. The Containerfile and CI

No step in the diff weakens TLS or hash checking: no `--trusted-host`, no index option, and `curl -sSfL` over https with
SHA-256 checks. CI's `images-pr (cmapi)` check passes on the PR, which is the Containerfile built on linux/amd64.

**F3 (Medium): the guard.** `guard_mutants.sh` on the head (`guard-mutants-head.txt`): of the 21 mutants that apply to the
head's design, 16 pass the guard. Among them: `continue-on-error` on the audit job or step, `if: false` on the step,
`--ignore-vuln` in `audit.sh`, the image without `--only-binary`, without `pip check`, with `--trusted-host` and an http
index, with an extra `pip install --no-deps requests`, and with cmapi built in isolation (an unhashed setuptools download).
The label "nothing else resolves" was not what was checked. The rewritten checks kill all 25 (`guard-mutants-fixed.txt`).

Not changed: the service job's second step, `pip install -e "cmapi[test]"`, resolves pytest and jsonschema's own
dependencies without hashes. They are test-only and set 2 audits them, so I left it.

## 6. Tests

| Run | Result |
|---|---|
| The PR's two new files, head, 2.10.1 | 6 failed, 12 passed |
| The same, 2.15.1 | 18 passed |
| The reviewed `test_jwks_skip_bad_key_656.py` on the head's `auth.py` | 9 failed, 22 passed |
| Fixed tree: that file, `test_pyjwt_advisories_655.py`, `test_auth.py`, `test_doc_citations.py`, `test_dependency_audit_655.py` (`tests-after-fixed.txt`) | 86 passed |
| Mutants of `Jwks._signing_keys` | 14 of 14 killed |
| Mutants of the CI guard | head: 16 of 21 survive; fixed: 0 of 25 |
| `shellcheck cmapi/audit.sh cmapi/lock.sh`, fixed | clean |

Not run: the whole service suite, an image build, the `dependency-audit` job on a runner, and `audit.sh` on Linux (the
`--only-binary` branch of F6 is read, not run; macOS takes the other branch).

## What `fix.diff` changes

- `cmapi/src/cmapi/core/auth.py`: F1, F4, F5.
- `cmapi/tests/service/test_jwks_skip_bad_key_656.py`: 31 tests (was 7).
- `cmapi/audit/osv_audit.py` (new), `cmapi/audit.sh`, `cmapi/tests/service/test_dependency_audit_655.py` (new): F2, F6.
- `deploy/tests/ci-guard.py`: F3.
- `.github/workflows/ci.yml`: the job's comment only.
- `docs/15-keycloak-integration.md`, `docs/14`, `docs/16`, `docs/citations.lock.json`: `auth.py` grew 13 lines, so 20
  citations moved (`--relocate`) and one was rewritten (`auth.py:66-85`). `docs/reviews/2026-11-24-issue-655/README.md`: three sentences.
