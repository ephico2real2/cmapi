"""cmapi.capacity: the usage analysis of docs/03 (#310), run in the embedded mode of docs/01 ("One interface, two modes"):
the API reads one namespace's live 14-day usage for a quota-change plan, and the worker runs the daily sweep that stores the
verdicts GET /api/v1/quotas joins in memory. Only this package builds PromQL or reads a MetricsSource.

    thanos.py    MetricsSource for each cluster's Thanos Querier (docs/02, "cmapi-capacity (capacity/)")
    usage.py     UsageSource: one namespace's 14-day usage, and a cluster's namespaces for the sweep; none when unconfigured
    verdicts.py  the verdict rules and thresholds of docs/03, "Verdicts", as pure functions
    sweep.py     the daily sweep and the stored verdicts (analysis_sweeps, namespace_verdicts)
"""
