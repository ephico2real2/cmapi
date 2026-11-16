// The Approvals tab on GET /api/v1/requests?status=pending_approval&approver=me, with :approve and :reject.
// The words are the mockup's (mockups/portal/Main.dc.html, isApprovals). The API decides who may approve: the page
// shows its refusal, such as 409 self-approval, and never decides that itself.
import { ActionGroup, Alert, AlertActionLink, Button, EmptyState, EmptyStateBody, FormGroup, Grid, GridItem, List, ListItem, Skeleton, Stack, TextArea } from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { useState } from "react";
import { useApprove, useMe, useReject, useRequests } from "../api/hooks";
import type { ChangeRequest, Me } from "../api/hooks";
import { PERMISSION } from "../api/permissions.generated";
import { Callout, Checks, Head, Hint, KV, Panel, Pill, Small } from "../components/ui";
import type { Check } from "../components/ui";
import { countsOf, groupsOf, whenOf } from "./format";
import type { TabProps } from "./route";

const LIMIT = 25;
const MARK = { pass: "✓", warn: "!", fail: "✕" } as const;
type Verdict = "approved" | "rejected";

export function ApprovalsTab({ config, open }: TabProps) {
  const me = useMe();
  const pending = useRequests({ status: "pending_approval", approver: "me", limit: LIMIT });
  // Each decision made here, with the request as the API answered it. The card stays, with its callout, until the tab
  // is left: the list is not read again at once, so the decision does not vanish from under the person who made it.
  const [decided, setDecided] = useState<Record<string, { verdict: Verdict; request: ChangeRequest; comment: string }>>({});
  const items = pending.state === "ok" ? pending.data.items : [];
  const waiting = items.filter((r) => !decided[r.requestId]).length;

  const head = (
    <Head
      title="Approvals"
      lede={`Requests waiting for a decision on the ${config.instance} instance. Approval happens here, in cmapi, before anything is written to Git: once a request has all its approvals, the worker opens a bot pull request that merges when CI passes. Email links, chat buttons and ServiceNow all end in the same Approve.`}
      pill={pending.state === "ok" ? <Pill>{waiting ? `${waiting} waiting for you` : "nothing waiting for you"}</Pill> : undefined}
    />
  );
  if (pending.state === "forbidden") {
    return (
      <Stack hasGutter>
        {head}
        <EmptyState titleText="You do not have permission to see approvals." headingLevel="h2" icon={LockIcon}>
          <EmptyStateBody>{pending.detail}</EmptyStateBody>
        </EmptyState>
      </Stack>
    );
  }
  return (
    <Stack hasGutter>
      {head}
      {pending.state === "loading" && <Stack hasGutter><span role="status">Loading approvals…</span><Skeleton /><Skeleton /><Skeleton /></Stack>}
      {pending.state === "error" && (
        <Alert variant="danger" isInline title="The approvals did not load." actionLinks={<AlertActionLink onClick={pending.reload}>Try again</AlertActionLink>}>{pending.cause}</Alert>
      )}
      {me.state === "ok" && items.map((r) => (
        <ApprovalCard
          key={r.requestId}
          request={decided[r.requestId]?.request ?? r}
          decision={decided[r.requestId]}
          me={me.data}
          onDecided={(verdict, request, comment) => setDecided((d) => ({ ...d, [r.requestId]: { verdict, request, comment } }))}
          onOpen={() => open("workflow", { request: r.requestId })}
        />
      ))}
      {pending.state === "ok" && items.length === 0 && (
        <Panel title="Nothing waiting for you">
          <Small>Small and medium rnd and dev namespaces are auto-approved by baseline-rnd-namespace, and expired namespaces by expired-namespace. Anything else waits here.</Small>
        </Panel>
      )}
    </Stack>
  );
}

interface CardProps {
  request: ChangeRequest;
  decision?: { verdict: Verdict; comment: string };
  me: Me;
  onDecided: (verdict: Verdict, request: ChangeRequest, comment: string) => void;
  onOpen: () => void;
}

