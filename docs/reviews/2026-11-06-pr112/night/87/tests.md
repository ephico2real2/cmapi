MEASURED — All test commands below use Python `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/87a649b8-ffcb-4a8a-b61b-8ed3c119287a/scratchpad/pr112/venv/bin/python` and working folder `./head/cmapi`.

MEASURED — `report/run-tests.sh` expands to: `KUBECONFIG=<review-root>/empty-kubeconfig TMPDIR=<review-root>/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r87 <python> -m pytest <arguments> -q -W ignore -p no:cacheprovider`. `<review-root>` is `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/87a649b8-ffcb-4a8a-b61b-8ed3c119287a/scratchpad/codex-87`. Invocations of the wrapper below start in that root; pytest starts in `head/cmapi`.

MEASURED — Baseline service command: `PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r87 <python> -m pytest tests/service -q -W ignore -p no:cacheprovider`, with the same KUBECONFIG, TMPDIR and PYTHONDONTWRITEBYTECODE environment. Running; output in `logs/baseline-service.log`.

MEASURED — C1 command: `sh report/run-tests.sh ../../report/tests/test_c1.py`. Exit 0. Output: `9 passed in 2.02s`. Full output: `logs/C1.log`. Tests execute the real provider using HTTP MockTransport; no real GitHub.

MEASURED — C2 command: `sh report/run-tests.sh ../../report/tests/test_c2.py`. Exit 0. Output: `12 passed in 2.05s`. Full output: `logs/C2.log`. Folder/environment as above.

MEASURED — C3 baseline command: `sh report/run-tests.sh ../../report/tests/test_c3.py`. Exit 1. Output: `1 failed in 2.33s`; observed success instead of failure for the hidden suite. Full traceback: `logs/C3-before.log`.

MEASURED — Initial C3 isolated command: `REVIEW_TREE=report/work-C3 sh report/run-tests.sh tests/service/test_review_r87_c3.py tests/service/test_github_check_runs.py`. Exit 1: `3 failed, 78 passed, 2 errors in 14.70s`. Log: `logs/C3-after.log`. This command mistakenly overlapped the still-running baseline suite on the same database; database-backed results are contaminated and will be rerun serially. The reviewer caused the overlap; it is not evidence of a production defect.

MEASURED — C3 isolated provider command: `REVIEW_TREE=report/work-C3 sh report/run-tests.sh ../../tests/test_c3.py` (pytest folder `report/work-C3/cmapi`, environment otherwise identical). Exit 0. Output: `1 passed in 3.08s`; log `logs/C3-after-provider.log`. No database fixture used.

MEASURED — C3 patch command, from review root: `patch -d head -p1 --fuzz=0 --dry-run < report/patches/C3.patch`. Exit 0, all three paths accepted. Output: `logs/C3-patch.log`.

MEASURED — C4 command: `sh report/run-tests.sh ../../report/tests/test_c4.py`. Exit 0. Output: `16 passed in 2.68s`; log `logs/C4.log`. Folder/environment as at top.
