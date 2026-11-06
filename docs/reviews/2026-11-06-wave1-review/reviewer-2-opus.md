# Wave 1 adversarial review: reviewer 2

On `fa8c27c` (PR #98, issue #94). The set is `final/01` to `final/09`, applied in order by `final/APPLY.md`. Logs are in `logs/`. The full code of every fix and test is at the end of this file.

## Reviewer 1's four findings

Each was reproduced first. All four are real, and all four fixes change.

| # | Verdict | Final severity | Reason, with source |
|---|---|---|---|
| F1 | **AMEND** | CRITICAL | `crc-guard.py:87` raises `IncompleteRead` inside the `HTTPError` handler, reproduced with a real local TLS server. It is not the last path: `tls()` raises `Stop` (`:73`), which the watch's loop also does not catch (CA file gone mid-run), and a `KeyError` from an odd baseline (`:241`) does the same. Each leaves no stop file |
| F2 | **AMEND** | HIGH | `secrets.sh:32` takes any `--issuer`, and the 404 for another realm is also Keycloak's own. The glob `*/realms/cmapi` passes `https://kc/realms/not-cmapi?x=/realms/cmapi` and the same with `#`, and curl asks for `not-cmapi` |
| F3 | **AMEND** | HIGH | `crc-proof.sh:62` takes any failure as blocked. The exact string is right for a drop, but a hung server gives the same string (measured), and the patch breaks the shipped suite's stub |
| F4 | **AMEND** | CRITICAL | The defect is real at `docs/13:78`. The fix closes the owner's terminal on a stop, does not hold for a step pasted later, and loses the realm sync's log |

### F1: what changed

Reviewer 1's patch handles one more case in `http_get`, and returns status 0 for it. Three changes:

- `http_get` keeps the status it did receive: `e.code, b""`. The log then says `corp=503`, not `corp=0`, and `issuer` still reads an empty body as unknown.
- **The root fix is the catch-all.** The loop body sits in `except Exception`, so anything unforeseen adds a problem, writes the stop file, and the watch goes on logging. This earlier commit and F1 are two rounds of the same defect: a list of exceptions that was one short.
- `watch` wraps the whole of it in `except BaseException`, so a watch that cannot even begin (no baseline, log not writable) writes the stop file too.

A failure cannot read as healthy: the catch-all always adds to `problems`, and `kc` starts empty, so `down` is true.

The test is in `crc-guard-test.py` on its real TLS server, rather than monkeypatching `urlopen`, and has three new mutants.

### F2: what changed

`[[ "$ISSUER" =~ ^https://[^/?#]+/realms/cmapi$ ]]`, not a glob, so the query and fragment forms stop too. Test cases go in `secrets-test.sh` section 11, each with Keycloak's own 404 from the curl stub, and two mutants in `mutate-secrets.py`.

- **`crc-guard.py issuer` does not have this hole.** Its path is fixed at `/realms/cmapi` (`:106`), read in full. A trailing slash on `CMAPI_KEYCLOAK_URL` gives a 404 that is not Keycloak's own, which is `unknown`, so a stop.
- **A host other than Keycloak's cannot be refused by `secrets.sh`,** which does not know the host. `doc13-test.py` now holds step 9's literal host, with a mutant.
- `--no-issuer-check` is untouched, since the rule only applies with the check on. `kind-test.sh:56` and the stub suite still pass.

### F3: what changed

Measured with the proof's own command on the pinned image (BusyBox 1.37, Alpine), `logs/f3-busybox-wget-measured.txt`:

| What the target does | wget says | Elapsed |
|---|---|---|
| Drops the SYN | `wget: download timed out` | 5 s |
| Accepts, then never answers | `wget: download timed out` | 5 s |
| Resets, or nothing listening | `wget: can't connect to remote host (...): Connection refused` | 0 s |
| ICMP unreachable | the same | 1 s |
| Name does not resolve | `wget: bad address '...'` | 1 s |
| Answers 503 | `wget: server returned error: HTTP/1.0 503 down` | 0 s |

So the string is correct but not sufficient. A hung api with the policy not enforced would pass as "blocked". **The positive control:** `/readyz` through the Route must answer 200 straight after the timeout, which is the path the policy allows. DNS needs no separate check, since `bad address` already says so.

**Could a reset fail a working policy?** OVN-Kubernetes's own documentation describes a baseline drop ACL on isolated pods, and I found nothing describing a reset for a policy denial. That is read, not measured, and enforcement on OVN is already on the "not proven" list. If a reset did happen, step 21 stops and prints wget's words for a person. That is the right direction to be wrong in, since a refused connection is also what a Service with no endpoints looks like.

Reviewer 1's patch alone fails the shipped suite: its stub exits 1 and prints nothing, so "proof passes when all is right" goes red (`logs/f3-codex-patch-on-the-shipped-suite.txt`). The stub now prints the timeout, with six new cases.

### F4: what changed

The stated shell is "one bash, not zsh" (`docs/13:75`), pasted by a person. Reviewer 1's `set -euo pipefail` plus `|| exit $?` has these failures:

1. **It closes the shell.** Measured in an interactive bash: `exit`, and the later line never ran (`logs/06-runbook-before-after.txt`). `docs/12:99` already says why not to do this.
2. **A stop does not hold.** After the shell is gone, the next paste runs elsewhere, with `$G`, `$R` and `$STOP` empty. The design's `gate` file only ever records the watch's breaches, and steps 1 to 10 do not read it.
3. **Step 19 loses its log.** `oc wait ... || exit $?` exits before `oc logs`, and the runbook's own text says "read the log".
4. **Steps 3 and the prelude still only print,** and its test looks for the text `|| exit $?`, not for what a failure does.

**The reconciliation.** `docs/12`'s subshell for the shell, and the design's gate file for the later step:

```bash
( set -euo pipefail
  $G gate "$STOP"
  deploy/crc-backup.sh
); stopped $? 11
```

`stopped` writes any failure to `$STOP`, so every later step refuses at its first line, however much later it is pasted. Step 14 alone has no gate, since a stop is what it must act on. Clearing a stop is one documented procedure, after the owner has heard.

There is a trap, measured in the same log: `( set -e; false; echo x ) || stopped` prints `x`, because bash ignores `set -e` on the left of `||`. Hence the `;`, and a test on that exact shape.

**`doc13-test.py` holds it by running it.** Each step's block goes through a plain bash, on stubs of `oc`, `git`, `sleep` and every script, with each command it calls failing in turn. Each must end the step, leave the shell alive, write the stop file, and make the next step refuse. It passes on bash 5.3 and on the Mac's stock 3.2. There are 34 mutants, none surviving, including `stopped` closing the shell and an AND-list.

## What reviewer 1 missed

| # | Severity | Where | Failure |
|---|---|---|---|
| N1 | HIGH | `crc-guard.py:370` | `gate` passes when the watch is dead or never began |
| N2 | HIGH | `crc-guard.py:300-303` | One failed read ends `import-wait`, and a pending import is left to start unattended |
| N3 | MEDIUM | `crc-guard.py:316` | `HasErrors` alone kills a running import |
| N4 | HIGH | `cmapi/src/cmapi/core/registry.py:193-198` | A CA bundle is `invalid caData`, so the reader never connects |
| N5 | MEDIUM | `realm/10-realm-import.yaml` | Any person's password can be guessed without limit and with no client secret |

### N1: `gate` passes when nothing is watching

`gate` reads only the stop file, and a dead watch writes nothing. Step 10 starts it in the background and never checks it. On `fa8c27c`, three ways there:

- `kill -9` of the watch: `stop file exists: no`, then `gate rc=0` (`logs/05-liveness-before-after.txt`).
- A hang, or the Mac asleep: the same, with nothing written.
- Step 10's snapshot failing, or the CA not exported: the watch dies at once, and every later gate passes.

**Fix (05).** The watch beats in `$STOP.alive`. `gate` refuses if that process is gone or the beat is over 120 s old, which is longer than one worst-case round (five realms at 3 s, `oc`'s 60 s, the poll). `watching` proves it began, and step 10 calls it. A clean end removes the beat, so step 23's gate passes. Step 10 also removes a stale `watch.log.done`, which would end a new watch at once.

### N2: one failed read abandons a pending import

`oc_json` raises `Stop` on any non-zero `oc` (`:61`), which leaves `import_wait` and exits 1 with the import still there and nobody following it. Reproduced: reads failing with a pending pod gave rc 1 and no delete, where an earlier import here waited about 6.5 days.

**Fix (07).** A failed read is logged, and the follow goes on using what it last knew, to the same deadlines: not started means withdrawn by name at the deadline, started means reported and never interrupted. If the delete itself cannot reach the API it still stops and says so, and step 14's text now says what to read then.

### N3: `HasErrors` is not "the import failed"

`crc-guard.py:316` withdraws on `HasErrors` with a started pod. In the operator's 26.6.4 source, `updateErrorStatus` (`KeycloakRealmImportController.java:101-109`) sets `HasErrors` for any exception in a reconcile, not only a failed Job (`:139-141`). So one transient operator error would delete the import under a healthy running pod, where `docs/13` says "Never interrupted". Reproduced on the stub: `errors` with a running pod deleted it. That the condition actually fires this way on RHBK is inferred from source.

**Fix (07).** Withdraw on a pod that has failed: phase `Failed`, or a non-zero exit. The Job's retries are still stopped, which is what the withdrawal was for.

### N4: the reader's CA bundle is refused

`crc-reader-import.sh` passes the service account's `ca.crt` as `caData`. `registry.py:195` strips the PEM lines of the **whole bundle**, joins them, and decodes with `validate=True`. If any certificate but the last ends in `=`, strict base64 refuses it: `Error: Excess data after padding`, measured on real certificates of 1 to 6 per file, failing from the first with padding not at the end.

The result is `invalid-secret`, `cmapi_cluster_status` is never `connected`, and step 21 fails after everything is deployed.

**That CRC's `ca.crt` is such a bundle is inferred.** Red Hat's bug 2129668 lists several signers in `kube-root-ca.crt`'s bundle, kind has one, and I found no record in the repository of this path connecting on CRC. `APPLY.md` has the one read-only command that settles it. The fix is safe either way.

**Fix (08), application code.** Each PEM block is decoded alone, and text with no PEM markers behaves as before. Nine test cases, including garbage in a second block. It is the one patch in `cmapi/src`, so the pull request should say reviewer 2 wrote it.

### N5: guessing a person's password

The realm federates all of `ou=People` in the shared directory. On real Keycloak 26.6.4 with the file that ships (`logs/job3-realm-measured.txt`):

- `admin-cli`, which Keycloak gives every realm, is public with direct grants. It took `ola`'s and an LDAP person's password with no client secret: 200. So `cmapi-automation`'s secret does not limit who can test a password.
- `bruteForceProtected` is false. 40 wrong guesses took 1.1 s with no lockout, and the right password then worked.

The token it gives is harmless: no audience, no roles, and `core/auth.py:153` pins the audience. The harm is an unlimited password check on people other projects also authenticate.

**Fix (09), which must go in before the first import.** `admin-cli` named in the import with `enabled: false`, and `bruteForceProtected: true`, `permanentLockout: false`, `failureFactor: 10`. Measured after, on the same image: the import succeeds, `admin-cli` answers 401, the realm reports protection on, and the realm sync and every sign-in below still work. `realm-test.py` holds it on a real server, and a static test holds the file.

## Checked, and not a finding

Each measured on Keycloak 26.6.4 unless it says otherwise.

| Claim checked | Result |
|---|---|
| `cmapi-realm-admin` on its own realm only | `GET /admin/realms` lists only `cmapi`. `master` and another realm 403 on read and delete; creating a realm 403 |
| `cmapi-directory` | Reads users 200. Reset password, clients and another realm all 403 |
| `cmapi-automation` | No secret 401, wrong secret 401. No client-credentials grant |
| Direct grants | Apart from N5's `admin-cli`, only `cmapi-automation`. Every public client 400 |
| The test users | Roles as in `TEST_USERS`, none an admin. Passwords are 48 random characters from `secrets.sh`, none in the repository |
| A local user editing their identity | Account API is 403 for `account-console`'s token: this realm's imported scopes give it no account role. `employeeId` is also `edit: [admin]` in the profile |
| `redirectUris` | Other hosts and ports refused; `cmapi-docs` without PKCE refused. `cmapi-portal.apps-crc.testing/*` and `localhost:5173/*` are held for a portal not yet deployed, and PKCE is on. Noted for the portal's wave, since an unclaimed host on a wildcard domain can be claimed by anything that can make a Route |
| `snapshot` fields empty on both sides | Read in full: every field is set on a running pod, and a realm at 200 with no key becomes status -1. A deleted other import, a new `keycloak-0`, a changed key and a realm gone each stop `compare`, by test. `watch` looks only at realms and `keycloak-0`, by design; `compare` catches a deleted import at the next step |
| A withdrawal racing a pod's start | Pending at the read and started before the delete is a window of about a second, before a JVM has touched the database. Not a defect |
| `crc-image.sh` token and cleanup | Token never on an argument. The file is gone after SIGTERM and SIGHUP, measured with a build running (`logs/job3-crc-image-signals.txt`; INT in a background job is ignored, so that line shows nothing). A `kill -9` leaves a 0600 file, which no script can prevent |
| `20-config.yaml` | One cluster, `writes: false`, checked first at `pipeline.py:162,276`. `directory`'s hosts are only returned as a URL in a 422 (`:136-139`), and `webUrl` builds links. No write verb in the reader's role. `test_crc_environment.py` holds the proof's requests |
| `crc-reader-import.sh` | The token goes by pipe, never an argument. Its identity and list checks match the role. Listing pods across namespaces is ruling 8 |
| The proof's dry run | The body is complete, and `writable()` is the first check, so 422 `cluster-not-writable` is right |

## CI (Job 2)

The failure is reproduced in Ubuntu 24.04: `crc-scripts-test.sh`'s `modes`, `FAIL` with `File: ...`, and everything else in the script passing.

**Every instance of the shape:** `crc-scripts-test.sh:66` (right result by luck, since the second `stat` truncates the file), `crc-scripts-test.sh:150` (the failure), and `crc-backup-test.sh:60` (next in line, in a step CI had not reached). `secrets.sh:132` and `render-test.sh:123` already had `-c` first. `ci-guard.py` now fails on the shape, so a Mac can catch it too.

**Each later step, read and run:**

| Step | Result |
|---|---|
| `doc13-test.py` | Passes in Ubuntu with the set applied, block runs included |
| `mockup-configmap.sh --check`, kubeconform with `-skip Route` on both trees and on both renders, `render-test.sh` | Pass in Ubuntu, with the pinned kubeconform and schemas: 36 and 31 resources, 2 skipped, 0 invalid. `KeycloakRealmImport`'s schema is in the catalog, including this file's fields |
| `crc-backup-test.sh` | See the proof table. It pulls `quay.io/sclorg/postgresql-16-c9s` by digest, public, so **no `registry.redhat.io` credentials are needed**: that name appears only in stub data and comments |
| `realm-test.py` | See the proof table. Quay and Docker Hub by digest, on Podman here |
| Python | 3.12 both on the runner and in the Ubuntu container |

**Inferred only:** Docker rather than Podman, since this Mac's daemon is not running, and `osixia/openldap` under Docker's file limit. `APPLY.md` says what to try first if that seed fails. No change is made for it.

**Runtime.** The patches add cases and mutants to `crc-guard-test.py`, so it takes longer. The guard's 33 mutants took 935 s on this Mac, measured, where one pass at `fa8c27c` takes 36 s, so its 21 mutants plus the base run would be about 13 min here (computed, not run). To keep it near the 4.5 and 6.5 minutes on the runner, a mutant now stops at its first wrong case. `doc13-test.py` with its block runs and 34 mutants took about a minute here. The runner's own times are CI's to show.

## Proof

The set applied in order to a fresh copy of `repo/`, each patch clean (`logs/final-apply.txt`), then these. Each has its own `logs/final-<name>.txt`, and `logs/final-summary.txt` holds the rc's.

| Suite | Result | Where |
|---|---|---|
| `crc-guard-test.py` | 0 failed; 33 mutants, none surviving, in 935 s | This Mac, Python 3.14, on the same content |
| `crc-scripts-test.sh` | 0 failed | This Mac, and Ubuntu 24.04 in a container (GNU userland), where it failed before |
| `doc13-test.py` | 0 failed; 34 mutants, none surviving | This Mac on bash 5.3, the blocks also on bash 3.2, and Ubuntu 24.04 |
| `doc12-test.py`, `render-test.sh`, `ci-guard.py` | 0 failed | This Mac and Ubuntu 24.04 |
| `secrets-test.sh` on its stub | 0 failed | This Mac and Ubuntu 24.04 |
| `mutate-secrets.py` | 32 mutants, 0 wrong | This Mac |
| `shellcheck` | Clean | This Mac, and the pinned 0.11.0 in Ubuntu 24.04 |
| kubeconform, `-skip Route`, and the render steps | 36 and 31 resources, 2 skipped, 0 invalid | Ubuntu 24.04, the pinned kubeconform and schemas |
| `test_plain_manifests.py`, `test_crc_environment.py`, `test_registry_ca_bundle.py`, `--noconftest` | 51 passed, 4 errors: `fixture 'fresh_db' not found`, as those four need a database | This Mac |
| The same three, with `conftest.py` and a throwaway PostgreSQL 16 | 55 passed | This Mac |
| The whole service suite, on that database | 352 passed, 1 failed: `test_every_shell_script_...` runs `git ls-files`, and an export has no repository | This Mac |
| `crc-backup-test.sh`, the default public image | 0 failed | Podman on this Mac |
| `realm-test.py`, real Keycloak 26.6.4 and an LDAP stand-in | 34 cases, 0 failed, including the new ones | Podman on this Mac |

**Before and after, each test:** `logs/01` to `logs/09`, as `APPLY.md` lists them.

**Containers.** Everything ran under `cmapi-r2-*` on 127.0.0.1 and is gone. `cmapi-test-pg` was not touched. `crc-backup-test.sh` and `realm-test.py` hard-code `cmapi-w1-*`, so they ran on a copy with those names changed, as the brief's limit requires; nothing else in that copy differs, and the patches do not carry the rename.

## What was measured, inferred and not tested

**Measured:** each result in the proof table; wget's text on the pinned image; `http_get`'s failure against a real TLS server; a watch killed with `kill -9`; a bundle failing strict base64 on real certificates, and the registry's check on synthetic ones; realm `cmapi` on community Keycloak 26.6.4 with PostgreSQL 16 and an OpenLDAP stand-in, before and after 09; the same Ubuntu failure as CI's.

**Read from source, not run:** the operator's `HasErrors` (Keycloak 26.6.4, `KeycloakRealmImportController.java`); OVN-Kubernetes's drop ACL ([its design note](https://github.com/ovn-org/ovn-kubernetes/commit/e85a11f98e9c6b690d8b1b2e6a96649653da2314)).

**Inferred:** that CRC's `ca.crt` is a bundle whose certificates trigger N4 ([Red Hat bug 2129668](https://bugzilla.redhat.com/show_bug.cgi?id=2129668) lists its several signers); that RHBK behaves as community 26.6.4 on the `admin-cli` entry and the brute-force fields; that Docker behaves as Podman in the two container tests.

**Not tested:** anything on CRC, by the brief. The kind steps of job `manifests`. The Chrome proofs. A real terminal: the shell's survival was measured in `bash -i` on a pipe and in plain bash, not by pasting into Terminal. Docker itself, in the two container tests.

## Not done, for the coordinator

- **N4's fix is application code,** in `cmapi/src`. `CLAUDE.md` has the coordinator applying reviewer 2's fixes narrowly while authoring no application code, and every pull request saying who wrote what, so the PR should name reviewer 2 for it.
- **Records.** `docs/reviews/`, the tracker and the testing record are not updated, since this is a proposal. Each finding needs its issue under the project's rule: N1, N2, N3, N4 and N5 have none yet.
- `docs/13`'s text outside the steps was changed only where a fix changed what it says.

## The full code of every final fix and test

The nine patches, whole, as `final/` holds them. Each carries its test.

### `01-gnu-stat-first.patch`

````diff
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/tests/ci-guard.py b/deploy/tests/ci-guard.py
--- a/deploy/tests/ci-guard.py	2026-11-06 05:44:00
+++ b/deploy/tests/ci-guard.py	2026-11-06 05:44:02
@@ -26,6 +26,10 @@
 check("deploy/render-test.sh" in runs, "render.sh's result is checked, not only the absence of the placeholder")
 for script in ("deploy/secrets-test.sh", "deploy/tests/ci-guard.py", "deploy/tests/doc12-test.py", "deploy/tests/kind-test-stubbed.sh", "deploy/tests/mutate-secrets.py", "deploy/tests/np-reach-test.sh", "deploy/tests/crc-guard-test.py", "deploy/tests/crc-scripts-test.sh", "deploy/tests/crc-backup-test.sh", "deploy/tests/doc13-test.py", "deploy/tests/realm-test.py"):
     check(script in runs, f"the job runs {script}")
+# #90, twice now: GNU's stat -f writes the file system's details on stdout before it fails, so "stat -f ... || stat -c ..." on Linux gives both. -c goes first, wherever a script reads a mode.
+bsd_first = [f"{os.path.relpath(os.path.join(d, f), ROOT)}:{n}" for d, _, fs in os.walk(os.path.join(ROOT, "deploy")) for f in fs if f.endswith((".sh", ".py")) and f != "ci-guard.py"
+             for n, line in enumerate(open(os.path.join(d, f), errors="replace"), 1) if not line.lstrip().startswith("#") and re.search(r"\bstat -f\b", line) and not re.search(r"\bstat -c\b.*\bstat -f\b", line)]
+check(not bsd_first, f"stat -c before stat -f: {bsd_first}")
 shellchecked = next(s["run"] for s in steps if s.get("name") == "Shellcheck")
 # The chart path's two scripts leave with the charts (Wave 4), and this job has never checked them.
 charts = ("deploy/baseline-crc.sh", "deploy/release-crc.sh")
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/tests/crc-backup-test.sh b/deploy/tests/crc-backup-test.sh
--- a/deploy/tests/crc-backup-test.sh	2026-11-06 05:44:00
+++ b/deploy/tests/crc-backup-test.sh	2026-11-06 05:44:02
@@ -57,7 +57,8 @@
 rc=$(B); [ "$rc" = 0 ] && ok "a backup on the image as it ships" || bad "a backup on the image as it ships: rc $rc: $(tail -2 "$W/out")"
 tail -1 "$W/out" | grep -q '7 realms, read to its end' && ok "it counted the seven realm rows: $(tail -1 "$W/out" | sed 's/^backup in [^:]*: //')" || bad "its last line: $(tail -1 "$W/out")"
 f=$(find "$W/backup" -type f -name 'keycloak-*.dump'); [ -n "$f" ] && ok "one dump in the directory" || bad "no dump"
-m() { stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1"; }; [ "$(m "$W/backup")" = 700 ] && [ "$(m "$f")" = 600 ] && ok "directory 0700, file 0600" || bad "modes $(m "$W/backup") $(m "$f")"
+# The GNU form first: GNU's -f writes the file system's details on stdout before it fails, while BSD's stat refuses -c with nothing on stdout (#90).
+m() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }; [ "$(m "$W/backup")" = 700 ] && [ "$(m "$f")" = 600 ] && ok "directory 0700, file 0600" || bad "modes $(m "$W/backup") $(m "$f")"
 if grep -qF -e "$PW" -e "$f" "$W/out"; then bad "the password or the path reached the output"; else ok "no password and no path in the output"; fi
 if grep -qF "$PW" "$ARGV_LOG"; then bad "the password reached an argument"; else ok "no password on any argument"; fi
 # The file restores: into an empty database, the steps docs/13 gives the owner.
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/tests/crc-scripts-test.sh b/deploy/tests/crc-scripts-test.sh
--- a/deploy/tests/crc-scripts-test.sh	2026-11-06 05:44:00
+++ b/deploy/tests/crc-scripts-test.sh	2026-11-06 05:44:02
@@ -63,7 +63,7 @@
 cat >"$W/bin/skopeo" <<'P'
 #!/usr/bin/env bash
 printf 'skopeo %s\n' "$*" >>"$ARGV_LOG"
-while [ $# -gt 0 ]; do case "$1" in --digestfile) printf 'sha256:aaaa' >"$2"; shift;; --dest-authfile) cp "$2" "$ARGV_LOG.auth"; stat -f '%Lp' "$2" 2>/dev/null >"$ARGV_LOG.mode" || stat -c '%a' "$2" >"$ARGV_LOG.mode"; shift;; esac; shift; done; exit "${STUB_SKOPEO_RC:-0}"
+while [ $# -gt 0 ]; do case "$1" in --digestfile) printf 'sha256:aaaa' >"$2"; shift;; --dest-authfile) cp "$2" "$ARGV_LOG.auth"; stat -c '%a' "$2" 2>/dev/null >"$ARGV_LOG.mode" || stat -f '%Lp' "$2" >"$ARGV_LOG.mode"; shift;; esac; shift; done; exit "${STUB_SKOPEO_RC:-0}"
 P
 cat >"$W/bin/curl" <<'P'
 #!/usr/bin/env bash
@@ -147,7 +147,8 @@
 grep -q 'POSTGRESQL_USER' "$W/out" && ok "--inspect names the variables" || bad "--inspect names nothing"
 want "backup" 0 "$(run "$D/crc-backup.sh")"
 f=$(find "$B" -type f -name 'keycloak-*.dump'); [ -n "$f" ] && ok "a dump in the directory" || bad "no dump"
-m() { stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1"; }; [ "$(m "$B")" = 700 ] && [ "$(m "$f")" = 600 ] && ok "directory 0700, file 0600" || bad "modes $(m "$B") $(m "$f")"
+# The GNU form first: GNU's -f writes the file system's details on stdout before it fails, while BSD's stat refuses -c with nothing on stdout (#90).
+m() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }; [ "$(m "$B")" = 700 ] && [ "$(m "$f")" = 600 ] && ok "directory 0700, file 0600" || bad "modes $(m "$B") $(m "$f")"
 if grep -qF -e "$DUMP_MARK" -e "$f" "$W/out" "$ARGV_LOG"; then bad "the dump's content or path reached the output"; else ok "no content and no path in the output"; fi
 if grep -qE 'pg_dump.*(> *[/a-z]|-f )' "$ARGV_LOG"; then bad "the dump is written inside the pod"; else ok "the dump goes to stdout"; fi
 if grep -qE 'exec (-[a-z]+ )*-t' "$ARGV_LOG"; then bad "a TTY would corrupt the stream"; else ok "no TTY on the stream"; fi
````

### `02-watch-never-dies-silently.patch`

````diff
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/crc-guard.py b/deploy/crc-guard.py
--- a/deploy/crc-guard.py	2026-11-06 05:44:54
+++ b/deploy/crc-guard.py	2026-11-06 05:44:55
@@ -84,7 +84,11 @@
         with urllib.request.urlopen(url, timeout=timeout, context=tls()) as r:
             return r.status, r.read()
     except urllib.error.HTTPError as e:
-        return e.code, e.read()
+        # The status came, the body may not: raised in this handler, the next one could not catch it.
+        try:
+            return e.code, e.read()
+        except (http.client.HTTPException, OSError, ValueError):
+            return e.code, b""
     # HTTPException: a Keycloak going down can cut an answer short, and that must read as no answer, not end the watch.
     except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
         return 0, b""
@@ -219,7 +223,21 @@
     print(f"{now()} {os.path.basename(path)}: KeycloakRealmImport cmapi, realm cmapi, namespace keycloak")
 
 
+def stop_the_run(stop_file: str) -> None:
+    open(stop_file, "a").close()
+
+
 def watch(log: str, stop_file: str, baseline_file: str) -> int:
+    """A watch that ends before LOG.done, for any reason, is one nobody is reading: the run stops. A guard that cannot look never reads as healthy."""
+    try:
+        return follow(log, stop_file, baseline_file)
+    except BaseException as e:
+        stop_the_run(stop_file)
+        print(f"{now()} BREACH, the run is stopped: the watch ended: {type(e).__name__}: {str(e)[:200]}", flush=True)
+        return 1
+
+
+def follow(log: str, stop_file: str, baseline_file: str) -> int:
     base = json.load(open(baseline_file))
     realms = sorted(base["realms"])
     breach_since = None
@@ -233,29 +251,34 @@
             t0 = time.monotonic()
             problems = []
             statuses = {}
-            for r in realms:
-                s = realm_state(r, timeout=3)
-                statuses[r] = s["status"]
-                if s["status"] != 200:
-                    problems.append(f"{r}={s['status']}")
-                elif s["public_key_sha256"] != base["realms"][r]["public_key_sha256"]:
-                    problems.append(f"{r}: public key changed")
+            kc = {}
+            # Every exception, not a list of them: the list is what let this die twice. It logs on, so the outage's length is on record.
             try:
-                kc = pod_state("keycloak-0")
-                b = base["keycloak-0"]
-                if (kc["uid"], kc["restarts"], kc["started"]) != (b["uid"], b["restarts"], b["started"]):
-                    problems.append(f"keycloak-0 restarted: {kc}")
-                elif not kc["ready"]:
-                    problems.append("keycloak-0 not Ready")
-            except (Stop, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:
-                kc = {}
-                problems.append(f"keycloak-0 unreadable: {str(e)[:120]}")
+                for r in realms:
+                    s = realm_state(r, timeout=3)
+                    statuses[r] = s["status"]
+                    if s["status"] != 200:
+                        problems.append(f"{r}={s['status']}")
+                    elif s["public_key_sha256"] != base["realms"][r]["public_key_sha256"]:
+                        problems.append(f"{r}: public key changed")
+                try:
+                    kc = pod_state("keycloak-0")
+                    b = base["keycloak-0"]
+                    if (kc["uid"], kc["restarts"], kc["started"]) != (b["uid"], b["restarts"], b["started"]):
+                        problems.append(f"keycloak-0 restarted: {kc}")
+                    elif not kc["ready"]:
+                        problems.append("keycloak-0 not Ready")
+                except (Stop, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:
+                    kc = {}
+                    problems.append(f"keycloak-0 unreadable: {str(e)[:120]}")
+            except Exception as e:
+                problems.append(f"the watch could not look: {type(e).__name__}: {str(e)[:120]}")
             say(f"realms {statuses} keycloak-0 {kc.get('restarts')}/{kc.get('ready')} {'BREACH ' + '; '.join(problems) if problems else 'ok'}")
             down = any(s != 200 for s in statuses.values()) or not kc.get("ready")
             if problems and breach_since is None:
                 breach_since = time.monotonic()
                 rc = 3
-                open(stop_file, "a").close()
+                stop_the_run(stop_file)
                 say("STOP: every cmapi step stops now. cmapi takes no action on Keycloak: no delete, no restart. Report to the owner")
                 print(f"{now()} BREACH, the run is stopped: {'; '.join(problems)}", flush=True)
             if breach_since is not None:
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/tests/crc-guard-test.py b/deploy/tests/crc-guard-test.py
--- a/deploy/tests/crc-guard-test.py	2026-11-06 05:44:54
+++ b/deploy/tests/crc-guard-test.py	2026-11-06 05:46:09
@@ -54,6 +54,9 @@
         if code == "short":                                 # a server going down: the answer stops before its length
             self.send_response(200); self.send_header("Content-Length", "1000"); self.end_headers(); self.wfile.write(b"{"); self.wfile.flush(); self.close_connection = True
             return
+        if code == "short503":                              # the same, on an error: urllib reads this body inside its HTTPError handler
+            self.send_response(503); self.send_header("Content-Length", "1000"); self.end_headers(); self.wfile.write(b"<"); self.wfile.flush(); self.close_connection = True
+            return
         if code == "garbage":                               # not HTTP at all
             self.wfile.write(b"not http\r\n\r\n"); self.wfile.flush(); self.close_connection = True
             return
@@ -122,7 +125,7 @@
     yield "issuer: a certificate from another CA is neither", run(guard, "issuer", CMAPI_CRC_CA=os.path.join(W, "other.crt")).returncode == 20
     yield "no CA named: it stops, TLS is never off", run(guard, "issuer", CMAPI_CRC_CA="").returncode != 0 and run(guard, "issuer", CMAPI_CRC_CA="").returncode != 10
     yield "issuer: nothing listening is neither", run(guard, "issuer", CMAPI_KEYCLOAK_URL="https://localhost:9").returncode == 20
-    for label, answer in (("an answer cut short", ["short", ""]), ("an answer that is not HTTP", ["garbage", ""]), ("JSON that is not an object", [200, '["cmapi"]'])):
+    for label, answer in (("an answer cut short", ["short", ""]), ("an error answer cut short", ["short503", ""]), ("an answer that is not HTTP", ["garbage", ""]), ("JSON that is not an object", [200, '["cmapi"]'])):
         s = base_state(); s["http"]["cmapi"] = answer; save(s)
         r = run(guard, "issuer"); yield f"issuer: {label} is neither, with no traceback", r.returncode == 20 and "Traceback" not in r.stderr
     save(base_state())
@@ -197,13 +200,13 @@
     # the watch
     save(base_state()); run(guard, "snapshot", a)
     log = os.path.join(W, "w.log"); stop = os.path.join(W, "stop")
-    def watch(mut, seconds=1.2):
+    def watch(mut, seconds=1.2, baseline=None, **env):
         for x in (log, log + ".done", stop):
             if os.path.exists(x): os.unlink(x)
         s = base_state(); mut(s); save(s)
-        p = subprocess.Popen([sys.executable, guard, "watch", log, stop, a], env=ENV, stdout=subprocess.PIPE, text=True)
+        p = subprocess.Popen([sys.executable, guard, "watch", log, stop, baseline or a], env={**ENV, **env}, stdout=subprocess.PIPE, text=True)
         time.sleep(seconds); open(log + ".done", "w").close(); out, _ = p.communicate(timeout=20)
-        return p.returncode, open(log).read(), out
+        return p.returncode, open(log).read() if os.path.exists(log) else "", out
     rc, text, _ = watch(lambda s: None, 0.5)
     yield "the watch stays quiet when all is well", rc == 0 and "BREACH" not in text and not os.path.exists(stop)
     yield "the watch's lines are timestamped", text.startswith("20") and "realms {" in text
@@ -215,6 +218,16 @@
     yield "an answer cut short stops the run, and the watch lives", rc == 3 and "BREACH corp=0" in text and "watch ended rc=3" in text
     rc, text, _ = watch(lambda s: s["http"].__setitem__("corp", ["garbage", ""]))
     yield "an answer that is not HTTP stops the run, and the watch lives", rc == 3 and "BREACH corp=0" in text and "watch ended rc=3" in text
+    rc, text, _ = watch(lambda s: s["http"].__setitem__("corp", ["short503", ""]))
+    yield "an error answer cut short stops the run, and the watch lives", rc == 3 and os.path.exists(stop) and "BREACH corp=503" in text and "watch ended rc=3" in text
+    # Past the listed cases: the CA file gone mid-run (Stop, from tls()), and an exception nobody wrote a case for (a baseline with no key).
+    rc, text, _ = watch(lambda s: None, CMAPI_CRC_CA=os.path.join(W, "no-such-ca"))
+    yield "a CA file gone mid-run stops the run, and the watch lives", rc == 3 and os.path.exists(stop) and "the watch could not look" in text and "watch ended rc=3" in text
+    odd = os.path.join(W, "odd.json"); json.dump({**json.load(open(a)), "realms": {"corp": {}}}, open(odd, "w"))
+    rc, text, _ = watch(lambda s: None, baseline=odd)
+    yield "an exception nobody listed stops the run, and the watch lives", rc == 3 and os.path.exists(stop) and "the watch could not look: KeyError" in text and "watch ended rc=3" in text
+    rc, _, out = watch(lambda s: None, 0.2, baseline=os.path.join(W, "no-such-baseline"))
+    yield "a watch that cannot begin stops the run", rc == 1 and os.path.exists(stop) and "the watch ended" in out
     rc, text, _ = watch(lambda s: s["pods"].__setitem__("keycloak-0", {"metadata": {}}))
     yield "an unreadable keycloak-0 stops the run, and the watch lives", rc == 3 and "keycloak-0 unreadable" in text and "watch ended rc=3" in text
     rc, text, _ = watch(lambda s: s["http"]["corp"].__setitem__(1, json.dumps({"realm": "corp", "public_key": "x"})))
@@ -269,6 +282,9 @@
     "a breach during the import does not stop the run": ("if os.path.exists(stop_file):\n                # A running", "if False:\n                # A running"),
     "the realm name is not checked": ('r"^    realm: cmapi$")', 'r"^  realm:$")'),
     "a second document is allowed": ('if re.search(r"^---", text, re.M) or re.search(r"^\\.\\.\\.", text, re.M):', "if False:"),
+    "an error answer cut short loses its status": ('            return e.code, b""', "            raise"),
+    "a surprise ends the watch": ("            except Exception as e:\n                problems.append(f\"the watch could not look", "            except ZeroDivisionError as e:\n                problems.append(f\"the watch could not look"),
+    "a watch that ends leaves no stop file": ("        stop_the_run(stop_file)\n        print(f\"{now()} BREACH, the run is stopped: the watch ended", "        print(f\"{now()} BREACH, the run is stopped: the watch ended"),
     "the watch ignores a restart": ('problems.append(f"keycloak-0 restarted: {kc}")', "pass"),
     "the watch never reports": ("if down and waited >= REPORT_AFTER_SECONDS and not reported:", "if False:"),
     "the watch does not stop the run": ("open(stop_file, \"a\").close()", "pass"),
````

### `03-secrets-issuer-names-cmapi.patch`

````diff
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/secrets-test.sh b/deploy/secrets-test.sh
--- a/deploy/secrets-test.sh	2026-11-06 05:48:14
+++ b/deploy/secrets-test.sh	2026-11-06 05:48:15
@@ -195,6 +195,11 @@
 r=$(runi 000 '' 60); expect "11g a certificate failure is not absent" 1 "$r"; none_written 11g
 grep -q -- '--cacert' "$CURL_LOG" || { echo "  FAIL 11: the CA file was not used"; fails=$((fails+1)); }
 if grep -qE -- '(^| )(-k|--insecure)( |$)' "$CURL_LOG"; then echo "  FAIL 11: TLS verification was turned off"; fails=$((fails+1)); fi
+# Keycloak's own 404 is what a request for any other realm gets too, so the URL itself has to name this realm. The curl stub would say "absent" to each.
+for bad in https://kc.test/realms/not-cmapi https://kc.test/realms/cmapi/ 'https://kc.test/realms/not-cmapi?x=/realms/cmapi' 'https://kc.test/realms/not-cmapi#/realms/cmapi' http://kc.test/realms/cmapi https://kc.test/x/realms/cmapi; do
+  : >"$CURL_LOG"; r=$(PATH="$W/bin:$PATH" ISSUER_CODE=404 ISSUER_BODY='{"error":"Realm does not exist"}' "$S" --namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind --issuer "$bad" --ca-file "$W/ca.pem" >"$T" 2>&1; echo "rc=$? $(tail -1 "$T" | cut -c1-140)")
+  expect "11j --issuer $bad stops" 2 "$r"; none_written "11j $bad"; [ ! -s "$CURL_LOG" ] || { echo "  FAIL 11j: it asked $bad"; fails=$((fails+1)); }
+done
 r=$(runi 404 '{"error":"Realm does not exist"}'); expect "11h Keycloak's own 404: generates" 0 "$r"; [ "$(h)" != none ] || { echo "  FAIL 11h: nothing written"; fails=$((fails+1)); }
 : >"$CURL_LOG"; r=$(runi 503 'down'); expect "11i Secrets present: nothing to mint, Keycloak not needed" 0 "$r"; [ ! -s "$CURL_LOG" ] || { echo "  FAIL 11i: asked the issuer when nothing was to be minted"; fails=$((fails+1)); }
 collect
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/secrets.sh b/deploy/secrets.sh
--- a/deploy/secrets.sh	2026-11-06 05:48:14
+++ b/deploy/secrets.sh	2026-11-06 05:48:15
@@ -30,6 +30,8 @@
   --test-users) TEST_USERS=true; shift;;
   *) echo "unknown argument $1" >&2; exit 2;; esac; done
 if [ "$ISSUER_CHECK" = true ] && [ -z "$ISSUER" ]; then echo "ERROR: --issuer is required (or --no-issuer-check on a cluster with no Keycloak)" >&2; exit 2; fi
+# The whole URL, and realm cmapi: a 404 for any other realm is also Keycloak's own, and would read as "cmapi is absent" and mint. A glob on the end would pass ?x=/realms/cmapi.
+if [ "$ISSUER_CHECK" = true ] && ! [[ "$ISSUER" =~ ^https://[^/?#]+/realms/cmapi$ ]]; then echo "ERROR: --issuer must be https://<Keycloak host>/realms/cmapi, not $ISSUER" >&2; exit 2; fi
 if [ -n "$CA_FILE" ] && [ ! -r "$CA_FILE" ]; then echo "ERROR: cannot read the CA file $CA_FILE" >&2; exit 2; fi
 # shellcheck disable=SC2086  # KUBECTL may carry --kubeconfig
 kc() { $KUBECTL "$@"; }
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/tests/mutate-secrets.py b/deploy/tests/mutate-secrets.py
--- a/deploy/tests/mutate-secrets.py	2026-11-06 05:48:14
+++ b/deploy/tests/mutate-secrets.py	2026-11-06 05:48:15
@@ -65,6 +65,8 @@
     "X anything but a 200 reads as absent": [('        *) echo "ERROR: cannot tell whether the realm exists at $ISSUER: $state. Nothing is generated. Run this again when Keycloak answers." >&2; exit 1 ;;', '        *) ;;')],
     "Y any 404 reads as absent": [("""elif c=="404" and d=={"error":"Realm does not exist"}: print("absent")""", """elif c=="404": print("absent")""")],
     "Z a curl failure reads as absent": [('if [ "$rc" -ne 0 ]; then rm -f "$body"; echo "no answer (curl rc $rc)"; return; fi', 'if [ "$rc" -ne 0 ]; then rm -f "$body"; echo absent; return; fi')],
+    "AD an issuer naming another realm is asked": [('if [ "$ISSUER_CHECK" = true ] && ! [[ "$ISSUER" =~ ^https://[^/?#]+/realms/cmapi$ ]]; then', 'if false; then')],
+    "AE a glob on the end of the issuer": [('! [[ "$ISSUER" =~ ^https://[^/?#]+/realms/cmapi$ ]]', '! [[ "$ISSUER" =~ /realms/cmapi$ ]]')],
     "AA forgetting the flag skips the check": [('if [ "$ISSUER_CHECK" = true ] && [ -z "$ISSUER" ]; then echo "ERROR: --issuer is required (or --no-issuer-check on a cluster with no Keycloak)" >&2; exit 2; fi', 'if [ -z "$ISSUER" ]; then ISSUER_CHECK=false; fi')],
     "AB verification off": [('code=$(curl -sS -m 15 ${CA_FILE:+--cacert "$CA_FILE"} -o', 'code=$(curl -k -sS -m 15 ${CA_FILE:+--cacert "$CA_FILE"} -o')],
     "AC the issuer is asked after the first write": [
````

### `04-proof-blocked-is-not-broken.patch`

````diff
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/crc-proof.sh b/deploy/crc-proof.sh
--- a/deploy/crc-proof.sh	2026-11-06 05:51:06
+++ b/deploy/crc-proof.sh	2026-11-06 05:51:06
@@ -59,7 +59,11 @@
 oc_ wait pod/np-probe -n "$probe_ns" --for=condition=Ready --timeout=120s >/dev/null || fail "the probe pod did not start"
 # The control first: the mockup is in the same namespace and no policy selects it, so this path must work, or "blocked" below would prove nothing.
 oc_ exec np-probe -n "$probe_ns" -- wget -q -O /dev/null --timeout=5 http://cmapi-mockup.cmapi.svc:8080/portal.html >/dev/null 2>&1 || fail "the probe cannot reach the unselected mockup: the check below would prove nothing"
-if oc_ exec np-probe -n "$probe_ns" -- wget -q -O /dev/null --timeout=5 http://cmapi-api.cmapi.svc:8080/readyz 2>/dev/null; then fail "another namespace reaches 8080: the policy is not enforced"; fi
+# Failing is not being blocked: a dropped connection is this image's "download timed out", and a bad address, a refused connection or oc exec itself failing each say something else (measured, BusyBox 1.37).
+if blocked=$(oc_ exec np-probe -n "$probe_ns" -- wget -q -O /dev/null --timeout=5 http://cmapi-api.cmapi.svc:8080/readyz 2>&1 >/dev/null); then fail "another namespace reaches 8080: the policy is not enforced"; fi
+case "$blocked" in *"wget: download timed out"*) ;; *) fail "the probe of the api failed, but not by a dropped connection, so this says nothing about the policy: ${blocked:0:200}";; esac
+# A server that accepts and then hangs times out the same way (measured), so the api must answer the router right after that timeout.
+[ "$(c -o /dev/null -w '%{http_code}' "$API/readyz")" = 200 ] || fail "the api does not answer the router after the probe: the timeout may be the api's, not the policy's"
 say "another namespace's pod reaches the mockup and is blocked from the api (the policy is enforced on OVN-Kubernetes)"
 cleanup_probe; trap - EXIT
 
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/tests/crc-scripts-test.sh b/deploy/tests/crc-scripts-test.sh
--- a/deploy/tests/crc-scripts-test.sh	2026-11-06 05:51:06
+++ b/deploy/tests/crc-scripts-test.sh	2026-11-06 05:51:06
@@ -46,7 +46,7 @@
 print(json.dumps({"items":[pod("a","api"),pod("w","worker"),pod("m","mockup")]}))'; exit 0;;
   "get networkpolicy cmapi-metrics"*) printf '2026-11-06T09:00:00Z'; exit 0;;
   "exec np-probe"*"cmapi-mockup"*) exit "${STUB_CONTROL_RC:-0}";;
-  "exec np-probe"*"cmapi-api"*) exit "${STUB_BLOCK_RC:-1}";;
+  "exec np-probe"*"cmapi-api"*) : >"$ARGV_LOG.probed"; echo "${STUB_BLOCK_ERR-wget: download timed out}" >&2; exit "${STUB_BLOCK_RC:-1}";;
   "get secret cmapi-test-users"*) printf '%s' "$SECRETVAL" | base64; exit 0;;
   "auth can-i"*"--all-namespaces"*) echo "${STUB_READER_WIDE:-no}"; exit 0;;
   "auth can-i"*"cmapi-reader"*) echo yes; exit 0;;
@@ -73,7 +73,7 @@
   url=; code=; for a in "$@"; do case "$a" in http*) url=$a;; esac; done; case "$*" in *-w*) wants=1;; *) wants=;; esac
   [ ! -p /dev/stdin ] || cat >/dev/null
   case "$url" in
