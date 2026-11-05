import { Flex, SearchInput, Stack } from "@patternfly/react-core";
import { DataTable, Empty, Filter, Head, Pager, Panel, Pill, RowButton, Small } from "../components/ui";
import type { TabProps } from "../model/types";

export function Requests({ v }: TabProps) {
  const list = v.reqList;
  return (
    <Stack hasGutter>
      <Head title="Requests" lede="Every write you or your team started, newest first. Open one to replay it step by step in the workflow." />
      <Panel>
        <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapMd" }}>
          <div className="cp-combo">
            <SearchInput aria-label="Find a request" placeholder="Find by request ID, namespace or cluster" value={list.text} onChange={(e) => list.onType(e)} onClear={() => list.onType({ target: { value: "" } })} />
          </div>
          <Filter label="Status" options={v.reqFilters} />
        </Flex>
      </Panel>
      <Panel>
        <Pager range={list.range} prev={list.prev} next={list.next} prevDis={list.prevDis} nextDis={list.nextDis} />
        <DataTable
          label="Requests"
          cols={["Request", "Cluster", "Namespace", "Action", "Status", "Where it is", "Approval", "PR", "Updated", ""]}
          rows={v.requests as any[]}
          cells={(r) => [
            r.id, r.cluster, r.ns, r.action, <Pill tone={r.tone}>{r.status}</Pill>,
            <>{r.where}<div><Small>{r.whereN}</Small></div></>,
            r.approval, r.pr, r.when, <RowButton onClick={r.open}>Open at current step</RowButton>
          ]}
        />
        {v.noRequests && <Empty>{`No requests on the ${v.inst.label} instance match this search and filter.`}</Empty>}
        <Small>This list shows the {v.inst.label} instance only; requests for other environments live in their own instance. A request refused before it is stored (a policy rejection or the wrong instance) never appears here.</Small>
        <Flex gap={{ default: "gapSm" }}>
          {v.showReject && <RowButton onClick={v.openReject}>Replay a policy rejection</RowButton>}
          <RowButton onClick={v.openWrong}>Replay a wrong-instance request</RowButton>
        </Flex>
      </Panel>
    </Stack>
  );
}
