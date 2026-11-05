#!/usr/bin/env node
// Scripted walks through the portal with zero console errors allowed:
//   node interactions.test.mjs                        walks dist/portal.html and runs the standalone-only checks
//   node interactions.test.mjs --record out.json [--source-dir dir]    also writes the DOM and focus after each step
//   node interactions.test.mjs --compare ref.json     fails where a step differs from a recorded run
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";
import { TABS, canonicalDom, distPage, gotoView, serve } from "./views.mjs";

const flag = (name) => { const i = process.argv.indexOf(name); return i < 0 ? null : process.argv[i + 1]; };
const sourceDir = flag("--source-dir");
const server = sourceDir ? await serve(sourceDir, { favicon: true }) : null;
const url = server ? `http://127.0.0.1:${server.port}/Main.dc.html` : pathToFileURL(distPage).href;

// PW_CHANNEL=chrome runs in the installed Chrome, and PW_HEADED=1 shows the window.
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL, headless: !process.env.PW_HEADED });
const context = await browser.newContext({ viewport: { width: 1320, height: 1720 }, deviceScaleFactor: 1 });
const page = await context.newPage();
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(e.message));

const transcript = [];
const settle = () => page.evaluate(() => new Promise((resolve) => setTimeout(resolve)));

// Records one step: its DOM, plus which field holds focus and where its caret is.
async function step(name, action) {
  if (action) await action();
  await settle();
  const focus = await page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    let caret = null;
    try { caret = el.selectionStart; } catch { /* date inputs have no caret */ }
    return { tag: el.localName, id: el.id, caret };
  });
  transcript.push({ name, focus, dom: await page.evaluate(canonicalDom) });
}

const button = (scope, name) => page.locator(scope).getByRole("button", { name, exact: false });
const text = (selector) => page.locator(selector).first().innerText();

async function reload() {
  await page.goto(url);
  await page.waitForSelector("nav.tabs");
}

async function walkWorkflows() {
  for (const instance of ["nonprod", "staging", "prod"]) {
    await reload();
    await gotoView(page, { instance, tab: "workflow" });
    const scenarios = await page.locator(".scenarios .scn").count();
    assert.ok(scenarios > 0, instance);
    for (let s = 0; s < scenarios; s++) {
      const scenario = page.locator(".scenarios .scn").nth(s);
      const label = await scenario.locator("b").innerText();
      await step(`${instance}: open ${label}`, () => scenario.click());
      const next = page.locator(".controls .btn.primary");
      let count = 1;
      while (await next.isEnabled()) {
        await step(`${instance}: ${label} step ${++count}`, () => next.click());
      }
      if (label === "AI agent onboards · rnd") {
        assert.equal(count, 13, "the agent scenario has 13 steps");
        assert.match(await text("main"), /403/);
      }
      await step(`${instance}: ${label} back`, () => button(".controls", "Back").click());
      await step(`${instance}: ${label} reset`, () => button(".controls", "Reset").click());
      assert.ok(await page.locator(".controls .btn").nth(1).isDisabled(), "Back is disabled after Reset");
    }
  }
}

async function walkQuotas() {
  await reload();
  await gotoView(page, { instance: "nonprod", tab: "quotas" });
  const firstRow = () => page.locator("table.res tbody tr td").first().innerText();
  const next = page.locator(".pager .rowbtn", { hasText: "Next" }).first();
  const prev = page.locator(".pager .rowbtn", { hasText: "Previous" }).first();

  const opening = await firstRow();
  let forward = 0;
  while ((await next.getAttribute("aria-disabled")) !== "true") {
    await step(`quotas: next page ${++forward}`, () => next.click());
  }
  assert.ok(forward > 1, "there is more than one page");
  for (let i = forward; i > 0; i--) await step(`quotas: previous page ${i}`, () => prev.click());
  assert.equal(await firstRow(), opening, "paging back returns to the first page");

  const letter = page.locator(".az .azb:not([aria-disabled='true'])").nth(3);
  const wanted = (await letter.innerText()).toLowerCase();
  await step("quotas: letter jump", () => letter.click());
  assert.equal((await firstRow())[0].toLowerCase(), wanted);

  const search = page.locator("#q-search");
  await step("quotas: focus search", () => search.click());
  for (const [i, key] of [..."pay"].entries()) {
    await step(`quotas: type ${key}`, () => page.keyboard.type(key));
    const state = await search.evaluate((el) => ({ focused: document.activeElement === el, caret: el.selectionStart, value: el.value }));
    assert.deepEqual(state, { focused: true, caret: i + 1, value: "pay".slice(0, i + 1) }, "type-ahead keeps focus and caret");
  }
  assert.ok(await page.locator("#q-sug li").count() > 0, "suggestions appear");
  await step("quotas: arrow down", () => page.keyboard.press("ArrowDown"));
  await step("quotas: show all matches", () => button(".searchrow", "Show all matches").click());
  await step("quotas: clear matches", () => page.locator(".searchrow .chip.on").click());

  for (const group of ["Env", "Cluster", "Tier", "Sort", "Per page"]) {
    const chips = page.locator(".fgroup", { hasText: group }).first().locator(".chip");
    await step(`quotas: filter ${group}`, () => chips.nth(1).click());
    await step(`quotas: filter ${group} back`, () => chips.first().click());
  }
  await step("quotas: attention filter", () => page.locator(".attn .chip").nth(1).click());
  await step("quotas: attention all", () => page.locator(".attn .chip").first().click());
  await step("quotas: export", () => button(".searchrow", "Export CSV").click());
  await step("quotas: close export", () => page.locator(".qtools .actions .rowbtn").click());

  await step("quotas: pick a row", () => page.locator("table.res tbody tr button").nth(1).click());
  const sizes = page.getByRole("group", { name: "New size" }).locator(".segbtn");
  await step("quotas: custom size", () => sizes.last().click());
  const cpu = page.locator("#q-cpu");
  await step("quotas: focus cpu", () => cpu.click());
  await step("quotas: type cpu", async () => { await cpu.fill(""); await page.keyboard.type("24"); });
  assert.equal(await cpu.inputValue(), "24");
  assert.ok(await cpu.evaluate((el) => document.activeElement === el), "the cpu field keeps focus");
  await step("quotas: plan", () => button("form.card", "Plan change").click());
  await step("quotas: submit", () => button("form.card", "Submit change").click());
}

