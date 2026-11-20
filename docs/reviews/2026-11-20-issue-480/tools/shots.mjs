// Screenshots of the create operation in Swagger UI (/docs) and ReDoc (/redoc), in the installed Chrome, for the PR of #480.
// Prints what each control shows, so the PR quotes measured text, not the picture alone.
import { chromium } from "playwright";
const [base, out, scheme = "light"] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: scheme });
const log = (k, v) => console.log(`${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`);

// ---- Swagger UI
await page.goto(`${base}/docs#/namespaces/namespaces_create_namespace`);
const op = page.locator("#operations-namespaces-namespaces_create_namespace");
await op.locator(".opblock-body").waitFor({ timeout: 30000 });
await page.waitForTimeout(1500);
await op.locator(".opblock-section").first().screenshot({ path: `${out}/swagger-1-parameters.png` });
await op.locator(".opblock-section-request-body").screenshot({ path: `${out}/swagger-2-request-body.png` });
for (const [code, pick] of [["409", "idempotency-replay"], ["422", "policy-violation"], ["503", "idp-unavailable"]]) {
  const row = op.locator(`tr.response[data-code="${code}"]`);
  const select = row.locator(".examples-select select");
  log(`swagger ${code} examples`, await select.locator("option").allTextContents());
  await select.selectOption({ label: pick });
  await page.waitForTimeout(300);
  log(`swagger ${code} shows`, (await row.locator(".highlight-code, pre").first().innerText()).replace(/\s+/g, " ").slice(0, 160));
  await row.screenshot({ path: `${out}/swagger-3-response-${code}.png` });
}
await op.locator(".responses-wrapper").screenshot({ path: `${out}/swagger-4-responses.png` });
const ext = op.locator(".opblock-section").filter({ hasText: "Extensions" }).last();
log("swagger extensions", (await ext.innerText()).replace(/\s+/g, " ").slice(0, 300));
await ext.screenshot({ path: `${out}/swagger-5-extensions.png` });

// ---- ReDoc
await page.goto(`${base}/redoc#tag/namespaces/operation/namespaces_create_namespace`);
await page.getByText("Create a namespace", { exact: true }).first().waitFor();
await page.waitForTimeout(3000);
const head = page.locator('[id="namespaces/namespaces_create_namespace"]');
await head.scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/redoc-1-operation.png` });
const resp = page.locator('[id="namespaces/namespaces_create_namespace/responses"]');
log("redoc status tabs", await resp.getByRole("tab").allTextContents());
for (const code of ["409", "422"]) {
  await resp.getByRole("tab", { name: code, exact: true }).click();
  await page.waitForTimeout(800);
  await resp.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -60));
  await page.waitForTimeout(500);
  log(`redoc ${code} body`, (await resp.innerText()).replace(/\s+/g, " ").slice(0, 300));
  await page.screenshot({ path: `${out}/redoc-2-response-${code}.png` });
}
await browser.close();
