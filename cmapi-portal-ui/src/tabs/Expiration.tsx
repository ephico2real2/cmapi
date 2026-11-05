import { ActionGroup, Button, Flex, Form, FormGroup, Grid, GridItem, SearchInput, Stack, TextInput } from "@patternfly/react-core";
import { Callout, type Choice, Checks, Choices, Code, DataTable, Empty, Filter, Head, KV, Pager, Panel, Pill, RowButton, Small } from "../components/ui";
import type { TabProps } from "../model/types";

export function Expiration({ v }: TabProps) {
  const exp = v.exp;
  const d = exp.d;
  return (
    <Stack hasGutter>
      <Head title="Expiration" lede={exp.lede} pill={<Pill>{exp.head}</Pill>} />
      {exp.prod && (
        <Panel>
          <Callout tone="ok" title="Production namespaces never expire">{"A prod request with an expiry gets 422 expiration-not-allowed, the renderer never writes cmapi.net/expires-at or cmapi.net/expiry for prod, and the deny-expiry-in-prod Kyverno policy refuses them in CI and at admission, so a hand edit cannot add them either."}</Callout>
          <KV rows={exp.prodRows} />
        </Panel>
      )}
      {exp.nonprod && (
        <>
          <Panel>
            <Filter label="State" options={exp.states as Choice[]} />
            <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapMd" }}>
              <div className="cp-combo">
                <SearchInput aria-label="Find a namespace or team" placeholder="Find a namespace or team" value={exp.text} onChange={(e) => exp.onType(e)} onClear={() => exp.onType({ target: { value: "" } })} />
              </div>
              <Filter label="Env" options={exp.envs} />
            </Flex>
          </Panel>
          <Panel>
            <Pager range={exp.range} prev={exp.prev} next={exp.next} prevDis={exp.prevDis} nextDis={exp.nextDis} />
            <DataTable
              label="Expiration"
              cols={["Namespace", "Cluster", "Env", "Team", "Expires", "Days left", "Lifetime", "State", ""]}
              rows={exp.rows as any[]}
              selected={(x) => /\b(on|sel|selected)\b/.test(x.cls)}
              cells={(x) => [x.ns, x.cluster, x.env, x.team, x.expires, x.days, x.life, <Pill tone={x.tone}>{x.state}</Pill>, <RowButton onClick={x.pick}>{x.btn}</RowButton>]}
            />
            {exp.empty && <Empty>No namespace matches this state and search.</Empty>}
            <Small>{exp.foot}</Small>
          </Panel>
          {exp.hasSel && (
            <Grid hasGutter>
              <GridItem md={12} lg={6}>
                <Panel title={d.title} pill={<Pill tone={d.tone}>{d.state}</Pill>}>
                  <KV rows={d.rows} />
                  <Small>{d.foot}</Small>
                </Panel>
              </GridItem>
              <GridItem md={12} lg={6}>
                <Panel title={<>Change expiration · {d.ns}</>} pill={<Pill>{d.env} · {d.cluster}</Pill>}>
                  <Form onSubmit={exp.submit}>
                    {d.locked && <Callout tone="warn" title={d.lockTitle}>{d.lockText}</Callout>}
                    {d.open && (
                      <>
                        <FormGroup label="Action" role="group" fieldId="exp-action">
                          <Choices label="Action" options={d.actions} />
                        </FormGroup>
                        {d.setDate && (
                          <FormGroup label="New expiry date" fieldId="exp-until">
                            <TextInput id="exp-until" type="date" min="2026-11-04" value={d.until} onChange={(e) => (d.onUntil as (event: unknown) => void)(e)} />
                          </FormGroup>
                        )}
                        <Checks items={d.checks.map((c: any) => ({ s: c.s, mark: c.mark, main: c.l, note: c.n }))} />
                        <Callout tone={d.apprTone} title={d.apprTitle}>{d.apprDetail}</Callout>
                        <ActionGroup><Button variant="primary" type="submit">{d.btn}</Button></ActionGroup>
                        {d.sent && (
                          <>
                            <Callout tone={d.sentTone} title={d.sentTitle}>{d.sentText}</Callout>
                            <Code text={d.sentBody} />
                          </>
                        )}
                      </>
                    )}
                  </Form>
                </Panel>
              </GridItem>
            </Grid>
          )}
        </>
      )}
    </Stack>
  );
}
