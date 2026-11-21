// The Quotas tab on GET /api/v1/quotas, :suggest and :export, with the quota change as a namespace PATCH: its dry run
// first, then the change that was planned, with If-Match and an Idempotency-Key. The words are the mockup's
// (mockups/portal/Main.dc.html, isQuotas and quotaView()). MOCKUP-CONTRACT.md lists what differs, and why.
import {
  ActionGroup, Alert, AlertActionLink, Button, EmptyState, EmptyStateBody, Flex, Form, FormGroup, Grid, GridItem, Label, Menu, MenuContent, MenuItem,
  MenuList, Modal, ModalBody, ModalFooter, ModalHeader, Skeleton, Stack, TextArea, TextInput, TextInputGroup, TextInputGroupMain
} from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { SUGGEST_MIN, useCatalog, useClusters, useExport, useMe, useNamespace, usePatchPlan, useQuotas, useSubmitPatch, useSuggest } from "../api/hooks";
import type { ChangeRequest, ExportQuery, NamespacePatch, NamespaceView, Outcome, Plan, PlannedChange, QuotaRow, QuotasQuery, TierCatalog } from "../api/hooks";
import { PERMISSION } from "../api/permissions.generated";
import { Callout, Checks, Choices, Code, ComboBox, DataTable, Empty, Filter, Head, Hint, Meter, Pager, Panel, Pill, Small } from "../components/ui";
import type { Check, Choice } from "../components/ui";
import { grantsIn, operatorIn, PROTECT_KEY, PROTECT_VALUE } from "./access";
import { barOf, countsOf, fmt, GIB, isoDay, policyOf, quantityOf } from "./format";
import { capacityCheck, capacityLine, MARK, sentence } from "./plan";
import type { TabProps } from "./route";

const SORTS = [["name", "Name A–Z", "A–Z"], ["used", "% used", "most used first"], ["severity", "Needs attention", "most urgent first"]] as const;
type Sort = (typeof SORTS)[number][0];
const LIMITS = [25, 50, 100] as const;
const DEFAULT_LIMIT = 50;
/** The attention counts of the API (`facets` of QuotaPage, `state` of GET /api/v1/quotas), with the mockup's words where it has them. */
const ATTENTION = [["near-limit", "Near limit ≥ 80%", "warn"], ["open-request", "Open request", ""], ["tier-outdated", "Tier outdated", "warn"]] as const;
type State = (typeof ATTENTION)[number][0];
const LETTERS = "abcdefghijklmnopqrstuvwxyz".split("");
const SEARCH_DELAY_MS = 300;
const CUSTOM = "custom";
/** The answers that say the etag of a change is not the folder's now (docs/04, If-Match): read the namespace again. */
const PRECONDITION = new Set(["precondition-failed", "precondition-required"]);
const outdated = (o: Outcome<unknown>): boolean => o.state === "refused" && PRECONDITION.has(o.code);
const PATCH_NAMESPACE = PERMISSION["PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}"];

const keyOf = (r: Pick<QuotaRow, "clusterId" | "name">): string => `${r.clusterId}/${r.name}`;
const pick = <T extends string>(value: string | null, allowed: readonly T[], fallback: T): T => (allowed.includes(value as T) ? (value as T) : fallback);

/** The three resources of a row, each as numbers in the mockup's units: cores, Gi and pods. */
function sizesOf(r: QuotaRow) {
  const cores = (q: string | null | undefined) => quantityOf(q);
  const gi = (q: string | null | undefined) => { const n = quantityOf(q); return n === null ? null : n / GIB; };
  return {
    cpu: [cores(r.cpu[0]), cores(r.cpu[1])] as const,
    memory: [gi(r.memory[0]), gi(r.memory[1])] as const,
    pods: [quantityOf(r.pods[0]), quantityOf(r.pods[1])] as const
  };
}

/** "7.4 / 8 cores", or "—" where the namespace has no hard limit for it. */
const usedText = (pair: readonly [number | null, number | null], unit: string): string =>
  (pair[1] === null ? "—" : `${pair[0] === null ? "—" : fmt(pair[0])} / ${fmt(pair[1])}${unit}`);

interface Tier { name: string; custom: boolean; cpu: number | null; memory: number | null; pods: number | null; cpuText: string; memoryText: string }

/** The tiers of one environment of the catalog. The contract types `environments` as open objects, so each field is checked. */
function tiersOf(catalog: TierCatalog | null, env: string | null): Tier[] {
  const entry = (env ? catalog?.environments[env] : undefined) as { tiers?: unknown } | undefined;
  const list = Array.isArray(entry?.tiers) ? entry.tiers : [];
  return list.flatMap((raw) => {
    const t = raw as { name?: unknown; custom?: unknown; order?: unknown; quota?: Record<string, unknown> };
    if (typeof t.name !== "string") return [];
    const q = t.quota ?? {};
    const text = (k: string) => (typeof q[k] === "string" ? (q[k] as string) : "—");
    const memory = quantityOf(text("requests.memory"));
    return [{ order: typeof t.order === "number" ? t.order : 0, tier: { name: t.name, custom: t.custom === true, cpu: quantityOf(text("requests.cpu")),
      memory: memory === null ? null : memory / GIB, pods: quantityOf(text("pods")), cpuText: text("requests.cpu"), memoryText: text("requests.memory") } }];
  }).sort((a, b) => a.order - b.order).map(({ tier }) => tier);
}

/** Each tier name of the catalog, in its order, over every environment that the instance serves: the Tier filter. */
function tierNames(catalog: TierCatalog | null): string[] {
  const names: string[] = [];
  for (const env of Object.keys(catalog?.environments ?? {})) for (const t of tiersOf(catalog, env)) if (!names.includes(t.name)) names.push(t.name);
  return names;
}

