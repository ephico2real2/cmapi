// The Workflow tab on GET /api/v1/requests/{request_id}/events: one request, step by step, one step for each event.
// The words are the mockup's (mockups/portal/Main.dc.html, isWorkflow). MOCKUP-CONTRACT.md lists what the API cannot show.
import {
  Alert, AlertActionLink, Button, Card, CardBody, EmptyState, EmptyStateBody, Flex, FlexItem, Grid, GridItem, Label, List, ListItem,
  ProgressStep, ProgressStepper, Skeleton, Stack, Title
} from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { OPEN_STATES, useEvents, useRequest, useRequests } from "../api/hooks";
import type { ChangeRequest, RequestEvent } from "../api/hooks";
import { Callout, Choices, Empty, Head, KV, Panel, Pill, Small } from "../components/ui";
import { approvalOf, clockOf, durationOf, toneOf } from "./format";
import type { TabProps } from "./route";

/** The mockup's playback pace: one step each 2.6 seconds. */
const PLAY_MS = 2600;
/** The newest requests, as the mockup's scenario buttons. The Requests tab reads the same first page, so Query holds it once. */
const RECENT = 5;
const PAGE = 25;

export function WorkflowTab({ config, params, setParams }: TabProps) {
  const wanted = params.get("request") ?? undefined;
  const recent = useRequests({ limit: PAGE });
  const newest = recent.state === "ok" ? recent.data.items.slice(0, RECENT) : [];
  const id = wanted ?? newest[0]?.requestId;
  const events = useEvents(id);
  const request = useRequest(id);

  const head = (controls?: ReactNode) => (
    <Head
      title="Request workflow"
      lede="Follow a request from the caller's Keycloak token through cmapi, placement on stored capacity snapshots, the cluster-configs pull request and the destination cluster's own Argo CD. Pick a scenario, then step through."
      pill={controls}
    />
  );

  // The scenario buttons: the newest requests, and the one in the address when it is older than those.
  const picks: { requestId: string; meta: string }[] = newest.map((r) => ({ requestId: r.requestId, meta: `${r.namespace} · ${r.status}` }));
  if (id && !picks.some((p) => p.requestId === id)) {
    picks.unshift({ requestId: id, meta: request.state === "ok" ? `${request.data.namespace} · ${request.data.status}` : "" });
  }
  const scenarios = picks.length > 0 && (
    <Choices label="Scenarios" options={picks.map((p) => ({ label: p.requestId, sub: p.meta, on: p.requestId === id, pick: () => setParams({ request: p.requestId }) }))} />
  );

  if (events.state === "forbidden" || request.state === "forbidden" || (!id && recent.state === "forbidden")) {
    const detail = events.state === "forbidden" ? events.detail : request.state === "forbidden" ? request.detail : recent.state === "forbidden" ? recent.detail : "";
    return (
      <Stack hasGutter>
        {head()}
        <EmptyState titleText="You do not have permission to see this request." headingLevel="h2" icon={LockIcon}>
          <EmptyStateBody>{detail}</EmptyStateBody>
        </EmptyState>
      </Stack>
    );
  }
  if (!id) {
    return (
      <Stack hasGutter>
        {head()}
        {recent.state === "loading" && <Stack hasGutter><span role="status">Loading the request…</span><Skeleton /><Skeleton /></Stack>}
        {recent.state === "error" && (
          <Alert variant="danger" isInline title="The request did not load." actionLinks={<AlertActionLink onClick={recent.reload}>Try again</AlertActionLink>}>{recent.cause}</Alert>
        )}
        {recent.state === "ok" && <Empty>{`No requests on the ${config.instance} instance yet.`}</Empty>}
      </Stack>
    );
  }
  const failed = events.state === "error" ? events : request.state === "error" ? request : null;
  if (failed) {
    const retry = () => { events.reload(); request.reload(); };
    return (
      <Stack hasGutter>
        {head()}
        {scenarios}
        <Alert variant="danger" isInline title="The request did not load." actionLinks={<AlertActionLink onClick={retry}>Try again</AlertActionLink>}>{failed.cause}</Alert>
      </Stack>
    );
  }
  if (events.state !== "ok" || request.state !== "ok") {
    return (
      <Stack hasGutter>
        {head()}
        {scenarios}
        <Stack hasGutter><span role="status">Loading the request…</span><Skeleton /><Skeleton /><Skeleton /></Stack>
      </Stack>
    );
  }
  return <Timeline key={id} head={head} scenarios={scenarios} instance={config.instance} request={request.data} events={events.data.events} status={events.data.status} />;
}

interface TimelineProps {
  head: (controls?: ReactNode) => ReactNode;
  scenarios: ReactNode;
  instance: string;
  request: ChangeRequest;
  events: RequestEvent[];
  status: ChangeRequest["status"];
}

