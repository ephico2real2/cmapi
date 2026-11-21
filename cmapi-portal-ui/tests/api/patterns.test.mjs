// The pattern checker of patterns.ts: each way a test ends (verdict, error, either time limit, dispose) settles it and
// frees its timer and listeners (#522 reviews). A hand-driven clock and worker show what is left pending; the last test
// runs the real patternWorker.ts in a worker thread. Plain `node` runs it, as tests/api/mutants.mjs runs a suite.
import assert from "node:assert/strict";
import { test } from "node:test";
import { Worker as ThreadWorker } from "node:worker_threads";
import { patternChecker } from "../../src/portal/patterns.ts";

// A manually driven clock and worker expose pending resources without wall-clock races.
async function withChecker(run) {
  const originalSet = globalThis.setTimeout, originalClear = globalThis.clearTimeout;
  const timers = new Map(), workers = [];
  globalThis.setTimeout = (callback, ms) => { const token = {}; timers.set(token, { callback, ms }); return token; };
  globalThis.clearTimeout = (token) => timers.delete(token);
  const checker = patternChecker({ spawn: () => {
    const listeners = { message: new Set(), error: new Set() };
    const worker = {
      listeners, terminated: false,
      addEventListener: (type, fn) => listeners[type].add(fn),
      removeEventListener: (type, fn) => listeners[type].delete(fn),
      postMessage(data) { this.request = data; },
      terminate() { this.terminated = true; },
      emit(data) { for (const fn of [...listeners.message]) fn({ data: { id: this.request.id, ...data } }); },
      error() { for (const fn of [...listeners.error]) fn(); }
    };
    workers.push(worker);
    return worker;
  } });
  const expire = () => {
    assert.equal(timers.size, 1);
    const [token, { callback }] = [...timers][0];
    timers.delete(token);
    callback();
  };
  try { await run({ checker, timers, workers, expire }); }
  finally { checker.dispose(); globalThis.setTimeout = originalSet; globalThis.clearTimeout = originalClear; }
}

for (const started of [false, true]) {
  test(`dispose cancels a ${started ? "running" : "starting"} test and ignores its late start`, () => withChecker(async ({ checker, timers, workers }) => {
    const pending = checker.test("^a$", "a");
    await Promise.resolve();
    const worker = workers[0];
    if (started) worker.emit({ started: true });
    checker.dispose();
    assert.equal(timers.size, 0, "dispose must clear the active deadline immediately");
    assert.equal(await pending, null, "dispose settles the active request");
    assert.equal(worker.listeners.message.size + worker.listeners.error.size, 0);
    assert.equal(worker.terminated, true);
    worker.emit({ started: true });
    assert.equal(timers.size, 0, "a stale event cannot rearm a disposed test");
    const next = checker.test("^a$", "a");
    await Promise.resolve();
    workers[1].emit({ started: true });
    workers[1].emit({ ok: true });
    assert.equal(await next, true, "cancellation must not mark the worker broken or the pattern slow");
    assert.equal(timers.size, 0);
  }));
}

test("verdicts, and errors after the start, clear both kinds of deadline; such an error permits a fresh worker", () => withChecker(async ({ checker, timers, workers }) => {
  for (const [started, error] of [[false, false], [true, false], [true, true]]) {
    const pending = checker.test(`^a${started}${error}$`, "a");
    await Promise.resolve();
    const worker = workers.at(-1);
    assert.equal([...timers.values()][0].ms, 5000);
    worker.emit({ id: -1, started: true });
    assert.equal([...timers.values()][0].ms, 5000, "another request's start cannot replace the start timer");
    if (started) {
      worker.emit({ started: true });
      assert.equal([...timers.values()][0].ms, 200);
    }
    if (error) worker.error(); else worker.emit({ ok: false });
    assert.equal(await pending, error ? null : false);
    assert.equal(timers.size, 0);
    assert.equal(worker.listeners.message.size + worker.listeners.error.size, 0);
    assert.equal(worker.terminated, error);
  }
  const next = checker.test("^z$", "z");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(workers.length, 2, "only the error replaced the worker");
  workers[1].emit({ started: true });
  workers[1].emit({ ok: true });
  assert.equal(await next, true);
}));

