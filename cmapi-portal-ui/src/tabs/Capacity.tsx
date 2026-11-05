import { DescriptionList, DescriptionListDescription, DescriptionListGroup, DescriptionListTerm, Gallery, Stack } from "@patternfly/react-core";
import { DataTable, Head, Meter, Panel, Pill, Small } from "../components/ui";
import type { TabProps } from "../model/types";

function Stat({ term, value, note }: { term: string; value: React.ReactNode; note: React.ReactNode }) {
  return (
    <DescriptionListGroup>
      <DescriptionListTerm>{term}</DescriptionListTerm>
      <DescriptionListDescription><b>{value}</b><div><Small>{note}</Small></div></DescriptionListDescription>
    </DescriptionListGroup>
  );
}

export function Capacity({ v }: TabProps) {
  return (
    <Stack hasGutter>
      <Head
        title="Capacity"
        lede="Cluster capacity from the latest complete snapshots, grouped by clusters.yaml metadata. CPU and memory are measured, committed and checked separately; a cluster is as full as its fuller resource. Headroom never crosses cluster boundaries, so the largest single placement is shown beside the total."
        pill={<Pill>snapshot 17:00 · every 30 min</Pill>}
      />
      <Gallery hasGutter minWidths={{ default: "320px" }}>
        {v.groups.map((g: any) => (
          <Panel key={g.name} title={g.name} pill={<Pill tone={g.tone}>{g.status}</Pill>}>
            <Small>{g.meta}</Small>
            <DescriptionList columnModifier={{ default: "2Col" }} isCompact>
              <Stat term="CPU commitment" value={g.cpuCommit} note={<>quota headroom {g.cpuHead}</>} />
              <Stat term="Memory commitment" value={g.memCommit} note={<>quota headroom {g.memHead}</>} />
              <Stat term="Largest placement" value={g.largest} note={g.largestOn} />
              <Stat term="Bound by" value={g.bound} note={g.boundWhy} />
            </DescriptionList>
            <Small>{g.note}</Small>
          </Panel>
        ))}
      </Gallery>
      <Panel title="Clusters">
        <DataTable
          label="Clusters"
          cols={["Cluster", "Env", "Zones", "CPU commitment", "Memory commitment", "Quota headroom", "Bound by", "Snapshot", "Status"]}
          rows={v.clusters as any[]}
          cells={(c) => [
            c.id, c.env, c.zones,
            <Meter ariaLabel={`${c.id} CPU commitment`} pct={c.cpuPct} bar={c.cpuBar} label={c.cpuCommit} />,
            <Meter ariaLabel={`${c.id} memory commitment`} pct={c.memPct} bar={c.memBar} label={c.memCommit} />,
            c.head, c.bound, c.snap, <Pill tone={c.tone}>{c.status}</Pill>
          ]}
        />
        <Small>{v.capFoot}</Small>
      </Panel>
    </Stack>
  );
}
