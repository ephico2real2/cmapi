// The client's cost on the large bodies of large.py: parse, compile every property's patterns once, test one value each.
import { readFileSync, readdirSync } from "node:fs";
const dir = new URL(".", import.meta.url);
for (const f of readdirSync(dir).filter((x) => /^large-.*\.json$/.test(x)).sort()) {
  const text = readFileSync(new URL(f, dir), "utf8");
  let t = performance.now(); const body = JSON.parse(text); const parse = performance.now() - t;
  t = performance.now(); let n = 0;
  for (const s of [body.labels, body.annotations]) for (const p of Object.values(s.properties)) for (const pat of [p.pattern, ...(p.allOf ?? []).map((x) => x.pattern)].filter(Boolean)) { new RegExp(pat, "u").test("abc-team@d7.example.com"); n++; }
  console.log(`${f}: parse ${parse.toFixed(1)} ms, compile+test ${n} patterns ${(performance.now() - t).toFixed(1)} ms`);
}