test("a worker that fails before it starts a test is a worker the page does not have: no second worker", () => withChecker(async ({ checker, timers, workers }) => {
  const first = checker.test("^a$", "a");
  await Promise.resolve();
  workers[0].error();                // its script did not load: a CSP block, a 404 (HTML, "run a worker")
  assert.equal(await first, null);
  assert.equal(timers.size, 0);
  assert.equal(workers[0].terminated, true);
  const second = checker.test("^b$", "b");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(workers.length, 1, "no new worker, and no new fetch of a script that fails, for each later test");
  assert.equal(await second, null, "not checked here, cmapi decides");
}));

test("a start timeout disables all subsequent checks, including queued and previously cached ones", () => withChecker(async ({ checker, timers, workers, expire }) => {
  const cached = checker.test("^a$", "a");
  await Promise.resolve();
  workers[0].emit({ started: true });
  workers[0].emit({ ok: true });
  assert.equal(await cached, true);
  const pending = checker.test("^b$", "b");
  await Promise.resolve();
  const queued = checker.test("^c$", "c");
  const oldWorker = workers[0];
  expire();
  assert.equal(await pending, null);
  assert.equal(await queued, null);
  assert.equal(await checker.test("^a$", "a"), null);
  oldWorker.emit({ started: true });
  assert.equal(timers.size, 0);
  assert.equal(workers.length, 1);
  assert.equal(oldWorker.terminated, true);
}));

test("a pattern timeout disables only that pattern; stale starts cannot affect the replacement", () => withChecker(async ({ checker, timers, workers, expire }) => {
  const pending = checker.test("^a$", "a");
  await Promise.resolve();
  const oldWorker = workers[0];
  oldWorker.emit({ started: true });
  expire();
  assert.equal(await pending, null);
  assert.equal(await checker.test("^a$", "b"), null);
  const next = checker.test("^b$", "b");
  await Promise.resolve();
  oldWorker.emit({ started: true });
  assert.equal(timers.size, 1, "only the replacement's start deadline remains");
  assert.equal([...timers.values()][0].ms, 5000);
  workers[1].emit({ started: true });
  workers[1].emit({ ok: true });
  assert.equal(await next, true);
  assert.equal(timers.size, 0);
}));

test("the real worker posts started while RegExp.test blocks and is terminated about 200 ms later", async () => {
  const source = new URL("../../src/portal/patternWorker.ts", import.meta.url).href;
  const script = `import { parentPort } from 'node:worker_threads';
    globalThis.self = { postMessage: (data) => parentPort.postMessage(data) };
    await import(${JSON.stringify(source)});
    parentPort.on('message', (data) => self.onmessage({ data }));`;
  let startedAt, endedAt, verdicts = 0, watchdog;
  const exits = [];
  const checker = patternChecker({ spawn: () => {
    const thread = new ThreadWorker(new URL(`data:text/javascript,${encodeURIComponent(script)}`));
    const target = new EventTarget();
    thread.on("message", (data) => {
      if (data.started) startedAt = performance.now(); else verdicts++;
      target.dispatchEvent(new MessageEvent("message", { data }));
    });
    thread.on("error", () => target.dispatchEvent(new Event("error")));
    return Object.assign(target, {
      postMessage: (data) => thread.postMessage(data),
      terminate: () => { endedAt = performance.now(); exits.push(thread.terminate()); }
    });
  } });
  try {
    const result = await Promise.race([
      checker.test("^(?:[a-z0-9]+-?)*[a-z0-9]$", "a".repeat(40) + "A"),
      new Promise((_, reject) => { watchdog = setTimeout(() => reject(new Error("no cutoff in 3 s")), 3000); })
    ]);
    assert.equal(result, null);
    assert.equal(verdicts, 0, "the regex never returned a verdict");
    const elapsed = endedAt - startedAt;
    assert.ok(elapsed >= 180 && elapsed < 1500, `terminated ${elapsed.toFixed(1)} ms after receiving started`);
    console.log(`real blocked worker: terminated ${elapsed.toFixed(1)} ms after started`);
  } finally { clearTimeout(watchdog); checker.dispose(); await Promise.all(exits); }
});
