# #348: the validator matches a configured pattern with RE2, in linear time

Part of #332. Written by Opus 5.5 (`high`), the implementer. One model family for this step.

**The defect.** cmapi's validator matched each configured `pattern` of `metadata-keys.yaml` with Python `re`
(`re.fullmatch` in `MetadataKeys._governed`), a backtracking engine. A pattern inside the subset that the loader admits
(#332), such as `(a+)+b`, takes time exponential in the value: a requester's label value (63 characters) or annotation
value could hold a worker on each plan. The pattern is the operator's; the value is any requester's.

## The choice

**RE2, through `google-re2` (RE2's own Python binding), for every match of a value against its regex**
(`value_matches` in `core/metadata.py`). The loader still refuses a pattern outside the subset (#332), still compiles it in
Python `re` (Python clients of the API document read the JSON Schema `pattern` with it), and now also compiles it in RE2,
so a pattern RE2 refuses stops the start instead of failing a request.

Why: RE2 "guarantees" that "the match time is linear in the length of the input string", and was designed "to handle
regular expressions from untrusted users without risk" (RE2 README). It evaluates the alternatives in parallel instead of
backtracking (Russ Cox, "Regular Expression Matching Can Be Simple And Fast": backtracking "requires O(2^n) time" on the
pathological case, the Thompson simulation "O(mn)"; "Perl, PCRE, Python, and Ruby are all using recursive backtracking").
It is also the engine of the other side of cmapi's check: Kyverno's CEL `matches()` is RE2 (CEL language definition), so
cmapi now judges a value with the engine that judges it at admission.

| Package | Measured or read |
|---|---|
| Name and version | `google-re2==1.1.20251105` (PyPI, published 2025-11-05; the README says the PyPI package `re2` "is not by the RE2 authors and is unmaintained") |
| Licence | BSD-3-Clause (RE2's repository; the wheel's classifier is "OSI Approved :: BSD License") |
| Dependencies | None (`requires_dist` is empty) |
| Wheels | `cp312` for `manylinux_2_27_x86_64.manylinux_2_28_x86_64`, `manylinux_2_28_aarch64`, macOS 13 to 15 on arm64 and x86_64, Windows |
| The image | Installed in the pinned base `ubi9/python-312-minimal@sha256:b99faa...` (linux/amd64, glibc 2.34, pip 24.2): pip took the `manylinux_2_28_x86_64` wheel, no compiler; `(a+)+b` on 100,001 characters 0.747 ms under emulation (`evidence/ubi-wheel.log`) |
| This Mac | Python 3.12.14, macOS arm64 wheel |

## Measured: Python re and RE2 on the same anchored regex

`evidence/probe_re2.out` and `evidence/probe_options.out`, on this Mac, 2026-11-17. Each pattern is in the subset.

| Pattern | Shape | Value | Python `re` | RE2 |
|---|---|---|---|---|
| `(a+)+b` | nested unbounded quantifiers | `a` x16 + `c` | 5.5 ms | 0.126 ms |
| `(a+)+b` | | `a` x20 + `c` | 85.2 ms | 0.176 ms |
| `(a+)+b` | | `a` x24 + `c` | 1,373.6 ms (doubling per character) | 0.112 ms |
| `(a+)+b` | | `a` x262,144 + `c` | not run | 0.682 ms |
| `(a\|a)*b` | one quantifier, overlapping alternation | `a` x24 + `c` | 2,802.8 ms | 0.210 ms |
| `(a\|aa)+b` | one quantifier, overlapping alternation | `a` x30 + `c` | 293.3 ms | 0.143 ms |
| `[a-z]*[a-z]*[a-z]*[a-z]*[a-z]*b` | no nesting, polynomial | `a` x120 + `1` | 1,891.2 ms | 0.249 ms |
| `[a-z0-9]+(?:-[a-z0-9]+)*` | nested, unambiguous (a common slug pattern) | `a-` x5,000 + `!` | 1.1 ms | 0.305 ms |

## Rejected

| Option | Why not (measured where it says so) |
|---|---|
| Refuse nested unbounded quantifiers at load (star height above 1) | It misses the cause: `(a\|a)*b` (2.8 s at 25 characters), `(a\|aa)+b` and five adjacent `[a-z]*` (1.9 s at 121 characters) have no nested quantifier and backtrack as badly. It also refuses safe and common patterns such as `[a-z0-9]+(?:-[a-z0-9]+)*` (1.1 ms on 10,001 characters in `re`). A complete static test for exponential and polynomial backtracking is an analysis of the pattern's automaton (ambiguity), a research tool's job, not a loader's |
| Bound the value's length | Labels are bounded already, at 63 characters, and `(a+)+b` takes 1.4 s at 25. Any bound short enough for the worst pattern refuses real annotation values |
| A per-match timeout | Python `re` has none (the `re` docs list no timeout parameter); the third-party `regex` module has one. A timeout still spends the bound on every request, makes the verdict depend on the machine's load, and needs a refusal for "took too long" that no rule of the file says. It limits the symptom; RE2 removes it |
| Run `re` in a thread or process with a deadline | A thread running `re` cannot be stopped in CPython; a process per check costs far more than the check and still spends the deadline |
| Keep `re` and require the operator to write safe patterns | The operator's text and the requester's value meet only at request time; a safe engine makes the operator's pattern harmless whatever its shape |

## Behaviour that changes

- Each value is matched by RE2. On the #332 corpus (25 regexes, 80 strings; every shipped and company regex and each
  construct of the subset) RE2 gives Python `re`'s verdict on every one:
  `test_the_validator_reads_each_regex_of_the_three_engine_corpus_as_python_re_does`. With the ECMA-262 and Kyverno legs of
  #332, which hold Python `re` equal to those engines, the readers agree.
- A value with a lone surrogate (JSON `"\ud800"`; FastAPI's `json.loads` passes it to the validator, measured) is refused by
  a key's pattern or format with `invalid_value` (or `invalid-team-dl`). On main a pattern such as `[^/]*` accepted it.
  RE2 reads UTF-8, which cannot hold one, and so does a Kubernetes string: Go's JSON decoder replaces it with U+FFFD, so the
  cluster would hold another value than the one checked. Without this, RE2's `UnicodeEncodeError` would have been a 500.
- A pattern in the subset whose program is beyond RE2's memory budget (8 MiB by default) stops the start with RE2's
  reason: a hundred `[^a]{1000}` in a row ("pattern too large - compile failed"; fifty load, `evidence/probe_mem.out`). On
  main it loaded. No shipped pattern is near it.

## Tests, before and after

Before is main 31e0794, after is this branch. Logs in the implementer's notes, `ob-348/`.

| Test | Main | Branch |
|---|---|---|
| `tests/core/test_metadata_linear_match_348.py::test_the_validator_answers_in_linear_time_whatever_the_pattern` (a child process; 16 values: four shapes, a 63-character label value and a 100,001-character annotation value, each refused and accepted) | fails: "the validator did not answer 16 values in 30 s" | passes; the file's 7 tests in 0.81 s |
| `...::test_the_validator_reads_each_regex_of_the_three_engine_corpus_as_python_re_does` | fails (no `value_matches`) | passes |
| `...::test_a_value_with_a_lone_surrogate_is_refused_and_never_raises` (3 values) | 3 fail (accepted) | pass |
| `...::test_a_pattern_too_large_for_re2_stops_the_start_with_re2s_reason` | fails: the file loads ("DID NOT RAISE") | passes |
| `...::test_each_shape_is_in_the_subset_that_the_loader_admits` (a guard) | passes | passes |
| The metadata and policy tests of `tests/core` (11 files), Node present, no Kyverno CLI on this Mac | | 317 pass, 23 skipped (the Kyverno legs) |

CI's `reference-code` job runs `tests/core` with `CMAPI_REQUIRE_KYVERNO=1` and `CMAPI_REQUIRE_NODE=1`, so the Kyverno leg of
the three-engine corpus runs there.

## Sources, read on 2026-11-17

- RE2, <https://github.com/google/re2>: README ("handle regular expressions from untrusted users without risk", "the match
  time is linear in the length of the input string", the `google-re2` package and the unmaintained `re2`, BSD-3-Clause).
- `google-re2` on PyPI, <https://pypi.org/project/google-re2/>: the wheels of 1.1.20251105 and their tags.
- Russ Cox, "Regular Expression Matching Can Be Simple And Fast", <https://swtch.com/~rsc/regexp/regexp1.html>.
- OWASP, "Regular expression Denial of Service - ReDoS",
  <https://community.owasp.org/attacks/Regular_expression_Denial_of_Service_-_ReDoS>: the cause is backtracking; the
  evil regexes `(a+)+$`, `([a-zA-Z]+)*$`, `(a|aa)+$`, `(a|a?)+$`; repetition over a group with repetition or overlapping
  alternation.
- CEL language definition, <https://github.com/google/cel-spec/blob/master/doc/langdef.md>: `matches` uses RE2 syntax.
- Python `re`, <https://docs.python.org/3/library/re.html>: no timeout parameter.

## Not tested here

- The Kyverno leg of the corpus on this Mac: the Kyverno CLI is not installed here, and downloading it was refused by the
  permission check (`curl -sSfL -o k.tgz https://github.com/kyverno/kyverno/releases/download/v1.20.0/kyverno-cli_v1.20.0_darwin_arm64.tar.gz`).
  CI's `reference-code` job runs it.
- The image itself was not built; the wheel was installed in its base image (above).
- CRC and kind: nothing ran on a cluster. The service suite was not run locally; CI's `service` job is the run.