-    */readyz) code=${STUB_READYZ:-200}; case "$url" in http://*) code=302;; esac;;
+    */readyz) code=${STUB_READYZ:-200}; [ ! -e "$ARGV_LOG.probed" ] || code=${STUB_READYZ_AFTER:-$code}; case "$url" in http://*) code=302;; esac;;
     */api/v1/version) printf '{"commit":"%s"}' "${STUB_COMMIT:-$(git -C "$REPO" rev-parse --short=10 HEAD)}"; exit 0;;
     */metrics) code=${STUB_METRICS:-404};;
     */api/v1/me) case "$*" in *--config*) printf '{"username":"bot-user","roles":["cmapi-onboarding"]}'; exit 0;; *) code=401;; esac;;
@@ -168,7 +168,7 @@
 export STUB_PROOF=1 CMAPI_PROOF_SCRAPE_TRIES=1 CMAPI_CRC_CA=$W/mac.pem; P=$W/rendered; mkdir -p "$P"; printf 'image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:aaaa\n' >"$P/IMAGE"
 want "proof passes when all is right" 0 "$(run "$D/crc-proof.sh" "$P")"; [ "$(tail -1 "$W/out")" = "proof: all passed" ] || bad "the proof's last line: $(tail -1 "$W/out")"
 no_secret "$W/out" "proof"
