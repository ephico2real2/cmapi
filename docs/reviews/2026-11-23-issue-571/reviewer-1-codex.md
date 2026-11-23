# PR #579, reviewer 1 (Codex gpt-6.1-sol, high), 2026-11-23

Saved by the coordinator from Codex's returned report.

## Finding (P2): the If-Match parser backtracks quadratically on malformed whitespace

`head/cmapi/src/cmapi/core/etag.py:16`, called at l.46-53. The two `[ \t]*` around the optional tag can share the same whitespace. When the next character cannot end the element, the regex backtracks over every split.

- Example: `'"x",' + ' ' * 99995 + 'x'`.
- Codex measured 2,000 spaces at 0.056 s, 4,000 at 0.223 s and 8,000 at 0.881 s; 100,000 characters were interrupted after 2-3 s.
- **The coordinator reproduced it on head:** 4,000 at 0.220 s, 8,000 at 0.878 s, 16,000 at 3.690 s.

Fix: move the trailing whitespace into the optional tag group.

```python
_LIST_ELEMENT = re.compile(r'[ \t]*(?:(W/)?"([\x21\x23-\x7e\x80-\xff]*)"[ \t]*)?(?:,|\Z)')
```

- Codex: the 20 parser cases pass, and the results are identical on all 55,987 strings of length 0 to 6 over ` a",W/`.
- **The coordinator:** identical on all 137,257 strings of length 0 to 6 over ` a",W/\t`, with 16,000 spaces taking 0.0018 s.

Proposed regression test: a subprocess with `timeout=2` that parses `'"x",' + ws * 99995 + 'x'` for a space and for a tab, and expects `[]`. It fails on head (TimeoutExpired) and passes with the fix.

## Claims, as Codex ruled them
1. **Grammar and termination: confirmed.** There is no zero-length match mid-string. Garbage after a valid tag discards the whole value. `*` inside a list gives []. Starlette decodes header values as latin-1 (datastructures.py 484-486, 0.41.3), so the regex's \x80-\xff holds.
2. **"The guard is never weaker": literally refuted, but safe.** ` "tag" ` (a padded quoted singleton) was 412 on base and is 200 on head. That is a valid one-element list that holds the current tag, so it is within the owner's list rule. Whitespace-only values, wildcard lists, CR/LF and padded unquoted tags give no bypass.
3. **Joined wildcard lines:** `*` alone gives 428; `*, *` and `*, "tag"` give 412 (malformed list) on a new request, and the stored answer on a replay. These are consistent with the stated choices. Only a standalone `*` gives 428.
4. **404 < 428 < 412: confirmed for planning** (change pipeline.py:234-238, delete :447-451, expiry router.py:358-374). Replays return before the lookup, as the owner's replay rule wants. The internal expired-delete skips the precondition (:450-451).
5. **FakeGit #578: confirmed** for folder reads (github.py:70-77, gitea.py:55-76, workspace.py:299-308). Gitea also supports a direct-file path, which FakeGit's filter does not; no test needs it.
6. **Test gaps:**
   - The expiry test covers only `:set`.
   - The wildcard-replay test could pass with a wrong replay comparison, because Git never moves (the #495 test covers moved Git).
   - The parser test has no long-whitespace case.
   - The doc test only matches strings.
7. **The docs and descriptions match the code.** The six docs/14 relocated citations match their locked text.

Limits: Codex could not run the service suite (no pytest or starlette in its runtime). It ran the pure parser, the extracted guard and FakeGit code, timing probes and the subprocess regression.
