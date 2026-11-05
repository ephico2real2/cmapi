import { Button, Card, CardBody, Flex, FlexItem, Gallery, Grid, GridItem, Label, List, ListItem, ProgressStep, ProgressStepper, Stack, Title } from "@patternfly/react-core";
import { Callout, Checks, Choices, Code, DataTable, Empty, Head, KV, Panel, Pill, Small } from "../components/ui";
import type { TabProps } from "../model/types";

// The lanes keep one colour across the page, as in the mockup. Its hex values map to PatternFly's label colours.
const LANE = { "#6a57c9": "purple", "#a03c86": "yellow", "#1f5fd1": "blue", "#5b7d1a": "green", "#b15a1c": "orange", "#0e8487": "teal" } as const;
const laneColor = (hex?: string) => LANE[hex as keyof typeof LANE] ?? "grey";

const STEP = { now: "info", done: "success" } as const;
// A step after a request's current position has not happened: "ahead" shows what comes next, even once stepped past.
const stepVariant = (cls: string) => (cls.includes("ahead") ? "pending" : STEP[cls as keyof typeof STEP] ?? "pending");

export function Workflow({ v }: TabProps) {
  const wf = v.wf;
  return (
    <Stack hasGutter>
      <Head
        title="Request workflow"
        lede="Follow a request from the caller's Keycloak token through cmapi, placement on stored capacity snapshots, the cluster-configs pull request and the destination cluster's own Argo CD. Pick a scenario, then step through."
        pill={
          <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapSm" }} aria-label="Playback" role="group">
            <Button variant="secondary" onClick={v.wfReset}>Reset</Button>
            <Button variant="secondary" isDisabled={wf.atStart} onClick={v.wfBack}>Back</Button>
            <Button variant="primary" isDisabled={wf.atEnd} onClick={v.wfNext}>Next step</Button>
            <Button variant="secondary" aria-pressed={wf.playing === "true"} onClick={v.wfPlay}>{wf.playLabel}</Button>
            <span aria-live="polite"><Small>{wf.counter}</Small></span>
          </Flex>
        }
      />

      {wf.banner.show && (
        <Callout tone={wf.banner.tone} title="Current position.">
          <Stack hasGutter>
            <span>{wf.banner.text}</span>
            {wf.banner.backShow && <div><Button variant="secondary" size="sm" onClick={wf.banner.back}>Back to current step</Button></div>}
          </Stack>
        </Callout>
      )}

      <Choices label="Scenarios" options={wf.scenarios.map((s: any) => ({ label: s.label, sub: s.meta, on: s.on, pick: s.pick }))} />

      <Gallery hasGutter minWidths={{ default: "160px" }} aria-label="Systems involved" component="section">
        {wf.nodes.map((n: any) => (
          <Card key={n.name} isCompact className={n.cls === "active" ? "cp-active" : undefined} aria-current={n.cls === "active" ? "step" : undefined}>
            <CardBody>
              <Stack className="cp-wrap">
                <div><Label isCompact variant={n.cls === "idle" ? "outline" : "filled"} color={n.cls === "blocked" ? "red" : laneColor(n.color)}>{n.name}</Label></div>
                <Small>{n.sub}</Small>
                <b>{n.st}</b>
              </Stack>
            </CardBody>
          </Card>
        ))}
      </Gallery>

      <Grid hasGutter>
        <GridItem md={12} lg={3}>
          <Panel title="Steps">
            <ProgressStepper isVertical aria-label="Steps">
              {wf.steps.map((s: any) => (
                <ProgressStep
                  key={s.n}
                  variant={stepVariant(s.cls)}
                  isCurrent={s.current === "step"}
                  titleId={`wf-step-${s.n}`}
                  aria-label={`${s.lane}: ${s.title}`}
                  description={s.lane}
                >
                  <Button variant="link" isInline onClick={s.pick}>{s.n} {s.title}</Button>
                  {s.isPos && <> <Label isCompact status="info">current position</Label></>}
                </ProgressStep>
              ))}
            </ProgressStepper>
          </Panel>
        </GridItem>

        <GridItem md={12} lg={6}>
          <Card isCompact component="article" aria-live="polite">
            <CardBody>
              <Stack hasGutter className="cp-wrap">
                <div><Label isCompact color={laneColor(wf.detail.color)}>{wf.detail.eyebrow}</Label></div>
                <Title headingLevel="h2" size="xl">{wf.detail.title}</Title>
                <p>
                  {wf.detail.runs.map((r: any, i: number) => (r.b ? <b key={i}>{r.t}</b> : r.c ? <code key={i}>{r.t}</code> : <span key={i}>{r.t}</span>))}
                </p>
                {wf.detail.hasChecks && <Checks items={wf.detail.checks.map((c: any) => ({ s: c.s, mark: c.mark, main: c.l, note: c.n }))} />}
                {wf.detail.hasCode && <Code label={wf.detail.codeLabel} text={wf.detail.lines.map((l: any) => l.t).join("\n")} />}
              </Stack>
            </CardBody>
          </Card>
        </GridItem>

        <GridItem md={12} lg={3}>
          <Stack hasGutter>
            <Panel title={wf.reqHead} pill={<Pill tone={wf.reqPill.tone}>{wf.reqPill.t}</Pill>}>
              <KV rows={wf.reqRows} />
            </Panel>
            <Panel title="Events">
              {wf.noEvents && <Empty>No events yet.</Empty>}
              <List isPlain>
                {wf.events.map((e: any, i: number) => (
                  <ListItem key={i}>
                    <Small><time>{e.time}</time></Small>
                    <div><b>{e.type}</b> <Small>· {e.actor}</Small></div>
                    <Small>{e.msg}</Small>
                  </ListItem>
                ))}
              </List>
            </Panel>
          </Stack>
        </GridItem>

        <GridItem span={12}>
          <Panel title="Capacity · cmapi-capacity" pill={<Pill tone={wf.cap.tone}>{wf.cap.pill}</Pill>}>
            {wf.cap.has && (
              <>
                <b>{wf.cap.title}</b>
                <Small>{wf.cap.meta}</Small>
                <DataTable
                  label="Capacity"
                  cols={wf.cap.cols}
                  rows={wf.cap.rows as any[][]}
                  cells={(row) => row.map((cell: any) => (cell.pill ? <Pill tone={cell.tone}>{cell.t}</Pill> : cell.t))}
                />
              </>
            )}
            <Small>{wf.cap.note}</Small>
          </Panel>
        </GridItem>

        <GridItem md={12} lg={6}>
          <Panel title="Pull request · Git" pill={<Pill tone={wf.pr.tone}>{wf.pr.pill}</Pill>}>
            {wf.pr.has && (
              <>
                <b>{wf.pr.title}</b>
                <Small>{wf.pr.meta}</Small>
                <List isPlain>
                  {wf.pr.files.map((f: any) => (
                    <ListItem key={f.path}>
                      <Flex justifyContent={{ default: "justifyContentSpaceBetween" }}>
                        <FlexItem><code>{f.path}</code></FlexItem>
                        <FlexItem>+{f.add} −{f.del}</FlexItem>
                      </Flex>
                    </ListItem>
                  ))}
                </List>
                <Checks items={wf.pr.checks.map((c: any) => ({ s: c.s, mark: c.mark, main: c.n, note: c.note }))} />
                <Flex gap={{ default: "gapSm" }}>{wf.pr.reviewers.map((r: any, i: number) => <Pill key={i} tone={r.tone}>{r.t}</Pill>)}</Flex>
              </>
            )}
            {wf.pr.none && <Empty>{wf.pr.msg}</Empty>}
          </Panel>
        </GridItem>

        <GridItem md={12} lg={6}>
          <Panel
            title={<>Argo CD · {wf.argo.cluster}</>}
            pill={<Flex gap={{ default: "gapSm" }}><Pill tone={wf.argo.syncTone}>{wf.argo.sync}</Pill><Pill tone={wf.argo.healthTone}>{wf.argo.health}</Pill></Flex>}
          >
            <b>{wf.argo.app}</b>
            <Small>{wf.argo.meta}</Small>
            {wf.argo.blocked && <Empty>Not reached. The live objects below are unchanged.</Empty>}
            {wf.argo.empty && <Empty>{wf.argo.note}</Empty>}
            {wf.argo.hasRes && (
              <DataTable
                label="Argo CD resources"
                cols={["Wave", "Kind", "Name", "Applied by", "Status", "Detail"]}
                rows={wf.argo.resources as any[]}
                cells={(r) => [r.wave, r.kind, r.name, r.by, <Pill tone={r.tone}>{r.st}</Pill>, r.ch]}
              />
            )}
          </Panel>
        </GridItem>
      </Grid>
    </Stack>
  );
}
