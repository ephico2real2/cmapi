# #609: every download of CI and of the cmapi image retries a transient answer

The implementer's record: Opus 5.5 at `high`, 2026-11-23, on `fix/609-download-retry` from `05f0747`. The reviews go
beside it when they are done.

**Measured.** PR #608 (a test-only change), run 45248911791, job `images-pr (cmapi, ...)`, 2026-11-23 19:26Z:
`curl: (22) The requested URL returned error: 503` on the Kyverno CLI release, then `ERROR: failed to build`.

**Source**, fetched 2026-11-23: curl's manual, `--retry` (`curl/curl`, `docs/cmdline-opts/retry.md`, branch `master`;
<https://curl.se/docs/manpage.html#--retry>): "If a transient error is returned when curl tries to perform a transfer, it
retries this number of times before giving up. ... Transient error means either: a timeout, an FTP 4xx response code or
an HTTP 408, 429, 500, 502, 503, 504, 522 or 524 response code." It waits one second, then doubles the wait, and
"Before retrying, curl removes data that the failed attempt wrote to an output file set with --output".

| Option | Why not, or why |
|---|---|
| **`--retry 5` on each download** | Chosen. Five tries take about 31 s of backoff (1+2+4+8+16) at most, and honour `Retry-After`. Each download writes with `-o`, so a retry starts from an empty file, and each is still checked by its SHA-256 |
| `--retry-all-errors` | Retries a 404 and every other failure too, which hides a wrong URL or version for 31 s and then fails anyway |
| A retry loop in shell | More lines in 17 places for what one flag does |
| Re-running the job by hand | The symptom; the next 503 fails another PR |

**Where.** 17 downloads: `cmapi/Containerfile` (5), `.github/workflows/ci.yml` (7), `api-contract-report.yml` (1), the
example config repo's `examples/cluster-configs/.github/workflows/ci.yml` (2), and the CNPG manifest in
`deploy/tests/kind-test-stubbed.sh` (which the manifests job runs) and `deploy/kind-test.sh` (1 each; added in review, by
reviewer 1). Not changed: `examples/local/INSTALL.md`,
which a person runs and re-runs, and the review records.

**Tests.**

| Test | Before (`05f0747`) | After |
|---|---|---|
| `deploy/tests/download-retry-test.py`: each of the 15 commands, with its own flags, against a local server that answers 503 once per path | 15 of 15 fail, curl exit 22 | 15 of 15 pass, exit 0 with the file's bytes |
| The same test after review: 17 commands, `<url> -o <file>` read too, and a curl download it cannot read fails the test by line | on `1c0d1d4`'s scripts: 17 found, the 2 CNPG downloads fail, curl exit 22 | 17 of 17 pass |
| `deploy/tests/ci-guard.py`: the manifests job's downloads are found with `--retry`, verified by SHA-256, and the new test runs in the job | the old pattern finds 0 downloads in the new `ci.yml` | passes, 4 downloads |
