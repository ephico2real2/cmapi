// Inserted (by hand, never committed) before the AxeBuilder scan of check 7 Quotas and KPIs, for quotas 390 light, with
// time7.py applied. Output on 2026-11-21, Chromium 156.0.8078.4, load average about 10:
//   FRAMES 1 · INJECT 103 · RUNPARTIAL 3193 (partial result 3980566 characters) · NEWPAGE 88 · INJECT-BLANK 260
//   FINISH 4627 · CLOSE-BLANK 5 · LEGACY 2191 · DEFAULT 5278   (ms)
//   axe.run(document) in the page, after a per-rule run of every rule: 736 ms for 1938 elements
const { createRequire } = await import("node:module");
const src = createRequire(import.meta.url)("axe-core").source;
console.log("FRAMES", page.frames().length);
let a = Date.now(); await page.evaluate(src); console.log("INJECT", Date.now() - a);
a = Date.now(); const partial = await page.evaluate(() => window.axe.runPartial(document, {})); console.log("RUNPARTIAL", Date.now() - a, JSON.stringify(partial).length);
a = Date.now(); const blank = await page.context().newPage(); console.log("NEWPAGE", Date.now() - a);
a = Date.now(); await blank.evaluate(src); console.log("INJECT-BLANK", Date.now() - a);
a = Date.now(); await blank.evaluate((p) => window.axe.finishRun([p], {}), partial); console.log("FINISH", Date.now() - a);
a = Date.now(); await blank.close(); console.log("CLOSE-BLANK", Date.now() - a);
a = Date.now(); await new AxeBuilder({ page }).setLegacyMode(true).analyze(); console.log("LEGACY", Date.now() - a);
a = Date.now(); await new AxeBuilder({ page }).analyze(); console.log("DEFAULT", Date.now() - a);
