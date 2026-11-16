// The KPIs tab on GET /api/v1/admin/kpi (reports:read, the operator and the admin). The words are the mockup's
// (mockups/portal/Main.dc.html, isKpis, systemView() and KPIS). The API gives the figures of the process that answered,
// the database and the live KPIs of docs/17-kpis.md; MOCKUP-CONTRACT.md lists what the mockup has and the API does not.
import { Alert, AlertActionLink, Card, CardBody, CardTitle, EmptyState, EmptyStateBody, Gallery, Skeleton, Stack, Title } from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { useKpi } from "../api/hooks";
import type { KpiView } from "../api/hooks";
import { Head, KV, Meter, Panel, Pill, Small } from "../components/ui";
import { clockOf, fmt } from "./format";
import type { TabProps } from "./route";

const MIB = 2 ** 20;
const UNAVAILABLE = "unavailable";

interface MeterView { label: string; value: string; now: number; bar: string; mark: string; pct: number | null; over: boolean }

/** The mockup's meterOf(): a share of a limit against a threshold, or "unavailable" when a figure is not measured. */
function meterOf(label: string, used: number | null, limit: number | null, threshold: number, value: (pct: number) => string, scale = 1): MeterView {
  const mark = `${Math.min(100, threshold * scale)}%`;
  if (used === null || limit === null || limit <= 0) return { label, value: UNAVAILABLE, now: 0, bar: "", mark, pct: null, over: false };
  const pct = (used / limit) * 100;
  const over = pct > threshold;
  return { label, value: value(pct), now: Math.min(100, Math.round(pct * scale)), bar: over ? "warn" : "", mark, pct, over };
}

/** A figure that nothing measures: the mockup's "unavailable", never 0. */
const unmeasured = (label: string, mark: string): MeterView => ({ label, value: UNAVAILABLE, now: 0, bar: "", mark, pct: null, over: false });

/** "612 MiB" or "1.5 GiB": the mockup's sizes. */
const sizeOf = (bytes: number): string => (bytes >= 1024 * MIB ? `${fmt(bytes / (1024 * MIB))} GiB` : `${Math.round(bytes / MIB)} MiB`);

/** A KPI value in the mockup's forms: "6 min", "9.5 h", "84%", or "unavailable" for a value that is not measured. */
export function kpiValue(value: number | null, unit: string): string {
  if (value === null) return UNAVAILABLE;
  if (unit === "ratio") return `${fmt(value * 100)}%`;
  if (unit === "seconds") return value < 60 ? `${fmt(value)} s` : value < 3600 ? `${fmt(value / 60)} min` : `${fmt(value / 3600)} h`;
  return `${fmt(value)} ${unit}`;
}

function components(data: KpiView) {
  const th = data.thresholds;
  return data.components.map((c) => {
    const mem = meterOf("Memory", c.memoryBytes, c.memoryLimitBytes, th.memoryPercent, (pct) => `${Math.round(pct)}% · ${sizeOf(c.memoryBytes!)} of ${sizeOf(c.memoryLimitBytes!)}`);
    // cpu.stat gives the CPU time since the container started, not a rate: one read cannot say how busy the process is now.
    const cpu = unmeasured("CPU", `${th.cpuPercent}%`);
    // Throttling is the saturation signal. The periods count from the container's start; the bar is four times the share, as the mockup's is.
    const thr = meterOf("Throttled", c.cpuThrottledPeriods, c.cpuPeriods, th.throttledPercent, (pct) => `${pct.toFixed(1)}% of periods (limit ${th.throttledPercent}%)`, 25);
    const lag = unmeasured("Event-loop lag p99", "40%");
    const overs: string[] = [];
    if (mem.over) overs.push(`memory ${Math.round(mem.pct!)}% > ${th.memoryPercent}%`);
    if (thr.over) overs.push(`throttled ${thr.pct!.toFixed(1)}% > ${th.throttledPercent}%`);
    const cpuNote = c.cpuUsageSeconds === null ? "CPU time unavailable" : `${fmt(c.cpuUsageSeconds)} s of CPU since the container started`;
    const limit = c.cpuLimitCores === null ? "no CPU limit" : `limit ${fmt(c.cpuLimitCores)} cores`;
    return {
      name: `cmapi-${c.component}`, tone: overs.length ? "warn" : "ok", badge: overs.length ? "watch" : "healthy",
      meta: `${cpuNote} · ${limit} · measured at ${clockOf(new Date(c.measuredAt * 1000).toISOString())}`,
      meters: [mem, cpu, thr, lag], rule: overs.length ? `watch: ${overs.join(", ")}` : "within every threshold", watch: overs.length > 0
    };
  });
}

