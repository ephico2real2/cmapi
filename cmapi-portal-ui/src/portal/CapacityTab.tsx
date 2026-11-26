// The Capacity tab on GET /api/v1/capacity (#302). The words and the sections are the mockup's (mockups/portal/Main.dc.html,
// isCapacity and its CAPACITY data): the group cards, then the Clusters table. MOCKUP-CONTRACT.md lists what differs, and why.
// Every figure is the API's: the page sums nothing, and a figure the API gives as null shows "—", never 0 and never a bar.
// Each cluster's stored snapshot (#21), which placement reads, is its Snapshot column; the head says the newest one.
import {
  Alert, AlertActionLink, DescriptionList, DescriptionListDescription, DescriptionListGroup, DescriptionListTerm, EmptyState, EmptyStateBody,
  Gallery, Skeleton, Stack
} from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import type { ReactNode } from "react";
import { useCapacity } from "../api/hooks";
import type { CapacityCluster, CapacityGroup, CapacityPage, CapacityResource } from "../api/hooks";
import { DataTable, Empty, Head, Meter, Panel, Pill, Small } from "../components/ui";
import type { TabProps } from "./route";

type Resource = "cpu" | "memory";
type Status = NonNullable<CapacityCluster["status"]>;

const GI = 2 ** 30;
/** The mockup's tones: ok, warn, and critical as bad. Over 100 % is critical's tone with its own word. */
const TONE: Record<Status, string> = { ok: "ok", warn: "warn", critical: "bad", over: "bad" };
/** The meter's bar: the mockup's BARCLS, warn and crit. */
const BAR: Record<Status, string | undefined> = { ok: undefined, warn: "warn", critical: "crit", over: "crit" };

const clock = (iso: string): string => new Date(iso).toISOString().slice(11, 16);
/** One decimal at most, and none when whole: "56", "7.8", "19.1". */
const tenths = (x: number): string => String(Math.round(x * 10) / 10);
const cores = (millicores: number): string => {
  const n = tenths(millicores / 1000);
  return `${n} ${n === "1" ? "core" : "cores"}`;
};
const gi = (bytes: number): string => `${tenths(bytes / GI)} Gi`;
/** CPU in cores and memory in Gi (binary), never G or GB. */
const amount = (r: Resource, value: number): string => (r === "cpu" ? cores(value) : gi(value));
const pct = (ratio: number): string => `${Math.round(ratio * 100)}%`;
/** Quota headroom: "56 cores", "over by 56.4 cores" below zero, "—" when not known. */
const headroomOf = (r: Resource, value: number | null): string => (value === null ? "—" : value < 0 ? `over by ${amount(r, -value)}` : amount(r, value));
/** The mockup's number form for an overcommit or a target: 2 is "2.0", 1.25 is "1.25". */
const ratioWord = (x: number): string => x.toFixed(2).replace(/0$/, "");
const boundWord = (b: CapacityCluster["boundBy"]): string => (b === null ? "—" : b === "both" ? "cpu and memory" : b);

/** A cluster's status pill: the commitment's status with what binds, or the state that leaves it unknown. */
function statusOf(c: CapacityCluster): [string, string] {
  switch (c.state) {
    case "loading": return ["loading", "info"];
    case "not-imported": return ["not imported", "info"];
    case "unreachable": return [`unreachable${c.asOf ? ` since ${clock(c.asOf)}` : ""}`, "bad"];
    case "forbidden": return ["no access to the quotas", "bad"];
    case "no-size": return ["no size", "info"];
    case "stale": return [`stale since ${c.asOf ? clock(c.asOf) : "—"}`, "bad"];
    default:
      if (c.status === null) return ["—", ""];
      return [c.status === "ok" ? "ok" : `${c.status} · ${c.boundBy ?? "—"}`, TONE[c.status]];
  }
}

