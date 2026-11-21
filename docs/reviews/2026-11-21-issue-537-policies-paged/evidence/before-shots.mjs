// Full-page screenshots of the Policies tab on the stand-in, with an 80-policy fleet (as CRC, #537), and their heights.
// node shots.mjs <worktree cmapi-portal-ui> <out dir> [open]
import { mkdirSync } from "node:fs";
import { join } from "node:path";
const [app, outDir, openIt] = process.argv.slice(2);
const { chromium } = await import(join(app, "node_modules", "playwright", "index.mjs"));
const S = await import(join(app, "tests", "api", "standin.mjs"));
mkdirSync(outDir, { recursive: true });
let portal;
const issuer = await S.startIssuer({ redirectUris: () => [portal.page] });
const api = await S.startApi({ issuer, portalOrigin: () => portal.origin });
const CONFIG = { apiUrl: api.url, issuer: issuer.url, clientId: "cmapi-portal", audience: "cmapi-nonprod", instance: "nonprod", displayName: "Non-production", environments: ["rnd", "dev"], otherInstances: {} };
portal = await S.servePortal(join(app, "dist"), () => CONFIG);
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL });
issuer.state.user = S.USERS.requester; issuer.state.sessions = true; issuer.state.lifetime = 300;
Object.assign(api.state, { mode: "ok", delayMs: 0, hold: null, seen: [], answers: [], lose: new Set(), policies: S.policyFleetWith(80), rejections: S.rejectionsFrom(3) });
const heights = {};
for (const width of [390, 820, 1440]) {
  const context = await browser.newContext({ viewport: { width, height: 1000 } });
  const page = await context.newPage();
  await page.goto(`${portal.page}#policies`);
  await page.locator("table[aria-label='Refused by cmapi'] tbody tr").first().waitFor();
  if (openIt) await page.getByRole("tabpanel").locator(".pf-v6-c-card").filter({ has: page.getByRole("heading", { name: "Results by policy" }) }).locator(".pf-v6-c-card__header-toggle button").click();
  for (const theme of ["light", "dark"]) {
    await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
    await page.waitForTimeout(600);
    // The page's main container scrolls, not the document: grow the window to the tallest element, as check 484-L does.
    const tall = await page.evaluate(() => Math.max(...[...document.querySelectorAll("*")].map((el) => el.scrollHeight)));
    await page.setViewportSize({ width, height: tall });
    await page.waitForTimeout(300);
    heights[`${width}-${theme}`] = await page.evaluate(() => Math.max(...[...document.querySelectorAll("*")].map((el) => el.scrollHeight)));
    await page.screenshot({ path: join(outDir, `policies-${width}-${theme}.png`), fullPage: true });
  }
  await context.close();
}
console.log(JSON.stringify(heights));
await browser.close(); portal.close(); api.close(); issuer.close();
process.exit(0);
