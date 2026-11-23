## PR #608 — source assessment supports the fix; runtime verification incomplete

Paths below are relative to `review-608/head/`.

| Question | Verdict and evidence |
|---|---|
| Is `aria-busy` the right condition? | **Confirmed for the placeholder-data case.** `src/api/hooks.ts:540` includes filters/cursor in the query key; line 547 uses `keepPreviousData`; line 90 maps `isPlaceholderData` to `refreshing`. `PoliciesTab.tsx:103` derives `busy`, and lines 199–203 pass both that marker and the displayed items to `DataTable`. `src/components/ui.tsx:304` renders `aria-busy={busy \|\| undefined}`. This matches [TanStack’s v5 pagination semantics](https://tanstack.com/query/latest/docs/framework/react/guides/paginated-queries). |
| Correct at every current helper call? | **Confirmed by source inspection.** All three calls target **Failing resources**: `tests/api/portal.test.mjs:3611`, `3617`, `3622`. That table receives `busy`. The helper would not provide this guarantee for **Clusters** or **Results by policy**, whose tables omit `busy` (`PoliciesTab.tsx:162`, `222`). |
| Can busy be absent before fetching starts? | **Refuted for the proposed query-render/fetch-start gap.** TanStack computes the optimistic result during render, before the effect that applies observer options; placeholder data already carries `isPlaceholderData=true`. See [`useBaseQuery`](https://raw.githubusercontent.com/TanStack/query/main/packages/react-query/src/useBaseQuery.ts), lines 97–102, and [`QueryObserver`](https://raw.githubusercontent.com/TanStack/query/main/packages/query-core/src/queryObserver.ts), lines 601–637. The updated policy heading and busy table therefore render together. The chip updates route state directly, without a fetch-start effect (`src/portal/route.ts:36–41`; `PoliciesTab.tsx:88–97`). **Qualification:** this is source reasoning, not a browser reproduction; the exact pinned 5.107.1 sources were unavailable at the attempted versioned URLs. |
| Does it time out clearly? | **Confirmed bounded; diagnostic wording unverified.** `fresh()` sets an 8,000 ms default timeout (`portal.test.mjs:48`); `settledRows` calls locator `waitFor()` at line 3551. Its selector names the table and excludes busy state. There is also a named 90-second check deadline at lines 147–171. I could not observe the actual Playwright timeout message. |
| Any other one-shot reads? | **Confirmed.** The Capacity focus/304 case reads `tableRows` once at `portal.test.mjs:4358`. Lines 4352–4357 establish server-side activity, not browser query completion. Because the expected rows remain identical, that assertion can pass before the browser processes the 304. Other one-shot helpers also exist: Requests at line 63, Quotas at 2144, Expiration at 2850. Their existence alone does not establish the same filter-change flake. |
| Are moving `sentPol` assertions justified? | **Confirmed.** They now follow settlement at lines 3617–3618 and 3622–3623. The stand-in records the request before delaying or holding its answer (`tests/api/standin.mjs:923–925`). |

No demonstrated defect in the changed helper warrants a fix.

**Verification limits:** Node dependency resolution returned:

```text
ERR_MODULE_NOT_FOUND playwright
ERR_MODULE_NOT_FOUND @tanstack/react-query
ERR_MODULE_NOT_FOUND @axe-core/playwright
```

I could not run the portal suite, reproduce the flake, or verify timeout diagnostics. I also did not finish reading all 5,146 lines of `portal.test.mjs` and all 1,396 lines of `standin.mjs`; therefore this is **not a completed full-file/exhaustive suite review** under your grounding requirement. The conclusions above are limited to the inspected code and cited evidence.

## PR #610 — request changes: two CNPG downloads remain uncovered

Paths below are relative to `review-610/head/`.

| Question | Verdict and evidence |
|---|---|
| Were all 15 stated command sites changed? | **Confirmed.** Executing the new test’s discovery function found 15 commands, each with retry count `5`: Containerfile 5, main CI 7, contract-report workflow 1, example workflow 2. These are command sites; the Containerfile schema loop downloads five separate files (`cmapi/Containerfile:43–51`). |
| Are all curl/wget downloads covered? | **Refuted — finding below.** `deploy/kind-test.sh:50` and `deploy/tests/kind-test-stubbed.sh:22` both download CNPG without retry. The latter runs in CI at `.github/workflows/ci.yml:384–385`. The inspected wget commands are connectivity probes, for example `deploy/kind-test.sh:136` and `deploy/crc-proof.sh:133–139`. |
| Is `--retry 5` sufficient? | **Confirmed for the reported 503.** The [curl manual](https://curl.se/docs/manpage.html#--retry) explicitly includes 503 among retryable responses. `--retry-connrefused` additionally covers refused connections; `--retry-all-errors` broadens retrying to all errors. Neither is required to fix a 503. Five retries permit six attempts. |
| Do checksums remain? | **Confirmed for all 15 changed sites.** Downloads are followed by verification in `cmapi/Containerfile:34–51`; `.github/workflows/ci.yml:39–40`, `86–87`, `303–304`, `359–371`, `430–431`; `.github/workflows/api-contract-report.yml:117–118`; and `examples/cluster-configs/.github/workflows/ci.yml:25–26`, `47–48`. CNPG also remains checksum-checked at `deploy/kind-test.sh:51`, including when exercised through the stubbed test. |
| Does CI run and guard the new test? | **Confirmed.** Workflow lines 380–381 execute it; `deploy/tests/ci-guard.py:27–28` checks its presence. Running the guard with the supplied Python exited **0**, printing `4 downloads`, `the job runs deploy/tests/download-retry-test.py`, and `ci cases failed: 0`. |
| Could the test miss a retry-less download? | **Confirmed.** Its file allowlist omits both CNPG scripts (`download-retry-test.py:21–22`), and its regex requires output-before-URL ordering (`:25`). Discovery returned `matched=False` for both actual CNPG commands. A synthetic `curl -fsSL https://example.test/new-tool -o new-tool` also returned `False`, while the existing count remained 15 and satisfied the guard (`:71`). Removing retry from one of the currently recognized 15 does **not** evade extraction; its live 503 case should then fail. |

**Finding — P2: CI still has an unprotected download, and the regression test excludes it.**

A transient 503 fetching CNPG can still fail the manifests job through `kind-test-stubbed.sh`. Both real CNPG download sites need retries, and the test needs to discover their URL-before-output syntax.

Full replacement commands:

```bash
# deploy/kind-test.sh:50
curl -fsSL --retry 5 "$CNPG_URL" -o "$T/cnpg.yaml"
```

```bash
# deploy/tests/kind-test-stubbed.sh:22
curl -fsSL --retry 5 "$(sed -n 's/^CNPG_URL=//p' "$SRC/kind-test.sh")" -o "$KT_CNPG" || { echo "ERROR: could not download the CNPG manifest" >&2; exit 1; }
```

Replace `DOWNLOAD` and `downloads()` in `deploy/tests/download-retry-test.py` with the following. Existing imports and `FILES` remain sufficient. This deliberately supports the current command forms and rejects unsupported forms in the selected download inventory.

```python
DOWNLOAD = re.compile(
    r"\bcurl((?:\s+(?!-o\b)-[-\w]+(?:\s+\d+)?)*)\s+"
)


def downloads():
    files = FILES + [
        "deploy/kind-test.sh",
        "deploy/tests/kind-test-stubbed.sh",
    ]
    for rel in files:
        with open(os.path.join(ROOT, rel)) as stream:
            for n, line in enumerate(stream, 1):
                if (
                    line.lstrip().startswith("#")
                    or not re.search(r"\bcurl\s", line)
                ):
                    continue

                # These scripts also contain API/connectivity probes.
                if rel.startswith("deploy/") and "CNPG_URL" not in line:
                    continue

                m = DOWNLOAD.search(line)
                if not m or not re.search(
                    r"(?:^|\s)-o\s+\S+", line[m.end():]
                ):
                    raise AssertionError(
                        f"{rel}:{n}: unsupported download: {line.strip()}"
                    )

                yield (
                    f"{rel}:{n}",
                    shlex.split(m.group(1)),
                    line[m.end():].strip(),
                )
```

Replace the count check in `main()`:

```python
    if len(found) < 17:
        print(
            f"  FAIL only {len(found)} downloads found: "
            "the pattern no longer matches the files"
        )
        fails.append("count")
```

Failing-first inventory test, runnable without sockets or downloads from the export’s `head/`:

```python
import runpy

m = runpy.run_path(
    "deploy/tests/download-retry-test.py",
    run_name="review_inventory",
)
found = list(m["downloads"]())

assert len(found) == 17, (
    f"expected 17 downloads, got {len(found)}"
)

for where, flags, _ in found:
    assert "--retry" in flags, where
    assert int(flags[flags.index("--retry") + 1]) > 0, where

print("PASS: 17 downloads with retry")
```

I ran the inventory test against the original definitions, then the proposed definitions and command changes using in-memory file snapshots—no export edits. Observed output:

```text
before: FAIL: expected 17 downloads, got 15
scanner fixed only: FAIL: deploy/kind-test.sh:50
after full fix: PASS (17 downloads with retry)
mutant rejected: deploy/kind-test.sh:50
mutant rejected: deploy/tests/kind-test-stubbed.sh:22
additional retry-less command discovered: 18 True
```

The mutants removed retry independently from each added CNPG command. This proves discovery and retry-policy coverage; it does **not** substitute for the live curl test.

**Verification limits:** Running the supplied `download-retry-test.py` exited **1 before any transfer**, at line 55:

```text
PermissionError: [Errno 1] Operation not permitted
```

The sandbox denies local server binding and writes inside the exports; a write probe likewise returned `Operation not permitted`. Consequently, I could not show live 503 failure-before/success-after, build images, or execute CI. No git commands or pushes were performed, and no files were changed.

Codex session ID: 01a20a3e-3c85-7442-84bf-478ce6cc1fa4
Resume in Codex: codex resume 01a20a3e-3c85-7442-84bf-478ce6cc1fa4
