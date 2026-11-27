// The Adopt view of the Namespaces tab (story #26; mockup docs/reviews/2026-11-14-issue-26-adoption/mockup-adopt.html): an
// existing namespace that cmapi does not manage is adopted through a request, its approvals and a pull request, as the
// adoption design says (docs/reviews/2026-11-14-issue-26-adoption/README.md). MOCKUP-CONTRACT.md lists what differs.
//
// The workflow, step by step (each step's function is named):
//   1. AdoptView: the candidates of the cluster (useAdoptionList "candidates") and the labelled namespaces that a rule skips
//      (useAdoptionList "skipped"), each read now from the cluster.
//   2. "Adopt <ns>" opens AdoptOne, whose address is #namespaces?view=adopt&cluster=<id>&adopt=<ns>.
//   3. Missing metadata (#739): below the plan, one field for each required key that the namespace lacks (the candidate's
//      missingKeys), and the optional ones behind "More". A key that cmapi fills in or that starts the name is read-only with
//      the API's value and added only if selected; an empty field adds nothing, and its key stays a finding until a request adds it.
//   4. Check (dry run): POST .../namespaces/{ns}:adopt?dryRun=true with the keys (useAdoptPlan). The plan shows the objects
//      read, the keys it adds, its findings, the keys under a skip prefix, what stays unmanaged, the files and the approval.
//      Nothing is written.
//   5. Submit adoption request: the same body with one Idempotency-Key (useSubmitAdoption); a 202 shows the request.
import {
  ActionGroup, Alert, AlertActionLink, Button, CodeBlock, CodeBlockCode, EmptyState, EmptyStateBody, ExpandableSection, Form, FormGroup, Grid,
  GridItem, Label, List, ListItem, Skeleton, Stack, TextArea, Title, Truncate
} from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { useAdoptionList, useAdoptPlan, useSubmitAdoption } from "../api/hooks";
import type { AdoptionStanding, ChangeRequest, Cluster, Plan, PlannedAdoption } from "../api/hooks";
import { ApiProblem } from "../api/problem";
import { Callout, Hint, Panel, Small } from "../components/ui";
import { checkField, errorsByField } from "./metadataForm";
import type { MetaForm } from "./metadataForm";
import { MissingMetadata } from "./MissingMetadata";
import { addedOf, missingFields, stillMissing } from "./missingKeys";
import type { MissingField } from "./missingKeys";
import { sharedPatternTest } from "./patterns";
import { approvalCard } from "./plan";
import type { TabProps } from "./route";

const PASSED = "The check passed (dry run, 200). Nothing is written yet.";

/** The candidates and the skipped namespaces of one cluster, and the adoption of one of them. */
export function AdoptView({ cluster, adopt, form, onAdopt, open }: {
  cluster: Cluster; adopt: string; form: MetaForm; onAdopt: (ns: string) => void; open: TabProps["open"];
}) {
  const candidates = useAdoptionList(cluster.clusterId, "candidates");
  const skipped = useAdoptionList(cluster.clusterId, "skipped");
  return (
    <Stack hasGutter>
      <Panel title="Adopt an existing namespace">
        <Hint>
          A namespace that cmapi does not manage is adopted only when it carries the label <code>{`${candidates.state === "ok" ? candidates.data.label : "cmapi.net/adopt"}: "true"`}</code>. cmapi
          reads it as it is, writes it to Git under the custom tier, and lists every difference from the rules as a finding. A person approves it, and the change reaches the cluster only through a pull request.
        </Hint>
        <Title headingLevel="h3" size="md">Candidates</Title>
        <StandingTable result={candidates} empty={`No namespace on ${cluster.clusterId} carries cmapi.net/adopt: "true" and can be adopted.`}
          label={`Namespaces of ${cluster.clusterId} that can be adopted`} onAdopt={onAdopt} />
        <Title headingLevel="h3" size="md">Labelled, and skipped</Title>
        <StandingTable result={skipped} empty="No labelled namespace is skipped." label={`Labelled namespaces of ${cluster.clusterId} that are not adopted`} />
      </Panel>
      {adopt && candidates.state === "loading" && <Skeleton />}
      {adopt && candidates.state !== "loading" && (
        <AdoptOne key={`${cluster.clusterId}/${adopt}`} cluster={cluster} ns={adopt} form={form} open={open}
          missing={candidates.state === "ok" ? candidates.data.items.find((s) => s.name === adopt)?.missingKeys ?? [] : []} />
      )}
    </Stack>
  );
}