-pstop() { local label=$1; shift; local got; got=$(: >"$ARGV_LOG"; env "$@" "$D/crc-proof.sh" "$P" >"$W/out" 2>&1; echo $?); [ "$got" != 0 ] && ok "proof fails: $label" || bad "proof did not fail: $label"; }
+pstop() { local label=$1; shift; local got; rm -f "$ARGV_LOG.probed"; got=$(: >"$ARGV_LOG"; env "$@" "$D/crc-proof.sh" "$P" >"$W/out" 2>&1; echo $?); [ "$got" != 0 ] && ok "proof fails: $label" || bad "proof did not fail: $label"; }
 pstop "a pod under another SCC" STUB_SCC=anyuid
 pstop "a restart" STUB_RESTARTS=1
 pstop "another image running" STUB_IMAGE_ID=sha256:bbbb
@@ -178,6 +178,12 @@
 pstop "/metrics on the Route" STUB_METRICS=200
 pstop "the probe reaching the api: the policy not enforced" STUB_BLOCK_RC=0
 pstop "the control failing: the block would prove nothing" STUB_CONTROL_RC=1
+pstop "the api's name not resolving: broken, not blocked" "STUB_BLOCK_ERR=wget: bad address 'cmapi-api.cmapi.svc:8080'"
+pstop "a refused connection: broken, not blocked" "STUB_BLOCK_ERR=wget: can't connect to remote host (10.0.0.1): Connection refused"
+pstop "the api answering 503: not blocked" "STUB_BLOCK_ERR=wget: server returned error: HTTP/1.0 503 down"
+pstop "oc exec failing: nothing was probed" "STUB_BLOCK_ERR=Error from server: error dialing backend: EOF"
+pstop "no reason at all" STUB_BLOCK_ERR=
+pstop "a timeout from an api that then does not answer the router" STUB_READYZ_AFTER=503
 pstop "a worker that may write" STUB_WRITER=yes
 pstop "a reader reading Secrets" STUB_READER_WIDE=yes
 pstop "a plan that passes" STUB_PLAN=200
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/docs/13-crc-deployment.md b/docs/13-crc-deployment.md
--- a/docs/13-crc-deployment.md	2026-11-06 05:51:06
+++ b/docs/13-crc-deployment.md	2026-11-06 05:51:06
@@ -311,7 +311,7 @@
 | Admitted under `restricted-v2` and started under the policy | Each pod's `openshift.io/scc`, 0 restarts, `status.startTime` after the policy's `creationTimestamp` | `crc-proof.sh` |
 | `/readyz` 200 | `curl --cacert` through the Route | `crc-proof.sh` |
 | `/api/v1/version` names the built commit | Equals `git rev-parse --short=10 HEAD`; the api's and worker's `imageID` hold the digest | `crc-proof.sh` |
