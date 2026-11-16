// The New namespace tab: GET /api/v1/tiers and GET /api/v1/clusters for the form, the dry run for the plan and its
// approval, then the create with an Idempotency-Key that the portal makes (#282). The words are the mockup's
// (mockups/portal/Main.dc.html, isNew). MOCKUP-CONTRACT.md lists what differs, and why.
import {
  ActionGroup, Alert, AlertActionLink, Button, EmptyState, EmptyStateBody, Flex, FlexItem, Form, FormGroup, FormSelect, FormSelectOption, Grid,
  GridItem, Label, Skeleton, Stack, TextArea, TextInput
} from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { useState } from "react";
import type { FormEvent } from "react";
import { useClusters, useMe, usePlan, useSubmitNamespace, useTiers } from "../api/hooks";
import type { Cluster, NamespaceCreate, Plan, TierCatalog } from "../api/hooks";
import { Callout, Checks, Choices, Empty, Head, Hint, KV, Panel, Pill, Small } from "../components/ui";
import type { Check } from "../components/ui";
import { dayName, daysUntil, isoDay, policyOf } from "./format";
import type { TabProps } from "./route";

const MARK = { pass: "✓", warn: "!", fail: "✕" } as const;
/** docs/02: a namespace lives at most 180 days from its creation, and prod never expires. */
const MAX_LIFETIME_DAYS = 180;
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

/** The API's reasons, as one sentence: "dev create: 1 from approver-platform; threshold beyondTier: +1 approver-platform." */
const sentence = (reasons: string[]): string => (reasons.length ? `${reasons.join("; ")}.` : "");

/** The mockup's approval card, from the plan's approval: who must approve, and why. */
function approvalCard(plan: Plan, env: string): { tone: string; title: string; detail: string; rule: string } {
  const a = plan.approval;
  const need = a.slots.reduce((n, s) => n + s.count, 0);
  if (a.auto || need === 0) {
    const title = a.auto && a.auto !== "none-required" ? `Auto-approved by ${policyOf(a.auto)}` : "No approval needed";
    return { tone: "ok", title, detail: sentence(a.reasons), rule: `${a.rule} · 0 of 0 (auto)` };
  }
  const groups = a.slots.map((s) => s.group).join(" + ");
  const self = a.selfApproval ? `Self-approval is allowed in ${env}.` : "The requester cannot approve their own request.";
  return {
    tone: env === "prod" ? "warn" : "info",
    title: `${need} approval${need > 1 ? "s" : ""} in cmapi from ${groups}`,
    detail: `${sentence(a.reasons)} ${self}`.trim(),
    rule: `${a.rule} · ${a.slots.map((s) => `${s.count} of ${s.group}`).join(" + ")}`
  };
}

