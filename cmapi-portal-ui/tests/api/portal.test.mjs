#!/usr/bin/env node
// The portal on the API (issue #204), against the built portal (dist/), a stand-in issuer and a stand-in API.
// Stage: built-mocked. It proves what the browser does. It does not prove a sign-in on a real Keycloak or a call to
// the real service. PW_CHANNEL=chrome runs it in the installed Chrome, and PW_HEADED=1 shows the window.
import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { isDeepStrictEqual } from "node:util";
import { AxeBuilder } from "@axe-core/playwright";
import { chromium } from "playwright";
import { COMPANY_KEYS, expirationsFrom, quotaCsv, quotaQueryOf, quotasFrom, quotaSuggest, REFERENCE_KEYS, requestsFrom, requestWith, SAMPLES, servePortal, startApi, startIssuer, USERS } from "./standin.mjs";

const app = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const out = join(app, "test-output", "api");
mkdirSync(out, { recursive: true });

let portal;
const issuer = await startIssuer({ redirectUris: () => [portal.page] });
const api = await startApi({ issuer, portalOrigin: () => portal.origin });
const CONFIG = { apiUrl: api.url, issuer: issuer.url, clientId: "cmapi-portal", audience: "cmapi-nonprod", instance: "nonprod", displayName: "Non-production", environments: ["rnd", "dev"],
  otherInstances: { prod: { environments: ["prod"], url: "https://cmapi.example.test" }, staging: { environments: ["qa", "uat"], url: "https://cmapi-staging.example.test" } } };
portal = await servePortal(join(app, "dist"), () => CONFIG);
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL, headless: !process.env.PW_HEADED });

const recorded = SAMPLES.operations.requests_list_requests.response.body.items[0];
const sixtyOne = requestsFrom(recorded, 61);
const AUTH = `${issuer.url}/protocol/openid-connect/auth`;
// Chrome reports each answer that is not 2xx as a console error. A check that asks for one names its status here.
let expectedStatus = [];

/** A new browser profile: no session, no storage. */
async function fresh({ user = "requester", items = sixtyOne, mode = "ok", width = 1440, quotas = SAMPLES.operations.quotas_quotas.response.body.items, kpi = SAMPLES.operations.admin_kpi.response.body,
  expirations = [], never = false, metadataKeys = REFERENCE_KEYS } = {}) {
  issuer.state.user = user && USERS[user];
  issuer.state.sessions = true;
  issuer.state.lifetime = 300;
  Object.assign(api.state, { mode, items, delayMs: 0, seen: [], answers: [], lose: new Set(), keys: new Map(), created: 0, clusters: SAMPLES.operations.core_clusters.response.body.items,
    tiers: SAMPLES.operations.tiers_tiers.response.body, plan: SAMPLES.operations["namespaces_create_namespace:dryRun"].response.body, quotas, etags: new Map(), kpi,
    expirations, never, today: SAMPLES.operations.expiration_expirations.response.body.today, metadataKeys, protection: new Map() });
  issuer.state.seen.length = 0;
  expectedStatus = [];
  const context = await browser.newContext({ viewport: { width, height: 1000 } });
  const page = await context.newPage();
  page.setDefaultTimeout(8000);
  const errors = [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const status = /status of (\d{3})/.exec(m.text())?.[1];
    if (!status || !expectedStatus.includes(Number(status))) errors.push(`${m.text()} (${m.location().url})`);
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return { context, page, errors };
}
const open = async (page, hash = "#requests") => {
  await page.goto(portal.page + hash);
  await page.locator("[role=tablist]").waitFor();
};
const panel = (page) => page.getByRole("tabpanel");
const rows = (page) => page.locator("table[aria-label=Requests] tbody tr").evaluateAll((trs) => trs.map((tr) => [...tr.children].map((td) => td.innerText.replace(/\s+/g, " ").trim())));
const range = (page) => panel(page).getByText(/ of \d+ · newest first$|^0 requests$/).innerText();
/** Waits for the pager to say `want`. A failure says what the pager and the API's last call were. */
async function waitRange(page, want) {
  try {
    await page.waitForFunction((text) => document.querySelector("[role=tabpanel]")?.innerText.includes(text), want);
  } catch {
    assert.fail(`the pager never said "${want}": it says "${await range(page).catch(() => "nothing")}", and the last call was ${JSON.stringify(api.state.seen.at(-1))}`);
  }
}
const calls = (path) => api.state.seen.filter((c) => c.path === path);
const tabNames = (page) => page.getByRole("tab").allInnerTexts();

// What one request of the API reads as in the table. Written from the mockup's forms, not from the page's code.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function expectedRow(r) {
  const at = new Date(r.updatedAt), time = r.updatedAt.slice(11, 16);
  const today = r.updatedAt.slice(0, 10) === new Date().toISOString().slice(0, 10);
  const need = r.approval.slots.reduce((n, s) => n + s.count, 0), left = r.approval.remaining.reduce((n, s) => n + s.needed, 0);
  const last = r.events.at(-1);
  return [r.requestId, r.clusterId, r.namespace, r.action, r.status, `${last.event} by ${last.by}`, `${r.approval.rule} · ${need - left} of ${need}`,
    r.pr ? `#${r.pr.number}` : "—", today ? time : `${MONTHS[at.getUTCMonth()]} ${at.getUTCDate()} ${time}`, "Open at current step"];
}

// No check may wait without end: a defect in the page must fail the suite, not hang it.
const CHECK_TIMEOUT_MS = 90_000;
const done = [];
async function check(name, run) {
  // CHECK=F2 runs only the checks whose name starts with F2.
  if (process.env.CHECK && !name.startsWith(process.env.CHECK)) return;
  let timer;
  const late = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`"${name}" did not end in ${CHECK_TIMEOUT_MS / 1000} s`)), CHECK_TIMEOUT_MS); });
  try {
    await Promise.race([run(), late]);
  } finally {
    clearTimeout(timer);
  }
  done.push(name);
  console.log(`ok - ${name}`);
}

