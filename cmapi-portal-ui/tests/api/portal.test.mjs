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
import { requestsFrom, SAMPLES, servePortal, startApi, startIssuer, USERS } from "./standin.mjs";

const app = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const out = join(app, "test-output", "api");
mkdirSync(out, { recursive: true });

let portal;
const issuer = await startIssuer({ redirectUris: () => [portal.page] });
const api = await startApi({ issuer, portalOrigin: () => portal.origin });
const CONFIG = { apiUrl: api.url, issuer: issuer.url, clientId: "cmapi-portal", audience: "cmapi-nonprod", instance: "nonprod", displayName: "Non-production", environments: ["rnd", "dev"], otherInstances: [] };
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
  Object.assign(api.state, { mode, items, delayMs: 0, seen: [] });
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
    // Open at current step needs the Workflow tab. It is off, and it says why in text that a screen reader links to it.
    const openButton = page.getByRole("button", { name: "Open at current step" });
    assert.equal(await openButton.getAttribute("aria-disabled"), "true");
    assert.match(await page.locator(`#${await openButton.getAttribute("aria-describedby")}`).innerText(), /Workflow tab is not on the API yet/);
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
    const ADDED = ["Open at current step is off: the Workflow tab is not on the API yet."];
    const known = [...fromMockup, ...data, ...LIBRARY, ...ADDED].sort((x, y) => y.length - x.length);
    const invented = shown.filter((text) => known.reduce((rest, k) => rest.split(k).join(""), text).trim() !== "");
    assert.deepEqual(invented, [], "no string that the mockup does not have");
    assert.deepEqual(errors, []);
    await context.close();
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
