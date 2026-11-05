#!/usr/bin/env node
// Captures every acceptance view: node capture.mjs <out-dir> [source-dir]
// Without source-dir it opens dist/portal.html from file://, as a person double-clicking it would. With
// source-dir it serves that folder and opens Main.dc.html, which is how to capture another runtime.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";
import { VIEWS, canonicalDom, distPage, gotoView, serve, viewName } from "./views.mjs";

const [outDir, sourceDir] = process.argv.slice(2);
if (!outDir) {
  console.error("usage: node capture.mjs <out-dir> [source-dir]");
  process.exit(2);
}
mkdirSync(outDir, { recursive: true });

const server = sourceDir ? await serve(sourceDir) : null;
const url = server ? `http://127.0.0.1:${server.port}/Main.dc.html` : pathToFileURL(distPage).href;
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1320, height: 1720 }, deviceScaleFactor: 1 });
const page = await context.newPage();
const problems = [];
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") problems.push(`${m.type()}: ${m.text()}`); });
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));

await page.goto(url);
await page.waitForSelector("nav.tabs");
for (const view of VIEWS) {
  await gotoView(page, view);
  const name = viewName(view);
  await page.locator("#dc-root").screenshot({ path: join(outDir, `${name}.png`), animations: "disabled", caret: "hide" });
  writeFileSync(join(outDir, `${name}.dom.txt`), await page.evaluate(canonicalDom));
  console.log(`captured ${name}`);
}
await browser.close();
if (server) server.close();
console.log(problems.length ? `console problems:\n${[...new Set(problems)].join("\n")}` : "console clean");
