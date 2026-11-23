# Reviewer 2 (Opus 5.5 high): PRs #608 (#600) and #610 (#609)

Reviewer 2 checked reviewer 1's (Codex gpt-6.1-sol) report, `review-608/codex-result-608-610.txt`, read in full. All runs
were on this Mac, on the exports. Nothing was written to CRC or to any git repository. No cluster was used.

## Rulings

| PR | Ruling |
|---|---|
| #610 (#609) | **Changes needed; patch below.** Codex's finding is confirmed by running the test. `deploy/kind-test.sh:50` and `deploy/tests/kind-test-stubbed.sh:22` download CNPG without `--retry`. The second one runs in CI (`ci.yml:385`, the manifests job). The test cannot see either one: `URL -o file` order, and the files are not in its list. Head's own test passes 15 of 15 while it misses both. |
| #608 (#600) | **Accept as is; no patch.** Codex's source reading is confirmed by running the check. With the implementer's 500 ms injection, base fails 3 of 3 at the Show failures read, and the actual rows are the unfiltered CRC rows. Head passes 3 of 3 with the injection and 3 of 3 without it. Head's whole API suite passes: 139 checks, 0 `not ok`. |
| Capacity "a 304 keeps the figures" (`portal.test.mjs:4358`) | **No change.** The rows before and after the 304 are identical, so the read cannot fail on timing; it is not a flake. Lines 4354 to 4357 assert what matters: the revalidation with the ETag and `notModified == 1`. The step after it (a changed answer, then waiting for "stale since 09:14") shows the page still reads after the 304. Making the read wait would prove only the browser's cache behaviour, which the app never sees. Under the owner's do-not-over-build rule, it stays. |

## #610: what reviewer 2 changed from Codex's proposal

- **The command fixes are Codex's, unchanged:** `--retry 5` on both CNPG lines.
- **Scanner: Codex's `CNPG_URL` filter is replaced by a general probe rule.** Codex skipped every line in `deploy/` that does
  not contain `CNPG_URL`. That would silently skip any new download added to `kind-test.sh`. Reviewer 2's rule instead
  treats a curl in the listed files as a probe only when it does one of these things:
  - writes the status code (`-w`);
  - discards the body (`-o /dev/null`);
  - is read into a variable (`$(curl ...)`).

  Every other curl must parse as `curl FLAGS -o OUT URL` or `curl FLAGS URL -o OUT`. If it does not, or if what it parses
  as the URL starts with `-`, the test fails before any transfer and names the line. Like Codex's version, this is one
  regex and one refusal, so it is no more code.
- **The file list:** the two CNPG scripts are added, as Codex proposed.
- **The count floor:** 17, as Codex proposed.
- **Test order:** `downloads()` now runs before the server starts, so a refused line exits cleanly.
- **Docs:**
  - the test's docstring now describes the scan and the probe rule;
  - `docs/reviews/2026-11-23-issue-609/README.md` changes its counts from 15 to 17 and adds a row with reviewer 2's
    measured before and after. That row records the implementer's evidence; the coordinator may drop that hunk.

### The patch: `review-610/r2-outputs/fix.diff` (against 1c0d1d4, `patch -p1`)

Verified: `patch -p1` applied to a fresh copy of `head/` gives a tree identical to `review-610/r2/` (`diff -rq` clean).

