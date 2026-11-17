import re, re2, time, sys
for p in [r"(a)\1", r"(?=a)", r"(?P<x>a)", r"a{1001}"]:
    try:
        re2.compile(p); print("compiled", p)
    except Exception as e:
        print("refused", p, type(e).__name__, e)
for v in ["\ud800", "a\udfffb"]:
    try:
        print("surrogate", repr(v), re2.fullmatch(r"^(?:[^b]*)$", v))
    except Exception as e:
        print("surrogate err", type(e).__name__, e)
pat = r"^(?:(a+)+b)$"
for n in (16, 20, 22, 24):
    v = "a" * n + "c"
    t = time.perf_counter(); re.fullmatch(pat, v); tr = time.perf_counter() - t
    t = time.perf_counter(); re2.fullmatch(pat, v); t2 = time.perf_counter() - t
    print(f"n={n} re={tr*1000:.1f}ms re2={t2*1000:.3f}ms")
for n in (63, 10_000, 262_144):
    v = "a" * n + "c"
    t = time.perf_counter(); re2.fullmatch(pat, v); t2 = time.perf_counter() - t
    print(f"re2 n={n} {t2*1000:.3f}ms")
print(re2.compile(pat).fullmatch("aab"), re2.fullmatch(pat, "aab") is not None)
print(type(re2.compile(pat)))
