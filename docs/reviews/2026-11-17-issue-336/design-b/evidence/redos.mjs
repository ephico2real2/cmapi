// V8 (Irregexp, a backtracking engine, as in Chrome and Node) on value regexes that main's loader accepts (redos-loader.log).
// The time of one test() on a value of n characters that almost matches. Run: node redos.mjs
const cases = [["^(?:^(a+)+b$)$", (n) => "a".repeat(n) + "!"], ["^(?:^(a|a)*b$)$", (n) => "a".repeat(n) + "!"],
  ["^(?:^([a-z]+)*-x$)$", (n) => "a".repeat(n) + "!"], ["^(?:^(?:[a-z0-9]+-?)*[a-z0-9]$)$", (n) => "a".repeat(n) + "!"]];
for (const [p, value] of cases) {
  const re = new RegExp(p, "u");
  const row = [];
  for (const n of [16, 20, 22, 24, 26]) {
    const t = performance.now(); re.test(value(n)); row.push(`n=${n}: ${(performance.now() - t).toFixed(1)} ms`);
    if (performance.now() - t > 4000) break;
  }
  console.log(p, "|", row.join(", "));
}
