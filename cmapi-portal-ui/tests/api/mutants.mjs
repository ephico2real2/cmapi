#!/usr/bin/env node
// Proves that the checks of tests/api can fail. Each mutant breaks one thing in the source, the portal is built again,
// and the suite must fail. A mutant that survives is a weak check. The source is restored after each one.
// Run it by hand (`npm run test:mutants`): it builds the portal one time for each mutant.
import { execFileSync, spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const app = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const vite = join(app, "node_modules", ".bin", "vite");

// [what it breaks, file, the text, its replacement, the suite that must fail, and optionally the checks of that suite to run
// (their names' start, as CHECK takes it): the checks that claim to see the defect, so a mutant does not run the whole suite]
const MUTANTS = [
  ["PKCE dropped", "src/portal/auth.ts", `response_type: "code",`, `response_type: "code", disablePKCE: true,`, "portal"],
  ["tokens kept in localStorage", "src/portal/auth.ts", `new WebStorageStateStore({ store: new InMemoryWebStorage() })`, `new WebStorageStateStore({ store: window.localStorage })`, "portal"],
  ["tokens kept in sessionStorage", "src/portal/auth.ts", `new WebStorageStateStore({ store: new InMemoryWebStorage() })`, `new WebStorageStateStore({ store: window.sessionStorage })`, "portal"],
  ["the code stays in the address", "src/portal/auth.ts", `onSigninCallback: (user) => history.replaceState(null, "", location.pathname + returnHash(user))`, `onSigninCallback: () => {}`, "portal"],
  ["the view is lost at sign-in", "src/portal/auth.ts", `? state.hash : "";`, `? "" : "";`, "portal"],
  ["no renewal on a 401", "src/api/client.ts", `const fresh = await replacement.token;`, `const fresh = undefined as string | undefined;`, "portal"],
  ["no recovery when the renewal fails", "src/api/client.ts", `    await signInOnce();\n    return first;`, `    return first;`, "portal"],
  ["a call can send a cookie or follow a redirect", "src/api/client.ts", `new Request(request.clone(), { credentials: "omit", redirect: "error" })`, `request.clone()`, "direct"],
  ["the ID token is in the logout URL", "src/portal/auth.ts", `await this.leave(endpoint, fields);`, `location.assign(endpoint + "?" + new URLSearchParams(fields));`, "portal"],
  ["a renewal in flight outlives the sign-out", "src/portal/auth.ts", `await this.pendingRenewal?.catch(() => undefined);`, ``, "direct"],
  ["a discovered http endpoint is accepted", "src/portal/auth.ts", `if (url.protocol !== "https:" && !local) throw new Error(`, `if (false) throw new Error(`, "direct"],
  ["an empty query in config.json is accepted", "src/portal/config.ts", `url.href.includes("?") || url.href.includes("#")`, `url.search || url.hash`, "direct"],
  ["an API that always answers 401 redirects without end", "src/portal/PortalApp.tsx", `signIn: async () => { sessionEnded.current(); }`, `signIn: async () => { await latest.current.signinRedirect(); }`, "portal"],
  ["a failed callback stays in the address", "src/portal/PortalApp.tsx", `if ((auth.error && hasAuthParams()) || callbackError) history.replaceState(null, "", location.pathname);`, ``, "portal"],
  ["an error with no state signs in again", "src/portal/PortalApp.tsx", `(params.has("error") || params.has("code")) && !params.get("state")`, `false`, "portal"],
  ["a failed renewal hides behind the page", "src/portal/PortalApp.tsx", `if (sessionEnded || auth.error || callbackError) return`, `if (sessionEnded || (auth.error && !auth.isAuthenticated) || callbackError) return`, "portal"],
  ["a 403 reads as an error with a retry", "src/api/hooks.ts", `error.status === 403`, `error.status === 999`, "portal"],
  ["each tab shows, whatever /me says", "src/portal/PortalApp.tsx", `TABS.filter((tab) => held.has(tab.needs))`, `TABS.filter(() => true)`, "portal"],
  ["the name comes from nowhere", "src/portal/PortalApp.tsx", `<b>{me.data.username}</b>`, `<b>ola</b>`, "portal"],
  ["two columns swapped", "src/portal/RequestsTab.tsx", `r.requestId, r.clusterId, r.namespace,`, `r.requestId, r.namespace, r.clusterId,`, "portal"],
  ["each status the wrong colour", "src/portal/format.ts", `pending_approval: "warn", awaiting_prune: "warn",`, `pending_approval: "ok", awaiting_prune: "ok",`, "portal"],
  ["the approval count is wrong", "src/portal/format.ts", "`${a.rule} · ${have} of ${need}`", "`${a.rule} · ${need} of ${need}`", "portal"],
  ["the status filter stays in the browser", "src/portal/RequestsTab.tsx", `if (state !== "all") query.state = state;`, ``, "portal"],
  ["the search stays in the browser", "src/portal/RequestsTab.tsx", `if (q) query.q = q;`, ``, "portal"],
  ["Next is connected to nothing", "src/portal/RequestsTab.tsx", `next={() => page.nextCursor && setCursor(page.nextCursor)}`, `next={() => {}}`, "portal"],
  ["Next is never disabled", "src/portal/RequestsTab.tsx", `nextDis={!page.nextCursor}`, `nextDis={false}`, "portal"],
  ["the empty sentence is gone", "src/portal/RequestsTab.tsx", `{result.data.items.length === 0 && <Empty>`, `{false && <Empty>`, "portal"],
  ["a changed heading", "src/portal/RequestsTab.tsx", `<Head title="Requests" lede="Every write you`, `<Head title="Requests" lede="Each write you`, "portal"],
  ["an invented sentence", "src/portal/RequestsTab.tsx", `<Small>This list shows the`, `<Small>Requests are kept for 90 days. This list shows the`, "portal"],
  ["Open at current step goes nowhere", "src/portal/RequestsTab.tsx", `onClick={() => open("workflow", { request: r.requestId })}`, `onClick={() => {}}`, "portal", "8 Workflow: Open"],
  // Portal slice 2 (#300): the Workflow, New namespace and Approvals tabs.
  ["a step is not its event", "src/portal/WorkflowTab.tsx", `{j + 1} {e.event}`, `{j + 1} {e.by}`, "portal", "8 Workflow: Open"],
  ["an open request is not followed", "src/api/hooks.ts", `const FOLLOW_MS = 5000;`, `const FOLLOW_MS = 600_000;`, "portal", "8 Workflow: Open"],
  ["a finished request is read again", "src/api/hooks.ts", `"merged", "awaiting_prune", "sync_failed"
]);`, `"merged", "awaiting_prune", "sync_failed", "synced"
]);`, "portal", "8 Workflow: Open"],
  ["merge_failed has the wrong tone", "src/portal/format.ts", `sync_failed: "bad", merge_failed: "bad",`, `sync_failed: "bad", merge_failed: "info",`, "portal", "8 Workflow: Open"],
  ["applied has the wrong tone", "src/portal/format.ts", `pr_open: "info", applied: "info",`, `pr_open: "info", applied: "ok",`, "portal", "8 Workflow: Open"],
  ["Back to current step does nothing", "src/portal/WorkflowTab.tsx", `onClick={() => setPicked(null)}`, `onClick={() => {}}`, "portal", "8 Workflow: Open"],
  ["Next step is never off", "src/portal/WorkflowTab.tsx", `isDisabled={i === last}`, `isDisabled={false}`, "portal", "8 Workflow: Open"],
  ["the detail is of another step", "src/portal/WorkflowTab.tsx", `const step = events[i];`, `const step = events[last];`, "portal", "8 Workflow: Open"],
  ["a changed Workflow heading", "src/portal/WorkflowTab.tsx", `title="Request workflow"`, `title="Request flow"`, "portal", "6 the Workflow"],
  ["a new Idempotency-Key for each submit", "src/portal/NewNamespaceTab.tsx", `if (sent.current?.request !== request) sent.current =`, `sent.current =`, "portal", "9 New namespace: the"],
  ["a changed form keeps the old Idempotency-Key", "src/portal/NewNamespaceTab.tsx", `if (sent.current?.request !== request) sent.current =`, `if (!sent.current) sent.current =`, "portal", "R1 New namespace"],
  ["Submit sends a form that was not planned", "src/portal/NewNamespaceTab.tsx", `const canSubmit = planOk !== null && submit.state !== "sending" && !!cluster;`, `const canSubmit = submit.state !== "sending" && !!cluster;`, "portal", "R2 New namespace"],
  ["a double click sends two writes", "src/api/hooks.ts", `return (args) => inFlight.current ?? (inFlight.current = run(args).finally(() => { inFlight.current = null; }));`, `return (args) => run(args);`, "portal", "R3 a double click"],
  ["the requester is matched by username", "src/portal/ApprovalsTab.tsx", `const self = who.sub === me.identity.sub;`, `const self = who.username === me.username;`, "portal", "R4 Approvals"],
  ["no Idempotency-Key", "src/api/hooks.ts", `header: { "Idempotency-Key": key }`, `header: {}`, "portal", "9 New namespace: the"],
  ["the dry run writes", "src/api/hooks.ts", `path: { cluster_id: clusterId }, query: { dryRun: true }`, `path: { cluster_id: clusterId }, query: { dryRun: false }`, "portal", "9 New namespace: the"],
  ["the plan outlives a change to the form", "src/portal/NewNamespaceTab.tsx", `const planIsOfForm = planned !== null && planned.cluster === cluster?.clusterId && JSON.stringify(planned.body) === JSON.stringify(body) && planned.draft === draft;`, `const planIsOfForm = planned !== null;`, "portal", "9 New namespace: the"],
  ["Submit does not open the new request", "src/portal/NewNamespaceTab.tsx", `.then((request) => open("workflow", { request: request.requestId }), () => undefined)`, `.then(() => undefined, () => undefined)`, "portal", "9 New namespace: the"],
  ["a 5xx reads as a refusal", "src/api/hooks.ts", `return error.status >= 500 ?`, `return error.status >= 600 ?`, "portal", "9 New namespace: the"],
  ["a refused dry run is hidden", "src/portal/NewNamespaceTab.tsx", `if (planIsOfForm && plan.state === "refused") return <Callout`, `if (false) return <Callout`, "portal", "9 New namespace refusals"],
  ["tier sizes swapped", "src/portal/NewNamespaceTab.tsx", `cpu: String(q["requests.cpu"] ?? "—"), memory: String(q["requests.memory"] ?? "—")`, `cpu: String(q["requests.memory"] ?? "—"), memory: String(q["requests.cpu"] ?? "—")`, "portal", "9 New namespace: the"],
  ["the approval count of the plan is wrong", "src/portal/NewNamespaceTab.tsx", "title: `${need} approval${need > 1", "title: `${need - 1} approval${need > 1", "portal", "9 New namespace: the"],
  ["an invented hint", "src/portal/NewNamespaceTab.tsx", `<Hint id="ns-region-help">From clusters.yaml metadata.</Hint>`, `<Hint id="ns-region-help">From clusters.yaml metadata. Pick the nearest.</Hint>`, "portal", "6 the Workflow"],
  ["the other portals are gone", "src/portal/config.ts", `otherInstances: otherInstancesOf(o.otherInstances)`, `otherInstances: []`, "portal", "9 New namespace: the"],
  ["an http portal link is accepted", "src/portal/config.ts", `url: serviceUrl(o.url, \`otherInstances.\${name}.url\`)`, `url: String(o.url)`, "bundle"],
  ["the approvals are not mine", "src/portal/ApprovalsTab.tsx", `{ status: "pending_approval", approver: "me", limit: LIMIT }`, `{ status: "pending_approval", limit: LIMIT }`, "portal", "10 Approvals: the requests"],
  ["a reject with no reason is sent", "src/portal/ApprovalsTab.tsx", `if (!reason) return;`, ``, "portal", "10 Approvals: the requests"],
  ["Approve is connected to nothing", "src/portal/ApprovalsTab.tsx", `onClick={onApprove}`, `onClick={() => {}}`, "portal", "10 Approvals: the requests"],
  ["a refusal of the API is hidden", "src/portal/ApprovalsTab.tsx", `{refusal?.state === "refused" && <Callout`, `{false && <Callout`, "portal", "10 Approvals: the API"],
  ["the decision's callout is gone", "src/portal/ApprovalsTab.tsx", `{done && <Callout`, `{false && <Callout`, "portal", "10 Approvals: the requests"],
  ["a decided request still counts as waiting", "src/portal/ApprovalsTab.tsx", `items.filter((r) => !decided[r.requestId]).length`, `items.length`, "portal", "10 Approvals: the requests"],
  ["the requester is never you", "src/portal/ApprovalsTab.tsx", `const self = who.sub === me.identity.sub;`, `const self = false;`, "portal", "10 Approvals: the API"],
  // #336: the labels and annotations of the New namespace form, from GET /api/v1/metadata-keys.
  ["#336 a declared field is dropped", "src/portal/metadataForm.ts", "ordered.forEach((f, i) => fields.push({ ...f, id: `ns-${kind}-${i}` }));", "ordered.slice(1).forEach((f, i) => fields.push({ ...f, id: `ns-${kind}-${i}` }));", "portal", "18 New namespace on a company"],
  ["#336 the CRC keys are hard-coded again", "src/portal/NewNamespaceTab.tsx", "const metadata = form ? bodyOf(form, typed, extras) : { labels: {}, annotations: {} };", `const metadata = { labels: { "cmapi.net/team": typed["label:cmapi.net/team"] ?? "" }, annotations: { "cmapi.net/team-dl": typed["annotation:cmapi.net/team-dl"] ?? "" } };`, "portal", "18 New namespace on a company"],
  ["#336 a pattern is not checked", "src/portal/metadataForm.ts", "if ((await test(pattern, value)) === false) return `Not valid: ${f.rule}`;", "if (false) return `Not valid: ${f.rule}`;", "portal", "18 New namespace on a company"],
  ["#336 the label syntax is not checked", "src/portal/metadataForm.ts", `if (length(value) > maxLength || (await test(pattern, value)) === false) return "Not a valid label value";`, `if (false) return "Not a valid label value";`, "portal", "18 New namespace on a company"],
  // #479: the form locks the name's start to the prefix key's value, so no form can send another start; the check stays
  // as cmapi's step 3 for checkField's other callers, and the direct test M5 sees it.
  ["#336 the prefix is not checked", "src/portal/metadataForm.ts", "if (f.namespacePrefix && ctx.namespace && !ctx.namespace.startsWith(`${value}-`))", "if (false)", "direct"],
  ["#336 an enum value is not checked", "src/portal/metadataForm.ts", "if (f.enum && !f.enum.includes(value)) return", "if (false) return", "direct"],
  ["#336 characters are counted in UTF-16 units", "src/portal/metadataForm.ts", "const length = (value: string): number => [...value].length;", "const length = (value: string): number => value.length;", "direct"],
  ["#336 the patterns run on the page's thread", "src/portal/patterns.ts", "export const sharedPatternTest: PatternTest = (pattern, value) => (shared ??= patternChecker()).test(pattern, value);", `export const sharedPatternTest: PatternTest = (pattern, value) => new RegExp(pattern, "u").test(value);`, "portal", "18 New namespace: a configured"],
  ["#336 no time limit on a pattern", "src/portal/patterns.ts", "export const PATTERN_LIMIT_MS = 200;", "export const PATTERN_LIMIT_MS = 600_000;", "portal", "18 New namespace: a configured"],
  ["#336 a refusal's errors are dropped", "src/api/problem.ts", "errors: itemsOf(body.errors) });", "errors: [] });", "portal", "18 New namespace: a refused"],
  ["#336 a refusal's errors are not on their fields", "src/portal/NewNamespaceTab.tsx", "shownError(f) ?? mapped?.byField[f.id] ?? null", "shownError(f) ?? null", "portal", "18 New namespace: a refused"],
  ["#336 an empty required field is in error before the person tries the form", "src/portal/NewNamespaceTab.tsx", "!attempted && (shown[valueKey(f)] ?? \"\") === \"\" ? null", "false ? null", "portal", "OB3-368 New namespace"],
  ["#336 a key the form lacks does not read the rules again", "src/portal/NewNamespaceTab.tsx", "if (mapped?.unknownKey) rules.reload();", "", "portal", "18 New namespace: a refused"],
  ["#336 the summary does not take the focus", "src/portal/NewNamespaceTab.tsx", "summaryRef.current?.focus();", "", "portal", "18 New namespace: a refused"],
  ["#336 the summary's link goes nowhere", "src/portal/NewNamespaceTab.tsx", "onClick={() => focusOn(id)}", "onClick={() => undefined}", "portal", "18 New namespace: a refused"],
  ["#336 a key that cmapi sets is sent", "src/portal/metadataForm.ts", `if (f.derivedFrom === null && (value !== "" || emptied)) (f.kind === "label" ? out.labels : out.annotations)[f.key] = value;`, `if (value !== "" || f.derivedFrom !== null) (f.kind === "label" ? out.labels : out.annotations)[f.key] = value;`, "portal", "18 New namespace on a company"],
  ["#336 an empty optional key is sent", "src/portal/metadataForm.ts", `if (f.derivedFrom === null && (value !== "" || emptied)) (f.kind === "label" ? out.labels : out.annotations)[f.key] = value;`, `if (f.derivedFrom === null) (f.kind === "label" ? out.labels : out.annotations)[f.key] = value;`, "portal", "9 New namespace: the"],
  ["#336 a key that cmapi sets is editable", "src/portal/MetadataFields.tsx", `<TextInput id={field.id} readOnlyVariant="default" value={derivedValue(field, target)}`, `<TextInput id={field.id} value={derivedValue(field, target)}`, "portal", "18 New namespace on a company"],
  ["#336 an operator-only key is offered", "src/portal/metadataForm.ts", `if (prop["x-cmapi-operator-only"] === true) return "operator-only";`, `if (false) return "operator-only";`, "portal", "18 New namespace on a company"],
  ["#336 a URL field is type=url", "src/portal/MetadataFields.tsx", `const type = field.format === "email-in-domains" ? "email" : "text";`, `const type = field.format === "email-in-domains" ? "email" : field.format === "url" ? "url" : "text";`, "portal", "18 New namespace on a company"],
  ["#336 the example is the value", "src/portal/MetadataFields.tsx", "isRequired={field.required} value={value}", `isRequired={field.required} value={value || (field.example ?? "")}`, "portal", "18 New namespace on a company"],
  ["#336 the titles are ignored", "src/portal/metadataForm.ts", "title: textOf(prop.title),", "title: null,", "portal", "18 New namespace on the reference"],
  ["#336 the rules-changed warning is gone", "src/portal/NewNamespaceTab.tsx", "{rulesChanged && <Alert", "{false && <Alert", "portal", "18 New namespace: rules that"],
  ["#336 the rules are not read again", "src/api/hooks.ts", "    staleTime: 0,\n    refetchOnWindowFocus: true,", "    staleTime: 600_000,\n    refetchOnWindowFocus: true,", "portal", "18 New namespace: rules that"],
  ["#336 a 403 of the rules reads as an error", "src/portal/NewNamespaceTab.tsx", "const forbidden = [clusters, tiers, rules].find", "const forbidden = [clusters, tiers].find", "portal", "18 New namespace states"],
  ["#336 an answer of another shape is read", "src/portal/metadataForm.ts", `if (!isObject(map) || map.type !== "object" || !isObject(map.properties)) throw`, "if (false) throw", "portal", "18 New namespace states"],
  ["#336 a keyword that the form does not evaluate", "src/portal/metadataForm.ts", `"x-cmapi-derived-from", "x-cmapi-format", "x-cmapi-namespace-prefix"`, `"x-cmapi-derived-from", "x-cmapi-namespace-prefix"`, "../contract"],
  // Portal slice 3 (#301): the Quotas and KPIs tabs.
  ["the quota search stays in the browser", "src/portal/QuotasTab.tsx", "if (applied) filters.q = applied;", "", "portal", "11 Quotas: the rows"],
  ["the environment filter stays in the browser", "src/portal/QuotasTab.tsx", "if (env) filters.env = env;", "", "portal", "11 Quotas: the rows"],
  ["the state chip is not sent", "src/portal/QuotasTab.tsx", "if (state) query.state = state;", "", "portal", "11 Quotas: the rows"],
  ["the quota sort is not sent", "src/portal/QuotasTab.tsx", "if (sort !== \"name\") query.sort = sort;", "", "portal", "11 Quotas: the rows"],
  ["the quotas' Next is connected to nothing", "src/portal/QuotasTab.tsx", "next={() => page.page.nextCursor && setCursor(page.page.nextCursor)}", "next={() => {}}", "portal", "11 Quotas: the rows"],
  ["the quotas' Next is never off", "src/portal/QuotasTab.tsx", "nextDis={!page.page.nextCursor}", "nextDis={false}", "portal", "11 Quotas: the rows"],
  ["the letter jump goes nowhere", "src/portal/QuotasTab.tsx", "onClick={() => n && apply({ sort: \"name\" }, l)}", "onClick={() => {}}", "portal", "11 Quotas: the rows"],
  ["a letter with no namespace is on", "src/portal/QuotasTab.tsx", "isAriaDisabled={!n}", "isAriaDisabled={false}", "portal", "11 Quotas: the rows"],
  ["used and hard swapped", "src/portal/QuotasTab.tsx", "cpu: [cores(r.cpu[0]), cores(r.cpu[1])] as const,", "cpu: [cores(r.cpu[1]), cores(r.cpu[0])] as const,", "portal", "11 Quotas: the rows"],
  ["the CPU meter at 0", "src/portal/QuotasTab.tsx", "ariaLabel=\"CPU requests of quota\" value={c?.pct ?? 0}", "ariaLabel=\"CPU requests of quota\" value={0}", "portal", "11 Quotas: the rows"],
  // #392: while the next sort loads, the table shows the last answer's rows (keepPreviousData).
  ["392: the pager says the sort asked for, not the sort of the rows shown", "src/portal/QuotasTab.tsx", "SORTS.find(([id]) => id === shownSort)![2]", "SORTS.find(([id]) => id === sort)![2]", "portal", "11 Quotas: the rows"],
  ["392: the table is not busy while it shows the last answer's rows", "src/portal/QuotasTab.tsx", "rows={items}\n              busy={busy}", "rows={items}\n              busy={false}", "portal", "11 Quotas: the rows"],
  ["392: Next pages from the last answer's cursor while the next sort loads", "src/portal/QuotasTab.tsx", "busy={busy}\n      range={text}", "busy={false}\n      range={text}", "portal", "11 Quotas: the rows"],
  ["392: Previous accepts an old cursor during a quota sort", "src/components/ui.tsx", "isAriaDisabled={disabled(prevDis)}", "isAriaDisabled={String(prevDis) === \"true\"}", "portal", "11 Quotas: the rows"],
  ["407: the pager accepts cursors from the previous answer", "src/components/ui.tsx", "busy || String(flag)", "String(flag)", "portal", "407"],
  ["407: Requests accepts old cursors", "src/portal/RequestsTab.tsx", "busy={result.refreshing}\n              range=", "busy={false}\n              range=", "portal", "407 Requests keeps"],
  ["407: Expiration accepts old cursors", "src/portal/ExpirationTab.tsx", "busy={busy}\n              range=", "busy={false}\n              range=", "portal", "407 Expiration keeps"],
  ["407: Policies results accept old cursors", "src/portal/PoliciesTab.tsx", "busy={busy}\n              range=", "busy={false}\n              range=", "portal", "407 Policies results"],
  ["407: Policies refusals accept old cursors", "src/portal/PoliciesTab.tsx", "busy={result.refreshing}\n            range=", "busy={false}\n            range=", "portal", "407 Policies refusals"],
  // #347: the read waits for the tab bar and the theme, and still fails on a transition that has not ended.
  ["347: a tab bar transition outlives the read", "src/app.css", ".cp-mono { font-family: var(--pf-t--global--font--family--mono); }", ".cp-mono { font-family: var(--pf-t--global--font--family--mono); }\n.pf-v6-c-tabs__scroll-button { transition-duration: 6s !important; }", "portal", "7 the Workflow"],
  ["347: a theme colour transition outlives the read", "src/app.css", ".cp-wrap { overflow-wrap: anywhere; }", ".cp-wrap { overflow-wrap: anywhere; }\n.pf-v6-c-page { transition: background-color 6s !important; }", "portal", "7 layout"],
  ["a row's attention is wrong", "src/portal/QuotasTab.tsx", "row.used >= 0.8 && <Pill key=\"n\"", "row.used >= 0.9 && <Pill key=\"n\"", "portal", "11 Quotas: the rows"],
  ["All counts the filtered rows", "src/portal/QuotasTab.tsx", "n: state ? (unstated.state === \"ok\" ? String(unstated.data.page.total) : \"…\")", "n: state ? (page ? String(page.page.total) : \"…\")", "portal", "11 Quotas: the rows"],
  ["the page size loses the first namespace", "src/portal/QuotasTab.tsx", "sort === \"name\" && shownSort === \"name\" && page?.items[0] ? page.items[0].name : null", "null", "portal", "11 Quotas: the rows"],
  ["the type-ahead asks for one character", "src/api/hooks.ts", "export const SUGGEST_MIN = 2;", "export const SUGGEST_MIN = 1;", "portal", "11 Quotas type"],
  ["Enter does not pick the match", "src/portal/QuotasTab.tsx", "else if (e.key === \"Enter\" && idx >= 0 && items.length) { e.preventDefault(); choose(items[idx]); }", "else if (false) { /* none */ }", "portal", "11 Quotas type"],
  ["a picked match is not where the page starts", "src/portal/QuotasTab.tsx", "sort: \"name\", ns: keyOf(s) }, s.name)}", "sort: \"name\", ns: keyOf(s) }, null)}", "portal", "11 Quotas type"],
  ["the export ignores the filters", "src/portal/QuotasTab.tsx", "const exportParams: ExportQuery = { ...filters,", "const exportParams: ExportQuery = {", "portal", "11 Quotas export"],
  ["the downloaded file is not the export", "src/portal/QuotasTab.tsx", "new Blob([csv], { type: \"text/csv\" })", "new Blob([csv.split(/\\r?\\n/).slice(0, 5).join(\"\\n\")], { type: \"text/csv\" })", "portal", "11 Quotas export"],
  ["Submit sends a quota change that was not planned", "src/portal/QuotasTab.tsx", "if (!planIsOfForm) { setPlanned(change); return; }", "", "portal", "12 Quotas change: the plan"],
  ["no If-Match on the change", "src/api/hooks.ts", "header: { \"Idempotency-Key\": key, \"If-Match\": ifMatchOf(etag) }", "header: { \"Idempotency-Key\": key }", "portal", "12 Quotas change: the plan"],
  ["If-Match is not a quoted entity tag", "src/api/hooks.ts", "(etag.startsWith(\"\\\"\") ? etag : `\"${etag}\"`)", "(etag)", "portal", "12 Quotas change: the plan"],
  ["the change's dry run writes", "src/api/hooks.ts", "query: { dryRun: true }, header: { \"If-Match\"", "query: { dryRun: false }, header: { \"If-Match\"", "portal", "12 Quotas change: the plan"],
  ["the same size is planned", "src/portal/QuotasTab.tsx", "if (!same) setPlanned(change);", "setPlanned(change);", "portal", "12 Quotas change: the plan"],
  ["the quota approval count is wrong", "src/portal/QuotasTab.tsx", "tone: need > 1 ? \"warn\" : \"info\", title: `${need} approval", "tone: need > 1 ? \"warn\" : \"info\", title: `${need + 1} approval", "portal", "12 Quotas change: the plan"],
  ["the 202 is not shown", "src/portal/QuotasTab.tsx", "{answered?.state === \"ok\" && (", "{false && (", "portal", "12 Quotas change: the plan"],
  ["the detail's used is the hard", "src/portal/QuotasTab.tsx", "pair[0] === null ? \"—\" : `${fmt(pair[0])}${unit}`", "pair[1] === null ? \"—\" : `${fmt(pair[1])}${unit}`", "portal", "12 Quotas change: the plan"],
  ["a new Idempotency-Key for each quota submit", "src/portal/QuotasTab.tsx", "if (sentKey.current?.change !== fingerprint) sentKey.current =", "sentKey.current =", "portal", "R5"],
  ["a changed quota change keeps the old key", "src/portal/QuotasTab.tsx", "if (sentKey.current?.change !== fingerprint) sentKey.current =", "if (!sentKey.current) sentKey.current =", "portal", "R5"],
  ["a double click sends two quota writes", "src/api/hooks.ts", "  const send = useOneAtATime(mutation.mutateAsync);\n  return { ...outcomeOf(mutation), submit: (change, key)", "  const send = mutation.mutateAsync;\n  return { ...outcomeOf(mutation), submit: (change, key)", "portal", "R6"],
  ["the browser's checks are off for a custom size", "src/portal/QuotasTab.tsx", "if (!form.current?.reportValidity()) return;", "", "portal", "12 Quotas change: custom"],
  ["a lock does not hide the form", "src/portal/QuotasTab.tsx", "{row.openRequest ? (", "{false ? (", "portal", "12 Quotas change: custom"],
  ["a viewer gets the change form", "src/portal/QuotasTab.tsx", "canChange={me.state === \"ok\" && me.data.access.permissions.includes(PATCH_NAMESPACE)}", "canChange={true}", "portal", "12 Quotas change: custom"],
  ["a refused plan is hidden", "src/portal/QuotasTab.tsx", "{planIsOfForm && plan.state === \"refused\" && <Callout", "{false && <Callout", "portal", "12 Quotas refusals"],
  ["a refused submit is hidden", "src/portal/QuotasTab.tsx", "{answered?.state === \"refused\" && <Callout", "{false && <Callout", "portal", "12 Quotas refusals"],
  ["a stale cursor reads as an error", "src/portal/QuotasTab.tsx", "result.state === \"error\" && result.code === \"invalid-cursor\"", "false", "portal", "12 Quotas refusals"],
  ["a 403 of the quotas reads as an error", "src/portal/QuotasTab.tsx", "if (result.state === \"forbidden\") {", "if (false) {", "portal", "12 Quotas refusals"],
  ["no loading line for the quotas", "src/portal/QuotasTab.tsx", "<span role=\"status\">Loading quotas…</span>", "", "portal", "12 Quotas refusals"],
  ["a changed Quotas heading", "src/portal/QuotasTab.tsx", "title=\"Quotas\"", "title=\"Quota\"", "portal", "6 the Quotas"],
  ["an invented sentence on the Quotas tab", "src/portal/QuotasTab.tsx", "<Small>Quota status from the watch cache; no Thanos call.", "<Small>Quotas refresh each minute. Quota status from the watch cache; no Thanos call.", "portal", "6 the Quotas"],
  ["an invented sentence on the KPIs tab", "src/portal/KpisTab.tsx", "<Small>Measured by the process that answered, when the page asked.", "<Small>Read again each minute. Measured by the process that answered, when the page asked.", "portal", "6 the Quotas"],
  ["a null KPI reads 0", "src/portal/KpisTab.tsx", "if (value === null) return UNAVAILABLE;", "if (value === null) return \"0\";", "portal", "13 KPIs: the"],
  ["a ratio is not a percent", "src/portal/KpisTab.tsx", "if (unit === \"ratio\") return `${fmt(value * 100)}%`;", "if (unit === \"ratio\") return `${fmt(value)}%`;", "portal", "13 KPIs: the"],
  ["the memory meter shows another figure", "src/portal/KpisTab.tsx", "meterOf(\"Memory\", c.memoryBytes, c.memoryLimitBytes", "meterOf(\"Memory\", c.memoryLimitBytes, c.memoryLimitBytes", "portal", "13 KPIs: the"],
  ["no threshold is read", "src/portal/KpisTab.tsx", "const over = pct > threshold;", "const over = false;", "portal", "13 KPIs: the"],
  ["the throttling bar is not scaled", "src/portal/KpisTab.tsx", "% of periods (limit ${th.throttledPercent}%)`, 25)", "% of periods (limit ${th.throttledPercent}%)`, 1)", "portal", "13 KPIs: the"],
  ["the database watch is not counted", "src/portal/KpisTab.tsx", "const watch = comps.filter((c) => c.watch).length + (db.watch ? 1 : 0);", "const watch = comps.filter((c) => c.watch).length;", "portal", "13 KPIs: the"],
  ["a changed KPIs heading", "src/portal/KpisTab.tsx", "title=\"KPIs\"", "title=\"KPI\"", "portal", "6 the Quotas"],
  ["a 403 of the KPIs reads as an error", "src/portal/KpisTab.tsx", "if (kpi.state === \"forbidden\") {", "if (false) {", "portal", "13 KPIs states"],
  ["the KPIs' Try again is connected to nothing", "src/portal/KpisTab.tsx", "<AlertActionLink onClick={kpi.reload}>", "<AlertActionLink onClick={() => {}}>", "portal", "13 KPIs states"],
  ["the KPIs tab needs no permission", "src/portal/PortalApp.tsx", "needs: PERMISSION[\"GET /api/v1/admin/kpi\"], panel: KpisTab", "needs: null, panel: KpisTab", "portal", "13 KPIs states"],
  // Portal slice 4a (#318): the Expiration tab.
  ["a changed Expiration heading", "src/portal/ExpirationTab.tsx", "title=\"Expiration\"", "title=\"Expirations\"", "portal", "6 the Expiration"],
  ["an invented sentence on the Expiration tab", "src/portal/ExpirationTab.tsx", " \u00b7 paged and searched like Quotas \u00b7 today is ", " \u00b7 paged and searched like Quotas, refreshed each minute \u00b7 today is ", "portal", "6 the Expiration"],
  ["the state chip stays in the browser", "src/portal/ExpirationTab.tsx", "if (state) query.state = state;", "", "portal", "14 "],
  ["the expiry search stays in the browser", "src/portal/ExpirationTab.tsx", "if (applied) filters.q = applied;", "", "portal", "14 "],
  ["the expiry Next goes nowhere", "src/portal/ExpirationTab.tsx", "next={() => page.page.nextCursor && setCursor(page.page.nextCursor)}", "next={() => {}}", "portal", "14 "],
  ["days in grace read as plain numbers", "src/portal/ExpirationTab.tsx", "`${r.daysLeft} (grace ${rules.graceDays + r.daysLeft} left)`", "String(r.daysLeft)", "portal", "14 "],
  ["Submit sends an expiry change that was not planned", "src/portal/ExpirationTab.tsx", "    if (!planIsOfForm) { setPlanned(change); return; }\n    if (plan.state !== \"ok\") return;\n    setSubmitted(fingerprint);\n    submit.submit(planned, keyFor(fingerprint))", "    setSubmitted(fingerprint);\n    submit.submit(change, keyFor(fingerprint))", "portal", "15 Expiration detail"],
  ["the extend sends other days than the plan shows", "src/portal/ExpirationTab.tsx", "change: { route: \"extend\", body: { days: n } }", "change: { route: \"extend\", body: { days: n + 1 } }", "portal", "15 Expiration detail"],
  ["make permanent goes to :extend", "src/portal/ExpirationTab.tsx", "change: { route: \"makePermanent\", body: {} }", "change: { route: \"extend\", body: {} }", "portal", "15 Expiration:"],
  ["a new Idempotency-Key for each expiry submit", "src/portal/ExpirationTab.tsx", "if (sentKey.current?.change !== fingerprint) sentKey.current =", "sentKey.current =", "portal", "R7"],
  ["a changed expiry keeps the old Idempotency-Key", "src/portal/ExpirationTab.tsx", "if (sentKey.current?.change !== fingerprint) sentKey.current =", "if (!sentKey.current) sentKey.current =", "portal", "R7"],
  ["a 412 of an expiry does not read the namespace again", "src/portal/ExpirationTab.tsx", "useEffect(() => { if (stale) reread(); }, [stale]);", "", "portal", "F3"],
  ["an expiry plan keeps the stale ETag", "src/portal/ExpirationTab.tsx", "setPlanned((p) => (p !== null && p.etag !== etag && ofBody(p) ? { ...p, etag } : p))", "setPlanned((p) => p)", "portal", "F3"],
  ["no If-Match on an expiry change", "src/api/hooks.ts", "\"If-Match\": ifMatchOf(change.etag), ", "", "portal", "15 Expiration detail"],
  ["two expiry writes at once", "src/api/hooks.ts", "void client.invalidateQueries({ queryKey: [\"expirations\"], refetchType: \"none\" });\n      void client.invalidateQueries({ queryKey: [\"namespace\", change.clusterId, change.ns], refetchType: \"none\" });\n    }\n  });\n  const send = useOneAtATime(mutation.mutateAsync);", "void client.invalidateQueries({ queryKey: [\"expirations\"], refetchType: \"none\" });\n      void client.invalidateQueries({ queryKey: [\"namespace\", change.clusterId, change.ns], refetchType: \"none\" });\n    }\n  });\n  const send = mutation.mutateAsync;", "portal", "R7"],
  ["a viewer sees the expiry form", "src/portal/ExpirationTab.tsx", "canChange={me.state === \"ok\" && grantsIn(me.data.access, EXTEND, shown.env)}", "canChange={true}", "portal", "16 "],
  ["a role of another environment sees the expiry form", "src/portal/access.ts", "(r.environments === \"all\" || (!!env && r.environments.includes(env)))", "true", "portal", "17 "],
  ["the expiry empty sentence is gone", "src/portal/ExpirationTab.tsx", "{items.length === 0 && <Empty>No namespace matches", "{false && <Empty>No namespace matches", "portal", "16 "],
  ["the expirations' Try again is connected to nothing", "src/portal/ExpirationTab.tsx", "<AlertActionLink onClick={result.reload}>", "<AlertActionLink onClick={() => {}}>", "portal", "16 "],
  ["a 403 of the expirations reads as an error", "src/portal/ExpirationTab.tsx", "if (result.state === \"forbidden\") {", "if (false) {", "portal", "16 "],
  ["an instance where nothing expires shows the list", "src/portal/ExpirationTab.tsx", "if (never) {", "if (false) {", "portal", "16 "],
  // #302: the Policies tab.
  ["an unknown count reads as 0", "src/portal/PoliciesTab.tsx", "(n === null || n === undefined ? \"—\" : String(n))", "String(n ?? 0)", "portal", "20 Policies: the clusters"],
  ["the mode is not the cluster's", "src/portal/PoliciesTab.tsx", ": c.mode;\n}", ": \"audit\";\n}", "portal", "20 Policies: the clusters"],
  ["each state the wrong tone", "src/portal/PoliciesTab.tsx", "since ${clock(c.asOf)}` : \"\"}`, \"bad\"]", "since ${clock(c.asOf)}` : \"\"}`, \"info\"]", "portal", "20 Policies: the clusters"],
  ["the error tone is danger", "src/portal/PoliciesTab.tsx", "error: \"info\" };", "error: \"bad\" };", "portal", "20 Policies: the clusters"],
  ["the cluster chip stays in the browser", "src/portal/PoliciesTab.tsx", "if (cluster) query.clusterId = cluster;", "", "portal", "20 Policies: the clusters"],
  ["Show failures stays in the browser", "src/portal/PoliciesTab.tsx", "if (policy) query.policy = policy;", "", "portal", "20 Policies: the clusters"],
  ["the policies' Next goes nowhere", "src/portal/PoliciesTab.tsx", "next={() => page.page.nextCursor && setCursor(page.page.nextCursor)}\n              prevDis", "next={() => {}}\n              prevDis", "portal", "20 Policies: the clusters"],
  ["a list of policies of the page's own", "src/portal/PoliciesTab.tsx", "rows={page.policies}", "rows={page.policies.slice(0, 1)}", "portal", "20 Policies: the clusters"],
  ["the hidden counts are not summed", "src/portal/PoliciesTab.tsx", "unmanaged: h.unmanaged + (c.hidden?.unmanaged ?? 0),", "unmanaged: h.unmanaged,", "portal", "20 Policies: the clusters"],
  ["the stage is the API's word", "src/portal/PoliciesTab.tsx", "(r.stage === \"ci\" ? \"CI\" : r.outcome === \"warned\" ? \"plan, warned\" : \"plan (422)\")", "r.stage", "portal", "20 Policies: the refusals"],
  ["the refusal names nobody", "src/portal/PoliciesTab.tsx", "              r.username];", "              \"—\"];", "portal", "20 Policies: the refusals"],
  ["engine none still shows the results", "src/portal/PoliciesTab.tsx", "if (engineOff) {", "if (false) {", "portal", "21 Policies"],
  ["a 403 of the refusals reads as an error", "src/portal/PoliciesTab.tsx", "  if (result.state === \"forbidden\") {\n    body =", "  if (false) {\n    body =", "portal", "21 Policies"],
  ["the policy results' Try again is connected to nothing", "src/portal/PoliciesTab.tsx", "title=\"The policy results did not load.\" actionLinks={<AlertActionLink onClick={result.reload}>", "title=\"The policy results did not load.\" actionLinks={<AlertActionLink onClick={() => {}}>", "portal", "21 Policies"],
  ["OB3 384: a policy's unknown count reads as 0", "src/portal/PoliciesTab.tsx", "count(p.counts?.pass)", "String(p.counts?.pass ?? 0)", "portal", "22 Policies"],
  ["OB3 384: the head sums no cluster into 0 failing", "src/portal/PoliciesTab.tsx", ": \"—\";\n  const drift", ": \"0\";\n  const drift", "portal", "22 Policies"],
  ["OB3 384: the missing count is the 20 names", "src/portal/PoliciesTab.tsx", "const missing = b.expected - b.live,", "const missing = b.missing.length,", "portal", "22 Policies"],
  ["a changed Policies heading", "src/portal/PoliciesTab.tsx", "title=\"Policies\"", "title=\"Policy\"", "portal", "6 the Policies"],
  ["an invented sentence on the Policies tab", "src/portal/PoliciesTab.tsx", " · paged like every list.`", " · paged like every list, newest first.`", "portal", "6 the Policies"],
  // #302: the Capacity tab.
  ["302 Capacity: an unknown commitment draws a 0 % bar", "src/portal/CapacityTab.tsx", "{f.commitment === null\n        ? <span>—</span>", "{false\n        ? <span>—</span>", "portal", "23 Capacity"],
  ["302 Capacity: over 100 % reads as 100 %", "src/portal/CapacityTab.tsx", "label={pct(f.commitment)}", "label={pct(Math.min(1, f.commitment))}", "portal", "23 Capacity"],
  ["302 Capacity: the bar of a critical cluster has no tone", "src/portal/CapacityTab.tsx", "const BAR: Record<Status, string | undefined> = { ok: undefined, warn: \"warn\", critical: \"crit\", over: \"crit\" };", "const BAR: Record<Status, string | undefined> = { ok: undefined, warn: \"warn\", critical: undefined, over: undefined };", "portal", "23 Capacity"],
  ["302 Capacity: the simulated size is not said", "src/portal/CapacityTab.tsx", "const simulated = f.simulated === null ? null", "const simulated = true ? null", "portal", "23 Capacity"],
  ["302 Capacity: memory in G, not Gi", "src/portal/CapacityTab.tsx", "const gi = (bytes: number): string => `${tenths(bytes / GI)} Gi`;", "const gi = (bytes: number): string => `${tenths(bytes / 1e9)} G`;", "portal", "23 Capacity"],
  ["302 Capacity: the memory placement is the CPU cluster's", "src/portal/CapacityTab.tsx", "const c = g.cpu.largestPlacement, m = g.memory.largestPlacement;", "const c = g.cpu.largestPlacement, m = { ...g.memory.largestPlacement, clusterId: c.clusterId };", "portal", "23 Capacity"],
  ["302 Capacity: a negative headroom reads as room", "src/portal/CapacityTab.tsx", "value < 0 ? `over by ${amount(r, -value)}` : amount(r, value)", "amount(r, Math.abs(value))", "portal", "23 Capacity"],
  ["302 Capacity: a stale cluster is not marked", "src/portal/CapacityTab.tsx", "case \"stale\": return [`stale since ${c.asOf ? clock(c.asOf) : \"—\"}`, \"bad\"];", "case \"stale\": return [\"ok\", \"ok\"];", "portal", "23 Capacity"],
  ["302 Capacity: the group pill counts every cluster", "src/portal/CapacityTab.tsx", "`${g.status} · ${g.statusCounts[g.status]} of ${g.included}`", "`${g.status} · ${g.included} of ${g.included}`", "portal", "23 Capacity"],
  ["302 Capacity: a cluster's Bound by is always cpu", "src/portal/CapacityTab.tsx", "room, boundWord(c.boundBy),", "room, \"cpu\",", "portal", "23 Capacity"],
  ["302 Capacity: the footnote's overcommit is a constant", "src/portal/CapacityTab.tsx", "`${t.env}: overcommit cpu ${ratioWord(t.overcommit.cpu)}", "`${t.env}: overcommit cpu ${ratioWord(2)}", "portal", "23 Capacity"],
  ["302 Capacity: a left-out cluster is not named", "src/portal/CapacityTab.tsx", "`coverage ${coverage}`, ...g.excluded.map(leftOut)]", "`coverage ${coverage}`]", "portal", "23 Capacity"],
  ["302 Capacity: the hidden clusters are not said", "src/portal/CapacityTab.tsx", "{page.hiddenClusters > 0 && <Small>", "{false && <Small>", "portal", "23 Capacity"],
  ["302 Capacity: the Capacity tab shows without capacity:read", "src/portal/PortalApp.tsx", "needs: PERMISSION[\"GET /api/v1/capacity\"]", "needs: PERMISSION[\"GET /api/v1/requests\"]", "portal", "24 Capacity"],
  ["302 Capacity: Capacity's Try again is connected to nothing", "src/portal/CapacityTab.tsx", "title=\"Capacity did not load.\" actionLinks={<AlertActionLink onClick={result.reload}>", "title=\"Capacity did not load.\" actionLinks={<AlertActionLink onClick={() => {}}>", "portal", "24 Capacity"],
  ["302 Capacity: capacity is not read again on focus", "src/api/hooks.ts", "    refetchOnWindowFocus: true,\n    staleTime: 0,\n    refetchInterval", "    refetchOnWindowFocus: false,\n    staleTime: 0,\n    refetchInterval", "portal", "24 Capacity"],
  ["302 Capacity: a changed Capacity heading", "src/portal/CapacityTab.tsx", "title=\"Capacity\"", "title=\"Capacities\"", "portal", "6 the Capacity"],
  ["302 Capacity: an invented sentence on the Capacity tab", "src/portal/CapacityTab.tsx", "Pods of other namespaces are not subtracted.", "Pods of other namespaces are not subtracted, and nodes are measured hourly.", "portal", "6 the Capacity"],
  // #366: the protection of a namespace.
  ["the protection control is everyone's", "src/portal/QuotasTab.tsx", "canProtect={me.state === \"ok\" && operatorIn(me.data, shown.env) && grantsIn(me.data.access, PATCH_NAMESPACE, shown.env)}", "canProtect={me.state === \"ok\"}", "portal", "19 Protection: everyone"],
  ["an operator somewhere is an operator everywhere", "src/portal/access.ts", "me.operator && (me.operatorEnvironments === \"all\" || (!!env && me.operatorEnvironments.includes(env)))", "me.operator", "portal", "19 Protection: an operator limited"],
  // The detail also needs namespaces:write in the environment, so the create form is where the environment of an operator shows.,
  ["the badge reads the labels, not protectedBy", "src/portal/QuotasTab.tsx", "{view?.protected && <Label", "{view?.labels[\"cmapi.net/protected\"] === \"true\" && <Label", "portal", "19 Protection: everyone"],
  ["removing the protection sends \"false\"", "src/portal/QuotasTab.tsx", "const label = { [PROTECT_KEY]: set ? null : PROTECT_VALUE };", "const label = { [PROTECT_KEY]: set ? \"false\" : PROTECT_VALUE };", "portal", "19 Protection: removing"],
  ["the protection body carries another key", "src/portal/QuotasTab.tsx", "body: { labels: label } };", "body: { labels: { ...label, \"cmapi.net/team\": view.team ?? \"\" } } };", "portal", "19 Protection: the operator's"],
  ["the protection keeps no key across a retry", "src/portal/QuotasTab.tsx", "if (keyOfChange.current?.change !== fingerprint) keyOfChange.current = { key: crypto.randomUUID(), change: fingerprint };", "keyOfChange.current = { key: crypto.randomUUID(), change: fingerprint };", "portal", "19 Protection: the operator's"],
  ["a 412 of the protection is not read again", "src/portal/QuotasTab.tsx", "useEffect(() => { if (open && stale) reread(); }, [open, stale]);", "", "portal", "19 Protection: a 412"],
  ["the removal does not say what still protects", "src/portal/QuotasTab.tsx", "{set && others.length > 0 && (", "{false && (", "portal", "19 Protection: removing"],
  ["a 403 of the protection does not read /me again", "src/portal/QuotasTab.tsx", "useEffect(() => { if (forbidden) void queries.invalidateQueries({ queryKey: [\"me\"] }); }, [forbidden]);", "", "portal", "19 Protection: a 412"],
  // #479 (Phase 4): the New namespace form of mockups/portal/new-namespace-479.html. Each breaks one behaviour of design
  // section 7 (P1-P12), and the check named for it must fail.
  ["#479 the name's start is typed, not locked", "src/portal/NamespaceNameField.tsx", `{start && <InputGroupItem><Locked id="ns-name-start"`, `{false && <InputGroupItem><Locked id="ns-name-start"`, "portal", "479-P2"],
  ["#479 the name's end does not follow the cluster", "src/portal/metadataForm.ts", `const value = f.derivedFrom !== null ? target[f.derivedFrom] : shown[valueKey(f)] ?? "";`, `const value = f.derivedFrom !== null ? "dev" : shown[valueKey(f)] ?? "";`, "portal", "479-P2"],
  ["#479 an empty middle creates a double hyphen", "src/portal/metadataForm.ts", 'if (start && end && desired === "") return', 'if (false) return', "portal", "479-P2 a team-wide namespace"],
  ["#512 a middle with a dash at either end passes", "src/portal/metadataForm.ts", 'if (start !== null && end !== null && desired !== "" && !DNS_LABEL.test(desired)) return', 'if (false) return', "portal", "512 the middle"],
  ["#479 the name's length is not checked", "src/portal/metadataForm.ts", "if (length(name) > NAME_MAX) return", "if (false) return", "portal", "479-P2"],
  ["#479 the default does not copy its source", "src/portal/metadataForm.ts", "out[valueKey(f)] = source?.derivedFrom ? target[source.derivedFrom] : typed[`${f.kind}:${f.defaultFrom}`] ?? \"\";", "out[valueKey(f)] = \"\";", "portal", "479-P3"],
  ["#479 an edited default is written over", "src/portal/metadataForm.ts", "if (f.defaultFrom === null || valueKey(f) in typed) continue;", "if (f.defaultFrom === null) continue;", "portal", "479-P3"],
  ["#479 an unedited default is sent", "src/portal/NewNamespaceTab.tsx", "const metadata = form ? bodyOf(form, typed, extras)", "const metadata = form ? bodyOf(form, shown, extras)", "portal", "479-P3"],
  ["#479 a key that cmapi sets is not marked automatic", "src/portal/MetadataFields.tsx", `labelInfo={<Label isCompact>automatic</Label>}`, ``, "portal", "479-P3"],
  ["#479 the dry run's sources are not shown", "src/portal/NewNamespaceTab.tsx", "{set.length > 0 && <>", "{false && <>", "portal", "479-P3"],
  ["#479 Submit is open before a check", "src/portal/NewNamespaceTab.tsx", `isAriaDisabled={!canSubmit}`, `isAriaDisabled={false}`, "portal", "479-P6"],
  ["#479 a change does not close Submit", "src/portal/NewNamespaceTab.tsx", `const planIsOfForm = planned !== null && planned.cluster === cluster?.clusterId && JSON.stringify(planned.body) === JSON.stringify(body) && planned.draft === draft;`, `const planIsOfForm = planned !== null;`, "portal", "479-P6"],
  ["#479 the plan's file does not replace the preview", "src/portal/NewNamespaceTab.tsx", "const file = planOk ? planNamespaceFile(planOk.files) : null;", "const file = null;", "portal", "479-P6"],
  ["#479 the preview does not follow the form", "src/portal/NewNamespaceTab.tsx", "previewYaml(shownName, lines)", "previewYaml(shownName, { label: [], annotation: [] })", "portal", "479-P6"],
  ["#479 the additional keys are open by default", "src/portal/NewNamespaceTab.tsx", "const [extraOpen, setExtraOpen] = useState(false);", "const [extraOpen, setExtraOpen] = useState(true);", "portal", "479-P9"],
  ["#479 a new row is pre-filled", "src/portal/NewNamespaceTab.tsx", `{ id, key: "", value: "" }`, `{ id, key: "team", value: "x" }`, "portal", "479-P9"],
  ["#479 an extra key's prefix is not checked", "src/portal/metadataForm.ts", "if (other === null || (await test(other.pattern, key)) === false) return", "if (other === null) return", "portal", "479-P9"],
  ["#479 a duplicate extra key passes", "src/portal/metadataForm.ts", "if (rows.filter((r) => r.key === key).length > 1)", "if (false)", "portal", "479-P9"],
  ["#479 extra keys are not sent", "src/portal/metadataForm.ts", `for (const r of extras[kind]) if (r.key !== "") map[r.key] = r.value;`, ``, "portal", "479-P9"],
  ["#479 closing the section drops the rows", "src/portal/NewNamespaceTab.tsx", "onExpand={setExtraOpen}", "onExpand={(open) => { setExtraOpen(open); if (!open) setExtras({ label: [], annotation: [] }); }}", "portal", "479-P9"],
  ["#479 a check that did not run lists nothing", "src/portal/NewNamespaceTab.tsx", "if (blocked && problems.length) {", "if (false) {", "portal", "479-P9"],
  ["#479 annotation bytes are counted in UTF-16 units", "src/portal/metadataForm.ts", "export const bytesOf = (text: string): number => new TextEncoder().encode(text).length;", "export const bytesOf = (text: string): number => text.length;", "direct"],
  ["#479 expiration is on by the environment's name", "src/portal/metadataForm.ts", "return rules?.enabled && rules.allowedAtCreate ? rules : null;", "return environment !== \"prod\" ? rules ?? null : null;", "portal", "479-P12 where"],
  ["#479 maxLifetimeDays refuses a date", "src/portal/metadataForm.ts", `if (days < 1) return { state: "bad", error: "Pick a date after today." };`, `if (days < 1 || days > rules.maxLifetimeDays) return { state: "bad", error: "Pick a date after today." };`, "portal", "479-P12 Expires"],
  ["#479 maxLifetimeDays sets a date", "src/portal/NewNamespaceTab.tsx", `const [expires, setExpires] = useState("");`, `const [expires, setExpires] = useState(new Date(Date.now() + 180 * 864e5).toISOString().slice(0, 10));`, "portal", "479-P12 Expires"],
  ["#479 the calendar offers today", "src/portal/ExpiryField.tsx", `(yyyyMMddFormat(date) <= today ? "Pick a date after today." : "")`, `(yyyyMMddFormat(date) < today ? "Pick a date after today." : "")`, "portal", "479-P12 Expires"],
  ["#479 No expiry does nothing", "src/portal/ExpiryField.tsx", `onClick={() => onChange("")}>No expiry`, `onClick={() => undefined}>No expiry`, "portal", "479-P12 Expires"],
  ["#479 the form names a company", "src/portal/ExtraKeysSection.tsx", `placeholder="e.g. value"`, `placeholder="e.g. payments-team@company.net"`, "direct"],
  ["#479 x-cmapi-expiration is ignored again", "src/portal/metadataForm.ts", `answer: { read: ["labels", "annotations", "x-cmapi-expiration"], ignored: {} },`, `answer: { read: ["labels", "annotations"], ignored: {} },`, "../contract"],
  ["#479 a changed status sentence", "src/portal/NewNamespaceTab.tsx", `title="Changed since the last check. Press Check (dry run) again."`, `title="Changed since the last check."`, "portal", "6 the Workflow"],
  ["#479 an invented sentence in the preview", "src/portal/NewNamespaceTab.tsx", "<Small>What will be created. It updates as you type.</Small>", "<Small>What will be created. It updates as you type, every second.</Small>", "portal", "6 the Workflow"],
  // PR #506 review: each defect that reviewer 1 (Codex) and reviewer 2 (Opus) found, put back; the check named for it must fail.
  ["N1 a dry run reuses a cached pass", "src/api/hooks.ts", "    staleTime: 0,\n    gcTime: 0,\n", "", "portal", "N1 New namespace"],
  ["#506 a change that leaves the body does not close Submit", "src/portal/NewNamespaceTab.tsx", " && planned.draft === draft;", ";", "portal", "506-01"],
  ["#506 Check on a checked form does not ask cmapi again", "src/portal/NewNamespaceTab.tsx", "if (planIsOfForm) plan.reload();\n    else setPlanned(", "setPlanned(", "portal", "506-01"],
  ["#506 an emptied default is not sent", "src/portal/metadataForm.ts", "const emptied = f.defaultFrom !== null && valueKey(f) in values;", "const emptied = false;", "direct"],
  ["#506 a default from a key that cmapi fills in stays empty", "src/portal/metadataForm.ts", "source?.derivedFrom ? target[source.derivedFrom] : typed", "typed", "portal", "506-02"],
  ["#506 a refused extra row is not marked", "src/portal/NewNamespaceTab.tsx", "if (id) refusedAt[id] = item.detail ?? item.code;", "", "portal", "506-04"],
  ["#506 a refusal of the name is not on the name", "src/portal/NewNamespaceTab.tsx", "result?.name ?? nameRefused;", "result?.name ?? null;", "portal", "506-04"],
  ["#506 a refusal of the date is not on the date", "src/portal/NewNamespaceTab.tsx", `refused={refusal?.code.startsWith("expiration-") ? refusal.detail : null}`, "refused={null}", "portal", "506-04"],
  ["#506 a region of another environment still filters", "src/portal/NewNamespaceTab.tsx", "const activeRegion = inEnv.some((c) => c.labels.region === region) ? region : ANY_REGION;", "const activeRegion = region;", "portal", "506-11"],
  ["#506 the picker takes 2099-02-30", "src/portal/ExpiryField.tsx", "dateParse={strictDay} ", "", "portal", "506-12"],
  ["#506 a name of 1 character passes", "src/portal/metadataForm.ts", "if (length(name) < NAME_MIN) return", "if (false) return", "direct"],
  ["#506 an empty optional end is an end", "src/portal/metadataForm.ts", `return value === "" && !f.required ? null : value;`, "return value;", "direct"],
  ["#506 a YAML word is a plain key", "src/portal/preview.ts", "&& !/^(y|yes|n|no|true|false|on|off|null)$/i.test(key)", "", "direct"],
  ["#506 a table where cmapi takes no extra key", "src/portal/metadataForm.ts", "if (other === null || max === 0) return null;", "", "direct"],
  ["#506 an emptied default is not checked", "src/portal/metadataForm.ts", "if (value === \"\" && (f.required || !sent))", "if (value === \"\")", "direct"],
  ["the create box is everyone's", "src/portal/NewNamespaceTab.tsx", "const canProtect = me.state === \"ok\" && operatorIn(me.data, env) && !!form?.operatorOnlyLabels.includes(PROTECT_KEY);", "const canProtect = me.state === \"ok\" && !!form?.operatorOnlyLabels.includes(PROTECT_KEY);", "portal", "19 New namespace"],
  ["the create box sends the label unchecked", "src/portal/NewNamespaceTab.tsx", "...(canProtect && protect ? {", "...(canProtect ? {", "portal", "19 New namespace"],
  ["Try again is connected to nothing", "src/portal/RequestsTab.tsx", `<AlertActionLink onClick={retry}>`, `<AlertActionLink onClick={() => {}}>`, "portal"],
  ["no loading line", "src/portal/RequestsTab.tsx", `<span role="status">Loading requests…</span>`, ``, "portal"],
  ["sign-out stays in the browser", "src/portal/PortalApp.tsx", `void auth.signoutRedirect();`, ``, "portal"],
  ["the sample logic is in the portal's build", "src/main.tsx", `import.meta.env.MODE === "demo"`, `import.meta.env.MODE !== "demo"`, "bundle"],
  ["a bad config.json is accepted", "src/portal/config.ts", `if (url.protocol !== "https:" && !local)`, `if (false)`, "bundle"],
  ["a missing issuer is accepted", "src/portal/config.ts", "if (typeof value !== \"string\" || !value) throw new ConfigError(`config.json has no ${name}.`);", `if (typeof value !== "string" || !value) return "https://sso.example.test";`, "bundle"]
];

const SUITE_TIMEOUT_MS = 240_000;
const only = process.argv[2];
// Each text must be in its file exactly one time. Check all of them before the first build, not in the middle of a run.
const stale = MUTANTS.filter(([, file, from]) => readFileSync(join(app, file), "utf8").split(from).length !== 2).map(([what, file]) => `${what} (${file})`);
if (stale.length) throw new Error(`the text of these mutants is not in the source exactly one time: ${stale.join("; ")}`);
const selected = MUTANTS.filter(([what]) => !only || what.includes(only));
if (!selected.length) throw new Error(`No mutant matches ${only}`);
function runSuite(suite, checks) {
  return spawnSync(process.execPath, [join(app, "tests", "api", `${suite}.test.mjs`)], {
    cwd: app, env: { ...process.env, CHECK: checks ?? "" }, encoding: "utf8", timeout: SUITE_TIMEOUT_MS, killSignal: "SIGKILL"
  });
}
// Run each selected check on a clean build before crediting failures to any edit.
execFileSync(vite, ["build"], { cwd: app, stdio: "ignore" });
const baselines = new Set();
for (const [, , , , suite, checks] of selected) {
  const key = JSON.stringify([suite, checks]);
  if (baselines.has(key)) continue;
  const run = runSuite(suite, checks);
  if (run.status !== 0 || (checks && !run.stdout.includes(`ok - ${checks}`))) {
    throw new Error(`Baseline failed for ${suite} ${checks ?? ""}: ${run.error ?? (run.stderr || run.stdout)}`);
  }
  baselines.add(key);
}
const results = [];
for (const [what, file, from, to, suite, checks] of selected) {
  const path = join(app, file), source = readFileSync(path, "utf8");
  if (source.split(from).length !== 2) throw new Error(`${what}: the text is not in ${file} exactly one time`);
  writeFileSync(path, source.replace(from, to));
  let outcome;
  try {
    execFileSync(vite, ["build"], { cwd: app, stdio: "ignore" });
    // A mutant can make the page wait without end. The suite has its own limit for each check; this one is the backstop.
    const run = runSuite(suite, checks);
    if (run.error || run.signal) outcome = `unverified: ${run.error ?? run.signal}`;
    else if (suite === "portal" && run.status !== 0 && !run.stderr.split("\n").some(line => line.startsWith(`not ok - ${checks ?? ""}`))) {
      outcome = `unverified: no selected portal check failed\n${run.stderr}`;
    }
    else outcome = run.status === 0 ? "SURVIVED" : `killed: ${(run.stderr.match(/AssertionError[^\n]*\n?[^\n]*|TimeoutError[^\n]*|Timeout \d+ms[^\n]*|did not end in \d+ s/) ?? ["the suite failed"])[0].replace(/\s+/g, " ").slice(0, 150)}`;
  } catch (error) {
    outcome = `unverified: ${error.message}`;
  } finally {
    writeFileSync(path, source);
  }
  results.push([what, outcome]);
  console.log(`${outcome.startsWith("killed") ? "ok  " : "FAIL"} ${what} - ${outcome}`);
}
execFileSync(vite, ["build"], { cwd: app, stdio: "ignore" });
const killed = results.filter(([, outcome]) => outcome.startsWith("killed")).length;
const survived = results.filter(([, outcome]) => outcome === "SURVIVED").length;
console.log(`${results.length} mutants, ${killed} killed, ${survived} survived, ${results.length - killed - survived} unverified. The source is restored and the portal is built again.`);
if (killed !== results.length) process.exit(1);
