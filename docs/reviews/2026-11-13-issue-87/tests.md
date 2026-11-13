MEASURED — Commands below run sequentially using the supplied virtual environment. Only the two authorized existing test files and review-added files are selected. Database reset is exclusively the existing pytest fixture; no manual database cleanup, containers, installation, commits, or pushes.

MEASURED — baseline

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_github_check_runs.py tests/service/test_review_r87_c3.py -q -W ignore -p no:cacheprovider
```

Full output:

```text
........................................................................ [ 85%]
............                                                             [100%]
84 passed in 14.78s

```

Exit status: 0

MEASURED — c6-before

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_review_r87_c5_c8.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
F....s.s.sF..............                                                [100%]
=================================== FAILURES ===================================
___________ test_completed_run_without_a_conclusion_remains_pending ____________
tests/service/test_review_r87_c5_c8.py:14: in test_completed_run_without_a_conclusion_remains_pending
    assert checks(runs=[run(CONTEXT_KYVERNO, conclusion=None)]) == {
E   AssertionError: assert {'ci/kyverno': 'failure'} == {'ci/kyverno': 'pending'}
E     
E     Differing items:
E     {'ci/kyverno': 'failure'} != {'ci/kyverno': 'pending'}
E     Use -v to get more diff
___ test_only_cmapi_and_one_ci_green_cannot_merge[completed-null-check-run] ____
tests/service/test_review_r87_c5_c8.py:45: in test_only_cmapi_and_one_ci_green_cannot_merge
    assert status(client, keys, rid)['status'] == 'pr_open'
E   AssertionError: assert 'failed' == 'pr_open'
E     
E     - pr_open
E     + failed
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:02:48.800207Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 198.0, "event": "http", "request_id": "e26cc75bd72749dd", "level": "info", "timestamp": "2026-11-13T14:02:49.050599Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:02:49.170940Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 15.4, "event": "http", "request_id": "217b22338596426d", "level": "info", "timestamp": "2026-11-13T14:02:49.280294Z"}
=========================== short test summary info ============================
FAILED tests/service/test_review_r87_c5_c8.py::test_completed_run_without_a_conclusion_remains_pending
FAILED tests/service/test_review_r87_c5_c8.py::test_only_cmapi_and_one_ci_green_cannot_merge[completed-null-check-run]
2 failed, 20 passed, 3 skipped in 18.14s

```

Exit status: 1

