// What the acceptance test captures, and how to reach it. Views are reached by clicking the portal's own
// instance and tab buttons, so one driver works on any runtime that renders Main.dc.html.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

export const TABS = { workflow: "Workflow", new: "New namespace", quotas: "Quotas", expiration: "Expiration", requests: "Requests", approvals: "Approvals", policies: "Policies", capacity: "Capacity", kpis: "KPIs" };
export const INSTANCES = { nonprod: "nonprod", staging: "staging", prod: "prod" };

export const VIEWS = [
  ...Object.keys(TABS).map((tab) => ({ instance: "nonprod", tab })),
  ...["staging", "prod"].flatMap((instance) => ["workflow", "quotas"].map((tab) => ({ instance, tab })))
];

export const viewName = (view) => `${view.instance}-${view.tab}`;
export const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
export const distPage = join(repoRoot, "mockups", "portal", "dist", "portal.html");

export async function gotoView(page, view) {
  await page.locator(".instbar").getByRole("button", { name: new RegExp(`^${INSTANCES[view.instance]}`) }).click();
  await page.locator("nav.tabs").getByRole("button", { name: new RegExp(`^${TABS[view.tab]}`) }).click();
  await page.evaluate(() => document.fonts.ready);
}

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".css": "text/css" };

export function serve(dir) {
  const server = createServer(async (req, res) => {
    const path = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname)).replace(/^(\.\.[/\\])+/, "");
    try {
      const body = await readFile(join(dir, path));
      res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" });
      res.end(body);
    } catch {
      res.writeHead(404);
      res.end();
    }
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ port: server.address().port, close: () => server.close() })));
}

// Runs in the page. Gives a canonical form of the rendered tree, so two runtimes can be compared as DOM.
// data-dc-tpl and data-sc-name are the canvas editor's bookkeeping, not part of what renders.
export function canonicalDom() {
  const SKIP = new Set(["data-dc-tpl", "data-sc-name"]);
  const walk = (node) => {
    if (node.nodeType === Node.TEXT_NODE) return node.nodeValue;
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    const attrs = Array.from(node.attributes).filter((a) => !SKIP.has(a.name) && !(a.name === "value" && node.tagName === "INPUT"))
      .map((a) => [a.name, a.name === "style" ? node.style.cssText : a.value])
      .filter((a) => !(a[0] === "style" && a[1] === ""))
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map((a) => `${a[0]}="${a[1]}"`);
    if ("value" in node && /^(INPUT|TEXTAREA|SELECT)$/.test(node.tagName)) attrs.push(`.value="${node.value}"`);
    if (node.disabled === true) attrs.push(".disabled");
    return `<${node.localName}${attrs.length ? " " + attrs.join(" ") : ""}>${Array.from(node.childNodes).map(walk).join("")}</${node.localName}>`;
  };
  return Array.from(document.querySelector("#dc-root .sc-host").childNodes).map(walk).join("");
}