async function walkNewNamespace() {
  await reload();
  await gotoView(page, { instance: "nonprod", tab: "new" });
  const team = page.locator("#ns-team");
  await step("new: clear team", async () => { await team.click(); await team.press("ControlOrMeta+a"); await page.keyboard.press("Delete"); });
  for (const key of "risk") await step(`new: type ${key}`, () => page.keyboard.type(key));
  assert.equal(await team.inputValue(), "risk");
  assert.equal(await page.locator("#ns-name").inputValue(), "risk-rnd", "the name follows the team");
  assert.equal(await team.evaluate((el) => el.selectionStart), 4, "the caret stays at the end");

  // Type in the middle: only a kept caret leaves the letter where it was typed.
  await step("new: caret to middle", () => team.evaluate((el) => el.setSelectionRange(2, 2)));
  await step("new: type in the middle", () => page.keyboard.type("x"));
  assert.equal(await team.inputValue(), "rixsk");
  assert.equal(await team.evaluate((el) => el.selectionStart), 3);

  const tiers = page.getByRole("group", { name: /tier/i }).locator(".segbtn");
  for (let i = 0; i < await tiers.count(); i++) await step(`new: tier ${i}`, () => tiers.nth(i).click());
  await step("new: region", () => page.locator("#ns-region").selectOption("any"));
  assert.equal(await page.locator("#ns-region").inputValue(), "any");
  await step("new: back to a small tier", () => tiers.first().click());
  await step("new: environment dev", () => page.getByRole("group", { name: "Environment" }).locator(".segbtn").last().click());
  await step("new: submit", () => page.locator("form.card button[type=submit]").first().click());
  assert.match(await page.locator("nav.tabs .tab.on").innerText(), /Workflow/, "submitting opens the workflow");
}

async function walkApprovals() {
  await reload();
  await gotoView(page, { instance: "nonprod", tab: "approvals" });
  // Only some requests are this user's to decide, and deciding one removes its buttons.
  const actionable = page.locator(".apprgrid").filter({ has: page.locator(".actions .btn.primary") });
  assert.ok(await actionable.count() >= 1, "a request is waiting for this user");
  await step("approvals: approve", () => actionable.first().locator(".actions .btn.primary").click());
  assert.match(await text("main"), /Approved/);

  await reload();
  await gotoView(page, { instance: "nonprod", tab: "approvals" });
  const item = page.locator(".apprgrid").filter({ has: page.locator(".actions .btn.primary") }).first();
  await step("approvals: start reject", () => item.locator(".actions .btn", { hasText: "Reject" }).click());
  const reason = item.locator("textarea");
  await step("approvals: confirm with no reason is refused", () => item.locator(".actions .btn", { hasText: "Confirm reject" }).click());
  assert.ok(await reason.isVisible(), "a reason is required");
  await step("approvals: focus reason", () => reason.click());
  for (const key of "no") await step(`approvals: reason ${key}`, () => page.keyboard.type(key));
  assert.equal(await reason.inputValue(), "no");
  assert.ok(await reason.evaluate((el) => document.activeElement === el && el.selectionStart === 2), "the reason keeps focus and caret");
  await step("approvals: confirm reject", () => item.locator(".actions .btn", { hasText: "Confirm reject" }).click());
  assert.match(await text("main"), /Rejected/);
}

