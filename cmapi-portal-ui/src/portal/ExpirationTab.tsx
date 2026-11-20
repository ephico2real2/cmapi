// The Expiration tab on GET /api/v1/expirations, with the expiry changes as :extend, :set and :makePermanent: the dry run
// first, then the change that was planned, with If-Match and an Idempotency-Key. The words are the mockup's
// (mockups/portal/Main.dc.html, isExpiration and expirationView()). MOCKUP-CONTRACT.md lists what differs, and why.
import { ActionGroup, Alert, AlertActionLink, Button, EmptyState, EmptyStateBody, Flex, Form, FormGroup, Grid, GridItem, SearchInput, Skeleton, Stack, TextInput } from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useExpirations, useExpiryPlan, useMe, useNamespace, useSubmitExpiry } from "../api/hooks";
import type { ChangeRequest, ExpirationPage, ExpirationRow, ExpirationsQuery, ExpiryChange, Outcome, Plan, PlannedExpiry } from "../api/hooks";
import { PERMISSION } from "../api/permissions.generated";
import { Callout, Checks, Choices, Code, DataTable, Empty, Filter, Head, KV, Pager, Panel, Pill, Small } from "../components/ui";
import type { Check, Choice } from "../components/ui";
import { grantsIn } from "./access";
import { countsOf, dayName, policyOf } from "./format";
import { MARK, sentence } from "./plan";
import type { TabProps } from "./route";

type Rules = ExpirationPage["rules"][string];
type StateId = NonNullable<ExpirationsQuery["state"]>;

/** The mockup's state chips (STATES of expirationView()), each the API's `state`, and "All" with none. */
const STATES = [["attention", "Needs action"], ["expiring", "Expiring ≤ 14 d"], ["grace", "In grace"], ["pending_delete", "Pending delete"],
  ["active", "Active"], ["permanent", "Permanent"]] as const;
/** The mockup's EXP_STATE: the word and the tone of each state. */
const STATE_PILL: Record<ExpirationRow["state"], [string, string]> = {
  grace: ["In grace", "bad"], expiring: ["Expiring", "warn"], pending_delete: ["Pending delete", "warn"], active: ["Active", "info"], permanent: ["Permanent", "ok"]
};
const LIMIT = 25;
const SEARCH_DELAY_MS = 300;
/** The answers that say the etag of a change is not the folder's now (docs/04, If-Match): read the namespace again. */
const PRECONDITION = new Set(["precondition-failed", "precondition-required"]);
const outdated = (o: Outcome<unknown>): boolean => o.state === "refused" && PRECONDITION.has(o.code);
const EXTEND = PERMISSION["POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:extend"];

const keyOf = (r: Pick<ExpirationRow, "clusterId" | "name">): string => `${r.clusterId}/${r.name}`;
const STATE_IDS: readonly string[] = STATES.map(([id]) => id);
/** A day as ISO text, `days` after the ISO day `from`, in UTC. */
const plusDays = (from: string, days: number): string => new Date(Date.parse(from) + days * 864e5).toISOString().slice(0, 10);
const between = (from: string, to: string): number => Math.round((Date.parse(to) - Date.parse(from)) / 864e5);

/** "-3 (grace 4 left)", in the mockup's form; past grace, the grace is over. */
function daysText(r: ExpirationRow, rules: Rules | undefined): string {
  if (r.daysLeft === null || r.daysLeft === undefined) return "—";
  if (r.daysLeft >= 0) return String(r.daysLeft);
  return r.state === "grace" && rules ? `${r.daysLeft} (grace ${rules.graceDays + r.daysLeft} left)` : `${r.daysLeft} (grace over)`;
}

