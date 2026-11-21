// Each configured pattern is tested in a module Web Worker, with a time limit (#336). The loader accepts patterns that
// backtrack in ECMA-262 (^(?:[a-z0-9]+-?)*[a-z0-9]$ takes V8 944 ms on 26 characters, four times as long for each two
// more), and a label value may hold 63: on the page's thread one keystroke could freeze the form. A test that runs out of
// time ends its worker, marks the pattern slow for the session and answers null: "not checked here". The form then shows
// no error for it, and cmapi's dry run decides. The worker is its own file of the build, so the portal's CSP
// (script-src 'self', which worker-src falls back to) allows it with no blob: URL.
//
// The limit is the pattern's own time: it starts when the worker says that it has started the test (#508). A test posted
// to a worker that is still loading waits in the worker's queue (HTML, "run a worker": the port's message queue is
// enabled after the script runs), and a cold start on a loaded machine took more than 200 ms (Chrome at CPU throttling
// 25: spawned at 11880 ms, timed out at 12118 ms). Timed from the post, that start-up marked a plain pattern slow for the
// session, and its errors stopped showing. A worker that does not start at all is a worker the page does not have.
import type { PatternTest } from "./metadataForm";

/** How long the page waits for one pattern test, from its start in the worker. A check that takes longer is not checked here. */
export const PATTERN_LIMIT_MS = 200;
/** How long the page waits for the worker to start a test. A worker that has not started by then is treated as none. */
export const WORKER_START_LIMIT_MS = 5000;

/** The worker's two messages for one test: that it started it, then its verdict. */
type Reply = { id: number; started: true } | { id: number; ok: boolean | null };

/** One worker at a time, one test at a time: a test that runs out of time ends only its own worker. */
export function patternChecker({ limitMs = PATTERN_LIMIT_MS, startLimitMs = WORKER_START_LIMIT_MS,
  spawn = () => new Worker(new URL("./patternWorker.ts", import.meta.url), { type: "module" }) }:
  { limitMs?: number; startLimitMs?: number; spawn?: () => Worker } = {}): { test: PatternTest; dispose: () => void } {
  const slow = new Set<string>();
  const known = new Map<string, boolean>();
  let worker: Worker | null = null;
  let broken = false;
  let next = 0;
  let queue: Promise<unknown> = Promise.resolve();
  let cancelTest: (() => void) | null = null;

  // Ending a worker also settles its test. dispose() may be called in either timed phase.
  const end = () => { worker?.terminate(); worker = null; cancelTest?.(); };
  const once = (pattern: string, value: string): Promise<boolean | null> => {
    if (broken || slow.has(pattern)) return Promise.resolve(null);
    const memo = known.get(`${pattern}\u0000${value}`);
    if (memo !== undefined) return Promise.resolve(memo);
    try {
      worker ??= spawn();
    } catch {
      broken = true;                 // no Worker here (an old browser): nothing is checked here, cmapi decides
      return Promise.resolve(null);
    }
    const w = worker, id = ++next;
    return new Promise((resolve) => {
      let running = false;
      const done = (ok: boolean | null) => {
        cancelTest = null;
        clearTimeout(timer);
        w.removeEventListener("message", onMessage);
        w.removeEventListener("error", onError);
        resolve(ok);
      };
      const onMessage = (e: MessageEvent<Reply>) => {
        const reply = e.data;
        if (reply.id !== id) return;
        if ("started" in reply) {
          running = true;
          clearTimeout(timer);
          timer = setTimeout(() => { slow.add(pattern); end(); done(null); }, limitMs);
          return;
        }
        if (reply.ok !== null) {
          if (known.size > 2000) known.clear();
          known.set(`${pattern}\u0000${value}`, reply.ok);
        }
        done(reply.ok);
      };
      // An error before the test started is the worker's script that did not load or run: a CSP block or a 404 is a
      // network error, and the page gets an "error" event, not an exception from new Worker (HTML, "run a worker"). That
      // worker never starts, so the page has none, as at a missed start; an error after the start ends only this worker.
      const onError = () => { if (!running) broken = true; end(); done(null); };
      // Until the worker starts the test, only its start-up is timed; the pattern is not at fault for it.
      let timer = setTimeout(() => { broken = true; end(); done(null); }, startLimitMs);
      cancelTest = () => done(null);
      w.addEventListener("message", onMessage);
      w.addEventListener("error", onError);
      w.postMessage({ id, pattern, value });
    });
  };
  const test: PatternTest = (pattern, value) => {
    const run = queue.then(() => once(pattern, value));
    queue = run.catch(() => undefined);
    return run;
  };
  return { test, dispose: end };
}

let shared: ReturnType<typeof patternChecker> | null = null;

/** The page's one checker: a pattern found slow stays slow until the page is loaded again. */
export const sharedPatternTest: PatternTest = (pattern, value) => (shared ??= patternChecker()).test(pattern, value);
