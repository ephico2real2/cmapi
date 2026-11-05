import { ActionGroup, Button, FormGroup, Grid, GridItem, List, ListItem, Stack, TextArea } from "@patternfly/react-core";
import { Callout, Checks, DataTable, Head, Hint, KV, Panel, Pill, Small } from "../components/ui";
import type { TabProps } from "../model/types";

export function Approvals({ v }: TabProps) {
  const apv = v.apv;
  return (
    <Stack hasGutter>
      <Head
        title="Approvals"
        lede={<>Requests waiting for a decision on the {v.inst.label} instance. Approval happens here, in cmapi, before anything is written to Git: once a request has all its approvals, the worker opens a bot pull request that merges when CI passes. Email links, chat buttons and ServiceNow all end in the same Approve.</>}
        pill={<Pill>{apv.head}</Pill>}
      />
      {apv.items.map((a: any) => (
        <Grid hasGutter key={a.cid}>
          <GridItem md={12} lg={8}>
            <Panel title={a.title} pill={<Pill tone={a.tone}>{a.count}</Pill>}>
              <Small>{a.meta}</Small>
              <b>Why it needs approval</b>
              <List>{a.reasons.map((r: any, i: number) => <ListItem key={i}>{r.t}</ListItem>)}</List>
              {a.hasUsage && (
                <>
                  <b>Live usage · last 14 days</b>
                  <DataTable
                    label="Live usage"
                    cols={["Resource", "Now", "7d avg", "p95", "Peak", "Quota"]}
                    rows={a.usage as any[]}
                    cells={(u) => [u.k, u.now, u.avg, u.p95, u.peak, u.quota]}
                  />
                </>
              )}
              <Small>{a.foot}</Small>
              {a.decided && <Callout tone={a.doneTone} title={a.doneTitle}>{a.doneText}</Callout>}
              {a.rejecting && (
                <FormGroup label="Why are you rejecting it? (required, sent to the requester)" fieldId={a.cid}>
                  <TextArea id={a.cid} value={a.comment} onChange={(e) => a.onComment(e)} />
                  <Hint>{a.commentHint}</Hint>
                </FormGroup>
              )}
              <ActionGroup>
                <Button variant="secondary" onClick={a.open}>Open at current step</Button>
                {a.canAct && (
                  <>
                    <Button variant="secondary" onClick={a.reject}>{a.rejectLabel}</Button>
                    <Button variant="primary" onClick={a.approve}>Approve</Button>
                  </>
                )}
              </ActionGroup>
            </Panel>
          </GridItem>
          <GridItem md={12} lg={4}>
            <Panel title="Your eligibility">
              <Checks items={a.elig.map((c: any) => ({ s: c.s, mark: c.mark, main: c.l, note: c.n }))} />
              <b>Approvals so far</b>
              <KV rows={a.so} />
              <b>How approvers were told</b>
              <Small>{a.channels}</Small>
            </Panel>
          </GridItem>
        </Grid>
      ))}
      {apv.none && <Panel title="Nothing waiting for you"><Small>{"Small and medium rnd and dev namespaces are auto-approved by baseline-rnd-namespace, and expired namespaces by expired-namespace. Anything else waits here."}</Small></Panel>}
      <Panel title="Recently decided"><KV rows={apv.recent} /></Panel>
    </Stack>
  );
}
