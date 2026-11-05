import { Card, CardBody, CardTitle, Gallery, Stack, Title } from "@patternfly/react-core";
import { Callout, DataTable, Head, KV, Meter, Panel, Pill, Small } from "../components/ui";
import type { TabProps } from "../model/types";

const Rule = ({ cls, children }: { cls?: string; children: React.ReactNode }) =>
  children ? <Small>{children}</Small> : null;

export function Kpis({ v }: TabProps) {
  return (
    <Stack hasGutter>
      <Head
        title="KPIs"
        lede={<>The {v.inst.label} instance's KPI board: first whether cmapi itself has room (each component's memory, CPU, throttling and event loop, and the database), then the service KPIs from the recording rules over the last 30 days. The page and /metrics read the same collectors, so they cannot disagree.</>}
        pill={<Pill>30 days · {v.inst.label}</Pill>}
      />
      <Panel title="System status · each component's own cgroup" pill={<Pill tone={v.sys.tone}>{v.sys.pill}</Pill>}>
        <Gallery hasGutter minWidths={{ default: "280px" }}>
          {v.sys.comps.map((c: any) => (
            <Panel key={c.name} title={c.name} pill={<Pill tone={c.tone}>{c.badge}</Pill>}>
              <Small>{c.meta}</Small>
              {c.meters.map((m: any) => <Meter key={m.label} title={m.label} label={m.value} value={m.now} pct={m.pct} bar={m.bar} mark={m.mark} />)}
              <Rule cls={c.ruleCls}>{c.rule}</Rule>
            </Panel>
          ))}
        </Gallery>
        <Small>{v.sys.foot}</Small>
      </Panel>
      <Panel title="Database · PostgreSQL, schemas cmapi and capacity" pill={<Pill tone={v.db.tone}>{v.db.pill}</Pill>}>
        <Gallery hasGutter minWidths={{ default: "280px" }}>
          {v.db.meters.map((m: any) => <Meter key={m.label} title={m.label} label={m.value} value={m.now} pct={m.pct} bar={m.bar} mark={m.mark} />)}
        </Gallery>
        <KV rows={v.db.rows} />
        <Rule cls={v.db.ruleCls}>{v.db.rule}</Rule>
        <Small>Measured every 30 s by the worker that holds the discovery lock (pg_monitor role); volume fill from kubelet_volume_stats through the hub's Thanos. A value nothing reports reads unavailable, never 0.</Small>
      </Panel>
      <Gallery hasGutter minWidths={{ default: "240px" }}>
        {v.kpis.map((k: any) => (
          <Card key={k.name} isCompact>
            <CardTitle component="h3">{k.name}</CardTitle>
            <CardBody>
              <Stack className="cp-wrap">
                <div><Pill tone={k.tone}>{k.status}</Pill></div>
                <Title headingLevel="h4" size="xl">{k.value}</Title>
                <Small>Target: {k.target}</Small>
                <Small>{k.source}</Small>
              </Stack>
            </CardBody>
          </Card>
        ))}
      </Gallery>
      <Panel title="Dashboards · OpenShift console, Observe › Dashboards (Perses) · eight per instance">
        <DataTable
          label="Dashboards"
          cols={["Dashboard", "PersesDashboard", "Shows"]}
          rows={v.dashboards as any[]}
          cells={(d) => [<b>{d.name}</b>, <>cmapi/{d.id}</>, d.what]}
        />
        <Small>Shipped by the Helm chart as PersesDashboards in the cmapi namespace, reading the hub's Thanos Querier. Sites that use Grafana set dashboards.provider to grafana or both.</Small>
      </Panel>
    </Stack>
  );
}
