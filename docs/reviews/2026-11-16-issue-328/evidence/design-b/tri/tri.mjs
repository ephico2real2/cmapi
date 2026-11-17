// ECMA-262 (u flag, as ajv) on tri_corpus.py's regexes; prints each verdict that differs from Python's.
import { readFileSync } from "node:fs";
const { regexes, corpus, python } = JSON.parse(readFileSync(process.argv[2], "utf8"));
let n = 0, bad = 0;
for (const [name, rx] of Object.entries(regexes)) {
  const re = new RegExp(rx, "u");
  corpus.forEach((s, i) => { n++; if (re.test(s) !== python[name][i]) { bad++; console.log("ECMA differs", name, JSON.stringify(s), re.test(s)); } });
}
console.log(`ecma: ${n} verdicts, ${bad} differ from python`);
