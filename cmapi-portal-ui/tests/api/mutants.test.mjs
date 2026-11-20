// Exercise the mutation driver without changing the developer's source tree or starting a browser.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const app = fileURLToPath(new URL("../../", import.meta.url));

test("a portal startup error cannot kill a mutant", () => {
  const output = join(app, "test-output");
  mkdirSync(output, { recursive: true });
  const root = mkdtempSync(join(output, "mutant-driver-"));
  try {
    cpSync(join(app, "src"), join(root, "src"), { recursive: true });
    const driver = join(root, "tests/api/mutants.mjs");
    mkdirSync(dirname(driver), { recursive: true });
    cpSync(join(app, "tests/api/mutants.mjs"), driver);
    const vite = join(root, "node_modules/.bin/vite");
    mkdirSync(dirname(vite), { recursive: true });
    writeFileSync(vite, "#!/bin/sh\nexit 0\n", { mode: 0o755 });
    writeFileSync(join(dirname(driver), "portal.test.mjs"), 'throw new Error("stand-in failed to start");');
    const run = spawnSync(process.execPath, [driver, "407:"], { cwd: root, encoding: "utf8" });
    assert.equal(run.status, 1, run.stdout);
    assert.match(run.stdout + run.stderr, /stand-in failed to start/);
    assert.doesNotMatch(run.stdout, /ok +407:/);
    assert.equal(readFileSync(join(root, "src/components/ui.tsx"), "utf8"), readFileSync(join(app, "src/components/ui.tsx"), "utf8"));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
