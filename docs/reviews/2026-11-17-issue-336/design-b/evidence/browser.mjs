// What Chromium does with the schema's patterns in an <input pattern> (HTML compiles it with the v flag), and what an
// <input type=email> sends. Run: node browser.mjs <path to a node_modules that has playwright>
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(process.argv[2] + "/");
const { chromium } = require("playwright");
const ref = JSON.parse(readFileSync(new URL("response-reference.json", import.meta.url), "utf8"));
const co = JSON.parse(readFileSync(new URL("response-company.json", import.meta.url), "utf8"));
const browser = await chromium.launch();
const page = await browser.newPage();
const messages = [];
page.on("console", (m) => messages.push(m.text()));
await page.setContent("<form><input id=f></form>");
console.log("browser", browser.version());
const probe = async (pattern, value) => page.evaluate(([p, v]) => {
  const f = document.getElementById("f");
  f.setAttribute("pattern", p);
  f.value = v;
  return { patternMismatch: f.validity.patternMismatch, valid: f.checkValidity() };
}, [pattern, value]);
const rows = [
  ["reference cmapi.net/team", ref.labels.properties["cmapi.net/team"].pattern, "NOT A TEAM!"],
  ["reference cmapi.net/team-dl", ref.annotations.properties["cmapi.net/team-dl"].pattern, "x@other.com"],
  ["company company.net/mnemonic", co.labels.properties["company.net/mnemonic"].pattern, "toolong"],
  ["company mnemonic-confluence", co.annotations.properties["company.net/mnemonic-confluence"].pattern, "ftp://x"],
  ["company label value (allOf)", co.labels.properties["company.net/lob"].pattern, "free text!"]
];
for (const [name, p, bad] of rows) console.log(`${name}: pattern attribute with a value that cmapi refuses (${JSON.stringify(bad)}):`, JSON.stringify(await probe(p, bad)));
console.log("console lines:", messages.length, messages.slice(0, 3).map((m) => m.slice(0, 140)));
// type=email: what .value gives for what a person types.
await page.setContent("<form><input id=e type=email></form>");
for (const typed of [" abc-team@company.net ", "abc-team@bücher.example", "é@company.net", "abc-team@company.net\n"]) {
  await page.fill("#e", "");
  await page.locator("#e").pressSequentially(typed.replace("\n", ""));
  const r = await page.evaluate(() => { const e = document.getElementById("e"); return { value: e.value, typeMismatch: e.validity.typeMismatch }; });
  console.log(`type=email typed ${JSON.stringify(typed.replace("\n", ""))} ->`, JSON.stringify(r));
}
await browser.close();
