# Examples

Configuration and manifests from the design, laid out at the paths they will have in the cmapi
and cluster-configs repositories. Each file starts with a `# Source:` line naming the document it
came from. Where two documents show the same file, the copy in
[01-design-and-architecture.md](../docs/01-design-and-architecture.md) wins.

| Path | What it is | Origin |
| --- | --- | --- |
| `config/instance.yaml` | One instance's identity: name, allowedEnvironments, URLs, Keycloak audience, Git repository, directory of the other instances | Verbatim |
| `config/clusters.yaml` | Policy, metadata and placement per cluster (connections come from imports) | Verbatim |
| `config/plugins.yaml` | Which plugins load, keyed by instance | Verbatim |
| `config/authz-scopes.yaml` | Role-to-scope bindings | Verbatim |
| `config/capacity.yaml` | Snapshot interval, targets, overcommit per environment | Verbatim |
| `config/approval-rules.yaml` | Environment rules, patterns, thresholds and auto-approval policies | Verbatim |
| `config/integrations.yaml` | Optional SyncSignal, OperationsEngine and EventPublisher | Verbatim |
| `config/operations/cluster-onboard.yaml` | Operation template run by the built-in engine or Argo Workflows | Verbatim |
| `cmapi-sso/realm/ephico2real.yaml` | Keycloak realm as code (keycloak-config-cli) | Verbatim |
| `cluster-configs/policies/metadata-keys.yaml` | Governed, team and sensitive metadata keys | Verbatim |
| `cluster-configs/clusters/OCP_GF1/...` | A rendered project-meta file and the Argo CD Notifications bootstrap | Verbatim |
| `baseline/cmapi-reader-rbac.yaml` | The read-only cmapi-reader ServiceAccount the baseline process applies to every cluster | Verbatim |
| `hub/cmapi-imports-secret.yaml` | The import contract: one Secret per cluster in cmapi-imports | Verbatim |
| `hub/cmapi-adoption-configmap.yaml` | Adoption selector and exclusions | Verbatim |
| `observability/servicemonitor.yaml` | One per component on the metrics port | Verbatim |
| `observability/prometheusrule.yaml` | The 21 agreed alerts (13 service, 8 system) and the KPI recording rules | Starter: names, conditions and severities agreed; PromQL is a first draft |
| `observability/perses.yaml` | UIPlugin, PersesDatasource and the list of the eight dashboards | Starter: check apiVersions against the installed operator |
| `helm/values-kpi.yaml` | KPI thresholds, database collection, dashboards provider, monitoring switches and the resource limits the system meters measure against | Starter: limits are proposals |

Notes:

- The project-meta example (`payments-dev` with `env: dev` under `OCP_GF1`) predates the
  instance split; with the agreed rules a dev namespace must sit on a cluster whose
  clusters.yaml environment is dev, served by the nonprod instance.
- Each instance's files hold only its own allowedEnvironments: nonprod rnd and dev, staging qa
  and uat, prod prod.
