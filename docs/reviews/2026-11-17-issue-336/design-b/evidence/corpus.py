"""Writes corpus.json: for each declared key of both configs that a requester sets, values and the validator's verdict.
The verdict is MetadataKeys.validate() on that one key (require_governed=False, no namespace, so namespacePrefix is not
read), the authority the portal must never be stricter than. Also RE2's verdict (value_matches) for each schema pattern.
Run: PYTHONPATH=<export>/cmapi/src python corpus.py <export>"""
import json, random, sys
from pathlib import Path
import cmapi.core.metadata as m

root = Path(sys.argv[1])
here = Path(__file__).parent
rng = random.Random(336)
ALPHABET = list("abcxyzABCZ0189-_.@/:?#[] ") + ["\n", "\t", "\r", "é", "ü", "😀", " ", " ", "℀", "／", "ａ", "\u0000"]
FIXED = ["", " ", "a", "ab", "abc", "abcd", "abcde", "ABC", "Abc", "abc\n", "\nabc", "abc ", "-abc", "abc-", "a.b", "a_b", "a--b",
         "a" * 63, "a" * 64, "0", "1", "6", "7", "01", "é", "ａbc", "abc ", "😀", "\ud800", "abc\ud800",
         "auto", "manual", "AUTO", "auto\n", "cc-4410", "cc-441", "cc-44100", "CC-4410",
         "payments", "payments-team@ephico2real.com", "payments-team@EPHICO2REAL.COM", "x@ephico2real.com.evil.com", "a@b@ephico2real.com",
         "@ephico2real.com", "é@ephico2real.com", "x@ephico2real.com\n", " x@ephico2real.com",
         "abc-team@company.net", "abc-team@COMPANY.NET", "abc@company.net.evil", "a@b@company.net", "@company.net", "é@company.net",
         "abc-team@company.net\n", "a..b@company.net", ".a@company.net", "a+b@company.net", "a/b@company.net", "a\"b@company.net",
         "https://wiki.company.net/abc", "HTTPS://WIKI.company.net", "http://x", "https://", "https:///x", "https://[::1]/", "https://[::1]:8443/x",
         "https://[1:2:3:4:5:6:7:8]", "https://[::ffff:1.2.3.4]", "https://u@[::1]", "https://a b", "ftp://x", "https://x/ ", "https://ex.com℀x",
         "https://x/ok?q=1#f", "https://x\n", "https://xn--bcher-kva.example/", "https://bücher.example/", "https://x/😀", "https://[::1]x", "https://x]"]


def values(rule):
    out = list(FIXED)
    if rule.example:
        out.append(rule.example)
    for v in rule.enum or ():
        out += [v, v + " ", v.upper()]
    for _ in range(1500):
        n = rng.randint(0, 14)
        out.append("".join(rng.choice(ALPHABET) for _ in range(n)))
    if rule.example:
        for _ in range(300):
            s = list(rule.example)
            i = rng.randrange(len(s) + 1)
            op = rng.choice("ids")
            if op == "i":
                s.insert(i, rng.choice(ALPHABET))
            elif op == "d" and s:
                s.pop(min(i, len(s) - 1))
            elif s:
                s[min(i, len(s) - 1)] = rng.choice(ALPHABET)
            out.append("".join(s))
    return list(dict.fromkeys(out))


cases = []
for name, rel in (("reference", "examples/cluster-configs/policies/metadata-keys.yaml"),
                  ("company", "examples/cluster-configs/policies/metadata-keys.company.yaml")):
    keys = m.MetadataKeys.load(root / rel)
    for kind in m.KINDS:
        schema = keys.json_schema(kind, "create")
        for key, rule in keys.rules[kind].items():
            if rule.derived:
                continue
            prop = schema["properties"][key]
            pats = [p for p in [prop.get("pattern"), *(s.get("pattern") for s in prop.get("allOf", []))] if p]
            for v in values(rule):
                sent = {key: v}
                errs = keys.validate(sent if kind == "label" else {}, sent if kind == "annotation" else {},
                                     operator=False, require_governed=False)
                mine = [e for e in errs if e.get("key") == key]
                re2v = {p: m.value_matches(p, v) for p in pats}
                cases.append({"config": name, "kind": kind, "key": key, "required": rule.required, "value": v,
                              "server_ok": not mine and not (rule.required and v == ""), "server_codes": [e["code"] for e in mine],
                              "re2": re2v})
(here / "corpus.json").write_text(json.dumps({"cases": cases}, ensure_ascii=True))
print("cases", len(cases), "keys", len({(c['config'], c['kind'], c['key']) for c in cases}))