/** The Snapshot cell: the newest complete snapshot's minute, or why placement cannot use it. */
function snapshotOf(c: CapacityCluster): ReactNode {
  const s = c.snapshot;
  if (s.state === "none") return <Pill tone="info">none yet</Pill>;
  const at = s.takenAt ? clock(s.takenAt) : "—";
  if (s.state === "ok") return at;
  return <Pill tone="warn">{s.state === "stale" ? `stale ${at}` : "incomplete"}</Pill>;
}

/** The head's pill: the newest snapshot of any cluster and the interval, as the mockup's "snapshot 17:00 · every 30 min". */
function snapshotPill(page: CapacityPage): string {
  const every = `every ${Math.round(page.snapshotIntervalSeconds / 60)} min`;
  const times = page.clusters.map((c) => c.snapshot.takenAt).filter((t): t is string => t !== null).sort();
  return times.length ? `snapshot ${clock(times[times.length - 1])} · ${every}` : `no snapshot yet · ${every}`;
}

/** Why a cluster is left out of its group's figures, in the meta line's words. */
function leftOut(e: CapacityGroup["excluded"][number]): string {
  if (e.reason === "not-writable") return `${e.clusterId} placement off`;
  const word = e.reason === "stale" ? `stale since ${e.asOf ? clock(e.asOf) : "—"}` : e.reason === "forbidden" ? "no access to the quotas"
    : e.reason === "no-size" ? "no size" : e.reason === "not-imported" ? "not imported" : e.reason;
  return `${e.clusterId} left out: ${word}`;
}

/** The size beside each meter: the basis first, then the other when both are known ("simulated 64 cores · nodes 7.8 cores"). */
function sizeOf(r: Resource, f: CapacityResource, basis: CapacityCluster["basis"]): string {
  const simulated = f.simulated === null ? null : `simulated ${amount(r, f.simulated)}`;
  const nodes = f.allocatable === null ? null : `nodes ${amount(r, f.allocatable)}`;
  return (basis === "allocatable" ? [nodes, simulated] : [simulated, nodes]).filter(Boolean).join(" · ");
}

/** A commitment meter. Unknown draws no bar and says "—"; over 100 % fills the bar and says the real figure. */
function Commitment({ label, f, size }: { label: string; f: CapacityResource; size: string }) {
  return (
    <Stack>
      {f.commitment === null
        ? <span>—</span>
        : <Meter ariaLabel={label} value={Math.min(100, Math.round(f.commitment * 100))} label={pct(f.commitment)} bar={f.status ? BAR[f.status] : undefined} />}
      {size && <Small>{size}</Small>}
    </Stack>
  );
}

function Stat({ term, value, note }: { term: string; value: ReactNode; note: ReactNode }) {
  return (
    <DescriptionListGroup>
      <DescriptionListTerm>{term}</DescriptionListTerm>
      <DescriptionListDescription><b>{value}</b><div><Small>{note}</Small></div></DescriptionListDescription>
    </DescriptionListGroup>
  );
}

/** "warn · 2 of 3": the worst status of the included clusters, and how many have it. */
function groupStatus(g: CapacityGroup): [string, string] {
  if (g.status === null) return ["—", ""];
  return [g.status === "ok" ? "ok" : `${g.status} · ${g.statusCounts[g.status]} of ${g.included}`, TONE[g.status]];
}

/** "1 of 1 cluster · coverage 1.0 · OCP_GF7 left out: stale since 15:30". */
function metaOf(g: CapacityGroup): string {
  const coverage = g.coverage === null ? "—" : Number.isInteger(g.coverage * 10) ? g.coverage.toFixed(1) : g.coverage.toFixed(2);
  return [`${g.included} of ${g.matching} ${g.matching === 1 ? "cluster" : "clusters"}`, `coverage ${coverage}`, ...g.excluded.map(leftOut)].join(" · ");
}

function largestOf(g: CapacityGroup): [string, string] {
  if (!g.cpu || !g.memory) return ["—", ""];
  const c = g.cpu.largestPlacement, m = g.memory.largestPlacement;
  return [`${cores(c.value)} · ${gi(m.value)}`, c.clusterId === m.clusterId ? `on ${c.clusterId}` : `cpu on ${c.clusterId} · memory on ${m.clusterId}`];
}

