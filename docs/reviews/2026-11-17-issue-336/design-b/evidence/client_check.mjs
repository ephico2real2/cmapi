// The proposed client check (design.md, "Client-side checks") run on corpus.json, against the validator's verdict.
// Also: each schema pattern in ECMA-262 with the u flag against RE2, and whether it compiles with the v flag, which the
// HTML pattern attribute uses (HTML Living Standard, "The pattern attribute": compiled with the v flag).
// Run: node client_check.mjs
import { readFileSync } from "node:fs";
const here = new URL(".", import.meta.url);
const { cases } = JSON.parse(readFileSync(new URL("corpus.json", here), "utf8"));
const responses = Object.fromEntries(["reference", "company"].map((n) => [n, JSON.parse(readFileSync(new URL(`response-${n}.json`, here), "utf8"))]));

/** The client's verdict on one value of one declared key: the schema keywords that the form reads. */
export function clientCheck(prop, value, required) {
  if (value === "") return required ? "required" : null;          // an empty optional key is not sent
  const chars = [...value].length;                                // JSON Schema counts characters (code points)
  if (prop.maxLength !== undefined && chars > prop.maxLength) return "maxLength";
  if (prop.minLength !== undefined && chars < prop.minLength) return "minLength";
  if (prop.enum && !prop.enum.includes(value)) return "enum";
  for (const p of [prop.pattern, ...(prop.allOf ?? []).map((s) => s.pattern)].filter(Boolean)) {
    if (!new RegExp(p, "u").test(value)) return "pattern";
  }
  return null;
}

let stricter = [], looser = [], agree = 0, patternDiff = [], patternChecks = 0;
for (const c of cases) {
  const schema = responses[c.config][c.kind === "label" ? "labels" : "annotations"];
  const prop = schema.properties[c.key];
  const client = clientCheck(prop, c.value, c.required);
  if (client && c.server_ok) stricter.push({ ...c, client });
  else if (!client && !c.server_ok) looser.push({ ...c, client });
  else agree++;
  for (const [p, re2] of Object.entries(c.re2)) {
    patternChecks++;
    const js = new RegExp(p, "u").test(c.value);
    if (js !== re2) patternDiff.push({ config: c.config, key: c.key, value: c.value, js, re2 });
  }
}
console.log(`cases ${cases.length}: agree ${agree}, client stricter than the validator ${stricter.length}, client looser ${looser.length}`);
console.log(`pattern verdicts ECMA-262 (u) vs RE2: ${patternChecks} checks, ${patternDiff.length} differ`);
const show = (xs) => xs.slice(0, 12).map((x) => JSON.stringify({ config: x.config, key: x.key, value: x.value, server: x.server_codes, client: x.client, js: x.js, re2: x.re2 })).join("\n");
if (stricter.length) console.log("STRICTER:\n" + show(stricter));
if (patternDiff.length) console.log("PATTERN DIFF:\n" + show(patternDiff));
const looseKinds = {};
for (const x of looser) { const k = `${x.config} ${x.key} ${x.server_codes.join(",")} [${JSON.stringify([...x.value].some((ch) => { const cp = ch.codePointAt(0); return cp >= 0xd800 && cp <= 0xdfff; }) ? "lone surrogate" : x.value)}]`; looseKinds[k] = (looseKinds[k] ?? 0) + 1; }
console.log("LOOSER (the server refuses, the client lets through):");
for (const [k, n] of Object.entries(looseKinds)) console.log(`  ${n} x ${k}`);

// Every pattern of both responses, with the u flag and with the v flag.
const pats = new Map();
const walk = (node, where) => {
  if (Array.isArray(node)) return node.forEach((x, i) => walk(x, `${where}[${i}]`));
  if (node && typeof node === "object") for (const [k, v] of Object.entries(node)) { if (k === "pattern") pats.set(`${where}`, v); else walk(v, `${where}.${k}`); }
};
for (const [n, r] of Object.entries(responses)) walk(r, n);
const uniq = [...new Set(pats.values())];
let uFail = 0, vFail = [];
for (const p of uniq) {
  try { new RegExp(p, "u"); } catch (e) { uFail++; console.log("u fails", p.slice(0, 60), e.message); }
  try { new RegExp(`^(?:${p})$`, "v"); } catch (e) { vFail.push([p, e.message]); }
}
console.log(`distinct patterns ${uniq.length}: compile with u: ${uniq.length - uFail}; fail with v (the HTML pattern attribute): ${vFail.length}`);
for (const [p, msg] of vFail) console.log(`  v-flag refuses ${JSON.stringify(p.slice(0, 70))}${p.length > 70 ? "…" : ""}: ${msg}`);
