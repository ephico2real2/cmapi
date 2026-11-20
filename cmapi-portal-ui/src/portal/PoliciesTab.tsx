// The Policies tab on GET /api/v1/policies/results and /policies/rejections (#302). The words are the mockup's
// (mockups/portal/Main.dc.html, isPolicies and policiesView()). MOCKUP-CONTRACT.md lists what differs, and why.
// No policy is named here: the API's `policies` come from the bundle that cmapi renders (#333 widens it).
import { Alert, AlertActionLink, Button, EmptyState, EmptyStateBody, Skeleton, Stack } from "@patternfly/react-core";
import { LockIcon } from "@patternfly/react-icons";
import { useState } from "react";
import type { ReactNode } from "react";
import { usePolicyRejections, usePolicyResults } from "../api/hooks";
import type { PolicyCluster, PolicyResultPage, PolicyResultsQuery, PolicySummary, Rejection, RejectionsQuery } from "../api/hooks";
import { Callout, Choices, DataTable, Empty, Head, Pager, Panel, Pill, Small } from "../components/ui";
import type { Choice } from "../components/ui";
import { whenOf } from "./format";
import type { TabProps } from "./route";

const LIMIT = 25;
const RESULTS = "fail,warn,error";
const SINCE = "7d";

/** Each state of a cluster's reports: its word and its tone. Never a zero for what is not known (docs/14, the API's states). */
const STATE: Record<PolicyCluster["state"], (c: PolicyCluster) => [string, string]> = {
  ok: () => ["ok", "ok"],
  loading: () => ["loading", "info"],
  "not-installed": () => ["Kyverno not installed", "info"],
  forbidden: () => ["no access to the reports", "bad"],
  "not-imported": () => ["not imported", "info"],
  unreachable: (c) => [`unreachable${c.asOf ? ` since ${clock(c.asOf)}` : ""}`, "bad"],
  stale: (c) => [`stale since ${c.asOf ? clock(c.asOf) : "—"}`, "warn"],
  capped: (c) => [`${c.dropped ?? 0} rows not listed`, "warn"],
  drift: () => ["off the bundle", "warn"],
  "mode-off": () => ["mode off", "info"],
  "engine-off": () => ["Kyverno off", "info"]
};
/** The mockup's result tones: fail bad, warn warn, error info. */
const RESULT_TONE: Record<string, string> = { fail: "bad", warn: "warn", error: "info" };
const KIND_WORD: Record<string, string> = { label: "label", annotation: "annotation", quota: "quota", limit: "limit" };

const clock = (iso: string): string => new Date(iso).toISOString().slice(11, 16);
const count = (n: number | null | undefined): string => (n === null || n === undefined ? "—" : String(n));

/** "label cmapi.net/team: pattern", from the bundle's index.json; a hand-written policy has its description. */
function whatOf(p: PolicySummary): string {
  if (!p.check) return p.description ?? "—";
  return `${KIND_WORD[p.check.kind] ?? p.check.kind} ${p.check.key ?? "keys that no stanza declares"}: ${p.check.rule}`;
}

/** The bundle on the cluster, in a word: current, or what is off. The totals, never the name lists, which stop at 20. */
function bundleOf(c: PolicyCluster): [string, string] {
  const b = c.bundle;
  if (!b) return ["—", ""];
  const missing = b.expected - b.live, differ = b.live - b.current;
  const off = [missing && `${missing} missing`, differ && `${differ} differ`,
    b.actionsDifferTotal && `${b.actionsDifferTotal} with other actions`].filter(Boolean);
  return off.length ? [off.join(", "), "warn"] : ["current", "ok"];
}

/** "audit", or "audit (cluster: Deny)" when the cluster's copies carry other actions than the configured mode's. */
function modeOf(c: PolicyCluster): string {
  return c.bundle && c.bundle.actionsDifferTotal && c.liveActions.length ? `${c.mode} (cluster: ${c.liveActions.join(", ")})` : c.mode;
}

