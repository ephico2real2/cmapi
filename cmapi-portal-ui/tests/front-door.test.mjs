// The built portal, the API's HTML pages and the mockup in a browser, through the front door's nginx configuration
// (cmapi-portal-ui/nginx/), with its Content-Security-Policy and its one origin. Each page must work with no
// "securitypolicyviolation" event and no CSP message in the console.
//
// It needs nginx and the API's page bundles, so it is not part of `npm test`:
//   FRONT_DOOR_NGINX=/path/to/nginx     an nginx binary (1.30.6 is what the image runs), or
//   FRONT_DOOR_IMAGE=cmapi-portal:ci    the image, run by FRONT_DOOR_ENGINE (docker) on the host network (Linux)
//   FRONT_DOOR_PYTHON=python3           a Python with cmapi's dependencies (fastapi, uvicorn)
//   FRONT_DOOR_STATIC=<dir>             the bundles of `cmapi-tools docs-assets --static-dir <dir>`
// Run after `npm run build`. PW_CHANNEL=chrome runs it in the installed Chrome.
//
// The portal signs in at the stand-in issuer (tests/api/standin.mjs) and calls the stand-in API through nginx. The
// API's pages are cmapi's own route functions (deploy/tests/front-door-docs-standin.py). Not covered: Swagger UI's
// "Authorize" popup, which needs a client cmapi-docs at the issuer.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { connect } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { startApi, startIssuer, USERS } from "./api/standin.mjs";

const app = join(dirname(fileURLToPath(import.meta.url)), "..");
const repo = join(app, "..");
const PYTHON = process.env.FRONT_DOOR_PYTHON || "python3";
const STATIC = process.env.FRONT_DOOR_STATIC;
const nginxFlag = process.env.FRONT_DOOR_NGINX ? ["--nginx", process.env.FRONT_DOOR_NGINX]
  : process.env.FRONT_DOOR_IMAGE ? ["--image", process.env.FRONT_DOOR_IMAGE, "--engine", process.env.FRONT_DOOR_ENGINE || "docker"] : null;
assert.ok(nginxFlag, "set FRONT_DOOR_NGINX or FRONT_DOOR_IMAGE");
assert.ok(STATIC && existsSync(join(STATIC, "swagger-ui", "swagger-ui-bundle.js")), "set FRONT_DOOR_STATIC to the folder of cmapi-tools docs-assets");
assert.ok(existsSync(join(app, "dist", "index.html")), "run npm run build first");
const MOCKUP_HOST = "cmapi-mockup.test";
const CHECK_TIMEOUT_MS = 60_000;

const freePort = () => new Promise((resolve) => { const s = createServer().listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); }); });
async function waitPort(port, what, child) {
  for (let i = 0; i < 150; i++) {
    if (child?.exitCode != null) throw new Error(`${what} stopped with ${child.exitCode}`);
    const up = await new Promise((resolve) => { const c = connect(port, "127.0.0.1", () => { c.end(); resolve(true); }); c.on("error", () => resolve(false)); });
    if (up) return;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`${what} did not listen on ${port} within 15 s`);
}