/** The custom tier's bounds for requests.cpu (cores) and requests.memory (Gi), from the catalog's `custom` of the environment. */
function boundsOf(catalog: TierCatalog | null, env: string | null) {
  const custom = ((env ? catalog?.environments[env] : undefined) as { custom?: Record<string, Record<string, unknown>> } | undefined)?.custom;
  const read = (part: string, key: string, scale = 1) => {
    const n = quantityOf(typeof custom?.[part]?.[key] === "string" ? (custom[part][key] as string) : null);
    return n === null ? undefined : String(n / scale);
  };
  return {
    cpu: { min: read("min", "requests.cpu"), max: read("max", "requests.cpu"), step: read("step", "requests.cpu") },
    memory: { min: read("min", "requests.memory", GIB), max: read("max", "requests.memory", GIB), step: read("step", "requests.memory", GIB) }
  };
}

export function QuotasTab({ config, params, setParams, open }: TabProps) {
  const me = useMe();
  const catalog = useCatalog();
  const clusters = useClusters();
  // The view of the address: the applied search, the filters, the sort, the page size and the namespace shown below.
  const applied = params.get("q") ?? "";
  const env = pick(params.get("env"), config.environments, "");
  const cluster = params.get("cluster") ?? "";
  const tier = params.get("tier") ?? "";
  const state = pick<State | "">(params.get("state"), ATTENTION.map(([id]) => id), "");
  const sort = pick<Sort>(params.get("sort"), SORTS.map(([id]) => id), "name");
  const limit = Number(pick(params.get("limit"), LIMITS.map(String), String(DEFAULT_LIMIT)));
  const chosen = params.get("ns") ?? "";
  // A cursor and a letter jump belong to one set of filters, so they live here and not in the address.
  const [cursor, setCursor] = useState<string | null>(null);
  // A shared address that names a namespace opens on the page that starts with it, where the API can place one: by name.
  const [startsWith, setStartsWith] = useState<string | null>(() => (chosen.includes("/") && sort === "name" ? chosen.slice(chosen.indexOf("/") + 1) : null));
  const [exporting, setExporting] = useState(false);
  const exported = useExport();
  // The namespace shown below the list, kept while the person pages away from it (the mockup shows it from every row).
  const lastShown = useRef<QuotaRow | null>(null);

  const view = { q: applied, env, cluster, tier, state, sort, limit: String(limit), ns: chosen };
  const apply = (next: Partial<typeof view>, at: string | null = null) => {
    setCursor(null);
    setStartsWith(at);
    setExporting(false);
    const merged = { ...view, ...next };
    setParams({ ...merged, sort: merged.sort === "name" ? "" : merged.sort, limit: merged.limit === String(DEFAULT_LIMIT) ? "" : merged.limit });
  };

  // The filters of the API, without the state chip: the "All" count, and the export's and the list's common part.
  const filters: QuotasQuery = {};
  if (applied) filters.q = applied;
  if (env) filters.env = env;
  if (cluster) filters.clusterId = cluster;
  if (tier) filters.tier = tier;
  const query: QuotasQuery = { ...filters };
  if (state) query.state = state;
  if (sort !== "name") query.sort = sort;
  query.limit = limit;
  if (cursor) query.cursor = cursor;
  else if (startsWith && sort === "name") query.startsWith = startsWith;
  const result = useQuotas(query);
  // Every namespace in scope, with no filter (the heading), and the rows of the filters without the state chip (All).
  const scope = useQuotas({ limit: DEFAULT_LIMIT });
  const unstated = useQuotas({ ...filters, limit: DEFAULT_LIMIT });
  const inScope = scope.state === "ok" ? scope.data.page.total : null;

  const head = (
    <Head
      title="Quotas"
      lede={`The ResourceQuota of every namespace in the environments your roles cover on the ${config.instance} instance, read live from cmapi's watch cache of each cluster. Used is what pods have requested, not what they consume.`}
      pill={scope.state === "ok" ? <Pill>{`${inScope} namespaces in scope · ${scope.data.facets["near-limit"] ?? 0} near the limit`}</Pill> : undefined}
    />
  );
  if (result.state === "forbidden") {
    return (
      <Stack hasGutter>
        {head}
        <EmptyState titleText="You do not have permission to see quotas." headingLevel="h2" icon={LockIcon}>
          <EmptyStateBody>{result.detail}</EmptyStateBody>
        </EmptyState>
      </Stack>
    );
  }

  const page = result.state === "ok" ? result.data : null;
  // The sort of the rows on screen: while the next sort loads they are still the last answer's (#392).
  const shownSort = pick<Sort>(page?.asked.sort ?? null, SORTS.map(([id]) => id), "name");
  // The rows on screen are the last answer's while the next one loads: their cursors belong to that answer's query, not to the
  // sort or filters just asked for, so the pager does not page from them (the API would refuse it, 400 invalid-cursor).
  const busy = result.state === "ok" && result.refreshing;
  const facets = page?.facets ?? {};
  const attention: Choice[] = [
    { label: "All", n: state ? (unstated.state === "ok" ? String(unstated.data.page.total) : "…") : page ? String(page.page.total) : "…", on: !state, pick: () => apply({ state: "" }) },
    ...ATTENTION.map(([id, label]) => ({ label, n: String(facets[id] ?? 0), on: state === id, pick: () => apply({ state: state === id ? "" : id }) }))
  ];
  const chip = (current: string, value: string, label: string, key: keyof typeof view): Choice => ({ label, on: current === value, pick: () => apply({ [key]: value }) });
  const clusterIds = clusters.state === "ok" ? clusters.data.items.map((c) => c.clusterId).sort() : [];
  const envOpts = [chip(env, "", "All", "env"), ...config.environments.map((e) => chip(env, e, e, "env"))];
  const clusterOpts = [chip(cluster, "", "All", "cluster"), ...clusterIds.map((c) => chip(cluster, c, c, "cluster"))];
  const tierOpts = [chip(tier, "", "All", "tier"), ...tierNames(catalog.state === "ok" ? catalog.data : null).map((t) => chip(tier, t, t, "tier"))];
  const sortOpts = SORTS.map(([id, label]) => chip(sort, id, label, "sort"));
  // A new page size keeps the first namespace of the page in view where the API can place a page: by name (startsWith).
  const sizeOpts = LIMITS.map((n) => ({ label: String(n), on: limit === n, pick: () => apply({ limit: String(n) }, sort === "name" && shownSort === "name" && page?.items[0] ? page.items[0].name : null) }));
  const firstOnPage = shownSort === "name" ? page?.items[0]?.name.charAt(0) ?? "" : "";

  // The call that this page sent, as the mockup's pager shows it. A cursor is cut: it is long, and it is not for reading.
  const sent = new URLSearchParams(Object.entries(query).map(([k, v]) => [k, k === "cursor" ? `${String(v).slice(0, 10)}…` : String(v)]));
  const exportParams: ExportQuery = { ...filters, ...(state ? { state } : {}), ...(sort !== "name" ? { sort } : {}) };
  const exportCall = new URLSearchParams(Object.entries(exportParams).map(([k, v]) => [k, String(v)])).toString();
  const onExport = () => {
    setExporting(true);
    exported.run(exportParams).catch(() => undefined);
  };

  const stale = result.state === "error" && result.code === "invalid-cursor";
  const items = page?.items ?? [];
  // The namespace shown below: the one in the address, else the first of the page. A namespace on another page stays shown.
  const shown = items.find((r) => keyOf(r) === chosen) ?? (chosen && lastShown.current && keyOf(lastShown.current) === chosen ? lastShown.current : items[0]) ?? null;
  lastShown.current = shown;
  const range = page
    ? page.page.total
      ? `${page.page.from}–${page.page.to} of ${page.page.total}${inScope !== null && page.page.total !== inScope ? ` (filtered from ${inScope})` : ""} · ${SORTS.find(([id]) => id === shownSort)![2]}`
      : "0 namespaces"
    : "";
  const pager = (text: string) => page && (
    <Pager
      busy={busy}
      range={text}
      prev={() => page.page.prevCursor && setCursor(page.page.prevCursor)}
      next={() => page.page.nextCursor && setCursor(page.page.nextCursor)}
      prevDis={!page.page.prevCursor}
      nextDis={!page.page.nextCursor}
    />
  );

  return (
    <Stack hasGutter>
      {head}
      <Panel>
        <Filter label="Needs attention" options={attention} />
        <Search
          applied={applied}
          onApply={(text) => apply({ q: text })}
          onPick={(s) => apply({ q: "", env: "", cluster: "", tier: "", state: "", sort: "name", ns: keyOf(s) }, s.name)}
          onExport={onExport}
        />
        <Flex gap={{ default: "gapMd" }}>
          <Filter label="Env" options={envOpts} />
          <Filter label="Cluster" options={clusterOpts} />
          <Filter label="Tier" options={tierOpts} />
          <Filter label="Sort" options={sortOpts} />
          <Filter label="Per page" options={sizeOpts} />
        </Flex>
        <Flex role="group" aria-label="Jump to the first namespace starting with a letter" gap={{ default: "gapXs" }}>
          {LETTERS.map((l) => {
            const n = page?.letters[l.toUpperCase()] ?? 0;
            return (
              <Button key={l} variant={n && firstOnPage === l ? "primary" : "tertiary"} size="sm" isAriaDisabled={!n}
                aria-label={`${l.toUpperCase()}: ${n} namespace${n === 1 ? "" : "s"}`} onClick={() => n && apply({ sort: "name" }, l)}>
                {l}
              </Button>
            );
          })}
        </Flex>
        {exporting && <ExportView instance={config.instance} call={exportCall} outcome={exported} onClose={() => { setExporting(false); exported.reset(); }} />}
      </Panel>

      <Panel>
        {result.state === "loading" && <Stack hasGutter><span role="status">Loading quotas…</span><Skeleton /><Skeleton /><Skeleton /></Stack>}
        {result.state === "error" && !stale && (
          <Alert variant="danger" isInline title="The quotas did not load." actionLinks={<AlertActionLink onClick={result.reload}>Try again</AlertActionLink>}>{result.cause}</Alert>
        )}
        {stale && (
          <Callout tone="warn" title="This page link is out of date">
            <Stack hasGutter>
              <span>The filters or sort changed after it was made, so the API refused it (400 invalid-cursor) rather than show the wrong rows.</span>
              <div><Button variant="secondary" size="sm" onClick={() => apply({})}>Back to the first page</Button></div>
            </Stack>
          </Callout>
        )}
        {page && (
          <>
            {pager(range)}
            <DataTable
              label="Quotas"
              cols={["Namespace", "Cluster", "Env", "Tier", "CPU requests", "Memory requests", "Pods", "Attention", ""]}
              rows={items}
              busy={busy}
              selected={(r) => shown !== null && keyOf(r) === keyOf(shown)}
              cells={(r) => {
                const s = sizesOf(r);
                const c = barOf(s.cpu[0], s.cpu[1]), m = barOf(s.memory[0], s.memory[1]);
                const sel = shown !== null && keyOf(r) === keyOf(shown);
                return [
                  r.name, r.clusterId, r.env ?? "—", r.tier ?? "—",
                  <Meter ariaLabel="CPU requests of quota" value={c?.pct ?? 0} bar={c?.bar} label={`${usedText(s.cpu, "")} cores`} />,
                  <Meter ariaLabel="Memory requests of quota" value={m?.pct ?? 0} bar={m?.bar} label={`${usedText(s.memory, "")} Gi`} />,
                  usedText(s.pods, ""), <Attention row={r} />,
                  <Button variant="secondary" size="sm" onClick={() => setParams({ ...view, sort: sort === "name" ? "" : sort, limit: limit === DEFAULT_LIMIT ? "" : String(limit), ns: keyOf(r) })}>{sel ? "Selected" : "Manage"}</Button>
                ];
              }}
            />
            {items.length === 0 && <Empty>{`No namespace on the ${config.instance} instance matches these filters.`}</Empty>}
            {pager(`GET /api/v1/quotas?${sent.toString()}`)}
          </>
        )}
        <Small>Quota status from the watch cache; no Thanos call. Pages follow a cursor on the sort key, so namespaces created or deleted between pages never cause a skip or a repeat. Bars turn amber at 80% and red at 95% of the hard limit.</Small>
      </Panel>

      {shown && (
        <Detail
          key={keyOf(shown)}
          row={shown}
          config={config}
          catalog={catalog.state === "ok" ? catalog.data : null}
          canChange={me.state === "ok" && me.data.access.permissions.includes(PATCH_NAMESPACE)}
          canProtect={me.state === "ok" && operatorIn(me.data, shown.env) && grantsIn(me.data.access, PATCH_NAMESPACE, shown.env)}
          onOpen={(id) => open("workflow", { request: id })}
        />
      )}
    </Stack>
  );
}