function StandingTable({ result, empty, label, onAdopt }: {
  result: ReturnType<typeof useAdoptionList>; empty: string; label: string; onAdopt?: (ns: string) => void;
}) {
  if (result.state === "loading") return <Stack><span role="status">Loading the namespaces…</span><Skeleton /></Stack>;
  if (result.state === "forbidden") {
    return <EmptyState titleText="You do not have permission to adopt namespaces." headingLevel="h4" icon={LockIcon} variant="xs"><EmptyStateBody>{result.detail}</EmptyStateBody></EmptyState>;
  }
  if (result.state === "error") {
    return <Alert variant="danger" isInline title="The namespaces did not load." actionLinks={<AlertActionLink onClick={result.reload}>Try again</AlertActionLink>}>{result.cause}</Alert>;
  }
  if (result.data.items.length === 0) return <Small>{empty}</Small>;
  const recognised = (s: AdoptionStanding) => (s.recognised.length ? s.recognised.map((r) => <Label key={r} isCompact>{r}</Label>) : <Small>—</Small>);
  return (
    <Table aria-label={label} variant="compact" gridBreakPoint="grid-md">
      <Thead>
        <Tr><Th>Namespace</Th><Th>{onAdopt ? "Made by another tool" : "Why it is not adopted"}</Th>{onAdopt && <Th screenReaderText="Actions" />}</Tr>
      </Thead>
      <Tbody>
        {result.data.items.map((s) => (
          <Tr key={s.name}>
            <Td dataLabel="Namespace"><code>{s.name}</code></Td>
            {onAdopt
              ? <><Td dataLabel="Made by another tool">{recognised(s)}</Td>
                <Td dataLabel="Actions"><AdoptButton ns={s.name} onAdopt={onAdopt} /></Td></>
              : <Td dataLabel="Why it is not adopted" modifier="breakWord">{`${s.rule}: ${s.detail}`}</Td>}
          </Tr>
        ))}
      </Tbody>
    </Table>
  );
}

/** "Adopt <ns>" in a candidate's row. A button keeps its text on one line (PatternFly's button is nowrap), so a long name is
 *  truncated, as PatternFly's truncate guidelines ask of data that overflows a table cell, with the full text in a tooltip on the
 *  button itself (#749). The tooltip's trigger is the button, so the row keeps one focus stop and no focusable span inside it;
 *  the button's name is its whole text, so the tooltip adds no description to it. */
function AdoptButton({ ns, onAdopt }: { ns: string; onAdopt: (ns: string) => void }) {
  const ref = useRef<HTMLButtonElement>(null);
  const text = `Adopt ${ns}`;
  return (
    <Button ref={ref} variant="secondary" size="sm" onClick={() => onAdopt(ns)}>
      <Truncate content={text} tooltipProps={{ triggerRef: ref, aria: "none" }} />
    </Button>
  );
}

/** What stays unmanaged, as a sentence: "3 ServiceAccounts and an unknown number of RoleBindings stay unmanaged" (#749: one
 *  capital, at its start). A count that could not be read is null; the server's not-adopted finding says the same words
 *  (core/adoption.py, unmanaged_phrase). Null when the namespace has none. */
