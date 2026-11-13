#!/usr/bin/env node
// Runs Main.dc.html's logic class with no browser: scenarios, role behaviour and list paging on each instance.
// Also checks the two promises the standalone build makes: ES2019 syntax, and a dist file that is up to date.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parse } from "acorn";
import { repoRoot } from "./views.mjs";

const portal = join(repoRoot, "mockups", "portal");
const source = readFileSync(join(portal, "Main.dc.html"), "utf8");
const script = source.slice(source.indexOf(">", source.indexOf("data-dc-script")) + 1, source.lastIndexOf("</script>"));

class DCLogic {
  constructor(props) { this.props = props || {}; this.state = {}; }
  setState(patch) { this.state = { ...this.state, ...patch }; }
}
const Component = new Function("DCLogic", `${script}\n;return Component;`)(DCLogic);
const INSTANCES = ["nonprod", "staging", "prod"];
const make = (instance, startTab = "workflow") => new Component({ instance, startTab });

let passed = 0;
function test(name, fn) {
  fn();
  passed++;
  console.log(`ok - ${name}`);
}

function walkScenario(c) {
  const seen = [];
  for (;;) {
    const { wf, wfNext } = c.renderVals();
    seen.push(wf);
    if (wf.atEnd) return seen;
    wfNext();
  }
}

function pageRows(c) {
  const v = c.renderVals();
  return { rows: v.quotas.map((q) => `${q.cluster}/${q.ns}`), page: v.qPage };
}

test("every instance opens with scenarios that run start to end", () => {
  for (const instance of INSTANCES) {
    const c = make(instance);
    const scenarios = c.renderVals().wf.scenarios;
    assert.ok(scenarios.length > 0, instance);
    for (const scenario of scenarios) {
      const pick = c.renderVals().wf.scenarios.find((s) => s.label === scenario.label);
      pick.pick();
      const steps = walkScenario(c);
      assert.ok(steps.length > 1, scenario.label);
      assert.equal(steps[0].atStart, true, scenario.label);
    }
  }
});

test("the AI agent scenario has 13 steps, acts as bot-user, and ends refused with 403", () => {
  const c = make("nonprod");
  c.renderVals().wf.scenarios.find((s) => s.label === "AI agent onboards · rnd").pick();
  const steps = walkScenario(c);
  assert.equal(steps.length, 13);
  const text = JSON.stringify(steps);
  assert.match(text, /bot-user/);
  assert.match(text, /cmapi-onboarding/);
  const last = JSON.stringify(steps[12].detail);
  assert.match(last, /403/);
  assert.match(last, /forbidden/);
});

test("only the nonprod instance offers the AI agent scenario", () => {
  const offered = (instance) => make(instance).renderVals().wf.scenarios.some((s) => /AI agent/.test(s.label));
  assert.deepEqual(INSTANCES.map(offered), [true, false, false]);
});

test("each instance's wrong-environment scenario returns 422 environment-not-served", () => {
  for (const instance of INSTANCES) {
    const c = make(instance);
    c.openScn(`wrong-${instance}`);
    assert.match(JSON.stringify(walkScenario(c)), /environment-not-served/, instance);
  }
});

test("quota paging visits every row once, in order, and comes back to the same pages", () => {
  for (const instance of INSTANCES) {
    const c = make(instance, "quotas");
    const pages = [];
    for (;;) {
      const { rows, page } = pageRows(c);
      assert.ok(rows.length > 0 && rows.length <= 50, `${instance}: page size ${rows.length}`);
      pages.push(rows);
      if (page.nextDis === "true") break;
      page.next();
    }
    assert.ok(pages.length > 1, `${instance} should need more than one page`);
    const all = pages.flat();
    assert.equal(new Set(all).size, all.length, `${instance}: a row appeared twice`);
    const total = Number(/of ([\d,]+)/.exec(pageRows(c).page.range)[1].replace(/,/g, ""));
    assert.equal(all.length, total, `${instance}: the range's total`);

    for (let i = pages.length - 2; i >= 0; i--) {
      pageRows(c).page.prev();
      assert.deepEqual(pageRows(c).rows, pages[i], `${instance}: page ${i} going back`);
    }
    assert.equal(pageRows(c).page.prevDis, "true");
  }
});

test("a letter jump opens at the first namespace with that letter", () => {
  const c = make("nonprod", "quotas");
  const letter = c.renderVals().qAz.filter((l) => l.dis !== "true" && l.dis !== true)[3];
  letter.pick();
  const first = c.renderVals().quotas[0].ns;
  assert.equal(first[0].toLowerCase(), letter.t.toLowerCase());
});

test("a namespace's lock shows the same approval count as its request (#148)", () => {
  // The Approvals tab holds how many approvals a request needs. The Requests tab repeats it as text for the requests that it lists.
  const need = new Map([...source.matchAll(/\{ id: "(req-[^"]+)", title:[^\n]*? need: (\d+),/g)].map((m) => [m[1], m[2]]));
  const listed = new Map([...source.matchAll(/\{ id: "(req-[^"]+)", cluster:[^\n]*? approval: "([^"]+)"/g)].map((m) => [m[1], m[2]]));
  const locks = [...source.matchAll(/lock: \{ id: "(req-[^"]+)",[^}]*? approval: "([^"]+)" \}/g)];
  assert.ok(locks.length > 0 && need.size > 0 && listed.size > 0, "no lock or no request found: the patterns no longer match the data");
  for (const [, id, approval] of locks) {
    assert.ok(need.has(id) || listed.has(id), `the lock names ${id}, which is on neither the Approvals tab nor the Requests tab`);
    if (need.has(id)) assert.match(approval, new RegExp(` of ${need.get(id)}$`), `the lock of ${id} against the ${need.get(id)} approvals that it needs`);
    if (listed.has(id)) assert.equal(approval, listed.get(id), `the lock of ${id} against the Requests tab`);
  }
});

test("the standalone runtime parses as ES2019", () => {
  parse(readFileSync(join(portal, "runtime", "dc-lite.js"), "utf8"), { ecmaVersion: 2019 });
});

test("dist/portal.html is built from the current sources", () => {
  execFileSync("node", [join(repoRoot, "scripts", "build-portal.mjs"), "--check"], { stdio: "pipe" });
});

console.log(`${passed} passed`);
