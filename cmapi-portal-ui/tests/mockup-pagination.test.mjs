// The mockup's Policies pager (#537, review of PR #540): each disclosure controls its region, and focus stays on the same
// page across ellipsis windows. Run by npm test.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { chromium } from "playwright";

const source = readFileSync(new URL("../../mockups/portal/Main.dc.html", import.meta.url), "utf8");
const runtime = readFileSync(new URL("../../mockups/portal/runtime/dc-lite.js", import.meta.url), "utf8");
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setContent('<div id="dc-root"></div>');
  await page.addScriptTag({ content: runtime });
  await page.evaluate((source) => {
    const def = DcLite.parse(source);
    // Exercise the real template/logic/runtime with enough policies to change the ellipsis window.
    def.js += '\nPOLICY_DEFS = Array.from({ length: 250 }, function (_, i) { return { name: "review-policy-" + i, kind: "ValidatingPolicy", what: "Review fixture" }; }); RENDERED_CHECKS = [];';
    DcLite.mount(def, document.getElementById("dc-root"), { instance: "nonprod", startTab: "policies" });
  }, source);
  const toggles = page.locator("main button.disclose");
  for (let i = 0; i < 4; i++) {
    const toggle = toggles.nth(i);
    const id = await toggle.getAttribute("aria-controls");
    assert.ok(id, "each mockup toggle has aria-controls");
    const target = page.locator(`[id=${JSON.stringify(id)}]`);
    assert.equal(await target.count(), 1);
    for (const key of ["Enter", "Space"]) {
      await toggle.focus();
      await page.keyboard.press(key);
      assert.equal(await target.isVisible(), await toggle.getAttribute("aria-expanded") === "true");
    }
  }
  await toggles.last().click();
  const nav = page.getByRole("navigation", { name: "Results by policy pages" });
  for (const n of [5, 6, 7, 10, 6, 5, 4, 1]) {
    const button = nav.getByRole("button", { name: `Page ${n}`, exact: true });
    await button.focus();
    await page.keyboard.press("Enter");
    await nav.locator(`[aria-current="page"][aria-label="Page ${n}"]`).waitFor();
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("aria-label")), `Page ${n}`, "ellipsis changes keep focus on the activated page");
  }
  assert.deepEqual(errors, []);
  console.log("ok - 540 mockup disclosure relationships and focus across ellipsis windows");
} finally {
  await browser.close();
}
