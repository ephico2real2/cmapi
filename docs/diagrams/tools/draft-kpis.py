#!/usr/bin/env python3
"""Draft generator for the KPI figure. The committed source.html is the source."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import importlib.util
spec = importlib.util.spec_from_file_location("gen", Path(__file__).parent / "gen.py")
TARGET = Path(sys.argv[1])
sys.argv = [sys.argv[0], "/tmp/claude-501/diagen-unused"]
gen = importlib.util.module_from_spec(spec); spec.loader.exec_module(gen)
box, arrow, page, e = gen.box, gen.arrow, gen.page, gen.e

def listbox(x, y, w, title, items, dashed=False, note=None):
    h = 30 + 17 * len(items) + (22 if note else 8)
    d = ' stroke-dasharray="5 4"' if dashed else ""
    o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="var(--surface)" stroke="currentColor" stroke-width="1.2"{d}/>',
         f'<text x="{x+14}" y="{y+21}" font-weight="600">{e(title)}</text>']
    for i, it in enumerate(items):
        o.append(f'<text x="{x+14}" y="{y+41+i*17}" font-family="IBM Plex Mono, monospace" font-size="11.5">{e(it)}</text>')
    if note:
        o.append(f'<text x="{x+14}" y="{y+h-10}" font-size="11.5" fill="var(--muted)">{e(note)}</text>')
    return "\n".join(o), h

mid, b = "ahk", []
b.append('<g font-family="IBM Plex Mono, monospace" font-size="13" font-weight="600">'
         '<rect x="20" y="14" width="290" height="30" rx="6" fill="var(--none-wash)" stroke="var(--none)"/><text x="165" y="34" text-anchor="middle" fill="var(--none)">SOURCE</text>'
         '<rect x="380" y="14" width="340" height="30" rx="6" fill="var(--remote-wash)" stroke="var(--remote)"/><text x="550" y="34" text-anchor="middle" fill="var(--remote)">KPI  ·  docs/17</text>'
         '<rect x="790" y="14" width="290" height="30" rx="6" fill="var(--host-wash)" stroke="var(--host)"/><text x="935" y="34" text-anchor="middle" fill="var(--host)">WHERE IT IS SHOWN</text></g>')
live = ["lead-time-auto-p90", "lead-time-approved-p90", "approval-turnaround-p50", "approval-turnaround-p90", "auto-approval-rate", "self-service-rate", "change-failure-rate"]
built = ["api-availability", "system-headroom", "cpu-saturation", "managed-coverage"]
designed = ["drift-events", "expired-namespaces-cleaned", "import-health", "placement-accuracy",
            "capacity-freshness", "cluster-headroom", "quota-efficiency", "capacity-recovered", "database-headroom", "backup-freshness"]
y1 = 70
s, h1 = listbox(380, y1, 340, "Live: the API computes it", live, note="formulas tested in the service suite"); b.append(s)
y2 = y1 + h1 + 26
s, h2 = listbox(380, y2, 340, "Built: the code feeds the metric", built, dashed=True, note="the KPI query is not proven on a cluster"); b.append(s)
y3 = y2 + h2 + 26
s, h3 = listbox(380, y3, 340, "Designed: no code feeds the source", designed, dashed=True); b.append(s)
# sources
b.append(box(20, y1 + 20, 290, 76, "PostgreSQL", ["change_requests and approvals", "read at each call of the API"]))
b.append(arrow([(310, y1 + 58), (376, y1 + 58)], mid))
b.append(box(20, y2 + 6, 290, 76, "cmapi_ metrics on /metrics", ["HTTP requests, cgroup figures, namespaces", "fed by the api and the worker"]))
b.append(arrow([(310, y2 + 44), (376, y2 + 44)], mid))
b.append(box(20, y3 + 40, 290, 76, "Not built", ["cmapi-capacity, the usage analysis,", "expire_check, backup and volume figures"], dashed=True))
b.append(arrow([(310, y3 + 78), (376, y3 + 78)], mid, "proposed", 318, y3 + 71, stroke="var(--muted)", dashed=True))
# shown
b.append(box(790, y1, 290, 76, "GET /api/v1/admin/kpi", ["kpis, components, database, thresholds", "permission reports:read"]))
b.append(arrow([(720, y1 + 38), (786, y1 + 38)], mid))
b.append(box(790, y1 + 104, 290, 58, "The portal's KPIs tab", ["on sample data: it does not call the API yet"], dashed=True))
b.append(arrow([(935, y1 + 76), (935, y1 + 100)], mid, "proposed", 943, y1 + 93, stroke="var(--muted)", dashed=True))
b.append(box(790, y2, 290, 76, "Prometheus, user workload monitoring", ["ServiceMonitors are in the manifests", "no scrape proven: nothing is deployed"], dashed=True))
b.append(arrow([(720, y2 + 38), (786, y2 + 38)], mid, "proposed", 728, y2 + 31, stroke="var(--muted)", dashed=True))
b.append(box(790, y2 + 104, 290, 76, "Alerts and dashboards", ["12 alert rules are in the manifests", "none has fired; dashboards are not built"], dashed=True))
b.append(arrow([(935, y2 + 76), (935, y2 + 100)], mid, "proposed", 943, y2 + 93, stroke="var(--muted)", dashed=True))
fy = y3 + h3 + 36
b.append(f'<text x="20" y="{fy}">Solid box = built code with tests. Dashed box = not built, or not proven on a cluster. Dashed arrow = proposed.</text>')
b.append(f'<text x="20" y="{fy+19}">The API also serves the figures of its own process (cgroup) and of the database. They are figures, not KPIs.</text>')
b.append(f'<text x="20" y="{fy+38}" fill="var(--host)" font-weight="600">21 KPIs on 2026-11-13: 7 live, 4 built, 10 designed. No KPI value is measured on a cluster yet.</text>')
aria = ("Seven KPIs are live: the API computes them from the database. Four are built: the code feeds their metrics, and a dashboard query is not proven. "
        "Ten are designed. The API serves the live KPIs and the system figures; Prometheus, the dashboards and the alerts are not proven on a cluster.")
cap = ("Each KPI has one row in docs/17 with its formula and target. The live KPIs come from the request table, so the API can answer without Prometheus. "
       "The built KPIs need a Prometheus query, which waits for the first deployment.")
out = TARGET
out.mkdir(parents=True, exist_ok=True)
(out / "source.html").write_text(page("KPI Sources", "cmapi · KPIs · 2026-11-13", "Each KPI, its source and where it is shown",
    "docs/17-kpis.md defines 21 KPIs. This figure groups them by what the code does today.",
    "Read from <code>cmapi/src/cmapi/core/kpi.py</code>, <code>core/observability.py</code> and the manifests, at the commit that added docs/17.",
    [("The KPIs by status", (1100, fy + 54), aria, "\n".join(b), cap, mid)]))