export function ExpirationTab({ config, params, setParams, open }: TabProps) {
  const me = useMe();
  // The view of the address: the state chip (the mockup starts on "Needs action"), the env, the search and the namespace.
  const raw = params.get("state");
  const state = (raw === null ? "attention" : raw === "all" ? "" : STATE_IDS.includes(raw) ? raw : "attention") as StateId | "";
  const env = config.environments.includes(params.get("env") ?? "") ? params.get("env")! : "";
  const applied = params.get("q") ?? "";
  const chosen = params.get("ns") ?? "";
  // A cursor belongs to one set of filters, so it lives here and not in the address.
  const [cursor, setCursor] = useState<string | null>(null);
  const lastShown = useRef<ExpirationRow | null>(null);

  const view = { state: state === "" ? "all" : state, env, q: applied, ns: chosen };
  const apply = (next: Partial<typeof view>) => {
    setCursor(null);
    const merged = { ...view, ...next };
    setParams({ ...merged, state: merged.state === "attention" ? "" : merged.state });
  };

  const filters: ExpirationsQuery = {};
  if (applied) filters.q = applied;
  if (env) filters.env = env;
  const query: ExpirationsQuery = { ...filters, limit: LIMIT };
  if (state) query.state = state;
  if (cursor) query.cursor = cursor;
  const result = useExpirations(query);
  // Every namespace in scope, with no filter (the heading), and the rows of the filters without the state chip (All).
  const scope = useExpirations({ limit: LIMIT });
  const unstated = useExpirations({ ...filters, limit: LIMIT });

  const scoped = scope.state === "ok" ? scope.data : null;
  const never = scoped !== null && Object.keys(scoped.rules).length === 0;
  const lede = never
    ? "Expiration is optional for rnd, dev, qa and uat namespaces, and never applies in prod."
    : ledeOf(config.instance, scoped ? Object.values(scoped.rules)[0] : undefined);
  const head = (
    <Head
      title="Expiration"
      lede={lede}
      pill={scoped ? <Pill>{never ? `${config.instance} · never expires`
        : `${scoped.facets.expiring ?? 0} expiring · ${scoped.facets.grace ?? 0} in grace · ${scoped.facets.pending_delete ?? 0} pending delete`}</Pill> : undefined}
    />
  );
  if (result.state === "forbidden") {
    return (
      <Stack hasGutter>
        {head}
        <EmptyState titleText="You do not have permission to see expirations." headingLevel="h2" icon={LockIcon}>
          <EmptyStateBody>{result.detail}</EmptyStateBody>
        </EmptyState>
      </Stack>
    );
  }
  if (never) {
    return (
      <Stack hasGutter>
        {head}
        <Panel>
          <Callout tone="ok" title="Production namespaces never expire">{"A prod request with an expiry gets 422 expiration-not-allowed, the renderer never writes cmapi.net/expires-at or cmapi.net/expiry for prod, and cmapi treats a prod namespace as permanent whatever it carries. The deny-expiry-in-prod Kyverno policy reports a hand edit that adds them, in CI and at admission, and refuses it where prod's policy mode is enforce."}</Callout>
        </Panel>
      </Stack>
    );
  }

  const page = result.state === "ok" ? result.data : null;
  const busy = result.state === "ok" && result.refreshing;
  const facets = page?.facets ?? {};
  const states: Choice[] = [
    ...STATES.map(([id, label]) => ({ label, n: String(facets[id] ?? 0), on: state === id, pick: () => apply({ state: id }) })),
    { label: "All", n: state ? (unstated.state === "ok" ? String(unstated.data.page.total) : "…") : page ? String(page.page.total) : "…", on: !state, pick: () => apply({ state: "all" }) }
  ];
  const envs: Choice[] = [["", "All"], ...config.environments.map((e) => [e, e])].map(([id, label]) => ({ label, on: env === id, pick: () => apply({ env: id }) }));
  const stale = result.state === "error" && result.code === "invalid-cursor";
  const items = page?.items ?? [];
  const shown = items.find((r) => keyOf(r) === chosen) ?? (chosen && lastShown.current && keyOf(lastShown.current) === chosen ? lastShown.current : items[0]) ?? null;
  lastShown.current = shown;
  // An environment with expiration off has no rules (#479); a row with no env takes the first environment's.
  const rulesOf = (r: ExpirationRow): Rules | undefined => (r.env ? page?.rules[r.env] : page ? Object.values(page.rules)[0] : undefined);
  // The call that this page sent, as the mockup's footnote shows it. A cursor is cut: it is long, and it is not for reading.
  const sent = new URLSearchParams(Object.entries(query).map(([k, v]) => [k, k === "cursor" ? `${String(v).slice(0, 10)}…` : String(v)]));

  return (
    <Stack hasGutter>
      {head}
      <Panel>
        <Filter label="State" options={states} />
        <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapMd" }}>
          <Search applied={applied} onApply={(text) => apply({ q: text })} />
          <Filter label="Env" options={envs} />
        </Flex>
      </Panel>

      <Panel>
        {result.state === "loading" && <Stack hasGutter><span role="status">Loading expirations…</span><Skeleton /><Skeleton /><Skeleton /></Stack>}
        {result.state === "error" && !stale && (
          <Alert variant="danger" isInline title="The expirations did not load." actionLinks={<AlertActionLink onClick={result.reload}>Try again</AlertActionLink>}>{result.cause}</Alert>
        )}
        {stale && (
          <Callout tone="warn" title="This page link is out of date">
            <Stack hasGutter>
              <span>The filters changed after it was made, so the API refused it (400 invalid-cursor) rather than show the wrong rows.</span>
              <div><Button variant="secondary" size="sm" onClick={() => apply({})}>Back to the first page</Button></div>
            </Stack>
          </Callout>
        )}
        {page && (
          <>
            <Pager
              busy={busy}
              range={page.page.total ? `${page.page.from}–${page.page.to} of ${page.page.total} · most urgent first` : "0 namespaces"}
              prev={() => page.page.prevCursor && setCursor(page.page.prevCursor)}
              next={() => page.page.nextCursor && setCursor(page.page.nextCursor)}
              prevDis={!page.page.prevCursor}
              nextDis={!page.page.nextCursor}
            />
            <DataTable
              busy={busy}
              label="Expiration"
              cols={["Namespace", "Cluster", "Env", "Team", "Expires", "Days left", "Lifetime", "State", ""]}
              rows={items}
              selected={(r) => shown !== null && keyOf(r) === keyOf(shown)}
              cells={(r) => {
                const rules = rulesOf(r), sel = shown !== null && keyOf(r) === keyOf(shown);
                return [r.name, r.clusterId, r.env ?? "—", r.team ?? "—", r.expiresAt ? dayName(r.expiresAt) : "never",
                  <span className={r.daysLeft !== null && r.daysLeft !== undefined && r.daysLeft < 0 ? "cp-daysneg" : undefined}>{daysText(r, rules)}</span>,
                  r.expiresAt && r.lifetimeDays !== null && r.lifetimeDays !== undefined && rules ? `${r.lifetimeDays} of ${rules.maxLifetimeDays} d` : "—",
                  <Pill tone={STATE_PILL[r.state][1]}>{STATE_PILL[r.state][0]}</Pill>,
                  <Button variant="secondary" size="sm" onClick={() => setParams({ ...view, state: view.state === "attention" ? "" : view.state, ns: keyOf(r) })}>{sel ? "Selected" : "Manage"}</Button>];
              }}
            />
            {items.length === 0 && <Empty>No namespace matches this state and search.</Empty>}
            <Small>{`GET /api/v1/expirations?${sent.toString()} · paged and searched like Quotas · today is ${dayName(page.today)}.`}</Small>
          </>
        )}
      </Panel>

      {shown && page && (
        <Detail
          key={keyOf(shown)}
          row={shown}
          rules={rulesOf(shown)}
          today={page.today}
          canChange={me.state === "ok" && grantsIn(me.data.access, EXTEND, shown.env)}
          onOpen={(id) => open("workflow", { request: id })}
        />
      )}
    </Stack>
  );
}