/** The API's attention counts that hold for one row: the same tests as `facets` (cmapi/src/cmapi/plugins/quotas). */
function Attention({ row }: { row: QuotaRow }) {
  const marks = [row.used >= 0.8 && <Pill key="n" tone="warn">near-limit</Pill>, row.openRequest && <Pill key="o">open-request</Pill>, row.tierOutdated && <Pill key="t" tone="warn">tier-outdated</Pill>].filter(Boolean);
  return marks.length ? <Flex gap={{ default: "gapXs" }}>{marks}</Flex> : <>—</>;
}

/** The mockup's type-ahead: GET /api/v1/quotas:suggest as the person types, with the keyboard of a combobox (ARIA APG). */
function Search({ applied, onApply, onPick, onExport }: { applied: string; onApply: (text: string) => void; onPick: (s: { name: string; clusterId: string }) => void; onExport: () => void }) {
  const [text, setText] = useState(applied);
  const [asked, setAsked] = useState("");
  const [openList, setOpenList] = useState(false);
  const [active, setActive] = useState(-1);
  useEffect(() => setText(applied), [applied]);
  // The call goes out when the typing stops, and Query cancels the call that a newer text replaces.
  useEffect(() => {
    const timer = setTimeout(() => setAsked(text), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text]);
  const listed = openList && text.trim().length >= SUGGEST_MIN;
  const suggestions = useSuggest(listed ? asked : "");
  const items = suggestions.state === "ok" && asked === text ? suggestions.data : [];
  const idx = Math.min(active, items.length - 1);
  const choose = (s: { name: string; clusterId: string }) => { setText(""); setOpenList(false); setActive(-1); onPick(s); };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" && items.length) { e.preventDefault(); setOpenList(true); setActive(Math.min(items.length - 1, idx + 1)); }
    else if (e.key === "ArrowUp" && items.length) { e.preventDefault(); setActive(Math.max(0, idx - 1)); }
    else if (e.key === "Enter" && idx >= 0 && items.length) { e.preventDefault(); choose(items[idx]); }
    else if (e.key === "Escape") { setOpenList(false); setActive(-1); }
  };
  const onSubmit = (e: FormEvent) => { e.preventDefault(); setOpenList(false); onApply(text.trim()); };
  const settled = asked === text && suggestions.state === "ok";
  return (
    <form role="search" onSubmit={onSubmit}>
      <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapSm" }}>
        <ComboBox
          isOpen={listed}
          input={(
            <TextInputGroup>
              <TextInputGroupMain
                inputId="q-search"
                type="search"
                role="combobox"
                aria-label="Find a namespace, team or app"
                aria-controls="q-sug"
                isExpanded={listed}
                placeholder="Find a namespace, team or app (type 2+ characters)"
                value={text}
                onChange={(_, v) => { setText(v); setOpenList(true); setActive(-1); }}
                inputProps={{ autoComplete: "off", "aria-autocomplete": "list", "aria-activedescendant": idx >= 0 ? `q-opt-${idx}` : undefined, onKeyDown: onKey }}
              />
            </TextInputGroup>
          )}
          list={(
            <Menu role="listbox">
              <MenuContent>
                <MenuList id="q-sug" aria-label="Matching namespaces">
                  {items.map((s, k) => (
                    <MenuItem key={keyOf(s)} id={`q-opt-${k}`} itemId={keyOf(s)} isFocused={k === idx} isSelected={k === idx} description={<>{s.clusterId} {s.why}</>} onClick={() => choose(s)}>{s.name}</MenuItem>
                  ))}
                  {settled && items.length === 0 && <MenuItem isDisabled>No namespace matches "{text}".</MenuItem>}
                  {!settled && suggestions.state !== "error" && suggestions.state !== "forbidden" && <MenuItem isDisabled>Searching…</MenuItem>}
                  {(suggestions.state === "error" || suggestions.state === "forbidden") && <MenuItem isDisabled>The matches did not load.</MenuItem>}
                </MenuList>
              </MenuContent>
            </Menu>
          )}
        />
        <Button variant="secondary" type="submit">Show all matches</Button>
        {applied && <Button variant="tertiary" onClick={() => onApply("")}>matching "{applied}" ✕</Button>}
        <Button variant="secondary" onClick={onExport}>Export CSV</Button>
      </Flex>
    </form>
  );
}

