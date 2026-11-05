# Examples

Configuration and manifests from the design, laid out at the paths they will have in the cmapi
and cluster-configs repositories. Each file starts with a `# Source:` line naming the document it
came from. Where two documents show the same file, the copy in
[01-design-and-architecture.md](../docs/01-design-and-architecture.md) wins.

| Path | What it is | Origin |
| --- | --- | --- |
| `config/instance.yaml` | One instance's identity: name, allowedEnvironments, URLs, Keycloak audience, requester identity and DirectoryProvider settings, Git repository, directory of the other instances | Updated |
| `config/tiers.yaml` | The tier catalog (combined reference): sizable keys, defaults, small/medium/large/custom, custom bounds and per-environment overrides. Read only by `cmapi.core.tiers` | Values are proposals |
| `instances/<instance>/tiers.yaml` | Each instance's catalog: the same tiers, only its own environments | Derived |
| `src/cmapi/` | Reference implementation of the pure-logic modules in the v2 Module catalog: `core/` config, errors, ports (Protocols for every extension point), authz, expression, metadata, tiers, approvals, lifecycle, listquery, ratelimit, `identity/` (claims, directory, keycloak_admin, checks), `render/manifests.py`; `plugins/expiration/rules.py` | Reference code |
| `tests/` | 113 tests over every module above, against the example configs and the example namespace folder. Run from `examples/`: `PYTHONPATH=src:tests python -m pytest -q` | Reference code |
| `local/` | The reference modules behind a FastAPI app, run end to end against a real Keycloak, a local Git repository and an air-gapped k3s cluster: `run.sh`, `demo.py`, `transcript.txt` (see local/README.md) | Runnable |
| `instances/<instance>/instance.yaml`, `expiration.yaml` | Each instance's identity file and expiry limits (prod: none) | Derived |
| `config/clusters.yaml` | Policy, metadata and placement per cluster (connections come from imports) | Verbatim |
| `config/plugins.yaml` | Which plugins load, keyed by instance | Verbatim |
| `config/authz-scopes.yaml` | Role-to-scope bindings (shape reference) | Verbatim |
| `config/capacity.yaml` | Snapshot interval, targets, overcommit per environment | Verbatim |
| `config/approval-rules.yaml` | Combined reference: environment rules, patterns, thresholds and auto-approval policies (baseline-rnd-namespace for rnd and dev, expired-namespace) | Updated to the approval-first design |
| `instances/<instance>/approval-rules.yaml`, `authz-scopes.yaml` | The real per-instance files: each holds only its own environments and clusters | Derived |
| `config/expiration.yaml` | Optional expiration: 30-day extensions, 180-day lifetime, notices, 7-day grace; prod has no entry | From the design |
| `cluster-configs/policies/env/prod/deny-expiry-in-prod.yaml` | Kyverno ValidatingPolicy: prod namespaces never carry expiry metadata | Starter: check the apiVersion against your Kyverno release |
| `config/integrations.yaml` | Optional SyncSignal, OperationsEngine and EventPublisher | Verbatim |
| `config/operations/cluster-onboard.yaml` | Operation template run by the built-in engine or Argo Workflows | Verbatim |
| `cmapi-sso/realm/ephico2real.yaml` | Keycloak realm as code (keycloak-config-cli), with the employee ID and middle-name mappers, User Profile declarations and the cmapi-identity client scope | Updated: check key names against your keycloak-config-cli release |
| `cluster-configs/policies/metadata-keys.yaml` | Governed, team and sensitive metadata keys (cmapi.net/team-dl required; cmapi.net/owner retired) and emailDomains, the organisation's mail domains that every email-valued key must use (ephico2real.com is a placeholder) | Updated |
| `cluster-configs/clusters/OCP_GF15/namespaces/payments-dev/` | One namespace as cmapi writes it: namespace.yaml, resourcequota.yaml, limitrange.yaml, serviceaccounts.yaml, rolebindings.yaml, token-issuer-rolebinding.yaml (plain manifests, dev, optional expiry) | New |
| `cluster-configs/clusters/OCP_GF15/argocd/root-application.yaml` | The cluster's root Application: syncs every namespace folder with directory recurse | New; set repoURL and the AppProject |
| `cluster-configs/clusters/OCP_GF1/bootstrap/notifications.yaml` | Argo CD Notifications with a per-cluster token and cluster ID | Updated |
| `baseline/cmapi-reader-rbac.yaml` | The read-only cmapi-reader ServiceAccount the baseline process applies to every cluster, now with Kyverno policy reports | Updated |
| `hub/cmapi-imports-secret.yaml` | The import contract: one Secret per cluster in cmapi-imports | Verbatim |
| `hub/cmapi-adoption-configmap.yaml` | Adoption selector and exclusions | Verbatim |
| `observability/servicemonitor.yaml` | One per component on the metrics port | Verbatim |
| `observability/prometheusrule.yaml` | The 23 agreed alerts (13 service, 10 system and lifecycle) and short-window KPI recording rules | Starter: names, conditions and severities agreed; PromQL is a first draft |
| `observability/perses.yaml` | UIPlugin, PersesDatasource and the list of the eight dashboards | Starter: check apiVersions against the installed operator |
| `helm/values-kpi.yaml` | KPI thresholds, database collection, dashboards provider, monitoring switches and the resource limits the system meters measure against | Starter: limits are proposals |

Notes:

- Each instance's files hold only its own allowedEnvironments: nonprod rnd and dev, staging qa
  and uat, prod prod. The files under `config/` that list every environment are references;
  deploy the ones under `instances/`.
- cmapi writes plain Kubernetes manifests, one folder per namespace; nothing on the cluster expands them.
  Who asked comes from the token; employee ID and names stay in cmapi's database, never in these files.
- Approvals are recorded in cmapi (`POST /requests/{id}:approve`); nothing in these files relies on
  Git reviews or approval labels.