MEASURED — M1-ignore-check-runs

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_github_check_runs.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
FFFFFFFFFFFFFFFFFFFFFFFFFFFFF.....F...F.FFFFFFFFFFF.F.FFFFF....FF...FFFF [ 86%]
FFFFF.FFF..                                                              [100%]
=================================== FAILURES ===================================
_________ test_no_statuses_and_two_successful_check_runs_read_as_green _________
tests/service/test_github_check_runs.py:75: in test_no_statuses_and_two_successful_check_runs_read_as_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, id=1), run(CONTEXT_KYVERNO, id=2)]) == {
E   AssertionError: assert {} == {'ci/kubeconf...o': 'success'}
E     
E     Right contains 2 more items:
E     {'ci/kubeconform': 'success', 'ci/kyverno': 'success'}
E     Use -v to get more diff
________ test_a_completed_run_that_is_not_success_is_not_green[failure] ________
tests/service/test_github_check_runs.py:85: in test_a_completed_run_that_is_not_success_is_not_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
_______ test_a_completed_run_that_is_not_success_is_not_green[cancelled] _______
tests/service/test_github_check_runs.py:85: in test_a_completed_run_that_is_not_success_is_not_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
_______ test_a_completed_run_that_is_not_success_is_not_green[timed_out] _______
tests/service/test_github_check_runs.py:85: in test_a_completed_run_that_is_not_success_is_not_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
____ test_a_completed_run_that_is_not_success_is_not_green[action_required] ____
tests/service/test_github_check_runs.py:85: in test_a_completed_run_that_is_not_success_is_not_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
_________ test_a_completed_run_that_is_not_success_is_not_green[stale] _________
tests/service/test_github_check_runs.py:85: in test_a_completed_run_that_is_not_success_is_not_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
____ test_a_completed_run_that_is_not_success_is_not_green[startup_failure] ____
tests/service/test_github_check_runs.py:85: in test_a_completed_run_that_is_not_success_is_not_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
________ test_a_completed_run_that_is_not_success_is_not_green[neutral] ________
tests/service/test_github_check_runs.py:85: in test_a_completed_run_that_is_not_success_is_not_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
________ test_a_completed_run_that_is_not_success_is_not_green[skipped] ________
tests/service/test_github_check_runs.py:85: in test_a_completed_run_that_is_not_success_is_not_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
_________ test_a_completed_run_that_is_not_success_is_not_green[None] __________
tests/service/test_github_check_runs.py:85: in test_a_completed_run_that_is_not_success_is_not_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
_ test_a_completed_run_that_is_not_success_is_not_green[a-conclusion-github-adds-later] _
tests/service/test_github_check_runs.py:85: in test_a_completed_run_that_is_not_success_is_not_green
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-queued] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-in_progress] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-waiting] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-requested] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-pending] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-a-status-github-adds-later] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-queued] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-in_progress] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-waiting] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-requested] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-pending] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-a-status-github-adds-later] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-queued] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-in_progress] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-waiting] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-requested] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-pending] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-a-status-github-adds-later] _
tests/service/test_github_check_runs.py:91: in test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says
    assert checks(runs=[run(CONTEXT_KUBECONFORM, status=state, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: "pending"}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_a_status_and_a_run_of_one_name_merge_to_the_worst[success-from_run1-failure] _
tests/service/test_github_check_runs.py:111: in test_a_status_and_a_run_of_one_name_merge_to_the_worst
    assert checks(statuses=[st(CONTEXT_KYVERNO, from_status)], runs=[run(CONTEXT_KYVERNO, **from_run)]) == {CONTEXT_KYVERNO: expected}
E   AssertionError: assert {'ci/kyverno': 'success'} == {'ci/kyverno': 'failure'}
E     
E     Differing items:
E     {'ci/kyverno': 'success'} != {'ci/kyverno': 'failure'}
E     Use -v to get more diff
_ test_a_status_and_a_run_of_one_name_merge_to_the_worst[success-from_run5-pending] _
tests/service/test_github_check_runs.py:111: in test_a_status_and_a_run_of_one_name_merge_to_the_worst
    assert checks(statuses=[st(CONTEXT_KYVERNO, from_status)], runs=[run(CONTEXT_KYVERNO, **from_run)]) == {CONTEXT_KYVERNO: expected}
E   AssertionError: assert {'ci/kyverno': 'success'} == {'ci/kyverno': 'pending'}
E     
E     Differing items:
E     {'ci/kyverno': 'success'} != {'ci/kyverno': 'pending'}
E     Use -v to get more diff
_ test_a_status_and_a_run_of_one_name_merge_to_the_worst[pending-from_run7-failure] _
tests/service/test_github_check_runs.py:111: in test_a_status_and_a_run_of_one_name_merge_to_the_worst
    assert checks(statuses=[st(CONTEXT_KYVERNO, from_status)], runs=[run(CONTEXT_KYVERNO, **from_run)]) == {CONTEXT_KYVERNO: expected}
E   AssertionError: assert {'ci/kyverno': 'pending'} == {'ci/kyverno': 'failure'}
E     
E     Differing items:
E     {'ci/kyverno': 'pending'} != {'ci/kyverno': 'failure'}
E     Use -v to get more diff
__ test_other_names_stay_apart_and_a_context_nobody_reported_is_not_invented ___
tests/service/test_github_check_runs.py:116: in test_other_names_stay_apart_and_a_context_nobody_reported_is_not_invented
    assert got == {CONTEXT_CMAPI: "success", CONTEXT_KUBECONFORM: "success"}
E   AssertionError: assert {'cmapi/check': 'success'} == {'ci/kubeconf...k': 'success'}
E     
E     Omitting 1 identical items, use -vv to show
E     Right contains 1 more item:
E     {'ci/kubeconform': 'success'}
E     Use -v to get more diff
_______________ test_it_asks_for_the_latest_runs_of_the_pr_head ________________
tests/service/test_github_check_runs.py:123: in test_it_asks_for_the_latest_runs_of_the_pr_head
    asked = next(r for r in seen if r.url.path.endswith("/check-runs"))
E   StopIteration
_ test_a_rerun_in_one_suite_replaces_the_attempt_before_it[older0-newer0-success] _
tests/service/test_github_check_runs.py:135: in test_a_rerun_in_one_suite_replaces_the_attempt_before_it
    assert checks(runs=[run(CONTEXT_KUBECONFORM, **older), run(CONTEXT_KUBECONFORM, **newer)]) == {CONTEXT_KUBECONFORM: expected}
E   AssertionError: assert {} == {'ci/kubeconform': 'success'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'success'}
E     Use -v to get more diff
_ test_a_rerun_in_one_suite_replaces_the_attempt_before_it[older1-newer1-success] _
tests/service/test_github_check_runs.py:135: in test_a_rerun_in_one_suite_replaces_the_attempt_before_it
    assert checks(runs=[run(CONTEXT_KUBECONFORM, **older), run(CONTEXT_KUBECONFORM, **newer)]) == {CONTEXT_KUBECONFORM: expected}
E   AssertionError: assert {} == {'ci/kubeconform': 'success'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'success'}
E     Use -v to get more diff
_ test_a_rerun_in_one_suite_replaces_the_attempt_before_it[older2-newer2-pending] _
tests/service/test_github_check_runs.py:135: in test_a_rerun_in_one_suite_replaces_the_attempt_before_it
    assert checks(runs=[run(CONTEXT_KUBECONFORM, **older), run(CONTEXT_KUBECONFORM, **newer)]) == {CONTEXT_KUBECONFORM: expected}
E   AssertionError: assert {} == {'ci/kubeconform': 'pending'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'pending'}
E     Use -v to get more diff
_ test_a_rerun_in_one_suite_replaces_the_attempt_before_it[older3-newer3-failure] _
tests/service/test_github_check_runs.py:135: in test_a_rerun_in_one_suite_replaces_the_attempt_before_it
    assert checks(runs=[run(CONTEXT_KUBECONFORM, **older), run(CONTEXT_KUBECONFORM, **newer)]) == {CONTEXT_KUBECONFORM: expected}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
___ test_one_name_from_another_suite_or_app_does_not_hide_a_failure[other0] ____
tests/service/test_github_check_runs.py:142: in test_one_name_from_another_suite_or_app_does_not_hide_a_failure
    assert checks(runs=runs) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
___ test_one_name_from_another_suite_or_app_does_not_hide_a_failure[other1] ____
tests/service/test_github_check_runs.py:142: in test_one_name_from_another_suite_or_app_does_not_hide_a_failure
    assert checks(runs=runs) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
___ test_one_name_from_another_suite_or_app_does_not_hide_a_failure[other2] ____
tests/service/test_github_check_runs.py:142: in test_one_name_from_another_suite_or_app_does_not_hide_a_failure
    assert checks(runs=runs) == {CONTEXT_KUBECONFORM: "failure"}
E   AssertionError: assert {} == {'ci/kubeconform': 'failure'}
E     
E     Right contains 1 more item:
E     {'ci/kubeconform': 'failure'}
E     Use -v to get more diff
_____________ test_a_failure_on_a_later_page_of_check_runs_counts ______________
tests/service/test_github_check_runs.py:149: in test_a_failure_on_a_later_page_of_check_runs_counts
    assert len(got) == 151 and got[CONTEXT_KYVERNO] == "failure"
E   assert (0 == 151)
E    +  where 0 = len({})
____ test_it_asks_for_full_pages_and_stops_when_the_link_header_has_no_next ____
tests/service/test_github_check_runs.py:162: in test_it_asks_for_full_pages_and_stops_when_the_link_header_has_no_next
    assert [(r.url.params["per_page"], r.url.params["page"]) for r in asked] == [("100", "1"), ("100", "2")]
E   AssertionError: assert [] == [('100', '1'), ('100', '2')]
E     
E     Right contains 2 more items, first extra item: ('100', '1')
E     Use -v to get more diff
______ test_a_host_that_never_stops_paging_is_an_error_not_a_partial_read ______
tests/service/test_github_check_runs.py:183: in test_a_host_that_never_stops_paging_is_an_error_not_a_partial_read
    with pytest.raises(GitUnavailable, match="pages"):
E   Failed: DID NOT RAISE <class 'cmapi.core.git.base.GitUnavailable'>
___ test_a_refused_read_raises_instead_of_reading_as_no_checks[on_runs-403] ____
tests/service/test_github_check_runs.py:193: in test_a_refused_read_raises_instead_of_reading_as_no_checks
    with pytest.raises(GitUnavailable, match=str(code)):
E   Failed: DID NOT RAISE <class 'cmapi.core.git.base.GitUnavailable'>
___ test_a_refused_read_raises_instead_of_reading_as_no_checks[on_runs-404] ____
tests/service/test_github_check_runs.py:193: in test_a_refused_read_raises_instead_of_reading_as_no_checks
    with pytest.raises(GitUnavailable, match=str(code)):
E   Failed: DID NOT RAISE <class 'cmapi.core.git.base.GitUnavailable'>
___ test_a_refused_read_raises_instead_of_reading_as_no_checks[on_runs-422] ____
tests/service/test_github_check_runs.py:193: in test_a_refused_read_raises_instead_of_reading_as_no_checks
    with pytest.raises(GitUnavailable, match=str(code)):
E   Failed: DID NOT RAISE <class 'cmapi.core.git.base.GitUnavailable'>
___ test_a_refused_read_raises_instead_of_reading_as_no_checks[on_runs-429] ____
tests/service/test_github_check_runs.py:193: in test_a_refused_read_raises_instead_of_reading_as_no_checks
    with pytest.raises(GitUnavailable, match=str(code)):
E   Failed: DID NOT RAISE <class 'cmapi.core.git.base.GitUnavailable'>
_____________________ test_a_refused_later_page_raises_too _____________________
tests/service/test_github_check_runs.py:202: in test_a_refused_later_page_raises_too
    with pytest.raises(GitUnavailable):
E   Failed: DID NOT RAISE <class 'cmapi.core.git.base.GitUnavailable'>
___________________________ test_a_5xx_is_retryable ____________________________
tests/service/test_github_check_runs.py:207: in test_a_5xx_is_retryable
    with pytest.raises(GitUnavailable):
E   Failed: DID NOT RAISE <class 'cmapi.core.git.base.GitUnavailable'>
___ test_green_from_actions_merges_and_the_worker_posts_only_the_cmapi_check ___
tests/service/test_github_check_runs.py:327: in test_green_from_actions_merges_and_the_worker_posts_only_the_cmapi_check
    assert status(client, keys, rid)["status"] == "merged"
E   AssertionError: assert 'pr_open' == 'merged'
E     
E     - merged
E     + pr_open
---------------------------- Captured stdout setup -----------------------------
migrated to head
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:03:52.918007Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 213.1, "event": "http", "request_id": "c4236c5cce6947cf", "level": "info", "timestamp": "2026-11-13T14:03:53.190653Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:53.317752Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 14.9, "event": "http", "request_id": "954897e4d7994297", "level": "info", "timestamp": "2026-11-13T14:03:53.409010Z"}
_ test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged[nothing yet] _
tests/service/test_github_check_runs.py:350: in test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged
    assert status(client, keys, rid)["status"] == "merged"
E   AssertionError: assert 'pr_open' == 'merged'
E     
E     - merged
E     + pr_open
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:03:53.761594Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 186.0, "event": "http", "request_id": "ef060f109bd64ec4", "level": "info", "timestamp": "2026-11-13T14:03:54.002675Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:54.125759Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:54.171028Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:54.209627Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 13.0, "event": "http", "request_id": "073774a3fb9a4133", "level": "info", "timestamp": "2026-11-13T14:03:54.291808Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:54.318919Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 14.8, "event": "http", "request_id": "aee9b216d1ce4c5c", "level": "info", "timestamp": "2026-11-13T14:03:54.404118Z"}
_ test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged[one still running] _
tests/service/test_github_check_runs.py:350: in test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged
    assert status(client, keys, rid)["status"] == "merged"
E   AssertionError: assert 'pr_open' == 'merged'
E     
E     - merged
E     + pr_open
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:03:54.694700Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 173.7, "event": "http", "request_id": "9ee58777f2ae4894", "level": "info", "timestamp": "2026-11-13T14:03:54.920714Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:55.053791Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:55.102665Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:55.143672Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 12.4, "event": "http", "request_id": "53fd7d4c11b648db", "level": "info", "timestamp": "2026-11-13T14:03:55.225881Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:55.251243Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 15.1, "event": "http", "request_id": "4f9abf1ea37b4a0b", "level": "info", "timestamp": "2026-11-13T14:03:55.332687Z"}
____ test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[failure] ____
tests/service/test_github_check_runs.py:361: in test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr
    assert view["status"] == "failed"
