// The New namespace tab: GET /api/v1/tiers, GET /api/v1/clusters and GET /api/v1/metadata-keys for the form, the dry run
// for the plan and its approval, then the create with an Idempotency-Key that the portal makes (#282). The labels and
// annotations are the instance's own keys, from its metadata-keys.yaml (#336). The form follows the mockup of #479
// (mockups/portal/new-namespace-479.html): the name with both ends locked, the team's default, the expiry date, the
// additional keys, a live preview, and Check (dry run) before Submit. MOCKUP-CONTRACT.md lists what differs, and why.
//
// The workflow, from the person's input to the API's answer:
//   1. Each change updates the form's state (typed values, the desired name, the extra rows, the date) and the preview.
//   2. CHECK_AFTER_MS later the fields are checked by the API's own rules (checkForm), each pattern off the page's thread.
//   3. Check (dry run) checks the form now; with no problem it plans the body (usePlan), else it lists the problems.
//   4. The plan's answer replaces the preview; Submit opens only for a passing plan of the form as it is now.
//   5. Submit sends that body with one Idempotency-Key, and a 202 opens the Workflow tab on the new request.
import {
  ActionGroup, Alert, AlertActionLink, Button, Checkbox, CodeBlock, CodeBlockCode, EmptyState, EmptyStateBody, Flex, Form, FormGroup, FormSection,
  FormSelect, FormSelectOption, Grid, GridItem, List, ListItem, Skeleton, Stack, TextArea
} from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useClusters, useMe, useMetadataKeys, usePlan, useSubmitNamespace, useTiers } from "../api/hooks";
import type { Cluster, CreateBody, Plan, TierCatalog } from "../api/hooks";
import type { ProblemItem } from "../api/problem";
import { Callout, Checks, Choices, Empty, Head, Hint, KV, Panel, Small } from "../components/ui";
import type { Check } from "../components/ui";
import { operatorIn, PROTECT_KEY, PROTECT_VALUE } from "./access";
import { ExpiryField } from "./ExpiryField";
import { extraInputId, ExtraKeysSection } from "./ExtraKeysSection";
import { isoDay, policyOf } from "./format";
import { Field, fieldName, MetadataSection } from "./MetadataFields";
import {
  bodyOf, checkAll, checkExtras, checkName, defaultSource, endValue, errorsByField, expiryInfo, expiryRulesOf, joinName, nameEnds, nameSuggestion,
  shownValues, valueKey
} from "./metadataForm";
import type { ExpiryInfo, ExtraCheck, ExtraRow, Kind, MetaField, MetaForm, Source } from "./metadataForm";
import { NamespaceNameField } from "./NamespaceNameField";
import { sharedPatternTest } from "./patterns";
import { capacityCheck, capacityLine, MARK, sentence } from "./plan";
import { planNamespaceFile, previewLines, previewYaml, sourceWords } from "./preview";
import type { TabProps } from "./route";

const ANY_REGION = "any";

interface Tier {
  name: string;
  cpu: string;
  memory: string;
  pods: string;
}

/**
 * The catalog's tiers for one environment. The contract types `environments` as open objects (TierCatalogView), so each
 * field is checked here. The custom tier takes its own sizes, which this form does not ask for, so it is not offered.
 */
function tiersOf(catalog: TierCatalog, env: string): Tier[] {
  const entry = catalog.environments[env] as { tiers?: unknown } | undefined;
  const list = Array.isArray(entry?.tiers) ? entry.tiers : [];
  return list.flatMap((raw) => {
    const t = raw as { name?: unknown; custom?: unknown; order?: unknown; quota?: Record<string, unknown> };
    if (typeof t.name !== "string" || t.custom === true) return [];
    const q = t.quota ?? {};
    return [{ name: t.name, order: typeof t.order === "number" ? t.order : 0, cpu: String(q["requests.cpu"] ?? "—"), memory: String(q["requests.memory"] ?? "—"), pods: String(q.pods ?? "—") }];
  }).sort((a, b) => a.order - b.order).map(({ name, cpu, memory, pods }) => ({ name, cpu, memory, pods }));
}

/** The folder that the plan writes: the longest path that every changed file shares. */
function folderOf(plan: Plan): string {
  const paths = Object.keys(plan.changes);
  if (!paths.length) return "—";
  const parts = paths.map((p) => p.split("/").slice(0, -1));
  const shared: string[] = [];
  for (let k = 0; parts.every((p) => k < p.length && p[k] === parts[0][k]); k++) shared.push(parts[0][k]);
  return `${shared.join("/")}/`;
}

