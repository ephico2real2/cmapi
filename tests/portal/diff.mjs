#!/usr/bin/env node
// Pixel-diffs two captures: node diff.mjs <reference-dir> <actual-dir> [diff-dir]
// Reference PNGs are named like the captures (nonprod-workflow.png). A view passes under 0.5% differing pixels.
// Where both sides also hold a .dom.txt, the table reports whether the rendered DOM is identical.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";
import { VIEWS, viewName } from "./views.mjs";

const LIMIT = 0.5;
const [refDir, actualDir, diffDir] = process.argv.slice(2);
if (!refDir || !actualDir) {
  console.error("usage: node diff.mjs <reference-dir> <actual-dir> [diff-dir]");
  process.exit(2);
}
if (diffDir) mkdirSync(diffDir, { recursive: true });

let failed = 0;
console.log("| View | Size (reference, actual) | Different | Result | DOM |\n| --- | --- | --- | --- | --- |");
for (const view of VIEWS) {
  const name = viewName(view);
  const refPath = join(refDir, `${name}.png`);
  if (!existsSync(refPath)) {
    failed++;
    console.log(`| ${name} | no reference | | FAIL | |`);
    continue;
  }
  const a = PNG.sync.read(readFileSync(refPath));
  const b = PNG.sync.read(readFileSync(join(actualDir, `${name}.png`)));
  const size = `${a.width}x${a.height}, ${b.width}x${b.height}`;
  // A size mismatch is a real difference: compare the shared area and count the rest as different.
  const width = Math.min(a.width, b.width);
  const height = Math.min(a.height, b.height);
  const crop = (png) => { const out = new PNG({ width, height }); PNG.bitblt(png, out, 0, 0, width, height, 0, 0); return out; };
  const diff = new PNG({ width, height });
  const shared = pixelmatch(crop(a).data, crop(b).data, diff.data, width, height, { threshold: 0.1 });
  const total = Math.max(a.width, b.width) * Math.max(a.height, b.height);
  const percent = ((shared + total - width * height) / total) * 100;
  const ok = percent < LIMIT;
  if (!ok) failed++;
  if (diffDir && shared) writeFileSync(join(diffDir, `${name}.png`), PNG.sync.write(diff));
  const domA = join(refDir, `${name}.dom.txt`);
  const domB = join(actualDir, `${name}.dom.txt`);
  const dom = existsSync(domA) && existsSync(domB) ? (readFileSync(domA, "utf8") === readFileSync(domB, "utf8") ? "identical" : "DIFFERS") : "";
  console.log(`| ${name} | ${size} | ${percent.toFixed(3)}% | ${ok ? "pass" : "FAIL"} | ${dom} |`);
}
process.exit(failed ? 1 : 0);