E   AssertionError: assert 'pr_open' == 'failed'
E     
E     - failed
E     + pr_open
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:03:55.634654Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 188.6, "event": "http", "request_id": "eac37729981f4c50", "level": "info", "timestamp": "2026-11-13T14:03:55.877141Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:56.015489Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 15.2, "event": "http", "request_id": "70a984faac724b52", "level": "info", "timestamp": "2026-11-13T14:03:56.112307Z"}
___ test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[timed_out] ___
tests/service/test_github_check_runs.py:361: in test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr
    assert view["status"] == "failed"
E   AssertionError: assert 'pr_open' == 'failed'
E     
E     - failed
E     + pr_open
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:03:56.416880Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 181.2, "event": "http", "request_id": "ec3fe2ce2f70424f", "level": "info", "timestamp": "2026-11-13T14:03:56.652016Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:56.775376Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 14.8, "event": "http", "request_id": "ff82cf49e9b541da", "level": "info", "timestamp": "2026-11-13T14:03:56.868283Z"}
___ test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[cancelled] ___
tests/service/test_github_check_runs.py:361: in test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr
    assert view["status"] == "failed"
E   AssertionError: assert 'pr_open' == 'failed'
E     
E     - failed
E     + pr_open
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:03:57.152990Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 178.7, "event": "http", "request_id": "b5cc8825d3da49eb", "level": "info", "timestamp": "2026-11-13T14:03:57.384691Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:57.519054Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 15.6, "event": "http", "request_id": "af48ebad4d944994", "level": "info", "timestamp": "2026-11-13T14:03:57.614296Z"}
____ test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[skipped] ____
tests/service/test_github_check_runs.py:361: in test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr
    assert view["status"] == "failed"
E   AssertionError: assert 'pr_open' == 'failed'
E     
E     - failed
E     + pr_open
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:03:57.912628Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 173.8, "event": "http", "request_id": "7c2a6eee1dd94cc9", "level": "info", "timestamp": "2026-11-13T14:03:58.138545Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:58.257872Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 15.8, "event": "http", "request_id": "b677bd92803a4944", "level": "info", "timestamp": "2026-11-13T14:03:58.351037Z"}
____ test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[neutral] ____
tests/service/test_github_check_runs.py:361: in test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr
    assert view["status"] == "failed"
E   AssertionError: assert 'pr_open' == 'failed'
E     
E     - failed
E     + pr_open
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:03:58.634642Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 175.3, "event": "http", "request_id": "0e0ee5459f444160", "level": "info", "timestamp": "2026-11-13T14:03:58.862338Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:58.987311Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 15.8, "event": "http", "request_id": "02bafda9207f46ec", "level": "info", "timestamp": "2026-11-13T14:03:59.081801Z"}
__________ test_a_failure_does_not_wait_for_the_other_check_to_finish __________
tests/service/test_github_check_runs.py:371: in test_a_failure_does_not_wait_for_the_other_check_to_finish
    assert status(client, keys, rid)["status"] == "failed"
E   AssertionError: assert 'pr_open' == 'failed'
E     
E     - failed
E     + pr_open
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:03:59.513934Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 175.5, "event": "http", "request_id": "9258c0b38eb44e87", "level": "info", "timestamp": "2026-11-13T14:03:59.741895Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:03:59.860172Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 14.3, "event": "http", "request_id": "66c2c8d2fd7742e6", "level": "info", "timestamp": "2026-11-13T14:03:59.951811Z"}
_______________ test_green_ci_does_not_excuse_a_head_that_moved ________________
tests/service/test_github_check_runs.py:394: in test_green_ci_does_not_excuse_a_head_that_moved
    assert status(client, keys, rid)["status"] == "failed" and host.merge_refused == 0