/** The export's answer: the file's name and rows, the call, the first rows, and the file itself to save. */
function ExportView({ instance, call, outcome, onClose }: { instance: string; call: string; outcome: ReturnType<typeof useExport>; onClose: () => void }) {
  const csv = outcome.state === "ok" ? outcome.data : null;
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => {
    if (csv === null) return;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    setHref(url);
    return () => URL.revokeObjectURL(url);
  }, [csv]);
  const close = <div><Button variant="secondary" size="sm" onClick={onClose}>Close</Button></div>;
  if (outcome.state === "sending" || outcome.state === "idle") return <span role="status">Exporting…</span>;
  if (outcome.state === "refused" || outcome.state === "error") {
    return <><Callout tone="bad" title="The export did not complete.">{outcome.state === "refused" ? `${outcome.code}: ${outcome.detail}` : outcome.cause}</Callout>{close}</>;
  }
  const lines = (csv ?? "").split(/\r?\n/).filter(Boolean);
  const rows = Math.max(0, lines.length - 1);
  const file = `quotas-${instance}-${isoDay(new Date())}.csv`;
  return (
    <>
      <Callout tone="info" title={`${file} · ${rows} rows`}>
        {`GET /api/v1/quotas:export${call ? `?${call}` : ""} streams every row matching the current filters, not only this page, in the current sort order. Capped at 10,000 rows and recorded in the audit log.`}
      </Callout>
      <Code text={lines.slice(0, 5).join("\n") + (rows > 4 ? `\n… ${rows - 4} more rows` : "")} />
      <Flex gap={{ default: "gapSm" }}>
        {href && <Button component="a" variant="primary" size="sm" href={href} download={file}>Download</Button>}
        {close}
      </Flex>
    </>
  );
}

