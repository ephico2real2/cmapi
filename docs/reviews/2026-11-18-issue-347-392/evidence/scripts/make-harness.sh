#!/bin/sh
# Writes tests/api/zz-stress.test.mjs: portal.test.mjs with two stress knobs, for the #347/#392 before/after counts only
# (never committed). CPU_RATE=n throttles each page's CPU through CDP Emulation.setCPUThrottlingRate; JITTER_MS=n waits a
# random 0..n ms after a check-7 view is reached, so the read lands at a random phase of PatternFly's scroll-button timers.
# WIDTH=n and VIEW=name narrow the check-7 loops to one width and one view.
set -eu
cd "$1/cmapi-portal-ui/tests/api"
python3 - <<'PY'
s = open("portal.test.mjs").read()
a = "  const page = await context.newPage();\n  page.setDefaultTimeout(8000);\n"
assert s.count(a) == 1
s = s.replace(a, a + "  if (process.env.CPU_RATE) await (await context.newCDPSession(page)).send(\"Emulation.setCPUThrottlingRate\", { rate: Number(process.env.CPU_RATE) });\n")
# API_DELAY_MS=n: the stand-in API answers each call n ms late, as a slower API would.
c = "  issuer.state.seen.length = 0;\n  expectedStatus = [];\n"
assert s.count(c) == 1
s = s.replace(c, c + "  if (process.env.API_DELAY_MS) api.state.delayMs = Number(process.env.API_DELAY_MS);\n")
b = "        await reach(page);\n"
n = s.count(b)
assert n >= 4, n
s = s.replace(b, b + "        if (process.env.JITTER_MS) await new Promise((r) => setTimeout(r, Math.random() * Number(process.env.JITTER_MS)));\n")
import re
# WIDTH=n and VIEW=name run one width and one view of the check-7 loops.
s, k = re.subn(r"(\n( *)for \(const \[(\w+), [^\n]*\] of VIEWS\) \{\n)", lambda m: m.group(1) + m.group(2) + f"  if (process.env.VIEW && {m.group(3)} !== process.env.VIEW) continue;\n", s)
s, w = re.subn(r"(\n( *)for \(const width of \[390, 820, 1440\]\) \{\n)", lambda m: m.group(1) + m.group(2) + "  if (process.env.WIDTH && width !== Number(process.env.WIDTH)) continue;\n", s)
print("view loops:", k, "width loops:", w)
open("zz-stress.test.mjs", "w").write(s)
print("reach sites:", n)
PY