E   AssertionError: assert ('pr_open' == 'failed'
E     
E     - failed
E     + pr_open)
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:04:00.948581Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 190.3, "event": "http", "request_id": "b7e0172809884f64", "level": "info", "timestamp": "2026-11-13T14:04:01.190764Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:01.327475Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 14.2, "event": "http", "request_id": "dee3fe63707748cc", "level": "info", "timestamp": "2026-11-13T14:04:01.419185Z"}
____ test_the_workers_own_validator_can_still_stop_a_merge_when_ci_is_green ____
tests/service/test_github_check_runs.py:406: in test_the_workers_own_validator_can_still_stop_a_merge_when_ci_is_green
    assert status(client, keys, rid)["status"] == "failed" and host.posted == [CONTEXT_CMAPI]
E   AssertionError: assert ('pr_open' == 'failed'
E     
E     - failed
E     + pr_open)
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:04:01.723032Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 163.4, "event": "http", "request_id": "e3df6828ac40413d", "level": "info", "timestamp": "2026-11-13T14:04:01.938732Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:02.047835Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 12.9, "event": "http", "request_id": "40938fc6d25c4a1d", "level": "info", "timestamp": "2026-11-13T14:04:02.132952Z"}
____ test_an_app_without_checks_read_is_a_visible_failure_not_a_silent_wait ____
tests/service/test_github_check_runs.py:415: in test_an_app_without_checks_read_is_a_visible_failure_not_a_silent_wait
    assert still and attempts == 1 and "403" in why and "check-runs" in why, why
E   AssertionError: waiting for ci/kubeconform, ci/kyverno from the Git host's CI
E   assert (True and 0 == 1)
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:04:02.408009Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 164.5, "event": "http", "request_id": "949f18be09d1486d", "level": "info", "timestamp": "2026-11-13T14:04:02.624680Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:02.735932Z"}
=========================== short test summary info ============================
FAILED tests/service/test_github_check_runs.py::test_no_statuses_and_two_successful_check_runs_read_as_green
FAILED tests/service/test_github_check_runs.py::test_a_completed_run_that_is_not_success_is_not_green[failure]
FAILED tests/service/test_github_check_runs.py::test_a_completed_run_that_is_not_success_is_not_green[cancelled]
FAILED tests/service/test_github_check_runs.py::test_a_completed_run_that_is_not_success_is_not_green[timed_out]
FAILED tests/service/test_github_check_runs.py::test_a_completed_run_that_is_not_success_is_not_green[action_required]
FAILED tests/service/test_github_check_runs.py::test_a_completed_run_that_is_not_success_is_not_green[stale]
FAILED tests/service/test_github_check_runs.py::test_a_completed_run_that_is_not_success_is_not_green[startup_failure]
FAILED tests/service/test_github_check_runs.py::test_a_completed_run_that_is_not_success_is_not_green[neutral]
FAILED tests/service/test_github_check_runs.py::test_a_completed_run_that_is_not_success_is_not_green[skipped]
FAILED tests/service/test_github_check_runs.py::test_a_completed_run_that_is_not_success_is_not_green[None]
FAILED tests/service/test_github_check_runs.py::test_a_completed_run_that_is_not_success_is_not_green[a-conclusion-github-adds-later]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-queued]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-in_progress]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-waiting]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-requested]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-pending]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[None-a-status-github-adds-later]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-queued]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-in_progress]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-waiting]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-requested]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-pending]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[success-a-status-github-adds-later]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-queued]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-in_progress]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-waiting]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-requested]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-pending]
FAILED tests/service/test_github_check_runs.py::test_an_unfinished_run_is_pending_whatever_its_conclusion_field_says[failure-a-status-github-adds-later]
FAILED tests/service/test_github_check_runs.py::test_a_status_and_a_run_of_one_name_merge_to_the_worst[success-from_run1-failure]
FAILED tests/service/test_github_check_runs.py::test_a_status_and_a_run_of_one_name_merge_to_the_worst[success-from_run5-pending]
FAILED tests/service/test_github_check_runs.py::test_a_status_and_a_run_of_one_name_merge_to_the_worst[pending-from_run7-failure]
FAILED tests/service/test_github_check_runs.py::test_other_names_stay_apart_and_a_context_nobody_reported_is_not_invented
FAILED tests/service/test_github_check_runs.py::test_it_asks_for_the_latest_runs_of_the_pr_head
FAILED tests/service/test_github_check_runs.py::test_a_rerun_in_one_suite_replaces_the_attempt_before_it[older0-newer0-success]
FAILED tests/service/test_github_check_runs.py::test_a_rerun_in_one_suite_replaces_the_attempt_before_it[older1-newer1-success]
FAILED tests/service/test_github_check_runs.py::test_a_rerun_in_one_suite_replaces_the_attempt_before_it[older2-newer2-pending]
FAILED tests/service/test_github_check_runs.py::test_a_rerun_in_one_suite_replaces_the_attempt_before_it[older3-newer3-failure]
FAILED tests/service/test_github_check_runs.py::test_one_name_from_another_suite_or_app_does_not_hide_a_failure[other0]
FAILED tests/service/test_github_check_runs.py::test_one_name_from_another_suite_or_app_does_not_hide_a_failure[other1]
FAILED tests/service/test_github_check_runs.py::test_one_name_from_another_suite_or_app_does_not_hide_a_failure[other2]
FAILED tests/service/test_github_check_runs.py::test_a_failure_on_a_later_page_of_check_runs_counts
FAILED tests/service/test_github_check_runs.py::test_it_asks_for_full_pages_and_stops_when_the_link_header_has_no_next
FAILED tests/service/test_github_check_runs.py::test_a_host_that_never_stops_paging_is_an_error_not_a_partial_read
FAILED tests/service/test_github_check_runs.py::test_a_refused_read_raises_instead_of_reading_as_no_checks[on_runs-403]
FAILED tests/service/test_github_check_runs.py::test_a_refused_read_raises_instead_of_reading_as_no_checks[on_runs-404]
FAILED tests/service/test_github_check_runs.py::test_a_refused_read_raises_instead_of_reading_as_no_checks[on_runs-422]
FAILED tests/service/test_github_check_runs.py::test_a_refused_read_raises_instead_of_reading_as_no_checks[on_runs-429]
FAILED tests/service/test_github_check_runs.py::test_a_refused_later_page_raises_too
FAILED tests/service/test_github_check_runs.py::test_a_5xx_is_retryable - Fai...
FAILED tests/service/test_github_check_runs.py::test_green_from_actions_merges_and_the_worker_posts_only_the_cmapi_check
FAILED tests/service/test_github_check_runs.py::test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged[nothing yet]
FAILED tests/service/test_github_check_runs.py::test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged[one still running]
FAILED tests/service/test_github_check_runs.py::test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[failure]
FAILED tests/service/test_github_check_runs.py::test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[timed_out]
FAILED tests/service/test_github_check_runs.py::test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[cancelled]
FAILED tests/service/test_github_check_runs.py::test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[skipped]
FAILED tests/service/test_github_check_runs.py::test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[neutral]
FAILED tests/service/test_github_check_runs.py::test_a_failure_does_not_wait_for_the_other_check_to_finish
FAILED tests/service/test_github_check_runs.py::test_green_ci_does_not_excuse_a_head_that_moved
FAILED tests/service/test_github_check_runs.py::test_the_workers_own_validator_can_still_stop_a_merge_when_ci_is_green
FAILED tests/service/test_github_check_runs.py::test_an_app_without_checks_read_is_a_visible_failure_not_a_silent_wait
62 failed, 21 passed in 14.49s

