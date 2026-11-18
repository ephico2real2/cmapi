// Probe for #347: a timeline of the Tabs scroll buttons around the "new 390" view of check 7.
// Usage: node probe.mjs <worktree>/cmapi-portal-ui [throttleRate] [runs]
import { join } from "node:path";
const app = process.argv[2];
const rate = Number(process.argv[3] ?? 1);
const runs = Number(process.argv[4] ?? 3);
const { chromium } = await import(join(app, "node_modules/playwright/index.mjs"));
const S = await import(join(app, "tests/api/standin.mjs"));
let portal;
const issuer = await S.startIssuer({ redirectUris: () => [portal.page] });
const api = await S.startApi({ issuer, portalOrigin: () => portal.origin });
const CONFIG = { apiUrl: api.url, issuer: issuer.url, clientId: "cmapi-portal", audience: "cmapi-nonprod", instance: "nonprod", displayName: "Non-production", environments: ["rnd", "dev"],
  otherInstances: { prod: { environments: ["prod"], url: "https://cmapi.example.test" }, staging: { environments: ["qa", "uat"], url: "https://cmapi-staging.example.test" } } };
portal = await S.servePortal(join(app, "dist"), () => CONFIG);
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL });
const SAMPLES = S.SAMPLES;
const INSTRUMENT = () => {
  const t0 = performance.now(); window.__log = [];
  const log = (what) => window.__log.push(`${Math.round(performance.now() - t0)} ${what}`);
  window.__mark = log;
  addEventListener("resize", () => log(`window resize ${innerWidth}`));
  document.addEventListener("transitionrun", (e) => { if (e.target.closest?.(".pf-v6-c-tabs")) log(`transitionrun ${e.target.className.split(" ")[0]} ${e.propertyName}`); }, true);
  document.addEventListener("scroll", (e) => { if (e.target.getAttribute?.("role") === "tablist") log(`tablist scroll ${e.target.scrollLeft}`); }, true);
  new MutationObserver((ms) => { for (const m of ms) { const el = m.target; if (el.classList?.contains("pf-v6-c-tabs") && m.type === "attributes") log(`tabs class scrollable=${el.classList.contains("pf-m-scrollable")}`);
    if (m.type === "childList") for (const n of m.addedNodes) if (n.classList?.contains("pf-v6-c-tabs__scroll-button")) log("scroll button rendered"); } })
    .observe(document, { subtree: true, attributes: true, attributeFilter: ["class"], childList: true });
  new ResizeObserver(() => { const l = document.querySelector("[role=tablist]"); if (l) log(`tablist width ${l.clientWidth} scrollW ${l.scrollWidth} docW ${document.documentElement.clientWidth}`); })
    .observe(document.documentElement);
};
const FINITE = "(a) => a.effect?.getComputedTiming().endTime !== Infinity && a.playState !== \"finished\"";
const running = (page) => page.evaluate(`document.getAnimations().filter(${FINITE}).length`);
const settled = (page) => page.evaluate(`Promise.all(document.getAnimations().filter(${FINITE}).map((a) => a.finished.catch(() => undefined)))`);
const TABS_AT_REST = `[...document.querySelectorAll(".pf-v6-c-tabs:not(.pf-m-vertical)")].every((tabs) => {
    const list = tabs.querySelector(":scope > [role=tablist]");
    if (!list?.firstElementChild) return true;
    const box = list.getBoundingClientRect(), left = Math.ceil(box.left), right = Math.floor(box.right);
    const inView = (el) => {
      const r = el.getBoundingClientRect(), l = Math.ceil(r.left), rr = Math.floor(r.right);
      return (l >= left && rr <= right) || (box.width < r.width && ((l < left && rr > left) || (rr > right && l < right)));
    };
    const overflows = !inView(list.firstElementChild) || !inView(list.lastElementChild);
    const scrollable = tabs.classList.contains("pf-m-scrollable"), buttons = tabs.querySelector(":scope > .pf-v6-c-tabs__scroll-button") !== null;
    return overflows ? scrollable : !scrollable && !buttons;
  })`;
