// Design 336-A: the client leg. The served create schema of each config, read by @cfworker/json-schema 4.1.6 (no eval,
// RegExp with the u flag), plus the form's one extra check (x-cmapi-namespace-prefix against the namespace), on the
// create corpus of tests/core with validate()'s verdict. Unsound = the server accepts and the client refuses (must be 0).
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(process.argv[2] + "/");
const { Validator } = require("@cfworker/json-schema");
const NS = { reference: "payments-dev", company: "abc-rnd" };
for (const name of ["reference", "company"]) {
  const corpus = JSON.parse(readFileSync(new URL(`../evidence/corpus-${name}.json`, import.meta.url), "utf8"));
  const v = { label: new Validator(corpus.schema.labels, "2020-12", false), annotation: new Validator(corpus.schema.annotations, "2020-12", false) };
  // Every pattern in the schema compiles in ECMA-262 with the u flag.
  const patterns = [];
  JSON.stringify(corpus.schema, (k, val) => { if (k === "pattern") patterns.push(val); return val; });
  patterns.forEach((p) => new RegExp(p, "u"));
  const t = { total: 0, accepted: 0, agree: 0, unsound: [], loose: {} };
  for (const row of corpus.rows) {
    const schema = row.kind === "label" ? corpus.schema.labels : corpus.schema.annotations;
    const r = v[row.kind].validate(row.body);
    const prefixKey = Object.entries(schema.properties).find(([, s]) => s["x-cmapi-namespace-prefix"])?.[0];
    const prefixBad = prefixKey && row.body[prefixKey] && !NS[name].startsWith(`${row.body[prefixKey]}-`);
    // The form's limits on the other keys, read from x-cmapi-other-keys (the same generator).
    const lim = schema["x-cmapi-other-keys"], others = Object.entries(row.body).filter(([k]) => !(k in schema.properties));
    const bytes = others.map(([, val]) => new TextEncoder().encode(val).length);
    const overLimits = others.length > lim.max || (lim.maxValueBytes !== undefined && (bytes.some((b) => b > lim.maxValueBytes) || bytes.reduce((a, b) => a + b, 0) > lim.maxBytesTotal));
    const refused = !r.valid || prefixBad || (process.argv[3] === "limits" && overLimits);
    t.total++; t.accepted += row.accepted;
    if (row.accepted && refused) t.unsound.push({ body: row.body, errors: r.errors.slice(0, 2).map((e) => `${e.keywordLocation} ${e.instanceLocation}`) });
    else if (!row.accepted && !refused) { const k = row.codes.join("+"); t.loose[k] = (t.loose[k] ?? 0) + 1; }
    else t.agree++;
  }
  console.log(`${name}: ${patterns.length} patterns compile with u; ${t.total} create maps, ${t.accepted} accepted by validate(); `
    + `client agrees on ${t.agree}; unsound (server accepts, client refuses) ${t.unsound.length}; loose (client lets through, server refuses) ${JSON.stringify(t.loose)}`);
  for (const u of t.unsound.slice(0, 5)) console.log("  UNSOUND", JSON.stringify(u));
}