/** The mockup's lede, with the numbers of the instance's rules. */
function ledeOf(instance: string, r: Rules | undefined): string {
  const step = r?.maxExtensionDays ?? 30, life = r?.maxLifetimeDays ?? 180, grace = r?.graceDays ?? 7;
  const notices = (r?.notifyDaysBefore ?? [14, 7, 1]).join(", ").replace(/, (\d+)$/, " and $1");
  return `Every namespace on the ${instance} instance that has, or could have, an expiry date. Expiry is optional and prod never has it. Extend in steps of up to ${step} days, up to ${life} days from creation; past that, or to make a namespace permanent, approver-platform approves. Notices go out at ${notices} days, a ${grace}-day grace follows the date, and then cmapi opens a delete request that an operator confirms.`;
}

/** The mockup's search box: the API's `q`, sent when the typing stops. */
function Search({ applied, onApply }: { applied: string; onApply: (text: string) => void }) {
  const [text, setText] = useState(applied);
  useEffect(() => setText(applied), [applied]);
  useEffect(() => {
    if (text.trim() === applied) return;
    const timer = setTimeout(() => onApply(text.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text]);
  return (
    <div className="cp-combo">
      <SearchInput aria-label="Find a namespace or team" placeholder="Find a namespace or team" value={text} onChange={(_, v) => setText(v)} onClear={() => setText("")} />
    </div>
  );
}

interface DetailProps {
  row: ExpirationRow;
  rules: Rules | undefined;
  today: string;
  canChange: boolean;
  onOpen: (requestId: string) => void;
}

/** The namespace's expiry, and the form that changes it. */
function Detail({ row, rules, today, canChange, onOpen }: DetailProps) {
  const ns = useNamespace(row.clusterId, row.name);
  const etag = ns.state === "ok" ? ns.data.etag : null;
  const [word, tone] = STATE_PILL[row.state];
  const d = row.daysLeft;
  const left = d === null || d === undefined ? "—" : d >= 0 ? String(d)
    : row.state === "grace" && rules ? `past the date; ${rules.graceDays + d} grace days left` : "past the date; grace is over";
  const notices = rules?.notifyDaysBefore ?? [];
  const rows = [
    { k: "Expires", v: row.expiresAt ? `${dayName(row.expiresAt)} (${row.expiresAt})` : "never (permanent)" },
    { k: "Days left", v: left },
    { k: "Created", v: row.created ? dayName(row.created) : "—" },
    { k: "Lifetime", v: row.lifetimeDays !== null && row.lifetimeDays !== undefined && rules ? `${row.lifetimeDays} of ${rules.maxLifetimeDays} days` : "—" },
    { k: "Notices sent", v: row.noticesSent ? `${row.noticesSent} of ${notices.length} (${notices.join(", ")} days)` : "none yet" },
    { k: "After grace", v: row.expiresAt ? "delete request (expired-namespace), then an operator confirms the prune" : "nothing: permanent" }
  ];
  return (
    <Grid hasGutter>
      <GridItem md={12} lg={6}>
        <Panel title={`${row.name} on ${row.clusterId}`} pill={<Pill tone={tone}>{word}</Pill>}>
          <KV rows={rows} />
          {ns.state === "error" && <Callout tone="bad" title="The namespace did not load.">{ns.cause}</Callout>}
          <Small>{`GET /api/v1/clusters/${row.clusterId}/namespaces/${row.name} · ETag ${etag ?? "—"} · the date lives in Git as cmapi.net/expires-at; this list reads it from the watch cache.`}</Small>
        </Panel>
      </GridItem>
      {canChange && (
        <GridItem md={12} lg={6}>
          <Panel title={`Change expiration · ${row.name}`} pill={<Pill>{`${row.env ?? "—"} · ${row.clusterId}`}</Pill>}>
            {row.openRequest ? (
              <Callout tone="warn" title={`Open request: ${row.openRequest}`}>
                <Stack hasGutter>
                  <span>{`${row.openRequest} holds this namespace in cmapi. One open request per namespace, so another change waits until it closes.`}</span>
                  <div><Button variant="secondary" size="sm" onClick={() => onOpen(row.openRequest!)}>Open at current step</Button></div>
                </Stack>
              </Callout>
            ) : row.actions.length === 0 ? (
              <Empty>{`Namespaces in ${row.env ?? "this environment"} cannot carry an expiry date.`}</Empty>
            ) : etag === null ? (
              ns.state === "loading" ? <span role="status">Loading the namespace…</span> : null
            ) : (
              <ChangeForm row={row} rules={rules ?? NO_RULES} today={today} etag={etag} reread={ns.reload} />
            )}
          </Panel>
        </GridItem>
      )}
    </Grid>
  );
}

type Act = { id: string; label: string; sub: string; change: ExpiryChange };

/** The mockup's actions: extend by 7, 14 or the most days of one step, or make permanent; set a date for a permanent namespace.
 *  Only those of the row's `actions` (the API's): where expiration is off, Make permanent alone (#479). */
function actionsOf(row: ExpirationRow, rules: Rules, until: string): Act[] {
  const steps = [...new Set([7, 14, rules.maxExtensionDays])].filter((n) => n > 0 && n <= rules.maxExtensionDays);
  const all: Act[] = [
    { id: "set", label: "Set a date", sub: `at most ${rules.maxExtensionDays} days from today`, change: { route: "set", body: { until } } },
    ...steps.map((n): Act => ({ id: `ext${n}`, label: `Extend ${n} days`, sub: n === rules.maxExtensionDays ? `+${n}, the most per step` : `+${n}`, change: { route: "extend", body: { days: n } } })),
    { id: "perm", label: "Make permanent", sub: "adds approver-platform", change: { route: "makePermanent", body: {} } }
  ];
  return all.filter((a) => row.actions.includes(a.change.route));
}

/** The rules of an environment whose expiration is off: none. Its rows take only Make permanent, which reads no rule. */
const NO_RULES: Rules = { maxExtensionDays: 0, maxLifetimeDays: 0, notifyDaysBefore: [], graceDays: 0 };

/** The date that a plan writes in the namespace's manifest, or null when it writes none: what Git will hold. */
function plannedDate(plan: Plan): string | null {
  const file = Object.entries(plan.files).find(([path]) => path.endsWith("/namespace.yaml"))?.[1] ?? "";
  return /cmapi\.net\/expires-at:\s*'?(\d{4}-\d{2}-\d{2})/.exec(file)?.[1] ?? null;
}

/** The plan's approval as the mockup's callout: who must approve, and why. */
function approvalOf(plan: Plan): { tone: string; title: string; detail: string } {
  const a = plan.approval;
  const need = a.slots.reduce((n, x) => n + x.count, 0);
  if (a.auto && a.auto !== "none-required") return { tone: "ok", title: `Auto-approved by ${policyOf(a.auto)}`, detail: sentence(a.reasons) };
  if (need === 0) return { tone: "ok", title: "No approval needed", detail: `${sentence(a.reasons)} The bot PR merges when CI passes.`.trim() };
  const groups = a.slots.map((x) => x.group).join(" + ");
  return { tone: "info", title: `${need} approval${need > 1 ? "s" : ""} in cmapi from ${groups}`, detail: `${sentence(a.reasons)} Nothing reaches Git until they approve.`.trim() };
}

/** What the 202 says, in the mockup's words. */
function sentOf(r: ChangeRequest): { title: string; text: string } {
  const { need, have } = countsOf(r);
  return {
    title: `202 Accepted · ${r.requestId} · ${r.status}`,
    text: r.status === "pending_approval" && need > have
      ? "The approvers are notified; the expiry changes in Git once they approve."
      : "Approved at once; the bot PR updates cmapi.net/expires-at when CI passes."
  };
}

const PATH = { extend: ":extend", set: ":set", makePermanent: ":makePermanent" } as const;

function ChangeForm({ row, rules, today, etag, reread }: { row: ExpirationRow; rules: Rules; today: string; etag: string; reread: () => void }) {
  const [until, setUntil] = useState(plusDays(today, rules.maxExtensionDays));
  const acts = actionsOf(row, rules, until);
  const [actId, setActId] = useState(acts[0].id);
  const act = acts.find((a) => a.id === actId) ?? acts[0];
  const [planned, setPlanned] = useState<PlannedExpiry | null>(null);
  // The change that the last Submit sent, so that its answer shows only while the form is that change.
  const [submitted, setSubmitted] = useState<string | null>(null);
  const form = useRef<HTMLFormElement>(null);
  // One key for each change that this form sends (#282): the same change sent again keeps its key, a changed one gets a new one.
  const sentKey = useRef<{ key: string; change: string } | null>(null);
  const keyFor = (fingerprint: string): string => {
    if (sentKey.current?.change !== fingerprint) sentKey.current = { key: crypto.randomUUID(), change: fingerprint };
    return sentKey.current.key;
  };
  const plan = useExpiryPlan(planned);
  const submit = useSubmitExpiry();

  const change = { clusterId: row.clusterId, ns: row.name, etag, ...act.change } as PlannedExpiry;
  // The key's fingerprint is the request: where, the route and the body. If-Match is its precondition, so the same body sent
  // again on a newer etag keeps its key, as the API's replay compares the body only (cmapi/src/cmapi/plugins/namespaces/router.py).
  const fingerprint = JSON.stringify([row.clusterId, row.name, act.change.route, act.change.body]);
  const ofBody = (p: PlannedExpiry): boolean => JSON.stringify([p.clusterId, p.ns, p.route, p.body]) === fingerprint;
  // A plan is of one body at one etag: a plan made at an etag that the namespace no longer has is not the plan of the form.
  const planIsOfForm = planned !== null && ofBody(planned) && planned.etag === etag;
  // A 412 or 428, of the plan or of the submit, reads the namespace again instead of sending its stale etag again (docs/04).
  const stale = (planned !== null && ofBody(planned) && outdated(plan)) || (submitted === fingerprint && outdated(submit));
  useEffect(() => { if (stale) reread(); }, [stale]);
  // The namespace read again with a new etag plans the same change on it, so the next Submit sends a plan of the folder now.
  useEffect(() => { setPlanned((p) => (p !== null && p.etag !== etag && ofBody(p) ? { ...p, etag } : p)); }, [etag]);
  const pick = (id: string) => { setActId(id); setPlanned(null); };

  // What the person sees before the plan: the mockup's checks, from the rules of the list (expirationView()).
  const from = row.expiresAt && row.expiresAt > today ? row.expiresAt : today;
  const newIso = act.change.route === "extend" ? plusDays(from, act.change.body.days) : act.change.route === "set" ? until : null;
  const tooEarly = act.change.route === "set" && (!until || until <= today);
  const checks: Check[] = row.actions.includes("extend") || row.actions.includes("set")
    ? [{ s: "pass", mark: MARK.pass, main: "Non-prod namespace", note: `${row.env ?? "—"} allows expiration` }]
    : [{ s: "pass", mark: MARK.pass, main: "Expiration is off", note: `${row.env ?? "—"} takes no new date; the kept one can be removed` }];
  if (act.change.route === "extend") {
    const n = act.change.body.days;
    checks.push({ s: n <= rules.maxExtensionDays ? "pass" : "fail", mark: n <= rules.maxExtensionDays ? MARK.pass : MARK.fail, main: `Extension within ${rules.maxExtensionDays} days`, note: `+${n} days, to ${dayName(newIso!)}` });
  }
  if (newIso && row.created) {
    const life = between(row.created, newIso), over = life > rules.maxLifetimeDays;
    checks.push({ s: over ? "warn" : "pass", mark: over ? MARK.warn : MARK.pass, main: `Lifetime within ${rules.maxLifetimeDays} days`, note: `${life} days from creation (${dayName(row.created)})` });
  }
  if (act.change.route === "makePermanent") checks.push({ s: "pass", mark: MARK.pass, main: "Removes cmapi.net/expires-at and cmapi.net/expiry", note: "" });
  const shownChecks = tooEarly ? [{ s: "fail", mark: MARK.fail, main: "Date", note: "must be tomorrow or later" }] : checks;

  const onPlan = () => {
    if (!form.current?.reportValidity() || tooEarly) return;
    setPlanned(change);
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (submit.state === "sending" || tooEarly) return;
    if (!form.current?.reportValidity()) return;
    // Nothing is submitted that the person has not seen planned: a form with no plan, or changed since its plan, is planned
    // first, and the next Submit sends it. A refused or failed plan is on the page, and Submit waits for a plan.
    if (!planIsOfForm) { setPlanned(change); return; }
    if (plan.state !== "ok") return;
    setSubmitted(fingerprint);
    submit.submit(planned, keyFor(fingerprint)).catch(() => undefined);
  };

  const planOk = plan.state === "ok" && planIsOfForm ? plan.data : null;
  const writes = planOk ? plannedDate(planOk) : null;
  const appr = planOk ? approvalOf(planOk) : null;
  const answered = submitted === fingerprint ? submit : null;
  const btn = act.change.route === "makePermanent" ? "Request make permanent" : act.change.route === "set" ? "Set expiry" : "Extend";
  const choices: Choice[] = acts.map((a) => ({ label: a.label, sub: a.sub, on: a.id === act.id, pick: () => pick(a.id) }));
  return (
    <Form noValidate={false} onSubmit={onSubmit} ref={form}>
      <FormGroup label="Action" role="group" fieldId="exp-action">
        <Choices label="Action" options={choices} />
      </FormGroup>
      {act.change.route === "set" && (
        <FormGroup label="New expiry date" fieldId="exp-until">
          <TextInput id="exp-until" type="date" isRequired min={plusDays(today, 1)} max={plusDays(today, rules.maxExtensionDays)} value={until}
            onChange={(_, v) => { setUntil(v); setPlanned(null); }} />
        </FormGroup>
      )}
      <Checks items={shownChecks} />
      {planOk && appr && (
        <Stack hasGutter>
          <Checks items={[
            { s: "pass", mark: MARK.pass, main: "If-Match matches the current ETag", note: planned!.etag },
            { s: "pass", mark: MARK.pass, main: "The plan writes", note: writes ? `cmapi.net/expires-at: ${writes}` : "no cmapi.net/expires-at" }
          ]} />
          <Callout tone={appr.tone} title={appr.title}>{appr.detail}</Callout>
        </Stack>
      )}
      <ActionGroup>
        <Button variant="secondary" type="button" onClick={onPlan}>Plan change</Button>
        <Button variant="primary" type="submit" isLoading={submit.state === "sending"}>{btn}</Button>
      </ActionGroup>
      {plan.state === "sending" && planIsOfForm && <span role="status">Planning…</span>}
      {planIsOfForm && plan.state === "refused" && <Callout tone="bad" title={`Refused: ${plan.code}`}>{plan.detail}</Callout>}
      {planIsOfForm && plan.state === "error" && (
        <Alert variant="danger" isInline title="The plan did not complete." actionLinks={<AlertActionLink onClick={plan.reload}>Try again</AlertActionLink>}>{plan.cause}</Alert>
      )}
      {answered?.state === "ok" && (
        <>
          <Callout tone="ok" title={sentOf(answered.data).title}>{sentOf(answered.data).text}</Callout>
          <Code text={`POST /api/v1/clusters/${row.clusterId}/namespaces/${row.name}/expiration${PATH[act.change.route]}\n${JSON.stringify({ requestId: answered.data.requestId, status: answered.data.status,
            change: { expiresAt: writes }, approval: answered.data.approval && { rule: answered.data.approval.rule, remaining: answered.data.approval.remaining } }, null, 2)}`} />
        </>
      )}
      {answered?.state === "refused" && <Callout tone="bad" title={`${answered.status} ${answered.code} · nothing written`}>{`No request was stored and nothing was written to Git. ${answered.detail}`}</Callout>}
      {answered?.state === "error" && <Callout tone="bad" title="Not submitted">{`${answered.cause} Submit again: the same request is sent, and the API makes it at most once.`}</Callout>}
    </Form>
  );
}