async function walkExpiration() {
  await reload();
  await gotoView(page, { instance: "nonprod", tab: "expiration" });
  const actions = page.getByRole("group", { name: "Action" }).locator(".segbtn");
  await step("expiration: extend 14", () => actions.nth(1).click());
  await step("expiration: submit extend", () => page.locator("form.card button[type=submit]").click());
  await step("expiration: another row", () => page.locator("table.res tbody tr button").nth(2).click());
  await step("expiration: make permanent", () => actions.filter({ hasText: /permanent/i }).click());
  await step("expiration: submit permanent", () => page.locator("form.card button[type=submit]").click());
  assert.match(await text("form.card"), /platform-leads/);

  const find = page.locator(".combo input[type=search]");
  await step("expiration: focus search", () => find.click());
  for (const key of "pay") await step(`expiration: search ${key}`, () => page.keyboard.type(key));
  assert.ok(await find.evaluate((el) => document.activeElement === el && el.selectionStart === 3), "search keeps focus and caret");

  await reload();
  await gotoView(page, { instance: "prod", tab: "expiration" });
  await step("expiration: prod never expires");
  assert.match(await text("main"), /Production namespaces never expire/);
}

// Only the standalone page has these: the hash, the bar, and running without a network.
async function standaloneOnly() {
  await page.goto(`${url}#staging/quotas`);
  await page.waitForSelector("nav.tabs");
  await settle();
  assert.match(await page.locator("nav.tabs .tab.on").innerText(), /Quotas/, "the hash chooses the tab");
  assert.match(await page.locator(".instbadge").innerText(), /staging/, "the hash chooses the instance");
  assert.equal(await page.locator(".dcl-bar button[aria-pressed=true]").innerText(), "staging");

  await page.locator("nav.tabs").getByRole("button", { name: "Capacity" }).click();
  await settle();
  assert.match(new URL(page.url()).hash, /^#staging\/capacity$/, "a tab click updates the hash");
  await page.locator(".instbar").getByRole("button", { name: /^prod/ }).click();
  await settle();
  assert.equal(new URL(page.url()).hash, "#prod/capacity", "the portal's own switch updates the hash");
  await page.locator(".dcl-bar").getByRole("button", { name: "nonprod" }).click();
  await page.waitForFunction(() => document.querySelector(".instbadge").innerText.includes("nonprod"));
  assert.match(await page.locator("nav.tabs .tab.on").innerText(), /Capacity/, "the bar keeps the tab");
  assert.equal(await page.locator("#dc-root .sc-host").count(), 1, "switching does not leave a second portal mounted");

  await gotoView(page, { instance: "nonprod", tab: "workflow" });
  const counter = () => page.locator(".counter").innerText();
  const before = await counter();
  await button(".controls", "Play").click();
  await page.waitForFunction((was) => document.querySelector(".counter").innerText !== was, before, { timeout: 4000 });
  await page.locator(".controls .btn").nth(3).click();

  await page.goto(`${url}#bogus/nonsense`);
  await page.waitForSelector("nav.tabs");
  assert.match(await page.locator("nav.tabs .tab.on").innerText(), /Workflow/, "a bad hash falls back to the defaults");

  // Below 1320 px the page's own CSS reflows, and nothing may scroll sideways.
  const overflow = [];
  for (const width of [1100, 820, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const tab of Object.keys(TABS)) {
      await gotoView(page, { instance: "nonprod", tab });
      const extra = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (extra > 0) overflow.push(`${tab} at ${width}: ${extra}px`);
    }
  }
  await page.setViewportSize({ width: 1320, height: 1720 });
  assert.deepEqual(overflow, [], "no view scrolls sideways");

  // Fails to load fonts, so the expected errors are scoped to this page, not the walks above.
  const offline = await context.newPage();
  await offline.route(/fonts\.(googleapis|gstatic)\.com/, (route) => route.abort());
  const pageErrors = [];
  offline.on("pageerror", (e) => pageErrors.push(e.message));
  await offline.goto(url);
  await offline.waitForSelector("nav.tabs");
  assert.deepEqual(pageErrors, [], "the page runs with no network");
  await offline.close();
}

for (const [name, walk] of [["workflow", walkWorkflows], ["quotas", walkQuotas], ["new namespace", walkNewNamespace], ["approvals", walkApprovals], ["expiration", walkExpiration]]) {
  await walk();
  console.log(`ok - ${name} (${transcript.length} steps so far)`);
}
if (!sourceDir) {
  await standaloneOnly();
  console.log("ok - hash, bar, play, reflow, offline");
}
await browser.close();
if (server) server.close();

assert.deepEqual([...new Set(errors)], [], "console errors");
console.log("ok - no console errors");

if (flag("--record")) writeFileSync(flag("--record"), JSON.stringify(transcript));
if (flag("--compare")) {
  const reference = JSON.parse(readFileSync(flag("--compare"), "utf8"));
  assert.equal(transcript.length, reference.length, "the same number of steps");
  const differing = transcript.filter((s, i) => s.dom !== reference[i].dom || JSON.stringify(s.focus) !== JSON.stringify(reference[i].focus)).map((s) => s.name);
  assert.deepEqual(differing, [], "steps that differ from the reference");
  console.log(`ok - all ${transcript.length} steps match the reference, DOM and focus`);
}