function ApprovalCard({ request: r, decision, me, onDecided, onOpen }: CardProps) {
  const approve = useApprove();
  const reject = useReject();
  const [rejecting, setRejecting] = useState(false);
  const [comment, setComment] = useState("");
  const canReject = me.access.permissions.includes(PERMISSION["POST /api/v1/requests/{request_id}:reject"]);
  const { need, have } = countsOf(r);
  const sending = approve.state === "sending" || reject.state === "sending";
  const refusal = [approve, reject].find((o) => o.state === "refused" || o.state === "error");
  const field = `rej-${r.requestId}`;
  const who = r.requester.requester;

  // The answer of the API is the decision: the card shows the request as it came back. A refusal stays in the hook's state.
  const onApprove = () => approve.approve(r.requestId).then((answer) => onDecided("approved", answer, ""), () => undefined);
  const onReject = () => {
    if (!rejecting) { setRejecting(true); return; }
    const reason = comment.trim();
    if (!reason) return;
    reject.reject(r.requestId, reason).then((answer) => onDecided("rejected", answer, reason), () => undefined);
  };

  let done: { tone: string; title: string; text: string } | null = null;
  if (decision?.verdict === "approved") {
    done = have >= need
      ? { tone: "ok", title: `Approved · ${need} of ${need}`, text: "The request is approved. The worker opens the bot PR now; it merges when CI and the cmapi check pass, and Argo CD applies it." }
      : { tone: "info", title: `Approved by you · ${have} of ${need}`, text: `Your approval is recorded: ${have} of ${need}. Nothing is in Git yet.` };
  } else if (decision?.verdict === "rejected") {
    done = { tone: "bad", title: "Rejected", text: `The requester sees your reason: “${decision.comment}”. Nothing was written to Git, and any reservation is released.` };
  }

  const self = who.username === me.username;
  const elig: Check[] = [
    ...me.access.roles.filter((role) => role.permissions.includes(PERMISSION["POST /api/v1/requests/{request_id}:approve"]))
      .map((role) => ({ s: "pass", mark: MARK.pass, main: `Role ${role.role}`, note: "Keycloak token" })),
    self
      ? { s: r.approval?.selfApproval ? "warn" : "fail", mark: r.approval?.selfApproval ? MARK.warn : MARK.fail, main: "Not the requester", note: "you opened this request" }
      : { s: "pass", mark: MARK.pass, main: "Not the requester", note: `requested by ${who.username}` }
  ];
  const so = r.approval?.approvals.map((a) => a.username).join(", ");

  return (
    <Grid hasGutter>
      <GridItem md={12} lg={8}>
        <Panel title={`${r.requestId} · ${r.namespace} on ${r.clusterId}`} pill={<Pill tone={decision?.verdict === "rejected" ? "bad" : decision && have >= need ? "ok" : "warn"}>{decision?.verdict === "rejected" ? "rejected" : `${have} of ${need} approvals`}</Pill>}>
          <Small>{`${r.action}${r.reason ? ` (${r.reason})` : ""} · requested by ${who.email ?? who.username} · ${whenOf(r.createdAt, new Date())}`}</Small>
          <b>Why it needs approval</b>
          <List>{(r.approval?.reasons ?? []).map((reason, i) => <ListItem key={i}>{reason}</ListItem>)}</List>
          {done && <Callout tone={done.tone} title={done.title}>{done.text}</Callout>}
          {refusal?.state === "refused" && <Callout tone="bad" title={`Refused: ${refusal.code}`}>{refusal.detail}</Callout>}
          {refusal?.state === "error" && <Callout tone="bad" title="Not recorded">{refusal.cause}</Callout>}
          {rejecting && !decision && (
            <FormGroup label="Why are you rejecting it? (required, sent to the requester)" fieldId={field}>
              <TextArea id={field} value={comment} onChange={(_, v) => setComment(v)} />
              {!comment.trim() && <Hint>A reason is required before the request can be rejected.</Hint>}
            </FormGroup>
          )}
          <ActionGroup>
            <Button variant="secondary" onClick={onOpen}>Open at current step</Button>
            {!decision && (
              <>
                {canReject && <Button variant="secondary" isDisabled={sending} onClick={onReject}>{rejecting ? "Confirm reject" : "Reject"}</Button>}
                <Button variant="primary" isDisabled={sending} isLoading={approve.state === "sending"} onClick={onApprove}>Approve</Button>
              </>
            )}
          </ActionGroup>
        </Panel>
      </GridItem>
      <GridItem md={12} lg={4}>
        <Panel title="Your eligibility">
          <Checks items={elig} />
          <b>Approvals so far</b>
          <KV rows={[{ k: "Required", v: `${need} from ${groupsOf(r)}` }, { k: "So far", v: so || "none" }]} />
        </Panel>
      </GridItem>
    </Grid>
  );
}
