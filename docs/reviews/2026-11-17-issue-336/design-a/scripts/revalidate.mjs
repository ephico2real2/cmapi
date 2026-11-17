// Design 336-A: does a browser revalidate a cross-origin fetch that carries Authorization, when the API answers
// Cache-Control: no-cache with a strong ETag? The portal's premise for the caching decision. Loopback only.
import { createServer } from "node:http";
import { createRequire } from "node:module";
const require = createRequire("/Users/olasumbo/gitRepos/cmapi-design/cmapi-portal-ui/package.json");
const { chromium } = require("playwright");
const BODY = JSON.stringify({ labels: { type: "object" } }), ETAG = '"abc123"';
const seen = [];
const listen = (s) => new Promise((r) => s.listen(0, "127.0.0.1", () => r(s.address().port)));
const page = createServer((q, s) => { s.writeHead(200, { "content-type": "text/html" }); s.end("<!doctype html><title>p</title>"); });
let pagePort;
const api = createServer((q, s) => {
  const cors = { "access-control-allow-origin": `http://127.0.0.1:${pagePort}`, "access-control-allow-headers": "authorization", "access-control-expose-headers": "etag", vary: "origin" };
  if (q.method === "OPTIONS") { s.writeHead(204, cors); return s.end(); }
  seen.push({ method: q.method, ifNoneMatch: q.headers["if-none-match"] ?? null, auth: Boolean(q.headers.authorization) });
  const h = { ...cors, etag: ETAG, "cache-control": "no-cache" };
  if (q.headers["if-none-match"] === ETAG) { s.writeHead(304, h); return s.end(); }
  s.writeHead(200, { ...h, "content-type": "application/json" }); s.end(BODY);
});
pagePort = await listen(page); const apiPort = await listen(api);
const browser = await chromium.launch();
const p = await (await browser.newContext()).newPage();
await p.goto(`http://127.0.0.1:${pagePort}/`);
const results = await p.evaluate(async (url) => {
  const out = [];
  for (let i = 0; i < 2; i++) {
    const r = await fetch(url, { headers: { Authorization: "Bearer t" }, credentials: "omit" });
    out.push({ status: r.status, etag: r.headers.get("etag"), body: await r.text() });
  }
  return out;
}, `http://127.0.0.1:${apiPort}/api/v1/metadata-keys`);
console.log("browser", browser.version());
console.log("what the page's fetch saw:", JSON.stringify(results));
console.log("what the API saw:", JSON.stringify(seen.filter((x) => x.method === "GET")));
await browser.close(); page.close(); api.close();
