#!/usr/bin/env node
// What the portal's build promises (issue #204, criterion 4): it holds no sample data of the mockup, and with no
// config.json that names an issuer and an API it shows an error and starts nothing.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { servePortal } from "./standin.mjs";

const app = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const textOf = (dir) => readdirSync(dir, { recursive: true }).filter((f) => /\.(js|html|css|json)$/.test(String(f))).map((f) => readFileSync(join(dir, String(f)), "utf8")).join("\n");

// The names of the mockup's sample data, read from the mockup: each request ID, cluster ID and recommendation ID.
const mockup = readFileSync(join(app, "..", "mockups", "portal", "Main.dc.html"), "utf8");
const samples = [...new Set(mockup.match(/\b(?:req|op|pl)-20261103-[0-9a-f]{4}\b|\bOCP_GF\d+\b|\brec-[a-z-]+-\d{4}\b/g))];
assert.ok(samples.length >= 30, `the mockup's sample names were read (${samples.length})`);
const demo = textOf(join(app, "dist-demo"));
assert.deepEqual(samples.filter((s) => !demo.includes(s)), [], "the check can see them: the demo build holds each one");
const built = textOf(join(app, "dist"));
assert.deepEqual(samples.filter((s) => built.includes(s)), [], "the portal's build holds none of the mockup's sample data");
assert.ok(!/renderVals|logic\.generated/.test(built), "and not the mockup's logic class");
console.log(`ok - the portal's build holds no sample data (${samples.length} names checked)`);

const VALID = { apiUrl: "https://cmapi.example.test", issuer: "https://sso.example.test/realms/cmapi", clientId: "cmapi-portal", instance: "nonprod" };
const CASES = [
  ["no config.json", null, /config\.json did not load \(HTTP 404\)/],
  ["not JSON", "<html>", /config\.json is not JSON/],
  ["no issuer", { ...VALID, issuer: undefined }, /config\.json has no issuer/],
  ["no API", { ...VALID, apiUrl: "" }, /config\.json has no apiUrl/],
  ["an issuer over plain http", { ...VALID, issuer: "http://sso.example.test/realms/cmapi" }, /issuer must be an https URL/],
  ["an API with a password in its URL", { ...VALID, apiUrl: "https://user:pw@cmapi.example.test" }, /apiUrl must have no user, query or fragment/],
  ["an API with a path", { ...VALID, apiUrl: "https://cmapi.example.test/api/v1" }, /apiUrl must have no path/],
  ["no client", { ...VALID, clientId: "" }, /config\.json has no clientId/]
];
let config = null;
const portal = await servePortal(join(app, "dist"), () => config);
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL, headless: !process.env.PW_HEADED });
try {
  for (const [name, value, message] of CASES) {
    config = value;
    const page = await (await browser.newContext()).newPage();
    const asked = [];
    page.on("request", (r) => { if (!r.url().startsWith(portal.origin)) asked.push(r.url()); });
    await page.goto(portal.page);
    await page.getByRole("heading", { name: "The portal is not configured." }).waitFor({ timeout: 8000 });
    assert.match(await page.locator("#root").innerText(), message, name);
    assert.equal(await page.getByRole("tab").count(), 0, `${name}: no tab`);
    assert.equal(await page.locator("table").count(), 0, `${name}: no data`);
    assert.deepEqual(asked, [], `${name}: no call to an issuer or an API`);
    await page.context().close();
  }
  console.log(`ok - with no valid config.json the portal shows an error and starts nothing (${CASES.length} cases)`);
} finally {
  await browser.close();
  portal.close();
}
