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
    // A lock can add where the request stands after its approval text, as in "auto: expired-namespace · awaiting prune confirmation".
    if (listed.has(id)) assert.ok(approval.startsWith(listed.get(id)), `the lock of ${id} says "${approval}", and the Requests tab says "${listed.get(id)}"`);
  }
});

test("each KPI card has the name of a KPI of docs/17-kpis.md (#175)", () => {
  const defined = new Set([...readFileSync(join(repoRoot, "docs", "17-kpis.md"), "utf8").matchAll(/^\| `[a-z0-9-]+` \| ([^|]+) \|/gm)].map((m) => m[1].trim()));
  assert.ok(defined.size >= 15, "the KPI table of docs/17 was not found");
  // docs/17 has the two percentiles of the approval turnaround as two KPIs, and a card shows them together.
  const known = (name) => defined.has(name) || (name === "Approval turnaround (p50 / p90)" && defined.has("Approval turnaround (p50)") && defined.has("Approval turnaround (p90)"));
  const cards = [...source.matchAll(/^    kpi\("([^"]+)",/gm)].map((m) => m[1]);
  assert.ok(cards.length >= 25, "the KPI cards of the mockup were not found");
  assert.deepEqual(cards.filter((name) => !known(name)), []);
});

// #537: the Policies tab's sections open and close, and Results by policy, the long list, is last, closed and paged.
const pageSlots = new Function("DCLogic", `${script}\n;return pageSlots;`)(DCLogic);
const pol = (c) => c.renderVals().pol;

test("#537 the numbered pages: every page up to 7, then the first, the last, the current page's neighbours and a gap", () => {
  assert.deepEqual(pageSlots(1, 1), [1]);
  assert.deepEqual(pageSlots(2, 4), [1, 2, 3, 4]);
  assert.deepEqual(pageSlots(7, 7), [1, 2, 3, 4, 5, 6, 7]);
  assert.deepEqual(pageSlots(1, 10), [1, 2, 3, 4, 5, 0, 10]);
  assert.deepEqual(pageSlots(4, 10), [1, 2, 3, 4, 5, 0, 10]);
  assert.deepEqual(pageSlots(5, 10), [1, 0, 4, 5, 6, 0, 10]);
  assert.deepEqual(pageSlots(7, 10), [1, 0, 6, 7, 8, 9, 10]);
  assert.deepEqual(pageSlots(10, 10), [1, 0, 6, 7, 8, 9, 10]);
  for (let last = 1; last <= 30; last++) {
    for (let page = 1; page <= last; page++) {
      const slots = pageSlots(page, last);
      assert.ok(slots.length <= 7 && slots.includes(page) && slots[0] === 1 && slots.at(-1) === last, `${page} of ${last}: ${slots}`);
    }
  }
});

test("#537 each section opens and closes and shows its count; Results by policy starts closed", () => {
  const c = make("nonprod", "policies");
  const sec = pol(c).sec;
  assert.deepEqual(Object.fromEntries(Object.entries(sec).map(([k, s]) => [k, [s.show, s.open]])),
    { clusters: [true, "true"], fails: [true, "true"], refused: [true, "true"], policies: [false, "false"] });
  assert.deepEqual([sec.clusters.count, sec.fails.count, sec.refused.count, sec.policies.count], [String(pol(c).clusters.length), String(pol(c).fails.length), String(pol(c).rejections.length), String(pol(c).policies.length)]);
  sec.policies.toggle();
  assert.equal(pol(c).sec.policies.open, "true");
  pol(c).sec.clusters.toggle();
  assert.equal(pol(c).sec.clusters.show, false);
  assert.equal(pol(c).sec.clusters.count, sec.clusters.count, "a closed section keeps its count");
});

test("#537 Results by policy: 25 a page, the numbered pages, 25, 50 or 100 a page, and page 1 again after a new cluster or page size", () => {
  const c = make("nonprod", "policies");
  const all = pol(c).policies.map((p) => p.name);
  assert.ok(all.length > 25, `the sample has more than one page of policies (${all.length})`);
  assert.deepEqual(pol(c).pageRows.map((p) => p.name), all.slice(0, 25));
  assert.equal(pol(c).pg.range, `1–25 of ${all.length}`);
  assert.deepEqual(pol(c).pg.slots.map((s) => [s.text, s.current]), [["1", "page"], ["2", null]]);
  assert.equal(pol(c).pg.prevDis, "true");
  pol(c).pg.slots[1].pick();
  assert.deepEqual(pol(c).pageRows.map((p) => p.name), all.slice(25, 50));
  assert.equal(pol(c).pg.range, `26–${Math.min(50, all.length)} of ${all.length}`);
  assert.equal(pol(c).pg.nextDis, "true");
  pol(c).pg.prev();
  assert.equal(pol(c).pg.page, 1);
  pol(c).pg.next();
  // A new cluster starts at page 1.
  pol(c).clusterOpts[1].pick();
  assert.equal(pol(c).pg.page, 1);
  pol(c).pg.next();
  assert.equal(pol(c).pg.page, 2);
  // So does a new page size. The sample has under 51 policies, so page 2 of 25 has no page 2 at 50: the state says it went back.
  pol(c).pg.sizes.find((o) => o.label === "50").pick();
  assert.equal(c.state.ppage, 1, "a new page size starts at page 1");
  assert.deepEqual([pol(c).pg.page, pol(c).pg.perPage, pol(c).pageRows.length], [1, 50, Math.min(50, all.length)]);
  assert.deepEqual(pol(c).pg.sizes.map((o) => [o.label, o.on]), [["25", "false"], ["50", "true"], ["100", "false"]]);
  pol(c).pg.sizes.find((o) => o.label === "100").pick();
  assert.equal(pol(c).pageRows.length, Math.min(100, all.length));
  assert.deepEqual(pol(c).pg.slots.map((s) => s.text), ["1"]);
});

test("the standalone runtime parses as ES2019", () => {
  parse(readFileSync(join(portal, "runtime", "dc-lite.js"), "utf8"), { ecmaVersion: 2019 });
});

test("dist/portal.html is built from the current sources", () => {
  execFileSync("node", [join(repoRoot, "scripts", "build-portal.mjs"), "--check"], { stdio: "pipe" });
});

console.log(`${passed} passed`);
