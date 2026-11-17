# #332 and #338: the loader of metadata-keys.yaml, decided

Step 3 of the #328 plan (`docs/reviews/2026-11-16-issue-328/arbitration.md` on PR #329). Written by Opus 5.5 (`high`), the
implementer. One model family for this step: Codex is out of quota until 2026-11-18 and Fable is paused by the owner.

- **#332.** A configured `pattern` was read by Python `re` in cmapi, then by RE2 in the rendered Kyverno policies and by
  ECMA-262 in every client of the API document (#328), with no check that the three read it alike. The email and URL
  formats were written three times by hand: Python (`identity/checks.py email_in_domains`, `urlsplit`), CEL
  (`policygen._value_rule`) and, for #328, JSON Schema.
- **#328 question 3.** The owner: a required key with no `example` is refused at load.
- **#338.** An unknown top-level stanza was ignored, and a text where a list is expected was read as its characters.

## What changed

| Where | Change |
|---|---|
| `core/metadata.py` | `portable_pattern_problem` (the allowlist reader below), `anchored` (`^(?:P)$`, the one place a pattern is anchored), `value_regex(rule, domains)` (the one regex of a pattern or a format). The loader refuses a pattern outside the subset, an empty or non-text pattern, a required key with no `example`, an `example` its own rule refuses, an unknown stanza, a stanza of the wrong type, an `adoptionLabels` entry with an unknown field, and an `emailDomains` entry that is not a domain name. The validator matches `value_regex` (`re.fullmatch`) |
| `core/policygen.py` `_value_rule` | CEL `matches(value_regex)` for patterns and both formats, in place of the hand-written email CEL (`split('@')`, `lowerAscii()`) and URL CEL (`(?i)^https?://[^/?#]+` and an RE2-only whitespace class) |
| `examples/cluster-configs/policies/env/*/cmapi-metadata-*.yaml` | Re-rendered (`cmapi-tools policies render`): the `cmapi.net/team-dl` validation now carries the email regex |
| `.github/workflows/ci.yml`, `reference-code` | Node 24 and `CMAPI_REQUIRE_NODE=1`, so the ECMA-262 leg fails rather than skips |
| `docs/18-configuration.md` | The shape checks, the rule table, the loader's refusals and a "Patterns" section |
| `deploy/helm/cmapi/values.schema.json` (#335, merged as 326a234) | `requiredExample`: a key of `requiredLabels` or `requiredAnnotations` needs `example` or `value`, so Helm refuses the block before a render, as the loader refuses the file at start. The rest of the loader's new refusals the schema already held (unknown stanza and field, a text for a list, an `adoptionLabels` field, a non-text `example`, the domain syntax, an empty `pattern`). Two stay in the loader only, since JSON Schema cannot say them: the pattern subset (a grammar with nested parentheses is not a regular language, so no `pattern` keyword describes it) and an `example` that its own rule refuses (the rule is data, and a schema cannot use data as a pattern) |
| Shipped configs | None changed. All six copies load (chart, three examples, CRC and kind ConfigMaps): `test_every_shipped_copy_loads` |

## The method of the subset check

**Chosen: an allowlist, read by a small recursive-descent parser in `core/metadata.py` (`_Subset`).** The grammar is
RFC 9485 (I-Regexp) without `\p{..}` and `.`, plus `(?:...)`, lazy quantifiers, `\$` and `\/`, and `^`/`$` only where a
whole-value match makes them no-ops. Each refusal names the construct, its position and what to write instead.

Why I-Regexp: it is the IETF's format for exactly this problem, "an interoperable regular expression", defined as a
grammar, with a mapping to ECMA-262 ("wrap the result in `^(?:` and `)$`", with the u flag; RFC 9485 section 5.3) and to
RE2 (section 5.4). Its grammar has no `\d`, `\w`, `\s` (section 3; 5.1 suggests `[0-9]` for `\d`). Two of its constructs
are not in the common subset of these three engines, so they are left out:

- `\p{..}`: Python `re` has no Unicode properties.
- `.`: RFC 9485 maps it to `[^\n\r]` for ECMA-262 (5.3), because ECMA-262's `.` also leaves out U+2028 and U+2029; Python
  (`.` "matches any character except a newline", re docs) and Go RE2 (`s` flag off: "let . match \n (default false)") read
  it as "not `\n`". Refused, with `[^\n\r]` suggested, rather than rewritten, so the configured text is the string that
  the three engines read.

`^` and `$`: Python's `$` "Matches the end of the string or just before the newline at the end of the string" (re docs);
Go's is "at end of text (like \z not \Z)" (regexp/syntax). The two agree only where nothing can follow `$`, so `$` is
allowed at the end of the pattern or of a top-level alternative, and `^` at the start of one. Every shipped pattern is
`^...$`, so all still load.

Counts: Go regexp/syntax: "The counting forms x{n,m}, x{n,}, and x{n} reject forms that create a minimum or maximum
repetition count above 1000", and nested counts multiply (`repeatIsValid`; measured: `^(?:a{100}){11}$` gives
"invalid repeat count"). The reader applies the same product rule.

### Rejected

| Option | Why not (measured where it says so) |
|---|---|
| Compile in all three engines at load and trust the result | A compile is not a reading: `\d`, `\w`, `.`, `$` mid-pattern and `{,3}` compile in some engines and read differently (`{,3}` is 0 to 3 in Python and the literal text in RE2; `evidence/blocklist-vs-allowlist.txt`). It would also put an RE2 and a JavaScript engine into the API image only to start |
| A blocklist regex (design B's `_NOT_PORTABLE`, its section 2.3) | Measured on this test's 29 constructs: it misses 16, among them `.`, `\d`, `\w`, `{,3}`, `{1001}`, nested counts, a lone `]` `{` `}`, `\-`, `$` before the end and `[a&&b]`. Seven of the 16 do not even compile in ECMA-262 or RE2 (`evidence/blocklist-vs-allowlist.txt`, `evidence/re2-missed.go`) |
| Rewrite the pattern (`.` to `[^\n\r]`, as RFC 9485 5.3 does) | The configured text and the string the engines read would differ, and the docs would have to explain both. A refusal that names the replacement keeps them one |
| `re.escape` for a mail domain in the email regex (design B's `caseless`) | It writes `\-`, which ECMA-262 refuses outside a class in Unicode mode (measured: `new RegExp("^\\-$", "u")` throws "Invalid escape"). `_literal` escapes only syntax characters, and the loader holds each domain to DNS label syntax |
| `(?i)` for the case of `http` and the domains | ECMA-262 before ES2025 has no inline flag; each ASCII letter is written `[xX]` (also design A and B) |
| `urlsplit` for the URL format | It strips a leading C0 control (`"\x01http://x"` accepted, which the policy refused) and raises `ValueError` on brackets (`"http://[x"`), which the API turned into 422 `validation-failed` instead of the key's refusal (`evidence/validator-main-vs-branch.txt`) |

## Behaviour that changes

Measured by `evidence/url-email-verdicts.py` on main 5a8f817 and on this branch, 162 verdicts of the company file's URL and
email keys: 10 differ (`evidence/validator-main-vs-branch.txt`).

- Refused now, accepted on main: `"\x01http://x"` (the policy refused it already), `http://[v1.x]/` (an IPvFuture
  literal; RFC 3986's `IPvFuture` is not written into the regex), and `http://[fe80::1%25eth0]/` (an IPv6 zone ID, which
  `ipaddress` reads and RFC 3986 and the WHATWG URL standard do not).
- Refused, as on main: a netloc with a character whose NFKC form holds `/`, `?`, `#`, `@` or `:` (`http://a℀b/`,
  CVE-2019-9636), and text before `[` that is not a userinfo or after `]` that is not a port (`http://[::1]x/`). urlsplit
  raised `ValueError` on both; `test_the_url_regex_accepts_nothing_that_the_urlsplit_check_refused` holds the regex to that
  (review of #346, OB3).
- Refused now with the key's `invalid_value`, a 422 `validation-failed` from `urlsplit` on main: `http://[x`, `http://x]`,
  `http://[x]`, `http://[:::::]/`, `http://[1::2::3]/`, `http://[12345::]/`, `http://[1.2.3.4]/`,
  `http://[::ffff:256.0.0.1]/`.
- Nothing accepted now that main refused. The bracketed host is RFC 3986's `IPv6address`, written out in the subset;
  `test_the_url_host_reads_an_ipv6_address_as_python_ipaddress_does` holds it equal to `ipaddress.IPv6Address` on 27,000
  seeded addresses and corruptions (and fails on a one-character change of the regex, measured).
- In the policies: the email check is one regex, so a domain's letters are matched as ASCII (`[cC]`), as CEL's
  `lowerAscii()` did. Python's `str.lower()` lowered a non-ASCII letter too (the Kelvin sign U+212A to `k`).
- A pattern is matched as written: an empty `pattern` was skipped by the validator (`if rule.pattern`) and anchored to
  `^(?:)$` by the policy. It is now refused at load, as the chart's `values.schema.json` (`minLength: 1`) refuses it.
- `email_in_domains` in `identity/checks.py` stays for `check_team_dl` (its tests); the metadata validator no longer
  calls it.

## The three engines, measured

`evidence/result.txt`, on 2026-11-17: the 25 regexes of the test (each accepted pattern anchored, and every pattern and
format regex of the shipped and company files, with a hyphenated mail domain) on 80 strings (empty, 63 and 64
characters, a final newline, `\r`, U+00A0, U+2028, U+001C, U+0085, U+FEFF, U+0661, a combining accent, an astral
character, NUL, IPv6 hosts and their corruptions): RE2 (Go 1.27.3 `regexp`) 2000 verdicts, 0 differ from Python
`re.fullmatch`; ECMA-262 (Node 26.9.0, `u` flag) 2000 verdicts, 0 differ. The harness is design B's (`tri.go`,
`tri.mjs`), on `corpus.json`.

In CI the same comparison is a test, `tests/core/test_metadata_pattern_subset_332.py`: the ECMA-262 leg runs Node, the RE2
leg runs the Kyverno CLI v1.20.0 (the image's pin, the engine that judges at admission) on one `ValidatingPolicy` per
regex. A mutant check (a regex with `.` and one with `$\n?` added, and `a\n` and `x\r` in the corpus) makes the ECMA-262
leg and the RE2 leg fail, measured on this Mac.

## Tests, before and after

Before is main 5a8f817 (`git archive`), after is this branch. Logs in the implementer's notes, `ob-332/`.

| Test | Main | Branch |
|---|---|---|
| `test_metadata_pattern_subset_332.py` (with the new names stubbed so it collects on main) | 62 fail, 8 pass (the 8 are guards: good URLs, URLs main refused too, and a key that needs no example) | 70 pass |
| `test_metadata_loader_shape_338.py` | 44 fail, 1 pass (`test_every_shipped_copy_loads`, a guard) | 45 pass |
| `test_policygen.py::test_python_and_kyverno_refuse_the_same_value`, the two new URL cases | 2 fail | pass |
| `tests/service/test_metadata_url_332_api.py`, `policy.engine: none`, no `kyverno` on PATH | 2 fail (202 for `\x01https://...`, 422 `validation-failed` for `http://[...`), 1 pass | 3 pass |
| `tests/core` in full, Node and Kyverno required | | 532 pass |
| `tests/service/test_helm_metadata_values.py` (helm 4.3.1, no database), the 8 new cases | 8 fail on main 326a234 (Helm renders a required key with no example; the loader loads the misspelt stanza, the text for a list, a non-text example, a required key with no example and `\d`; `_LIST_STANZAS` is new) | 64 pass |

## Sources, read on 2026-11-17

- RFC 9485, I-Regexp: An Interoperable Regular Expression Format, <https://www.rfc-editor.org/rfc/rfc9485.html>:
  section 3 (the ABNF; no multi-character escapes `\s`, `\S`, `\w`), 5.1 (`\d` to `[0-9]`), 5.3 (ECMA-262: `.` to
  `[^\n\r]`, wrap in `^(?:` and `)$`, the `u` flag), 5.4 (RE2: wrap in `\A(?:` and `)\z`).
- Go `regexp/syntax`, <https://pkg.go.dev/regexp/syntax>: the 1000 count limit; `$` "at end of text (like \z not \Z)";
  `s` "let . match \n (default false)"; "Perl character classes (all ASCII-only)": `\d` `[0-9]`, `\s` `[\t\n\f\r ]`;
  `ErrInvalidRepeatOp` "invalid nested repetition operator".
- CEL language definition, <https://github.com/google/cel-spec/blob/master/doc/langdef.md>: `matches` "Tests whether a
  string matches a given RE2 regular expression"; "Regular expressions follow the RE2 syntax."
- Python `re`, <https://docs.python.org/3/library/re.html>: `$`, `.`, `\d` ("any Unicode decimal digit ... Matches
  `[0-9]` if the ASCII flag is used"), possessive quantifiers and atomic groups "Added in version 3.11", `re.fullmatch`.
- ECMA-262, RegExp patterns, <https://tc39.es/ecma262/multipage/text-processing.html#sec-patterns>, and JSON Schema
  2020-12 Validation 6.3.3 (a `pattern` is ECMA-262, not anchored; quoted in design B section 7). The ECMA-262 behaviours
  this record relies on (Unicode-mode escapes, lone `]` `{` `}`, `.`) were measured in Node 26.9.0, not quoted.
- RFC 3986 section 3.2.2, `IPv6address` and `IPvFuture`, <https://www.rfc-editor.org/rfc/rfc3986#section-3.2.2>.

## Not tested here

- CRC and kind: nothing ran on a cluster. The service suite ran one new file locally; CI's `service` job is the full run.
