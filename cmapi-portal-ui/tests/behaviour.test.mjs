#!/usr/bin/env node
// Behaviour the text comparison in parity.test.mjs cannot see. Runs against the built app.
import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { AxeBuilder } from "@axe-core/playwright";
import { chromium } from "playwright";
import { serve } from "../../tests/portal/views.mjs";

const app = join(dirname(fileURLToPath(import.meta.url)), "..");
const server = await serve(join(app, "dist-demo"));
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
page.setDefaultTimeout(5000);
const open = async (hash) => {
  await page.goto(`http://127.0.0.1:${server.port}/index.html${hash}`);
  await page.reload();
  await page.waitForSelector("[role=tablist]");
};
const hash = () => page.evaluate(() => location.hash);
const wait = (ms = 40) => page.waitForTimeout(ms);

try {
  // The mockup's forms validate natively, and the contract says the date limits stay native.
  await open("#nonprod/new");
  await page.locator("#ns-exp").fill("2026-11-01");
  await page.getByRole("button", { name: "Submit request" }).click();
  await wait();
  assert.equal(await hash(), "#nonprod/new", "a date below min does not submit");
  await open("#nonprod/new");
  await page.locator("#ns-dl").fill("not an email");
  await page.getByRole("button", { name: "Submit request" }).click();
  await wait();
  assert.equal(await hash(), "#nonprod/new", "a Team DL that is no email address does not submit");
  await open("#nonprod/new");
  await page.getByRole("button", { name: "Submit request" }).click();
  await wait();
  assert.equal(await hash(), "#nonprod/workflow", "a valid form still submits");

  await open("#nonprod/expiration");
  await page.getByRole("group", { name: "State", exact: true }).getByRole("button", { name: /^Permanent/ }).click();
  await page.locator("table tbody tr button").nth(1).click();
  await page.locator("#exp-until").fill("2026-11-01");
  await page.getByRole("button", { name: "Set expiry" }).click();
  await wait();
  assert.equal(await page.getByText("Not submitted").count(), 0, "a date below min does not reach the expiration handler");
  await open("#nonprod/quotas");
  await page.getByRole("group", { name: "New size", exact: true }).getByRole("button", { name: /^custom/ }).click();
  await page.locator("#q-cpu").fill("0.5");
  await page.getByRole("button", { name: "Submit change" }).click();
  await wait();
  assert.equal(await page.getByText(/202 Accepted/).count(), 0, "a cpu off the step does not submit");

  // The KPI footnote says "The black tick on each bar is the threshold", so each bar has one, in the right place.
  await open("#nonprod/kpis");
  assert.match(await page.locator("main").innerText(), /The black tick on each bar is the threshold/);
  const ticks = await page.evaluate(() => [...document.querySelectorAll(".cp-meter")].map((meter) => {
    const bar = meter.querySelector("[role=progressbar]").getBoundingClientRect();
    const tick = meter.querySelector(".cp-mark").getBoundingClientRect();
    return { at: (tick.left - bar.left) / bar.width, want: parseFloat(meter.querySelector(".cp-mark").style.insetInlineStart) / 100, top: tick.top - bar.top, bottom: tick.bottom - bar.bottom, seen: tick.width > 0 && tick.height > 0 };
  }));
  assert.equal(ticks.length, 14, "every meter on the page that has a threshold shows it");
  for (const t of ticks) {
    assert.ok(t.seen, "the tick has a size");
    assert.ok(Math.abs(t.at - t.want) < 0.01, `tick at ${t.at}, threshold ${t.want}`);
    assert.ok(Math.abs(t.top) <= 1 && Math.abs(t.bottom) <= 1, `the tick lies on the bar (${t.top}, ${t.bottom})`);
  }

  // PatternFly marks the visible measure aria-hidden, so the value has to reach assistive technology another way.
  const texts = await page.evaluate(() => [...document.querySelectorAll("[role=progressbar]")].map((e) => e.getAttribute("aria-valuetext")));
  assert.ok(texts.every(Boolean), "every KPI meter has aria-valuetext");
  await open("#nonprod/quotas");
  const quota = await page.locator("table tbody tr").first().locator("[role=progressbar]").first().getAttribute("aria-valuetext");
  assert.match(quota, /\/ \d+ cores$/, "a quota meter says its figures");

  // The type-ahead while open: axe never sees this state in parity.test.mjs.
  await page.locator("#q-search").click();
  await page.keyboard.type("pay");
  await page.keyboard.press("ArrowDown");
  await wait();
  const option = await page.evaluate(() => {
    const input = document.querySelector("#q-search");
    const active = document.getElementById(input.getAttribute("aria-activedescendant"));
    const popup = document.getElementById(input.getAttribute("aria-controls"));
    return { role: active.getAttribute("role"), selected: active.getAttribute("aria-selected"), popup: popup.getAttribute("role"), inside: popup.contains(active) };
  });
  assert.deepEqual(option, { role: "option", selected: "true", popup: "listbox", inside: true }, "the combobox points at its listbox and the active option says so");
  const open1 = await new AxeBuilder({ page }).include(".cp-combo").analyze();
  assert.deepEqual(open1.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id), [], "axe on the open type-ahead");

  // Workflow: which lane is acting, and what has not happened yet.
  await open("#nonprod/workflow");
  await page.getByRole("button", { name: "Next step" }).click();
  await wait();
  const lanes = await page.evaluate(() => [...document.querySelectorAll('[aria-label="Systems involved"] .pf-v6-c-card')].map((c) => ({ current: c.getAttribute("aria-current"), outline: getComputedStyle(c).outlineStyle })));
  assert.ok(lanes.some((l) => l.current === "step" && l.outline === "solid"), "the acting lane stands out");
  assert.ok(lanes.some((l) => l.current === null && l.outline === "none"), "the others do not");

  const steps = page.locator(".pf-v6-c-progress-stepper__step");
  let current = -1;
  for (let n = 0; n < 8 && current < 0; n++) {
    await open("#nonprod/requests");
    await page.getByRole("button", { name: "Open at current step" }).nth(n).click();
    await wait();
    const at = await steps.evaluateAll((all) => all.findIndex((s) => s.classList.contains("pf-m-current")));
    if (at >= 1 && at + 2 < await steps.count()) current = at;
  }
  assert.ok(current >= 1, "a request with steps before and after its position");
  await page.getByRole("button", { name: "Next step" }).click();
  await page.getByRole("button", { name: "Next step" }).click();
  await wait();
  assert.match(await steps.nth(current + 1).getAttribute("class"), /pf-m-pending/, "a step after the request's position is not shown as done");
  assert.match(await steps.nth(current - 1).getAttribute("class"), /pf-m-success/, "one before it is");

  // A pending check is neutral in the mockup (.mark has no status colour), not info.
  await open("#nonprod/workflow");
  const next = page.getByRole("button", { name: "Next step" });
  const pending = [];
  for (let i = 0; i < 20; i++) {
    pending.push(...await page.evaluate(() => [...document.querySelectorAll(".pf-v6-c-icon__content")].filter((el) => el.textContent === "•").map((el) => el.className)));
    if (await next.isDisabled()) break;
    await next.click();
    await wait(10);
  }
  assert.ok(pending.length > 0, "the walk meets a pending check");
  assert.ok(pending.every((c) => !/pf-m-info/.test(c)), "no pending mark uses the info colour");

  // No step number with a stop the mockup does not have.
  assert.equal(await page.getByRole("button", { name: /^\d+\. / }).count(), 0, "step labels carry only the mockup's text");

  // A bad hash on the view already showing still resolves to the real hash.
  await open("#nonprod/workflow");
  await page.evaluate(() => { location.hash = "#bogus/nonsense"; });
  await wait();
  assert.equal(await hash(), "#nonprod/workflow", "the hash shows the view on screen");
  // A changed hash reopens the portal, so a field the logic does not hold starts over, as a remount does on the standalone page.
  await open("#nonprod/new");
  const startText = await page.locator("#ns-why").inputValue();
  await page.locator("#ns-why").fill("typed why");
  await page.evaluate(() => { location.hash = "#staging/new"; });
  await wait();
  assert.equal(await page.locator("#ns-why").inputValue(), startText, "a hash edit resets Justification");

  console.log("ok - behaviour");
} finally {
  await browser.close();
  server.close();
}
