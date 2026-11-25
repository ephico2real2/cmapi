# PR #658 (#655, #656, #657): reviewer 2, Opus 5.5 (high)

Read 2026-11-24. Export `review-658/`. I did not write the change or reviewer 1's review. Every output named here is in
`review-658/r2-outputs/`. The patch is `r2-outputs/fix.diff` (848 lines), one patch against `head/`, built from `cmapi/`,
`docs/`, `examples/local`, `.github` and `deploy` only. `build_diff.sh` builds it, applies it with `patch -p1 -F0` to a fresh
copy of `head/`, and compares the result with `r2/`: equal. A second dry run on a full copy of `head/` applied clean.

Trees: `r2/` is the final tree (head, plus Fable's patch, plus my changes). `r2-on-head/` and `r2-on-fable/` hold the final
tests beside the head's and Fable's `auth.py`, for the before runs. Venvs used as they are: `wt-655-outputs/venv-new`
(PyJWT 2.15.1, pytest 9.2.0) and `venv-old` (PyJWT 2.10.1, pytest 8.3.4), Python 3.12.14, macOS. The database was
`cmapi_wt616` only. No image was built, no cluster, no GitHub write. A throwaway clone in my scratchpad (`git clone --shared`
of `wt-651`) was used for the merge simulation; no existing repository was changed.

## Rulings

| # | Fable's severity | Ruling | Test that decides it |
|---|---|---|---|
| F1 | Medium | **Accepted, and widened.** Fable's skip is safe, but a key published for PS256 or RS512 still verified RS256 tokens (R2-1). Final code passes over any key whose `alg` is not RS256 | `test_a_key_published_for_another_algorithm_never_verifies_an_rs256_token`: fails on the head and on Fable's fix, passes on mine |
| F2 | Medium | **Accepted.** An outage must fail the job, labelled "not audited", not warn. `osv_audit.py` is kept: pip-audit cannot tell the two apart, and the file is what makes it testable offline. Two messages corrected (R2-2) | `test_dependency_audit_655.py`, 10 tests; `audit-outage-r2.txt`, exit 3 |
| F3 | Medium | **Accepted, minus one check.** 22 of Fable's 25 mutants are real weakenings and stay killed. The regex check for an index, a trusted host and `curl -k` is dropped: the integrity it claims comes from the hashes | `guard-mutants-r2.txt`: 22 killed, the 3 dropped by design |
| F4 | Low | **Accepted**, as defence in depth. With R2-1 the message that printed the member (`Unable to find an algorithm for key`) cannot be reached by an RS256 member any more | `test_the_log_of_a_skipped_key_has_no_key_material`, reworked |
| F5 | Low, predates | **Fix here, and file an issue closed by #658.** It is the same function and the same kind of defect as #656 (one member of the JWKS breaks verification), so it is in scope under "file it and fix it in the same session" | `test_a_member_with_private_parameters_is_skipped` |
| F6 | Low | **Accepted, simplified**: `--only-binary :none:` or `:all:` replaces the empty-array idiom | `audit-with-654.txt` (macOS path); Linux path read, not run |

What Fable missed:

- **R2-1 (Low, predates the PR)**: a key whose `alg` is not RS256 is loaded and verifies RS256 tokens (below). Fixed here. Issue to file.
- **R2-2 (Low)**: the "OSV did not answer" messages were also printed for a `--strict` collection failure. Corrected.
- **R2-3 (record)**: Fable's two claims about #654 no longer hold as measured. The lock adds annotated-doc 0.0.6, not 0.0.5,
  and merging the branch tips conflicts in four files, not one. Steps are in the last section.

## Sources, fetched 2026-11-24 (`r2-outputs/sources/`)

- RFC 7517 §5 (`https://www.rfc-editor.org/rfc/rfc7517.txt`): "Implementations SHOULD ignore JWKs within a JWK Set that use
  "kty" (key type) values that are not understood by them, that are missing required members, or for which values are out of
  the supported ranges." §4.4: "The "alg" (algorithm) parameter identifies the algorithm intended for use with the key. ...
  Use of this member is OPTIONAL." §4.2: "The "use" parameter is employed to indicate whether a public key is used for
  encrypting data or verifying the signature on data."
- RFC 7515 §4.1.1 (`.../rfc7515.txt`): "The JWS Signature value is not valid if the "alg" value does not represent a
  supported algorithm or if there is not a key for use with that algorithm associated with the party that digitally signed
  or MACed the content." §4.1.4: the `kid` value "MUST be a case-sensitive string".
- RFC 8725 §3.1 (`.../rfc8725.txt`): "Moreover, each key MUST be used with exactly one algorithm, and this MUST be checked when
  the cryptographic operation is performed." Fable's report cites RFC 8725 for `alg: none`. §3.1 is about checking the
  algorithm, and the sentence above is what R2-1 rests on.
- pip-audit README at v2.10.1 (`https://raw.githubusercontent.com/pypa/pip-audit/v2.10.1/README.md`), "Exit codes": "`0`: No
  known vulnerabilities were detected. `1`: One or more known vulnerabilities were found." Nothing on errors. The source of
  2.10.1 (`tools/.../pip_audit/_cli.py:186-192`, `_service/osv.py:69-79`) shows the rest. A `ConnectTimeout` becomes
  `_fatal` → `sys.exit(1)`. An HTTP error becomes `ServiceError`, which nothing catches, so it is a traceback and exit 1. A
  refused connection (`requests.ConnectionError`) is not caught either. No retry anywhere in the package. 2.10.1 is the newest
  release on PyPI today, and the changelog's Unreleased section adds no retry. The same README, "Reporting only fixable
  vulnerabilities": "you can export its output in JSON format and externally process it". That is what `osv_audit.py` does.
  JSON is a manifest format (`_format/json.py:36-40`), so the report is written on every successful run and never on a failed
  one (`_cli.py:635-652`).
- pip "Secure installs" (`https://pip.pypa.io/en/stable/topics/secure-installs/`): "This mode uses local hashes, embedded in a
  requirements.txt file, to protect against remote tampering and network issues." `pip install --only-binary`
  (`https://pip.pypa.io/en/stable/cli/pip_install/`): "Accepts either ":all:" to disable all source packages, ":none:" to
  empty the set". Not settled: whether pip hash-checks build dependencies in an isolated build. I found no primary source for
  it either way, so no ruling here depends on it.
- OWASP "Fail securely" (`https://owasp.org/www-community/Fail_securely`): "you should design your security mechanism so that
  a failure will follow the same execution path as disallowing the operation."
- GitHub Actions workflow syntax
  (`https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax`): "The runner will report the status of
  the step as fail/succeed based on this exit code." Step `continue-on-error`: "Prevents a job from failing when a step fails."
- GHSA-8wjv-2p76-3863 (`https://api.github.com/advisories/GHSA-8wjv-2p76-3863`, and OSV): `pyJWT >= 2.13.0, < 2.14.0`, first
  patched 2.14.0. **Fable's correction of the README row is confirmed.** GHSA-42vr-xj54-vc7v (the payload case) is
  `>= 2.0.0a1, <= 2.14.0`, which does include 2.10.1.
- Keycloak `JWKBuilder.java` (main) sets `k.setAlgorithm(algorithm)` on every RSA key it publishes (lines 92, 119, 161). So
  Keycloak's keys carry `alg`, and a realm with a PS256 or RS512 provider publishes that key with that `alg`.

## F1: the skip, and R2-1

**The skip cannot widen what verifies. Measured, not assumed:**

- A token whose `kid` names a skipped key is 401 "unknown signing key", in both orders of the set, whether the realm's real
  key or the other loaded key signed it (`test_a_token_that_names_a_skipped_key_is_401_...`, 6 cases).
- A bad member never hides a good key of the same kid, in either order (`test_a_bad_member_does_not_hide_...`).
- `alg: none` never verifies, by three separate layers, each measured:
  - `authenticate` refuses any header `alg` but RS256.
  - `jwt.decode(..., algorithms=["RS256"])` refuses `none`.
  - PyJWT refuses a `none` token with a non-None key: "When alg = "none", key value must be None." (`probes/none_probe.txt`,
    both versions).

  So mutants M20 and M22, which open one or two of these layers, survive. They do not change the behaviour, so they count as
  equivalent mutants. A JWK with `alg: none` is passed over (`OTHER_ALGORITHMS["alg is none"]`).
- **Fable's noted behaviour change** does not reduce what a legitimate token can use. It skips a member whose `kid` is null,
  a number or empty, where before it loaded it. PyJWT's `get_unverified_header` refuses a token whose `kid` is not a string,
  in both versions ("Key ID header parameter must be a string"). `authenticate` refuses an empty `kid` (`not
  header.get("kid")`). So no token could ever name such a member (`probes/kid_header_probe.txt`).
- **`except Exception` is load-bearing.** On 2.15.1, after R2-1, every remaining error is a `PyJWTError`, so narrowing the
  `except` (M1) survives there. On 2.10.1 the same members raise `ValueError` and `TypeError` (`probes/raise_probe.txt`), and
  M1 is killed: 8 tests fail. A skip only removes a key, so the broad `except` cannot widen anything.

**R2-1 (Low, predates the PR): a key for another algorithm verifies RS256 tokens.** `probes/alg_probe.txt`, both versions:
`PyJWK` loads `{"alg": "PS256"}` and `{"alg": "RS512"}` RSA members as `RSAPublicKey`. `jwt.decode(token, key.key,
algorithms=["RS256"])` then **verifies** an RS256 token signed by that key's private key. That breaks RFC 8725 §3.1's "each key
MUST be used with exactly one algorithm". Exploiting it needs the private key of the realm's other key, which only Keycloak
holds, so it is Low. The fix is one filter, and it also makes Fable's list and `none` `alg` cases unreachable in `PyJWK`:

```python
        for k in raw:
            if not isinstance(k, dict) or k.get("use", "sig") != "sig" or k.get("kty") != "RSA":
                continue
            if k.get("alg", "RS256") != "RS256":                    # "alg" is optional (RFC 7517, section 4.4)
                continue
            kid = k.get("kid")
```

A key for another algorithm is passed over without being counted, as an encryption key is. A realm with a PS256 provider
would otherwise log a warning on every refresh. A member with no `alg` is still a key for RS256: RFC 7517 §4.4 makes `alg`
optional, and `test_a_key_with_no_alg_is_a_key_for_rs256` covers it. The full function is in `r2/cmapi/src/cmapi/core/auth.py:58-87`.
It is 22 lines of code under its comment, with one decision per line, and readable by a junior engineer. I kept Fable's
structure.

**Tests changed for this.** In `test_jwks_skip_bad_key_656.py`, the four `alg` cases move from `BAD_MEMBERS` (counted) to
`OTHER_ALGORITHMS` (passed over, not counted): list, none, number, HS256. "an alg PyJWT does not know" moves out of
`BAD_KEYS` the same way. PS256, RS512 and `rs256` are added. Three tests are new:

- `test_a_key_published_for_another_algorithm_never_verifies_an_rs256_token` decides R2-1.
- `test_a_key_with_no_alg_is_a_key_for_rs256` kills M16.
- `test_an_encryption_key_with_no_alg_never_verifies_a_token` kills M21: without it, the `use` check was untested once the
  `alg` filter existed.

The log test now uses an RS256 member with a bad `e`. The old `alg: 5` member no longer reaches `PyJWK`.

| Run (`r2-outputs/`) | Result |
|---|---|
| The final 36-test file on the head's `auth.py` (`final-jwks-on-head.txt`) | 17 failed, 19 passed |
| The same on Fable's `auth.py` (`final-jwks-on-fable.txt`) | 10 failed, 26 passed: 2 are R2-1 (PS256, RS512 verify); 8 are the "not counted" choice |
| Final tree, 2.15.1: the JWKS file, `test_review_b_auth`, `test_auth`, `test_pyjwt_advisories_655`, `test_dependency_audit_655` (`final-r2-2.15.1.txt`) | 101 passed |
| Final tree, 2.10.1, the same without the advisories file (`final-r2-2.10.1.txt`) | 90 passed |
| Fable's patch as delivered, 2.15.1 (`fable-tests-after.txt`) | 74 passed; at the head 19 failed (`fable-tests-before-head.txt`) |

**Mutants of the final `_signing_keys` and its guards** (`auth_mutants.sh`, `auth-mutants-2.15.1-final.txt`,
`auth-mutants-2.10.1.txt`):

| Result | Mutants |
|---|---|
| Killed (19 of 22 on 2.15.1) | M2 to M19 and M21. Among them: no `alg` filter (M15), `alg` required (M16), `RS*` family (M18), `alg` without case (M19), a skipped member takes or removes a loaded key (M9, M10), one bad member fails the set (M11), the `use` check removed (M21) |
| M1, narrowed `except` | Survives on 2.15.1 and is killed on 2.10.1 (8 failed). Equivalent on the pinned version |
| M20 and M22, `alg: none` | Survive: equivalent, because the third layer above still refuses the token |

## F2: the outage

**Fail the job, do not warn.** A warning leaves CI green on a set that nobody audited. That is the silent pass the brief rules
out, and it breaks OWASP's "a failure will follow the same execution path as disallowing the operation". Exit 3 is non-zero,
and GitHub reports the step "as fail/succeed based on this exit code". The job's step has no `continue-on-error`, and the guard
enforces that. So the job fails, its log says "NOT AUDITED ... Run it again", and a rerun is one click. Three attempts, with
waits of 10 s and then 20 s, keep a short blip of OSV from blocking every pull request. This fits the owner's "no ignore list"
gate: what is unknown is not a pass.

Measured with `r2/`'s `audit.sh` and OSV unreachable (a dead HTTPS proxy; PyPI not proxied). Output:
`audit-outage-r2.txt` and `audit-outage-r2-full.txt`.
- Each set: three attempts, then `osv_audit: NOT AUDITED`.
- At the end: `audit.sh: NOT AUDITED ... for these sets`, with all three sets listed.
- **exit 3.**

With OSV reachable and #654's pins (`audit-with-654.txt`): 39, 49 and 34 packages, 0 advisories, exit 0.

**Is `osv_audit.py` needed?** Yes. pip-audit 2.10.1, the newest release, exits 1 for an advisory and 1 for a failed query, and
it does not retry (source cited above). So something outside pip-audit must tell the two apart, and pip-audit's README points
to processing its JSON. In Python the decision is testable offline (Fable's 10 stub tests). Written as a bash function inside
`audit.sh`, it could only be tested with the network and three venvs. One part is dead code under `--strict`: the "skipped"
branch, because pip-audit then stops with `_fatal` before it writes a report (`_cli.py:557-558`). It is 2 lines and never a
pass, so I kept it.

**R2-2.** The no-report messages said "OSV or the network failed" and "OSV did not answer". A `--strict` collection failure
also leaves no report, so they now say "pip-audit gave no answer ... its error is above". The same goes for the exit-3 line in
`audit.sh`'s header and its `NOT AUDITED` line.

## F3: the guard

Of Fable's 25 mutants, these 22 kill a real weakening:

- `continue-on-error` on the job or the step, `if: false`, `|| true`, the job on main only, an action on a tag;
- `--ignore-vuln`, no `--strict`, `--osv-url`;
- `audit.sh` treating a set that was not audited as ok, exiting 0 on an advisory or on an outage, or installing without hashes;
- a `PIP_` variable on the workflow;
- the service job or the image without `--only-binary` or without `--require-hashes`;
- the image without `pip check`, with an extra `pip install` (two forms), or with an isolated build that downloads an
  unhashed backend.

I dropped the `weakening` regex. It killed three mutants: `PIP_TRUSTED_HOST`, `--trusted-host` with an http index, and
`curl -k`. Each of them leaves integrity intact:
- With `--require-hashes`, pip installs only files whose SHA-256 the lock holds, wherever they come from ("to protect against
  remote tampering and network issues").
- Every `curl` in the Containerfile is followed by `sha256sum -c -` under `set -eu`.
- The `curl` lines predate #655.

The three now survive by design (`guard-mutants-r2.txt`: 22 killed, 3 survived).

I first dropped the workflow `PIP_*` check too, then **retracted that**. I could not show that no `PIP_` variable can weaken a
hashed install, so the check stays.

**Brittleness.** The checks on `audit.sh`'s exit lines (`"1) failed+="`, `"((${#unaudited[@]})) && exit 3"`) and the `pip
check` regex match text, not behaviour. A refactor makes them fail loudly; it does not make them pass falsely. I kept them:
the alternative is a functional test of `audit.sh`, which needs the network.

## F4 to F6

- **F4** is kept as defence in depth, and the log test still fails on the head.
- **F5** is fixed here (ruling above). The coordinator files an issue, "a private JWK in the realm's JWKS is a 500", with
  `Part of #656` and closed by #658.
- **F6** is simplified: `binary=:none:`, set to `:all:` on Linux, then `--only-binary "$binary"`. The `${a[@]+"${a[@]}"}`
  idiom and its comment are gone. Shellcheck is clean on `audit.sh` and `lock.sh`.

## Landing after #654 (#651)

Measured (`lock-with-654.txt`, `audit-with-654.txt`). In a copy of `r2/` I applied #654's two pin changes:

- `cmapi/pyproject.toml`: `fastapi==0.162.2` and `starlette==1.10.0`;
- `examples/local/requirements.txt`: the same two pins.

Then `lock.sh` (uv 0.13.7) exited 0, with these changes to the lock:
- `fastapi` 0.115.6 → 0.162.2;
- `starlette` 0.41.3 → 1.10.0;
- added `annotated-doc==0.0.6` and `opentelemetry-api==1.45.2`.

`audit.sh` then exited 0.

**R2-3.** Fable's lock had annotated-doc 0.0.5. PyPI shows that 0.0.6 was uploaded 2026-11-10T18:17Z, so it passed the
14-day cooldown at 18:17Z today, between Fable's run and mine. The lock depends on when it is made. That is the cooldown
working, not a defect.

I merged `fix/651-fastapi-starlette-upgrade` into `fix/655-pyjwt-audit-lock` plus my patch, in a scratch clone. Conflicts:
`cmapi/src/cmapi/main.py`, `docs/14`, `docs/15`, `docs/citations.lock.json`. The `main.py` conflict is #654's own: its
branch is based on `a2a55f3` and conflicts with main `5962830` (#644 and #646) without #658. So #654 must merge main first.
Fable's "only `docs/citations.lock.json` conflicts" does not hold for the branch tips.

Steps for the coordinator:

1. #654 merges `main` itself, is green (its `service` check failed earlier), and merges.
2. On `fix/655-pyjwt-audit-lock`, after this patch is applied: `git fetch origin && git merge origin/main`.
3. In `docs/14-authorization.md`, `docs/15-keycloak-integration.md` and `docs/citations.lock.json`, keep #658's side of each
   conflicting hunk and main's other changes. For each such file F:
   `git show :1:F >b; git show :2:F >o; git show :3:F >t; git merge-file --ours -p o b t >F; git add F`.
   Do not use `git checkout --ours F`: it would drop main's hunks that did not conflict. Any code-file conflict is resolved
   by hand.
4. `cmapi/lock.sh`, which needs uv 0.13.7 or later. Expect the four changes above.
5. `python scripts/doc-citations.py --relocate`, then `--check`. In the simulation, 4 `main.py` citations were left, the ones
   #654 moved: `main.py:141-142`, `:144-146`, `:179-180` and `:139-140`, each one line earlier there. Read each cited range,
   correct the number in the document, run `--write`, then `--check` until it reports 0 problems. The simulation reached 0
   problems; it took #654's side of `main.py`, for the simulation only.
6. Checks:
   - `cmapi/audit.sh python3.12` exits 0;
   - `python deploy/tests/ci-guard.py .github/workflows/ci.yml` reports 0 failed;
   - `shellcheck cmapi/audit.sh cmapi/lock.sh`;
   - the targeted tests above, plus `test_doc_citations.py`;
   - push. CI's `dependency-audit`, `service` and `images-pr (cmapi)` must be green before merge.

## What `fix.diff` changes, against `head/`

- **Fable's patch**, as reviewed above.
- **Mine, on top of it:**
  - `auth.py`: the `alg` filter and its comment (R2-1), and the `except` comment.
  - `test_jwks_skip_bad_key_656.py`: 36 tests.
  - `audit.sh`: F6 simplified, and the R2-2 messages and header.
  - `osv_audit.py`: the R2-2 messages.
  - `ci-guard.py`: the `weakening` check removed.
  - `docs/15`: the RFC 8725 sentence, and the citation `auth.py:66-87`.
  - `docs/14`, `docs/15`, `docs/16`, `docs/citations.lock.json`: relocated. `--check` reports 0 problems
    (`doc-citations-check.txt`).
  - The review README: the #656 row (R2-1, 36 tests: 17 fail on the head, 10 on Fable's) and the merge step for citations.

## Not run

- The whole service suite.
- An image build.
- The `dependency-audit` job on a runner.
- `audit.sh` on Linux, so the `:all:` branch of F6 was read, not run.
- `test_doc_citations.py`, because it needs a git checkout. The tool itself was run in a throwaway `git init` copy.
- The real merge of main after #654: #654 has not merged, so step 5's citation list is from a simulation.

## Issues to file (coordinator)

- **R2-1**: "A JWK published for another algorithm verifies RS256 tokens (RFC 8725, section 3.1)". `Part of #656`, closed by #658.
- **F5**: "A private JWK in the realm's JWKS makes a token of its kid HTTP 500". `Part of #656`, closed by #658.

Sources: [RFC 7517](https://www.rfc-editor.org/rfc/rfc7517.txt), [RFC 7515](https://www.rfc-editor.org/rfc/rfc7515.txt),
[RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.txt), [pip-audit README v2.10.1](https://raw.githubusercontent.com/pypa/pip-audit/v2.10.1/README.md),
[pip-audit CHANGELOG](https://raw.githubusercontent.com/pypa/pip-audit/main/CHANGELOG.md), [pip Secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/),
[pip install](https://pip.pypa.io/en/stable/cli/pip_install/), [OWASP Fail securely](https://owasp.org/www-community/Fail_securely),
[GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[GHSA-8wjv-2p76-3863](https://api.github.com/advisories/GHSA-8wjv-2p76-3863), [GHSA-42vr-xj54-vc7v](https://api.github.com/advisories/GHSA-42vr-xj54-vc7v),
[Keycloak JWKBuilder](https://raw.githubusercontent.com/keycloak/keycloak/main/core/src/main/java/org/keycloak/jose/jwk/JWKBuilder.java).