/** The approval of the plan: who must approve, and why. The API decides it (docs/02); the page only says it. */
function approvalCard(plan: Plan, env: string): { title: string; detail: string; rule: string } {
  const a = plan.approval;
  const need = a.slots.reduce((n, s) => n + s.count, 0);
  if (a.auto || need === 0) {
    const title = a.auto && a.auto !== "none-required" ? `Auto-approved by ${policyOf(a.auto)}` : "No approval needed";
    return { title, detail: sentence(a.reasons), rule: `${a.rule} · 0 of 0 (auto)` };
  }
  const groups = a.slots.map((s) => s.group).join(" + ");
  const self = a.selfApproval ? `Self-approval is allowed in ${env}.` : "The requester cannot approve their own request.";
  return {
    title: `${need} approval${need > 1 ? "s" : ""} in cmapi from ${groups}`,
    detail: `${sentence(a.reasons)} ${self}`.trim(),
    rule: `${a.rule} · ${a.slots.map((s) => `${s.count} of ${s.group}`).join(" + ")}`
  };
}

/** How long the form waits after the last keystroke before it checks the fields (design B of #336, D7). */
const CHECK_AFTER_MS = 150;

/** The refusal of a dry run or a submit, for the field errors and the summary. */
interface Refusal { code: string; detail: string; errors: ProblemItem[] }

/** The result of the form's own checks: each field's problem by id, the name's, and each extra table's. */
interface FormCheck { fields: Record<string, string | null>; name: string | null; extras: Partial<Record<Kind, ExtraCheck>> }

/** One problem that the form itself sees, for the list of a check that did not run, with the id of its control. */
interface Problem { text: string; focus: string }

/** The inputs of one run of the form's checks. */
interface CheckInput {
  form: MetaForm;
  typed: Record<string, string>;
  shown: Record<string, string>;
  nsName: string;
  name: { start: string | null; desired: string; end: string | null };
  extras: Record<Kind, ExtraRow[]>;
}

/**
 * The form's own checks, by the API's rules: each field (checkAll), the name (checkName) and each extra table
 * (checkExtras). One fault, one error, as validate() reports it (_without_copied_faults): an unedited default that copies
 * a refused source has no error of its own.
 */
async function checkForm(input: CheckInput): Promise<FormCheck> {
  const fields = await checkAll(input.form, input.shown, input.nsName, sharedPatternTest, input.typed);
  for (const f of input.form.fields) {
    const source = defaultSource(input.form, f);
    if (source && !(valueKey(f) in input.typed) && fields[source.id]) fields[f.id] = null;
  }
  const extras: Partial<Record<Kind, ExtraCheck>> = {};
  for (const kind of ["label", "annotation"] as const) {
    if (input.form.otherKeys[kind]) extras[kind] = await checkExtras(input.form, kind, input.extras[kind], sharedPatternTest);
  }
  return { fields, name: checkName(input.name.start, input.name.desired, input.name.end), extras };
}

/** The problems of the extra tables, each with the input it names. */
function extraProblems(checked: FormCheck, extras: Record<Kind, ExtraRow[]>): Problem[] {
  const out: Problem[] = [];
  for (const kind of ["label", "annotation"] as const) {
    const check = checked.extras[kind];
    if (!check) continue;
    extras[kind].forEach((r, i) => {
      const p = check.rows[r.id];
      const row = `Additional ${kind} ${i + 1}${r.key ? ` ${r.key}` : ""}`;
      if (p?.key) out.push({ text: `${row}: ${p.key}`, focus: extraInputId(kind, r.id, "key") });
      if (p?.value) out.push({ text: `${row}: ${p.value}`, focus: extraInputId(kind, r.id, "value") });
    });
    const last = extras[kind].at(-1);
    for (const t of check.table) out.push({ text: t, focus: last ? extraInputId(kind, last.id, "key") : "ns-extra-toggle" });
  }
  return out;
}

/** Every problem of a check, in the order of the form, with the id of the control that each one names. */
function problemsOf(form: MetaForm, checked: FormCheck, extras: Record<Kind, ExtraRow[]>, expiry: ExpiryInfo | null, start: MetaField | null): Problem[] {
  const out: Problem[] = [];
  if (start && checked.fields[start.id]) out.push({ text: `${fieldName(start)}: ${checked.fields[start.id]}`, focus: start.id });
  if (checked.name) out.push({ text: `Namespace: ${checked.name}`, focus: "ns-name" });
  for (const f of form.fields) if (f !== start && checked.fields[f.id]) out.push({ text: `${fieldName(f)}: ${checked.fields[f.id]}`, focus: f.id });
  if (expiry?.state === "bad") out.push({ text: `Expires: ${expiry.error}`, focus: "ns-exp" });
  return [...out, ...extraProblems(checked, extras)];
}

