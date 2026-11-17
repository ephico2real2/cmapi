// Each configured pattern is tested in a module Web Worker, with a time limit (#336). The loader accepts patterns that
// backtrack in ECMA-262 (^(?:[a-z0-9]+-?)*[a-z0-9]$ takes V8 944 ms on 26 characters, four times as long for each two
// more), and a label value may hold 63: on the page's thread one keystroke could freeze the form. A test that runs out of
// time ends its worker, marks the pattern slow for the session and answers null: "not checked here". The form then shows
// no error for it, and cmapi's dry run decides. The worker is its own file of the build, so the portal's CSP
// (script-src 'self', which worker-src falls back to) allows it with no blob: URL.
import type { PatternTest } from "./metadataForm";

/** How long the page waits for one pattern test. A check that takes longer is not checked here. */
export const PATTERN_LIMIT_MS = 200;

interface Reply { id: number; ok: boolean | null }

/** One worker at a time, one test at a time: a test that runs out of time ends only its own worker. */
export function patternChecker(limitMs: number = PATTERN_LIMIT_MS,
  spawn: () => Worker = () => new Worker(new URL("./patternWorker.ts", import.meta.url), { type: "module" })): { test: PatternTest; dispose: () => void } {
  const slow = new Set<string>();
  const known = new Map<string, boolean>();
  let worker: Worker | null = null;
  let broken = false;
  let next = 0;
  let queue: Promise<unknown> = Promise.resolve();

  const end = () => { worker?.terminate(); worker = null; };
  const once = (pattern: string, value: string): Promise<boolean | null> => {
    if (broken || slow.has(pattern)) return Promise.resolve(null);
    const memo = known.get(`${pattern}\u0000${value}`);
    if (memo !== undefined) return Promise.resolve(memo);
    try {
      worker ??= spawn();
    } catch {
      broken = true;                 // no worker here (a policy or an old browser): nothing is checked here, cmapi decides
      return Promise.resolve(null);
    }
    const w = worker, id = ++next;
    return new Promise((resolve) => {
      const done = (ok: boolean | null) => {
        clearTimeout(timer);
        w.removeEventListener("message", onMessage);
        w.removeEventListener("error", onError);
        resolve(ok);
      };
      const onMessage = (e: MessageEvent<Reply>) => {
        if (e.data.id !== id) return;
        if (e.data.ok !== null) {
          if (known.size > 2000) known.clear();
          known.set(`${pattern}\u0000${value}`, e.data.ok);
        }
        done(e.data.ok);
      };
      const onError = () => { end(); done(null); };
      const timer = setTimeout(() => { slow.add(pattern); end(); done(null); }, limitMs);
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