```diff
--- a/deploy/kind-test.sh
+++ b/deploy/kind-test.sh
@@ -47,7 +47,7 @@
-curl -fsSL "$CNPG_URL" -o "$T/cnpg.yaml"
+curl -fsSL --retry 5 "$CNPG_URL" -o "$T/cnpg.yaml"
--- a/deploy/tests/kind-test-stubbed.sh
+++ b/deploy/tests/kind-test-stubbed.sh
@@ -19,7 +19,7 @@
-  curl -fsSL "$(sed -n 's/^CNPG_URL=//p' "$SRC/kind-test.sh")" -o "$KT_CNPG" || { ... }
+  curl -fsSL --retry 5 "$(sed -n 's/^CNPG_URL=//p' "$SRC/kind-test.sh")" -o "$KT_CNPG" || { ... }
--- a/deploy/tests/download-retry-test.py
+++ b/deploy/tests/download-retry-test.py
 FILES = [".github/workflows/ci.yml", ".github/workflows/api-contract-report.yml", "cmapi/Containerfile",
-         "examples/cluster-configs/.github/workflows/ci.yml"]
+         "examples/cluster-configs/.github/workflows/ci.yml",
+         # The CNPG manifest: kind-test-stubbed.sh fetches it in the manifests job, kind-test.sh on a real kind run.
+         "deploy/kind-test.sh", "deploy/tests/kind-test-stubbed.sh"]
-# A download: curl, its flags, -o, the output, the URL. Each one in these files is written on one line.
-DOWNLOAD = re.compile(r"\bcurl((?:\s+-[-\w]+(?:\s+\d+)?)*)\s+-o\s+(\S+)\s+(\S+)")
+# A download, on one line: curl, its flags, then `-o <file> <url>` or `<url> -o <file>`.
+DOWNLOAD = re.compile(r"\bcurl((?:\s+(?!-o\s)-[-\w]+(?:\s+\d+)?)*)\s+(?:-o\s+\S+\s+(?P<url>\S+)|(?P<url_first>\S.*?)\s+-o\s+\S+)")
+PROBE = re.compile(r"\s-w\s|-o\s+/dev/null\b|\$\(\s*curl\b")
 def downloads():
     for rel in FILES:
         for n, line in enumerate(open(os.path.join(ROOT, rel)), 1):
+            if line.lstrip().startswith("#") or not re.search(r"\bcurl\s", line) or PROBE.search(line):
+                continue
             m = DOWNLOAD.search(line)
-            if m:
-                yield f"{rel}:{n}", shlex.split(m.group(1)), m.group(3)
+            url = m and (m["url"] or m["url_first"])
+            if not url or url.startswith("-"):
+                raise SystemExit(f"  FAIL {rel}:{n}: a curl download this test cannot read: {line.strip()}")
+            yield f"{rel}:{n}", shlex.split(m.group(1)), url
 def main() -> int:
+    fails, found = [], list(downloads())
     server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FlakyOnce)
     threading.Thread(target=server.serve_forever, daemon=True).start()
-    fails, found = [], list(downloads())
-    if len(found) < 15:
+    if len(found) < 17:
```

The excerpt above leaves out the docstring and README hunks. The file has them.

### #610 before and after (the real test, binding 127.0.0.1, curl 8.7.1, macOS)

| Run | Output file in `review-610/r2-outputs/` | Result |
|---|---|---|
| Head's test, as is | `before-head-as-is.txt` | `15 downloads, 0 failed`, exit 0. Both CNPG lines are missed. |
| Head plus the new scanner only (scripts unchanged) | `before-new-scanner-head-scripts.txt` | `FAIL deploy/kind-test.sh:50 ... exit 22` and `FAIL deploy/tests/kind-test-stubbed.sh:22 ... exit 22`, then `17 downloads, 2 failed`, exit 1 |
| Full patch | `after.txt` | `17 downloads, 0 failed`, exit 0 |
| `ci-guard.py` on head and on r2 (Python 3.13 with PyYAML 6.0.2) | `ci-guard-head.txt`, `ci-guard-r2.txt` | `ci cases failed: 0`, exit 0, both |
| `deploy/tests/kind-test-stubbed.sh` on r2 (real CNPG download, everything else stubbed) | `kind-test-stubbed-r2.txt` | 48 ok, `wrong: 0`, exit 0, 2 min 47 s |
| `shellcheck` 0.11.0 on both changed scripts | (not saved) | clean |

The scanner mutants (`mutants.txt`) each add one line to `kind-test.sh`:

| Mutant line | Result |
|---|---|
| `curl -fsSL -o "$T/new" URL` | Found; `FAIL ... exit 22`; 18 downloads |
| `curl -fsSL URL -o "$T/new"` | Found; `FAIL ... exit 22`; 18 downloads |
| `--output`, `-O`, `URL \| tar xz`, `-o f -H "X: y" URL` | Each one: `FAIL ...: a curl download this test cannot read`, exit 1 |
| `CODE=$(curl -s -o /dev/null -w ... )` (a probe) | Skipped; exit 0 |

