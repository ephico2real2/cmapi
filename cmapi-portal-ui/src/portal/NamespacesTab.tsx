// The Namespaces tab (#484, design of #481, section 6; mockup docs/reviews/2026-11-20-epic-481-metadata-patch/
// mockup-namespaces-tab.html): pick a cluster, then a namespace; see what Git holds beside what the cluster has; change its
// labels and annotations through a request, as a create goes. MOCKUP-CONTRACT.md lists what differs from the mockup, and why.
//
// The workflow, from the person's choice to the API's answer (each step's function is named):
//   1. NamespaceLookup: the cluster (GET /api/v1/clusters), its chips and the lookup (GET .../namespaces?q=&mnemonic=&limit=).
//   2. NamespaceChange reads the namespace (useNamespace: its Git, its live state, its sync and its ETag) and the rules
//      (useMetadataKeys: x-cmapi-edit of each key); rowsOf makes the table's rows, locked keys with their reason.
//   3. Each edit goes into the draft (withValue), a merge patch over Git; checkDraft checks it as it is typed, by the API's rules.
//   4. Check (dry run): the form's own problems first; then PATCH ...?dryRun=true with If-Match (usePatchPlan). The plan's
//      metadataDiff and approval replace the change box's estimate (changeLines).
//   5. Submit: the plan on the page, with its If-Match and one Idempotency-Key (useSubmitPatch). A 202 shows the request and
//      reads the namespace again, so the strip says Pending.
//   6. A 412 reads the namespace again; rebase puts the draft on the new Git and asks about each key that both sides changed.
//      A 409 shows the holder, and Submit stays off until Reload.
import {
  ActionGroup, Alert, AlertActionLink, Button, EmptyState, EmptyStateBody, Flex, FlexItem, Form, FormGroup, FormHelperText, Grid, GridItem,
  HelperText, HelperTextItem, Label, List, ListItem, Skeleton, Stack, TextArea, TextInput
} from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useClusters, useMe, useMetadataKeys, useNamespace, usePatchPlan, useSubmitPatch } from "../api/hooks";
import type { ChangeRequest, Cluster, Me, NamespacePatch, NamespaceView, PlannedChange } from "../api/hooks";
import { ApiProblem } from "../api/problem";
import { PERMISSION } from "../api/permissions.generated";
import { Callout, Head, Hint, Panel, Small } from "../components/ui";
import { grantsIn, operatorIn } from "./access";
import { extraInputId, ExtraKeysSection } from "./ExtraKeysSection";
import { fieldName, FieldInput } from "./MetadataFields";
import { checkExtras, checkExtraValue, checkField, errorsByField, nameEnds, valueKey } from "./metadataForm";
import type { ExtraCheck, ExtraRow, Kind, MetaForm } from "./metadataForm";
import { NamespaceLookup } from "./NamespaceLookup";
import { changeLines, isEditable, patchOf, rebase, rowsOf, valueNow, withValue } from "./namespaceChange";
import type { ChangeLine, Draft, GitEdits, KeyRow, Maps } from "./namespaceChange";
import { sharedPatternTest } from "./patterns";
import { approvalCard } from "./plan";
import { EXPIRES_AT } from "./preview";
import type { TabProps } from "./route";

const PATCH_NAMESPACE = PERMISSION["PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}"];
/** How long the change waits after the last keystroke before it checks the fields, as the New namespace form (#336, D7). */
const CHECK_AFTER_MS = 150;
const NO_ROWS: Record<Kind, ExtraRow[]> = { label: [], annotation: [] };
const NO_EDITS: GitEdits = { labels: {}, annotations: {} };
const PASSED = "The check passed (dry run, 200). Nothing is written yet.";

const mapsOf = (m: { labels: Record<string, string>; annotations: Record<string, string> } | null | undefined): Maps =>
  ({ label: { ...m?.labels }, annotation: { ...m?.annotations } });
const kindKey = (id: string): [Kind, string] => [id.slice(0, id.indexOf(":")) as Kind, id.slice(id.indexOf(":") + 1)];