```

Exit status: 1

MEASURED — M2-missing-ci-success

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_github_check_runs.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
.....................................................................F.. [ 86%]
.....F.....                                                              [100%]
=================================== FAILURES ===================================
_ test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged[nothing yet] _
tests/service/test_github_check_runs.py:341: in test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged
    assert host.posted == [] and host.merge_refused == 0
E   AssertionError: assert (['cmapi/check...'cmapi/check'] == []
E     
E     Left contains 3 more items, first extra item: 'cmapi/check'
E     Use -v to get more diff)
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:04:24.465413Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 162.4, "event": "http", "request_id": "cc1958ced59b41ab", "level": "info", "timestamp": "2026-11-13T14:04:24.681761Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:24.798905Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "error": "GitUnavailable: merge PR 1: 405 {\"message\":\"Required status check is expected\"}", "trace": "Traceback (most recent call last):\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/worker.py\", line 101, in run_one\n    handler(self.ctx, s, job)\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/jobs/pr_checks.py\", line 93, in pr_checks\n    merge_sha = ctx.git.merge(pr, head)\n                ^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/core/git/github.py\", line 196, in merge\n    raise GitUnavailable(f\"merge PR {pr.number}: {r.status_code} {r.text[:300]}\")\ncmapi.core.git.base.GitUnavailable: merge PR 1: 405 {\"message\":\"Required status check is expected\"}\n", "event": "job_failed", "level": "error", "timestamp": "2026-11-13T14:04:24.826944Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 2, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:24.871529Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 2, "error": "GitUnavailable: merge PR 1: 405 {\"message\":\"Required status check is expected\"}", "trace": "Traceback (most recent call last):\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/worker.py\", line 101, in run_one\n    handler(self.ctx, s, job)\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/jobs/pr_checks.py\", line 93, in pr_checks\n    merge_sha = ctx.git.merge(pr, head)\n                ^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/core/git/github.py\", line 196, in merge\n    raise GitUnavailable(f\"merge PR {pr.number}: {r.status_code} {r.text[:300]}\")\ncmapi.core.git.base.GitUnavailable: merge PR 1: 405 {\"message\":\"Required status check is expected\"}\n", "event": "job_failed", "level": "error", "timestamp": "2026-11-13T14:04:24.897858Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 3, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:24.941137Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 3, "error": "GitUnavailable: merge PR 1: 405 {\"message\":\"Required status check is expected\"}", "trace": "Traceback (most recent call last):\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/worker.py\", line 101, in run_one\n    handler(self.ctx, s, job)\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/jobs/pr_checks.py\", line 93, in pr_checks\n    merge_sha = ctx.git.merge(pr, head)\n                ^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/core/git/github.py\", line 196, in merge\n    raise GitUnavailable(f\"merge PR {pr.number}: {r.status_code} {r.text[:300]}\")\ncmapi.core.git.base.GitUnavailable: merge PR 1: 405 {\"message\":\"Required status check is expected\"}\n", "event": "job_failed", "level": "error", "timestamp": "2026-11-13T14:04:24.966020Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 17.2, "event": "http", "request_id": "80dc65a2752e48b3", "level": "info", "timestamp": "2026-11-13T14:04:25.059089Z"}
_____ test_ci_that_never_reports_fails_the_request_when_the_clock_runs_out _____
tests/service/test_github_check_runs.py:380: in test_ci_that_never_reports_fails_the_request_when_the_clock_runs_out
    assert view["status"] == "failed" and fake.prs[1]["state"] == "closed"
E   AssertionError: assert ('pr_open' == 'failed'
E     
E     - failed
E     + pr_open)
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:04:30.856546Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 154.2, "event": "http", "request_id": "ef116db5a2c44322", "level": "info", "timestamp": "2026-11-13T14:04:31.063920Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:31.176018Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "error": "GitUnavailable: merge PR 1: 405 {\"message\":\"Required status check is expected\"}", "trace": "Traceback (most recent call last):\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/worker.py\", line 101, in run_one\n    handler(self.ctx, s, job)\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/jobs/pr_checks.py\", line 93, in pr_checks\n    merge_sha = ctx.git.merge(pr, head)\n                ^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi/src/cmapi/core/git/github.py\", line 196, in merge\n    raise GitUnavailable(f\"merge PR {pr.number}: {r.status_code} {r.text[:300]}\")\ncmapi.core.git.base.GitUnavailable: merge PR 1: 405 {\"message\":\"Required status check is expected\"}\n", "event": "job_failed", "level": "error", "timestamp": "2026-11-13T14:04:31.204652Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 12.7, "event": "http", "request_id": "daa74b493ba24a2f", "level": "info", "timestamp": "2026-11-13T14:04:31.290344Z"}
=========================== short test summary info ============================
FAILED tests/service/test_github_check_runs.py::test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged[nothing yet]
FAILED tests/service/test_github_check_runs.py::test_ci_that_never_reports_fails_the_request_when_the_clock_runs_out
2 failed, 81 passed in 13.10s

```

Exit status: 1

MEASURED — M3-post-ci-on-github

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_github_check_runs.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
....................................................................FFFF [ 86%]
FFFF..FF...                                                              [100%]
=================================== FAILURES ===================================
___ test_green_from_actions_merges_and_the_worker_posts_only_the_cmapi_check ___
tests/service/test_github_check_runs.py:328: in test_green_from_actions_merges_and_the_worker_posts_only_the_cmapi_check
    assert host.posted == [CONTEXT_CMAPI], "the worker posted a context Actions owns"