interface DetailProps {
  row: QuotaRow;
  config: TabProps["config"];
  catalog: TierCatalog | null;
  canChange: boolean;
  /** An operator in the namespace's environment who may change it (#366): the protection control is shown. */
  canProtect: boolean;
  onOpen: (requestId: string) => void;
}

/** The namespace's ResourceQuota, whether a delete request is refused for it, and the form that changes its quota. */
function Detail({ row, config, catalog, canChange, canProtect, onOpen }: DetailProps) {
  const ns = useNamespace(row.clusterId, row.name);
  const view = ns.state === "ok" ? ns.data : null;
  const s = sizesOf(row);
  const rows = [["requests.cpu", s.cpu, " cores"], ["requests.memory", s.memory, " Gi"], ["pods", s.pods, ""]] as const;
  const etag = ns.state === "ok" ? ns.data.etag : null;
  return (
    <Grid hasGutter>
      <GridItem md={12} lg={6}>
        <Panel title={`${row.name} on ${row.clusterId}`} pill={view?.protected || row.tierOutdated ? (
          <Flex gap={{ default: "gapXs" }}>
            {view?.protected && <Label isCompact color="orange" icon={<LockIcon />}>Protected</Label>}
            {row.tierOutdated && <Pill tone="warn">tier-outdated</Pill>}
          </Flex>
        ) : undefined}>
          <Small>{`${row.env ?? "—"} · tier ${row.tier ?? "—"} · ResourceQuota ${row.name}-quota · read from the watch cache, current to the second`}</Small>
          <DataTable
            label="ResourceQuota"
            cols={["ResourceQuota", "Used", "Hard", ""]}
            blank="Used of hard"
            rows={[...rows]}
            cells={([k, pair, unit]) => {
              const b = barOf(pair[0], pair[1]);
              return [k, pair[0] === null ? "—" : `${fmt(pair[0])}${unit}`, pair[1] === null ? "—" : `${fmt(pair[1])}${unit}`,
                <Meter ariaLabel={`${k} used of hard`} value={b?.pct ?? 0} bar={b?.bar} label={b ? `${b.pct}%` : "—"} />];
            }}
          />
          {ns.state === "error" && <Callout tone="bad" title="The namespace did not load.">{ns.cause}</Callout>}
          {view?.protected && <Small>{protectionLine(view)}</Small>}
          {canProtect && view && !row.openRequest && <ProtectControl view={view} reread={ns.reload} onOpen={onOpen} />}
          <Small>{`GET /api/v1/clusters/${row.clusterId}/namespaces/${row.name} · ETag ${etag ?? "—"} · ResourceQuota and LimitRange for tier ${row.tier ?? "—"} live in the namespace folder in Git.`}</Small>
        </Panel>
      </GridItem>
      {canChange && (
        <GridItem md={12} lg={6}>
          <Panel title={`Change quota · ${row.name}`} pill={<Pill>{`${row.env ?? "—"} · ${row.clusterId}`}</Pill>}>
            {row.openRequest ? (
              <Callout tone="warn" title={`Change in progress: ${row.openRequest}`}>
                <Stack hasGutter>
                  <span>{`${row.openRequest} holds this namespace in cmapi. cmapi holds one open request per namespace, so another change is refused with 409 change-pending until this one closes.`}</span>
                  <div><Button variant="secondary" size="sm" onClick={() => onOpen(row.openRequest!)}>Open at current step</Button></div>
                </Stack>
              </Callout>
            ) : etag === null ? (
              ns.state === "loading" ? <span role="status">Loading the namespace…</span> : null
            ) : (
              <ChangeForm row={row} etag={etag} config={config} catalog={catalog} reread={ns.reload} />
            )}
          </Panel>
        </GridItem>
      )}
    </Grid>
  );
}

