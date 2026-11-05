#!/usr/bin/env node
// Proves the page against the mockup (mockups/portal/dist/portal.html): every string the mockup shows is on the page,
// at every view and after every step of the same walk. Then axe and layout checks on each tab.
// PatternFly replaces the look, so screenshots go to test-output/ for people to read and are never diffed.
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { AxeBuilder } from "@axe-core/playwright";
import { chromium } from "playwright";
import { distPage, serve, TABS } from "../../tests/portal/views.mjs";

const app = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(app, "test-output");
mkdirSync(out, { recursive: true });

const server = await serve(join(app, "dist"));
// PW_CHANNEL=chrome runs in the installed Chrome, and PW_HEADED=1 shows the window.
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL, headless: !process.env.PW_HEADED });
const open = async (url, ready) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/ERR_FAILED|ERR_INTERNET|net::/.test(m.text())) errors.push(`${m.text()} (${m.location().url})`); });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await page.waitForSelector(ready);
  return { page, errors };
};
const mock = await open(pathToFileURL(distPage).href, "nav.tabs");
const real = await open(`http://127.0.0.1:${server.port}/index.html`, "[role=tablist]");

const settle = (page) => page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 20)));
const squeeze = (text) => text.replace(/\s+/g, "");
const mockStrings = (page) => page.evaluate(() => {
  const walker = document.createTreeWalker(document.querySelector("#dc-root"), NodeFilter.SHOW_TEXT);
  const found = new Set();
  // aria-hidden marks decoration (the brand mark and the avatar's letter), not content.
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.nodeValue.trim() && !node.parentElement.closest("[aria-hidden=true]")) found.add(node.nodeValue.trim());
  }
  document.querySelectorAll("#dc-root input, #dc-root textarea").forEach((el) => { if (el.value) found.add(el.value); });
  return [...found];
});
const pageText = (page) => page.evaluate(() => {
  const root = document.getElementById("root");
  const values = [...root.querySelectorAll("input, textarea")].map((el) => el.value);
  return root.textContent + values.join(" ");
});

// Words PatternFly itself adds for screen readers, and the names blank table headings carry for them.
const LIBRARY_TEXT = /^((Info|Success|Warning|Danger|Custom) alert:|Action|Used of hard)$/;

const results = [];
async function compare(name) {
  await settle(mock.page);
  await settle(real.page);
  const text = squeeze(await pageText(real.page));
  const strings = await mockStrings(mock.page);
  const missing = strings.filter((s) => !text.includes(squeeze(s)));
  // The reverse: anything the page says that the mockup does not is invented, unless it is PatternFly's own.
  const mockText = squeeze(await mock.page.evaluate(() => {
    const root = document.querySelector("#dc-root");
    return root.textContent + [...root.querySelectorAll("input, textarea")].map((el) => el.value).join(" ");
  }));
  const added = (await real.page.evaluate(() => {
    const walker = document.createTreeWalker(document.getElementById("root"), NodeFilter.SHOW_TEXT);
    const found = new Set();
    while (walker.nextNode()) if (walker.currentNode.nodeValue.trim()) found.add(walker.currentNode.nodeValue.trim());
    return [...found];
  })).filter((s) => !mockText.includes(squeeze(s)) && !LIBRARY_TEXT.test(s));
  results.push({ name, strings: strings.length, missing, added });
}

const both = async (action) => {
  await action(mock.page, "mock");
  await action(real.page, "real");
};
const press = (name) => both((page) => page.getByRole("button", { name }).first().click());

const tab = (label) => both((page, which) => (which === "mock"
  ? page.locator("nav.tabs").getByRole("button", { name: new RegExp(`^${label}`) }).click()
  : page.getByRole("tab", { name: new RegExp(`^${label}`) }).click()));
const instance = (name) => both((page, which) => (which === "mock"
  ? page.locator(".instbar").getByRole("button", { name: new RegExp(`^${name}`) }).click()
  : page.getByRole("group", { name: "Instance" }).getByRole("button", { name: new RegExp(`^${name}`) }).click()));
const typeInto = (selector, text) => both(async (page) => {
  await page.locator(selector).first().click();
  await page.keyboard.type(text);
});

for (const name of ["nonprod", "staging", "prod"]) {
  await instance(name);
  for (const label of Object.values(TABS)) {
    await tab(label);
    await compare(`${name} ${label}`);
  }
}