function unmanagedSentence(counts: Record<string, number | null | undefined>): string | null {
  const shown = Object.entries(counts).filter(([, n]) => n !== 0);
  if (shown.length === 0) return null;
  const parts = shown.map(([kind, n]) => (n == null ? `an unknown number of ${kind}s` : `${n} ${kind}${n === 1 ? "" : "s"}`));
  const text = `${parts.join(" and ")} ${shown.length === 1 && shown[0][1] === 1 ? "stays" : "stay"} unmanaged`;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The plan of one adoption, the metadata it lacks below it, and beside them its Justification, Check and Submit. */
function AdoptOne({ cluster, ns, form, missing, open }: {
  cluster: Cluster; ns: string; form: MetaForm; missing: NonNullable<AdoptionStanding["missingKeys"]>; open: TabProps["open"];
}) {
  const [why, setWhy] = useState("");
  // The values typed into the Missing metadata fields, by valueKey; the fields' own problems after the last Check.
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string | null>>({});
  const fields = missingFields(form, missing);
  const [asked, setAsked] = useState<PlannedAdoption | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<ChangeRequest | null>(null);
  const [notSent, setNotSent] = useState<{ status: number; code: string; detail: string } | null>(null);
  const plan = useAdoptPlan(asked);
  const submit = useSubmitAdoption();
  // One Idempotency-Key for each adoption sent (#282): the same adoption sent again keeps it, a changed one gets a new one.
  const sent = useRef<{ key: string; request: string } | null>(null);
  const keyFor = (adoption: PlannedAdoption): string => {
    const request = JSON.stringify(adoption);
    if (sent.current?.request !== request) sent.current = { key: crypto.randomUUID(), request };
    return sent.current.key;
  };
  const current: PlannedAdoption = { clusterId: cluster.clusterId, ns, justification: why.trim(), ...addedOf(fields, typed) };
  const planIsOfForm = asked !== null && JSON.stringify(asked) === JSON.stringify(current);
  const planOk = plan.state === "ok" && planIsOfForm ? plan.data : null;
  const canSubmit = planOk !== null && submit.state !== "sending" && done === null;

  // A refusal of the dry run that names a field puts its words under that field (errorsByField, by the form's field id).
  const refusedBy = plan.state === "refused" && planIsOfForm ? errorsByField(plan.errors ?? [], form).byField : {};
  const shownErrors: Record<string, string | null> = Object.fromEntries(fields.map((f) => [f.id, fieldErrors[f.id] ?? refusedBy[f.field.id] ?? null]));

  /** The form's own checks of each value typed, by the API's rules, then the dry run of exactly this adoption. */
  const onCheck = async () => {
    setDone(null);
    setNotSent(null);
    const found: Record<string, string | null> = {};
    for (const f of fields) {
      const value = typed[f.id] ?? "";
      // An empty field adds nothing: the key stays missing and a finding, as the owner's decision 2 on #26 says.
      if (f.fixed === null && value !== "") found[f.id] = await checkField(f.field, value, { namespace: ns, labelValue: form.labelValue }, sharedPatternTest, true);
    }
    setFieldErrors(found);
    const bad = fields.filter((f) => found[f.id]);
    if (!current.justification) { setProblem("Justification: say why this namespace is adopted."); return; }
    if (bad.length) { setProblem(`Missing metadata: ${bad.map((f) => `${f.field.title ?? f.field.key}: ${found[f.id]}`).join("; ")}`); return; }
    setProblem(null);
    if (planIsOfForm) plan.reload();
    else setAsked(current);
  };
  const type = (f: MissingField, value: string) => {
    setTyped((t) => ({ ...t, [f.id]: value }));
    setFieldErrors((e) => ({ ...e, [f.id]: null }));
    setDone(null);
  };
  const left = stillMissing(fields, typed);
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !asked) return;
    submit.submit(asked, keyFor(asked)).then((request) => { setDone(request); setNotSent(null); }, (err: unknown) => {
      const p = err instanceof ApiProblem ? err : null;
      setNotSent({ status: p?.status ?? 0, code: p?.code ?? "network", detail: p?.detail ?? "The network did not answer." });
    });
  };

  const status = () => {
    if (done) {
      return (
        <Alert variant="success" isInline isLiveRegion title={`Request ${done.requestId} submitted (202).`}
          actionLinks={<AlertActionLink onClick={() => open("workflow", { request: done.requestId })}>Open at current step</AlertActionLink>}>
          It waits for its approvals; the pull request opens after them.
        </Alert>
      );
    }
    if (notSent && notSent.status > 0 && notSent.status < 500) return <Callout tone="bad" title="Not submitted">{`${notSent.code}: ${notSent.detail}`}</Callout>;
    if (notSent) return <Callout tone="bad" title="Not submitted">{`${notSent.detail} Submit again: the same request is sent, and the API makes it at most once.`}</Callout>;
    if (problem) return <Callout tone="bad" title="The check did not run. Fix these:"><List><ListItem>{problem}</ListItem></List></Callout>;
    if (planIsOfForm && plan.state === "sending") return <span role="status">Checking with cmapi…</span>;
    if (planOk) {
      const appr = approvalCard(planOk, cluster.environment);
      return (
        <Callout tone="ok" title={PASSED}>
          <div>{`${appr.title}. ${appr.detail}`}</div>
          <Small>{`${(planOk.findings ?? []).length} findings · ${planOk.adoption?.objects.length ?? 0} objects read · ${addedCount(planOk)} keys added · ${appr.rule}`}</Small>
        </Callout>
      );
    }
    if (plan.state === "refused" && planIsOfForm) {
      const title = plan.code === "namespace-not-adoptable" ? "Not adoptable" : "The check failed";
      return <Callout tone="bad" title={`${title}: ${plan.code}`}>{plan.detail}</Callout>;
    }
    if (plan.state === "error" && planIsOfForm) {
      return <Alert variant="danger" isInline title="The dry run did not complete." actionLinks={<AlertActionLink onClick={plan.reload}>Try again</AlertActionLink>}>{plan.cause}</Alert>;
    }
    if (asked !== null) return <Callout tone="info" title="Changed since the last check. Press Check (dry run) again." />;
    return <Callout tone="info" title="Write why, then press Check (dry run)." />;
  };

  return (
    <Grid hasGutter>
      <GridItem md={7}>
        <Stack hasGutter>
          <Panel title={`Adopt ${ns}`}>
            {planOk ? <PlanDetail plan={planOk} /> : <Small>Press Check (dry run) to read the namespace from the cluster and see what its adoption writes.</Small>}
          </Panel>
          <Panel title="Missing metadata">
            <Hint>
              {`The keys that the rules declare and ${ns} lacks. The adoption adds what you fill in; select Add beside a read-only value to include it. Leave a field empty to add it later: each required key stays a finding until a request adds it.`}
            </Hint>
            <MissingMetadata fields={fields} values={typed} errors={shownErrors} prefix="adopt" onChange={type} />
            {left.length > 0 && <Small>{`Still missing after this adoption: ${left.map((f) => f.field.title ?? f.field.key).join(", ")}.`}</Small>}
          </Panel>
        </Stack>
      </GridItem>
      <GridItem md={5} className="cp-sticky">
        <Panel title="Your adoption">
          <Form noValidate onSubmit={onSubmit}>
            <FormGroup label="Justification (required)" fieldId="adopt-why">
              <TextArea id="adopt-why" value={why} rows={2} placeholder="Why this namespace is adopted" onChange={(_, v) => { setWhy(v); setDone(null); }} />
            </FormGroup>
            <div id="adopt-status">{status()}</div>
            <ActionGroup>
              <Button variant="secondary" type="button" onClick={() => void onCheck()}>Check (dry run)</Button>
              <Button variant="primary" type="submit" isAriaDisabled={!canSubmit} aria-describedby="adopt-status" isLoading={submit.state === "sending"}>Submit adoption request</Button>
            </ActionGroup>
          </Form>
        </Panel>
      </GridItem>
    </Grid>
  );
}