/** The codes of a refusal of the namespace name itself (core/naming.py, the create's checks): shown on the name (P8). */
const NAME_REFUSALS = new Set(["invalid-namespace-name", "reserved-namespace", "namespace-exists", "namespace-exists-unmanaged"]);

/** The input of the extra row that a refusal's item names by its key (an extra key has no field above), or null. */
function rowInputOf(item: ProblemItem, extras: Record<Kind, ExtraRow[]>): string | null {
  for (const kind of ["label", "annotation"] as const) {
    if (item.kind !== undefined && item.kind !== kind) continue;
    const row = extras[kind].find((r) => r.key === item.key);
    if (row) return extraInputId(kind, row.id, item.code === "invalid_value" ? "value" : "key");
  }
  return null;
}

/** Each input's own message for the browser's native validation, so Check stops on it and focuses the first one. */
function setValidity(form: HTMLFormElement | null, fields: MetaField[], errors: Record<string, string | null>, name: string | null) {
  for (const f of fields) {
    const el = form?.querySelector<HTMLInputElement | HTMLSelectElement>(`#${f.id}`);
    el?.setCustomValidity(f.derivedFrom === null ? errors[f.id] ?? "" : "");
  }
  form?.querySelector<HTMLInputElement>("#ns-name")?.setCustomValidity(name ?? "");
}

