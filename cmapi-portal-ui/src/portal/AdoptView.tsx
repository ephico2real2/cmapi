// The Adopt view of the Namespaces tab (story #26; mockup docs/reviews/2026-11-14-issue-26-adoption/mockup-adopt.html): an
// existing namespace that cmapi does not manage is adopted through a request, its approvals and a pull request, as the
// adoption design says (docs/reviews/2026-11-14-issue-26-adoption/README.md). MOCKUP-CONTRACT.md lists what differs.
//
// The workflow, step by step (each step's function is named):
//   1. AdoptView: the candidates of the cluster (useAdoptionList "candidates") and the labelled namespaces that a rule skips
//      (useAdoptionList "skipped"), each read now from the cluster.
//   2. "Adopt <ns>" opens AdoptOne, whose address is #namespaces?view=adopt&cluster=<id>&adopt=<ns>.
//   3. Check (dry run): POST .../namespaces/{ns}:adopt?dryRun=true (useAdoptPlan). The plan shows the objects read, its findings,
//      the keys under a skip prefix, what stays unmanaged, the files and the approval. Nothing is written.
//   4. Submit adoption request: the same body with one Idempotency-Key (useSubmitAdoption); a 202 shows the request.
import {
  ActionGroup, Alert, AlertActionLink, Button, CodeBlock, CodeBlockCode, EmptyState, EmptyStateBody, ExpandableSection, Form, FormGroup, Grid,
  GridItem, Label, List, ListItem, Skeleton, Stack, TextArea, Title
} from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { useAdoptionList, useAdoptPlan, useSubmitAdoption } from "../api/hooks";
import type { AdoptionStanding, ChangeRequest, Cluster, Plan, PlannedAdoption } from "../api/hooks";
import { ApiProblem } from "../api/problem";
import { Callout, Hint, Panel, Small } from "../components/ui";
import { approvalCard } from "./plan";
import type { TabProps } from "./route";

const PASSED = "The check passed (dry run, 200). Nothing is written yet.";

/** The candidates and the skipped namespaces of one cluster, and the adoption of one of them. */
export function AdoptView({ cluster, adopt, onAdopt, open }: { cluster: Cluster; adopt: string; onAdopt: (ns: string) => void; open: TabProps["open"] }) {
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
      {adopt && <AdoptOne key={`${cluster.clusterId}/${adopt}`} cluster={cluster} ns={adopt} open={open} />}
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
                <Td dataLabel="Actions"><Button variant="secondary" size="sm" onClick={() => onAdopt(s.name)}>{`Adopt ${s.name}`}</Button></Td></>
              : <Td dataLabel="Why it is not adopted" modifier="breakWord">{`${s.rule}: ${s.detail}`}</Td>}
          </Tr>
        ))}
      </Tbody>
    </Table>
  );
}

/** The plan of one adoption beside its Justification, Check and Submit. */
function AdoptOne({ cluster, ns, open }: { cluster: Cluster; ns: string; open: TabProps["open"] }) {
  const [why, setWhy] = useState("");
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
  const current: PlannedAdoption = { clusterId: cluster.clusterId, ns, justification: why.trim() };
  const planIsOfForm = asked !== null && JSON.stringify(asked) === JSON.stringify(current);
  const planOk = plan.state === "ok" && planIsOfForm ? plan.data : null;
  const canSubmit = planOk !== null && submit.state !== "sending" && done === null;

  const onCheck = () => {
    setDone(null);
    setNotSent(null);
    if (!current.justification) { setProblem("Justification: say why this namespace is adopted."); return; }
    setProblem(null);
    if (planIsOfForm) plan.reload();
    else setAsked(current);
  };
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
          <Small>{`${(planOk.findings ?? []).length} findings · ${planOk.adoption?.objects.length ?? 0} objects read · ${appr.rule}`}</Small>
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
        <Panel title={`Adopt ${ns}`}>
          {planOk ? <PlanDetail plan={planOk} /> : <Small>Press Check (dry run) to read the namespace from the cluster and see what its adoption writes.</Small>}
        </Panel>
      </GridItem>
      <GridItem md={5} className="cp-sticky">
        <Panel title="Your adoption">
          <Form noValidate onSubmit={onSubmit}>
            <FormGroup label="Justification (required)" fieldId="adopt-why">
              <TextArea id="adopt-why" value={why} rows={2} placeholder="Why this namespace is adopted" onChange={(_, v) => { setWhy(v); setDone(null); }} />
            </FormGroup>
            <div id="adopt-status">{status()}</div>
            <ActionGroup>
              <Button variant="secondary" type="button" onClick={onCheck}>Check (dry run)</Button>
              <Button variant="primary" type="submit" isAriaDisabled={!canSubmit} aria-describedby="adopt-status" isLoading={submit.state === "sending"}>Submit adoption request</Button>
            </ActionGroup>
          </Form>
        </Panel>
      </GridItem>
    </Grid>
  );
}

/** What the plan read and writes: the objects, the findings, the skipped keys, what stays unmanaged, and each file. */
function PlanDetail({ plan }: { plan: Plan }) {
  const adoption = plan.adoption;
  const unmanaged = Object.entries(adoption?.notAdopted ?? {}).filter(([, n]) => n !== 0);
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
      <Title headingLevel="h3" size="md">Findings: reported, never changed</Title>
      {(plan.findings ?? []).length === 0 ? <Small>No finding: the namespace follows every rule.</Small> : (
        <List aria-label="Findings">
          {(plan.findings ?? []).map((f, i) => <ListItem key={i}><code>{String(f.rule)}</code> {String(f.message)}</ListItem>)}
        </List>
      )}
      <Title headingLevel="h3" size="md">Not adopted</Title>
      <Small>{unmanaged.length > 0
        ? `${unmanaged.map(([kind, n]) => `${n ?? "An unknown number of"} ${kind}s`).join(" and ")} stay unmanaged: adoption takes the Namespace, ResourceQuotas and LimitRanges only.`
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