/** "Kyverno v1.20.0; audit in dev, rnd": the engine, the pinned CLI and each environment's mode (GET /admin/integrations' policy). */
function pinnedOf(policy: PolicyResultPage["policy"]): string {
  if (policy.engine === "none") return "no policy engine (policy.engine: none)";
  const byMode = new Map<string, string[]>();
  for (const [env, mode] of Object.entries(policy.environments)) byMode.set(mode, [...(byMode.get(mode) ?? []), env]);
  const modes = [...byMode].map(([mode, envs]) => `${mode} in ${envs.join(", ")}`).join("; ");
  return `${policy.kyvernoVersion ? `Kyverno ${policy.kyvernoVersion}` : "no Kyverno CLI pinned (outside the image)"}; ${modes}`;
}

export function PoliciesTab({ config, params, setParams }: TabProps) {
  // The view of the address: the mockup's pcluster and ppolicy.
  const cluster = params.get("cluster") ?? "";
  const policy = params.get("policy") ?? "";
  // A cursor belongs to one set of filters, so it lives here and not in the address.
  const [cursor, setCursor] = useState<string | null>(null);
  const [refusedCursor, setRefusedCursor] = useState<string | null>(null);
  const apply = (next: { cluster?: string; policy?: string }) => {
    setCursor(null);
    setParams({ cluster, policy, ...next });
  };

  const query: PolicyResultsQuery = { result: RESULTS, limit: LIMIT };
  if (cluster) query.clusterId = cluster;
  if (policy) query.policy = policy;
  if (cursor) query.cursor = cursor;
  const result = usePolicyResults(query);
  const refusedQuery: RejectionsQuery = { since: SINCE, limit: LIMIT };
  if (refusedCursor) refusedQuery.cursor = refusedCursor;
  const refused = usePolicyRejections(refusedQuery);

  const page = result.state === "ok" ? result.data : null;
  const busy = result.state === "ok" && result.refreshing;
  const engineOff = page?.policy.engine === "none";
  const known = page?.clusters.filter((c) => c.counts !== null) ?? [];
  // With no cluster's counts known, the head says so: a sum over nothing is not "0 failing".
  const failing = known.length ? String(known.reduce((n, c) => n + (c.counts?.fail ?? 0), 0)) : "—";
  const drift = page?.clusters.filter((c) => bundleOf(c)[1] === "warn").length ?? 0;
  const pillTone = drift || (known.length && failing !== "0") ? "warn" : known.length ? "ok" : "info";
  const head = (
    <Head
      title="Policies"
      lede={`What the Kyverno bundle decided on each cluster of the ${config.instance} instance, read from the policy reports, beside cmapi's own refusals at plan time and in CI. The same bundle runs in all three places. Pinned for this instance: ${page ? pinnedOf(page.policy) : "…"}.`}
      pill={page && !engineOff ? <Pill tone={pillTone}>{`${failing} failing · ${drift} cluster${drift === 1 ? "" : "s"} off the bundle`}</Pill> : undefined}
    />
  );
  const rejections = <Refused result={refused} setCursor={setRefusedCursor} />;

  if (result.state === "forbidden") {
    return (
      <Stack hasGutter>
        {head}
        <EmptyState titleText="You do not have permission to see policy results." headingLevel="h2" icon={LockIcon}>
          <EmptyStateBody>{result.detail}</EmptyStateBody>
        </EmptyState>
      </Stack>
    );
  }
  if (engineOff) {
    return (
      <Stack hasGutter>
        {head}
        <Callout tone="info" title="Kyverno is off on this instance">{"policy.engine is none: no cluster report is read, and no policy is rendered. cmapi's own checks still refuse at plan time; their refusals are below."}</Callout>
        {rejections}
      </Stack>
    );
  }

  const stale = result.state === "error" && result.code === "invalid-cursor";
  const inScope = (c: PolicyCluster) => !cluster || c.clusterId === cluster;
  const hidden = known.filter(inScope).reduce((h, c) => ({ unmanaged: h.unmanaged + (c.hidden?.unmanaged ?? 0),
    other: h.other + (c.hidden?.otherPolicies ?? 0), gone: h.gone + (c.hidden?.stale ?? 0) }), { unmanaged: 0, other: 0, gone: 0 });
  const chips: Choice[] = [["", "All clusters"], ...known.map((c) => [c.clusterId, c.clusterId])].map(([id, label]) => (
    { label, on: cluster === id, pick: () => apply({ cluster: id }) }));
  const sent = [`result=${RESULTS}`, cluster && `clusterId=${cluster}`, policy && `policy=${policy}`].filter(Boolean).join("&");
  const title = `Failing, warning and erroring resources${policy ? ` · ${policy}` : ""}${cluster ? ` · ${cluster}` : ""}`;

  return (
    <Stack hasGutter>
      {head}
      <Panel title="Clusters">
        {result.state === "loading" && <Stack hasGutter><span role="status">Loading the policy results…</span><Skeleton /><Skeleton /></Stack>}
        {result.state === "error" && !stale && (
          <Alert variant="danger" isInline title="The policy results did not load." actionLinks={<AlertActionLink onClick={result.reload}>Try again</AlertActionLink>}>{result.cause}</Alert>
        )}
        {page && (
          <>
            <DataTable
              label="Clusters"
              cols={["Cluster", "Env", "Mode", "Bundle running", "Policies ready", "Pass", "Fail", "Warn", "Error", "Reports"]}
              rows={page.clusters}
              cells={(c) => {
                const [bundle, bundleTone] = bundleOf(c), [word, tone] = STATE[c.state](c);
                return [c.clusterId, c.env, modeOf(c), bundleTone ? <Pill tone={bundleTone}>{bundle}</Pill> : bundle,
                  c.bundle ? `${c.bundle.ready} / ${c.bundle.expected}` : "—", count(c.counts?.pass), count(c.counts?.fail),
                  count(c.counts?.warn), count(c.counts?.error), <Pill tone={tone}>{word}</Pill>];
              }}
            />
            {page.clusters.length === 0 && <Empty>No cluster of your environments is known to this instance.</Empty>}
            <Stack>{page.clusters.filter((c) => c.stateDetail).map((c) => <Small key={c.clusterId}>{`${c.clusterId}: ${c.stateDetail}.`}</Small>)}</Stack>
            <Small>{"Kyverno not installed, an unreachable cluster, reports that cmapi-reader may not read, and rows past the cap show as states, never as zero. A cluster whose policies differ from what cmapi renders, by digest or by their actions, is off the bundle."}</Small>
          </>
        )}
      </Panel>

      {page && (
        <Panel title="Results by policy">
          <Choices label="Cluster" options={chips} />
          <DataTable
            label="Results by policy"
            cols={["Policy", "Kind", "What it checks", "Pass", "Fail", "Warn", "Error", ""]}
            rows={page.policies}
            selected={(p) => p.name === policy}
            cells={(p) => [<span className="cp-mono">{p.name}</span>, p.kind, whatOf(p), count(p.counts?.pass), count(p.counts?.fail),
              count(p.counts?.warn), count(p.counts?.error),
              <Button variant="secondary" size="sm" onClick={() => apply({ policy: p.name === policy ? "" : p.name })}>{p.name === policy ? "Showing" : "Show failures"}</Button>]}
          />
          {page.policies.length === 0 && <Empty>No policy runs in the environments of these clusters.</Empty>}
          {known.some(inScope) && <Small>{`${hidden.unmanaged} results on namespaces that cmapi does not manage, ${hidden.other} of other policies and ${hidden.gone} of policies no longer on the cluster are counted and not shown.`}</Small>}
        </Panel>
      )}

      <Panel title={title}>
        {stale && (
          <Callout tone="warn" title="This page link is out of date">
            <Stack hasGutter>
              <span>The filters changed after it was made, so the API refused it (400 invalid-cursor) rather than show the wrong rows.</span>
              <div><Button variant="secondary" size="sm" onClick={() => apply({})}>Back to the first page</Button></div>
            </Stack>
          </Callout>
        )}
        {page && (
          <>
            <Pager
              busy={busy}
              range={page.page.total ? `${page.page.from}–${page.page.to} of ${page.page.total} · by namespace` : "0 results"}
              prev={() => page.page.prevCursor && setCursor(page.page.prevCursor)}
              next={() => page.page.nextCursor && setCursor(page.page.nextCursor)}
              prevDis={!page.page.prevCursor}
              nextDis={!page.page.nextCursor}
            />
            <DataTable
              busy={busy}
              label="Failing resources"
              cols={["Namespace", "Resource", "Policy", "Result", "Message", "Cluster"]}
              rows={page.items}
              cells={(r) => [r.namespace, `${r.resource.kind}/${r.resource.name}`,
                <Stack><span className="cp-mono">{r.policy}</span>{r.rule && <Small>{`rule ${r.rule}`}</Small>}</Stack>,
                <Pill tone={RESULT_TONE[r.result]}>{r.result}</Pill>, r.message, r.clusterId]}
            />
            {page.items.length === 0 && <Empty>Nothing failing for this selection.</Empty>}
          </>
        )}
        <Small>{`GET /api/v1/policies/results?${sent} · filtered to the environments your roles cover · paged like every list.`}</Small>
      </Panel>

      {rejections}
    </Stack>
  );
}