export function NamespacesTab({ params, setParams, open }: TabProps) {
  const me = useMe();
  const clusters = useClusters();
  const rules = useMetadataKeys();
  const clusterId = params.get("cluster") ?? "";
  const ns = params.get("ns") ?? "";
  const head = <Head title="Namespaces" lede="Pick a cluster, then a namespace. See what Git holds beside what the cluster has, and change its labels and annotations. Changes go through a request, approval and Git, like a new namespace." />;

  const forbidden = [clusters, rules].find((r) => r.state === "forbidden");
  if (forbidden?.state === "forbidden") {
    return (
      <Stack hasGutter>
        {head}
        <EmptyState titleText="You do not have permission to see namespaces." headingLevel="h2" icon={LockIcon}>
          <EmptyStateBody>{forbidden.detail}</EmptyStateBody>
        </EmptyState>
      </Stack>
    );
  }
  const failed = [clusters, rules].find((r) => r.state === "error");
  if (failed?.state === "error") {
    return (
      <Stack hasGutter>
        {head}
        <Alert variant="danger" isInline title="The tab did not load." actionLinks={<AlertActionLink onClick={() => { clusters.reload(); rules.reload(); }}>Try again</AlertActionLink>}>
          {failed.cause}
        </Alert>
      </Stack>
    );
  }
  if (clusters.state !== "ok" || rules.state !== "ok" || me.state !== "ok") {
    return <Stack hasGutter>{head}<span role="status">Loading the clusters…</span><Skeleton /></Stack>;
  }
  const form = rules.data.form;
  // A declared key whose x-cmapi-edit the answer lacks would be offered with no rule: the tab says so instead (design 4.3).
  const unruled = form.fields.find((f) => !form.edits[valueKey(f)]);
  if (unruled) {
    return <Stack hasGutter>{head}<Alert variant="danger" isInline title="The tab did not load.">{`The metadata rules of this instance do not say how the ${unruled.kind} ${unruled.key} may change (x-cmapi-edit).`}</Alert></Stack>;
  }
  const cluster = clusters.data.items.find((c) => c.clusterId === clusterId);
  const start = nameEnds(form).start;
  return (
    <Stack hasGutter>
      {head}
      <Panel>
        <NamespaceLookup clusters={clusters.data.items} clusterId={cluster ? clusterId : ""} chipTitle={start ? start.title ?? start.key : null}
          onCluster={(id) => setParams({ cluster: id })} onOpen={(name) => setParams({ cluster: clusterId, ns: name })} />
      </Panel>
      {cluster && ns
        ? <NamespaceChange key={`${clusterId}/${ns}`} cluster={cluster} ns={ns} form={form} me={me.data} open={open} />
        : <EmptyState titleText="Choose a cluster and a namespace to see it." headingLevel="h2" variant="sm" />}
    </Stack>
  );
}

/** The problems of one state of the change, as the form's own checks see them, by the id of the control each one names. */
interface DraftCheck { rows: Record<string, string | null>; extras: Partial<Record<Kind, ExtraCheck>> }

/**
 * The form's own checks of the change, by the API's rules (metadataForm.ts): each drafted declared key as it will be sent
 * (checkField with sent), each drafted additional key's value (checkExtraValue), and each new additional row (checkExtras),
 * where a key that the namespace already holds is changed in the table, not added again.
 */
async function checkDraft(form: MetaForm, ns: string, rows: KeyRow[], draft: Draft, added: Record<Kind, ExtraRow[]>, git: Maps): Promise<DraftCheck> {
  const out: DraftCheck = { rows: {}, extras: {} };
  for (const r of rows) {
    const value = draft[r.id];
    if (!(r.id in draft) || value === null) continue;
    out.rows[r.id] = r.field ? await checkField(r.field, value, { namespace: ns, labelValue: form.labelValue }, sharedPatternTest, true)
      : await checkExtraValue(form, r.kind, value, sharedPatternTest);
  }
  for (const kind of ["label", "annotation"] as const) {
    if (!form.otherKeys[kind]) continue;
    const check = await checkExtras(form, kind, added[kind], sharedPatternTest);
    for (const r of added[kind]) {
      if (r.key in git[kind] && check.rows[r.id] && !check.rows[r.id].key) check.rows[r.id].key = "This key is already on the namespace: change it in the table.";
    }
    out.extras[kind] = check;
  }
  return out;
}