const children = [];
const closers = [];
let failed = 0;
try {
  // The stand-ins: the issuer, the API (JSON), and cmapi's HTML pages, behind one upstream address as nginx sees the API.
  const listen = await freePort();
  const origin = `http://localhost:${listen}`;
  const issuer = await startIssuer({ redirectUris: () => [`${origin}/`, `${origin}/index.html`] });
  const api = await startApi({ issuer, portalOrigin: () => origin });
  closers.push(() => issuer.close?.(), () => api.close());
  const docsPort = await freePort();
  const docs = spawn(PYTHON, [join(repo, "deploy/tests/front-door-docs-standin.py"), String(docsPort), STATIC],
    { env: { ...process.env, PYTHONPATH: join(repo, "cmapi/src") }, stdio: ["ignore", "inherit", "inherit"] });
  children.push(docs);
  await waitPort(docsPort, "the docs stand-in", docs);
  const apiPort = Number(new URL(api.url).port);
  const upstream = createServer((req, res) => {
    const port = req.url.startsWith("/api/") ? apiPort : docsPort;
    const out = httpRequest({ host: "127.0.0.1", port, method: req.method, path: req.url, headers: req.headers }, (r) => { res.writeHead(r.statusCode, r.headers); r.pipe(res); });
    out.on("error", () => { res.writeHead(502); res.end(); });
    req.pipe(out);
  });
  const upstreamPort = await new Promise((resolve) => upstream.listen(0, "127.0.0.1", () => resolve(upstream.address().port)));
  closers.push(() => upstream.close());

  // nginx with the front door's configuration, from deploy/tests/front-door-test.py's render mode.
  const work = mkdtempSync(join(tmpdir(), "front-door-browser-"));
  closers.push(() => rmSync(work, { recursive: true, force: true }));
  const rendered = spawnSync(PYTHON, [join(repo, "deploy/tests/front-door-test.py"), ...nginxFlag, "render", "--out", join(work, "conf"),
    "--listen", String(listen), "--upstream", `127.0.0.1:${upstreamPort}`, "--oidc-origin", new URL(issuer.url).origin,
    "--portal-host", "localhost", "--mockup-host", MOCKUP_HOST], { encoding: "utf8", timeout: 120_000 });
  assert.equal(rendered.status, 0, `render failed: ${rendered.stderr}`);
  const { command, html } = JSON.parse(rendered.stdout);
  cpSync(join(app, "dist"), join(html, "portal"), { recursive: true });
  cpSync(join(repo, "mockups/portal/dist/portal.html"), join(html, "mockup", "portal.html"));
  writeFileSync(join(html, "portal", "config.json"), JSON.stringify({ apiUrl: origin, issuer: issuer.url, clientId: "cmapi-portal",
    audience: "cmapi-nonprod", instance: "nonprod", displayName: "Non-production", environments: ["rnd", "dev"], otherInstances: [] }));
  const nginx = spawn(command[0], command.slice(1), { stdio: ["ignore", "ignore", "inherit"] });
  children.push(nginx);
  await waitPort(listen, "nginx", nginx);

  const browser = await chromium.launch({ channel: process.env.PW_CHANNEL, headless: !process.env.PW_HEADED,
    args: [`--host-resolver-rules=MAP ${MOCKUP_HOST} 127.0.0.1`] });
  closers.unshift(() => browser.close());

  /** A new profile that records each CSP violation and each CSP message of the console. */
  async function page() {
    const context = await browser.newContext();
    await context.addInitScript(() => {
      window.__csp = [];
      document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
    });
    const p = await context.newPage();
    p.setDefaultTimeout(15_000);
    const csp = [];
    p.on("console", (m) => { if (/Content Security Policy|Refused to/i.test(m.text())) csp.push(m.text()); });
    p.on("pageerror", (e) => csp.push(`page error: ${e.message}`));
    return { context, p, violations: async () => [...csp, ...(await p.evaluate(() => window.__csp).catch(() => []))] };
  }

  /** Waits for the selector; a failure says what the page shows and which CSP violations it had. */
  async function shows(p, selector, violations) {
    try {
      await p.locator(selector).first().waitFor();
    } catch {
      const text = (await p.locator("body").innerText().catch(() => "")).slice(0, 300).replace(/\s+/g, " ");
      throw new Error(`no ${selector}; the page shows "${text}"; violations ${JSON.stringify(await violations())}`);
    }
  }

  async function check(name, fn) {
    const timer = new Promise((_, reject) => setTimeout(() => reject(new Error(`timed out after ${CHECK_TIMEOUT_MS / 1000} s`)), CHECK_TIMEOUT_MS));
    try {
      await Promise.race([fn(), timer]);
      console.log(`  ok   ${name}`);
    } catch (e) {
      failed++;
      console.log(`  FAIL ${name}: ${e.message}`);
    }
  }

  await check("the portal signs in and lists requests on one origin, with no CSP violation", async () => {
    issuer.state.user = USERS.requester;
    api.state.seen.length = 0;
    const { context, p, violations } = await page();
    await p.goto(`${origin}/#requests`);
    await shows(p, "table[aria-label=Requests] tbody tr", violations);
    const calls = api.state.seen.filter((c) => c.path === "/api/v1/requests");
    assert.ok(calls.length > 0, "the portal called /api/v1/requests through the front door");
    assert.deepEqual(calls.map((c) => c.origin), calls.map(() => null), "same origin: the browser sent no Origin header, so no CORS was needed");
    assert.deepEqual(await violations(), []);
    await p.getByRole("button", { name: "Sign out" }).click();
    await p.waitForURL(`${origin}/`);
    assert.ok(issuer.state.seen.some((s) => s.what === "logout" && s.method === "POST"), "the sign-out form was posted to the issuer (form-action)");
    assert.deepEqual(await violations(), []);
    await context.close();
  });

  await check("Swagger UI renders the operations, with no CSP violation", async () => {
    const { context, p, violations } = await page();
    await p.goto(`${origin}/docs`);
    await shows(p, ".opblock", violations);
    assert.ok(await p.locator(".opblock").count() > 10, "Swagger UI shows the operations of the contract");
    assert.deepEqual(await violations(), []);
    await context.close();
  });

  // ReDoc 3 loads its "API docs by Redocly" logo from cdn.redoc.ly, and no option removes it (docs/reviews/2026-11-14-issue-229/).
  // The policy refuses it, and the bundle hides the image. Any other refused request fails the check.
  const REDOC_LOGO = /^(img-src https:\/\/cdn\.redoc\.ly\/redoc\/logo-mini(-full)?\.svg|.*Loading the image 'https:\/\/cdn\.redoc\.ly\/redoc\/logo-mini(-full)?\.svg'.*)$/;
  await check("ReDoc renders the reference and searches it, with only its logo refused", async () => {
    const { context, p, violations } = await page();
    await p.goto(`${origin}/redoc`);
    await shows(p, ".api-content", violations);
    await p.waitForTimeout(2000);
    assert.ok(p.workers().length > 0, "ReDoc's search workers run ('unsafe-eval' and blob: workers in the policy)");
    await p.keyboard.press("Control+k");
    await p.locator('input[placeholder="Search docs..."]').fill("namespace");
    await p.getByText("request fields", { exact: false }).first().waitFor();
    assert.deepEqual((await violations()).filter((v) => !REDOC_LOGO.test(v)), []);
    await context.close();
  });

  await check("the problem pages render, with no CSP violation", async () => {
    const { context, p, violations } = await page();
    const r = await p.goto(`${origin}/problems`);
    assert.equal(r.status(), 200);
    assert.match(await p.locator("body").innerText(), /policy-violation/);
    assert.deepEqual(await violations(), []);
    await context.close();
  });

  await check("the mockup renders on its own host, with no CSP violation", async () => {
    const { context, p, violations } = await page();
    await p.goto(`http://${MOCKUP_HOST}:${listen}/#nonprod/workflow`);
    await shows(p, "nav.tabs", violations);
    assert.deepEqual(await violations(), []);
    await context.close();
  });
} finally {
  for (const c of children) c.kill("SIGTERM");
  for (const close of closers) { try { await close(); } catch { /* the next one still runs */ } }
}
console.log(`front door browser checks failed: ${failed}`);
process.exit(failed ? 1 : 0);
