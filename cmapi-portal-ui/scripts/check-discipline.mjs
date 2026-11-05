#!/usr/bin/env node
// PatternFly decides the look: app styles may not hard-code a colour, override a PatternFly class or force a rule.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const src = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const RULES = [
  [/#[0-9a-fA-F]{3,8}\b/, "a hex colour"],
  [/\.pf-v\d+-/, "an override of a PatternFly class"],
  [/!important/, "!important"]
];
const problems = [];
for (const entry of readdirSync(src, { recursive: true })) {
  if (!String(entry).endsWith(".css")) continue;
  readFileSync(join(src, entry), "utf8").split("\n").forEach((line, i) => {
    for (const [rule, what] of RULES) if (rule.test(line)) problems.push(`${entry}:${i + 1}: ${what}`);
  });
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log("ok - app styles use PatternFly tokens only");
