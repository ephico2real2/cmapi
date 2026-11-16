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
  ["each tab shows, whatever /me says", "src/portal/PortalApp.tsx", `TABS.filter((tab) => tab.needs === null || held.has(tab.needs))`, `TABS.filter(() => true)`, "portal"],
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
  ["a new Idempotency-Key for each submit", "src/portal/NewNamespaceTab.tsx", `submit.submit(cluster.clusterId, body, key)`, `submit.submit(cluster.clusterId, body, crypto.randomUUID())`, "portal", "9 New namespace: the"],
  ["no Idempotency-Key", "src/api/hooks.ts", `header: { "Idempotency-Key": key }`, `header: {}`, "portal", "9 New namespace: the"],
  ["the dry run writes", "src/api/hooks.ts", `query: { dryRun: true }`, `query: { dryRun: false }`, "portal", "9 New namespace: the"],
  ["the plan outlives a change to the form", "src/portal/NewNamespaceTab.tsx", `{ set(value); setPlanned(null); }`, `{ set(value); }`, "portal", "9 New namespace: the"],
  ["the browser's checks are off", "src/portal/NewNamespaceTab.tsx", `<Form noValidate={false}`, `<Form noValidate`, "portal", "9 New namespace refusals"],
  ["Submit does not open the new request", "src/portal/NewNamespaceTab.tsx", `.then((request) => open("workflow", { request: request.requestId }), () => undefined)`, `.then(() => undefined, () => undefined)`, "portal", "9 New namespace: the"],
  ["a 5xx reads as a refusal", "src/api/hooks.ts", `return error.status >= 500 ?`, `return error.status >= 600 ?`, "portal", "9 New namespace: the"],
  ["a refused dry run is hidden", "src/portal/NewNamespaceTab.tsx", `{plan.state === "refused" && <Callout`, `{false && <Callout`, "portal", "9 New namespace refusals"],
  ["tier sizes swapped", "src/portal/NewNamespaceTab.tsx", `cpu: String(q["requests.cpu"] ?? "—"), memory: String(q["requests.memory"] ?? "—")`, `cpu: String(q["requests.memory"] ?? "—"), memory: String(q["requests.cpu"] ?? "—")`, "portal", "9 New namespace: the"],
  ["the approval count of the plan is wrong", "src/portal/NewNamespaceTab.tsx", "title: `${need} approval${need > 1", "title: `${need - 1} approval${need > 1", "portal", "9 New namespace: the"],
  ["an invented hint", "src/portal/NewNamespaceTab.tsx", `<Hint>From clusters.yaml metadata.</Hint>`, `<Hint>From clusters.yaml metadata. Pick the nearest.</Hint>`, "portal", "6 the Workflow"],
  ["the other portals are gone", "src/portal/config.ts", `otherInstances: otherInstancesOf(o.otherInstances)`, `otherInstances: []`, "portal", "9 New namespace: the"],
  ["an http portal link is accepted", "src/portal/config.ts", `url: serviceUrl(o.url, \`otherInstances.\${name}.url\`)`, `url: String(o.url)`, "bundle"],
  ["the approvals are not mine", "src/portal/ApprovalsTab.tsx", `{ status: "pending_approval", approver: "me", limit: LIMIT }`, `{ status: "pending_approval", limit: LIMIT }`, "portal", "10 Approvals: the requests"],
  ["a reject with no reason is sent", "src/portal/ApprovalsTab.tsx", `if (!reason) return;`, ``, "portal", "10 Approvals: the requests"],
  ["Approve is connected to nothing", "src/portal/ApprovalsTab.tsx", `onClick={onApprove}`, `onClick={() => {}}`, "portal", "10 Approvals: the requests"],
  ["a refusal of the API is hidden", "src/portal/ApprovalsTab.tsx", `{refusal?.state === "refused" && <Callout`, `{false && <Callout`, "portal", "10 Approvals: the API"],
  ["the decision's callout is gone", "src/portal/ApprovalsTab.tsx", `{done && <Callout`, `{false && <Callout`, "portal", "10 Approvals: the requests"],
  ["a decided request still counts as waiting", "src/portal/ApprovalsTab.tsx", `items.filter((r) => !decided[r.requestId]).length`, `items.length`, "portal", "10 Approvals: the requests"],
  ["the requester is never you", "src/portal/ApprovalsTab.tsx", `const self = who.username === me.username;`, `const self = false;`, "portal", "10 Approvals: the API"],
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
const results = [];
for (const [what, file, from, to, suite, checks] of MUTANTS) {
  if (only && !what.includes(only)) continue;
  const path = join(app, file), source = readFileSync(path, "utf8");
  if (source.split(from).length !== 2) throw new Error(`${what}: the text is not in ${file} exactly one time`);
  writeFileSync(path, source.replace(from, to));
  let outcome;
  try {
    execFileSync(vite, ["build"], { cwd: app, stdio: "ignore" });
    // A mutant can make the page wait without end. The suite has its own limit for each check; this one is the backstop.
    const env = checks ? { ...process.env, CHECK: checks } : { ...process.env, CHECK: "" };
    const run = spawnSync(process.execPath, [join(app, "tests", "api", `${suite}.test.mjs`)], { cwd: app, env, encoding: "utf8", timeout: SUITE_TIMEOUT_MS, killSignal: "SIGKILL" });
    if (run.error?.code === "ETIMEDOUT") outcome = "killed: timeout";
    else outcome = run.status === 0 ? "SURVIVED" : `killed: ${(run.stderr.match(/AssertionError[^\n]*\n?[^\n]*|TimeoutError[^\n]*|Timeout \d+ms[^\n]*|did not end in \d+ s/) ?? ["the suite failed"])[0].replace(/\s+/g, " ").slice(0, 150)}`;
  } catch {
    outcome = "killed: the build failed";
  } finally {
    writeFileSync(path, source);
  }
  results.push([what, outcome]);
  console.log(`${outcome.startsWith("killed") ? "ok  " : "FAIL"} ${what} - ${outcome}`);
}
execFileSync(vite, ["build"], { cwd: app, stdio: "ignore" });
const dirty = execFileSync("git", ["status", "--porcelain", "--", "src"], { cwd: app, encoding: "utf8" }).split("\n").filter((l) => / M /.test(` ${l}`) && MUTANTS.some((m) => l.endsWith(m[1].replace("src/", ""))));
const survived = results.filter(([, outcome]) => !outcome.startsWith("killed"));
console.log(`${results.length} mutants, ${results.length - survived.length} killed, ${survived.length} survived. The source is restored and the portal is built again.`);
if (survived.length) process.exit(1);