/** One request's events as the mockup's playback: the steps, the step in view, and where the request is now. */
function Timeline({ head, scenarios, instance, request, events, status }: TimelineProps) {
  const n = events.length;
  const last = n - 1;
  // null follows the current position: a new event moves the view with it. A step the person picked stays.
  const [picked, setPicked] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const i = picked === null ? last : Math.min(picked, last);
  const at = useRef(i);
  at.current = i;

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      if (at.current >= last) { setPlaying(false); return; }
      setPicked(at.current + 1);
    }, PLAY_MS);
    return () => clearInterval(timer);
  }, [playing, last]);

  const go = (step: number) => { setPlaying(false); setPicked(Math.max(0, Math.min(step, last))); };
  const play = () => {
    if (playing) { setPlaying(false); return; }
    if (i >= last) setPicked(0);
    setPlaying(true);
  };
  const finished = !OPEN_STATES.has(status);

  const controls = n > 0 && (
    <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapSm" }} aria-label="Playback" role="group">
      <Button variant="secondary" onClick={() => go(0)}>Reset</Button>
      <Button variant="secondary" isDisabled={i === 0} onClick={() => go(i - 1)}>Back</Button>
      <Button variant="primary" isDisabled={i === last} onClick={() => go(i + 1)}>Next step</Button>
      <Button variant="secondary" aria-pressed={playing} onClick={play}>{playing ? "Pause" : "Play"}</Button>
      <span aria-live="polite"><Small>{`${i + 1} / ${n}`}</Small></span>
    </Flex>
  );

  const step = events[i];
  const lead = finished ? Date.parse(request.updatedAt) - Date.parse(request.createdAt) : NaN;
  const rows = [
    { k: "ID", v: request.requestId }, { k: "Instance", v: request.instance || instance }, { k: "Cluster", v: request.clusterId },
    { k: "Namespace", v: request.namespace }, { k: "Action", v: request.action }, { k: "Approval", v: approvalOf(request) },
    { k: "Pull request", v: request.pr ? `#${request.pr.number}` : "—" }
  ];
  if (Number.isFinite(lead)) rows.push({ k: "Lead time", v: durationOf(lead) });

  return (
    <Stack hasGutter>
      {head(controls)}
      {n > 0 && (
        <Callout tone={finished ? "ok" : "info"} title="Current position.">
          <Stack hasGutter>
            <span>{`${request.requestId} ${finished ? "finished" : "is"} at step ${n} of ${n}: ${events[last].event}.`}</span>
            {i !== last && <div><Button variant="secondary" size="sm" onClick={() => setPicked(null)}>Back to current step</Button></div>}
          </Stack>
        </Callout>
      )}
      {scenarios}
      <Grid hasGutter>
        <GridItem md={12} lg={3}>
          <Panel title="Steps">
            {n === 0 && <Empty>No events yet.</Empty>}
            <ProgressStepper isVertical aria-label="Steps">
              {events.map((e, j) => (
                <ProgressStep
                  key={j}
                  variant={j < i ? "success" : j === i ? "info" : "pending"}
                  isCurrent={j === i}
                  titleId={`wf-step-${j + 1}`}
                  aria-label={`${e.by}: ${e.event}`}
                  description={e.by}
                >
                  <Button variant="link" isInline onClick={() => go(j)}>{j + 1} {e.event}</Button>
                  {j === last && <> <Label isCompact status="info">current position</Label></>}
                </ProgressStep>
              ))}
            </ProgressStepper>
          </Panel>
        </GridItem>

        <GridItem md={12} lg={6}>
          {step && (
            <Card isCompact component="article" aria-live="polite">
              <CardBody>
                <Stack hasGutter className="cp-wrap">
                  <div><Label isCompact color="blue">{`Step ${i + 1} of ${n} · ${step.by}`}</Label></div>
                  <Title headingLevel="h2" size="xl">{step.event}</Title>
                  {step.note && <p>{step.note}</p>}
                  <Flex gap={{ default: "gapSm" }} alignItems={{ default: "alignItemsCenter" }}>
                    {step.status && <FlexItem><Pill tone={toneOf(step.status as ChangeRequest["status"])}>{step.status}</Pill></FlexItem>}
                    <FlexItem><Small><time dateTime={step.at}>{clockOf(step.at)}</time></Small></FlexItem>
                  </Flex>
                </Stack>
              </CardBody>
            </Card>
          )}
        </GridItem>

        <GridItem md={12} lg={3}>
          <Stack hasGutter>
            <Panel title="Change request" pill={<Pill tone={toneOf(status)}>{status}</Pill>}>
              <KV rows={rows} />
            </Panel>
            <Panel title="Events">
              {n === 0 && <Empty>No events yet.</Empty>}
              <List isPlain>
                {events.map((e, j) => (
                  <ListItem key={j}>
                    <Small><time dateTime={e.at}>{clockOf(e.at)}</time></Small>
                    <div><b>{e.event}</b> <Small>· {e.by}</Small></div>
                    {e.note && <Small>{e.note}</Small>}
                  </ListItem>
                ))}
              </List>
            </Panel>
          </Stack>
        </GridItem>

        <GridItem span={12}>
          <PullRequest request={request} finished={finished} />
        </GridItem>
      </Grid>
    </Stack>
  );
}

/** The mockup's "Pull request · Git" panel, from the request's PR and its files. */
function PullRequest({ request, finished }: { request: ChangeRequest; finished: boolean }) {
  const pr = request.pr;
  const merged = request.mergeSha !== null;
  const files = Object.entries(request.files);
  return (
    <Panel title="Pull request · Git" pill={<Pill tone={pr ? (merged ? "ok" : "info") : undefined}>{pr ? (merged ? "merged" : "open") : "none"}</Pill>}>
      {pr && (
        <>
          <b><a href={pr.url}>{`#${pr.number}`}</a></b>
          <Small>{`${pr.branch} → main`}</Small>
          <List isPlain>
            {files.map(([path, change]) => (
              <ListItem key={path}>
                <Flex justifyContent={{ default: "justifyContentSpaceBetween" }}>
                  <FlexItem className="cp-wrap"><code>{path}</code></FlexItem>
                  <FlexItem>{change}</FlexItem>
                </Flex>
              </ListItem>
            ))}
          </List>
        </>
      )}
      {!pr && <Empty>{finished ? "No pull request. Nothing was written to Git." : "No pull request yet. The worker opens one after the plan and approval are settled."}</Empty>}
    </Panel>
  );
}
