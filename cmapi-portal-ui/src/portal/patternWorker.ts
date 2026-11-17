// The worker of patterns.ts: tests one configured pattern on one value, off the page's thread (#336). A pattern that
// backtracks can run for minutes in ECMA-262; here it holds only this worker, which the page ends after its time limit.
// The u flag reads a value by code points, as RE2 and Python read it (the subset of #332 reads alike in all three).
const compiled = new Map<string, RegExp>();

self.onmessage = (event: MessageEvent<{ id: number; pattern: string; value: string }>) => {
  const { id, pattern, value } = event.data;
  let ok: boolean | null;
  try {
    let re = compiled.get(pattern);
    if (!re) {
      re = new RegExp(pattern, "u");
      compiled.set(pattern, re);
    }
    ok = re.test(value);
  } catch {
    ok = null;                       // a pattern that this engine cannot compile: not checked here, cmapi decides
  }
  self.postMessage({ id, ok });
};

export {};
