"""The usage analysis of #310 (story #22, "Existing-namespace changes use live 14-day usage; insufficient data is explicit"):
docs/03's verdict rules at their boundaries, insufficient data, the live usage of a plan, and severity level 1.

Pure: no database and no Thanos. The PromQL runs against usage_fake.FakeMetrics, which answers it from figures."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cmapi.capacity.usage import (EXPECTED_STEPS, Figures, MetricsUnavailable, NamespaceUsage, NoUsage, PromUsage, QuotaHistory,
                                  plan_usage, sample, selector, sweep_queries, usage_queries)
from cmapi.capacity.verdicts import DEFAULTS, AnalysisSettings, Thresholds, Verdict, headline, judge
from cmapi.core.listquery import severity
from usage_fake import GiB, Fake, FakeMetrics

AT = datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc)
DEV = DEFAULTS["dev"]               # quota-oversized below 0.30, requests-oversized below 0.20, quota-tight at 0.95, idle 7 days
PROD = DEFAULTS["prod"]
QUOTAS = {"cpu": 8.0, "memory": 16 * GiB}


def usage(cpu=(2.0, 2.0, 2.0, 3.0, None), memory=(8 * GiB, 8 * GiB, 8 * GiB, 9 * GiB, None), *, coverage=1.0,
          quota=None) -> NamespaceUsage:
    """A namespace with enough data whose requests use about half of its quota: right-sized unless a test moves one figure."""
    q = quota or {"cpu": QuotaHistory(0.5, 0.0, 0.6), "memory": QuotaHistory(0.5, 0.0, 0.6)}
    return NamespaceUsage("ok", None, coverage, Figures(*cpu[:4], cpu[4] if cpu[4] is not None else cpu[2]),
                          Figures(*memory[:4], memory[4] if memory[4] is not None else memory[2]), q, AT)


def names(verdicts: list[Verdict], resource: str | None = None) -> list[str]:
    return [v.verdict for v in verdicts if resource is None or v.resource == resource]


REQUESTS = {"cpu": 4.0, "memory": 8 * GiB}


def test_a_namespace_whose_quota_requests_and_usage_agree_is_right_sized():
    v = judge("dev", DEV, usage(), REQUESTS, QUOTAS)
    assert names(v) == ["right-sized", "right-sized"]
    assert headline(v).verdict == "right-sized" and headline(v).kind == "ok"
    assert headline(v).reason == "Quota, requests and real usage agree within the dev thresholds."


@pytest.mark.parametrize("hours, peak, tight", [(0.10, 0.96, True), (0.0999, 0.96, False), (0.0, 1.0, True), (0.0, 0.9999, False)])
def test_quota_tight_fires_at_ten_percent_of_hours_or_when_the_quota_was_exhausted(hours, peak, tight):
    quota = {"cpu": QuotaHistory(0.5, hours, peak), "memory": QuotaHistory(0.5, 0.0, 0.6)}
    v = judge("dev", DEV, usage(quota=quota), REQUESTS, QUOTAS)
    assert ("quota-tight" in names(v, "cpu")) is tight
    assert names(v, "memory") == ["right-sized"]
    if tight:
        h = headline(v)
        assert (h.verdict, h.kind, h.resources) == ("quota-tight", "risk", ("cpu",))
        assert "ceiling is 95%" in h.reason


@pytest.mark.parametrize("ratio, oversized", [(0.30, False), (0.2999, True)])
def test_quota_oversized_fires_below_the_environments_floor(ratio, oversized):
    quota = {"cpu": QuotaHistory(ratio, 0.0, 0.5), "memory": QuotaHistory(0.5, 0.0, 0.6)}
    v = judge("dev", DEV, usage(quota=quota), REQUESTS, QUOTAS)
    assert ("quota-oversized" in names(v, "cpu")) is oversized
    if oversized:
        assert headline(v).verdict == "quota-oversized" and "below dev's floor of 30%" in headline(v).reason


@pytest.mark.parametrize("p95, oversized", [(0.8, False), (0.7999, True)])
def test_requests_oversized_fires_when_usage_p95_over_requests_is_below_the_floor(p95, oversized):
    # 4 cores requested; dev's floor is 0.20, so 0.8 cores at p95 is the boundary.
    v = judge("dev", DEV, usage(cpu=(0.5, 0.5, p95, 1.0, None)), REQUESTS, QUOTAS)
    assert ("requests-oversized" in names(v, "cpu")) is oversized


def test_the_floors_and_the_ceiling_are_the_environments():
    quota = {"cpu": QuotaHistory(0.45, 0.0, 0.7), "memory": QuotaHistory(0.5, 0.0, 0.6)}
    assert names(judge("dev", DEV, usage(quota=quota), REQUESTS, QUOTAS), "cpu") == ["right-sized"]
    assert names(judge("prod", PROD, usage(quota=quota), REQUESTS, QUOTAS), "cpu") == ["quota-oversized"]   # prod: below 0.50
    # The ceiling is in the sweep's query: the share of hours at or above it (dev 0.95, prod 0.85).
    assert ">= bool 0.95)[14d:1h])" in sweep_queries(7, DEV.quota_tight_at)["quota.hoursAtCeiling"]
    assert ">= bool 0.85)[14d:1h])" in sweep_queries(14, PROD.quota_tight_at)["quota.hoursAtCeiling"]
    assert "cpu.idleP95" in sweep_queries(7, 0.95) and "[7d:5m]" in sweep_queries(7, 0.95)["cpu.idleP95"]
    assert "cpu.idleP95" not in sweep_queries(14, 0.85), "prod's idle period is the window: its p95 is the window's"


@pytest.mark.parametrize("cpu_p95, mem_p95, idle", [(0.0499, 127 * 2**20, True), (0.05, 127 * 2**20, False),
                                                    (0.0499, 128 * 2**20, False)])
def test_idle_is_cpu_p95_under_005_cores_and_memory_p95_under_128_mib_over_the_idle_period(cpu_p95, mem_p95, idle):
    # The idle period's p95 decides, not the window's: rnd and dev look at 7 days.
    u = usage(cpu=(0.01, 0.01, 1.0, 2.0, cpu_p95), memory=(GiB, GiB, GiB, GiB, mem_p95))
    v = judge("dev", DEV, u, REQUESTS, QUOTAS)
    assert ("idle" in names(v)) is idle
    if idle:
        assert headline(v).verdict == "idle" and headline(v).resources == ("cpu", "memory")


@pytest.mark.parametrize("coverage, state", [(0.8, "ok"), (0.7999, "insufficient-data")])
def test_under_80_percent_of_the_windows_steps_is_insufficient_data(coverage, state):
    metrics = FakeMetrics({"payments-dev": Fake(steps=coverage * EXPECTED_STEPS)})
    u = PromUsage(metrics, clock=lambda: AT.timestamp()).namespace("CRC", "payments-dev")
    assert u.state == state
    if state != "ok":
        assert u.reason == "Pods were seen in 80% of the 14-day window's 4,032 five-minute steps; 80% are needed."
        v = judge("dev", DEV, u, REQUESTS, QUOTAS)
        assert names(v) == ["insufficient-data", "insufficient-data"]
        assert (headline(v).verdict, headline(v).kind) == ("insufficient-data", "info")


def test_no_source_is_insufficient_data_that_says_so():
    u = NoUsage().namespace("CRC", "payments-dev")
    assert (u.state, u.cpu, u.memory) == ("insufficient-data", None, None)
    assert "No usage source is configured" in u.reason
    assert NoUsage().cluster("CRC", idle_days=7, ceiling=0.95, at=AT) == {}


def test_a_namespace_with_no_sample_or_a_nan_is_insufficient_data_never_zero():
    metrics = FakeMetrics({"a": Fake(cpu=(None, None, None, None, None)), "b": Fake(steps=None)})
    p = PromUsage(metrics)
    assert p.namespace("CRC", "a").state == "insufficient-data" and "no CPU usage sample" in p.namespace("CRC", "a").reason
    assert p.namespace("CRC", "b").state == "insufficient-data"
    assert p.namespace("CRC", "nothing-here").state == "insufficient-data"
    assert sample({"value": [0, "NaN"]}) is None and sample({"value": [0, "+Inf"]}) is None and sample({"value": [0, "2"]}) == 2.0


def test_a_quota_with_no_history_in_thanos_is_insufficient_data_for_that_resource():
    u = usage(quota={"memory": QuotaHistory(0.5, 0.0, 0.6)})
    v = judge("dev", DEV, u, REQUESTS, QUOTAS)
    assert names(v, "cpu") == ["insufficient-data"] and "kube_resourcequota" in v[0].reason
    assert headline(v).verdict == "insufficient-data"


def test_a_failed_query_is_unavailable_and_is_asked_again_next_time():
    metrics = FakeMetrics({"payments-dev": Fake()})
    metrics.fail = "the Thanos Querier warned: partial data"
    p = PromUsage(metrics)
    u = p.namespace("CRC", "payments-dev")
    assert u.state == "unavailable" and "warned" in u.reason
    metrics.fail = None
    assert p.namespace("CRC", "payments-dev").state == "ok", "a failure is not cached"


def test_the_live_read_is_one_instant_one_namespace_and_cached_ten_minutes():
    metrics = FakeMetrics({"payments-dev": Fake(), "ledger-dev": Fake()})
    now = [AT.timestamp()]
    p = PromUsage(metrics, clock=lambda: now[0])
    first = p.namespace("CRC", "payments-dev")
    assert first.state == "ok" and first.cpu.p95 == 1.0 and first.coverage == 1.0
    assert len({at for _, _, at in metrics.calls}) == 1, "every query of one read is evaluated at one instant"
    assert all('namespace="payments-dev"' in q for _, q, _ in metrics.calls)
    assert all('container!="", image!=""' in q for _, q, _ in metrics.calls if "container_" in q)
    calls = len(metrics.calls)
    now[0] += 599
    assert p.namespace("CRC", "payments-dev") is first and len(metrics.calls) == calls
    now[0] += 2
    p.namespace("CRC", "payments-dev")
    assert len(metrics.calls) == 2 * calls


def test_the_queries_are_the_designs():
    q = usage_queries(selector("payments-dev"))
    assert q["cpu.p95"] == ('quantile_over_time(0.95, (sum by (namespace) (rate(container_cpu_usage_seconds_total{container!="", '
                            'image!="", namespace="payments-dev"}[5m])))[14d:5m])')
    assert q["memory.peak"] == ('max_over_time((sum by (namespace) (container_memory_working_set_bytes{container!="", image!="", '
                                'namespace="payments-dev"}))[14d:5m])')
    assert q["cpu.avg7d"].startswith("avg_over_time((") and q["cpu.avg7d"].endswith("[7d:5m])")
    assert q["coverage"] == 'count_over_time((sum by (namespace) (kube_pod_status_phase{phase="Running", namespace="payments-dev"}))[14d:5m])'


def test_the_plan_shows_the_figures_and_the_new_quota_over_the_peak():
    u = usage(cpu=(6.1, 5.4, 8.2, 9.6, None), memory=(11.8 * GiB, 10.9 * GiB, 15.9 * GiB, 17.2 * GiB, None))
    view, facts = plan_usage(u, {"requests.cpu": "16", "requests.memory": "32Gi"}, {"requests.cpu": "32", "requests.memory": "64Gi"})
    assert view["state"] == "ok" and view["units"] == {"cpu": "millicores", "memory": "bytes"}
    assert view["cpu"] == {"now": 6100, "avg7d": 5400, "p95": 8200, "peak": 9600, "quota": 16000, "newQuota": 32000, "newOverPeak": 3.33}
    assert view["memory"]["newOverPeak"] == 3.72 and view["memory"]["quota"] == 32 * GiB
    assert facts == {"usage": "ok", "requestToPeakRatio": 3.721}


def test_the_ratio_fact_counts_only_the_resources_the_change_raises():
    u = usage(cpu=(1.0, 1.0, 1.0, 2.0, None), memory=(GiB, GiB, GiB, 2 * GiB, None))
    _, facts = plan_usage(u, {"requests.cpu": "16", "requests.memory": "4Gi"}, {"requests.cpu": "8", "requests.memory": "5Gi"})
    assert facts == {"usage": "ok", "requestToPeakRatio": 2.5}, "CPU falls, so its 4x over the peak is no increase"
    _, facts = plan_usage(u, {"requests.cpu": "16"}, {"requests.cpu": "8"})
    assert facts == {"usage": "ok"}


@pytest.mark.parametrize("u", [NoUsage().namespace("CRC", "x"),
                               NamespaceUsage("unavailable", "Thanos did not answer: timeout", None)])
def test_without_usage_the_plan_says_why_and_shows_no_figure(u):
    view, facts = plan_usage(u, {"requests.cpu": "8"}, {"requests.cpu": "16"})
    assert view["state"] == u.state and view["reason"] == u.reason
    assert view["cpu"] == {"now": None, "avg7d": None, "p95": None, "peak": None, "quota": 8000, "newQuota": 16000, "newOverPeak": None}
    assert facts == {"usage": u.state}, "no requestToPeakRatio is guessed"


@pytest.mark.parametrize("used, verdict, level", [(0.5, None, 0), (0.5, "right-sized", 0), (0.5, "insufficient-data", 0),
                                                  (0.5, "idle", 1), (0.5, "quota-oversized", 1), (0.5, "requests-oversized", 1),
                                                  (0.8, "idle", 2), (0.5, "quota-tight", 3), (0.95, None, 3), (0.79, None, 0)])
def test_severity_has_the_four_levels_of_the_design(used, verdict, level):
    assert severity(used, verdict) == level


def test_headline_is_the_worst_risk_then_the_largest_waste():
    risk = Verdict("memory", "quota-tight", "risk", "tight")
    waste = Verdict("cpu", "quota-oversized", "waste", "big")
    idle = Verdict("cpu", "idle", "waste", "idle")
    assert headline([waste, risk]).verdict == "quota-tight"
    assert headline([waste, idle]).verdict == "idle"
    assert headline([Verdict("cpu", "right-sized", "ok", "ok"), Verdict("memory", "insufficient-data", "info", "x")]).verdict == "insufficient-data"


def test_analysis_yaml_overrides_a_served_environment_and_refuses_anything_else():
    s = AnalysisSettings({"environments": {"dev": {"quotaTightAt": 0.9, "idleDays": 14}}}, {"rnd", "dev"})
    assert s.of("dev") == Thresholds(0.30, 0.20, 0.9, 14) and s.of("rnd") == DEFAULTS["rnd"]
    for raw, words in [({"environments": {"prod": {"quotaTightAt": 0.9}}}, "not an environment this instance serves"),
                       ({"environments": {"dev": {"quotaTightAt": 1.5}}}, "a ratio above 0 and at most 1"),
                       ({"environments": {"dev": {"idleDays": 30}}}, "1 to 14"),
                       ({"environments": {"dev": {"other": 1}}}, "takes only"), ({"thresholds": {}}, "unknown keys")]:
        with pytest.raises(ValueError, match=words):
            AnalysisSettings(raw, {"rnd", "dev"})


def test_metrics_unavailable_is_a_runtime_error():
    assert issubclass(MetricsUnavailable, RuntimeError)