-| The Route through the policy | A Route that answers proves nothing unless something was blocked. A throwaway namespace's pod must reach the mockup (the control), and must be blocked from the api. `/metrics` is 404 through the Route. Plain HTTP is redirected | `crc-proof.sh` |
+| The Route through the policy | A Route that answers proves nothing unless something was blocked. A throwaway namespace's pod must reach the mockup (the control), and must be blocked from the api: wget's own `download timed out`, what a dropped connection gives on the probe's image (measured), with the api answering the router straight after. A bad address, a refused connection or a failed `oc exec` fails the proof, since none of them says anything about the policy. OVN-Kubernetes's documentation describes a drop, not a reset; the first run measures it, and a reset would stop here to be read. `/metrics` is 404 through the Route. Plain HTTP is redirected | `crc-proof.sh` |
 | `/docs` signed in, `GET /api/v1/me` | Open `https://cmapi-api.apps-crc.testing/docs`, Authorize, sign in as local user `ola`, Try it out on `/api/v1/me`, screenshot. Her password goes to the clipboard, never the screen: `oc get secret cmapi-test-users -n cmapi -o 'jsonpath={.data.ola}' \| base64 -d \| pbcopy`. `crc-proof.sh` signs in `bot-user` by password grant | Chrome and `crc-proof.sh` |
 | A login through LDAP federation | The owner, as an LDAP person; `/me` shows `/cmapi/cmapi-*` groups and `employeeId` equal to `uidNumber`, screenshot. Before it, `LDAP full sync: 200` with `added` above 0 in the Job's log | Chrome |
 | The mockup, captioned as static | `https://cmapi-mockup.apps-crc.testing/portal.html`, screenshot captioned "static mockup, no API behind it" | Chrome |
````

### `05-gate-sees-a-dead-watch.patch`

````diff
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/crc-guard.py b/deploy/crc-guard.py
--- a/deploy/crc-guard.py	2026-11-06 07:03:30
+++ b/deploy/crc-guard.py	2026-11-06 07:03:30
@@ -9,7 +9,8 @@
   snapshot FILE                the other realms and their imports, keycloak-0, postgres-0, the Keycloak CR, with no credential
   compare BEFORE AFTER         stop on any difference
   watch LOG STOPFILE BASELINE  poll every realm every 5 s until LOG.done appears; on a breach write STOPFILE and report at 300 s
-  gate STOPFILE                exit 1 if the watch has stopped the run
+  gate STOPFILE                exit 1 if the run is stopped, or a watch that began is no longer looking
+  watching STOPFILE            exit 1 unless the watch of this run has begun and is looking
   import-wait STOPFILE         follow our import; withdraw it, by name, if it has not started in time
 
 Exit codes: 0 fine, 1 stop, 2 usage."""
@@ -45,6 +46,9 @@
 REPORT_AFTER_SECONDS = float(os.environ.get("CMAPI_GUARD_REPORT_AFTER", "300"))
 SCHEDULE_DEADLINE = float(os.environ.get("CMAPI_GUARD_SCHEDULE_DEADLINE", "300"))
 RUN_DEADLINE = float(os.environ.get("CMAPI_GUARD_RUN_DEADLINE", "300"))
+# Longer than one round of the watch can take: five realms at 3 s, oc's 60 s, the poll.
+WATCH_STALE_SECONDS = float(os.environ.get("CMAPI_GUARD_WATCH_STALE", "120"))
+WATCH_START_SECONDS = float(os.environ.get("CMAPI_GUARD_WATCH_START", "15"))
 
 
 class Stop(Exception):
@@ -227,6 +231,39 @@
     open(stop_file, "a").close()
 
 
+def why_stopped(stop_file: str) -> str | None:
+    """Why nothing more may run, or None. The stop file, or a watch that began and is no longer looking: killed, hung or asleep with the Mac, it writes nothing,
+    so the file alone would read that blindness as all well. No heartbeat means it has not begun, or ended cleanly."""
+    if os.path.exists(stop_file):
+        return f"this run is stopped ({stop_file}); nothing more runs until the owner has been told"
+    alive = stop_file + ".alive"
+    try:
+        with open(alive) as f:
+            pid = int(f.read())
+            age = time.time() - os.fstat(f.fileno()).st_mtime
+    except FileNotFoundError:
+        return None
+    try:
+        os.kill(pid, 0)
+    except (ProcessLookupError, PermissionError):           # PermissionError: another user's process has that number now, so it is not the watch
+        return f"the watch (pid {pid}) is not running, so nothing is watching Keycloak"
+    if age > WATCH_STALE_SECONDS:
+        return f"the watch (pid {pid}) has not looked for {int(age)} s"
+    return None
+
+
+def watching(stop_file: str) -> None:
+    t0 = time.monotonic()
+    while not os.path.exists(stop_file + ".alive"):
+        if os.path.exists(stop_file) or time.monotonic() - t0 > WATCH_START_SECONDS:
+            raise Stop("the watch did not begin; read its output")
+        time.sleep(0.1)
+    why = why_stopped(stop_file)
+    if why:
+        raise Stop(why)
+    print(f"{now()} the watch is looking")
+
+
 def watch(log: str, stop_file: str, baseline_file: str) -> int:
     """A watch that ends before LOG.done, for any reason, is one nobody is reading: the run stops. A guard that cannot look never reads as healthy."""
     try:
@@ -240,6 +277,11 @@
 def follow(log: str, stop_file: str, baseline_file: str) -> int:
     base = json.load(open(baseline_file))
     realms = sorted(base["realms"])
+    alive = stop_file + ".alive"
+    # Whole or not at all: gate and watching read it at any moment.
+    with open(alive + ".new", "w") as f:
+        f.write(str(os.getpid()))
+    os.replace(alive + ".new", alive)
     breach_since = None
     reported = recovered = False
     rc = 0
@@ -249,6 +291,7 @@
         say(f"watch: every {POLL_SECONDS:g} s, realms {realms}")
         while not os.path.exists(log + ".done"):
             t0 = time.monotonic()
+            os.utime(alive)
             problems = []
             statuses = {}
             kc = {}
@@ -292,6 +335,7 @@
                     say(f"Keycloak answers again after {int(waited)} s; the run stays stopped")
             time.sleep(max(0.0, POLL_SECONDS - (time.monotonic() - t0)))
         say(f"watch ended rc={rc}")
+    os.unlink(alive)
     return rc
 
 
@@ -331,7 +375,7 @@
         if condition(kri, "Done") == "true" and condition(kri, "HasErrors") != "true":
             state = issuer_state()
             print(f"{now()} import Done after {int(time.monotonic() - t0)} s; realm cmapi is {state}")
-            if os.path.exists(stop_file):
+            if why_stopped(stop_file):
                 # A running import is left to finish, but a breach during it still stops what comes next.
                 print(f"{now()} the watch stopped the run while the import ran; nothing more runs until the owner has been told", flush=True)
                 return 1
@@ -340,7 +384,7 @@
             # The Job has no backoffLimit of its own (buildJob sets none), so Kubernetes' default of 6 would start more pods.
             withdraw("the import failed; this stops the Job's further attempts")
             return 1
-        if not started and os.path.exists(stop_file):
+        if not started and why_stopped(stop_file):
             withdraw("the run is stopped and the import has not started")
             return 1
         if not started and time.monotonic() - t0 > SCHEDULE_DEADLINE:
@@ -364,6 +408,7 @@
     p = sub.add_parser("compare"); p.add_argument("before"); p.add_argument("after")
     p = sub.add_parser("watch"); p.add_argument("log"); p.add_argument("stop_file"); p.add_argument("baseline")
     p = sub.add_parser("gate"); p.add_argument("stop_file")
+    p = sub.add_parser("watching"); p.add_argument("stop_file")
     p = sub.add_parser("import-wait"); p.add_argument("stop_file")
     a = ap.parse_args()
     try:
@@ -390,8 +435,11 @@
         elif a.cmd == "watch":
             return watch(a.log, a.stop_file, a.baseline)
         elif a.cmd == "gate":
-            if os.path.exists(a.stop_file):
-                raise Stop("the watch has stopped this run; nothing more runs until the owner has been told")
+            why = why_stopped(a.stop_file)
+            if why:
+                raise Stop(why)
+        elif a.cmd == "watching":
+            watching(a.stop_file)
         elif a.cmd == "import-wait":
             return import_wait(a.stop_file)
     except Stop as e:
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/tests/crc-guard-test.py b/deploy/tests/crc-guard-test.py
--- a/deploy/tests/crc-guard-test.py	2026-11-06 07:03:30
+++ b/deploy/tests/crc-guard-test.py	2026-11-06 07:03:30
@@ -87,7 +87,7 @@
 open(KIND, "w").write('#!/bin/sh\n[ -z "$STUB_KIND" ] || echo "$STUB_KIND"\n'); os.chmod(KIND, 0o755)
 ENV = {**os.environ, "CMAPI_OC": os.path.join(W, "oc"), "STUB_STATE": STATE, "STUB_ARGV": ARGV, "CMAPI_CRC_CA": os.path.join(W, "ca.crt"),
        "CMAPI_KEYCLOAK_URL": f"https://localhost:{PORT}", "PATH": os.path.join(W, "bin") + ":" + os.environ["PATH"],
-       "CMAPI_GUARD_POLL": "0.1", "CMAPI_GUARD_REPORT_AFTER": "0.5", "CMAPI_GUARD_SCHEDULE_DEADLINE": "0.4", "CMAPI_GUARD_RUN_DEADLINE": "0.4"}
+       "CMAPI_GUARD_POLL": "0.1", "CMAPI_GUARD_REPORT_AFTER": "0.5", "CMAPI_GUARD_SCHEDULE_DEADLINE": "0.4", "CMAPI_GUARD_RUN_DEADLINE": "0.4", "CMAPI_GUARD_WATCH_START": "0.5"}
 
 
 def run(guard, *args, **env):
@@ -201,7 +201,7 @@
     save(base_state()); run(guard, "snapshot", a)
     log = os.path.join(W, "w.log"); stop = os.path.join(W, "stop")
     def watch(mut, seconds=1.2, baseline=None, **env):
-        for x in (log, log + ".done", stop):
+        for x in (log, log + ".done", stop, stop + ".alive"):
             if os.path.exists(x): os.unlink(x)
         s = base_state(); mut(s); save(s)
         p = subprocess.Popen([sys.executable, guard, "watch", log, stop, baseline or a], env={**ENV, **env}, stdout=subprocess.PIPE, text=True)
@@ -237,12 +237,45 @@
     yield "gate: stopped", run(guard, "gate", stop).returncode == 1
     if os.path.exists(stop): os.unlink(stop)
     yield "gate: open", run(guard, "gate", stop).returncode == 0
+    # A watch that says nothing because it is gone: the stop file alone would read that as all well.
+    def wait_for(path):
+        for _ in range(100):
+            if os.path.exists(path): return True
+            time.sleep(0.05)
+        return False
+    for x in (log, log + ".done", stop, stop + ".alive"):
+        if os.path.exists(x): os.unlink(x)
+    save(base_state())
+    yield "watching: no watch is a stop", run(guard, "watching", stop).returncode == 1
+    p = subprocess.Popen([sys.executable, guard, "watch", log, stop, a], env=ENV, stdout=subprocess.DEVNULL)
+    # Read before any yield: a mutant ends at its first wrong case, and a watch left running here would never end.
+    up = wait_for(stop + ".alive")
+    began = up and run(guard, "watching", stop).returncode == 0
+    open_while_looking = run(guard, "gate", stop).returncode == 0
+    beats = False
+    if up:
+        old = time.time() - 1000; os.utime(stop + ".alive", (old, old)); time.sleep(0.5); beats = os.stat(stop + ".alive").st_mtime > old + 500
+    p.kill(); p.wait()
+    yield "watching: a watch that began", began
+    yield "gate: open while the watch looks", open_while_looking
+    yield "the watch beats, every round", beats
+    yield "gate: a killed watch stops the run, with no stop file", not os.path.exists(stop) and run(guard, "gate", stop).returncode == 1
+    yield "watching: a killed watch is a stop", run(guard, "watching", stop).returncode == 1
+    open(stop + ".alive", "w").write(str(os.getpid())); old = time.time() - 121; os.utime(stop + ".alive", (old, old))
+    yield "gate: a hung watch stops the run", run(guard, "gate", stop, CMAPI_GUARD_WATCH_STALE="120").returncode == 1
+    os.utime(stop + ".alive")
+    yield "gate: a watch that looked just now passes", run(guard, "gate", stop, CMAPI_GUARD_WATCH_STALE="120").returncode == 0
+    os.unlink(stop + ".alive")
+    rc, text, _ = watch(lambda s: None, 0.5)
+    yield "a watch that ended cleanly leaves the gate open", rc == 0 and not os.path.exists(stop + ".alive") and run(guard, "gate", stop).returncode == 0
     # the import's wait, and its withdrawal: only ever our own, by name
-    def waits(our, pods, stop_set=False):
+    def waits(our, pods, stop_set=False, watch_gone=False, **env):
         open(ARGV, "w").close(); s = base_state(); s["our_import"] = our; s["import_pods"] = pods; save(s)
         if os.path.exists(stop): os.unlink(stop)
         if stop_set: open(stop, "w").close()
-        r = run(guard, "import-wait", stop); deletes = [l.strip() for l in open(ARGV) if l.startswith("delete")]
+        if watch_gone: open(stop + ".alive", "w").write("999999")
+        r = run(guard, "import-wait", stop, **env); deletes = [l.strip() for l in open(ARGV) if l.startswith("delete")]
+        if watch_gone: os.unlink(stop + ".alive")
         return r.returncode, deletes
     only_ours = ["delete keycloakrealmimport cmapi -n keycloak --wait=true --timeout=60s"]
     pending = {"status": {"phase": "Pending"}}; running = {"status": {"phase": "Running", "containerStatuses": [{"state": {"running": {}}}]}}
@@ -252,6 +285,7 @@
     s = base_state(); s["http"]["cmapi"] = [200, '{"realm":"cmapi","public_key":"k"}']; base_http = s["http"]
     rc, d = waits(started, [pending]); yield "not started by the deadline: withdrawn, by name only", rc == 1 and d == only_ours
     rc, d = waits(started, [], stop_set=True); yield "the run stopped, not started: withdrawn", rc == 1 and d == only_ours
+    rc, d = waits(started, [], watch_gone=True, CMAPI_GUARD_SCHEDULE_DEADLINE="60"); yield "the watch gone, not started: withdrawn", rc == 1 and d == only_ours
     rc, d = waits(started, [running]); yield "running too long: reported, never interrupted", rc == 1 and d == []
     rc, d = waits(errors, [{"status": {"phase": "Failed", "containerStatuses": [{"state": {"terminated": {}}}]}}]); yield "failed: withdrawn, so the Job does not try again", rc == 1 and d == only_ours
     open(ARGV, "w").close(); s = base_state(); s["our_import"] = done; s["import_pods"] = [running]; s["http"]["cmapi"] = base_http["cmapi"]; save(s)
@@ -279,12 +313,18 @@
     "no principal check": ("if user not in PRINCIPALS:", "if False:"),
     "an answer cut short ends the watch": ("except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):", "except (urllib.error.URLError, OSError, ValueError):"),
     "an unreadable pod ends the watch": ("except (Stop, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:", "except Stop as e:"),
-    "a breach during the import does not stop the run": ("if os.path.exists(stop_file):\n                # A running", "if False:\n                # A running"),
+    "a breach during the import does not stop the run": ("if why_stopped(stop_file):\n                # A running", "if False:\n                # A running"),
     "the realm name is not checked": ('r"^    realm: cmapi$")', 'r"^  realm:$")'),
     "a second document is allowed": ('if re.search(r"^---", text, re.M) or re.search(r"^\\.\\.\\.", text, re.M):', "if False:"),
     "an error answer cut short loses its status": ('            return e.code, b""', "            raise"),
     "a surprise ends the watch": ("            except Exception as e:\n                problems.append(f\"the watch could not look", "            except ZeroDivisionError as e:\n                problems.append(f\"the watch could not look"),
     "a watch that ends leaves no stop file": ("        stop_the_run(stop_file)\n        print(f\"{now()} BREACH, the run is stopped: the watch ended", "        print(f\"{now()} BREACH, the run is stopped: the watch ended"),
+    "a killed watch reads as all well": ('        return f"the watch (pid {pid}) is not running, so nothing is watching Keycloak"', "        return None"),
+    "a hung watch reads as all well": ("    if age > WATCH_STALE_SECONDS:", "    if False:"),
+    "no watch passes for a watch": ('            raise Stop("the watch did not begin; read its output")', "            return"),
+    "the heartbeat outlives a clean end": ("    os.unlink(alive)\n", ""),
+    "the watch never beats": ("            os.utime(alive)\n", ""),
+    "import-wait ignores a dead watch": ("        if not started and why_stopped(stop_file):", "        if not started and os.path.exists(stop_file):"),
     "the watch ignores a restart": ('problems.append(f"keycloak-0 restarted: {kc}")', "pass"),
     "the watch never reports": ("if down and waited >= REPORT_AFTER_SECONDS and not reported:", "if False:"),
     "the watch does not stop the run": ("open(stop_file, \"a\").close()", "pass"),
@@ -305,8 +345,9 @@
         for name, (old, new) in MUTANTS.items():
             assert text.count(old) == 1, (name, old, text.count(old))
             m = os.path.join(W, "mutant.py"); open(m, "w").write(text.replace(old, new))
-            f = [l for l, ok in score(m) if not ok]
-            print(f"  {'killed  ' if f else 'SURVIVED'} {name}" + (f" ({f[0]})" if f else ""))
+            # To the first wrong case and no further: every case on every mutant is most of this job's time.
+            f = next((l for l, ok in cases(m) if not ok), None)
+            print(f"  {'killed  ' if f else 'SURVIVED'} {name}" + (f" ({f})" if f else ""), flush=True)
             wrong += 0 if f else 1
     print(f"guard cases failed: {len(bad)}, mutants survived: {wrong}")
     sys.exit(1 if bad or wrong else 0)
````

### `06-runbook-stops-hold.patch`

````diff
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/tests/doc13-test.py b/deploy/tests/doc13-test.py
--- a/deploy/tests/doc13-test.py	2026-11-06 05:55:35
+++ b/deploy/tests/doc13-test.py	2026-11-06 06:03:16
@@ -1,7 +1,8 @@
 #!/usr/bin/env python3
 """docs/13's run, read: what it says is what the wave's rulings and the owner's requirements say, and every path and subcommand it names exists. A runbook is run by hand, so nothing else holds it.
