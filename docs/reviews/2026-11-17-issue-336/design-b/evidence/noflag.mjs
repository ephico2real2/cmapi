// The same pattern verdicts as client_check.mjs, without the u flag (code units, not code points), against RE2.
import { readFileSync } from "node:fs";
const { cases } = JSON.parse(readFileSync(new URL("corpus.json", import.meta.url), "utf8"));
let n = 0, diff = [];
for (const c of cases) for (const [p, re2] of Object.entries(c.re2)) { n++; const js = new RegExp(p).test(c.value); if (js !== re2) diff.push([c.key, c.value, js, re2]); }
console.log(`without u: ${n} checks, ${diff.length} differ from RE2`);
for (const d of diff.slice(0, 8)) console.log("  ", JSON.stringify(d));
