// Is <input type=url> ever stricter than cmapi's url format? Each value: Chromium's typeMismatch, and the validator's
// verdict (from url_verdicts.json, written by url_verdicts.py). Run: node browser_url.mjs <node_modules with playwright>
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(process.argv[2] + "/");
const { chromium } = require("playwright");
const verdicts = JSON.parse(readFileSync(new URL("url_verdicts.json", import.meta.url), "utf8"));
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent("<form><input id=u type=url></form>");
let stricter = 0;
for (const [value, server] of Object.entries(verdicts)) {
  const r = await page.evaluate((v) => { const u = document.getElementById("u"); u.value = v; return { value: u.value, typeMismatch: u.validity.typeMismatch }; }, value);
  const flag = r.typeMismatch && server ? "BROWSER STRICTER" : "";
  if (flag) stricter++;
  console.log(JSON.stringify(value).padEnd(32), "server", server ? "accepts" : "refuses", "| type=url", r.typeMismatch ? "refuses" : "accepts", r.value !== value ? `(value ${JSON.stringify(r.value)})` : "", flag);
}
console.log(`values where type=url refuses what cmapi accepts: ${stricter}`);
await browser.close();
