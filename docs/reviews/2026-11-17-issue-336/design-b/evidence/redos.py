"""Does the loader (main, #332 subset + #348 RE2) accept patterns that backtrack exponentially in a backtracking engine?
Prints each pattern's verdict at load and the value_regex the API would serve."""
import sys
import cmapi.core.metadata as m
BASE = {"emailDomains": ["company.net"], "requiredLabels": {}}
for p in ["^(a+)+b$", "^(a|a)*b$", "^([a-z]+)*-x$", "^(?:[a-z0-9]+-?)*[a-z0-9]$"]:
    raw = dict(BASE, requiredLabels={"company.net/x": {"pattern": p, "example": "ab" if "b" in p else "a-x"}})
    try:
        keys = m.MetadataKeys(raw)
        print("LOADS ", repr(p), "->", m.value_regex(keys.rules["label"]["company.net/x"], []))
    except ValueError as e:
        print("REFUSED", repr(p), str(e)[:160])
