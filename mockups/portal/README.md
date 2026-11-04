# cmapi Portal mockup

Source of the portal mockup. It is a Claude Design canvas artboard (`Main.dc.html` plus
`canvas.json`), so it renders in the Design canvas rather than as a plain HTML page.

Live version: https://claude.ai/artifact/HW3mp5RRmuapPhj8beBH1M

What it shows, per instance (nonprod, staging, prod; switched with the `instance` tweak):

- **Workflow:** the request flow in the same lanes as `../cmapi-flow.html` (caller, Keycloak,
  cmapi-api, cmapi-capacity, cluster-configs, Argo CD), including a wrong-instance request that
  gets 422 `environment-not-served` with the right instance's URL.
- **New namespace:** schema-driven form limited to the instance's allowedEnvironments, with
  placement and plan preview.
- **Quotas:** every namespace's ResourceQuota (requests.cpu, requests.memory, pods; used
  vs hard) with its usage verdict and any recommendation. Pick one to plan a tier or custom
  change: live 14-day usage, CPU and memory checks against the cluster (zone-failure in prod),
  the approval that will apply, and the 202 or 422 that submitting returns.
- **Requests:** drill-down that opens the workflow at the request's current step.
- **Approvals:** manual and auto-approved requests, with the policy that matched.
- **Capacity:** CPU and memory commitment and headroom per cluster and group from stored
  snapshots, with the resource that binds each one.
- **KPIs:** the agreed KPIs and the seven dashboards (Perses in the OpenShift console).

The header links to the instance's Swagger UI (`/docs`) and ReDoc (`/redoc`).