export function NewNamespaceTab({ config, open }: TabProps) {
  const now = new Date();
  const me = useMe();
  const clusters = useClusters();
  // No choice yet: the first environment of this instance that has a cluster to write to.
  const [pickedEnv, setEnv] = useState("");
  const writable = clusters.state === "ok" ? clusters.data.items.filter((c) => c.writes) : null;
  const env = pickedEnv || (writable && (config.environments.find((e) => writable.some((c) => c.environment === e)) ?? config.environments[0])) || "";
  const tiers = useTiers(env);
  const [tier, setTier] = useState("medium");
  const [team, setTeam] = useState("");
  const [region, setRegion] = useState(ANY_REGION);
  const [chosen, setChosen] = useState("");
  const [name, setName] = useState("");
  const [dl, setDl] = useState("");
  const [expires, setExpires] = useState("");
  const [why, setWhy] = useState("");
  // The body that the last Dry run sent. A change to the form hides its result, as in the mockup.
  const [planned, setPlanned] = useState<{ cluster: string; body: NamespaceCreate } | null>(null);
  // One key for this opening of the form (#282). Submitting again after a refusal or a lost answer sends the same key,
  // so the API answers with the first request and never makes two. Leaving the tab ends the form: the next one has a new key.
  const [key] = useState(() => crypto.randomUUID());
  const submit = useSubmitNamespace();
  const plan = usePlan(planned?.cluster ?? "", planned?.body ?? null);

  const edit = <T,>(set: (value: T) => void) => (value: T) => { set(value); setPlanned(null); };
  const head = <Head title="New namespace" lede="Describe what you need. cmapi picks the cluster from stored capacity snapshots, shows the approval that will apply, and turns the request into a pull request." />;

  const forbidden = [clusters, tiers].find((r) => r.state === "forbidden");
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
  const failed = [clusters, tiers].find((r) => r.state === "error");
  if (failed?.state === "error") {
    return (
      <Stack hasGutter>
        {head}
        <Alert variant="danger" isInline title="The form did not load." actionLinks={<AlertActionLink onClick={() => { clusters.reload(); tiers.reload(); }}>Try again</AlertActionLink>}>
          {failed.cause}
        </Alert>
      </Stack>
    );
  }
  if (clusters.state === "ok" && !env) return <Stack hasGutter>{head}<Empty>config.json names no environment for this instance.</Empty></Stack>;
  if (clusters.state !== "ok" || tiers.state !== "ok") {
    return <Stack hasGutter>{head}<span role="status">Loading the form…</span><Skeleton /><Skeleton /><Skeleton /></Stack>;
  }

  const offered = tiersOf(tiers.data, env);
  const current = offered.find((t) => t.name === tier) ?? offered[0];
  const inEnv = (writable ?? []).filter((c) => c.environment === env);
  const regions = [...new Set(inEnv.map((c) => c.labels.region).filter((r): r is string => Boolean(r)))].sort();
  const candidates = inEnv.filter((c) => region === ANY_REGION || c.labels.region === region);
  const cluster: Cluster | undefined = candidates.find((c) => c.clusterId === chosen) ?? candidates[0];
  const nsName = name || (team ? `${team}-${env}` : "");
  const expAllowed = env !== "prod";
  const expDays = expAllowed && expires ? daysUntil(expires, now) : null;

  const body: NamespaceCreate = {
    namespace: nsName,
    tier: current?.name ?? tier,
    labels: { "cmapi.net/team": team },
    annotations: { "cmapi.net/team-dl": dl },
    justification: why || null,
    ...(expAllowed && expires ? { expiresAt: expires } : {})
  };
  const planOk = plan.state === "ok" ? plan.data : null;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!cluster || submit.state === "sending") return;
    // The tab ends on a 202: the Workflow tab follows the new request, as the mockup's Submit opens its workflow.
    submit.submit(cluster.clusterId, body, key).then((request) => open("workflow", { request: request.requestId }), () => undefined);
  };

  const checks: Check[] = planOk ? [
    { s: "pass", mark: MARK.pass, main: "Environment served", note: `${env} in [${config.environments.join(", ")}]` },
    capacityCheck(planOk),
    {
      s: expDays !== null && (expDays < 1 || expDays > MAX_LIFETIME_DAYS) ? "fail" : "pass",
      mark: expDays !== null && (expDays < 1 || expDays > MAX_LIFETIME_DAYS) ? MARK.fail : MARK.pass,
      main: "Expiry",
      note: !expAllowed ? "none: prod never expires" : expires ? `${expires}, ${expDays} days (limit ${MAX_LIFETIME_DAYS})` : "none: permanent"
    },
    { s: planOk.approval.auto ? "pass" : "warn", mark: planOk.approval.auto ? MARK.pass : MARK.warn, main: "Approval", note: approvalCard(planOk, env).rule }
  ] : [];
  const appr = planOk ? approvalCard(planOk, env) : null;

  return (
    <Stack hasGutter>
      {head}
      <Grid hasGutter>
        <GridItem md={12} lg={7}>
          <Panel>
            <Form noValidate={false} onSubmit={onSubmit}>
              <FormGroup label="Environment" role="group" fieldId="ns-env">
                <Choices label="Environment" options={config.environments.map((e) => ({ label: e, on: e === env, pick: () => { edit(setEnv)(e); setChosen(""); } }))} />
                <Hint>This is the {config.displayName} portal: it serves {config.environments.join(", ")} only.</Hint>
                {config.otherInstances.length > 0 && (
                  <Flex gap={{ default: "gapMd" }}>
                    {config.otherInstances.map((x) => <Small key={x.name}>{x.environments.join(", ")} → <a href={x.url}>{`${x.name} portal`}</a></Small>)}
                  </Flex>
                )}
              </FormGroup>
              <Grid hasGutter>
                <GridItem md={6}>
                  <FormGroup label="Team" fieldId="ns-team">
                    <TextInput id="ns-team" isRequired value={team} onChange={(_, v) => edit(setTeam)(v)} />
                    <Hint>Who owns it, for cost and notices: any team name. Not checked against who you are; your Keycloak roles decide what you may do.</Hint>
                  </FormGroup>
                </GridItem>
                <GridItem md={6}>
                  <FormGroup label="Region" fieldId="ns-region">
                    <FormSelect id="ns-region" value={region} onChange={(_, v) => { edit(setRegion)(v); setChosen(""); }}>
                      {regions.map((r) => <FormSelectOption key={r} value={r} label={r} />)}
                      <FormSelectOption value={ANY_REGION} label="Any region" />
                    </FormSelect>
                    <Hint>From clusters.yaml metadata.</Hint>
                  </FormGroup>
                </GridItem>
              </Grid>
              <FormGroup label="Cluster" fieldId="ns-cluster">
                <FormSelect id="ns-cluster" value={cluster?.clusterId ?? ""} isDisabled={!candidates.length} onChange={(_, v) => edit(setChosen)(v)}>
                  {candidates.map((c) => <FormSelectOption key={c.clusterId} value={c.clusterId} label={c.clusterId} />)}
                  {!candidates.length && <FormSelectOption value="" label="—" />}
                </FormSelect>
                <Hint>{candidates.length ? `The ${env} clusters that take writes, from GET /api/v1/clusters. Placement is not on the API yet (#303).` : `No ${env} cluster takes writes on this instance.`}</Hint>
              </FormGroup>
              <FormGroup label="Namespace name" fieldId="ns-name">
                <TextInput id="ns-name" isRequired value={nsName} onChange={(_, v) => edit(setName)(v)} />
                <Hint>Any DNS-1123 name. Not allowed: reserved names (default, openshift-*, kube-*, cmapi-system, ocp-*) and a name already on the cluster outside cmapi.</Hint>
              </FormGroup>
              <FormGroup label="Tier" role="group" fieldId="ns-tier">
                <Choices label="Tier" options={offered.map((t) => ({ label: t.name, sub: `${t.cpu} cores · ${t.memory}`, on: t.name === current?.name, pick: () => edit(setTier)(t.name) }))} />
                <Hint>cmapi writes the tier's ResourceQuota and LimitRange (config/tiers.yaml) into the namespace folder.</Hint>
              </FormGroup>
              <Grid hasGutter>
                <GridItem md={6}>
                  <FormGroup label="Team DL (required)" fieldId="ns-dl">
                    <TextInput id="ns-dl" type="email" isRequired value={dl} onChange={(_, v) => edit(setDl)(v)} />
                    <Hint>Your team's distribution list, in one of the organisation's email domains (emailDomains); format only.{me.state === "ok" && ` Requested by ${me.data.username} (${me.data.identity.email ?? "no email"}), from your sign-in.`}</Hint>
                  </FormGroup>
                </GridItem>
                <GridItem md={6}>
                  {expAllowed && (
                    <FormGroup label="Expires (optional)" fieldId="ns-exp">
                      <TextInput id="ns-exp" type="date" min={isoDay(now, 1)} max={isoDay(now, MAX_LIFETIME_DAYS)} value={expires} onChange={(_, v) => edit(setExpires)(v)} />
                      <Hint>{expires ? `Expires in ${expDays} days. Notices at 14, 7 and 1 days, then a 7-day grace; extend from the Expiration tab in steps of up to 30 days.` : "Leave empty for a permanent namespace. At most 180 days from today; extend later from the Expiration tab."}</Hint>
                    </FormGroup>
                  )}
                  {!expAllowed && (
                    <FormGroup label="Expires" fieldId="ns-exp-never">
                      <Hint>Never. Production namespaces cannot carry expiration metadata: refused at validation and by the deny-expiry-in-prod policy.</Hint>
                    </FormGroup>
                  )}
                </GridItem>
              </Grid>
              <FormGroup label="Justification" fieldId="ns-why">
                <TextArea id="ns-why" value={why} onChange={(_, v) => edit(setWhy)(v)} />
              </FormGroup>
              {plan.state === "sending" && <span role="status">Planning…</span>}
              {planOk && <Callout tone="info" title="Dry run passed · nothing written"><Checks items={checks} /></Callout>}
              {plan.state === "refused" && <Callout tone="bad" title={`Refused: ${plan.code}`}>{plan.detail}</Callout>}
              {plan.state === "error" && (
                <Alert variant="danger" isInline title="The dry run did not complete." actionLinks={<AlertActionLink onClick={plan.reload}>Try again</AlertActionLink>}>{plan.cause}</Alert>
              )}
              {submit.state === "refused" && <Callout tone="bad" title="Not submitted">{`${submit.code}: ${submit.detail}`}</Callout>}
              {submit.state === "error" && <Callout tone="bad" title="Not submitted">{`${submit.cause} Submit again: the same request is sent, and the API makes it at most once.`}</Callout>}
              <ActionGroup>
                <Button variant="secondary" type="button" isDisabled={!cluster} onClick={() => cluster && setPlanned({ cluster: cluster.clusterId, body })}>Dry run</Button>
                <Button variant="primary" type="submit" isDisabled={!cluster} isLoading={submit.state === "sending"}>Submit request</Button>
              </ActionGroup>
            </Form>
          </Panel>
        </GridItem>
        <GridItem md={12} lg={5}>
          <Stack hasGutter>
            <Panel title="Placement preview" pill={planOk ? <Pill tone={planOk.capacity.fresh ? "ok" : "warn"}>{planOk.capacity.fresh ? "fresh data" : "stale data"}</Pill> : undefined}>
              <Small>The cluster is your choice until placement is on the API (#303). The dry run checks its capacity.</Small>
              {cluster && (
                <Flex alignItems={{ default: "alignItemsCenter" }} flexWrap={{ default: "nowrap" }}>
                  <FlexItem><Label isCompact status={planOk?.capacity.status === "fits" ? "success" : undefined}>1</Label></FlexItem>
                  <FlexItem grow={{ default: "grow" }} style={{ minWidth: 0 }}>
                    <b>{cluster.clusterId}</b>
                    <div><Small>{planOk ? capacityLine(planOk) : `${cluster.environment}${cluster.labels.region ? ` · ${cluster.labels.region}` : ""} · ${cluster.status}`}</Small></div>
                  </FlexItem>
                  {planOk && <FlexItem><Pill tone={CAPACITY_TONE[planOk.capacity.status]}>{planOk.capacity.status}</Pill></FlexItem>}
                </Flex>
              )}
            </Panel>
            <Panel title="Approval that will apply">
              {appr ? <Callout tone={appr.tone} title={appr.title}>{appr.detail}</Callout> : <Callout tone="info" title="Not planned yet">Dry run asks the API which approval applies.</Callout>}
              <KV rows={[
                { k: "Rule", v: appr?.rule ?? "—" },
                { k: "Quota", v: current ? `${current.cpu} cores · ${current.memory} · ${current.pods} pods` : "—" },
                { k: "Expires", v: !expAllowed ? "never (prod)" : expires ? `${dayName(expires)} (${expDays} days)` : "never (permanent)" },
                { k: "Lands in Git", v: planOk ? folderOf(planOk) : "—" }
              ]} />
            </Panel>
          </Stack>
        </GridItem>
      </Grid>
    </Stack>
  );
}

const CAPACITY_TONE = { fits: "ok", warn: "warn", exceeded: "bad", unknown: "" } as const;

function capacityCheck(plan: Plan): Check {
  const c = plan.capacity;
  if (c.status === "fits") return { s: "pass", mark: MARK.pass, main: "Capacity", note: c.fresh ? "fits on fresh data" : "fits on stale data" };
  if (c.status === "exceeded") return { s: "fail", mark: MARK.fail, main: "Capacity", note: "capacity-exceeded" };
  return { s: "warn", mark: MARK.warn, main: "Capacity", note: c.status };
}

/** "cpu 3% · memory 3% · binds on cpu", from the capacity check's fields when it has them. */
function capacityLine(plan: Plan): string {
  const c = plan.capacity as Plan["capacity"] & { cpu?: unknown; memory?: unknown };
  const pct = (x: unknown) => (typeof x === "number" ? `${Math.round(x * 100)}%` : "—");
  return `cpu ${pct(c.cpu)} · memory ${pct(c.memory)}${c.bindingResource ? ` · binds on ${c.bindingResource}` : ""}`;
}