function boundWhyOf(g: CapacityGroup): string {
  if (!g.cpu || !g.memory || g.cpu.commitment === null || g.memory.commitment === null) return "";
  const cpu = `cpu ${pct(g.cpu.commitment)}`, memory = `memory ${pct(g.memory.commitment)}`;
  return `${g.boundBy === "memory" ? `${memory} vs ${cpu}` : `${cpu} vs ${memory}`} committed`;
}

/** The note of a group: each environment's overcommit, and which clusters are sized by clusters.yaml rather than measured. */
function noteOf(g: CapacityGroup, members: CapacityCluster[], page: CapacityPage): string {
  const envs = [...new Set(members.map((c) => c.env))].sort();
  const over = envs.map((env) => page.targets.find((t) => t.env === env)).filter((t) => t !== undefined)
    .map((t) => `${t.env} overcommit: CPU ${ratioWord(t.overcommit.cpu)}, memory ${ratioWord(t.overcommit.memory)}.`);
  const simulated = members.filter((c) => c.basis === "simulated").map((c) => c.clusterId);
  const sized = simulated.length ? [`Sized by simulatedCapacity in clusters.yaml (${simulated.join(", ")}): a configured size, not a measurement.`] : [];
  return [...over, ...sized].join(" ");
}

/** The mockup's capFoot, from the API's targets instead of its constants. */
function footOf(page: CapacityPage): string {
  return `${page.targets.map((t) => `${t.env}: overcommit cpu ${ratioWord(t.overcommit.cpu)}, memory ${ratioWord(t.overcommit.memory)}${t.overcommitDefault ? " (not in capacity.yaml)" : ""}; commitment warns at ${Math.round(t.commitment.warn * 100)}%, critical at ${Math.round(t.commitment.critical * 100)}%`).join(" · ")}. Each resource is judged on its own; a cluster takes the worse status. Memory cannot be throttled, so its overcommit stays tighter.`;
}

/** The lines under the table: why a cluster's figures are not all there, and what is not measured at all. */
function detailsOf(c: CapacityCluster): string[] {
  const out: string[] = [];
  if (c.stateDetail) out.push(`${c.clusterId}: ${c.stateDetail}.`);
  // A cluster that is not connected has one detail, the same for its nodes and its quotas: said once.
  if (c.nodesDetail && c.state !== "unreachable" && c.state !== "not-imported") out.push(`${c.clusterId} nodes: ${c.nodesDetail}.`);
  if (!c.writes) out.push(`${c.clusterId}: writes are off in clusters.yaml, so it takes no placement and is left out of its group.`);
  if (c.snapshot.state !== "ok" && c.snapshot.detail) out.push(`${c.clusterId} snapshot: ${c.snapshot.detail}; placement leaves it out.`);
  return out;
}

