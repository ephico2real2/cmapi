// Screenshots of the create operation in Swagger UI (/docs) and ReDoc (/redoc), in the installed Chrome, for the PR of #480.
// Prints what each control shows, so the PR quotes measured text, not the picture alone.
import assert from "node:assert/strict";
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
  log(`swagger ${code} shows`, (await row.locator(".highlight-code, pre").first().innerText()).replace(/\s+/g, " ").slice(0, 160).trimEnd());
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
// The response samples (right column): one button per status, then ReDoc's Example menu, which ReDoc 3.1.0 shows for a
// status with two examples or more. Each pick must change the sample's body, not only the menu's label.
const example = head.getByRole("button", { name: "Example", exact: true }).last();
for (const [code, pick] of [["403", "environment-forbidden"], ["409", "idempotency-replay"],
                            ["422", "policy-violation"], ["503", "idp-unavailable"]]) {
  await head.locator('button:not([role="tab"])', { hasText: new RegExp(`^${code}$`) }).click();
  await example.click();
  log(`redoc ${code} examples`, await page.getByRole("menuitem").allTextContents());
  await page.getByRole("menuitem", { name: pick, exact: true }).click();
  await page.waitForTimeout(300);
  const body = await example.evaluate((el) => {
    let panel = el;
    while (panel && !panel.querySelector("pre")) panel = panel.parentElement;
    return panel.querySelector("pre").innerText;
  });
  assert.ok(body.replace(/\s+/g, "").includes(`"code":"${pick}"`), `ReDoc ${code} did not show ${pick}: ${body.slice(0, 200)}`);
  log(`redoc ${code} shows`, body.replace(/\s+/g, " ").slice(0, 160).trimEnd());
  await example.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${out}/redoc-2-response-${code}.png` });
}
await browser.close();
