"""#348 options: what a nested-quantifier refusal and a length bound miss, measured in Python re and google-re2."""
import re, re2, time, sys
sys.path.insert(0, sys.argv[1])
from cmapi.core.metadata import portable_pattern_problem, anchored
CASES = [
    ("(a+)+b", "nested unbounded", "a" * 24 + "c"),
    ("(a|a)*b", "star height 1, overlapping alternation", "a" * 24 + "c"),
    ("(a|aa)+b", "star height 1, overlapping alternation", "a" * 30 + "c"),
    ("[a-z]*[a-z]*[a-z]*[a-z]*[a-z]*b", "star height 1, polynomial n^5", "a" * 120 + "1"),
    ("[a-z0-9]+(?:-[a-z0-9]+)*", "nested, unambiguous (a common slug pattern)", "a-" * 5000 + "!"),
]
for p, what, v in CASES:
    rx = anchored(p)
    t = time.perf_counter(); re.fullmatch(rx, v); tr = time.perf_counter() - t
    t = time.perf_counter(); re2.fullmatch(rx, v); t2 = time.perf_counter() - t
    print(f"{p!r:40} {what:45} len={len(v):6} subset={portable_pattern_problem(p) or 'in'}  re={tr*1000:9.1f} ms  re2={t2*1000:6.3f} ms")