The mutants and the new-scanner "before" run ran before the last docstring rewrap. That edit changed only comment text.

### Tree-wide check for other curl or wget downloads (head)

These locations were searched: `deploy/`, `scripts/`, `.github/` (three workflows), `cmapi/Containerfile`,
`cmapi-portal-ui/Containerfile` and `examples/cluster-configs/.github`.

- **Downloads:** the 17 covered by the test are the only curl or wget downloads.
- **Probes and API calls, not downloads:**
  - `deploy/secrets.sh:59` (`-w`);
  - `deploy/crc-trust.sh:59`;
  - `deploy/crc-rollback.sh:31-32`;
  - `deploy/crc-proof.sh:18,23,113` and the `wget -O /dev/null` lines at 133-139;
  - `deploy/kind-import/up.sh:39`;
  - `deploy/kind-test.sh:136,209-220`;
  - `deploy/tests/np-reach-test.sh:45-64`;
  - the stub writers and printf lines in `deploy/tests/*`;
  - `deploy/helm/cmapi/templates/NOTES.txt:11`, a user hint.
- **Nothing to check:** `cmapi-portal-ui/Containerfile` has no curl, wget or `ADD http`. `.github/workflows/values-contract-report.yml`
  has none.
- **Python `urllib`:** `deploy/crc-guard.py` and `deploy/oidc-login.py` make API calls, not artifact downloads.
- **Outside the brief's scope:** `examples/local/run.sh:41` already has `--retry 3`.

**Limits of the scanner:**

- It reads only the six listed files, not the whole tree.
- A download read into a variable (`x=$(curl -fsSL url)`) counts as a probe.
- A flag with a non-numeric value placed before the URL in `URL -o` order (`-H "X: y" URL -o f`) is mis-split. The replay
  then fails, so this errs toward failing, not passing.

## #608: runs

The setup:

- `review-608/r2/` is a copy of head. Its `cmapi-portal-ui/node_modules` is a real directory of per-entry symlinks into
  `wt-600/cmapi-portal-ui/node_modules`, which has a lockfile identical to head's.
- A single symlink would have let Vite write `node_modules/.vite-temp` inside the wt-600 worktree. With this setup, Vite
  wrote it in r2's own directory. wt-600's `.vite-temp` is unchanged (mtime 13:08).
- Base and head differ only in `tests/api/portal.test.mjs`, so one build (`tsc --noEmit && vite build`, `build.txt`)
  served both. Base's test file ran from a temporary copy in r2's `tests/api/`, which was removed afterwards.
- The gate was `r2-work/run608.sh`, one background run: no `[p]ytest tests/service`, no `[n]npm test`, and a 1-minute
  load under 8. It opened at 21:42:10Z with load `7.74`.

The runs used `CHECK="20 Policies: the clusters"` and headless chromium 156.0.8078.4. Outputs are in
`review-608/r2-outputs/`:

| Copy | Runs | Result |
|---|---|---|
| Base check with the injection | 3 | 3 `not ok`, at `portal.r2-base-inject.mjs:3616:12` (base line 3615, the Show failures read). The actual rows begin `'accounts-api-dev'`, the unfiltered rows. |
| Head check with the injection | 3 | 3 ok |
| Base check, no injection | 3 | 3 ok (the race does not show locally without the delay) |
| Head check, no injection | 3 | 3 ok |
| Head, the whole `tests/api/portal.test.mjs` | 1 | `portal on the API: 139 checks`, 0 `not ok`, exit 0. Both check 20 cases, all four 407 Policies cases and check 24 (Capacity) pass. |

## Ran and not run

- **Ran:**
  - #610: everything in the tables above.
  - #608: everything in the tables above.
- **Not run:**
  - `npm test` in full, because the portal's other suites (behaviour, parity, contract) were outside this change.
  - The Chrome channel (`PW_CHANNEL=chrome`).
  - CI and image builds.
  - `deploy/kind-test.sh` against a real kind cluster.
  - The live curl test on Linux, where CI runs it. It ran only with macOS curl 8.7.1.
  - Re-fetching curl's manual: the `--retry`-covers-503 claim rests on the implementer's and Codex's fetched quote, and on
    the measured exit 0 after a 503 shown above.
