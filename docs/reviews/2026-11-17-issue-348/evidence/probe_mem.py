import re2, sys
sys.path.insert(0, sys.argv[1])
from cmapi.core.metadata import portable_pattern_problem, anchored, _URL
o = re2.Options(); o.log_errors = False
print("default max_mem", o.max_mem)
for p in ["[^a]{1000}", "(?:[^a]{10}){100}", "[^a]{1000}[^b]{1000}[^c]{1000}", "(?:[^\\n\\r]{1000}x){1}" , "[a-z]{1000}"*10, "é{1000}"]:
    prob = portable_pattern_problem(p)
    try:
        re2.compile(anchored(p), o); r = "re2 ok"
    except re2.error as e:
        r = f"re2 refused: {e}"
    print(f"{p[:40]!r:44} subset={prob or 'in'} {r}")
re2.compile(_URL, o); print("URL ok")
for n in (50, 100):
    p = "[^a]{1000}" * n
    try:
        re2.compile(anchored(p), o); r = "re2 ok"
    except re2.error as e:
        r = f"re2 refused: {e.args[0].decode()}"
    print(f"[^a]{{1000}} x {n}: subset={portable_pattern_problem(p) or 'in'} {r}")