/** How many labels and annotations the adoption adds (#739), from the plan's metadataDiff. */
const addedCount = (plan: Plan): number =>
  Object.keys(plan.metadataDiff?.labels ?? {}).length + Object.keys(plan.metadataDiff?.annotations ?? {}).length;

/** What the plan read and writes: the objects, the keys it adds, the findings, the skipped keys, what stays unmanaged, and each file. */
function PlanDetail({ plan }: { plan: Plan }) {
  const adoption = plan.adoption;
  const unmanaged = unmanagedSentence(adoption?.notAdopted ?? {});
  const added = (["labels", "annotations"] as const).flatMap((m) => Object.entries(plan.metadataDiff?.[m] ?? {})
    .map(([key, c]) => ({ kind: m === "labels" ? "label" : "annotation", key, value: c.after ?? "" })));
  return (
    <Stack hasGutter>
      <Title headingLevel="h3" size="md">Objects read from the cluster</Title>
      <Table aria-label="Objects read from the cluster" variant="compact" gridBreakPoint="grid-md">
        <Thead><Tr><Th>Kind</Th><Th>Name</Th><Th>resourceVersion</Th></Tr></Thead>
        <Tbody>
          {(adoption?.objects ?? []).map((o) => (
            <Tr key={`${o.kind}/${o.name}`}>
              <Td dataLabel="Kind">{o.kind}</Td><Td dataLabel="Name" modifier="breakWord"><code>{o.name}</code></Td>
              <Td dataLabel="resourceVersion"><code>{o.resourceVersion}</code></Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
      {added.length > 0 && (
        <>
          <Title headingLevel="h3" size="md">Keys this adoption adds</Title>
          <List aria-label="Keys this adoption adds">
            {added.map((a) => <ListItem key={`${a.kind}:${a.key}`}><code>{`${a.kind} ${a.key}: ${a.value}`}</code></ListItem>)}
          </List>
        </>
      )}
      <Title headingLevel="h3" size="md">Findings: reported, never changed</Title>
      {(plan.findings ?? []).length === 0 ? <Small>No finding: the namespace follows every rule.</Small> : (
        <List aria-label="Findings">
          {(plan.findings ?? []).map((f, i) => <ListItem key={i}><code>{String(f.rule)}</code> {String(f.message)}</ListItem>)}
        </List>
      )}
      <Title headingLevel="h3" size="md">Not adopted</Title>
      <Small>{unmanaged
        ? `${unmanaged}: adoption takes the Namespace, ResourceQuotas and LimitRanges only.`
        : "No ServiceAccount or RoleBinding: adoption takes the Namespace, ResourceQuotas and LimitRanges only."}</Small>
      <Title headingLevel="h3" size="md">Files</Title>
      {Object.entries(plan.files).map(([path, text]) => (
        <ExpandableSection key={path} toggleText={path} isIndented>
          <CodeBlock><CodeBlockCode>{text}</CodeBlockCode></CodeBlock>
        </ExpandableSection>
      ))}
    </Stack>
  );
}