/** The status strip (design T3): the API's sync state, the request that holds the namespace, and the keys that drifted. */
function SyncStrip({ view, held, onReload, onOpen }: { view: NamespaceView; held: boolean; onReload: () => void; onOpen: (requestId: string) => void }) {
  const { state, openRequest, driftedKeys } = view.sync;
  const reload = <AlertActionLink onClick={onReload}>Reload</AlertActionLink>;
  if (openRequest) {
    return (
      <Alert variant="info" isInline title="Pending" actionLinks={<>{reload}<AlertActionLink onClick={() => onOpen(openRequest.requestId)}>Open at current step</AlertActionLink></>}>
        {`${openRequest.requestId} (${openRequest.status}) holds ${view.name}.${held ? " Submit stays off until it finishes and you reload." : ""}`}
      </Alert>
    );
  }
  if (state === "drift") {
    const n = driftedKeys.length;
    const what = n ? `${n} key${n > 1 ? "s" : ""} on the cluster differ${n > 1 ? "" : "s"} from Git` : "The cluster does not have this namespace";
    return <Alert variant="warning" isInline title="Drift" actionLinks={reload}>{`${what} · no open request. Your change applies to Git, which the cluster is brought back to.`}</Alert>;
  }
  if (state === "in-sync") return <Alert variant="success" isInline title="In sync" actionLinks={reload}>The cluster has what Git holds.</Alert>;
  return <Alert variant="custom" isInline title="Unknown" actionLinks={reload}>cmapi cannot compare Git with the cluster now: the cluster's watch is not fresh.</Alert>;
}

/** One line of the change box: "label company.net/cl   1 → 2", with its approval mark. */
function Line({ line, source }: { line: ChangeLine; source?: string }) {
  return (
    <ListItem>
      <code>{`${line.kind} ${line.key}   ${line.before ?? "(new)"} → ${line.after ?? "(removed)"}`}</code>
      {line.sensitive && <> <Label isCompact color="purple">+1 approval</Label></>}
      {source && source !== "request" && <> <Small>{`from the ${source}`}</Small></>}
    </ListItem>
  );
}