/** The plan's approval as the mockup's callout of a quota change: who must approve, and why. */
function approvalOf(plan: Plan, env: string): { tone: string; title: string; detail: string } {
  const a = plan.approval;
  const need = a.slots.reduce((n, x) => n + x.count, 0);
  if (a.auto && a.auto !== "none-required") return { tone: "ok", title: `Auto-approved by ${policyOf(a.auto)}`, detail: sentence(a.reasons) };
  if (need === 0) return { tone: "ok", title: "No approval needed", detail: `${sentence(a.reasons)} The request is approved at once; the bot PR merges as soon as CI passes.`.trim() };
  const groups = a.slots.map((x) => x.group).join(" + ");
  const self = a.selfApproval ? `Nothing reaches Git until they approve. Self-approval is allowed in ${env}.` : "Nothing reaches Git until they approve; the requester cannot approve their own request.";
  return { tone: need > 1 ? "warn" : "info", title: `${need} approval${need > 1 ? "s" : ""} in cmapi from ${groups}`, detail: `${sentence(a.reasons)} ${self}`.trim() };
}

/** What the 202 says, in the mockup's words: approved at once, or waiting for its approvals. */
function sentOf(r: ChangeRequest): { title: string; text: string } {
  const { need, have } = countsOf(r);
  const groups = (r.approval?.slots ?? []).map((x) => x.group).join(" + ");
  const left = need - have;
  return {
    title: `202 Accepted · ${r.requestId} · ${r.status}`,
    text: r.status === "pending_approval"
      ? `Waiting for ${left} approval${left > 1 ? "s" : ""} in cmapi (${groups}). The approvers are notified; nothing is written to Git until the count is met.`
      : `Approved at once: the worker opens a bot PR now; it merges when CI passes and Argo CD re-stamps the quota on ${r.clusterId}.`
  };
}

