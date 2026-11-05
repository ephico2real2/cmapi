# cmapi, local end-to-end

The reference modules in `examples/src/cmapi`, behind a real HTTP API and run against real services:

- Keycloak 26;
- a local Git repository;
- a Kubernetes cluster: k3s, kind, or one you already have.

**The setup and installation guide is [INSTALL.md](INSTALL.md).** It covers every component, by
hand or through `run.sh`, on Linux and macOS, and includes screenshots.

```bash
sudo ./run.sh                    # Linux with root: k3s, no container registry needed
./run.sh                         # macOS or no root: kind (Docker or Podman)
CLUSTER=existing ./run.sh        # the cluster your kubeconfig points at
```

| Piece | Here | In production |
| --- | --- | --- |
| Identity | Keycloak 26, realm `ephico2real` built by `keycloak_setup.py` | Same realm, LDAP-federated users |
| Access | Keycloak client roles → permissions in `config/authz-roles.yaml`; no team or namespace-name scoping | Same |
| Automation | `bot-user`, a local Keycloak account holding `cmapi-onboarding` (create only), signing in through `cmapi-automation` | Same, password in a vault, or a service-account client |
| Tokens | Verified offline against the realm's JWKS, audience `cmapi-nonprod` | Same |
| Directory | `core/identity/keycloak_admin.py` against the admin API as `cmapi-directory` | Same |
| Git | A local bare repository; a bot PR is a branch; the bot merges `--no-ff` against the expected head | GitHub or GitLab REST |
| CI | kubeconform (strict), the Kyverno 1.16 CLI, and the cmapi plan-hash check | Git host CI |
| Cluster | k3s v1.31, kind (Kubernetes v1.31.4) or any cluster, through `kubectl` and a kubeconfig | OpenShift |
| Argo CD | A stand-in in the worker: server-side apply of the merged folder, confirmed by a read; deletes wait in `awaiting_prune` until an operator confirms | Argo CD, `Prune=confirm` |
| Capacity | Simulated from `config/clusters.yaml` | cmapi-capacity and Thanos |
| Store | In memory | PostgreSQL |

`demo.py` runs 14 scenarios through the API with real tokens; INSTALL.md section 4.7 lists them.
`transcript.txt` is the output of the last run, and `screenshots/` holds the images used in the
guide.

Found by running it (all fixed in the design and the code):

- **Kyverno CI check could pass vacuously.** The Kyverno 1.16 CLI silently applies **0 rules** to a
  `policies.kyverno.io/v1` document. The policies now use `v1beta1`, and the validator fails when
  the CLI reports `Applying 0 policy rule(s)`.
- **No create could be auto-approved.** Every create counted as a sensitive-key change (the first
  `cmapi.net/team`). Setting a sensitive key the first time is no longer a change.
- **Tier errors returned 500.** `TierError` now maps to a 422 `policy-violation`.
- **Two more 500s.** `prune:confirm` with nothing waiting, and unknown request IDs, returned 500.
  They now return 409 `nothing-to-prune` and 404.
- **Cancel by the requester never matched.** It read the wrong field of the request record.
