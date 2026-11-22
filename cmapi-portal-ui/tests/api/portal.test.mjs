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
import { checkComboBoxLifecycle } from "../combobox.mjs";
import { capacityFleet, capacityGroups, COMPANY_KEYS, expirationsFrom, KEYS_479, heldPageRows, namespacesOfMockup, policyCluster, policyFleet, policyFleetWith, policyRowsFrom, quotaCsv, quotaQueryOf, quotasFrom, quotaSuggest,
  recordEtag, REFERENCE_KEYS, rejectionsFrom, requestsFrom, requestWith, SAMPLES, servePortal, startApi, startIssuer, syncRecord, USERS } from "./standin.mjs";

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
  expirations = [], never = false, metadataKeys = REFERENCE_KEYS, policies = policyFleet(), rejections = rejectionsFrom(3), capacity = capacityFleet(), namespaces = [],
  clusters = SAMPLES.operations.core_clusters.response.body.items } = {}) {
  issuer.state.user = user && USERS[user];
  issuer.state.sessions = true;
  issuer.state.lifetime = 300;
  Object.assign(api.state, { mode, items, delayMs: 0, hold: null, seen: [], answers: [], lose: new Set(), keys: new Map(), created: 0, clusters, namespaces,
    tiers: SAMPLES.operations.tiers_tiers.response.body, plan: SAMPLES.operations["namespaces_create_namespace:dryRun"].response.body, quotas, etags: new Map(), kpi,
    expirations, never, today: SAMPLES.operations.expiration_expirations.response.body.today, metadataKeys, protection: new Map(), policies, rejections, capacity, notModified: 0 });
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
/**
 * The options of an open list that are not the element at their own centre (document.elementFromPoint): shown in the DOM
 * but hidden on the screen, for example by a card that clips its overflow (#535). An empty array is every option seen.
 */
const hiddenOptions = (page, list) => page.evaluate((list) => [...document.querySelectorAll(`${list} [role=option]`)].filter((option) => {
  const box = option.getBoundingClientRect();
  const at = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  return !at || !option.contains(at);
}).map((option) => option.innerText.split("\n")[0]), list);
const tabNames = (page) => page.getByRole("tab").allInnerTexts();

// Start on a middle page so that both cursors would work with the old answer.
async function checkHeldPage(page, { label, path, change, match, after, lastPage = false }) {
  // PatternFly renders these tables with role="grid", so a role="table" query matches none of them: find it by its label.
  const table = panel(page).locator(`table[aria-label="${label}"]`);
  // The nearest ancestor with both controls owns this table's pager, including on the two-list Policies tab.
  const list = table.locator("xpath=ancestor::*[.//button[normalize-space(.)='Next ›'] and .//button[normalize-space(.)='‹ Previous']][1]");
  const next = list.getByRole("button", { name: "Next ›", exact: true });
  const prev = list.getByRole("button", { name: "‹ Previous", exact: true });
  await next.click();
  await list.getByText(/^26–50 of 61/).waitFor();
  assert.ok(await prev.isEnabled() && await next.isEnabled(), "both old cursors are available");
  const rows = table.locator("tbody tr");
  const previousRows = await rows.allTextContents();
  const before = calls(path).length;
  const held = Promise.withResolvers();
  const received = Promise.withResolvers();
  api.state.hold = {
    match(call) {
      if (call.path !== path || !match(call.query)) return false;
      received.resolve();
      return true;
    },
    until: held.promise
  };
  try {
    await change(next);
    await received.promise;
    await table.and(page.locator("[aria-busy=true]")).waitFor();
    assert.deepEqual(await rows.allTextContents(), previousRows, "the table retains the previous page");
    for (const button of [prev, next]) {
      assert.equal(await button.getAttribute("aria-disabled"), "true", await button.innerText());
      await button.click({ force: true });
    }
  } finally {
    api.state.hold = null;
    held.resolve();
  }
  await list.getByText(after).waitFor();
  assert.equal(await table.getAttribute("aria-busy"), null);
  assert.equal(await prev.isEnabled(), lastPage);
  assert.equal(await next.isEnabled(), !lastPage);
  assert.equal(calls(path).length, before + 1, "only the held request reached the API");
}

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
  const started = performance.now();
  const late = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`"${name}" did not end in ${CHECK_TIMEOUT_MS / 1000} s`)), CHECK_TIMEOUT_MS); });
  try {
    await Promise.race([run(), late]);
  } catch (error) {
    console.error(`not ok - ${name}`);
    throw error;
  } finally {
    clearTimeout(timer);
  }
  done.push(name);
  // Each check says its time against its limit, so a check that nears the limit shows in every run's log (#508).
  console.log(`ok - ${name} (${((performance.now() - started) / 1000).toFixed(1)} s of ${CHECK_TIMEOUT_MS / 1000} s)`);
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

  await check("407 Requests keeps both cursors off while a search loads", async () => {
    const { context, page } = await fresh({ items: heldPageRows().items });
    await open(page);
    await checkHeldPage(page, {
      label: "Requests", path: "/api/v1/requests",
      change: () => page.getByRole("textbox", { name: "Find a request" }).fill("LEDGER"),
      match: (q) => q.q === "LEDGER" && !q.cursor, after: /^1–25 of 30/
    });
    await context.close();
  });

  await check("407 paused Requests keeps the previous page's cursors off until reconnect", async () => {
    const { context, page } = await fresh();
    try {
      await open(page);
      const next = panel(page).getByRole("button", { name: "Next ›" });
      const prev = panel(page).getByRole("button", { name: "‹ Previous" });
      await next.click();
      await waitRange(page, "26–50 of 61");
      await page.evaluate(() => window.dispatchEvent(new Event("offline")));
      await page.getByRole("textbox", { name: "Find a request" }).fill("LEDGER");
      await page.waitForURL((url) => url.hash === "#requests?q=LEDGER");
      const table = page.locator("table[aria-label=Requests]");
      await table.and(page.locator("[aria-busy=true]")).waitFor();
      assert.ok(await prev.isDisabled() && await next.isDisabled(), "paused rows still have the old cursors");
      assert.equal(calls("/api/v1/requests").filter((c) => c.query.q === "LEDGER").length, 0);
      await page.evaluate(() => window.dispatchEvent(new Event("online")));
      await waitRange(page, "1–25 of 30");
      assert.equal(await table.getAttribute("aria-busy"), null);
      assert.ok(await prev.isDisabled() && await next.isEnabled());
    } finally {
      await context.close();
    }
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

  await check("5 a role sees the tabs that GET /api/v1/me permits: a viewer, an approver, a requester, an operator, and the approval relay with no capacity:read", async () => {
    // The stand-in's access token is an opaque string, so the browser cannot read a role from it.
    // Namespaces needs objects:read, the permission of its first call (GET .../namespaces): every role that reads objects (#484).
    const base = ["Workflow", "Namespaces", "Quotas", "Expiration", "Requests", "Policies", "Capacity"];
    const want = {
      viewer: base,
      approver: ["Workflow", "Namespaces", "Quotas", "Expiration", "Requests", "Approvals", "Policies", "Capacity"],
      requester: ["Workflow", "New namespace", "Namespaces", "Quotas", "Expiration", "Requests", "Policies", "Capacity"],
      // KPIs is operator and above: reports:read (docs/14).
      operator: ["Workflow", "New namespace", "Namespaces", "Quotas", "Expiration", "Requests", "Policies", "Capacity", "KPIs"],
      // requests:read and approvals:relay only (docs/14): no capacity:read, so no Capacity tab (#302).
      relay: ["Workflow", "Requests"]
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
    await panel(page).getByText("1 / 6", { exact: true }).waitFor();
    assert.equal(await counter(), "1 / 6");
    assert.equal(await panel(page).getByRole("button", { name: "Back", exact: true }).isDisabled(), true, "Back is off at the first step");
    await panel(page).getByRole("button", { name: "Next step" }).click();
    await panel(page).getByText("2 / 6", { exact: true }).waitFor();
    assert.equal(await counter(), "2 / 6");
    assert.equal(await panel(page).locator("article h2").innerText(), upToApplied[1].event, "the detail shows the step in view");
    await banner(page).getByRole("button", { name: "Back to current step" }).click();
    await panel(page).getByText("6 / 6", { exact: true }).waitFor();
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
    await panel(page).getByRole("button", { name: "Check (dry run)" }).waitFor();
  };
  /** The required fields of the form of design section 3.1 (KEYS_479), with the mockup's values. */
  const fill479 = async (page, { mnemonic = "abc", desired = "payments" } = {}) => {
    await page.getByLabel("Mnemonic (required)").fill(mnemonic);
    await page.getByLabel("Namespace", { exact: true }).fill(desired);
    await page.getByLabel("Line of business (required)").fill("amgsst");
    await page.getByLabel("Critical level (required)").selectOption("1");
    await page.getByLabel("Team DL (required)").fill("payments-team@company.net");
    await page.getByLabel("Justification").fill("Payments service dev namespace");
  };
  /** A calendar date `days` after today (UTC), as the form counts it. */
  const isoAfter = (days) => new Date(Date.now() + days * 864e5).toISOString().slice(0, 10);
  // The status of the form's last Check (#479 P7), under the preview.
  const PASSED = "The check passed (dry run, 200)";
  const checkButton = (page) => panel(page).getByRole("button", { name: "Check (dry run)" });
  const submitButton = (page) => panel(page).getByRole("button", { name: "Submit request" });
  const fillForm = async (page, { team = "payments", dl = "payments-team@ephico2real.com" } = {}) => {
    await page.getByLabel("Team (required)").fill(team);
    await page.getByLabel("Team DL (required)").fill(dl);
    await page.getByLabel("Justification").fill("Payments service dev namespace");
  };
  const posts = () => api.state.seen.filter((c) => c.method === "POST" && c.path === "/api/v1/clusters/CRC/namespaces");
  const approvalCard = (page) => panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: "Preview" }) });

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
    await waitValue(page.getByLabel("Namespace (required)"), "payments-dev");
    assert.equal(await page.getByLabel("Namespace (required)").inputValue(), "payments-dev", "no key makes an end of the name here: the suggestion, team and environment");
    assert.equal(await submitButton(page).getAttribute("aria-disabled"), "true", "Submit is off until a check passes (#479 P7)");

    await checkButton(page).click();
    const callout = panel(page).locator(".pf-v6-c-alert").filter({ hasText: PASSED });
    await callout.waitFor();
    assert.deepEqual((await callout.locator("ul").first().locator(":scope > li").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim()), [
      "✓ Environment served dev in [rnd, dev]", "✓ Capacity fits on fresh data", "✓ Expiry none: permanent", "! Approval dev-create · 2 of approver-platform"
    ]);
    const plan = SAMPLES.operations["namespaces_create_namespace:dryRun"].response.body;
    assert.match(await callout.innerText(), new RegExp(`2 approvals in cmapi from approver-platform\\. ${plan.approval.reasons.join("; ").replace(/[+()]/g, "\\$&")}\\. Self-approval is allowed in dev\\.`));
    assert.match(await approvalCard(page).innerText(), /Cluster\s+CRC \(dev\)\s+Expires\s+never \(permanent\)\s+Quota\s+medium: 16 cores · 32Gi · 100 pods\s+Approval\s+dev-create · 2 of approver-platform\s+Lands in Git\s+clusters\/CRC\/namespaces\/payments-dev\//);
    assert.equal(await submitButton(page).getAttribute("aria-disabled"), null, "a passing check opens Submit");
    const dry = posts().filter((c) => c.query.dryRun === "true");
    assert.equal(dry.length, 1, "one dry run");
    assert.equal(dry[0].key, null, "a dry run sends no Idempotency-Key");
    assert.deepEqual(dry[0].body, { namespace: "payments-dev", tier: "medium", labels: { "cmapi.net/team": "payments" }, annotations: { "cmapi.net/team-dl": "payments-team@ephico2real.com" }, justification: "Payments service dev namespace" });
    // A change to the form hides the plan and closes Submit, as in the mockup: the form must be checked again.
    await panel(page).getByRole("group", { name: "Tier" }).getByRole("button", { name: /^small/ }).click();
    await panel(page).getByText("Changed since the last check. Press Check (dry run) again.").waitFor();
    assert.equal(await callout.count(), 0, "the plan is of the old form");
    assert.equal(await submitButton(page).getAttribute("aria-disabled"), "true");
    await submitButton(page).click({ force: true });
    await page.waitForTimeout(300);
    assert.equal(posts().filter((c) => c.query.dryRun !== "true").length, 0, "Submit sends nothing for a form that is not checked");

    // The first submit meets a failure of the API; Submit again sends the same key. The answer of the second is lost on the
    // way, so the person submits a third time: the API answers with the request it made, and makes no second one.
    await checkButton(page).click();
    await callout.waitFor();
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
    await checkButton(page).click();
    await callout.waitFor();
    await submitButton(page).click();
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
      await page.getByLabel("Namespace (required)").fill("openshift-tools");
      await checkButton(page).click();
      const refused = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The check failed: reserved-namespace" });
      await refused.waitFor();
      assert.match(await refused.innerText(), /openshift-tools is reserved/);
      assert.match(await refused.getAttribute("class"), /pf-m-danger/);
      // An empty Team DL, then one that is not an address: the browser refuses each, and nothing goes to the API.
      const before = posts().length;
      await page.getByLabel("Team DL (required)").fill("");
      await checkButton(page).click();
      await page.getByLabel("Team DL (required)").fill("not-an-address");
      await checkButton(page).click();
      await page.getByLabel("Expires (optional)").fill("2020-01-01");
      await page.getByLabel("Team DL (required)").fill("payments-team@ephico2real.com");
      await checkButton(page).click();
      const blocked = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The check did not run. Fix these:" });
      await blocked.getByText("Expires: Pick a date after today.").waitFor();
      await submitButton(page).click({ force: true });
      await page.waitForTimeout(300);
      assert.equal(posts().length, before, "no check and no submit while a field is not valid");
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
      await checkButton(page).waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("R1 New namespace: a form changed after a lost answer is another request, with its own Idempotency-Key", async () => {
    const { context, page, errors } = await fresh();
    expectedStatus = [409];
    const passed = panel(page).locator(".pf-v6-c-alert").filter({ hasText: PASSED });
    await newTab(page);
    await fillForm(page);
    await checkButton(page).click();
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
    await checkButton(page).click();
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

  await check("R2 New namespace: Submit is off until the check passes and off again after any change; it sends exactly the checked body", async () => {
    const { context, page, errors } = await fresh();
    const passed = panel(page).locator(".pf-v6-c-alert").filter({ hasText: PASSED });
    const writes = () => posts().filter((c) => c.query.dryRun !== "true");
    const dryRuns = () => posts().filter((c) => c.query.dryRun === "true");
    await newTab(page);
    await fillForm(page);
    // Not checked yet: Submit is aria-disabled (PatternFly isAriaDisabled: focusable, says why) and sends nothing.
    await panel(page).getByText("Not checked yet. Press Check (dry run) to ask cmapi whether this request passes.").waitFor();
    assert.equal(await submitButton(page).getAttribute("aria-disabled"), "true");
    assert.equal(await submitButton(page).getAttribute("aria-describedby"), "ns-status", "the reason is the status in words");
    await submitButton(page).focus();
    await page.keyboard.press("Enter");
    await page.getByLabel("Team (required)").press("Enter");        // a text input's Enter submits a form (HTML implicit submission)
    await submitButton(page).click({ force: true });
    await page.waitForTimeout(300);
    assert.equal(writes().length + dryRuns().length, 0, "no submit, and no plan either: only Check plans");
    await checkButton(page).click();
    await passed.waitFor();
    assert.equal(await submitButton(page).getAttribute("aria-disabled"), null);
    // A change after the check: Submit is off again until the new form is checked.
    await panel(page).getByRole("group", { name: "Tier" }).getByRole("button", { name: /^small/ }).click();
    await passed.waitFor({ state: "detached" });
    assert.equal(await passed.count(), 0, "the plan is of the old form");
    assert.equal(await submitButton(page).getAttribute("aria-disabled"), "true");
    await submitButton(page).click({ force: true });
    await page.waitForTimeout(300);
    assert.equal(writes().length, 0, "no submit of a plan that the person did not see");
    await checkButton(page).click();
    await passed.waitFor();
    assert.equal(dryRuns().at(-1).body.tier, "small", "the new form was planned");
    await submitButton(page).click();
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
  // A value read after an action waits for it, as Playwright's auto-retrying assertions do: one read can come before the
  // re-render (#518; https://playwright.dev/docs/test-assertions, "using non-retrying assertions can lead to a flaky test").
  async function waitValue(input, want) {
    for (let i = 0; i < 40; i++) {
      if (await input.inputValue() === want) return;
      await input.page().waitForTimeout(100);
    }
    assert.equal(await input.inputValue(), want);
  }
  async function waitError(input, want) {
    for (let i = 0; i < 40; i++) {
      const text = await errorOf(input);
      if (want === null ? text === null : text !== null && want.test(text)) return text;
      await input.page().waitForTimeout(100);
    }
    assert.fail(`the field's error is ${JSON.stringify(await errorOf(input))}, not ${want}`);
  }
  const dryRuns = () => posts().filter((c) => c.query.dryRun === "true");
  const passed = (page) => panel(page).locator(".pf-v6-c-alert").filter({ hasText: PASSED });
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
        await checkButton(page).click();
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
      // The key that starts the name (namespacePrefix) is in the Name section, before the name (#479 P2); the keys that cmapi
      // sets come first in their section (P3), then the required inputs, then the optional ones, as the mockup orders them.
      assert.deepEqual(await labelsOf(section(page, "Name")), ["company.net/mnemonic (required)", "Namespace (required)"]);
      assert.deepEqual(await labelsOf(section(page, "Labels")), ["name", "company.net/app-environment", "company.net/lob (required)", "company.net/cl (required)"]);
      assert.deepEqual(await labelsOf(section(page, "Annotations")), ["company.net/app-environment", "company.net/mnemonic-group-contact (optional)", "company.net/mnemonic-confluence (optional)"]);
      assert.doesNotMatch(await panel(page).locator("form").evaluate((el) => el.textContent), /cmapi\.net\/protected|cmapi\.net\/team|Team DL/, "no operator-only key, and none of the reference file's");
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
      await page.getByLabel("Namespace (required)").fill("payments");
      await lob.fill("amg sst");
      await cl.selectOption("1");
      await waitError(mnemonic, /^Not valid: must match \^\[a-z\]\{3,4\}\$; the namespace name starts with this value and '-'/);
      await waitError(lob, /^Not a valid label value/);
      assert.equal(await mnemonic.getAttribute("aria-invalid"), "true");
      assert.equal(await name.inputValue(), "ABC-payments", "the name that cmapi copies follows the namespace");
      const before = posts().length;
      await checkButton(page).click();
      await submitButton(page).click({ force: true });
      await page.waitForTimeout(500);
      assert.equal(posts().length, before, "nothing is planned or sent while a field is refused");

      // The mnemonic starts the namespace name (namespacePrefix): the locked start follows it, so no other start can be typed.
      await mnemonic.fill("abc");
      await lob.fill("amgsst");
      await waitError(mnemonic, null);
      assert.equal((await page.locator("#ns-name-start").innerText()).trim(), "abc-");
      assert.equal(await page.getByLabel("Namespace (required)").inputValue(), "payments", "the person types the rest only");
      assert.equal(await page.locator("#ns-name-end").count(), 0, "this file makes no end of the name");

      // An optional URL that cmapi accepts and <input type=url> refuses (#336, design B): text with the URL keyboard.
      const wiki = page.getByLabel("company.net/mnemonic-confluence (optional)");
      assert.deepEqual([await wiki.getAttribute("type"), await wiki.getAttribute("inputmode")], ["text", "url"]);
      assert.equal(await page.getByLabel("company.net/mnemonic-group-contact (optional)").getAttribute("type"), "email");
      await wiki.fill("https://wiki.company.net:abc/x");
      await page.getByLabel("Justification").fill("ABC rnd namespace");
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.deepEqual(dryRuns().at(-1).body, { namespace: "abc-payments", tier: "medium",
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
      // #479: the optional keys are fields in their section, as the mockup shows them; each starts empty.
      assert.deepEqual(await Promise.all(optional.map((k) => page.getByLabel(`${k} (optional)`).inputValue())), ["", "", ""]);
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
      await checkButton(page).waitFor();
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
      await checkButton(page).click();
      const refused = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The check failed: policy-violation" });
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
      // The name is typed: the suggestion from this team would not be a DNS-1123 name, which the form checks (#479).
      await page.getByLabel("Namespace (required)").fill("payments-dev");
      await page.waitForTimeout(300);
      const started = Date.now();
      assert.equal(await Promise.race([page.evaluate(() => 1), new Promise((resolve) => setTimeout(() => resolve("no answer"), 1000))]), 1, "the page answers");
      await page.getByLabel("Justification").pressSequentially("ok", { timeout: 1000 });
      assert.equal(await page.getByLabel("Justification").inputValue(), "ok", "a field takes keys while the pattern runs");
      assert.ok(Date.now() - started < 2000, `answered in ${Date.now() - started} ms`);
      await page.waitForTimeout(400);
      assert.equal(await errorOf(page.getByLabel("Team (required)")), null, "not checked here: no error, cmapi decides");
      api.state.answers.push(refusedWith([{ code: "invalid_value", key: "cmapi.net/team", detail: `must match ${slow}` }]));
      await checkButton(page).click();
      await panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The check failed: policy-violation" }).waitFor();
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
      await checkButton(page).click();
      await page.waitForTimeout(400);
      assert.equal(posts().length, before, "the browser stops on the new required key");
      await owner.fill("platform");
      await checkButton(page).click();
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
      assert.equal(await checkButton(page).count(), 0, "never a form with fields missing");
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

  // #479 (Phase 4): the New namespace form of the mockup mockups/portal/new-namespace-479.html, on an instance with the
  // configuration of design section 3.1 (KEYS_479, the service's answer for it). Each behaviour runs at 390, 820 and 1440 px
  // in each theme, on a fresh form, and each is written from the mockup, the design and the API's answer, not from the page.
  const RND_CLUSTER = { ...SAMPLES.operations.core_clusters.response.body.items[0], clusterId: "KIND_CMAPI_TEST", environment: "rnd", secretName: "cmapi-cluster-kind" };
  const TIERS_RND = { ...SAMPLES.operations.tiers_tiers.response.body, environments: { ...SAMPLES.operations.tiers_tiers.response.body.environments,
    rnd: SAMPLES.operations.tiers_tiers.response.body.environments.dev } };
  async function atEachView(run, { setup = () => undefined, ...options } = {}) {
    for (const width of [390, 820, 1440]) {
      for (const theme of ["light", "dark"]) {
        const { context, page, errors } = await fresh({ width, metadataKeys: KEYS_479, ...options });
        try {
          setup();
          await newTab(page);
          await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
          await run(page, `${width} ${theme}`);
          assert.deepEqual(errors, [], `${width} ${theme}`);
        } catch (error) {
          // Name the view in what the suite prints (Node prints the stack, which holds the first message).
          throw Object.assign(new Error(`${width} ${theme}: ${error.message}`, { cause: error }), { stack: `${width} ${theme}: ${error.stack}` });
        } finally { await context.close(); }
      }
    }
  }
  const groupOf = (page, label) => panel(page).locator(".pf-v6-c-form__group").filter({ has: page.getByLabel(label, { exact: true }) });
  const statusText = async (page) => (await page.locator("#ns-status").innerText()).replace(/\s+/g, " ");
  const code = (page) => panel(page).locator(".pf-v6-c-code-block").innerText();

  await check("479-P2 the name: both ends locked and filled from the mnemonic and the cluster's environment, the full name and its length", async () => {
    await atEachView(async (page, view) => {
      const name = page.getByLabel("Namespace", { exact: true });
      const start = page.locator("#ns-name-start"), end = page.locator("#ns-name-end");
      // The first environment with a cluster to write to is rnd here.
      assert.deepEqual([(await start.innerText()).trim(), (await end.innerText()).trim()], ["…-", "-rnd"], "nothing typed: the start waits for the mnemonic");
      assert.equal(await page.locator("#ns-name-start input, #ns-name-end input").count(), 0, "neither end is an input");
      await page.getByLabel("Mnemonic (required)").fill("abc");
      await start.filter({ hasText: "abc-" }).waitFor();
      assert.equal((await start.innerText()).trim(), "abc-", "the start follows the mnemonic");
      assert.match(await page.locator("#ns-name-help").innerText(), /Leave empty for a team-wide namespace: abc-rnd\./);
      await name.fill("payments");
      await page.locator("#ns-name-full").filter({ hasText: "Will be created as abc-payments-rnd (16 of 63 characters)" }).waitFor();
      assert.equal((await page.locator("#ns-name-full").innerText()).trim(), "Will be created as abc-payments-rnd (16 of 63 characters)");
      assert.equal(await name.inputValue(), "payments", "the person types the middle only");
      assert.match(await name.getAttribute("aria-describedby"), /ns-name-start.*ns-name-end/, "a screen reader hears both ends");
      // The suffix follows the cluster's environment at once (plan R6), and so do the keys that cmapi fills in.
      assert.equal(await page.getByLabel("Cluster").inputValue(), "KIND_CMAPI_TEST");
      await panel(page).getByRole("group", { name: "Environment" }).getByRole("button", { name: "dev" }).click();
      await end.filter({ hasText: "-dev" }).waitFor();
      assert.equal((await end.innerText()).trim(), "-dev");
      await waitValue(page.getByLabel("Cluster"), "CRC");
      assert.equal(await page.getByLabel("Cluster").inputValue(), "CRC");
      await waitValue(section(page, "Labels").getByLabel("Name", { exact: true }), "abc-payments-dev");
      assert.equal(await section(page, "Labels").getByLabel("Name", { exact: true }).inputValue(), "abc-payments-dev");
      await waitValue(section(page, "Labels").getByLabel("App environment", { exact: true }), "dev");
      assert.equal(await section(page, "Labels").getByLabel("App environment", { exact: true }).inputValue(), "dev");
      // The whole name is a DNS-1123 label of at most 63 characters (core/naming.py): checked as it is typed.
      await name.fill("x".repeat(56));
      await waitError(name, /^The full name is longer than 63 characters\./);
      await name.fill("payments");
      await waitError(name, null);
      await fill479(page);
      await checkButton(page).click();
      await passed(page).waitFor();
      const sent = dryRuns().at(-1);
      assert.equal(sent.path, "/api/v1/clusters/CRC/namespaces", view);
      assert.equal(sent.body.namespace, "abc-payments-dev");
      assert.equal(["name", "company.net/app-environment"].filter((k) => k in sent.body.labels).length, 0, "cmapi fills in the keys that it sets");
    }, { setup: () => { api.state.clusters = [...api.state.clusters, RND_CLUSTER]; api.state.tiers = TIERS_RND; } });
  });

  await check("479-P2 a team-wide namespace with an empty middle is previewed and sent in the dry run", async () => {
    await atEachView(async (page) => {
      await fill479(page, { desired: "" });
      await page.locator("#ns-name-full").filter({ hasText: "Will be created as abc-dev (7 of 63 characters)" }).waitFor();
      assert.equal(await page.getByLabel("Namespace", { exact: true }).evaluate((input) => input.required), false);
      assert.match(await page.locator("#ns-name-help").innerText(), /Leave empty for a team-wide namespace: abc-dev\./);
      assert.equal((await page.locator("#ns-name-full").innerText()).trim(), "Will be created as abc-dev (7 of 63 characters)");
      assert.match(await code(page), /^  name: "abc-dev"$/m);
      assert.equal(await section(page, "Labels").getByLabel("Name", { exact: true }).inputValue(), "abc-dev");
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.equal(dryRuns().at(-1).body.namespace, "abc-dev");
    });
  });

  await check("512 the middle starts and ends with a letter or digit; inner dashes and team-wide names pass", async () => {
    await atEachView(async (page) => {
      await fill479(page);
      const name = page.getByLabel("Namespace", { exact: true });
      for (const desired of ["-x", "x-", "-"]) {
        await name.fill(desired);
        await waitError(name, /^Start and end with a letter or digit\./);
        const before = dryRuns().length;
        await checkButton(page).click();
        await panel(page).getByText("Namespace: Start and end with a letter or digit.", { exact: true }).waitFor();
        assert.equal(dryRuns().length, before, "a bad middle is refused before the dry run");
      }
      for (const desired of ["x-y", "x--y", "1", ""]) {
        await name.fill(desired);
        await waitError(name, null);
        await checkButton(page).click();
        await passed(page).waitFor();
        assert.equal(dryRuns().at(-1).body.namespace, desired ? `abc-${desired}-dev` : "abc-dev");
      }
    });
  });

  await check("479-P3-P5 the keys that cmapi sets are locked and marked automatic; Team copies Mnemonic until edited; each field checks as it is typed", async () => {
    await atEachView(async (page) => {
      for (const label of ["Name", "App environment"]) {
        const input = section(page, "Labels").getByLabel(label, { exact: true });
        assert.deepEqual(await input.evaluate((el) => [el.readOnly, el.disabled]), [true, false], `${label}: read-only, in the tab order`);
        assert.equal(await groupOf(page, label).getByText("automatic", { exact: true }).count(), 1, `${label} is marked automatic`);
      }
      const team = page.getByLabel("Team (required)"), mnemonic = page.getByLabel("Mnemonic (required)");
      const chip = () => groupOf(page, "Team (required)").getByText("from Mnemonic", { exact: true });
      assert.equal(await team.inputValue(), "");
      await mnemonic.fill("abc");
      await waitValue(team, "abc");
      assert.equal(await team.inputValue(), "abc", "the default copies the mnemonic");
      await chip().waitFor();
      assert.equal(await chip().count(), 1);
      await mnemonic.fill("xyz");
      await waitValue(team, "xyz");
      assert.equal(await team.inputValue(), "xyz", "and follows it while not edited");
      // Each field checks as it is typed, before any Check (P5): the validator's words.
      await page.getByLabel("Line of business (required)").fill("amg sst");
      await waitError(page.getByLabel("Line of business (required)"), /^Not a valid label value/);
      await fill479(page);
      await panel(page).locator(".pf-v6-c-code-block").filter({ hasText: /cmapi\.net\/team: "abc" {3}# from Mnemonic/ }).waitFor();
      assert.match(await code(page), /cmapi\.net\/team: "abc" {3}# from Mnemonic/);
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.equal(dryRuns().at(-1).body.labels["cmapi.net/team"], undefined, "an unedited default is not sent: cmapi fills it in");
      assert.match(await statusText(page), /cmapi\.net\/team = abc default from company\.net\/mnemonic/, "the dry run says where the value comes from (A7)");
      // An edit is the person's: the chip goes, and a later change of the mnemonic leaves it alone (plan R5).
      await team.fill("payments");
      await chip().waitFor({ state: "detached" });
      assert.equal(await chip().count(), 0);
      await mnemonic.fill("abcd");
      assert.equal(await team.inputValue(), "payments");
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.equal(dryRuns().at(-1).body.labels["cmapi.net/team"], "payments");
      assert.match(await statusText(page), /cmapi\.net\/team = payments from the request/);
    });
  });

  await check("479-P6-P7 the preview follows each keystroke; Check (dry run) replaces it with the plan's file; Submit opens only then, and closes on any change", async () => {
    await atEachView(async (page) => {
      assert.match(await code(page), /^apiVersion: v1\nkind: Namespace\nmetadata:\n {2}name: "…-…-dev"/);
      await fill479(page);
      await panel(page).locator(".pf-v6-c-code-block").filter({ hasText: 'cmapi.net/team-dl: "payments-team@company.net"' }).waitFor();
      const yaml = await code(page);
      for (const line of ['name: "abc-payments-dev"', 'name: "abc-payments-dev"   # automatic', 'company.net/app-environment: "dev"   # automatic', 'company.net/mnemonic: "abc"',
        'company.net/lob: "amgsst"', 'company.net/cl: "1"', 'cmapi.net/team: "abc"   # from Mnemonic', 'cmapi.net/team-dl: "payments-team@company.net"']) {
        assert.ok(yaml.includes(line), `the preview has ${line}`);
      }
      assert.match(await approvalCard(page).innerText(), /Namespace\s+abc-payments-dev\s+Cluster\s+CRC \(dev\)\s+Expires\s+never \(permanent\)/);
      assert.equal(await submitButton(page).getAttribute("aria-disabled"), "true", "not checked: Submit is off");
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.match(await approvalCard(page).innerText(), /From the dry run: clusters\/CRC\/namespaces\/abc-payments-dev\/namespace\.yaml/);
      assert.match(await code(page), /name: abc-payments-dev\n {2}labels:\n {4}cmapi\.net\/cluster-id: CRC/, "the plan's own namespace.yaml");
      assert.equal(await submitButton(page).getAttribute("aria-disabled"), null);
      await page.getByLabel("Critical level (required)").selectOption("2");
      await panel(page).getByText("Changed since the last check. Press Check (dry run) again.").waitFor();
      assert.equal(await submitButton(page).getAttribute("aria-disabled"), "true", "a change closes Submit again");
      assert.match(await code(page), /company\.net\/cl: "2"/, "the preview is the form's again");
      await checkButton(page).click();
      await passed(page).waitFor();
      await submitButton(page).click();
      await banner(page).waitFor();
      const write = posts().filter((c) => c.query.dryRun !== "true").at(-1);
      assert.deepEqual(write.body, dryRuns().at(-1).body, "Submit sends the checked body");
    });
  });

  await check("479-P9-P11 Additional labels and annotations: closed and empty by default; two key/value tables checked as typed; closing keeps the rows, which go in the same maps", async () => {
    await atEachView(async (page) => {
      const toggle = panel(page).getByRole("button", { name: /^Additional labels and annotations \(optional\)/ });
      assert.equal(await toggle.getAttribute("aria-expanded"), "false", "closed by default");
      assert.match(await toggle.innerText(), /none$/);
      assert.equal(await page.locator("[id^=ns-xl-], [id^=ns-xa-]").count(), 0, "empty by default: no row, no value");
      await toggle.click();
      assert.equal(await panel(page).getByText("None. Add one only if you need it.").count(), 2);
      assert.equal(await panel(page).getByText("0 of 50 · 0 of 65536 bytes").count(), 1);
      await panel(page).getByRole("button", { name: "+ Add label" }).click();
      const key = page.getByLabel("Key of additional label 1"), value = page.getByLabel("Value of additional label 1");
      assert.equal(await key.evaluate((el) => el === document.activeElement), true, "the new row's key has the focus");
      assert.deepEqual([await key.inputValue(), await value.inputValue(), await key.getAttribute("placeholder")], ["", "", "e.g. example.company.net/key"], "placeholder text only");
      assert.equal(await errorOf(key), null, "an empty new row is not in error before the person tries the form");
      for (const [typed, want] of [["kubernetes.io/team", "The prefix must be *.company.net/ (or none)."], ["cmapi.net/team", "This key has its own field above."],
        ["cmapi.net/protected", "Only an operator sets this key."], ["bad key", /^Not a valid key/]]) {
        await key.fill(typed);
        await waitError(key, typeof want === "string" ? new RegExp(`^${want.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`) : want);
        assert.equal(await key.getAttribute("aria-invalid"), "true");
      }
      await key.fill("team.company.net/squad");
      await value.fill("check out");
      await waitError(value, /^A label value: /);
      await value.fill("checkout");
      await waitError(value, null);
      await waitError(key, null);
      await panel(page).getByRole("button", { name: "+ Add label" }).click();
      await page.getByLabel("Key of additional label 2").fill("team.company.net/squad");
      await waitError(page.getByLabel("Key of additional label 2"), /^This key is already in the table\./);
      await panel(page).getByRole("button", { name: "Remove additional label 2" }).click();
      await waitError(key, null);
      await panel(page).getByRole("button", { name: "+ Add annotation" }).click();
      await page.getByLabel("Key of additional annotation 1").fill("runbook.company.net/url");
      await page.getByLabel("Value of additional annotation 1").fill("https://wiki.company.net/abc/runbook");
      // The counter is rendered from the new value; count() itself does not retry (#552).
      await panel(page).getByText("1 of 50 · 36 of 65536 bytes").waitFor();
      assert.equal(await panel(page).getByText("1 of 50 · 36 of 65536 bytes").count(), 1, "the bytes of the values, as cmapi counts them");
      await toggle.click();
      await toggle.and(page.locator("[aria-expanded=false]")).waitFor();
      assert.equal(await toggle.getAttribute("aria-expanded"), "false");
      assert.match(await toggle.innerText(), /1 label, 1 annotation$/, "closed, it counts what it holds");
      assert.match(await code(page), /team\.company\.net\/squad: "checkout" {3}# additional/);
      await fill479(page);
      await checkButton(page).click();
      await passed(page).waitFor();
      const body = dryRuns().at(-1).body;
      assert.equal(body.labels["team.company.net/squad"], "checkout", "closing the section keeps the rows (P11)");
      assert.equal(body.annotations["runbook.company.net/url"], "https://wiki.company.net/abc/runbook");
      // A refused row in a closed section: Check opens it, lists the row, and plans nothing.
      await toggle.click();
      await key.fill("kubernetes.io/team");
      await toggle.click();
      const before = dryRuns().length;
      await checkButton(page).click();
      await panel(page).getByText("The check did not run. Fix these:").waitFor();
      assert.equal(await toggle.getAttribute("aria-expanded"), "true", "the section opens on its problem");
      assert.match(await statusText(page), /Additional label 1 kubernetes\.io\/team: The prefix must be \*\.company\.net\/ \(or none\)\./);
      assert.equal(dryRuns().length, before);
    });
  });

  await check("479-P12 Expires: empty by default; a calendar from tomorrow; the date and the days left; a warning past maxLifetimeDays, never a refusal; No expiry clears it", async () => {
    await atEachView(async (page) => {
      const date = page.getByLabel("Expires (optional)");
      assert.equal(await date.inputValue(), "", "empty: a permanent namespace, never a date from the limit (D15)");
      assert.equal(await page.locator("#ns-exp-days").innerText(), "No expiry: the namespace is permanent.");
      assert.equal(await page.locator("#ns-exp-help").innerText(), "Notices to the team DL 14, 7 and 1 days before. It keeps running 7 days after the date.");
      // The calendar: today cannot be picked; the 15th of next month can.
      await panel(page).getByRole("button", { name: "Open the calendar" }).click();
      const calendar = page.getByRole("dialog");
      await calendar.waitFor();
      const now = new Date();
      assert.equal(await calendar.locator(".pf-v6-c-calendar-month__dates-cell.pf-m-current button").isDisabled(), true, "today is not offered");
      await calendar.getByRole("button", { name: "Next month" }).click();
      await calendar.locator(".pf-v6-c-calendar-month__dates-cell:not(.pf-m-adjacent-month) button").filter({ hasText: /^15$/ }).click();
      const next = new Date(now.getFullYear(), now.getMonth() + 1, 15);
      const picked = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}-15`;
      await waitValue(date, picked);
      assert.equal(await date.inputValue(), picked, "the calendar writes the date");
      const days = Math.round((Date.parse(picked) - Date.parse(isoAfter(0))) / 864e5);
      assert.equal(await page.locator("#ns-exp-days").innerText(), `Expires on ${picked}, in ${days} days.`);
      assert.match(await approvalCard(page).innerText(), new RegExp(`Expires\\s+${picked} \\(in ${days} days\\)`));
      assert.match(await code(page), new RegExp(`cmapi\\.net/expires-at: "${picked}" {3}# from Expires`));
      // Past maxLifetimeDays (180 here): a warning that one more approval is needed; the check runs and the API decides.
      await date.fill(isoAfter(200));
      await page.locator("#ns-exp-days").filter({ hasText: `Expires on ${isoAfter(200)}, in 200 days. More than 180 days: needs one more approval.` }).waitFor();
      assert.ok((await page.locator("#ns-exp-days").innerText()).startsWith(`Expires on ${isoAfter(200)}, in 200 days. More than 180 days: needs one more approval.`));
      assert.match(await page.locator("#ns-exp-days").getAttribute("class"), /pf-m-warning/);
      await fill479(page);
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.equal(dryRuns().at(-1).body.expiresAt, isoAfter(200), "a date past the limit is sent, not refused in the browser");
      assert.match(await statusText(page), new RegExp(`! Expiry ${isoAfter(200)}, 200 days \\(limit 180: one more approval\\)`));
      assert.match(await code(page), new RegExp(`cmapi\\.net/expires-at: '${isoAfter(200)}'`), "the plan writes the date on the namespace");
      await panel(page).getByRole("button", { name: "No expiry" }).click();
      await waitValue(date, "");
      assert.equal(await page.locator("#ns-exp-days").innerText(), "No expiry: the namespace is permanent.");
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.equal("expiresAt" in dryRuns().at(-1).body, false, "no date, no expiresAt");
    });
  });

  await check("479-P12 where x-cmapi-expiration turns expiration off for the environment, there is no date field, only why, and nothing is sent", async () => {
    // dev is off here by its flag, not by its name: the form reads enabled from the answer (A11), and names no environment.
    const off = { ...KEYS_479, "x-cmapi-expiration": { environments: { rnd: KEYS_479["x-cmapi-expiration"].environments.rnd, dev: { enabled: false } } } };
    await atEachView(async (page) => {
      // rnd, the first environment here, keeps its date field: the flag is per environment.
      await page.getByLabel("Expires (optional)").waitFor();
      await panel(page).getByRole("group", { name: "Environment" }).getByRole("button", { name: "dev" }).click();
      await page.getByLabel("Expires (optional)").waitFor({ state: "detached" });
      assert.equal(await page.getByLabel("Expires (optional)").count(), 0, "no date field");
      assert.equal(await page.locator("#ns-exp-off").innerText(), "Expiration is turned off for this environment (expiration.yaml: enabled: false). The namespace is permanent.");
      assert.match(await approvalCard(page).innerText(), /Expires\s+never \(expiration off here\)/);
      await fill479(page);
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.equal("expiresAt" in dryRuns().at(-1).body, false);
    }, { metadataKeys: off, setup: () => { api.state.clusters = [...api.state.clusters, RND_CLUSTER]; api.state.tiers = TIERS_RND; } });
  });

  // PR #506 review (reviewer 1 Codex gpt-6.2-astra, reviewer 2 Opus 5.5): the defects of findings 01, 02, 04, 11 and 12.
  // Each is one behaviour, not a layout, so each runs on one view.
  const waitFor = async (page, ready, what) => {
    for (let i = 0; i < 50 && !ready(); i++) await page.waitForTimeout(100);
    assert.ok(ready(), what);
  };
  const extraToggle = (page) => panel(page).getByRole("button", { name: /^Additional labels and annotations \(optional\)/ });

  await check("506-01 Submit is off again after a change that leaves the body as it was; Check on a checked form asks cmapi again", async () => {
    const { context, page, errors } = await fresh({ metadataKeys: KEYS_479 });
    try {
      await newTab(page);
      await fill479(page);
      await checkButton(page).click();
      await passed(page).waitFor();
      const first = dryRuns().length;
      await checkButton(page).click();
      await waitFor(page, () => dryRuns().length === first + 1, "a second Check of the same form sends a second dry run");
      await passed(page).waitFor();
      assert.equal(await submitButton(page).getAttribute("aria-disabled"), null);
      // Team emptied: unedited it was not sent, emptied it is sent as "" (finding 09), so the form is not the checked one.
      await page.getByLabel("Team (required)").fill("");
      await panel(page).getByText("Changed since the last check. Press Check (dry run) again.").waitFor();
      assert.equal(await submitButton(page).getAttribute("aria-disabled"), "true", "an emptied Team closes Submit");
      await page.getByLabel("Team (required)").fill("abc");
      await checkButton(page).click();
      await passed(page).waitFor();
      // A row with no key yet: the body is as it was, but the form is not.
      await extraToggle(page).click();
      await page.getByRole("button", { name: "+ Add label" }).click();
      await panel(page).getByText("Changed since the last check. Press Check (dry run) again.").waitFor();
      assert.equal(await submitButton(page).getAttribute("aria-disabled"), "true", "a new row closes Submit");
      await checkButton(page).click();
      await panel(page).getByText("The check did not run. Fix these:").waitFor();
      assert.equal(await passed(page).count(), 0, "the last pass is not shown beside the form's problems");
      assert.equal(await submitButton(page).getAttribute("aria-disabled"), "true");
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  await check("N1 New namespace: returning to a checked draft asks cmapi again within the cache's stale time", async () => {
    const { context, page, errors } = await fresh({ metadataKeys: KEYS_479 });
    try {
      await newTab(page);
      await fill479(page);
      const level = page.getByLabel("Critical level (required)");
      const started = Date.now();
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.equal(dryRuns().length, 1, "the first Check sends draft A");
      const draftA = dryRuns()[0].body;
      await level.selectOption("2");
      await panel(page).getByText("Changed since the last check. Press Check (dry run) again.").waitFor();
      assert.equal(await submitButton(page).getAttribute("aria-disabled"), "true");
      await level.selectOption("1");
      await checkButton(page).click();
      await waitFor(page, () => dryRuns().length === 2, "Check after editing A to B and back sends a second dry run");
      await passed(page).waitFor();
      assert.deepEqual(dryRuns().map((c) => c.body), [draftA, draftA]);

      // Also switch the query key to B: returning to A must not reuse its cached pass.
      await level.selectOption("2");
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.equal(dryRuns().length, 3, "Check sends draft B");
      await level.selectOption("1");
      await checkButton(page).click();
      await waitFor(page, () => dryRuns().length === 4, "returning from checked B to A sends a new dry run");
      await passed(page).waitFor();
      assert.deepEqual(dryRuns().at(-1).body, draftA);
      assert.ok(Date.now() - started < 15_000, "both returns to A happen within the app's cache freshness window");
      assert.equal(await submitButton(page).getAttribute("aria-disabled"), null);
      assert.equal(posts().filter((c) => c.query.dryRun !== "true").length, 0, "checking writes nothing");
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  await check("506-02 a required default copied from a key that cmapi fills in is filled, and the check runs", async () => {
    const keys = structuredClone(KEYS_479);
    keys.labels.properties["cmapi.net/team"]["x-cmapi-default-from"] = "company.net/app-environment";
    const { context, page, errors } = await fresh({ metadataKeys: keys });
    try {
      await newTab(page);
      await fill479(page);
      assert.equal(await page.getByLabel("Team (required)").inputValue(), "dev", "the cluster's environment, as cmapi fills it");
      await checkButton(page).click();
      await passed(page).waitFor();
      assert.equal("cmapi.net/team" in dryRuns().at(-1).body.labels, false, "unedited: cmapi fills it in");
      assert.match(await statusText(page), /cmapi\.net\/team = dev default from company\.net\/app-environment/);
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  await check("506-04 a refusal of an extra row, of the name or of the date shows on that control (P8)", async () => {
    const { context, page, errors } = await fresh({ metadataKeys: KEYS_479 });
    expectedStatus = [409, 422];
    try {
      await newTab(page);
      await fill479(page);
      await extraToggle(page).click();
      await page.getByRole("button", { name: "+ Add annotation" }).click();
      const key = page.getByLabel("Key of additional annotation 1");
      await key.fill("runbook");
      await extraToggle(page).click();
      api.state.answers.push(refusedWith([{ code: "reserved_key", key: "runbook" }]));
      await checkButton(page).click();
      await panel(page).getByText("The check failed: policy-violation").waitFor();
      assert.equal(await extraToggle(page).getAttribute("aria-expanded"), "true", "the refused row's section opens");
      await waitError(key, /^reserved_key/);
      await panel(page).getByRole("button", { name: "runbook: reserved_key" }).click();
      await page.waitForFunction(() => document.activeElement?.id.endsWith("-key"));
      await page.getByRole("button", { name: "Remove additional annotation 1" }).click();
      const exists = SAMPLES.problems["namespace-exists"].response.body;
      api.state.answers.push({ route: "POST /api/v1/clusters/CRC/namespaces", status: 409, body: exists });
      await checkButton(page).click();
      await panel(page).getByText("The check failed: namespace-exists").waitFor();
      await waitError(page.getByLabel("Namespace", { exact: true }), new RegExp(`^${exists.detail}`));
      await page.getByLabel("Expires (optional)").fill(isoAfter(3));
      api.state.answers.push({ route: "POST /api/v1/clusters/CRC/namespaces", status: 422,
        body: { type: "https://cmapi.ephico2real.com/problems/expiration-in-past", title: "expiration in past", status: 422, code: "expiration-in-past", detail: "The expiry must be after today" } });
      await checkButton(page).click();
      await panel(page).getByText("The check failed: expiration-in-past").waitFor();
      assert.match(await page.locator("#ns-exp-refused").innerText(), /^The expiry must be after today/);
      assert.equal(await page.getByLabel("Expires (optional)").getAttribute("aria-invalid"), "true");
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  await check("506-11 a region picked in one environment does not hide the clusters of another", async () => {
    const { context, page, errors } = await fresh({ metadataKeys: KEYS_479 });
    try {
      api.state.clusters = [...api.state.clusters, { ...RND_CLUSTER, labels: { ...RND_CLUSTER.labels, region: "rnd-only" } }];
      api.state.tiers = TIERS_RND;
      await newTab(page);
      await page.getByLabel("Region").selectOption("rnd-only");
      await panel(page).getByRole("group", { name: "Environment" }).getByRole("button", { name: "dev" }).click();
      await waitValue(page.getByLabel("Region"), "any");
      assert.equal(await page.getByLabel("Region").inputValue(), "any");
      await waitValue(page.getByLabel("Cluster"), "CRC");
      assert.equal(await page.getByLabel("Cluster").inputValue(), "CRC");
      assert.equal(await checkButton(page).isEnabled(), true);
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  });

  await check("506-12 a day that the month lacks (2099-02-30) is not a date: the picker says so on the field", async () => {
    const { context, page, errors } = await fresh({ metadataKeys: KEYS_479 });
    try {
      await newTab(page);
      const date = page.getByLabel("Expires (optional)");
      const pickerError = panel(page).locator(".pf-v6-c-date-picker__helper-text");
      await date.fill("2099-02-30");
      await date.press("Tab");
      await pickerError.getByText("Enter a date as YYYY-MM-DD.").waitFor();
      assert.equal(await date.getAttribute("aria-invalid"), "true");
      await date.fill("2099-03-02");
      await date.press("Tab");
      await pickerError.waitFor({ state: "detached" });
      assert.equal(await pickerError.count(), 0, "a real day: no error");
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
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
      await checkButton(page).click();
      await panel(page).locator(".pf-v6-c-alert").filter({ hasText: PASSED }).waitFor();
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
  // The tab's text, and the text of each open list that one of its comboboxes controls: the list is in document.body, outside
  // the tab panel, so that no card clips it (#535), and its menu holds it with any footer.
  const shownText = (page) => panel(page).evaluate((tab) => {
    const lists = [...tab.querySelectorAll("[role=combobox][aria-controls]")].map((box) => document.getElementById(box.getAttribute("aria-controls")))
      .filter((list) => list && !tab.contains(list)).map((list) => list.closest(".pf-v6-c-menu") ?? list);
    const found = [];
    for (const root of [tab, ...lists]) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) if (walker.currentNode.nodeValue.trim()) found.push(walker.currentNode.nodeValue.replace(/\s+/g, " ").trim());
      root.querySelectorAll("[placeholder]").forEach((el) => found.push(el.getAttribute("placeholder")));
      root.querySelectorAll("[aria-label]").forEach((el) => found.push(el.getAttribute("aria-label")));
      root.querySelectorAll("input, textarea, select").forEach((el) => el.value && found.push(el.value));
    }
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
      // New namespace (#479): the mockup is mockups/portal/new-namespace-479.html, on an instance with the configuration of
      // design section 3.1 (KEYS_479). The form with the mockup's own values typed in, the additional keys open with a row
      // refused and then a row that passes, a date, the passing check, a change after it, and an environment with
      // expiration off.
      const { context, page, errors } = await fresh({ metadataKeys: KEYS_479 });
      const shown = [];
      try {
        await newTab(page);
        shown.push(...await shownText(page));
        await page.getByLabel("Mnemonic (required)").fill("abc");
        await page.getByLabel("Namespace", { exact: true }).fill("payments");
        await page.getByLabel("Line of business (required)").fill("amgsst");
        await page.getByLabel("Critical level (required)").selectOption("1");
        await page.getByLabel("Cost center (optional)").fill("cc-4410");
        await page.getByLabel("Team DL (required)").fill("payments-team@company.net");
        await page.getByLabel("Justification").fill("Payments service dev namespace");
        await panel(page).getByRole("group", { name: "Tier" }).getByRole("button", { name: /^small/ }).click();
        shown.push(...await shownText(page));
        await panel(page).getByRole("button", { name: /^Additional labels and annotations \(optional\)/ }).click();
        shown.push(...await shownText(page));
        await panel(page).getByRole("button", { name: "+ Add label" }).click();
        await page.getByLabel("Key of additional label 1").fill("cmapi.net/team");
        await panel(page).getByText("This key has its own field above.").waitFor();
        shown.push(...await shownText(page));
        await page.getByLabel("Key of additional label 1").fill("squad");
        await page.getByLabel("Value of additional label 1").fill("checkout");
        await page.getByLabel("Expires (optional)").fill(isoAfter(25));
        await panel(page).getByText(/^Expires on \d{4}-\d{2}-\d{2}, in 25 days\.$/).waitFor();
        shown.push(...await shownText(page));
        await checkButton(page).click();
        await panel(page).getByText(PASSED).waitFor();
        shown.push(...await shownText(page));
        await page.getByLabel("Justification").fill("Payments service dev namespace, for the settlement API");
        await panel(page).getByText("Changed since the last check. Press Check (dry run) again.").waitFor();
        shown.push(...await shownText(page));
        api.state.metadataKeys = { ...KEYS_479, "x-cmapi-expiration": { environments: { rnd: KEYS_479["x-cmapi-expiration"].environments.rnd, dev: { enabled: false } } } };
        await page.reload();
        await checkButton(page).waitFor();
        shown.push(...await shownText(page));
      } finally {
        api.state.metadataKeys = KEYS_479;
      }
      // The mockup's strings that the page does not show, each with its reason (MOCKUP-CONTRACT.md, "New namespace").
      const MOCKUP_ONLY = [
        // Its sample clusters, sizes and approval: the page shows the API's clusters and tiers, and the plan's approval.
        "KIND_CMAPI_TEST (rnd)", "OCP_PROD_1 (prod)", "small: cpu 4, memory 16Gi", "1 from approver-platform",
        // Its hints for keys whose words come from the instance's file (title, description, the rule in words).
        "A copy of the namespace name.", "The cluster's environment.", "Who owns it, for cost and notices. Filled from Mnemonic; you can change it.",
        "Your team's mnemonic, 3 or 4 lowercase letters. Every namespace name starts with it.", "0 to 6.", "Optional, like cc-1234.", "An address in company.net.",
        // A required mark: the page says "(required)" or "(optional)" in words (WCAG 2.2, 3.3.2); an empty optional select is "—".
        "*", "(none)", "▸",
        // Its group-contact placeholder: the answer has no example for that key.
        "abc-team@company.net",
        // Its expiry hint claims a delete request; x-cmapi-expiration does not say deleteAfterGrace, so the page says the grace only.
        "Notices to the team DL 14, 7 and 1 days before. It keeps running 7 days after the date, then a delete request is opened.",
        // Its extra-key hint names reserved prefixes; the answer names none where no allowed prefix meets one.
        "Allowed: no prefix, or *.company.net/. Not kubernetes.io/, openshift.io/ or a key that has its own field above.",
        // Its idle status is one sentence around a bold button name; the page says the same sentence whole.
        "Not checked yet. Press", "to ask cmapi whether this request passes."];
      const html = readFileSync(join(app, "..", "mockups", "portal", "new-namespace-479.html"), "utf8");
      const block = html.slice(html.indexOf("<h1>New namespace</h1>"), html.indexOf("</aside>"));
      const fromMockup = [...new Set([...block.replace(/<[^>]+>/g, "\n").split("\n").map((t) => t.replace(/\s+/g, " ").trim()).filter(Boolean),
        ...[...block.matchAll(/(?:placeholder|aria-label)="([^"]+)"/g)].map((m) => m[1])])].filter((t) => !MOCKUP_ONLY.includes(t));
      // The mockup's script says these in the states driven above (render(), invalidate(), the check's handler, drawRows(), keyError()).
      const SCRIPT = ["Changed since the last check. Press Check (dry run) again.", "The check passed (dry run, 200).", "cmapi will set:", "from the namespace",
        "from the environment", "from the request", "None. Add one only if you need it.", "This key has its own field above.", "1 label, 0 annotations", "1 of 50",
        "Not checked yet. Press Check (dry run) to ask cmapi whether this request passes.", "never (expiration off here)"];
      fromMockup.push(...SCRIPT);
      const plan = SAMPLES.operations["namespaces_create_namespace:dryRun"].response.body;
      const tiers = SAMPLES.operations.tiers_tiers.response.body.environments.dev.tiers.filter((t) => !t.custom);
      const rules = [KEYS_479.labels, KEYS_479.annotations].flatMap((map) => Object.entries(map.properties).filter(([, p]) => !p["x-cmapi-operator-only"])
        .map(([key, p]) => [key, p.title ?? key, `${p.title ?? key} (${(map.required ?? []).includes(key) ? "required" : "optional"})`, p.description, ...(p.examples ?? [])])).flat();
      const data = ["rnd", "dev", "CRC", "us-central", "any", "abc", "payments", "amgsst", "cc-4410", "checkout", "squad", "payments-team@company.net", "ola@ephico2real.com",
        "Non-production", "rnd, dev", ...tiers.map((t) => t.name), ...plan.approval.reasons, "prod portal", "staging portal", "qa, uat", "fits", "1", "true", "managed", "nonprod",
        "Payments service dev namespace, for the settlement API", "Prune=confirm,ServerSideApply=true", "(planned)", "ola", "e.g. value", "e.g. example.company.net/key",
        /^\d{4}-\d{2}-\d{2}$/, ...rules];
      // The portal's own words (MOCKUP-CONTRACT.md, "New namespace"): the environment, region and cluster of the API, the tier's
      // sizes, the plan's checks and approval, the key and words of each field from the answer, the name's length, the date's
      // rules from x-cmapi-expiration, the additional keys' rules from the answer, and the plan's own namespace.yaml.
      const ADDED = ["Environment", "Region", "Any region", "From clusters.yaml metadata.", "This is the Non-production portal: it serves rnd, dev only.",
        "The dev clusters that take writes, from GET /api/v1/clusters. Placement is not on the API yet (#303).",
        "cmapi writes the tier's ResourceQuota and LimitRange (config/tiers.yaml) into the namespace folder.", "Leave empty for a team-wide namespace: abc-dev.", "Expires (optional)", "Open the calendar",
        "Requested by ola (ola@ephico2real.com), from your sign-in.", "Filled from Mnemonic; you can change it.", "Environment served", "Capacity", "fits on fresh data", "Expiry",
        "Approval", "Lands in Git", "Nothing is written yet.", "Check (dry run) asks cmapi which approval applies.", "Self-approval is allowed in dev.", "Key", "Value",
        "Not a reserved prefix, a key that cmapi sets, or a key that has its own field above.", "Allowed: no prefix, or *.company.net/.", "Notices to the team DL 14, 7 and 1 days before. It keeps running 7 days after the date.",
        "Expiration is turned off for this environment (expiration.yaml: enabled: false). The namespace is permanent.", "YYYY-MM-DD", "Key of additional label 1", "Value of additional label 1",
        "Remove additional label 1", "This is the", "portal: it serves", "only.", "prod", "…-",
        // PatternFly's words for a screen reader on an error line (HelperTextItem variant="error").
        "error status",
        /^From the dry run: clusters\/CRC\/namespaces\/abc-payments-dev\/namespace\.yaml$/, "apiVersion: v1", "kind: Namespace", "metadata:", "labels:", "annotations:", "name:",
        "# cmapi.net/managed, cluster-id, request-id, tier … added by cmapi", "# automatic", "# from Mnemonic", "# additional", "# from Expires", "# required, not set yet",
        "default from company.net/mnemonic", "Each value up to 4096 bytes, 65536 in all.", "0 of 50 · 0 of 65536 bytes", "never (permanent)",
        /^(Will be created as )?(abc|…)-(payments|…)-(dev|…)$/, /^\(\d+ of 63 characters\)$/, /^\d+ cores · \d+Gi$/, /^[a-z]+: \d+ cores · \d+Gi · \d+ pods$/, /^\d+ approvals? in cmapi from /,
        /^[a-z]+-create · \d+ of /, /^[a-z]+ in \[[a-z, ]+\]$/, /^Expires on \d{4}-\d{2}-\d{2}, in \d+ days\.$/, /^\d{4}-\d{2}-\d{2} \(in \d+ days\)$/,
        /^\d{4}-\d{2}-\d{2}, \d+ days \(limit 180\)$/, /^cpu \d+% · memory \d+% · binds on (cpu|memory)$/, /^Plan hash [0-9a-f]{4}…$/, /^[✓!✕]$/,
        /^clusters\/CRC\/namespaces\/abc-payments-dev\/(namespace\.yaml)?$/, /^[\w./-]+ = [\w.@-]+$/];
      const strings = [...data, ...ADDED].filter((k) => typeof k === "string");
      const patterns = [...data, ...ADDED].filter((k) => k instanceof RegExp);
      // The preview's YAML is one text: the form's lines or the plan's file, built from the data above. Check 479-P6 compares it
      // line by line; here it is set aside so that a key or value in it does not count as an invented string.
      counts.new = compare("New namespace", fromMockup, shown.filter((t) => !t.startsWith("apiVersion: v1")), [...strings, ...LIBRARY], patterns);
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
  // PatternFly's Tabs show or hide their scroll buttons after two timers (react-core 6.7.0, Tabs.js): handleScrollButtons
  // decides 100 ms after a mount, a resize or a scroll of the tab list, and componentDidUpdate sets pf-m-scrollable 100 ms
  // after that, which starts the buttons' 125 ms margin, transform and opacity transitions. A transition exists only once its
  // style change happens, so document.getAnimations() cannot see one that a timer has not started yet: a read in that gap
  // passes with nothing running, or fails when the timer fires between two reads (#347, the six transitions of "new 390
  // light"). So the read first waits for the tab bars' end state, with the first and the last tab judged as PatternFly
  // judges them (helpers/util.js, isElementInView with partial false): when either is out of view, pf-m-scrollable is set;
  // when both are in view, no scroll button is rendered (hideScrollButtons removes them at their transitionend).
  const TABS_AT_REST = `[...document.querySelectorAll(".pf-v6-c-tabs:not(.pf-m-vertical)")].every((tabs) => {
    const list = tabs.querySelector(":scope > [role=tablist]");
    if (!list?.firstElementChild) return true;
    const box = list.getBoundingClientRect(), left = Math.ceil(box.left), right = Math.floor(box.right);
    const inView = (el) => {
      const r = el.getBoundingClientRect(), l = Math.ceil(r.left), rr = Math.floor(r.right);
      return (l >= left && rr <= right) || (box.width < r.width && ((l < left && rr > left) || (rr > right && l < right)));
    };
    const overflows = !inView(list.firstElementChild) || !inView(list.lastElementChild);
    const scrollable = tabs.classList.contains("pf-m-scrollable"), buttons = tabs.querySelector(":scope > .pf-v6-c-tabs__scroll-button") !== null;
    return overflows ? scrollable : !scrollable && !buttons;
  })`;
  /** Waits until nothing will move when the page is read: the tab bars at rest, then each finite animation ended. */
  async function settle(page) {
    try {
      await page.waitForFunction(TABS_AT_REST);
    } catch {
      assert.fail(`the tab bar's scroll buttons never came to rest: ${await page.evaluate(() => [...document.querySelectorAll(".pf-v6-c-tabs")].map((t) => t.className).join(" | "))}`);
    }
    // A click before the read (Reject, Plan change) starts transitions of its own, which can start after the first wait began.
    for (let round = 0; round < 5 && (round === 0 || await running(page)); round++) await settled(page);
  }

  await check("7 layout at 390, 820 and 1440 px in each theme, and axe at phone and desktop width", async () => {
    for (const width of [390, 820, 1440]) {
      const { context, page, errors } = await fresh({ width });
      await open(page);
      await page.locator("table[aria-label=Requests] tbody tr").first().waitFor();
      for (const theme of ["light", "dark"]) {
        await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
        await settle(page);
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

  // One check for each tab (#508, #521): the six views and their 24 axe scans took 67 s of the 90 s CHECK_TIMEOUT_MS on a
  // loaded Mac in one check. The time is the scans that the check asserts, so it is split, with the same assertions in each part.
  const NEW_LAYOUT_VIEWS = [
    ["workflow", "requester", [applied, mergeFailed], async (page) => { await open(page, `#workflow?request=${applied.requestId}`); await banner(page).waitFor(); }],
    ["new", "requester", undefined, async (page) => {
      await newTab(page);
      await fillForm(page);
      await checkButton(page).click();
      await panel(page).getByText(PASSED).waitFor();
    }],
    ["approvals", "approver", [ola, second], async (page) => {
      await open(page, "#approvals");
      // The reason field is a state that opens on a click: it is scanned too.
      await cardOf(page, second.requestId).getByRole("button", { name: "Reject" }).click();
      await cardOf(page, second.requestId).getByLabel("Why are you rejecting it? (required, sent to the requester)").waitFor();
    }],
    // The company instance's form (#336), with a value refused in the browser.
    ["new-company", "requester", undefined, async (page) => {
      await newTab(page);
      await page.getByLabel("company.net/mnemonic (required)").fill("ABC");
      await page.getByLabel("company.net/lob (required)").fill("amgsst");
      await page.getByLabel("company.net/cl (required)").selectOption("1");
      await waitError(page.getByLabel("company.net/mnemonic (required)"), /^Not valid: /);
    }, { metadataKeys: COMPANY_KEYS }],
    // #479: the form of design section 3.1 with the additional keys open, a row refused, a date past the limit (its
    // warning) and a check that did not run; then the same form fixed and checked, with the plan's file in the preview.
    ["new-479-problems", "requester", undefined, async (page) => {
      await newTab(page);
      await fill479(page);
      await panel(page).getByRole("button", { name: /^Additional labels and annotations \(optional\)/ }).click();
      await panel(page).getByRole("button", { name: "+ Add label" }).click();
      await page.getByLabel("Key of additional label 1").fill("kubernetes.io/team");
      await panel(page).getByRole("button", { name: "+ Add annotation" }).click();
      await page.getByLabel("Key of additional annotation 1").fill("runbook.company.net/url");
      await page.getByLabel("Value of additional annotation 1").fill("https://wiki.company.net/abc/runbook");
      await page.getByLabel("Expires (optional)").fill(isoAfter(200));
      await checkButton(page).click();
      await panel(page).getByText("The check did not run. Fix these:").waitFor();
    }, { metadataKeys: KEYS_479 }],
    ["new-479-checked", "requester", undefined, async (page) => {
      await newTab(page);
      await fill479(page);
      await panel(page).getByRole("button", { name: /^Additional labels and annotations \(optional\)/ }).click();
      await panel(page).getByRole("button", { name: "+ Add label" }).click();
      await page.getByLabel("Key of additional label 1").fill("team.company.net/squad");
      await page.getByLabel("Value of additional label 1").fill("checkout");
      await page.getByLabel("Expires (optional)").fill(isoAfter(25));
      await checkButton(page).click();
      await panel(page).getByText(PASSED).waitFor();
    }, { metadataKeys: KEYS_479 }]
  ];
  for (const [tab, user, items, reach, options = {}] of NEW_LAYOUT_VIEWS) {
    await check(`7 the Workflow, New namespace and Approvals tabs at 390, 820 and 1440 px in each theme, and axe at phone and desktop width: ${tab}`, async () => {
      let scans = 0;
      for (const width of [390, 820, 1440]) {
        const { context, page, errors } = await fresh({ user, items, width, ...options });
        await reach(page);
        // The #479 views are long forms in a scrolling main area: the window grows to the whole form, so the screenshot shows it.
        if (tab.startsWith("new-479")) {
          // The tallest scroller is the page's own (PatternFly's main area), whichever element it is at this width.
          const height = await page.evaluate(() => Math.max(...[...document.querySelectorAll("*")].map((el) => el.scrollHeight)));
          await page.setViewportSize({ width, height: height + 200 });
        }
        for (const theme of ["light", "dark"]) {
          await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
          await settle(page);
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
      console.log(`  ${tab}: 3 widths, 2 themes, ${scans} axe scans`);
    });
  }

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
    await next.click();
    await waitQuotaRange(page, "26–50 of 70 · A–Z");
    assert.ok(await prev.isEnabled() && await next.isEnabled(), "the retained page has both cursors");
    // The sort: the highest use first. Until its answer arrives, the table keeps the A–Z rows (keepPreviousData): it is busy,
    // and the pager says the order of the rows it shows, not the one asked for (#392, #317). The stand-in holds the answer,
    // so that moment is always seen, and then the rows are read only once the pager says the new order.
    let answer;
    api.state.hold = { match: (c) => c.path === "/api/v1/quotas" && c.query.sort === "used", until: new Promise((resolve) => { answer = resolve; }) };
    await panel(page).getByRole("group", { name: "Sort" }).getByRole("button", { name: "% used" }).click();
    await page.locator("table[aria-label=Quotas][aria-busy=true]").waitFor();
    assert.match(await panel(page).innerText(), /26–50 of 70 · A–Z/, "the pager says the order of the rows shown");
    assert.doesNotMatch(await panel(page).innerText(), /most used first/, "no order that the rows shown do not have");
    assert.deepEqual((await quotaRows(page)).map((r) => r[0]), named.slice(25, 50).map((r) => r.name), "the A–Z rows stay while the sort loads");
    const letterBar = panel(page).getByRole("group", { name: "Jump to the first namespace starting with a letter" });
    assert.equal(await letterBar.locator("button.pf-m-primary").textContent(), named[25].name[0]);
    // Their cursor is the A–Z answer's: paging from it with the sort asked for is refused (400 invalid-cursor), so the pager is off.
    const pending = page.getByRole("button", { name: "Next ›" }).first();
    assert.equal(await prev.getAttribute("aria-disabled"), "true", "Previous stays off while the sort loads");
    await prev.click({ force: true });
    assert.equal(await pending.getAttribute("aria-disabled"), "true", "Next is off while the rows shown are the last answer's");
    await pending.click({ force: true });
    assert.deepEqual(quotaCalls().filter((c) => c.query.cursor && c.query.sort === "used").map((c) => c.query), [], "no page is asked for with the last answer's cursor and the new sort");
    answer();
    api.state.hold = null;
    await waitQuotaRange(page, "1–25 of 70 · most used first");
    assert.equal(await letterBar.locator("button.pf-m-primary").count(), 0);
    assert.ok(await next.isEnabled() && await prev.isDisabled());
    assert.equal(await page.locator("table[aria-label=Quotas]").getAttribute("aria-busy"), null, "the table is not busy once its rows are the answer's");
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
    assert.deepEqual(await hiddenOptions(page, "#q-sug"), [], "every match is on the screen, not clipped by the card (#535)");
    await box.press("ArrowDown");
    await box.press("ArrowDown");
    await box.and(page.locator('[aria-activedescendant="q-opt-1"]')).waitFor();
    assert.equal(await box.getAttribute("aria-activedescendant"), "q-opt-1", "the second match is active");
    assert.equal(await options.nth(1).getAttribute("aria-selected"), "true");
    await box.press("Enter");
    const picked = want[1];
    await page.waitForFunction((name) => document.querySelector("table[aria-label=Quotas] tbody tr td")?.innerText === name, picked.name);
    sentQuery({ limit: "50", startsWith: picked.name }, "the filters start again, and the page starts at the match");
    assert.deepEqual((await quotaRows(page))[0].at(-1), "Selected", "the match is the namespace shown below");
    assert.equal(new URL(page.url()).hash, `#quotas?ns=${encodeURIComponent(`${picked.clusterId}/${picked.name}`)}`);
    await waitValue(box, "");
    await panel(page).getByRole("heading", { name: `${picked.name} on ${picked.clusterId}` }).waitFor();
    // No match, and Escape.
    await box.fill("zzz");
    await page.getByRole("listbox").getByText('No namespace matches "zzz".').waitFor();
    await box.press("Escape");
    await box.and(page.locator("[aria-expanded=false]")).waitFor();
    assert.equal(await box.getAttribute("aria-expanded"), "false");
    await checkComboBoxLifecycle(page, box, "#q-sug", "pay", "#requests");
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
    await callout.waitFor({ state: "detached" });
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
    // PatternFly's focus trap gives the focus back after the dialog leaves the DOM, not with it: wait for it, with a bound.
    await page.waitForFunction(() => document.activeElement?.textContent === "Remove protection", null, { timeout: 5_000 });
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
      body: { type: "https://cmapi.ephico2real.com/problems/forbidden", title: "forbidden", status: 403, code: "forbidden", detail: `Needs namespaces:protect in ${protectedTarget.env}. Keys: cmapi.net/protected.` } });
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
    await checkButton(page).click();
    await panel(page).locator(".pf-v6-c-alert").filter({ hasText: PASSED }).waitFor();
    assert.deepEqual(posts().at(-1).body.labels, { "cmapi.net/team": "payments" }, "unchecked: no protection key at all");
    await box.check();
    assert.match(await panel(page).innerText(), /Operators only\. Adds cmapi\.net\/protected=true: cmapi refuses a delete request for this namespace until an operator removes it\./);
    await checkButton(page).click();
    await panel(page).locator(".pf-v6-c-alert").filter({ hasText: PASSED }).waitFor();
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
        await settle(page);
        const card = detailCard(page, protectedTarget);
        await card.scrollIntoViewIfNeeded();
        await card.screenshot({ path: join(out, `protection-${width}-${theme}.png`) });
        const scan = await new AxeBuilder({ page }).analyze();
        assert.deepEqual(scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.html}`), [], `axe at ${width} ${theme}`);
        await card.getByRole("button", { name: "Remove protection" }).click();
        await dialog(page).locator(".pf-v6-c-alert").filter({ hasText: "1 approval in cmapi" }).waitFor();
        await settle(page);
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
        await settle(page);
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

  await check("407 Expiration keeps both cursors off while an environment loads", async () => {
    const { context, page } = await expFresh({ expirations: expirationsFrom(61, EXP_TODAY) });
    await open(page, "#expiration?state=all");
    await checkHeldPage(page, {
      label: "Expiration", path: "/api/v1/expirations",
      change: () => panel(page).getByRole("group", { name: "Env" }).getByRole("button", { name: "rnd", exact: true }).click(),
      match: (q) => q.env === "rnd" && !q.cursor, after: /^1–25 of 30/
    });
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
          await settle(page);
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

  // One check for each view (#508): the 16 axe scans of the four views took 73 s of the 91 s that the whole took on a
  // loaded Mac (one AxeBuilder.analyze() of the Quotas page: 5.3 s, in runPartial and finishRun), past CHECK_TIMEOUT_MS.
  // That time is the scans that the check asserts, so it is split, with the same assertions in each part.
  const QUOTA_LAYOUT_VIEWS = [
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
  for (const [view, user, reach] of QUOTA_LAYOUT_VIEWS) {
    await check(`7 the Quotas and KPIs tabs at 390, 820 and 1440 px in each theme, and axe at phone and desktop width: ${view}`, async () => {
      let scans = 0;
      for (const width of [390, 820, 1440]) {
        const { context, page, errors } = await quotaFresh({ user, width, kpi: podKpi });
        await reach(page);
        for (const theme of ["light", "dark"]) {
          await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
          await settle(page);
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
      console.log(`  ${view}: 3 widths, 2 themes, ${scans} axe scans`);
    });
  }

  // Portal slice 4, the Policies part (#302). The fleet is CRC with 30 failing, warning and erroring rows built from the recorded
  // row of GET /api/v1/policies/results, and one cluster in each other state of the API. Each expectation is written from the
  // mockup's forms (policiesView()) and the API's contract, not from the page's code.
  const polCalls = () => calls("/api/v1/policies/results");
  const refusedCalls = () => calls("/api/v1/policies/rejections");
  const sentPol = (want, why) => assert.ok(polCalls().some((c) => isDeepStrictEqual(c.query, want)), `${why}: ${JSON.stringify(want)} was not sent; the calls were ${JSON.stringify(polCalls().map((c) => c.query))}`);
  const tableRows = (page, label) => page.locator(`table[aria-label="${label}"] tbody tr`).evaluateAll((trs) => trs.map((tr) => [...tr.children].map((td) => td.innerText.replace(/\s+/g, " ").trim())));
  const polCard = (page, title) => panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: title }) });
  const openPol = async (page, hash = "#policies") => {
    await open(page, hash);
    await page.locator("table[aria-label=Clusters] tbody tr").first().waitFor();
  };
  // #537: Results by policy is last and starts closed, 25 rows a page. The checks that read every policy open it with 100 a page.
  const polToggle = (page, title) => polCard(page, title).locator(".pf-v6-c-card__header-toggle button");
  const openPolicies = async (page, perPage = 25) => {
    await polToggle(page, "Results by policy").click();
    await page.locator("table[aria-label='Results by policy']").waitFor();
    if (perPage !== 25) {
      await panel(page).getByRole("group", { name: "Per page" }).getByRole("button", { name: String(perPage), exact: true }).click();
      await page.waitForFunction((n) => document.querySelector("[aria-label='Per page'] .pf-m-selected")?.innerText === String(n), perPage);
    }
  };
  // The mockup's cluster row: id, env, the mode, the bundle, ready, the four counts ("—", never 0, when unknown) and the state's word.
  const STATE_WORD = { ok: () => "ok", "not-installed": () => "Kyverno not installed", forbidden: () => "no access to the reports", "not-imported": () => "not imported", unreachable: (c) => `unreachable since ${c.asOf.slice(11, 16)}`,
    stale: (c) => `stale since ${c.asOf.slice(11, 16)}`, capped: (c) => `${c.dropped} rows not listed`, drift: () => "off the bundle", loading: () => "loading", "mode-off": () => "mode off", "engine-off": () => "Kyverno off" };
  const n = (v) => (v === null || v === undefined ? "—" : String(v));
  const expectedCluster = (c) => {
    const b = c.bundle, off = b ? [b.expected - b.live && `${b.expected - b.live} missing`, b.live - b.current && `${b.live - b.current} differ`, b.actionsDifferTotal && `${b.actionsDifferTotal} with other actions`].filter(Boolean) : [];
    return [c.clusterId, c.env, c.mode, b ? (off.length ? off.join(", ") : "current") : "—", b ? `${b.ready} / ${b.expected}` : "—", n(c.counts?.pass), n(c.counts?.fail), n(c.counts?.warn), n(c.counts?.error), STATE_WORD[c.state](c)];
  };
  const keyOfRow = (r) => [r.namespace, r.resource.kind, r.resource.name, r.policy, r.kyvernoRule ?? ""].join("/");
  const byKey = (a, b) => (keyOfRow(a) < keyOfRow(b) ? -1 : keyOfRow(a) > keyOfRow(b) ? 1 : 0);
  const expectedResult = (r) => [r.namespace, `${r.resource.kind}/${r.resource.name}`, `${r.policy}${r.rule ? ` rule ${r.rule}` : ""}`, r.result, r.message, r.clusterId];

  await check("20 Policies: the clusters, the policies and the rows of GET /api/v1/policies/results cell by cell; a state is never a zero; the cluster chips, Show failures and the pages are API parameters", async () => {
    const fleet = policyFleet();
    const { context, page, errors } = await fresh({ policies: fleet });
    await openPol(page);
    assert.deepEqual(await tableRows(page, "Clusters"), fleet.clusters.map(expectedCluster));
    const unknown = (await tableRows(page, "Clusters")).filter((r) => ["Kyverno not installed", "no access to the reports", "not imported"].includes(r[9]) || r[9].startsWith("unreachable"));
    assert.equal(unknown.length, 4);
    assert.ok(unknown.every((r) => r.slice(5, 9).every((v) => v === "—")), "a cluster whose counts are unknown shows —, never 0");
    // Each state's tone: unreachable and forbidden danger, capped, stale and drift warning, the rest (not imported among them) info, ok success (the mockup's stateTone).
    const tones = await polCard(page, "Clusters").locator("tbody tr").evaluateAll((trs) => trs.map((tr) => tr.lastElementChild.querySelector(".pf-v6-c-label").className.match(/pf-m-(success|warning|danger|info)/)?.[1] ?? "grey"));
    assert.deepEqual(tones, ["success", "warning", "danger", "info", "danger", "warning", "warning", "info"]);
    const lede = await panel(page).locator("p").first().innerText();
    assert.equal(lede, `What the Kyverno bundle decided on each cluster of the nonprod instance, read from the policy reports, beside cmapi's own refusals at plan time and in CI. The same bundle runs in all three places. Pinned for this instance: ${fleet.policy.kyvernoVersion ? `Kyverno ${fleet.policy.kyvernoVersion}` : "no Kyverno CLI pinned (outside the image)"}; audit in dev, rnd.`);
    const failing = fleet.clusters.reduce((t, c) => t + (c.counts?.fail ?? 0), 0);
    await panel(page).getByText(`${failing} failing · 1 cluster off the bundle`).waitFor();
    // The policies: the API's, from the bundle, each with what it checks and its counts. None is named by the page.
    await openPolicies(page, 100);
    await panel(page).getByText("1840 results on namespaces that cmapi does not manage, 41 of other policies and 2 of policies no longer on the cluster are counted and not shown.").waitFor();
    const policyRows = await tableRows(page, "Results by policy");
    assert.equal(policyRows.length, fleet.policies.length);
    const first = fleet.policies[0];
    assert.deepEqual(policyRows[0].slice(0, 3), [first.name, first.kind, `${first.check.kind} ${first.check.key ?? "keys that no stanza declares"}: ${first.check.rule}`]);
    // The rows: by namespace, 25 a page, then the rest.
    const ordered = [...fleet.items].sort(byKey);
    assert.deepEqual(await tableRows(page, "Failing resources"), ordered.slice(0, 25).map(expectedResult));
    sentPol({ result: "fail,warn,error", limit: "25" }, "the first call");
    const pills = await polCard(page, /^Failing, warning and erroring resources/).locator("tbody tr").evaluateAll((trs) => trs.map((tr) => tr.children[3].querySelector(".pf-v6-c-label").className.match(/pf-m-(success|warning|danger|info)/)?.[1]));
    assert.deepEqual(pills, ordered.slice(0, 25).map((r) => ({ fail: "danger", warn: "warning", error: "info" })[r.result]), "fail danger, warn warning, error info");
    await polCard(page, /^Failing, warning and erroring resources/).getByRole("button", { name: "Next ›" }).click();
    await panel(page).getByText("26–30 of 30 · by namespace").waitFor();
    assert.deepEqual(await tableRows(page, "Failing resources"), ordered.slice(25).map(expectedResult));
    await polCard(page, /^Failing, warning and erroring resources/).getByRole("button", { name: "‹ Previous" }).click();
    await panel(page).getByText("1–25 of 30 · by namespace").waitFor();
    // A chip is the API's clusterId; Show failures is its policy. Each is a new first page, and in the address.
    await panel(page).getByRole("group", { name: "Cluster" }).getByRole("button", { name: "CRC", exact: true }).click();
    await page.waitForFunction(() => location.hash === "#policies?cluster=CRC");
    sentPol({ result: "fail,warn,error", limit: "25", clusterId: "CRC" }, "the chip");
    const second = ordered.find((r) => r.policy !== ordered[0].policy).policy;
    await polCard(page, "Results by policy").locator("tbody tr").filter({ hasText: second }).getByRole("button", { name: "Show failures" }).click();
    await panel(page).getByRole("heading", { name: `Failing, warning and erroring resources · ${second} · CRC` }).waitFor();
    sentPol({ result: "fail,warn,error", limit: "25", clusterId: "CRC", policy: second }, "Show failures");
    assert.deepEqual(await tableRows(page, "Failing resources"), ordered.filter((r) => r.policy === second).slice(0, 25).map(expectedResult));
    await panel(page).getByText(`GET /api/v1/policies/results?result=fail,warn,error&clusterId=CRC&policy=${second} · filtered to the environments your roles cover · paged like every list.`).waitFor();
    await polCard(page, "Results by policy").getByRole("button", { name: "Showing" }).click();
    await panel(page).getByRole("heading", { name: "Failing, warning and erroring resources · CRC", exact: true }).waitFor();
    // Clusters whose counts are unknown are no chip: the mockup's chips are the live clusters.
    assert.deepEqual(await panel(page).getByRole("group", { name: "Cluster" }).getByRole("button").allInnerTexts(), ["All clusters", ...fleet.clusters.filter((c) => c.counts !== null).map((c) => c.clusterId)]);
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("20 Policies: the refusals of GET /api/v1/policies/rejections, with the stage, the policy or check, Kyverno's warnings beside cmapi's errors, and the username only", async () => {
    const rejections = rejectionsFrom(3);
    const { context, page, errors } = await fresh({ rejections });
    await openPol(page);
    await page.locator("table[aria-label='Refused by cmapi'] tbody tr").first().waitFor();
    const got = await tableRows(page, "Refused by cmapi");
    const [plan, warned, ci] = rejections;
    assert.equal(got.length, 3);
    assert.deepEqual(got[0].slice(1, 3), [`${plan.clusterId} · ${plan.namespace}`, "plan (422)"]);
    assert.equal(got[0][3], "metadata-keys rule reserved_key");
    assert.equal(got[0][4], `kubernetes.io/team is reserved; use cmapi.net/team (2 times that day) warning: ${plan.findings[1].policy} ${plan.findings[1].rule}: ${plan.findings[1].message}`);
    assert.equal(got[0][5], plan.username);
    assert.deepEqual(got[1].slice(2, 4), ["plan, warned", `${warned.findings[0].policy} rule ${warned.findings[0].rule}`]);
    assert.deepEqual([got[2][2], got[2][3]], ["CI", "cmapi-check"]);
    assert.equal(got[2][4], ci.findings[0].message);
    const text = await polCard(page, "Refused by cmapi before Git · last 7 days").innerText();
    assert.doesNotMatch(text, /@|employee|justification/i, "no email, employee ID or justification");
    assert.ok(refusedCalls().every((c) => c.query.since === "7d"), "the mockup's window");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("407 Policies results keep both cursors off while a cluster loads", async () => {
    const { context, page } = await fresh({ policies: policyFleet(policyRowsFrom(61)) });
    await openPol(page);
    await openPolicies(page);
    await checkHeldPage(page, {
      label: "Failing resources", path: "/api/v1/policies/results",
      change: () => panel(page).getByRole("group", { name: "Cluster" }).getByRole("button", { name: "CRC", exact: true }).click(),
      match: (q) => q.clusterId === "CRC" && !q.cursor, after: /^1–25 of 61/
    });
    await context.close();
  });

  await check("407 Policies refusals keep both cursors off while another page loads", async () => {
    const { context, page } = await fresh({ rejections: heldPageRows().rejections });
    await openPol(page);
    await checkHeldPage(page, {
      label: "Refused by cmapi", path: "/api/v1/policies/rejections",
      change: (next) => next.click(), match: (q) => !!q.cursor, after: /^51–61 of 61/, lastPage: true
    });
    await context.close();
  });

  await check("21 Policies states: loading, empty, a 403, a 5xx with Try again, a stale cursor, the refusals' 403 in their panel only, and engine none", async () => {
    {
      const { context, page, errors } = await fresh();
      api.state.delayMs = 400;
      await page.goto(`${portal.page}#policies`);
      await page.getByRole("status").filter({ hasText: "Loading the policy results…" }).waitFor();
      await page.locator("table[aria-label=Clusters] tbody tr").first().waitFor();
      api.state.delayMs = 0;
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ mode: "empty" });
      await openPol(page);
      await panel(page).getByText("Nothing failing for this selection.").waitFor();
      await panel(page).getByText("Nothing refused in the last 7 days.").waitFor();
      await panel(page).getByText("0 results", { exact: true }).waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      expectedStatus = [403];
      const { context, page, errors } = await fresh();
      expectedStatus = [403];
      api.state.answers.push({ route: "GET /api/v1/policies/results", status: 403, body: { type: "https://cmapi.ephico2real.com/problems/forbidden", title: "forbidden", status: 403, code: "forbidden", detail: "Missing permission objects:read: no role in your token grants it (roles: ['cmapi-none'])" } });
      await open(page, "#policies");
      await panel(page).getByRole("heading", { name: "You do not have permission to see policy results." }).waitFor();
      assert.match(await panel(page).innerText(), /Missing permission objects:read/);
      assert.equal(await panel(page).getByRole("button", { name: "Try again" }).count(), 0, "a 403 offers no action");
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh();
      expectedStatus = [500];
      api.state.answers.push({ route: "GET /api/v1/policies/results", status: 500, body: { type: "https://cmapi.ephico2real.com/problems/internal-error", title: "internal-error", status: 500, code: "internal-error", detail: "The watch cache did not answer." } });
      await open(page, "#policies");
      const alert = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "The policy results did not load." });
      await alert.waitFor();
      assert.match(await alert.innerText(), /The watch cache did not answer\./);
      await alert.getByRole("button", { name: "Try again" }).click();
      await page.locator("table[aria-label=Clusters] tbody tr").first().waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh();
      await openPol(page);
      expectedStatus = [400];
      api.state.answers.push({ route: "GET /api/v1/policies/results", status: 400, body: { type: "https://cmapi.ephico2real.com/problems/invalid-cursor", title: "invalid-cursor", status: 400, code: "invalid-cursor", detail: "Filters or sort changed since this cursor was issued" } });
      await polCard(page, /^Failing, warning and erroring resources/).getByRole("button", { name: "Next ›" }).click();
      await panel(page).getByText("This page link is out of date").waitFor();
      await panel(page).getByRole("button", { name: "Back to the first page" }).click();
      await panel(page).getByText("1–25 of 30 · by namespace").waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // The refusals fail on their own: the results stay, and the 403 is in the refusals' panel only.
      const { context, page, errors } = await fresh();
      expectedStatus = [403];
      api.state.answers.push({ route: "GET /api/v1/policies/rejections", status: 403, body: { type: "https://cmapi.ephico2real.com/problems/forbidden", title: "forbidden", status: 403, code: "forbidden", detail: "Missing permission requests:read: no role in your token grants it (roles: ['cmapi-none'])" } });
      await openPol(page);
      await polCard(page, "Refused by cmapi before Git · last 7 days").getByRole("heading", { name: "You do not have permission to see the refusals." }).waitFor();
      assert.equal((await tableRows(page, "Failing resources")).length, 25);
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // policy.engine none: the tab says Kyverno is off and shows cmapi's refusals only.
      const off = policyFleet([]);
      off.policy = { ...off.policy, engine: "none", environments: { dev: "off", rnd: "off" } };
      off.clusters = off.clusters.slice(0, 1).map((c) => policyCluster(c, { clusterId: c.clusterId, state: "engine-off", mode: "off", stateDetail: "policy.engine is none on this instance: no Kyverno runs and no report is read" }));
      off.policies = [];
      const { context, page, errors } = await fresh({ policies: off });
      await open(page, "#policies");
      await panel(page).getByText("Kyverno is off on this instance").waitFor();
      await page.locator("table[aria-label='Refused by cmapi'] tbody tr").first().waitFor();
      assert.equal(await panel(page).locator("table[aria-label=Clusters], table[aria-label='Results by policy'], table[aria-label='Failing resources']").count(), 0, "no results panel with engine none");
      assert.match(await panel(page).locator("p").first().innerText(), /Pinned for this instance: no policy engine \(policy\.engine: none\)\.$/);
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("22 Policies: no zero for what is not known: a policy on no cluster with counts, the head with no cluster counted, and CRC with Kyverno and none of cmapi's policies (OB3, #384)", async () => {
    // Kyverno not installed anywhere: no count is known, so no 0 is shown, in the head or in the policies.
    const none = policyFleet([]);
    none.clusters = none.clusters.filter((c) => c.state === "not-installed");
    none.perCluster = {};
    {
      const { context, page, errors } = await fresh({ policies: none });
      await openPol(page);
      await panel(page).getByText("— failing · 0 clusters off the bundle").waitFor();
      await openPolicies(page, 100);
      const rows = await tableRows(page, "Results by policy");
      assert.equal(rows.length, none.policies.length);
      assert.ok(rows.every((r) => r.slice(3, 7).every((v) => v === "—")), `a policy with no known count shows —, never 0: ${JSON.stringify(rows[0])}`);
      assert.equal(await panel(page).getByText(/results on namespaces that cmapi does not manage/).count(), 0, "no hidden counts are known");
      assert.deepEqual(errors, []);
      await context.close();
    }
    // CRC since 2026-11-17: Kyverno installed, the 31 policies of dev not delivered. The API names 20 of the missing and counts 31.
    const crc = policyFleet([]);
    const base = crc.clusters[0], names = crc.policies.map((p) => p.name);
    crc.clusters = [{ ...base, state: "drift", stateDetail: `${names.length} missing, 0 differ from the render, 0 without the actions Audit, Warn of mode audit`,
      liveActions: [], counts: { pass: 0, fail: 0, warn: 0, error: 0, skip: 0 }, hidden: { unmanaged: 0, otherPolicies: 0, stale: 0 },
      bundle: { ...base.bundle, expected: names.length, live: 0, current: 0, ready: 0, missing: names.slice(0, 20), differing: [], actionsDiffer: [], actionsDifferTotal: 0 } }];
    crc.perCluster = {};
    {
      const { context, page, errors } = await fresh({ policies: crc });
      await openPol(page);
      const [row] = await tableRows(page, "Clusters");
      assert.deepEqual(row, ["CRC", "dev", "audit", `${names.length} missing`, `0 / ${names.length}`, "0", "0", "0", "0", "off the bundle"]);
      await panel(page).getByText("0 failing · 1 cluster off the bundle").waitFor();
      await openPolicies(page, 100);
      assert.ok((await tableRows(page, "Results by policy")).every((r) => r.slice(3, 7).every((v) => v === "—")), "a policy not on the cluster has no count");
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("6 the Policies tab says what the mockup says, and adds only what is listed", async () => {
    const fleet = policyFleet();
    const { context, page, errors } = await fresh({ policies: fleet });
    const shown = [];
    await openPol(page);
    await page.locator("table[aria-label='Refused by cmapi'] tbody tr").first().waitFor();
    assert.deepEqual(await panel(page).getByRole("heading", { level: 1 }).allInnerTexts(), ["Policies"], "the mockup's heading");
    shown.push(...await shownText(page));
    await openPolicies(page);
    await polCard(page, "Results by policy").locator("tbody tr").first().getByRole("button", { name: "Show failures" }).click();
    await polCard(page, "Results by policy").getByRole("button", { name: "Showing" }).waitFor();
    shown.push(...await shownText(page));
    api.state.mode = "empty";
    await panel(page).getByRole("group", { name: "Cluster" }).getByRole("button", { name: "CRC", exact: true }).click();
    await panel(page).getByText("Nothing failing for this selection.").waitFor();
    shown.push(...await shownText(page));
    await context.close();
    // The mockup's clusters footnote names a bundle tag and an alert that cmapi has not: the page says what it reads (MOCKUP-CONTRACT.md).
    const MOCKUP_ONLY = ["Kyverno not installed, an unreachable cluster, and results dropped by the report size breaker show as states, never as zero. A cluster on another bundle tag than the pinned one raises CmapiPolicyBundleDrift after 30 minutes."];
    const fromMockup = mockupBlock("isPolicies", "isCapacity").filter((t) => !MOCKUP_ONLY.includes(t));
    const data = [...fleet.clusters.flatMap((c) => [c.clusterId, c.env, c.mode, c.stateDetail && `${c.clusterId}: ${c.stateDetail}.`]), ...fleet.policies.flatMap((p) => [p.name, p.kind]),
      ...fleet.items.flatMap((r) => [r.namespace, r.policy, r.message, r.result, `${r.resource.kind}/${r.resource.name}`]),
      ...api.state.rejections.flatMap((r) => [r.username, `${r.clusterId} · ${r.namespace}`, ...r.findings.flatMap((f) => [f.policy, f.message]),
        r.count > 1 && `${r.findings[0].message} (${r.count} times that day)`])].filter(Boolean);
    // The mockup's logic builds these (policiesView()).
    const FROM_LOGIC = [/^\d+$/, /^—$/, /^\d+ \/ \d+$/, /^\d+ failing · \d+ clusters? off the bundle$/, /^Failing, warning and erroring resources( · [\w-]+)?( · [A-Z0-9_]+)?$/, /^(plan \(422\)|plan, warned|CI)$/,
      /^([A-Z][a-z]{2} \d{1,2} )?\d{2}:\d{2}$/, "All clusters", "Show failures", "Showing", "ok", "Kyverno not installed", /^unreachable since \d{2}:\d{2}$/,
      /^\d+–\d+ of \d+$/, /^Page \d+$/];
    // The portal's own words, each in MOCKUP-CONTRACT.md.
    const ADDED = ["Mode", "By", "current", "off the bundle", "no access to the reports", "not imported", /^\d+ rows not listed$/, /^stale since \d{2}:\d{2}$/, /^\d+ missing(, \d+ differ)?$/, /^rule [\w-]+$/,
      /^(label|annotation|quota|limit) [\w./-]+: [\w-]+$/, /^(label|annotation) keys that no stanza declares: [\w-]+$/, /^\d+–\d+ of \d+ · (by namespace|newest first)$/, "0 results",
      /^What the Kyverno bundle decided on each cluster of the nonprod instance, read from the policy reports, beside cmapi's own refusals at plan time and in CI\. The same bundle runs in all three places\. Pinned for this instance: (Kyverno v[\d.]+|no Kyverno CLI pinned \(outside the image\)); audit in dev, rnd\.$/,
      "Kyverno not installed, an unreachable cluster, reports that cmapi-reader may not read, and rows past the cap show as states, never as zero. A cluster whose policies differ from what cmapi renders, by digest or by their actions, is off the bundle.",
      /^\d+ results on namespaces that cmapi does not manage, \d+ of other policies and \d+ of policies no longer on the cluster are counted and not shown\.$/,
      /^GET \/api\/v1\/policies\/results\?result=fail,warn,error(&clusterId=[A-Z0-9_]+)?(&policy=[\w-]+)? · filtered to the environments your roles cover · paged like every list\.$/,
      /^\(\d+ times that day\)$/, /^(warning|error): [\w-]+( [\w-]+)?: /, "Nothing refused in the last 7 days.", "Cluster", "Failing resources", "Refused by cmapi", "Results by policy", "Clusters",
      "nonprod", "dev", "rnd", "Action", "‹ Previous", "Next ›"];
    const strings = [...data, ...FROM_LOGIC, ...ADDED].filter((k) => typeof k === "string");
    const patterns = [...FROM_LOGIC, ...ADDED].filter((k) => k instanceof RegExp);
    const counted = compare("Policies", fromMockup, shown, [...strings, ...LIBRARY], patterns);
    console.log(`  strings of the mockup compared on the Policies tab: ${counted}`);
    assert.deepEqual(errors, []);
  });

  // Each view is its own check, with the same lines, so neither nears the 90 s limit (the precedent of #508 and #521; #537 measured
  // the one check at 47.1 s in npm test).
  {
    const VIEWS = [
      ["policies", async (page) => { await openPol(page); await page.locator("table[aria-label='Refused by cmapi'] tbody tr").first().waitFor(); }],
      ["policies-policy", async (page) => {
        await openPol(page, `#policies?cluster=CRC&policy=${policyFleet().items[0].policy}`);
        await openPolicies(page);
        await polCard(page, "Results by policy").getByRole("button", { name: "Showing" }).waitFor();
      }]
    ];
    for (const [view, reach] of VIEWS) {
      await check(`7 the Policies tab at 390, 820 and 1440 px in each theme, and axe at phone and desktop width: ${view}`, async () => {
        let scans = 0;
        for (const width of [390, 820, 1440]) {
          const { context, page, errors } = await fresh({ width });
          await reach(page);
          for (const theme of ["light", "dark"]) {
            await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
            await settle(page);
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
        console.log(`  ${view}: 3 widths, 2 themes, ${scans} axe scans`);
      });
    }
  }

  // #537, the owner's layout: the header pill, then Clusters, the failing resources and the refusals, each open, and Results by
  // policy last and closed. Each section shows its count; Results by policy shows 25 rows a page with numbered pages, and 25, 50
  // or 100 a page. The fleet has 80 policies, as CRC had on 2026-11-21 (ob1-run31, l5a-policies-1440-light-chrome.png).
  const EIGHTY = () => policyFleetWith(80);
  const SECTIONS = ["Clusters", "Failing, warning and erroring resources", "Refused by cmapi before Git · last 7 days", "Results by policy"];
  const sectionsOf = (page) => panel(page).locator(".pf-v6-c-card").evaluateAll((cards) => cards.map((card) => ({
    title: card.querySelector("h2")?.innerText, count: card.querySelector(".pf-v6-c-card__header .pf-v6-c-badge")?.innerText,
    expanded: card.querySelector(".pf-v6-c-card__header-toggle button")?.getAttribute("aria-expanded") })));
  const policyNames = (page) => page.locator("table[aria-label='Results by policy'] tbody tr td:first-child").allInnerTexts();
  const policyPager = (page) => panel(page).getByRole("navigation", { name: "Results by policy pages" });
  /** The page buttons as they read: "‹", each page ("…" for a gap), "›"; the current page in brackets. */
  const pagesOf = (page) => policyPager(page).evaluate((nav) => [...nav.querySelectorAll("button, span[aria-hidden=true]")].map((el) => {
    const text = el.innerText.trim();
    return el.getAttribute("aria-current") === "page" ? `[${text}]` : text;
  }));
  const policyRange = (page) => polCard(page, "Results by policy").getByText(/^\d+–\d+ of \d+$/).innerText();
  const themes = async (page, each) => {
    for (const theme of ["light", "dark"]) {
      await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
      await each(theme);
    }
  };

  await check("537-O the Policies sections in the owner's order, each with its count, and Results by policy closed until opened, at 390, 820 and 1440 px in each theme", async () => {
    const fleet = EIGHTY();
    for (const width of [390, 820, 1440]) {
      const { context, page, errors } = await fresh({ width, policies: fleet });
      await openPol(page);
      await page.locator("table[aria-label='Refused by cmapi'] tbody tr").first().waitFor();
      await themes(page, async (theme) => {
        const where = `${width} ${theme}`;
        assert.deepEqual(await sectionsOf(page), [
          { title: "Clusters", count: String(fleet.clusters.length), expanded: "true" },
          { title: SECTIONS[1], count: String(fleet.items.length), expanded: "true" },
          { title: SECTIONS[2], count: String(api.state.rejections.length), expanded: "true" },
          { title: SECTIONS[3], count: String(fleet.policies.length), expanded: "false" }], `${where}: the order, the counts and what is open`);
        // The header pill stays above the sections.
        const [pill, first] = await Promise.all([panel(page).getByText(/ failing · \d+ clusters? off the bundle$/).boundingBox(), polCard(page, "Clusters").boundingBox()]);
        assert.ok(pill.y < first.y, `${where}: the pill is above Clusters`);
        assert.equal(await page.locator("table[aria-label='Results by policy']").count(), 0, `${where}: Results by policy is closed`);
        assert.equal(await panel(page).getByRole("group", { name: "Cluster" }).count(), 0, `${where}: the cluster filter is with Results by policy`);
      });
      await openPolicies(page);
      assert.equal((await sectionsOf(page))[3].expanded, "true");
      assert.equal((await policyNames(page)).length, 25, `${width}: page 1 has 25 rows`);
      assert.equal(await panel(page).getByRole("group", { name: "Cluster" }).count(), 1, `${width}: the cluster filter shows with the list`);
      // Closing a section keeps its count in the header.
      await polToggle(page, "Clusters").click();
      await page.locator("table[aria-label=Clusters]").waitFor({ state: "detached" });
      assert.deepEqual((await sectionsOf(page))[0], { title: "Clusters", count: String(fleet.clusters.length), expanded: "false" });
      assert.equal(await page.locator("table[aria-label=Clusters]").count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("537-P Results by policy pages: 25 rows, page 2 is rows 26–50, 50 and 100 a page, page 1 again after a new cluster or page size, and a gap past seven pages", async () => {
    const fleet = EIGHTY(), names = fleet.policies.map((p) => p.name);
    for (const width of [390, 820, 1440]) {
      const { context, page, errors } = await fresh({ width, policies: fleet });
      await openPol(page);
      await openPolicies(page);
      await themes(page, async (theme) => {
        const where = `${width} ${theme}`;
        await policyPager(page).getByRole("button", { name: "Page 1", exact: true }).click();
        await polCard(page, "Results by policy").getByText("1–25 of 80", { exact: true }).waitFor();
        assert.deepEqual(await policyNames(page), names.slice(0, 25), `${where}: page 1`);
        assert.equal(await policyRange(page), "1–25 of 80");
        assert.deepEqual(await pagesOf(page), ["‹", "[1]", "2", "3", "4", "›"]);
        assert.equal(await policyPager(page).getByRole("button", { name: "Previous page" }).getAttribute("aria-disabled"), "true", `${where}: no page before 1`);
        await policyPager(page).getByRole("button", { name: "Page 2", exact: true }).click();
        await polCard(page, "Results by policy").getByText("26–50 of 80", { exact: true }).waitFor();
        assert.deepEqual(await policyNames(page), names.slice(25, 50), `${where}: page 2 is rows 26–50`);
        assert.equal(await policyRange(page), "26–50 of 80");
        assert.deepEqual(await pagesOf(page), ["‹", "1", "[2]", "3", "4", "›"]);
        await policyPager(page).getByRole("button", { name: "Next page" }).click();
        assert.deepEqual(await policyNames(page), names.slice(50, 75), `${where}: Next is page 3`);
        await policyPager(page).getByRole("button", { name: "Page 4", exact: true }).click();
        await polCard(page, "Results by policy").getByText("76–80 of 80", { exact: true }).waitFor();
        assert.deepEqual(await policyNames(page), names.slice(75), `${where}: the last page`);
        assert.equal(await policyRange(page), "76–80 of 80");
        assert.equal(await policyPager(page).getByRole("button", { name: "Next page" }).getAttribute("aria-disabled"), "true", `${where}: no page after the last`);
      });
      // 50 a page starts at page 1, then 100 a page shows all 80 on one page.
      await panel(page).getByRole("group", { name: "Per page" }).getByRole("button", { name: "50", exact: true }).click();
      await polCard(page, "Results by policy").getByText("1–50 of 80", { exact: true }).waitFor();
      assert.equal(await policyRange(page), "1–50 of 80", `${width}: a new page size starts at page 1`);
      assert.deepEqual(await policyNames(page), names.slice(0, 50));
      assert.deepEqual(await pagesOf(page), ["‹", "[1]", "2", "›"]);
      await policyPager(page).getByRole("button", { name: "Page 2", exact: true }).click();
      assert.deepEqual(await policyNames(page), names.slice(50));
      await panel(page).getByRole("group", { name: "Per page" }).getByRole("button", { name: "100", exact: true }).click();
      await polCard(page, "Results by policy").getByText("1–80 of 80", { exact: true }).waitFor();
      assert.deepEqual(await policyNames(page), names, `${width}: 100 a page`);
      assert.deepEqual(await pagesOf(page), ["‹", "[1]", "›"]);
      // A new cluster, from its chip or from the address, starts at page 1.
      await panel(page).getByRole("group", { name: "Per page" }).getByRole("button", { name: "25", exact: true }).click();
      await policyPager(page).getByRole("button", { name: "Page 3", exact: true }).click();
      await panel(page).getByRole("group", { name: "Cluster" }).getByRole("button", { name: "CRC", exact: true }).click();
      await page.waitForFunction(() => location.hash === "#policies?cluster=CRC");
      assert.equal(await policyRange(page), "1–25 of 80", `${width}: a new cluster starts at page 1`);
      assert.deepEqual(await policyNames(page), names.slice(0, 25));
      await policyPager(page).getByRole("button", { name: "Page 2", exact: true }).click();
      await page.evaluate(() => { location.hash = "#policies"; });
      await panel(page).getByRole("group", { name: "Cluster" }).getByRole("button", { name: "All clusters", pressed: true }).waitFor();
      assert.equal(await policyRange(page), "1–25 of 80", `${width}: a cluster changed in the address starts at page 1`);
      assert.deepEqual(errors, []);
      await context.close();
    }
    // Past seven pages, the first and the last page stay, with the current page's neighbours and a gap.
    const { context, page, errors } = await fresh({ policies: policyFleetWith(250) });
    await openPol(page);
    await openPolicies(page);
    assert.deepEqual(await pagesOf(page), ["‹", "[1]", "2", "3", "4", "5", "…", "10", "›"]);
    await policyPager(page).getByRole("button", { name: "Page 5", exact: true }).click();
    await polCard(page, "Results by policy").getByText("101–125 of 250", { exact: true }).waitFor();
    assert.deepEqual(await pagesOf(page), ["‹", "1", "…", "4", "[5]", "6", "…", "10", "›"]);
    await policyPager(page).getByRole("button", { name: "Page 10", exact: true }).click();
    await polCard(page, "Results by policy").getByText("226–250 of 250", { exact: true }).waitFor();
    assert.deepEqual(await pagesOf(page), ["‹", "1", "…", "6", "7", "8", "9", "[10]", "›"]);
    assert.equal(await policyRange(page), "226–250 of 250");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("540-R switching clusters twice resets every time, including a smaller or empty policy list", async () => {
    const { context, page, errors } = await fresh({ policies: EIGHTY() });
    await openPol(page);
    await openPolicies(page);
    for (const via of ["chip", "address"]) {
      const clusterId = via === "chip" ? "CRC" : "OCP_GF6";
      await policyPager(page).getByRole("button", { name: "Page 4", exact: true }).click();
      api.state.policies = policyFleetWith(10);
      if (via === "chip") await panel(page).getByRole("group", { name: "Cluster" }).getByRole("button", { name: clusterId, exact: true }).click();
      else await page.evaluate((id) => { location.hash = `#policies?cluster=${id}`; }, clusterId);
      await polCard(page, "Results by policy").getByText("1–10 of 10", { exact: true }).waitFor();
      assert.equal((await policyNames(page)).length, 10, `${via}: fewer pages than page 4`);
      api.state.policies = EIGHTY();
      // Do not page in CRC: that would overwrite the old cluster and mask the regression.
      if (via === "chip") await panel(page).getByRole("group", { name: "Cluster" }).getByRole("button", { name: "All clusters", exact: true }).click();
      else await page.evaluate(() => { location.hash = "#policies"; });
      await polCard(page, "Results by policy").getByText("1–25 of 80", { exact: true }).waitFor();
      assert.equal(await policyRange(page), "1–25 of 80", `${via}: returning to All clusters also resets`);
    }
    api.state.policies = policyFleetWith(0);
    await page.evaluate(() => { location.hash = "#policies?cluster=OCP_GF10"; });
    await panel(page).getByText("No policy runs in the environments of these clusters.", { exact: true }).waitFor();
    assert.deepEqual(await policyNames(page), []);
    assert.equal(await policyPager(page).count(), 0, "zero policies has an empty state, no phantom page");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("540-S chip wrapping stays scoped to chip strips in Policies and other cards", async () => {
    const { context, page, errors } = await fresh({ policies: EIGHTY() });
    for (const hash of ["#policies", "#quotas"]) {
      await open(page, hash);
      if (hash === "#policies") {
        await page.locator("table[aria-label=Clusters]").waitFor();
        await openPolicies(page);
      }
      await panel(page).locator(".cp-wrap").first().waitFor();
      const wraps = await panel(page).locator(".cp-wrap, .cp-wrap .cp-scroll").evaluateAll((els) => els.map((el) => ({
        chips: el.classList.contains("cp-scroll"), wrap: getComputedStyle(el).overflowWrap
      })));
      assert.ok(wraps.some((w) => w.chips), `${hash}: exercise the shared Choices component`);
      for (const w of wraps) assert.equal(w.wrap, w.chips ? "normal" : "anywhere", `${hash}: text outside chip strips keeps its wrapping`);
    }
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("540-A every disclosure controls a persistent uniquely named region", async () => {
    const { context, page, errors } = await fresh({ policies: EIGHTY() });
    await openPol(page);
    for (const title of SECTIONS) {
      const toggle = polToggle(page, title);
      const targetId = await toggle.getAttribute("aria-controls");
      assert.ok(targetId, `${title}: aria-controls`);
      const target = page.locator(`[id=${JSON.stringify(targetId)}]`);
      assert.equal(await target.count(), 1, `${title}: one persistent target`);
      assert.equal(await target.getAttribute("aria-labelledby"), await toggle.getAttribute("id"));
      for (const key of ["Enter", "Space"]) {
        const wasExpanded = await toggle.getAttribute("aria-expanded") === "true";
        await toggle.focus();
        await page.keyboard.press(key);
        await toggle.and(page.locator(wasExpanded ? "[aria-expanded=false]" : "[aria-expanded=true]")).waitFor();
        const expanded = await toggle.getAttribute("aria-expanded") === "true";
        assert.equal(await target.isVisible(), expanded, `${title}: ${key} synchronizes visibility`);
        assert.equal(await target.count(), 1, `${title}: closing keeps the target`);
      }
    }
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("537-K the section toggles, the page buttons and the page sizes work from the keyboard, and focus stays on the button pressed, at 390, 820 and 1440 px in each theme", async () => {
    const fleet = EIGHTY(), names = fleet.policies.map((p) => p.name);
    for (const width of [390, 820, 1440]) {
      const { context, page, errors } = await fresh({ width, policies: fleet });
      await openPol(page);
      await themes(page, async (theme) => {
        const where = `${width} ${theme}`;
        const toggle = polToggle(page, "Results by policy");
        await toggle.focus();
        await page.keyboard.press("Enter");
        await page.locator("table[aria-label='Results by policy']").waitFor();
        assert.equal(await toggle.getAttribute("aria-expanded"), "true", `${where}: Enter opens`);
        await page.keyboard.press("Space");
        await page.locator("table[aria-label='Results by policy']").waitFor({ state: "detached" });
        assert.equal(await toggle.getAttribute("aria-expanded"), "false", `${where}: Space closes`);
        await page.keyboard.press("Space");
        await page.locator("table[aria-label='Results by policy']").waitFor();
        // Tab moves from the toggle into the list, to its first chip.
        await page.keyboard.press("Tab");
        assert.equal(await page.evaluate(() => document.activeElement?.innerText), "All clusters", `${where}: Tab reaches the cluster filter`);
        const two = policyPager(page).getByRole("button", { name: "Page 2", exact: true });
        await two.focus();
        await page.keyboard.press("Enter");
        await page.waitForFunction(() => document.querySelector("nav[aria-label='Results by policy pages'] [aria-current=page]")?.innerText === "2");
        assert.deepEqual(await policyNames(page), names.slice(25, 50), `${where}: Enter on page 2`);
        assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("aria-label")), "Page 2", `${where}: focus stays on page 2`);
        await page.keyboard.press("Tab");
        await page.keyboard.press("Space");
        assert.deepEqual(await policyNames(page), names.slice(50, 75), `${where}: Tab, then Space on page 3`);
        assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("aria-label")), "Page 3", `${where}: focus stays on page 3`);
        await policyPager(page).getByRole("button", { name: "Previous page" }).focus();
        await page.keyboard.press("Enter");
        await polCard(page, "Results by policy").getByText("26–50 of 80", { exact: true }).waitFor();
        assert.equal(await policyRange(page), "26–50 of 80", `${where}: Enter on Previous`);
        await panel(page).getByRole("group", { name: "Per page" }).getByRole("button", { name: "50", exact: true }).focus();
        await page.keyboard.press("Space");
        await polCard(page, "Results by policy").getByText("1–50 of 80", { exact: true }).waitFor();
        assert.equal(await policyRange(page), "1–50 of 80", `${where}: Space on 50`);
        await panel(page).getByRole("group", { name: "Per page" }).getByRole("button", { name: "25", exact: true }).focus();
        await page.keyboard.press("Enter");
        await polCard(page, "Results by policy").getByText("1–25 of 80", { exact: true }).waitFor();
        assert.equal(await policyRange(page), "1–25 of 80", `${where}: Enter on 25`);
        await toggle.focus();
        await page.keyboard.press("Enter");
        await page.locator("table[aria-label='Results by policy']").waitFor({ state: "detached" });
      });
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  // The committed screenshots are the pull request's evidence, captured once: a run writes them only when asked to (#530).
  const shots537 = process.env.UPDATE_COMMITTED_SCREENSHOTS === "1" ? join(app, "screenshots", "537-policies-paged", "after") : join(out, "537-policies-paged");
  mkdirSync(shots537, { recursive: true });
  // [state, how to reach it, the fleet's policies]: 250 policies are 10 pages; the last has the widest row of page buttons (‹ 1 … 6 7 8 9 10 ›).
  const LAYOUT_537 = [
    ["closed", async () => {}, 80],
    ["open-page-2", async (page) => { await openPolicies(page); await policyPager(page).getByRole("button", { name: "Page 2", exact: true }).click(); }, 80],
    ["open-100", async (page) => { await openPolicies(page, 100); }, 80],
    ["open-page-10-of-10", async (page) => { await openPolicies(page); await policyPager(page).getByRole("button", { name: "Page 10", exact: true }).click(); }, 250]
  ];
  /** The words of the chip labels that break over two lines (#538): each word's range has one line box. A chip may wrap between words. */
  const brokenChips = (page) => panel(page).locator(".pf-v6-c-toggle-group__text").evaluateAll((spans) => spans.flatMap((span) => {
    const walker = document.createTreeWalker(span, NodeFilter.SHOW_TEXT), broken = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      for (const word of node.nodeValue.matchAll(/\S+/g)) {
        const range = document.createRange();
        range.setStart(node, word.index);
        range.setEnd(node, word.index + word[0].length);
        if (new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top))).size > 1) broken.push(word[0]);
      }
    }
    return broken;
  }));
  const outsideCards = (page) => panel(page).locator(".pf-v6-c-card").evaluateAll((cards) => cards.flatMap((card) => {
    const box = card.getBoundingClientRect();
    return [...card.querySelectorAll("*")].filter((el) => !el.closest(".pf-v6-c-scroll-inner-wrapper, .cp-scroll") || el.matches(".pf-v6-c-scroll-inner-wrapper, .cp-scroll"))
      .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && (r.left < box.left - 1 || r.right > box.right + 1); })
      .map((el) => `${card.querySelector("h2")?.innerText}: ${el.localName}.${[...el.classList].join(".")} ${el.getAttribute("aria-label") ?? el.innerText?.slice(0, 20)}`);
  }));
  for (const [state, reach, count] of LAYOUT_537) {
    await check(`537-L the Policies tab at 390, 820 and 1440 px in each theme, and axe at phone and desktop width: ${state}`, async () => {
      let scans = 0;
      const heights = {};
      for (const width of [390, 820, 1440]) {
        const { context, page, errors } = await fresh({ width, policies: policyFleetWith(count) });
        await openPol(page);
        await page.locator("table[aria-label='Refused by cmapi'] tbody tr").first().waitFor();
        await reach(page);
        assert.deepEqual(await brokenChips(page), [], `${state} ${width}: no chip's label breaks inside a word`);
        // The page's main container scrolls, not the document: the window grows to the tallest element, as in 484-L.
        const height = await page.evaluate(() => Math.max(...[...document.querySelectorAll("*")].map((el) => el.scrollHeight)));
        heights[width] = height;
        await page.setViewportSize({ width, height: height + 200 });
        await themes(page, async (theme) => {
          await settle(page);
          assert.equal(await running(page), 0, `${state} ${width} ${theme}: no colour transition still runs when the page is read`);
          const layout = await page.evaluate(() => {
            const main = document.querySelector(".pf-v6-c-page__main-container") ?? document.documentElement;
            return { doc: document.documentElement.scrollWidth - document.documentElement.clientWidth, main: main.scrollWidth - main.clientWidth, text: document.body.innerText };
          });
          assert.ok(layout.doc <= 0 && layout.main <= 0, `${state} ${width} ${theme}: no sideways scroll (${layout.doc}, ${layout.main})`);
          assert.doesNotMatch(layout.text, /\{\{|undefined|NaN|\[object|null/, `${state} ${width} ${theme}: no leftover placeholder`);
          // A card can hide what sticks out of it, which the page's scroll width does not see: nothing in a section reaches past its
          // card, but in a table's or a chip strip's own scroll area.
          assert.deepEqual(await outsideCards(page), [], `${state} ${width} ${theme}: everything stays inside its card`);
          // As 484-L: 1440 and 390 are the evidence, 820 goes to test-output.
          await page.screenshot({ path: join(width === 820 ? out : shots537, width === 820 ? `537-${state}-${width}-${theme}.png` : `${state}-${width}-${theme}.png`), fullPage: true });
          if (width !== 820) {
            const scan = await new AxeBuilder({ page }).analyze();
            scans++;
            assert.deepEqual(scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.html}`), [], `axe on ${state} at ${width} ${theme}`);
          }
        });
        assert.deepEqual(errors, []);
        await context.close();
      }
      console.log(`  ${state}: 3 widths, 2 themes, ${scans} axe scans; the tab's height ${JSON.stringify(heights)} px`);
    });
  }

  // Portal slice 4, the Capacity part (#302). The fleet is CRC as the arbitration says it must show, a second dev cluster, and a
  // cluster in each other state of the API. Each expectation is written from the mockup's forms (CAPACITY, the capacity view of
  // renderVals) and the API's contract, not from the page's code.
  const GIB = 2 ** 30;
  const tenth = (x) => String(Math.round(x * 10) / 10);
  const coresOf = (m) => `${tenth(m / 1000)} ${tenth(m / 1000) === "1" ? "core" : "cores"}`;
  const giOf = (b) => `${tenth(b / GIB)} Gi`;
  const amountOf = (r, v) => (r === "cpu" ? coresOf(v) : giOf(v));
  const roomOf = (r, v) => (v === null ? "—" : v < 0 ? `over by ${amountOf(r, -v)}` : amountOf(r, v));
  const pctOf = (x) => `${Math.round(x * 100)}%`;
  const hhmm = (iso) => iso.slice(11, 16);
  const boundOf = (b) => (b === null ? "—" : b === "both" ? "cpu and memory" : b);
  const CAP_WORD = { ok: (c) => (c.status === "ok" ? "ok" : `${c.status} · ${c.boundBy}`), loading: () => "loading", "not-imported": () => "not imported", unreachable: (c) => `unreachable since ${hhmm(c.asOf)}`,
    forbidden: () => "no access to the quotas", "no-size": () => "no size", stale: (c) => `stale since ${hhmm(c.asOf)}` };
  const CAP_TONE = { ok: "success", warn: "warning", critical: "danger", over: "danger" };
  const sizeOf = (r, f, basis) => {
    const simulated = f.simulated === null ? null : `simulated ${amountOf(r, f.simulated)}`, nodes = f.allocatable === null ? null : `nodes ${amountOf(r, f.allocatable)}`;
    return (basis === "allocatable" ? [nodes, simulated] : [simulated, nodes]).filter(Boolean).join(" · ");
  };
  const meterOf = (r, f, basis) => [f.commitment === null ? "—" : pctOf(f.commitment), sizeOf(r, f, basis)].filter(Boolean).join(" ");
  const expectedCap = (c) => [c.clusterId, c.env, c.zones?.length ? c.zones.join(" · ") : "—", meterOf("cpu", c.cpu, c.basis), meterOf("memory", c.memory, c.basis),
    c.cpu.headroom === null && c.memory.headroom === null ? "—" : `${roomOf("cpu", c.cpu.headroom)} · ${roomOf("memory", c.memory.headroom)}`,
    boundOf(c.boundBy), c.asOf ? hhmm(c.asOf) : "—", CAP_WORD[c.state](c)];
  const LEFT_OUT = { stale: (e) => `stale since ${hhmm(e.asOf)}`, forbidden: () => "no access to the quotas", "no-size": () => "no size", "not-imported": () => "not imported" };
  const expectedGroup = (g) => {
    const coverage = Number.isInteger(g.coverage * 10) ? g.coverage.toFixed(1) : g.coverage.toFixed(2);
    const left = g.excluded.map((e) => (e.reason === "not-writable" ? `${e.clusterId} placement off` : `${e.clusterId} left out: ${(LEFT_OUT[e.reason] ?? (() => e.reason))(e)}`));
    const status = g.status === null ? "—" : g.status === "ok" ? "ok" : `${g.status} · ${g.statusCounts[g.status]} of ${g.included}`;
    const stat = (r) => (g[r] ? [pctOf(g[r].commitment), `quota headroom ${amountOf(r, g[r].headroom)}`] : ["—", "quota headroom —"]);
    const largest = g.cpu ? [`${coresOf(g.cpu.largestPlacement.value)} · ${giOf(g.memory.largestPlacement.value)}`, g.cpu.largestPlacement.clusterId === g.memory.largestPlacement.clusterId
      ? `on ${g.cpu.largestPlacement.clusterId}` : `cpu on ${g.cpu.largestPlacement.clusterId} · memory on ${g.memory.largestPlacement.clusterId}`] : ["—", ""];
    const why = g.cpu ? (g.boundBy === "memory" ? `memory ${pctOf(g.memory.commitment)} vs cpu ${pctOf(g.cpu.commitment)} committed` : `cpu ${pctOf(g.cpu.commitment)} vs memory ${pctOf(g.memory.commitment)} committed`) : "";
    return { name: g.name, status, meta: [`${g.included} of ${g.matching} cluster${g.matching === 1 ? "" : "s"}`, `coverage ${coverage}`, ...left].join(" · "),
      stats: [["CPU commitment", ...stat("cpu")], ["Memory commitment", ...stat("memory")], ["Largest placement", ...largest], ["Bound by", boundOf(g.boundBy), why]] };
  };
  const capCalls = () => calls("/api/v1/capacity");
  const openCap = async (page, hash = "#capacity") => {
    await open(page, hash);
    await page.locator("table[aria-label=Clusters] tbody tr").first().waitFor();
  };
  const capCard = (page, title) => panel(page).locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
  /** Each group card as the page shows it: its name, the pill, the meta line and the four stats, each [term, value, note]. */
  const groupCards = (page) => panel(page).locator(".pf-v6-l-gallery > .pf-v6-c-card").evaluateAll((cards) => cards.map((card) => {
    const text = (el) => (el?.innerText ?? "").replace(/\s+/g, " ").trim();
    return { name: text(card.querySelector(".pf-v6-c-card__title")), status: text(card.querySelector(".pf-v6-c-label")),
      meta: text(card.querySelector(".pf-v6-c-card__body small")),
      stats: [...card.querySelectorAll(".pf-v6-c-description-list__group")].map((g) => [text(g.querySelector("dt")), text(g.querySelector("dd b")), text(g.querySelector("dd small"))]) };
  }));
  /** Each cluster's two meters: null when it draws none, else what a screen reader gets and the bar's tone. */
  const meters = (page) => page.locator("table[aria-label=Clusters] tbody tr").evaluateAll((trs) => trs.map((tr) => [3, 4].map((i) => {
    const bar = tr.children[i].querySelector("[role=progressbar]");
    if (!bar) return null;
    return { now: bar.getAttribute("aria-valuenow"), text: bar.getAttribute("aria-valuetext"), tone: bar.closest(".pf-v6-c-progress").className.match(/pf-m-(danger|warning)/)?.[1] ?? "" };
  })));
  const expectedMeters = (c) => ["cpu", "memory"].map((r) => (c[r].commitment === null ? null
    : { now: String(Math.min(100, Math.round(c[r].commitment * 100))), text: pctOf(c[r].commitment), tone: { ok: "", warn: "warning", critical: "danger", over: "danger" }[c[r].status] }));
  const capFoot = (page) => `${page.targets.map((t) => `${t.env}: overcommit cpu ${t.overcommit.cpu.toFixed(2).replace(/0$/, "")}, memory ${t.overcommit.memory.toFixed(2).replace(/0$/, "")}${t.overcommitDefault ? " (not in capacity.yaml)" : ""}; commitment warns at ${Math.round(t.commitment.warn * 100)}%, critical at ${Math.round(t.commitment.critical * 100)}%`).join(" · ")}. Each resource is judged on its own; a cluster takes the worse status. Memory cannot be throttled, so its overcommit stays tighter.`;

  await check("23 Capacity: the group cards and the Clusters table of GET /api/v1/capacity cell by cell; unknown is —, never 0 or a bar; over 100 % fills the bar and says its figure; the footnote from the API's targets", async () => {
    const fleet = capacityFleet();
    const { context, page, errors } = await fresh({ capacity: fleet });
    await openCap(page);
    assert.deepEqual(await tableRows(page, "Clusters"), fleet.clusters.map(expectedCap));
    assert.deepEqual(await meters(page), fleet.clusters.map(expectedMeters), "a null draws no meter (no aria-valuenow); over 100 % is a full danger bar with its own figure");
    const tones = await page.locator("table[aria-label=Clusters] tbody tr").evaluateAll((trs) => trs.map((tr) => tr.lastElementChild.querySelector(".pf-v6-c-label").className.match(/pf-m-(success|warning|danger|info)/)?.[1] ?? "grey"));
    assert.deepEqual(tones, fleet.clusters.map((c) => (c.state === "ok" ? CAP_TONE[c.status] : { loading: "info", "no-size": "info", "not-imported": "info", stale: "danger", unreachable: "danger", forbidden: "danger" }[c.state])));
    // CRC as the arbitration says: 56 % of 128 cores and 45 % of 320 Gi against its simulated size, the nodes' 7.8 cores and 19.1 Gi beside them.
    assert.deepEqual((await tableRows(page, "Clusters"))[0].slice(2, 6), ["—", "56% simulated 64 cores · nodes 7.8 cores", "45% simulated 256 Gi · nodes 19.1 Gi", "56 cores · 176 Gi"]);
    assert.deepEqual(await groupCards(page), fleet.groups.map(expectedGroup));
    const dev = fleet.groups.find((g) => g.name === "us-central · dev");
    assert.deepEqual(expectedGroup(dev).stats[2], ["Largest placement", "56 cores · 380 Gi", "cpu on CRC · memory on OCP_GF15"], "each resource's own cluster");
    await panel(page).getByText(capFoot(fleet), { exact: true }).waitFor();
    assert.match(capFoot(fleet), /^dev: overcommit cpu 2\.0, memory 1\.25; .* · rnd: overcommit cpu 1\.5, memory 1\.1;/, "the API's targets, not the mockup's constants");
    for (const c of fleet.clusters.filter((x) => x.stateDetail)) await panel(page).getByText(`${c.clusterId}: ${c.stateDetail}.`, { exact: true }).waitFor();
    await panel(page).getByText("OCP_GF14: writes are off in clusters.yaml, so it takes no placement and is left out of its group.", { exact: true }).waitFor();
    await panel(page).getByText("2 clusters of environments where your roles do not read capacity are not shown.", { exact: true }).waitFor();
    await panel(page).getByText(`OCP_GF14 nodes: ${fleet.clusters.find((c) => c.clusterId === "OCP_GF14").nodesDetail}.`, { exact: true }).waitFor();
    // A cluster that is not connected has one detail for its quotas and its nodes (#404): said once, not twice.
    for (const id of ["OCP_GF9", "OCP_GF13"]) assert.equal(await panel(page).getByText(new RegExp(`^${id} nodes:`)).count(), 0, id);
    const text = await panel(page).innerText();
    assert.doesNotMatch(text, /\b0%|\d G\b|\bGB\b/, "no 0 % for what is not known, and memory in Gi only");
    assert.deepEqual(capCalls().map((c) => c.query), [{}], "one call, with the API's default groupBy");
    assert.deepEqual(errors, []);
    await context.close();
  });

  await check("24 Capacity states: loading, empty, a 403 with no action, a 5xx with Try again, no tab without capacity:read, and a read again on focus that the browser's cache answers with the API's 304", async () => {
    {
      const { context, page, errors } = await fresh();
      api.state.delayMs = 400;
      await page.goto(`${portal.page}#capacity`);
      await page.getByRole("status").filter({ hasText: "Loading capacity…" }).waitFor();
      await page.locator("table[aria-label=Clusters] tbody tr").first().waitFor();
      api.state.delayMs = 0;
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh({ mode: "empty" });
      await open(page, "#capacity");
      await panel(page).getByText("No cluster of your environments is known to this instance.").waitFor();
      assert.equal(await panel(page).locator(".pf-v6-l-gallery").count(), 0, "no group card with no cluster");
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh();
      expectedStatus = [403];
      api.state.answers.push({ route: "GET /api/v1/capacity", status: 403, body: { type: "https://cmapi.ephico2real.com/problems/forbidden", title: "forbidden", status: 403, code: "forbidden", detail: "Missing permission capacity:read: no role in your token grants it (roles: ['cmapi-none'])" } });
      await open(page, "#capacity");
      await panel(page).getByRole("heading", { name: "You do not have permission to see capacity." }).waitFor();
      assert.match(await panel(page).innerText(), /Missing permission capacity:read/);
      assert.equal(await panel(page).getByRole("button", { name: "Try again" }).count(), 0, "a 403 offers no action");
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      const { context, page, errors } = await fresh();
      expectedStatus = [500];
      api.state.answers.push({ route: "GET /api/v1/capacity", status: 500, body: { type: "https://cmapi.ephico2real.com/problems/internal-error", title: "internal-error", status: 500, code: "internal-error", detail: "The watch cache did not answer." } });
      await open(page, "#capacity");
      const alert = panel(page).locator(".pf-v6-c-alert").filter({ hasText: "Capacity did not load." });
      await alert.waitFor();
      assert.match(await alert.innerText(), /The watch cache did not answer\./);
      await alert.getByRole("button", { name: "Try again" }).click();
      await page.locator("table[aria-label=Clusters] tbody tr").first().waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // The approval relay holds requests:read only: no Capacity tab, and its address shows the first tab it has.
      const { context, page, errors } = await fresh({ user: "relay" });
      await open(page, "#capacity");
      assert.deepEqual(await tabNames(page), ["Workflow", "Requests"]);
      assert.equal(await page.getByRole("tab", { selected: true }).innerText(), "Workflow");
      assert.equal(capCalls().length, 0, "no call that the person may not make");
      assert.deepEqual(errors, []);
      await context.close();
    }
    {
      // Read again on focus: the browser's cache sends If-None-Match with the API's strong ETag, the API answers 304, and the page
      // keeps its figures. A change on the API is a new tag and new figures.
      const fleet = capacityFleet();
      const { context, page, errors } = await fresh({ capacity: fleet });
      await openCap(page);
      const focus = () => page.evaluate(() => { window.dispatchEvent(new Event("visibilitychange")); window.dispatchEvent(new Event("focus")); });
      await focus();
      await page.waitForFunction(() => true);
      await new Promise((resolve) => { const t = setInterval(() => { if (capCalls().length >= 2) { clearInterval(t); resolve(); } }, 50); setTimeout(() => { clearInterval(t); resolve(); }, 5000); });
      const [first, second] = capCalls();
      assert.ok(second, `a read on focus: the calls were ${JSON.stringify(capCalls())}`);
      assert.equal(first.ifNoneMatch, null);
      assert.match(second.ifNoneMatch ?? "", /^"[0-9a-f]{32}"$/, "the browser revalidates with the API's tag");
      assert.equal(api.state.notModified, 1, "the API answered 304");
      assert.deepEqual(await tableRows(page, "Clusters"), fleet.clusters.map(expectedCap), "a 304 keeps the figures");
      api.state.capacity = { ...fleet, clusters: fleet.clusters.map((c) => (c.clusterId === "CRC" ? { ...c, state: "stale", stateDetail: "the ResourceQuota watch is stale: no good read for over 1800s" } : c)) };
      await focus();
      await panel(page).getByText("stale since 09:14", { exact: true }).waitFor();
      assert.equal(api.state.notModified, 1, "a changed answer is a 200");
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  await check("6 the Capacity tab says what the mockup says, and adds only what is listed", async () => {
    const fleet = capacityFleet();
    const { context, page, errors } = await fresh({ capacity: fleet });
    await openCap(page);
    assert.deepEqual(await panel(page).getByRole("heading", { level: 1 }).allInnerTexts(), ["Capacity"], "the mockup's heading");
    const shown = await shownText(page);
    await context.close();
    // The mockup's lede and pill speak of snapshots, which are not built (#21): the page says where its figures come from.
    const MOCKUP_ONLY = ["Cluster capacity from the latest complete snapshots, grouped by clusters.yaml metadata. CPU and memory are measured, committed and checked separately; a cluster is as full as its fuller resource. Headroom never crosses cluster boundaries, so the largest single placement is shown beside the total.",
      "snapshot 17:00 · every 30 min", "Snapshot"];
    const fromMockup = mockupBlock("isCapacity", "isKpis").filter((t) => !MOCKUP_ONLY.includes(t));
    const data = fleet.clusters.flatMap((c) => [c.clusterId, c.env, ...(c.zones ?? []), c.stateDetail && `${c.clusterId}: ${c.stateDetail}.`, c.nodesDetail && `${c.clusterId} nodes: ${c.nodesDetail}.`])
      .concat(fleet.groups.map((g) => g.name)).filter(Boolean);
    // The mockup's logic builds these (the capacity view of renderVals and CAPACITY).
    const FROM_LOGIC = [/^\d+%$/, /^—$/, "ok", "cpu", "memory", "cpu and memory", /^(warn|critical) · (cpu|memory|both)$/, /^\d+(\.\d)? cores? · \d+(\.\d)? Gi$/, /^\d{2}:\d{2}$/,
      /^(ok|warn|critical|over)( · \d+ of \d+)?$/, /^quota headroom \d+(\.\d)? (cores?|Gi)$/, /^on [A-Z0-9_]+$/, /^(cpu|memory) \d+% vs (cpu|memory) \d+% committed$/,
      /^\d+ of \d+ clusters?( · .*)?$/, /^[a-z]+ overcommit: CPU [\d.]+, memory [\d.]+\.( Sized by .*)?$/, capFoot(fleet)];
    // The portal's own words, each in MOCKUP-CONTRACT.md.
    const ADDED = ["As of", "live from the watch · no snapshots yet",
      "Cluster capacity from each cluster's watch of its quotas and nodes, grouped by clusters.yaml metadata. CPU and memory are committed and checked separately; a cluster is as full as its fuller resource. Headroom never crosses cluster boundaries, so the largest single placement is shown beside the total.",
      /^(simulated|nodes) \d+(\.\d)? (cores?|Gi)( · (simulated|nodes) \d+(\.\d)? (cores?|Gi))?$/, /^over by \d+(\.\d)? (cores?|Gi) · over by \d+(\.\d)? (cores?|Gi)$/, /^(over by )?\d+(\.\d)? cores? · (over by )?\d+(\.\d)? Gi$/,
      /^over · (cpu|memory|both)$/, /^(stale|unreachable) since \d{2}:\d{2}$/, "loading", "not imported", "no access to the quotas", "no size", "quota headroom —", /^cpu on [A-Z0-9_]+ · memory on [A-Z0-9_]+$/,
      "OCP_GF14: writes are off in clusters.yaml, so it takes no placement and is left out of its group.",
      /^\d+ clusters? of environments where your roles do not read capacity (is|are) not shown\.$/,
      /^Committed is the hard requests of the ResourceQuotas that cmapi manages on the nonprod instance, per namespace its smallest unscoped one, against the size × overcommit\. Pods of other namespaces are not subtracted\. Not measured until the capacity snapshots: requested, usedAvg, usedPeak, history\.$/,
      "Clusters", "nonprod", "dev", "rnd", "us-central", "eu-west",
      // Each meter's accessible name: the demo tab's, from the mockup's column headings.
      /^[A-Z][A-Z0-9_]+ (CPU|memory) commitment$/];
    const strings = [...data, ...FROM_LOGIC, ...ADDED].filter((k) => typeof k === "string");
    const patterns = [...FROM_LOGIC, ...ADDED].filter((k) => k instanceof RegExp);
    const counted = compare("Capacity", fromMockup, shown, [...strings, ...LIBRARY], patterns);
    console.log(`  strings of the mockup compared on the Capacity tab: ${counted}`);
    assert.deepEqual(errors, []);
  });

  await check("7 the Capacity tab at 390, 820 and 1440 px in each theme, and axe at phone and desktop width", async () => {
    // The fleet of every state, and CRC alone: what the arbitration says CRC must show.
    const crcOnly = () => {
      const fleet = capacityFleet(), clusters = fleet.clusters.filter((c) => c.clusterId === "CRC");
      return { ...fleet, targets: fleet.targets.filter((t) => t.env === "dev"), clusters, groups: capacityGroups(clusters) };
    };
    const VIEWS = [["capacity", capacityFleet], ["capacity-crc", crcOnly]];
    let scans = 0;
    for (const [view, fleetOf] of VIEWS) {
      for (const width of [390, 820, 1440]) {
        const { context, page, errors } = await fresh({ width, capacity: fleetOf() });
        await openCap(page);
        for (const theme of ["light", "dark"]) {
          await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
          await settle(page);
          assert.equal(await running(page), 0, `${view} ${width} ${theme}: no colour transition still runs when the page is read`);
          const layout = await page.evaluate(() => {
            const main = document.querySelector(".pf-v6-c-page__main-container") ?? document.documentElement;
            return { doc: document.documentElement.scrollWidth - document.documentElement.clientWidth, main: main.scrollWidth - main.clientWidth, text: document.body.innerText };
          });
          assert.ok(layout.doc <= 0 && layout.main <= 0, `${view} ${width} ${theme}: no sideways scroll (${layout.doc}, ${layout.main})`);
          assert.doesNotMatch(layout.text, /\{\{|undefined|NaN|\[object/, `${view} ${width} ${theme}: no leftover placeholder`);
          // The page scrolls an inner container, not the document: the viewport grows to the tallest scroller for the picture, then
          // goes back.
          const tall = await page.evaluate(() => Math.max(...[...document.querySelectorAll("html, body, .pf-v6-c-page, .pf-v6-c-page *")].map((el) => el.scrollHeight)));
          await page.setViewportSize({ width, height: Math.max(1000, tall + 140) });
          await page.screenshot({ path: join(out, `${view}-${width}-${theme}.png`), fullPage: true });
          await page.setViewportSize({ width, height: 1000 });
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

  // #484, the Namespaces tab (design of #481, section 6, T1 to T9; mockup docs/reviews/2026-11-20-epic-481-metadata-patch/
  // mockup-namespaces-tab.html). The instance has the keys of KEYS_479 and the mockup's namespaces (namespacesOfMockup), on
  // CRC (dev) and KIND_CMAPI_TEST (rnd). Each expectation is written from the design, the mockup and the API's answer.
  const NS_CLUSTERS = [SAMPLES.operations.core_clusters.response.body.items[0], RND_CLUSTER];
  const nsFresh = (options = {}) => fresh({ metadataKeys: KEYS_479, namespaces: namespacesOfMockup(), clusters: NS_CLUSTERS, ...options });
  const nsRecord = (name) => api.state.namespaces.find((r) => r.name === name);
  const clusterBox = (page) => page.getByLabel("Cluster", { exact: true });
  const lookupBox = (page) => page.getByRole("combobox", { name: "Namespace", exact: true });
  const nsOptions = (page) => page.locator("#nsx-list [role=option]:not(:disabled)");
  const nsTable = (page, ns) => panel(page).locator(`table[aria-label="Labels and annotations of ${ns}"]`);
  /** The row of one key, by the "label <key>" line under its title. */
  const keyRow = (page, ns, kind, key) => nsTable(page, ns).locator("tbody tr").filter({ has: page.getByText(`${kind} ${key}`, { exact: true }) });
  const cells = (row) => row.locator("td").evaluateAll((tds) => tds.map((td) => td.innerText.replace(/\s+/g, " ").trim()));
  const strip = (page) => panel(page).locator(".pf-v6-c-alert").first();
  const nsStatus = async (page) => (await page.locator("#nsx-status").innerText()).replace(/\s+/g, " ");
  const nsCheck = (page) => panel(page).getByRole("button", { name: "Check (dry run)" });
  const nsSubmit = (page) => panel(page).getByRole("button", { name: "Submit request" });
  const nsPatches = (ns = "abc-payments-dev") => api.state.seen.filter((c) => c.method === "PATCH" && c.path === `/api/v1/clusters/CRC/namespaces/${ns}`);
  const nsDryRuns = (ns) => nsPatches(ns).filter((c) => c.query.dryRun === "true");
  const detailReads = (ns = "abc-payments-dev") => api.state.seen.filter((c) => c.method === "GET" && c.path === `/api/v1/clusters/CRC/namespaces/${ns}`);
  /** Opens one namespace from the address, as a shared link does, and waits for its table. */
  async function openNamespace(page, ns = "abc-payments-dev", cluster = "CRC") {
    await open(page, `#namespaces?cluster=${cluster}&ns=${ns}`);
    await nsTable(page, ns).waitFor();
  }
  /** The change of the design's example (section 4.1): the critical level to 2, the cost code removed, a runbook added. */
  async function draftExample(page) {
    await page.getByLabel("Critical level (required)").selectOption("2");
    await panel(page).getByRole("button", { name: "Remove Cost center" }).click();
    const toggle = panel(page).getByRole("button", { name: /^Add labels and annotations \(optional\)/ });
    if (await toggle.getAttribute("aria-expanded") === "false") await toggle.click();
    await panel(page).getByRole("button", { name: "+ Add annotation" }).click();
    await page.getByLabel("Key of additional annotation 1").fill("runbook.company.net/url");
    await page.getByLabel("Value of additional annotation 1").fill("https://wiki.company.net/abc/runbook");
    await page.getByLabel("Justification (required)").fill("Raise the critical level, retire the cost code and add the on-call runbook.");
  }
  const nsPassed = (page) => panel(page).locator("#nsx-status .pf-v6-c-alert").filter({ hasText: "The check passed (dry run, 200)" });
  /** Runs one check at 390, 820 and 1440 px, in each theme, on a fresh profile. */
  async function atEachNsView(run, options = {}) {
    for (const width of [390, 820, 1440]) {
      for (const theme of ["light", "dark"]) {
        const { context, page, errors } = await nsFresh({ width, ...options });
        try {
          await page.addInitScript((dark) => { if (dark) addEventListener("DOMContentLoaded", () => document.documentElement.classList.add("pf-v6-theme-dark")); }, theme === "dark");
          await run(page, `${width} ${theme}`);
          assert.deepEqual(errors, [], `${width} ${theme}`);
        } catch (error) {
          throw Object.assign(new Error(`${width} ${theme}: ${error.message}`, { cause: error }), { stack: `${width} ${theme}: ${error.stack}` });
        } finally { await context.close(); }
      }
    }
  }

  await check("484-T1 cluster first: every cluster, its mnemonic chips with counts, and a lookup of 2+ letters 250 ms after the last key; a first word that is a mnemonic turns its chip on", async () => {
    await atEachNsView(async (page) => {
      await open(page, "#namespaces");
      assert.deepEqual(await clusterBox(page).locator("option").allInnerTexts(), ["Choose a cluster…", "CRC (dev)", "KIND_CMAPI_TEST (rnd)"], "every cluster that GET /api/v1/clusters lists");
      assert.equal(await lookupBox(page).isDisabled(), true, "the lookup waits for a cluster");
      await panel(page).getByText("Choose a cluster and a namespace to see it.").waitFor();
      await clusterBox(page).selectOption("CRC");
      await panel(page).getByText("7 managed namespaces in CRC. Type 2+ letters, or start with a mnemonic.").waitFor();
      assert.deepEqual(await chips(page, "Mnemonic"), ["All 7", "abc 4", "xyz 2", "lmn 1"], "the cluster's facets, most first");
      assert.deepEqual(api.state.seen.filter((c) => c.path === "/api/v1/clusters/CRC/namespaces").map((c) => c.query), [{ limit: "10" }]);
      const box = lookupBox(page);
      await box.pressSequentially("a");
      await page.waitForTimeout(400);
      assert.equal(api.state.seen.filter((c) => c.path === "/api/v1/clusters/CRC/namespaces").length, 1, "one letter asks nothing");
      await box.pressSequentially("bc pay");
      await page.waitForFunction(() => document.querySelectorAll("#nsx-list [role=option]:not(:disabled)").length === 2);
      assert.deepEqual(api.state.seen.filter((c) => c.path === "/api/v1/clusters/CRC/namespaces").slice(1).map((c) => c.query), [{ q: "pay", mnemonic: "abc", limit: "10" }],
        "one call for the text when the typing stopped: the first word is abc's chip, the rest is q");
      assert.deepEqual(await chips(page, "Mnemonic").then((c) => c.length), 4);
      assert.equal(await panel(page).locator(".pf-v6-c-toggle-group__button.pf-m-selected").innerText(), "abc 4", "abc's chip turned on by itself");
      assert.deepEqual((await nsOptions(page).allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim()),
        ["abc-paylater-dev team billing · pending req-20261120-0011", "abc-payments-dev team payments · unknown"], "team and state; the list reads no Git, so a state is pending or unknown");
      await page.getByText("2 of 2 in CRC · Mnemonic abc · ↑↓ Enter").waitFor();
      assert.deepEqual(await hiddenOptions(page, "#nsx-list"), [], "every option is on the screen, not clipped by the card (#535)");
      // Typed text is not a target: Enter with no option chosen opens nothing.
      await box.fill("abc-payments-dev");
      await page.waitForTimeout(400);
      await box.press("Enter");
      assert.equal(await nsTable(page, "abc-payments-dev").count(), 0);
      assert.equal(new URL(page.url()).hash, "#namespaces?cluster=CRC");
      // A chip filters the lookup; All takes it off.
      await box.fill("");
      await panel(page).getByRole("button", { name: "xyz 2" }).click();
      await box.fill("pa");
      await page.waitForFunction(() => document.querySelectorAll("#nsx-list [role=option]:not(:disabled)").length === 1);
      const asked = api.state.seen.filter((c) => c.path === "/api/v1/clusters/CRC/namespaces").map((c) => c.query);
      assert.deepEqual(asked.at(-1), { q: "pa", mnemonic: "xyz", limit: "10" }, JSON.stringify(asked));
      await nsOptions(page).first().click();
      await nsTable(page, "xyz-payments-dev").waitFor();
      assert.equal(new URL(page.url()).hash, "#namespaces?cluster=CRC&ns=xyz-payments-dev", "the address names the namespace");
      await panel(page).getByRole("button", { name: "xyz-payments-dev", exact: true }).waitFor();
      assert.match(await panel(page).getByText(/^Recent in CRC:/).innerText(), /^Recent in CRC:$/, "the recent list of this browser");
    });
  });

  await check("484-T1 the debounce starts again on the last letter and fires at 250 ms", async () => {
    await atEachNsView(async (page) => {
      await page.clock.install();
      await open(page, "#namespaces?cluster=CRC");
      await panel(page).getByText(/^7 managed namespaces in CRC/).waitFor();
      await page.clock.pauseAt(new Date(Date.now() + 60000));
      const searched = () => api.state.seen.filter((c) => c.query.q);
      await lookupBox(page).fill("le");
      await page.clock.runFor(200);
      await lookupBox(page).fill("led");
      await page.clock.runFor(249);
      assert.equal(searched().length, 0);
      const received = page.waitForRequest((r) => new URL(r.url()).searchParams.get("q") === "led");
      await page.clock.runFor(1);
      await received;
    });
  });

  await check("484-T1 only the latest answer is shown, and a new cluster starts a new lookup", async () => {
    await atEachNsView(async (page) => {
      await open(page, "#namespaces?cluster=CRC");
      await panel(page).getByText(/^7 managed namespaces in CRC/).waitFor();
      const held = Promise.withResolvers(), received = Promise.withResolvers();
      api.state.hold = { match: (c) => c.path === "/api/v1/clusters/CRC/namespaces" && c.query.q === "ledger" && (received.resolve(), true), until: held.promise };
      try {
        await lookupBox(page).fill("ledger");
        await received.promise;
        await lookupBox(page).fill("orders");
        await page.waitForFunction(() => document.querySelector("#nsx-list [role=option]:not(:disabled)")?.innerText.startsWith("xyz-orders-dev"));
      } finally {
        api.state.hold = null;
        held.resolve();
      }
      await page.waitForTimeout(300);
      assert.deepEqual((await nsOptions(page).allInnerTexts()).map((t) => t.split("\n")[0]), ["xyz-orders-dev"], "the late answer for ledger never shows");
      await clusterBox(page).selectOption("KIND_CMAPI_TEST");
      await panel(page).getByText(/^3 managed namespaces in KIND_CMAPI_TEST/).waitFor();
      assert.equal(await lookupBox(page).inputValue(), "");
      assert.deepEqual(await chips(page, "Mnemonic"), ["All 3", "abc 2", "qrs 1"]);
    });
  });

  await check("484-T2 loading a namespace reads its Git, live state and sync, and the rules' x-cmapi-edit: fixed keys locked with their reason, sensitive keys marked", async () => {
    await atEachNsView(async (page) => {
      await openNamespace(page);
      assert.equal(detailReads().length, 1, "GET .../namespaces/abc-payments-dev");
      assert.ok(api.state.seen.some((c) => c.path === "/api/v1/metadata-keys"), "GET /api/v1/metadata-keys");
      for (const [kind, key, title, git, reason] of [["label", "name", "Name", "abc-payments-dev", "Copied from the namespace name."],
        // A fixed key that the file does not declare and Git holds (a system key): locked, with the read's reason.
        ["label", "cmapi.net/managed", "cmapi.net/managed", "true", "Managed by cmapi."],
        ["label", "company.net/app-environment", "App environment", "dev", "Copied from the cluster's environment."],
        ["label", "company.net/mnemonic", "Mnemonic", "abc", "Part of the namespace's fixed name."],
        // This annotation has no title in the configuration: the key names it, as on the New namespace form.
        ["annotation", "company.net/app-environment", "company.net/app-environment", "dev", "Copied from the cluster's environment."],
        ["annotation", "cmapi.net/expires-at", "Expires", "2026-12-15", "Change it with Extend, Set expiry or Make permanent."]]) {
        const row = keyRow(page, "abc-payments-dev", kind, key);
        const [k, g, , change] = await cells(row);
        assert.equal(k, `${title} fixed ${kind} ${key}`, `${key}: locked, marked fixed`);
        assert.equal(g, git, `${key}: what Git holds`);
        assert.equal(change, reason, `${key}: the reason of x-cmapi-edit`);
        assert.equal(await row.locator("input, select").count(), 0, `${key}: nothing to type in`);
      }
      for (const [key, title] of [["company.net/cl", "Critical level (required)"], ["cmapi.net/team", "Team (required)"]]) {
        assert.equal((await cells(keyRow(page, "abc-payments-dev", "label", key)))[0], `${title} sensitive label ${key}`, `${key} is sensitive`);
      }
      assert.equal((await cells(keyRow(page, "abc-payments-dev", "label", "company.net/lob")))[0], "Line of business (required) label company.net/lob");
      assert.equal(await page.getByLabel("Critical level (required)").inputValue(), "1", "a changeable key starts from what Git holds");
      assert.deepEqual(await page.getByLabel("Critical level (required)").locator("option").allInnerTexts(), ["0", "1", "2", "3", "4", "5", "6"], "no empty choice: the key has a value");
    });
  });

  await check("484-T3 Git, Live and Your change side by side, and the status strip: Drift with each drifted key, In sync, Pending with its request, Unknown", async () => {
    await atEachNsView(async (page) => {
      nsRecord("abc-payments-dev").live.labels["team.company.net/owner"] = "old";
      nsRecord("abc-reports-dev").liveFresh = false;
      // A pending namespace whose watch went stale: the read lists no drift, and the last value seen is not Git's.
      const stale = nsRecord("abc-paylater-dev");
      stale.liveFresh = false;
      stale.live.labels["cmapi.net/team"] = "last-seen";
      await openNamespace(page);
      assert.deepEqual(await nsTable(page, "abc-payments-dev").locator("thead th").allTextContents(), ["Key", "Git (desired)", "Live (cluster)", "Your change"]);
      const titleOf = async () => (await strip(page).locator(".pf-v6-c-alert__title").innerText()).replace(/^\w+ alert:\s*/, "");
      const textOf = () => strip(page).locator(".pf-v6-c-alert__description").innerText();
      assert.equal(await titleOf(), "Drift");
      assert.equal(await textOf(), "2 keys on the cluster differ from Git · no open request. Your change applies to Git, which the cluster is brought back to.");
      assert.deepEqual((await cells(keyRow(page, "abc-payments-dev", "label", "team.company.net/owner"))).slice(1, 3), ["—", "drift old"]);
      assert.deepEqual((await cells(keyRow(page, "abc-payments-dev", "label", "company.net/lob"))).slice(1, 3), ["amgsst", "drift amgsst-old"], "the drifted key with both values");
      assert.deepEqual((await cells(keyRow(page, "abc-payments-dev", "label", "company.net/cl"))).slice(1, 3), ["1", "✓ 1"]);
      for (const [ns, title, text] of [["abc-ledger-dev", "In sync", "The cluster has what Git holds."],
        ["abc-paylater-dev", "Pending", "req-20261120-0011 (pending_approval) holds abc-paylater-dev."],
        ["abc-reports-dev", "Unknown", "cmapi cannot compare Git with the cluster now: the cluster's watch is not fresh."]]) {
        await open(page, `#namespaces?cluster=CRC&ns=${ns}`);
        await nsTable(page, ns).waitFor();
        await page.waitForFunction((t) => document.querySelector("[role=tabpanel] .pf-v6-c-alert__title")?.innerText.endsWith(t), title);
        assert.equal(await textOf(), text, ns);
        if (title === "Pending") assert.equal(await strip(page).getByRole("button", { name: "Open at current step" }).count(), 1, "the request's link");
        if (title === "Pending") assert.equal((await cells(keyRow(page, ns, "label", "cmapi.net/team")))[2], "last-seen", "a value that is not Git's has no tick");
        if (title === "Unknown") assert.equal((await cells(keyRow(page, ns, "label", "company.net/cl")))[2], "1", "nothing compared: no mark");
      }
    });
  });

  await check("484-T4 changeable fields reuse the New namespace form's inputs and checks as typed; removing an optional key stages null with Undo", async () => {
    await atEachNsView(async (page) => {
      await openNamespace(page);
      const lob = page.getByLabel("Line of business (required)");
      await lob.fill("amg sst");
      await waitError(lob, /^Not a valid label value/);
      assert.equal(await lob.getAttribute("aria-invalid"), "true");
      await lob.fill("");
      await waitError(lob, /^Required: /);
      await lob.fill("retail");
      await waitError(lob, null);
      assert.match((await cells(keyRow(page, "abc-payments-dev", "label", "company.net/lob")))[3], /^changed$/, "the row says it changed");
      const dl = page.getByLabel("Team DL (required)");
      await dl.fill("payments-team@other.example");
      await waitError(dl, /^Not valid: an address in/);
      await dl.fill("payments-team@company.net");
      await waitError(dl, null);
      await panel(page).getByRole("button", { name: "Remove Cost center" }).click();
      const cost = keyRow(page, "abc-payments-dev", "label", "cmapi.net/cost-center");
      assert.equal((await cells(cost))[3], "cc-4410 removed ↺ Undo", "a removal is staged, with Undo");
      assert.equal(await cost.locator("del").innerText(), "cc-4410");
      await panel(page).getByRole("button", { name: "Undo the removal of Cost center" }).click();
      await waitValue(page.getByLabel("Cost center (optional)"), "cc-4410");
      assert.equal(await keyRow(page, "abc-payments-dev", "label", "company.net/lob").getByRole("button").count(), 0, "a required key is never removed");
      assert.equal(nsPatches().length, 0, "nothing is sent while typing");
    });
  });

  await check("484-T5 existing additional keys can be edited and removed; new ones go in the closed, empty Add labels and annotations section", async () => {
    await atEachNsView(async (page) => {
      await openNamespace(page);
      const squad = keyRow(page, "abc-payments-dev", "label", "team.company.net/squad");
      assert.equal((await cells(squad))[0], "team.company.net/squad additional label team.company.net/squad");
      const value = page.getByLabel("Value of label team.company.net/squad");
      assert.equal(await value.inputValue(), "checkout");
      await value.fill("check out");
      await waitError(value, /^A label value: /);
      await value.fill("payments");
      await waitError(value, null);
      await panel(page).getByRole("button", { name: "Remove label team.company.net/squad" }).click();
      assert.equal((await cells(squad))[3], "checkout removed ↺ Undo");
      const toggle = panel(page).getByRole("button", { name: /^Add labels and annotations \(optional\)/ });
      assert.equal(await toggle.getAttribute("aria-expanded"), "false", "closed by default");
      assert.match(await toggle.innerText(), /none$/);
      assert.equal(await page.locator("[id^=ns-xl-], [id^=ns-xa-]").count(), 0, "empty by default");
      await toggle.click();
      await panel(page).getByRole("button", { name: "+ Add label" }).click();
      const key = page.getByLabel("Key of additional label 1");
      await key.fill("team.company.net/squad");
      await waitError(key, /^This key is already on the namespace: change it in the table\./);
      await key.fill("kubernetes.io/team");
      await waitError(key, /^The prefix must be \*\.company\.net\/ \(or none\)\./);
      await key.fill("team.company.net/oncall");
      await page.getByLabel("Value of additional label 1").fill("alice");
      await waitError(key, null);
      await toggle.click();
      assert.match(await toggle.innerText(), /1 label, 0 annotations$/, "closed, it counts what it holds");
    });
  });

  await check("484-T6 the change box lists only effective changes, before and after, with the sensitive mark; Justification is required", async () => {
    await atEachNsView(async (page) => {
      await openNamespace(page);
      const box = panel(page).getByRole("list", { name: "The change", exact: true });
      assert.deepEqual(await box.locator("li").allInnerTexts(), ["No change yet."]);
      await draftExample(page);
      const lines = async () => (await box.locator("li").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim());
      assert.deepEqual(await lines(), ["label company.net/cl 1 → 2 +1 approval", "label cmapi.net/cost-center cc-4410 → (removed)",
        "annotation runbook.company.net/url (new) → https://wiki.company.net/abc/runbook"]);
      await page.getByLabel("Critical level (required)").selectOption("1");
      assert.deepEqual(await lines(), ["label cmapi.net/cost-center cc-4410 → (removed)", "annotation runbook.company.net/url (new) → https://wiki.company.net/abc/runbook"],
        "back to what Git holds: no change");
      await page.getByLabel("Justification (required)").fill("");
      await nsCheck(page).click();
      await panel(page).getByText("The check did not run. Fix these:").waitFor();
      assert.match(await nsStatus(page), /Justification: say why this change is needed\./);
      assert.equal(nsPatches().length, 0, "nothing is sent");
      await panel(page).getByRole("button", { name: "Justification: say why this change is needed." }).click();
      await page.waitForFunction(() => document.activeElement?.id === "nsx-why");
    });
  });

  await check("484-T7 Check sends the dry run with If-Match; the server's metadataDiff and approval replace the estimate; Submit is off until checked and after any change", async () => {
    await atEachNsView(async (page) => {
      await openNamespace(page);
      const etag = recordEtag(nsRecord("abc-payments-dev"));
      await draftExample(page);
      assert.equal(await nsSubmit(page).getAttribute("aria-disabled"), "true", "not checked: Submit is off");
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      const dry = nsDryRuns().at(-1);
      assert.equal(dry.ifMatch, `"${etag}"`, "If-Match: the etag that the namespace was read at, quoted");
      assert.equal(dry.key, null, "a dry run takes no Idempotency-Key");
      assert.deepEqual(dry.body, { labels: { "company.net/cl": "2", "cmapi.net/cost-center": null }, annotations: { "runbook.company.net/url": "https://wiki.company.net/abc/runbook" },
        justification: "Raise the critical level, retire the cost code and add the on-call runbook." }, "a merge patch: null removes the cost center");
      assert.match(await nsStatus(page), /1 approval in cmapi from approver-platform\. dev change: 0 from approver-platform; threshold sensitiveKeyChanged: \+1 approver-platform\./);
      assert.match(await nsStatus(page), new RegExp(`If-Match "${etag}"`));
      const fromPlan = panel(page).getByRole("list", { name: "The change, from the dry run" });
      assert.deepEqual((await fromPlan.locator("li").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim()), ["label cmapi.net/cost-center cc-4410 → (removed)",
        "label company.net/cl 1 → 2 +1 approval", "annotation runbook.company.net/url (new) → https://wiki.company.net/abc/runbook"], "the plan's metadataDiff");
      assert.equal(await nsSubmit(page).getAttribute("aria-disabled"), null, "checked: Submit is on");
      await page.getByLabel("Critical level (required)").selectOption("3");
      await panel(page).getByText("Changed since the last check. Press Check (dry run) again.").waitFor();
      assert.equal(await nsSubmit(page).getAttribute("aria-disabled"), "true", "a change turns Submit off");
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      // Reverting an unchecked edit cannot resurrect the previous pass.
      await page.getByLabel("Critical level (required)").selectOption("4");
      await page.getByLabel("Critical level (required)").selectOption("3");
      await panel(page).getByText("Changed since the last check. Press Check (dry run) again.").waitFor();
      assert.equal(await nsSubmit(page).getAttribute("aria-disabled"), "true");
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      api.state.delayMs = 600;
      await nsCheck(page).click();
      await panel(page).getByText("Checking with cmapi…").waitFor();
      assert.equal(await nsSubmit(page).getAttribute("aria-disabled"), "true");
      await nsPassed(page).waitFor();
      api.state.delayMs = 0;
      // #527: the first change again is asked again, not answered from the cache.
      await page.getByLabel("Critical level (required)").selectOption("2");
      const before = nsDryRuns().length;
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      for (let i = 0; i < 20 && nsDryRuns().length === before; i++) await page.waitForTimeout(100);
      assert.equal(nsDryRuns().length, before + 1, "Check asks cmapi again for a change that it checked before");
      assert.equal(nsPatches().filter((c) => c.query.dryRun !== "true").length, 0, "nothing was submitted");
    });
  });

  await check("484-T8 409: the holder is shown and Submit stays off until Reload, also when the holder has already finished", async () => {
    await atEachNsView(async (page) => {
      await openNamespace(page);
      await draftExample(page);
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      // Someone else's request takes the lock after the check: the dry run does not check it, the submit does (repo.py).
      nsRecord("abc-payments-dev").openRequest = { requestId: "req-20261121-0009", status: "pr_open" };
      expectedStatus = [409];
      await nsSubmit(page).click();
      await panel(page).getByText("409 change-pending. Not submitted.").waitFor();
      assert.match(await nsStatus(page), /req-20261121-0009 holds abc-payments-dev\. Submit stays off until it finishes: then Reload\./);
      await page.waitForFunction(() => document.querySelector("[role=tabpanel] .pf-v6-c-alert__title")?.innerText.endsWith("Pending"));
      assert.equal(await strip(page).locator(".pf-v6-c-alert__description").innerText(),
        "req-20261121-0009 (pr_open) holds abc-payments-dev. Submit stays off until it finishes and you reload.");
      assert.equal(await nsSubmit(page).getAttribute("aria-disabled"), "true");
      // The holder finishes before the next read: Submit stays off until the person reloads (design T8).
      nsRecord("abc-payments-dev").openRequest = null;
      await strip(page).getByRole("button", { name: "Reload" }).click();
      await page.waitForFunction(() => document.querySelector("[role=tabpanel] .pf-v6-c-alert__title")?.innerText.endsWith("Drift"));
      await draftExample(page);
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      // The next write meets a holder that ends before the namespace is read again.
      api.state.answers.push({ route: "PATCH /api/v1/clusters/CRC/namespaces/abc-payments-dev", status: 409,
        body: { type: "https://cmapi.ephico2real.com/problems/change-pending", title: "change-pending", status: 409, code: "change-pending", detail: "req-20261121-0010 holds abc-payments-dev", requestId: "req-20261121-0010" } });
      await nsSubmit(page).click();
      await panel(page).getByText("409 change-pending. Not submitted.").waitFor();
      await page.waitForFunction(() => document.querySelector("[role=tabpanel] .pf-v6-c-alert__title")?.innerText.endsWith("Drift"));
      assert.equal(await nsSubmit(page).getAttribute("aria-disabled"), "true", "no holder on the page now, and Submit is still off until Reload");
      await strip(page).getByRole("button", { name: "Reload" }).click();
      await panel(page).getByText("Make a change, then press Check (dry run).").waitFor();
      assert.deepEqual(await panel(page).getByRole("list", { name: "The change", exact: true }).locator("li").allInnerTexts(), ["No change yet."], "Reload starts from Git again");
    });
  });

  await check("484-T8 412: Git changed meanwhile; the namespace is read again, the other edits are kept, each key both sides changed is asked, and a new Check uses the new ETag", async () => {
    await atEachNsView(async (page) => {
      await openNamespace(page);
      const rec = nsRecord("abc-payments-dev"), first = recordEtag(rec);
      await page.getByLabel("Line of business (required)").fill("retail");
      await page.getByLabel("Critical level (required)").selectOption("2");
      await page.getByLabel("Cost center (optional)").fill("cc-9999");
      await page.getByLabel("Justification (required)").fill("Retail line, higher level, new cost code.");
      await panel(page).getByRole("button", { name: /^Add labels and annotations/ }).click();
      await panel(page).getByRole("button", { name: "+ Add annotation" }).click();
      await page.getByLabel("Key of additional annotation 1").fill("runbook.company.net/url");
      await page.getByLabel("Value of additional annotation 1").fill("my-runbook");
      for (const map of [rec.git, rec.live]) map.annotations["runbook.company.net/url"] = "their-runbook";
      // Someone's merged request added the same annotation and moved two of the same labels in Git (and on the cluster).
      for (const map of [rec.git, rec.live]) Object.assign(map.labels, { "company.net/cl": "3", "cmapi.net/cost-center": "cc-5000" });
      const second = recordEtag(rec);
      expectedStatus = [412];
      await nsCheck(page).click();
      await panel(page).getByText("412: the namespace changed in Git. Reloaded; your other changes are kept. Both sides changed these keys:").waitFor();
      assert.equal(nsDryRuns().at(-1).ifMatch, `"${first}"`);
      assert.match(await nsStatus(page), /company\.net\/cl: now 3, yours 2/);
      assert.match(await nsStatus(page), /cmapi\.net\/cost-center: now cc-5000, yours cc-9999/);
      assert.equal((await cells(keyRow(page, "abc-payments-dev", "label", "company.net/cl")))[1], "3", "the table shows the new Git");
      assert.equal(await page.getByLabel("Line of business (required)").inputValue(), "retail", "a key that only this person changed is kept");
      assert.equal(await nsSubmit(page).getAttribute("aria-disabled"), "true");
      const sent = nsDryRuns().length;
      await nsCheck(page).click();
      assert.equal(nsDryRuns().length, sent, "no Check until each key is chosen");
      await panel(page).getByRole("button", { name: "Use current for company.net/cl" }).click();
      await panel(page).getByRole("button", { name: "Keep my edit for cmapi.net/cost-center" }).click();
      await panel(page).getByText("412: the namespace changed in Git. Reloaded; your changes are kept. Press Check (dry run) again.").waitFor();
      await waitValue(page.getByLabel("Critical level (required)"), "3");
      // The annotation that both people added is a row of the table now: the new row cannot send it over the other value.
      await nsCheck(page).click();
      await panel(page).getByText("This key is already on the namespace: change it in the table.").first().waitFor();
      assert.equal(nsDryRuns().length, sent, "no Check while a new key is one that Git now holds");
      assert.equal((await cells(keyRow(page, "abc-payments-dev", "annotation", "runbook.company.net/url")))[1], "their-runbook");
      await page.getByLabel("Key of additional annotation 1").fill("runbook.company.net/mine");
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      const dry = nsDryRuns().at(-1);
      assert.equal(dry.ifMatch, `"${second}"`, "the new ETag");
      assert.deepEqual(dry.body.annotations, { "runbook.company.net/mine": "my-runbook" });
      assert.deepEqual(dry.body.labels, { "company.net/lob": "retail", "cmapi.net/cost-center": "cc-9999" }, "Use current dropped cl; Keep my edit kept the cost code");
      // A 412 of Submit: read again, Check again, and the stale ETag is never sent again.
      for (const map of [rec.git, rec.live]) map.labels["cmapi.net/app"] = "web";
      const third = recordEtag(rec);
      await nsSubmit(page).click();
      await panel(page).getByText("412: the namespace changed in Git. Reloaded; your changes are kept. Press Check (dry run) again.").waitFor();
      assert.equal(await nsSubmit(page).getAttribute("aria-disabled"), "true");
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      await nsSubmit(page).click();
      await panel(page).getByText(/Request req-\d{8}-6\d{3} submitted \(202\)\./).waitFor();
      const writes = nsPatches().filter((c) => c.query.dryRun !== "true");
      assert.deepEqual(writes.map((c) => c.ifMatch), [`"${second}"`, `"${third}"`], "one stale write refused, then the new ETag");
    });
  });

  await check("484-T9 after 202: the request with its link; the strip turns Pending, then In sync when the cluster has the change, on Reload (no polling)", async () => {
    await atEachNsView(async (page) => {
      await openNamespace(page);
      await draftExample(page);
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      await nsSubmit(page).click();
      const done = panel(page).locator("#nsx-status .pf-v6-c-alert").filter({ hasText: /submitted \(202\)/ });
      await done.waitFor();
      const write = nsPatches().filter((c) => c.query.dryRun !== "true").at(-1);
      assert.match(write.key ?? "", /^[0-9a-f-]{36}$/, "an Idempotency-Key");
      assert.equal(write.ifMatch, nsDryRuns().at(-1).ifMatch, "the If-Match that was checked");
      assert.deepEqual(write.body, nsDryRuns().at(-1).body, "Submit sends the checked body");
      const id = nsRecord("abc-payments-dev").openRequest.requestId;
      assert.match(await done.innerText(), new RegExp(`Request ${id} submitted \\(202\\)\\.\\s+The strip shows Pending until the cluster has the change\\.`));
      await page.waitForFunction(() => document.querySelector("[role=tabpanel] .pf-v6-c-alert__title")?.innerText.endsWith("Pending"));
      assert.equal(await strip(page).locator(".pf-v6-c-alert__description").innerText(), `${id} (pending_approval) holds abc-payments-dev.`);
      assert.deepEqual(await panel(page).getByRole("list", { name: "The change", exact: true }).locator("li").allInnerTexts(), ["No change yet."]);
      const reads = detailReads().length;
      await page.waitForTimeout(1500);
      assert.equal(detailReads().length, reads, "no polling loop");
      await done.getByRole("button", { name: "Open at current step" }).click();
      await page.waitForURL((url) => url.hash === `#workflow?request=${id}`);
      await openNamespace(page);
      // The request merges and the cluster syncs: Reload shows it.
      syncRecord(nsRecord("abc-payments-dev"));
      await strip(page).getByRole("button", { name: "Reload" }).click();
      await page.waitForFunction(() => document.querySelector("[role=tabpanel] .pf-v6-c-alert__title")?.innerText.endsWith("In sync"));
      assert.deepEqual((await cells(keyRow(page, "abc-payments-dev", "label", "company.net/cl"))).slice(1, 3), ["2", "✓ 2"]);
      assert.equal((await cells(keyRow(page, "abc-payments-dev", "annotation", "runbook.company.net/url")))[1], "https://wiki.company.net/abc/runbook", "the new key is in Git");
    });
  });

  await check("484-O operator-only keys: changeable with namespaces:protect in the namespace's environment, locked with the API's reason for anyone else", async () => {
    const withProtection = () => { const r = nsRecord("abc-payments-dev"); for (const m of [r.git, r.live]) m.labels["do-not-delete"] = "true"; };
    const REASON = "Needs namespaces:protect in dev. Changing this key needs one more approval.";
    await atEachNsView(async (page) => {
      withProtection();
      await openNamespace(page);
      assert.deepEqual((await cells(keyRow(page, "abc-payments-dev", "label", "do-not-delete"))).slice(2), ["✓ true", REASON], "a requester: locked, with the API's reason");
      assert.equal(await keyRow(page, "abc-payments-dev", "label", "cmapi.net/protected").count(), 0, "a key that Git lacks is not offered to a requester");
      assert.equal(await page.getByLabel("Value of label do-not-delete").count(), 0);
    });
    await atEachNsView(async (page) => {
      withProtection();
      await openNamespace(page);
      assert.equal(await page.getByLabel("Value of label do-not-delete").inputValue(), "true", "an operator types in it");
      await page.getByLabel("Value of label cmapi.net/protected").fill("true");
      await panel(page).getByRole("button", { name: "Remove label do-not-delete" }).click();
      await page.getByLabel("Justification (required)").fill("Protect with the cmapi label instead.");
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      assert.deepEqual(nsDryRuns().at(-1).body.labels, { "do-not-delete": null, "cmapi.net/protected": "true" });
      assert.match(await nsStatus(page), /1 approval in cmapi from approver-platform/, "a sensitive key adds one approval");
    }, { user: "operator" });
  });

  await check("484-R a key that no rule admits: locked against typing, with Remove and Undo only; the removal sends null", async () => {
    await atEachNsView(async (page) => {
      const rec = nsRecord("abc-payments-dev");
      for (const m of [rec.git, rec.live]) m.labels["old.invalid/key"] = "legacy";
      await openNamespace(page);
      const row = keyRow(page, "abc-payments-dev", "label", "old.invalid/key");
      assert.deepEqual(await cells(row), ["old.invalid/key fixed label old.invalid/key", "legacy", "✓ legacy", "Not allowed by this instance's rules. Remove"]);
      assert.equal(await row.locator("input, select").count(), 0, "never set or changed");
      assert.equal(await keyRow(page, "abc-payments-dev", "label", "cmapi.net/managed").locator("input, button").count(), 0, "cmapi's own key is locked");
      await panel(page).getByRole("button", { name: "Remove label old.invalid/key" }).click();
      assert.equal((await cells(row))[3], "legacy removed ↺ Undo");
      await panel(page).getByRole("button", { name: "Undo the removal of label old.invalid/key" }).click();
      assert.equal((await cells(row))[3], "Not allowed by this instance's rules. Remove");
      await panel(page).getByRole("button", { name: "Remove label old.invalid/key" }).click();
      await page.getByLabel("Justification (required)").fill("Drop a key from before the rules.");
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      assert.deepEqual(nsDryRuns().at(-1).body.labels, { "old.invalid/key": null }, "a merge patch removal");
      assert.deepEqual((await panel(page).getByRole("list", { name: "The change, from the dry run" }).locator("li").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim()),
        ["label old.invalid/key legacy → (removed)"]);
    });
  });

  await check("484-K keyboard: the cluster, then the lookup with arrow keys and Enter", async () => {
    await atEachNsView(async (page) => {
      await open(page, "#namespaces");
      await clusterBox(page).focus();
      // A closed select takes the first letter of an option (HTML's select type-ahead); the arrow keys open the native list on macOS.
      await page.keyboard.press("C");
      await panel(page).getByText(/^7 managed namespaces in CRC/).waitFor();
      assert.equal(await clusterBox(page).inputValue(), "CRC", "the key chose the cluster");
      for (let i = 0; i < 6 && await page.evaluate(() => document.activeElement?.id) !== "nsx-ns"; i++) await page.keyboard.press("Tab");
      assert.equal(await page.evaluate(() => document.activeElement?.id), "nsx-ns", "Tab reaches the lookup after the chips");
      await page.keyboard.type("abc pay");
      await page.waitForFunction(() => document.querySelectorAll("#nsx-list [role=option]:not(:disabled)").length === 2);
      const box = lookupBox(page);
      assert.deepEqual(await hiddenOptions(page, "#nsx-list"), [], "keyboard matches are on the screen before any arrow key can scroll them (#535)");
      await page.keyboard.press("ArrowDown");
      await box.and(page.locator('[aria-activedescendant="nsx-opt-0"]')).waitFor();
      assert.equal(await box.getAttribute("aria-activedescendant"), "nsx-opt-0");
      await page.keyboard.press("ArrowDown");
      await box.and(page.locator('[aria-activedescendant="nsx-opt-1"]')).waitFor();
      assert.equal(await box.getAttribute("aria-activedescendant"), "nsx-opt-1");
      assert.equal(await nsOptions(page).nth(1).getAttribute("aria-selected"), "true");
      // The ARIA APG combobox: DOM focus stays on the input while the list, in document.body (#535), shows the active option.
      assert.equal(await page.evaluate(() => document.activeElement?.id), "nsx-ns", "focus stays on the combobox");
      await page.keyboard.press("ArrowUp");
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Enter");
      await nsTable(page, "abc-payments-dev").waitFor();
      assert.equal(await box.getAttribute("aria-expanded"), "false");
      await box.fill("xyz o");
      await page.waitForFunction(() => document.querySelectorAll("#nsx-list [role=option]:not(:disabled)").length === 1);
      await page.keyboard.press("Escape");
      await box.and(page.locator("[aria-expanded=false]")).waitFor();
      assert.equal(await box.getAttribute("aria-expanded"), "false", "Escape closes the list");
      await checkComboBoxLifecycle(page, box, "#nsx-list", "abc pay", "#requests");
    });
  });

  await check("484-6 the tab says the mockup's words: each static string of the mockup is on the page, or listed as a difference", async () => {
    const mockup = readFileSync(join(app, "..", "docs", "reviews", "2026-11-20-epic-481-metadata-patch", "mockup-namespaces-tab.html"), "utf8");
    // The page part of the mockup (from its heading to its script), without the Simulate buttons, which stand in for the API.
    const part = mockup.slice(mockup.indexOf("<h1>"), mockup.indexOf("<script>")).replace(/<div class="sim">[\s\S]*?<\/div>/, "");
    const texts = [...new Set(part.replace(/<[^>]+>/g, "\n").split("\n").map((t) => t.replace(/\s+/g, " ").trim()).filter(Boolean))];
    // MOCKUP-CONTRACT.md, "Where the portal's Namespaces tab differs": the required mark in words, the caret and the placeholder sentence of the closed section.
    const LISTED = ["Justification *", "▸", "Two empty key/value tables, as on the New namespace form (closed and empty by default; checked as you type)."];
    const fromMockup = texts.filter((t) => !LISTED.includes(t));
    assert.ok(fromMockup.length >= 20, `the mockup was read (${fromMockup.length} strings)`);
    const { context, page, errors } = await nsFresh();
    await open(page, "#namespaces");
    await panel(page).getByText("Choose a cluster and a namespace to see it.").waitFor();
    let shown = await panel(page).innerText();
    await openNamespace(page);
    shown += ` ${await panel(page).innerText()}`;
    const squeeze = (t) => t.replace(/\s+/g, "");
    assert.deepEqual(fromMockup.filter((t) => !squeeze(shown).includes(squeeze(t))), [], "each string of the mockup is on the page");
    assert.deepEqual(errors, []);
    await context.close();
    console.log(`  ${fromMockup.length} strings of the mockup compared, ${LISTED.length} listed`);
  });

  await check("484-V a viewer reads a namespace with no change box; a role limited to rnd has it on an rnd namespace only", async () => {
    for (const [user, ns, cluster, writes] of [["viewer", "abc-payments-dev", "CRC", false], ["rndRequester", "abc-payments-dev", "CRC", false], ["rndRequester", "abc-payments-rnd", "KIND_CMAPI_TEST", true]]) {
      const { context, page, errors } = await nsFresh({ user });
      await openNamespace(page, ns, cluster);
      assert.equal(await panel(page).getByRole("heading", { name: "Your change" }).count(), writes ? 1 : 0, `${user} on ${ns}`);
      assert.equal(await page.getByLabel("Line of business (required)").count(), writes ? 1 : 0, `${user} on ${ns}: inputs`);
      if (!writes) await panel(page).getByText(`Changing this namespace needs namespaces:write in ${cluster === "CRC" ? "dev" : "rnd"}.`).waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
  });

  // The states of the Namespaces tab at 390, 820 and 1440 px in each theme, with axe at phone and desktop width; one check for each
  // state, so no check nears CHECK_TIMEOUT_MS (#508, #521). The screenshots at 390 and 1440 go to test-output/api/484-namespaces-tab (#530).
  const NS_LAYOUT_VIEWS = [
    ["empty", async (page) => { await open(page, "#namespaces"); await panel(page).getByText("Choose a cluster and a namespace to see it.").waitFor(); }],
    ["lookup", async (page) => {
      await open(page, "#namespaces?cluster=CRC");
      await lookupBox(page).fill("abc pay");
      await page.waitForFunction(() => document.querySelectorAll("#nsx-list [role=option]:not(:disabled)").length === 2);
    }],
    ["drift", (page) => openNamespace(page)],
    ["in-sync", (page) => openNamespace(page, "abc-ledger-dev")],
    ["pending", (page) => openNamespace(page, "abc-paylater-dev")],
    ["unknown", async (page) => { nsRecord("abc-reports-dev").liveFresh = false; await openNamespace(page, "abc-reports-dev"); }],
    ["problems", async (page) => {
      await openNamespace(page);
      await page.getByLabel("Line of business (required)").fill("amg sst");
      await panel(page).getByRole("button", { name: /^Add labels and annotations \(optional\)/ }).click();
      await panel(page).getByRole("button", { name: "+ Add label" }).click();
      await page.getByLabel("Key of additional label 1").fill("kubernetes.io/team");
      await nsCheck(page).click();
      await panel(page).getByText("The check did not run. Fix these:").waitFor();
    }],
    ["checked", async (page) => { await openNamespace(page); await draftExample(page); await nsCheck(page).click(); await nsPassed(page).waitFor(); }],
    ["conflict", async (page) => {
      await openNamespace(page);
      await page.getByLabel("Critical level (required)").selectOption("2");
      await page.getByLabel("Justification (required)").fill("Higher level.");
      const rec = nsRecord("abc-payments-dev");
      for (const map of [rec.git, rec.live]) map.labels["company.net/cl"] = "3";
      expectedStatus = [412];
      await nsCheck(page).click();
      await panel(page).getByText(/Both sides changed these keys:/).waitFor();
    }],
    ["held", async (page) => {
      await openNamespace(page);
      await draftExample(page);
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      nsRecord("abc-payments-dev").openRequest = { requestId: "req-20261121-0009", status: "pr_open" };
      expectedStatus = [409];
      await nsSubmit(page).click();
      await panel(page).getByText("409 change-pending. Not submitted.").waitFor();
      await page.waitForFunction(() => document.querySelector("[role=tabpanel] .pf-v6-c-alert__title")?.innerText.endsWith("Pending"));
    }],
    ["submitted", async (page) => {
      await openNamespace(page);
      await draftExample(page);
      await nsCheck(page).click();
      await nsPassed(page).waitFor();
      await nsSubmit(page).click();
      await panel(page).getByText(/submitted \(202\)/).waitFor();
      await page.waitForFunction(() => document.querySelector("[role=tabpanel] .pf-v6-c-alert__title")?.innerText.endsWith("Pending"));
    }]
  ];
  // The committed screenshots are the pull request's evidence, captured once: a run writes them only when asked to (#530).
  const shots = process.env.UPDATE_COMMITTED_SCREENSHOTS === "1" ? join(app, "screenshots", "484-namespaces-tab") : join(out, "484-namespaces-tab");
  mkdirSync(shots, { recursive: true });
  for (const [state, reach] of NS_LAYOUT_VIEWS) {
    await check(`484-L the Namespaces tab at 390, 820 and 1440 px in each theme, and axe at phone and desktop width: ${state}`, async () => {
      let scans = 0;
      for (const width of [390, 820, 1440]) {
        const { context, page, errors } = await nsFresh({ width });
        await reach(page);
        if (state !== "empty" && state !== "lookup") {
          const height = await page.evaluate(() => Math.max(...[...document.querySelectorAll("*")].map((el) => el.scrollHeight)));
          await page.setViewportSize({ width, height: height + 200 });
        }
        for (const theme of ["light", "dark"]) {
          await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
          await settle(page);
          assert.equal(await running(page), 0, `${state} ${width} ${theme}: no colour transition still runs when the page is read`);
          const layout = await page.evaluate(() => {
            const main = document.querySelector(".pf-v6-c-page__main-container") ?? document.documentElement;
            return { doc: document.documentElement.scrollWidth - document.documentElement.clientWidth, main: main.scrollWidth - main.clientWidth, text: document.body.innerText };
          });
          assert.ok(layout.doc <= 0 && layout.main <= 0, `${state} ${width} ${theme}: no sideways scroll (${layout.doc}, ${layout.main})`);
          assert.doesNotMatch(layout.text, /\{\{|undefined|NaN|\[object|null/, `${state} ${width} ${theme}: no leftover placeholder`);
          if (!["empty", "lookup"].includes(state)) {
            // The owner's choice: the change box sits beside the table from PatternFly's md (48rem, 768 px), below it on a phone.
            const [table, change] = await Promise.all([panel(page).locator("table[aria-label^='Labels and annotations of ']").boundingBox(),
              panel(page).getByRole("heading", { name: "Your change" }).boundingBox()]);
            assert.equal(change.x > table.x + table.width, width >= 768, `${state} ${width}: the change box is ${width >= 768 ? "beside" : "below"} the table`);
          }
          const shot = `${state}-${width}-${theme}.png`;
          await page.screenshot({ path: join(width === 820 ? out : shots, width === 820 ? `484-${shot}` : shot), fullPage: true });
          if (width !== 820) {
            const scan = await new AxeBuilder({ page }).analyze();
            scans++;
            assert.deepEqual(scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes[0]?.html}`), [], `axe on ${state} at ${width} ${theme}`);
          }
        }
        assert.deepEqual(errors, []);
        await context.close();
      }
      console.log(`  ${state}: 3 widths, 2 themes, ${scans} axe scans`);
    });
  }

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