function ChangeForm({ row, etag, config, catalog, reread }: { row: QuotaRow; etag: string; config: TabProps["config"]; catalog: TierCatalog | null; reread: () => void }) {
  const env = row.env ?? "";
  const tiers = tiersOf(catalog, row.env);
  const bounds = boundsOf(catalog, row.env);
  const current = sizesOf(row);
  const [size, setSize] = useState(row.tier ?? "");
  const [cpuRaw, setCpu] = useState(current.cpu[1] === null ? "" : String(current.cpu[1]));
  const [memRaw, setMem] = useState(current.memory[1] === null ? "" : String(current.memory[1]));
  const [why, setWhy] = useState("");
  const [planned, setPlanned] = useState<PlannedChange | null>(null);
  // The change that the last Submit sent, so that its answer shows only while the form is that change.
  const [submitted, setSubmitted] = useState<string | null>(null);
  const form = useRef<HTMLFormElement>(null);
  // One key for each change that this form sends (#282): the same change sent again keeps its key, a changed one gets a new one.
  const sentKey = useRef<{ key: string; change: string } | null>(null);
  const keyFor = (fingerprint: string): string => {
    if (sentKey.current?.change !== fingerprint) sentKey.current = { key: crypto.randomUUID(), change: fingerprint };
    return sentKey.current.key;
  };
  const plan = usePatchPlan(planned);
  const submit = useSubmitPatch();

  const custom = size === CUSTOM;
  const named = tiers.find((t) => t.name === size && !t.custom);
  const newCpu = custom ? parseFloat(cpuRaw) : named?.cpu ?? NaN;
  const newMem = custom ? parseFloat(memRaw) : named?.memory ?? NaN;
  const newPods = custom ? current.pods[1] : named?.pods ?? null;
  const same = newCpu === current.cpu[1] && newMem === current.memory[1] && newPods === current.pods[1];
  const body: NamespacePatch = custom
    ? { tier: CUSTOM, quota: { "requests.cpu": cpuRaw.trim(), "requests.memory": `${memRaw.trim()}Gi` }, justification: why || null }
    : { tier: size, justification: why || null };
  const change: PlannedChange = { clusterId: row.clusterId, ns: row.name, etag, body };
  // The key's fingerprint is the request: where and the body. If-Match is its precondition, so the same body sent again on
  // a newer etag keeps its key, as the API's replay compares the body only (cmapi/src/cmapi/plugins/namespaces/router.py).
  const fingerprint = JSON.stringify([row.clusterId, row.name, body]);
  const ofBody = (p: PlannedChange): boolean => JSON.stringify([p.clusterId, p.ns, p.body]) === fingerprint;
  // A plan is of one body at one etag: a plan made at an etag that the namespace no longer has is not the plan of the form.
  const planIsOfForm = planned !== null && ofBody(planned) && planned.etag === etag;
  // A 412 or 428, of the plan or of the submit, reads the namespace again instead of sending its stale etag again (docs/04).
  const stale = (planned !== null && ofBody(planned) && outdated(plan)) || (submitted === fingerprint && outdated(submit));
  useEffect(() => { if (stale) reread(); }, [stale]);
  // The namespace read again with a new etag plans the same change on it, so the next Submit sends a plan of the folder now.
  useEffect(() => { setPlanned((p) => (p !== null && p.etag !== etag && ofBody(p) ? { ...p, etag } : p)); }, [etag]);
  const [asked, setAsked] = useState(false);
  const edit = <T,>(set: (value: T) => void) => (value: T) => { set(value); setPlanned(null); setAsked(false); };

  const onPlan = () => {
    // A value that the browser refuses (below the custom tier's minimum, off its step) is not sent.
    if (!form.current?.reportValidity()) return;
    setAsked(true);
    if (!same) setPlanned(change);
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (submit.state === "sending") return;
    setAsked(true);
    if (same) return;
    // Nothing is submitted that the person has not seen planned: a form with no plan, or changed since its plan, is planned
    // first, and the next Submit sends it. A refused or failed plan is on the page, and Submit waits for a plan.
    if (!planIsOfForm) { setPlanned(change); return; }
    if (plan.state !== "ok") return;
    setSubmitted(fingerprint);
    submit.submit(planned, keyFor(fingerprint)).catch(() => undefined);
  };

  const planOk = plan.state === "ok" && planIsOfForm ? plan.data : null;
  const checks: Check[] = planOk ? [
    { s: "pass", mark: MARK.pass, main: "Environment served", note: `${env} in [${config.environments.join(", ")}]` },
    { s: "pass", mark: MARK.pass, main: "If-Match matches the current ETag", note: planned!.etag },
    { ...capacityCheck(planOk), main: `Capacity on ${row.clusterId}`, note: `${capacityCheck(planOk).note} · ${capacityLine(planOk)}` },
    { s: planOk.approval.auto ? "pass" : "warn", mark: planOk.approval.auto ? MARK.pass : MARK.warn, main: "Approval", note: planOk.approval.rule }
  ] : [];
  const appr = planOk ? approvalOf(planOk, env) : null;
  const answered = submitted === fingerprint ? submit : null;

  const sizes: Choice[] = tiers.map((t) => ({
    label: t.name,
    sub: t.custom ? "set cpu and memory" : `${t.cpuText} cores · ${t.memoryText}${t.name === row.tier ? " · current" : ""}`,
    on: t.name === size,
    pick: () => edit(setSize)(t.name)
  }));
  if (!tiers.length) return <Empty>{`The catalog has no tier for ${env || "this namespace's environment"}.`}</Empty>;
  return (
    <Form noValidate={false} onSubmit={onSubmit} ref={form}>
      <FormGroup label="New size" role="group" fieldId="q-size">
        <Choices label="New size" options={sizes} />
        <Hint>{"A tier changes one label and the operator re-stamps the quota (PATCH …/namespaces/{ns}). Custom sets requests.cpu and requests.memory directly, in the same PATCH."}</Hint>
      </FormGroup>
      {custom && (
        <Grid hasGutter>
          <GridItem md={6}>
            <FormGroup label="requests.cpu (cores)" fieldId="q-cpu">
              <TextInput id="q-cpu" type="number" isRequired min={bounds.cpu.min} max={bounds.cpu.max} step={bounds.cpu.step} inputMode="numeric" value={cpuRaw} onChange={(_, v) => edit(setCpu)(v)} />
            </FormGroup>
          </GridItem>
          <GridItem md={6}>
            <FormGroup label="requests.memory (Gi)" fieldId="q-mem">
              <TextInput id="q-mem" type="number" isRequired min={bounds.memory.min} max={bounds.memory.max} step={bounds.memory.step} value={memRaw} onChange={(_, v) => edit(setMem)(v)} />
            </FormGroup>
          </GridItem>
        </Grid>
      )}
      <FormGroup label="Justification" fieldId="q-why">
        <TextArea id="q-why" placeholder="Why this size is needed, for example the load test or launch it supports" value={why} onChange={(_, v) => edit(setWhy)(v)} />
      </FormGroup>
      <ActionGroup>
        <Button variant="secondary" type="button" onClick={onPlan}>Plan change</Button>
        <Button variant="primary" type="submit" isLoading={submit.state === "sending"}>Submit change</Button>
      </ActionGroup>
      {asked && same && <Empty>The new size equals the current quota; pick another tier or custom values.</Empty>}
      {plan.state === "sending" && <span role="status">Planning…</span>}
      {planOk && appr && (
        <Stack hasGutter>
          <Checks items={checks} />
          <Callout tone={appr.tone} title={appr.title}>{appr.detail}</Callout>
        </Stack>
      )}
      {planIsOfForm && plan.state === "refused" && <Callout tone="bad" title={`Refused: ${plan.code}`}>{plan.detail}</Callout>}
      {planIsOfForm && plan.state === "error" && (
        <Alert variant="danger" isInline title="The plan did not complete." actionLinks={<AlertActionLink onClick={plan.reload}>Try again</AlertActionLink>}>{plan.cause}</Alert>
      )}
      {answered?.state === "ok" && (
        <>
          <Callout tone="ok" title={sentOf(answered.data).title}>{sentOf(answered.data).text}</Callout>
          <Code text={JSON.stringify({ requestId: answered.data.requestId, status: answered.data.status, clusterId: answered.data.clusterId, namespace: answered.data.namespace,
            approval: answered.data.approval && { rule: answered.data.approval.rule, remaining: answered.data.approval.remaining }, links: answered.data.links }, null, 2)} />
        </>
      )}
      {answered?.state === "refused" && <Callout tone="bad" title={`${answered.status} ${answered.code} · nothing written`}>{`No request was stored and nothing was written to Git. ${answered.detail}`}</Callout>}
      {answered?.state === "error" && <Callout tone="bad" title="Not submitted">{`${answered.cause} Submit again: the same request is sent, and the API makes it at most once.`}</Callout>}
    </Form>
  );
}

/**
 * Why a delete request is refused, from the API's protectedBy: the labels in Git that a delete checks (#366). "A delete
 * request", not "a delete": no Kyverno rule reads the label, so a delete outside cmapi is not stopped.
 */
function protectionLine(view: NamespaceView): string {
  const expiry = view.expiresAt ? " Its expiry will not delete it: the delete after its grace is held while it is protected." : "";
  return `cmapi refuses a delete request for this namespace (422 namespace-protected): ${(view.protectedBy ?? []).join(", ")}.${expiry}`;
}

const PROTECTION = `${PROTECT_KEY}=${PROTECT_VALUE}`;

/**
 * An operator protects the namespace, or removes the protection (#366): a Button that opens a dialog with the plan of the
 * change and its approval, then submits it. Not a Switch: PatternFly's switch saves at once, and this change is a request
 * that may wait for an approval. The body names the protection label only, "true" or null (a merge patch removes a key
 * with null), so the control cannot carry another change; the API keeps every other key.
 */
