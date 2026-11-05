# cmapi, local end-to-end

The reference modules in `examples/src/cmapi` behind a real HTTP API, against real services:

| Piece | Here | In production |
| --- | --- | --- |
| Identity | Keycloak 26 (release tarball, `start-dev`), realm `ephico2real` built by `keycloak_setup.py`: User Profile with `employeeId` and `middleName`, the `cmapi-identity` client scope, client roles on `cmapi-nonprod`, groups under `/cmapi`, users `ola` (requester), `amy` (platform-leads), `opal` (operator), the `svc-payments-ci` and `cmapi-directory` clients | Same realm, LDAP-federated users |
| Tokens | Verified offline against the realm's JWKS (PyJWT), audience `cmapi-nonprod` | Same |
| Directory | `core/identity/keycloak_admin.py` against the admin API as `cmapi-directory` (onBehalfOf by employee ID) | Same |
| Git | A local bare repository `cluster-configs-nonprod.git`; a bot PR is a branch, CI runs on it, the bot merges `--no-ff` with the expected head | GitHub or GitLab REST |
| CI | kubeconform (strict) and the Kyverno 1.16 CLI on the rendered files, plus the cmapi check (the branch holds exactly the approved plan) | Git host CI |
| Cluster | k3s v1.31, air-gapped (images from the GitHub release, no registry) | OpenShift |
| Argo CD | A stand-in in the worker: server-side apply of the merged folder, confirmed by a read; deletes wait in `awaiting_prune` until an operator confirms | Argo CD, `Prune=confirm` |
| Capacity | Simulated from `config/clusters.yaml` (64 cores, 256Gi, overcommit from capacity.yaml) | cmapi-capacity and Thanos |
| Store | In memory | PostgreSQL |

Run it: `sudo ./run.sh` (downloads once, starts Keycloak, k3s and the API on :8000, runs the 113 tests and
`demo.py`). `./run.sh stop` stops everything. `transcript.txt` is the output of the last run.

What `demo.py` exercises, all through the API with real tokens:

1. `GET /me` from the token: username, roles, groups, employee ID, middle name.
2. `GET /tiers?environment=dev`.
3. Refusals at plan time: a namespace outside the caller's binding (403), a team DL outside
   `emailDomains`, a quota with a named tier, a system key from the caller, a service client without
   `onBehalfOf`.
4. A dry run: files, capacity, approval (auto-approved by `baseline-rnd-namespace`), plan hash.
5. Submit: approved → bot PR → CI → merged → applied on k3s → synced; the Namespace, ResourceQuota and
   LimitRange on the cluster.
6. A large namespace: pending approval; the requester and an approver outside the approving group are
   refused; `amy` approves; it syncs.
7. `svc-payments-ci` on behalf of employee 1001: the requester recorded and labelled is `ola`.
8. Tier change medium → large: three files change; the quota on the cluster and its `tier-hash`.
9. Expiry: a 40-day extension is refused (`expiration-limit`), 30 days goes through.
10. A sensitive key change adds platform-leads.
11. `GET /quotas`: paged from the live cluster, with facets.
12. Delete: approved, merged, held in `awaiting_prune` until `opal` confirms, then the namespace terminates.
13. The Git history: one bot PR per request.

Found by running it (fixed in the design and the code):

- The Kyverno 1.16 CLI silently applies **0 rules** to a `policies.kyverno.io/v1` document, so a CI
  check on it passes vacuously. The policies now use `v1beta1`, and the validator fails when the CLI
  reports `Applying 0 policy rule(s)`.
- Every create counted as a sensitive-key change (the first `cmapi.net/team`), so no create could be
  auto-approved. Setting a sensitive key the first time is no longer a change.
- `TierError` must map to a 422 `policy-violation`; the routers now do.
