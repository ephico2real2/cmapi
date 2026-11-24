# #655, #656 and #657: PyJWT out of its advisories, a dependency audit in CI, and a hashed lock for the image

Opus 5.5 (high) implemented all of it: the pins, `core/auth.py`, the tests, the lock files and their scripts, the CI job,
the Containerfile and the docs. No other model wrote code. The measurements below were taken on the implementer's Mac
(Python 3.12.14, local venvs) and in the base image with podman; no cluster was used.

- **#655:** PyJWT 2.10.1 is in 16 GHSA advisories and PYSEC-2025-183; pytest 8.3.4 in GHSA-6w46-j5rx-g56g. CI ran no
  dependency audit, and the image resolved every transitive package when it was built.
- **#656** (found here): one signing key of the realm's JWKS that PyJWK cannot load made cmapi refuse every token with 503.
- **#657** (found here): the image shipped the base image's pip 24.2, which is in six advisories.

## The advisories, before and after

`pip-audit -s osv` (outputs `audit-4-main-pins.txt`, `audit-1-branch-alone.txt`, `audit-3-with-654-relocked.txt`; IDs read
one by one with `gh api /advisories/<GHSA>` in `ghsa-summary.txt`):

| Package | main | This branch | This branch with #654's pins |
|---|---|---|---|
| PyJWT | 2.10.1: 16 GHSA (1 critical, 5 high, 9 medium, 1 low) and PYSEC-2025-183 | 2.15.1: none | none |
| pytest | 8.3.4: GHSA-6w46-j5rx-g56g | 9.2.0: none | none |
| Starlette | 0.41.3: 7 (#651, PR #654) | 0.41.3: the same 7 | 1.10.0: none |
| pip in the image | 24.2: 6 (`base-image-pip-audit.txt`) | 26.3, from the lock: none | none |

pip-audit prints each advisory twice when OSV holds both its PYSEC and its GHSA record ("Found 14 known vulnerabilities" is
Starlette's 7).

## How far each PyJWT advisory reached cmapi, measured

`probes/reach_probe.py`, `probes/http_probe.py` and `probes/depth_probe.py`, run with each venv (`outputs/reach-old.txt`,
`reach-new.txt`, `http.txt`, `depth.txt`):

| Advisory | On 2.10.1 | Reaches cmapi? | Test |
|---|---|---|---|
| GHSA-752w-5fwx-jx9f, unknown `crit` | a realm-signed token with `crit: ["x-cmapi-unknown"]` was **accepted** by `Authenticator.authenticate` | **yes** | `test_a_token_with_an_unknown_critical_extension_is_refused`: fails on 2.10.1, passes on 2.15.1 |
| The class of GHSA-8wjv-2p76-3863 (header) and GHSA-42vr-xj54-vc7v (payload), recursion before verification. GHSA-8wjv's published range is `>= 2.13.0, < 2.14.0`, so neither it nor OSV names 2.10.1 for the header case; the behaviour below was measured on 2.10.1 all the same | a header nested 9,997 deep (a 26,708-byte token) let `RecursionError` escape `jwt.get_unverified_header`; over uvicorn with httptools, as `main.run` serves, the answer was **HTTP 500**, with no token | **yes**, unauthenticated | `test_a_deeply_nested_header_is_401_and_no_recursion_error_escapes` and `..._over_http_not_500`: fail on 2.10.1, pass on 2.15.1 |
| GHSA-ffc3-869f-jxw9 (critical), GHSA-p4g4-x82p-q773, GHSA-xgmm-8j9v-c9wx, HS/asymmetric confusion | the library's own guard took the realm's public key, CR-only PEM, DER or JWK JSON, as an HS256 secret | **no**: cmapi refuses any `alg` but RS256 before decoding (`auth.py:170-172`), and decodes with the key object and `algorithms=["RS256"]` | two guards, passing on both versions |
| GHSA-9v7f-9g4p-ffgj (redirects), GHSA-993g-76c3-p5m4 (schemes), GHSA-fhv5-28vv-h8m8 and GHSA-2gx3-rcp4-g85q (refetch on unknown kid) | PyJWKClient's | **no**: cmapi fetches the JWKS with httpx, which followed no 302 (the target was never asked) and refused `file:`, `ftp:` and `data:`; its own unknown-kid limit is `retry_after` | two guards, passing on both versions |
| GHSA-hxm8-2xgr-2p9m, non-canonical signatures | | **no**: nothing in cmapi keys on the raw bearer string | |
| GHSA-jq35-7prp-9v3f, GHSA-pxh4-856f-4h89, GHSA-jwrc-g2q2-pq5p, GHSA-w7vc-732c-9m39, GHSA-x33g-cr3x-6449 | | **no**: cmapi passes the key object, never a PyJWK, uses no HMAC, loads RSA keys only, and the payload segment is bounded by the header size | |
| GHSA-w6j9-cwv2-h6wq, one bad key fails the set | PyJWKSet's | not through PyJWT, but cmapi's own loop did the same: **#656** | `test_jwks_skip_bad_key_656.py`: 6 of 7 fail on main's `auth.py` (`before-main-auth-656.txt`), 7 pass after. The review of #658 (reviewer 1, Fable 5.2) then found that a `kid` or `alg` that is a list and `alg: none` still failed the whole set, that the log line could print the member, and that a published private key was HTTP 500; `Jwks._signing_keys` now skips a member on any error. Reviewer 2 (Opus 5.5) found that a key published for PS256 or RS512 verified RS256 tokens, against RFC 8725, section 3.1 ("each key MUST be used with exactly one algorithm"): a key whose `alg` is not RS256 is now passed over, and not counted. The file's 36 tests: 17 fail on the first fix, 10 on reviewer 1's |

The examples' reference app (`examples/local/app.py`) does use `PyJWKClient`, so the PyJWKClient advisories reached it on
2.10.1: a nested payload let `RecursionError` escape `get_signing_key_from_jwt` (`reach-old.txt`). It is on 2.15.1 now.

## The choices

- **PyJWT 2.15.1** and **pytest 9.2.0**: the newest releases at least two weeks old (2026-09-28 and 2026-10-27), with no
  advisory in OSV or the GitHub database (`advisories-chosen-versions.txt`). Their breaking changes, and why none touches
  cmapi: `sources.md`.
- **The lock: `uv pip compile --universal --generate-hashes`**, one `requirements.txt` that pip installs. Rejected:
  - `pip-compile --generate-hashes` (pip-tools): it resolves for the machine it runs on, and its README says to run it "on
    each Python environment separately"; the image is linux/amd64 and the developers are on macOS.
  - `uv lock` with `uv export --hashes`: two files to keep in step, and uv's own docs "recommend against using both a uv.lock
    and a requirements.txt file". The image does not have uv and does not need it.
  - `pylock.toml` (PEP 751, Final): pip 26.3 calls its support "experimental", and the base image's pip is 24.2.
- **What the lock holds**: `pyproject.toml`'s dependencies (still the source of the direct pins), plus
  `requirements-image.in`: setuptools, the build backend, because cmapi is built with `--no-build-isolation` so the backend
  is hashed too; and pip, which replaces the base image's (#657). `lock.sh` passes `--exclude-newer "14 days"`, the
  two-week rule, as uv's cooldown.
- **The install**: pip's "Secure installs": `--require-hashes --only-binary :all:` for the lock, then cmapi with
  `--no-deps --no-build-isolation --no-index`, then `pip check`, then setuptools leaves the image.
- **The audit: pip-audit against OSV**, in `cmapi/audit.sh`, which CI and a developer run the same way. OSV because the
  GitHub API's `affects=` filter is case-sensitive (measured: `pyjwt@2.10.1` and `PyJWT@2.10.1` return 8 different advisories
  each). pip-audit and not OSV-Scanner because it audits an installed Python environment, which is the set that ships, and
  installs from a hashed lock of its own. No ignore list: none is needed. pip-audit exits 1 for an advisory and for a
  failed query alike (measured), so `cmapi/audit/osv_audit.py` reads its JSON report: no report is tried three times, and
  is then exit 3, "not audited", never a pass and never an advisory (the review of #658).
- **The service job now installs the lock** before `cmapi[test]`, so the tests run on the image's versions.

## How it composes with #654

#654 pins FastAPI 0.162.2 and Starlette 1.10.0. This branch's lock was made from main's FastAPI 0.115.6, so on its own:

- `dependency-audit` fails on Starlette 0.41.3's 7 advisories (`audit-1-branch-alone.txt`). That is the gate working.
- With #654's pins and this lock unchanged, `pip check` fails: "cmapi 0.2.0 has requirement fastapi==0.162.2, but you have
  fastapi 0.115.6" (`audit-2-with-654-stale-lock.txt`). The image build fails the same way.
- With #654's pins and `cmapi/lock.sh` run, the lock moves fastapi, starlette, and adds annotated-doc and opentelemetry-api
  (`lock-with-654.txt`), and every set passes (`audit-3-with-654-relocked.txt`).

So #654 merges first; this branch then merges `main`, runs `cmapi/lock.sh`, and pushes. This branch regenerates the lock.
In the merge, `docs/14`, `docs/15` and `docs/citations.lock.json` conflict where both branches moved a citation: keep this
branch's side of each conflicting hunk, run `python scripts/doc-citations.py --relocate`, read each citation that `--check`
still names (the `main.py` ones #654 moved), correct it, and run `--write` (the review of #658). If
the order were reversed, #654 would fail `dependency-audit` and the image build until it ran `cmapi/lock.sh`.

## The tests

| Run | PyJWT, pytest | Result |
|---|---|---|
| The new tests and the targeted auth files, this branch (`after-new-venv-branch.txt`) | 2.15.1, 9.2.0 | 206 passed, 37 subtests passed |
| `test_pyjwt_advisories_655.py` (`before-old-venv-655.txt`) | 2.10.1, 8.3.4 | 3 failed (crit, nested, nested over HTTP), 8 passed (the guards) |
| `test_jwks_skip_bad_key_656.py` without its metric lines, on main's `auth.py` (`before-main-auth-656.txt`) | 2.15.1, 9.2.0 | 6 failed, 1 passed |
| The same, on this branch's `auth.py` (`after-fixed-auth-656-variant.txt`) | 2.15.1, 9.2.0 | 7 passed |
| The targeted auth files with the old PyJWT (`targeted-old-pyjwt-branch-src.txt`) | 2.10.1, 8.3.4 | 188 passed |
| The reference code's whole suite, `examples/` as CI's reference-code job runs it (`reference-code-suite-pytest9.txt`) | 2.15.1, 9.2.0 | 748 passed, 113 skipped. The skip reasons were not tallied; the suite skips when Kyverno, Node, Go or a container engine is absent, which CI requires |
| The service suite, collection only (`collect-only-service-pytest9.txt`) | 2.15.1, 9.2.0 | 2700 collected, no error; 2700 with 8.3.4 too |

The Containerfile's install steps ran in the base image itself, with the lock's linux wheels and no network
(`base-image-install-steps.txt`): pip 24.2 installed the lock and became 26.3, cmapi installed, `pip check` passed,
setuptools left, `import cmapi.main` worked, and the four entry points exist. Every locked package has a cp312
manylinux x86_64 wheel that matches its hash (`linux-wheels-download.txt`).

`deploy/tests/ci-guard.py` checks the new job, the service job's install and the Containerfile's install; each of three
mutants fails it (`ci-guard.txt`).

## The order-dependent log test (the coordinator's full suite on the merged head)

`test_the_log_of_a_skipped_key_has_no_key_material` failed in the full suite and passed alone. Measured:

- **Trigger:** `test_api_contract.py::test_openapi_lists_every_route_with_summary_permission_and_problems`, the suite's first
  test; it builds an app (the `world` fixture). Before the fix, that test and the log test together: 1 failed. Each alone: passed
  (`outputs/658-minimal-pair.txt`).
- **Mechanism** (`probes/structlog_cache_probe.py`, `outputs/658-structlog-cache-probe.txt`). `configure_logging` sets
  `cache_logger_on_first_use=True`. The first log line caches the shared `log` that auth.py writes through, holding the
  processor list of that moment. `capture_logs()` changes the list in place, so a cached logger still sees it. That holds
  until `configure_logging` runs again and gives structlog a new list, or the cached logger filters warnings out. Then
  nothing is captured. The coordinator's diagnosis is right about the cause, the cache, but a cached logger alone is not
  enough: it also needs a later `configure_logging` or a level above WARNING. A pytest plugin that looked at the proxy
  after each test found it cached on a stale list right after the trigger test. Its first version imported structlog at
  load, and that alone changed the outcome of other tests (`test_cors.py`), so the plugin imports it lazily.
- **The fix:** the test captures on a logger of its own. A fixture puts a `structlog.testing.LogCapture` logger, with an
  explicit wrapper class and caching off, in place of `core.auth.log`. Neither the global configuration nor its cache then
  decides what is captured. This follows structlog's testing docs (https://www.structlog.org/en/stable/testing.html, read
  2026-11-24): "capture_logs() relies on changing the configuration. If you have cache_logger_on_first_use enabled for
  performance, any cached loggers will not be affected", and "You can build your own helpers using
  structlog.testing.LogCapture". Production keeps the cache, which the performance docs recommend.
- **Proof:** with the trigger first, 2 passed after the fix. The file alone: 36 passed. The trigger file, the auth, JWKS,
  PyJWT and observability files, then the 656 file: 209 passed (`outputs/658-targeted-after-fix.txt`). The assertion still
  bites: a mutant that logs the error's message, the first fix's leak, fails it.
