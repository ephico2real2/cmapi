import { ActionGroup, Button, Flex, FlexItem, Form, FormGroup, FormSelect, FormSelectOption, Grid, GridItem, Label, Stack, TextArea, TextInput } from "@patternfly/react-core";
import { Callout, Checks, Choices, Head, Hint, KV, Panel, Pill, Small } from "../components/ui";
import type { TabProps } from "../model/types";

export function NewNamespace({ v }: TabProps) {
  // renderVals adds these three after building the object, which type inference cannot follow.
  const appr = v.appr as typeof v.appr & { quota: string; expires: string; path: string };
  const rows = [
    ...v.place.ranked.map((p: any) => ({ rank: p.rank, cluster: p.cluster, detail: p.detail, end: p.score, top: p.cls === "top" })),
    ...v.place.excluded.map((p: any) => ({ rank: "—", cluster: p.cluster, detail: p.detail, end: <Pill tone="warn">{p.reason}</Pill>, top: false }))
  ];
  return (
    <Stack hasGutter>
      <Head title="New namespace" lede="Describe what you need. cmapi picks the cluster from stored capacity snapshots, shows the approval that will apply, and turns the request into a pull request." />
      <Grid hasGutter>
        <GridItem md={12} lg={7}>
          <Panel>
            <Form onSubmit={v.nsSubmit}>
              <FormGroup label="Environment" role="group" fieldId="ns-env">
                <Choices label="Environment" options={v.envOpts} />
                <Hint>This is the {v.inst.display} portal: it serves {v.inst.envs} only.</Hint>
                <Flex gap={{ default: "gapMd" }}>
                  {v.elsewhere.map((x: any) => <Small key={x.label}>{x.envs} → <a href={x.href}>{x.label}</a></Small>)}
                </Flex>
              </FormGroup>
              <Grid hasGutter>
                <GridItem md={6}>
                  <FormGroup label="Team" fieldId="ns-team">
                    <TextInput id="ns-team" value={v.form.team} onChange={(e) => v.onTeam(e)} />
                    <Hint>Who owns it, for cost and notices: any team name. Not checked against who you are; your Keycloak roles decide what you may do.</Hint>
                  </FormGroup>
                </GridItem>
                <GridItem md={6}>
                  <FormGroup label="Region" fieldId="ns-region">
                    <FormSelect id="ns-region" value={v.form.region} onChange={(e) => v.onRegion(e)}>
                      <FormSelectOption value="us-central" label="us-central" />
                      <FormSelectOption value="any" label="Any region" />
                    </FormSelect>
                    <Hint>From clusters.yaml metadata.</Hint>
                  </FormGroup>
                </GridItem>
              </Grid>
              <FormGroup label="Namespace name" fieldId="ns-name">
                <TextInput id="ns-name" value={v.nsName} onChange={(e) => v.onName(e)} />
                <Hint>Any DNS-1123 name. Not allowed: reserved names (default, openshift-*, kube-*, cmapi-system, ocp-*) and a name already on the cluster outside cmapi.</Hint>
              </FormGroup>
              <FormGroup label="Tier" role="group" fieldId="ns-tier">
                <Choices label="Tier" options={v.tierOpts} />
                <Hint>cmapi writes the tier's ResourceQuota and LimitRange (config/tiers.yaml) into the namespace folder.</Hint>
              </FormGroup>
              <Grid hasGutter>
                <GridItem md={6}>
                  <FormGroup label="Team DL (required)" fieldId="ns-dl">
                    <TextInput id="ns-dl" type="email" defaultValue="payments-team@ephico2real.com" />
                    <Hint>Your team's distribution list, in one of the organisation's email domains (emailDomains); format only. Requested by ola (ola@ephico2real.com), from your sign-in.</Hint>
                  </FormGroup>
                </GridItem>
                <GridItem md={6}>
                  {v.nsExp.allowed && (
                    <FormGroup label="Expires (optional)" fieldId="ns-exp">
                      <TextInput id="ns-exp" type="date" min="2026-11-04" max={v.nsExp.max} value={v.nsExp.value} onChange={(e) => v.nsExp.onDate(e)} />
                      <Hint>{v.nsExp.hint}</Hint>
                    </FormGroup>
                  )}
                  {v.nsExp.prod && (
                    <FormGroup label="Expires" fieldId="ns-exp-never">
                      <Hint>Never. Production namespaces cannot carry expiration metadata: refused at validation and by the deny-expiry-in-prod policy.</Hint>
                    </FormGroup>
                  )}
                </GridItem>
              </Grid>
              <FormGroup label="Justification" fieldId="ns-why">
                <TextArea id="ns-why" defaultValue="Payments service namespace for the settlement API." />
              </FormGroup>
              {v.dry.show && (
                <Callout tone="info" title="Dry run passed · nothing written">
                  <Checks items={v.dry.checks.map((c: any) => ({ s: c.s, mark: c.mark, main: c.l, note: c.n }))} />
                </Callout>
              )}
              <ActionGroup>
                <Button variant="secondary" type="button" onClick={v.nsDry}>Dry run</Button>
                <Button variant="primary" type="submit">Submit request</Button>
              </ActionGroup>
            </Form>
          </Panel>
        </GridItem>
        <GridItem md={12} lg={5}>
          <Stack hasGutter>
            <Panel title="Placement preview" pill={<Pill>{v.place.asOf}</Pill>}>
              <Small>{v.place.lede}</Small>
              {rows.map((r) => (
                <Flex key={r.cluster} alignItems={{ default: "alignItemsCenter" }} flexWrap={{ default: "nowrap" }}>
                  <FlexItem><Label isCompact status={r.top ? "success" : undefined}>{r.rank}</Label></FlexItem>
                  <FlexItem grow={{ default: "grow" }} style={{ minWidth: 0 }}>
                    <b>{r.cluster}</b>
                    <div><Small>{r.detail}</Small></div>
                  </FlexItem>
                  <FlexItem>{r.end}</FlexItem>
                </Flex>
              ))}
            </Panel>
            <Panel title="Approval that will apply">
              <Callout tone={appr.tone} title={appr.title}>{appr.detail}</Callout>
              <KV rows={[{ k: "Rule", v: appr.rule }, { k: "Quota", v: appr.quota }, { k: "Expires", v: appr.expires }, { k: "Lands in Git", v: appr.path }]} />
            </Panel>
          </Stack>
        </GridItem>
      </Grid>
    </Stack>
  );
}
