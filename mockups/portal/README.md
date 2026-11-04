# cmapi Portal mockup

Source of the portal mockup. It is a Claude Design canvas artboard (`Main.dc.html` plus
`canvas.json`), so it renders in the Design canvas rather than as a plain HTML page.

Live version: https://claude.ai/artifact/HW3mp5RRmuapPhj8beBH1M

What it shows, per instance (nonprod, staging, prod; switched with the `instance` tweak):

- **Workflow:** the request flow in the same lanes as `../cmapi-flow.html` (caller, Keycloak,
  cmapi-api, cmapi-capacity, cluster-configs, Argo CD), including a wrong-instance request that
  gets 422 `environment-not-served` with the right instance's URL.
- **New namespace:** schema-driven form limited to the instance's allowedEnvironments, with
  placement, an optional expiry date (hidden in prod) and plan preview.
- **Quotas:** every namespace's ResourceQuota (requests.cpu, requests.memory, pods; used
  vs hard) with its usage verdict and any recommendation, for a few hundred generated namespaces
  per instance: A to Z, 25/50/100 per page with previous/next, a letter bar, type-ahead search
  (name prefix, then contains, then team or app), env/cluster/tier filters, sort by name, % used
  or attention, attention counts as one-click filters, and CSV export. Pick one to plan a tier or custom
  change: live 14-day usage, CPU and memory checks against the cluster (zone-failure in prod),
  the approval that will apply, and the 202 or 422 that submitting returns.
- **Expiration:** non-prod namespaces by expiry state (needs action, expiring, in grace, pending delete,
  active, permanent), paged and searchable, with Extend 7/14/30 days, Make permanent and Set a date,
  the limits and the approval each one needs. On the prod instance: "production namespaces never expire".
- **Requests:** drill-down that opens the workflow at the request's current step, newest first.
- **Approvals:** requests waiting in cmapi (nothing in Git yet) with Approve and Reject (a reason is
  required), your eligibility, the approvals so far and the channels that notified approvers.
- **Policies:** Kyverno bundle per cluster against the pinned tag, results by policy, failing resources,
  and cmapi's own refusals at plan time and in CI.
- **Capacity:** CPU and memory commitment and headroom per cluster and group from stored
  snapshots, with the resource that binds each one.
- **KPIs:** System status (each component's memory, CPU, throttling and event-loop lag against
  kpi.thresholds, with the rule beside any amber meter) and the database (connections, volume,
  size by schema, pools, backups; unavailable where nothing reports), then the agreed KPIs and the
  eight dashboards (Perses in the OpenShift console).

The header links to the instance's Swagger UI (`/docs`) and ReDoc (`/redoc`).