E   AssertionError: the worker posted a context Actions owns
E   assert ['ci/kubeconf...'cmapi/check'] == ['cmapi/check']
E     
E     At index 0 diff: 'ci/kubeconform' != 'cmapi/check'
E     Left contains 2 more items, first extra item: 'ci/kyverno'
E     Use -v to get more diff
---------------------------- Captured stdout setup -----------------------------
migrated to head
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:04:56.229557Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 192.5, "event": "http", "request_id": "dc4e3c64b58f46f5", "level": "info", "timestamp": "2026-11-13T14:04:56.476234Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:56.591965Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 13.4, "event": "http", "request_id": "690044a5bbb44a35", "level": "info", "timestamp": "2026-11-13T14:04:56.706571Z"}
_ test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged[nothing yet] _
tests/service/test_github_check_runs.py:351: in test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged
    assert host.posted == [CONTEXT_CMAPI]
E   AssertionError: assert ['ci/kubeconf...'cmapi/check'] == ['cmapi/check']
E     
E     At index 0 diff: 'ci/kubeconform' != 'cmapi/check'
E     Left contains 2 more items, first extra item: 'ci/kyverno'
E     Use -v to get more diff
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:04:57.151417Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 164.9, "event": "http", "request_id": "504d6372de6f462e", "level": "info", "timestamp": "2026-11-13T14:04:57.368178Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:57.486820Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:57.530002Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:57.567613Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 13.4, "event": "http", "request_id": "90224a64fdeb4ddf", "level": "info", "timestamp": "2026-11-13T14:04:57.649493Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:57.676321Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 13.6, "event": "http", "request_id": "baaf04192b51410e", "level": "info", "timestamp": "2026-11-13T14:04:57.796840Z"}
_ test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged[one still running] _
tests/service/test_github_check_runs.py:351: in test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged
    assert host.posted == [CONTEXT_CMAPI]
E   AssertionError: assert ['ci/kubeconf...'cmapi/check'] == ['cmapi/check']
E     
E     At index 0 diff: 'ci/kubeconform' != 'cmapi/check'
E     Left contains 2 more items, first extra item: 'ci/kyverno'
E     Use -v to get more diff
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:04:58.090250Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 161.6, "event": "http", "request_id": "f194d8c7093d4b83", "level": "info", "timestamp": "2026-11-13T14:04:58.303691Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:58.427476Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:58.476238Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:58.510711Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 12.2, "event": "http", "request_id": "b69d21f6555b468f", "level": "info", "timestamp": "2026-11-13T14:04:58.590757Z"}
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:58.615267Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 14.8, "event": "http", "request_id": "3c6a16cd00c44f57", "level": "info", "timestamp": "2026-11-13T14:04:58.731618Z"}
____ test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[failure] ____
tests/service/test_github_check_runs.py:363: in test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr
    assert host.posted == [CONTEXT_CMAPI]
E   AssertionError: assert ['ci/kubeconf...'cmapi/check'] == ['cmapi/check']
E     
E     At index 0 diff: 'ci/kubeconform' != 'cmapi/check'
E     Left contains 2 more items, first extra item: 'ci/kyverno'
E     Use -v to get more diff
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:04:59.117400Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 199.7, "event": "http", "request_id": "f33d95caf8e047ba", "level": "info", "timestamp": "2026-11-13T14:04:59.378152Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:04:59.506894Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 13.0, "event": "http", "request_id": "fa6a00437e754e96", "level": "info", "timestamp": "2026-11-13T14:04:59.618589Z"}
___ test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[timed_out] ___
tests/service/test_github_check_runs.py:363: in test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr
    assert host.posted == [CONTEXT_CMAPI]
E   AssertionError: assert ['ci/kubeconf...'cmapi/check'] == ['cmapi/check']
E     
E     At index 0 diff: 'ci/kubeconform' != 'cmapi/check'
E     Left contains 2 more items, first extra item: 'ci/kyverno'
E     Use -v to get more diff
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:04:59.890609Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 206.0, "event": "http", "request_id": "472cf5646adc4d25", "level": "info", "timestamp": "2026-11-13T14:05:00.150674Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:05:00.257728Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 14.5, "event": "http", "request_id": "c57865adc0b74610", "level": "info", "timestamp": "2026-11-13T14:05:00.363133Z"}
___ test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[cancelled] ___
tests/service/test_github_check_runs.py:363: in test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr
    assert host.posted == [CONTEXT_CMAPI]
E   AssertionError: assert ['ci/kubeconf...'cmapi/check'] == ['cmapi/check']
E     
E     At index 0 diff: 'ci/kubeconform' != 'cmapi/check'
E     Left contains 2 more items, first extra item: 'ci/kyverno'
E     Use -v to get more diff
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:05:00.649235Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 206.9, "event": "http", "request_id": "c858c14581804f02", "level": "info", "timestamp": "2026-11-13T14:05:00.908145Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:05:01.025219Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 13.9, "event": "http", "request_id": "0b6dcd0231464b13", "level": "info", "timestamp": "2026-11-13T14:05:01.130055Z"}
____ test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[skipped] ____
tests/service/test_github_check_runs.py:363: in test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr
    assert host.posted == [CONTEXT_CMAPI]
E   AssertionError: assert ['ci/kubeconf...'cmapi/check'] == ['cmapi/check']
E     
E     At index 0 diff: 'ci/kubeconform' != 'cmapi/check'
E     Left contains 2 more items, first extra item: 'ci/kyverno'
E     Use -v to get more diff
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:05:01.410184Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 166.5, "event": "http", "request_id": "fd5785c3d6564acb", "level": "info", "timestamp": "2026-11-13T14:05:01.629629Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:05:01.745142Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 13.2, "event": "http", "request_id": "7b862f8f450a4042", "level": "info", "timestamp": "2026-11-13T14:05:01.852706Z"}
____ test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[neutral] ____
tests/service/test_github_check_runs.py:363: in test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr
    assert host.posted == [CONTEXT_CMAPI]
E   AssertionError: assert ['ci/kubeconf...'cmapi/check'] == ['cmapi/check']
E     
E     At index 0 diff: 'ci/kubeconform' != 'cmapi/check'
E     Left contains 2 more items, first extra item: 'ci/kyverno'
E     Use -v to get more diff
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:05:02.125147Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 162.3, "event": "http", "request_id": "39cb2fd305e644e0", "level": "info", "timestamp": "2026-11-13T14:05:02.339679Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:05:02.452466Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 12.7, "event": "http", "request_id": "a25037be71ba4112", "level": "info", "timestamp": "2026-11-13T14:05:02.555287Z"}
_______________ test_green_ci_does_not_excuse_a_head_that_moved ________________
tests/service/test_github_check_runs.py:395: in test_green_ci_does_not_excuse_a_head_that_moved
    assert host.posted == [CONTEXT_CMAPI]
E   AssertionError: assert ['ci/kubeconf...'cmapi/check'] == ['cmapi/check']
E     
E     At index 0 diff: 'ci/kubeconform' != 'cmapi/check'
E     Left contains 2 more items, first extra item: 'ci/kyverno'
E     Use -v to get more diff
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:05:04.397204Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 160.1, "event": "http", "request_id": "f82d98974f26443d", "level": "info", "timestamp": "2026-11-13T14:05:04.611215Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:05:04.728734Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 15.4, "event": "http", "request_id": "eb013b385fd241f2", "level": "info", "timestamp": "2026-11-13T14:05:04.859516Z"}
____ test_the_workers_own_validator_can_still_stop_a_merge_when_ci_is_green ____
tests/service/test_github_check_runs.py:406: in test_the_workers_own_validator_can_still_stop_a_merge_when_ci_is_green
    assert status(client, keys, rid)["status"] == "failed" and host.posted == [CONTEXT_CMAPI]
E   AssertionError: assert ('failed' == 'failed'
E     
E       failed and ['ci/kubeconf...'cmapi/check'] == ['cmapi/check']
E     
E     At index 0 diff: 'ci/kubeconform' != 'cmapi/check'
E     Left contains 2 more items, first extra item: 'ci/kyverno'
E     Use -v to get more diff)
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:05:05.153831Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 180.0, "event": "http", "request_id": "fe5776cd45a64e4e", "level": "info", "timestamp": "2026-11-13T14:05:05.386397Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:05:05.501096Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 12.8, "event": "http", "request_id": "519eb3d477cd4edc", "level": "info", "timestamp": "2026-11-13T14:05:05.603735Z"}
=========================== short test summary info ============================
FAILED tests/service/test_github_check_runs.py::test_green_from_actions_merges_and_the_worker_posts_only_the_cmapi_check
FAILED tests/service/test_github_check_runs.py::test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged[nothing yet]
FAILED tests/service/test_github_check_runs.py::test_while_ci_has_not_finished_the_request_waits_and_nothing_is_posted_or_merged[one still running]
FAILED tests/service/test_github_check_runs.py::test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[failure]
FAILED tests/service/test_github_check_runs.py::test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[timed_out]
FAILED tests/service/test_github_check_runs.py::test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[cancelled]
FAILED tests/service/test_github_check_runs.py::test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[skipped]
FAILED tests/service/test_github_check_runs.py::test_ci_that_did_not_pass_fails_the_request_and_closes_the_pr[neutral]
FAILED tests/service/test_github_check_runs.py::test_green_ci_does_not_excuse_a_head_that_moved
FAILED tests/service/test_github_check_runs.py::test_the_workers_own_validator_can_still_stop_a_merge_when_ci_is_green
10 failed, 73 passed in 13.68s

```

Exit status: 1

MEASURED — M4-ignore-approved-head

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_github_check_runs.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
........................................................................ [ 86%]
...........                                                              [100%]
83 passed in 12.82s

```

Exit status: 0

MEASURED — C7-sensitivity-before

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_review_r87_c7_sensitivity.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
____ test_named_moved_head_check_detects_removal_of_the_approved_head_guard ____
tests/service/test_review_r87_c7_sensitivity.py:21: in test_named_moved_head_check_detects_removal_of_the_approved_head_guard
    with pytest.raises(AssertionError):
E   Failed: DID NOT RAISE <class 'AssertionError'>
---------------------------- Captured stdout setup -----------------------------
migrated to head
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:05:47.055350Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 187.9, "event": "http", "request_id": "f65d694c3a5a451b", "level": "info", "timestamp": "2026-11-13T14:05:47.296301Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:05:47.479372Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 14.5, "event": "http", "request_id": "05787e4297224abd", "level": "info", "timestamp": "2026-11-13T14:05:47.599917Z"}
=========================== short test summary info ============================
FAILED tests/service/test_review_r87_c7_sensitivity.py::test_named_moved_head_check_detects_removal_of_the_approved_head_guard
1 failed in 1.56s

```

Exit status: 1

MEASURED — C5-main-semantics

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_review_r87_c5_c8.py -k no_external_ci -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
............                                                             [100%]
12 passed, 13 deselected in 8.71s

```

Exit status: 0

MEASURED — C5-head-semantics

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_review_r87_c5_c8.py -k no_external_ci -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
............                                                             [100%]
12 passed, 13 deselected in 9.22s

```

Exit status: 0

MEASURED — C6-C8-after

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_review_r87_c5_c8.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
......................                                                   [100%]
22 passed in 16.82s

```

Exit status: 0

MEASURED — C7-sensitivity-after

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_review_r87_c7_sensitivity.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
.                                                                        [100%]
1 passed in 1.44s

```

Exit status: 0

MEASURED — M4-after-test-fix

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_github_check_runs.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text

==================================== ERRORS ====================================
___________ ERROR collecting tests/service/test_github_check_runs.py ___________
In test_green_ci_does_not_excuse_a_head_that_moved: function already takes an argument 'same_tree' with a default value
=========================== short test summary info ============================
ERROR tests/service/test_github_check_runs.py - Failed: In test_green_ci_does...
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.30s

```

Exit status: 2

MEASURED — C7-final-sensitivity-before

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_review_r87_c7_sensitivity.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
____ test_named_moved_head_check_detects_removal_of_the_approved_head_guard ____
tests/service/test_review_r87_c7_sensitivity.py:23: in test_named_moved_head_check_detects_removal_of_the_approved_head_guard
    with pytest.raises(AssertionError):
E   Failed: DID NOT RAISE <class 'AssertionError'>
---------------------------- Captured stdout setup -----------------------------
migrated to head
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:09:47.764713Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 235.4, "event": "http", "request_id": "e83631c9bc6d410c", "level": "info", "timestamp": "2026-11-13T14:09:48.053753Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:09:48.232441Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 19.1, "event": "http", "request_id": "0d1373f3be2d4ea3", "level": "info", "timestamp": "2026-11-13T14:09:48.364404Z"}
=========================== short test summary info ============================
FAILED tests/service/test_review_r87_c7_sensitivity.py::test_named_moved_head_check_detects_removal_of_the_approved_head_guard
1 failed in 1.62s

```

Exit status: 1

MEASURED — M4-after-corrected-test-fix

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_github_check_runs.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
........................................................................ [ 85%]
.......F....                                                             [100%]
=================================== FAILURES ===================================
____ test_green_ci_does_not_excuse_a_head_that_moved[same-files-new-commit] ____
tests/service/test_github_check_runs.py:404: in test_green_ci_does_not_excuse_a_head_that_moved
    assert status(client, keys, rid)["status"] == "failed" and host.merge_refused == 0
E   AssertionError: assert ('merged' == 'failed'
E     
E     - failed
E     + merged)
---------------------------- Captured stdout setup -----------------------------
{"instance": "nonprod", "issuer": "https://keycloak.test/realms/cmapi", "audience": "cmapi-nonprod", "version": "0.2.0", "commit": "unknown", "clusters": {"CRC": "connected"}, "event": "startup", "level": "info", "timestamp": "2026-11-13T14:10:15.779484Z"}
{"method": "POST", "route": "/api/v1/clusters/{cluster_id}/namespaces", "status": 202, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 161.8, "event": "http", "request_id": "4dc2ea841c51405f", "level": "info", "timestamp": "2026-11-13T14:10:15.993451Z"}
----------------------------- Captured stdout call -----------------------------
{"job": 2, "kind": "pr_checks", "request_id": "req-20261113-0001", "attempt": 1, "worker": "w", "event": "job_start", "level": "info", "timestamp": "2026-11-13T14:10:16.103404Z"}
{"method": "GET", "route": "/api/v1/requests/{request_id}", "status": 200, "caller_sub": "sub-ola", "client": "cmapi-portal", "ms": 13.0, "event": "http", "request_id": "55f1fc2465c247f0", "level": "info", "timestamp": "2026-11-13T14:10:16.215139Z"}
=========================== short test summary info ============================
FAILED tests/service/test_github_check_runs.py::test_green_ci_does_not_excuse_a_head_that_moved[same-files-new-commit]
1 failed, 83 passed in 13.93s

```

Exit status: 1

MEASURED — patch validation

```sh
/usr/bin/patch --dry-run -p1 --fuzz=0 -d /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patch-validation/c6 -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patches/R87-C6.patch
```

Full output:

```text
patching file 'cmapi/src/cmapi/core/git/github.py'
patching file 'cmapi/tests/service/test_github_check_runs.py'
patching file 'cmapi/tests/service/test_review_r87_c5_c8.py'
```

Exit status: 0

MEASURED — patch validation

```sh
/usr/bin/patch -p1 --fuzz=0 -d /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patch-validation/c6 -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patches/R87-C6.patch
```

Full output:

```text
patching file 'cmapi/src/cmapi/core/git/github.py'
patching file 'cmapi/tests/service/test_github_check_runs.py'
patching file 'cmapi/tests/service/test_review_r87_c5_c8.py'
```

Exit status: 0

MEASURED — patch validation

```sh
/usr/bin/patch --dry-run -p1 --fuzz=0 -d /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patch-validation/c7 -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patches/R87-C7.patch
```

Full output:

```text
patching file 'cmapi/tests/service/test_github_check_runs.py'
patching file 'cmapi/tests/service/test_review_r87_c7_sensitivity.py'
```

Exit status: 0

MEASURED — patch validation

```sh
/usr/bin/patch -p1 --fuzz=0 -d /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patch-validation/c7 -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patches/R87-C7.patch
```

Full output:

```text
patching file 'cmapi/tests/service/test_github_check_runs.py'
patching file 'cmapi/tests/service/test_review_r87_c7_sensitivity.py'
```

Exit status: 0

MEASURED — patch validation

```sh
/usr/bin/patch --dry-run -p1 --fuzz=0 -d /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patch-validation/combined -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patches/R87-C6.patch
```

Full output:

```text
patching file 'cmapi/src/cmapi/core/git/github.py'
patching file 'cmapi/tests/service/test_github_check_runs.py'
patching file 'cmapi/tests/service/test_review_r87_c5_c8.py'
```

Exit status: 0

MEASURED — patch validation

```sh
/usr/bin/patch -p1 --fuzz=0 -d /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patch-validation/combined -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patches/R87-C6.patch
```

Full output:

```text
patching file 'cmapi/src/cmapi/core/git/github.py'
patching file 'cmapi/tests/service/test_github_check_runs.py'
patching file 'cmapi/tests/service/test_review_r87_c5_c8.py'
```

Exit status: 0

MEASURED — patch validation

```sh
/usr/bin/patch --dry-run -p1 --fuzz=0 -d /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patch-validation/combined -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patches/R87-C7.patch
```

Full output:

```text
patching file 'cmapi/tests/service/test_github_check_runs.py'
patching file 'cmapi/tests/service/test_review_r87_c7_sensitivity.py'
```

Exit status: 0

MEASURED — patch validation

```sh
/usr/bin/patch -p1 --fuzz=0 -d /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patch-validation/combined -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/patches/R87-C7.patch
```

Full output:

```text
patching file 'cmapi/tests/service/test_github_check_runs.py'
patching file 'cmapi/tests/service/test_review_r87_c7_sensitivity.py'
```

Exit status: 0

MEASURED — Combined patches reproduce every repaired/new file byte-for-byte; pr_checks.py is byte-identical to the exported head.

MEASURED — C7-final-sensitivity-after

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_review_r87_c7_sensitivity.py -q -W ignore -p no:cacheprovider --tb=short
```

Full output:

```text
.                                                                        [100%]
1 passed in 1.42s

```

Exit status: 0

MEASURED — AST-delimited byte comparison: GitHub code outside _run_state is identical to report/original, including the C3 check-suite implementation.

MEASURED — final

Working directory: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/head/cmapi`

```sh
/usr/bin/env PATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONPATH=src:tests/service CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_github_check_runs.py tests/service/test_review_r87_c3.py tests/service/test_review_r87_c5_c8.py tests/service/test_review_r87_c7_sensitivity.py -q -W ignore -p no:cacheprovider
```

Full output:

```text
........................................................................ [ 66%]
....................................                                     [100%]
108 passed in 30.93s

```

Exit status: 0

MEASURED — Mutation/comparison setup commands, in working directory `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87`. The pytest commands and their entire stdout/stderr are recorded above under the corresponding run labels. Each setup wrapper restores the bytes in a finally block. The M1–M4 source edits are also retained as report/M1-ignore-check-runs.patch, report/M2-missing-ci-success.patch, report/M3-post-ci-on-github.patch and report/M4-ignore-approved-head.patch.

MEASURED — Setup invocation:

```sh
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/mutate.py M1-ignore-check-runs
```

MEASURED — exit 1; 62 failed, 21 passed; source restored.

MEASURED — Setup invocation:

```sh
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/mutate.py M2-missing-ci-success
```

MEASURED — exit 1; 2 failed, 81 passed; source restored.

MEASURED — Setup invocation:

```sh
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/mutate.py M3-post-ci-on-github
```

MEASURED — exit 1; 10 failed, 73 passed; source restored.

MEASURED — Setup invocation:

```sh
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/mutate.py M4-ignore-approved-head
```

MEASURED — exit 0; 83 passed; source restored.

MEASURED — Setup invocation:

```sh
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/compare_main.py
```

MEASURED — exit 0; 12 passed, 13 deselected; exported head restored.

MEASURED — Setup invocation:

```sh
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/verify_c7_before.py
```

MEASURED — exit 1; 1 failed; repaired test restored.

MEASURED — Setup invocation:

```sh
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/mutate.py M4-ignore-approved-head M4-after-corrected-test-fix
```

MEASURED — exit 1; 1 failed, 83 passed; source restored.

MEASURED — Setup invocation:

```sh
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python report/verify_patches.py
```

MEASURED — exit 0; all dry-runs and applications passed; combined files identical.

MEASURED — Main handler reconstruction command (the target copy was initialized from the exported head):

```sh
/usr/bin/patch -R -p1 --fuzz=0 -d report/main -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/review-87/report/main-pr-checks-reverse.patch
```

MEASURED — Full output: `patching file 'cmapi/src/cmapi/jobs/pr_checks.py'`; exit status 0.

MEASURED — The early M4-after-test-fix run exited 2 at collection because pytest rejects defaults on parametrized arguments. It is retained above as a failed audit attempt, and is excluded from the killed-mutant count. M4-after-corrected-test-fix collected successfully and failed specifically because the mutant merged the unapproved new SHA.