function database(data: KpiView) {
  const d = data.database, th = data.thresholds;
  const conn = meterOf("Connections", d.connections, d.connectionsMax, th.dbConnectionsPercent, () => `${d.connections} of ${d.connectionsMax} (max_connections)`);
  const vol = unmeasured("Volume", `${th.dbVolumePercent}%`);
  const overs = conn.over ? [`connections ${Math.round(conn.pct!)}% > ${th.dbConnectionsPercent}%`] : [];
  return {
    tone: overs.length ? "warn" : "info", pill: overs.length ? "watch" : "backup unavailable", meters: [conn, vol],
    rows: [
      { k: "Size", v: `${d.sizeBytes === null ? UNAVAILABLE : sizeOf(d.sizeBytes)} · WAL ${d.walBytes === null ? UNAVAILABLE : sizeOf(d.walBytes)}` },
      { k: "Pools", v: d.poolInUse === null || d.poolSize === null ? UNAVAILABLE : `${d.poolInUse} in use of ${d.poolSize}` },
      { k: "Oldest transaction", v: d.oldestTransactionSeconds === null ? UNAVAILABLE : `${fmt(d.oldestTransactionSeconds)} s` },
      { k: "Volume trend", v: UNAVAILABLE },
      { k: "Last backup", v: "unavailable: no backup tool reports for this database yet (open question), so Backup freshness shows unavailable rather than 0" }
    ],
    rule: overs.length ? `watch: ${overs.join("; ")}` : "within every threshold", watch: overs.length > 0
  };
}

const Meters = ({ meters }: { meters: MeterView[] }) => <>{meters.map((m) => <Meter key={m.label} title={m.label} label={m.value} value={m.now} bar={m.bar} mark={m.mark} />)}</>;

export function KpisTab({ config }: TabProps) {
  const kpi = useKpi();
  const instance = kpi.state === "ok" ? kpi.data.instance : config.instance;
  const head = (
    <Head
      title="KPIs"
      lede={`The ${instance} instance's KPI board: first whether cmapi itself has room (the memory, CPU and throttling of the process that answered, and the database), then the service KPIs that cmapi computes from its database. The page and /metrics read the same collectors, so they cannot disagree.`}
      pill={<Pill>{instance}</Pill>}
    />
  );
  if (kpi.state === "forbidden") {
    return (
      <Stack hasGutter>
        {head}
        <EmptyState titleText="You do not have permission to see the KPIs." headingLevel="h2" icon={LockIcon}>
          <EmptyStateBody>{kpi.detail}</EmptyStateBody>
        </EmptyState>
      </Stack>
    );
  }
  if (kpi.state === "error") {
    return (
      <Stack hasGutter>
        {head}
        <Alert variant="danger" isInline title="The KPIs did not load." actionLinks={<AlertActionLink onClick={kpi.reload}>Try again</AlertActionLink>}>{kpi.cause}</Alert>
      </Stack>
    );
  }
  if (kpi.state === "loading") return <Stack hasGutter>{head}<span role="status">Loading the KPIs…</span><Skeleton /><Skeleton /><Skeleton /></Stack>;

  const comps = components(kpi.data), db = database(kpi.data), th = kpi.data.thresholds;
  const watch = comps.filter((c) => c.watch).length + (db.watch ? 1 : 0);
  const updated = clockOf(new Date(Math.max(0, ...kpi.data.components.map((c) => c.measuredAt)) * 1000).toISOString());
  return (
    <Stack hasGutter>
      {head}
      <Panel title="System status · each component's own cgroup" pill={<Pill tone={watch ? "warn" : "ok"}>{watch ? `${watch} to watch · updated ${updated}` : `all healthy · updated ${updated}`}</Pill>}>
        <Gallery hasGutter minWidths={{ default: "280px" }}>
          {comps.map((c) => (
            <Panel key={c.name} title={c.name} pill={<Pill tone={c.tone}>{c.badge}</Pill>}>
              <Small>{c.meta}</Small>
              <Meters meters={c.meters} />
              <Small>{c.rule}</Small>
            </Panel>
          ))}
        </Gallery>
        <Small>{`Thresholds from kpi.thresholds: memory and CPU ${th.memoryPercent}% of the limit, throttling ${th.throttledPercent}% of periods (the saturation signal: a pod can be throttled while CPU still reads as headroom). The black tick on each bar is the threshold.`}</Small>
      </Panel>
      <Panel title="Database · PostgreSQL, schemas cmapi and capacity" pill={<Pill tone={db.tone}>{db.pill}</Pill>}>
        <Gallery hasGutter minWidths={{ default: "280px" }}>
          <Meters meters={db.meters} />
        </Gallery>
        <KV rows={db.rows} />
        <Small>{db.rule}</Small>
        <Small>Measured by the process that answered, when the page asked. A value nothing reports reads unavailable, never 0.</Small>
      </Panel>
      <Gallery hasGutter minWidths={{ default: "240px" }}>
        {kpi.data.kpis.map((k) => (
          <Card key={k.id} isCompact>
            <CardTitle component="h3">{k.name}</CardTitle>
            <CardBody>
              <Stack className="cp-wrap">
                <div><Pill tone="info">{`target ${k.targetStatus}`}</Pill></div>
                <Title headingLevel="h4" size="xl">{kpiValue(k.value, k.unit)}</Title>
                <Small>{`Target: ${k.target}`}</Small>
                <Small>{k.source}</Small>
              </Stack>
            </CardBody>
          </Card>
        ))}
      </Gallery>
      <Small>{kpi.data.unavailable}</Small>
    </Stack>
  );
}
