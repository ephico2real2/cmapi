# #181 (SEC-06): the review of the change that removes the password grant

The change is about sign-in and tokens, so it has a second reader.

| Who | What |
|---|---|
| OB1, Fable 5.2 | The change, commits `4a8dd54` and `31d625b`, then the rulings, a run of each of Codex's tests before and after its fix, and this record |
| Codex `gpt-6.1-sol`, 2026-11-13, 202,745 tokens | Ten claims on an export of `31d625b`: `brief.md`. Its report, with the full code of each fix and test and the Keycloak 26.6.4 source that it read: `codex-report.md` |

## The rulings

| Claim | Codex | Ruling |
|---|---|---|
| C1. The password is in one request, and no error text holds a secret | REFUTED: an error repeated text of Keycloak's page, the path of a redirect and the `error_description` of an answer. A theme or a provider can put a secret there | **Accepted.** Codex's fix: an error is a constant of the script, and a page message passes only when it is one of two known messages of Keycloak. 5 cases failed before |
| C2. The password goes only under the issuer | REFUTED: `https://issuer/realms/cmapi/../other/...` passed the prefix check | **Accepted.** Codex's fix parses each URL, compares the origin, and refuses dot segments, percent escapes, `;`, `//`, userinfo and control characters. 9 cases failed before |
| C3. TLS, the loopback rule, no redirect | REFUTED on one point: `http_proxy` of the environment could carry the clear-text loopback request to a proxy. The rest CONFIRMED, with ten redirect cases | **Accepted.** `ProxyHandler({})`: the script uses no proxy of the environment |
| C4. PKCE and state | CONFIRMED | Stands |
| C5. Cookies are enough for Keycloak 26's form flow | CONFIRMED for the form flow, from the source. A real deployment is not run | Stands. The realm test on a real Keycloak is the proof (GitHub's `manifests` job) |
| C6. The realm files and the service-account import | CONFIRMED | Stands |
| C7. The sync brings an old realm to the new state | REFUTED on two points: the sync read one page of 500 clients, and it removed `bot-user` only when test users are on, so a realm with test users off kept an account that could still sign in through a browser client | **Accepted.** Codex's fix reads each page and removes `bot-user` in each run. cmapi's own sync made that account, so cmapi can delete it. 2 tests failed before |
| C8. The service account gets no more than `bot-user` had | CONFIRMED | Stands |
| C9. The refusal check of `crc-proof.sh` cannot pass with the grant on and counts against no account | CONFIRMED | Stands |
| C10. The new checks of the realm test can fail | PLAUSIBLE: it cannot run without a container | Stands as PLAUSIBLE until the `manifests` job runs it |
| Extra. The chart's realm did not name `admin-cli`, so Keycloak made it with the password grant on, until the sync ran | REFUTED | **Accepted.** The chart names `admin-cli` disabled, as the plain import does. The defect is older than this change |
| Extra. "The diff removes the plugin switch" | REFUTED | **Not a defect.** The export's diff was made against a `main` that had gained #180 after this branch started, so #180's files read as removed. The branch now has `main` merged, and `test_plugins_switch.py` passes on it (41 cases) |

Codex's regression tests are in the service suite: `test_review_r181_oidc_security.py`, `test_review_r181_realm_sync_security.py` and `test_review_r181_helm_admin_cli.py`. On the reviewed head: 7 failed, 4 passed. With the fixes: 11 passed. Codex wrote the fixes of C1, C2, C3, C7 and the chart, and those tests. Fable 5.2 wrote the rest.

One change to Codex's helm test: it finds `helm` on the PATH and not at `/usr/local/bin`, and it also holds each client of the chart's realm to `directAccessGrantsEnabled: false`.

## Not tested

Nothing here ran against a real Keycloak on this Mac: containers are off (#157). The realm test runs in GitHub's `manifests` job. Nothing ran on CRC: realm `cmapi` is not there.
