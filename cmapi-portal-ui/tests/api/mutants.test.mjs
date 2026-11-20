// Exercise the mutation driver without changing the developer's source tree or starting a browser.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const app = fileURLToPath(new URL("../../", import.meta.url));

function withDriver(suite, verify) {
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
    writeFileSync(join(dirname(driver), "portal.test.mjs"), suite);
    const run = spawnSync(process.execPath, [driver, "407:"], { cwd: root, encoding: "utf8" });
    verify(run, root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test("a portal startup error cannot kill a mutant", () => {
  withDriver('throw new Error("stand-in failed to start");', (run, root) => {
    assert.equal(run.status, 1, run.stdout);
    assert.match(run.stdout + run.stderr, /stand-in failed to start/);
    assert.doesNotMatch(run.stdout, /ok +407:/);
    assert.equal(readFileSync(join(root, "src/components/ui.tsx"), "utf8"), readFileSync(join(app, "src/components/ui.tsx"), "utf8"));
  });
});

test("the mutation driver selects each paged list's check for its own broken pager", () => {
  // Record which check the driver selected when each real source-file edit was present.
  const files = ["RequestsTab", "ExpirationTab", "PoliciesTab"];
  const suite = `
    import { appendFileSync, readFileSync } from "node:fs";
    for (const file of ${JSON.stringify(files)}) {
      const source = readFileSync("src/portal/" + file + ".tsx", "utf8");
      for (const [index, block] of [...source.matchAll(/<Pager\\s+([^>]*?)range=/g)].entries()) {
        if (!block[1].includes("busy={false}")) continue;
        appendFileSync("edits.jsonl", JSON.stringify([file, index, process.env.CHECK]) + "\\n");
      }
    }
    console.log("ok - " + process.env.CHECK);
  `;
  withDriver(suite, (run, root) => {
    // The recording suite passes every edit, so the driver must report survivors.
    assert.equal(run.status, 1, run.stdout);
    const edits = readFileSync(join(root, "edits.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line));
    assert.deepEqual(edits, [
      ["RequestsTab", 0, "407 Requests keeps"],
      ["ExpirationTab", 0, "407 Expiration keeps"],
      ["PoliciesTab", 0, "407 Policies results"],
      ["PoliciesTab", 1, "407 Policies refusals"]
    ]);
  });
});
