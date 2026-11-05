import { Stack } from "@patternfly/react-core";
import { Choices, DataTable, Empty, Head, Panel, Pill, RowButton, Small } from "../components/ui";
import type { TabProps } from "../model/types";

export function Policies({ v }: TabProps) {
  const pol = v.pol;
  return (
    <Stack hasGutter>
      <Head
        title="Policies"
        lede={<>What the Kyverno bundle decided on each cluster of the {v.inst.label} instance, read from the policy reports, beside cmapi's own refusals at plan time and in CI. The same bundle runs in all three places. Pinned for this instance: {pol.pinned}.</>}
        pill={<Pill tone={pol.tone}>{pol.head}</Pill>}
      />
      <Panel title="Clusters">
        <DataTable
          label="Clusters"
          cols={["Cluster", "Env", "Bundle running", "Policies ready", "Pass", "Fail", "Warn", "Error", "Reports"]}
          rows={pol.clusters as any[]}
          cells={(c) => [c.id, c.env, <Pill tone={c.bundleTone}>{c.bundle}</Pill>, c.ready, c.pass, c.fail, c.warn, c.error, <Pill tone={c.stateTone}>{c.state}</Pill>]}
        />
        <Small>Kyverno not installed, an unreachable cluster, and results dropped by the report size breaker show as states, never as zero. A cluster on another bundle tag than the pinned one raises CmapiPolicyBundleDrift after 30 minutes.</Small>
      </Panel>
      <Panel title="Results by policy" pill={<Choices label="Cluster" options={pol.clusterOpts} />}>
        <DataTable
          label="Results by policy"
          cols={["Policy", "Kind", "What it checks", "Pass", "Fail", "Warn", "Error", ""]}
          rows={pol.policies as any[]}
          selected={(x) => x.cls === "sel"}
          cells={(x) => [<code>{x.name}</code>, x.kind, x.what, x.pass, x.fail, x.warn, x.error, <RowButton onClick={x.pick}>{x.btn}</RowButton>]}
        />
        <Small>{pol.legacy}</Small>
      </Panel>
      <Panel title={pol.failTitle}>
        <DataTable
          label="Failing resources"
          cols={["Namespace", "Resource", "Policy", "Result", "Message", "Cluster"]}
          rows={pol.fails as any[]}
          cells={(x) => [x.ns, x.res, x.policy, <Pill tone={x.tone}>{x.result}</Pill>, x.msg, x.cluster]}
        />
        {pol.noFails && <Empty>Nothing failing for this selection.</Empty>}
        <Small>GET /api/v1/policies/results?result=fail,warn,error · filtered to the environments your roles cover · paged like every list.</Small>
      </Panel>
      <Panel title="Refused by cmapi before Git · last 7 days">
        <DataTable
          label="Refused by cmapi before Git"
          cols={["When", "Where", "Stage", "Policy or check", "Detail"]}
          rows={pol.rejections as any[]}
          cells={(x) => [x.when, x.where, x.stage, <code>{x.policy}</code>, x.detail]}
        />
        <Small>GET /api/v1/policies/rejections?since=7d · plan-time refusals never become requests, so they are listed here rather than under Requests.</Small>
      </Panel>
    </Stack>
  );
}
