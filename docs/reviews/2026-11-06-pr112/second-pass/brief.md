ADVERSARIAL REVIEW, SECOND PASS: pull request 112 "LDAP groups app-cmapi-rbac-<role>, cmapi.<role> test users", repository ephico2real2/cmapi, head ecc5cb362b99a4c06fc942466890cdbb753b9ca1, exported to /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/head. Source of the change: issues 110 and 109, and docs/reviews/2026-11-06-pr112/ in the export.

You reviewed an earlier head of this change. Reviewer 2 and the coordinator then accepted the fixes in the commits listed below. Check that each fix closes its hole and opens no other. Then attack what the first pass did not ask. Keep to the named files. Do not read the rest of the repository, because the owner pays for each token.

Commits under review: 47ddb4f The stored requirement's test moves to the service suite;836c761 A stored row with no groupPath reads as the constant it was decided under;797188a LDAP measurements fail closed;7001161 A failed read for a password hash is not zero hashes;5fe1d55 A name LDIF gives in base64 is still a name;ef6b990 The bind user's read of ou=Groups is checked before any write;5623dca The old groups stay until the new set is what the script writes;00f6b72 --remove-test-identities leaves what it did not write;3e66245 A failed openssl makes no Secret;e28ce14 crc-trust.sh --mac-ca keeps working with --extra-ca;0bde88c apply-bind-user.sh: a failed read is not a pass;

For EACH claim, return one line `C<n>: CONFIRMED | REFUTED | PLAUSIBLE | NOT REACHED` and the artefact: a command and its output, or `file:line`. A bare CONFIRMED counts as nothing. A claim in this brief can be false, and some cannot be tested from here. Do not assume a claim is true because this brief states it.

For EVERY finding, give the FULL code of the fix, with its path, and a test that fails before the fix and passes after, in full. The test runs real behaviour; searching a script for a string does not count. A finding without its full snippet and its test is not a finding and will be discarded.

Limits: work only in /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass. C8 is not part of this pass: do not review deploy/tests/doc13-test.py. New files that a fix adds go in its patch (a plain `git diff` misses them). The Python environment with the test dependencies is /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv (put its bin first on PATH); do not install into it. The service tests use the PostgreSQL on 127.0.0.1:55432 (CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi); create your own database on it if you need an empty one, and drop it after. No cluster, no `oc` against a real server, no CRC, no kubeconfig (`KUBECONFIG` is an empty file). Containers are allowed for the test below: use `CONTAINER=podman` only if a daemon answers, and if none does, mark what needs one NOT REACHED and go on. No secrets in any output. No commit and no push. Delete what you create outside this folder.

Claims:

C1. examples/cmapi-sso/ldap/apply-test-identities.sh, `remove_new` and `read_state`. CLAIM: `--remove-test-identities` deletes nothing when any entry at one of its names differs from what the first form writes, and a partial first run can still be removed. Refute it with an interrupted first run, then a removal, then a rerun.
C2. The same file, the old-group removal. CLAIM: `--remove-old-groups` refuses unless every new group and test user reads `same`, and it deletes with a recursive `ldapdelete -r`.
C3. The same file, `measure` and `measure_prog`. CLAIM: no failed step can leave a value that compares equal before and after. Try a step this claim does not name: a failed `awk`, a failed `cut`, a `mktemp` that fails.
C4. The same file, the password generation inside a piped `while`. CLAIM: under /bin/dash and under bash, a failed `openssl` leaves no Secret, and nothing is written to LDAP.
C5. examples/cmapi-sso/ldap/apply-bind-user.sh, the two exit checks. CLAIM: a real OpenLDAP with the rules of the test answers exit 32 for `ou=TrustedApplications` to this user, and the production server named in docs/11 answers the same.
C6. cmapi/src/cmapi/core/db/repo.py and core/authz.py, `requirement_from_json`. CLAIM: a stored row with no `groupPath` reads under `LEGACY_GROUP_PATH`, equal to the constant `main` held before this change, and a new row always stores its path. Name any path that writes a requirement without one.
C7. deploy/crc-trust.sh, `mac_ca`. CLAIM: with `--extra-ca` in the trust file, keycloak-ca.pem is Keycloak's CA, and without it the bundle is byte-identical to the earlier head's.
C9. deploy/tests/ldap-identities-test.sh, `the_failures`. CLAIM: each case fails on the cause it names, and not on a harness error or an earlier leftover. Read the reason a case gives, not only its exit status.
C10. What goes wrong on the next real use: docs/13 steps 9 and 10, then the rollback, in that order, on a server whose group entries also carry an attribute the script did not write. CLAIM: the failure, if any, stops with nothing deleted and says what to do.

End with the single most important finding, and anything you saw that was not asked, each with its full snippet and its test.

## How you read code

If the project has `.tokensave/`, use tokensave to read code. Use grep and whole-file reads only for what it cannot answer. The index can be older than these commits: `graph_root` is `/Users/olasumbo/gitRepos/cmapi-design-crc`. For code these commits changed, read the files in /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/head. Call `tokensave_read` with `mode` `lines`, `map` or `signatures`, because its default reads the whole file and is cut at 15,000 characters. If a tool is not available or fails, say so with the exact error, and go on with the shell. Tests, builds and logs stay in the shell, with short output. Your final message states how many graph calls and how many shell calls you made.

## How you report

Write to /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/ as you work, so that a stop at any moment loses nothing. Keep research and tests apart from your opinions.

| File | Holds |
|---|---|
| `plan.md` | The claims by ID, in your order. Write this first |
| `research.md` | Per ID: each source with `file:line`, a short quote, and what it establishes |
| `tests.md` | Per ID: the exact command with the full path of each tool, the folder, the output and the exit status. Long output goes in `logs/` |
| `verdicts.md` | One row per ID: ID, verdict, one-line reason |
| `fixes.md` | Only for a defect: root cause, full fix, full test, and its result before and after. Patches go in `patches/<ID>.patch`, against /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/head, applying with `patch -p1 --fuzz=0` |
| `resume.md` | The ID you are on, what is next, what is running. Rewrite it after each ID |

After each ID, before the next, append to each file it touches and rewrite `resume.md`. Do not write a section that says only that nothing applies. Do not write a program to test the format of these reports. Label each statement MEASURED, READ FROM CODE or PROPOSAL NOT OPERATED. A claim you did not reach stays NOT REACHED. Your final message is short: the tally of verdicts and the path of `verdicts.md`. Stop after the claims above.
