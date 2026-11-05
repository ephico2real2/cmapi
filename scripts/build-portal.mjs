#!/usr/bin/env node
// Inlines mockups/portal/Main.dc.html and its runtime into dist/portal.html, one file to double-click or publish.
// With --check it builds nothing and fails if dist/portal.html is out of date, so the two cannot drift.
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const portal = join(dirname(fileURLToPath(import.meta.url)), "..", "mockups", "portal");
const output = join(portal, "dist", "portal.html");
const RUNTIME_TAG = '<script src="runtime/dc-lite.js"></script>';

function build() {
  const page = readFileSync(join(portal, "index.html"), "utf8");
  const runtime = readFileSync(join(portal, "runtime", "dc-lite.js"), "utf8");
  const source = readFileSync(join(portal, "Main.dc.html"), "utf8");
  if (!page.includes(RUNTIME_TAG)) throw new Error(`index.html no longer contains ${RUNTIME_TAG}`);
  // "<!-- <script" puts the HTML parser in a state where the closing tag no longer ends the block, and the page dies silently.
  if (/<\/script|<!--/i.test(runtime)) throw new Error("dc-lite.js must not contain a closing script tag or an HTML comment opener");

  // Escaping < keeps the source's own </script> from ending this block; JSON.parse turns it back.
  const data = JSON.stringify(source).replace(/</g, "\\u003c");
  const inlined = `<script type="application/json" id="dc-source">${data}</script>\n<script>\n${runtime}</script>`;
  return page.replace(RUNTIME_TAG, () => inlined);
}

const html = build();
if (process.argv.includes("--check")) {
  if (!existsSync(output) || readFileSync(output, "utf8") !== html) {
    console.error("mockups/portal/dist/portal.html is out of date: run node scripts/build-portal.mjs");
    process.exit(1);
  }
  console.log("mockups/portal/dist/portal.html is up to date");
} else {
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, html);
  console.log(`wrote mockups/portal/dist/portal.html (${html.length} characters)`);
}