try {
  await check("F2 persistent API 401s stop for an explicit sign-in", async () => {
    const { context, page } = await fresh({ mode: "always401" });
    expectedStatus = [401];
    try {
      await page.goto(`${portal.page}#requests`);
      await page.getByRole("heading", { name: "Sign-in did not complete." }).waitFor();
      await page.waitForTimeout(500);
      assert.equal(issuer.state.seen.filter((s) => s.what === "auth").length, 1);
      assert.equal(calls("/api/v1/me").length, 2);
      api.state.mode = "ok";
      await page.getByRole("button", { name: "Sign in again" }).click();
      await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
      assert.equal(issuer.state.seen.filter((s) => s.what === "auth").length, 2);
    } finally { await context.close(); }
  });

  await check("F4 automatic renewal failure has a visible recovery action", async () => {
    const { context, page } = await fresh();
    expectedStatus = [400];
    try {
      let first = true;
      await page.route(`${issuer.url}/protocol/openid-connect/token`, async (route) => {
        if (!first) return route.continue();
        first = false;
        const response = await route.fetch();
        const body = await response.json();
        await route.fulfill({ response, json: { ...body, expires_in: 2 } });
      });
      await open(page);
      issuer.state.sessions = false;
      await page.getByRole("heading", { name: "Sign-in did not complete." }).waitFor();
      assert.equal(await page.getByRole("table").count(), 0);
      assert.equal(issuer.state.seen.filter((s) => s.what === "auth").length, 1);
      issuer.state.sessions = true;
      await page.getByRole("button", { name: "Sign in again" }).click();
      await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
    } finally { await context.close(); }
  });

  await check("F9 an issuer error without state cannot trigger automatic sign-in", async () => {
    const { context, page } = await fresh();
    try {
      let authorizations = 0;
      await page.route(`${AUTH}*`, (route) => {
        ++authorizations;
        return route.fulfill({ status: 302, headers: { location: `${portal.page}?error=access_denied` }, body: "" });
      });
      await page.goto(`${portal.page}?error=access_denied`);
      await page.getByRole("heading", { name: "Sign-in did not complete." }).waitFor();
      await page.waitForTimeout(500);
      assert.equal(authorizations, 0);
      assert.equal(page.url(), portal.page);
      assert.equal(await page.getByRole("button", { name: "Sign in again" }).count(), 1);
    } finally { await context.close(); }
  });

  await check("F5 failed callbacks scrub the current address and history entry", async () => {
    for (const kind of ["code-exchange", "error"]) {
      const { context, page } = await fresh();
      expectedStatus = [400];
      try {
        if (kind === "code-exchange") {
          await page.route(`${issuer.url}/protocol/openid-connect/token`, (route) => route.fulfill({
            status: 400, contentType: "application/json", body: JSON.stringify({ error: "invalid_grant" })
          }));
          await page.goto(portal.page);
        } else await page.goto(`${portal.page}?error=access_denied&state=unknown`);
        await page.getByRole("heading", { name: "Sign-in did not complete." }).waitFor();
        await page.waitForFunction(() => location.search === "");
        const cdp = await context.newCDPSession(page);
        const history = await cdp.send("Page.getNavigationHistory");
        assert.equal(history.entries[history.currentIndex].url, portal.page);
        assert.equal(issuer.state.seen.filter((s) => s.what === "auth").length, kind === "error" ? 0 : 1);
      } finally { await context.close(); }
    }
  });

  await check("1 no session: the browser goes to the issuer with code, S256, the client and a state; no token in a URL or in storage", async () => {
    const { context, page, errors } = await fresh({ user: null });
    await page.goto(`${portal.page}#requests`);
    await page.waitForURL((url) => url.href.startsWith(AUTH));
    const q = Object.fromEntries(new URL(page.url()).searchParams);
    assert.equal(q.response_type, "code");
    assert.equal(q.client_id, "cmapi-portal");
    assert.equal(q.code_challenge_method, "S256");
    assert.match(q.code_challenge, /^[A-Za-z0-9_-]{43}$/, "the challenge is a SHA-256 in base64url");
    assert.ok(q.state, "a state");
    assert.equal(q.redirect_uri, portal.page, "the redirect URI is the page, with no query and no fragment");
    assert.equal(q.scope, "openid");
    assert.deepEqual(Object.keys(q).filter((k) => /token|password|secret/i.test(k)), [], "no token and no secret in the authorization request");
    assert.equal(calls("/api/v1/me").length + calls("/api/v1/requests").length, 0, "no API call before the sign-in");

    // Now the person signs in at the issuer, and the issuer sends the browser back with a code.
    issuer.state.user = USERS.requester;
    await page.goto(page.url());
    await page.locator("[role=tablist]").waitFor();
    await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
    assert.equal(page.url(), `${portal.page}#requests`, "the code and the state are gone from the address, and the view is back");
    const tokens = issuer.tokens();
    assert.ok(tokens.length >= 2, "the issuer gave an access token and a refresh token");
    const stored = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }));
    assert.deepEqual(stored.local, {}, "localStorage is empty");
    const kept = JSON.stringify(stored.session);
    for (const t of tokens) assert.ok(!kept.includes(t), "no token in sessionStorage");
    assert.ok(!/code_verifier/.test(kept), "the PKCE verifier is removed after the exchange");
    const urls = [...issuer.state.seen.map((s) => s.url ?? ""), ...api.state.seen.map((c) => c.path + JSON.stringify(c.query))].join("\n");
    for (const t of tokens) assert.ok(!urls.includes(t), "no token in a URL");
    assert.deepEqual(issuer.state.seen.filter((s) => s.what === "token").map((s) => s.grant), ["authorization_code"], "one code exchange");
    assert.ok(api.state.seen.every((c) => c.cookie === null), "no cookie goes to the API");
    assert.ok(api.state.seen.every((c) => c.user === "ola"), "each API call carries the person's token");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("2 the Requests tab shows the recorded request of GET /api/v1/requests, cell by cell", async () => {
    const { context, page, errors } = await fresh({ items: [recorded] });
    await open(page);
    assert.deepEqual(await rows(page), [expectedRow(recorded)]);
    assert.equal(await range(page), "1–1 of 1 · newest first");
    assert.match(await page.locator("table[aria-label=Requests] tbody tr .pf-v6-c-label").getAttribute("class"), /pf-m-warning/, "pending_approval has the mockup's warn tone");
    // Open at current step opens the Workflow tab on this request (check 8 follows it there).
    const openButton = page.getByRole("button", { name: "Open at current step" });
    assert.equal(await openButton.getAttribute("aria-disabled"), null, "the button is on");
    assert.deepEqual(calls("/api/v1/requests")[0].query, { limit: "25" }, "the first page: 25 rows, no filter");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("2 cursor paging: forward to the last page and back, each row one time; search and status are API parameters", async () => {
    const { context, page, errors } = await fresh();
    await open(page);
    const seen = [];
    const ranges = [];
    const next = page.getByRole("button", { name: "Next ›" }).first(), prev = page.getByRole("button", { name: "‹ Previous" }).first();
    assert.equal(await prev.getAttribute("aria-disabled"), "true", "no page before the first");
    // 61 rows are three pages. One more turn than that means that Next did not go off on the last page.
    for (let turn = 0; ; turn++) {
      assert.ok(turn < 3, "Next is off on the last page");
      ranges.push(await range(page));
      seen.push(...(await rows(page)).map((r) => r[0]));
      if (await next.getAttribute("aria-disabled") === "true") break;
      await next.click();
      await waitRange(page, ranges.length === 1 ? "26–50 of 61" : "51–61 of 61");
    }
    assert.deepEqual(ranges, ["1–25 of 61 · newest first", "26–50 of 61 · newest first", "51–61 of 61 · newest first"]);
    assert.deepEqual(seen, sixtyOne.map((r) => r.requestId), "each request one time, newest first");
    await prev.click();
    await waitRange(page, "26–50 of 61");
    assert.deepEqual(await rows(page), sixtyOne.slice(25, 50).map(expectedRow), "the page before, cell by cell");
    // Two moves forward sent two cursors of the API. The move back shows a page that Query still holds (15 seconds).
    assert.equal(calls("/api/v1/requests").filter((c) => c.query.cursor).length, 2, "each new page sends the cursor of the API");

    await page.getByRole("textbox", { name: "Find a request" }).fill("LEDGER");
    await waitRange(page, "1–25 of 30 · newest first");
    const searched = calls("/api/v1/requests").at(-1).query;
    assert.deepEqual(searched, { limit: "25", q: "LEDGER" }, "the search goes to the API, and the page starts again without a cursor");
    assert.ok((await rows(page)).every((r) => r[2].startsWith("ledger-")));
    await page.getByRole("group", { name: "Status" }).getByRole("button", { name: "Open", exact: true }).click();
    const wanted = sixtyOne.filter((r) => r.namespace.startsWith("ledger-") && ["pending_approval", "approved", "pr_open", "merged", "awaiting_prune", "sync_failed"].includes(r.status));
    assert.ok(wanted.length > 0 && wanted.length < 25, "one page of open ledger requests");
    await waitRange(page, `1–${wanted.length} of ${wanted.length} · newest first`);
    assert.deepEqual(calls("/api/v1/requests").at(-1).query, { limit: "25", q: "LEDGER", state: "open" });
    assert.deepEqual(await rows(page), wanted.map(expectedRow));
    assert.equal(new URL(page.url()).hash, "#requests?q=LEDGER&state=open", "the address holds the view");

    // The same address in a new page: the tokens were in memory only, so the portal signs in again and returns to the view.
    const again = await context.newPage();
    await again.goto(page.url());
    await again.locator("table[aria-label=Requests] tbody tr").first().waitFor();
    assert.equal(new URL(again.url()).hash, "#requests?q=LEDGER&state=open");
    assert.equal(await again.getByRole("textbox", { name: "Find a request" }).inputValue(), "LEDGER");
    assert.deepEqual(await rows(again), wanted.map(expectedRow));
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("3 loading, then empty with the mockup's words", async () => {
    const { context, page, errors } = await fresh({ mode: "empty" });
    api.state.delayMs = 700;
    await page.goto(`${portal.page}#requests`);
    await page.getByRole("status").filter({ hasText: "Loading requests…" }).waitFor();
    await panel(page).getByText("No requests on the nonprod instance match this search and filter.").waitFor();
    assert.equal(await range(page), "0 requests");
    assert.equal(await page.getByRole("status").filter({ hasText: "Loading requests…" }).count(), 0);
    assert.deepEqual(await rows(page), []);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("3 a 403 shows the problem's detail and offers no action", async () => {
    const { context, page, errors } = await fresh({ mode: "forbidden" });
    expectedStatus = [403];
    await open(page);
    await panel(page).getByRole("heading", { name: "You do not have permission to see requests." }).waitFor();
    assert.match(await panel(page).innerText(), /Missing permission requests:read: no role in your token grants it/);
    assert.equal(await panel(page).getByRole("button").count(), 0, "no button: no retry, no filter, no row");
    assert.equal(await panel(page).locator("table").count(), 0);
    assert.equal(calls("/api/v1/requests").length, 1, "the portal does not ask again");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("3 a 401: one silent renewal and the same call again; then, with the session ended, sign-in again", async () => {
    const { context, page, errors } = await fresh({ mode: "expire-once" });
    expectedStatus = [401, 400];
    await open(page);
    await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
    assert.deepEqual(issuer.state.seen.filter((s) => s.what === "token").map((s) => s.grant), ["authorization_code", "refresh_token"], "one renewal, with the refresh token");
    assert.equal(issuer.state.seen.filter((s) => s.what === "auth").length, 1, "no second visit to the issuer");
    assert.equal((await rows(page)).length, 25, "the rows are there: the person saw no error");

    // The session ends: the API refuses the token and the issuer refuses the refresh token.
    api.state.mode = "always401";
    issuer.state.sessions = false;
    issuer.state.user = null;
    await page.getByRole("group", { name: "Status" }).getByRole("button", { name: "Closed", exact: true }).click();
    await page.getByRole("heading", { name: "Sign-in did not complete." }).waitFor();
    await page.getByRole("button", { name: "Sign in again" }).click();
    await page.waitForURL((url) => url.href.startsWith(AUTH));
    assert.equal(issuer.state.seen.filter((s) => s.what === "token" && s.grant === "refresh_token").length, 2, "one more renewal try, and no more");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("3 a 5xx shows the problem's detail, and Try again sends the call again", async () => {
    const { context, page, errors } = await fresh({ mode: "error500" });
    expectedStatus = [500];
    await open(page);
    const alert = panel(page).locator(".pf-v6-c-alert");
    await alert.getByText("The requests did not load.").waitFor();
    assert.match(await alert.innerText(), /The database did not answer\./);
    assert.match(await alert.getAttribute("class"), /pf-m-danger/);
    assert.equal(calls("/api/v1/requests").length, 1, "no retry until the person asks");
    api.state.mode = "ok";
    await alert.getByRole("button", { name: "Try again" }).click();
    await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
    assert.equal(await alert.count(), 0);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("5 a role sees the tabs that GET /api/v1/me permits: a viewer, an approver, a requester, an operator", async () => {
    // The stand-in's access token is an opaque string, so the browser cannot read a role from it.
    const base = ["Workflow", "Quotas", "Expiration", "Requests", "Policies", "Capacity"];
    const want = {
      viewer: base,
      approver: ["Workflow", "Quotas", "Expiration", "Requests", "Approvals", "Policies", "Capacity"],
      requester: ["Workflow", "New namespace", "Quotas", "Expiration", "Requests", "Policies", "Capacity"],
      // KPIs is operator and above: reports:read (docs/14).
      operator: ["Workflow", "New namespace", "Quotas", "Expiration", "Requests", "Policies", "Capacity", "KPIs"]
    };
    for (const [user, tabs] of Object.entries(want)) {
      const { context, page, errors } = await fresh({ user });
      await open(page);
      assert.deepEqual(await tabNames(page), tabs, user);
      assert.match(await page.locator("header").innerText(), new RegExp(`${USERS[user].username}\\s*${USERS[user].role} \\(Keycloak roles\\)`), "the name and the roles come from /me");
      // A tab that the person does not hold is not reachable by its address either.
      await page.goto(`${portal.page}#approvals`);
      await page.reload();
      await page.locator("[role=tablist]").waitFor();
      const selected = await page.getByRole("tab", { selected: true }).innerText();
      assert.equal(selected, tabs.includes("Approvals") ? "Approvals" : "Workflow", `${user}: #approvals`);
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("6 the tab says what the mockup says, and adds only what is listed", async () => {
    const { context, page, errors } = await fresh({ items: [recorded] });
    await open(page);
    // The mockup's block of the tab, as text: each tag out, each {{hole}} a break.
    const mockup = readFileSync(join(app, "..", "mockups", "portal", "Main.dc.html"), "utf8");
    const block = mockup.slice(mockup.indexOf('<sc-if value="{{isRequests}}"'), mockup.indexOf('<sc-if value="{{isApprovals}}"'));
    const attrs = [...block.matchAll(/(?:placeholder|aria-label)="([^"{]+)"/g)].map((m) => m[1]);
    const texts = block.replace(/<[^>]+>/g, "\n").split(/\n|\{\{[^}]+\}\}/).map((s) => s.replace(/\s+/g, " ").trim()).filter(Boolean);
    const chips = ["All", "Open", "Closed"]; // reqFilters in the mockup's logic
    // The mockup's replay buttons open its sample scenarios. The portal has none (MOCKUP-CONTRACT.md).
    const MOCKUP_ONLY = ["Replay a policy rejection", "Replay a wrong-instance request"];
    const fromMockup = [...texts, ...attrs, ...chips].filter((s) => !MOCKUP_ONLY.includes(s));
    assert.ok(fromMockup.length >= 20, `the mockup's block was read (${fromMockup.length} strings)`);
    const read = () => panel(page).evaluate((root) => {
      const found = [];
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) if (walker.currentNode.nodeValue.trim()) found.push(walker.currentNode.nodeValue.replace(/\s+/g, " ").trim());
      root.querySelectorAll("[placeholder]").forEach((el) => found.push(el.getAttribute("placeholder")));
      root.querySelectorAll("[aria-label]").forEach((el) => found.push(el.getAttribute("aria-label")));
      return found;
    });
    // Two states of the tab: one request, and no request. The mockup's sentence for an empty list shows only in the second.
    const shown = await read();
    api.state.mode = "empty";
    await page.getByRole("group", { name: "Status" }).getByRole("button", { name: "Closed", exact: true }).click();
    await waitRange(page, "0 requests");
    shown.push(...await read());
    const squeeze = (text) => text.replace(/\s+/g, "");
    const all = squeeze(shown.join(" "));
    const missing = fromMockup.filter((text) => !all.includes(squeeze(text)));
    assert.deepEqual(missing, [], "each string of the mockup's tab is on the page");
    // What the page adds: the data, PatternFly's own words for a screen reader, and the one line that MOCKUP-CONTRACT.md lists.
    const data = [...expectedRow(recorded), "plan_needs_approval", "by ola", "1–1 of 1 · newest first", "0 requests", "nonprod"];
    const LIBRARY = ["Reset", "Warning alert:"];
    const ADDED = [];
    const known = [...fromMockup, ...data, ...LIBRARY, ...ADDED].sort((x, y) => y.length - x.length);
    const invented = shown.filter((text) => known.reduce((rest, k) => rest.split(k).join(""), text).trim() !== "");
    assert.deepEqual(invented, [], "no string that the mockup does not have");
    assert.deepEqual(errors, []);
    await context.close();
  });

  // The Workflow tab's requests: the recorded synced request of GET /api/v1/requests/{id}, cut at its applied event
  // (#286: applied before the merge), and the same cut followed by merge_failed. Written from the samples, not the page.
  const synced = SAMPLES.operations.requests_get_request.response.body;
  const upToApplied = synced.events.slice(0, synced.events.findIndex((e) => e.event === "applied") + 1);
  const applied = requestWith(synced, { requestId: "req-20261115-1002", namespace: "ledger-dev", status: "applied", events: upToApplied, mergeSha: null });
  const mergeFailed = requestWith(synced, { requestId: "req-20261115-1001", namespace: "billing-dev", status: "merge_failed", mergeSha: null,
    events: [...upToApplied, { at: "2026-11-15T07:44:10.000000Z", by: "worker", event: "merge_failed", note: "the PR head moved: 9f1c2d3e is not the plan's", status: "merge_failed" }] });
  const clock = (iso) => iso.slice(11, 19);
  const eventRows = (events) => events.map((e) => `${clock(e.at)} ${e.event} · ${e.by}${e.note ? ` ${e.note}` : ""}`);
  const listed = (page) => page.locator("[role=tabpanel] .pf-v6-c-card").filter({ has: page.getByRole("heading", { name: "Events" }) }).locator("li")
    .evaluateAll((lis) => lis.map((li) => li.innerText.replace(/\s+/g, " ").trim()));
  const banner = (page) => panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Current position." });
  const statusPill = (page) => panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: "Change request" }) }).locator(".pf-v6-c-label").first();

  await check("8 Workflow: Open at current step in Requests shows the request's events as its steps; applied and merge_failed keep their tones; an open request is followed to synced", async () => {
    const { context, page, errors } = await fresh({ items: [applied, mergeFailed] });
    await open(page);
    await page.locator("table[aria-label=Requests] tbody tr").filter({ hasText: applied.requestId }).getByRole("button", { name: "Open at current step" }).click();
    await banner(page).waitFor();
    assert.equal(new URL(page.url()).hash, `#workflow?request=${applied.requestId}`, "the address names the request");
    assert.equal(await page.getByRole("tab", { selected: true }).innerText(), "Workflow");
    assert.match(await banner(page).innerText(), new RegExp(`${applied.requestId} is at step 6 of 6: applied\\.`));
    assert.match(await statusPill(page).innerText(), /^applied$/);
    assert.match(await statusPill(page).getAttribute("class"), /pf-m-info/, "applied has the info tone of an open request");
    assert.deepEqual(await listed(page), eventRows(upToApplied), "each event, oldest first: time, event, actor and note");
    assert.deepEqual(await page.getByRole("list", { name: "Steps" }).locator("li").evaluateAll((lis) => lis.map((li) => li.innerText.replace(/\s+/g, " ").trim())),
      upToApplied.map((e, j) => `${j + 1} ${e.event}${j === upToApplied.length - 1 ? " current position" : ""} ${e.by}`), "one step for each event");
    assert.ok(calls(`/api/v1/requests/${applied.requestId}/events`).length >= 1 && calls(`/api/v1/requests/${applied.requestId}`).length >= 1, "the events and the request come from the API");

    // Playback, as the mockup's: Reset, Next step, Back, and Back to current step.
    const counter = () => panel(page).getByRole("group", { name: "Playback" }).locator("[aria-live]").innerText();
    assert.equal(await counter(), "6 / 6");
    assert.equal(await panel(page).getByRole("button", { name: "Next step" }).isDisabled(), true, "Next is off at the last step");
    await panel(page).getByRole("button", { name: "Reset" }).click();
    assert.equal(await counter(), "1 / 6");
    assert.equal(await panel(page).getByRole("button", { name: "Back", exact: true }).isDisabled(), true, "Back is off at the first step");
    await panel(page).getByRole("button", { name: "Next step" }).click();
    assert.equal(await counter(), "2 / 6");
    assert.equal(await panel(page).locator("article h2").innerText(), upToApplied[1].event, "the detail shows the step in view");
    await banner(page).getByRole("button", { name: "Back to current step" }).click();
    assert.equal(await counter(), "6 / 6");

    // The request moves on. The tab reads its events again while it is open, and follows it to synced.
    api.state.items = api.state.items.map((r) => (r.requestId === applied.requestId ? { ...synced, requestId: applied.requestId, namespace: applied.namespace } : r));
    await page.waitForFunction((id) => document.querySelector("[role=tabpanel]")?.innerText.includes(`${id} finished at step 9 of 9: synced.`), applied.requestId, { timeout: 15000 });
    assert.match(await statusPill(page).getAttribute("class"), /pf-m-success/, "synced has the ok tone");
    assert.deepEqual(await listed(page), eventRows(synced.events));
    const prCard = panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: "Pull request · Git" }) });
    assert.match(await prCard.innerText(), new RegExp(`merged[\\s\\S]*#${synced.pr.number}[\\s\\S]*${synced.pr.branch} → main`));
    const polls = calls(`/api/v1/requests/${applied.requestId}/events`).length;
    await page.waitForTimeout(6000);
    assert.equal(calls(`/api/v1/requests/${applied.requestId}/events`).length, polls, "a finished request is not read again");

    // The other request ended in merge_failed: an open state with the bad tone.
    await panel(page).getByRole("group", { name: "Scenarios" }).getByRole("button", { name: new RegExp(mergeFailed.requestId) }).click();
    await page.waitForFunction((id) => document.querySelector("[role=tabpanel]")?.innerText.includes(`${id} is at step 7 of 7: merge_failed.`), mergeFailed.requestId);
    assert.match(await statusPill(page).getAttribute("class"), /pf-m-danger/, "merge_failed has the bad tone");
    assert.equal(new URL(page.url()).hash, `#workflow?request=${mergeFailed.requestId}`);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("8 Workflow states: loading, no request, a 404 with Try again, and a 403 with no action", async () => {
    {
      const { context, page, errors } = await fresh({ mode: "empty" });
      api.state.delayMs = 700;
      await page.goto(`${portal.page}#workflow`);
      await page.getByRole("status").filter({ hasText: "Loading the request…" }).waitFor();
      await panel(page).getByText("No requests on the nonprod instance yet.").waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ items: [applied] });
      expectedStatus = [404];
      await open(page, "#workflow?request=req-20261115-0404");
      const alert = panel(page).locator(".pf-v6-c-alert");
      await alert.getByText("The request did not load.").waitFor();
      assert.match(await alert.innerText(), /No request req-20261115-0404/);
      await panel(page).getByRole("group", { name: "Scenarios" }).getByRole("button", { name: new RegExp(applied.requestId) }).click();
      await banner(page).waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ items: [applied] });
      expectedStatus = [403];
      const denied = { type: "https://cmapi.ephico2real.com/problems/forbidden", title: "forbidden", status: 403, code: "forbidden", detail: "Missing permission requests:read: no role in your token grants it (roles: ['cmapi-none'])" };
      api.state.answers.push({ route: `GET /api/v1/requests/${applied.requestId}/events`, status: 403, body: denied });
      await open(page, `#workflow?request=${applied.requestId}`);
      await panel(page).getByRole("heading", { name: "You do not have permission to see this request." }).waitFor();
      assert.match(await panel(page).innerText(), /Missing permission requests:read/);
      assert.equal(await panel(page).getByRole("button").count(), 0, "no action");
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  const newTab = async (page) => {
    await open(page, "#new");
    await panel(page).getByRole("button", { name: "Dry run" }).waitFor();
  };
  const fillForm = async (page, { team = "payments", dl = "payments-team@ephico2real.com" } = {}) => {
    await page.getByLabel("Team (required)").fill(team);
    await page.getByLabel("Team DL (required)").fill(dl);
    await page.getByLabel("Justification").fill("Payments service dev namespace");
  };
  const posts = () => api.state.seen.filter((c) => c.method === "POST" && c.path === "/api/v1/clusters/CRC/namespaces");
  const approvalCard = (page) => panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: "Approval that will apply" }) });

  await check("9 New namespace: the tiers and clusters of the API, the dry run's plan and approval, and a submit that opens the new request", async () => {
    const { context, page, errors } = await fresh();
    await newTab(page);
    const env = panel(page).getByRole("group", { name: "Environment" });
    assert.deepEqual(await env.getByRole("button").allInnerTexts(), ["rnd", "dev"]);
    assert.equal(await env.getByRole("button", { name: "dev" }).getAttribute("aria-pressed"), "true", "dev: the first environment with a cluster to write to");
    const tiers = SAMPLES.operations.tiers_tiers.response.body.environments.dev.tiers.filter((t) => !t.custom);
    assert.deepEqual((await panel(page).getByRole("group", { name: "Tier" }).getByRole("button").allInnerTexts()).map((t) => t.replace(/\s+/g, " ")),
      tiers.map((t) => `${t.name} ${t.quota["requests.cpu"]} cores · ${t.quota["requests.memory"]}`), "the tiers of GET /api/v1/tiers?environment=dev");
    assert.deepEqual(calls("/api/v1/tiers").map((c) => c.query), [{ environment: "dev" }]);
    assert.equal(await page.getByLabel("Cluster").inputValue(), "CRC");
    assert.match(await panel(page).innerText(), /prod → prod portal/, "the other instances' portals, from config.json");
    assert.match(await panel(page).innerText(), /Requested by ola \(ola@ephico2real\.com\), from your sign-in\./, "the requester comes from /me");
    await fillForm(page);
    assert.equal(await page.getByLabel("Namespace name").inputValue(), "payments-dev", "the mockup's name: team and environment");

    await panel(page).getByRole("button", { name: "Dry run" }).click();
    const callout = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Dry run passed · nothing written" });
    await callout.waitFor();
    assert.deepEqual((await callout.locator("li").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim()), [
      "✓ Environment served dev in [rnd, dev]", "✓ Capacity fits on fresh data", "✓ Expiry none: permanent", "! Approval dev-create · 2 of approver-platform"
    ]);
    const plan = SAMPLES.operations["namespaces_create_namespace:dryRun"].response.body;
    assert.match(await approvalCard(page).innerText(), new RegExp(`2 approvals in cmapi from approver-platform\\s+${plan.approval.reasons.join("; ").replace(/[+()]/g, "\\$&")}\\. Self-approval is allowed in dev\\.`));
    assert.match(await approvalCard(page).innerText(), /Rule\s+dev-create · 2 of approver-platform\s+Quota\s+16 cores · 32Gi · 100 pods\s+Expires\s+never \(permanent\)\s+Lands in Git\s+clusters\/CRC\/namespaces\/payments-dev\//);
    const dry = posts().filter((c) => c.query.dryRun === "true");
    assert.equal(dry.length, 1, "one dry run");
    assert.equal(dry[0].key, null, "a dry run sends no Idempotency-Key");
    assert.deepEqual(dry[0].body, { namespace: "payments-dev", tier: "medium", labels: { "cmapi.net/team": "payments" }, annotations: { "cmapi.net/team-dl": "payments-team@ephico2real.com" }, justification: "Payments service dev namespace" });
    // A change to the form hides the plan, as in the mockup.
    await panel(page).getByRole("group", { name: "Tier" }).getByRole("button", { name: /^small/ }).click();
    assert.equal(await callout.count(), 0, "the plan is of the old form");

    // The first submit meets a failure of the API; Submit again sends the same key. The answer of the second is lost on the
    // way, so the person submits a third time: the API answers with the request it made, and makes no second one.
    // Submit on the changed form plans it first, and the plan is shown; the next Submit sends it.
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    await callout.waitFor();
    assert.equal(posts().filter((c) => c.query.dryRun !== "true").length, 0, "the changed form was planned, not submitted");
    expectedStatus = [502];
    api.state.answers.push({ route: "POST /api/v1/clusters/CRC/namespaces", status: 502, body: { type: "https://cmapi.ephico2real.com/problems/git-unavailable", title: "git-unavailable", status: 502, code: "git-unavailable", detail: "The Git host did not answer." } });
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    const notSubmitted = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Not submitted" });
    await notSubmitted.getByText(/The Git host did not answer\./).waitFor();
    // A 5xx is the API failing, not refusing: the page says that the same submit can be sent again.
    assert.match(await notSubmitted.innerText(), /The Git host did not answer\. Submit again: the same request is sent, and the API makes it at most once\./);
    // Chrome sends a POST again by itself when a reused connection closes with no answer; that retry is lost as well.
    api.state.lose.add("POST /api/v1/clusters/CRC/namespaces");
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    await panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Not submitted" }).getByText(/The network did not answer\./).waitFor();
    assert.equal(api.state.created, 1, "the lost answer's request was made");
    api.state.lose.clear();
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    await banner(page).waitFor();
    const sent = posts().filter((c) => c.query.dryRun !== "true");
    assert.ok(sent.length >= 3, `the failure, the lost answer and the retry (${sent.length} calls)`);
    assert.match(sent[0].key, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/, "a random UUID");
    assert.deepEqual(sent.map((c) => c.key), sent.map(() => sent[0].key), "one key for the form, sent again on each retry");
    assert.equal(api.state.created, 1, "the API made one request");
    const made = api.state.items[0];
    assert.equal(new URL(page.url()).hash, `#workflow?request=${made.requestId}`, "the Workflow tab follows the new request");
    assert.match(await banner(page).innerText(), new RegExp(`${made.requestId} is at step 1 of 1: plan_auto_approved\\.`));

    // A new opening of the form is a new action: it has its own key.
    await page.getByRole("tab", { name: "New namespace" }).click();
    await fillForm(page, { team: "ledger" });
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    await callout.waitFor();
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    await banner(page).waitFor();
    const last = posts().at(-1);
    assert.notEqual(last.key, sent[0].key, "a new form, a new key");
    assert.equal(last.body.namespace, "ledger-dev");
    assert.equal(api.state.created, 2);
    // The lost answer is the one console error that this check causes on purpose.
    assert.deepEqual(errors.filter((e) => !/net::ERR_EMPTY_RESPONSE \(http:\/\/127\.0\.0\.1:\d+\/api\/v1\/clusters\/CRC\/namespaces\)$/.test(e)), []);
    await context.close();
  });

  await check("9 New namespace refusals and states: a refused dry run, the browser's own checks, a 403, a 5xx and loading", async () => {
    {
      const { context, page, errors } = await fresh();
      expectedStatus = [422];
      await newTab(page);
      await fillForm(page);
      await page.getByLabel("Namespace name").fill("openshift-tools");
      await panel(page).getByRole("button", { name: "Dry run" }).click();
      const refused = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Refused: reserved-namespace" });
      await refused.waitFor();
      assert.match(await refused.innerText(), /openshift-tools is reserved/);
      assert.match(await refused.getAttribute("class"), /pf-m-danger/);
      // An empty Team DL, then one that is not an address: the browser refuses each, and nothing goes to the API.
      const before = posts().length;
      await page.getByLabel("Team DL (required)").fill("");
      await panel(page).getByRole("button", { name: "Submit request" }).click();
      await page.getByLabel("Team DL (required)").fill("not-an-address");
      await panel(page).getByRole("button", { name: "Submit request" }).click();
      await page.getByLabel("Expires (optional)").fill("2020-01-01");
      await page.getByLabel("Team DL (required)").fill("payments-team@ephico2real.com");
      await panel(page).getByRole("button", { name: "Submit request" }).click();
      await page.waitForTimeout(300);
      assert.equal(posts().length, before, "no submit while a field is not valid");
      assert.equal(await page.getByLabel("Team DL (required)").evaluate((el) => el.required), true);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh();
      expectedStatus = [403];
      api.state.answers.push({ route: "GET /api/v1/clusters", status: 403, body: { type: "https://cmapi.ephico2real.com/problems/forbidden", title: "forbidden", status: 403, code: "forbidden", detail: "Missing permission clusters:read: no role in your token grants it (roles: ['cmapi-requester'])" } });
      await open(page, "#new");
      await panel(page).getByRole("heading", { name: "You do not have permission to request a namespace." }).waitFor();
      assert.match(await panel(page).innerText(), /Missing permission clusters:read/);
      assert.equal(await panel(page).getByRole("button").count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh();
      expectedStatus = [500];
      api.state.delayMs = 500;
      api.state.answers.push({ route: "GET /api/v1/tiers", status: 500, body: { type: "https://cmapi.ephico2real.com/problems/internal-error", title: "internal-error", status: 500, code: "internal-error", detail: "The database did not answer." } });
      await page.goto(`${portal.page}#new`);
      await page.getByRole("status").filter({ hasText: "Loading the form…" }).waitFor();
      const alert = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The form did not load." });
      await alert.waitFor();
      assert.match(await alert.innerText(), /The database did not answer\./);
      api.state.delayMs = 0;
      await alert.getByRole("button", { name: "Try again" }).click();
      await panel(page).getByRole("button", { name: "Dry run" }).waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("R1 New namespace: a form changed after a lost answer is another request, with its own Idempotency-Key", async () => {
    const { context, page, errors } = await fresh();
    expectedStatus = [409];
    const passed = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Dry run passed · nothing written" });
    await newTab(page);
    await fillForm(page);
    await panel(page).getByRole("button", { name: "Dry run" }).click();
    await passed.waitFor();
    // The API makes the request, and its answer is lost on the way.
    api.state.lose.add("POST /api/v1/clusters/CRC/namespaces");
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    await panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Not submitted" }).getByText(/The network did not answer\./).waitFor();
    api.state.lose.clear();
    assert.equal(api.state.created, 1, "the lost answer's request was made");
    const lost = posts().filter((c) => c.query.dryRun !== "true");
    // The person changes the form, plans it again and submits it: another body, so another request (docs/04, Idempotency-Key).
    await page.getByLabel("Justification").fill("Payments and ledger dev namespace");
    await panel(page).getByRole("button", { name: "Dry run" }).click();
    await passed.waitFor();
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    const replay = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "idempotency-replay" });
    await Promise.race([banner(page).waitFor(), replay.waitFor()]);
    const last = posts().at(-1);
    assert.equal(last.body.justification, "Payments and ledger dev namespace");
    assert.ok(lost.every((c) => c.key === lost[0].key), "the lost answer's retries share one key");
    assert.notEqual(last.key, lost[0].key, "a changed body is sent with a new key, not the key of the lost request");
    assert.equal(await replay.count(), 0, "no 409 idempotency-replay");
    assert.equal(api.state.created, 2);
    await banner(page).waitFor();
    assert.deepEqual(errors.filter((e) => !/net::ERR_EMPTY_RESPONSE \(http:\/\/127\.0\.0\.1:\d+\/api\/v1\/clusters\/CRC\/namespaces\)$/.test(e)), []);
    await context.close();
  });

  await check("R2 New namespace: Submit sends only the plan that the person saw; a form not planned, or changed since its dry run, is planned first", async () => {
    const { context, page, errors } = await fresh();
    const passed = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Dry run passed · nothing written" });
    const writes = () => posts().filter((c) => c.query.dryRun !== "true");
    const dryRuns = () => posts().filter((c) => c.query.dryRun === "true");
    await newTab(page);
    await fillForm(page);
    // No dry run yet: Submit runs it and shows its plan, and writes nothing.
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    await Promise.race([passed.waitFor(), banner(page).waitFor()]);
    assert.equal(writes().length, 0, "no submit of a form that was never planned");
    await passed.waitFor();
    // A change after the dry run: the next Submit plans the new form first.
    await panel(page).getByRole("group", { name: "Tier" }).getByRole("button", { name: /^small/ }).click();
    assert.equal(await passed.count(), 0, "the plan is of the old form");
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    await Promise.race([passed.waitFor(), banner(page).waitFor()]);
    assert.equal(writes().length, 0, "no submit of a plan that the person did not see");
    assert.equal(dryRuns().at(-1).body.tier, "small", "the new form was planned");
    // The plan on the page is of the form: Submit sends exactly the body that was planned.
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    await banner(page).waitFor();
    assert.equal(writes().length, 1);
    assert.deepEqual(writes()[0].body, dryRuns().at(-1).body, "the submitted body is the dry run's");
    assert.deepEqual(errors, []);
    await context.close();
  });

  // #336: the labels and annotations of the form come from GET /api/v1/metadata-keys, the instance's own metadata-keys.yaml.
  // Each expectation is written from the API's answer and the validator's words, not from the page's code.
  const section = (page, title) => panel(page).locator(".pf-v6-c-form__section").filter({ has: page.locator(".pf-v6-c-form__section-title", { hasText: new RegExp(`^${title}$`) }) });
  const labelsOf = (where) => where.locator("label.pf-v6-c-form__label").evaluateAll((ls) => ls.map((l) => l.textContent.trim()));
  /** The error under a field, read through its aria-describedby, as a screen reader finds it; null when it has none. */
  const errorOf = async (input) => {
    const id = (await input.getAttribute("aria-describedby") ?? "").split(" ").find((x) => x.endsWith("-error"));
    return id ? (await input.page().locator(`#${id}`).textContent()).trim() : null;
  };
  async function waitError(input, want) {
    for (let i = 0; i < 40; i++) {
      const text = await errorOf(input);
      if (want === null ? text === null : text !== null && want.test(text)) return text;
      await input.page().waitForTimeout(100);
    }
    assert.fail(`the field's error is ${JSON.stringify(await errorOf(input))}, not ${want}`);
  }
  const dryRuns = () => posts().filter((c) => c.query.dryRun === "true");
  const passed = (page) => panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Dry run passed · nothing written" });
  const refusedWith = (errors) => ({ route: "POST /api/v1/clusters/CRC/namespaces", status: 422, body: { ...SAMPLES.problems["policy-violation"].response.body, errors } });

  await check("OB3-368 New namespace: no field is in error before the person tries the form; an empty required field is, after a Dry run", async () => {
    // WAI-ARIA 1.2, aria-invalid: not on a required widget only because nothing was entered before the user tried to submit.
    for (const metadataKeys of [REFERENCE_KEYS, COMPANY_KEYS]) {
      const { context, page, errors } = await fresh({ metadataKeys });
      try {
        await newTab(page);
        await page.waitForTimeout(600);
        assert.deepEqual(await panel(page).locator("[aria-invalid=true]").count(), 0, "no field is invalid before the person tries the form");
        assert.deepEqual(await panel(page).locator("[id$=-error]").count(), 0, "and no error text");
        const first = page.locator("#ns-label-0");
        const before = posts().length;
        await panel(page).getByRole("button", { name: "Dry run" }).click();
        await waitError(first, /^Required: /);
        assert.equal(await first.getAttribute("aria-invalid"), "true");
        assert.equal(posts().length, before, "nothing is planned");
        assert.deepEqual(errors, []);
      } finally { await context.close(); }
    }
  });

  await check("18 New namespace on a company instance: the fields of GET /api/v1/metadata-keys, the keys cmapi sets read-only, refusals in the browser, and the body", async () => {
    const { context, page, errors } = await fresh({ metadataKeys: COMPANY_KEYS });
    try {
      await newTab(page);
      assert.deepEqual(await labelsOf(section(page, "Labels")), ["company.net/mnemonic (required)", "company.net/lob (required)", "company.net/cl (required)", "name", "company.net/app-environment"]);
      assert.deepEqual(await labelsOf(section(page, "Annotations")), ["company.net/app-environment", "company.net/mnemonic-group-contact (optional)", "company.net/mnemonic-confluence (optional)"]);
      assert.doesNotMatch(await panel(page).evaluate((el) => el.textContent), /cmapi\.net\/protected|cmapi\.net\/team|Team DL/, "no operator-only key, and none of the reference file's");
      const mnemonic = page.getByLabel("company.net/mnemonic (required)"), lob = page.getByLabel("company.net/lob (required)"), cl = page.getByLabel("company.net/cl (required)");
      assert.equal(await mnemonic.inputValue(), "", "an example is a placeholder, never a value");
      assert.equal(await mnemonic.getAttribute("placeholder"), "abc");
      assert.deepEqual(await Promise.all([mnemonic, lob, cl].map((f) => f.evaluate((el) => el.required))), [true, true, true]);
      assert.deepEqual(await cl.locator("option").allInnerTexts(), ["—", "0", "1", "2", "3", "4", "5", "6"]);
      const name = section(page, "Labels").getByLabel("name", { exact: true }), labelEnv = section(page, "Labels").getByLabel("company.net/app-environment", { exact: true });
      const annotationEnv = section(page, "Annotations").getByLabel("company.net/app-environment", { exact: true });
      assert.deepEqual(await Promise.all([name, labelEnv, annotationEnv].map((f) => f.evaluate((el) => [el.readOnly, el.disabled]))), [[true, false], [true, false], [true, false]],
        "read-only, not disabled: read by a screen reader, never sent");
      assert.equal(await annotationEnv.inputValue(), "dev", "the environment that cmapi writes");

      // A value that cmapi refuses is refused in the browser, in the validator's words, and nothing goes to the API.
      await mnemonic.fill("ABC");
      await lob.fill("amg sst");
      await cl.selectOption("1");
      await waitError(mnemonic, /^Not valid: must match \^\[a-z\]\{3,4\}\$; the start of the namespace name, before its first '-'/);
      await waitError(lob, /^Not a valid label value/);
      assert.equal(await mnemonic.getAttribute("aria-invalid"), "true");
      assert.equal(await name.inputValue(), "ABC-dev", "the name that cmapi copies follows the namespace");
      const before = posts().length;
      await panel(page).getByRole("button", { name: "Dry run" }).click();
      await panel(page).getByRole("button", { name: "Submit request" }).click();
      await page.waitForTimeout(500);
      assert.equal(posts().length, before, "nothing is planned or sent while a field is refused");

      // The mnemonic starts the namespace name (namespacePrefix): the suggested name follows it, and another name is refused.
      await mnemonic.fill("abc");
      await lob.fill("amgsst");
      await waitError(mnemonic, null);
      assert.equal(await page.getByLabel("Namespace name").inputValue(), "abc-dev");
      await page.getByLabel("Namespace name").fill("xyz-dev");
      await waitError(mnemonic, /^xyz-dev does not start with abc-/);
      await panel(page).getByRole("button", { name: "Dry run" }).click();
      await page.waitForTimeout(500);
      assert.equal(posts().length, before, "a name that the mnemonic does not start is not planned");
      await page.getByLabel("Namespace name").fill("");
      assert.equal(await page.getByLabel("Namespace name").inputValue(), "abc-dev", "an empty name is the suggestion again");

      // An optional URL that cmapi accepts and <input type=url> refuses (#336, design B): text with the URL keyboard.
      await panel(page).getByRole("button", { name: "Optional annotations (2)" }).click();
      const wiki = page.getByLabel("company.net/mnemonic-confluence (optional)");
      assert.deepEqual([await wiki.getAttribute("type"), await wiki.getAttribute("inputmode")], ["text", "url"]);
      assert.equal(await page.getByLabel("company.net/mnemonic-group-contact (optional)").getAttribute("type"), "email");
      await wiki.fill("https://wiki.company.net:abc/x");
      await page.getByLabel("Justification").fill("ABC rnd namespace");
      await panel(page).getByRole("button", { name: "Dry run" }).click();
      await passed(page).waitFor();
      assert.deepEqual(dryRuns().at(-1).body, { namespace: "abc-dev", tier: "medium",
        labels: { "company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1" },
        annotations: { "company.net/mnemonic-confluence": "https://wiki.company.net:abc/x" }, justification: "ABC rnd namespace" },
        "the requester's keys only: no key that cmapi sets, no empty optional key");
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  await check("18 New namespace on the reference instance: Team and Team DL from GET /api/v1/metadata-keys with the mockup's words, the optional labels, and a revalidated read", async () => {
    const { context, page, errors } = await fresh();
    try {
      await newTab(page);
      const labels = REFERENCE_KEYS.labels;
      const optional = Object.keys(labels.properties).filter((k) => !labels.required.includes(k) && !labels.properties[k]["x-cmapi-operator-only"]);
      assert.deepEqual(await labelsOf(section(page, "Labels")), ["Team (required)", ...optional.map((k) => `${k} (optional)`)]);
      assert.deepEqual(await labelsOf(section(page, "Annotations")), ["Team DL (required)"]);
      assert.equal(optional.length, 3);
      assert.equal(await panel(page).getByRole("button", { name: "Optional labels (3)" }).getAttribute("aria-expanded"), "false", "the optional keys wait in a collapsed group");
      const team = page.getByLabel("Team (required)");
      assert.deepEqual([await team.inputValue(), await team.getAttribute("placeholder")], ["", "payments"]);
      const help = await team.getAttribute("aria-describedby");
      assert.match((await page.locator(`#${help}`).textContent()).replace(/\s+/g, " "),
        /^cmapi\.net\/team Who owns it, for cost and notices: any team name\. Not checked against who you are; your Keycloak roles decide what you may do\. Must match \^\[a-z0-9-\]\{2,40\}\$\.$/,
        "the key, then the config's words: the mockup's hint, from the instance's file");
      // The answer has a strong ETag and private, no-cache: the next opening of the tab revalidates it.
      const first = calls("/api/v1/metadata-keys");
      assert.equal(first.length, 1);
      assert.equal(first[0].ifNoneMatch, null);
      await page.getByRole("tab", { name: "Requests" }).click();
      await page.getByRole("tab", { name: "New namespace" }).click();
      await panel(page).getByRole("button", { name: "Dry run" }).waitFor();
      await page.waitForFunction(() => true);
      for (let i = 0; i < 30 && calls("/api/v1/metadata-keys").length < 2; i++) await page.waitForTimeout(100);
      assert.match(calls("/api/v1/metadata-keys")[1]?.ifNoneMatch ?? "none", /^"[0-9a-f]{32}"$/, "the browser asks with the tag it holds, and the API answers 304");
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  await check("18 New namespace: a refused dry run's errors on their fields, the others in a summary that takes the focus; a key the form lacks reads the rules again", async () => {
    const { context, page, errors } = await fresh();
    expectedStatus = [422];
    try {
      await newTab(page);
      await fillForm(page);
      api.state.answers.push(refusedWith([{ code: "invalid_value", key: "cmapi.net/team", detail: "must match ^[a-z0-9-]{2,40}$" }, { code: "reserved_key", key: "cmapi.net/x" },
        { code: "missing_required_key", key: "cmapi.net/owner", kind: "label", detail: "must match ^[a-z]+$" }]));
      const reads = calls("/api/v1/metadata-keys").length;
      await panel(page).getByRole("button", { name: "Dry run" }).click();
      const refused = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Refused: policy-violation" });
      await refused.waitFor();
      const team = page.getByLabel("Team (required)");
      await waitError(team, /^must match \^\[a-z0-9-\]\{2,40\}\$/);
      assert.equal(await team.getAttribute("aria-invalid"), "true");
      assert.deepEqual((await refused.locator("li").allInnerTexts()).map((t) => t.trim()),
        ["cmapi.net/team: must match ^[a-z0-9-]{2,40}$", "cmapi.net/x: reserved_key", "cmapi.net/owner: must match ^[a-z]+$"]);
      assert.ok(await page.evaluate(() => Boolean(document.activeElement?.querySelector?.(".pf-v6-c-alert.pf-m-danger"))), "the summary has the focus");
      for (let i = 0; i < 30 && calls("/api/v1/metadata-keys").length === reads; i++) await page.waitForTimeout(100);
      assert.equal(calls("/api/v1/metadata-keys").length, reads + 1, "a missing key that the form does not show: the rules are read again");
      await refused.getByRole("button", { name: "cmapi.net/team: must match ^[a-z0-9-]{2,40}$" }).click();
      await page.waitForFunction(() => document.activeElement?.getAttribute("aria-describedby")?.includes("-error"));
      assert.equal(await team.evaluate((el) => el === document.activeElement), true, "the summary's link moves the focus to its field");
      // An edit is another form: the refusal and its field errors are of the old one.
      await team.fill("payments2");
      await waitError(team, null);
      assert.equal(await refused.count(), 0);
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  await check("18 New namespace: a configured pattern that backtracks is not checked here; the page stays responsive and the dry run decides", async () => {
    // main's loader accepts this pattern (#336, design B, redos-loader.log); V8 needs 944 ms for 26 characters, four times as long for each two more.
    const slow = "^(?:[a-z0-9]+-?)*[a-z0-9]$";
    const keys = structuredClone(REFERENCE_KEYS);
    Object.assign(keys.labels.properties["cmapi.net/team"], { pattern: `^(?:${slow})$`, "x-cmapi-rule": `must match ${slow}`, description: `Must match ${slow}.` });
    const { context, page, errors } = await fresh({ metadataKeys: keys });
    expectedStatus = [422];
    try {
      await newTab(page);
      await page.getByLabel("Team DL (required)").fill("payments-team@ephico2real.com");
      // A label value that the pattern almost matches: it backtracks on it for far longer than this suite runs.
      const value = `${"a".repeat(40)}A`;
      await page.getByLabel("Team (required)").fill(value);
      await page.waitForTimeout(300);
      const started = Date.now();
      assert.equal(await Promise.race([page.evaluate(() => 1), new Promise((resolve) => setTimeout(() => resolve("no answer"), 1000))]), 1, "the page answers");
      await page.getByLabel("Justification").pressSequentially("ok", { timeout: 1000 });
      assert.equal(await page.getByLabel("Justification").inputValue(), "ok", "a field takes keys while the pattern runs");
      assert.ok(Date.now() - started < 2000, `answered in ${Date.now() - started} ms`);
      await page.waitForTimeout(400);
      assert.equal(await errorOf(page.getByLabel("Team (required)")), null, "not checked here: no error, cmapi decides");
      api.state.answers.push(refusedWith([{ code: "invalid_value", key: "cmapi.net/team", detail: `must match ${slow}` }]));
      await panel(page).getByRole("button", { name: "Dry run" }).click();
      await panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Refused: policy-violation" }).waitFor();
      await waitError(page.getByLabel("Team (required)"), new RegExp(`^must match ${slow.replace(/[\\^$.*+?()[\]{}|]/g, "\\$&")}`));
      assert.equal(dryRuns().at(-1).body.labels["cmapi.net/team"], value);
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  await check("18 New namespace: rules that change while the form is open; the fields follow them, a removed key is not sent, and a warning says so", async () => {
    const { context, page, errors } = await fresh();
    try {
      await newTab(page);
      await fillForm(page);
      const changed = structuredClone(REFERENCE_KEYS);
      delete changed.annotations.properties["cmapi.net/team-dl"];
      delete changed.annotations.required;
      changed.labels.properties["cmapi.net/owner"] = { type: "string", pattern: "^(?:^[a-z]+$)$", maxLength: 63, minLength: 1, description: "The owning group. Must match ^[a-z]+$.",
        "x-cmapi-rule": "must match ^[a-z]+$", examples: ["platform"] };
      changed.labels.required = [...changed.labels.required, "cmapi.net/owner"];
      api.state.metadataKeys = changed;
      // The window has the focus again: TanStack Query reads the rules again (useMetadataKeys, refetchOnWindowFocus).
      await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")));
      await panel(page).getByText("The label and annotation rules of this instance changed. Check the fields below.").waitFor();
      assert.equal(await page.getByLabel("Team DL (required)").count(), 0, "the removed key's field is gone");
      assert.equal(await page.getByLabel("Team (required)").inputValue(), "payments", "a key that remains keeps its value");
      const owner = page.getByLabel("cmapi.net/owner (required)");
      assert.deepEqual([await owner.inputValue(), await owner.evaluate((el) => el.required)], ["", true], "a new required key is empty and required");
      const before = posts().length;
      await panel(page).getByRole("button", { name: "Dry run" }).click();
      await page.waitForTimeout(400);
      assert.equal(posts().length, before, "the browser stops on the new required key");
      await owner.fill("platform");
      await panel(page).getByRole("button", { name: "Dry run" }).click();
      await passed(page).waitFor();
      const sent = dryRuns().at(-1).body;
      assert.deepEqual([sent.labels, sent.annotations], [{ "cmapi.net/team": "payments", "cmapi.net/owner": "platform" }, {}], "the removed key's value is not sent");
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  await check("18 New namespace states with the rules: a 403, a 5xx with Try again, an answer of another shape, and a role limited to rnd", async () => {
    {
      const { context, page, errors } = await fresh();
      expectedStatus = [403];
      api.state.answers.push({ route: "GET /api/v1/metadata-keys", status: 403, body: { ...SAMPLES.problems.forbidden.response.body, detail: "Missing permission objects:read: no role in your token grants it (roles: ['cmapi-approval-relay'])" } });
      await open(page, "#new");
      await panel(page).getByRole("heading", { name: "You do not have permission to request a namespace." }).waitFor();
      assert.match(await panel(page).innerText(), /Missing permission objects:read/);
      assert.equal(await panel(page).getByRole("button").count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh();
      expectedStatus = [500];
      api.state.answers.push({ route: "GET /api/v1/metadata-keys", status: 500, body: { type: "https://cmapi.ephico2real.com/problems/internal-error", title: "internal-error", status: 500, code: "internal-error", detail: "The rules did not load." } });
      await open(page, "#new");
      const alert = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The form did not load." });
      await alert.waitFor();
      assert.match(await alert.innerText(), /The rules did not load\./);
      await alert.getByRole("button", { name: "Try again" }).click();
      await page.getByLabel("Team (required)").waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ metadataKeys: { labels: [], annotations: {} } });
      await open(page, "#new");
      const alert = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The form did not load." });
      await alert.waitFor();
      assert.match(await alert.innerText(), /The metadata rules of this instance are not in the form this portal reads/);
      assert.equal(await panel(page).getByRole("button", { name: "Dry run" }).count(), 0, "never a form with fields missing");
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // A role limited to rnd reads the rules: they are the instance's, the same for every caller (objects:read in any environment).
      const { context, page, errors } = await fresh({ user: "rndRequester" });
      await newTab(page);
      assert.equal(await page.getByLabel("Team (required)").count(), 1);
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  const ola = SAMPLES.operations.requests_list_requests.response.body.items[0];
  const second = { ...ola, requestId: "req-20261115-2002", namespace: "ledger-dev" };
  const cardOf = (page, id) => panel(page).locator(".pf-v6-l-grid").filter({ has: page.getByRole("heading", { name: new RegExp(`^${id} ·`) }) });

  await check("10 Approvals: the requests waiting for me; Approve records one approval; Reject needs a reason; Open at current step", async () => {
    const { context, page, errors } = await fresh({ user: "approver", items: [ola, second] });
    await open(page, "#approvals");
    await cardOf(page, ola.requestId).waitFor();
    assert.deepEqual(calls("/api/v1/requests")[0].query, { status: "pending_approval", approver: "me", limit: "25" }, "the pending requests that need my groups");
    const head = () => panel(page).locator(".pf-v6-c-label").first().innerText();
    assert.equal(await head(), "2 waiting for you");
    const card = cardOf(page, ola.requestId);
    const text = (await card.innerText()).replace(/\s+/g, " ");
    assert.ok(text.startsWith(`0 of 1 approvals ${ola.requestId} · ${ola.namespace} on ${ola.clusterId} update · requested by ola@ephico2real.com · `), text);
    assert.match(text, new RegExp(`Why it needs approval ${ola.approval.reasons.join(" ").replace(/[+()>]/g, "\\$&")}`));
    assert.match(text, /Your eligibility ✓ Role cmapi-approver Keycloak token ✓ Not the requester requested by ola Approvals so far Required 1 from approver-platform So far none/);

    await card.getByRole("button", { name: "Approve" }).click();
    const done = card.locator(".pf-v6-c-alert").filter({ hasText: "Approved · 1 of 1" });
    await done.waitFor();
    assert.match(await done.innerText(), /The request is approved\. The worker opens the bot PR now; it merges when CI and the cmapi check pass, and Argo CD applies it\./);
    assert.match(await card.locator(".pf-v6-c-label").first().getAttribute("class"), /pf-m-success/);
    assert.equal(await card.locator(".pf-v6-c-label").first().innerText(), "1 of 1 approvals");
    assert.equal(await card.getByRole("button", { name: "Approve" }).count(), 0, "a decided request has no more actions");
    assert.equal(await head(), "1 waiting for you");
    assert.deepEqual(api.state.seen.filter((c) => c.method === "POST").map((c) => c.path), [`/api/v1/requests/${ola.requestId}:approve`]);

    const other = cardOf(page, second.requestId);
    await other.getByRole("button", { name: "Reject" }).click();
    const reason = other.getByLabel("Why are you rejecting it? (required, sent to the requester)");
    await reason.waitFor();
    assert.match(await other.innerText(), /A reason is required before the request can be rejected\./);
    await other.getByRole("button", { name: "Confirm reject" }).click();
    assert.equal(api.state.seen.filter((c) => c.path.endsWith(":reject")).length, 0, "no reason, no call");
    await reason.fill("Use the medium tier");
    await other.getByRole("button", { name: "Confirm reject" }).click();
    const rejected = other.locator(".pf-v6-c-alert").filter({ hasText: "Rejected" });
    await rejected.waitFor();
    assert.match(await rejected.innerText(), /The requester sees your reason: “Use the medium tier”\. Nothing was written to Git, and any reservation is released\./);
    assert.deepEqual(api.state.seen.filter((c) => c.path.endsWith(":reject")).map((c) => c.body), [{ comment: "Use the medium tier" }]);
    assert.equal(await head(), "nothing waiting for you");

    await other.getByRole("button", { name: "Open at current step" }).click();
    await banner(page).waitFor();
    assert.equal(new URL(page.url()).hash, `#workflow?request=${second.requestId}`);
    assert.match(await banner(page).innerText(), new RegExp(`${second.requestId} finished at step 2 of 2: rejected\\.`));
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("10 Approvals: the API refuses a self-approval and the page shows it; empty, 403 and 5xx", async () => {
    {
      // The requester, here with the approver role, approves their own request where the rule allows no self-approval.
      USERS.owner = { ...USERS.requester, role: "cmapi-approver", groups: USERS.approver.groups };
      const own = { ...ola, approval: { ...ola.approval, selfApproval: false } };
      const { context, page, errors } = await fresh({ user: "owner", items: [own] });
      expectedStatus = [409];
      await open(page, "#approvals");
      const card = cardOf(page, own.requestId);
      await card.waitFor();
      assert.match((await card.innerText()).replace(/\s+/g, " "), /✕ Not the requester you opened this request/);
      await card.getByRole("button", { name: "Approve" }).click();
      const refused = card.locator(".pf-v6-c-alert").filter({ hasText: "Refused: self-approval" });
      await refused.waitFor();
      assert.match(await refused.innerText(), /Requesters cannot approve their own request here/);
      assert.equal(api.state.items[0].status, "pending_approval", "nothing was recorded");
      assert.equal(await card.getByRole("button", { name: "Approve" }).count(), 1, "the request still waits");
      assert.deepEqual(errors, []);
      await context.close();
      delete USERS.owner;
    }
    {
      const { context, page, errors } = await fresh({ user: "approver", items: [] });
      await open(page, "#approvals");
      await panel(page).getByRole("heading", { name: "Nothing waiting for you" }).waitFor();
      assert.match(await panel(page).innerText(), /Small and medium rnd and dev namespaces are auto-approved by baseline-rnd-namespace, and expired namespaces by expired-namespace\. Anything else waits here\./);
      assert.equal(await panel(page).locator(".pf-v6-c-label").first().innerText(), "nothing waiting for you");
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ user: "approver", mode: "forbidden" });
      expectedStatus = [403];
      await open(page, "#approvals");
      await panel(page).getByRole("heading", { name: "You do not have permission to see approvals." }).waitFor();
      assert.equal(await panel(page).getByRole("button").count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ user: "approver", mode: "error500", items: [ola] });
      expectedStatus = [500];
      await open(page, "#approvals");
      const alert = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The approvals did not load." });
      await alert.waitFor();
      api.state.mode = "ok";
      await alert.getByRole("button", { name: "Try again" }).click();
      await cardOf(page, ola.requestId).waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("R3 a double click on Submit, Approve or Confirm reject sends one write", async () => {
    const counts = {};
    {
      const { context, page, errors } = await fresh();
      await newTab(page);
      await fillForm(page);
      await panel(page).getByRole("button", { name: "Dry run" }).click();
      await panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Dry run passed · nothing written" }).waitFor();
      api.state.delayMs = 300;
      await panel(page).getByRole("button", { name: "Submit request" }).dblclick();
      await banner(page).waitFor();
      counts.submit = posts().filter((c) => c.query.dryRun !== "true").length;
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ user: "approver", items: [ola, second] });
      expectedStatus = [409];
      await open(page, "#approvals");
      const card = cardOf(page, ola.requestId);
      await card.waitFor();
      api.state.delayMs = 300;
      await card.getByRole("button", { name: "Approve" }).dblclick();
      await card.locator(".pf-v6-c-alert").filter({ hasText: "Approved · 1 of 1" }).waitFor();
      await page.waitForTimeout(800);
      counts.approve = api.state.seen.filter((c) => c.path.endsWith(":approve")).length;
      counts.approveRefusalShown = await card.locator(".pf-v6-c-alert").filter({ hasText: "Refused" }).count();
      const other = cardOf(page, second.requestId);
      await other.getByRole("button", { name: "Reject" }).click();
      await other.getByLabel("Why are you rejecting it? (required, sent to the requester)").fill("Use the medium tier");
      await other.getByRole("button", { name: "Confirm reject" }).dblclick();
      await other.locator(".pf-v6-c-alert").filter({ hasText: "Rejected" }).first().waitFor();
      await page.waitForTimeout(800);
      counts.reject = api.state.seen.filter((c) => c.path.endsWith(":reject")).length;
      counts.rejectRefusalShown = await other.locator(".pf-v6-c-alert").filter({ hasText: "Refused" }).count();
      assert.deepEqual(errors, []);
      await context.close();
    }
    console.log(`  writes on a double click: ${JSON.stringify(counts)}`);
    assert.deepEqual(counts, { submit: 1, approve: 1, approveRefusalShown: 0, reject: 1, rejectRefusalShown: 0 }, "one write for each double click, and no refusal of the second beside the decision");
  });

  await check("R4 Approvals: the eligibility's requester check compares the sub, as the API does (docs/14), not the username", async () => {
    // The requester of the recorded request (sub-ola, "ola") signs in after a rename in Keycloak: a new username, the same sub.
    USERS.renamed = { ...USERS.requester, username: "ola.renamed", role: "cmapi-approver", groups: USERS.approver.groups };
    const own = { ...ola, approval: { ...ola.approval, selfApproval: false } };
    const { context, page, errors } = await fresh({ user: "renamed", items: [own] });
    expectedStatus = [409];
    try {
      await open(page, "#approvals");
      const card = cardOf(page, own.requestId);
      await card.waitFor();
      assert.match((await card.innerText()).replace(/\s+/g, " "), /✕ Not the requester you opened this request/, "the same sub is the requester, whatever the username");
      await card.getByRole("button", { name: "Approve" }).click();
      await card.locator(".pf-v6-c-alert").filter({ hasText: "Refused: self-approval" }).waitFor();
      assert.deepEqual(errors, []);
    } finally {
      await context.close();
      delete USERS.renamed;
    }
  });

  // The text of one tab's block of the mockup: each tag out, each {{hole}} a break, and its placeholders and aria-labels.
  const mockupBlock = (from, to) => {
    const mockup = readFileSync(join(app, "..", "mockups", "portal", "Main.dc.html"), "utf8");
    const block = mockup.slice(mockup.indexOf(`<sc-if value="{{${from}}}"`), mockup.indexOf(`<sc-if value="{{${to}}}"`));
    const attrs = [...block.matchAll(/(?:placeholder|aria-label)="([^"{]+)"/g)].map((m) => m[1]);
    const texts = block.replace(/<[^>]+>/g, "\n").split(/\n|\{\{[^}]+\}\}/).map((t) => t.replace(/\s+/g, " ").trim()).filter(Boolean);
    return [...new Set([...texts, ...attrs])];
  };
  const shownText = (page) => panel(page).evaluate((root) => {
    const found = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) if (walker.currentNode.nodeValue.trim()) found.push(walker.currentNode.nodeValue.replace(/\s+/g, " ").trim());
    root.querySelectorAll("[placeholder]").forEach((el) => found.push(el.getAttribute("placeholder")));
    root.querySelectorAll("[aria-label]").forEach((el) => found.push(el.getAttribute("aria-label")));
    root.querySelectorAll("input, textarea, select").forEach((el) => el.value && found.push(el.value));
    return found;
  });
  /** Both directions: each string of the mockup's block is shown (but those listed as mockup only), and each string shown is known. */
  function compare(tab, fromMockup, shown, known, patterns = []) {
    const squeeze = (text) => text.replace(/\s+/g, "");
    const all = squeeze(shown.join(" "));
    assert.deepEqual(fromMockup.filter((text) => !all.includes(squeeze(text))), [], `${tab}: each string of the mockup's tab is on the page`);
    const sorted = [...fromMockup, ...known].sort((x, y) => y.length - x.length);
    // A text that a pattern of the mockup's logic (or of the listed additions) matches whole is known.
    const invented = [...new Set(shown.filter((text) => !patterns.some((re) => re.test(text))).filter((text) => sorted.reduce((rest, k) => rest.split(k).join(""), text).replace(/[\s·→:;,.()]/g, "") !== ""))];
    assert.deepEqual(invented, [], `${tab}: no string that the mockup does not have`);
    return fromMockup.length;
  }
  // The approval cell in the mockup's form: "auto: <policy>", or "<rule> · <have> of <need>".
  const approvalOf = (r) => {
    if (r.approval.auto) return `auto: ${r.approval.auto.replace(/^auto:/, "")}`;
    const need = r.approval.slots.reduce((n, x) => n + x.count, 0), left = r.approval.remaining.reduce((n, x) => n + x.needed, 0);
    return `${r.approval.rule} · ${need - left} of ${need}`;
  };
  // PatternFly's own words for a screen reader.
  const LIBRARY = ["Info alert:", "Success alert:", "Danger alert:", "Warning alert:", "Reset", "Loading..."];

  await check("6 the Workflow, New namespace and Approvals tabs say what the mockup says, and add only what is listed", async () => {
    const counts = {};
    {
      // Workflow: the open request (applied) and the finished one (synced, with its PR), each at its current position and one step back.
      const done = { ...synced, requestId: "req-20261115-1003", namespace: "orders-dev" };
      const none = requestWith(synced, { requestId: "req-20261115-1004", namespace: "search-dev", status: "pending_approval", events: [], pr: null, mergeSha: null });
      const { context, page, errors } = await fresh({ items: [applied, done, none] });
      await open(page, `#workflow?request=${applied.requestId}`);
      await banner(page).waitFor();
      const shown = await shownText(page);
      await panel(page).getByRole("button", { name: "Back", exact: true }).click();
      shown.push(...await shownText(page));
      await panel(page).getByRole("group", { name: "Scenarios" }).getByRole("button", { name: new RegExp(done.requestId) }).click();
      await page.waitForFunction((id) => document.querySelector("[role=tabpanel]")?.innerText.includes(`${id} finished`), done.requestId);
      shown.push(...await shownText(page));
      await panel(page).getByRole("group", { name: "Scenarios" }).getByRole("button", { name: new RegExp(none.requestId) }).click();
      await panel(page).getByText("No events yet.").first().waitFor();
      shown.push(...await shownText(page));
      // The mockup's panels that the API has no data for, and its scenario playback words (MOCKUP-CONTRACT.md, "Workflow").
      const MOCKUP_ONLY = ["Capacity · cmapi-capacity", "Argo CD ·", "Not reached. The live objects below are unchanged.", "Wave", "Kind", "Name", "Applied by",
        "Status", "Detail", "Systems involved", "+", "−"];
      const fromMockup = mockupBlock("isWorkflow", "isNew").filter((t) => !MOCKUP_ONLY.includes(t));
      const data = [...[applied, done, none].flatMap((r) => [r.requestId, r.namespace, r.clusterId, r.instance, r.action, r.status, approvalOf(r)]),
        ...synced.events.flatMap((e) => [e.event, e.by, e.note, e.status, clock(e.at)]), `#${synced.pr.number}`, `${synced.pr.branch} → main`, ...Object.entries(synced.files).flat(),
        "merged", "open", "none", "applied", "synced", "pr_open", "approved"];
      // The mockup's words that its logic builds (Main.dc.html, workflow()): "Step N of M · lane", "N / M", the banner, Play.
      const FROM_LOGIC = [/^Step \d+ of \d+ · /, /^\d+ \/ \d+$/, /^req-\d{8}-\d{4} (is|finished) at step \d+ of \d+: /, /^\d+$/, /^\d+ min \d+ s$|^\d+ s$/];
      // The same logic's fixed words: its request card (reqHead, reqRows), its PR message and its play label.
      const LOGIC = ["No pull request yet. The worker opens one after the plan and approval are settled.", "Change request", "ID", "Instance", "Cluster", "Namespace",
        "Action", "Approval", "Pull request", "Lead time", "Play", "Pause", "—"];
      counts.workflow = compare("Workflow", fromMockup, shown, [...data, ...LOGIC, ...LIBRARY], FROM_LOGIC);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // New namespace: the form with the mockup's own values typed in, then its dry run, then an expiry date; then a prod instance.
      const { context, page, errors } = await fresh();
      const shown = [];
      try {
        await newTab(page);
        await page.getByLabel("Team (required)").fill("payments");
        await page.getByLabel("Team DL (required)").fill("payments-team@ephico2real.com");
        await page.getByLabel("Justification").fill("Payments service namespace for the settlement API.");
        shown.push(...await shownText(page));
        await panel(page).getByRole("button", { name: "Dry run" }).click();
        await panel(page).getByText("Dry run passed · nothing written").waitFor();
        shown.push(...await shownText(page));
        await page.getByLabel("Expires (optional)").fill(new Date(Date.now() + 20 * 864e5).toISOString().slice(0, 10));
        shown.push(...await shownText(page));
        // The same portal for a prod instance: prod namespaces never expire.
        CONFIG.environments = ["prod"];
        api.state.clusters = [{ ...api.state.clusters[0], clusterId: "PROD_A", environment: "prod" }];
        api.state.tiers = { ...api.state.tiers, environments: { prod: api.state.tiers.environments.dev } };
        await page.reload();
        await panel(page).getByRole("button", { name: "Dry run" }).waitFor();
        shown.push(...await shownText(page));
      } finally {
        CONFIG.environments = ["rnd", "dev"];
      }
      const plan = SAMPLES.operations["namespaces_create_namespace:dryRun"].response.body;
      const tiers = SAMPLES.operations.tiers_tiers.response.body.environments.dev.tiers.filter((t) => !t.custom);
      const data = ["rnd", "dev", "prod", "CRC", "PROD_A", "us-central", "any", "payments", "payments-dev", "payments-prod", "payments-team@ephico2real.com", "Non-production", "rnd, dev",
        ...tiers.map((t) => t.name), ...plan.approval.reasons, "prod portal", "staging portal", "qa, uat", "connected", "fits", "fresh data", "1", /^\d{4}-\d{2}-\d{2}$/];
      // The mockup's logic builds these (Main.dc.html, renderVals(): envOpts, tierOpts, place, appr, nsExp, dry).
      const FROM_LOGIC = [/^\d+ cores · \d+Gi$/, /^\d+ cores · \d+Gi · \d+ pods$/, /^\d+ approvals? in cmapi from /, /^[a-z]+-create · \d+ of /, /^[a-z]+ in \[[a-z, ]+\]$/,
        /^Expires in \d+ days\. Notices at 14, 7 and 1 days, then a 7-day grace; extend from the Expiration tab in steps of up to 30 days\.$/, /^[A-Z][a-z]{2} \d{1,2} \(\d+ days\)$/,
        /^\d{4}-\d{2}-\d{2}, \d+ days \(limit 180\)$/, /^Requested by ola \(ola@ephico2real\.com\), from your sign-in\.$/, /^[✓!✕]$/];
      const LOGIC = ["Leave empty for a permanent namespace. At most 180 days from today; extend later from the Expiration tab.", "Self-approval is allowed in dev.", "Environment served",
        "Capacity", "fits on fresh data", "Expiry", "none: permanent", "Approval", "never (permanent)", "never (prod)", "Your team's distribution list, in one of the organisation's email domains (emailDomains); format only."];
      // The labels and annotations come from GET /api/v1/metadata-keys (#336): each field's key, its label, its words and its
      // example (the placeholder), from the API's answer. Operator-only keys are not offered.
      const rules = Object.values(REFERENCE_KEYS).flatMap((map) => Object.entries(map.properties).filter(([, p]) => !p["x-cmapi-operator-only"])
        .map(([key, p]) => [key, `${p.title ?? key} (${(map.required ?? []).includes(key) ? "required" : "optional"})`, p.description, ...(p.examples ?? [])])).flat();
      // The portal's own words, each in MOCKUP-CONTRACT.md: the cluster field until placement is on the API (#303), the approval before a dry run,
      // and the two sections of the instance's keys with the group of its optional ones (#336).
      const ADDED = ["Cluster", "The dev clusters that take writes, from GET /api/v1/clusters. Placement is not on the API yet (#303).",
        "The prod clusters that take writes, from GET /api/v1/clusters. Placement is not on the API yet (#303).",
        "The cluster is your choice until placement is on the API (#303). The dry run checks its capacity.", "Not planned yet", "Dry run asks the API which approval applies.",
        /^(dev|prod) · us-central · connected$/, /^cpu \d+% · memory \d+% · binds on (cpu|memory)$/, "clusters/CRC/namespaces/payments-dev/",
        "Labels", "Annotations", /^Optional (labels|annotations) \(\d+\)$/, ...rules];
      const strings = [...data, ...LOGIC, ...ADDED].filter((k) => typeof k === "string");
      const patterns = [...FROM_LOGIC, ...data, ...ADDED].filter((k) => k instanceof RegExp);
      const MOCKUP_ONLY = [];
      // The mockup's Team DL hint holds the requester's line; the portal shows that line once, under the annotations, and the
      // DL field's hint is the API's words for its key (MOCKUP-CONTRACT.md, "New namespace").
      const SPLIT = { "Your team's distribution list, in one of the organisation's email domains (emailDomains); format only. Requested by ola (ola@ephico2real.com), from your sign-in.":
        ["Your team's distribution list, in one of the organisation's email domains (emailDomains); format only.", "Requested by ola (ola@ephico2real.com), from your sign-in."] };
      const fromMockup = mockupBlock("isNew", "isQuotas").flatMap((t) => SPLIT[t] ?? [t]).filter((t) => !MOCKUP_ONLY.includes(t));
      assert.ok(Object.keys(SPLIT).every((t) => mockupBlock("isNew", "isQuotas").includes(t)), "the split string is the mockup's");
      counts.new = compare("New namespace", fromMockup, shown, [...strings, ...LIBRARY], patterns);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // Approvals: two requests waiting; one approved, one with its reason open, then rejected; then nothing waiting.
      const { context, page, errors } = await fresh({ user: "approver", items: [ola, second] });
      await open(page, "#approvals");
      await cardOf(page, ola.requestId).waitFor();
      const shown = await shownText(page);
      await cardOf(page, ola.requestId).getByRole("button", { name: "Approve" }).click();
      await cardOf(page, ola.requestId).locator(".pf-v6-c-alert").filter({ hasText: "Approved · 1 of 1" }).waitFor();
      await cardOf(page, second.requestId).getByRole("button", { name: "Reject" }).click();
      shown.push(...await shownText(page));
      await cardOf(page, second.requestId).getByLabel("Why are you rejecting it? (required, sent to the requester)").fill("Use the medium tier");
      await cardOf(page, second.requestId).getByRole("button", { name: "Confirm reject" }).click();
      await cardOf(page, second.requestId).locator(".pf-v6-c-alert").filter({ hasText: "Rejected" }).waitFor();
      shown.push(...await shownText(page));
      api.state.items = [];
      await page.reload();
      await panel(page).getByRole("heading", { name: "Nothing waiting for you" }).waitFor();
      shown.push(...await shownText(page));
      // The mockup's live usage and its notice channels: the API has neither. Recently decided waits for an API filter (#304).
      const MOCKUP_ONLY = ["Live usage · last 14 days", "Resource", "Now", "7d avg", "p95", "Peak", "Quota", "How approvers were told", "Recently decided"];
      const fromMockup = mockupBlock("isApprovals", "isPolicies").filter((t) => !MOCKUP_ONLY.includes(t));
      const data = [...[ola, second].flatMap((r) => [r.requestId, r.namespace, r.clusterId, ...r.approval.reasons]), USERS.approver.username];
      // The mockup's logic builds these (Main.dc.html, approvalsView()).
      const FROM_LOGIC = [/^\d+ waiting for you$/, /^\d+ of \d+ approvals$/, /^req-\d{8}-\d{4} · [a-z-]+ on [A-Z_]+$/, /^update · requested by ola@ephico2real\.com · (\d{2}:\d{2}|[A-Z][a-z]{2} \d{1,2} \d{2}:\d{2})$/,
        /^Approved · \d+ of \d+$/, /^The requester sees your reason: “Use the medium tier”\. Nothing was written to Git, and any reservation is released\.$/, /^[✓!✕]$/, /^\d+ from approver-platform$/];
      const LOGIC = ["nothing waiting for you", "The request is approved. The worker opens the bot PR now; it merges when CI and the cmapi check pass, and Argo CD applies it.", "Rejected",
        "A reason is required before the request can be rejected.", "Reject", "Confirm reject", "Role cmapi-approver", "Keycloak token", "Not the requester", "requested by ola", "Required",
        "So far", "none", "rejected", "nonprod", "Use the medium tier"];
      counts.approvals = compare("Approvals", fromMockup, shown, [...data, ...LOGIC, ...LIBRARY], FROM_LOGIC);
      assert.deepEqual(errors, []);
      await context.close();
    }
    console.log(`  strings of the mockup compared: ${JSON.stringify(counts)}`);
  });

  // The theme class starts CSS transitions of PatternFly's colours. A screenshot or an axe scan in the next statement can read a
  // colour between the light value and the dark value: main's CI failed that way with a contrast finding on "Sign out" (#221).
  // An animation with no end (a spinner) is not waited for.
  const FINITE = "(a) => a.effect?.getComputedTiming().endTime !== Infinity && a.playState !== \"finished\"";
  const running = (page) => page.evaluate(`document.getAnimations().filter(${FINITE}).length`);
  const settled = (page) => page.evaluate(`Promise.race([
    Promise.all(document.getAnimations().filter(${FINITE}).map((a) => a.finished.catch(() => undefined))),
    new Promise((_, refuse) => setTimeout(() => refuse(new Error("the theme transition did not end in 5 s")), 5000))])`).then(() => undefined);

  await check("7 layout at 390, 820 and 1440 px in each theme, and axe at phone and desktop width", async () => {
    for (const width of [390, 820, 1440]) {
      const { context, page, errors } = await fresh({ width });
      await open(page);
      await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
      for (const theme of ["light", "dark"]) {
        await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
        await settled(page);
        assert.equal(await running(page), 0, `${width} ${theme}: no colour transition still runs when the page is read`);
        const layout = await page.evaluate(() => {
          const main = document.querySelector(".pf-v6-c-page__main-container") ?? document.documentElement;
          return { doc: document.documentElement.scrollWidth - document.documentElement.clientWidth, main: main.scrollWidth - main.clientWidth, text: document.body.innerText };
        });
        assert.ok(layout.doc <= 0 && layout.main <= 0, `${width} ${theme}: no sideways scroll (${layout.doc}, ${layout.main})`);
        assert.doesNotMatch(layout.text, /\{\{|undefined|NaN|\[object/, `${width} ${theme}: no leftover placeholder`);
        assert.ok(await page.getByRole("tab", { name: "Requests" }).count(), `${width}: the tab is reachable`);
        await page.screenshot({ path: join(out, `requests-${width}-${theme}.png`), fullPage: true });
        if (width !== 820) {
          const scan = await new AxeBuilder({ page }).analyze();
          assert.deepEqual(scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.html}`), [], `axe at ${width} ${theme}`);
        }
      }
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("7 the Workflow, New namespace and Approvals tabs at 390, 820 and 1440 px in each theme, and axe at phone and desktop width", async () => {
    const VIEWS = [
      ["workflow", "requester", [applied, mergeFailed], async (page) => { await open(page, `#workflow?request=${applied.requestId}`); await banner(page).waitFor(); }],
      ["new", "requester", undefined, async (page) => {
        await newTab(page);
        await fillForm(page);
        await panel(page).getByRole("button", { name: "Dry run" }).click();
        await panel(page).getByText("Dry run passed · nothing written").waitFor();
      }],
      ["approvals", "approver", [ola, second], async (page) => {
        await open(page, "#approvals");
        // The reason field is a state that opens on a click: it is scanned too.
        await cardOf(page, second.requestId).getByRole("button", { name: "Reject" }).click();
        await cardOf(page, second.requestId).getByLabel("Why are you rejecting it? (required, sent to the requester)").waitFor();
      }],
      // The company instance's form (#336), with a value refused in the browser and the optional annotations open.
      ["new-company", "requester", undefined, async (page) => {
        await newTab(page);
        await page.getByLabel("company.net/mnemonic (required)").fill("ABC");
        await page.getByLabel("company.net/lob (required)").fill("amgsst");
        await page.getByLabel("company.net/cl (required)").selectOption("1");
        await panel(page).getByRole("button", { name: "Optional annotations (2)" }).click();
        await waitError(page.getByLabel("company.net/mnemonic (required)"), /^Not valid: /);
      }, { metadataKeys: COMPANY_KEYS }]
    ];
    let scans = 0;
    for (const [tab, user, items, reach, options = {}] of VIEWS) {
      for (const width of [390, 820, 1440]) {
        const { context, page, errors } = await fresh({ user, items, width, ...options });
        await reach(page);
        for (const theme of ["light", "dark"]) {
          await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
          // A click before the scan (Reject) starts transitions of its own, which can start after the first wait began.
          for (let round = 0; round < 5 && (round === 0 || await running(page)); round++) await settled(page);
          assert.equal(await running(page), 0, `${tab} ${width} ${theme}: no colour transition still runs when the page is read`);
          const layout = await page.evaluate(() => {
            const main = document.querySelector(".pf-v6-c-page__main-container") ?? document.documentElement;
            return { doc: document.documentElement.scrollWidth - document.documentElement.clientWidth, main: main.scrollWidth - main.clientWidth, text: document.body.innerText };
          });
          assert.ok(layout.doc <= 0 && layout.main <= 0, `${tab} ${width} ${theme}: no sideways scroll (${layout.doc}, ${layout.main})`);
          assert.doesNotMatch(layout.text, /\{\{|undefined|NaN|\[object/, `${tab} ${width} ${theme}: no leftover placeholder`);
          await page.screenshot({ path: join(out, `${tab}-${width}-${theme}.png`), fullPage: true });
          if (width !== 820) {
            const scan = await new AxeBuilder({ page }).analyze();
            scans++;
            assert.deepEqual(scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.html}`), [], `axe on ${tab} at ${width} ${theme}`);
          }
        }
        assert.deepEqual(errors, []);
        await context.close();
      }
    }
    console.log(`  ${VIEWS.length} tabs, 3 widths, 2 themes, ${scans} axe scans`);
  });

  // Portal slice 3 (#301): the Quotas and KPIs tabs. The fleet is 70 namespaces of the stand-in, in dev and rnd, with the
  // catalog's tiers for both. Each expectation is written from the mockup's forms and the API's contract, not from the page.
  const fleet = quotasFrom(70);
  const withRnd = { ...SAMPLES.operations.tiers_tiers.response.body, environments: { ...SAMPLES.operations.tiers_tiers.response.body.environments, rnd: SAMPLES.operations.tiers_tiers.response.body.environments.dev } };
  const byName = (a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : a.clusterId < b.clusterId ? -1 : a.clusterId > b.clusterId ? 1 : 0);
  const named = [...fleet].sort(byName);
  const UNIT = { m: 1e-3, Mi: 1 / 1024, Gi: 1, "": 1 };
  const num = (q) => { const [, n, u = ""] = /^([\d.]+)(m|Mi|Gi)?$/.exec(q); return Number(n) * UNIT[u]; };
  const one = (n) => String(Math.round(n * 10) / 10);
  // The mockup's row (quotaView(): list): name, cluster, env, tier, "used / hard cores", "used / hard Gi", "used / hard" pods,
  // and then the attention counts of the API that hold for the row, and the row's button.
  const expectedQuota = (r, selected = false) => [r.name, r.clusterId, r.env, r.tier, `${one(num(r.cpu[0]))} / ${one(num(r.cpu[1]))} cores`, `${one(num(r.memory[0]))} / ${one(num(r.memory[1]))} Gi`,
    `${r.pods[0]} / ${r.pods[1]}`, [r.used >= 0.8 && "near-limit", r.openRequest && "open-request", r.tierOutdated && "tier-outdated"].filter(Boolean).join(" ") || "—", selected ? "Selected" : "Manage"];
  const quotaRows = (page) => page.locator("table[aria-label=Quotas] tbody tr").evaluateAll((trs) => trs.map((tr) => [...tr.children].map((td) => td.innerText.replace(/\s+/g, " ").trim())));
  const quotaCalls = () => calls("/api/v1/quotas");
  // The tab also reads the counts of its heading and of All: the page's call is one of the calls, not always the last one.
  const sentQuery = (want, why) => assert.ok(quotaCalls().some((c) => isDeepStrictEqual(c.query, want)), `${why ?? "the page's call"}: ${JSON.stringify(want)} was not sent; the calls were ${JSON.stringify(quotaCalls().map((c) => c.query))}`);
  const openQuotas = async (page, hash = "#quotas") => {
    await open(page, hash);
    await page.locator("table[aria-label=Quotas] tbody tr").first().waitFor();
  };
  async function waitQuotaRange(page, want) {
    try {
      await page.waitForFunction((text) => document.querySelector("[role=tabpanel]")?.innerText.includes(text), want);
    } catch {
      assert.fail(`the Quotas pager never said "${want}"; the last call was ${JSON.stringify(quotaCalls().at(-1))}`);
    }
  }
  const chips = async (page, name) => (await panel(page).getByRole("group", { name }).getByRole("button").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim());
  const quotaFresh = async (options) => {
    const opened = await fresh({ quotas: fleet, ...options });
    api.state.tiers = withRnd;
    return opened;
  };

  await check("11 Quotas: the rows of GET /api/v1/quotas cell by cell; the page, the sort, the filters, the state chips, the letter jump and the search are API parameters", async () => {
    const { context, page, errors } = await quotaFresh();
    await openQuotas(page);
    assert.deepEqual(quotaCalls()[0].query, { limit: "50" }, "the first page: the mockup's 50 rows, sorted by name");
    const nearLimit = fleet.filter((r) => r.used >= 0.8).length;
    assert.match(await panel(page).innerText(), new RegExp(`70 namespaces in scope · ${nearLimit} near the limit`));
    assert.deepEqual(await quotaRows(page), named.slice(0, 50).map((r, i) => expectedQuota(r, i === 0)), "the first page, cell by cell; the first namespace is shown below");
    assert.match(await panel(page).innerText(), /1–50 of 70 · A–Z/);
    assert.deepEqual(await chips(page, "Needs attention"), ["All 70", `Near limit ≥ 80% ${nearLimit}`, `Open request ${fleet.filter((r) => r.openRequest).length}`, `Tier outdated ${fleet.filter((r) => r.tierOutdated).length}`]);
    const near = page.locator("table[aria-label=Quotas] tbody tr").first().locator("[role=progressbar]").first();
    assert.equal(await near.getAttribute("aria-valuenow"), String(Math.round(num(named[0].cpu[0]) / num(named[0].cpu[1]) * 100)), "the CPU meter's value is used over hard");

    // Cursor paging: forward to the last page and back.
    const next = page.getByRole("button", { name: "Next ›" }).first(), prev = page.getByRole("button", { name: "‹ Previous" }).first();
    assert.equal(await prev.getAttribute("aria-disabled"), "true");
    await next.click();
    await waitQuotaRange(page, "51–70 of 70 · A–Z");
    assert.ok(quotaCalls().at(-1).query.cursor, "the next page sends the API's cursor");
    assert.deepEqual((await quotaRows(page)).map((r) => r[0]), named.slice(50).map((r) => r.name));
    assert.equal(await next.getAttribute("aria-disabled"), "true", "Next is off on the last page");
    await prev.click();
    await waitQuotaRange(page, "1–50 of 70 · A–Z");

    // The page size keeps the first namespace in view: the API places a page by name (startsWith).
    await panel(page).getByRole("group", { name: "Per page" }).getByRole("button", { name: "25", exact: true }).click();
    await waitQuotaRange(page, "1–25 of 70 · A–Z");
    sentQuery({ limit: "25", startsWith: named[0].name });
    // The sort: the highest use first.
    await panel(page).getByRole("group", { name: "Sort" }).getByRole("button", { name: "% used" }).click();
    await waitQuotaRange(page, "1–25 of 70 · most used first");
    sentQuery({ sort: "used", limit: "25" });
    const used = [...fleet].sort((a, b) => b.used - a.used || byName(a, b));
    assert.deepEqual((await quotaRows(page)).map((r) => r[0]), used.slice(0, 25).map((r) => r.name));
    // A state chip: the API filters, and the other chips and All keep their counts.
    await panel(page).getByRole("group", { name: "Needs attention" }).getByRole("button", { name: /^Near limit/ }).click();
    await waitQuotaRange(page, `1–25 of ${nearLimit} (filtered from 70) · most used first`);
    assert.deepEqual(quotaCalls().filter((c) => c.query.state).at(-1).query, { state: "near-limit", sort: "used", limit: "25" });
    assert.ok((await quotaRows(page)).every((r) => r[7].includes("near-limit")));
    assert.equal((await chips(page, "Needs attention"))[0], "All 70", "All counts the rows of the other filters");
    await panel(page).getByRole("group", { name: "Needs attention" }).getByRole("button", { name: /^Near limit/ }).click();
    // The environment and the tier.
    await panel(page).getByRole("group", { name: "Env" }).getByRole("button", { name: "dev", exact: true }).click();
    await panel(page).getByRole("group", { name: "Tier" }).getByRole("button", { name: "small", exact: true }).click();
    const devSmall = fleet.filter((r) => r.env === "dev" && r.tier === "small");
    await waitQuotaRange(page, `1–${devSmall.length} of ${devSmall.length} (filtered from 70) · most used first`);
    sentQuery({ env: "dev", tier: "small", sort: "used", limit: "25" });
    assert.equal(new URL(page.url()).hash, "#quotas?env=dev&tier=small&sort=used&limit=25", "the address holds the view");
    assert.deepEqual(await chips(page, "Tier"), ["All", "small", "medium", "large", "custom"], "the tiers of the catalog, in its order");

    // The letter jump: sort by name, and the page starts at the first name with the letter.
    await panel(page).getByRole("group", { name: "Env" }).getByRole("button", { name: "All", exact: true }).click();
    await panel(page).getByRole("group", { name: "Tier" }).getByRole("button", { name: "All", exact: true }).click();
    const letters = panel(page).getByRole("group", { name: "Jump to the first namespace starting with a letter" });
    const ps = fleet.filter((r) => r.name.startsWith("p")).length;
    const p = letters.getByRole("button", { name: `P: ${ps} namespace${ps === 1 ? "" : "s"}` });
    await p.click();
    await page.waitForFunction(() => document.querySelector("table[aria-label=Quotas] tbody tr td")?.innerText.startsWith("p"));
    sentQuery({ limit: "25", startsWith: "p" });
    assert.match(await p.getAttribute("class"), /pf-m-primary/, "the letter of the page's first name is marked");
    assert.equal(await letters.getByRole("button", { name: "Z: 0 namespaces" }).getAttribute("aria-disabled"), "true", "a letter with no namespace is off");

    // Show all matches: the search is the API's q, and its chip clears it.
    await page.getByRole("combobox", { name: "Find a namespace, team or app" }).fill("LEDGER");
    await panel(page).getByRole("button", { name: "Show all matches" }).click();
    const ledger = fleet.filter((r) => r.name.includes("ledger"));
    await waitQuotaRange(page, `1–${ledger.length} of ${ledger.length} (filtered from 70) · A–Z`);
    sentQuery({ q: "LEDGER", limit: "25" });
    await panel(page).getByRole("button", { name: 'matching "LEDGER" ✕' }).click();
    await waitQuotaRange(page, "1–25 of 70 · A–Z");

    // The same address in a new page keeps the view.
    await panel(page).getByRole("group", { name: "Sort" }).getByRole("button", { name: "Needs attention" }).click();
    await waitQuotaRange(page, "1–25 of 70 · most urgent first");
    const again = await context.newPage();
    await again.goto(page.url());
    await again.locator("table[aria-label=Quotas] tbody tr").first().waitFor();
    assert.equal(await again.getByRole("group", { name: "Sort" }).getByRole("button", { name: "Needs attention" }).getAttribute("aria-pressed"), "true");
    assert.deepEqual(await quotaRows(again), await quotaRows(page));
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("11 Quotas type-ahead: GET /api/v1/quotas:suggest as one types; the keyboard picks a match, and the page starts at it", async () => {
    const { context, page, errors } = await quotaFresh();
    await openQuotas(page);
    const box = page.getByRole("combobox", { name: "Find a namespace, team or app" });
    await box.fill("p");
    await page.waitForTimeout(500);
    assert.equal(calls("/api/v1/quotas:suggest").length, 0, "one character asks nothing: the API answers fewer than two with no match");
    assert.equal(await box.getAttribute("aria-expanded"), "false");
    await box.fill("pay");
    const options = page.getByRole("listbox").getByRole("option");
    const want = quotaSuggest(fleet, "pay");
    await page.waitForFunction((n) => document.querySelectorAll("#q-sug [role=option]:not([aria-disabled=true])").length === n, want.length);
    assert.deepEqual(calls("/api/v1/quotas:suggest").map((c) => c.query), [{ q: "pay" }], "one call, for the text when the typing stopped");
    assert.equal(await box.getAttribute("aria-expanded"), "true");
    assert.deepEqual((await options.allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim()), want.map((s) => `${s.name} ${s.clusterId} ${s.why}`));
    await box.press("ArrowDown");
    await box.press("ArrowDown");
    assert.equal(await box.getAttribute("aria-activedescendant"), "q-opt-1", "the second match is active");
    assert.equal(await options.nth(1).getAttribute("aria-selected"), "true");
    await box.press("Enter");
    const picked = want[1];
    await page.waitForFunction((name) => document.querySelector("table[aria-label=Quotas] tbody tr td")?.innerText === name, picked.name);
    sentQuery({ limit: "50", startsWith: picked.name }, "the filters start again, and the page starts at the match");
    assert.deepEqual((await quotaRows(page))[0].at(-1), "Selected", "the match is the namespace shown below");
    assert.equal(new URL(page.url()).hash, `#quotas?ns=${encodeURIComponent(`${picked.clusterId}/${picked.name}`)}`);
    assert.equal(await box.inputValue(), "");
    await panel(page).getByRole("heading", { name: `${picked.name} on ${picked.clusterId}` }).waitFor();
    // No match, and Escape.
    await box.fill("zzz");
    await page.getByRole("listbox").getByText('No namespace matches "zzz".').waitFor();
    await box.press("Escape");
    assert.equal(await box.getAttribute("aria-expanded"), "false");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("11 Quotas export: GET /api/v1/quotas:export with the list's filters and sort; its rows, its first lines and the file", async () => {
    const { context, page, errors } = await quotaFresh();
    await openQuotas(page, "#quotas?env=dev&sort=used");
    await panel(page).getByRole("button", { name: "Export CSV" }).click();
    const csv = quotaCsv(fleet, quotaQueryOf(new URLSearchParams("env=dev&sort=used")));
    const lines = csv.split("\r\n").filter(Boolean);
    const file = `quotas-nonprod-${new Date().toISOString().slice(0, 10)}.csv`;
    const callout = panel(page).locator(".pf-v6-c-alert").filter({ hasText: file });
    await callout.waitFor();
    assert.deepEqual(calls("/api/v1/quotas:export").map((c) => c.query), [{ env: "dev", sort: "used" }], "one export, of the list's filters, with no page");
    assert.match(await callout.innerText(), new RegExp(`${file} · ${lines.length - 1} rows`));
    assert.match(await callout.innerText(), /GET \/api\/v1\/quotas:export\?env=dev&sort=used streams every row matching the current filters, not only this page, in the current sort order\. Capped at 10,000 rows and recorded in the audit log\./);
    assert.equal(await panel(page).locator(".pf-v6-c-code-block").innerText(), [...lines.slice(0, 5), `… ${lines.length - 5} more rows`].join("\n"));
    const [download] = await Promise.all([page.waitForEvent("download"), panel(page).getByRole("link", { name: "Download" }).click()]);
    assert.equal(download.suggestedFilename(), file);
    assert.equal(readFileSync(await download.path(), "utf8"), csv, "the file is the API's CSV, every row");
    await panel(page).getByRole("button", { name: "Close" }).click();
    assert.equal(await callout.count(), 0);
    assert.equal(calls("/api/v1/quotas:export").length, 1, "the file came from the one export");
    assert.deepEqual(errors, []);
    await context.close();
  });

  // A dev namespace on the small tier with no open request: its change to medium raises CPU, so the platform group approves.
  const target = named.find((r) => r.env === "dev" && r.tier === "small" && !r.openRequest);
  const locked = named.find((r) => r.openRequest);
  const patches = (r = target) => api.state.seen.filter((c) => c.method === "PATCH" && c.path === `/api/v1/clusters/${r.clusterId}/namespaces/${r.name}`);
  const changeCard = (page) => panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: /^Change quota · / }) });
  const manage = async (page, r) => {
    await openQuotas(page, `#quotas?ns=${encodeURIComponent(`${r.clusterId}/${r.name}`)}`);
    await panel(page).getByRole("heading", { name: `${r.name} on ${r.clusterId}` }).waitFor();
  };
  const planOf = async (page, size) => {
    if (size) await changeCard(page).getByRole("group", { name: "New size" }).getByRole("button", { name: new RegExp(`^${size}`) }).click();
    await changeCard(page).getByRole("button", { name: "Plan change" }).click();
  };

  await check("12 Quotas change: the plan's checks and approval, then a submit of exactly the planned body with If-Match and an Idempotency-Key; the same size plans nothing", async () => {
    const { context, page, errors } = await quotaFresh();
    await manage(page, target);
    // The etag that GET /api/v1/clusters/{cluster_id}/namespaces/{ns} gave the page.
    const etag = api.state.etags.get(`${target.clusterId}/${target.name}`);
    assert.match(etag, /^[0-9a-f]{16}$/);
    assert.match(await panel(page).innerText(), new RegExp(`GET /api/v1/clusters/${target.clusterId}/namespaces/${target.name} · ETag ${etag} · ResourceQuota and LimitRange for tier small live in the namespace folder in Git\\.`));
    const detail = panel(page).locator("table[aria-label=ResourceQuota] tbody tr");
    assert.deepEqual(await detail.evaluateAll((trs) => trs.map((tr) => [...tr.children].map((td) => td.innerText.replace(/\s+/g, " ").trim()))), [
      ["requests.cpu", `${one(num(target.cpu[0]))} cores`, "8 cores", `${Math.round(num(target.cpu[0]) / 8 * 100)}%`],
      ["requests.memory", `${one(num(target.memory[0]))} Gi`, "16 Gi", `${Math.round(num(target.memory[0]) / 16 * 100)}%`],
      ["pods", target.pods[0], "50", `${Math.round(Number(target.pods[0]) / 50 * 100)}%`]
    ]);
    assert.deepEqual((await changeCard(page).getByRole("group", { name: "New size" }).getByRole("button").allInnerTexts()).map((t) => t.replace(/\s+/g, " ")),
      ["small 8 cores · 16Gi · current", "medium 16 cores · 32Gi", "large 32 cores · 64Gi", "custom set cpu and memory"], "the catalog's tiers of the environment");

    // The current size: nothing to plan, and nothing is sent.
    await planOf(page);
    await changeCard(page).getByText("The new size equals the current quota; pick another tier or custom values.").waitFor();
    assert.equal(patches().length, 0);

    // Submit with no plan plans first and writes nothing; the next Submit sends the plan that is on the page.
    await changeCard(page).getByRole("group", { name: "New size" }).getByRole("button", { name: /^medium/ }).click();
    await changeCard(page).getByLabel("Justification").fill("Load test next sprint");
    await changeCard(page).getByRole("button", { name: "Submit change" }).click();
    const approval = changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi from approver-platform" });
    await approval.waitFor();
    assert.equal(patches().filter((c) => c.query.dryRun !== "true").length, 0, "a change that was not planned is planned first");
    const [dry] = patches();
    assert.deepEqual({ query: dry.query, ifMatch: dry.ifMatch, key: dry.key, body: dry.body },
      { query: { dryRun: "true" }, ifMatch: `"${etag}"`, key: null, body: { tier: "medium", justification: "Load test next sprint" } }, "the dry run: the etag of GET as If-Match, and no key");
    assert.deepEqual((await changeCard(page).locator("li").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim()), [
      "✓ Environment served dev in [rnd, dev]", `✓ If-Match matches the current ETag ${etag}`, `✓ Capacity on ${target.clusterId} fits on fresh data · cpu 13% · memory 10% · binds on cpu`, "! Approval dev-change"
    ]);
    const update = SAMPLES.operations.namespaces_update_namespace.response.body;
    assert.match(await approval.innerText(), new RegExp(`${update.approval.reasons.join("; ").replace(/[+()>]/g, "\\$&")}\\. Nothing reaches Git until they approve\\. Self-approval is allowed in dev\\.`));
    await changeCard(page).getByRole("button", { name: "Submit change" }).click();
    const accepted = changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" });
    await accepted.waitFor();
    const writes = patches().filter((c) => c.query.dryRun !== "true");
    assert.equal(writes.length, 1);
    assert.deepEqual(writes[0].body, dry.body, "the submitted body is the planned one");
    assert.equal(writes[0].ifMatch, `"${etag}"`);
    assert.match(writes[0].key, /^[0-9a-f-]{36}$/, "an Idempotency-Key that the portal made");
    assert.match(await accepted.innerText(), /202 Accepted · req-\d{8}-8001 · pending_approval\s+Waiting for 1 approval in cmapi \(approver-platform\)\. The approvers are notified; nothing is written to Git until the count is met\./);
    assert.match(await changeCard(page).locator(".pf-v6-c-code-block").innerText(), /"requestId": "req-\d{8}-8001",\s+"status": "pending_approval"/);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("12 Quotas change: custom sizes within the catalog's bounds; a lock opens its request; a viewer has no change form", async () => {
    {
      const { context, page, errors } = await quotaFresh();
      await manage(page, target);
      await changeCard(page).getByRole("group", { name: "New size" }).getByRole("button", { name: /^custom/ }).click();
      const cpu = changeCard(page).getByLabel("requests.cpu (cores)"), mem = changeCard(page).getByLabel("requests.memory (Gi)");
      assert.deepEqual([await cpu.inputValue(), await mem.inputValue()], ["8", "16"], "custom starts at the current quota");
      assert.deepEqual(await cpu.evaluate((el) => [el.min, el.max, el.step, el.required]), ["2", "32", "1", true], "the custom tier's bounds of the catalog");
      // Below the custom tier's minimum: the browser refuses it, and nothing is sent.
      await cpu.fill("1");
      await planOf(page);
      await page.waitForTimeout(300);
      assert.equal(patches().length, 0, "no plan of a value that the browser refuses");
      await cpu.fill("12");
      await mem.fill("24");
      await planOf(page);
      await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "approval" }).waitFor();
      assert.deepEqual(patches().at(-1).body, { tier: "custom", quota: { "requests.cpu": "12", "requests.memory": "24Gi" }, justification: null });
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await quotaFresh();
      await manage(page, locked);
      const lock = changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: `Change in progress: ${locked.openRequest}` });
      await lock.waitFor();
      assert.match(await lock.innerText(), new RegExp(`${locked.openRequest} holds this namespace in cmapi\\. cmapi holds one open request per namespace, so another change is refused with 409 change-pending until this one closes\\.`));
      assert.equal(await changeCard(page).getByRole("button", { name: "Plan change" }).count(), 0, "no form while a request holds the namespace");
      await lock.getByRole("button", { name: "Open at current step" }).click();
      await page.waitForFunction((id) => location.hash === `#workflow?request=${id}`, locked.openRequest);
      assert.deepEqual(errors.filter((e) => !/status of 404/.test(e)), []);
      await context.close();
    }
    {
      const { context, page, errors } = await quotaFresh({ user: "viewer" });
      await manage(page, target);
      assert.equal(await changeCard(page).count(), 0, "the viewer holds no namespaces:write, so the change form is not shown");
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("12 Quotas refusals and states: loading, empty, a 403, a 5xx with Try again, a stale cursor, a refused plan and a 412", async () => {
    {
      const { context, page, errors } = await quotaFresh();
      api.state.delayMs = 700;
      await page.goto(`${portal.page}#quotas`);
      await page.getByRole("status").filter({ hasText: "Loading quotas…" }).waitFor();
      await page.locator("table[aria-label=Quotas] tbody tr").first().waitFor();
      assert.equal(await page.getByRole("status").filter({ hasText: "Loading quotas…" }).count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await quotaFresh({ mode: "empty" });
      await open(page, "#quotas");
      await panel(page).getByText("No namespace on the nonprod instance matches these filters.").waitFor();
      assert.match(await panel(page).innerText(), /0 namespaces/);
      assert.equal(await panel(page).getByRole("heading", { name: /^Change quota/ }).count(), 0, "no namespace, no detail");
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await quotaFresh();
      expectedStatus = [403];
      api.state.answers.push({ route: "GET /api/v1/quotas", status: 403, body: { type: "https://cmapi.ephico2real.com/problems/forbidden", title: "forbidden", status: 403, code: "forbidden", detail: "Missing permission objects:read: no role in your token grants it (roles: ['cmapi-none'])" } });
      await open(page, "#quotas");
      await panel(page).getByRole("heading", { name: "You do not have permission to see quotas." }).waitFor();
      assert.match(await panel(page).innerText(), /Missing permission objects:read/);
      assert.equal(await panel(page).getByRole("button").count(), 0, "no action");
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await quotaFresh();
      expectedStatus = [500];
      api.state.answers.push({ route: "GET /api/v1/quotas", status: 500, body: { type: "https://cmapi.ephico2real.com/problems/internal-error", title: "internal-error", status: 500, code: "internal-error", detail: "The watch cache did not answer." } });
      await open(page, "#quotas");
      const alert = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The quotas did not load." });
      await alert.waitFor();
      assert.match(await alert.innerText(), /The watch cache did not answer\./);
      await alert.getByRole("button", { name: "Try again" }).click();
      await page.locator("table[aria-label=Quotas] tbody tr").first().waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // A cursor that the API no longer takes: the mockup's callout, and its way back to the first page.
      const { context, page, errors } = await quotaFresh();
      expectedStatus = [400];
      await openQuotas(page);
      api.state.answers.push({ route: "GET /api/v1/quotas", status: 400, body: { type: "https://cmapi.ephico2real.com/problems/invalid-cursor", title: "invalid-cursor", status: 400, code: "invalid-cursor", detail: "Filters or sort changed since this cursor was issued" } });
      await page.getByRole("button", { name: "Next ›" }).first().click();
      const stale = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "This page link is out of date" });
      await stale.waitFor();
      assert.match(await stale.innerText(), /The filters or sort changed after it was made, so the API refused it \(400 invalid-cursor\) rather than show the wrong rows\./);
      await stale.getByRole("button", { name: "Back to the first page" }).click();
      await waitQuotaRange(page, "1–50 of 70 · A–Z");
      assert.equal(await stale.count(), 0, "the first page, with no cursor, is shown again");
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // A plan that the API refuses, then a change of the folder after the plan: the submit gets 412 and writes nothing.
      const { context, page, errors } = await quotaFresh();
      expectedStatus = [422, 412];
      await manage(page, target);
      api.state.answers.push({ route: `PATCH /api/v1/clusters/${target.clusterId}/namespaces/${target.name}`, status: 422, body: { type: "https://cmapi.ephico2real.com/problems/capacity-exceeded", title: "capacity-exceeded", status: 422, code: "capacity-exceeded", detail: "requests.cpu 32 does not fit on CRC" } });
      await planOf(page, "large");
      const refused = changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "Refused: capacity-exceeded" });
      await refused.waitFor();
      assert.match(await refused.innerText(), /requests\.cpu 32 does not fit on CRC/);
      await planOf(page, "medium");
      await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
      assert.equal(await refused.count(), 0, "the refusal was of the other plan");
      api.state.etags.set(`${target.clusterId}/${target.name}`, "0123456789abcdef");
      await changeCard(page).getByRole("button", { name: "Submit change" }).click();
      const failed = changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "412 precondition-failed · nothing written" });
      await failed.waitFor();
      assert.match(await failed.innerText(), /No request was stored and nothing was written to Git\. The namespace changed in Git since you read it/);
      assert.equal(api.state.created, 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("R5 Quotas: the same change sent again after a lost answer keeps its Idempotency-Key; a changed one gets a new key", async () => {
    const { context, page, errors } = await quotaFresh();
    expectedStatus = [409];
    const route = `PATCH /api/v1/clusters/${target.clusterId}/namespaces/${target.name}`;
    await manage(page, target);
    await planOf(page, "medium");
    await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
    // The API makes the request, and its answer is lost on the way.
    api.state.lose.add(route);
    await changeCard(page).getByRole("button", { name: "Submit change" }).click();
    await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "Not submitted" }).getByText(/The network did not answer\. Submit again: the same request is sent, and the API makes it at most once\./).waitFor();
    api.state.lose.clear();
    assert.equal(api.state.created, 1, "the lost answer's request was made");
    // The same change again: the same key, so the API answers with the request it made.
    await changeCard(page).getByRole("button", { name: "Submit change" }).click();
    await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
    const writes = () => patches().filter((c) => c.query.dryRun !== "true");
    assert.ok(writes().every((c) => c.key === writes()[0].key), "the retries of one change share one key");
    assert.equal(api.state.created, 1, "no second request");
    // A changed form is another change: planned again, then sent with a new key. The namespace is held now, so the API refuses it.
    await changeCard(page).getByLabel("Justification").fill("Launch week");
    await planOf(page);
    await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
    await changeCard(page).getByRole("button", { name: "Submit change" }).click();
    await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "409 change-pending · nothing written" }).waitFor();
    assert.notEqual(writes().at(-1).key, writes()[0].key, "a changed body is sent with a new key");
    assert.equal(writes().at(-1).body.justification, "Launch week");
    assert.deepEqual(errors.filter((e) => !/net::ERR_EMPTY_RESPONSE/.test(e)), []);
    await context.close();
  });

  await check("F1 Quotas: a 412 reads the namespace again and plans on its new ETag; Submit never sends the stale ETag again", async () => {
    const { context, page, errors } = await quotaFresh();
    expectedStatus = [412];
    const where = `${target.clusterId}/${target.name}`;
    const reads = () => api.state.seen.filter((c) => c.method === "GET" && c.path === `/api/v1/clusters/${where.replace("/", "/namespaces/")}`).length;
    const until = async (ok, why) => {
      const end = Date.now() + 5000;
      while (!ok()) {
        if (Date.now() > end) assert.fail(why());
        await page.waitForTimeout(50);
      }
    };
    await manage(page, target);
    const old = api.state.etags.get(where);
    await planOf(page, "medium");
    await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
    // Another change reaches the folder in Git after the plan, so its etag moves on.
    const now = "0123456789abcdef";
    api.state.etags.set(where, now);
    const readsBefore = reads();
    await changeCard(page).getByRole("button", { name: "Submit change" }).click();
    await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "412 precondition-failed · nothing written" }).waitFor();
    const writes = () => patches().filter((c) => c.query.dryRun !== "true");
    // docs/04 and problem_docs.py: "Read the object again, and send the change with the new ETag in If-Match".
    await until(() => reads() > readsBefore, () => `the namespace was not read again after the 412 (GETs: ${reads()})`);
    await until(() => patches().some((c) => c.query.dryRun === "true" && c.ifMatch === `"${now}"`),
      () => `the change was not planned again on the new etag; the PATCHes were ${JSON.stringify(patches().map((c) => [c.query.dryRun ?? "write", c.ifMatch]))}`);
    await changeCard(page).locator("li").filter({ hasText: `If-Match matches the current ETag ${now}` }).waitFor();
    await changeCard(page).getByRole("button", { name: "Submit change" }).click();
    await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
    assert.equal(writes().filter((c) => c.ifMatch === `"${old}"`).length, 1, "the stale etag was sent one time, never again");
    assert.equal(writes().at(-1).ifMatch, `"${now}"`, "the change went with the etag that the page read again");
    assert.ok(writes().every((c) => c.key === writes()[0].key), "the same body keeps its key across the new etag");
    assert.deepEqual(writes().at(-1).body, { tier: "medium", justification: null });
    assert.equal(api.state.created, 1);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("R6 a double click on Submit change sends one write", async () => {
    const { context, page, errors } = await quotaFresh();
    await manage(page, target);
    await planOf(page, "medium");
    await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
    api.state.delayMs = 300;
    await changeCard(page).getByRole("button", { name: "Submit change" }).dblclick();
    await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
    await page.waitForTimeout(800);
    const writes = patches().filter((c) => c.query.dryRun !== "true").length;
    console.log(`  writes on a double click of Submit change: ${writes}`);
    assert.equal(writes, 1);
    assert.equal(await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "409" }).count(), 0);
    assert.deepEqual(errors, []);
    await context.close();
    // Two submits in one task: the page's "sending" state cannot have reached React yet, so only the one-at-a-time guard
    // of the hook (useOneAtATime) stands between them and a second write.
    const second = await quotaFresh();
    await manage(second.page, target);
    await planOf(second.page, "medium");
    await changeCard(second.page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
    api.state.delayMs = 300;
    await changeCard(second.page).locator("form").evaluate((form) => { form.requestSubmit(); form.requestSubmit(); });
    await changeCard(second.page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
    await second.page.waitForTimeout(800);
    const together = patches().filter((c) => c.query.dryRun !== "true").length;
    console.log(`  writes on two submits in one task: ${together}`);
    assert.equal(together, 1);
    assert.deepEqual(second.errors, []);
    await second.context.close();
  });

  // #366: operators protect a namespace from deletion. The badge is everyone's, from the API's protectedBy; the control and the
  // create box are an operator's, from /me's operator and operatorEnvironments. Each body names the protection label only.
  const PROTECTION = "cmapi.net/protected=true";
  const protectedTarget = named.find((r) => r.env === "dev" && r.tier === "small" && !r.openRequest && r !== target);
  const detailCard = (page, r) => panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: `${r.name} on ${r.clusterId}` }) });
  const dialog = (page) => page.getByRole("dialog");
  const protectFresh = async (user, protection = []) => {
    const opened = await quotaFresh({ user });
    api.state.protection = new Map([[`${protectedTarget.clusterId}/${protectedTarget.name}`, protection]]);
    await manage(opened.page, protectedTarget);
    return opened;
  };

  await check("19 Protection: everyone sees the badge and why a delete request is refused; only an operator has the control", async () => {
    for (const [user, control] of [["viewer", null], ["requester", null], ["operator", "Remove protection"]]) {
      const { context, page, errors } = await protectFresh(user, [PROTECTION, "do-not-delete=true"]);
      const card = detailCard(page, protectedTarget);
      await card.getByText("Protected", { exact: true }).waitFor();
      assert.match(await card.innerText(), /cmapi refuses a delete request for this namespace \(422 namespace-protected\): cmapi\.net\/protected=true, do-not-delete=true\./, user);
      assert.equal(await card.getByRole("button", { name: /protect/i }).count(), control ? 1 : 0, `${user}: the control`);
      if (control) assert.equal(await card.getByRole("button", { name: control }).count(), 1);
      assert.deepEqual(errors, []);
      await context.close();
    }
    // Not protected: no badge, and the operator's control protects.
    const { context, page, errors } = await protectFresh("operator");
    const card = detailCard(page, protectedTarget);
    await card.getByRole("button", { name: "Protect from deletion" }).waitFor();
    assert.equal(await card.getByText("Protected", { exact: true }).count(), 0);
    assert.doesNotMatch(await card.innerText(), /cmapi refuses a delete request/);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("19 Protection: the operator's dialog plans exactly the label with If-Match, shows the approval, and submits that body with one key", async () => {
    const { context, page, errors } = await protectFresh("operator");
    const etag = api.state.etags.get(`${protectedTarget.clusterId}/${protectedTarget.name}`);
    const writes = () => patches(protectedTarget);
    await detailCard(page, protectedTarget).getByRole("button", { name: "Protect from deletion" }).click();
    await dialog(page).getByRole("heading", { name: "Protect from deletion" }).waitFor();
    assert.match(await dialog(page).innerText(), new RegExp(`This sends a request to add cmapi\.net/protected=true to ${protectedTarget.name}\.`));
    const approval = dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "No approval needed" });
    await approval.waitFor();
    assert.deepEqual(writes().map((c) => ({ query: c.query, ifMatch: c.ifMatch, key: c.key, body: c.body })),
      [{ query: { dryRun: "true" }, ifMatch: `"${etag}"`, key: null, body: { labels: { "cmapi.net/protected": "true" } } }], "the plan: the label only");
    await dialog(page).getByLabel("Justification").fill("Shared ledger, never delete");
    // The first answer is lost on the way: Submit again sends the same request with the same key.
    const route = `PATCH /api/v1/clusters/${protectedTarget.clusterId}/namespaces/${protectedTarget.name}`;
    api.state.lose.add(route);
    await dialog(page).getByRole("button", { name: "Submit request" }).click();
    await dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "Not submitted" }).waitFor();
    api.state.lose.clear();
    await dialog(page).getByRole("button", { name: "Submit request" }).click();
    await dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
    const sent = writes().filter((c) => c.query.dryRun !== "true");
    assert.ok(sent.length >= 2, `the lost write and the second (${sent.length})`);
    assert.deepEqual(sent.map((c) => c.key), sent.map(() => sent[0].key), "the same change keeps its Idempotency-Key");
    assert.equal(api.state.created, 1, "the API made one request");
    assert.deepEqual(sent[0].body, { labels: { "cmapi.net/protected": "true" }, justification: "Shared ledger, never delete" }, "the label and the reason, nothing else");
    assert.equal(sent.at(-1).ifMatch, `"${etag}"`);
    assert.match(sent[0].key, /^[0-9a-f-]{36}$/);
    assert.equal(await dialog(page).getByRole("status").filter({ hasText: "202 Accepted" }).count(), 1, "the outcome is a status message");
    await dialog(page).getByRole("button", { name: "Open at current step" }).click();
    await page.waitForFunction(() => location.hash.startsWith("#workflow?request="));
    assert.deepEqual(errors.filter((e) => !/net::ERR_EMPTY_RESPONSE/.test(e)), []);
    await context.close();
  });

  await check("19 Protection: an operator limited to rnd has the control and the create box in rnd, and neither in dev", async () => {
    const onRnd = named.find((r) => r.env === "rnd" && !r.openRequest);
    const { context, page, errors } = await quotaFresh({ user: "rndOperator" });
    await manage(page, protectedTarget);
    await detailCard(page, protectedTarget).getByText(/ETag [0-9a-f]{16}/).waitFor();     // the namespace was read
    assert.equal(await detailCard(page, protectedTarget).getByRole("button", { name: /protect/i }).count(), 0, "dev: not an operator there");
    await manage(page, onRnd);
    await detailCard(page, onRnd).getByRole("button", { name: "Protect from deletion" }).waitFor();
    // The create form: the box follows operatorEnvironments, not a permission held somewhere.
    await newTab(page);
    const envs = panel(page).getByRole("group", { name: "Environment" });
    await envs.getByRole("button", { name: "dev" }).click();
    await panel(page).getByLabel("Justification").waitFor();
    assert.equal(await panel(page).getByLabel("Protect from deletion").count(), 0, "dev: not an operator there");
    await envs.getByRole("button", { name: "rnd" }).click();
    await panel(page).getByLabel("Protect from deletion").waitFor();
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("19 Protection: removing it sends null, needs approver-platform, and says what still protects; Cancel sends nothing", async () => {
    const { context, page, errors } = await protectFresh("operator", [PROTECTION, "do-not-delete=true"]);
    const opener = detailCard(page, protectedTarget).getByRole("button", { name: "Remove protection" });
    await opener.click();
    await dialog(page).getByRole("heading", { name: "Remove protection" }).waitFor();
    await dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi from approver-platform" }).waitFor();
    assert.match(await dialog(page).innerText(), /Still protected by do-not-delete=true/);
    assert.match(await dialog(page).innerText(), /threshold sensitiveKeyChanged: \+1 approver-platform/);
    assert.deepEqual(patches(protectedTarget).map((c) => c.body), [{ labels: { "cmapi.net/protected": null } }], "removal is null, never \"false\"");
    await dialog(page).getByRole("button", { name: "Cancel" }).click();
    await dialog(page).waitFor({ state: "detached" });
    assert.equal(patches(protectedTarget).filter((c) => c.query.dryRun !== "true").length, 0, "Cancel writes nothing");
    assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Remove protection", "the focus is back on the button");
    await opener.click();
    await dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
    await dialog(page).getByRole("button", { name: "Submit request" }).click();
    await dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
    assert.match(await dialog(page).innerText(), /Waiting for 1 approval in cmapi \(approver-platform\)/);
    assert.deepEqual(patches(protectedTarget).filter((c) => c.query.dryRun !== "true").map((c) => c.body), [{ labels: { "cmapi.net/protected": null }, justification: null }]);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("19 Protection: a 412 reads the namespace again and plans on its new ETag; a refusal shows its code", async () => {
    const { context, page, errors } = await protectFresh("operator");
    const key = `${protectedTarget.clusterId}/${protectedTarget.name}`;
    const old = api.state.etags.get(key);
    api.state.etags.set(key, "0123456789abcdef");
    expectedStatus = [412];
    await detailCard(page, protectedTarget).getByRole("button", { name: "Protect from deletion" }).click();
    await dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "No approval needed" }).waitFor();
    assert.deepEqual(patches(protectedTarget).map((c) => c.ifMatch), [`"${old}"`, "\"0123456789abcdef\""], "the stale etag once, then the namespace's new one");
    assert.equal(await dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "precondition-failed" }).count(), 0);
    expectedStatus = [412, 403];
    api.state.answers.push({ route: `PATCH /api/v1/clusters/${key.replace("/", "/namespaces/")}`, status: 403,
      body: { type: "https://cmapi.ephico2real.com/problems/forbidden", title: "forbidden", status: 403, code: "forbidden", detail: "Only an operator (namespaces:protect) may set cmapi.net/protected" } });
    const meBefore = calls("/api/v1/me").length;
    await dialog(page).getByRole("button", { name: "Submit request" }).click();
    await dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "403 forbidden · nothing written" }).waitFor();
    for (let i = 0; i < 20 && calls("/api/v1/me").length === meBefore; i++) await page.waitForTimeout(100);
    assert.ok(calls("/api/v1/me").length > meBefore, "a 403 reads /me again");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("19 New namespace: Protect from deletion for an operator, absent for a requester; the body has the label only when checked", async () => {
    {
      const { context, page, errors } = await fresh();
      await newTab(page);
      assert.equal(await panel(page).getByLabel("Protect from deletion").count(), 0, "a requester has no box");
      assert.deepEqual(errors, []);
      await context.close();
    }
    const { context, page, errors } = await fresh({ user: "operator" });
    await newTab(page);
    await fillForm(page);
    const box = panel(page).getByLabel("Protect from deletion");
    assert.equal(await box.isChecked(), false);
    await panel(page).getByRole("button", { name: "Dry run" }).click();
    await panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Dry run passed" }).waitFor();
    assert.deepEqual(posts().at(-1).body.labels, { "cmapi.net/team": "payments" }, "unchecked: no protection key at all");
    await box.check();
    assert.match(await panel(page).innerText(), /Operators only\. Adds cmapi\.net\/protected=true: cmapi refuses a delete request for this namespace until an operator removes it\./);
    await panel(page).getByRole("button", { name: "Dry run" }).click();
    await panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Dry run passed" }).waitFor();
    assert.deepEqual(posts().at(-1).body.labels, { "cmapi.net/team": "payments", "cmapi.net/protected": "true" });
    await panel(page).getByRole("button", { name: "Submit request" }).click();
    await page.waitForFunction(() => location.hash.startsWith("#workflow?request="));
    assert.deepEqual(posts().at(-1).body.labels, { "cmapi.net/team": "payments", "cmapi.net/protected": "true" }, "the submit sends the planned body");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("19 Protection at 390 and 1440 px in each theme, with the dialog open, and axe", async () => {
    for (const width of [390, 1440]) {
      const { context, page, errors } = await quotaFresh({ user: "operator", width });
      api.state.protection = new Map([[`${protectedTarget.clusterId}/${protectedTarget.name}`, [PROTECTION]]]);
      await manage(page, protectedTarget);
      await detailCard(page, protectedTarget).getByText("Protected", { exact: true }).waitFor();
      for (const theme of ["light", "dark"]) {
        await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
        await settled(page);
        const card = detailCard(page, protectedTarget);
        await card.scrollIntoViewIfNeeded();
        await card.screenshot({ path: join(out, `protection-${width}-${theme}.png`) });
        const scan = await new AxeBuilder({ page }).analyze();
        assert.deepEqual(scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.html}`), [], `axe at ${width} ${theme}`);
        await card.getByRole("button", { name: "Remove protection" }).click();
        await dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
        await settled(page);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        assert.ok(overflow <= 0, `${width} ${theme}: no sideways scroll with the dialog open (${overflow})`);
        await page.screenshot({ path: join(out, `protection-dialog-${width}-${theme}.png`) });
        const modal = await new AxeBuilder({ page }).include(".pf-v6-c-modal-box").analyze();
        assert.deepEqual(modal.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.html}`), [], `axe on the dialog at ${width} ${theme}`);
        await dialog(page).getByRole("button", { name: "Cancel" }).click();
        await dialog(page).waitFor({ state: "detached" });
      }
      assert.deepEqual(errors, []);
      await context.close();
    }
    for (const width of [390, 1440]) {
      const { context, page, errors } = await fresh({ user: "operator", width });
      await newTab(page);
      for (const theme of ["light", "dark"]) {
        await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
        await settled(page);
        const group = panel(page).locator(".pf-v6-c-form__group").filter({ hasText: "Deletion protection" });
        await group.getByLabel("Protect from deletion").check();
        await group.scrollIntoViewIfNeeded();
        await group.screenshot({ path: join(out, `protection-create-${width}-${theme}.png`) });
      }
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  // Portal slice 4a (#318): the Expiration tab. The fleet is 40 namespaces of the stand-in in dev and rnd, over every state,
  // counted from the API's day. Each expectation is written from the mockup's forms (expirationView()) and the API's contract.
  const EXP_TODAY = SAMPLES.operations.expiration_expirations.response.body.today;
  const expFleet = expirationsFrom(40, EXP_TODAY);
  const EXP_WORD = { grace: "In grace", expiring: "Expiring", pending_delete: "Pending delete", active: "Active", permanent: "Permanent" };
  const EXP_RANK = { grace: 0, expiring: 1, pending_delete: 2, active: 3, permanent: 4 };
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const dayOf = (iso) => `${MON[Number(iso.slice(5, 7)) - 1]} ${Number(iso.slice(8, 10))}`;
  const plus = (iso, n) => new Date(Date.parse(iso) + n * 864e5).toISOString().slice(0, 10);
  const urgent = (a, b) => (EXP_RANK[a.state] - EXP_RANK[b.state]) || ((a.daysLeft ?? 99999) - (b.daysLeft ?? 99999)) || byName(a, b);
  const attention = (r) => ["expiring", "grace", "pending_delete"].includes(r.state);
  // The mockup's row: namespace, cluster, env, team, "Nov 3" or "never", days left (in grace: "-3 (grace 4 left)"), "75 of 180 d", the state, the button.
  const expectedExp = (r, selected = false) => [r.name, r.clusterId, r.env, r.team, r.expiresAt ? dayOf(r.expiresAt) : "never",
    r.daysLeft === null ? "—" : r.daysLeft >= 0 ? String(r.daysLeft) : r.state === "grace" ? `${r.daysLeft} (grace ${7 + r.daysLeft} left)` : `${r.daysLeft} (grace over)`,
    r.expiresAt ? `${r.lifetimeDays} of 180 d` : "—", EXP_WORD[r.state], selected ? "Selected" : "Manage"];
  const expRows = (page) => page.locator("table[aria-label=Expiration] tbody tr").evaluateAll((trs) => trs.map((tr) => [...tr.children].map((td) => td.innerText.replace(/\s+/g, " ").trim())));
  const expCalls = () => calls("/api/v1/expirations");
  const sentExp = (want, why) => assert.ok(expCalls().some((c) => isDeepStrictEqual(c.query, want)), `${why ?? "the page's call"}: ${JSON.stringify(want)} was not sent; the calls were ${JSON.stringify(expCalls().map((c) => c.query))}`);
  const expFresh = (options) => fresh({ expirations: expFleet, ...options });
  const openExp = async (page, hash = "#expiration") => {
    await open(page, hash);
    await page.locator("table[aria-label=Expiration] tbody tr").first().waitFor();
  };
  const expCard = (page) => panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: /^Change expiration · / }) });
  const dated = [...expFleet].filter((r) => r.state === "active" && r.env === "dev").sort(urgent)[0];
  const undated = [...expFleet].filter((r) => r.state === "permanent" && r.env === "dev").sort(byName)[0];
  // Open the tab on one namespace: the search narrows the list to it, as the mockup's Approvals link does (xq, xsel).
  const manageExp = async (page, r) => {
    await openExp(page, `#expiration?state=all&q=${r.name}&ns=${encodeURIComponent(`${r.clusterId}/${r.name}`)}`);
    await panel(page).getByRole("heading", { name: `${r.name} on ${r.clusterId}` }).waitFor();
  };
  const expPosts = (r, route) => api.state.seen.filter((c) => c.method === "POST" && c.path === `/api/v1/clusters/${r.clusterId}/namespaces/${r.name}/expiration:${route}`);
  const actOf = async (page, name) => {
    if (name) await expCard(page).getByRole("group", { name: "Action" }).getByRole("button", { name: new RegExp(`^${name}`) }).click();
    await expCard(page).getByRole("button", { name: "Plan change" }).click();
  };

  await check("14 Expiration: the rows of GET /api/v1/expirations cell by cell, most urgent first; the state and env chips, the search and the pages are API parameters", async () => {
    const { context, page, errors } = await expFresh();
    await openExp(page);
    const needs = expFleet.filter(attention).sort(urgent);
    sentExp({ limit: "25", state: "attention" }, "the mockup opens on Needs action, 25 rows");
    assert.deepEqual(await expRows(page), needs.slice(0, 25).map((r, i) => expectedExp(r, i === 0)), "the first page, cell by cell; the first namespace is shown below");
    const count = (s) => expFleet.filter((r) => r.state === s).length;
    assert.match(await panel(page).innerText(), new RegExp(`${count("expiring")} expiring · ${count("grace")} in grace · ${count("pending_delete")} pending delete`));
    assert.deepEqual(await chips(page, "State"), [`Needs action ${needs.length}`, `Expiring ≤ 14 d ${count("expiring")}`, `In grace ${count("grace")}`, `Pending delete ${count("pending_delete")}`,
      `Active ${count("active")}`, `Permanent ${count("permanent")}`, `All ${expFleet.length}`]);
    assert.match(await panel(page).innerText(), new RegExp(`1–${Math.min(25, needs.length)} of ${needs.length} · most urgent first`));
    assert.match(await panel(page).innerText(), new RegExp(`GET /api/v1/expirations\\?limit=25&state=attention · paged and searched like Quotas · today is ${dayOf(EXP_TODAY)}\\.`));
    // All, then the pages forward and back: each row one time.
    await panel(page).getByRole("group", { name: "State" }).getByRole("button", { name: /^All/ }).click();
    const all = [...expFleet].sort(urgent);
    await page.waitForFunction((t) => document.querySelector("[role=tabpanel]")?.innerText.includes(t), `1–25 of ${all.length} · most urgent first`);
    sentExp({ limit: "25" }, "All sends no state");
    assert.deepEqual((await expRows(page)).map((r) => r[0]), all.slice(0, 25).map((r) => r.name));
    await page.getByRole("button", { name: "Next ›" }).first().click();
    await page.waitForFunction((t) => document.querySelector("[role=tabpanel]")?.innerText.includes(t), `26–${all.length} of ${all.length}`);
    assert.deepEqual((await expRows(page)).map((r) => r[0]), all.slice(25).map((r) => r.name), "the second page follows the first, no row twice");
    assert.ok(expCalls().at(-1).query.cursor, "Next sends the API's cursor");
    await page.getByRole("button", { name: "‹ Previous" }).first().click();
    await page.waitForFunction((t) => document.querySelector("[role=tabpanel]")?.innerText.includes(t), `1–25 of ${all.length}`);
    // A state chip, an env chip and the search: each is a parameter of the call, and the rows are the API's.
    await panel(page).getByRole("group", { name: "State" }).getByRole("button", { name: /^In grace/ }).click();
    await page.waitForFunction((t) => document.querySelector("[role=tabpanel]")?.innerText.includes(t), `of ${count("grace")} · most urgent first`);
    sentExp({ limit: "25", state: "grace" });
    assert.deepEqual((await expRows(page)).map((r) => r[0]), expFleet.filter((r) => r.state === "grace").sort(urgent).map((r) => r.name));
    await panel(page).getByRole("group", { name: "Env" }).getByRole("button", { name: "rnd", exact: true }).click();
    const graceRnd = expFleet.filter((r) => r.state === "grace" && r.env === "rnd").sort(urgent);
    await page.waitForFunction((t) => document.querySelector("[role=tabpanel]")?.innerText.includes(t), graceRnd.length ? `of ${graceRnd.length} · most urgent first` : "0 namespaces");
    sentExp({ limit: "25", state: "grace", env: "rnd" });
    await panel(page).getByRole("group", { name: "Env" }).getByRole("button", { name: "All", exact: true }).click();
    await panel(page).getByRole("group", { name: "State" }).getByRole("button", { name: /^All/ }).click();
    await panel(page).getByPlaceholder("Find a namespace or team").fill("ledger");
    const ledger = expFleet.filter((r) => r.name.includes("ledger") || r.team.includes("ledger")).sort(urgent);
    await page.waitForFunction((t) => document.querySelector("[role=tabpanel]")?.innerText.includes(t), `of ${ledger.length} · most urgent first`);
    sentExp({ limit: "25", q: "ledger" }, "the search is the API's q");
    assert.deepEqual((await expRows(page)).map((r) => r[0]), ledger.map((r) => r.name));
    assert.equal(new URL(page.url()).hash, "#expiration?state=all&q=ledger", "the view is in the address");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("15 Expiration detail and extend: the API's row, the plan's approval and date, then a submit of exactly the planned body with If-Match and an Idempotency-Key", async () => {
    const { context, page, errors } = await expFresh();
    await manageExp(page, dated);
    const etag = api.state.etags.get(`${dated.clusterId}/${dated.name}`);
    assert.match(etag, /^[0-9a-f]{16}$/);
    const detail = panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: `${dated.name} on ${dated.clusterId}` }) });
    const kv = (await detail.locator(".pf-v6-c-description-list__group").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim());
    assert.deepEqual(kv, [`Expires ${dayOf(dated.expiresAt)} (${dated.expiresAt})`, `Days left ${dated.daysLeft}`, `Created ${dayOf(dated.created)}`, `Lifetime ${dated.lifetimeDays} of 180 days`,
      dated.noticesSent ? `Notices sent ${dated.noticesSent} of 3 (14, 7, 1 days)` : "Notices sent none yet", "After grace delete request (expired-namespace), then an operator confirms the prune"]);
    assert.match(await detail.innerText(), new RegExp(`GET /api/v1/clusters/${dated.clusterId}/namespaces/${dated.name} · ETag ${etag} · the date lives in Git as cmapi.net/expires-at`));
    assert.deepEqual((await expCard(page).getByRole("group", { name: "Action" }).getByRole("button").allInnerTexts()).map((t) => t.replace(/\s+/g, " ")),
      ["Extend 7 days +7", "Extend 14 days +14", "Extend 30 days +30, the most per step", "Make permanent adds approver-platform"]);
    // Submit with no plan plans first and writes nothing; the next Submit sends the plan that is on the page.
    await expCard(page).getByRole("group", { name: "Action" }).getByRole("button", { name: /^Extend 14 days/ }).click();
    const to = plus(dated.expiresAt, 14);
    assert.deepEqual((await expCard(page).locator("li").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim()).slice(0, 3),
      [`✓ Non-prod namespace dev allows expiration`, `✓ Extension within 30 days +14 days, to ${dayOf(to)}`, `✓ Lifetime within 180 days ${dated.lifetimeDays + 14} days from creation (${dayOf(dated.created)})`]);
    await expCard(page).getByRole("button", { name: "Extend", exact: true }).click();
    const approval = expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "No approval needed" });
    await approval.waitFor();
    assert.equal(expPosts(dated, "extend").filter((c) => c.query.dryRun !== "true").length, 0, "a change that was not planned is planned first");
    const [dry] = expPosts(dated, "extend");
    assert.deepEqual({ query: dry.query, ifMatch: dry.ifMatch, key: dry.key, body: dry.body }, { query: { dryRun: "true" }, ifMatch: `"${etag}"`, key: null, body: { days: 14 } });
    await expCard(page).locator("li").filter({ hasText: `The plan writes cmapi.net/expires-at: ${to}` }).waitFor();
    await expCard(page).locator("li").filter({ hasText: `If-Match matches the current ETag ${etag}` }).waitFor();
    await expCard(page).getByRole("button", { name: "Extend", exact: true }).click();
    const accepted = expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" });
    await accepted.waitFor();
    const writes = expPosts(dated, "extend").filter((c) => c.query.dryRun !== "true");
    assert.equal(writes.length, 1);
    assert.deepEqual(writes[0].body, dry.body, "the submitted body is the planned one");
    assert.equal(writes[0].ifMatch, `"${etag}"`);
    assert.match(writes[0].key, /^[0-9a-f-]{36}$/, "an Idempotency-Key that the portal made");
    assert.match(await accepted.innerText(), /202 Accepted · req-\d{8}-7001 · approved\s+Approved at once; the bot PR updates cmapi\.net\/expires-at when CI passes\./);
    assert.match(await expCard(page).locator(".pf-v6-c-code-block").innerText(), new RegExp(`POST /api/v1/clusters/${dated.clusterId}/namespaces/${dated.name}/expiration:extend[\\s\\S]*"expiresAt": "${to}"`));
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("15 Expiration: a date for a permanent namespace through :set, and make permanent through :makePermanent with its approval", async () => {
    {
      const { context, page, errors } = await expFresh();
      await manageExp(page, undated);
      assert.deepEqual((await expCard(page).getByRole("group", { name: "Action" }).getByRole("button").allInnerTexts()).map((t) => t.replace(/\s+/g, " ")), ["Set a date at most 30 days from today"]);
      const field = expCard(page).getByLabel("New expiry date");
      assert.deepEqual([await field.getAttribute("min"), await field.getAttribute("max"), await field.inputValue()], [plus(EXP_TODAY, 1), plus(EXP_TODAY, 30), plus(EXP_TODAY, 30)], "the rules' limits, from the API's day");
      const until = plus(EXP_TODAY, 12);
      await field.fill(until);
      await expCard(page).getByRole("button", { name: "Set expiry" }).click();
      await expCard(page).locator("li").filter({ hasText: `The plan writes cmapi.net/expires-at: ${until}` }).waitFor();
      await expCard(page).getByRole("button", { name: "Set expiry" }).click();
      await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
      const posts = expPosts(undated, "set");
      assert.deepEqual(posts.map((c) => [c.query.dryRun ?? "write", c.body]), [["true", { until }], ["write", { until }]]);
      assert.equal(expPosts(undated, "extend").length, 0, "a date for a permanent namespace is :set, not :extend");
      // A date that is not after today is refused by the page, and nothing is sent.
      await field.fill(EXP_TODAY);
      await expCard(page).getByRole("button", { name: "Set expiry" }).click();
      await expCard(page).locator("li").filter({ hasText: "Date must be tomorrow or later" }).waitFor();
      assert.equal(expPosts(undated, "set").length, 2);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await expFresh();
      await manageExp(page, dated);
      await actOf(page, "Make permanent");
      const approval = expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi from approver-platform" });
      await approval.waitFor();
      assert.match(await approval.innerText(), /threshold expirationBeyondLimits: \+1 approver-platform\. Nothing reaches Git until they approve\./);
      await expCard(page).locator("li").filter({ hasText: "The plan writes no cmapi.net/expires-at" }).waitFor();
      await expCard(page).getByRole("button", { name: "Request make permanent" }).click();
      const accepted = expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" });
      await accepted.waitFor();
      assert.match(await accepted.innerText(), /pending_approval\s+The approvers are notified; the expiry changes in Git once they approve\./);
      assert.deepEqual(expPosts(dated, "makePermanent").map((c) => [c.query.dryRun ?? "write", c.body]), [["true", {}], ["write", {}]]);
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("F3 Expiration: a 412 reads the namespace again and plans on its new ETag; Submit never sends the stale ETag again", async () => {
    const { context, page, errors } = await expFresh();
    expectedStatus = [412];
    const where = `${dated.clusterId}/${dated.name}`;
    const reads = () => api.state.seen.filter((c) => c.method === "GET" && c.path === `/api/v1/clusters/${dated.clusterId}/namespaces/${dated.name}`).length;
    const until = async (ok, why) => {
      const end = Date.now() + 5000;
      while (!ok()) {
        if (Date.now() > end) assert.fail(why());
        await page.waitForTimeout(50);
      }
    };
    await manageExp(page, dated);
    const old = api.state.etags.get(where);
    await actOf(page);
    await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "No approval needed" }).waitFor();
    const now = "0123456789abcdef";
    api.state.etags.set(where, now);
    const readsBefore = reads();
    await expCard(page).getByRole("button", { name: "Extend", exact: true }).click();
    await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "412 precondition-failed · nothing written" }).waitFor();
    const writes = () => expPosts(dated, "extend").filter((c) => c.query.dryRun !== "true");
    await until(() => reads() > readsBefore, () => `the namespace was not read again after the 412 (GETs: ${reads()})`);
    await until(() => expPosts(dated, "extend").some((c) => c.query.dryRun === "true" && c.ifMatch === `"${now}"`),
      () => `the change was not planned again on the new etag; the POSTs were ${JSON.stringify(expPosts(dated, "extend").map((c) => [c.query.dryRun ?? "write", c.ifMatch]))}`);
    await expCard(page).locator("li").filter({ hasText: `If-Match matches the current ETag ${now}` }).waitFor();
    await expCard(page).getByRole("button", { name: "Extend", exact: true }).click();
    await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
    assert.equal(writes().filter((c) => c.ifMatch === `"${old}"`).length, 1, "the stale etag was sent one time, never again");
    assert.equal(writes().at(-1).ifMatch, `"${now}"`);
    assert.ok(writes().every((c) => c.key === writes()[0].key), "the same body keeps its key across the new etag");
    assert.equal(api.state.created, 1);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("R7 Expiration: a double click sends one write; the same change after a lost answer keeps its key, a changed one gets a new key", async () => {
    {
      const { context, page, errors } = await expFresh();
      await manageExp(page, dated);
      await actOf(page);
      await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "No approval needed" }).waitFor();
      api.state.delayMs = 300;
      await expCard(page).locator("form").evaluate((form) => { form.requestSubmit(); form.requestSubmit(); });
      await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
      await page.waitForTimeout(800);
      const together = expPosts(dated, "extend").filter((c) => c.query.dryRun !== "true").length;
      console.log(`  expiry writes on two submits in one task: ${together}`);
      assert.equal(together, 1);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await expFresh();
      expectedStatus = [409];
      const route = `POST /api/v1/clusters/${dated.clusterId}/namespaces/${dated.name}/expiration:extend`;
      await manageExp(page, dated);
      await actOf(page);
      await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "No approval needed" }).waitFor();
      api.state.lose.add(route);
      await expCard(page).getByRole("button", { name: "Extend", exact: true }).click();
      await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "Not submitted" }).getByText(/Submit again: the same request is sent, and the API makes it at most once\./).waitFor();
      api.state.lose.clear();
      assert.equal(api.state.created, 1, "the lost answer's request was made");
      await expCard(page).getByRole("button", { name: "Extend", exact: true }).click();
      await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
      const writes = () => expPosts(dated, "extend").filter((c) => c.query.dryRun !== "true");
      assert.ok(writes().every((c) => c.key === writes()[0].key), "the retries of one change share one key");
      assert.equal(api.state.created, 1, "no second request");
      await actOf(page, "Extend 30 days");
      await expCard(page).locator("li").filter({ hasText: `The plan writes cmapi.net/expires-at: ${plus(dated.expiresAt, 30)}` }).waitFor();
      await expCard(page).getByRole("button", { name: "Extend", exact: true }).click();
      await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "409 change-pending · nothing written" }).waitFor();
      assert.notEqual(writes().at(-1).key, writes()[0].key, "a changed body is sent with a new key");
      assert.deepEqual(writes().at(-1).body, { days: 30 });
      assert.deepEqual(errors.filter((e) => !/net::ERR_EMPTY_RESPONSE/.test(e)), []);
      await context.close();
    }
  });

  await check("16 Expiration states: loading, empty, a 403, a 5xx with Try again, a stale cursor, a lock, a viewer, and an instance where nothing expires", async () => {
    {
      const { context, page, errors } = await expFresh();
      api.state.delayMs = 700;
      await page.goto(`${portal.page}#expiration`);
      await page.getByRole("status").filter({ hasText: "Loading expirations…" }).waitFor();
      await page.locator("table[aria-label=Expiration] tbody tr").first().waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await expFresh({ mode: "empty" });
      await open(page, "#expiration");
      await panel(page).getByText("No namespace matches this state and search.").waitFor();
      assert.match(await panel(page).innerText(), /0 namespaces/);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await expFresh();
      expectedStatus = [403];
      api.state.answers.push({ route: "GET /api/v1/expirations", status: 403, body: { type: "https://cmapi.ephico2real.com/problems/forbidden", title: "forbidden", status: 403, code: "forbidden", detail: "Missing permission objects:read: no role in your token grants it (roles: ['cmapi-none'])" } });
      await open(page, "#expiration?state=grace");
      await panel(page).getByRole("heading", { name: "You do not have permission to see expirations." }).waitFor();
      assert.match(await panel(page).innerText(), /Missing permission objects:read/);
      assert.equal(await panel(page).getByRole("button").count(), 0, "no action");
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await expFresh();
      expectedStatus = [500];
      api.state.answers.push({ route: "GET /api/v1/expirations", status: 500, body: { type: "https://cmapi.ephico2real.com/problems/internal-error", title: "internal-error", status: 500, code: "internal-error", detail: "The watch cache did not answer." } });
      await open(page, "#expiration?state=grace");
      const alert = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The expirations did not load." });
      await alert.waitFor();
      assert.match(await alert.innerText(), /The watch cache did not answer\./);
      await alert.getByRole("button", { name: "Try again" }).click();
      await page.locator("table[aria-label=Expiration] tbody tr").first().waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await expFresh();
      expectedStatus = [400];
      await openExp(page, "#expiration?state=all");
      api.state.answers.push({ route: "GET /api/v1/expirations", status: 400, body: { type: "https://cmapi.ephico2real.com/problems/invalid-cursor", title: "invalid-cursor", status: 400, code: "invalid-cursor", detail: "Filters or sort changed since this cursor was issued" } });
      await page.getByRole("button", { name: "Next ›" }).first().click();
      const stale = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "This page link is out of date" });
      await stale.waitFor();
      await stale.getByRole("button", { name: "Back to the first page" }).click();
      await page.waitForFunction((t) => document.querySelector("[role=tabpanel]")?.innerText.includes(t), `1–25 of ${expFleet.length}`);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // A namespace that a request holds: the lock, and its way to the request. No form.
      const held = { ...dated, openRequest: "req-20261116-0042" };
      const { context, page, errors } = await expFresh({ expirations: expFleet.map((r) => (r === dated ? held : r)) });
      await manageExp(page, held);
      const lock = expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "Open request: req-20261116-0042" });
      await lock.waitFor();
      assert.match(await lock.innerText(), /req-20261116-0042 holds this namespace in cmapi\. One open request per namespace, so another change waits until it closes\./);
      assert.equal(await expCard(page).getByRole("button", { name: "Plan change" }).count(), 0);
      await lock.getByRole("button", { name: "Open at current step" }).click();
      await page.waitForURL(/#workflow\?request=req-20261116-0042$/);
      assert.deepEqual(errors.filter((e) => !/status of 404/.test(e)), []);
      await context.close();
    }
    {
      // A viewer reads the list and the detail, and has no change form: the permission of :extend is not in /me.
      const { context, page, errors } = await expFresh({ user: "viewer" });
      await manageExp(page, dated);
      assert.equal(await panel(page).getByRole("heading", { name: /^Change expiration/ }).count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // An instance where no namespace can expire (prod): the API's rules are empty, and the mockup's prod callout shows.
      const { context, page, errors } = await expFresh({ never: true });
      await open(page, "#expiration");
      await panel(page).getByText("Production namespaces never expire").waitFor();
      assert.match(await panel(page).innerText(), /Expiration is optional for rnd, dev, qa and uat namespaces, and never applies in prod\.[\s\S]*nonprod · never expires/);
      assert.equal(await panel(page).locator("table").count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("17 Expiration: a role limited to rnd has the change form on an rnd namespace and not on a dev one", async () => {
    // docs/14, "environments": the API answers 403 environment-forbidden outside the role's environments, so the form is not shown there.
    const rndRow = [...expFleet].filter((r) => r.state === "active" && r.env === "rnd").sort(urgent)[0];
    const { context, page, errors } = await expFresh({ user: "rndRequester" });
    await manageExp(page, rndRow);
    await page.getByText("rnd.requester", { exact: true }).waitFor();
    await panel(page).getByRole("heading", { name: `Change expiration · ${rndRow.name}` }).waitFor();
    await manageExp(page, dated);
    await page.getByText("rnd.requester", { exact: true }).waitFor();
    const etag = api.state.etags.get(`${dated.clusterId}/${dated.name}`);
    await panel(page).getByText(new RegExp(`ETag ${etag}`)).waitFor();
    assert.equal(dated.env, "dev");
    assert.equal(await panel(page).getByRole("heading", { name: /^Change expiration/ }).count(), 0, "no form where the role does not reach");
    assert.equal(expPosts(dated, "extend").length, 0);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("6 the Expiration tab says what the mockup says, and adds only what is listed", async () => {
    const { context, page, errors } = await expFresh();
    const shown = [];
    await openExp(page);
    shown.push(...await shownText(page));
    await manageExp(page, dated);
    await actOf(page, "Make permanent");
    await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
    shown.push(...await shownText(page));
    await expCard(page).getByRole("button", { name: "Request make permanent" }).click();
    await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
    shown.push(...await shownText(page));
    await manageExp(page, undated);
    await expCard(page).getByRole("button", { name: "Set expiry" }).click();
    await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "No approval needed" }).waitFor();
    shown.push(...await shownText(page));
    await manageExp(page, { ...dated });
    api.state.mode = "empty";
    await panel(page).getByRole("group", { name: "Env" }).getByRole("button", { name: "dev", exact: true }).click();
    await panel(page).getByText("No namespace matches this state and search.").waitFor();
    shown.push(...await shownText(page));
    await context.close();
    // An instance where nothing expires: the mockup's prod card.
    const prod = await expFresh({ never: true });
    await open(prod.page, "#expiration");
    await panel(prod.page).getByText("Production namespaces never expire").waitFor();
    shown.push(...await shownText(prod.page));
    // The mockup's prod card names sample policies and clusters; its detail has an Extensions count that the API does not give,
    // a footnote on GET .../expiration (not built) and expire_check (not built), and a lede that names platform-leads.
    const MOCKUP_ONLY = ["Extensions"];
    const fromMockup = mockupBlock("isExpiration", "isRequests").filter((t) => !MOCKUP_ONLY.includes(t));
    const data = [...expFleet.flatMap((r) => [r.name, r.clusterId, r.env, r.team])].filter(Boolean);
    // The mockup's logic builds these (expirationView()).
    const FROM_LOGIC = [/^\d+$/, /^-\d+ \(grace \d+ left\)$/, /^[A-Z][a-z]{2} \d{1,2}$/, /^[A-Z][a-z]{2} \d{1,2} \(\d{4}-\d{2}-\d{2}\)$/, /^\d+ of 180 d(ays)?$/, /^\d+–\d+ of \d+ · most urgent first$/,
      /^\d+ expiring · \d+ in grace · \d+ pending delete$/, /^[a-z-]+ on [A-Z_]+$/, /^Change expiration · [a-z-]+$/, /^(dev|rnd) · [A-Z_]+$/, /^(dev|rnd) allows expiration$/, /^\+\d+ days, to [A-Z][a-z]{2} \d{1,2}$/,
      /^\d+ days from creation \([A-Z][a-z]{2} \d{1,2}\)$/, /^Extension within 30 days$/, /^Lifetime within 180 days$/, /^Extend \d+ days$/, /^\+\d+(, the most per step)?$/, /^\d+ approvals? in cmapi from /,
      /^202 Accepted · req-\d{8}-\d{4} · (pending_approval|approved)$/, /^POST \/api\/v1\/clusters\/[A-Z_]+\/namespaces\/[a-z-]+\/expiration:(extend|set|makePermanent) \{/, /^past the date; \d+ grace days left$/, /^Open request: req-\d{8}-\d+$/, /^[✓!✕]$/, /^\d+ of 3 \(14, 7, 1 days\)$/,
      /^\{|^"|^\}|^\]|^\[/, /^\d{4}-\d{2}-\d{2}$/];
    const LOGIC = ["Needs action", "Expiring ≤ 14 d", "In grace", "Pending delete", "Active", "Permanent", "Expiring", "All", "Selected", "Manage", "never", "—", "never (permanent)", "none yet",
      "delete request (expired-namespace), then an operator confirms the prune", "nothing: permanent", "Expires", "Days left", "Created", "Lifetime", "Notices sent", "After grace",
      "Make permanent", "Set a date", "Non-prod namespace", "Removes cmapi.net/expires-at and cmapi.net/expiry", "No open request on the namespace", "Request make permanent", "Set expiry", "Extend",
      "No approval needed", "The approvers are notified; the expiry changes in Git once they approve.", "Approved at once; the bot PR updates cmapi.net/expires-at when CI passes.", "0 namespaces",
      "New expiry date", "Action", "Expiration is optional for rnd, dev, qa and uat namespaces, and never applies in prod."];
    // The portal's own words, each in MOCKUP-CONTRACT.md.
    const ADDED = ["Plan change", "Planning…", "If-Match matches the current ETag", "The plan writes", /^cmapi\.net\/expires-at: \d{4}-\d{2}-\d{2}$/, "no cmapi.net/expires-at", "adds approver-platform",
      /^at most 30 days from today$/, /^-\d+ \(grace over\)$/, /^[0-9a-f]{16}$/, /^GET \/api\/v1\/expirations\?[\w=&-]+ · paged and searched like Quotas · today is [A-Z][a-z]{2} \d{1,2}\.$/,
      /^GET \/api\/v1\/clusters\/[A-Z_]+\/namespaces\/[a-z-]+ · ETag [0-9a-f]{16} · the date lives in Git as cmapi\.net\/expires-at; this list reads it from the watch cache\.$/,
      /^Every namespace on the nonprod instance that has, or could have, an expiry date\. Expiry is optional and prod never has it\. Extend in steps of up to 30 days, up to 180 days from creation; past that, or to make a namespace permanent, approver-platform approves\. Notices go out at 14, 7 and 1 days, a 7-day grace follows the date, and then cmapi opens a delete request that an operator confirms\.$/,
      /^dev change: 0 from approver-platform; threshold expirationBeyondLimits: \+1 approver-platform\. Nothing reaches Git until they approve\.$/, /^dev change: 0 from approver-platform\. The bot PR merges when CI passes\.$/,
      /^nonprod · never expires$/, /^req-\d{8}-\d+ holds this namespace in cmapi\. One open request per namespace, so another change waits until it closes\.$/, "Open at current step", "rnd", "dev", "nonprod", "approver-platform", "Search input", "Reset", "Used of hard"];
    const strings = [...data, ...LOGIC, ...ADDED].filter((k) => typeof k === "string");
    const patterns = [...FROM_LOGIC, ...ADDED].filter((k) => k instanceof RegExp);
    const n = compare("Expiration", fromMockup, shown, [...strings, ...LIBRARY], patterns);
    console.log(`  strings of the mockup compared on the Expiration tab: ${n}`);
    assert.deepEqual([...errors, ...prod.errors], []);
    await prod.context.close();
  });

  await check("7 the Expiration tab at 390, 820 and 1440 px in each theme, and axe at phone and desktop width", async () => {
    const VIEWS = [
      ["expiration", async (page) => {
        await manageExp(page, dated);
        await actOf(page, "Make permanent");
        await expCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
      }],
      ["expiration-set", async (page) => { await manageExp(page, undated); await expCard(page).getByLabel("New expiry date").waitFor(); }],
      ["expiration-list", async (page) => { await openExp(page, "#expiration?state=all"); }]
    ];
    let scans = 0;
    for (const [view, reach] of VIEWS) {
      for (const width of [390, 820, 1440]) {
        const { context, page, errors } = await expFresh({ width });
        await reach(page);
        for (const theme of ["light", "dark"]) {
          await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
          for (let round = 0; round < 5 && (round === 0 || await running(page)); round++) await settled(page);
          assert.equal(await running(page), 0, `${view} ${width} ${theme}: no colour transition still runs when the page is read`);
          const layout = await page.evaluate(() => {
            const main = document.querySelector(".pf-v6-c-page__main-container") ?? document.documentElement;
            return { doc: document.documentElement.scrollWidth - document.documentElement.clientWidth, main: main.scrollWidth - main.clientWidth, text: document.body.innerText };
          });
          assert.ok(layout.doc <= 0 && layout.main <= 0, `${view} ${width} ${theme}: no sideways scroll (${layout.doc}, ${layout.main})`);
          assert.doesNotMatch(layout.text, /\{\{|undefined|NaN|\[object/, `${view} ${width} ${theme}: no leftover placeholder`);
          await page.screenshot({ path: join(out, `${view}-${width}-${theme}.png`), fullPage: true });
          if (width !== 820) {
            const scan = await new AxeBuilder({ page }).analyze();
            scans++;
            assert.deepEqual(scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.html}`), [], `axe on ${view} at ${width} ${theme}`);
          }
        }
        assert.deepEqual(errors, []);
        await context.close();
      }
    }
    console.log(`  ${VIEWS.length} views, 3 widths, 2 themes, ${scans} axe scans`);
  });

  // The KPIs of a pod: the recorded answer with the cgroup figures that a container has (the sample was recorded on macOS).
  const recordedKpi = SAMPLES.operations.admin_kpi.response.body;
  const podKpi = { ...recordedKpi, components: [{ ...recordedKpi.components[0], memoryBytes: 612 * 2 ** 20, memoryLimitBytes: 2 ** 30, cpuUsageSeconds: 412.6, cpuLimitCores: 2,
    cpuPeriods: 1000, cpuThrottledPeriods: 16, cpuThrottledSeconds: 0.8, measuredAt: Date.parse("2026-11-15T17:30:12Z") / 1000 }],
    // The sizes are pinned like the rest: a recorded run's database size and WAL differ from run to run (test_api_samples.py).
    database: { ...recordedKpi.database, connections: 90, sizeBytes: 10117647, walBytes: 80 * 2 ** 20 } };
  const kpiCards = (page) => panel(page).locator(".pf-v6-l-gallery > .pf-v6-c-card").filter({ has: page.locator("h3") }).evaluateAll((cards) => cards.map((c) => c.innerText.replace(/\s+/g, " ").trim()));
  // The mockup's forms of a KPI value: "6 min", "9.5 h", "84%", and "unavailable" for one that is not measured.
  const kpiText = (k) => (k.value === null ? "unavailable" : k.unit === "ratio" ? `${one(k.value * 100)}%` : k.value < 60 ? `${one(k.value)} s` : k.value < 3600 ? `${one(k.value / 60)} min` : `${one(k.value / 3600)} h`);

  await check("13 KPIs: the operator's tab shows GET /api/v1/admin/kpi: the process, the database, each live KPI; a null is unavailable; the thresholds mark a watch", async () => {
    const { context, page, errors } = await fresh({ user: "operator", kpi: podKpi });
    await open(page, "#kpis");
    await panel(page).getByRole("heading", { name: "cmapi-api" }).waitFor();
    assert.equal(calls("/api/v1/admin/kpi").length, 1);
    const system = panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: "System status · each component's own cgroup" }) }).first();
    const api1 = system.locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: "cmapi-api" }) });
    const text = (await api1.innerText()).replace(/\s+/g, " ");
    assert.match(text, /^watch cmapi-api 412\.6 s of CPU since the container started · limit 2 cores · measured at 17:30:12/);
    assert.match(text, /Memory 60% · 612 MiB of 1 GiB CPU unavailable Throttled 1\.6% of periods \(limit 1%\) Event-loop lag p99 unavailable watch: throttled 1\.6% > 1%/);
    const meters = await api1.locator("[role=progressbar]").evaluateAll((bars) => bars.map((b) => b.getAttribute("aria-valuenow")));
    assert.deepEqual(meters, ["60", "0", "40", "0"], "memory 60%; throttling at four times its share, as the mockup draws it; nothing for what is not measured");
    const db = panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: "Database · PostgreSQL, schemas cmapi and capacity" }) });
    assert.match((await db.innerText()).replace(/\s+/g, " "), /^watch Database · PostgreSQL, schemas cmapi and capacity Connections 90 of 100 \(max_connections\) Volume unavailable Size 10 MiB · WAL 80 MiB Pools 0 in use of 5 Oldest transaction 0 s Volume trend unavailable Last backup unavailable: no backup tool reports for this database yet \(open question\), so Backup freshness shows unavailable rather than 0 watch: connections 90% > 80%/);
    assert.match(await system.innerText(), /2 to watch · updated 17:30:12/, "the process and the database are each one to watch");
    assert.deepEqual(await kpiCards(page), recordedKpi.kpis.map((k) => `${k.name} target ${k.targetStatus} ${kpiText(k)} Target: ${k.target} ${k.source}`), "each live KPI of the API, in its order");
    assert.ok((await kpiCards(page)).some((c) => c.includes(" unavailable ")), "a KPI with no value reads unavailable, never 0");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("13 KPIs states: loading, a 403 with no action, a 5xx with Try again; the requester has no KPIs tab", async () => {
    {
      const { context, page, errors } = await fresh({ user: "operator" });
      api.state.delayMs = 700;
      await page.goto(`${portal.page}#kpis`);
      await page.getByRole("status").filter({ hasText: "Loading the KPIs…" }).waitFor();
      await panel(page).getByRole("heading", { name: "cmapi-api" }).waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ user: "operator" });
      expectedStatus = [403];
      api.state.answers.push({ route: "GET /api/v1/admin/kpi", status: 403, body: { type: "https://cmapi.ephico2real.com/problems/forbidden", title: "forbidden", status: 403, code: "forbidden", detail: "Missing permission reports:read: no role in your token grants it (roles: ['cmapi-operator'])" } });
      await open(page, "#kpis");
      await panel(page).getByRole("heading", { name: "You do not have permission to see the KPIs." }).waitFor();
      assert.match(await panel(page).innerText(), /Missing permission reports:read/);
      assert.equal(await panel(page).getByRole("button").count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ user: "operator" });
      expectedStatus = [500];
      api.state.answers.push({ route: "GET /api/v1/admin/kpi", status: 500, body: { type: "https://cmapi.ephico2real.com/problems/internal-error", title: "internal-error", status: 500, code: "internal-error", detail: "The database did not answer." } });
      await open(page, "#kpis");
      const alert = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The KPIs did not load." });
      await alert.waitFor();
      assert.match(await alert.innerText(), /The database did not answer\./);
      await alert.getByRole("button", { name: "Try again" }).click();
      await panel(page).getByRole("heading", { name: "cmapi-api" }).waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ user: "requester" });
      await page.goto(`${portal.page}#kpis`);
      await page.locator("[role=tablist]").waitFor();
      assert.equal(await page.getByRole("tab", { name: "KPIs" }).count(), 0);
      assert.equal(await page.getByRole("tab", { selected: true }).innerText(), "Workflow");
      assert.equal(calls("/api/v1/admin/kpi").length, 0, "no call that the person cannot make");
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("6 the Quotas and KPIs tabs say what the mockup says, and add only what is listed", async () => {
    const counts = {};
    {
      const { context, page, errors } = await quotaFresh();
      const shown = [];
      await manage(page, target);
      shown.push(...await shownText(page));
      // The type-ahead, open with its matches, and with none.
      const box = page.getByRole("combobox", { name: "Find a namespace, team or app" });
      await box.fill("pay");
      await page.locator("#q-sug [role=option]:not([aria-disabled=true])").first().waitFor();
      shown.push(...await shownText(page));
      await box.fill("zzz");
      await page.getByRole("listbox").getByText('No namespace matches "zzz".').waitFor();
      shown.push(...await shownText(page));
      await box.press("Escape");
      await box.fill("ledger");
      await panel(page).getByRole("button", { name: "Show all matches" }).click();
      await panel(page).getByRole("button", { name: 'matching "ledger" ✕' }).waitFor();
      shown.push(...await shownText(page));
      await panel(page).getByRole("button", { name: 'matching "ledger" ✕' }).click();
      // The export, the plan, a custom size, the same size and the 202.
      await panel(page).getByRole("button", { name: "Export CSV" }).click();
      await panel(page).getByRole("link", { name: "Download" }).waitFor();
      shown.push(...await shownText(page));
      await panel(page).getByRole("button", { name: "Close" }).click();
      await manage(page, target);
      await planOf(page);
      await changeCard(page).getByText("The new size equals the current quota; pick another tier or custom values.").waitFor();
      shown.push(...await shownText(page));
      await changeCard(page).getByRole("group", { name: "New size" }).getByRole("button", { name: /^custom/ }).click();
      shown.push(...await shownText(page));
      await planOf(page, "medium");
      await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
      shown.push(...await shownText(page));
      await changeCard(page).getByRole("button", { name: "Submit change" }).click();
      await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "202 Accepted" }).waitFor();
      shown.push(...await shownText(page));
      // A namespace that a request holds, and a stale cursor.
      await manage(page, locked);
      await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "Change in progress" }).waitFor();
      shown.push(...await shownText(page));
      expectedStatus = [400];
      api.state.answers.push({ route: "GET /api/v1/quotas", status: 400, body: { type: "https://cmapi.ephico2real.com/problems/invalid-cursor", title: "invalid-cursor", status: 400, code: "invalid-cursor", detail: "Filters or sort changed" } });
      await page.getByRole("button", { name: "Next ›" }).first().click();
      await panel(page).getByText("This page link is out of date").waitFor();
      shown.push(...await shownText(page));
      // No namespace matches.
      api.state.mode = "empty";
      await panel(page).getByRole("group", { name: "Env" }).getByRole("button", { name: "dev", exact: true }).click();
      await panel(page).getByText("No namespace on the nonprod instance matches these filters.").waitFor();
      shown.push(...await shownText(page));
      // The mockup's usage analysis, recommendation and live usage: the API has none (#310). Its footnote, lede and hint name them.
      const MOCKUP_ONLY = ["Verdict", "Usage verdict", "Recommendation", "Use this size", "/quota · ETag", "Live usage · last 14 days", "Resource", "Now", "7d avg", "p95", "Peak", "Quota", "New / peak",
        "Read live from", "'s Thanos by cmapi-capacity for this plan; cached 10 minutes and not stored. Cluster headroom comes from the 17:00 snapshot, committed quota and reservations, with no Thanos call.",
        "instance, read live from cmapi's watch cache of each cluster. Used is what pods have requested, not what they consume; real usage is read from Thanos only when you plan a change.",
        "Quota status from the watch cache, verdicts from the 02:00 usage sweep; no Thanos call. Pages follow a cursor on the sort key, so namespaces created or deleted between pages never cause a skip or a repeat. Bars turn amber at 80% and red at 95% of the hard limit.",
        "A tier changes one label and the operator re-stamps the quota (PATCH …/namespaces/{ns}). Custom sets requests.cpu and requests.memory directly (PATCH …/namespaces/{ns}/quota)."];
      const fromMockup = mockupBlock("isQuotas", "isExpiration").filter((t) => !MOCKUP_ONLY.includes(t));
      const data = [...fleet.flatMap((r) => [r.name, r.clusterId, r.env, r.tier, r.openRequest].filter(Boolean)), "rnd", "dev", "nonprod", "small", "medium", "large", "custom", "CRC", "pay", "zzz", "ledger",
        ...SAMPLES.operations.namespaces_update_namespace.response.body.approval.reasons, "approver-platform", "dev-change", "pending_approval", locked.openRequest];
      // The mockup's logic builds these (quotaView()): chips, sizes, range, pager call, detail, change, the 202 and the export.
      // A letter button is matched whole: as a known text, each letter would erase every other text from the check.
      const FROM_LOGIC = [/^\d+$/, /^[a-z]$/, /^\d+(\.\d+)? \/ \d+( cores| Gi)?$/, /^\d+(\.\d+)?( cores| Gi)?$/, /^\d+%$/, /^\d+–\d+ of \d+( \(filtered from \d+\))? · (A–Z|most used first|most urgent first)$/, /^GET \/api\/v1\/quotas\?/,
        /^[A-Z]: \d+ namespaces?$/, /^\d+ cores · \d+Gi( · current)?$/, /^[a-z-]+ on [A-Z_]+$/, /^(dev|rnd) · tier [a-z]+ · ResourceQuota [a-z-]+-quota · read from the watch cache, current to the second$/,
        /^GET \/api\/v1\/clusters\/[A-Z_]+\/namespaces\/[a-z-]+ · ETag [0-9a-f]{16} · ResourceQuota and LimitRange for tier [a-z]+ live in the namespace folder in Git\.$/, /^Change quota · [a-z-]+$/, /^(dev|rnd) · [A-Z_]+$/,
        /^202 Accepted · req-\d{8}-\d{4} · pending_approval$/, /^quotas-nonprod-\d{4}-\d{2}-\d{2}\.csv · \d+ rows$/, /^GET \/api\/v1\/quotas:export streams every row matching the current filters, not only this page, in the current sort order\. Capped at 10,000 rows and recorded in the audit log\.$/,
        /^Change in progress: req-\d{8}-\d+$/, /^[✓!✕]$/, /^[a-z]+ in \[rnd, dev\]$/, /^[0-9a-f]{16}$/, /^\d+ approvals? in cmapi from /, /^No namespace matches "[a-z]+"\.$/, /^matching "[a-z]+" ✕$/];
      const LOGIC = ["requests.cpu", "requests.memory", "pods", "requests.cpu used of hard", "requests.memory used of hard", "pods used of hard", "Selected", "Manage", "All", "Name A–Z", "% used", "Needs attention", "Near limit ≥ 80%", "Open request", "set cpu and memory", "Environment served", "If-Match matches the current ETag",
        "Waiting for 1 approval in cmapi (approver-platform). The approvers are notified; nothing is written to Git until the count is met.", "0 namespaces", "Change in progress", "—", "25", "50", "100"];
      // The portal's own words, each in MOCKUP-CONTRACT.md.
      const ADDED = ["Attention", "Searching…", "…", "near-limit", "open-request", "tier-outdated", "Tier outdated", "Download", "Matching namespaces", "Planning…", "Approval", "Capacity on CRC", /^fits on fresh data · cpu \d+% · memory \d+% · binds on cpu$/,
        /^\d+ namespaces in scope · \d+ near the limit$/, "instance, read live from cmapi's watch cache of each cluster. Used is what pods have requested, not what they consume.",
        "Quota status from the watch cache; no Thanos call. Pages follow a cursor on the sort key, so namespaces created or deleted between pages never cause a skip or a repeat. Bars turn amber at 80% and red at 95% of the hard limit.",
        "A tier changes one label and the operator re-stamps the quota (PATCH …/namespaces/{ns}). Custom sets requests.cpu and requests.memory directly, in the same PATCH.",
        /^req-\d{8}-\d+ holds this namespace in cmapi\. cmapi holds one open request per namespace, so another change is refused with 409 change-pending until this one closes\.$/,
        /^dev change: 0 from approver-platform; threshold quotaIncreasePct > 100: \+1 approver-platform\. Nothing reaches Git until they approve\. Self-approval is allowed in dev\.$/,
        /^GET \/api\/v1\/quotas:export(\?[a-zA-Z=&-]+)? streams every row/, /^(name,clusterId|[a-z-]+,CRC,|… \d+ more rows)/, /^\{|^"|^\}|^\]|^\[/, "Used of hard", "Action"];
      const strings = [...data, ...LOGIC, ...ADDED].filter((k) => typeof k === "string");
      const patterns = [...FROM_LOGIC, ...ADDED].filter((k) => k instanceof RegExp);
      counts.quotas = compare("Quotas", fromMockup, shown, [...strings, ...LIBRARY], patterns);
      assert.deepEqual(errors.filter((e) => !/status of 400/.test(e)), []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ user: "operator", kpi: podKpi });
      await open(page, "#kpis");
      await panel(page).getByRole("heading", { name: "cmapi-api" }).waitFor();
      const shown = await shownText(page);
      const mockup = readFileSync(join(app, "..", "mockups", "portal", "Main.dc.html"), "utf8");
      const block = mockup.slice(mockup.indexOf('<sc-if value="{{isKpis}}"'), mockup.indexOf('<p class="foot">Mockup with example data'));
      const texts = [...new Set(block.replace(/<[^>]+>/g, "\n").split(/\n|\{\{[^}]+\}\}/).map((t) => t.replace(/\s+/g, " ").trim()).filter(Boolean))];
      // The mockup's 30-day window, its event loop and recording rules, its worker's 30 s measure and its dashboards: the API has none (MOCKUP-CONTRACT.md).
      const MOCKUP_ONLY = ["instance's KPI board: first whether cmapi itself has room (each component's memory, CPU, throttling and event loop, and the database), then the service KPIs from the recording rules over the last 30 days. The page and /metrics read the same collectors, so they cannot disagree.",
        "30 days ·", "Measured every 30 s by the worker that holds the discovery lock (pg_monitor role); volume fill from kubelet_volume_stats through the hub's Thanos. A value nothing reports reads unavailable, never 0.",
        "Dashboards · OpenShift console, Observe › Dashboards (Perses) · eight per instance", "Dashboard", "PersesDashboard", "Shows", "cmapi/",
        "Shipped by the Helm chart as PersesDashboards in the cmapi namespace, reading the hub's Thanos Querier. Sites that use Grafana set dashboards.provider to grafana or both."];
      const fromMockup = texts.filter((t) => !MOCKUP_ONLY.includes(t));
      const data = ["nonprod", "cmapi-api", ...recordedKpi.kpis.flatMap((k) => [k.name, k.target, k.source, kpiText(k)]), recordedKpi.unavailable];
      // The mockup's logic builds these (systemView(), meterOf(), kpi()).
      const FROM_LOGIC = [/^\d+ to watch · updated \d{2}:\d{2}:\d{2}$/, /^all healthy · updated \d{2}:\d{2}:\d{2}$/, /^\d+% · \d+ MiB of \d+(\.\d)? GiB$/, /^\d+\.\d% of periods \(limit \d+%\)$/, /^\d+ of \d+ \(max_connections\)$/,
        /^watch: [a-z ]+ \d+(\.\d)?% > \d+%(, [a-z ]+ \d+(\.\d)?% > \d+%)*$/, /^Target: /];
      const LOGIC = ["healthy", "watch", "within every threshold", "Memory", "CPU", "Throttled", "Event-loop lag p99", "Connections", "Volume", "unavailable", "Pools", "Oldest transaction", "Volume trend", "Last backup",
        "unavailable: no backup tool reports for this database yet (open question), so Backup freshness shows unavailable rather than 0", "backup unavailable",
        "Thresholds from kpi.thresholds: memory and CPU 80% of the limit, throttling 1% of periods (the saturation signal: a pod can be throttled while CPU still reads as headroom). The black tick on each bar is the threshold."];
      // The portal's own words, each in MOCKUP-CONTRACT.md.
      const ADDED = ["instance's KPI board: first whether cmapi itself has room (the memory, CPU and throttling of the process that answered, and the database), then the service KPIs that cmapi computes from its database. The page and /metrics read the same collectors, so they cannot disagree.",
        "Size", /^\d+ MiB · WAL \d+ MiB$/, /^\d+ in use of \d+$/, /^\d+(\.\d)? s$/, /^target (proposed|agreed)$/, /^\d+(\.\d)? s of CPU since the container started · limit \d+ cores · measured at \d{2}:\d{2}:\d{2}$/,
        "Measured by the process that answered, when the page asked. A value nothing reports reads unavailable, never 0."];
      const strings = [...data, ...LOGIC, ...ADDED].filter((k) => typeof k === "string");
      const patterns = [...FROM_LOGIC, ...ADDED].filter((k) => k instanceof RegExp);
      counts.kpis = compare("KPIs", fromMockup, shown, [...strings, ...LIBRARY], patterns);
      assert.deepEqual(errors, []);
      await context.close();
    }
    console.log(`  strings of the mockup compared: ${JSON.stringify(counts)}`);
  });

  await check("7 the Quotas and KPIs tabs at 390, 820 and 1440 px in each theme, and axe at phone and desktop width", async () => {
    const VIEWS = [
      ["quotas", "requester", async (page) => {
        await manage(page, target);
        await planOf(page, "medium");
        await changeCard(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
      }],
      ["quotas-typeahead", "requester", async (page) => {
        // The type-ahead's list is a state that opens on typing: it is scanned too.
        await openQuotas(page);
        await page.getByRole("combobox", { name: "Find a namespace, team or app" }).fill("pay");
        await page.locator("#q-sug [role=option]:not([aria-disabled=true])").first().waitFor();
      }],
      ["quotas-export", "requester", async (page) => {
        await openQuotas(page);
        await panel(page).getByRole("button", { name: "Export CSV" }).click();
        await panel(page).getByRole("link", { name: "Download" }).waitFor();
      }],
      ["kpis", "operator", async (page) => { await open(page, "#kpis"); await panel(page).getByRole("heading", { name: "cmapi-api" }).waitFor(); }]
    ];
    let scans = 0;
    for (const [view, user, reach] of VIEWS) {
      for (const width of [390, 820, 1440]) {
        const { context, page, errors } = await quotaFresh({ user, width, kpi: podKpi });
        await reach(page);
        for (const theme of ["light", "dark"]) {
          await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
          for (let round = 0; round < 5 && (round === 0 || await running(page)); round++) await settled(page);
          assert.equal(await running(page), 0, `${view} ${width} ${theme}: no colour transition still runs when the page is read`);
          const layout = await page.evaluate(() => {
            const main = document.querySelector(".pf-v6-c-page__main-container") ?? document.documentElement;
            return { doc: document.documentElement.scrollWidth - document.documentElement.clientWidth, main: main.scrollWidth - main.clientWidth, text: document.body.innerText };
          });
          assert.ok(layout.doc <= 0 && layout.main <= 0, `${view} ${width} ${theme}: no sideways scroll (${layout.doc}, ${layout.main})`);
          assert.doesNotMatch(layout.text, /\{\{|undefined|NaN|\[object/, `${view} ${width} ${theme}: no leftover placeholder`);
          await page.screenshot({ path: join(out, `${view}-${width}-${theme}.png`), fullPage: true });
          if (width !== 820) {
            const scan = await new AxeBuilder({ page }).analyze();
            scans++;
            assert.deepEqual(scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.html}`), [], `axe on ${view} at ${width} ${theme}`);
          }
        }
        assert.deepEqual(errors, []);
        await context.close();
      }
    }
    console.log(`  ${VIEWS.length} views, 3 widths, 2 themes, ${scans} axe scans`);
  });

  await check("sign out ends the session at the issuer", async () => {
    const { context, page, errors } = await fresh();
    await open(page);
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.waitForURL((url) => url.href.startsWith(AUTH));
    const logout = issuer.state.seen.find((s) => s.what === "logout");
    assert.ok(logout, "the browser went to the end-session endpoint");
    assert.equal(logout.query.post_logout_redirect_uri, portal.page);
    assert.equal(logout.method, "POST", "a form POST, as OpenID Connect RP-Initiated Logout 1.0 permits");
    assert.equal(logout.url, "/realms/cmapi/protocol/openid-connect/logout", "no query: no token is in the logout URL");
    assert.match(logout.query.id_token_hint, /^[\w-]+\.[\w-]+\.[\w-]+$/, "the ID token is the hint, in the body, so the issuer asks no question");
    assert.equal(logout.query.client_id, "cmapi-portal");
    assert.deepEqual(errors, []);
    await context.close();
  });

  console.log(`ok - portal on the API: ${done.length} checks, ${browser.browserType().name()} ${browser.version()}`);
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  // A check that timed out can still hold the browser: do not wait for it longer than this.
  await Promise.race([browser.close(), new Promise((resolve) => setTimeout(resolve, 5000))]);
  portal.close();
  api.close();
  issuer.close();
  // The servers keep their sockets open for a moment. The result is known, so end now.
  process.exit(process.exitCode ?? 0);
}
