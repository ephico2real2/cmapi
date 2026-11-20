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

// #336: the New namespace form evaluates or shows each keyword that GET /api/v1/metadata-keys sends, or lists it as
// ignored with its reason (src/portal/metadataForm.ts, KEYWORDS). A keyword in neither list fails here: the generator
// (MetadataKeys.json_schema) gained a rule that the form would silently check less than cmapi does.
const { KEYWORDS } = await import("../src/portal/metadataForm.ts");
const samples = JSON.parse(readFileSync(join(app, "..", "cmapi", "src", "cmapi", "contract", "samples.json"), "utf8"));
const answers = { reference: samples.operations.core_metadata_keys.response.body,
  company: JSON.parse(readFileSync(join(app, "tests", "api", "metadata-keys.company.json"), "utf8")),
  "company-479": JSON.parse(readFileSync(join(app, "tests", "api", "metadata-keys.company-479.json"), "utf8")) };
const known = (level) => new Set([...KEYWORDS[level].read, ...Object.keys(KEYWORDS[level].ignored)]);
const unknown = [];
const visit = (level, where, schema) => {
  for (const keyword of Object.keys(schema)) if (!known(level).has(keyword)) unknown.push(`${where}: ${keyword}`);
};
for (const [name, answer] of Object.entries(answers)) {
  assert.deepEqual(Object.keys(answer).sort(), ["annotations", "labels", "x-cmapi-expiration"],
    `${name}: the answer's two maps and expiresAt's rules (#479)`);
  visit("answer", name, answer);
  for (const [env, rules] of Object.entries(answer["x-cmapi-expiration"].environments)) visit("expiration", `${name} x-cmapi-expiration.${env}`, rules);
  for (const field of ["labels", "annotations"]) {
    const map = answer[field];
    visit("map", `${name} ${field}`, map);
    visit("additionalProperties", `${name} ${field}.additionalProperties`, map.additionalProperties);
    visit("otherKeys", `${name} ${field}.x-cmapi-other-keys`, map["x-cmapi-other-keys"]);
    // propertyNames, each branch of its anyOf, and the `not` of a branch with the keys and prefixes that it refuses (#479 P10).
    visit("propertyNames", `${name} ${field}.propertyNames`, map.propertyNames);
    for (const [i, branch] of map.propertyNames.anyOf.entries()) {
      visit("keyBranch", `${name} ${field}.propertyNames.anyOf[${i}]`, branch);
      for (const [j, refused] of (branch.not?.anyOf ?? []).entries()) visit("keyBranch", `${name} ${field}.propertyNames.anyOf[${i}].not.anyOf[${j}]`, refused);
    }
    for (const [key, prop] of Object.entries(map.properties)) {
      visit("property", `${name} ${field}.${key}`, prop);
      (prop.allOf ?? []).forEach((entry, i) => visit("allOf", `${name} ${field}.${key}.allOf[${i}]`, entry));
    }
  }
}
assert.deepEqual(unknown, [], "keywords of GET /api/v1/metadata-keys that the form neither evaluates nor lists as ignored");
console.log("ok - the New namespace form reads each keyword of GET /api/v1/metadata-keys or lists it as ignored");