let fails = 0, early = 0;
for (let i = 0; i < runs; i++) {
  issuer.state.user = S.USERS.requester; issuer.state.sessions = true; issuer.state.lifetime = 300; issuer.state.seen.length = 0;
  Object.assign(api.state, { mode: "ok", items: S.requestsFrom(SAMPLES.operations.requests_list_requests.response.body.items[0], 61), delayMs: 0, seen: [], answers: [], lose: new Set(), keys: new Map(), created: 0, clusters: SAMPLES.operations.core_clusters.response.body.items,
    tiers: SAMPLES.operations.tiers_tiers.response.body, plan: SAMPLES.operations["namespaces_create_namespace:dryRun"].response.body, quotas: SAMPLES.operations.quotas_quotas.response.body.items, etags: new Map(), kpi: SAMPLES.operations.admin_kpi.response.body,
    expirations: [], never: false, today: SAMPLES.operations.expiration_expirations.response.body.today, metadataKeys: S.REFERENCE_KEYS, protection: new Map(), policies: S.policyFleet(), rejections: S.rejectionsFrom(3), capacity: S.capacityFleet(), notModified: 0 });
  const context = await browser.newContext({ viewport: { width: 390, height: 1000 } });
  const page = await context.newPage();
  await page.addInitScript(INSTRUMENT);
  if (rate > 1) { const cdp = await context.newCDPSession(page); await cdp.send("Emulation.setCPUThrottlingRate", { rate }); }
  const panel = page.getByRole("tabpanel");
  const mark = (s) => page.evaluate((s) => window.__mark?.(`--- ${s}`), s).catch(() => {});
  await page.goto(portal.page + "#new");
  await page.locator("[role=tablist]").waitFor(); await mark("tablist visible");
  if (process.env.SWEEP) { await page.waitForTimeout(i * Number(process.env.SWEEP)); await mark(`phase ${i * Number(process.env.SWEEP)}`); } else {
  await panel.getByRole("button", { name: "Dry run" }).waitFor(); await mark("dry run button");
  await page.getByLabel("Team (required)").fill("payments");
  await page.getByLabel("Team DL (required)").fill("payments-team@ephico2real.com");
  await page.getByLabel("Justification").fill("Payments service dev namespace"); await mark("filled");
  await panel.getByRole("button", { name: "Dry run" }).click();
  await panel.getByText("Dry run passed · nothing written").waitFor(); await mark("dry run passed"); }
  await page.evaluate(() => document.documentElement.classList.toggle("pf-v6-theme-dark", false));
  // MODE=new: the fix's settle(), copied from portal.test.mjs (TABS_AT_REST, then the same rounds).
  if (process.env.MODE === "new") { await page.waitForFunction(TABS_AT_REST); await mark("tabs at rest"); }
  for (let round = 0; round < 5 && (round === 0 || await running(page)); round++) { await settled(page); await mark(`settled round ${round}`); }
  const n = await running(page); await mark(`running=${n}`);
  if (n) fails++;
  await page.waitForTimeout(600);
  // A read before rest: nothing ran when the page was read, and PatternFly's scroll buttons started after it.
  const log = await page.evaluate(() => window.__log);
  const readAt = Number(log.find((l) => l.includes(`running=`))?.split(" ")[0]);
  const flips = log.filter((l) => l.includes("scrollable=true")).map((l) => Number(l.split(" ")[0]));
  if (!n && flips.some((t) => t > readAt)) early++;
  if (n || process.env.VERBOSE) console.log(`run ${i} running=${n}\n  ${(await page.evaluate(() => window.__log)).join("\n  ")}`);
  await context.close();
}
console.log(`MODE=${process.env.MODE ?? "old"} SWEEP=${process.env.SWEEP ?? "-"}: FAILS ${fails} of ${runs} at rate ${rate}; read before the scroll buttons rested (passed vacuously): ${early}`);
await browser.close(); process.exit(0);
