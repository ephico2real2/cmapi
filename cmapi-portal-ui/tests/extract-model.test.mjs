#!/usr/bin/env node
// Runs the real extractor on variants of Main.dc.html, in a throwaway tree, and reads what it generated.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const app = join(dirname(fileURLToPath(import.meta.url)), "..");
const main = readFileSync(join(app, "..", "mockups", "portal", "Main.dc.html"), "utf8");
const root = mkdtempSync(join(tmpdir(), "extract-model-"));
mkdirSync(join(root, "app", "scripts"), { recursive: true });
mkdirSync(join(root, "app", "src", "model"), { recursive: true });
mkdirSync(join(root, "mockups", "portal"), { recursive: true });
cpSync(join(app, "scripts", "extract-model.mjs"), join(root, "app", "scripts", "extract-model.mjs"));

function extract(variant) {
  writeFileSync(join(root, "mockups", "portal", "Main.dc.html"), variant);
  const run = spawnSync("node", [join(root, "app", "scripts", "extract-model.mjs")], { encoding: "utf8" });
  if (run.status !== 0) return { error: run.stderr };
  const generated = readFileSync(join(root, "app", "src", "model", "logic.generated.js"), "utf8");
  const line = generated.split("\n").find((l) => l.startsWith("export const PROPS = "));
  return { generated, props: line.slice("export const PROPS = ".length, -1) };
}
const withHelp = (help) => main.replace('"default":"nonprod"}', `"default":"nonprod","help":${help}}`);

try {
  const plain = extract(main);
  assert.deepEqual(JSON.parse(plain.props).instance.options, ["nonprod", "staging", "prod"], "this file extracts");
  assert.equal(JSON.parse(extract(withHelp('"a &amp; b"')).props).instance.help, "a & b", "an entity in data-props is decoded, as dc-lite decodes it");
  assert.equal(JSON.parse(extract(withHelp('"it&#39;s"')).props).instance.help, "it's", "a numeric entity too");
  const quoted = main.replace(/data-props='([^']*)'/, (m, json) => `data-props="${json.replace(/"/g, "&quot;")}"`);
  assert.deepEqual(JSON.parse(extract(quoted).props), JSON.parse(plain.props), "a double-quoted, entity-escaped attribute reads the same");
  assert.equal(JSON.parse(extract(withHelp('"a > b"')).props).instance.help, "a > b", "a > inside the attribute does not end the tag");
  assert.match(extract(withHelp("(globalThis.PWNED=1)")).error ?? "", /JSON/, "code in data-props is refused, not inlined");
  const mentioned = main.replace("<x-dc>", "<!-- logic lives in data-dc-script below --><x-dc>");
  assert.equal(extract(mentioned).generated, plain.generated, "the words data-dc-script elsewhere are not the tag");
  const trailing = main.replace("</body>", "<script>/* analytics */</script></body>");
  assert.equal(extract(trailing).generated, plain.generated, "a script after the logic stays out of the module");
  console.log("ok - extract-model");
} finally {
  rmSync(root, { recursive: true, force: true });
}