await instance("nonprod");
await tab("Workflow");
const scenarios = await mock.page.locator(".scenarios .scn b").allInnerTexts();
for (const scenario of scenarios) {
  await press(new RegExp(`^${scenario.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
  await compare(`workflow ${scenario} start`);
  let step = 1;
  while (await mock.page.locator(".controls .btn.primary").isEnabled()) {
    await press("Next step");
    await compare(`workflow ${scenario} step ${++step}`);
    assert.equal(await real.page.getByRole("button", { name: "Next step" }).isEnabled() || !(await mock.page.locator(".controls .btn.primary").isEnabled()), true, "Next step enabled state");
  }
}

await tab("Quotas");
await press(/^Next/);
await compare("quotas next");
await press(/^Next/);
await press(/Previous/);
await compare("quotas previous");
await typeInto("#q-search", "pay");
await compare("quotas type-ahead");
await press("Show all matches");
await compare("quotas all matches");
await press(/^matching/);
await both((page) => page.locator("table tbody tr button").nth(1).click());
await compare("quotas row");
await both((page) => page.getByRole("group", { name: "New size" }).getByRole("button").last().click());
await compare("quotas custom size");
await press("Plan change");
await compare("quotas planned");
await press("Submit change");
await compare("quotas submitted");
await press("Export CSV");
await compare("quotas export");

await tab("New namespace");
await both(async (page) => { await page.locator("#ns-team").fill("risk"); });
await compare("new team");
assert.equal(await real.page.locator("#ns-name").inputValue(), "risk-rnd", "the name follows the team");
await both((page) => page.getByRole("group", { name: "Tier" }).getByRole("button").last().click());
await compare("new tier");
await press("Dry run");
await compare("new dry run");
await press("Submit request");
await compare("new submitted");

await tab("Approvals");
await press(/^Approve$/);
await compare("approvals approved");
await press(/^Reject$/);
await compare("approvals rejecting");
await both((page) => page.locator("textarea").first().fill("no room"));
await press("Confirm reject");
await compare("approvals rejected");

await tab("Expiration");
await both((page) => page.getByRole("group", { name: "Action" }).getByRole("button").nth(1).click());
await press(/^Extend/);
await compare("expiration submitted");

// Each failure here is one string the mockup shows that the page does not.
const failing = results.filter((r) => r.missing.length);
const unique = [...new Set(failing.flatMap((r) => r.missing))];
writeFileSync(join(out, "parity.json"), JSON.stringify(results, null, 1));
console.log(`content parity: ${results.length} states, ${results.reduce((n, r) => n + r.strings, 0)} strings compared, ${failing.length} states with a missing string`);
for (const s of unique.slice(0, 40)) console.log(`  missing: ${s.slice(0, 140)}`);
const invented = [...new Set(results.flatMap((r) => r.added))];
console.log(`added by the page: ${invented.length}`);
for (const s of invented.slice(0, 40)) console.log(`  added: ${s.slice(0, 140)}`);

const page = real.page;
const findings = [];
const tabs = Object.values(TABS);
for (const width of [1440, 820, 390]) {
  await page.setViewportSize({ width, height: 1000 });
  for (const label of tabs) {
    const target = page.getByRole("tab", { name: new RegExp(`^${label}`) });
    await target.click();
    await settle(page);
    const layout = await page.evaluate(() => {
      const main = document.querySelector("main")?.parentElement ?? document.documentElement;
      const doc = document.documentElement;
      return { doc: doc.scrollWidth - doc.clientWidth, main: main.scrollWidth - main.clientWidth, leftover: /\{\{|undefined|NaN/.test(document.getElementById("root").textContent) };
    });
    if (layout.doc > 0 || layout.main > 0) findings.push(`${label} at ${width}: scrolls sideways by ${Math.max(layout.doc, layout.main)}px`);
    if (layout.leftover) findings.push(`${label} at ${width}: a leftover placeholder`);
    await page.screenshot({ path: join(out, `${label.replace(/\s+/g, "-").toLowerCase()}-${width}.png`) });
    if (width !== 820) {
      const scan = await new AxeBuilder({ page }).analyze();
      for (const v of scan.violations) {
        if (v.impact === "serious" || v.impact === "critical") findings.push(`${label} at ${width}: axe ${v.impact} ${v.id} (${v.nodes.length}): ${v.nodes[0].target}`);
      }
    }
  }
}
console.log(findings.length ? `findings:\n  ${[...new Set(findings)].join("\n  ")}` : "ok - layout at 1440, 820, 390 and axe on every tab");

await browser.close();
server.close();
const errors = [...new Set(real.errors)];
if (errors.length) console.log(`console errors:\n  ${errors.slice(0, 15).map((e) => e.slice(0, 220)).join("\n  ")}`);
assert.deepEqual(unique, [], "every string the mockup shows is on the page");
assert.deepEqual(invented, [], "the page says nothing the mockup does not");
assert.deepEqual(findings, [], "layout and accessibility");
assert.deepEqual(errors, [], "console errors");
console.log("ok - parity, layout, accessibility, console");