function ProtectControl({ view, reread, onOpen }: { view: NamespaceView; reread: () => void; onOpen: (requestId: string) => void }) {
  const set = (view.protectedBy ?? []).includes(PROTECTION);
  const others = (view.protectedBy ?? []).filter((p) => p !== PROTECTION);
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  // One key for each change (#282): the same change sent again after a lost answer keeps it.
  const keyOfChange = useRef<{ key: string; change: string } | null>(null);
  const label = { [PROTECT_KEY]: set ? null : PROTECT_VALUE };
  // The plan is of the label change at the namespace's etag now; a 412 or 428 reads the namespace again and plans again.
  const change: PlannedChange = { clusterId: view.clusterId, ns: view.name, etag: view.etag ?? "", body: { labels: label } };
  const plan = usePatchPlan(open && view.etag ? change : null);
  const submit = useSubmitPatch();
  const body: NamespacePatch = { labels: label, justification: why || null };
  const fingerprint = JSON.stringify([view.clusterId, view.name, body]);
  const answered = submitted === fingerprint ? submit : null;
  const stale = outdated(plan) || (answered !== null && outdated(answered));
  useEffect(() => { if (open && stale) reread(); }, [open, stale]);
  // A 403 says the roles changed since /me was read: read it again, so the control follows what the API now allows.
  const queries = useQueryClient();
  const forbidden = answered?.state === "refused" && answered.status === 403;
  useEffect(() => { if (forbidden) void queries.invalidateQueries({ queryKey: ["me"] }); }, [forbidden]);

  const close = () => { setOpen(false); setWhy(""); setSubmitted(null); };
  const keyFor = (): string => {
    if (keyOfChange.current?.change !== fingerprint) keyOfChange.current = { key: crypto.randomUUID(), change: fingerprint };
    return keyOfChange.current.key;
  };
  const planOk = plan.state === "ok" ? plan.data : null;
  const done = answered?.state === "ok";
  const onSubmit = () => {
    if (!planOk || submit.state === "sending" || done) return;
    setSubmitted(fingerprint);
    submit.submit({ ...change, body }, keyFor()).catch(() => undefined);
  };
  const appr = planOk ? approvalOf(planOk, view.env ?? "") : null;
  // The title is the button's name; PatternFly truncates a long title on a phone, so the namespace is in the body.
  const title = set ? "Remove protection" : "Protect from deletion";
  return (
    <>
      <div>
        <Button variant={set ? "warning" : "secondary"} onClick={() => setOpen(true)}>{set ? "Remove protection" : "Protect from deletion"}</Button>
      </div>
      <Modal variant="small" isOpen={open} onClose={close} aria-labelledby="protect-title" aria-describedby="protect-what">
        <ModalHeader title={title} labelId="protect-title" titleIconVariant={set ? "warning" : undefined} />
        <ModalBody>
          <Stack hasGutter>
            <span id="protect-what">{set
              ? `This sends a request to remove ${PROTECTION} from ${view.name}. Once it is applied, cmapi accepts a delete request for the namespace again.`
              : `This sends a request to add ${PROTECTION} to ${view.name}. Once it is applied, cmapi refuses a delete request for the namespace (422 namespace-protected), also the delete after it expires.`}</span>
            {set && others.length > 0 && (
              <Callout tone="warn" title={`Still protected by ${others.join(", ")}`}>{"This request removes " + PROTECT_KEY + " only, so cmapi still refuses a delete request."}</Callout>
            )}
            <FormGroup label="Justification" fieldId="protect-why">
              <TextArea id="protect-why" value={why} isDisabled={done} onChange={(_, v) => setWhy(v)} />
            </FormGroup>
            {plan.state === "sending" && <span role="status">Planning…</span>}
            {planOk && appr && (
              <Stack hasGutter>
                <Checks items={[
                  { s: "pass", mark: MARK.pass, main: "If-Match matches the current ETag", note: change.etag },
                  { s: planOk.approval.auto ? "pass" : "warn", mark: planOk.approval.auto ? MARK.pass : MARK.warn, main: "Approval", note: planOk.approval.rule }
                ]} />
                <Callout tone={appr.tone} title={appr.title}>{appr.detail}</Callout>
              </Stack>
            )}
            {plan.state === "refused" && !outdated(plan) && <Callout tone="bad" title={`Refused: ${plan.code}`}>{plan.detail}</Callout>}
            {plan.state === "error" && (
              <Alert variant="danger" isInline title="The plan did not complete." actionLinks={<AlertActionLink onClick={plan.reload}>Try again</AlertActionLink>}>{plan.cause}</Alert>
            )}
            <div role="status">
              {done && (
                <Callout tone="ok" title={sentOf(answered.data).title}>
                  <Stack hasGutter>
                    <span>{sentOf(answered.data).text}</span>
                    <div><Button variant="secondary" size="sm" onClick={() => { close(); onOpen(answered.data.requestId); }}>Open at current step</Button></div>
                  </Stack>
                </Callout>
              )}
            </div>
            {answered?.state === "refused" && !outdated(answered) && (
              <Callout tone="bad" title={`${answered.status} ${answered.code} · nothing written`}>{`No request was stored and nothing was written to Git. ${answered.detail}`}</Callout>
            )}
            {answered?.state === "error" && <Callout tone="bad" title="Not submitted">{`${answered.cause} Submit again: the same request is sent, and the API makes it at most once.`}</Callout>}
          </Stack>
        </ModalBody>
        <ModalFooter>
          {!done && <Button variant={set ? "warning" : "primary"} onClick={onSubmit} isDisabled={!planOk} isLoading={submit.state === "sending"}>Submit request</Button>}
          <Button variant="link" onClick={close}>{done ? "Close" : "Cancel"}</Button>
        </ModalFooter>
      </Modal>
    </>
  );
}
