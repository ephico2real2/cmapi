// The Requests tab on GET /api/v1/requests. The words and the columns are the mockup's (mockups/portal/Main.dc.html).
import { Alert, AlertActionLink, Button, EmptyState, EmptyStateBody, Flex, SearchInput, Skeleton, Stack } from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { useEffect, useState } from "react";
import { useRequests } from "../api/hooks";
import type { RequestsQuery } from "../api/hooks";
import { DataTable, Empty, Filter, Head, Pager, Panel, Pill, Small } from "../components/ui";
import { actionOf, approvalOf, prOf, rangeOf, toneOf, whenOf, whereOf } from "./format";
import type { TabProps } from "./route";

const LIMIT = 25;
const STATES = [["all", "All"], ["open", "Open"], ["closed", "Closed"]] as const;
type StateFilter = (typeof STATES)[number][0];
const SEARCH_DELAY_MS = 300;
const WHY_NOT_OPEN = "requests-open-why";

export function RequestsTab({ config, params, setParams }: TabProps) {
  const q = params.get("q") ?? "";
  const wanted = params.get("state");
  const state: StateFilter = STATES.some(([id]) => id === wanted) ? (wanted as StateFilter) : "all";
  // A cursor belongs to one set of filters, so it lives here and not in the address: a shared link starts at page one.
  const [cursor, setCursor] = useState<string | null>(null);
  const [text, setText] = useState(q);
  useEffect(() => setText(q), [q]);

  const apply = (next: { q?: string; state?: StateFilter }) => {
    setCursor(null);
    setParams({ q: next.q ?? q, state: (next.state ?? state) === "all" ? "" : next.state ?? state });
  };
  // The search is a parameter of the API. It goes out when the typing stops, and Query cancels the call it replaces.
  useEffect(() => {
    if (text.trim() === q) return;
    const timer = setTimeout(() => apply({ q: text.trim() }), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  });

  const query: RequestsQuery = { limit: LIMIT };
  if (q) query.q = q;
  if (state !== "all") query.state = state;
  if (cursor) query.cursor = cursor;
  const result = useRequests(query);

  const head = <Head title="Requests" lede="Every write you or your team started, newest first. Open one to replay it step by step in the workflow." />;
  if (result.state === "forbidden") {
    return (
      <Stack hasGutter>
        {head}
        <EmptyState titleText="You do not have permission to see requests." headingLevel="h2" icon={LockIcon}>
          <EmptyStateBody>{result.detail}</EmptyStateBody>
        </EmptyState>
      </Stack>
    );
  }

  const filters = STATES.map(([id, label]) => ({ label, on: id === state, pick: () => apply({ state: id }) }));
  const retry = () => {
    // The API refuses a cursor of other filters (400 invalid-cursor). Page one is always valid.
    if (result.state === "error" && result.code === "invalid-cursor") setCursor(null);
    else result.reload();
  };
  const page = result.state === "ok" ? result.data.page : null;
  const now = new Date();

  return (
    <Stack hasGutter>
      {head}
      <Panel>
        <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapMd" }}>
          <div className="cp-combo">
            <SearchInput aria-label="Find a request" placeholder="Find by request ID, namespace or cluster" value={text} onChange={(_, value) => setText(value)} onClear={() => setText("")} />
          </div>
          <Filter label="Status" options={filters} />
        </Flex>
      </Panel>
      <Panel>
        {result.state === "loading" && (
          <Stack hasGutter><span role="status">Loading requests…</span><Skeleton /><Skeleton /><Skeleton /></Stack>
        )}
        {result.state === "error" && (
          <Alert variant="danger" isInline title="The requests did not load." actionLinks={<AlertActionLink onClick={retry}>Try again</AlertActionLink>}>
            {result.cause}
          </Alert>
        )}
        {result.state === "ok" && page && (
          <>
            <Pager
              range={rangeOf(page)}
              prev={() => page.prevCursor && setCursor(page.prevCursor)}
              next={() => page.nextCursor && setCursor(page.nextCursor)}
              prevDis={!page.prevCursor}
              nextDis={!page.nextCursor}
            />
            <DataTable
              label="Requests"
              cols={["Request", "Cluster", "Namespace", "Action", "Status", "Where it is", "Approval", "PR", "Updated", ""]}
              rows={result.data.items}
              cells={(r) => {
                const where = whereOf(r);
                return [
                  r.requestId, r.clusterId, r.namespace, actionOf(r), <Pill tone={toneOf(r.status)}>{r.status}</Pill>,
                  <>{where.event}<div><Small>{where.by}</Small></div></>,
                  approvalOf(r), prOf(r), whenOf(r.updatedAt, now),
                  <Button variant="secondary" size="sm" isAriaDisabled aria-describedby={WHY_NOT_OPEN}>Open at current step</Button>
                ];
              }}
            />
            {result.data.items.length === 0 && <Empty>{`No requests on the ${config.instance} instance match this search and filter.`}</Empty>}
            {result.data.items.length > 0 && <Small><span id={WHY_NOT_OPEN}>Open at current step is off: the Workflow tab is not on the API yet.</span></Small>}
          </>
        )}
        <Small>This list shows the {config.instance} instance only; requests for other environments live in their own instance. A request refused before it is stored (a policy rejection or the wrong instance) never appears here.</Small>
      </Panel>
    </Stack>
  );
}