-Then the same checks on mutants of the document: a mutant that passes is a rule this test cannot fail on. No cluster. usage: doc13-test.py [<docs/13 file>]. Exit 1 on any failure."""
-import os, re, sys
+Then its blocks, run: each step in a plain bash, as pasted, on stubs of oc, git, sleep and every script, with each command it runs failing in turn. Each failure must end the step, leave the shell alive, write the stop
+file and make the next step refuse. Then the same checks on mutants of the document: a mutant that passes is a rule this test cannot fail on. No cluster. usage: doc13-test.py [<docs/13 file>]. DOC13_BASH names another bash. Exit 1 on any failure."""
+import os, re, shutil, stat, subprocess, sys, tempfile
 ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
 PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs/13-crc-deployment.md")
 DOC = open(PATH).read()
@@ -9,15 +10,111 @@
 MANIFESTS = os.path.join(ROOT, "deploy/manifests")
 
 
-def problems(doc):
+# Stands in for every command the run calls: logs its call, fails when that call is FAIL, and answers what the blocks read.
+STUB = r'''#!/usr/bin/env bash
+key="$(basename "$0") $*"
+printf '%s\n' "$key" >>"$CALLS"
+[ "$key" != "$FAIL" ] || exit 7
+case "$key" in
+  "crc-guard.py gate "*) [ ! -e "$2" ]; exit;;
+  "crc-guard.py issuer") exit "$STUB_ISSUER";;
+  "git status"*) printf '%s' "${STUB_DIRTY:-}";;
+  "oc get sa "*) echo x;;
+  "oc get ns cmapi-imports"*|"oc get clusterrole,"*) printf '%s' "${STUB_LISTED:-}";;
+esac
+exit 0
+'''
+
+
+def run_blocks(doc, steps, only=None):
+    """Each step, or those in only, run with each of its commands failing. One string per rule a failure broke."""
+    out = []
+    prelude = re.search(r"^## The run\n.*?```bash\n(.*?)```", doc, re.S | re.M)[1]
+    work = tempfile.mkdtemp(prefix="doc13-run.")
+    try:
+        bin_dir = os.path.join(work, "bin"); deploy = os.path.join(work, "deploy"); os.mkdir(bin_dir); os.mkdir(deploy)
+        names = [os.path.join(bin_dir, n) for n in ("oc", "git", "sleep")] + [os.path.join(deploy, "crc-guard.py")]
+        names += [os.path.join(deploy, os.path.basename(p)) for p in set(re.findall(r"\bdeploy/[\w./-]+\.sh", "\n".join(steps.values())))]
+        for n in names:
+            with open(n, "w") as f:
+                f.write(STUB)
+            os.chmod(n, os.stat(n).st_mode | stat.S_IXUSR)
+        run_dir = os.path.join(work, "deploy", "rendered", "wave1-run"); os.makedirs(run_dir)
+        stop = os.path.join(run_dir, "stop"); calls = os.path.join(work, "calls"); script = os.path.join(work, "script")
+        # What the issuer must answer for each step to pass, and what it must stop on.
+        passes = {4: 10, 13: 10, 16: 0}
+        wrong = {4: (0, 20), 13: (0, 20), 16: (10, 20)}
+
+        def go(n, fail="", last="watch ended rc=0", then_next=True, **env):
+            for f in (stop, calls):
+                if os.path.exists(f): os.unlink(f)
+            with open(os.path.join(run_dir, "watch.log"), "w") as f:
+                f.write(last + "\n")
+            # The prelude with nothing failing: it defines what the steps use. Then the step, a mark, and the next step, pasted later.
+            with open(script, "w") as f:
+                f.write(prelude + "\n" + 'echo prelude >>"$CALLS"\n' + steps[n] + 'echo SURVIVED; echo next >>"$CALLS"\n' + (steps.get(n + 1, "") if then_next else "") + "echo SURVIVED_NEXT\n")
+            r = subprocess.run([os.environ.get("DOC13_BASH", "bash"), script], cwd=work, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
+                               env={**os.environ, "PATH": bin_dir + os.pathsep + os.environ["PATH"], "CALLS": calls, "FAIL": fail, "STUB_ISSUER": str(env.pop("issuer", passes.get(n, 10))), **env})
+            log = open(calls).read().splitlines() if os.path.exists(calls) else []
+            at = log.index("prelude") if "prelude" in log else 0
+            nx = log.index("next") if "next" in log else len(log)
+            return r, log[at + 1:nx], log[nx + 1:], os.path.exists(stop)
+
+        def stopped_right(label, n, r, step_calls, after, was_stopped, fail=""):
+            alive = "SURVIVED_NEXT" in r.stdout
+            if not alive: out.append(f"{label}: the shell did not survive step {n}")
+            if not was_stopped: out.append(f"{label}: step {n} wrote no stop file")
+            allowed = ("crc-guard.py gate ",) + (("crc-guard.py import-wait ",) if n + 1 == 14 else ())
+            ran = [c for c in after if not c.startswith(allowed)]
+            if ran: out.append(f"{label}: the step after {n} ran {ran[0][:80]}")
+            if fail in step_calls:
+                # What may still follow a failure: the same read retried, the realm sync's log, and a watch begun in the background just before.
+                late = [c for c in step_calls[step_calls.index(fail) + 1:] if c != fail and c != "oc logs job/cmapi-realm-sync -n cmapi" and not c.startswith(("sleep ", "crc-guard.py watch "))]
+                if late: out.append(f"{label}: step {n} ran on after it failed: {late[0][:80]}")
+
+        for n in sorted(only or steps):
+            r, step_calls, after, was_stopped = go(n, then_next=False)
+            if was_stopped or "SURVIVED_NEXT" not in r.stdout:
+                out.append(f"step {n} does not pass when nothing fails: {r.stdout[-200:]} {r.stderr[-200:]}")
+                continue
+            for key in sorted(set(step_calls)):
+                if key.startswith("crc-guard.py watch "):      # in the background: `watching` is what sees it, in crc-guard-test.py
+                    continue
+                r2, sc, after2, st = go(n, fail=key)
+                stopped_right(f"{key[:60]} failing", n, r2, sc, after2, st, fail=key)
+                if n == 19 and key.startswith("oc wait job/") and "oc logs job/cmapi-realm-sync -n cmapi" not in sc:
+                    out.append("a realm sync that failed lost its log")
+            for bad in wrong.get(n, ()):
+                r2, sc, after2, st = go(n, issuer=bad)
+                stopped_right(f"the issuer answering {bad}", n, r2, sc, after2, st)
+                if n == 13 and any(c.startswith("oc apply") for c in sc): out.append(f"the import was applied with the issuer answering {bad}")
+            if n == 3:
+                r2, sc, after2, st = go(n, STUB_LISTED="namespace/cmapi-system")
+                stopped_right("something listed", n, r2, sc, after2, st)
+            if n == 22:
+                r2, sc, after2, st = go(n, last="watch ended rc=3")
+                stopped_right("a watch that ended rc=3", n, r2, sc, after2, st)
+        r2, sc, after2, st = go(1, STUB_DIRTY=" M x")
+        if not st or "deploy/crc-trust.sh" in " ".join(sc): out.append("a dirty checkout does not stop the run")
+    finally:
+        shutil.rmtree(work)
+    return out
+
+
+def steps_of(doc):
+    steps = {}
+    for m in re.finditer(r"^### Step (\d+):[^\n]*\n(.*?)(?=^##|\Z)", doc, re.S | re.M):
+        steps[int(m[1])] = "\n".join(re.findall(r"```bash\n(.*?)```", m[2], re.S))
+    return steps
+
+
+def problems(doc, only=None):
     """One string per broken rule."""
     out = []
     def need(ok, label):
         if not ok:
             out.append(label)
-    steps = {}
-    for m in re.finditer(r"^### Step (\d+):[^\n]*\n(.*?)(?=^##|\Z)", doc, re.S | re.M):
-        steps[int(m[1])] = "\n".join(re.findall(r"```bash\n(.*?)```", m[2], re.S))
+    steps = steps_of(doc)
     need(sorted(steps) == list(range(1, 24)), f"the steps are 1 to 23 in order: {sorted(steps)}")
     run = "\n".join(steps.values())
     # Ruling 13: every apply under one field manager. Lines are joined at a trailing backslash first.
@@ -27,11 +124,23 @@
     for piece in applies:
         need("--server-side" in piece and "--field-manager=cmapi-wave1" in piece, f"an apply without --server-side --field-manager=cmapi-wave1: {piece.strip()}")
         need(not re.search(r"-R\b.*environment|environment/?\"?\s+-R", piece), f"-R on the environment: {piece.strip()}")
-    # The owner's requirement: a breach stops every later step. Every step from the backup on looks at the stop file first; import-wait is given it, since it must withdraw an import on it.
+    # The owner's requirement: a stop stops every later step. Each step is `( set -euo pipefail ... ); stopped $? N`: a subshell, so a failure never closes the terminal, and the stop written down,
+    # so it holds for a step pasted later. Not `( ... ) || stopped`, which turns set -e off inside. Each looks at the stop file first; import-wait is given it, since it must withdraw an import on it.
+    prelude = (re.search(r"^## The run\n.*?```bash\n(.*?)```", doc, re.S | re.M) or [None, ""])[1]
+    need(not re.search(r"^\s*set -", prelude.split("( set -euo pipefail")[0], re.M), "set in the terminal's own shell")
+    need('| tee -a "$STOP"' in prelude, "stopped does not write the stop file")
     for n, body in steps.items():
-        if n >= 11:
-            first = next((line for line in body.splitlines() if not line.startswith("I=$R")), "")
-            need(first.startswith(('$G gate "$STOP"', '$G import-wait "$STOP"')), f"step {n} does not start with the stop file: {first[:60]}")
+        shape = re.fullmatch(r"\( set -euo pipefail\n(.*)\n\); stopped \$\? (\d+)\n", body, re.S)
+        need(shape and shape[2] == str(n), f"step {n} is not a subshell with set -euo pipefail ending in stopped $? {n}: {body[:40]!r}...{body[-30:]!r}")
+        if not shape:
+            continue
+        inner = shape[1].splitlines()
+        need(inner[0].strip().startswith('$G import-wait "$STOP"' if n == 14 else '$G gate "$STOP"'), f"step {n} does not start with the stop file: {inner[0][:60]}")
+        # Under set -e, A && B carries on past a failed A, and only these forms may stand in a list.
+        for line in inner:
+            code = re.sub(r"\s+#.*$", "", line)
+            need(not re.search(r"&&", code.replace("&& break", "")), f"step {n} hides a failure in an AND-list: {code.strip()[:70]}")
+            need(not re.search(r"\|\|", re.sub(r"\|\| rc=\$\?|\] \|\| \{ .*; exit 1; \}", "", code)), f"step {n} hides a failure in an OR-list: {code.strip()[:70]}")
     # Nothing broad, and TLS on.
     for label, pattern in (("--all", r"\s--all\b"), ("a selector on a delete", r"delete[^\n]*(\s-l\s|--selector)"), ("--prune", r"--prune"), ("delete -f", r"delete[^\n]*\s-f\s"),
                            ("TLS off", r"(\s-k\s|--insecure|--tls-verify=false|verify=False|CERT_NONE)"), ("a credential on an argument", r"(\s-p\s+\"?\$|--password[= ]\"?\$)")):
@@ -45,6 +154,9 @@
     for n in (12, 15, 16, 20, 22):
         need(re.search(r'\$G compare "\$RUN/s0\.json"', steps.get(n, "")), f"step {n} does not compare with s0")
     need("$G watch" in steps.get(10, ""), "the watch does not start at step 10")
+    need('$G watching "$STOP"' in steps.get(10, ""), "nothing checks that the watch began")
+    need('rm -f "$RUN/watch.log.done"' in steps.get(10, ""), "a done file left from before would end the new watch at once")
+    need("--issuer https://keycloak.apps-crc.testing/realms/cmapi " in steps.get(9, ""), "step 9 does not name this Keycloak's realm cmapi")
     # Every name resolves.
     subcommands = set(re.findall(r'sub\.add_parser\("([a-z-]+)"\)', GUARD)) | set(re.findall(r'p = sub\.add_parser\("([a-z-]+)"\)', GUARD))
     for sub in set(re.findall(r"\$G ([a-z-]+)", run)):
@@ -60,24 +172,45 @@
     need("gitea" not in doc.lower(), "Gitea in the runbook")
     need("It is the owner's decision alone" in doc and "--delete-realm --owner-approved" in doc, "the owner's two decisions")
     need("REPORT TO THE OWNER NOW" in doc and "300 s" in doc, "the bound on a restart")
