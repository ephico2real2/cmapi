// Screenshots of the change operation (PATCH) in Swagger UI (/docs) and ReDoc (/redoc), in the installed Chrome, for the PR of #485.
// Prints what each control shows, so the PR quotes measured text, not the picture alone.
import assert from "node:assert/strict";
import { chromium } from "playwright";
const [base, out, scheme = "light"] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: scheme });
const log = (k, v) => console.log(`${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`);

// ---- Swagger UI
await page.goto(`${base}/docs#/namespaces/namespaces_update_namespace`);
const op = page.locator("#operations-namespaces-namespaces_update_namespace");
await op.locator(".opblock-body").waitFor({ timeout: 30000 });
await page.waitForTimeout(1500);
await op.locator(".opblock-section").first().screenshot({ path: `${out}/swagger-1-parameters.png` });
const bodySelect = op.locator(".opblock-section-request-body .examples-select select");
log("swagger request body examples", await bodySelect.locator("option").allTextContents());
log("swagger request body shows", (await op.locator(".opblock-section-request-body .highlight-code, .opblock-section-request-body pre").first().innerText()).replace(/\s+/g, " ").slice(0, 300).trimEnd());
await op.locator(".opblock-section-request-body").screenshot({ path: `${out}/swagger-2-request-body.png` });
for (const [code, pick] of [["409", "change-pending"], ["412", "precondition-failed"], ["422", "policy-violation"], ["428", "precondition-required"]]) {
  const row = op.locator(`tr.response[data-code="${code}"]`);
  const select = row.locator(".examples-select select");
  if (await select.count()) {        // a status with one example has no menu
    log(`swagger ${code} examples`, await select.locator("option").allTextContents());
    await select.selectOption({ label: pick });
  }
  await page.waitForTimeout(300);
  log(`swagger ${code} shows`, (await row.locator(".highlight-code, pre").first().innerText()).replace(/\s+/g, " ").slice(0, 160).trimEnd());
  await row.screenshot({ path: `${out}/swagger-3-response-${code}.png` });
}
await op.locator(".responses-wrapper").screenshot({ path: `${out}/swagger-4-responses.png` });
const ext = op.locator(".opblock-section").filter({ hasText: "Extensions" }).last();
log("swagger extensions", (await ext.innerText()).replace(/\s+/g, " ").slice(0, 300));
await ext.screenshot({ path: `${out}/swagger-5-extensions.png` });

// ---- ReDoc
await page.goto(`${base}/redoc#tag/namespaces/operation/namespaces_update_namespace`);
await page.getByText("Change a namespace", { exact: true }).first().waitFor();
await page.waitForTimeout(3000);
const head = page.locator('[id="namespaces/namespaces_update_namespace"]');
await head.scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/redoc-1-operation.png` });
const resp = page.locator('[id="namespaces/namespaces_update_namespace/responses"]');
log("redoc status tabs", await resp.getByRole("tab").allTextContents());
// The response samples (right column): one button per status, then ReDoc's Example menu, which ReDoc 3.1.0 shows for a
// status with two examples or more. Each pick must change the sample's body, not only the menu's label.
const example = head.getByRole("button", { name: "Example", exact: true }).last();
// ReDoc shows the Example menu for two examples or more; a status with one has none, and the last menu is the request's.
for (const [code, pick, many] of [["403", "environment-forbidden", true], ["409", "change-pending", true],
                                  ["412", "precondition-failed", false], ["422", "policy-violation", true],
                                  ["428", "precondition-required", false]]) {
  await head.locator('button:not([role="tab"])', { hasText: new RegExp(`^${code}$`) }).click();
  if (many) {
    await example.click();
    log(`redoc ${code} examples`, await page.getByRole("menuitem").allTextContents());
    await page.getByRole("menuitem", { name: pick, exact: true }).click();
  }
  await page.waitForTimeout(300);
  const body = await head.locator("pre").last().innerText();
  assert.ok(body.replace(/\s+/g, "").includes(`"code":"${pick}"`), `ReDoc ${code} did not show ${pick}: ${body.slice(0, 200)}`);
  log(`redoc ${code} shows`, body.replace(/\s+/g, " ").slice(0, 160).trimEnd());
  await head.locator("pre").last().scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${out}/redoc-2-response-${code}.png` });
}
await browser.close();
