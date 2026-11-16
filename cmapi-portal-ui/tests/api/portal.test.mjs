#!/usr/bin/env node
// The portal on the API (issue #204), against the built portal (dist/), a stand-in issuer and a stand-in API.
// Stage: built-mocked. It proves what the browser does. It does not prove a sign-in on a real Keycloak or a call to
// the real service. PW_CHANNEL=chrome runs it in the installed Chrome, and PW_HEADED=1 shows the window.
import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { AxeBuilder } from "@axe-core/playwright";
import { chromium } from "playwright";
import { requestsFrom, requestWith, SAMPLES, servePortal, startApi, startIssuer, USERS } from "./standin.mjs";

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
async function fresh({ user = "requester", items = sixtyOne, mode = "ok", width = 1440 } = {}) {
  issuer.state.user = user && USERS[user];
  issuer.state.sessions = true;
  issuer.state.lifetime = 300;
  Object.assign(api.state, { mode, items, delayMs: 0, seen: [], answers: [], lose: new Set(), keys: new Map(), created: 0, clusters: SAMPLES.operations.core_clusters.response.body.items,
    tiers: SAMPLES.operations.tiers_tiers.response.body, plan: SAMPLES.operations["namespaces_create_namespace:dryRun"].response.body });
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

  await check("5 a role sees the tabs that GET /api/v1/me permits: a viewer, an approver, a requester", async () => {
    // The stand-in's access token is an opaque string, so the browser cannot read a role from it.
    const base = ["Workflow", "Quotas", "Expiration", "Requests", "Policies", "Capacity"];
    const want = {
      viewer: base,
      approver: ["Workflow", "Quotas", "Expiration", "Requests", "Approvals", "Policies", "Capacity"],
      requester: ["Workflow", "New namespace", "Quotas", "Expiration", "Requests", "Policies", "Capacity"]
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
    await page.getByLabel("Team", { exact: true }).fill(team);
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
        await page.getByLabel("Team", { exact: true }).fill("payments");
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
      // The portal's own words, each in MOCKUP-CONTRACT.md: the cluster field until placement is on the API (#303), and the approval before a dry run.
      const ADDED = ["Cluster", "The dev clusters that take writes, from GET /api/v1/clusters. Placement is not on the API yet (#303).",
        "The prod clusters that take writes, from GET /api/v1/clusters. Placement is not on the API yet (#303).",
        "The cluster is your choice until placement is on the API (#303). The dry run checks its capacity.", "Not planned yet", "Dry run asks the API which approval applies.",
        /^(dev|prod) · us-central · connected$/, /^cpu \d+% · memory \d+% · binds on (cpu|memory)$/, "clusters/CRC/namespaces/payments-dev/"];
      const strings = [...data, ...LOGIC, ...ADDED].filter((k) => typeof k === "string");
      const patterns = [...FROM_LOGIC, ...data, ...ADDED].filter((k) => k instanceof RegExp);
      const MOCKUP_ONLY = [];
      const fromMockup = mockupBlock("isNew", "isQuotas").filter((t) => !MOCKUP_ONLY.includes(t));
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
      }]
    ];
    let scans = 0;
    for (const [tab, user, items, reach] of VIEWS) {
      for (const width of [390, 820, 1440]) {
        const { context, page, errors } = await fresh({ user, items, width });
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