-    return out
+    # Slow next to the rest, and only worth saying once the document's shape holds.
+    return out or run_blocks(doc, steps, only)
 
 
 MUTANTS = {
     "an apply with no field manager": (' --field-manager=cmapi-wave1 -f "$R/environment/"', ' -f "$R/environment/"'),
     "an apply not server-side": ('oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/"', 'oc apply --field-manager=cmapi-wave1 -f "$R/environment/"'),
     "-R on the environment": ('--field-manager=cmapi-wave1 -f "$R/environment/"', '--field-manager=cmapi-wave1 -R -f "$R/environment/"'),
-    "the backup without the gate": ('$G gate "$STOP" && deploy/crc-backup.sh\n', "deploy/crc-backup.sh\n"),
-    "the workloads without the gate": ('$G gate "$STOP" && oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"', 'oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"'),
+    "the backup without the gate": ('  $G gate "$STOP"\n  deploy/crc-backup.sh\n', "  deploy/crc-backup.sh\n"),
+    "the workloads without the gate": ('  $G gate "$STOP"\n  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"', '  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"'),
     "a broad delete": ("oc delete keycloakrealmimport cmapi -n keycloak", "oc delete keycloakrealmimport --all -n keycloak"),
-    "TLS off": ('deploy/crc-trust.sh --check &&', 'curl -k x && deploy/crc-trust.sh --check &&'),
+    "TLS off": ('  deploy/crc-trust.sh --check\n', '  curl -k x\n  deploy/crc-trust.sh --check\n'),
     "the issuer check skipped": ("deploy/secrets.sh --issuer https://keycloak.apps-crc.testing/realms/cmapi --ca-file \"$CMAPI_CRC_CA\"", "deploy/secrets.sh --no-issuer-check"),
     "a compare dropped": ('$G compare "$RUN/s0.json" "$RUN/s3.json"', "true"),
     "a guard subcommand that does not exist": ('$G headroom --needs 672', '$G room --needs 672'),
     "a file that does not exist": ('"$R/components/database-cnpg/cluster.yaml"', '"$R/components/database-cnpg/db.yaml"'),
     "a script that does not exist": ("deploy/crc-reader-import.sh", "deploy/crc-reader.sh"),
     "the owner's keychain step gone": ("security add-trusted-cert", "something else"),
-    "the import before the backup": ("### Step 11: the backup, immediately before the import\n\n```bash\n$G gate \"$STOP\" && deploy/crc-backup.sh\n", "### Step 11: the backup, immediately before the import\n\n```bash\n$G gate \"$STOP\"\n"),
+    "the import before the backup": ("### Step 11: the backup, immediately before the import\n\n```bash\n( set -euo pipefail\n  $G gate \"$STOP\"\n  deploy/crc-backup.sh\n", "### Step 11: the backup, immediately before the import\n\n```bash\n( set -euo pipefail\n  $G gate \"$STOP\"\n"),
+    "set -e in the terminal's own shell": ("G=deploy/crc-guard.py; export", "set -euo pipefail\nG=deploy/crc-guard.py; export"),
+    "a step with no errexit": ('( set -euo pipefail\n  $G gate "$STOP"\n  deploy/crc-backup.sh\n', '( set -uo pipefail\n  $G gate "$STOP"\n  deploy/crc-backup.sh\n'),
+    "( ... ) || stopped, which turns set -e off inside": ("); stopped $? 11", ") || stopped $? 11"),
+    "a failure that is only printed": ("); stopped $? 5", "); echo done"),
+    "a step that closes the shell": ("); stopped $? 9", "); stopped $? 9 || exit 1"),
+    "another step's number": ("); stopped $? 12", "); stopped $? 21"),
+    "an AND-list": ('  deploy/crc-trust.sh --check\n  deploy/crc-trust.sh --mac-ca', '  deploy/crc-trust.sh --check && deploy/crc-trust.sh --mac-ca'),
+    "stopped writes nothing": (' | tee -a "$STOP"; return', "; return"),
+    "stopped closes the shell": ('tee -a "$STOP"; return "$1"; }', 'tee -a "$STOP"; exit "$1"; }'),
+    "step 4 reads any answer as absent": ('  [ "$rc" = 10 ]\n  echo "absent: go on"', '  echo "absent: go on"'),
+    "step 13 reads any answer as absent": ('  [ "$rc" = 10 ]\n  oc apply --server-side --dry-run=server', '  oc apply --server-side --dry-run=server'),
+    "step 16 does not look at the realm": ('  $G issuer\n  echo "realm present"', '  echo "realm present"'),
+    "something listed is only printed": ('  [ -z "$left" ] || { echo "STOP: this run did not make: $left"; exit 1; }\n', ""),
+    "the realm sync's log lost": ('  rc=0; oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s || rc=$?', '  oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s'),
+    "the realm sync's failure forgotten": ('  [ "$rc" = 0 ]\n', ""),
+    "the watch's last line not asserted": ('  case "$last" in *"watch ended rc=0") ;; *) echo "STOP: the watch did not end clean"; exit 1;; esac\n', ""),
+    "nothing checks the watch began": ('  $G watching "$STOP"\n', ""),
+    "a stale done file ends the new watch": ('  rm -f "$RUN/watch.log.done"\n', ""),
+    "the issuer of another host": ("--issuer https://keycloak.apps-crc.testing/realms/cmapi", "--issuer https://keycloak.example/realms/cmapi"),
+    "a dirty checkout is only printed": ('  [ -z "$(git status --porcelain)" ]\n', '  git status --porcelain\n'),
 }
 
 fails = problems(DOC)
@@ -88,7 +221,10 @@
 if not fails:
     for name, (old, new) in MUTANTS.items():
         assert DOC.count(old) >= 1, (name, old)
-        found = problems(DOC.replace(old, new))
+        mutant = DOC.replace(old, new)
+        # The blocks that changed, or two steps for a change to what they all use: the whole run has already passed, and it takes half a minute each.
+        was, now = steps_of(DOC), steps_of(mutant)
+        found = problems(mutant, [n for n in now if now[n] != was.get(n)] or [1, 9])
         print(f"  {'killed  ' if found else 'SURVIVED'} {name}" + (f" ({found[0][:90]})" if found else ""))
         survived += 0 if found else 1
 print(f"doc13 cases failed: {len(fails)}, mutants survived: {survived}")
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/docs/13-crc-deployment.md b/docs/13-crc-deployment.md
--- a/docs/13-crc-deployment.md	2026-11-06 05:55:35
+++ b/docs/13-crc-deployment.md	2026-11-06 05:57:17
@@ -74,17 +74,27 @@
 
 Run these in one bash, not zsh, from the repository's root. Keep every output: it goes in `docs/reviews/`, once checked for secret values.
 
