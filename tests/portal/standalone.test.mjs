#!/usr/bin/env node
// Standalone page and runtime details that the walks do not reach. The caret case is compared with React's own rule.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";
import { distPage, repoRoot, serve } from "./views.mjs";

const portal = join(repoRoot, "mockups", "portal");

// The build refuses a runtime the HTML parser would read past the end of its own script block.
const root = mkdtempSync(join(tmpdir(), "build-portal-"));
try {
  mkdirSync(join(root, "scripts"));
  mkdirSync(join(root, "mockups", "portal", "runtime"), { recursive: true });
  cpSync(join(repoRoot, "scripts", "build-portal.mjs"), join(root, "scripts", "build-portal.mjs"));
  cpSync(join(portal, "index.html"), join(root, "mockups", "portal", "index.html"));
  cpSync(join(portal, "Main.dc.html"), join(root, "mockups", "portal", "Main.dc.html"));
  const runtime = readFileSync(join(portal, "runtime", "dc-lite.js"), "utf8");
  writeFileSync(join(root, "mockups", "portal", "runtime", "dc-lite.js"), `${runtime}\n// <!-- <script> in a comment\n`);
  const build = spawnSync("node", [join(root, "scripts", "build-portal.mjs")], { encoding: "utf8" });
  assert.notEqual(build.status, 0, "a runtime holding <!-- <script> does not build");
} finally {
  rmSync(root, { recursive: true, force: true });
}

// A reference folder gets its favicon request answered, or a --record run in installed Chrome dies on a 404 console error.
const reference = await serve(tmpdir(), { favicon: true });
assert.equal((await fetch(`http://127.0.0.1:${reference.port}/favicon.ico`)).status, 204, "a reference folder");
reference.close();
// Our own pages are served strictly, and carry the icon themselves, so removing it cannot pass unnoticed.
const strict = await serve(tmpdir());
assert.equal((await fetch(`http://127.0.0.1:${strict.port}/favicon.ico`)).status, 404, "our own pages get no help");
strict.close();
for (const page of [join(portal, "index.html"), distPage, join(repoRoot, "cmapi-portal-ui", "index.html")]) {
  assert.match(readFileSync(page, "utf8"), /<link rel="icon" href="data:,">/, `${page} carries its inline icon`);
}

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL });
const page = await browser.newPage();
page.setDefaultTimeout(5000);
try {
  // A field never typed in, focused, whose state changes: React writes the value, and that write moves the caret to the end.
  await page.setContent(`<!doctype html><body><div id="root"></div>`);
  await page.addScriptTag({ path: join(portal, "runtime", "dc-lite.js") });
  await page.evaluate(() => {
    const source = `<x-dc><input id="f" value="{{v}}"><select id="s" value="{{p}}"><option value="a">a</option><option value="b">b</option></select></x-dc>
      <script type="text/x-dc" data-dc-script data-props='{}'>class Component extends DCLogic { constructor(p) { super(p); window.logic = this; this.state = { v: "wait", p: "b" }; } renderVals() { return this.state; } }<\/script>`;
    window.DcLite.mount(window.DcLite.parse(source), document.getElementById("root"), {});
  });
  await page.locator("#f").click();
  await page.keyboard.press("Home");
  const caret = await page.evaluate(async () => {
    window.logic.setState({ v: "changed" });
    await new Promise((resolve) => setTimeout(resolve));
    const f = document.querySelector("#f");
    return { value: f.value, caret: f.selectionStart, focused: document.activeElement === f };
  });
  assert.deepEqual(caret, { value: "changed", caret: 7, focused: true }, "the caret goes to the end, as under React");
  assert.equal(await page.evaluate(() => "defaultValue" in document.querySelector("#s") || Object.hasOwn(document.querySelector("#s"), "defaultValue")), false, "no stray property on a select");

  // A bad hash on the view already showing still resolves to the real hash.
  await page.goto(`${pathToFileURL(distPage).href}#nonprod/workflow`);
  await page.waitForSelector("nav.tabs");
  await page.evaluate(() => { location.hash = "#bogus/nonsense"; });
  await page.waitForTimeout(40);
  assert.equal(await page.evaluate(() => location.hash), "#nonprod/workflow", "the hash shows the view on screen");
  console.log("ok - standalone");
} finally {
  await browser.close();
}
