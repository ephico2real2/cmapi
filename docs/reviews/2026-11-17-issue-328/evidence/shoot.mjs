// #328 screenshots: cmapi's own /docs (Swagger UI 5.34.1) on a local run, the New namespace (create) request body,
// Schema tab, labels and annotations expanded. Usage: node shoot.mjs <base-url> <tag>
import { chromium } from "/Users/olasumbo/gitRepos/cmapi-design/tests/portal/node_modules/playwright/index.mjs";
const [base, tag] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, colorScheme: "light" });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(`${base}/docs#/namespaces/namespaces_create_namespace`);
const op = page.locator("#operations-namespaces-namespaces_create_namespace");
await op.waitFor({ timeout: 30000 });
if (!(await op.locator(".opblock-body").count())) await op.locator(".opblock-summary").first().click();
await op.locator(".opblock-body").waitFor();
const body = op.locator(".opblock-section-request-body");
const schemaTab = body.locator("button[data-name=model], button:has-text('Schema')").first();
if (await schemaTab.count()) await schemaTab.click();
for (const f of ["labels", "annotations"]) {
  const li = body.locator("li.json-schema-2020-12-property").filter({ has: page.locator(":scope > article > .json-schema-2020-12-head .json-schema-2020-12__title", { hasText: new RegExp(`^${f}$`) }) }).first();
  if (await li.count()) await li.locator(".json-schema-2020-12-expand-deep-button").first().click();
}
await page.waitForTimeout(500);
await body.screenshot({ path: `shots/swagger-${tag}-new-namespace-schema.png` });
const text = await body.innerText();
const ex = body.locator("button[data-name=example], button:has-text('Example Value')").first();
if (await ex.count()) await ex.click();
await op.locator("button.try-out__btn").click();
const ta = op.locator("textarea.body-param__text");
await ta.waitFor();
const tried = await ta.inputValue();
await body.screenshot({ path: `shots/swagger-${tag}-new-namespace-tryitout.png` });
console.log(JSON.stringify({ tag, errors, tried: JSON.parse(tried), required: (text.match(/\*/g) || []).length, schemaText: text.slice(0, 3000) }, null, 1));
await browser.close();