/** The stage in the mockup's words: "plan (422)", "plan, warned" or "CI". */
const stageOf = (r: Rejection): string => (r.stage === "ci" ? "CI" : r.outcome === "warned" ? "plan, warned" : "plan (422)");

/** The finding a row is named by: its first error, or its first warning. */
const primaryOf = (r: Rejection) => r.findings.find((f) => f.severity === "error") ?? r.findings[0];

function Refused({ result, setCursor }: { result: ReturnType<typeof usePolicyRejections>; setCursor: (c: string | null) => void }) {
  let body: ReactNode = null;
  if (result.state === "loading") body = <Stack hasGutter><span role="status">Loading the refusals…</span><Skeleton /></Stack>;
  if (result.state === "forbidden") {
    body = (
      <EmptyState titleText="You do not have permission to see the refusals." headingLevel="h3" icon={LockIcon}>
        <EmptyStateBody>{result.detail}</EmptyStateBody>
      </EmptyState>
    );
  }
  if (result.state === "error") {
    body = <Alert variant="danger" isInline title="The refusals did not load." actionLinks={<AlertActionLink onClick={result.reload}>Try again</AlertActionLink>}>{result.cause}</Alert>;
  }
  if (result.state === "ok") {
    const page = result.data, now = new Date();
    body = (
      <>
        {page.page.total > page.page.limit && (
          <Pager
            busy={result.refreshing}
            range={`${page.page.from}–${page.page.to} of ${page.page.total} · newest first`}
            prev={() => page.page.prevCursor && setCursor(page.page.prevCursor)}
            next={() => page.page.nextCursor && setCursor(page.page.nextCursor)}
            prevDis={!page.page.prevCursor}
            nextDis={!page.page.nextCursor}
          />
        )}
        <DataTable
          busy={result.refreshing}
          label="Refused by cmapi"
          cols={["When", "Where", "Stage", "Policy or check", "Detail", "By"]}
          rows={page.items}
          cells={(r) => {
            const first = primaryOf(r), rest = r.findings.filter((f) => f !== first);
            return [whenOf(r.firstAt, now), `${r.clusterId} · ${r.namespace}`, stageOf(r),
              <Stack><span className="cp-mono">{first?.policy ?? r.problem ?? "—"}</span>{first?.rule && <Small>{`rule ${first.rule}`}</Small>}</Stack>,
              <Stack>
                <span>{`${first?.message ?? ""}${r.count > 1 ? ` (${r.count} times that day)` : ""}`}</span>
                {rest.map((f, i) => <Small key={i}>{`${f.severity}: ${f.policy}${f.rule ? ` ${f.rule}` : ""}: ${f.message}`}</Small>)}
              </Stack>,
              r.username];
          }}
        />
        {page.items.length === 0 && <Empty>Nothing refused in the last 7 days.</Empty>}
      </>
    );
  }
  return (
    <Panel title="Refused by cmapi before Git · last 7 days">
      {body}
      <Small>{"GET /api/v1/policies/rejections?since=7d · plan-time refusals never become requests, so they are listed here rather than under Requests."}</Small>
    </Panel>
  );
}