+**How a stop works.** Each step is a subshell with `set -euo pipefail`, as in `docs/12`: `set -e` in a terminal's own shell would close it on the first failure, and a pasted `exit` would lose the variables below and leave the next paste running somewhere else. `stopped` writes any failure to `$STOP`. So a stop ends that step, the terminal stays, and every later step refuses at its first line, however much later it is pasted. Keep `; stopped $?` on its own after the `)`: a list such as `( ... ) || stopped` turns `set -e` off inside the parentheses, which is bash's rule.
+
 ```bash
-set -uo pipefail
-git status --porcelain; git rev-parse --short=10 HEAD            # nothing printed by the first; the merged commit by the second
 RUN=$PWD/deploy/rendered/wave1-run; mkdir -p "$RUN"; R=$PWD/deploy/rendered/crc; STOP=$RUN/stop
-G=deploy/crc-guard.py
+G=deploy/crc-guard.py; export CMAPI_CRC_CA=$RUN/crc-ca.pem
+stopped() { [ "$1" = 0 ] && return 0; echo "STOP at step $2 (rc $1): report it. No retry and no workaround." | tee -a "$STOP"; return "$1"; }
+( set -euo pipefail
+  $G gate "$STOP"
+  [ -z "$(git status --porcelain)" ]
+  git rev-parse --short=10 HEAD                                    # the merged commit
+); stopped $? 0
 ```
 
 ### Step 1: the trust file still verifies Keycloak
 
 ```bash
-deploy/crc-trust.sh --check && deploy/crc-trust.sh --mac-ca "$RUN/crc-ca.pem" && export CMAPI_CRC_CA=$RUN/crc-ca.pem
+( set -euo pipefail
+  $G gate "$STOP"
+  deploy/crc-trust.sh --check
+  deploy/crc-trust.sh --mac-ca "$RUN/crc-ca.pem"
+); stopped $? 1
 ```
 
 **Stops when** `30-trust.yaml` no longer verifies Keycloak: a real TLS handshake against the Route, with that file as the only CA. It reads no Secret. See [If the CA rotates](#if-the-ca-rotates).
@@ -92,8 +102,12 @@
 ### Step 2: this is CRC, and there is room
 
 ```bash
-$G preflight --needs 768 | tee "$RUN/preflight.txt"; echo "preflight rc=${PIPESTATUS[0]}"
-oc adm top node | tee "$RUN/top-before.txt"; oc get pv -o name >"$RUN/pv-before.txt"
+( set -euo pipefail
+  $G gate "$STOP"
+  $G preflight --needs 768 | tee "$RUN/preflight.txt"
+  oc adm top node | tee "$RUN/top-before.txt"
+  oc get pv -o name >"$RUN/pv-before.txt"
+); stopped $? 2
 ```
 
 **Stops when** the API server is not `https://api.crc.testing:6443`; the context is not `<namespace>/api-crc-testing:6443/kubeadmin`; `oc whoami` is not kubeadmin (`kube:admin` or `kubeadmin`); any kind cluster exists; request headroom minus 768 Mi is under 2 GiB; `keycloak-0` or `postgres-0` is not Ready.
@@ -101,9 +115,13 @@
 ### Step 3: nothing is there that this run did not make
 
 ```bash
-oc get ns cmapi-imports cmapi-system --ignore-not-found
-oc get clusterrole,clusterrolebinding cmapi-reader --ignore-not-found
-oc get ns cmapi -o jsonpath='{.metadata.labels}{"\n"}'
+( set -euo pipefail
+  $G gate "$STOP"
+  left=$(oc get ns cmapi-imports cmapi-system --ignore-not-found -o name)
+  left+=$(oc get clusterrole,clusterrolebinding cmapi-reader --ignore-not-found -o name)
+  [ -z "$left" ] || { echo "STOP: this run did not make: $left"; exit 1; }
+  oc get ns cmapi -o jsonpath='{.metadata.labels}{"\n"}'
+); stopped $? 3
 ```
 
 **Stops when** anything is listed that this run has not made: stop and ask whose it is.
@@ -111,7 +129,12 @@
 ### Step 4: realm `cmapi` does not exist
 
 ```bash
-$G issuer; [ $? = 10 ] && echo "absent: go on" || echo STOP
+( set -euo pipefail
+  $G gate "$STOP"
+  rc=0; $G issuer || rc=$?
+  [ "$rc" = 10 ]
+  echo "absent: go on"
+); stopped $? 4
 ```
 
 **Stops on** anything but Keycloak's own 404. A timeout, a certificate failure or a router's 503 is not "absent".
@@ -119,7 +142,12 @@
 ### Step 5: the image, before anything touches Keycloak
 
 ```bash
-IMAGE=$(deploy/crc-image.sh | tail -1) && deploy/render.sh crc "$IMAGE" && echo "$IMAGE" | tee "$RUN/image.txt"
+( set -euo pipefail
+  $G gate "$STOP"
+  IMAGE=$(deploy/crc-image.sh | tail -1)
+  deploy/render.sh crc "$IMAGE"
+  echo "$IMAGE" | tee "$RUN/image.txt"
+); stopped $? 5
 ```
 
 **Stops on** a failure of any check in either script. It is finished before any Keycloak step, so its load is never beside an import. `podman push --cert-dir` is not honoured on this Mac (measured), so `crc-image.sh` pushes with `skopeo`, TLS verified against the ingress CA, with the session's token in a 0600 file and never on an argument.
@@ -129,7 +157,10 @@
 Top-level files only. Never `-R` here: `reader/` and `realm/` are applied by name, in their own steps.
 
 ```bash
-oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/"
+( set -euo pipefail
+  $G gate "$STOP"
+  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/"
+); stopped $? 6
 ```
 
 Writes only to `cmapi` and `cmapi-imports`.
@@ -137,7 +168,11 @@
 ### Step 7: the reader
 
 ```bash
-oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/reader/00-cmapi-reader.yaml" && deploy/crc-reader-import.sh
+( set -euo pipefail
+  $G gate "$STOP"
+  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/reader/00-cmapi-reader.yaml"
+  deploy/crc-reader-import.sh
+); stopped $? 7
 ```
 
 **Stops when** the token Secret is not filled in 30 tries.
@@ -147,11 +182,15 @@
 Admission copies an account's `imagePullSecrets` into a pod when the pod is created, so a pod made before the controller has filled them would never get them (inferred). So wait.
 
 ```bash
-oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/00-serviceaccounts.yaml"
-for sa in cmapi-api cmapi-worker cmapi-jobs; do
-  for _ in $(seq 1 60); do [ -n "$(oc get sa "$sa" -n cmapi -o 'jsonpath={.imagePullSecrets}')" ] && break; sleep 1; done
-  [ -n "$(oc get sa "$sa" -n cmapi -o 'jsonpath={.imagePullSecrets}')" ] && echo "$sa: pull secret there" || echo "STOP: $sa has no pull secret"
-done
+( set -euo pipefail
+  $G gate "$STOP"
+  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/00-serviceaccounts.yaml"
+  for sa in cmapi-api cmapi-worker cmapi-jobs; do
+    for _ in $(seq 1 60); do [ -n "$(oc get sa "$sa" -n cmapi -o 'jsonpath={.imagePullSecrets}')" ] && break; sleep 1; done
+    [ -n "$(oc get sa "$sa" -n cmapi -o 'jsonpath={.imagePullSecrets}')" ] || { echo "STOP: $sa has no pull secret"; exit 1; }
+    echo "$sa: pull secret there"
+  done
+); stopped $? 8
 ```
 
 **Stops when** an account has no pull secret after 60 s.
@@ -159,7 +198,10 @@
 ### Step 9: the Secrets
 
 ```bash
-deploy/secrets.sh --issuer https://keycloak.apps-crc.testing/realms/cmapi --ca-file "$CMAPI_CRC_CA" --test-users
+( set -euo pipefail
+  $G gate "$STOP"
+  deploy/secrets.sh --issuer https://keycloak.apps-crc.testing/realms/cmapi --ca-file "$CMAPI_CRC_CA" --test-users
+); stopped $? 9
 ```
 
 This writes `cmapi-realm-secrets` in `keycloak`, by name, and `cmapi-keycloak`, `cmapi-keys` and `cmapi-test-users` in `cmapi`. Before minting it asks the realm: a 200 stops it, since a realm exists whose client secrets nobody here knows, and anything but Keycloak's own 404 stops it too. A later run mints nothing, so it does not ask.
@@ -167,16 +209,24 @@
 ### Step 10: the snapshot, and the watch from here to the end
 
 ```bash
-$G snapshot "$RUN/s0.json"
-nohup $G watch "$RUN/watch.log" "$STOP" "$RUN/s0.json" >"$RUN/watch.out" 2>&1 &
+( set -euo pipefail
+  $G gate "$STOP"
+  $G snapshot "$RUN/s0.json"
+  rm -f "$RUN/watch.log.done"
+  nohup $G watch "$RUN/watch.log" "$STOP" "$RUN/s0.json" >"$RUN/watch.out" 2>&1 &
+  $G watching "$STOP"
+); stopped $? 10
 ```
 
-**Stops when** a realm does not answer 200. From here the watch runs in the background, with `CMAPI_CRC_CA` exported, and a breach writes `$STOP`. Every later step checks it.
+**Stops when** a realm does not answer 200, or the watch did not begin. From here the watch runs in the background, with `CMAPI_CRC_CA` exported, and a breach writes `$STOP`. Every later step checks it, and also that the watch is still running and has looked within 120 s: a watch that is killed or hangs writes nothing, and nobody would be looking.
 
 ### Step 11: the backup, immediately before the import
 
 ```bash
-$G gate "$STOP" && deploy/crc-backup.sh
+( set -euo pipefail
+  $G gate "$STOP"
+  deploy/crc-backup.sh
+); stopped $? 11
 ```
 
 **A failed backup stops the run.** See [The backup](#the-backup).
@@ -184,7 +234,11 @@
 ### Step 12: the backup changed nothing
 
 ```bash
-$G gate "$STOP" && $G snapshot "$RUN/s1.json" && $G compare "$RUN/s0.json" "$RUN/s1.json"
+( set -euo pipefail
+  $G gate "$STOP"
+  $G snapshot "$RUN/s1.json"
+  $G compare "$RUN/s0.json" "$RUN/s1.json"
+); stopped $? 12
 ```
 
 **Stops on** any difference.
@@ -192,10 +246,16 @@
 ### Step 13: the import, alone on the quietest cluster
 
 ```bash
-I=$R/environment/realm/10-realm-import.yaml
-$G gate "$STOP" && $G headroom --needs 768 && $G check-import "$I" && { $G issuer; [ $? = 10 ]; } \
-  && oc apply --server-side --dry-run=server --field-manager=cmapi-wave1 -f "$I" \
-  && oc apply --server-side --field-manager=cmapi-wave1 -f "$I"
+( set -euo pipefail
+  $G gate "$STOP"
+  I=$R/environment/realm/10-realm-import.yaml
+  $G headroom --needs 768
+  $G check-import "$I"
+  rc=0; $G issuer || rc=$?
+  [ "$rc" = 10 ]
+  oc apply --server-side --dry-run=server --field-manager=cmapi-wave1 -f "$I"
+  oc apply --server-side --field-manager=cmapi-wave1 -f "$I"
+); stopped $? 13
 ```
 
 **Stops when** the run is stopped; headroom is under the line; the file names anything but `cmapi`; the realm is not absent; the API refuses `spec.resources`.
@@ -205,7 +265,9 @@
 ### Step 14: follow the import
 
 ```bash
-$G import-wait "$STOP" | tee "$RUN/import.txt"; echo "import-wait rc=${PIPESTATUS[0]}"
+( set -euo pipefail
+  $G import-wait "$STOP" | tee "$RUN/import.txt"
+); stopped $? 14
 ```
 
 | What it sees | Bound | What it does |
@@ -217,11 +279,19 @@
 | `Done`, realm present | | rc 0, unless the watch stopped the run meanwhile |
 | `Done`, realm absent | | Stops |
 
+This step alone starts with no gate, since a stop is what it must act on. It has no bound on a running import, so if it stops without saying `withdrawn` or `Done`, read `oc get keycloakrealmimport cmapi -n keycloak`: an import still there can still start.
+
 ### Step 15: nothing else changed, with time for a late restart
 
 ```bash
-$G gate "$STOP" && oc logs job/cmapi -n keycloak --tail=5 | tee "$RUN/import-log-tail.txt"
-sleep 120; $G gate "$STOP" && $G snapshot "$RUN/s2.json" && $G compare "$RUN/s0.json" "$RUN/s2.json"
+( set -euo pipefail
+  $G gate "$STOP"
+  oc logs job/cmapi -n keycloak --tail=5 | tee "$RUN/import-log-tail.txt"
+  sleep 120
+  $G gate "$STOP"
+  $G snapshot "$RUN/s2.json"
+  $G compare "$RUN/s0.json" "$RUN/s2.json"
+); stopped $? 15
 ```
 
 **Stops on** any difference. 120 s because a restart could lag.
@@ -231,9 +301,15 @@
 The operator's guide says to delete it once the realm is imported. It removes the Job, the pod and the Secret holding the realm's JSON. The realm stays, because no code path in the controller calls Keycloak. Deleting also means it can never start again unattended.
 
 ```bash
-$G gate "$STOP" && oc delete keycloakrealmimport cmapi -n keycloak
-$G issuer; [ $? = 0 ] && echo "realm present" || echo STOP
-$G gate "$STOP" && $G snapshot "$RUN/s3.json" && $G compare "$RUN/s0.json" "$RUN/s3.json"
+( set -euo pipefail
+  $G gate "$STOP"
+  oc delete keycloakrealmimport cmapi -n keycloak
+  $G issuer
+  echo "realm present"
+  $G gate "$STOP"
+  $G snapshot "$RUN/s3.json"
+  $G compare "$RUN/s0.json" "$RUN/s3.json"
+); stopped $? 16
 ```
 
 **Stops when** the realm is not present afterwards, or on any difference.
@@ -241,8 +317,12 @@
 ### Step 17: the database
 
 ```bash
-$G gate "$STOP" && $G headroom --needs 672 && oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/database-cnpg/cluster.yaml" \
-  && oc wait cluster.postgresql.cnpg.io/cmapi-db -n cmapi --for=jsonpath='{.status.phase}'='Cluster in healthy state' --timeout=300s
+( set -euo pipefail
+  $G gate "$STOP"
+  $G headroom --needs 672
+  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/database-cnpg/cluster.yaml"
+  oc wait cluster.postgresql.cnpg.io/cmapi-db -n cmapi --for=jsonpath='{.status.phase}'='Cluster in healthy state' --timeout=300s
+); stopped $? 17
 ```
 
 **Stops when** the run is stopped, headroom is under the line, or the database is not healthy.
@@ -252,9 +332,12 @@
 The policy goes first by itself: `-R` applies files in name order, `20-api` ahead of `40-networkpolicy`, and "started under the policy" must be true from the first moment.
 
 ```bash
-$G gate "$STOP" && oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml" \
-  && oc apply --server-side --field-manager=cmapi-wave1 -R -f "$R/components/cmapi" -f "$R/components/portal"
-for d in cmapi-api cmapi-worker cmapi-mockup; do oc rollout status "deploy/$d" -n cmapi --timeout=600s || echo "STOP: $d"; done
+( set -euo pipefail
+  $G gate "$STOP"
+  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"
+  oc apply --server-side --field-manager=cmapi-wave1 -R -f "$R/components/cmapi" -f "$R/components/portal"
+  for d in cmapi-api cmapi-worker cmapi-mockup; do oc rollout status "deploy/$d" -n cmapi --timeout=600s; done
+); stopped $? 18
 ```
 
 **Stops when** a rollout is not done.
@@ -264,10 +347,14 @@
 The user profile, group mappings, read-only LDAP federation and local test users. Without it `employee_id` never reaches a token. One try and no retries: `requireSync` fails the Job when federation read nobody (#96).
 
 ```bash
-$G gate "$STOP" && oc delete job cmapi-realm-sync -n cmapi --ignore-not-found \
-  && oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/realm/20-realm-sync.yaml" \
-  && oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s
-oc logs job/cmapi-realm-sync -n cmapi | tee "$RUN/realm-sync.txt"
+( set -euo pipefail
+  $G gate "$STOP"
+  oc delete job cmapi-realm-sync -n cmapi --ignore-not-found
+  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/realm/20-realm-sync.yaml"
+  rc=0; oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s || rc=$?
+  oc logs job/cmapi-realm-sync -n cmapi | tee "$RUN/realm-sync.txt"      # whichever way it ended: the log says why
+  [ "$rc" = 0 ]
+); stopped $? 19
 ```
 
 **Stops when** the Job fails, which now includes a federation that read nobody. A failed Job is not Complete, so the wait runs out its 600 s; read the log.
@@ -275,13 +362,20 @@
 ### Step 20: nothing else changed
 
 ```bash
-$G gate "$STOP" && $G snapshot "$RUN/s4.json" && $G compare "$RUN/s0.json" "$RUN/s4.json"
+( set -euo pipefail
+  $G gate "$STOP"
+  $G snapshot "$RUN/s4.json"
+  $G compare "$RUN/s0.json" "$RUN/s4.json"
+); stopped $? 20
 ```
 
 ### Step 21: the proofs
 
 ```bash
-$G gate "$STOP" && deploy/crc-proof.sh "$R" | tee "$RUN/proof.txt"; echo "proof rc=${PIPESTATUS[0]}"
+( set -euo pipefail
+  $G gate "$STOP"
+  deploy/crc-proof.sh "$R" | tee "$RUN/proof.txt"
+); stopped $? 21
 ```
 
 Then the Chrome proofs in [The issue's proofs](#the-issues-proofs). **Stops at** the first failure.
@@ -289,9 +383,16 @@
 ### Step 22: the end of the watch
 
 ```bash
-$G gate "$STOP" && $G snapshot "$RUN/s5.json" && $G compare "$RUN/s0.json" "$RUN/s5.json"
-touch "$RUN/watch.log.done"; sleep 10; tail -1 "$RUN/watch.log"
-oc adm top node | tee "$RUN/top-after.txt"
+( set -euo pipefail
+  $G gate "$STOP"
+  $G snapshot "$RUN/s5.json"
+  $G compare "$RUN/s0.json" "$RUN/s5.json"
+  touch "$RUN/watch.log.done"
+  for _ in $(seq 1 90); do case "$(tail -1 "$RUN/watch.log")" in *"watch ended"*) break;; esac; sleep 1; done
+  last=$(tail -1 "$RUN/watch.log"); echo "$last"
+  case "$last" in *"watch ended rc=0") ;; *) echo "STOP: the watch did not end clean"; exit 1;; esac
+  oc adm top node | tee "$RUN/top-after.txt"
+); stopped $? 22
 ```
 
 **Stops on** any difference, or a last line that is not `watch ended rc=0`.
@@ -301,7 +402,10 @@
 Once the run is verified and the coordinator agrees. It is the owner's term.
 
 ```bash
-$G gate "$STOP" && deploy/crc-backup.sh --delete
+( set -euo pipefail
+  $G gate "$STOP"
+  deploy/crc-backup.sh --delete
+); stopped $? 23
 ```
 
 ## The issue's proofs
@@ -328,7 +432,7 @@
 
 **What it cannot show.** A public key shows a realm was replaced, not that a client inside it changed. A realm no import names is invisible unless listed. Seeing those needs an admin credential, which stays forbidden.
 
-**Watching.** `crc-guard.py watch` polls every realm and `keycloak-0` every 5 s, one timestamped line to `watch.log`. A non-200, a changed key or a changed `keycloak-0` writes the stop file, prints `BREACH`, and goes on logging, so the outage's length is on record.
+**Watching.** `crc-guard.py watch` polls every realm and `keycloak-0` every 5 s, one timestamped line to `watch.log`. A non-200, a changed key, a changed `keycloak-0` or anything that stops it looking writes the stop file, prints `BREACH`, and goes on logging, so the outage's length is on record. It beats in `$STOP.alive`, and `gate` refuses when that beat's process is gone or the beat is over 120 s old.
 
 ## If Keycloak restarts
 
@@ -338,7 +442,7 @@
 2. **Take no action on Keycloak:** no delete, no restart, no CR edit, no scale.
 3. **Tell the owner immediately,** with `watch.log` and `oc describe pod keycloak-0 -n keycloak`, read-only.
 4. **The baseline is 2 min 42 s**, the one measured restart. **At 300 s still unready, the watch prints `REPORT TO THE OWNER NOW`.** That is 1.85 times the only measurement, so a normal restart does not raise it, and it comes well before the kubelet's own limit: the startup probe's `600 x 1 s` would kill and restart the container, doubling the outage.
-5. **The run does not resume by itself.** After the owner has heard: snapshot, and compare with `s0`. A new `keycloak-0` start is expected to differ. The realms must not.
+5. **The run does not resume by itself.** After the owner has heard: snapshot, and compare with `s0`. A new `keycloak-0` start is expected to differ. The realms must not. If the owner says go on: `touch "$RUN/watch.log.done"`, wait for `watch ended` in `watch.log`, `rm -f "$STOP" "$STOP.alive"`, and go on from step 10, which takes a new baseline and a new watch. The same goes for any other stop.
 
 While Keycloak is down, cmapi's own pods hold (read from `auth.py`, `health.py`, `keycloak_admin.py`): issued tokens keep verifying from the cached signing keys, an unknown `kid` is 503 `idp-unavailable`, `/readyz` tests only the database so no pod restarts, and there is no retry storm: one JWKS fetch per pod per 30 s. A new sign-in is impossible, since that is Keycloak's.
 
````

### `07-import-wait-follows-through.patch`

````diff
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/crc-guard.py b/deploy/crc-guard.py
--- a/deploy/crc-guard.py	2026-11-06 07:38:17
+++ b/deploy/crc-guard.py	2026-11-06 07:38:17
@@ -351,6 +351,12 @@
     return False
 
 
+def pod_failed(pod: dict) -> bool:
+    if pod.get("status", {}).get("phase") == "Failed":
+        return True
+    return any((c.get("state", {}).get("terminated") or {}).get("exitCode") not in (None, 0) for c in pod.get("status", {}).get("containerStatuses") or [])
+
+
 def withdraw(reason: str) -> None:
     """Delete our import, by name and only by name. The operator owns its Job and Secret through owner references (GarbageCollected,
     KeycloakRealmImportJobDependentResource.java:59), so they go with it, and a pod that has not started never will."""
@@ -363,12 +369,18 @@
 def import_wait(stop_file: str) -> int:
     t0 = time.monotonic()
     started_at = None
+    pods: list[dict] = []
     while True:
-        kri = oc_json("get", "keycloakrealmimport", OURS, "-n", NS, "--ignore-not-found")
-        if not kri:
-            raise Stop(f"KeycloakRealmImport {OURS} is not there")
-        pods = import_pods()
-        started = any(container_started(p) for p in pods)
+        # A read that fails says nothing about the import, and ending here would leave a pending one to start unattended. So go on, on what was last known, to the same deadlines.
+        try:
+            kri, pods = oc_json("get", "keycloakrealmimport", OURS, "-n", NS, "--ignore-not-found"), import_pods()
+            if not kri:
+                print(f"STOP: KeycloakRealmImport {OURS} is not there", file=sys.stderr)
+                return 1
+            started = any(container_started(p) for p in pods)
+        except (Stop, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:
+            print(f"{now()} could not read the import: {str(e)[:200]}", flush=True)
+            kri, started = {}, started_at is not None
         if started and started_at is None:
             started_at = time.monotonic()
             print(f"{now()} the import's container started {int(started_at - t0)} s after the apply", flush=True)
@@ -380,7 +392,8 @@
                 print(f"{now()} the watch stopped the run while the import ran; nothing more runs until the owner has been told", flush=True)
                 return 1
             return 0 if state == "present" else 1
-        if condition(kri, "HasErrors") == "true" and started:
+        # A failed pod, not the condition alone: the operator also sets HasErrors for an error of its own while a pod runs on (updateErrorStatus, KeycloakRealmImportController.java:101-109), and a running import is never interrupted.
+        if condition(kri, "HasErrors") == "true" and any(pod_failed(p) for p in pods):
             # The Job has no backoffLimit of its own (buildJob sets none), so Kubernetes' default of 6 would start more pods.
             withdraw("the import failed; this stops the Job's further attempts")
             return 1
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/tests/crc-guard-test.py b/deploy/tests/crc-guard-test.py
--- a/deploy/tests/crc-guard-test.py	2026-11-06 07:38:17
+++ b/deploy/tests/crc-guard-test.py	2026-11-06 07:38:17
@@ -13,6 +13,11 @@
 import json,os,sys
 s=json.load(open(os.environ["STUB_STATE"])); a=sys.argv[1:]
 open(os.environ["STUB_ARGV"],"a").write(" ".join(a)+"\n")
+# What the API server's going away looks like: reads of our import and its pods fail, after reads_ok of them have worked and for fail_reads of them, then work again.
+if a[:2] in (["get","keycloakrealmimport"],["get","pods"]) and s.get("fail_reads",0)>0:
+    if s.get("reads_ok",0)>0: s["reads_ok"]-=1
+    else: s["fail_reads"]-=1; json.dump(s,open(os.environ["STUB_STATE"],"w")); print("Unable to connect to the server",file=sys.stderr); sys.exit(1)
+    json.dump(s,open(os.environ["STUB_STATE"],"w"))
 def out(o): print(json.dumps(o)); sys.exit(0)
 if a[:2]==["whoami","--show-server"]: print(s["server"]); sys.exit(0)
 if a==["whoami"]: print(s["user"]); sys.exit(0)
@@ -269,8 +274,8 @@
     rc, text, _ = watch(lambda s: None, 0.5)
     yield "a watch that ended cleanly leaves the gate open", rc == 0 and not os.path.exists(stop + ".alive") and run(guard, "gate", stop).returncode == 0
     # the import's wait, and its withdrawal: only ever our own, by name
-    def waits(our, pods, stop_set=False, watch_gone=False, **env):
-        open(ARGV, "w").close(); s = base_state(); s["our_import"] = our; s["import_pods"] = pods; save(s)
+    def waits(our, pods, stop_set=False, watch_gone=False, fail_reads=0, reads_ok=0, **env):
+        open(ARGV, "w").close(); s = base_state(); s["our_import"] = our; s["import_pods"] = pods; s["fail_reads"] = fail_reads; s["reads_ok"] = reads_ok; save(s)
         if os.path.exists(stop): os.unlink(stop)
         if stop_set: open(stop, "w").close()
         if watch_gone: open(stop + ".alive", "w").write("999999")
@@ -288,6 +293,15 @@
     rc, d = waits(started, [], watch_gone=True, CMAPI_GUARD_SCHEDULE_DEADLINE="60"); yield "the watch gone, not started: withdrawn", rc == 1 and d == only_ours
     rc, d = waits(started, [running]); yield "running too long: reported, never interrupted", rc == 1 and d == []
     rc, d = waits(errors, [{"status": {"phase": "Failed", "containerStatuses": [{"state": {"terminated": {}}}]}}]); yield "failed: withdrawn, so the Job does not try again", rc == 1 and d == only_ours
+    rc, d = waits(errors, [running]); yield "HasErrors while its pod runs, the operator's own error: never interrupted", rc == 1 and d == []
+    rc, d = waits(errors, [pending]); yield "HasErrors with no pod started: withdrawn at the deadline", rc == 1 and d == only_ours
+    rc, d = waits(errors, [{"status": {"phase": "Running", "containerStatuses": [{"state": {"terminated": {"exitCode": 137}}}]}}]); yield "HasErrors, a container killed: withdrawn", rc == 1 and d == only_ours
+    rc, d = waits(started, [pending], fail_reads=10 ** 6); yield "reads failing, not started: still withdrawn at the deadline, not left to fire", rc == 1 and d == only_ours
+    rc, d = waits(started, [running], fail_reads=10 ** 6, reads_ok=2); yield "reads failing after it started: reported, never interrupted", rc == 1 and d == []
+    s = base_state(); s["http"]["cmapi"] = [200, '{"realm":"cmapi","public_key":"k"}']; base_http = s["http"]
+    open(ARGV, "w").close(); s["our_import"] = done; s["import_pods"] = [running]; s["fail_reads"] = 2; save(s)
+    if os.path.exists(stop): os.unlink(stop)
+    r = run(guard, "import-wait", stop); yield "a read that fails twice does not end the follow: Done, passes", r.returncode == 0 and "delete" not in open(ARGV).read()
     open(ARGV, "w").close(); s = base_state(); s["our_import"] = done; s["import_pods"] = [running]; s["http"]["cmapi"] = base_http["cmapi"]; save(s)
     r = run(guard, "import-wait", stop); yield "Done and the realm answers: passes, deletes nothing", r.returncode == 0 and "delete" not in open(ARGV).read()
     open(stop, "w").close()
@@ -312,7 +326,7 @@
     "no context check": ("if not context.endswith(CONTEXT_SUFFIX):", "if False:"),
     "no principal check": ("if user not in PRINCIPALS:", "if False:"),
     "an answer cut short ends the watch": ("except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):", "except (urllib.error.URLError, OSError, ValueError):"),
-    "an unreadable pod ends the watch": ("except (Stop, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:", "except Stop as e:"),
+    "an unreadable pod ends the watch": ("except (Stop, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:\n                    kc = {}", "except Stop as e:\n                    kc = {}"),
     "a breach during the import does not stop the run": ("if why_stopped(stop_file):\n                # A running", "if False:\n                # A running"),
     "the realm name is not checked": ('r"^    realm: cmapi$")', 'r"^  realm:$")'),
     "a second document is allowed": ('if re.search(r"^---", text, re.M) or re.search(r"^\\.\\.\\.", text, re.M):', "if False:"),
@@ -325,6 +339,9 @@
     "the heartbeat outlives a clean end": ("    os.unlink(alive)\n", ""),
     "the watch never beats": ("            os.utime(alive)\n", ""),
     "import-wait ignores a dead watch": ("        if not started and why_stopped(stop_file):", "        if not started and os.path.exists(stop_file):"),
+    "HasErrors alone interrupts a running import": ('if condition(kri, "HasErrors") == "true" and any(pod_failed(p) for p in pods):', 'if condition(kri, "HasErrors") == "true" and started:'),
+    "a failed read ends the follow": ("except (Stop, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:\n            print(f\"{now()} could not read the import", "except ZeroDivisionError as e:\n            print(f\"{now()} could not read the import"),
+    "a failed read forgets it started": ("kri, started = {}, started_at is not None", "kri, started = {}, False"),
     "the watch ignores a restart": ('problems.append(f"keycloak-0 restarted: {kc}")', "pass"),
     "the watch never reports": ("if down and waited >= REPORT_AFTER_SECONDS and not reported:", "if False:"),
     "the watch does not stop the run": ("open(stop_file, \"a\").close()", "pass"),
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/docs/13-crc-deployment.md b/docs/13-crc-deployment.md
--- a/docs/13-crc-deployment.md	2026-11-06 07:38:17
+++ b/docs/13-crc-deployment.md	2026-11-06 07:38:17
@@ -275,7 +275,8 @@
 | Our pod's container not started | 300 s from the apply. An earlier import here waited about 6.5 days | Deletes `KeycloakRealmImport cmapi`, by name |
 | The run stopped, not started | At once | The same delete |
 | Started, not done | 300 s after start; 79 s measured at this CPU limit | Reports. **Never interrupted** |
-| `HasErrors` with a started pod | At once | The same delete, which stops the Job's further attempts |
+| `HasErrors` with a failed pod | At once | The same delete, which stops the Job's further attempts. `HasErrors` alone is not enough: the operator also sets it for an error of its own while a pod runs on (its 26.6.4 source; RHBK's is inferred) |
+| A read that fails | Goes on, on what it last knew, to these same bounds | Logged. It does not leave a pending import unfollowed |
 | `Done`, realm present | | rc 0, unless the watch stopped the run meanwhile |
 | `Done`, realm absent | | Stops |
 
````

### `08-reader-ca-bundle.patch`

````diff
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/cmapi/src/cmapi/core/registry.py b/cmapi/src/cmapi/core/registry.py
--- a/cmapi/src/cmapi/core/registry.py	2026-11-06 06:07:38
+++ b/cmapi/src/cmapi/core/registry.py	2026-11-06 06:08:30
@@ -19,6 +19,7 @@
 import base64
 import binascii
 import os
+import re
 import tempfile
 import threading
 import time
@@ -39,6 +40,7 @@
 INSECURE_ALLOWED = {"rnd"}
 STATUSES = ("connected", "not-imported", "invalid-secret", "unreachable", "cert-verify-failed", "auth_failed",
             "wrong-identity", "forbidden", "environment-not-served")
+PEM_CERTIFICATE = re.compile(r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", re.S)
 
 
 @dataclass
@@ -138,6 +140,15 @@
         return [_secret(s) for s in r.json().get("items", [])]
 
 
+def _valid_ca_data(ca_data: str) -> bool:
+    """Each PEM block by itself: a service account's ca.crt is usually a bundle, and base64 padding may end any block, so the blocks joined are not base64 even when each one is."""
+    bodies = PEM_CERTIFICATE.findall(ca_data) or ["".join(l for l in ca_data.splitlines() if not l.startswith("-----"))]
+    try:
+        return all(base64.b64decode("".join(b.split()), validate=True) for b in bodies)
+    except (binascii.Error, ValueError):
+        return False
+
+
 def _secret(doc: Mapping[str, Any]) -> dict[str, Any]:
     meta = doc.get("metadata", {})
     data = {k: base64.b64decode(v).decode() for k, v in (doc.get("data") or {}).items()}
@@ -190,13 +201,8 @@
         ca_data = d.get("caData")
         if insecure and ca_data:
             findings.append("insecure with caData")
-        if ca_data:
-            try:
-                der = base64.b64decode("".join(l for l in ca_data.splitlines() if not l.startswith("-----")), validate=True)
-                if not der:
-                    raise ValueError
-            except (binascii.Error, ValueError):
-                findings.append("invalid caData")
+        if ca_data and not _valid_ca_data(ca_data):
+            findings.append("invalid caData")
         # 3. TLS mode
         env = st.policy.environment if st.policy else None
         if insecure and env not in INSECURE_ALLOWED:
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/cmapi/tests/service/test_registry_ca_bundle.py b/cmapi/tests/service/test_registry_ca_bundle.py
--- a/cmapi/tests/service/test_registry_ca_bundle.py	1969-12-31 18:00:00
+++ b/cmapi/tests/service/test_registry_ca_bundle.py	2026-11-06 06:08:30
@@ -0,0 +1,55 @@
+"""The reader's import Secret carries the service account's ca.crt as caData (deploy/crc-reader-import.sh). That is usually a bundle of several certificates, and base64 padding may end
+any of them, so the six checks must read each block by itself. Needs no database, and no certificate: the check is on the encoding, and TLS reads the file later."""
+from __future__ import annotations
+
+import base64
+
+import pytest
+
+from cmapi.core.registry import READER_IDENTITY, ClusterPolicy, ClusterRegistry
+
+
+class Reader:
+    def __init__(self, *args, **kw):
+        pass
+
+    def version(self):
+        return "v1.35.0"
+
+    def whoami(self):
+        return READER_IDENTITY
+
+    def list(self, kind, **kw):
+        return {"items": []}
+
+    def close(self):
+        pass
+
+
+def check(ca_data):
+    policy = ClusterPolicy(cluster_id="CRC", environment="dev", gitops_path="clusters/CRC", writes=False)
+    registry = ClusterRegistry({"CRC": policy}, None, client_factory=Reader, start_caches=False)
+    return registry._check("CRC", {"data": {"apiUrl": "https://kubernetes.default.svc", "token": "t", "caData": ca_data}, "annotations": {}})
+
+
+def pem(size):
+    """A block whose base64 ends in one '=' (size % 3 == 2), two (size % 3 == 1) or none."""
+    body = base64.b64encode(bytes(range(256)) * (size // 256) + bytes(range(size % 256))).decode()
+    lines = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
+    return f"-----BEGIN CERTIFICATE-----\n{lines}\n-----END CERTIFICATE-----\n"
+
+
+@pytest.mark.parametrize("sizes", [[1000], [1001], [1002], [1000, 1001, 1002, 1003, 1004], [1001, 1000], [1002, 1002, 1002]], ids=str)
+def test_one_certificate_or_a_bundle_connects(sizes):
+    st = check("".join(pem(s) for s in sizes))
+    assert (st.status, st.findings) == ("connected", [])
+
+
+@pytest.mark.parametrize("ca_data", [
+    "not base64 at all!",
+    "-----BEGIN CERTIFICATE-----\n!!!!\n-----END CERTIFICATE-----\n",
+    pem(1000) + "-----BEGIN CERTIFICATE-----\nAAA=AAA\n-----END CERTIFICATE-----\n",
+], ids=["no-pem", "garbage-block", "garbage-second-block"])
+def test_what_is_not_base64_is_still_refused(ca_data):
+    st = check(ca_data)
+    assert st.status == "invalid-secret" and st.findings == ["invalid caData"]
````

### `09-realm-one-password-client.patch`

````diff
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/cmapi/tests/service/test_plain_manifests.py b/cmapi/tests/service/test_plain_manifests.py
--- a/cmapi/tests/service/test_plain_manifests.py	2026-11-06 06:09:36
+++ b/cmapi/tests/service/test_plain_manifests.py	2026-11-06 06:13:12
@@ -265,6 +265,16 @@
     assert len(list(yaml.safe_load_all((CRC / "realm/10-realm-import.yaml").read_text()))) == 1
 
 
+def test_crc_realm_takes_a_password_only_through_the_automation_client_and_limits_guesses():
+    """A public client with direct grants takes a person's password with no secret. Keycloak gives every realm one, admin-cli, unless the import names it. Measured in deploy/tests/realm-test.py."""
+    realm = crc("KeycloakRealmImport", "cmapi")["spec"]["realm"]
+    direct = [c["clientId"] for c in realm["clients"] if c.get("directAccessGrantsEnabled") and c.get("enabled")]
+    assert direct == ["cmapi-automation"]
+    admin_cli = next(c for c in realm["clients"] if c["clientId"] == "admin-cli")
+    assert admin_cli["enabled"] is False and admin_cli["directAccessGrantsEnabled"] is False
+    assert realm["bruteForceProtected"] is True and realm["permanentLockout"] is False
+
+
 def test_crc_realm_sync_is_one_try_and_requires_the_federation():
     job = crc("Job", "cmapi-realm-sync")["spec"]
     assert job["backoffLimit"] == 0 and job["template"]["spec"]["restartPolicy"] == "Never", "no retries against a Keycloak that is down"
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/manifests/environments/crc/realm/10-realm-import.yaml b/deploy/manifests/environments/crc/realm/10-realm-import.yaml
--- a/deploy/manifests/environments/crc/realm/10-realm-import.yaml	2026-11-06 06:09:36
+++ b/deploy/manifests/environments/crc/realm/10-realm-import.yaml	2026-11-06 06:13:12
@@ -55,6 +55,11 @@
     offlineSessionMaxLifespan: 7776000
     revokeRefreshToken: true
     refreshTokenMaxReuse: 0
+    # This realm reads every person in the shared directory, and without this anyone who reaches the Route could guess their passwords without limit (40 in 1.1 s, measured).
+    # Temporary only: a lockout is in this realm, for 60 s and doubling, never in LDAP.
+    bruteForceProtected: true
+    permanentLockout: false
+    failureFactor: 10
     clientScopes:
     - name: basic
       protocol: openid-connect
@@ -219,6 +224,13 @@
         - name: cmapi-approval-relay
           description: approvals:relay for channel integrations
     clients:
+    # Every realm gets a public admin-cli that takes a password with no client secret, so cmapi-automation's secret would guard nothing (measured). Nothing here uses it.
+    - clientId: admin-cli
+      name: Not used in this realm
+      enabled: false
+      publicClient: true
+      standardFlowEnabled: false
+      directAccessGrantsEnabled: false
     - clientId: cmapi-nonprod
       name: cmapi nonprod API
       enabled: true
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/deploy/tests/realm-test.py b/deploy/tests/realm-test.py
--- a/deploy/tests/realm-test.py	2026-11-06 06:09:36
+++ b/deploy/tests/realm-test.py	2026-11-06 06:13:12
@@ -120,6 +120,14 @@
         check(c.get("groups") == ["/cmapi/cmapi-requesters"], f"groups, filtered on cmapi-*: {c.get('groups')}"); check("cmapi-requester" in c["resource_access"]["cmapi-nonprod"]["roles"], "the group's role")
     check(login("john.doe", "wrong").status_code == 401 or login("john.doe", "wrong").status_code == 400, "a wrong LDAP password is refused")
     check(login("bot-user", "rt-bot").status_code == 200, "the local bot user signs in")
+    # A person's password goes through one client, with its secret, and cannot be guessed without limit.
+    for client in ("admin-cli", "cmapi-portal", "cmapi-docs", "cmapi-cli", "account", "account-console", "security-admin-console"):
+        r = httpx.post(f"{B}/realms/cmapi/protocol/openid-connect/token", data={"grant_type": "password", "client_id": client, "username": "bot-user", "password": "rt-bot"}); check(r.status_code != 200, f"{client} takes no password with no client secret: {r.status_code}")
+    for _ in range(realm["failureFactor"]):
+        login("amy", "wrong")
+    time.sleep(1)                      # the protector counts on its own thread
+    check(login("amy", "rt-amy").status_code != 200, "after that many wrong guesses even the right password is refused for now")
+    check(login("ola", "rt-ola").status_code == 200, "and no one else is")
     adm = httpx.post(f"{B}/realms/cmapi/protocol/openid-connect/token", data={"grant_type": "client_credentials", "client_id": "cmapi-realm-admin", "client_secret": vals["CMAPI_REALM_ADMIN_SECRET"]}).json()["access_token"]; A = {"Authorization": f"Bearer {adm}"}
     check(httpx.delete(f"{B}/admin/realms/corp-rt", headers=A).status_code == 403, "cmapi-realm-admin cannot delete another realm")
     # A sync that cannot reach LDAP must fail the Job.
diff -ruN --no-dereference -x __pycache__ -x .pytest_cache -x *.pyc a/docs/13-crc-deployment.md b/docs/13-crc-deployment.md
--- a/docs/13-crc-deployment.md	2026-11-06 06:09:36
+++ b/docs/13-crc-deployment.md	2026-11-06 06:13:12
@@ -15,7 +15,7 @@
 | Namespace `cmapi-system` (new) | ServiceAccount `cmapi-reader` and its token Secret |
 | Cluster | ClusterRole and ClusterRoleBinding `cmapi-reader`: `get, list, watch` on namespaces, resourcequotas and limitranges, `list` on pods and persistentvolumeclaims |
 | Namespace `keycloak` | Secret `cmapi-realm-secrets`, and `KeycloakRealmImport cmapi`, deleted once Done |
-| Keycloak | Realm `cmapi`. Creating any realm also adds a client `cmapi-realm` to `master` (measured). That is the one known change outside realm `cmapi` |
+| Keycloak | Realm `cmapi`, with guesses limited (a temporary lockout, in this realm alone) and its default `admin-cli` client off, so no client takes a person's password without a secret. Creating any realm also adds a client `cmapi-realm` to `master` (measured). That is the one known change outside realm `cmapi` |
 
 In LDAP nothing is written: the realm reads it through the read-only `cmapi-ldap-bind`. See [`docs/11`](11-existing-identity-services.md).
 
````
