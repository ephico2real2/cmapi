// Screenshots of the New namespace form for the PR of #336: the reference and the company rules, 390/820/1440 px, light and
// dark. The built portal (dist/), the stand-in issuer and API of the portal's suite. A tall viewport, so the whole form fits.
// Run from cmapi-portal-ui/: node <this file> <out dir>
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { createRequire } from "node:module";
const app = process.cwd();
const { chromium } = createRequire(join(app, "package.json"))("playwright");
const { COMPANY_KEYS, REFERENCE_KEYS, servePortal, startApi, startIssuer, USERS } = await import(join(app, "tests/api/standin.mjs"));
const out = process.argv[2];
mkdirSync(out, { recursive: true });
let portal;
const issuer = await startIssuer({ redirectUris: () => [portal.page] });
const api = await startApi({ issuer, portalOrigin: () => portal.origin });
const CONFIG = { apiUrl: api.url, issuer: issuer.url, clientId: "cmapi-portal", audience: "cmapi-nonprod", instance: "nonprod", displayName: "Non-production", environments: ["rnd", "dev"], otherInstances: {} };
portal = await servePortal(join(app, "dist"), () => CONFIG);
const browser = await chromium.launch();
issuer.state.user = USERS.requester;
const shots = [];
try {
  for (const [name, keys, fill] of [
    ["reference", REFERENCE_KEYS, async (page) => {
      await page.getByLabel("Team (required)").fill("payments");
      await page.getByLabel("Team DL (required)").fill("payments-team@ephico2real.com");
      await page.getByRole("button", { name: "Optional labels (3)" }).click();
      await page.getByLabel("Justification").fill("Payments service dev namespace");
      await page.getByRole("button", { name: "Dry run" }).click();
      await page.getByText("Dry run passed · nothing written").waitFor();
    }],
    ["company", COMPANY_KEYS, async (page) => {
      await page.getByLabel("company.net/mnemonic (required)").fill("ABC");
      await page.getByLabel("company.net/lob (required)").fill("amgsst");
      await page.getByLabel("company.net/cl (required)").selectOption("1");
      await page.getByRole("button", { name: "Optional annotations (2)" }).click();
      await page.getByText(/^Not valid: must match/).waitFor();
    }]]) {
    for (const width of [390, 820, 1440]) {
      api.state.metadataKeys = keys;
      const context = await browser.newContext({ viewport: { width, height: width === 390 ? 4200 : 2600 } });
      const page = await context.newPage();
      await page.goto(`${portal.page}#new`);
      await page.getByRole("button", { name: "Dry run" }).waitFor();
      await fill(page);
      for (const theme of ["light", "dark"]) {
        await page.evaluate((dark) => document.documentElement.classList.toggle("pf-v6-theme-dark", dark), theme === "dark");
        await page.waitForTimeout(600);
        const file = join(out, `new-${name}-${width}-${theme}.png`);
        await page.screenshot({ path: file, fullPage: true });
        shots.push(file);
      }
      // The placeholder's colour, which axe does not measure (#336, design B, D12): read once and recorded.
      if (width === 1440) {
        const field = name === "reference" ? "Team DL (required)" : "company.net/mnemonic-confluence (optional)";
        const colours = await page.getByLabel(field).evaluate((el) => {
          let node = el;
          while (node && ["rgba(0, 0, 0, 0)", "transparent"].includes(getComputedStyle(node).backgroundColor)) node = node.parentElement;
          return { placeholder: getComputedStyle(el, "::placeholder").color, background: node ? getComputedStyle(node).backgroundColor : "none" };
        });
        console.log(name, "dark placeholder", JSON.stringify(colours));
        await page.evaluate(() => document.documentElement.classList.remove("pf-v6-theme-dark"));
        await page.waitForTimeout(600);
        console.log(name, "light placeholder", JSON.stringify(await page.getByLabel(field).evaluate((el) => {
          let node = el;
          while (node && ["rgba(0, 0, 0, 0)", "transparent"].includes(getComputedStyle(node).backgroundColor)) node = node.parentElement;
          return { placeholder: getComputedStyle(el, "::placeholder").color, background: node ? getComputedStyle(node).backgroundColor : "none" };
        })));
      }
      await context.close();
    }
  }
  console.log(`${shots.length} screenshots in ${out}; ${browser.version()}`);
} finally {
  await browser.close();
  portal.close(); api.close(); issuer.close();
}
