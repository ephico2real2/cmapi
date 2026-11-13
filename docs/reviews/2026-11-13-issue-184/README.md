# #184 (SEC-07): the review of the change that requires the token type `at+jwt`

The change is about tokens, so it has a second reader.

| Who | What |
|---|---|
| OB1, Fable 5.2 | The change (commit `3026637`), then the rulings, a run of each of Codex's tests before and after its fix, and this record |
| Codex `gpt-6.1-sol`, 2026-11-13, 195,225 tokens | Seven claims on an export of `11ce7b7`: `brief.md`. Its report, with the full code of each fix and test and the sources that it read (Keycloak 26.6.4, PyJWT 2.10.1, RFC 9068, RFC 7515, RFC 8725): `codex-report.md` |

## The rulings

| Claim | Codex | Ruling |
|---|---|---|
| C1. The header that is checked is the header of the token whose signature was verified | CONFIRMED. The type check after the signature check is not a bypass | Stands. Codex's test changes the header and keeps the signature: 3 cases, each 401 "Invalid token" |
| C2. No token that is not an access token passes in the default mode | CONFIRMED, for 13 wrong forms and 8 right forms on tokens signed with an exact header | Stands. The cases are in the suite |
| C3. The legacy mode accepts only the header `JWT` with the claim `Bearer` | CONFIRMED. No other check is necessary: a Keycloak ID token has the claim `typ: ID` and the audience of its client | Stands |
| C4. Each client that gets a token for cmapi has the attribute | REFUTED on one condition: Keycloak's V1 token exchange encodes the token in the context of the target client (`V1TokenExchangeProvider.setClientToContext`), and the API's own bearer-only client had no attribute in the two realm files. The realm files turn no exchange on | **Accepted.** The API's client has the attribute in the CRC import and in the chart. The sync already set it on that client, so the import now equals what the sync writes. 2 cases failed before. `test_plain_manifests.py` no longer exempts that client |
| C5. The sync finds each client that gets a token for cmapi | REFUTED: a client with `cmapi-audience` as an optional scope gets a token for cmapi when the request names the scope, and the sync missed it | **Accepted.** Codex's fix reads the default and the optional scopes. 1 test failed before. Not found by the sync, and now said in `docs/15`: a client with an audience mapper of its own |
| C6. No test of a refusal passes for the wrong reason | CONFIRMED for the refusal causes, with one defect of coverage: E1 | Stands |
| C7. The order of the rollout | REFUTED: `docs/13` applied the API before the sync, and no document gave the order of an upgrade | **Accepted, with OB1's text.** The sync is now step 20 of `docs/13` and the workloads are step 21. Codex's order test failed before. See "C7" below |
| E1. The test "no header type and no claim" had the header `JWT` | REFUTED: `Keys.token(typ=None)` left out the key, and PyJWT then wrote its own `JWT` | **Accepted.** The fixture gives `typ: None`, which PyJWT deletes. 1 test failed before. The two cases of `test_auth.py` now test a token with no header type |
| E2. The chart does not write `auth.acceptLegacyTokenType` | REFUTED: `--set auth.acceptLegacyTokenType=true` changed nothing in `instance.yaml` | **Accepted.** The chart writes the value, default `false`. 1 case failed before |

Codex's tests are in the service suite: `test_review_r184_token_type.py`, `test_review_r184_realm_sync.py` and `test_review_r184_deploy.py`. On the reviewed code: 6 failed, 30 passed. With the fixes: 36 passed. Codex wrote the fixes of C4, C5, E1 and E2 and those tests. Fable 5.2 wrote the rest.

Changes to Codex's tests: they find the repository from their own path and not from `REVIEW184_HEAD`, they use the suite's `keys` fixture, and the two chart tests do not run where `helm` is not installed, as `test_review_r181_helm_admin_cli.py` does.

## C7: what was taken and what was not

Codex's scenario is an upgrade: a realm that was imported before #184, and a new API that starts before the sync. `docs/13` is the first deployment. Its step 4 stops when realm `cmapi` exists, and step 15 imports a realm that has the attribute on each client. So no token of a `docs/13` run has the header `JWT` because of the order.

The order is still better with the sync first. Before the sync a token has no `employee_id`, so the API served a realm that was not complete. The Job needs nothing from the workloads: its trust file is from step 6, its ServiceAccount from step 8 and its Secrets from step 11. The policy of step 21 selects only the API and the worker. So the two steps changed places, and `deploy/tests/doc13-test.py` holds the new order (0 cases failed, 0 mutants survived).

Not taken from Codex's text: the upgrade instructions inside step 20. They are in `docs/15`, "The type of an access token", where the setting is: run the sync while the old API serves, wait for the lifetime of an access token (300 seconds) or get new tokens, then roll out the API, or set `auth.acceptLegacyTokenType` for that time. Codex's text also removed the reasons of the step (`employee_id`, #96, #110). They stay.

The chart runs the sync as a `post-upgrade` hook, after the new pods start. That is not changed here: a `pre-upgrade` hook would run the new image with the old ConfigMap. `docs/15` says that a chart upgrade across #184 needs the setting or the sync by hand. No deployment of the chart exists today.

The memory table of `docs/13` has a new row for step 20 (the database plus the Job, 352 Mi). Step 19 still asks for 672 Mi, which is now more than the run uses after the import.

## Not changed

- The type check stays after the signature check (C1). Before it, a wrong type would answer 401 where an unreachable Keycloak now answers 503, and no check would be stronger.
- The legacy mode has no list of permitted clients (C3). The claim `typ: Bearer` with the signature, the issuer and the audience tells an access token from an ID token and a refresh token of Keycloak.
- Codex's caution on C5 is not a finding: a `PUT` of a client can start a client policy of the server. The sync of #181 uses the same `PUT`.

## Not tested

Nothing here ran against a real Keycloak on this Mac: containers are off (#157). The realm test (`deploy/tests/realm-test.py`) runs in GitHub's `manifests` job, on a real Keycloak and OpenLDAP. Its result for this change is in the pull request. No token exchange ran: C4 is from Keycloak's source and from the realm files. Nothing ran on CRC: realm `cmapi` is not there. There was no second pass on the fixed head: the fixes of C4, C5, E1 and E2 are Codex's own, and C7 changes a document that its test and `doc13-test.py` hold.