export function CapacityTab({ config }: TabProps) {
  const result = useCapacity();
  const head = (
    <Head
      title="Capacity"
      lede="Cluster capacity from each cluster's watch of its quotas and nodes and its latest complete snapshot, grouped by clusters.yaml metadata. CPU and memory are committed and checked separately; a cluster is as full as its fuller resource. Headroom never crosses cluster boundaries, so the largest single placement is shown beside the total."
      pill={result.state === "ok" ? <Pill tone="info">{snapshotPill(result.data)}</Pill> : undefined}
    />
  );
  if (result.state === "loading") {
    return <Stack hasGutter>{head}<span role="status">Loading capacity…</span><Skeleton /><Skeleton /><Skeleton /></Stack>;
  }
  if (result.state === "forbidden") {
    return (
      <Stack hasGutter>
        {head}
        <EmptyState titleText="You do not have permission to see capacity." headingLevel="h2" icon={LockIcon}>
          <EmptyStateBody>{result.detail}</EmptyStateBody>
        </EmptyState>
      </Stack>
    );
  }
  if (result.state === "error") {
    return (
      <Stack hasGutter>
        {head}
        <Alert variant="danger" isInline title="Capacity did not load." actionLinks={<AlertActionLink onClick={result.reload}>Try again</AlertActionLink>}>{result.cause}</Alert>
      </Stack>
    );
  }

  const page = result.data;
  const membersOf = (g: CapacityGroup) => page.clusters.filter((c) => g.clusterIds.includes(c.clusterId));
  return (
    <Stack hasGutter>
      {head}
      {page.groups.length > 0 && (
        <Gallery hasGutter minWidths={{ default: "300px" }}>
          {page.groups.map((g) => {
            const [status, tone] = groupStatus(g), [largest, largestOn] = largestOf(g);
            return (
              <Panel key={g.name} title={g.name} pill={<Pill tone={tone}>{status}</Pill>}>
                <Small>{metaOf(g)}</Small>
                <DescriptionList columnModifier={{ default: "2Col" }} isCompact>
                  <Stat term="CPU commitment" value={g.cpu?.commitment == null ? "—" : pct(g.cpu.commitment)} note={`quota headroom ${g.cpu ? cores(g.cpu.headroom) : "—"}`} />
                  <Stat term="Memory commitment" value={g.memory?.commitment == null ? "—" : pct(g.memory.commitment)} note={`quota headroom ${g.memory ? gi(g.memory.headroom) : "—"}`} />
                  <Stat term="Largest placement" value={largest} note={largestOn} />
                  <Stat term="Bound by" value={boundWord(g.boundBy)} note={boundWhyOf(g)} />
                </DescriptionList>
                <Small>{noteOf(g, membersOf(g), page)}</Small>
              </Panel>
            );
          })}
        </Gallery>
      )}
      <Panel title="Clusters">
        <DataTable
          label="Clusters"
          cols={["Cluster", "Env", "Zones", "CPU commitment", "Memory commitment", "Quota headroom", "Bound by", "Snapshot", "Status"]}
          rows={page.clusters}
          cells={(c) => {
            const [word, tone] = statusOf(c);
            const room = c.cpu.headroom === null && c.memory.headroom === null ? "—" : `${headroomOf("cpu", c.cpu.headroom)} · ${headroomOf("memory", c.memory.headroom)}`;
            return [c.clusterId, c.env, c.zones?.length ? c.zones.join(" · ") : "—",
              <Commitment label={`${c.clusterId} CPU commitment`} f={c.cpu} size={sizeOf("cpu", c.cpu, c.basis)} />,
              <Commitment label={`${c.clusterId} memory commitment`} f={c.memory} size={sizeOf("memory", c.memory, c.basis)} />,
              room, boundWord(c.boundBy), snapshotOf(c), <Pill tone={tone}>{word}</Pill>];
          }}
        />
        {page.clusters.length === 0 && <Empty>No cluster of your environments is known to this instance.</Empty>}
        <Stack>{page.clusters.flatMap(detailsOf).map((line) => <Small key={line}>{line}</Small>)}</Stack>
        {page.hiddenClusters > 0 && <Small>{`${page.hiddenClusters} ${page.hiddenClusters === 1 ? "cluster" : "clusters"} of environments where your roles do not read capacity ${page.hiddenClusters === 1 ? "is" : "are"} not shown.`}</Small>}
        <Small>{footOf(page)}</Small>
        <Small>{`Committed is the hard requests of the ResourceQuotas that cmapi manages on the ${config.instance} instance, per namespace its smallest unscoped one, against the size × overcommit, live from each cluster's watch. Pods of other namespaces are not subtracted. The worker stores a snapshot of each cluster every ${Math.round(page.snapshotIntervalSeconds / 60)} minutes; placement leaves out a cluster whose newest complete one is over ${Math.round(page.staleAfterSeconds / 60)} minutes old. Not measured: ${page.notMeasured.join(", ")}.`}</Small>
      </Panel>
    </Stack>
  );
}
