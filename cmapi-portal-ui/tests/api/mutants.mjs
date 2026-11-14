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

// [what it breaks, file, the text, its replacement, the suite that must fail]
const MUTANTS = [
  ["PKCE dropped", "src/portal/auth.ts", `response_type: "code",`, `response_type: "code", disablePKCE: true,`, "portal"],
  ["tokens kept in localStorage", "src/portal/auth.ts", `new WebStorageStateStore({ store: new InMemoryWebStorage() })`, `new WebStorageStateStore({ store: window.localStorage })`, "portal"],
  ["tokens kept in sessionStorage", "src/portal/auth.ts", `new WebStorageStateStore({ store: new InMemoryWebStorage() })`, `new WebStorageStateStore({ store: window.sessionStorage })`, "portal"],
  ["the code stays in the address", "src/portal/auth.ts", `onSigninCallback: (user) => history.replaceState(null, "", location.pathname + returnHash(user))`, `onSigninCallback: () => {}`, "portal"],
  ["the view is lost at sign-in", "src/portal/auth.ts", `? state.hash : "";`, `? "" : "";`, "portal"],
  ["no renewal on a 401", "src/api/client.ts", `const fresh = await renewOnce();`, `const fresh = undefined as string | undefined;`, "portal"],
  ["no sign-in when the renewal fails", "src/api/client.ts", `    await session.signIn();\n    return first;`, `    return first;`, "portal"],
  ["a cookie goes to the API", "src/api/client.ts", `credentials: "omit"`, `credentials: "include"`, "portal"],
  ["a 403 reads as an error with a retry", "src/api/hooks.ts", `error.status === 403`, `error.status === 999`, "portal"],
  ["each tab shows, whatever /me says", "src/portal/PortalApp.tsx", `TABS.filter((tab) => tab.needs === null || held.has(tab.needs))`, `TABS.filter(() => true)`, "portal"],
  ["the name comes from nowhere", "src/portal/PortalApp.tsx", `<b>{me.data.username}</b>`, `<b>ola</b>`, "portal"],
  ["two columns swapped", "src/portal/RequestsTab.tsx", `r.requestId, r.clusterId, r.namespace,`, `r.requestId, r.namespace, r.clusterId,`, "portal"],
  ["each status the wrong colour", "src/portal/format.ts", `pending_approval: "warn", awaiting_prune: "warn",`, `pending_approval: "ok", awaiting_prune: "ok",`, "portal"],
  ["the approval count is wrong", "src/portal/format.ts", "`${a.rule} · ${need - left} of ${need}`", "`${a.rule} · ${need} of ${need}`", "portal"],
  ["the status filter stays in the browser", "src/portal/RequestsTab.tsx", `if (state !== "all") query.state = state;`, ``, "portal"],
  ["the search stays in the browser", "src/portal/RequestsTab.tsx", `if (q) query.q = q;`, ``, "portal"],
  ["Next is connected to nothing", "src/portal/RequestsTab.tsx", `next={() => page.nextCursor && setCursor(page.nextCursor)}`, `next={() => {}}`, "portal"],
  ["Next is never disabled", "src/portal/RequestsTab.tsx", `nextDis={!page.nextCursor}`, `nextDis={false}`, "portal"],
  ["the empty sentence is gone", "src/portal/RequestsTab.tsx", `{result.data.items.length === 0 && <Empty>`, `{false && <Empty>`, "portal"],
  ["a changed heading", "src/portal/RequestsTab.tsx", `<Head title="Requests" lede="Every write you`, `<Head title="Requests" lede="Each write you`, "portal"],
  ["an invented sentence", "src/portal/RequestsTab.tsx", `<Small>This list shows the`, `<Small>Requests are kept for 90 days. This list shows the`, "portal"],
  ["Open at current step looks active", "src/portal/RequestsTab.tsx", `isAriaDisabled aria-describedby={WHY_NOT_OPEN}`, ``, "portal"],
  ["Try again is connected to nothing", "src/portal/RequestsTab.tsx", `<AlertActionLink onClick={retry}>`, `<AlertActionLink onClick={() => {}}>`, "portal"],
  ["no loading line", "src/portal/RequestsTab.tsx", `<span role="status">Loading requests…</span>`, ``, "portal"],
  ["sign-out stays in the browser", "src/portal/PortalApp.tsx", `void auth.signoutRedirect();`, ``, "portal"],
  ["the sample logic is in the portal's build", "src/main.tsx", `import.meta.env.MODE === "demo"`, `import.meta.env.MODE !== "demo"`, "bundle"],
  ["a bad config.json is accepted", "src/portal/config.ts", `if (url.protocol !== "https:" && !local)`, `if (false)`, "bundle"],
  ["a missing issuer is accepted", "src/portal/config.ts", "if (typeof value !== \"string\" || !value) throw new ConfigError(`config.json has no ${name}.`);", `if (typeof value !== "string" || !value) return "https://sso.example.test";`, "bundle"]
];

const only = process.argv[2];
const results = [];
for (const [what, file, from, to, suite] of MUTANTS) {
  if (only && !what.includes(only)) continue;
  const path = join(app, file), source = readFileSync(path, "utf8");
  if (source.split(from).length !== 2) throw new Error(`${what}: the text is not in ${file} exactly one time`);
  writeFileSync(path, source.replace(from, to));
  let outcome;
  try {
    execFileSync(vite, ["build"], { cwd: app, stdio: "ignore" });
    const run = spawnSync(process.execPath, [join(app, "tests", "api", `${suite}.test.mjs`)], { cwd: app, encoding: "utf8" });
    outcome = run.status === 0 ? "SURVIVED" : `killed: ${(run.stderr.match(/AssertionError[^\n]*\n?[^\n]*|TimeoutError[^\n]*|Timeout \d+ms[^\n]*/) ?? ["the suite failed"])[0].replace(/\s+/g, " ").slice(0, 150)}`;
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
