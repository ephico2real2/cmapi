#!/usr/bin/env node
// Every state key of the logic class is named in MOCKUP-CONTRACT.md, and every dataset the contract names exists.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const app = join(dirname(fileURLToPath(import.meta.url)), "..");
const main = readFileSync(join(app, "..", "mockups", "portal", "Main.dc.html"), "utf8");
const state = /this\.state = \{ (.*) \};\n/.exec(main)[1];
const keys = [...state.matchAll(/(?:^|, )(\w+): /g)].map((m) => m[1]);
assert.ok(keys.length > 40, "the state literal was found");

const contract = readFileSync(join(app, "MOCKUP-CONTRACT.md"), "utf8");
const tabs = contract.slice(contract.indexOf("## Tabs"), contract.indexOf("## Where the page differs"));
const rows = tabs.split("\n").filter((l) => l.startsWith("| ") && !l.startsWith("| Tab"));
const named = (column) => new Set(rows.flatMap((row) => [...row.split("|")[column].matchAll(/`(\w+)`/g)].map((m) => m[1])));
const listed = named(2);
assert.deepEqual(keys.filter((k) => !listed.has(k)), [], "state keys the contract does not list");
assert.deepEqual([...listed].filter((k) => !keys.includes(k)), [], "contract keys the logic does not have");

const returned = main.slice(main.indexOf("  renderVals() {"));
assert.deepEqual([...named(3)].filter((k) => !new RegExp(`\\b${k}: `).test(returned)), [], "contract datasets renderVals does not return");
assert.ok(named(3).has("dashboards"), "the KPI tab's dashboards are listed");
// The parity test reads dist/portal.html, so a template edit with a stale dist would pass without the page changing.
const scripts = JSON.parse(readFileSync(join(app, "package.json"), "utf8")).scripts;
assert.match(scripts.test, /^node \.\.\/scripts\/build-portal\.mjs --check && /, "npm test first checks that the mockup build is current");
console.log("ok - contract");