export function NewNamespaceTab({ config, open }: TabProps) {
  const today = isoDay(new Date());
  const me = useMe();
  const clusters = useClusters();
  const rules = useMetadataKeys();
  // No choice yet: the first environment of this instance that has a cluster to write to.
  const [pickedEnv, setEnv] = useState("");
  const writable = clusters.state === "ok" ? clusters.data.items.filter((c) => c.writes) : null;
  const env = pickedEnv || (writable && (config.environments.find((e) => writable.some((c) => c.environment === e)) ?? config.environments[0])) || "";
  const tiers = useTiers(env);
  const [tier, setTier] = useState("medium");
  const [region, setRegion] = useState(ANY_REGION);
  const [chosen, setChosen] = useState("");
  // The part of the name that the person types: the middle between the locked ends, or the whole name without them.
  const [desired, setDesired] = useState("");
  // What the person typed in each label and annotation field, keyed by kind and key (metadataForm.valueKey), so a value
  // stays with its key when the rules change while the form is open. A default field is edited once its key is here.
  const [typed, setTyped] = useState<Record<string, string>>({});
  // The additional keys: closed and empty by default (P9). Each row has its own id, so a removal keeps the others' state.
  const [extras, setExtras] = useState<Record<Kind, ExtraRow[]>>({ label: [], annotation: [] });
  const [extraOpen, setExtraOpen] = useState(false);
  const rowIds = useRef(0);
  const [expires, setExpires] = useState("");
  const [protect, setProtect] = useState(false);
  const [why, setWhy] = useState("");
  // The body that the last Check planned, and the form's draft then. It stays while the form changes: the status then
  // says that the form changed.
  const [planned, setPlanned] = useState<{ cluster: string; body: CreateBody; draft: string } | null>(null);
  // The last Check found problems in the form itself and sent nothing: the status lists them, as they are now.
  const [blocked, setBlocked] = useState(false);
  // The body that the last Submit sent, so that its refusal shows on the fields only while the form is that body.
  const [submitted, setSubmitted] = useState<string | null>(null);
  // One key for each request that this form sends (#282). Submitting the same form again after a refusal or a lost answer
  // sends the same key, so the API answers with the first request and never makes two. A changed form is another request:
  // the API refuses an old key with another body (409 idempotency-replay, docs/04 "Rules for each call"), so it gets a new
  // key. Leaving the tab ends the form: the next one starts with none.
  const sent = useRef<{ key: string; request: string } | null>(null);
  const keyFor = (clusterId: string, value: CreateBody): string => {
    const request = JSON.stringify([clusterId, value]);
    if (sent.current?.request !== request) sent.current = { key: crypto.randomUUID(), request };
    return sent.current.key;
  };
  const submit = useSubmitNamespace();
  const plan = usePlan(planned?.cluster ?? "", planned?.body ?? null);
  const formRef = useRef<HTMLFormElement>(null);
  const summaryRef = useRef<HTMLDivElement>(null);

  const form: MetaForm | null = rules.state === "ok" ? rules.data.form : null;
  const fingerprint = rules.state === "ok" ? rules.data.fingerprint : null;

  const offered = tiers.state === "ok" ? tiersOf(tiers.data, env) : [];
  const current = offered.find((t) => t.name === tier) ?? offered[0];
  const inEnv = (writable ?? []).filter((c) => c.environment === env);
  // A region that this environment's clusters lack (picked in another environment, or gone in a refetch) filters nothing.
  const activeRegion = inEnv.some((c) => c.labels.region === region) ? region : ANY_REGION;
  const candidates = inEnv.filter((c) => activeRegion === ANY_REGION || c.labels.region === activeRegion);
  const cluster: Cluster | undefined = candidates.find((c) => c.clusterId === chosen) ?? candidates[0];
  // The name: its ends come from the keys that make them (P2), and the person types the rest.
  const ends = form ? nameEnds(form) : { start: null, end: null };
  const place: Record<Source, string> = { namespace: "", environment: env, cluster: cluster?.clusterId ?? "", instance: me.state === "ok" ? me.data.instance : "" };
  // The ends read the values before the name is known; a default copied from the name itself is read after it, below.
  const early = form ? shownValues(form, typed, place) : typed;
  const startValue = endValue(ends.start, early, place), endPart = endValue(ends.end, early, place);
  const hasEnds = startValue !== null || endPart !== null;
  const nsName = hasEnds ? joinName(startValue, desired, endPart) : desired || (form ? nameSuggestion(form, early, env) : "");
  // What the page shows for the name: an end or a middle not typed yet is "…", as in the mockup; the body sends nsName.
  const shownName = hasEnds ? joinName(startValue === null ? null : startValue || "…", desired || "…", endPart === null ? null : endPart || "…") : nsName;
  const target: Record<Source, string> = { ...place, namespace: shownName };
  const shown = form ? shownValues(form, typed, { ...place, namespace: nsName }) : typed;
  const expiryRules = form ? expiryRulesOf(form, env) : null;
  const expiry = expiryRules ? expiryInfo(expires, today, expiryRules) : null;

  // The fields' own checks: CHECK_AFTER_MS after the last change, each pattern in a worker with a time limit (patterns.ts).
  // A result is of the inputs it was run on; it shows only while the form still has them.
  const input: CheckInput | null = form ? { form, typed, shown, nsName, name: { start: startValue, desired: hasEnds ? desired : nsName, end: endPart }, extras } : null;
  const inputs = JSON.stringify([fingerprint, typed, shown, nsName, desired, extras]);
  const [checked, setChecked] = useState<{ inputs: string; result: FormCheck } | null>(null);
  // WAI-ARIA 1.2, aria-invalid: "if the user has not attempted to submit the form, authors SHOULD NOT set the aria-invalid
  // attribute on required widgets simply because the user has not yet entered data". An empty required field shows its
  // error after the first Check; until then the browser's own check (required) still stops it.
  const [attempted, setAttempted] = useState(false);
  const result: FormCheck | null = checked?.inputs === inputs ? checked.result : null;
  /** The checks of the form as this render has it: the last result when it is of these inputs, else a new run. */
  const checkNow = async (): Promise<FormCheck | null> => {
    if (!input) return null;
    if (result) return result;
    const fresh = await checkForm(input);
    setChecked({ inputs, result: fresh });
    return fresh;
  };
  // `inputs` is the text of the rules, the values, the name and the rows, so it changes exactly when one of them does.
  useEffect(() => {
    if (!input) return;
    let live = true;
    const timer = setTimeout(() => { void checkForm(input).then((r) => { if (live) setChecked({ inputs, result: r }); }); }, CHECK_AFTER_MS);
    return () => { live = false; clearTimeout(timer); };
  }, [inputs]);
  useEffect(() => { if (form) setValidity(formRef.current, form.fields, result?.fields ?? {}, result?.name ?? null); });

  // The rules of this instance changed after the form loaded: the fields follow the new rules, a removed key's value is
  // dropped, and a warning says so (the conflict state).
  const firstRules = useRef<string | null>(null);
  useEffect(() => {
    if (!fingerprint || !form) return;
    if (firstRules.current === null) firstRules.current = fingerprint;
    const kept = new Set(form.fields.map(valueKey));
    setTyped((v) => (Object.keys(v).every((k) => kept.has(k)) ? v : Object.fromEntries(Object.entries(v).filter(([k]) => kept.has(k)))));
    // The rows of a table that the new rules no longer offer go too: hidden, they could not be removed.
    setExtras((x) => (x.label.length && !form.otherKeys.label) || (x.annotation.length && !form.otherKeys.annotation)
      ? { label: form.otherKeys.label ? x.label : [], annotation: form.otherKeys.annotation ? x.annotation : [] } : x);
  }, [fingerprint]);
  const rulesChanged = firstRules.current !== null && fingerprint !== null && fingerprint !== firstRules.current;

  const setValue = (f: MetaField, value: string) => setTyped({ ...typed, [valueKey(f)]: value });
  const head = <Head title="New namespace" lede="Fill in the fields, then check the request. The preview shows exactly what will be created; Submit opens once the check passes." />;

  // An operator's protection box, in this environment, where the instance's rules make the label operator-only (#366).
  // Shown or not, the API decides on the token: a requester's body with the label gets 403.
  const canProtect = me.state === "ok" && operatorIn(me.data, env) && !!form?.operatorOnlyLabels.includes(PROTECT_KEY);
  const metadata = form ? bodyOf(form, typed, extras) : { labels: {}, annotations: {} };
  const body: CreateBody = {
    namespace: nsName,
    tier: current?.name ?? tier,
    ...metadata,
    ...(canProtect && protect ? { labels: { ...metadata.labels, [PROTECT_KEY]: PROTECT_VALUE } } : {}),
    justification: why || null,
    ...(expiryRules && expires ? { expiresAt: expires } : {})
  };
  // The plan on the page is of this form: same cluster, same body, same draft. A refetch of the clusters, tiers or rules can
  // change the form without an edit, so the bodies are compared; an edit can leave the body as it was (a row with no key
  // yet), so the drafts are compared too (P7: Submit is off again after any change).
  const draft = JSON.stringify([typed, extras]);
  const planIsOfForm = planned !== null && planned.cluster === cluster?.clusterId && JSON.stringify(planned.body) === JSON.stringify(body) && planned.draft === draft;
  const refusal: Refusal | null = plan.state === "refused" && planIsOfForm ? plan
    : submit.state === "refused" && submitted === JSON.stringify(body) ? submit : null;
  const mapped = form && refusal ? errorsByField(refusal.errors, form) : null;
  // P8 where the form has no field for it: an extra row's key or value, by the id of its input.
  const refusedAt: Record<string, string> = {};
  for (const { item, field } of mapped?.items ?? []) {
    const id = field ? null : rowInputOf(item, extras);
    if (id) refusedAt[id] = item.detail ?? item.code;
  }
  const refusalKey = refusal ? JSON.stringify([refusal.code, refusal.errors]) : "";
  useEffect(() => {
    if (!refusalKey) return;
    if (Object.keys(refusedAt).length) setExtraOpen(true);  // a refused row shows in the open section
    summaryRef.current?.focus();                         // the summary of a refusal takes the focus (WCAG 2.2, 3.3.1)
    if (mapped?.unknownKey) rules.reload();              // a key that the form does not show: the rules changed
  }, [refusalKey]);

  const forbidden = [clusters, tiers, rules].find((r) => r.state === "forbidden");
  if (forbidden?.state === "forbidden") {
    return (
      <Stack hasGutter>
        {head}
        <EmptyState titleText="You do not have permission to request a namespace." headingLevel="h2" icon={LockIcon}>
          <EmptyStateBody>{forbidden.detail}</EmptyStateBody>
        </EmptyState>
      </Stack>
    );
  }
  const failed = [clusters, tiers, rules].find((r) => r.state === "error");
  if (failed?.state === "error") {
    return (
      <Stack hasGutter>
        {head}
        <Alert variant="danger" isInline title="The form did not load." actionLinks={<AlertActionLink onClick={() => { clusters.reload(); tiers.reload(); rules.reload(); }}>Try again</AlertActionLink>}>
          {failed.cause}
        </Alert>
      </Stack>
    );
  }
  if (clusters.state === "ok" && !env) return <Stack hasGutter>{head}<Empty>config.json names no environment for this instance.</Empty></Stack>;
  if (clusters.state !== "ok" || tiers.state !== "ok" || !form || !input) {
    return <Stack hasGutter>{head}<span role="status">Loading the form…</span><Skeleton /><Skeleton /><Skeleton /></Stack>;
  }

  const regions = [...new Set(inEnv.map((c) => c.labels.region).filter((r): r is string => Boolean(r)))].sort();
  const shownError = (f: MetaField): string | null =>
    !attempted && (shown[valueKey(f)] ?? "") === "" ? null : result?.fields[f.id] ?? null;
  const fieldErrors: Record<string, string | null | undefined> = Object.fromEntries(
    form.fields.map((f) => [f.id, shownError(f) ?? mapped?.byField[f.id] ?? null]));
  const nameRefused = refusal && NAME_REFUSALS.has(refusal.code) ? refusal.detail : null;
  const nameError = !attempted && desired === "" ? null : result?.name ?? nameRefused;
  const planOk = plan.state === "ok" && planIsOfForm ? plan.data : null;
  const problems = result ? problemsOf(form, result, extras, expiry, ends.start) : [];
  const canSubmit = planOk !== null && submit.state !== "sending" && !!cluster;

  const focusOn = (id: string) => {
    if (id.startsWith("ns-x")) setExtraOpen(true);
    requestAnimationFrame(() => document.getElementById(id)?.focus());
  };

  /** Check (dry run): the form's own checks first, then the browser's (required, the address); then the dry run. */
  const onCheck = async () => {
    if (!cluster) return;
    setAttempted(true);
    const found = await checkNow();
    if (!found) return;
    setValidity(formRef.current, form.fields, found.fields, found.name);
    const list = problemsOf(form, found, extras, expiry, ends.start);
    if (list.some((p) => p.focus.startsWith("ns-x"))) {
      setExtraOpen(true);
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    if (list.length || !(formRef.current?.reportValidity() ?? false)) {
      setBlocked(true);
      return;
    }
    setBlocked(false);
    // Check on a form that has its plan asks cmapi again: the answer can change (capacity, a namespace made since).
    if (planIsOfForm) plan.reload();
    else setPlanned({ cluster: cluster.clusterId, body, draft });
  };
  /** Submit: only the plan on the page, of the form as it is now (P7). Nothing goes straight to submit. */
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !planned) return;
    setSubmitted(JSON.stringify(planned.body));
    // The tab ends on a 202: the Workflow tab follows the new request, as the mockup's Submit opens its workflow.
    submit.submit(planned.cluster, planned.body, keyFor(planned.cluster, planned.body)).then((request) => open("workflow", { request: request.requestId }), () => undefined);
  };
  const addRow = (kind: Kind) => {
    const id = ++rowIds.current;
    setExtras((x) => ({ ...x, [kind]: [...x[kind], { id, key: "", value: "" }] }));
    requestAnimationFrame(() => document.getElementById(extraInputId(kind, id, "key"))?.focus());
  };

  const appr = planOk ? approvalCard(planOk, env) : null;
  const beyond = expiry?.state === "date" && expiry.beyond;
  const checks: Check[] = planOk && appr ? [
    { s: "pass", mark: MARK.pass, main: "Environment served", note: `${env} in [${config.environments.join(", ")}]` },
    capacityCheck(planOk),
    {
      // Past maxLifetimeDays a date is allowed with one more approval (design P12): a warning, never a failure.
      s: beyond ? "warn" : "pass", mark: beyond ? MARK.warn : MARK.pass, main: "Expiry",
      note: !expiryRules ? "none: off in this environment" : expiry?.state === "date"
        ? `${expiry.date}, ${expiry.days} days (limit ${expiryRules.maxLifetimeDays}${beyond ? ": one more approval" : ""})` : "none: permanent"
    },
    { s: planOk.approval.auto ? "pass" : "warn", mark: planOk.approval.auto ? MARK.pass : MARK.warn, main: "Approval", note: appr.rule }
  ] : [];
  // The error summary of a refusal: each item, and a link to the field that it names.
  const summary = mapped && mapped.items.length > 0 && (
    <List>
      {mapped.items.map(({ item, field, text }, i) => {
        const id = field?.id ?? rowInputOf(item, extras);
        return <ListItem key={i}>{id ? <Button variant="link" isInline onClick={() => focusOn(id)}>{text}</Button> : text}</ListItem>;
      })}
    </List>
  );
  const stale = planned !== null && !planIsOfForm;
  const lines = previewLines({ form, typed, shown, target, extras, expiresAt: expiry?.state === "date" ? expiry.date : null,
    protect: canProtect && protect ? { key: PROTECT_KEY, value: PROTECT_VALUE } : null });
  const file = planOk ? planNamespaceFile(planOk.files) : null;
  const expiresText = !expiryRules ? "never (expiration off here)" : expiry?.state === "date" ? `${expiry.date} (in ${expiry.days} days)`
    : expiry?.state === "bad" ? "—" : "never (permanent)";

  /** The status under the preview: what the last Check found, that the form changed since, or that it was not checked. */
  const status = () => {
    if (planIsOfForm && plan.state === "sending") return <span role="status">Checking with cmapi…</span>;
    if (planOk && appr) {
      const set = planOk.metadata ? [...Object.entries(planOk.metadata.labels), ...Object.entries(planOk.metadata.annotations)] : [];
      return (
        <Callout tone="ok" title="The check passed (dry run, 200). Nothing is written yet.">
          <Checks items={checks} />
          <Small>{capacityLine(planOk)}</Small>
          {set.length > 0 && <>
            <div>cmapi will set:</div>
            <List>{set.map(([k, v], i) => <ListItem key={i}><code>{`${k} = ${v.value}`}</code> <Small>{sourceWords(v.source)}</Small></ListItem>)}</List>
          </>}
          <div>{`${appr.title}. ${appr.detail}`}</div>
          <Small>{`Plan hash ${planOk.planHash.slice(0, 4)}…`}</Small>
        </Callout>
      );
    }
    if (planIsOfForm && plan.state === "refused") return <Callout tone="bad" title={`The check failed: ${plan.code}`}>{plan.detail}{summary}</Callout>;
    if (planIsOfForm && plan.state === "error") {
      return <Alert variant="danger" isInline title="The dry run did not complete." actionLinks={<AlertActionLink onClick={plan.reload}>Try again</AlertActionLink>}>{plan.cause}</Alert>;
    }
    if (blocked && problems.length) {
      return (
        <Callout tone="bad" title="The check did not run. Fix these:">
          <List>{problems.map((p, i) => <ListItem key={i}><Button variant="link" isInline onClick={() => focusOn(p.focus)}>{p.text}</Button></ListItem>)}</List>
        </Callout>
      );
    }
    if (stale || blocked) return <Callout tone="info" title="Changed since the last check. Press Check (dry run) again." />;
    return <Callout tone="info" title="Not checked yet. Press Check (dry run) to ask cmapi whether this request passes." />;
  };

  return (
    <Stack hasGutter>
      {head}
      <Grid hasGutter>
        <GridItem md={7}>
          <Panel>
            <Form noValidate={false} onSubmit={onSubmit} ref={formRef}>
              <FormSection title="Where" titleElement="h3">
                <FormGroup label="Environment" role="group" fieldId="ns-env">
                  <Choices label="Environment" options={config.environments.map((e) => ({ label: e, on: e === env, pick: () => { setEnv(e); setChosen(""); } }))} />
                  <Hint>This is the {config.displayName} portal: it serves {config.environments.join(", ")} only.</Hint>
                  {config.otherInstances.length > 0 && (
                    <Flex gap={{ default: "gapMd" }}>
                      {config.otherInstances.map((x) => <Small key={x.name}>{x.environments.join(", ")} → <a href={x.url}>{`${x.name} portal`}</a></Small>)}
                    </Flex>
                  )}
                </FormGroup>
                <Grid hasGutter>
                  <GridItem md={6}>
                    <FormGroup label="Region" fieldId="ns-region">
                      <FormSelect id="ns-region" value={activeRegion} aria-describedby="ns-region-help" onChange={(_, v) => { setRegion(v); setChosen(""); }}>
                        {regions.map((r) => <FormSelectOption key={r} value={r} label={r} />)}
                        <FormSelectOption value={ANY_REGION} label="Any region" />
                      </FormSelect>
                      <Hint id="ns-region-help">From clusters.yaml metadata.</Hint>
                    </FormGroup>
                  </GridItem>
                  <GridItem md={6}>
                    <FormGroup label="Cluster" fieldId="ns-cluster">
                      <FormSelect id="ns-cluster" value={cluster?.clusterId ?? ""} isDisabled={!candidates.length} aria-describedby="ns-cluster-help" onChange={(_, v) => setChosen(v)}>
                        {candidates.map((c) => <FormSelectOption key={c.clusterId} value={c.clusterId} label={`${c.clusterId} (${c.environment})`} />)}
                        {!candidates.length && <FormSelectOption value="" label="—" />}
                      </FormSelect>
                      <Hint id="ns-cluster-help">{candidates.length ? `The ${env} clusters that take writes, from GET /api/v1/clusters. Placement is not on the API yet (#303).` : `No ${env} cluster takes writes on this instance.`}</Hint>
                    </FormGroup>
                  </GridItem>
                </Grid>
                <FormGroup label="Tier" role="group" fieldId="ns-tier">
                  <Choices label="Tier" options={offered.map((t) => ({ label: t.name, sub: `${t.cpu} cores · ${t.memory}`, on: t.name === current?.name, pick: () => setTier(t.name) }))} />
                  <Hint>cmapi writes the tier's ResourceQuota and LimitRange (config/tiers.yaml) into the namespace folder.</Hint>
                </FormGroup>
              </FormSection>
              {rulesChanged && <Alert variant="warning" isInline title="The label and annotation rules of this instance changed. Check the fields below." />}
              <FormSection title="Name" titleElement="h3">
                {ends.start && ends.start.derivedFrom === null && (
                  <Field field={ends.start} value={shown[valueKey(ends.start)] ?? ""} error={fieldErrors[ends.start.id]} target={target} onChange={(v) => setValue(ends.start!, v)} />
                )}
                <NamespaceNameField start={startValue === null ? null : ends.start} end={endPart === null ? null : ends.end} startValue={startValue} endValue={endPart} desired={hasEnds ? desired : nsName}
                  error={nameError} onChange={setDesired} />
              </FormSection>
              {(["label", "annotation"] as const).map((kind) => (
                <MetadataSection key={kind} kind={kind} fields={form.fields} values={shown} typed={typed} errors={fieldErrors} target={target}
                  skip={ends.start?.derivedFrom === null ? ends.start : null} sourceOf={(f) => defaultSource(form, f)} onChange={setValue} />
              ))}
              {me.state === "ok" && <Hint>{`Requested by ${me.data.username} (${me.data.identity.email ?? "no email"}), from your sign-in.`}</Hint>}
              <FormSection title="Expiration (optional)" titleElement="h3">
                <ExpiryField rules={form.expiration[env]} value={expires} today={today} refused={refusal?.code.startsWith("expiration-") ? refusal.detail : null} onChange={setExpires} />
              </FormSection>
              {canProtect && (
                <FormGroup label="Deletion protection" fieldId="ns-protect">
                  <Checkbox id="ns-protect" label="Protect from deletion" isChecked={protect} aria-describedby="ns-protect-help" onChange={(_, v) => setProtect(v)} />
                  <Hint id="ns-protect-help">{`Operators only. Adds ${PROTECT_KEY}=${PROTECT_VALUE}: cmapi refuses a delete request for this namespace until an operator removes it.${protect && expiry?.state === "date" ? ` The delete after ${expiry.date} and its grace will be held while it is protected.` : ""}`}</Hint>
                </FormGroup>
              )}
              <FormSection title="Why" titleElement="h3">
                <FormGroup label="Justification" fieldId="ns-why">
                  <TextArea id="ns-why" value={why} onChange={(_, v) => setWhy(v)} />
                </FormGroup>
              </FormSection>
              <ExtraKeysSection form={form} rows={extras} checks={result?.extras ?? {}} refused={refusedAt} attempted={attempted} expanded={extraOpen} onExpand={setExtraOpen}
                onChange={(kind, rows) => setExtras((x) => ({ ...x, [kind]: rows }))} onAdd={addRow} />
              <ActionGroup>
                <Button variant="secondary" type="button" isDisabled={!cluster} onClick={() => void onCheck()}>Check (dry run)</Button>
                <Button variant="primary" type="submit" isAriaDisabled={!canSubmit} aria-describedby="ns-status" isLoading={submit.state === "sending"}>Submit request</Button>
              </ActionGroup>
            </Form>
          </Panel>
        </GridItem>
        <GridItem md={5} className="cp-sticky">
          <Panel title="Preview">
            <Small>What will be created. It updates as you type.</Small>
            <KV rows={[
              { k: "Namespace", v: <code>{shownName || "—"}</code> },
              { k: "Cluster", v: cluster ? `${cluster.clusterId} (${env})` : "—" },
              { k: "Expires", v: expiresText },
              { k: "Quota", v: current ? `${current.name}: ${current.cpu} cores · ${current.memory} · ${current.pods} pods` : "—" },
              { k: "Approval", v: appr ? appr.rule : "Check (dry run) asks cmapi which approval applies." },
              ...(planOk ? [{ k: "Lands in Git", v: folderOf(planOk) }] : [])
            ]} />
            {file && <Small>{`From the dry run: ${file.path}`}</Small>}
            <CodeBlock><CodeBlockCode className="cp-pre-line">{file ? file.text : previewYaml(shownName, lines)}</CodeBlockCode></CodeBlock>
            <div ref={summaryRef} tabIndex={-1} id="ns-status">
              {status()}
              {submit.state === "refused" && <Callout tone="bad" title="Not submitted">{`${submit.code}: ${submit.detail}`}{refusal === submit && summary}</Callout>}
              {submit.state === "error" && <Callout tone="bad" title="Not submitted">{`${submit.cause} Submit again: the same request is sent, and the API makes it at most once.`}</Callout>}
            </div>
          </Panel>
        </GridItem>
      </Grid>
    </Stack>
  );
}