/** The change of one namespace: the strip, the Git | Live | Your change table, the new keys, and the change box beside them. */
function NamespaceChange({ cluster, ns, form, me, open }: { cluster: Cluster; ns: string; form: MetaForm; me: Me; open: TabProps["open"] }) {
  const view = useNamespace(cluster.clusterId, ns);
  const data = view.state === "ok" ? view.data : null;
  // The Git that the draft was made against, and its ETag: the If-Match of the change.
  const [base, setBase] = useState<{ etag: string; git: Maps } | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [added, setAdded] = useState<Record<Kind, ExtraRow[]>>(NO_ROWS);
  const [addOpen, setAddOpen] = useState(false);
  const rowIds = useRef(0);
  const [why, setWhy] = useState("");
  // After a 412: the keys that both sides changed, still to choose for, and that the namespace was read again.
  const [conflicts, setConflicts] = useState<string[]>([]);
  const [rebased, setRebased] = useState(false);
  const after412 = useRef(false);
  // A 409 change-pending: Submit stays off until the person reloads (design T8).
  const [held, setHeld] = useState(false);
  const [planned, setPlanned] = useState<{ change: PlannedChange; draft: string } | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [done, setDone] = useState<ChangeRequest | null>(null);
  const [problems, setProblems] = useState<{ text: string; focus: string }[]>([]);
  // The refusal of the last Submit, until the change or the namespace moves on: a 5xx or a lost answer is sent again as is.
  const [notSent, setNotSent] = useState<{ status: number; code: string; detail: string } | null>(null);
  const plan = usePatchPlan(planned?.change ?? null);
  const submit = useSubmitPatch();
  // One Idempotency-Key for each change sent (#282): the same change sent again keeps it, a changed one gets a new one.
  const sent = useRef<{ key: string; request: string } | null>(null);
  const keyFor = (change: PlannedChange): string => {
    const request = JSON.stringify(change);
    if (sent.current?.request !== request) sent.current = { key: crypto.randomUUID(), request };
    return sent.current.key;
  };

  // Step 6: a read with a new ETag puts the draft on the new Git (rebase); the first read sets the base.
  const etag = data?.etag ?? null;
  useEffect(() => {
    if (!data || etag === null) return;
    const git = mapsOf(data.git);
    if (base === null) { setBase({ etag, git }); return; }
    if (base.etag === etag) return;
    const next = rebase(draft, base.git, git);
    setDraft(next.draft);
    setConflicts(next.conflicts);
    setRebased(after412.current);
    after412.current = false;
    setBase({ etag, git });
  }, [etag, base]);

  const git = base?.git ?? mapsOf(data?.git), live = mapsOf(data);
  const env = cluster.environment;
  const canChange = grantsIn(me.access, PATCH_NAMESPACE, env) && data?.git != null;
  // namespaces:protect in this environment, as the Quotas tab's protection control decides it (#366): design section 3, row 4.
  const operator = canChange && operatorIn(me, env);
  const rows = data ? rowsOf(form, git, live, data.git?.edits ?? NO_EDITS, operator) : null;

  // Step 3: the checks of the draft, CHECK_AFTER_MS after the last change; a result shows only while the draft is that one.
  const inputs = JSON.stringify([draft, added, etag]);
  const [checked, setChecked] = useState<{ inputs: string; result: DraftCheck } | null>(null);
  const result = checked?.inputs === inputs ? checked.result : null;
  useEffect(() => {
    if (!rows) return;
    let alive = true;
    const timer = setTimeout(() => { void checkDraft(form, ns, rows, draft, added, git).then((r) => { if (alive) setChecked({ inputs, result: r }); }); }, CHECK_AFTER_MS);
    return () => { alive = false; clearTimeout(timer); };
  }, [inputs, rows !== null]);

  const body: NamespacePatch = { ...patchOf(draft, added), justification: why || null };
  const draftText = JSON.stringify([draft, added, why]);
  const planIsOfForm = planned !== null && base !== null && planned.change.etag === base.etag && planned.draft === draftText;
  const planOk = plan.state === "ok" && planIsOfForm ? plan.data : null;
  const refusal = plan.state === "refused" && planIsOfForm ? plan : null;
  const holder = data?.sync.openRequest ?? null;
  const canSubmit = planOk !== null && !held && holder === null && conflicts.length === 0 && submit.state !== "sending";

  // A 412 of the dry run: the namespace is read again, and the new ETag rebases the draft (a 412 of Submit: onSubmit).
  const stale = plan.state === "refused" && planIsOfForm && plan.status === 412;
  useEffect(() => {
    if (!stale) return;
    after412.current = true;
    view.reload();
  }, [stale]);

  if (view.state === "forbidden") {
    return <EmptyState titleText="You do not have permission to see this namespace." headingLevel="h2" icon={LockIcon}><EmptyStateBody>{view.detail}</EmptyStateBody></EmptyState>;
  }
  if (view.state === "error") {
    return <Alert variant="danger" isInline title="The namespace did not load." actionLinks={<AlertActionLink onClick={view.reload}>Try again</AlertActionLink>}>{view.cause}</Alert>;
  }
  if (!data || !rows || base === null) return <Stack hasGutter><span role="status">Loading the namespace…</span><Skeleton /><Skeleton /></Stack>;

  const errors = result?.rows ?? {};
  // A refusal's items on the fields they name (errorsByField), the others in the status list.
  const mapped = refusal ? errorsByField(refusal.errors, form) : null;
  const shownError = (r: KeyRow): string | null => errors[r.id] ?? (r.field ? mapped?.byField[r.field.id] : undefined) ?? null;
  const inputId = (r: KeyRow) => r.field?.id ?? `nsx-${r.kind}-${r.key.replace(/[^A-Za-z0-9]/g, "_")}`;
  const lines = changeLines(rows, draft, added);
  const diffLines: (ChangeLine & { source: string })[] = planOk?.metadataDiff
    ? (["label", "annotation"] as const).flatMap((kind) => Object.entries(planOk.metadataDiff![kind === "label" ? "labels" : "annotations"]).map(([key, c]) => ({
      kind, key, before: c.before ?? null, after: c.after ?? null, source: c.source, sensitive: !!form.edits[`${kind}:${key}`]?.sensitive })))
    : [];

  const reset = () => {
    setDraft({}); setAdded(NO_ROWS); setConflicts([]); setRebased(false); setHeld(false); setPlanned(null); setBlocked(false); setDone(null); setNotSent(null);
  };
  const reload = () => { reset(); view.reload(); };
  const edit = (r: KeyRow, value: string | null) => { setDraft((d) => withValue(d, r, value)); setDone(null); setNotSent(null); };

  /** The problems that stop Check before anything is sent, each with the id of the control that it names. */
  const problemsOf = (found: DraftCheck): { text: string; focus: string }[] => {
    const out: { text: string; focus: string }[] = [];
    for (const r of rows) if (found.rows[r.id]) out.push({ text: `${r.title}: ${found.rows[r.id]}`, focus: inputId(r) });
    for (const kind of ["label", "annotation"] as const) {
      const check = found.extras[kind];
      added[kind].forEach((r, i) => {
        const p = check?.rows[r.id];
        if (p?.key) out.push({ text: `New ${kind} ${i + 1}: ${p.key}`, focus: extraInputId(kind, r.id, "key") });
        if (p?.value) out.push({ text: `New ${kind} ${i + 1}: ${p.value}`, focus: extraInputId(kind, r.id, "value") });
      });
      for (const t of check?.table ?? []) out.push({ text: t, focus: "ns-extra-toggle" });
    }
    if (!why.trim()) out.push({ text: "Justification: say why this change is needed.", focus: "nsx-why" });
    return out;
  };
  const focusOn = (id: string) => {
    if (id.startsWith("ns-x")) setAddOpen(true);
    requestAnimationFrame(() => document.getElementById(id)?.focus());
  };

  /** Step 4: the form's own checks, then the dry run of exactly this change on the ETag it was made against. */
  const onCheck = async () => {
    setAttempted(true);
    if (conflicts.length) { setBlocked(true); setProblems([]); return; }
    const found = result ?? await checkDraft(form, ns, rows, draft, added, git);
    const list = problemsOf(found);
    setProblems(list);
    if (list.length) {
      if (list.some((p) => p.focus.startsWith("ns-x"))) setAddOpen(true);
      setBlocked(true);
      return;
    }
    setBlocked(false);
    setRebased(false);
    setDone(null);
    setNotSent(null);
    // Check on a checked change asks cmapi again: Git, the lock or the capacity can have moved.
    if (planIsOfForm) plan.reload();
    else setPlanned({ change: { clusterId: cluster.clusterId, ns, etag: base.etag, body }, draft: draftText });
  };
  /** Step 5: only the plan on the page, of the change as it is now. */
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !planned) return;
    submit.submit(planned.change, keyFor(planned.change)).then((request) => {
      reset();
      setWhy("");
      setDone(request);
      view.reload();
    }, (e: unknown) => {
      const problem = e instanceof ApiProblem ? e : null;
      setNotSent({ status: problem?.status ?? 0, code: problem?.code ?? "network", detail: problem?.detail ?? "The network did not answer." });
      if (problem?.status === 412) { after412.current = true; view.reload(); }
      if (problem?.status === 409 && problem.code === "change-pending") { setHeld(true); view.reload(); }
    });
  };
  const choose = (id: string, keep: boolean) => {
    if (!keep) setDraft((d) => { const next = { ...d }; delete next[id]; return next; });
    setConflicts((c) => c.filter((x) => x !== id));
  };
  const addRow = (kind: Kind) => {
    const id = ++rowIds.current;
    setAdded((x) => ({ ...x, [kind]: [...x[kind], { id, key: "", value: "" }] }));
    requestAnimationFrame(() => document.getElementById(extraInputId(kind, id, "key"))?.focus());
  };

  const status = () => {
    if (done) {
      return (
        <Alert variant="success" isInline isLiveRegion title={`Request ${done.requestId} submitted (202).`}
          actionLinks={<AlertActionLink onClick={() => open("workflow", { request: done.requestId })}>Open at current step</AlertActionLink>}>
          The strip shows Pending until the cluster has the change.
        </Alert>
      );
    }
    if (conflicts.length) {
      return (
        <Callout tone="bad" title="412: the namespace changed in Git. Reloaded; your other changes are kept. Both sides changed these keys:">
          <List isPlain>
            {conflicts.map((id) => {
              const [kind, key] = kindKey(id);
              return (
                <ListItem key={id}>
                  <Flex gap={{ default: "gapSm" }} alignItems={{ default: "alignItemsCenter" }}>
                    <code>{`${key}: now ${git[kind][key] ?? "(none)"}, yours ${draft[id] ?? "(removed)"}`}</code>
                    <Button variant="secondary" size="sm" onClick={() => choose(id, false)}>{`Use current for ${key}`}</Button>
                    <Button variant="secondary" size="sm" onClick={() => choose(id, true)}>{`Keep my edit for ${key}`}</Button>
                  </Flex>
                </ListItem>
              );
            })}
          </List>
        </Callout>
      );
    }
    if (notSent?.status === 409 && notSent.code === "change-pending") {
      return <Callout tone="bad" title="409 change-pending. Not submitted.">{`${notSent.detail}. Submit stays off until it finishes: then Reload.`}</Callout>;
    }
    if (notSent && notSent.status !== 412 && notSent.status > 0 && notSent.status < 500) return <Callout tone="bad" title="Not submitted">{`${notSent.code}: ${notSent.detail}`}</Callout>;
    if (notSent && notSent.status !== 412) return <Callout tone="bad" title="Not submitted">{`${notSent.detail} Submit again: the same request is sent, and the API makes it at most once.`}</Callout>;
    if (rebased) return <Callout tone="info" title="412: the namespace changed in Git. Reloaded; your changes are kept. Press Check (dry run) again." />;
    if (planIsOfForm && plan.state === "sending") return <span role="status">Checking with cmapi…</span>;
    if (planOk) {
      const appr = approvalCard(planOk, env);
      return (
        <Callout tone="ok" title={PASSED}>
          <div>{`${appr.title}. ${appr.detail}`}</div>
          <Small>{`${appr.rule} · If-Match "${planned?.change.etag}"`}</Small>
        </Callout>
      );
    }
    if (refusal) {
      return (
        <Callout tone="bad" title={`The check failed: ${refusal.code}`}>
          {refusal.detail}
          {mapped && mapped.items.length > 0 && <List>{mapped.items.map(({ text }, i) => <ListItem key={i}>{text}</ListItem>)}</List>}
        </Callout>
      );
    }
    if (planIsOfForm && plan.state === "error") return <Alert variant="danger" isInline title="The dry run did not complete." actionLinks={<AlertActionLink onClick={plan.reload}>Try again</AlertActionLink>}>{plan.cause}</Alert>;
    if (blocked && problems.length) {
      return (
        <Callout tone="bad" title="The check did not run. Fix these:">
          <List>{problems.map((p, i) => <ListItem key={i}><Button variant="link" isInline onClick={() => focusOn(p.focus)}>{p.text}</Button></ListItem>)}</List>
        </Callout>
      );
    }
    if (planned !== null) return <Callout tone="info" title="Changed since the last check. Press Check (dry run) again." />;
    return <Callout tone="info" title="Make a change, then press Check (dry run)." />;
  };

  const drifted = new Map(data.sync.driftedKeys.map((d) => [`${d.kind}:${d.key}`, d]));
  const compared = data.sync.state !== "unknown";
  const liveCell = (id: string, value: string | null) => {
    if (drifted.has(id)) return <><Label isCompact status="warning">drift</Label> <code>{value ?? "(none)"}</code></>;
    return <code>{compared && value !== null ? `✓ ${value}` : value ?? "—"}</code>;
  };
  // A key with no title of its own can be a label and an annotation (do-not-delete): its kind is in its name.
  const nameOf = (r: KeyRow) => (r.field ? r.title : `${r.kind} ${r.key}`);
  const changeCell = (r: KeyRow) => {
    const value = valueNow(r, draft);
    if (canChange && value === null && r.git !== null) {
      return (
        <Flex gap={{ default: "gapSm" }} alignItems={{ default: "alignItemsCenter" }}>
          <del><code>{r.git}</code></del><Small>removed</Small>
          <Button variant="link" isInline onClick={() => edit(r, r.git)} aria-label={`Undo the removal of ${nameOf(r)}`}>↺ Undo</Button>
        </Flex>
      );
    }
    const lock = <Small><LockIcon aria-hidden="true" /> {r.edit.reason ?? "Read only."}</Small>;
    // Design section 3, row 3 (#492 M2): a key that no rule admits may be removed, never set or changed.
    if (canChange && r.access === "remove") {
      return (
        <Stack>
          {lock}
          <FlexItem><Button variant="link" isInline onClick={() => edit(r, null)} aria-label={`Remove ${nameOf(r)}`}>Remove</Button></FlexItem>
        </Stack>
      );
    }
    if (!isEditable(r) || !canChange) return lock;
    const error = shownError(r);
    const id = inputId(r), name = r.field ? fieldName(r.field) : `Value of ${nameOf(r)}`;
    const onChange = (v: string) => edit(r, v);
    return (
      <Stack>
        <Flex gap={{ default: "gapSm" }} alignItems={{ default: "alignItemsCenter" }} flexWrap={{ default: "wrap" }}>
          <FlexItem>
            {r.field
              ? <FieldInput field={r.field} value={value ?? ""} error={error} describedBy={error ? `${id}-error` : ""} label={name} emptyOption={r.git === null} onChange={onChange} />
              : <TextInput id={id} value={value ?? ""} aria-label={name} validated={error ? "error" : "default"} aria-describedby={error ? `${id}-error` : undefined}
                spellCheck={false} autoComplete="off" onChange={(_, v) => onChange(v)} />}
          </FlexItem>
          {r.id in draft && <Label isCompact color="purple">changed</Label>}
          {r.edit.mode === "optional" && r.git !== null && <Button variant="link" isInline onClick={() => edit(r, null)} aria-label={`Remove ${nameOf(r)}`}>Remove</Button>}
        </Flex>
        {error && <FormHelperText><HelperText><HelperTextItem id={`${id}-error`} variant="error">{error}</HelperTextItem></HelperText></FormHelperText>}
      </Stack>
    );
  };
  const keyCell = (r: KeyRow) => (
    <Stack>
      <Flex gap={{ default: "gapXs" }} alignItems={{ default: "alignItemsCenter" }}>
        <b>{`${r.title}${r.field?.required ? " (required)" : ""}`}</b>
        {!isEditable(r) && <Label isCompact>fixed</Label>}
        {r.extra && <Label isCompact color="blue">additional</Label>}
        {r.edit.sensitive && <Label isCompact color="purple">sensitive</Label>}
      </Flex>
      <Small><code>{`${r.kind} ${r.key}`}</code></Small>
    </Stack>
  );
  const gitCell = (r: KeyRow) => (r.git === null && r.field?.required ? <Label isCompact status="warning">missing: required</Label> : <code>{r.git ?? "—"}</code>);
  // The expiry date is a system key, changed on its own routes; the read gives its reason (#528) while Git holds a date.
  const expiry = data.git?.edits.annotations[EXPIRES_AT];
  const expiresGit = git.annotation[EXPIRES_AT] ?? null, expiresLive = live.annotation[EXPIRES_AT] ?? null;

  return (
    <Stack hasGutter>
      <SyncStrip view={data} held={held} onReload={reload} onOpen={(id) => open("workflow", { request: id })} />
      {data.git === null && <Callout tone="warn" title="Git holds no folder for this namespace, so it cannot be changed here." />}
      <Grid hasGutter>
        <GridItem md={7}>
          <Panel>
            <Table aria-label={`Labels and annotations of ${ns}`} variant="compact" gridBreakPoint="grid-lg">
              <Thead><Tr><Th width={25}>Key</Th><Th width={20}>Git (desired)</Th><Th width={20}>Live (cluster)</Th><Th width={35}>Your change</Th></Tr></Thead>
              <Tbody>
                {rows.map((r) => (
                  <Tr key={r.id}>
                    <Td dataLabel="Key">{keyCell(r)}</Td>
                    <Td dataLabel="Git (desired)">{gitCell(r)}</Td>
                    <Td dataLabel="Live (cluster)">{liveCell(r.id, r.live)}</Td>
                    <Td dataLabel="Your change">{changeCell(r)}</Td>
                  </Tr>
                ))}
                {expiry && expiresGit !== null && (
                  <Tr>
                    <Td dataLabel="Key">{keyCell({ id: `annotation:${EXPIRES_AT}`, kind: "annotation", key: EXPIRES_AT, title: "Expires", edit: expiry, access: "locked", field: null, extra: false, git: expiresGit, live: expiresLive })}</Td>
                    <Td dataLabel="Git (desired)"><code>{expiresGit}</code></Td>
                    <Td dataLabel="Live (cluster)">{liveCell(`annotation:${EXPIRES_AT}`, expiresLive)}</Td>
                    <Td dataLabel="Your change"><Small><LockIcon aria-hidden="true" /> {expiry.reason}</Small></Td>
                  </Tr>
                )}
              </Tbody>
            </Table>
            {canChange && (
              <ExtraKeysSection form={form} rows={added} checks={result?.extras ?? {}} refused={{}} attempted={attempted} expanded={addOpen} onExpand={setAddOpen}
                onChange={(kind, next) => { setAdded((x) => ({ ...x, [kind]: next })); setDone(null); setNotSent(null); }} onAdd={addRow} title="Add labels and annotations (optional)" />
            )}
            {!canChange && data.git !== null && <Hint>{`Changing this namespace needs ${PATCH_NAMESPACE} in ${env}.`}</Hint>}
          </Panel>
        </GridItem>
        {canChange && (
          <GridItem md={5} className="cp-sticky">
            <Panel title="Your change">
              <Form noValidate onSubmit={onSubmit}>
                <List isPlain aria-label={planOk ? "The change, from the dry run" : "The change"}>
                  {planOk ? diffLines.map((l) => <Line key={`${l.kind}:${l.key}`} line={l} source={l.source} />)
                    : lines.map((l) => <Line key={`${l.kind}:${l.key}`} line={l} />)}
                  {(planOk ? diffLines : lines).length === 0 && <ListItem><Small>No change yet.</Small></ListItem>}
                </List>
                <FormGroup label="Justification (required)" fieldId="nsx-why">
                  <TextArea id="nsx-why" value={why} rows={2} placeholder="Why this change is needed" onChange={(_, v) => setWhy(v)} />
                </FormGroup>
                <div id="nsx-status">{status()}</div>
                <ActionGroup>
                  <Button variant="secondary" type="button" onClick={() => void onCheck()}>Check (dry run)</Button>
                  <Button variant="primary" type="submit" isAriaDisabled={!canSubmit} aria-describedby="nsx-status" isLoading={submit.state === "sending"}>Submit request</Button>
                </ActionGroup>
              </Form>
            </Panel>
          </GridItem>
        )}
      </Grid>
    </Stack>
  );
}
