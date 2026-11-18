// Does the portal's tab bar overflow (PatternFly's scroll buttons shown) at each width, for each role? (#347)
import { join } from "node:path";
const app = process.argv[2];
const { chromium } = await import(join(app, "node_modules/playwright/index.mjs"));
const S = await import(join(app, "tests/api/standin.mjs"));
let portal;
const issuer = await S.startIssuer({ redirectUris: () => [portal.page] });
const api = await S.startApi({ issuer, portalOrigin: () => portal.origin });
portal = await S.servePortal(join(app, "dist"), () => ({ apiUrl: api.url, issuer: issuer.url, clientId: "cmapi-portal", audience: "cmapi-nonprod", instance: "nonprod", displayName: "Non-production", environments: ["rnd", "dev"], otherInstances: {} }));
const browser = await chromium.launch();
for (const user of ["requester", "approver", "operator"]) for (const width of [390, 820, 1440]) {
  issuer.state.user = S.USERS[user]; issuer.state.sessions = true; issuer.state.lifetime = 300;
  const context = await browser.newContext({ viewport: { width, height: 1000 } });
  const page = await context.newPage();
  await page.goto(portal.page + "#requests");
  await page.locator("[role=tablist]").waitFor();
  await page.waitForTimeout(800);
  console.log(user, width, await page.evaluate(() => { const t = document.querySelector(".pf-v6-c-tabs"), l = t.querySelector("[role=tablist]"); return `tabs=${l.children.length} scrollWidth=${l.scrollWidth} clientWidth=${l.clientWidth} scrollable=${t.classList.contains("pf-m-scrollable")}`; }));
  await context.close();
}
await browser.close(); process.exit(0);
